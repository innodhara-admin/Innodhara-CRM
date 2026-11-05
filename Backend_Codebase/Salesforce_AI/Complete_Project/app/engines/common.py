"""Helpers shared by all engines: org settings, AI-decision recording,
role/lead lookups, and small conveniences.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Department, Role
from app.models.organisation import OrgSettings
from app.models.user import User
from app.models.work import AIDecision


async def get_org_settings(db: AsyncSession, org_id: str) -> OrgSettings:
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    ).scalar_one_or_none()
    if row is None:
        row = OrgSettings(org_id=org_id)
        db.add(row)
        await db.flush()
    return row


async def record_decision(
    db: AsyncSession,
    *,
    org_id: str,
    decision_type: str,
    engine: str,
    decision: str,
    reason: str,
    project_id: str | None = None,
    input_summary: str | None = None,
    confidence: float = 1.0,
    needs_human: bool = False,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> AIDecision:
    """Every AI decision carries a written reason anyone can read later."""
    row = AIDecision(
        org_id=org_id,
        project_id=project_id,
        decision_type=decision_type,
        engine=engine,
        input_summary=input_summary,
        decision=decision,
        reason=reason,
        confidence=confidence,
        needs_human=needs_human,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(row)
    await db.flush()
    return row


async def find_role_user(db: AsyncSession, org_id: str, role: str) -> User | None:
    """First active user holding a role in this organisation."""
    return (
        await db.execute(
            select(User)
            .where(User.org_id == org_id, User.role == role, User.is_active.is_(True))
            .order_by(User.created_at)
        )
    ).scalars().first()


async def find_department_lead(db: AsyncSession, org_id: str, department: str | None) -> User | None:
    """The lead who hears about a person's overload / level-3 escalations."""
    role = (
        Role.OPERATIONS_LEAD.value
        if department in (Department.OPERATIONS.value, Department.ACCOUNTS.value)
        else Role.SALES_LEAD.value
    )
    lead = await find_role_user(db, org_id, role)
    if lead is None:  # fall back to the org admin
        lead = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
    return lead


async def get_user(db: AsyncSession, org_id: str, user_id: str | None) -> User | None:
    if not user_id or user_id in ("ai", "system"):
        return None
    return (
        await db.execute(
            select(User).where(User.org_id == org_id, User.id == user_id)
        )
    ).scalar_one_or_none()


def fmt_date(value: datetime | None) -> str:
    return value.strftime("%d %b %Y") if value else "—"


def clip(text: str | None, n: int = 300) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[: n - 1] + "…"
