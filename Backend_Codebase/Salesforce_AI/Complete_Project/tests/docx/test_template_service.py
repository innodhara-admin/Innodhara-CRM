# tests/docx/test_template_service.py
import io

import pytest
from docx import Document

from app.core.exceptions import ValidationFailedError
from app.services import docx_template_service as dts


def _docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("School Name")
    doc.add_paragraph("A body paragraph long enough to serve as a style reference.")
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def test_analyse_returns_outline_index_and_projection(monkeypatch):
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    result = dts.analyse(_docx())
    assert result["index_kind"] == "none"
    assert result["outline"]["blocks"]
    assert "School Name" in result["projection"]
    assert len(result["projection"]) >= 20


def test_analyse_refuses_a_file_that_is_not_a_docx():
    with pytest.raises(ValidationFailedError) as err:
        dts.analyse(b"PK\x03\x04 not really a document")
    assert "Word document" in str(err.value)


def test_analyse_refuses_an_empty_file():
    with pytest.raises(ValidationFailedError):
        dts.analyse(b"")


def test_analyse_refuses_a_document_with_no_text(monkeypatch):
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    doc = Document()
    buf = io.BytesIO(); doc.save(buf)
    with pytest.raises(ValidationFailedError) as err:
        dts.analyse(buf.getvalue())
    assert "no text" in str(err.value).lower()


# --- the summary the console shows after an upload (Task B1) ----------------


def _simple_plan():
    return {
        "flow": "simple",
        "version": 1,
        "tags": [
            {"tag_id": "a", "raw": "<School Name>", "kind": "semantic"},
            {"tag_id": "b", "raw": "<ask:1 Unit>", "kind": "ask"},
            {"tag_id": "c", "raw": "<ask:1 Unit>", "kind": "ask"},
            {"tag_id": "d", "raw": "<ask_calculate:Rs. 5>", "kind": "ask_calculate"},
        ],
    }


def test_the_summary_counts_occurrences_not_literals():
    """`<ask:1 Unit>` twice is two questions, and the console says so."""
    summary = dts.plan_summary(_simple_plan())
    assert summary["flow"] == "simple"
    assert summary["tags"] == 4
    assert summary["distinct"] == [
        "<School Name>", "<ask:1 Unit>", "<ask_calculate:Rs. 5>",
    ]


def test_the_summary_says_how_many_will_always_be_asked():
    """ask and ask_calculate ignore the confidence threshold entirely (D4), so
    an administrator can see the size of the conversation before uploading."""
    assert dts.plan_summary(_simple_plan())["always_asked"] == 3


def test_a_complex_plan_summarises_as_complex():
    """An exact-dict pin, so a new key has to be a decision rather than a
    surprise. U1 added two: `ruled_blanks`, which is zero here because the
    complex flow marks its placeholders in the console rather than in the Word
    file, and `document_type`, which is "proposal" for every template that
    predates the MOU pipeline. Both are reported on BOTH branches so the
    console can read one shape whatever it uploaded."""
    summary = dts.plan_summary({"version": 1, "entries": [{"key": "client_name"}]})
    assert summary == {"flow": "complex", "tags": 0, "always_asked": 0,
                       "distinct": [], "ruled_blanks": 0,
                       "document_type": "proposal"}


def test_a_missing_plan_summarises_as_complex():
    """Every template uploaded before this feature existed has no `flow` key."""
    assert dts.plan_summary(None)["flow"] == "complex"


# --- OCR is not needed to find a tag (Task B2) ------------------------------


def test_analyse_can_skip_ocr_entirely():
    """A tag cannot live inside a raster image, so the simple flow does not
    need OCR to find its placeholders -- only to enrich what the model later
    knows about the document. Measured, OCR is 97-98% of the whole upload."""
    def boom(*a, **k):
        raise AssertionError("OCR must not run when with_ocr is False")

    result = dts.analyse(_docx(), with_ocr=False)
    assert result["ocr"] == {}
    assert result["outline"]["blocks"]
    assert result["index_kind"] == "none"


def test_analyse_still_runs_ocr_by_default(monkeypatch):
    """The complex flow is unchanged: it OCRs at upload, as it always has."""
    called = []
    monkeypatch.setattr(dts.ocr, "ocr_document",
                        lambda *a, **k: called.append(1) or {"img1.png": "text"})
    result = dts.analyse(_docx())
    assert called == [1]
    assert result["ocr"] == {"img1.png": "text"}
