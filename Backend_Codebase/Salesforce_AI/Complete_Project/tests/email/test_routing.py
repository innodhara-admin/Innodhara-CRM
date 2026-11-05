"""An email waiting on the person owns the conversation (plan Task 7)."""
from __future__ import annotations

import uuid

from app.ai import orchestrator
from app.ai.llm import LlmResponse
from app.database import SessionLocal
from app.models.email_template import EmailFillStatus
from app.models.proposal_fill import FillStatus, ProposalFillSession
from tests.email.helpers import (  # noqa: F401  (layer is a fixture)
    FACTS, ctx_for, layer, make_program,
)
from tests.email.test_agent import (  # noqa: F401  (agent_model is a fixture)
    SUNIL, _call, _client_with, _command, _named_template, _session, agent_model,
)


def _route_to(agent: str) -> LlmResponse:
    return LlmResponse(text='{"agent": "%s", "reason": "test"}' % agent)


async def _asking_email(client, org_a, agent_model, chat) -> None:
    token = org_a["admin_token"]
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL)
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="One question.")])
    await _command(client, token, f"send the final follow-up to {lead}", chat=chat)
    assert (await _session(chat)).status == EmailFillStatus.ASKING


async def test_an_asking_email_fill_owns_the_turn(client, org_a, agent_model, layer):
    layer(by_raw=FACTS)
    chat = f"chat-route-{uuid.uuid4().hex[:6]}"
    await _asking_email(client, org_a, agent_model, chat)
    agent_model([_route_to("query"), LlmResponse(text="Noted.")])
    body = await _command(client, org_a["admin_token"], "Mr.", chat=chat, agent=None)
    assert body["agent"] == "email"


async def test_a_waiting_for_document_fill_does_not_capture_the_chat(
        client, org_a, agent_model, layer):
    layer(by_raw=FACTS)
    token = org_a["admin_token"]
    program_id = await make_program(client, token)
    name = f"Proposal email {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "IBC proposal email.docx", name,
                          program_id=program_id, built="proposal")
    lead = await _client_with(client, token, SUNIL)
    chat = f"chat-wait-{uuid.uuid4().hex[:6]}"
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="No proposal yet.")])
    await _command(client, token, f"send the proposal email to {lead}", chat=chat)
    # Nothing is held: the warning is given before any fill is opened.
    assert await _session(chat) is None
    agent_model([_route_to("proposal"), LlmResponse(text="Which programme?")])
    body = await _command(client, token, f"create the proposal for {lead}",
                          chat=chat, agent=None)
    assert body["agent"] == "proposal"


async def test_one_fill_at_a_time_in_a_chat(client, org_a, agent_model, layer):
    """Review Focus 5, both directions."""
    layer(by_raw=FACTS)
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    chat = f"chat-one-{uuid.uuid4().hex[:6]}"
    async with SessionLocal() as db:
        db.add(ProposalFillSession(
            org_id=ctx.org_id, lead_id="lead-x", program_id="prog-x",
            template_id="tpl-x", template_doc_id="doc-x", user_id=ctx.user_id,
            chat_session_id=chat, status=FillStatus.ASKING,
            tags_json=[{"tag_id": "a" * 12, "outcome": "question", "raw": "<X>"}]))
        await db.commit()
    name = f"Final follow-up {uuid.uuid4().hex[:4]}"
    await _named_template(client, token, "Final follow-up.docx", name)
    lead = await _client_with(client, token, SUNIL)
    agent_model([_call("send_template_email", client=lead, template=name),
                 LlmResponse(text="Finish the proposal first.")])
    body = await _command(client, token, f"send the final follow-up to {lead}",
                          chat=chat)
    result = body["actions"][0]["result"]
    assert result["ok"] is False and "Finish it first" in result["message"]
    assert await _session(chat) is None

    # And the other way: an email asking in a chat is answered by the email
    # agent even when the router names the proposal agent.
    other = f"chat-two-{uuid.uuid4().hex[:6]}"
    await _asking_email(client, org_a, agent_model, other)
    agent_model([_route_to("proposal"), LlmResponse(text="Noted.")])
    body = await _command(client, token, "Mrs.", chat=other, agent=None)
    assert body["agent"] == "email"


def test_router_prompt_names_template_emails_and_keeps_the_others():
    prompt = orchestrator._ROUTER_PROMPT
    assert "own templates" in prompt
    # Lines for the other agents are as they were.
    assert ('- followup: follow-up reminders and follow-up messages — "which '
            'follow-ups are\n  due"') in prompt
    assert "- client: adding a NEW client (a lead)" in prompt


def test_router_knows_sending_an_existing_document_is_an_email():
    """Replay defects 3, 5 and 7 (28 Oct): "IBC proposal mail kalisi" and
    "send the MoU cover letter" opened new documents, and "email X that our
    visit moves" went to the scheduler."""
    prompt = orchestrator._ROUTER_PROMPT
    assert "send the MoU cover letter" in prompt
    assert "kalisi" in prompt and "bhejo" in prompt
    assert 'starts "email <client> that' in prompt


def test_email_agent_must_not_ask_for_details_itself():
    """Replay defect 4: the model listed templates, then asked for the meeting
    details in prose and claimed a draft was ready."""
    from app.ai.agents.email_agent import EmailAgent

    prompt = EmailAgent.system_prompt
    assert "in the same turn" in prompt
    assert "never ask the user for the email's details yourself" in prompt
