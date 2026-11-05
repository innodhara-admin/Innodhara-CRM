"""Field map (spec 6.8): each person's readings on one day. Readings are app
opens, not visits, and the screen says so."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core import clock
from app.core.exceptions import NotFoundError
from app.insights import field
from tests.insights.builders import make_org, make_ping, make_user

NOW = datetime(2026, 10, 22, 6, 0)          # 11:30 in Kolkata
TODAY = date(2026, 10, 22)
HOUR = timedelta(hours=1)
TZ = clock.zone("Asia/Kolkata")


async def _org(db):
    org = await make_org(db, name="Field Org")
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    lata = await make_user(db, org, name="Lata", role="sales_lead")
    await make_user(db, org, name="Omar", role="operations_agent")       # sends no readings
    return org, asha, lata


async def test_latest_and_fresh(db):
    org, asha, lata = await _org(db)
    await make_ping(db, org, asha, at=NOW - 3 * HOUR, lat=12.90, lng=77.50)
    await make_ping(db, org, asha, at=NOW - 30 * timedelta(minutes=1), lat=12.95, lng=77.55,
                    approximate=True)
    await make_ping(db, org, asha, at=NOW - 10 * timedelta(minutes=1), status="gps_off")
    await make_ping(db, org, lata, at=NOW - 2 * HOUR)
    result = await field.build(db, org.id, TZ, NOW, day=TODAY)
    people = {p["name"]: p for p in result["people"]["items"]}
    assert set(people) == {"Asha", "Lata"}
    asha_row = people["Asha"]
    assert asha_row["latest"]["lat"] == 12.95 and asha_row["latest"]["approximate"] is True
    assert asha_row["fresh"] is True and asha_row["readings"] == 3
    assert asha_row["first"].endswith("Z") and asha_row["last"] > asha_row["first"]
    assert people["Lata"]["fresh"] is False
    assert result["map"]["style_url"].startswith("https://")
    assert "not live tracking" in result["note"]


async def test_a_person_not_seen_is_listed(db):
    org, asha, lata = await _org(db)
    await make_ping(db, org, asha, at=NOW - HOUR)
    people = {p["name"]: p for p in (await field.build(db, org.id, TZ, NOW, day=TODAY))
              ["people"]["items"]}
    assert people["Lata"]["latest"] is None and people["Lata"]["readings"] == 0
    assert people["Lata"]["status_note"] == "Not seen today"


async def test_trail_only_ok_readings_in_order(db):
    org, asha, _ = await _org(db)
    await make_ping(db, org, asha, at=NOW - HOUR, lat=12.3, lng=77.3)
    await make_ping(db, org, asha, at=NOW - 3 * HOUR, lat=12.1, lng=77.1)
    await make_ping(db, org, asha, at=NOW - 2 * HOUR, status="permission_denied")
    await make_ping(db, org, asha, at=NOW - 30 * HOUR, lat=11.0, lng=76.0)   # yesterday
    trail = await field.person(db, org.id, TZ, NOW, user_id=asha.id, day=TODAY)
    assert [(p["lat"], p["lng"]) for p in trail["trail"]] == [(12.1, 77.1), (12.3, 77.3)]
    assert trail["readings"] == 3 and trail["status"] == "ok"
    with pytest.raises(NotFoundError):
        await field.person(db, org.id, TZ, NOW, user_id="nobody", day=TODAY)


async def test_trust_counts(db):
    org, asha, lata = await _org(db)
    await make_ping(db, org, asha, at=NOW - HOUR)
    await make_ping(db, org, asha, at=NOW - 2 * HOUR, mock=True)
    await make_ping(db, org, asha, at=NOW - 3 * HOUR, approximate=True)
    await make_ping(db, org, lata, at=NOW - HOUR, status="gps_off")
    await make_ping(db, org, lata, at=NOW - 2 * HOUR, status="timeout")
    await make_ping(db, org, lata, at=NOW - 3 * HOUR, status="permission_denied")
    trust = (await field.build(db, org.id, TZ, NOW, day=TODAY))["trust"]
    assert {k: trust[k] for k in ("ok", "gps_off", "timeout", "permission_denied", "mock",
                                  "approximate")} == {
        "ok": 3, "gps_off": 1, "timeout": 1, "permission_denied": 1, "mock": 1,
        "approximate": 1}


async def test_hours_in_org_zone(db):
    org, asha, _ = await _org(db)
    await make_ping(db, org, asha, at=datetime(2026, 10, 22, 3, 30))     # 09:00 in Kolkata
    await make_ping(db, org, asha, at=datetime(2026, 10, 21, 19, 0))     # 00:30 on the 22nd
    hours = (await field.build(db, org.id, TZ, NOW, day=TODAY))["hours"]["counts"]
    assert len(hours) == 24 and hours[9] == 1 and hours[0] == 1 and sum(hours) == 2


async def test_old_day_is_empty(db):
    org, asha, _ = await _org(db)
    result = await field.build(db, org.id, TZ, NOW, day=TODAY - timedelta(days=91))
    assert result["people"]["status"] == "empty"
    assert result["people"]["note"] == "Readings are kept for 90 days."
    assert result["trust"]["status"] == "empty"
