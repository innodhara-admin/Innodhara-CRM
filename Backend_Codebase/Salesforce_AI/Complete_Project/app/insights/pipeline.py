"""Pipeline screen (spec 6.2, 7.4): the stage funnel, time spent in each
stage, and the deals that have stalled."""
from __future__ import annotations

from datetime import datetime, tzinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LeadState
from app.insights import common, scoring
from app.models.lead import Lead

THIN_DEALS = 5
THIN_VISITS = 5
STALLED_MAX = 10
TIME_STAGES = (
    LeadState.COLD_CALLING.value, LeadState.OPEN.value, LeadState.ACTIVE.value,
    LeadState.COLD.value, LeadState.EXECUTION_IN_PROGRESS.value,
    LeadState.CLIENT_EXECUTION_IN_PROGRESS.value,
)


def _days(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 86400)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime,
                range: str = "month") -> dict:
    today = common.local_day(now, tz)
    start, end = common.period_bounds_utc(range, today, tz)
    end = min(end, now)

    leads = list((await db.execute(select(Lead).where(Lead.org_id == org_id))).scalars().all())
    states = await common.states_as_of(db, org_id, end)
    past = await common.history(db, org_id)
    visits = common.stage_visits(past)
    quiet = await common.last_activity(db, org_id, [lead.id for lead in leads], now)
    by_id = {lead.id: lead for lead in leads}

    def days_quiet(lead_id: str) -> int:
        lead = by_id[lead_id]
        return common.days_between(quiet.get(lead_id) or lead.created_at, now)

    stages = []
    for state in common.STAGE_ORDER:
        if state == LeadState.CLOSED.value:
            count = sum(1 for v in visits if v.state == state and start <= v.entered < end)
            stages.append({"state": state, "label": common.STATE_LABELS[state], "count": count,
                           "moves_on": None, "stuck": 0, "avg_days": None})
            continue
        ended = [v for v in visits if v.state == state and v.exited is not None
                 and start <= v.exited < end]
        open_now = [v for v in visits if v.state == state and v.exited is None
                    and v.lead_id in by_id]
        durations = ([_days(v.entered, v.exited) for v in ended]
                     + [_days(v.entered, end) for v in open_now])
        stuck = sum(1 for v in open_now
                    if _days(v.entered, now) >= common.STUCK_DAYS
                    and days_quiet(v.lead_id) >= common.STUCK_DAYS)
        stages.append({
            "state": state, "label": common.STATE_LABELS[state],
            "count": sum(1 for s in states.values() if s == state),
            "moves_on": (round(sum(1 for v in ended if common.is_forward(state, v.exit_to))
                               / len(ended), 2) if ended else None),
            "stuck": stuck, "avg_days": _avg(durations),
        })
    total = sum(s["count"] for s in stages)
    if total == 0:
        funnel = common.block("empty", "No clients have been added yet.", stages=stages)
    elif total < THIN_DEALS:
        funnel = common.block("thin", f"Only {total} clients so far, so the shape is rough.",
                              stages=stages)
    else:
        funnel = common.block(stages=stages)

    time_rows, samples = [], 0
    for state in TIME_STAGES:
        durations = [_days(v.entered, v.exited) for v in visits
                     if v.state == state and v.exited is not None and start <= v.exited < end]
        durations += [_days(v.entered, end) for v in visits
                      if v.state == state and v.exited is None and v.lead_id in by_id]
        samples += len(durations)
        time_rows.append({"state": state, "label": common.STATE_LABELS[state],
                          "avg_days": _avg(durations)})
    longest = max((r for r in time_rows if r["avg_days"] is not None),
                  key=lambda r: r["avg_days"], default=None)
    reading = (f"Deals spend longest in {longest['label']}, about "
               f"{round(longest['avg_days'])} days on average." if longest else None)
    if samples == 0:
        stage_time = common.block("empty", "No deal has moved between stages yet.",
                                  stages=time_rows, reading=None)
    elif samples < THIN_VISITS:
        stage_time = common.block("thin", "Few stage moves so far; these averages will settle.",
                                  stages=time_rows, reading=reading)
    else:
        stage_time = common.block(stages=time_rows, reading=reading)

    stalled = await stalled_deals(db, org_id, tz, now, leads=leads, past=past)
    return {"funnel": funnel, "stage_time": stage_time, "stalled": stalled}


async def stalled_deals(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, *,
                        leads: list[Lead], past) -> dict:
    """In play, no forward move and no activity for 14 days or more."""
    in_play = [lead for lead in leads if lead.state in common.IN_PLAY]
    if not in_play:
        return common.block("empty", "No deals in play yet.", items=[])
    scores = await scoring.score_deals(db, org_id, in_play, now, tz=tz)
    people = await common.org_people(db, org_id)
    owners = await common.deal_people(db, org_id, in_play)
    rows = []
    for lead in in_play:
        score = scores[lead.id]
        in_state = common.days_between(
            common.current_visit_start(past.get(lead.id, []), lead.created_at), now)
        if in_state < common.STUCK_DAYS or score.days_quiet < common.STUCK_DAYS:
            continue
        worst = min((f for f in score.factors if f["points"] < 0),
                    key=lambda f: f["points"], default=None)
        opener, closer = owners[lead.id]
        rows.append({
            "lead_id": lead.id, "name": lead.name, "state": lead.state,
            "label": common.STATE_LABELS.get(lead.state, lead.state),
            "days_in_state": in_state,
            "opener": common.person_name(people, opener),
            "closer": common.person_name(people, closer),
            "score": score.value,
            "reason": worst["label"] if worst else f"Quiet for {score.days_quiet} days",
        })
    rows.sort(key=lambda r: (r["score"], -r["days_in_state"]))
    note = None if rows else "No deal has been quiet for 14 days."
    return common.block("ok", note, items=rows[:STALLED_MAX])
