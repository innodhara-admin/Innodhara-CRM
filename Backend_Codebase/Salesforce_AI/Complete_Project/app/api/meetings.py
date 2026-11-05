"""Meetings: upload the recording, watch pipeline progress, review the
extracted action items (the optional human gate of Figure 5)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.constants import ActionItemStatus, MeetingPlanState, MeetingStatus
from app.core.context import OrgContext
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.database import get_db
from app.engines.planner_engine import _title_similarity
from app.jobs.queue import PRIORITY_BACKGROUND, job_queue
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.lead import ConsentRecord
from app.models.meeting import Meeting, Transcript
from app.services import audit_service, lead_service, storage

# Same threshold as the F22 adoption fence and the F9 duplicate fence, so
# "a possible duplicate" and "the same work" agree by construction.
_DUP_THRESHOLD = 0.7

router = APIRouter(prefix="/meetings", tags=["meetings"])

_MAX_AUDIO_BYTES = 200 * 1024 * 1024
# F40: how stale a consent record may be and still belong to this recording.
# Generous on purpose — a long meeting plus a patchy-signal upload is normal, and
# refusing a legitimate upload is its own harm. But not unbounded: attaching a
# months-old consent row to today's recording would be the same defect wearing
# different clothes, a proof that does not belong to the thing it proves.
_CONSENT_MAX_AGE = timedelta(hours=24)


class ReviewItem(BaseModel):
    id: str | None = None       # existing item id; None = user-added item
    title: str
    description: str | None = None
    keep: bool = True


class ReviewConfirmRequest(BaseModel):
    items: list[ReviewItem]


def _meeting_dict(meeting: Meeting) -> dict:
    return {
        "id": meeting.id,
        "lead_id": meeting.lead_id,
        "status": meeting.status,
        "duration_seconds": meeting.duration_seconds,
        "consent_captured": meeting.consent_captured,
        "state_suggestion": meeting.state_suggestion,
        "error": meeting.error,
        "started_at": meeting.started_at.isoformat() if meeting.started_at else None,
        "audio_available": bool(meeting.audio_path),
        # Where the plan for this recording stands ("Approve plan", 1 Oct
        # 2026); null when no Planner was started for it. Additive.
        "plan_state": meeting.plan_state,
        "plan_note": meeting.plan_note,
    }


@router.post("/upload")
async def upload_meeting(
    lead_id: str = Form(...),
    consent_confirmed: bool = Form(...),
    duration_seconds: int | None = Form(default=None),
    title: str | None = Form(default=None),
    # Optional: recording from inside a project pins the meeting to it. Left
    # out (the old contract), the Planner resolves it from the lead's live
    # projects instead of assuming a first meeting.
    project_id: str | None = Form(default=None),
    # Optional, and additive on purpose: the shipping app sends nothing and
    # gets exactly the behaviour it has today. Only a caller that asks for
    # "relationship" gets the light pipeline. `/schedule` and `/notes` have
    # carried this field all along; `/upload` never did, so a *recorded*
    # catch-up had no way to say what it was.
    meeting_type: str | None = Form(default=None),
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    """Upload the recording and start the background pipeline. The app polls
    GET /meetings/{id} to show progress (never a frozen screen — §11.5)."""
    if not consent_confirmed:
        raise ValidationFailedError(
            "Consent must be confirmed before a recording is processed (DPDP, doc §14)"
        )
    await lead_service.get_workable_lead(db, ctx.org_id, lead_id)
    audio = await file.read()
    if not audio:
        raise ValidationFailedError("Empty audio file")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise ValidationFailedError("Audio too large (max 200 MB)")

    # Nothing is written to disk until the request is known to be acceptable.
    # `save_bytes` used to run first, so every refusal below left real client
    # audio in STORAGE_DIR with no `Meeting` row pointing at it — and
    # `retention_service` sweeps by walking meetings, so an orphan is past every
    # retention window the moment it is created and is never collected. The
    # reachable case is `UploadMeetingWorker`'s retry after a lost response:
    # correctly refused (consent is single-use), and it used to cost a second
    # copy of the recording.
    # F40 — LINK the consent the human actually captured; never manufacture one.
    #
    # This used to write a second, contradictory record with method="in_app" and
    # note="Confirmed at upload" hardcoded. Observed on the device: the user chose
    # *verbal* ("Principal Nair and team agreed verbally") and the row attached to
    # the meeting said "in_app / Confirmed at upload". Anyone auditing consent for
    # that recording read the fabricated one — and the fabricated value was the
    # more defensible-sounding of the two, which is exactly the direction an audit
    # trail must never drift.
    #
    # Data Model §3.5 breaks twice over: `method` is "how consent was captured",
    # and rows are "captured BEFORE the recording started" and "never edited" —
    # but this row was invented at UPLOAD, i.e. after. Tapping Upload is not a
    # consent interaction.
    #
    # Setting `meeting_id` on the pre-existing row is linking, not editing: the
    # method, note, captured_by and captured_at of the human's own record are all
    # left exactly as they were.
    consent = (
        await db.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.org_id == ctx.org_id,
                ConsentRecord.lead_id == lead_id,
                ConsentRecord.meeting_id.is_(None),
                ConsentRecord.captured_at >= utcnow() - _CONSENT_MAX_AGE,
            )
            .order_by(ConsentRecord.captured_at.desc())
        )
    ).scalars().first()
    if consent is None:
        # Closes F40's second gap: `consent_confirmed` is a self-asserted caller
        # flag that the API used to trust while generating the evidence for it.
        # Any direct call with consent_confirmed=true produced a complete-looking
        # consent trail for a recording nobody ever consented to. Now the proof
        # has to exist, captured before the recording, or there is no upload.
        raise ValidationFailedError(
            "No consent record was captured for this lead before the recording "
            "(DPDP, doc §14). Record how the client agreed via "
            "POST /leads/{lead_id}/consent first — consent is proof captured "
            "beforehand, not a checkbox at upload."
        )
    audio_path = storage.save_bytes(
        ctx.org_id, storage.CATEGORY_AUDIO, file.filename or "meeting.m4a", audio
    )
    meeting = Meeting(
        org_id=ctx.org_id,
        lead_id=lead_id,
        agent_id=ctx.user_id,
        title=title,
        audio_path=audio_path,
        audio_mime=file.content_type or "audio/mpeg",
        project_id=project_id,
        meeting_type=meeting_type,
        duration_seconds=duration_seconds,
        consent_captured=True,
        status=MeetingStatus.UPLOADED.value,
    )
    db.add(meeting)
    await db.flush()

    consent.meeting_id = meeting.id
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="meeting.uploaded",
        entity_type="meeting", entity_id=meeting.id,
        detail={"bytes": len(audio)},
    )
    await db.commit()

    await job_queue.enqueue(
        "process_meeting",
        {"meeting_id": meeting.id},
        org_id=ctx.org_id,
        priority=PRIORITY_BACKGROUND,
    )
    return _meeting_dict(meeting)


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found")
    transcript = (
        await db.execute(select(Transcript).where(Transcript.meeting_id == meeting_id))
    ).scalar_one_or_none()
    items = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == ctx.org_id, ActionItem.meeting_id == meeting_id
            )
        )
    ).scalars().all()
    return {
        **_meeting_dict(meeting),
        "transcript": {
            "text": transcript.text,
            "summary": transcript.summary,
            "language": transcript.language,
            "confidence": transcript.confidence,
            "low_confidence": transcript.low_confidence,
            "word_count": transcript.word_count,
        }
        if transcript
        else None,
        "action_items": [
            # due_date travels with the item: the meeting screen was listing
            # "Prepare for follow-up meeting" with no sign of the 27th the
            # transcript agreed on ("action items missed meeting dates",
            # 19 Sep 2026), although extraction had resolved it.
            {"id": i.id, "title": i.title, "description": i.description,
             "status": i.status,
             "due_date": i.due_date.isoformat() if i.due_date else None}
            for i in items
            # The Planner's own tasks that are not live (waiting for "Approve
            # plan", left out, or dropped with a turned-down plan) are not
            # what this meeting agreed. Listing them here is what made BS
            # Carmel School's 2 confirmed items read as 5 (29 Sep 2026).
            if not (i.created_by == "ai" and i.status in _NOT_LIVE)
        ],
    }


_NOT_LIVE = (
    ActionItemStatus.PENDING_REVIEW.value,
    ActionItemStatus.CANCELLED.value,
    ActionItemStatus.SUPERSEDED.value,
)


@router.post("/{meeting_id}/retry")
async def retry_meeting(
    meeting_id: str,
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    """Retry a failed pipeline (poor signal / model hiccup — doc §12)."""
    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found")
    if meeting.status != MeetingStatus.FAILED.value:
        raise ConflictError(f"Meeting is '{meeting.status}', not failed")
    meeting.status = MeetingStatus.UPLOADED.value
    meeting.error = None
    await db.commit()
    await job_queue.enqueue(
        "process_meeting", {"meeting_id": meeting.id},
        org_id=ctx.org_id, priority=PRIORITY_BACKGROUND,
    )
    return {"requeued": True}


def _review_items_query(org_id: str, meeting_id: str):
    """The review gate's business is what the AI heard in THIS meeting.

    `plan_version_added` is not null on tasks a plan version owns; those are
    also created `pending_review` and carry the meeting id, but they belong to
    the plan and only go live through `activate_plan` (which staffs them and
    wires dependencies). Letting them show up here would let a confirm flip
    them open behind the plan's back, or silently cancel them as "not echoed"."""
    return select(ActionItem).where(
        ActionItem.org_id == org_id,
        ActionItem.meeting_id == meeting_id,
        ActionItem.status == ActionItemStatus.PENDING_REVIEW.value,
        ActionItem.plan_version_added.is_(None),
    )


@router.get("/{meeting_id}/review")
async def get_review_items(
    meeting_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found")
    items = (await db.execute(_review_items_query(ctx.org_id, meeting_id))).scalars().all()
    dup_hints = await _duplicate_hints(db, ctx.org_id, meeting, items)
    return {
        "meeting_status": meeting.status,
        "items": [
            {
                "id": i.id,
                "title": i.title,
                "description": i.description,
                # F24: the open task on this lead (from an earlier meeting or
                # added by hand) that this item looks like, so the human can
                # drop a restated commitment instead of opening a twin. None
                # when nothing looks like it. Advisory only — never auto-acts.
                "possible_duplicate_of": dup_hints.get(i.id),
            }
            for i in items
        ],
    }


async def _duplicate_hints(
    db: AsyncSession, org_id: str, meeting: Meeting, items: list[ActionItem]
) -> dict[str, dict]:
    """Per extracted item, the open task on the same lead it most resembles
    (finding F24). Candidates are the lead's already-open rows from a DIFFERENT
    meeting, or ones created by hand — never this meeting's own items. Same
    `_title_similarity` and 0.7 threshold as the F22/F9 fences, so a warning
    here and an actual merge elsewhere agree by construction. Decides nothing:
    the human keeps/drops/edits at the gate exactly as before."""
    if not items or not meeting.lead_id:
        return {}
    candidates = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.lead_id == meeting.lead_id,
                ActionItem.status.in_(
                    (ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value)
                ),
                or_(ActionItem.meeting_id.is_(None), ActionItem.meeting_id != meeting.id),
            )
        )
    ).scalars().all()
    hints: dict[str, dict] = {}
    for item in items:
        best: ActionItem | None = None
        best_score = 0.0
        for row in candidates:
            score = _title_similarity(item.title or "", row.title or "")
            if score > best_score:
                best, best_score = row, score
        if best is not None and best_score >= _DUP_THRESHOLD:
            hints[item.id] = {
                "id": best.id,
                "title": best.title,
                "at": best.created_at.strftime("%d %b") if best.created_at else None,
            }
    return hints


@router.post("/{meeting_id}/review/confirm")
async def confirm_review(
    meeting_id: str,
    body: ReviewConfirmRequest,
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    """Human review of extracted items: edit, add, remove, confirm (doc §9.1.4).

    Accepted ONCE (BS Carmel School, 29 Sep 2026: confirmed from two phones
    42 seconds apart, the second confirm re-created both kept items without
    their dates and started the Planner again). The first thing written is a
    conditional status change, so of two confirms only one can win it, even
    at the same moment; the other changes nothing and says so."""
    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found")
    claimed = await db.execute(
        update(Meeting)
        .where(
            Meeting.id == meeting_id,
            Meeting.org_id == ctx.org_id,
            Meeting.status == MeetingStatus.REVIEW_PENDING.value,
        )
        .values(status=MeetingStatus.COMPLETED.value)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        await db.rollback()
        await db.refresh(meeting)
        return {
            "confirmed": True,
            "already_confirmed": True,
            "action_items_saved": 0,
            "planning": False,
            "plan_state": meeting.plan_state,
        }
    pending = (
        await db.execute(_review_items_query(ctx.org_id, meeting_id))
    ).scalars().all()
    pending_by_id = {i.id: i for i in pending}

    kept = 0
    seen_ids: set[str] = set()
    confirmed: list[dict] = []          # what the human actually agreed to
    for entry in body.items:
        if entry.id and entry.id in pending_by_id:
            item = pending_by_id[entry.id]
            seen_ids.add(entry.id)
            if not entry.keep:
                item.status = ActionItemStatus.CANCELLED.value
                continue
            item.title = entry.title[:490]
            item.description = entry.description
            item.status = ActionItemStatus.OPEN.value
            kept += 1
            confirmed.append({
                "title": item.title, "description": item.description,
                "due_date": item.due_date,
            })
        elif entry.id:
            # An id that is not one of this review's pending items (a stale
            # screen, an item already decided). Never written as a new task.
            continue
        elif entry.keep:
            db.add(
                ActionItem(
                    org_id=ctx.org_id, lead_id=meeting.lead_id, meeting_id=meeting_id,
                    title=entry.title[:490], description=entry.description,
                    owner_id=ctx.user_id, status=ActionItemStatus.OPEN.value,
                    created_by=ctx.user_id,
                )
            )
            kept += 1
            confirmed.append({
                "title": entry.title[:490], "description": entry.description,
                "due_date": None,
            })
    # Anything the client didn't echo back is treated as removed.
    for item_id, item in pending_by_id.items():
        if item_id not in seen_ids:
            item.status = ActionItemStatus.CANCELLED.value

    meeting.status = MeetingStatus.COMPLETED.value
    if kept:
        meeting.plan_state = MeetingPlanState.PLANNING.value
        meeting.plan_note = None
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="meeting.review_confirmed",
        entity_type="meeting", entity_id=meeting_id, detail={"kept": kept},
    )
    await db.commit()

    # The human has said what this meeting really agreed; NOW the Planner runs
    # the same Workflow-1 machine the typed-notes path runs (finding F9), built
    # around the confirmed to-dos instead of re-deriving them. Backgrounded:
    # planning is a model call, and this request must not hang on it.
    planning_started = False
    if kept:
        await job_queue.enqueue(
            "plan_meeting",
            {"meeting_id": meeting_id, "agreed_tasks": [
                {**c, "due_date": c["due_date"].isoformat() if c["due_date"] else None}
                for c in confirmed
            ]},
            org_id=ctx.org_id,
            priority=PRIORITY_BACKGROUND,
        )
        planning_started = True
    return {
        "confirmed": True,
        "already_confirmed": False,
        "action_items_saved": kept,
        # Additive: older apps ignore it, newer ones can say "the Planner is
        # working on it" instead of implying the meeting is finished with.
        "planning": planning_started,
        "plan_state": meeting.plan_state,
    }


# ─────────────────────────────────────────────────────────────────────────────
# "Approve plan" (design agreed 1 Oct 2026): after the review, the Planner's
# plan for a recorded meeting waits for the person who recorded it
# ─────────────────────────────────────────────────────────────────────────────


class PlanApproveRequest(BaseModel):
    # The Planner's tasks the person switched off. Everything else stays on,
    # so an empty list (or an older client) approves the whole plan.
    skip_task_ids: list[str] = []


async def _own_meeting(db: AsyncSession, ctx: OrgContext, meeting_id: str) -> Meeting:
    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.id == meeting_id, Meeting.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found")
    return meeting


def _day(value) -> str:
    return f"{value:%d %b}" if value else "no date"


async def _change_lines(db: AsyncSession, plan, project) -> list[str]:
    """The plan's other changes as short lines: a new project, moved dates,
    removals, reopened work, a new project window, a moved demo."""
    from app.models.project import ClientCommitment

    lines: list[str] = []
    if plan.version == 1:
        lines.append(f"New project: {project.name}")
    ops = plan.pending_ops or []
    ids = [op.get("task_id") for op in ops if op.get("task_id")]
    titles = {}
    if ids:
        rows = (await db.execute(select(ActionItem).where(ActionItem.id.in_(ids)))).scalars()
        titles = {r.id: r.title for r in rows}
    for op in ops:
        kind = op.get("op")
        title = titles.get(op.get("task_id"), "A task")
        reason = f": {op['reason']}" if op.get("reason") else ""
        if kind == "redate":
            old = op.get("old_due")
            new = op.get("new_due")
            lines.append(f"'{title}' moved "
                         + (f"{_day(_iso(old))} to {_day(_iso(new))}" if old
                            else f"to {_day(_iso(new))}"))
        elif kind == "cancel":
            lines.append(f"'{title}' removed{reason}")
        elif kind == "reopen":
            lines.append(f"'{title}' reopened{reason}")
        elif kind == "unblock":
            lines.append(f"'{title}' no longer blocked")
        elif kind == "set_window":
            parts = []
            if op.get("start"):
                parts.append(f"starts {_day(_iso(op['start']))}")
            if op.get("end"):
                parts.append(f"ends {_day(_iso(op['end']))}")
            lines.append("Project " + " and ".join(parts))
        elif kind == "reschedule_demo":
            lines.append(f"Demo moved to {_day(_iso(op.get('new_date')))}"
                         + (f" at {op['new_time']}" if op.get("new_time") else ""))
        elif kind == "renegotiate_commitment":
            row = (await db.execute(select(ClientCommitment).where(
                ClientCommitment.id == op.get("commitment_id")))).scalar_one_or_none()
            lines.append(f"Promise '{row.text if row else 'to the client'}' "
                         f"now due {_day(_iso(op.get('new_due')))}")
    if plan.trigger == "new_meeting" and plan.changes_from_previous:
        for line in plan.changes_from_previous.splitlines():
            if line.strip() and line.strip() not in lines:
                lines.append(line.strip())
    return lines


def _iso(value):
    from datetime import datetime as _dt

    try:
        return _dt.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def _plan_view(db: AsyncSession, ctx: OrgContext, meeting: Meeting) -> dict:
    from app.core.constants import PlanStatus
    from app.engines import planner_engine
    from app.models.project import Project

    hold, plan = await planner_engine.held_meeting_plan(
        db, org_id=ctx.org_id, meeting_id=meeting.id)
    state = meeting.plan_state
    if (plan is not None and plan.status == PlanStatus.ACTIVE.value
            and state in (MeetingPlanState.READY.value,
                          MeetingPlanState.SENT_FOR_APPROVAL.value)):
        state = MeetingPlanState.APPROVED.value
    view: dict = {
        "meeting_id": meeting.id,
        "state": state,
        "note": meeting.plan_note,
        "approval_id": hold.id if hold else None,
        "can_approve": bool(hold is not None and hold.status == "pending"
                            and hold.requested_from_user_id == ctx.user_id
                            and state == MeetingPlanState.READY.value),
        "plan_id": None, "version": None, "project_id": None, "project_name": None,
        "new_project": False, "tasks": [], "changes": [],
    }
    if plan is None or state not in (
        MeetingPlanState.READY.value, MeetingPlanState.SENT_FOR_APPROVAL.value,
        MeetingPlanState.APPROVED.value,
    ):
        return view
    project = (
        await db.execute(select(Project).where(Project.id == plan.project_id))
    ).scalar_one()
    tasks = await planner_engine.plan_tasks(db, plan)
    ids = {t.id for t in tasks}
    view.update({
        "plan_id": plan.id, "version": plan.version, "project_id": project.id,
        "project_name": project.name, "new_project": plan.version == 1,
        "changes": await _change_lines(db, plan, project),
        "tasks": [
            {
                "id": t.id, "title": t.title, "description": t.description,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "phase": t.phase, "priority": t.priority, "status": t.status,
                "depends_on": [d for d in (t.depends_on_ids or []) if d in ids],
                # Accepted at the review gate: shown greyed, cannot be left out.
                "confirmed": planner_engine.is_confirmed_task(t),
                # Promised to the client in the meeting: locked on.
                "promised_to_client": bool(t.client_commitment_id),
            }
            for t in tasks
        ],
    })
    return view


@router.get("/{meeting_id}/plan")
async def get_meeting_plan(
    meeting_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Where this recording's plan stands, and the plan itself when there is
    one to show: what the loader polls and what the plan sheet lists."""
    meeting = await _own_meeting(db, ctx, meeting_id)
    return await _plan_view(db, ctx, meeting)


@router.post("/{meeting_id}/plan/approve")
async def approve_meeting_plan(
    meeting_id: str,
    body: PlanApproveRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """"Approve plan" with the tasks left on. Once only: a double tap or a
    second phone gets the outcome of the first, with `already: true`."""
    from app.core.constants import PlanStatus
    from app.core.exceptions import PermissionDeniedError
    from app.engines import planner_engine
    from app.models.comms import Approval

    meeting = await _own_meeting(db, ctx, meeting_id)
    hold, plan = await planner_engine.held_meeting_plan(
        db, org_id=ctx.org_id, meeting_id=meeting.id)
    if hold is None or plan is None:
        raise NotFoundError("There is no plan waiting for this meeting")
    if hold.requested_from_user_id != ctx.user_id:
        raise PermissionDeniedError(
            "Only the person who recorded this meeting can approve its plan")

    async def outcome(already: bool) -> dict:
        view = await _plan_view(db, ctx, meeting)
        approver = None
        if view["state"] == MeetingPlanState.SENT_FOR_APPROVAL.value:
            from app.engines.common import get_user

            waiting = (
                await db.execute(
                    select(Approval).where(
                        Approval.org_id == ctx.org_id,
                        Approval.entity_type == "plan_change",
                        Approval.entity_id == plan.id,
                        Approval.status == "pending",
                    ).order_by(Approval.requested_at.desc())
                )
            ).scalars().first()
            user = await get_user(db, ctx.org_id, waiting.requested_from_user_id) \
                if waiting else None
            approver = user.name if user else None
        return {"state": view["state"], "note": view["note"], "already": already,
                "approver_name": approver, "skipped": 0}

    replaced = (hold.status == "expired"
                or meeting.plan_state == MeetingPlanState.SUPERSEDED.value)
    if replaced:
        raise ConflictError(meeting.plan_note
                            or "A newer plan replaced this one before it was approved.")
    if hold.status != "pending" or plan.status != PlanStatus.PENDING_REVIEW.value:
        # Already approved (or turned down): the first decision stands.
        return await outcome(already=True)

    skipped_rows: list[ActionItem] = []

    tasks = {t.id: t for t in await planner_engine.plan_tasks(db, plan)}
    for task_id in dict.fromkeys(body.skip_task_ids):
        task = tasks.get(task_id)
        if task is None:
            raise ValidationFailedError("A task you switched off is not part of this plan.")
        refusal = planner_engine.refuse_skip_reason(task)
        if refusal:
            raise ValidationFailedError(refusal)
        skipped_rows.append(task)

    claimed = await db.execute(
        update(Approval)
        .where(Approval.id == hold.id, Approval.status == "pending")
        .values(status="approved", decided_at=utcnow(),
                decision_note=f"Approve plan: {len(skipped_rows)} task(s) left out")
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount == 0:
        await db.rollback()
        await db.refresh(meeting)
        return await outcome(already=True)
    result = await planner_engine.approve_meeting_plan(
        db, org_id=ctx.org_id, meeting_id=meeting.id,
        skip_ids=[t.id for t in skipped_rows], by_user_id=ctx.user_id,
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="meeting.plan_approved",
        entity_type="meeting", entity_id=meeting.id,
        detail={"skipped": [t.id for t in skipped_rows], "state": result["state"]},
    )
    await db.commit()
    return {"state": result["state"], "note": meeting.plan_note, "already": False,
            "approver_name": result.get("approver_name"),
            "skipped": result["skipped"]}


@router.post("/{meeting_id}/plan/retry")
async def retry_meeting_plan(
    meeting_id: str,
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    """Plan again after the Planner failed: the same confirmed to-dos."""
    meeting = await _own_meeting(db, ctx, meeting_id)
    if meeting.plan_state != MeetingPlanState.FAILED.value:
        raise ConflictError(f"The plan is '{meeting.plan_state}', not failed")
    confirmed = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == ctx.org_id,
                ActionItem.meeting_id == meeting.id,
                ActionItem.plan_version_added.is_(None),
                ActionItem.status == ActionItemStatus.OPEN.value,
            )
        )
    ).scalars().all()
    meeting.plan_state = MeetingPlanState.PLANNING.value
    meeting.plan_note = None
    await job_queue.enqueue(
        "plan_meeting",
        {"meeting_id": meeting.id, "agreed_tasks": [
            {"title": i.title, "description": i.description,
             "due_date": i.due_date.isoformat() if i.due_date else None}
            for i in confirmed
        ]},
        org_id=ctx.org_id, priority=PRIORITY_BACKGROUND, db=db,
    )
    await db.commit()
    return {"requeued": True, "plan_state": meeting.plan_state}


# ─────────────────────────────────────────────────────────────────────────────
# Workflow-layer entry points: scheduled meetings and typed/dictated notes
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime  # noqa: E402

from app.core.constants import MeetingType  # noqa: E402  (also used above)
from app.engines import planner_engine  # noqa: E402


class ScheduleMeetingRequest(BaseModel):
    lead_id: str
    title: str | None = None
    started_at: datetime
    meeting_type: str = MeetingType.FIRST_VISIT.value
    project_id: str | None = None
    agent_id: str | None = None


@router.post("/schedule")
async def schedule_meeting(
    body: ScheduleMeetingRequest,
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    """Book a meeting in advance (Workflow 1.2) — mirrored to the agent's
    calendar as a booking."""
    await lead_service.get_workable_lead(db, ctx.org_id, body.lead_id)
    agent_id = body.agent_id or ctx.user_id
    meeting = Meeting(
        org_id=ctx.org_id,
        lead_id=body.lead_id,
        agent_id=agent_id,
        title=body.title,
        status=MeetingStatus.SCHEDULED.value,
        started_at=body.started_at,
        meeting_type=body.meeting_type,
        project_id=body.project_id,
    )
    db.add(meeting)
    await db.flush()
    from app.engines import resource_engine
    from app.services.notification_service import notify

    await resource_engine.book(
        db, org_id=ctx.org_id, user_id=agent_id, kind="travel",
        date_from=body.started_at, date_to=body.started_at,
        project_id=body.project_id, source_type="demo", source=meeting.id,
        note=f"Meeting: {body.title or body.lead_id}",
    )
    if agent_id != ctx.user_id:
        await notify(
            db, org_id=ctx.org_id, user_id=agent_id,
            title=f"Meeting booked: {body.title or 'client visit'}",
            body=f"{body.started_at:%a %d %b %H:%M}",
            kind="general", entity_type="meeting", entity_id=meeting.id,
        )
    await db.commit()
    return _meeting_dict(meeting)


class MeetingNotesRequest(BaseModel):
    lead_id: str
    text: str
    title: str | None = None
    meeting_type: str = MeetingType.FIRST_VISIT.value
    project_id: str | None = None
    meeting_id: str | None = None      # fill in a previously scheduled meeting
    consent_confirmed: bool = False    # notes need no consent; audio does
    attendee_user_ids: list[str] = []
    attendee_stakeholder_ids: list[str] = []


@router.post("/notes")
async def meeting_from_notes(
    body: MeetingNotesRequest,
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    """The manual path (recording refused, or a dictated summary): typed
    notes are the transcript source, and the Planner runs the same merge —
    the engines reconcile manual work, they never fight it."""
    await lead_service.get_workable_lead(db, ctx.org_id, body.lead_id)
    if body.meeting_id:
        meeting = (
            await db.execute(
                select(Meeting).where(
                    Meeting.id == body.meeting_id, Meeting.org_id == ctx.org_id
                )
            )
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError("Meeting not found")
    else:
        meeting = Meeting(
            org_id=ctx.org_id,
            lead_id=body.lead_id,
            agent_id=ctx.user_id,
            title=body.title,
            status=MeetingStatus.TRANSCRIBED.value,
            meeting_type=body.meeting_type,
            project_id=body.project_id,
        )
        db.add(meeting)
        await db.flush()
    meeting.notes_text = body.text
    meeting.attendee_user_ids = body.attendee_user_ids or [ctx.user_id]
    meeting.attendee_stakeholder_ids = body.attendee_stakeholder_ids
    if body.project_id:
        meeting.project_id = body.project_id
    transcript = Transcript(
        org_id=ctx.org_id, meeting_id=meeting.id, text=body.text,
        summary=None, language="typed", confidence=1.0, low_confidence=False,
        word_count=len(body.text.split()),
    )
    db.add(transcript)
    await db.flush()

    # A typed catch-up takes the same light path a recorded one does. This
    # endpoint calls the Planner directly rather than going through
    # `pipelines.process_meeting`, so the branch has to exist here as well or
    # typing up a friendly call would build a project plan.
    if meeting.meeting_type == MeetingType.RELATIONSHIP.value:
        from app.jobs.pipelines import process_relationship_meeting
        from app.models.organisation import Organisation

        org = (
            await db.execute(
                select(Organisation).where(Organisation.id == ctx.org_id)
            )
        ).scalar_one()
        lead = await lead_service.get_lead(db, ctx.org_id, body.lead_id)
        light = await process_relationship_meeting(
            db, meeting=meeting, transcript=transcript, lead=lead, org=org,
        )
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id,
            action="meeting.catch_up_processed",
            entity_type="meeting", entity_id=meeting.id, detail=light,
        )
        await db.commit()
        # `planner` is null and says so: the app reads that key, and a catch-up
        # genuinely has no plan rather than an empty one.
        return {"meeting": _meeting_dict(meeting), "planner": None,
                "relationship": light}

    result = await planner_engine.process_meeting(
        db, org_id=ctx.org_id, meeting=meeting, text=body.text
    )
    meeting.status = MeetingStatus.COMPLETED.value
    from app.engines import events as event_stream
    from app.core.constants import EventType

    await event_stream.emit(
        db, org_id=ctx.org_id, event_type=EventType.MEETING_PROCESSED.value,
        project_id=meeting.project_id, entity_type="meeting", entity_id=meeting.id,
        actor=ctx.user_id, details={"action": result.get("action", "")},
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="meeting.notes_processed",
        entity_type="meeting", entity_id=meeting.id, detail=result,
    )
    await db.commit()
    return {"meeting": _meeting_dict(meeting), "planner": result}
