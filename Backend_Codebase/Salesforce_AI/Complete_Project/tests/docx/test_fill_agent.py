# tests/docx/test_fill_agent.py
"""Asking for a simple-flow proposal starts a conversation (Task J1).

Driven the way `tests/test_assistant.py` drives every other agent: a scripted
model layer runs the real tool loop against the real database, through the
real `/assistant/command` route. Two fakes are needed, because two different
models are involved -- the agent's, which decides which tool to call, and the
fill pass's in `docx_tagfill`, which decides what each tag means.

What this task does NOT do is produce a document. J2 owns the review and the
build; here the fill ends in `reviewing`, with every value waiting for a human
to see it (D13).
"""
import io

import pytest
from docx import Document
from sqlalchemy import select

from app.ai import docx_tagfill
from app.ai import llm as llm_mod
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal
from app.models.program import ProposalTemplate, ProposalTemplateDoc
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from tests.conftest import auth, open_lead

API = "/api/v1"
pytestmark = pytest.mark.asyncio


def _tagged_docx() -> bytes:
    """One semantic tag and seven that must always be asked."""
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    items = ("Laptops", "Interactive Panel", "Magazine Rack", "Projector",
             "3D Printer", "Drone Kit", "Safety Glasses")
    t = doc.add_table(rows=len(items) + 1, cols=2)
    t.cell(0, 0).text = "Description"
    t.cell(0, 1).text = "Estimation"
    for row, item in enumerate(items, start=1):
        t.cell(row, 0).text = item
        t.cell(row, 1).text = "<ask:1 Unit>"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _plain_docx() -> bytes:
    """No tags: the complex flow's shape, for the branch that must not change."""
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("School Name")
    doc.add_paragraph("A body paragraph long enough to serve as a style reference.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


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
    """The fill pass's model: one scripted reply per resolve/answer call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0) if self.replies else {"resolutions": []}


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


async def _program(client, token, name, code) -> str:
    return (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": name, "code": code, "description": "d"},
    )).json()["id"]


async def _upload(client, token, program_id, data, flow) -> str:
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Tagged", "make_current": "true", "flow": flow},
        files={"file": ("t.docx", data,
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _pricing(client, token, program_id) -> None:
    """Every proposal still needs a rate card (D16), simple flow included."""
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/pricing", headers=auth(token),
        json={"currency": "INR", "make_current": True,
              "items": [{"code": "LAB", "label": "Innovation Lab",
                         "unit": "lab", "unit_price": 250000}]},
    )
    assert resp.status_code == 200, resp.text


async def _ground(client, token, code, lead_name, *, tagged=True):
    program_id = await _program(client, token, f"Fill {code}", code)
    await _upload(client, token, program_id,
                  _tagged_docx() if tagged else _plain_docx(),
                  "simple" if tagged else "complex")
    await _pricing(client, token, program_id)
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": lead_name})).json()["id"]
    # Jarvis makes no proposal for a lead still in cold calling.
    await open_lead(client, token, lead_id)
    return program_id, lead_id


async def _plan_tags(program_id: str) -> list[dict]:
    async with SessionLocal() as db:
        template = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.program_id == program_id,
            ProposalTemplate.is_current.is_(True),
        ))).scalars().first()
        row = (await db.execute(select(ProposalTemplateDoc).where(
            ProposalTemplateDoc.template_id == template.id))).scalar_one()
    return (row.plan_json or {}).get("tags") or []


async def _command(client, token, text, *, session_id, agent="proposal"):
    return await client.post(
        f"{API}/assistant/command", headers=auth(token),
        json={"text": text, "agent": agent, "session_id": session_id},
    )


def _asked(body) -> dict | None:
    """The question the tool loop raised, as the app receives it."""
    for action in body["actions"]:
        if action.get("outcome") == "needs_confirmation":
            return action
    return None


def _tool_result(layer: "FakeModelLayer", tool: str):
    """What the agent loop actually handed back to the model.

    The `actions` list carries a truncated preview for the app; this is the
    real thing, and it is what the model's next turn was written against.
    """
    for call in layer.calls:
        for message in call.get("messages") or []:
            if message.get("role") == "tool_result" and message.get("name") == tool:
                return message["result"]
    raise AssertionError(f"the model was never given a result for {tool}")


def _values(session):
    """What a fill actually SAYS: every tag, its outcome and its value.

    Not the whole record. The answer pass re-words an open question it could
    not settle -- D46, keeping the re-ask narrower than the question before it
    -- so comparing records whole would call a reworded question a changed
    document. Nothing but values is ever written into one.
    """
    return [(t["tag_id"], t["outcome"], t.get("value"))
            for t in session.tags_json]


async def _fill_for(chat: str) -> ProposalFillSession | None:
    async with SessionLocal() as db:
        return (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat
        ))).scalars().first()


# --- the conversation --------------------------------------------------------


async def test_asking_for_a_simple_flow_proposal_asks_questions_instead(
        client, org_a, agent_model, fill_model):
    """Amendment D: B1's loud refusal must be REPLACED by this conversation.
    The salesperson is already talking to Jarvis, so being told to "ask Jarvis"
    would be the one reply that cannot possibly help."""
    token = org_a["admin_token"]
    program_id, _ = await _ground(client, token, "JONEA", "Orchid J1A")
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1A", "program": "JONEA"})]),
        LlmResponse(text="I need a few details before I can fill the document."),
    ])

    resp = await _command(client, token, "create a proposal for Orchid J1A "
                          "for JONEA", session_id="chat-j1a")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    asked = _asked(body)
    assert asked is not None, body["actions"]
    assert asked["tool"] == "create_proposal"
    assert "ask Jarvis" not in (asked["question"] or "")
    assert "not built from here" not in (asked["question"] or "")


async def test_the_first_round_is_six_questions_with_their_defaults(
        client, org_a, agent_model, fill_model):
    """D5. Eight tags would be eight round trips; six per round makes it two."""
    token = org_a["admin_token"]
    program_id, _ = await _ground(client, token, "JONEB", "Orchid J1B")
    # The model writes its OWN questions here, quoting neither the tag nor the
    # row label. C2's fallback question would contain both, so a message that
    # merely echoed it would pass every assertion below without the round
    # having named the item or the suggestion itself.
    fill_model({"resolutions": [
        {"tag_id": tag["tag_id"], "question": "How many of these do you want?"}
        for tag in await _plan_tags(program_id)
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1B", "program": "JONEB"})]),
        LlmResponse(text="A few details first."),
    ])

    body = (await _command(client, token, "create the JONEB proposal",
                           session_id="chat-j1b")).json()

    asked = _asked(body)
    question = asked["question"]
    assert fs.QUESTIONS_PER_ROUND == 6
    # Exactly one round in one message -- not one message per question, and
    # not all eight at once.
    assert "6. " in question and "7. " not in question
    # Each line names the cell it is about (D9's row label) and the value the
    # template's author suggested, neither of which is in the model's question.
    assert "Laptops" in question and "Interactive Panel" in question
    assert "the template suggests 1 Unit" in question
    # D5's taps: the author's suggestion, and the answer that settles the round.
    assert "1 Unit" in asked["candidates"]
    assert any("suggested" in c.lower() for c in asked["candidates"])


async def test_an_answer_settles_questions_and_the_next_round_is_asked(
        client, org_a, agent_model, fill_model):
    token = org_a["admin_token"]
    program_id, _ = await _ground(client, token, "JONEC", "Orchid J1C")
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1C", "program": "JONEC"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the JONEC proposal",
                   session_id="chat-j1c")

    session = await _fill_for("chat-j1c")
    assert session is not None
    first_round = [q["tag_id"] for q in fs.open_questions(session)]

    fill_model({"resolutions": [
        {"tag_id": tag_id, "value": "2 Units", "reason": "two of each"}
        for tag_id in first_round
    ]})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="answer_proposal_questions",
                                         args={"answer": "two of each"})]),
        LlmResponse(text="Noted. Two more to go."),
    ])

    body = (await _command(client, token, "two of each",
                           session_id="chat-j1c")).json()

    asked = _asked(body)
    assert asked is not None and asked["tool"] == "answer_proposal_questions"
    session = await _fill_for("chat-j1c")
    assert len(fs.open_questions(session, limit=None)) == 2
    assert len(session.asked_json) == 1


async def test_a_whole_fill_runs_inside_one_session_id(
        client, org_a, agent_model, fill_model):
    """The end-to-end J1 owns: create, asked, answered, answered, and the fill
    is complete and waiting for its review. The document itself is J2's."""
    token = org_a["admin_token"]
    await _ground(client, token, "JONED", "Orchid J1D")
    chat = "chat-j1d"

    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1D", "program": "JONED"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the JONED proposal", session_id=chat)

    for reply in ("two of each", "one of the rest"):
        session = await _fill_for(chat)
        outstanding = [q["tag_id"] for q in fs.open_questions(session, limit=None)]
        fill_model({"resolutions": [
            {"tag_id": tag_id, "value": "2 Units", "reason": reply}
            for tag_id in outstanding
        ]})
        agent_model([
            LlmResponse(tool_calls=[ToolCall(name="answer_proposal_questions",
                                             args={"answer": reply})]),
            LlmResponse(text="Noted."),
        ])
        await _command(client, token, reply, session_id=chat)

    session = await _fill_for(chat)
    assert fs.open_questions(session, limit=None) == []
    assert session.status == FillStatus.REVIEWING
    assert all(t["value"] for t in session.tags_json)

    # Nothing has been written. J2 posts the review and builds the document.
    assert session.status != FillStatus.READY
    assert session.proposal_id is None
    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == session.lead_id))).scalars().all()
    assert proposals == []


async def test_a_second_request_resumes_the_same_fill(
        client, org_a, agent_model, fill_model):
    """Section 7: "actually make it 3 units" an hour later lands on the right
    fill. Opening a second one would ask every question again and lose the
    answers already given."""
    token = org_a["admin_token"]
    await _ground(client, token, "JONEE", "Orchid J1E")
    chat = "chat-j1e"

    for _ in range(2):
        fill_model({"resolutions": []})
        agent_model([
            LlmResponse(tool_calls=[ToolCall(
                name="create_proposal",
                args={"client": "Orchid J1E", "program": "JONEE"})]),
            LlmResponse(text="A few details first."),
        ])
        await _command(client, token, "create the JONEE proposal",
                       session_id=chat)

    async with SessionLocal() as db:
        rows = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat))).scalars().all()
    assert len(rows) == 1


async def test_the_questions_can_be_shown_again_without_answering_them(
        client, org_a, agent_model, fill_model):
    token = org_a["admin_token"]
    await _ground(client, token, "JONEF", "Orchid J1F")
    chat = "chat-j1f"
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1F", "program": "JONEF"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the JONEF proposal", session_id=chat)

    before = await _fill_for(chat)
    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(name="show_proposal_questions", args={})]),
        LlmResponse(text="Here is what is still open."),
    ])
    body = (await _command(client, token, "what were you asking me?",
                           session_id=chat)).json()

    shown = [a for a in body["actions"] if a["tool"] == "show_proposal_questions"]
    assert shown and shown[0]["ok"] is True

    # Asserted on what the MODEL was handed, not on the action record: the
    # action carries `base._preview`, which truncates past 800 characters and
    # is documented as lossy in tests/test_action_preview_is_lossy.py.
    result = _tool_result(layer, "show_proposal_questions")
    assert result["remaining"] == 8
    assert len(result["questions"]) == fs.QUESTIONS_PER_ROUND
    assert all(q["tag_id"] and q["question"] for q in result["questions"])

    # D48: a tool that only LISTS has not dealt with the reply, so the turn
    # passes it on as well -- that is how "All the suggested values are fine"
    # was lost on the owner's contract. What showing the questions must never
    # do is change a value, and it does not.
    after = await _fill_for(chat)
    assert _values(after) == _values(before)
    assert len(fs.open_questions(after, limit=None)) == 8


async def test_each_question_says_where_in_the_document_it_is(
        client, org_a, agent_model, fill_model):
    """D9. A question carries the row label of the cell it sits in, and that
    label is the only thing telling four `<ask:1 Unit>` apart.

    Its neighbour above asserts `tag_id` and `question`; neither it nor
    anything else asserted `about` or `suggested`, so deleting the row label
    left the whole suite green while the app showed four identical questions.
    Found by mutating `fill_tools.question_line` after A1 moved it.
    """
    token = org_a["admin_token"]
    await _ground(client, token, "JONEK", "Orchid J1K")
    chat = "chat-j1k"
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1K", "program": "JONEK"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the JONEK proposal", session_id=chat)

    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(name="show_proposal_questions", args={})]),
        LlmResponse(text="Here is what is still open."),
    ])
    await _command(client, token, "what were you asking me?", session_id=chat)

    questions = _tool_result(layer, "show_proposal_questions")["questions"]
    assert all(q["about"] for q in questions), (
        "a question with no row label cannot be told from its neighbours")
    # The fixture's seven `<ask:1 Unit>` sit in seven named table rows, so the
    # labels are what make them seven different questions rather than one
    # asked seven times.
    labels = [q["about"] for q in questions]
    assert len(set(labels)) == len(labels)
    assert any(q["suggested"] for q in questions), (
        "the template's own suggestions are what the app offers as taps")


async def test_answering_when_no_fill_is_open_says_so_and_invents_nothing(
        client, org_a, agent_model, fill_model):
    token = org_a["admin_token"]
    await _ground(client, token, "JONEG", "Orchid J1G")
    layer = fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="answer_proposal_questions",
                                         args={"answer": "two of each"})]),
        LlmResponse(text="I do not have a proposal open."),
    ])

    body = (await _command(client, token, "two of each",
                           session_id="chat-j1g-empty")).json()

    failed = [a for a in body["actions"]
              if a["tool"] == "answer_proposal_questions"]
    assert failed and failed[0]["ok"] is False
    # The message must say what is actually wrong. Without the guard the tool
    # still fails -- on an AttributeError deep inside the service -- and `ok`
    # is False either way, so the error text is the only thing that tells the
    # two apart, and it is the only one a person could act on.
    assert "no proposal being filled" in failed[0]["error"]
    assert layer.calls == []
    async with SessionLocal() as db:
        rows = (await db.execute(select(ProposalFillSession))).scalars().all()
    assert all(r.chat_session_id != "chat-j1g-empty" for r in rows)


async def test_a_one_off_command_never_answers_a_fill_from_another_one(
        client, org_a, agent_model, fill_model):
    """A command with no session_id opens a fill whose chat id is null. Keying
    the lookup on the chat alone would then make every later one-off command
    an answer to it -- the one place in this feature where a null would be a
    wildcard rather than a value."""
    token = org_a["admin_token"]
    await _ground(client, token, "JONEI", "Orchid J1I")
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1I", "program": "JONEI"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the JONEI proposal", session_id=None)
    orphan = await _fill_for(None)
    assert orphan is not None

    layer = fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="answer_proposal_questions",
                                         args={"answer": "two of each"})]),
        LlmResponse(text="I do not have a proposal open."),
    ])
    body = (await _command(client, token, "two of each",
                           session_id=None)).json()

    failed = [a for a in body["actions"]
              if a["tool"] == "answer_proposal_questions"]
    assert failed and failed[0]["ok"] is False
    assert "no proposal being filled" in failed[0]["error"]
    assert layer.calls == []
    assert (await _fill_for(None)).asked_json == []


async def test_a_colleagues_fill_in_the_same_chat_id_is_not_answered(
        client, org_a, agent_model, fill_model):
    """Section 5 records `user_id` as "whose conversation this is". A chat id
    is minted by the client app, so it is not a thing to stake one
    salesperson's half-answered document on."""
    owner, colleague = org_a["admin_token"], org_a["agent_token"]
    await _ground(client, owner, "JONEJ", "Orchid J1J")
    chat = "chat-shared-id"
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1J", "program": "JONEJ"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, owner, "create the JONEJ proposal", session_id=chat)
    assert await _fill_for(chat) is not None

    layer = fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(name="answer_proposal_questions",
                                         args={"answer": "two of each"})]),
        LlmResponse(text="I do not have a proposal open."),
    ])
    body = (await _command(client, colleague, "two of each",
                           session_id=chat)).json()

    failed = [a for a in body["actions"]
              if a["tool"] == "answer_proposal_questions"]
    assert failed and failed[0]["ok"] is False
    assert "no proposal being filled" in failed[0]["error"]
    assert layer.calls == []
    assert (await _fill_for(chat)).asked_json == []


# --- what must not change ----------------------------------------------------


async def test_a_complex_flow_template_still_builds_immediately(
        client, org_a, agent_model, fill_model):
    """The other flow is untouched: no fill session, a real proposal, one
    tool call and no question."""
    token = org_a["admin_token"]
    await _ground(client, token, "JONEH", "Orchid J1H", tagged=False)
    layer = fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid J1H", "program": "JONEH"})]),
        LlmResponse(text="Created."),
    ])

    body = (await _command(client, token, "create the JONEH proposal",
                           session_id="chat-j1h")).json()

    created = [a for a in body["actions"] if a["tool"] == "create_proposal"]
    assert created and created[0]["ok"] is True, created
    assert created[0]["result"]["created"] is True
    assert _asked(body) is None
    assert layer.calls == []
    assert await _fill_for("chat-j1h") is None


async def test_asking_to_create_again_does_not_re_ask_the_same_round(
        client, org_a, agent_model, fill_model):
    """THE LOOP, observed in real use on 8 September and reported by the owner.

    The agent runs on the fast tier and was never told the fill conversation
    exists, so on every reply it called `create_proposal` again instead of
    `answer_proposal_questions`. `_open_fill` resumed the same session and
    re-raised the identical six questions -- forever. Six tool calls in the
    real transcript, all `create_proposal`, and the fill row's `asked_json`
    stayed empty the whole time.

    The prompt is half the fix and cannot be the whole of it: a prompt is
    advice to a model, and this one is small and fast. So resuming a fill that
    still has open questions must not LOOK like progress. It returns and says
    what to call instead, which the model reads as a tool result rather than
    as advice.
    """
    token = org_a["admin_token"]
    await _ground(client, token, "JLOOP", "Orchid Loop")
    chat = "chat-loop"

    fill_model({"resolutions": []})
    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid Loop", "program": "JLOOP"})]),
        LlmResponse(text="A few details first."),
    ])
    first = (await _command(client, token, "create the JLOOP proposal",
                            session_id=chat)).json()
    assert _asked(first) is not None, "the first ask must still happen"

    # The user answers, and the model gets it wrong exactly as it did in the
    # real transcript: it calls create_proposal again.
    fill_model({"resolutions": []})
    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid Loop", "program": "JLOOP"})]),
        LlmResponse(text="Right."),
    ])
    second = (await _command(client, token, "all the suggested values are fine",
                             session_id=chat)).json()

    # It must not re-ask THE SAME ROUND -- that is what looked like progress
    # and was not. It does ask again, and that is the difference D49 makes: the
    # reply was carried through to the answer tool, the round it answered is
    # gone, and what is on screen now is the NEXT one. Before D49 the words
    # were dropped here and the person said them twice.
    result = _tool_result(layer, "create_proposal")
    assert result["already_open"] is True
    assert result["still_to_answer"] == 8
    # And it must name the way out, because the model's next move is chosen
    # from what this result says.
    assert "answer_proposal_questions" in result["what_to_do"]

    # Still one fill, and it was not disturbed.
    async with SessionLocal() as db:
        rows = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat))).scalars().all()
    assert len(rows) == 1
    # The fake answers nothing, so the COUNT cannot move; what must be
    # true is that the words reached the fill at all, which is the round
    # recorded against them.
    assert [e["reply"] for e in rows[0].asked_json] == [
        "all the suggested values are fine"], (
        "the reply was thrown away: it reached the fill as no round at all")
    assert len(fs.open_questions(rows[0], limit=None)) == 8


async def test_approving_while_questions_are_open_names_the_answer_tool(
        client, org_a, agent_model, fill_model):
    """The crash the Orchid contract hit, in the proposal flow that shares
    `_confirm_values`: an approval arriving with questions still open raised
    "has not been through its review yet" instead of saying what to do. It
    returns now, and names the PROPOSAL's answer tool, not the contract's."""
    token = org_a["admin_token"]
    _program_id, lead_id = await _ground(client, token, "JOKAY", "Orchid Okay")
    chat = "chat-okay"
    fill_model({"resolutions": []})
    agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="create_proposal",
            args={"client": "Orchid Okay", "program": "JOKAY"})]),
        LlmResponse(text="A few details first."),
    ])
    await _command(client, token, "create the JOKAY proposal", session_id=chat)

    layer = agent_model([
        LlmResponse(tool_calls=[ToolCall(
            name="confirm_proposal_values", args={"approved": True})]),
        LlmResponse(text="Noted."),
    ])
    await _command(client, token, "All the suggested values are fine",
                   session_id=chat)

    result = _tool_result(layer, "confirm_proposal_values")
    assert result.get("still_asking") is True, result
    assert result["still_to_answer"] == 8
    assert "answer_proposal_questions" in result["what_to_do"]
    assert (await _fill_for(chat)).status == FillStatus.ASKING
    async with SessionLocal() as db:
        assert (await db.execute(select(Proposal).where(
            Proposal.lead_id == lead_id))).scalars().all() == []


async def test_the_agent_is_told_the_fill_conversation_exists(client, org_a):
    """The other half. The tools were added in J1 and nothing ever told the
    agent when to use them -- the system prompt described only the build-and-
    send flow, which is why the model reached for `create_proposal` every
    time. Asserted on the prompt the model is actually given."""
    from app.ai.agents.proposal_agent import ProposalAgent

    prompt = ProposalAgent.system_prompt
    assert "answer_proposal_questions" in prompt
    assert "create_proposal" in prompt
    # It has to say WHEN, not merely that the tool exists.
    assert "again" in prompt.lower() or "already" in prompt.lower()
