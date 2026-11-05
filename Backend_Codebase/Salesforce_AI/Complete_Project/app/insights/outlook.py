"""Outlook (spec 6.3, 7.6): how many wins to expect this quarter.

Not a trained forecast -- stage history. For each deal in play:

    p(win) = the rate at which deals in its stage went on to win, smoothed
             toward a starting estimate while history is small,
             x (0.5 + score / 100), at most 0.95.

Expected wins = won so far this quarter + the sum of p. The likely range is
the 80% interval of that sum (a normal approximation of a Poisson-binomial),
never below what is already won. The month a deal is expected in is today
plus the median days its stage has taken to reach a win (a starting
estimate while there are fewer than five).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadState
from app.insights import common, scoring
from app.models.lead import Lead

PRIOR_P = {"open": 0.25, "active": 0.45, "cold": 0.10}
PRIOR_STRENGTH = 10
PRIOR_DAYS = {"open": 45, "active": 25, "cold": 60}
MIN_SAMPLES = 5
P_CAP = 0.95
LEAD_FLOW_PRIOR = 0.35
LEAD_FLOW_DAYS = 30
Z80 = 1.2816
MIN_DECIDED = 5
MONTHS_SHOWN = 6

METHOD_NOTE = (
    "Worked out from how deals in each stage have moved before, nudged by each "
    "deal's score. While there is little history it leans on starting estimates. "
    "An AI forecast comes later."
)


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _add_month(month: str) -> str:
    year, mon = (int(x) for x in month.split("-"))
    return f"{year + 1:04d}-01" if mon == 12 else f"{year:04d}-{mon + 1:02d}"


async def _learn(db: AsyncSession, org_id: str):
    """From history: per in-play stage, the visits whose outcome is known,
    the wins among them and the days to win; the number of decided rounds.

    An outcome is known when the round was later won or lost -- or when it is
    sitting in `cold` now: deals rarely say no, they go quiet, and a rate
    that only heard from the deals decided out loud would run high."""
    exits: dict[str, int] = defaultdict(int)
    wins: dict[str, int] = defaultdict(int)
    days_to_win: dict[str, list[float]] = defaultdict(list)
    decided = 0
    past = await common.history(db, org_id)
    now_cold = set((await db.execute(
        select(Lead.id).where(Lead.org_id == org_id, Lead.state == LeadState.COLD.value)
    )).scalars().all())
    for lead_id, rows in past.items():
        all_rounds = common.rounds(rows)
        for n, one_round in enumerate(all_rounds):
            went_cold = (one_round[-1].changed_at
                         if n == len(all_rounds) - 1 and lead_id in now_cold
                         and one_round[-1].to_state == LeadState.COLD.value else None)
            won = next((r for r in one_round
                        if r.to_state == common.WON_STATE and r.from_state is not None), None)
            losses = [r.changed_at for r in one_round
                      if r.to_state == common.LOST_STATE and r.from_state is not None]
            if won is not None or losses:
                decided += 1
            for i, row in enumerate(one_round[:-1]):
                stage = row.to_state
                if stage not in PRIOR_P:
                    continue
                entered = row.changed_at
                if won is not None and won.changed_at > entered:
                    exits[stage] += 1
                    wins[stage] += 1
                    days_to_win[stage].append((won.changed_at - entered).total_seconds() / 86400)
                elif any(at > entered for at in losses):
                    exits[stage] += 1
                elif went_cold is not None and stage != LeadState.COLD.value                         and went_cold > entered:
                    exits[stage] += 1
    return exits, wins, days_to_win, decided, past


def _rate(stage: str, exits, wins) -> float:
    return ((wins.get(stage, 0) + PRIOR_P[stage] * PRIOR_STRENGTH)
            / (exits.get(stage, 0) + PRIOR_STRENGTH))


def _stage_days(stage: str, days_to_win) -> float:
    samples = days_to_win.get(stage, [])
    return median(samples) if len(samples) >= MIN_SAMPLES else PRIOR_DAYS[stage]


def _interval(won: int, ps: list[float]) -> tuple[int, int, int]:
    total = sum(ps)
    sd = math.sqrt(sum(p * (1 - p) for p in ps))
    expected = won + round(total)
    low = max(won, round(won + total - Z80 * sd))
    high = max(expected, round(won + total + Z80 * sd))
    return expected, low, high


async def _deal_odds(db, org_id, tz, now):
    exits, wins, days_to_win, decided, past = await _learn(db, org_id)
    leads = await common.leads_in_states(db, org_id, common.IN_PLAY)
    scores = await scoring.score_deals(db, org_id, leads, now, tz=tz)
    today = common.local_day(now, tz)
    odds = []
    for lead in leads:
        score = scores[lead.id].value
        p = min(P_CAP, _rate(lead.state, exits, wins) * (0.5 + score / 100))
        when = today + timedelta(days=round(_stage_days(lead.state, days_to_win)))
        odds.append({"lead": lead, "p": round(p, 3), "score": score, "month": _month(when)})
    return odds, decided, past


def _quarter_last_month(now: datetime, tz: tzinfo) -> str:
    _, end = common.period_bounds_utc("quarter", common.local_day(now, tz), tz)
    return _month(common.local_day(end - timedelta(seconds=1), tz))


def _in_quarter(odds: list[dict], now: datetime, tz: tzinfo) -> list[dict]:
    """The deals expected by the end of this quarter. A deal the screen places
    in a later month is not a win expected this quarter, so the headline and
    the quarter's month bars always agree."""
    last = _quarter_last_month(now, tz)
    return [o for o in odds if o["month"] <= last]


async def expected_wins(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime
                        ) -> tuple[int, int, int, int]:
    """(won so far this quarter, expected, low, high)."""
    start, _ = common.period_bounds_utc("quarter", common.local_day(now, tz), tz)
    won_list, _ = await common.won_and_lost(db, org_id, start, now)
    odds, _, _ = await _deal_odds(db, org_id, tz, now)
    won = len(won_list)
    return (won, *_interval(won, [o["p"] for o in _in_quarter(odds, now, tz)]))


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime) -> dict:
    today = common.local_day(now, tz)
    q_start, q_end = common.period_bounds_utc("quarter", today, tz)
    won_list, _ = await common.won_and_lost(db, org_id, q_start, now)
    won = len(won_list)
    odds, decided, past = await _deal_odds(db, org_id, tz, now)
    this_quarter = _in_quarter(odds, now, tz)
    expected, low, high = _interval(won, [o["p"] for o in this_quarter])
    near_certain = sum(1 for o in this_quarter if o["score"] >= 80)
    likely = max(0, expected - won - near_certain)

    if not odds and not won:
        summary_status, summary_note = "empty", "No deals in play and no wins yet this quarter."
    elif decided < MIN_DECIDED:
        summary_status = "thin"
        summary_note = "Few deals have been decided yet, so this leans on starting estimates."
    else:
        summary_status, summary_note = "ok", None
    summary = common.block(summary_status, summary_note, won=won, expected=expected,
                           low=low, high=high, near_certain=near_certain, likely=likely)

    # Week by week over the quarter: wins so far, flat after today.
    first_day = common.local_day(q_start, tz)
    last_day = common.local_day(q_end - timedelta(seconds=1), tz)
    weeks, cursor = [], common.week_start(first_day)
    win_days = [common.local_day(at, tz) for _, at in won_list]
    today_index = 0
    while cursor <= last_day:
        week_end = cursor + timedelta(days=7)
        if cursor <= today < week_end:
            today_index = len(weeks)
        weeks.append({"week_start": cursor.isoformat(),
                      "won_cum": sum(1 for d in win_days if d < week_end)})
        cursor = week_end
    cumulative = common.block(
        summary_status, summary_note, weeks=weeks, today_index=today_index,
        expected_end=expected, low_end=low, high_end=high)

    # By month: the quarter's months, then any later month a deal is expected in.
    months_order = [_month(first_day)]
    while len(months_order) < 3:
        months_order.append(_add_month(months_order[-1]))
    for o in sorted(odds, key=lambda o: o["month"]):
        while o["month"] > months_order[-1] and len(months_order) < MONTHS_SHOWN:
            months_order.append(_add_month(months_order[-1]))
    by_month = {m: {"month": m, "won": 0, "expected": 0, "deals": []} for m in months_order}
    for d in win_days:
        if _month(d) in by_month:
            by_month[_month(d)]["won"] += 1
    sums: dict[str, float] = defaultdict(float)
    for o in odds:
        month = o["month"] if o["month"] in by_month else months_order[-1]
        sums[month] += o["p"]
        by_month[month]["deals"].append({"lead_id": o["lead"].id, "name": o["lead"].name,
                                         "p": o["p"], "score": o["score"]})
    for month, item in by_month.items():
        item["expected"] = item["won"] + round(sums[month])
        item["deals"].sort(key=lambda d: (-d["p"], d["name"]))
    months = common.block(summary_status, summary_note, items=list(by_month.values()))

    lead_flow = await _lead_flow(db, org_id, tz, now, past)
    by_person = await _by_person(db, org_id, odds, won_list)
    return {"summary": summary, "cumulative": cumulative, "months": months,
            "lead_flow": lead_flow, "by_person": by_person, "method_note": METHOD_NOTE}


async def _lead_flow(db, org_id, tz, now, past) -> dict:
    """New leads opening in the next 30 days, from today's cold-calling list."""
    window = timedelta(days=LEAD_FLOW_DAYS)
    tried = opened = 0
    opens_by_month: dict[str, int] = defaultdict(int)
    for visit in common.stage_visits(past):
        if visit.state != LeadState.COLD_CALLING.value:
            continue
        if visit.exit_to == LeadState.OPEN.value and visit.exited is not None:
            opens_by_month[_month(common.local_day(visit.exited, tz))] += 1
        if visit.entered <= now - window:
            tried += 1
            if (visit.exit_to == LeadState.OPEN.value and visit.exited is not None
                    and visit.exited - visit.entered <= window):
                opened += 1
    rate = (opened + LEAD_FLOW_PRIOR * PRIOR_STRENGTH) / (tried + PRIOR_STRENGTH)
    waiting = len(await common.leads_in_states(db, org_id, [LeadState.COLD_CALLING.value]))
    mean = waiting * rate
    spread = Z80 * math.sqrt(waiting * rate * (1 - rate))
    this_month = _month(common.local_day(now, tz))
    months = [this_month]
    for _ in range(2):
        year, mon = (int(x) for x in months[0].split("-"))
        months.insert(0, f"{year - 1:04d}-12" if mon == 1 else f"{year:04d}-{mon - 1:02d}")
    history = [{"month": m, "opened": opens_by_month.get(m, 0)} for m in months]
    if waiting == 0 and not any(h["opened"] for h in history):
        status, note = "empty", "No leads are in cold calling yet."
    elif tried < MIN_SAMPLES:
        status = "thin"
        note = "Little cold-calling history yet, so this leans on a starting estimate."
    else:
        status, note = "ok", None
    return common.block(status, note, history=history, expected=round(mean),
                        low=max(0, round(mean - spread)), high=round(mean + spread))


async def _by_person(db, org_id, odds, won_list) -> dict:
    """Expected wins credited to each deal's closer (spec 7.1b)."""
    people = await common.org_people(db, org_id)
    leads = [o["lead"] for o in odds]
    won_ids = [lead_id for lead_id, _ in won_list]
    won_leads = list((await db.execute(
        select(Lead).where(Lead.org_id == org_id, Lead.id.in_(won_ids))
    )).scalars().all()) if won_ids else []
    closers = await common.deal_people(db, org_id, leads + won_leads)
    totals: dict[str, float] = defaultdict(float)
    for o in odds:
        closer = closers[o["lead"].id][1]
        if closer:
            totals[closer] += o["p"]
    for lead_id in won_ids:
        closer = closers.get(lead_id, (None, None))[1]
        if closer:
            totals[closer] += 1
    items = [{"user_id": uid, "name": common.person_name(people, uid), "expected": round(v)}
             for uid, v in totals.items() if round(v) > 0]
    items.sort(key=lambda i: (-i["expected"], i["name"] or ""))
    if not items:
        return common.block("empty", "No expected wins can be credited to anyone yet.",
                            items=[])
    return common.block(items=items)
