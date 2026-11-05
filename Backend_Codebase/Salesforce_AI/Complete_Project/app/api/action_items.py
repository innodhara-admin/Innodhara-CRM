"""Action items: list, create, reassign (RBAC-scoped), close with a result."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.constants import ActionItemStatus
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import can_reassign_task
from app.database import get_db
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.lead import Lead
from app.models.project import Project
from app.models.user import User
from app.services import audit_service, notification_service

router = APIRouter(prefix="/action-items", tags=["action items"])


class CreateItemRequest(BaseModel):
    title: str = Field(min_length=2, max_length=490)
    description: str | None = None
    lead_id: str | None = None
    owner_id: str | None = None
    due_date: datetime | None = None


class UpdateItemRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    owner_id: str | None = None
    due_date: datetime | None = None
    result_note: str | None = None


async def _item_dict(db: AsyncSession, item: ActionItem) -> dict:
    owner_name = (
        await db.execute(select(User.name).where(User.id == item.owner_id))
    ).scalar_one_or_none()
    lead_name = (
        await db.execute(select(Lead.name).where(Lead.id == item.lead_id))
    ).scalar_one_or_none()
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "owner_id": item.owner_id,
        "owner_name": owner_name,
        "lead_id": item.lead_id,
        "school": lead_name,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "result_note": item.result_note,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "created_at": item.created_at.isoformat(),
    }


@router.get("")
async def list_action_items(
    status: str = "open",
    owner: str = "me",
    lead_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    ctx: OrgContext = Depends(require_permission("manage_tasks")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ActionItem).where(ActionItem.org_id == ctx.org_id)
    if owner == "me":
        stmt = stmt.where(ActionItem.owner_id == ctx.user_id)
    elif owner != "anyone":
        stmt = stmt.where(ActionItem.owner_id == owner)  # explicit user id
    if status != "all":
        try:
            stmt = stmt.where(ActionItem.status == ActionItemStatus(status).value)
        except ValueError:
            raise ValidationFailedError(f"Unknown status '{status}'")
    else:
        stmt = stmt.where(ActionItem.status != ActionItemStatus.PENDING_REVIEW.value)
    if lead_id:
        stmt = stmt.where(ActionItem.lead_id == lead_id)
    items = (
        await db.execute(
            stmt.order_by(ActionItem.created_at.desc())
            .offset(max(offset, 0)).limit(min(limit, 200))
        )
    ).scalars().all()
    return [await _item_dict(db, i) for i in items]


@router.get("/waiting-on-me")
async def waiting_on_me(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Open tasks that are blocked waiting on the caller (customer ask,
    21 Sep 2026). Feeds the "Colleagues waiting on you" card on Home. Any
    member can be waited on, so no task permission is required to read it."""
    items = (
        await db.execute(
            select(ActionItem)
            .where(
                ActionItem.org_id == ctx.org_id,
                ActionItem.blocked.is_(True),
                ActionItem.blocked_on_user_id == ctx.user_id,
                ActionItem.status.in_(
                    [ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value]
                ),
            )
            .order_by(ActionItem.updated_at.desc())
            .limit(50)
        )
    ).scalars().all()
    out = []
    for item in items:
        waiter = (
            await db.execute(select(User.name).where(User.id == item.assignee_id))
        ).scalar_one_or_none() if item.assignee_id else None
        lead_name = (
            await db.execute(select(Lead.name).where(Lead.id == item.lead_id))
        ).scalar_one_or_none() if item.lead_id else None
        project_name = (
            await db.execute(select(Project.name).where(Project.id == item.project_id))
        ).scalar_one_or_none() if item.project_id else None
        out.append({
            "id": item.id,
            "title": item.title,
            "blocked_reason": item.blocked_reason,
            "waiting_user_id": item.assignee_id,
            "waiting_user_name": waiter,
            "lead_id": item.lead_id,
            "school": lead_name,
            "project_id": item.project_id,
            "project_name": project_name,
            "due_date": item.due_date.isoformat() if item.due_date else None,
        })
    return {"items": out}


@router.post("")
async def create_action_item(
    body: CreateItemRequest,
    ctx: OrgContext = Depends(require_permission("manage_tasks")),
    db: AsyncSession = Depends(get_db),
):
    owner_id = body.owner_id or ctx.user_id
    if owner_id != ctx.user_id:
        owner = (
            await db.execute(
                select(User).where(User.id == owner_id, User.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        if owner is None:
            raise NotFoundError("Owner not found in your organisation")
    item = ActionItem(
        org_id=ctx.org_id,
        lead_id=body.lead_id,
        title=body.title,
        description=body.description,
        owner_id=owner_id,
        due_date=body.due_date,
        status=ActionItemStatus.OPEN.value,
        created_by=ctx.user_id,
    )
    db.add(item)
    await db.flush()
    if owner_id != ctx.user_id:
        await notification_service.notify(
            db, org_id=ctx.org_id, user_id=owner_id,
            title=f"New task from {ctx.name}: {body.title}",
            kind="task_assigned", entity_type="action_item", entity_id=item.id,
        )
    await db.commit()
    return await _item_dict(db, item)


@router.patch("/{item_id}")
async def update_action_item(
    item_id: str,
    body: UpdateItemRequest,
    ctx: OrgContext = Depends(require_permission("manage_tasks")),
    db: AsyncSession = Depends(get_db),
):
    item = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.id == item_id, ActionItem.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("Action item not found")

    if body.owner_id is not None and body.owner_id != item.owner_id:
        if not can_reassign_task(ctx.role, ctx.user_id, item.owner_id, same_team=True):
            raise PermissionDeniedError("You can only reassign your own tasks")
        new_owner = (
            await db.execute(
                select(User).where(User.id == body.owner_id, User.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        if new_owner is None:
            raise NotFoundError("New owner not found in your organisation")
        item.owner_id = body.owner_id
        await notification_service.notify(
            db, org_id=ctx.org_id, user_id=body.owner_id,
            title=f"{ctx.name} assigned you a task: {item.title}",
            kind="task_assigned", entity_type="action_item", entity_id=item.id,
        )

    if body.status is not None:
        try:
            new_status = ActionItemStatus(body.status)
        except ValueError:
            raise ValidationFailedError(f"Unknown status '{body.status}'")
        item.status = new_status.value
        if new_status == ActionItemStatus.DONE:
            item.completed_at = utcnow()
    if body.title is not None:
        item.title = body.title[:490]
    if body.description is not None:
        item.description = body.description
    if body.due_date is not None:
        item.due_date = body.due_date
    if body.result_note is not None:
        item.result_note = body.result_note

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="action_item.updated",
        entity_type="action_item", entity_id=item_id,
        detail=body.model_dump(exclude_none=True, mode="json"),
    )
    await db.commit()
    return await _item_dict(db, item)
