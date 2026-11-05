"""Query Agent — answers questions by reading the database in plain language,
always scoped to the caller's organisation (doc §6)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.ai import memory as memory_ai
from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
from app.ai.agents.resolvers import resolve_lead, resolve_user
from app.core import clock
from app.core.constants import ActionItemStatus, FollowUpStatus, LeadState
from app.models.action_item import ActionItem
from app.models.demo import Demo, DemoTeam
from app.models.followup import FollowUp
from app.models.lead import Contact, Lead, ClientIntelligence
from app.models.project import Project
from app.models.proposal import Proposal
from app.models.user import User


def _item_dict(item: ActionItem, owner: str | None, lead: str | None) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        # Without this the model cannot see P1/P2/P3 and silently answers
        # "what are the priorities?" by due date instead (F19).
        "priority": item.priority,
        "owner": owner,
        "client": lead,
        "due_date": item.due_date.isoformat() if item.due_date else None,
        "description": item.description,
        # F46: "why did you pick Baski" had no answer from data — the recorded
        # reason was in NO agent's view, so the model explained why it had
        # *mentioned* the name instead. Carried verbatim, caveats included: the
        # clause that matters most is the one the engine attaches when it is not
        # confident ("tie; lead should confirm or change"), and a paraphrase
        # would drop exactly that.
        "assignment_reason": item.assignment_reason,
    }


#: "Every client", said on purpose: drop the filter.
_EVERY_CLIENT = frozenset({"all", "all clients", "every client", "everything",
                           "any client", "anyone", "everyone"})
#: Not a client at all — what a model writes when nobody named one.
_NOT_A_CLIENT = frozenset({"default", "none", "null", "n/a", "na", "nil", "-",
                           "unspecified", "not specified", "unknown", "me",
                           "my", "mine", "my clients", "no"})


def _effective_client(runtime: AgentRuntime, client: str | None) -> str | None:
    """Resolve which client a lead-scopable query should target (F17).

    The app's context chip sends a `lead_id`; when the model does not name a
    client of its own, that selected lead becomes the filter — so "what are the
    action items?" with a lead selected answers *for that lead* instead of
    everything. An explicit client the model passed always wins, and the
    sentinel "all" is the deliberate way to broaden back to every client.
    Returns a name-or-id for `resolve_lead`, or None for no client filter."""
    said = (client or "").strip().lower()
    if said in _EVERY_CLIENT:
        return None
    if not said or said in _NOT_A_CLIENT:
        # The model filled the field with a placeholder instead of leaving it
        # out. "default" is not a client, it is "they did not say" — and
        # looking it up answered a plain "show my open tasks" with "which
        # client did you mean?" (measured 21 Sep 2026, in English too).
        client = runtime.extra_context.get("lead_id")
        said = (client or "").strip().lower()
    if not said or said in _EVERY_CLIENT or said in _NOT_A_CLIENT:
        return None
    return client


class QueryAgent(BaseAgent):
    name = "query"
    description = "Answers questions like 'show my open tasks' or 'this week's demos'."
    system_prompt = (
        "You are the Query Agent of a B2B sales platform. "
        "A client name written in Kannada or Devanagari script is recorded in Latin letters: transliterate it before you search, never search in the original script. "
        "Answer questions by calling tools, then present results as a short, "
        "numbered plain-language list (the user may refer to items by number "
        "later). Never make up data — only report what tools return."
        # F45: asked "who is doing the curriculum", this answered with the
        # CLIENT's science coordinator; asked "who is ASSIGNED to the curriculum
        # task" it correctly answered our own agent. Retrieval was never broken —
        # the bare phrasing silently resolved to client-side people, which
        # inverts responsibility for a deliverable: the rep stops chasing
        # internally and waits on a client who was never asked.
        "\n\nWHO IS DOING SOMETHING: 'who is doing X', 'who owns X', 'who is "
        "handling X' mean WHICH OF OUR PEOPLE is responsible. Answer from the "
        "task's assignee (list_action_items), never from the client's staff. "
        "People at the client organisation appear in get_client_details; they "
        "are contacts, not people work can be given to. If no task matches and "
        "you answer from the client side instead, say so explicitly — 'nobody "
        "on our side is assigned; on the client side X is the contact for it'. "
        "Never present a client contact as the owner of our work."
        # F46 / F57: the same rule the spec puts above all ten engines — when
        # unsure, ask; never guess.
        "\n\nWHY SOMETHING WAS DECIDED: when asked why a person was picked for a "
        "task, quote `assignment_reason` VERBATIM, including any caveat such as "
        "'tie; lead should confirm or change'. That caveat is the point of the "
        "question. Never restate why you mentioned a name in conversation — that "
        "is not what is being asked. If the field is empty, say no reason was "
        "recorded rather than inventing one."
    )

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="list_action_items",
                description="List action items (tasks). Defaults to the caller's open items.",
                parameters={
                    "type": "object",
                    "properties": {
                        "owner": {
                            "type": "string",
                            "description": "'me', a colleague's name, or 'anyone'",
                        },
                        "status": {
                            "type": "string",
                            "description": "open | in_progress | done | cancelled | all",
                        },
                        "client": {
                            "type": "string",
                            "description": "filter by client name or id; defaults "
                            "to the client the user is viewing. Pass 'all' to "
                            "include every client.",
                        },
                    },
                },
                handler=self._list_action_items,
            ),
            ToolSpec(
                name="list_leads",
                description="List clients/leads, optionally by state or name search.",
                parameters={
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "open|active|cold|execution_in_progress|"
                                           "client_execution_in_progress|closed|lost_for_now|all",
                        },
                        "search": {"type": "string"},
                        "important_only": {"type": "boolean"},
                        "mine_only": {"type": "boolean"},
                    },
                },
                handler=self._list_leads,
            ),
            ToolSpec(
                name="get_client_details",
                description="Full picture of one client: state, contacts, recent "
                "notes, proposals. Defaults to the client the user is viewing.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {
                            "type": "string",
                            "description": "client name or id; optional when the "
                            "user is already viewing a client",
                        }
                    },
                },
                handler=self._client_details,
            ),
            ToolSpec(
                name="list_followups_due",
                description="Follow-ups that are due (today by default).",
                parameters={
                    "type": "object",
                    "properties": {
                        "when": {"type": "string", "description": "today | overdue | this_week | all_pending"}
                    },
                },
                handler=self._list_followups,
            ),
            ToolSpec(
                name="list_demos",
                description="Demos scheduled, optionally for a month (YYYY-MM) or a team.",
                parameters={
                    "type": "object",
                    "properties": {
                        "month": {"type": "string", "description": "YYYY-MM"},
                        "team": {"type": "string"},
                    },
                },
                handler=self._list_demos,
            ),
            ToolSpec(
                name="get_project_brief",
                # Found live 2026-08-06: "tell me a brief about the project"
                # fell through to semantic note search and came back empty,
                # because NO tool returned a project. Third instance of the
                # F46/F57 pattern.
                description=(
                    "Brief on a project: objective, status, health and WHY, the "
                    "live plan, task counts, the client's people, open promises "
                    "and what is due next. Use this for 'tell me about the "
                    "project', 'brief me', 'how is it going', 'where are we'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {
                            "type": "string",
                            "description": "client name or id; optional when the "
                            "user is already viewing a client",
                        }
                    },
                },
                handler=self._project_brief,
            ),
            ToolSpec(
                name="list_approvals",
                # F57: no agent exposed approvals AT ALL, so "how many approvals
                # are waiting on me" was answered from the task list — device-
                # proven on two roles, including a sales lead who genuinely held
                # approvals and got her to-do list back under "Due later". The
                # REST endpoint existed and the Approvals tab used it; nothing
                # wrapped it as a tool. Approvals are this product's central
                # control, so a confident wrong answer here is the worst kind.
                description=(
                    "Approvals waiting for a human decision — the human gate on "
                    "anything the AI drafts. Use this for any question about "
                    "approvals, sign-offs, or 'what is waiting on me'. This is "
                    "NOT the task list."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "mine": {
                            "type": "boolean",
                            "description": "only approvals routed to the caller "
                            "(default true)",
                        },
                        "status": {
                            "type": "string",
                            "description": "pending | approved | rejected | expired | all",
                        },
                        "client": {
                            "type": "string",
                            "description": "filter by client; defaults to the "
                            "client the user is viewing. Pass 'all' for every client.",
                        },
                    },
                },
                handler=self._list_approvals,
            ),
            ToolSpec(
                name="explain_decision",
                # F46: `why_trace` — documented as "'Why did the AI do that?' —
                # inputs, decision, reason, confidence, overrides" — had exactly
                # one caller, the REST endpoint behind the app's "Why?" chip. The
                # explainability data was reachable only by tapping a UI control,
                # never through natural language, though Data Model §5.5 says
                # "any human can ALWAYS ask why the AI did that".
                description=(
                    "Why the AI did something: the recorded inputs, decision, "
                    "reason and confidence for one record (a task, lead, plan or "
                    "project). Use for 'why did you...' questions."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "description": "action_item | lead | project | "
                            "action_plan | proposal | contact",
                        },
                        "entity_id": {"type": "string"},
                    },
                    "required": ["entity_type", "entity_id"],
                },
                handler=self._explain_decision,
            ),
            ToolSpec(
                name="search_past_notes",
                description="Semantic search over this organisation's past meeting notes and client intelligence.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "client": {
                            "type": "string",
                            "description": "optional client filter; defaults to the "
                            "client the user is viewing. Pass 'all' to search "
                            "across every client.",
                        },
                    },
                    "required": ["query"],
                },
                handler=self._search_notes,
            ),
        ]

    async def _list_action_items(
        self,
        runtime: AgentRuntime,
        owner: str = "me",
        status: str = "open",
        client: str | None = None,
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        stmt = select(ActionItem).where(ActionItem.org_id == ctx.org_id)
        if owner == "me" or not owner:
            stmt = stmt.where(ActionItem.owner_id == ctx.user_id)
        elif owner != "anyone":
            target = await resolve_user(runtime, owner)
            stmt = stmt.where(ActionItem.owner_id == target.id)
        if status and status != "all":
            stmt = stmt.where(ActionItem.status == status)
        else:
            stmt = stmt.where(ActionItem.status != ActionItemStatus.PENDING_REVIEW.value)
        client = _effective_client(runtime, client)
        if client:
            lead = await resolve_lead(runtime, client)
            stmt = stmt.where(ActionItem.lead_id == lead.id)
        items = (
            (await db.execute(stmt.order_by(ActionItem.created_at.desc()).limit(30)))
            .scalars().all()
        )
        results = []
        for item in items:
            owner_row = (
                await db.execute(select(User.name).where(User.id == item.owner_id))
            ).scalar_one_or_none()
            lead_row = (
                await db.execute(select(Lead.name).where(Lead.id == item.lead_id))
            ).scalar_one_or_none()
            results.append(_item_dict(item, owner_row, lead_row))
        return results

    async def _list_leads(
        self,
        runtime: AgentRuntime,
        state: str = "all",
        search: str | None = None,
        important_only: bool = False,
        mine_only: bool = False,
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        stmt = select(Lead).where(Lead.org_id == ctx.org_id)
        if state and state != "all":
            try:
                stmt = stmt.where(Lead.state == LeadState(state).value)
            except ValueError:
                return [{"error": f"Unknown state '{state}'"}]
        if search:
            stmt = stmt.where(func.lower(Lead.name).like(f"%{search.lower()}%"))
        if important_only:
            stmt = stmt.where(Lead.is_important.is_(True))
        if mine_only:
            stmt = stmt.where(Lead.owner_id == ctx.user_id)
        leads = (
            (await db.execute(stmt.order_by(Lead.last_activity_at.desc()).limit(30)))
            .scalars().all()
        )
        return [
            {
                "id": lead.id,
                "name": lead.name,
                "state": lead.state + (" (important)" if lead.is_important else ""),
                "city": lead.city,
                "last_activity": lead.last_activity_at.isoformat() if lead.last_activity_at else None,
                "suggested_state": lead.suggested_state,
            }
            for lead in leads
        ]

    async def _client_details(
        self, runtime: AgentRuntime, client: str | None = None
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        # No "all" here — a full-picture query needs exactly one client; fall
        # back to the viewed one, and resolve_lead raises a clear ask if neither.
        lead = await resolve_lead(runtime, client or runtime.extra_context.get("lead_id"))
        contacts = (
            await db.execute(
                select(Contact).where(Contact.org_id == ctx.org_id, Contact.lead_id == lead.id)
            )
        ).scalars().all()
        notes = (
            await db.execute(
                select(ClientIntelligence)
                .where(ClientIntelligence.org_id == ctx.org_id,
                       ClientIntelligence.lead_id == lead.id)
                .order_by(ClientIntelligence.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
        proposals = (
            await db.execute(
                select(Proposal)
                .where(Proposal.org_id == ctx.org_id, Proposal.lead_id == lead.id)
                .order_by(Proposal.created_at.desc())
                .limit(5)
            )
        ).scalars().all()
        open_items = (
            await db.execute(
                select(func.count(ActionItem.id)).where(
                    ActionItem.org_id == ctx.org_id,
                    ActionItem.lead_id == lead.id,
                    ActionItem.status.in_(["open", "in_progress"]),
                )
            )
        ).scalar_one()
        return {
            "id": lead.id,
            "name": lead.name,
            "state": lead.state,
            "important": lead.is_important,
            "city": lead.city,
            "open_action_items": open_items,
            "contacts": [
                {"name": c.name, "title": c.title, "email": c.email, "phone": c.phone}
                for c in contacts
            ],
            "recent_notes": [n.note for n in notes],
            "proposals": [
                {"id": p.id, "title": p.title, "status": p.status, "total": p.total_amount}
                for p in proposals
            ],
        }

    async def _project_brief(
        self, runtime: AgentRuntime, client: str | None = None
    ) -> dict[str, Any]:
        """The project behind the client the user is looking at."""
        from app.engines import assistant_engine

        db, ctx = runtime.db, runtime.ctx
        target = _effective_client(runtime, client)
        if not target:
            return {"error": "Name a client, or open one first."}
        lead = await resolve_lead(runtime, target)
        projects = (
            await db.execute(
                select(Project)
                .where(Project.org_id == ctx.org_id, Project.lead_id == lead.id)
                .order_by(Project.created_at.desc())
            )
        ).scalars().all()
        if not projects:
            return {
                "client": lead.name,
                "no_project_yet": True,
                "note": (
                    f"{lead.name} has no project yet — a project is born when a "
                    f"meeting is recorded and its plan confirmed."
                ),
            }
        live = [p for p in projects if p.status not in ("closed", "lost")]
        if len(live) > 1:
            return {
                "client": lead.name,
                "several_projects": [p.name for p in live],
                "note": "Say which one you mean.",
            }
        return await assistant_engine.project_brief(
            db, org_id=ctx.org_id, project=(live or projects)[0]
        )

    async def _list_approvals(
        self,
        runtime: AgentRuntime,
        mine: bool = True,
        status: str = "pending",
        client: str | None = None,
    ) -> list[dict[str, Any]]:
        """Approvals waiting on a human (F57).

        Returns `stage` deliberately. This org holds a `stage=recommend`
        approval that does NOT appear in the default decide queue, so an answer
        that counted it alongside decide-stage cards would mislead in a second,
        quieter way — the finding warns about exactly that.
        """
        from app.core.constants import ApprovalStatus
        from app.models.comms import Approval

        db, ctx = runtime.db, runtime.ctx
        stmt = select(Approval).where(Approval.org_id == ctx.org_id)
        if status and status != "all":
            stmt = stmt.where(Approval.status == status)
        if mine:
            stmt = stmt.where(Approval.requested_from_user_id == ctx.user_id)
        target = _effective_client(runtime, client)
        if target:
            lead = await resolve_lead(runtime, target)
            project_ids = (
                await db.execute(
                    select(Project.id).where(Project.lead_id == lead.id)
                )
            ).scalars().all()
            stmt = stmt.where(Approval.project_id.in_(project_ids or [""]))
        rows = (
            await db.execute(stmt.order_by(Approval.created_at.desc()).limit(30))
        ).scalars().all()

        results: list[dict[str, Any]] = []
        for a in rows:
            results.append(
                {
                    "id": a.id,
                    "what_is_being_approved": a.entity_type,
                    "reason": a.reason,
                    # Without the stage the count is not comparable to the queue
                    # the user is looking at.
                    "stage": a.stage,
                    "status": a.status,
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                }
            )
        return results

    async def _explain_decision(
        self, runtime: AgentRuntime, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        """The recorded reasoning behind one record (F46).

        Data Model §5.5: "any human can always ask 'why did the AI do that?' and
        get the inputs, the decision, the reason, and the confidence." That was
        true only by tapping the app's Why? chip — `why_trace` had one caller and
        no agent exposed it.
        """
        from app.engines import assistant_engine

        trace = await assistant_engine.why_trace(
            runtime.db, org_id=runtime.ctx.org_id,
            entity_type=entity_type, entity_id=entity_id,
        )
        return {"entity_type": entity_type, "entity_id": entity_id, "trace": trace}

    async def _list_followups(
        self, runtime: AgentRuntime, when: str = "today"
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        today = clock.today(await clock.org_zone(db, ctx.org_id))
        stmt = select(FollowUp).where(
            FollowUp.org_id == ctx.org_id,
            FollowUp.status == FollowUpStatus.PENDING.value,
        )
        if when == "today":
            stmt = stmt.where(FollowUp.due_date <= today)
        elif when == "overdue":
            stmt = stmt.where(FollowUp.due_date < today)
        elif when == "this_week":
            stmt = stmt.where(FollowUp.due_date <= today + timedelta(days=7))
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

    async def _list_demos(
        self, runtime: AgentRuntime, month: str | None = None, team: str | None = None
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        stmt = select(Demo).where(Demo.org_id == ctx.org_id)
        if month:
            try:
                year_s, month_s = month.split("-")
                start = date(int(year_s), int(month_s), 1)
            except ValueError:
                return [{"error": f"Month must be YYYY-MM, got '{month}'"}]
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
            stmt = stmt.where(Demo.scheduled_date >= start, Demo.scheduled_date < end)
        if team:
            from app.ai.agents.resolvers import resolve_team

            team_row = await resolve_team(runtime, team)
            stmt = stmt.where(Demo.team_id == team_row.id)
        demos = (
            (await db.execute(stmt.order_by(Demo.scheduled_date).limit(50))).scalars().all()
        )
        results = []
        for demo in demos:
            lead_name = (
                await db.execute(select(Lead.name).where(Lead.id == demo.lead_id))
            ).scalar_one_or_none()
            team_name = (
                await db.execute(select(DemoTeam.name).where(DemoTeam.id == demo.team_id))
            ).scalar_one_or_none()
            results.append(
                {
                    "client": lead_name,
                    "date": demo.scheduled_date.isoformat(),
                    "time": demo.scheduled_time,
                    "team": team_name,
                    "status": demo.status,
                }
            )
        return results

    async def _search_notes(
        self, runtime: AgentRuntime, query: str, client: str | None = None
    ) -> list[dict[str, Any]]:
        lead_id = None
        client = _effective_client(runtime, client)
        if client:
            lead = await resolve_lead(runtime, client)
            lead_id = lead.id
        return await memory_ai.search_memory(
            runtime.db, org_id=runtime.ctx.org_id, query=query, lead_id=lead_id
        )
