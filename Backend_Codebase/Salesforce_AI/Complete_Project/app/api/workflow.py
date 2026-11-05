"""Workflow API: task lifecycle (complete/decline/block/progress/split),
approvals, assignment batch confirmation, inbound webhook + triage,
incidents, why-traces, digests and the sweep trigger."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.permissions import can_reassign_task
from app.core.constants import (
    ActionItemStatus,
    ApprovalStatus,
    AssignmentStatus,
    CompletionMethod,
    DeclineReason,
    DeliverableSource,
    EventType,
    InboundIntent,
    IncidentStatus,
    Phase,
    TaskPriority,
    TaskSource,
)
from app.core.context import OrgContext
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.database import get_db
from app.engines import (
    approval_engine,
    assignment_engine,
    assistant_engine,
    document_engine,
    events,
    inbound_engine,
    knowledge_engine,
    sync_engine,
)
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.comms import Approval, InboundMessage
from app.models.project import ClientCommitment, Project
from app.models.user import User
from app.models.work import Assignment, Incident

router = APIRouter(tags=["workflow"])


async def _get_task(db: AsyncSession, ctx: OrgContext, task_id: str) -> ActionItem:
    task = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == ctx.org_id, ActionItem.id == task_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise NotFoundError("Task not found")
    return task


def _require_own_task(ctx: OrgContext, task: ActionItem, action: str) -> None:
    """Agents act on their own work; leads and admins act across the team.

    F51: this router enforced ownership on **one action out of twenty-three**.
    `/decline` checked the assignee inline and nothing else checked anything, so
    a non-assignee blocked another user's task straight through the UI —
    device-proven, 200 OK, `progress_events.actor` recording someone who did not
    own the work.

    The rule already existed: `can_reassign_task` implements the doc §13 matrix
    ("Sales Agent — own only; Sales Lead — whole team; Admin — yes") and had two
    callers, both on the *reassign* path. This reuses it rather than inventing a
    second rule. Roles §4.6 states the prohibition directly: an operations agent
    "cannot assign or **move** other people's tasks".

    ⚠ `require_permission("manage_tasks")` is NOT a substitute and was rejected
    on evidence: that permission grants all five org roles, so it would not have
    stopped the case that was actually observed. The missing control is
    ownership, not role.

    `/complete` and `/progress` are deliberately NOT gated — reporting that work
    is finished is legitimate teamwork, and Roles §4.6 puts both under "their
    tasks" without prohibiting the cover case. That is a product decision taken
    with the project owner, not an oversight.
    """
    if not can_reassign_task(ctx.role, ctx.user_id, task.assignee_id, same_team=True):
        raise PermissionDeniedError(
            f"{task.title} is assigned to someone else — you cannot {action} it. "
            f"Ask the assignee, or ask your lead to reassign it to you."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class CompleteRequest(BaseModel):
    result_note: str | None = None
    completion_method: str = CompletionMethod.IN_APP.value
    deliverable_type: str | None = None
    deliverable_title: str | None = None
    deliverable_content_md: str | None = None
    deliverable_file_path: str | None = None


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    body: CompleteRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Finish a task any way you like — in-app, by voice, or by uploading the
    artifact you made outside. Both are first-class (Workflow 4 B.3)."""
    task = await _get_task(db, ctx, task_id)
    if task.status == ActionItemStatus.DONE.value:
        return {"ok": True, "already_done": True}
    task.status = ActionItemStatus.DONE.value
    task.completed_at = utcnow()
    task.result_note = body.result_note
    task.completion_method = body.completion_method
    task.progress_percent = 100
    deliverable_id = None
    if body.deliverable_type:
        deliverable = await document_engine.add_deliverable(
            db, org_id=ctx.org_id, project_id=task.project_id or "",
            dtype=body.deliverable_type,
            title=body.deliverable_title or task.title,
            content_md=body.deliverable_content_md,
            file_path=body.deliverable_file_path,
            source=(
                DeliverableSource.MANUAL_UPLOAD.value
                if body.completion_method == CompletionMethod.MANUAL_UPLOAD.value
                else DeliverableSource.AI_GENERATED.value
            ),
            uploaded_by=ctx.user_id,
            linked_action_item_id=task.id,
            status="internal_review",
        )
        deliverable_id = deliverable.id
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.TASK_DONE.value,
        project_id=task.project_id, entity_type="action_item", entity_id=task.id,
        actor=ctx.user_id,
        details={"completion_method": body.completion_method,
                 "note": body.result_note or ""},
    )
    await db.commit()
    return {"ok": True, "deliverable_id": deliverable_id}


class DeclineRequest(BaseModel):
    reason: str = DeclineReason.OTHER.value
    note: str | None = None


@router.post("/tasks/{task_id}/decline")
async def decline_task(
    task_id: str,
    body: DeclineRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, ctx, task_id)
    if task.assignee_id != ctx.user_id:
        raise PermissionDeniedError("Only the assignee can decline a task")
    user = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one()
    assignment = await assignment_engine.decline_task(
        db, org_id=ctx.org_id, task=task, user=user,
        reason_code=body.reason, note=body.note,
    )
    await db.commit()
    return {
        "ok": True,
        "reassigned_to": task.assignee_id,
        "reason": task.assignment_reason,
        "needs_lead": assignment is None or task.assignee_id is None,
    }


class BlockRequest(BaseModel):
    reason: str = Field(min_length=2)
    # Optional: the colleague this waits on, when the app lets the person pick
    # one. Otherwise the Sync Engine looks for a name in `reason`.
    blocked_on_user_id: str | None = None


@router.post("/tasks/{task_id}/block")
async def block_task(
    task_id: str,
    body: BlockRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """'I'm blocked' stops the nudge ladder and starts the right machinery —
    chase the blocker, not the blocked (Workflow 11)."""
    task = await _get_task(db, ctx, task_id)
    _require_own_task(ctx, task, "block")
    task.blocked = True
    task.blocked_reason = body.reason
    task.reminder_level = 0
    await sync_engine.cancel_reminders(db, ctx.org_id, "action_item", task.id)
    details = {"reason": body.reason}
    if body.blocked_on_user_id:
        details["blocked_on_user_id"] = body.blocked_on_user_id
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.TASK_BLOCKED.value,
        project_id=task.project_id, entity_type="action_item", entity_id=task.id,
        actor=ctx.user_id, details=details,
    )
    # The reaction above runs in this session and has decided who (if anyone)
    # this waits on; say so, so the app can tell the person "Siva was told".
    blocked_on = None
    if task.blocked_on_user_id:
        name = (
            await db.execute(select(User.name).where(User.id == task.blocked_on_user_id))
        ).scalar_one_or_none()
        blocked_on = {"id": task.blocked_on_user_id, "name": name}
    await db.commit()
    return {"ok": True, "blocked_on": blocked_on}


@router.post("/tasks/{task_id}/unblock")
async def unblock_task(
    task_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, ctx, task_id)
    _require_own_task(ctx, task, "unblock")
    task.blocked = False
    task.blocked_reason = None
    task.blocked_on_user_id = None
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.TASK_UNBLOCKED.value,
        project_id=task.project_id, entity_type="action_item", entity_id=task.id,
        actor=ctx.user_id,
    )
    await db.commit()
    return {"ok": True}


class ProgressRequest(BaseModel):
    percent: int = Field(ge=0, le=100)
    note: str | None = None


@router.post("/tasks/{task_id}/progress")
async def update_progress(
    task_id: str,
    body: ProgressRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, ctx, task_id)
    task.progress_percent = body.percent
    if task.status == ActionItemStatus.OPEN.value and body.percent > 0:
        task.status = ActionItemStatus.IN_PROGRESS.value
    if body.note:
        task.result_note = body.note
    await db.commit()
    return {"ok": True}


class NewDateRequest(BaseModel):
    new_due: datetime
    reason: str | None = None


@router.post("/tasks/{task_id}/new-date")
async def propose_new_date(
    task_id: str,
    body: NewDateRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """'Give new date' from the nudge — the engine checks the ripple before
    accepting: a break of a dependent task or client commitment routes the
    change to the phase lead instead (Workflow 10.3)."""
    task = await _get_task(db, ctx, task_id)
    _require_own_task(ctx, task, "re-date")
    breaks: list[str] = []
    # Dependent tasks with due dates before the new date lose their slack.
    dependents = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == ctx.org_id,
                ActionItem.status.in_(
                    [ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value]
                ),
            )
        )
    ).scalars().all()
    for d in dependents:
        if task.id in (d.depends_on_ids or []) and d.due_date and d.due_date <= body.new_due:
            breaks.append(f"dependent task '{d.title}' is due {d.due_date:%d %b}")
    if task.client_commitment_id:
        commitment = (
            await db.execute(
                select(ClientCommitment).where(
                    ClientCommitment.id == task.client_commitment_id
                )
            )
        ).scalar_one_or_none()
        if commitment is not None and commitment.due_date and commitment.due_date < body.new_due:
            breaks.append(
                f"client commitment '{commitment.text}' is due {commitment.due_date:%d %b}"
            )
    if breaks:
        from app.core.constants import PHASE_LEAD_ROLE, Role
        from app.engines.common import find_role_user
        from app.services.notification_service import notify

        lead_role = PHASE_LEAD_ROLE.get(task.phase or "", Role.OPERATIONS_LEAD.value)
        lead = await find_role_user(db, ctx.org_id, lead_role)
        if lead is not None:
            await notify(
                db, org_id=ctx.org_id, user_id=lead.id,
                title=f"Date change needs your yes: {task.title}",
                body=(
                    f"{ctx.name} asks {body.new_due:%d %b} "
                    f"(reason: {body.reason or '—'}) but it breaks: "
                    + "; ".join(breaks)
                ),
                kind="approval_waiting", entity_type="action_item", entity_id=task.id,
            )
        await db.commit()
        return {"accepted": False, "routed_to_lead": True, "breaks": breaks}
    old = task.due_date
    task.due_date = body.new_due
    task.reminder_level = 0
    await sync_engine.cancel_reminders(db, ctx.org_id, "action_item", task.id)
    from app.services import audit_service

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="task.redated",
        entity_type="action_item", entity_id=task.id,
        detail={"from": old.isoformat() if old else None,
                "to": body.new_due.isoformat(), "reason": body.reason},
    )
    await db.commit()
    return {"accepted": True, "breaks": []}


class SplitRequest(BaseModel):
    parts: list[dict] = Field(min_length=2)  # [{"title": ..., "assignee_id": ...?}]


@router.post("/tasks/{task_id}/split")
async def split_task(
    task_id: str,
    body: SplitRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Split into linked children (Workflow 16.5): parent kept, children carry
    parent_item_id, second part depends on the first."""
    task = await _get_task(db, ctx, task_id)
    _require_own_task(ctx, task, "split")
    children = []
    previous_id: str | None = None
    for part in body.parts:
        child = ActionItem(
            org_id=ctx.org_id, lead_id=task.lead_id, project_id=task.project_id,
            title=part["title"], phase=task.phase,
            required_skill=part.get("required_skill", task.required_skill),
            priority=task.priority, due_date=task.due_date,
            visible_to_client=task.visible_to_client,
            source=task.source, status=ActionItemStatus.OPEN.value,
            parent_item_id=task.id, created_by=ctx.user_id,
            depends_on_ids=[previous_id] if previous_id else [],
        )
        db.add(child)
        await db.flush()
        if part.get("assignee_id"):
            child.assignee_id = part["assignee_id"]
            child.assigned_by = ctx.user_id
            child.assignment_reason = f"Split by {ctx.name}"
            db.add(
                Assignment(
                    org_id=ctx.org_id, action_item_id=child.id,
                    to_user_id=child.assignee_id, assigned_by=ctx.user_id,
                    reason=child.assignment_reason,
                    status=AssignmentStatus.ACCEPTED.value, decided_at=utcnow(),
                )
            )
        else:
            await assignment_engine.assign_task(
                db, org_id=ctx.org_id, task=child, notify_assignee=True,
                assigned_by=ctx.user_id,
            )
        previous_id = child.id
        children.append({"id": child.id, "title": child.title,
                         "assignee_id": child.assignee_id})
    task.status = ActionItemStatus.SUPERSEDED.value
    task.superseded_by = children[0]["id"] if children else None
    await db.commit()
    return {"children": children}


class VendorPromiseRequest(BaseModel):
    vendor_name: str
    promised_date: datetime
    chase_contact_user_id: str | None = None


@router.post("/tasks/{task_id}/vendor-promise")
async def record_vendor_promise(
    task_id: str,
    body: VendorPromiseRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, ctx, task_id)
    _require_own_task(ctx, task, "record a vendor promise on")
    task.external_wait = {
        "vendor_name": body.vendor_name,
        "promised_date": body.promised_date.isoformat(),
        "chase_contact": body.chase_contact_user_id or ctx.user_id,
    }
    await db.commit()
    return {"ok": True}


class VendorSlipRequest(BaseModel):
    new_promised_date: datetime
    note: str | None = None


@router.post("/tasks/{task_id}/vendor-slip")
async def record_vendor_slip(
    task_id: str,
    body: VendorSlipRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, ctx, task_id)
    _require_own_task(ctx, task, "record a vendor slip on")
    if not task.external_wait:
        raise ValidationFailedError("This task has no vendor promise recorded")
    wait = dict(task.external_wait)
    wait["promised_date"] = body.new_promised_date.isoformat()
    task.external_wait = wait
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.VENDOR_SLIP.value,
        project_id=task.project_id, entity_type="action_item", entity_id=task.id,
        actor=ctx.user_id,
        details={"new_promised_date": body.new_promised_date.isoformat(),
                 "note": body.note or ""},
    )
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Approvals
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/approvals")
async def list_approvals(
    status: str = "pending",
    mine: bool = True,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Approval).where(Approval.org_id == ctx.org_id)
    if status != "all":
        stmt = stmt.where(Approval.status == status)
    if mine:
        stmt = stmt.where(
            (Approval.requested_from_user_id == ctx.user_id)
            | (Approval.joint_with_user_id == ctx.user_id)
        )
    rows = (await db.execute(stmt.order_by(Approval.requested_at.desc()))).scalars().all()
    return [
        {
            "id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id,
            "project_id": a.project_id, "stage": a.stage, "status": a.status,
            "reason": a.reason, "recommendation": a.recommendation,
            "joint_with_user_id": a.joint_with_user_id,
            "joint_status": a.joint_status,
            "bundled_entities": a.bundled_entities,
            "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        }
        for a in rows
    ]


class DecideRequest(BaseModel):
    approve: bool
    note: str | None = None
    # Additive (2026-08-03, F30): approving an outbound message that still
    # carries "[Name]"-style blanks is refused unless the approver says, in so
    # many words, that they mean to send it as it stands. Absent = false = the
    # safe answer, so an older client is protected rather than broken.
    allow_blanks: bool = False


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    body: DecideRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    approval = (
        await db.execute(
            select(Approval).where(
                Approval.org_id == ctx.org_id, Approval.id == approval_id
            )
        )
    ).scalar_one_or_none()
    if approval is None:
        raise NotFoundError("Approval not found")
    if ctx.user_id not in (approval.requested_from_user_id, approval.joint_with_user_id):
        raise PermissionDeniedError("This approval is not addressed to you")
    if ctx.user_id == approval.joint_with_user_id:
        # Joint second slot: open while their own slot is undecided and the
        # approval as a whole hasn't been rejected/expired.
        if approval.joint_status not in (None, ApprovalStatus.PENDING.value):
            raise ConflictError("You have already decided this approval")
        if approval.status not in (
            ApprovalStatus.PENDING.value, ApprovalStatus.APPROVED.value,
        ):
            raise ConflictError(f"Approval is already '{approval.status}'")
    elif approval.status != ApprovalStatus.PENDING.value:
        # Primary slot: one decision only — a double-tap must never re-decide.
        raise ConflictError(f"Approval is already '{approval.status}'")
    result = await approval_engine.decide(
        db, org_id=ctx.org_id, approval_id=approval.id,
        user_id=ctx.user_id, approve=body.approve, note=body.note,
        allow_blanks=body.allow_blanks,
    )
    from app.services import audit_service

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="approval.approved" if body.approve else "approval.rejected",
        entity_type="approval", entity_id=approval.id,
        detail={"note": body.note},
    )
    await db.commit()
    return {
        "id": result.id, "status": result.status, "stage": result.stage,
        "joint_status": result.joint_status,
        "chained_next": result.id != approval.id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Assignment batch confirmation (lead_confirm mode)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/assignments/proposed")
async def proposed_assignments(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Assignment)
            .where(
                Assignment.org_id == ctx.org_id,
                Assignment.status == AssignmentStatus.PROPOSED.value,
            )
            .order_by(Assignment.created_at)
        )
    ).scalars().all()
    tasks = {
        t.id: t for t in (
            await db.execute(
                select(ActionItem).where(
                    ActionItem.org_id == ctx.org_id,
                    ActionItem.id.in_({a.action_item_id for a in rows} or {""}),
                )
            )
        ).scalars().all()
    }
    # Which client each assignment is for (2 Oct 2026), so a lead confirming
    # the batch can tell one client's work from another's. Same rule as the
    # Home briefing: the task's own client, else its project's client.
    from app.models.lead import Lead

    projects = dict(
        (await db.execute(
            select(Project.id, Project.name).where(
                Project.org_id == ctx.org_id,
                Project.id.in_({t.project_id for t in tasks.values() if t.project_id}
                               or {""}))
        )).all()
    )
    project_leads = dict(
        (await db.execute(
            select(Project.id, Project.lead_id).where(
                Project.org_id == ctx.org_id, Project.id.in_(set(projects) or {""}))
        )).all()
    )
    task_lead = {t.id: t.lead_id or project_leads.get(t.project_id)
                 for t in tasks.values()}
    lead_names = dict(
        (await db.execute(
            select(Lead.id, Lead.name).where(
                Lead.org_id == ctx.org_id,
                Lead.id.in_({v for v in task_lead.values() if v} or {""}))
        )).all()
    )
    out = []
    for a in rows:
        task = tasks.get(a.action_item_id)
        lead_id = task_lead.get(task.id) if task else None
        out.append(
            {
                "id": a.id, "action_item_id": a.action_item_id,
                "task_title": task.title if task else None,
                "phase": task.phase if task else None,
                "to_user_id": a.to_user_id, "reason": a.reason,
                # Additive (2 Oct 2026): an older app ignores these.
                "lead_id": lead_id if lead_id in lead_names else None,
                "lead_name": lead_names.get(lead_id) if lead_id else None,
                "project_id": task.project_id if task else None,
                "project_name": projects.get(task.project_id) if task else None,
                "due_date": (task.due_date.isoformat()
                             if task and task.due_date else None),
            }
        )
    return out


class ConfirmBatchRequest(BaseModel):
    assignment_ids: list[str]
    overrides: dict[str, str] = Field(default_factory=dict)


@router.post("/assignments/confirm-batch")
async def confirm_batch(
    body: ConfirmBatchRequest,
    ctx: OrgContext = Depends(require_permission("confirm_assignments")),
    db: AsyncSession = Depends(get_db),
):
    """One screen, all proposed assignments — confirm-all or change any.
    Recorded as assignments.status changes, never approvals rows.

    Lead-only (F51). `lead_confirm` mode exists precisely so a *lead* signs off
    the batch before anyone is notified; until this gate existed, any org member
    could confirm the whole organisation's assignments, and an operations agent
    was being offered the card on his own Home screen."""
    rows = await assignment_engine.confirm_batch(
        db, org_id=ctx.org_id, assignment_ids=body.assignment_ids,
        confirmed_by=ctx.user_id, overrides=body.overrides,
    )
    await db.commit()
    return {"confirmed": len(rows)}


# ─────────────────────────────────────────────────────────────────────────────
# Inbound webhook + triage
# ─────────────────────────────────────────────────────────────────────────────


class InboundRequest(BaseModel):
    channel: str = "email"
    from_address: str
    to_address: str | None = None
    subject: str | None = None
    body: str


@router.post("/inbound/ingest")
async def ingest_inbound(
    payload: InboundRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """The inbound webhook (also the dry-run entry). Voice notes are
    transcribed before reaching this text form."""
    msg = await inbound_engine.ingest(
        db, org_id=ctx.org_id, channel=payload.channel,
        from_address=payload.from_address, to_address=payload.to_address,
        subject=payload.subject, body=payload.body,
    )
    await db.commit()
    return {
        "id": msg.id, "status": msg.status, "intent": msg.intent,
        "change_type": msg.change_type, "sentiment": msg.sentiment,
        "summary": msg.ai_summary,
        "matched_project_id": msg.matched_project_id,
        "extracted_points": msg.extracted_points,
        "needs_human_reason": msg.needs_human_reason,
    }


@router.get("/inbound/triage")
async def triage_queue(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(InboundMessage).where(
                InboundMessage.org_id == ctx.org_id,
                InboundMessage.status.in_(["triage", "needs_human"]),
            )
        )
    ).scalars().all()
    return [
        {
            "id": m.id, "channel": m.channel, "from_address": m.from_address,
            "subject": m.subject, "body": m.body[:500], "status": m.status,
            "reason": m.needs_human_reason, "summary": m.ai_summary,
            # The AI's own reading of the message. Additive (2026-07-29): the
            # triage screen offers "set intent", and a picker that cannot show
            # the guess it is overwriting is a blind write. The matched ids let
            # a client tell which client the message belongs to without a
            # second round trip — the reply route needs it to scope the
            # assistant. There is deliberately no confidence: the model never
            # records one, and inventing a number would be a lie.
            "intent": m.intent,
            "change_type": m.change_type,
            "matched_lead_id": m.matched_lead_id,
            "matched_project_id": m.matched_project_id,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


class TriageResolveRequest(BaseModel):
    contact_id: str | None = None
    mark_processed: bool = True
    note: str | None = None
    # Additive (2026-07-29): the human's correction of the AI's reading, and
    # the project this message actually belongs to. Both optional — omit them
    # and this endpoint behaves exactly as it did before.
    intent: str | None = None
    project_id: str | None = None


@router.post("/inbound/{message_id}/resolve")
async def resolve_triage(
    message_id: str,
    body: TriageResolveRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    msg = (
        await db.execute(
            select(InboundMessage).where(
                InboundMessage.org_id == ctx.org_id, InboundMessage.id == message_id
            )
        )
    ).scalar_one_or_none()
    if msg is None:
        raise NotFoundError("Inbound message not found")
    if body.contact_id:
        from app.models.lead import Contact

        contact = (
            await db.execute(
                select(Contact).where(
                    Contact.org_id == ctx.org_id, Contact.id == body.contact_id
                )
            )
        ).scalar_one_or_none()
        if contact is None:
            raise NotFoundError("Contact not found")
        msg.matched_contact_id = contact.id
        msg.matched_lead_id = contact.lead_id
    if body.intent is not None:
        # A human correcting the AI. Validated against the vocabulary the
        # engines route on — an invented intent would silently route nowhere.
        allowed = {i.value for i in InboundIntent}
        if body.intent not in allowed:
            raise ValidationFailedError(
                f"Unknown intent '{body.intent}'. Expected one of: "
                + ", ".join(sorted(allowed))
            )
        msg.intent = body.intent
    if body.project_id is not None:
        project = (
            await db.execute(
                select(Project).where(
                    Project.org_id == ctx.org_id, Project.id == body.project_id
                )
            )
        ).scalar_one_or_none()
        if project is None:
            raise NotFoundError("Project not found")
        msg.matched_project_id = project.id
    if body.mark_processed:
        msg.status = "processed"
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Incidents
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/incidents")
async def list_incidents(
    project_id: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Incident).where(Incident.org_id == ctx.org_id)
    if project_id:
        stmt = stmt.where(Incident.project_id == project_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": i.id, "project_id": i.project_id, "severity": i.severity,
            "description": i.description, "status": i.status,
            "owner_user_id": i.owner_user_id, "fix_task_ids": i.fix_task_ids,
            "lesson": i.lesson,
        }
        for i in rows
    ]


class IncidentFixRequest(BaseModel):
    fix_tasks: list[dict] = Field(default_factory=list)
    # [{"title", "assignee_id"?, "due_in_days"?, "priority"?}]


@router.post("/incidents/{incident_id}/fix-tasks")
async def create_fix_tasks(
    incident_id: str,
    body: IncidentFixRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    incident = (
        await db.execute(
            select(Incident).where(
                Incident.org_id == ctx.org_id, Incident.id == incident_id
            )
        )
    ).scalar_one_or_none()
    if incident is None:
        raise NotFoundError("Incident not found")
    ids = list(incident.fix_task_ids or [])
    created = []
    for spec in body.fix_tasks:
        task = ActionItem(
            org_id=ctx.org_id, project_id=incident.project_id,
            title=spec["title"],
            phase=Phase.DELIVERY.value,
            priority=spec.get("priority", TaskPriority.P1.value),
            due_date=utcnow() + timedelta(days=int(spec.get("due_in_days", 1))),
            source=TaskSource.AI_REFINEMENT.value,
            status=ActionItemStatus.OPEN.value,
            created_by=ctx.user_id,
            visible_to_client=bool(spec.get("visible_to_client", True)),
        )
        db.add(task)
        await db.flush()
        if spec.get("assignee_id"):
            task.assignee_id = spec["assignee_id"]
            task.assigned_by = ctx.user_id
            task.assignment_reason = "Incident fix task"
        else:
            task.required_skill = spec.get("required_skill", "logistics")
            await assignment_engine.assign_task(
                db, org_id=ctx.org_id, task=task, notify_assignee=True
            )
        ids.append(task.id)
        created.append({"id": task.id, "title": task.title,
                        "assignee_id": task.assignee_id})
    incident.fix_task_ids = ids
    incident.status = IncidentStatus.FIXING.value
    await db.commit()
    return {"fix_tasks": created}


class IncidentResolveRequest(BaseModel):
    lesson: str = Field(min_length=2)


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    body: IncidentResolveRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    incident = (
        await db.execute(
            select(Incident).where(
                Incident.org_id == ctx.org_id, Incident.id == incident_id
            )
        )
    ).scalar_one_or_none()
    if incident is None:
        raise NotFoundError("Incident not found")
    incident.status = IncidentStatus.RESOLVED.value
    incident.resolved_at = utcnow()
    incident.lesson = body.lesson
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.INCIDENT_RESOLVED.value,
        project_id=incident.project_id, entity_type="incident",
        entity_id=incident.id, actor=ctx.user_id,
        details={"lesson": body.lesson},
    )
    await knowledge_engine.distil_incident(db, org_id=ctx.org_id, incident=incident)
    await db.commit()
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Why-traces, digests, sweep
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/why/{entity_type}/{entity_id}")
async def why(
    entity_type: str,
    entity_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """'Why did the AI do that?' — open to the whole organisation."""
    return {
        "trace": await assistant_engine.why_trace(
            db, org_id=ctx.org_id, entity_type=entity_type, entity_id=entity_id
        )
    }


@router.get("/digests/daily")
async def my_daily_digest(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    user = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one()
    digest = await assistant_engine.build_daily_digest(db, org_id=ctx.org_id, user=user)
    await db.commit()
    return {"content_md": digest.content_md}


@router.post("/sync/sweep")
async def run_sweep(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Manual trigger of the Sync Engine's daily sweep (also runs on the
    scheduler). Useful for testing and for dry-runs."""
    stats = await sync_engine.daily_sweep(db, org_id=ctx.org_id)
    await db.commit()
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Manual draft path — a person asks for a client message directly
# ─────────────────────────────────────────────────────────────────────────────


class DraftRequest(BaseModel):
    contact_id: str
    kind: str = "follow_up"
    purpose: str = "manual message"
    project_id: str | None = None
    channel: str | None = None
    subject: str | None = None
    instruction: str | None = None
    facts: dict = Field(default_factory=dict)
    urgent: bool = False


@router.post("/messages/draft")
async def draft_message(
    body: DraftRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Ask the Communication Engine for a draft — it still goes through the
    approval gate like every other outward message."""
    from app.engines import communication_engine
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    contact = (
        await db.execute(
            select(Contact).where(
                Contact.org_id == ctx.org_id, Contact.id == body.contact_id
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found")
    project = None
    stakeholder = None
    if body.project_id:
        project = (
            await db.execute(
                select(Project).where(
                    Project.org_id == ctx.org_id, Project.id == body.project_id
                )
            )
        ).scalar_one_or_none()
        if project is not None:
            stakeholder = (
                await db.execute(
                    select(Stakeholder).where(
                        Stakeholder.project_id == project.id,
                        Stakeholder.contact_id == contact.id,
                    )
                )
            ).scalars().first()
    sender = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one()
    message, approval, uncovered = await communication_engine.draft_client_message(
        db, org_id=ctx.org_id, kind=body.kind, purpose=body.purpose,
        lead_id=contact.lead_id, contact=contact, project=project,
        stakeholder=stakeholder, channel=body.channel, subject=body.subject,
        instruction=body.instruction, facts=body.facts, sender=sender,
        urgent=body.urgent, triggered_by="manual",
    )
    await db.commit()
    if message is None:
        return {"held": True, "reason": "draft refused or held — see ai_decisions"}
    return {
        "message_id": message.id,
        "approval_id": approval.id if approval else None,
        "status": message.status,
        "body": message.body,
        "uncovered_points": uncovered,
    }
