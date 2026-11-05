"""The sales head's screens (23 Oct 2026): read-only, one route per screen.

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-23-sales-head-design.md
section 9.1. Every route needs `view_sales_insights`, which only the sales
head holds; the super admin is refused by `get_org_context` as everywhere.
The only write is the day's score and pulse snapshot (app/insights/snapshots).

Each response is screen-shaped: `generated_at` and the organisation's
`timezone`, then blocks that each carry a `status` (ok / thin / empty) and a
plain `note`, so the app draws the honest state without rules of its own.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import date, datetime, tzinfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core import clock
from app.core.context import OrgContext
from app.core.exceptions import ValidationFailedError
from app.database import get_db
from app.insights import (ai_usage, cache, clients, common, deal, field, meetings, outlook,
                          person, pipeline, pulse, snapshots, team)
from app.models.base import utcnow

router = APIRouter(prefix="/insights", tags=["insights"])

_watch = require_permission("view_sales_insights")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
RANGES = ("month", "quarter", "year")
DAYS = (7, 30)


def _zone_name(tz: tzinfo) -> str:
    return getattr(tz, "key", None) or str(tz)


def _days(days: int) -> int:
    if days not in DAYS:
        raise ValidationFailedError("days must be 7 or 30")
    return days


async def _serve(db: AsyncSession, ctx: OrgContext, route: str, params: tuple,
                 build: Callable[[tzinfo, datetime], Awaitable[dict]]) -> dict:
    async def compute() -> dict:
        now = utcnow()
        tz = await clock.org_zone(db, ctx.org_id)
        await snapshots.ensure_today(db, ctx.org_id, tz, now)
        body = await build(tz, now)
        await db.commit()
        return {"generated_at": common.iso_utc(now), "timezone": _zone_name(tz), **body}

    return await cache.get_or_compute((ctx.org_id, route, params), cache.TTL_SECONDS, compute)


@router.get("/pulse")
async def get_pulse(ctx: OrgContext = Depends(_watch), db: AsyncSession = Depends(get_db)):
    return await _serve(db, ctx, "pulse", (),
                        lambda tz, now: pulse.build(db, ctx.org_id, tz, now))


@router.get("/pipeline")
async def get_pipeline(range: str = Query("month"), ctx: OrgContext = Depends(_watch),
                       db: AsyncSession = Depends(get_db)):
    if range not in RANGES:
        raise ValidationFailedError("range must be month, quarter or year")
    return await _serve(db, ctx, "pipeline", (range,),
                        lambda tz, now: pipeline.build(db, ctx.org_id, tz, now, range=range))


@router.get("/outlook")
async def get_outlook(ctx: OrgContext = Depends(_watch), db: AsyncSession = Depends(get_db)):
    return await _serve(db, ctx, "outlook", (),
                        lambda tz, now: outlook.build(db, ctx.org_id, tz, now))


@router.get("/team")
async def get_team(metric: str = Query("meetings"), days: int = Query(7),
                   ctx: OrgContext = Depends(_watch), db: AsyncSession = Depends(get_db)):
    if metric not in team.METRICS:
        raise ValidationFailedError("metric must be meetings, emails, followups or tasks_done")
    days = _days(days)
    return await _serve(db, ctx, "team", (metric, days),
                        lambda tz, now: team.build(db, ctx.org_id, tz, now, metric=metric,
                                                   days=days))


@router.get("/people/{user_id}")
async def get_person(user_id: str, days: int = Query(7), ctx: OrgContext = Depends(_watch),
                     db: AsyncSession = Depends(get_db)):
    days = _days(days)
    return await _serve(db, ctx, "person", (user_id, days),
                        lambda tz, now: person.build(db, ctx.org_id, tz, now, user_id=user_id,
                                                     days=days))


@router.get("/clients")
async def get_clients(ctx: OrgContext = Depends(_watch), db: AsyncSession = Depends(get_db)):
    return await _serve(db, ctx, "clients", (),
                        lambda tz, now: clients.build(db, ctx.org_id, tz, now))


@router.get("/deals/{lead_id}")
async def get_deal(lead_id: str, ctx: OrgContext = Depends(_watch),
                   db: AsyncSession = Depends(get_db)):
    return await _serve(db, ctx, "deal", (lead_id,),
                        lambda tz, now: deal.build(db, ctx.org_id, tz, now, lead_id=lead_id))


@router.get("/meetings")
async def get_meetings(days: int = Query(7), ctx: OrgContext = Depends(_watch),
                       db: AsyncSession = Depends(get_db)):
    days = _days(days)
    return await _serve(db, ctx, "meetings", (days,),
                        lambda tz, now: meetings.build(db, ctx.org_id, tz, now, days=days))


def _day_or_today(day: date | None, tz: tzinfo, now: datetime) -> date:
    return day or common.local_day(now, tz)


@router.get("/field")
async def get_field(date: date | None = Query(None), ctx: OrgContext = Depends(_watch),
                    db: AsyncSession = Depends(get_db)):
    asked = date
    return await _serve(db, ctx, "field", (asked,),
                        lambda tz, now: field.build(db, ctx.org_id, tz, now,
                                                    day=_day_or_today(asked, tz, now)))


@router.get("/field/{user_id}")
async def get_field_person(user_id: str, date: date | None = Query(None),
                           ctx: OrgContext = Depends(_watch), db: AsyncSession = Depends(get_db)):
    asked = date
    return await _serve(db, ctx, "field_person", (user_id, asked),
                        lambda tz, now: field.person(db, ctx.org_id, tz, now, user_id=user_id,
                                                     day=_day_or_today(asked, tz, now)))


@router.get("/ai")
async def get_ai(month: str | None = Query(None), ctx: OrgContext = Depends(_watch),
                 db: AsyncSession = Depends(get_db)):
    if month is not None and not _MONTH.match(month):
        raise ValidationFailedError("month must look like 2026-10")
    return await _serve(db, ctx, "ai", (month,),
                        lambda tz, now: ai_usage.build(db, ctx.org_id, tz, now, month=month))
