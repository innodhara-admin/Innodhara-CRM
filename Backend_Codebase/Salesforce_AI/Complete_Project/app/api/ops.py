"""Operations API: invoices & payments, vendors, leave & bookings,
deliverables (incl. manual upload), playbooks & suggestions."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.constants import (
    ApprovalEntityType,
    DeliverableSource,
    EventType,
    InvoiceStatus,
    MessageKind,
    Role,
)
from app.core.context import OrgContext
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.database import get_db
from app.engines import (
    communication_engine,
    document_engine,
    events,
    resource_engine,
)
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.finance import Deliverable, Invoice, Vendor
from app.models.lead import Contact
from app.models.project import Playbook, PlaybookSuggestion, Project, Stakeholder
from app.models.resource import ResourceBooking
from app.models.user import User
from app.services import audit_service

router = APIRouter(tags=["operations"])


# ─────────────────────────────────────────────────────────────────────────────
# Invoices & payments
# ─────────────────────────────────────────────────────────────────────────────


class InvoiceRequest(BaseModel):
    project_id: str
    kind: str = "full"  # advance | balance | full
    advance_pct: float = 50.0
    due_in_days: int = 14
    sent_to_stakeholder_id: str | None = None


@router.post("/invoices")
async def create_invoice(
    body: InvoiceRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Amounts always derived from accepted proposals — never typed."""
    project = (
        await db.execute(
            select(Project).where(
                Project.org_id == ctx.org_id, Project.id == body.project_id
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found")
    stakeholder_id = body.sent_to_stakeholder_id
    if stakeholder_id is None:
        # Default: the payments gatekeeper (accountant), not the principal.
        gatekeeper = (
            await db.execute(
                select(Stakeholder).where(
                    Stakeholder.project_id == project.id,
                    Stakeholder.influence == "gatekeeper",
                )
            )
        ).scalars().first()
        if gatekeeper is not None:
            stakeholder_id = gatekeeper.id
    invoice = await document_engine.create_invoice(
        db, org_id=ctx.org_id, project=project, kind=body.kind,
        advance_pct=body.advance_pct, due_in_days=body.due_in_days,
        sent_to_stakeholder_id=stakeholder_id,
    )
    await db.commit()
    return {
        "id": invoice.id, "amount": invoice.amount, "kind": invoice.kind,
        "computation": invoice.computation, "status": invoice.status,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "sent_to_stakeholder_id": invoice.sent_to_stakeholder_id,
    }


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(
    invoice_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Draft the carrying email to the gatekeeper (CC the principal) and put
    it through the approval gate (Workflow 8.3)."""
    invoice = (
        await db.execute(
            select(Invoice).where(Invoice.org_id == ctx.org_id, Invoice.id == invoice_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice not found")
    project = (
        await db.execute(select(Project).where(Project.id == invoice.project_id))
    ).scalar_one()
    stakeholder = None
    if invoice.sent_to_stakeholder_id:
        stakeholder = (
            await db.execute(
                select(Stakeholder).where(Stakeholder.id == invoice.sent_to_stakeholder_id)
            )
        ).scalar_one_or_none()
    if stakeholder is None:
        raise ValidationFailedError(
            "No payments gatekeeper recorded — add the accountant as a "
            "stakeholder first (the invoice never goes blindly to the principal)"
        )
    contact = (
        await db.execute(select(Contact).where(Contact.id == stakeholder.contact_id))
    ).scalar_one()
    # CC the client's decision maker — whatever their title is, money mail
    # is copied, not addressed, to whoever holds final say.
    cc: list[str] = []
    decision_maker = (
        await db.execute(
            select(Stakeholder)
            .where(
                Stakeholder.project_id == project.id,
                Stakeholder.influence == "decision_maker",
                Stakeholder.id != stakeholder.id,
            )
            # F55: `.first()` over an unordered set picked an ARBITRARY decision
            # maker, and a project can hold more than one — Round 7 ended with a
            # second campus's head attached as a `decision_maker` on the wrong
            # project. Whoever this resolves to gets CC'd on an invoice, so the
            # pick has to be stable and defensible.
            #
            # Oldest first: the decision maker this project has known longest.
            # A person attached later (the F55 case) can no longer displace the
            # original one just because a query came back in a different order.
            .order_by(Stakeholder.created_at, Stakeholder.id)
        )
    ).scalars().first()
    if decision_maker is not None:
        p_contact = (
            await db.execute(
                select(Contact).where(Contact.id == decision_maker.contact_id)
            )
        ).scalar_one_or_none()
        if p_contact is not None and p_contact.email and p_contact.email != contact.email:
            cc.append(p_contact.email)

    message, approval, _unc = await communication_engine.draft_client_message(
        db, org_id=ctx.org_id, kind=MessageKind.INVOICE.value,
        purpose=f"send {invoice.kind} invoice",
        lead_id=project.lead_id, contact=contact, project=project,
        stakeholder=stakeholder,
        subject=f"{project.name} — {invoice.kind} invoice",
        cc=cc,
        instruction="The invoice with its computation shown plainly.",
        facts={
            "amount": f"{invoice.amount:,.0f} {invoice.currency}",
            "due_date": f"{invoice.due_date:%d %b %Y}" if invoice.due_date else "on receipt",
            "computation": invoice.computation or "",
        },
        triggered_by="manual",
        approval_facts={"amount": invoice.amount},
    )
    invoice.status = InvoiceStatus.SENT.value
    invoice.sent_at = utcnow()
    invoice.sent_message_id = message.id if message else None
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.INVOICE_SENT.value,
        project_id=project.id, entity_type="invoice", entity_id=invoice.id,
        actor=ctx.user_id, details={"amount": invoice.amount},
    )
    await db.commit()
    return {
        "ok": True,
        "message_id": message.id if message else None,
        "approval_id": approval.id if approval else None,
    }


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0)
    method: str | None = None
    note: str | None = None
    received_on: datetime | None = None


@router.post("/invoices/{invoice_id}/record-payment")
async def record_payment(
    invoice_id: str,
    body: PaymentRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    invoice = (
        await db.execute(
            select(Invoice).where(Invoice.org_id == ctx.org_id, Invoice.id == invoice_id)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise NotFoundError("Invoice not found")
    payment = await document_engine.record_payment(
        db, org_id=ctx.org_id, invoice=invoice, amount=body.amount,
        method=body.method, recorded_by=ctx.user_id, note=body.note,
        received_on=body.received_on,
    )
    await db.commit()
    return {"payment_id": payment.id, "invoice_status": invoice.status}


@router.get("/invoices")
async def list_invoices(
    project_id: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invoice).where(Invoice.org_id == ctx.org_id)
    if project_id:
        stmt = stmt.where(Invoice.project_id == project_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": i.id, "project_id": i.project_id, "kind": i.kind,
            "amount": i.amount, "status": i.status,
            "computation": i.computation,
            "due_date": i.due_date.isoformat() if i.due_date else None,
        }
        for i in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Vendors
# ─────────────────────────────────────────────────────────────────────────────


class VendorRequest(BaseModel):
    name: str
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    category: str | None = None
    notes: str | None = None


@router.post("/vendors")
async def create_vendor(
    body: VendorRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    vendor = Vendor(org_id=ctx.org_id, **body.model_dump())
    db.add(vendor)
    await db.commit()
    return {"id": vendor.id, "name": vendor.name}


@router.get("/vendors")
async def list_vendors(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(Vendor).where(Vendor.org_id == ctx.org_id))
    ).scalars().all()
    return [
        {
            "id": v.id,
            "name": v.name,
            "contact_name": v.contact_name,
            "phone": v.phone,
            "email": v.email,
            "category": v.category,
            "notes": v.notes,
        }
        for v in rows
    ]


@router.delete("/vendors/{vendor_id}")
async def delete_vendor(
    vendor_id: str,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Nothing in the schema references a vendor row: no foreign key, no
    id-shaped column anywhere points at `vendors.id`. The only place a vendor
    is ever recorded outside its own table is `action_items.external_wait`,
    a free-text JSON blob written by `POST /tasks/{id}/vendor-promise`
    (`app/api/workflow.py`) as `{"vendor_name": <typed string>, ...}` — a
    name, not a reference. Deleting a vendor therefore cannot orphan
    anything: the vendor list is a catalogue, and a task's recorded promise
    keeps its typed name, independent of whether that row still exists."""
    row = (
        await db.execute(
            select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Vendor not found")

    await db.delete(row)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="ops.vendor_deleted",
        entity_type="vendor", entity_id=vendor_id, detail={"name": row.name},
    )
    await db.commit()
    return {"deleted": True}


# ─────────────────────────────────────────────────────────────────────────────
# Leave & bookings
# ─────────────────────────────────────────────────────────────────────────────


class LeaveRequest(BaseModel):
    user_id: str
    leave_from: date
    leave_to: date


@router.post("/leave")
async def record_leave(
    body: LeaveRequest,
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    """Recording leave triggers the automatic endangered-task check
    (Workflow 12)."""
    user = (
        await db.execute(
            select(User).where(User.org_id == ctx.org_id, User.id == body.user_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    if body.leave_to < body.leave_from:
        raise ValidationFailedError("leave_to is before leave_from")
    await resource_engine.record_leave(
        db, org_id=ctx.org_id, user=user,
        leave_from=body.leave_from, leave_to=body.leave_to,
    )
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.LEAVE_RECORDED.value,
        entity_type="user", entity_id=user.id, actor=ctx.user_id,
        details={"from": body.leave_from.isoformat(), "to": body.leave_to.isoformat()},
    )
    await db.commit()
    return {"ok": True, "note": "tasks due in the window are being cross-checked"}


class BookingRequest(BaseModel):
    user_id: str
    kind: str  # delivery | demo | travel | hold
    date_from: date
    date_to: date
    project_id: str | None = None
    note: str | None = None


@router.post("/bookings")
async def create_booking(
    body: BookingRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    booking = await resource_engine.book(
        db, org_id=ctx.org_id, user_id=body.user_id, kind=body.kind,
        date_from=body.date_from, date_to=body.date_to,
        project_id=body.project_id, source_type="hold", source=ctx.user_id,
        note=body.note,
    )
    await db.commit()
    return {"id": booking.id}


@router.get("/bookings")
async def list_bookings(
    user_id: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ResourceBooking).where(ResourceBooking.org_id == ctx.org_id)
    if user_id:
        stmt = stmt.where(ResourceBooking.user_id == user_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": b.id, "user_id": b.user_id, "kind": b.kind,
            "from": b.date_from.isoformat(), "to": b.date_to.isoformat(),
            "project_id": b.project_id, "note": b.note,
        }
        for b in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Deliverables (incl. the manual-upload path)
# ─────────────────────────────────────────────────────────────────────────────


class DeliverableRequest(BaseModel):
    project_id: str
    type: str
    title: str | None = None
    content_md: str | None = None
    file_path: str | None = None
    source: str = DeliverableSource.MANUAL_UPLOAD.value
    linked_action_item_id: str | None = None


@router.post("/deliverables")
async def add_deliverable(
    body: DeliverableRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """An uploaded file is a fully valid way to finish any task — the rest of
    the machine treats it exactly like a generated one."""
    deliverable = await document_engine.add_deliverable(
        db, org_id=ctx.org_id, project_id=body.project_id, dtype=body.type,
        title=body.title, content_md=body.content_md, file_path=body.file_path,
        source=body.source, uploaded_by=ctx.user_id,
        linked_action_item_id=body.linked_action_item_id,
        status="internal_review",
    )
    await db.commit()
    return {"id": deliverable.id, "version": deliverable.version}


@router.get("/deliverables")
async def list_deliverables(
    project_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Deliverable).where(
                Deliverable.org_id == ctx.org_id,
                Deliverable.project_id == project_id,
            ).order_by(Deliverable.type, Deliverable.version)
        )
    ).scalars().all()
    return [
        {
            "id": d.id, "type": d.type, "title": d.title, "version": d.version,
            "source": d.source, "status": d.status,
            "linked_action_item_id": d.linked_action_item_id,
        }
        for d in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Playbooks & suggestions
# ─────────────────────────────────────────────────────────────────────────────


class PlaybookRequest(BaseModel):
    program_id: str
    phase: str
    entries: list[dict]


@router.post("/playbooks")
async def upsert_playbook(
    body: PlaybookRequest,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    """New version per change — plans record which version generated them."""
    current = (
        await db.execute(
            select(Playbook).where(
                Playbook.org_id == ctx.org_id,
                Playbook.program_id == body.program_id,
                Playbook.phase == body.phase,
                Playbook.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    version = 1
    if current is not None:
        current.is_current = False
        version = current.version + 1
    playbook = Playbook(
        org_id=ctx.org_id, program_id=body.program_id, phase=body.phase,
        entries=body.entries, version=version, is_current=True,
        updated_by=ctx.user_id,
    )
    db.add(playbook)
    await db.commit()
    return {"id": playbook.id, "version": version}


@router.get("/playbooks")
async def list_playbooks(
    program_id: str | None = None,
    phase: str | None = None,
    current_only: bool = True,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """A go-live prerequisite that had a write path and no read path: without
    this a console can only overwrite task waves blindly."""
    stmt = select(Playbook).where(Playbook.org_id == ctx.org_id)
    if program_id:
        stmt = stmt.where(Playbook.program_id == program_id)
    if phase:
        stmt = stmt.where(Playbook.phase == phase)
    if current_only:
        stmt = stmt.where(Playbook.is_current.is_(True))
    rows = (
        await db.execute(stmt.order_by(Playbook.phase, Playbook.version))
    ).scalars().all()
    return [
        {
            "id": p.id,
            "program_id": p.program_id,
            "phase": p.phase,
            "entries": p.entries,
            "version": p.version,
            "is_current": p.is_current,
            "updated_by": p.updated_by,
        }
        for p in rows
    ]


@router.delete("/playbooks/{playbook_id}")
async def delete_playbook(
    playbook_id: str,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    """Nothing references a playbook, so there is no reference guard. Removing
    the current version promotes its predecessor — the un-supersede path the
    API has never had."""
    row = (
        await db.execute(
            select(Playbook).where(
                Playbook.id == playbook_id, Playbook.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Playbook not found")

    was_current, program_id, phase = row.is_current, row.program_id, row.phase
    await db.delete(row)
    await db.flush()

    if was_current:
        predecessor = (
            await db.execute(
                select(Playbook)
                .where(
                    Playbook.org_id == ctx.org_id,
                    Playbook.program_id == program_id,
                    Playbook.phase == phase,
                )
                .order_by(Playbook.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if predecessor is not None:
            predecessor.is_current = True

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="ops.playbook_deleted",
        entity_type="playbook", entity_id=playbook_id,
        detail={"program_id": program_id, "phase": phase},
    )
    await db.commit()
    return {"deleted": True}


@router.get("/playbooks/suggestions")
async def list_suggestions(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(PlaybookSuggestion).where(
                PlaybookSuggestion.org_id == ctx.org_id,
                PlaybookSuggestion.status == "pending",
            )
        )
    ).scalars().all()
    return [
        {
            "id": s.id, "program_id": s.program_id, "phase": s.phase,
            "entry": s.entry, "reason": s.reason,
        }
        for s in rows
    ]


class SuggestionDecision(BaseModel):
    accept: bool


@router.post("/playbooks/suggestions/{suggestion_id}/decide")
async def decide_suggestion(
    suggestion_id: str,
    body: SuggestionDecision,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    """The one-tap accept: every future project inherits the lesson
    (Workflow 22.5)."""
    suggestion = (
        await db.execute(
            select(PlaybookSuggestion).where(
                PlaybookSuggestion.org_id == ctx.org_id,
                PlaybookSuggestion.id == suggestion_id,
            )
        )
    ).scalar_one_or_none()
    if suggestion is None:
        raise NotFoundError("Suggestion not found")
    suggestion.status = "accepted" if body.accept else "rejected"
    suggestion.decided_by = ctx.user_id
    suggestion.decided_at = utcnow()
    if body.accept:
        current = (
            await db.execute(
                select(Playbook).where(
                    Playbook.org_id == ctx.org_id,
                    Playbook.program_id == suggestion.program_id,
                    Playbook.phase == suggestion.phase,
                    Playbook.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        entries = list(current.entries or []) if current else []
        entries.append(suggestion.entry)
        version = (current.version + 1) if current else 1
        if current is not None:
            current.is_current = False
        db.add(
            Playbook(
                org_id=ctx.org_id, program_id=suggestion.program_id,
                phase=suggestion.phase, entries=entries, version=version,
                is_current=True, updated_by=ctx.user_id,
            )
        )
    await db.commit()
    return {"ok": True, "status": suggestion.status}


# ─────────────────────────────────────────────────────────────────────────────
# Approval rules (data, not code) & user skills
# ─────────────────────────────────────────────────────────────────────────────

from app.models.comms import ApprovalRule  # noqa: E402
from app.models.user import UserSkill  # noqa: E402


class ApprovalRuleRequest(BaseModel):
    entity_type: str
    condition: dict = Field(default_factory=dict)
    rank: int = 100
    approver_role: str
    fallback_role: str | None = None
    recommender_role: str | None = None
    joint_with_role: str | None = None
    joint_condition: dict | None = None
    auto_approve: bool = False
    expires_hours: float = 48.0
    description: str | None = None


@router.post("/approval-rules")
async def create_approval_rule(
    body: ApprovalRuleRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Changing who approves what is a settings edit — never a code change."""
    rule = ApprovalRule(org_id=ctx.org_id, **body.model_dump())
    db.add(rule)
    await db.commit()
    return {"id": rule.id}


@router.get("/approval-rules")
async def list_approval_rules(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(ApprovalRule)
            .where(ApprovalRule.org_id == ctx.org_id)
            .order_by(ApprovalRule.entity_type, ApprovalRule.rank)
        )
    ).scalars().all()
    return [
        {
            # Field order mirrors ApprovalRuleRequest above: this read is the
            # write's counterpart and should look like one. fallback_role and
            # auto_approve were accepted and stored but never returned, so a
            # rule set to auto-approve read back as one that waits for a human
            # and a reseed bundle silently dropped it (change #9).
            "id": r.id, "entity_type": r.entity_type, "condition": r.condition,
            "rank": r.rank, "approver_role": r.approver_role,
            "fallback_role": r.fallback_role,
            "recommender_role": r.recommender_role,
            "joint_with_role": r.joint_with_role,
            "joint_condition": r.joint_condition,
            "auto_approve": r.auto_approve,
            "expires_hours": r.expires_hours, "description": r.description,
        }
        for r in rows
    ]


@router.delete("/approval-rules/{rule_id}")
async def delete_approval_rule(
    rule_id: str,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    rule = (
        await db.execute(
            select(ApprovalRule).where(
                ApprovalRule.org_id == ctx.org_id, ApprovalRule.id == rule_id
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise NotFoundError("Rule not found")
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


class SkillRequest(BaseModel):
    user_id: str
    skill: str
    level: str = "good"  # basic | good | expert


@router.post("/skills")
async def set_skill(
    body: SkillRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Skills bring work to a desk; leads adjust levels when reality proves
    them wrong (Roles doc §4.5)."""
    if ctx.role not in ("org_admin", "sales_lead", "operations_lead"):
        raise PermissionDeniedError("Only the admin or a lead can adjust skills")
    existing = (
        await db.execute(
            select(UserSkill).where(
                UserSkill.org_id == ctx.org_id,
                UserSkill.user_id == body.user_id,
                UserSkill.skill == body.skill,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.level = body.level
        await db.commit()
        return {"id": existing.id, "updated": True}
    skill = UserSkill(
        org_id=ctx.org_id, user_id=body.user_id, skill=body.skill, level=body.level
    )
    db.add(skill)
    await db.commit()
    return {"id": skill.id, "updated": False}


@router.get("/skills")
async def list_skills(
    user_id: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(UserSkill).where(UserSkill.org_id == ctx.org_id)
    if user_id:
        stmt = stmt.where(UserSkill.user_id == user_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {"user_id": s.user_id, "skill": s.skill, "level": s.level} for s in rows
    ]


@router.delete("/skills")
async def delete_skill(
    user_id: str,
    skill: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Natural key, not a row id — GET /skills does not return one, and this
    mirrors POST /skills, which upserts on the same pair."""
    # This role tuple is duplicated from POST /skills above, deliberately.
    # Centralising it into core/permissions.py _MATRIX is Part F #11, which is
    # DEFERRED: the backend change list is closed, and moving it would need the
    # list reopened. Dashboard/READMEs/09_BACKEND_CHANGES.md is the authority on
    # what that list currently holds — deliberately not repeated here, because
    # the count has already moved once and a comment naming it goes stale
    # silently. Kept identical to its sibling so the two cannot drift apart
    # while they both exist.
    if ctx.role not in ("org_admin", "sales_lead", "operations_lead"):
        raise PermissionDeniedError("Only the admin or a lead can adjust skills")
    row = (
        await db.execute(
            select(UserSkill).where(
                UserSkill.org_id == ctx.org_id,
                UserSkill.user_id == user_id,
                UserSkill.skill == skill,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"No '{skill}' skill recorded for that person")

    # A deactivated user cannot service an open task, so a leftover skill row
    # on a deactivated holder must not count as coverage — only ACTIVE holders
    # do. This has to agree with the go-live skill-coverage check
    # (06_DESIGN.md §5.6), which is also active-only: two definitions of
    # "covered" is how the next divergence starts.
    others = (
        await db.execute(
            select(func.count()).select_from(UserSkill).join(
                User, User.id == UserSkill.user_id
            ).where(
                UserSkill.org_id == ctx.org_id,
                UserSkill.skill == skill,
                UserSkill.user_id != user_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one()
    if others == 0:
        open_work = (
            await db.execute(
                select(func.count()).select_from(ActionItem).where(
                    ActionItem.org_id == ctx.org_id,
                    ActionItem.required_skill == skill,
                    ActionItem.status.in_(("open", "in_progress", "pending_review")),
                )
            )
        ).scalar_one()
        if open_work:
            raise ConflictError(
                f"{open_work} open task(s) need '{skill}' and nobody else holds "
                f"it. Give the skill to someone else first, or close that work."
            )

    await db.delete(row)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="ops.skill_deleted",
        entity_type="user_skill", entity_id=row.id,
        detail={"user_id": user_id, "skill": skill},
    )
    await db.commit()
    return {"deleted": True}
