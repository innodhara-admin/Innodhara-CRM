# tests/docx/test_golden_samples.py
"""Opt-in tests against the organisation's four real proposal documents.

They live in `data/samples/` and are not in git — 27 MB of branded material.
When the directory is absent every test here skips, so a clean checkout stays
green; on the VM they run and are the real proof.
"""
import io
from pathlib import Path

import pytest
from docx import Document

from app.services.docx import convert, fill
from app.services.docx import index as ix
from app.services.docx import outline as ol
from app.services.docx import text as dt
from tests.docx.test_text import raw_count as raw_count_bytes

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"

# filename -> the client-name literal that document uses
SAMPLES = {
    "Essential Lab.docx": "School Name",
    "Innovation Lab Template.docx": "School Name",
    "School_YuviPep 360_2 1.docx": "School School",
    "School_YuviPep 360 EmpowerED_New_compressed.docx": "School Name",
}

# measured 2026-09-03 against the raw XML
EXPECTED_OCCURRENCES = {
    "Essential Lab.docx": 7,
    "Innovation Lab Template.docx": 7,
    "School_YuviPep 360_2 1.docx": 9,
    "School_YuviPep 360 EmpowerED_New_compressed.docx": 14,
}

pytestmark = pytest.mark.skipif(
    not SAMPLES_DIR.is_dir(), reason="data/samples/ not present"
)


def raw_count(path: Path, literal: str) -> int:
    """Path-taking variant of the shared ground-truth tokenizer.

    Reuses the stack-based `raw_count` (bytes-based) from
    `tests.docx.test_text` rather than re-implementing paragraph-boundary
    scanning here. See the Task 3 controller ruling: a second copy of that
    tokenizer logic in this file is exactly the defect (a naive single-pass
    `<w:p[ >].*?</w:p>` regex undercounting nested text-box paragraphs) the
    ruling exists to prevent.
    """
    return raw_count_bytes(Path(path).read_bytes(), literal)


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_walker_agrees_with_raw_xml(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    doc = Document(str(path))
    assert dt.count_token(doc, literal) == raw_count(path, literal)


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_occurrence_counts_have_not_drifted(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    doc = Document(str(path))
    assert dt.count_token(doc, literal) == EXPECTED_OCCURRENCES[name]


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_replacement_leaves_nothing_behind(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    doc = Document(str(path))
    media_before = len(doc.part.package.image_parts)
    sections_before = len(doc.sections)

    replaced = dt.replace_token(doc, literal, "Greenwood International School")
    assert replaced == EXPECTED_OCCURRENCES[name]

    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()

    reopened = Document(io.BytesIO(data))
    assert dt.count_token(reopened, literal) == 0
    assert raw_count_bytes(data, literal) == 0
    assert len(reopened.part.package.image_parts) == media_before
    assert len(reopened.sections) == sections_before


# measured 2026-09-03
EXPECTED_SHAPE = {
    "Essential Lab.docx": {"sections": 5, "media": 14, "tables": 3},
    "Innovation Lab Template.docx": {"sections": 6, "media": 14, "tables": 2},
    "School_YuviPep 360_2 1.docx": {"sections": 23, "media": 33, "tables": 18},
    "School_YuviPep 360 EmpowerED_New_compressed.docx":
        {"sections": 20, "media": 32, "tables": 14},
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_outline_parses_every_real_document(name):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    out = ol.parse(path.read_bytes())
    shape = EXPECTED_SHAPE[name]
    assert len(out["media"]) == shape["media"]
    assert sum(1 for b in out["blocks"] if b["kind"] == "table") == shape["tables"]
    assert out["headings"], "no headings found"
    assert len(ol.project_text(out)) > 500


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_every_outline_path_resolves_and_verifies(name):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    data = path.read_bytes()
    out = ol.parse(data)
    doc = Document(io.BytesIO(data))
    for block in out["blocks"]:
        ol.verify(doc, block["path"], block["fingerprint"])


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_the_client_literal_is_offered_as_a_token(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    out = ol.parse(path.read_bytes())
    assert literal in {t["literal"] for t in out["tokens"]}, (
        f"{literal!r} was not surfaced as a bindable token for {name}"
    )


EXPECTED_INDEX = {
    "Essential Lab.docx": "none",
    "Innovation Lab Template.docx": "none",
    "School_YuviPep 360_2 1.docx": "static",
    "School_YuviPep 360 EmpowerED_New_compressed.docx": "none",
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_index_kind_matches_what_was_measured(name):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    assert ix.detect(Document(str(path))) == EXPECTED_INDEX[name]


def test_the_static_index_yields_its_thirty_two_entries():
    path = SAMPLES_DIR / "School_YuviPep 360_2 1.docx"
    if not path.exists():
        pytest.skip("sample not present")
    entries = ix.static_entries(Document(str(path)))
    assert len(entries) == 32
    assert entries[0]["label"].startswith("ABOUT YUVIPEP")
    assert entries[0]["anchor"] == "_bookmark0"
    assert all(e["page_text"].strip().isdigit() for e in entries)


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_a_real_document_fills_and_converts(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    data = path.read_bytes()
    out = ol.parse(data)

    heading = next((b for b in out["blocks"] if b["kind"] == "heading"), None)
    body_ref = next(
        (b for b in out["blocks"] if b["kind"] == "paragraph" and len(b["text"]) > 60),
        None,
    )
    if heading is None or body_ref is None:
        pytest.skip(f"{name} has no heading/body pair to anchor against")

    plan = {"version": 1, "entries": [
        {"kind": "token", "key": "client_name", "literal": literal},
        {"kind": "insert", "key": "greeting", "after": heading["path"],
         "fingerprint": heading["fingerprint"], "style_ref": body_ref["path"],
         "shape": "paragraph", "brief": "Opening greeting.",
         "max_words": 90, "required": True},
    ]}
    values = {"client_name": "Greenwood International School",
              "greeting": "We are delighted to present this proposal."}

    result = fill.apply(data, plan, values)
    assert result["unfilled"] == []

    filled_doc = Document(io.BytesIO(result["docx"]))
    assert dt.count_token(filled_doc, literal) == 0
    assert raw_count_bytes(result["docx"], literal) == 0
    assert len(filled_doc.part.package.image_parts) == EXPECTED_SHAPE[name]["media"]
    assert len(filled_doc.sections) == EXPECTED_SHAPE[name]["sections"]

    pdf = convert.docx_to_pdf(result["docx"])
    assert pdf[:5] == b"%PDF-"
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Greenwood International School" in text
    assert literal not in text
