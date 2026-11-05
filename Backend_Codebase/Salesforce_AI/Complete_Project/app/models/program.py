"""Programs, versioned pricing tables, versioned proposal & message templates.

Versioning rule (doc §12): proposals copy the exact template and pricing
version they used, so old proposals never change when pricing is updated.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin, utcnow


class Program(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """A product an organisation sells (e.g. IBC)."""

    __tablename__ = "programs"
    __table_args__ = (Index("ix_programs_org_code", "org_id", "code", unique=True),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PricingTable(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """Versioned price list for a program. Numbers NEVER come from the AI."""

    __tablename__ = "pricing_tables"
    __table_args__ = (Index("ix_pricing_org_program", "org_id", "program_id", "version"),)

    program_id: Mapped[str] = mapped_column(String(32), ForeignKey("programs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    # items: [{"code": "workshop", "label": "STEM Workshop", "unit": "per workshop",
    #          "unit_price": 1500, "notes": "..."}]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(32))


class ProposalTemplate(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """Proposal template per program; many allowed (e.g. short + detailed)."""

    __tablename__ = "proposal_templates"
    __table_args__ = (Index("ix_ptemplates_org_program", "org_id", "program_id"),)

    program_id: Mapped[str] = mapped_column(String(32), ForeignKey("programs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # "markdown" (the original: body_md with {variables}) or "docx" (an uploaded
    # .docx plus a fill plan). Defaulted so every template that already exists
    # keeps its behaviour without a data migration.
    kind: Mapped[str] = mapped_column(String(20), default="markdown", nullable=False)
    # Markdown body with {variables} for kind="markdown": {client_name}
    # (alias {school_name}), {contact_name}, {sender_name}, {org_name},
    # {program_name}, {pricing_table}, {total_amount}, {context_summary}...
    # For kind="docx" this holds a plain-text projection of the uploaded
    # document, so draft_check, revisions, the bundle export and the Android
    # content view keep working unchanged.
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    # D-B. A programme carries ONE current proposal template AND one
    # current MOU template, so `is_current` is really current-per-
    # document-type. `kind` cannot serve as the discriminator:
    # markdown, docx and docx_simple are all proposals.
    document_type: Mapped[str] = mapped_column(
        String(20), default="proposal", server_default="proposal",
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(32))


class ProposalTemplateDoc(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """The uploaded .docx behind a kind="docx" template version.

    One row per template VERSION, not per template family: publishing v2
    uploads a new file and gets its own row, so a proposal built on v1 still
    resolves the exact bytes it was built from.

    `source_path` is written once and never rewritten. Every proposal is
    source + plan + values -> a new file.
    """

    __tablename__ = "proposal_template_docs"
    __table_args__ = (Index("ix_ptdocs_org_template", "org_id", "template_id"),)

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("proposal_templates.id"), unique=True, index=True
    )
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    outline_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ocr_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    index_kind: Mapped[str] = mapped_column(String(10), default="none")
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")
    analysis_error: Mapped[str | None] = mapped_column(Text)


class MessageTemplate(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """Intro / follow-up message templates with variables, per channel."""

    __tablename__ = "message_templates"
    __table_args__ = (Index("ix_mtemplates_org_kind", "org_id", "kind", "channel"),)

    kind: Mapped[str] = mapped_column(String(30), nullable=False)      # intro|follow_up
    channel: Mapped[str] = mapped_column(String(20), nullable=False)   # email|whatsapp
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    subject: Mapped[str | None] = mapped_column(String(300))           # email only
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(32))
