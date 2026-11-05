"""Organisation (tenant) and its per-organisation settings."""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import PKMixin, TimestampMixin


class Organisation(Base, PKMixin, TimestampMixin):
    """One company on the platform. Parent of every other record."""

    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    email_domain: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    brand_colors: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class OrgSettings(Base, PKMixin, TimestampMixin):
    """Feature switches, retention policy and integration credentials (per org).

    Integration secrets are stored encrypted (Fernet) — see core/crypto.py.
    """

    __tablename__ = "org_settings"

    org_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("organisations.id"), unique=True, nullable=False, index=True
    )

    # Feature switches
    require_action_item_review: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_suggest_lead_state: Mapped[bool] = mapped_column(Boolean, default=True)

    # Data protection (doc §14)
    audio_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    transcript_retention_days: Mapped[int] = mapped_column(Integer, default=365)

    # AI cost control (doc §11.5)
    llm_monthly_budget_usd: Mapped[float] = mapped_column(Float, default=50.0)

    # Locale
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # Default follow-up cadence in days after a follow-up is completed
    followup_cadence_days: Mapped[int] = mapped_column(Integer, default=7)

    # How long a newly opened lead stays announced on everyone's home screen.
    # The card also clears early once the lead leaves OPEN, so this is a
    # ceiling, not a duration.
    lead_open_feed_days: Mapped[int] = mapped_column(Integer, default=3)

    # Integrations — JSON blobs; secret values inside are Fernet-encrypted.
    # email:    {"from_domain": "...", "smtp_username": "...", "smtp_app_password_enc": "..."}
    # whatsapp: {"access_token_enc": "...", "phone_number_id": "..."}
    # calendar: {"calendar_id": "...", "credentials_file": "..."}
    email_integration: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    whatsapp_integration: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)
    calendar_integration: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=dict)

    # ── Workflow-design behaviour dials (Data Model §2.2 ✚ fields) ──────────
    # How AI task assignments go live: auto | lead_confirm.
    assignment_mode: Mapped[str] = mapped_column(String(20), default="lead_confirm")
    # Which weekdays count as working days (Mon..Sun labels).
    working_days: Mapped[list[str]] = mapped_column(
        JSON, default=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    )
    workday_start: Mapped[str] = mapped_column(String(5), default="09:00")
    workday_end: Mapped[str] = mapped_column(String(5), default="18:30")
    # The one priority urgent enough to break quiet hours ("P1").
    quiet_hours_override_priority: Mapped[str] = mapped_column(String(5), default="P1")
    # Working days after due date at which each nudge level fires.
    nudge_gap_days: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=lambda: {"level1": 1, "level2": 3, "level3": 5}
    )
    # After this many unanswered client nudges: stop, create a call task.
    max_unanswered_nudges: Mapped[int] = mapped_column(Integer, default=2)
    # Courtesy cap: max messages per stakeholder per week across ALL projects.
    max_client_messages_per_week: Mapped[int] = mapped_column(Integer, default=3)
    # Days of silence after which the system suggests lead state = cold.
    lead_cold_after_days: Mapped[int] = mapped_column(Integer, default=30)
    # % of max_open_tasks at which new work is steered away from a person.
    high_load_caution_pct: Mapped[int] = mapped_column(Integer, default=80)
    # No delivery work before the advance invoice is paid.
    delivery_requires_advance: Mapped[bool] = mapped_column(Boolean, default=True)
    # Scope-expansion tasks stay blocked until the school confirms the price.
    scope_change_requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    # When the weekly client progress report is drafted for approval.
    client_report_day: Mapped[str] = mapped_column(String(10), default="Friday")
    client_report_time: Mapped[str] = mapped_column(String(5), default="16:00")
    # Payment chasing schedule relative to invoice due date. "cc" names who
    # gets copied: an influence level ("decision_maker") or a stakeholder
    # role in the client's own vocabulary ("principal", "cfo").
    # [{"offset": -3, "tone": "heads_up"}, ..., {"offset": 20, "action": "call_task"}]
    payment_reminder_schedule: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=lambda: [
            {"offset": -3, "tone": "heads_up"},
            {"offset": 3, "tone": "polite"},
            {"offset": 10, "tone": "firm", "cc": "decision_maker"},
            {"offset": 20, "action": "call_task"},
        ],
    )
    # Reply-watch ladder for unanswered outbound (days after send per nudge).
    reply_nudge_after_days: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=lambda: {"nudge1": 4, "nudge2": 8, "call_task": 12}
    )
    # Below this AI confidence, engines route to a human instead of acting.
    ai_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.6)
