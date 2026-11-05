"""Finding F51 — the task-lifecycle router enforced ownership on one action of 23.

Round 7 Act 12, device-proven: as Sourav (operations_agent, NOT the assignee) I
opened a task now assigned to Mithun and blocked it. `POST /tasks/{id}/block`
returned 200 OK, `blocked_reason` was stored, and `progress_events.actor`
recorded Sourav against Mithun's task. No refusal, no warning.

`/decline` had an inline assignee check eleven lines away; nothing else on the
router checked anything, and `workflow.py` was the only API module that never
called `require_permission` at all.

Two different controls are missing, and conflating them is how the obvious fix
fails:

  * the task lifecycle needs **ownership** — `require_permission("manage_tasks")`
    would NOT have stopped Sourav, because that permission grants all five org
    roles;
  * `/assignments/confirm-batch` needs a **role** — `lead_confirm` means the
    phase lead signs off the batch, and the route was open to any member.

`/complete` and `/progress` stay open by decision: covering for a colleague who
finished the work is teamwork, not a privilege escalation.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth, login

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def crew(client, org_a):
    """Two operations agents and one operations lead in the same org."""
    out = {"org_id": org_a["id"]}
    for key, email, role in (
        ("owner", "f51.owner@alpha-example.com", "operations_agent"),
        ("other", "f51.other@alpha-example.com", "operations_agent"),
        ("lead", "f51.lead@alpha-example.com", "operations_lead"),
    ):
        resp = await client.post(
            "/api/v1/admin/users", headers=auth(org_a["admin_token"]),
            json={"email": email, "name": key.title(), "role": role},
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()
        session = await login(client, email, created["temp_password"])
        out[key] = {"id": created["id"], "token": session["access_token"]}
    return out


async def _task_for(org_id: str, assignee_id: str, title: str) -> str:
    from app.database import SessionLocal
    from app.models.action_item import ActionItem

    async with SessionLocal() as db:
        task = ActionItem(
            org_id=org_id, title=title, assignee_id=assignee_id, priority="P2",
        )
        db.add(task)
        await db.flush()
        await db.commit()
        return task.id


async def test_a_non_assignee_cannot_block_someone_elses_task(client, crew):
    """The exact device-proven case: 200 OK on another user's task."""
    task_id = await _task_for(crew["org_id"], crew["owner"]["id"],
                              "Train and schedule facilitators")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(crew["other"]["token"]),
        json={"reason": "Venue confirmation from the school is still pending"},
    )
    assert resp.status_code == 403, (
        f"F51: a non-assignee blocked another user's task — got {resp.status_code}"
    )
    # An honest refusal names the task and says what to do about it.
    assert "assigned to someone else" in resp.text, resp.text

    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from sqlalchemy import select

    async with SessionLocal() as db:
        row = (
            await db.execute(select(ActionItem).where(ActionItem.id == task_id))
        ).scalar_one()
    assert row.blocked is False, "the refusal did not prevent the write"
    assert row.blocked_reason is None


async def test_the_assignee_can_still_block_their_own_task(client, crew):
    """Control. 'I'm blocked' is an honesty switch — gating it away would be worse
    than the bug, because it stops the nudge ladder chasing the wrong person."""
    task_id = await _task_for(crew["org_id"], crew["owner"]["id"], "My own task")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(crew["owner"]["token"]),
        json={"reason": "Waiting on the venue"},
    )
    assert resp.status_code == 200, resp.text


async def test_a_lead_can_act_across_the_team(client, crew):
    """Control. Doc §13: 'Sales Agent — own only; Sales Lead — whole team'.

    A guard that refused leads too would pass the first test and break the
    escalation path the reminder ladder depends on (level 3 goes to the lead
    with one-tap reassign/extend).
    """
    task_id = await _task_for(crew["org_id"], crew["owner"]["id"], "Lead reaches this")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(crew["lead"]["token"]),
        json={"reason": "Escalated — chasing the vendor myself"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "route,payload",
    [
        ("unblock", {}),
        ("new-date", {"new_due": "2026-12-01T00:00:00", "reason": "slipped"}),
        ("split", {"parts": [{"title": "one"}, {"title": "two"}]}),
        ("vendor-promise", {"vendor_name": "PrintCraft",
                            "promised_date": "2026-12-01T00:00:00"}),
        ("vendor-slip", {"new_promised_date": "2026-12-08T00:00:00"}),
    ],
)
async def test_every_mutating_lifecycle_route_is_gated(client, crew, route, payload):
    """F51's real size: /block was merely the one that got caught.

    These were all 'code-verified, not executed' in the write-up because
    exercising them on the live project would have corrupted Round 7 state.
    Here they are actually executed.
    """
    task_id = await _task_for(crew["org_id"], crew["owner"]["id"], f"Task for {route}")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/{route}", headers=auth(crew["other"]["token"]),
        json=payload,
    )
    assert resp.status_code == 403, (
        f"/{route} is ungated for a non-assignee — got {resp.status_code}: "
        f"{resp.text[:200]}"
    )


async def test_completing_is_deliberately_still_open(client, crew):
    """A decision, recorded as a test so it cannot be mistaken for an oversight.

    If this ever *should* be gated, this test is the thing to change — not the
    absence of a check.
    """
    task_id = await _task_for(crew["org_id"], crew["owner"]["id"], "Covered for a colleague")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/complete", headers=auth(crew["other"]["token"]),
        json={"result_note": "Finished this while they were on leave"},
    )
    assert resp.status_code == 200, resp.text


async def test_an_agent_cannot_confirm_the_orgs_assignment_batch(client, crew):
    """`lead_confirm` means the phase lead confirms — the route was open to all.

    This is the half of F51 the spec states outright, and the half nobody had
    executed: confirming the batch on the live project would have staffed the
    whole organisation's work.
    """
    resp = await client.post(
        "/api/v1/assignments/confirm-batch", headers=auth(crew["other"]["token"]),
        json={"assignment_ids": []},
    )
    assert resp.status_code == 403, (
        f"an operations_agent confirmed the org's assignment batch — "
        f"got {resp.status_code}"
    )


async def test_a_lead_can_confirm_the_assignment_batch(client, crew):
    """Control — the gate must not break the mode it exists to enforce."""
    resp = await client.post(
        "/api/v1/assignments/confirm-batch", headers=auth(crew["lead"]["token"]),
        json={"assignment_ids": []},
    )
    assert resp.status_code == 200, resp.text
