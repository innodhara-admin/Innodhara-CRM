"""Handing a finished client to a relationship manager.

Step 3 of the build order. The button exists, the engine picks somebody, the
engagement is recorded and the manager is told. Nothing about the relationship
itself is built yet — that is steps 4 onward.

Two things here are load-bearing rather than incidental:

* Every pick writes an `ai_decisions` row, so the app's "Why this person?"
  sheet has prose to render. Finding F10 was exactly this affordance offered
  with nothing behind it, and the last test in this file asserts the sheet
  itself renders, not merely that a row exists.
* A client has one relationship. Reassignment moves the manager on the row
  that is already there; a second handover is refused. The alternative — a
  new engagement per correction — would make "who looks after this client"
  a question with a history instead of an answer.
"""
from __future__ import annotations

import pytest

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "handover-example.com"
BARE_DOMAIN = "nomanagers-example.com"


async def _add(client, org, email, name, role, department=None):
    resp = await client.post(
        "/api/v1/admin/users", headers=auth(org["admin_token"]),
        json={"email": email, "name": name, "role": role,
              **({"department": department} if department else {})},
    )
    assert resp.status_code == 200, resp.text
    user = resp.json()
    session = await login(client, email, user["temp_password"])
    return user["id"], session["access_token"]


@pytest.fixture(scope="module")
async def org(client, super_token) -> dict:
    """One sales agent, one sales lead, two relationship managers.

    Two managers rather than one so the engine has an actual choice to make;
    with one candidate every pick is trivially correct and proves nothing.
    """
    org = await create_org(
        client, super_token,
        name="Handover Co", slug="handover-co", domain=DOMAIN,
    )
    for key, email, name, role, dept in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent", "sales"),
        ("ravi", f"ravi@{DOMAIN}", "Ravi Agent", "sales_agent", "sales"),
        ("siva", f"siva@{DOMAIN}", "Siva Lead", "sales_lead", "sales"),
        ("meena", f"meena@{DOMAIN}", "Meena Manager",
         "relationship_manager", "relationship"),
        ("nikhil", f"nikhil@{DOMAIN}", "Nikhil Manager",
         "relationship_manager", "relationship"),
    ):
        uid, token = await _add(client, org, email, name, role, dept)
        org[f"{key}_id"] = uid
        org[f"{key}_token"] = token

    # Meena's area of expertise, named after a place the leads below sit in.
    # The engine reads a manager's `user_skills` and looks for one that the
    # client's own record mentions -- it does not carry a vocabulary of its own.
    resp = await client.post(
        "/api/v1/skills", headers=auth(org["admin_token"]),
        json={"user_id": org["meena_id"], "skill": "kolkata", "level": "expert"},
    )
    assert resp.status_code == 200, resp.text
    return org


@pytest.fixture(scope="module")
async def bare_org(client, super_token) -> dict:
    """An org that has no relationship managers at all."""
    org = await create_org(
        client, super_token,
        name="No Managers Co", slug="no-managers-co", domain=BARE_DOMAIN,
    )
    uid, token = await _add(
        client, org, f"asha@{BARE_DOMAIN}", "Asha Agent", "sales_agent", "sales"
    )
    org["asha_id"], org["asha_token"] = uid, token
    return org


async def _closed_lead(client, org, name, owner_key="priya", city="Kolkata") -> dict:
    """A lead walked all the way to `closed` by its owner.

    Written out rather than inserted directly so the walk goes through the
    same state machine and the same ownership gate a person would.
    """
    owner_token = org[f"{owner_key}_token"]
    owner_id = org.get(f"{owner_key}_id")
    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": name, "city": city, "owner_id": owner_id},
    )
    assert created.status_code == 200, created.text
    lead = created.json()
    await add_reached_contact(client, owner_token, lead["id"])
    for state in ("open", "active", "execution_in_progress",
                  "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state", headers=auth(owner_token),
            json={"state": state, "reason": "walking to closed"},
        )
        assert resp.status_code == 200, f"{state}: {resp.text}"
    return lead


# ── the choice ──────────────────────────────────────────────────────────────

async def test_the_engine_picks_the_manager_whose_focus_matches(client, org):
    """Meena holds `kolkata` as a skill and the client sits in Kolkata;
    Nikhil holds nothing. Both are free and neither has a client yet, so the
    focus match is the only thing separating them."""
    lead = await _closed_lead(client, org, "Focus Match Client", city="Kolkata")

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["manager_id"] == org["meena_id"], body["reason"]
    assert body["status"] == "active"
    assert body["overridden"] is False
    assert "kolkata" in body["reason"].lower(), \
        f"the reason must say what matched: {body['reason']}"


async def test_the_manager_is_told(client, org):
    lead = await _closed_lead(client, org, "Told Client")
    await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )
    notes = await client.get(
        "/api/v1/notifications", headers=auth(org["meena_token"])
    )
    assert notes.status_code == 200, notes.text
    titles = [n["title"] for n in notes.json()]
    assert any("Told Client" in t for t in titles), titles


async def test_a_person_can_overrule_the_engine(client, org):
    """The engine will sometimes be wrong and there has to be a fix that is
    not a developer. The override is recorded as one."""
    lead = await _closed_lead(client, org, "Overruled Client")

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["siva_token"]), json={"manager_id": org["nikhil_id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["manager_id"] == org["nikhil_id"]
    assert body["overridden"] is True
    assert "Meena" in body["reason"], \
        f"an override must say what it overruled: {body['reason']}"


# ── the rules around it ─────────────────────────────────────────────────────

async def test_a_client_still_being_sold_to_cannot_be_handed_over(client, org):
    """Relationship management starts when the selling and delivery are done.
    Handing over an open lead would take it out of the pipeline silently."""
    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": "Still Selling Client", "owner_id": org["priya_id"]},
    )
    lead = created.json()
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await client.patch(
        f"/api/v1/leads/{lead['id']}/state", headers=auth(org["priya_token"]),
        json={"state": "open", "reason": "answered"},
    )

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )
    assert resp.status_code == 422, resp.text
    assert "closed" in resp.json()["detail"]


async def test_another_agent_cannot_hand_over_someone_elses_client(client, org):
    lead = await _closed_lead(client, org, "Not Ravis Client")

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["ravi_token"]), json={},
    )
    assert resp.status_code == 403, resp.text
    assert "Priya Agent" in resp.json()["detail"]


async def test_a_relationship_manager_cannot_hand_clients_over(client, org):
    """Deciding that a client is finished with sales is the sales side's call.
    An RM who wants one back asks; they do not help themselves."""
    lead = await _closed_lead(client, org, "Not Meenas To Claim")

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["meena_token"]), json={},
    )
    assert resp.status_code == 403, resp.text


async def test_a_client_is_not_handed_over_twice(client, org):
    lead = await _closed_lead(client, org, "Only Once Client")
    first = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )
    assert second.status_code == 422, second.text
    assert "already looks after" in second.json()["detail"]


async def test_an_org_with_no_managers_is_told_so_plainly(client, bare_org):
    """The button must not fail silently. Somebody has to be able to read the
    refusal and know that the fix is to add a manager."""
    created = await client.post(
        "/api/v1/leads", headers=auth(bare_org["asha_token"]),
        json={"name": "Nobody To Hand To"},
    )
    lead = created.json()
    await add_reached_contact(client, bare_org["asha_token"], lead["id"])
    for state in ("open", "active", "execution_in_progress",
                  "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state",
            headers=auth(bare_org["asha_token"]),
            json={"state": state, "reason": "walking to closed"},
        )
        assert resp.status_code == 200, f"{state}: {resp.text}"

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(bare_org["asha_token"]), json={},
    )
    assert resp.status_code == 422, resp.text
    assert "no relationship manager" in resp.json()["detail"].lower()


# ── reassignment ────────────────────────────────────────────────────────────

async def test_reassignment_moves_the_manager_on_the_same_engagement(client, org):
    """One client, one relationship. Correcting who holds it is a correction,
    not a new chapter — so there must still be exactly one engagement row."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.relationship import RelationshipEngagement

    lead = await _closed_lead(client, org, "Reassigned Client")
    await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )

    moved = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/manager",
        headers=auth(org["siva_token"]),
        json={"manager_id": org["nikhil_id"], "reason": "Meena is stretched"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["manager_id"] == org["nikhil_id"]

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(RelationshipEngagement).where(
                RelationshipEngagement.lead_id == lead["id"]
            )
        )).scalars().all()
    assert len(rows) == 1, \
        f"reassignment opened a second engagement: {[r.status for r in rows]}"
    assert rows[0].manager_id == org["nikhil_id"]

    read = await client.get(
        f"/api/v1/leads/{lead['id']}/relationship",
        headers=auth(org["meena_token"]),
    )
    assert read.status_code == 200, read.text
    assert read.json()["engagement"]["manager_name"] == "Nikhil Manager"


async def test_a_client_nobody_looks_after_reads_as_null_not_missing(client, org):
    """Most clients will never have a relationship manager. That is an
    ordinary answer, not a missing record, so it is not a 404."""
    lead = await _closed_lead(client, org, "Left Closed Client")
    resp = await client.get(
        f"/api/v1/leads/{lead['id']}/relationship",
        headers=auth(org["priya_token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["engagement"] is None


# ── the Why? sheet ──────────────────────────────────────────────────────────

async def test_the_pick_can_explain_itself(client, org):
    """F10 again, for this feature.

    Not "a row exists" but "the sheet the app opens renders it". The bug being
    guarded against was an affordance the backend never populated, and a test
    that only checked the table would have passed while the button still said
    "no decision recorded".
    """
    from app.database import SessionLocal
    from app.engines import assistant_engine

    lead = await _closed_lead(client, org, "Explain Yourself Client")
    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={},
    )
    assert resp.status_code == 200, resp.text

    async with SessionLocal() as db:
        trace = await assistant_engine.why_trace(
            db, org_id=org["id"], entity_type="lead", entity_id=lead["id"]
        )
    assert "No AI decision is recorded" not in trace, trace
    assert "Explain Yourself Client" in trace, trace
    assert "Meena" in trace, trace
