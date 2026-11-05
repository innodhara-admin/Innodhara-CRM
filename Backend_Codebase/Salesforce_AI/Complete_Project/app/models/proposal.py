"""Proposals and their revision history."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ProposalStatus
from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class Proposal(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "proposals"
    __table_args__ = (
        Index("ix_proposals_org_lead", "org_id", "lead_id"),
        Index("ix_proposals_org_status", "org_id", "status"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    program_id: Mapped[str] = mapped_column(String(32), ForeignKey("programs.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=ProposalStatus.DRAFT.value, nullable=False
    )

    # Locked versions (doc §12: "Proposals lock their versions").
    template_id: Mapped[str] = mapped_column(String(32), ForeignKey("proposal_templates.id"))
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional since 2026-09-08 (owner's decision). An offering whose prices
    # live inside its own Word document has nothing to put in a rate card, and
    # the simple flow never reads one: every figure in that document comes
    # from a tag and the person's own answer. The markdown and complex-docx
    # paths still require one and still refuse without it -- they render
    # {total_amount} and {pricing_table} into the body, so a proposal built
    # without a rate card there would have holes where the commercials belong.
    #
    # A database that already exists needs
    # scripts/migrations/2026-09-08_optional_rate_card.py; `create_all` builds
    # a new one correctly from here.
    pricing_table_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("pricing_tables.id"), nullable=True)
    pricing_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Rendered content and computed commercials. line_items:
    # [{"code","label","unit","unit_price","quantity","line_total"}]
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    # Variables used to render the template (client_name, contact_name, ...);
    # kept so the commercial block can be regenerated after edits.
    variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="INR")

    # What each placeholder in a docx template resolved to, and from where:
    # [{"key","kind","source":"system"|"ai"|"unfilled","text","brief","anchor"}]
    # Empty for markdown templates.
    filled_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Copied from the template at build time, so a proposal keeps saying how it
    # was produced even if the template is later replaced or deleted.
    template_kind: Mapped[str] = mapped_column(
        String(20), default="markdown", nullable=False
    )

    docx_path: Mapped[str | None] = mapped_column(String(500))
    pdf_path: Mapped[str | None] = mapped_column(String(500))

    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_message_id: Mapped[str | None] = mapped_column(String(32))

    # ── Project layer (Data Model §6.5 ✚ fields) ─────────────────────────────
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # Filled on an amendment (scope change): the accepted proposal it modifies.
    amends_proposal_id: Mapped[str | None] = mapped_column(String(32))
    # When a special price was granted, the approval that allows it — no number
    # ever exists without a recorded human yes.
    special_price_approval_id: Mapped[str | None] = mapped_column(String(32))


class ProposalRevision(Base, PKMixin, OrgScopedMixin):
    """Every edit (voice or text command) is kept — full audit of changes."""

    __tablename__ = "proposal_revisions"

    proposal_id: Mapped[str] = mapped_column(String(32), ForeignKey("proposals.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text)   # the human command
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    edited_by: Mapped[str | None] = mapped_column(String(32))
    edited_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
