"""One clock for every date judgement — `app/core/clock.py`.

The defect this exists to end: an instant is stored in UTC and then asked
"which day is that?" by code holding a *different* zone's calendar.
`assistant_engine` compared `due_date.date()` (UTC) against `date.today()`
(the server's own zone), so a task due 20:00 UTC — 01:30 the next morning in
Asia/Kolkata, thirty minutes away — was reported as overdue.

Storage stays UTC (75 DateTime columns and 148 `utcnow()` call sites are not
worth migrating, and a naive-IST column is indistinguishable from a naive-UTC
one that was never converted). What changes is that every *judgement* about
what day something falls on runs through here, in the organisation's own
timezone.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import clock

IST = clock.zone("Asia/Kolkata")


# ── zone() never raises, because a bad value must not stop a briefing ────────

def test_zone_defaults_to_the_column_default_when_unset():
    assert str(clock.zone(None)) == clock.DEFAULT_TIMEZONE
    assert str(clock.zone("")) == clock.DEFAULT_TIMEZONE


def test_zone_falls_back_rather_than_raising_on_a_bad_name():
    assert str(clock.zone("Not/AZone")) == clock.DEFAULT_TIMEZONE


def test_zone_honours_a_real_name_other_than_the_default():
    assert str(clock.zone("Europe/London")) == "Europe/London"


# ── local_date() — the function the mix needed ───────────────────────────────

def test_an_evening_utc_instant_belongs_to_the_next_day_in_ist():
    """20:00 UTC is 01:30 the next morning in Asia/Kolkata."""
    assert clock.local_date(datetime(2026, 8, 25, 20, 0), IST) == date(2026, 8, 26)


def test_a_working_hours_utc_instant_belongs_to_the_same_day_in_ist():
    assert clock.local_date(datetime(2026, 8, 25, 5, 0), IST) == date(2026, 8, 25)


def test_the_boundary_is_1830_utc():
    assert clock.local_date(datetime(2026, 8, 25, 18, 29), IST) == date(2026, 8, 25)
    assert clock.local_date(datetime(2026, 8, 25, 18, 30), IST) == date(2026, 8, 26)


def test_local_date_of_nothing_is_nothing():
    assert clock.local_date(None, IST) is None


def test_an_already_aware_instant_is_not_shifted_twice():
    aware = datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc)
    assert clock.local_date(aware, IST) == date(2026, 8, 26)


def test_local_date_agrees_with_what_the_android_app_computes():
    """`MyTasksFragment.parseDate` reads the naive string as UTC and converts to
    the device zone. With the org zone and the device zone the same, the two
    must land on the same day — that agreement is the whole point."""
    stored = datetime(2026, 8, 25, 20, 0)
    android = (
        stored.replace(tzinfo=timezone.utc)
        .astimezone(timezone(timedelta(hours=5, minutes=30)))
        .date()
    )
    assert clock.local_date(stored, IST) == android


# ── today() — never the server's own date ────────────────────────────────────

def test_today_in_utc_is_the_utc_date():
    assert clock.today(clock.zone("UTC")) == datetime.now(timezone.utc).date()


def test_today_in_ist_is_the_ist_date():
    expected = datetime.now(timezone.utc).astimezone(IST).date()
    assert clock.today(IST) == expected


def test_two_zones_either_side_of_the_dateline_can_disagree():
    """Proof that `today` is genuinely zone-dependent and not the server's."""
    pair = {clock.today(clock.zone("Pacific/Kiritimati")),
            clock.today(clock.zone("Pacific/Midway"))}
    assert len(pair) == 2


# ── org_zone() — where the zone comes from in practice ───────────────────────

@pytest.mark.asyncio
async def test_org_zone_reads_the_organisations_own_setting(client, super_token):
    from tests.conftest import auth, create_org

    from app.database import SessionLocal

    org = await create_org(client, super_token, name="Clock Org",
                           slug="clock-org", domain="clock-org-example.com")
    async with SessionLocal() as db:
        assert str(await clock.org_zone(db, org["id"])) == "Asia/Kolkata"

    await client.patch("/api/v1/admin/settings", headers=auth(org["admin_token"]),
                       json={"timezone": "Europe/London"})
    async with SessionLocal() as db:
        assert str(await clock.org_zone(db, org["id"])) == "Europe/London"


@pytest.mark.asyncio
async def test_org_zone_of_an_unknown_org_is_the_default(client, super_token):
    from app.database import SessionLocal

    async with SessionLocal() as db:
        assert str(await clock.org_zone(db, "0" * 32)) == clock.DEFAULT_TIMEZONE


def test_zone_survives_a_host_with_no_timezone_database(monkeypatch):
    """The fallback must not need the thing that just failed.

    `zone()` degrades an unknown name to the default — but the default is itself
    a zone name, so on a slim container with no tz database (the reason
    `tzdata` is in requirements.txt) resolving it would raise too, from inside
    the handler for exactly that error. UTC is the one zone `datetime` can
    always produce.
    """
    import app.core.clock as clock_mod

    def _always_missing(_name):
        raise clock_mod.ZoneInfoNotFoundError("no tz database on this host")

    monkeypatch.setattr(clock_mod, "ZoneInfo", _always_missing)
    monkeypatch.setattr(clock_mod, "_cache", {})

    tz = clock_mod.zone("Asia/Kolkata")
    assert tz is not None
    assert clock_mod.today(tz) is not None
    assert clock_mod.local_date(datetime(2026, 8, 25, 20, 0), tz) is not None


@pytest.mark.asyncio
async def test_me_reports_the_organisations_timezone(client, super_token):
    """The Android app buckets tasks with `ZoneId.systemDefault()` — the phone's
    zone. That is the same class of mix one layer out: a rep travelling, or a
    phone set wrong, and the app names a different day from the server that fed
    it. `GET /auth/me` already carries the org's branding for the app; the zone
    it must reckon dates in belongs there too."""
    from tests.conftest import auth, create_org

    org = await create_org(client, super_token, name="Tz Me",
                           slug="tz-me", domain="tz-me-example.com")
    me = (await client.get("/api/v1/auth/me",
                           headers=auth(org["admin_token"]))).json()
    assert me["org_timezone"] == "Asia/Kolkata"

    await client.patch("/api/v1/admin/settings", headers=auth(org["admin_token"]),
                       json={"timezone": "Europe/London"})
    me = (await client.get("/api/v1/auth/me",
                           headers=auth(org["admin_token"]))).json()
    assert me["org_timezone"] == "Europe/London"
