"""Word email templates, managed from the dashboard's item 7 (28 Oct 2026)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.context import OrgContext
from app.database import get_db
from app.services import email_template_service as svc

router = APIRouter(prefix="/admin/email-templates", tags=["org admin"])


@router.post("")
async def upload_email_template(
    template_type: str = Form(...),
    name: str = Form(...),
    category: str | None = Form(None),
    program_id: str | None = Form(None),
    when_to_use: str | None = Form(None),
    built_document: str = Form("none"),
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    template = await svc.create_template(
        db, ctx, template_type=template_type, category=category,
        program_id=program_id, name=name, when_to_use=when_to_use,
        built_document=built_document, filename=(file.filename or "").strip(),
        data=await file.read())
    out = (await svc.summaries(db, ctx.org_id, [template]))[0]
    await db.commit()
    return out


@router.get("")
async def list_email_templates(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await svc.summaries(db, ctx.org_id,
                               await svc.all_templates(db, ctx.org_id))


@router.get("/categories")
async def list_email_categories(
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    return await svc.categories(db, ctx.org_id)


@router.delete("/{template_id}")
async def delete_email_template(
    template_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    await svc.remove_template(db, ctx, template_id)
    await db.commit()
    return {"deleted": True}


@router.post("/{template_id}/attachments")
async def add_email_template_attachment(
    template_id: str,
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    row = await svc.add_attachment(db, ctx, template_id,
                                   (file.filename or "").strip(),
                                   await file.read())
    await db.commit()
    return {"id": row.id, "filename": row.filename, "size_bytes": row.size_bytes}


@router.delete("/{template_id}/attachments/{attachment_id}")
async def delete_email_template_attachment(
    template_id: str,
    attachment_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    await svc.remove_attachment(db, ctx, template_id, attachment_id)
    await db.commit()
    return {"deleted": True}
