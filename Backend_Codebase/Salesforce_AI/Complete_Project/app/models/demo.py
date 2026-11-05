"""Demo teams, memberships and scheduled demos."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import DemoStatus
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class DemoTeam(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """Demo team record — fields per doc §9.5 (name, lead, media rep, sales rep)."""

    __tablename__ = "demo_teams"
    __table_args__ = (Index("ix_demo_teams_org_name", "org_id", "name", unique=True),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    lead_user_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    media_rep_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))
    sales_rep_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"))


class DemoTeamMember(Base, PKMixin, OrgScopedMixin):
    __tablename__ = "demo_team_members"
    __table_args__ = (Index("ix_dtm_team_user", "team_id", "user_id", unique=True),)

    team_id: Mapped[str] = mapped_column(String(32), ForeignKey("demo_teams.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    role_in_team: Mapped[str] = mapped_column(String(50), default="member")


class Demo(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "demos"
    __table_args__ = (
        Index("ix_demos_org_date", "org_id", "scheduled_date"),
        Index("ix_demos_org_team_date", "org_id", "team_id", "scheduled_date"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    team_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("demo_teams.id"), index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_time: Mapped[str | None] = mapped_column(String(10))  # "10:30"
    status: Mapped[str] = mapped_column(String(30), default=DemoStatus.SCHEDULED.value)
    notes: Mapped[str | None] = mapped_column(Text)
    calendar_event_id: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # ── Project layer (Data Model §7.4) ──────────────────────────────────────
    # The project the demo serves (empty for early sales demos on a bare lead).
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # The plan task that scheduled it — task and demo record stay one thing.
    action_item_id: Mapped[str | None] = mapped_column(String(32))
