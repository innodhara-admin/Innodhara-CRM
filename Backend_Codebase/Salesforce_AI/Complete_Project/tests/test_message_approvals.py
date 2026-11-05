"""Finding F2 — a message that says "waiting in Approvals" must actually be
waiting in Approvals, and must stop waiting once it has been decided.

`message_service.create_message` puts a message in PENDING_APPROVAL, but the
Approvals inbox is driven by the separate `approvals` table. Two services —
the card-scan intro and the demo invite — created the message and no approval,
so both told the user their draft was "waiting in Approvals" while
`GET /approvals?status=pending` was empty and no screen could reach it.

The second half is the mirror image, found while fixing the first: a message
can also be decided directly with `POST /messages/{id}/approve|reject` (the
follow-up queue and the Jarvis inline bars do that), which used to leave its
approvals row `pending` for the full 48-hour expiry, pointing at work already
done.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def intro_template(client, org_a):
    """The org needs a current intro template before anything can be drafted."""
    resp = await client.post(
        "/api/v1/admin/message-templates",
        headers=auth(org_a["admin_token"]),
        json={
            "kind": "intro", "channel": "email", "name": "F2 intro",
            "subject": "Great meeting you, {{contact_name}}",
            "body": "Dear {{contact_name}},\n\nThank you for your time.\n\n"
                    "{{sender_name}}",
            "make_current": True,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _lead_with_contact(client, token, name: str) -> tuple[str, str]:
    lead = (
        await client.post("/api/v1/leads", headers=auth(token), json={"name": name})
    ).json()
    contact = (
        await client.post(
            f"/api/v1/leads/{lead['id']}/contacts",
            headers=auth(token),
            json={"name": "Meera Joshi", "title": "Head of Operations",
                  "email": "meera@f2-example.com", "is_primary": True},
        )
    ).json()
    return lead["id"], contact["id"]


async def _pending_approvals(client, token) -> list[dict]:
    resp = await client.get("/api/v1/approvals?status=pending", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_intro_draft_is_reachable_in_the_approvals_inbox(client, org_a, intro_template):
    """The card-scan sheet says "it is waiting in Approvals, nothing was sent."
    That sentence has to be true."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.lead import Contact
    from app.services import intro_service
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead_id, contact_id = await _lead_with_contact(client, token, "F2 Intro Co")

    before = {a["id"] for a in await _pending_approvals(client, token)}

    async with SessionLocal() as db:
        contact = (
            await db.execute(select(Contact).where(Contact.id == contact_id))
        ).scalar_one()
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="agent@alpha-example.com")
        message = await intro_service.draft_intro_message(db, ctx, contact=contact)
        await db.commit()
        message_id = message.id

    after = await _pending_approvals(client, token)
    new = [a for a in after if a["id"] not in before]
    assert new, "the intro draft filed no approval — it is unreachable (F2)"
    assert any(a["entity_type"] == "outbound_message" and a["entity_id"] == message_id
               for a in new), \
        f"no approval points at the intro message: {new}"


async def test_deciding_a_message_directly_closes_its_approval(client, org_a, intro_template):
    """Approving from the message (follow-up queue / Jarvis inline bar) must not
    leave a phantom approval sitting in someone's inbox."""
    from app.core.constants import ApprovalStatus
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.comms import Approval
    from app.models.lead import Contact
    from app.services import intro_service
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead_id, contact_id = await _lead_with_contact(client, token, "F2 Close Co")

    async with SessionLocal() as db:
        contact = (
            await db.execute(select(Contact).where(Contact.id == contact_id))
        ).scalar_one()
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="agent@alpha-example.com")
        message = await intro_service.draft_intro_message(db, ctx, contact=contact)
        await db.commit()
        message_id = message.id

    async with SessionLocal() as db:
        pending = (await db.execute(
            select(Approval).where(
                Approval.entity_id == message_id,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )).scalars().all()
    assert len(pending) == 1, f"expected exactly one pending approval, got {len(pending)}"

    resp = await client.post(f"/api/v1/messages/{message_id}/approve", headers=auth(token))
    assert resp.status_code == 200, resp.text

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Approval).where(Approval.entity_id == message_id)
        )).scalars().all()
    assert rows, "the approval vanished — it should be resolved, not deleted"
    assert all(r.status != ApprovalStatus.PENDING.value for r in rows), \
        "approving the message left its approval pending — a phantom in the inbox"
    assert all(r.decided_at is not None for r in rows)


async def test_repeating_a_draft_does_not_file_a_second_approval(client, org_a, intro_template):
    """create_message is idempotent on its key; the approval must be too, or a
    retried card scan quietly doubles the inbox."""
    from app.core.constants import ApprovalStatus
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.comms import Approval
    from app.models.lead import Contact
    from app.services import intro_service
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead_id, contact_id = await _lead_with_contact(client, token, "F2 Idempotent Co")

    for _ in range(2):
        async with SessionLocal() as db:
            contact = (
                await db.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                             role="sales_agent", email="agent@alpha-example.com")
            message = await intro_service.draft_intro_message(db, ctx, contact=contact)
            await db.commit()
            message_id = message.id

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Approval).where(
                Approval.entity_id == message_id,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )).scalars().all()
    assert len(rows) == 1, f"a repeated draft filed {len(rows)} approvals"
