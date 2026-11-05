"""Finding F30 — a draft still carrying `[Name]` must not reach a client, and
finding F29 — the daily digest must use the reader's date, not UTC's.

F30's evidence was three real messages in the demo database, one of them
already 'sent', all reading like *"Vendor Sign-off: [Name]"*. Two of the three
had their first blank at character 397 and 474 — **past** the 300-character
preview the approval card showed — so the defence that "the human approval gate
catches it" was structurally false for exactly the cases that matter.

Both directions matter here more than usual, because this fence can block a
legitimate send: a bracketed *phrase* like "[see attached]" is not a blank and
must go through untouched.
"""
from __future__ import annotations

import uuid

from datetime import date, datetime, timedelta

import pytest

from app.services import draft_check
from tests.conftest import auth

# Marked per-test rather than module-wide: the detector tests below are pure
# functions and do not need an event loop.
asyncio_test = pytest.mark.asyncio


# ── The detector, both directions ────────────────────────────────────────

def test_detector_catches_the_shapes_actually_observed():
    """Every one of these came out of the live demo database."""
    body = (
        "Hello Ms. Mukherjee,\n"
        "Vendor Sign-off: [Name]\n"
        "Designation: [Designation]\n"
        "- Date: [Insert Date]\n"
        "- Timing: [Insert Start Time] – [Insert End Time]\n"
        "- Location/Mode: [Insert Location or Virtual Link]\n"
    )
    blanks = draft_check.find_blanks(body)
    assert "[Name]" in blanks
    assert "[Designation]" in blanks
    assert "[Insert Date]" in blanks
    assert "[Insert Location or Virtual Link]" in blanks
    # And the other fill-in shapes this system can produce.
    assert draft_check.find_blanks("Dear {{contact_name}},") == ["{{contact_name}}"]
    assert draft_check.find_blanks("Hello {client_name},") == ["{client_name}"]
    assert draft_check.find_blanks("Price: TBD") == ["TBD"]


def test_detector_leaves_legitimate_writing_alone():
    """A fence that blocks real sends is worse than the bug. None of these is
    an unfinished draft."""
    for text in (
        "The commercials are attached [see attached] for your records.",
        "We can hold the slot [subject to confirmation from your side].",
        "The total is [Rs 59,000] including taxes.",
        "Our refund policy is handled on a case-by-case basis.",
        "Reach me on +91 98765 43210 any weekday.",
        "He said 'the price [was] agreed last week'.",
    ):
        assert draft_check.find_blanks(text) == [], text


def test_refusal_quotes_the_draft_back():
    """The refusal has to show the line, because the preview was what hid it."""
    body = "Thanks for asking.\n\nVendor Sign-off: [Name]\n\nRegards,\nSiva"
    blanks = draft_check.find_blanks(body)
    message = draft_check.refusal_message(
        blanks, draft_check.blank_lines(body, blanks)
    )
    assert "[Name]" in message
    assert "Vendor Sign-off: [Name]" in message
    assert "Nothing was sent" in message


# ── The fence, through the API ───────────────────────────────────────────

async def _draft(client, token, org, *, body: str, subject: str = "A subject") -> str:
    """A pending_approval message with an approvals row, the shape both
    approve routes act on."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import message_service

    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": f"F30 Co {subject[:8]} {uuid.uuid4().hex[:6]}"})
    ).json()
    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org["id"], user_id=org["agent_id"],
                         role="sales_agent", email="agent@alpha-example.com")
        message = await message_service.create_message(
            db, ctx, kind="follow_up", channel="email",
            to_address="someone@f30-example.com", subject=subject, body=body,
            lead_id=lead["id"], request_approval=True,
        )
        await db.commit()
        return message.id


async def _status(client, token, message_id: str) -> str:
    resp = await client.get(f"/api/v1/messages/{message_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["status"]


UNFINISHED = (
    "Hello,\n\nThank you for your question. Our refund policy is handled "
    "case by case.\n\nVendor Sign-off Contact: [Name] | [Designation]\n\n"
    "Warm regards,\nSiva"
)
FINISHED = (
    "Hello,\n\nThank you for your question. Our refund policy is handled "
    "case by case.\n\nWarm regards,\nSiva"
)


@asyncio_test
async def test_approving_an_unfinished_draft_is_refused_and_nothing_is_sent(
    client, org_a
):
    token = org_a["admin_token"]
    message_id = await _draft(client, token, org_a, body=UNFINISHED)

    resp = await client.post(
        f"/api/v1/messages/{message_id}/approve", headers=auth(token)
    )
    assert resp.status_code == 422, resp.text
    detail = str(resp.json()["detail"])
    assert "[Name]" in detail and "Nothing was sent" in detail, detail
    # The refusal must change nothing: the draft is still waiting, not queued.
    assert await _status(client, token, message_id) == "pending_approval"


@asyncio_test
async def test_a_finished_draft_still_approves_normally(client, org_a):
    """The fence must not become a wall — no regression on the ordinary path."""
    token = org_a["admin_token"]
    message_id = await _draft(client, token, org_a, body=FINISHED)
    resp = await client.post(
        f"/api/v1/messages/{message_id}/approve", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert await _status(client, token, message_id) in ("queued", "sending", "sent")


@asyncio_test
async def test_the_approver_can_confirm_and_send_it_as_it_is(client, org_a):
    """It is a fence, not a veto: rule 1 is that humans approve or edit, so an
    approver who has read the blanks may still choose to send."""
    token = org_a["admin_token"]
    message_id = await _draft(client, token, org_a, body=UNFINISHED)
    resp = await client.post(
        f"/api/v1/messages/{message_id}/approve?allow_blanks=true",
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert await _status(client, token, message_id) in ("queued", "sending", "sent")


@asyncio_test
async def test_the_approvals_inbox_route_is_fenced_too(client, org_a):
    """The inbox is the OTHER way into the same send (handoff §5). Fencing one
    route only would have moved the bug rather than fixed it."""
    from app.core.constants import ApprovalStatus
    from app.database import SessionLocal
    from app.models.comms import Approval
    from sqlalchemy import select

    token = org_a["admin_token"]
    message_id = await _draft(client, token, org_a, body=UNFINISHED)

    async with SessionLocal() as db:
        approval = (await db.execute(
            select(Approval).where(Approval.entity_id == message_id)
        )).scalars().first()
    assert approval is not None, "fixture problem: no approvals row was filed"

    resp = await client.post(
        f"/api/v1/approvals/{approval.id}/decide",
        headers=auth(token), json={"approve": True},
    )
    assert resp.status_code == 422, resp.text
    assert "[Name]" in str(resp.json()["detail"])

    # And the refusal left the approval undecided — it can still be acted on.
    async with SessionLocal() as db:
        row = (await db.execute(
            select(Approval).where(Approval.id == approval.id)
        )).scalar_one()
        assert row.status == ApprovalStatus.PENDING.value
    assert await _status(client, token, message_id) == "pending_approval"


@asyncio_test
async def test_the_blanks_are_visible_before_anyone_taps_approve(client, org_a):
    """Refusing after the tap is the floor. The screen should be able to warn
    first, which needs the blanks on the read."""
    token = org_a["admin_token"]
    message_id = await _draft(client, token, org_a, body=UNFINISHED)
    resp = await client.get(f"/api/v1/messages/{message_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["blanks"] == ["[Name]", "[Designation]"], resp.json()["blanks"]


# ── F29 — the digest reads the reader's date, not UTC's ──────────────────

@asyncio_test
async def test_digest_uses_the_local_date_not_utc(client, org_a, monkeypatch):
    """F29. Written so it holds at ANY hour: the original failure only showed
    between 00:00 and 05:30 IST, and a test that depends on when it is run is
    not a guard. Here UTC is forced to yesterday, which is exactly what the
    clock does during those hours."""
    from app.core.constants import FollowUpStatus
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.followup import FollowUp
    from app.models.lead import Lead
    from app.models.user import User
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": f"F29 Timezone Co {uuid.uuid4().hex[:6]}"})
    ).json()
    async with SessionLocal() as db:
        agent = (await db.execute(
            select(User).where(User.id == org_a["agent_id"])
        )).scalar_one()
        lead_row = (await db.execute(
            select(Lead).where(Lead.id == lead["id"])
        )).scalar_one()
        lead_row.owner_id = agent.id
        db.add(FollowUp(
            org_id=org_a["id"], lead_id=lead["id"], owner_id=agent.id,
            due_date=date.today(), channel="whatsapp",
            status=FollowUpStatus.PENDING.value, note="F29 due today",
        ))
        await db.commit()

    # Force the condition instead of waiting for 1am: UTC is a day behind the
    # reader. Anything bucketing on utcnow().date() now drops today's work.
    monkeypatch.setattr(
        assistant_engine, "utcnow",
        lambda: datetime.combine(date.today(), datetime.min.time()) - timedelta(hours=4),
    )

    async with SessionLocal() as db:
        agent = (await db.execute(
            select(User).where(User.id == org_a["agent_id"])
        )).scalar_one()
        digest = await assistant_engine.build_daily_digest(
            db, org_id=org_a["id"], user=agent
        )
        content = digest.content_md
        await db.commit()

    assert "Follow-ups due" in content, content
    assert "F29 Timezone Co" in content, content
