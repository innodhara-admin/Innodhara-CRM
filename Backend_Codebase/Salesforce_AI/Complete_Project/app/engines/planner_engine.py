"""Planner Engine — turns meetings, replies and progress into a versioned
global action plan (30-Workflows §4 engine 1).

Its output is always a NEW version with an AI-written diff — never an
in-place edit. It extracts client commitments, detects conflicts between
sources and holds the plan until a human resolves them, and runs a
feasibility pass (via the Resource & Calendar Engine) before anything is
promised to a client.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ActionItemStatus,
    ApprovalEntityType,
    CommitmentStatus,
    ConflictStatus,
    DecisionType,
    EventType,
    MeetingPlanState,
    Phase,
    PlanStatus,
    PlanTrigger,
    ProjectStatus,
    Role,
    TaskPriority,
    TaskSource,
)
from app.ai.planning import norm_role
from app.core.exceptions import ConflictError
from app.engines import events, nlu, resource_engine
from app.engines.common import (
    find_role_user,
    get_org_settings,
    get_user,
    record_decision,
)
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.comms import Approval
from app.models.lead import Contact, Lead, ClientIntelligence
from app.models.meeting import Meeting
from app.models.organisation import OrgSettings
from app.models.program import PricingTable, Program
from app.models.project import (
    ActionPlan,
    ClientCommitment,
    Conflict,
    Playbook,
    Project,
    ProjectMember,
    Stakeholder,
)
from app.models.user import User
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "planner"


# ─────────────────────────────────────────────────────────────────────────────
# Plan mechanics
# ─────────────────────────────────────────────────────────────────────────────


async def _next_version(db: AsyncSession, project_id: str) -> int:
    from sqlalchemy import func

    current = (
        await db.execute(
            select(func.max(ActionPlan.version)).where(ActionPlan.project_id == project_id)
        )
    ).scalar_one()
    return (current or 0) + 1


def _has_cycle(tasks: list[ActionItem]) -> bool:
    """Circular-dependency detection — the Planner refuses to activate a plan
    containing cycles (Workflow 11)."""
    graph = {t.id: list(t.depends_on_ids or []) for t in tasks}
    seen: dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(node: str) -> bool:
        state = seen.get(node)
        if state == 0:
            return True  # back-edge → cycle
        if state == 1:
            return False
        seen[node] = 0
        for dep in graph.get(node, []):
            if dep in graph and visit(dep):
                return True
        seen[node] = 1
        return False

    return any(visit(n) for n in graph)


async def open_conflicts(db: AsyncSession, project_id: str) -> list[Conflict]:
    return (
        await db.execute(
            select(Conflict).where(
                Conflict.project_id == project_id,
                Conflict.status == ConflictStatus.OPEN.value,
            )
        )
    ).scalars().all()


async def newer_active_plan(
    db: AsyncSession, *, project_id: str, version: int
) -> ActionPlan | None:
    """The plan that already replaced this one, if any.

    Data Model §4.3 defines `superseded` as "replaced by a **newer** version" and
    `current_plan_version` as "which version is live **right now**". Both become
    false statements the moment an older plan is activated over a newer one, so
    this is the single question every activation has to ask (F49).
    """
    return (
        await db.execute(
            select(ActionPlan)
            .where(
                ActionPlan.project_id == project_id,
                ActionPlan.status == PlanStatus.ACTIVE.value,
                ActionPlan.version > version,
            )
            .order_by(ActionPlan.version.desc())
        )
    ).scalars().first()


async def retire_superseded_plan(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    old: ActionPlan,
    replaced_by_label: str,
    decision_reason: str,
    notify_entity_id: str | None = None,
) -> bool:
    """Collapse one never-activated plan and *everything hanging off it*.

    F49: two code paths superseded a plan and only this one retired the approval
    that went with it. The inbound date-shift handler set `status = superseded`
    and stopped — which also blinded this sweep, because the sweep only selects
    plans still in DRAFT/PENDING_REVIEW. The orphan it left could therefore never
    be cleaned up by any later sweep, and approving it rolled the project
    backwards over a merge (device-proven 2026-08-05).

    So the retirement lives here, once, and both paths call it. Returns False if
    the plan was left alone.

    Conflict-held drafts are exempt and that guard is *inside* this function
    deliberately: it used to sit in the caller, which is exactly how the two
    paths came to disagree.
    """
    held = (
        await db.execute(
            select(Conflict).where(
                Conflict.held_plan_id == old.id,
                Conflict.status == ConflictStatus.OPEN.value,
            )
        )
    ).scalars().first()
    if held is not None:
        # Frozen for a named human; released only by resolving the conflict.
        return False

    old.status = PlanStatus.SUPERSEDED.value

    # Tasks this version opened but that never went live die with it.
    stale_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.plan_version_added == old.version,
                ActionItem.status == ActionItemStatus.PENDING_REVIEW.value,
            )
        )
    ).scalars().all()
    for t in stale_tasks:
        t.status = ActionItemStatus.SUPERSEDED.value

    stale_approvals = (
        await db.execute(
            select(Approval).where(
                Approval.org_id == org_id,
                Approval.entity_type == ApprovalEntityType.PLAN_CHANGE.value,
                Approval.entity_id == old.id,
                Approval.status == "pending",
            )
        )
    ).scalars().all()
    for a in stale_approvals:
        a.status = "expired"
        a.decision_note = (
            f"Superseded by {replaced_by_label} before activation — "
            "the newer information replaced this re-plan"
        )
        a.decided_at = utcnow()
        # A message bundled on a collapsed approval must never be sent.
        from app.models.messaging import OutboundMessage

        for bundle in a.bundled_entities or []:
            if bundle.get("entity_type") == "outbound_message" and bundle.get("entity_id"):
                stale_msg = (
                    await db.execute(
                        select(OutboundMessage).where(
                            OutboundMessage.id == bundle["entity_id"],
                            OutboundMessage.org_id == org_id,
                        )
                    )
                ).scalar_one_or_none()
                if stale_msg is not None and stale_msg.status in ("draft", "pending_approval"):
                    stale_msg.status = "rejected"
                    stale_msg.last_error = (
                        f"Collapsed with plan v{old.version} — superseded before send"
                    )
        if a.requested_from_user_id:
            await notify(
                db, org_id=org_id, user_id=a.requested_from_user_id,
                title=f"Plan v{old.version} collapsed before activation",
                body=f"Newer information arrived — {replaced_by_label} replaces "
                     f"the v{old.version} you were reviewing. Nothing was applied.",
                kind="plan_updated", entity_type="action_plan",
                entity_id=notify_entity_id or old.id,
            )

    # A recorded meeting's plan still waiting for "Approve plan" goes too, or
    # its card would offer a plan that can no longer be activated.
    if old.trigger_ref and old.trigger in (
        PlanTrigger.FIRST_MEETING.value, PlanTrigger.NEW_MEETING.value
    ):
        holds = (
            await db.execute(
                select(Approval).where(
                    Approval.org_id == org_id,
                    Approval.entity_type == ApprovalEntityType.MEETING_PLAN.value,
                    Approval.entity_id == old.trigger_ref,
                    Approval.status == "pending",
                )
            )
        ).scalars().all()
        for h in holds:
            h.status = "expired"
            h.decision_note = (
                f"Superseded by {replaced_by_label} before it was approved"
            )
            h.decided_at = utcnow()
            if h.requested_from_user_id:
                await notify(
                    db, org_id=org_id, user_id=h.requested_from_user_id,
                    title=f"Plan for {project.name} replaced",
                    body=f"Newer information arrived and {replaced_by_label} replaces "
                         "the plan you had not approved yet. Nothing was applied.",
                    kind="plan_updated", entity_type="meeting",
                    entity_id=old.trigger_ref,
                )
        if holds:
            held_meeting = (
                await db.execute(select(Meeting).where(Meeting.id == old.trigger_ref))
            ).scalar_one_or_none()
            if held_meeting is not None:
                held_meeting.plan_state = MeetingPlanState.SUPERSEDED.value
                held_meeting.plan_note = (
                    "A newer plan for this project replaced this one before it "
                    "was approved. Nothing from it was applied."
                )

    await record_decision(
        db, org_id=org_id, project_id=project.id,
        decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
        decision=f"Plan v{old.version} superseded before activation",
        reason=decision_reason,
        entity_type="action_plan", entity_id=old.id,
    )
    return True


_FINISHED = (
    ActionItemStatus.DONE.value,
    ActionItemStatus.CANCELLED.value,
    ActionItemStatus.SUPERSEDED.value,
)


def _norm_title(text: str) -> str:
    return " ".join((text or "").split()).casefold()


async def _live_task_id(
    db: AsyncSession, *, org_id: str, lead_id: str | None, ref: str
) -> str | None:
    """The live (not finished) task a dependency reference means, or None.

    A reference is a task id or, as the Planner writes them, a title. A title
    is matched exactly (ignoring case and spacing) against this client's live
    tasks only. A finished task is nothing to wait for, so it is not
    returned either."""
    by_id = (
        await db.execute(
            select(ActionItem.id).where(
                ActionItem.org_id == org_id, ActionItem.id == ref,
                ActionItem.status.notin_(_FINISHED),
            )
        )
    ).scalar_one_or_none()
    if by_id is not None or not lead_id:
        return by_id
    wanted = _norm_title(ref)
    for task_id, title in (
        await db.execute(
            select(ActionItem.id, ActionItem.title)
            .where(
                ActionItem.org_id == org_id, ActionItem.lead_id == lead_id,
                ActionItem.status.notin_(_FINISHED),
            )
            .order_by(ActionItem.created_at.desc())
        )
    ).all():
        if _norm_title(title) == wanted:
            return task_id
    return None


async def _resolve_dependency_refs(
    db: AsyncSession, *, org_id: str, lead_id: str | None, refs: list[Any],
    batch: dict[str, str], self_id: str,
) -> list[str]:
    """Dependency references (titles or ids) → task ids a task can wait on.

    Found at Ollama School of Commerce (1 Oct 2026): a title the plan's own
    batch no longer held (the recording's meeting, dropped by a fence after
    the model wrote the plan) used to be stored as the title itself. A title
    is never marked done, so the task waiting on it never got an owner. Now
    it is linked to the client's live task with that title; a reference that
    matches nothing live is left out rather than waited on forever."""
    batch_norm = {_norm_title(t): i for t, i in batch.items()}
    out: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        found = batch.get(ref) or batch_norm.get(_norm_title(ref))
        if found is None:
            found = await _live_task_id(db, org_id=org_id, lead_id=lead_id, ref=ref)
        if found is None:
            logger.info("Plan dependency %r matches no live task; not waited on", ref)
        elif found != self_id and found not in out:
            out.append(found)
    return out


async def repair_title_dependencies(
    db: AsyncSession, *, org_id: str | None = None
) -> list[dict[str, Any]]:
    """Re-link dependencies stored as titles, by the same rule as new plans
    (one-off repair for rows written before 1 Oct 2026). Links that are real
    task ids are left exactly as they are. A task left with nothing live to
    wait for, and no owner yet, is staffed now. Returns what changed."""
    from app.engines import assignment_engine

    stmt = select(ActionItem).where(ActionItem.status.notin_(_FINISHED))
    if org_id:
        stmt = stmt.where(ActionItem.org_id == org_id)
    changed: list[dict[str, Any]] = []
    for task in (await db.execute(stmt)).scalars().all():
        deps = list(task.depends_on_ids or [])
        if not deps:
            continue
        existing = set(
            (
                await db.execute(
                    select(ActionItem.id).where(ActionItem.id.in_(deps))
                )
            ).scalars().all()
        )
        if all(d in existing for d in deps):
            continue
        new: list[str] = []
        for d in deps:
            if d in existing:
                found = d
            else:
                found = await _live_task_id(
                    db, org_id=task.org_id, lead_id=task.lead_id, ref=d)
            if found and found != task.id and found not in new:
                new.append(found)
        task.depends_on_ids = new
        assigned = None
        still_waiting = (
            await db.execute(
                select(ActionItem.id).where(
                    ActionItem.id.in_(new or [""]),
                    ActionItem.status.notin_(_FINISHED),
                )
            )
        ).first()
        if still_waiting is None and not task.assignee_id:
            await assignment_engine.assign_task(db, org_id=task.org_id, task=task)
            assigned = task.assignee_id
        changed.append({"task_id": task.id, "title": task.title,
                        "before": deps, "after": new, "assigned_to": assigned})
    return changed


async def create_plan_version(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    trigger: str,
    trigger_ref: str | None,
    summary: str,
    changes: list[str],
    new_tasks: list[dict[str, Any]],
    pending_ops: list[dict[str, Any]] | None = None,
    held_by_conflict: Conflict | None = None,
    approval_facts: dict[str, Any] | None = None,
    hold_for_meeting: Meeting | None = None,
) -> tuple[ActionPlan, Approval | None]:
    """The one way a plan changes: a new version with a written diff.

    new_tasks items: {title, description, phase, required_skill, due_in_days |
    due_date, priority, visible_to_client, source, depends_on, assign_on,
    blocked_reason, external_wait, commitment: {text, due_in_days, direction,
    promised_to}}.
    Returns (plan, approval) — approval is None when the change was small
    enough to match no rule (auto-activated as "system").

    `hold_for_meeting` (a recorded meeting, 1 Oct 2026): instead of going to
    the approval rules now, the plan waits for the person who recorded the
    meeting to choose its tasks and tap "Approve plan"
    (`approve_meeting_plan`); the rules apply after that. The approval
    returned is then that hold.
    """
    version = await _next_version(db, project.id)
    plan = ActionPlan(
        org_id=org_id,
        project_id=project.id,
        version=version,
        summary=summary,
        trigger=trigger,
        trigger_ref=trigger_ref,
        changes_from_previous="\n".join(changes) if changes else "Initial plan",
        status=PlanStatus.DRAFT.value,
        pending_ops=pending_ops or [],
    )
    db.add(plan)
    await db.flush()

    # Nothing half-applies (Workflow 18): a newer version supersedes any older
    # version still waiting for activation — its never-activated tasks and its
    # pending approvals collapse with it. Conflict-held drafts are exempt:
    # they are frozen for a named human and released only by resolution.
    open_siblings = (
        await db.execute(
            select(ActionPlan).where(
                ActionPlan.project_id == project.id,
                ActionPlan.id != plan.id,
                ActionPlan.status.in_(
                    [PlanStatus.DRAFT.value, PlanStatus.PENDING_REVIEW.value]
                ),
            )
        )
    ).scalars().all()
    for old in open_siblings:
        await retire_superseded_plan(
            db, org_id=org_id, project=project, old=old,
            replaced_by_label=f"plan v{version}",
            decision_reason=(
                f"v{version} ({trigger}) arrived while v{old.version} was "
                "still under review — nothing half-applies"
            ),
            notify_entity_id=plan.id,
        )

    # Rows this meeting already opened that no plan owns yet: the to-dos a human
    # confirmed at the review gate, or — when the org has that gate switched off
    # — the items the pipeline opened directly. Both look identical here
    # (meeting_id set, plan_version_added NULL), so one lookup covers both
    # entry points. The Planner is asked to carry each of them into the plan;
    # writing that carry as a second row is finding F22.
    adoptable: list[ActionItem] = []
    if trigger_ref and trigger in ("first_meeting", "new_meeting"):
        adoptable = list(
            (
                await db.execute(
                    select(ActionItem).where(
                        ActionItem.org_id == org_id,
                        ActionItem.meeting_id == trigger_ref,
                        ActionItem.plan_version_added.is_(None),
                        ActionItem.status.notin_(
                            [
                                ActionItemStatus.CANCELLED.value,
                                ActionItemStatus.SUPERSEDED.value,
                            ]
                        ),
                    )
                )
            ).scalars().all()
        )
    adopted_ids: set[str] = set()

    # Create the version's new tasks (kept pending_review until activation).
    created: list[ActionItem] = []
    title_to_id: dict[str, str] = {}
    for spec in new_tasks:
        due = spec.get("due_date")
        if due is None and spec.get("due_in_days") is not None:
            due = utcnow() + timedelta(days=spec["due_in_days"])
        existing = _adoption_match(spec["title"], adoptable, adopted_ids)
        if existing is not None:
            # Adopt. The row keeps its id, the human's wording (they may have
            # edited it at the gate) and the date the client actually heard;
            # the plan contributes only what a plan knows — phase, skill,
            # priority, dependencies. Status is deliberately untouched: work a
            # person already made live is never retracted into pending_review.
            adopted_ids.add(existing.id)
            task = existing
            task.project_id = project.id
            task.plan_version_added = version
            task.phase = spec.get("phase", Phase.PREPARATION.value)
            task.required_skill = spec.get("required_skill")
            task.priority = spec.get("priority", TaskPriority.P2.value)
            task.visible_to_client = bool(spec.get("visible_to_client", False))
            task.source = spec.get("source", TaskSource.MEETING.value)
            task.assign_on = spec.get("assign_on", "plan_activation")
            if spec.get("blocked_reason"):
                task.blocked = True
                task.blocked_reason = spec["blocked_reason"]
            if spec.get("external_wait"):
                task.external_wait = spec["external_wait"]
            # A date the human had beats one the model derived; a date only the
            # model has is better than none.
            if task.due_date is None and due is not None:
                task.due_date = due
        else:
            task = ActionItem(
                org_id=org_id,
                lead_id=project.lead_id,
                project_id=project.id,
                meeting_id=trigger_ref if trigger in ("first_meeting", "new_meeting") else None,
                plan_version_added=version,
                title=spec["title"],
                description=spec.get("description"),
                phase=spec.get("phase", Phase.PREPARATION.value),
                required_skill=spec.get("required_skill"),
                priority=spec.get("priority", TaskPriority.P2.value),
                due_date=due,
                visible_to_client=bool(spec.get("visible_to_client", False)),
                source=spec.get("source", TaskSource.MEETING.value),
                status=ActionItemStatus.PENDING_REVIEW.value,
                assign_on=spec.get("assign_on", "plan_activation"),
                blocked=bool(spec.get("blocked_reason")),
                blocked_reason=spec.get("blocked_reason"),
                external_wait=spec.get("external_wait"),
                created_by="ai",
            )
            db.add(task)
        await db.flush()
        # Dependencies are declared against the MODEL's title, which an adopted
        # row does not carry — register both so `depends_on` resolves either way.
        title_to_id[spec["title"]] = task.id
        title_to_id[task.title] = task.id
        created.append(task)
        # Commitment linked to the task.
        commitment_spec = spec.get("commitment")
        if commitment_spec:
            commitment = ClientCommitment(
                org_id=org_id,
                project_id=project.id,
                text=commitment_spec["text"],
                direction=commitment_spec.get("direction", "ours"),
                promised_to=commitment_spec.get("promised_to"),
                promised_by=commitment_spec.get("promised_by"),
                due_date=utcnow() + timedelta(days=commitment_spec.get("due_in_days", 7)),
                linked_action_item_id=task.id,
                status=CommitmentStatus.OPEN.value,
                source_type=trigger,
                source=trigger_ref,
            )
            db.add(commitment)
            await db.flush()
            task.client_commitment_id = commitment.id

    # Wire dependencies by title reference: a title in this batch, else the
    # client's live task with that title (`_resolve_dependency_refs`).
    for spec, task in zip(new_tasks, created):
        deps = spec.get("depends_on") or []
        if not deps:
            continue
        dep_ids = await _resolve_dependency_refs(
            db, org_id=org_id, lead_id=project.lead_id, refs=deps,
            batch=title_to_id, self_id=task.id,
        )
        if dep_ids:
            task.depends_on_ids = dep_ids

    # Validation: refuse cycles.
    all_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.status.notin_(
                    [ActionItemStatus.CANCELLED.value, ActionItemStatus.SUPERSEDED.value]
                ),
            )
        )
    ).scalars().all()
    if _has_cycle(all_tasks):
        plan.status = PlanStatus.DRAFT.value
        await record_decision(
            db, org_id=org_id, project_id=project.id,
            decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
            decision=f"Plan v{version} refused activation",
            reason="Circular dependency detected — a human must untangle it",
            needs_human=True, entity_type="action_plan", entity_id=plan.id,
        )
        return plan, None

    # A conflict holds the plan as draft — dates are NOT changed yet.
    if held_by_conflict is not None:
        held_by_conflict.held_plan_id = plan.id
        await events.emit(
            db, org_id=org_id, event_type=EventType.PLAN_HELD.value,
            project_id=project.id, entity_type="action_plan", entity_id=plan.id,
            details={"conflict_id": held_by_conflict.id},
        )
        return plan, None

    if hold_for_meeting is not None:
        plan.status = PlanStatus.PENDING_REVIEW.value
        hold = await _hold_for_recorder(
            db, org_id=org_id, plan=plan, project=project, meeting=hold_for_meeting
        )
        return plan, hold

    # Route through the Approval Engine; below-every-rule changes activate as
    # "system" (Data Model §8.5 boundary 1).
    from app.engines import approval_engine

    plan.status = PlanStatus.PENDING_REVIEW.value
    facts = {
        "tasks_added": len(created),
        "new_project": version == 1,
        **(approval_facts or {}),
    }
    approval = await approval_engine.request_approval(
        db, org_id=org_id,
        entity_type=ApprovalEntityType.PLAN_CHANGE.value,
        entity_id=plan.id,
        project_id=project.id,
        facts=facts,
        reason=f"Plan v{version}: {summary} — "
        + (changes[0] if changes else f"{len(created)} task(s)"),
        bundled_entities=approval_facts.get("bundled_entities") if approval_facts else None,
        default_approver_role=None,  # no rule match → auto-activate
    )
    if approval is None:
        await activate_plan(db, org_id=org_id, plan_id=plan.id, approved_by="system")
    return plan, approval


async def activate_plan(
    db: AsyncSession, *, org_id: str, plan_id: str, approved_by: str
) -> ActionPlan:
    """Activation is one transaction: supersede the old version, apply held
    ops, open the new tasks, staff them as one batch, notify each affected
    person with only their own changes (Workflow 6.4)."""
    plan = (
        await db.execute(
            select(ActionPlan).where(ActionPlan.org_id == org_id, ActionPlan.id == plan_id)
        )
    ).scalar_one()
    if plan.status == PlanStatus.ACTIVE.value:
        return plan
    project = (
        await db.execute(select(Project).where(Project.id == plan.project_id))
    ).scalar_one()

    # F49 — the safety net. Activation used to check only "am I already active?",
    # so approving a stale card walked the project BACKWARDS: v2 went active over
    # v4, `current_plan_version` fell 4 → 2, and the meeting-2 merge left the live
    # plan. That is not hypothetical — it happened on the real project on
    # 2026-08-05, and it did not self-heal (five tasks the rollback released
    # stayed open after the pointer was repaired).
    #
    # This guard is deliberately independent of the retirement helper above: the
    # helper stops orphans being *created*, this stops any that already exist —
    # or that some future path invents — from doing damage.
    newer = await newer_active_plan(
        db, project_id=project.id, version=plan.version
    )
    if newer is not None:
        raise ConflictError(
            f"Plan v{plan.version} cannot be activated: v{newer.version} is "
            f"already the live plan for {project.name}. Activating an older "
            f"version would discard everything v{newer.version} added. Re-plan "
            f"from the current version instead."
        )
    # Second shape the check above cannot see: the pointer is ahead while nothing
    # is currently ACTIVE (a newer version was retired without a replacement
    # activating). `current_plan_version` is the Data Model's own answer to
    # "which version is live right now", so it gets a vote of its own.
    if project.current_plan_version > plan.version:
        raise ConflictError(
            f"Plan v{plan.version} cannot be activated: {project.name} is already "
            f"on version {project.current_plan_version}. Activating an older "
            f"version would move the project backwards."
        )

    # Supersede the previous active version (never deleted).
    previous = (
        await db.execute(
            select(ActionPlan).where(
                ActionPlan.project_id == project.id,
                ActionPlan.status == PlanStatus.ACTIVE.value,
            )
        )
    ).scalars().all()
    for p in previous:
        p.status = PlanStatus.SUPERSEDED.value

    plan.status = PlanStatus.ACTIVE.value
    plan.approved_by = approved_by
    plan.approved_at = utcnow()
    project.current_plan_version = plan.version

    changed_by_user: dict[str, list[str]] = {}

    # Apply held operations (re-dates, cancellations, reopenings, unblocks,
    # window moves, commitment renegotiations). Project-level ops carry no
    # task_id and are handled before the task lookup.
    for op in plan.pending_ops or []:
        kind = op.get("op")
        if kind == "set_window":
            # Apply only the sides the op carries — a missing side means
            # "unchanged", never "erase".
            if op.get("start"):
                project.start_date = datetime.fromisoformat(op["start"])
            if op.get("end"):
                project.target_end_date = datetime.fromisoformat(op["end"])
            continue
        if kind == "reschedule_demo":
            # The client asked to move the demo. Until now the merge had no op
            # for this, so the model re-dated whatever TASK mentioned the demo
            # and the demo itself kept its original date — the client was left
            # holding a calendar invite for a day nobody was coming.
            #
            # Applied at ACTIVATION like every other op: a demo move is a plan
            # change, so it waits behind the same approval.
            from app.core.context import OrgContext
            from app.models.demo import Demo
            from app.services import demo_invite_service

            demo = (
                await db.execute(
                    select(Demo).where(
                        Demo.org_id == org_id, Demo.id == op.get("demo_id")
                    )
                )
            ).scalar_one_or_none()
            if demo is None:
                continue
            moved = False
            # `demos.scheduled_date` is a DATE, not a datetime — comparing a
            # datetime against it would always look "changed" and re-invite the
            # client on every activation.
            try:
                new_date = datetime.fromisoformat(str(op.get("new_date"))).date()
            except (TypeError, ValueError):
                new_date = None
            if new_date is not None and new_date != demo.scheduled_date:
                demo.scheduled_date = new_date
                moved = True
            if op.get("new_time") and op["new_time"] != demo.scheduled_time:
                demo.scheduled_time = op["new_time"]
                moved = True
            await db.flush()
            if moved:
                # Same follow-through the Reschedule button gives: an "event
                # updated" invite, drafted and held for a human tap. Moving the
                # date and NOT telling the client would be the worse bug.
                lead_row = (
                    await db.execute(select(Lead).where(Lead.id == demo.lead_id))
                ).scalar_one_or_none()
                approver = await get_user(db, org_id, approved_by)
                if lead_row is not None and approver is not None:
                    await demo_invite_service.compose_demo_invite(
                        db,
                        OrgContext(
                            org_id=org_id, user_id=approver.id,
                            role=approver.role, email=approver.email,
                        ),
                        demo=demo, lead=lead_row, change="rescheduled",
                    )
                await record_decision(
                    db, org_id=org_id, project_id=project.id,
                    decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
                    decision=f"Demo moved to {demo.scheduled_date}",
                    reason="The client asked for a different date in the meeting.",
                    entity_type="demo", entity_id=demo.id,
                )
            continue
        if kind == "renegotiate_commitment":
            commitment = (
                await db.execute(
                    select(ClientCommitment).where(
                        ClientCommitment.id == op.get("commitment_id")
                    )
                )
            ).scalar_one_or_none()
            if commitment is not None:
                commitment.due_date = datetime.fromisoformat(op["new_due"])
                commitment.status = CommitmentStatus.RENEGOTIATED.value
                await events.emit(
                    db, org_id=org_id,
                    event_type=EventType.COMMITMENT_RENEGOTIATED.value,
                    project_id=project.id, entity_type="client_commitment",
                    entity_id=commitment.id,
                    details={"new_due": op["new_due"]},
                    react=False,
                )
            continue
        task = (
            await db.execute(
                select(ActionItem).where(ActionItem.id == op.get("task_id"))
            )
        ).scalar_one_or_none()
        if task is None:
            continue
        if kind == "redate":
            old = task.due_date
            task.due_date = datetime.fromisoformat(op["new_due"])
            task.reminder_level = 0
            if task.assignee_id:
                changed_by_user.setdefault(task.assignee_id, []).append(
                    f"'{task.title}' moved "
                    + (f"{old:%d %b} → {task.due_date:%d %b}" if old else f"to {task.due_date:%d %b}")
                )
        elif kind == "cancel":
            task.status = ActionItemStatus.CANCELLED.value
            task.result_note = op.get("reason", "cancelled by re-plan")
            if task.assignee_id:
                changed_by_user.setdefault(task.assignee_id, []).append(
                    f"'{task.title}' cancelled: {op.get('reason', '')}"
                )
        elif kind == "reopen":
            task.status = ActionItemStatus.OPEN.value
            task.result_note = None
            task.completed_at = None
            if op.get("new_due"):
                task.due_date = datetime.fromisoformat(op["new_due"])
            if task.assignee_id:
                changed_by_user.setdefault(task.assignee_id, []).append(
                    f"'{task.title}' reopened: {op.get('reason', '')}"
                )
        elif kind == "unblock":
            task.blocked = False
            task.blocked_reason = None

    # Open this version's new tasks and staff them as ONE batch.
    # Tasks ADOPTED from the meeting review gate (finding F22) belong to this
    # version too, but are already `open` — a person made them live when they
    # confirmed the meeting. The query spans both statuses so they are staffed
    # with the rest of the plan; only the pending ones are flipped open.
    new_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.plan_version_added == plan.version,
                ActionItem.status.in_(
                    [
                        ActionItemStatus.PENDING_REVIEW.value,
                        ActionItemStatus.OPEN.value,
                    ]
                ),
            )
        )
    ).scalars().all()
    assignees_before = {t.id: t.assignee_id for t in new_tasks}
    for t in new_tasks:
        if t.status == ActionItemStatus.PENDING_REVIEW.value:
            t.status = ActionItemStatus.OPEN.value

    from app.engines import assignment_engine

    await assignment_engine.assign_batch(db, org_id=org_id, tasks=new_tasks)

    # An adopted task can move off the person who recorded the meeting once the
    # plan staffs it by skill. Nothing leaves someone's list silently.
    for t in new_tasks:
        was = assignees_before.get(t.id)
        if was and t.assignee_id and t.assignee_id != was:
            changed_by_user.setdefault(was, []).append(
                f"'{t.title}' is now with the person the plan staffed for it"
                + (f" — {t.assignment_reason}" if t.assignment_reason else "")
            )

    # Everyone affected joins the team and hears only their own changes.
    for t in new_tasks:
        if not t.assignee_id:
            continue
        member = (
            await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == t.assignee_id,
                    ProjectMember.left_at.is_(None),
                )
            )
        ).scalars().first()
        if member is None:
            db.add(
                ProjectMember(
                    org_id=org_id, project_id=project.id, user_id=t.assignee_id,
                    role_in_project=None, added_by="ai", joined_at=utcnow(),
                )
            )
            await events.emit(
                db, org_id=org_id, event_type=EventType.MEMBER_JOINED.value,
                project_id=project.id, entity_type="user", entity_id=t.assignee_id,
            )
        changed_by_user.setdefault(t.assignee_id, []).append(
            f"New task: '{t.title}'"
            + (f" (due {t.due_date:%d %b})" if t.due_date else "")
            + (f" — {t.assignment_reason}" if t.assignment_reason else "")
        )

    for user_id, items in changed_by_user.items():
        await notify(
            db, org_id=org_id, user_id=user_id,
            title=f"Plan v{plan.version} active — your changes",
            body="\n".join(items), kind="plan_updated",
            entity_type="action_plan", entity_id=plan.id,
        )

    await events.emit(
        db, org_id=org_id, event_type=EventType.PLAN_ACTIVATED.value,
        project_id=project.id, entity_type="action_plan", entity_id=plan.id,
        actor=approved_by,
        details={"version": plan.version, "summary": plan.summary or ""},
    )
    return plan


async def plan_rejected(db: AsyncSession, *, org_id: str, plan_id: str, note: str) -> None:
    """A rejection with a note loops the plan back — the note is the
    instruction (e.g. 'give syllabus to Sourav' → reassignment override)."""
    plan = (
        await db.execute(
            select(ActionPlan).where(ActionPlan.org_id == org_id, ActionPlan.id == plan_id)
        )
    ).scalar_one_or_none()
    if plan is None:
        return
    plan.status = PlanStatus.DRAFT.value
    await record_decision(
        db, org_id=org_id, project_id=plan.project_id,
        decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
        decision=f"Plan v{plan.version} rejected", reason=note or "rejected",
        needs_human=True, entity_type="action_plan", entity_id=plan.id,
    )
    # Reassignment instructions in the note, in any phrasing ("give X to
    # Sourav", "let Priya handle the schedule", ...).
    tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == plan.project_id,
                ActionItem.plan_version_added == plan.version,
            )
        )
    ).scalars().all()
    reassignments: list[dict[str, str]] = []
    if nlu.llm_available():
        from app.ai import planning

        users = (
            await db.execute(
                select(User).where(User.org_id == org_id, User.is_active.is_(True))
            )
        ).scalars().all()
        try:
            reassignments = await planning.parse_rejection_note(
                org_id=org_id, note=note or "", tasks=tasks, users=users
            )
        except planning.PlanningUnavailable:
            reassignments = []  # the note still reaches a human via the redo loop
    else:
        # Stub-provider path: the simple "give X to <Name>" grammar.
        import re

        m = re.search(r"give\s+(?:the\s+)?([\w \-]+?)\s+to\s+([A-Z][a-z]+)", note or "")
        if m:
            keyword, person = m.group(1).strip().lower(), m.group(2)
            target = (
                await db.execute(
                    select(User).where(User.org_id == org_id, User.name.like(f"{person}%"))
                )
            ).scalars().first()
            if target is not None:
                for t in tasks:
                    if keyword.split()[0] in t.title.lower():
                        reassignments.append({"task_id": t.id, "user_id": target.id})
    if reassignments:
        from app.core.constants import AssignmentStatus
        from app.models.work import Assignment

        tasks_by_id = {t.id: t for t in tasks}
        for r in reassignments:
            t = tasks_by_id.get(r["task_id"])
            if t is None:
                continue
            previous = t.assignee_id
            t.assignee_id = r["user_id"]
            t.assigned_by = "human_override"
            t.assignment_reason = f"Lead override: {note}"
            db.add(
                Assignment(
                    org_id=org_id, action_item_id=t.id,
                    from_user_id=previous, to_user_id=r["user_id"],
                    assigned_by="human_override", reason=note,
                    status=AssignmentStatus.OVERRIDDEN.value,
                    decided_at=utcnow(),
                )
            )
    # The plan then goes back through review.
    from app.engines import approval_engine

    plan.status = PlanStatus.PENDING_REVIEW.value
    await approval_engine.request_approval(
        db, org_id=org_id, entity_type=ApprovalEntityType.PLAN_CHANGE.value,
        entity_id=plan.id, project_id=plan.project_id,
        facts={"new_project": plan.version == 1, "tasks_added": 0, "resubmission": True},
        reason=f"Plan v{plan.version} resubmitted after rejection — note applied: {note}",
        default_approver_role=Role.SALES_LEAD.value,
    )


# ─────────────────────────────────────────────────────────────────────────────
# "Approve plan": a recorded meeting's plan waits for the person who recorded
# it (design agreed 1 Oct 2026, after BS Carmel School)
# ─────────────────────────────────────────────────────────────────────────────

LEFT_OUT_NOTE = "Left out when the plan was approved"


async def _hold_for_recorder(
    db: AsyncSession, *, org_id: str, plan: ActionPlan, project: Project,
    meeting: Meeting,
) -> Approval:
    """File the plan for the person who recorded the meeting: one card in their
    Approvals (and so on Home), one notification that opens the meeting. No
    expiry: it is their own meeting's plan, not someone else's queue to chase."""
    hold = Approval(
        org_id=org_id, project_id=project.id,
        entity_type=ApprovalEntityType.MEETING_PLAN.value,
        entity_id=meeting.id,
        requested_from_user_id=meeting.agent_id,
        requested_from_role=None,
        stage="decide",
        bundled_entities=[],
        reason=f"Plan for {project.name} is ready: choose which tasks to add, "
               "then approve it",
        status="pending",
        requested_at=utcnow(), expires_at=None,
    )
    db.add(hold)
    await db.flush()
    meeting.plan_state = MeetingPlanState.READY.value
    meeting.plan_note = None
    await notify(
        db, org_id=org_id, user_id=meeting.agent_id,
        title=f"Plan ready for {project.name}",
        body="Choose which tasks to add and approve the plan.",
        kind="plan_ready", entity_type="meeting", entity_id=meeting.id,
    )
    return hold


async def held_meeting_plan(
    db: AsyncSession, *, org_id: str, meeting_id: str
) -> tuple[Approval | None, ActionPlan | None]:
    """The latest hold for this meeting and the plan this meeting produced
    (the newest version that came from it and was not retired)."""
    hold = (
        await db.execute(
            select(Approval)
            .where(
                Approval.org_id == org_id,
                Approval.entity_type == ApprovalEntityType.MEETING_PLAN.value,
                Approval.entity_id == meeting_id,
            )
            .order_by(Approval.requested_at.desc())
        )
    ).scalars().first()
    plan = (
        await db.execute(
            select(ActionPlan)
            .where(
                ActionPlan.org_id == org_id,
                ActionPlan.trigger_ref == meeting_id,
                ActionPlan.trigger.in_(
                    [PlanTrigger.FIRST_MEETING.value, PlanTrigger.NEW_MEETING.value]
                ),
            )
            .order_by(ActionPlan.version.desc())
        )
    ).scalars().first()
    return hold, plan


async def plan_tasks(db: AsyncSession, plan: ActionPlan) -> list[ActionItem]:
    """Every task this plan version carries that is still alive: the Planner's
    own (pending until approval) and the confirmed to-dos it adopted."""
    return list(
        (
            await db.execute(
                select(ActionItem)
                .where(
                    ActionItem.project_id == plan.project_id,
                    ActionItem.plan_version_added == plan.version,
                    ActionItem.status.notin_(
                        [ActionItemStatus.CANCELLED.value,
                         ActionItemStatus.SUPERSEDED.value]
                    ),
                )
                .order_by(ActionItem.due_date, ActionItem.created_at)
            )
        ).scalars().all()
    )


def is_confirmed_task(task: ActionItem) -> bool:
    """A to-do a person already accepted at the review gate (adopted by the
    plan), as opposed to one the Planner added. The Planner writes "ai"."""
    return task.created_by != "ai"


def refuse_skip_reason(task: ActionItem) -> str | None:
    """Why this task cannot be left out, or None when it can."""
    if is_confirmed_task(task) or task.status != ActionItemStatus.PENDING_REVIEW.value:
        return f"'{task.title}' was already accepted and stays in the plan."
    if task.client_commitment_id:
        return (f"'{task.title}' was promised to the client in the meeting, "
                "so it stays in the plan.")
    return None


def _date_shift_days(ops: list[dict[str, Any]] | None) -> int:
    shift = 0
    for op in ops or []:
        if op.get("op") == "redate" and op.get("old_due") and op.get("new_due"):
            try:
                old = datetime.fromisoformat(op["old_due"])
                new = datetime.fromisoformat(op["new_due"])
            except ValueError:
                continue
            shift = max(shift, abs((new - old).days))
    return shift


async def approve_meeting_plan(
    db: AsyncSession, *, org_id: str, meeting_id: str, skip_ids: list[str],
    by_user_id: str,
) -> dict[str, Any]:
    """The person who recorded the meeting approved its plan with the tasks
    they left on. The caller has already claimed the hold (it is no longer
    pending) and checked `skip_ids` with `refuse_skip_reason`.

    Skipped tasks are cancelled and nothing waits on them any more. Then the
    plan goes through the plan_change rules with the same facts it would have
    had without the hold: no rule, or the rule names this same person → live
    now; otherwise it waits for the rule's approver ("Sent to X")."""
    from app.engines import approval_engine

    meeting = (
        await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    ).scalar_one()
    _hold, plan = await held_meeting_plan(db, org_id=org_id, meeting_id=meeting_id)
    if plan is None or plan.status != PlanStatus.PENDING_REVIEW.value:
        raise ConflictError("This plan was replaced or decided before it was approved.")
    project = (
        await db.execute(select(Project).where(Project.id == plan.project_id))
    ).scalar_one()
    skip = set(skip_ids or [])
    tasks = await plan_tasks(db, plan)
    skipped = [t for t in tasks if t.id in skip]
    kept = [t for t in tasks if t.id not in skip]
    for t in skipped:
        t.status = ActionItemStatus.CANCELLED.value
        t.result_note = LEFT_OUT_NOTE
    if skip:
        # Anything that waited on a task now left out no longer waits on it.
        waiting = (
            await db.execute(
                select(ActionItem).where(
                    ActionItem.project_id == plan.project_id,
                    ActionItem.status.notin_(
                        [ActionItemStatus.CANCELLED.value,
                         ActionItemStatus.SUPERSEDED.value]
                    ),
                )
            )
        ).scalars().all()
        for t in waiting:
            deps = list(t.depends_on_ids or [])
            if any(d in skip for d in deps):
                t.depends_on_ids = [d for d in deps if d not in skip]
    await db.flush()

    approver = await get_user(db, org_id, by_user_id)
    who = approver.name if approver else "the recorder"
    facts = {
        "tasks_added": len(kept),
        "new_project": plan.version == 1,
        "date_shift_days": _date_shift_days(plan.pending_ops),
    }
    rule = await approval_engine.find_rule(
        db, org_id=org_id, entity_type=ApprovalEntityType.PLAN_CHANGE.value, facts=facts
    )
    outcome: dict[str, Any] = {"skipped": len(skipped), "kept": len(kept),
                               "approver_name": None}
    same_person = False
    if rule is not None and not rule.auto_approve and not rule.recommender_role:
        rule_user = await approval_engine._resolve_role_user(
            db, org_id, rule.approver_role, facts)
        if rule_user is None:
            rule_user = await approval_engine._resolve_role_user(
                db, org_id, rule.fallback_role, facts)
        joint = bool(rule.joint_with_role) and approval_engine._condition_matches(
            rule.joint_condition, facts)
        same_person = rule_user is not None and rule_user.id == by_user_id and not joint

    if rule is None or same_person:
        await activate_plan(db, org_id=org_id, plan_id=plan.id, approved_by=by_user_id)
        meeting.plan_state = MeetingPlanState.APPROVED.value
        meeting.plan_note = None
        await record_decision(
            db, org_id=org_id, project_id=project.id,
            decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
            decision=f"Plan v{plan.version} approved by {who}",
            reason=(f"{len(kept)} task(s) kept, {len(skipped)} left out"
                    + ("; they are also the approver the rules name" if same_person
                       else "; no approval rule applies")),
            entity_type="action_plan", entity_id=plan.id,
        )
        outcome["state"] = MeetingPlanState.APPROVED.value
        return outcome

    approval = await approval_engine.request_approval(
        db, org_id=org_id, entity_type=ApprovalEntityType.PLAN_CHANGE.value,
        entity_id=plan.id, project_id=project.id, facts=facts,
        reason=(f"Plan v{plan.version} for {project.name}, approved by {who}: "
                f"{len(kept)} task(s)"
                + (f", {len(skipped)} left out" if skipped else "")),
        default_approver_role=None,
    )
    if approval is None or approval.status == "approved":
        # No rule after all, or one that approves by itself (it activated).
        if approval is None:
            await activate_plan(db, org_id=org_id, plan_id=plan.id,
                                approved_by=by_user_id)
        meeting.plan_state = MeetingPlanState.APPROVED.value
        meeting.plan_note = None
        outcome["state"] = MeetingPlanState.APPROVED.value
        return outcome
    lead = await get_user(db, org_id, approval.requested_from_user_id)
    name = lead.name if lead else "the approver"
    meeting.plan_state = MeetingPlanState.SENT_FOR_APPROVAL.value
    meeting.plan_note = f"Sent to {name} for approval."
    outcome["state"] = MeetingPlanState.SENT_FOR_APPROVAL.value
    outcome["approver_name"] = lead.name if lead else None
    return outcome


async def discard_meeting_plan(
    db: AsyncSession, *, org_id: str, meeting_id: str, note: str | None
) -> None:
    """The hold was rejected (from the Approvals inbox): the Planner's extra
    tasks and its other changes are dropped. What the person confirmed at the
    review gate stays exactly as it is. Nothing goes to anyone else."""
    meeting = (
        await db.execute(select(Meeting).where(Meeting.id == meeting_id))
    ).scalar_one_or_none()
    _hold, plan = await held_meeting_plan(db, org_id=org_id, meeting_id=meeting_id)
    if plan is not None and plan.status == PlanStatus.PENDING_REVIEW.value:
        plan.status = PlanStatus.SUPERSEDED.value
        for t in await plan_tasks(db, plan):
            if not is_confirmed_task(t) and t.status == ActionItemStatus.PENDING_REVIEW.value:
                t.status = ActionItemStatus.SUPERSEDED.value
                t.result_note = "Plan turned down before it was approved"
        await record_decision(
            db, org_id=org_id, project_id=plan.project_id,
            decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
            decision=f"Plan v{plan.version} turned down",
            reason=note or "Turned down from the Approvals inbox",
            entity_type="action_plan", entity_id=plan.id,
        )
    if meeting is not None:
        meeting.plan_state = MeetingPlanState.DISCARDED.value
        meeting.plan_note = ("The plan was turned down. The to-dos you confirmed "
                             "stay as they are.")


# ─────────────────────────────────────────────────────────────────────────────
# Meeting processing — birth and merge
# ─────────────────────────────────────────────────────────────────────────────


DEFAULT_FIRST_PLAN = [
    # (title suffix, phase, skill, due days, visible)
    ("Prepare day-wise syllabus", Phase.PREPARATION.value, "curriculum_design", 5, True),
    ("Build draft proposal with pricing", Phase.PROPOSAL.value, "proposals", 3, False),
    ("Schedule teacher demo session", Phase.SALES.value, "scheduling", 7, True),
    ("Check trainer availability", Phase.PREPARATION.value, "scheduling", 4, False),
    ("Send thank-you + summary email", Phase.SALES.value, "english_writing", 1, True),
]


def _agreed_task_specs(
    agreed_tasks: list[dict[str, Any]] | None,
    *,
    skip_titles: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Human-confirmed review-gate to-dos as plan task specs.

    Only the stub provider needs this: the model layer is handed the same list
    as prompt context (`planning.agreed_block`) and places them itself, which
    is why nothing here tries to guess a phase."""
    specs: list[dict[str, Any]] = []
    seen = {t.lower() for t in (skip_titles or set())}
    for t in agreed_tasks or []:
        title = (t.get("title") or "").strip()
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        spec: dict[str, Any] = {
            "title": title[:490],
            "description": t.get("description"),
            "phase": Phase.PREPARATION.value,
            "visible_to_client": False,
            "source": TaskSource.MEETING.value,
        }
        if t.get("due_date") is not None:
            spec["due_date"] = t["due_date"]
        else:
            spec["due_in_days"] = 7
        specs.append(spec)
    return specs


def _title_similarity(a: str, b: str) -> float:
    """Word-overlap ratio of two task titles, 0..1 (Jaccard-ish over
    significant tokens). Deliberately keeps the verb — "schedule the demo" and
    "confirm the demo" must NOT read as the same task."""
    aw = {w for w in re.findall(r"[a-z0-9]+", a.lower()) if len(w) > 2}
    bw = {w for w in re.findall(r"[a-z0-9]+", b.lower()) if len(w) > 2}
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / min(len(aw), len(bw))


def _adoption_match(
    title: str,
    candidates: list[ActionItem],
    taken: set[str],
    *,
    threshold: float = 0.7,
) -> ActionItem | None:
    """The already-open row a plan task IS, or None when it is genuinely new.

    Finding F22: a to-do the human confirmed at the review gate and the
    Planner's carry of that same to-do into the plan are ONE piece of work, but
    were written as two rows — inflating every per-lead count, My Tasks, the
    digest and the nudge ladder. `_drop_duplicates_of_confirmed` could not see
    this: it de-duplicates within the model's own output, and the review-gate
    rows are not in the list it is handed.

    Same similarity function and same threshold as that fence, so the two agree
    by construction — "schedule the demo" still does not adopt "confirm the
    demo" (0.67). Each candidate can be claimed only once, so two plan tasks can
    never collapse onto a single existing row.
    """
    best: ActionItem | None = None
    best_score = 0.0
    for row in candidates:
        if row.id in taken:
            continue
        score = _title_similarity(title, row.title or "")
        if score > best_score:
            best, best_score = row, score
    return best if best_score >= threshold else None


def _drop_duplicates_of_confirmed(
    task_specs: list[dict[str, Any]],
    agreed_tasks: list[dict[str, Any]] | None,
    *,
    threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """A deterministic fence on the ONE thing F9's design must not do: emit a
    second task for work a human already confirmed.

    The model is asked to carry each confirmed to-do into the plan verbatim and
    add only NEW work; a weaker model sometimes carries it AND invents a near
    twin ("Provide safety compliance documentation" + "Prepare safety
    compliance documentation"). This keeps, for each confirmed to-do, only the
    single closest model task and drops any OTHER task that is also a near
    duplicate of that same confirmed to-do. A task matching no confirmed to-do
    is always kept — genuine new work is never silently dropped."""
    titles = [(t.get("title") or "").strip() for t in (agreed_tasks or [])]
    titles = [t for t in titles if t]
    if not titles:
        return task_specs
    # For each confirmed to-do, the index of the model task that best represents
    # it (its verbatim carry) — that one is kept.
    winners: set[int] = set()
    for confirmed in titles:
        scored = [
            (_title_similarity(confirmed, s.get("title") or ""), i)
            for i, s in enumerate(task_specs)
        ]
        scored = [(sc, i) for sc, i in scored if sc >= threshold]
        if scored:
            winners.add(max(scored)[1])
    kept: list[dict[str, Any]] = []
    for i, s in enumerate(task_specs):
        title = s.get("title") or ""
        redundant = any(_title_similarity(c, title) >= threshold for c in titles)
        if redundant and i not in winners:
            continue  # a second task for an already-represented confirmed to-do
        kept.append(s)
    return kept


async def _drop_scheduled_meeting_tasks(
    db: AsyncSession, *, org_id: str, meeting: Meeting, task_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """When this recording already scheduled its agreed meeting, the meeting
    has its own task and its invite is drafted by the system — so a plan task
    that is only that meeting or its invite ("Prepare calendar invite for
    follow-up meeting") is dropped. Only for the meeting scheduled from THIS
    recording: a different meeting the plan wants is kept. Seen on the first
    real upload (Risabh Public School, 23 Sep 2026)."""
    from app.models.scheduled_meeting import ScheduledMeeting
    from app.services.meeting_invite_service import is_only_the_meeting

    scheduled = (
        await db.execute(
            select(ScheduledMeeting.id).where(
                ScheduledMeeting.org_id == org_id,
                ScheduledMeeting.recording_meeting_id == meeting.id,
                ScheduledMeeting.status == "scheduled",
            )
        )
    ).first()
    if scheduled is None:
        return task_specs
    return [s for s in task_specs if not is_only_the_meeting(s.get("title") or "")]


# A pricing line is either quantity-independent or it scales with the count the
# client actually mentioned — and telling those apart never requires knowing what
# the org sells. "flat" is tested FIRST because a real seeded unit reads
# "flat per bootcamp" and contains both cues (F31).
_FLAT_UNIT_CUES = ("flat", "fixed", "one-time", "one time", "lump")


def _is_flat_unit(unit: str) -> bool:
    return not unit or any(cue in unit for cue in _FLAT_UNIT_CUES)


async def _estimate_value(
    db: AsyncSession, org_id: str, program: Program | None, quantity: int | None
) -> float | None:
    """Value estimate strictly from the current pricing table — never invented.

    F31: the pricing vocabulary belongs to the ORG, not to us. "per student",
    "per seat", "per licence", "per rack", "per site" are all just scaling
    lines, so no domain word appears here. A flat-priced engagement is worth
    its flat lines even when the discussion mentioned no count at all, which is
    why the quantity gates only the scaling lines rather than the whole
    function.

    **Each line is scaled by its OWN count.** `quantity` is a single number —
    the one count the client happened to mention — and applying it to every
    line is only correct when a program prices in one unit. The datacentre
    catalogue is the first with three (per rack / per hall / per site), and it
    exposed the bug: 120 racks priced the hall line and the site line 120 times
    over, turning ₹11,50,000 into ₹5,15,40,000 — a 45x overstatement on the
    project card, while the proposal for the same project totalled correctly.

    `proposal_service._build` has always read `default_quantity` per line and
    its totals have always been right. This function now reads the same field,
    so the card and the proposal cannot disagree.

    ⚠ Known limit, deliberate: a count the CLIENT states does not override a
    table default. Meeting 1 saying "120 racks" against a default of 120 agrees
    by luck; meeting 2 saying "160 racks" will still price 120 until someone
    edits the line or a proposal is raised. Choosing which line a bare number
    refers to would mean guessing at units, and understating from the org's own
    table is safer than inventing. The quantity is still used for any line that
    declares no default of its own.
    """
    if program is None:
        return None
    pricing = (
        await db.execute(
            select(PricingTable).where(
                PricingTable.org_id == org_id,
                PricingTable.program_id == program.id,
                PricingTable.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if pricing is None:
        return None
    total = 0.0
    for item in pricing.items or []:
        unit = str(item.get("unit") or "").strip().lower()
        price = float(item.get("unit_price") or 0)
        if _is_flat_unit(unit):
            total += price
            continue
        # The line's own count wins. 0 is a real answer ("none of these"), so
        # only a missing/blank default falls back to the discussed quantity.
        own = item.get("default_quantity")
        line_quantity: float | None
        if own is None or own == "":
            line_quantity = float(quantity) if quantity else None
        else:
            try:
                line_quantity = float(own)
            except (TypeError, ValueError):
                line_quantity = float(quantity) if quantity else None
        # A per-unit line with no count anywhere is left out rather than
        # guessed at — a partial estimate stays honest, an invented one does not.
        if line_quantity:
            total += price * line_quantity
    return total or None


async def _match_program(db: AsyncSession, org_id: str, text: str) -> Program | None:
    programs = (
        await db.execute(
            select(Program).where(Program.org_id == org_id, Program.is_active.is_(True))
        )
    ).scalars().all()
    t = text.lower()
    best, best_score = None, 0
    for p in programs:
        words = {w for w in (p.name + " " + (p.description or "")).lower().split() if len(w) > 3}
        score = sum(1 for w in words if w in t)
        if score > best_score:
            best, best_score = p, score
    return best


async def _hold_for_ai_failure(
    db: AsyncSession,
    *,
    org_id: str,
    meeting: Meeting,
    project: Project | None,
    error: str,
) -> dict[str, Any]:
    """The model layer is unreachable/unusable — never guess with keyword
    templates; the meeting is held and a human is told (design rule 3)."""
    await record_decision(
        db, org_id=org_id, project_id=project.id if project else None,
        decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
        decision="Meeting held — AI planning unavailable",
        reason=f"The planning model could not produce a usable result: {error[:300]}",
        needs_human=True, confidence=0.0,
        entity_type="meeting", entity_id=meeting.id,
    )
    await notify(
        db, org_id=org_id, user_id=meeting.agent_id,
        title="Meeting saved — planning needs a retry",
        body="The AI planner could not process this meeting right now. "
        "Nothing was lost; retry from the meeting screen or plan it manually.",
        kind="general", entity_type="meeting", entity_id=meeting.id,
    )
    return {"action": "held_for_review", "reason": "ai_unavailable"}


async def _wrong_project_guard(
    db: AsyncSession,
    *,
    org_id: str,
    meeting: Meeting,
    lead: Lead,
    project: Project,
    text: str,
) -> dict[str, Any] | None:
    """Workflow 6 'wrong project': a transcript that clearly concerns another
    client is flagged, never merged. LLM judgement in production; the
    word-overlap check only serves the stub/test provider."""
    suspect: str | None = None
    reason = ""
    if nlu.llm_available():
        from app.ai import planning

        other = (
            await db.execute(
                select(Lead.name).where(Lead.org_id == org_id, Lead.id != lead.id)
            )
        ).scalars().all()
        try:
            verdict = await planning.verify_transcript_project(
                org_id=org_id, text=text, project_name=project.name,
                lead_name=lead.name, other_lead_names=list(other),
            )
        except planning.PlanningUnavailable:
            return None  # the merge itself will hold if the model stays down
        # Deterministic fence on the model's judgement: the merge halts ONLY
        # when the model names a specific OTHER known client as the real
        # counterparty. "Doesn't feel like this client" alone never blocks —
        # most notes barely name anyone.
        named = (verdict["likely_client"] or "").strip().lower()
        known_other = next(
            (o for o in other if o and o.lower() == named), None
        ) if named else None
        if not verdict["matches"] and known_other:
            suspect = known_other
            reason = verdict["reason"]
    else:
        lead_words = {w.lower() for w in lead.name.split() if len(w) > 3}
        if lead_words and text and not any(w in text.lower() for w in lead_words):
            others = (
                await db.execute(
                    select(Lead).where(Lead.org_id == org_id, Lead.id != lead.id)
                )
            ).scalars().all()
            for o in others:
                o_words = [w for w in o.name.split() if len(w) > 3]
                if o_words and all(w.lower() in text.lower() for w in o_words):
                    suspect = o.name
                    reason = f"Transcript mentions '{o.name}', not '{lead.name}'"
                    break
    if suspect is None:
        return None
    await record_decision(
        db, org_id=org_id, project_id=project.id,
        decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
        decision="Merge halted — transcript may belong to another client",
        reason=reason or f"Transcript appears to concern '{suspect}', not '{lead.name}'",
        needs_human=True, confidence=0.3,
        entity_type="meeting", entity_id=meeting.id,
    )
    await notify(
        db, org_id=org_id, user_id=meeting.agent_id,
        title="Is this meeting on the right project?",
        body=f"The transcript appears to concern {suspect}; the meeting is filed "
        f"under {lead.name}. Please confirm before it is merged.",
        kind="general", entity_type="meeting", entity_id=meeting.id,
    )
    return {"action": "held_for_review"}


async def _followups_only(
    db: AsyncSession,
    *,
    org_id: str,
    lead: Lead,
    meeting: Meeting,
    summary: str,
) -> dict[str, Any]:
    """No project is born — 1–2 follow-ups on the lead, and it stays open."""
    from app.models.followup import FollowUp

    db.add(
        FollowUp(
            org_id=org_id, lead_id=lead.id, owner_id=meeting.agent_id,
            due_date=(utcnow() + timedelta(days=7)).date(),
            channel="call",
            note=f"Follow up after meeting: {summary[:150]}",
            created_by="ai",
        )
    )
    await record_decision(
        db, org_id=org_id, decision_type=DecisionType.PLAN_UPDATE.value,
        engine=ENGINE, decision="No project created",
        reason="Discussion was vague (no concrete ask, dates or numbers) — "
        "created follow-ups instead; projects are only born from concrete work",
        entity_type="meeting", entity_id=meeting.id,
    )
    return {"action": "followups_only"}


async def _resolve_meeting_project(
    db: AsyncSession, *, org_id: str, lead_id: str, text: str
) -> Project | None:
    """Which live engagement is this meeting about — if any?

    A recording carries no project id (`POST /meetings/upload` has no such
    field), so without this every recording would look like a FIRST meeting
    and fork a second project for the same client.

    The judgement is the model's, always — including when there is only one
    live project, because "another meeting on the ongoing work" and "a new
    engagement with an old client" look identical from the row count alone.
    Anything it cannot place returns None and the caller proposes a project,
    which a human still approves. On the stub provider nothing is resolved:
    it cannot make this call, and guessing would file meetings under the
    wrong project."""
    if not nlu.llm_available():
        return None
    live = [
        p for p in (
            await db.execute(
                select(Project).where(
                    Project.org_id == org_id, Project.lead_id == lead_id
                )
            )
        ).scalars().all()
        if p.status not in (ProjectStatus.CLOSED.value, ProjectStatus.LOST.value)
    ]
    if not live:
        return None
    from app.ai import planning

    try:
        picked = await planning.match_message_project(
            org_id=org_id, text=text, projects=live, source_kind="meeting",
        )
    except planning.PlanningUnavailable:
        return None
    if len(picked) == 1:
        return next(p for p in live if p.id == picked[0])
    return None


async def process_meeting(
    db: AsyncSession,
    *,
    org_id: str,
    meeting: Meeting,
    text: str,
    agreed_tasks: list[dict[str, Any]] | None = None,
    hold_for_review: bool = False,
) -> dict[str, Any]:
    """The pipeline's planning step. First meeting with real discussion →
    a project is proposed; vague discussion → follow-ups only; a meeting on
    an existing project → merge into a new plan version.

    `agreed_tasks` are to-dos a human already confirmed at the meeting review
    gate: the plan is built around them instead of re-deriving them.

    `hold_for_review` (recorded meetings, 1 Oct 2026): the plan waits for the
    person who recorded the meeting to tap "Approve plan" before the
    approval rules see it (`create_plan_version(hold_for_meeting=...)`).

    Production runs entirely on the model layer (any topic, any workflow);
    the deterministic keyword path exists only for LLM_PROVIDER=stub, which
    keeps the dry-run suite reproducible."""
    lead = (
        await db.execute(select(Lead).where(Lead.id == meeting.lead_id))
    ).scalar_one()

    if not meeting.project_id:
        resolved = await _resolve_meeting_project(
            db, org_id=org_id, lead_id=meeting.lead_id, text=text
        )
        if resolved is not None:
            meeting.project_id = resolved.id

    if meeting.project_id:
        project = (
            await db.execute(select(Project).where(Project.id == meeting.project_id))
        ).scalar_one_or_none()
        if project is not None:
            held = await _wrong_project_guard(
                db, org_id=org_id, meeting=meeting, lead=lead, project=project, text=text
            )
            if held is not None:
                return held
            if nlu.llm_available():
                from app.ai import planning

                try:
                    return await merge_meeting_llm(
                        db, org_id=org_id, project=project, meeting=meeting, text=text,
                        agreed_tasks=agreed_tasks, hold_for_review=hold_for_review,
                    )
                except planning.PlanningUnavailable as exc:
                    return await _hold_for_ai_failure(
                        db, org_id=org_id, meeting=meeting, project=project,
                        error=str(exc),
                    )
            facts = nlu.extract_meeting_heuristic(text)
            return await merge_meeting(
                db, org_id=org_id, project=project, meeting=meeting, facts=facts,
                text=text, agreed_tasks=agreed_tasks, hold_for_review=hold_for_review,
            )

    if nlu.llm_available():
        from app.ai import planning

        try:
            spec = await planning.generate_initial_plan(
                db, org_id=org_id, lead_name=lead.name, text=text,
                agreed_tasks=agreed_tasks,
            )
        except planning.PlanningUnavailable as exc:
            return await _hold_for_ai_failure(
                db, org_id=org_id, meeting=meeting, project=None, error=str(exc)
            )
        if not spec["concrete"]:
            return await _followups_only(
                db, org_id=org_id, lead=lead, meeting=meeting, summary=spec["summary"]
            )
        return await propose_project_from_spec(
            db, org_id=org_id, lead=lead, meeting=meeting, spec=spec,
            agreed_tasks=agreed_tasks, hold_for_review=hold_for_review,
        )

    facts = nlu.extract_meeting_heuristic(text)
    if not facts.get("concrete") and not agreed_tasks:
        return await _followups_only(
            db, org_id=org_id, lead=lead, meeting=meeting,
            summary=facts.get("summary", ""),
        )
    return await propose_project(
        db, org_id=org_id, lead=lead, meeting=meeting, facts=facts, text=text,
        agreed_tasks=agreed_tasks, hold_for_review=hold_for_review,
    )


def _name_match(a: str, b: str) -> bool:
    """Cautious person-name match: containment either way, else
    significant-token subset. No match beats the wrong person's identity."""
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    at = {t for t in re.findall(r"[a-z0-9]+", a) if len(t) > 2}
    bt = {t for t in re.findall(r"[a-z0-9]+", b) if len(t) > 2}
    return bool(at and bt and (at <= bt or bt <= at))


def _match_stakeholder_spec(
    specs: list[dict[str, Any]], contact_name: str
) -> dict[str, Any] | None:
    """Match a model-identified person to a contact record by name."""
    for spec in specs:
        if _name_match(spec["name"], contact_name):
            return spec
    return None


def _find_contact_for_name(contacts: list[Contact], name: str) -> Contact | None:
    for c in contacts:
        if _name_match(name, c.name):
            return c
    return None


SAME_PERSON_THRESHOLD = 0.7

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "shri", "smt", "sir",
               "madam", "sri", "kumari"}


def _fuller_name(a: str, b: str) -> str:
    """Of two names for one person, the one that says more: more name words
    (honorifics not counted), then the longer."""
    def words(n: str) -> int:
        return len([w for w in re.findall(r"[a-z]+", n.lower()) if w not in _HONORIFICS])
    return max((a, b), key=lambda n: (words(n), len(n)))


async def _resolve_people(
    db: AsyncSession, *, org_id: str, contacts: list[Contact],
    specs: list[dict[str, Any]],
) -> list[str]:
    """Check the people a meeting named with the model before any of them
    becomes a contact (Ollama School of Commerce, 1 Oct 2026). `specs` is
    changed IN PLACE so every caller then reads the same people:

    - two names for one individual in this meeting ("Mr. Jain", "Rishabh
      Jain") become one entry, under the fuller name, keeping what each said;
    - a name that is a saved contact misspelt ("Rishabh" for "Risabh") is
      renamed to the saved contact, so no duplicate is created and the
      meeting's role lands on the real person;
    - a role with no name ("Accounts Head") that is no saved contact is not
      saved; a note asks for the person once their name is known.

    "The same" means a score of SAME_PERSON_THRESHOLD or more. When the model
    is not available or fails, nothing changes: losing a person is worse than
    a duplicate a human can merge. Returns notes for the plan's change list."""
    named = [s for s in specs if s.get("name")]
    if not named or not nlu.llm_available():
        return []
    from app.ai import planning

    try:
        review = await planning.review_meeting_people(
            org_id=org_id,
            people=[{"name": s["name"], **({"role": s["role"]} if s.get("role") else {})}
                    for s in named],
            contacts=[{"name": c.name, **({"title": c.title} if c.title else {})}
                      for c in contacts],
        )
    except planning.PlanningUnavailable as exc:
        logger.warning("People check unavailable; saving names as heard: %s", exc)
        return []
    except Exception:  # noqa: BLE001 — never cost a meeting its people
        logger.exception("People check failed; saving names as heard")
        return []

    notes: list[str] = []
    root: dict[int, int] = {}
    for i in range(len(named)):
        r = review[i]
        same = r["same_as"]
        root[i] = root[same] if (same is not None
                                 and r["same_as_score"] >= SAME_PERSON_THRESHOLD) else i
    merged: dict[int, dict[str, Any]] = {}
    for i, spec in enumerate(named):
        k = root[i]
        if k not in merged:
            merged[k] = dict(spec)
            continue
        into = merged[k]
        logger.info("People check: %r and %r are one person", into["name"], spec["name"])
        into["name"] = _fuller_name(into["name"], spec["name"])
        for key in ("role", "influence"):
            if not into.get(key) and spec.get(key):
                into[key] = spec[key]
        into["receives_updates"] = bool(into.get("receives_updates")
                                        or spec.get("receives_updates"))
    # A group's answers: any member that matched a saved contact names it;
    # the group is a person if any member was.
    result: list[dict[str, Any]] = []
    for k, spec in merged.items():
        members = [i for i in range(len(named)) if root[i] == k]
        best = max(members, key=lambda i: review[i]["contact_score"])
        is_person = any(review[i]["is_person"] for i in members)
        contact_i = review[best]["contact"]
        if contact_i is not None and review[best]["contact_score"] >= SAME_PERSON_THRESHOLD:
            saved = contacts[contact_i]
            if saved.name != spec["name"]:
                logger.info("People check: %r is the saved contact %r (%.2f)",
                            spec["name"], saved.name, review[best]["contact_score"])
                spec["heard_as"] = spec["name"]
                spec["name"] = saved.name
        elif not is_person:
            label = spec["name"]
            notes.append(
                f"The meeting mentioned the {label} without a name; add them as a "
                "contact once you know who they are"
            )
            continue
        # Two entries that now carry the same saved name are one person too.
        twin = next((s for s in result
                     if _norm_title(s["name"]) == _norm_title(spec["name"])), None)
        if twin is not None:
            for key in ("role", "influence"):
                if not twin.get(key) and spec.get(key):
                    twin[key] = spec[key]
            twin["receives_updates"] = bool(twin.get("receives_updates")
                                            or spec.get("receives_updates"))
            continue
        result.append(spec)
    specs[:] = result + [s for s in specs if not s.get("name")]
    return notes


async def ensure_contacts_for_specs(
    db: AsyncSession,
    *,
    org_id: str,
    lead_id: str,
    contacts: list[Contact],
    specs: list[dict[str, Any]],
) -> tuple[list[Contact], list[str]]:
    """Create a `Contact` for every person a meeting named who has none yet.

    F41: this block used to live inside `sync_stakeholder_specs`, which the
    **first-meeting** path does not call. So the one moment you actually learn
    who these people are was the one moment the system discarded them — 0
    contacts, 0 stakeholders and 11 ownerless commitments after a full cycle,
    while meeting *2* on the same lead created Mr. Rao automatically. Data Model
    §3.3 lists "from a meeting" as one of three documented routes into
    `contacts`, and §3.4 says stakeholders are "created by the Planner Engine
    when meetings reveal who is who" — neither is qualified by "from the second
    meeting onward".

    Deliberately creates the contact with **no email and no phone**: a transcript
    never contains one, and inventing an address is how a client gets mail meant
    for somebody else. Nothing can be sent to them until a human records one.

    Returns (contacts including the new rows, notes describing what was added).

    ⚠ This exists as a *shared* function rather than a second implementation on
    purpose. Calling `sync_stakeholder_specs` from the create path instead would
    create **two stakeholder rows per contact** — it makes stakeholders too, and
    the create path's own loop then runs over every contact with no existence
    check. The two also disagree about defaults, and the create path's version
    is the one that matters: it maps `is_primary → decision_maker`, which is what
    gives `primary_stakeholder` a value and therefore what gives commitments an
    owner. Losing that rule *is* F41's consequence #3.
    """
    # The model checks the names first and edits `specs` in place, so the
    # caller's later name matching sees the same people (1 Oct 2026).
    notes: list[str] = await _resolve_people(
        db, org_id=org_id, contacts=contacts, specs=specs) if specs else []
    for spec in specs or []:
        if not spec.get("name"):
            continue
        if _find_contact_for_name(contacts, spec["name"]) is not None:
            continue
        contact = Contact(
            org_id=org_id, lead_id=lead_id, name=spec["name"],
            title=(spec.get("role") or "").replace("_", " ").title() or None,
            source="meeting",
        )
        db.add(contact)
        await db.flush()
        contacts.append(contact)
        notes.append(
            f"New client-side person recorded: {contact.name}"
            + (f" ({spec['role']})" if spec.get("role") else "")
        )
    return contacts, notes


async def backfill_stakeholders_for_contact(
    db: AsyncSession, *, org_id: str, contact: Contact
) -> int:
    """Give a newly added contact a stakeholder row on the lead's live projects.

    F41's consequence #4, and the half that makes the difference between "new
    projects are correct" and "F41 is fixed". The create-path loop runs **once**,
    inside project creation. So adding a contact by hand afterwards created no
    stakeholder at all — device-proven during Round 7, contacts 0→3 with
    stakeholders 0→0, which is why hand-adding Mrs. Nair never repaired the
    project and why the only progress recipient left was an addressless person
    (the state [F50] then tripped over).

    Uses exactly the create path's defaults, including `is_primary →
    decision_maker`: a second set of defaults is how F41 happened.

    Closed and lost projects are left alone — backfilling finished work would
    rewrite history rather than repair the present.
    """
    projects = (
        await db.execute(
            select(Project).where(
                Project.org_id == org_id,
                Project.lead_id == contact.lead_id,
                Project.status.not_in(
                    [ProjectStatus.CLOSED.value, ProjectStatus.LOST.value]
                ),
            )
        )
    ).scalars().all()
    added = 0
    for project in projects:
        existing = (
            await db.execute(
                select(Stakeholder).where(
                    Stakeholder.project_id == project.id,
                    Stakeholder.contact_id == contact.id,
                )
            )
        ).scalars().first()
        if existing is not None:
            continue
        db.add(
            Stakeholder(
                org_id=org_id, project_id=project.id, contact_id=contact.id,
                role_at_client=norm_role(contact.title) or "other",
                influence="decision_maker" if contact.is_primary else "influencer",
                receives_progress_updates=bool(contact.is_primary),
            )
        )
        added += 1
    if added:
        await db.flush()
    return added


async def sync_stakeholder_specs(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    specs: list[dict[str, Any]],
) -> list[str]:
    """Apply model-discovered client-side people to a live project (Data
    Model §3.4: 'Created by the Planner Engine when meetings reveal who is
    who'). Additive only: creates missing contacts (source=meeting, no
    address — nothing can ever be sent to them until a human records one)
    and missing stakeholder rows, and fills EMPTY fields on existing rows.
    It never overwrites a value already set by a human or an earlier read —
    a differing reading is reported in the returned notes, not applied."""
    if not specs:
        return []
    notes: list[str] = []
    contacts = list((
        await db.execute(select(Contact).where(Contact.lead_id == project.lead_id))
    ).scalars().all())
    stakeholders = (
        await db.execute(
            select(Stakeholder).where(Stakeholder.project_id == project.id)
        )
    ).scalars().all()
    by_contact = {s.contact_id: s for s in stakeholders}

    # Shared with the first-meeting path since F41 — one implementation, so the
    # two cannot drift the way they had.
    contacts, created_notes = await ensure_contacts_for_specs(
        db, org_id=org_id, lead_id=project.lead_id, contacts=contacts, specs=specs,
    )
    notes += created_notes

    for spec in specs:
        contact = _find_contact_for_name(contacts, spec["name"])
        if contact is None:
            continue
        if spec.get("other_engagement"):
            # F55: a real person at this client, but their involvement belongs to
            # a DIFFERENT engagement — another campus, branch or future programme
            # named in passing. Round 7 ended with a second campus's head sitting
            # on the wrong project as a `decision_maker`. `stakeholders` is
            # per-project by design (Workflow 29: "Kavita is on the bootcamp
            # only"), so they get a contact and no stakeholder row here.
            notes.append(
                f"{contact.name} was noted as a contact, but their involvement "
                f"concerns a different engagement — not added as a stakeholder "
                f"on {project.name}"
            )
            continue
        stakeholder = by_contact.get(contact.id)
        if stakeholder is None:
            stakeholder = Stakeholder(
                org_id=org_id, project_id=project.id, contact_id=contact.id,
                role_at_client=spec.get("role") or norm_role(contact.title) or "other",
                influence=spec.get("influence") or "influencer",
                receives_progress_updates=bool(spec.get("receives_updates")),
            )
            db.add(stakeholder)
            await db.flush()
            by_contact[contact.id] = stakeholder
            notes.append(
                f"Stakeholder added: {contact.name} — "
                f"{stakeholder.role_at_client} ({stakeholder.influence})"
            )
        else:
            filled: list[str] = []
            if spec.get("role") and (
                not stakeholder.role_at_client
                or stakeholder.role_at_client == "other"
            ):
                stakeholder.role_at_client = spec["role"]
                filled.append(f"role={spec['role']}")
            if spec.get("influence") and not stakeholder.influence:
                stakeholder.influence = spec["influence"]
                filled.append(f"influence={spec['influence']}")
            if spec.get("receives_updates") and not stakeholder.receives_progress_updates:
                stakeholder.receives_progress_updates = True
                filled.append("now receives progress updates")
            if filled:
                notes.append(f"Stakeholder updated: {contact.name} — " + ", ".join(filled))
            elif (
                spec.get("influence")
                and stakeholder.influence
                and spec["influence"] != stakeholder.influence
            ):
                notes.append(
                    f"Noted: the new discussion reads {contact.name} as "
                    f"{spec['influence']} (kept {stakeholder.influence} — "
                    "edit the stakeholder if reality changed)"
                )
    return notes


async def raise_meeting_complaints(
    db: AsyncSession, *, org_id: str, project: Project, lead: Lead | None,
    meeting_id: str | None, complaints: list[dict[str, Any]] | None,
) -> int:
    """A complaint made in a MEETING gets the same machinery as one sent by email.

    F54: Workflow 22 — incident, severity, the health event and the dual-lead P1
    escalation — had exactly one caller, the inbound intent router. So a client
    saying "your trainer arrived 40 minutes late" to a rep's face produced one
    task and nothing else, while the identical words by email paged both leads
    in seconds. `incidents` stayed at 0 through a whole delivery meeting.

    The incident-raising core is shared with the inbound path rather than
    duplicated; the holding reply is NOT, because it is inbound-shaped — you do
    not email someone "we'll get back to you within the hour" while standing in
    the room with them.
    """
    if not complaints:
        return 0
    from app.engines.inbound_engine import raise_complaint_incident

    raised = 0
    for c in complaints:
        detail = (c.get("detail") or "").strip()
        if not detail:
            continue
        await raise_complaint_incident(
            db, org_id=org_id, project=project, description=detail,
            source_type="meeting", source=meeting_id,
            complainant=c.get("raised_by"),
            client_name=lead.name if lead else None,
        )
        raised += 1
    if raised:
        await record_decision(
            db, org_id=org_id, project_id=project.id,
            decision_type=DecisionType.ESCALATION.value, engine=ENGINE,
            decision=f"{raised} complaint(s) raised as incidents from a meeting",
            needs_human=True, confidence=1.0,
            reason=(
                "A complaint stated in a meeting is the same event as one sent by "
                "email, and gets the same response: an incident, both leads paged."
            ),
            entity_type="meeting", entity_id=meeting_id,
        )
    return raised


async def _create_project_shell(
    db: AsyncSession,
    *,
    org_id: str,
    lead: Lead,
    meeting: Meeting,
    program: Program | None,
    name: str,
    objective: str | None,
    value_estimate: float | None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    new_facts: list[str] | None = None,
    stakeholder_specs: list[dict[str, Any]] | None = None,
) -> tuple[Project, Stakeholder | None]:
    """The shared birth of a project: the row, its owner, the meeting linkage,
    the event, stakeholders from the lead's contacts, and intelligence."""
    project = Project(
        org_id=org_id,
        lead_id=lead.id,
        program_id=program.id if program else None,
        name=name,
        objective=objective,
        status=ProjectStatus.PLANNING.value,
        sales_owner_id=None,
        value_estimate=value_estimate,
        start_date=start_date,
        target_end_date=end_date,
        created_from_meeting_id=meeting.id,
    )
    # Sales owner: the lead of the meeting agent's department, else the agent.
    agent = await get_user(db, org_id, meeting.agent_id)
    sales_lead = await find_role_user(db, org_id, Role.SALES_LEAD.value)
    project.sales_owner_id = (sales_lead or agent).id if (sales_lead or agent) else None
    db.add(project)
    await db.flush()
    meeting.project_id = project.id
    meeting.meeting_no = 1

    await events.emit(
        db, org_id=org_id, event_type=EventType.PROJECT_CREATED.value,
        project_id=project.id, entity_type="project", entity_id=project.id,
        details={"name": project.name, "value_estimate": value_estimate},
    )

    # Stakeholders from the lead's contacts. The role is FREE-FORM — the
    # client organisation's own vocabulary (principal, cto, procurement_head,
    # store_manager...) — taken from the model's read of the discussion when
    # it identified the person, else from the contact's recorded title.
    # No fixed role list exists anywhere; only `influence` is a vocabulary.
    contacts = list((
        await db.execute(select(Contact).where(Contact.lead_id == lead.id))
    ).scalars().all())
    specs = stakeholder_specs or []

    # F41: the loop below is correct and always was — it simply had nothing to
    # iterate. A first meeting introduces the people, so with no contacts yet on
    # the lead the model's reading of who is who was thrown away entirely, and
    # `primary_stakeholder` fell through to None (which is why all 11 commitments
    # from that meeting carried no holder).
    #
    # So: complete the loop's INPUT, and let the existing loop do the rest. No
    # new stakeholder code — see `ensure_contacts_for_specs` for why calling
    # `sync_stakeholder_specs` here instead would double-create them and drop the
    # `is_primary → decision_maker` rule this function depends on.
    contacts, _created = await ensure_contacts_for_specs(
        db, org_id=org_id, lead_id=lead.id, contacts=contacts, specs=specs,
    )

    primary_stakeholder = None
    primary_contact_stakeholder = None
    for c in contacts:
        spec = _match_stakeholder_spec(specs, c.name) or {}
        if spec.get("other_engagement") and not c.is_primary:
            # F55, same rule as sync_stakeholder_specs: a person whose
            # involvement belongs to a different engagement is a contact on this
            # lead, not a stakeholder on this project. `is_primary` overrides —
            # a hand-designated primary contact is a human's explicit choice and
            # the model does not get to overrule it.
            continue
        stakeholder = Stakeholder(
            org_id=org_id, project_id=project.id, contact_id=c.id,
            role_at_client=spec.get("role") or norm_role(c.title) or "other",
            # The model's judgement of whose word weighs what, when it named
            # the person; the deterministic default (primary contact = the
            # decision maker) otherwise.
            influence=spec.get("influence")
            or ("decision_maker" if c.is_primary else "influencer"),
            receives_progress_updates=bool(spec.get("receives_updates")) or c.is_primary,
        )
        db.add(stakeholder)
        await db.flush()
        if c.is_primary and primary_contact_stakeholder is None:
            primary_contact_stakeholder = stakeholder
        if stakeholder.influence == "decision_maker" and primary_stakeholder is None:
            primary_stakeholder = stakeholder
    if primary_stakeholder is None:
        # Commitments still need a holder even when nobody was classified
        # as the final decision maker.
        primary_stakeholder = primary_contact_stakeholder

    # Client intelligence from the meeting's reusable facts.
    for fact in new_facts or []:
        db.add(
            ClientIntelligence(
                org_id=org_id, lead_id=lead.id, note=fact,
                category="from_meeting", source="system", added_by="ai",
            )
        )
    return project, primary_stakeholder


async def _record_skill_gaps(
    db: AsyncSession, *, org_id: str, project_id: str, gaps: list[str]
) -> None:
    """A generated plan needs skills nobody in the org holds — that is a
    hiring/training signal for a human, never a silent fallback."""
    if not gaps:
        return
    await record_decision(
        db, org_id=org_id, project_id=project_id,
        decision_type=DecisionType.ASSIGNMENT.value, engine=ENGINE,
        decision=f"Skill gap: no one holds {', '.join(gaps)}",
        reason="The plan requires skills missing from the team's skill records. "
        "Affected tasks fall to the phase lead until someone with the skill "
        "is recorded or the lead reassigns.",
        needs_human=True, confidence=0.9,
        entity_type="project", entity_id=project_id,
    )


async def propose_project_from_spec(
    db: AsyncSession,
    *,
    org_id: str,
    lead: Lead,
    meeting: Meeting,
    spec: dict[str, Any],
    agreed_tasks: list[dict[str, Any]] | None = None,
    hold_for_review: bool = False,
) -> dict[str, Any]:
    """A first meeting on ANY topic → project + plan v1, authored by the
    model layer and fenced by validation (app/ai/planning.py). Pricing stays
    strictly table-driven."""
    program = None
    if spec.get("program_match"):
        program = (
            await db.execute(
                select(Program).where(
                    Program.org_id == org_id, Program.name == spec["program_match"]
                )
            )
        ).scalar_one_or_none()
    value = await _estimate_value(db, org_id, program, spec.get("pricing_quantity") or None)

    name = spec.get("project_name") or " — ".join(
        [lead.name, program.name if program else "New engagement"]
    )
    if lead.name.split()[0].lower() not in name.lower():
        name = f"{lead.name} — {name}"
    project, primary_stakeholder = await _create_project_shell(
        db, org_id=org_id, lead=lead, meeting=meeting, program=program,
        name=name[:290], objective=spec.get("objective"),
        value_estimate=value,
        start_date=spec.get("start_date"), end_date=spec.get("end_date"),
        new_facts=spec.get("new_facts"),
        stakeholder_specs=spec.get("stakeholders"),
    )
    # F54: a complaint voiced in the very first meeting is still a complaint.
    await raise_meeting_complaints(
        db, org_id=org_id, project=project, lead=lead,
        meeting_id=meeting.id, complaints=spec.get("complaints"),
    )

    task_specs = []
    fenced = await _drop_scheduled_meeting_tasks(
        db, org_id=org_id, meeting=meeting, task_specs=spec["tasks"])
    for t in _drop_duplicates_of_confirmed(fenced, agreed_tasks):
        item = dict(t)
        commitment = item.get("commitment")
        if commitment and primary_stakeholder is not None:
            commitment.setdefault("promised_to", primary_stakeholder.id)
        item["source"] = TaskSource.MEETING.value
        task_specs.append(item)

    await _record_skill_gaps(
        db, org_id=org_id, project_id=project.id, gaps=spec.get("skill_gaps") or []
    )
    plan, approval = await create_plan_version(
        db, org_id=org_id, project=project,
        trigger=PlanTrigger.FIRST_MEETING.value, trigger_ref=meeting.id,
        summary=f"Initial plan from first meeting: {spec.get('summary', '')[:120]}",
        changes=[f"{len(task_specs)} tasks created from the first meeting"],
        new_tasks=task_specs,
        approval_facts={"new_project": True},
        hold_for_meeting=meeting if hold_for_review else None,
    )
    await record_decision(
        db, org_id=org_id, project_id=project.id,
        decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
        input_summary=f"First meeting summary: {spec.get('summary', '')[:400]}",
        decision=f"Project '{project.name}' proposed with plan v1 ({len(task_specs)} tasks)",
        reason="First meeting contained concrete work — plan authored by the "
        "model layer from the discussion itself, validated field by field",
        confidence=spec.get("confidence", 0.75),
        entity_type="project", entity_id=project.id,
    )
    return {
        "action": "project_proposed",
        "project_id": project.id,
        "plan_id": plan.id,
        "approval_id": approval.id if approval else None,
    }


async def propose_project(
    db: AsyncSession,
    *,
    org_id: str,
    lead: Lead,
    meeting: Meeting,
    facts: dict[str, Any],
    text: str,
    agreed_tasks: list[dict[str, Any]] | None = None,
    hold_for_review: bool = False,
) -> dict[str, Any]:
    """Stub-provider path (LLM_PROVIDER=stub, used by tests and dry runs):
    a first meeting with real discussion → project + plan v1 (Workflow 1)."""
    program = await _match_program(db, org_id, text)
    students = facts.get("students")
    value = await _estimate_value(db, org_id, program, students)

    duration = facts.get("duration_days")
    classes = facts.get("classes")
    # The objective is composed from the extracted FACTS (duration, classes,
    # size) — never a raw transcript snippet. Conflict detection and future
    # merges parse it ("7-day" vs a later "5 days").
    objective_bits: list[str] = []
    if duration:
        objective_bits.append(f"{duration}-day")
    objective_bits.append(
        program.name.split("—")[-1].strip() if program else "engagement"
    )
    if classes:
        objective_bits.append(f"for classes {classes[0]}–{classes[1]}")
    if students:
        objective_bits.append(f"(~{students} students)")
    objective = " ".join(objective_bits) if (duration or classes or students) \
        else facts.get("summary")
    project, primary_stakeholder = await _create_project_shell(
        db, org_id=org_id, lead=lead, meeting=meeting, program=program,
        name=" — ".join([lead.name, program.name if program else "New engagement"]),
        objective=objective, value_estimate=value,
        new_facts=facts.get("new_facts", []),
    )

    # Plan v1 tasks — the standard first wave, tailored by the facts.
    detail = []
    if duration:
        detail.append(f"{duration}-day")
    if classes:
        detail.append(f"classes {classes[0]}–{classes[1]}")
    if students:
        detail.append(f"~{students} students")
    suffix = f" ({', '.join(detail)})" if detail else ""
    task_specs: list[dict[str, Any]] = _agreed_task_specs(agreed_tasks)
    for title, phase, skill, due_days, visible in DEFAULT_FIRST_PLAN:
        spec: dict[str, Any] = {
            "title": title + suffix if "syllabus" in title or "proposal" in title.lower() else title,
            "phase": phase,
            "required_skill": skill,
            "due_in_days": due_days,
            "visible_to_client": visible,
            "source": TaskSource.MEETING.value,
        }
        task_specs.append(spec)
    # Commitments extracted from the meeting attach to matching tasks.
    for c in facts.get("commitments", []):
        for spec in task_specs:
            if c.get("skill") and c["skill"] == spec.get("required_skill"):
                spec.setdefault("commitment", {
                    "text": c["text"],
                    "due_in_days": c.get("days", 7),
                    "direction": "ours",
                    "promised_to": primary_stakeholder.id if primary_stakeholder else None,
                })
                break

    plan, approval = await create_plan_version(
        db, org_id=org_id, project=project,
        trigger=PlanTrigger.FIRST_MEETING.value, trigger_ref=meeting.id,
        summary=f"Initial plan from first meeting: {facts.get('summary', '')[:120]}",
        changes=[f"{len(task_specs)} tasks created from the first meeting"],
        new_tasks=task_specs,
        approval_facts={"new_project": True},
        hold_for_meeting=meeting if hold_for_review else None,
    )
    await record_decision(
        db, org_id=org_id, project_id=project.id,
        decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
        input_summary=f"First meeting facts: {facts}",
        decision=f"Project '{project.name}' proposed with plan v1 ({len(task_specs)} tasks)",
        reason="First meeting contained concrete work (program, duration, size)",
        entity_type="project", entity_id=project.id,
    )
    return {
        "action": "project_proposed",
        "project_id": project.id,
        "plan_id": plan.id,
        "approval_id": approval.id if approval else None,
    }


async def _link_meeting(db: AsyncSession, project: Project, meeting: Meeting) -> None:
    from sqlalchemy import func

    meeting.project_id = project.id
    if not meeting.meeting_no:
        meeting.meeting_no = (
            (
                await db.execute(
                    select(func.count(Meeting.id)).where(Meeting.project_id == project.id)
                )
            ).scalar_one()
        )


async def merge_meeting_llm(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    meeting: Meeting,
    text: str,
    agreed_tasks: list[dict[str, Any]] | None = None,
    hold_for_review: bool = False,
) -> dict[str, Any]:
    """The heart of the Planner, generic: the model reads the live plan
    snapshot plus the new transcript and emits a validated diff in the op
    vocabulary — including contradictions as conflicts, never picking a side
    (Workflows 6, 7 — any topic)."""
    from app.ai import planning

    await _link_meeting(db, project, meeting)
    diff = await planning.generate_plan_merge(
        db, org_id=org_id, project=project, text=text, source_kind="meeting",
        agreed_tasks=agreed_tasks,
    )

    # New client facts are kept regardless of what the plan does.
    for fact in diff["new_facts"]:
        db.add(
            ClientIntelligence(
                org_id=org_id, lead_id=project.lead_id, note=fact,
                category="from_meeting", source="system", added_by="ai",
            )
        )

    # People the meeting revealed are synced regardless of what the plan
    # does — the Planner, not a human, keeps the stakeholder map current.
    stakeholder_notes = await sync_stakeholder_specs(
        db, org_id=org_id, project=project, specs=diff.get("stakeholders") or []
    )
    # F54: the delivery meeting where this was found WAS a merge — meeting 4.
    await raise_meeting_complaints(
        db, org_id=org_id, project=project,
        lead=(await db.execute(select(Lead).where(Lead.id == project.lead_id)))
        .scalar_one_or_none(),
        meeting_id=meeting.id, complaints=diff.get("complaints"),
    )
    if stakeholder_notes:
        await record_decision(
            db, org_id=org_id, project_id=project.id,
            decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
            decision="Stakeholder map updated from this meeting",
            reason="; ".join(stakeholder_notes),
            confidence=diff["confidence"],
            entity_type="meeting", entity_id=meeting.id,
        )

    if diff["no_change"]:
        await record_decision(
            db, org_id=org_id, project_id=project.id,
            decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
            decision="No plan change from this meeting",
            reason=diff["summary"] or "The discussion required no plan change",
            confidence=diff["confidence"],
            entity_type="meeting", entity_id=meeting.id,
        )
        return {"action": "no_changes", "stakeholder_notes": stakeholder_notes}

    # Contradictions hold the re-plan for a named human (never pick a side).
    conflict: Conflict | None = None
    if diff["conflicts"]:
        raised_to = await get_user(db, org_id, project.sales_owner_id)
        first_meeting = (
            await db.execute(
                select(Meeting)
                .where(Meeting.project_id == project.id)
                .order_by(Meeting.created_at)
            )
        ).scalars().first()
        for description in diff["conflicts"]:
            row = Conflict(
                org_id=org_id, project_id=project.id,
                description=description,
                source_a_type="meeting",
                source_a=first_meeting.id if first_meeting else None,
                source_b_type="meeting", source_b=meeting.id,
                raised_to_user_id=raised_to.id if raised_to else None,
                status=ConflictStatus.OPEN.value,
            )
            db.add(row)
            await db.flush()
            if conflict is None:
                conflict = row
            await events.emit(
                db, org_id=org_id, event_type=EventType.CONFLICT_RAISED.value,
                project_id=project.id, entity_type="conflict", entity_id=row.id,
                details={"description": row.description},
            )
            await record_decision(
                db, org_id=org_id, project_id=project.id,
                decision_type=DecisionType.CONFLICT_RAISED.value, engine=ENGINE,
                decision="Re-plan held — conflicting instructions",
                reason=row.description, needs_human=True,
                entity_type="conflict", entity_id=row.id,
            )
            if raised_to is not None:
                await notify(
                    db, org_id=org_id, user_id=raised_to.id,
                    title="Two sources said different things",
                    body=row.description
                    + " — the re-plan is held until you resolve it.",
                    kind="escalation", entity_type="conflict", entity_id=row.id,
                )

    new_tasks = []
    fenced = await _drop_scheduled_meeting_tasks(
        db, org_id=org_id, meeting=meeting, task_specs=diff["new_tasks"])
    for t in _drop_duplicates_of_confirmed(fenced, agreed_tasks):
        item = dict(t)
        item["source"] = TaskSource.MEETING.value
        new_tasks.append(item)
    await _record_skill_gaps(
        db, org_id=org_id, project_id=project.id, gaps=diff["skill_gaps"]
    )

    date_shift_days = 0
    for op in diff["ops"]:
        if op["op"] == "redate" and op.get("old_due") and op.get("new_due"):
            old = datetime.fromisoformat(op["old_due"])
            new = datetime.fromisoformat(op["new_due"])
            date_shift_days = max(date_shift_days, abs((new - old).days))

    change_lines = (diff["changes"] or ["Held by conflict"]) + stakeholder_notes
    plan, approval = await create_plan_version(
        db, org_id=org_id, project=project,
        trigger=PlanTrigger.NEW_MEETING.value, trigger_ref=meeting.id,
        summary=f"Merge of meeting {meeting.meeting_no}: {diff['summary'][:120]}",
        changes=change_lines,
        new_tasks=new_tasks,
        pending_ops=diff["ops"],
        held_by_conflict=conflict,
        approval_facts={"date_shift_days": date_shift_days},
        hold_for_meeting=meeting if hold_for_review else None,
    )
    return {
        "action": "plan_merged" if conflict is None else "held_by_conflict",
        "plan_id": plan.id,
        "conflict_id": conflict.id if conflict else None,
        "approval_id": approval.id if approval else None,
    }


async def merge_meeting(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    meeting: Meeting,
    facts: dict[str, Any],
    text: str,
    agreed_tasks: list[dict[str, Any]] | None = None,
    hold_for_review: bool = False,
) -> dict[str, Any]:
    """Stub-provider merge (LLM_PROVIDER=stub, tests/dry runs): keyword facts
    merged with the regex conflict check — production uses merge_meeting_llm."""
    await _link_meeting(db, project, meeting)

    changes: list[str] = []
    existing_titles = set(
        (
            await db.execute(
                select(ActionItem.title).where(
                    ActionItem.project_id == project.id,
                    ActionItem.status.notin_(
                        [ActionItemStatus.CANCELLED.value,
                         ActionItemStatus.SUPERSEDED.value]
                    ),
                )
            )
        ).scalars().all()
    )
    new_tasks: list[dict[str, Any]] = _agreed_task_specs(
        agreed_tasks, skip_titles=existing_titles
    )
    if new_tasks:
        changes.append(f"{len(new_tasks)} task(s) confirmed by the agent at the review gate")
    pending_ops: list[dict[str, Any]] = []

    # Conflict detection: new duration vs committed duration.
    conflict = None
    new_duration = facts.get("duration_days")
    if new_duration and project.objective:
        import re

        m = re.search(r"(\d+)[- ]day", project.objective)
        if m and int(m.group(1)) != new_duration:
            old_duration = int(m.group(1))
            raised_to = await get_user(db, org_id, project.sales_owner_id)
            first_meeting = (
                await db.execute(
                    select(Meeting)
                    .where(Meeting.project_id == project.id)
                    .order_by(Meeting.created_at)
                )
            ).scalars().first()
            conflict = Conflict(
                org_id=org_id, project_id=project.id,
                description=(
                    f"Duration disagreement: earlier source says {old_duration} days; "
                    f"meeting {meeting.meeting_no} says {new_duration} days"
                ),
                source_a_type="meeting",
                source_a=first_meeting.id if first_meeting else None,
                source_b_type="meeting", source_b=meeting.id,
                raised_to_user_id=raised_to.id if raised_to else None,
                status=ConflictStatus.OPEN.value,
            )
            db.add(conflict)
            await db.flush()
            await events.emit(
                db, org_id=org_id, event_type=EventType.CONFLICT_RAISED.value,
                project_id=project.id, entity_type="conflict", entity_id=conflict.id,
                details={"description": conflict.description},
            )
            await record_decision(
                db, org_id=org_id, project_id=project.id,
                decision_type=DecisionType.CONFLICT_RAISED.value, engine=ENGINE,
                decision="Re-plan held — conflicting instructions",
                reason=conflict.description, needs_human=True,
                entity_type="conflict", entity_id=conflict.id,
            )
            if raised_to is not None:
                await notify(
                    db, org_id=org_id, user_id=raised_to.id,
                    title="Two people said different things",
                    body=conflict.description + " — the re-plan is held until you resolve it.",
                    kind="escalation", entity_type="conflict", entity_id=conflict.id,
                )

    # Anchor dates: new concrete dates re-date open delivery-phase work.
    dates = [datetime.fromisoformat(d) for d in facts.get("dates", [])]
    if dates and conflict is None:
        start = min(dates)
        if project.start_date != start:
            old_start = project.start_date
            project.start_date = start
            if facts.get("duration_days"):
                project.target_end_date = start + timedelta(days=facts["duration_days"] - 1)
            open_tasks = (
                await db.execute(
                    select(ActionItem).where(
                        ActionItem.project_id == project.id,
                        ActionItem.status.in_(
                            [ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value]
                        ),
                    )
                )
            ).scalars().all()
            moved = 0
            for t in open_tasks:
                if t.due_date and t.due_date > start:
                    new_due = start - timedelta(days=2)
                    pending_ops.append(
                        {
                            "op": "redate", "task_id": t.id,
                            "old_due": t.due_date.isoformat(),
                            "new_due": new_due.isoformat(),
                        }
                    )
                    moved += 1
            changes.append(
                f"Delivery anchored to {start:%d %b}"
                + (f" (was {old_start:%d %b})" if old_start else "")
                + (f"; {moved} due date(s) moved" if moved else "")
            )

    # New capability needs → new tasks (batches for small labs, etc.).
    if facts.get("computers") and facts.get("students") and facts["students"] > facts["computers"]:
        new_tasks.append(
            {
                "title": f"Design batch schedule for {facts['computers']}-computer lab "
                f"(~{facts['students']} students → batches)",
                "phase": Phase.PREPARATION.value,
                "required_skill": "scheduling",
                "due_in_days": 6,
                "visible_to_client": False,
                "source": TaskSource.MEETING.value,
            }
        )
        changes.append(f"Batch schedule needed: {facts['computers']} computers for {facts['students']} students")

    # New commitments from this meeting.
    for c in facts.get("commitments", []):
        exists = (
            await db.execute(
                select(ClientCommitment).where(
                    ClientCommitment.project_id == project.id,
                    ClientCommitment.text == c["text"],
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            new_tasks.append(
                {
                    "title": c["text"],
                    "phase": Phase.PREPARATION.value,
                    "required_skill": c.get("skill"),
                    "due_in_days": c.get("days", 7),
                    "visible_to_client": True,
                    "source": TaskSource.MEETING.value,
                    "commitment": {"text": c["text"], "due_in_days": c.get("days", 7)},
                }
            )
            changes.append(f"New commitment: {c['text']}")

    # New school facts → intelligence.
    for fact in facts.get("new_facts", []):
        db.add(
            ClientIntelligence(
                org_id=org_id, lead_id=project.lead_id, note=fact,
                category="from_meeting", source="system", added_by="ai",
            )
        )

    if not changes and not new_tasks and conflict is None:
        return {"action": "no_changes"}

    date_shift_days = 0
    for op in pending_ops:
        old = datetime.fromisoformat(op["old_due"])
        new = datetime.fromisoformat(op["new_due"])
        date_shift_days = max(date_shift_days, abs((new - old).days))

    plan, approval = await create_plan_version(
        db, org_id=org_id, project=project,
        trigger=PlanTrigger.NEW_MEETING.value, trigger_ref=meeting.id,
        summary=f"Merge of meeting {meeting.meeting_no}: {facts.get('summary', '')[:120]}",
        changes=changes or ["Held by conflict"],
        new_tasks=new_tasks,
        pending_ops=pending_ops,
        held_by_conflict=conflict,
        approval_facts={"date_shift_days": date_shift_days},
        hold_for_meeting=meeting if hold_for_review else None,
    )
    return {
        "action": "plan_merged" if conflict is None else "held_by_conflict",
        "plan_id": plan.id,
        "conflict_id": conflict.id if conflict else None,
        "approval_id": approval.id if approval else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Conflict resolution → the held plan proceeds
# ─────────────────────────────────────────────────────────────────────────────


async def resolve_conflict(
    db: AsyncSession,
    *,
    org_id: str,
    conflict: Conflict,
    resolution_note: str,
    resolved_by: str,
) -> None:
    conflict.status = ConflictStatus.RESOLVED.value
    conflict.resolution_note = resolution_note
    conflict.resolved_by = resolved_by
    conflict.resolved_at = utcnow()
    await events.emit(
        db, org_id=org_id, event_type=EventType.CONFLICT_RESOLVED.value,
        project_id=conflict.project_id, entity_type="conflict", entity_id=conflict.id,
        actor=resolved_by, details={"resolution": resolution_note},
    )
    if conflict.held_plan_id:
        # The held plan proceeds through normal review.
        plan = (
            await db.execute(
                select(ActionPlan).where(ActionPlan.id == conflict.held_plan_id)
            )
        ).scalar_one_or_none()
        if plan is not None and plan.status == PlanStatus.DRAFT.value:
            from app.engines import approval_engine

            # F49 fallout, caught while adding the activation guard: a plan can
            # sit held by a conflict for days while newer plans are created and
            # activated around it (exactly the state Round 7 left — v5 held by
            # 4 open conflicts, v6 live). Releasing it into review would then
            # offer an approver a card that the activation guard must refuse,
            # which is a dead end dressed as a decision. Retire it instead, and
            # say so.
            project_row = (
                await db.execute(
                    select(Project).where(Project.id == conflict.project_id)
                )
            ).scalar_one()
            newer = await newer_active_plan(
                db, project_id=conflict.project_id, version=plan.version
            )
            if newer is not None:
                await retire_superseded_plan(
                    db, org_id=org_id, project=project_row, old=plan,
                    replaced_by_label=f"plan v{newer.version}",
                    decision_reason=(
                        f"Conflict resolved, but v{newer.version} became the live "
                        f"plan while v{plan.version} was held — releasing it would "
                        f"have rolled the project back. Re-plan from "
                        f"v{newer.version} to carry these decisions forward."
                    ),
                )
                if conflict.raised_to_user_id:
                    await notify(
                        db, org_id=org_id, user_id=conflict.raised_to_user_id,
                        title=f"Conflict resolved — plan v{plan.version} is out of date",
                        body=f"The re-plan held by this conflict was overtaken by "
                             f"plan v{newer.version}. It was not applied. Re-plan "
                             f"from v{newer.version} to keep this resolution.",
                        kind="plan_updated", entity_type="action_plan",
                        entity_id=plan.id,
                    )
                return

            plan.status = PlanStatus.PENDING_REVIEW.value
            approval = await approval_engine.request_approval(
                db, org_id=org_id,
                entity_type=ApprovalEntityType.PLAN_CHANGE.value,
                entity_id=plan.id, project_id=conflict.project_id,
                facts={"conflict_resolved": True, "tasks_added": 0},
                reason=f"Held plan v{plan.version} released — conflict resolved: {resolution_note}",
                default_approver_role=Role.SALES_LEAD.value,
            )
            if approval is None:
                await activate_plan(db, org_id=org_id, plan_id=plan.id, approved_by="system")


# ─────────────────────────────────────────────────────────────────────────────
# Phase shift — playbook waves (Workflows 8, 26)
# ─────────────────────────────────────────────────────────────────────────────


async def phase_shift(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    phase: str,
    anchor_date: datetime | None = None,
) -> dict[str, Any]:
    """Generate the phase's task wave from the program playbook, tailored to
    the project, as a new plan version."""
    playbook = (
        await db.execute(
            select(Playbook).where(
                Playbook.org_id == org_id,
                Playbook.program_id == (project.program_id or ""),
                Playbook.phase == phase,
                Playbook.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    entries = list(playbook.entries or []) if playbook else []
    anchor = anchor_date or project.start_date or (utcnow() + timedelta(days=21))
    new_tasks: list[dict[str, Any]] = []
    for e in entries:
        due = anchor + timedelta(days=int(e.get("offset_days", -7)))
        new_tasks.append(
            {
                "title": e["title"],
                "phase": phase,
                "required_skill": e.get("required_skill"),
                "due_date": due,
                "priority": e.get("priority", "P2"),
                "visible_to_client": bool(e.get("visible_to_client", False)),
                "source": TaskSource.PLAYBOOK.value,
                "assign_on": e.get("assign_on", "plan_activation"),
            }
        )
    if not new_tasks and nlu.llm_available():
        # No playbook for this program+phase — derive the wave from the
        # project itself instead of stalling (generic engagements have no
        # catalogue entry to inherit from).
        from app.ai import planning

        try:
            specs, gaps = await planning.generate_phase_wave(
                db, org_id=org_id, project=project, phase=phase, anchor=anchor
            )
        except planning.PlanningUnavailable:
            specs, gaps = [], []
        for s in specs:
            s["source"] = TaskSource.AI_REFINEMENT.value
            new_tasks.append(s)
        await _record_skill_gaps(
            db, org_id=org_id, project_id=project.id, gaps=gaps
        )
    if not new_tasks:
        return {"action": "no_playbook"}
    plan, approval = await create_plan_version(
        db, org_id=org_id, project=project,
        trigger=PlanTrigger.PHASE_SHIFT.value, trigger_ref=project.id,
        summary=f"{phase.capitalize()} wave from playbook v{playbook.version}"
        if playbook and playbook.entries
        else f"{phase.capitalize()} wave derived from the project objective",
        changes=[
            f"{len(new_tasks)} {phase} task(s) generated from "
            + ("the playbook" if playbook and playbook.entries else "the project itself")
        ],
        new_tasks=new_tasks,
        approval_facts={"phase_shift": phase},
    )
    return {
        "action": "wave_generated",
        "plan_id": plan.id,
        "tasks": len(new_tasks),
        "approval_id": approval.id if approval else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Feasibility (asked before anything is promised to a client)
# ─────────────────────────────────────────────────────────────────────────────


async def feasibility_pass(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    date_from: datetime,
    date_to: datetime,
) -> dict[str, Any]:
    """Can the project team work this window? Consults the Resource &
    Calendar Engine across ALL projects."""
    member_ids = (
        await db.execute(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.left_at.is_(None),
            )
        )
    ).scalars().all()
    users = (
        await db.execute(select(User).where(User.id.in_(member_ids or [""])))
    ).scalars().all()
    conflicts = await resource_engine.feasibility(
        db, org_id=org_id, users=users, date_from=date_from, date_to=date_to
    )
    blockers = {uid: c for uid, c in conflicts.items() if c}
    feasible = not blockers
    names = {u.id: u.name for u in users}
    detail = (
        "all team members free"
        if feasible
        else "; ".join(f"{names.get(uid, uid)}: {', '.join(c)}" for uid, c in blockers.items())
    )
    await record_decision(
        db, org_id=org_id, project_id=project.id,
        decision_type=DecisionType.FEASIBILITY.value, engine=ENGINE,
        decision="feasible" if feasible else "not feasible",
        reason=f"Window {date_from:%d %b}–{date_to:%d %b}: {detail}",
        confidence=0.95,
    )
    return {"feasible": feasible, "detail": detail, "blockers": blockers}
