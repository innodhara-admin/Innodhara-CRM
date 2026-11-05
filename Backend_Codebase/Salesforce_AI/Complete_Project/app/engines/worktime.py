"""Working-time math shared by every engine.

Reminders never fire on leave days or outside working hours; non-urgent sends
wait for the working window (org_settings dials, Data Model §2.2).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.models.organisation import OrgSettings
from app.models.user import User

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_hhmm(value: str, fallback: time) -> time:
    try:
        h, m = value.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return fallback


def working_weekdays(org: OrgSettings, user: User | None = None) -> set[int]:
    """Weekday numbers (Mon=0) that count as working days for this person."""
    labels = None
    if user is not None and user.working_days:
        labels = user.working_days
    elif org.working_days:
        labels = org.working_days
    if not labels:
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    return {DAY_LABELS.index(d) for d in labels if d in DAY_LABELS}


def is_on_leave(user: User | None, d: date) -> bool:
    if user is None or user.on_leave_from is None or user.on_leave_to is None:
        return False
    return user.on_leave_from <= d <= user.on_leave_to


def is_working_day(d: date, org: OrgSettings, user: User | None = None) -> bool:
    if d.weekday() not in working_weekdays(org, user):
        return False
    return not is_on_leave(user, d)


def add_working_days(start: date, n: int, org: OrgSettings, user: User | None = None) -> date:
    """The date n working days after start (skipping non-working and leave days)."""
    d = start
    remaining = n
    guard = 0
    while remaining > 0 and guard < 400:
        d = d + timedelta(days=1)
        guard += 1
        if is_working_day(d, org, user):
            remaining -= 1
    return d


def working_days_between(start: date, end: date, org: OrgSettings, user: User | None = None) -> int:
    """Whole working days strictly after start, up to and including end."""
    if end <= start:
        return 0
    d, count, guard = start, 0, 0
    while d < end and guard < 800:
        d = d + timedelta(days=1)
        guard += 1
        if is_working_day(d, org, user):
            count += 1
    return count


def next_working_moment(
    dt: datetime, org: OrgSettings, user: User | None = None
) -> datetime:
    """The earliest moment ≥ dt inside the working window on a working day."""
    start_t = parse_hhmm(org.workday_start, time(9, 0))
    end_t = parse_hhmm(org.workday_end, time(18, 30))
    moment = dt
    for _ in range(400):
        d = moment.date()
        if is_working_day(d, org, user):
            if moment.time() < start_t:
                return datetime.combine(d, start_t)
            if moment.time() <= end_t:
                return moment
        # Move to the start of the next day and retry.
        moment = datetime.combine(d + timedelta(days=1), start_t)
    return moment


def within_working_hours(dt: datetime, org: OrgSettings) -> bool:
    start_t = parse_hhmm(org.workday_start, time(9, 0))
    end_t = parse_hhmm(org.workday_end, time(18, 30))
    return (
        dt.weekday() in working_weekdays(org)
        and start_t <= dt.time() <= end_t
    )
