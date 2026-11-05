"""Team screen (spec 6.4, 7.16): who did what, who was seen on the field
today, how full each plate is, and when the team works."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, tzinfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ActionItemStatus, Role
from app.insights import common
from app.models.action_item import ActionItem
from app.models.assistant import AssistantTurn
from app.models.followup import FollowUp
from app.models.lead import ClientIntelligence, Contact
from app.models.location import STATUS_OK, LocationPing
from app.models.meeting import Meeting
from app.models.messaging import OutboundMessage

METRICS = ("meetings", "emails", "followups", "tasks_done")
COUNT_KEYS = ("meetings", "emails", "followups", "tasks_done", "notes", "contacts", "jarvis")
TRACKED_ROLES = (Role.SALES_AGENT.value, Role.SALES_LEAD.value)
OPEN_STATUSES = (ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value)
HEAT_WEEKS = 6
HEAT_DAYS = 6           # Monday to Saturday


async def actions(db: AsyncSession, org_id: str, since: datetime, until: datetime
                  ) -> list[tuple[str, str, datetime, str | None]]:
    """(user_id, kind, at, session) for every counted action in [since, until)
    (spec 7.16). `session` is set only for Jarvis turns."""
    def window(col):
        return (col >= since, col < until)

    out: list[tuple[str, str, datetime, str | None]] = []
    met_at = func.coalesce(Meeting.started_at, Meeting.created_at)
    for user, at in (await db.execute(
        select(Meeting.agent_id, met_at).where(Meeting.org_id == org_id, common.held_meeting(),
                                             *window(met_at))
    )).all():
        out.append((user, "meetings", common.as_dt(at), None))
    for kind, model, user_col, at_col, extra in (
        ("emails", OutboundMessage, OutboundMessage.sender_user_id, OutboundMessage.sent_at,
         (OutboundMessage.sent_at.is_not(None),)),
        ("followups", FollowUp, FollowUp.owner_id, FollowUp.completed_at,
         (FollowUp.completed_at.is_not(None),)),
        ("tasks_done", ActionItem, ActionItem.assignee_id, ActionItem.completed_at,
         (ActionItem.completed_at.is_not(None),)),
        ("notes", ClientIntelligence, ClientIntelligence.added_by, ClientIntelligence.created_at,
         ()),
        ("contacts", Contact, Contact.created_by, Contact.created_at, ()),
    ):
        for user, at in (await db.execute(
            select(user_col, at_col).where(model.org_id == org_id, *extra, *window(at_col))
        )).all():
            out.append((user, kind, at, None))
    for user, at, session in (await db.execute(
        select(AssistantTurn.user_id, AssistantTurn.created_at, AssistantTurn.session_id)
        .where(AssistantTurn.org_id == org_id, *window(AssistantTurn.created_at))
    )).all():
        out.append((user, "jarvis", at, session))
    return [a for a in out if a[0]]


async def counts_by_person(db: AsyncSession, org_id: str, since: datetime, until: datetime
                           ) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {k: 0 for k in COUNT_KEYS})
    sessions: dict[str, set[str]] = defaultdict(set)
    for user, kind, _at, session in await actions(db, org_id, since, until):
        if kind == "jarvis":
            sessions[user].add(session)
            counts[user]          # make sure the person has a row
        else:
            counts[user][kind] += 1
    for user, ids in sessions.items():
        counts[user]["jarvis"] = len(ids)
    return {user: dict(c) for user, c in counts.items()}


def window_start(now: datetime, tz: tzinfo, days: int) -> datetime:
    """The start of the org day `days - 1` days before today: "the last 7
    days" means today and the six before it."""
    today = common.local_day(now, tz)
    return common.day_bounds_utc(today - timedelta(days=days - 1), tz)[0]


def levels(counts: list[int]) -> list[int]:
    """0 for an empty day, 1..4 by where a busy day sits among the busy days."""
    busy = sorted(c for c in counts if c > 0)
    out = []
    for c in counts:
        if c <= 0:
            out.append(0)
            continue
        share = sum(1 for b in busy if b <= c) / len(busy)
        out.append(max(1, min(4, math.ceil(share * 4))))
    return out


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime,
                metric: str = "meetings", days: int = 7) -> dict:
    members = await common.team_users(db, org_id)
    since = window_start(now, tz, days)
    counts = await counts_by_person(db, org_id, since, now)
    zero = {k: 0 for k in COUNT_KEYS}

    rows = []
    for user in members:
        c = counts.get(user.id, zero)
        if not user.is_active and not any(c.values()):
            continue
        rows.append({"user_id": user.id, "name": user.name, "role": user.role,
                     "value": c[metric], "meetings": c["meetings"], "emails": c["emails"],
                     "followups": c["followups"], "tasks_done": c["tasks_done"]})
    rows.sort(key=lambda r: (-r["value"], r["name"]))
    people = (common.block(metric=metric, items=rows) if rows else
              common.block("empty", "No sales team members yet.", metric=metric, items=[]))

    return {
        "people": people,
        "field_card": await _field_card(db, org_id, tz, now, members),
        "workload": await _workload(db, org_id, members),
        "heatmap": await _heatmap(db, org_id, tz, now, {u.id for u in members}),
    }


async def _field_card(db, org_id, tz, now, members) -> dict:
    tracked = [u for u in members if u.is_active and u.role in TRACKED_ROLES]
    if not tracked:
        return common.block("empty", "Nobody on the team sends field readings.",
                            seen_today=0, team_size=0, location_off=[])
    start, _ = common.day_bounds_utc(common.local_day(now, tz), tz)
    statuses: dict[str, set[str]] = defaultdict(set)
    for user, status in (await db.execute(
        select(LocationPing.user_id, LocationPing.status).where(
            LocationPing.org_id == org_id, LocationPing.captured_at >= start,
            LocationPing.captured_at <= now)
    )).all():
        statuses[user].add(status)
    seen = [u for u in tracked if STATUS_OK in statuses.get(u.id, set())]
    off = [u.name for u in tracked if statuses.get(u.id) and STATUS_OK not in statuses[u.id]]
    return common.block(seen_today=len(seen), team_size=len(tracked), location_off=sorted(off))


async def _workload(db, org_id, members) -> dict:
    active = [u for u in members if u.is_active]
    if not active:
        return common.block("empty", "No sales team members yet.", items=[])
    open_counts = dict((await db.execute(
        select(ActionItem.assignee_id, func.count()).where(
            ActionItem.org_id == org_id, ActionItem.status.in_(OPEN_STATUSES))
        .group_by(ActionItem.assignee_id)
    )).all())
    items = [{"user_id": u.id, "name": u.name, "open": int(open_counts.get(u.id, 0)),
              "capacity": int(u.max_open_tasks or 0)} for u in active]
    items.sort(key=lambda i: (-(i["open"] / i["capacity"] if i["capacity"] else i["open"]),
                              i["name"]))
    return common.block(items=items)


async def _heatmap(db, org_id, tz, now, member_ids: set[str]) -> dict:
    today = common.local_day(now, tz)
    first = common.week_start(today) - timedelta(weeks=HEAT_WEEKS - 1)
    start = common.day_bounds_utc(first, tz)[0]
    per_day: dict = defaultdict(int)
    seen_sessions: set[tuple] = set()
    for user, kind, at, session in await actions(db, org_id, start, now):
        if user not in member_ids:
            continue
        day = common.local_day(at, tz)
        if kind == "jarvis":
            key = (user, session, day)
            if key in seen_sessions:
                continue
            seen_sessions.add(key)
        per_day[day] += 1
    days = [first + timedelta(weeks=w, days=d) for w in range(HEAT_WEEKS) for d in range(HEAT_DAYS)]
    counts = [per_day.get(d, 0) for d in days]
    lv = levels(counts)
    weeks = []
    for w in range(HEAT_WEEKS):
        cells = [{"date": days[w * HEAT_DAYS + d].isoformat(),
                  "count": counts[w * HEAT_DAYS + d], "level": lv[w * HEAT_DAYS + d]}
                 for d in range(HEAT_DAYS)]
        weeks.append({"week_start": days[w * HEAT_DAYS].isoformat(), "days": cells})
    if not any(counts):
        return common.block("empty", "No recorded work in the last six weeks.", weeks=weeks)
    return common.block(weeks=weeks)
