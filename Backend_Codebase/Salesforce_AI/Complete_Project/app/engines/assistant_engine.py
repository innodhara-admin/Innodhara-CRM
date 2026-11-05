"""Assistant Engine — the front door for everything a person types or says,
plus the daily personal digests, weekly internal and client reports,
onboarding briefs and 'why did the AI do that?' traces
(30-Workflows §4 engine 10).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import (
    ActionItemStatus,
    ApprovalStatus,
    CommitmentStatus,
    DigestKind,
    EventType,
    MessageKind,
    ProjectHealth,
    ProjectStatus,
)
from app.engines.common import get_org_settings, get_user
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.comms import Approval, InboundMessage
from app.models.finance import Deliverable
from app.models.lead import Contact
from app.models.project import (
    ActionPlan,
    ClientCommitment,
    Project,
    ProjectMember,
    Stakeholder,
)
from app.models.user import User
from app.models.work import AIDecision, Digest, ProgressEvent
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "assistant"
OPEN_STATUSES = (ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value)

# Trailing role words in a seeded name like "YuviPep Admin": the first token is
# then the ORG name, so greeting by it reads as greeting the organisation, not
# the person (finding F15). For those, greet with the whole label instead.
_ROLE_NAME_WORDS = {"admin", "administrator", "lead", "manager", "team", "ops", "operations"}


def _greeting_name(full_name: str | None) -> str:
    """A friendly first name for a normal person ("Siva Kumar" -> "Siva"), but
    the full label when the name is org-derived ("YuviPep Admin" stays whole,
    never "YuviPep")."""
    tokens = (full_name or "").split()
    if not tokens:
        return "there"
    if len(tokens) >= 2 and tokens[-1].lower() in _ROLE_NAME_WORDS:
        return full_name.strip()
    return tokens[0]


def _greeting_word(hour: int) -> str:
    """The salutation for a given local hour.

    The digest used to open "Good morning" whatever the clock said, so a
    quarter past midnight was greeted like breakfast. The bands below are
    deliberately plain, and the small hours get their own line rather than
    being stretched into "evening" — someone reading this at 02:00 knows what
    time it is.

    The hour must be the ORG's local hour (see `clock.org_zone`), never the
    server's: the same rule the rest of this file follows for dates.
    """
    if 5 <= hour < 12:
        return "Good morning"
    if 12 <= hour < 17:
        return "Good afternoon"
    if 17 <= hour < 21:
        return "Good evening"
    return "Working late"


# ─────────────────────────────────────────────────────────────────────────────
# Daily personal digest (internal — never needs approval)
# ─────────────────────────────────────────────────────────────────────────────


async def build_daily_digest(db: AsyncSession, *, org_id: str, user: User) -> Digest:
    now = utcnow()
    # F29/F65: "today" for a follow-up, a demo or a task is the *reader's*
    # today. It used to be `date.today()`, the date in whatever timezone this
    # server process happens to run in, which is nobody's setting — and it was
    # then compared against `due_date.date()`, the date in UTC. Two calendars,
    # one comparison. See `app/core/clock.py`: every judgement below now runs
    # in the organisation's own timezone, and stored instants are asked which
    # local day they fall on rather than being read as if they were dates.
    tz = await clock.org_zone(db, org_id)
    today_local = clock.today(tz)
    tasks = (
        await db.execute(
            select(ActionItem)
            .where(
                ActionItem.org_id == org_id,
                ActionItem.assignee_id == user.id,
                ActionItem.status.in_(OPEN_STATUSES),
            )
            .order_by(ActionItem.priority, ActionItem.due_date)
        )
    ).scalars().all()
    # F52 — these two were meant to partition and did not.
    #
    # `today` compared DATES with `<=` while `overdue` compared DATETIMES with
    # `<`. Due dates are stored at midnight, so a task due today satisfied BOTH:
    # `2026-08-05 <= 2026-08-05` and `2026-08-05 00:00 < 2026-08-05 09:52`. The
    # renderer then guarded the "Due today:" header on `today` and filled it from
    # `[t for t in today if t not in overdue]` — always empty. So every morning
    # the briefing printed a heading over nothing, and announced today's work as
    # already late, from 00:00 on its own due date.
    #
    # Both now use `today_local`, the same local date its six neighbours use —
    # which also closes [F29]'s residue, since the task lists were the one part
    # F29's fix did not reach.
    #
    # ⚠ Do NOT copy this to the Sync Engine. Workflow 10 defines the reminder
    # ladder's overdue as `due_date < now` deliberately: that sweep runs at
    # 18:00, the workday end, where "due today and not done" IS overdue.
    today = [
        t for t in tasks
        if t.due_date and clock.local_date(t.due_date, tz) == today_local
    ]
    overdue = [
        t for t in tasks
        if t.due_date and clock.local_date(t.due_date, tz) < today_local
    ]
    approvals = (
        await db.execute(
            select(Approval).where(
                Approval.org_id == org_id,
                Approval.requested_from_user_id == user.id,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )
    ).scalars().all()
    # Overnight replies on the user's projects.
    member_project_ids = (
        await db.execute(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id, ProjectMember.left_at.is_(None)
            )
        )
    ).scalars().all()
    overnight = []
    if member_project_ids:
        overnight = (
            await db.execute(
                select(InboundMessage).where(
                    InboundMessage.org_id == org_id,
                    InboundMessage.matched_project_id.in_(member_project_ids),
                    InboundMessage.received_at >= now - timedelta(hours=18),
                )
            )
        ).scalars().all()

    # Follow-ups and demos (finding F3). The digest used to consult only tasks,
    # approvals and overnight replies, so a person whose whole day was a
    # follow-up and a demo got a heading and nothing under it — while the "My
    # day" cards directly below said "1 due today", contradicting it on the
    # same screen.
    from app.core.constants import DemoStatus, FollowUpStatus
    from app.models.demo import Demo
    from app.models.followup import FollowUp
    from app.models.lead import Lead

    followups = (
        await db.execute(
            select(FollowUp, Lead)
            .join(Lead, Lead.id == FollowUp.lead_id)
            .where(
                FollowUp.org_id == org_id,
                FollowUp.owner_id == user.id,
                FollowUp.status == FollowUpStatus.PENDING.value,
                FollowUp.due_date <= today_local,
            )
            .order_by(FollowUp.due_date)
        )
    ).all()
    # Demos on the leads this person owns, today and the week ahead.
    demos = (
        await db.execute(
            select(Demo, Lead)
            .join(Lead, Lead.id == Demo.lead_id)
            .where(
                Demo.org_id == org_id,
                Lead.owner_id == user.id,
                Demo.status == DemoStatus.SCHEDULED.value,
                Demo.scheduled_date >= today_local,
                Demo.scheduled_date <= today_local + timedelta(days=7),
            )
            .order_by(Demo.scheduled_date)
        )
    ).all()

    # Customer ask, 21 Sep 2026: a task about "ABC School" says so, and the
    # name opens that client. The client is the task's own lead, else its
    # project's lead. Rendered as a link the app resolves
    # (yuvipep://lead/<id>); this digest is only ever shown in the app. Put
    # AFTER "title (due …)" so that text stays as it always was.
    project_leads = dict(
        (await db.execute(
            select(Project.id, Project.lead_id).where(
                Project.id.in_({t.project_id for t in tasks if t.project_id} or {""}))
        )).all()
    )
    task_lead = {t.id: t.lead_id or project_leads.get(t.project_id) for t in tasks}
    lead_names = dict(
        (await db.execute(
            select(Lead.id, Lead.name).where(
                Lead.id.in_({v for v in task_lead.values() if v} or {""}))
        )).all()
    )

    def _client(t: ActionItem) -> str:
        lead_id = task_lead.get(t.id)
        name = lead_names.get(lead_id) if lead_id else None
        if not name:
            return ""
        label = name.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")
        return f" · [{label}](yuvipep://lead/{lead_id})"

    greeting = _greeting_word(clock.now(tz).hour)
    lines = [f"# {greeting}, {_greeting_name(user.name)}", ""]
    if overdue:
        lines.append("**Overdue:**")
        lines += [
            f"- [{t.priority}] {t.title} (due {t.due_date:%d %b}){_client(t)}"
            for t in overdue
        ]
        lines.append("")
    if today:
        lines.append("**Due today:**")
        # F52: the `if t not in overdue` filter is gone. It was compensating for
        # two lists that overlapped; now that they partition, it could only ever
        # remove rows that belong here.
        lines += [f"- [{t.priority}] {t.title}{_client(t)}" for t in today]
        lines.append("")
    others = [t for t in tasks if t not in today and t not in overdue][:5]
    if others:
        lines.append("**Coming up:**")
        lines += [
            f"- [{t.priority}] {t.title}"
            + (f" (due {t.due_date:%d %b})" if t.due_date else "")
            + _client(t)
            for t in others
        ]
        lines.append("")
    if approvals:
        lines.append("**Approvals waiting on you:**")
        lines += [f"- {a.reason}" for a in approvals]
        lines.append("")
    if followups:
        lines.append("**Follow-ups due:**")
        lines += [
            f"- {lead.name} ({f.channel})"
            + (f" — {f.note}" if f.note else "")
            + (" — overdue" if f.due_date < today_local else "")
            for f, lead in followups
        ]
        lines.append("")
    if demos:
        lines.append("**Demos coming up:**")
        lines += [
            f"- {lead.name} on {d.scheduled_date:%d %b}"
            + (f" at {d.scheduled_time}" if d.scheduled_time else "")
            for d, lead in demos
        ]
        lines.append("")
    if overnight:
        lines.append("**Replies that came in:**")
        lines += [f"- {m.ai_summary or m.body[:100]}" for m in overnight]

    # An honest empty state rather than a heading over nothing (finding F3):
    # a card showing only the greeting reads as broken, not as calm.
    if not any((overdue, today, others, approvals, followups, demos, overnight)):
        lines.append("Nothing needs you right now — no tasks due, no "
                     "approvals waiting, no follow-ups or demos on the "
                     "calendar, and nothing came in overnight.")

    digest = Digest(
        org_id=org_id, kind=DigestKind.DAILY_USER.value, for_user_id=user.id,
        content_md="\n".join(lines), generated_at=now,
    )
    db.add(digest)
    await db.flush()
    return digest


# ─────────────────────────────────────────────────────────────────────────────
# Weekly reports (Workflow 17)
# ─────────────────────────────────────────────────────────────────────────────


async def build_weekly_client_report(
    db: AsyncSession, *, org_id: str, project: Project
) -> Digest | None:
    """Plain, honest, in the school's language — drafted, then approved by
    the sales lead. Returns None when nothing happened (a 'nothing happened'
    report hurts)."""
    now = utcnow()
    week_ago = now - timedelta(days=7)
    if project.status == ProjectStatus.ON_HOLD.value:
        return None
    events_week = (
        await db.execute(
            select(ProgressEvent).where(
                ProgressEvent.org_id == org_id,
                ProgressEvent.project_id == project.id,
                ProgressEvent.at >= week_ago,
                ProgressEvent.event_type.in_(
                    [EventType.TASK_DONE.value, EventType.DELIVERABLE_ADDED.value,
                     EventType.MESSAGE_SENT.value, EventType.DEMO_COMPLETED.value,
                     EventType.COMMITMENT_KEPT.value]
                ),
            )
        )
    ).scalars().all()
    if not events_week:
        return None

    done_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.completed_at >= week_ago,
                ActionItem.visible_to_client.is_(True),
            )
        )
    ).scalars().all()
    upcoming = (
        await db.execute(
            select(ActionItem)
            .where(
                ActionItem.project_id == project.id,
                ActionItem.status.in_(OPEN_STATUSES),
                ActionItem.visible_to_client.is_(True),
                ActionItem.due_date <= now + timedelta(days=7),
            )
            .order_by(ActionItem.due_date)
        )
    ).scalars().all()
    commitments = (
        await db.execute(
            select(ClientCommitment).where(
                ClientCommitment.project_id == project.id,
                ClientCommitment.status == CommitmentStatus.OPEN.value,
            )
        )
    ).scalars().all()

    lines = [f"# Weekly update — {project.name}", ""]
    if done_tasks:
        lines.append("**Done this week:**")
        lines += [f"- {t.title}" for t in done_tasks]
        lines.append("")
    if upcoming:
        lines.append("**Next week:**")
        lines += [
            f"- {t.title}" + (f" ({t.due_date:%a %d %b})" if t.due_date else "")
            for t in upcoming
        ]
        lines.append("")
    # Honesty rule: a bad week is reported with the recovery step, not hidden.
    if project.health != ProjectHealth.ON_TRACK.value:
        lines.append(
            f"**Status:** {project.health.replace('_', ' ')} — {project.health_reason}. "
            "Recovery is underway; dates below reflect it."
        )
    else:
        target = f" for {project.target_end_date:%d %b}" if project.target_end_date else ""
        lines.append(f"**Status:** on track{target}.")
    if commitments:
        lines.append("")
        lines.append("**Open promises we're tracking:**")
        lines += [f"- {c.text}" + (f" (by {c.due_date:%d %b})" if c.due_date else "") for c in commitments]

    digest = Digest(
        org_id=org_id, kind=DigestKind.WEEKLY_PROJECT_CLIENT.value,
        project_id=project.id, content_md="\n".join(lines), generated_at=now,
    )
    db.add(digest)
    await db.flush()

    # Draft the carrying message to every receives_progress_updates stakeholder.
    recipients = (
        await db.execute(
            select(Stakeholder).where(
                Stakeholder.project_id == project.id,
                Stakeholder.receives_progress_updates.is_(True),
                Stakeholder.do_not_contact.is_(False),
            )
        )
    ).scalars().all()
    if recipients:
        primary = recipients[0]
        contact = (
            await db.execute(select(Contact).where(Contact.id == primary.contact_id))
        ).scalar_one_or_none()
        cc = []
        for s in recipients[1:]:
            c = (
                await db.execute(select(Contact).where(Contact.id == s.contact_id))
            ).scalar_one_or_none()
            if c is not None and c.email:
                cc.append(c.email)
        if contact is not None:
            from app.engines import communication_engine

            message, _appr, _unc = await communication_engine.draft_client_message(
                db, org_id=org_id, kind=MessageKind.REPORT.value,
                purpose="weekly client progress report",
                lead_id=project.lead_id, contact=contact, project=project,
                stakeholder=primary,
                subject=f"{project.name} — weekly update",
                cc=cc,
                instruction="The weekly report below, warm and plain.",
                facts={"report": digest.content_md},
                triggered_by="weekly_report",
            )
            if message is not None:
                digest.sent_message_id = message.id
    return digest


async def build_weekly_internal(
    db: AsyncSession, *, org_id: str, project: Project
) -> Digest:
    now = utcnow()
    week_ago = now - timedelta(days=7)
    events_week = (
        await db.execute(
            select(ProgressEvent)
            .where(
                ProgressEvent.org_id == org_id,
                ProgressEvent.project_id == project.id,
                ProgressEvent.at >= week_ago,
            )
            .order_by(ProgressEvent.at)
        )
    ).scalars().all()
    lines = [
        f"# Team week in review — {project.name}",
        f"Health: {project.health}" + (f" ({project.health_reason})" if project.health_reason else ""),
        "",
    ]
    lines += [
        f"- {e.at:%a %H:%M} {e.event_type.replace('_', ' ')}"
        + (f": {e.details.get('summary') or e.details.get('reason') or ''}" if e.details else "")
        for e in events_week[:40]
    ]
    digest = Digest(
        org_id=org_id, kind=DigestKind.WEEKLY_PROJECT_INTERNAL.value,
        project_id=project.id, content_md="\n".join(lines), generated_at=now,
    )
    db.add(digest)
    await db.flush()
    return digest


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding brief (Workflow 15) — no human writes it
# ─────────────────────────────────────────────────────────────────────────────


async def project_brief(
    db: AsyncSession, *, org_id: str, project: Project
) -> dict:
    """Everything you would want if someone said "brief me on this project".

    Found live on 2026-08-06: asked *"tell me a brief about the project"*, the
    assistant fell back to semantic note search, found nothing, and asked the
    user what to look up. It was not being evasive — **no agent tool returned a
    project at all.** The eight query tools were lead-scoped or task-scoped, so
    the single most natural question in the product had no data behind it.

    Third instance of [F46]/[F57]'s pattern: a question the product invites, no
    tool exposing the answer, so the model reaches for the nearest thing. The
    fix is the same — a tool, not a prompt.

    Structured rather than prose on purpose: the model phrases it for the
    reader, and every number here is a fact from the database.
    """
    from app.engines.sync_engine import health_signals

    plan = (
        await db.execute(
            select(ActionPlan)
            .where(ActionPlan.project_id == project.id,
                   ActionPlan.status == "active")
        )
    ).scalars().first()

    tasks = (
        await db.execute(
            select(ActionItem).where(ActionItem.project_id == project.id)
        )
    ).scalars().all()
    by_status: dict[str, int] = {}
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1

    people = (
        await db.execute(
            select(Stakeholder, Contact)
            .join(Contact, Contact.id == Stakeholder.contact_id)
            .where(Stakeholder.project_id == project.id)
        )
    ).all()
    commitments = (
        await db.execute(
            select(ClientCommitment).where(
                ClientCommitment.project_id == project.id,
                ClientCommitment.status == CommitmentStatus.OPEN.value,
            )
        )
    ).scalars().all()

    _counts, reasons = await health_signals(db, org_id, project.id)
    next_due = sorted(
        (t for t in tasks if t.due_date and t.status in OPEN_STATUSES),
        key=lambda t: t.due_date,
    )[:5]

    return {
        "project": project.name,
        "status": project.status,
        "health": project.health,
        "why_that_health": reasons or ["nothing is wrong"],
        "objective": project.objective,
        "starts": project.start_date.date().isoformat() if project.start_date else None,
        "target_end": (
            project.target_end_date.date().isoformat()
            if project.target_end_date else None
        ),
        "value_estimate": project.value_estimate,
        "currency": project.currency,
        "current_plan_version": project.current_plan_version,
        "plan_summary": plan.summary if plan else None,
        "tasks_by_status": by_status,
        "client_people": [
            {"name": c.name, "role": s.role_at_client, "influence": s.influence,
             "gets_updates": bool(s.receives_progress_updates)}
            for s, c in people
        ],
        "open_promises": [
            {"text": c.text, "direction": c.direction,
             "due": c.due_date.date().isoformat() if c.due_date else None}
            for c in commitments
        ],
        "next_due": [
            {"title": t.title, "due": t.due_date.date().isoformat(),
             "priority": t.priority}
            for t in next_due
        ],
    }


async def onboarding_brief(
    db: AsyncSession, *, org_id: str, project: Project, user: User
) -> str:
    plan = (
        await db.execute(
            select(ActionPlan).where(
                ActionPlan.project_id == project.id,
                ActionPlan.status == "active",
            )
        )
    ).scalars().first()
    members = (
        await db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(
                ProjectMember.project_id == project.id,
                ProjectMember.left_at.is_(None),
            )
        )
    ).all()
    stakeholders = (
        await db.execute(
            select(Stakeholder, Contact)
            .join(Contact, Contact.id == Stakeholder.contact_id)
            .where(Stakeholder.project_id == project.id)
        )
    ).all()
    from app.models.user import UserSkill

    skills = (
        await db.execute(select(UserSkill.skill).where(UserSkill.user_id == user.id))
    ).scalars().all()
    open_in_skill = []
    if skills:
        open_in_skill = (
            await db.execute(
                select(ActionItem).where(
                    ActionItem.project_id == project.id,
                    ActionItem.status.in_(OPEN_STATUSES),
                    ActionItem.required_skill.in_(skills),
                )
            )
        ).scalars().all()
    upcoming = (
        await db.execute(
            select(ActionItem)
            .where(
                ActionItem.project_id == project.id,
                ActionItem.status.in_(OPEN_STATUSES),
                ActionItem.due_date.is_not(None),
            )
            .order_by(ActionItem.due_date)
        )
    ).scalars().all()

    lines = [
        f"# Welcome to {project.name}",
        "",
        f"**Objective:** {project.objective or '—'}",
        f"**Status:** {project.status}, health {project.health}",
        f"**Plan:** v{project.current_plan_version}"
        + (f" — {plan.summary}" if plan and plan.summary else ""),
        "",
        "**Your teammates:**",
    ]
    lines += [
        f"- {u.name} ({m.role_in_project or u.designation or u.role})"
        for m, u in members
    ]
    lines += ["", "**Client-side people:**"]
    lines += [
        f"- {c.name} — {s.role_at_client or c.title} ({s.influence or 'contact'})"
        for s, c in stakeholders
    ]
    if upcoming:
        lines += ["", "**Upcoming dates:**"]
        lines += [f"- {t.due_date:%d %b}: {t.title}" for t in upcoming[:6]]
    if open_in_skill:
        lines += ["", "**Open tasks in your skill area:**"]
        lines += [f"- {t.title}" for t in open_in_skill[:6]]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Questions the front door answers directly
# ─────────────────────────────────────────────────────────────────────────────


async def whats_blocking(db: AsyncSession, *, org_id: str, project: Project) -> str:
    blocked = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.blocked.is_(True),
                ActionItem.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    overdue = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.status.in_(OPEN_STATUSES),
                ActionItem.due_date < utcnow(),
            )
        )
    ).scalars().all()
    # F43: this used to consult ONLY blocked + overdue tasks, so it answered
    # "Nothing is blocking" while the entire plan sat frozen behind an unsigned
    # approval, and — with 4 open conflicts holding plan v5 — it listed 16
    # OVERDUE rows without once mentioning the conflicts. Silently empty, then
    # noisily wrong, on the two things that actually stop work.
    #
    # The good answer already existed elsewhere in this codebase: the ops lead's
    # Delivery card says "4 unresolved conflict(s) blocking a re-plan", computed
    # by sync_engine. That ranking is now shared rather than re-invented, so the
    # two surfaces cannot answer the same question differently again.
    from app.engines.sync_engine import health_signals

    _counts, reasons = await health_signals(db, org_id, project.id)

    # Pending approvals are deliberately NOT part of health_signals: a draft
    # awaiting sign-off is normal, and counting it would mark healthy projects
    # at_risk. But it is precisely what "what's blocking?" means to a human —
    # it is the thing standing between the plan and the work starting.
    pending = (
        await db.execute(
            select(Approval).where(
                Approval.org_id == org_id,
                Approval.project_id == project.id,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )
    ).scalars().all()

    if not blocked and not overdue and not reasons and not pending:
        return f"Nothing is blocking {project.name} — health is {project.health}."

    lines = []
    for a in pending:
        lines.append(
            f"- WAITING ON A DECISION: {a.reason or a.entity_type}"
            + (f" (with {a.stage})" if getattr(a, "stage", None) else "")
        )
    # The ranked summary — conflicts, broken commitments, open incidents — before
    # the per-task detail, because a held re-plan outranks any single late task.
    for reason in reasons:
        if "conflict" in reason or "commitment" in reason or "incident" in reason:
            lines.append(f"- {reason.upper()}")
    for t in blocked:
        lines.append(f"- BLOCKED: {t.title} — {t.blocked_reason}")
    for t in overdue:
        if t not in blocked:
            # NOTE: `overdue` above uses `due_date < utcnow()`, so a task due
            # TODAY is counted late. That is [F52]'s defect, not F43's, and it is
            # deliberately left alone here — F52's fix must not be applied to the
            # Sync Engine's ladder, where Workflow 10 defines overdue exactly
            # this way on purpose. Fix them together.
            lines.append(f"- OVERDUE: {t.title} (due {t.due_date:%d %b})")
    return f"Blocking {project.name}:\n" + "\n".join(lines)


async def why_trace(
    db: AsyncSession, *, org_id: str, entity_type: str, entity_id: str
) -> str:
    """'Why did the AI do that?' — inputs, decision, reason, confidence,
    overrides. Open to the whole organisation."""
    decisions = (
        await db.execute(
            select(AIDecision)
            .where(
                AIDecision.org_id == org_id,
                AIDecision.entity_type == entity_type,
                AIDecision.entity_id == entity_id,
            )
            .order_by(AIDecision.created_at)
        )
    ).scalars().all()
    if not decisions:
        return "No AI decision is recorded for this record."
    lines = []
    for d in decisions:
        lines.append(
            f"[{d.created_at:%d %b %H:%M}] {d.engine or ''} {d.decision_type}: "
            f"{d.decision} — {d.reason} (confidence {d.confidence:.2f})"
            + (f" — OVERRIDDEN: {d.human_override}" if d.human_override else "")
        )
    return "\n".join(lines)
