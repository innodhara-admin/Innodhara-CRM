"""A client hints they want to buy again, and the loop closes.

The AI raises a card with the client's own words attached. A person accepts or
dismisses — the AI never moves the lead by itself, and that is asserted here by
checking that a flagged client sits untouched until somebody answers the card.

Accepting is the whole loop closing: the lead goes back to OPEN, its owner is
cleared so a sales lead has to choose one, a second cycle is recorded, and the
relationship engagement ends. Half of that happening would be worse than none
of it, so they are asserted together.

The quote matters more than it looks. A person is being asked to decide, and
"the AI thinks so" is not evidence; what the client actually said is. So a flag
that arrives with no reason and no quote is downgraded rather than shown, and
that is tested.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "rmopp-example.com"

BUYING_SIGNAL = """
Meena: How have things been since we finished?
Client: Very good. Actually, we have budget approved for next quarter and we
        want three more of the same for the other branches. Who should I talk
        to about that?
"""

JUST_POLITE = """
Meena: How have things been?
Client: All fine, thank you. We must do something together again sometime.
Meena: That would be lovely. Take care.
"""


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
    """The catch-up analysis, switched by what the transcript contains.

    Keyed off the transcript so one fixture can serve both the buying-signal
    and the just-polite cases without the test having to reach into the stub.
    """
    from app.ai import extraction as extraction_mod
    from app.jobs import pipelines

    async def fake_relationship(transcript, *, org_name, client_name, **kwargs):
        if "budget approved" in transcript:
            return extraction_mod.RelationshipAnalysis(
                summary="Good call. They have budget for next quarter and want "
                        "three more for the other branches.",
                key_facts=["Budget approved for next quarter"],
                next_touch_days=7,
                next_touch_topics="Who owns the budget for the other branches",
                new_opportunity=True,
                opportunity_reason="They have approved budget and asked who to "
                                   "talk to about buying more.",
                opportunity_quote="we have budget approved for next quarter and "
                                  "we want three more of the same",
            )
        return extraction_mod.RelationshipAnalysis(
            summary="Friendly call, nothing specific.",
            key_facts=[],
            next_touch_days=45,
            next_touch_topics="",
            new_opportunity=False,
        )

    monkeypatch.setattr(
        pipelines.extraction, "analyse_relationship_meeting", fake_relationship)


@pytest.fixture(scope="module")
async def org(client, super_token) -> dict:
    org = await create_org(
        client, super_token,
        name="RM Opportunity Co", slug="rm-opp-co", domain=DOMAIN,
    )
    for key, email, name, role, dept in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent", "sales"),
        ("siva", f"siva@{DOMAIN}", "Siva Lead", "sales_lead", "sales"),
        ("meena", f"meena@{DOMAIN}", "Meena Manager",
         "relationship_manager", "relationship"),
    ):
        uid, token = await _add(client, org, email, name, role, dept)
        org[f"{key}_id"] = uid
        org[f"{key}_token"] = token
    return org


async def _client_of_meena(client, org, name) -> dict:
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
        assert resp.status_code == 200, resp.text
    handed = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={"manager_id": org["meena_id"]},
    )
    assert handed.status_code == 200, handed.text
    return lead


async def _catch_up(client, org, lead_id, text):
    resp = await client.post(
        "/api/v1/meetings/notes", headers=auth(org["meena_token"]),
        json={"lead_id": lead_id, "title": "Catch-up", "text": text,
              "meeting_type": "relationship"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── raising the card ────────────────────────────────────────────────────────

async def test_a_buying_signal_raises_a_card_with_their_own_words(
    client, org, fake_ai
):
    lead = await _client_of_meena(client, org, "Buying Again Client")
    result = await _catch_up(client, org, lead["id"], BUYING_SIGNAL)
    assert result["relationship"]["new_opportunity"] is True

    body = (await client.get(f"/api/v1/leads/{lead['id']}/relationship",
                             headers=auth(org["meena_token"]))).json()
    opp = body["engagement"]["opportunity"]
    assert opp["status"] == "open"
    assert opp["reason"], "a card with no reason is not answerable"
    assert "budget approved" in (opp["quote"] or ""), \
        f"the card must carry what the client actually said: {opp['quote']}"


async def test_politeness_is_not_an_opportunity(client, org, fake_ai):
    """A false positive sends a salesperson to bother a happy client, which
    costs more than a missed hint."""
    lead = await _client_of_meena(client, org, "Just Polite Client")
    result = await _catch_up(client, org, lead["id"], JUST_POLITE)
    assert result["relationship"]["new_opportunity"] is False

    body = (await client.get(f"/api/v1/leads/{lead['id']}/relationship",
                             headers=auth(org["meena_token"]))).json()
    assert body["engagement"]["opportunity"]["status"] == "none"


async def test_the_card_can_explain_itself(client, org, fake_ai):
    """F10 again. A person is being asked to decide, so the Why? sheet has to
    have something to show them."""
    from app.database import SessionLocal
    from app.engines import assistant_engine

    lead = await _client_of_meena(client, org, "Explainable Opportunity Client")
    await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    async with SessionLocal() as db:
        trace = await assistant_engine.why_trace(
            db, org_id=org["id"], entity_type="lead", entity_id=lead["id"]
        )
    assert "No AI decision is recorded" not in trace, trace
    assert "budget" in trace.lower(), trace


async def test_the_card_shows_on_the_managers_home(client, org, fake_ai):
    lead = await _client_of_meena(client, org, "Home Card Client")
    await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    rows = (await client.get("/api/v1/relationships/mine",
                             headers=auth(org["meena_token"]))).json()
    row = next(r for r in rows if r["lead_name"] == "Home Card Client")
    assert row["opportunity_open"] is True
    assert row["opportunity_reason"]


# ── answering it ────────────────────────────────────────────────────────────

async def test_accepting_puts_the_client_back_into_sales(client, org, fake_ai):
    """The whole loop closing.

    This test used to assert the lead did NOT move — that was step 6, where
    `closed -> open` did not exist yet. Step 7 completes it, so the assertion
    is inverted on purpose rather than deleted: what it guards now is that
    every part of the handover back happens together, because half of it
    happening is worse than none.
    """
    lead = await _client_of_meena(client, org, "Accepted Client")
    await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/opportunity/accept",
        headers=auth(org["meena_token"]), json={},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sales_leads_notified"] >= 1
    assert body["engagement"]["opportunity"]["status"] == "accepted"
    assert body["engagement"]["opportunity"]["decided_by_name"] == "Meena Manager"

    # The lead is back in the pipeline, at OPEN and never at COLD_CALLING —
    # we already know this client.
    assert body["lead_state"] == "open", body
    detail = (await client.get(f"/api/v1/leads/{lead['id']}",
                               headers=auth(org["priya_token"]))).json()
    assert detail["state"] == "open"
    assert detail["owner_id"] is None,         "the new round must start with nobody on it"

    # The engagement ends outright rather than pausing (open question 4).
    assert body["engagement"]["status"] == "returned_to_sales"
    assert body["engagement"]["ended_at"] is not None

    # Two rounds on record: the one that already happened, and this one.
    assert body["cycle_number"] == 2
    assert body["cycle_owner_id"] is None

    notes = (await client.get("/api/v1/notifications",
                              headers=auth(org["siva_token"]))).json()
    titles = [n["title"] for n in notes]
    assert any("Accepted Client" in t for t in titles), titles
    bodies = " ".join(n.get("body") or "" for n in notes)
    assert "budget approved" in bodies,         "the sales lead must see what the client actually said"


async def test_dismissing_records_it_rather_than_deleting_it(client, org, fake_ai):
    """The AI being wrong is the only signal the detection needs looking at."""
    lead = await _client_of_meena(client, org, "Dismissed Client")
    await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/opportunity/dismiss",
        headers=auth(org["meena_token"]),
        json={"note": "He was being polite, the budget is for something else"},
    )
    assert resp.status_code == 200, resp.text
    opp = resp.json()["engagement"]["opportunity"]
    assert opp["status"] == "dismissed"
    assert "polite" in (opp["reason"] or ""), opp["reason"]
    assert opp["decided_at"] is not None


async def test_a_card_cannot_be_answered_twice(client, org, fake_ai):
    lead = await _client_of_meena(client, org, "Answered Once Client")
    await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    first = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/opportunity/dismiss",
        headers=auth(org["meena_token"]), json={},
    )
    assert first.status_code == 200, first.text

    again = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/opportunity/accept",
        headers=auth(org["meena_token"]), json={},
    )
    assert again.status_code == 422, again.text
    assert "no open opportunity" in again.json()["detail"].lower()


async def test_sales_cannot_answer_the_relationship_managers_card(
    client, org, fake_ai
):
    """`manage_relationships` is the RM's and the admin's. A sales agent who
    wants the client back asks; they do not help themselves."""
    lead = await _client_of_meena(client, org, "Not Priyas Card Client")
    await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/opportunity/accept",
        headers=auth(org["priya_token"]), json={},
    )
    assert resp.status_code == 403, resp.text


async def test_a_hint_about_a_client_nobody_looks_after_raises_nothing(
    client, org, fake_ai
):
    """A card with no owner is a card nobody answers. The catch-up still
    saves — it just does not leave a question hanging in mid-air."""
    from app.database import SessionLocal
    from app.models.relationship import RelationshipEngagement

    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": "Unmanaged Client", "owner_id": org["priya_id"]},
    )
    lead = created.json()
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await client.patch(
        f"/api/v1/leads/{lead['id']}/state", headers=auth(org["priya_token"]),
        json={"state": "open", "reason": "answered"},
    )
    result = await _catch_up(client, org, lead["id"], BUYING_SIGNAL)

    assert result["relationship"]["new_opportunity"] is False
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(RelationshipEngagement).where(
                RelationshipEngagement.lead_id == lead["id"]
            )
        )).scalars().all()
    assert rows == []
