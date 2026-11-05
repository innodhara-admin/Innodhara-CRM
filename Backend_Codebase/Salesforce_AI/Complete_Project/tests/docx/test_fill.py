# tests/docx/test_fill.py
import io

import pytest
from docx import Document

from app.services.docx import fill, outline as ol, text as dt


def _template_docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal for School Name", level=1)   # body[0]
    doc.add_paragraph("A body paragraph of a reasonable length for cloning.")  # body[1]
    doc.add_paragraph("Prepared for School Name by YuviPep.")                  # body[2]
    t = doc.add_table(rows=3, cols=2)                                          # body[3]
    t.style = "Table Grid"
    t.cell(0, 0).text = "Description"; t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Item";        t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total";       t.cell(2, 1).text = "Rs 0"
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def _plan(data):
    out = ol.parse(data)
    by_path = {b["path"]: b for b in out["blocks"]}
    table_path = next(b["path"] for b in out["blocks"] if b["kind"] == "table")
    return out, {
        "version": 1,
        "entries": [
            {"kind": "token", "key": "client_name", "literal": "School Name"},
            {"kind": "insert", "key": "greeting", "after": "body[0]",
             "fingerprint": by_path["body[0]"]["fingerprint"],
             "style_ref": "body[1]", "shape": "paragraph",
             "brief": "Opening greeting.", "max_words": 90, "required": True},
            {"kind": "replace", "key": "why_us", "path": "body[2]",
             "fingerprint": by_path["body[2]"]["fingerprint"],
             "brief": "Why us.", "max_words": 120, "required": False},
            {"kind": "table", "key": "pricing_table", "path": table_path,
             "fingerprint": by_path[table_path]["fingerprint"],
             "columns": [{"col": 0, "field": "label"},
                         {"col": 1, "field": "line_total"}],
             "header_rows": 1,
             "total_row": {"label_col": 0, "value_col": 1}},
        ],
    }


VALUES = {
    "client_name": "Greenwood International School",
    "greeting": "We are delighted to present this proposal.",
    "why_us": "YuviPep has worked with two hundred schools.",
    "pricing_table": {
        "rows": [{"label": "Innovation Lab", "line_total": "Rs 8,50,000"},
                 {"label": "Annual Support", "line_total": "Rs 1,20,000"}],
        "total": "Rs 9,70,000",
    },
}


def test_applies_every_entry_kind():
    data = _template_docx()
    _, plan = _plan(data)
    result = fill.apply(data, plan, VALUES)
    doc = Document(io.BytesIO(result["docx"]))

    assert dt.count_token(doc, "School Name") == 0

    texts = [dt.node_text(p) for p in dt.iter_paragraphs(doc.element.body)]
    assert "We are delighted to present this proposal." in texts
    assert "YuviPep has worked with two hundred schools." in texts

    # The template says 'School Name' twice: in the heading and in body[2].
    # This plan's `replace` entry overwrites body[2] wholesale, so that
    # occurrence is gone before token replacement runs and only the heading
    # is rewritten. `test_an_unfilled_optional_replace_leaves_the_original_
    # wording` covers the other side: leave why_us unfilled and both survive.
    assert dt.count_token(doc, "Greenwood International School") == 1
    assert "Proposal for Greenwood International School" in texts

    table = doc.tables[0]
    assert len(table.rows) == 4
    assert table.cell(0, 0).text == "Description"
    assert table.cell(2, 0).text == "Annual Support"
    assert table.cell(3, 1).text == "Rs 9,70,000"


def test_reports_what_it_filled_and_from_where():
    data = _template_docx()
    _, plan = _plan(data)
    result = fill.apply(data, plan, VALUES)
    by_key = {f["key"]: f for f in result["filled"]}
    assert by_key["client_name"]["source"] == "system"
    assert by_key["pricing_table"]["source"] == "system"
    assert by_key["greeting"]["source"] == "ai"
    assert by_key["greeting"]["text"] == "We are delighted to present this proposal."


def test_a_missing_value_leaves_the_placeholder_unfilled():
    data = _template_docx()
    _, plan = _plan(data)
    values = dict(VALUES); values.pop("greeting")
    result = fill.apply(data, plan, values)
    assert "greeting" in result["unfilled"]
    by_key = {f["key"]: f for f in result["filled"]}
    assert by_key["greeting"]["source"] == "unfilled"


def test_an_unfilled_optional_replace_leaves_the_original_wording():
    data = _template_docx()
    _, plan = _plan(data)
    values = dict(VALUES); values.pop("why_us")
    result = fill.apply(data, plan, values)
    doc = Document(io.BytesIO(result["docx"]))
    texts = [dt.node_text(p) for p in dt.iter_paragraphs(doc.element.body)]
    assert any("Prepared for Greenwood" in t for t in texts)
    # The paragraph survives, so its token is rewritten too — two occurrences
    # here against the one in test_applies_every_entry_kind, which replaces it.
    assert dt.count_token(doc, "Greenwood International School") == 2


def test_multi_paragraph_shape_creates_one_paragraph_per_line():
    data = _template_docx()
    _, plan = _plan(data)
    plan["entries"][1]["shape"] = "paragraphs"
    values = dict(VALUES); values["greeting"] = "First para.\n\nSecond para."
    result = fill.apply(data, plan, values)
    doc = Document(io.BytesIO(result["docx"]))
    texts = [dt.node_text(p) for p in dt.iter_paragraphs(doc.element.body)]
    assert "First para." in texts and "Second para." in texts


def test_a_stale_anchor_is_refused_rather_than_written_to_the_wrong_place():
    data = _template_docx()
    _, plan = _plan(data)
    plan["entries"][1]["fingerprint"] = "sha256:0000000000000000"
    with pytest.raises(ol.AnchorError):
        fill.apply(data, plan, VALUES)


def test_the_source_document_is_not_modified():
    data = _template_docx()
    _, plan = _plan(data)
    fill.apply(data, plan, VALUES)
    assert dt.count_token(Document(io.BytesIO(data)), "School Name") == 2


def test_validate_plan_flags_an_unknown_entry_kind():
    data = _template_docx()
    out, plan = _plan(data)
    plan["entries"].append({"kind": "nonsense", "key": "x"})
    problems = fill.validate_plan(plan, out)
    assert any("nonsense" in p for p in problems)


def test_validate_plan_flags_a_duplicate_key():
    data = _template_docx()
    out, plan = _plan(data)
    plan["entries"].append({"kind": "token", "key": "client_name", "literal": "X"})
    assert any("client_name" in p for p in fill.validate_plan(plan, out))


def test_validate_plan_accepts_a_coherent_plan():
    data = _template_docx()
    out, plan = _plan(data)
    assert fill.validate_plan(plan, out) == []
