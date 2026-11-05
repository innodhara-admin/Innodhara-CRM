"""Finding F50 — a client update was dropped and *nothing* recorded that it was.

Round 7 Act 12: Baski completed a `visible_to_client` task. The only stakeholder
flagged `receives_progress_updates` was an addressless contact, so
`draft_client_message` hit `if not to_address: return None, None, []` and stopped.
Correct decision, invisible execution: 0 outbound, 0 approvals, 0 `ai_decisions`,
and not one line in the log. The completing user was told "Done", the lead saw
nothing, the client heard nothing, and no queue anywhere held the discrepancy.

Data Model §5.5 is the contract: "One row = one decision an engine took... Every
decision an engine makes — who to assign, **what to draft**, when to escalate — is
written here", with `needs_human` = "True when the engine stopped and routed to a
person". Deciding *not* to draft is a decision about what to draft.

The function has five refusal paths. Three (`do_not_contact`, `needs_review`, the
courtesy cap) already recorded; two returned bare. These tests pin all of them,
because the defect was the asymmetry rather than any single branch.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _decisions_for_contact(contact_id: str):
    from app.database import SessionLocal
    from app.models.work import AIDecision

    async with SessionLocal() as db:
        return (
            await db.execute(
                select(AIDecision).where(
                    AIDecision.entity_type == "contact",
                    AIDecision.entity_id == contact_id,
                )
            )
        ).scalars().all()


async def test_no_address_refusal_is_recorded_not_silent(client, org_a):
    """F50's exact shape: a contact with neither email nor phone.

    The engine must still refuse — inventing an address would be far worse — but
    the refusal has to be findable afterwards.
    """
    from app.database import SessionLocal
    from app.engines import communication_engine
    from app.models.lead import Contact

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F50 Addressless Co"})
    ).json()

    async with SessionLocal() as db:
        contact = Contact(
            org_id=org_a["id"], lead_id=lead["id"],
            name="Silent Sam", title="Head of Nothing",
            email=None, phone=None, is_primary=True,
        )
        db.add(contact)
        await db.flush()
        contact_id = contact.id

        message, approval, uncovered = await communication_engine.draft_client_message(
            db, org_id=org_a["id"], kind="progress_update",
            purpose="tell the client a visible task finished",
            lead_id=lead["id"], contact=contact,
            facts={"completed": "Revise content per feedback"},
        )
        await db.commit()

    # The refusal itself is correct and must not regress into inventing a recipient.
    assert message is None, "a message must NOT be drafted to a contact with no address"
    assert approval is None
    assert uncovered == []

    rows = await _decisions_for_contact(contact_id)
    assert rows, (
        "F50: the engine stopped and recorded nothing — the client update is "
        "invisible to every human surface (no draft, no approval, no decision row)"
    )
    row = rows[0]
    assert row.needs_human is True, (
        "a refusal a human must act on has to carry needs_human (Data Model §5.5)"
    )
    assert "Silent Sam" in row.reason, (
        f"the reason must name who could not be reached: {row.reason!r}"
    )
    # The reason has to say what to DO, or it is a log line rather than a decision.
    assert "address" in row.reason.lower()


async def test_recorded_refusal_names_the_purpose_that_was_dropped(client, org_a):
    """A decision row that does not say *what* was dropped cannot be acted on.

    Falsification note: this is the check that would fail if someone "fixed" F50
    by recording a generic row. Knowing a draft was refused is useless without
    knowing which one.
    """
    from app.database import SessionLocal
    from app.engines import communication_engine
    from app.models.lead import Contact

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F50 Purpose Co"})
    ).json()

    async with SessionLocal() as db:
        contact = Contact(
            org_id=org_a["id"], lead_id=lead["id"],
            name="Quiet Quinn", email=None, phone=None,
        )
        db.add(contact)
        await db.flush()
        contact_id = contact.id
        await communication_engine.draft_client_message(
            db, org_id=org_a["id"], kind="progress_update",
            purpose="share the signed handover certificate",
            lead_id=lead["id"], contact=contact, facts={},
        )
        await db.commit()

    rows = await _decisions_for_contact(contact_id)
    assert rows, "no decision recorded at all"
    assert any("handover certificate" in r.reason for r in rows), (
        f"the dropped purpose is not recoverable from the record: "
        f"{[r.reason for r in rows]}"
    )


async def test_no_sender_refusal_is_also_recorded(client, org_a):
    """The second bare return — F50 could only code-verify this one.

    `sender is None` needs an ownerless lead, no project, and a fresh thread, so
    `pick_sender` exhausts all four of its fallbacks. Constructed directly because
    no API path produces an ownerless lead.

    This is the "what shape can the check not see?" half: the no-address tests
    above would all pass with this branch left silent.
    """
    from app.database import SessionLocal
    from app.engines import communication_engine
    from app.models.lead import Contact, Lead

    async with SessionLocal() as db:
        lead = Lead(org_id=org_a["id"], name="F50 Ownerless Co", owner_id=None)
        db.add(lead)
        await db.flush()
        contact = Contact(
            org_id=org_a["id"], lead_id=lead.id,
            name="Orphan Omar", email="omar@alpha-example.com",
        )
        db.add(contact)
        await db.flush()
        contact_id = contact.id

        message, _approval, _unc = await communication_engine.draft_client_message(
            db, org_id=org_a["id"], kind="progress_update",
            purpose="confirm the revised schedule",
            lead_id=lead.id, contact=contact, facts={}, sender=None,
        )
        await db.commit()

    assert message is None, (
        "precondition failed: a sender WAS resolved, so this test is not "
        "exercising the branch it claims to — check pick_sender's fallbacks"
    )
    rows = await _decisions_for_contact(contact_id)
    assert rows, "F50's second silent branch: no sender, and still nothing recorded"
    assert rows[0].needs_human is True
    assert "sender" in rows[0].reason.lower(), (
        f"the reason must say a sender was the missing piece: {rows[0].reason!r}"
    )


async def test_a_reachable_contact_still_gets_a_draft(client, org_a):
    """The control. F50's fix must not turn a working path into a refusal.

    Without this, a fix that recorded a decision *and* stopped drafting for
    everyone would pass the two tests above.
    """
    from app.database import SessionLocal
    from app.engines import communication_engine
    from app.models.lead import Contact

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F50 Control Co"})
    ).json()

    async with SessionLocal() as db:
        contact = Contact(
            org_id=org_a["id"], lead_id=lead["id"],
            name="Reachable Rita", email="rita@alpha-example.com", is_primary=True,
        )
        db.add(contact)
        await db.flush()
        message, _approval, _unc = await communication_engine.draft_client_message(
            db, org_id=org_a["id"], kind="progress_update",
            purpose="tell the client a visible task finished",
            lead_id=lead["id"], contact=contact, facts={"completed": "A real task"},
        )
        await db.commit()

    assert message is not None, (
        "a contact WITH an address must still be drafted to — F50's fix is about "
        "recording refusals, not creating new ones"
    )
    assert message.to_address == "rita@alpha-example.com"
