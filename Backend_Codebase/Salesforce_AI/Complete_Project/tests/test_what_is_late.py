"""Findings F52 and F53 — the product had no reliable answer to "what is late".

They fail in OPPOSITE directions, on the same data, in the same minute:

    task                                   Home briefing    My tasks
    Train facilitators (due TODAY)         Overdue  ❌      Today   ✅
    Design curriculum   (due 31 Jul)       Overdue  ✅      Today   ❌

**F52** — `today` compared DATES with `<=`, `overdue` compared DATETIMES with
`<`. Due dates are stored at midnight, so a task due today satisfied both. The
renderer guarded the "Due today:" header on `today` and filled it with
`[t for t in today if t not in overdue]` — structurally always empty. Every
morning printed a heading over nothing and called today's work late from 00:00.

**F53** — "My tasks" had only four buckets and no Overdue at all, so
`due <= today` swept five-day-late work under "Today".

They ship together: fixing either alone leaves the two screens contradicting
each other, which is the actual user-facing harm.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _task(org_id: str, user_id: str, title: str, days_offset: int | None):
    """A task due N days from today, at midnight — how the planner stores them."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.base import utcnow

    due = None
    if days_offset is not None:
        midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        due = midnight + timedelta(days=days_offset)
    async with SessionLocal() as db:
        item = ActionItem(
            org_id=org_id, title=title, assignee_id=user_id,
            priority="P2", due_date=due,
        )
        db.add(item)
        await db.flush()
        await db.commit()
        return item.id


async def _briefing(org_id: str, user_id: str) -> str:
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.user import User

    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one()
        digest = await assistant_engine.build_daily_digest(
            db, org_id=org_id, user=user
        )
        return digest.content_md


@pytest.fixture(scope="module")
async def briefing_user(client, org_a):
    """A user of their own, so other tests' tasks cannot colour the briefing."""
    from tests.conftest import login

    resp = await client.post(
        "/api/v1/admin/users", headers=auth(org_a["admin_token"]),
        json={"email": "f52.user@alpha-example.com", "name": "Late Larry",
              "role": "operations_agent"},
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    await login(client, created["email"], created["temp_password"])
    return created["id"]


async def test_a_task_due_today_is_not_called_overdue(client, org_a, briefing_user):
    """F52's headline: today's work announced as already late, from midnight."""
    await _task(org_a["id"], briefing_user, "Train and schedule facilitators", 0)
    text = await _briefing(org_a["id"], briefing_user)

    overdue_block = text.split("**Overdue:**")[1].split("**")[0] if "**Overdue:**" in text else ""
    assert "Train and schedule facilitators" not in overdue_block, (
        f"F52: a task due TODAY is announced as Overdue.\n{text}"
    )
    assert "**Due today:**" in text, text
    today_block = text.split("**Due today:**")[1].split("**")[0]
    assert "Train and schedule facilitators" in today_block, (
        f"F52: the 'Due today:' header rendered over empty space.\n{text}"
    )


async def test_the_due_today_header_is_never_empty(client, org_a, briefing_user):
    """The header was guarded on one list and filled from another, so it was
    *structurally* impossible for it to have content."""
    await _task(org_a["id"], briefing_user, "Something due today", 0)
    text = await _briefing(org_a["id"], briefing_user)
    assert "**Due today:**" in text
    body = text.split("**Due today:**")[1].split("**")[0].strip()
    assert body, f"the 'Due today:' header still renders over nothing:\n{text}"


async def test_genuinely_late_work_is_still_called_overdue(client, org_a, briefing_user):
    """The control. A fix that simply stopped saying Overdue would pass the two
    tests above and destroy the briefing's real job."""
    await _task(org_a["id"], briefing_user, "Design workshop curriculum", -5)
    text = await _briefing(org_a["id"], briefing_user)
    assert "**Overdue:**" in text, text
    overdue_block = text.split("**Overdue:**")[1].split("**")[0]
    assert "Design workshop curriculum" in overdue_block, (
        f"five-day-late work is no longer reported as overdue.\n{text}"
    )


async def test_today_and_overdue_never_overlap(client, org_a, briefing_user):
    """The root cause was two lists that were meant to partition and did not."""
    await _task(org_a["id"], briefing_user, "Late one", -3)
    await _task(org_a["id"], briefing_user, "Today one", 0)
    await _task(org_a["id"], briefing_user, "Future one", 4)
    text = await _briefing(org_a["id"], briefing_user)

    overdue_block = text.split("**Overdue:**")[1].split("**")[0]
    today_block = text.split("**Due today:**")[1].split("**")[0]
    assert "Late one" in overdue_block and "Late one" not in today_block
    assert "Today one" in today_block and "Today one" not in overdue_block
    assert "Future one" not in overdue_block and "Future one" not in today_block


async def test_the_sync_engine_ladder_was_deliberately_left_alone():
    """⚠ The trap, pinned so nobody "finishes the job" and breaks the ladder.

    Workflow 10 defines the reminder ladder's overdue as `action_items.due_date <
    now` ON PURPOSE: that sweep runs at 18:00, the workday end, where "due today
    and still not done" genuinely IS overdue. Applying F52's local-date fix there
    would stop the ladder ever chasing same-day work.
    """
    import inspect

    from app.engines import sync_engine

    source = inspect.getsource(sync_engine)
    assert "ActionItem.due_date < now" in source, (
        "the Sync Engine's end-of-day ladder no longer uses `due_date < now` — "
        "if F52's fix was propagated here, same-day work stopped being chased"
    )
