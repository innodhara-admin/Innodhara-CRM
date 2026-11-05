"""Org Admin setup (doc §9.5): staff, programs, pricing, templates, demo
teams, feature switches, integrations and the audit log."""
from __future__ import annotations

import io
import secrets
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.config import get_settings
from app.core.constants import (
    ORG_ROLES, Department, MessageChannel, Role, TemplateKind,
)
from app.core.context import OrgContext
from app.core.crypto import encrypt_secret
from app.core.exceptions import (
    ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError,
)
from app.core.reset_taxonomy import CONFIG, REPLACE, WIPE, deletion_order
from app.core.security import hash_password, verify_password
from app.database import Base, get_db
from app.models.audit import AuditLog
from app.models.base import utcnow
from app.models.demo import Demo, DemoTeam, DemoTeamMember
from app.models.organisation import Organisation, OrgSettings
from app.models.program import (
    MessageTemplate,
    PricingTable,
    Program,
    ProposalTemplate,
    ProposalTemplateDoc,
)
from app.models.project import Playbook, PlaybookSuggestion, Project
from app.models.proposal import Proposal
from app.models.user import User
from app.services import audit_service, docx_template_service, org_delete, storage

router = APIRouter(prefix="/admin", tags=["org admin"])


# ══════════════════════════ Staff ══════════════════════════════════════════
class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2)
    role: str
    phone: str | None = None
    department: str | None = None
    designation: str | None = None
    whatsapp_number: str | None = None
    max_open_tasks: int | None = Field(default=None, ge=1, le=100)
    working_days: list[str] | None = None


class UpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    require_action_item_review: bool | None = None
    department: str | None = None
    designation: str | None = None
    whatsapp_number: str | None = None
    max_open_tasks: int | None = Field(default=None, ge=1, le=100)
    working_days: list[str] | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    phone: str | None
    is_active: bool
    department: str | None = None
    designation: str | None = None
    whatsapp_number: str | None = None
    max_open_tasks: int | None = None
    working_days: list[str] | None = None
    require_action_item_review: bool | None = None


def _user_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id, email=u.email, name=u.name, role=u.role,
        phone=u.phone, is_active=u.is_active,
        department=u.department, designation=u.designation,
        whatsapp_number=u.whatsapp_number, max_open_tasks=u.max_open_tasks,
        working_days=u.working_days,
        require_action_item_review=u.require_action_item_review,
    )


def _validated_department(value: str | None) -> str | None:
    """`Department` is sales | operations | accounts. Note `accounts` is a
    department but not a role — the accounts executive is an operations_agent."""
    if value is None:
        return None
    try:
        return Department(value).value
    except ValueError:
        raise ValidationFailedError(
            f"Unknown department '{value}'. Use one of: "
            + ", ".join(d.value for d in Department)
        )


@router.post("/users")
async def register_staff(
    body: CreateUserRequest,
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    try:
        role = Role(body.role)
    except ValueError:
        raise ValidationFailedError(f"Unknown role '{body.role}'")
    if role not in ORG_ROLES:
        raise ValidationFailedError("Only organisation roles can be assigned here")
    exists = (
        await db.execute(
            select(User).where(func.lower(User.email) == body.email.lower())
        )
    ).scalar_one_or_none()
    if exists:
        raise ConflictError(f"User {body.email} already exists")
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()
    if not body.email.lower().endswith("@" + org.email_domain):
        raise ValidationFailedError(
            f"Staff email must use your organisation's domain @{org.email_domain}"
        )
    temp_password = secrets.token_urlsafe(9)
    user = User(
        org_id=ctx.org_id,
        email=body.email.lower(),
        name=body.name,
        role=role.value,
        phone=body.phone,
        password_hash=hash_password(temp_password),
        must_change_password=True,
        department=_validated_department(body.department),
        designation=body.designation,
        whatsapp_number=body.whatsapp_number,
        working_days=body.working_days,
    )
    if body.max_open_tasks is not None:
        user.max_open_tasks = body.max_open_tasks
    db.add(user)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.staff_registered",
        entity_type="user", detail={"email": body.email, "role": role.value},
    )
    await db.commit()
    return {**_user_response(user).model_dump(), "temp_password": temp_password}


@router.get("/users", response_model=list[UserResponse])
async def list_staff(
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    users = (
        await db.execute(select(User).where(User.org_id == ctx.org_id))
    ).scalars().all()
    return [_user_response(u) for u in users]


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_staff_member(
    user_id: str,
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    """A staff-detail screen cannot be built from `list_staff` alone."""
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    return _user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_staff(
    user_id: str,
    body: UpdateUserRequest,
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    if body.role is not None:
        try:
            role = Role(body.role)
        except ValueError:
            raise ValidationFailedError(f"Unknown role '{body.role}'")
        if role not in ORG_ROLES:
            raise ValidationFailedError("Only organisation roles can be assigned")
        user.role = role.value
    if body.name is not None:
        user.name = body.name
    if body.phone is not None:
        user.phone = body.phone
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.require_action_item_review is not None:
        user.require_action_item_review = body.require_action_item_review
    if body.department is not None:
        user.department = _validated_department(body.department)
    if body.designation is not None:
        user.designation = body.designation
    if body.whatsapp_number is not None:
        user.whatsapp_number = body.whatsapp_number
    if body.max_open_tasks is not None:
        user.max_open_tasks = body.max_open_tasks
    if body.working_days is not None:
        user.working_days = body.working_days
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.staff_updated",
        entity_type="user", entity_id=user_id,
    )
    await db.commit()
    return _user_response(user)


@router.post("/users/{user_id}/reset-password")
async def reset_staff_password(
    user_id: str,
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    """Forgotten password (mobile G6): the admin issues a fresh temporary
    password — shown once — and the user must change it at next login."""
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    temp_password = secrets.token_urlsafe(9)
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.staff_password_reset",
        entity_type="user", entity_id=user_id,
    )
    await db.commit()
    return {"reset": True, "temp_password": temp_password}


# ══════════════════════════ Programs ═══════════════════════════════════════
class ProgramRequest(BaseModel):
    name: str
    code: str = Field(min_length=1, max_length=50)
    description: str | None = None


@router.post("/programs")
async def add_program(
    body: ProgramRequest,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(
            select(Program).where(
                Program.org_id == ctx.org_id,
                func.lower(Program.code) == body.code.lower(),
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise ConflictError(f"Program code '{body.code}' already exists")
    program = Program(
        org_id=ctx.org_id, name=body.name, code=body.code.upper(),
        description=body.description,
    )
    db.add(program)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.program_added",
        entity_type="program", detail={"code": body.code},
    )
    await db.commit()
    return {"id": program.id, "name": program.name, "code": program.code}


@router.get("/programs")
async def list_programs(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    programs = (
        await db.execute(select(Program).where(Program.org_id == ctx.org_id))
    ).scalars().all()
    return [
        {"id": p.id, "name": p.name, "code": p.code,
         "description": p.description, "is_active": p.is_active}
        for p in programs
    ]


# ══════════════════════════ Pricing (versioned) ═════════════════════════════
class PricingItem(BaseModel):
    code: str
    label: str
    unit: str = "-"
    unit_price: float = Field(ge=0)
    # None means "this org did not say how many" — NOT "one of them". The
    # difference matters: `items` is stored via model_dump(), so a default of 1
    # was written into every line an admin created without thinking about
    # quantities, and downstream could no longer tell a deliberate quantity of
    # one (one site, one handover pack) from an unanswered question. The value
    # estimate scales an unanswered line by the count discussed in the meeting,
    # and a stated one by itself. Proposals still start such a line at 1
    # (`proposal_service`: `.get("default_quantity", 1) or 1`).
    default_quantity: float | None = None
    notes: str | None = None


class PricingRequest(BaseModel):
    currency: str = "INR"
    items: list[PricingItem] = Field(min_length=1)


@router.post("/programs/{program_id}/pricing")
async def set_pricing(
    program_id: str,
    body: PricingRequest,
    ctx: OrgContext = Depends(require_permission("edit_pricing")),
    db: AsyncSession = Depends(get_db),
):
    """Creates a NEW pricing version; old proposals keep the version they used."""
    program = (
        await db.execute(
            select(Program).where(Program.id == program_id, Program.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")
    current = (
        await db.execute(
            select(PricingTable)
            .where(
                PricingTable.org_id == ctx.org_id,
                PricingTable.program_id == program_id,
            )
            .order_by(PricingTable.version.desc())
        )
    ).scalars().first()
    next_version = (current.version + 1) if current else 1
    if current:
        current.is_current = False
    pricing = PricingTable(
        org_id=ctx.org_id,
        program_id=program_id,
        version=next_version,
        currency=body.currency,
        items=[i.model_dump() for i in body.items],
        created_by=ctx.user_id,
    )
    db.add(pricing)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.pricing_updated",
        entity_type="program", entity_id=program_id, detail={"version": next_version},
    )
    await db.commit()
    return {"id": pricing.id, "version": next_version, "currency": body.currency,
            "items": pricing.items}


@router.get("/programs/{program_id}/pricing")
async def get_pricing_history(
    program_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    tables = (
        await db.execute(
            select(PricingTable)
            .where(
                PricingTable.org_id == ctx.org_id,
                PricingTable.program_id == program_id,
            )
            .order_by(PricingTable.version.desc())
        )
    ).scalars().all()
    return [
        {"id": t.id, "version": t.version, "currency": t.currency,
         "items": t.items, "is_current": t.is_current,
         "effective_from": t.effective_from.isoformat()}
        for t in tables
    ]


# ══════════════════════════ Proposal templates (versioned) ══════════════════
class ProposalTemplateRequest(BaseModel):
    name: str
    body_md: str = Field(min_length=20)
    make_current: bool = True


@router.post("/programs/{program_id}/proposal-templates")
async def add_proposal_template(
    program_id: str,
    body: ProposalTemplateRequest,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    program = (
        await db.execute(
            select(Program).where(Program.id == program_id, Program.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")
    same_name = (
        await db.execute(
            select(ProposalTemplate)
            .where(
                ProposalTemplate.org_id == ctx.org_id,
                ProposalTemplate.program_id == program_id,
                ProposalTemplate.name == body.name,
            )
            .order_by(ProposalTemplate.version.desc())
        )
    ).scalars().first()
    version = (same_name.version + 1) if same_name else 1
    if body.make_current:
        others = (
            await db.execute(
                select(ProposalTemplate).where(
                    ProposalTemplate.org_id == ctx.org_id,
                    ProposalTemplate.program_id == program_id,
                    ProposalTemplate.is_current.is_(True),
                )
            )
        ).scalars().all()
        for other in others:
            other.is_current = False
    template = ProposalTemplate(
        org_id=ctx.org_id, program_id=program_id, name=body.name,
        version=version, body_md=body.body_md,
        is_current=body.make_current, created_by=ctx.user_id,
    )
    db.add(template)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.proposal_template_added",
        entity_type="program", entity_id=program_id,
        detail={"name": body.name, "version": version},
    )
    await db.commit()
    return {"id": template.id, "name": template.name, "version": version,
            "is_current": template.is_current}


# ══════════════════ Document (.docx) proposal templates ══════════════════
# A docx template is an uploaded, branded document plus a fill plan. It is
# stored once and never rewritten: every proposal is source + plan + values ->
# a new file. See
# docs/superpowers/specs/2026-09-03-docx-proposal-templates-design.md


class SavePlanRequest(BaseModel):
    plan: dict[str, Any]


def _doc_summary(template: ProposalTemplate, doc_row: ProposalTemplateDoc) -> dict:
    return {
        "id": template.id, "name": template.name, "version": template.version,
        "kind": template.kind, "is_current": template.is_current,
        "document_type": template.document_type,
        "doc_id": doc_row.id, "index_kind": doc_row.index_kind,
        "blocks": len((doc_row.outline_json or {}).get("blocks", [])),
        # flow, tags, always_asked, distinct -- the simple flow has no
        # editor to move on to, so this response IS its success screen.
        **docx_template_service.plan_summary(doc_row.plan_json),
    }


@router.post("/programs/{program_id}/proposal-templates/docx")
async def add_proposal_template_docx(
    program_id: str,
    name: str = Form(...),
    make_current: bool = Form(True),
    flow: str = Form("simple"),
    document_type: str = Form("proposal"),
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".docx"):
        raise ValidationFailedError("Upload a .docx file")
    data = await file.read()
    template, doc_row = await docx_template_service.create_docx_template(
        db, ctx, program_id=program_id, name=name,
        filename=filename, data=data,
        make_current=make_current, flow=flow, document_type=document_type,
    )
    await db.commit()
    return _doc_summary(template, doc_row)


@router.get("/proposal-template-docs/{doc_id}")
async def get_proposal_template_doc(
    doc_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    doc_row = await docx_template_service.get_doc(db, ctx.org_id, doc_id)
    template = (
        await db.execute(
            select(ProposalTemplate).where(ProposalTemplate.id == doc_row.template_id)
        )
    ).scalar_one_or_none()
    return {
        # both spellings: `id` is what the console's zod read shape expects,
        # `doc_id` is what the upload response returns and the editor routes on.
        "id": doc_row.id,
        "doc_id": doc_row.id,
        "template_id": doc_row.template_id,
        "name": template.name if template else "",
        "version": template.version if template else 0,
        "filename": doc_row.filename,
        "size_bytes": doc_row.size_bytes,
        "index_kind": doc_row.index_kind,
        "analysis_status": doc_row.analysis_status,
        "analysis_error": doc_row.analysis_error,
        "outline": doc_row.outline_json or {},
        "ocr": doc_row.ocr_json or {},
        "plan": doc_row.plan_json or {"version": 1, "entries": []},
    }


@router.post("/proposal-template-docs/{doc_id}/suggest")
async def suggest_proposal_template_placeholders(
    doc_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    """Advisory only. Nothing is saved: the administrator accepts, rewords or
    rejects each suggestion, then PUTs the plan."""
    from app.ai import docx_suggest

    doc_row = await docx_template_service.get_doc(db, ctx.org_id, doc_id)
    template = (
        await db.execute(
            select(ProposalTemplate).where(ProposalTemplate.id == doc_row.template_id)
        )
    ).scalar_one_or_none()
    program_name = ""
    if template is not None:
        program = (
            await db.execute(select(Program).where(Program.id == template.program_id))
        ).scalar_one_or_none()
        program_name = program.name if program else ""
    suggestions = await docx_suggest.suggest(
        ctx, outline=doc_row.outline_json or {}, ocr=doc_row.ocr_json or {},
        program_name=program_name,
    )
    return {"suggestions": suggestions}


@router.put("/proposal-template-docs/{doc_id}/plan")
async def save_proposal_template_plan(
    doc_id: str,
    body: SavePlanRequest,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    doc_row = await docx_template_service.get_doc(db, ctx.org_id, doc_id)
    problems = await docx_template_service.save_plan(db, ctx, doc_row, body.plan)
    if problems:
        raise ValidationFailedError(
            "This plan does not match the document: " + "; ".join(problems)
        )
    await db.commit()
    return {"entries": len((body.plan.get("entries") or []))}


@router.post("/proposal-template-docs/{doc_id}/preview")
async def preview_proposal_template(
    doc_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    """Fill the plan with obviously-fake sample values and return the PDF.

    No model is called: a preview must not spend tokens, and it must look the
    same every time an administrator presses the button.
    """
    from app.services.docx import convert as docx_convert
    from app.services.docx import fill as docx_fill

    doc_row = await docx_template_service.get_doc(db, ctx.org_id, doc_id)
    source = storage.read_bytes(ctx.org_id, doc_row.source_path)
    plan = doc_row.plan_json or {"version": 1, "entries": []}

    values: dict[str, Any] = {}
    for entry in plan.get("entries") or []:
        key, kind = entry.get("key"), entry.get("kind")
        if kind == "table":
            fields = [c["field"] for c in entry.get("columns") or []]
            def row(label: str, amount: str) -> dict:
                sample = {"label": label, "unit": "per unit", "quantity": "1",
                          "unit_price": amount, "line_total": amount}
                return {f: sample.get(f, "") for f in fields}
            values[key] = {"rows": [row("Sample line item", "0"),
                                    row("Second sample item", "0")],
                           "total": "0"}
        elif kind == "token":
            values[key] = "Sample School"
        else:
            values[key] = (
                f"[sample text for '{key}' — the AI writes this when a real "
                "proposal is generated]"
            )

    filled = docx_fill.apply(source, plan, values)
    pdf = docx_convert.docx_to_pdf(filled["docx"])
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="preview.pdf"'},
    )


@router.get("/proposal-template-docs/{doc_id}/media/{name}")
async def get_proposal_template_media(
    doc_id: str,
    name: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Serve one image out of the stored document.

    `name` is checked against the media list the outline recorded, so the route
    cannot be walked to another part of the package or off disk.
    """
    import mimetypes
    import zipfile

    doc_row = await docx_template_service.get_doc(db, ctx.org_id, doc_id)
    allowed = set((doc_row.outline_json or {}).get("media") or [])
    if name not in allowed:
        raise NotFoundError("No such image in this document")

    source = storage.read_bytes(ctx.org_id, doc_row.source_path)
    with zipfile.ZipFile(io.BytesIO(source)) as z:
        try:
            data = z.read(f"word/media/{name}")
        except KeyError as exc:
            raise NotFoundError("No such image in this document") from exc
    return Response(
        content=data,
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
    )


@router.get("/programs/{program_id}/proposal-templates")
async def list_proposal_templates(
    program_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    templates = (
        await db.execute(
            select(ProposalTemplate)
            .where(
                ProposalTemplate.org_id == ctx.org_id,
                ProposalTemplate.program_id == program_id,
            )
            .order_by(ProposalTemplate.name, ProposalTemplate.version.desc())
        )
    ).scalars().all()
    return [
        {"id": t.id, "name": t.name, "version": t.version, "kind": t.kind,
         "is_current": t.is_current, "body_md": t.body_md}
        for t in templates
    ]


# ══════════════════════════ Message templates ═══════════════════════════════
class MessageTemplateRequest(BaseModel):
    kind: str          # intro | follow_up
    channel: str       # email | whatsapp
    name: str
    subject: str | None = None
    body: str = Field(min_length=10)
    make_current: bool = True


@router.post("/message-templates")
async def add_message_template(
    body: MessageTemplateRequest,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    try:
        kind = TemplateKind(body.kind).value
        channel = MessageChannel(body.channel).value
    except ValueError:
        raise ValidationFailedError("kind must be intro|follow_up; channel email|whatsapp")
    if channel == MessageChannel.EMAIL.value and not body.subject:
        raise ValidationFailedError("Email templates need a subject")
    same = (
        await db.execute(
            select(MessageTemplate)
            .where(
                MessageTemplate.org_id == ctx.org_id,
                MessageTemplate.kind == kind,
                MessageTemplate.channel == channel,
                MessageTemplate.name == body.name,
            )
            .order_by(MessageTemplate.version.desc())
        )
    ).scalars().first()
    version = (same.version + 1) if same else 1
    if body.make_current:
        others = (
            await db.execute(
                select(MessageTemplate).where(
                    MessageTemplate.org_id == ctx.org_id,
                    MessageTemplate.kind == kind,
                    MessageTemplate.channel == channel,
                    MessageTemplate.is_current.is_(True),
                )
            )
        ).scalars().all()
        for other in others:
            other.is_current = False
    template = MessageTemplate(
        org_id=ctx.org_id, kind=kind, channel=channel, name=body.name,
        version=version, subject=body.subject, body=body.body,
        is_current=body.make_current, created_by=ctx.user_id,
    )
    db.add(template)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.message_template_added",
        detail={"kind": kind, "channel": channel, "version": version},
    )
    await db.commit()
    return {"id": template.id, "kind": kind, "channel": channel,
            "version": version, "is_current": template.is_current}


@router.get("/message-templates")
async def list_message_templates(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    templates = (
        await db.execute(
            select(MessageTemplate)
            .where(MessageTemplate.org_id == ctx.org_id)
            .order_by(MessageTemplate.kind, MessageTemplate.channel,
                      MessageTemplate.version.desc())
        )
    ).scalars().all()
    return [
        {"id": t.id, "kind": t.kind, "channel": t.channel, "name": t.name,
         "version": t.version, "subject": t.subject, "body": t.body,
         "is_current": t.is_current}
        for t in templates
    ]


# ══════════════════════════ Demo teams ══════════════════════════════════════
class DemoTeamRequest(BaseModel):
    name: str
    lead_user_id: str | None = None
    media_rep_id: str | None = None
    sales_rep_id: str | None = None
    member_ids: list[str] = []


@router.post("/demo-teams")
async def register_demo_team(
    body: DemoTeamRequest,
    ctx: OrgContext = Depends(require_permission("manage_teams")),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(
            select(DemoTeam).where(
                DemoTeam.org_id == ctx.org_id,
                func.lower(DemoTeam.name) == body.name.lower(),
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise ConflictError(f"Demo team '{body.name}' already exists")

    async def _check_user(user_id: str | None) -> None:
        if user_id is None:
            return
        user = (
            await db.execute(
                select(User).where(User.id == user_id, User.org_id == ctx.org_id)
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError(f"User {user_id} not found in your organisation")

    for uid in [body.lead_user_id, body.media_rep_id, body.sales_rep_id, *body.member_ids]:
        await _check_user(uid)

    team = DemoTeam(
        org_id=ctx.org_id, name=body.name, lead_user_id=body.lead_user_id,
        media_rep_id=body.media_rep_id, sales_rep_id=body.sales_rep_id,
    )
    db.add(team)
    await db.flush()
    for uid in body.member_ids:
        db.add(DemoTeamMember(org_id=ctx.org_id, team_id=team.id, user_id=uid))
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.demo_team_registered",
        entity_type="demo_team", entity_id=team.id, detail={"name": body.name},
    )
    await db.commit()
    return {"id": team.id, "name": team.name}


@router.get("/demo-teams")
async def list_demo_teams(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    teams = (
        await db.execute(select(DemoTeam).where(DemoTeam.org_id == ctx.org_id))
    ).scalars().all()
    results = []
    for team in teams:
        members = (
            await db.execute(
                select(User.id, User.name)
                .join(DemoTeamMember, DemoTeamMember.user_id == User.id)
                .where(DemoTeamMember.team_id == team.id)
            )
        ).all()

        async def _name(uid: str | None) -> str | None:
            if not uid:
                return None
            return (
                await db.execute(select(User.name).where(User.id == uid))
            ).scalar_one_or_none()

        results.append(
            {
                "id": team.id,
                "name": team.name,
                # Each id sits next to the name it resolves, so the pairing is
                # obvious. The names stay: the Android app calls this route and
                # may render them, and rule 1 of 09 §2 is additive-only. The ids
                # were write-only, and User.name is not unique — so a
                # delete-and-recreate edit (there is no PATCH) could not restore
                # these three roles and a reseed bundle lost them (change #10).
                "lead": await _name(team.lead_user_id),
                "lead_user_id": team.lead_user_id,
                "media_rep": await _name(team.media_rep_id),
                "media_rep_id": team.media_rep_id,
                "sales_rep": await _name(team.sales_rep_id),
                "sales_rep_id": team.sales_rep_id,
                "members": [{"id": m[0], "name": m[1]} for m in members],
            }
        )
    return results


# ══════════════════════════ Guarded deletes (change #6, part 2) ═════════════
async def _promote_predecessor(db: AsyncSession, model, **scope) -> None:
    """After deleting the current row of a versioned family, make the highest
    remaining version current again. This is the API's only un-supersede path
    and it exists as a consequence of deletion, not as its own endpoint."""
    predecessor = (
        await db.execute(
            select(model)
            .filter_by(**scope)
            .order_by(model.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if predecessor is not None:
        predecessor.is_current = True


@router.delete("/programs/{program_id}")
async def delete_program(
    program_id: str,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    """`code` is UNIQUE per org, so without this a typo is permanent — and its
    description keeps being read by the offering matcher."""
    program = (
        await db.execute(
            select(Program).where(
                Program.id == program_id, Program.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")

    used_by_projects = (
        await db.execute(
            select(func.count()).select_from(Project).where(
                Project.org_id == ctx.org_id, Project.program_id == program_id
            )
        )
    ).scalar_one()
    used_by_proposals = (
        await db.execute(
            select(func.count()).select_from(Proposal).where(
                Proposal.org_id == ctx.org_id, Proposal.program_id == program_id
            )
        )
    ).scalar_one()
    if used_by_projects or used_by_proposals:
        raise ConflictError(
            f"'{program.name}' is used by {used_by_projects} project(s) and "
            f"{used_by_proposals} proposal(s) and cannot be removed. Mark it "
            f"inactive instead."
        )

    for model, scope in (
        (PricingTable, {"program_id": program_id}),
        (ProposalTemplate, {"program_id": program_id}),
        (Playbook, {"program_id": program_id}),
        (PlaybookSuggestion, {"program_id": program_id}),
    ):
        await db.execute(
            sa_delete(model.__table__).where(
                model.__table__.c.org_id == ctx.org_id,
                model.__table__.c.program_id == program_id,
            )
        )

    await db.delete(program)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.program_deleted",
        entity_type="program", entity_id=program_id,
        detail={"name": program.name, "code": program.code},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/programs/{program_id}/pricing/{version}")
async def delete_pricing_version(
    program_id: str,
    version: int,
    ctx: OrgContext = Depends(require_permission("edit_pricing")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(PricingTable).where(
                PricingTable.org_id == ctx.org_id,
                PricingTable.program_id == program_id,
                PricingTable.version == version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Pricing version not found")

    locked = (
        await db.execute(
            select(func.count()).select_from(Proposal).where(
                Proposal.org_id == ctx.org_id, Proposal.pricing_table_id == row.id
            )
        )
    ).scalar_one()
    if locked:
        raise ConflictError(
            f"{locked} proposal(s) locked this rate card version. Removing it "
            f"would break the price they were sent at."
        )

    was_current = row.is_current
    await db.delete(row)
    await db.flush()
    if was_current:
        await _promote_predecessor(
            db, PricingTable, org_id=ctx.org_id, program_id=program_id
        )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.pricing_deleted",
        entity_type="pricing_table", entity_id=row.id,
        detail={"program_id": program_id, "version": version},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/programs/{program_id}/proposal-templates/{template_id}")
async def delete_proposal_template(
    program_id: str,
    template_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(ProposalTemplate).where(
                ProposalTemplate.id == template_id,
                ProposalTemplate.org_id == ctx.org_id,
                ProposalTemplate.program_id == program_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Proposal template not found")

    locked = (
        await db.execute(
            select(func.count()).select_from(Proposal).where(
                Proposal.org_id == ctx.org_id, Proposal.template_id == template_id
            )
        )
    ).scalar_one()
    if locked:
        raise ConflictError(
            f"{locked} proposal(s) were built from this template version."
        )

    was_current, name = row.is_current, row.name
    await db.delete(row)
    await db.flush()
    if was_current:
        await _promote_predecessor(
            db, ProposalTemplate, org_id=ctx.org_id,
            program_id=program_id,
            # D-B: deleting the current MOU must promote the previous
            # MOU, never a proposal template -- and vice versa.
            document_type=row.document_type,
        )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.proposal_template_deleted",
        entity_type="proposal_template", entity_id=template_id,
        detail={"program_id": program_id, "name": name},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/message-templates/{template_id}")
async def delete_message_template(
    template_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    """No reference guard: nothing points at a message template. Removing the
    last intro/email one breaks card-scan drafting, and the console's checklist
    turns amber immediately — that is the guard (06_DESIGN.md §7.2)."""
    row = (
        await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.id == template_id,
                MessageTemplate.org_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Message template not found")

    was_current, kind, channel = row.is_current, row.kind, row.channel
    await db.delete(row)
    await db.flush()
    if was_current:
        await _promote_predecessor(
            db, MessageTemplate, org_id=ctx.org_id, kind=kind, channel=channel
        )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.message_template_deleted",
        entity_type="message_template", entity_id=template_id,
        detail={"kind": kind, "channel": channel},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/demo-teams/{team_id}")
async def delete_demo_team(
    team_id: str,
    ctx: OrgContext = Depends(require_permission("manage_teams")),
    db: AsyncSession = Depends(get_db),
):
    """Member rows go with it: the schema declares no `ondelete=` anywhere, so
    the handler is the only thing that will clean them up."""
    team = (
        await db.execute(
            select(DemoTeam).where(
                DemoTeam.id == team_id, DemoTeam.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise NotFoundError("Demo team not found")

    booked = (
        await db.execute(
            select(func.count()).select_from(Demo).where(
                Demo.org_id == ctx.org_id, Demo.team_id == team_id
            )
        )
    ).scalar_one()
    if booked:
        raise ConflictError(
            f"{booked} demo(s) are booked against '{team.name}'."
        )

    await db.execute(
        sa_delete(DemoTeamMember.__table__).where(
            DemoTeamMember.__table__.c.team_id == team_id
        )
    )
    await db.delete(team)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.demo_team_deleted",
        entity_type="demo_team", entity_id=team_id, detail={"name": team.name},
    )
    await db.commit()
    return {"deleted": True}


# ══════════════════════════ Settings & integrations ═════════════════════════
class SettingsRequest(BaseModel):
    require_action_item_review: bool | None = None
    auto_suggest_lead_state: bool | None = None
    audio_retention_days: int | None = Field(default=None, ge=1, le=3650)
    transcript_retention_days: int | None = Field(default=None, ge=1, le=3650)
    llm_monthly_budget_usd: float | None = Field(default=None, ge=0)
    timezone: str | None = None
    currency: str | None = None
    followup_cadence_days: int | None = Field(default=None, ge=1, le=365)
    # Workflow behaviour dials (Data Model §2.2 ✚) — the Org Admin's control
    # panel; every engine reads these before acting.
    assignment_mode: str | None = Field(default=None, pattern="^(auto|lead_confirm)$")
    working_days: list[str] | None = None
    workday_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    workday_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    quiet_hours_override_priority: str | None = Field(default=None, pattern="^P[123]$")
    nudge_gap_days: dict | None = None
    max_unanswered_nudges: int | None = Field(default=None, ge=0, le=10)
    max_client_messages_per_week: int | None = Field(default=None, ge=1, le=50)
    lead_cold_after_days: int | None = Field(default=None, ge=1, le=365)
    high_load_caution_pct: int | None = Field(default=None, ge=10, le=100)
    delivery_requires_advance: bool | None = None
    scope_change_requires_confirmation: bool | None = None
    client_report_day: str | None = None
    client_report_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    payment_reminder_schedule: list[dict] | None = None
    reply_nudge_after_days: dict | None = None
    ai_confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class EmailIntegrationRequest(BaseModel):
    smtp_username: str
    smtp_app_password: str


class WhatsAppIntegrationRequest(BaseModel):
    """Meta (`access_token` + `phone_number_id`, the original body) or Wati
    (4 Nov 2026). A blank secret keeps the stored one."""

    provider: str | None = Field(default=None, pattern="^(off|meta|wati)$")
    access_token: str | None = None
    phone_number_id: str | None = None
    # A Wati API host and nothing else: the server sends the stored token to
    # it, so any other address would let an admin probe hosts from inside.
    wati_host: str | None = Field(
        default=None, pattern=r"^https://([a-z0-9-]+\.)*wati\.io/?$")
    wati_token: str | None = None
    wati_channel: str | None = None
    country_code: str | None = Field(default=None, pattern=r"^\d{1,4}$")

    @field_validator("wati_host", "country_code", mode="before")
    @classmethod
    def _blank_is_keep(cls, value):
        """The panel sends "" for a box typed in and cleared: that means keep."""
        return None if isinstance(value, str) and not value.strip() else value


class WhatsAppStaffUpdatesRequest(BaseModel):
    enabled: bool
    kinds_off: list[str] = []


class WhatsAppTestRequest(BaseModel):
    to: str


class CalendarIntegrationRequest(BaseModel):
    calendar_id: str
    credentials_file: str
    # Reusable Google Meet link stamped into demo invites (create one at
    # meet.google.com → "Create a meeting for later").
    meet_link: str | None = None


async def _get_settings_row(db: AsyncSession, org_id: str) -> OrgSettings:
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    ).scalar_one_or_none()
    if row is None:
        row = OrgSettings(org_id=org_id)
        db.add(row)
        await db.flush()
    return row


def _settings_response(s: OrgSettings) -> dict[str, Any]:
    _cfg = get_settings()
    _email_creds = bool((s.email_integration or {}).get("smtp_username"))
    from app.services import whatsapp_settings, whatsapp_staff

    _wa = whatsapp_settings.load(s.whatsapp_integration)
    # "Stored" means the CHOSEN provider's credentials (4 Nov 2026).
    _whatsapp_creds = _wa.ready()
    _calendar_creds = bool((s.calendar_integration or {}).get("calendar_id"))
    return {
        "require_action_item_review": s.require_action_item_review,
        "auto_suggest_lead_state": s.auto_suggest_lead_state,
        "audio_retention_days": s.audio_retention_days,
        "transcript_retention_days": s.transcript_retention_days,
        "llm_monthly_budget_usd": s.llm_monthly_budget_usd,
        "timezone": s.timezone,
        "currency": s.currency,
        "followup_cadence_days": s.followup_cadence_days,
        "assignment_mode": s.assignment_mode,
        "working_days": s.working_days,
        "workday_start": s.workday_start,
        "workday_end": s.workday_end,
        "quiet_hours_override_priority": s.quiet_hours_override_priority,
        "nudge_gap_days": s.nudge_gap_days,
        "max_unanswered_nudges": s.max_unanswered_nudges,
        "max_client_messages_per_week": s.max_client_messages_per_week,
        "lead_cold_after_days": s.lead_cold_after_days,
        "high_load_caution_pct": s.high_load_caution_pct,
        "delivery_requires_advance": s.delivery_requires_advance,
        "scope_change_requires_confirmation": s.scope_change_requires_confirmation,
        "client_report_day": s.client_report_day,
        "client_report_time": s.client_report_time,
        "payment_reminder_schedule": s.payment_reminder_schedule,
        "reply_nudge_after_days": s.reply_nudge_after_days,
        "ai_confidence_threshold": s.ai_confidence_threshold,
        # ── Delivery honesty (D5) ────────────────────────────────────────────
        # Two halves are required for anything to leave: stored credentials AND
        # a process-wide mode. email_service returns a "dry_run:<path>" file
        # unless email_mode == "smtp" AND creds is not None. Reporting only the
        # first half is how "everyone believes they were sent" happens.
        "email_mode": _cfg.email_mode,
        "whatsapp_mode": _cfg.whatsapp_mode,
        "calendar_mode": _cfg.calendar_mode,
        "inbound_email_mode": _cfg.inbound_email_mode,
        "email_credentials_stored": _email_creds,
        "whatsapp_credentials_stored": _whatsapp_creds,
        "calendar_credentials_stored": _calendar_creds,
        "email_integration_configured": _email_creds and _cfg.email_mode == "smtp",
        "whatsapp_integration_configured": (
            _whatsapp_creds and _cfg.whatsapp_mode == "cloud_api"
        ),
        "calendar_integration_configured": (
            _calendar_creds and _cfg.calendar_mode == "google"
        ),
        # WhatsApp provider and staff updates (4 Nov 2026). The webhook path
        # carries a secret: only this settings read shows it, to the admin who
        # pastes it into Wati.
        "whatsapp_provider": _wa.provider,
        "whatsapp_staff_updates": _wa.staff_updates,
        "whatsapp_kinds_off": sorted(_wa.kinds_off),
        "whatsapp_country_code": _wa.country_code,
        "whatsapp_webhook_path": (
            f"/api/v1/webhooks/wati/{_wa.webhook_secret}"
            if _wa.provider == "wati" and _wa.webhook_secret else None
        ),
        "whatsapp_notification_kinds": list(whatsapp_staff.NOTIFICATION_KINDS),
        "public_base_url_set": bool(_cfg.public_base_url.strip()),
    }


@router.get("/settings")
async def get_org_settings(
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_settings_row(db, ctx.org_id)
    await db.commit()
    return _settings_response(row)


@router.patch("/settings")
async def update_org_settings(
    body: SettingsRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_settings_row(db, ctx.org_id)
    for field_name, value in body.model_dump(exclude_none=True).items():
        setattr(row, field_name, value)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.settings_updated",
        detail=body.model_dump(exclude_none=True),
    )
    await db.commit()
    return _settings_response(row)


@router.put("/integrations/email")
async def set_email_integration(
    body: EmailIntegrationRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_settings_row(db, ctx.org_id)
    row.email_integration = {
        "smtp_username": body.smtp_username,
        "smtp_app_password_enc": encrypt_secret(body.smtp_app_password.replace(" ", "")),
    }
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.email_integration_set"
    )
    await db.commit()
    return {"configured": True}


@router.put("/integrations/whatsapp")
async def set_whatsapp_integration(
    body: WhatsAppIntegrationRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    from app.services import whatsapp_settings

    row = await _get_settings_row(db, ctx.org_id)
    raw = dict(row.whatsapp_integration or {})
    if body.access_token and body.access_token.strip():
        raw["access_token_enc"] = encrypt_secret(body.access_token.strip())
    if body.phone_number_id and body.phone_number_id.strip():
        raw["phone_number_id"] = body.phone_number_id.strip()
    import re

    from app.core.exceptions import ValidationFailedError as _Invalid

    # Wati's page may show the token as "Bearer <token>"; the header adds its own.
    token = re.sub(r"^\s*bearer\s+", "", body.wati_token or "", flags=re.IGNORECASE).strip()
    if body.wati_host:
        host = body.wati_host.rstrip("/").lower()
        if (host != (raw.get("wati_host") or whatsapp_settings.DEFAULT_WATI_HOST)
                and raw.get("wati_token_enc") and not token):
            raise _Invalid("Enter the Wati token again when you change the API host.")
        raw["wati_host"] = host
    if token:
        raw["wati_token_enc"] = encrypt_secret(token)
    if body.wati_channel and body.wati_channel.strip():
        raw["wati_channel"] = body.wati_channel.strip()
    if body.country_code:
        raw["country_code"] = body.country_code
    # The original body (token + number id, no provider) still means Meta.
    provider = body.provider or (
        "meta" if body.access_token or body.phone_number_id else raw.get("provider"))
    if provider:
        raw["provider"] = provider
    raw.setdefault("webhook_secret", secrets.token_urlsafe(24))
    row.whatsapp_integration = raw
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.whatsapp_integration_set",
        detail={"provider": provider},
    )
    await db.commit()
    return {"configured": whatsapp_settings.load(raw).ready()}


@router.patch("/integrations/whatsapp/staff-updates")
async def set_whatsapp_staff_updates(
    body: WhatsAppStaffUpdatesRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    from app.services import whatsapp_staff

    unknown = sorted(set(body.kinds_off) - set(whatsapp_staff.NOTIFICATION_KINDS))
    if unknown:
        raise ValidationFailedError(f"Unknown update kind: {', '.join(unknown)}")
    row = await _get_settings_row(db, ctx.org_id)
    raw = dict(row.whatsapp_integration or {})
    raw["staff_updates"] = body.enabled
    raw["kinds_off"] = sorted(set(body.kinds_off))
    row.whatsapp_integration = raw
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.whatsapp_staff_updates_set",
        detail={"enabled": body.enabled, "kinds_off": raw["kinds_off"]},
    )
    await db.commit()
    return {"enabled": body.enabled, "kinds_off": raw["kinds_off"]}


@router.post("/integrations/whatsapp/test")
async def send_whatsapp_test(
    body: WhatsAppTestRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Send the `test_message` template to one number, through the chosen
    provider. In dry run it is written to the outbox and says so."""
    from uuid import uuid4

    from app.core.exceptions import ExternalServiceError
    from app.services import whatsapp_providers, whatsapp_settings
    from app.services.whatsapp_text import normalise_phone

    row = await _get_settings_row(db, ctx.org_id)
    cfg = whatsapp_settings.load(row.whatsapp_integration)
    if cfg.provider == "off":
        raise ValidationFailedError("Choose Meta or Wati and store its credentials first.")
    to = normalise_phone(body.to, cfg.country_code)
    if to is None:
        raise ValidationFailedError(f"'{body.to}' is not a phone number WhatsApp can use.")
    try:
        result = await whatsapp_providers.send_template(
            cfg, org_id=ctx.org_id, to=to, template="test_message",
            values={"name": (ctx.name or "there").split()[0]}, local_id=uuid4().hex)
        outcome = {"ok": result.ok, "provider_id": result.provider_id, "error": result.error}
    except ExternalServiceError as exc:
        outcome = {"ok": False, "provider_id": "", "error": str(exc)}
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.whatsapp_test_sent",
        detail={"ok": outcome["ok"]},
    )
    await db.commit()
    return {**outcome, "to": to,
            "dry_run": outcome["provider_id"].startswith("dry_run:")}


@router.get("/integrations/whatsapp/templates")
async def check_whatsapp_templates(
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Each template this platform sends, against what the provider holds."""
    from app.core.exceptions import ExternalServiceError
    from app.services import whatsapp_providers, whatsapp_settings
    from app.services.whatsapp_templates import TEMPLATES

    row = await _get_settings_row(db, ctx.org_id)
    cfg = whatsapp_settings.load(row.whatsapp_integration)
    held: dict[str, dict] = {}
    error = None
    checked = cfg.provider == "wati" and cfg.ready()
    if checked:
        try:
            held = {r["name"]: r for r in await whatsapp_providers.list_templates(cfg)}
        except ExternalServiceError as exc:
            checked, error = False, str(exc)
    await db.commit()
    rows = []
    for t in TEMPLATES.values():
        found = held.get(t.name)
        rows.append({
            "name": t.name, "category": t.category, "document": t.document,
            "values": list(t.values),
            "found": (found is not None) if checked else None,
            "status": found.get("status") if found else None,
            "values_match": (set(found.get("params") or []) == set(t.values)) if found else None,
        })
    return {"provider": cfg.provider, "checked": checked, "error": error, "templates": rows}


@router.put("/integrations/calendar")
async def set_calendar_integration(
    body: CalendarIntegrationRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_settings_row(db, ctx.org_id)
    row.calendar_integration = {
        "calendar_id": body.calendar_id,
        "credentials_file": body.credentials_file,
        "meet_link": body.meet_link,
    }
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.calendar_integration_set"
    )
    await db.commit()
    return {"configured": True}


# ══════════════════════════ Audit log ═══════════════════════════════════════
@router.get("/audit")
async def view_audit_log(
    limit: int = 100,
    ctx: OrgContext = Depends(require_permission("view_audit")),
    db: AsyncSession = Depends(get_db),
):
    entries = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.org_id == ctx.org_id)
            .order_by(AuditLog.at.desc())
            .limit(min(limit, 500))
        )
    ).scalars().all()
    return [
        {
            "at": e.at.isoformat(),
            "user_id": e.user_id,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "detail": e.detail,
        }
        for e in entries
    ]


# ══════════════════════════ Reset ══════════════════════════════════════════
class ResetRequest(BaseModel):
    dry_run: bool = True
    wipe_transactional: bool = True
    wipe_catalogue: bool = False
    wipe_org_config: bool = False
    confirm_org_name: str | None = None


# Every FK edge from a table that SURVIVES a catalogue-only reset (WIPE or
# CONFIG) into a table that reset DELETES (REPLACE, the catalogue). None of
# them carries `ondelete=` (reset_taxonomy.py: "the schema declares no
# ondelete= rule anywhere"), so a catalogue-only reset (wipe_catalogue=True,
# wipe_transactional=False) deletes the parent while these children survive
# — several of these columns are NOT NULL, so that is an orphan, not a
# dangling optional reference. Change #6's per-row DELETE guards already
# refuse to remove a program a proposal references; this reset must not
# permit in bulk what those guards refuse one row at a time — a
# catalogue-only reset deleting every program while proposals survive is the
# same act at scale, and cannot be more permissive for being bigger.
#
# This is derived from the schema, not hand-copied: the immediately
# preceding task shipped a Critical defect from exactly that pattern (a
# hand-copied table-ordering list, wrong in five places no test caught).
# `reset_taxonomy.py` is frozen and guarded (tests/test_reset_taxonomy.py)
# and is not touched here — WIPE/CONFIG/REPLACE are only read, and the
# derivation below is re-proved independently by
# tests/test_dashboard_reset.py::test_catalogue_orphan_edges_match_the_schema
# so a new WIPE/CONFIG -> REPLACE edge added later is covered with no code
# change here, rather than silently reopening the orphan hole.
#
# This FK walk is blind by construction to a reference the ORM never
# declared as a ForeignKey in the first place. `playbook_suggestions.
# program_id` is exactly that: a bare `String(32)` (app/models/project.py),
# NOT NULL, holding a `programs.id` value with nothing telling SQLAlchemy so
# — no amount of walking `column.foreign_keys` will ever find it. That is a
# schema defect in its own right (the column should carry a ForeignKey) and
# is deliberately NOT being fixed here: adding one is a migration, and this
# project has no Alembic. `_CATALOGUE_ORPHAN_EDGES_DECLARED` below is the
# hand-written escape hatch for edges of that shape — checked in, one row
# per bare reference, each commented with why derivation cannot see it.
def _derive_catalogue_orphan_edges() -> tuple[tuple[str, str, str], ...]:
    edges: set[tuple[str, str, str]] = set()
    replace_set = set(REPLACE)
    for child in set(WIPE) | set(CONFIG):
        table = Base.metadata.tables[child]
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent in replace_set:
                    edges.add((child, column.name, parent))
    # Sorted so the 422 message (built by iterating this tuple) is stable
    # across runs — derivation walks set-typed buckets, so insertion order
    # is not otherwise guaranteed.
    return tuple(sorted(edges))


# Bare (non-FK) catalogue references, declared by hand because the FK walk
# above cannot see them. Every entry here means "derivation is blind here,
# and here is why" — it is not a place to add convenience shortcuts around
# columns the ORM *could* see but doesn't for some other reason.
_CATALOGUE_ORPHAN_EDGES_DECLARED: tuple[tuple[str, str, str], ...] = (
    # playbook_suggestions.program_id -> programs: bare String(32), no
    # ForeignKey declared, NOT NULL. See the comment above
    # _derive_catalogue_orphan_edges for why this can't be derived and why
    # it isn't being schema-fixed here.
    ("playbook_suggestions", "program_id", "programs"),
)


_CATALOGUE_ORPHAN_EDGES: tuple[tuple[str, str, str], ...] = tuple(
    sorted(set(_derive_catalogue_orphan_edges()) | set(_CATALOGUE_ORPHAN_EDGES_DECLARED))
)


async def _catalogue_blocking_edges(
    db: AsyncSession, org_id: str
) -> list[dict[str, Any]]:
    """Org-scoped rows a catalogue-only reset would orphan.

    Only rows where the FK column IS NOT NULL count — a null `demos.team_id`
    or `projects.program_id` references nothing, so it orphans nothing. A
    pre-go-live org with none of these rows is exactly who `wipe_catalogue`
    alone is for, and must not be refused.
    """
    blocking: list[dict[str, Any]] = []
    for child, fk_column, parent in _CATALOGUE_ORPHAN_EDGES:
        table = Base.metadata.tables[child]
        column = table.c[fk_column]
        count = (
            await db.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.org_id == org_id, column.isnot(None))
            )
        ).scalar_one()
        if count:
            blocking.append(
                {"table": child, "column": fk_column, "references": parent,
                 "count": count}
            )
    return blocking


@router.post("/reset")
async def reset_organisation(
    body: ResetRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk removal, scoped to one organisation.

    Unlike scripts/reset_for_datacentre_demo.py — which deletes globally and is
    safe only because the demo database holds one tenant — every statement here
    carries `WHERE org_id = :org`. Tables whose org_id is nullable (jobs,
    llm_usage) keep their platform-level rows, which belong to no tenant.
    """
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()

    if not body.dry_run and (body.confirm_org_name or "").strip() != org.name:
        raise ValidationFailedError(
            f"To apply this reset, send confirm_org_name exactly as '{org.name}'"
        )

    # A catalogue-only reset (wipe_catalogue without wipe_transactional) can
    # orphan WIPE-side rows that still reference what it is about to delete.
    # When wipe_transactional is also true those children are gone first
    # (WIPE precedes REPLACE in deletion_order), so nothing can be orphaned
    # and this check is skipped. A dry run always reports what it finds and
    # never refuses — the conflict must be visible at preview, not just at
    # apply.
    blocking_edges: list[dict[str, Any]] = []
    if body.wipe_catalogue and not body.wipe_transactional:
        blocking_edges = await _catalogue_blocking_edges(db, ctx.org_id)
        if blocking_edges and not body.dry_run:
            detail = ", ".join(
                f"{e['table']}.{e['column']} -> {e['references']} "
                f"({e['count']} row{'' if e['count'] == 1 else 's'})"
                for e in blocking_edges
            )
            raise ValidationFailedError(
                "Catalogue reset refused: it would orphan rows that still "
                f"reference it — {detail}. Wipe transactional data too "
                "(wipe_transactional=true), or clear those rows first."
            )

    tables = deletion_order(
        transactional=body.wipe_transactional,
        catalogue=body.wipe_catalogue,
        org_config=body.wipe_org_config,
    )

    counts: dict[str, int] = {}
    for name in tables:
        table = Base.metadata.tables[name]
        scoped = table.c.org_id == ctx.org_id
        counts[name] = (
            await db.execute(select(func.count()).select_from(table).where(scoped))
        ).scalar_one()
        if not body.dry_run and counts[name]:
            await db.execute(sa_delete(table).where(scoped))

    total = sum(counts.values())
    if not body.dry_run:
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.org_reset",
            entity_type="organisation", entity_id=ctx.org_id,
            detail={
                "counts": counts,
                "total": total,
                "wipe_transactional": body.wipe_transactional,
                "wipe_catalogue": body.wipe_catalogue,
                "wipe_org_config": body.wipe_org_config,
            },
        )
        await db.commit()

    return {
        "org": {"id": org.id, "name": org.name},
        "counts": counts,
        "total": total,
        "applied": not body.dry_run,
        "blocking_edges": blocking_edges,
    }


# ══════════════════════════ Delete the organisation ════════════════════════
class DeleteOrgRequest(BaseModel):
    dry_run: bool = True
    confirm_text: str | None = None
    password: str | None = None


@router.post("/delete-organisation")
async def delete_organisation(
    body: DeleteOrgRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Delete the caller's whole organisation and leave no trace of it
    (docs/superpowers/specs/2026-10-28-org-delete-design.md).

    An org admin of this organisation only. A dry run, the default, changes
    nothing. The real run needs `DELETE <name>` typed back and the admin's own
    password, and writes no audit row: the developer decided the system keeps
    no record of a deleted organisation (28 Oct 2026). A wrong password is a
    422, not a 401, so the dashboard does not read it as an expired session.
    The work is in app/services/org_delete.py, shared with
    scripts/delete_organisation.py.
    """
    if not ctx.is_org_admin:
        raise PermissionDeniedError("Only an org admin can delete the organisation.")
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()

    if body.dry_run:
        conn = await db.connection()
        found = await conn.run_sync(
            org_delete.preview, ctx.org_id, get_settings().storage_path
        )
        return {
            "applied": False,
            "org": {"id": org.id, "name": org.name},
            "rows": found.rows,
            "total": found.total,
            "platform_rows": sum(len(ids) for ids in found.platform_rows.values()),
            "other_org_mentions": found.other_org_mentions,
            "files": found.files,
            "bytes": found.bytes,
            "outside_files": found.outside_files,
            "users": found.users,
            "expected_confirmation": f"DELETE {org.name}",
        }

    try:
        org_delete.sqlite_file(get_settings().resolved_database_url)
    except ValueError as exc:
        raise ValidationFailedError(str(exc))
    if not org_delete.confirmation_matches(body.confirm_text or "", org.name):
        raise ValidationFailedError(
            f"Type DELETE {org.name} exactly to confirm. Nothing was deleted."
        )
    user = (await db.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if not body.password or not verify_password(body.password, user.password_hash):
        raise ValidationFailedError("That password is not right. Nothing was deleted.")

    org_ref = {"id": org.id, "name": org.name}
    # The delete runs on its own connections; this request's read transaction
    # must not hold the WAL open while the database is compacted.
    await db.rollback()
    result = await org_delete.apply_live(
        ctx.org_id, backup_root=org_delete.default_backup_root(), now=utcnow()
    )
    return {
        "applied": True,
        "org": org_ref,
        "deleted": result.deleted,
        "total": result.total,
        "platform_rows_removed": result.platform_rows_removed,
        "files_removed": result.files_removed,
        "bytes_removed": result.bytes_removed,
        "remaining": result.remaining,
        "compacted": result.compacted,
        "backup_folder": result.backup_folder,
        "backup_expires_at": result.backup_expires_at,
    }
