"""Task 8: Jarvis drafts a client WhatsApp for the same one-tap approval."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.ai.agents.base import AgentRuntime
from app.ai.agents.email_agent import EmailAgent
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError
from app.models.lead import Contact
from app.models.proposal import Proposal
from app.services import proposal_email_service
from tests.insights.builders import make_lead, make_org, make_user

pytestmark = pytest.mark.asyncio


class _NoModel:
    async def generate_json(self, **_):
        raise AssertionError("no model call was expected")


class _ScriptedModel:
    def __init__(self, text):
        self.text, self.calls = text, []

    async def generate_json(self, **kw):
        self.calls.append(kw)
        return {"text": self.text}


async def _setup(db, phone="09876543210"):
    org = await make_org(db, name="WA Jarvis Org")
    ek = await make_user(db, org, name="Ekaghni Mukherjee", role="sales_lead")
    lead = await make_lead(db, org, name="Nexora Public", state="active", owner=ek,
                           created_at=datetime(2026, 11, 1))
    contact = Contact(org_id=org.id, lead_id=lead.id, name="Ravi Kumar", phone=phone,
                      is_primary=True)
    db.add(contact)
    await db.flush()
    ctx = OrgContext(org_id=org.id, user_id=ek.id, role=ek.role, email=ek.email, name=ek.name)
    return AgentRuntime(db=db, ctx=ctx, extra_context={}), lead


async def test_the_tool_is_offered():
    assert "send_whatsapp_to_client" in [t.name for t in EmailAgent().tools()]


async def test_a_message_in_the_users_words_needs_no_model(db, monkeypatch):
    from app.ai.agents import email_agent

    monkeypatch.setattr(email_agent, "get_model_layer", lambda: _NoModel())
    runtime, _ = await _setup(db)
    result = await EmailAgent()._send_whatsapp(
        runtime, client="Nexora Public", message="We will call you on Monday.")
    assert result["ready_for_approval"] and result["attachment"] is None
    assert result["to"] == "Ravi Kumar <09876543210>"
    [pending] = runtime.pending_approvals
    assert pending["channel"] == "whatsapp" and pending["message_id"] == result["message_id"]
    assert pending["body_preview"] == (
        "Dear Ravi Kumar, here is a message from your account team. We will call you on "
        "Monday. Regards, Ekaghni Mukherjee. You can reply here with any questions.")


async def test_no_message_is_written_by_the_model(db, monkeypatch):
    from app.ai.agents import email_agent

    model = _ScriptedModel("Thank you for meeting us today.")
    monkeypatch.setattr(email_agent, "get_model_layer", lambda: model)
    runtime, _ = await _setup(db)
    result = await EmailAgent()._send_whatsapp(runtime, client="Nexora Public")
    assert "Thank you for meeting us today." in result["body_preview"]
    assert model.calls[0]["purpose"] == "whatsapp.draft"


async def test_the_latest_proposal_is_attached(db, monkeypatch):
    async def rendered(_db, _proposal):
        return None

    monkeypatch.setattr(proposal_email_service, "ensure_rendered_files", rendered)
    runtime, lead = await _setup(db)
    db.add(Proposal(org_id=runtime.ctx.org_id, lead_id=lead.id, program_id="p1",
                    title="IBC Proposal", template_id="t1", template_version=1,
                    content_md="x", pdf_path="orgs/x/proposals/ibc.pdf",
                    created_by=runtime.ctx.user_id))
    await db.flush()
    result = await EmailAgent()._send_whatsapp(
        runtime, client="Nexora Public", attach_proposal=True)
    assert result["attachment"].endswith(".pdf")
    from app.models.messaging import OutboundMessage

    draft = await db.get(OutboundMessage, result["message_id"])
    assert draft.channel == "whatsapp" and draft.kind == "proposal"
    assert draft.attachments[0]["path"] == "orgs/x/proposals/ibc.pdf"
    assert draft.proposal_id is not None


async def test_no_proposal_says_so(db):
    runtime, _ = await _setup(db)
    with pytest.raises(NotFoundError, match="no proposal"):
        await EmailAgent()._send_whatsapp(runtime, client="Nexora Public",
                                          attach_proposal=True)


async def test_a_contact_without_a_phone_is_refused(db):
    runtime, _ = await _setup(db, phone=None)
    with pytest.raises(NotFoundError, match="no phone number"):
        await EmailAgent()._send_whatsapp(runtime, client="Nexora Public", message="x")
