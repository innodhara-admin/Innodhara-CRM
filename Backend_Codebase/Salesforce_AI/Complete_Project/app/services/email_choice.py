# app/services/email_choice.py
"""What Jarvis chooses an email template from (28 Oct 2026).

The organisation's current templates, and the few facts about one client that
decide between similar ones: how many follow-ups have gone unanswered (two or
more means the final follow-up), whether a meeting is booked, and whether the
proposal or MOU a product email carries has been built yet.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import MessageKind, MessageStatus
from app.core.context import OrgContext
from app.models.comms import InboundMessage
from app.models.lead import Lead
from app.models.meeting import Meeting
from app.models.messaging import OutboundMessage
from app.models.program import Program
from app.models.scheduled_meeting import ScheduledMeeting
from app.services import email_fill_service, email_template_service

_SENT = (MessageStatus.SENT.value, MessageStatus.DELIVERED.value)


async def follow_ups_unanswered(db: AsyncSession, org_id: str, lead_id: str) -> int:
    """Follow-up emails sent to this client since it last wrote to us."""
    last_heard = (await db.execute(
        select(func.max(func.coalesce(InboundMessage.received_at,
                                      InboundMessage.created_at)))
        .where(InboundMessage.org_id == org_id,
               InboundMessage.matched_lead_id == lead_id))).scalar_one()
    query = select(func.count(OutboundMessage.id)).where(
        OutboundMessage.org_id == org_id, OutboundMessage.lead_id == lead_id,
        OutboundMessage.channel == "email",
        OutboundMessage.kind == MessageKind.FOLLOW_UP.value,
        OutboundMessage.status.in_(_SENT))
    if last_heard is not None:
        query = query.where(OutboundMessage.sent_at > last_heard)
    return int((await db.execute(query)).scalar_one())


async def choices(db: AsyncSession, ctx: OrgContext, lead: Lead) -> dict[str, Any]:
    templates = await email_template_service.current_templates(db, ctx.org_id)
    products = dict((await db.execute(select(Program.id, Program.name).where(
        Program.org_id == ctx.org_id))).all())
    rows = []
    for t in templates:
        built = await email_fill_service.built_document_for(db, ctx, t, lead.id)
        rows.append({
            "id": t.id, "name": t.name, "type": t.template_type,
            "category": t.category, "product": products.get(t.program_id),
            "when_to_use": t.when_to_use, "built_document": t.built_document,
            "has_built_document": built is not None,
        })

    today = clock.today(await clock.org_zone(db, ctx.org_id))
    booked = (await db.execute(select(ScheduledMeeting).where(
        ScheduledMeeting.org_id == ctx.org_id, ScheduledMeeting.lead_id == lead.id,
        ScheduledMeeting.status != "cancelled",
        ScheduledMeeting.meeting_date >= today,
    ).order_by(ScheduledMeeting.meeting_date))).scalars().first()
    last_meeting = (await db.execute(select(func.max(Meeting.created_at)).where(
        Meeting.org_id == ctx.org_id, Meeting.lead_id == lead.id))).scalar_one()
    return {
        "client": lead.name,
        "templates": rows,
        "facts": {
            "follow_ups_unanswered": await follow_ups_unanswered(
                db, ctx.org_id, lead.id),
            "booked_meeting": None if booked is None else {
                "date": booked.meeting_date.isoformat(),
                "start_time": booked.start_time},
            "last_meeting_at": last_meeting.isoformat() if last_meeting else None,
        },
    }
