"""Phase 6 (Inbox) — the inbound triage contract.

Nothing covered inbound triage before this file, which is how the gaps below
survived to Phase 6: `GET /inbound/triage` never returned the AI's own reading
of the message, and `POST /inbound/{id}/resolve` could only attach a contact.
The Inbox screen offers "set intent" and "attach to project", and a picker that
cannot show the guess it overwrites is a blind write.

What is deliberately NOT tested here, because it is deliberately not built:
`resolve` still accepts a `note` it never stores, and still has no `lead_id`
(attaching to a lead goes through one of its contacts). Both are recorded as
known gaps in FINDINGS/handoff rather than papered over here.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _triage_message(client, token, *, from_address: str) -> dict:
    """A message from a sender we don't know lands in the triage queue (X1)."""
    resp = await client.post(
        "/api/v1/inbound/ingest",
        headers=auth(token),
        json={
            "channel": "email",
            "from_address": from_address,
            "subject": "Enquiry",
            "body": "We heard about your programmes. Can someone call us?",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "triage", f"expected triage, got {data['status']}"
    return data


async def _queue(client, token) -> list[dict]:
    resp = await client.get("/api/v1/inbound/triage", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _row(client, token, message_id: str) -> dict:
    rows = [m for m in await _queue(client, token) if m["id"] == message_id]
    assert rows, f"{message_id} is not in the triage queue"
    return rows[0]


async def test_triage_row_carries_the_ai_reading_and_its_matches(client, org_a):
    """The card shows the AI's intent guess and which client it belongs to.

    Without these keys the intent picker opens blank over a guess the human
    cannot see, and the reply route cannot scope the assistant to the client
    the backend already matched.
    """
    token = org_a["admin_token"]
    msg = await _triage_message(client, token, from_address="stranger@unknown-example.com")

    row = await _row(client, token, msg["id"])
    for key in ("intent", "change_type", "matched_lead_id",
                "matched_project_id", "created_at"):
        assert key in row, f"triage row is missing '{key}': {sorted(row)}"
    assert row["created_at"], "created_at must be a real timestamp"
    # The old contract must still hold, key for key.
    for key in ("id", "channel", "from_address", "subject", "body",
                "status", "reason", "summary"):
        assert key in row, f"triage row lost the pre-existing key '{key}'"


async def test_resolving_sets_the_intent_a_human_chose(client, org_a):
    """A human correcting the AI is the whole point of the triage screen."""
    token = org_a["admin_token"]
    msg = await _triage_message(client, token, from_address="intent@unknown-example.com")

    resp = await client.post(
        f"/api/v1/inbound/{msg['id']}/resolve",
        headers=auth(token),
        json={"intent": "scheduling", "mark_processed": False},
    )
    assert resp.status_code == 200, resp.text

    assert (await _row(client, token, msg["id"]))["intent"] == "scheduling"


async def test_an_invented_intent_is_refused(client, org_a):
    """The engines route on this vocabulary — an unknown value would route
    nowhere at all, silently. It must be refused, not stored."""
    token = org_a["admin_token"]
    msg = await _triage_message(client, token, from_address="bogus@unknown-example.com")

    resp = await client.post(
        f"/api/v1/inbound/{msg['id']}/resolve",
        headers=auth(token),
        json={"intent": "please_call_me", "mark_processed": False},
    )
    assert resp.status_code == 422, resp.text
    assert "please_call_me" in resp.text
    # And it left the message exactly as it was — no half-applied resolve.
    row = await _row(client, token, msg["id"])
    assert row["intent"] != "please_call_me"
    assert row["status"] == "triage", "a refused resolve must not process the message"


async def test_resolving_attaches_the_message_to_a_project(client, org_a):
    token = org_a["admin_token"]
    msg = await _triage_message(client, token, from_address="project@unknown-example.com")
    project_id = await _make_project(org_a["id"], "Phase 6 attach target")

    resp = await client.post(
        f"/api/v1/inbound/{msg['id']}/resolve",
        headers=auth(token),
        json={"project_id": project_id, "mark_processed": False},
    )
    assert resp.status_code == 200, resp.text

    assert (await _row(client, token, msg["id"]))["matched_project_id"] == project_id


async def test_another_orgs_project_is_not_attachable(client, org_a, org_b):
    """Org isolation is the one thing that must never regress."""
    token = org_a["admin_token"]
    msg = await _triage_message(client, token, from_address="crossorg@unknown-example.com")
    foreign_project = await _make_project(org_b["id"], "Beta's own project")

    resp = await client.post(
        f"/api/v1/inbound/{msg['id']}/resolve",
        headers=auth(token),
        json={"project_id": foreign_project, "mark_processed": False},
    )
    assert resp.status_code == 404, resp.text
    assert (await _row(client, token, msg["id"]))["matched_project_id"] is None


async def test_the_old_resolve_contract_still_works(client, org_a):
    """Back-compatibility: a body with neither new field behaves as before."""
    token = org_a["admin_token"]
    msg = await _triage_message(client, token, from_address="oldclient@unknown-example.com")

    resp = await client.post(
        f"/api/v1/inbound/{msg['id']}/resolve",
        headers=auth(token),
        json={"mark_processed": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert not [m for m in await _queue(client, token) if m["id"] == msg["id"]], \
        "a processed message must leave the triage queue"


async def test_messages_say_who_sent_them(client, org_a):
    """`GET /messages` is org-wide, so the message centre can only offer its
    Mine/All filter if each row names its sender."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import message_service

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Phase 6 Message Co"})
    ).json()

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="agent@alpha-example.com")
        message = await message_service.create_message(
            db, ctx, kind="follow_up", channel="email",
            to_address="ravi@p6-example.com",
            subject="Checking in", body="Just checking in.",
            lead_id=lead["id"],
        )
        await db.commit()
        message_id = message.id

    listed = await client.get("/api/v1/messages?status=all", headers=auth(token))
    assert listed.status_code == 200, listed.text
    mine = [m for m in listed.json() if m["id"] == message_id]
    assert mine, "the drafted message is not in GET /messages"
    assert mine[0]["sender_user_id"] == org_a["agent_id"], \
        "a message centre cannot filter Mine/All without the sender"

    detail = await client.get(f"/api/v1/messages/{message_id}", headers=auth(token))
    assert detail.status_code == 200, detail.text
    assert detail.json()["sender_user_id"] == org_a["agent_id"]
    assert "delivery_log" in detail.json(), "the delivery trace lost its log"


async def _make_project(org_id: str, name: str) -> str:
    """A bare project row — projects are born from the Planner, which needs a
    model call this suite deliberately cannot make."""
    from app.database import SessionLocal
    from app.models.lead import Lead
    from app.models.project import Project

    async with SessionLocal() as db:
        lead = Lead(org_id=org_id, name=f"{name} client")
        db.add(lead)
        await db.flush()
        project = Project(org_id=org_id, lead_id=lead.id, name=name)
        db.add(project)
        await db.commit()
        return project.id
