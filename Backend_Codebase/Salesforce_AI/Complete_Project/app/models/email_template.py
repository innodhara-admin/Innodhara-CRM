"""Word email templates and the state of one email being filled (28 Oct 2026).

New tables only: this project has no Alembic, so `create_all` creates a missing
table at startup but never adds a column to one that exists. Nothing here adds
a column anywhere else.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class EmailTemplate(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One version of one uploaded Word email.

    A common email has a category and no programme; a product email has a
    programme and no category. "Current" is per name: an organisation may hold
    several current templates in one category or for one product.
    """

    __tablename__ = "email_templates"
    __table_args__ = (
        Index("ix_email_templates_org_current", "org_id", "is_current"),
    )

    template_type: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    program_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("programs.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    when_to_use: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    # none | proposal | mou: the client's built document this email carries.
    built_document: Mapped[str] = mapped_column(
        String(10), default="none", nullable=False)
    # The subject line as written in the file, tags and all.
    subject_raw: Mapped[str] = mapped_column(String(500), nullable=False)
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # `docx.tags.scan` occurrences, the subject line's included.
    tags_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(String(32))


class EmailTemplateAttachment(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """A file sent with every email made from one template version."""

    __tablename__ = "email_template_attachments"

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("email_templates.id"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)


class EmailFillStatus:
    """`asking` -> `drafted`, or `waiting_for_document` until the proposal or
    MoU the template carries has been built. `abandoned` is terminal."""

    ASKING = "asking"
    WAITING_FOR_DOCUMENT = "waiting_for_document"
    DRAFTED = "drafted"
    ABANDONED = "abandoned"


class EmailFillSession(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One email from one template, for one client, in one conversation.

    The working memory of the fill, as `proposal_fill_sessions` is for a
    proposal: the chat transcript cannot hold answers across turns.
    """

    __tablename__ = "email_fill_sessions"
    __table_args__ = (
        Index("ix_email_fill_org_chat", "org_id", "chat_session_id"),
        Index("ix_email_fill_org_message", "org_id", "message_id"),
    )

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    chat_session_id: Mapped[str | None] = mapped_column(String(64))
    lead_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("leads.id"), index=True)
    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("email_templates.id"))
    contact_id: Mapped[str | None] = mapped_column(String(32))
    to_address: Mapped[str | None] = mapped_column(String(320))
    cc: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        String(30), default=EmailFillStatus.ASKING, nullable=False)
    dossier_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    asked_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    message_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("outbound_messages.id"))
    proposal_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("proposals.id"))
    mou_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("mou_documents.id"))
    # The formatted body, sent as the email's HTML part.
    html_body: Mapped[str | None] = mapped_column(Text)
