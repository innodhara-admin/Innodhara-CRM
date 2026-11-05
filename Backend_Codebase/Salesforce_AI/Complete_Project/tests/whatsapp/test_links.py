"""Task 4: a PDF a WhatsApp provider can fetch, and nothing else."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.core import signed_links
from app.models.base import utcnow
from app.services import storage
from tests.insights.builders import make_lead, make_meeting, make_org, make_user

pytestmark = pytest.mark.asyncio

ROUTE = "/api/v1/public/wa/"


async def test_round_trip_and_tamper_and_expiry():
    token = signed_links.make({"k": "file", "o": "org1", "p": "orgs/org1/x.pdf"})
    assert signed_links.read(token)["p"] == "orgs/org1/x.pdf"
    body, sig = token.split(".")
    other = signed_links.make({"k": "file", "o": "org2", "p": "orgs/org2/x.pdf"})
    assert signed_links.read(other.split(".")[0] + "." + sig) is None
    assert signed_links.read(token[:-2] + "xx") is None
    assert signed_links.read("nonsense") is None
    assert signed_links.read(signed_links.make({"k": "file"}, ttl_seconds=-1)) is None


async def test_public_url_needs_a_base(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_base_url", "")
    assert signed_links.public_url("abc") is None
    monkeypatch.setattr(get_settings(), "public_base_url", "https://crm.example/")
    assert signed_links.public_url("abc") == "https://crm.example/api/v1/public/wa/abc"


async def test_a_stored_file_is_served(client):
    rel = storage.save_bytes("org-pdf", storage.CATEGORY_PROPOSALS, "p.pdf", b"%PDF-1.4 hello")
    token = signed_links.make({"k": "file", "o": "org-pdf", "p": rel, "n": "Proposal.pdf"})
    resp = await client.get(ROUTE + token)
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert "Proposal.pdf" in resp.headers.get("content-disposition", "")


async def test_another_orgs_file_is_refused(client):
    rel = storage.save_bytes("org-victim", storage.CATEGORY_PROPOSALS, "p.pdf", b"%PDF-1.4 secret")
    token = signed_links.make({"k": "file", "o": "org-thief", "p": rel})
    assert (await client.get(ROUTE + token)).status_code == 404
    token = signed_links.make({"k": "file", "o": "org-thief",
                               "p": "orgs/org-thief/../org-victim/" + rel.split("/", 2)[2]})
    assert (await client.get(ROUTE + token)).status_code == 404


async def test_bad_or_expired_token_is_404(client):
    assert (await client.get(ROUTE + "nonsense")).status_code == 404
    expired = signed_links.make({"k": "file", "o": "x", "p": "y"}, ttl_seconds=-1)
    assert (await client.get(ROUTE + expired)).status_code == 404


async def test_transcript_is_rendered_and_scoped(client, db):
    org = await make_org(db, name="WA Transcript Org")
    other = await make_org(db, name="WA Other Org")
    lead = await make_lead(db, org, name="Transcript Client", state="active",
                           created_at=datetime(2026, 11, 1))
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    meeting = await make_meeting(db, org, lead, by=asha, at=datetime(2026, 11, 2, 6, 0),
                                 summary="They want the <advanced> lab & a demo")
    await db.commit()
    ok = signed_links.make({"k": "transcript", "o": org.id, "m": meeting.id})
    resp = await client.get(ROUTE + ok)
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    wrong_org = signed_links.make({"k": "transcript", "o": other.id, "m": meeting.id})
    assert (await client.get(ROUTE + wrong_org)).status_code == 404


async def test_an_archived_transcript_is_gone(client, db):
    from sqlalchemy import select

    from app.models.meeting import Transcript

    org = await make_org(db, name="WA Archived Org")
    lead = await make_lead(db, org, name="Archived Client", state="active",
                           created_at=datetime(2026, 11, 1))
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    meeting = await make_meeting(db, org, lead, by=asha, at=datetime(2026, 11, 2, 6, 0),
                                 summary="old")
    row = (await db.execute(select(Transcript).where(
        Transcript.meeting_id == meeting.id))).scalar_one()
    row.archived_at = utcnow()
    await db.commit()
    token = signed_links.make({"k": "transcript", "o": org.id, "m": meeting.id})
    assert (await client.get(ROUTE + token)).status_code == 404
