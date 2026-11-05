# tests/docx/test_fill_build.py
"""The review, and the document that follows it (Task J2).

D13 is the whole subject. The 0.80 confidence threshold is self-reported and
uncalibrated, so it decides whether the assistant ASKS; this decides whether
the document is WRITTEN. A fill cannot reach `ready` except through
`reviewing`, and the tests below assert that as a transition rather than as an
outcome -- an outcome can be reached by a caller that skipped the gate.
"""
import io
from datetime import timedelta

import pytest
from docx import Document
from sqlalchemy import select

from app.ai import docx_tagfill
from app.ai import llm as llm_mod
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.core.exceptions import ValidationFailedError
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.program import ProposalTemplate, ProposalTemplateDoc
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services import storage
from app.services.docx import tags as docx_tags
from tests.conftest import auth, open_lead

API = "/api/v1"
pytestmark = pytest.mark.asyncio


def _tagged_docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "Description"
    t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Interactive Panel"
    t.cell(1, 1).text = "<ask:1 Unit>"
    t.cell(2, 0).text = "Magazine Rack"
    t.cell(2, 1).text = "<ask:1 Unit>"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class FakeModelLayer:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return LlmResponse(text="Done.")
        return self.script.pop(0)

    async def generate_json(self, **kwargs):
        response = await self.generate(**kwargs)
        return llm_mod.extract_json(response.text)


class FillLayer:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0) if self.replies else {"resolutions": []}

    @property
    def prompt(self) -> str:
        return self.calls[-1]["messages"][-1]["content"]


@pytest.fixture
def agent_model(monkeypatch):
    def _install(script):
        fake = FakeModelLayer(script)
        monkeypatch.setattr(agent_base, "get_model_layer", lambda: fake)
        monkeypatch.setattr("app.ai.orchestrator.get_model_layer", lambda: fake,
                            raising=True)
        return fake
    return _install


@pytest.fixture
def fill_model(monkeypatch):
    def _install(*replies):
        layer = FillLayer(*replies)
        monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: layer)
        return layer
    return _install


@pytest.fixture
def no_pdf(monkeypatch):
    """LibreOffice takes seconds a call. One test does it for real."""
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-stub")


async def _ground(client, token, code, lead_name):
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"Fill {code}", "code": code, "description": "d"},
    )).json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Tagged", "make_current": "true", "flow": "simple"},
        files={"file": ("t.docx", _tagged_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    assert (await client.post(
        f"{API}/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "make_current": True,
              "items": [{"code": "LAB", "label": "Innovation Lab",
                         "unit": "lab", "unit_price": 250000,
                         "default_quantity": 2}]},
    )).status_code == 200
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": lead_name})).json()["id"]
    return program["id"], lead_id


async def _ctx(client, token):
    from app.core.context import OrgContext
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                      role=me["role"], email=me["email"])


async def _plan_tags(program_id):
    async with SessionLocal() as db:
        template = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.program_id == program_id,
            ProposalTemplate.is_current.is_(True)))).scalars().first()
        row = (await db.execute(select(ProposalTemplateDoc).where(
            ProposalTemplateDoc.template_id == template.id))).scalar_one()
    return (row.plan_json or {}).get("tags") or []


async def _answered_fill(client, token, code, name, *, values=None):
    """A fill with every question settled: sitting in `reviewing`."""
    program_id, lead_id = await _ground(client, token, code, name)
    ctx = await _ctx(client, token)
    tags = await _plan_tags(program_id)

    layer = FillLayer({"resolutions": []})
    import app.ai.docx_tagfill as tf_mod
    original = tf_mod.get_model_layer
    tf_mod.get_model_layer = lambda: layer
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(db, ctx, lead_id=lead_id,
                                            program_id=program_id,
                                            chat_session_id=f"chat-{code}")
        layer.replies = [{"resolutions": [
            {"tag_id": t["tag_id"],
             "value": (values or {}).get(t["tag_id"], "2 Units"),
             "reason": "answered"}
            for t in tags
        ]}]
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.apply_answers(db, ctx, session, "two of each")
    finally:
        tf_mod.get_model_layer = original
    assert session.status == FillStatus.REVIEWING
    return ctx, session, program_id, lead_id, tags


async def _command(client, token, text, *, session_id):
    return await client.post(
        f"{API}/assistant/command", headers=auth(token),
        json={"text": text, "agent": "proposal", "session_id": session_id})


def _asked(body):
    for action in body["actions"]:
        if action.get("outcome") == "needs_confirmation":
            return action
    return None


# --- the gate ----------------------------------------------------------------


async def test_the_review_lists_every_value_and_where_it_came_from(
        client, org_a):
    """Including the ones filled without asking -- they are why this exists."""
    _, session, _, _, tags = await _answered_fill(
        client, org_a["admin_token"], "J2REV", "Orchid J2A")

    lines = fs.review_lines(session)
    assert len(lines) == len(tags) == 3
    assert all(line["value"] for line in lines)
    assert all(line["source"] == "user" for line in lines)
    assert {line["about"] for line in lines} >= {"Interactive Panel",
                                                 "Magazine Rack"}
    assert all(line["reviewed"] is False for line in lines)


async def test_a_fill_cannot_be_built_without_passing_through_reviewing(
        client, org_a, no_pdf):
    """The transition, not the outcome. `build` refuses anything but `ready`,
    and `ready` has exactly one door."""
    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2GATE", "Orchid J2B")

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        assert session.status == FillStatus.REVIEWING
        with pytest.raises(ValidationFailedError):
            await fs.build(db, ctx, session)      # not ready yet
        session = await fs.mark_ready(db, session)
        assert session.status == FillStatus.READY
        proposal = await fs.build(db, ctx, session)

    assert proposal.template_kind == "docx_simple"
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
    assert session.status == FillStatus.BUILT
    assert session.proposal_id == proposal.id


async def test_a_fill_still_asking_cannot_be_marked_ready(client, org_a):
    program_id, lead_id = await _ground(client, org_a["admin_token"],
                                        "J2ASK", "Orchid J2C")
    ctx = await _ctx(client, org_a["admin_token"])
    import app.ai.docx_tagfill as tf_mod
    original = tf_mod.get_model_layer
    tf_mod.get_model_layer = lambda: FillLayer({"resolutions": []})
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(db, ctx, lead_id=lead_id,
                                            program_id=program_id,
                                            chat_session_id="chat-j2c")
            assert session.status == FillStatus.ASKING
            with pytest.raises(ValidationFailedError):
                await fs.mark_ready(db, session)
            with pytest.raises(ValidationFailedError):
                await fs.build(db, ctx, session)
            assert session.status == FillStatus.ASKING
    finally:
        tf_mod.get_model_layer = original


# --- the document ------------------------------------------------------------


async def test_the_written_document_has_the_values_and_no_tags_left(
        client, org_a, no_pdf):
    ctx, session, program_id, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2DOC", "Orchid J2D",
        values=None)
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    written = storage.read_bytes(ctx.org_id, proposal.docx_path)
    assert docx_tags.scan(written) == []          # nothing left to fill
    text = fs._document_text(written)
    assert "2 Units" in text
    assert "<ask:1 Unit>" not in text
    assert "<School Name>" not in text


async def test_a_document_that_could_not_be_written_is_not_shipped(
        client, org_a, no_pdf, monkeypatch):
    """`apply_tags` reports rather than raises, so acting on the report is
    this layer's job. A proposal still reading "<ask:6 Units>" is worse than
    no proposal at all."""
    ctx, session, _, lead_id, _ = await _answered_fill(
        client, org_a["admin_token"], "J2SKIP", "Orchid J2E")

    def _all_skipped(docx_bytes, occurrences, values):
        return {"docx": docx_bytes, "written": [],
                "skipped": [{"tag_id": o["tag_id"], "raw": o["raw"],
                             "reason": "the tag is no longer at those offsets"}
                            for o in occurrences]}

    monkeypatch.setattr(fs.tagfill, "apply_tags", _all_skipped)
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        with pytest.raises(ValidationFailedError) as err:
            await fs.build(db, ctx, session)

    assert "could not be written" in str(err.value)
    async with SessionLocal() as db:
        rows = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
    assert rows == []


async def test_the_pdf_is_produced_and_a_failure_does_not_lose_the_document(
        client, org_a):
    """One real LibreOffice conversion, and the fallback beside it: the
    document is already written and stored when the converter runs, and the
    send path converts on demand -- so raising here would throw away an
    approved document over a converter hiccup."""
    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2PDF", "Orchid J2F")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    assert proposal.pdf_path
    assert storage.read_bytes(ctx.org_id, proposal.pdf_path)[:5] == b"%PDF-"

    ctx2, session2, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2PDX", "Orchid J2G")

    def _broken(*args, **kwargs):
        raise RuntimeError("soffice is not installed")

    async with SessionLocal() as db:
        session2 = await db.get(ProposalFillSession, session2.id)
        await fs.mark_ready(db, session2)
        original = fs.convert.docx_to_pdf
        fs.convert.docx_to_pdf = _broken
        try:
            second = await fs.build(db, ctx2, session2)
        finally:
            fs.convert.docx_to_pdf = original

    assert second.pdf_path is None
    assert second.docx_path                       # the document survived


async def test_a_static_contents_page_is_remeasured_after_the_fill(
        client, org_a, no_pdf, monkeypatch):
    """A static table of contents carries page numbers only LibreOffice can
    re-measure, and the replacements have just changed the text it counts.
    Exactly what docx_proposal_service does after its own fill."""
    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2TOC", "Orchid J2P")

    refreshed = []

    def _refresh(docx_bytes):
        refreshed.append(len(docx_bytes))
        return docx_bytes

    monkeypatch.setattr(fs.ix, "detect_bytes", lambda _b: "static")
    monkeypatch.setattr(fs.ix, "refresh_static", _refresh)
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        await fs.build(db, ctx, session)

    assert refreshed, "a static contents page was not re-measured"


async def test_approving_twice_does_not_write_two_documents(
        client, org_a, no_pdf):
    """A tapped button, a retried request, a model that calls the tool twice.
    Building is the one step here that cannot be undone."""
    ctx, session, _, lead_id, _ = await _answered_fill(
        client, org_a["admin_token"], "J2TWICE", "Orchid J2Q")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        first = await fs.build(db, ctx, session)
        session = await db.get(ProposalFillSession, session.id)
        second = await fs.build(db, ctx, session)

    assert first.id == second.id
    async with SessionLocal() as db:
        rows = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
    assert len(rows) == 1


async def test_what_went_into_the_proposal_is_recorded_for_the_app(
        client, org_a, no_pdf):
    """The Android "What went into this proposal" card reads `filled_json`.
    Its six keys are the complex flow's -- renaming one turns a working card
    into a blank one -- and `source` says where each value actually came from.
    """
    token = org_a["admin_token"]
    program_id, lead_id = await _ground(client, token, "J2CARD", "Orchid J2H")
    ctx = await _ctx(client, token)
    tags = await _plan_tags(program_id)
    by_kind = {t["kind"]: t for t in tags}
    semantic, ask = by_kind["semantic"], by_kind["ask"]

    import app.ai.docx_tagfill as tf_mod
    layer = FillLayer(
        # The model fills the semantic tag from a real dossier fact...
        {"resolutions": [
            {"tag_id": semantic["tag_id"], "value": "Orchid J2H",
             "confidence": 0.97, "citation": "client.name",
             "reason": "the client's own name"},
        ]},
        # ...and the person answers the asks: one in their own words, one
        # accepting the template's suggestion verbatim.
        {"resolutions": [
            {"tag_id": t["tag_id"],
             "value": "3 Units" if t["tag_id"] == ask["tag_id"] else "1 Unit",
             "reason": "answered"}
            for t in tags if t["kind"] != "semantic"
        ]},
    )
    original = tf_mod.get_model_layer
    tf_mod.get_model_layer = lambda: layer
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(db, ctx, lead_id=lead_id,
                                            program_id=program_id,
                                            chat_session_id="chat-j2card")
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.apply_answers(db, ctx, session, "three panels")
    finally:
        tf_mod.get_model_layer = original

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    filled = proposal.filled_json
    assert len(filled) == len(tags)
    for row in filled:
        assert set(row) >= {"key", "kind", "source", "text", "brief", "anchor"}
    by_key = {row["key"]: row for row in filled}
    assert by_key[semantic["tag_id"]]["source"] == "ai"
    assert by_key[semantic["tag_id"]]["citation"] == "client.name"
    assert by_key[ask["tag_id"]]["source"] == "user"
    assert by_key[ask["tag_id"]]["text"] == "3 Units"
    # The person accepted the author's own suggestion word for word, so the
    # words are the template's even though the choice was theirs.
    other = [t for t in tags if t["kind"] == "ask" and t["tag_id"] != ask["tag_id"]][0]
    assert by_key[other["tag_id"]]["source"] == "default"
    assert all(row["computed_by"] is None for row in filled)


async def test_no_number_in_the_record_was_produced_by_a_model(
        client, org_a, no_pdf):
    """D15's rule survives the change, by a shorter route than before.

    "No number reaches a document unless Python computed it from the locked
    rate card, or a person typed it." This flow computes nothing, so every
    figure in the proposal is one a person typed and approved -- and the
    record asserts no total of its own to be wrong about.
    """
    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2NUM", "Orchid J2I")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    assert proposal.total_amount == 0.0
    assert proposal.line_items == []
    # Every value that IS in the document came from a person or a cited fact.
    assert {row["source"] for row in proposal.filled_json} <= {
        "ai", "user", "default"}
    assert all(row["computed_by"] is None for row in proposal.filled_json)


# --- corrections -------------------------------------------------------------


async def test_a_correction_changes_the_written_document(
        client, org_a, no_pdf, fill_model):
    """The proof J2 is asked for: the review is not decorative."""
    ctx, session, program_id, _, tags = await _answered_fill(
        client, org_a["admin_token"], "J2FIX", "Orchid J2J")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "5 Units", "reason": "the panel"},
    ]})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.apply_correction(
            db, ctx, session, "make the interactive panel five units")
        assert session.status == FillStatus.REVIEWING
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    text = fs._document_text(storage.read_bytes(ctx.org_id, proposal.docx_path))
    assert "5 Units" in text
    by_key = {row["key"]: row for row in proposal.filled_json}
    assert by_key[panel["tag_id"]]["text"] == "5 Units"
    assert "the correction:" in by_key[panel["tag_id"]]["citation"]


async def test_a_corrected_value_is_unreviewed_again(
        client, org_a, fill_model):
    """D13's flag means a human saw THIS value, and a value that has just
    changed has not been seen since."""
    ctx, session, _, _, tags = await _answered_fill(
        client, org_a["admin_token"], "J2UNREV", "Orchid J2K")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        assert all(t["reviewed"] for t in session.tags_json)

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "5 Units", "reason": "the panel"},
    ]})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        with pytest.raises(ValidationFailedError):
            await fs.apply_correction(db, ctx, session, "five panels")


async def test_a_correction_nobody_could_place_changes_nothing(
        client, org_a, fill_model):
    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2VAGUE", "Orchid J2L")
    before = [dict(t) for t in session.tags_json]

    fill_model({"resolutions": []})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.apply_correction(db, ctx, session, "that looks off")

    assert [dict(t) for t in session.tags_json] == before
    assert session.status == FillStatus.REVIEWING


# --- through the assistant ---------------------------------------------------


async def test_approving_in_the_chat_builds_the_document(
        client, org_a, agent_model, fill_model, no_pdf):
    """The end J1's test stopped short of: create, answer, review, approve,
    document -- all inside one session_id."""
    token = org_a["admin_token"]
    chat = "chat-j2end"
    program_id, lead_id = await _ground(client, token, "J2END", "Orchid J2M")
    # Jarvis makes no proposal for a lead still in cold calling.
    await open_lead(client, token, lead_id)
    tags = await _plan_tags(program_id)

    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J2M", "program": "J2END"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the J2END proposal", session_id=chat)

    fill_model({"resolutions": [
        {"tag_id": t["tag_id"], "value": "2 Units", "reason": "answered"}
        for t in tags
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="answer_proposal_questions",
                                         args={"answer": "two of each"})]),
        LlmResponse(text="Here is what I will write."),
    ])
    body = (await _command(client, token, "two of each", session_id=chat)).json()

    # The last answer posts the review, not a document.
    review = _asked(body)
    assert review is not None
    assert "Interactive Panel" in review["question"]
    assert "you told me" in review["question"]
    assert review["candidates"] == ["Yes, these are all correct"]
    async with SessionLocal() as db:
        assert (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all() == []

    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="confirm_proposal_values",
                                         args={"approved": True})]),
        LlmResponse(text="Done -- the proposal is ready."),
    ])
    body = (await _command(client, token, "yes, all correct",
                           session_id=chat)).json()

    built = [a for a in body["actions"] if a["tool"] == "confirm_proposal_values"]
    assert built and built[0]["ok"] is True, built
    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
        session = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat))).scalars().first()
    assert len(proposals) == 1
    assert proposals[0].template_kind == "docx_simple"
    assert session.status == FillStatus.BUILT
    assert session.proposal_id == proposals[0].id


async def test_a_correction_in_the_chat_is_never_read_as_an_approval(
        client, org_a, agent_model, fill_model, no_pdf):
    """Building is the half of this that cannot be undone, so a correction
    beats an approval whenever a confused model sends both."""
    token = org_a["admin_token"]
    ctx, session, _, lead_id, tags = await _answered_fill(
        client, token, "J2BOTH", "Orchid J2N")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "9 Units", "reason": "the panel"},
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="confirm_proposal_values",
            args={"approved": True, "correction": "make the panel nine"})]),
        LlmResponse(text="Updated -- here is the list again."),
    ])
    body = (await _command(client, token, "actually make the panel nine",
                           session_id="chat-J2BOTH")).json()

    assert _asked(body) is not None               # the review, again
    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
        session = await db.get(ProposalFillSession, session.id)
    assert proposals == []
    assert session.status == FillStatus.REVIEWING
    assert {t["tag_id"]: t["value"] for t in session.tags_json}[
        panel["tag_id"]] == "9 Units"


async def test_calling_the_gate_without_a_decision_builds_nothing(
        client, org_a, agent_model, no_pdf):
    """The default has to be "not approved". A model that calls the tool
    without working out what the user said must re-post the list, not ship a
    document -- silence is not consent, and building is the one step here that
    cannot be taken back."""
    token = org_a["admin_token"]
    _, session, _, lead_id, _ = await _answered_fill(
        client, token, "J2MUTE", "Orchid J2R")

    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="confirm_proposal_values",
                                         args={})]),
        LlmResponse(text="Here is the list again."),
    ])
    body = (await _command(client, token, "hmm", session_id="chat-J2MUTE")).json()

    asked = _asked(body)
    assert asked is not None and asked["tool"] == "confirm_proposal_values"
    assert "about to write into the document" in asked["question"]
    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
        session = await db.get(ProposalFillSession, session.id)
    assert proposals == []
    assert session.status == FillStatus.REVIEWING


async def test_the_review_can_be_shown_again_without_approving_it(
        client, org_a, agent_model, no_pdf):
    token = org_a["admin_token"]
    _, session, _, lead_id, _ = await _answered_fill(
        client, token, "J2SHOW", "Orchid J2O")

    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(name="show_proposal_review", args={})]),
        LlmResponse(text="Here it is."),
    ])
    body = (await _command(client, token, "show me that list again",
                           session_id="chat-J2SHOW")).json()

    shown = [a for a in body["actions"] if a["tool"] == "show_proposal_review"]
    assert shown and shown[0]["ok"] is True
    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
        session = await db.get(ProposalFillSession, session.id)
    assert proposals == []
    assert session.status == FillStatus.REVIEWING

async def test_the_review_collapses_lines_that_say_the_same_thing(
        client, org_a, fill_model):
    """A client's name appears nine times in the real YuviPep document, six of
    them in footers with no row label to tell them apart. Nine identical lines
    is nine lines a reader's eye slides over -- which is the formality this
    review exists NOT to be. They collapse to one line carrying the count, and
    nothing is hidden: a row differing in value, origin or place stays its own
    line, because that is a separate thing to check.
    """
    from app.ai.agents import proposal_agent as pa

    rows = [
        {"about": "Footer", "value": "Orchid", "source": "ai", "warnings": []},
        {"about": "Footer", "value": "Orchid", "source": "ai", "warnings": []},
        {"about": "Footer", "value": "Orchid", "source": "ai", "warnings": []},
        # same place and value, but a person supplied this one
        {"about": "Footer", "value": "Orchid", "source": "user", "warnings": []},
        # same place and origin, different value
        {"about": "Footer", "value": "Orchid Intl", "source": "ai", "warnings": []},
        {"about": "Grades", "value": "1 to 8", "source": "user", "warnings": []},
    ]
    grouped = pa._group(rows)

    assert [count for _, count in grouped] == [3, 1, 1, 1]
    assert [row["value"] for row, _ in grouped] == [
        "Orchid", "Orchid", "Orchid Intl", "1 to 8"]

    # And on a real fill: this document's two `<ask:1 Unit>` tags carry the
    # same value but sit in different rows, so they are two things to check
    # and stay two lines. Grouping that collapsed them would hide one.
    _, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2GRP", "Orchid J2S")
    message = pa._review_message(session)
    numbered = [ln for ln in message.splitlines()
                if ln[:1].isdigit() and ". " in ln]
    assert len(numbered) == 3
    assert "in 2 places" not in message
    assert any("Interactive Panel" in ln for ln in numbered)
    assert any("Magazine Rack" in ln for ln in numbered)


# --- an offering whose prices live in the document ---------------------------


async def _ground_without_pricing(client, token, code, lead_name):
    """A programme with a tagged template and NO rate card at all."""
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"Fill {code}", "code": code, "description": "d"},
    )).json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Tagged", "make_current": "true", "flow": "simple"},
        files={"file": ("t.docx", _tagged_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": lead_name})).json()["id"]
    return program["id"], lead_id


async def _answered_without_pricing(client, token, code, name):
    program_id, lead_id = await _ground_without_pricing(client, token, code, name)
    ctx = await _ctx(client, token)
    tags = await _plan_tags(program_id)

    layer = FillLayer({"resolutions": []})
    import app.ai.docx_tagfill as tf_mod
    original = tf_mod.get_model_layer
    tf_mod.get_model_layer = lambda: layer
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(db, ctx, lead_id=lead_id,
                                            program_id=program_id,
                                            chat_session_id=f"chat-{code}")
        layer.replies = [{"resolutions": [
            {"tag_id": t["tag_id"], "value": "2 Units", "reason": "answered"}
            for t in tags
        ]}]
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.apply_answers(db, ctx, session, "two of each")
    finally:
        tf_mod.get_model_layer = original
    return ctx, session, lead_id


async def test_a_proposal_builds_with_no_rate_card_at_all(
        client, org_a, no_pdf):
    """The owner's decision, 8 September: a rate card is OPTIONAL.

    An offering whose prices live inside the Word document has nothing to put
    in a rate card, and requiring one made the salesperson meet
    "No pricing table for this program" at the end of a conversation they had
    already answered every question in. Nothing the CLIENT sees depended on it
    either: in this flow every figure in the document comes from a tag and the
    person's own answer, never from the PricingTable.
    """
    ctx, session, lead_id = await _answered_without_pricing(
        client, org_a["admin_token"], "NOCARD", "Orchid NoCard")

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    assert proposal.template_kind == "docx_simple"
    assert proposal.pricing_table_id is None
    assert proposal.pricing_version is None
    # The owner's choice for the record: an empty commercial rather than a
    # missing one. The app already renders a null total as "a dash" and reads
    # pricing_version through a null check, so nothing downstream has to change.
    assert proposal.line_items == []
    assert proposal.total_amount == 0.0
    assert proposal.currency

    # And the document is still a real document.
    written = storage.read_bytes(ctx.org_id, proposal.docx_path)
    assert docx_tags.scan(written) == []
    assert "2 Units" in fs._document_text(written)


async def test_a_rate_card_is_recorded_but_never_claimed_as_the_total(
        client, org_a, no_pdf):
    """Owner's decision, 8 September, from seeing it go wrong.

    Where a rate card exists the LINK is kept -- which rate card was current
    when this proposal was made is worth knowing -- but its figures are not
    this proposal's commercials. In the complex flow they would be: there the
    rate card is written into the document's price table, so the total IS the
    document's total. Here the price table is filled by tags only (section 10,
    question 4), so a total taken from the rate card describes nothing on the
    page. In real use that put "Total amount: 2200" in front of a salesperson
    whose document said "Rs. 15,00,000/- to Rs. 25,00,000/-".
    """
    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "HASCARD", "Orchid HasCard")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    # Recorded.
    assert proposal.pricing_table_id is not None
    assert proposal.pricing_version == 1
    # Not claimed.
    assert proposal.line_items == []
    assert proposal.total_amount == 0.0
    # What the proposal is worth is in the document, in the words approved.
    assert any(row["kind"] == "ask" for row in proposal.filled_json)


async def test_the_markdown_path_still_demands_a_rate_card(client, org_a):
    """Unchanged, and it must be: a markdown template renders {total_amount}
    and {pricing_table} into the body, so building one without a rate card
    produces a document with holes where the commercials belong. Only the flow
    whose prices live in its own document may go without."""
    from app.core.exceptions import NotFoundError
    from app.services import proposal_service

    token = org_a["admin_token"]
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": "Markdown no card", "code": "MDNOCARD",
              "description": "d"})).json()
    await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Plain", "body_md": "A markdown body long enough to pass.",
              "make_current": True})
    ctx = await _ctx(client, token)
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": "Orchid Markdown"})).json()["id"]

    async with SessionLocal() as db:
        with pytest.raises(NotFoundError):
            await proposal_service.build_proposal(
                db, ctx, lead_id=lead_id, program_id=program["id"])


async def test_the_columns_are_nullable_in_the_model(client, org_a):
    """The schema half of the decision, asserted where a reader will find it.

    `create_all` builds a new database from these columns, so a fresh
    environment needs no migration at all -- only databases that already exist
    do, and scripts/migrations/2026-09-08_optional_rate_card.py is that.
    """
    from app.models.proposal import Proposal

    assert Proposal.__table__.c.pricing_table_id.nullable is True
    assert Proposal.__table__.c.pricing_version.nullable is True
    # Still not nullable, because every proposal has these whatever the flow.
    assert Proposal.__table__.c.template_id.nullable is False
    assert Proposal.__table__.c.total_amount.nullable is False


async def test_the_chat_card_announces_no_total_it_cannot_stand_behind(
        client, org_a, agent_model, fill_model, no_pdf):
    """What the owner actually saw on 8 September.

    The built-proposal card in the chat read "Total amount: 2200, Line items:
    Code: Robotics, Quantity: 1" for a proposal whose document said the
    investment was "Rs. 15,00,000/- to Rs. 25,00,000/-". 2200 was the rate
    card's per-student unit price with the quantity defaulted to 1 -- a unit
    price wearing a total's label, about a table that is not in this document.

    The card now reports no total at all. Zero would have been worse than
    absent: an absent figure reads as absent, a zero reads as free.
    """
    from app.ai.agents.proposal_agent import _proposal_summary

    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2CARD2", "Orchid Card")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    card = _proposal_summary(proposal)
    assert "total_amount" not in card
    assert "line_items" not in card
    assert "document" in card["commercials"]
    # Still identifies the proposal and which versions it locked.
    assert card["id"] == proposal.id
    assert card["pricing_version"] == proposal.pricing_version
    assert card["template_version"] == proposal.template_version


async def test_a_complex_flow_card_still_reports_its_commercials(client, org_a):
    """The other flow is untouched: there the rate card IS written into the
    document's price table, so its total is the document's total and the card
    must keep saying so."""
    from app.ai.agents.proposal_agent import _proposal_summary
    from app.models.proposal import Proposal

    complex_proposal = Proposal(
        id="x", title="t", status="draft", currency="INR",
        total_amount=500000.0,
        line_items=[{"code": "LAB", "label": "Innovation Lab", "unit": "lab",
                     "unit_price": 250000.0, "quantity": 2.0,
                     "line_total": 500000.0}],
        template_version=1, pricing_version=1, template_kind="docx",
    )
    card = _proposal_summary(complex_proposal)
    assert card["total_amount"] == 500000.0
    assert [i["code"] for i in card["line_items"]] == ["LAB"]
    assert "commercials" not in card


async def test_rewriting_the_wording_is_refused_for_a_filled_document(
        client, org_a, no_pdf):
    """Owner's decision, 8 September: not offered for a docx_simple proposal.

    `edit_narrative` rewrites `content_md`. For this flow that is the PROJECTED
    TEXT of the document that was already written and saved -- rewriting it
    changes the record and leaves the .docx the client actually receives
    untouched, so the assistant would report "wording updated" over a file
    that had not changed. In the transcript that prompted this it happened to
    refuse, but only because the instruction contained a price and tripped the
    complex flow's commercial fence; an instruction without one would have
    succeeded and silently desynced the record from the document.
    """
    from app.core.exceptions import ValidationFailedError

    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2EDIT", "Orchid Edit")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    from app.ai.agents.proposal_agent import ProposalAgent
    from app.ai.agents.base import AgentRuntime

    async with SessionLocal() as db:
        runtime = AgentRuntime(db=db, ctx=ctx)
        runtime.extra_context["proposal_id"] = proposal.id
        with pytest.raises(ValidationFailedError) as err:
            await ProposalAgent()._edit_narrative(
                runtime, instruction="make the opening warmer")

    message = str(err.value)
    # It has to name the way forward, not merely say no. That way forward
    # changed once corrections existed: it used to be "create the proposal
    # again", which was the only route then and is the long way round now.
    assert "tags" in message or "fill" in message.lower()
    assert "correct" in message.lower()


async def test_changing_line_items_is_refused_for_a_filled_document(
        client, org_a, no_pdf):
    """The same defect in the same family. A simple-flow proposal has no line
    items at all now, so an operation on them edits nothing and recomputes a
    total the document never had."""
    from app.core.exceptions import ValidationFailedError
    from app.ai.agents.proposal_agent import ProposalAgent
    from app.ai.agents.base import AgentRuntime

    ctx, session, _, _, _ = await _answered_fill(
        client, org_a["admin_token"], "J2ITEMS", "Orchid Items")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    async with SessionLocal() as db:
        runtime = AgentRuntime(db=db, ctx=ctx)
        runtime.extra_context["proposal_id"] = proposal.id
        with pytest.raises(ValidationFailedError) as err:
            await ProposalAgent()._update_items(
                runtime, operations=[{"op": "set_quantity", "code": "LAB",
                                      "quantity": 5}])

    # It must refuse for the RIGHT reason. `apply_line_item_ops` already
    # raises on a code it cannot find, and a simple-flow proposal has no line
    # items at all -- so without this assertion the test passes whether the
    # guard exists or not, on an incidental "no such item" from a layer that
    # knows nothing about which flow this is.
    message = str(err.value)
    assert "own Word document" in message
    assert "LAB" not in message


async def test_the_other_flows_can_still_be_edited(client, org_a):
    """The guard must be about THIS flow only. A markdown or complex-docx
    proposal is still edited exactly as it always was -- there the wording in
    `content_md` IS the proposal, and the line items ARE its commercials."""
    from app.ai.agents.proposal_agent import _refuses_editing

    class P:
        def __init__(self, kind):
            self.template_kind = kind

    assert _refuses_editing(P("docx_simple")) is True
    assert _refuses_editing(P("docx")) is False
    assert _refuses_editing(P("markdown")) is False


async def test_the_editing_tools_say_they_do_not_apply_here(client, org_a):
    """A refusal the model could have avoided is a refusal that should not
    have been reached: the descriptions say so before it tries."""
    from app.ai.agents.proposal_agent import ProposalAgent

    tools = {t.name: t.description for t in ProposalAgent().tools()}
    for name in ("edit_narrative", "update_line_items"):
        # `docx_simple` exactly, not an `or` over two phrasings: an `or` here
        # stayed true when one half was deleted, so it could not fail.
        assert "docx_simple" in tools[name], name
        assert "Does NOT apply" in tools[name], name


# --- correcting a proposal that has already been built ----------------------


async def _built(client, org_a, code, name, no_pdf_unused=None):
    """A finished simple-flow proposal, and its fill session."""
    ctx, session, _, lead_id, tags = await _answered_fill(
        client, org_a["admin_token"], code, name)
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)
        session = await db.get(ProposalFillSession, session.id)
    return ctx, session, proposal, tags


async def test_a_built_proposal_can_be_corrected_and_rebuilt(
        client, org_a, no_pdf, fill_model):
    """The gap the editing guard exposed, closed (owner, 8 September).

    Spotting one wrong number in a finished document used to mean answering
    every question again, because a built fill is not resumable and the
    editing tools -- rightly -- refuse to touch a document whose text they
    cannot actually change. The correction reopens the fill it was built from,
    changes the one value, and writes the document again from the same
    answers.
    """
    ctx, session, proposal, tags = await _built(
        client, org_a, "CORR1", "Orchid Corr1")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]
    before_text = fs._document_text(storage.read_bytes(ctx.org_id, proposal.docx_path))
    assert "2 Units" in before_text

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "7 Units", "reason": "the panel"},
    ]})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.reopen_for_correction(
            db, ctx, session, "make the interactive panel seven units")

    # D13 is not bypassed by a correction: it goes back to the review, and
    # nothing is written until a human has seen the list again.
    assert session.status == FillStatus.REVIEWING
    still = fs._document_text(storage.read_bytes(ctx.org_id, proposal.docx_path))
    assert "7 Units" not in still, "the document changed before it was approved"

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.mark_ready(db, session)
        rebuilt = await fs.build(db, ctx, session)

    # The SAME proposal, corrected -- not a second one.
    assert rebuilt.id == proposal.id
    after = fs._document_text(storage.read_bytes(ctx.org_id, rebuilt.docx_path))
    assert "7 Units" in after
    assert "2 Units" in after          # the other tag is untouched
    by_key = {r["key"]: r for r in rebuilt.filled_json}
    assert by_key[panel["tag_id"]]["text"] == "7 Units"
    assert "the correction:" in by_key[panel["tag_id"]]["citation"]

    async with SessionLocal() as db:
        rows = (await db.execute(select(Proposal).where(
            Proposal.lead_id == rebuilt.lead_id))).scalars().all()
    assert len(rows) == 1, "a correction must not leave two proposals behind"


async def test_a_correction_is_recorded_as_a_revision(
        client, org_a, no_pdf, fill_model):
    """`proposal_revisions` is how this project remembers what a proposal used
    to say, and the Android screen reads it. A rebuild that left no revision
    would lose the only record that the document ever said something else."""
    from app.models.proposal import ProposalRevision

    ctx, session, proposal, tags = await _built(
        client, org_a, "CORR2", "Orchid Corr2")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "9 Units", "reason": "the panel"},
    ]})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.reopen_for_correction(
            db, ctx, session, "nine panels")
        session = await fs.mark_ready(db, session)
        await fs.build(db, ctx, session)

    async with SessionLocal() as db:
        revs = (await db.execute(select(ProposalRevision).where(
            ProposalRevision.proposal_id == proposal.id
        ).order_by(ProposalRevision.revision_no))).scalars().all()
    assert len(revs) >= 2, "the correction left no revision"
    assert "nine panels" in (revs[-1].instruction or "")


async def test_a_proposal_the_client_already_has_is_not_rewritten(
        client, org_a, no_pdf, fill_model):
    """The one case where a correction must refuse. Once a proposal is sent,
    the client is holding the document; quietly rewriting the file behind that
    would make our record disagree with what they were sent."""
    from app.core.constants import ProposalStatus

    ctx, session, proposal, tags = await _built(
        client, org_a, "CORR3", "Orchid Corr3")
    async with SessionLocal() as db:
        row = await db.get(Proposal, proposal.id)
        row.status = ProposalStatus.SENT.value
        await db.commit()

    fill_model({"resolutions": []})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        with pytest.raises(ValidationFailedError) as err:
            await fs.reopen_for_correction(db, ctx, session, "change the panel")
    assert "sent" in str(err.value).lower()


async def test_building_twice_without_a_correction_still_returns_the_same(
        client, org_a, no_pdf):
    """The idempotence that stopped a double approval writing two documents
    must survive the rebuild path being added."""
    ctx, session, proposal, _ = await _built(client, org_a, "CORR4", "Orchid Corr4")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        again = await fs.build(db, ctx, session)
    assert again.id == proposal.id
    assert again.docx_path == proposal.docx_path, "it rebuilt when nothing changed"


async def test_a_correction_nobody_could_place_leaves_the_document_alone(
        client, org_a, no_pdf, fill_model):
    ctx, session, proposal, _ = await _built(client, org_a, "CORR5", "Orchid Corr5")
    fill_model({"resolutions": []})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.reopen_for_correction(db, ctx, session, "hmm")
    assert session.status == FillStatus.BUILT, "a vague sentence reopened the fill"


async def test_only_this_conversation_can_correct_its_own_proposal(
        client, org_a, no_pdf):
    """Same rule as resuming: a fill is one person's conversation."""
    ctx, session, _, _ = await _built(client, org_a, "CORR6", "Orchid Corr6")
    async with SessionLocal() as db:
        mine = await fs.find_correctable(
            db, ctx, chat_session_id="chat-CORR6")
        wrong_chat = await fs.find_correctable(
            db, ctx, chat_session_id="somebody-elses-chat")
        no_chat = await fs.find_correctable(db, ctx, chat_session_id=None)
    assert mine is not None and mine.id == session.id
    assert wrong_chat is None
    assert no_chat is None


async def test_a_proposal_older_than_the_window_is_not_corrected(
        client, org_a, no_pdf):
    """The dossier a correction reasons over was assembled when the fill was
    opened. Past the window it is stale, and a fresh proposal is the honest
    answer -- the same rule resuming already follows."""
    from sqlalchemy import update as sql_update

    ctx, session, _, _ = await _built(client, org_a, "CORR7", "Orchid Corr7")
    stale = utcnow() - timedelta(days=fs.FILL_SESSION_TTL_DAYS, hours=1)
    async with SessionLocal() as db:
        await db.execute(sql_update(ProposalFillSession)
                         .where(ProposalFillSession.id == session.id)
                         .values(updated_at=stale))
        await db.commit()
    async with SessionLocal() as db:
        assert await fs.find_correctable(
            db, ctx, chat_session_id="chat-CORR7") is None


async def test_the_assistant_offers_the_correction_in_the_chat(
        client, org_a, agent_model, fill_model, no_pdf):
    """End to end through the tool the model actually calls."""
    ctx, session, proposal, tags = await _built(
        client, org_a, "CORR8", "Orchid Corr8")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "4 Units", "reason": "the panel"},
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="correct_proposal",
            args={"correction": "the interactive panel should be four"})]),
        LlmResponse(text="Here is the updated list."),
    ])
    body = (await _command(client, org_a["admin_token"],
                           "actually make the panel four",
                           session_id="chat-CORR8")).json()

    asked = _asked(body)
    assert asked is not None, "the corrected review was not put to the user"
    assert "4 Units" in asked["question"]
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
    assert session.status == FillStatus.REVIEWING


async def test_the_editing_refusal_now_points_at_the_correction(client, org_a):
    """The message written when there WAS no way to correct a built proposal
    told people to create it again. There is one now, and a message that sends
    someone the long way round is a worse answer than no message."""
    from app.ai.agents.proposal_agent import NOT_EDITABLE_HERE

    assert "correct" in NOT_EDITABLE_HERE.lower()
    assert "creating the proposal again" not in NOT_EDITABLE_HERE


async def test_a_failed_conversion_leaves_no_pdf_rather_than_yesterdays(
        client, org_a, no_pdf, fill_model):
    """The rebuild's sharpest edge. `_attach_pdf` is deliberately non-fatal --
    a converter hiccup must not throw away an approved document -- so on a
    REBUILD a failure would otherwise leave `pdf_path` pointing at the PDF of
    the document as it was BEFORE the correction. A stale PDF beside a
    corrected .docx is worse than no PDF: the send path would attach it.
    """
    ctx, session, proposal, tags = await _built(
        client, org_a, "CORRPDF", "Orchid CorrPdf")
    panel = [t for t in tags if t["context"] == "Interactive Panel"][0]
    old_pdf = proposal.pdf_path
    assert old_pdf, "the first build produced no PDF to go stale"

    fill_model({"resolutions": [
        {"tag_id": panel["tag_id"], "value": "6 Units", "reason": "the panel"},
    ]})

    def _broken(*args, **kwargs):
        raise RuntimeError("soffice is not installed")

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.reopen_for_correction(db, ctx, session, "six panels")
        session = await fs.mark_ready(db, session)
        original = fs.convert.docx_to_pdf
        fs.convert.docx_to_pdf = _broken
        try:
            rebuilt = await fs.build(db, ctx, session)
        finally:
            fs.convert.docx_to_pdf = original

    assert rebuilt.pdf_path is None, "the PDF of the uncorrected document survived"
    assert rebuilt.docx_path != proposal.docx_path
    assert "6 Units" in fs._document_text(
        storage.read_bytes(ctx.org_id, rebuilt.docx_path))


async def test_a_vague_correction_in_the_chat_changes_nothing(
        client, org_a, agent_model, fill_model, no_pdf):
    """The agent's own guard, which the service-level test cannot reach: the
    handler compares the tags before and after and re-posts the list rather
    than reporting a change it did not make."""
    ctx, session, proposal, _ = await _built(
        client, org_a, "CORRVAGUE", "Orchid Vague")

    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="correct_proposal", args={"correction": "something looks off"})]),
        LlmResponse(text="Which one?"),
    ])
    body = (await _command(client, org_a["admin_token"], "something looks off",
                           session_id="chat-CORRVAGUE")).json()

    asked = _asked(body)
    assert asked is not None
    assert "could not tell which value" in asked["question"]
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        row = await db.get(Proposal, proposal.id)
    assert session.status == FillStatus.BUILT, "a vague sentence reopened the fill"
    assert row.docx_path == proposal.docx_path, "the document was rewritten"
