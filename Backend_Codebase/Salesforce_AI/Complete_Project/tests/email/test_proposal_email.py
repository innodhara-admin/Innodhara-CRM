"""The proposal email uses the product's template when there is one (Task 8)."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.ai.llm import LlmResponse
from app.database import SessionLocal
from app.models.email_template import EmailFillSession, EmailFillStatus
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from tests.conftest import auth
from tests.email.helpers import (  # noqa: F401  (layer is a fixture)
    API, FACTS, ctx_for, layer, make_program, make_proposal,
)
from tests.email.test_agent import (  # noqa: F401  (agent_model is a fixture)
    SUNIL, _call, _client_with, _command, _named_template, _session, agent_model,
)

FIXED_LINE = "Please find attached our proposal for"


async def _ground(client, org_a, *contacts, with_template=True):
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    program_id = await make_program(client, token)
    template_id = None
    if with_template:
        template_id = await _named_template(
            client, token, "IBC proposal email.docx",
            f"Proposal email {uuid.uuid4().hex[:4]}", program_id=program_id,
            built="proposal")
    lead_name = await _client_with(client, token, *(contacts or (SUNIL,)))
    async with SessionLocal() as db:
        lead = (await db.execute(select(Lead).where(
            Lead.org_id == ctx.org_id, Lead.name == lead_name))).scalar_one()
    proposal_id = await make_proposal(ctx, lead.id, program_id)
    return token, ctx, proposal_id, template_id, lead_name


async def test_with_a_template_the_proposal_email_uses_it(
        client, org_a, agent_model, layer):
    layer(by_raw=FACTS)
    token, ctx, proposal_id, template_id, _ = await _ground(client, org_a)
    chat = f"chat-pe-{uuid.uuid4().hex[:6]}"
    agent_model([_call("prepare_email", proposal_ref=proposal_id),
                 LlmResponse(text="One question first.")])
    body = await _command(client, token, "send it", chat=chat, agent="proposal")
    asked = next(a for a in body["actions"] if a.get("outcome") == "needs_confirmation")
    assert asked["tool"] == "prepare_email"
    assert asked["candidates"][:3] == ["Mr.", "Ms.", "Mrs."]
    session = await _session(chat)
    assert session.template_id == template_id
    assert session.proposal_id == proposal_id
    assert session.status == EmailFillStatus.ASKING


async def test_without_a_template_the_fixed_email_is_unchanged(
        client, org_a, agent_model, layer):
    layer(by_raw=FACTS)
    token, ctx, proposal_id, _, _ = await _ground(client, org_a, with_template=False)
    chat = f"chat-pf-{uuid.uuid4().hex[:6]}"
    agent_model([_call("prepare_email", proposal_ref=proposal_id),
                 LlmResponse(text="Ready.")])
    body = await _command(client, token, "send it", chat=chat, agent="proposal")
    [approval] = body["pending_approvals"]
    assert approval["kind"] == "proposal_email"
    async with SessionLocal() as db:
        message = await db.get(OutboundMessage, approval["message_id"])
    assert FIXED_LINE in message.body
    assert await _session(chat) is None


async def test_held_recipient_answer_uses_the_template_too(
        client, org_a, agent_model, layer):
    layer(by_raw=FACTS)
    token, ctx, proposal_id, template_id, _ = await _ground(
        client, org_a, SUNIL, {"name": "Rina Das", "email": "rina@sunrise.example"})
    chat = f"chat-ph-{uuid.uuid4().hex[:6]}"
    agent_model([_call("prepare_email", proposal_ref=proposal_id),
                 LlmResponse(text="Who should get it?")])
    body = await _command(client, token, "send it", chat=chat, agent="proposal")
    assert "Who at" in body["actions"][0]["question"]
    agent_model([])   # the held flow answers before any model is asked
    body = await _command(client, token, "Sunil Menon", chat=chat, agent=None)
    session = await _session(chat)
    assert session is not None and session.template_id == template_id
    assert session.to_address == SUNIL["email"]
    asked = body["actions"][0]
    assert asked["outcome"] == "needs_confirmation"
    assert asked["candidates"][:3] == ["Mr.", "Ms.", "Mrs."]


async def test_approve_and_send_button_is_unchanged(client, org_a, layer):
    layer(by_raw=FACTS)
    token, ctx, proposal_id, _, _ = await _ground(client, org_a)
    resp = await client.post(f"{API}/proposals/{proposal_id}/approve-send",
                             headers=auth(token),
                             json={"to_address": SUNIL["email"]})
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as db:
        message = await db.get(OutboundMessage, resp.json()["message_id"])
        sessions = (await db.execute(select(EmailFillSession).where(
            EmailFillSession.proposal_id == proposal_id))).scalars().all()
    assert FIXED_LINE in message.body
    assert sessions == []
