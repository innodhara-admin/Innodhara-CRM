"""Pulse, the sales head's home screen (spec 6.1).

* the org pulse (7.13): the mean of four 0-100 parts, and its change since
  the snapshot a week ago,
* four tiles: deals in play (with an 8-week line), wins expected this
  quarter, win rate over 90 days (7.2), median days to win (7.3),
* what needs the sales head's eyes (7.9), computed on every request,
* the team's week, Monday to Saturday,
* the month's AI spend.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, tzinfo
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadState
from app.insights import ai_usage, common, outlook, scoring, snapshots, team
from app.models.action_item import ActionItem
from app.models.comms import InboundMessage
from app.models.location import STATUS_DENIED, LocationPing
from app.models.project import ClientCommitment, Project
from app.models.proposal import Proposal

WIN_RATE_DAYS = 90
MIN_DECIDED = 5
DAYS_TO_WIN_WINDOW = 180
TREND_WEEKS = 8
MOVING_DAYS = 14
FOLLOW_THROUGH_DAYS = 30
ALERTS_SHOWN = 5
SEVERITY_ORDER = {"critical": 0, "serious": 1, "warning": 2}
QUIET_SCORE_BELOW = 30
QUIET_DAYS = 10
UNANSWERED_DAYS = 10
NEGATIVE_DAYS = 7
PROMISE_DAYS = 30
OVERDUE_COUNT = 3
REFUSED_STREAK = 3


def _whole(x: float) -> int:
    return int(math.floor(x + 0.5))


async def _tiles(db, org_id, tz, now, in_play_count) -> dict:
    today = common.local_day(now, tz)
    this_week = common.week_start(today)
    trend = []
    for i in range(TREND_WEEKS - 1, -1, -1):
        if i == 0:
            at = now
        else:
            at = common.day_bounds_utc(this_week - timedelta(weeks=i - 1), tz)[0]
        states = await common.states_as_of(db, org_id, at)
        trend.append(sum(1 for s in states.values() if s in common.IN_PLAY))
    in_play = common.block(
        "ok" if in_play_count or any(trend) else "empty",
        None if in_play_count or any(trend) else "No deals in play yet.",
        value=in_play_count, trend=trend)

    won, expected, low, high = await outlook.expected_wins(db, org_id, tz, now)
    wins = common.block("ok" if expected else "empty",
                        None if expected else "No wins expected yet.",
                        won=won, expected=expected, low=low, high=high)

    w, lost = await common.won_and_lost(db, org_id, now - timedelta(days=WIN_RATE_DAYS), now)
    decided = len(w) + len(lost)
    if decided >= MIN_DECIDED:
        win_rate = common.block(value=round(len(w) / decided, 2), won=len(w), decided=decided)
    else:
        win_rate = common.block("thin" if decided else "empty",
                                "Not enough decided deals yet.", value=None, won=len(w),
                                decided=decided)

    recent, _ = await common.won_and_lost(
        db, org_id, now - timedelta(days=DAYS_TO_WIN_WINDOW), now)
    past = await common.history(db, org_id)
    spans = []
    for lead_id, at in recent:
        for one_round in common.rounds(past.get(lead_id, [])):
            if not any(r.changed_at == at for r in one_round):
                continue
            opened = [r.changed_at for r in one_round
                      if r.to_state == LeadState.OPEN.value and r.changed_at <= at]
            if opened:
                spans.append((at - opened[0]).total_seconds() / 86400)
    days_to_win = (common.block(value=_whole(median(spans))) if spans else
                   common.block("empty", "No wins in the last six months yet.", value=None))
    tiles = {"in_play": in_play, "wins": wins, "win_rate": win_rate, "days_to_win": days_to_win}
    if all(t["status"] == "empty" for t in tiles.values()):
        return common.block("empty", "Nothing to show yet.", **tiles)
    return common.block(**tiles)


async def _pulse_parts(db, org_id, tz, now, deals, scores) -> dict[str, int | None]:
    parts: dict[str, int | None] = {}
    if deals:
        recent = await common.activity_by_lead(db, org_id, now - timedelta(days=MOVING_DAYS), now)
        parts["moving"] = _whole(100 * sum(1 for d in deals if recent.get(d.id)) / len(deals))
    else:
        parts["moving"] = None

    members = {u.id for u in await common.team_users(db, org_id)}
    since = now - timedelta(days=FOLLOW_THROUGH_DAYS)
    due = (await db.execute(
        select(ActionItem).where(ActionItem.org_id == org_id, ActionItem.due_date >= since,
                                 ActionItem.due_date <= now,
                                 ActionItem.status.not_in(("cancelled", "superseded",
                                                           "declined")))
    )).scalars().all()
    due = [t for t in due if t.assignee_id in members]
    on_time = sum(1 for t in due if t.completed_at is not None
                  and common.local_day(t.completed_at, tz) <= common.local_day(t.due_date, tz))
    parts["follow_through"] = _whole(100 * on_time / len(due)) if due else None

    parts["client_health"] = (_whole(100 * sum(1 for d in deals if scores[d.id].health == "healthy")
                                     / len(deals)) if deals else None)

    week = timedelta(days=7)
    acts = [a for a in await team.actions(db, org_id, now - 9 * week, now) if a[0] in members]
    this_week = sum(1 for a in acts if a[2] >= now - week)
    before = sum(1 for a in acts if a[2] < now - week) / 8
    if before:
        parts["activity"] = min(100, _whole(100 * this_week / before))
    else:
        parts["activity"] = 100 if this_week else None
    return parts


async def alerts(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime) -> list[dict]:
    """Everything that qualifies, most severe first, then oldest first."""
    found: list[tuple[str, datetime, dict]] = []

    def add(severity, kind, title, detail, subject_type, subject_id, since):
        found.append((severity, since, {
            "severity": severity, "kind": kind, "title": title, "detail": detail,
            "subject": {"type": subject_type, "id": subject_id}}))

    deals = await common.leads_in_states(db, org_id, common.IN_PLAY)
    scores = await scoring.score_deals(db, org_id, deals, now, tz=tz)
    by_id = {d.id: d for d in deals}
    for d in deals:
        s = scores[d.id]
        if s.value < QUIET_SCORE_BELOW and s.days_quiet >= QUIET_DAYS:
            add("critical", "deal_quiet", f"{d.name} has gone quiet",
                f"Deal score {s.value}, nothing recorded for {s.days_quiet} days.",
                "deal", d.id, s.last_activity or d.created_at)

    ids = list(by_id)
    if ids:
        sent = dict((await db.execute(
            select(Proposal.lead_id, func.max(Proposal.sent_at)).where(
                Proposal.org_id == org_id, Proposal.lead_id.in_(ids),
                Proposal.status.in_(scoring.SENT_STATES), Proposal.sent_at.is_not(None))
            .group_by(Proposal.lead_id))).all())
        for lead_id, at in sent.items():
            at = common.as_dt(at)
            keys = {f["key"] for f in scores[lead_id].factors}
            if "proposal_unanswered" in keys and now - at >= timedelta(days=UNANSWERED_DAYS):
                add("critical", "proposal_unanswered",
                    f"No reply to the proposal for {by_id[lead_id].name}",
                    f"Sent {common.days_between(at, now)} days ago, no reply since.",
                    "deal", lead_id, at)

        for lead_id, at in (await db.execute(
            select(InboundMessage.matched_lead_id,
                   func.max(func.coalesce(InboundMessage.received_at, InboundMessage.created_at)))
            .where(InboundMessage.org_id == org_id, InboundMessage.matched_lead_id.in_(ids),
                   InboundMessage.sentiment == "negative",
                   func.coalesce(InboundMessage.received_at, InboundMessage.created_at)
                   >= now - timedelta(days=NEGATIVE_DAYS))
            .group_by(InboundMessage.matched_lead_id))).all():
            at = common.as_dt(at)
            add("serious", "negative_reply", f"{by_id[lead_id].name} sent an unhappy reply",
                f"Received {common.days_between(at, now)} days ago.", "deal", lead_id, at)

        for lead_id, due in (await db.execute(
            select(Project.lead_id, func.min(ClientCommitment.due_date))
            .join(Project, Project.id == ClientCommitment.project_id)
            .where(ClientCommitment.org_id == org_id, Project.lead_id.in_(ids),
                   ClientCommitment.direction == "ours", ClientCommitment.status == "broken",
                   ClientCommitment.due_date >= now - timedelta(days=PROMISE_DAYS))
            .group_by(Project.lead_id))).all():
            due = common.as_dt(due)
            add("serious", "promise_broken", f"A promise to {by_id[lead_id].name} was broken",
                f"It was due on {common.local_day(due, tz).strftime('%d %b').lstrip('0')}.",
                "deal", lead_id, due)

    members = [u for u in await common.team_users(db, org_id) if u.is_active]
    open_tasks: dict[str, list] = defaultdict(list)
    for assignee, due in (await db.execute(
        select(ActionItem.assignee_id, ActionItem.due_date).where(
            ActionItem.org_id == org_id,
            ActionItem.status.in_(("open", "in_progress", "pending_review"))))).all():
        open_tasks[assignee].append(due)
    for u in members:
        mine = open_tasks.get(u.id, [])
        if u.max_open_tasks and len(mine) > u.max_open_tasks:
            add("warning", "over_capacity", f"{u.name} has more than they can carry",
                f"{len(mine)} open tasks, room for {u.max_open_tasks}.", "person", u.id, now)
        overdue = sorted(d for d in mine if d is not None and d < now)
        if len(overdue) >= OVERDUE_COUNT:
            add("warning", "overdue_tasks", f"{u.name} has {len(overdue)} overdue tasks",
                f"The oldest was due {common.days_between(overdue[0], now)} days ago.",
                "person", u.id, overdue[0])

    today = common.local_day(now, tz)
    start = common.day_bounds_utc(today - timedelta(days=13), tz)[0]
    refused: dict[str, set] = defaultdict(set)
    for user_id, at in (await db.execute(
        select(LocationPing.user_id, LocationPing.captured_at).where(
            LocationPing.org_id == org_id, LocationPing.status == STATUS_DENIED,
            LocationPing.captured_at >= start, LocationPing.captured_at <= now))).all():
        refused[user_id].add(common.local_day(at, tz))
    for u in members:
        days = refused.get(u.id)
        if not days:
            continue
        d = today if today in days else today - timedelta(days=1)
        streak = 0
        while d in days:
            streak += 1
            d -= timedelta(days=1)
        if streak >= REFUSED_STREAK:
            add("warning", "location_refused", f"{u.name} has location turned off",
                f"Location was refused {streak} days in a row.", "person", u.id,
                common.day_bounds_utc(d + timedelta(days=1), tz)[0])

    found.sort(key=lambda f: (SEVERITY_ORDER[f[0]], f[1]))
    return [item for _, _, item in found]


def _shown(found: list[dict]) -> list[dict]:
    """The slots on the card: the most urgent alert of each kind first, then the
    rest, so one kind cannot fill every slot (developer's call, 24 Oct). The
    chosen ones keep the order of `found`: most severe first, then oldest."""
    seen: set[str] = set()
    leaders, rest = [], []
    for i, a in enumerate(found):
        (rest if a["kind"] in seen else leaders).append(i)
        seen.add(a["kind"])
    return [found[i] for i in sorted((leaders + rest)[:ALERTS_SHOWN])]


async def _activity_week(db, org_id, tz, now) -> dict:
    monday = common.week_start(common.local_day(now, tz))
    start = common.day_bounds_utc(monday, tz)[0]
    members = {u.id for u in await common.team_users(db, org_id)}
    rows = {monday + timedelta(days=i): {"meetings": 0, "emails": 0, "followups": 0}
            for i in range(6)}
    for user, kind, at, _s in await team.actions(db, org_id, start, now):
        day = common.local_day(at, tz)
        if user in members and day in rows and kind in rows[day]:
            rows[day][kind] += 1
    days = [{"date": d.isoformat(), **counts} for d, counts in sorted(rows.items())]
    if not any(v for d in days for k, v in d.items() if k != "date"):
        return common.block("empty", "No meetings, emails or follow-ups this week yet.",
                            days=days)
    return common.block(days=days)


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime) -> dict:
    deals = await common.leads_in_states(db, org_id, common.IN_PLAY)
    scores = await scoring.score_deals(db, org_id, deals, now, tz=tz)
    parts = await _pulse_parts(db, org_id, tz, now, deals, scores)
    present = [v for v in parts.values() if v is not None]
    today = common.local_day(now, tz)
    if present:
        score = _whole(sum(present) / len(present))
        await snapshots.ensure_today(db, org_id, tz, now, pulse_score=score)
        before = await snapshots.pulse_on_or_before(db, org_id, today - timedelta(days=7))
        missing = [k.replace("_", " ") for k, v in parts.items() if v is None]
        pulse_block = common.block(
            "thin" if missing else "ok",
            f"No data yet for: {', '.join(missing)}." if missing else None,
            score=score, change=None if before is None else score - before, parts=parts)
    else:
        pulse_block = common.block("empty", "Nothing to measure yet.", score=0, change=None,
                                   parts={k: 0 for k in parts})

    found = await alerts(db, org_id, tz, now)
    alert_block = (common.block(items=_shown(found)) if found else
                   common.block("empty", "Nothing needs your eyes right now.", items=[]))
    totals = await ai_usage.month_totals(db, org_id, tz, now)
    return {
        "pulse": pulse_block,
        "tiles": await _tiles(db, org_id, tz, now, len(deals)),
        "alerts": alert_block,
        "activity_week": await _activity_week(db, org_id, tz, now),
        "ai": common.block("ok" if totals["spent_usd"] else "empty",
                           None if totals["spent_usd"] else "No AI use this month yet.",
                           **totals),
    }
