"""Action items (tasks) — the richest table in the system.

Tasks are born from meetings (extracted by AI), from client replies, from
playbooks, from re-plans, or by hand; they die by being done, cancelled, or
superseded — never by deletion (Data Model §4.4).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.core.constants import ActionItemStatus
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class ActionItem(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "action_items"
    __table_args__ = (
        # Matches the hot query "my open tasks" (doc §11.1).
        Index("ix_action_items_org_owner_status", "org_id", "assignee_id", "status"),
        Index("ix_action_items_org_lead", "org_id", "lead_id"),
        Index("ix_action_items_org_project_status", "org_id", "project_id", "status"),
        Index("ix_action_items_org_due", "org_id", "due_date", "status"),
    )

    lead_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("meetings.id"), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # The doer. Spec name is assignee_id; owner_id kept as a synonym for
    # pre-project-layer code paths.
    assignee_id: Mapped[str | None] = mapped_column(
        "assignee_id", String(32), ForeignKey("users.id"), index=True
    )
    owner_id = synonym("assignee_id")
    status: Mapped[str] = mapped_column(
        String(30), default=ActionItemStatus.OPEN.value, nullable=False
    )
    due_date: Mapped[datetime | None] = mapped_column(DateTime)
    result_note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(32))  # user id or "ai"/"system"

    # ── Project layer (Data Model §4.4 ✚ fields) ─────────────────────────────
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    plan_version_added: Mapped[int | None] = mapped_column(Integer)
    # sales | proposal | preparation | delivery | payment | closure
    phase: Mapped[str | None] = mapped_column(String(20))
    # Matched against user_skills to build the assignment candidate list.
    required_skill: Mapped[str | None] = mapped_column(String(100))
    assigned_by: Mapped[str | None] = mapped_column(String(32))  # user id or "ai"
    # The AI-written reason for the pick — always shown to the assignee.
    assignment_reason: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(5), default="P2")  # P1|P2|P3
    # Tasks that must finish first; assignee not nudged while these are open.
    depends_on_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # plan_activation (default) | when_ready (assigned when dependencies clear)
    assign_on: Mapped[str] = mapped_column(String(20), default="plan_activation")
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    # The colleague this task waits on, when the reason names one (or the
    # blocker picked one). Set by `sync_engine._on_task_blocked`, cleared on
    # unblock; it is what `GET /action-items/waiting-on-me` lists. No FK on
    # purpose: the column is added by ALTER on live databases (no Alembic).
    blocked_on_user_id: Mapped[str | None] = mapped_column(String(32))
    # Waiting on someone OUTSIDE the company. The only writer is
    # `record_vendor_promise` (app/api/workflow.py), which produces:
    # {"vendor_name": "...", "promised_date": "YYYY-MM-DD", "chase_contact": user_id}
    # `vendor_name` is free text, typed at the time — it is never validated
    # against, and never references, the `vendors` catalogue table.
    # `sync_engine.py` reads `vendor_name` first, matching what is actually
    # written. No caller has ever produced a `vendor_id` key.
    external_wait: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    # True = when this finishes, the school should hear about it.
    visible_to_client: Mapped[bool] = mapped_column(Boolean, default=False)
    client_commitment_id: Mapped[str | None] = mapped_column(String(32))
    # 0 none / 1 gentle sent / 2 firm sent / 3 escalated to the lead.
    reminder_level: Mapped[int] = mapped_column(Integer, default=0)
    # meeting | client_reply | ai_refinement | playbook | manual
    source: Mapped[str] = mapped_column(String(20), default="manual")
    # in_app | manual_upload | voice | external | system
    completion_method: Mapped[str | None] = mapped_column(String(20))
    superseded_by: Mapped[str | None] = mapped_column(String(32))
    # Filled on the children when a task is split.
    parent_item_id: Mapped[str | None] = mapped_column(String(32))
