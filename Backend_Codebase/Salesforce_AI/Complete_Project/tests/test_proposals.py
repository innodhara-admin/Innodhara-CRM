"""Proposals: totals from the pricing table (never the AI), version locking,
line-item edits, approval gate, dry-run send, idempotency."""
from __future__ import annotations

import pytest

from app.core.constants import MessageStatus
from app.core.context import OrgContext
from app.database import SessionLocal
from app.jobs.sender import send_message
from app.services import proposal_service
from tests.conftest import auth

pytestmark = pytest.mark.asyncio

TEMPLATE = """# {program_name} Proposal for {school_name}

Dear {contact_name},

{context_summary}

## Commercials

{pricing_table}

Total: {total_amount}

Regards, {sender_name} ({org_name})
"""


@pytest.fixture(scope="module")
async def setup(client, org_a):
    """Program + pricing + template + lead with contact, in org A."""
    token = org_a["admin_token"]
    program = (
        await client.post(
            "/api/v1/admin/programs",
            headers=auth(token),
            json={"name": "IBC", "code": "IBC", "description": "STEM program"},
        )
    ).json()
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing",
        headers=auth(token),
        json={
            "currency": "INR",
            "items": [
                {"code": "workshop", "label": "STEM Workshop",
                 "unit": "per workshop", "unit_price": 2000, "default_quantity": 12},
                {"code": "kit", "label": "Maker Kit",
                 "unit": "per kit", "unit_price": 500, "default_quantity": 10},
            ],
        },
    )
    template_resp = await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Standard", "body_md": TEMPLATE},
    )
    assert template_resp.status_code == 200, template_resp.text

    lead = (
        await client.post(
            "/api/v1/leads", headers=auth(token), json={"name": "Proposal School"}
        )
    ).json()
    await client.post(
        f"/api/v1/leads/{lead['id']}/contacts",
        headers=auth(token),
        json={"name": "Mrs. Principal", "title": "Principal",
              "email": "principal@proposal.test", "is_primary": True},
    )
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    return {
        "program": program,
        "lead": lead,
        "token": token,
        "org_id": me["org_id"],
        "user_id": me["user_id"],
        "email": me["email"],
    }


async def _build(client, setup, **extra) -> dict:
    resp = await client.post(
        "/api/v1/proposals",
        headers=auth(setup["token"]),
        json={"lead_id": setup["lead"]["id"],
              "program_id": setup["program"]["id"], **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_build_proposal_totals_from_pricing_table(client, setup):
    proposal = await _build(client, setup, context_summary="Following our meeting.")
    # 12 workshops x 2000 + 10 kits x 500 = 29000 — computed in code
    assert proposal["total_amount"] == 29000
    assert proposal["template_version"] == 1
    assert proposal["pricing_version"] == 1
    assert "Rs 29,000" in proposal["content_md"]
    assert "Mrs. Principal" in proposal["content_md"]


async def test_requested_quantities_override_defaults(client, setup):
    proposal = await _build(client, setup, quantities={"workshop": 16, "kit": 0})
    # 16 x 2000 + 0 x 500 = 32000
    assert proposal["total_amount"] == 32000


async def test_line_item_ops_recompute_totals_and_document(client, setup):
    proposal = await _build(client, setup)
    ctx = OrgContext(
        org_id=setup["org_id"], user_id=setup["user_id"],
        role="org_admin", email=setup["email"],
    )
    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        notes = proposal_service.apply_line_item_ops(
            row,
            [
                {"op": "set_quantity", "code": "workshop", "quantity": 16},
                {"op": "set_unit_price", "code": "workshop", "unit_price": 1500},
                {"op": "remove_item", "code": "kit"},
            ],
        )
        await proposal_service.record_edit(
            db, ctx, row, instruction="16 workshops at Rs 1500; drop kits"
        )
        await db.commit()
        assert row.total_amount == 24000  # 16 x 1500
        assert "Rs 24,000" in row.content_md
        assert "Maker Kit" not in row.content_md
        assert len(notes) == 3

    detail = (
        await client.get(
            f"/api/v1/proposals/{proposal['id']}", headers=auth(setup["token"])
        )
    ).json()
    assert detail["total_amount"] == 24000
    assert any(r["instruction"] for r in detail["revisions"])


async def test_narrative_edit_cannot_change_numbers(client, setup):
    proposal = await _build(client, setup)
    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        # Model tries to smuggle in a different price — the computed block wins.
        malicious = "# Totally new proposal\n\nEverything free! Total: Rs 1\n"
        proposal_service.apply_narrative_edit(row, malicious)
        assert "Rs 29,000" in row.content_md  # real total re-inserted
        assert row.total_amount == 29000


async def test_download_docx_and_pdf(client, setup):
    proposal = await _build(client, setup)
    for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK")):
        resp = await client.get(
            f"/api/v1/proposals/{proposal['id']}/download?format={fmt}",
            headers=auth(setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.content[:4].startswith(magic)


async def test_approve_send_queues_and_dry_run_sends(client, setup):
    # F47: this used to call `_build` with no context_summary, so the narrative
    # rendered `[missing:context_summary]` and the test asserted it SENT. The
    # blank fence now reads the attached narrative, so the happy path has to
    # supply a complete proposal — which is what a happy path meant all along.
    proposal = await _build(client, setup, context_summary="Following our meeting.")
    resp = await client.post(
        f"/api/v1/proposals/{proposal['id']}/approve-send",
        headers=auth(setup["token"]),
        json={"to_address": "principal@proposal.test",
              "cc": ["owner@proposal.test"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == MessageStatus.QUEUED.value
    message_id = body["message_id"]

    # Run the send worker directly (no background workers in tests).
    result = await send_message({"message_id": message_id}, "test-job")
    assert result.get("sent") is True
    assert result["provider_id"].startswith("dry_run:")

    detail = (
        await client.get(
            f"/api/v1/messages/{message_id}", headers=auth(setup["token"])
        )
    ).json()
    assert detail["status"] == MessageStatus.SENT.value
    assert detail["cc"] == ["owner@proposal.test"]
    events = [e["event"] for e in detail["delivery_log"]]
    assert events[:3] == ["drafted", "queued", "sent"]


async def test_proposal_email_idempotency(client, setup):
    """Same proposal + recipient twice -> one message, no duplicate send."""
    proposal = await _build(client, setup, context_summary="Following our meeting.")
    first = (
        await client.post(
            f"/api/v1/proposals/{proposal['id']}/approve-send",
            headers=auth(setup["token"]),
            json={"to_address": "dup@proposal.test", "cc": []},
        )
    ).json()
    second = (
        await client.post(
            f"/api/v1/proposals/{proposal['id']}/approve-send",
            headers=auth(setup["token"]),
            json={"to_address": "dup@proposal.test", "cc": []},
        )
    ).json()
    assert first["message_id"] == second["message_id"]


async def test_invalid_email_rejected(client, setup):
    proposal = await _build(client, setup)
    resp = await client.post(
        f"/api/v1/proposals/{proposal['id']}/approve-send",
        headers=auth(setup["token"]),
        json={"to_address": "not-an-email", "cc": []},
    )
    assert resp.status_code == 422


async def test_pricing_update_does_not_touch_old_proposals(client, setup):
    proposal = await _build(client, setup)
    assert proposal["pricing_version"] == 1
    await client.post(
        f"/api/v1/admin/programs/{setup['program']['id']}/pricing",
        headers=auth(setup["token"]),
        json={
            "currency": "INR",
            "items": [{"code": "workshop", "label": "STEM Workshop",
                       "unit": "per workshop", "unit_price": 9999,
                       "default_quantity": 1}],
        },
    )
    old = (
        await client.get(
            f"/api/v1/proposals/{proposal['id']}", headers=auth(setup["token"])
        )
    ).json()
    assert old["pricing_version"] == 1
    assert old["total_amount"] == 29000  # locked (doc §12)

    fresh = await _build(client, setup)
    assert fresh["pricing_version"] == 2
    assert fresh["total_amount"] == 9999


async def test_narrative_rewrite_cannot_smuggle_a_discount_into_the_prose():
    """F23: re-inserting the machine table protects the TABLE, but a model told
    to discount writes the discounted figures into the PROSE, which survives.
    The deterministic fence must reject that (a prompt rule did not hold on any
    model tested)."""
    from app.core.exceptions import ValidationFailedError
    from app.models.proposal import Proposal
    from app.services.proposal_service import apply_narrative_edit, narrative_price_drift

    items = [
        {"code": "ws", "label": "Workshop", "unit": "head",
         "unit_price": 1450, "quantity": 16, "line_total": 23200},
        {"code": "mod", "label": "Module", "unit": "module",
         "unit_price": 9500, "quantity": 1, "line_total": 9500},
    ]
    p = Proposal(line_items=items, total_amount=243000, currency="INR", content_md="")

    # Benign rewrites that only echo the real numbers must pass untouched.
    clean = ("We will deliver 16 workshops at Rs 1,450 per head. The total "
             "investment is Rs 243,000, inclusive of one module at Rs 9,500.")
    assert narrative_price_drift(p, clean) == []
    apply_narrative_edit(p, clean)  # does not raise
    assert "1,450" in p.content_md

    # Comma-formatted discount in prose -> caught and rejected.
    bad = ("After the requested 10% discount, the rate is Rs 1,305 per head, "
           "for a revised total of Rs 218,700.")
    drift = narrative_price_drift(p, bad)
    assert "1,305" in drift and "218,700" in drift, drift
    with pytest.raises(ValidationFailedError):
        apply_narrative_edit(p, bad)

    # Bare (comma-less) discounted figures next to a price word are caught too.
    bad2 = "Discounted rate: 1305 per head; new total 218700 all in."
    d2 = narrative_price_drift(p, bad2)
    assert "1305" in d2 and "218700" in d2, d2

    # A year and an audience size must NOT trip the fence (no false positive).
    ok = ("In 2026 we will train 300 students across 3 campuses, "
          "still at Rs 1,450 per head.")
    assert narrative_price_drift(p, ok) == [], narrative_price_drift(p, ok)


# ─────────────────────────────────────────────────────────────────────────────
# Finding F47 — a `[missing:…]` placeholder reached a real client PDF, past a
# guard the app had explicitly run in strict mode.
#
# Three gaps lined up. `template_service.missing_variables()` had zero callers.
# `draft_check` did not recognise the project's own marker (the colon and
# underscores fail `_LABEL`, and "missing" is not a fill word). And all four
# `find_blanks` call sites passed subject+body only — never the attachment,
# which is the one document the client actually reads.
#
# The email body was clean. The PDF opened with `[missing:context_summary]`.
# ─────────────────────────────────────────────────────────────────────────────


async def test_marker_in_the_attachment_blocks_the_send(client, setup):
    """F47 end to end: a clean body cannot carry a dirty attachment past the gate."""
    proposal = await _build(client, setup)  # deliberately no context_summary
    assert "[missing:context_summary]" in proposal["content_md"], (
        "precondition: this test needs an incompletely rendered narrative"
    )
    resp = await client.post(
        f"/api/v1/proposals/{proposal['id']}/approve-send",
        headers=auth(setup["token"]),
        json={"to_address": "principal@proposal.test", "cc": []},
    )
    assert resp.status_code == 422, (
        f"F47: a proposal whose PDF says [missing:...] was accepted for sending "
        f"— got {resp.status_code}: {resp.text}"
    )
    assert "context_summary" in resp.text, (
        f"the refusal must name the unfilled field: {resp.text}"
    )


async def test_the_marker_is_visible_before_anyone_taps_approve(client, setup):
    """The warning and the refusal must agree.

    If `blanks` on the message row ignored the attachment while the approve gate
    checked it, the screen would invite a tap the server then refuses — the
    opposite of this product's honest-refusal pattern.
    """
    from app.database import SessionLocal
    from app.models.messaging import OutboundMessage

    proposal = await _build(client, setup)
    # The message body is deliberately CLEAN. This is F47's exact shape: nothing
    # is wrong with the email, and everything is wrong with what it carries.
    async with SessionLocal() as db:
        message = OutboundMessage(
            org_id=setup["org_id"], lead_id=setup["lead"]["id"],
            proposal_id=proposal["id"], kind="proposal", channel="email",
            to_address="principal@proposal.test",
            subject="Your proposal", body="Dear Mrs. Principal, please find it attached.",
            status=MessageStatus.PENDING_APPROVAL.value,
            sender_user_id=setup["user_id"],
            idempotency_key=f"f47-preview-{proposal['id']}",
        )
        db.add(message)
        await db.flush()
        message_id = message.id
        await db.commit()

    resp = await client.get(
        f"/api/v1/messages/{message_id}", headers=auth(setup["token"])
    )
    assert resp.status_code == 200, resp.text
    assert any("missing:context_summary" in b for b in resp.json()["blanks"]), (
        f"the approver is shown no warning for a blank the gate will refuse: "
        f"{resp.json()['blanks']}"
    )


async def test_a_complete_proposal_still_sends(client, setup):
    """The control: F47's fix must not block proposals that are actually finished."""
    proposal = await _build(client, setup, context_summary="Following our meeting.")
    assert "[missing:" not in proposal["content_md"]
    resp = await client.post(
        f"/api/v1/proposals/{proposal['id']}/approve-send",
        headers=auth(setup["token"]),
        json={"to_address": "principal@proposal.test", "cc": []},
    )
    assert resp.status_code == 200, resp.text


async def test_an_unfilled_proposal_is_escalated_when_it_is_BUILT(client, setup):
    """F47's third gap: the marker exists "so a human notices" and nothing looked.

    Catching it at the approve gate blocks the damage; catching it at creation is
    what makes it fixable. `missing_variables` had zero callers before this.
    """
    from app.database import SessionLocal
    from app.models.work import AIDecision
    from sqlalchemy import select

    proposal = await _build(client, setup)  # no context_summary
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(AIDecision).where(
                    AIDecision.entity_type == "proposal",
                    AIDecision.entity_id == proposal["id"],
                )
            )
        ).scalars().all()
    assert rows, "a proposal rendered with blanks recorded nothing at creation"
    assert rows[0].needs_human is True
    assert "context_summary" in rows[0].reason, rows[0].reason


# ─────────────────────────────────────────────────────────────────────────────
# Found live on 2026-08-06, during the datacentre demo build.
#
# A proposal was drafted while it still read `[missing:context_summary]`. The
# blank was then filled, and the PDF correctly re-rendered to a NEW file. The
# email that reached the client carried the OLD attachment and the OLD body.
#
#   proposal.pdf_path      -> .../7bb628c5_...pdf   (fixed)
#   message.attachments[0] -> .../000567ef_...pdf   (the [missing:] one)  ← SENT
#
# Cause: `create_message` returns an existing message untouched when the
# idempotency key matches (`proposal-email-{id}-{address}`). That guard exists
# to stop a DOUBLE SEND; it was also freezing a draft nobody had approved.
#
# This is [F38] one level up — a correction that reaches the record but never
# the queued message — and [F47]'s fence made it sharper, because the fence
# reads the CURRENT proposal (clean, so it passes) while the send used the stale
# attachment.
# ─────────────────────────────────────────────────────────────────────────────


async def test_fixing_a_proposal_updates_the_draft_that_has_not_been_sent(client, setup):
    """The live bug, end to end: fix the blank, re-prepare, and the SAME draft
    must now carry the new PDF and the new body."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import proposal_email_service, proposal_service

    ctx = OrgContext(org_id=setup["org_id"], user_id=setup["user_id"],
                     role="org_admin", email=setup["email"])
    proposal = await _build(client, setup)  # no context_summary -> [missing:]
    assert "[missing:context_summary]" in proposal["content_md"]

    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        first = await proposal_email_service.prepare_proposal_email(
            db, ctx, row, to_address="kavitha@proposal.test",
        )
        await db.commit()
        first_id, stale_pdf = first.id, first.attachments[0]["path"]

    # The human fills the blank — exactly what Jarvis did on the demo.
    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        proposal_service.apply_narrative_edit(
            row, row.content_md.replace(
                "[missing:context_summary]",
                "Two halls, 120 racks, commissioning from 1 September.",
            ),
        )
        await proposal_service.record_edit(db, ctx, row, instruction="fill the blank")
        await db.commit()

    # Ask to email it again — same proposal, same recipient.
    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        second = await proposal_email_service.prepare_proposal_email(
            db, ctx, row, to_address="kavitha@proposal.test",
        )
        await db.commit()
        second_id, fresh_pdf = second.id, second.attachments[0]["path"]
        body = second.body

    assert second_id == first_id, (
        "idempotency broke — a second request created a DUPLICATE draft, which "
        "is the double-send this guard exists to prevent"
    )
    assert fresh_pdf != stale_pdf, (
        f"the draft still attaches the OLD pdf. This is what reached a real "
        f"client: {stale_pdf}"
    )

    assert "[missing:" not in body


async def test_a_message_already_sent_is_never_rewritten(client, setup):
    """The other half. Refreshing a draft is right; rewriting history is not —
    a sent message must keep the exact words that left the building."""
    from app.core.constants import MessageStatus
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import message_service, proposal_email_service, proposal_service

    ctx = OrgContext(org_id=setup["org_id"], user_id=setup["user_id"],
                     role="org_admin", email=setup["email"])
    proposal = await _build(client, setup, context_summary="Original summary.")

    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        msg = await proposal_email_service.prepare_proposal_email(
            db, ctx, row, to_address="sent@proposal.test",
        )
        msg.status = MessageStatus.SENT.value
        sent_body, msg_id = msg.body, msg.id
        await db.commit()

    async with SessionLocal() as db:
        row = await proposal_service.get_proposal(db, setup["org_id"], proposal["id"])
        again = await proposal_email_service.prepare_proposal_email(
            db, ctx, row, to_address="sent@proposal.test",
        )
        await db.commit()
        assert again.id == msg_id
        assert again.body == sent_body, (
            "a message that has already SENT was rewritten — the record no "
            "longer matches what the client received"
        )
        assert again.status == MessageStatus.SENT.value
