"""Draft the introductory message for a new contact from the organisation's
template, variables filled in, ready for one-tap approval (doc §6, §9.1)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MessageChannel, MessageKind, TemplateKind
from app.core.context import OrgContext
from app.core.exceptions import ValidationFailedError
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.organisation import Organisation
from app.models.user import User
from app.services import message_service, template_service


async def draft_intro_message(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    contact: Contact,
    channel: str = MessageChannel.EMAIL.value,
    program_name: str | None = None,
) -> OutboundMessage:
    if channel == MessageChannel.EMAIL.value and not contact.email:
        raise ValidationFailedError(
            f"{contact.name} has no email on record — add one or use WhatsApp."
        )
    if channel == MessageChannel.WHATSAPP.value and not contact.phone:
        raise ValidationFailedError(
            f"{contact.name} has no phone number on record — add one or use email."
        )

    template = await template_service.get_current_message_template(
        db, ctx.org_id, TemplateKind.INTRO.value, channel
    )
    lead = (
        await db.execute(
            select(Lead).where(Lead.id == contact.lead_id, Lead.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()
    sender = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one_or_none()

    variables = {
        "contact_name": contact.name,
        "contact_title": contact.title or "",
        # Both names are supplied deliberately (finding F11/F6): existing org
        # templates reference {school_name} and must keep rendering, while new
        # ones can use the neutral {client_name}. Removing the old key would
        # silently blank the variable in every template an org already saved.
        "client_name": lead.name if lead else "",
        "school_name": lead.name if lead else "",
        "sender_name": sender.name if sender else ctx.email,
        "sender_email": ctx.email,
        "sender_phone": (sender.phone if sender else None) or "",
        "org_name": org.name,
        "program_name": program_name or "",
    }
    body = template_service.render(template.body, variables)
    subject = (
        template_service.render(template.subject, variables)
        if template.subject
        else f"Great meeting you — {org.name}"
    )

    return await message_service.create_message(
        db,
        ctx,
        kind=MessageKind.INTRO.value,
        channel=channel,
        to_address=contact.email if channel == MessageChannel.EMAIL.value else contact.phone,
        subject=subject if channel == MessageChannel.EMAIL.value else None,
        body=body,
        lead_id=contact.lead_id,
        contact_id=contact.id,
        idempotency_key=f"intro-{contact.id}-{channel}",
        # The card-scan verify sheet tells the user this is "waiting in
        # Approvals". Without an approvals row it was waiting nowhere a screen
        # could reach (finding F2) — and the inbox is the ONLY route to an
        # intro draft, so there is no second, redundant entry to worry about.
        request_approval=True,
    )
