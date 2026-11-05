"""In-app notifications (e.g. task reassigned -> 'Siva is notified').

Every notification is a DB row first (the source of truth the app polls);
when FCM is configured (push_service.enabled), the same content also rings
the user's phone — fire-and-forget, never blocking the caller's transaction.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Notification
from app.services import push_service


async def notify(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    title: str,
    body: str | None = None,
    kind: str = "general",
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> Notification:
    n = Notification(
        org_id=org_id,
        user_id=user_id,
        title=title,
        body=body,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(n)
    push_service.push_soon(
        org_id=org_id, user_id=user_id, title=title, body=body,
        kind=kind, entity_type=entity_type, entity_id=entity_id,
    )
    return n
