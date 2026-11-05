"""Customer ask, 21 Sep 2026 — "blocked, waiting on Siva" must reach Siva.

Before: `POST /tasks/{id}/block` stored a free-text reason, and the Sync
Engine only acted when the reason said "school", "client" or "approval" (a
client chase). A colleague named in the reason was never told; the blocked
task showed up on his Projects screen and nowhere else.

Now the colleague is found in the reason (or passed explicitly), notified
once, and the task is listed for them at `GET /action-items/waiting-on-me`
until it is unblocked. Names are matched conservatively: an ambiguous first
name tells nobody rather than the wrong person.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.services.blocker_resolver import find_colleague
from tests.conftest import auth, login


# ── the name matcher on its own ──────────────────────────────────────────

PEOPLE = [
    ("u_siva", "Siva Kumar"),
    ("u_asha", "Asha Rao"),
    ("u_ravi1", "Ravi Shankar"),
    ("u_ravi2", "Ravi Teja"),
    ("u_al", "Al Noor"),
]


def test_a_first_name_in_the_reason_finds_the_colleague():
    assert find_colleague("waiting for inputs from Siva", PEOPLE) == "u_siva"


def test_case_and_possessive_do_not_matter():
    assert find_colleague("need SIVA's sign-off on the budget", PEOPLE) == "u_siva"


def test_a_full_name_wins():
    assert find_colleague("blocked on asha rao for the rate card", PEOPLE) == "u_asha"


def test_an_ambiguous_first_name_tells_nobody():
    assert find_colleague("waiting on Ravi", PEOPLE) is None


def test_a_full_name_settles_an_ambiguous_first_name():
    assert find_colleague("waiting on Ravi Teja for the deck", PEOPLE) == "u_ravi2"


def test_no_name_no_colleague():
    assert find_colleague("waiting for the school to reply", PEOPLE) is None


def test_part_of_a_word_is_not_a_name():
    # "Sivakumar Street" is not Siva; "shivam" is not "Siva".
    assert find_colleague("parcel stuck at Sivakumar Street", PEOPLE) is None


def test_very_short_first_names_are_not_matched_alone():
    # "Al" would match "al" in "…al dente"-style noise; two letters is too weak.
    assert find_colleague("waiting on al", PEOPLE) is None
    assert find_colleague("waiting on Al Noor", PEOPLE) == "u_al"


def test_the_blocked_person_is_never_their_own_blocker():
    assert find_colleague("Siva to confirm", PEOPLE, exclude={"u_siva"}) is None


def test_two_different_colleagues_named_tells_nobody():
    assert find_colleague("waiting on Siva and Asha", PEOPLE) is None


# ── end to end through the API ───────────────────────────────────────────

@pytest.fixture(autouse=True)
def _sync_reactor():
    """The test client skips the app's startup, which is what installs the
    Sync Engine as the event reactor; this module needs the reaction."""
    from app.engines import events, sync_engine

    sync_engine.register()
    yield
    events.set_reactor(None)


@pytest.fixture(scope="module")
async def team(client, org_a):
    out = {"org_id": org_a["id"], "admin_token": org_a["admin_token"]}
    for key, email, name, role in (
        ("mithun", "blk.mithun@alpha-example.com", "Mithun Rao", "operations_agent"),
        ("siva", "blk.siva@alpha-example.com", "Sivaram Blocker", "operations_agent"),
        ("priya1", "blk.priya1@alpha-example.com", "Priyanka One", "operations_agent"),
        ("priya2", "blk.priya2@alpha-example.com", "Priyanka Two", "operations_agent"),
    ):
        resp = await client.post(
            "/api/v1/admin/users", headers=auth(org_a["admin_token"]),
            json={"email": email, "name": name, "role": role},
        )
        assert resp.status_code == 200, resp.text
        created = resp.json()
        session = await login(client, email, created["temp_password"])
        out[key] = {"id": created["id"], "token": session["access_token"]}
    return out


async def _task(org_id: str, assignee_id: str, title: str) -> str:
    from app.database import SessionLocal
    from app.models.action_item import ActionItem

    async with SessionLocal() as db:
        task = ActionItem(org_id=org_id, title=title, assignee_id=assignee_id, priority="P2")
        db.add(task)
        await db.commit()
        return task.id


async def _notes_for(user_id: str, task_id: str) -> list:
    """This task's blocked_on_you notes for a user. Tasks made here have no
    project or client, so the note points at the task itself."""
    from app.database import SessionLocal
    from app.models.user import Notification

    async with SessionLocal() as db:
        return (await db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.entity_type == "action_item",
                Notification.entity_id == task_id,
                Notification.kind == "blocked_on_you",
            )
        )).scalars().all()


async def test_the_note_opens_the_project_when_there_is_one(client, team):
    """The app's task screen only finds your own tasks, so the colleague's
    tap goes to the project (else the client) instead of "not found"."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.user import Notification

    task_id = await _task(team["org_id"], team["mithun"]["id"], "Ship the kits")
    async with SessionLocal() as db:
        task = (await db.execute(select(ActionItem).where(ActionItem.id == task_id))).scalar_one()
        task.lead_id = None
        task.project_id = "p" * 32  # the note only needs the id
        await db.commit()
    await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "Sivaram owes the packing list"},
    )
    async with SessionLocal() as db:
        notes = (await db.execute(
            select(Notification).where(
                Notification.user_id == team["siva"]["id"],
                Notification.kind == "blocked_on_you",
                Notification.body.contains("Ship the kits"),
            )
        )).scalars().all()
    assert [(n.entity_type, n.entity_id) for n in notes] == [("project", "p" * 32)]


async def _waiting_on(client, token: str) -> list[dict]:
    resp = await client.get("/api/v1/action-items/waiting-on-me", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def test_the_named_colleague_is_told_and_sees_it(client, team):
    task_id = await _task(team["org_id"], team["mithun"]["id"], "Send the lab kit list")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "waiting for inputs from Sivaram"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked_on"] == {
        "id": team["siva"]["id"], "name": "Sivaram Blocker",
    }

    notes = await _notes_for(team["siva"]["id"], task_id)
    assert len(notes) == 1
    assert "Mithun Rao" in notes[0].title
    assert "Send the lab kit list" in (notes[0].body or "")

    items = await _waiting_on(client, team["siva"]["token"])
    mine = [i for i in items if i["id"] == task_id]
    assert len(mine) == 1
    assert mine[0]["waiting_user_name"] == "Mithun Rao"
    assert mine[0]["blocked_reason"] == "waiting for inputs from Sivaram"

    # Not on Mithun's own list: he is the one waiting.
    assert all(i["id"] != task_id for i in await _waiting_on(client, team["mithun"]["token"]))


async def test_unblocking_takes_it_off_their_list(client, team):
    task_id = await _task(team["org_id"], team["mithun"]["id"], "Book the bus")
    await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "Sivaram has the vendor quote"},
    )
    assert any(i["id"] == task_id for i in await _waiting_on(client, team["siva"]["token"]))
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/unblock", headers=auth(team["mithun"]["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert all(i["id"] != task_id for i in await _waiting_on(client, team["siva"]["token"]))


async def test_an_ambiguous_name_tells_nobody(client, team):
    task_id = await _task(team["org_id"], team["mithun"]["id"], "Print certificates")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "waiting on Priyanka"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked_on"] is None
    assert await _notes_for(team["priya1"]["id"], task_id) == []
    assert await _notes_for(team["priya2"]["id"], task_id) == []


async def test_an_explicit_colleague_wins_over_the_text(client, team):
    task_id = await _task(team["org_id"], team["mithun"]["id"], "Order trophies")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "waiting on Priyanka", "blocked_on_user_id": team["priya2"]["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked_on"]["id"] == team["priya2"]["id"]
    assert len(await _notes_for(team["priya2"]["id"], task_id)) == 1


async def test_an_explicit_colleague_from_another_org_is_ignored(client, team, org_b):
    resp = await client.post(
        "/api/v1/admin/users", headers=auth(org_b["admin_token"]),
        json={"email": "blk.outsider@beta-example.com", "name": "Outsider Beta",
              "role": "operations_agent"},
    )
    assert resp.status_code == 200, resp.text
    outsider = resp.json()["id"]
    task_id = await _task(team["org_id"], team["mithun"]["id"], "Collect forms")
    resp = await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "stuck", "blocked_on_user_id": outsider},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["blocked_on"] is None
    assert await _notes_for(outsider, task_id) == []


async def test_reblocking_without_a_name_clears_the_old_colleague(client, team):
    task_id = await _task(team["org_id"], team["mithun"]["id"], "Hire the hall")
    await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "Sivaram to confirm the date"},
    )
    await client.post(
        f"/api/v1/tasks/{task_id}/block", headers=auth(team["mithun"]["token"]),
        json={"reason": "the hall owner is travelling"},
    )
    assert all(i["id"] != task_id for i in await _waiting_on(client, team["siva"]["token"]))


def test_a_colleagues_approval_does_not_chase_the_client():
    """'approval' in the reason used to mean 'draft a chase to the client'.
    When a colleague was named, the approval is theirs, not the client's."""
    from app.engines.sync_engine import _blocker_is_client

    assert _blocker_is_client("waiting for the school's approval", colleague_named=False)
    assert _blocker_is_client("client has not replied", colleague_named=False)
    assert not _blocker_is_client("needs Siva's approval", colleague_named=True)
    assert not _blocker_is_client("the hall owner is travelling", colleague_named=False)
