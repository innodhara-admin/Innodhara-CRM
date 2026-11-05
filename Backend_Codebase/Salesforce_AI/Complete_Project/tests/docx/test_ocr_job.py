# tests/docx/test_ocr_job.py
"""OCR runs after the upload has already returned (Task B2).

Measured in plan section 2.4: OCR is 97-98% of the cost of processing an
upload -- 9.84 s of the 10.04 s for the largest real document. A tag cannot
live inside a raster image, so the simple flow does not need OCR to find its
placeholders, only to enrich what the model later knows. Deferring it turns a
ten-second upload into a fifth of a second.
"""
import io
import time
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select

from app.database import SessionLocal
from app.jobs.docx_ocr import run_docx_ocr
from app.models.job import JobRecord
from app.models.program import ProposalTemplateDoc
from app.services import docx_template_service as dts
from tests.conftest import auth

API = "/api/v1"
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
BIGGEST = SAMPLES_DIR / "School_YuviPep 360_2 1.docx"

pytestmark = pytest.mark.asyncio


def _tagged() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph(
        "Prepared for <School Name>, in a body paragraph long enough to serve "
        "as a style reference."
    )
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


async def _program(client, token, code) -> str:
    resp = await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": "OCR Program", "code": code, "description": "d"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload(client, token, program_id, flow):
    return await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Branded", "make_current": "true", "flow": flow},
        files={"file": ("branded.docx", _tagged(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )


async def _jobs_of_type(job_type: str) -> list[JobRecord]:
    async with SessionLocal() as db:
        return list(
            (
                await db.execute(select(JobRecord).where(JobRecord.type == job_type))
            ).scalars().all()
        )


async def _doc(doc_id: str) -> ProposalTemplateDoc:
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(ProposalTemplateDoc).where(ProposalTemplateDoc.id == doc_id)
            )
        ).scalar_one()


# --- the upload no longer waits ---------------------------------------------


async def test_a_simple_upload_does_not_run_ocr_inline(client, org_a, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("OCR ran during a simple upload")

    monkeypatch.setattr(dts.ocr, "ocr_document", boom)
    token = org_a["admin_token"]
    program_id = await _program(client, token, "OCRA")
    resp = await _upload(client, token, program_id, "simple")
    assert resp.status_code == 200, resp.text
    assert (await _doc(resp.json()["doc_id"])).ocr_json == {}


async def test_a_simple_upload_queues_the_ocr_for_afterwards(client, org_a, monkeypatch):
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    token = org_a["admin_token"]
    program_id = await _program(client, token, "OCRB")
    doc_id = (await _upload(client, token, program_id, "simple")).json()["doc_id"]

    queued = [j for j in await _jobs_of_type("docx_ocr")
              if j.payload.get("doc_id") == doc_id]
    assert len(queued) == 1
    assert queued[0].org_id == (await _doc(doc_id)).org_id


async def test_a_complex_upload_still_ocrs_inline_and_queues_nothing(
    client, org_a, monkeypatch
):
    """The complex flow is unchanged in every respect, including its cost."""
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {"i.png": "seen"})
    token = org_a["admin_token"]
    program_id = await _program(client, token, "OCRC")
    doc_id = (await _upload(client, token, program_id, "complex")).json()["doc_id"]

    assert (await _doc(doc_id)).ocr_json == {"i.png": "seen"}
    assert [j for j in await _jobs_of_type("docx_ocr")
            if j.payload.get("doc_id") == doc_id] == []


# --- the job itself ---------------------------------------------------------


async def test_the_job_fills_in_the_ocr_it_was_queued_for(client, org_a, monkeypatch):
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    token = org_a["admin_token"]
    program_id = await _program(client, token, "OCRD")
    doc_id = (await _upload(client, token, program_id, "simple")).json()["doc_id"]
    assert (await _doc(doc_id)).ocr_json == {}

    monkeypatch.setattr("app.jobs.docx_ocr.ocr.ocr_document",
                        lambda *a, **k: {"cover.png": "YuviPep Innovation Lab"})
    await run_docx_ocr({"doc_id": doc_id}, "job-1")

    assert (await _doc(doc_id)).ocr_json == {"cover.png": "YuviPep Innovation Lab"}


async def test_a_failed_ocr_job_leaves_a_usable_template(client, org_a, monkeypatch):
    """The template is finished before this job runs: its tags are already
    scanned and stored. OCR only enriches what the model later knows, so a
    broken tesseract must cost the enrichment and nothing else.

    The error is allowed to propagate so the queue retries and finally
    dead-letters it, which is how an operator finds out OCR is broken.
    Swallowing it would hide that forever.
    """
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    token = org_a["admin_token"]
    program_id = await _program(client, token, "OCRE")
    doc_id = (await _upload(client, token, program_id, "simple")).json()["doc_id"]

    def boom(*a, **k):
        raise RuntimeError("tesseract is not installed")

    monkeypatch.setattr("app.jobs.docx_ocr.ocr.ocr_document", boom)
    with pytest.raises(RuntimeError):
        await run_docx_ocr({"doc_id": doc_id}, "job-2")

    row = await _doc(doc_id)
    assert row.ocr_json == {}
    assert row.analysis_status == "ready"
    assert len(row.plan_json["tags"]) == 1


async def test_the_job_gives_up_quietly_if_the_document_is_gone():
    """Deleted between enqueue and run. Retrying that forever helps nobody."""
    assert await run_docx_ocr({"doc_id": "no-such-doc"}, "job-3") is None


async def test_the_handler_is_registered_under_its_job_type():
    from app.jobs import register_handlers
    from app.jobs.queue import job_queue

    register_handlers()
    assert job_queue._handlers["docx_ocr"] is run_docx_ocr


# --- the measurement the task exists for ------------------------------------


@pytest.mark.skipif(not BIGGEST.exists(), reason="largest sample not present")
async def test_skipping_ocr_is_what_makes_a_simple_upload_fast():
    """Plan section 2.4 measured 9.84 s with OCR and 0.20 s without, on this
    14.1 MB document. The ratio is the claim; the absolute bound is generous
    because a loaded VM is not a benchmark rig."""
    data = BIGGEST.read_bytes()

    start = time.perf_counter()
    dts.analyse(data, with_ocr=False)
    without = time.perf_counter() - start

    start = time.perf_counter()
    dts.analyse(data)
    with_ocr = time.perf_counter() - start

    assert without < 2.0, f"parse alone took {without:.2f}s"
    assert without * 5 < with_ocr, (
        f"OCR {with_ocr:.2f}s was not the dominant cost against {without:.2f}s"
    )
