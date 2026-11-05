"""Handing a finished client to a relationship manager.

Paths are spelled out rather than sharing the `/leads` prefix, because these
routes belong to the relationship side of the system and not to the lead
pipeline; only their subject is the same record.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core import clock
from app.core.constants import (
    CycleOutcome,
    CycleSource,
    EngagementStatus,
    FollowUpStatus,
    LeadState,
    OpportunityStatus,
    Role,
)
from app.core.context import OrgContext
from app.core.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.permissions import can_change_lead_state
from app.database import get_db
from app.engines import knowledge_engine, relationship_engine
from app.models.base import utcnow
from app.models.followup import FollowUp
from app.models.lead import ClientIntelligence, Lead
from app.models.meeting import Meeting
from app.models.lead import LeadStateHistory
from app.models.project import Project
from app.models.relationship import LeadCycle, RelationshipEngagement
from app.models.user import User
from app.services import audit_service, lead_service, notification_service

# How long a client may go unheard-from before the RM's Home calls them quiet.
#
# A module constant and not an `org_settings` column on purpose: there is no
# Alembic here, so a new column needs a hand-written ALTER in
# `_apply_light_migrations` and a migration against a live database. Nobody has
# asked for this to differ per organisation. Promote it the day somebody does.
QUIET_AFTER_DAYS = 30

router = APIRouter(tags=["relationships"])


class HandoverRequest(BaseModel):
    # Left out, the engine chooses. Supplied, a person has chosen and the
    # engine's opinion is recorded alongside rather than thrown away.
    manager_id: str | None = None


class ReassignRequest(BaseModel):
    manager_id: str
    reason: str | None = None


async def _name(db: AsyncSession, org_id: str, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.org_id == org_id)
        )
    ).scalar_one_or_none()
    return (user.name or user.email) if user else None


async def _engagement_dict(
    db: AsyncSession, org_id: str, row: RelationshipEngagement
) -> dict:
    return {
        "id": row.id,
        "lead_id": row.lead_id,
        "manager_id": row.manager_id,
        "manager_name": await _name(db, org_id, row.manager_id),
        "assigned_by": row.assigned_by,
        "assigned_by_name": await _name(db, org_id, row.assigned_by),
        "reason": row.ai_reason,
        "overridden": row.overridden,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "ended_reason": row.ended_reason,
        # The "they might be ready to buy again" card. `status` is "none" for
        # almost every engagement, which is the ordinary answer.
        "opportunity": {
            "status": row.opportunity_status,
            "reason": row.opportunity_reason,
            # The client's own words. The card shows these because a person is
            # deciding, and a paraphrase is not evidence.
            "quote": row.opportunity_quote,
            "meeting_id": row.opportunity_meeting_id,
            "at": row.opportunity_at.isoformat() if row.opportunity_at else None,
            "decided_by_name": await _name(db, org_id, row.opportunity_decided_by),
            "decided_at": row.opportunity_decided_at.isoformat()
            if row.opportunity_decided_at else None,
        },
    }


async def _active_engagement(
    db: AsyncSession, org_id: str, lead_id: str
) -> RelationshipEngagement | None:
    return (
        await db.execute(
            select(RelationshipEngagement)
            .where(
                RelationshipEngagement.org_id == org_id,
                RelationshipEngagement.lead_id == lead_id,
                RelationshipEngagement.status == EngagementStatus.ACTIVE.value,
            )
            .order_by(RelationshipEngagement.started_at.desc())
        )
    ).scalars().first()


async def _last_touch(
    db: AsyncSession, org_id: str, lead_id: str
) -> datetime | None:
    """When anyone last actually spoke to this client.

    Every meeting counts, not only the relationship manager's own: if a
    colleague spoke to them last week the client has been spoken to, and
    telling the RM to chase would be wrong.
    """
    return (
        await db.execute(
            select(func.max(func.coalesce(Meeting.started_at, Meeting.created_at)))
            .where(Meeting.org_id == org_id, Meeting.lead_id == lead_id)
        )
    ).scalar_one_or_none()


async def _next_touch(
    db: AsyncSession, org_id: str, lead_id: str
) -> FollowUp | None:
    """The soonest planned conversation, if one is planned.

    Relationship follow-ups are ordinary `followups` rows -- the table already
    holds a lead, an owner, a due date, a channel and a note, which is exactly
    what a planned touch is. Step 5 starts writing them from meetings; until
    then this is legitimately empty and the screen says so.
    """
    return (
        await db.execute(
            select(FollowUp)
            .where(
                FollowUp.org_id == org_id,
                FollowUp.lead_id == lead_id,
                FollowUp.status == FollowUpStatus.PENDING.value,
            )
            .order_by(FollowUp.due_date)
        )
    ).scalars().first()


@router.get("/relationships/mine")
async def my_clients(
    ctx: OrgContext = Depends(require_permission("manage_relationships")),
    db: AsyncSession = Depends(get_db),
):
    """The relationship manager's Home: who I look after, worst first.

    Ordered by how long the client has gone unheard-from, longest first, so
    the screen answers "who needs me today" without anyone reading past the
    fold. A client nobody has ever met sorts as the most neglected of all,
    which is right -- being handed a client and never calling them is the
    failure this screen exists to make visible.
    """
    engagements = (
        await db.execute(
            select(RelationshipEngagement, Lead)
            .join(Lead, Lead.id == RelationshipEngagement.lead_id)
            .where(
                RelationshipEngagement.org_id == ctx.org_id,
                RelationshipEngagement.manager_id == ctx.user_id,
                RelationshipEngagement.status == EngagementStatus.ACTIVE.value,
            )
        )
    ).all()

    tz = await clock.org_zone(db, ctx.org_id)
    today = clock.today(tz)
    rows = []
    for engagement, lead in engagements:
        last = await _last_touch(db, ctx.org_id, lead.id)
        last_date = clock.local_date(last, tz)
        days_quiet = (today - last_date).days if last_date else None
        nxt = await _next_touch(db, ctx.org_id, lead.id)
        due = nxt.due_date if nxt else None
        rows.append({
            "engagement_id": engagement.id,
            "lead_id": lead.id,
            "lead_name": lead.name,
            "city": lead.city,
            "started_at": engagement.started_at.isoformat()
            if engagement.started_at else None,
            "last_touch_at": last.isoformat() if last else None,
            "days_quiet": days_quiet,
            # None (never spoken to) counts as quiet: it is the worst case,
            # not an unknown one.
            "is_quiet": days_quiet is None or days_quiet >= QUIET_AFTER_DAYS,
            "next_touch_date": due.isoformat() if due else None,
            "next_touch_note": nxt.note if nxt else None,
            "next_touch_overdue": bool(due and due < today),
            # Home needs to surface this: a client hinting they want to buy
            # again is the single most time-sensitive thing on the screen.
            "opportunity_open":
                engagement.opportunity_status == OpportunityStatus.OPEN.value,
            "opportunity_reason": engagement.opportunity_reason
            if engagement.opportunity_status == OpportunityStatus.OPEN.value
            else None,
        })

    # -1 sorts "never spoken to" above every real gap.
    rows.sort(key=lambda r: (-1 if r["days_quiet"] is None else -r["days_quiet"]))
    return rows


@router.get("/relationship-managers")
async def list_relationship_managers(
    ctx: OrgContext = Depends(require_permission("assign_relationship_manager")),
    db: AsyncSession = Depends(get_db),
):
    """The dropdown behind "hand this client to someone else".

    The engine will usually be right, and when it is not there has to be a way
    to fix it that is not a developer.
    """
    people = await relationship_engine.managers(db, ctx.org_id)
    return [
        {"id": p.id, "name": p.name, "email": p.email,
         "designation": p.designation}
        for p in people
    ]


@router.post("/leads/{lead_id}/relationship/handover")
async def hand_to_relationship_manager(
    lead_id: str,
    body: HandoverRequest,
    ctx: OrgContext = Depends(require_permission("assign_relationship_manager")),
    db: AsyncSession = Depends(get_db),
):
    """Hand a finished client to a relationship manager.

    Only from `closed`, and only ever because a person pressed the button —
    doing nothing leaves the client closed, which stays a valid ending. We are
    not putting every client into relationship management.
    """
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    # Same question as "may you move this lead": the owner, a sales lead, or
    # the org admin. Reusing it keeps one answer to "whose lead is this".
    if not can_change_lead_state(ctx.role, ctx.user_id, lead.owner_id):
        owner_name = await _name(db, ctx.org_id, lead.owner_id) or "its owner"
        raise PermissionDeniedError(
            f"This lead belongs to {owner_name}. Its owner or a sales lead "
            f"can hand it to a relationship manager."
        )
    if lead.state != LeadState.CLOSED.value:
        raise ValidationFailedError(
            f"'{lead.name}' is {lead.state}. A client is handed to a "
            f"relationship manager once the work is delivered and the lead is "
            f"closed."
        )
    existing = await _active_engagement(db, ctx.org_id, lead_id)
    if existing is not None:
        manager_name = await _name(db, ctx.org_id, existing.manager_id)
        raise ValidationFailedError(
            f"{manager_name} already looks after '{lead.name}'. Reassign the "
            f"engagement instead of starting a second one."
        )

    manager, reason, overridden = await relationship_engine.choose_manager(
        db, org_id=ctx.org_id, lead=lead, chosen_id=body.manager_id
    )
    if manager is None:
        # Deliberately a refusal a person can act on rather than a silent no-op.
        raise ValidationFailedError(
            f"There is no relationship manager in this organisation yet, so "
            f"'{lead.name}' cannot be handed over. Add one first, or leave the "
            f"lead closed."
        )

    engagement = RelationshipEngagement(
        org_id=ctx.org_id,
        lead_id=lead.id,
        manager_id=manager.id,
        assigned_by=ctx.user_id,
        ai_reason=reason,
        overridden=overridden,
        status=EngagementStatus.ACTIVE.value,
    )
    db.add(engagement)
    await db.flush()

    await notification_service.notify(
        db, org_id=ctx.org_id, user_id=manager.id,
        title=f"{lead.name} is yours to look after",
        body=(
            f"{ctx.name or ctx.email} handed this client over now that the "
            f"work is finished. {reason}"
        ),
        kind="relationship_handover", entity_type="lead", entity_id=lead.id,
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="relationship.handover", entity_type="lead", entity_id=lead.id,
        detail={"manager_id": manager.id, "overridden": overridden},
    )
    await db.commit()
    return await _engagement_dict(db, ctx.org_id, engagement)


@router.post("/leads/{lead_id}/relationship/manager")
async def reassign_relationship_manager(
    lead_id: str,
    body: ReassignRequest,
    ctx: OrgContext = Depends(require_permission("assign_relationship_manager")),
    db: AsyncSession = Depends(get_db),
):
    """Correct a bad pick.

    This moves the manager on the engagement that already exists instead of
    ending it and opening another: a client has one relationship, and who
    holds it changing is not the client's history changing.
    """
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    if not can_change_lead_state(ctx.role, ctx.user_id, lead.owner_id):
        owner_name = await _name(db, ctx.org_id, lead.owner_id) or "its owner"
        raise PermissionDeniedError(
            f"This lead belongs to {owner_name}. Its owner or a sales lead "
            f"can change who looks after it."
        )
    engagement = await _active_engagement(db, ctx.org_id, lead_id)
    if engagement is None:
        raise NotFoundError(
            f"Nobody is looking after '{lead.name}' yet, so there is nothing "
            f"to reassign."
        )

    people = await relationship_engine.managers(db, ctx.org_id)
    manager = next((p for p in people if p.id == body.manager_id), None)
    if manager is None:
        raise ValidationFailedError(
            "That person is not a relationship manager in this organisation."
        )
    if manager.id == engagement.manager_id:
        return await _engagement_dict(db, ctx.org_id, engagement)

    # Both read BEFORE the reassignment: an audit row that says it moved a
    # client from someone to themselves is worse than no audit row.
    previous_id = engagement.manager_id
    previous = await _name(db, ctx.org_id, previous_id)
    engagement.manager_id = manager.id
    engagement.overridden = True
    engagement.ai_reason = (
        f"{ctx.name or ctx.email} moved this from {previous} to {manager.name}"
        + (f": {body.reason}" if body.reason else "")
    )

    await notification_service.notify(
        db, org_id=ctx.org_id, user_id=manager.id,
        title=f"{lead.name} is now yours to look after",
        body=engagement.ai_reason,
        kind="relationship_handover", entity_type="lead", entity_id=lead.id,
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="relationship.reassigned", entity_type="lead", entity_id=lead.id,
        detail={"from": previous_id, "to": manager.id},
    )
    await db.commit()
    return await _engagement_dict(db, ctx.org_id, engagement)


class OpportunityDecision(BaseModel):
    note: str | None = None


async def _closed_at(db: AsyncSession, org_id: str, lead_id: str):
    """When this lead was last closed, from its own history."""
    return (
        await db.execute(
            select(LeadStateHistory.changed_at)
            .where(
                LeadStateHistory.org_id == org_id,
                LeadStateHistory.lead_id == lead_id,
                LeadStateHistory.to_state == LeadState.CLOSED.value,
            )
            .order_by(LeadStateHistory.changed_at.desc())
        )
    ).scalars().first()


async def _open_new_cycle(
    db: AsyncSession, *, org_id: str, lead, note: str | None
) -> LeadCycle:
    """Write down the round that just ended, then open the next one.

    Cycles are written lazily, so the first time a client comes back there is
    nothing on record for the round already finished. It is reconstructed from
    the lead itself — its owner, its creation date, the moment it was closed —
    rather than left as a gap, because a page showing "round 2" and nothing
    else would be worse than no page at all.
    """
    cycles = (
        await db.execute(
            select(LeadCycle)
            .where(LeadCycle.org_id == org_id, LeadCycle.lead_id == lead.id)
            .order_by(LeadCycle.cycle_number)
        )
    ).scalars().all()

    if not cycles:
        project_id = (
            await db.execute(
                select(Project.id)
                .where(Project.org_id == org_id, Project.lead_id == lead.id)
                .order_by(Project.created_at.desc())
            )
        ).scalars().first()
        db.add(
            LeadCycle(
                org_id=org_id,
                lead_id=lead.id,
                cycle_number=1,
                owner_id=lead.owner_id,
                source=CycleSource.COLD_CALL.value,
                opened_at=lead.created_at,
                closed_at=await _closed_at(db, org_id, lead.id) or utcnow(),
                outcome=CycleOutcome.CLOSED.value,
                project_id=project_id,
                note="Reconstructed from the lead when it came back for a "
                     "second round.",
            )
        )
        await db.flush()
        next_number = 2
    else:
        # Close whatever is still running before opening another.
        for cycle in cycles:
            if cycle.outcome == CycleOutcome.RUNNING.value:
                cycle.outcome = CycleOutcome.CLOSED.value
                cycle.closed_at = cycle.closed_at or utcnow()
        next_number = max(c.cycle_number for c in cycles) + 1

    fresh = LeadCycle(
        org_id=org_id,
        lead_id=lead.id,
        cycle_number=next_number,
        # No owner yet, on purpose: a sales lead picks one, and until they do
        # the lead cannot be driven by an agent who simply grabbed it.
        owner_id=None,
        source=CycleSource.RELATIONSHIP.value,
        opened_at=utcnow(),
        outcome=CycleOutcome.RUNNING.value,
        note=note,
    )
    db.add(fresh)
    await db.flush()
    return fresh


async def _open_opportunity(
    db: AsyncSession, org_id: str, lead_id: str
) -> RelationshipEngagement:
    """The engagement with a card waiting on it, or a refusal that says so."""
    engagement = await _active_engagement(db, org_id, lead_id)
    if engagement is None:
        raise NotFoundError("Nobody is looking after this client.")
    if engagement.opportunity_status != OpportunityStatus.OPEN.value:
        raise ValidationFailedError(
            "There is no open opportunity on this client to answer."
        )
    return engagement


@router.post("/leads/{lead_id}/relationship/opportunity/accept")
async def accept_opportunity(
    lead_id: str,
    body: OpportunityDecision,
    ctx: OrgContext = Depends(require_permission("manage_relationships")),
    db: AsyncSession = Depends(get_db),
):
    """The relationship manager agrees: this client wants to buy again.

    Every sales lead is told, because any of them may be the one to pick up
    the new round, and the notification carries the client's own words so the
    person reading it can judge it for themselves.

    Six things happen together, and half of them happening would be worse
    than none: the finished round is written down, a new round is opened with
    no owner, the lead moves `closed -> open`, `lead.owner_id` is cleared, the
    relationship engagement ends, and every sales lead is told.

    Clearing the owner is the deliberate part. A lead with nobody on it can be
    moved only by a sales lead or the org admin, which is exactly the next
    thing that should happen: one of them chooses who takes this round.

    On the codebase rule that only `PATCH /leads/{id}/state` moves a lead:
    this is now the second caller of `lead_service.change_state`, and both are
    endpoints where a person acted. No engine, background job or AI agent
    moves a lead — that is the invariant, and it holds. Handing a client back
    to sales is also the ONLY lead-state move this role can make; holding no
    `manage_leads`, they are refused every other transition.
    """
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    engagement = await _open_opportunity(db, ctx.org_id, lead_id)

    engagement.opportunity_status = OpportunityStatus.ACCEPTED.value
    engagement.opportunity_decided_by = ctx.user_id
    engagement.opportunity_decided_at = utcnow()

    reason = (
        body.note
        or engagement.opportunity_reason
        or "A catch-up suggested this client is ready to buy again"
    )
    cycle = await _open_new_cycle(db, org_id=ctx.org_id, lead=lead, note=reason)

    # The one lead-state move a relationship manager makes, and the boundary of
    # the role rather than a hole in it: handing a client BACK to sales. They
    # hold no `manage_leads`, so `PATCH /leads/{id}/state` refuses them every
    # other transition.
    await lead_service.change_state(
        db, org_id=ctx.org_id, lead_id=lead_id, to_state=LeadState.OPEN.value,
        changed_by=ctx.user_id,
        reason=f"Back into sales after a catch-up: {reason}",
    )
    # The new round has no owner. A sales lead picks one; until then only a
    # sales lead or the org admin can move this lead at all.
    lead.owner_id = None

    # Open question 4, answered: the engagement ends outright rather than
    # pausing. If they want a manager again after this round closes, somebody
    # presses the handover button again.
    engagement.status = EngagementStatus.RETURNED_TO_SALES.value
    engagement.ended_at = utcnow()
    engagement.ended_reason = reason

    who = ctx.name or ctx.email
    quote = engagement.opportunity_quote
    leads = (
        await db.execute(
            select(User).where(
                User.org_id == ctx.org_id,
                User.is_active.is_(True),
                User.role == Role.SALES_LEAD.value,
            )
        )
    ).scalars().all()
    for sales_lead in leads:
        await notification_service.notify(
            db, org_id=ctx.org_id, user_id=sales_lead.id,
            title=f"{lead.name} is back in sales — it needs an owner",
            body=(
                f"{who} had a catch-up and agreed this client wants to buy "
                f"again, so it is open again with nobody on it. "
                f"{engagement.opportunity_reason or ''}"
                + (f' They said: "{quote}"' if quote else "")
            ),
            kind="relationship_opportunity",
            entity_type="lead", entity_id=lead.id,
        )

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="relationship.opportunity_accepted",
        entity_type="lead", entity_id=lead.id,
        detail={"reason": engagement.opportunity_reason,
                "sales_leads_notified": len(leads),
                "cycle_number": cycle.cycle_number},
    )
    await db.commit()
    return {
        "engagement": await _engagement_dict(db, ctx.org_id, engagement),
        "sales_leads_notified": len(leads),
        "lead_state": lead.state,
        "cycle_number": cycle.cycle_number,
        # Null, and the screen says so: this is the question a sales lead is
        # now being asked.
        "cycle_owner_id": cycle.owner_id,
    }


@router.post("/leads/{lead_id}/relationship/opportunity/dismiss")
async def dismiss_opportunity(
    lead_id: str,
    body: OpportunityDecision,
    ctx: OrgContext = Depends(require_permission("manage_relationships")),
    db: AsyncSession = Depends(get_db),
):
    """It was politeness, not interest.

    Recorded rather than deleted: the AI having been wrong is the only signal
    that the detection needs looking at, and a dismissed card that leaves no
    trace teaches nobody anything.
    """
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    engagement = await _open_opportunity(db, ctx.org_id, lead_id)

    engagement.opportunity_status = OpportunityStatus.DISMISSED.value
    engagement.opportunity_decided_by = ctx.user_id
    engagement.opportunity_decided_at = utcnow()
    if body.note:
        engagement.opportunity_reason = (
            f"{engagement.opportunity_reason or ''} — dismissed: {body.note}"
        ).strip(" —")

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="relationship.opportunity_dismissed",
        entity_type="lead", entity_id=lead.id, detail={"note": body.note},
    )
    await db.commit()
    return {"engagement": await _engagement_dict(db, ctx.org_id, engagement)}


class CycleOwnerRequest(BaseModel):
    owner_id: str


def _cycle_dict(row: LeadCycle, owner_name: str | None) -> dict:
    return {
        "id": row.id,
        "cycle_number": row.cycle_number,
        "owner_id": row.owner_id,
        "owner_name": owner_name,
        "source": row.source,
        "opened_at": row.opened_at.isoformat() if row.opened_at else None,
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "outcome": row.outcome,
        "project_id": row.project_id,
        "note": row.note,
    }


@router.get("/leads/{lead_id}/cycles")
async def list_cycles(
    lead_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    """The rounds of business with this client, oldest first.

    An empty list is the ordinary answer and means "one round, still the only
    one" — cycles are only written once a client actually comes back, so most
    leads have none and the lead page shows what it always did.
    """
    await lead_service.get_lead(db, ctx.org_id, lead_id)
    rows = (
        await db.execute(
            select(LeadCycle)
            .where(LeadCycle.org_id == ctx.org_id, LeadCycle.lead_id == lead_id)
            .order_by(LeadCycle.cycle_number)
        )
    ).scalars().all()
    return [
        _cycle_dict(row, await _name(db, ctx.org_id, row.owner_id))
        for row in rows
    ]


@router.post("/leads/{lead_id}/cycles/{cycle_number}/owner")
async def set_cycle_owner(
    lead_id: str,
    cycle_number: int,
    body: CycleOwnerRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Give the new round to someone.

    A reopened lead has no owner, so `can_change_lead_state` already limits it
    to a sales lead or the org admin — the same people this endpoint is for.
    Reusing that check rather than writing a second rule keeps one answer to
    "whose lead is this".

    Assigning sets the owner on BOTH the cycle and the lead. The cycle is the
    record of the round; `lead.owner_id` is what the rest of the system reads,
    and leaving those two disagreeing would be a bug waiting to be found by
    somebody's screen.
    """
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    if not can_change_lead_state(ctx.role, ctx.user_id, lead.owner_id):
        raise PermissionDeniedError(
            "A sales lead or the org admin assigns the owner of a new round."
        )

    cycle = (
        await db.execute(
            select(LeadCycle).where(
                LeadCycle.org_id == ctx.org_id,
                LeadCycle.lead_id == lead_id,
                LeadCycle.cycle_number == cycle_number,
            )
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise NotFoundError(f"This client has no round {cycle_number}.")
    if cycle.outcome != CycleOutcome.RUNNING.value:
        raise ValidationFailedError(
            f"Round {cycle_number} is already finished ({cycle.outcome}); "
            f"its owner cannot be changed."
        )

    owner = (
        await db.execute(
            select(User).where(
                User.id == body.owner_id,
                User.org_id == ctx.org_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise ValidationFailedError("That person is not in this organisation.")
    if owner.role not in (Role.SALES_AGENT.value, Role.SALES_LEAD.value):
        raise ValidationFailedError(
            "A round of selling belongs to a sales agent or a sales lead."
        )

    cycle.owner_id = owner.id
    lead.owner_id = owner.id

    await notification_service.notify(
        db, org_id=ctx.org_id, user_id=owner.id,
        title=f"{lead.name} is yours",
        body=(
            f"{ctx.name or ctx.email} gave you this client for a new round. "
            + (cycle.note or "")
        ),
        kind="lead_assigned", entity_type="lead", entity_id=lead.id,
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="lead.cycle_owner_set",
        entity_type="lead", entity_id=lead.id,
        detail={"cycle_number": cycle_number, "owner_id": owner.id},
    )
    await db.commit()
    return _cycle_dict(cycle, owner.name or owner.email)


@router.get("/leads/{lead_id}/relationship")
async def get_relationship(
    lead_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Who looks after this client, if anyone.

    `null` rather than a 404 when nobody does: "no relationship manager" is an
    ordinary, permanent state for most clients, not a missing record.
    """
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    engagement = await _active_engagement(db, ctx.org_id, lead_id)

    # `replay_story` already assembles projects, proposals, known facts and
    # memories into a short readable block for the revival card. That is
    # precisely "everything we know about this client", so it is reused rather
    # than written again -- one story, one place to improve it.
    story = await knowledge_engine.replay_story(db, org_id=ctx.org_id, lead=lead)

    # How to approach them: the notes the organisation has accumulated, newest
    # first. Deliberately the stored notes and not a fresh model call -- this
    # endpoint is opened every time a screen loads, and a summary that changes
    # wording on every refresh reads as unreliable even when it is not.
    notes = (
        await db.execute(
            select(ClientIntelligence)
            .where(
                ClientIntelligence.org_id == ctx.org_id,
                ClientIntelligence.lead_id == lead_id,
            )
            .order_by(ClientIntelligence.created_at.desc())
            .limit(12)
        )
    ).scalars().all()

    last = await _last_touch(db, ctx.org_id, lead_id)
    nxt = await _next_touch(db, ctx.org_id, lead_id)
    tz = await clock.org_zone(db, ctx.org_id)
    last_date = clock.local_date(last, tz)
    today = clock.today(tz)

    return {
        # Unchanged shape for every existing caller: null when nobody looks
        # after this client, which stays the ordinary answer for most of them.
        "engagement": await _engagement_dict(db, ctx.org_id, engagement)
        if engagement is not None else None,
        "story": story,
        "intelligence": [
            {"note": n.note, "category": n.category, "source": n.source,
             "at": n.created_at.isoformat()}
            for n in notes
        ],
        "last_touch_at": last.isoformat() if last else None,
        "days_quiet": (today - last_date).days if last_date else None,
        "next_touch_date": nxt.due_date.isoformat() if nxt else None,
        "next_touch_note": nxt.note if nxt else None,
    }
