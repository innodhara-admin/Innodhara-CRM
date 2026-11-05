"""Email Agent — drafts and prepares emails from the salesperson's own
address; handles CC and the introductory message (doc §6).

Since 28 Oct 2026 it also sends the organisation's own Word email templates:
it picks one, fills its tags from the client's record or by asking, and drafts
it for the same one-tap approval. A free-written email is the fallback for a
request no template fits."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.ai.agents import email_fill_tools
from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
from app.ai.agents.resolvers import resolve_contact, resolve_lead
from app.ai.llm import TIER_FAST, ToolCall, get_model_layer
from app.ai import memory as memory_ai
from app.core.constants import MessageChannel, MessageKind
from app.core.exceptions import NeedsConfirmationError, NotFoundError
from app.models.email_template import EmailFillSession, EmailFillStatus, EmailTemplate
from app.models.lead import Contact, Lead
from app.models.organisation import Organisation
from app.models.program import Program
from app.services import (
    email_choice,
    email_fill_service,
    email_template_service,
    intro_service,
    message_service,
    proposal_email_service,
)

#: The tools that put a question card in front of the person (D48: the card
#: is the question, and the prose is cut to its first line).
_EMAIL_CARD_TOOLS = frozenset({
    "send_template_email", "answer_email_questions", "change_email"})

#: Words in a request that never belong to a template's name.
_FILLER_WORDS = frozenset({
    "the", "an", "our", "my", "this", "that", "email", "mail", "template",
    "message", "for", "to"})

#: The tools that deal with a reply to an open email's questions.
_EMAIL_REPLY_TOOLS = _EMAIL_CARD_TOOLS | {"cancel_template_email"}

#: A WhatsApp drafted this turn dealt with the person's words, even while an
#: email still waits for answers (4 Nov 2026).
_WHATSAPP_TOOL = "send_whatsapp_to_client"


class EmailAgent(BaseAgent):
    name = "email"
    description = "Drafts intro messages and custom emails; parks them for approval."
    system_prompt = (
        "You are the Email Agent. You draft emails on behalf of the salesperson "
        "— always from their own address, never a robot address. Every message "
        "you prepare waits for the user's one-tap approval; say so in your reply. "
        "Keep drafts short, warm and professional."
        "\n\n"
        "THE ORGANISATION HAS ITS OWN EMAIL TEMPLATES, and they come first. For "
        "any email to a client, call list_email_templates for that client, pick "
        "the template that fits what the user asked, and call "
        "send_template_email with its exact name in the same turn. The tool "
        "asks the user whatever the email needs: never ask the user for the "
        "email's details yourself, and never say a draft is ready unless "
        "send_template_email returned one. Use the facts it returns: when "
        "follow_ups_unanswered is 2 or more, a follow-up request means the final "
        "follow-up template. If two templates fit equally, pass the words the "
        "user used and the tool will ask them which. Use draft_custom_email only "
        "when no template fits the request. While a template email is being "
        "filled, every reply about its questions goes to answer_email_questions; "
        "a change to an email already drafted goes to change_email; and "
        "cancel_template_email drops one the user no longer wants."
        "\n\n"
        "A message the user wants sent to a client ON WHATSAPP goes to "
        "send_whatsapp_to_client, never to an email tool; set attach_proposal "
        "when they want the client's proposal sent with it."
    )

    CARD_TOOLS = _EMAIL_CARD_TOOLS

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="draft_intro_message",
                description="Draft the organisation's templated introductory message for a contact.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string", "description": "the client organisation only"},
                        "contact": {
                            "type": "string",
                            "description": (
                                "the person's name or job title ONLY, never the "
                                "client's name with it — e.g. 'Priya Nair' or "
                                "'Head of Procurement', not 'Priya Nair at Acme'"
                            ),
                        },
                        "channel": {"type": "string", "description": "email | whatsapp"},
                    },
                    "required": ["client"],
                },
                handler=self._draft_intro,
            ),
            ToolSpec(
                name="draft_custom_email",
                description="Write a custom email to a contact about a lead (AI-drafted, human-approved).",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string", "description": "the client organisation only"},
                        "contact": {
                            "type": "string",
                            "description": (
                                "the recipient's name or job title ONLY, never "
                                "with the client's name attached"
                            ),
                        },
                        "purpose": {"type": "string", "description": "what the email should achieve"},
                        "cc_contacts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "names, titles or email addresses to CC — one per entry",
                        },
                    },
                    "required": ["client", "purpose"],
                },
                handler=self._draft_custom,
            ),
            ToolSpec(
                name=_WHATSAPP_TOOL,
                description=(
                    "Draft a WhatsApp message to a contact at a client for "
                    "one-tap approval. Set attach_proposal to send the client's "
                    "latest proposal as a PDF with it."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string", "description": "the client organisation only"},
                        "contact": {
                            "type": "string",
                            "description": (
                                "ONLY a recipient the user named: their name or "
                                "job title. Omit it when the user named nobody."
                            ),
                        },
                        "message": {
                            "type": "string",
                            "description": (
                                "what the message should say, in the user's own "
                                "words; omit it to have a short message written"
                            ),
                        },
                        "attach_proposal": {
                            "type": "boolean",
                            "description": "true to send the client's latest proposal PDF",
                        },
                    },
                    "required": ["client"],
                },
                handler=self._send_whatsapp,
            ),
            ToolSpec(
                name="list_email_templates",
                description=(
                    "The organisation's email templates and the facts that "
                    "decide between them for one client. Call this before "
                    "send_template_email. Changes nothing."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string", "description": "the client organisation only"},
                    },
                    "required": ["client"],
                },
                handler=self._list_templates,
            ),
            ToolSpec(
                name="send_template_email",
                description=(
                    "Fill one of the organisation's email templates for a "
                    "client and draft it for one-tap approval. Asks the user "
                    "only what the client's record cannot answer."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string", "description": "the client organisation only"},
                        "template": {
                            "type": "string",
                            "description": "the template's name, as list_email_templates gave it",
                        },
                        "contact": {
                            "type": "string",
                            "description": (
                                "ONLY a recipient the user named: their name, "
                                "job title or email address. Omit it when the "
                                "user named nobody."
                            ),
                        },
                        "cc_contacts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "names, titles or email addresses to CC — one per entry",
                        },
                    },
                    "required": ["client", "template"],
                },
                handler=self._send_template,
            ),
            ToolSpec(
                name="answer_email_questions",
                description=(
                    "Pass on the user's answer to the questions you asked about "
                    "a template email. Send their words as they said them."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "the user's reply, in their own words"},
                    },
                    "required": ["answer"],
                },
                handler=self._answer_questions,
            ),
            ToolSpec(
                name="show_email_questions",
                description=(
                    "List the questions still open on the template email this "
                    "conversation is filling. Answers nothing."
                ),
                parameters={"type": "object", "properties": {}},
                handler=self._show_questions,
            ),
            ToolSpec(
                name="change_email",
                description=(
                    "Change something in a template email already drafted and "
                    "waiting for approval, then draft it again."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "change": {"type": "string", "description": "what to change, in the user's words"},
                    },
                    "required": ["change"],
                },
                handler=self._change,
            ),
            ToolSpec(
                name="cancel_template_email",
                description="Drop the template email this conversation is filling.",
                parameters={"type": "object", "properties": {}},
                handler=self._cancel,
            ),
        ]

    async def _draft_intro(
        self,
        runtime: AgentRuntime,
        client: str,
        contact: str | None = None,
        channel: str = "email",
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        lead = await resolve_lead(runtime, client)
        contact_row = await resolve_contact(runtime, lead, contact)
        channel = channel if channel in ("email", "whatsapp") else "email"
        message = await intro_service.draft_intro_message(
            db, ctx, contact=contact_row, channel=channel
        )
        runtime.pending_approvals.append(
            {
                "message_id": message.id,
                "kind": "intro",
                "channel": channel,
                "to": message.to_address,
                "subject": message.subject,
                "body_preview": message.body[:300],
            }
        )
        return {
            "ready_for_approval": True,
            "message_id": message.id,
            "to": f"{contact_row.name} <{message.to_address}>",
            "body_preview": message.body[:500],
        }

    async def _draft_custom(
        self,
        runtime: AgentRuntime,
        client: str,
        purpose: str,
        contact: str | None = None,
        cc_contacts: list[str] | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        lead = await resolve_lead(runtime, client)
        contact_row = await resolve_contact(runtime, lead, contact)
        if not contact_row.email:
            raise NotFoundError(f"{contact_row.name} has no email on record.")

        org = (
            await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
        ).scalar_one()
        memories = await memory_ai.search_memory(
            db, org_id=ctx.org_id, query=purpose, lead_id=lead.id, top_k=3
        )
        memory_text = "\n".join(f"- {m['text']}" for m in memories) or "- (no past notes)"

        draft = await get_model_layer().generate_json(
            purpose="email.draft_custom",
            tier=TIER_FAST,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Draft a short professional email from {ctx.name} of {org.name} "
                        f"to {contact_row.name} ({contact_row.title or 'contact'}) at "
                        f"{lead.name}.\nPurpose: {purpose}\n"
                        f"Relevant past notes:\n{memory_text}\n\n"
                        'Return JSON: {"subject": "...", "body": "..."} — body in plain '
                        "text, ending with the sender's name. No prices unless the "
                        "purpose states them explicitly."
                    ),
                }
            ],
            json_schema={
                "type": "object",
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"],
            },
            temperature=0.4,
        )

        cc_addresses: list[str] = []
        for hint in cc_contacts or []:
            if "@" in hint:
                cc_addresses.append(hint.strip())
            else:
                cc_row = await resolve_contact(runtime, lead, hint)
                if cc_row.email:
                    cc_addresses.append(cc_row.email)

        message = await message_service.create_message(
            db,
            ctx,
            kind=MessageKind.FOLLOW_UP.value,
            channel=MessageChannel.EMAIL.value,
            to_address=contact_row.email,
            cc=cc_addresses,
            subject=draft["subject"],
            body=draft["body"],
            lead_id=lead.id,
            contact_id=contact_row.id,
        )
        runtime.pending_approvals.append(
            {
                "message_id": message.id,
                "kind": "custom_email",
                "to": message.to_address,
                "cc": cc_addresses,
                "subject": message.subject,
                "body_preview": message.body[:300],
            }
        )
        return {
            "ready_for_approval": True,
            "message_id": message.id,
            "to": f"{contact_row.name} <{contact_row.email}>",
            "subject": draft["subject"],
            "body_preview": draft["body"][:500],
        }

    # --- WhatsApp to a client (4 Nov 2026) -------------------------------------

    async def _send_whatsapp(
        self,
        runtime: AgentRuntime,
        client: str,
        contact: str | None = None,
        message: str | None = None,
        attach_proposal: bool = False,
    ) -> dict[str, Any]:
        """A WhatsApp draft in the same approval bar as an email. It goes out as
        an approved template (app/services/whatsapp_service.py) once tapped."""
        db, ctx = runtime.db, runtime.ctx
        lead = await resolve_lead(runtime, client)
        contact_row = await resolve_contact(runtime, lead, contact)
        if not contact_row.phone:
            raise NotFoundError(f"{contact_row.name} has no phone number on record.")

        from app.core.exceptions import ValidationFailedError
        from app.services import whatsapp_templates
        from app.services.whatsapp_text import BODY_LIMIT, clean_value

        if attach_proposal and (message or "").strip():
            raise ValidationFailedError(
                "A proposal goes on WhatsApp with its own approved wording. Send "
                "your note as a separate WhatsApp.")
        names = {"contact_name": clean_value(contact_row.name),
                 "sender_name": clean_value(ctx.name or "Sales")}
        kind, proposal_id, attachments = MessageKind.FOLLOW_UP.value, None, None
        if attach_proposal:
            from app.models.proposal import Proposal

            proposal = (await db.execute(
                select(Proposal).where(
                    Proposal.org_id == ctx.org_id, Proposal.lead_id == lead.id,
                    Proposal.status != "declined",
                ).order_by(Proposal.created_at.desc())
            )).scalars().first()
            if proposal is None:
                raise NotFoundError(f"{lead.name} has no proposal to send yet.")
            await proposal_email_service.ensure_rendered_files(db, proposal)
            if not proposal.pdf_path:
                raise NotFoundError(f"The proposal for {lead.name} has no PDF yet.")
            filename = f"{proposal_email_service._safe_name(proposal.title)}.pdf"
            kind, proposal_id = MessageKind.PROPOSAL.value, proposal.id
            attachments = [{"path": proposal.pdf_path, "filename": filename}]

        if attachments:
            # The approver sees exactly what the client will read.
            text = whatsapp_templates.render("client_proposal", {
                **names, "programme": clean_value(proposal.title)})
            preview = text
        else:
            text = (message or "").strip() or await self._whatsapp_text(
                runtime, lead, contact_row)
            room = (BODY_LIMIT - whatsapp_templates.TEMPLATES["client_message"].fixed_len
                    - len(names["contact_name"]) - len(names["sender_name"]))
            if len(clean_value(text)) > room:
                raise ValidationFailedError(
                    f"That message is too long for WhatsApp ({len(text)} characters; "
                    f"keep it under {room}).")
            preview = whatsapp_templates.render("client_message", {
                **names, "message": clean_value(text)})
        draft = await message_service.create_message(
            db, ctx, kind=kind, channel=MessageChannel.WHATSAPP.value,
            to_address=contact_row.phone, body=text, lead_id=lead.id,
            contact_id=contact_row.id, proposal_id=proposal_id, attachments=attachments,
        )
        runtime.pending_approvals.append({
            "message_id": draft.id, "kind": "whatsapp", "channel": "whatsapp",
            "to": draft.to_address, "subject": None, "body_preview": preview,
        })
        return {
            "ready_for_approval": True,
            "message_id": draft.id,
            "to": f"{contact_row.name} <{draft.to_address}>",
            "body_preview": preview,
            "attachment": attachments[0]["filename"] if attachments else None,
        }

    async def _whatsapp_text(self, runtime: AgentRuntime, lead: Lead, contact: Contact) -> str:
        org = (
            await runtime.db.execute(
                select(Organisation).where(Organisation.id == runtime.ctx.org_id))
        ).scalar_one()
        memories = await memory_ai.search_memory(
            runtime.db, org_id=runtime.ctx.org_id, query=f"latest with {lead.name}",
            lead_id=lead.id, top_k=3)
        notes = "\n".join(f"- {m['text']}" for m in memories) or "- (no past notes)"
        draft = await get_model_layer().generate_json(
            purpose="whatsapp.draft",
            tier=TIER_FAST,
            org_id=runtime.ctx.org_id,
            user_id=runtime.ctx.user_id,
            messages=[{"role": "user", "content": (
                f"Write a short, warm WhatsApp follow-up from {runtime.ctx.name} of "
                f"{org.name} to {contact.name} at {lead.name}.\n"
                f"Relevant past notes:\n{notes}\n\n"
                'Return JSON: {"text": "..."}: two or three plain sentences, no '
                "greeting line and no sign-off (both are added), no prices."
            )}],
            json_schema={"type": "object", "properties": {"text": {"type": "string"}},
                         "required": ["text"]},
            temperature=0.4,
        )
        return ((draft.get("text") or "").strip()
                or "Thank you for your time. We look forward to speaking again soon.")

    # --- the organisation's own templates (28 Oct 2026) ---------------------

    def _chat(self, runtime: AgentRuntime) -> str | None:
        return runtime.extra_context.get("session_id")

    async def _list_templates(self, runtime: AgentRuntime, client: str) -> dict[str, Any]:
        lead = await resolve_lead(runtime, client)
        return await email_choice.choices(runtime.db, runtime.ctx, lead)

    async def _pick(self, runtime: AgentRuntime, wanted: str) -> EmailTemplate:
        """The current template named `wanted`; a question when it is not one."""
        templates = await email_template_service.current_templates(
            runtime.db, runtime.ctx.org_id)
        if not templates:
            raise NotFoundError(
                "This organisation has no email templates yet. Use "
                "draft_custom_email instead.")
        said = " ".join((wanted or "").split()).casefold()
        exact = [t for t in templates if t.id == wanted or t.name.casefold() == said]
        if len(exact) == 1:
            return exact[0]
        # Words that name no template: "the final follow-up email" means the
        # template called "Final follow-up".
        words = [w for w in said.split()
                 if len(w) > 1 and w not in _FILLER_WORDS]
        near = [t for t in templates
                if words and all(w in t.name.casefold() for w in words)]
        if len(near) == 1:
            return near[0]
        options = near or templates
        raise NeedsConfirmationError(
            "Which email: " + ", or ".join(t.name for t in options) + "?",
            candidates=[t.name for t in options])

    async def _other_fill_waiting(self, runtime: AgentRuntime) -> dict[str, Any] | None:
        """One conversation fills one thing at a time: a proposal or MoU waiting
        on the person comes first, and nothing about this email is started."""
        from app.models.proposal_fill import FillStatus  # noqa: PLC0415
        from app.services import proposal_fill_service  # noqa: PLC0415

        for document_type, noun in (("mou", "MoU"), ("proposal", "proposal")):
            fill = await proposal_fill_service.find_for_chat(
                runtime.db, runtime.ctx, chat_session_id=self._chat(runtime),
                document_type=document_type)
            if fill is not None and fill.status in (FillStatus.ASKING,
                                                    FillStatus.REVIEWING):
                return {
                    "ok": False,
                    "message": (
                        f"A {noun} is being filled in this conversation and is "
                        f"waiting on the user. Finish it first: nothing about "
                        f"this email was started."),
                }
        return None

    async def _fill_replies(self, runtime: AgentRuntime) -> list[str]:
        chat = self._chat(runtime)
        if not chat:
            return []
        rows = (await runtime.db.execute(select(EmailFillSession).where(
            EmailFillSession.org_id == runtime.ctx.org_id,
            EmailFillSession.user_id == runtime.ctx.user_id,
            EmailFillSession.chat_session_id == chat))).scalars().all()
        return [str(r.get("reply") or "") for row in rows
                for r in (row.asked_json or []) if isinstance(r, dict)]

    async def _recipient(self, runtime: AgentRuntime, lead: Lead,
                         template: EmailTemplate, hint: str | None,
                         cc_hints: list[str]) -> tuple[str, str | None, list[str]]:
        """(to_address, contact_id, cc) from the person's own words or the record.

        The rule the proposal email follows (2 Oct 2026): a recipient counts
        only if the person named them in this chat; otherwise the main contact,
        the only contact, or a question. Never a guess."""
        from app.ai.agents.proposal_agent import recipient_said  # noqa: PLC0415

        not_names = [lead.name]
        if template.program_id:
            program = await runtime.db.get(Program, template.program_id)
            if program is not None:
                not_names += [program.name, program.code]
        said = list(runtime.extra_context.get("_said_by_user") or [])
        replies = await self._fill_replies(runtime)

        def named(text: str | None) -> bool:
            return recipient_said(text, said=said, fill_replies=replies,
                                  not_names=[n for n in not_names if n])

        if hint and named(hint) and "@" in hint:
            to_address, contact_id = hint.strip(), None
        else:
            contact = await resolve_contact(runtime, lead, hint if named(hint) else None)
            if not contact.email:
                reachable = [c.name for c in (await runtime.db.execute(
                    select(Contact).where(Contact.org_id == runtime.ctx.org_id,
                                          Contact.lead_id == lead.id)
                )).scalars().all() if c.email]
                raise NeedsConfirmationError(
                    f"{contact.name} has no email on record. Who should receive "
                    "this email instead?"
                    + (f" I have {', '.join(reachable)}, or type an email address."
                       if reachable else " Type an email address."),
                    candidates=reachable)
            to_address, contact_id = contact.email, contact.id
        cc: list[str] = []
        for cc_hint in cc_hints:
            if not named(cc_hint):
                continue
            if "@" in cc_hint:
                cc.append(cc_hint.strip())
            else:
                row = await resolve_contact(runtime, lead, cc_hint)
                if row.email:
                    cc.append(row.email)
        return to_address, contact_id, cc

    async def _send_template(
        self,
        runtime: AgentRuntime,
        client: str,
        template: str,
        contact: str | None = None,
        cc_contacts: list[str] | None = None,
    ) -> dict[str, Any]:
        blocked = await self._other_fill_waiting(runtime)
        if blocked is not None:
            return blocked
        db, ctx, chat = runtime.db, runtime.ctx, self._chat(runtime)
        open_fill = await email_fill_service.find_for_chat(
            db, ctx, chat, statuses=(EmailFillStatus.ASKING,))
        if open_fill is not None:
            return {
                "already_open": True,
                "fill_session_id": open_fill.id,
                "what_to_do": (
                    "An email is already being filled in this conversation and "
                    "is waiting for the user's answers. Pass their words to "
                    "answer_email_questions, or call cancel_template_email if "
                    "they want to drop it."),
            }
        lead = await resolve_lead(runtime, client)
        chosen = await self._pick(runtime, template)
        waiting = await email_fill_service.find_for_chat(
            db, ctx, chat, statuses=(EmailFillStatus.WAITING_FOR_DOCUMENT,))
        if (waiting is not None and waiting.lead_id == lead.id
                and waiting.template_id == chosen.id):
            waiting = await email_fill_service.resume(db, ctx, waiting)
            return await email_fill_tools.raise_round(runtime, waiting, chosen,
                                                      lead.name)
        # Said before anything is asked (replay of 28 Oct): an email that
        # cannot be sent should not first ask who is to receive it.
        if (chosen.built_document != "none"
                and await email_fill_service.built_document_for(
                    db, ctx, chosen, lead.id) is None):
            return await email_fill_tools.missing_document(runtime, chosen, lead.name)
        to_address, contact_id, cc = await self._recipient(
            runtime, lead, chosen, contact, cc_contacts or [])
        return await email_fill_tools.start(
            runtime, template=chosen, lead=lead, to_address=to_address, cc=cc,
            contact_id=contact_id, chat_session_id=chat)

    async def _fill_in_hand(self, runtime: AgentRuntime,
                            *statuses: str) -> EmailFillSession:
        session = await email_fill_service.find_for_chat(
            runtime.db, runtime.ctx, self._chat(runtime), statuses=statuses)
        if session is None:
            raise NotFoundError(
                "There is no template email waiting in this conversation. Ask "
                "me to send one first.")
        return session

    async def _template_and_lead(self, runtime: AgentRuntime,
                                 session: EmailFillSession) -> tuple[EmailTemplate, Lead]:
        template = await runtime.db.get(EmailTemplate, session.template_id)
        if template is None:
            raise NotFoundError(email_fill_service.TEMPLATE_GONE)
        return template, await runtime.db.get(Lead, session.lead_id)

    async def _answer_questions(self, runtime: AgentRuntime, answer: str) -> dict[str, Any]:
        session = await self._fill_in_hand(runtime, EmailFillStatus.ASKING)
        session = await email_fill_service.apply_answers(
            runtime.db, runtime.ctx, session, answer)
        template, lead = await self._template_and_lead(runtime, session)
        return await email_fill_tools.raise_round(runtime, session, template, lead.name)

    async def _show_questions(self, runtime: AgentRuntime) -> dict[str, Any]:
        session = await self._fill_in_hand(runtime, EmailFillStatus.ASKING)
        return {
            "fill_session_id": session.id,
            "remaining": len(email_fill_service.open_questions(session, limit=None)),
            "questions": [email_fill_tools.question_line(q)
                          for q in email_fill_service.open_questions(session)],
        }

    async def _change(self, runtime: AgentRuntime, change: str) -> dict[str, Any]:
        session = await self._fill_in_hand(runtime, EmailFillStatus.DRAFTED,
                                           EmailFillStatus.ASKING)
        if session.status == EmailFillStatus.ASKING:
            return await self._answer_questions(runtime, change)
        session = await email_fill_service.apply_change(
            runtime.db, runtime.ctx, session, change)
        template, lead = await self._template_and_lead(runtime, session)
        return await email_fill_tools.raise_round(runtime, session, template, lead.name)

    async def _cancel(self, runtime: AgentRuntime) -> dict[str, Any]:
        session = await self._fill_in_hand(
            runtime, EmailFillStatus.ASKING, EmailFillStatus.WAITING_FOR_DOCUMENT)
        await email_fill_service.abandon(runtime.db, session)
        return {"cancelled": True,
                "note": "Nothing was sent. The email has been dropped."}

    def _an_email_tool_acted(self, runtime: AgentRuntime) -> bool:
        """Did a tool that can deal with the reply actually deal with it?

        Not merely "was one called": replayed with the real model on 28 Oct,
        "Mr." reached send_template_email again, which answered that the
        email was already open, and the answer was never recorded. A tool that
        reports it could not act has not dealt with the person's words (the
        proposal fill's D49 rule)."""
        for action in runtime.actions:
            if action.get("tool") not in _EMAIL_REPLY_TOOLS or not action.get("ok"):
                continue
            result = action.get("result")
            if isinstance(result, dict) and (result.get("already_open")
                                             or result.get("ok") is False):
                continue
            return True
        return False

    async def _tool_the_turn_needs(self, runtime: AgentRuntime, user_text: str,
                                   called: list[str]) -> ToolCall | None:
        """A reply while an email waits for answers belongs to that email (the
        proposal fill's D47 rule): a turn that called nothing able to act on it
        hands the person's own words to answer_email_questions."""
        if self._an_email_tool_acted(runtime) or any(
                a.get("tool") == _WHATSAPP_TOOL and a.get("ok") for a in runtime.actions):
            return None
        session = await email_fill_service.find_for_chat(
            runtime.db, runtime.ctx, self._chat(runtime),
            statuses=(EmailFillStatus.ASKING,))
        if session is None or not email_fill_service.open_questions(session, limit=None):
            return None
        return ToolCall(name="answer_email_questions", args={"answer": user_text})
