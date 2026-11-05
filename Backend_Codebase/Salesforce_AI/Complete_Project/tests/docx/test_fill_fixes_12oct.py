# tests/docx/test_fill_fixes_12oct.py
"""Three defects a live Jarvis conversation found on 12 Oct 2026.

1. The owner's proposal templates show the school's name on the cover and in
   every footer through content controls bound to dc:title, which is the
   literal "<School name>". The page was filled; the property was not, so the
   PDF said "<School name>" on all 23 pages.
2. "Yes, these are all correct" on the review went to create_proposal, which
   re-raised the same review: a loop for as long as the person kept tapping.
3. A correction on the review went to correct_proposal, which said "there is
   no proposal ... ask me to create one".
"""
import io

import pytest
from docx import Document
from sqlalchemy import select

from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services import storage
from app.services.docx import properties as props
from tests.conftest import auth, open_lead
from tests.docx.test_fill_agent import _tool_result
from tests.docx.test_fill_build import (  # noqa: F401 -- fixtures by name
    FillLayer,
    _answered_fill,
    _asked,
    _command,
    _ctx,
    _plan_tags,
    agent_model,
    fill_model,
    no_pdf,
)

API = "/api/v1"
pytestmark = pytest.mark.asyncio


# --- 1. the properties ---------------------------------------------------------

def _titled_docx(title: str, body_tag: str = "<School Name>") -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph(f"Prepared for {body_tag}, a body paragraph long enough "
                      "to serve as a style reference.")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Description"
    t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Interactive Panel"
    t.cell(1, 1).text = "<ask:1 Unit>"
    doc.core_properties.title = title
    doc.core_properties.subject = "Innovation Lab"
    doc.core_properties.author = "Template Author"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _core(docx_bytes: bytes) -> dict[str, str]:
    return {name: text for part, name, text in props.read(docx_bytes)
            if part == props.CORE}


def test_fill_literals_replaces_a_tag_title():
    out = props.fill_literals(_titled_docx("<School name>"),
                              {"<School name>": "Test School Sunrise"})
    assert _core(out)["title"] == "Test School Sunrise"
    assert props.tag_like(out) == []


def test_fill_literals_matches_a_literal_whatever_its_case():
    out = props.fill_literals(_titled_docx("<School Name>"),
                              {"<School name>": "Test School Sunrise"})
    assert _core(out)["title"] == "Test School Sunrise"


def test_fill_literals_blanks_a_tag_it_has_no_value_for():
    out = props.fill_literals(_titled_docx("<School Name>"), {})
    assert props.tag_like(out) == []
    assert "title" not in _core(out)


def test_fill_literals_leaves_real_properties_alone():
    """Unlike the MOU's `fill`: no title is set and no author is cleared."""
    source = _titled_docx("Innovation Lab Proposal")
    out = props.fill_literals(source, {"<School Name>": "Test School Sunrise"})
    assert _core(out) == _core(source)
    assert _core(out)["creator"] == "Template Author"


async def test_a_built_proposal_carries_no_tag_in_its_properties(
        client, org_a, no_pdf):
    token = org_a["admin_token"]
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": "Fill P12OCT", "code": "P12OCT", "description": "d"},
    )).json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Titled", "make_current": "true", "flow": "simple"},
        files={"file": ("t.docx", _titled_docx("<School Name>"),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": "Orchid Twelve Oct"})).json()["id"]
    ctx = await _ctx(client, token)
    tags = await _plan_tags(program["id"])
    school = [t for t in tags if t["raw"] == "<School Name>"][0]

    import app.ai.docx_tagfill as tf_mod
    layer = FillLayer({"resolutions": []})
    original = tf_mod.get_model_layer
    tf_mod.get_model_layer = lambda: layer
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(db, ctx, lead_id=lead_id,
                                            program_id=program["id"],
                                            chat_session_id="chat-P12OCT")
        layer.replies = [{"resolutions": [
            {"tag_id": t["tag_id"],
             "value": "Orchid Twelve Oct" if t["tag_id"] == school["tag_id"]
             else "2 Units",
             "reason": "answered"} for t in tags]}]
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.apply_answers(db, ctx, session, "two of each")
    finally:
        tf_mod.get_model_layer = original
    assert session.status == FillStatus.REVIEWING

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)
        built = storage.read_bytes(ctx.org_id, proposal.docx_path)
    assert props.tag_like(built) == []
    assert _core(built)["title"] == "Orchid Twelve Oct"
    # Only tag text changed: the template's other properties are its own.
    assert _core(built)["subject"] == "Innovation Lab"


# --- 2. "Yes" at the review, sent to create_proposal --------------------------

async def test_a_yes_at_the_review_sent_to_create_names_the_confirm_tool(
        client, org_a, agent_model, no_pdf):
    token = org_a["admin_token"]
    _, session, program_id, lead_id, _ = await _answered_fill(
        client, token, "L12YES", "Orchid L12 Yes")
    await open_lead(client, token, lead_id)

    layer = agent_model([
        # Exactly the live mistake: the approval goes to create_proposal...
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid L12 Yes", "program": "L12YES"})]),
        # ...and, told what is open, the model calls the gate in the same turn.
        LlmResponse(tool_calls=[ToolCall(
            name="confirm_proposal_values", args={"approved": True})]),
        LlmResponse(text="Done -- the proposal is ready."),
    ])
    body = (await _command(client, token, "Yes, these are all correct",
                           session_id="chat-L12YES")).json()

    result = _tool_result(layer, "create_proposal")
    assert result["already_open"] is True and result["at_review"] is True
    assert "confirm_proposal_values" in result["what_to_do"]
    assert "Interactive Panel" in result["review"]
    created = [a for a in body["actions"] if a["tool"] == "create_proposal"]
    assert created[0]["ok"] is True, "the review must not be re-raised as a question"
    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
    assert len(proposals) == 1


async def test_create_with_questions_still_open_is_unchanged(
        client, org_a, agent_model, fill_model):
    """The branch that already worked keeps its own loop-breaker."""
    token = org_a["admin_token"]
    from tests.docx.test_fill_build import _ground
    program_id, lead_id = await _ground(client, token, "L12ASK", "Orchid L12 Ask")
    await open_lead(client, token, lead_id)
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid L12 Ask", "program": "L12ASK"})]),
        LlmResponse(text="A few details first."),
    ])
    first = (await _command(client, token, "create the proposal",
                            session_id="chat-L12ASK")).json()
    assert _asked(first) is not None
    fill_model({"resolutions": []})
    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid L12 Ask", "program": "L12ASK"})]),
        LlmResponse(text="Right."),
    ])
    await _command(client, token, "hmm", session_id="chat-L12ASK")
    result = _tool_result(layer, "create_proposal")
    assert result["already_open"] is True
    assert "at_review" not in result
    assert "answer_proposal_questions" in result["what_to_do"]


# --- 3. a correction at the review, sent to correct_proposal -------------------

async def test_a_correction_at_the_review_is_applied_not_refused(
        client, org_a, agent_model, fill_model, no_pdf):
    token = org_a["admin_token"]
    _, session, _, lead_id, tags = await _answered_fill(
        client, token, "L12FIX", "Orchid L12 Fix")
    await open_lead(client, token, lead_id)
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "9 Units", "reason": "the panel"},
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="correct_proposal",
            args={"correction": "make the panel nine"})]),
        LlmResponse(text="Updated -- here is the list again."),
    ])
    body = (await _command(client, token, "panel should be 9",
                           session_id="chat-L12FIX")).json()

    fixed = [a for a in body["actions"] if a["tool"] == "correct_proposal"]
    assert "Ask me to create one" not in (fixed[0].get("error") or "")
    assert _asked(body) is not None               # the review, again
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
    assert proposals == []                        # nothing built
    assert session.status == FillStatus.REVIEWING
    assert {t["tag_id"]: t["value"] for t in session.tags_json}[
        panel["tag_id"]] == "9 Units"


async def test_a_correction_that_repeats_its_row_label_keeps_only_the_value(
        client, org_a, agent_model, fill_model, no_pdf):
    token = org_a["admin_token"]
    _, session, _, lead_id, tags = await _answered_fill(
        client, token, "L12LBL", "Orchid L12 Label")
    await open_lead(client, token, lead_id)
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]
    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "Interactive Panel: 9 Units",
         "reason": "the panel"},
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="confirm_proposal_values",
            args={"approved": False, "correction": "panel should be 9 units"})]),
        LlmResponse(text="Updated."),
    ])
    await _command(client, token, "panel should be 9 units",
                   session_id="chat-L12LBL")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
    assert {t["tag_id"]: t["value"] for t in session.tags_json}[
        panel["tag_id"]] == "9 Units"


async def test_correcting_a_built_proposal_also_drops_the_row_label(
        client, org_a, no_pdf, fill_model):
    """The second door to the same model step (found live after deploy)."""
    ctx, session, _, _, tags = await _answered_fill(
        client, org_a["admin_token"], "L12BLT", "Orchid L12 Built")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        await fs.build(db, ctx, session)
    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "Interactive Panel: 7 Units",
         "reason": "the panel"},
    ]})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.reopen_for_correction(db, ctx, session,
                                                 "panel should be 7 units")
    assert {t["tag_id"]: t["value"] for t in session.tags_json}[
        panel["tag_id"]] == "7 Units"


def test_a_value_that_only_starts_like_its_label_is_kept():
    tags = [{"tag_id": "a", "context": "Grades"}]
    kept = fs._without_row_label(tags, [{"tag_id": "a", "value": "Grades 6 to 10"}])
    assert kept[0]["value"] == "Grades 6 to 10"
    cut = fs._without_row_label(tags, [{"tag_id": "a", "value": "grades: 6 to 10"}])
    assert cut[0]["value"] == "6 to 10"
    empty = fs._without_row_label(tags, [{"tag_id": "a", "value": "Grades:"}])
    assert empty[0]["value"] == "Grades:"


async def test_looking_up_a_proposal_at_the_review_names_the_confirm_tool(
        client, org_a, agent_model, no_pdf):
    """The replay's variant: the correction went to get_proposal instead."""
    token = org_a["admin_token"]
    _, session, _, lead_id, _ = await _answered_fill(
        client, token, "L12GET", "Orchid L12 Get")
    await open_lead(client, token, lead_id)
    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="get_proposal", args={})]),
        LlmResponse(text="Which proposal?"),
    ])
    body = (await _command(client, token, "price line looks bad",
                           session_id="chat-L12GET")).json()
    got = [a for a in body["actions"] if a["tool"] == "get_proposal"]
    assert got[0]["ok"] is False
    assert "confirm_proposal_values" in got[0]["error"]
    assert "Create one first" not in got[0]["error"]


async def test_correct_with_nothing_open_still_says_so(
        client, org_a, agent_model):
    token = org_a["admin_token"]
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="correct_proposal", args={"correction": "make it nine"})]),
        LlmResponse(text="Nothing to correct."),
    ])
    body = (await _command(client, token, "make it nine",
                           session_id="chat-L12NONE")).json()
    fixed = [a for a in body["actions"] if a["tool"] == "correct_proposal"]
    assert fixed[0]["ok"] is False
    assert "Ask me to create one" in fixed[0]["error"]
