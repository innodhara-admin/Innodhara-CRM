"""What every sales head screen shares (23 Oct 2026).

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-23-sales-head-design.md
section 7. Everything here is a read; nothing asks the clock -- the router
passes `now` and the organisation's zone down (tests/test_one_clock_guard.py).

* windows in the organisation's own day,
* the union of everything that counts as activity on a deal (7.5),
* the lead states on any past date, replayed from lead_state_history (7.15),
* the opener and the closer of a deal (7.1b),
* wins and losses (7.1).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import LeadState, MeetingStatus, Role
from app.models.action_item import ActionItem
from app.models.audit import AuditLog
from app.models.comms import InboundMessage
from app.models.followup import FollowUp
from app.models.lead import ClientIntelligence, Contact, Lead, LeadStateHistory
from app.models.meeting import Meeting
from app.models.messaging import OutboundMessage
from app.models.project import Project
from app.models.user import User

STATE_LABELS: dict[str, str] = {
    LeadState.COLD_CALLING.value: "Cold calling",
    LeadState.OPEN.value: "Open",
    LeadState.ACTIVE.value: "Active",
    LeadState.COLD.value: "Cold",
    LeadState.EXECUTION_IN_PROGRESS.value: "Execution",
    LeadState.CLIENT_EXECUTION_IN_PROGRESS.value: "Client execution",
    LeadState.CLOSED.value: "Closed",
    LeadState.LOST_FOR_NOW.value: "Lost for now",
}

#: A deal still being worked (spec 7.1).
IN_PLAY = (LeadState.OPEN.value, LeadState.ACTIVE.value, LeadState.COLD.value)
#: The round is agreed the first time it reaches execution; `closed` is delivery.
WON_STATE = LeadState.EXECUTION_IN_PROGRESS.value
LOST_STATE = LeadState.LOST_FOR_NOW.value
#: The funnel, left to right.
STAGE_ORDER = (
    LeadState.COLD_CALLING.value, LeadState.OPEN.value, LeadState.ACTIVE.value,
    LeadState.EXECUTION_IN_PROGRESS.value, LeadState.CLIENT_EXECUTION_IN_PROGRESS.value,
    LeadState.CLOSED.value,
)
#: How far along the road each state is, for "did this move go forward".
#: Cold sits beside open: a deal that went quiet has not gone backwards.
STAGE_RANK: dict[str, int] = {
    LeadState.COLD_CALLING.value: 0, LeadState.OPEN.value: 1, LeadState.COLD.value: 1,
    LeadState.ACTIVE.value: 2, LeadState.EXECUTION_IN_PROGRESS.value: 3,
    LeadState.CLIENT_EXECUTION_IN_PROGRESS.value: 4, LeadState.CLOSED.value: 5,
}

STUCK_DAYS = 14
UNTOUCHED_DAYS = 10

#: The people on the team screens (spec 6). Operations is out of scope in v1.
TEAM_ROLES = (Role.SALES_AGENT.value, Role.SALES_LEAD.value,
              Role.RELATIONSHIP_MANAGER.value)

ROLE_LABELS: dict[str, str] = {
    Role.SALES_AGENT.value: "Sales agent",
    Role.SALES_LEAD.value: "Sales lead",
    Role.RELATIONSHIP_MANAGER.value: "Relationship manager",
    Role.SALES_HEAD.value: "Sales head",
    Role.ORG_ADMIN.value: "Org admin",
    Role.OPERATIONS_AGENT.value: "Operations agent",
    Role.OPERATIONS_LEAD.value: "Operations lead",
}

FORMER_COLLEAGUE = "Former colleague"

MEETING_TYPE_LABELS: dict[str, str] = {
    "first_visit": "First visit",
    "negotiation": "Negotiation",
    "kickoff": "Kickoff",
    "review": "Review",
    "closure": "Closure",
    "relationship": "Catch-up",
}



def held_meeting():
    """A recording, not a meeting booked for later (status `scheduled`)."""
    return Meeting.status != MeetingStatus.SCHEDULED.value


def block(status: str = "ok", note: str | None = None, **fields: Any) -> dict[str, Any]:
    """One screen block. Every block says whether it has enough to show
    (`ok`), too little to trust as a chart (`thin`), or nothing (`empty`),
    and a plain sentence when it is not `ok`."""
    return {"status": status, "note": note, **fields}


def is_forward(from_state: str | None, to_state: str) -> bool:
    if from_state is None or from_state not in STAGE_RANK or to_state not in STAGE_RANK:
        return False
    return STAGE_RANK[to_state] > STAGE_RANK[from_state]


# ── time ────────────────────────────────────────────────────────────────────

def local_day(instant: datetime, tz: tzinfo) -> date:
    return clock.local_date(instant, tz)


def day_bounds_utc(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start, end) of the organisation's `day`, as naive UTC instants."""
    return clock.start_of_day_utc(day, tz), clock.start_of_day_utc(day + timedelta(days=1), tz)


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


def month_bounds_utc(month: str, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start, end) of "YYYY-MM" in the organisation's zone, naive UTC."""
    year, mon = (int(part) for part in month.split("-"))
    first = date(year, mon, 1)
    nxt = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    return clock.start_of_day_utc(first, tz), clock.start_of_day_utc(nxt, tz)


def period_bounds_utc(kind: str, today: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start, end) of the calendar month, quarter or year holding `today`,
    in the organisation's zone, as naive UTC."""
    if kind == "year":
        first, nxt = date(today.year, 1, 1), date(today.year + 1, 1, 1)
    else:
        span = 3 if kind == "quarter" else 1
        start_month = (today.month - 1) // span * span + 1
        first = date(today.year, start_month, 1)
        end_month = start_month + span
        nxt = (date(today.year + 1, end_month - 12, 1) if end_month > 12
               else date(today.year, end_month, 1))
    return clock.start_of_day_utc(first, tz), clock.start_of_day_utc(nxt, tz)


def iso_utc(instant: datetime | None) -> str | None:
    """A stored naive-UTC instant as ISO with a Z."""
    if instant is None:
        return None
    return instant.replace(microsecond=0).isoformat() + "Z"


def to_local_hm(instant: datetime, tz: tzinfo) -> str:
    """"HH:MM" on the organisation's clock."""
    return clock.to_local(instant, tz).strftime("%H:%M")


def days_between(earlier: datetime, later: datetime) -> int:
    return max(0, int((later - earlier).total_seconds() // 86400))


# ── people ──────────────────────────────────────────────────────────────────

async def team_users(db: AsyncSession, org_id: str) -> list[User]:
    """Sales agents, sales leads and relationship managers, active or not
    (a person who has left still owns history)."""
    return list((await db.execute(
        select(User).where(User.org_id == org_id, User.role.in_(TEAM_ROLES))
        .order_by(User.name)
    )).scalars().all())


async def org_people(db: AsyncSession, org_id: str) -> dict[str, User]:
    """Everyone in the organisation, by id."""
    rows = (await db.execute(select(User).where(User.org_id == org_id))).scalars().all()
    return {u.id: u for u in rows}


def person_name(people: dict[str, User], user_id: str | None) -> str | None:
    """A name to show, or None when there is nobody. A user id that is no
    longer on file is still somebody: a former colleague."""
    if not user_id:
        return None
    user = people.get(user_id)
    return user.name if user is not None else FORMER_COLLEAGUE


# ── activity (spec 7.5) ─────────────────────────────────────────────────────

def _sources(org_id: str):
    """(model, lead column, time expression, extra conditions) for every
    kind of activity on a deal."""
    return (
        (LeadStateHistory, LeadStateHistory.lead_id, LeadStateHistory.changed_at,
         (LeadStateHistory.org_id == org_id, LeadStateHistory.from_state.is_not(None))),
        (Meeting, Meeting.lead_id, func.coalesce(Meeting.started_at, Meeting.created_at),
         (Meeting.org_id == org_id, held_meeting())),
        (OutboundMessage, OutboundMessage.lead_id, OutboundMessage.sent_at,
         (OutboundMessage.org_id == org_id, OutboundMessage.sent_at.is_not(None))),
        (FollowUp, FollowUp.lead_id, FollowUp.completed_at,
         (FollowUp.org_id == org_id, FollowUp.completed_at.is_not(None))),
        (ClientIntelligence, ClientIntelligence.lead_id, ClientIntelligence.created_at,
         (ClientIntelligence.org_id == org_id,)),
        (Contact, Contact.lead_id, Contact.created_at, (Contact.org_id == org_id,)),
        (ActionItem, ActionItem.lead_id, ActionItem.completed_at,
         (ActionItem.org_id == org_id, ActionItem.completed_at.is_not(None),
          ActionItem.lead_id.is_not(None))),
        (InboundMessage, InboundMessage.matched_lead_id,
         func.coalesce(InboundMessage.received_at, InboundMessage.created_at),
         (InboundMessage.org_id == org_id, InboundMessage.matched_lead_id.is_not(None))),
    )


async def activity_by_lead(db: AsyncSession, org_id: str, since: datetime,
                           until: datetime) -> dict[str, list[datetime]]:
    """Every activity instant per lead in [since, until), oldest first."""
    out: dict[str, list[datetime]] = defaultdict(list)
    for _model, lead_col, at, conds in _sources(org_id):
        rows = (await db.execute(
            select(lead_col, at).where(*conds, at >= since, at < until)
        )).all()
        for lead_id, when in rows:
            if lead_id and when is not None:
                out[lead_id].append(as_dt(when))
    for times in out.values():
        times.sort()
    return dict(out)


async def last_activity(db: AsyncSession, org_id: str, lead_ids: list[str],
                        until: datetime) -> dict[str, datetime | None]:
    """The latest activity at or before `until`, per lead (None if none)."""
    latest: dict[str, datetime | None] = {lead_id: None for lead_id in lead_ids}
    if not lead_ids:
        return latest
    for _model, lead_col, at, conds in _sources(org_id):
        rows = (await db.execute(
            select(lead_col, func.max(at)).where(*conds, at <= until, lead_col.in_(lead_ids))
            .group_by(lead_col)
        )).all()
        for lead_id, when in rows:
            if when is None:
                continue
            when = as_dt(when)
            if latest.get(lead_id) is None or when > latest[lead_id]:
                latest[lead_id] = when
    return latest


def as_dt(value) -> datetime:
    """SQLite hands back `func.max`/`coalesce` results as text."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# ── history (spec 7.15) ─────────────────────────────────────────────────────

async def history(db: AsyncSession, org_id: str) -> dict[str, list[LeadStateHistory]]:
    """Every lead's state history, oldest first."""
    rows = (await db.execute(
        select(LeadStateHistory).where(LeadStateHistory.org_id == org_id)
        .order_by(LeadStateHistory.changed_at, LeadStateHistory.id)
    )).scalars().all()
    out: dict[str, list[LeadStateHistory]] = defaultdict(list)
    for row in rows:
        out[row.lead_id].append(row)
    return dict(out)


async def states_as_of(db: AsyncSession, org_id: str, at: datetime) -> dict[str, str]:
    """Each lead's state at `at`, replayed from its history. A lead made
    after `at` is absent."""
    leads = (await db.execute(
        select(Lead.id, Lead.state, Lead.created_at).where(Lead.org_id == org_id)
    )).all()
    past = await history(db, org_id)
    out: dict[str, str] = {}
    for lead_id, current, created_at in leads:
        if created_at is not None and created_at > at:
            continue
        rows = past.get(lead_id, [])
        before = [r for r in rows if r.changed_at <= at]
        if before:
            out[lead_id] = before[-1].to_state
        elif rows:
            out[lead_id] = rows[0].from_state or rows[0].to_state
        else:
            out[lead_id] = current
    return out


@dataclass
class Visit:
    """One stay of one lead in one state."""
    lead_id: str
    state: str
    entered: datetime
    exited: datetime | None      # None: still there
    exit_to: str | None


def stage_visits(past: dict[str, list[LeadStateHistory]]) -> list[Visit]:
    out: list[Visit] = []
    for lead_id, rows in past.items():
        for i, row in enumerate(rows):
            nxt = rows[i + 1] if i + 1 < len(rows) else None
            out.append(Visit(lead_id, row.to_state, row.changed_at,
                             nxt.changed_at if nxt else None,
                             nxt.to_state if nxt else None))
    return out


def current_visit_start(rows: list[LeadStateHistory], fallback: datetime) -> datetime:
    """When the lead entered the state it is in now."""
    return rows[-1].changed_at if rows else fallback


def rounds(rows: list[LeadStateHistory]) -> list[list[LeadStateHistory]]:
    """A lead's history split into rounds of business: a new round starts
    when a closed or lost client is opened again."""
    out: list[list[LeadStateHistory]] = [[]]
    for row in rows:
        if (row.to_state == LeadState.OPEN.value
                and row.from_state in (LeadState.CLOSED.value, LOST_STATE) and out[-1]):
            out.append([])
        out[-1].append(row)
    return [r for r in out if r]


async def won_and_lost(db: AsyncSession, org_id: str, since: datetime, until: datetime
                       ) -> tuple[list[tuple[str, datetime]], list[tuple[str, datetime]]]:
    """Wins (first entry into execution, once per round) and losses (each
    entry into lost for now) in [since, until), oldest first."""
    wins: list[tuple[str, datetime]] = []
    losses: list[tuple[str, datetime]] = []
    for lead_id, rows in (await history(db, org_id)).items():
        for one_round in rounds(rows):
            won = next((r for r in one_round
                        if r.to_state == WON_STATE and r.from_state is not None), None)
            if won is not None and since <= won.changed_at < until:
                wins.append((lead_id, won.changed_at))
            for r in one_round:
                if r.to_state == LOST_STATE and r.from_state is not None \
                        and since <= r.changed_at < until:
                    losses.append((lead_id, r.changed_at))
    wins.sort(key=lambda w: w[1])
    losses.sort(key=lambda w: w[1])
    return wins, losses


# ── the people on a deal (spec 7.1b) ───────────────────────────────────────

async def deal_people(db: AsyncSession, org_id: str, leads: list[Lead]
                      ) -> dict[str, tuple[str | None, str | None]]:
    """(opener, closer) user ids per lead.

    Opener: the owner, when the owner is a sales agent -- opening never
    changes the owner. Closer: the project's sales owner; else the sales lead
    who created the lead; else the sales lead who held most of its meetings;
    else the owner when the owner is a sales lead; else nobody yet."""
    if not leads:
        return {}
    ids = [lead.id for lead in leads]
    roles = dict((await db.execute(
        select(User.id, User.role).where(User.org_id == org_id))).all())
    project_owner: dict[str, str] = {}
    for lead_id, owner_id in (await db.execute(
        select(Project.lead_id, Project.sales_owner_id)
        .where(Project.org_id == org_id, Project.lead_id.in_(ids),
               Project.sales_owner_id.is_not(None))
        .order_by(Project.created_at)
    )).all():
        project_owner[lead_id] = owner_id      # the newest project wins
    creator = dict((await db.execute(
        select(AuditLog.entity_id, AuditLog.user_id).where(
            AuditLog.org_id == org_id, AuditLog.action == "lead.created",
            AuditLog.entity_id.in_(ids))
    )).all())
    held: dict[str, Counter] = defaultdict(Counter)
    for lead_id, agent_id in (await db.execute(
        select(Meeting.lead_id, Meeting.agent_id)
        .where(Meeting.org_id == org_id, Meeting.lead_id.in_(ids), held_meeting())
    )).all():
        if roles.get(agent_id) == Role.SALES_LEAD.value:
            held[lead_id][agent_id] += 1

    out: dict[str, tuple[str | None, str | None]] = {}
    for lead in leads:
        owner_role = roles.get(lead.owner_id)
        opener = lead.owner_id if owner_role == Role.SALES_AGENT.value else None
        closer = project_owner.get(lead.id)
        if closer is None and roles.get(creator.get(lead.id)) == Role.SALES_LEAD.value:
            closer = creator[lead.id]
        if closer is None and held.get(lead.id):
            closer = held[lead.id].most_common(1)[0][0]
        if closer is None and owner_role == Role.SALES_LEAD.value:
            closer = lead.owner_id
        out[lead.id] = (opener, closer)
    return out


async def leads_in_states(db: AsyncSession, org_id: str, states) -> list[Lead]:
    return list((await db.execute(
        select(Lead).where(Lead.org_id == org_id, Lead.state.in_(list(states)))
        .order_by(Lead.name)
    )).scalars().all())
