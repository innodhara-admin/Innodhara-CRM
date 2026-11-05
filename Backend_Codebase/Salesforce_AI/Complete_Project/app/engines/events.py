"""The event stream — the one non-negotiable habit (30-Workflows §6).

Every meaningful change becomes a progress_events row via emit(). The Sync
Engine registers itself as the reactor at startup; every emit is then also a
trigger. A depth guard stops runaway reaction chains (reactions may emit
follow-on events, e.g. task_done → client update drafted → approval_requested).
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.work import ProgressEvent

logger = logging.getLogger(__name__)

Reactor = Callable[[AsyncSession, ProgressEvent], Awaitable[None]]

_reactor: Reactor | None = None
_depth: ContextVar[int] = ContextVar("event_depth", default=0)
MAX_REACTION_DEPTH = 8


def set_reactor(fn: Reactor | None) -> None:
    global _reactor
    _reactor = fn


async def emit(
    db: AsyncSession,
    *,
    org_id: str,
    event_type: str,
    project_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str = "system",
    details: dict[str, Any] | None = None,
    react: bool = True,
) -> ProgressEvent:
    """Write one event row and hand it to the Sync Engine reactor."""
    event = ProgressEvent(
        org_id=org_id,
        project_id=project_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        details=details or {},
    )
    db.add(event)
    await db.flush()

    if react and _reactor is not None:
        depth = _depth.get()
        if depth >= MAX_REACTION_DEPTH:
            logger.warning(
                "Event reaction depth cap reached at %s (%s) — event recorded, "
                "reaction skipped",
                event_type,
                event.id,
            )
            return event
        token = _depth.set(depth + 1)
        try:
            await _reactor(db, event)
        except Exception:  # noqa: BLE001 — a reaction bug must never lose the event
            logger.exception("Sync reaction failed for event %s (%s)", event_type, event.id)
        finally:
            _depth.reset(token)
    return event
