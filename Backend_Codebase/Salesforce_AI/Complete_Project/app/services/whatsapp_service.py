"""WhatsApp to a client: an approved OutboundMessage, sent as a template.

Until 4 Nov 2026 this posted plain text to the Meta Cloud API, which WhatsApp
only delivers inside the 24 hours after the client last wrote to us. A
business-started message must be an approved template, so every client message
now goes out as one, through the organisation's provider (Wati or Meta, see
whatsapp_providers.py):

* a message carrying a PDF (a proposal) -> `client_proposal`, the PDF as its
  document header, fetched from a 7-day signed link;
* anything else -> `client_message`, the approved text as one value.

Dry run is unchanged in spirit: without WHATSAPP_MODE=cloud_api or the
provider's credentials, the request is written to the outbox folder.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import signed_links
from app.core.exceptions import ExternalServiceError
from app.models.lead import Contact
from app.models.messaging import OutboundMessage
from app.models.user import User
from app.services import whatsapp_providers, whatsapp_settings
from app.services.whatsapp_text import normalise_phone


# The client_message template adds "Dear <name>," and "Regards, <sender>". A
# body drafted as a letter (an organisation's intro template, a follow-up)
# already has both, and would read them twice (final review, 4 Nov 2026).
_GREETING = re.compile(r"^\s*(dear|hi|hello|hey)\b[^\n.?:]{0,50}[,!]?\s*\n", re.IGNORECASE)
_SIGN_OFF = re.compile(
    r"(?:^|(?<=[.!?])\s+|\n+)\s*(warm regards|kind regards|best regards|thanks and regards"
    r"|regards|sincerely|cheers|thanks|thank you)\b\s*[,!.]?\s*(?:\n?[^\n.!?]{0,40})?\s*$",
    re.IGNORECASE)


def message_value(body: str) -> str:
    """The body without its own greeting line and sign-off."""
    text = (body or "").strip()
    stripped = _GREETING.sub("", text, count=1).strip()
    match = _SIGN_OFF.search(stripped)
    if match and match.start() > 0:
        stripped = stripped[:match.start()].strip()
    return stripped or text


def _pdf(message: OutboundMessage) -> dict | None:
    for att in message.attachments or []:
        if str(att.get("path") or "").lower().endswith(".pdf"):
            return att
    return None


async def send_client_message(
    db: AsyncSession, message: OutboundMessage, sender: User | None
) -> str:
    """Send one approved client WhatsApp. Returns the provider's id; raises
    ExternalServiceError when it did not go (the send job retries, then
    dead-letters and flags the message)."""
    cfg = await whatsapp_settings.for_org(db, message.org_id)
    to = normalise_phone(message.to_address, cfg.country_code)
    if to is None:
        raise ExternalServiceError("The client's number is not one WhatsApp can use")
    contact = None
    if message.contact_id:
        contact = (
            await db.execute(select(Contact).where(
                Contact.id == message.contact_id, Contact.org_id == message.org_id))
        ).scalar_one_or_none()
    contact_name = (contact.name if contact else None) or "Sir/Madam"
    sender_name = (sender.name if sender else None) or "Sales"

    pdf = _pdf(message)
    document_url = document_name = None
    if pdf is not None:
        document_name = pdf.get("filename") or "document.pdf"
        document_url = signed_links.public_url(signed_links.make(
            {"k": "file", "o": message.org_id, "p": pdf["path"], "n": document_name}))
        if document_url is None:
            raise ExternalServiceError(
                "PUBLIC_BASE_URL is not set on the server, so a document cannot be "
                "sent on WhatsApp")
        template = "client_proposal"
        values = {"contact_name": contact_name,
                  "programme": await _programme(db, message, document_name),
                  "sender_name": sender_name}
    else:
        template = "client_message"
        values = {"contact_name": contact_name, "message": message_value(message.body),
                  "sender_name": sender_name}

    result = await whatsapp_providers.send_template(
        cfg, org_id=message.org_id, to=to, template=template, values=values,
        document_url=document_url, document_name=document_name, local_id=message.id)
    if not result.ok:
        raise ExternalServiceError(result.error or "WhatsApp refused the message")
    return result.provider_id


async def _programme(db: AsyncSession, message: OutboundMessage, document_name: str) -> str:
    """What the proposal is for: its title, not the file's safe name."""
    if message.proposal_id:
        from app.models.proposal import Proposal

        title = (
            await db.execute(select(Proposal.title).where(
                Proposal.id == message.proposal_id, Proposal.org_id == message.org_id))
        ).scalar_one_or_none()
        if title:
            return title
    return document_name.rsplit(".", 1)[0]
