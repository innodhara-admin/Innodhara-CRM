"""Field map (spec 6.8): where the sales team was when they opened the app on
one day.

A reading is taken only when a sales agent or a sales lead opens the app or
brings it back to the screen, never in the background, so a reading is not a
client visit and the screen says so. This reads the same rows as the org
admin's map through `location_service.point_out`, and changes nothing about
who may read them there (`track_locations` stays the org admin's).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import clock
from app.core.exceptions import NotFoundError
from app.insights import common
from app.models.location import (STATUS_DENIED, STATUS_GPS_OFF, STATUS_OK, STATUS_TIMEOUT,
                                 LocationPing)
from app.models.user import User
from app.services import location_service

FRESH = timedelta(minutes=60)
NOTE = ("Readings are taken only when someone opens the app. This is not live tracking. "
        "Readings are kept for 90 days.")
TOO_OLD = "Readings are kept for 90 days."
STATUS_TEXT = {
    STATUS_DENIED: "Location permission refused",
    STATUS_GPS_OFF: "GPS was off",
    STATUS_TIMEOUT: "No fix in time",
}


def _retention_days() -> int:
    return int(getattr(get_settings(), "location_retention_days", 90) or 90)


async def _readings(db, org_id, tz, day, user_id=None) -> list[LocationPing]:
    start, end = common.day_bounds_utc(day, tz)
    query = select(LocationPing).where(LocationPing.org_id == org_id,
                                       LocationPing.captured_at >= start,
                                       LocationPing.captured_at < end)
    if user_id:
        query = query.where(LocationPing.user_id == user_id)
    return list((await db.execute(query.order_by(LocationPing.captured_at))).scalars().all())


def _too_old(day: date, today: date) -> bool:
    return day < today - timedelta(days=_retention_days()) or day > today


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, day: date) -> dict:
    today = common.local_day(now, tz)
    style = common.block(style_url=get_settings().location_map_style_dark)
    people = (await db.execute(
        select(User).where(User.org_id == org_id, User.role.in_(location_service.TRACKED_ROLES),
                           User.is_active.is_(True)).order_by(User.name)
    )).scalars().all()
    empty_trust = {k: 0 for k in ("ok", "gps_off", "timeout", "permission_denied", "mock",
                                  "approximate")}
    if _too_old(day, today):
        return {"map": style,
                "people": common.block("empty", TOO_OLD, items=[]),
                "trust": common.block("empty", TOO_OLD, **empty_trust),
                "hours": common.block("empty", TOO_OLD, counts=[0] * 24),
                "note": NOTE}

    readings = await _readings(db, org_id, tz, day)
    mine: dict[str, list[LocationPing]] = {}
    for p in readings:
        mine.setdefault(p.user_id, []).append(p)
    items = []
    for person in people:
        rows = mine.get(person.id, [])
        ok = [p for p in rows if p.status == STATUS_OK]
        latest = ok[-1] if ok else None
        if not rows:
            note = "Not seen today" if day == today else "Not seen on this day"
        elif latest is None:
            note = STATUS_TEXT.get(rows[-1].status, "No position")
        elif any(p.is_mock for p in rows):
            note = "A reading came from a fake GPS app"
        elif latest.approximate:
            note = "Approximate location only"
        else:
            note = None
        items.append({
            "user_id": person.id, "name": person.name, "role": person.role,
            "latest": None if latest is None else {
                "lat": latest.lat, "lng": latest.lng, "at": common.iso_utc(latest.captured_at),
                "approximate": bool(latest.approximate)},
            "fresh": bool(latest is not None and day == today
                          and now - latest.captured_at <= FRESH),
            "readings": len(rows),
            "first": common.iso_utc(rows[0].captured_at) if rows else None,
            "last": common.iso_utc(rows[-1].captured_at) if rows else None,
            "status_note": note,
        })
    if not people:
        people_block = common.block("empty", "Nobody on the team sends field readings.",
                                    items=[])
    elif not readings:
        people_block = common.block("ok", "Nobody has opened the app on this day yet.",
                                    items=items)
    else:
        people_block = common.block(items=items)

    trust = dict(empty_trust)
    hours = [0] * 24
    for p in readings:
        trust[p.status if p.status in trust else "ok"] += 1
        trust["mock"] += int(bool(p.is_mock))
        trust["approximate"] += int(bool(p.approximate))
        hours[clock.to_local(p.captured_at, tz).hour] += 1
    if readings:
        trust_block, hours_block = common.block(**trust), common.block(counts=hours)
    else:
        trust_block = common.block("empty", "No readings on this day.", **trust)
        hours_block = common.block("empty", "No readings on this day.", counts=hours)
    return {"map": style, "people": people_block, "trust": trust_block, "hours": hours_block,
            "note": NOTE}


async def person(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, user_id: str,
                 day: date) -> dict:
    user = (await db.execute(
        select(User).where(User.org_id == org_id, User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise NotFoundError("Person not found")
    today = common.local_day(now, tz)
    if _too_old(day, today):
        return common.block("empty", TOO_OLD, user_id=user.id, name=user.name, trail=[],
                            first=None, last=None, readings=0)
    rows = await _readings(db, org_id, tz, day, user_id=user.id)
    trail = [{"lat": p["lat"], "lng": p["lng"], "at": common.iso_utc(
                 datetime.fromisoformat(p["captured_at"]))}
             for p in map(location_service.point_out, rows) if p["status"] == STATUS_OK]
    fields = dict(user_id=user.id, name=user.name, trail=trail,
                  first=common.iso_utc(rows[0].captured_at) if rows else None,
                  last=common.iso_utc(rows[-1].captured_at) if rows else None,
                  readings=len(rows))
    if not trail:
        return common.block("empty", "No positions from this person on this day.", **fields)
    return common.block(**fields)
