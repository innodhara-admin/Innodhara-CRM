# tests/docx/test_build_docx_proposal.py
import io

import pytest
from docx import Document

from app.services import docx_proposal_service as dps
from app.services.docx import text as dt


class Template:
    kind = "docx"
    id = "tpl1"
    name = "Standard"
    version = 1


def _source() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("School Name")
    doc.add_paragraph("A body paragraph long enough to be a style reference here.")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "Description"; t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Item"; t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total"; t.cell(2, 1).text = "Rs 0"
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def _ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()


def _system_plan(data):
    from app.services.docx import outline as ol

    outline = ol.parse(data)
    table_path = next(b["path"] for b in outline["blocks"] if b["kind"] == "table")
    by_path = {b["path"]: b for b in outline["blocks"]}
    return {"version": 1, "entries": [
        {"kind": "token", "key": "client_name", "literal": "School Name"},
        {"kind": "table", "key": "pricing_table", "path": table_path,
         "fingerprint": by_path[table_path]["fingerprint"],
         "columns": [{"col": 0, "field": "label"}, {"col": 1, "field": "line_total"}],
         "header_rows": 1, "total_row": {"label_col": 0, "value_col": 1}},
    ]}


LINE_ITEMS = [{"label": "Innovation Lab", "unit": "per lab", "unit_price": 850000.0,
               "quantity": 1.0, "line_total": 850000.0}]


@pytest.mark.asyncio
async def test_system_values_fill_without_calling_the_model(monkeypatch):
    data = _source()
    plan = _system_plan(data)
    called = []

    async def never(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(dps.docx_prose, "fill_prose", never)

    result = await dps.build_docx_content(
        None, _ctx(), source_bytes=data, plan=plan,
        variables={"client_name": "Greenwood International School"},
        line_items=LINE_ITEMS,
        total_amount=850000.0, currency="INR", facts={},
    )
    assert called == []
    doc = Document(io.BytesIO(result["docx"]))
    assert dt.count_token(doc, "School Name") == 0
    assert doc.tables[0].cell(1, 0).text == "Innovation Lab"
    assert "Innovation Lab" in result["content_md"]
    assert result["unfilled"] == []


@pytest.mark.asyncio
async def test_prices_are_formatted_and_line_items_are_never_mutated(monkeypatch):
    """R4: line_items is persisted to a JSON column and returned to the Android
    app, so nothing here may stash a private key on it."""
    data = _source()
    plan = _system_plan(data)
    monkeypatch.setattr(dps.docx_prose, "fill_prose", lambda *a, **k: {})

    before = [dict(item) for item in LINE_ITEMS]
    result = await dps.build_docx_content(
        None, _ctx(), source_bytes=data, plan=plan,
        variables={"client_name": "Greenwood International School"},
        line_items=LINE_ITEMS, total_amount=850000.0, currency="INR", facts={},
    )
    assert LINE_ITEMS == before, "line_items was mutated"
    # Assert against the project's own formatter rather than a literal, so this
    # keeps holding if the currency symbol or grouping ever changes.
    from app.services.proposal_service import _money

    doc = Document(io.BytesIO(result["docx"]))
    assert doc.tables[0].cell(1, 1).text == _money(850000.0, "INR")
    assert doc.tables[0].cell(2, 1).text == _money(850000.0, "INR")   # total row


@pytest.mark.asyncio
async def test_prose_comes_from_the_model_and_unfilled_is_reported(monkeypatch):
    from app.services.docx import outline as ol

    data = _source()
    outline = ol.parse(data)
    by_path = {b["path"]: b for b in outline["blocks"]}
    heading = next(b for b in outline["blocks"] if b["kind"] == "heading")
    body_ref = next(b for b in outline["blocks"]
                    if b["kind"] == "paragraph" and len(b["text"]) > 40)
    plan = {"version": 1, "entries": [
        {"kind": "insert", "key": "greeting", "after": heading["path"],
         "fingerprint": heading["fingerprint"], "style_ref": body_ref["path"],
         "shape": "paragraph", "brief": "Opening greeting.", "max_words": 90,
         "required": True},
        {"kind": "insert", "key": "closing", "after": body_ref["path"],
         "fingerprint": by_path[body_ref["path"]]["fingerprint"],
         "style_ref": body_ref["path"], "shape": "paragraph",
         "brief": "Closing line.", "max_words": 40, "required": False},
    ]}

    seen = {}

    async def fake_fill_prose(ctx, *, entries, facts, allowed_amounts):
        seen["keys"] = [e["key"] for e in entries]
        seen["allowed"] = allowed_amounts
        return {
            "greeting": {"text": "We are delighted to write to you.",
                         "reasons": [], "attempts": 1},
            "closing": {"text": None, "reasons": ["meta_instruction"], "attempts": 2},
        }

    monkeypatch.setattr(dps.docx_prose, "fill_prose", fake_fill_prose)

    result = await dps.build_docx_content(
        None, _ctx(), source_bytes=data, plan=plan, variables={},
        line_items=LINE_ITEMS, total_amount=850000.0, currency="INR",
        facts={"client_name": "Greenwood International School"},
    )
    assert sorted(seen["keys"]) == ["closing", "greeting"]
    # the locked commercials reach the scrubber, so the model cannot restate a
    # price that is not one of them
    assert 850000.0 in seen["allowed"]
    texts = [dt.node_text(p) for p in dt.iter_paragraphs(
        Document(io.BytesIO(result["docx"])).element.body)]
    assert "We are delighted to write to you." in texts
    assert "closing" in result["unfilled"]
