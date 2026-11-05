"""The sending worker — delivers approved messages through the sending
scheduler rules of Figure 8: per-provider pacing, backoff on failure (via the
queue), and dead-letter with the message flagged, never a silent loss."""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.core.constants import MessageStatus
from app.database import SessionLocal
from app.jobs.queue import defer
from app.models.messaging import OutboundMessage
from app.services import message_service

logger = logging.getLogger(__name__)

# Sliding-window send pacing per (org, channel) — spreads sends over time so
# provider per-minute limits are respected (doc §11.6).
_send_history: dict[tuple[str, str], list[float]] = {}


def _pace_ok(org_id: str, channel: str) -> bool:
    settings = get_settings()
    limit = (
        settings.email_max_per_minute
        if channel == "email"
        else settings.whatsapp_max_per_minute
    )
    key = (org_id, channel)
    now = time.monotonic()
    window = [t for t in _send_history.get(key, []) if now - t < 60]
    _send_history[key] = window
    if len(window) >= limit:
        return False
    window.append(now)
    return True


def forget_org(org_id: str) -> None:
    """Drop a deleted organisation's pacing history."""
    for key in [k for k in _send_history if k[0] == org_id]:
        del _send_history[key]


async def send_message(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    message_id = payload["message_id"]
    async with SessionLocal() as db:
        message = (
            await db.execute(
                select(OutboundMessage).where(OutboundMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if message is None:
            return {"skipped": "message deleted"}
        if message.status == MessageStatus.SENT.value:
            return {"skipped": "already sent"}  # idempotency on retry
        if message.status not in (
            MessageStatus.QUEUED.value,
            MessageStatus.SENDING.value,
            MessageStatus.FAILED.value,
        ):
            return {"skipped": f"status is {message.status}"}

        if not _pace_ok(message.org_id, message.channel):
            raise defer(20)  # rate pacing — try again shortly, not a failure

        try:
            await message_service.execute_send(db, message)
            await db.commit()
            return {"sent": True, "provider_id": message.provider_message_id}
        except Exception as exc:
            message.status = MessageStatus.FAILED.value
            message.last_error = str(exc)[:1000]
            await message_service.log_event(db, message, "failed", str(exc)[:500])
            await db.commit()
            raise
