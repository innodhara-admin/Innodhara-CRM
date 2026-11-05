# app/jobs/docx_ocr.py
"""Read the text out of a template's images, after the upload has returned.

Measured in plan section 2.4: OCR is 97-98% of the cost of processing an
upload -- 9.84 s of the 10.04 s for the largest real document, and 2.33 s of
2.37 s for the smallest. A tag cannot live inside a raster image, so the
simple flow does not need OCR to FIND its placeholders; it needs it only to
enrich what the model is later told about the document. Deferring it turns a
ten-second upload into a fifth of a second.

The template is finished before this runs. Its tags are scanned, its
occurrence map is stored and it can build a proposal. If this job never runs,
nothing breaks -- the model is simply told less about the pictures.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.database import SessionLocal
from app.models.program import ProposalTemplateDoc
from app.services import storage
from app.services.docx import ocr

logger = logging.getLogger(__name__)


async def run_docx_ocr(payload: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    """Fill in `ocr_json` for one uploaded template document.

    Errors are NOT swallowed. The queue retries and finally dead-letters, which
    is how an operator finds out that tesseract is missing or that a source
    file has gone; a handler that quietly returned would hide a broken OCR
    installation for as long as it stayed broken. Nothing a salesperson or an
    administrator is waiting on depends on this job finishing.
    """
    doc_id = payload["doc_id"]
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(ProposalTemplateDoc).where(ProposalTemplateDoc.id == doc_id)
            )
        ).scalar_one_or_none()
        if row is None:
            # Deleted between being enqueued and being run. Retrying that
            # forever helps nobody, so this is a success with nothing to do.
            logger.info("docx_ocr: template document %s is gone, skipping", doc_id)
            return None

        source = storage.read_bytes(row.org_id, row.source_path)
        recognised = ocr.ocr_document(source)
        row.ocr_json = recognised
        await db.commit()

    logger.info("docx_ocr: read %d images for %s", len(recognised), doc_id)
    return {"doc_id": doc_id, "images": len(recognised)}
