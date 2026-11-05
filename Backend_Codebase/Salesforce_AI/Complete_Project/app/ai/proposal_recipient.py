"""Who receives the proposal email, asked and held open (2 Oct 2026).

Measured on Siva's conversations of 27 and 29 September, and on three replays
with the real model: when `prepare_email` had to ask who should receive the
proposal, the person's answer ("Dr. Sudhir") was routed like any new message.
The router sent the bare name to the conversation agent, which offered to add
Dr. Sudhir as a contact; and when it did reach the proposal agent, the
proposal built one turn earlier was out of reach ("there is no proposal in
this conversation"), so it offered to create one and asked every question
again.

So the question is held the way adding a client and arranging a meeting are
(app/ai/confirmations.py): the next message is read as the answer, here,
before any router sees it. It names a contact (in full, in part, by title, or
by the number of the option), or gives an email address; the email is then
drafted for the SAME proposal and comes back as the one-tap approval card.
"cancel" drafts nothing and keeps the proposal. A message about something
else is not forced into an answer: it is routed as usual and the reply offers
to come back to this.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import confirmations
from app.core.context import OrgContext
from app.core.exceptions import NeedsConfirmationError, ValidationFailedError
from app.models.assistant import AssistantPendingAction

KIND = "proposal_recipient"
AGENT = "proposal"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
#: A longer message than this that names no contact is about something else.
_SHORT = 3


def question_action(question: str, candidates: list[str]) -> dict[str, Any]:
    """The question as the app draws it: a card with the contacts as taps."""
    return {"tool": "prepare_email", "args": {}, "ok": False,
            "outcome": "needs_confirmation", "error": question,
            "question": question, "candidates": list(candidates)}


async def hold(db: AsyncSession, ctx: OrgContext, session_id: str | None, *,
               proposal_id: str, lead_id: str, cc: list[str], question: str,
               candidates: list[str]) -> None:
    """Keep the recipient question open in this chat. Without a chat there is
    no next message to read, so nothing is held (the question still asks)."""
    if not session_id:
        return
    await confirmations.save(
        db, ctx, session_id, kind=KIND, agent=AGENT,
        payload={"proposal_id": proposal_id, "lead_id": lead_id, "cc": list(cc),
                 "question": question, "candidates": list(candidates),
                 "paused": False},
        summary=question,
    )


async def _ask(db: AsyncSession, ctx: OrgContext, row: AssistantPendingAction,
               state: dict[str, Any], question: str,
               candidates: list[str]) -> confirmations.Outcome:
    """Ask again and keep holding (the save restarts the expiry clock)."""
    state["question"], state["candidates"], state["paused"] = question, candidates, False
    await confirmations.save(db, ctx, row.session_id, kind=KIND, agent=AGENT,
                             payload=state, summary=question, row=row)
    return confirmations.Outcome(reply=question,
                                 actions=[question_action(question, candidates)])


class _Flow:
    async def handle(self, db: AsyncSession, ctx: OrgContext,
                     row: AssistantPendingAction, text: str,
                     context: dict[str, Any] | None = None
                     ) -> confirmations.Outcome | None:
        from app.ai.agents.base import AgentRuntime, BaseAgent
        from app.ai.agents.resolvers import resolve_contact
        from app.models.lead import Contact, Lead
        from app.models.proposal import Proposal
        from app.services import proposal_email_service

        state = json.loads(row.payload or "{}")
        said = confirmations.words(text)
        verdict = confirmations.classify_reply(text)
        if verdict == confirmations.NO or "cancel" in said:
            await confirmations.drop(db, row)
            return confirmations.Outcome(
                reply="Okay, I haven't drafted the email. The proposal is saved; "
                      "tell me who to send it to whenever you are ready.")

        proposal = (await db.execute(select(Proposal).where(
            Proposal.org_id == ctx.org_id,
            Proposal.id == state.get("proposal_id")))).scalar_one_or_none()
        lead = (await db.execute(select(Lead).where(
            Lead.org_id == ctx.org_id, Lead.id == state.get("lead_id")))).scalar_one_or_none()
        if proposal is None or lead is None:
            await confirmations.drop(db, row)
            return confirmations.Outcome(
                reply="That proposal is no longer on file, so there is nothing to send.")

        if state.get("paused") and verdict == confirmations.YES:
            return await _ask(db, ctx, row, state, state.get("question") or "Who should receive it?",
                        state.get("candidates") or [])

        found = _EMAIL.search(text or "")
        contact_id = None
        if found:
            address, name = found.group(0), found.group(0)
        else:
            if text.strip().endswith("?"):
                return None
            hint = text.strip()
            options = state.get("candidates") or []
            if hint.isdigit() and 1 <= int(hint) <= len(options):
                hint = options[int(hint) - 1]
            runtime = AgentRuntime(db=db, ctx=ctx)
            try:
                contact = await resolve_contact(runtime, lead, hint)
            except NeedsConfirmationError as unsure:
                if len(said) > _SHORT:
                    return None  # a sentence about something else
                return await _ask(db, ctx, row, state, unsure.message, unsure.candidates)
            if not contact.email:
                contacts = (await db.execute(select(Contact).where(
                    Contact.org_id == ctx.org_id, Contact.lead_id == lead.id))).scalars().all()
                reachable = [c.name for c in contacts if c.email]
                question = (f"{contact.name} has no email on record. Who should "
                            "receive the proposal instead?"
                            + (f" I have {', '.join(reachable)}, or type an email address."
                               if reachable else " Type an email address."))
                return await _ask(db, ctx, row, state, question, reachable)
            address, name = contact.email, contact.name
            contact_id = contact.id

        # The product's own proposal email (28 Oct 2026): the same rule as
        # prepare_email. The email fill holds the conversation from here, so
        # this held question is dropped either way.
        from app.ai.agents import email_fill_tools  # noqa: PLC0415
        from app.services import email_template_service  # noqa: PLC0415

        template = await email_template_service.product_template_for(
            db, ctx.org_id, proposal.program_id, "proposal")
        if template is not None:
            runtime = AgentRuntime(db=db, ctx=ctx)
            await confirmations.drop(db, row)
            try:
                await email_fill_tools.start(
                    runtime, template=template, lead=lead, to_address=address,
                    cc=state.get("cc") or [], contact_id=contact_id,
                    chat_session_id=row.session_id)
            except NeedsConfirmationError as question:
                return confirmations.Outcome(
                    reply=question.message.splitlines()[0],
                    actions=[question_action(question.message, question.candidates)])
            await BaseAgent()._enrich_approvals(runtime)
            to = name if name == address else f"{name} <{address}>"
            return confirmations.Outcome(
                reply=f"The proposal email to {to} is ready for your one-tap approval.",
                actions=[{"tool": "prepare_email", "args": {"to_contact": name},
                          "ok": True, "result": {"ready_for_approval": True,
                                                 "to": to}}],
                pending_approvals=runtime.pending_approvals,
            )

        try:
            message = await proposal_email_service.prepare_proposal_email(
                db, ctx, proposal, to_address=address, cc=state.get("cc") or [])
        except ValidationFailedError as exc:
            return await _ask(db, ctx, row, state, f"{exc.message} Who should receive it?",
                        state.get("candidates") or [])
        await confirmations.drop(db, row)
        approval = {"message_id": message.id, "kind": "proposal_email",
                    "to": address, "cc": state.get("cc") or [],
                    "subject": message.subject}
        # The same truth-telling an agent's approval card gets (F30 blanks).
        runtime = AgentRuntime(db=db, ctx=ctx, pending_approvals=[approval])
        await BaseAgent()._enrich_approvals(runtime)
        to = name if name == address else f"{name} <{address}>"
        return confirmations.Outcome(
            reply=f"The proposal email to {to} is ready for your one-tap approval.",
            actions=[{"tool": "prepare_email", "args": {"to_contact": name}, "ok": True,
                      "result": {"ready_for_approval": True, "message_id": message.id,
                                 "to": to, "cc": state.get("cc") or []}}],
            pending_approvals=runtime.pending_approvals,
        )

    async def pause(self, db: AsyncSession, ctx: OrgContext,
                    row: AssistantPendingAction) -> str:
        state = json.loads(row.payload or "{}")
        state["paused"] = True
        row.payload = json.dumps(state, ensure_ascii=False)
        return "Shall I go back to the proposal email? Just tell me who should receive it."


FLOW = _Flow()
confirmations.register_flow(KIND, FLOW)
