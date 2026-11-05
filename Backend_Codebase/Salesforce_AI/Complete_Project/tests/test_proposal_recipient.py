"""Who a proposal email goes to, and not losing the proposal on the way
(Jarvis loop, reported 2 Oct 2026; Siva's conversations of 27 and 29 Sep).

What went wrong, measured on real conversations and three replays with the
real model:

1. After the values were approved the model drafted the email with a
   recipient it made up from nearby words -- the programme ("IBC"), a value
   from the document ("Operations Manager"), the address just typed, or the
   client's own name -- although nobody had named anyone and the client had
   a main contact with an email.
2. The resulting "who did you mean?" was answered ("Dr. Sudhir") and the
   router sent the bare name to a different agent, which offered to add him
   as a contact.
3. Even when it reached the proposal agent, the proposal built one turn
   earlier could not be found: "there is no proposal in this conversation",
   then "shall I create one?", then every question again.
4. A question with no suggested value still offered "All the suggested values
   are fine", which settles nothing, so the same question came back seven
   times.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.ai import confirmations, orchestrator, proposal_recipient
from app.ai.agents import fill_tools
from app.ai.agents.base import AgentRuntime
from app.ai.agents.proposal_agent import ProposalAgent, _resolve_proposal, recipient_said
from app.core.context import OrgContext
from app.core.exceptions import NeedsConfirmationError
from app.database import SessionLocal
from app.models.assistant import AssistantPendingAction
from app.models.lead import Contact, Lead
from app.models.program import Program
from app.models.proposal import Proposal
from app.models.proposal_fill import ProposalFillSession
from app.services import proposal_email_service
from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio
API = "/api/v1"


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
async def org(client, super_token):
    tag = uuid.uuid4().hex[:8]
    org = await create_org(client, super_token, name=f"Recipient {tag}",
                           slug=f"recipient-{tag}", domain=f"rcpt{tag}-example.com")
    me = (await client.get(f"{API}/auth/me", headers=auth(org["admin_token"]))).json()
    org["ctx"] = OrgContext(org_id=org["id"], user_id=me["user_id"], role="org_admin",
                            email=me["email"], name="Admin")
    return org


@pytest.fixture
def mailer(monkeypatch):
    """The email itself is drafted by `proposal_email_service` (unchanged and
    tested elsewhere); here only WHO it was drafted for matters."""
    sent: list[dict] = []

    async def prepare(db, ctx, proposal, *, to_address, cc=None, extra_note=None):
        sent.append({"proposal_id": proposal.id, "to": to_address, "cc": list(cc or [])})
        return SimpleNamespace(id=f"msg{len(sent)}", subject="Proposal", body="Hello")

    monkeypatch.setattr(proposal_email_service, "prepare_proposal_email", prepare)
    return sent


async def _client(org, contacts, *, program="IBC Lab Programme", code="IBC"):
    """A client, its contacts [(name, title, email, primary)], a programme and
    one proposal."""
    async with SessionLocal() as db:
        lead = Lead(org_id=org["id"], name=f"Orchid School {uuid.uuid4().hex[:5]}",
                    owner_id=org["ctx"].user_id, state="open")
        prog = Program(org_id=org["id"], name=program, code=code, description="d")
        db.add_all([lead, prog])
        await db.flush()
        for name, title, email, primary in contacts:
            db.add(Contact(org_id=org["id"], lead_id=lead.id, name=name, title=title,
                           email=email, is_primary=primary))
        proposal = Proposal(org_id=org["id"], lead_id=lead.id, program_id=prog.id,
                            title="IBC proposal", template_id="t", template_version=1,
                            content_md="x", created_by=org["ctx"].user_id)
        db.add(proposal)
        await db.commit()
        return lead.id, lead.name, prog.id, proposal.id


ORCHID = [("Dr. Sudhir", "Principal", "sudhir@example.com", True),
          ("Dr. Meena", "Point Of Contact", None, False)]
NO_MAIN = [("Ravi Kumar", "Coordinator", "ravi@example.com", False),
           ("Priya Nair", "Accounts Head", "priya@example.com", False)]


def _runtime(db, org, *, chat="chat1", said=("Create the proposal",), proposal_id=None):
    extra = {"session_id": chat, "_said_by_user": list(said)}
    if proposal_id:
        extra["proposal_id"] = proposal_id
    return AgentRuntime(db=db, ctx=org["ctx"], extra_context=extra)


async def _held(org, chat="chat1"):
    async with SessionLocal() as db:
        return (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.org_id == org["id"],
            AssistantPendingAction.session_id == chat))).scalars().first()


# ── 1. the recipient comes from the person's own words ────────────────────

async def test_a_made_up_recipient_is_ignored_and_the_main_contact_gets_it(org, mailer):
    _lead, lead_name, _prog, pid = await _client(org, ORCHID)
    async with SessionLocal() as db:
        rt = _runtime(db, org, proposal_id=pid)
        for invented in (lead_name, "IBC", "Operations Manager", f"{lead_name} (finance contact)"):
            out = await ProposalAgent()._prepare_email(rt, proposal_ref=pid, to_contact=invented)
            assert out["ready_for_approval"], invented
        await db.commit()
    assert {m["to"] for m in mailer} == {"sudhir@example.com"}, \
        "nobody named a recipient, so the main contact receives it, with no question"


def test_what_counts_as_said():
    said = ["I want to send the proposal for IBC", "Send it to Dr. Meena please",
            "Neil rao towers, nallurhalli", "All the suggested values are fine"]
    fill_replies = ["Neil rao towers, nallurhalli"]
    kw = dict(said=said, fill_replies=fill_replies,
              not_names=["Orchid International School", "IBC Lab Programme", "IBC"])
    assert recipient_said("Dr. Meena", **kw)
    assert recipient_said("meena", **kw)
    assert not recipient_said("IBC", **kw), "the programme is never the recipient"
    assert not recipient_said("Orchid International School", **kw)
    assert not recipient_said("Orchid International School (finance contact)", **kw)
    assert not recipient_said("Neil rao towers, nallurhalli", **kw), \
        "an answer to the document's question is not a recipient"
    assert not recipient_said("Operations Manager", **kw), "never said at all"
    assert not recipient_said("Dr.", **kw), "an honorific alone names nobody"
    assert not recipient_said(None, **kw)
    assert recipient_said("the principal", said=["send it to the principal"],
                          fill_replies=[], not_names=[])
    assert recipient_said("ravi@example.com", said=["mail it to ravi@example.com"],
                          fill_replies=[], not_names=[])
    assert not recipient_said("ravi@example.com", said=["send it"],
                              fill_replies=[], not_names=[])


async def test_a_named_recipient_is_used(org, mailer):
    _lead, _name, _prog, pid = await _client(org, NO_MAIN)
    async with SessionLocal() as db:
        rt = _runtime(db, org, said=["Create the proposal and send it to Priya"],
                      proposal_id=pid)
        await ProposalAgent()._prepare_email(rt, proposal_ref=pid, to_contact="Priya")
        await db.commit()
    assert mailer[-1]["to"] == "priya@example.com"


async def test_unnamed_cc_is_dropped(org, mailer):
    _lead, lead_name, _prog, pid = await _client(org, ORCHID)
    async with SessionLocal() as db:
        rt = _runtime(db, org, proposal_id=pid)
        await ProposalAgent()._prepare_email(rt, proposal_ref=pid,
                                             cc_contacts=[lead_name, "IBC"])
        await db.commit()
    assert mailer[-1]["cc"] == []


# ── 2. the question is held, and the answer reaches it ────────────────────

async def test_with_no_main_contact_the_question_is_held(org, mailer):
    _lead, _name, _prog, pid = await _client(org, NO_MAIN)
    async with SessionLocal() as db:
        rt = _runtime(db, org, proposal_id=pid)
        with pytest.raises(NeedsConfirmationError) as asked:
            await ProposalAgent()._prepare_email(rt, proposal_ref=pid, to_contact="IBC")
        await db.commit()
    assert "Ravi Kumar" in str(asked.value) and "Priya Nair" in str(asked.value)
    held = await _held(org)
    assert held is not None and held.kind == proposal_recipient.KIND
    assert mailer == []


async def _answer(org, text, chat="chat1"):
    async with SessionLocal() as db:
        result = await orchestrator.handle_command(db, org["ctx"], text, session_id=chat)
        await db.commit()
        return result


async def _ask_first(org, contacts=NO_MAIN, *, hint="IBC", said=("Create the proposal",)):
    # A programme code is unique in an org, and some tests ask twice.
    _lead, _name, _prog, pid = await _client(org, contacts, code=f"IBC{uuid.uuid4().hex[:4]}")
    async with SessionLocal() as db:
        rt = _runtime(db, org, proposal_id=pid, said=said)
        with pytest.raises(NeedsConfirmationError):
            await ProposalAgent()._prepare_email(rt, proposal_ref=pid, to_contact=hint)
        await db.commit()
    return pid


async def test_answering_by_name_drafts_the_email_for_the_same_proposal(org, mailer):
    pid = await _ask_first(org)
    result = await _answer(org, "Priya Nair")
    assert mailer == [{"proposal_id": pid, "to": "priya@example.com", "cc": []}]
    assert result.agent == "proposal"
    assert result.pending_approvals and result.pending_approvals[0]["to"] == "priya@example.com"
    assert "Priya Nair" in result.reply
    assert await _held(org) is None, "answered, so nothing is held any more"


async def test_answering_by_number_or_first_name_works(org, mailer):
    await _ask_first(org)
    await _answer(org, "2")
    assert mailer[-1]["to"] == "priya@example.com"
    await _ask_first(org, said=("Create the proposal",))
    await _answer(org, "ravi")
    assert mailer[-1]["to"] == "ravi@example.com"


async def test_answering_with_an_email_address_uses_it(org, mailer):
    await _ask_first(org)
    await _answer(org, "send it to accounts@orchid.example")
    assert mailer[-1]["to"] == "accounts@orchid.example"


async def test_a_contact_without_email_is_asked_about_again(org, mailer):
    await _ask_first(org, contacts=[("Dr. Meena", "Point Of Contact", None, False),
                                    ("Dr. Sudhir", "Principal", "sudhir@example.com", False)])
    result = await _answer(org, "Dr. Meena")
    assert mailer == []
    assert "no email" in result.reply.lower()
    assert await _held(org) is not None, "still waiting for someone who can receive it"
    await _answer(org, "Dr. Sudhir")
    assert mailer[-1]["to"] == "sudhir@example.com"


async def test_cancel_drafts_nothing_and_keeps_the_proposal(org, mailer):
    pid = await _ask_first(org)
    result = await _answer(org, "cancel")
    assert mailer == []
    assert await _held(org) is None
    assert "proposal" in result.reply.lower()
    async with SessionLocal() as db:
        assert await db.get(Proposal, pid) is not None


async def test_an_unrelated_message_is_not_taken_as_the_answer(org, mailer):
    await _ask_first(org)
    async with SessionLocal() as db:
        held = (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.session_id == "chat1",
            AssistantPendingAction.org_id == org["id"]))).scalars().first()
        outcome = await proposal_recipient.FLOW.handle(
            db, org["ctx"], held, "what are my tasks due today?", {})
    assert outcome is None, "a question about something else is routed as usual"
    assert mailer == []


async def test_after_an_unrelated_question_the_reply_offers_to_come_back(org, mailer, monkeypatch):
    from app.ai.agents.base import AgentResult
    from app.ai.agents.query_agent import QueryAgent

    await _ask_first(org)

    async def route(ctx, text, history):
        return "query"

    async def answer(self, db, ctx, text, extra_context=None, history=None):
        return AgentResult(agent="query", reply="Nothing is due today.")

    monkeypatch.setattr(orchestrator, "route", route)
    monkeypatch.setattr(QueryAgent, "run", answer)
    result = await _answer(org, "what are my tasks due today?")
    assert result.reply.startswith("Nothing is due today.")
    assert "proposal email" in result.reply, result.reply
    assert await _held(org) is not None, "still waiting for the recipient"


# ── 3. the proposal built in this chat is still there next turn ───────────

async def _built_fill(org, lead_id, prog_id, pid, chat="chat1"):
    async with SessionLocal() as db:
        db.add(ProposalFillSession(
            org_id=org["id"], lead_id=lead_id, program_id=prog_id, template_id="t",
            template_doc_id="d", proposal_id=pid, user_id=org["ctx"].user_id,
            chat_session_id=chat, status="built", document_type="proposal",
            asked_json=[{"round": 1, "reply": "Neil rao towers, nallurhalli",
                         "asked": [], "at": "x"}]))
        await db.commit()


async def test_the_built_proposal_is_found_on_a_later_turn(org):
    lead_id, _name, prog_id, pid = await _client(org, ORCHID)
    await _built_fill(org, lead_id, prog_id, pid)
    async with SessionLocal() as db:
        found = await _resolve_proposal(_runtime(db, org), None)
    assert found.id == pid


async def test_another_chat_does_not_see_it(org):
    lead_id, _name, prog_id, pid = await _client(org, ORCHID)
    await _built_fill(org, lead_id, prog_id, pid, chat="other-chat")
    async with SessionLocal() as db:
        with pytest.raises(Exception):
            await _resolve_proposal(_runtime(db, org, chat="chat1"), None)


async def test_a_fill_answer_is_not_a_recipient_even_later(org, mailer):
    """The BS Carmel case: the address typed for the document's question."""
    lead_id, _name, prog_id, pid = await _client(org, ORCHID)
    await _built_fill(org, lead_id, prog_id, pid)
    async with SessionLocal() as db:
        rt = _runtime(db, org, said=["Create the proposal", "Neil rao towers, nallurhalli",
                                     "Yes, these are all correct"])
        await ProposalAgent()._prepare_email(rt, to_contact="Neil rao towers, nallurhalli")
        await db.commit()
    assert mailer[-1] == {"proposal_id": pid, "to": "sudhir@example.com", "cc": []}


async def test_creating_it_again_does_not_reopen_the_questions(org, monkeypatch):
    from app.services import proposal_fill_service

    lead_id, lead_name, prog_id, pid = await _client(org, ORCHID)
    await _built_fill(org, lead_id, prog_id, pid)

    async def simple(db, ctx, program_id):
        return True

    opened: list[str] = []

    async def open_fill(self, runtime, lead, program_row, document_type="proposal"):
        opened.append(lead.id)
        return {"opened": True}

    monkeypatch.setattr(proposal_fill_service, "is_simple_flow", simple)
    monkeypatch.setattr(ProposalAgent, "_open_fill", open_fill)
    async with SessionLocal() as db:
        out = await ProposalAgent()._create(_runtime(db, org), client=lead_name, program="IBC")
        assert out["already_built"] is True and out["id"] == pid
        assert opened == []
        out = await ProposalAgent()._create(_runtime(db, org), client=lead_name,
                                            program="IBC", start_over=True)
        assert opened == [lead_id], "an explicit fresh start still opens a new fill"


# ── 4. no "all fine" button when nothing has a suggestion ─────────────────

def test_all_defaults_is_offered_only_when_something_is_suggested():
    with_suggestion = [{"tag_id": "a", "question": "How many?", "candidates": ["4 Units"]},
                       {"tag_id": "b", "question": "Address?", "candidates": []}]
    without = [{"tag_id": "b", "question": "What is the address?", "context": "Address",
                "candidates": []}]
    assert fill_tools.round_candidates(with_suggestion) == ["4 Units", fill_tools.ALL_DEFAULTS]
    assert fill_tools.round_candidates(without) == []
    text = fill_tools.round_message(without, 1, "")
    assert fill_tools.ALL_DEFAULTS not in text
    assert "no suggestion" in text.lower() and "type" in text.lower()
    assert fill_tools.ALL_DEFAULTS in fill_tools.round_message(with_suggestion, 2, "")
