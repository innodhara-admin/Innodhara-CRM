"""Conversation Agent — meeting understanding plus note/task commands.

Its heavy pipeline work (transcribe → extract → save) runs as a background
job (jobs/pipelines.py). Here live its interactive tools: add notes, manage
action items ("move task 2 to Siva", "close task 1 — proposal sent").
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.ai import memory as memory_ai
from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
from app.ai.agents.resolvers import resolve_lead, resolve_user
from app.core.constants import ActionItemStatus
from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.permissions import can_reassign_task, has_permission
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.lead import Lead, ClientIntelligence
from app.services import audit_service, lead_service, notification_service


async def _get_item(runtime: AgentRuntime, task_id: str) -> ActionItem:
    item = (
        await runtime.db.execute(
            select(ActionItem).where(
                ActionItem.id == task_id, ActionItem.org_id == runtime.ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError(
            "Task not found — use list_my_action_items first and pass the task's id."
        )
    return item


class ConversationAgent(BaseAgent):
    name = "conversation"
    description = "Adds client notes and manages action items by voice/text command."
    system_prompt = (
        "You are the Conversation Agent of a sales platform. You save notes "
        "about clients, add contacts (people at a client, with their phone or "
        "email) to clients already on file, and manage action items (tasks). When the user refers "
        "to a task by number, first call list_my_action_items to fetch the "
        "current numbered list, then act on the matching task's id. "
        "A question that is not about this platform's work (football, the "
        "weather, general knowledge) gets one short, friendly sentence saying "
        "you help with clients, tasks and notes — never a question back "
        "asking them to narrow it down, and never an invented answer. Reply "
        "in English however the request was written."
    )

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="add_client_note",
                description="Save a piece of client intelligence (a note) about a lead.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "note": {"type": "string"},
                        "category": {"type": "string", "description": "optional e.g. 'preference'"},
                    },
                    "required": ["client", "note"],
                },
                handler=self._add_note,
            ),
            ToolSpec(
                name="add_client_contact",
                description=(
                    "Add a person at an existing client as a contact, with "
                    "their phone number and/or email address if said."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "name": {"type": "string",
                                 "description": "the contact person's name"},
                        "title": {"type": "string",
                                  "description": "their role or job title"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["client", "name"],
                },
                handler=self._add_contact,
            ),
            ToolSpec(
                name="list_my_action_items",
                description="List the caller's action items with ids (numbered).",
                parameters={
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "open|in_progress|done|all"}
                    },
                },
                handler=self._list_items,
            ),
            ToolSpec(
                name="create_action_item",
                description="Create a new action item, optionally linked to a client.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "client": {"type": "string"},
                        "owner": {"type": "string", "description": "defaults to the caller"},
                    },
                    "required": ["title"],
                },
                handler=self._create_item,
            ),
            ToolSpec(
                name="reassign_action_item",
                description="Move a task to another person (they get notified).",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "to_person": {"type": "string"},
                    },
                    "required": ["task_id", "to_person"],
                },
                handler=self._reassign_item,
            ),
            ToolSpec(
                name="close_action_item",
                description="Mark a task done, saving the result/response note.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "result_note": {"type": "string"},
                    },
                    "required": ["task_id"],
                },
                handler=self._close_item,
            ),
        ]

    async def _add_note(
        self,
        runtime: AgentRuntime,
        client: str,
        note: str,
        category: str | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        lead = await resolve_lead(runtime, client)
        record = ClientIntelligence(
            org_id=ctx.org_id,
            lead_id=lead.id,
            note=note,
            category=category,
            source="voice",
            added_by=ctx.user_id,
        )
        db.add(record)
        await db.flush()
        await memory_ai.add_memory(
            db,
            org_id=ctx.org_id,
            lead_id=lead.id,
            text=f"Note about {lead.name}: {note}",
            source_type="note",
            source_id=record.id,
        )
        await lead_service.touch(db, ctx.org_id, lead.id)
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id,
            action="intelligence.added", entity_type="lead", entity_id=lead.id,
        )
        return {"saved": True, "client": lead.name, "note": note}

    async def _add_contact(
        self,
        runtime: AgentRuntime,
        client: str,
        name: str,
        title: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """The same save as `POST /leads/{id}/contacts`, so the contact counts
        towards opening the lead exactly as one typed into the app does."""
        db, ctx = runtime.db, runtime.ctx
        if not has_permission(ctx.role, "manage_leads"):
            raise PermissionDeniedError("Your role cannot add contacts to clients.")
        name = " ".join((name or "").split())
        if not name:
            raise ValidationFailedError("What is the contact's name?")
        email = (email or "").strip() or None
        if email and "@" not in email:
            raise ValidationFailedError(
                f"\"{email}\" doesn't look like an email address.")
        phone = (phone or "").strip() or None
        lead = await resolve_lead(runtime, client)
        contact = await lead_service.add_contact(
            db, ctx, lead_id=lead.id, name=name,
            title=(title or "").strip() or None, email=email, phone=phone,
        )
        blocker = await lead_service.open_blocker(db, lead, viewer_id=ctx.user_id)
        return {
            "saved": True,
            "client": lead.name,
            "contact": {"name": contact.name, "title": contact.title,
                        "phone": contact.phone, "email": contact.email},
            **({"still_cannot_open": blocker} if blocker else {}),
        }

    async def _list_items(
        self, runtime: AgentRuntime, status: str = "open"
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        stmt = select(ActionItem).where(
            ActionItem.org_id == ctx.org_id, ActionItem.owner_id == ctx.user_id
        )
        if status != "all":
            stmt = stmt.where(ActionItem.status == status)
        items = (
            (await db.execute(stmt.order_by(ActionItem.created_at).limit(30))).scalars().all()
        )
        results = []
        for idx, item in enumerate(items, start=1):
            lead_name = (
                await db.execute(select(Lead.name).where(Lead.id == item.lead_id))
            ).scalar_one_or_none()
            results.append(
                {"number": idx, "id": item.id, "title": item.title,
                 "status": item.status, "priority": item.priority, "client": lead_name}
            )
        return results

    async def _create_item(
        self,
        runtime: AgentRuntime,
        title: str,
        description: str | None = None,
        client: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        lead_id = None
        lead_name = None
        if client:
            lead = await resolve_lead(runtime, client)
            lead_id, lead_name = lead.id, lead.name
        owner_id = ctx.user_id
        owner_name = ctx.name
        if owner and owner.lower() not in ("me", ctx.name.lower()):
            target = await resolve_user(runtime, owner)
            owner_id, owner_name = target.id, target.name
        item = ActionItem(
            org_id=ctx.org_id,
            lead_id=lead_id,
            title=title,
            description=description,
            owner_id=owner_id,
            status=ActionItemStatus.OPEN.value,
            created_by=ctx.user_id,
        )
        db.add(item)
        await db.flush()
        if owner_id != ctx.user_id:
            await notification_service.notify(
                db, org_id=ctx.org_id, user_id=owner_id,
                title=f"New task from {ctx.name}: {title}",
                kind="task_assigned", entity_type="action_item", entity_id=item.id,
            )
        return {"created": True, "id": item.id, "title": title,
                "owner": owner_name, "client": lead_name}

    async def _reassign_item(
        self, runtime: AgentRuntime, task_id: str, to_person: str
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        item = await _get_item(runtime, task_id)
        target = await resolve_user(runtime, to_person)
        if not can_reassign_task(ctx.role, ctx.user_id, item.owner_id, same_team=True):
            raise PermissionDeniedError("You can only reassign your own tasks")
        item.owner_id = target.id
        await notification_service.notify(
            db, org_id=ctx.org_id, user_id=target.id,
            title=f"{ctx.name} assigned you a task: {item.title}",
            kind="task_assigned", entity_type="action_item", entity_id=item.id,
        )
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id,
            action="action_item.reassigned", entity_type="action_item", entity_id=item.id,
            detail={"to": target.name},
        )
        return {"reassigned": True, "task": item.title, "new_owner": target.name,
                "notified": True}

    async def _close_item(
        self, runtime: AgentRuntime, task_id: str, result_note: str | None = None
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        item = await _get_item(runtime, task_id)
        item.status = ActionItemStatus.DONE.value
        item.result_note = result_note
        item.completed_at = utcnow()
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id,
            action="action_item.closed", entity_type="action_item", entity_id=item.id,
            detail={"result": result_note},
        )
        return {"closed": True, "task": item.title, "result_note": result_note}
