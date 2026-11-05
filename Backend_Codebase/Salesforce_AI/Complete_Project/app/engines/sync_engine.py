"""Sync Engine — the heartbeat (30-Workflows §4 engine 4).

Reads progress_events and reacts: updates project health, unblocks dependent
tasks, runs the three-level reminder ladder, watches commitments, reply
timers, payments and vendor promises, fires client-update drafts when
visible_to_client tasks finish, and triggers digests. Runs on every event
plus a daily sweep.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ActionItemStatus,
    CommitmentDirection,
    CommitmentStatus,
    ConflictStatus,
    DecisionType,
    EventType,
    FollowUpStatus,
    IncidentStatus,
    Influence,
    InvoiceStatus,
    LeadState,
    MessageKind,
    MessageStatus,
    Phase,
    PRIORITY_ORDER,
    ProjectHealth,
    ProjectStatus,
    ReminderTargetType,
    Role,
    TaskPriority,
    TaskSource,
    ThreadStatus,
)
from app.engines import events, resource_engine
from app.engines.common import (
    find_department_lead,
    find_role_user,
    get_org_settings,
    get_user,
    record_decision,
)
from app.engines.worktime import (
    add_working_days,
    is_on_leave,
    next_working_moment,
    working_days_between,
)
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.comms import Thread
from app.models.finance import Invoice
from app.models.followup import FollowUp
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.organisation import OrgSettings
from app.models.project import (
    ClientCommitment,
    Conflict,
    Project,
    ProjectMember,
    Stakeholder,
)
from app.models.user import User
from app.models.work import Incident, ProgressEvent, Reminder
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "sync"
OPEN_STATUSES = (ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value)


def register() -> None:
    """Install the Sync Engine as the event-stream reactor."""
    events.set_reactor(react)


# ═════════════════════════════════════════════════════════════════════════════
# Event reactions
# ═════════════════════════════════════════════════════════════════════════════


async def react(db: AsyncSession, event: ProgressEvent) -> None:
    handler = {
        EventType.TASK_DONE.value: _on_task_done,
        EventType.TASK_BLOCKED.value: _on_task_blocked,
        EventType.TASK_UNBLOCKED.value: _on_task_unblocked,
        EventType.LEAVE_RECORDED.value: _on_leave_recorded,
        EventType.PAYMENT_RECEIVED.value: _on_payment_received,
        EventType.DEAL_AGREED.value: _on_deal_agreed,
        EventType.MEMBER_LEFT.value: _on_member_left,
        EventType.COMPLAINT_RECEIVED.value: _on_health_touch,
        EventType.COMMITMENT_BROKEN.value: _on_health_touch,
        EventType.CONFLICT_RAISED.value: _on_health_touch,
        EventType.CONFLICT_RESOLVED.value: _on_health_touch,
        EventType.INCIDENT_RESOLVED.value: _on_health_touch,
        EventType.TASK_OVERDUE.value: _on_health_touch,
        EventType.VENDOR_SLIP.value: _on_vendor_slip,
    }.get(event.event_type)
    if handler is not None:
        await handler(db, event)


async def _on_task_done(db: AsyncSession, event: ProgressEvent) -> None:
    """The heart of the platform (Workflow 14): unblock dependents, keep
    commitments, and let the school hear about visible work."""
    task = (
        await db.execute(select(ActionItem).where(ActionItem.id == event.entity_id))
    ).scalar_one_or_none()
    if task is None:
        return
    org_id = event.org_id

    # 1. Cancel every pending reminder for it — instantly.
    await cancel_reminders(db, org_id, ReminderTargetType.ACTION_ITEM.value, task.id)

    # 2. Unblock dependents — each re-validated at the moment it becomes ready.
    dependents = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    from app.engines import assignment_engine

    for dep in dependents:
        if task.id not in (dep.depends_on_ids or []):
            continue
        still_open = (
            await db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.id.in_(dep.depends_on_ids or [""]),
                    ActionItem.status.notin_(
                        [ActionItemStatus.DONE.value, ActionItemStatus.CANCELLED.value,
                         ActionItemStatus.SUPERSEDED.value]
                    ),
                )
            )
        ).scalar_one()
        if still_open == 0:
            await assignment_engine.revalidate_assignee(db, org_id=org_id, task=dep)
            if dep.assignee_id:
                await notify(
                    db, org_id=org_id, user_id=dep.assignee_id,
                    title=f"Ready to start: {dep.title}",
                    body=f"'{task.title}' finished — your task is no longer waiting.",
                    kind="task_assigned", entity_type="action_item", entity_id=dep.id,
                )

    # 3. Commitments this task fulfils → kept, and the school hears about it.
    commitment = None
    if task.client_commitment_id:
        commitment = (
            await db.execute(
                select(ClientCommitment).where(ClientCommitment.id == task.client_commitment_id)
            )
        ).scalar_one_or_none()
        if commitment is not None and commitment.status == CommitmentStatus.OPEN.value:
            commitment.status = CommitmentStatus.KEPT.value
            await events.emit(
                db, org_id=org_id, event_type=EventType.COMMITMENT_KEPT.value,
                project_id=task.project_id, entity_type="client_commitment",
                entity_id=commitment.id, react=False,
            )

    # 4. visible_to_client → the Communication Engine drafts the update.
    if task.visible_to_client and task.project_id:
        await _draft_completion_update(db, org_id, task, commitment)

    # 5. Health refresh.
    if task.project_id:
        await recompute_health(db, org_id, task.project_id)


async def _draft_completion_update(
    db: AsyncSession, org_id: str, task: ActionItem,
    commitment: ClientCommitment | None,
) -> None:
    from app.engines import communication_engine, document_engine

    project = (
        await db.execute(select(Project).where(Project.id == task.project_id))
    ).scalar_one_or_none()
    if project is None:
        return
    recipients = (
        await db.execute(
            select(Stakeholder).where(
                Stakeholder.project_id == project.id,
                Stakeholder.receives_progress_updates.is_(True),
                Stakeholder.do_not_contact.is_(False),
            )
        )
    ).scalars().all()
    if not recipients:
        return
    primary = recipients[0]
    contact = (
        await db.execute(select(Contact).where(Contact.id == primary.contact_id))
    ).scalar_one_or_none()
    if contact is None:
        return
    cc_addresses = []
    for s in recipients[1:]:
        c = (
            await db.execute(select(Contact).where(Contact.id == s.contact_id))
        ).scalar_one_or_none()
        if c is not None and c.email:
            cc_addresses.append(c.email)
    from app.models.finance import Deliverable

    attachments = []
    linked = (
        await db.execute(
            select(Deliverable)
            .where(Deliverable.linked_action_item_id == task.id)
            .order_by(Deliverable.version.desc())
        )
    ).scalars().first()
    if linked is not None and linked.file_path:
        attachments.append({"path": linked.file_path, "filename": linked.file_path.split("/")[-1]})

    facts: dict[str, Any] = {"completed": task.title}
    if task.result_note:
        facts["details"] = task.result_note
    if commitment is not None:
        facts["as_promised"] = commitment.text
    await communication_engine.draft_client_message(
        db, org_id=org_id, kind=MessageKind.PROGRESS_UPDATE.value,
        purpose="tell the client a visible task finished",
        lead_id=project.lead_id, contact=contact, project=project,
        stakeholder=primary,
        subject=f"{project.name} — update",
        cc=cc_addresses,
        instruction="Share the completed work; propose (don't promise) the natural next step.",
        facts=facts,
        attachments=attachments,
        triggered_by="task_completed",
    )


def _blocker_is_client(reason: str, *, colleague_named: bool) -> bool:
    """Does this block wait on the client, so a chase email is due?

    Keyword-based, as it always was — except that a named colleague means the
    wait is internal: "needs Siva's approval" is Siva's approval, and used to
    draft a chase to the client because it contains "approval".
    """
    if colleague_named:
        return False
    reason = reason.lower()
    return "school" in reason or "client" in reason or "approval" in reason


async def _resolve_blocking_colleague(
    db: AsyncSession, task: ActionItem, event: ProgressEvent,
) -> User | None:
    """The colleague a blocked task waits on, or None.

    An explicit pick (event details) wins when it is an active member of this
    org; otherwise the reason is searched for a name. The blocked person and
    whoever pressed "blocked" can never be their own blocker.
    """
    from app.services.blocker_resolver import find_colleague

    exclude = {u for u in (task.assignee_id, event.actor) if u}
    people = (
        await db.execute(
            select(User).where(User.org_id == event.org_id, User.is_active.is_(True))
        )
    ).scalars().all()
    by_id = {u.id: u for u in people if u.id not in exclude}
    picked = (event.details or {}).get("blocked_on_user_id")
    if picked:
        return by_id.get(picked)
    found = find_colleague(
        task.blocked_reason, [(u.id, u.name) for u in by_id.values()],
    )
    return by_id.get(found) if found else None


async def _on_task_blocked(db: AsyncSession, event: ProgressEvent) -> None:
    """Chase the blocker, not the blocked (Workflow 11)."""
    task = (
        await db.execute(select(ActionItem).where(ActionItem.id == event.entity_id))
    ).scalar_one_or_none()
    if task is None:
        return
    org_id = event.org_id
    await cancel_reminders(db, org_id, ReminderTargetType.ACTION_ITEM.value, task.id)

    reason = (task.blocked_reason or "").lower()
    # Downstream chain → at-risk marking + health.
    if task.project_id:
        await recompute_health(db, org_id, task.project_id)

    # Customer ask, 21 Sep 2026: "blocked, waiting for inputs from Siva" told
    # Siva nothing. Find the colleague, remember them (their Home lists it),
    # and tell them once. Re-blocking with a new reason re-decides.
    colleague = await _resolve_blocking_colleague(db, task, event)
    task.blocked_on_user_id = colleague.id if colleague else None
    if colleague is not None:
        waiter_id = task.assignee_id or event.actor
        waiter = (
            await db.execute(select(User.name).where(User.id == waiter_id))
        ).scalar_one_or_none() or "A colleague"
        # Point the tap somewhere the colleague can open: the app's task
        # screen only finds the caller's OWN tasks, so a bare action_item
        # would land Siva on "not found". Project, else client, else task.
        if task.project_id:
            target = ("project", task.project_id)
        elif task.lead_id:
            target = ("lead", task.lead_id)
        else:
            target = ("action_item", task.id)
        await notify(
            db, org_id=org_id, user_id=colleague.id,
            title=f"{waiter} is waiting on you",
            body=f"'{task.title}' is blocked: {task.blocked_reason}",
            kind="blocked_on_you", entity_type=target[0], entity_id=target[1],
        )

    if _blocker_is_client(reason, colleague_named=colleague is not None):
        # The blocker is the client → draft a polite chase to the right person.
        project = (
            await db.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one_or_none()
        if project is None:
            return
        stakeholders = (
            await db.execute(
                select(Stakeholder)
                .where(
                    Stakeholder.project_id == project.id,
                    Stakeholder.do_not_contact.is_(False),
                )
                # F55: the two `next(...)` picks below were taken from an
                # unordered set, so which client person received an update was
                # decided by row order. Oldest first — the people this project
                # has known longest win over anyone attached later.
                .order_by(Stakeholder.created_at, Stakeholder.id)
            )
        ).scalars().all()
        # The day-to-day contact first — whoever receives progress updates
        # without holding final say — else the decision maker. Judged from
        # the generic stakeholder fields, never from a role vocabulary.
        target = next(
            (s for s in stakeholders
             if s.receives_progress_updates and s.influence != "decision_maker"),
            next((s for s in stakeholders if s.influence == "decision_maker"), None),
        )
        if target is None:
            return
        contact = (
            await db.execute(select(Contact).where(Contact.id == target.contact_id))
        ).scalar_one_or_none()
        if contact is None:
            return
        from app.engines import communication_engine

        await communication_engine.draft_client_message(
            db, org_id=org_id, kind=MessageKind.FOLLOW_UP.value,
            purpose="gentle chase — our work waits on the client",
            lead_id=project.lead_id, contact=contact, project=project,
            stakeholder=target,
            subject=f"{project.name} — a quick nod needed",
            instruction=(
                "A gentle reminder — a quick approval lets us keep everything on time."
            ),
            facts={"waiting_on": task.blocked_reason, "so_that": task.title},
            triggered_by="reminder_ladder",
        )
    else:
        # Internal blocker: the ladder targets the blocking task's assignee;
        # the blocked person is told we're chasing it.
        blocker_ids = task.depends_on_ids or []
        blockers = (
            await db.execute(
                select(ActionItem).where(
                    ActionItem.id.in_(blocker_ids or [""]),
                    ActionItem.status.in_(OPEN_STATUSES),
                )
            )
        ).scalars().all()
        for b in blockers:
            if b.assignee_id:
                await notify(
                    db, org_id=org_id, user_id=b.assignee_id,
                    title=f"Your task blocks {task.title}",
                    body=f"'{b.title}' is holding up downstream work — please prioritise.",
                    kind="reminder", entity_type="action_item", entity_id=b.id,
                )
        if task.assignee_id and blockers:
            await notify(
                db, org_id=org_id, user_id=task.assignee_id,
                title="We're chasing your blocker",
                body=f"'{task.title}' waits on {', '.join(b.title for b in blockers)} — being chased.",
                kind="general", entity_type="action_item", entity_id=task.id,
            )


async def _on_task_unblocked(db: AsyncSession, event: ProgressEvent) -> None:
    task = (
        await db.execute(select(ActionItem).where(ActionItem.id == event.entity_id))
    ).scalar_one_or_none()
    if task is None:
        return
    task.blocked_on_user_id = None
    from app.engines import assignment_engine

    await assignment_engine.revalidate_assignee(db, org_id=event.org_id, task=task)
    if task.assignee_id:
        await notify(
            db, org_id=event.org_id, user_id=task.assignee_id,
            title=f"Unblocked: {task.title}",
            body="The wait is over — the task is ready.",
            kind="task_assigned", entity_type="action_item", entity_id=task.id,
        )
    if task.project_id:
        await recompute_health(db, event.org_id, task.project_id)


async def _on_leave_recorded(db: AsyncSession, event: ProgressEvent) -> None:
    """Workflow 12: cross-check every task due inside the leave window,
    reassign the endangered ones with a handover package."""
    org_id = event.org_id
    user = (
        await db.execute(select(User).where(User.id == event.entity_id))
    ).scalar_one_or_none()
    if user is None or user.on_leave_from is None or user.on_leave_to is None:
        return
    leave_from, leave_to = user.on_leave_from, user.on_leave_to
    tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.assignee_id == user.id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    endangered = [
        t for t in tasks
        if t.due_date is not None and leave_from <= t.due_date.date() <= leave_to
    ]
    # Cancel any reminders already aimed at the leave window; never nudge
    # people on leave.
    for t in tasks:
        reminders = (
            await db.execute(
                select(Reminder).where(
                    Reminder.org_id == org_id,
                    Reminder.target_type == ReminderTargetType.ACTION_ITEM.value,
                    Reminder.target_id == t.id,
                    Reminder.sent_at.is_(None),
                    Reminder.cancelled_at.is_(None),
                )
            )
        ).scalars().all()
        for r in reminders:
            if leave_from <= r.scheduled_at.date() <= leave_to:
                r.cancelled_at = utcnow()

    if not endangered:
        return
    from app.engines import assignment_engine

    moved_titles: list[str] = []
    for t in endangered:
        handover = (
            f"Handover: {user.name} on leave {leave_from:%d %b}–{leave_to:%d %b}; "
            f"progress {t.progress_percent or 0}%"
            + (f"; note: {t.result_note}" if t.result_note else "")
        )
        assignment = await assignment_engine.assign_task(
            db, org_id=org_id, task=t, exclude_user_ids={user.id},
            notify_assignee=True,
        )
        if assignment is not None and t.assignee_id and t.assignee_id != user.id:
            moved_titles.append(t.title)
            await notify(
                db, org_id=org_id, user_id=t.assignee_id,
                title=f"Handover package: {t.title}",
                body=handover, kind="task_assigned",
                entity_type="action_item", entity_id=t.id,
            )
            await events.emit(
                db, org_id=org_id, event_type=EventType.TASK_REASSIGNED.value,
                project_id=t.project_id, entity_type="action_item", entity_id=t.id,
                details={"from": user.id, "to": t.assignee_id, "reason": "leave"},
                react=False,
            )
        elif assignment is None:
            # No alternative — the honest option: ask to pre-pone.
            lead = await find_department_lead(db, org_id, user.department)
            await notify(
                db, org_id=org_id, user_id=user.id,
                title=f"Can you finish '{t.title}' before your leave?",
                body="No good alternative exists for this task — could you "
                f"complete it by {leave_from - timedelta(days=1):%d %b}?",
                kind="reminder", entity_type="action_item", entity_id=t.id,
            )
            if lead is not None:
                await notify(
                    db, org_id=org_id, user_id=lead.id,
                    title=f"Leave risk on '{t.title}'",
                    body=f"Only {user.name} has the skill; asked to pre-pone. "
                    "The risk exists either way.",
                    kind="escalation", entity_type="action_item", entity_id=t.id,
                )
    # Courtesy note listing what moved and what stayed.
    safe = [t.title for t in tasks if t not in endangered]
    await notify(
        db, org_id=org_id, user_id=user.id,
        title="While you're away",
        body=(
            (f"Moved: {', '.join(moved_titles)}. " if moved_titles else "")
            + (f"Staying with you: {', '.join(safe[:5])}." if safe else "")
        ),
        kind="general",
    )


async def _on_payment_received(db: AsyncSession, event: ProgressEvent) -> None:
    """Thank-you draft + closure eligibility check (Workflow 25)."""
    org_id = event.org_id
    invoice = (
        await db.execute(select(Invoice).where(Invoice.id == event.entity_id))
    ).scalar_one_or_none()
    if invoice is None:
        return
    await cancel_reminders(db, org_id, ReminderTargetType.INVOICE.value, invoice.id)
    project = (
        await db.execute(select(Project).where(Project.id == invoice.project_id))
    ).scalar_one_or_none()
    if project is None:
        return
    if invoice.status == InvoiceStatus.PAID.value:
        # Small thing, big goodwill.
        if invoice.sent_to_stakeholder_id:
            stakeholder = (
                await db.execute(
                    select(Stakeholder).where(Stakeholder.id == invoice.sent_to_stakeholder_id)
                )
            ).scalar_one_or_none()
            contact = None
            if stakeholder is not None:
                contact = (
                    await db.execute(
                        select(Contact).where(Contact.id == stakeholder.contact_id)
                    )
                ).scalar_one_or_none()
            if contact is not None:
                from app.engines import communication_engine

                await communication_engine.draft_client_message(
                    db, org_id=org_id, kind=MessageKind.REPLY.value,
                    purpose="payment thank-you",
                    lead_id=project.lead_id, contact=contact, project=project,
                    stakeholder=stakeholder,
                    subject=f"{project.name} — payment received, thank you",
                    instruction="A short warm thank-you for the payment.",
                    facts={"received": f"{invoice.amount:,.0f} {invoice.currency}"},
                    triggered_by="task_completed",
                )
        # Unblock delivery gated on advance.
        if invoice.kind == "advance":
            gated = (
                await db.execute(
                    select(ActionItem).where(
                        ActionItem.project_id == project.id,
                        ActionItem.blocked.is_(True),
                    )
                )
            ).scalars().all()
            for t in gated:
                if "advance" in (t.blocked_reason or "").lower():
                    t.blocked = False
                    t.blocked_reason = None
                    await events.emit(
                        db, org_id=org_id, event_type=EventType.TASK_UNBLOCKED.value,
                        project_id=project.id, entity_type="action_item",
                        entity_id=t.id, details={"by": "advance paid"},
                    )
        await _check_closure_eligibility(db, org_id, project)
    await recompute_health(db, org_id, project.id)


async def _check_closure_eligibility(
    db: AsyncSession, org_id: str, project: Project
) -> None:
    """All invoices paid + all closure tasks done → project closes and the
    Knowledge Engine distils it (Workflow 26)."""
    if project.status == ProjectStatus.CLOSED.value:
        return
    unpaid = (
        await db.execute(
            select(func.count(Invoice.id)).where(
                Invoice.project_id == project.id,
                Invoice.status.notin_([InvoiceStatus.PAID.value, InvoiceStatus.DRAFT.value]),
            )
        )
    ).scalar_one()
    open_tasks = (
        await db.execute(
            select(func.count(ActionItem.id)).where(
                ActionItem.project_id == project.id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalar_one()
    if unpaid == 0 and open_tasks == 0 and project.status in (
        ProjectStatus.PAYMENT_PENDING.value, ProjectStatus.DELIVERY.value,
    ):
        project.status = ProjectStatus.CLOSED.value
        await events.emit(
            db, org_id=org_id, event_type=EventType.PROJECT_CLOSED.value,
            project_id=project.id, entity_type="project", entity_id=project.id,
        )
        from app.engines import knowledge_engine

        await knowledge_engine.distil_project(db, org_id=org_id, project=project)
        lead = (
            await db.execute(select(Lead).where(Lead.id == project.lead_id))
        ).scalar_one_or_none()
        if lead is not None:
            from app.services import lead_service

            await lead_service.apply_suggestion(
                db, org_id=org_id, lead=lead, to_state=LeadState.CLOSED.value,
                reason=f"Project '{project.name}' delivered and paid",
                engine=ENGINE, confidence=0.95,
                input_summary=f"Project '{project.name}' reached delivered + paid",
            )


async def _on_deal_agreed(db: AsyncSession, event: ProgressEvent) -> None:
    """Workflow 8: selling → delivering. Ops co-ownership, preparation wave,
    the money trail starts."""
    org_id = event.org_id
    project = (
        await db.execute(select(Project).where(Project.id == event.project_id))
    ).scalar_one_or_none()
    if project is None:
        return
    ops_lead = await find_role_user(db, org_id, Role.OPERATIONS_LEAD.value)
    if ops_lead is not None and not project.ops_owner_id:
        project.ops_owner_id = ops_lead.id
        member = (
            await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == ops_lead.id,
                    ProjectMember.left_at.is_(None),
                )
            )
        ).scalars().first()
        if member is None:
            db.add(
                ProjectMember(
                    org_id=org_id, project_id=project.id, user_id=ops_lead.id,
                    role_in_project="owner", added_by="ai", joined_at=utcnow(),
                )
            )
    from app.engines import planner_engine

    await planner_engine.phase_shift(
        db, org_id=org_id, project=project, phase=Phase.PREPARATION.value
    )
    project.status = ProjectStatus.PREPARATION.value
    # Lead state suggestion (human confirms — same pattern as before).
    lead = (
        await db.execute(select(Lead).where(Lead.id == project.lead_id))
    ).scalar_one_or_none()
    if lead is not None and lead.state == LeadState.ACTIVE.value:
        from app.services import lead_service

        await lead_service.apply_suggestion(
            db, org_id=org_id, lead=lead,
            to_state=LeadState.EXECUTION_IN_PROGRESS.value,
            reason=f"Deal agreed on '{project.name}'",
            engine=ENGINE, confidence=0.9,
            input_summary=f"Deal agreed event on project '{project.name}'",
        )


async def _on_member_left(db: AsyncSession, event: ProgressEvent) -> None:
    """left_at filled → their open tasks are redistributed."""
    org_id = event.org_id
    user_id = event.entity_id
    project_id = event.project_id
    tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.project_id == project_id,
                ActionItem.assignee_id == user_id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    from app.engines import assignment_engine

    for t in tasks:
        await assignment_engine.assign_task(
            db, org_id=org_id, task=t, exclude_user_ids={user_id} if user_id else set(),
            notify_assignee=True,
        )


async def _on_vendor_slip(db: AsyncSession, event: ProgressEvent) -> None:
    """Workflow 24: walk the chain — inside slack, adjust quietly; past slack,
    the Planner proposes the re-plan."""
    org_id = event.org_id
    task = (
        await db.execute(select(ActionItem).where(ActionItem.id == event.entity_id))
    ).scalar_one_or_none()
    if task is None or not task.external_wait:
        return
    new_date_s = (event.details or {}).get("new_promised_date")
    if not new_date_s:
        return
    new_date = datetime.fromisoformat(new_date_s)
    project = (
        await db.execute(select(Project).where(Project.id == task.project_id))
    ).scalar_one_or_none()
    slack_edge = project.start_date if project and project.start_date else None
    if slack_edge is None or new_date < slack_edge - timedelta(days=1):
        # Slack exists — downstream dates adjust inside it, nobody alarmed.
        if task.due_date and new_date > task.due_date:
            task.due_date = new_date
        await record_decision(
            db, org_id=org_id, project_id=task.project_id,
            decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
            decision="Vendor slip absorbed by slack",
            reason=f"New promised date {new_date:%d %b} still clears the delivery chain",
            entity_type="action_item", entity_id=task.id,
        )
    else:
        # The slip eats the slack → human decides the re-plan.
        owner = await get_user(db, org_id, project.ops_owner_id if project else None)
        if owner is None:
            owner = await find_role_user(db, org_id, Role.OPERATIONS_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Vendor slip threatens the plan: {task.title}",
                body=(
                    f"New promised date {new_date:%d %b} eats the slack before "
                    f"{slack_edge:%d %b}. Options: re-plan the start, split delivery, "
                    "or rush an alternative."
                ),
                kind="escalation", entity_type="action_item", entity_id=task.id,
            )
        if task.project_id:
            await recompute_health(db, org_id, task.project_id)


async def _on_health_touch(db: AsyncSession, event: ProgressEvent) -> None:
    if event.project_id:
        await recompute_health(db, event.org_id, event.project_id)


# ═════════════════════════════════════════════════════════════════════════════
# Health
# ═════════════════════════════════════════════════════════════════════════════


async def health_signals(
    db: AsyncSession, org_id: str, project_id: str
) -> tuple[dict[str, int], list[str]]:
    """What is actually wrong with this project — counts, and the ranked
    human-readable reasons.

    Extracted from `recompute_health` for F43. The project's **Delivery** card
    already said *"4 unresolved conflict(s) blocking a re-plan"* from these very
    counts, while the assistant's "What's blocking?" — asked on the same project,
    in the same minute — answered *"Nothing is blocking"*. The good answer was
    already in the codebase; it just was not shared.

    Returns (counts, reasons) so the health tier and the sentence stay in step.
    """
    now = utcnow()
    overdue = (
        await db.execute(
            select(func.count(ActionItem.id)).where(
                ActionItem.project_id == project_id,
                ActionItem.status.in_(OPEN_STATUSES),
                ActionItem.due_date < now,
            )
        )
    ).scalar_one()
    blocked = (
        await db.execute(
            select(func.count(ActionItem.id)).where(
                ActionItem.project_id == project_id,
                ActionItem.blocked.is_(True),
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalar_one()
    broken = (
        await db.execute(
            select(func.count(ClientCommitment.id)).where(
                ClientCommitment.project_id == project_id,
                ClientCommitment.status == CommitmentStatus.BROKEN.value,
            )
        )
    ).scalar_one()
    conflicts = (
        await db.execute(
            select(func.count(Conflict.id)).where(
                Conflict.project_id == project_id,
                Conflict.status == ConflictStatus.OPEN.value,
            )
        )
    ).scalar_one()
    incidents = (
        await db.execute(
            select(func.count(Incident.id)).where(
                Incident.project_id == project_id,
                Incident.status != IncidentStatus.RESOLVED.value,
            )
        )
    ).scalar_one()

    reasons: list[str] = []
    if overdue:
        reasons.append(f"{overdue} task(s) overdue")
    if blocked:
        reasons.append(f"{blocked} task(s) blocked")
    if broken:
        reasons.append(f"{broken} commitment(s) broken")
    if conflicts:
        reasons.append(f"{conflicts} unresolved conflict(s) blocking a re-plan")
    if incidents:
        reasons.append(f"{incidents} open incident(s)")
    return (
        {"overdue": overdue, "blocked": blocked, "broken": broken,
         "conflicts": conflicts, "incidents": incidents},
        reasons,
    )


async def recompute_health(db: AsyncSession, org_id: str, project_id: str) -> None:
    project = (
        await db.execute(
            select(Project).where(Project.org_id == org_id, Project.id == project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        return
    counts, reasons = await health_signals(db, org_id, project_id)
    overdue, broken = counts["overdue"], counts["broken"]

    if broken or overdue >= 3:
        health = ProjectHealth.DELAYED.value
    elif reasons:
        health = ProjectHealth.AT_RISK.value
    else:
        health = ProjectHealth.ON_TRACK.value

    # Chain parents: worst of children plus own state (Workflow 27).
    children = (
        await db.execute(
            select(Project).where(Project.parent_project_id == project_id)
        )
    ).scalars().all()
    order = {
        ProjectHealth.ON_TRACK.value: 0,
        ProjectHealth.AT_RISK.value: 1,
        ProjectHealth.DELAYED.value: 2,
    }
    for child in children:
        if order.get(child.health, 0) > order.get(health, 0):
            health = child.health
            reasons.append(f"child project '{child.name}' is {child.health}")

    if health != project.health:
        project.health = health
        project.health_reason = "; ".join(reasons) if reasons else None
        await events.emit(
            db, org_id=org_id, event_type=EventType.PROJECT_HEALTH_CHANGED.value,
            project_id=project_id, entity_type="project", entity_id=project_id,
            details={"health": health, "reason": project.health_reason or ""},
            react=False,
        )
        if project.parent_project_id:
            await recompute_health(db, org_id, project.parent_project_id)
    else:
        project.health_reason = "; ".join(reasons) if reasons else None


# ═════════════════════════════════════════════════════════════════════════════
# Reminders
# ═════════════════════════════════════════════════════════════════════════════


async def cancel_reminders(
    db: AsyncSession, org_id: str, target_type: str, target_id: str
) -> None:
    rows = (
        await db.execute(
            select(Reminder).where(
                Reminder.org_id == org_id,
                Reminder.target_type == target_type,
                Reminder.target_id == target_id,
                Reminder.sent_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )
        )
    ).scalars().all()
    for r in rows:
        r.cancelled_at = utcnow()


# ═════════════════════════════════════════════════════════════════════════════
# The daily sweep
# ═════════════════════════════════════════════════════════════════════════════


async def daily_sweep(db: AsyncSession, *, org_id: str, now: datetime | None = None) -> dict:
    """Everything the heartbeat checks once a day (plus, in delivery,
    commitments are watched hourly by the same code)."""
    now = now or utcnow()
    org = await get_org_settings(db, org_id)
    stats = {
        "overdue_laddered": 0, "commitments_chased": 0, "reply_nudges": 0,
        "payment_reminders": 0, "overload_alerts": 0, "revival_cards": 0,
        "external_chases": 0,
    }

    stats["overdue_laddered"] = await _sweep_task_ladder(db, org_id, org, now)
    stats["commitments_chased"] = await _sweep_commitments(db, org_id, org, now)
    stats["reply_nudges"] = await _sweep_reply_watches(db, org_id, org, now)
    stats["payment_reminders"] = await _sweep_payment_ladder(db, org_id, org, now)
    stats["overload_alerts"] = await _sweep_overload(db, org_id, org, now)
    stats["revival_cards"] = await _sweep_revivals(db, org_id, org, now)
    stats["external_chases"] = await _sweep_external_waits(db, org_id, org, now)

    from app.engines import approval_engine

    await approval_engine.sweep_pending(db, org_id=org_id, now=now)

    # Health refresh for every open project + closure-eligibility checks.
    projects = (
        await db.execute(
            select(Project).where(
                Project.org_id == org_id,
                Project.status.notin_([ProjectStatus.CLOSED.value, ProjectStatus.LOST.value]),
            )
        )
    ).scalars().all()
    for p in projects:
        await recompute_health(db, org_id, p.id)
        if p.status in (ProjectStatus.PAYMENT_PENDING.value, ProjectStatus.DELIVERY.value):
            await _check_closure_eligibility(db, org_id, p)
    return stats


async def _sweep_task_ladder(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """The three-level nudge ladder (Workflow 10)."""
    gaps = org.nudge_gap_days or {"level1": 1, "level2": 3, "level3": 5}
    overdue = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.status.in_(OPEN_STATUSES),
                ActionItem.due_date < now,
                ActionItem.blocked.is_(False),
            )
        )
    ).scalars().all()
    count = 0
    for task in overdue:
        if not task.assignee_id:
            continue
        # Blocked-by-dependency tasks are not nudged.
        if task.depends_on_ids:
            open_deps = (
                await db.execute(
                    select(func.count(ActionItem.id)).where(
                        ActionItem.id.in_(task.depends_on_ids),
                        ActionItem.status.notin_(
                            [ActionItemStatus.DONE.value, ActionItemStatus.CANCELLED.value,
                             ActionItemStatus.SUPERSEDED.value]
                        ),
                    )
                )
            ).scalar_one()
            if open_deps:
                continue
        user = await get_user(db, org_id, task.assignee_id)
        if user is None:
            continue
        days_late = working_days_between(task.due_date.date(), now.date(), org, user)
        target_level = 0
        if days_late >= int(gaps.get("level3", 5)):
            target_level = 3
        elif days_late >= int(gaps.get("level2", 3)):
            target_level = 2
        elif days_late >= int(gaps.get("level1", 1)):
            target_level = 1
        if target_level <= (task.reminder_level or 0):
            continue
        if is_on_leave(user, now.date()):
            continue  # never nudge people on leave

        if (task.reminder_level or 0) == 0:
            await events.emit(
                db, org_id=org_id, event_type=EventType.TASK_OVERDUE.value,
                project_id=task.project_id, entity_type="action_item",
                entity_id=task.id, details={"days_late": days_late},
            )

        task.reminder_level = target_level
        count += 1
        if target_level == 1:
            await _fire_reminder(
                db, org_id, org, task, user, level=1, channel="push",
                text=f"Reminder: '{task.title}' was due {task.due_date:%d %b}. "
                "Reply with a new date if you're blocked.",
            )
        elif target_level == 2:
            await _fire_reminder(
                db, org_id, org, task, user, level=2, channel="whatsapp",
                text=f"2nd reminder — '{task.title}' is {days_late} working day(s) late"
                + (" and blocks other work." if await _has_dependents(db, task) else "."),
            )
        else:
            # Level 3 goes to the lead — a lead's own rot goes to the org admin.
            lead = await find_department_lead(db, org_id, user.department)
            if lead is not None and lead.id == user.id:
                lead = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
            if lead is not None:
                from app.engines import assignment_engine

                suggestion = await assignment_engine.build_candidates(
                    db, org_id=org_id, task=task, exclude_user_ids={user.id}
                )
                alt = suggestion[0][0].user.name if suggestion[0] else "nobody free"
                await _fire_reminder(
                    db, org_id, org, task, lead, level=3, channel="push",
                    text=(
                        f"Escalation: '{task.title}' ({user.name}) is {days_late} "
                        f"working day(s) late. Options: Reassign (suggest {alt}) / "
                        "Call / Extend."
                    ),
                )
                await events.emit(
                    db, org_id=org_id, event_type=EventType.TASK_ESCALATED.value,
                    project_id=task.project_id, entity_type="action_item",
                    entity_id=task.id,
                    details={"to": lead.id, "days_late": days_late},
                )
    return count


async def _has_dependents(db: AsyncSession, task: ActionItem) -> bool:
    dependents = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == task.org_id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    return any(task.id in (d.depends_on_ids or []) for d in dependents)


async def _fire_reminder(
    db: AsyncSession, org_id: str, org: OrgSettings, task: ActionItem,
    user: User, *, level: int, channel: str, text: str,
) -> None:
    """Reminders respect working hours and are recorded as reminders rows."""
    scheduled = next_working_moment(utcnow(), org, user)
    reminder = Reminder(
        org_id=org_id,
        target_type=ReminderTargetType.ACTION_ITEM.value,
        target_id=task.id,
        remind_user_id=user.id,
        level=level,
        channel=channel,
        scheduled_at=scheduled,
        sent_at=utcnow(),  # in-app delivery is immediate; channel mirrors follow
        note=text,
    )
    db.add(reminder)
    await notify(
        db, org_id=org_id, user_id=user.id,
        title=("Escalation" if level == 3 else "Reminder") + f": {task.title}",
        body=text, kind="escalation" if level == 3 else "reminder",
        entity_type="action_item", entity_id=task.id,
    )


async def _sweep_commitments(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """Chase promises BEFORE they break; mark broken honestly after."""
    count = 0
    open_commitments = (
        await db.execute(
            select(ClientCommitment).where(
                ClientCommitment.org_id == org_id,
                ClientCommitment.status == CommitmentStatus.OPEN.value,
                ClientCommitment.due_date.is_not(None),
            )
        )
    ).scalars().all()
    for c in open_commitments:
        if c.direction == CommitmentDirection.OURS.value:
            # T-1: is the linked task on track?
            if c.linked_action_item_id and now + timedelta(days=1) >= c.due_date > now:
                task = (
                    await db.execute(
                        select(ActionItem).where(ActionItem.id == c.linked_action_item_id)
                    )
                ).scalar_one_or_none()
                if task is not None and task.status in OPEN_STATUSES and task.assignee_id:
                    await notify(
                        db, org_id=org_id, user_id=task.assignee_id,
                        title=f"Client promise due tomorrow: {c.text}",
                        body=f"'{task.title}' fulfils this promise — it breaks tomorrow.",
                        kind="reminder", entity_type="client_commitment", entity_id=c.id,
                    )
                    count += 1
            elif now > c.due_date:
                c.status = CommitmentStatus.BROKEN.value
                await events.emit(
                    db, org_id=org_id, event_type=EventType.COMMITMENT_BROKEN.value,
                    project_id=c.project_id, entity_type="client_commitment",
                    entity_id=c.id, details={"text": c.text},
                )
                count += 1
        else:
            # The school's promise to us — chase politely after due.
            if now > c.due_date:
                project = (
                    await db.execute(select(Project).where(Project.id == c.project_id))
                ).scalar_one_or_none()
                if project is None:
                    continue
                stakeholder = None
                if c.promised_by:
                    stakeholder = (
                        await db.execute(
                            select(Stakeholder).where(Stakeholder.id == c.promised_by)
                        )
                    ).scalar_one_or_none()
                if stakeholder is None:
                    continue
                contact = (
                    await db.execute(
                        select(Contact).where(Contact.id == stakeholder.contact_id)
                    )
                ).scalar_one_or_none()
                if contact is None or stakeholder.do_not_contact:
                    continue
                already = (
                    await db.execute(
                        select(func.count(Reminder.id)).where(
                            Reminder.target_type == ReminderTargetType.CLIENT_COMMITMENT.value,
                            Reminder.target_id == c.id,
                        )
                    )
                ).scalar_one()
                if already >= (org.max_unanswered_nudges or 2):
                    continue
                from app.engines import communication_engine

                await communication_engine.draft_client_message(
                    db, org_id=org_id, kind=MessageKind.FOLLOW_UP.value,
                    purpose="gentle chase of the client's promise",
                    lead_id=project.lead_id, contact=contact, project=project,
                    stakeholder=stakeholder,
                    subject=f"{project.name} — gentle reminder",
                    instruction="A friendly nudge about what they promised us.",
                    facts={"awaiting": c.text, "was_due": f"{c.due_date:%d %b}"},
                    triggered_by="reminder_ladder",
                )
                db.add(
                    Reminder(
                        org_id=org_id,
                        target_type=ReminderTargetType.CLIENT_COMMITMENT.value,
                        target_id=c.id,
                        remind_user_id=project.sales_owner_id or "",
                        level=1, channel=stakeholder.preferred_channel or "email",
                        scheduled_at=now, sent_at=now,
                    )
                )
                count += 1
    return count


async def _sweep_reply_watches(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """The follow-up ladder for silent threads (Workflow 5): nudge → switch
    channel → call task → suggest cold."""
    ladder = org.reply_nudge_after_days or {"nudge1": 4, "nudge2": 8, "call_task": 12}
    count = 0
    threads = (
        await db.execute(
            select(Thread).where(
                Thread.org_id == org_id,
                Thread.last_direction == "outbound",
                Thread.status == ThreadStatus.OPEN.value,
                Thread.last_message_at.is_not(None),
            )
        )
    ).scalars().all()
    for thread in threads:
        days_silent = (now - thread.last_message_at).days
        contact = (
            await db.execute(select(Contact).where(Contact.id == thread.contact_id))
        ).scalar_one_or_none()
        lead = (
            await db.execute(select(Lead).where(Lead.id == thread.lead_id))
        ).scalar_one_or_none()
        if contact is None or lead is None:
            continue
        project = None
        if thread.project_id:
            project = (
                await db.execute(select(Project).where(Project.id == thread.project_id))
            ).scalar_one_or_none()
        nudges_sent = (
            await db.execute(
                select(func.count(Reminder.id)).where(
                    Reminder.org_id == org_id,
                    Reminder.target_type == "thread",
                    Reminder.target_id == thread.id,
                    Reminder.cancelled_at.is_(None),
                )
            )
        ).scalar_one()
        max_nudges = org.max_unanswered_nudges or 2

        stakeholder = None
        if thread.stakeholder_id:
            stakeholder = (
                await db.execute(
                    select(Stakeholder).where(Stakeholder.id == thread.stakeholder_id)
                )
            ).scalar_one_or_none()

        if days_silent >= int(ladder.get("call_task", 12)) and nudges_sent >= max_nudges:
            # No more automatic messages — a person calls. (No `continue` in
            # this branch: the day-30 cold suggestion below must still run.)
            owner = await get_user(db, org_id, thread.owner_user_id or lead.owner_id)
            existing = 1 if owner is None else (
                await db.execute(
                    select(func.count(ActionItem.id)).where(
                        ActionItem.org_id == org_id,
                        ActionItem.lead_id == lead.id,
                        ActionItem.title.like("Call%unanswered%"),
                        ActionItem.status.in_(OPEN_STATUSES),
                    )
                )
            ).scalar_one()
            if not existing:
                db.add(
                    ActionItem(
                        org_id=org_id, lead_id=lead.id,
                        project_id=thread.project_id,
                        title=f"Call {contact.name} — thread unanswered {days_silent} days",
                        phase=Phase.SALES.value, priority=TaskPriority.P2.value,
                        due_date=now + timedelta(days=2),
                        assignee_id=owner.id, assigned_by="ai",
                        assignment_reason="Max unanswered nudges reached — org rule: a person calls",
                        source=TaskSource.AI_REFINEMENT.value,
                        status=ActionItemStatus.OPEN.value, created_by="ai",
                    )
                )
                await notify(
                    db, org_id=org_id, user_id=owner.id,
                    title=f"Call task: {lead.name} silent {days_silent} days",
                    body="Two nudges went unanswered — time for a phone call.",
                    kind="task_assigned",
                )
                count += 1
        elif days_silent >= int(ladder.get("nudge2", 8)) and nudges_sent == 1:
            # Switch channel (stakeholder preference order, minus what was tried).
            from app.engines import communication_engine

            first_channel = thread.channel
            switch = "whatsapp" if first_channel == "email" else "email"
            await communication_engine.draft_client_message(
                db, org_id=org_id, kind=MessageKind.FOLLOW_UP.value,
                purpose="second nudge on a silent thread (channel switched)",
                lead_id=lead.id, contact=contact, project=project,
                stakeholder=stakeholder, channel=switch,
                subject=f"{project.name if project else lead.name} — checking in",
                instruction="Short, warm, zero pressure — just checking they saw it.",
                facts={"waiting_since": f"{thread.last_message_at:%d %b}"},
                triggered_by="reminder_ladder",
            )
            db.add(
                Reminder(
                    org_id=org_id, target_type="thread", target_id=thread.id,
                    remind_user_id=thread.owner_user_id or lead.owner_id or "",
                    level=2, channel=switch, scheduled_at=now, sent_at=now,
                )
            )
            count += 1
        elif days_silent >= int(ladder.get("nudge1", 4)) and nudges_sent == 0:
            from app.engines import communication_engine

            await communication_engine.draft_client_message(
                db, org_id=org_id, kind=MessageKind.FOLLOW_UP.value,
                purpose="gentle first nudge on a silent thread",
                lead_id=lead.id, contact=contact, project=project,
                stakeholder=stakeholder, channel=thread.channel,
                subject=f"{project.name if project else lead.name} — just checking in",
                instruction="Just checking it reached them; happy to answer questions.",
                facts={"sent_on": f"{thread.last_message_at:%d %b}"},
                triggered_by="reminder_ladder",
            )
            db.add(
                Reminder(
                    org_id=org_id, target_type="thread", target_id=thread.id,
                    remind_user_id=thread.owner_user_id or lead.owner_id or "",
                    level=1, channel=thread.channel, scheduled_at=now, sent_at=now,
                )
            )
            count += 1

        # Cold suggestion after the org's silence threshold.
        cold_after = org.lead_cold_after_days or 30
        if (
            days_silent >= cold_after
            and lead.state in (LeadState.OPEN.value, LeadState.ACTIVE.value)
            and lead.suggested_state != LeadState.COLD.value
        ):
            from app.services import lead_service

            await lead_service.apply_suggestion(
                db, org_id=org_id, lead=lead, to_state=LeadState.COLD.value,
                reason=f"No reply for {days_silent} days",
                engine=ENGINE, confidence=0.7,
                input_summary=f"Silence sweep: {days_silent} days since last "
                              f"activity (org threshold {cold_after})",
            )
            if project is not None and project.status not in (
                ProjectStatus.CLOSED.value, ProjectStatus.LOST.value,
            ):
                project.status = ProjectStatus.ON_HOLD.value
                project.status_reason = "client gone quiet — lead suggested cold"
    return count


async def _sweep_payment_ladder(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """Polite, persistent, aimed at the right person (Workflow 25)."""
    schedule = org.payment_reminder_schedule or []
    count = 0
    invoices = (
        await db.execute(
            select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.status.in_(
                    [InvoiceStatus.SENT.value, InvoiceStatus.PART_PAID.value,
                     InvoiceStatus.OVERDUE.value]
                ),
                Invoice.due_date.is_not(None),
            )
        )
    ).scalars().all()
    for invoice in invoices:
        days_from_due = (now.date() - invoice.due_date.date()).days
        if days_from_due > 0 and invoice.status == InvoiceStatus.SENT.value:
            invoice.status = InvoiceStatus.OVERDUE.value
            await events.emit(
                db, org_id=org_id, event_type=EventType.INVOICE_OVERDUE.value,
                project_id=invoice.project_id, entity_type="invoice",
                entity_id=invoice.id, details={"days": days_from_due},
            )
        fired = list(invoice.ladder_fired or [])
        project = (
            await db.execute(select(Project).where(Project.id == invoice.project_id))
        ).scalar_one_or_none()
        if project is None:
            continue
        stakeholder = None
        if invoice.sent_to_stakeholder_id:
            stakeholder = (
                await db.execute(
                    select(Stakeholder).where(Stakeholder.id == invoice.sent_to_stakeholder_id)
                )
            ).scalar_one_or_none()
        for step in schedule:
            offset = int(step.get("offset", 0))
            if days_from_due < offset or offset in fired:
                continue
            fired.append(offset)
            invoice.ladder_fired = fired
            if step.get("action") == "call_task":
                sales_lead = await find_role_user(db, org_id, Role.SALES_LEAD.value)
                admin = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
                if sales_lead is not None:
                    db.add(
                        ActionItem(
                            org_id=org_id, lead_id=project.lead_id, project_id=project.id,
                            title=f"Call about unpaid invoice ({invoice.amount:,.0f}) — "
                            f"{abs(days_from_due)} days past due",
                            phase=Phase.PAYMENT.value, priority=TaskPriority.P1.value,
                            due_date=now + timedelta(days=2),
                            assignee_id=sales_lead.id, assigned_by="ai",
                            assignment_reason="Payment ladder exhausted — the call task is the sales lead's",
                            source=TaskSource.AI_REFINEMENT.value,
                            status=ActionItemStatus.OPEN.value, created_by="ai",
                        )
                    )
                    await notify(
                        db, org_id=org_id, user_id=sales_lead.id,
                        title="Payment ladder exhausted — call the client",
                        body=f"Invoice {invoice.amount:,.0f} is {days_from_due} days past due.",
                        kind="escalation", entity_type="invoice", entity_id=invoice.id,
                    )
                if admin is not None:
                    await notify(
                        db, org_id=org_id, user_id=admin.id,
                        title=f"Invoice {days_from_due} days overdue on {project.name}",
                        body=f"{invoice.amount:,.0f} {invoice.currency} outstanding.",
                        kind="escalation", entity_type="invoice", entity_id=invoice.id,
                    )
                count += 1
                continue
            if stakeholder is None:
                continue
            contact = (
                await db.execute(
                    select(Contact).where(Contact.id == stakeholder.contact_id)
                )
            ).scalar_one_or_none()
            if contact is None:
                continue
            cc: list[str] = []
            cc_rule = step.get("cc")
            if cc_rule:
                # The org's schedule names who gets copied — an influence
                # level ("decision_maker") or a stakeholder role in the
                # client's own vocabulary ("principal", "cfo"). Resolved
                # against this project's stakeholders; a role nobody holds
                # falls back to the decision maker (that is the intent of
                # copying someone on firm payment mail).
                influence_values = {i.value for i in Influence}
                copied = (
                    await db.execute(
                        select(Stakeholder).where(
                            Stakeholder.project_id == project.id,
                            Stakeholder.influence == cc_rule
                            if cc_rule in influence_values
                            else Stakeholder.role_at_client == cc_rule,
                        )
                    )
                ).scalars().first()
                if copied is None and cc_rule not in influence_values:
                    copied = (
                        await db.execute(
                            select(Stakeholder).where(
                                Stakeholder.project_id == project.id,
                                Stakeholder.influence == Influence.DECISION_MAKER.value,
                            )
                        )
                    ).scalars().first()
                if copied is not None and copied.id != stakeholder.id:
                    p_contact = (
                        await db.execute(
                            select(Contact).where(Contact.id == copied.contact_id)
                        )
                    ).scalar_one_or_none()
                    if p_contact is not None and p_contact.email:
                        cc.append(p_contact.email)
            tone = step.get("tone", "polite")
            from app.engines import communication_engine

            remaining = invoice.amount - await _paid_amount(db, invoice)
            await communication_engine.draft_client_message(
                db, org_id=org_id, kind=MessageKind.INVOICE.value,
                purpose=f"payment reminder ({tone})",
                lead_id=project.lead_id, contact=contact, project=project,
                stakeholder=stakeholder,
                subject=f"{project.name} — invoice "
                + ("due soon" if offset < 0 else f"{days_from_due} days past due"),
                cc=cc,
                instruction={
                    "heads_up": "A friendly heads-up that the invoice falls due soon.",
                    "polite": "A polite reminder that the invoice is now due.",
                    "firm": "A firm but courteous note; the amount is restated plainly.",
                }.get(tone, "A polite payment reminder."),
                facts={
                    "amount_outstanding": f"{remaining:,.0f} {invoice.currency}",
                    "due_date": f"{invoice.due_date:%d %b %Y}",
                    "computation": invoice.computation or "",
                },
                triggered_by="reminder_ladder",
            )
            db.add(
                Reminder(
                    org_id=org_id, target_type=ReminderTargetType.INVOICE.value,
                    target_id=invoice.id,
                    remind_user_id=project.sales_owner_id or "",
                    level=1 if offset <= 3 else 2,
                    channel=stakeholder.preferred_channel or "email",
                    scheduled_at=now, sent_at=now, note=tone,
                )
            )
            count += 1
    return count


async def _paid_amount(db: AsyncSession, invoice: Invoice) -> float:
    from app.models.finance import Payment

    return (
        await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0.0)).where(
                Payment.invoice_id == invoice.id
            )
        )
    ).scalar_one()


async def _sweep_overload(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """Workflow 13 — the quiet bottleneck. Alert card + rebalance proposal."""
    count = 0
    users = (
        await db.execute(
            select(User).where(User.org_id == org_id, User.is_active.is_(True))
        )
    ).scalars().all()
    dept_loads: dict[str, list[float]] = {}
    for user in users:
        load = (
            await db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.org_id == org_id,
                    ActionItem.assignee_id == user.id,
                    ActionItem.status.in_(OPEN_STATUSES),
                )
            )
        ).scalar_one()
        cap = max(user.max_open_tasks or 8, 1)
        dept_loads.setdefault(user.department or "other", []).append(load / cap)
        if load <= cap:
            continue
        recent = (
            await db.execute(
                select(func.count(ProgressEvent.id)).where(
                    ProgressEvent.org_id == org_id,
                    ProgressEvent.event_type == EventType.USER_OVERLOADED.value,
                    ProgressEvent.entity_id == user.id,
                    ProgressEvent.at >= now - timedelta(days=2),
                )
            )
        ).scalar_one()
        if recent:
            continue  # already alerted recently
        await events.emit(
            db, org_id=org_id, event_type=EventType.USER_OVERLOADED.value,
            entity_type="user", entity_id=user.id,
            details={"load": load, "cap": cap},
        )
        lead = await find_department_lead(db, org_id, user.department)
        if lead is None:
            continue
        from app.engines import assignment_engine

        proposals = await assignment_engine.rebalance_proposals(db, org_id=org_id, user=user)
        proposal_text = "\n".join(
            f"- '{p['title']}' ({p['priority']}) → {p['to_user_name']} ({p['reason']})"
            for p in proposals
        ) or "- no clean moves available; consider adding a member or extending dates"
        await notify(
            db, org_id=org_id, user_id=lead.id,
            title=f"{user.name} is overloaded ({load}/{cap})",
            body="Rebalance proposal:\n" + proposal_text,
            kind="escalation", entity_type="user", entity_id=user.id,
        )
        count += 1

    # A whole department overloaded → the org admin hears the honest number.
    for dept, loads in dept_loads.items():
        if len(loads) >= 2 and sum(loads) / len(loads) >= 0.9:
            admin = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
            if admin is not None:
                await notify(
                    db, org_id=org_id, user_id=admin.id,
                    title=f"{dept.capitalize()} team at {sum(loads)/len(loads)*100:.0f}% average load",
                    body="The AI never hides a capacity problem by silently "
                    "stretching due dates — hiring or priorities need a decision.",
                    kind="escalation",
                )
    return count


async def _sweep_revivals(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """Workflow 28: T-7 before revival_date, wake the lead with the story."""
    count = 0
    leads = (
        await db.execute(
            select(Lead).where(
                Lead.org_id == org_id,
                Lead.state == LeadState.LOST_FOR_NOW.value,
                Lead.revival_date.is_not(None),
                Lead.revival_fired_at.is_(None),
            )
        )
    ).scalars().all()
    for lead in leads:
        if now >= lead.revival_date - timedelta(days=7):
            lead.revival_fired_at = now
            await events.emit(
                db, org_id=org_id, event_type=EventType.LEAD_REVIVED.value,
                entity_type="lead", entity_id=lead.id,
                details={"revival_date": lead.revival_date.isoformat()},
            )
            owner = await get_user(db, org_id, lead.owner_id)
            if owner is None:
                owner = await find_role_user(db, org_id, Role.SALES_AGENT.value)
            if owner is not None:
                from app.engines import knowledge_engine

                story = await knowledge_engine.replay_story(db, org_id=org_id, lead=lead)
                await notify(
                    db, org_id=org_id, user_id=owner.id,
                    title=f"Revival card: {lead.name}",
                    body=(lead.revival_context or "") + "\n\n" + story,
                    kind="general", entity_type="lead", entity_id=lead.id,
                )
                db.add(
                    ActionItem(
                        org_id=org_id, lead_id=lead.id,
                        title=f"Re-open {lead.name} — promised return "
                        f"({lead.revival_date:%d %b %Y})",
                        phase=Phase.SALES.value, priority=TaskPriority.P2.value,
                        due_date=lead.revival_date,
                        assignee_id=owner.id, assigned_by="ai",
                        assignment_reason="Relationship owner wakes the sleeping lead",
                        source=TaskSource.AI_REFINEMENT.value,
                        status=ActionItemStatus.OPEN.value, created_by="ai",
                    )
                )
                count += 1
    return count


async def _sweep_external_waits(
    db: AsyncSession, org_id: str, org: OrgSettings, now: datetime
) -> int:
    """Vendor promises are watched like due dates — but the chase target is
    OUR coordinator, never the vendor (Workflow 24)."""
    count = 0
    tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.status.in_(OPEN_STATUSES),
                ActionItem.external_wait.is_not(None),
            )
        )
    ).scalars().all()
    for task in tasks:
        wait = task.external_wait or {}
        promised = wait.get("promised_date")
        if not promised:
            continue
        promised_d = datetime.fromisoformat(promised).date()
        days_to = (promised_d - now.date()).days
        if days_to in (3, 1):
            chase_id = wait.get("chase_contact") or task.assignee_id
            chaser = await get_user(db, org_id, chase_id)
            already = (
                await db.execute(
                    select(func.count(Reminder.id)).where(
                        Reminder.target_type == ReminderTargetType.ACTION_ITEM.value,
                        Reminder.target_id == task.id,
                        Reminder.note == f"vendor T-{days_to}",
                    )
                )
            ).scalar_one()
            if chaser is not None and not already:
                vendor = wait.get("vendor_name") or wait.get("vendor_id") or "the vendor"
                await notify(
                    db, org_id=org_id, user_id=chaser.id,
                    title=f"Vendor check (T-{days_to}): {task.title}",
                    body=f"{vendor} promised {promised_d:%d %b} — confirm it's on track.",
                    kind="reminder", entity_type="action_item", entity_id=task.id,
                )
                db.add(
                    Reminder(
                        org_id=org_id,
                        target_type=ReminderTargetType.ACTION_ITEM.value,
                        target_id=task.id, remind_user_id=chaser.id,
                        level=1, channel="push", scheduled_at=now, sent_at=now,
                        note=f"vendor T-{days_to}",
                    )
                )
                count += 1
    return count
