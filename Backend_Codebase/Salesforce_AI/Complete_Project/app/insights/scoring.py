"""The deal score: 0-100, made of named rules, every point explained
(spec 7.7), and the client health it gives (7.8).

Start at 50, add every factor that fires, clamp to 0..100. Only the factors
that fired are returned, each with its points, so the sales head reads the
"why" beside the number. One query per factor for all the deals at once.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import Influence, LeadState
from app.insights import common
from app.models.comms import InboundMessage, Thread
from app.models.demo import Demo
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.meeting import Meeting
from app.models.project import ClientCommitment, Project, Stakeholder
from app.models.proposal import Proposal

START = 50

WEIGHTS: dict[str, int] = {
    "quiet_0_3": 10,
    "quiet_8_14": -8,
    "quiet_15_plus": -18,
    "stage_active": 8,
    "stage_cold": -12,
    "meetings": 5,              # each, at most MAX_MEETINGS
    "demo_done": 6,
    "proposal_sent": 6,
    "proposal_unanswered": -12,
    "decision_maker_unmet": -12,
    "negative_reply": -10,
    "promise_broken": -8,       # each, at most MAX_PROMISES
    "followup_overdue": -6,
    "important": 4,
}

FACTOR_LABELS: dict[str, str] = {
    "quiet_0_3": "In touch in the last 3 days",
    "quiet_8_14": "Quiet for 8 to 14 days",
    "quiet_15_plus": "Quiet for 15 days or more",
    "stage_active": "Active stage",
    "stage_cold": "Gone cold",
    "meetings": "Meetings held this round",
    "demo_done": "Demo done",
    "proposal_sent": "Proposal sent",
    "proposal_unanswered": "No reply to the proposal for 7 days or more",
    "decision_maker_unmet": "Decision maker never met",
    "negative_reply": "Unhappy reply in the last 30 days",
    "promise_broken": "A promise of ours was broken",
    "followup_overdue": "Follow-up overdue",
    "important": "Marked important",
}

MAX_MEETINGS = 3
MAX_PROMISES = 2
UNANSWERED_DAYS = 7
NEGATIVE_DAYS = 30
SENT_STATES = ("sent", "accepted")

HEALTHY_FROM = 60
WATCH_FROM = 40


@dataclass
class Score:
    value: int
    health: str
    factors: list[dict] = field(default_factory=list)
    days_quiet: int = 0
    last_activity: datetime | None = None


def health_of(value: int) -> str:
    if value >= HEALTHY_FROM:
        return "healthy"
    if value >= WATCH_FROM:
        return "watch"
    return "at_risk"


def _quiet_key(days: int) -> str | None:
    if days <= 3:
        return "quiet_0_3"
    if days <= 7:
        return None
    if days <= 14:
        return "quiet_8_14"
    return "quiet_15_plus"


def _round_start(rows) -> datetime | None:
    """When the lead's current round of business began."""
    rounds = common.rounds(rows)
    return rounds[-1][0].changed_at if rounds else None


async def score_deals(db: AsyncSession, org_id: str, leads: list[Lead], now: datetime,
                      *, tz: tzinfo | None = None) -> dict[str, Score]:
    if not leads:
        return {}
    tz = tz or clock.zone(None)
    ids = [lead.id for lead in leads]
    today = common.local_day(now, tz)

    last = await common.last_activity(db, org_id, ids, now)
    past = await common.history(db, org_id)

    meetings: dict[str, list[tuple[datetime, list[str]]]] = defaultdict(list)
    for lead_id, started, created, attendees in (await db.execute(
        select(Meeting.lead_id, Meeting.started_at, Meeting.created_at,
               Meeting.attendee_stakeholder_ids)
        .where(Meeting.org_id == org_id, Meeting.lead_id.in_(ids), common.held_meeting())
    )).all():
        meetings[lead_id].append((started or created, list(attendees or [])))

    demo_done = set((await db.execute(
        select(Demo.lead_id).where(Demo.org_id == org_id, Demo.lead_id.in_(ids),
                                   Demo.status == "completed")
    )).scalars().all())

    latest_sent: dict[str, datetime] = {}
    for lead_id, sent_at in (await db.execute(
        select(Proposal.lead_id, func.max(Proposal.sent_at))
        .where(Proposal.org_id == org_id, Proposal.lead_id.in_(ids),
               Proposal.status.in_(SENT_STATES), Proposal.sent_at.is_not(None))
        .group_by(Proposal.lead_id)
    )).all():
        latest_sent[lead_id] = common.as_dt(sent_at)

    inbound: dict[str, list[tuple[datetime, str | None]]] = defaultdict(list)
    for lead_id, received, created, sentiment in (await db.execute(
        select(InboundMessage.matched_lead_id, InboundMessage.received_at,
               InboundMessage.created_at, InboundMessage.sentiment)
        .where(InboundMessage.org_id == org_id, InboundMessage.matched_lead_id.in_(ids))
    )).all():
        inbound[lead_id].append((received or created, sentiment))

    last_thread: dict[str, tuple[datetime | None, str | None]] = {}
    for lead_id, at, direction in (await db.execute(
        select(Thread.lead_id, Thread.last_message_at, Thread.last_direction)
        .where(Thread.org_id == org_id, Thread.lead_id.in_(ids))
        .order_by(Thread.last_message_at)
    )).all():
        last_thread[lead_id] = (at, direction)     # the newest thread wins

    project_lead = dict((await db.execute(
        select(Project.id, Project.lead_id)
        .where(Project.org_id == org_id, Project.lead_id.in_(ids))
    )).all())
    deciders: dict[str, set[str]] = defaultdict(set)
    broken: dict[str, int] = defaultdict(int)
    if project_lead:
        for project_id, stakeholder_id in (await db.execute(
            select(Stakeholder.project_id, Stakeholder.id)
            .where(Stakeholder.org_id == org_id,
                   Stakeholder.project_id.in_(list(project_lead)),
                   Stakeholder.influence == Influence.DECISION_MAKER.value)
        )).all():
            deciders[project_lead[project_id]].add(stakeholder_id)
        for project_id, in (await db.execute(
            select(ClientCommitment.project_id)
            .where(ClientCommitment.org_id == org_id,
                   ClientCommitment.project_id.in_(list(project_lead)),
                   ClientCommitment.direction == "ours",
                   ClientCommitment.status == "broken")
        )).all():
            broken[project_lead[project_id]] += 1

    overdue = set((await db.execute(
        select(FollowUp.lead_id).where(
            FollowUp.org_id == org_id, FollowUp.lead_id.in_(ids),
            FollowUp.status == "pending", FollowUp.due_date < today)
    )).scalars().all())

    out: dict[str, Score] = {}
    for lead in leads:
        fired: list[tuple[str, int, str]] = []

        def fire(key: str, points: int | None = None, label: str | None = None) -> None:
            fired.append((key, WEIGHTS[key] if points is None else points,
                          label or FACTOR_LABELS[key]))

        touched = last.get(lead.id)
        days_quiet = common.days_between(touched or lead.created_at, now)
        key = _quiet_key(days_quiet)
        if key:
            fire(key)

        if lead.state == LeadState.ACTIVE.value:
            fire("stage_active")
        elif lead.state == LeadState.COLD.value:
            fire("stage_cold")

        since = _round_start(past.get(lead.id, [])) or lead.created_at
        held = [m for m in meetings.get(lead.id, []) if m[0] is not None and m[0] >= since]
        if held:
            n = min(len(held), MAX_MEETINGS)
            fire("meetings", WEIGHTS["meetings"] * n,
                 f"{n} meeting{'s' if n != 1 else ''} held this round")

        if lead.id in demo_done:
            fire("demo_done")

        sent = latest_sent.get(lead.id)
        if sent is not None:
            fire("proposal_sent")
            if now - sent >= timedelta(days=UNANSWERED_DAYS):
                replied = any(at is not None and at >= sent for at, _ in inbound.get(lead.id, []))
                thread_at, direction = last_thread.get(lead.id, (None, None))
                if direction == "inbound" and thread_at is not None and thread_at >= sent:
                    replied = True
                if not replied:
                    fire("proposal_unanswered")

        wanted = deciders.get(lead.id)
        if wanted:
            seen = {s for _, attendees in meetings.get(lead.id, []) for s in attendees}
            if not wanted & seen:
                fire("decision_maker_unmet")

        if any(sentiment == "negative" and at is not None
               and now - at <= timedelta(days=NEGATIVE_DAYS)
               for at, sentiment in inbound.get(lead.id, [])):
            fire("negative_reply")

        if broken.get(lead.id):
            n = min(broken[lead.id], MAX_PROMISES)
            fire("promise_broken", WEIGHTS["promise_broken"] * n,
                 FACTOR_LABELS["promise_broken"] if n == 1
                 else f"{n} promises of ours were broken")

        if lead.id in overdue:
            fire("followup_overdue")

        if lead.is_important:
            fire("important")

        value = max(0, min(100, START + sum(points for _, points, _ in fired)))
        out[lead.id] = Score(
            value=value, health=health_of(value),
            factors=[{"key": k, "label": label, "points": p} for k, p, label in fired],
            days_quiet=days_quiet, last_activity=touched,
        )
    return out
