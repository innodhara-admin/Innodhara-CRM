"""Demos: schedule, list, complete, and the month calendar view (doc §9.3)."""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.constants import DemoStatus
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.database import get_db
from app.models.base import utcnow
from app.models.demo import Demo, DemoTeam
from app.models.lead import Lead
from app.models.organisation import OrgSettings
from app.services import audit_service, calendar_service, demo_invite_service, lead_service

router = APIRouter(prefix="/demos", tags=["demos"])


class CreateDemoRequest(BaseModel):
    lead_id: str
    scheduled_date: date
    scheduled_time: str | None = None  # "10:30"
    team_id: str | None = None
    notes: str | None = None


class UpdateDemoRequest(BaseModel):
    scheduled_date: date | None = None
    scheduled_time: str | None = None
    team_id: str | None = None
    status: str | None = None
    notes: str | None = None


async def _demo_dict(db: AsyncSession, demo: Demo) -> dict:
    school = (
        await db.execute(select(Lead.name).where(Lead.id == demo.lead_id))
    ).scalar_one_or_none()
    team = (
        await db.execute(select(DemoTeam.name).where(DemoTeam.id == demo.team_id))
    ).scalar_one_or_none()
    return {
        "id": demo.id,
        "lead_id": demo.lead_id,
        "school": school,
        "team_id": demo.team_id,
        "team": team,
        "date": demo.scheduled_date.isoformat(),
        "time": demo.scheduled_time,
        "status": demo.status,
        "notes": demo.notes,
    }


@router.get("")
async def list_demos(
    month: str | None = None,  # YYYY-MM
    team_id: str | None = None,
    include_cancelled: bool = False,
    ctx: OrgContext = Depends(require_permission("view_demos")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Demo).where(Demo.org_id == ctx.org_id)
    if not include_cancelled:
        stmt = stmt.where(Demo.status != DemoStatus.CANCELLED.value)
    if month:
        try:
            year_s, month_s = month.split("-")
            start = date(int(year_s), int(month_s), 1)
        except ValueError:
            raise ValidationFailedError("month must be YYYY-MM")
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        stmt = stmt.where(Demo.scheduled_date >= start, Demo.scheduled_date < end)
    if team_id:
        stmt = stmt.where(Demo.team_id == team_id)
    demos = (
        await db.execute(stmt.order_by(Demo.scheduled_date).limit(200))
    ).scalars().all()
    return [await _demo_dict(db, d) for d in demos]


@router.get("/calendar")
async def calendar_view(
    year: int,
    month: int,
    team_id: str | None = None,
    ctx: OrgContext = Depends(require_permission("view_demos")),
    db: AsyncSession = Depends(get_db),
):
    """Full-month grid (up to 31 days) with demos per date — free and busy
    days at a glance (doc §9.3.4)."""
    if not (1 <= month <= 12):
        raise ValidationFailedError("month must be 1-12")
    days_in_month = monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    stmt = select(Demo).where(
        Demo.org_id == ctx.org_id,
        Demo.scheduled_date >= start,
        Demo.scheduled_date < end,
        Demo.status != DemoStatus.CANCELLED.value,
    )
    if team_id:
        stmt = stmt.where(Demo.team_id == team_id)
    demos = (await db.execute(stmt)).scalars().all()

    grid: dict[str, list[dict]] = {
        date(year, month, day).isoformat(): [] for day in range(1, days_in_month + 1)
    }
    for demo in demos:
        grid[demo.scheduled_date.isoformat()].append(await _demo_dict(db, demo))
    return {
        "year": year,
        "month": month,
        "days_in_month": days_in_month,
        "days": grid,
        "free_days": [d for d, items in grid.items() if not items],
        "total_demos": len(demos),
    }


@router.post("")
async def schedule_demo(
    body: CreateDemoRequest,
    ctx: OrgContext = Depends(require_permission("schedule_demos")),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.get_lead(db, ctx.org_id, body.lead_id)
    team = None
    if body.team_id:
        team = (
            await db.execute(
                select(DemoTeam).where(
                    DemoTeam.id == body.team_id, DemoTeam.org_id == ctx.org_id
                )
            )
        ).scalar_one_or_none()
        if team is None:
            raise NotFoundError("Demo team not found")

    clash_warning = None
    if team:
        clash = (
            await db.execute(
                select(Demo).where(
                    Demo.org_id == ctx.org_id,
                    Demo.team_id == team.id,
                    Demo.scheduled_date == body.scheduled_date,
                    Demo.status == DemoStatus.SCHEDULED.value,
                )
            )
        ).scalars().first()
        if clash:
            clash_warning = f"{team.name} already has a demo on {body.scheduled_date}"

    demo = Demo(
        org_id=ctx.org_id,
        lead_id=body.lead_id,
        team_id=body.team_id,
        scheduled_date=body.scheduled_date,
        scheduled_time=body.scheduled_time,
        notes=body.notes,
        created_by=ctx.user_id,
    )
    db.add(demo)
    await db.flush()

    settings_row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == ctx.org_id))
    ).scalar_one_or_none()
    event_id = await calendar_service.create_event(
        org_calendar_integration=settings_row.calendar_integration if settings_row else None,
        title=f"Demo: {lead.name}" + (f" ({team.name})" if team else ""),
        description=body.notes or "",
        on_date=body.scheduled_date,
        time_hhmm=body.scheduled_time,
    )
    if event_id:
        demo.calendar_event_id = event_id
    invite = await demo_invite_service.compose_demo_invite(
        db, ctx, demo=demo, lead=lead, team=team, change="scheduled"
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="demo.scheduled",
        entity_type="demo", entity_id=demo.id,
        detail={"school": lead.name, "date": body.scheduled_date.isoformat()},
    )
    await db.commit()
    result = await _demo_dict(db, demo)
    result["invite_message_id"] = invite.id if invite else None
    if invite is None:
        result["invite_note"] = "No contact email on the lead — no invite drafted"
    if clash_warning:
        result["warning"] = clash_warning
    return result


@router.patch("/{demo_id}")
async def update_demo(
    demo_id: str,
    body: UpdateDemoRequest,
    ctx: OrgContext = Depends(require_permission("update_demo_status")),
    db: AsyncSession = Depends(get_db),
):
    demo = (
        await db.execute(
            select(Demo).where(Demo.id == demo_id, Demo.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if demo is None:
        raise NotFoundError("Demo not found")
    if body.status is not None:
        try:
            new_status = DemoStatus(body.status)
        except ValueError:
            raise ValidationFailedError(f"Unknown status '{body.status}'")
        demo.status = new_status.value
        if new_status in (DemoStatus.COMPLETED, DemoStatus.CANCELLED):
            demo.completed_at = utcnow()
        if new_status == DemoStatus.CANCELLED and demo.calendar_event_id:
            settings_row = (
                await db.execute(
                    select(OrgSettings).where(OrgSettings.org_id == ctx.org_id)
                )
            ).scalar_one_or_none()
            await calendar_service.delete_event(
                org_calendar_integration=settings_row.calendar_integration
                if settings_row else None,
                event_id=demo.calendar_event_id,
            )
    rescheduled = False
    if body.scheduled_date is not None:
        rescheduled = rescheduled or body.scheduled_date != demo.scheduled_date
        demo.scheduled_date = body.scheduled_date
    if body.scheduled_time is not None:
        rescheduled = rescheduled or body.scheduled_time != demo.scheduled_time
        demo.scheduled_time = body.scheduled_time
    if body.team_id is not None:
        demo.team_id = body.team_id
    if body.notes is not None:
        demo.notes = body.notes

    # Invite follow-through: cancellations retract the calendar invite,
    # date/time changes send the "event updated" invite — both as drafts
    # awaiting approval, like the original invite.
    change = None
    if body.status is not None and demo.status == DemoStatus.CANCELLED.value:
        change = "cancelled"
    elif rescheduled and demo.status == DemoStatus.SCHEDULED.value:
        change = "rescheduled"
    invite = None
    if change:
        lead = (
            await db.execute(
                select(Lead).where(Lead.id == demo.lead_id, Lead.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        team = None
        if demo.team_id:
            team = (
                await db.execute(
                    select(DemoTeam).where(
                        DemoTeam.id == demo.team_id, DemoTeam.org_id == ctx.org_id
                    )
                )
            ).scalar_one_or_none()
        if lead is not None:
            invite = await demo_invite_service.compose_demo_invite(
                db, ctx, demo=demo, lead=lead, team=team, change=change
            )
    await db.commit()
    result = await _demo_dict(db, demo)
    if invite is not None:
        result["invite_message_id"] = invite.id
    return result
