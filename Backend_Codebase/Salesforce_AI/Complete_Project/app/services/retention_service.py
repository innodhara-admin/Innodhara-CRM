"""Data protection: retention sweeps and right-to-be-forgotten (doc §14).

- Raw audio is deleted after each org's audio_retention_days.
- Transcripts are archived (text scrubbed) after transcript_retention_days.
- Assistant conversations are dropped after assistant_history_retention_days —
  a chat transcript is working memory, not a record, so it must not become a
  permanent store of whatever people typed into it.
- erase_contact removes a person's data from the database, the files and the
  per-org memory store — "not just hide them".
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.assistant import AssistantTurn
from app.models.base import utcnow
from app.models.lead import Contact
from app.models.location import LocationPing
from app.models.meeting import Meeting, Transcript
from app.models.memory import MemoryChunk
from app.models.messaging import OutboundMessage
from app.models.organisation import Organisation, OrgSettings
from app.services import audit_service, storage


async def run_retention_sweep(db: AsyncSession) -> dict[str, int]:
    """Apply every organisation's retention policy. Returns counters."""
    audio_deleted = 0
    transcripts_archived = 0
    now = utcnow()

    orgs = (await db.execute(select(Organisation))).scalars().all()
    for org in orgs:
        settings_row = (
            await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))
        ).scalar_one_or_none()
        audio_days = settings_row.audio_retention_days if settings_row else 90
        transcript_days = settings_row.transcript_retention_days if settings_row else 365

        # 1) Delete raw audio past its retention window.
        audio_cutoff = now - timedelta(days=audio_days)
        meetings = (
            await db.execute(
                select(Meeting).where(
                    Meeting.org_id == org.id,
                    Meeting.created_at < audio_cutoff,
                    Meeting.audio_path.is_not(None),
                    Meeting.audio_deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for meeting in meetings:
            storage.delete_file(org.id, meeting.audio_path)
            meeting.audio_path = None
            meeting.audio_deleted_at = now
            audio_deleted += 1

        # 2) Archive transcripts past their window (keep the short summary).
        transcript_cutoff = now - timedelta(days=transcript_days)
        transcripts = (
            await db.execute(
                select(Transcript).where(
                    Transcript.org_id == org.id,
                    Transcript.created_at < transcript_cutoff,
                    Transcript.archived_at.is_(None),
                )
            )
        ).scalars().all()
        for transcript in transcripts:
            transcript.text = "[archived per retention policy]"
            transcript.archived_at = now
            transcripts_archived += 1

    # 3) Drop assistant conversations past their window. Platform-wide rather
    #    than per-org: the window is about the chat buffer's nature, not an
    #    organisation's record-keeping policy.
    chat_cutoff = now - timedelta(days=get_settings().assistant_history_retention_days)
    chats_purged = (
        await db.execute(
            select(func.count())
            .select_from(AssistantTurn)
            .where(AssistantTurn.created_at < chat_cutoff)
        )
    ).scalar_one()
    if chats_purged:
        await db.execute(
            delete(AssistantTurn).where(AssistantTurn.created_at < chat_cutoff)
        )

    # 4) Field location readings (2 Oct 2026): where someone was when they
    #    opened the app is kept LOCATION_RETENTION_DAYS, then deleted.
    location_cutoff = now - timedelta(days=get_settings().location_retention_days)
    locations_purged = (
        await db.execute(
            select(func.count())
            .select_from(LocationPing)
            .where(LocationPing.captured_at < location_cutoff)
        )
    ).scalar_one()
    if locations_purged:
        await db.execute(
            delete(LocationPing).where(LocationPing.captured_at < location_cutoff)
        )

    counters = {
        "audio_deleted": audio_deleted,
        "transcripts_archived": transcripts_archived,
        "assistant_turns_purged": chats_purged,
        "location_pings_purged": locations_purged,
    }
    if any(counters.values()):
        await audit_service.record(
            db, org_id=None, user_id=None, action="retention.sweep", detail=counters
        )
    return counters


async def erase_contact(
    db: AsyncSession, *, org_id: str, contact_id: str, requested_by: str
) -> dict[str, int]:
    """Right to be removed: purge a person's personal data everywhere."""
    contact = (
        await db.execute(
            select(Contact).where(Contact.id == contact_id, Contact.org_id == org_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found")

    counters = {
        "messages_scrubbed": 0, "memory_chunks_deleted": 0, "files_deleted": 0,
        "assistant_turns_deleted": 0,
    }

    # Card image file
    if contact.card_image_path:
        if storage.delete_file(org_id, contact.card_image_path):
            counters["files_deleted"] += 1

    # Scrub their address from past outbound messages (keep the record, drop PII)
    if contact.email or contact.phone:
        for addr in filter(None, [contact.email, contact.phone]):
            messages = (
                await db.execute(
                    select(OutboundMessage).where(
                        OutboundMessage.org_id == org_id,
                        OutboundMessage.to_address == addr,
                    )
                )
            ).scalars().all()
            for m in messages:
                m.to_address = "[erased]"
                m.body = "[erased on data-subject request]"
                counters["messages_scrubbed"] += 1

    # Purge memory chunks that mention the person by name
    if contact.name:
        chunks = (
            await db.execute(
                select(MemoryChunk).where(
                    MemoryChunk.org_id == org_id,
                    MemoryChunk.text.ilike(f"%{contact.name}%"),
                )
            )
        ).scalars().all()
        for chunk in chunks:
            await db.execute(delete(MemoryChunk).where(MemoryChunk.id == chunk.id))
            counters["memory_chunks_deleted"] += 1

        # ...and from assistant conversations, which are free text people
        # typed ("email Anita the proposal") and would otherwise survive an
        # erasure the platform promised was complete.
        counters["assistant_turns_deleted"] = (
            await db.execute(
                select(func.count())
                .select_from(AssistantTurn)
                .where(
                    AssistantTurn.org_id == org_id,
                    AssistantTurn.content.ilike(f"%{contact.name}%"),
                )
            )
        ).scalar_one()
        if counters["assistant_turns_deleted"]:
            await db.execute(
                delete(AssistantTurn).where(
                    AssistantTurn.org_id == org_id,
                    AssistantTurn.content.ilike(f"%{contact.name}%"),
                )
            )

    contact_name = contact.name
    await db.execute(delete(Contact).where(Contact.id == contact_id))
    await audit_service.record(
        db,
        org_id=org_id,
        user_id=requested_by,
        action="privacy.contact_erased",
        entity_type="contact",
        entity_id=contact_id,
        detail={"name_hash": str(hash(contact_name)), **counters},
    )
    return counters
