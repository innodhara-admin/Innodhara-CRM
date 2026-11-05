"""Deal drill-down (spec 6.6): one deal -- who works it, its score and why,
the people at the client, and what has happened, newest first."""
from __future__ import annotations

from datetime import datetime, tzinfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.constants import INFLUENCE_WEIGHT, LeadState
from app.core.exceptions import NotFoundError
from app.insights import common, scoring, snapshots
from app.models.action_item import ActionItem
from app.models.followup import FollowUp
from app.models.lead import Contact, Lead
from app.models.meeting import Meeting
from app.models.messaging import OutboundMessage
from app.models.organisation import OrgSettings
from app.models.project import Project, Stakeholder
from app.models.proposal import Proposal

TIMELINE_MAX = 30
TREND_DAYS = 30


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, lead_id: str) -> dict:
    lead = (await db.execute(
        select(Lead).where(Lead.org_id == org_id, Lead.id == lead_id)
    )).scalar_one_or_none()
    if lead is None:
        raise NotFoundError("Client not found")
    today = common.local_day(now, tz)
    people = await common.org_people(db, org_id)
    rows = (await common.history(db, org_id)).get(lead.id, [])
    opener, closer = (await common.deal_people(db, org_id, [lead]))[lead.id]

    meetings = list((await db.execute(
        select(Meeting).where(Meeting.org_id == org_id, Meeting.lead_id == lead.id,
                              common.held_meeting())
    )).scalars().all())
    proposals = list((await db.execute(
        select(Proposal).where(Proposal.org_id == org_id, Proposal.lead_id == lead.id)
    )).scalars().all())
    sent = sorted((p for p in proposals
                   if p.sent_at is not None and p.status in scoring.SENT_STATES),
                  key=lambda p: p.sent_at)

    # The one date that says most about where the deal stands.
    candidates = []
    if sent:
        candidates.append(("Proposal sent", sent[-1].sent_at))
    met = [m.started_at or m.created_at for m in meetings if (m.started_at or m.created_at)]
    if met:
        candidates.append(("Last meeting", max(met)))
    opened = [r.changed_at for r in rows
              if r.to_state == LeadState.OPEN.value and r.from_state is not None]
    if opened:
        candidates.append(("Opened", opened[-1]))
    key_label, key_at = max(candidates, key=lambda c: c[1]) if candidates \
        else ("Added", lead.created_at)

    header = {
        "lead_id": lead.id, "name": lead.name, "state": lead.state,
        "label": common.STATE_LABELS.get(lead.state, lead.state),
        "days_in_state": common.days_between(
            common.current_visit_start(rows, lead.created_at), now),
        "opener": common.person_name(people, opener),
        "closer": common.person_name(people, closer),
        "key_date_label": key_label,
        "key_date": common.local_day(key_at, tz).isoformat(),
    }

    score = (await scoring.score_deals(db, org_id, [lead], now, tz=tz))[lead.id]
    trend = await snapshots.score_trend(db, org_id, lead.id, TREND_DAYS, today)
    if not trend or trend[-1]["date"] != today.isoformat():
        trend.append({"date": today.isoformat(), "score": score.value})
    score_block = common.block(
        "ok" if len(trend) >= 2 else "thin",
        None if len(trend) >= 2 else "The trend line fills in one day at a time.",
        value=score.value, health=score.health, trend=trend, factors=score.factors,
    )

    return {
        "deal": common.block(**header),
        "score": score_block,
        "people": await _people(db, org_id, lead, meetings),
        "timeline": await _timeline(db, org_id, tz, now, lead, rows, meetings, sent, people),
        "proposal_value": await _proposal_value(db, org_id, sent),
    }


async def _people(db, org_id, lead, meetings) -> dict:
    project_ids = (await db.execute(
        select(Project.id).where(Project.org_id == org_id, Project.lead_id == lead.id)
    )).scalars().all()
    if not project_ids:
        return common.block("empty", "No people at this client have been recorded yet.",
                            items=[])
    rows = (await db.execute(
        select(Stakeholder, Contact.name)
        .join(Contact, Contact.id == Stakeholder.contact_id, isouter=True)
        .where(Stakeholder.org_id == org_id, Stakeholder.project_id.in_(list(project_ids)))
        .order_by(Stakeholder.created_at)
    )).all()
    if not rows:
        return common.block("empty", "No people at this client have been recorded yet.",
                            items=[])
    seen = {s for m in meetings for s in (m.attendee_stakeholder_ids or [])}
    items = [{"name": name or "Unnamed contact", "role_at_client": s.role_at_client,
              "influence": s.influence, "met": s.id in seen} for s, name in rows]
    items.sort(key=lambda p: -INFLUENCE_WEIGHT.get(p["influence"] or "", 0))
    return common.block(items=items)


def _by(people, user_id) -> str:
    if user_id == "system":
        return "the system"
    return common.person_name(people, user_id) or "someone"


async def _timeline(db, org_id, tz, now, lead, rows, meetings, sent, people) -> dict:
    events: list[tuple[datetime, str, str, str | None]] = []
    for r in rows:
        if r.from_state is None:
            events.append((r.changed_at, "created", "Added", f"by {_by(people, r.changed_by)}"))
        else:
            events.append((r.changed_at, "state",
                           f"Moved to {common.STATE_LABELS.get(r.to_state, r.to_state)}",
                           f"from {common.STATE_LABELS.get(r.from_state, r.from_state)}, "
                           f"by {_by(people, r.changed_by)}"))
    for m in meetings:
        at = m.started_at or m.created_at
        kind = common.MEETING_TYPE_LABELS.get(m.meeting_type or "", "Meeting")
        length = f"{round(m.duration_seconds / 60)} min, " if m.duration_seconds else ""
        events.append((at, "meeting", kind,
                       f"{length}by {_by(people, m.agent_id)}"))
    for sender, at in (await db.execute(
        select(OutboundMessage.sender_user_id, OutboundMessage.sent_at).where(
            OutboundMessage.org_id == org_id, OutboundMessage.lead_id == lead.id,
            OutboundMessage.sent_at.is_not(None))
    )).all():
        events.append((at, "message_sent", "Message sent", f"by {_by(people, sender)}"))
    for p in sent:
        events.append((p.sent_at, "proposal_sent", "Proposal sent", p.title))
    today = common.local_day(now, tz)
    for f in (await db.execute(
        select(FollowUp).where(FollowUp.org_id == org_id, FollowUp.lead_id == lead.id)
    )).scalars().all():
        if f.completed_at is not None:
            events.append((f.completed_at, "followup_done", "Follow-up done",
                           f"by {_by(people, f.owner_id)}"))
        elif f.status == "pending" and f.due_date < today:
            events.append((clock.start_of_day_utc(f.due_date, tz), "followup_overdue",
                           "Follow-up overdue", f"due {f.due_date.isoformat()}"))
    for title, at in (await db.execute(
        select(ActionItem.title, ActionItem.completed_at).where(
            ActionItem.org_id == org_id, ActionItem.lead_id == lead.id,
            ActionItem.completed_at.is_not(None))
    )).all():
        events.append((at, "task_done", "Task done", title))
    events = [e for e in events if e[0] is not None]
    events.sort(key=lambda e: e[0], reverse=True)
    items = [{"at": common.iso_utc(at), "kind": kind, "title": title, "detail": detail}
             for at, kind, title, detail in events[:TIMELINE_MAX]]
    if not items:
        return common.block("empty", "Nothing has happened on this deal yet.", items=[])
    return common.block(items=items)


async def _proposal_value(db, org_id, sent) -> dict | None:
    """Only a proposal that was sent with a real amount on it."""
    priced = [p for p in sent if (p.total_amount or 0) > 0]
    if not priced:
        return None
    latest = priced[-1]
    currency = latest.currency or (await db.execute(
        select(OrgSettings.currency).where(OrgSettings.org_id == org_id)
    )).scalar_one_or_none() or "INR"
    return {"amount": float(latest.total_amount), "currency": currency}
