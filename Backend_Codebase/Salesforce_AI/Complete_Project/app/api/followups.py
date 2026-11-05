"""Follow-ups: due list, create, complete (auto-schedules the next reminder)."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_permission, require_permission
from app.core import clock
from app.core.constants import FollowUpStatus
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.database import get_db
from app.models.base import utcnow
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.organisation import OrgSettings
from app.services import lead_service

router = APIRouter(prefix="/followups", tags=["followups"])


class CreateFollowUpRequest(BaseModel):
    lead_id: str
    due_date: date
    channel: str = "email"  # email | whatsapp | call
    note: str | None = None
    owner_id: str | None = None


class CompleteRequest(BaseModel):
    sent_message_id: str | None = None
    note: str | None = None
    schedule_next: bool = True


async def _followup_dict(db: AsyncSession, f: FollowUp) -> dict:
    lead_name = (
        await db.execute(select(Lead.name).where(Lead.id == f.lead_id))
    ).scalar_one_or_none()
    return {
        "id": f.id,
        "lead_id": f.lead_id,
        "school": lead_name,
        "due_date": f.due_date.isoformat(),
        "channel": f.channel,
        "status": f.status,
        "note": f.note,
        "owner_id": f.owner_id,
        "completed_at": f.completed_at.isoformat() if f.completed_at else None,
    }


@router.get("")
async def list_followups(
    due: str = "today",  # today | overdue | this_week | all_pending | all
    mine: bool = True,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(FollowUp).where(FollowUp.org_id == ctx.org_id)
    if due != "all":
        stmt = stmt.where(FollowUp.status == FollowUpStatus.PENDING.value)
    today = clock.today(await clock.org_zone(db, ctx.org_id))
    if due == "today":
        stmt = stmt.where(FollowUp.due_date <= today)
    elif due == "overdue":
        stmt = stmt.where(FollowUp.due_date < today)
    elif due == "this_week":
        stmt = stmt.where(FollowUp.due_date <= today + timedelta(days=7))
    if mine:
        stmt = stmt.where(FollowUp.owner_id == ctx.user_id)
    followups = (
        await db.execute(stmt.order_by(FollowUp.due_date).limit(100))
    ).scalars().all()
    return [await _followup_dict(db, f) for f in followups]


@router.post("")
async def create_followup(
    body: CreateFollowUpRequest,
    # Booking a conversation is sales work AND relationship work. See
    # `require_any_permission` for why this is not a wider `manage_leads`.
    ctx: OrgContext = Depends(
        require_any_permission("manage_leads", "manage_relationships")
    ),
    db: AsyncSession = Depends(get_db),
):
    await lead_service.get_lead(db, ctx.org_id, body.lead_id)
    if body.channel not in ("email", "whatsapp", "call"):
        raise ValidationFailedError("channel must be email, whatsapp or call")
    followup = FollowUp(
        org_id=ctx.org_id,
        lead_id=body.lead_id,
        owner_id=body.owner_id or ctx.user_id,
        due_date=body.due_date,
        channel=body.channel,
        note=body.note,
        created_by=ctx.user_id,
    )
    db.add(followup)
    await db.commit()
    return await _followup_dict(db, followup)


@router.post("/{followup_id}/complete")
async def complete_followup(
    followup_id: str,
    body: CompleteRequest,
    ctx: OrgContext = Depends(
        require_any_permission("manage_leads", "manage_relationships")
    ),
    db: AsyncSession = Depends(get_db),
):
    """Mark done; the lead is updated and the next reminder is set (doc §9.4)."""
    followup = (
        await db.execute(
            select(FollowUp).where(
                FollowUp.id == followup_id, FollowUp.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if followup is None:
        raise NotFoundError("Follow-up not found")
    followup.status = FollowUpStatus.DONE.value
    followup.completed_at = utcnow()
    followup.message_id = body.sent_message_id
    if body.note:
        followup.note = ((followup.note or "") + f"\nDone: {body.note}").strip()
    await lead_service.touch(db, ctx.org_id, followup.lead_id)

    next_due = None
    if body.schedule_next:
        settings_row = (
            await db.execute(
                select(OrgSettings).where(OrgSettings.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        cadence = settings_row.followup_cadence_days if settings_row else 7
        tz = clock.zone(settings_row.timezone if settings_row else None)
        next_followup = FollowUp(
            org_id=ctx.org_id,
            lead_id=followup.lead_id,
            owner_id=followup.owner_id or ctx.user_id,
            due_date=clock.today(tz) + timedelta(days=cadence),
            channel=followup.channel,
            note="Auto-scheduled after previous follow-up",
            created_by="system",
        )
        db.add(next_followup)
        await db.flush()
        next_due = next_followup.due_date.isoformat()

    await db.commit()
    return {"completed": True, "next_followup_due": next_due}
