"""Jarvis picks, fills and drafts template emails (plan Task 6).

Driven the way tests/docx/test_fill_agent.py drives the proposal agent: a
scripted agent model runs the real tool loop through the real
/assistant/command route, and a second fake answers for the fill pass.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.ai import llm as llm_mod
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.comms import InboundMessage
from app.models.email_template import EmailFillSession, EmailFillStatus
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from app.services import email_choice
from tests.conftest import add_reached_contact, auth, fresh_lead
from tests.email.helpers import (  # noqa: F401  (layer is a fixture)
    API, FACTS, FIXTURES, ctx_for, layer, make_program, make_template,
)


class AgentModel:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0) if self.script else LlmResponse(text="Done.")

    async def generate_json(self, **kwargs):
        return llm_mod.extract_json((await self.generate(**kwargs)).text)


@pytest.fixture
def agent_model(monkeypatch):
    def install(script):
        fake = AgentModel(script)
        monkeypatch.setattr(agent_base, "get_model_layer", lambda: fake)
        monkeypatch.setattr("app.ai.orchestrator.get_model_layer", lambda: fake)
        # draft_custom_email asks its own module for a model; without this the
        # run would reach the real provider named in the live .env.
        monkeypatch.setattr("app.ai.agents.email_agent.get_model_layer", lambda: fake)
        return fake
    return install


def _call(name, **args):
    return LlmResponse(tool_calls=[ToolCall(name=name, args=args,
                                            call_id=uuid.uuid4().hex[:8])])


async def _command(client, token, text, *, chat, agent="email"):
    resp = await client.post(f"{API}/assistant/command", headers=auth(token),
                             json={"text": text, "agent": agent, "session_id": chat})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _asked(body):
    return next((a for a in body["actions"]
                 if a.get("outcome") == "needs_confirmation"), None)


async def _client_with(client, token, *contacts) -> str:
    lead = await fresh_lead(client, token, "Zephyr Vale Academy")
    for fields in contacts:
        await add_reached_contact(client, token, lead["id"], **fields)
    return lead["name"]


SUNIL = {"name": "Sunil Menon", "title": "Head", "email": "sunil@sunrise.example"}


async def _session(chat) -> EmailFillSession:
    async with SessionLocal() as db:
        return (await db.execute(select(EmailFillSession).where(
            EmailFillSession.chat_session_id == chat
        ).order_by(EmailFillSession.created_at.desc()))).scalars().first()


def _salutation_answer(session, value="Mr."):
    return {"resolutions": [{"tag_id": t["tag_id"], "value": value}
                            for t in session.tags_json
                            if t["raw"] == "<ask:Mr.|Ms.|Mrs.>"]}


async def _named_template(client, token, filename, name, **kw) -> str:
    template_id = await make_template(client, token, filename, **kw)
    async with SessionLocal() as db:
        from app.models.email_template import EmailTemplate
        row = await db.get(EmailTemplate, template_id)
        row.name = name
        await db.commit()
    return template_id


async def test_named_template_is_drafted_with_its_attachments(
        client, org_a, agent_model, layer):
    token = org_a["admin_token"]
    await ctx_for(org_a)
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    template_id = await _named_template(client, token, "Final follow-up.docx", name,
                                        category="final_follow_up")
    await client.post(f"{API}/admin/email-templates/{template_id}/attachments",
                      headers=auth(token),
                      files={"file": ("brochure.pdf", b"%PDF b", "application/pdf")})
    lead = await _client_with(client, token, SUNIL)
    fill = layer(by_raw=FACTS)
    chat = f"chat-{uuid.uuid4().hex[:6]}"
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="One question first.")])
    body = await _command(client, token, f"send the final follow-up to {lead}",
                          chat=chat)
    asked = _asked(body)
    assert asked is not None and asked["tool"] == "send_template_email"
    assert asked["candidates"][:3] == ["Mr.", "Ms.", "Mrs."]
    assert "All the suggested values are fine" not in asked["candidates"]

    fill.answers.append(_salutation_answer(await _session(chat)))
    agent_model([_call("answer_email_questions", answer="Mr."),
                 LlmResponse(text="Drafted.")])
    body = await _command(client, token, "Mr.", chat=chat)
    [approval] = body["pending_approvals"]
    assert approval["kind"] == "template_email"
    assert approval["template"] == name
    assert approval["attachments"] == ["brochure.pdf"]
    assert approval["to"] == SUNIL["email"]


async def test_two_matching_templates_ask_with_names_as_taps(
        client, org_a, agent_model, layer):
    token = org_a["admin_token"]
    tag = uuid.uuid4().hex[:4]
    first, second = f"Chase {tag} gentle", f"Chase {tag} firm"
    await _named_template(client, token, "Final follow-up.docx", first)
    await _named_template(client, token, "No reply follow-up.docx", second)
    lead = await _client_with(client, token, SUNIL)
    layer(by_raw=FACTS)
    agent_model([_call("send_template_email", client=lead, template=f"chase {tag}"),
                 LlmResponse(text="Which one?")])
    body = await _command(client, token, f"chase {lead}", chat=f"chat-two-{tag}")
    asked = _asked(body)
    assert asked is not None
    assert sorted(asked["candidates"]) == sorted([first, second])
    assert body["pending_approvals"] == []


async def test_no_template_fits_falls_back_to_custom_email(client, org_a, agent_model):
    token = org_a["admin_token"]
    lead = await _client_with(client, token, SUNIL)
    agent_model([
        _call("draft_custom_email", client=lead, purpose="the visit moves to Thursday"),
        LlmResponse(text='{"subject": "Visit moved", "body": "Dear Sunil, ..."}'),
        LlmResponse(text="Drafted."),
    ])
    body = await _command(client, token,
                          f"email {lead} that our visit moves to Thursday",
                          chat=f"c-{uuid.uuid4().hex[:6]}")
    [approval] = body["pending_approvals"]
    assert approval["kind"] == "custom_email"
    assert approval["subject"] == "Visit moved"   # the scripted draft, not a real model


async def test_recipient_is_never_taken_from_the_template(
        client, org_a, agent_model, layer):
    """Review Focus 4: a recipient the person never named is dropped; with
    two contacts and no main one, Jarvis asks instead of guessing."""
    token = org_a["admin_token"]
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL,
                              {"name": "Rina Das", "email": "rina@sunrise.example"})
    layer(by_raw=FACTS)
    agent_model([_call("send_template_email", client=lead, template=name,
                       contact="Operations Manager"),
                 LlmResponse(text="Who should get it?")])
    body = await _command(client, token, f"send the final follow-up to {lead}",
                          chat=f"c-{uuid.uuid4().hex[:6]}")
    asked = _asked(body)
    assert asked is not None
    assert asked["question"].startswith(f"Who at {lead} should this go to?")
    assert body["pending_approvals"] == []


async def test_contact_without_email_is_asked_about(client, org_a, agent_model, layer):
    token = org_a["admin_token"]
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, {"name": "Phone Only"})
    layer(by_raw=FACTS)
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="No email.")])
    body = await _command(client, token, f"send the final follow-up to {lead}",
                          chat=f"c-{uuid.uuid4().hex[:6]}")
    asked = _asked(body)
    assert asked is not None and "has no email on record" in asked["question"]


async def test_answers_reach_the_fill_even_when_the_model_calls_nothing(
        client, org_a, agent_model, layer):
    token = org_a["admin_token"]
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL)
    fill = layer(by_raw=FACTS)
    chat = f"c-{uuid.uuid4().hex[:6]}"
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="One question.")])
    await _command(client, token, f"send the final follow-up to {lead}", chat=chat)
    fill.answers.append(_salutation_answer(await _session(chat), "Ms."))
    agent_model([LlmResponse(text="Thanks, noted.")])   # calls no tool at all
    body = await _command(client, token, "Ms.", chat=chat)
    assert [a["tool"] for a in body["actions"]][:1] == ["answer_email_questions"]
    assert (await _session(chat)).status == EmailFillStatus.DRAFTED


async def test_missing_proposal_warns_and_drafts_nothing(
        client, org_a, agent_model, layer):
    token = org_a["admin_token"]
    program_id = await make_program(client, token)
    name = f"Proposal email {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "IBC proposal email.docx", name,
                          program_id=program_id, built="proposal")
    lead = await _client_with(client, token, SUNIL)
    layer(by_raw=FACTS)
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="No proposal yet.")])
    body = await _command(client, token, f"send the proposal email to {lead}",
                          chat=f"c-{uuid.uuid4().hex[:6]}")
    result = body["actions"][0]["result"]
    assert result["waiting_for_document"] is True
    assert "will not send this email" in result["message"]
    assert "build the proposal first" in result["message"]
    assert body["pending_approvals"] == []


async def test_cancel_abandons(client, org_a, agent_model, layer):
    token = org_a["admin_token"]
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL)
    layer(by_raw=FACTS)
    chat = f"c-{uuid.uuid4().hex[:6]}"
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="One question.")])
    await _command(client, token, f"send the final follow-up to {lead}", chat=chat)
    agent_model([_call("cancel_template_email"), LlmResponse(text="Cancelled.")])
    await _command(client, token, "cancel that email", chat=chat)
    assert (await _session(chat)).status == EmailFillStatus.ABANDONED


async def test_choices_count_unanswered_follow_ups(client, org_a):
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    lead_name = await _client_with(client, token, SUNIL)
    async with SessionLocal() as db:
        lead = (await db.execute(select(Lead).where(
            Lead.org_id == ctx.org_id, Lead.name == lead_name))).scalar_one()
        for days in (6, 3):
            db.add(OutboundMessage(
                org_id=ctx.org_id, kind="follow_up", channel="email",
                status="sent", lead_id=lead.id, sender_user_id=ctx.user_id,
                to_address="x@y.example", subject="s", body="b",
                idempotency_key=uuid.uuid4().hex,
                sent_at=utcnow() - timedelta(days=days)))
        await db.commit()
        facts = (await email_choice.choices(db, ctx, lead))["facts"]
        assert facts["follow_ups_unanswered"] == 2
        db.add(InboundMessage(org_id=ctx.org_id, channel="email", body="Thanks",
                              matched_lead_id=lead.id,
                              received_at=utcnow() - timedelta(days=1)))
        await db.commit()
        facts = (await email_choice.choices(db, ctx, lead))["facts"]
        assert facts["follow_ups_unanswered"] == 0


async def test_filler_words_do_not_stop_a_name_matching(client, org_a, agent_model, layer):
    """"the zeta welcome email" names "Zeta welcome note": "the" and "email"
    are not part of any template's name and must not force a question."""
    token = org_a["admin_token"]
    tag = uuid.uuid4().hex[:4]
    name = f"Zeta {tag} welcome note"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL)
    layer(by_raw=FACTS)
    chat = f"chat-zeta-{tag}"
    agent_model([_call("send_template_email", client=lead,
                       template=f"the zeta {tag} welcome email"),
                 LlmResponse(text="One question.")])
    await _command(client, token, f"send the zeta {tag} welcome email to {lead}", chat=chat)
    session = await _session(chat)
    assert session is not None
    async with SessionLocal() as db:
        from app.models.email_template import EmailTemplate
        assert (await db.get(EmailTemplate, session.template_id)).name == name


async def test_a_reply_is_answered_even_when_the_model_reruns_the_send_tool(
        client, org_a, agent_model, layer):
    """Replay defect 1 (28 Oct): "Mr." reached send_template_email again, which
    said the email was already open; the answer must still reach the fill."""
    token = org_a["admin_token"]
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL)
    fill = layer(by_raw=FACTS)
    chat = f"chat-rerun-{uuid.uuid4().hex[:6]}"
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="One question.")])
    await _command(client, token, f"send the final follow-up to {lead}", chat=chat)
    fill.answers.append(_salutation_answer(await _session(chat)))
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="It is waiting on you.")])
    await _command(client, token, "Mr.", chat=chat)
    assert (await _session(chat)).status == EmailFillStatus.DRAFTED


async def test_a_missing_proposal_is_said_before_any_recipient_question(
        client, org_a, agent_model, layer):
    """Replay defect 6: with two contacts and no proposal, the person is told
    about the proposal first, not asked who should receive an email that
    cannot be sent."""
    token = org_a["admin_token"]
    program_id = await make_program(client, token)
    name = f"Proposal email {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "IBC proposal email.docx", name,
                          program_id=program_id, built="proposal")
    lead = await _client_with(client, token, SUNIL,
                              {"name": "Rina Das", "email": "rina@sunrise.example"})
    layer(by_raw=FACTS)
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="No proposal yet.")])
    body = await _command(client, token, f"send the proposal email to {lead}",
                          chat=f"chat-pre-{uuid.uuid4().hex[:6]}")
    assert _asked(body) is None
    assert body["actions"][0]["result"]["waiting_for_document"] is True


def test_round_message_does_not_say_email_twice():
    from app.ai.agents.email_fill_tools import round_message

    text = round_message([{"tag_id": "a", "raw": "<ask:>", "context": "Option 1:",
                           "question": "Which day?", "candidates": []}], 1,
                         "IBC proposal email", "Acme")
    assert text.startswith("To write the IBC proposal email for Acme,")
    other = round_message([{"tag_id": "a", "raw": "<ask:>", "context": "x",
                            "question": "q", "candidates": []}], 1, "Onboarding", "Acme")
    assert other.startswith("To write the Onboarding email for Acme,")
