# app/services/docx_template_service.py
"""Ingest an uploaded .docx and hold the material the console edits against.

Parsing and OCR happen once, here, at upload. Nothing in this module runs on
the proposal-generation path — a salesperson never waits for tesseract.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.program import Program, ProposalTemplate, ProposalTemplateDoc
from app.services import audit_service, storage
from app.services.docx import fill as docx_fill
from app.services.docx import index as docx_index
from app.services.docx import ocr
from app.services.docx import outline as docx_outline
from app.services.docx import tags as docx_tags
from app.services.docx import text as docx_text

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024      # largest real sample is 14.8 MB
CATEGORY_TEMPLATES = "proposal_templates"
_MIN_PROJECTION = 20                     # ProposalTemplateRequest.body_md floor

#: How a template version is written. `simple` is the default the owner
#: asked for: the author writes the placeholders into the Word file as
#: angle-bracket tags and the administrator only uploads it. `complex` is
#: the flow shipped in Tasks 1-23, where a human marks the placeholders up
#: in the console afterwards, and it is unchanged in every respect.
FLOWS = ("simple", "complex")
# D-B. Which kind of document a template produces. A programme may
# have one current template of each.
DOCUMENT_TYPES = ("proposal", "mou")

MOU_NEEDS_SIMPLE = (
    "An MOU template is filled by the assistant, so it has to be uploaded "
    "as \"Word document -- tags filled by the assistant\". There is no "
    "console editor for a contract: every value in one is a tag the "
    "assistant asks about and a person approves before it is written."
)
NO_TAGS = (
    "This document has no placeholders in it. A template filled by the "
    "assistant needs tags written into the Word file -- <School Name>, or "
    "<ask:4 Units> for something it should always ask about -- and without "
    "them every client would get exactly the same proposal. Add the tags "
    "and upload it again, or choose \"Word document -- placeholders marked "
    "here\" to mark them up in the console instead."
)


#: D-F. `Date: ___________` is not a tag and TAG_RE cannot see one:
#: a tag needs angle brackets. An author who leaves a ruled blank
#: gets underscores in front of a client, silently.
_RULED_BLANK = re.compile(r"_{3,}")


def count_ruled_blanks(docx_bytes: bytes) -> int:
    """Runs of three or more underscores, over the WHOLE walk.

    Headers and footers included, and that is the whole point: 47 of
    the owner's 240-paragraph MOU live outside the body. Both of ITS
    blanks happen to sit in the signature table, so a counter that
    walked the body alone would pass against the real document and
    still be wrong for the next one.
    """
    from docx import Document  # noqa: PLC0415 -- heavy, only needed here

    document = Document(io.BytesIO(docx_bytes))
    return sum(len(_RULED_BLANK.findall(docx_text.node_text(p)))
               for p in docx_text.walk_paragraphs(document))


def plan_summary(plan_json: dict | None) -> dict:
    """What the console shows after an upload, and nothing more.

    A simple-flow upload has no editor and no next step, so this summary
    is the whole success screen: how many tags, how many will always be
    asked whatever the model thinks (D4), and which literals were found.

    Counts OCCURRENCES, not literals: `<ask:1 Unit>` written in four cells
    is four questions about four different items (D1). Every template
    uploaded before this feature existed has no `flow` key and reads as
    complex.
    """
    plan = plan_json or {}
    if plan.get("flow") != "simple":
        return {"flow": "complex", "tags": 0, "always_asked": 0,
                "distinct": [], "ruled_blanks": 0,
                "document_type": "proposal"}
    found = plan.get("tags") or []
    return {
        "flow": "simple",
        "tags": len(found),
        "always_asked": sum(
            1 for t in found if t.get("kind") in ("ask", "ask_calculate")
        ),
        "distinct": sorted({t.get("raw", "") for t in found}),
        # D-F. Reported, never refused: a genuinely hand-signed blank
        # is legitimate. A template published before this feature has
        # no such key and correctly reports zero.
        "ruled_blanks": int(plan.get("ruled_blanks") or 0),
        "document_type": plan.get("document_type") or "proposal",
    }


def analyse(docx_bytes: bytes, *, with_ocr: bool = True) -> dict:
    """Everything the console and the model need to know about an upload.

    `with_ocr=False` skips reading the images, which is 97-98% of the
    whole cost (plan section 2.4: 9.84 s of 10.04 s on the largest real
    document). The simple flow does not need it to FIND its tags -- a tag
    cannot live inside a raster image -- so it defers the reading to a
    `docx_ocr` job and returns a finished template in a fifth of a
    second. The complex flow still OCRs inline, exactly as it always has.
    """
    if not docx_bytes:
        raise ValidationFailedError("The uploaded file is empty")
    if len(docx_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationFailedError(
            f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            if "word/document.xml" not in z.namelist():
                raise KeyError("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValidationFailedError(
            "That is not a Word document. Upload a .docx file saved from Word "
            "or Google Docs."
        ) from exc

    try:
        outline = docx_outline.parse(docx_bytes)
    except ValidationFailedError:
        raise
    except Exception as exc:  # noqa: BLE001 — a malformed package must not 500
        logger.exception("Failed to parse an uploaded template")
        raise ValidationFailedError(
            "This document could not be read. Try re-saving it from Word as "
            ".docx and uploading again."
        ) from exc

    projection = docx_outline.project_text(outline)
    if len(projection) < _MIN_PROJECTION:
        raise ValidationFailedError(
            "This document has no text the system can read, so there is "
            "nothing to place placeholders into."
        )

    from docx import Document
    index_kind = docx_index.detect(Document(io.BytesIO(docx_bytes)))
    return {
        "outline": outline,
        "ocr": ocr.ocr_document(docx_bytes) if with_ocr else {},
        "index_kind": index_kind,
        "projection": projection,
    }


async def create_docx_template(
    db: AsyncSession, ctx: OrgContext, *, program_id: str, name: str,
    filename: str, data: bytes, make_current: bool = True, flow: str = "simple",
    document_type: str = "proposal",
) -> tuple[ProposalTemplate, ProposalTemplateDoc]:
    program = (
        await db.execute(
            select(Program).where(Program.id == program_id, Program.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")

    if flow not in FLOWS:
        raise ValidationFailedError(
            f"Unknown flow '{flow}'. Choose one of: {', '.join(FLOWS)}."
        )

    if document_type not in DOCUMENT_TYPES:
        raise ValidationFailedError(
            f"Unknown document type '{document_type}'. Choose one "
            f"of: {', '.join(DOCUMENT_TYPES)}."
        )

    # An MOU is always the simple flow, and that is refused here rather
    # than left to produce a contract with an editor nobody should use.
    if document_type == "mou" and flow != "simple":
        raise ValidationFailedError(MOU_NEEDS_SIMPLE)

    # The simple flow defers OCR to a background job (D12): parse and tag
    # scan are 0.2 s, so the upload returns a finished template and the
    # images are read afterwards.
    analysis = analyse(data, with_ocr=flow != "simple")

    # Both branches decide before anything is stored, so a refused upload
    # leaves no template row and no file behind.
    if flow == "simple":
        occurrences = [o.as_dict() for o in docx_tags.scan(data)]
        if not occurrences:
            raise ValidationFailedError(NO_TAGS)
        # A contract gets its own kind, so that nothing branching on
        # kind can confuse one with a proposal -- and so a proposal
        # fill can refuse to open on an MOU template even though both
        # are tag-filled Word documents.
        kind = "mou_simple" if document_type == "mou" else "docx_simple"
        plan_json = {
            "flow": "simple", "version": 1, "tags": occurrences,
            "document_type": document_type,
            "ruled_blanks": count_ruled_blanks(data),
        }
    else:
        occurrences = []
        kind = "docx"
        plan_json = {"version": 1, "entries": []}

    same_name = (
        await db.execute(
            select(ProposalTemplate)
            .where(
                ProposalTemplate.org_id == ctx.org_id,
                ProposalTemplate.program_id == program_id,
                ProposalTemplate.name == name,
            )
            .order_by(ProposalTemplate.version.desc())
        )
    ).scalars().first()
    version = (same_name.version + 1) if same_name else 1

    if make_current:
        others = (
            await db.execute(
                select(ProposalTemplate).where(
                    ProposalTemplate.org_id == ctx.org_id,
                    ProposalTemplate.program_id == program_id,
                    # D-B: only retire the current template of THIS
                    # document type. Without this, uploading an MOU
                    # leaves the programme with no current proposal
                    # template and every "create the IBC proposal"
                    # answers "No proposal template for this program".
                    ProposalTemplate.document_type == document_type,
                    ProposalTemplate.is_current.is_(True),
                )
            )
        ).scalars().all()
        for other in others:
            other.is_current = False

    template = ProposalTemplate(
        org_id=ctx.org_id, program_id=program_id, name=name, version=version,
        kind=kind, body_md=analysis["projection"],
        is_current=make_current, created_by=ctx.user_id,
        document_type=document_type,
    )
    db.add(template)
    await db.flush()

    rel_path = storage.save_bytes(ctx.org_id, CATEGORY_TEMPLATES, filename, data)
    doc_row = ProposalTemplateDoc(
        org_id=ctx.org_id, template_id=template.id, source_path=rel_path,
        filename=filename, sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data), outline_json=analysis["outline"],
        ocr_json=analysis["ocr"], plan_json=plan_json,
        index_kind=analysis["index_kind"], analysis_status="ready",
    )
    db.add(doc_row)
    await db.flush()

    if flow == "simple":
        from app.jobs.queue import job_queue

        # `db` is passed deliberately: this is inside a request
        # transaction, so the job must commit atomically with the row it
        # names, and a second session would deadlock on SQLite's single
        # write lock. See JobQueue.enqueue.
        await job_queue.enqueue(
            "docx_ocr", {"doc_id": doc_row.id}, org_id=ctx.org_id, db=db,
        )

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.proposal_template_docx_uploaded",
        entity_type="program", entity_id=program_id,
        detail={"name": name, "version": version, "filename": filename,
                "index_kind": analysis["index_kind"],
                "flow": flow, "tags": len(occurrences),
                "blocks": len(analysis["outline"]["blocks"])},
    )
    return template, doc_row


async def get_doc(db: AsyncSession, org_id: str, doc_id: str) -> ProposalTemplateDoc:
    row = (
        await db.execute(
            select(ProposalTemplateDoc).where(
                ProposalTemplateDoc.id == doc_id,
                ProposalTemplateDoc.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Template document not found")
    return row


async def save_plan(
    db: AsyncSession, ctx: OrgContext, doc: ProposalTemplateDoc, plan: dict
) -> list[str]:
    problems = docx_fill.validate_plan(plan, doc.outline_json)
    if problems:
        return problems
    doc.plan_json = plan
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.proposal_template_plan_saved",
        entity_type="proposal_template", entity_id=doc.template_id,
        detail={"entries": len(plan.get("entries") or [])},
    )
    return []
