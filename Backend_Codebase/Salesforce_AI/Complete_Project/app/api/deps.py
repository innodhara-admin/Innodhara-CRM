"""Request dependencies: authentication, org-context resolution, RBAC.

The Backend API resolves the org context here and it travels with the request
from this point on (doc §5) — client-supplied org ids are never trusted.
"""
from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import Role
from app.core.context import OrgContext
from app.core.exceptions import AppError, PermissionDeniedError
from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.database import get_db
from app.models.organisation import Organisation
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


class UnauthorizedError(AppError):
    status_code = 401


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Missing bearer token")
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise UnauthorizedError("Invalid or expired token")
    user = (
        await db.execute(select(User).where(User.id == payload.get("sub")))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise UnauthorizedError("Account not found or deactivated")
    return user


async def get_org_context(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgContext:
    """Org-scoped context. The Super Admin is deliberately rejected here —
    the platform operator cannot read an organisation's sales data (doc §3)."""
    if user.role == Role.SUPER_ADMIN.value or not user.org_id:
        raise PermissionDeniedError(
            "This endpoint is organisation-scoped; the Super Admin has no access "
            "to organisation data."
        )
    org = (
        await db.execute(select(Organisation).where(Organisation.id == user.org_id))
    ).scalar_one_or_none()
    if org is None or not org.is_active:
        raise PermissionDeniedError("Your organisation is not active")
    return OrgContext(
        org_id=user.org_id,
        user_id=user.id,
        role=user.role,
        email=user.email,
        name=user.name,
    )


async def org_context_for_token(db: AsyncSession, token: str | None) -> OrgContext:
    """`get_current_user` + `get_org_context` for a caller that cannot use
    FastAPI's dependencies — a WebSocket, which re-checks the token on every
    voice turn so an expired token or a deactivated account stops the session
    exactly as it would stop an HTTP request. Same checks, same errors."""
    if not token:
        raise UnauthorizedError("Missing bearer token")
    payload = decode_access_token(token)
    if payload is None:
        raise UnauthorizedError("Invalid or expired token")
    user = (
        await db.execute(select(User).where(User.id == payload.get("sub")))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise UnauthorizedError("Account not found or deactivated")
    return await get_org_context(user=user, db=db)


async def get_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.SUPER_ADMIN.value:
        raise PermissionDeniedError("Super Admin only")
    return user


def require_permission(permission: str):
    async def _check(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if not has_permission(ctx.role, permission):
            raise PermissionDeniedError(
                f"Your role '{ctx.role}' cannot perform this action"
            )
        return ctx

    return _check


def require_any_permission(*permissions: str):
    """Allow the action if the role holds ANY of these.

    For the case where one endpoint serves two jobs that happen to need the
    same data. Follow-ups are the first: booking a conversation is part of
    working the sales pipeline AND part of managing a relationship, and the
    two roles that do those things share no other permission. The alternative
    was to widen `manage_leads`, which would have handed a relationship
    manager the sales states as well.

    Deliberately not a general-purpose "or" for permissions. If a third
    endpoint wants this, that is a sign the matrix needs a permission of its
    own rather than another disjunction here.
    """
    async def _check(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if not any(has_permission(ctx.role, p) for p in permissions):
            raise PermissionDeniedError(
                f"Your role '{ctx.role}' cannot perform this action"
            )
        return ctx

    return _check
