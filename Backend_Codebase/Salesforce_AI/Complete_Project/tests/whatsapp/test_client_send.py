"""Task 7: an approved client WhatsApp goes out as a template."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.constants import MessageStatus
from app.core.context import OrgContext
from app.core.crypto import encrypt_secret
from app.core.exceptions import ExternalServiceError
from app.models.lead import Contact
from app.models.organisation import OrgSettings
from app.services import message_service, storage, whatsapp_providers
from tests.insights.builders import make_lead, make_org, make_user

pytestmark = pytest.mark.asyncio


async def _message(db, attachments=None, wati=True):
    org = await make_org(db, name="WA Client Org")
    if wati:
        row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
        row.whatsapp_integration = {"provider": "wati",
                                    "wati_token_enc": encrypt_secret("tok-test")}
    ek = await make_user(db, org, name="Ekaghni Mukherjee", role="sales_lead")
    lead = await make_lead(db, org, name="WA Client", state="active", owner=ek,
                           created_at=datetime(2026, 11, 1))
    contact = Contact(org_id=org.id, lead_id=lead.id, name="Ravi Kumar", phone="09876543210")
    db.add(contact)
    await db.flush()
    ctx = OrgContext(org_id=org.id, user_id=ek.id, role=ek.role, email=ek.email, name=ek.name)
    message = await message_service.create_message(
        db, ctx, kind="follow_up", channel="whatsapp", to_address="09876543210",
        body="Thank you for your time today.\n\nWe will share the plan by Friday.",
        contact_id=contact.id, attachments=attachments)
    message.status = MessageStatus.QUEUED.value
    await db.flush()
    return org, message


@pytest.fixture
def captured(monkeypatch):
    sent = {}

    async def fake_send(cfg, **kw):
        sent.update(kw, provider=cfg.provider)
        return whatsapp_providers.SendResult(True, kw["local_id"])

    monkeypatch.setattr(whatsapp_providers, "send_template", fake_send)
    return sent


async def test_a_text_message_uses_client_message(db, captured):
    _, message = await _message(db)
    await message_service.execute_send(db, message)
    assert message.status == MessageStatus.SENT.value
    assert message.provider_message_id == message.id
    assert captured["provider"] == "wati"
    assert captured["template"] == "client_message"
    assert captured["to"] == "919876543210"
    assert captured["values"] == {
        "contact_name": "Ravi Kumar", "sender_name": "Ekaghni Mukherjee",
        "message": "Thank you for your time today.\n\nWe will share the plan by Friday."}
    assert captured["document_url"] is None


async def test_a_pdf_uses_client_proposal_with_a_signed_link(db, captured, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_base_url", "https://crm.example")
    rel = storage.save_bytes("x", storage.CATEGORY_PROPOSALS, "p.pdf", b"%PDF")
    _, message = await _message(db, attachments=[{"path": rel, "filename": "IBC Proposal.pdf"}])
    await message_service.execute_send(db, message)
    assert captured["template"] == "client_proposal"
    assert captured["values"]["programme"] == "IBC Proposal"
    assert captured["document_url"].startswith("https://crm.example/api/v1/public/wa/")
    assert captured["document_name"] == "IBC Proposal.pdf"


async def test_a_pdf_without_a_public_address_fails_clearly(db, captured, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_base_url", "")
    _, message = await _message(db, attachments=[{"path": "orgs/x/p.pdf", "filename": "P.pdf"}])
    with pytest.raises(ExternalServiceError, match="PUBLIC_BASE_URL"):
        await message_service.execute_send(db, message)


async def test_a_refusal_is_an_error_the_job_can_retry(db, monkeypatch):
    async def refuse(cfg, **kw):
        return whatsapp_providers.SendResult(False, "", "Wati refused: template not approved")

    monkeypatch.setattr(whatsapp_providers, "send_template", refuse)
    _, message = await _message(db)
    with pytest.raises(ExternalServiceError, match="template not approved"):
        await message_service.execute_send(db, message)


async def test_dry_run_still_sends_to_the_outbox(db):
    _, message = await _message(db, wati=False)
    await message_service.execute_send(db, message)
    assert message.status == MessageStatus.SENT.value
    assert message.provider_message_id.startswith("dry_run:")
