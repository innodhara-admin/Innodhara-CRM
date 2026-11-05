"""Inbound Engine — reads every incoming email/WhatsApp; matches sender →
contact → project → thread; classifies intent, change type and sentiment;
extracts concrete asks; routes to the right machinery. Anything unclear →
needs_human; anything unmatched → triage. Nothing is ever dropped
(30-Workflows §4 engine 7).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ActionItemStatus,
    ApprovalEntityType,
    ChangeType,
    CommitmentStatus,
    DecisionType,
    EventType,
    FollowUpStatus,
    InboundIntent,
    InboundStatus,
    InvoiceStatus,
    IncidentSeverity,
    IncidentStatus,
    MessageKind,
    Phase,
    PlanStatus,
    ProjectStatus,
    ProposalStatus,
    Role,
    Sentiment,
    TaskPriority,
    TaskSource,
    ThreadStatus,
)
from app.engines import communication_engine, events, nlu
from app.engines.common import (
    find_role_user,
    get_org_settings,
    get_user,
    record_decision,
)
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.comms import InboundMessage, Thread
from app.models.followup import FollowUp
from app.models.lead import Contact, Lead, ClientIntelligence
from app.models.meeting import Meeting
from app.models.project import ActionPlan, ClientCommitment, Conflict, Project, Stakeholder
from app.models.proposal import Proposal
from app.models.work import Incident, Reminder
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "inbound"


# ─────────────────────────────────────────────────────────────────────────────
# Matching: thread first, then sender, then content
# ─────────────────────────────────────────────────────────────────────────────



def reply_subject(msg: InboundMessage, project: Project | None = None) -> str:
    """A subject for a reply, even when the inbound had none (F44).

    All six reply sites derived `f"Re: {msg.subject}" if msg.subject else None`.
    But the app's *Log a client reply* sheet marks Subject "(optional)" — quite
    correctly, since a phone call or a WhatsApp message has no subject. Leave it
    blank, as anyone logging a call would, and EVERY generated reply came out
    subjectless. Both pending replies on the system were.

    A subjectless email whose first line reads "Subject: Re: …" is what the
    client would have received; F44's other half now moves that line into this
    field, and this is the floor beneath it — the project the conversation is
    about, which is what a human would have typed.
    """
    if msg.subject:
        return f"Re: {msg.subject}"
    if project is not None and project.name:
        return f"Re: {project.name}"
    return "Re: your message"


async def _match_contact(
    db: AsyncSession, org_id: str, channel: str, from_address: str | None
) -> Contact | None:
    if not from_address:
        return None
    addr = from_address.strip().lower()
    if channel == "email":
        from sqlalchemy import func

        return (
            await db.execute(
                select(Contact).where(
                    Contact.org_id == org_id,
                    func.lower(Contact.email) == addr,
                )
            )
        ).scalars().first()
    # WhatsApp: match by phone digits (suffix match, numbers vary in prefix).
    digits = "".join(ch for ch in addr if ch.isdigit())[-10:]
    if not digits:
        return None
    candidates = (
        await db.execute(
            select(Contact).where(Contact.org_id == org_id, Contact.phone.is_not(None))
        )
    ).scalars().all()
    for c in candidates:
        c_digits = "".join(ch for ch in (c.phone or "") if ch.isdigit())[-10:]
        if c_digits and c_digits == digits:
            return c
    return None


async def _match_projects(
    db: AsyncSession, org_id: str, lead_id: str, text: str
) -> tuple[Project | None, list[Project]]:
    """(primary project, all mentioned projects). Thread matching happens
    before this; content matching decides among a school's projects. Closed
    projects still count as content matches ("regarding the December
    bootcamp…" must attach to its timeline) but are never the default."""
    projects = (
        await db.execute(
            select(Project).where(
                Project.org_id == org_id,
                Project.lead_id == lead_id,
            )
        )
    ).scalars().all()
    open_projects = [
        p for p in projects
        if p.status not in (ProjectStatus.CLOSED.value, ProjectStatus.LOST.value)
    ]
    if not projects:
        return None, []
    if len(projects) == 1 and open_projects:
        return projects[0], projects

    if nlu.llm_available():
        # Production: the model reads the message against the projects'
        # names/objectives — generic, no keyword overlap needed.
        from app.ai import planning

        try:
            picked_ids = await planning.match_message_project(
                org_id=org_id, text=text, projects=list(projects)
            )
        except planning.PlanningUnavailable:
            picked_ids = []
        if len(picked_ids) == 1:
            picked = next(p for p in projects if p.id == picked_ids[0])
            return picked, [picked]
        if len(picked_ids) > 1:
            # The message deliberately spans several projects ("let's discuss
            # both …"): no single primary, every concerned project listed so
            # related_project_ids records the span and a human sorts it.
            chosen = set(picked_ids)
            return None, [p for p in projects if p.id in chosen]
        # Genuinely ambiguous (or model down): a single live project is still
        # the safe default. With several, return NO mentions — the content
        # references nothing specific, so thread continuity decides (a reply
        # on the invoice thread belongs to the invoice's project); a message
        # with no thread either routes project-less or reaches a human.
        if len(open_projects) == 1:
            return open_projects[0], open_projects
        return None, []

    t = text.lower()
    t_words = set(re.findall(r"[a-z0-9]+", t))
    stop = {
        "school", "with", "project", "the", "and", "for", "our", "new",
        "about", "per", "day", "days", "class", "classes", "students",
    }
    word_sets: list[tuple[Project, set[str]]] = []
    for p in projects:
        word_sets.append(
            (
                p,
                {
                    w
                    for w in re.findall(
                        r"[a-z0-9]+", (p.name + " " + (p.objective or "")).lower()
                    )
                    if len(w) >= 3 and w not in stop
                },
            )
        )
    # Only DISCRIMINATIVE words count: the school's own name (and anything
    # else shared between two projects) can never tell projects apart.
    if len(word_sets) > 1:
        counts: dict[str, int] = {}
        for _p, ws in word_sets:
            for w in ws:
                counts[w] = counts.get(w, 0) + 1
        word_sets = [
            (p, {w for w in ws if counts[w] == 1}) for p, ws in word_sets
        ]
    scored: list[tuple[int, Project]] = []
    for p, words in word_sets:
        scored.append((sum(1 for w in words if w in t_words), p))
    scored.sort(key=lambda x: -x[0])
    mentioned = [p for score, p in scored if score > 0]
    if len(mentioned) == 1:
        return mentioned[0], mentioned
    if len(mentioned) > 1 and scored[0][0] > scored[1][0]:
        return scored[0][1], mentioned
    if not mentioned and len(open_projects) == 1:
        # No content signal — the school's single live project is the default.
        return open_projects[0], open_projects
    # genuinely can't tell → no primary, all listed
    return None, mentioned or open_projects


async def _cancel_reply_watches(db: AsyncSession, org_id: str, thread: Thread) -> None:
    """Any reply kills the follow-up ladder instantly (Workflow 5.6)."""
    pending = (
        await db.execute(
            select(FollowUp).where(
                FollowUp.org_id == org_id,
                FollowUp.lead_id == thread.lead_id,
                FollowUp.status == FollowUpStatus.PENDING.value,
            )
        )
    ).scalars().all()
    for f in pending:
        if f.note and "nudge" in (f.note or "").lower():
            f.status = FollowUpStatus.SKIPPED.value
            f.completed_at = utcnow()
    reminders = (
        await db.execute(
            select(Reminder).where(
                Reminder.org_id == org_id,
                Reminder.target_type == "thread",
                Reminder.target_id == thread.id,
                Reminder.sent_at.is_(None),
                Reminder.cancelled_at.is_(None),
            )
        )
    ).scalars().all()
    for r in reminders:
        r.cancelled_at = utcnow()


# ─────────────────────────────────────────────────────────────────────────────
# The ingestion entry point (webhooks land here)
# ─────────────────────────────────────────────────────────────────────────────


async def ingest(
    db: AsyncSession,
    *,
    org_id: str,
    channel: str,
    from_address: str | None,
    to_address: str | None,
    body: str,
    subject: str | None = None,
    received_at: datetime | None = None,
) -> InboundMessage:
    """One message in. Match → understand → route. Nothing is ever dropped."""
    msg = InboundMessage(
        org_id=org_id,
        channel=channel,
        from_address=from_address,
        to_address=to_address,
        subject=subject,
        body=body,
        received_at=received_at or utcnow(),
        status=InboundStatus.NEW.value,
    )
    db.add(msg)
    await db.flush()

    contact = await _match_contact(db, org_id, channel, from_address)
    if contact is None:
        # Triage queue — a human sorts it; nothing is dropped.
        msg.status = InboundStatus.TRIAGE.value
        triage_owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if triage_owner is not None:
            await notify(
                db, org_id=org_id, user_id=triage_owner.id,
                title="Unmatched inbound message needs triage",
                body=f"From {from_address} ({channel}): {nlu.first_sentence(body)}",
                kind="escalation", entity_type="inbound_message", entity_id=msg.id,
            )
        await record_decision(
            db, org_id=org_id, decision_type=DecisionType.STATE_CHANGE.value,
            engine=ENGINE, decision="Sent to triage",
            reason=f"No contact matches sender {from_address}", needs_human=True,
            entity_type="inbound_message", entity_id=msg.id,
        )
        return msg

    msg.matched_contact_id = contact.id
    msg.matched_lead_id = contact.lead_id

    # Thread first: the conversation this reply continues.
    thread = (
        await db.execute(
            select(Thread)
            .where(
                Thread.org_id == org_id,
                Thread.contact_id == contact.id,
                Thread.channel == channel,
            )
            .order_by(Thread.last_message_at.desc().nullslast())
        )
    ).scalars().first()

    project: Project | None = None
    mentioned: list[Project] = []
    if thread is not None and thread.project_id:
        project = (
            await db.execute(select(Project).where(Project.id == thread.project_id))
        ).scalar_one_or_none()
        content_primary, mentioned = await _match_projects(
            db, org_id, contact.lead_id, body
        )
        if project is not None and mentioned:
            mentioned_ids = {p.id for p in mentioned}
            if len(mentioned) > 1:
                # The message spans several projects. A clear content winner
                # becomes the primary; a tie means we genuinely can't tell —
                # no primary, every mentioned timeline gets the message.
                project = content_primary
            elif project.id not in mentioned_ids:
                # Content clearly names a different project than the thread.
                project = mentioned[0]
    else:
        project, mentioned = await _match_projects(db, org_id, contact.lead_id, body)

    if thread is None:
        thread = await communication_engine.ensure_thread(
            db, org_id=org_id, lead_id=contact.lead_id, contact_id=contact.id,
            channel=channel, project_id=project.id if project else None,
            subject=subject,
        )
    thread.last_message_at = msg.received_at
    thread.last_direction = "inbound"
    if thread.status == ThreadStatus.DORMANT.value:
        thread.status = ThreadStatus.OPEN.value
        # A sleeping lead waking early (Workflow 28).
        lead = (
            await db.execute(select(Lead).where(Lead.id == contact.lead_id))
        ).scalar_one_or_none()
        if lead is not None and lead.state == "lost_for_now":
            await events.emit(
                db, org_id=org_id, event_type=EventType.LEAD_REVIVED.value,
                entity_type="lead", entity_id=lead.id,
                details={"reason": "client wrote back before the revival date"},
            )
            if lead.owner_id:
                await notify(
                    db, org_id=org_id, user_id=lead.owner_id,
                    title=f"{lead.name} came back early",
                    body=nlu.first_sentence(body), kind="general",
                    entity_type="lead", entity_id=lead.id,
                )

    msg.thread_id = thread.id
    msg.matched_project_id = project.id if project else None
    if len(mentioned) > 1:
        msg.related_project_ids = [p.id for p in mentioned]

    await _cancel_reply_watches(db, org_id, thread)

    # Understand.
    lead = (
        await db.execute(select(Lead).where(Lead.id == contact.lead_id))
    ).scalar_one_or_none()
    # "Client:" not "School:" — this string is fed to the model as context and
    # a domain word here leaks into its classification (finding F11 / F4).
    context = f"Client: {lead.name if lead else ''}. Project: {project.name if project else 'none'}."
    understanding = await nlu.classify_inbound(
        org_id=org_id, subject=subject, body=body, context=context
    )
    msg.intent = understanding["intent"]
    msg.change_type = understanding.get("change_type")
    msg.sentiment = understanding.get("sentiment")
    msg.ai_summary = understanding.get("summary")
    msg.extracted_points = understanding.get("extracted_points", [])

    await events.emit(
        db, org_id=org_id, event_type=EventType.REPLY_RECEIVED.value,
        project_id=project.id if project else None,
        entity_type="inbound_message", entity_id=msg.id,
        details={"intent": msg.intent, "sentiment": msg.sentiment,
                 "summary": msg.ai_summary or ""},
    )

    # Reusable facts → school intelligence.
    org = await get_org_settings(db, org_id)
    confidence = float(understanding.get("confidence", 0.5))
    if confidence < (org.ai_confidence_threshold or 0.6) and msg.intent not in (
        InboundIntent.COMPLAINT.value,
    ):
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = (
            f"Understanding confidence {confidence:.2f} below threshold"
        )
        owner = await get_user(db, org_id, (project.sales_owner_id if project else None) or (lead.owner_id if lead else None))
        if owner is None:
            owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Message from {contact.name} needs you",
                body=f"The AI understood too little to act: {msg.ai_summary}",
                kind="escalation", entity_type="inbound_message", entity_id=msg.id,
            )
        return msg

    # Route two-project messages that can't be split → both timelines + human.
    if project is None and len(mentioned) > 1:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Message spans several projects and can't be split"
        for p in mentioned:
            await events.emit(
                db, org_id=org_id, event_type=EventType.REPLY_RECEIVED.value,
                project_id=p.id, entity_type="inbound_message", entity_id=msg.id,
                details={"note": "message concerns multiple projects"}, react=False,
            )
        owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"{contact.name}'s message concerns several projects",
                body=msg.ai_summary or "", kind="escalation",
                entity_type="inbound_message", entity_id=msg.id,
            )
        return msg

    # People the message introduces ("our finance head Meena will handle
    # this") are synced onto the stakeholder map by the machine — humans
    # only edit the result, they never have to data-enter it.
    if project is not None and understanding.get("stakeholders"):
        from app.ai.planning import validate_stakeholder_specs
        from app.engines import planner_engine

        stakeholder_notes = await planner_engine.sync_stakeholder_specs(
            db, org_id=org_id, project=project,
            specs=validate_stakeholder_specs(understanding["stakeholders"]),
        )
        if stakeholder_notes:
            await record_decision(
                db, org_id=org_id, project_id=project.id,
                decision_type=DecisionType.PLAN_UPDATE.value, engine=ENGINE,
                decision="Stakeholder map updated from an inbound message",
                reason="; ".join(stakeholder_notes),
                confidence=confidence,
                entity_type="inbound_message", entity_id=msg.id,
            )

    # Per-intent routing. Money movement wins over the surface intent: a
    # "cheque is ready, collect Friday" reads as scheduling but IS payment
    # information — the extracted point carries the truth (Workflow 25).
    intent_for_routing = msg.intent
    if intent_for_routing in (
        InboundIntent.SCHEDULING.value, InboundIntent.ACKNOWLEDGEMENT.value,
    ) and any(
        p.get("type") == "payment_info" for p in (msg.extracted_points or [])
    ):
        intent_for_routing = InboundIntent.PAYMENT_INFO.value
    # Same principle for money negotiation: "can you do it in one lakh?"
    # reads as a question but IS a discount ask — the approval chain, never
    # the casual path, must own it.
    if intent_for_routing == InboundIntent.QUESTION.value and any(
        p.get("type") == "discount_request" for p in (msg.extracted_points or [])
    ):
        intent_for_routing = InboundIntent.CHANGE_REQUEST.value
    router = {
        InboundIntent.COMPLAINT.value: _route_complaint,
        InboundIntent.CHANGE_REQUEST.value: _route_change_request,
        InboundIntent.APPROVAL.value: _route_approval,
        InboundIntent.QUESTION.value: _route_question,
        InboundIntent.PAYMENT_INFO.value: _route_payment_info,
        InboundIntent.REJECTION.value: _route_rejection,
        InboundIntent.SCHEDULING.value: _route_scheduling,
        InboundIntent.ACKNOWLEDGEMENT.value: _route_acknowledgement,
    }.get(intent_for_routing)
    if router is None:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Intent could not be classified"
        owner = await get_user(db, org_id, project.sales_owner_id if project else None)
        if owner is None:
            owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Please read {contact.name}'s message yourself",
                body=body[:400], kind="escalation",
                entity_type="inbound_message", entity_id=msg.id,
            )
        return msg

    await router(db, org_id=org_id, msg=msg, contact=contact, lead=lead,
                 project=project, thread=thread)
    if msg.status == InboundStatus.NEW.value:
        msg.status = InboundStatus.PROCESSED.value
    return msg


# ─────────────────────────────────────────────────────────────────────────────
# Intent routers
# ─────────────────────────────────────────────────────────────────────────────


async def _stakeholder_for(
    db: AsyncSession, project: Project | None, contact: Contact
) -> Stakeholder | None:
    if project is None:
        return None
    return (
        await db.execute(
            select(Stakeholder).where(
                Stakeholder.project_id == project.id,
                Stakeholder.contact_id == contact.id,
            )
        )
    ).scalars().first()


async def raise_complaint_incident(
    db: AsyncSession,
    *,
    org_id: str,
    project: Project,
    description: str,
    source_type: str,
    source: str | None,
    complainant: str | None = None,
    client_name: str | None = None,
) -> Incident:
    """Raise the incident a complaint deserves, whatever channel it arrived by.

    F54: the whole of Workflow 22 — incident, severity, the COMPLAINT_RECEIVED
    health event and the dual-lead P1 escalation — lived inside
    `_route_complaint`, which has exactly one caller: the inbound intent router.
    So *"your trainer arrived 40 minutes late"*, said to a rep's face in a
    recorded meeting, produced a single task and nothing else — incidents stayed
    at 0 — while the identical words in an email paged both leads in seconds.

    Extracted rather than duplicated (the finding is explicit about this): the
    inbound path keeps its holding reply, which is inbound-shaped. A complaint
    made in the room does not get an automated "you'll hear from us within the
    hour" email — you are already standing there.
    """
    ops_lead = await find_role_user(db, org_id, Role.OPERATIONS_LEAD.value)
    sales_lead = await find_role_user(db, org_id, Role.SALES_LEAD.value)
    severity = (
        IncidentSeverity.HIGH.value
        if project.status == ProjectStatus.DELIVERY.value
        else IncidentSeverity.MEDIUM.value
    )
    incident = Incident(
        org_id=org_id, project_id=project.id,
        source_type=source_type, source=source,
        severity=severity,
        description=description,
        owner_user_id=ops_lead.id if ops_lead else None,
        status=IncidentStatus.OPEN.value,
    )
    db.add(incident)
    await db.flush()
    await events.emit(
        db, org_id=org_id, event_type=EventType.COMPLAINT_RECEIVED.value,
        project_id=project.id, entity_type="incident", entity_id=incident.id,
        details={"severity": severity, "summary": incident.description},
    )
    who = f" from {complainant}" if complainant else ""
    where = f" ({client_name})" if client_name else ""
    for leader in (ops_lead, sales_lead):
        if leader is not None:
            await notify(
                db, org_id=org_id, user_id=leader.id,
                title=f"P1 complaint{who}{where}",
                body=incident.description, kind="escalation",
                entity_type="incident", entity_id=incident.id,
            )
    return incident


async def _route_complaint(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """Complaints NEVER wait in a queue (Workflow 22)."""
    if project is None:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Complaint with no matching project"
        return
    incident = await raise_complaint_incident(
        db, org_id=org_id, project=project,
        description=msg.ai_summary or nlu.first_sentence(msg.body),
        source_type="inbound_message", source=msg.id,
        complainant=contact.name, client_name=lead.name if lead else None,
    )
    # Holding reply — drafted in seconds, never auto-sent.
    stakeholder = await _stakeholder_for(db, project, contact)
    await communication_engine.draft_client_message(
        db, org_id=org_id, kind=MessageKind.REPLY.value,
        purpose="complaint holding reply",
        lead_id=contact.lead_id, contact=contact, project=project,
        stakeholder=stakeholder,
        channel=msg.channel,
        subject=reply_subject(msg, project),
        instruction=(
            "We're very sorry — we are looking into this right now; "
            "you'll hear from us within the hour with the fix."
        ),
        facts={"issues_reported": [
            str(p.get("detail")) for p in (msg.extracted_points or [])
            if p.get("detail")
        ] or [incident.description]},
        triggered_by="inbound_reply",
        urgent=True,
        extracted_points=msg.extracted_points,
    )


async def _route_change_request(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """price → approval rules; content → revision task; date/scope → Planner
    feasibility (Workflows 4, 18, 20). Mixed asks run in parallel."""
    if project is None:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Change request with no matching project"
        owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Change request from {contact.name} — no project matched",
                body=msg.ai_summary or "", kind="escalation",
                entity_type="inbound_message", entity_id=msg.id,
            )
        return

    points = msg.extracted_points or []
    stakeholder = await _stakeholder_for(db, project, contact)
    handled_any = False

    # Price asks → the discount approval chain; the AI never negotiates money.
    price_points = [p for p in points if p.get("type") in ("discount_request", "price_question")]
    if price_points:
        handled_any = True
        from app.engines import approval_engine

        def _num(v: Any) -> float:
            # Schema asks for plain numbers, but not every provider enforces
            # schemas — never let a stray "1.26 lakh" crash the money path.
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        point = price_points[0]
        current = _num(point.get("from")) or float(project.value_estimate or 0)
        asked = _num(point.get("to"))
        discount_pct = round((current - asked) / current * 100, 1) if current and asked else 0.0
        await approval_engine.request_approval(
            db, org_id=org_id,
            entity_type=ApprovalEntityType.PRICE_CHANGE.value,
            entity_id=msg.id,
            project_id=project.id,
            facts={"discount_pct": discount_pct, "from": current, "to": asked},
            reason=(
                f"{contact.name} asks {current:,.0f} → {asked:,.0f} "
                f"(~{discount_pct:.0f}% discount) on {project.name}"
            ),
            default_approver_role=Role.SALES_LEAD.value,
        )
        await record_decision(
            db, org_id=org_id, project_id=project.id,
            decision_type=DecisionType.ESCALATION.value, engine=ENGINE,
            decision="Price ask routed to approval chain",
            reason=f"Discount of ~{discount_pct:.0f}% requested — money never takes the casual path",
            entity_type="inbound_message", entity_id=msg.id,
        )

    # Content asks → one revision task + immediate acknowledgement draft.
    # F31: `content_change` is the current routing name; `syllabus_change` is
    # still accepted so a model reply or stored point written against the older
    # vocabulary routes exactly as it did before.
    content_points = [
        p for p in points if p.get("type") in ("content_change", "syllabus_change")
    ]
    if content_points:
        handled_any = True
        change_text = "\n".join("- " + str(p.get("detail", "")) for p in content_points)
        # The skill that fits this revision is a judgement about the work,
        # not a constant: a syllabus fix needs curriculum design, a rack
        # layout fix needs something else entirely. LLM picks from the org
        # taxonomy; None routes without a skill and a human confirms.
        required_skill: str | None = "curriculum_design"  # stub-provider default
        if nlu.llm_available():
            from app.ai import planning

            try:
                required_skill = await planning.pick_skill(
                    org_id=org_id,
                    work=(
                        f"Revise this project's client-facing content/deliverable "
                        f"as asked: {change_text}"
                    ),
                    skills=await planning.org_skill_names(db, org_id),
                )
            except planning.PlanningUnavailable:
                required_skill = None
        task = ActionItem(
            org_id=org_id, lead_id=project.lead_id, project_id=project.id,
            title=f"Revise content per {contact.name}'s feedback",
            description=change_text,
            phase=Phase.PREPARATION.value,
            required_skill=required_skill,
            priority=TaskPriority.P1.value,
            due_date=utcnow() + timedelta(days=2),
            visible_to_client=True,
            source=TaskSource.CLIENT_REPLY.value,
            status=ActionItemStatus.OPEN.value,
            created_by="ai",
        )
        db.add(task)
        await db.flush()
        from app.engines import assignment_engine

        await assignment_engine.assign_task(
            db, org_id=org_id, task=task, notify_assignee=True
        )
        await events.emit(
            db, org_id=org_id, event_type=EventType.TASK_CREATED.value,
            project_id=project.id, entity_type="action_item", entity_id=task.id,
            details={"source": "client_reply", "points": len(content_points)},
        )
        await communication_engine.draft_client_message(
            db, org_id=org_id, kind=MessageKind.REPLY.value,
            purpose="acknowledge content change request",
            lead_id=contact.lead_id, contact=contact, project=project,
            stakeholder=stakeholder, channel=msg.channel,
            subject=reply_subject(msg, project),
            instruction="On it — the revised version will reach you within two days.",
            facts={"changes_requested": [str(p.get("detail")) for p in content_points]},
            triggered_by="inbound_reply",
            extracted_points=content_points,
        )

    # Date asks → feasibility BEFORE any promise, then a bundled re-plan +
    # confirmation email that succeed or fail together (Workflow 18).
    date_points = [p for p in points if p.get("type") == "date_change"]
    if date_points and project is not None:
        handled_any = True
        await _handle_date_change(
            db, org_id=org_id, msg=msg, contact=contact, project=project,
            stakeholder=stakeholder, point=date_points[0],
        )

    # Scope asks → amendment machinery (Workflow 20).
    scope_points = [p for p in points if p.get("type") == "scope_change"]
    if scope_points:
        handled_any = True
        await _handle_scope_change(
            db, org_id=org_id, msg=msg, contact=contact, project=project,
            stakeholder=stakeholder, point=scope_points[0],
        )

    if not handled_any:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Change request understood but no concrete ask extracted"
        owner = await get_user(db, org_id, project.sales_owner_id)
        if owner is None:
            owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Change request from {contact.name} needs a human read",
                body=msg.body[:400], kind="escalation",
                entity_type="inbound_message", entity_id=msg.id,
            )


async def _handle_date_change(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    project: Project, stakeholder: Stakeholder | None, point: dict[str, Any],
) -> None:
    from app.engines import planner_engine

    # Supersede an open draft re-plan on the same topic (Workflow 18 twist).
    open_drafts = (
        await db.execute(
            select(ActionPlan).where(
                ActionPlan.project_id == project.id,
                ActionPlan.status.in_(
                    [PlanStatus.DRAFT.value, PlanStatus.PENDING_REVIEW.value]
                ),
                ActionPlan.trigger == "client_reply",
            )
        )
    ).scalars().all()
    for d in open_drafts:
        # F49: this used to set `status = superseded` and stop — leaving the
        # plan's pending approval live and tappable. Worse, flipping the status
        # here made the planner's own careful sweep skip the plan forever (that
        # sweep only looks at DRAFT/PENDING_REVIEW), so the orphan could never be
        # cleaned up later. Approving one rolled the project back over a merge.
        # Both paths now share one retirement routine so they cannot drift again.
        await planner_engine.retire_superseded_plan(
            db, org_id=org_id, project=project, old=d,
            replaced_by_label="a newer client instruction",
            decision_reason=(
                "A newer message changed the same dates again — nothing half-applies"
            ),
        )

    dates = [datetime.fromisoformat(d) for d in point.get("dates", [])]
    if not dates:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Date change requested but no concrete date parsed"
        return
    new_start = min(dates)
    duration = 1
    if project.start_date and project.target_end_date:
        duration = (project.target_end_date - project.start_date).days + 1
    new_end = new_start + timedelta(days=duration - 1)

    # Immediate acknowledgement so the school is never left hanging.
    await communication_engine.draft_client_message(
        db, org_id=org_id, kind=MessageKind.REPLY.value,
        purpose="acknowledge date change request",
        lead_id=contact.lead_id, contact=contact, project=project,
        stakeholder=stakeholder, channel=msg.channel,
        subject=reply_subject(msg, project),
        instruction="Got it — checking feasibility; we'll confirm by end of day.",
        facts={"requested_start": f"{new_start:%d %b %Y}"},
        triggered_by="inbound_reply",
    )

    feasibility = await planner_engine.feasibility_pass(
        db, org_id=org_id, project=project, date_from=new_start, date_to=new_end
    )
    if not feasibility["feasible"]:
        # Options, not a plan — the AI never says yes before feasibility does.
        owner = await get_user(db, org_id, project.sales_owner_id)
        if owner is None:
            owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Date change from {contact.name} is NOT feasible as asked",
                body=(
                    f"Requested {new_start:%d %b}–{new_end:%d %b}: {feasibility['detail']}.\n"
                    "Options: (a) offer the next free window, (b) swap the booked "
                    "person, (c) split the delivery. Pick one and the reply will be drafted."
                ),
                kind="escalation", entity_type="inbound_message", entity_id=msg.id,
            )
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = f"Not feasible: {feasibility['detail']}"
        return

    # Feasible → one re-plan; every open dated task shifts by the same delta.
    pending_ops: list[dict[str, Any]] = []
    delta = None
    if project.start_date:
        delta = new_start - project.start_date
    open_tasks = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.status.in_(
                    [ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value]
                ),
                ActionItem.due_date.is_not(None),
            )
        )
    ).scalars().all()
    moved = 0
    for t in open_tasks:
        if delta is not None and t.phase in ("delivery", "preparation"):
            pending_ops.append(
                {
                    "op": "redate", "task_id": t.id,
                    "old_due": t.due_date.isoformat(),
                    "new_due": (t.due_date + delta).isoformat(),
                }
            )
            moved += 1
    # NOTHING is applied yet — the window move and the commitment
    # renegotiations ride as pending ops and land only when the plan
    # version activates (one transaction; nothing half-applies).
    pending_ops.append(
        {
            "op": "set_window",
            "start": new_start.isoformat(),
            "end": new_end.isoformat() if new_end else None,
        }
    )

    # Commitments renegotiate (not broken — both sides agreed) at activation.
    commitments = (
        await db.execute(
            select(ClientCommitment).where(
                ClientCommitment.project_id == project.id,
                ClientCommitment.status == CommitmentStatus.OPEN.value,
                ClientCommitment.due_date.is_not(None),
            )
        )
    ).scalars().all()
    renegotiated = 0
    for c in commitments:
        if delta is not None and c.due_date >= utcnow():
            pending_ops.append(
                {
                    "op": "renegotiate_commitment",
                    "commitment_id": c.id,
                    "new_due": (c.due_date + delta).isoformat(),
                }
            )
            renegotiated += 1

    # Draft the confirmation and bundle it with the plan approval —
    # one yes covers both; they succeed or fail together.
    confirm_msg, _appr, _unc = await communication_engine.draft_client_message(
        db, org_id=org_id, kind=MessageKind.REPLY.value,
        purpose="confirm feasible date change",
        lead_id=contact.lead_id, contact=contact, project=project,
        stakeholder=stakeholder, channel=msg.channel,
        subject=reply_subject(msg, project),
        instruction=(
            f"The new window {new_start:%d %b}–{new_end:%d %b} works on our side — "
            "please confirm any dependent events that move with it."
        ),
        facts={
            "confirmed_window": f"{new_start:%d %b} – {new_end:%d %b}",
            "notes": [f"{moved} internal dates move with it"],
        },
        triggered_by="inbound_reply",
        request_approval=False,  # rides on the plan approval as a bundle
    )
    delta_days = abs(delta.days) if delta is not None else 0
    plan, approval = await planner_engine.create_plan_version(
        db, org_id=org_id, project=project,
        trigger="client_reply", trigger_ref=msg.id,
        summary=f"Date shift to {new_start:%d %b} requested by {contact.name}",
        changes=[
            f"{moved} task(s) re-dated by {delta_days} day(s)",
            f"{renegotiated} commitment(s) renegotiated",
            "Confirmation email rides on this approval",
        ],
        new_tasks=[],
        pending_ops=pending_ops,
        approval_facts={
            "date_shift_days": delta_days,
            "delivery_dates_moved": True,
            "bundled_entities": (
                [{"entity_type": "outbound_message", "entity_id": confirm_msg.id}]
                if confirm_msg else None
            ),
        },
    )
    msg.linked_plan_version = plan.version
    if approval is None and confirm_msg is not None:
        # The plan was small enough to auto-activate, but a client-facing
        # message still always needs its own human yes.
        from app.engines import approval_engine

        await approval_engine.request_approval(
            db, org_id=org_id,
            entity_type=ApprovalEntityType.OUTBOUND_MESSAGE.value,
            entity_id=confirm_msg.id, project_id=project.id,
            facts={"kind": confirm_msg.kind, "channel": confirm_msg.channel},
            reason=f"Confirmation of the {new_start:%d %b} date change",
            default_approver_role=Role.SALES_LEAD.value,
        )


async def _handle_scope_change(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    project: Project | None, stakeholder: Stakeholder | None, point: dict[str, Any],
) -> None:
    if project is None:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        return
    from app.engines import document_engine, planner_engine

    org = await get_org_settings(db, org_id)
    direction = point.get("direction", "grow")
    # F31: `quantity_delta` is the current key; `students_delta` is still read so
    # a model reply (or a stored point) written against the older vocabulary keeps
    # working. Accepting both is what makes the rename safe to ship.
    quantity_delta = int(point.get("quantity_delta") or point.get("students_delta") or 0)

    if direction == "shrink":
        owner = await get_user(db, org_id, project.sales_owner_id)
        if owner is None:
            owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Scope reduction asked by {contact.name}",
                body=(
                    f"{point.get('detail', '')} — negative amendment and task "
                    "cancellations will follow your confirmation; sunk costs shown honestly."
                ),
                kind="escalation", entity_type="inbound_message", entity_id=msg.id,
            )
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Scope shrink — human confirms the negative amendment"
        return

    # Growth: delta priced strictly from the locked pricing version.
    base = await document_engine.accepted_proposal(db, org_id=org_id, project_id=project.id)
    amendment = None
    if base is not None and quantity_delta:
        # The locked per-unit rate: whatever this proposal prices per head /
        # per seat / per rack — the first "per …" line item, not a domain word.
        base_item = None
        for item in base.line_items or []:
            unit = str(item.get("unit") or item.get("code") or "").lower()
            if unit.startswith("per"):
                base_item = item
                break
        if base_item is None:
            # No line says "per …" — fall back to the first priced line rather
            # than to a domain word. Strictly wider than the old
            # `"student" in unit` test, so this can only match more.
            base_item = next(
                (i for i in base.line_items or [] if float(i.get("unit_price") or 0)), None
            )
        unit_price = float(base_item.get("unit_price", 0)) if base_item else 0.0
        if unit_price:
            # F31: the amendment is CLIENT-VISIBLE, so it must speak the client's
            # own pricing vocabulary. Carry the base proposal's own code and unit
            # rather than restating them — the rate was looked up generically and
            # the write has to be generic too, or a logistics client reads
            # "per student" on their own amendment.
            amendment = await document_engine.build_amendment(
                db, org_id=org_id, project=project, base_proposal=base,
                delta_line_items=[{
                    "code": base_item.get("code") or "scope_addition",
                    "label": "Scope addition",
                    "unit": base_item.get("unit") or "",
                    "unit_price": unit_price,
                    "quantity": quantity_delta,
                    "line_total": unit_price * quantity_delta,
                }],
                reason=point.get("detail", "scope expansion"),
                created_by=project.sales_owner_id or "ai",
                special_price_approval_id=base.special_price_approval_id,
            )

    blocked_reason = (
        "awaiting amendment confirmation"
        if org.scope_change_requires_confirmation else None
    )
    if nlu.llm_available():
        # Production: the expansion's work is derived from THIS project's
        # objective — any topic, no template. Money stays deterministic:
        # the amendment above priced from the locked proposal.
        from app.ai import planning

        try:
            specs, gaps = await planning.generate_scope_wave(
                db, org_id=org_id, project=project,
                change_detail=point.get("detail", "") or msg.ai_summary or "",
            )
        except planning.PlanningUnavailable:
            specs, gaps = [], []  # the plan version still records the ask
        if gaps:
            await planner_engine._record_skill_gaps(
                db, org_id=org_id, project_id=project.id, gaps=gaps
            )
        new_tasks = [
            {
                "title": s["title"], "description": s.get("description"),
                "phase": s["phase"], "required_skill": s.get("required_skill"),
                "due_in_days": s.get("due_in_days", 5),
                "priority": s.get("priority"),
                "visible_to_client": s.get("visible_to_client", False),
                "source": TaskSource.CLIENT_REPLY.value,
                "blocked_reason": blocked_reason,
            }
            for s in specs
        ]
    else:
        # Stub-provider template (deterministic test suites only).
        new_tasks = [
            {
                "title": f"Extend content for scope addition ({point.get('detail', '')[:80]})",
                "phase": Phase.PREPARATION.value, "required_skill": "curriculum_design",
                "due_in_days": 5, "visible_to_client": True,
                "source": TaskSource.CLIENT_REPLY.value, "blocked_reason": blocked_reason,
            },
            {
                "title": f"Order additional kits (+{quantity_delta or 'TBD'})",
                "phase": Phase.PREPARATION.value, "required_skill": "logistics",
                "due_in_days": 6, "visible_to_client": False,
                "source": TaskSource.CLIENT_REPLY.value, "blocked_reason": blocked_reason,
            },
            {
                "title": "Recompute batch schedule for expanded scope",
                "phase": Phase.PREPARATION.value, "required_skill": "scheduling",
                "due_in_days": 4, "visible_to_client": False,
                "source": TaskSource.CLIENT_REPLY.value, "blocked_reason": blocked_reason,
            },
            {
                "title": "Amend invoice for confirmed scope addition",
                "phase": Phase.PAYMENT.value, "required_skill": "invoicing",
                "due_in_days": 7, "visible_to_client": False,
                "source": TaskSource.CLIENT_REPLY.value, "blocked_reason": blocked_reason,
            },
        ]
    plan, approval = await planner_engine.create_plan_version(
        db, org_id=org_id, project=project,
        trigger="client_reply", trigger_ref=msg.id,
        summary=f"Scope expansion asked by {contact.name}: {point.get('detail', '')[:100]}",
        changes=[
            f"{len(new_tasks)} scope-expansion task(s)"
            + (" created blocked until the amendment is confirmed" if blocked_reason else "")
            + ("" if new_tasks else
               " — AI unavailable; the reviewer adds the expansion tasks"),
            f"Amendment prepared: {amendment.total_amount:,.0f} addition" if amendment else
            "No amendment computed (no accepted proposal or per-unit rate)",
        ],
        new_tasks=new_tasks,
        approval_facts={"scope_change": True, "tasks_added": len(new_tasks)},
    )
    msg.linked_plan_version = plan.version
    # Reply with the amendment rides on approval of the plan.
    await communication_engine.draft_client_message(
        db, org_id=org_id, kind=MessageKind.REPLY.value,
        purpose="scope expansion amendment",
        lead_id=contact.lead_id, contact=contact, project=project,
        stakeholder=stakeholder, channel=msg.channel,
        subject=reply_subject(msg, project),
        instruction=(
            "Wonderful news — here's the addition; one confirmation and we fold it in."
        ),
        facts=(
            {"amendment_total": f"{amendment.total_amount:,.0f}",
             "new_project_total": f"{(await document_engine.accepted_total(db, org_id=org_id, project_id=project.id))[0] + amendment.total_amount:,.0f}"}
            if amendment else {"note": "commercials to follow"}
        ),
        triggered_by="inbound_reply",
    )


async def _route_approval(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """The school said yes. To what? Proposal → deal agreed; a blocked task
    waiting on school approval → unblocked (Workflows 4, 11)."""
    if project is None:
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "A yes arrived but no project matches"
        return

    # 1) Blocked tasks waiting on the school.
    blocked = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.project_id == project.id,
                ActionItem.blocked.is_(True),
            )
        )
    ).scalars().all()
    school_blocked = [
        t for t in blocked
        if "school" in (t.blocked_reason or "").lower()
        or "approval" in (t.blocked_reason or "").lower()
        or "amendment" in (t.blocked_reason or "").lower()
        or "confirmation" in (t.blocked_reason or "").lower()
    ]
    amendment_confirmed = any(
        "amendment" in (t.blocked_reason or "").lower() for t in school_blocked
    )
    for t in school_blocked:
        t.blocked = False
        t.blocked_reason = None
        await events.emit(
            db, org_id=org_id, event_type=EventType.TASK_UNBLOCKED.value,
            project_id=project.id, entity_type="action_item", entity_id=t.id,
            details={"by": "client approval", "inbound_message": msg.id},
        )

    # 1b) A yes on scope tasks blocked for the amendment confirms the
    # amendment itself: value grows, the invoice math changes (Workflow 20.6).
    if amendment_confirmed:
        amendment = (
            await db.execute(
                select(Proposal)
                .where(
                    Proposal.org_id == org_id,
                    Proposal.project_id == project.id,
                    Proposal.amends_proposal_id.is_not(None),
                    Proposal.status.in_(
                        [ProposalStatus.DRAFT.value, ProposalStatus.SENT.value,
                         ProposalStatus.APPROVED_INTERNALLY.value]
                    ),
                )
                .order_by(Proposal.created_at.desc())
            )
        ).scalars().first()
        if amendment is not None:
            amendment.status = ProposalStatus.ACCEPTED.value
            project.value_estimate = (project.value_estimate or 0) + amendment.total_amount

    # 2) A sent proposal on this project → accepted; deal agreed.
    proposal = (
        await db.execute(
            select(Proposal)
            .where(
                Proposal.org_id == org_id,
                Proposal.project_id == project.id,
                Proposal.status == ProposalStatus.SENT.value,
            )
            .order_by(Proposal.created_at.desc())
        )
    ).scalars().first()
    if proposal is not None and not school_blocked:
        proposal.status = ProposalStatus.ACCEPTED.value
        if proposal.amends_proposal_id is None:
            project.status = ProjectStatus.AGREED.value
            await events.emit(
                db, org_id=org_id, event_type=EventType.DEAL_AGREED.value,
                project_id=project.id, entity_type="proposal", entity_id=proposal.id,
                details={"total": proposal.total_amount},
            )
        else:
            # Amendment confirmed → value grows; blocked scope tasks unblock
            # via the school-blocked sweep above on the next yes.
            project.value_estimate = (project.value_estimate or 0) + proposal.total_amount
    if school_blocked and not proposal:
        # commitments the school owed us are now kept
        commitments = (
            await db.execute(
                select(ClientCommitment).where(
                    ClientCommitment.project_id == project.id,
                    ClientCommitment.direction == "theirs",
                    ClientCommitment.status == CommitmentStatus.OPEN.value,
                )
            )
        ).scalars().all()
        for c in commitments:
            c.status = CommitmentStatus.KEPT.value
            await events.emit(
                db, org_id=org_id, event_type=EventType.COMMITMENT_KEPT.value,
                project_id=project.id, entity_type="client_commitment", entity_id=c.id,
                react=False,
            )


async def _route_question(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """Answered from what we know — program definition, deliverables,
    intelligence — never guessed (Workflow 19)."""
    knowledge: list[str] = []
    question_text = " ".join(
        str(p.get("detail", "")) for p in (msg.extracted_points or [])
    ) or msg.body
    q_words = {w.strip("?,.").lower() for w in question_text.split() if len(w) > 3}

    # Commercial topics take the money path, never the casual path. In
    # production the LLM's extracted point types carry that judgement;
    # the word sniff only serves the stub provider.
    point_types = {str(p.get("type")) for p in (msg.extracted_points or [])}
    commercial = bool(point_types & {"price_question", "discount_request", "payment_info"})
    if not nlu.llm_available():
        commercial = commercial or any(
            w in question_text.lower()
            for w in ("pay", "instalment", "installment", "price", "discount", "invoice")
        )
    if commercial:
        owner = (
            await get_user(db, org_id, project.sales_owner_id if project else None)
            or await find_role_user(db, org_id, Role.SALES_LEAD.value)
        )
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Commercial question from {contact.name}",
                body=question_text[:300], kind="approval_waiting",
                entity_type="inbound_message", entity_id=msg.id,
            )
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "Commercial topic — approval rules override the casual path"
        return

    # Gather EVERYTHING we hold that could answer — unfiltered. Which facts
    # actually answer this question is a judgement, made below.
    candidates: list[str] = []
    stub_match: list[tuple[str, int]] = []  # (full source text, overlap needed)
    if project is not None and project.program_id:
        from app.models.program import Program

        program = (
            await db.execute(select(Program).where(Program.id == project.program_id))
        ).scalar_one_or_none()
        if program is not None and program.description:
            candidates.append(f"Program: {program.description}")
            stub_match.append((program.description, 1))
    if project is not None:
        from app.models.finance import Deliverable

        deliverables = (
            await db.execute(
                select(Deliverable)
                .where(Deliverable.project_id == project.id)
                .order_by(Deliverable.version.desc())
            )
        ).scalars().all()
        seen_types = set()
        for d in deliverables:
            if d.type in seen_types or not d.content_md:
                continue
            seen_types.add(d.type)
            candidates.append(f"{d.type} v{d.version}: {nlu.first_sentence(d.content_md, 200)}")
            stub_match.append((d.content_md, 2))
    if lead is not None:
        intel = (
            await db.execute(
                select(ClientIntelligence).where(ClientIntelligence.lead_id == lead.id)
            )
        ).scalars().all()
        for i in intel:
            candidates.append(f"Known: {i.note}")
            stub_match.append((i.note, 2))

    if nlu.llm_available():
        # Production: the model judges — by meaning, not shared words — which
        # facts genuinely answer this question and whether they suffice. The
        # fence stays deterministic: answers compose ONLY from picked facts,
        # insufficient (or model down) goes to a human.
        from app.ai import planning

        try:
            verdict = await planning.select_answer_facts(
                org_id=org_id, question=question_text, facts=candidates
            )
        except planning.PlanningUnavailable:
            verdict = {"sufficient": False, "fact_indexes": []}
        if verdict["sufficient"]:
            knowledge = [candidates[i] for i in verdict["fact_indexes"]]
    else:
        # Stub-provider path: the deterministic word-overlap ranking.
        for fact, (source, needed) in zip(candidates, stub_match):
            s_words = {w.lower() for w in source.split()}
            if len(q_words & s_words) >= needed:
                knowledge.append(fact)

    if not knowledge:
        # No guessing — a named human answers, told exactly why the AI stopped.
        owner = (
            await get_user(db, org_id, project.sales_owner_id if project else None)
            or (await get_user(db, org_id, lead.owner_id) if lead else None)
            or await find_role_user(db, org_id, Role.SALES_LEAD.value)
        )
        task = ActionItem(
            org_id=org_id, lead_id=contact.lead_id,
            project_id=project.id if project else None,
            title=f"Answer {contact.name}'s question: {nlu.first_sentence(question_text, 80)}",
            description=f"The AI found no data to answer this. Question: {question_text}",
            phase=Phase.SALES.value, priority=TaskPriority.P2.value,
            due_date=utcnow() + timedelta(days=2),
            assignee_id=owner.id if owner else None,
            assigned_by="ai",
            assignment_reason="Question owner — no data available for an AI answer",
            source=TaskSource.CLIENT_REPLY.value,
            status=ActionItemStatus.OPEN.value, created_by="ai",
        )
        db.add(task)
        msg.status = InboundStatus.NEEDS_HUMAN.value
        msg.needs_human_reason = "No data found to answer — the AI never guesses"
        if owner is not None:
            await notify(
                db, org_id=org_id, user_id=owner.id,
                title=f"Question from {contact.name} needs your knowledge",
                body=question_text[:300], kind="task_assigned",
                entity_type="action_item", entity_id=task.id,
            )
        return

    stakeholder = await _stakeholder_for(db, project, contact)
    await communication_engine.draft_client_message(
        db, org_id=org_id, kind=MessageKind.REPLY.value,
        purpose="answer a question from our own data",
        lead_id=contact.lead_id, contact=contact, project=project,
        stakeholder=stakeholder, channel=msg.channel,
        subject=reply_subject(msg, project),
        instruction="Answer using only these facts; offer to walk them through the details.",
        facts={"question": nlu.first_sentence(question_text, 160), "facts": knowledge},
        triggered_by="inbound_reply",
        extracted_points=msg.extracted_points,
    )
    # Reusable fact for the future.
    if lead is not None:
        db.add(
            ClientIntelligence(
                org_id=org_id, lead_id=lead.id,
                note=f"Asked: {nlu.first_sentence(question_text, 120)}",
                category="preferences", source="system", added_by="ai",
            )
        )


async def _route_payment_info(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """'Cheque ready, collect Friday' → a collection task + the ladder pauses
    (Workflow 25)."""
    owner = (
        await get_user(db, org_id, lead.owner_id if lead else None)
        or await find_role_user(db, org_id, Role.SALES_AGENT.value)
        or await find_role_user(db, org_id, Role.SALES_LEAD.value)
    )
    task = ActionItem(
        org_id=org_id, lead_id=contact.lead_id,
        project_id=project.id if project else None,
        title=f"Collect payment from {lead.name if lead else contact.name}: "
        f"{nlu.first_sentence(msg.body, 80)}",
        phase=Phase.PAYMENT.value, priority=TaskPriority.P2.value,
        due_date=utcnow() + timedelta(days=3),
        assignee_id=owner.id if owner else None,
        assigned_by="ai", assignment_reason="Relationship owner is closest to collect",
        source=TaskSource.CLIENT_REPLY.value,
        status=ActionItemStatus.OPEN.value, created_by="ai",
    )
    db.add(task)
    await db.flush()
    # Pause the payment ladder: cancel unsent invoice reminders on this project.
    if project is not None:
        from app.models.finance import Invoice

        invoice_ids = (
            await db.execute(
                select(Invoice.id).where(Invoice.project_id == project.id)
            )
        ).scalars().all()
        if invoice_ids:
            reminders = (
                await db.execute(
                    select(Reminder).where(
                        Reminder.org_id == org_id,
                        Reminder.target_type == "invoice",
                        Reminder.target_id.in_(invoice_ids),
                        Reminder.sent_at.is_(None),
                        Reminder.cancelled_at.is_(None),
                    )
                )
            ).scalars().all()
            for r in reminders:
                r.cancelled_at = utcnow()
    if owner is not None:
        await notify(
            db, org_id=org_id, user_id=owner.id,
            title=f"Payment info from {contact.name}",
            body=msg.body[:300], kind="task_assigned",
            entity_type="action_item", entity_id=task.id,
        )


async def _route_rejection(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """Disputes and rejections → needs_human immediately, P1, with the paper
    trail assembled (Workflow 25 dispute)."""
    owner = (
        await get_user(db, org_id, project.sales_owner_id if project else None)
        or await find_role_user(db, org_id, Role.SALES_LEAD.value)
    )
    trail: list[str] = []
    if project is not None:
        proposals = (
            await db.execute(
                select(Proposal).where(Proposal.project_id == project.id)
            )
        ).scalars().all()
        for p in proposals:
            trail.append(
                f"{p.title}: {p.status}, total {p.total_amount:,.0f}"
                + (f", sent {p.sent_at:%d %b}" if p.sent_at else "")
            )
    task = ActionItem(
        org_id=org_id, lead_id=contact.lead_id,
        project_id=project.id if project else None,
        title=f"Dispute/rejection from {contact.name} — read and decide",
        description=(
            f"Message: {msg.body[:400]}\n\nPaper trail:\n"
            + "\n".join("- " + t for t in trail)
        ),
        phase=Phase.SALES.value, priority=TaskPriority.P1.value,
        due_date=utcnow() + timedelta(days=1),
        assignee_id=owner.id if owner else None,
        assigned_by="ai",
        assignment_reason="Relationship owner handles disputes — paper trails win disputes",
        source=TaskSource.CLIENT_REPLY.value,
        status=ActionItemStatus.OPEN.value, created_by="ai",
    )
    db.add(task)
    msg.status = InboundStatus.NEEDS_HUMAN.value
    msg.needs_human_reason = "Rejection/dispute — instant human escalation"

    # A dispute over money flips the open invoice to `disputed` (Data Model
    # §6.8) and pauses its reminder ladder — chasing a disputed bill is worse
    # than silence.
    body_l = (msg.body or "").lower()
    if project is not None and any(
        w in body_l for w in ("invoice", "amount", "bill", "payment", "price", "dispute")
    ):
        from app.models.finance import Invoice

        open_invoices = (
            await db.execute(
                select(Invoice).where(
                    Invoice.org_id == org_id,
                    Invoice.project_id == project.id,
                    Invoice.status.in_(
                        [InvoiceStatus.SENT.value, InvoiceStatus.OVERDUE.value,
                         InvoiceStatus.PART_PAID.value]
                    ),
                )
            )
        ).scalars().all()
        for inv in open_invoices:
            inv.status = InvoiceStatus.DISPUTED.value
            pending_reminders = (
                await db.execute(
                    select(Reminder).where(
                        Reminder.org_id == org_id,
                        Reminder.target_type == "invoice",
                        Reminder.target_id == inv.id,
                        Reminder.sent_at.is_(None),
                        Reminder.cancelled_at.is_(None),
                    )
                )
            ).scalars().all()
            for rem in pending_reminders:
                rem.cancelled_at = utcnow()

    if owner is not None:
        await notify(
            db, org_id=org_id, user_id=owner.id,
            title=f"P1: dispute or rejection from {contact.name}",
            body=msg.ai_summary or "", kind="escalation",
            entity_type="action_item", entity_id=task.id,
        )


async def _route_scheduling(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    owner = (
        await get_user(db, org_id, lead.owner_id if lead else None)
        or await find_role_user(db, org_id, Role.SALES_LEAD.value)
    )
    dates = [p for p in (msg.extracted_points or []) if p.get("type") == "date_change"]
    task = ActionItem(
        org_id=org_id, lead_id=contact.lead_id,
        project_id=project.id if project else None,
        title=f"Book meeting asked by {contact.name}"
        + (f" ({dates[0]['dates'][0]})" if dates and dates[0].get("dates") else ""),
        description=msg.body[:400],
        phase=Phase.SALES.value, priority=TaskPriority.P2.value,
        due_date=utcnow() + timedelta(days=1),
        assignee_id=owner.id if owner else None,
        assigned_by="ai", assignment_reason="Relationship owner books client meetings",
        source=TaskSource.CLIENT_REPLY.value,
        status=ActionItemStatus.OPEN.value, created_by="ai",
    )
    db.add(task)
    if owner is not None:
        await notify(
            db, org_id=org_id, user_id=owner.id,
            title=f"Meeting request from {contact.name}",
            body=msg.body[:200], kind="task_assigned",
            entity_type="action_item", entity_id=task.id,
        )


async def _route_acknowledgement(
    db: AsyncSession, *, org_id: str, msg: InboundMessage, contact: Contact,
    lead: Lead | None, project: Project | None, thread: Thread,
) -> None:
    """Nothing to do but log it and mark the thread settled (Workflow 18.6)."""
    thread.status = ThreadStatus.SETTLED.value
