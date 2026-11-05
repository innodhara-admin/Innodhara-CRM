"""Pulse, the home screen (spec 6.1, 7.2, 7.3, 7.9, 7.13): the org pulse and
its change, the four tiles, what needs the sales head's eyes, and the week."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.core import clock
from app.insights import pulse
from app.models.insight import InsightSnapshot
from tests.insights.builders import (
    make_commitment, make_inbound, make_lead, make_meeting, make_note, make_org,
    make_outbound, make_ping, make_project, make_proposal, make_task, make_thread, make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)          # Thursday 22 Oct, 11:30 in Kolkata
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _org(db):
    org = await make_org(db, name="Pulse Org")
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    lata = await make_user(db, org, name="Lata", role="sales_lead")
    return org, asha, lata


async def _decided(db, org, who, i, *, won, days_ago=30, opened_days_before=20):
    at = NOW - days_ago * DAY
    opened = at - opened_days_before * DAY
    last = ("active", "execution_in_progress") if won else ("active", "lost_for_now")
    return await make_lead(db, org, name=f"Decided {i} {won}", state=last[1], owner=who,
                           created_by=who, created_at=opened - 10 * DAY, moves=(
                               ("cold_calling", "open", who, opened),
                               ("open", "active", who, opened + DAY),
                               (*last, who, at)))


async def test_win_rate_needs_five_decided(db):
    org, _, lata = await _org(db)
    for i in range(3):
        await _decided(db, org, lata, i, won=True)
    await _decided(db, org, lata, 3, won=False)
    rate = (await pulse.build(db, org.id, TZ, NOW))["tiles"]["win_rate"]
    assert (rate["value"], rate["won"], rate["decided"], rate["status"]) == (None, 3, 4, "thin")
    await _decided(db, org, lata, 4, won=False)
    await _decided(db, org, lata, 5, won=True, days_ago=100)          # outside 90 days
    rate = (await pulse.build(db, org.id, TZ, NOW))["tiles"]["win_rate"]
    assert (rate["value"], rate["won"], rate["decided"], rate["status"]) == (0.6, 3, 5, "ok")


async def test_days_to_win_is_median_of_open_to_won(db):
    org, _, lata = await _org(db)
    for i, before in enumerate((10, 20, 40)):
        await _decided(db, org, lata, i, won=True, opened_days_before=before)
    await _decided(db, org, lata, 9, won=True, days_ago=200, opened_days_before=99)  # too old
    tile = (await pulse.build(db, org.id, TZ, NOW))["tiles"]["days_to_win"]
    assert tile["value"] == 20


async def test_in_play_trend_has_eight_weeks(db):
    org, asha, _ = await _org(db)
    await make_lead(db, org, name="Old Deal", state="open", owner=asha, created_by=asha,
                    created_at=NOW - 100 * DAY,
                    moves=(("cold_calling", "open", asha, NOW - 90 * DAY),))
    await make_lead(db, org, name="New Deal", state="active", owner=asha, created_by=asha,
                    created_at=NOW - 20 * DAY, moves=(
                        ("cold_calling", "open", asha, NOW - 10 * DAY),
                        ("open", "active", asha, NOW - 5 * DAY)))
    tile = (await pulse.build(db, org.id, TZ, NOW))["tiles"]["in_play"]
    assert tile["value"] == 2
    assert len(tile["trend"]) == 8
    assert tile["trend"][0] == 1 and tile["trend"][-1] == 2


async def test_pulse_parts_and_change(db):
    org, asha, lata = await _org(db)
    a = await make_lead(db, org, name="Warm Active", state="active", owner=asha, created_by=lata,
                        created_at=NOW - 60 * DAY)
    b = await make_lead(db, org, name="Warm Open", state="open", owner=asha, created_by=lata,
                        created_at=NOW - 60 * DAY)
    await make_note(db, org, a, by=asha, at=NOW - DAY)          # 68, healthy
    await make_note(db, org, b, by=asha, at=NOW - 2 * DAY)      # 60, healthy
    await make_task(db, org, assignee=asha, due=NOW - 3 * DAY, completed_at=NOW - 3 * DAY)
    await make_task(db, org, assignee=asha, due=NOW - 4 * DAY)  # overdue: not on time
    db.add(InsightSnapshot(org_id=org.id, day=date(2026, 10, 15), kind="org_pulse",
                           subject_id=org.id, value={"score": 60}))
    await db.flush()
    result = (await pulse.build(db, org.id, TZ, NOW))["pulse"]
    assert result["parts"] == {"moving": 100, "follow_through": 50, "client_health": 100,
                               "activity": 100}
    assert (result["score"], result["change"]) == (88, 28)
    stored = (await db.execute(select(InsightSnapshot.value).where(
        InsightSnapshot.org_id == org.id, InsightSnapshot.kind == "org_pulse",
        InsightSnapshot.day == date(2026, 10, 22)))).scalar_one()
    assert stored == {"score": 88}


async def _every_alert(db):
    """One deal or person for each of the seven alert kinds."""
    org, asha, lata = await _org(db)
    quiet = await make_lead(db, org, name="Silent Deal", state="cold", owner=asha,
                            created_by=lata, created_at=NOW - 90 * DAY,
                            moves=(("cold_calling", "open", asha, NOW - 80 * DAY),
                                   ("open", "cold", "system", NOW - 40 * DAY)))
    waiting = await make_lead(db, org, name="Unanswered Deal", state="active", owner=asha,
                              created_by=lata, created_at=NOW - 60 * DAY)
    await make_note(db, org, waiting, by=lata, at=NOW - DAY)
    await make_proposal(db, org, waiting, status="sent", sent_at=NOW - 12 * DAY)
    await make_thread(db, org, waiting, last_direction="outbound",
                      last_message_at=NOW - 12 * DAY)
    unhappy = await make_lead(db, org, name="Unhappy Deal", state="active", owner=asha,
                              created_by=lata, created_at=NOW - 60 * DAY)
    await make_inbound(db, org, unhappy, at=NOW - 2 * DAY, sentiment="negative")
    promised = await make_lead(db, org, name="Promise Deal", state="active", owner=asha,
                               created_by=lata, created_at=NOW - 60 * DAY)
    await make_note(db, org, promised, by=lata, at=NOW - DAY)
    project = await make_project(db, org, promised, sales_owner=lata)
    await make_commitment(db, org, project, direction="ours", status="broken",
                          due=NOW - 3 * DAY)
    busy = await make_user(db, org, name="Bala", role="sales_agent", max_open_tasks=2)
    for _ in range(3):
        await make_task(db, org, assignee=busy, due=NOW + 5 * DAY)
    late = await make_user(db, org, name="Chitra", role="sales_agent")
    for d in (2, 3, 4):
        await make_task(db, org, assignee=late, due=NOW - d * DAY)
    hidden = await make_user(db, org, name="Dev", role="sales_agent")
    for d in (0, 1, 2):
        await make_ping(db, org, hidden, at=NOW - d * DAY - timedelta(hours=1),
                        status="permission_denied")
    return org, {"deal_quiet": quiet.id, "proposal_unanswered": waiting.id,
                 "negative_reply": unhappy.id, "promise_broken": promised.id,
                 "over_capacity": busy.id, "overdue_tasks": late.id,
                 "location_refused": hidden.id}


async def test_each_alert_kind_fires(db):
    org, subjects = await _every_alert(db)
    found = await pulse.alerts(db, org.id, TZ, NOW)
    by_kind = {a["kind"]: a for a in found}
    assert set(by_kind) == set(subjects)
    for kind, subject_id in subjects.items():
        assert by_kind[kind]["subject"]["id"] == subject_id, kind
        assert by_kind[kind]["title"] and by_kind[kind]["detail"]
    assert {a["severity"] for a in found if a["kind"] in ("deal_quiet", "proposal_unanswered")} \
        == {"critical"}
    assert by_kind["over_capacity"]["subject"]["type"] == "person"
    assert by_kind["deal_quiet"]["subject"]["type"] == "deal"


async def test_alerts_order_and_cap(db):
    org, _ = await _every_alert(db)
    shown = (await pulse.build(db, org.id, TZ, NOW))["alerts"]["items"]
    assert len(shown) == 5
    order = {"critical": 0, "serious": 1, "warning": 2}
    ranks = [order[a["severity"]] for a in shown]
    assert ranks == sorted(ranks)
    assert [a["kind"] for a in shown[:2]] == ["deal_quiet", "proposal_unanswered"]   # oldest first


async def test_activity_week_is_monday_to_saturday(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Week Client", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 30 * DAY)
    await make_meeting(db, org, lead, by=lata, at=datetime(2026, 10, 19, 6, 0))
    await make_outbound(db, org, lead, sender=asha, sent_at=datetime(2026, 10, 20, 6, 0))
    await make_outbound(db, org, lead, sender=asha, sent_at=datetime(2026, 10, 18, 6, 0))  # Sun
    days = (await pulse.build(db, org.id, TZ, NOW))["activity_week"]["days"]
    assert [d["date"] for d in days] == [f"2026-10-{n}" for n in range(19, 25)]
    assert days[0]["meetings"] == 1 and days[1]["emails"] == 1
    assert sum(d["emails"] for d in days) == 1


async def test_an_empty_org_has_an_empty_pulse(db):
    org = await make_org(db, name="Quiet Pulse Org")
    result = await pulse.build(db, org.id, TZ, NOW)
    assert result["pulse"]["status"] == "empty"
    assert result["pulse"]["score"] == 0 and result["pulse"]["change"] is None
    assert result["alerts"]["status"] == "empty"
    assert result["ai"]["spent_usd"] == 0.0


async def test_one_kind_cannot_fill_every_slot(db):
    """Developer's call, 24 Oct: the most urgent alert of each kind gets a slot
    first, so six quiet deals cannot hide an overloaded person."""
    org, asha, lata = await _org(db)
    for i in range(6):
        await make_lead(db, org, name=f"Silent Deal {i}", state="cold", owner=asha,
                        created_by=lata, created_at=NOW - 90 * DAY,
                        moves=(("cold_calling", "open", asha, NOW - 80 * DAY),
                               ("open", "cold", "system", NOW - (40 + i) * DAY)))
    busy = await make_user(db, org, name="Bala", role="sales_agent", max_open_tasks=2)
    for _ in range(3):
        await make_task(db, org, assignee=busy, due=NOW + 5 * DAY)
    shown = (await pulse.build(db, org.id, TZ, NOW))["alerts"]["items"]
    assert len(shown) == 5
    assert [a["kind"] for a in shown] == ["deal_quiet"] * 4 + ["over_capacity"]
    assert shown[-1]["subject"]["id"] == busy.id
