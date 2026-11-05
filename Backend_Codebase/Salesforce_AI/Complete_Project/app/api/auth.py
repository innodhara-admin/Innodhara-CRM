"""Authentication: login (email = identity -> organisation + role), me,
password management, personal email app-password storage."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import UnauthorizedError, get_current_user
from app.core.crypto import encrypt_secret
from app.core.exceptions import ValidationFailedError
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models.base import utcnow
from app.models.organisation import Organisation, OrgSettings
from app.models.user import User
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    org_slug: str | None = None  # optional; email already implies the org


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str
    role: str
    org_id: str | None
    org_name: str | None
    must_change_password: bool


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str
    role: str
    org_id: str | None
    org_name: str | None
    phone: str | None
    has_email_app_password: bool
    # Org branding for the mobile app (G7): theme + logo without extra calls.
    org_slug: str | None = None
    org_logo_url: str | None = None
    org_brand_colors: dict | None = None
    designation: str | None = None
    department: str | None = None
    #: The zone this organisation reckons dates in. The app buckets tasks by
    #: day, and doing that in the *phone's* zone is the same mix the backend
    #: just stopped making — a rep in another country would see a different
    #: day from the server that sent the rows. Additive: an older build that
    #: ignores this field behaves exactly as before.
    org_timezone: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AppPasswordRequest(BaseModel):
    app_password: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(
            select(User).where(func.lower(User.email) == body.email.lower())
        )
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("Wrong email or password")
    if not user.is_active:
        raise UnauthorizedError("Account is deactivated")

    org_name = None
    if user.org_id:
        org = (
            await db.execute(
                select(Organisation).where(Organisation.id == user.org_id)
            )
        ).scalar_one_or_none()
        if org is None or not org.is_active:
            raise UnauthorizedError("Your organisation is not active")
        if body.org_slug and body.org_slug != org.slug:
            raise UnauthorizedError(
                f"This account belongs to organisation '{org.slug}'"
            )
        org_name = org.name

    user.last_login_at = utcnow()
    await audit_service.record(
        db, org_id=user.org_id, user_id=user.id, action="auth.login"
    )
    await db.commit()
    return LoginResponse(
        access_token=create_access_token(user.id, user.org_id, user.role, user.email),
        user_id=user.id,
        name=user.name,
        role=user.role,
        org_id=user.org_id,
        org_name=org_name,
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    org = None
    org_settings = None
    if user.org_id:
        org = (
            await db.execute(
                select(Organisation).where(Organisation.id == user.org_id)
            )
        ).scalar_one_or_none()
        org_settings = (
            await db.execute(
                select(OrgSettings).where(OrgSettings.org_id == user.org_id)
            )
        ).scalar_one_or_none()
    return MeResponse(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        org_id=user.org_id,
        org_name=org.name if org else None,
        phone=user.phone,
        has_email_app_password=bool(user.smtp_app_password_enc),
        org_slug=org.slug if org else None,
        org_logo_url=org.logo_url if org else None,
        org_brand_colors=org.brand_colors if org else None,
        designation=user.designation,
        department=user.department,
        org_timezone=org_settings.timezone if org_settings else None,
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Exchange a still-valid token for a fresh one (G4 — lets the mobile
    app extend a session without re-entering the password). An expired
    token cannot refresh: get_current_user already rejects it."""
    org_name = None
    if user.org_id:
        org = (
            await db.execute(
                select(Organisation).where(Organisation.id == user.org_id)
            )
        ).scalar_one_or_none()
        if org is None or not org.is_active:
            raise UnauthorizedError("Your organisation is not active")
        org_name = org.name
    return LoginResponse(
        access_token=create_access_token(user.id, user.org_id, user.role, user.email),
        user_id=user.id,
        name=user.name,
        role=user.role,
        org_id=user.org_id,
        org_name=org_name,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise UnauthorizedError("Current password is wrong")
    if len(body.new_password) < 8:
        raise ValidationFailedError("New password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await audit_service.record(
        db, org_id=user.org_id, user_id=user.id, action="auth.password_changed"
    )
    await db.commit()
    return {"changed": True}


@router.post("/email-app-password")
async def set_email_app_password(
    body: AppPasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store the user's own Gmail App Password (encrypted) so their proposals
    and messages send from their personal address."""
    if len(body.app_password.replace(" ", "")) < 8:
        raise ValidationFailedError("That does not look like a valid app password")
    user.smtp_app_password_enc = encrypt_secret(body.app_password.replace(" ", ""))
    await audit_service.record(
        db, org_id=user.org_id, user_id=user.id, action="auth.app_password_set"
    )
    await db.commit()
    return {"saved": True}
