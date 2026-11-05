"""Prepare a proposal for emailing: render files, draft the email, and park
it at the one-tap approval gate."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MessageChannel, MessageKind
from app.core.context import OrgContext
from app.core.exceptions import ValidationFailedError
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from app.models.organisation import Organisation
from app.models.proposal import Proposal
from app.models.user import User
from app.services import document_service, message_service, storage
from app.services.docx import convert as docx_convert

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:60] or "Proposal"


async def ensure_rendered_files(db: AsyncSession, proposal: Proposal) -> None:
    """Render DOCX + PDF for the current content if not already rendered.

    A docx-backed proposal already HAS its document — `build_proposal` wrote
    it — so there is nothing to render, only to convert. It deliberately does
    not fall back to the reportlab renderer: that would quietly replace a
    branded proposal with a plain one on the way to a client, which is the
    failure this whole path exists to remove.
    """
    if proposal.docx_path and proposal.pdf_path:
        return
    base = _safe_name(proposal.title)

    if getattr(proposal, "template_kind", "markdown") == "docx" and proposal.docx_path:
        docx_bytes = storage.read_bytes(proposal.org_id, proposal.docx_path)
        pdf_bytes = docx_convert.docx_to_pdf(docx_bytes)
        proposal.pdf_path = storage.save_bytes(
            proposal.org_id, storage.CATEGORY_PROPOSALS, f"{base}.pdf", pdf_bytes
        )
        await db.flush()
        return

    docx_bytes = document_service.render_docx(proposal.content_md, proposal.title)
    pdf_bytes = document_service.render_pdf(proposal.content_md, proposal.title)
    proposal.docx_path = storage.save_bytes(
        proposal.org_id, storage.CATEGORY_PROPOSALS, f"{base}.docx", docx_bytes
    )
    proposal.pdf_path = storage.save_bytes(
        proposal.org_id, storage.CATEGORY_PROPOSALS, f"{base}.pdf", pdf_bytes
    )
    await db.flush()


async def prepare_proposal_email(
    db: AsyncSession,
    ctx: OrgContext,
    proposal: Proposal,
    *,
    to_address: str,
    cc: list[str] | None = None,
    extra_note: str | None = None,
) -> OutboundMessage:
    """Create the proposal email (PDF attached) in PENDING_APPROVAL state."""
    to_address = (to_address or "").strip()
    if not _EMAIL_RE.match(to_address):
        raise ValidationFailedError(f"'{to_address}' is not a valid email address")
    cc = [c.strip() for c in (cc or []) if c.strip()]
    for addr in cc:
        if not _EMAIL_RE.match(addr):
            raise ValidationFailedError(f"CC address '{addr}' is not a valid email")

    await ensure_rendered_files(db, proposal)

    lead = (
        await db.execute(select(Lead).where(Lead.id == proposal.lead_id))
    ).scalar_one_or_none()
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()
    sender = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one_or_none()
    sender_name = sender.name if sender else ctx.email

    contact_name = proposal.variables.get("contact_name", "Sir/Madam")
    subject = f"{proposal.title} — {org.name}"
    body_lines = [
        f"Dear {contact_name},",
        "",
        f"Thank you for your time. Please find attached our proposal for "
        f"{lead.name if lead else 'your organisation'}.",
    ]
    if extra_note:
        body_lines += ["", extra_note]
    body_lines += [
        "",
        "We would be glad to walk you through it at your convenience.",
        "",
        "Warm regards,",
        sender_name,
        org.name,
        ctx.email,
    ]

    return await message_service.create_message(
        db,
        ctx,
        kind=MessageKind.PROPOSAL.value,
        channel=MessageChannel.EMAIL.value,
        to_address=to_address,
        cc=cc,
        subject=subject,
        body="\n".join(body_lines),
        lead_id=proposal.lead_id,
        proposal_id=proposal.id,
        attachments=[
            {"path": proposal.pdf_path, "filename": f"{_safe_name(proposal.title)}.pdf"}
        ],
        idempotency_key=await _live_key(
            db, ctx, f"proposal-email-{proposal.id}-{to_address}"),
    )


async def _live_key(db: AsyncSession, ctx: OrgContext, base: str) -> str:
    """The idempotency key to use: `base`, unless that email is dead.

    The key exists to stop a double send, and it still does: a draft, a queued
    or a sent email under it is returned as it is. But live on 12 Oct 2026 the
    first email for a proposal dead-lettered (the org's mail host was wrong),
    the proposal was then corrected and rebuilt, and every later "send it"
    returned that same dead email -- unapprovable, and still carrying the PDF
    from before the correction. A dead one gets a successor with its own key
    (`base#2`, `base#3`, ...), built from the proposal as it is now.
    """
    from app.core.constants import MessageStatus  # noqa: PLC0415

    dead = {MessageStatus.FAILED.value, MessageStatus.DEAD_LETTER.value,
            MessageStatus.REJECTED.value}
    key, n = base, 1
    while True:
        status = (await db.execute(select(OutboundMessage.status).where(
            OutboundMessage.org_id == ctx.org_id,
            OutboundMessage.idempotency_key == key,
        ))).scalar_one_or_none()
        if status is None or status not in dead:
            return key
        n += 1
        key = f"{base}#{n}"
