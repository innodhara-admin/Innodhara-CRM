"""A proposal email that can never go out is not handed back (12 Oct 2026).

Live: the first email for a proposal dead-lettered, the proposal was corrected
and rebuilt, and every later "send it" returned that same dead email --
unapprovable, and still attaching the PDF from before the correction.
"""
from __future__ import annotations

import pytest

from app.core.constants import MessageStatus
from app.core.context import OrgContext
from app.database import SessionLocal
from app.services import proposal_email_service, proposal_service
from tests.conftest import auth
from tests.test_proposals import TEMPLATE

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def setup(client, org_a):
    token = org_a["admin_token"]
    program = (await client.post(
        "/api/v1/admin/programs", headers=auth(token),
        json={"name": "Dead Mail", "code": "DEADMAIL12", "description": "d"},
    )).json()
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "items": [
            {"code": "kit", "label": "Kit", "unit": "per kit",
             "unit_price": 500, "default_quantity": 2}]},
    )
    assert (await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token), json={"name": "Standard", "body_md": TEMPLATE},
    )).status_code == 200
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Dead Mail School 12"})).json()
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    proposal = (await client.post(
        "/api/v1/proposals", headers=auth(token),
        json={"lead_id": lead["id"], "program_id": program["id"],
              "context_summary": "A summary."},
    )).json()
    ctx = OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                     role="org_admin", email=me["email"])
    return {"ctx": ctx, "proposal_id": proposal["id"]}


async def _prepare(setup, to):
    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(
            db, setup["ctx"].org_id, setup["proposal_id"])
        msg = await proposal_email_service.prepare_proposal_email(
            db, setup["ctx"], row, to_address=to)
        await db.commit()
        return msg.id, msg.status


async def _set_status(message_id, status):
    from app.models.messaging import OutboundMessage
    async with SessionLocal() as db:
        msg = await db.get(OutboundMessage, message_id)
        msg.status = status
        await db.commit()


@pytest.mark.parametrize("dead", [MessageStatus.DEAD_LETTER.value,
                                  MessageStatus.FAILED.value,
                                  MessageStatus.REJECTED.value])
async def test_a_dead_email_gets_a_fresh_one(setup, dead):
    to = f"{dead}@dead-mail.test"
    first, _ = await _prepare(setup, to)
    await _set_status(first, dead)
    second, status = await _prepare(setup, to)
    assert second != first
    assert status == MessageStatus.PENDING_APPROVAL.value
    # And asking again returns the new one, not a third.
    third, _ = await _prepare(setup, to)
    assert third == second


@pytest.mark.parametrize("alive", [MessageStatus.QUEUED.value,
                                   MessageStatus.SENT.value,
                                   MessageStatus.PENDING_APPROVAL.value])
async def test_a_live_or_sent_email_is_still_the_same_one(setup, alive):
    """The double-send guard is untouched."""
    to = f"{alive}@dead-mail.test"
    first, _ = await _prepare(setup, to)
    await _set_status(first, alive)
    again, status = await _prepare(setup, to)
    assert again == first
    assert status == alive
