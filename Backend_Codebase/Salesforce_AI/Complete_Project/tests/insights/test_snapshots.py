"""Daily snapshots of deal scores and the org pulse (spec 9.1.4): written by
the first insights request of the org's day, once, and read back as trends."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select

from app.core import clock
from app.insights import snapshots
from app.models.insight import InsightSnapshot
from tests.insights.builders import make_lead, make_note, make_org, make_user

NOW = datetime(2026, 10, 22, 20, 0)     # 01:30 on the 23rd in Kolkata
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _rows(db, org_id, kind=None):
    query = select(InsightSnapshot).where(InsightSnapshot.org_id == org_id)
    if kind:
        query = query.where(InsightSnapshot.kind == kind)
    return (await db.execute(query)).scalars().all()


async def test_first_call_writes_once(db):
    org = await make_org(db, name="Snapshot Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    in_play = []
    for name, state in (("One", "open"), ("Two", "active"), ("Three", "cold")):
        lead = await make_lead(db, org, name=name, state=state, owner=agent,
                               created_by=agent, created_at=NOW - 30 * DAY)
        await make_note(db, org, lead, by=agent, at=NOW - DAY)
        in_play.append(lead)
    await make_lead(db, org, name="Prospect", state="cold_calling", owner=agent,
                    created_by=agent, created_at=NOW - DAY)
    await snapshots.ensure_today(db, org.id, TZ, NOW, pulse_score=64)
    await snapshots.ensure_today(db, org.id, TZ, NOW, pulse_score=70)
    scores = await _rows(db, org.id, "deal_score")
    assert sorted(r.subject_id for r in scores) == sorted(lead.id for lead in in_play)
    assert {r.day for r in scores} == {date(2026, 10, 23)}      # the org's day
    pulse = await _rows(db, org.id, "org_pulse")
    assert [(r.subject_id, r.value) for r in pulse] == [(org.id, {"score": 64})]


async def test_a_pulse_written_later_in_the_day_is_kept(db):
    """The score rows can exist before anyone has computed a pulse."""
    org = await make_org(db, name="Late Pulse Org")
    await snapshots.ensure_today(db, org.id, TZ, NOW)
    assert await _rows(db, org.id, "org_pulse") == []
    await snapshots.ensure_today(db, org.id, TZ, NOW, pulse_score=55)
    assert len(await _rows(db, org.id, "org_pulse")) == 1


async def test_trend_returns_stored_days_in_order(db):
    org = await make_org(db, name="Trend Org")
    for offset, score in ((3, 40), (1, 48), (2, 44), (12, 10)):
        db.add(InsightSnapshot(org_id=org.id, day=date(2026, 10, 23) - timedelta(days=offset),
                               kind="deal_score", subject_id="lead-1", value={"score": score}))
    db.add(InsightSnapshot(org_id=org.id, day=date(2026, 10, 22), kind="deal_score",
                           subject_id="lead-2", value={"score": 99}))
    await db.flush()
    trend = await snapshots.score_trend(db, org.id, "lead-1", 10, date(2026, 10, 23))
    assert trend == [{"date": "2026-10-20", "score": 40}, {"date": "2026-10-21", "score": 44},
                     {"date": "2026-10-22", "score": 48}]


async def test_pulse_on_or_before_picks_latest_not_after(db):
    org = await make_org(db, name="Pulse Org")
    for day, score in ((date(2026, 10, 10), 50), (date(2026, 10, 15), 61),
                       (date(2026, 10, 18), 70)):
        db.add(InsightSnapshot(org_id=org.id, day=day, kind="org_pulse",
                               subject_id=org.id, value={"score": score}))
    await db.flush()
    assert await snapshots.pulse_on_or_before(db, org.id, date(2026, 10, 16)) == 61
    assert await snapshots.pulse_on_or_before(db, org.id, date(2026, 10, 15)) == 61
    assert await snapshots.pulse_on_or_before(db, org.id, date(2026, 10, 9)) is None


async def test_rows_of_another_org_are_not_read(db):
    org = await make_org(db, name="Mine")
    other = await make_org(db, name="Theirs")
    db.add(InsightSnapshot(org_id=other.id, day=date(2026, 10, 20), kind="org_pulse",
                           subject_id=other.id, value={"score": 80}))
    await db.flush()
    assert await snapshots.pulse_on_or_before(db, org.id, date(2026, 10, 23)) is None
    count = (await db.execute(select(func.count()).select_from(InsightSnapshot)
                              .where(InsightSnapshot.org_id == org.id))).scalar_one()
    assert count == 0


async def test_a_racing_duplicate_is_absorbed(db):
    """Two requests on the same day: the loser's insert fails on the unique
    key and is rolled back alone; the request carries on."""
    org = await make_org(db, name="Race Org")
    db.add(InsightSnapshot(org_id=org.id, day=date(2026, 10, 23), kind="org_pulse",
                           subject_id=org.id, value={"score": 1}))
    await db.flush()
    await snapshots._insert(db, [InsightSnapshot(org_id=org.id, day=date(2026, 10, 23),
                                                 kind="org_pulse", subject_id=org.id,
                                                 value={"score": 2})])
    pulse = await _rows(db, org.id, "org_pulse")
    assert [r.value for r in pulse] == [{"score": 1}]
