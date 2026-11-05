"""Follow-up reminders per lead."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import FollowUpStatus
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class FollowUp(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "followups"
    __table_args__ = (
        Index("ix_followups_org_due_status", "org_id", "due_date", "status"),
        Index("ix_followups_org_lead", "org_id", "lead_id"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    owner_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), default="email")  # email|whatsapp|call
    status: Mapped[str] = mapped_column(String(20), default=FollowUpStatus.PENDING.value)
    note: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(32))  # sent OutboundMessage
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(32))
    reminded: Mapped[bool] = mapped_column(default=False)  # daily reminder sent?
