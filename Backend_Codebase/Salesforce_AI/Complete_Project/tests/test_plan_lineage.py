"""Finding F49 — a superseded plan kept a live approval, and approving it rolled
the project backwards over a merge.

Two code paths supersede a plan. The planner's own sweep is careful: it expires
the plan's pending approvals, un-queues any message bundled on them, supersedes
the never-activated tasks and notifies the approver. The inbound date-shift
handler set `status = superseded` and stopped.

Worse than an omission: flipping the status early also *blinded* the careful
sweep, which only selects plans still in DRAFT/PENDING_REVIEW. The orphan it left
could never be cleaned up by any later sweep.

This was executed for real on 2026-08-05 — a stale v2 card was approved, v2 went
active over v4, `current_plan_version` fell 4 → 2, and the damage did not fully
self-heal (five tasks the rollback released stayed open after the pointer was
repaired). Data Model §4.3 makes it a correctness matter, not a tidiness one:
`superseded` means "replaced by a **newer** version" and `current_plan_version`
means "which version is live **right now**" — both were false.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _project(client, org, name: str):
    """A bare project to hang plan versions off."""
    from app.database import SessionLocal
    from app.models.project import Project

    lead = (
        await client.post("/api/v1/leads", headers=auth(org["admin_token"]),
                          json={"name": f"{name} Lead"})
    ).json()
    async with SessionLocal() as db:
        project = Project(
            org_id=org["id"], lead_id=lead["id"], name=name,
            status="preparation", current_plan_version=0,
        )
        db.add(project)
        await db.flush()
        await db.commit()
        return project.id


async def _plan(org_id: str, project_id: str, version: int, status: str):
    from app.database import SessionLocal
    from app.models.project import ActionPlan

    async with SessionLocal() as db:
        plan = ActionPlan(
            org_id=org_id, project_id=project_id, version=version,
            status=status, summary=f"v{version}", trigger="client_reply",
        )
        db.add(plan)
        await db.flush()
        await db.commit()
        return plan.id


async def test_activating_an_older_plan_over_a_newer_one_is_refused(client, org_a):
    """The safety net. This is the exact move that damaged the real project."""
    from app.core.exceptions import ConflictError
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.project import ActionPlan, Project

    project_id = await _project(client, org_a, "F49 Rollback Co")
    stale_id = await _plan(org_a["id"], project_id, 2, "pending_review")
    await _plan(org_a["id"], project_id, 4, "active")

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        project.current_plan_version = 4
        await db.commit()

    async with SessionLocal() as db:
        with pytest.raises(ConflictError) as err:
            await planner_engine.activate_plan(
                db, org_id=org_a["id"], plan_id=stale_id, approved_by="tester",
            )
    # The refusal must name both versions or the approver cannot act on it.
    assert "v2" in str(err.value) and "v4" in str(err.value), str(err.value)

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        v4 = (
            await db.execute(
                select(ActionPlan).where(
                    ActionPlan.project_id == project_id, ActionPlan.version == 4
                )
            )
        ).scalar_one()
    assert project.current_plan_version == 4, (
        "the pointer moved backwards — this is the exact F49 damage"
    )
    assert v4.status == "active", "the live plan was superseded by an older one"


async def test_pointer_ahead_with_nothing_active_is_also_refused(client, org_a):
    """The shape the first guard cannot see.

    `newer_active_plan` looks for a newer plan that is ACTIVE. A newer version
    can be retired without a replacement activating, leaving nothing ACTIVE while
    `current_plan_version` still points forward. Asked "is this the newest?", the
    first check would answer yes. The Data Model calls
    `current_plan_version` "which version is live right now", so it gets its own
    vote.
    """
    from app.core.exceptions import ConflictError
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.project import Project

    project_id = await _project(client, org_a, "F49 Pointer Co")
    stale_id = await _plan(org_a["id"], project_id, 2, "pending_review")
    await _plan(org_a["id"], project_id, 5, "superseded")  # newer, but NOT active

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        project.current_plan_version = 5
        await db.commit()

    async with SessionLocal() as db:
        with pytest.raises(ConflictError) as err:
            await planner_engine.activate_plan(
                db, org_id=org_a["id"], plan_id=stale_id, approved_by="tester",
            )
    assert "backwards" in str(err.value).lower(), str(err.value)


async def test_activating_a_newer_plan_still_works(client, org_a):
    """The control. A guard that refuses everything would pass the test above."""
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.project import Project

    project_id = await _project(client, org_a, "F49 Forward Co")
    await _plan(org_a["id"], project_id, 1, "active")
    newer_id = await _plan(org_a["id"], project_id, 2, "pending_review")

    async with SessionLocal() as db:
        plan = await planner_engine.activate_plan(
            db, org_id=org_a["id"], plan_id=newer_id, approved_by="tester",
        )
        await db.commit()
    assert plan.status == "active"

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
    assert project.current_plan_version == 2


async def test_retiring_a_plan_expires_its_pending_approval(client, org_a):
    """The root cause: superseding a plan must take its approval card with it.

    F49's orphan was tappable in the queue with no decision_note, indistinguishable
    from a live request.
    """
    from app.core.constants import ApprovalEntityType
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.comms import Approval
    from app.models.project import ActionPlan, Project

    project_id = await _project(client, org_a, "F49 Orphan Co")
    old_id = await _plan(org_a["id"], project_id, 1, "pending_review")

    async with SessionLocal() as db:
        approval = Approval(
            org_id=org_a["id"], project_id=project_id,
            entity_type=ApprovalEntityType.PLAN_CHANGE.value, entity_id=old_id,
            status="pending", reason="Plan v1: scope expansion",
        )
        db.add(approval)
        await db.flush()
        approval_id = approval.id
        await db.commit()

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        old = (
            await db.execute(select(ActionPlan).where(ActionPlan.id == old_id))
        ).scalar_one()
        retired = await planner_engine.retire_superseded_plan(
            db, org_id=org_a["id"], project=project, old=old,
            replaced_by_label="a newer client instruction",
            decision_reason="test",
        )
        await db.commit()
    assert retired is True

    async with SessionLocal() as db:
        row = (
            await db.execute(select(Approval).where(Approval.id == approval_id))
        ).scalar_one()
    assert row.status == "expired", (
        "F49: the plan was superseded but its approval stayed pending — still "
        "tappable, and approving it rolls the project backwards"
    )
    assert row.decision_note, "an expired card with no note looks like a bug to the approver"


async def test_a_conflict_held_plan_is_never_retired(client, org_a):
    """The exemption, now living inside the shared helper.

    It used to sit in the *caller*, which is precisely how the two supersede
    paths came to disagree. Round 7 left a real plan in this state (v5, held by
    4 open conflicts), so a regression here would destroy live evidence.
    """
    from app.core.constants import ConflictStatus
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.project import ActionPlan, Conflict, Project

    project_id = await _project(client, org_a, "F49 Held Co")
    held_id = await _plan(org_a["id"], project_id, 5, "draft")

    async with SessionLocal() as db:
        db.add(Conflict(
            org_id=org_a["id"], project_id=project_id, held_plan_id=held_id,
            status=ConflictStatus.OPEN.value,
            description="Two sources said different things about the dates",
        ))
        await db.commit()

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        held = (
            await db.execute(select(ActionPlan).where(ActionPlan.id == held_id))
        ).scalar_one()
        retired = await planner_engine.retire_superseded_plan(
            db, org_id=org_a["id"], project=project, old=held,
            replaced_by_label="plan v6", decision_reason="test",
        )
        await db.commit()

    assert retired is False, "a conflict-held plan was collapsed"
    async with SessionLocal() as db:
        row = (
            await db.execute(select(ActionPlan).where(ActionPlan.id == held_id))
        ).scalar_one()
    assert row.status == "draft", (
        "a plan frozen for a named human was superseded behind their back"
    )
