"""Notifications, org-scoped file serving, field dictation, and privacy
(right to be removed)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.context import OrgContext
from app.core.exceptions import ValidationFailedError
from app.database import get_db
from app.models.user import Notification
from app.services import retention_service, storage

router = APIRouter(tags=["misc"])


# ══════════════════════════ Notifications ═══════════════════════════════════
@router.get("/notifications")
async def list_notifications(
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    since: str | None = None,  # ISO datetime — cheap delta polling (G2)
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Notification).where(
        Notification.org_id == ctx.org_id, Notification.user_id == ctx.user_id
    )
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    if since:
        try:
            from datetime import datetime

            stmt = stmt.where(
                Notification.created_at
                > datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            )
        except ValueError:
            raise ValidationFailedError(f"'{since}' is not an ISO datetime")
    notifications = (
        await db.execute(
            stmt.order_by(Notification.created_at.desc())
            .offset(max(offset, 0)).limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "kind": n.kind,
            "entity_type": n.entity_type,
            "entity_id": n.entity_id,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifications
    ]


# ══════════════════════════ Device push registration (G1) ═══════════════════
class DeviceRegisterRequest(BaseModel):
    fcm_token: str
    platform: str = "android"
    app_version: str | None = None


@router.post("/devices")
async def register_device(
    body: DeviceRegisterRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Upsert this device's FCM token for the logged-in user. Called on app
    start and whenever FCM rotates the token."""
    from app.models.base import utcnow
    from app.models.user import DeviceToken

    token = body.fcm_token.strip()
    if len(token) < 20:
        raise ValidationFailedError("That does not look like an FCM token")
    existing = (
        await db.execute(select(DeviceToken).where(DeviceToken.fcm_token == token))
    ).scalar_one_or_none()
    if existing is not None:
        # Token moved to (or re-registered by) this user/org.
        existing.user_id = ctx.user_id
        existing.org_id = ctx.org_id
        existing.platform = body.platform
        existing.app_version = body.app_version
        existing.last_seen_at = utcnow()
    else:
        db.add(DeviceToken(
            org_id=ctx.org_id, user_id=ctx.user_id, fcm_token=token,
            platform=body.platform, app_version=body.app_version,
            last_seen_at=utcnow(),
        ))
    await db.commit()
    from app.services import push_service

    return {"registered": True, "push_enabled": push_service.enabled()}


@router.post("/devices/unregister")
async def unregister_device(
    body: DeviceRegisterRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Called on logout so a shared device stops ringing for the old user."""
    from sqlalchemy import delete

    from app.models.user import DeviceToken

    await db.execute(
        delete(DeviceToken).where(
            DeviceToken.fcm_token == body.fcm_token.strip(),
            DeviceToken.user_id == ctx.user_id,
        )
    )
    await db.commit()
    return {"unregistered": True}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    notification = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.org_id == ctx.org_id,
                Notification.user_id == ctx.user_id,
            )
        )
    ).scalar_one_or_none()
    if notification is not None:
        notification.is_read = True
        await db.commit()
    return {"read": True}


# ══════════════════════════ Files (org-scoped) ══════════════════════════════
@router.get("/files/{rel_path:path}")
async def get_file(
    rel_path: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Serve a stored file — storage.resolve refuses paths outside the
    caller's own orgs/{org_id}/ folder."""
    path = storage.resolve(ctx.org_id, rel_path)
    return FileResponse(path)


# ══════════════════════════ Field dictation ═════════════════════════════════
# Dictation clips are seconds of speech, not meetings. 10 MB at the app's
# 96 kbps AAC is ~14 minutes — far past any sane "speak into a text field",
# while still bounding what one request can cost the CPU.
_MAX_DICTATION_BYTES = 10 * 1024 * 1024


@router.post("/dictate")
async def dictate(
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Transcribe a short recording for a text field and hand the text back.

    This is the keyboard, not the meeting pipeline. The two differ on purpose:

      * It runs DICTATION_WHISPER_MODEL, not the pipeline's medium — someone
        is watching a spinner with a half-typed field open. It was `tiny`
        until 21 Sep 2026, when a spoken client name came back as Russian
        ("Я с Джебиис. Тумку."); `tiny` invents a language when it cannot
        place the accent. It now runs the same ladder as voice mode, limited
        to VOICE_STT_LANGUAGES, and is told the organisation's names.
      * The audio is never written to storage and never touches the database.
        A dictated word is a keystroke; keystrokes are not records, and
        keeping them would create a store of employee voice clips nobody asked
        for and retention has no rule for.
      * No permission gate beyond "logged in and in an org". Dictation is a way
        of typing, so anyone allowed to type into a field is allowed to speak
        into it — gating this on record_meeting would silently take the mic
        away from roles that can still use the keyboard.
    """
    from app.ai import client_draft, stt, voice
    from app.config import get_settings

    audio = await file.read()
    if not audio:
        raise ValidationFailedError("Empty audio file")
    if len(audio) > _MAX_DICTATION_BYTES:
        raise ValidationFailedError("Dictation clip too large (max 10 MB)")

    # The same names voice mode expects (people, recent clients, cities):
    # dictated text is mostly about those. Best-effort — a hint is a nicety,
    # and a failure here must not cost the person their sentence.
    try:
        hint = await client_draft.vocabulary_hint(db, ctx, None)
    except Exception:  # noqa: BLE001
        hint = None
    result = await stt.transcribe(
        audio,
        file.content_type or "audio/mp4",
        org_id=ctx.org_id,
        user_id=ctx.user_id,
        model=get_settings().dictation_whisper_model,
        prompt=hint,
        languages=voice.stt_languages(),
    )
    return {
        "text": result.text,
        "language": result.language,
        "confidence": result.confidence,
        # The verdict, not just the number. The assistant's mic auto-sends what
        # comes back, so a bad transcript becomes a command nobody typed —
        # measured with real Kannada speech, `tiny` returned 6-12% similarity at
        # 0.01-0.41 confidence, and the app sent it anyway because it had no
        # threshold to compare against. Deciding here keeps 0.6 defined once
        # (TranscriptionResult.low_confidence, the same gate meeting review
        # uses) instead of copied into the client where the two would drift.
        "low_confidence": result.low_confidence,
    }


# ══════════════════════════ Privacy (DPDP) ══════════════════════════════════
class EraseContactRequest(BaseModel):
    contact_id: str


@router.post("/privacy/erase-contact")
async def erase_contact(
    body: EraseContactRequest,
    ctx: OrgContext = Depends(require_permission("erase_personal_data")),
    db: AsyncSession = Depends(get_db),
):
    """Right to be removed: purge the person's data from the database, files
    and memory store — not just hide it (doc §14)."""
    counters = await retention_service.erase_contact(
        db, org_id=ctx.org_id, contact_id=body.contact_id, requested_by=ctx.user_id
    )
    await db.commit()
    return {"erased": True, **counters}
