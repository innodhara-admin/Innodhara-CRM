"""Work management & sync tables — assignments, reminders, the event stream,
incidents, AI decisions and digests (Data Model §5).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class Assignment(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One assignment event of one task — the full history (Data Model §5.1).

    In lead_confirm mode the lead's batch screen flips these rows
    proposed → accepted/overridden — never approvals rows.
    """

    __tablename__ = "assignments"
    __table_args__ = (Index("ix_assignments_org_item", "org_id", "action_item_id"),)

    action_item_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    from_user_id: Mapped[str | None] = mapped_column(String(32))
    to_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    assigned_by: Mapped[str | None] = mapped_column(String(32))  # user id or "ai"
    reason: Mapped[str | None] = mapped_column(Text)  # always written, always shown
    # proposed | accepted | auto_accepted | declined | overridden
    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)
    decline_reason: Mapped[str | None] = mapped_column(String(30))
    decline_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class Reminder(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One scheduled nudge (Data Model §5.2).

    Never fires on leave days or outside working hours; cancelled the instant
    the underlying thing completes.
    """

    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_org_sched", "org_id", "scheduled_at", "sent_at", "cancelled_at"),
        Index("ix_reminders_target", "target_type", "target_id"),
    )

    # action_item | followup | approval | client_commitment | invoice
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False)
    remind_user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1)  # 1 gentle / 2 firm / 3 lead
    channel: Mapped[str] = mapped_column(String(20), default="push")  # push|whatsapp|email
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)


class ProgressEvent(Base, PKMixin, OrgScopedMixin):
    """One meaningful change, anywhere in the system — the heartbeat
    (Data Model §5.3). The project timeline screen is this stream, humanised.
    """

    __tablename__ = "progress_events"
    __table_args__ = (
        Index("ix_events_org_project_at", "org_id", "project_id", "at"),
        Index("ix_events_org_type_at", "org_id", "event_type", "at"),
    )

    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(32))  # user id / "ai" / "system"
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Incident(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One delivery problem or client complaint, tracked until closed
    (Data Model §5.4)."""

    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incidents_org_proj_status", "org_id", "project_id", "status"),)

    project_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    # inbound_message | progress_event + that record's id
    source_type: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str | None] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(10), default="medium")  # low|medium|high
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(32))
    fix_task_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|fixing|resolved
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The takeaway written at closure — becomes a playbook suggestion.
    lesson: Mapped[str | None] = mapped_column(Text)


class AIDecision(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One decision an engine took, with its reasoning (Data Model §5.5).

    'Why did the AI do that?' always has an answer here.
    """

    __tablename__ = "ai_decisions"
    __table_args__ = (Index("ix_ai_decisions_org_proj", "org_id", "project_id"),)

    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # assignment | plan_update | draft_message | state_change | conflict_raised
    # | escalation | feasibility
    decision_type: Mapped[str] = mapped_column(String(30), nullable=False)
    engine: Mapped[str | None] = mapped_column(String(40))  # which engine decided
    input_summary: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    needs_human: Mapped[bool] = mapped_column(Boolean, default=False)
    human_override: Mapped[str | None] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(32))


class Digest(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One generated summary (Data Model §5.6)."""

    __tablename__ = "digests"
    __table_args__ = (Index("ix_digests_org_kind", "org_id", "kind", "generated_at"),)

    # daily_user | weekly_project_internal | weekly_project_client
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    for_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    # For the client kind: the message that carried it after approval.
    sent_message_id: Mapped[str | None] = mapped_column(String(32))
