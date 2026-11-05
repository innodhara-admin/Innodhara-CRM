"""Agent framework.

An agent = one focused AI worker with a small set of tools (doc §6). The
model decides *which* tool to call and with what visible arguments; the
org context (org_id, user) is injected by the runtime — the model can never
choose an organisation. Every tool call is recorded for observability.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import TIER_FAST, Message, ToolCall, get_model_layer
from zoneinfo import ZoneInfo

from app.core import clock
from app.core.context import OrgContext
from app.core.exceptions import LeadNotOpenError, NeedsConfirmationError

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8

# How much of a drafted message an inline approval card carries. The agents
# built this by slicing 300 characters, which is where F30 hid: the blanks sat
# at 397 and 474, past the cut, so the approver was shown a clean opening and
# asked to approve the rest unseen.
APPROVAL_PREVIEW_CHARS = 1200


@dataclass
class AgentRuntime:
    """Everything a tool needs, injected — never model-controlled."""

    db: AsyncSession
    ctx: OrgContext
    #: The organisation's timezone, resolved once per run. `_system` is sync
    #: and cannot await for it, and every relative date the model resolves —
    #: "today", "this Friday" — has to mean the same day as the tools' answers.
    tz: ZoneInfo = field(default_factory=clock.zone)
    # Records accumulated during a run:
    actions: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    extra_context: dict[str, Any] = field(default_factory=dict)  # e.g. active lead/proposal


ToolHandler = Callable[..., Awaitable[Any]]  # (runtime, **args) -> result


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


def _asked_a_question(runtime: AgentRuntime) -> bool:
    """Did this turn put a question to the person? (D48)

    Any tool at all, not only a fill's: a turn that asked which of two clients
    was meant has dealt with the reply just as honestly as one that asked for
    a value, and forcing a second call on top of either would post the same
    words twice.
    """
    return any(action.get("outcome") == "needs_confirmation"
               for action in runtime.actions)


@dataclass
class AgentResult:
    agent: str
    reply: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)
    #: What voice mode says instead of `reply`, when the two must differ (a
    #: spelling shown as "B-A-L" is spoken letter by letter). None = the reply.
    speech: str | None = None


class BaseAgent:
    name: str = "base"
    description: str = ""
    system_prompt: str = ""
    tier: str = TIER_FAST

    def tools(self) -> list[ToolSpec]:  # override
        return []

    def _tool_defs(self) -> list[dict[str, Any]]:
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self.tools()
        ]

    def _system(self, runtime: AgentRuntime, has_history: bool = False) -> str:
        context_note = ""
        # `extra_context` is enriched by `_enrich_context` before the run, so a
        # selected lead arrives here as a human name, not the opaque id the app
        # sends. A name the model can read AND tools it can trust are two halves
        # of the same fix (F17): the query tools default to the selected lead in
        # code, and this line lets the model narrate that scoping accurately.
        # Keys starting "_" are for code (voice mode's `_voice_confidence`), not
        # for the model: they are never written into the prompt.
        visible = {k: v for k, v in runtime.extra_context.items()
                   if not str(k).startswith("_")}
        if visible:
            ctx_data = dict(visible)
            lead_name = ctx_data.pop("lead_name", None)
            if lead_name:
                ctx_data.pop("lead_id", None)  # the name supersedes the raw id
                lines = [
                    f"The user is currently viewing the client '{lead_name}'. If "
                    "they ask about its tasks, notes, proposals, demos or "
                    "follow-ups without naming a different client, they mean this "
                    "one — the tools already default to it. Only broaden to every "
                    "client when the user explicitly asks."
                ]
                if ctx_data:
                    lines.append(
                        "Other selected context: " + json.dumps(ctx_data, default=str)
                    )
                context_note = "\n\n" + "\n".join(lines)
            elif ctx_data:
                context_note = (
                    "\n\nCurrent app context (already selected by the user): "
                    + json.dumps(ctx_data, default=str)
                )
        history_note = ""
        if has_history:
            # Small models will happily ignore earlier turns unless told they
            # are part of the same conversation.
            history_note = (
                "\n\nThis is an ongoing conversation: the messages before the "
                "latest one are earlier turns of it. Resolve 'it', 'that one', "
                "'him', 'the second one' and similar against them, and never ask the user to "
                "repeat something they have already told you. Those turns are "
                "words, not facts on file: call a tool to look anything up "
                "again before acting on it."
            )
        # F68: the planner, the merge and the extraction prompts are all handed
        # today's date. The assistant — the only one a human talks to about
        # dates — was not, so it could not resolve "this Friday", "today",
        # "next week" or "by month end" at all. Asked which tasks were due this
        # Friday it answered "if 2026-09-01 is today for you...", called a
        # Tuesday a Friday, and reported a due date for a task whose due_date
        # was NULL. A model with no clock does not say "I don't know the date";
        # it borrows a day name from the question and states it as fact.
        today = clock.today(runtime.tz)
        clock_note = (
            f"Today is {today.strftime('%A, %d %B %Y')} ({today.isoformat()}). "
            "Use this to resolve every relative date the user says — 'today', "
            "'this Friday', 'next week', 'by month end' — and to work out the "
            "weekday of any date a tool returns. "
            "State a task's due date exactly as the tool reported it. If a tool "
            "returns no due date, say it is not set — never describe an unset "
            "date, and never name a weekday you have not derived from an actual "
            "date. "
        )
        # The user may type OR speak, and the voice path (POST /dictate) runs
        # Whisper, which transcribes rather than translates — so a question
        # asked in any language arrives here in that language's own script,
        # and a single sentence may mix two. Measured with no instruction
        # here: the same Kannada question came back in English on one run and
        # in Kannada on the next two. Nobody chose that; the prompt was
        # silent, so the model decided per call. English is the decision.
        language_note = (
            "Always answer in English, whatever language the user wrote or "
            "spoke in. Understand the question in the language they used — "
            "they may use any language, or mix two in one sentence — and "
            "reply in English regardless. Never mirror their language, and "
            "never leave an untranslated phrase in your reply. Names of "
            "people, clients and places stay exactly as they are recorded. A name "
            "the user wrote in another script is the same client as the one "
            "on file in Latin letters: search for it, and write it back the "
            "way the record spells it. "
        )
        return (
            f"{self.system_prompt}\n\n"
            f"{clock_note}"
            f"{language_note}"
            f"You are acting for {runtime.ctx.name or runtime.ctx.email} "
            f"(role: {runtime.ctx.role}) inside their organisation. "
            "All data access is automatically limited to their organisation — "
            "never mention org ids. Use the tools to act; after acting, reply "
            "with a short, clear confirmation or answer in plain language. "
            "If a tool reports that something needs approval, tell the user it "
            "is ready for their one-tap approval. If a tool returns an error, "
            "explain it simply and suggest the next step. "
            # F28: the user types tersely and loosely, and that is allowed.
            # Their command is the AI's problem to solve, not their problem to
            # avoid — so there are exactly two acceptable outcomes, and a
            # lookup error reported as a dead end is not one of them.
            "The user will often write short, loosely worded commands. Work out "
            "what they mean and do it; when you genuinely cannot, say what you "
            "understood and ask ONE clarifying question — never answer with a "
            "bare lookup failure. If a tool replies that it needs "
            "confirmation, ask its question as your own and stop there: do not "
            "guess a value, do not retry the tool with something you made up, "
            "and never announce work you have not done — if the tool asked "
            "instead of acting, then nothing was drafted or sent and your "
            "reply must not claim it was. When a lookup does resolve, name the person or client you "
            "settled on in your reply, so the user can catch a wrong match "
            "before approving anything."
            + context_note
            + history_note
        )

    async def run(
        self,
        db: AsyncSession,
        ctx: OrgContext,
        user_text: str,
        extra_context: dict[str, Any] | None = None,
        history: list[Message] | None = None,
    ) -> AgentResult:
        """`history` is the earlier turns of this conversation (plain text,
        already alternating — see ai/conversation.py). The tool-call rounds
        below append to a copy of it and are discarded when the run ends:
        what persists is what was said, not how it was found out."""
        runtime = AgentRuntime(
            db=db, ctx=ctx, extra_context=extra_context or {},
            tz=await clock.org_zone(db, ctx.org_id),
        )
        await self._enrich_context(runtime)
        # What the person has actually said in this conversation, for tools
        # that must act only on their words (a proposal's recipient, 2 Oct
        # 2026). "_" keeps it out of the prompt: it is for code, not the model.
        runtime.extra_context["_said_by_user"] = [
            str(m.get("content") or "") for m in (history or [])
            if m.get("role") == "user"
        ] + [user_text]
        tool_specs = {t.name: t for t in self.tools()}
        has_history = bool(history)
        messages: list[Message] = list(history or [])
        messages.append({"role": "user", "content": user_text})
        model = get_model_layer()
        reply = ""
        # D48. Not "did a tool run" but "was the person ASKED anything".
        # The owner's 06:07:41 turn called `show_mou_questions` for "All the
        # suggested values are fine" -- a tool that lists and answers nothing
        # -- so a tool HAD run, D47's force stood aside, and the answer was
        # lost. Seven rounds recorded for nine replies.
        forced_once = False
        called: list[str] = []

        for _ in range(MAX_TOOL_ROUNDS):
            response = await model.generate(
                purpose=f"agent.{self.name}",
                tier=self.tier,
                org_id=ctx.org_id,
                user_id=ctx.user_id,
                system=self._system(runtime, has_history),
                messages=messages,
                tools=self._tool_defs() or None,
                temperature=0.2,
            )
            if not response.has_tool_calls:
                # D47. A turn that called NOTHING may still owe a tool call.
                # Nine of twenty answers to the owner's contract reached no
                # tool: the model restated the question it had just been given
                # and the fill sat untouched, which reads as being asked the
                # same thing again. Asked BEFORE the reply is taken, so the
                # model words its answer from what the tool actually returned
                # -- and only when nothing ran, so a tool it chose for itself
                # is never second-guessed.
                forced = None if forced_once or _asked_a_question(runtime) \
                    else await self._tool_the_turn_needs(runtime, user_text,
                                                         called)
                if forced is not None:
                    forced_once = True
                    logger.info("Turn called no tool; passing the reply to %s",
                                forced.name)
                    messages.append({"role": "assistant",
                                     "content": response.text,
                                     "tool_calls": [forced]})
                    messages.append({
                        "role": "tool_result",
                        "name": forced.name,
                        "call_id": forced.call_id,
                        "result": await self._execute_tool(
                            runtime, tool_specs, forced),
                    })
                    continue
                reply = response.text.strip()
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.text,
                    "tool_calls": response.tool_calls,
                }
            )
            for call in response.tool_calls:
                called.append(call.name)
                result = await self._execute_tool(runtime, tool_specs, call)
                messages.append(
                    {
                        "role": "tool_result",
                        "name": call.name,
                        "call_id": call.call_id,
                        "result": result,
                    }
                )
        else:
            reply = "I did several steps but ran out of room — please check the results above."

        # D48. The app draws the model's prose AND the card the tool built,
        # and on the owner's contract they disagreed on the same screen: the
        # card asked for six things, the prose asked for two. The card is
        # built from the document itself, so it is the question; the prose is
        # cut to the card's own opening line and cannot argue with it.
        card = self._question_card(runtime)
        if card:
            reply = card.splitlines()[0].strip() or reply
        refusal = not_allowed_reply(runtime.actions)
        if refusal and refusal not in reply:
            # The rule is stated as written: a model paraphrase could soften it
            # or, worse, still announce the meeting it did not book.
            reply = refusal

        await self._enrich_approvals(runtime)
        return AgentResult(
            agent=self.name,
            reply=reply or "Done.",
            actions=runtime.actions,
            pending_approvals=runtime.pending_approvals,
        )

    #: Tools whose question the APP draws as a card. The agent's prose is
    #: replaced by the card's opening line for these, so the two can never
    #: disagree (D48). Empty here: no agent gets this by accident.
    CARD_TOOLS: frozenset[str] = frozenset()

    def _question_card(self, runtime: AgentRuntime) -> str | None:
        """The question this turn put in front of the person, if a card tool
        asked it. The LAST one: a turn that asked twice ends on the second."""
        for action in reversed(runtime.actions):
            if (action.get("outcome") == "needs_confirmation"
                    and action.get("tool") in self.CARD_TOOLS):
                return str(action.get("question") or "") or None
        return None

    async def _tool_the_turn_needs(
        self, runtime: AgentRuntime, user_text: str, called: list[str]
    ) -> ToolCall | None:
        """The call this turn cannot be correct without, or None for most.

        Asked when the turn put no question to the person. `called` is every
        tool it did run, so an agent can tell a tool that merely LISTED
        something from one that could have acted on the reply. An agent that
        has
        left a question outstanding with the user answers it here rather than
        hoping the prompt was read: a prompt is advice, and on the fast tier
        advice is not enough. The default is None -- no agent is forced into
        anything it did not ask for.
        """
        return None

    async def _enrich_approvals(self, runtime: AgentRuntime) -> None:
        """Tell each inline approval card the truth about the draft behind it
        (F30).

        Two things the card could not previously say. First, the blanks a model
        left behind — `[Name]`, `[Insert Date]` — so the warning arrives BEFORE
        the tap rather than as a refusal after it. Second, that its preview is
        only a preview: agents built `body_preview` by slicing 300 characters,
        and the placeholders that prompted this finding sat at 397 and 474, so
        the person approving was shown a clean opening and never the blanks.

        Done here, once, rather than in each agent: a tool added in a later
        phase inherits it without knowing this rule exists. Best-effort by
        design — an enrichment failure must never lose the user their draft.
        """
        if not runtime.pending_approvals:
            return
        from app.models.messaging import OutboundMessage
        from app.services import draft_check

        for approval in runtime.pending_approvals:
            message_id = approval.get("message_id")
            if not message_id:
                continue
            try:
                message = (
                    await runtime.db.execute(
                        select(OutboundMessage).where(
                            OutboundMessage.org_id == runtime.ctx.org_id,
                            OutboundMessage.id == message_id,
                        )
                    )
                ).scalar_one_or_none()
            except Exception:  # noqa: BLE001 — never fatal to a drafted message
                logger.debug("Could not enrich approval for message %s", message_id)
                continue
            if message is None:
                continue
            body = message.body or ""
            if len(body) > len(approval.get("body_preview") or ""):
                approval["body_preview"] = body[:APPROVAL_PREVIEW_CHARS]
                if len(body) > APPROVAL_PREVIEW_CHARS:
                    approval["preview_note"] = (
                        "This is the opening of the message — open it to read the rest "
                        "before approving."
                    )
            blanks = draft_check.find_blanks(message.subject, body)
            if blanks:
                approval["blanks"] = blanks
                approval["warning"] = (
                    "This draft still has blanks to fill in: "
                    + ", ".join(blanks[:6])
                    + ". Approving is refused until you confirm you mean to send it "
                    "as it is."
                )

    async def _enrich_context(self, runtime: AgentRuntime) -> None:
        """Resolve a selected `lead_id` to its name once, up front, so the
        system prompt can name the client and the model's prose stays accurate.
        Best-effort: a lookup failure just leaves the raw context in place, and
        the deterministic tool-level scoping (which uses the id directly) is
        unaffected either way. Local import breaks the base<->resolvers cycle."""
        lead_id = runtime.extra_context.get("lead_id")
        if not lead_id or runtime.extra_context.get("lead_name"):
            return
        try:
            from app.ai.agents.resolvers import resolve_lead

            lead = await resolve_lead(runtime, lead_id)
            runtime.extra_context["lead_name"] = lead.name
        except Exception:  # noqa: BLE001 — enrichment is never fatal to a command
            logger.debug("Could not resolve selected lead %s for context", lead_id)

    async def _execute_tool(
        self,
        runtime: AgentRuntime,
        tool_specs: dict[str, ToolSpec],
        call: ToolCall,
    ) -> Any:
        spec = tool_specs.get(call.name)
        if spec is None:
            return {"error": f"Unknown tool '{call.name}'"}
        try:
            result = await spec.handler(runtime, **(call.args or {}))
            runtime.actions.append(
                {"tool": call.name, "args": call.args, "ok": True, "result": _preview(result)}
            )
            return result
        except LeadNotOpenError as exc:
            # A rule, not a failure: the lead is still in cold calling, so
            # nothing was created. `run` makes this sentence the reply.
            logger.info("Tool %s refused, lead not open: %s", call.name, exc.message)
            runtime.actions.append(
                {"tool": call.name, "args": call.args, "ok": False,
                 "outcome": "not_allowed", "error": exc.message}
            )
            return {
                "not_allowed": True,
                "error": exc.message,
                "instruction": (
                    "Tell the user exactly this. NOTHING was created, scheduled "
                    "or drafted, and do not offer to try again until the lead "
                    "is open."
                ),
            }
        except NeedsConfirmationError as exc:
            # The tool is not broken, it is unsure (F28). The model is told to
            # ASK rather than apologise, and the app is told this is a question
            # rather than a crash.
            #
            # `ok` stays False and `error` still carries the text on purpose:
            # the tool genuinely did not act, and an app built before this
            # renders exactly what it rendered before — a plain honest failure
            # — instead of a success that never happened. A newer app reads
            # `outcome` and draws the question card.
            logger.info("Tool %s needs confirmation: %s", call.name, exc.message)
            runtime.actions.append(
                {
                    "tool": call.name,
                    "args": call.args,
                    "ok": False,
                    "outcome": "needs_confirmation",
                    "error": exc.message,
                    "question": exc.message,
                    "candidates": exc.candidates,
                    # Structured state behind the question, when a tool has
                    # some (a client being built up); absent otherwise.
                    **({"details": exc.details} if exc.details else {}),
                }
            )
            return {
                "needs_confirmation": True,
                "question": exc.message,
                "candidates": exc.candidates,
                "instruction": (
                    "Do not guess and do not retry with an invented value. Tell "
                    "the user what you understood, ask this question, and wait "
                    "for their answer. NOTHING has been drafted, created or "
                    "sent for this request and nothing is waiting for approval "
                    "— do not say or imply otherwise."
                ),
            }
        except TypeError as exc:
            logger.warning("Tool %s bad arguments: %s", call.name, exc)
            runtime.actions.append(
                {"tool": call.name, "args": call.args, "ok": False, "error": str(exc)}
            )
            return {"error": f"Invalid arguments: {exc}"}
        except Exception as exc:  # noqa: BLE001 — surface to the model, don't crash
            logger.exception("Tool %s failed", call.name)
            runtime.actions.append(
                {"tool": call.name, "args": call.args, "ok": False, "error": str(exc)}
            )
            return {"error": str(exc)}


def not_allowed_reply(actions: list[dict[str, Any]]) -> str | None:
    """The refusal(s) a turn ran into because a lead is not open yet, as one
    reply, or None. Repeated refusals (the model retrying) are said once."""
    said: list[str] = []
    for action in actions:
        if action.get("outcome") == "not_allowed":
            text = str(action.get("error") or "").strip()
            if text and text not in said:
                said.append(text)
    return " ".join(said) or None


def _preview(result: Any, limit: int = 800) -> Any:
    try:
        text = json.dumps(result, default=str)
    except TypeError:
        text = str(result)
    if len(text) <= limit:
        return result
    return text[:limit] + "…"
