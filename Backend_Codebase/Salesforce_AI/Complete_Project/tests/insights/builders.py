"""Row builders for the sales head tests (23 Oct 2026).

The insight modules are pure reads over rows the rest of the system writes, so
their tests build those rows directly through the ORM, with exact timestamps,
instead of driving the whole API to reach a state. Every builder flushes and
returns the row. Timestamps are naive UTC, like every stored instant.

Columns a builder does not care about get harmless values; SQLite does not
enforce foreign keys, so a dummy id is enough where one is required.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from app.models.action_item import ActionItem
from app.models.assistant import AssistantTurn
from app.models.audit import AuditLog, LlmUsage
from app.models.comms import InboundMessage, Thread
from app.models.demo import Demo
from app.models.followup import FollowUp
from app.models.lead import ClientIntelligence, Contact, Lead, LeadStateHistory
from app.models.location import LocationPing
from app.models.meeting import Meeting, Transcript
from app.models.messaging import OutboundMessage
from app.models.organisation import Organisation, OrgSettings
from app.models.project import ClientCommitment, Project, Stakeholder
from app.models.proposal import Proposal
from app.models.relationship import RelationshipEngagement
from app.models.user import User
from app.models.work import Assignment

DEPARTMENT = {
    "sales_agent": "sales", "sales_lead": "sales", "sales_head": "sales",
    "relationship_manager": "relationship", "operations_agent": "operations",
    "operations_lead": "operations", "org_admin": None,
}


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _id(thing) -> str | None:
    """A row's id, or the string itself (a deleted person is only an id)."""
    if thing is None:
        return None
    return thing if isinstance(thing, str) else thing.id


async def _add(db, row):
    db.add(row)
    await db.flush()
    return row


async def make_org(db, *, name, tz="Asia/Kolkata", budget=50.0) -> Organisation:
    tag = _tag()
    org = await _add(db, Organisation(name=name, slug=f"org-{tag}",
                                      email_domain=f"{tag}.example.com"))
    await _add(db, OrgSettings(org_id=org.id, timezone=tz, llm_monthly_budget_usd=budget))
    return org


async def make_user(db, org, *, name, role, created_at=None, max_open_tasks=8,
                    is_active=True, working_days=None, on_leave=None) -> User:
    tag = _tag()
    user = User(
        org_id=org.id, email=f"{tag}@{org.email_domain}", name=name, role=role,
        password_hash="not-a-hash", is_active=is_active,
        department=DEPARTMENT.get(role), max_open_tasks=max_open_tasks,
        working_days=working_days,
    )
    if created_at is not None:
        user.created_at = created_at
    if on_leave is not None:
        user.on_leave_from, user.on_leave_to = on_leave
    return await _add(db, user)


async def make_lead(db, org, *, name, state, owner=None, created_by=None, created_at,
                    moves=(), last_activity_at=None, is_important=False) -> Lead:
    """`moves` are (from_state, to_state, user or "system", at) written to
    lead_state_history, after the creation row the real service writes
    (from_state None)."""
    lead = await _add(db, Lead(
        org_id=org.id, name=name, state=state, owner_id=_id(owner),
        is_important=is_important, created_at=created_at,
        last_activity_at=last_activity_at or created_at,
    ))
    first = moves[0][0] if moves else state
    await _add(db, LeadStateHistory(
        org_id=org.id, lead_id=lead.id, from_state=None, to_state=first,
        changed_by=_id(created_by), changed_at=created_at,
    ))
    for from_state, to_state, by, at in moves:
        await _add(db, LeadStateHistory(
            org_id=org.id, lead_id=lead.id, from_state=from_state, to_state=to_state,
            changed_by=by if isinstance(by, str) else _id(by), changed_at=at,
        ))
    await _add(db, AuditLog(
        org_id=org.id, user_id=_id(created_by), action="lead.created",
        entity_type="lead", entity_id=lead.id,
        detail={"name": name, "owner_id": _id(owner)}, at=created_at,
    ))
    return lead


async def make_meeting(db, org, lead, *, by, at, minutes=None, meeting_type=None,
                       plan_state=None, summary=None, stakeholder_ids=()) -> Meeting:
    meeting = await _add(db, Meeting(
        org_id=org.id, lead_id=lead.id, agent_id=_id(by), status="completed",
        started_at=at, created_at=at,
        duration_seconds=None if minutes is None else int(minutes * 60),
        meeting_type=meeting_type, plan_state=plan_state,
        attendee_stakeholder_ids=list(stakeholder_ids),
    ))
    if summary is not None:
        await _add(db, Transcript(org_id=org.id, meeting_id=meeting.id, text="(transcript)",
                                  summary=summary, word_count=100))
    return meeting


async def make_task(db, org, *, assignee, due, completed_at=None, status="open",
                    lead=None, meeting=None, result_note=None, completion_method=None,
                    created_at=None) -> ActionItem:
    if completed_at is not None and status == "open":
        status = "done"
    task = ActionItem(
        org_id=org.id, title=f"Task {_tag()}", assignee_id=_id(assignee),
        status=status, due_date=due, completed_at=completed_at,
        lead_id=_id(lead), meeting_id=_id(meeting), result_note=result_note,
        completion_method=completion_method,
    )
    task.created_at = created_at or ((due or datetime(2026, 1, 1)) - timedelta(days=3))
    return await _add(db, task)


async def make_followup(db, org, lead, *, owner, due: date, completed_at=None,
                        message_id=None) -> FollowUp:
    return await _add(db, FollowUp(
        org_id=org.id, lead_id=lead.id, owner_id=_id(owner), due_date=due,
        status="done" if completed_at else "pending",
        completed_at=completed_at, message_id=message_id,
    ))


async def make_outbound(db, org, lead, *, sender, sent_at, kind="follow_up",
                        status="sent") -> OutboundMessage:
    message = OutboundMessage(
        org_id=org.id, kind=kind, channel="email", status=status,
        lead_id=_id(lead), sender_user_id=_id(sender), to_address="client@example.com",
        body="(message)", idempotency_key=_tag(), sent_at=sent_at,
    )
    message.created_at = sent_at or datetime(2026, 1, 1)
    return await _add(db, message)


async def make_inbound(db, org, lead, *, at, sentiment=None, intent=None) -> InboundMessage:
    message = InboundMessage(
        org_id=org.id, channel="email", body="(reply)", received_at=at,
        matched_lead_id=_id(lead), sentiment=sentiment, intent=intent, status="processed",
    )
    message.created_at = at
    return await _add(db, message)


async def make_thread(db, org, lead, *, last_direction, last_message_at) -> Thread:
    return await _add(db, Thread(
        org_id=org.id, lead_id=lead.id, contact_id=_tag(), channel="email",
        last_direction=last_direction, last_message_at=last_message_at,
    ))


async def make_note(db, org, lead, *, by, at) -> ClientIntelligence:
    note = ClientIntelligence(org_id=org.id, lead_id=lead.id, note="(note)", added_by=_id(by))
    note.created_at = at
    return await _add(db, note)


async def make_contact(db, org, lead, *, by, at, name="Client Contact") -> Contact:
    contact = Contact(org_id=org.id, lead_id=lead.id, name=name, phone="+91 90000 00000",
                      created_by=_id(by))
    contact.created_at = at
    return await _add(db, contact)


async def make_project(db, org, lead, *, sales_owner=None) -> Project:
    return await _add(db, Project(org_id=org.id, lead_id=lead.id, name=f"{lead.name} work",
                                  sales_owner_id=_id(sales_owner)))


async def make_stakeholder(db, org, project, *, influence, name="Client Person",
                           role_at_client=None) -> Stakeholder:
    contact = await _add(db, Contact(org_id=org.id, lead_id=project.lead_id, name=name))
    return await _add(db, Stakeholder(org_id=org.id, project_id=project.id,
                                      contact_id=contact.id, influence=influence,
                                      role_at_client=role_at_client))


async def make_commitment(db, org, project, *, direction, status, due) -> ClientCommitment:
    return await _add(db, ClientCommitment(org_id=org.id, project_id=project.id,
                                           text="(promise)", direction=direction,
                                           status=status, due_date=due))


async def make_demo(db, org, lead, *, status, completed_at=None) -> Demo:
    when = completed_at or datetime(2026, 1, 1)
    return await _add(db, Demo(org_id=org.id, lead_id=lead.id, scheduled_date=when.date(),
                               status=status, completed_at=completed_at))


async def make_proposal(db, org, lead, *, status, sent_at=None, total_amount=0.0) -> Proposal:
    return await _add(db, Proposal(
        org_id=org.id, lead_id=lead.id, program_id="program", title="Proposal",
        status=status, template_id="template", template_version=1,
        content_md="(proposal)", total_amount=total_amount, created_by="someone",
        sent_at=sent_at,
    ))


async def make_ping(db, org, user, *, at, status="ok", lat=None, lng=None, mock=False,
                    approximate=False, trigger="open") -> LocationPing:
    if status == "ok":
        lat = 12.9716 if lat is None else lat
        lng = 77.5946 if lng is None else lng
    return await _add(db, LocationPing(
        org_id=org.id, user_id=_id(user), client_ref=_tag(), status=status,
        lat=lat, lng=lng, is_mock=mock, approximate=approximate, trigger=trigger,
        captured_at=at, received_at=at,
    ))


async def make_usage(db, org, *, user=None, model, purpose, cost, at, duration_ms=1500,
                     error=None) -> LlmUsage:
    return await _add(db, LlmUsage(
        org_id=org.id, user_id=_id(user), provider="openrouter", model=model,
        purpose=purpose, input_tokens=100, output_tokens=50, cost_usd=cost,
        duration_ms=duration_ms, error=error, at=at,
    ))


async def make_login(db, org, user, *, at) -> AuditLog:
    return await _add(db, AuditLog(org_id=org.id, user_id=_id(user), action="auth.login", at=at))


async def make_assistant_turn(db, org, user, *, at, session_id) -> AssistantTurn:
    turn = AssistantTurn(org_id=org.id, user_id=_id(user), session_id=session_id,
                         seq=0, role="user", content="(asked)")
    turn.created_at = at
    return await _add(db, turn)


async def make_assignment(db, org, task, *, to, status, decline_reason=None,
                          decline_note=None, decided_at=None) -> Assignment:
    return await _add(db, Assignment(
        org_id=org.id, action_item_id=task.id, to_user_id=_id(to), status=status,
        decline_reason=decline_reason, decline_note=decline_note, decided_at=decided_at,
        assigned_by="ai",
    ))


async def make_engagement(db, org, lead, *, manager, opportunity_status="none",
                          reason=None, at=None) -> RelationshipEngagement:
    return await _add(db, RelationshipEngagement(
        org_id=org.id, lead_id=lead.id, manager_id=_id(manager), assigned_by="someone",
        opportunity_status=opportunity_status, opportunity_reason=reason, opportunity_at=at,
    ))
