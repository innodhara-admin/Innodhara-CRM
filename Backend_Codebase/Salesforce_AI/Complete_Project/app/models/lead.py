"""Leads (schools), contacts, consent, state history and school intelligence."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import LeadState
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class Lead(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """A school we are trying to win. Moves through states (doc §4)."""

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_org_state", "org_id", "state"),
        Index("ix_leads_org_owner", "org_id", "owner_id"),
        Index("ix_leads_org_name", "org_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(300), nullable=False)
    state: Mapped[str] = mapped_column(String(50), default=LeadState.OPEN.value, nullable=False)
    # "Active and Important" = ACTIVE + this flag (doc §4 note).
    is_important: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    # System-suggested state change awaiting human confirmation (doc §4.1)
    suggested_state: Mapped[str | None] = mapped_column(String(50))
    suggested_state_reason: Mapped[str | None] = mapped_column(Text)

    # ── Revival machinery (Workflow 28) ─────────────────────────────────────
    lost_reason: Mapped[str | None] = mapped_column(String(30))  # budget_timing|...
    revival_date: Mapped[datetime | None] = mapped_column(DateTime)
    # AI-written wake-up brief: what they liked, the champion, the objection.
    revival_context: Mapped[str | None] = mapped_column(Text)
    revival_fired_at: Mapped[datetime | None] = mapped_column(DateTime)


class LeadStateHistory(Base, PKMixin, OrgScopedMixin):
    __tablename__ = "lead_state_history"

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(50))
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str | None] = mapped_column(String(32))  # user id or "system"
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Contact(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """A decision maker at a school (Principal, Owner...). Does not log in."""

    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contacts_org_lead", "org_id", "lead_id"),)

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(30))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # card|manual|meeting
    card_image_path: Mapped[str | None] = mapped_column(String(500))
    # Low-confidence OCR is flagged, not hidden (doc §12).
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # Who typed or scanned it in. NULL for contacts the meeting pipeline found
    # in a transcript, and for rows older than the column (2026-09-24). Opening
    # a lead needs a reachable contact added by its owner (lead_service).
    created_by: Mapped[str | None] = mapped_column(String(32))


class ConsentRecord(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """Proof the contact was told about recording (DPDP alignment, doc §14)."""

    __tablename__ = "consent_records"

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(String(32), index=True)
    method: Mapped[str] = mapped_column(String(50), default="verbal")  # verbal|written|in_app
    note: Mapped[str | None] = mapped_column(Text)
    captured_by: Mapped[str | None] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ClientIntelligence(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """Free-form notes about a school, added by voice or typing (doc §9.1.13)."""

    __tablename__ = "client_intelligence"
    __table_args__ = (Index("ix_intel_org_lead", "org_id", "lead_id"),)

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(20), default="typed")  # voice|typed|system
    added_by: Mapped[str | None] = mapped_column(String(32))
