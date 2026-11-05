"""Meetings (recordings) and transcripts."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import MeetingStatus
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class Meeting(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_org_lead", "org_id", "lead_id"),
        Index("ix_meetings_org_agent", "org_id", "agent_id"),
        # Retention sweeps scan by (org, created month) — doc §11.2 partitions
        # these by month in PostgreSQL; the index keeps SQLite dev fast too.
        Index("ix_meetings_org_created", "org_id", "created_at"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(30), default=MeetingStatus.UPLOADED.value, nullable=False
    )
    audio_path: Mapped[str | None] = mapped_column(String(500))
    audio_mime: Mapped[str | None] = mapped_column(String(100))
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime)  # retention
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    consent_captured: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    # Suggested lead-state move produced by the pipeline (human confirms).
    state_suggestion: Mapped[str | None] = mapped_column(String(50))

    # ── Project layer (Data Model §7.1 ✚ fields) ─────────────────────────────
    # Empty for a first meeting — filled when the project is born from it.
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    meeting_no: Mapped[int | None] = mapped_column(Integer)  # 1st, 2nd... in project
    # first_visit | negotiation | kickoff | review | closure
    meeting_type: Mapped[str | None] = mapped_column(String(20))
    # School-side people in the room — lets conflict resolution weigh voices.
    attendee_stakeholder_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    attendee_user_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Typed/dictated notes used instead of audio when recording is refused.
    notes_text: Mapped[str | None] = mapped_column(Text)
    # Where this recording's plan stands for "Approve plan" (1 Oct 2026):
    # planning | ready | approved | sent_for_approval | no_plan | failed |
    # discarded | superseded. Empty = the Planner was never started for it.
    # `plan_note` is the plain sentence the app shows with it. Both added by
    # ALTER on live databases (no Alembic).
    plan_state: Mapped[str | None] = mapped_column(String(20))
    plan_note: Mapped[str | None] = mapped_column(Text)


class Transcript(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "transcripts"

    meeting_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("meetings.id"), unique=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Float)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    word_count: Mapped[int | None] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)  # retention
