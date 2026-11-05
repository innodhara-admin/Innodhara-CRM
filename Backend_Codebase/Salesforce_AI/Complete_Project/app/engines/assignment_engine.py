"""Assignment Engine — picks the best person for every task, on facts, not
vibes (30-Workflows §4 engine 2, Workflow 9 deep dive).

Candidate order (strict):
  a) project members whose user_skills match the required skill,
  b) org users in the right department with the skill,
  c) the phase owner — flagged "no skill match".

Scoring facts: skill level, load vs max_open_tasks, leave, continuity,
due-date fit, field days. Batch assignment updates a working load count after
every pick, so the same "free" expert can never win every task.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.core.constants import (
    ActionItemStatus,
    AssignmentMode,
    AssignmentStatus,
    DecisionType,
    EventType,
    PHASE_LEAD_ROLE,
    PRIORITY_ORDER,
    Role,
    SKILL_LEVEL_SCORE,
    TaskPriority,
)
from app.engines import events, resource_engine
from app.engines.common import find_role_user, get_org_settings, record_decision
from app.models.action_item import ActionItem
from app.models.organisation import OrgSettings
from app.models.project import Project, ProjectMember
from app.models.user import User, UserSkill
from app.models.work import Assignment
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "assignment"
OPEN_STATUSES = (ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value)


@dataclass
class Candidate:
    user: User
    skill_level: str | None          # None = no skill match
    load: int                        # open + in_progress tasks (all projects)
    continuity: int                  # related tasks done on this project
    field_days: int
    conflicts: list[str] = field(default_factory=list)  # leave/booking clashes
    extra_load: int = 0              # working count added during a batch

    @property
    def effective_load(self) -> int:
        return self.load + self.extra_load

    def score(self) -> float:
        skill = SKILL_LEVEL_SCORE.get(self.skill_level or "", 0)
        cap = max(self.user.max_open_tasks or 8, 1)
        load_penalty = self.effective_load / cap
        return skill * 10 - load_penalty * 6 - self.field_days * 0.5 + self.continuity * 1.5

    def reason(self) -> str:
        cap = self.user.max_open_tasks or 8
        bits = [
            f"{self.user.name}: "
            + (f"{self.skill_level} skill match" if self.skill_level else "no skill match"),
            f"{self.effective_load}/{cap} open tasks",
        ]
        if self.continuity:
            bits.append(f"did {self.continuity} related task(s) on this project")
        if self.field_days:
            bits.append(f"{self.field_days} field day(s) this week")
        if self.conflicts:
            bits.append("but: " + "; ".join(self.conflicts))
        return ", ".join(bits)


async def _user_load(db: AsyncSession, org_id: str, user_id: str) -> int:
    return (
        await db.execute(
            select(func.count(ActionItem.id)).where(
                ActionItem.org_id == org_id,
                ActionItem.assignee_id == user_id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalar_one()


async def _continuity(db: AsyncSession, org_id: str, user_id: str, project_id: str | None) -> int:
    if not project_id:
        return 0
    return (
        await db.execute(
            select(func.count(ActionItem.id)).where(
                ActionItem.org_id == org_id,
                ActionItem.assignee_id == user_id,
                ActionItem.project_id == project_id,
            )
        )
    ).scalar_one()


async def _skill_map(db: AsyncSession, org_id: str, skill: str | None) -> dict[str, str]:
    """user_id → level for everyone holding the skill."""
    if not skill:
        return {}
    rows = (
        await db.execute(
            select(UserSkill).where(UserSkill.org_id == org_id, UserSkill.skill == skill)
        )
    ).scalars().all()
    return {r.user_id: r.level for r in rows}


async def build_candidates(
    db: AsyncSession,
    *,
    org_id: str,
    task: ActionItem,
    exclude_user_ids: set[str] | None = None,
) -> tuple[list[Candidate], str]:
    """The strict candidate ladder. Returns (candidates, tier_used)."""
    exclude = exclude_user_ids or set()
    skills = await _skill_map(db, org_id, task.required_skill)
    project = None
    if task.project_id:
        project = (
            await db.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one_or_none()

    async def to_candidates(users: list[User]) -> list[Candidate]:
        out: list[Candidate] = []
        window_from = utcnow()
        window_to = task.due_date or (window_from + timedelta(days=7))
        for u in users:
            if u.id in exclude or not u.is_active:
                continue
            conflicts = await resource_engine.conflicts_for(
                db, org_id=org_id, user=u, date_from=window_from, date_to=window_to
            )
            out.append(
                Candidate(
                    user=u,
                    skill_level=skills.get(u.id),
                    load=await _user_load(db, org_id, u.id),
                    continuity=await _continuity(db, org_id, u.id, task.project_id),
                    field_days=await resource_engine.field_days_in_week(
                        db, org_id=org_id, user_id=u.id,
                        around=(task.due_date.date() if task.due_date else None),
                    ),
                    conflicts=conflicts,
                )
            )
        return out

    # Tier a: project members with the skill.
    if project is not None:
        member_ids = [
            m.user_id
            for m in (
                await db.execute(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project.id,
                        ProjectMember.left_at.is_(None),
                    )
                )
            ).scalars().all()
        ]
        if member_ids:
            members = (
                await db.execute(select(User).where(User.id.in_(member_ids)))
            ).scalars().all()
            tier_a = await to_candidates([u for u in members if u.id in skills])
            tier_a = [c for c in tier_a if not c.conflicts]
            if tier_a:
                return tier_a, "project_member"

    # Tier b: org users (right department if the phase implies one) with skill.
    if skills:
        users = (
            await db.execute(
                select(User).where(User.org_id == org_id, User.id.in_(list(skills)))
            )
        ).scalars().all()
        tier_b = await to_candidates(users)
        available = [c for c in tier_b if not c.conflicts]
        if available:
            return available, "org_skill"
        if tier_b:  # everyone with the skill is booked/on leave — surface that
            return tier_b, "org_skill_conflicted"

    # Tier c: the phase owner, flagged "no skill match".
    fallback: User | None = None
    if project is not None and task.phase in ("preparation", "delivery", "payment", "closure"):
        if project.ops_owner_id:
            fallback = (
                await db.execute(select(User).where(User.id == project.ops_owner_id))
            ).scalar_one_or_none()
    if fallback is None and project is not None and project.sales_owner_id:
        fallback = (
            await db.execute(select(User).where(User.id == project.sales_owner_id))
        ).scalar_one_or_none()
    if fallback is None:
        lead_role = PHASE_LEAD_ROLE.get(task.phase or "", Role.OPERATIONS_LEAD.value)
        fallback = await find_role_user(db, org_id, lead_role)
    if fallback is not None and fallback.id not in exclude:
        return await to_candidates([fallback]), "phase_lead_fallback"
    return [], "none"


def _pick(candidates: list[Candidate], org: OrgSettings) -> tuple[Candidate | None, bool, str]:
    """Choose the winner. Returns (winner, is_tie_for_lead, note)."""
    if not candidates:
        return None, False, "no candidates"
    # High-load caution: steer away from people above the caution threshold,
    # unless they are the only skill match (Workflow 13).
    caution = (org.high_load_caution_pct or 80) / 100.0
    def overloaded(c: Candidate) -> bool:
        cap = max(c.user.max_open_tasks or 8, 1)
        return c.effective_load / cap >= caution
    pool = [c for c in candidates if not overloaded(c)] or candidates
    pool = sorted(pool, key=lambda c: -c.score())
    if len(pool) >= 2 and abs(pool[0].score() - pool[1].score()) < 0.01:
        # tie → prefer lower load; then fewer P1s is approximated by load;
        # a genuine tie after that goes to the lead as a question.
        if pool[0].effective_load != pool[1].effective_load:
            pool.sort(key=lambda c: (c.effective_load, -c.score()))
        else:
            return pool[0], True, "tie between equally-suited candidates"
    return pool[0], False, ""


async def assign_task(
    db: AsyncSession,
    *,
    org_id: str,
    task: ActionItem,
    exclude_user_ids: set[str] | None = None,
    working_loads: dict[str, int] | None = None,
    notify_assignee: bool | None = None,
    assigned_by: str = "ai",
) -> Assignment | None:
    """Assign one task (one decision in a batch when working_loads is shared)."""
    org = await get_org_settings(db, org_id)
    candidates, tier = await build_candidates(
        db, org_id=org_id, task=task, exclude_user_ids=exclude_user_ids
    )
    if working_loads:
        for c in candidates:
            c.extra_load = working_loads.get(c.user.id, 0)

    winner, is_tie, note = _pick(candidates, org)
    if winner is None:
        await record_decision(
            db, org_id=org_id, project_id=task.project_id,
            decision_type=DecisionType.ASSIGNMENT.value, engine=ENGINE,
            input_summary=f"Task: {task.title} (skill: {task.required_skill})",
            decision="no assignment", reason="No candidate exists in the organisation",
            confidence=0.0, needs_human=True,
            entity_type="action_item", entity_id=task.id,
        )
        return None

    # Confidence: full skill match high; fallback/downgrade low → lead question.
    skill_score = SKILL_LEVEL_SCORE.get(winner.skill_level or "", 0)
    confidence = {3: 0.94, 2: 0.8, 1: 0.55, 0: 0.4}[skill_score]
    if tier == "phase_lead_fallback":
        confidence = 0.4
    if is_tie:
        confidence = 0.5
    needs_human = confidence < (org.ai_confidence_threshold or 0.6)

    reason = winner.reason()
    if tier == "phase_lead_fallback":
        reason += f" — skill gap: {task.required_skill}; assigned to phase lead by default"
    if is_tie:
        reason += " — tie; lead should confirm or change"
    # P1 may exceed capacity, but must then propose what to postpone.
    cap = max(winner.user.max_open_tasks or 8, 1)
    if winner.effective_load >= cap and task.priority == TaskPriority.P1.value:
        postpone = (
            await db.execute(
                select(ActionItem)
                .where(
                    ActionItem.org_id == org_id,
                    ActionItem.assignee_id == winner.user.id,
                    ActionItem.status.in_(OPEN_STATUSES),
                    ActionItem.priority != TaskPriority.P1.value,
                )
                .order_by(ActionItem.due_date.desc())
            )
        ).scalars().first()
        if postpone is not None:
            reason += (
                f" — capacity exceeded for P1; propose postponing "
                f"'{postpone.title}' (due {postpone.due_date:%d %b})"
                if postpone.due_date else
                f" — capacity exceeded for P1; propose postponing '{postpone.title}'"
            )

    previous = task.assignee_id
    task.assignee_id = winner.user.id
    task.assigned_by = assigned_by
    task.assignment_reason = reason

    auto = org.assignment_mode == AssignmentMode.AUTO.value
    status = (
        AssignmentStatus.AUTO_ACCEPTED.value if auto and not needs_human
        else AssignmentStatus.PROPOSED.value
    )
    assignment = Assignment(
        org_id=org_id,
        action_item_id=task.id,
        from_user_id=previous,
        to_user_id=winner.user.id,
        assigned_by=assigned_by,
        reason=reason,
        status=status,
    )
    db.add(assignment)
    await db.flush()

    await record_decision(
        db, org_id=org_id, project_id=task.project_id,
        decision_type=DecisionType.ASSIGNMENT.value, engine=ENGINE,
        input_summary=(
            f"Task: {task.title} (skill: {task.required_skill}, {task.priority}, "
            f"due {task.due_date:%d %b}). " if task.due_date else
            f"Task: {task.title} (skill: {task.required_skill}, {task.priority}). "
        ) + f"Candidates: {', '.join(c.reason() for c in candidates[:4])}",
        decision=f"Assigned to {winner.user.name}",
        reason=reason, confidence=confidence, needs_human=needs_human,
        entity_type="action_item", entity_id=task.id,
    )

    if working_loads is not None:
        working_loads[winner.user.id] = working_loads.get(winner.user.id, 0) + 1

    # Notify: in auto mode immediately; in lead_confirm the batch confirmation
    # screen notifies (confirm_batch below). Explicit override wins.
    should_notify = notify_assignee if notify_assignee is not None else (auto and not needs_human)
    if should_notify:
        await notify(
            db, org_id=org_id, user_id=winner.user.id,
            title=f"New task: {task.title}",
            body=(f"Due {task.due_date:%d %b} · " if task.due_date else "")
            + f"assigned by AI: {reason}",
            kind="task_assigned", entity_type="action_item", entity_id=task.id,
        )
    return assignment


async def assign_batch(
    db: AsyncSession,
    *,
    org_id: str,
    tasks: list[ActionItem],
    assigned_by: str = "ai",
) -> list[Assignment]:
    """A plan is assigned as one batch, in one pass — priority-then-due-date
    order, with a running load count (Workflow 9 step 7)."""
    ordered = sorted(
        tasks,
        key=lambda t: (
            PRIORITY_ORDER.get(t.priority, 2),
            t.due_date or datetime.max,
        ),
    )
    working_loads: dict[str, int] = {}
    out: list[Assignment] = []
    for task in ordered:
        if task.assign_on == "when_ready" and task.depends_on_ids:
            continue  # deliberately unassigned until dependencies clear
        a = await assign_task(
            db, org_id=org_id, task=task, working_loads=working_loads,
            assigned_by=assigned_by,
        )
        if a is not None:
            out.append(a)
    return out


async def confirm_batch(
    db: AsyncSession,
    *,
    org_id: str,
    assignment_ids: list[str],
    confirmed_by: str,
    overrides: dict[str, str] | None = None,
) -> list[Assignment]:
    """The lead's one-screen batch confirmation (lead_confirm mode).

    overrides: {assignment_id: new_user_id} — recorded as status=overridden,
    never as approvals rows (Data Model §8.5 boundary 2).

    Only the ids sent are confirmed, and only while still proposed (2 Oct
    2026): the app now confirms the rows the lead ticks, so a stale screen or
    a double tap can send an id that was already decided. Deciding it again
    would notify the assignee a second time; it is skipped and not counted.
    """
    overrides = overrides or {}
    rows = (
        await db.execute(
            select(Assignment).where(
                Assignment.org_id == org_id, Assignment.id.in_(assignment_ids),
                Assignment.status == AssignmentStatus.PROPOSED.value,
            )
        )
    ).scalars().all()
    for a in rows:
        task = (
            await db.execute(select(ActionItem).where(ActionItem.id == a.action_item_id))
        ).scalar_one_or_none()
        if task is None:
            continue
        if a.id in overrides:
            new_user = (
                await db.execute(
                    select(User).where(User.org_id == org_id, User.id == overrides[a.id])
                )
            ).scalar_one_or_none()
            if new_user is not None:
                a.status = AssignmentStatus.OVERRIDDEN.value
                a.decided_at = utcnow()
                replacement = Assignment(
                    org_id=org_id, action_item_id=task.id,
                    from_user_id=a.to_user_id, to_user_id=new_user.id,
                    assigned_by=confirmed_by,
                    reason=f"Lead override of AI pick ({a.reason})",
                    status=AssignmentStatus.ACCEPTED.value,
                    decided_at=utcnow(),
                )
                db.add(replacement)
                task.assignee_id = new_user.id
                task.assigned_by = confirmed_by
                task.assignment_reason = f"Assigned by lead (overriding AI proposal)"
                await notify(
                    db, org_id=org_id, user_id=new_user.id,
                    title=f"New task: {task.title}",
                    body="Assigned by your lead",
                    kind="task_assigned", entity_type="action_item", entity_id=task.id,
                )
                continue
        a.status = AssignmentStatus.ACCEPTED.value
        a.decided_at = utcnow()
        if task.assignee_id:
            await notify(
                db, org_id=org_id, user_id=task.assignee_id,
                title=f"New task: {task.title}",
                body=(f"Due {task.due_date:%d %b} · " if task.due_date else "")
                + f"assigned by AI: {task.assignment_reason}",
                kind="task_assigned", entity_type="action_item", entity_id=task.id,
            )
    return rows


async def decline_task(
    db: AsyncSession,
    *,
    org_id: str,
    task: ActionItem,
    user: User,
    reason_code: str,
    note: str | None = None,
) -> Assignment | None:
    """Workflow 16 — 'I can't do this'. Reassigns excluding the decliner and
    LEARNS: an 'on_site_elsewhere' decline means the calendar missed a booking;
    the gap is recorded and registered on the spot."""
    latest = (
        await db.execute(
            select(Assignment)
            .where(Assignment.org_id == org_id, Assignment.action_item_id == task.id)
            .order_by(Assignment.created_at.desc())
        )
    ).scalars().first()
    if latest is not None and latest.to_user_id == user.id:
        latest.status = AssignmentStatus.DECLINED.value
        latest.decline_reason = reason_code
        latest.decline_note = note
        latest.decided_at = utcnow()
    else:
        # The task was assigned outside the engine (by hand, or seeded) — the
        # decline is still an assignment event and belongs in the history.
        db.add(
            Assignment(
                org_id=org_id,
                action_item_id=task.id,
                from_user_id=None,
                to_user_id=user.id,
                assigned_by=task.assigned_by or "ai",
                reason=task.assignment_reason or "assigned outside the engine",
                status=AssignmentStatus.DECLINED.value,
                decline_reason=reason_code,
                decline_note=note,
                decided_at=utcnow(),
            )
        )

    task.status = ActionItemStatus.DECLINED.value
    previous_assignee = task.assignee_id
    task.assignee_id = None

    await events.emit(
        db, org_id=org_id, event_type=EventType.TASK_DECLINED.value,
        project_id=task.project_id, entity_type="action_item", entity_id=task.id,
        actor=user.id, details={"reason": reason_code, "note": note or ""},
    )

    # Learning: a calendar-fact decline means a booking was missed.
    if reason_code == "on_site_elsewhere":
        window_from = utcnow()
        window_to = task.due_date or (window_from + timedelta(days=7))
        existing = await resource_engine.bookings_in_window(
            db, org_id=org_id, user_id=user.id, date_from=window_from, date_to=window_to,
        )
        if not existing:
            await resource_engine.book(
                db, org_id=org_id, user_id=user.id, kind="delivery",
                date_from=window_from, date_to=window_to,
                source_type="hold", source=task.id,
                note=f"Registered from decline: {note or 'on-site elsewhere'}",
            )
            await record_decision(
                db, org_id=org_id, project_id=task.project_id,
                decision_type=DecisionType.ESCALATION.value, engine=ENGINE,
                decision="Calendar gap registered",
                reason=(
                    f"{user.name} declined as on-site elsewhere but no booking "
                    "existed — the missing booking is now registered so the "
                    "same surprise cannot happen twice"
                ),
                entity_type="action_item", entity_id=task.id,
            )

    task.status = ActionItemStatus.OPEN.value  # back to open for reassignment
    return await assign_task(
        db, org_id=org_id, task=task,
        exclude_user_ids={user.id} | ({previous_assignee} if previous_assignee else set()),
    )


async def revalidate_assignee(
    db: AsyncSession, *, org_id: str, task: ActionItem
) -> Assignment | None:
    """Ready-time re-validation (Workflow 9 step 8): the moment a task becomes
    ready, confirm its assignee is still available and within capacity —
    a plan never relies on a weeks-old guess."""
    if not task.assignee_id:
        # when_ready task — assign now with fresh data.
        return await assign_task(db, org_id=org_id, task=task)
    user = (
        await db.execute(
            select(User).where(User.org_id == org_id, User.id == task.assignee_id)
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return await assign_task(db, org_id=org_id, task=task)
    window_from = utcnow()
    window_to = task.due_date or (window_from + timedelta(days=7))
    conflicts = await resource_engine.conflicts_for(
        db, org_id=org_id, user=user, date_from=window_from, date_to=window_to
    )
    load = await _user_load(db, org_id, user.id)
    cap = max(user.max_open_tasks or 8, 1)
    if not conflicts and load <= cap:
        return None  # still fine — no churn
    reason = "; ".join(conflicts) if conflicts else f"overloaded ({load}/{cap})"
    await record_decision(
        db, org_id=org_id, project_id=task.project_id,
        decision_type=DecisionType.ASSIGNMENT.value, engine=ENGINE,
        decision=f"Ready-time re-validation: {user.name} no longer suitable",
        reason=reason, confidence=0.9,
        entity_type="action_item", entity_id=task.id,
    )
    return await assign_task(
        db, org_id=org_id, task=task, exclude_user_ids={user.id}
    )


async def rebalance_proposals(
    db: AsyncSession, *, org_id: str, user: User
) -> list[dict]:
    """Workflow 13 — overload. Returns move proposals for the lead's card:
    the person's lowest-priority, not-yet-started tasks with best alternatives."""
    tasks = (
        await db.execute(
            select(ActionItem)
            .where(
                ActionItem.org_id == org_id,
                ActionItem.assignee_id == user.id,
                ActionItem.status == ActionItemStatus.OPEN.value,
            )
            .order_by(ActionItem.due_date.desc())
        )
    ).scalars().all()
    # lowest priority first (P3 before P2 before P1), untouched work only
    tasks = sorted(
        [t for t in tasks if (t.progress_percent or 0) == 0],
        key=lambda t: -PRIORITY_ORDER.get(t.priority, 2),
    )
    proposals: list[dict] = []
    for t in tasks[:2]:
        candidates, _tier = await build_candidates(
            db, org_id=org_id, task=t, exclude_user_ids={user.id}
        )
        org = await get_org_settings(db, org_id)
        winner, _tie, _note = _pick(candidates, org)
        if winner is not None:
            proposals.append(
                {
                    "action_item_id": t.id,
                    "title": t.title,
                    "priority": t.priority,
                    "to_user_id": winner.user.id,
                    "to_user_name": winner.user.name,
                    "reason": winner.reason(),
                }
            )
    return proposals
