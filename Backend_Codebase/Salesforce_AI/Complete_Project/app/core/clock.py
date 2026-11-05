"""One clock for every date judgement — the organisation's own.

## The rule

**Instants are stored in UTC. Every question of the form "which day is that?"
is answered in the organisation's timezone, through this module.**

Mixing the two is what produced the defect this exists to end:
`assistant_engine` compared `ActionItem.due_date.date()` — the **UTC** date of a
stored instant — against `date.today()`, the date in whatever timezone the
*server process* happens to run in. Those agree for most of the day and part
company whenever the two calendars differ, which for Asia/Kolkata is any instant
from 18:30 UTC onwards. A task due 20:00 UTC is due 01:30 tomorrow morning in
Kolkata — thirty minutes away — and was reported as **overdue**.

## Why storage was left in UTC

Storing local time instead was considered and rejected on the numbers: 75
`DateTime` column declarations and 148 `utcnow()` call sites, against a live
database whose existing rows are UTC. A naive local-time column is
byte-identical to a naive UTC column, so a half-finished migration is invisible
— every row would need converting in one shot, correctly, with no way to detect
a row that had been missed. The judgement layer is where the bug actually lives,
and it is one module wide.

## Why the organisation's zone, not a constant

`org_settings.timezone` already exists and already defaults to `Asia/Kolkata`,
the console already edits it, and `tests/test_genericity.py` exists precisely to
stop this product hardcoding one country. Reading the column costs one query and
keeps a Dubai organisation correct for free.

## Agreeing with the Android app

`MyTasksFragment.parseDate` reads the naive ISO string as UTC and converts to
the **device** zone before taking the date. `local_date` does the same thing
with the **organisation** zone, so with the two aligned — the normal case — the
phone and the server name the same day. Before this, they could not.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: `org_settings.timezone`'s own column default, kept in step with it by
#: `tests/test_clock.py`.
DEFAULT_TIMEZONE = "Asia/Kolkata"

_UTC = timezone.utc
_cache: dict[str, ZoneInfo] = {}


def zone(name: str | None = None) -> tzinfo:
    """Resolve a timezone name, **never raising**.

    An organisation's timezone is free text on a settings screen, and a typo in
    it must not be able to stop a briefing from rendering or a sweep from
    running. An unknown name degrades to the default rather than taking the
    caller down.
    """
    key = (name or "").strip() or DEFAULT_TIMEZONE
    cached = _cache.get(key)
    if cached is not None:
        return cached
    resolved: tzinfo | None = None
    for candidate in (key, DEFAULT_TIMEZONE):
        try:
            resolved = ZoneInfo(candidate)
            break
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            continue
    if resolved is None:
        # The default is itself a zone name, so a host with no timezone
        # database (a slim container without `tzdata` — see requirements.txt)
        # fails to resolve it too, from inside the handler for that very error.
        # `timezone.utc` needs no database and is the one zone always available.
        # Dates will be a few hours out for an eastern tenant, which is wrong
        # but legible; raising here would take down every briefing and sweep.
        resolved = _UTC
    _cache[key] = resolved
    return resolved


def to_local(instant: datetime | None, tz: tzinfo) -> datetime | None:
    """A stored instant as an aware datetime in `tz`.

    Naive input is treated as UTC, which is what `models.base.utcnow` writes.
    Aware input is converted rather than reinterpreted, so passing one already
    in a zone cannot shift it twice.
    """
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=_UTC)
    return instant.astimezone(tz)


def local_date(instant: datetime | None, tz: tzinfo) -> date | None:
    """Which day a stored instant falls on, in `tz`.

    **Use this instead of `.date()` on any stored datetime.** `.date()` answers
    in UTC, which is a different question from the one every screen is asking.
    """
    local = to_local(instant, tz)
    return local.date() if local is not None else None


def now(tz: tzinfo) -> datetime:
    """The current moment, aware, in `tz`."""
    return datetime.now(_UTC).astimezone(tz)


def today(tz: tzinfo) -> date:
    """Today in `tz` — never `date.today()`, which answers for the server."""
    return now(tz).date()


def start_of_day_utc(day: date, tz: tzinfo) -> datetime:
    """The naive-UTC instant at which `day` begins in `tz`.

    For range queries that must stay in the database: comparing a stored column
    against these bounds is exact, where converting every row in Python is not.
    """
    local_midnight = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    return local_midnight.astimezone(_UTC).replace(tzinfo=None)


async def org_zone(db, org_id: str | None) -> tzinfo:
    """The organisation's timezone, or the default when there isn't one.

    An organisation with no settings row, or none at all, resolves to the
    default rather than failing — the same reasoning as `zone`.
    """
    if not org_id:
        return zone(None)
    from sqlalchemy import select

    from app.models.organisation import OrgSettings

    name = (
        await db.execute(
            select(OrgSettings.timezone).where(OrgSettings.org_id == org_id)
        )
    ).scalar_one_or_none()
    return zone(name)
