"""Field location (2 Oct 2026). Sales agents and sales leads send a reading
when they open the app; the org admin reads them on the field map."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.config import get_settings
from app.core import clock
from app.core.context import OrgContext
from app.core.exceptions import PermissionDeniedError
from app.database import get_db
from app.models.base import utcnow
from app.services import location_service

router = APIRouter(prefix="/locations", tags=["locations"])


class PingIn(BaseModel):
    client_ref: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    status: Literal["ok", "permission_denied", "gps_off", "timeout"]
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    is_mock: bool = False
    approximate: bool = False
    trigger: Literal["open", "resume"] = "open"
    captured_at: datetime


@router.post("/ping")
async def ping(
    body: PingIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    if ctx.role not in location_service.TRACKED_ROLES:
        raise PermissionDeniedError("Only sales agents and sales leads send their location.")
    saved, reason = await location_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, client_ref=body.client_ref,
        status=body.status, lat=body.lat, lng=body.lng, accuracy_m=body.accuracy_m,
        is_mock=body.is_mock, approximate=body.approximate, trigger=body.trigger,
        captured_at=body.captured_at,
    )
    await db.commit()
    return {"saved": saved, "reason": reason}


@router.get("/latest")
async def latest(
    ctx: OrgContext = Depends(require_permission("track_locations")),
    db: AsyncSession = Depends(get_db),
):
    tz = await clock.org_zone(db, ctx.org_id)
    return {
        "people": await location_service.latest(db, org_id=ctx.org_id, tz=tz),
        "generated_at": utcnow().isoformat(),
    }


@router.get("/points")
async def points(
    start: datetime = Query(alias="from"),
    end: datetime = Query(alias="to"),
    user_ids: list[str] | None = Query(default=None),
    roles: list[str] | None = Query(default=None),
    ctx: OrgContext = Depends(require_permission("track_locations")),
    db: AsyncSession = Depends(get_db),
):
    rows, truncated = await location_service.points(
        db, org_id=ctx.org_id, start=start, end=end, user_ids=user_ids, roles=roles,
    )
    return {"points": rows, "truncated": truncated}


@router.get("/config")
async def config(ctx: OrgContext = Depends(get_org_context)):
    settings = get_settings()
    return {
        "style_light": settings.location_map_style_light,
        "style_dark": settings.location_map_style_dark,
        "attribution": settings.location_map_attribution,
    }
