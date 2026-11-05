"""A refused upload must not leave the recording on disk.

`POST /meetings/upload` wrote the audio and *then* checked F40's consent record,
so every refusal left a file in STORAGE_DIR that no `Meeting` row points at. The
retention sweep walks `Meeting` rows (`retention_service`: "delete raw audio past
its retention window" iterates meetings and clears `meeting.audio_path`), so an
orphan is past every retention window the moment it is written and is never
collected. That is real client audio under a DPDP retention policy.

The reachable path is not exotic. `UploadMeetingWorker` retries on `IOException`,
and a socket reset after the server has committed is a lost *response*, not a
lost request — so the retry arrives to find the consent record already linked to
the first meeting, is correctly refused, and used to leave a second copy of the
recording behind.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.meeting import Meeting
from app.services import storage
from tests.conftest import auth, create_org, open_lead

pytestmark = pytest.mark.asyncio

AUDIO = b"ID3\x03\x00\x00\x00" + b"\x00" * 2048


def _stored(org_id: str) -> list[str]:
    audio_dir = storage._root() / "orgs" / org_id / "audio"  # noqa: SLF001
    return sorted(p.name for p in audio_dir.glob("*")) if audio_dir.is_dir() else []


async def _upload(client, token, lead_id):
    return await client.post(
        "/api/v1/meetings/upload",
        headers={**auth(token), "Idempotency-Key": "minted-at-enqueue"},
        data={"lead_id": lead_id, "consent_confirmed": "true",
              "duration_seconds": "181", "title": "Site walk-through"},
        files={"file": ("meeting.m4a", AUDIO, "audio/mp4")},
    )


async def test_an_upload_with_no_consent_record_stores_nothing(client, super_token):
    org = await create_org(client, super_token, name="Orphan A",
                           slug="orphan-a", domain="orphan-a-example.com")
    token = org["admin_token"]
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Meridian", "city": "Pune"})).json()
    await open_lead(client, token, lead["id"])

    refused = await _upload(client, token, lead["id"])

    assert refused.status_code == 422
    assert _stored(org["id"]) == [], (
        "the refused recording is on disk with no meeting pointing at it, so no "
        "retention sweep will ever remove it"
    )


async def test_a_retried_upload_leaves_exactly_one_recording(client, super_token):
    """The worker's retry, end to end.

    The consent record is single-use — `meeting_id IS NULL` is part of the
    lookup and a successful upload links it — so the second attempt is refused
    and there is no duplicate meeting. What must also be true is that there is
    no duplicate *file*.
    """
    org = await create_org(client, super_token, name="Orphan B",
                           slug="orphan-b", domain="orphan-b-example.com")
    token = org["admin_token"]
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Meridian", "city": "Pune"})).json()
    await open_lead(client, token, lead["id"])
    await client.post(f"/api/v1/leads/{lead['id']}/consent", headers=auth(token),
                      json={"method": "verbal", "note": "Agreed on site"})

    first = await _upload(client, token, lead["id"])
    retry = await _upload(client, token, lead["id"])

    assert first.status_code == 200
    assert retry.status_code == 422, "consent is single-use; the retry must not duplicate"

    async with SessionLocal() as db:
        meetings = (await db.execute(
            select(Meeting).where(Meeting.org_id == org["id"]))).scalars().all()
    assert len(meetings) == 1, "the consent fence should have stopped a second meeting"
    assert len(_stored(org["id"])) == 1, (
        f"{len(_stored(org['id']))} recordings on disk for 1 meeting — the retry "
        "left an orphan"
    )
    assert meetings[0].audio_path.endswith(_stored(org["id"])[0])
