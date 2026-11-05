"""Every date judgement is made in the organisation's timezone.

The moment is pinned by patching `clock.now`, so these assert what the engines
do *with a clock* rather than what the wall clock happens to be — and the pinned
moment is deliberately far from the real one, so an implementation still reading
the server's own date cannot pass by coincidence. `test_clock.py` tests the
clock itself against the real one.

    pinned now   2027-03-15 19:30 UTC  =  2027-03-16 01:00 Asia/Kolkata

    DUE_SOON     2027-03-15 20:00 UTC  =  2027-03-16 01:30 IST
                 due in thirty minutes; its UTC date is the 15th and the
                 reader's is the 16th, which is the whole defect

    DUE_EARLIER  2027-03-15 10:00 UTC  =  2027-03-15 15:30 IST
                 the same calendar day in UTC, *yesterday* in Kolkata — the two
                 zones must disagree about it, which is what proves the
                 organisation's own setting is being read
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.constants import ActionItemStatus, TaskPriority
from app.database import SessionLocal
from app.engines import assistant_engine
from app.models.action_item import ActionItem
from app.models.user import User
from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio

NOW_UTC = datetime(2027, 3, 15, 19, 30, tzinfo=timezone.utc)
DUE_SOON = datetime(2027, 3, 15, 20, 0)
DUE_EARLIER = datetime(2027, 3, 15, 10, 0)
LONG_PAST = datetime(2027, 3, 8, 6, 0)


@pytest.fixture(autouse=True)
def _pin_now(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda tz: NOW_UTC.astimezone(tz))


async def _org_with_task(client, super_token, slug, due, *, tz=None):
    org = await create_org(client, super_token, name=f"Clock {slug}",
                           slug=slug, domain=f"{slug}-example.com")
    if tz:
        resp = await client.patch("/api/v1/admin/settings",
                                  headers=auth(org["admin_token"]),
                                  json={"timezone": tz})
        assert resp.status_code == 200, resp.text
    me = (await client.get("/api/v1/auth/me",
                           headers=auth(org["admin_token"]))).json()
    async with SessionLocal() as db:
        db.add(ActionItem(
            org_id=org["id"], assignee_id=me["user_id"],
            title="Call the client back", priority=TaskPriority.P1.value,
            status=ActionItemStatus.OPEN.value, due_date=due,
        ))
        await db.commit()
        user = (await db.execute(
            select(User).where(User.id == me["user_id"]))).scalar_one()
        digest = await assistant_engine.build_daily_digest(
            db, org_id=org["id"], user=user)
    return digest.content_md


def _bucket(body: str) -> str:
    for heading in ("**Overdue:**", "**Due today:**", "**Coming up:**"):
        if heading in body:
            return heading
    return "(none)"


async def test_a_task_due_in_thirty_minutes_is_not_overdue(client, super_token):
    body = await _org_with_task(client, super_token, "clock-soon", DUE_SOON)
    assert _bucket(body) == "**Due today:**"


async def test_a_task_that_really_is_late_is_still_overdue(client, super_token):
    """The fix must not simply stop calling anything overdue."""
    body = await _org_with_task(client, super_token, "clock-late", LONG_PAST)
    assert _bucket(body) == "**Overdue:**"


async def test_kolkata_and_utc_disagree_about_the_same_instant(client, super_token):
    """One row, two organisations, two timezones, two correct answers.

    In Kolkata the 15th finished an hour and a half ago, so 15:30 IST on the
    15th is yesterday's work. In UTC it is still the 15th, so the same instant
    is today's. An implementation reading the server's own date returns the same
    answer to both, which is how this fails.
    """
    kolkata = await _org_with_task(client, super_token, "clock-ist", DUE_EARLIER)
    utc = await _org_with_task(client, super_token, "clock-utc", DUE_EARLIER,
                               tz="UTC")
    assert _bucket(kolkata) == "**Overdue:**"
    assert _bucket(utc) == "**Due today:**"


async def test_a_bad_timezone_falls_back_instead_of_breaking_the_briefing(
    client, super_token
):
    body = await _org_with_task(client, super_token, "clock-bad", DUE_SOON,
                                tz="Not/AZone")
    assert _bucket(body) == "**Due today:**"
