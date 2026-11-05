# app/ai/agents/email_fill_tools.py
"""What an email fill SAYS, shared by every agent that starts one (28 Oct 2026).

The email agent, the proposal agent (its proposal email), the follow-up agent
and the held recipient flow all hand a template email to the same service and
turn its state into the same three outcomes: a round of questions (a question
card), a warning that the proposal or MOU it carries is not built yet, or a
draft waiting for the one-tap approval.

Nothing here decides a value. `email_fill_service` owns the state and
`docx_tagfill` owns the model calls.
"""
from __future__ import annotations

from typing import Any

from app.ai.agents.base import AgentRuntime
from app.core.exceptions import NeedsConfirmationError
from app.models.email_template import EmailFillSession, EmailFillStatus, EmailTemplate
from app.models.messaging import OutboundMessage
from app.models.program import Program
from app.services import email_fill_service

#: The tap that settles every suggested value at once, the same words the
#: proposal fill offers.
ALL_DEFAULTS = "All the suggested values are fine"

#: How a built document is named to the person.
_NOUNS = {"proposal": "proposal", "mou": "MoU"}


def _about(question: dict[str, Any]) -> str:
    about = (question.get("context") or "").strip().rstrip(":").strip()
    return "" if about.lower() == "dear" else about


def _wording(question: dict[str, Any]) -> str:
    text = (question.get("question") or "").strip()
    if not text or "<" in text:
        # The fallback quotes the raw tag ("What should replace <ask:> ..."),
        # which reads as broken on a phone. Say where it goes instead.
        about = _about(question)
        return f'What should go after "{about}"?' if about else "What should go here?"
    return text


def round_message(questions: list[dict[str, Any]], total: int,
                  template_name: str, client_name: str) -> str:
    more = "" if total <= len(questions) else (
        f" (and {total - len(questions)} more after these)")
    count = len(questions)
    what = (template_name if template_name.lower().endswith("email")
            else f"{template_name} email")
    lines = [f"To write the {what} for {client_name}, I need "
             f"{count} thing{'' if count == 1 else 's'} from you{more}:", ""]
    for number, question in enumerate(questions, start=1):
        about = _about(question)
        text = _wording(question)
        line = f"{number}. {about}: {text}" if about and about not in text else (
            f"{number}. {text}")
        choices = email_fill_service.choices_of(question)
        if choices:
            line += f" ({', '.join(choices)})"
        elif question.get("candidates"):
            line += f" (suggested: {question['candidates'][0]})"
        lines.append(line)
    lines += ["", "Answer in one message."]
    return "\n".join(lines)


def round_candidates(questions: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    multi = False
    for question in questions:
        if email_fill_service.choices_of(question):
            multi = True
        for candidate in question.get("candidates") or []:
            if candidate and candidate not in out:
                out.append(candidate)
    # "All the suggested values are fine" settles nothing for a multi-choice
    # question (its suggestion is the list itself), so it is not offered then.
    if out and not multi:
        out.append(ALL_DEFAULTS)
    return out


def question_line(question: dict[str, Any]) -> dict[str, Any]:
    return {"tag_id": question["tag_id"], "question": _wording(question),
            "about": _about(question) or question.get("raw"),
            "suggested": question.get("candidates") or []}


def approval_entry(message: OutboundMessage, template_name: str,
                   attachments: list[str]) -> dict[str, Any]:
    return {
        "message_id": message.id,
        "kind": "template_email",
        "template": template_name,
        "to": message.to_address,
        "cc": list(message.cc or []),
        "subject": message.subject,
        "body_preview": (message.body or "")[:300],
        "attachments": attachments,
    }


async def missing_document(runtime: AgentRuntime, template: EmailTemplate,
                           lead_name: str) -> dict[str, Any]:
    """The warning for a template whose built proposal or MoU does not exist:
    nothing is drafted, and the person is offered to build it first."""
    product = await runtime.db.get(Program, template.program_id)
    noun = _NOUNS.get(template.built_document, "document")
    name = f"{product.name} " if product is not None else ""
    return {
        "ok": False,
        "waiting_for_document": True,
        "message": (
            f"There is no {name}{noun} for {lead_name} yet, so I will not "
            f"send this email: it says the {noun} is attached. Shall I "
            f"build the {noun} first?"),
        "what_to_do": (
            f"Tell the user exactly this message. Nothing was drafted. If "
            f"they say yes, the {noun} is built through the proposal tools; "
            f"afterwards, asking for this email again sends it."),
    }


async def raise_round(runtime: AgentRuntime, session: EmailFillSession,
                      template: EmailTemplate, lead_name: str) -> dict[str, Any]:
    """The fill's state as a tool outcome: a question card, a warning, or a draft."""
    runtime.extra_context["email_fill_session_id"] = session.id
    if session.status == EmailFillStatus.WAITING_FOR_DOCUMENT:
        return dict(await missing_document(runtime, template, lead_name),
                    fill_session_id=session.id)
    if session.status == EmailFillStatus.ASKING:
        waiting = email_fill_service.open_questions(session)
        total = len(email_fill_service.open_questions(session, limit=None))
        raise NeedsConfirmationError(
            round_message(waiting, total, template.name, lead_name),
            candidates=round_candidates(waiting))
    message = await runtime.db.get(OutboundMessage, session.message_id)
    names = [a.get("filename") for a in (message.attachments or [])]
    runtime.pending_approvals.append(approval_entry(message, template.name, names))
    return {
        "ready_for_approval": True,
        "message_id": message.id,
        "to": message.to_address,
        "subject": message.subject,
        "attachments": names,
        "note": "Awaiting the user's one-tap Approve & Send.",
    }


async def start(runtime: AgentRuntime, *, template: EmailTemplate, lead,
                to_address: str, cc: list[str], contact_id: str | None,
                chat_session_id: str | None) -> dict[str, Any]:
    """Open the fill for an already resolved recipient, and say where it stands."""
    session = await email_fill_service.open_session(
        runtime.db, runtime.ctx, template=template, lead_id=lead.id,
        chat_session_id=chat_session_id, contact_id=contact_id,
        to_address=to_address, cc=cc)
    return await raise_round(runtime, session, template, lead.name)
