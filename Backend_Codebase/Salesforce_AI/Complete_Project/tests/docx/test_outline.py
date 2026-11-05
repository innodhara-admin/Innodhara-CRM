# tests/docx/test_outline.py
import io

import pytest
from docx import Document

from app.services.docx import outline as ol


def test_paths_address_top_level_body_children(table_docx):
    out = ol.parse(table_docx)
    paths = [b["path"] for b in out["blocks"]]
    assert paths[0].startswith("body[")
    assert any(b["kind"] == "table" for b in out["blocks"])


def test_table_block_reports_its_shape(table_docx):
    out = ol.parse(table_docx)
    table = next(b for b in out["blocks"] if b["kind"] == "table")
    assert table["table"]["rows"] == 3
    assert table["table"]["cols"] == 2
    assert table["table"]["header"] == ["Description", "Estimation"]


def test_headings_are_classified_with_a_level():
    doc = Document()
    doc.add_heading("Pricing Overview", level=1)
    doc.add_paragraph("Body text here.")
    buf = io.BytesIO(); doc.save(buf)
    out = ol.parse(buf.getvalue())
    heading = next(b for b in out["blocks"] if b["kind"] == "heading")
    assert heading["level"] == 1
    assert heading["text"] == "Pricing Overview"
    assert out["headings"][0]["text"] == "Pricing Overview"


def test_resolve_round_trips_every_path(table_docx):
    out = ol.parse(table_docx)
    doc = Document(io.BytesIO(table_docx))
    for block in out["blocks"]:
        assert ol.resolve(doc, block["path"]) is not None


def test_verify_accepts_a_matching_fingerprint(table_docx):
    out = ol.parse(table_docx)
    doc = Document(io.BytesIO(table_docx))
    block = out["blocks"][0]
    assert ol.verify(doc, block["path"], block["fingerprint"]) is not None


def test_verify_rejects_a_changed_block(table_docx):
    out = ol.parse(table_docx)
    doc = Document(io.BytesIO(table_docx))
    block = out["blocks"][0]
    with pytest.raises(ol.AnchorError) as err:
        ol.verify(doc, block["path"], "sha256:deadbeef")
    assert "no longer matches" in str(err.value)


def test_verify_rejects_a_path_that_does_not_exist(table_docx):
    doc = Document(io.BytesIO(table_docx))
    with pytest.raises(ol.AnchorError):
        ol.verify(doc, "body[9999]", "sha256:whatever")


def test_candidate_tokens_finds_repeated_title_case_literals():
    doc = Document()
    for _ in range(3):
        doc.add_paragraph("Prepared for School Name by YuviPep.")
    buf = io.BytesIO(); doc.save(buf)
    out = ol.parse(buf.getvalue())
    literals = {t["literal"]: t["occurrences"] for t in out["tokens"]}
    assert literals.get("School Name") == 3


def test_text_projection_reads_as_a_document(table_docx):
    out = ol.parse(table_docx)
    projected = ol.project_text(out)
    assert "Description" in projected
    assert "Innovation Lab" in projected
    assert len(projected) >= 20      # ProposalTemplateRequest.body_md min_length


def test_header_and_footer_blocks_are_addressable(header_docx):
    out = ol.parse(header_docx)
    paths = [b["path"] for b in out["blocks"]]
    assert any(p.startswith("sec[0]/hdr") for p in paths)
    assert any(p.startswith("sec[0]/ftr") for p in paths)
