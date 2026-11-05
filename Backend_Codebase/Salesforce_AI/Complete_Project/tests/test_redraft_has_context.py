"""A rejection note that asks for a FACT must be answerable.

Reported live 2026-08-07:

    "A demo is scheduled. In the approval stage I pressed reject and in the
     note I said 'add the demo date too'. Then it redrafted the mail asking —
     'Also, could you please confirm the demo date?' ... we have already given
     the demo date via mail. Why didn't it say that date in the redrafted mail?"

Because it could not. `redraft_rejected` called `compose_body` with:

    facts={"original_draft": message.body}
    sender_name="", org_name=""

That is the whole context. No project, no demo, no sender, no organisation.
`compose_body`'s system prompt says "Use ONLY the facts provided — never invent
numbers, dates or promises", so a model asked to add a date it had not been
given had exactly two options: invent one, or ask. **It asked.** That is the
correct behaviour of a blind path, which is why nothing looked broken.

The asymmetry is the bug: `draft_client_message` composes with caller-supplied
`facts`, the sender's real name, the org name and the stakeholder's language.
The redraft path threw all four away and re-derived none of them.

The fix gives the redraft the same context. It does NOT relax the "only the
facts provided" rule — with nothing scheduled there is no `scheduled_demos`
line, and the model still cannot invent a date.
"""
from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def _setup(org, *, demo_dates: list[tuple[date, str, str]]):
    """A lead + contact + a queued message, with N demos in given statuses."""
    from app.database import SessionLocal
    from app.models.demo import Demo
    from app.models.lead import Contact, Lead
    from app.models.messaging import OutboundMessage

    async with SessionLocal() as db:
        lead = Lead(org_id=org["id"], name="Meridian Data Centres", state="active")
        db.add(lead)
        await db.flush()
        contact = Contact(org_id=org["id"], lead_id=lead.id, name="Kavitha Rao",
                          email="kavitha@dc.test", is_primary=True)
        db.add(contact)
        for d, t, status in demo_dates:
            db.add(Demo(org_id=org["id"], lead_id=lead.id, scheduled_date=d,
                        scheduled_time=t, status=status))
        await db.flush()
        message = OutboundMessage(
            org_id=org["id"], kind="follow_up", channel="email",
            lead_id=lead.id, contact_id=contact.id,
            sender_user_id=org["agent_id"],
            to_address="kavitha@dc.test", subject="Site walkthrough",
            body="Dear Kavitha,\n\nLooking forward to the walkthrough.\n\nSiva",
            status="draft",
            idempotency_key=uuid4().hex,
        )
        db.add(message)
        await db.flush()
        mid = message.id
        await db.commit()
    return mid


async def _captured_compose(monkeypatch):
    """Run a redraft with compose_body stubbed, and return what it was given."""
    captured: dict = {}

    from app.engines import communication_engine

    async def _fake_compose(**kwargs):
        captured.update(kwargs)
        return "redrafted body"

    monkeypatch.setattr(communication_engine, "compose_body", _fake_compose)
    monkeypatch.setattr(communication_engine.nlu, "llm_available", lambda: True)
    return captured


async def _run(org, message_id: str, instruction: str):
    from app.database import SessionLocal
    from app.engines import communication_engine
    from app.models.messaging import OutboundMessage
    from sqlalchemy import select

    async with SessionLocal() as db:
        message = (
            await db.execute(
                select(OutboundMessage).where(OutboundMessage.id == message_id)
            )
        ).scalar_one()
        await communication_engine.redraft_rejected(
            db, org_id=org["id"], message=message, instruction=instruction,
        )
        await db.commit()


async def test_the_redraft_is_given_the_demo_date(org_a, monkeypatch):
    """The headline, in the words of the report."""
    captured = await _captured_compose(monkeypatch)
    mid = await _setup(org_a, demo_dates=[(date(2026, 9, 18), "14:30", "scheduled")])

    await _run(org_a, mid, "add the demo date too")

    demos = captured["facts"].get("scheduled_demos")
    assert demos, (
        "the redraft still has no demo in its facts, so the model can only ask "
        "the client to confirm a date we already scheduled"
    )
    assert demos[0]["date"] == "2026-09-18"
    assert demos[0]["time"] == "14:30"


async def test_the_redraft_knows_who_is_writing_and_from_where(org_a, monkeypatch):
    """`sender_name=""` and `org_name=""` were hardcoded — the redraft could not
    even sign itself, though the system prompt tells it to."""
    captured = await _captured_compose(monkeypatch)
    mid = await _setup(org_a, demo_dates=[])

    await _run(org_a, mid, "make it warmer")

    assert captured["sender_name"], "the redraft does not know who is sending it"
    assert captured["org_name"], "the redraft does not know the organisation"


async def test_no_demo_means_no_demo_fact_so_it_cannot_invent_one(org_a, monkeypatch):
    """The honesty half. Nothing scheduled must leave the key ABSENT — an empty
    list invites the model to fill it."""
    captured = await _captured_compose(monkeypatch)
    mid = await _setup(org_a, demo_dates=[])

    await _run(org_a, mid, "add the demo date too")

    assert "scheduled_demos" not in captured["facts"], (
        "an empty demo list was passed; the model must be given nothing at all"
    )


async def test_a_cancelled_demo_is_not_offered_as_the_date(org_a, monkeypatch):
    """Telling a client to attend a demo we cancelled is worse than asking."""
    captured = await _captured_compose(monkeypatch)
    mid = await _setup(org_a, demo_dates=[
        (date(2026, 9, 9), "10:30", "cancelled"),
        (date(2026, 9, 18), "14:30", "scheduled"),
    ])

    await _run(org_a, mid, "add the demo date too")

    dates = [d["date"] for d in captured["facts"]["scheduled_demos"]]
    assert "2026-09-09" not in dates, "a cancelled demo was offered as the date"
    assert dates == ["2026-09-18"]


async def test_the_original_draft_is_still_the_thing_being_edited(org_a, monkeypatch):
    """Context is added, not swapped — the note is an EDIT instruction and the
    model still needs the text it is editing."""
    captured = await _captured_compose(monkeypatch)
    mid = await _setup(org_a, demo_dates=[(date(2026, 9, 18), "14:30", "scheduled")])

    await _run(org_a, mid, "add the demo date too")

    assert "Looking forward to the walkthrough" in captured["facts"]["original_draft"]
    assert captured["instruction"] == "add the demo date too"
