"""Outbound message lifecycle.

draft -> pending_approval -> (human taps Approve) -> queued -> sending
      -> sent -> delivered | failed(retry w/ backoff) -> dead_letter

Every send carries an idempotency key (doc §12 "No double sends").
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MessageChannel, MessageStatus
from app.core.context import OrgContext
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.models.base import utcnow
from app.models.messaging import MessageDeliveryLog, OutboundMessage
from app.models.organisation import OrgSettings
from app.models.user import User
from app.services import audit_service, draft_check, email_service, whatsapp_service


async def _close_linked_approval(
    db: AsyncSession, message: OutboundMessage, *, decided_by: str, note: str
) -> None:
    """Resolve the approvals row for a message decided by the OTHER route.

    A message can be approved or rejected two ways: from the Approvals inbox
    (`approval_engine.decide` → `_release_message`) or directly with
    `POST /messages/{id}/approve`, which the follow-up queue and the Jarvis
    inline bars use. Only the first closed the approval, so deciding a message
    the second way left its approval sitting `pending` in someone's inbox for
    the full 48-hour expiry — pointing at work that was already done (and, on
    reject, already redrafted). Found while fixing F2, which makes more
    messages carry approvals in the first place.
    """
    from app.core.constants import ApprovalStatus
    from app.models.comms import Approval

    rows = (
        await db.execute(
            select(Approval).where(
                Approval.org_id == message.org_id,
                Approval.entity_type == "outbound_message",
                Approval.entity_id == message.id,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )
    ).scalars().all()
    for approval in rows:
        approval.status = (
            ApprovalStatus.APPROVED.value if decided_by == "approved"
            else ApprovalStatus.REJECTED.value
        )
        approval.decided_at = utcnow()
        approval.decision_note = note


async def log_event(
    db: AsyncSession, message: OutboundMessage, event: str, detail: str | None = None
) -> None:
    db.add(
        MessageDeliveryLog(
            org_id=message.org_id, message_id=message.id, event=event, detail=detail
        )
    )


async def create_message(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    kind: str,
    channel: str,
    to_address: str,
    body: str,
    subject: str | None = None,
    cc: list[str] | None = None,
    lead_id: str | None = None,
    contact_id: str | None = None,
    proposal_id: str | None = None,
    bcc: list[str] | None = None,
    followup_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    idempotency_key: str | None = None,
    request_approval: bool = False,
) -> OutboundMessage:
    """Create a message in PENDING_APPROVAL — nothing sends without a human tap.

    `request_approval=True` also files an `approvals` row, which is what makes
    the draft reachable from the Approvals inbox (finding F2). Without it a
    message sits in PENDING_APPROVAL that no screen can reach — the card-scan
    sheet and the demo-booking result both claimed "waiting in Approvals" while
    `GET /approvals?status=pending` was empty.

    It is opt-IN rather than automatic on purpose. A caller whose draft is
    already actionable somewhere else — the Jarvis agents show an inline
    approval bar, a proposal email is sent from the proposal screen — would
    otherwise get a SECOND, redundant entry in the inbox that lingers as
    `pending` after the user has acted elsewhere, because
    `POST /messages/{id}/approve` operates on the message directly. Pass True
    only when the approvals inbox is the route to this message.
    """
    if channel == MessageChannel.EMAIL.value and not subject:
        raise ValidationFailedError("Email messages need a subject")
    key = idempotency_key or uuid4().hex
    existing = (
        await db.execute(
            select(OutboundMessage).where(
                OutboundMessage.org_id == ctx.org_id,
                OutboundMessage.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # A repeat request for the same thing. Idempotency exists to stop a
        # DOUBLE SEND — it must not also freeze a draft nobody has acted on.
        #
        # Observed 2026-08-06 on the live demo: a proposal was drafted while it
        # still said `[missing:context_summary]`, the blank was then filled, the
        # PDF correctly re-rendered — and the email that went to the client
        # carried the OLD attachment and the OLD body, because this returned the
        # first message untouched. Same shape as [F38] one level up: a
        # correction that can reach the record but never the queued message.
        #
        # So: a draft that has not been approved yet is REFRESHED from the
        # current content. Anything queued, sent or already decided is left
        # exactly as it is — that is the double-send guard, and it still holds.
        if existing.status in (
            MessageStatus.DRAFT.value, MessageStatus.PENDING_APPROVAL.value
        ):
            existing.subject = subject
            existing.body = body
            existing.cc = cc or []
            existing.bcc = bcc or []
            if attachments is not None:
                existing.attachments = attachments
            await db.flush()
        return existing

    message = OutboundMessage(
        org_id=ctx.org_id,
        kind=kind,
        channel=channel,
        status=MessageStatus.PENDING_APPROVAL.value,
        lead_id=lead_id,
        contact_id=contact_id,
        proposal_id=proposal_id,
        followup_id=followup_id,
        sender_user_id=ctx.user_id,
        to_address=to_address,
        cc=cc or [],
        bcc=bcc or [],
        subject=subject,
        body=body,
        attachments=attachments or [],
        idempotency_key=key,
    )
    db.add(message)
    await db.flush()
    await log_event(db, message, "drafted", f"by {ctx.email}")

    if request_approval:
        # Deliberately AFTER the idempotency short-circuit above: a repeated
        # request returns the original message and must not file a second
        # approval for it.
        from app.core.constants import ApprovalEntityType, Role
        from app.engines import approval_engine

        await approval_engine.request_approval(
            db,
            org_id=ctx.org_id,
            entity_type=ApprovalEntityType.OUTBOUND_MESSAGE.value,
            entity_id=message.id,
            facts={"kind": kind, "channel": channel, "sender_user_id": ctx.user_id},
            reason=(
                f"{kind.replace('_', ' ').capitalize()} to {to_address} "
                f"({channel}) — approve to send"
            ),
            default_approver_role=Role.SALES_LEAD.value,
        )
    return message


async def get_message(db: AsyncSession, org_id: str, message_id: str) -> OutboundMessage:
    message = (
        await db.execute(
            select(OutboundMessage).where(
                OutboundMessage.id == message_id, OutboundMessage.org_id == org_id
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise NotFoundError("Message not found")
    return message


async def checkable_texts(
    db: AsyncSession, message: OutboundMessage
) -> list[str | None]:
    """Every piece of text this message will actually put in front of a client.

    F47: the blank fence only ever saw `subject` and `body`. A proposal email's
    body was clean while the **attached PDF** — the one document a client reads
    closely — opened with `[missing:context_summary]`. The strict check ran, and
    passed, because it was reading the wrong text.

    So the narrative that renders into the attachment is checked too. Returned as
    a list for `find_blanks(*texts)`; `blank_lines` is still given the body plus
    the narrative so a refusal can quote the offending line wherever it lives.
    """
    texts: list[str | None] = [message.subject, message.body]
    if getattr(message, "proposal_id", None):
        from app.models.proposal import Proposal

        proposal = (
            await db.execute(
                select(Proposal).where(
                    Proposal.org_id == message.org_id,
                    Proposal.id == message.proposal_id,
                )
            )
        ).scalar_one_or_none()
        if proposal is not None and proposal.content_md:
            texts.append(proposal.content_md)
    return texts


async def find_message_blanks(
    db: AsyncSession, message: OutboundMessage
) -> tuple[list[str], list[str]]:
    """(blanks, the lines they sit on) across subject, body AND attachment."""
    texts = await checkable_texts(db, message)
    blanks = draft_check.find_blanks(*texts)
    lines: list[str] = []
    for text in texts[1:]:  # skip the subject: a one-line field quotes badly
        lines += draft_check.blank_lines(text, blanks)
    return blanks, lines


async def approve_message(
    db: AsyncSession, ctx: OrgContext, message_id: str, *, allow_blanks: bool = False
) -> OutboundMessage:
    """The one-tap human approval — moves the message into the send queue.

    `allow_blanks=False` is the F30 fence: a draft still carrying `[Name]` or
    `[Insert Date]` is refused rather than sent. It is not a veto — the caller
    can approve again with `allow_blanks=True` — but it can never happen by
    accident, which is the point: the blanks that prompted this finding sat
    *past* the truncated preview the approver was shown.
    """
    message = await get_message(db, ctx.org_id, message_id)
    if message.status == MessageStatus.QUEUED.value:
        return message  # idempotent approve
    if message.status not in (
        MessageStatus.PENDING_APPROVAL.value,
        MessageStatus.DRAFT.value,
        MessageStatus.FAILED.value,
    ):
        raise ConflictError(f"Message is already '{message.status}'")
    if not allow_blanks:
        blanks, lines = await find_message_blanks(db, message)
        if blanks:
            raise ValidationFailedError(draft_check.refusal_message(blanks, lines))
    message.status = MessageStatus.QUEUED.value
    message.approved_by = ctx.user_id
    message.approved_at = utcnow()
    message.queued_at = utcnow()
    await log_event(db, message, "queued", f"approved by {ctx.email}")
    await _close_linked_approval(
        db, message, decided_by="approved",
        note=f"Approved directly from the message by {ctx.email}",
    )
    await audit_service.record(
        db,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        action="message.approved",
        entity_type="message",
        entity_id=message.id,
        detail={"channel": message.channel, "to": message.to_address},
    )
    return message


async def reject_message(
    db: AsyncSession, ctx: OrgContext, message_id: str, reason: str | None = None
) -> OutboundMessage:
    message = await get_message(db, ctx.org_id, message_id)
    if message.status not in (
        MessageStatus.PENDING_APPROVAL.value,
        MessageStatus.DRAFT.value,
    ):
        raise ConflictError(f"Message is already '{message.status}'")
    message.status = MessageStatus.REJECTED.value
    await log_event(db, message, "rejected", reason)
    await _close_linked_approval(
        db, message, decided_by="rejected",
        note=f"Rejected directly from the message by {ctx.email}"
        + (f" — {reason}" if reason else ""),
    )
    if message.kind == "meeting_invite":
        # Same loop as the Approvals inbox: a reason redrafts the invite and
        # puts it back for approval; no reason just closes it.
        from app.services import meeting_invite_service

        await meeting_invite_service.after_rejection(
            db, org_id=ctx.org_id, message=message, reason=reason or "",
        )
    return message


async def execute_send(db: AsyncSession, message: OutboundMessage) -> None:
    """Actually deliver a QUEUED message. Called by the send worker.

    Raises ExternalServiceError on transient failure (caller retries with
    backoff and eventually dead-letters).
    """
    sender = (
        await db.execute(select(User).where(User.id == message.sender_user_id))
    ).scalar_one_or_none()
    org_settings = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == message.org_id))
    ).scalar_one_or_none()

    message.status = MessageStatus.SENDING.value
    message.attempts += 1
    await db.flush()

    if message.channel == MessageChannel.EMAIL.value:
        from app.services import email_fill_service  # noqa: PLC0415

        creds = email_service.resolve_credentials(
            user_email=sender.email if sender else "",
            user_app_password_enc=sender.smtp_app_password_enc if sender else None,
            org_email_integration=org_settings.email_integration if org_settings else None,
        )
        provider_id = await email_service.send_email(
            email_service.EmailPayload(
                sender_name=sender.name if sender else "Sales",
                sender_email=sender.email if sender else "noreply@platform.local",
                to_address=message.to_address,
                subject=message.subject or "",
                body=message.body,
                cc=list(message.cc or []),
                attachments=list(message.attachments or []),
                org_id=message.org_id,
                bcc=list(message.bcc or []),
                html_body=await email_fill_service.html_for_message(
                    db, message.org_id, message.id),
            ),
            creds,
        )
    else:
        creds = whatsapp_service.resolve_credentials(
            org_settings.whatsapp_integration if org_settings else None
        )
        provider_id = await whatsapp_service.send_whatsapp(
            org_id=message.org_id,
            to_phone=message.to_address,
            body=message.body,
            creds=creds,
        )

    message.status = MessageStatus.SENT.value
    message.sent_at = utcnow()
    message.provider_message_id = provider_id
    message.last_error = None
    await log_event(db, message, "sent", provider_id)

    # The event stream hears about every real send; the thread flips to
    # "we spoke last" so the reply watch can start (Data Model §8.1).
    from app.core.constants import EventType
    from app.engines import events as event_stream

    await event_stream.emit(
        db, org_id=message.org_id, event_type=EventType.MESSAGE_SENT.value,
        project_id=message.project_id, entity_type="outbound_message",
        entity_id=message.id, actor=message.sender_user_id,
        details={"kind": message.kind, "channel": message.channel,
                 "to": message.to_address},
    )
    if message.thread_id:
        from app.models.comms import Thread

        thread = (
            await db.execute(select(Thread).where(Thread.id == message.thread_id))
        ).scalar_one_or_none()
        if thread is not None:
            thread.last_message_at = utcnow()
            thread.last_direction = "outbound"
    if message.kind == "proposal":
        await event_stream.emit(
            db, org_id=message.org_id, event_type=EventType.PROPOSAL_SENT.value,
            project_id=message.project_id, entity_type="outbound_message",
            entity_id=message.id, actor=message.sender_user_id,
        )

    # Keep the proposal's own state in sync however its email was approved —
    # mark_sent is idempotent and also walks the project forward.
    if message.proposal_id:
        from app.models.proposal import Proposal
        from app.services import proposal_service

        proposal = (
            await db.execute(
                select(Proposal).where(
                    Proposal.id == message.proposal_id,
                    Proposal.org_id == message.org_id,
                )
            )
        ).scalar_one_or_none()
        if proposal is not None:
            await proposal_service.mark_sent(db, proposal, message_id=message.id)

    # An MOU carried by a Word email template is the client's now (28 Oct
    # 2026): mark it sent, the way the proposal above is.
    if message.channel == MessageChannel.EMAIL.value:
        from app.services import email_fill_service  # noqa: PLC0415

        await email_fill_service.after_sent(db, message)
