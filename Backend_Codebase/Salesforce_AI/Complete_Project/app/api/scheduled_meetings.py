"""Meetings arranged with a client — their own path, separate from demos.

Customer ask, 21 Sep 2026. See app/services/meeting_invite_service.py for the
rules; this module is only the HTTP surface. Anyone who can see clients
(`view_leads`) may list, arrange and cancel meetings.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from app.models.scheduled_meeting import ScheduledMeeting
from app.services import meeting_invite_service

router = APIRouter(prefix="/scheduled-meetings", tags=["meetings"])


class ScheduleRequest(BaseModel):
    lead_id: str
    date: date
    time: str | None = Field(default=None, description="HH:MM, 24-hour")
    duration_minutes: int | None = None
    purpose: str | None = Field(default=None, max_length=2000)
    cc: list[str] = []
    bcc: list[str] = []


async def _dict(db: AsyncSession, m: ScheduledMeeting,
                invite: OutboundMessage | None = None) -> dict:
    client = (await db.execute(select(Lead.name).where(Lead.id == m.lead_id))).scalar_one_or_none()
    if invite is None and m.invite_message_id:
        invite = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.id == m.invite_message_id))).scalar_one_or_none()
    notes = {
        "no_contact": "No invite drafted: the client has no contact with an email address.",
        "rejected": "The invite was rejected without a reason, so it was not redrafted.",
        "pending_approval": "The invite is waiting in Approvals.",
    }
    return {
        "id": m.id,
        "lead_id": m.lead_id,
        "client": client,
        "date": m.meeting_date.isoformat(),
        "time": m.start_time,
        "duration_minutes": m.duration_minutes,
        "purpose": m.purpose,
        "status": m.status,
        "source": m.source,
        "cc": m.cc or [],
        "bcc": m.bcc or [],
        "organizer_id": m.organizer_id,
        "action_item_id": m.action_item_id,
        "google_calendar": bool(m.calendar_event_id),
        "invite": ({"message_id": invite.id, "status": invite.status}
                   if invite is not None else None),
        "invite_note": notes.get(m.invite_status or "", ""),
    }


async def _get(db: AsyncSession, ctx: OrgContext, meeting_id: str) -> ScheduledMeeting:
    m = (await db.execute(select(ScheduledMeeting).where(
        ScheduledMeeting.org_id == ctx.org_id, ScheduledMeeting.id == meeting_id))
    ).scalar_one_or_none()
    if m is None:
        raise NotFoundError("Meeting not found")
    return m


@router.get("")
async def list_meetings(
    lead_id: str | None = None,
    include_cancelled: bool = False,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ScheduledMeeting).where(ScheduledMeeting.org_id == ctx.org_id)
    if lead_id:
        stmt = stmt.where(ScheduledMeeting.lead_id == lead_id)
    if not include_cancelled:
        stmt = stmt.where(ScheduledMeeting.status != "cancelled")
    rows = (await db.execute(
        stmt.order_by(ScheduledMeeting.meeting_date, ScheduledMeeting.start_time).limit(200)
    )).scalars().all()
    return [await _dict(db, m) for m in rows]


@router.post("")
async def schedule_meeting(
    body: ScheduleRequest,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = (await db.execute(select(Lead).where(
        Lead.org_id == ctx.org_id, Lead.id == body.lead_id))).scalar_one_or_none()
    if lead is None:
        raise NotFoundError("Client not found")
    meeting, invite = await meeting_invite_service.schedule(
        db, ctx, lead=lead, on_date=body.date, time_hhmm=body.time,
        duration_minutes=body.duration_minutes, purpose=body.purpose,
        cc=body.cc, bcc=body.bcc, source="app",
    )
    out = await _dict(db, meeting, invite)
    await db.commit()
    return out


@router.post("/{meeting_id}/cancel")
async def cancel_meeting(
    meeting_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    meeting = await _get(db, ctx, meeting_id)
    invite = await meeting_invite_service.cancel(db, ctx, meeting)
    out = await _dict(db, meeting, invite)
    await db.commit()
    return out
