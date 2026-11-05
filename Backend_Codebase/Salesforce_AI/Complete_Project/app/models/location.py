"""Where a sales agent or a sales lead was when they opened the app (2 Oct 2026).

One row per reading the phone sent: a position, or the reason there is none
(location permission refused, GPS off, no fix in time). The app records one
only when it is opened or brought back to the screen -- never in the
background -- and only the org admin can read them (`track_locations`). Kept
LOCATION_RETENTION_DAYS (default 90), then the retention sweep deletes them.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, utcnow

STATUS_OK = "ok"
STATUS_DENIED = "permission_denied"
STATUS_GPS_OFF = "gps_off"
STATUS_TIMEOUT = "timeout"
STATUSES = (STATUS_OK, STATUS_DENIED, STATUS_GPS_OFF, STATUS_TIMEOUT)


class LocationPing(Base, PKMixin, OrgScopedMixin):
    __tablename__ = "location_pings"
    __table_args__ = (
        # The phone mints `client_ref` when it takes the reading, so a reading
        # retried from its outbox is stored once.
        UniqueConstraint("org_id", "user_id", "client_ref",
                         name="uq_location_pings_client_ref"),
        Index("ix_location_pings_org_time", "org_id", "captured_at"),
        Index("ix_location_pings_user_time", "user_id", "captured_at"),
    )

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False
    )
    client_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    # Android's mock-location flag: a fake-GPS app supplied the position.
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The person allowed approximate location only (a rough area).
    approximate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # "open" (the app started) or "resume" (it came back to the screen).
    trigger: Mapped[str] = mapped_column(String(10), default="open", nullable=False)
    # When the phone took the reading (UTC), and when the server got it.
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
