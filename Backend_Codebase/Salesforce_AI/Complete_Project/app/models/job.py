"""Persisted background jobs — survives restarts, supports retry/backoff/DLQ."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import JobStatus
from app.database import Base
from app.models.base import PKMixin, utcnow


class JobRecord(Base, PKMixin):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_next_run", "status", "next_run_at"),)

    org_id: Mapped[str | None] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(30), default=JobStatus.QUEUED.value, nullable=False
    )
    # Lower number = higher priority. Interactive requests beat background jobs
    # (doc §11.7 "quick interactive requests are given priority").
    priority: Mapped[int] = mapped_column(Integer, default=100)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    next_run_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
