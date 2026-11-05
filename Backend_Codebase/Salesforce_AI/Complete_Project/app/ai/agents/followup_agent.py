"""Follow-up Agent — writes follow-up emails / WhatsApp messages for a lead
and keeps the follow-up loop turning (doc §6, §9.4)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.ai import memory as memory_ai
from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
from app.ai.agents.resolvers import resolve_contact, resolve_lead
from app.ai.llm import TIER_FAST, get_model_layer
from app.core import clock
from app.core.constants import (
    FollowUpStatus,
    MessageChannel,
    MessageKind,
    TemplateKind,
)
from app.core.exceptions import NotFoundError
from app.models.base import utcnow
from app.models.followup import FollowUp
from app.models.lead import Lead
from app.models.organisation import Organisation, OrgSettings
from app.services import message_service, template_service


class FollowupAgent(BaseAgent):
    name = "followup"
    description = "Drafts follow-up messages, lists due follow-ups, completes them."
    system_prompt = (
        "You are the Follow-up Agent. You help the salesperson never miss a "
        "follow-up: list what is due, draft short polite follow-up messages "
        "(email or WhatsApp) that mention the last interaction, and mark "
        "follow-ups done (which schedules the next reminder). Every message "
        "waits for the user's one-tap approval."
    )

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="list_due_followups",
                description="Follow-ups due today (or overdue) for this organisation.",
                parameters={
                    "type": "object",
                    "properties": {
                        "mine_only": {"type": "boolean", "description": "default true"}
                    },
                },
                handler=self._list_due,
            ),
            ToolSpec(
                name="draft_followup_message",
                description="Draft a follow-up email or WhatsApp message for a client.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "channel": {"type": "string", "description": "email | whatsapp"},
                        "contact": {
                            "type": "string",
                            "description": (
                                "optional — the person's name or job title ONLY, "
                                "never with the client's name attached"
                            ),
                        },
                        "extra_context": {"type": "string", "description": "anything specific to mention"},
                    },
                    "required": ["client"],
                },
                handler=self._draft_message,
            ),
            ToolSpec(
                name="schedule_followup",
                description="Create a follow-up reminder for a client on a date.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "channel": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["client", "due_date"],
                },
                handler=self._schedule,
            ),
            ToolSpec(
                name="complete_followup",
                description="Mark a follow-up done; the next reminder is scheduled automatically.",
                parameters={
                    "type": "object",
                    "properties": {
                        "followup_id": {"type": "string"},
                        "sent_message_id": {"type": "string", "description": "optional"},
                    },
                    "required": ["followup_id"],
                },
                handler=self._complete,
            ),
        ]

    async def _list_due(
        self, runtime: AgentRuntime, mine_only: bool = True
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        today = clock.today(await clock.org_zone(db, ctx.org_id))
        stmt = select(FollowUp).where(
            FollowUp.org_id == ctx.org_id,
            FollowUp.status == FollowUpStatus.PENDING.value,
            FollowUp.due_date <= today,
        )
        if mine_only:
            stmt = stmt.where(FollowUp.owner_id == ctx.user_id)
        followups = (
            (await db.execute(stmt.order_by(FollowUp.due_date).limit(30))).scalars().all()
        )
        results = []
        for f in followups:
            lead_name = (
                await db.execute(select(Lead.name).where(Lead.id == f.lead_id))
            ).scalar_one_or_none()
            results.append(
                {
                    "id": f.id,
                    "client": lead_name,
                    "due_date": f.due_date.isoformat(),
                    "channel": f.channel,
                    "note": f.note,
                }
            )
        return results

    async def _draft_message(
        self,
        runtime: AgentRuntime,
        client: str,
        channel: str = "whatsapp",
        contact: str | None = None,
        extra_context: str | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        channel = channel if channel in ("email", "whatsapp") else "whatsapp"
        lead = await resolve_lead(runtime, client)
        contact_row = await resolve_contact(runtime, lead, contact)
        to_address = (
            contact_row.email if channel == "email" else contact_row.phone
        )
        if not to_address:
            raise NotFoundError(
                f"{contact_row.name} has no "
                f"{'email' if channel == 'email' else 'phone number'} on record."
            )

        # An email follow-up uses the organisation's own follow-up template
        # when it has one (28 Oct 2026). WhatsApp, and an organisation with no
        # such template, carry on below exactly as before.
        if channel == "email":
            started = await self._from_template(runtime, lead, contact_row, to_address)
            if started is not None:
                return started

        org = (
            await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
        ).scalar_one()

        # Base template if the org has one; the model personalises around it.
        try:
            template = await template_service.get_current_message_template(
                db, ctx.org_id, TemplateKind.FOLLOW_UP.value, channel
            )
            base = template.body
            base_subject = template.subject
        except NotFoundError:
            base, base_subject = "", None

        memories = await memory_ai.search_memory(
            db, org_id=ctx.org_id, query=f"last meeting with {lead.name}",
            lead_id=lead.id, top_k=3,
        )
        memory_text = "\n".join(f"- {m['text']}" for m in memories) or "- (no past notes)"

        draft = await get_model_layer().generate_json(
            purpose="followup.draft",
            tier=TIER_FAST,
            org_id=ctx.org_id,
            user_id=ctx.user_id,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Write a short, polite follow-up {channel} message from "
                        f"{ctx.name} of {org.name} to {contact_row.name} at {lead.name}. "
                        f"Reference the last interaction naturally.\n"
                        f"Past notes:\n{memory_text}\n"
                        + (f"Also mention: {extra_context}\n" if extra_context else "")
                        + (f"Organisation's base template to adapt:\n{base}\n" if base else "")
                        + '\nReturn JSON: {"subject": "...", "body": "..."} '
                        "(subject empty for WhatsApp; body 3-6 sentences, no prices)."
                    ),
                }
            ],
            json_schema={
                "type": "object",
                "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["body"],
            },
            temperature=0.4,
        )

        message = await message_service.create_message(
            db,
            ctx,
            kind=MessageKind.FOLLOW_UP.value,
            channel=channel,
            to_address=to_address,
            subject=(draft.get("subject") or base_subject or f"Following up — {org.name}")
            if channel == "email"
            else None,
            body=draft["body"],
            lead_id=lead.id,
            contact_id=contact_row.id,
        )
        runtime.pending_approvals.append(
            {
                "message_id": message.id,
                "kind": "follow_up",
                "channel": channel,
                "to": to_address,
                "body_preview": message.body[:300],
            }
        )
        return {
            "ready_for_approval": True,
            "message_id": message.id,
            "channel": channel,
            "to": f"{contact_row.name} ({to_address})",
            "body_preview": draft["body"][:500],
        }

    async def _from_template(self, runtime: AgentRuntime, lead: Lead,
                             contact_row, to_address: str) -> dict[str, Any] | None:
        """The follow-up template this client is due, filled like any template
        email, or None when the organisation has none. Two or more follow-ups
        gone unanswered means the final follow-up, when there is one."""
        from app.ai.agents import email_fill_tools  # noqa: PLC0415
        from app.core.exceptions import NeedsConfirmationError  # noqa: PLC0415
        from app.services import email_choice, email_template_service  # noqa: PLC0415

        common = [t for t in await email_template_service.current_templates(
            runtime.db, runtime.ctx.org_id) if t.template_type == "common"]
        final = [t for t in common if t.category == "final_follow_up"]
        plain = [t for t in common if t.category == "follow_up"]
        unanswered = await email_choice.follow_ups_unanswered(
            runtime.db, runtime.ctx.org_id, lead.id)
        chosen = final if unanswered >= 2 and final else plain
        if not chosen:
            return None
        if len(chosen) > 1:
            names = [t.name for t in chosen]
            raise NeedsConfirmationError(
                "Which follow-up email: " + ", or ".join(names) + "?",
                candidates=names)
        return await email_fill_tools.start(
            runtime, template=chosen[0], lead=lead, to_address=to_address, cc=[],
            contact_id=contact_row.id,
            chat_session_id=runtime.extra_context.get("session_id"))

    async def _schedule(
        self,
        runtime: AgentRuntime,
        client: str,
        due_date: str,
        channel: str = "email",
        note: str | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        lead = await resolve_lead(runtime, client)
        try:
            due = date.fromisoformat(due_date)
        except ValueError:
            return {"error": f"Date must be YYYY-MM-DD, got '{due_date}'"}
        followup = FollowUp(
            org_id=ctx.org_id,
            lead_id=lead.id,
            owner_id=ctx.user_id,
            due_date=due,
            channel=channel if channel in ("email", "whatsapp", "call") else "email",
            note=note,
            created_by=ctx.user_id,
        )
        db.add(followup)
        await db.flush()
        return {"scheduled": True, "id": followup.id, "client": lead.name,
                "due_date": due.isoformat()}

    async def _complete(
        self,
        runtime: AgentRuntime,
        followup_id: str,
        sent_message_id: str | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        followup = (
            await db.execute(
                select(FollowUp).where(
                    FollowUp.id == followup_id, FollowUp.org_id == ctx.org_id
                )
            )
        ).scalar_one_or_none()
        if followup is None:
            raise NotFoundError("Follow-up not found — call list_due_followups first.")
        followup.status = FollowUpStatus.DONE.value
        followup.completed_at = utcnow()
        followup.message_id = sent_message_id

        settings_row = (
            await db.execute(select(OrgSettings).where(OrgSettings.org_id == ctx.org_id))
        ).scalar_one_or_none()
        cadence = settings_row.followup_cadence_days if settings_row else 7
        tz = clock.zone(settings_row.timezone if settings_row else None)
        next_followup = FollowUp(
            org_id=ctx.org_id,
            lead_id=followup.lead_id,
            owner_id=followup.owner_id or ctx.user_id,
            due_date=clock.today(tz) + timedelta(days=cadence),
            channel=followup.channel,
            note="Auto-scheduled after previous follow-up",
            created_by="system",
        )
        db.add(next_followup)
        await db.flush()
        return {
            "completed": True,
            "next_reminder": next_followup.due_date.isoformat(),
        }
