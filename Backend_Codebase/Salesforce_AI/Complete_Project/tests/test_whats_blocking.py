"""Finding F43 — "What's blocking?" said nothing was blocking while the whole
plan was frozen.

Two observations, both deterministic and both reproduced here:

  * **Act 5** — the plan was held awaiting sign-off and 10 tasks were unstaffed.
    The answer was *"Nothing is blocking Orchid International School."*
  * **Act 11** — **4 open conflicts** were holding plan v5 in draft. The answer
    listed **16 OVERDUE rows and never mentioned the conflicts once.** Silently
    empty, then noisily wrong.

It consulted only `blocked=True` and overdue tasks — never the two things that
actually stop work: a decision nobody has taken, and a disagreement nobody has
resolved.

The correction recorded against F43 matters here: the good answer was **already
in the codebase**. The ops lead's Delivery card says *"4 unresolved conflict(s)
blocking a re-plan"*, computed by `sync_engine`. So the fix shares that ranking
rather than inventing a second one — the reason two surfaces disagreed is that
they each had their own idea of what "blocking" meant.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _project(client, org, name: str) -> str:
    from app.database import SessionLocal
    from app.models.project import Project

    lead = (
        await client.post("/api/v1/leads", headers=auth(org["admin_token"]),
                          json={"name": f"{name} Lead"})
    ).json()
    async with SessionLocal() as db:
        project = Project(
            org_id=org["id"], lead_id=lead["id"], name=name, status="preparation",
        )
        db.add(project)
        await db.flush()
        await db.commit()
        return project.id


async def _ask(org_id: str, project_id: str) -> str:
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.project import Project

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        return await assistant_engine.whats_blocking(
            db, org_id=org_id, project=project
        )


async def test_a_plan_frozen_behind_an_approval_is_reported(client, org_a):
    """Act 5's failure: the plan cannot move and the assistant says all is well."""
    from app.core.constants import ApprovalEntityType
    from app.database import SessionLocal
    from app.models.comms import Approval

    project_id = await _project(client, org_a, "F43 Frozen Plan Co")
    async with SessionLocal() as db:
        db.add(Approval(
            org_id=org_a["id"], project_id=project_id,
            entity_type=ApprovalEntityType.PLAN_CHANGE.value, entity_id="plan-1",
            status="pending", reason="Plan v1: initial plan awaiting sign-off",
        ))
        await db.commit()

    answer = await _ask(org_a["id"], project_id)
    assert "Nothing is blocking" not in answer, (
        f"F43: the plan is frozen awaiting a decision and the answer is "
        f"{answer!r}"
    )
    assert "awaiting sign-off" in answer, answer


async def test_open_conflicts_are_reported(client, org_a):
    """Act 11's failure: 4 conflicts holding a re-plan, never mentioned."""
    from app.core.constants import ConflictStatus
    from app.database import SessionLocal
    from app.models.project import Conflict

    project_id = await _project(client, org_a, "F43 Conflict Co")
    async with SessionLocal() as db:
        for i in range(4):
            db.add(Conflict(
                org_id=org_a["id"], project_id=project_id,
                status=ConflictStatus.OPEN.value,
                description=f"Two sources disagree about item {i}",
            ))
        await db.commit()

    answer = await _ask(org_a["id"], project_id)
    assert "Nothing is blocking" not in answer, answer
    assert "conflict" in answer.lower(), (
        f"4 open conflicts are holding the re-plan and the answer never says so: "
        f"{answer!r}"
    )
    assert "4" in answer, answer


async def test_a_held_replan_outranks_a_late_task(client, org_a):
    """Act 11's *shape*, not just its content.

    The old answer buried the real problem under 16 OVERDUE lines. A conflict
    holding the whole plan has to come before any single late task, or the fix
    is cosmetic.
    """
    from app.core.constants import ConflictStatus
    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.base import utcnow
    from app.models.project import Conflict
    from datetime import timedelta

    project_id = await _project(client, org_a, "F43 Ranking Co")
    async with SessionLocal() as db:
        db.add(Conflict(
            org_id=org_a["id"], project_id=project_id,
            status=ConflictStatus.OPEN.value, description="Scope disagreement",
        ))
        for i in range(3):
            db.add(ActionItem(
                org_id=org_a["id"], project_id=project_id,
                title=f"A late task {i}", priority="P2",
                due_date=utcnow() - timedelta(days=5),
            ))
        await db.commit()

    answer = await _ask(org_a["id"], project_id)
    lines = [ln for ln in answer.splitlines() if ln.startswith("- ")]
    assert lines, answer
    assert "CONFLICT" in lines[0].upper(), (
        f"the held re-plan is not the first thing said; a user reads the top of "
        f"the list: {lines[:3]}"
    )


async def test_a_genuinely_clear_project_still_says_so(client, org_a):
    """The control. A guard that always finds something to report is noise, and
    the honest empty state was one of the things Act 1 got RIGHT."""
    project_id = await _project(client, org_a, "F43 Clear Co")
    answer = await _ask(org_a["id"], project_id)
    assert "Nothing is blocking" in answer, answer


async def test_a_decided_approval_no_longer_blocks(client, org_a):
    """Only PENDING decisions block. Counting decided ones would make the
    answer permanently alarming."""
    from app.core.constants import ApprovalEntityType
    from app.database import SessionLocal
    from app.models.comms import Approval

    project_id = await _project(client, org_a, "F43 Decided Co")
    async with SessionLocal() as db:
        db.add(Approval(
            org_id=org_a["id"], project_id=project_id,
            entity_type=ApprovalEntityType.PLAN_CHANGE.value, entity_id="plan-9",
            status="approved", reason="Plan v2: already signed off",
        ))
        await db.commit()

    answer = await _ask(org_a["id"], project_id)
    assert "Nothing is blocking" in answer, answer


async def test_the_ranking_is_shared_with_the_delivery_card():
    """The durable half: one implementation, so the two surfaces cannot drift.

    F43's own correction retracted "conflicts appear in exactly two places" —
    the Delivery card names them, from `recompute_health`. If that ranking is
    ever re-inlined, the assistant and the card can disagree again.
    """
    import inspect

    from app.engines import assistant_engine, sync_engine

    assert hasattr(sync_engine, "health_signals"), (
        "the shared ranking is gone; whats_blocking and the Delivery card will "
        "drift apart again"
    )
    source = inspect.getsource(assistant_engine.whats_blocking)
    assert "health_signals" in source, (
        "whats_blocking has stopped reusing the Delivery card's ranking"
    )
