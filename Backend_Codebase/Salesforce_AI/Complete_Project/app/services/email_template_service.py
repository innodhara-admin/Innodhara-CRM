# app/services/email_template_service.py
"""Upload and manage Word email templates (spec section 7, 28 Oct 2026).

A template is an uploaded Word file whose first line is `Subject: ...` and
whose blanks are tags in the proposal templates' own grammar (`<School Name>`,
`<ask:...>`). It is stored once and never rewritten: every email is
`source + values -> a new file -> subject, HTML and text`.

Two kinds: a **common** email has a category and no programme; a **product**
email has a programme and no category, and may carry the client's built
proposal or MOU. Versions are numbered per name, and "current" is per name
too: several current templates may share a category or a product.
"""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    EMAIL_CATEGORY_PRESETS,
    BuiltDocument,
    EmailTemplateType,
)
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.email_template import EmailTemplate, EmailTemplateAttachment
from app.models.program import Program
from app.services import audit_service, draft_check, email_render, storage
from app.services.docx import tags as docx_tags

MAX_TEMPLATE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_TOTAL = 20 * 1024 * 1024
CATEGORY = "email_templates"
ALLOWED_ATTACHMENTS = (".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".png",
                       ".jpg", ".jpeg")

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

_NON_WORD = re.compile(r"[^a-z0-9_]+")


def normalise_category(text: str) -> str:
    """"Follow-up" and "follow up" are one category: `follow_up`."""
    key = _NON_WORD.sub("_", (text or "").strip().lower().replace("-", "_"))
    return re.sub(r"_+", "_", key).strip("_")[:50]


def category_label(key: str | None) -> str | None:
    if not key:
        return None
    return EMAIL_CATEGORY_PRESETS.get(key) or key.replace("_", " ").capitalize()


def _mb(n: int) -> int:
    return n // (1024 * 1024)


def _extension(filename: str) -> str:
    name = (filename or "").lower()
    return name[name.rfind("."):] if "." in name else ""


async def _program(db: AsyncSession, org_id: str, program_id: str) -> Program:
    program = (await db.execute(select(Program).where(
        Program.id == program_id, Program.org_id == org_id))).scalar_one_or_none()
    if program is None:
        raise ValidationFailedError(
            "That product is not one of this organisation's products.")
    return program


def _check_word_file(filename: str, data: bytes) -> None:
    if _extension(filename) != ".docx":
        raise ValidationFailedError(
            "Upload a Word document (.docx). A .doc or a PDF cannot be filled in.")
    if not data:
        raise ValidationFailedError("The uploaded file is empty.")
    if len(data) > MAX_TEMPLATE_BYTES:
        raise ValidationFailedError(
            f"That file is larger than {_mb(MAX_TEMPLATE_BYTES)} MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                raise KeyError("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValidationFailedError(
            "That is not a Word document. Save it from Word or Google Docs as "
            ".docx and upload it again.") from exc


def _check_kind(template_type: str, category: str | None,
                program_id: str | None, built_document: str) -> str | None:
    """The type rules, and the normalised category. Plain words for an admin."""
    if template_type not in [t.value for t in EmailTemplateType]:
        raise ValidationFailedError("Choose Common email or Product email.")
    if built_document not in [b.value for b in BuiltDocument]:
        raise ValidationFailedError(
            "The built document must be none, the proposal or the MoU.")
    if template_type == EmailTemplateType.COMMON.value:
        if program_id:
            raise ValidationFailedError(
                "A common email does not belong to a product. Choose Product "
                "email to tie it to one.")
        if built_document != BuiltDocument.NONE.value:
            raise ValidationFailedError(
                "Only a product email can carry the client's built proposal or "
                "MoU.")
        key = normalise_category(category or "")
        if not key:
            raise ValidationFailedError("A common email needs a category.")
        return key
    if not program_id:
        raise ValidationFailedError("A product email needs a product.")
    if category:
        raise ValidationFailedError(
            "A product email is grouped by its product and has no category.")
    return None


async def create_template(
    db: AsyncSession, ctx: OrgContext, *, template_type: str,
    category: str | None, program_id: str | None, name: str,
    when_to_use: str | None, built_document: str, filename: str, data: bytes,
) -> EmailTemplate:
    name = (name or "").strip()
    if not name:
        raise ValidationFailedError("Give the template a name.")
    category = _check_kind(template_type, category, program_id, built_document)
    if program_id:
        await _program(db, ctx.org_id, program_id)
    _check_word_file(filename, data)
    rendered = email_render.render(data)   # refuses a file with no subject line
    occurrences = [o.as_dict() for o in docx_tags.scan(data)]

    previous = (await db.execute(
        select(EmailTemplate).where(
            EmailTemplate.org_id == ctx.org_id, EmailTemplate.name == name)
        .order_by(EmailTemplate.version.desc()))).scalars().all()
    carried: list[EmailTemplateAttachment] = []
    for row in previous:
        if row.is_current:
            carried = await attachments_of(db, row.id)
            row.is_current = False

    template = EmailTemplate(
        org_id=ctx.org_id, template_type=template_type, category=category,
        program_id=program_id or None, name=name,
        when_to_use=(when_to_use or "").strip()[:300] or None,
        version=(previous[0].version + 1) if previous else 1, is_current=True,
        built_document=built_document, subject_raw=rendered.subject[:500],
        source_path=storage.save_bytes(ctx.org_id, CATEGORY, filename, data),
        filename=filename, sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data), tags_json=occurrences, created_by=ctx.user_id,
    )
    db.add(template)
    await db.flush()
    # A new version of the Word file keeps the files the admin already added:
    # re-uploading a corrected subject line must not silently drop a brochure.
    for att in carried:
        db.add(EmailTemplateAttachment(
            org_id=ctx.org_id, template_id=template.id, filename=att.filename,
            path=att.path, size_bytes=att.size_bytes,
            content_type=att.content_type))
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.email_template_uploaded", entity_type="email_template",
        entity_id=template.id,
        detail={"name": name, "version": template.version,
                "type": template_type, "category": category,
                "program_id": program_id, "tags": len(occurrences)})
    await db.flush()
    return template


async def get_template(db: AsyncSession, org_id: str,
                       template_id: str) -> EmailTemplate:
    row = (await db.execute(select(EmailTemplate).where(
        EmailTemplate.id == template_id,
        EmailTemplate.org_id == org_id))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Email template not found.")
    return row


async def attachments_of(db: AsyncSession,
                         template_id: str) -> list[EmailTemplateAttachment]:
    return list((await db.execute(
        select(EmailTemplateAttachment)
        .where(EmailTemplateAttachment.template_id == template_id)
        .order_by(EmailTemplateAttachment.created_at))).scalars().all())


async def add_attachment(db: AsyncSession, ctx: OrgContext, template_id: str,
                         filename: str, data: bytes) -> EmailTemplateAttachment:
    template = await get_template(db, ctx.org_id, template_id)
    ext = _extension(filename)
    if ext not in ALLOWED_ATTACHMENTS:
        raise ValidationFailedError(
            "That kind of file cannot be attached. Use PDF, Word, PowerPoint, "
            "Excel or an image (PNG or JPG).")
    if not data:
        raise ValidationFailedError("The uploaded file is empty.")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValidationFailedError(
            f"One attachment can be at most {_mb(MAX_ATTACHMENT_BYTES)} MB.")
    used = (await db.execute(
        select(func.coalesce(func.sum(EmailTemplateAttachment.size_bytes), 0))
        .where(EmailTemplateAttachment.template_id == template.id))).scalar_one()
    if used + len(data) > MAX_ATTACHMENTS_TOTAL:
        raise ValidationFailedError(
            f"A template's attachments can be at most "
            f"{_mb(MAX_ATTACHMENTS_TOTAL)} MB together, so the email stays "
            "under the 25 MB most mail providers accept.")
    row = EmailTemplateAttachment(
        org_id=ctx.org_id, template_id=template.id, filename=filename,
        path=storage.save_bytes(ctx.org_id, CATEGORY, filename, data),
        size_bytes=len(data), content_type=_CONTENT_TYPES[ext])
    db.add(row)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.email_template_attachment_added",
        entity_type="email_template", entity_id=template.id,
        detail={"filename": filename, "size_bytes": len(data)})
    await db.flush()
    return row


async def remove_attachment(db: AsyncSession, ctx: OrgContext,
                            template_id: str, attachment_id: str) -> None:
    template = await get_template(db, ctx.org_id, template_id)
    row = (await db.execute(select(EmailTemplateAttachment).where(
        EmailTemplateAttachment.id == attachment_id,
        EmailTemplateAttachment.template_id == template.id,
    ))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Attachment not found.")
    await db.delete(row)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.email_template_attachment_removed",
        entity_type="email_template", entity_id=template.id,
        detail={"filename": row.filename})
    await db.flush()


async def remove_template(db: AsyncSession, ctx: OrgContext,
                          template_id: str) -> None:
    """Remove one version. If it was current, the highest remaining version of
    the same name becomes current, the way the other template families do."""
    template = await get_template(db, ctx.org_id, template_id)
    was_current, name = template.is_current, template.name
    for att in await attachments_of(db, template.id):
        await db.delete(att)
    await db.delete(template)
    await db.flush()
    if was_current:
        predecessor = (await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.org_id == ctx.org_id, EmailTemplate.name == name)
            .order_by(EmailTemplate.version.desc()).limit(1))).scalar_one_or_none()
        if predecessor is not None:
            predecessor.is_current = True
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.email_template_removed", entity_type="email_template",
        entity_id=template_id, detail={"name": name})
    await db.flush()


async def all_templates(db: AsyncSession, org_id: str) -> list[EmailTemplate]:
    return list((await db.execute(
        select(EmailTemplate).where(EmailTemplate.org_id == org_id)
        .order_by(EmailTemplate.is_current.desc(), EmailTemplate.name,
                  EmailTemplate.version.desc()))).scalars().all())


async def current_templates(db: AsyncSession,
                            org_id: str) -> list[EmailTemplate]:
    return list((await db.execute(
        select(EmailTemplate).where(
            EmailTemplate.org_id == org_id, EmailTemplate.is_current.is_(True))
        .order_by(EmailTemplate.template_type, EmailTemplate.name))).scalars().all())


async def product_template_for(db: AsyncSession, org_id: str, program_id: str,
                               built_document: str) -> EmailTemplate | None:
    return (await db.execute(
        select(EmailTemplate).where(
            EmailTemplate.org_id == org_id,
            EmailTemplate.is_current.is_(True),
            EmailTemplate.template_type == EmailTemplateType.PRODUCT.value,
            EmailTemplate.program_id == program_id,
            EmailTemplate.built_document == built_document)
        .order_by(EmailTemplate.created_at.desc()).limit(1))).scalar_one_or_none()


async def categories(db: AsyncSession, org_id: str) -> list[dict[str, str]]:
    used = (await db.execute(
        select(EmailTemplate.category).where(
            EmailTemplate.org_id == org_id,
            EmailTemplate.category.isnot(None)).distinct())).scalars().all()
    out = [{"key": k, "label": v} for k, v in EMAIL_CATEGORY_PRESETS.items()]
    for key in sorted(set(used) - set(EMAIL_CATEGORY_PRESETS)):
        out.append({"key": key, "label": category_label(key)})
    return out


def summary(template: EmailTemplate, attachments: list[EmailTemplateAttachment],
            *, program_name: str | None) -> dict[str, Any]:
    """What the dashboard shows for one template version."""
    found = template.tags_json or []
    try:
        data = storage.read_bytes(template.org_id, template.source_path)
        leftover = draft_check.find_blanks(email_render.render(data).text)
    except Exception:  # noqa: BLE001 -- a summary never fails a listing
        leftover = []
    return {
        "id": template.id,
        "template_type": template.template_type,
        "category": template.category,
        "category_label": category_label(template.category),
        "program_id": template.program_id,
        "program_name": program_name,
        "name": template.name,
        "when_to_use": template.when_to_use,
        "version": template.version,
        "is_current": bool(template.is_current),
        "built_document": template.built_document,
        "subject": template.subject_raw,
        "filename": template.filename,
        "tags": len(found),
        "always_asked": sum(1 for t in found
                            if t.get("kind") in ("ask", "ask_calculate")),
        "distinct": sorted({t.get("raw", "") for t in found}),
        "leftover_blanks": leftover,
        "attachments": [{"id": a.id, "filename": a.filename,
                         "size_bytes": a.size_bytes} for a in attachments],
    }


async def summaries(db: AsyncSession, org_id: str,
                    templates: list[EmailTemplate]) -> list[dict[str, Any]]:
    names = dict((await db.execute(
        select(Program.id, Program.name).where(Program.org_id == org_id))).all())
    return [summary(t, await attachments_of(db, t.id),
                    program_name=names.get(t.program_id)) for t in templates]
