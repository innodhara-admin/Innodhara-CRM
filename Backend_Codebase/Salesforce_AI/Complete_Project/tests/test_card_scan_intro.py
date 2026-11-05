"""Finding F38 — a corrected address could reach an already-queued message by no
path at all.

The card scanner was **write-then-verify**: the contact *and* the intro email
were created and committed straight from the OCR result, before any human saw
the verify sheet. The scan misread `mekaghni@` as `mekaghnni@`. Correcting the
contact fixed the contact and left the queued intro addressed to a dead mailbox
— and rejecting it produced a redraft carrying the **same** wrong address, whose
approval card no longer even showed it.

The tempting fix — re-resolve `to_address` from `contact_id` — is the single most
dangerous wrong fix in FINDINGS.md: it breaks WhatsApp, explicitly-typed
recipients, and proposal emails that carry no contact_id at all.

The product owner's decision removes the problem instead of patching it: the scan
PROPOSES fields, the human edits them, and only the contact's **final saved
contents** count. So the intro is drafted on save. A corrected address is simply
the address the draft is built from — there is no stale draft to chase.
"""
from __future__ import annotations

import io

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio

_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64  # enough to be a non-empty upload


@pytest.fixture
async def intro_template(client, org_a):
    """The org needs an intro template or drafting fails honestly with
    "ask your Org Admin to add one" — which is correct behaviour, but it would
    hide whether the address reached the draft."""
    resp = await client.post(
        "/api/v1/admin/message-templates", headers=auth(org_a["admin_token"]),
        json={"kind": "intro", "channel": "email", "name": "Standard intro",
              "subject": "Great meeting you",
              "body": "Dear {contact_name}, it was a pleasure meeting you. {sender_name}"},
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
def fake_ocr(monkeypatch):
    """The real misread from Round 7 Act 2: one doubled letter in the address."""
    from app.ai import vision

    async def _scan(image, mime, *, org_id=None, user_id=None):
        # 0.86 is the real confidence from Act 2 — comfortably over the 0.7
        # needs_review threshold, which is the point: the gate behaved
        # correctly and the address was still wrong.
        return vision.CardScanResult(
            name="EKAGHNI MUKHERJEE", title="Engineer",
            email="mekaghnni@telaverge.com",          # ← the OCR error
            phone="+91 93105 24629",
            organisation="Telaverge Communications (I) Pvt. Ltd",
            confidence=0.86,
        )

    monkeypatch.setattr(vision, "read_business_card", _scan)


async def _scan_card(client, token, lead_id):
    return await client.post(
        f"/api/v1/leads/{lead_id}/contacts/from-card",
        headers=auth(token),
        data={"draft_intro": "true", "intro_channel": "email"},
        files={"file": ("card.jpg", io.BytesIO(_JPEG), "image/jpeg")},
    )


async def _intros_for(contact_id: str):
    from app.database import SessionLocal
    from app.models.messaging import OutboundMessage
    from sqlalchemy import select

    async with SessionLocal() as db:
        return (
            await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.contact_id == contact_id,
                    OutboundMessage.kind == "intro",
                )
            )
        ).scalars().all()


async def test_scanning_a_card_queues_nothing_yet(client, org_a, fake_ocr):
    """The inversion. Nothing may be drafted from raw OCR."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F38 Scan Co"})
    ).json()
    resp = await _scan_card(client, token, lead["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["intro_message"] is None, (
        "F38: an intro was drafted from unverified OCR — the human has not even "
        "seen the fields yet"
    )
    assert body["intro_pending"] is True, (
        "the sheet needs to know an intro WILL be drafted, or it cannot say so "
        "honestly"
    )
    assert await _intros_for(body["contact"]["id"]) == []


async def test_the_saved_correction_is_what_gets_drafted(
    client, org_a, fake_ocr, intro_template
):
    """F38's exact scenario, end to end: fix the address, save, and the draft
    goes to the corrected one."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F38 Correction Co"})
    ).json()
    contact = (await _scan_card(client, token, lead["id"])).json()["contact"]
    assert contact["email"] == "mekaghnni@telaverge.com"  # the misread, as scanned

    # The human fixes the doubled letter and saves.
    resp = await client.patch(
        f"/api/v1/leads/contacts/{contact['id']}", headers=auth(token),
        json={"name": "EKAGHNI MUKHERJEE", "title": "Engineer",
              "email": "mekaghni@telaverge.com", "phone": "+91 93105 24629"},
    )
    assert resp.status_code == 200, resp.text

    intros = await _intros_for(contact["id"])
    assert len(intros) == 1, f"expected exactly one intro, got {len(intros)}"
    assert intros[0].to_address == "mekaghni@telaverge.com", (
        f"F38: the draft went to the OCR's misread address, not the one the "
        f"human confirmed: {intros[0].to_address}"
    )


async def test_saving_twice_does_not_queue_a_second_introduction(
    client, org_a, fake_ocr, intro_template
):
    """You introduce yourself once. Editing a contact months later must not mail
    them again."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F38 Once Co"})
    ).json()
    contact = (await _scan_card(client, token, lead["id"])).json()["contact"]
    payload = {"name": "EKAGHNI MUKHERJEE", "email": "mekaghni@telaverge.com"}
    for _ in range(3):
        await client.patch(f"/api/v1/leads/contacts/{contact['id']}",
                           headers=auth(token), json=payload)
    assert len(await _intros_for(contact["id"])) == 1


async def test_abandoning_the_sheet_leaves_nothing_queued(client, org_a, fake_ocr):
    """The honesty win. Before, walking away left a draft nobody had vouched
    for; now nothing exists until a human commits to it."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F38 Abandoned Co"})
    ).json()
    contact = (await _scan_card(client, token, lead["id"])).json()["contact"]
    # No PATCH — the user backed out of the verify sheet.
    assert await _intros_for(contact["id"]) == []


async def test_editing_an_ordinary_contact_never_mails_anyone(client, org_a):
    """The blast-radius control: PATCH is the generic contact editor, used for
    hand-added people too. Only card-sourced contacts get an introduction."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F38 Manual Co"})
    ).json()
    contact = (
        await client.post(f"/api/v1/leads/{lead['id']}/contacts", headers=auth(token),
                          json={"name": "Typed By Hand",
                                "email": "typed@alpha-example.com"})
    ).json()
    resp = await client.patch(
        f"/api/v1/leads/contacts/{contact['id']}", headers=auth(token),
        json={"name": "Typed By Hand", "email": "typed2@alpha-example.com"},
    )
    assert resp.status_code == 200, resp.text
    assert await _intros_for(contact["id"]) == [], (
        "editing a hand-entered contact queued an introduction to them"
    )
