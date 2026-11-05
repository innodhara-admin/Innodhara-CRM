"""Relationship management: who looks after a client once the selling stops."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import (
    CycleOutcome,
    CycleSource,
    EngagementStatus,
    OpportunityStatus,
)
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class LeadCycle(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One round of business with one client.

    The lead keeps a single `state` column, which always means THIS round's
    state, so every query that reads `lead.state` is untouched by any of this.
    A cycle row is the record of a round having happened: who owned it, how it
    started, how it ended.

    Rows are written lazily. A client sold to once and closed has none, and
    needs none — the screens for that lead are exactly what they were. The
    first time a client comes back, the round that already happened is written
    down alongside the new one, so a two-round client has two rows and the two
    cards the plan describes.

    Two designs were rejected and are worth naming. A brand new lead per round
    (what chain deals do) splits contacts and history across records, so
    "everything we know about this client" ends up in two places. A separate
    Client/Engagement entity is cleaner on paper and touches almost every
    query in the system, which is a lot of risk for a card on a page.
    """

    __tablename__ = "lead_cycles"
    __table_args__ = (
        Index("ix_lead_cycles_org_lead", "org_id", "lead_id"),
        Index("ix_lead_cycles_lead_number", "lead_id", "cycle_number", unique=True),
    )

    lead_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("leads.id"), index=True, nullable=False
    )
    # 1, 2, 3 … in order. Unique per lead, which is what stops two rounds
    # being opened by two taps at the same moment.
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Null while a reopened lead is waiting for a sales lead to pick someone.
    owner_id: Mapped[str | None] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(
        String(20), default=CycleSource.COLD_CALL.value, nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(
        String(20), default=CycleOutcome.RUNNING.value, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(32))
    # Why this round started. For a second round, the relationship manager's
    # own words about what the client said.
    note: Mapped[str | None] = mapped_column(Text)


class RelationshipEngagement(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One client handed to one relationship manager.

    A client has at most one ACTIVE engagement at a time, and normally only
    ever one engagement full stop — the manager does not rotate. That rule is
    enforced in `relationship_service`, not by a partial unique index, because
    partial indexes are the one piece of index syntax that differs between
    SQLite and PostgreSQL and this schema is built by `create_all` on both.

    Reassignment moves `manager_id` on the row that is already here rather
    than opening a second one: a wrong first pick is a correction, not a new
    chapter in the client's history.

    Ending is the other direction. When the client goes back into the sales
    process the engagement stops outright — status `returned_to_sales`, an
    `ended_at`, and nothing scheduled. If they want a manager again after the
    next close, somebody presses the button again.
    """

    __tablename__ = "relationship_engagements"
    __table_args__ = (
        Index("ix_engagements_org_lead", "org_id", "lead_id"),
        Index("ix_engagements_org_manager_status", "org_id", "manager_id", "status"),
    )

    lead_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("leads.id"), index=True, nullable=False
    )
    manager_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True, nullable=False
    )
    # The person who pressed the button. "ai" is not a valid value here: a
    # human always decides that a client is handed over, even when the AI
    # chose who to.
    assigned_by: Mapped[str] = mapped_column(String(32), nullable=False)
    # Why this manager. Written whether the AI chose or a person overrode it,
    # so the "Why this person?" sheet always has prose to show — the F10 trap
    # was a suggestion offered with nothing recorded behind it.
    ai_reason: Mapped[str | None] = mapped_column(Text)
    # True when a human picked the manager instead of taking the AI's choice.
    # Kept because "the AI got it wrong here" is the only signal that the
    # scoring needs looking at.
    overridden: Mapped[bool] = mapped_column(default=False, nullable=False)

    status: Mapped[str] = mapped_column(
        String(30), default=EngagementStatus.ACTIVE.value, nullable=False
    )

    # ── "they might be ready to buy again" ──────────────────────────────────
    # Raised by a catch-up, never acted on by itself. At most one is open per
    # client, which is why these are columns here rather than their own table:
    # a second hint before the first is answered replaces it, because a person
    # deciding is what closes the question, not the number of hints.
    opportunity_status: Mapped[str] = mapped_column(
        String(20), default=OpportunityStatus.NONE.value, nullable=False
    )
    opportunity_reason: Mapped[str | None] = mapped_column(Text)
    # The client's own words. A person reads this to decide, so it is stored
    # verbatim and never a paraphrase.
    opportunity_quote: Mapped[str | None] = mapped_column(Text)
    opportunity_meeting_id: Mapped[str | None] = mapped_column(String(32))
    opportunity_at: Mapped[datetime | None] = mapped_column(DateTime)
    opportunity_decided_by: Mapped[str | None] = mapped_column(String(32))
    opportunity_decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_reason: Mapped[str | None] = mapped_column(Text)
