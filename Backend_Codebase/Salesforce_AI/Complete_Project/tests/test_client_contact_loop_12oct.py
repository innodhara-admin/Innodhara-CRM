"""The open-contact loop a live Jarvis conversation hit on 12 Oct 2026.

A sales lead gave the contact in one sentence. The reading model also copied
back the owner it had been shown, "you"; looked up as a person, "you" found
nobody; the reply re-asked "Who is the contact?"; and repeating the contact
then changed nothing, so every further try was "Sorry, I didn't catch that".
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.assistant import AssistantPendingAction
from tests.test_client_creation import (  # noqa: F401 -- fixtures by name
    _card,
    _read,
    _say,
    _start_open,
    boss_team,
    fake_model,
    team,
)

pytestmark = pytest.mark.asyncio

CONTACT = dict(contact_name="Ekaghni Mukherjee", contact_title="Principal",
               contact_email="ekaghni.mukherjee@example-mail.com")


async def test_an_owner_copied_back_as_you_is_not_looked_up(
        client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    body = await _say(client, token, "Open it now", session)
    assert _card(body)["details"]["stage"] == "open_contact"

    fake_model([_read(answer="values", owner="you", **CONTACT)])
    body = await _say(client, token, "contact is ekaghni mukherjee, the principal, "
                      "ekaghni.mukherjee@example-mail.com", session)

    assert "couldn't find anyone" not in body["reply"]
    assert "Who is the contact" not in body["reply"]
    details = _card(body)["details"]
    assert details["owner"] == "you"
    assert details["contact"]["email"] == "ekaghni.mukherjee@example-mail.com"
    assert details["stage"] != "open_contact"


async def test_repeating_a_contact_already_held_moves_on(
        client, fake_model, boss_team):
    """The second half of the loop, on its own: the step holds a complete
    contact, the person says it again, nothing changes -- move on."""
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    await _say(client, token, "Open it now", session)
    async with SessionLocal() as db:
        row = (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.session_id == session))).scalar_one()
        payload = json.loads(row.payload)
        payload["contact"] = {"name": "Ekaghni Mukherjee", "title": "Principal",
                              "phone": None,
                              "email": "ekaghni.mukherjee@example-mail.com"}
        payload["stage"] = "open_contact"
        row.payload = json.dumps(payload)
        await db.commit()

    fake_model([_read(answer="values", **CONTACT)])
    body = await _say(client, token, "i just told u. ekaghni mukherjee, principal, "
                      "ekaghni.mukherjee@example-mail.com", session)
    assert "didn't catch" not in body["reply"]
    assert _card(body)["details"]["stage"] != "open_contact"


async def test_an_incomplete_contact_is_still_asked_for(
        client, fake_model, boss_team):
    """Moving on is only for a contact that is already complete."""
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    await _say(client, token, "Open it now", session)
    fake_model([_read(answer="values", contact_name="Anita Sharma")])
    body = await _say(client, token, "Anita Sharma", session)
    assert "What is Anita Sharma's designation?" in body["reply"]
    fake_model([_read(answer="unclear")])
    body = await _say(client, token, "hmm", session)
    assert "didn't catch" in body["reply"]
    assert "designation" in body["reply"]
    assert _card(body)["details"]["stage"] == "open_contact"


async def test_a_real_other_owner_is_still_refused_for_an_open_lead(
        client, fake_model, boss_team):
    """Only the copied-back value is ignored; a named colleague is still read."""
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    await _say(client, token, "Open it now", session)
    fake_model([_read(answer="values", owner="Priya Nair", **CONTACT)])
    body = await _say(client, token, "give it to Priya Nair", session)
    assert "An open lead is owned by you" in body["reply"]
