"""Proposals: build from template+pricing, edit by natural command, download
DOCX/PDF, approve & send (the one-tap gate)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.proposal_agent import parse_and_apply_edit
from app.api.deps import require_permission
from app.core.constants import MessageStatus, ProposalStatus
from app.core.context import OrgContext
from app.core.exceptions import ConflictError, ValidationFailedError
from app.database import get_db
from app.jobs.queue import PRIORITY_SEND, job_queue
from app.models.base import utcnow
from app.models.proposal import ProposalRevision
from app.services import (
    audit_service,
    message_service,
    proposal_email_service,
    proposal_service,
    storage,
)

router = APIRouter(prefix="/proposals", tags=["proposals"])


class BuildProposalRequest(BaseModel):
    lead_id: str
    program_id: str
    template_id: str | None = None
    context_summary: str | None = None
    quantities: dict[str, float] | None = None
    project_id: str | None = None


class EditProposalRequest(BaseModel):
    instruction: str = Field(min_length=3)


class ApproveSendRequest(BaseModel):
    to_address: str
    cc: list[str] = []
    extra_note: str | None = None


def _proposal_dict(p) -> dict:
    return {
        "id": p.id,
        "lead_id": p.lead_id,
        "program_id": p.program_id,
        "title": p.title,
        "status": p.status,
        "content_md": p.content_md,
        "line_items": p.line_items,
        "total_amount": p.total_amount,
        "currency": p.currency,
        "template_version": p.template_version,
        "pricing_version": p.pricing_version,
        # A docx proposal shows the salesperson which sections the AI wrote and
        # which are still blank, so an unfilled one is visible before sending.
        "template_kind": p.template_kind,
        "filled": p.filled_json or [],
        "sent_at": p.sent_at.isoformat() if p.sent_at else None,
        "created_at": p.created_at.isoformat(),
    }


@router.post("")
async def build_proposal(
    body: BuildProposalRequest,
    ctx: OrgContext = Depends(require_permission("send_proposal")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await proposal_service.build_proposal(
        db, ctx,
        lead_id=body.lead_id,
        program_id=body.program_id,
        template_id=body.template_id,
        context_summary=body.context_summary,
        quantities=body.quantities,
        project_id=body.project_id,
    )
    await db.commit()
    return _proposal_dict(proposal)


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await proposal_service.get_proposal(db, ctx.org_id, proposal_id)
    revisions = (
        await db.execute(
            select(ProposalRevision)
            .where(ProposalRevision.proposal_id == proposal_id)
            .order_by(ProposalRevision.revision_no.desc())
            .limit(20)
        )
    ).scalars().all()
    return {
        **_proposal_dict(proposal),
        "revisions": [
            {"revision_no": r.revision_no, "instruction": r.instruction,
             "total_amount": r.total_amount, "edited_at": r.edited_at.isoformat()}
            for r in revisions
        ],
    }


@router.post("/{proposal_id}/edit")
async def edit_proposal(
    proposal_id: str,
    body: EditProposalRequest,
    ctx: OrgContext = Depends(require_permission("send_proposal")),
    db: AsyncSession = Depends(get_db),
):
    """Edit by simple voice or text command, e.g. 'make the workshops 16 and
    the price Rs 1500 per year' (doc §9.1.10)."""
    proposal = await proposal_service.get_proposal(db, ctx.org_id, proposal_id)
    if proposal.status == ProposalStatus.SENT.value:
        raise ValidationFailedError(
            "This proposal was already sent; create a new one to make changes."
        )
    result = await parse_and_apply_edit(db, ctx, proposal, body.instruction)
    await db.commit()
    return {**_proposal_dict(proposal), "edit_result": result}


@router.get("/{proposal_id}/download")
async def download_proposal(
    proposal_id: str,
    format: str = "pdf",
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    proposal = await proposal_service.get_proposal(db, ctx.org_id, proposal_id)
    await proposal_email_service.ensure_rendered_files(db, proposal)
    await db.commit()
    if format == "docx":
        data = storage.read_bytes(ctx.org_id, proposal.docx_path)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ext = "docx"
    else:
        data = storage.read_bytes(ctx.org_id, proposal.pdf_path)
        media, ext = "application/pdf", "pdf"
    filename = f"proposal_{proposal_id[:8]}.{ext}"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{proposal_id}/upload-revision")
async def upload_manual_revision(
    proposal_id: str,
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission("send_proposal")),
    db: AsyncSession = Depends(get_db),
):
    """A human edited the rendered file outside the system and re-submits it
    (mobile G3). The upload becomes the proposal's send artifact, recorded as
    a revision — and it must re-pass internal review before sending. The
    locked total is verified inside the PDF when its text is extractable;
    a file whose numbers no longer match is refused."""
    proposal = await proposal_service.get_proposal(db, ctx.org_id, proposal_id)
    if proposal.status == ProposalStatus.SENT.value:
        raise ValidationFailedError(
            "This proposal was already sent; create a new one to make changes."
        )
    name = (file.filename or "").lower()
    if not (name.endswith(".pdf") or name.endswith(".docx")):
        raise ValidationFailedError("Upload a .pdf or .docx file")
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise ValidationFailedError("File is larger than 15 MB")
    if not data:
        raise ValidationFailedError("The file is empty")

    total_verified = None
    if name.endswith(".pdf"):
        # Best-effort integrity check: the locked total must still appear.
        try:
            import io

            from pypdf import PdfReader

            text = "".join(
                page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages
            )
            if text.strip():
                grouped = f"{proposal.total_amount:,.0f}"
                plain = f"{proposal.total_amount:.0f}"
                total_verified = grouped in text or plain in text.replace(",", "")
                if not total_verified:
                    raise ValidationFailedError(
                        f"The locked total {grouped} {proposal.currency} was not "
                        "found in the uploaded file. Prices come from the pricing "
                        "table — edit the words, never the numbers. If the total "
                        "genuinely changed, request a price change approval first."
                    )
            # No extractable text (scan/image PDF): accepted, flagged unverified.
        except ValidationFailedError:
            raise
        except Exception:  # noqa: BLE001 — parser hiccups must not block uploads
            total_verified = None

    rel_path = storage.save_bytes(
        ctx.org_id, "proposals", f"manual_{proposal_id[:8]}_{file.filename}", data
    )
    if name.endswith(".pdf"):
        proposal.pdf_path = rel_path
    else:
        proposal.docx_path = rel_path

    last_no = (
        await db.execute(
            select(ProposalRevision.revision_no)
            .where(ProposalRevision.proposal_id == proposal_id)
            .order_by(ProposalRevision.revision_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0
    db.add(
        ProposalRevision(
            org_id=ctx.org_id, proposal_id=proposal_id, revision_no=last_no + 1,
            instruction=f"Manually edited file uploaded ({file.filename})"
            + ("" if total_verified else " — total not machine-verified"),
            content_md=proposal.content_md,
            line_items=proposal.line_items or [],
            total_amount=proposal.total_amount,
            edited_by=ctx.user_id,
        )
    )
    # A manual edit invalidates any earlier internal approval.
    proposal.status = ProposalStatus.DRAFT.value
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="proposal.manual_revision_uploaded",
        entity_type="proposal", entity_id=proposal_id,
        detail={"filename": file.filename, "total_verified": total_verified},
    )
    await db.commit()
    return {
        "uploaded": True,
        "revision_no": last_no + 1,
        "total_verified": total_verified,
        "status": proposal.status,
        "note": "Re-submit for internal review before sending"
        + ("" if total_verified else
           "; the file's text was not machine-readable, so the approver "
           "must verify the numbers by eye"),
    }


@router.post("/{proposal_id}/approve-send")
async def approve_and_send(
    proposal_id: str,
    body: ApproveSendRequest,
    ctx: OrgContext = Depends(require_permission("send_proposal")),
    db: AsyncSession = Depends(get_db),
):
    """The 'Approve and Send' tap: prepares (or reuses) the proposal email and
    queues it immediately — sender is the salesperson's own address."""
    proposal = await proposal_service.get_proposal(db, ctx.org_id, proposal_id)
    message = await proposal_email_service.prepare_proposal_email(
        db, ctx, proposal,
        to_address=body.to_address, cc=body.cc, extra_note=body.extra_note,
    )
    message = await message_service.approve_message(db, ctx, message.id)
    await proposal_service.mark_sent(db, proposal, message_id=message.id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="proposal.approved_and_sent",
        entity_type="proposal", entity_id=proposal_id,
        detail={"to": body.to_address, "cc": body.cc},
    )
    await db.commit()
    await job_queue.enqueue(
        "send_message", {"message_id": message.id},
        org_id=ctx.org_id, priority=PRIORITY_SEND,
    )
    return {
        "approved": True,
        "message_id": message.id,
        "status": MessageStatus.QUEUED.value,
        "to": body.to_address,
        "cc": body.cc,
    }


@router.post("/{proposal_id}/submit-review")
async def submit_internal_review(
    proposal_id: str,
    ctx: OrgContext = Depends(require_permission("send_proposal")),
    db: AsyncSession = Depends(get_db),
):
    """Workflow 3.4: mark ready → the org's approval rule fires (e.g. proposal
    above ₹1,00,000 → sales lead approves). Below every rule it clears
    immediately."""
    from app.core.constants import ApprovalEntityType, ProposalStatus
    from app.engines import approval_engine

    proposal = await proposal_service.get_proposal(db, ctx.org_id, proposal_id)
    if proposal.status not in (
        ProposalStatus.DRAFT.value, ProposalStatus.INTERNAL_REVIEW.value,
    ):
        raise ConflictError(f"Proposal is already '{proposal.status}'")
    approval = await approval_engine.request_approval(
        db, org_id=ctx.org_id,
        entity_type=ApprovalEntityType.PROPOSAL.value,
        entity_id=proposal.id,
        project_id=proposal.project_id,
        facts={"amount": proposal.total_amount, "sender_user_id": ctx.user_id},
        reason=f"Proposal '{proposal.title}' ({proposal.total_amount:,.0f} "
        f"{proposal.currency}) ready for internal review",
        default_approver_role=None,
    )
    if approval is None:
        proposal.status = ProposalStatus.APPROVED_INTERNALLY.value
        await db.commit()
        return {"status": proposal.status, "approval_id": None,
                "note": "below every review threshold"}
    proposal.status = ProposalStatus.INTERNAL_REVIEW.value
    await db.commit()
    return {"status": proposal.status, "approval_id": approval.id}
