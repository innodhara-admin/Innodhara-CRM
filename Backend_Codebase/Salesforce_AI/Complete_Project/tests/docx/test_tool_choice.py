# tests/docx/test_tool_choice.py
"""Does the model CHOOSE the right tool? (Task A3)

**The single most important test in this plan, and the one that did not
exist.** Every J1 and J2 test -- and every test in `test_mou_agent.py` --
writes `ToolCall(name="create_mou")` into a script and hands it to the agent.
That proves what happens WHEN a tool is called. It cannot prove that a model
WOULD call it, and that is exactly where the last session's conversation
broke: in real use the agent called `create_proposal` six times and
`answer_proposal_questions` zero, in front of the owner, while a green suite
said everything worked.

So the fake here is driven by the PROMPT IT IS HANDED, not by a script. It
reads the system prompt and the tool definitions the agent actually passes,
reads the conversation so far, and picks a tool. It is a crude stand-in for a
real model -- but crucially IT CAN BE WRONG, which a scripted call can never
be.

Its one rule is the lesson itself:

    A TOOL THE SYSTEM PROMPT DOES NOT MENTION IS A TOOL THE MODEL DOES NOT
    CALL.

That is not an arbitrary simplification. It is precisely the failure J1 shipped
-- the tools existed and the prompt never named them -- and modelling it is
what lets these tests go red when A2's paragraph is taken away. The last four
tests do exactly that: they revert the prompt and the router line and assert
the right tools become unreachable, because a test that cannot fail proves
nothing.

**This crude model is WRONG about the reply turn, and that is left standing on
purpose.** "this academic year" shares no words with `answer_mou_questions`,
so it reaches for `create_mou` again -- the September failure, reproduced from
first principles rather than described. What turns that into progress is not
the model's taste but A2's loop-breaker, which returns `already_open` and
names the tool that moves the fill on. Tuning the fake until it guessed right
would have thrown away the only test that spends that guarantee.
"""
import io
import re

import pytest
from docx import Document

from app.ai import docx_tagfill
from app.ai import orchestrator
from app.ai.agents import base as agent_base
from app.ai.agents.proposal_agent import ProposalAgent
from app.ai.llm import LlmResponse, ToolCall
from app.core.context import OrgContext
from tests.conftest import auth, open_lead

API = "/api/v1"

#: Words too common to say anything about which tool is meant.
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "call", "calls", "do",
    "for", "from", "has", "have", "in", "is", "it", "its", "of", "on", "one",
    "or", "so", "that", "the", "their", "them", "they", "this", "to", "use",
    "user", "was", "what", "when", "which", "who", "will", "with", "you",
    "your",
}
_WORD = re.compile(r"[a-z_][a-z_0-9]*")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


class PromptDrivenLayer:
    """A model that reads its instructions instead of being told the answer.

    Not a good model. A DEFENSIBLE one: it follows the system prompt, it can
    see the tools it was given, and it can pick the wrong one.

    The choice, in order:

    1. **Only tools the system prompt names are candidates.** This is the rule
       the whole task exists for. A tool the prompt never mentions is
       invisible, exactly as it was to the fast-tier model in September.
    2. Each candidate is scored on how much of the CONVERSATION its name and
       description share -- the user's words, and the names of tools already
       called, which is how "this conversation is about an MOU" survives from
       one turn to the next.
    3. A sentence of the prompt that mentions the tool AND something in the
       conversation is worth more than a description match, because a system
       prompt is an instruction and a tool description is a label.

    One tool call per user turn: once a result comes back it answers in prose,
    which is what the scripted layers in the other files do too.
    """

    def __init__(self):
        self.chosen: list[str] = []
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        messages = kwargs.get("messages") or []
        system = kwargs.get("system") or ""
        tools = kwargs.get("tools") or []
        if not tools:
            return LlmResponse(text="Nothing to do.")

        if messages and messages[-1].get("role") == "tool_result":
            # A TOOL RESULT IS FACT. If the result says which tool to call
            # instead -- which is exactly what A2's loop-breaker returns -- do
            # that, rather than deciding again from the same words that were
            # wrong the first time. This is the half of the design that
            # protects a model whose taste is poor, and it is the half no
            # scripted test can exercise.
            named = _tool_named_by(messages[-1], tools)
            if named is not None:
                self.chosen.append(named["name"])
                return LlmResponse(tool_calls=[ToolCall(
                    name=named["name"], args=_args_for(named, messages))])
            return LlmResponse(text="Done.")

        context = _words(" ".join(
            str(m.get("content") or "") for m in messages
        )) | {c.name for m in messages for c in (m.get("tool_calls") or [])} \
            | _words(" ".join(
                c.name for m in messages for c in (m.get("tool_calls") or [])))

        best, best_score = None, 0.0
        for tool in tools:
            # (1) the prompt has to have told the model this exists
            if tool["name"] not in system:
                continue
            score = len(context & (_words(tool["name"])
                                   | _words(tool["description"])))
            # (3) an instruction that ties this tool to what is being said
            for sentence in re.split(r"(?<=[.!?])\s+", system):
                if tool["name"] in sentence:
                    score += 3 * len(context & _words(sentence))
            if score > best_score:
                best, best_score = tool, score

        if best is None:
            return LlmResponse(text="I do not know how to do that.")
        self.chosen.append(best["name"])
        return LlmResponse(tool_calls=[
            ToolCall(name=best["name"], args=_args_for(best, messages))])

    async def generate_json(self, **kwargs):
        """The ROUTER's call: the same idea over the router prompt's own
        agent list, which it parses rather than being handed."""
        self.calls.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]

        # BOUNDED to the agent list. Without the split, the LAST agent's
        # description ran to the end of the prompt and swallowed the request
        # itself, so every request matched the last agent perfectly -- a fake
        # that always agreed with itself, which is the failure this whole file
        # exists to avoid.
        head = prompt.split("Request:", 1)[0].split("Agents:", 1)[1]
        # The history rides inside the same block, so it has to be cut off the
        # agent list before the list is parsed -- otherwise it lands in the
        # LAST agent's description and that agent wins every follow-up.
        marker = "Earlier in this same conversation"
        agents, _, earlier_text = head.partition(marker)
        request = _words(re.search(r'Request: "(.*)"', prompt).group(1))
        # The prompt itself says a short follow-up continues the earlier work,
        # so the history counts -- at half weight, because "this academic year"
        # is about whatever was being discussed and not about itself.
        earlier = _words(earlier_text)

        best, best_score = "query", 0
        for name, description in re.findall(
                r"^- (\w+): (.*?)(?=^- \w+:|\Z)", agents, re.M | re.S):
            words = _words(description)
            score = 2 * len(request & words) + len(earlier & words)
            if score > best_score:
                best, best_score = name, score
        return {"agent": best, "reason": "matched the agent's own description"}


def _tool_named_by(tool_result, tools):
    """The tool a result tells the model to call instead, if it does.

    A2's loop-breaker returns `what_to_do` naming the tool that moves the fill
    on -- and the tool NOT to call again, which is why the one just called is
    excluded here rather than matched first.
    """
    result = tool_result.get("result")
    if not isinstance(result, dict):
        return None
    advice = str(result.get("what_to_do") or "")
    if not advice:
        return None
    just_called = tool_result.get("name")
    for tool in tools:
        if tool["name"] != just_called and tool["name"] in advice:
            return tool
    return None


def _args_for(tool, messages) -> dict:
    """Fill the tool's required arguments from the conversation.

    Crude on purpose: WHICH tool the model picks is the subject here, and a
    fake that got the arguments wrong would fail these tests for a reason
    nobody is asking about.
    """
    said = next((str(m.get("content") or "") for m in reversed(messages)
                 if m.get("role") == "user"), "")
    required = (tool.get("parameters") or {}).get("required") or []
    args = {}
    for name in required:
        args[name] = {"client": CLIENT, "program": CODE}.get(name, said)
    if "approved" in ((tool.get("parameters") or {}).get("properties") or {}) \
            and not required:
        args["approved"] = True
    return args


CODE = "A3MOU"
#: Unique to this file ON PURPOSE. "Sandur Education Centre" is also created
#: by test_mou_fill.py and test_mou_models.py, and with three leads of that
#: name `resolve_lead` is ambiguous -- so create_mou failed, no fill was
#: opened, and these tests passed alone and failed in the suite.
CLIENT = "Aurora Public School A3"


# --- grounding ----------------------------------------------------------------


def _mou_docx() -> bytes:
    doc = Document()
    doc.add_heading("Memorandum of Understanding", level=1)
    doc.add_paragraph(
        "Between <School Name> and YuviPep, a body paragraph long enough to "
        "serve as a style reference.")
    doc.add_paragraph("The programme runs for <ask:one academic year>.")
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


class FillLayer:
    def __init__(self, answers, tags):
        self.answers, self.tags = answers, tags

    async def generate_json(self, **kwargs):
        if "ARITHMETICALLY RELATED" in kwargs["messages"][-1]["content"]:
            return {"relations": []}
        return {"resolutions": [
            {"tag_id": t["tag_id"], "value": self.answers[t["raw"]],
             "confidence": 1.0, "citation": "turn 1", "reason": "said so"}
            for t in self.tags if t["raw"] in self.answers]}


ANSWERS = {"<School Name>": "Sandur Education Centre",
           "<ask:one academic year>": "AY 2026-27",
           "<ask:1 Unit>": "2 Units"}


@pytest.fixture
def choosing(monkeypatch):
    """Install the prompt-driven model for BOTH the agent and the router."""
    from app.services.docx import tags as dtags
    from app.services import proposal_fill_service as fs

    layer = PromptDrivenLayer()
    monkeypatch.setattr(agent_base, "get_model_layer", lambda: layer)
    monkeypatch.setattr("app.ai.orchestrator.get_model_layer", lambda: layer,
                        raising=True)
    tags = [o.as_dict() for o in dtags.scan(_mou_docx())] \
        + [o.as_dict() for o in dtags.scan(_proposal_docx())]
    monkeypatch.setattr(docx_tagfill, "get_model_layer",
                        lambda: FillLayer(ANSWERS, tags))
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-stub")
    return layer


async def _fills_for(chat: str, document_type: str):
    """The fills of one kind this conversation has opened."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.proposal_fill import ProposalFillSession

    async with SessionLocal() as db:
        return (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat,
            ProposalFillSession.document_type == document_type,
        ))).scalars().all()


async def _ground(client, token):
    """One programme carrying both templates, and one lead.

    IDEMPOTENT: the database persists across the tests in this module, so the
    second test to ask for this programme is handed the one the first made.
    A fresh code per test would work too, but every test here says the same
    sentence to the model, and the sentence is the subject.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.program import Program

    async with SessionLocal() as db:
        existing = (await db.execute(select(Program).where(
            Program.code == CODE))).scalars().first()
        if existing is not None:
            return existing.id

    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"Innovation {CODE}", "code": CODE,
              "description": "d"})).json()
    assert "id" in program, program
    for data, document_type in ((_mou_docx(), "mou"),
                                (_proposal_docx(), "proposal")):
        resp = await client.post(
            f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
            headers=auth(token),
            data={"name": document_type, "make_current": "true",
                  "flow": "simple", "document_type": document_type},
            files={"file": ("t.docx", data,
                            "application/vnd.openxmlformats-officedocument"
                            ".wordprocessingml.document")})
        assert resp.status_code == 200, resp.text
    lead = await client.post(f"{API}/leads", headers=auth(token),
                             json={"name": CLIENT})
    # Jarvis makes no MOU or proposal for a lead still in cold calling.
    await open_lead(client, token, lead.json()["id"])
    return program["id"]


async def _say(client, token, text, *, chat):
    """One turn, THROUGH THE ROUTER -- no `agent` is forced, because which
    agent gets the request is half of what is being tested."""
    return await client.post(
        f"{API}/assistant/command", headers=auth(token),
        json={"text": text, "session_id": chat})


# --- the choice ---------------------------------------------------------------


async def test_create_the_mou_reaches_the_mou_tools(client, org_a, choosing):
    """Nothing here says `create_mou`. The model is asked, and it picks."""
    token = org_a["admin_token"]
    await _ground(client, token)

    await _say(client, token, f"create the {CODE} MOU for {CLIENT}",
               chat="chat-a3one")

    assert choosing.chosen, "the model called no tool at all"
    assert choosing.chosen[0] == "create_mou"
    assert "create_proposal" not in choosing.chosen


async def test_a_reply_reaches_answer_mou_questions_even_when_the_model_reaches_wrong(
    client, org_a, choosing
):
    """THE DEFECT AND ITS CURE, in one test.

    This crude model DOES reach for `create_mou` on the reply -- "this
    academic year, Sandur Education Centre" shares no words with
    `answer_mou_questions`, and a bag of words cannot tell a follow-up from a
    fresh request. That is not a flaw in the fixture. It is the September
    failure, reproduced: the real model reached for `create_proposal` six
    times for the same reason.

    What stops it is not taste, it is A2's LOOP-BREAKER. `create_mou` on an
    open fill returns `already_open` and names `answer_mou_questions`, and the
    turn then reaches the right tool. A prompt is advice; a tool result is
    fact -- and this is the test that spends the fact.
    """
    token = org_a["admin_token"]
    await _ground(client, token)
    chat = "chat-a3two"

    await _say(client, token, f"create the {CODE} MOU for {CLIENT}", chat=chat)
    first = list(choosing.chosen)
    await _say(client, token, "this academic year, Aurora Public School A3",
               chat=chat)

    later = choosing.chosen[len(first):]
    assert later, "the reply reached no tool at all"
    assert "answer_mou_questions" in later, (
        "the turn never reached the tool that moves the fill on -- this is "
        "the September loop, and the loop-breaker did not break it")
    # It DOES reach for `create_proposal` here -- a bag of words cannot tell
    # a follow-up from a fresh request, which is the whole subject of this
    # file. What matters is that the wrong tool cost nothing (D44): no second
    # document was started, and the reply still reached the fill above.
    assert not await _fills_for(chat, "proposal"), (
        "a reply about a contract opened a proposal fill")


async def test_the_fill_is_never_opened_twice_however_often_the_model_asks(
    client, org_a, choosing
):
    """`create_mou` was called four times across this conversation before the
    loop-breaker was written -- the same shape as the six that reached the
    owner. What matters is that it never opened a second fill and never lost
    an answer: every one of those calls was turned into progress.
    """
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.proposal_fill import ProposalFillSession

    token = org_a["admin_token"]
    await _ground(client, token)
    chat = "chat-a3three"

    await _say(client, token, f"create the {CODE} MOU for {CLIENT}", chat=chat)
    for reply in ("this academic year, Aurora Public School A3",
                  "what were you asking me again?"):
        await _say(client, token, reply, chat=chat)

    async with SessionLocal() as db:
        fills = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.chat_session_id == chat))).scalars().all()
    assert len(fills) == 1, (
        "the conversation opened %d fills; every extra one throws away the "
        "answers already given" % len(fills))
    assert not fills[0].mou_id, "nothing was built without the D13 review"


async def test_a_proposal_request_still_reaches_the_proposal_tools(
    client, org_a, choosing
):
    """A2 must not have cost the proposal flow its own tools -- the whole
    reason one agent owns both documents."""
    token = org_a["admin_token"]
    await _ground(client, token)

    await _say(client, token, f"create the {CODE} proposal for {CLIENT}",
               chat="chat-a3four")

    assert choosing.chosen[0] == "create_proposal"
    assert "create_mou" not in choosing.chosen


# --- the router ---------------------------------------------------------------


async def _route(text: str) -> str:
    return await orchestrator.route(
        OrgContext(org_id="o" * 32, user_id="u" * 32, role="admin",
                   email="a@b.c"),
        text,
    )


async def test_the_router_sends_a_contract_request_to_the_proposal_agent(
    client, org_a, choosing
):
    """Deliberately NOT one of the examples written into the router prompt.
    Matching a phrase the prompt quotes verbatim would prove only that string
    equality works."""
    assert await _route(
        "draw up the memorandum of understanding for Green Valley School"
    ) == "proposal"


async def test_the_router_still_sends_a_proposal_request_to_the_same_agent(
    client, org_a, choosing
):
    assert await _route(
        "create the IBC proposal and email it to their finance head"
    ) == "proposal"


# --- PROVING THESE TESTS CAN FAIL (A3 step 2) --------------------------------
#
# Kept as tests rather than done once by hand, because "I checked it goes red"
# is exactly the assurance J1 had. If A2's paragraph is ever removed, or the
# router line reverted, these fail and say why.


def _prompt_without_the_mou_paragraph() -> str:
    """The system prompt as it read BEFORE A2, derived rather than pasted so
    it cannot drift out of step with the real one."""
    prompt = ProposalAgent.system_prompt
    marker = "AN MOU IS A SEPARATE DOCUMENT WITH ITS OWN PIPELINE."
    assert marker in prompt, "A2's paragraph is gone; these tests are moot"
    return prompt[:prompt.index(marker)].rstrip()


async def test_without_the_prompt_paragraph_the_mou_tools_go_invisible(
    client, org_a, choosing, monkeypatch
):
    """THE DEFECT REPRODUCED, and the proof that the tests above discriminate.

    Every MOU tool still EXISTS and is still handed to the model in this run;
    only the paragraph naming them is gone -- which is exactly the state J1
    shipped. The model then reaches for a proposal tool for a contract
    request, and never finds the MOU ones at all.

    It does not assert WHICH wrong tool gets picked. This fake is crude, and
    which of several wrong answers a crude model lands on says nothing; that
    the right one became unreachable says everything.
    """
    token = org_a["admin_token"]
    await _ground(client, token)
    monkeypatch.setattr(ProposalAgent, "system_prompt",
                        _prompt_without_the_mou_paragraph())

    await _say(client, token, f"create the {CODE} MOU for {CLIENT}",
               chat="chat-a3five")

    assert choosing.chosen, "the model did nothing at all, which proves little"
    assert not [t for t in choosing.chosen if "mou" in t], (
        "an MOU tool was still reachable with the paragraph removed, so the "
        "tests above prove nothing about the prompt")


async def test_without_the_prompt_paragraph_a_reply_still_reaches_the_fill(
    client, org_a, choosing, monkeypatch
):
    """This one INVERTED at D48, and the inversion is the point.

    It used to pin the paragraph as the only thing making the answer
    tool reachable on a reply. It is no longer: a document already being
    filled in this conversation now says so from inside a TOOL RESULT,
    and names the tool that moves it on, whatever the system prompt does
    or does not mention. A prompt is advice and a tool result is fact --
    this is the test that spends the fact.

    The paragraph is still load-bearing for STARTING a contract, which
    no tool result can tell the model about;
    test_without_the_prompt_paragraph_the_mou_tools_go_invisible pins
    that and is untouched.
    """
    token = org_a["admin_token"]
    await _ground(client, token)
    chat = "chat-a3six"
    await _say(client, token, f"create the {CODE} MOU for {CLIENT}", chat=chat)
    monkeypatch.setattr(ProposalAgent, "system_prompt",
                        _prompt_without_the_mou_paragraph())
    before = len(choosing.chosen)
    await _say(client, token, "this academic year, Aurora Public School A3",
               chat=chat)

    assert "answer_mou_questions" in choosing.chosen[before:]


async def test_without_the_router_line_a_contract_does_not_reach_the_agent(
    client, org_a, choosing, monkeypatch
):
    """The router prompt as it read before A2: the word MOU appeared nowhere,
    so a contract request matched nothing that meant `proposal`."""
    before_a2 = orchestrator._ROUTER_PROMPT.replace(
        '''- proposal: anything about proposals OR MOUs — create, edit quantities/prices/
  wording, send a proposal ("create the IBC proposal and email it to their
  finance head"), and memoranda of understanding ("create the MOU for IBC",
  "draft the MoU for Sandur", "draw up the contract"). One agent owns both
  documents, so a contract is never a different agent's business.
''',
        '''- proposal: anything about proposals — create, edit quantities/prices/wording,
  send a proposal ("create the IBC proposal and email it to their finance head")
''')
    assert before_a2 != orchestrator._ROUTER_PROMPT, (
        "the router line is not what this test expects; update it here too")
    monkeypatch.setattr(orchestrator, "_ROUTER_PROMPT", before_a2)

    assert await _route(
        "draw up the memorandum of understanding for Green Valley School"
    ) != "proposal"


async def test_the_router_still_works_for_proposals_without_the_mou_line(
    client, org_a, choosing, monkeypatch
):
    """The counterpart, and it must STAY GREEN: A2 widened the line, it did
    not replace what was there. A revert that broke proposal routing too
    would make the test above pass for the wrong reason."""
    before_a2 = orchestrator._ROUTER_PROMPT.replace(
        "OR MOUs", "").replace(
        ''', and memoranda of understanding ("create the MOU for IBC",
  "draft the MoU for Sandur", "draw up the contract"). One agent owns both
  documents, so a contract is never a different agent's business.''', "")
    monkeypatch.setattr(orchestrator, "_ROUTER_PROMPT", before_a2)

    assert await _route(
        "create the IBC proposal and email it to their finance head"
    ) == "proposal"
