"""Daily snapshots behind the sales head's trend lines (23 Oct 2026).

Most history on the sales head's screens is rebuilt by replaying
`lead_state_history`, so it works from the first day. Two numbers cannot be
replayed, because what they are made of is not kept over time: a deal's score
and the org pulse. Those are written here once a day, lazily -- the first
/insights request of the day for an organisation writes that day's rows --
so the scheduler is not touched.

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-23-sales-head-design.md
section 9.1.4. No foreign keys: the reset taxonomy wipes these with the other
transactional rows, before `leads`.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, utcnow

KIND_DEAL_SCORE = "deal_score"
KIND_ORG_PULSE = "org_pulse"


class InsightSnapshot(Base, PKMixin, OrgScopedMixin):
    __tablename__ = "insight_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "day", "kind", "subject_id",
                         name="uq_insight_snapshots_key"),
        Index("ix_insight_snapshots_org_kind_day", "org_id", "kind", "day"),
    )

    # The organisation's own calendar day (its timezone), not the UTC date.
    day: Mapped[date] = mapped_column(Date, nullable=False)
    # deal_score | org_pulse
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # The lead for a deal score; the organisation itself for the pulse.
    subject_id: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
