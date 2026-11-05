"""Meeting intelligence (spec 6.7): counts, recorded hours, tasks and plans
that came out of meetings, the weekly rhythm, types, and the latest
meetings with their summary line."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core import clock
from app.insights import meetings
from tests.insights.builders import make_lead, make_meeting, make_org, make_task, make_user

NOW = datetime(2026, 10, 22, 6, 0)          # Thursday 22 Oct
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _org(db):
    org = await make_org(db, name="Meetings Org")
    lata = await make_user(db, org, name="Lata", role="sales_lead")
    lead = await make_lead(db, org, name="Met Client", state="active", owner=lata,
                           created_by=lata, created_at=NOW - 90 * DAY)
    return org, lata, lead


async def test_meeting_hours_ignore_typed_notes(db):
    org, lata, lead = await _org(db)
    first = await make_meeting(db, org, lead, by=lata, at=NOW - DAY, minutes=30,
                               meeting_type="first_visit", plan_state="approved")
    await make_meeting(db, org, lead, by=lata, at=NOW - 2 * DAY, minutes=90,
                       meeting_type="negotiation", plan_state="discarded")
    await make_meeting(db, org, lead, by=lata, at=NOW - 3 * DAY, minutes=None,
                       meeting_type="negotiation", plan_state="no_plan")      # typed notes
    await make_meeting(db, org, lead, by=lata, at=NOW - 20 * DAY, minutes=60)  # outside 7 days
    for _ in range(3):
        await make_task(db, org, assignee=lata, due=NOW + DAY, meeting=first)
    summary = (await meetings.build(db, org.id, TZ, NOW, days=7))["summary"]
    assert (summary["count"], summary["hours"], summary["avg_minutes"]) == (3, 2.0, 60)
    assert (summary["tasks_created"], summary["plans_approved"], summary["plans_total"]) == (3, 1, 2)


async def test_types_are_counted_and_labelled(db):
    org, lata, lead = await _org(db)
    for kind in ("negotiation", "negotiation", "first_visit", None):
        await make_meeting(db, org, lead, by=lata, at=NOW - DAY, meeting_type=kind)
    types = (await meetings.build(db, org.id, TZ, NOW, days=7))["types"]["items"]
    assert types == [{"type": "negotiation", "label": "Negotiation", "count": 2},
                     {"type": "first_visit", "label": "First visit", "count": 1},
                     {"type": "other", "label": "Not set", "count": 1}]


async def test_latest_summary_trimmed(db):
    org, lata, lead = await _org(db)
    long_first = "The client " + "really " * 40 + "liked the plan. They asked about dates."
    await make_meeting(db, org, lead, by=lata, at=NOW - DAY, minutes=20,
                       summary="Agreed on a pilot. Next step is the proposal.")
    await make_meeting(db, org, lead, by=lata, at=NOW - 2 * DAY, summary=long_first)
    latest = (await meetings.build(db, org.id, TZ, NOW, days=7))["latest"]["items"]
    assert latest[0]["summary"] == "Agreed on a pilot."
    assert latest[0]["minutes"] == 20 and latest[0]["lead_name"] == "Met Client"
    assert len(latest[1]["summary"]) <= 140 and latest[1]["summary"].endswith("...")
    assert latest[1]["minutes"] is None


async def test_per_week_has_eight_weeks(db):
    org, lata, lead = await _org(db)
    await make_meeting(db, org, lead, by=lata, at=datetime(2026, 10, 19, 6, 0))
    await make_meeting(db, org, lead, by=lata, at=datetime(2026, 10, 20, 6, 0))
    await make_meeting(db, org, lead, by=lata, at=datetime(2026, 9, 1, 6, 0))
    weeks = (await meetings.build(db, org.id, TZ, NOW, days=7))["per_week"]["weeks"]
    assert len(weeks) == 8
    assert weeks[-1] == {"week_start": "2026-10-19", "count": 2}
    assert weeks[0]["week_start"] == "2026-08-31"
    assert weeks[0]["count"] == 1


async def test_no_meetings_is_empty(db):
    org, *_ = await _org(db)
    result = await meetings.build(db, org.id, TZ, NOW, days=30)
    for name in ("summary", "per_week", "types", "latest"):
        assert result[name]["status"] == "empty", name
    assert result["summary"]["avg_minutes"] is None
