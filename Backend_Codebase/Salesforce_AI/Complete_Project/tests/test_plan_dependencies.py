"""A plan task that waits on another must be released when that one is done
(Ollama School of Commerce, 1 Oct 2026).

The Planner names a prerequisite by its title. Titles inside the plan's own
batch were always turned into ids; a title the batch no longer holds was
stored as it was. That happens when a fence removes the task after the model
wrote the plan: the recording's meeting ("Meeting with ... on Mon 05 Oct at
11:00", already scheduled, so the Planner's copy is dropped) or a duplicate of
a confirmed to-do. A title is never marked done, so the waiting task never got
an owner: tested on a copy of the live data, marking the meeting done left
"Design workbook content" unassigned, while a task linked by id was picked up
at once.

Now such a title is linked to the client's live task with exactly that title;
one that is already finished, or that does not exist, is not waited on.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.engines import planner_engine
from app.models.action_item import ActionItem
from app.models.project import Project
from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio

API = "/api/v1"
MEETING = "Meeting with Test Client on Mon 05 Oct at 11:00"


@pytest.fixture(autouse=True)
def _sync_reactor():
    """The test client skips app startup, which installs the Sync Engine."""
    from app.engines import events, sync_engine

    sync_engine.register()
    yield
    events.set_reactor(None)


@pytest.fixture
def staffed(monkeypatch):
    """Who gets a task is the assignment engine's call (skills, load,
    calendars), and a fresh test org has nobody with a recorded skill. What is
    under test here is whether a task is RELEASED for staffing, so the
    engine's pick is replaced by one that records the task and gives it to
    the org admin."""
    from app.engines import assignment_engine
    from app.models.user import User

    asked: list[str] = []

    async def pick(db, *, org_id, task, **_):
        asked.append(task.id)
        admin = (await db.execute(select(User).where(
            User.org_id == org_id, User.role == "org_admin"))).scalars().first()
        task.assignee_id = admin.id if admin else None
        return None

    monkeypatch.setattr(assignment_engine, "assign_task", pick)
    return asked


@pytest.fixture
async def org(client, super_token):
    tag = uuid.uuid4().hex[:8]
    org = await create_org(client, super_token, name=f"Deps {tag}",
                           slug=f"deps-{tag}", domain=f"deps{tag}-example.com")
    me = (await client.get(f"{API}/auth/me", headers=auth(org["admin_token"]))).json()
    org["admin_id"] = me["user_id"]
    return org


async def _setup(client, org, *, prerequisite_status="open"):
    """A client with one live task outside any plan (the scheduled meeting's
    own task), and a project to plan on."""
    lead = (await client.post(f"{API}/leads", headers=auth(org["admin_token"]),
                              json={"name": "Test Client"})).json()
    async with SessionLocal() as db:
        meeting_task = ActionItem(
            org_id=org["id"], lead_id=lead["id"], title=MEETING,
            assignee_id=org["admin_id"], status=prerequisite_status,
            created_by="system",
        )
        project = Project(org_id=org["id"], lead_id=lead["id"], name="Test work",
                          status="planning")
        db.add_all([meeting_task, project])
        await db.commit()
        return lead["id"], meeting_task.id, project.id


async def _plan(org, project_id, specs):
    async with SessionLocal() as db:
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()
        plan, _ = await planner_engine.create_plan_version(
            db, org_id=org["id"], project=project, trigger="manual", trigger_ref=None,
            summary="test", changes=["test"], new_tasks=specs,
        )
        await db.commit()
        rows = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.plan_version_added == plan.version))).scalars().all()
        return {r.title: r for r in rows}


def _spec(title, *deps, assign_on="when_ready"):
    return {"title": title, "phase": "preparation", "due_in_days": 5,
            "depends_on": list(deps), "assign_on": assign_on}


async def test_a_title_outside_the_batch_links_to_the_live_task(client, org):
    _lead, meeting_id, project_id = await _setup(client, org)
    rows = await _plan(org, project_id, [
        _spec("Design the workbook", MEETING),
        _spec("Print the workbook", "Design the workbook"),
    ])
    assert rows["Design the workbook"].depends_on_ids == [meeting_id]
    assert rows["Print the workbook"].depends_on_ids == [rows["Design the workbook"].id]
    assert rows["Design the workbook"].assignee_id is None, "it waits, as designed"


async def test_marking_the_prerequisite_done_gives_the_waiting_task_an_owner(
    client, org, staffed
):
    _lead, meeting_id, project_id = await _setup(client, org)
    rows = await _plan(org, project_id, [_spec("Design the workbook", MEETING)])
    waiting_id = rows["Design the workbook"].id
    assert waiting_id not in staffed, "it waits for the meeting, as designed"

    resp = await client.post(f"{API}/tasks/{meeting_id}/complete",
                             headers=auth(org["admin_token"]), json={})
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as db:
        waiting = (await db.execute(select(ActionItem).where(
            ActionItem.id == waiting_id))).scalar_one()
    assert waiting_id in staffed and waiting.assignee_id is not None, \
        "the task waiting on the meeting was not picked up when the meeting was done"


async def test_a_title_nothing_has_is_not_waited_on(client, org, staffed):
    _lead, _meeting_id, project_id = await _setup(client, org)
    rows = await _plan(org, project_id, [
        _spec("Design the workbook", "A task that was never written down"),
    ])
    task = rows["Design the workbook"]
    assert task.depends_on_ids == []
    assert task.id in staffed, "with nothing to wait for it is staffed at once"


async def test_a_title_already_finished_is_not_waited_on(client, org):
    _lead, _meeting_id, project_id = await _setup(client, org, prerequisite_status="done")
    rows = await _plan(org, project_id, [_spec("Design the workbook", MEETING)])
    assert rows["Design the workbook"].depends_on_ids == []


async def test_matching_ignores_case_and_spacing_but_not_other_clients(client, org):
    _lead, meeting_id, project_id = await _setup(client, org)
    other = (await client.post(f"{API}/leads", headers=auth(org["admin_token"]),
                               json={"name": "Another Client"})).json()
    async with SessionLocal() as db:
        db.add(ActionItem(org_id=org["id"], lead_id=other["id"], status="open",
                          title="Only on another client", created_by="system"))
        await db.commit()
    rows = await _plan(org, project_id, [
        _spec("Design the workbook", "  " + MEETING.upper() + " "),
        _spec("Unrelated", "Only on another client"),
    ])
    assert rows["Design the workbook"].depends_on_ids == [meeting_id]
    assert rows["Unrelated"].depends_on_ids == []


async def test_repair_relinks_stored_titles(client, org):
    """The same rule, applied to links already stored as titles."""
    lead_id, meeting_id, project_id = await _setup(client, org)
    async with SessionLocal() as db:
        broken = ActionItem(org_id=org["id"], lead_id=lead_id, project_id=project_id,
                            title="Waiting on a title", status="open",
                            assign_on="when_ready", depends_on_ids=[MEETING, "Gone task"],
                            created_by="ai")
        fine = ActionItem(org_id=org["id"], lead_id=lead_id, project_id=project_id,
                          title="Waiting on an id", status="open",
                          depends_on_ids=[meeting_id], created_by="ai")
        db.add_all([broken, fine])
        await db.commit()
        changed = await planner_engine.repair_title_dependencies(db, org_id=org["id"])
        await db.commit()
        await db.refresh(broken)
        await db.refresh(fine)
    assert [c["task_id"] for c in changed] == [broken.id]
    assert broken.depends_on_ids == [meeting_id]
    assert fine.depends_on_ids == [meeting_id]
