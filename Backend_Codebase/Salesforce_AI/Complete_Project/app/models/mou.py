# app/models/mou.py
"""A memorandum of understanding, built from a tagged Word template.

**Deliberately not a `Proposal`, and this is the whole of decision D-A.** A
`Proposal` row is read by five things that describe a DEAL:

    api/leads.py:357          the lead screen's proposal list
    engines/knowledge_engine  the client's own history, fed back to a model
    engines/document_engine   accepted_total, which sums total_amount
    engines/approval_engine   approval routing for a priced proposal
    engines/inbound_engine    "a SENT proposal on this project" == the deal
                              is agreed

The last one decides it. An MOU is signed AFTER a proposal has been accepted,
so an MOU wearing a Proposal's clothes would arrive on an already-closed deal
and advance its state on its own.

**No `total_amount`, no `line_items`, no `pricing_table_id`, no
`project_id`.** Absent rather than merely unused, so that no aggregate written
later can pick an MOU up by accident. An MOU's prices live inside its own
document and are filled by tags, exactly as a simple-flow proposal's are, and
D37 already says a document carrying its own prices needs no rate card. The
last session shipped "Total amount: 2200" for a document reading
Rs. 15,00,000 because the machinery was carried across without asking whether
its premise came too; a table with no total cannot make that mistake.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import (OrgScopedMixin, PKMixin, TimestampMixin,
                             utcnow)


class MouStatus:
    """`draft` -> `sent`.

    There is no `accepted`: accepting an MOU is a signature on paper, and this
    system has no way to observe one. Once it is `sent` the client is holding
    the document, so a correction is refused outright -- an amendment is a new
    MOU, not a quiet rewrite of the file they were sent.
    """

    DRAFT = "draft"
    SENT = "sent"


class MouDocument(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "mou_documents"
    __table_args__ = (Index("ix_mous_org_lead", "org_id", "lead_id"),)

    lead_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("leads.id"), index=True
    )
    program_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("programs.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=MouStatus.DRAFT, nullable=False
    )

    # Which template version this was built from. The source document is never
    # rewritten (D3), so these two resolve the exact bytes it came from.
    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("proposal_templates.id")
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # The projected plain text of the document that was built. The .docx is
    # the artefact a client receives; this is the record of it, and it is what
    # search and the Android content view read.
    content_md: Mapped[str] = mapped_column(Text, nullable=False)

    # Provenance, read by the Android "What went into this" card. THE COMPLEX
    # FLOW'S SIX KEYS -- key, kind, source, text, brief, anchor -- plus
    # computed_by and citation. Renaming one turns a working card into a blank
    # one, which is a defect the last session shipped and had to find by hand.
    filled_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    docx_path: Mapped[str | None] = mapped_column(String(500))
    pdf_path: Mapped[str | None] = mapped_column(String(500))

    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_message_id: Mapped[str | None] = mapped_column(String(32))


class MouRevision(Base, PKMixin, OrgScopedMixin):
    """What this MOU said before it was corrected.

    A correction rewrites the MOU in place -- the same row, so the id the
    salesperson is already holding keeps working -- and without this the
    superseded wording is gone. On a contract that is the wrong thing to lose:
    "what did this say before we changed it" is a question somebody eventually
    asks, and the file itself has been written anew by then.

    **`ProposalRevision` could not be reused, and this is not a preference.**
    Its foreign key is `proposal_id -> proposals.id`; it carries `line_items`
    and `total_amount`, which are the exact commercial columns `MouDocument`
    leaves out so no aggregate can pick an MOU up (D-A); and `mou_documents`
    is wiped BEFORE `proposal_revisions`, so a row of one pointing at a row of
    the other would be orphaned by a reset.

    `revision_no` counts from 1, and revision 1 is the document as first
    built -- so the wording before the Nth correction is revision N, exactly
    as `proposal_revisions` numbers them.
    """

    __tablename__ = "mou_revisions"

    mou_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("mou_documents.id"), index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction: Mapped[str | None] = mapped_column(Text)   # the human command
    content_md: Mapped[str] = mapped_column(Text, nullable=False)

    # The provenance as it stood for THIS version. Kept per revision because
    # a correction changes which values went in, and the record of a document
    # is not complete without the record of where its values came from.
    filled_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # A plain column, not a foreign key -- exactly as ProposalRevision has it,
    # so a revision survives the user who made it being removed.
    edited_by: Mapped[str | None] = mapped_column(String(32))
    edited_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
