# app/services/client_dossier.py
"""Everything the model is told about one client, assembled once (D7).

Measured on the busiest real client in the database: a genuinely complete
dossier is about 47,525 characters, roughly 11,900 tokens. With the document
(under 5,600) and the instructions (about 1,000) the first pass is around
18,500 tokens against a window of a million.

**So nothing here is summarised, sampled or capped.** The first draft of D7
capped meetings at five and notes at ten; that was solving a problem which does
not exist, and it would have hidden from the model exactly the sentences it
needs -- the note that says when the programme runs, the transcript line where
someone said which fortnight in September avoids the exam block. On the
measured client the transcripts alone are the single richest source.

**Two tables are excluded deliberately, on quality grounds rather than size.**
`ai_decisions` is the engine's own past reasoning, and feeding a model its
earlier guesses invites it to treat them as established fact. `progress_events`
is state-machine bookkeeping: volume without meaning for this task. Together
they were 15,570 of the measured 47,525 characters, so removing them makes the
dossier better and smaller at once.

**Fields are listed explicitly, never derived from the table.** A user row
carries a password hash and an encrypted SMTP password, and a memory chunk
carries an embedding vector; none of them belongs in a prompt, and a blocklist
is one forgotten column away from leaking one.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import OrgContext
from app.core.exceptions import NotFoundError
from app.models.action_item import ActionItem
from app.models.comms import Thread
from app.models.demo import Demo
from app.models.finance import Deliverable, Invoice
from app.models.followup import FollowUp
from app.models.lead import (
    ClientIntelligence,
    ConsentRecord,
    Contact,
    Lead,
    LeadStateHistory,
)
from app.models.meeting import Meeting, Transcript
from app.models.memory import MemoryChunk
from app.models.messaging import OutboundMessage
from app.models.organisation import Organisation
from app.models.program import PricingTable, Program
from app.models.project import ActionPlan, ClientCommitment, Project, Stakeholder
from app.models.proposal import Proposal, ProposalRevision
from app.models.user import User

#: A safety valve, not a budget. About 15k tokens, roughly 25% above the
#: busiest client measured today. A client with fifty meetings will exceed it
#: eventually; until then it never binds.
DOSSIER_CHAR_CEILING = 60_000

#: Left out on quality grounds. See the module docstring.
EXCLUDED = ("ai_decisions", "progress_events")

#: Sections the ceiling may trim, oldest-first. `client`, `programme`,
#: `rate_card`, `sender` and `organisation` are never trimmed: they are one
#: record each and they are what the whole fill is grounded in.
TRIMMABLE = (
    "state_history", "contacts", "notes", "meetings", "plans", "commitments",
    "stakeholders", "deliverables", "invoices", "action_items", "followups",
    "demos", "proposals", "threads", "messages", "consent", "memory",
)


async def build(
    db: AsyncSession, ctx: OrgContext, lead_id: str, program_id: str
) -> dict[str, Any]:
    """The whole client, the whole programme, and who is sending it.

    Assembled once per fill session and replayed verbatim on every later turn,
    so the answer to turn 7 is grounded in the same facts as turn 1.
    """
    lead = await _one(db, select(Lead).where(
        Lead.id == lead_id, Lead.org_id == ctx.org_id))
    if lead is None:
        raise NotFoundError("Client not found")

    project = await _one(db, select(Project).where(
        Project.org_id == ctx.org_id, Project.lead_id == lead_id
    ).order_by(Project.created_at.desc()))
    project_id = project.id if project else None

    meetings = await _rows(db, select(Meeting).where(
        Meeting.org_id == ctx.org_id, Meeting.lead_id == lead_id
    ).order_by(Meeting.created_at))
    transcripts = await _rows(db, select(Transcript).where(
        Transcript.org_id == ctx.org_id,
        Transcript.meeting_id.in_([m.id for m in meetings] or [""]),
    ))
    by_meeting = {t.meeting_id: t for t in transcripts}

    proposals = await _rows(db, select(Proposal).where(
        Proposal.org_id == ctx.org_id, Proposal.lead_id == lead_id
    ).order_by(Proposal.created_at))
    revisions = await _rows(db, select(ProposalRevision).where(
        ProposalRevision.org_id == ctx.org_id,
        ProposalRevision.proposal_id.in_([p.id for p in proposals] or [""]),
    ).order_by(ProposalRevision.revision_no))
    by_proposal: dict[str, list] = {}
    for revision in revisions:
        by_proposal.setdefault(revision.proposal_id, []).append(revision)

    programme = await _one(db, select(Program).where(
        Program.id == program_id, Program.org_id == ctx.org_id))
    rate_card = await _one(db, select(PricingTable).where(
        PricingTable.org_id == ctx.org_id,
        PricingTable.program_id == program_id,
        PricingTable.is_current.is_(True),
    ))
    sender = await _one(db, select(User).where(User.id == ctx.user_id))
    org = await _one(db, select(Organisation).where(Organisation.id == ctx.org_id))

    dossier: dict[str, Any] = {
        "client": {
            "name": lead.name, "state": lead.state, "city": lead.city,
            "region": lead.region, "address": lead.address,
            "website": lead.website, "source": lead.source,
            "important": lead.is_important, "notes": lead.notes,
            "lost_reason": lead.lost_reason,
            "last_activity_at": _when(lead.last_activity_at),
        },
        "state_history": [
            {"from": h.from_state, "to": h.to_state, "reason": h.reason,
             "at": _when(h.changed_at)}
            for h in await _rows(db, select(LeadStateHistory).where(
                LeadStateHistory.org_id == ctx.org_id,
                LeadStateHistory.lead_id == lead_id,
            ).order_by(LeadStateHistory.changed_at))
        ],
        "contacts": [
            {"name": c.name, "title": c.title, "email": c.email,
             "phone": c.phone, "primary": c.is_primary}
            for c in await _rows(db, select(Contact).where(
                Contact.org_id == ctx.org_id, Contact.lead_id == lead_id,
            ).order_by(Contact.created_at))
        ],
        "notes": [
            {"note": n.note, "category": n.category, "source": n.source,
             "at": _when(n.created_at)}
            for n in await _rows(db, select(ClientIntelligence).where(
                ClientIntelligence.org_id == ctx.org_id,
                ClientIntelligence.lead_id == lead_id,
            ).order_by(ClientIntelligence.created_at))
        ],
        "meetings": [
            {
                "title": m.title, "status": m.status, "type": m.meeting_type,
                "started_at": _when(m.started_at), "notes": m.notes_text,
                "transcript": _transcript(by_meeting.get(m.id)),
            }
            for m in meetings
        ],
        "project": None if project is None else {
            "name": project.name, "objective": project.objective,
            "status": project.status, "health": project.health,
            "health_reason": project.health_reason,
            "start_date": _when(project.start_date),
            "target_end_date": _when(project.target_end_date),
            "value_estimate": project.value_estimate,
            "currency": project.currency,
        },
        "plans": [
            {"version": p.version, "summary": p.summary, "trigger": p.trigger,
             "changes": p.changes_from_previous, "status": p.status}
            for p in await _by_project(db, ctx, ActionPlan, project_id,
                                       ActionPlan.version)
        ],
        "commitments": [
            {"text": c.text, "direction": c.direction, "to": c.promised_to,
             "by": c.promised_by, "due": _when(c.due_date), "status": c.status}
            for c in await _by_project(db, ctx, ClientCommitment, project_id)
        ],
        "stakeholders": [
            {"role": s.role_at_client, "influence": s.influence,
             "channel": s.preferred_channel,
             "updates": s.receives_progress_updates}
            for s in await _by_project(db, ctx, Stakeholder, project_id)
        ],
        "deliverables": [
            {"type": d.type, "title": d.title, "status": d.status,
             "version": d.version, "content": d.content_md}
            for d in await _by_project(db, ctx, Deliverable, project_id)
        ],
        "invoices": [
            {"kind": i.kind, "amount": i.amount, "currency": i.currency,
             "status": i.status, "due": _when(i.due_date)}
            for i in await _by_project(db, ctx, Invoice, project_id)
        ],
        "action_items": [
            {"title": a.title, "description": a.description, "status": a.status,
             "due": _when(a.due_date), "result": a.result_note,
             "phase": a.phase, "blocked": a.blocked,
             "blocked_reason": a.blocked_reason}
            for a in await _rows(db, select(ActionItem).where(
                ActionItem.org_id == ctx.org_id, ActionItem.lead_id == lead_id,
            ).order_by(ActionItem.created_at))
        ],
        "followups": [
            {"note": f.note, "channel": f.channel, "status": f.status,
             "due": _when(f.due_date)}
            for f in await _rows(db, select(FollowUp).where(
                FollowUp.org_id == ctx.org_id, FollowUp.lead_id == lead_id,
            ).order_by(FollowUp.created_at))
        ],
        "demos": [
            {"date": _when(d.scheduled_date), "time": d.scheduled_time,
             "status": d.status, "notes": d.notes}
            for d in await _rows(db, select(Demo).where(
                Demo.org_id == ctx.org_id, Demo.lead_id == lead_id,
            ).order_by(Demo.created_at))
        ],
        "proposals": [
            {
                "title": p.title, "status": p.status, "total": p.total_amount,
                "currency": p.currency, "content": p.content_md,
                "template_kind": p.template_kind, "sent_at": _when(p.sent_at),
                "revisions": [
                    {"no": r.revision_no, "instruction": r.instruction,
                     "total": r.total_amount, "at": _when(r.edited_at)}
                    for r in by_proposal.get(p.id, [])
                ],
            }
            for p in proposals
        ],
        "threads": [
            {"channel": t.channel, "subject": t.subject, "status": t.status,
             "last_at": _when(t.last_message_at),
             "last_direction": t.last_direction}
            for t in await _rows(db, select(Thread).where(
                Thread.org_id == ctx.org_id, Thread.lead_id == lead_id,
            ).order_by(Thread.created_at))
        ],
        "messages": [
            {"kind": m.kind, "channel": m.channel, "status": m.status,
             "to": m.to_address, "subject": m.subject, "body": m.body,
             "sent_at": _when(m.sent_at)}
            for m in await _rows(db, select(OutboundMessage).where(
                OutboundMessage.org_id == ctx.org_id,
                OutboundMessage.lead_id == lead_id,
            ).order_by(OutboundMessage.created_at))
        ],
        "consent": [
            {"method": c.method, "note": c.note, "at": _when(c.captured_at)}
            for c in await _rows(db, select(ConsentRecord).where(
                ConsentRecord.org_id == ctx.org_id,
                ConsentRecord.lead_id == lead_id,
            ).order_by(ConsentRecord.created_at))
        ],
        "memory": [
            # The embedding is deliberately absent: a vector tells the model
            # nothing and would dwarf the text it was made from.
            {"text": m.text, "source": m.source_type, "at": _when(m.created_at)}
            for m in await _rows(db, select(MemoryChunk).where(
                MemoryChunk.org_id == ctx.org_id, MemoryChunk.lead_id == lead_id,
            ).order_by(MemoryChunk.created_at))
        ],
        "programme": None if programme is None else {
            "name": programme.name, "code": programme.code,
            "description": programme.description,
        },
        "rate_card": None if rate_card is None else {
            "version": rate_card.version, "currency": rate_card.currency,
            "items": rate_card.items,
            "effective_from": _when(rate_card.effective_from),
        },
        "sender": None if sender is None else {
            "name": sender.name, "email": sender.email, "phone": sender.phone,
            "role": sender.role, "designation": sender.designation,
            "department": sender.department,
        },
        "organisation": None if org is None else {
            "name": org.name, "slug": org.slug, "email_domain": org.email_domain,
        },
        "omitted": [],
    }
    _trim(dossier)
    return dossier


def size_of(dossier: dict[str, Any]) -> int:
    return len(json.dumps(dossier, default=str))


def _trim(dossier: dict[str, Any]) -> None:
    """Bring the dossier under the ceiling, and say what that cost.

    Oldest-first within the largest section (D7). The largest section is
    re-chosen after every drop rather than emptied first: a dossier can be over
    the ceiling because of two big sections, and draining one of them entirely
    to spare the other would lose more history than trimming both a little.

    **Nothing is ever truncated mid-record.** A half a meeting is worse than no
    meeting -- the model cannot tell which it is looking at.
    """
    dropped: dict[str, int] = {}
    while size_of(dossier) > DOSSIER_CHAR_CEILING:
        section = _largest(dossier)
        if section is None:
            break
        dossier[section].pop(0)
        dropped[section] = dropped.get(section, 0) + 1

    dossier["omitted"] = [
        {
            "section": section,
            "dropped": count,
            "kept": len(dossier[section]),
            "why": (
                f"the dossier was over the {DOSSIER_CHAR_CEILING:,}-character "
                "ceiling, so the oldest records here were dropped first"
            ),
        }
        for section, count in sorted(dropped.items())
    ]


def _largest(dossier: dict[str, Any]) -> str | None:
    """The trimmable section with the most characters in it, if any has one."""
    best, best_size = None, 0
    for section in TRIMMABLE:
        records = dossier.get(section) or []
        if not records:
            continue
        size = len(json.dumps(records, default=str))
        if size > best_size:
            best, best_size = section, size
    return best


async def _rows(db: AsyncSession, stmt) -> list:
    return list((await db.execute(stmt)).scalars().all())


async def _one(db: AsyncSession, stmt):
    return (await db.execute(stmt)).scalars().first()


async def _by_project(db: AsyncSession, ctx: OrgContext, model, project_id, order=None):
    """Project-scoped rows, oldest first. Empty when the client has no project."""
    if not project_id:
        return []
    stmt = select(model).where(
        model.org_id == ctx.org_id, model.project_id == project_id
    )
    return await _rows(db, stmt.order_by(order if order is not None else model.created_at))


def _transcript(row) -> dict[str, Any] | None:
    """The full text, never a summary of it.

    On the measured client the transcripts are 12,063 characters -- the single
    richest source, and precisely where "the programme runs 28 September to
    2 October" would have been said. Capping them would defeat the feature.
    """
    if row is None:
        return None
    return {
        "text": row.text, "summary": row.summary,
        "words": row.word_count, "low_confidence": row.low_confidence,
    }


def _when(value) -> str | None:
    return None if value is None else str(value)
