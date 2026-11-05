"""Team screen (spec 6.4, 7.16): who did what, the field card, workload and
when the team works."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.core import clock
from app.insights import team
from tests.insights.builders import (
    make_assistant_turn, make_contact, make_followup, make_lead, make_meeting, make_note,
    make_org, make_outbound, make_ping, make_task, make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)          # Thursday 22 Oct, 11:30 in Kolkata
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _team(db):
    org = await make_org(db, name="Team Org")
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    bala = await make_user(db, org, name="Bala", role="sales_agent")
    lata = await make_user(db, org, name="Lata", role="sales_lead")
    lead = await make_lead(db, org, name="Team Client", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 60 * DAY)
    return org, asha, bala, lata, lead


async def test_metric_switch_and_sort(db):
    org, asha, bala, lata, lead = await _team(db)
    for d in (1, 2, 3):
        await make_meeting(db, org, lead, by=lata, at=NOW - d * DAY)
    await make_meeting(db, org, lead, by=asha, at=NOW - DAY)
    for d in (1, 2):
        await make_outbound(db, org, lead, sender=bala, sent_at=NOW - d * DAY)
    await make_meeting(db, org, lead, by=asha, at=NOW - 20 * DAY)     # outside 7 days
    by_meetings = (await team.build(db, org.id, TZ, NOW, metric="meetings", days=7))["people"]
    assert by_meetings["metric"] == "meetings"
    assert [(i["name"], i["value"]) for i in by_meetings["items"]] == [
        ("Lata", 3), ("Asha", 1), ("Bala", 0)]
    assert by_meetings["items"][0]["role"] == "sales_lead"
    by_emails = (await team.build(db, org.id, TZ, NOW, metric="emails", days=7))["people"]
    assert [(i["name"], i["value"]) for i in by_emails["items"]][0] == ("Bala", 2)
    thirty = (await team.build(db, org.id, TZ, NOW, metric="meetings", days=30))["people"]
    assert [(i["name"], i["value"]) for i in thirty["items"]][:2] == [("Lata", 3), ("Asha", 2)]


async def test_emails_count_only_sent(db):
    org, asha, _, _, lead = await _team(db)
    await make_outbound(db, org, lead, sender=asha, sent_at=NOW - DAY)
    await make_outbound(db, org, lead, sender=asha, sent_at=None, status="draft")
    await make_outbound(db, org, lead, sender=asha, sent_at=None, status="rejected")
    await make_outbound(db, org, lead, sender=asha, sent_at=None, status="pending_approval")
    counts = await team.counts_by_person(db, org.id, NOW - 7 * DAY, NOW)
    assert counts[asha.id]["emails"] == 1


async def test_counts_cover_every_kind(db):
    org, asha, _, _, lead = await _team(db)
    await make_meeting(db, org, lead, by=asha, at=NOW - DAY)
    await make_followup(db, org, lead, owner=asha, due=date(2026, 10, 21),
                        completed_at=NOW - DAY)
    await make_task(db, org, assignee=asha, due=NOW, completed_at=NOW - DAY)
    await make_note(db, org, lead, by=asha, at=NOW - DAY)
    await make_contact(db, org, lead, by=asha, at=NOW - DAY)
    counts = (await team.counts_by_person(db, org.id, NOW - 7 * DAY, NOW))[asha.id]
    assert counts == {"meetings": 1, "emails": 0, "followups": 1, "tasks_done": 1,
                      "notes": 1, "contacts": 1, "jarvis": 0}


async def test_jarvis_counts_sessions_not_turns(db):
    org, asha, *_ = await _team(db)
    for i in range(5):
        await make_assistant_turn(db, org, asha, at=NOW - DAY + i * timedelta(minutes=1),
                                  session_id="s-1")
    await make_assistant_turn(db, org, asha, at=NOW - 2 * DAY, session_id="s-2")
    counts = await team.counts_by_person(db, org.id, NOW - 7 * DAY, NOW)
    assert counts[asha.id]["jarvis"] == 2


async def test_workload_capacity(db):
    org, asha, bala, *_ = await _team(db)
    for _ in range(3):
        await make_task(db, org, assignee=asha, due=NOW + DAY)
    await make_task(db, org, assignee=asha, due=NOW + DAY, status="in_progress")
    await make_task(db, org, assignee=asha, due=NOW, completed_at=NOW - DAY)      # done
    await make_task(db, org, assignee=asha, due=NOW, status="cancelled")
    workload = (await team.build(db, org.id, TZ, NOW, metric="meetings", days=7))["workload"]
    rows = {i["name"]: (i["open"], i["capacity"]) for i in workload["items"]}
    assert rows["Asha"] == (4, 8) and rows["Bala"] == (0, 8)
    assert workload["items"][0]["name"] == "Asha"            # the fullest plate first


async def test_heatmap_shape_and_levels(db):
    org, asha, _, lata, lead = await _team(db)
    # Monday 19 Oct (this week): 4 actions; Tuesday 20 Oct: 1; Sunday is not shown.
    monday = datetime(2026, 10, 19, 6, 0)
    for i in range(4):
        await make_note(db, org, lead, by=asha, at=monday + i * timedelta(minutes=5))
    await make_meeting(db, org, lead, by=lata, at=monday + DAY)
    await make_note(db, org, lead, by=asha, at=datetime(2026, 10, 18, 6, 0))       # Sunday
    heat = (await team.build(db, org.id, TZ, NOW, metric="meetings", days=7))["heatmap"]
    weeks = heat["weeks"]
    assert len(weeks) == 6 and all(len(w["days"]) == 6 for w in weeks)
    assert weeks[-1]["week_start"] == "2026-10-19"
    assert weeks[0]["week_start"] == "2026-09-14"
    this_week = weeks[-1]["days"]
    assert [d["date"] for d in this_week][:2] == ["2026-10-19", "2026-10-20"]
    assert (this_week[0]["count"], this_week[1]["count"]) == (4, 1)
    assert this_week[0]["level"] > this_week[1]["level"] > 0
    assert this_week[2]["count"] == 0 and this_week[2]["level"] == 0
    assert all(0 <= d["level"] <= 4 for w in weeks for d in w["days"])


async def test_field_card_location_off(db):
    org, asha, bala, lata, _ = await _team(db)
    await make_ping(db, org, asha, at=NOW - timedelta(hours=1))
    await make_ping(db, org, bala, at=NOW - timedelta(hours=2), status="permission_denied")
    await make_ping(db, org, lata, at=NOW - 2 * DAY)                     # not today
    card = (await team.build(db, org.id, TZ, NOW, metric="meetings", days=7))["field_card"]
    assert (card["seen_today"], card["team_size"], card["location_off"]) == (1, 3, ["Bala"])


async def test_a_team_of_nobody_is_empty(db):
    org = await make_org(db, name="Lonely Org")
    result = await team.build(db, org.id, TZ, NOW, metric="meetings", days=7)
    for name in ("people", "field_card", "workload", "heatmap"):
        assert result[name]["status"] == "empty", name
