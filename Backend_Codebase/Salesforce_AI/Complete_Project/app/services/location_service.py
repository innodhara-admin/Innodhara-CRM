"""Field location (2 Oct 2026): store the readings phones send, and read them
back for the org admin's map.

A reading is taken only when a sales agent or a sales lead opens the app or
brings it back to the screen. The same thinning rule runs on the phone and
here, so a phone that misbehaves cannot flood the table: a reading is kept
when ten minutes have passed since the last kept one, or the person moved
more than 200 m, or something about it changed (status, fake GPS,
approximate location). Status changes are what the admin most needs to see,
so they are always kept.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import Role
from app.core.exceptions import ValidationFailedError
from app.models.base import utcnow
from app.models.location import STATUS_OK, LocationPing
from app.models.user import User

TRACKED_ROLES = (Role.SALES_AGENT.value, Role.SALES_LEAD.value)
MIN_GAP = timedelta(minutes=10)
MIN_MOVE_M = 200.0
FUTURE_SLACK = timedelta(minutes=5)
MAX_AGE = timedelta(days=7)
MAX_WINDOW = timedelta(days=31)
MAX_POINTS = 5000
FAKE_GPS_WINDOW = timedelta(days=7)
_EARTH_RADIUS_M = 6_371_000.0


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def to_utc_naive(value: datetime) -> datetime:
    """Stored datetimes are naive UTC, like every other table."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def worth_saving(
    last: LocationPing | None, *, status: str, lat: float | None,
    lng: float | None, is_mock: bool, approximate: bool, captured_at: datetime,
) -> bool:
    """The thinning rule (the app's LocationThrottle is the same rule)."""
    if last is None:
        return True
    if (status != last.status or bool(is_mock) != bool(last.is_mock)
            or bool(approximate) != bool(last.approximate)):
        return True
    if captured_at - last.captured_at >= MIN_GAP:
        return True
    if status == STATUS_OK and None not in (lat, lng, last.lat, last.lng):
        return distance_m(last.lat, last.lng, lat, lng) > MIN_MOVE_M
    return False


async def record(
    db: AsyncSession, *, org_id: str, user_id: str, client_ref: str, status: str,
    lat: float | None, lng: float | None, accuracy_m: float | None,
    is_mock: bool, approximate: bool, trigger: str, captured_at: datetime,
) -> tuple[bool, str | None]:
    """Store one reading. Returns (saved, reason when not saved)."""
    now = utcnow()
    captured = to_utc_naive(captured_at)
    if captured > now + FUTURE_SLACK:
        # A phone whose clock runs ahead: the server's time is the better guess.
        captured = now
    if captured < now - MAX_AGE:
        raise ValidationFailedError("This reading is more than 7 days old.")
    if status == STATUS_OK and (lat is None or lng is None):
        raise ValidationFailedError("A recorded location needs a latitude and a longitude.")
    if status != STATUS_OK:
        lat = lng = accuracy_m = None
        is_mock = False

    seen = (await db.execute(
        select(LocationPing.id).where(
            LocationPing.org_id == org_id, LocationPing.user_id == user_id,
            LocationPing.client_ref == client_ref,
        ).limit(1)
    )).first()
    if seen is not None:
        return False, "duplicate"

    # Compared with the last kept reading taken at or before this one, so a
    # reading that arrives late from the phone's outbox is judged in order.
    last = (await db.execute(
        select(LocationPing).where(
            LocationPing.org_id == org_id, LocationPing.user_id == user_id,
            LocationPing.captured_at <= captured,
        ).order_by(LocationPing.captured_at.desc()).limit(1)
    )).scalars().first()
    if not worth_saving(last, status=status, lat=lat, lng=lng, is_mock=is_mock,
                        approximate=approximate, captured_at=captured):
        return False, "too_soon"

    try:
        async with db.begin_nested():
            db.add(LocationPing(
                org_id=org_id, user_id=user_id, client_ref=client_ref,
                status=status, lat=lat, lng=lng, accuracy_m=accuracy_m,
                is_mock=bool(is_mock), approximate=bool(approximate),
                trigger=trigger, captured_at=captured, received_at=now,
            ))
    except IntegrityError:
        # The same reading sent twice at the same moment: one of them won.
        return False, "duplicate"
    return True, None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def point_out(ping: LocationPing) -> dict[str, Any]:
    return {
        "user_id": ping.user_id, "status": ping.status,
        "lat": ping.lat, "lng": ping.lng, "accuracy_m": ping.accuracy_m,
        "is_mock": bool(ping.is_mock), "approximate": bool(ping.approximate),
        "captured_at": _iso(ping.captured_at),
    }


async def latest(db: AsyncSession, *, org_id: str, tz: tzinfo) -> list[dict[str, Any]]:
    """Every active sales agent and sales lead of the org, with their last
    reading of any kind, their last position, how many readings today said
    location off, and how many fake-GPS positions in the last 7 days."""
    people = (await db.execute(
        select(User).where(
            User.org_id == org_id, User.role.in_(TRACKED_ROLES),
            User.is_active.is_(True),
        ).order_by(User.name)
    )).scalars().all()
    today_start = clock.start_of_day_utc(clock.today(tz), tz)
    fake_since = utcnow() - FAKE_GPS_WINDOW
    out: list[dict[str, Any]] = []
    for person in people:
        mine = (LocationPing.org_id == org_id, LocationPing.user_id == person.id)
        last_any = (await db.execute(
            select(LocationPing).where(*mine)
            .order_by(LocationPing.captured_at.desc()).limit(1)
        )).scalars().first()
        last_ok = (await db.execute(
            select(LocationPing).where(*mine, LocationPing.status == STATUS_OK)
            .order_by(LocationPing.captured_at.desc()).limit(1)
        )).scalars().first()
        off_today = (await db.execute(
            select(func.count()).select_from(LocationPing).where(
                *mine, LocationPing.status != STATUS_OK,
                LocationPing.captured_at >= today_start)
        )).scalar_one()
        fake = (await db.execute(
            select(func.count()).select_from(LocationPing).where(
                *mine, LocationPing.is_mock.is_(True),
                LocationPing.captured_at >= fake_since)
        )).scalar_one()
        out.append({
            "user_id": person.id, "name": person.name, "role": person.role,
            "last_seen_at": _iso(last_any.captured_at) if last_any else None,
            "last_status": last_any.status if last_any else None,
            "last_ok": None if last_ok is None else {
                "lat": last_ok.lat, "lng": last_ok.lng,
                "accuracy_m": last_ok.accuracy_m,
                "captured_at": _iso(last_ok.captured_at),
                "is_mock": bool(last_ok.is_mock),
                "approximate": bool(last_ok.approximate),
            },
            "off_today": off_today,
            "fake_gps_7d": fake,
        })
    return out


async def points(
    db: AsyncSession, *, org_id: str, start: datetime, end: datetime,
    user_ids: list[str] | None, roles: list[str] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Readings in [start, end), oldest first. At most MAX_POINTS: the newest
    are kept and `truncated` says some older ones were left out."""
    start, end = to_utc_naive(start), to_utc_naive(end)
    if end <= start:
        raise ValidationFailedError("'to' must be after 'from'.")
    if end - start > MAX_WINDOW:
        raise ValidationFailedError("Choose at most 31 days at a time.")
    query = (
        select(LocationPing)
        .join(User, User.id == LocationPing.user_id)
        .where(
            LocationPing.org_id == org_id, User.org_id == org_id,
            LocationPing.captured_at >= start, LocationPing.captured_at < end,
        )
    )
    if user_ids:
        query = query.where(LocationPing.user_id.in_(user_ids))
    if roles:
        query = query.where(User.role.in_(roles))
    rows = (await db.execute(
        query.order_by(LocationPing.captured_at.desc()).limit(MAX_POINTS + 1)
    )).scalars().all()
    truncated = len(rows) > MAX_POINTS
    rows = list(rows[:MAX_POINTS])
    rows.reverse()
    return [point_out(p) for p in rows], truncated
