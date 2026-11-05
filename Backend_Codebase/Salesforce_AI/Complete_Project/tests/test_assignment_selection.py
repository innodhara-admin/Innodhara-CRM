"""Confirming assignments a lead picks, and saying whose client each is
(2 Oct 2026).

The confirm screen showed every proposed assignment as one batch with no
client on it, so a lead confirming today's client also confirmed an older
client's work. Now each row names its client (the task's own, else its
project's -- the Home briefing's rule), only the ticked ids are confirmed,
and an id that was already decided is never decided (or notified) again.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.conftest import auth, create_org, fresh_lead

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def org(client, super_token):
    """An org of its own: GET /assignments/proposed is org-wide, so rows
    other tests leave proposed would otherwise show up here."""
    out = await create_org(
        client, super_token,
        name="Selection Org", slug="selection-org", domain="selection-example.com",
    )
    resp = await client.post(
        "/api/v1/admin/users", headers=auth(out["admin_token"]),
        json={"email": "doer@selection-example.com", "name": "Dev Doer",
              "role": "operations_agent"},
    )
    assert resp.status_code == 200, resp.text
    out["doer_id"] = resp.json()["id"]
    return out


async def _proposed(org: dict, *, title: str, lead_id: str | None = None,
                    project_id: str | None = None) -> str:
    """A task and its proposed assignment, as lead_confirm mode leaves them."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.work import Assignment

    async with SessionLocal() as db:
        task = ActionItem(org_id=org["id"], title=title, lead_id=lead_id,
                          project_id=project_id, assignee_id=org["doer_id"],
                          priority="P2", status="open")
        db.add(task)
        await db.flush()
        row = Assignment(org_id=org["id"], action_item_id=task.id,
                         to_user_id=org["doer_id"], assigned_by="ai",
                         reason="best skill match", status="proposed")
        db.add(row)
        await db.commit()
        return row.id


async def _project(org: dict, lead_id: str, name: str) -> str:
    from app.database import SessionLocal
    from app.models.project import Project

    async with SessionLocal() as db:
        project = Project(org_id=org["id"], lead_id=lead_id, name=name)
        db.add(project)
        await db.commit()
        return project.id


async def _status(assignment_id: str) -> str:
    from app.database import SessionLocal
    from app.models.work import Assignment

    async with SessionLocal() as db:
        return (await db.execute(
            select(Assignment.status).where(Assignment.id == assignment_id)
        )).scalar_one()


async def _told(org: dict) -> int:
    from app.database import SessionLocal
    from app.models.user import Notification

    async with SessionLocal() as db:
        return (await db.execute(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == org["doer_id"],
                Notification.kind == "task_assigned",
            )
        )).scalar_one()


async def _rows(client, org: dict) -> dict:
    resp = await client.get("/api/v1/assignments/proposed",
                            headers=auth(org["admin_token"]))
    assert resp.status_code == 200, resp.text
    return {r["id"]: r for r in resp.json()}


async def test_each_proposed_assignment_names_its_client(client, org):
    acme = await fresh_lead(client, org["admin_token"], "Acme Selection")
    beta = await fresh_lead(client, org["admin_token"], "Beta Selection")
    project_id = await _project(org, beta["id"], "Beta rollout")

    own = await _proposed(org, title="Send Acme the kit list", lead_id=acme["id"])
    via_project = await _proposed(org, title="Plan Beta training",
                                  project_id=project_id)
    nobody = await _proposed(org, title="Tidy the shared drive")

    rows = await _rows(client, org)
    assert rows[own]["lead_id"] == acme["id"]
    assert rows[own]["lead_name"] == acme["name"]
    # No lead on the task itself: the project's client, as on Home.
    assert rows[via_project]["lead_id"] == beta["id"]
    assert rows[via_project]["lead_name"] == beta["name"]
    assert rows[via_project]["project_name"] == "Beta rollout"
    assert rows[nobody]["lead_id"] is None
    assert rows[nobody]["lead_name"] is None
    # What the screen already rendered is unchanged.
    assert rows[own]["task_title"] == "Send Acme the kit list"
    assert rows[own]["reason"] == "best skill match"


async def test_only_the_ticked_assignments_are_confirmed(client, org):
    lead = await fresh_lead(client, org["admin_token"], "Gamma Selection")
    first = await _proposed(org, title="Gamma one", lead_id=lead["id"])
    second = await _proposed(org, title="Gamma two", lead_id=lead["id"])
    older = await _proposed(org, title="Older client's task", lead_id=lead["id"])

    resp = await client.post(
        "/api/v1/assignments/confirm-batch", headers=auth(org["admin_token"]),
        json={"assignment_ids": [first, second]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"confirmed": 2}
    assert await _status(first) == "accepted"
    assert await _status(second) == "accepted"
    assert await _status(older) == "proposed"
    assert older in await _rows(client, org)
    assert first not in await _rows(client, org)


async def test_a_decided_assignment_is_not_confirmed_or_announced_twice(client, org):
    lead = await fresh_lead(client, org["admin_token"], "Delta Selection")
    once = await _proposed(org, title="Delta once", lead_id=lead["id"])

    first = await client.post(
        "/api/v1/assignments/confirm-batch", headers=auth(org["admin_token"]),
        json={"assignment_ids": [once]},
    )
    assert first.json() == {"confirmed": 1}
    told = await _told(org)

    # A double tap, or a second phone with the old list on screen.
    again = await client.post(
        "/api/v1/assignments/confirm-batch", headers=auth(org["admin_token"]),
        json={"assignment_ids": [once]},
    )
    assert again.status_code == 200, again.text
    assert again.json() == {"confirmed": 0}
    assert await _status(once) == "accepted"
    assert await _told(org) == told, "the assignee was told twice"
