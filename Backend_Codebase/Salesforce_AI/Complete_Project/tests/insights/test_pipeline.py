"""Pipeline screen (spec 6.2, 7.4): the stage funnel, time in each stage, and
the stalled deals."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core import clock
from app.insights import pipeline
from tests.insights.builders import make_lead, make_note, make_org, make_user

NOW = datetime(2026, 10, 22, 6, 0)          # Thursday 22 Oct, 11:30 in Kolkata
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


def _stage(result, state):
    return next(s for s in result["funnel"]["stages"] if s["state"] == state)


async def test_funnel_counts_by_range(db):
    org = await make_org(db, name="Funnel Org")
    head = await make_user(db, org, name="Lata", role="sales_lead")
    for i in range(3):
        await make_lead(db, org, name=f"Prospect {i}", state="cold_calling", owner=head,
                        created_by=head, created_at=NOW - 2 * DAY)
    await make_lead(db, org, name="Opened", state="open", owner=head, created_by=head,
                    created_at=NOW - 30 * DAY,
                    moves=(("cold_calling", "open", head, NOW - 20 * DAY),))
    # Closed on 2 Oct: inside this month, this quarter and this year.
    await make_lead(db, org, name="Delivered Oct", state="closed", owner=head, created_by=head,
                    created_at=NOW - 200 * DAY, moves=(
                        ("cold_calling", "open", head, NOW - 190 * DAY),
                        ("open", "active", head, NOW - 150 * DAY),
                        ("active", "execution_in_progress", head, NOW - 100 * DAY),
                        ("execution_in_progress", "client_execution_in_progress", head,
                         NOW - 60 * DAY),
                        ("client_execution_in_progress", "closed", head, NOW - 20 * DAY)))
    # Closed on 22 Aug: this year only.
    await make_lead(db, org, name="Delivered Aug", state="closed", owner=head, created_by=head,
                    created_at=NOW - 300 * DAY, moves=(
                        ("cold_calling", "open", head, NOW - 290 * DAY),
                        ("open", "active", head, NOW - 250 * DAY),
                        ("active", "execution_in_progress", head, NOW - 200 * DAY),
                        ("execution_in_progress", "client_execution_in_progress", head,
                         NOW - 120 * DAY),
                        ("client_execution_in_progress", "closed", head, NOW - 61 * DAY)))
    month = await pipeline.build(db, org.id, TZ, NOW, range="month")
    assert [s["state"] for s in month["funnel"]["stages"]] == [
        "cold_calling", "open", "active", "execution_in_progress",
        "client_execution_in_progress", "closed"]
    assert _stage(month, "cold_calling")["count"] == 3
    assert _stage(month, "open")["count"] == 1
    assert _stage(month, "closed")["count"] == 1
    assert _stage(month, "open")["label"] == "Open"
    year = await pipeline.build(db, org.id, TZ, NOW, range="year")
    assert _stage(year, "closed")["count"] == 2
    quarter = await pipeline.build(db, org.id, TZ, NOW, range="quarter")
    assert _stage(quarter, "closed")["count"] == 1


async def test_moves_on_and_avg_days(db):
    org = await make_org(db, name="Stage Time Org")
    head = await make_user(db, org, name="Lata", role="sales_lead")
    # Two visits to "open" that ended this month: one forward after 10 days,
    # one to lost after 4 days. One still in "open" for 6 days so far.
    await make_lead(db, org, name="Forward", state="active", owner=head, created_by=head,
                    created_at=NOW - 40 * DAY, moves=(
                        ("cold_calling", "open", head, NOW - 18 * DAY),
                        ("open", "active", head, NOW - 8 * DAY)))
    await make_lead(db, org, name="Dropped", state="lost_for_now", owner=head,
                    created_by=head, created_at=NOW - 40 * DAY, moves=(
                        ("cold_calling", "open", head, NOW - 9 * DAY),
                        ("open", "lost_for_now", head, NOW - 5 * DAY)))
    still = await make_lead(db, org, name="Still Open", state="open", owner=head,
                            created_by=head, created_at=NOW - 40 * DAY,
                            moves=(("cold_calling", "open", head, NOW - 6 * DAY),))
    await make_note(db, org, still, by=head, at=NOW - DAY)
    result = await pipeline.build(db, org.id, TZ, NOW, range="month")
    opened = _stage(result, "open")
    assert opened["moves_on"] == 0.5
    assert opened["avg_days"] == round((10 + 4 + 6) / 3, 1)
    assert _stage(result, "closed")["moves_on"] is None
    times = {s["state"]: s["avg_days"] for s in result["stage_time"]["stages"]}
    assert times["open"] == round((10 + 4 + 6) / 3, 1)
    assert result["stage_time"]["reading"]


async def test_stalled_needs_fourteen_quiet_days(db):
    org = await make_org(db, name="Stalled Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    head = await make_user(db, org, name="Lata", role="sales_lead")
    nearly = await make_lead(db, org, name="Thirteen Days", state="open", owner=agent,
                             created_by=head, created_at=NOW - 60 * DAY,
                             moves=(("cold_calling", "open", agent, NOW - 13 * DAY),))
    stalled = await make_lead(db, org, name="Fourteen Days", state="open", owner=agent,
                              created_by=head, created_at=NOW - 60 * DAY,
                              moves=(("cold_calling", "open", agent, NOW - 30 * DAY),))
    await make_note(db, org, stalled, by=agent, at=NOW - 14 * DAY)
    worse = await make_lead(db, org, name="Long Gone Cold", state="cold", owner=agent,
                            created_by=head, created_at=NOW - 90 * DAY,
                            moves=(("cold_calling", "open", agent, NOW - 80 * DAY),
                                   ("open", "cold", "system", NOW - 40 * DAY)))
    result = await pipeline.build(db, org.id, TZ, NOW, range="month")
    rows = result["stalled"]["items"]
    assert [r["lead_id"] for r in rows] == [worse.id, stalled.id]     # lowest score first
    assert nearly.id not in {r["lead_id"] for r in rows}
    first = rows[0]
    assert (first["state"], first["label"], first["days_in_state"]) == ("cold", "Cold", 40)
    assert (first["opener"], first["closer"]) == ("Asha", "Lata")
    assert first["reason"] == "Quiet for 15 days or more"
    assert result["stalled"]["status"] == "ok"


async def test_an_org_with_no_deals_is_empty(db):
    org = await make_org(db, name="Empty Pipeline Org")
    result = await pipeline.build(db, org.id, TZ, NOW, range="quarter")
    for name in ("funnel", "stage_time", "stalled"):
        assert result[name]["status"] == "empty", name
        assert result[name]["note"]
    assert all(s["count"] == 0 for s in result["funnel"]["stages"])
