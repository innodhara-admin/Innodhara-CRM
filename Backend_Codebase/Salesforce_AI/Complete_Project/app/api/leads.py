"""Leads (schools), contacts (incl. business-card scan), consent and
school-intelligence notes."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import memory as memory_ai, vision
from app.api.deps import get_org_context, require_permission
from app.core.constants import (
    ContactSource,
    LeadState,
    MessageChannel,
    MessageKind,
    Role,
)
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.database import get_db
from app.models.action_item import ActionItem
from app.models.followup import FollowUp
from app.models.lead import ConsentRecord, Contact, Lead, LeadStateHistory, ClientIntelligence
from app.models.meeting import Meeting
from app.models.base import utcnow
from app.models.messaging import OutboundMessage
from app.models.organisation import OrgSettings
from app.models.mou import MouDocument
from app.models.proposal import Proposal
from app.models.user import User
from app.services import (
    audit_service,
    intro_service,
    lead_service,
    notification_service,
    storage,
)

router = APIRouter(prefix="/leads", tags=["leads"])


class NewLeadContact(BaseModel):
    """The contact a sales lead gives when opening a lead straight away."""
    name: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None


class LeadRequest(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    address: str | None = None
    city: str | None = None
    region: str | None = None
    website: str | None = None
    source: str | None = None
    notes: str | None = None
    owner_id: str | None = None
    # 7 Oct 2026: a sales lead may create the lead already open, with its
    # contact. Left out (every older app), nothing changes.
    open_now: bool = False
    contact: NewLeadContact | None = None


class LeadUpdateRequest(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    website: str | None = None
    notes: str | None = None
    owner_id: str | None = None
    is_important: bool | None = None


class StateChangeRequest(BaseModel):
    state: str
    reason: str | None = None


class ContactRequest(BaseModel):
    name: str
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    is_primary: bool = False
    # F38: on the SAVE of a card-scanned contact, draft the introduction from
    # these confirmed values. Ignored for contacts that did not come from a card,
    # and ignored once an intro already exists for them.
    draft_intro: bool = True


class IntelligenceRequest(BaseModel):
    note: str = Field(min_length=2)
    category: str | None = None
    source: str = "typed"  # typed | voice


class ConsentRequest(BaseModel):
    method: str = "verbal"
    note: str | None = None
    meeting_id: str | None = None


def _lead_dict(lead: Lead) -> dict:
    return {
        "id": lead.id,
        "name": lead.name,
        "state": lead.state,
        "is_important": lead.is_important,
        "owner_id": lead.owner_id,
        "address": lead.address,
        "city": lead.city,
        "region": lead.region,
        "website": lead.website,
        "source": lead.source,
        "notes": lead.notes,
        "suggested_state": lead.suggested_state,
        "suggested_state_reason": lead.suggested_state_reason,
        "last_activity_at": lead.last_activity_at.isoformat() if lead.last_activity_at else None,
        "created_at": lead.created_at.isoformat(),
    }


@router.post("")
async def create_lead(
    body: LeadRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    # The creation rules (owner check, pre-sales state, history, audit, the
    # owner's notification) live in lead_service, shared with the assistant.
    if body.open_now:
        if body.owner_id and body.owner_id != ctx.user_id:
            raise ValidationFailedError(
                "A lead opened straight away is owned by you, so it cannot be "
                "given to someone else.")
        lead, _contact = await lead_service.create_open_lead(
            db, ctx, name=body.name,
            contact=body.contact.model_dump() if body.contact else None,
            address=body.address, city=body.city, region=body.region,
            website=body.website, source=body.source, notes=body.notes,
        )
    else:
        lead, _owner_name = await lead_service.create_lead(
            db, ctx, name=body.name, owner_id=body.owner_id,
            address=body.address, city=body.city, region=body.region,
            website=body.website, source=body.source, notes=body.notes,
        )
    await db.commit()
    return _lead_dict(lead)


@router.get("")
async def list_leads(
    state: str | None = None,
    q: str | None = None,
    mine: bool = False,
    important: bool = False,
    limit: int = 50,
    offset: int = 0,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Lead).where(Lead.org_id == ctx.org_id)
    if state:
        try:
            stmt = stmt.where(Lead.state == LeadState(state).value)
        except ValueError:
            raise ValidationFailedError(f"Unknown state '{state}'")
    if q:
        stmt = stmt.where(func.lower(Lead.name).like(f"%{q.lower()}%"))
    if mine:
        stmt = stmt.where(Lead.owner_id == ctx.user_id)
    if important:
        stmt = stmt.where(Lead.is_important.is_(True))
    leads = (
        await db.execute(
            stmt.order_by(Lead.last_activity_at.desc())
            .offset(max(offset, 0)).limit(min(limit, 200))
        )
    ).scalars().all()
    return [_lead_dict(lead) for lead in leads]


@router.get("/assignable-owners")
async def assignable_owners(
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    """The people a lead may be handed to when it is created.

    Sales agents only: cold calling is the agent's job, and the picker should
    not invite a sales lead to assign work to another lead.

    Guarded by `manage_leads` rather than `manage_staff` on purpose. The
    obvious source, `GET /admin/users`, is org-admin only, so a sales lead —
    the very person who assigns leads — cannot call it.

    NOTE: this route MUST stay above `GET /{lead_id}`. FastAPI matches in
    declaration order, and below it "assignable-owners" is read as a lead id.
    """
    users = (
        await db.execute(
            select(User)
            .where(
                User.org_id == ctx.org_id,
                User.is_active.is_(True),
                User.role == Role.SALES_AGENT.value,
            )
            .order_by(User.name)
        )
    ).scalars().all()
    return [
        {"id": u.id, "name": u.name or u.email, "email": u.email}
        for u in users
    ]


@router.get("/recently-opened")
async def recently_opened(
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Leads that just came out of cold calling — the home-screen announcement.

    A lead qualifies while it is still OPEN and its cold_calling -> open move
    is inside the org's window. Both conditions are checked, so the card
    disappears the moment someone records a meeting and confirms ACTIVE, and
    again when the window lapses, without anything needing to expire it.

    There is no `opened_at` column: the transition row already records when it
    happened, and duplicating that on `leads` would give two answers that can
    disagree.

    NOTE: must stay above `GET /{lead_id}` — see `assignable_owners`.
    """
    settings = (
        await db.execute(
            select(OrgSettings).where(OrgSettings.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    days = getattr(settings, "lead_open_feed_days", None) or 3
    cutoff = utcnow() - timedelta(days=days)

    rows = (
        await db.execute(
            select(Lead, LeadStateHistory)
            .join(LeadStateHistory, LeadStateHistory.lead_id == Lead.id)
            .where(
                Lead.org_id == ctx.org_id,
                Lead.state == LeadState.OPEN.value,
                LeadStateHistory.org_id == ctx.org_id,
                LeadStateHistory.from_state == LeadState.COLD_CALLING.value,
                LeadStateHistory.to_state == LeadState.OPEN.value,
                LeadStateHistory.changed_at >= cutoff,
            )
            .order_by(LeadStateHistory.changed_at.desc())
            .limit(50)
        )
    ).all()

    owner_ids = {lead.owner_id for lead, _ in rows if lead.owner_id}
    names: dict[str, str] = {}
    if owner_ids:
        for u in (
            await db.execute(
                select(User).where(
                    User.id.in_(owner_ids), User.org_id == ctx.org_id
                )
            )
        ).scalars().all():
            names[u.id] = u.name or u.email

    return [
        {
            "id": lead.id,
            "name": lead.name,
            "city": lead.city,
            "owner_id": lead.owner_id,
            "owner_name": names.get(lead.owner_id) if lead.owner_id else None,
            "opened_at": history.changed_at.isoformat(),
            "reason": history.reason,
        }
        for lead, history in rows
    ]


@router.get("/{lead_id}")
async def get_lead_detail(
    lead_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    contacts = (
        await db.execute(
            select(Contact).where(Contact.org_id == ctx.org_id, Contact.lead_id == lead_id)
        )
    ).scalars().all()
    items = (
        await db.execute(
            select(ActionItem)
            .where(ActionItem.org_id == ctx.org_id, ActionItem.lead_id == lead_id)
            .order_by(ActionItem.created_at.desc()).limit(20)
        )
    ).scalars().all()
    meetings = (
        await db.execute(
            select(Meeting)
            .where(Meeting.org_id == ctx.org_id, Meeting.lead_id == lead_id)
            .order_by(Meeting.created_at.desc()).limit(10)
        )
    ).scalars().all()
    proposals = (
        await db.execute(
            select(Proposal)
            .where(Proposal.org_id == ctx.org_id, Proposal.lead_id == lead_id)
            .order_by(Proposal.created_at.desc()).limit(10)
        )
    ).scalars().all()
    # A SEPARATE query, and a separate key below. An MOU is signed AFTER a
    # proposal is accepted, so a contract merged into that list would arrive
    # on an already-closed deal -- and inbound_engine reads a sent proposal as
    # "the deal is agreed" (D-A).
    mous = (
        await db.execute(
            select(MouDocument)
            .where(MouDocument.org_id == ctx.org_id,
                   MouDocument.lead_id == lead_id)
            .order_by(MouDocument.created_at.desc()).limit(10)
        )
    ).scalars().all()
    followups = (
        await db.execute(
            select(FollowUp)
            .where(FollowUp.org_id == ctx.org_id, FollowUp.lead_id == lead_id)
            .order_by(FollowUp.due_date.desc()).limit(10)
        )
    ).scalars().all()
    notes = (
        await db.execute(
            select(ClientIntelligence)
            .where(ClientIntelligence.org_id == ctx.org_id,
                   ClientIntelligence.lead_id == lead_id)
            .order_by(ClientIntelligence.created_at.desc()).limit(20)
        )
    ).scalars().all()
    history = (
        await db.execute(
            select(LeadStateHistory)
            .where(LeadStateHistory.org_id == ctx.org_id,
                   LeadStateHistory.lead_id == lead_id)
            .order_by(LeadStateHistory.changed_at.desc()).limit(20)
        )
    ).scalars().all()
    # One query for every name the timeline and the owner line need, rather
    # than one per history row.
    wanted = {h.changed_by for h in history if h.changed_by} | (
        {lead.owner_id} if lead.owner_id else set()
    )
    names: dict[str, str] = {}
    if wanted:
        for u in (
            await db.execute(
                select(User).where(User.id.in_(wanted), User.org_id == ctx.org_id)
            )
        ).scalars().all():
            names[u.id] = u.name or u.email
    # Why this lead cannot be opened yet (cold calling only; None otherwise),
    # so the app can say it before the person taps "open" rather than after.
    open_blocker = await lead_service.open_blocker(db, lead, viewer_id=ctx.user_id)
    return {
        **_lead_dict(lead),
        "owner_name": names.get(lead.owner_id) if lead.owner_id else None,
        "can_open": lead.state == LeadState.COLD_CALLING.value and open_blocker is None,
        "open_blocker": open_blocker,
        "contacts": [
            {"id": c.id, "name": c.name, "title": c.title, "email": c.email,
             "phone": c.phone, "is_primary": c.is_primary,
             "needs_review": c.needs_review, "source": c.source,
             "created_by": c.created_by,
             "added_by_owner": bool(lead.owner_id) and c.created_by == lead.owner_id}
            for c in contacts
        ],
        "action_items": [
            {"id": i.id, "title": i.title, "status": i.status,
             "owner_id": i.owner_id,
             "due_date": i.due_date.isoformat() if i.due_date else None}
            for i in items
        ],
        "meetings": [
            {"id": m.id, "status": m.status,
             "started_at": m.started_at.isoformat() if m.started_at else None,
             "duration_seconds": m.duration_seconds}
            for m in meetings
        ],
        "proposals": [
            {"id": p.id, "title": p.title, "status": p.status,
             "total_amount": p.total_amount, "currency": p.currency}
            for p in proposals
        ],
        # No total and no currency: MouDocument has no such columns, so a
        # screen that sums a client's documents cannot pick a contract up.
        "mous": [
            {"id": m.id, "title": m.title, "status": m.status,
             "created_at": m.created_at.isoformat()}
            for m in mous
        ],
        "followups": [
            {"id": f.id, "due_date": f.due_date.isoformat(), "channel": f.channel,
             "status": f.status, "note": f.note}
            for f in followups
        ],
        "intelligence": [
            {"id": n.id, "note": n.note, "category": n.category,
             "source": n.source, "created_at": n.created_at.isoformat()}
            for n in notes
        ],
        # Newest first, as before. The timeline strip in the app reverses it.
        # "system" is a real value in `changed_by` (engines and jobs move
        # leads too) and has no user row, so it is spelled out rather than
        # left blank.
        "state_history": [
            {"from": h.from_state, "to": h.to_state, "reason": h.reason,
             "at": h.changed_at.isoformat(),
             "by": ("the system" if h.changed_by == "system"
                    else names.get(h.changed_by) if h.changed_by else None)}
            for h in history
        ],
    }


@router.patch("/{lead_id}")
async def update_lead(
    lead_id: str,
    body: LeadUpdateRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    changes = body.model_dump(exclude_none=True)
    if "is_important" in changes:
        # "Active and Important" — the importance flag (doc §4)
        lead.is_important = changes.pop("is_important")
    for field_name, value in changes.items():
        setattr(lead, field_name, value)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="lead.updated",
        entity_type="lead", entity_id=lead_id, detail=changes,
    )
    await db.commit()
    return _lead_dict(lead)


@router.patch("/{lead_id}/state")
async def change_lead_state(
    lead_id: str,
    body: StateChangeRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    # The rules, the history, the closed round and the announcement all live
    # in lead_service.change_state_for_user — Jarvis moves a lead through the
    # very same function (21 Sep 2026).
    lead = await lead_service.change_state_for_user(
        db, ctx, lead_id=lead_id, to_state=body.state, reason=body.reason,
    )
    await db.commit()
    return _lead_dict(lead)


@router.post("/{lead_id}/contacts")
async def add_contact(
    lead_id: str,
    body: ContactRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    # Shared with the assistant: lead_service.add_contact also runs the F41
    # stakeholder backfill and writes the audit row.
    contact = await lead_service.add_contact(
        db, ctx, lead_id=lead_id, name=body.name, title=body.title,
        email=body.email, phone=body.phone, is_primary=body.is_primary,
    )
    await db.commit()
    return {"id": contact.id, "name": contact.name, "email": contact.email,
            "phone": contact.phone, "title": contact.title}


@router.post("/{lead_id}/contacts/from-card")
async def add_contact_from_card(
    lead_id: str,
    file: UploadFile = File(...),
    draft_intro: bool = Form(default=True),
    intro_channel: str = Form(default="email"),
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Business-card photo -> Vision/OCR -> saved contact -> intro message
    drafted from the org template, ready for one-tap approval (doc §9.1)."""
    await lead_service.get_lead(db, ctx.org_id, lead_id)
    image = await file.read()
    if not image:
        raise ValidationFailedError("Empty file")
    if len(image) > 10 * 1024 * 1024:
        raise ValidationFailedError("Card image too large (max 10 MB)")

    card_path = storage.save_bytes(
        ctx.org_id, storage.CATEGORY_CARDS, file.filename or "card.jpg", image
    )
    scan = await vision.read_business_card(
        image, file.content_type or "image/jpeg",
        org_id=ctx.org_id, user_id=ctx.user_id,
    )
    contact = Contact(
        org_id=ctx.org_id,
        lead_id=lead_id,
        name=scan.name or "Unknown (review card)",
        title=scan.title,
        email=scan.email,
        phone=scan.phone,
        source=ContactSource.CARD.value,
        card_image_path=card_path,
        needs_review=scan.needs_review,
        created_by=ctx.user_id,
    )
    db.add(contact)
    await db.flush()
    # Same F41 backfill as the manual route — a scanned card is the other way a
    # person arrives after the project already exists.
    from app.engines import planner_engine

    await planner_engine.backfill_stakeholders_for_contact(
        db, org_id=ctx.org_id, contact=contact
    )
    if contact.email:
        from app.services import meeting_invite_service

        await meeting_invite_service.invite_waiting_meetings(
            db, org_id=ctx.org_id, lead_id=lead_id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="contact.card_scanned",
        entity_type="contact", entity_id=contact.id,
        detail={"confidence": scan.confidence},
    )

    # F38 — the intro is NO LONGER drafted here.
    #
    # This used to be write-then-verify: the contact *and* the intro email were
    # created and committed straight from the OCR result, before any human saw
    # the verify sheet. When the scan misread `mekaghni@` as `mekaghnni@`,
    # correcting the contact fixed the contact and left the queued intro
    # addressed to a dead mailbox — and rejecting it produced a redraft with the
    # same wrong address. There was no path by which a correction could reach it.
    #
    # Per the product owner's decision: the scan proposes, the human edits, and
    # **only the contact's final saved contents count**. So drafting moves to the
    # save (`PATCH /contacts/{id}`), where it reads values a human has confirmed.
    # This dissolves F38 rather than patching it — a corrected address is simply
    # the address the draft is built from.
    #
    # It also strengthens F2's honesty: abandoning the sheet now queues nothing
    # at all, instead of leaving a draft nobody vouched for.
    await db.commit()
    return {
        "contact": {
            "id": contact.id, "name": contact.name, "title": contact.title,
            "email": contact.email, "phone": contact.phone,
            "needs_review": contact.needs_review,
            "confidence": scan.confidence,
            "organisation_on_card": scan.organisation,
        },
        # F38: always null now — nothing is drafted until the human saves. The
        # fields are kept so an older build still parses the response.
        "intro_message": None,
        "intro_error": None,
        # What WILL happen when they save, so the sheet can say so honestly
        # rather than claiming a draft already exists (F2's rule).
        "intro_pending": bool(draft_intro),
        "intro_channel": (
            intro_channel
            if intro_channel in (MessageChannel.EMAIL.value, MessageChannel.WHATSAPP.value)
            else MessageChannel.EMAIL.value
        ),
    }


@router.patch("/contacts/{contact_id}")
async def update_contact(
    contact_id: str,
    body: ContactRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    contact = (
        await db.execute(
            select(Contact).where(Contact.id == contact_id, Contact.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found")
    contact.name = body.name
    contact.title = body.title
    contact.email = body.email
    contact.phone = body.phone
    contact.is_primary = body.is_primary
    contact.needs_review = False  # human just fixed it
    await db.flush()
    if contact.email:
        # An email added later still owes any waiting meeting its invite.
        from app.services import meeting_invite_service

        await meeting_invite_service.invite_waiting_meetings(
            db, org_id=ctx.org_id, lead_id=contact.lead_id)

    # F38 — this is where a card's intro is drafted, from the values the human
    # just confirmed. The scan proposes; the save decides.
    #
    # Guarded three ways so an ordinary contact edit never mails anyone:
    #   * only for contacts that came from a card scan,
    #   * only when no intro has been drafted for them already (so editing the
    #     same contact next month does not queue a second introduction), and
    #   * only when `draft_intro` is on.
    intro_message = None
    intro_error = None
    if body.draft_intro and contact.source == ContactSource.CARD.value:
        already = (
            await db.execute(
                select(func.count(OutboundMessage.id)).where(
                    OutboundMessage.org_id == ctx.org_id,
                    OutboundMessage.contact_id == contact.id,
                    OutboundMessage.kind == MessageKind.INTRO.value,
                )
            )
        ).scalar_one()
        if not already:
            channel = (
                MessageChannel.EMAIL.value if contact.email
                else MessageChannel.WHATSAPP.value
            )
            try:
                message = await intro_service.draft_intro_message(
                    db, ctx, contact=contact, channel=channel
                )
                intro_message = {
                    "message_id": message.id, "channel": message.channel,
                    "to": message.to_address, "subject": message.subject,
                    "body": message.body, "status": message.status,
                }
            except Exception as exc:  # noqa: BLE001 — saving must not fail on the intro
                intro_error = str(exc)

    await db.commit()
    return {
        "id": contact.id, "name": contact.name, "updated": True,
        "intro_message": intro_message, "intro_error": intro_error,
    }


@router.post("/{lead_id}/intelligence")
async def add_intelligence(
    lead_id: str,
    body: IntelligenceRequest,
    ctx: OrgContext = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.get_lead(db, ctx.org_id, lead_id)
    note = ClientIntelligence(
        org_id=ctx.org_id, lead_id=lead_id, note=body.note,
        category=body.category,
        source=body.source if body.source in ("typed", "voice") else "typed",
        added_by=ctx.user_id,
    )
    db.add(note)
    await db.flush()
    await memory_ai.add_memory(
        db, org_id=ctx.org_id, lead_id=lead_id,
        text=f"Note about {lead.name}: {body.note}",
        source_type="note", source_id=note.id,
    )
    await lead_service.touch(db, ctx.org_id, lead_id)
    await db.commit()
    return {"id": note.id, "saved": True}


@router.post("/{lead_id}/consent")
async def record_consent(
    lead_id: str,
    body: ConsentRequest,
    ctx: OrgContext = Depends(require_permission("record_meeting")),
    db: AsyncSession = Depends(get_db),
):
    await lead_service.get_lead(db, ctx.org_id, lead_id)
    consent = ConsentRecord(
        org_id=ctx.org_id, lead_id=lead_id, meeting_id=body.meeting_id,
        method=body.method, note=body.note, captured_by=ctx.user_id,
    )
    db.add(consent)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="consent.recorded",
        entity_type="lead", entity_id=lead_id, detail={"method": body.method},
    )
    await db.commit()
    return {"id": consent.id, "recorded": True}
