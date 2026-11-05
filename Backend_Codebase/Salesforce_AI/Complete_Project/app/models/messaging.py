"""Outbound messages (email / WhatsApp) and their delivery log.

Nothing reaches a client without a human tapping Approve (doc §12, §13).
Every send carries an idempotency key so retries never double-send.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MessageStatus
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class OutboundMessage(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index("ix_messages_org_status", "org_id", "status"),
        Index("ix_messages_org_created", "org_id", "created_at"),
        Index("ix_messages_idem", "org_id", "idempotency_key", unique=True),
    )

    kind: Mapped[str] = mapped_column(String(30), nullable=False)     # intro|proposal|follow_up|notification
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email|whatsapp
    status: Mapped[str] = mapped_column(
        String(30), default=MessageStatus.PENDING_APPROVAL.value, nullable=False
    )

    lead_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    contact_id: Mapped[str | None] = mapped_column(String(32))
    proposal_id: Mapped[str | None] = mapped_column(String(32))
    followup_id: Mapped[str | None] = mapped_column(String(32))
    sender_user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))

    to_address: Mapped[str] = mapped_column(String(320), nullable=False)  # email or phone
    cc: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Delivered to, never shown in the headers (2026-09-23, meeting invites).
    bcc: Mapped[list[str] | None] = mapped_column(JSON, default=list)
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # [{"path": "orgs/.../proposal.pdf", "filename": "Proposal.pdf"}]

    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(32))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    provider_message_id: Mapped[str | None] = mapped_column(String(300), index=True)

    # ── Project layer (Data Model §8.2 ✚ fields) ─────────────────────────────
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    thread_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # Why the machine drafted it: task_completed | plan_updated | weekly_report
    # | inbound_reply | reminder_ladder | manual
    triggered_by: Mapped[str | None] = mapped_column(String(30))
    # The approval that released it (Approval Engine).
    approval_id: Mapped[str | None] = mapped_column(String(32))
    # Late-night drafts wait for the morning window unless a human overrides.
    scheduled_send_at: Mapped[datetime | None] = mapped_column(DateTime)


class MessageDeliveryLog(Base, PKMixin, OrgScopedMixin):
    """Timeline of delivery events (queued/sent/delivered/failed/bounced)."""

    __tablename__ = "message_delivery_log"
    __table_args__ = (Index("ix_mdl_org_message", "org_id", "message_id"),)

    message_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("outbound_messages.id"), index=True
    )
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class WhatsappLog(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One WhatsApp to a member of staff (4 Nov 2026): a copy of an in-app
    notification or the morning brief. Client messages stay OutboundMessages;
    this is the delivery record for the staff side, which has no approval."""

    __tablename__ = "whatsapp_log"
    __table_args__ = (
        Index("ix_whatsapp_log_org_user_kind", "org_id", "user_id", "kind", "local_date"),
    )

    user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    to_number: Mapped[str] = mapped_column(String(30), nullable=False)
    # A notification kind ("task_assigned", "meeting_processed", ...) or "daily_brief".
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    template: Mapped[str | None] = mapped_column(String(60))
    notification_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # queued | sent | failed | skipped | delivered | read
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    provider_id: Mapped[str | None] = mapped_column(String(300), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    # The organisation's local date a morning brief was for (one per person per day).
    local_date: Mapped[str | None] = mapped_column(String(10))
