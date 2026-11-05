# app/models/proposal_fill.py
"""One in-progress fill of one simple-flow template for one client.

**This row is the working memory; the chat transcript is only the record.**
`app/ai/conversation.py` replays 12 turns inside a 6,000-character budget,
prunes to 60 rows, stores plain text only, and never replays tool calls, tool
results or entity ids. A fill with 25 tags and a dozen clarifications would be
pruned away mid-job, so the state cannot live in the conversation (D6, and the
measurement behind it in plan section 2.7).

**One table, no columns added anywhere else.** This project has no Alembic:
`create_all` creates a missing table at startup but never adds a column, so a
new column is a manual migration on every environment and a new table is free.
That constraint is why the simple flow rides on the existing
`ProposalTemplate.kind` value `"docx_simple"` rather than a new column (D11),
and why this is the only schema change the whole feature makes.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class FillStatus:
    """`gathering` -> (`asking` <-> `gathering`) -> `reviewing` -> `ready` -> `built`.

    A correction made during review returns the session to `gathering`.
    Nothing is written into a document until `ready`, and `ready` is reachable
    only through `reviewing` -- because the 0.80 confidence threshold is
    self-reported and uncalibrated, so a human sees every value, including the
    ones filled silently (D13).
    """

    GATHERING = "gathering"
    ASKING = "asking"
    REVIEWING = "reviewing"
    READY = "ready"
    BUILT = "built"
    ABANDONED = "abandoned"


class ProposalFillSession(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "proposal_fill_sessions"
    __table_args__ = (
        # Resuming: a fill is found by chat session, lead and programme, so
        # "actually make it 3 units" an hour later lands on the right one.
        Index("ix_fill_sessions_org_chat", "org_id", "chat_session_id"),
        # Sweeping: a session untouched for FILL_SESSION_TTL_DAYS is abandoned
        # rather than silently resumed a week later.
        Index("ix_fill_sessions_org_status", "org_id", "status"),
    )

    lead_id: Mapped[str] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    program_id: Mapped[str] = mapped_column(String(32), ForeignKey("programs.id"), index=True)
    template_id: Mapped[str] = mapped_column(String(32), ForeignKey("proposal_templates.id"))
    template_doc_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("proposal_template_docs.id")
    )
    # Set once the document is produced; null for every fill still in progress.
    proposal_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("proposals.id"))
    # D-C. Where a built MOU is recorded, beside proposal_id. Exactly
    # one of the two is ever set, and which one is decided by
    # document_type below.
    mou_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("mou_documents.id")
    )
    # D-C. The discriminator. Without it an MOU fill and a proposal
    # fill for the same lead, the same programme and the same chat are
    # indistinguishable to find_for_chat, which keys on the chat
    # alone -- so a reply about one would be applied to the other.
    document_type: Mapped[str] = mapped_column(
        String(20), default="proposal", server_default="proposal",
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    # The assistant session this fill belongs to. Null for a fill that did not
    # come from a conversation.
    chat_session_id: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[str] = mapped_column(
        String(20), default=FillStatus.GATHERING, nullable=False
    )
    # The whole client and the whole document (D7), assembled once and replayed
    # verbatim on every later turn, so the answer to turn 7 is grounded in the
    # same facts as turn 1.
    dossier_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # The occurrence map from `docx.tags.scan`, each entry carrying its
    # resolution: value, source, confidence, citation, computed_by, reviewed.
    tags_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Every question asked and the answer it got.
    asked_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
