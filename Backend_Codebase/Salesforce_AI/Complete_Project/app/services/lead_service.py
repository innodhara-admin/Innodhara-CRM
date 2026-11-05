"""Lead lifecycle: state machine, history, suggestions (doc §4)."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LEAD_STATE_TRANSITIONS, ContactSource, LeadState
from app.core.context import OrgContext
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models.base import utcnow
from app.models.lead import Contact, Lead, LeadStateHistory
from app.services import audit_service


def normalise_name(name: str | None) -> str:
    """A client name as the duplicate rule compares it: case and spacing ignored."""
    return " ".join((name or "").split()).casefold()


async def same_name_lead(db: AsyncSession, org_id: str, name: str) -> Lead | None:
    """The client already on file under exactly this name (case and extra
    spaces ignored), or None. Near spellings are not this: Jarvis asks about
    those, because two similar names can be two real clients."""
    from sqlalchemy import func  # noqa: PLC0415

    wanted = normalise_name(name)
    if not wanted:
        return None
    first = wanted.split()[0].replace("%", "").replace("_", "")
    rows = (
        await db.execute(
            select(Lead).where(Lead.org_id == org_id,
                               func.lower(Lead.name).like(f"%{first}%"))
            .order_by(Lead.created_at)
        )
    ).scalars().all()
    return next((lead for lead in rows if normalise_name(lead.name) == wanted), None)


async def duplicate_name_message(db: AsyncSession, lead: Lead) -> str:
    from app.models.user import User  # noqa: PLC0415

    owner = None
    if lead.owner_id:
        owner = (await db.execute(select(User.name).where(User.id == lead.owner_id))
                 ).scalar_one_or_none()
    state = lead.state.replace("_", " ")
    about = f"{lead.name} is already on file ({state}" + (f", owned by {owner})." if owner else ").")
    return (f"{about} Two clients cannot have the same name. Open that one instead, "
            "or use a name that tells them apart, for example with the city.")


async def refuse_duplicate_name(db: AsyncSession, org_id: str, name: str) -> None:
    """No two clients with the same name in one organisation (26 Sep 2026:
    the live org had two "Abc School" and two "Xavier School")."""
    existing = await same_name_lead(db, org_id, name)
    if existing is not None:
        import logging  # noqa: PLC0415

        logging.getLogger(__name__).info(
            "Duplicate client name refused: %r (on file as %s)", name, existing.id)
        raise ConflictError(await duplicate_name_message(db, existing))


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def looks_like_email(value: str | None) -> bool:
    """An address that can be sent to: something@something.something, no spaces."""
    return bool(value) and _EMAIL_RE.match(value.strip()) is not None


def check_open_contact(contact: dict | None) -> dict:
    """The contact a lead opened straight away must have (7 Oct 2026): a name,
    a designation and an email address; the phone is optional. Returns it
    cleaned; refuses with the first thing missing."""
    def clean(key: str) -> str | None:
        text = " ".join(str((contact or {}).get(key) or "").split())
        return text or None

    if not contact:
        raise ValidationFailedError(
            "To open a lead straight away, add the contact at the client: their "
            "name, designation and email address.")
    out = {"name": clean("name"), "title": clean("title"),
           "email": clean("email"), "phone": clean("phone")}
    if not out["name"]:
        raise ValidationFailedError(
            "The contact's name is required to open a lead straight away.")
    if not out["title"]:
        raise ValidationFailedError(
            "The contact's designation is required to open a lead straight away.")
    if not out["email"]:
        raise ValidationFailedError(
            "The contact's email address is required to open a lead straight away.")
    if not looks_like_email(out["email"]):
        raise ValidationFailedError(f"'{out['email']}' doesn't look like an email address.")
    out["email"] = out["email"].lower()
    return out


async def create_lead(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    name: str,
    owner_id: str | None = None,
    address: str | None = None,
    city: str | None = None,
    region: str | None = None,
    website: str | None = None,
    source: str | None = None,
    notes: str | None = None,
    audit_detail: dict | None = None,
) -> tuple[Lead, str]:
    """Create a lead in pre-sales, owned by `owner_id` (the creator when None).

    The one path a lead is created by: `POST /leads` and the assistant's
    confirmed "create this client" both come here, so an owner check, a
    history row, an audit row or a notification cannot exist on one and be
    missing on the other. Returns the lead and the owner's display name.
    Does not commit — the caller owns the transaction.
    """
    from app.models.user import User  # noqa: PLC0415
    from app.services import notification_service  # noqa: PLC0415

    await refuse_duplicate_name(db, ctx.org_id, name)
    owner_id = owner_id or ctx.user_id
    owner_name = ctx.name or ctx.email
    if owner_id != ctx.user_id:
        # An owner named by the client is checked against this org before it is
        # written: `owner_id` is a plain string on the wire, and an unchecked
        # one would silently hand a lead to a stranger — or to nobody, leaving
        # it unopenable, since only the owner may leave COLD_CALLING.
        #
        # The role is deliberately NOT constrained here. The picker offers
        # sales agents only, but the fallback above assigns the creator, who
        # is often a sales lead; rejecting that role would make a lead created
        # without an explicit owner impossible.
        owner = (
            await db.execute(
                select(User).where(
                    User.id == owner_id,
                    User.org_id == ctx.org_id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if owner is None:
            raise ValidationFailedError(
                "That owner is not an active member of your organisation"
            )
        owner_name = owner.name or owner.email

    lead = Lead(
        org_id=ctx.org_id,
        name=name,
        # Pre-sales entry. A lead is a name and a phone number until someone
        # has actually called; the established flow begins at OPEN.
        state=LeadState.COLD_CALLING.value,
        owner_id=owner_id,
        address=address,
        city=city,
        region=region,
        website=website,
        source=source,
        notes=notes,
    )
    db.add(lead)
    await db.flush()
    db.add(
        LeadStateHistory(
            org_id=ctx.org_id, lead_id=lead.id, from_state=None,
            to_state=LeadState.COLD_CALLING.value,
            reason=f"Assigned to {owner_name} by {ctx.name or ctx.email}",
            changed_by=ctx.user_id,
        )
    )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="lead.created",
        entity_type="lead", entity_id=lead.id,
        detail={"name": lead.name, "owner_id": owner_id, **(audit_detail or {})},
    )
    if owner_id != ctx.user_id:
        # Assigning work to yourself is not news; assigning it to someone else is.
        await notification_service.notify(
            db, org_id=ctx.org_id, user_id=owner_id,
            title=f"You own {lead.name}",
            body=f"{ctx.name or ctx.email} assigned this lead to you — start cold calling.",
            kind="lead_assigned", entity_type="lead", entity_id=lead.id,
        )
    return lead, owner_name


async def create_open_lead(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    name: str,
    contact: dict | None,
    address: str | None = None,
    city: str | None = None,
    region: str | None = None,
    website: str | None = None,
    source: str | None = None,
    notes: str | None = None,
    audit_detail: dict | None = None,
) -> tuple[Lead, Contact]:
    """A sales lead creates a lead that is already open (7 Oct 2026).

    The same steps as a lead created and later opened by its owner, in one
    transaction: the cold-calling history row, the contact (added by the
    sales lead, who owns the lead), the move to open and the announcement.
    The Home "recently opened" card finds a lead by that cold_calling -> open
    history row, so the lead is never inserted as open directly.

    Every refusal (role, contact, duplicate name) happens before the first
    write. Does not commit -- the caller owns the transaction.
    """
    from app.core.constants import Role  # noqa: PLC0415

    if ctx.role != Role.SALES_LEAD.value:
        raise PermissionDeniedError(
            "Only a sales lead can open a lead straight away. Create it in cold "
            "calling instead.")
    person = check_open_contact(contact)
    lead, _owner_name = await create_lead(
        db, ctx, name=name, owner_id=ctx.user_id, address=address, city=city,
        region=region, website=website, source=source, notes=notes,
        audit_detail={"opened_at_creation": True, **(audit_detail or {})},
    )
    saved = await add_contact(
        db, ctx, lead_id=lead.id, name=person["name"], title=person["title"],
        email=person["email"], phone=person["phone"], is_primary=True,
    )
    reason = f"Opened at creation by {ctx.name or ctx.email}; contact {saved.name}"
    lead = await change_state(
        db, org_id=ctx.org_id, lead_id=lead.id, to_state=LeadState.OPEN.value,
        changed_by=ctx.user_id, reason=reason,
    )
    await _announce_open(db, ctx, lead, reason)
    return lead, saved


async def add_contact(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    lead_id: str,
    name: str,
    title: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    is_primary: bool = False,
) -> Contact:
    """Save a contact typed in by a person (not scanned from a card).

    Shared by `POST /leads/{id}/contacts` and the assistant, for the same
    reason as `create_lead`. Does not commit.
    """
    from app.engines import planner_engine  # noqa: PLC0415

    await get_lead(db, ctx.org_id, lead_id)
    contact = Contact(
        org_id=ctx.org_id, lead_id=lead_id, name=name, title=title,
        email=email, phone=phone, is_primary=is_primary,
        source=ContactSource.MANUAL.value, created_by=ctx.user_id,
    )
    db.add(contact)
    await db.flush()
    # F41 consequence #4: the stakeholder loop runs once, at project creation, so
    # a contact added by hand afterwards used to create no stakeholder row at all
    # — the project stayed unreachable no matter how many people you entered.
    await planner_engine.backfill_stakeholders_for_contact(
        db, org_id=ctx.org_id, contact=contact
    )
    if email:
        # A meeting scheduled before the client had an email contact is still
        # waiting for its invite (2026-09-23).
        from app.services import meeting_invite_service  # noqa: PLC0415

        await meeting_invite_service.invite_waiting_meetings(
            db, org_id=ctx.org_id, lead_id=lead_id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="contact.added",
        entity_type="lead", entity_id=lead_id,
    )
    return contact


async def get_lead(db: AsyncSession, org_id: str, lead_id: str) -> Lead:
    lead = (
        await db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id)
        )
    ).scalar_one_or_none()
    if lead is None:
        raise NotFoundError("Lead not found")
    return lead


async def get_workable_lead(db: AsyncSession, org_id: str, lead_id: str) -> Lead:
    """`get_lead`, refusing a lead that is still in pre-sales.

    A meeting with a school nobody has phoned yet is not a thing that happens,
    so the API says so rather than accepting work that would strand the lead:
    recording a meeting does not move a lead out of COLD_CALLING, only its
    owner does, and the resulting meeting would sit against a lead the rest of
    the team cannot see as live.

    Safe by construction for existing data — no lead reaches COLD_CALLING
    except through `POST /leads` after this change.
    """
    lead = await get_lead(db, org_id, lead_id)
    if lead.state == LeadState.COLD_CALLING.value:
        raise ValidationFailedError(
            f"'{lead.name}' is still in cold calling. Its owner has to open "
            f"the lead before meetings can be booked or recorded against it."
        )
    return lead


def has_been_opened(lead: Lead) -> bool:
    """False while the lead is still in cold calling.

    "Open" here means "reached OPEN or anything after it": an ACTIVE lead is
    past open, not short of it. A lead only ever enters COLD_CALLING when it
    is created, so the state alone answers the question.
    """
    return lead.state != LeadState.COLD_CALLING.value


def ensure_opened(lead: Lead, action: str) -> None:
    """Refuse to let Jarvis create sales work for a lead still in cold calling.

    `action` completes "therefore ... is not allowed" -- e.g. "scheduling a
    meeting". Notes, contacts, tasks and follow-ups are deliberately not gated:
    they are what cold calling itself produces.
    """
    from app.core.exceptions import LeadNotOpenError  # noqa: PLC0415

    if not has_been_opened(lead):
        raise LeadNotOpenError(
            f"{lead.name} is not in open state yet, therefore {action} is not "
            f"allowed. Its owner has to move it from cold calling to open first."
        )


def _reachable(contact: Contact) -> bool:
    return bool((contact.email or "").strip() or (contact.phone or "").strip())


async def open_blocker(
    db: AsyncSession, lead: Lead, viewer_id: str | None = None
) -> str | None:
    """Why this lead cannot be moved from cold calling to open yet, or None.

    The rule: at least one contact at the client, added by the lead's owner,
    with a phone number or an email address. The owner made the calls, so a
    contact someone else entered -- or one the meeting pipeline found in a
    transcript, which never has either -- does not show that they reached
    anyone. Asked of the CURRENT owner: when a lead is reassigned, the new
    owner has to have reached someone too.
    """
    if lead.state != LeadState.COLD_CALLING.value:
        return None
    contacts = (
        await db.execute(
            select(Contact).where(
                Contact.org_id == lead.org_id,
                Contact.lead_id == lead.id,
                Contact.created_by == lead.owner_id,
            )
        )
    ).scalars().all()
    if lead.owner_id and any(_reachable(c) for c in contacts):
        return None
    if lead.owner_id and viewer_id == lead.owner_id:
        return (
            f"{lead.name} can't be opened yet. Add at least one contact with a "
            f"phone number or an email address first."
        )
    owner_name = await _user_name(db, lead.org_id, lead.owner_id)
    return (
        f"{lead.name} can't be opened yet. Its owner, {owner_name}, has to add "
        f"at least one contact with a phone number or an email address first."
    )


async def change_state(
    db: AsyncSession,
    *,
    org_id: str,
    lead_id: str,
    to_state: str,
    changed_by: str,
    reason: str | None = None,
    force: bool = False,
) -> Lead:
    """Move a lead through the state diagram, recording history."""
    lead = await get_lead(db, org_id, lead_id)
    try:
        target = LeadState(to_state)
    except ValueError:
        raise ValidationFailedError(f"Unknown lead state '{to_state}'")

    current = LeadState(lead.state)
    if target == current:
        return lead
    if not force and target not in LEAD_STATE_TRANSITIONS.get(current, set()):
        allowed = ", ".join(s.value for s in LEAD_STATE_TRANSITIONS.get(current, set()))
        raise ValidationFailedError(
            f"Cannot move lead from '{current.value}' to '{target.value}'. Allowed: {allowed}"
        )

    db.add(
        LeadStateHistory(
            org_id=org_id,
            lead_id=lead.id,
            from_state=current.value,
            to_state=target.value,
            reason=reason,
            changed_by=changed_by,
        )
    )
    lead.state = target.value
    lead.suggested_state = None
    lead.suggested_state_reason = None
    lead.last_activity_at = utcnow()
    await audit_service.record(
        db,
        org_id=org_id,
        user_id=None if changed_by == "system" else changed_by,
        action="lead.state_changed",
        entity_type="lead",
        entity_id=lead.id,
        detail={"from": current.value, "to": target.value, "reason": reason},
    )
    return lead


async def change_state_for_user(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    lead_id: str,
    to_state: str,
    reason: str | None = None,
) -> Lead:
    """Move a lead the way a person moves it: who may, the history row, the
    round that ends, and the sales floor hearing that a lead is now open.

    The one path a person's state change takes: `PATCH /leads/{id}/state` and
    Jarvis's `move_client_state` both come here, so the pre-sales rule cannot
    hold on one and be missing on the other. Does not commit — the caller owns
    the transaction.
    """
    from app.core.permissions import (  # noqa: PLC0415
        can_change_lead_state,
        can_leave_cold_calling,
    )

    # Read the lead before the move so the pre-sales question is asked of the
    # state it is actually in.
    before = await get_lead(db, ctx.org_id, lead_id)
    leaving_pre_sales = before.state == LeadState.COLD_CALLING.value
    if leaving_pre_sales and not can_leave_cold_calling(
        ctx.role, ctx.user_id, before.owner_id
    ):
        owner_name = await _user_name(db, ctx.org_id, before.owner_id)
        raise PermissionDeniedError(
            f"Only {owner_name} owns this lead and can take it out of cold "
            f"calling. Reassign the owner first if that needs to change."
        )
    # Every move from OPEN onward: the owner drives their own lead, a sales
    # lead drives any of them. `manage_leads` on its own let one agent close
    # another agent's deal, which is a reporting problem before it is a
    # permissions one -- `closed` is what the numbers count.
    if not leaving_pre_sales and not can_change_lead_state(
        ctx.role, ctx.user_id, before.owner_id
    ):
        owner_name = await _user_name(db, ctx.org_id, before.owner_id)
        raise PermissionDeniedError(
            f"This lead belongs to {owner_name}. Its owner or a sales lead "
            f"can change its state."
        )

    # Opening needs proof the owner reached someone: a contact they added with
    # a phone or an email. Asked of everyone, the org admin's break-glass
    # included -- it is a fact about the lead, not about who is asking.
    if leaving_pre_sales and to_state == LeadState.OPEN.value:
        blocker = await open_blocker(db, before, viewer_id=ctx.user_id)
        if blocker:
            raise ValidationFailedError(blocker)

    lead = await change_state(
        db, org_id=ctx.org_id, lead_id=lead_id, to_state=to_state,
        changed_by=ctx.user_id, reason=reason,
    )
    # A lead reaching a terminal state means this ROUND is over. Recorded here,
    # in the one place that moves leads, rather than by an engine reacting to
    # an event — the lifecycle stays something people drive.
    await _close_running_cycle(db, ctx.org_id, lead)

    if leaving_pre_sales and lead.state == LeadState.OPEN.value:
        # A lead becoming real is news for the whole sales floor, not just its
        # owner: anyone may be the one who ends up visiting the school.
        await _announce_open(db, ctx, lead, reason)
    return lead


async def _close_running_cycle(db: AsyncSession, org_id: str, lead: Lead) -> None:
    """Mark the open round finished when the lead reaches a terminal state.

    A no-op for the vast majority of leads, which have no cycle rows at all —
    those are only written once a client comes back for a second round. This
    exists so that a client on their third round has an honest record of how
    the second one ended.
    """
    from app.core.constants import CycleOutcome  # noqa: PLC0415
    from app.models.relationship import LeadCycle  # noqa: PLC0415

    terminal = {
        LeadState.CLOSED.value: CycleOutcome.CLOSED.value,
        LeadState.LOST_FOR_NOW.value: CycleOutcome.LOST_FOR_NOW.value,
    }
    outcome = terminal.get(lead.state)
    if outcome is None:
        return
    cycle = (
        await db.execute(
            select(LeadCycle)
            .where(
                LeadCycle.org_id == org_id,
                LeadCycle.lead_id == lead.id,
                LeadCycle.outcome == CycleOutcome.RUNNING.value,
            )
            .order_by(LeadCycle.cycle_number.desc())
        )
    ).scalars().first()
    if cycle is None:
        return
    cycle.outcome = outcome
    cycle.closed_at = utcnow()


async def _user_name(db: AsyncSession, org_id: str, user_id: str | None) -> str:
    """A name for a message, never an exception. Falls back to something a
    person can still act on when the row is missing or nameless."""
    from app.models.user import User  # noqa: PLC0415

    if not user_id:
        return "nobody (this lead has no owner)"
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.org_id == org_id)
        )
    ).scalar_one_or_none()
    if user is None:
        return "its owner"
    return user.name or user.email


async def _announce_open(
    db: AsyncSession, ctx: OrgContext, lead: Lead, reason: str | None
) -> None:
    """Tell every sales agent and sales lead that a lead is now workable.

    Deliberately a plain loop: an org's sales floor is tens of people, and the
    notification service already hands the push off fire-and-forget.
    """
    from app.core.constants import Role  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415
    from app.services import notification_service  # noqa: PLC0415

    recipients = (
        await db.execute(
            select(User).where(
                User.org_id == ctx.org_id,
                User.is_active.is_(True),
                User.role.in_([Role.SALES_AGENT.value, Role.SALES_LEAD.value]),
                User.id != ctx.user_id,        # the opener already knows
            )
        )
    ).scalars().all()
    opener = ctx.name or ctx.email
    body = f"{opener}: {reason}" if reason else f"Opened by {opener}."
    for user in recipients:
        await notification_service.notify(
            db, org_id=ctx.org_id, user_id=user.id,
            title=f"{lead.name} is now open",
            body=body, kind="lead_opened",
            entity_type="lead", entity_id=lead.id,
        )


async def apply_suggestion(
    db: AsyncSession,
    *,
    org_id: str,
    lead: Lead,
    to_state: str,
    reason: str,
    engine: str,
    confidence: float = 0.8,
    input_summary: str | None = None,
) -> None:
    """The ONE way a lead-state suggestion is written — and the reason it is
    written here rather than by each caller assigning the two fields.

    The suggestion banner in the app offers a **Why?** button, which reads
    `ai_decisions` for (entity_type='lead', entity_id=lead.id). Every producer
    of a suggestion used to set `suggested_state`/`suggested_state_reason`
    directly and record nothing, so `ai_decisions` held 0 rows and the button
    could only ever answer "No AI decision is recorded for this record"
    (finding F10) — an affordance the backend never honoured.
    """
    from app.core.constants import DecisionType
    from app.engines.common import record_decision

    lead.suggested_state = to_state
    lead.suggested_state_reason = reason
    await record_decision(
        db,
        org_id=org_id,
        decision_type=DecisionType.STATE_CHANGE.value,
        engine=engine,
        input_summary=input_summary,
        decision=f"Suggested moving '{lead.name}' from {lead.state} to {to_state}",
        reason=reason,
        confidence=confidence,
        needs_human=True,          # a suggestion is, by definition, awaiting a person
        entity_type="lead",
        entity_id=lead.id,
    )


async def suggest_state(
    db: AsyncSession,
    *,
    org_id: str,
    lead_id: str,
    to_state: str,
    reason: str,
    engine: str = "lead_service",
    confidence: float = 0.8,
    input_summary: str | None = None,
) -> Lead:
    """System proposes a move (e.g. Open -> Active after a real discussion);
    a human confirms via the state endpoint (doc §4.1)."""
    lead = await get_lead(db, org_id, lead_id)
    current = LeadState(lead.state)
    try:
        target = LeadState(to_state)
    except ValueError:
        return lead
    if target != current and target in LEAD_STATE_TRANSITIONS.get(current, set()):
        await apply_suggestion(
            db, org_id=org_id, lead=lead, to_state=target.value, reason=reason,
            engine=engine, confidence=confidence, input_summary=input_summary,
        )
    return lead


async def touch(db: AsyncSession, org_id: str, lead_id: str) -> None:
    lead = (
        await db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id)
        )
    ).scalar_one_or_none()
    if lead is not None:
        lead.last_activity_at = utcnow()
