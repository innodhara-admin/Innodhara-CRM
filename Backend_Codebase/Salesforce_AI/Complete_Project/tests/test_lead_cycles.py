"""Rounds of business with the same client.

The design decision this file guards: a lead keeps ONE `state` column, always
meaning the current round, and `lead_cycles` records the rounds around it. Every
existing query that reads `lead.state` is untouched — that is the whole reason
the design was chosen over a new lead per round or a separate Client entity.

Cycles are written lazily. A client sold to once has no rows and needs none.
The first time one comes back, the round that already happened is reconstructed
alongside the new one, so a two-round client has two cards and not one.

The last test walks the entire journey the plan describes, from a cold call to
a second round with a new owner, because each half of this works in isolation
and the question that matters is whether they work in sequence.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "cycles-example.com"

BUYING_SIGNAL = "Client: we have budget approved and want three more."


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


@pytest.fixture
def fake_ai(monkeypatch):
    from app.ai import extraction as extraction_mod
    from app.jobs import pipelines

    async def fake_relationship(transcript, *, org_name, client_name, **kwargs):
        return extraction_mod.RelationshipAnalysis(
            summary="They want more.",
            key_facts=[],
            next_touch_days=14,
            next_touch_topics="",
            new_opportunity=True,
            opportunity_reason="Approved budget and asked for three more.",
            opportunity_quote="we have budget approved and want three more",
        )

    monkeypatch.setattr(
        pipelines.extraction, "analyse_relationship_meeting", fake_relationship)


@pytest.fixture(scope="module")
async def org(client, super_token) -> dict:
    org = await create_org(
        client, super_token,
        name="Cycles Co", slug="cycles-co", domain=DOMAIN,
    )
    for key, email, name, role, dept in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent", "sales"),
        ("ravi", f"ravi@{DOMAIN}", "Ravi Agent", "sales_agent", "sales"),
        ("siva", f"siva@{DOMAIN}", "Siva Lead", "sales_lead", "sales"),
        ("meena", f"meena@{DOMAIN}", "Meena Manager",
         "relationship_manager", "relationship"),
        ("ops", f"ops@{DOMAIN}", "Ops Person", "operations_agent", "operations"),
    ):
        uid, token = await _add(client, org, email, name, role, dept)
        org[f"{key}_id"] = uid
        org[f"{key}_token"] = token
    return org


async def _walk_to_closed(client, org, name) -> dict:
    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": name, "city": "Kolkata", "owner_id": org["priya_id"]},
    )
    lead = created.json()
    await add_reached_contact(client, org["priya_token"], lead["id"])
    for state in ("open", "active", "execution_in_progress",
                  "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state", headers=auth(org["priya_token"]),
            json={"state": state, "reason": "walking to closed"},
        )
        assert resp.status_code == 200, f"{state}: {resp.text}"
    return lead


async def _hand_over_and_reopen(client, org, lead) -> dict:
    handed = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={"manager_id": org["meena_id"]},
    )
    assert handed.status_code == 200, handed.text
    await client.post(
        "/api/v1/meetings/notes", headers=auth(org["meena_token"]),
        json={"lead_id": lead["id"], "title": "Catch-up", "text": BUYING_SIGNAL,
              "meeting_type": "relationship"},
    )
    accepted = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/opportunity/accept",
        headers=auth(org["meena_token"]), json={},
    )
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


# ── the lazy rule ───────────────────────────────────────────────────────────

async def test_an_ordinary_lead_has_no_cycles_at_all(client, org):
    """Most clients are sold to once. They must carry no cycle rows, or every
    lead in the system grows a card nobody asked for."""
    lead = await _walk_to_closed(client, org, "One Round Client")
    resp = await client.get(f"/api/v1/leads/{lead['id']}/cycles",
                            headers=auth(org["priya_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_coming_back_writes_down_the_round_that_already_happened(
    client, org, fake_ai
):
    """A page showing "round 2" and nothing else would be worse than no page.
    The finished round is reconstructed from the lead itself."""
    lead = await _walk_to_closed(client, org, "Two Rounds Client")
    await _hand_over_and_reopen(client, org, lead)

    cycles = (await client.get(f"/api/v1/leads/{lead['id']}/cycles",
                               headers=auth(org["siva_token"]))).json()
    assert len(cycles) == 2, cycles
    first, second = cycles

    assert first["cycle_number"] == 1
    assert first["source"] == "cold_call", "the first round began with a call"
    assert first["outcome"] == "closed"
    assert first["closed_at"] is not None
    assert first["owner_id"] == org["priya_id"], \
        "the finished round belongs to whoever sold it"

    assert second["cycle_number"] == 2
    assert second["source"] == "relationship", \
        "a returning client did not come from a cold call"
    assert second["outcome"] == "running"
    assert second["owner_id"] is None
    assert second["closed_at"] is None


async def test_the_second_round_starts_at_open_never_at_cold_calling(
    client, org, fake_ai
):
    """Cold calling exists to find out whether there is interest. With a
    client we have already delivered for, we know there is."""
    lead = await _walk_to_closed(client, org, "No Cold Call Client")
    await _hand_over_and_reopen(client, org, lead)

    detail = (await client.get(f"/api/v1/leads/{lead['id']}",
                               headers=auth(org["siva_token"]))).json()
    assert detail["state"] == "open"
    history = [h["to"] for h in detail["state_history"]]
    assert "cold_calling" not in history[:1], history


# ── the new owner ───────────────────────────────────────────────────────────

async def test_a_sales_lead_gives_the_new_round_to_someone(client, org, fake_ai):
    lead = await _walk_to_closed(client, org, "Needs An Owner Client")
    await _hand_over_and_reopen(client, org, lead)

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/cycles/2/owner",
        headers=auth(org["siva_token"]), json={"owner_id": org["ravi_id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] == org["ravi_id"]
    assert resp.json()["owner_name"] == "Ravi Agent"

    # The cycle is the record; `lead.owner_id` is what everything else reads.
    # They must not disagree.
    detail = (await client.get(f"/api/v1/leads/{lead['id']}",
                               headers=auth(org["siva_token"]))).json()
    assert detail["owner_id"] == org["ravi_id"]

    notes = (await client.get("/api/v1/notifications",
                              headers=auth(org["ravi_token"]))).json()
    assert any("Needs An Owner Client" in n["title"] for n in notes), notes


async def test_an_agent_cannot_take_an_unowned_round_for_themselves(
    client, org, fake_ai
):
    """The new round deliberately has no owner, which means only a sales lead
    or the admin can act on it. An agent helping themselves would undo the
    reason it was left empty."""
    lead = await _walk_to_closed(client, org, "Not Ravis To Take Client")
    await _hand_over_and_reopen(client, org, lead)

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/cycles/2/owner",
        headers=auth(org["ravi_token"]), json={"owner_id": org["ravi_id"]},
    )
    assert resp.status_code == 403, resp.text


async def test_a_round_belongs_to_a_salesperson(client, org, fake_ai):
    lead = await _walk_to_closed(client, org, "Wrong Role Client")
    await _hand_over_and_reopen(client, org, lead)

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/cycles/2/owner",
        headers=auth(org["siva_token"]), json={"owner_id": org["ops_id"]},
    )
    assert resp.status_code == 422, resp.text
    assert "sales" in resp.json()["detail"].lower()


# ── rounds end ──────────────────────────────────────────────────────────────

async def test_finishing_the_second_round_records_how_it_ended(
    client, org, fake_ai
):
    """A client on a third round needs an honest record of the second."""
    lead = await _walk_to_closed(client, org, "Round Two Ends Client")
    await _hand_over_and_reopen(client, org, lead)
    await client.post(
        f"/api/v1/leads/{lead['id']}/cycles/2/owner",
        headers=auth(org["siva_token"]), json={"owner_id": org["ravi_id"]},
    )

    resp = await client.patch(
        f"/api/v1/leads/{lead['id']}/state", headers=auth(org["ravi_token"]),
        json={"state": "lost_for_now", "reason": "budget went elsewhere"},
    )
    assert resp.status_code == 200, resp.text

    cycles = (await client.get(f"/api/v1/leads/{lead['id']}/cycles",
                               headers=auth(org["siva_token"]))).json()
    second = cycles[1]
    assert second["outcome"] == "lost_for_now", cycles
    assert second["closed_at"] is not None


# ── the whole journey ───────────────────────────────────────────────────────

async def test_the_whole_loop_from_cold_call_to_a_second_round(
    client, org, fake_ai
):
    """Cold call → sold → closed → relationship → wants more → back to sales
    with a new owner.

    Each half is tested above. This asserts they work in sequence, which is
    the only thing anybody actually experiences.
    """
    from app.database import SessionLocal
    from app.models.relationship import RelationshipEngagement

    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": "Full Journey Client", "city": "Kolkata",
              "owner_id": org["priya_id"]},
    )
    lead = created.json()
    assert lead["state"] == "cold_calling", "round one starts with a call"

    await add_reached_contact(client, org["priya_token"], lead["id"])
    for state in ("open", "active", "execution_in_progress",
                  "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state", headers=auth(org["priya_token"]),
            json={"state": state, "reason": "round one"},
        )
        assert resp.status_code == 200, f"{state}: {resp.text}"

    accepted = await _hand_over_and_reopen(client, org, lead)
    assert accepted["cycle_number"] == 2
    assert accepted["lead_state"] == "open"

    # The relationship ended rather than paused, and the client is nobody's
    # until a sales lead decides.
    async with SessionLocal() as db:
        engagement = (await db.execute(
            select(RelationshipEngagement).where(
                RelationshipEngagement.lead_id == lead["id"])
        )).scalars().one()
    assert engagement.status == "returned_to_sales"
    assert engagement.ended_at is not None

    assign = await client.post(
        f"/api/v1/leads/{lead['id']}/cycles/2/owner",
        headers=auth(org["siva_token"]), json={"owner_id": org["ravi_id"]},
    )
    assert assign.status_code == 200, assign.text

    # And round two behaves like any ordinary round from here.
    resp = await client.patch(
        f"/api/v1/leads/{lead['id']}/state", headers=auth(org["ravi_token"]),
        json={"state": "active", "reason": "round two under way"},
    )
    assert resp.status_code == 200, resp.text

    cycles = (await client.get(f"/api/v1/leads/{lead['id']}/cycles",
                               headers=auth(org["ravi_token"]))).json()
    assert [c["cycle_number"] for c in cycles] == [1, 2]
    assert [c["source"] for c in cycles] == ["cold_call", "relationship"]
    assert cycles[1]["owner_name"] == "Ravi Agent"
