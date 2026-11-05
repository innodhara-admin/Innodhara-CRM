"""Scheduling Agent — demo dates, team schedules, calendar view (doc §6, §9.3),
and client meetings, which are not demos (customer ask, 21 Sep 2026)."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
from app.ai.agents.resolvers import resolve_lead, resolve_team
from app.core import clock
from app.core.constants import DemoStatus
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.permissions import has_permission
from app.models.base import utcnow
from app.models.demo import Demo, DemoTeam, DemoTeamMember
from app.models.lead import Lead
from app.models.organisation import OrgSettings
from app.models.user import User
from app.services import audit_service, calendar_service, lead_service


def _parse_month(month: str | None, today: date) -> tuple[date, date]:
    """`today` is passed in rather than read here: "this month" means the month
    it is in the *organisation's* timezone, and this helper has no way to ask."""
    if month:
        year_s, month_s = month.split("-")
        start = date(int(year_s), int(month_s), 1)
    else:
        start = date(today.year, today.month, 1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return start, end


class SchedulingAgent(BaseAgent):
    name = "scheduling"
    description = "Books demos and client meetings, shows team schedules and the month calendar."
    system_prompt = (
        "You are the Scheduling Agent. You manage client demos and demo teams: "
        "list committed clients and demo dates, show each team's schedule, "
        "render a month calendar, and book or move demos. When booking, check "
        "the team's availability first and mention any clash you find.\n"
        "A MEETING is not a demo. When the person asks to schedule, set up, "
        "arrange or fix a meeting, a call or a visit with a client, use "
        "schedule_meeting — never book_demo. Use book_demo only when they "
        "actually say demo or demonstration. Pass schedule_meeting whatever "
        "they said (client, day, time, purpose, who to copy) even if something "
        "is missing: the tool asks for the rest itself. Never ask for a missing "
        "detail in your own words, and never invent a day or a time."
    )

    #: The meeting tool's question is the reply, so prose cannot contradict it.
    CARD_TOOLS = frozenset({"schedule_meeting"})

    async def run(self, db, ctx, user_text, extra_context=None, history=None):
        # The meeting tool checks the model's day/time/length against what
        # the person actually said (meeting_draft.ground), so it needs the
        # words themselves. Passed here rather than in BaseAgent so no other
        # agent's context changes.
        context = dict(extra_context or {})
        context["_user_text"] = user_text
        return await super().run(db, ctx, user_text, extra_context=context,
                                 history=history)

    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="list_demos",
                description="List scheduled demos with client, date and team.",
                parameters={
                    "type": "object",
                    "properties": {
                        "month": {"type": "string", "description": "YYYY-MM (optional)"},
                        "team": {"type": "string"},
                    },
                },
                handler=self._list_demos,
            ),
            ToolSpec(
                name="list_demo_teams",
                description="List demo teams with their members.",
                parameters={"type": "object", "properties": {}},
                handler=self._list_teams,
            ),
            ToolSpec(
                name="calendar_view",
                description="Month grid: every day of the month with its demos, so free days are obvious.",
                parameters={
                    "type": "object",
                    "properties": {
                        "month": {"type": "string", "description": "YYYY-MM, default current"},
                        "team": {"type": "string"},
                    },
                },
                handler=self._calendar_view,
            ),
            ToolSpec(
                name="book_demo",
                description="Schedule a demo for a client on a date, optionally with a team and time.",
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "demo_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "team": {"type": "string"},
                        "time": {"type": "string", "description": "HH:MM"},
                        "notes": {"type": "string"},
                    },
                    "required": ["client", "demo_date"],
                },
                handler=self._book_demo,
            ),
            ToolSpec(
                name="schedule_meeting",
                description=(
                    "Schedule a MEETING with a client (a call, a visit, a "
                    "discussion) — not a demo. Drafts the invite email for "
                    "approval. Pass everything the person said; anything "
                    "missing is asked for by the tool."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string"},
                        "date": {"type": "string", "description": "YYYY-MM-DD, or the person's words ('Friday')"},
                        "time": {"type": "string", "description": "HH:MM 24-hour"},
                        "duration_minutes": {"type": "integer"},
                        "purpose": {"type": "string"},
                        "cc": {"type": "array", "items": {"type": "string"}, "description": "email addresses"},
                        "bcc": {"type": "array", "items": {"type": "string"}, "description": "email addresses"},
                    },
                },
                handler=self._schedule_meeting,
            ),
            ToolSpec(
                name="list_meetings",
                description="List scheduled client meetings (not demos), optionally for one client.",
                parameters={
                    "type": "object",
                    "properties": {"client": {"type": "string"}},
                },
                handler=self._list_meetings,
            ),
            ToolSpec(
                name="cancel_meeting",
                description="Cancel a client meeting (pass its id from list_meetings). Drafts a cancellation email for approval.",
                parameters={
                    "type": "object",
                    "properties": {"meeting_id": {"type": "string"}},
                    "required": ["meeting_id"],
                },
                handler=self._cancel_meeting,
            ),
            ToolSpec(
                name="cancel_demo",
                description="Cancel a scheduled demo (pass its id from list_demos).",
                parameters={
                    "type": "object",
                    "properties": {"demo_id": {"type": "string"}},
                    "required": ["demo_id"],
                },
                handler=self._cancel_demo,
            ),
        ]

    async def _list_demos(
        self, runtime: AgentRuntime, month: str | None = None, team: str | None = None
    ) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        stmt = select(Demo).where(
            Demo.org_id == ctx.org_id, Demo.status != DemoStatus.CANCELLED.value
        )
        if month:
            try:
                start, end = _parse_month(
                    month, clock.today(await clock.org_zone(db, ctx.org_id))
                )
            except ValueError:
                return [{"error": f"Month must be YYYY-MM, got '{month}'"}]
            stmt = stmt.where(Demo.scheduled_date >= start, Demo.scheduled_date < end)
        if team:
            team_row = await resolve_team(runtime, team)
            stmt = stmt.where(Demo.team_id == team_row.id)
        demos = (
            (await db.execute(stmt.order_by(Demo.scheduled_date).limit(60))).scalars().all()
        )
        results = []
        for demo in demos:
            client = (
                await db.execute(select(Lead.name).where(Lead.id == demo.lead_id))
            ).scalar_one_or_none()
            team_name = (
                await db.execute(select(DemoTeam.name).where(DemoTeam.id == demo.team_id))
            ).scalar_one_or_none()
            results.append(
                {
                    "id": demo.id,
                    "client": client,
                    "date": demo.scheduled_date.isoformat(),
                    "time": demo.scheduled_time,
                    "team": team_name,
                    "status": demo.status,
                }
            )
        return results

    async def _list_teams(self, runtime: AgentRuntime) -> list[dict[str, Any]]:
        db, ctx = runtime.db, runtime.ctx
        teams = (
            await db.execute(select(DemoTeam).where(DemoTeam.org_id == ctx.org_id))
        ).scalars().all()
        results = []
        for team in teams:
            async def _name(user_id: str | None) -> str | None:
                if not user_id:
                    return None
                return (
                    await db.execute(select(User.name).where(User.id == user_id))
                ).scalar_one_or_none()

            members = (
                await db.execute(
                    select(User.name)
                    .join(DemoTeamMember, DemoTeamMember.user_id == User.id)
                    .where(DemoTeamMember.team_id == team.id)
                )
            ).scalars().all()
            results.append(
                {
                    "id": team.id,
                    "name": team.name,
                    "lead": await _name(team.lead_user_id),
                    "media_rep": await _name(team.media_rep_id),
                    "sales_rep": await _name(team.sales_rep_id),
                    "members": list(members),
                }
            )
        return results

    async def _calendar_view(
        self, runtime: AgentRuntime, month: str | None = None, team: str | None = None
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        try:
            start, end = _parse_month(
                month, clock.today(await clock.org_zone(db, ctx.org_id))
            )
        except ValueError:
            return {"error": f"Month must be YYYY-MM, got '{month}'"}
        demos = await self._list_demos(
            runtime, month=start.strftime("%Y-%m"), team=team
        )
        days: dict[str, list[dict[str, Any]]] = {}
        day = start
        while day < end:
            days[day.isoformat()] = []
            day = date.fromordinal(day.toordinal() + 1)
        for demo in demos:
            if isinstance(demo, dict) and demo.get("date") in days:
                days[demo["date"]].append(demo)
        free_days = [d for d, items in days.items() if not items]
        return {
            "month": start.strftime("%Y-%m"),
            "days": days,
            "free_days": free_days,
            "total_demos": len(demos),
        }

    async def _book_demo(
        self,
        runtime: AgentRuntime,
        client: str,
        demo_date: str,
        team: str | None = None,
        time: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        if not has_permission(ctx.role, "schedule_demos"):
            raise PermissionDeniedError(
                "Only Operations Leads, Sales Leads or Org Admins can schedule demos."
            )
        lead = await resolve_lead(runtime, client)
        lead_service.ensure_opened(lead, "booking a demo")
        try:
            on_date = date.fromisoformat(demo_date)
        except ValueError:
            return {"error": f"Date must be YYYY-MM-DD, got '{demo_date}'"}

        team_row = await resolve_team(runtime, team) if team else None
        clash_note = None
        if team_row:
            clash = (
                await db.execute(
                    select(Demo).where(
                        Demo.org_id == ctx.org_id,
                        Demo.team_id == team_row.id,
                        Demo.scheduled_date == on_date,
                        Demo.status == DemoStatus.SCHEDULED.value,
                    )
                )
            ).scalars().first()
            if clash:
                clash_client = (
                    await db.execute(select(Lead.name).where(Lead.id == clash.lead_id))
                ).scalar_one_or_none()
                clash_note = (
                    f"Warning: {team_row.name} already has a demo at "
                    f"{clash_client} on {on_date.isoformat()}."
                )

        demo = Demo(
            org_id=ctx.org_id,
            lead_id=lead.id,
            team_id=team_row.id if team_row else None,
            scheduled_date=on_date,
            scheduled_time=time,
            notes=notes,
            created_by=ctx.user_id,
        )
        db.add(demo)
        await db.flush()

        settings_row = (
            await db.execute(select(OrgSettings).where(OrgSettings.org_id == ctx.org_id))
        ).scalar_one_or_none()
        event_id = await calendar_service.create_event(
            org_calendar_integration=settings_row.calendar_integration if settings_row else None,
            title=f"Demo: {lead.name}" + (f" ({team_row.name})" if team_row else ""),
            description=notes or "",
            on_date=on_date,
            time_hhmm=time,
        )
        if event_id:
            demo.calendar_event_id = event_id

        from app.services import demo_invite_service

        invite = await demo_invite_service.compose_demo_invite(
            db, ctx, demo=demo, lead=lead, team=team_row, change="scheduled"
        )
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id,
            action="demo.booked", entity_type="demo", entity_id=demo.id,
            detail={"client": lead.name, "date": on_date.isoformat()},
        )
        result = {
            "booked": True,
            "id": demo.id,
            "client": lead.name,
            "date": on_date.isoformat(),
            "team": team_row.name if team_row else None,
            "google_calendar": bool(event_id),
            "invite_email": (
                "drafted for approval" if invite else "no contact email on the lead"
            ),
        }
        if clash_note:
            result["warning"] = clash_note
        return result

    async def _schedule_meeting(self, runtime: AgentRuntime, **values: Any) -> dict[str, Any]:
        from app.ai import meeting_draft

        return await meeting_draft.start(runtime, values)

    async def _list_meetings(
        self, runtime: AgentRuntime, client: str | None = None
    ) -> list[dict[str, Any]]:
        from app.models.scheduled_meeting import ScheduledMeeting

        db, ctx = runtime.db, runtime.ctx
        stmt = select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == ctx.org_id, ScheduledMeeting.status == "scheduled"
        )
        if client:
            lead = await resolve_lead(runtime, client)
            stmt = stmt.where(ScheduledMeeting.lead_id == lead.id)
        rows = (
            await db.execute(stmt.order_by(ScheduledMeeting.meeting_date).limit(60))
        ).scalars().all()
        out = []
        for m in rows:
            name = (
                await db.execute(select(Lead.name).where(Lead.id == m.lead_id))
            ).scalar_one_or_none()
            out.append({"id": m.id, "client": name, "date": m.meeting_date.isoformat(),
                        "time": m.start_time, "duration_minutes": m.duration_minutes,
                        "purpose": m.purpose})
        return out

    async def _cancel_meeting(self, runtime: AgentRuntime, meeting_id: str) -> dict[str, Any]:
        from app.models.scheduled_meeting import ScheduledMeeting
        from app.services import meeting_invite_service

        db, ctx = runtime.db, runtime.ctx
        if not meeting_invite_service.may_schedule(ctx.role):
            raise PermissionDeniedError("Your role cannot arrange client meetings.")
        meeting = (
            await db.execute(select(ScheduledMeeting).where(
                ScheduledMeeting.id == meeting_id, ScheduledMeeting.org_id == ctx.org_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError("Meeting not found — call list_meetings first.")
        invite = await meeting_invite_service.cancel(db, ctx, meeting)
        return {"cancelled": True, "scheduled_meeting_id": meeting.id,
                "cancellation_email": "drafted for approval" if invite else "none needed",
                "approval_id": (await meeting_invite_service.approval_id_for(db, invite)
                                if invite else None)}

    async def _cancel_demo(self, runtime: AgentRuntime, demo_id: str) -> dict[str, Any]:
        db, ctx = runtime.db, runtime.ctx
        if not has_permission(ctx.role, "schedule_demos"):
            raise PermissionDeniedError("You don't have permission to cancel demos.")
        demo = (
            await db.execute(
                select(Demo).where(Demo.id == demo_id, Demo.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        if demo is None:
            raise NotFoundError("Demo not found — call list_demos first.")
        demo.status = DemoStatus.CANCELLED.value
        demo.completed_at = utcnow()
        if demo.calendar_event_id:
            settings_row = (
                await db.execute(
                    select(OrgSettings).where(OrgSettings.org_id == ctx.org_id)
                )
            ).scalar_one_or_none()
            await calendar_service.delete_event(
                org_calendar_integration=settings_row.calendar_integration
                if settings_row else None,
                event_id=demo.calendar_event_id,
            )
        from app.services import demo_invite_service

        lead = (
            await db.execute(
                select(Lead).where(Lead.id == demo.lead_id, Lead.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        invite = None
        if lead is not None:
            invite = await demo_invite_service.compose_demo_invite(
                db, ctx, demo=demo, lead=lead, change="cancelled"
            )
        return {
            "cancelled": True,
            "id": demo.id,
            "cancellation_email": (
                "drafted for approval" if invite else "no contact email on the lead"
            ),
        }
