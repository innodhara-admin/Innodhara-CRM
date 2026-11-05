"""Proposal Agent — builds and edits proposals from the organisation's own
template and pricing table (doc §6).

Numbers discipline: the model only passes *which* item and *what quantity /
explicitly-requested price*; all arithmetic and document numbers are computed
by proposal_service. The model cannot invent totals.
"""
from __future__ import annotations

from typing import Any

from app.ai.llm import TIER_FAST, TIER_STRONG, get_model_layer
from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
# A1: these five moved to fill_tools, because a round of questions and the D13
# review are the same act whichever document is being filled, and A2 adds the
# MOU's tools beside them. Bound to the names they already had so that every
# call site below -- and the two tests that reach for `proposal_agent._group`
# and `proposal_agent._review_message` -- keep working untouched.
from app.ai.agents.fill_tools import (
    ALL_DEFAULTS,
    APPROVE,
    group as _group,
    question_line as _question_line,
    review_message as _review_message,
    round_candidates as _round_candidates,
    round_message as _round_message,
)
from app.ai.agents.resolvers import resolve_contact, resolve_lead, resolve_program
from app.core.context import OrgContext
from app.core.exceptions import (
    NeedsConfirmationError,
    NotFoundError,
    ValidationFailedError,
)
from app.ai.agents import fill_tools
from app.models.lead import Contact
from app.models.mou import MouDocument
from app.models.proposal import Proposal
from app.services import (
    lead_service,
    proposal_email_service,
    proposal_fill_service,
    proposal_service,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Imported for its side effect too: it registers the held recipient question
# with app.ai.confirmations, so it is known from the first command after a
# restart (this module is imported by the orchestrator at startup).
from app.ai import proposal_recipient

import re as _re

#: Words that sit around a name without being one.
_NOT_A_NAME = frozenset({
    "mr", "mrs", "ms", "miss", "dr", "prof", "sir", "madam", "shri", "smt", "sri",
    "the", "to", "for", "of", "and", "at", "a", "an", "send", "it", "email",
    "mail", "please", "contact", "person", "team",
})


def _tokens(text: Any) -> set[str]:
    return {w for w in _re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(w) > 1}


def recipient_said(
    hint: str | None, *, said: list[str], fill_replies: list[str],
    not_names: list[str],
) -> bool:
    """Did the person name this recipient in their own words? (2 Oct 2026)

    On Siva's conversations the model filled the email's recipient with the
    programme ("IBC"), a value from the document ("Operations Manager"), the
    address just typed as an answer, or the client's own name -- nobody had
    named anyone. A hint counts only if every word that could be a name is in
    what the person said in this chat, outside their answers to the
    document's questions and the fixed taps, and it is not just the client or
    the programme. An email address must have been typed by them."""
    hint = (hint or "").strip()
    if not hint:
        return False
    skip = {_said(r) for r in fill_replies} | {_said(ALL_DEFAULTS), _said(APPROVE)}
    heard_text = " ".join(t for t in said if _said(t) not in skip)
    if "@" in hint:
        return hint.lower() in heard_text.lower()
    excluded = set().union(*(_tokens(n) for n in not_names)) if not_names else set()
    words = _tokens(hint) - _NOT_A_NAME - excluded
    return bool(words) and words <= _tokens(heard_text)


async def _proposal_from_this_chat(runtime: AgentRuntime) -> Proposal | None:
    """The proposal this conversation built, while it can still be corrected.

    Without it a turn could only find a proposal it built ITSELF: the one
    built a turn earlier was invisible, the assistant said there was no
    proposal in the conversation, offered to create one, and asked every
    question again (Orchid, 27 Sep 2026). Same chat, same window as
    `correct_proposal` already uses."""
    chat = runtime.extra_context.get("session_id")
    built = await proposal_fill_service.find_correctable(
        runtime.db, runtime.ctx, chat_session_id=chat, document_type="proposal")
    if built is None or not built.proposal_id:
        return None
    return (await runtime.db.execute(select(Proposal).where(
        Proposal.org_id == runtime.ctx.org_id,
        Proposal.id == built.proposal_id))).scalar_one_or_none()


async def _resolve_proposal(runtime: AgentRuntime, proposal_ref: str | None) -> Proposal:
    """Find the proposal by id, or fall back to app context / latest for lead,
    or to the one this conversation built."""
    db, ctx = runtime.db, runtime.ctx
    ref = (proposal_ref or "").strip() or runtime.extra_context.get("proposal_id", "")
    if not ref:
        from_chat = await _proposal_from_this_chat(runtime)
        if from_chat is not None:
            return from_chat
    if ref:
        proposal = (
            await db.execute(
                select(Proposal).where(Proposal.id == ref, Proposal.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        if proposal:
            return proposal
        # maybe it's a client name
        lead = await resolve_lead(runtime, ref)
        proposal = (
            await db.execute(
                select(Proposal)
                .where(Proposal.org_id == ctx.org_id, Proposal.lead_id == lead.id)
                .order_by(Proposal.created_at.desc())
            )
        ).scalars().first()
        if proposal:
            return proposal
    # Nothing BUILT -- but one may be half-filled in this chat. Replayed on
    # 12 Oct 2026: a correction on the review went to get_proposal, "create
    # one first" came back, and the model asked the person for a proposal id
    # for a document waiting on their check. Name the tool that reaches it.
    open_fill = await proposal_fill_service.find_for_chat(
        db, ctx, chat_session_id=runtime.extra_context.get("session_id"),
        document_type="proposal")
    if open_fill is not None:
        names = fill_tools.TOOLS["proposal"]
        waiting = proposal_fill_service.open_questions(open_fill, limit=None)
        raise NotFoundError(
            "This proposal is not built yet: it is being filled in this "
            "conversation. Do not offer to create one and do not ask for an id. "
            + (f"Pass the user's words to {names['answer']}." if waiting else
               f"It is waiting at the review. If the user's message asks to "
               f"change ANYTHING (\"wrong\", \"looks bad\", \"should be\", "
               f"\"make it\", a new value), call {names['confirm']} with their "
               f"whole message in correction and approved=false -- never "
               f"approve a message that asks for a change. Only if it accepts "
               f"every value and asks for no change, call {names['confirm']} "
               f"with approved=true.")
        )
    raise NotFoundError(
        "Which proposal? Create one first or pass the client name / proposal id."
    )


#: Why the editing tools stand aside for a document filled by the assistant.
#: `content_md` is only the PROJECTION of that document, not the document, so
#: rewriting it would change the record and leave the .docx the client
#: receives untouched -- an edit that reports success over a file that never
#: moved. Its commercials are not in `line_items` either; they are sentences
#: inside the document, in the words the salesperson approved.
NOT_EDITABLE_HERE = (
    "This proposal was filled in from the tags in its own Word document, so "
    "there is no wording or line item here to edit -- both live inside the "
    "document itself. Tell me which value is wrong and what it should say "
    "instead, and I will correct it and write the document again."
)


#: Why the editing tools stand aside for a CONTRACT, and why they have to do
#: it BEFORE resolving anything.
#:
#: Defect 3, measured: `edit_narrative` refused on a simple-flow proposal only
#: because the instruction happened to contain a price and tripped the price
#: guard. On the path that does NOT trip it, the tool rewrote the RECORD of a
#: document it cannot touch and reported success.
#:
#: For an MOU it is worse than that. `_resolve_proposal` falls back to the
#: client's most recent proposal when it is handed a name, so "make it warmer"
#: in a contract conversation could rewrite an unrelated PROPOSAL -- a
#: different document, for the same client, that nobody mentioned -- and
#: report success. Hence the guard runs first and asks about the CONVERSATION,
#: not about whatever `_resolve_proposal` manages to find.
NOT_EDITABLE_MOU = (
    "This is a memorandum of understanding, and its wording and its figures "
    "live inside its own Word document -- there is no narrative or line item "
    "here to edit. Tell me which value is wrong and what it should say "
    "instead, and I will put it through correct_mou, which writes the "
    "document again."
)


def _mou_summary(mou: Any) -> dict[str, Any]:
    """What the chat card shows for a contract.

    NO total, NO line items, NO currency. `MouDocument` has no such columns
    and that is D-A rather than an omission: the last session announced
    "Total amount: 2200" for a document reading Rs. 15,00,000 by carrying the
    proposal's summary across without asking whether its premise came too.
    What this contract is worth is stated inside it, in the words the person
    approved, and `filled_json` carries those for the app to show.
    """
    return {
        "mou_id": mou.id,
        "title": mou.title,
        "status": mou.status,
        "lead_id": mou.lead_id,
        "program_id": mou.program_id,
        "template_version": mou.template_version,
        "has_pdf": bool(mou.pdf_path),
    }


def _refuses_editing(proposal: Any) -> bool:
    """Is this a proposal whose content lives in its own document?"""
    return getattr(proposal, "template_kind", "markdown") == "docx_simple"


def _guard_editing(proposal: Any) -> None:
    if _refuses_editing(proposal):
        raise ValidationFailedError(NOT_EDITABLE_HERE.format(
            program=getattr(proposal, "title", "") or "same"))


def _proposal_summary(proposal: Proposal) -> dict[str, Any]:
    """What the chat card shows about a proposal.

    A simple-flow proposal has no computed commercials -- its prices are
    sentences inside its own document, in the words the salesperson approved.
    Reporting `total_amount` and `line_items` for one meant the chat card
    announced a total that appeared nowhere in the proposal, so they are left
    out rather than sent as zeroes: an absent figure reads as absent, and a
    zero reads as free.
    """
    simple = getattr(proposal, "template_kind", "markdown") == "docx_simple"
    if simple:
        return {
            "id": proposal.id,
            "title": proposal.title,
            "status": proposal.status,
            "currency": proposal.currency,
            "commercials": (
                "in the document itself, in the words you approved -- this "
                "flow computes no total"
            ),
            "template_version": proposal.template_version,
            "pricing_version": proposal.pricing_version,
        }
    return {
        "id": proposal.id,
        "title": proposal.title,
        "status": proposal.status,
        "currency": proposal.currency,
        "total_amount": proposal.total_amount,
        "line_items": [
            {
                "code": i.get("code"),
                "label": i.get("label"),
                "unit": i.get("unit"),
                "unit_price": i.get("unit_price"),
                "quantity": i.get("quantity"),
                "line_total": i.get("line_total"),
            }
            for i in (proposal.line_items or [])
        ],
        "template_version": proposal.template_version,
        "pricing_version": proposal.pricing_version,
    }


def _said(text: Any) -> str:
    """One sentence, compared the way a person would read it aloud.

    Case and runs of spaces are not a decision anybody made, so a tap that
    arrived as "Yes, these are all correct " is the same approval as the one
    the review offered. Nothing else is folded: this is the comparison a
    document gets written on.
    """
    return " ".join(str(text or "").split()).casefold()


class ProposalAgent(BaseAgent):
    name = "proposal"
    description = "Creates and edits proposals; prepares them for sending."
    system_prompt = (
        "You are the Proposal Agent. You build proposals from the organisation's "
        "template and pricing table, apply the user's edits, and prepare the "
        "email for one-tap approval. Always call get_proposal first when editing, "
        "so you know the line item codes. Quantities and prices you pass must "
        "come from the user's words or the pricing table — never invent numbers. "
        "When asked to create AND send, do both steps (create, then prepare_email). "
        "\n\n"
        "SOME PROPOSALS ARE FILLED IN BY ASKING. When a programme's template is "
        "a Word document whose author left tags in it, `create_proposal` does "
        "not draft anything: it opens a fill and asks you to put questions to "
        "the user. After that, every reply they give about those questions goes "
        "to `answer_proposal_questions` with their words as they said them -- "
        "NEVER to `create_proposal` again. Calling `create_proposal` a second "
        "time cannot make progress: the fill is already open and you would ask "
        "the same questions again. Use `show_proposal_questions` if they ask "
        "what is still outstanding, and `confirm_proposal_values` when they "
        "approve the list of values or want one of them changed."
        "\n\n"
        "AN MOU IS A SEPARATE DOCUMENT WITH ITS OWN PIPELINE. \"Create the "
        "MOU for IBC\" means `create_mou`, never `create_proposal`. It opens "
        "a fill and asks you to put questions to the user, exactly as a "
        "tagged proposal does. Every reply they give about those questions "
        "goes to `answer_mou_questions` -- NEVER to `create_mou` again. "
        "Calling `create_mou` a second time cannot make progress: the fill is "
        "already open and you would ask the same questions again. Use "
        "`show_mou_questions` if they ask what is outstanding, "
        "`confirm_mou_values` when they approve the list or want one changed, "
        "and `correct_mou` to change a value in an MOU that has already been "
        "built. An MOU is a contract, not a proposal: it never has line items "
        "or a total to edit, so `edit_narrative` and `update_line_items` are "
        "not for it."
    )

    #: The fill tools that can act on what the person just said. A turn that
    #: called one of these has had its chance at the reply (D48).
    CHANGES_THE_FILL = frozenset(
        name
        for names in fill_tools.TOOLS.values()
        for key, name in names.items()
        if key in ("create", "answer", "confirm", "correct")
    )

    #: Every fill tool draws a question card in the app, so the agent's own
    #: prose never re-lists what the card already says (D48).
    CARD_TOOLS = frozenset(
        name
        for names in fill_tools.TOOLS.values()
        for key, name in names.items()
        if key != "noun"
    )

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="create_proposal",
                description="Build a new proposal draft for a client from a program's template + current pricing.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "program": {"type": "string", "description": "program code or name, e.g. IBC"},
                        "quantities": {
                            "type": "object",
                            "description": "optional map of item code -> quantity the user asked for",
                        },
                        "context_note": {
                            "type": "string",
                            "description": "optional 1-2 sentence context from the meeting",
                        },
                        "start_over": {
                            "type": "boolean",
                            "description": (
                                "true ONLY if the user explicitly asked for a new "
                                "proposal from scratch although this conversation "
                                "already built one"
                            ),
                        },
                    },
                    "required": ["client", "program"],
                },
                handler=self._create,
            ),
            ToolSpec(
                name="get_proposal",
                description="Fetch a proposal's line items (codes, quantities, prices) and status.",
                parameters={
                    "type": "object",
                    "properties": {
                        "proposal_ref": {"type": "string", "description": "proposal id or client name"}
                    },
                },
                handler=self._get,
            ),
            ToolSpec(
                name="update_line_items",
                description=(
                    "Apply commercial edits the user actually asked for "
                    "(quantities, human-directed prices, add/remove items). "
                    "Does NOT apply to a docx_simple proposal -- one filled by "
                    "the assistant keeps its prices inside its own document."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "proposal_ref": {"type": "string"},
                        "operations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "type": "string",
                                        "description": "set_quantity | set_unit_price | add_item | remove_item",
                                    },
                                    "code": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unit_price": {"type": "number"},
                                    "label": {"type": "string"},
                                    "unit": {"type": "string"},
                                },
                                "required": ["op", "code"],
                            },
                        },
                        "instruction": {"type": "string", "description": "the user's original words"},
                    },
                    "required": ["operations"],
                },
                handler=self._update_items,
            ),
            ToolSpec(
                name="edit_narrative",
                description=(
                    "Rewrite the proposal's wording per the user's instruction "
                    "(numbers stay locked). Does NOT apply to a docx_simple "
                    "proposal -- one filled by the assistant from the tags in "
                    "its own Word document has no wording here to rewrite."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "proposal_ref": {"type": "string"},
                        "instruction": {"type": "string"},
                    },
                    "required": ["instruction"],
                },
                handler=self._edit_narrative,
            ),
            ToolSpec(
                name="prepare_email",
                description=(
                    "Draft the proposal email (PDF attached) for one-tap approval. "
                    "Leave to_contact EMPTY unless the user named who should "
                    "receive it in this conversation: the client's main contact "
                    "is used, or the user is asked. Never put the client, the "
                    "programme, or a value from the document in to_contact."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "proposal_ref": {"type": "string"},
                        "to_contact": {
                            "type": "string",
                            "description": (
                                "ONLY a recipient the user named: their name, "
                                "job title or email address, never the client's "
                                "name. Omit it when the user named nobody."
                            ),
                        },
                        "cc_contacts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "names/titles/emails to CC",
                        },
                    },
                },
                handler=self._prepare_email,
            ),
            ToolSpec(
                name="answer_proposal_questions",
                description=(
                    "Pass on the user's answer to the questions you asked "
                    "about a Word-document proposal. Send their words as "
                    "they said them -- one sentence may answer several "
                    "questions at once."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "answer": {
                            "type": "string",
                            "description": "the user's reply, in their own words",
                        },
                    },
                    "required": ["answer"],
                },
                handler=self._answer_questions,
            ),
            ToolSpec(
                name="show_proposal_questions",
                description=(
                    "List the questions still open on the Word-document "
                    "proposal this conversation is filling in. Answers "
                    "nothing and changes nothing."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self._show_questions,
            ),
            ToolSpec(
                name="confirm_proposal_values",
                description=(
                    "The user has seen the list of values about to go into "
                    "the Word document. Call this with approved=true if they "
                    "accepted it, or with their words in `correction` if they "
                    "want something changed. Approving BUILDS the document."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "approved": {
                            "type": "boolean",
                            "description": "true only if the user accepted every value",
                        },
                        "correction": {
                            "type": "string",
                            "description": "what they want changed, in their own words",
                        },
                    },
                },
                handler=self._confirm_values,
            ),
            ToolSpec(
                name="correct_proposal",
                description=(
                    "Change a value in a proposal that has ALREADY been built "
                    "from a Word document, then show the user the updated list "
                    "for approval. Use this when they point at something wrong "
                    "in a finished proposal -- never edit_narrative or "
                    "update_line_items, which cannot reach inside the document."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "correction": {
                            "type": "string",
                            "description": "what is wrong and what it should say, in their words",
                        },
                    },
                    "required": ["correction"],
                },
                handler=self._correct_built,
            ),
            ToolSpec(
                name="show_proposal_review",
                description=(
                    "Show the user every value about to go into the Word "
                    "document, and where each one came from. Changes nothing."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self._show_review,
            ),
            # --- the MOU, which is a contract and not a proposal (D-A) ---
            ToolSpec(
                name="create_mou",
                description=(
                    "Start a memorandum of understanding for a client from "
                    "the programme's MOU template. Use this for \"create the "
                    "MOU\", \"draft the MoU\", \"draw up the contract\" -- "
                    "NEVER create_proposal, which builds a different document "
                    "and puts it in the sales pipeline. Opens a fill and asks "
                    "the user the document's own questions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "program": {
                            "type": "string",
                            "description": "program code or name, e.g. IBC",
                        },
                    },
                    "required": ["client", "program"],
                },
                handler=self._create_mou,
            ),
            ToolSpec(
                name="answer_mou_questions",
                description=(
                    "Pass on the user's answer to the questions you asked "
                    "about an MOU. Send their words as they said them -- one "
                    "sentence may answer several questions at once. Every "
                    "reply about an open MOU comes here, never to create_mou."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "answer": {
                            "type": "string",
                            "description": "the user's reply, in their own words",
                        },
                    },
                    "required": ["answer"],
                },
                handler=self._answer_mou_questions,
            ),
            ToolSpec(
                name="show_mou_questions",
                description=(
                    "List the questions still open on the MOU this "
                    "conversation is filling in. Answers nothing and changes "
                    "nothing."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self._show_mou_questions,
            ),
            ToolSpec(
                name="confirm_mou_values",
                description=(
                    "The user has seen the list of values about to go into "
                    "the MOU. Call this with approved=true if they accepted "
                    "it, or with their words in `correction` if they want "
                    "something changed. Approving BUILDS the contract."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "approved": {
                            "type": "boolean",
                            "description": "true only if the user accepted every value",
                        },
                        "correction": {
                            "type": "string",
                            "description": "what they want changed, in their own words",
                        },
                    },
                },
                handler=self._confirm_mou_values,
            ),
            ToolSpec(
                name="correct_mou",
                description=(
                    "Change a value in an MOU that has ALREADY been built, "
                    "then show the user the updated list for approval. This "
                    "is the ONLY way to change a finished MOU -- "
                    "edit_narrative and update_line_items cannot reach inside "
                    "the document and refuse for a contract."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "correction": {
                            "type": "string",
                            "description": "what is wrong and what it should say, in their words",
                        },
                    },
                    "required": ["correction"],
                },
                handler=self._correct_mou,
            ),
            ToolSpec(
                name="show_mou_review",
                description=(
                    "Show the user every value about to go into the MOU, and "
                    "where each one came from. Changes nothing."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self._show_mou_review,
            ),
        ]

    async def _create(
        self,
        runtime: AgentRuntime,
        client: str,
        program: str,
        quantities: dict[str, Any] | None = None,
        context_note: str | None = None,
        start_over: bool = False,
    ) -> dict[str, Any]:
        lead = await resolve_lead(runtime, client)
        lead_service.ensure_opened(lead, "creating a proposal")
        program_row = await resolve_program(runtime, program)
        if await proposal_fill_service.is_simple_flow(
            runtime.db, runtime.ctx, program_row.id
        ):
            # This chat already BUILT it (Orchid, 27 Sep 2026: "shall I create
            # it?" after the proposal had been built, then every question
            # again and a second proposal for the same client). Only an
            # explicit fresh start opens the questions again.
            built = None if start_over else await _proposal_from_this_chat(runtime)
            if (built is not None and built.lead_id == lead.id
                    and built.program_id == program_row.id
                    and await proposal_fill_service.find_for_chat(
                        runtime.db, runtime.ctx,
                        chat_session_id=runtime.extra_context.get("session_id"),
                        document_type="proposal") is None):
                runtime.extra_context["proposal_id"] = built.id
                return {
                    "already_built": True, **_proposal_summary(built),
                    "what_to_do": (
                        "This proposal was already built in this conversation. "
                        "Do NOT ask the user to create it again. To send it, call "
                        "prepare_email (leave to_contact empty unless the user "
                        "named the recipient). To change a value, call "
                        "correct_proposal. Call create_proposal with "
                        "start_over=true ONLY if the user explicitly asked for a "
                        "new proposal from scratch."
                    ),
                }
            # A simple-flow template is filled tag by tag, with the person
            # in the chat answering what the document asks. Building it
            # here would reach proposal_service's refusal, whose advice is
            # to ask Jarvis -- which is what they are already doing.
            return await self._open_fill(runtime, lead, program_row)
        clean_quantities = {}
        for code, qty in (quantities or {}).items():
            try:
                clean_quantities[str(code)] = float(qty)
            except (TypeError, ValueError):
                continue
        proposal = await proposal_service.build_proposal(
            runtime.db,
            runtime.ctx,
            lead_id=lead.id,
            program_id=program_row.id,
            context_summary=context_note,
            quantities=clean_quantities or None,
        )
        runtime.extra_context["proposal_id"] = proposal.id
        return {"created": True, **_proposal_summary(proposal)}

    async def _open_fill(
        self, runtime: AgentRuntime, lead: Any, program_row: Any,
        document_type: str = "proposal",
    ) -> dict[str, Any]:
        """Start -- or pick back up -- the conversation that fills the document.

        Resuming first is not an optimisation. Opening a second fill for the
        same client and programme in the same chat would ask every question
        again and throw away the answers already given, and the salesperson
        would have no way to tell which fill their next sentence reached.
        """
        names = fill_tools.TOOLS[document_type]
        chat = runtime.extra_context.get("session_id")
        session = await proposal_fill_service.find_open(
            runtime.db, runtime.ctx, lead_id=lead.id,
            program_id=program_row.id, chat_session_id=chat,
            document_type=document_type,
        )
        if session is not None:
            waiting = proposal_fill_service.open_questions(session, limit=None)
            if waiting:
                # Re-raising the round here is what made the assistant loop
                # for a real user on 8 September: it looks like progress, so
                # the model asks the same six questions, the person answers
                # again, and nothing is ever recorded. Say plainly that the
                # fill is already open and name the tool that moves it on.
                # A tool result is read as fact; the system prompt is read as
                # advice, and on the fast tier advice is not enough.
                #
                # The tools are named from the document type rather than
                # written in: telling a contract's model to call
                # `answer_proposal_questions` would name a tool that cannot
                # reach its fill, which is the same loop wearing a new hat.
                runtime.extra_context["fill_session_id"] = session.id
                return {
                    "already_open": True,
                    "fill_session_id": session.id,
                    "status": session.status,
                    "still_to_answer": len(waiting),
                    "what_to_do": (
                        f"This {names['noun']} is already being filled in and "
                        f"is waiting on the user's answers. Do NOT call "
                        f"{names['create']} again -- it cannot make progress. "
                        f"If the user has just answered, pass their words to "
                        f"{names['answer']}. If they want to see what is "
                        f"outstanding, call {names['show']}."
                    ),
                }
            # Every question answered: the fill is at the REVIEW. Re-raising
            # the review here is what looped live on 12 Oct 2026 -- tool
            # results are not replayed into the next turn, so the model saw
            # only the review text, took the person's "Yes, these are all
            # correct" back to create_*, got the same review, and so on for
            # as long as they kept tapping. Same remedy as the branch above:
            # say what is open and name the tool that moves it on, so the
            # model can call it in this same turn.
            runtime.extra_context["fill_session_id"] = session.id
            return {
                "already_open": True,
                "at_review": True,
                "fill_session_id": session.id,
                "status": session.status,
                "review": _review_message(session),
                "what_to_do": (
                    f"This {names['noun']} is already filled in and is "
                    f"waiting for the user to check the values in `review`. "
                    f"Do NOT call {names['create']} again -- it cannot make "
                    f"progress. If the user's latest message asks to change "
                    f"ANYTHING (\"wrong\", \"looks bad\", \"should be\", "
                    f"\"make it\", a new value), call {names['confirm']} with "
                    f"their whole message in correction and approved=false "
                    f"-- never approve a message that asks for a change. Only "
                    f"if it accepts every value and asks for no change (for "
                    f"example \"Yes, these are all correct\", \"go ahead\"), "
                    f"call {names['confirm']} with approved=true. Otherwise "
                    f"show them `review` exactly as written and ask them to "
                    f"check it."
                ),
            }

        # Nothing of THIS kind is open -- but a document of the other kind may
        # be, and until D48 that sailed straight past the loop-breaker above,
        # which is keyed on the type. `create_proposal` with a contract
        # mid-fill in the same chat opened a SECOND fill: two sets of
        # questions, and the person's next sentence reaching whichever one the
        # model happened to name. `test_tool_choice` reproduced it the moment
        # its word-scoring tipped from `create_mou` to `create_proposal`.
        other = await self._other_document_waiting(runtime, document_type)
        if other is not None:
            return other

        session = await proposal_fill_service.open_session(
            runtime.db, runtime.ctx, lead_id=lead.id,
            program_id=program_row.id, chat_session_id=chat,
            document_type=document_type,
        )
        return self._round(runtime, session, lead_name=lead.name,
                           document_type=document_type)

    async def _other_document_waiting(
        self, runtime: AgentRuntime, document_type: str
    ) -> dict[str, Any] | None:
        """A document of the OTHER kind, mid-fill in this same conversation.

        One conversation fills one document at a time. Not a preference: the
        two fills would ask their questions into the same chat, and a reply
        would reach whichever one the model named rather than the one the
        person was reading. The answer already given to the first would be
        thrown away by nobody noticing.

        Shaped exactly like the loop-breaker above, because the model has to
        read it the same way -- what is open, and which tool moves it on.
        Returns None when there is nothing waiting, which is the ordinary
        case: a contract AFTER its proposal is finished is the whole point of
        the pipeline, and a built or abandoned fill is not waiting on anyone.
        """
        chat = runtime.extra_context.get("session_id")
        if not chat:
            return None
        other_type = "proposal" if document_type == "mou" else "mou"
        session = await proposal_fill_service.find_for_chat(
            runtime.db, runtime.ctx, chat_session_id=chat,
            document_type=other_type)
        if session is None:
            return None
        # Not "is it waiting for answers" but "is it finished". A fill at
        # its D13 review has nothing outstanding and is still the document
        # this conversation is filling -- and it is the moment the person is
        # closest to having one, so it is the worst moment to start another.
        waiting = proposal_fill_service.open_questions(session, limit=None)
        names = fill_tools.TOOLS[other_type]
        next_tool = names["answer"] if waiting else names["confirm"]
        runtime.extra_context["fill_session_id"] = session.id
        return {
            "already_open": True,
            "fill_session_id": session.id,
            "status": session.status,
            "still_to_answer": len(waiting),
            "what_to_do": (
                f"A {names['noun']} -- not the document you just asked for --"
                f" is already being filled in in this conversation and is "
                f"waiting on the user. Finish it first: pass their words to "
                f"{next_tool}, or call {names['show']} if they want to see "
                f"what is outstanding. Do NOT start a second document: the "
                f"answers already given belong to this one."
            ),
        }

    async def _create_mou(
        self, runtime: AgentRuntime, client: str, program: str,
    ) -> dict[str, Any]:
        """Open the conversation that fills a contract.

        There is NO non-tagged branch here, and that is the difference from
        `create_proposal`. An MOU exists only as a Word template with tags in
        it, so a programme without one gets a sentence saying so -- not a
        proposal built quietly in its place, which is the document that
        programme probably DOES have a template for and is the wrong document
        entirely (D-A). Returned rather than raised: the wrong tool must be
        harmless, and a refusal the model can read is how it finds the right
        one.
        """
        lead = await resolve_lead(runtime, client)
        lead_service.ensure_opened(lead, "creating an MOU")
        program_row = await resolve_program(runtime, program)
        if not await proposal_fill_service.is_mou_flow(
            runtime.db, runtime.ctx, program_row.id
        ):
            return {
                "ok": False,
                "message": (
                    f"There is no MOU template for {program_row.name}, so I "
                    "cannot draw up the contract. An Org Admin uploads one as "
                    "a Word document with the placeholders written into it. "
                    "I have created nothing -- a proposal is a different "
                    "document and is not a substitute for a contract."
                ),
            }
        return await self._open_fill(runtime, lead, program_row,
                                     document_type="mou")

    async def _answer_mou_questions(
        self, runtime: AgentRuntime, answer: str
    ) -> dict[str, Any]:
        return await self._answer_questions(runtime, answer,
                                            document_type="mou")

    async def _show_mou_questions(self, runtime: AgentRuntime) -> dict[str, Any]:
        return await self._show_questions(runtime, document_type="mou")

    async def _confirm_mou_values(
        self, runtime: AgentRuntime, approved: bool = False,
        correction: str = "",
    ) -> dict[str, Any]:
        return await self._confirm_values(
            runtime, approved=approved, correction=correction,
            document_type="mou")

    async def _correct_mou(
        self, runtime: AgentRuntime, correction: str
    ) -> dict[str, Any]:
        return await self._correct_built(runtime, correction,
                                         document_type="mou")

    async def _show_mou_review(self, runtime: AgentRuntime) -> dict[str, Any]:
        return await self._show_review(runtime, document_type="mou")

    async def _mou_in_hand(self, runtime: AgentRuntime) -> Any:
        """The MOU this conversation is about, or None.

        Asked of the CONVERSATION, never of `_resolve_proposal`. That is the
        whole point: a contract conversation has no proposal, so resolving one
        would either fail with advice about creating a proposal -- wrong, they
        are holding a contract -- or, if the model passed the client's name,
        succeed against some other document entirely.
        """
        if runtime.extra_context.get("mou_id"):
            return await runtime.db.get(
                MouDocument, runtime.extra_context["mou_id"])
        chat = runtime.extra_context.get("session_id")
        if not chat:
            return None
        built = await proposal_fill_service.find_correctable(
            runtime.db, runtime.ctx, chat_session_id=chat, document_type="mou")
        if built is not None:
            return built
        return await proposal_fill_service.find_for_chat(
            runtime.db, runtime.ctx, chat_session_id=chat, document_type="mou")

    async def _answer_questions(
        self, runtime: AgentRuntime, answer: str,
        document_type: str = "proposal",
    ) -> dict[str, Any]:
        session = await self._fill_in_hand(runtime, document_type)
        session = await proposal_fill_service.apply_answers(
            runtime.db, runtime.ctx, session, answer
        )
        return self._round(runtime, session, document_type=document_type)

    async def _show_questions(
        self, runtime: AgentRuntime, document_type: str = "proposal",
    ) -> dict[str, Any]:
        """The open questions as data. Deliberately does NOT raise: being
        asked what the questions were is not the assistant being unsure,
        and answering it must not count as having asked them again."""
        session = await self._fill_in_hand(runtime, document_type)
        waiting = proposal_fill_service.open_questions(session)
        return {
            "fill_session_id": session.id,
            "status": session.status,
            "remaining": len(
                proposal_fill_service.open_questions(session, limit=None)
            ),
            "questions": [_question_line(q) for q in waiting],
        }

    async def _tool_the_turn_needs(
        self, runtime: AgentRuntime, user_text: str, called: list[str]
    ) -> Any:
        """While a document is being filled in, a reply belongs to its fill.

        D47. Measured on the owner's Orchid contract of 11 September:
        `asked_json` recorded eleven rounds against twenty answers. The turns
        in between are the model repeating the round it had just been handed
        -- "The only remaining MoU question is ... Reply 'Innovation Nexus' to
        finish" -- while the fill sat where it was. The system prompt has said
        every reply goes to the answer tool since A2, and `_open_fill` catches
        the model reaching for `create_mou` instead; neither catches it
        reaching for nothing.

        Only while the fill is ASKING. A fill at its review is NOT forced:
        `confirm_*_values` is the one tool that writes a client-facing
        document, and a tool call nobody made must never be the thing that
        ships one.
        """
        from app.ai.llm import ToolCall
        from app.models.proposal_fill import FillStatus

        # A tool that ACTED on the reply already had it. Not merely one that
        # was called: on the owner's 10:24 turn "Instead of 4k make it 9k" --
        # an answer to the question on screen -- reached `correct_mou`, which
        # edits a contract that has already been built. It failed, said so,
        # and the words were dropped. A tool that reports it could not act has
        # not dealt with them.
        #
        # **This narrows D44 rather than overturning it.** An early
        # `confirm_*_values` is still harmless: it refuses, it builds nothing,
        # and D13's review still stands between every value and the document.
        # What changes is that the sentence the tool ITSELF says to pass on is
        # passed on in the same turn, instead of costing the person one.
        if self._a_fill_tool_acted(runtime):
            return None

        for document_type in ("mou", "proposal"):
            session = await proposal_fill_service.find_for_chat(
                runtime.db, runtime.ctx,
                chat_session_id=runtime.extra_context.get("session_id"),
                document_type=document_type,
            )
            if session is None:
                continue
            # D50. At the review there is nothing left to answer, so the
            # ASKING test above left the owner's tap with nowhere to go: they
            # approved a finished contract, the model addressed the approval
            # to the proposal tools, and the turn ended with the document
            # unwritten and no way forward.
            #
            # **Only the review's own words carry it.** This is the one tool
            # that writes a client-facing file, so the match is exact against
            # the phrase the review offered -- not the model's reading of a
            # sentence, and not a paraphrase. Anything else a person says at
            # the review is asking for a change, and a document written from
            # that would be one nobody approved.
            if session.status == FillStatus.REVIEWING:
                if _said(user_text) == _said(fill_tools.APPROVE):
                    return ToolCall(
                        name=fill_tools.TOOLS[document_type]["confirm"],
                        args={"approved": True},
                    )
                continue
            if session.status != FillStatus.ASKING:
                continue
            if not proposal_fill_service.open_questions(session, limit=None):
                continue
            return ToolCall(
                name=fill_tools.TOOLS[document_type]["answer"],
                # Their words as they said them: what the model wrote in its
                # place is a paraphrase of an answer, and D14 cites the person.
                args={"answer": user_text},
            )
        return None

    def _a_fill_tool_acted(self, runtime: AgentRuntime) -> bool:
        """Did a tool that can change the fill actually change anything?

        Three ways it did not, and each one leaves the person's words
        unanswered: it raised (`ok` is false, which is how `correct_mou`
        reported having no contract to correct); it returned the `already_open`
        or `still_asking` redirect, which say in their own words to pass the
        reply to the answer tool; or it returned its own `ok: false`.

        A tool that ASKED something is not judged here at all -- `run` checks
        that first, which is what keeps `answer_*_questions` from being handed
        the same sentence twice when it ends, as it always does, by raising the
        next round.
        """
        for action in runtime.actions:
            if action.get("tool") not in self.CHANGES_THE_FILL:
                continue
            if not action.get("ok"):
                continue
            result = action.get("result")
            if isinstance(result, dict) and (
                    result.get("still_asking")
                    or result.get("already_open")
                    or result.get("ok") is False):
                continue
            return True
        return False

    async def _fill_in_hand(self, runtime: AgentRuntime,
                            document_type: str = "proposal"):
        names = fill_tools.TOOLS[document_type]
        session = await proposal_fill_service.find_for_chat(
            runtime.db, runtime.ctx,
            chat_session_id=runtime.extra_context.get("session_id"),
            document_type=document_type,
        )
        if session is None:
            raise NotFoundError(await self._nothing_of_that_kind(
                runtime, document_type, names))
        runtime.extra_context["fill_session_id"] = session.id
        return session

    async def _nothing_of_that_kind(
        self, runtime: AgentRuntime, document_type: str, names: dict
    ) -> str:
        """What to say when the document this tool is for is not open.

        D50, and the owner's 13:52 turn. They tapped "Yes, these are all
        correct" on a finished contract's review; the model called
        `confirm_proposal_values`; and what came back was "there is no
        proposal being filled in this conversation -- ask me to create one",
        so the assistant offered to start a proposal for a contract that was
        one tap from being written.

        There was no proposal. There was an MOU, finished, waiting on exactly
        that tap. A tool that cannot act has to say what IS open and name the
        tool that can -- the rule `create_*` has followed since A2, which the
        three tools behind this one had never been given.
        """
        other_type = "proposal" if document_type == "mou" else "mou"
        other = await proposal_fill_service.find_for_chat(
            runtime.db, runtime.ctx,
            chat_session_id=runtime.extra_context.get("session_id"),
            document_type=other_type)
        if other is None:
            return (f"There is no {names['noun']} being filled in this "
                    f"conversation. Ask me to create one for a client and a "
                    f"programme first.")
        theirs = fill_tools.TOOLS[other_type]
        waiting = proposal_fill_service.open_questions(other, limit=None)
        next_tool = theirs["answer"] if waiting else theirs["confirm"]
        return (
            f"There is no {names['noun']} in this conversation, but there IS "
            f"a {theirs['noun']} being filled in it, and it is what the user "
            f"is talking about. Call {next_tool} instead -- not "
            f"{names['confirm']}, not {names['answer']}, and do not offer to "
            f"create anything."
        )

    def _round(
        self, runtime: AgentRuntime, session: Any, lead_name: str = "",
        document_type: str = "proposal",
    ) -> dict[str, Any]:
        """Ask the next round, or report that the fill is ready to review.

        The questions go out as one NeedsConfirmationError carrying up to
        QUESTIONS_PER_ROUND of them (D5). The Innovation Lab template alone
        forces nineteen, and nineteen round trips is an interrogation rather
        than a conversation.
        """
        runtime.extra_context["fill_session_id"] = session.id
        waiting = proposal_fill_service.open_questions(session)
        if not waiting:
            # D13. Nothing is written until a human has seen every value,
            # the silently-filled ones included, so the end of the
            # questions is not the end of the job -- it is the review.
            raise NeedsConfirmationError(
                _review_message(session),
                candidates=[APPROVE],
            )
        total = len(proposal_fill_service.open_questions(session, limit=None))
        raise NeedsConfirmationError(
            _round_message(waiting, total, lead_name),
            candidates=_round_candidates(waiting),
        )

    async def _confirm_values(
        self, runtime: AgentRuntime, approved: bool = False,
        correction: str = "", document_type: str = "proposal",
    ) -> dict[str, Any]:
        """The D13 gate. Approving is the only way a document gets written.

        A correction wins over an approval when both arrive: a model that
        sets approved=true while passing on words asking for a change has
        misread the user, and building the document is the half of that
        which cannot be undone.
        """
        session = await self._fill_in_hand(runtime, document_type)
        if correction.strip():
            before = [dict(t) for t in session.tags_json]
            session = await proposal_fill_service.apply_correction(
                runtime.db, runtime.ctx, session, correction
            )
            if [dict(t) for t in session.tags_json] == before:
                raise NeedsConfirmationError(
                    "I could not tell which of these you meant. Here they "
                    "are again -- name the row and what it should say.\n\n"
                    + _review_message(session),
                    candidates=[APPROVE],
                )
            return self._round(runtime, session, document_type=document_type)

        # The wrong tool must be harmless (D44), and this one was not. On the
        # Orchid contract (11 September) the fast-tier model read the round's
        # "All the suggested values are fine" tap as an approval and called
        # this with forty-four questions open; `mark_ready` refused, the tool
        # crashed, and the model improvised a paragraph about checkpoints.
        # There is nothing to approve before the review, so say so and name
        # the tool that moves the fill on.
        waiting = proposal_fill_service.open_questions(session, limit=None)
        if waiting:
            names = fill_tools.TOOLS[document_type]
            return {
                "ok": False,
                "still_asking": True,
                "fill_session_id": session.id,
                "status": session.status,
                "still_to_answer": len(waiting),
                "what_to_do": (
                    f"Nothing can be approved yet: this {names['noun']} "
                    f"still has {len(waiting)} unanswered "
                    f"question{'' if len(waiting) == 1 else 's'}, and the "
                    f"user has not been shown the review. If they just "
                    f"answered a question or accepted the suggested values, "
                    f"pass their words to {names['answer']}. Call "
                    f"{names['confirm']} only after they have seen the full "
                    f"list of values."
                ),
            }

        if not approved:
            raise NeedsConfirmationError(
                _review_message(session), candidates=[APPROVE])

        # D-E's gate (plan amendment D). An approval with a mismatch standing
        # is refused ONCE: the sentence names which two of the person's own
        # answers disagree, and saying it again on the next approval would
        # teach them to dismiss it. A negotiated total that is not price x
        # students is a normal thing for a contract to contain, so this asks
        # rather than refuses -- and the figure written is theirs either way,
        # because nothing here computes a value (D15).
        #
        # A proposal never reaches this: relations are proposed for MOUs only,
        # so `unacknowledged_arithmetic` is empty and the gate is a no-op.
        standing = proposal_fill_service.unacknowledged_arithmetic(session)
        if standing:
            await proposal_fill_service.acknowledge_arithmetic(
                runtime.db, session)
            return {
                "ok": False,
                "arithmetic": list(standing.values()),
                "message": (
                    "Before I write this -- "
                    + "; ".join(standing.values())
                    + ". If that is what was agreed, tell me again and I "
                      "will write it exactly as it stands."
                ),
            }

        session = await proposal_fill_service.mark_ready(runtime.db, session)
        document = await proposal_fill_service.build(
            runtime.db, runtime.ctx, session)
        if document_type == "mou":
            runtime.extra_context["mou_id"] = document.id
            return {"created": True, "built_from": "mou_simple",
                    **_mou_summary(document)}
        runtime.extra_context["proposal_id"] = document.id
        return {"created": True, "built_from": "docx_simple",
                **_proposal_summary(document)}

    async def _correct_built(
        self, runtime: AgentRuntime, correction: str,
        document_type: str = "proposal",
    ) -> dict[str, Any]:
        """Correct a finished document, and put the review again.

        Deliberately raises the review rather than rebuilding on the spot: a
        correction is a change to a document a person is about to send, and
        D13's rule -- nothing written until they have seen every value -- does
        not lapse because the document happens to exist already.
        """
        names = fill_tools.TOOLS[document_type]
        session = await proposal_fill_service.find_correctable(
            runtime.db, runtime.ctx,
            chat_session_id=runtime.extra_context.get("session_id"),
            document_type=document_type,
        )
        if session is None:
            # Nothing BUILT -- but a fill of this kind may be open in this
            # chat, waiting at its review. Live on 12 Oct 2026 the person
            # corrected a value on the review list, the model chose this
            # tool, and "there is no proposal ... ask me to create one" sent
            # it offering a second proposal for a document one tap from
            # being written. A correction before the build is exactly what
            # the confirm tool takes, so hand it there.
            open_fill = await proposal_fill_service.find_for_chat(
                runtime.db, runtime.ctx,
                chat_session_id=runtime.extra_context.get("session_id"),
                document_type=document_type,
            )
            if open_fill is not None:
                if proposal_fill_service.open_questions(open_fill, limit=None):
                    runtime.extra_context["fill_session_id"] = open_fill.id
                    return {
                        "ok": False,
                        "still_asking": True,
                        "fill_session_id": open_fill.id,
                        "what_to_do": (
                            f"This {names['noun']} is not built yet and still "
                            f"has questions open. Pass the user's words to "
                            f"{names['answer']}; do not offer to create "
                            f"anything."
                        ),
                    }
                return await self._confirm_values(
                    runtime, approved=False, correction=correction,
                    document_type=document_type)
            raise NotFoundError(
                f"There is no {names['noun']} from this conversation that I "
                f"can correct. Ask me to create one and I will fill it in "
                f"with you."
            )
        before = [dict(t) for t in session.tags_json]
        session = await proposal_fill_service.reopen_for_correction(
            runtime.db, runtime.ctx, session, correction
        )
        if [dict(t) for t in session.tags_json] == before:
            raise NeedsConfirmationError(
                "I could not tell which value you meant. Here is what the "
                "document says -- name the row and what it should say.\n\n"
                + _review_message(session),
                candidates=[APPROVE],
            )
        runtime.extra_context["fill_session_id"] = session.id
        return self._round(runtime, session, document_type=document_type)

    async def _show_review(
        self, runtime: AgentRuntime, document_type: str = "proposal",
    ) -> dict[str, Any]:
        """Every value and its origin, as data. Writes nothing."""
        session = await self._fill_in_hand(runtime, document_type)
        return {
            "fill_session_id": session.id,
            "status": session.status,
            "still_to_answer": len(
                proposal_fill_service.open_questions(session, limit=None)
            ),
            "values": proposal_fill_service.review_lines(session),
        }

    async def _get(
        self, runtime: AgentRuntime, proposal_ref: str | None = None
    ) -> dict[str, Any]:
        proposal = await _resolve_proposal(runtime, proposal_ref)
        runtime.extra_context["proposal_id"] = proposal.id
        return _proposal_summary(proposal)

    async def _update_items(
        self,
        runtime: AgentRuntime,
        operations: list[dict[str, Any]],
        proposal_ref: str | None = None,
        instruction: str | None = None,
    ) -> dict[str, Any]:
        # BEFORE resolving anything: see NOT_EDITABLE_MOU. Resolving first
        # is how a contract conversation reaches a different client document.
        if await self._mou_in_hand(runtime) is not None:
            return {"ok": False, "message": NOT_EDITABLE_MOU}
        proposal = await _resolve_proposal(runtime, proposal_ref)
        _guard_editing(proposal)
        notes = proposal_service.apply_line_item_ops(proposal, operations)
        await proposal_service.record_edit(
            runtime.db, runtime.ctx, proposal,
            instruction=instruction or "; ".join(notes),
        )
        runtime.extra_context["proposal_id"] = proposal.id
        return {"updated": True, "changes": notes, **_proposal_summary(proposal)}

    async def _edit_narrative(
        self,
        runtime: AgentRuntime,
        instruction: str,
        proposal_ref: str | None = None,
    ) -> dict[str, Any]:
        # BEFORE resolving anything, and before the price guard. Defect 3
        # refused only because the instruction happened to contain a price;
        # this refuses on the path that does NOT trip that guard, which is the
        # path where the old code reported success over a file it never moved.
        if await self._mou_in_hand(runtime) is not None:
            return {"ok": False, "message": NOT_EDITABLE_MOU}
        proposal = await _resolve_proposal(runtime, proposal_ref)
        _guard_editing(proposal)
        new_content = await rewrite_narrative(
            runtime.ctx, proposal.content_md, instruction
        )
        proposal_service.apply_narrative_edit(proposal, new_content)
        await proposal_service.record_edit(
            runtime.db, runtime.ctx, proposal, instruction=instruction
        )
        runtime.extra_context["proposal_id"] = proposal.id
        return {"updated": True, "note": "Wording updated; commercial table unchanged."}

    async def _recipient_words(self, runtime: AgentRuntime, lead: Any, proposal: Any):
        """`recipient_said`, bound to this conversation: what the person said,
        their answers to this chat's document questions, and the names that
        are never a recipient (the client, the programme)."""
        from app.models.program import Program
        from app.models.proposal_fill import ProposalFillSession

        chat = runtime.extra_context.get("session_id")
        replies: list[str] = []
        if chat:
            for fill in (await runtime.db.execute(select(ProposalFillSession).where(
                    ProposalFillSession.org_id == runtime.ctx.org_id,
                    ProposalFillSession.user_id == runtime.ctx.user_id,
                    ProposalFillSession.chat_session_id == chat))).scalars().all():
                replies += [str(r.get("reply") or "") for r in (fill.asked_json or [])
                            if isinstance(r, dict)]
        program = (await runtime.db.execute(select(Program).where(
            Program.id == proposal.program_id))).scalar_one_or_none()
        not_names = [lead.name] + ([program.name, program.code] if program else [])
        said = list(runtime.extra_context.get("_said_by_user") or [])

        def check(hint: str | None) -> bool:
            return recipient_said(hint, said=said, fill_replies=replies,
                                  not_names=[n for n in not_names if n])
        return check

    async def _prepare_email(
        self,
        runtime: AgentRuntime,
        proposal_ref: str | None = None,
        to_contact: str | None = None,
        cc_contacts: list[str] | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        proposal = await _resolve_proposal(runtime, proposal_ref)
        lead = await resolve_lead(runtime, proposal.lead_id)

        # A recipient only from the person's own words (see recipient_said).
        # Without one, nobody is guessed: the main contact, the only contact,
        # or a question.
        said = await self._recipient_words(runtime, lead, proposal)
        if not said(to_contact):
            to_contact = None
        cc_hints = [h for h in (cc_contacts or []) if said(h)]

        contact_id = None
        try:
            if to_contact and "@" in to_contact:
                to_address = to_contact.strip()
                to_name = to_address
            else:
                contact = await resolve_contact(runtime, lead, to_contact)
                contact_id = contact.id
                if not contact.email:
                    reachable = [c.name for c in (await db.execute(select(Contact).where(
                        Contact.org_id == ctx.org_id, Contact.lead_id == lead.id)
                    )).scalars().all() if c.email]
                    raise NeedsConfirmationError(
                        f"{contact.name} has no email on record. Who should "
                        "receive the proposal instead?"
                        + (f" I have {', '.join(reachable)}, or type an email address."
                           if reachable else " Type an email address."),
                        candidates=reachable,
                    )
                to_address, to_name = contact.email, contact.name
        except NeedsConfirmationError as question:
            # Held, so the answer comes back here and not to whichever agent
            # the router would pick for a bare name (2 Oct 2026). Only the
            # recipient's question: a CC question asks as it always did.
            await proposal_recipient.hold(
                db, ctx, runtime.extra_context.get("session_id"),
                proposal_id=proposal.id, lead_id=lead.id, cc=[],
                question=question.message, candidates=question.candidates)
            raise

        cc_addresses: list[str] = []
        for hint in cc_hints:
            if "@" in hint:
                cc_addresses.append(hint.strip())
            else:
                cc_contact = await resolve_contact(runtime, lead, hint)
                if cc_contact.email:
                    cc_addresses.append(cc_contact.email)

        # The product's own proposal email (28 Oct 2026), when the dashboard
        # has one: it is filled and drafted like every template email, with
        # this client's built proposal attached. Without one, the fixed email
        # below is sent exactly as before.
        from app.ai.agents import email_fill_tools  # noqa: PLC0415
        from app.services import email_template_service  # noqa: PLC0415

        template = await email_template_service.product_template_for(
            db, ctx.org_id, proposal.program_id, "proposal")
        if template is not None:
            return await email_fill_tools.start(
                runtime, template=template, lead=lead, to_address=to_address,
                cc=cc_addresses, contact_id=contact_id,
                chat_session_id=runtime.extra_context.get("session_id"))

        message = await proposal_email_service.prepare_proposal_email(
            db, ctx, proposal, to_address=to_address, cc=cc_addresses
        )
        runtime.pending_approvals.append(
            {
                "message_id": message.id,
                "kind": "proposal_email",
                "to": to_address,
                "cc": cc_addresses,
                "subject": message.subject,
            }
        )
        return {
            "ready_for_approval": True,
            "message_id": message.id,
            "to": f"{to_name} <{to_address}>",
            "cc": cc_addresses,
            "note": "Awaiting the user's one-tap Approve & Send.",
        }


_REWRITE_PROMPT = """Rewrite this sales proposal per the instruction. Rules:
- Keep it professional and warm; keep the same overall structure and headings.
- Do NOT change, add or remove any prices, quantities or totals.
- Keep every {{placeholder}}-free — output the final text, not a template.
- The commercial table (between pricing markers) will be re-inserted
  automatically; you may leave it out or copy it unchanged.
Return ONLY the rewritten Markdown document.

INSTRUCTION: {instruction}

CURRENT PROPOSAL:
{content}
"""


async def rewrite_narrative(ctx: OrgContext, content_md: str, instruction: str) -> str:
    response = await get_model_layer().generate(
        purpose="proposal.rewrite_narrative",
        tier=TIER_STRONG,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        messages=[
            {
                "role": "user",
                "content": _REWRITE_PROMPT.format(instruction=instruction, content=content_md),
            }
        ],
        temperature=0.4,
        max_tokens=8192,
    )
    return response.text.strip()


_EDIT_PARSE_PROMPT = """A salesperson wants to edit a proposal. Convert their
instruction into structured operations.

Line items currently in the proposal (code | label | unit_price | quantity):
{items}

Instruction: "{instruction}"

Return JSON:
{{
  "line_ops": [  // commercial changes; [] if none
    {{"op": "set_quantity"|"set_unit_price"|"add_item"|"remove_item",
      "code": "...", "quantity": 0, "unit_price": 0, "label": "...", "unit": "..."}}
  ],
  "narrative_instruction": "..." or null  // wording changes; null if none
}}
Only include fields relevant to each op. Prices/quantities must come from the
instruction itself — never invent numbers."""


_DOCX_EDIT_PROMPT = """A salesperson wants to change a proposal built from a \
document template. Turn their instruction into structured edits.

Commercial line items (code | label | unit_price | quantity):
{items}

Sections of the document the AI wrote, which can be rewritten:
{placeholders}

Instruction: "{instruction}"

Return JSON:
{{
  "line_ops": [ {{"op": "set_quantity"|"set_unit_price"|"add_item"|"remove_item",
                  "code": "...", "quantity": 0, "unit_price": 0,
                  "label": "...", "unit": "..."}} ],
  "placeholder_keys": ["..."],
  "placeholder_instruction": "..." or null
}}

Only list a placeholder key that appears above. Prices and quantities must come \
from the instruction itself — never invent numbers. The document's fixed \
content and its price table cannot be reworded; if the instruction asks for \
that, return empty lists."""


async def parse_docx_edit(ctx, proposal, instruction: str):
    """-> (placeholder_keys, placeholder_instruction, line_ops)"""
    known = {
        f["key"]: f
        for f in (proposal.filled_json or [])
        if f.get("kind") in ("insert", "replace")
    }
    items_desc = "\n".join(
        f"- {i.get('code')} | {i.get('label')} | {i.get('unit_price')} | {i.get('quantity')}"
        for i in (proposal.line_items or [])
    ) or "- (none)"
    placeholders_desc = "\n".join(
        f'- "{key}": {row.get("brief") or "(no brief)"} — currently: '
        f'{(row.get("text") or "")[:90]}'
        for key, row in known.items()
    ) or "- (none)"

    data = await get_model_layer().generate_json(
        purpose="proposal.parse_docx_edit",
        tier=TIER_FAST,
        org_id=getattr(ctx, "org_id", None),
        user_id=getattr(ctx, "user_id", None),
        messages=[{"role": "user", "content": _DOCX_EDIT_PROMPT.format(
            items=items_desc, placeholders=placeholders_desc, instruction=instruction,
        )}],
        json_schema={
            "type": "object",
            "properties": {
                "line_ops": {"type": "array", "items": {"type": "object"}},
                "placeholder_keys": {"type": "array", "items": {"type": "string"}},
                "placeholder_instruction": {"type": "string", "nullable": True},
            },
            "required": ["line_ops"],
        },
        temperature=0.1,
    )
    keys = [k for k in (data.get("placeholder_keys") or []) if k in known]
    line_ops = [
        {k: v for k, v in op.items() if v is not None}
        for op in (data.get("line_ops") or [])
    ]
    return keys, (data.get("placeholder_instruction") or ""), line_ops


async def _apply_docx_edit(
    db: AsyncSession, ctx: OrgContext, proposal: Proposal, instruction: str
) -> dict[str, Any]:
    """Re-fill the named placeholders and rebuild the document.

    Rebuilt from the TEMPLATE SOURCE every time, never from the previous
    output, so formatting cannot erode across successive edits. Placeholders
    the instruction did not name are passed back verbatim rather than
    regenerated.
    """
    from app.models.program import ProposalTemplateDoc
    from app.services import docx_proposal_service, storage

    keys, placeholder_instruction, line_ops = await parse_docx_edit(
        ctx, proposal, instruction
    )

    changes: list[str] = []
    if line_ops:
        changes += proposal_service.apply_line_item_ops(proposal, line_ops)

    docx_bytes: bytes | None = None
    if keys:
        doc_row = (
            await db.execute(
                select(ProposalTemplateDoc).where(
                    ProposalTemplateDoc.template_id == proposal.template_id,
                    ProposalTemplateDoc.org_id == proposal.org_id,
                )
            )
        ).scalar_one_or_none()
        if doc_row is None:
            raise NotFoundError(
                "The document this proposal was built from is missing, so its "
                "sections cannot be rewritten. Re-upload the template."
            )

        plan = dict(doc_row.plan_json or {})
        entries = []
        for entry in (plan.get("entries") or []):
            entry = dict(entry)
            if entry.get("key") in keys and placeholder_instruction:
                entry["brief"] = (
                    f'{entry.get("brief", "")} {placeholder_instruction}'.strip()
                )
            entries.append(entry)
        plan["entries"] = entries

        # everything the instruction did not name keeps the text it already has
        overrides = {
            row["key"]: row.get("text") or ""
            for row in (proposal.filled_json or [])
            if row.get("kind") in ("insert", "replace")
            and row.get("key") not in keys
            and (row.get("text") or "").strip()
        }

        source_bytes = storage.read_bytes(proposal.org_id, doc_row.source_path)
        built = await docx_proposal_service.build_docx_content(
            db, ctx,
            source_bytes=source_bytes, plan=plan,
            variables=proposal.variables or {}, line_items=proposal.line_items or [],
            total_amount=proposal.total_amount, currency=proposal.currency,
            facts={k: v for k, v in (proposal.variables or {}).items()
                   if isinstance(v, str)},
            prose_overrides=overrides,
        )
        docx_bytes = built["docx"]
        proposal.content_md = built["content_md"]
        proposal.filled_json = built["filled"]
        changes.append(f"rewrote {', '.join(sorted(keys))}")

    if not changes:
        changes.append("no changes detected in the instruction")

    # record_edit clears docx_path and pdf_path, because rendered files are
    # stale after an edit. The rebuilt document is written AFTER it: written
    # before, it would be wiped, ensure_rendered_files would see a docx
    # proposal with no document, and fall back to the plain renderer.
    await proposal_service.record_edit(db, ctx, proposal, instruction=instruction)

    if docx_bytes is not None:
        from app.services.proposal_email_service import _safe_name

        proposal.docx_path = storage.save_bytes(
            proposal.org_id, storage.CATEGORY_PROPOSALS,
            f"{_safe_name(proposal.title)}.docx", docx_bytes,
        )

    return {"changes": changes, "total_amount": proposal.total_amount}


async def parse_and_apply_edit(
    db: AsyncSession, ctx: OrgContext, proposal: Proposal, instruction: str
) -> dict[str, Any]:
    """Used by the REST edit endpoint: natural-language instruction -> edits."""
    if getattr(proposal, "template_kind", "markdown") == "docx":
        return await _apply_docx_edit(db, ctx, proposal, instruction)

    items_desc = "\n".join(
        f"- {i.get('code')} | {i.get('label')} | {i.get('unit_price')} | {i.get('quantity')}"
        for i in (proposal.line_items or [])
    )
    data = await get_model_layer().generate_json(
        purpose="proposal.parse_edit",
        tier=TIER_FAST,
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        messages=[
            {
                "role": "user",
                "content": _EDIT_PARSE_PROMPT.format(items=items_desc, instruction=instruction),
            }
        ],
        json_schema={
            "type": "object",
            "properties": {
                "line_ops": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string"},
                            "code": {"type": "string"},
                            "quantity": {"type": "number", "nullable": True},
                            "unit_price": {"type": "number", "nullable": True},
                            "label": {"type": "string", "nullable": True},
                            "unit": {"type": "string", "nullable": True},
                        },
                        "required": ["op", "code"],
                    },
                },
                "narrative_instruction": {"type": "string", "nullable": True},
            },
            "required": ["line_ops"],
        },
        temperature=0.1,
    )
    changes: list[str] = []
    line_ops = [
        {k: v for k, v in op.items() if v is not None}
        for op in data.get("line_ops", [])
    ]
    if line_ops:
        changes += proposal_service.apply_line_item_ops(proposal, line_ops)
    narrative = data.get("narrative_instruction")
    if narrative:
        new_content = await rewrite_narrative(ctx, proposal.content_md, narrative)
        proposal_service.apply_narrative_edit(proposal, new_content)
        changes.append("wording updated")
    if not changes:
        changes.append("no changes detected in the instruction")
    await proposal_service.record_edit(db, ctx, proposal, instruction=instruction)
    return {"changes": changes, "total_amount": proposal.total_amount}
