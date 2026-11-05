"""The one route outside the login: a PDF behind a signed link (4 Nov 2026).

A WhatsApp provider downloads a template's document header from here: a
proposal PDF sent to a client, or a meeting transcript sent to the person who
recorded it. See app/core/signed_links.py. Anything the link does not name
exactly, or names outside its own organisation, is a plain 404: the route
never says whether something exists.

A transcript is rendered on request, never stored as a PDF, so the retention
sweep that archives transcripts also ends their links.
"""
from __future__ import annotations

import html

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import signed_links
from app.core.exceptions import NotFoundError
from app.database import get_db
from app.models.lead import Lead
from app.models.meeting import Meeting, Transcript
from app.services import storage

router = APIRouter(prefix="/public", tags=["public"])


def _gone() -> NotFoundError:
    return NotFoundError("Not found")


@router.get("/wa/{token}")
async def whatsapp_document(token: str, db: AsyncSession = Depends(get_db)):
    data = signed_links.read(token)
    if not data or not data.get("o"):
        raise _gone()
    if data.get("k") == "file" and data.get("p"):
        try:
            path = storage.resolve(data["o"], data["p"])
        except Exception:  # noqa: BLE001 — another org's path or a missing file: same 404
            raise _gone() from None
        return FileResponse(path, media_type="application/pdf",
                            filename=data.get("n") or path.name)
    if data.get("k") == "transcript" and data.get("m"):
        return await _transcript_pdf(db, data["o"], data["m"])
    raise _gone()


async def _transcript_pdf(db: AsyncSession, org_id: str, meeting_id: str) -> Response:
    from app.services.document_service import render_pdf

    row = (
        await db.execute(
            select(Transcript, Meeting, Lead)
            .join(Meeting, Meeting.id == Transcript.meeting_id)
            .outerjoin(Lead, Lead.id == Meeting.lead_id)
            .where(Transcript.org_id == org_id, Meeting.org_id == org_id,
                   Transcript.meeting_id == meeting_id,
                   Transcript.archived_at.is_(None))
        )
    ).first()
    if row is None:
        raise _gone()
    transcript, meeting, lead = row
    when = meeting.started_at or meeting.created_at
    title = "Meeting transcript"
    if lead is not None:
        title += f" · {lead.name}"
    if when is not None:
        title += f" · {when:%d %b %Y}"
    # reportlab reads its text as markup, so "<" or "&" said in a meeting
    # would break the render: escape before it gets there.
    parts = [f"# {html.escape(title, quote=False)}"]
    if transcript.summary:
        parts += ["## Summary", html.escape(transcript.summary, quote=False)]
    parts += ["## Transcript", html.escape(transcript.text or "", quote=False)]
    # reportlab is synchronous: a long transcript must not stall every other
    # request while it renders (final review, 4 Nov 2026).
    pdf = await run_in_threadpool(render_pdf, "\n\n".join(parts), title)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="transcript.pdf"'})
