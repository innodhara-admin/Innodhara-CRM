# tests/docx/test_render_files.py
import io

import pytest
from docx import Document

from app.services import proposal_email_service as pes


class FakeProposal:
    def __init__(self, kind):
        self.org_id = "org1"
        self.title = "Innovation Lab Proposal"
        self.content_md = "# Heading\n\nBody text for the markdown path."
        self.docx_path = None
        self.pdf_path = None
        self.template_kind = kind


class DB:
    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_a_docx_proposal_converts_its_stored_document(monkeypatch, tmp_path):
    doc = Document(); doc.add_paragraph("Filled document body.")
    buf = io.BytesIO(); doc.save(buf)
    stored = buf.getvalue()

    proposal = FakeProposal("docx")
    proposal.docx_path = "orgs/org1/proposals/x.docx"

    monkeypatch.setattr(pes.storage, "read_bytes", lambda org, path: stored)
    monkeypatch.setattr(pes.storage, "save_bytes",
                        lambda org, cat, name, data: f"orgs/{org}/{cat}/{name}")
    seen = {}

    def fake_convert(data, **kw):
        seen["called"] = True
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(pes.docx_convert, "docx_to_pdf", fake_convert)

    await pes.ensure_rendered_files(DB(), proposal)
    assert seen.get("called") is True
    assert proposal.pdf_path.endswith(".pdf")


@pytest.mark.asyncio
async def test_a_markdown_proposal_still_uses_reportlab(monkeypatch):
    proposal = FakeProposal("markdown")
    calls = []
    monkeypatch.setattr(pes.document_service, "render_docx",
                        lambda md, title: calls.append("docx") or b"DOCX")
    monkeypatch.setattr(pes.document_service, "render_pdf",
                        lambda md, title: calls.append("pdf") or b"%PDF-")
    monkeypatch.setattr(pes.storage, "save_bytes",
                        lambda org, cat, name, data: f"orgs/{org}/{cat}/{name}")

    await pes.ensure_rendered_files(DB(), proposal)
    assert calls == ["docx", "pdf"]


@pytest.mark.asyncio
async def test_a_docx_proposal_never_falls_back_to_the_plain_renderer(monkeypatch):
    """The branded document must not be quietly replaced by a reportlab one on
    the way to a client -- that is the failure this whole path exists to remove.
    """
    doc = Document(); doc.add_paragraph("Filled document body.")
    buf = io.BytesIO(); doc.save(buf)

    proposal = FakeProposal("docx")
    proposal.docx_path = "orgs/org1/proposals/x.docx"

    monkeypatch.setattr(pes.storage, "read_bytes", lambda org, path: buf.getvalue())
    monkeypatch.setattr(pes.storage, "save_bytes",
                        lambda org, cat, name, data: f"orgs/{org}/{cat}/{name}")
    monkeypatch.setattr(pes.docx_convert, "docx_to_pdf", lambda data, **kw: b"%PDF-1.4")

    def must_not_run(*a, **k):
        raise AssertionError("the plain renderer ran for a docx proposal")

    monkeypatch.setattr(pes.document_service, "render_docx", must_not_run)
    monkeypatch.setattr(pes.document_service, "render_pdf", must_not_run)

    await pes.ensure_rendered_files(DB(), proposal)
    # the document it was built with is kept, only the PDF is added
    assert proposal.docx_path == "orgs/org1/proposals/x.docx"
    assert proposal.pdf_path.endswith(".pdf")
