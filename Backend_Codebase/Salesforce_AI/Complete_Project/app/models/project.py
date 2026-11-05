"""The project layer — projects, teams, stakeholders, versioned plans,
commitments, conflicts and playbooks (Data Model §4).

The lead is the relationship; the project is the work. Everything an
engagement produces hangs off one of these rows.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class Project(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One concrete piece of work for a school (Data Model §4.1)."""

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_org_status", "org_id", "status"),
        Index("ix_projects_org_lead", "org_id", "lead_id"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    program_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("programs.id"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)
    # planning | proposal_stage | negotiation | agreed | preparation | delivery
    # | payment_pending | closed | on_hold | lost
    status: Mapped[str] = mapped_column(String(30), default="planning", nullable=False)
    status_reason: Mapped[str | None] = mapped_column(Text)  # for on_hold / lost
    # on_track | at_risk | delayed — recomputed by the Sync Engine.
    health: Mapped[str] = mapped_column(String(20), default="on_track")
    health_reason: Mapped[str | None] = mapped_column(Text)
    sales_owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    ops_owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    current_plan_version: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[datetime | None] = mapped_column(DateTime)
    target_end_date: Mapped[datetime | None] = mapped_column(DateTime)
    # Always computed from pricing tables and approved special prices.
    value_estimate: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    # Chain deals (Workflow 27): commercials on the parent, delivery on children.
    parent_project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    invoicing_mode: Mapped[str | None] = mapped_column(String(20))  # group | per_branch
    created_from_meeting_id: Mapped[str | None] = mapped_column(String(32))


class ProjectMember(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One staff member on one project's team (Data Model §4.2)."""

    __tablename__ = "project_members"
    __table_args__ = (Index("ix_project_members_proj_user", "project_id", "user_id"),)

    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    # trainer | assistant_trainer | proposal_writer | coordinator | accounts
    # | media | owner
    role_in_project: Mapped[str | None] = mapped_column(String(50))
    added_by: Mapped[str | None] = mapped_column(String(32))  # user id or "ai"
    joined_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Filled = no longer on the team; open tasks get redistributed.
    left_at: Mapped[datetime | None] = mapped_column(DateTime)


class Stakeholder(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One contact in the context of one project (Data Model §3.4)."""

    __tablename__ = "stakeholders"
    __table_args__ = (Index("ix_stakeholders_proj_contact", "project_id", "contact_id"),)

    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    contact_id: Mapped[str] = mapped_column(String(32), ForeignKey("contacts.id"), index=True)
    # Free-form snake_case role in the CLIENT organisation's own vocabulary
    # (principal, cto, procurement_head, store_manager...) — authored by the
    # model's read of the discussion or by a human; no fixed list exists.
    # (Renamed from role_at_school; init_db migrates old databases.)
    role_at_client: Mapped[str | None] = mapped_column(String(50))
    # decision_maker | influencer | gatekeeper
    influence: Mapped[str | None] = mapped_column(String(20))
    preferred_channel: Mapped[str] = mapped_column(String(20), default="email")
    preferred_language: Mapped[str] = mapped_column(String(30), default="english")
    receives_progress_updates: Mapped[bool] = mapped_column(Boolean, default=False)
    # Absolute stop — the Communication Engine refuses drafts while true.
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)


class ActionPlan(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One VERSION of a project's global action plan (Data Model §4.3).

    Every re-plan creates a new version with a written diff — the old version
    is never edited and never deleted.
    """

    __tablename__ = "action_plans"
    __table_args__ = (
        Index("ix_action_plans_proj_version", "project_id", "version", unique=True),
    )

    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    # first_meeting | new_meeting | client_reply | progress_review | phase_shift | manual
    trigger: Mapped[str | None] = mapped_column(String(30))
    trigger_ref: Mapped[str | None] = mapped_column(String(32))
    # The AI-written diff, readable by a human at a glance.
    changes_from_previous: Mapped[str | None] = mapped_column(Text)
    # draft | pending_review | active | superseded
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(32))  # user id or "system"
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Operations held until activation (re-dates, cancellations, reopenings):
    # [{"op": "redate", "task_id": "...", "new_due": "...", "old_due": "..."}, ...]
    pending_ops: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ClientCommitment(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One promise — in either direction (Data Model §4.5)."""

    __tablename__ = "client_commitments"
    __table_args__ = (Index("ix_commitments_proj_status", "project_id", "status"),)

    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), default="ours")  # ours | theirs
    promised_to: Mapped[str | None] = mapped_column(String(32))  # stakeholder id
    # user id (ours) or stakeholder id (theirs) — direction decides the table.
    promised_by: Mapped[str | None] = mapped_column(String(32))
    due_date: Mapped[datetime | None] = mapped_column(DateTime)
    linked_action_item_id: Mapped[str | None] = mapped_column(String(32))
    # open | kept | broken | renegotiated
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    # meeting | inbound_message | outbound_message + that record's id.
    source_type: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str | None] = mapped_column(String(32))


class Conflict(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One disagreement between two sources (Data Model §4.6).

    The AI never picks a side silently: it records the conflict, holds the
    affected re-plan as a draft, and puts it in front of the right human.
    """

    __tablename__ = "conflicts"
    __table_args__ = (Index("ix_conflicts_proj_status", "project_id", "status"),)

    project_id: Mapped[str] = mapped_column(String(32), ForeignKey("projects.id"), index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_a_type: Mapped[str | None] = mapped_column(String(30))  # meeting|inbound_message|note
    source_a: Mapped[str | None] = mapped_column(String(32))
    source_b_type: Mapped[str | None] = mapped_column(String(30))
    source_b: Mapped[str | None] = mapped_column(String(32))
    raised_to_user_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(32))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The draft plan version held by this conflict, if any.
    held_plan_id: Mapped[str | None] = mapped_column(String(32))


class Playbook(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One program's standard task wave for one phase (Data Model §4.7)."""

    __tablename__ = "playbooks"
    __table_args__ = (
        Index("ix_playbooks_program_phase", "program_id", "phase", "version"),
    )

    program_id: Mapped[str] = mapped_column(String(32), ForeignKey("programs.id"), index=True)
    # preparation | delivery | payment | closure
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    # Task recipes: [{"title", "required_skill", "offset_days", "priority",
    #                 "visible_to_client"}]
    entries: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(32))


class PlaybookSuggestion(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """A Knowledge-Engine-proposed playbook improvement awaiting admin yes.

    Workflow 22: 'confirm working machines a day early' — accepted with one tap.
    """

    __tablename__ = "playbook_suggestions"

    program_id: Mapped[str] = mapped_column(String(32), index=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    # A single proposed task recipe, same shape as playbooks.entries items.
    entry: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str | None] = mapped_column(Text)
    source_incident_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|rejected
    decided_by: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
