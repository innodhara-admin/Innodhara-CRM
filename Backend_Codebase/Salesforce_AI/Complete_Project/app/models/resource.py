"""Resource bookings — the master busy-calendar (Data Model §7.5)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class ResourceBooking(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One claim on someone's time — across ALL projects.

    The single source of truth for 'who and what is busy when'. This table is
    why nobody is ever booked in two cities in the same week.
    """

    __tablename__ = "resource_bookings"
    __table_args__ = (
        Index("ix_bookings_org_user_window", "org_id", "user_id", "date_from", "date_to"),
    )

    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # delivery | demo | travel | leave | hold
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    date_from: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    date_to: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # What created it: action_item | demo | leave | hold + that record's id.
    source_type: Mapped[str | None] = mapped_column(String(30))
    source: Mapped[str | None] = mapped_column(String(32))
    calendar_event_id: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
