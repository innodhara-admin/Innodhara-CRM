# tests/docx/test_mou_agent.py
"""The agent's MOU tools, and the words that tell it they exist (Task A2).

**This is the task the last session lost three days to.** J1 added the fill
tools and never told the agent about them: the agent ran on the fast tier,
called `create_proposal` six times, `answer_proposal_questions` zero, and the
conversation looped in front of the owner. Every test written for it scripted
`ToolCall(name=...)`, which proves what happens WHEN a tool is called and
never that a model WOULD call it.

So two things ship together here and neither is optional. The tools, and the
paragraph in the system prompt that names them -- because a tool the prompt
does not mention is a tool the model does not call. Whether the model actually
picks them is A3's, and it is a separate test file for a reason.

The third thing is that THE WRONG TOOL MUST BE HARMLESS. A prompt is advice;
a tool result is fact, and on the fast tier advice is not enough. `create_mou`
on a fill that is already open returns `already_open`, says how many questions
are outstanding and names the tool that moves it on, rather than re-raising
the round and looking like progress.
"""
import io

import pytest
from docx import Document
from sqlalchemy import select

from app.ai import docx_tagfill
from app.ai import llm as llm_mod
from app.ai import orchestrator
from app.ai.agents import base as agent_base
from app.ai.agents import proposal_agent as pa
from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal
from app.models.mou import MouDocument
from app.models.program import ProposalTemplate
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services.docx import tags as dtags
from tests.conftest import auth, fresh_lead, open_lead

API = "/api/v1"
# No `pytestmark = pytest.mark.asyncio`: pytest.ini sets asyncio_mode = auto,
# so async tests are collected anyway and marking the SYNC ones warns.


# --- the documents ------------------------------------------------------------


def _mou_docx() -> bytes:
    """A contract with three things to ask about, in two sections."""
    doc = Document()
    doc.add_heading("Memorandum of Understanding", level=1)
    doc.add_paragraph(
        "Between <School Name> and YuviPep, a body paragraph long enough to "
        "serve as a style reference.")
    doc.add_paragraph("Signed for the school by <ask:Smt. Y S Ghorpade>.")
    doc.add_heading("Operation Terms", level=2)
    doc.add_paragraph("The programme runs for <ask:one academic year>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _priced_mou_docx() -> bytes:
    """Three figures that are meant to multiply. D-E's whole subject."""
    doc = Document()
    doc.add_heading("Pricing Details", level=2)
    doc.add_paragraph("Price per student <ask_calculate:Rs. 4000>.")
    doc.add_paragraph("Students <ask:75>.")
    doc.add_paragraph("Payable annually <ask_calculate:Rs. 3,00,000>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _proposal_docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    doc.add_paragraph("Quantity <ask:1 Unit>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- the two model layers -----------------------------------------------------


class FakeModelLayer:
    """The agent's model: a scripted sequence of tool calls and replies."""

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
    """The fill pass's model.

    Answers by ANSWER MAP rather than by script, so a test does not have to
    know how many passes the service happens to make. The relation pass is
    told apart by its prompt, exactly as F2's own tests do it.
    """

    def __init__(self, answers=None, relations=None, tags=None):
        self.answers = answers or {}
        self.relations = relations or []
        self.tags = tags or []
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        body = kwargs["messages"][-1]["content"]
        if "ARITHMETICALLY RELATED" in body:
            return {"relations": list(self.relations)}
        return {"resolutions": [
            {"tag_id": tag["tag_id"], "value": self.answers[tag["raw"]],
             "confidence": 1.0, "citation": "turn 1",
             "reason": "the person said so"}
            for tag in self.tags if tag["raw"] in self.answers]}


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
    def _install(**kwargs):
        layer = FillLayer(**kwargs)
        monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: layer)
        return layer
    return _install


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-stub")


# --- grounding ----------------------------------------------------------------


async def _program(client, token, code) -> str:
    return (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"MOU {code}", "code": code, "description": "d"},
    )).json()["id"]


async def _upload(client, token, program_id, data, document_type):
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": document_type, "make_current": "true", "flow": "simple",
              "document_type": document_type},
        files={"file": ("t.docx", data,
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _ground(client, token, code, lead_name, *, docx=None,
                  with_proposal=False):
    program_id = await _program(client, token, code)
    await _upload(client, token, program_id, docx or _mou_docx(), "mou")
    if with_proposal:
        await _upload(client, token, program_id, _proposal_docx(), "proposal")
    lead_id = (await fresh_lead(client, token, lead_name))["id"]
    # Jarvis makes no MOU or proposal for a lead still in cold calling.
    await open_lead(client, token, lead_id)
    return program_id, lead_id


async def _command(client, token, text, *, session_id, agent="proposal"):
    return await client.post(
        f"{API}/assistant/command", headers=auth(token),
        json={"text": text, "agent": agent, "session_id": session_id})


def _asked(body) -> dict | None:
    for action in body["actions"]:
        if action.get("outcome") == "needs_confirmation":
            return action
    return None


def _tool_result(layer, tool):
    for call in layer.calls:
        for message in call.get("messages") or []:
            if message.get("role") == "tool_result" \
                    and message.get("name") == tool:
                return message["result"]
    raise AssertionError(f"the model was never given a result for {tool}")


def _call(name, **args):
    return LlmResponse(tool_calls=[ToolCall(name=name, args=args)])


async def _fill_for(chat, document_type="mou"):
    async with SessionLocal() as db:
        return (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat,
            ProposalFillSession.document_type == document_type,
        ))).scalars().first()


def _tags_of(docx_bytes):
    return [o.as_dict() for o in dtags.scan(docx_bytes)]


def _values(session):
    """What a fill actually SAYS: every tag, its outcome and its value.

    Not the whole record. The answer pass re-words an open question it
    could not settle -- that is D46, keeping the re-ask narrower than the
    question before it -- so comparing the records whole would call a
    reworded question a changed document. Nothing is written into a
    document but values.
    """
    return [(t["tag_id"], t["outcome"], t.get("value"))
            for t in session.tags_json]


MOU_ANSWERS = {
    "<School Name>": "Orchid International School",
    "<ask:Smt. Y S Ghorpade>": "Smt. R Kulkarni",
    "<ask:one academic year>": "AY 2026-27",
}


async def _open_mou(client, token, code, name, agent_model, fill_model,
                    *, docx=None, answers=None, relations=None, chat=None):
    """A conversation with an MOU fill open, driven through the real route."""
    docx = docx or _mou_docx()
    chat = chat or f"chat-{code}".lower()
    program_id, lead_id = await _ground(client, token, code, name, docx=docx)
    fill_model(answers=answers or MOU_ANSWERS, relations=relations,
               tags=_tags_of(docx))
    layer = agent_model([
        _call("create_mou", client=name, program=code),
        LlmResponse(text="A few details first."),
    ])
    body = (await _command(client, token, f"create the {code} MOU",
                           session_id=chat)).json()
    return layer, body, chat, program_id, lead_id


# --- the prompt, which ships with the tools ----------------------------------


def test_the_system_prompt_names_every_mou_tool():
    """A tool the prompt does not mention is a tool the model does not call.
    That sentence is the whole of the three days this task cost."""
    prompt = pa.ProposalAgent.system_prompt
    for tool in ("create_mou", "answer_mou_questions", "show_mou_questions",
                 "confirm_mou_values", "correct_mou"):
        assert tool in prompt, f"the prompt never mentions {tool}"


def test_the_prompt_says_an_mou_is_not_a_proposal():
    """`create_proposal` for a contract would build the wrong document into
    the wrong table and put it in the sales pipeline (D-A)."""
    prompt = pa.ProposalAgent.system_prompt
    assert "MOU" in prompt
    assert "never `create_proposal`" in prompt or \
           "never create_proposal" in prompt


def test_the_prompt_forbids_calling_create_mou_twice():
    prompt = pa.ProposalAgent.system_prompt
    assert "create_mou` a second time" in prompt or \
           "create_mou a second time" in prompt


def test_the_agent_offers_the_mou_tools():
    names = {t.name for t in pa.ProposalAgent().tools()}
    assert {"create_mou", "answer_mou_questions", "show_mou_questions",
            "confirm_mou_values", "show_mou_review", "correct_mou"} <= names


def test_the_router_prompt_knows_what_an_mou_is():
    """Measured before this task: the word appeared nowhere, so "create the
    MOU for IBC" matched nothing and fell back to `query`. A3 tests that a
    model actually routes it; this pins that the words are there to route on.
    """
    assert "MOU" in orchestrator._ROUTER_PROMPT
    proposal_line = [
        line for line in orchestrator._ROUTER_PROMPT.splitlines()
        if line.strip().startswith("- proposal:")]
    assert proposal_line, "the proposal line vanished"
    block = orchestrator._ROUTER_PROMPT.split("- proposal:")[1].split("\n- ")[0]
    assert "MOU" in block or "memorand" in block.lower()


# --- opening a fill -----------------------------------------------------------


async def test_create_mou_opens_a_fill_and_asks_the_first_round(
    client, org_a, agent_model, fill_model
):
    token = org_a["admin_token"]
    _layer, body, chat, _p, _l = await _open_mou(
        client, token, "AMOU1", "Orchid A1", agent_model, fill_model)

    asked = _asked(body)
    assert asked is not None, "the first round was never put to the user"
    session = await _fill_for(chat)
    assert session is not None
    assert session.document_type == "mou"
    assert session.status in (FillStatus.ASKING, FillStatus.GATHERING)


async def test_an_mou_fill_writes_no_proposal_row(
    client, org_a, agent_model, fill_model
):
    token = org_a["admin_token"]
    _layer, _body, _chat, _p, lead_id = await _open_mou(
        client, token, "AMOU2", "Orchid A2", agent_model, fill_model)
    async with SessionLocal() as db:
        rows = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
    assert rows == []


async def test_create_mou_on_a_programme_with_no_mou_template_says_so(
    client, org_a, agent_model, fill_model
):
    """And does NOT fall through to building a proposal, which is the
    document this programme does have a template for."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "AMOU3")
    await _upload(client, token, program_id, _proposal_docx(), "proposal")
    lead_id = (await fresh_lead(client, token, "Orchid A3"))["id"]
    await open_lead(client, token, lead_id)
    fill_model(answers={}, tags=[])
    layer = agent_model([
        _call("create_mou", client="Orchid A3", program="AMOU3"),
        LlmResponse(text="No contract template yet."),
    ])
    await _command(client, token, "create the AMOU3 MOU", session_id="chat-amou3")

    result = _tool_result(layer, "create_mou")
    assert result["ok"] is False
    assert "MOU" in result["message"]
    # Scoped to THIS lead. Asserting over every Proposal in the database
    # passed alone and failed in the suite, against rows other tests had
    # every right to create.
    async with SessionLocal() as db:
        assert (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all() == []


# --- THE LOOP-BREAKER ---------------------------------------------------------


async def test_calling_create_mou_again_names_the_right_tool(
    client, org_a, agent_model, fill_model
):
    """The regression test drives the WRONG tool deliberately, the way the
    real model did six times in a row in front of the owner.

    A prompt is advice and a tool result is fact. This is the fact.
    """
    token = org_a["admin_token"]
    _layer, _body, chat, _p, _l = await _open_mou(
        client, token, "AMOU4", "Orchid A4", agent_model, fill_model)

    layer = agent_model([
        _call("create_mou", client="Orchid A4", program="AMOU4"),
        LlmResponse(text="Still waiting on you."),
    ])
    await _command(client, token, "create the AMOU4 MOU", session_id=chat)

    result = _tool_result(layer, "create_mou")
    assert result["already_open"] is True
    assert result["still_to_answer"] > 0
    assert "answer_mou_questions" in result["what_to_do"]
    assert "create_mou" in result["what_to_do"], (
        "the result must name the tool NOT to call again, not only the right one")


async def test_calling_create_mou_again_opens_no_second_fill(
    client, org_a, agent_model, fill_model
):
    """Two fills for one chat would ask everything again and throw away the
    answers already given, and nothing would tell the salesperson which fill
    their next sentence reached."""
    token = org_a["admin_token"]
    _layer, _body, chat, _p, _l = await _open_mou(
        client, token, "AMOU5", "Orchid A5", agent_model, fill_model)
    agent_model([
        _call("create_mou", client="Orchid A5", program="AMOU5"),
        LlmResponse(text="Still waiting."),
    ])
    await _command(client, token, "create the AMOU5 MOU", session_id=chat)

    async with SessionLocal() as db:
        rows = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat))).scalars().all()
    assert len(rows) == 1


# --- answering ----------------------------------------------------------------


async def test_an_answer_settles_questions_without_reopening_the_fill(
    client, org_a, agent_model, fill_model
):
    token = org_a["admin_token"]
    _layer, _body, chat, _p, _l = await _open_mou(
        client, token, "AMOU6", "Orchid A6", agent_model, fill_model)
    before = await _fill_for(chat)
    assert fs.open_questions(before, limit=None)

    agent_model([
        _call("answer_mou_questions", answer="Kulkarni, this academic year"),
        LlmResponse(text="Noted."),
    ])
    await _command(client, token, "Kulkarni, this academic year",
                   session_id=chat)

    after = await _fill_for(chat)
    assert after.id == before.id
    assert fs.open_questions(after, limit=None) == []
    assert after.status == FillStatus.REVIEWING


async def test_show_mou_questions_answers_nothing_and_changes_nothing(
    client, org_a, agent_model, fill_model
):
    token = org_a["admin_token"]
    _layer, _body, chat, _p, _l = await _open_mou(
        client, token, "AMOU7", "Orchid A7", agent_model, fill_model)
    before = await _fill_for(chat)
    fill_model(answers={}, tags=[])   # a question about the question
                                     # settles nothing, so the
                                     # values must not move

    layer = agent_model([
        _call("show_mou_questions"),
        LlmResponse(text="Here is what is open."),
    ])
    await _command(client, token, "what were you asking?", session_id=chat)

    result = _tool_result(layer, "show_mou_questions")
    assert result["questions"] and all(
        q["tag_id"] and q["about"] for q in result["questions"])
    # D48: the turn ALSO passes the reply on, because a tool that only lists
    # has not dealt with it -- that is how the owner's "All the suggested
    # values are fine" was lost on 11 September. What `show_mou_questions`
    # itself must never do is change a value, and it does not.
    after = await _fill_for(chat)
    assert _values(after) == _values(before)


async def test_answering_when_no_mou_is_open_says_so_and_invents_nothing(
    client, org_a, agent_model, fill_model
):
    token = org_a["admin_token"]
    _program_id, lead_id = await _ground(client, token, "AMOU8", "Orchid A8")
    fill_model(answers={}, tags=[])
    agent_model([
        _call("answer_mou_questions", answer="seventy five"),
        LlmResponse(text="Nothing is open."),
    ])
    body = (await _command(client, token, "seventy five",
                           session_id="chat-amou8")).json()
    failed = [a for a in body["actions"] if a["tool"] == "answer_mou_questions"]
    assert failed and failed[0]["ok"] is False
    async with SessionLocal() as db:
        assert (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all() == []


# --- the review and the build -------------------------------------------------


async def _answered(client, token, code, name, agent_model, fill_model,
                    **kwargs):
    """An MOU fill sitting in `reviewing`, reached through the agent."""
    layer, _body, chat, program_id, lead_id = await _open_mou(
        client, token, code, name, agent_model, fill_model, **kwargs)
    agent_model([
        _call("answer_mou_questions", answer="as agreed"),
        LlmResponse(text="Noted."),
    ])
    await _command(client, token, "as agreed", session_id=chat)
    session = await _fill_for(chat)
    assert session.status == FillStatus.REVIEWING, session.status
    return chat, session, lead_id


async def test_confirming_the_values_builds_the_contract(
    client, org_a, agent_model, fill_model, no_pdf
):
    token = org_a["admin_token"]
    chat, _session, lead_id = await _answered(
        client, token, "AMOU9", "Orchid A9", agent_model, fill_model)

    layer = agent_model([
        _call("confirm_mou_values", approved=True),
        LlmResponse(text="Done."),
    ])
    await _command(client, token, "yes those are right", session_id=chat)

    result = _tool_result(layer, "confirm_mou_values")
    assert result["created"] is True
    assert result["built_from"] == "mou_simple"
    async with SessionLocal() as db:
        mous = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all()
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all()
    assert len(mous) == 1
    assert proposals == [], "approving an MOU wrote a Proposal row"


async def test_not_approving_reposts_the_review_and_writes_nothing(
    client, org_a, agent_model, fill_model, no_pdf
):
    token = org_a["admin_token"]
    chat, _session, lead_id = await _answered(
        client, token, "AMOUA", "Orchid AA", agent_model, fill_model)
    agent_model([
        _call("confirm_mou_values", approved=False),
        LlmResponse(text="Have another look."),
    ])
    body = (await _command(client, token, "hang on", session_id=chat)).json()
    assert _asked(body) is not None
    async with SessionLocal() as db:
        assert (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all() == []


async def test_approving_while_questions_are_open_names_the_answer_tool(
    client, org_a, agent_model, fill_model, no_pdf
):
    """The Orchid contract, 11 September. The round offered "All the
    suggested values are fine" as a tap; the fast-tier model read it as an
    approval and called `confirm_mou_values` with forty-four questions open;
    and the tool CRASHED -- "This proposal has not been through its review
    yet" -- which the model turned into a paragraph about checkpoints.

    The wrong tool must be harmless (D44). It returns, says how many
    questions are still open, and names the tool that moves the fill on.
    """
    token = org_a["admin_token"]
    _layer, _body, chat, _program_id, lead_id = await _open_mou(
        client, token, "AMOUW", "Orchid AW", agent_model, fill_model)
    assert (await _fill_for(chat)).status == FillStatus.ASKING

    layer = agent_model([
        _call("confirm_mou_values", approved=True),
        LlmResponse(text="Noted."),
    ])
    await _command(client, token, "All the suggested values are fine",
                   session_id=chat)

    result = _tool_result(layer, "confirm_mou_values")
    assert result.get("still_asking") is True, result
    assert result["still_to_answer"] == 3
    assert "answer_mou_questions" in result["what_to_do"]
    # D49: the fill DOES move on, because the redirect's own words say to pass
    # the reply to the answer tool and something now does. What D44 promised
    # is unchanged and is asserted below: nothing was built. The person said
    # "All the suggested values are fine" and that is an answer, whichever
    # tool the model reached for.
    async with SessionLocal() as db:
        assert (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all() == []


async def test_show_mou_review_lists_every_value_and_writes_nothing(
    client, org_a, agent_model, fill_model
):
    token = org_a["admin_token"]
    chat, session, lead_id = await _answered(
        client, token, "AMOUB", "Orchid AB", agent_model, fill_model)

    layer = agent_model([
        _call("show_mou_review"),
        LlmResponse(text="Here it is."),
    ])
    await _command(client, token, "what will it say?", session_id=chat)

    result = _tool_result(layer, "show_mou_review")
    assert len(result["values"]) == len(session.tags_json)
    assert result["still_to_answer"] == 0
    async with SessionLocal() as db:
        assert (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all() == []


async def test_correcting_a_built_mou_goes_back_through_the_review(
    client, org_a, agent_model, fill_model, no_pdf
):
    """D13 does not lapse because the document happens to exist already."""
    token = org_a["admin_token"]
    chat, _session, lead_id = await _answered(
        client, token, "AMOUC", "Orchid AC", agent_model, fill_model)
    agent_model([_call("confirm_mou_values", approved=True),
                 LlmResponse(text="Done.")])
    await _command(client, token, "yes", session_id=chat)

    async def _revise(_ctx, *, dossier, resolutions, correction):
        target = next(r for r in resolutions
                      if r["raw"] == "<ask:Smt. Y S Ghorpade>")
        return [{"tag_id": target["tag_id"], "value": "Dr A Rao",
                 "confidence": 1.0, "reason": "corrected", "citation": "c"}]

    monkey = docx_tagfill.revise
    docx_tagfill.revise = _revise
    try:
        agent_model([_call("correct_mou", correction="the signatory is Dr A Rao"),
                     LlmResponse(text="Have a look.")])
        body = (await _command(client, token, "the signatory is Dr A Rao",
                               session_id=chat)).json()
    finally:
        docx_tagfill.revise = monkey

    assert _asked(body) is not None, "a correction skipped the review"
    async with SessionLocal() as db:
        mous = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all()
    assert len(mous) == 1, "the correction wrote a second contract"


# --- THE EDITING TOOLS MUST REFUSE (defect 3) ---------------------------------


async def _built_mou(client, token, code, name, agent_model, fill_model):
    chat, _session, lead_id = await _answered(
        client, token, code, name, agent_model, fill_model)
    agent_model([_call("confirm_mou_values", approved=True),
                 LlmResponse(text="Done.")])
    await _command(client, token, "yes", session_id=chat)
    return chat, lead_id


async def test_edit_narrative_refuses_for_an_mou_and_names_the_way_forward(
    client, org_a, agent_model, fill_model, no_pdf
):
    token = org_a["admin_token"]
    chat, _lead = await _built_mou(client, token, "AMOUD", "Orchid AD",
                                   agent_model, fill_model)
    layer = agent_model([
        _call("edit_narrative", instruction="make the tone warmer, add a price of Rs 5000"),
        LlmResponse(text="I cannot edit a contract that way."),
    ])
    await _command(client, token, "make it warmer", session_id=chat)

    result = _tool_result(layer, "edit_narrative")
    assert result["ok"] is False
    assert "correct_mou" in result["message"]


async def test_it_refuses_on_an_instruction_WITHOUT_a_price(
    client, org_a, agent_model, fill_model, no_pdf
):
    """DEFECT 3, exactly. `edit_narrative` refused on a simple-flow proposal
    only because the instruction happened to contain a price and tripped
    `narrative_price_drift`. Ask what the code does on the path that does NOT
    trip the guard -- because without one it would have rewritten the RECORD
    of a document it cannot touch and reported success."""
    token = org_a["admin_token"]
    chat, _lead = await _built_mou(client, token, "AMOUE", "Orchid AE",
                                   agent_model, fill_model)
    layer = agent_model([
        _call("edit_narrative", instruction="reword the recitals"),
        LlmResponse(text="I cannot edit a contract that way."),
    ])
    await _command(client, token, "reword the recitals", session_id=chat)

    result = _tool_result(layer, "edit_narrative")
    assert result["ok"] is False
    assert "correct_mou" in result["message"]


async def test_update_line_items_refuses_for_an_mou(
    client, org_a, agent_model, fill_model, no_pdf
):
    """An MOU has no line items at all -- D-A removed the columns. Reaching
    for them would find some OTHER document's."""
    token = org_a["admin_token"]
    chat, _lead = await _built_mou(client, token, "AMOUF", "Orchid AF",
                                   agent_model, fill_model)
    layer = agent_model([
        _call("update_line_items", operations=[{"op": "set_quantity",
                                                "code": "LAB", "quantity": 4}]),
        LlmResponse(text="Not for a contract."),
    ])
    await _command(client, token, "make it four labs", session_id=chat)

    result = _tool_result(layer, "update_line_items")
    assert result["ok"] is False
    assert "correct_mou" in result["message"]


async def test_the_refusal_never_reaches_an_unrelated_proposal(
    client, org_a, agent_model, fill_model, no_pdf
):
    """THE UNSAFE SUCCESS this guard exists for.

    `_resolve_proposal` falls back to the client's most recent proposal when
    it is handed a name. A conversation about Orchid's MOU that says "make it
    warmer" would otherwise rewrite Orchid's unrelated PROPOSAL and report
    success -- a document the salesperson never mentioned.
    """
    token = org_a["admin_token"]
    program_id, lead_id = await _ground(client, token, "AMOUG", "Orchid AG",
                                        with_proposal=True)
    chat = "chat-amoug"
    fill_model(answers=MOU_ANSWERS, tags=_tags_of(_mou_docx()))
    agent_model([_call("create_mou", client="Orchid AG", program="AMOUG"),
                 LlmResponse(text="A few details.")])
    await _command(client, token, "create the AMOUG MOU", session_id=chat)
    agent_model([_call("answer_mou_questions", answer="as agreed"),
                 LlmResponse(text="Noted.")])
    await _command(client, token, "as agreed", session_id=chat)
    agent_model([_call("confirm_mou_values", approved=True),
                 LlmResponse(text="Done.")])
    await _command(client, token, "yes", session_id=chat)

    # An ORDINARY proposal for the same client, of the kind `_resolve_proposal`
    # would find by name. Nothing in the conversation mentions it.
    async with SessionLocal() as db:
        template = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.program_id == program_id,
            ProposalTemplate.document_type == "proposal",
        ))).scalars().first()
        other = Proposal(
            org_id=org_a["id"], lead_id=lead_id, program_id=program_id,
            title="An older proposal", content_md="The original wording",
            template_id=template.id, template_version=template.version,
            template_kind="markdown", created_by="u" * 32,
        )
        db.add(other)
        await db.commit()
        before = other.content_md

    layer = agent_model([
        _call("edit_narrative", instruction="reword it", proposal_ref="Orchid AG"),
        LlmResponse(text="No."),
    ])
    await _command(client, token, "reword it", session_id=chat)

    assert _tool_result(layer, "edit_narrative")["ok"] is False
    async with SessionLocal() as db:
        after = (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().first()
    assert after.content_md == before, (
        "an MOU conversation rewrote an unrelated proposal")


async def test_a_proposal_conversation_can_still_edit_its_narrative(
    client, org_a, agent_model, fill_model
):
    """The guard must not cost the proposal flow its editing tools."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "AMOUH")
    template = await _upload(client, token, program_id, _proposal_docx(),
                             "proposal")
    lead_id = (await fresh_lead(client, token, "Orchid AH"))["id"]
    await open_lead(client, token, lead_id)
    async with SessionLocal() as db:
        proposal = Proposal(
            org_id=org_a["id"], lead_id=lead_id, program_id=program_id,
            title="An ordinary proposal", content_md="The original wording",
            template_id=template["id"], template_version=1,
            template_kind="markdown", created_by="u" * 32,
        )
        db.add(proposal)
        await db.commit()
        proposal_id = proposal.id

    async def _rewrite(_ctx, content_md, instruction):
        return "A warmer wording"

    monkey = pa.rewrite_narrative
    pa.rewrite_narrative = _rewrite
    try:
        layer = agent_model([
            _call("edit_narrative", instruction="warmer",
                  proposal_ref=proposal_id),
            LlmResponse(text="Done."),
        ])
        await _command(client, token, "warmer", session_id="chat-amouh")
    finally:
        pa.rewrite_narrative = monkey

    assert _tool_result(layer, "edit_narrative")["updated"] is True


# --- D-E's approval gate (plan amendment D) ----------------------------------


PRICED = {"<ask_calculate:Rs. 4000>": "Rs. 4000",
          "<ask:75>": "75",
          "<ask_calculate:Rs. 3,00,000>": "Rs. 2,50,000/- Net"}


def _relation(docx_bytes):
    ids = {o.raw: o.tag_id for o in dtags.scan(docx_bytes)}
    return [{"result": ids["<ask_calculate:Rs. 3,00,000>"], "op": "product",
             "operands": [ids["<ask_calculate:Rs. 4000>"], ids["<ask:75>"]]}]


async def _mismatched(client, token, code, name, agent_model, fill_model):
    docx = _priced_mou_docx()
    return await _answered(client, token, code, name, agent_model, fill_model,
                           docx=docx, answers=PRICED,
                           relations=_relation(docx))


async def test_the_review_says_which_two_figures_disagree(
    client, org_a, agent_model, fill_model
):
    """F2 produces a sentence naming the two figures. Until A2 the review
    printed "it reads like a price, and prices normally come from the rate
    card" INSTEAD, discarding it -- which hides the only thing D-E does."""
    token = org_a["admin_token"]
    chat, session, _lead = await _mismatched(
        client, token, "AMOUI", "Orchid AI", agent_model, fill_model)

    message = pa._review_message(session)
    assert "2,50,000" in message and "3,00,000" in message
    assert "rate card" not in message, (
        "the arithmetic finding was replaced by the price-drift wording")


async def test_an_approval_with_a_mismatch_standing_is_refused_once(
    client, org_a, agent_model, fill_model, no_pdf
):
    token = org_a["admin_token"]
    chat, _session, lead_id = await _mismatched(
        client, token, "AMOUJ", "Orchid AJ", agent_model, fill_model)

    layer = agent_model([_call("confirm_mou_values", approved=True),
                         LlmResponse(text="Have a look at this first.")])
    await _command(client, token, "yes", session_id=chat)
    first = _tool_result(layer, "confirm_mou_values")
    assert first["ok"] is False
    assert "3,00,000" in first["message"]
    async with SessionLocal() as db:
        assert (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all() == []

    layer = agent_model([_call("confirm_mou_values", approved=True),
                         LlmResponse(text="Done.")])
    await _command(client, token, "yes I mean it", session_id=chat)
    second = _tool_result(layer, "confirm_mou_values")
    assert second.get("created") is True
    async with SessionLocal() as db:
        built = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().all()
    assert len(built) == 1


async def test_the_value_written_is_exactly_what_the_person_typed(
    client, org_a, agent_model, fill_model, no_pdf
):
    """D15. The check reports; it NEVER substitutes its own figure."""
    token = org_a["admin_token"]
    chat, _session, lead_id = await _mismatched(
        client, token, "AMOUK", "Orchid AK", agent_model, fill_model)
    for text in ("yes", "yes I mean it"):
        agent_model([_call("confirm_mou_values", approved=True),
                     LlmResponse(text="ok")])
        await _command(client, token, text, session_id=chat)

    async with SessionLocal() as db:
        mou = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().first()
    assert "2,50,000" in mou.content_md
    assert "3,00,000" not in mou.content_md


async def test_correcting_an_operand_clears_the_acknowledgement(
    client, org_a, agent_model, fill_model
):
    """A figure that has just changed has not been acknowledged since -- the
    same rule `_record` already applies to `reviewed`."""
    token = org_a["admin_token"]
    docx = _priced_mou_docx()
    chat, session, _lead = await _mismatched(
        client, token, "AMOUL", "Orchid AL", agent_model, fill_model)

    agent_model([_call("confirm_mou_values", approved=True),
                 LlmResponse(text="Have a look.")])
    await _command(client, token, "yes", session_id=chat)
    session = await _fill_for(chat)
    assert any(t.get("arithmetic_ack") for t in session.tags_json)

    ids = {o.raw: o.tag_id for o in dtags.scan(docx)}
    price = ids["<ask_calculate:Rs. 4000>"]

    async def _revise(_ctx, *, dossier, resolutions, correction):
        return [{"tag_id": price, "value": "Rs. 4500", "confidence": 1.0,
                 "reason": "corrected", "citation": "c"}]

    monkey = docx_tagfill.revise
    docx_tagfill.revise = _revise
    try:
        agent_model([_call("confirm_mou_values", approved=False,
                           correction="make the price 4500"),
                     LlmResponse(text="Updated.")])
        await _command(client, token, "make the price 4500", session_id=chat)
    finally:
        docx_tagfill.revise = monkey

    session = await _fill_for(chat)
    assert not any(t.get("arithmetic_ack") for t in session.tags_json), (
        "an acknowledgement survived the figure it acknowledged changing")


async def test_a_proposal_approval_is_never_gated_on_arithmetic(
    client, org_a, agent_model, fill_model, no_pdf
):
    """MOUs only. A proposal carries no relations, so the gate must be a
    no-op there rather than an extra tap on every proposal."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "AMOUM")
    await _upload(client, token, program_id, _proposal_docx(), "proposal")
    lead_id = (await fresh_lead(client, token, "Orchid AM"))["id"]
    await open_lead(client, token, lead_id)
    docx = _proposal_docx()
    fill_model(answers={"<School Name>": "Orchid AM", "<ask:1 Unit>": "2 Units"},
               tags=_tags_of(docx))
    agent_model([_call("create_proposal", client="Orchid AM", program="AMOUM"),
                 LlmResponse(text="A few details.")])
    await _command(client, token, "create it", session_id="chat-amoum")
    agent_model([_call("answer_proposal_questions", answer="two of each"),
                 LlmResponse(text="Noted.")])
    await _command(client, token, "two of each", session_id="chat-amoum")

    layer = agent_model([_call("confirm_proposal_values", approved=True),
                         LlmResponse(text="Done.")])
    await _command(client, token, "yes", session_id="chat-amoum")
    assert _tool_result(layer, "confirm_proposal_values")["created"] is True


# --- a reply must reach the fill, whatever the model does (D47) ---------------


async def test_a_reply_reaches_the_fill_even_when_the_model_calls_nothing(
    client, org_a, agent_model, fill_model
):
    """Nine of the owner's twenty answers reached no tool at all.

    Measured on the Orchid contract of 11 September: `asked_json` recorded
    ELEVEN rounds against twenty replies, and the turns in between are the
    model restating the question it had just been handed -- "The only
    remaining MoU question is ... Reply 'Innovation Nexus' to finish" -- while
    the fill sat untouched. The person reads that as being asked the same
    thing again, because it is.

    The prompt has told it to call `answer_mou_questions` since A2, and the
    loop-breaker in `_open_fill` catches the model reaching for `create_mou`
    instead. Neither catches the model reaching for NOTHING. A prompt is
    advice; while a fill is asking, a reply that ran no tool is passed to the
    answer tool here.
    """
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUNOTOOL", "Orchid NT",
                                       agent_model, fill_model)
    before = len(fs.open_questions(await _fill_for(chat), limit=None))
    assert before, "the fill had nothing outstanding for the reply to settle"

    # The measured failure: prose, and not one tool call.
    agent_model([LlmResponse(text="The only remaining question is the name.")])
    await _command(client, token, "All the suggested values are fine",
                   session_id=chat)

    after = len(fs.open_questions(await _fill_for(chat), limit=None))
    assert after < before, (
        "the reply never reached the fill: %d outstanding before, %d after"
        % (before, after))


async def test_the_forced_answer_is_the_persons_own_words(
    client, org_a, agent_model, fill_model
):
    """What reaches the fill is what they typed. Anything the model wrote in
    its place is a paraphrase of an answer, and D14 cites the person."""
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUWORDS", "Orchid W",
                                       agent_model, fill_model, chat="chat-mouwords")
    layer = agent_model([LlmResponse(text="Anything but a tool call.")])
    await _command(client, token, "two of each, and the date is 11.09.2026",
                   session_id=chat)
    session = await _fill_for(chat)
    assert session.asked_json[-1]["reply"] == \
        "two of each, and the date is 11.09.2026"
    assert _tool_result(layer, "answer_mou_questions")


async def test_a_turn_with_no_fill_open_runs_no_tool_of_its_own(
    client, org_a, agent_model, fill_model
):
    """The force is scoped to a fill that is ASKING. A conversation with none
    open is an ordinary turn, and inventing a tool call for one would answer
    questions nobody has asked."""
    token = org_a["admin_token"]
    await _ground(client, token, "MOUNONE", "Orchid None")
    layer = agent_model([LlmResponse(text="Nothing is open.")])
    await _command(client, token, "All the suggested values are fine",
                   session_id="chat-mounone")
    assert not any(
        message.get("role") == "tool_result"
        for call in layer.calls
        for message in (call.get("messages") or [])), \
        "a tool ran for a conversation with no fill open"


# --- the turn has to ASK, and the card is the question (D48) ------------------


async def test_a_reply_that_only_listed_the_questions_still_reaches_the_fill(
    client, org_a, agent_model, fill_model
):
    """The owner's 06:07:41 turn, on the run that had D47 in it.

    They said "All the suggested values are fine". The model called
    `show_mou_questions` -- a tool that lists and answers nothing -- so a tool
    HAD run, D47's force stood aside, and the answer was lost. The fill
    recorded seven rounds for nine replies.

    The rule is not "did a tool run" but "was the person asked anything". A
    turn that ends without a question card, while a fill is waiting on them,
    has not dealt with their reply.
    """
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUSHOWN", "Orchid Shown",
                                       agent_model, fill_model,
                                       chat="chat-shown")
    before = len(fs.open_questions(await _fill_for(chat), limit=None))
    agent_model([_call("show_mou_questions"),
                 LlmResponse(text="There are still some open.")])
    await _command(client, token, "All the suggested values are fine",
                   session_id=chat)
    after = len(fs.open_questions(await _fill_for(chat), limit=None))
    assert after < before, (
        "the reply was lost behind a tool that answers nothing: %d before, "
        "%d after" % (before, after))


async def test_a_turn_that_asked_the_person_something_is_left_alone(
    client, org_a, agent_model, fill_model
):
    """The other side of it. A turn that DID put a question card up has dealt
    with the reply, and forcing a second call would post the same words to the
    fill twice."""
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUASKED", "Orchid Asked",
                                       agent_model, fill_model,
                                       chat="chat-asked")
    agent_model([_call("answer_mou_questions", answer="two of each"),
                 LlmResponse(text="Noted.")])
    await _command(client, token, "two of each", session_id=chat)
    session = await _fill_for(chat)
    replies = [entry["reply"] for entry in session.asked_json]
    assert replies.count("two of each") == 1, (
        "the same reply reached the fill twice: %r" % (replies,))


async def test_a_reply_about_an_open_fill_is_never_routed_elsewhere(
    client, org_a, agent_model, fill_model
):
    """The owner's 06:08:15 turn. "Yes show the remaining" was routed to the
    QUERY agent, which has no MOU tools and no idea a document was open, and
    it improvised: "I can't see the MoU's remaining fields from here... where
    is the MoU form you're filling?"

    The router is a fast model choosing from one sentence and four quoted
    turns, and it falls back to `query` whenever it is unsure. While a
    document in this conversation is waiting on the person, the conversation
    belongs to the agent that owns it.
    """
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUROUTE", "Orchid Route",
                                       agent_model, fill_model,
                                       chat="chat-route")
    # The router runs on the same fake layer, so this IS the routing decision
    # it made on the owner's contract.
    agent_model([LlmResponse(text='{"agent": "query"}'),
                 LlmResponse(text="Anything at all.")])
    body = (await _command(client, token, "Yes show the remaining",
                           session_id=chat, agent=None)).json()
    assert body["agent"] == "proposal", (
        "a reply about the open contract was answered by the %s agent"
        % body["agent"])


async def test_a_conversation_with_no_open_fill_is_routed_normally(
    client, org_a, agent_model, fill_model
):
    """The guard. The override is scoped to a document that is actually
    waiting on someone -- otherwise every question a salesperson ever asked in
    a chat that once built a contract would reach the wrong agent."""
    token = org_a["admin_token"]
    await _ground(client, token, "MOUFREE", "Orchid Free")
    agent_model([LlmResponse(text='{"agent": "query"}'),
                 LlmResponse(text="Nothing is open.")])
    body = (await _command(client, token, "what do we know about them?",
                           session_id="chat-moufree", agent=None)).json()
    assert body["agent"] == "query"


async def test_the_question_card_is_the_question_and_the_prose_does_not_argue(
    client, org_a, agent_model, fill_model
):
    """The app draws the model's prose AND the card the tool built, and on the
    owner's contract they disagreed: the card asked for six things and the
    prose asked for two, on the same screen. The card is built from the
    document itself, so it is the question; the prose is cut to the card's own
    opening line and never re-lists the items."""
    token = org_a["admin_token"]
    _, body, _, _, _ = await _open_mou(client, token, "MOUCARD", "Orchid Card",
                                       agent_model, fill_model,
                                       chat="chat-card")
    asked = _asked(body)
    assert asked is not None
    assert body["reply"] == asked["question"].splitlines()[0]
    assert "A few details first." not in body["reply"], (
        "the model's own paraphrase is still the reply")


# --- a tool that could not act has not dealt with the reply (D49) ------------


async def test_a_reply_survives_a_fill_tool_that_could_not_act(
    client, org_a, agent_model, fill_model
):
    """The owner's 10:24 turn, on the run that had D47 and D48 in it.

    Mid-round they typed "Instead of 4k make it 9k" -- an answer to question
    one. The model reached for `correct_mou`, which edits a contract that has
    already been BUILT, and it failed: "There is no MOU from this conversation
    that I can correct." On the screen directly above, the card was asking
    them for four values.

    D48 stood the force down for any tool that COULD have acted on the words.
    This one could not, and said so. A tool that reports it could not act has
    not dealt with the reply, so the reply goes on to the tool that can.
    """
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUFAILED", "Orchid Failed",
                                       agent_model, fill_model,
                                       chat="chat-failed")
    before = len(fs.open_questions(await _fill_for(chat), limit=None))
    agent_model([_call("correct_mou", correction="Instead of 4k make it 9k"),
                 LlmResponse(text="There is no MOU to correct.")])
    await _command(client, token, "Instead of 4k make it 9k", session_id=chat)
    after = len(fs.open_questions(await _fill_for(chat), limit=None))
    assert after < before, (
        "the reply was lost behind a tool that refused it: %d before, %d after"
        % (before, after))


async def test_a_reply_survives_an_approval_the_fill_is_not_ready_for(
    client, org_a, agent_model, fill_model, no_pdf
):
    """The same shape, and the one that cost the owner a turn at 10:21:49.

    They said "All the suggested values are fine"; the model read the round's
    own tap as an approval and called `confirm_mou_values`, which returned its
    D44 redirect -- correctly, and without building anything. The words were
    then dropped, and they had to type "Answer the remaining questions" to get
    the same round back.

    **This narrows D44 rather than overturning it.** The wrong tool is still
    harmless: it refuses, it builds nothing, and D13's review still stands
    between every value and the document. What changes is that the sentence
    the tool itself says to pass on IS passed on, in the same turn.
    """
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUEARLY", "Orchid E",
                                       agent_model, fill_model,
                                       chat="chat-early")
    before = len(fs.open_questions(await _fill_for(chat), limit=None))
    layer = agent_model([_call("confirm_mou_values", approved=True),
                         LlmResponse(text="Noted.")])
    await _command(client, token, "All the suggested values are fine",
                   session_id=chat)

    result = _tool_result(layer, "confirm_mou_values")
    assert result.get("still_asking") is True, result
    assert "answer_mou_questions" in result["what_to_do"]
    after = len(fs.open_questions(await _fill_for(chat), limit=None))
    assert after < before, (
        "the tool said to pass their words on and nothing did: %d before, "
        "%d after" % (before, after))
    async with SessionLocal() as db:
        assert (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == (await _fill_for(chat)).lead_id
        ))).scalars().first() is None, "an early approval built a document"


async def test_a_tool_that_did_act_still_stands_the_force_down(
    client, org_a, agent_model, fill_model
):
    """The guard. A tool that answered the round has had the reply, and
    forcing a second call would post the same words to the fill twice."""
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUACTED", "Orchid Act",
                                       agent_model, fill_model,
                                       chat="chat-acted")
    agent_model([_call("answer_mou_questions", answer="two of each"),
                 LlmResponse(text="Noted.")])
    await _command(client, token, "two of each", session_id=chat)
    replies = [e["reply"] for e in (await _fill_for(chat)).asked_json]
    assert replies.count("two of each") == 1, (
        "the same reply reached the fill twice: %r" % (replies,))


async def test_an_approval_that_built_the_document_is_not_asked_again(
    client, org_a, agent_model, fill_model, no_pdf
):
    """The other side of D49, and the one a mutation found nothing pinning.

    A fill tool that ACTED has had the reply. `confirm_mou_values` with every
    question answered builds the contract and returns -- it asks nothing, so
    the "was the person asked anything" fence does not catch it. If the force
    fired anyway, the approval would be posted to `answer_mou_questions`,
    which refuses a fill that is no longer resumable: an error in the app, on
    the turn that just produced the document.
    """
    token = org_a["admin_token"]
    _, _, chat, _, lead_id = await _open_mou(client, token, "MOUBUILT",
                                             "Orchid Built", agent_model,
                                             fill_model, chat="chat-built")
    agent_model([_call("answer_mou_questions", answer="all of them are fine"),
                 LlmResponse(text="Here is everything.")])
    await _command(client, token, "all of them are fine", session_id=chat)
    rounds = len((await _fill_for(chat)).asked_json)

    layer = agent_model([_call("confirm_mou_values", approved=True),
                         LlmResponse(text="Built.")])
    await _command(client, token, "Yes, these are all correct", session_id=chat)

    assert _tool_result(layer, "confirm_mou_values")["created"] is True
    session = await _fill_for(chat)
    assert len(session.asked_json) == rounds, (
        "the approval was posted to the fill as an answer: %r"
        % ([e["reply"] for e in session.asked_json],))
    async with SessionLocal() as db:
        built = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().first()
    assert built is not None, "the approval did not build the contract"


# --- the other document's tools must not look like a dead end (D50) ----------


async def test_a_proposal_tool_on_a_contract_names_the_contracts_tool(
    client, org_a, agent_model, fill_model
):
    """The owner's 13:52 turn. They tapped "Yes, these are all correct" on the
    review; the model called `confirm_proposal_values`; and the answer they
    got was "there isn't a proposal draft currently open in this conversation
    ... what client name and programme should I create the proposal for?"

    There was no proposal. There was a CONTRACT, finished, waiting on that
    exact tap. A tool that cannot act must say what IS open and name the tool
    that can -- the same rule `create_*` has followed since A2, applied to the
    three tools that had not.
    """
    token = org_a["admin_token"]
    _, _, chat, _, _ = await _open_mou(client, token, "MOUOTHER", "Orchid O",
                                       agent_model, fill_model,
                                       chat="chat-other")
    layer = agent_model([_call("confirm_proposal_values", approved=True),
                         LlmResponse(text="Something went wrong.")])
    await _command(client, token, "Yes, these are all correct",
                   session_id=chat)

    said = str(_tool_result(layer, "confirm_proposal_values"))
    # This contract is still ASKING, so the tool that moves it on is the
    # answer tool. A contract at its review names the confirm tool instead,
    # which test_an_approval_reaches_the_right_document walks through.
    assert "answer_mou_questions" in said, said
    assert "MOU" in said, said
    assert "Ask me to create one" not in said, (
        "it still tells them to create the document they already have")


async def test_an_approval_reaches_the_right_document(
    client, org_a, agent_model, fill_model, no_pdf
):
    """And the tap itself must survive the wrong tool.

    At the review there is nothing left to answer, so D48's force -- which
    only runs while a fill is ASKING -- left this turn with nowhere to go and
    the owner stuck on a finished contract. The approval they actually gave
    now reaches the document it was about.

    **Only the review's own words.** This is the one tool that writes a
    client-facing file, so what carries it is an exact match on the phrase the
    review offered, not the model's reading of a sentence.
    """
    token = org_a["admin_token"]
    _, _, chat, _, lead_id = await _open_mou(client, token, "MOUAPPROVE",
                                             "Orchid Ap", agent_model,
                                             fill_model, chat="chat-approve")
    agent_model([_call("answer_mou_questions", answer="all of them are fine"),
                 LlmResponse(text="Here is everything.")])
    await _command(client, token, "all of them are fine", session_id=chat)
    assert (await _fill_for(chat)).status == FillStatus.REVIEWING

    agent_model([_call("confirm_proposal_values", approved=True),
                 LlmResponse(text="I could not find a proposal.")])
    await _command(client, token, "Yes, these are all correct",
                   session_id=chat)

    async with SessionLocal() as db:
        built = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().first()
    assert built is not None, (
        "the approval was lost on the wrong tool and the contract was never "
        "written")


async def test_anything_but_the_approval_never_builds_by_itself(
    client, org_a, agent_model, fill_model, no_pdf
):
    """The guard, and the reason the match is exact. A person at the review
    who says something else is asking for a CHANGE, and a document written
    from that would be one nobody approved."""
    token = org_a["admin_token"]
    _, _, chat, _, lead_id = await _open_mou(client, token, "MOUNOAPP",
                                             "Orchid Na", agent_model,
                                             fill_model, chat="chat-noapp")
    agent_model([_call("answer_mou_questions", answer="all of them are fine"),
                 LlmResponse(text="Here is everything.")])
    await _command(client, token, "all of them are fine", session_id=chat)
    assert (await _fill_for(chat)).status == FillStatus.REVIEWING

    agent_model([LlmResponse(text="Anything at all, and no tool.")])
    await _command(client, token, "the date should be the first of March",
                   session_id=chat)

    async with SessionLocal() as db:
        built = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().first()
    assert built is None, "a sentence that was not the approval built a document"
    assert (await _fill_for(chat)).status == FillStatus.REVIEWING


async def test_the_approval_is_read_as_a_person_reads_it(
    client, org_a, agent_model, fill_model, no_pdf
):
    """Case and stray spaces are not a decision anybody made. A tap that
    arrived lower-cased, or with a space on the end from a keyboard, is the
    same approval the review offered -- and being strict about it would
    leave the person exactly where D50 found them, tapping a button that
    does nothing."""
    token = org_a["admin_token"]
    _, _, chat, _, lead_id = await _open_mou(client, token, "MOUCASE",
                                             "Orchid Ca", agent_model,
                                             fill_model, chat="chat-case")
    agent_model([_call("answer_mou_questions", answer="all of them are fine"),
                 LlmResponse(text="Here is everything.")])
    await _command(client, token, "all of them are fine", session_id=chat)

    agent_model([LlmResponse(text="No tool at all.")])
    await _command(client, token, "  yes, THESE are all correct ",
                   session_id=chat)

    async with SessionLocal() as db:
        built = (await db.execute(select(MouDocument).where(
            MouDocument.lead_id == lead_id))).scalars().first()
    assert built is not None, "the same words, differently typed, did nothing"
