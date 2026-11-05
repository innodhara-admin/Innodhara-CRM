"""Platform level (Super Admin): organisation onboarding and platform stats.

The Super Admin enrols organisations and invites the first Org Admin, but can
never read an organisation's private sales data (doc §3, §15).
"""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_super_admin
from app.config import get_settings
from app.core.constants import Role
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import hash_password
from app.database import get_db
from app.models.audit import LlmUsage
from app.models.lead import Lead
from app.models.meeting import Meeting
from app.models.organisation import Organisation, OrgSettings
from app.models.user import User
from app.services import audit_service

router = APIRouter(prefix="/orgs", tags=["platform (super admin)"])


class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    email_domain: str = Field(min_length=3, max_length=200)
    logo_url: str | None = None
    brand_colors: dict | None = None
    admin_email: EmailStr
    admin_name: str


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    email_domain: str
    is_active: bool


class CreateOrgResponse(OrgResponse):
    admin_email: str
    admin_temp_password: str
    note: str = (
        "Share the temporary password with the Org Admin securely; "
        "they must change it at first login."
    )


@router.post("", response_model=CreateOrgResponse)
async def create_organisation(
    body: CreateOrgRequest,
    admin: User = Depends(get_super_admin),
    db: AsyncSession = Depends(get_db),
):
    domain = body.email_domain.lstrip("@").lower()
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", domain):
        raise ValidationFailedError(f"'{domain}' is not a valid email domain")
    existing = (
        await db.execute(select(Organisation).where(Organisation.slug == body.slug))
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(f"Organisation slug '{body.slug}' already exists")
    email_taken = (
        await db.execute(
            select(User).where(func.lower(User.email) == body.admin_email.lower())
        )
    ).scalar_one_or_none()
    if email_taken:
        raise ConflictError(f"A user with email {body.admin_email} already exists")

    settings = get_settings()
    org = Organisation(
        name=body.name,
        slug=body.slug,
        email_domain=domain,
        logo_url=body.logo_url,
        brand_colors=body.brand_colors or {},
    )
    db.add(org)
    await db.flush()
    db.add(
        OrgSettings(
            org_id=org.id,
            audio_retention_days=settings.default_audio_retention_days,
            transcript_retention_days=settings.default_transcript_retention_days,
            llm_monthly_budget_usd=settings.llm_default_org_monthly_budget_usd,
        )
    )
    temp_password = secrets.token_urlsafe(9)
    db.add(
        User(
            org_id=org.id,
            email=body.admin_email.lower(),
            name=body.admin_name,
            role=Role.ORG_ADMIN.value,
            password_hash=hash_password(temp_password),
            must_change_password=True,
        )
    )
    await audit_service.record(
        db, org_id=None, user_id=admin.id,
        action="platform.org_created", entity_type="organisation", entity_id=org.id,
        detail={"name": org.name, "slug": org.slug},
    )
    await db.commit()
    return CreateOrgResponse(
        id=org.id, name=org.name, slug=org.slug, email_domain=org.email_domain,
        is_active=org.is_active, admin_email=body.admin_email,
        admin_temp_password=temp_password,
    )


@router.get("", response_model=list[OrgResponse])
async def list_organisations(
    admin: User = Depends(get_super_admin), db: AsyncSession = Depends(get_db)
):
    orgs = (await db.execute(select(Organisation))).scalars().all()
    return [
        OrgResponse(
            id=o.id, name=o.name, slug=o.slug,
            email_domain=o.email_domain, is_active=o.is_active,
        )
        for o in orgs
    ]


@router.patch("/{org_id}/active")
async def set_organisation_active(
    org_id: str,
    active: bool,
    admin: User = Depends(get_super_admin),
    db: AsyncSession = Depends(get_db),
):
    org = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    if org is None:
        raise NotFoundError("Organisation not found")
    org.is_active = active
    await audit_service.record(
        db, org_id=None, user_id=admin.id,
        action="platform.org_active_changed", entity_type="organisation",
        entity_id=org_id, detail={"active": active},
    )
    await db.commit()
    return {"id": org_id, "is_active": active}


@router.get("/platform/stats")
async def platform_stats(
    admin: User = Depends(get_super_admin), db: AsyncSession = Depends(get_db)
):
    """Aggregate counts only — no private sales data (doc §16)."""
    orgs = (await db.execute(select(Organisation))).scalars().all()
    stats = []
    for org in orgs:
        users = (
            await db.execute(
                select(func.count(User.id)).where(User.org_id == org.id)
            )
        ).scalar_one()
        leads = (
            await db.execute(
                select(func.count(Lead.id)).where(Lead.org_id == org.id)
            )
        ).scalar_one()
        meetings = (
            await db.execute(
                select(func.count(Meeting.id)).where(Meeting.org_id == org.id)
            )
        ).scalar_one()
        ai_cost = (
            await db.execute(
                select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0)).where(
                    LlmUsage.org_id == org.id
                )
            )
        ).scalar_one()
        stats.append(
            {
                "org": org.slug,
                "active": org.is_active,
                "users": users,
                "leads": leads,
                "meetings": meetings,
                "ai_cost_usd_total": round(ai_cost, 4),
            }
        )
    return {"organisations": stats}
