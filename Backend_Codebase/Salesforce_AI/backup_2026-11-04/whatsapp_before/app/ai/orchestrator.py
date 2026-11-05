"""The Orchestrator — reads each request and routes it to the right specialist
agent, always passing the organisation context along (doc §6, Figure 4).

Routing uses the cheap/fast model tier; the chosen agent then runs its own
tool loop. Multi-part commands ("create the proposal AND send it") stay with
one agent whose tools cover the whole job.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import confirmations, conversation
# Every held conversation's flow registers on import. The orchestrator is
# where held conversations are answered, so they are all imported here, at
# startup: `meeting_draft` used to be imported only inside the scheduling
# agent's tool, so after a restart an answer to "what time?" found no flow,
# the held meeting was dropped and the answer routed as a new message
# (2 Oct 2026). `client_draft` and `proposal_recipient` arrive with their
# agents below; named here too so this list is the whole set.
from app.ai import client_draft, meeting_draft, proposal_recipient  # noqa: F401,E402
from app.ai.agents.base import AgentResult, BaseAgent
from app.ai.agents.client_agent import ClientAgent
from app.ai.agents.conversation_agent import ConversationAgent
from app.ai.agents.email_agent import EmailAgent
from app.ai.agents.followup_agent import FollowupAgent
from app.ai.agents.proposal_agent import ProposalAgent
from app.ai.agents.query_agent import QueryAgent
from app.ai.agents.scheduling_agent import SchedulingAgent
from app.ai.llm import TIER_FAST, Message, get_model_layer
from app.core.context import OrgContext

logger = logging.getLogger(__name__)

_AGENTS: dict[str, type[BaseAgent]] = {
    "conversation": ConversationAgent,
    "proposal": ProposalAgent,
    "email": EmailAgent,
    "followup": FollowupAgent,
    "query": QueryAgent,
    "scheduling": SchedulingAgent,
    "client": ClientAgent,
}

_ROUTER_PROMPT = """You route a salesperson's request to one specialist agent.

Agents:
- query: questions/reports — "show my open tasks", "list active clients",
  "what do we know about X", "which demos this week", and ANY request for
  what is known about a client already on file, however worded and in
  whatever language: "tell me about SJBC Tumkur", "SJBC Tumkur bagge maahiti
  kodi", "SJBC Tumkur ke baare mein batao"
- conversation: notes, contacts and task changes — "add a note", "close task
  1", "move task 2 to Siva", "create a task", and adding a person to a client
  ALREADY on file: "add Ramesh, their director, 9876543210, as a contact
  for SJBC Tumkur", "save Anita's email anita@acme.com for Acme"
- proposal: anything about proposals OR MOUs — create, edit quantities/prices/
  wording, send a proposal ("create the IBC proposal and email it to their
  finance head"), and memoranda of understanding ("create the MOU for IBC",
  "draft the MoU for Sandur", "draw up the contract"). One agent owns both
  documents, so a contract is never a different agent's business.
- email: introductory messages, custom/one-off emails, and REPLIES to something
  a client sent us — "reply to their question about the refund policy", "draft
  an email to <person> at <client>", "answer this and send it". Anything whose
  outcome is a message going out to a client and is NOT about a proposal.
  Writing the answer as chat prose is never enough: it must become a draft.
  Also every email from the organisation's own templates: an intro, a meeting
  confirmation, a follow-up after a meeting or when they have not replied,
  onboarding, or a product's email ("send the IBC proposal email to their
  finance head", "send the meeting confirmation to Acme"), and short answers
  to its questions about one ("Ms.", "Tuesday at 11"). SENDING a proposal or
  an MoU that already exists is an email: "send the IBC proposal email to
  Acme", "send the MoU cover letter to Acme", "Acme ge IBC proposal mail
  kalisi", "Acme ko proposal email bhejo". Creating one is proposal's. A
  request that starts "email <client> that ..." is always email's, even when
  it mentions a meeting or a visit
- followup: follow-up reminders and follow-up messages — "which follow-ups are
  due", "write a whatsapp follow-up for Green Valley", "mark follow-up done"
- scheduling: demos and demo teams — book/cancel demos, team schedules,
  calendar view — AND meetings with a client: "schedule a meeting with Acme on
  Friday at 11", "set up a call with Sandur next week", "fix a
  visit to IBC", "cancel my meeting with Acme", and short answers to its
  questions about a meeting ("at 4 pm", "Monday"). A meeting is not a demo;
  both belong to this agent
- client: adding a NEW client (a lead) — "add a new client Nexora in Pune",
  "create a lead for Acme and give it to Asha", "register this company, we met
  their CTO Anita", "who can own a new client"; and MOVING an existing client
  to another state — "move Acme to open", "take SJBC out of cold calling",
  "mark Green Valley as lost for now", "this one is active now". Questions
  about clients already on file are query's. Asking ABOUT a client is never
  this agent's work, in any language.

Requests come in English, Hindi and Kannada, romanised or in script, often
mixed with English. These are the words that decide what is being asked, and a
small model guesses them wrongly without help:
  Kannada — kelasa/kelasagalu = task(s); maahiti = information; bagge = about;
  yaavuvu = which are; torisi/tori = show; kodi = give; serisi = add;
  rachisi/maadi = create/do; hosa = new; ondu = a, one; baaki = pending/due;
  sabhe/meeting = meeting; graahaka = client; hesaru = name; badalisi = change;
  kalisi/kalsi = send.
  Hindi — kaam = task; dikhao = show; batao = tell; baare mein = about;
  banao = create; karo = do; naya = new; naam = name; baaki = pending;
  bhejo = send.
A request built from these is the same request in English: "nanna kelasagalu
torisi" is "show my tasks", and goes to query.

Anything that is not this platform's business — football, the weather, general
knowledge, chit-chat — goes to conversation, which says plainly that it helps
with sales work. Never treat such a question as a search: asked "which
football team do you like?" the answer is not "which team do you mean?".
Requests arrive in English, Hindi or Kannada, romanised or in script; route on
what is being asked, not on the language it is asked in.
{history}
Request: "{text}"

Return JSON: {{"agent": "<name>", "reason": "<short>"}}"""

_ROUTER_HISTORY_HEADER = """
Earlier in this same conversation (oldest first) — a short follow-up like
"make it warmer", "send it", "the second one" continues that work, so route
it to the agent that would handle what it refers to:
{turns}
"""

_ROUTER_SCHEMA = {
    "type": "object",
    "properties": {"agent": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["agent"],
}


def _history_block(history: list[Message] | None, *, turns: int = 4) -> str:
    """The tail of the conversation, flattened into the router prompt. The
    router answers a schema-constrained JSON question, so history rides as
    quoted text rather than as real turns — that keeps the single-question
    shape the small fast model handles reliably."""
    if not history:
        return ""
    lines = []
    for message in history[-turns:]:
        who = "User" if message.get("role") == "user" else "Assistant"
        said = str(message.get("content") or "").strip().replace("\n", " ")
        if said:
            lines.append(f'- {who}: "{said[:300]}"')
    if not lines:
        return ""
    return _ROUTER_HISTORY_HEADER.format(turns="\n".join(lines))


async def route(
    ctx: OrgContext, text: str, history: list[Message] | None = None
) -> str:
    """Pick the agent for this request. Falls back to 'query' on any doubt."""
    try:
        data = await get_model_layer().generate_json(
            purpose="orchestrator.route",
            tier=TIER_FAST,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            messages=[
                {
                    "role": "user",
                    "content": _ROUTER_PROMPT.format(
                        text=text[:2000], history=_history_block(history)
                    ),
                }
            ],
            json_schema=_ROUTER_SCHEMA,
            temperature=0.0,
            max_tokens=256,
        )
        agent = str(data.get("agent", "")).strip().lower()
        if agent in _AGENTS:
            return agent
        logger.warning("Router picked unknown agent '%s'; defaulting to query", agent)
    except Exception:  # noqa: BLE001 — routing must never take the app down
        logger.exception("Routing failed; defaulting to query agent")
    return "query"


async def _the_fill_owns_the_turn(
    db: AsyncSession, ctx: OrgContext, session_id: str | None, chosen: str
) -> str:
    """A document waiting on this person owns the conversation (D48).

    The router is a fast model reading one sentence and four quoted turns, and
    it falls back to `query` whenever it is unsure. On the owner's contract
    "Yes show the remaining" went to the query agent, which has no MOU tools
    and no idea a document was open, and it improvised a paragraph asking
    where the form was.

    Scoped to a fill that is actually waiting -- asking, or at its review.
    Once the document is built or abandoned the conversation is ordinary
    again, which matters: otherwise one unfinished contract would capture
    every question a salesperson ever asked in that chat.
    """
    if not session_id:
        return chosen
    if chosen != "proposal":
        from app.models.proposal_fill import FillStatus  # noqa: PLC0415
        from app.services import proposal_fill_service  # noqa: PLC0415

        waiting = (FillStatus.ASKING, FillStatus.REVIEWING)
        for document_type in ("mou", "proposal"):
            session = await proposal_fill_service.find_for_chat(
                db, ctx, chat_session_id=session_id, document_type=document_type)
            if session is not None and session.status in waiting:
                logger.info("A %s is waiting on this person; the turn goes to the "
                            "proposal agent, not %s", document_type, chosen)
                return "proposal"
    # The same rule for an email filled from a Word template (28 Oct 2026):
    # while it waits for answers, a short reply ("Ms.", "Tuesday at 11") is
    # about it, whatever the router made of the sentence alone.
    if chosen != "email":
        from app.models.email_template import EmailFillStatus  # noqa: PLC0415
        from app.services import email_fill_service  # noqa: PLC0415

        email = await email_fill_service.find_for_chat(
            db, ctx, session_id, statuses=(EmailFillStatus.ASKING,))
        if email is not None:
            logger.info("An email is waiting on this person; the turn goes to "
                        "the email agent, not %s", chosen)
            return "email"
    return chosen


async def _held_conversation(
    db: AsyncSession, ctx: OrgContext, session_id: str | None, text: str,
    context: dict[str, Any] | None = None,
) -> tuple[AgentResult | None, str | None, str | None]:
    """Give the message to a conversation this chat is holding open (see
    app/ai/confirmations.py) before the router sees it.

    Returns (result, resume_prompt, held_id): a result when the held
    conversation answered; otherwise, when it was paused because the message
    is about something else, the offer to continue and which row it was."""
    held = await confirmations.load(db, ctx, session_id, include_expired=True)
    if held is None:
        return None, None, None
    if confirmations.is_expired(held):
        await confirmations.drop(db, held)
        if confirmations.classify_reply(text) == confirmations.YES:
            return AgentResult(
                agent=held.agent,
                reply=("That was a while ago, so I didn't act on it and nothing "
                       "was created. Tell me again if you still want it."),
            ), None, None
        return None, None, None
    flow = confirmations.flow_for(held.kind)
    if flow is None:
        await confirmations.drop(db, held)
        return None, None, None
    outcome = await flow.handle(db, ctx, held, text, dict(context or {}))
    if outcome is not None:
        return AgentResult(agent=held.agent, reply=outcome.reply,
                           actions=outcome.actions, speech=outcome.speech,
                           pending_approvals=outcome.pending_approvals), None, None
    return None, await flow.pause(db, ctx, held), held.id


async def handle_command(
    db: AsyncSession,
    ctx: OrgContext,
    text: str,
    *,
    context: dict[str, Any] | None = None,
    force_agent: str | None = None,
    session_id: str | None = None,
    on_routed: Callable[[str], Awaitable[None]] | None = None,
) -> AgentResult:
    """Entry point used by POST /assistant/command and by voice mode.

    With a `session_id` the command joins an ongoing conversation: the earlier
    turns are loaded, shown to both the router and the agent, and this
    exchange is appended afterwards. Without one the call is stateless, and
    nothing is recorded — the caller decides whether it is having a
    conversation or firing a one-off command (scripts and tests do the
    latter).

    `on_routed(agent_name)` is called once the agent is chosen and before it
    runs — voice mode speaks its acknowledgement there. A failing callback is
    ignored: it must never cost the person their command."""
    history = await conversation.load_history(
        db, org_id=ctx.org_id, user_id=ctx.user_id, session_id=session_id
    )
    # A conversation held open in this chat (a client being built up) gets
    # the message first, so "skip this" or "create it" never reaches the router.
    held_result, resume_prompt, held_id = await _held_conversation(
        db, ctx, session_id, text, context)
    if held_result is not None:
        await conversation.save_exchange(
            db, org_id=ctx.org_id, user_id=ctx.user_id, session_id=session_id,
            user_text=text, reply=held_result.reply, agent=held_result.agent,
        )
        return held_result

    agent_name = (
        force_agent if force_agent in _AGENTS else await route(ctx, text, history)
    )
    if force_agent not in _AGENTS:
        agent_name = await _the_fill_owns_the_turn(db, ctx, session_id,
                                                   agent_name)
    if on_routed is not None:
        try:
            await on_routed(agent_name)
        except Exception:  # noqa: BLE001 — an acknowledgement is never load-bearing
            logger.debug("on_routed callback failed", exc_info=True)
    agent = _AGENTS[agent_name]()
    # Which conversation this is, handed to the agent the way the selected
    # lead already is. A multi-turn job that has to survive between
    # commands -- filling a tagged Word document tag by tag -- is keyed on
    # it, so "two of each" an hour later reaches the fill it belongs to
    # and not another salesperson's.
    run_context = dict(context or {})
    if session_id:
        run_context["session_id"] = session_id
    result = await agent.run(
        db, ctx, text, extra_context=run_context, history=history
    )
    if resume_prompt and not any(a.get("outcome") == "needs_confirmation"
                                 for a in result.actions):
        # The held conversation waited while this was answered. Offer to go
        # back — unless the answer asked its own question (two questions in
        # one reply cannot both be answered "yes"), or replaced the held one.
        still = await confirmations.load(db, ctx, session_id)
        if still is not None and still.id == held_id:
            result.reply = f"{result.reply} {resume_prompt}"
    # Only a completed exchange is remembered: if the agent raised, there is
    # no reply to record and the retry should start from a clean slate.
    await conversation.save_exchange(
        db, org_id=ctx.org_id, user_id=ctx.user_id, session_id=session_id,
        user_text=text, reply=result.reply, agent=result.agent,
    )
    return result
