"""Outbound messages: the approval inbox, send/reject, delivery log, and
provider webhooks for delivery status (Figure 8)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.config import get_settings
from app.core.constants import MessageStatus
from app.core.context import OrgContext
from app.database import get_db
from app.jobs.queue import PRIORITY_SEND, job_queue
from app.models.messaging import MessageDeliveryLog, OutboundMessage
from app.services import draft_check, message_service

router = APIRouter(tags=["messages"])


class RejectRequest(BaseModel):
    reason: str | None = None


async def _narratives(
    db: AsyncSession, org_id: str, messages: list[OutboundMessage]
) -> dict[str, str]:
    """proposal_id -> narrative, for every proposal attached to these messages.

    Batched on purpose: `blanks` is computed per row on a list endpoint that
    returns up to 200, and F47's fix must not turn that into 200 queries.
    """
    ids = {m.proposal_id for m in messages if m.proposal_id}
    if not ids:
        return {}
    from app.models.proposal import Proposal

    rows = (
        await db.execute(
            select(Proposal).where(Proposal.org_id == org_id, Proposal.id.in_(ids))
        )
    ).scalars().all()
    return {p.id: p.content_md for p in rows if p.content_md}


def _message_dict(m: OutboundMessage, narrative: str | None = None) -> dict:
    return {
        "id": m.id,
        "kind": m.kind,
        "channel": m.channel,
        "status": m.status,
        "to": m.to_address,
        "cc": m.cc,
        # Additive (2026-09-23): meeting invites may carry a blind copy.
        "bcc": m.bcc or [],
        "subject": m.subject,
        "body": m.body,
        "lead_id": m.lead_id,
        "proposal_id": m.proposal_id,
        # Additive (2026-07-29): /messages is org-wide, so the message centre
        # needs to know whose message a row is to offer a Mine/All filter.
        # The endpoint's scope is unchanged — the client filters, honestly and
        # visibly, rather than the server hiding rows from an old build.
        "sender_user_id": m.sender_user_id,
        # Additive (2026-08-03, F30): the fill-in-the-blanks a model left
        # behind, so a screen can warn BEFORE someone taps Approve rather than
        # only refusing afterwards. Empty list = nothing detected.
        # 2026-08-05 (F47): the attached proposal narrative is included, because
        # the placeholder that reached a real client sat in the PDF, not the
        # body — the warning has to cover what the approve gate now refuses, or
        # the screen promises a send the server will reject.
        "blanks": draft_check.find_blanks(m.subject, m.body, narrative),
        "attempts": m.attempts,
        "last_error": m.last_error,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        "created_at": m.created_at.isoformat(),
    }


@router.get("/messages")
async def list_messages(
    status: str = "pending_approval",
    limit: int = 50,
    offset: int = 0,
    ctx: OrgContext = Depends(require_permission("send_messages")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(OutboundMessage).where(OutboundMessage.org_id == ctx.org_id)
    if status != "all":
        stmt = stmt.where(OutboundMessage.status == status)
    messages = (
        await db.execute(
            stmt.order_by(OutboundMessage.created_at.desc())
            .offset(max(offset, 0)).limit(min(limit, 200))
        )
    ).scalars().all()
    narratives = await _narratives(db, ctx.org_id, list(messages))
    return [
        _message_dict(m, narratives.get(m.proposal_id) if m.proposal_id else None)
        for m in messages
    ]


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    ctx: OrgContext = Depends(require_permission("send_messages")),
    db: AsyncSession = Depends(get_db),
):
    message = await message_service.get_message(db, ctx.org_id, message_id)
    log = (
        await db.execute(
            select(MessageDeliveryLog)
            .where(MessageDeliveryLog.message_id == message_id)
            .order_by(MessageDeliveryLog.at)
        )
    ).scalars().all()
    narratives = await _narratives(db, ctx.org_id, [message])
    return {
        **_message_dict(
            message,
            narratives.get(message.proposal_id) if message.proposal_id else None,
        ),
        "delivery_log": [
            {"event": e.event, "detail": e.detail, "at": e.at.isoformat()} for e in log
        ],
    }


@router.post("/messages/{message_id}/approve")
async def approve_message(
    message_id: str,
    allow_blanks: bool = False,
    ctx: OrgContext = Depends(require_permission("send_messages")),
    db: AsyncSession = Depends(get_db),
):
    """The one-tap 'Approve & Send'.

    `allow_blanks` (additive, default false — F30): a draft still carrying
    `[Name]`-style blanks is refused with a 422 naming them. Passing true is
    the caller saying "I have read it and I mean to send it as it is". Old
    clients simply get the refusal, which is the safe direction for a build
    that cannot show the blanks.
    """
    message = await message_service.approve_message(
        db, ctx, message_id, allow_blanks=allow_blanks
    )
    await db.commit()
    await job_queue.enqueue(
        "send_message", {"message_id": message.id},
        org_id=ctx.org_id, priority=PRIORITY_SEND,
    )
    return {"approved": True, "status": MessageStatus.QUEUED.value}


@router.post("/messages/{message_id}/reject")
async def reject_message(
    message_id: str,
    body: RejectRequest,
    ctx: OrgContext = Depends(require_permission("send_messages")),
    db: AsyncSession = Depends(get_db),
):
    await message_service.reject_message(db, ctx, message_id, body.reason)
    await db.commit()
    return {"rejected": True}


# ══════════════════════════ Provider webhooks ═══════════════════════════════
webhooks = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhooks.get("/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(request: Request):
    """Meta webhook verification handshake."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == get_settings().whatsapp_webhook_verify_token
    ):
        return params.get("hub.challenge", "")
    return PlainTextResponse("verification failed", status_code=403)


@webhooks.post("/whatsapp")
async def whatsapp_status(request: Request, db: AsyncSession = Depends(get_db)):
    """Delivery receipts from the WhatsApp Cloud API -> Message Delivery Log."""
    payload = await request.json()
    updated = 0
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for status in change.get("value", {}).get("statuses", []):
                    provider_id = status.get("id")
                    state = status.get("status")  # sent | delivered | read | failed
                    if not provider_id or not state:
                        continue
                    message = (
                        await db.execute(
                            select(OutboundMessage).where(
                                OutboundMessage.provider_message_id == provider_id
                            )
                        )
                    ).scalar_one_or_none()
                    if message is None:
                        continue
                    if state == "delivered" and message.status == MessageStatus.SENT.value:
                        message.status = MessageStatus.DELIVERED.value
                    elif state == "failed":
                        message.status = MessageStatus.FAILED.value
                    await message_service.log_event(
                        db, message, f"provider_{state}",
                        str(status.get("errors", ""))[:400] or None,
                    )
                    updated += 1
        await db.commit()
    except (KeyError, TypeError, ValueError):
        pass  # malformed webhook — acknowledge anyway per Meta guidance
    return {"received": True, "updated": updated}
