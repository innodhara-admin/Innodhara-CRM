"""A demo the client asks to move, in a MEETING, must actually move.

Found live 2026-08-06 on the datacentre demo build:

    "I booked a demo on 9 August. I recorded a meeting where the client said
     'please shift the demo to 15 August'. The planner made a merge plan, the
     demo date did NOT shift, and something else got shifted."

Two causes, both structural:

  1. `VALID_OPS` had no op that could move a demo. The vocabulary was
     redate (a TASK), cancel, reopen, unblock, set_window, renegotiate_commitment.
     So the nearest expressible thing was `redate` on whatever task happened to
     mention the word "demo" — which is the "something else" that moved.
  2. The merge snapshot never showed demos at all, so the model could not even
     name the demo it was being asked to move.

Meanwhile the reschedule machinery was complete and correct — behind the app's
Reschedule button. Fourth instance of the F41 / F54 / F56 pattern: machinery
that exists, works, and is wired to exactly one entry point.

The fix is deliberately NOT "let redate touch demos". Moving a demo has to send
the client an updated calendar invite; a task re-date must not.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _project_with_demo(client, org, name: str):
    from app.database import SessionLocal
    from app.models.demo import Demo
    from app.models.project import ActionPlan, Project

    lead = (
        await client.post("/api/v1/leads", headers=auth(org["admin_token"]),
                          json={"name": f"{name} Client"})
    ).json()
    async with SessionLocal() as db:
        project = Project(org_id=org["id"], lead_id=lead["id"], name=name,
                          status="preparation", current_plan_version=1)
        db.add(project)
        await db.flush()
        demo = Demo(org_id=org["id"], lead_id=lead["id"],
                    scheduled_date=date(2026, 8, 9), scheduled_time="10:00",
                    status="scheduled")
        db.add(demo)
        plan = ActionPlan(org_id=org["id"], project_id=project.id, version=2,
                          status="pending_review", summary="merge",
                          trigger="new_meeting")
        db.add(plan)
        await db.flush()
        ids = (project.id, demo.id, plan.id)
        await db.commit()
        return ids


async def test_the_demo_actually_moves(client, org_a):
    """The headline. 9 Aug -> 15 Aug, on the demo row itself."""
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.demo import Demo
    from app.models.project import ActionPlan

    _pid, demo_id, plan_id = await _project_with_demo(client, org_a, "DC Demo Move")
    async with SessionLocal() as db:
        plan = (
            await db.execute(select(ActionPlan).where(ActionPlan.id == plan_id))
        ).scalar_one()
        plan.pending_ops = [
            {"op": "reschedule_demo", "demo_id": demo_id,
             "new_date": "2026-08-15", "new_time": "14:30"}
        ]
        await db.commit()

    async with SessionLocal() as db:
        await planner_engine.activate_plan(
            db, org_id=org_a["id"], plan_id=plan_id, approved_by=org_a["agent_id"],
        )
        await db.commit()

    async with SessionLocal() as db:
        demo = (
            await db.execute(select(Demo).where(Demo.id == demo_id))
        ).scalar_one()
    assert demo.scheduled_date == date(2026, 8, 15), (
        f"the client asked for the 15th and the demo is still on "
        f"{demo.scheduled_date} — this is the bug"
    )
    assert demo.scheduled_time == "14:30"


async def test_the_client_is_told_the_demo_moved(client, org_a):
    """Moving the date and NOT re-inviting would be the worse bug — the client
    keeps a calendar entry for a day nobody is coming."""
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.lead import Contact
    from app.models.messaging import OutboundMessage
    from app.models.project import ActionPlan

    _pid, demo_id, plan_id = await _project_with_demo(client, org_a, "DC Demo Invite")
    async with SessionLocal() as db:
        demo_lead = (
            await db.execute(
                select(ActionPlan).where(ActionPlan.id == plan_id)
            )
        ).scalar_one()
        from app.models.demo import Demo

        d = (await db.execute(select(Demo).where(Demo.id == demo_id))).scalar_one()
        db.add(Contact(org_id=org_a["id"], lead_id=d.lead_id, name="Kavitha Rao",
                       email="kavitha@dc.test", is_primary=True))
        demo_lead.pending_ops = [
            {"op": "reschedule_demo", "demo_id": demo_id, "new_date": "2026-08-15"}
        ]
        await db.commit()

    async with SessionLocal() as db:
        await planner_engine.activate_plan(
            db, org_id=org_a["id"], plan_id=plan_id, approved_by=org_a["agent_id"],
        )
        await db.commit()

    async with SessionLocal() as db:
        msgs = (
            await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.to_address == "kavitha@dc.test"
                )
            )
        ).scalars().all()
    assert msgs, "the demo moved and the client was never told"
    assert all(m.status == "pending_approval" for m in msgs), (
        "an updated invite was sent without a human tap"
    )


async def test_an_unknown_demo_id_is_dropped_not_guessed():
    """A demo move sends the client a calendar update, so a hallucinated id must
    never get through validation."""
    from app.ai.planning import validate_ops

    ops = validate_ops(
        [{"op": "reschedule_demo", "demo_id": "does-not-exist",
          "new_date": "2026-08-15"}],
        known_task_ids=set(), known_commitment_ids=set(),
        known_demo_ids={"the-real-one"},
    )
    assert ops == [], "an invented demo id survived validation"


async def test_a_vague_date_is_dropped():
    """'next week' is not a date. Dropping it is better than guessing one and
    telling the client to turn up."""
    from app.ai.planning import validate_ops

    for bad in ("next week", "", None, "soon"):
        ops = validate_ops(
            [{"op": "reschedule_demo", "demo_id": "d1", "new_date": bad}],
            known_task_ids=set(), known_commitment_ids=set(),
            known_demo_ids={"d1"},
        )
        assert ops == [], f"{bad!r} was accepted as a demo date"


async def test_the_model_is_told_not_to_redate_a_task_instead():
    """The guard on the actual failure mode. Without this instruction the model
    reaches for `redate` on a task whose title mentions the demo — which moves
    our internal to-do and leaves the client's invite untouched."""
    from app.ai.planning import _MERGE_SYSTEM, VALID_OPS

    assert "reschedule_demo" in VALID_OPS
    prompt = _MERGE_SYSTEM.lower()
    assert "reschedule_demo" in prompt, "the merge prompt never offers the op"
    assert "redate" in prompt and "demo" in prompt
    assert "calendar invite" in prompt, (
        "the prompt does not say WHY a task re-date is the wrong tool here"
    )


async def test_the_merge_snapshot_shows_demos():
    """A demo the model cannot see is a demo it cannot move — and the id has to
    be there, or `demo_id` can only ever be invented."""
    import inspect

    from app.ai import planning

    src = inspect.getsource(planning.generate_plan_merge)
    assert "Scheduled demos" in src, (
        "the merge snapshot lists no demos, so the model cannot reference one"
    )
    assert "d.id" in src, "the snapshot lists demos without their ids"
