"""Email follow-ups use the organisation's follow-up templates (plan Task 9)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.ai.llm import LlmResponse
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from tests.conftest import create_org
from tests.email.helpers import FACTS, ctx_for, layer  # noqa: F401  (fixture)
from tests.email.test_agent import (  # noqa: F401  (agent_model is a fixture)
    SUNIL, AgentModel, _call, _client_with, _command, _named_template, _session,
)


@pytest.fixture
def agent_model(monkeypatch):
    def install(script):
        fake = AgentModel(script)
        monkeypatch.setattr("app.ai.agents.base.get_model_layer", lambda: fake)
        monkeypatch.setattr("app.ai.orchestrator.get_model_layer", lambda: fake)
        # The follow-up draft asks its own module for a model.
        monkeypatch.setattr("app.ai.agents.followup_agent.get_model_layer",
                            lambda: fake)
        return fake
    return install


async def _org(client, super_token, label: str) -> dict:
    tag = uuid.uuid4().hex[:6]
    return await create_org(client, super_token, name=f"Followup {label} {tag}",
                            slug=f"fu-{label}-{tag}", domain=f"fu{tag}.example")


async def _templated_org(client, super_token):
    org = await _org(client, super_token, "t")
    token = org["admin_token"]
    await _named_template(client, token, "No reply follow-up.docx", "No reply follow-up",
                          category="follow_up")
    await _named_template(client, token, "Final follow-up.docx", "Final follow-up",
                          category="final_follow_up")
    return org


async def test_email_follow_up_uses_the_template(client, super_token, agent_model, layer):
    layer(by_raw=FACTS)
    org = await _templated_org(client, super_token)
    lead = await _client_with(client, org["admin_token"], SUNIL)
    chat = f"chat-fu-{uuid.uuid4().hex[:6]}"
    agent_model([_call("draft_followup_message", client=lead, channel="email"),
                 LlmResponse(text="One question.")])
    body = await _command(client, org["admin_token"], f"follow up with {lead} by email",
                          chat=chat, agent="followup")
    asked = next(a for a in body["actions"] if a.get("outcome") == "needs_confirmation")
    assert asked["tool"] == "draft_followup_message"
    session = await _session(chat)
    async with SessionLocal() as db:
        from app.models.email_template import EmailTemplate
        assert (await db.get(EmailTemplate, session.template_id)).name == "No reply follow-up"


async def test_two_unanswered_picks_the_final_follow_up(
        client, super_token, agent_model, layer):
    layer(by_raw=FACTS)
    org = await _templated_org(client, super_token)
    lead_name = await _client_with(client, org["admin_token"], SUNIL)
    ctx = await ctx_for(org)
    async with SessionLocal() as db:
        lead = (await db.execute(select(Lead).where(
            Lead.org_id == ctx.org_id, Lead.name == lead_name))).scalar_one()
        for days in (9, 4):
            db.add(OutboundMessage(
                org_id=ctx.org_id, kind="follow_up", channel="email", status="sent",
                lead_id=lead.id, sender_user_id=ctx.user_id, to_address="x@y.example",
                subject="s", body="b", idempotency_key=uuid.uuid4().hex,
                sent_at=utcnow() - timedelta(days=days)))
        await db.commit()
    chat = f"chat-fu-{uuid.uuid4().hex[:6]}"
    agent_model([_call("draft_followup_message", client=lead_name, channel="email"),
                 LlmResponse(text="One question.")])
    await _command(client, org["admin_token"], f"follow up with {lead_name}",
                   chat=chat, agent="followup")
    session = await _session(chat)
    async with SessionLocal() as db:
        from app.models.email_template import EmailTemplate
        assert (await db.get(EmailTemplate, session.template_id)).name == "Final follow-up"


async def test_no_template_keeps_todays_draft(client, super_token, agent_model, layer):
    layer(by_raw=FACTS)
    org = await _org(client, super_token, "n")
    lead = await _client_with(client, org["admin_token"], SUNIL)
    chat = f"chat-fu-{uuid.uuid4().hex[:6]}"
    model = agent_model([
        _call("draft_followup_message", client=lead, channel="email"),
        LlmResponse(text='{"subject": "Following up", "body": "Dear Sunil, ..."}'),
        LlmResponse(text="Drafted."),
    ])
    body = await _command(client, org["admin_token"], f"follow up with {lead}",
                          chat=chat, agent="followup")
    [approval] = body["pending_approvals"]
    assert approval["kind"] == "follow_up"
    assert await _session(chat) is None
    assert any(c.get("purpose") == "followup.draft" for c in model.calls)


async def test_whatsapp_follow_up_unchanged(client, super_token, agent_model, layer):
    layer(by_raw=FACTS)
    org = await _templated_org(client, super_token)
    lead = await _client_with(client, org["admin_token"],
                              {**SUNIL, "phone": "+91 90000 22222"})
    chat = f"chat-fu-{uuid.uuid4().hex[:6]}"
    agent_model([
        _call("draft_followup_message", client=lead, channel="whatsapp"),
        LlmResponse(text='{"subject": "", "body": "Hi Sunil, following up."}'),
        LlmResponse(text="Drafted."),
    ])
    body = await _command(client, org["admin_token"], f"whatsapp {lead}",
                          chat=chat, agent="followup")
    [approval] = body["pending_approvals"]
    assert approval["channel"] == "whatsapp"
    assert await _session(chat) is None
