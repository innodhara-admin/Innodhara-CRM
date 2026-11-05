"""Resource & Calendar Engine — the single owner of "who and what is free
when", across ALL projects (30-Workflows §4, engine 3).

Leave, delivery days, demos, travel and holds all become resource_bookings
rows. The Assignment Engine counts these as busy time; the Planner's
feasibility passes query them. This is why nobody is ever booked in two
cities in one week.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.resource import ResourceBooking
from app.models.user import User

logger = logging.getLogger(__name__)

ENGINE = "resource_calendar"


def _to_dt(value: date | datetime, end: bool = False) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time(23, 59) if end else time(0, 0))


async def book(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    kind: str,
    date_from: date | datetime,
    date_to: date | datetime,
    project_id: str | None = None,
    source_type: str | None = None,
    source: str | None = None,
    note: str | None = None,
) -> ResourceBooking:
    """One claim on someone's time. Bookings are never created out of thin
    air — source_type/source say what created them."""
    row = ResourceBooking(
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        kind=kind,
        date_from=_to_dt(date_from),
        date_to=_to_dt(date_to, end=True),
        source_type=source_type,
        source=source,
        note=note,
    )
    db.add(row)
    await db.flush()
    return row


async def cancel_for_source(
    db: AsyncSession, *, org_id: str, source_type: str, source: str
) -> int:
    rows = (
        await db.execute(
            select(ResourceBooking).where(
                ResourceBooking.org_id == org_id,
                ResourceBooking.source_type == source_type,
                ResourceBooking.source == source,
            )
        )
    ).scalars().all()
    for r in rows:
        await db.delete(r)
    return len(rows)


async def bookings_in_window(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    date_from: date | datetime,
    date_to: date | datetime,
    exclude_kinds: tuple[str, ...] = (),
) -> list[ResourceBooking]:
    """All bookings of one person overlapping [date_from, date_to]."""
    start, end = _to_dt(date_from), _to_dt(date_to, end=True)
    stmt = select(ResourceBooking).where(
        ResourceBooking.org_id == org_id,
        ResourceBooking.user_id == user_id,
        ResourceBooking.date_from <= end,
        ResourceBooking.date_to >= start,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [r for r in rows if r.kind not in exclude_kinds]


async def conflicts_for(
    db: AsyncSession,
    *,
    org_id: str,
    user: User,
    date_from: date | datetime,
    date_to: date | datetime,
    treat_hold_as_busy: bool = False,
) -> list[str]:
    """Human-readable reasons this person is NOT free in the window.

    Checks the user's leave fields AND the master busy-calendar.
    """
    reasons: list[str] = []
    start_d = _to_dt(date_from).date()
    end_d = _to_dt(date_to, end=True).date()
    if user.on_leave_from and user.on_leave_to:
        if user.on_leave_from <= end_d and user.on_leave_to >= start_d:
            reasons.append(
                f"on leave {user.on_leave_from:%d %b}–{user.on_leave_to:%d %b}"
            )
    exclude = () if treat_hold_as_busy else ("hold",)
    for b in await bookings_in_window(
        db, org_id=org_id, user_id=user.id, date_from=date_from, date_to=date_to,
        exclude_kinds=exclude,
    ):
        reasons.append(
            f"{b.kind} booking {b.date_from:%d %b}–{b.date_to:%d %b}"
            + (f" (project {b.project_id})" if b.project_id else "")
        )
    return reasons


async def is_free(
    db: AsyncSession,
    *,
    org_id: str,
    user: User,
    date_from: date | datetime,
    date_to: date | datetime,
) -> bool:
    return not await conflicts_for(
        db, org_id=org_id, user=user, date_from=date_from, date_to=date_to
    )


async def feasibility(
    db: AsyncSession,
    *,
    org_id: str,
    users: list[User],
    date_from: date | datetime,
    date_to: date | datetime,
) -> dict[str, list[str]]:
    """The Planner's question: can these people work this window?

    Returns {user_id: [conflict reasons]} — empty lists mean feasible.
    """
    out: dict[str, list[str]] = {}
    for u in users:
        out[u.id] = await conflicts_for(
            db, org_id=org_id, user=u, date_from=date_from, date_to=date_to
        )
    return out


async def field_days_in_week(
    db: AsyncSession, *, org_id: str, user_id: str, around: date | None = None
) -> int:
    """How many field days (delivery/demo/travel) this person has in the week
    around a date — counted as busy time by the Assignment Engine."""
    around = around or clock.today(await clock.org_zone(db, org_id))
    week_start = around - timedelta(days=around.weekday())
    week_end = week_start + timedelta(days=6)
    rows = await bookings_in_window(
        db, org_id=org_id, user_id=user_id, date_from=week_start, date_to=week_end,
        exclude_kinds=("hold", "leave"),
    )
    days: set[str] = set()
    for b in rows:
        d = max(b.date_from.date(), week_start)
        stop = min(b.date_to.date(), week_end)
        while d <= stop:
            days.add(d.isoformat())
            d += timedelta(days=1)
    return len(days)


async def record_leave(
    db: AsyncSession,
    *,
    org_id: str,
    user: User,
    leave_from: date,
    leave_to: date,
) -> ResourceBooking:
    """Leave becomes both user fields (fast checks) and a booking row
    (the master calendar). The leave_recorded event is emitted by the caller."""
    user.on_leave_from = leave_from
    user.on_leave_to = leave_to
    return await book(
        db,
        org_id=org_id,
        user_id=user.id,
        kind="leave",
        date_from=leave_from,
        date_to=leave_to,
        source_type="leave",
        source=user.id,
        note="recorded leave",
    )
