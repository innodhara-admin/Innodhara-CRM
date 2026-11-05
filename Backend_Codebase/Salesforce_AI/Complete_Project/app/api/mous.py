# app/api/mous.py
"""Reading a built MOU back.

**A contract is not a proposal (D-A), and this module exists so that stays
true at the API boundary and not only in the schema.** An MOU is signed after
a proposal has been accepted, so one wearing a Proposal's clothes would arrive
on an already-closed deal: `inbound_engine` reads a SENT proposal as "the deal
is agreed". The lead detail therefore carries `mous` beside `proposals` and
never inside it.

The payload has NO `total_amount`, NO `line_items` and NO `currency`, because
`MouDocument` has no such columns. That is not an omission to be tidied up
later: a screen that sums a client's documents cannot pick a contract up if
the number is not there to be summed. The last session shipped "Total amount:
2200" for a document reading Rs. 15,00,000 by carrying the proposal's shape
across without asking whether its premise came too.

**The file paths are not in the payload; the file is.** The plan asked for
"both file paths", but a storage key is useless to a client -- nothing serves
one -- and this project's own idiom is `/download?format=`, which is what
`proposals` does and what the Android side already knows how to call. So the
payload says WHETHER each file exists and the download route serves it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.models.mou import MouDocument, MouRevision
from app.services import storage
from app.services.docx import convert

router = APIRouter(prefix="/mous", tags=["mous"])

DOCX_MEDIA = ("application/vnd.openxmlformats-officedocument"
              ".wordprocessingml.document")


async def _get(db: AsyncSession, org_id: str, mou_id: str) -> MouDocument:
    """This organisation's MOU, or 404.

    404 rather than 403, and the org filter is in the WHERE clause rather than
    checked after loading: telling a stranger that an id exists is itself a
    leak, and a check that runs after the row is in hand is a check somebody
    will one day move.
    """
    mou = (await db.execute(select(MouDocument).where(
        MouDocument.id == mou_id,
        MouDocument.org_id == org_id,
    ))).scalar_one_or_none()
    if mou is None:
        raise NotFoundError("MOU not found")
    return mou


def _mou_dict(mou: MouDocument) -> dict:
    return {
        "id": mou.id,
        "lead_id": mou.lead_id,
        "program_id": mou.program_id,
        "title": mou.title,
        "status": mou.status,
        "content_md": mou.content_md,
        "template_id": mou.template_id,
        "template_version": mou.template_version,
        # What went into it, for the app's "what went into this" card. The
        # complex flow's six keys plus computed_by and citation -- renaming
        # one turns a working card into a blank one.
        "filled": mou.filled_json or [],
        "has_docx": bool(mou.docx_path),
        "has_pdf": bool(mou.pdf_path),
        "sent_at": mou.sent_at.isoformat() if mou.sent_at else None,
        "created_at": mou.created_at.isoformat(),
    }


@router.get("/{mou_id}")
async def get_mou(
    mou_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    mou = await _get(db, ctx.org_id, mou_id)
    revisions = (await db.execute(
        select(MouRevision)
        .where(MouRevision.mou_id == mou_id,
               MouRevision.org_id == ctx.org_id)
        .order_by(MouRevision.revision_no.desc())
        .limit(20)
    )).scalars().all()
    return {
        **_mou_dict(mou),
        # Newest first. Revision 1 is the contract as first built, so what it
        # said before the Nth correction is revision N -- and once the file
        # has been written anew, this is the only place that survives.
        "revisions": [
            {"revision_no": r.revision_no, "instruction": r.instruction,
             "edited_at": r.edited_at.isoformat()}
            for r in revisions
        ],
    }


@router.get("/{mou_id}/download")
async def download_mou(
    mou_id: str,
    format: str = "pdf",
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    """The contract itself.

    A missing PDF is converted here rather than refused. F3 leaves `pdf_path`
    null when LibreOffice fails, deliberately -- losing an approved contract
    over a converter hiccup is worse than converting late -- and this is where
    that retry was always going to happen.
    """
    mou = await _get(db, ctx.org_id, mou_id)
    if not mou.docx_path:
        raise NotFoundError("That MOU has no document stored.")

    if format == "docx":
        return _file(storage.read_bytes(ctx.org_id, mou.docx_path),
                     DOCX_MEDIA, mou_id, "docx")

    if not mou.pdf_path:
        mou.pdf_path = storage.save_bytes(
            ctx.org_id, storage.CATEGORY_PROPOSALS,
            f"mou_{mou_id[:8]}.pdf",
            convert.docx_to_pdf(storage.read_bytes(ctx.org_id, mou.docx_path)),
        )
        await db.commit()
    return _file(storage.read_bytes(ctx.org_id, mou.pdf_path),
                 "application/pdf", mou_id, "pdf")


def _file(data: bytes, media: str, mou_id: str, ext: str) -> Response:
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition":
                 f'attachment; filename="mou_{mou_id[:8]}.{ext}"'},
    )
