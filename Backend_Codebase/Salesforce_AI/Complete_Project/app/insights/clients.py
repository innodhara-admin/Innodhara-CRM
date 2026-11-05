"""Clients screen (spec 6.5, 7.8): health from the deal score, score against
silence, the mood in client replies, promises kept, and clients who look
ready to buy again."""
from __future__ import annotations

from datetime import datetime, tzinfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import OpportunityStatus
from app.insights import common, scoring
from app.models.comms import InboundMessage
from app.models.lead import Lead
from app.models.project import ClientCommitment
from app.models.relationship import RelationshipEngagement

MOOD_MONTHS = 3
THIN_POINTS = 5


def _last_months(now: datetime, tz: tzinfo, n: int) -> list[str]:
    today = common.local_day(now, tz)
    year, month = today.year, today.month
    out = []
    for _ in range(n):
        out.insert(0, f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return out


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime) -> dict:
    deals = await common.leads_in_states(db, org_id, common.IN_PLAY)
    scores = await scoring.score_deals(db, org_id, deals, now, tz=tz)
    counts = {"healthy": 0, "watch": 0, "at_risk": 0}
    points = []
    for lead in deals:
        s = scores[lead.id]
        counts[s.health] += 1
        points.append({"lead_id": lead.id, "name": lead.name, "days_quiet": s.days_quiet,
                       "score": s.value, "health": s.health})
    points.sort(key=lambda p: (p["score"], -p["days_quiet"]))
    if not deals:
        health = common.block("empty", "No deals in play yet.", **counts)
        scatter = common.block("empty", "No deals in play yet.", points=[])
    else:
        health = common.block(**counts)
        scatter = (common.block("thin", "Only a few deals in play, so look at each one.",
                                points=points)
                   if len(points) < THIN_POINTS else common.block(points=points))
    return {
        "health": health,
        "scatter": scatter,
        "mood": await _mood(db, org_id, tz, now),
        "promises": await _promises(db, org_id),
        "opportunities": await _opportunities(db, org_id),
    }


async def _mood(db, org_id, tz, now) -> dict:
    months = _last_months(now, tz, MOOD_MONTHS)
    start, _ = common.month_bounds_utc(months[0], tz)
    by_month = {m: {"month": m, "positive": 0, "neutral": 0, "negative": 0} for m in months}
    at = func.coalesce(InboundMessage.received_at, InboundMessage.created_at)
    for when, sentiment in (await db.execute(
        select(at, InboundMessage.sentiment).where(
            InboundMessage.org_id == org_id, InboundMessage.sentiment.is_not(None),
            at >= start, at < now)
    )).all():
        day = common.local_day(common.as_dt(when), tz)
        key = f"{day.year:04d}-{day.month:02d}"
        if key in by_month and sentiment in ("positive", "neutral", "negative"):
            by_month[key][sentiment] += 1
    rows = list(by_month.values())
    if not any(r["positive"] + r["neutral"] + r["negative"] for r in rows):
        return common.block("empty", "No client replies have been read yet.", months=rows)
    return common.block(months=rows)


async def _promises(db, org_id) -> dict:
    tally = {"ours": {"kept": 0, "total": 0}, "theirs": {"kept": 0, "total": 0}}
    for direction, status, n in (await db.execute(
        select(ClientCommitment.direction, ClientCommitment.status, func.count())
        .where(ClientCommitment.org_id == org_id,
               ClientCommitment.status.in_(("kept", "broken")))
        .group_by(ClientCommitment.direction, ClientCommitment.status)
    )).all():
        if direction not in tally:
            continue
        tally[direction]["total"] += n
        if status == "kept":
            tally[direction]["kept"] += n
    if not tally["ours"]["total"] and not tally["theirs"]["total"]:
        return common.block("empty", "No promise has been kept or broken yet.", **tally)
    return common.block(**tally)


async def _opportunities(db, org_id) -> dict:
    rows = (await db.execute(
        select(RelationshipEngagement, Lead.name)
        .join(Lead, Lead.id == RelationshipEngagement.lead_id)
        .where(RelationshipEngagement.org_id == org_id,
               RelationshipEngagement.opportunity_status == OpportunityStatus.OPEN.value)
        .order_by(RelationshipEngagement.opportunity_at.desc())
    )).all()
    items = [{"lead_id": e.lead_id, "name": name, "reason": e.opportunity_reason,
              "at": common.iso_utc(e.opportunity_at)} for e, name in rows]
    if not items:
        return common.block("empty", "No client looks ready to buy again right now.", items=[])
    return common.block(items=items)
