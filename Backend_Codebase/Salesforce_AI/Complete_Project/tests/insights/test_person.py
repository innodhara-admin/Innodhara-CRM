"""Person report card (spec 6.9) and its consistency flags (7.10): what the
records show about one person, against the middle of their colleagues in the
same role. A flag is evidence, never a verdict, so every flag has a twin test
proving the innocent version of the same thing stays quiet."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core import clock
from app.core.exceptions import NotFoundError
from app.insights import person, team
from tests.insights.builders import (
    make_assignment, make_contact, make_followup, make_lead, make_login, make_meeting,
    make_note, make_org, make_outbound, make_ping, make_task, make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)          # Thursday 22 Oct, 11:30 in Kolkata
DAY = timedelta(days=1)
MIN = timedelta(minutes=1)
TZ = clock.zone("Asia/Kolkata")


async def _org(db):
    org = await make_org(db, name="Report Card Org")
    asha = await make_user(db, org, name="Asha", role="sales_agent",
                           created_at=NOW - 200 * DAY)
    lata = await make_user(db, org, name="Lata", role="sales_lead",
                           created_at=NOW - 200 * DAY)
    return org, asha, lata


async def _flags(db, org, user, kind=None, days=7):
    found = await person.flags(db, org.id, TZ, NOW, user.id, days)
    return [f for f in found if kind is None or f["kind"] == kind]


# ── flag 1: moved with nothing behind it ────────────────────────────────────

async def test_moved_without_activity_is_flagged(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Quiet Open", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 30 * DAY,
                           moves=(("cold_calling", "open", asha, NOW - 2 * DAY),))
    flags = await _flags(db, org, asha, "moved_without_activity")
    assert len(flags) == 1
    assert flags[0]["subject"] == {"type": "deal", "id": lead.id}
    assert "Quiet Open" in flags[0]["evidence"] and "20 Oct" in flags[0]["evidence"]
    assert flags[0]["title"]


async def test_opener_move_with_contact_is_not_flagged(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Reached Client", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 30 * DAY,
                           moves=(("cold_calling", "open", asha, NOW - 2 * DAY),))
    await make_contact(db, org, lead, by=asha, at=NOW - 3 * DAY)
    assert await _flags(db, org, asha, "moved_without_activity") == []


async def test_handover_move_by_closer_is_not_flagged(db):
    org, asha, lata = await _org(db)
    await make_lead(db, org, name="Handed On", state="active", owner=asha, created_by=lata,
                    created_at=NOW - 60 * DAY, moves=(
                        ("cold_calling", "open", asha, NOW - 40 * DAY),
                        ("open", "active", lata, NOW - 2 * DAY)))
    assert await _flags(db, org, lata, "moved_without_activity") == []


async def test_a_backwards_move_is_not_a_flag(db):
    org, asha, lata = await _org(db)
    await make_lead(db, org, name="Went Cold", state="cold", owner=lata, created_by=lata,
                    created_at=NOW - 60 * DAY, moves=(
                        ("cold_calling", "open", lata, NOW - 40 * DAY),
                        ("open", "cold", lata, NOW - 2 * DAY)))
    assert await _flags(db, org, lata, "moved_without_activity") == []


# ── flag 2: tasks closed in a burst ─────────────────────────────────────────

async def test_task_burst_is_flagged(db):
    org, asha, _ = await _org(db)
    start = NOW - 2 * DAY
    for i in range(5):
        await make_task(db, org, assignee=asha, due=NOW, completed_at=start + i * 2 * MIN,
                        completion_method="in_app")
    flags = await _flags(db, org, asha, "task_burst")
    assert len(flags) == 1
    assert "5 tasks" in flags[0]["evidence"]
    assert flags[0]["subject"] is None


async def test_burst_with_notes_is_not_flagged(db):
    org, asha, _ = await _org(db)
    start = NOW - 2 * DAY
    for i in range(5):
        await make_task(db, org, assignee=asha, due=NOW, completed_at=start + i * 2 * MIN,
                        result_note="Called and confirmed")
    for i in range(4):          # four is not a burst
        await make_task(db, org, assignee=asha, due=NOW, completed_at=start + DAY + i * MIN)
    for i in range(6):          # uploaded proof is not a burst either
        await make_task(db, org, assignee=asha, due=NOW, completed_at=start + 3 * 60 * MIN + i * MIN,
                        completion_method="manual_upload")
    assert await _flags(db, org, asha, "task_burst") == []


# ── flag 3: follow-up done, nothing sent ────────────────────────────────────

async def test_followup_nothing_sent_is_flagged(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Chased Client", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 30 * DAY)
    await make_followup(db, org, lead, owner=asha, due=date(2026, 10, 20),
                        completed_at=NOW - 2 * DAY)
    flags = await _flags(db, org, asha, "followup_nothing_sent")
    assert len(flags) == 1 and flags[0]["subject"] == {"type": "deal", "id": lead.id}


async def test_followup_with_message_is_not_flagged(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Mailed Client", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 30 * DAY)
    await make_followup(db, org, lead, owner=asha, due=date(2026, 10, 20),
                        completed_at=NOW - 2 * DAY)
    await make_outbound(db, org, lead, sender=asha, sent_at=NOW - 2 * DAY + 3 * 60 * MIN)
    other = await make_lead(db, org, name="Met Client", state="open", owner=asha,
                            created_by=lata, created_at=NOW - 30 * DAY)
    await make_followup(db, org, other, owner=asha, due=date(2026, 10, 20),
                        completed_at=NOW - 2 * DAY, message_id="sent-message")
    assert await _flags(db, org, asha, "followup_nothing_sent") == []


# ── flag 4: location ────────────────────────────────────────────────────────

async def test_fake_gps_is_flagged(db):
    org, asha, _ = await _org(db)
    await make_ping(db, org, asha, at=NOW - DAY, mock=True)
    flags = await _flags(db, org, asha, "location")
    assert len(flags) == 1 and "fake" in flags[0]["evidence"].lower()


async def test_location_refused_on_three_days_is_flagged(db):
    org, asha, _ = await _org(db)
    for d in (1, 2):
        await make_ping(db, org, asha, at=NOW - d * DAY, status="permission_denied")
    assert await _flags(db, org, asha, "location") == []
    await make_ping(db, org, asha, at=NOW - 3 * DAY, status="permission_denied")
    flags = await _flags(db, org, asha, "location")
    assert len(flags) == 1 and "3 days" in flags[0]["evidence"]


# ── flag 5: silent working days ─────────────────────────────────────────────

async def _new_starter(db, org, **kw):
    """Joined on Monday 19 Oct; active on Monday and Wednesday."""
    sam = await make_user(db, org, name="Sam", role="sales_agent",
                          created_at=datetime(2026, 10, 19, 3, 0), **kw)
    await make_login(db, org, sam, at=datetime(2026, 10, 19, 4, 0))
    await make_ping(db, org, sam, at=datetime(2026, 10, 21, 4, 0))
    return sam


async def test_silent_working_day_is_flagged(db):
    org, *_ = await _org(db)
    sam = await _new_starter(db, org)
    flags = await _flags(db, org, sam, "silent_working_day")
    assert len(flags) == 1
    assert "20 Oct" in flags[0]["evidence"]


async def test_leave_day_is_not_silent(db):
    org, *_ = await _org(db)
    sam = await _new_starter(db, org, on_leave=(date(2026, 10, 20), date(2026, 10, 20)))
    assert await _flags(db, org, sam, "silent_working_day") == []


async def test_a_day_off_is_not_silent(db):
    org, *_ = await _org(db)
    sam = await _new_starter(db, org, working_days=["Mon", "Wed", "Thu", "Fri"])
    assert await _flags(db, org, sam, "silent_working_day") == []


# ── the card ────────────────────────────────────────────────────────────────

async def test_on_time_late_overdue_split(db):
    org, asha, _ = await _org(db)
    await make_task(db, org, assignee=asha, due=datetime(2026, 10, 18),
                    completed_at=datetime(2026, 10, 18, 15, 0))          # 20:30 on the due day
    await make_task(db, org, assignee=asha, due=datetime(2026, 10, 17),
                    completed_at=datetime(2026, 10, 19, 9, 0))           # late
    await make_task(db, org, assignee=asha, due=datetime(2026, 10, 20))  # overdue now
    await make_task(db, org, assignee=asha, due=datetime(2026, 10, 1))   # long overdue
    await make_task(db, org, assignee=asha, due=datetime(2026, 10, 25))  # not due yet
    task = await make_task(db, org, assignee=asha, due=datetime(2026, 10, 30), status="declined")
    await make_assignment(db, org, task, to=asha, status="declined", decline_reason="busy",
                          decided_at=NOW - DAY)
    lead = await make_lead(db, org, name="Follow Client", state="open", owner=asha,
                           created_at=NOW - 30 * DAY)
    await make_followup(db, org, lead, owner=asha, due=date(2026, 10, 19),
                        completed_at=datetime(2026, 10, 19, 8, 0))
    await make_followup(db, org, lead, owner=asha, due=date(2026, 10, 20))
    report = await person.build(db, org.id, TZ, NOW, user_id=asha.id, days=7)
    tasks = report["tasks"]
    assert (tasks["assigned"], tasks["on_time"], tasks["late"], tasks["overdue"],
            tasks["declined"]) == (3, 1, 1, 2, 1)
    assert tasks["decline_reasons"] == ["Too busy"]
    assert tasks["followups"] == {"due": 2, "done_on_day": 1, "missed": 1}
    assert report["follow_through"]["on_time_rate"] == round(1 / 3, 2)


async def test_team_middle_is_same_role_median(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Meeting Client", state="open", owner=asha,
                           created_at=NOW - 30 * DAY)
    others = [await make_user(db, org, name=n, role="sales_agent") for n in ("Bala", "Chitra", "Dev")]
    for who, n in ((asha, 1), (others[0], 3), (others[1], 10), (others[2], 4), (lata, 50)):
        for i in range(n):
            await make_meeting(db, org, lead, by=who, at=NOW - DAY + i * MIN)
    effort = (await person.build(db, org.id, TZ, NOW, user_id=asha.id, days=7))["effort"]
    meetings = next(i for i in effort["items"] if i["key"] == "meetings")
    assert (meetings["value"], meetings["team_middle"]) == (1, 4)
    assert [i["key"] for i in effort["items"]] == ["meetings", "emails", "notes", "contacts",
                                                   "jarvis", "active_days"]


async def test_opener_and_closer_stats_differ(db):
    org, asha, lata = await _org(db)
    lead = await make_lead(db, org, name="Handed Client", state="open", owner=asha,
                           created_by=lata, created_at=NOW - 3 * DAY,
                           moves=(("cold_calling", "open", asha, NOW - DAY),))
    await make_contact(db, org, lead, by=asha, at=NOW - 2 * DAY)
    opener = (await person.build(db, org.id, TZ, NOW, user_id=asha.id, days=7))["leads"]
    closer = (await person.build(db, org.id, TZ, NOW, user_id=lata.id, days=7))["leads"]
    assert (opener["role_kind"], closer["role_kind"]) == ("opener", "closer")
    o = {s["label"]: s["value"] for s in opener["stats"]}
    c = {s["label"]: s["value"] for s in closer["stats"]}
    assert o["Leads handed over"] == "1" and o["Opened"] == "1" and o["Contacts added"] == "1"
    assert o["Hand-over to first contact"] == "1 day"
    assert c["Leads created and handed out"] == "1"
    assert set(o) != set(c)
    assert opener["by_state"] == [{"state": "open", "label": "Open", "count": 1}]
    assert closer["by_state"] == [{"state": "open", "label": "Open", "count": 1}]


async def test_day_spans_and_field(db):
    org, asha, _ = await _org(db)
    lead = await make_lead(db, org, name="Span Client", state="open", owner=asha,
                           created_at=NOW - 30 * DAY)
    await make_ping(db, org, asha, at=datetime(2026, 10, 21, 3, 30))         # 09:00
    await make_note(db, org, lead, by=asha, at=datetime(2026, 10, 21, 12, 0))  # 17:30
    await make_ping(db, org, asha, at=datetime(2026, 10, 20, 4, 0), mock=True)
    report = await person.build(db, org.id, TZ, NOW, user_id=asha.id, days=7)
    spans = {d["date"]: (d["first"], d["last"]) for d in report["day_spans"]["days"]}
    assert spans["2026-10-21"] == ("09:00", "17:30")
    assert spans["2026-10-19"] == (None, None)
    assert len(spans) == 7
    assert (report["field"]["days_seen"], report["field"]["fake_gps"]) == (2, 1)
    assert report["person"]["since"] == (NOW - 200 * DAY).date().isoformat()


async def test_inactive_and_missing_people_do_not_break(db):
    org, asha, lata = await _org(db)
    gone = await make_user(db, org, name="Gone", role="sales_agent", is_active=False)
    lead = await make_lead(db, org, name="Ghost Owned", state="open", owner="deleted-user-id",
                           created_by="deleted-user-id", created_at=NOW - 20 * DAY)
    await make_task(db, org, assignee="deleted-user-id", due=NOW - DAY, lead=lead)
    await make_meeting(db, org, lead, by="deleted-user-id", at=NOW - DAY)
    report = await person.build(db, org.id, TZ, NOW, user_id=gone.id, days=30)
    assert report["person"]["name"] == "Gone"
    await person.build(db, org.id, TZ, NOW, user_id=asha.id, days=30)
    await team.build(db, org.id, TZ, NOW, metric="meetings", days=30)
    with pytest.raises(NotFoundError):
        await person.build(db, org.id, TZ, NOW, user_id="deleted-user-id", days=7)
