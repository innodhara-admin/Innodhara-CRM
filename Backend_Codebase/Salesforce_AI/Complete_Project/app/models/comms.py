"""Threads, inbound messages, approval rules and approvals (Data Model §8)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class Thread(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One conversation: one person + one channel, tied to a project — or,
    before any project exists, to the lead (Data Model §8.1).
    """

    __tablename__ = "threads"
    __table_args__ = (
        Index("ix_threads_org_lead", "org_id", "lead_id"),
        Index("ix_threads_org_project", "org_id", "project_id"),
        Index("ix_threads_contact_channel", "contact_id", "channel"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    contact_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    stakeholder_id: Mapped[str | None] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email|whatsapp
    subject: Mapped[str | None] = mapped_column(String(500))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime)
    # inbound = the school wrote last (ball in our court); outbound = we wait.
    last_direction: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|settled|dormant
    # The staff member who owns this conversation (thread_owner approvals).
    owner_user_id: Mapped[str | None] = mapped_column(String(32))


class InboundMessage(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One message the school sends us — the listening half (Data Model §8.3).

    Nothing is ever dropped: a message that matches nothing goes to triage.
    """

    __tablename__ = "inbound_messages"
    __table_args__ = (
        Index("ix_inbound_org_status", "org_id", "status"),
        Index("ix_inbound_org_thread", "org_id", "thread_id"),
    )

    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email|whatsapp
    from_address: Mapped[str | None] = mapped_column(String(320))
    to_address: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    matched_contact_id: Mapped[str | None] = mapped_column(String(32))
    matched_lead_id: Mapped[str | None] = mapped_column(String(32), index=True)
    matched_project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # One message spanning several projects (Workflow 29).
    related_project_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    thread_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # question | change_request | approval | rejection | complaint | payment_info
    # | scheduling | acknowledgement | unknown
    intent: Mapped[str | None] = mapped_column(String(30))
    # For change requests: price | content | date | scope | other
    change_type: Mapped[str | None] = mapped_column(String(20))
    sentiment: Mapped[str | None] = mapped_column(String(10))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    # The specific asks, broken into a checklist the coverage check ticks off.
    extracted_points: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # new | processed | needs_human | triage
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    linked_plan_version: Mapped[int | None] = mapped_column(Integer)
    needs_human_reason: Mapped[str | None] = mapped_column(Text)


class ApprovalRule(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One rule about who must say yes to what (Data Model §8.5).

    Rules are data — changing who approves what never needs a code change.
    """

    __tablename__ = "approval_rules"
    __table_args__ = (Index("ix_approval_rules_org_entity", "org_id", "entity_type"),)

    # outbound_message | proposal | price_change | plan_change | invoice
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # When the rule kicks in, e.g. {"discount_pct_gt": 10} or
    # {"amount_gt": 100000} or {"date_shift_days_gt": 2} or
    # {"kind": "progress_update"} — first matching rule (by rank) decides.
    condition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rank: Mapped[int] = mapped_column(Integer, default=100)  # lower = checked first
    # An org role, or "thread_owner" / "sender".
    approver_role: Mapped[str] = mapped_column(String(30), nullable=False)
    fallback_role: Mapped[str | None] = mapped_column(String(30))
    # Chained approvals: this role reviews first and attaches a recommendation.
    recommender_role: Mapped[str | None] = mapped_column(String(30))
    # Joint approvals: a second approver when both sides must say yes.
    joint_with_role: Mapped[str | None] = mapped_column(String(30))
    # Joint approver only required when this condition also matches
    # (e.g. {"delivery_dates_moved": true}).
    joint_condition: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_hours: Mapped[float] = mapped_column(Float, default=48.0)
    description: Mapped[str | None] = mapped_column(String(300))


class Approval(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One approval request — the human gate, recorded (Data Model §8.6)."""

    __tablename__ = "approvals"
    __table_args__ = (
        Index("ix_approvals_org_status", "org_id", "status"),
        Index("ix_approvals_requested_from", "requested_from_user_id", "status"),
    )

    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(32), index=True)
    requested_from_user_id: Mapped[str | None] = mapped_column(String(32))
    requested_from_role: Mapped[str | None] = mapped_column(String(30))
    # recommend | decide (single-step approvals are always decide)
    stage: Mapped[str] = mapped_column(String(15), default="decide")
    chain_parent_id: Mapped[str | None] = mapped_column(String(32))
    # The recommendation attached by the recommend stage, travelling with it.
    recommendation: Mapped[str | None] = mapped_column(Text)
    joint_with_user_id: Mapped[str | None] = mapped_column(String(32))
    joint_status: Mapped[str | None] = mapped_column(String(15))  # pending|approved|rejected
    joint_decision_note: Mapped[str | None] = mapped_column(Text)
    joint_decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Records released by this same yes when they succeed or fail together:
    # [{"entity_type": "outbound_message", "entity_id": "..."}]
    bundled_entities: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    # pending | approved | rejected | expired | escalated
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    escalated_to_user_id: Mapped[str | None] = mapped_column(String(32))
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime)
