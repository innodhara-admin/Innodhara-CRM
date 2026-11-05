# tests/docx/test_docx_edit_path.py
import io

import pytest
from docx import Document

from app.ai.agents import proposal_agent


class P:
    id = "p1"; org_id = "org1"; template_kind = "docx"; template_id = "t1"
    content_md = "body"; line_items = []; total_amount = 0.0; currency = "INR"
    filled_json = [
        {"key": "greeting", "kind": "insert", "source": "ai",
         "text": "Old greeting.", "brief": "Opening greeting.", "anchor": "body[0]"},
        {"key": "client_name", "kind": "token", "source": "system",
         "text": "Greenwood", "brief": "", "anchor": "School Name ×6"},
    ]


def _ctx():
    class Ctx:
        org_id = "org1"; user_id = "u1"
    return Ctx()


@pytest.mark.asyncio
async def test_an_instruction_names_the_placeholder_to_redo(monkeypatch):
    async def fake_json(**kwargs):
        return {"line_ops": [], "placeholder_keys": ["greeting"],
                "placeholder_instruction": "warmer, mention the June deadline"}

    class Layer:
        generate_json = staticmethod(fake_json)

    monkeypatch.setattr(proposal_agent, "get_model_layer", lambda: Layer())
    keys, instruction, ops = await proposal_agent.parse_docx_edit(
        _ctx(), P(), "make the greeting warmer and mention the June deadline"
    )
    assert keys == ["greeting"]
    assert "June" in instruction
    assert ops == []


@pytest.mark.asyncio
async def test_a_key_that_is_not_in_the_proposal_is_dropped(monkeypatch):
    async def fake_json(**kwargs):
        return {"line_ops": [], "placeholder_keys": ["nonexistent"],
                "placeholder_instruction": "x"}

    class Layer:
        generate_json = staticmethod(fake_json)

    monkeypatch.setattr(proposal_agent, "get_model_layer", lambda: Layer())
    keys, _, _ = await proposal_agent.parse_docx_edit(_ctx(), P(), "change something")
    assert keys == []


@pytest.mark.asyncio
async def test_only_the_named_placeholder_is_sent_back_to_the_model(monkeypatch):
    """The task is per-placeholder re-fill: editing the greeting must not
    quietly rewrite the closing the salesperson was happy with."""
    from app.services import docx_proposal_service as dps

    asked = {}

    async def fake_fill_prose(ctx, *, entries, facts, allowed_amounts):
        asked["keys"] = [e["key"] for e in entries]
        return {e["key"]: {"text": "fresh text", "reasons": [], "attempts": 1}
                for e in entries}

    monkeypatch.setattr(dps.docx_prose, "fill_prose", fake_fill_prose)

    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("A body paragraph long enough to be a style reference here.")
    buf = io.BytesIO(); doc.save(buf)
    data = buf.getvalue()

    from app.services.docx import outline as ol
    out = ol.parse(data)
    heading = next(b for b in out["blocks"] if b["kind"] == "heading")
    body = next(b for b in out["blocks"] if b["kind"] == "paragraph")
    plan = {"version": 1, "entries": [
        {"kind": "insert", "key": "greeting", "after": heading["path"],
         "fingerprint": heading["fingerprint"], "style_ref": body["path"],
         "shape": "paragraph", "brief": "Greeting.", "max_words": 60},
        {"kind": "insert", "key": "closing", "after": body["path"],
         "fingerprint": body["fingerprint"], "style_ref": body["path"],
         "shape": "paragraph", "brief": "Closing.", "max_words": 40},
    ]}

    result = await dps.build_docx_content(
        None, _ctx(), source_bytes=data, plan=plan, variables={},
        line_items=[], total_amount=0.0, currency="INR", facts={},
        prose_overrides={"closing": "The closing the human already accepted."},
    )
    assert asked["keys"] == ["greeting"], "an untouched placeholder was regenerated"

    from app.services.docx import text as dt
    texts = [dt.node_text(p) for p in dt.iter_paragraphs(
        Document(io.BytesIO(result["docx"])).element.body)]
    assert "The closing the human already accepted." in texts
    assert "fresh text" in texts


@pytest.mark.asyncio
async def test_the_rebuilt_document_survives_record_edit(monkeypatch):
    """record_edit clears docx_path and pdf_path because rendered files go
    stale. If the rebuilt document were written before that, it would be wiped
    and ensure_rendered_files would fall back to the plain renderer -- the
    silent downgrade Task 15 exists to prevent."""
    from app.services import proposal_service

    proposal = P()
    proposal.docx_path = "orgs/org1/proposals/old.docx"
    proposal.pdf_path = "orgs/org1/proposals/old.pdf"

    order = []

    async def fake_record_edit(db, ctx, prop, *, instruction):
        order.append("record_edit")
        prop.docx_path = None
        prop.pdf_path = None

    monkeypatch.setattr(proposal_service, "record_edit", fake_record_edit)

    async def fake_parse(ctx, prop, instruction):
        return [], "", []

    monkeypatch.setattr(proposal_agent, "parse_docx_edit", fake_parse)

    result = await proposal_agent._apply_docx_edit(None, _ctx(), proposal, "no-op")
    assert order == ["record_edit"]
    assert result["changes"]
