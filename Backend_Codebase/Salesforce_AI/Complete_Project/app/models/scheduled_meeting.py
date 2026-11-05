"""A meeting arranged with a client — not a demo (customer ask, 21 Sep 2026).

Demos carry a demo team and are booked by leads and the admin. A meeting is
simpler and anyone who can see the client may arrange one: from the app, from
Jarvis, or because a recording contains an agreed meeting. Its invite email is
an ordinary OutboundMessage (kind "meeting_invite") that waits in Approvals.

Named ScheduledMeeting because `Meeting` already means a recording.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import JSON, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class ScheduledMeeting(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "scheduled_meetings"
    __table_args__ = (
        Index("ix_scheduled_meetings_org_date", "org_id", "meeting_date"),
        Index("ix_scheduled_meetings_org_lead", "org_id", "lead_id"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(32))
    purpose: Mapped[str | None] = mapped_column(Text)
    meeting_date: Mapped[date] = mapped_column(Date, nullable=False)
    # "HH:MM" in the organisation's time, like Demo.scheduled_time. Null only
    # when a recording agreed a day but no time; the invite is then all-day
    # until a redraft ("make it 11") sets one.
    start_time: Mapped[str | None] = mapped_column(String(5))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|cancelled
    organizer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Extra addresses for the invite; the client's primary contact is always "to".
    cc: Mapped[list[str]] = mapped_column(JSON, default=list)
    bcc: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20), default="app")  # app|jarvis|recording
    # The recording that agreed it, when source == "recording" (one per recording).
    recording_meeting_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action_item_id: Mapped[str | None] = mapped_column(String(32))
    calendar_event_id: Mapped[str | None] = mapped_column(String(200))
    # The latest invite draft, and pending_approval | rejected | no_contact.
    # Once approved, the message itself carries queued / sent.
    invite_message_id: Mapped[str | None] = mapped_column(String(32))
    invite_status: Mapped[str | None] = mapped_column(String(20))
