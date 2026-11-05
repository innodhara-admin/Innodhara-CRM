"""Opening a lead needs a contact from its owner, and Jarvis creates no sales
work for a lead that has not been opened (2026-09-24).

Two rules, asserted against the server:

1. A lead leaves cold calling for OPEN only once its owner has added at least
   one contact with a phone number or an email address. A contact added by
   anybody else -- or one the meeting pipeline found in a transcript -- does
   not count. The same rule holds for the app's PATCH and for Jarvis, because
   both go through `lead_service.change_state_for_user`.

2. While a lead is in cold calling, Jarvis refuses to schedule a meeting, book
   a demo, or create a proposal or an MOU, and says so in plain words. Notes
   and contacts are still allowed: they are what cold calling produces.
"""
from __future__ import annotations

import io
import json
import uuid

import pytest
from sqlalchemy import create_engine, select, text

from app.ai import llm as llm_mod
from app.ai import meeting_draft, orchestrator
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal, _apply_light_migrations
from app.models.assistant import AssistantPendingAction
from app.models.demo import Demo
from app.models.lead import ClientIntelligence, Contact
from app.models.proposal import Proposal
from app.models.scheduled_meeting import ScheduledMeeting
from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

API = "/api/v1"


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _add_user(client, org, name: str, role: str) -> dict:
    email = f"{name.split()[0].lower()}{_hex()}@{org['domain']}"
    created = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                                json={"email": email, "name": name, "role": role})
    assert created.status_code == 200, created.text
    token = (await login(client, email, created.json()["temp_password"]))["access_token"]
    return {"id": created.json()["id"], "token": token, "name": name}


@pytest.fixture
async def org(client, super_token):
    """A fresh org per test: Priya and Ravi are agents, Siva is the sales lead."""
    slug = _hex()
    domain = f"opn{slug}-example.com"
    org = await create_org(client, super_token, name=f"Open {slug}",
                           slug=f"open-{slug}", domain=domain)
    org["domain"] = domain
    org["priya"] = await _add_user(client, org, "Priya Nair", "sales_agent")
    org["ravi"] = await _add_user(client, org, "Ravi Kumar", "sales_agent")
    org["siva"] = await _add_user(client, org, "Siva Rao", "sales_lead")
    return org


async def _lead(client, org, owner_key="priya", name=None) -> dict:
    resp = await client.post(
        f"{API}/leads", headers=auth(org["siva"]["token"]),
        json={"name": name or f"Lead {_hex()}", "owner_id": org[owner_key]["id"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "cold_calling"
    return resp.json()


async def _open(client, token, lead_id, state="open"):
    return await client.patch(f"{API}/leads/{lead_id}/state", headers=auth(token),
                              json={"state": state, "reason": "Spoke to them"})


async def _detail(client, token, lead_id) -> dict:
    resp = await client.get(f"{API}/leads/{lead_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── rule 1: the owner's contact opens the lead ───────────────────────────────


async def test_a_lead_with_no_contact_cannot_be_opened(client, org):
    lead = await _lead(client, org)
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "contact" in detail and "phone" in detail and "email" in detail
    assert (await _detail(client, org["priya"]["token"], lead["id"]))["state"] == \
        "cold_calling", "a refused move must not have moved it"


async def test_a_contact_with_a_phone_number_opens_it(client, org):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"],
                              phone="+91 98765 43210")
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open"


async def test_a_contact_with_only_an_email_opens_it(client, org):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"],
                              phone=None, email="anita@client.example")
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 200, resp.text


async def test_a_contact_with_neither_phone_nor_email_does_not_count(client, org):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"],
                              phone=None, email=None)
    await add_reached_contact(client, org["priya"]["token"], lead["id"],
                              phone="   ", email="  ")
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 422, resp.text


async def test_a_contact_someone_else_added_does_not_count(client, org):
    """Siva typed a number in, but Priya is the one who made the calls."""
    lead = await _lead(client, org)
    await add_reached_contact(client, org["siva"]["token"], lead["id"])
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 422, resp.text

    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 200, resp.text


async def test_a_contact_from_a_meeting_transcript_does_not_count(client, org):
    """The pipeline records people it hears about with no phone and no email,
    and with no person behind them -- neither makes it the owner's contact."""
    lead = await _lead(client, org)
    async with SessionLocal() as db:
        db.add(Contact(org_id=org["id"], lead_id=lead["id"], name="Mr Rao",
                       phone="+91 90000 11111", source="meeting"))
        await db.commit()
    resp = await _open(client, org["priya"]["token"], lead["id"])
    assert resp.status_code == 422, resp.text


async def test_the_owner_is_told_to_add_one_and_others_are_told_who(client, org):
    lead = await _lead(client, org)
    mine = (await _open(client, org["priya"]["token"], lead["id"])).json()["detail"]
    assert "Add at least one contact" in mine, mine

    # The org admin's break-glass path is refused too, and is told whose
    # contact is missing.
    theirs = (await _open(client, org["admin_token"], lead["id"])).json()["detail"]
    assert "Priya Nair" in theirs, theirs


async def test_the_org_admin_still_opens_once_the_owner_has_a_contact(client, org):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    resp = await _open(client, org["admin_token"], lead["id"])
    assert resp.status_code == 200, resp.text


async def test_who_may_open_is_asked_before_whether_it_can_be(client, org):
    """Ravi does not own it: he is refused for that, not told to add a contact."""
    lead = await _lead(client, org)
    resp = await _open(client, org["ravi"]["token"], lead["id"])
    assert resp.status_code == 403, resp.text
    assert "Priya Nair" in resp.json()["detail"]


async def test_a_reassigned_lead_needs_the_new_owners_contact(client, org):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    moved = await client.patch(f"{API}/leads/{lead['id']}", headers=auth(org["siva"]["token"]),
                               json={"owner_id": org["ravi"]["id"]})
    assert moved.status_code == 200, moved.text

    assert (await _open(client, org["ravi"]["token"], lead["id"])).status_code == 422
    await add_reached_contact(client, org["ravi"]["token"], lead["id"])
    assert (await _open(client, org["ravi"]["token"], lead["id"])).status_code == 200


async def test_dropping_a_dead_cold_call_needs_no_contact(client, org):
    """Only the move to OPEN is gated. Lost-for-now is unchanged."""
    lead = await _lead(client, org)
    resp = await _open(client, org["priya"]["token"], lead["id"], state="lost_for_now")
    assert resp.status_code == 200, resp.text


async def test_moves_after_open_are_untouched(client, org):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    assert (await _open(client, org["priya"]["token"], lead["id"])).status_code == 200
    for target in ("active", "cold", "open", "active", "execution_in_progress",
                   "client_execution_in_progress", "closed", "open"):
        resp = await _open(client, org["priya"]["token"], lead["id"], state=target)
        assert resp.status_code == 200, f"{target}: {resp.text}"


async def test_a_scanned_card_counts_as_the_owners_contact(client, org, monkeypatch):
    from app.ai import vision

    async def _scan(image, mime, *, org_id=None, user_id=None):
        return vision.CardScanResult(name="Anita Rao", title="Director",
                                     email="anita@client.example", phone=None,
                                     organisation="Client", confidence=0.9)

    monkeypatch.setattr(vision, "read_business_card", _scan)
    lead = await _lead(client, org)
    resp = await client.post(
        f"{API}/leads/{lead['id']}/contacts/from-card",
        headers=auth(org["priya"]["token"]),
        data={"draft_intro": "false"},
        files={"file": ("card.jpg", io.BytesIO(b"\xff\xd8\xff fake"), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert (await _open(client, org["priya"]["token"], lead["id"])).status_code == 200


async def test_the_lead_detail_says_whether_it_can_be_opened(client, org):
    lead = await _lead(client, org)
    before = await _detail(client, org["priya"]["token"], lead["id"])
    assert before["can_open"] is False
    assert "Add at least one contact" in before["open_blocker"]
    assert before["contacts"] == []

    await add_reached_contact(client, org["siva"]["token"], lead["id"])
    middle = await _detail(client, org["priya"]["token"], lead["id"])
    assert middle["can_open"] is False
    assert middle["contacts"][0]["added_by_owner"] is False
    assert middle["contacts"][0]["created_by"] == org["siva"]["id"]

    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    after = await _detail(client, org["priya"]["token"], lead["id"])
    assert after["can_open"] is True and after["open_blocker"] is None
    assert sorted(c["added_by_owner"] for c in after["contacts"]) == [False, True]

    await _open(client, org["priya"]["token"], lead["id"])
    opened = await _detail(client, org["priya"]["token"], lead["id"])
    assert opened["can_open"] is False, "only a cold-calling lead can be opened"
    assert opened["open_blocker"] is None


# ── the migration ────────────────────────────────────────────────────────────


def test_the_migration_adds_the_column_and_credits_existing_contacts(tmp_path):
    """Contacts older than the column are credited from the audit log: a card
    scan names the contact, a typed contact is matched to its lead by time.
    Anything unmatched stays NULL, which never counts as the owner's."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE contacts (id VARCHAR(32) PRIMARY KEY, org_id VARCHAR(32), "
            "lead_id VARCHAR(32), name VARCHAR(200), email VARCHAR(320), "
            "phone VARCHAR(30), source VARCHAR(20), created_at DATETIME)"))
        conn.execute(text(
            "CREATE TABLE audit_log (id VARCHAR(32) PRIMARY KEY, org_id VARCHAR(32), "
            "user_id VARCHAR(32), action VARCHAR(100), entity_type VARCHAR(50), "
            "entity_id VARCHAR(32), detail JSON, at DATETIME)"))
        conn.execute(text(
            "INSERT INTO contacts VALUES "
            "('typed', 'o', 'L1', 'A', NULL, '1', 'manual', '2026-09-23 09:57:36.147147'),"
            "('late', 'o', 'L1', 'B', NULL, '1', 'manual', '2026-09-23 12:00:00.000000'),"
            "('card', 'o', 'L2', 'C', 'c@x', NULL, 'card', '2026-09-20 10:00:00.000000'),"
            "('heard', 'o', 'L1', 'D', NULL, NULL, 'meeting', '2026-09-23 09:57:36.000000')"))
        conn.execute(text(
            "INSERT INTO audit_log VALUES "
            "('a1', 'o', 'u-typed', 'contact.added', 'lead', 'L1', NULL, "
            "'2026-09-23 09:57:36.149718'),"
            "('a2', 'o', 'u-card', 'contact.card_scanned', 'contact', 'card', NULL, "
            "'2026-09-20 10:00:01.000000'),"
            "('a3', 'o', 'u-other', 'contact.added', 'lead', 'L9', NULL, "
            "'2026-09-23 12:00:00.000000')"))
    with engine.begin() as conn:
        _apply_light_migrations(conn)
        _apply_light_migrations(conn)  # idempotent: a second start changes nothing
        rows = dict(conn.execute(text("SELECT id, created_by FROM contacts")).all())
    engine.dispose()
    assert rows == {"typed": "u-typed", "late": None, "card": "u-card", "heard": None}


# ── rule 2: Jarvis creates no sales work before open ─────────────────────────


class FakeModelLayer:
    def __init__(self, script: list[LlmResponse]):
        self.script = list(script)

    async def generate(self, **kwargs):
        if not self.script:
            return LlmResponse(text="Done.")
        return self.script.pop(0)

    async def generate_json(self, **kwargs):
        return llm_mod.extract_json((await self.generate(**kwargs)).text)


@pytest.fixture
def fake_model(monkeypatch):
    def _install(script: list[LlmResponse]) -> FakeModelLayer:
        fake = FakeModelLayer(script)
        for target in (agent_base, orchestrator, meeting_draft):
            monkeypatch.setattr(target, "get_model_layer", lambda: fake)
        return fake

    return _install


async def _say(client, token, said, session_id=None):
    resp = await client.post(f"{API}/assistant/command", headers=auth(token),
                             json={"text": said, "session_id": session_id or f"s{_hex()}"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _asks(agent: str, tool: str, prose: str, **args) -> list[LlmResponse]:
    """Router picks `agent`; it calls `tool`; then writes `prose`. The prose
    claims success on purpose: the reply must not repeat that claim."""
    return [LlmResponse(text=json.dumps({"agent": agent})),
            LlmResponse(tool_calls=[ToolCall(name=tool, args=args)]),
            LlmResponse(text=prose)]


def _refused(body, lead_name: str, action: str) -> None:
    expected = (f"{lead_name} is not in open state yet, therefore {action} is "
                f"not allowed. Its owner has to move it from cold calling to open first.")
    assert body["reply"] == expected, body["reply"]
    assert body["actions"][-1]["outcome"] == "not_allowed", body["actions"]
    assert body["actions"][-1]["ok"] is False


async def _count(model, lead_id: str) -> int:
    async with SessionLocal() as db:
        return len((await db.execute(
            select(model).where(model.lead_id == lead_id))).scalars().all())


async def test_jarvis_will_not_schedule_a_meeting_before_open(client, org, fake_model):
    lead = await _lead(client, org)
    fake_model(_asks("scheduling", "schedule_meeting", "Done — the meeting is booked.",
                     client=lead["name"], date="2026-10-02", time="11:00"))
    body = await _say(client, org["priya"]["token"],
                      f"schedule a meeting with {lead['name']} on 2 Oct at 11")
    _refused(body, lead["name"], "scheduling a meeting")
    assert await _count(ScheduledMeeting, lead["id"]) == 0


async def test_jarvis_refuses_as_soon_as_the_client_is_named(client, org, fake_model):
    """Named with nothing else: refused now, not after asking for a day and a
    time for a meeting that could never be booked."""
    lead = await _lead(client, org)
    session = f"s{_hex()}"
    fake_model(_asks("scheduling", "schedule_meeting", "Which day?", client=lead["name"]))
    body = await _say(client, org["priya"]["token"], f"meeting with {lead['name']}", session)
    _refused(body, lead["name"], "scheduling a meeting")
    async with SessionLocal() as db:
        held = (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.session_id == session))).scalars().all()
    assert held == [], "nothing should be left waiting for a day and a time"


async def test_a_client_named_later_in_the_conversation_is_refused_too(
    client, org, fake_model
):
    lead = await _lead(client, org)
    session = f"s{_hex()}"
    fake_model(_asks("scheduling", "schedule_meeting", "x", date="2026-10-02",
                     time="11:00"))
    first = await _say(client, org["priya"]["token"], "set up a meeting on 2 Oct at 11",
                       session)
    assert first["actions"][-1]["outcome"] == "needs_confirmation", first
    assert "client" in first["reply"].lower()

    fake_model([LlmResponse(text=json.dumps({"about_this": True,
                                             "client": lead["name"]}))])
    second = await _say(client, org["priya"]["token"], lead["name"], session)
    _refused(second, lead["name"], "scheduling a meeting")
    assert await _count(ScheduledMeeting, lead["id"]) == 0
    async with SessionLocal() as db:
        held = (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.session_id == session))).scalars().all()
    assert held == [], "the refused meeting must not keep holding the chat"


async def test_jarvis_will_not_book_a_demo_before_open(client, org, fake_model):
    lead = await _lead(client, org)
    fake_model(_asks("scheduling", "book_demo", "Demo booked for 5 October!",
                     client=lead["name"], demo_date="2026-10-05"))
    body = await _say(client, org["siva"]["token"], f"book a demo at {lead['name']}")
    _refused(body, lead["name"], "booking a demo")
    assert await _count(Demo, lead["id"]) == 0


async def test_jarvis_will_not_create_a_proposal_before_open(client, org, fake_model):
    lead = await _lead(client, org)
    fake_model(_asks("proposal", "create_proposal", "Your proposal is ready.",
                     client=lead["name"], program="Anything"))
    body = await _say(client, org["siva"]["token"], f"create a proposal for {lead['name']}")
    _refused(body, lead["name"], "creating a proposal")
    assert await _count(Proposal, lead["id"]) == 0


async def test_jarvis_will_not_create_an_mou_before_open(client, org, fake_model):
    from app.models.mou import MouDocument
    from app.models.proposal_fill import ProposalFillSession

    lead = await _lead(client, org)
    fake_model(_asks("proposal", "create_mou", "The MOU is being drafted.",
                     client=lead["name"], program="Anything"))
    body = await _say(client, org["siva"]["token"], f"draw up the MOU for {lead['name']}")
    _refused(body, lead["name"], "creating an MOU")
    assert await _count(MouDocument, lead["id"]) == 0
    assert await _count(ProposalFillSession, lead["id"]) == 0


async def test_once_open_jarvis_books_the_demo(client, org, fake_model):
    lead = await _lead(client, org)
    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    assert (await _open(client, org["priya"]["token"], lead["id"])).status_code == 200
    fake_model(_asks("scheduling", "book_demo", "Booked.", client=lead["name"],
                     demo_date="2026-10-05"))
    body = await _say(client, org["siva"]["token"], f"book a demo at {lead['name']}")
    assert body["actions"][-1]["ok"] is True, body["actions"]
    assert body["reply"] == "Booked."
    assert await _count(Demo, lead["id"]) == 1


async def test_jarvis_still_adds_a_note_while_cold_calling(client, org, fake_model):
    lead = await _lead(client, org)
    fake_model(_asks("conversation", "add_client_note", "Saved the note.",
                     client=lead["name"], note="Call back after the exams"))
    body = await _say(client, org["priya"]["token"], "note: call back after exams")
    assert body["actions"][-1]["ok"] is True, body["actions"]
    assert body["reply"] == "Saved the note."
    assert await _count(ClientIntelligence, lead["id"]) == 1


async def test_jarvis_adds_the_contact_that_lets_the_owner_open(client, org, fake_model):
    lead = await _lead(client, org)
    fake_model(_asks("conversation", "add_client_contact", "Added Anita.",
                     client=lead["name"], name="Anita Rao", title="Director",
                     phone="+91 98765 43210"))
    body = await _say(client, org["priya"]["token"],
                      f"add Anita Rao, director, 9876543210 as a contact for {lead['name']}")
    action = body["actions"][-1]
    assert action["ok"] is True, action
    assert action["result"]["contact"]["phone"] == "+91 98765 43210"
    assert "still_cannot_open" not in action["result"]
    async with SessionLocal() as db:
        contact = (await db.execute(select(Contact).where(
            Contact.lead_id == lead["id"]))).scalar_one()
    assert contact.created_by == org["priya"]["id"]
    assert contact.source == "manual"

    assert (await _open(client, org["priya"]["token"], lead["id"])).status_code == 200


async def test_a_contact_jarvis_adds_for_someone_else_says_what_is_still_missing(
    client, org, fake_model
):
    lead = await _lead(client, org)
    fake_model(_asks("conversation", "add_client_contact", "Added.",
                     client=lead["name"], name="Anita Rao", email="anita@client.example"))
    body = await _say(client, org["siva"]["token"], "add Anita as a contact")
    result = body["actions"][-1]["result"]
    assert "Priya Nair" in result["still_cannot_open"], result


async def test_jarvis_refuses_a_contact_with_a_broken_email(client, org, fake_model):
    lead = await _lead(client, org)
    fake_model(_asks("conversation", "add_client_contact", "Could not add it.",
                     client=lead["name"], name="Anita Rao", email="not-an-address"))
    body = await _say(client, org["priya"]["token"], "add Anita")
    assert body["actions"][-1]["ok"] is False
    assert await _count(Contact, lead["id"]) == 0


async def test_opening_by_asking_jarvis_follows_the_same_contact_rule(
    client, org, fake_model
):
    lead = await _lead(client, org)
    fake_model(_asks("client", "move_client_state", "x", client=lead["name"],
                     state="open"))
    body = await _say(client, org["priya"]["token"], f"move {lead['name']} to open")
    action = body["actions"][-1]
    assert action["ok"] is False and "contact" in action["error"], action

    await add_reached_contact(client, org["priya"]["token"], lead["id"])
    fake_model(_asks("client", "move_client_state", "Opened.", client=lead["name"],
                     state="open"))
    body = await _say(client, org["priya"]["token"], f"move {lead['name']} to open")
    assert body["actions"][-1]["ok"] is True, body["actions"]
    assert (await _detail(client, org["priya"]["token"], lead["id"]))["state"] == "open"


async def test_a_turn_refused_twice_says_so_once(client, org, fake_model):
    """A model that retries the refused tool must not make the reply repeat."""
    lead = await _lead(client, org)
    call = ToolCall(name="book_demo", args={"client": lead["name"],
                                            "demo_date": "2026-10-05"})
    fake_model([LlmResponse(text='{"agent": "scheduling"}'),
                LlmResponse(tool_calls=[call]), LlmResponse(tool_calls=[call]),
                LlmResponse(text="Booked!")])
    body = await _say(client, org["siva"]["token"], "book a demo")
    _refused(body, lead["name"], "booking a demo")
