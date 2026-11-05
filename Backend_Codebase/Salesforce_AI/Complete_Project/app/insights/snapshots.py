"""Lazy daily snapshots: the only writes the sales head's screens make
(spec 9.1.4).

The first insights request of the organisation's day stores that day's
score for every deal in play, and the org pulse once Pulse has computed it.
Nothing is scheduled. Two requests racing on the same day both try; the
unique key lets one win and the other's insert is rolled back on its own
savepoint, leaving the request's transaction intact.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights import common, scoring
from app.models.insight import KIND_DEAL_SCORE, KIND_ORG_PULSE, InsightSnapshot


async def _has(db: AsyncSession, org_id: str, day: date, kind: str) -> bool:
    return (await db.execute(
        select(InsightSnapshot.id).where(
            InsightSnapshot.org_id == org_id, InsightSnapshot.day == day,
            InsightSnapshot.kind == kind).limit(1)
    )).first() is not None


async def _insert(db: AsyncSession, rows: list[InsightSnapshot]) -> None:
    if not rows:
        return
    try:
        async with db.begin_nested():
            db.add_all(rows)
    except IntegrityError:
        pass        # another request wrote today's rows first


async def ensure_today(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, *,
                       pulse_score: int | None = None) -> None:
    today = common.local_day(now, tz)
    if not await _has(db, org_id, today, KIND_DEAL_SCORE):
        leads = await common.leads_in_states(db, org_id, common.IN_PLAY)
        scores = await scoring.score_deals(db, org_id, leads, now, tz=tz)
        await _insert(db, [
            InsightSnapshot(org_id=org_id, day=today, kind=KIND_DEAL_SCORE,
                            subject_id=lead_id, value={"score": score.value})
            for lead_id, score in scores.items()
        ])
    if pulse_score is not None and not await _has(db, org_id, today, KIND_ORG_PULSE):
        # The organisation is the subject: a NULL here would not be unique.
        await _insert(db, [InsightSnapshot(org_id=org_id, day=today, kind=KIND_ORG_PULSE,
                                           subject_id=org_id, value={"score": pulse_score})])


async def score_trend(db: AsyncSession, org_id: str, lead_id: str, days: int,
                      today: date) -> list[dict]:
    """Stored scores of one deal over the last `days` days, oldest first."""
    rows = (await db.execute(
        select(InsightSnapshot.day, InsightSnapshot.value).where(
            InsightSnapshot.org_id == org_id, InsightSnapshot.kind == KIND_DEAL_SCORE,
            InsightSnapshot.subject_id == lead_id,
            InsightSnapshot.day > today - timedelta(days=days),
            InsightSnapshot.day <= today,
        ).order_by(InsightSnapshot.day)
    )).all()
    return [{"date": day.isoformat(), "score": int((value or {}).get("score", 0))}
            for day, value in rows]


async def pulse_on_or_before(db: AsyncSession, org_id: str, day: date) -> int | None:
    row = (await db.execute(
        select(InsightSnapshot.value).where(
            InsightSnapshot.org_id == org_id, InsightSnapshot.kind == KIND_ORG_PULSE,
            InsightSnapshot.day <= day,
        ).order_by(InsightSnapshot.day.desc()).limit(1)
    )).scalar_one_or_none()
    return None if row is None else int(row.get("score", 0))
