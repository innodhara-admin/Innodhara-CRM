"""Jarvis adds a client by conversation — owner, optional details, then "create it".

The server runs the conversation (app/ai/client_draft.py); a scripted model
stands in only where the flow asks one — to route the first request, to call
the tool, and to read free speech into values. What these tests pin down is
the part no model is trusted with: the exact questions, in order; the owner
never left empty; nothing created before a clear go-ahead; and a skip, a
delegation, a correction, a spelling, an unrelated question, a cancel, a stale
reply, another person or a new chat never turning into a wrong client.
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select, update

from app.ai import client_draft, confirmations
from app.ai import llm as llm_mod
from app.ai import orchestrator
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal
from app.models.assistant import AssistantPendingAction
from app.models.audit import AuditLog
from app.models.base import utcnow
from app.models.user import User
from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

API = "/api/v1"
NAME = "Bal Bhavan Public School"


class FakeModelLayer:
    def __init__(self, script: list[LlmResponse]):
        self.script = list(script)
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return LlmResponse(text="Done.")
        return self.script.pop(0)

    async def generate_json(self, **kwargs):
        return llm_mod.extract_json((await self.generate(**kwargs)).text)


@pytest.fixture
def fake_model(monkeypatch):
    def _install(script: list[LlmResponse]) -> FakeModelLayer:
        fake = FakeModelLayer(script)
        for target in (agent_base, orchestrator, client_draft):
            monkeypatch.setattr(target, "get_model_layer", lambda: fake)
        return fake

    return _install


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _read(**fields) -> LlmResponse:
    """What the reading model returns for a free-form reply."""
    return LlmResponse(text=json.dumps(fields))


async def _add_user(client, team, name: str, role: str) -> dict:
    email = f"{name.split()[0].lower()}{_hex()}@{team['domain']}"
    created = await client.post(f"{API}/admin/users", headers=auth(team["admin_token"]),
                                json={"email": email, "name": name, "role": role})
    assert created.status_code == 200, created.text
    token = (await login(client, email, created.json()["temp_password"]))["access_token"]
    return {"id": created.json()["id"], "token": token, "name": name}


@pytest.fixture
async def team(client, super_token):
    """A fresh organisation per test: Meera Iyer talks to Jarvis; Priya Nair and
    Rahul Reddy are the other sales agents. Owner questions depend on exactly
    who is in the org, so nothing is shared between tests."""
    slug = _hex()
    domain = f"team{slug}-example.com"
    org = await create_org(client, super_token, name=f"Team {slug}",
                           slug=f"team-{slug}", domain=domain)
    org["domain"] = domain
    org["me"] = await _add_user(client, org, "Meera Iyer", "sales_agent")
    org["priya"] = await _add_user(client, org, "Priya Nair", "sales_agent")
    org["rahul"] = await _add_user(client, org, "Rahul Reddy", "sales_agent")
    return org


def _session() -> str:
    return f"draftsess{uuid.uuid4().hex}"


async def _say(client, token, text, session_id):
    resp = await client.post(f"{API}/assistant/command", headers=auth(token),
                             json={"text": text, "session_id": session_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ask_to_create(**args) -> list[LlmResponse]:
    """The router picks the client agent; the agent calls create_client."""
    return [LlmResponse(text='{"agent": "client"}'),
            LlmResponse(tool_calls=[ToolCall(name="create_client", args=args)]),
            LlmResponse(text="Prose the card must replace.")]


async def _leads(client, token, name) -> list[dict]:
    resp = await client.get(f"{API}/leads", headers=auth(token), params={"q": name})
    return [lead for lead in resp.json() if lead["name"] == name]


def _card(body) -> dict:
    return body["actions"][-1]


# ── the conversation, exactly as specified ───────────────────────────────────


async def test_the_whole_conversation_word_for_word(client, team, fake_model):
    me, session = team["me"], _session()

    fake_model(_ask_to_create(name=NAME))
    body = await _say(client, me["token"], f"Create a lead named {NAME}.", session)
    assert body["agent"] == "client"
    assert body["reply"] == "Sure. Who should own it? Priya Nair, Rahul Reddy, or you?"
    assert _card(body)["outcome"] == "needs_confirmation"
    assert _card(body)["candidates"] == ["Priya Nair", "Rahul Reddy", "Me"]
    assert _card(body)["details"]["stage"] == "owner"

    fake = fake_model([])
    body = await _say(client, me["token"], "Skip this.", session)
    assert body["reply"] == ("The owner is the one who makes the cold calls, so it "
                             "needs one. Shall I give it to Priya Nair?")
    assert _card(body)["candidates"] == ["Yes", "Someone else"]

    body = await _say(client, me["token"], "Do whatever you want.", session)
    assert body["reply"] == ("Okay, Priya Nair will own it. Do you want to add a city, "
                             "source, website or notes? They're optional.")
    assert _card(body)["candidates"] == ["No thanks"]
    assert fake.calls == []  # a skip and a delegation cost no model call

    fake = fake_model([_read(answer="values", city="Pune")])
    body = await _say(client, me["token"], "Add city as Pune.", session)
    assert body["reply"] == (f"Got it, Pune. So: {NAME} in Pune, owned by Priya Nair. "
                             "Anything else, or shall I create it?")
    assert _card(body)["candidates"] == ["Create it", "Cancel"]
    details = _card(body)["details"]
    assert (details["stage"], details["name"], details["owner"], details["city"]) == \
        ("confirm", NAME, "Priya Nair", "Pune")
    reading_prompt = fake.calls[0]["messages"][0]["content"]
    assert 'Their reply: "Add city as Pune."' in reading_prompt
    assert "Hindi or Kannada" in reading_prompt
    assert await _leads(client, me["token"], NAME) == []

    fake = fake_model([])
    body = await _say(client, me["token"], "Create it.", session)
    assert fake.calls == []
    assert body["reply"] == (f"Done — {NAME} is added and Priya Nair owns it and has been "
                             "notified. It starts in cold calling.")
    lead_id = body["actions"][0]["result"]["lead_id"]
    detail = (await client.get(f"{API}/leads/{lead_id}", headers=auth(me["token"]))).json()
    assert (detail["name"], detail["city"], detail["state"], detail["owner_id"]) == \
        (NAME, "Pune", "cold_calling", team["priya"]["id"])
    notes = (await client.get(f"{API}/notifications",
                              headers=auth(team["priya"]["token"]))).json()
    assert any(n.get("entity_id") == lead_id and n.get("kind") == "lead_assigned"
               for n in notes)
    async with SessionLocal() as db:
        audit = (await db.execute(select(AuditLog).where(
            AuditLog.entity_id == lead_id, AuditLog.action == "lead.created"))).scalar_one()
        held = (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.session_id == session))).scalars().all()
    assert "assistant" in str(audit.detail)
    assert held == []  # the conversation is over


# ── the owner ────────────────────────────────────────────────────────────────


async def test_the_suggestion_is_the_agent_with_fewest_cold_calls(client, team, fake_model):
    for i in range(2):
        created = await client.post(f"{API}/leads", headers=auth(team["admin_token"]),
                                    json={"name": f"Busy {i} {_hex()}",
                                          "owner_id": team["priya"]["id"]})
        assert created.status_code == 200
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    body = await _say(client, me["token"], "create a lead", session)
    assert body["reply"] == "Sure. Who should own it? Rahul Reddy, Priya Nair, or you?"
    fake_model([])
    body = await _say(client, me["token"], "skip", session)
    assert body["reply"].endswith("Shall I give it to Rahul Reddy?")


async def test_a_second_skip_takes_the_suggestion(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([])
    await _say(client, me["token"], "skip this", session)
    body = await _say(client, me["token"], "skip", session)
    assert body["reply"].startswith("Okay, Priya Nair will own it.")


async def test_declining_the_suggestion_asks_again_without_them(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake = fake_model([])
    await _say(client, me["token"], "skip this", session)
    body = await _say(client, me["token"], "Someone else", session)
    assert body["reply"] == "Who should own it then? Rahul Reddy or you?"
    body = await _say(client, me["token"], "later", session)  # already pushed back once
    assert body["reply"].startswith("Okay, Rahul Reddy will own it.")
    assert fake.calls == []


async def test_a_name_or_me_answers_the_owner_question(client, team, fake_model):
    me = team["me"]
    session = _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake = fake_model([])
    body = await _say(client, me["token"], "Rahul", session)
    assert body["reply"].startswith("Okay, Rahul Reddy will own it. Do you want to add")
    assert fake.calls == []

    session = _session()
    fake_model(_ask_to_create(name=f"Other {_hex()}"))
    await _say(client, me["token"], "create", session)
    fake_model([])
    body = await _say(client, me["token"], "Me", session)
    assert body["reply"].startswith("Okay, you'll own it.")
    body = await _say(client, me["token"], "No thanks", session)
    assert body["reply"].startswith("Okay. So: Other ")
    assert "owned by you." in body["reply"]


async def test_an_unknown_owner_is_asked_about_not_guessed(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([_read(answer="values", owner="Suresh")])
    body = await _say(client, me["token"], "give it to Suresh please", session)
    assert body["reply"] == ("I couldn't find anyone called Suresh who can own a client. "
                             "Who should own it? Priya Nair, Rahul Reddy, or you?")


async def test_someone_who_cannot_work_leads_cannot_own_one(client, team, fake_model):
    await _add_user(client, team, "Opsy Kumar", "operations_agent")
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME, owner="Opsy Kumar"))
    body = await _say(client, me["token"], "create, give it to Opsy", session)
    assert body["reply"] == ("Sure. Opsy Kumar is an operations agent and can't own a "
                             "client. Who should own it? Priya Nair, Rahul Reddy, or you?")


async def test_two_matching_people_are_asked_about(client, team, fake_model):
    await _add_user(client, team, "Priya Shah", "sales_agent")
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME, owner="Priya"))
    body = await _say(client, me["token"], "create it for Priya", session)
    assert body["reply"] == "Sure. Did you mean Priya Nair or Priya Shah?"
    assert _card(body)["candidates"] == ["Priya Nair", "Priya Shah"]
    fake = fake_model([])
    body = await _say(client, me["token"], "Priya Shah", session)
    assert body["reply"].startswith("Okay, Priya Shah will own it.")
    assert fake.calls == []


# ── a name that is only close to someone is asked about (17 Sep 2026) ────────
# Heard live: "Ria Nair" was taken as Priya Nair without a word, because
# "ria nair" sits inside "priya nair". A misheard or unknown name must never
# silently become a different colleague.


async def test_a_near_miss_name_is_confirmed_not_used(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake = fake_model([])
    body = await _say(client, me["token"], "Ria Nair", session)
    assert body["reply"] == "I couldn't find anyone called Ria Nair. Did you mean Priya Nair?"
    assert _card(body)["details"]["stage"] == "owner_suggested"
    assert _card(body)["details"]["owner"] is None
    assert _card(body)["candidates"] == ["Yes", "Someone else"]
    assert fake.calls == []
    body = await _say(client, me["token"], "Yes", session)
    assert body["reply"].startswith("Okay, Priya Nair will own it. Do you want to add")


async def test_declining_a_near_miss_asks_again_without_them(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([])
    await _say(client, me["token"], "Ria Nair", session)
    body = await _say(client, me["token"], "Someone else", session)
    assert body["reply"] == "Who should own it then? Rahul Reddy or you?"
    assert _card(body)["details"]["owner"] is None


async def test_a_near_miss_said_up_front_is_confirmed(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME, owner="Ria Nair"))
    body = await _say(client, me["token"], "create it and give it to Ria Nair", session)
    assert body["reply"] == ("Sure. I couldn't find anyone called Ria Nair. "
                             "Did you mean Priya Nair?")
    assert _card(body)["details"]["owner"] is None


async def test_a_near_miss_read_from_a_sentence_is_confirmed(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([_read(answer="values", owner="Ria Nair")])
    body = await _say(client, me["token"], "I think Ria Nair should own this one", session)
    assert body["reply"] == "I couldn't find anyone called Ria Nair. Did you mean Priya Nair?"
    assert _card(body)["details"]["owner"] is None


async def test_a_misheard_first_name_is_offered_not_refused(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([_read(answer="values", owner="Rahool")])
    body = await _say(client, me["token"], "give it to Rahool", session)
    assert body["reply"] == "I couldn't find anyone called Rahool. Did you mean Rahul Reddy?"
    body = await _say(client, me["token"], "Yes", session)
    assert body["reply"].startswith("Okay, Rahul Reddy will own it.")


async def test_whole_names_and_first_names_still_need_no_question(client, team, fake_model):
    me = team["me"]
    for said, owner in (("priya nair", "Priya Nair"), ("Nair", "Priya Nair"),
                        ("Rahul ji", "Rahul Reddy"), ("to Rahul please", "Rahul Reddy")):
        session = _session()
        fake_model(_ask_to_create(name=f"Other {_hex()}"))
        await _say(client, me["token"], "create", session)
        fake = fake_model([])
        body = await _say(client, me["token"], said, session)
        assert body["reply"].startswith(f"Okay, {owner} will own it."), (said, body["reply"])
        assert fake.calls == [], said


async def test_the_reading_model_is_told_to_keep_the_name_as_said(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake = fake_model([_read(answer="values", owner="Rahul Reddy")])
    await _say(client, me["token"], "hand it over to rahul reddy", session)
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "exactly as the user said it" in prompt


async def test_a_romanised_yes_at_the_owner_step_is_not_a_name(client, team,
                                                               fake_model):
    """Reported 21 Sep 2026: answering "Houdu maadi" ("yes, do it" in Kannada)
    got "I couldn't find anyone called Houdu Maddi who can own a client" —
    the owner step looked the words up as a person before asking whether they
    were a plain yes."""
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake = fake_model([])
    body = await _say(client, me["token"], "Houdu Maddi", session)
    assert "couldn't find anyone called" not in body["reply"], body["reply"]
    assert body["reply"].startswith("Sorry, I didn't catch who should own it.")
    assert "Who should own it?" in body["reply"]
    assert fake.calls == []  # and it costs no model call


async def test_the_same_holds_for_hindi_and_plain_english(client, team, fake_model):
    token = team["me"]["token"]
    for said in ("Haan ji", "Theek hai", "Yes please", "Sari maadi"):
        session = _session()
        fake_model(_ask_to_create(name=f"Other {_hex()}"))
        await _say(client, token, "create", session)
        fake_model([])
        body = await _say(client, token, said, session)
        assert "couldn't find anyone called" not in body["reply"], (said, body["reply"])


async def test_a_real_name_still_answers_the_owner_question(client, team, fake_model):
    """The guard must not swallow names: only a plain yes or no is skipped."""
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake = fake_model([])
    body = await _say(client, me["token"], "Priya Nair", session)
    assert body["reply"].startswith("Okay, Priya Nair will own it.")
    assert fake.calls == []


# ── moving a client that already exists (21 Sep 2026) ────────────────────────
# Reported: "I assigned to Rahul, when I logged into Rahul, asked to add NOTES,
# it added successfully, but it was not able to change state from coldcalling
# to open state." Jarvis had no tool for it at all.


def _ask_to_move(**args) -> list[LlmResponse]:
    return [LlmResponse(text='{"agent": "client"}'),
            LlmResponse(tool_calls=[ToolCall(name="move_client_state", args=args)]),
            LlmResponse(text="Prose about the move.")]


async def _lead_owned_by(client, team, owner: dict, name: str) -> dict:
    created = await client.post(f"{API}/leads", headers=auth(team["admin_token"]),
                                json={"name": name, "owner_id": owner["id"]})
    assert created.status_code == 200, created.text
    return created.json()


async def _state_of(client, token, lead_id: str) -> str:
    resp = await client.get(f"{API}/leads/{lead_id}", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["state"]


async def test_the_owner_can_open_a_client_by_asking(client, team, fake_model):
    me = team["me"]
    lead = await _lead_owned_by(client, team, me, f"Vaidehi School {_hex()}")
    assert lead["state"] == "cold_calling"
    await add_reached_contact(client, me["token"], lead["id"])
    fake_model(_ask_to_move(client=lead["name"], state="open",
                            reason="They are interested"))
    body = await _say(client, me["token"], f"move {lead['name']} to open", _session())
    action = body["actions"][-1]
    assert action["tool"] == "move_client_state", action
    assert action["ok"] is True, action
    assert action["result"]["from"] == "cold calling"
    assert action["result"]["state"] == "open"
    assert await _state_of(client, me["token"], lead["id"]) == "open"


async def test_the_same_rule_as_the_screen_decides_who_may_move_it(client, team,
                                                                   fake_model):
    """Only the owner takes a lead out of cold calling — the rule the
    PATCH /leads/{id}/state endpoint enforces, not a second copy of it."""
    lead = await _lead_owned_by(client, team, team["priya"], f"Not Mine {_hex()}")
    fake_model(_ask_to_move(client=lead["name"], state="open"))
    body = await _say(client, team["me"]["token"], "open that one", _session())
    action = body["actions"][-1]
    assert action["ok"] is False
    assert "Priya Nair" in action["error"] and "cold calling" in action["error"]
    assert await _state_of(client, team["me"]["token"], lead["id"]) == "cold_calling"


async def test_a_move_the_state_machine_forbids_is_explained_not_forced(
    client, team, fake_model
):
    me = team["me"]
    lead = await _lead_owned_by(client, team, me, f"Straight To Closed {_hex()}")
    fake_model(_ask_to_move(client=lead["name"], state="closed"))
    body = await _say(client, me["token"], "close it", _session())
    action = body["actions"][-1]
    assert action["ok"] is False
    assert "Cannot move lead from 'cold_calling' to 'closed'" in action["error"]
    assert await _state_of(client, me["token"], lead["id"]) == "cold_calling"


async def test_a_state_nobody_has_is_asked_about_not_guessed(client, team, fake_model):
    me = team["me"]
    lead = await _lead_owned_by(client, team, me, f"Odd State {_hex()}")
    fake_model(_ask_to_move(client=lead["name"], state="warm-ish"))
    body = await _say(client, me["token"], "make it warm-ish", _session())
    action = body["actions"][-1]
    assert action["ok"] is False
    assert "know a state called" in action["error"]
    assert '"warm-ish"' in action["error"]
    assert "cold calling" in action["error"] and "lost for now" in action["error"]


async def test_the_words_people_use_for_a_state_are_understood(client, team, fake_model):
    """"take it out of cold calling" and "opened" are the same move."""
    me = team["me"]
    for said in ("Open", "opened", "OPEN "):
        lead = await _lead_owned_by(client, team, me, f"Worded {_hex()}")
        await add_reached_contact(client, me["token"], lead["id"])
        fake_model(_ask_to_move(client=lead["name"], state=said))
        body = await _say(client, me["token"], "open it", _session())
        assert body["actions"][-1]["ok"] is True, (said, body["actions"][-1])
        assert await _state_of(client, me["token"], lead["id"]) == "open"


async def test_moving_a_client_nobody_can_find_asks_which_one(client, team, fake_model):
    me = team["me"]
    await _lead_owned_by(client, team, me, f"Findable {_hex()}")
    fake_model(_ask_to_move(client="a school that does not exist", state="open"))
    body = await _say(client, me["token"], "open that", _session())
    action = body["actions"][-1]
    assert action["ok"] is False
    assert "which" in action["error"].lower() or "find" in action["error"].lower()


# ── saying several things at once ────────────────────────────────────────────


async def test_details_given_up_front_skip_their_questions(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME, city="Pune", owner="Rahul", source="the expo"))
    body = await _say(client, me["token"], "...", session)
    assert body["reply"] == ("Sure. Rahul Reddy will own it. Do you want to add a "
                             "website or notes? They're optional.")


async def test_everything_up_front_goes_straight_to_the_read_back(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME, city="Pune", owner="me", source="referral",
                              website="balbhavan.example", notes="Wants a demo in June",
                              contact_name="Anita Desai", contact_title="Principal"))
    body = await _say(client, me["token"], "...", session)
    assert body["reply"] == (
        f"Sure. So: {NAME} in Pune, owned by you, with Anita Desai (Principal) as the "
        "main contact. Source: referral. Website: balbhavan.example. Note: Wants a demo "
        "in June. Anything else, or shall I create it?")
    fake_model([])
    body = await _say(client, me["token"], "go ahead", session)
    assert body["reply"].endswith("Anita Desai is saved as the main contact.")
    lead_id = body["actions"][0]["result"]["lead_id"]
    detail = (await client.get(f"{API}/leads/{lead_id}", headers=auth(me["token"]))).json()
    assert [(c["name"], c["title"], c["is_primary"]) for c in detail["contacts"]] == \
        [("Anita Desai", "Principal", True)]
    assert (detail["source"], detail["website"], detail["notes"]) == \
        ("referral", "balbhavan.example", "Wants a demo in June")


async def test_a_nameless_request_asks_for_the_name_first(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create())
    body = await _say(client, me["token"], "create a lead", session)
    assert body["reply"] == "Sure. What is the client called?"
    fake_model([_read(answer="values", name=NAME)])
    body = await _say(client, me["token"], NAME, session)
    assert body["reply"] == "Sure. Who should own it? Priya Nair, Rahul Reddy, or you?"


# ── spelling ─────────────────────────────────────────────────────────────────


async def _to_optional(client, team, fake_model, session):
    fake_model(_ask_to_create(name=NAME, owner="Priya"))
    await _say(client, team["me"]["token"], "create", session)


async def test_spelling_the_name_and_correcting_it(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_optional(client, team, fake_model, session)

    fake_model([_read(answer="spell", spell_field="name")])
    body = await _say(client, me["token"], "can you spell the organisation name", session)
    assert body["reply"] == (
        f"{NAME} is spelled B-A-L, B-H-A-V-A-N, P-U-B-L-I-C, S-C-H-O-O-L. "
        "Do you want to add a city, source, website or notes? They're optional.")

    fake = fake_model([_read(answer="values", name="Bal Bhawan Public School")])
    body = await _say(client, me["token"], "no, Bhawan is with a W not a V", session)
    assert NAME in fake.calls[0]["messages"][0]["content"]  # corrected from the current value
    assert body["reply"] == (
        "Got it — it's now spelled B-A-L, B-H-A-W-A-N, P-U-B-L-I-C, S-C-H-O-O-L. "
        "Do you want to add a city, source, website or notes? They're optional.")

    fake_model([])
    body = await _say(client, me["token"], "no thanks", session)
    assert body["reply"] == ("Okay. So: Bal Bhawan Public School, owned by Priya Nair. "
                             "Anything else, or shall I create it?")
    body = await _say(client, me["token"], "create it", session)
    assert body["reply"].startswith("Done — Bal Bhawan Public School is added")
    assert await _leads(client, me["token"], NAME) == []


async def test_spelling_something_not_given_yet(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_optional(client, team, fake_model, session)
    fake_model([_read(answer="spell", spell_field="city")])
    body = await _say(client, me["token"], "spell the city", session)
    assert body["reply"].startswith("There's no city to spell yet. Do you want to add")


async def test_a_word_is_corrected_letter_by_letter(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name="Sri Chaitanya Academy", owner="me"))
    await _say(client, me["token"], "create", session)
    fake_model([_read(answer="spell", spell_field="name")])
    body = await _say(client, me["token"], "spell the name", session)
    assert body["reply"].startswith(
        "Sri Chaitanya Academy is spelled S-R-I, C-H-A-I-T-A-N-Y-A, A-C-A-D-E-M-Y.")

    fake = fake_model([])
    body = await _say(client, me["token"], "The first word is S H R E E", session)
    assert fake.calls == []  # letters are assembled by the server, never guessed
    assert body["reply"] == (
        "Got it — it's now spelled S-H-R-E-E, C-H-A-I-T-A-N-Y-A, A-C-A-D-E-M-Y. "
        "Do you want to add a city, source, website or notes? They're optional.")


async def test_letters_without_a_word_number_go_to_the_word_they_resemble(
        client, team, fake_model):
    me, session = team["me"], _session()
    await _to_optional(client, team, fake_model, session)
    fake = fake_model([])
    body = await _say(client, me["token"], "the name should be B H A W A N", session)
    assert fake.calls == []
    assert body["reply"].startswith(
        "Got it — it's now spelled B-A-L, B-H-A-W-A-N, P-U-B-L-I-C, S-C-H-O-O-L.")


async def test_letters_that_fit_no_word_ask_which_word(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_optional(client, team, fake_model, session)
    fake_model([_read(answer="spell", spell_field="name")])
    await _say(client, me["token"], "spell the name", session)
    fake = fake_model([])
    body = await _say(client, me["token"], "X Y Z", session)
    assert body["reply"] == ("Which word should be X-Y-Z — the first, second, third, "
                             "or fourth?")
    body = await _say(client, me["token"], "the fourth one", session)
    assert body["reply"].startswith(
        "Got it — it's now spelled B-A-L, B-H-A-V-A-N, P-U-B-L-I-C, X-Y-Z.")
    assert fake.calls == []


@pytest.mark.parametrize("model_label", ["unclear", "no", "values", "other_request"])
async def test_a_word_it_cannot_read_is_asked_for_letter_by_letter(client, team, fake_model,
                                                                   model_label):
    me, session = team["me"], _session()
    await _to_optional(client, team, fake_model, session)
    fake_model([_read(answer="spell", spell_field="name")])
    await _say(client, me["token"], "spell the name", session)
    fake_model([_read(answer=model_label)])
    body = await _say(client, me["token"], "the second word is wrong, bowen with a W",
                      session)
    assert body["reply"] == "Sure — spell the second word for me, letter by letter."
    fake = fake_model([])
    body = await _say(client, me["token"], "B, H, A, W, A, N", session)
    assert fake.calls == []
    assert body["reply"].startswith(
        "Got it — it's now spelled B-A-L, B-H-A-W-A-N, P-U-B-L-I-C, S-C-H-O-O-L.")


async def test_a_numbered_question_about_something_else_is_not_a_spelling(
        client, team, fake_model):
    me, session = team["me"], _session()
    await _to_optional(client, team, fake_model, session)
    fake_model([_read(answer="other_request"), LlmResponse(text='{"agent": "query"}'),
                LlmResponse(text="Your second task is to call Acme.")])
    body = await _say(client, me["token"], "what's my second task for today?", session)
    assert body["agent"] == "query"
    assert body["reply"] == (f"Your second task is to call Acme. …and shall I continue "
                             f"with {NAME}?")


async def test_code_only_context_never_reaches_a_prompt(client, team, fake_model):
    from app.core.context import OrgContext

    me = team["me"]
    fake = fake_model([LlmResponse(text="Nothing to report.")])
    ctx = OrgContext(org_id=team["id"], user_id=me["id"], role="sales_agent",
                     email="meera@example.com", name="Meera Iyer")
    async with SessionLocal() as db:
        await orchestrator.handle_command(
            db, ctx, "anything new?", force_agent="query",
            context={"_voice_confidence": 0.42, "proposal_id": "p123"})
    system = fake.calls[0]["system"]
    assert "p123" in system
    assert "_voice_confidence" not in system and "0.42" not in system


# ── something else in the middle ─────────────────────────────────────────────


async def test_an_unrelated_question_is_answered_and_the_lead_waits(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)

    fake_model([_read(answer="other_request"),
                LlmResponse(text='{"agent": "query"}'),
                LlmResponse(text="You have no open tasks.")])
    body = await _say(client, me["token"], "what are my tasks today", session)
    assert body["agent"] == "query"
    assert body["reply"] == f"You have no open tasks. …and shall I continue with {NAME}?"

    fake = fake_model([])
    body = await _say(client, me["token"], "yes", session)
    assert fake.calls == []
    assert body["reply"] == (f"Okay, back to {NAME}. Who should own it? Priya Nair, "
                             "Rahul Reddy, or you?")


async def test_declining_to_continue_drops_the_lead(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([_read(answer="other_request"), LlmResponse(text='{"agent": "query"}'),
                LlmResponse(text="Nothing due.")])
    await _say(client, me["token"], "anything due?", session)
    fake_model([])
    body = await _say(client, me["token"], "no", session)
    assert body["reply"] == f"Okay, I've dropped {NAME}. Nothing was created."


async def test_a_different_client_replaces_the_unfinished_one(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([_read(answer="other_request")] + _ask_to_create(name="Orbit Labs"))
    body = await _say(client, me["token"], "actually create a lead named Orbit Labs", session)
    assert body["reply"] == (f"Sure — that replaces the unfinished {NAME}. Who should own "
                             "it? Priya Nair, Rahul Reddy, or you?")


# ── nothing is created without a clear go-ahead ──────────────────────────────


async def _to_confirm(client, team, fake_model, session):
    fake_model(_ask_to_create(name=NAME, owner="Priya", city="Pune", source="expo",
                              website="x.example", notes="n"))
    body = await _say(client, team["me"]["token"], "create", session)
    assert body["reply"].endswith("Anything else, or shall I create it?")


async def test_cancel_drops_it(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    fake_model([])
    body = await _say(client, me["token"], "Cancel", session)
    assert body["reply"] == f"Okay, I've dropped {NAME}. Nothing was created."
    assert await _leads(client, me["token"], NAME) == []


async def test_a_bare_no_at_the_end_is_checked_then_drops(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    fake_model([])
    body = await _say(client, me["token"], "no", session)
    assert body["reply"] == f"Just to be sure — shall I create {NAME} now?"
    body = await _say(client, me["token"], "no", session)
    assert body["reply"] == f"Okay, I've dropped {NAME}. Nothing was created."
    assert await _leads(client, me["token"], NAME) == []


async def test_yes_after_the_check_creates(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    fake_model([])
    await _say(client, me["token"], "no", session)
    body = await _say(client, me["token"], "yes", session)
    assert body["reply"].startswith(f"Done — {NAME} is added")


async def test_new_details_with_a_yes_are_read_back_not_created(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    fake_model([_read(answer="yes", source="a referral")])
    body = await _say(client, me["token"], "yes, and the source is a referral", session)
    assert body["reply"].startswith("Got it, a referral. So: ")
    assert "Source: a referral." in body["reply"]
    assert await _leads(client, me["token"], NAME) == []


async def test_an_unclear_reply_at_the_end_asks_plainly(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    fake_model([_read(answer="delegate")])
    body = await _say(client, me["token"], "hmm whatever works for you boss", session)
    assert body["reply"] == f"Sorry, I didn't catch that. Shall I create {NAME} now?"
    assert await _leads(client, me["token"], NAME) == []


async def test_a_stale_draft_creates_nothing(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    async with SessionLocal() as db:
        await db.execute(update(AssistantPendingAction)
                         .where(AssistantPendingAction.session_id == session)
                         .values(expires_at=utcnow().replace(year=2000)))
        await db.commit()
    fake = fake_model([])
    body = await _say(client, me["token"], "yes", session)
    assert fake.calls == []
    assert "didn't act on it" in body["reply"]
    assert await _leads(client, me["token"], NAME) == []


async def test_someone_else_cannot_finish_your_lead(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text="Okay.")])
    await _say(client, team["rahul"]["token"], "Create it.", session)
    assert await _leads(client, me["token"], NAME) == []


async def test_new_chat_forgets_the_lead(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    cleared = await client.request("DELETE", f"{API}/assistant/history?session_id={session}",
                                   headers=auth(me["token"]))
    assert cleared.status_code == 200
    fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text="Okay.")])
    await _say(client, me["token"], "yes", session)
    assert await _leads(client, me["token"], NAME) == []


async def test_an_owner_who_left_before_create_is_replaced_not_used(client, team, fake_model):
    me, session = team["me"], _session()
    await _to_confirm(client, team, fake_model, session)
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == team["priya"]["id"])
                         .values(is_active=False))
        await db.commit()
    fake_model([])
    body = await _say(client, me["token"], "create it", session)
    assert body["reply"] == ("Priya Nair can no longer own clients, so I haven't created "
                             "it. Who should own it? Rahul Reddy or you?")
    assert await _leads(client, me["token"], NAME) == []


async def test_a_similar_client_on_file_is_mentioned(client, team, fake_model):
    """A name that merely resembles one on file does not stop anything; it is
    named in the read-back so the person can see it."""
    me, session = team["me"], _session()
    created = await client.post(f"{API}/leads", headers=auth(me["token"]), json={"name": NAME})
    assert created.status_code == 200
    similar = "Bal Bhavan School"
    fake_model(_ask_to_create(name=similar, owner="me", city="Pune", source="s",
                              website="w", notes="n"))
    body = await _say(client, me["token"], "create", session)
    assert (f"Already on file with a similar name: {NAME} (cold calling, owned by Meera "
            "Iyer).") in body["reply"]
    assert body["reply"].endswith("Anything else, or shall I create it?")


async def test_a_request_wrapped_round_a_name_is_not_part_of_the_name():
    """Measured twice on the live model (21 Sep 2026): asked in Kannada or
    Hindi, it handed the whole sentence over as the client's NAME. Kannada and
    Hindi put the verb last, so the request trails the name."""
    from app.ai.client_draft import _client_name_only

    assert _client_name_only("TPU shaale emba hesarinalli ondu lead rachisi") == "TPU shaale"
    assert _client_name_only("SJBC Tumkur ge hosa lead maadi") == "SJBC Tumkur"
    assert _client_name_only("Green Valley ke liye ek naya lead banao") == "Green Valley"
    # Names that merely end in one of those words are untouched: one trailing
    # word is a name, a run of them is a request.
    for name in ("Global Lead", "Lead India School", "Bal Bhavan Public School",
                 "Orchid International School", "Acme"):
        assert _client_name_only(name) == name


async def test_the_name_is_cleaned_before_it_reaches_the_draft(client, team, fake_model):
    me, session = team["me"], _session()
    fake_model(_ask_to_create(name="TPU shaale emba hesarinalli ondu lead rachisi"))
    body = await _say(client, me["token"], "TPU shaale emba hesarinalli ondu lead rachisi",
                      session)
    assert _card(body)["details"]["name"] == "TPU shaale"
    assert body["reply"] == "Sure. Who should own it? Priya Nair, Rahul Reddy, or you?"


async def test_the_agent_is_told_a_name_is_not_the_whole_sentence(client, team,
                                                                  fake_model):
    """Live on 21 Sep 2026, "SJBC Tumkur ge hosa lead maadi" (Kannada for
    "create a new lead for SJBC Tumkur") was passed through as the client's
    NAME, sentence and all — which also hid it from the duplicate check."""
    from app.ai.agents.client_agent import ClientAgent

    prompt = ClientAgent.system_prompt
    assert "organisation's own name and nothing else" in prompt
    assert "whatever language" in prompt
    assert "SJBC Tumkur" in prompt


# ── the same name twice (21 Sep 2026) ────────────────────────────────────────
# Asked for after a customer watched Jarvis start a second "SJBC Tumkur"
# without a word about the one already on file.


async def _on_file(client, team, name: str) -> dict:
    created = await client.post(f"{API}/leads", headers=auth(team["me"]["token"]),
                                json={"name": name})
    assert created.status_code == 200, created.text
    return created.json()


REFUSED = (" is already on file (cold calling, owned by Meera Iyer). Two clients "
           "cannot have the same name. If this is a different client, tell me a name "
           "that tells them apart, for example with the city.")


async def test_the_same_name_is_refused_and_a_telling_apart_name_asked(client, team,
                                                                       fake_model):
    """26 Sep 2026: an identical name is no longer allowed at all (it used to
    be "add another one?"). The rest of the draft is kept and a name that tells
    the two apart is asked for, before the owner question."""
    me, session = team["me"], _session()
    await _on_file(client, team, NAME)
    fake_model(_ask_to_create(name=NAME))
    body = await _say(client, me["token"], f"Create a lead named {NAME}", session)
    assert body["reply"] == f"Sure. {NAME}{REFUSED}"
    assert _card(body)["details"]["stage"] == "name"
    assert "Who should own it?" not in body["reply"]

    fake_model([_read(answer="values", name=f"{NAME} Hebbal")])
    body = await _say(client, me["token"], f"call it {NAME} Hebbal", session)
    assert "Who should own it?" in body["reply"]
    assert len(await _leads(client, me["token"], NAME)) == 1


async def test_a_different_case_is_the_same_name(client, team, fake_model):
    me, session = team["me"], _session()
    await _on_file(client, team, NAME)
    fake_model(_ask_to_create(name=NAME.upper()))
    body = await _say(client, me["token"], f"create {NAME.upper()}", session)
    assert "Two clients cannot have the same name" in body["reply"]


async def test_cancel_at_that_question_creates_nothing(client, team, fake_model):
    me, session = team["me"], _session()
    await _on_file(client, team, NAME)
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    fake_model([])
    body = await _say(client, me["token"], "cancel", session)
    assert "Nothing was created" in body["reply"]
    assert len(await _leads(client, me["token"], NAME)) == 1


async def test_a_different_name_at_that_question_is_checked_again(client, team,
                                                                  fake_model):
    me, session = team["me"], _session()
    await _on_file(client, team, NAME)
    fake_model(_ask_to_create(name=NAME))
    await _say(client, me["token"], "create", session)
    other = f"Bal Bhavan Annexe {_hex()}"
    fake_model([_read(answer="values", name=other)])
    body = await _say(client, me["token"], f"no, call it {other}", session)
    assert "already on file" not in body["reply"], body["reply"]
    assert "Who should own it?" in body["reply"]


async def test_a_near_name_is_asked_about_and_may_still_be_added(client, team, fake_model):
    """Not identical, only close: two real clients can have similar names, so
    Jarvis asks, and "Add it anyway" still works."""
    me, session = team["me"], _session()
    await _on_file(client, team, NAME)
    near = NAME[:-1]  # "... Schoo": close enough to ask, not the same name
    fake_model(_ask_to_create(name=near, owner="me"))
    body = await _say(client, me["token"], "create", session)
    assert "Do you want to add another one with this name?" in body["reply"]
    fake_model([])
    await _say(client, me["token"], "Add it anyway", session)
    await _say(client, me["token"], "No thanks", session)
    body = await _say(client, me["token"], "Create it", session)
    assert body["reply"].startswith(f"Done — {near} is added")


# ── who may start ────────────────────────────────────────────────────────────


async def test_roles_that_do_not_work_leads_cannot_start(client, team, fake_model):
    manager = await _add_user(client, team, "Rima Manager", "relationship_manager")
    fake_model(_ask_to_create(name=NAME))
    body = await _say(client, manager["token"], "create", _session())
    action = _card(body)
    assert action["ok"] is False and "outcome" not in action
    assert "cannot add clients" in action["error"]


async def test_one_off_commands_cannot_hold_a_conversation(client, team, fake_model):
    fake_model(_ask_to_create(name=NAME)[1:])
    resp = await client.post(f"{API}/assistant/command", headers=auth(team["me"]["token"]),
                             json={"text": "create", "agent": "client"})
    action = _card(resp.json())
    assert "only works inside an assistant chat" in action["error"]


async def test_the_endpoint_audit_row_is_unchanged(client, team):
    """The refactor into lead_service must not alter POST /leads."""
    name = f"Endpoint Co {_hex()}"
    created = await client.post(f"{API}/leads", headers=auth(team["me"]["token"]),
                                json={"name": name})
    async with SessionLocal() as db:
        audit = (await db.execute(select(AuditLog).where(
            AuditLog.entity_id == created.json()["id"],
            AuditLog.action == "lead.created"))).scalar_one()
    assert "assistant" not in str(audit.detail)


# ── the router and the reply reader ──────────────────────────────────────────


async def test_the_router_knows_the_client_agent(fake_model):
    from app.core.context import OrgContext

    fake = fake_model([LlmResponse(text='{"agent": "client"}')])
    ctx = OrgContext(org_id="o", user_id="u", role="sales_agent", email="e@x.com")
    assert await orchestrator.route(ctx, "add a new client Nexora") == "client"
    assert "- client: adding a NEW client" in fake.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("text,expected", [
    ("Yes", "yes"), ("yes please", "yes"), ("Yes, create it", "yes"),
    ("ok go ahead", "yes"), ("do it", "yes"), ("haan ji", "yes"),
    ("theek hai", "yes"), ("हाँ", "yes"), ("ಹೌದು", "yes"), ("ಸರಿ", "yes"),
    ("No", "no"), ("no, don't create it", "no"), ("not now", "no"),
    ("nahi", "no"), ("ಬೇಡ", "no"), ("cancel", "no"),
    ("yes but make the owner Ravi", None), ("ok cancel", None), ("hmm", None),
    ("what are my tasks", None), ("", None),
    ("yes yes yes yes yes yes yes", None),
])
async def test_classify_reply(text, expected):
    assert confirmations.classify_reply(text) == expected


def test_spelling_format():
    assert client_draft.spell_out("Bal Bhavan 2") == "B-A-L, B-H-A-V-A-N, 2"


# ── Open straight away: a sales lead only (7 Oct 2026) ───────────────────────

EMAIL = "anita@acme-example.com"
SPELLED = "A-N-I-T-A at A-C-M-E dash E-X-A-M-P-L-E dot C-O-M"


@pytest.fixture
async def boss_team(team, client):
    """`team` plus Sunil Rao, a sales lead, who talks to Jarvis here."""
    team["boss"] = await _add_user(client, team, "Sunil Rao", "sales_lead")
    return team


async def test_spell_email():
    assert client_draft.spell_email(EMAIL) == SPELLED
    assert client_draft.spell_email("a.b_c+1@x.co.in") == \
        "A dot B underscore C plus 1 at X dot C-O dot I-N"


async def _start_open(client, fake_model, boss_team, **extra):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, **extra) + [
        _read(answer="values", contact_name="Anita Sharma"),
        _read(answer="values", contact_title="Director"),
    ])
    session = _session()
    token = boss_team["boss"]["token"]
    body = await _say(client, token, f"Add a client {name}", session)
    return name, session, token, body


async def test_a_sales_lead_is_asked_whether_to_open_it(client, fake_model, boss_team):
    name, session, token, body = await _start_open(client, fake_model, boss_team)
    card = _card(body)
    assert card["details"]["stage"] == "open_choice"
    assert f"open {name} straight away, or start it in cold calling" in body["reply"]
    assert card["candidates"] == ["Open it now", "Cold calling"]


async def test_the_open_path_end_to_end(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    body = await _say(client, token, "Open it now", session)
    assert _card(body)["details"]["stage"] == "open_contact"
    assert f"Who is the contact at {name}?" in body["reply"]
    assert _card(body)["details"]["open_now"] is True

    body = await _say(client, token, "Anita Sharma", session)
    assert "What is Anita Sharma's designation?" in body["reply"]
    body = await _say(client, token, "Director", session)
    assert "What is Anita Sharma's email address?" in body["reply"]
    body = await _say(client, token, EMAIL, session)
    assert "Do you want to add a phone number, city, source, website or notes?" \
        in body["reply"]
    body = await _say(client, token, "No thanks", session)
    assert _card(body)["details"]["stage"] == "confirm"
    assert "It will be opened straight away." in body["reply"]
    assert not await _leads(client, token, name)

    body = await _say(client, token, "Create it", session)
    assert _card(body)["details"]["stage"] == "email_check"
    assert f"{EMAIL} is spelled {SPELLED}. Is that right?" in body["reply"]
    assert not await _leads(client, token, name)

    body = await _say(client, token, "Yes", session)
    assert "is added and opened" in body["reply"]
    [lead] = await _leads(client, token, name)
    assert lead["state"] == "open" and lead["owner_id"] == boss_team["boss"]["id"]
    detail = (await client.get(f"{API}/leads/{lead['id']}", headers=auth(token))).json()
    [contact] = detail["contacts"]
    assert (contact["name"], contact["title"], contact["email"]) == \
        ("Anita Sharma", "Director", EMAIL)


async def test_a_wrong_email_is_asked_again_and_spelled_again(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    for said in ("Open it now", "Anita Sharma", "Director", EMAIL, "No thanks",
                 "Create it"):
        body = await _say(client, token, said, session)
    body = await _say(client, token, "No", session)
    assert "What is the right email address?" in body["reply"]
    body = await _say(client, token, "anita.s@acme-example.com", session)
    assert _card(body)["details"]["stage"] == "email_check"
    assert "anita.s@acme-example.com is spelled A-N-I-T-A dot S at" in body["reply"]
    assert not await _leads(client, token, name)
    body = await _say(client, token, "Yes", session)
    [lead] = await _leads(client, token, name)
    detail = (await client.get(f"{API}/leads/{lead['id']}", headers=auth(token))).json()
    assert detail["contacts"][0]["email"] == "anita.s@acme-example.com"


async def test_a_bad_email_is_not_kept(client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True, contact_name="Anita Sharma",
                              contact_title="Director")
               + [_read(answer="values", contact_email="anita-at-acme")])
    session, token = _session(), boss_team["boss"]["token"]
    body = await _say(client, token, f"Add {name} as an open lead", session)
    assert "What is Anita Sharma's email address?" in body["reply"]
    body = await _say(client, token, "anita-at-acme", session)
    assert "anita-at-acme doesn't look like an email address." in body["reply"]
    assert "What is Anita Sharma's email address?" in body["reply"]
    assert _card(body)["details"]["contact"].get("email") is None


async def test_spoken_email_is_written_as_an_address(client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True, contact_name="Anita Sharma",
                              contact_title="Director")
               + [_read(answer="values", contact_email="anita at acme-example dot com")])
    session, token = _session(), boss_team["boss"]["token"]
    await _say(client, token, f"Add {name} as an open lead", session)
    body = await _say(client, token, "anita at acme example dot com", session)
    assert _card(body)["details"]["contact"]["email"] == EMAIL


async def test_open_now_in_the_first_sentence_skips_the_question(
        client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True))
    body = await _say(client, boss_team["boss"]["token"], f"Add {name}, open it now",
                      _session())
    assert _card(body)["details"]["stage"] == "open_contact"
    assert f"Who is the contact at {name}?" in body["reply"]


async def test_cold_calling_answer_keeps_todays_flow(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    body = await _say(client, token, "Cold calling", session)
    assert _card(body)["details"]["stage"] in ("owner", "owner_suggested")
    assert "Who should own it?" in body["reply"] or "Shall I give it to" in body["reply"]
    assert _card(body)["details"]["open_now"] is False


async def test_choosing_open_takes_over_a_named_owner(client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, owner="Priya Nair"))
    session, token = _session(), boss_team["boss"]["token"]
    body = await _say(client, token, f"Add {name} for Priya Nair", session)
    assert _card(body)["details"]["stage"] == "open_choice"
    body = await _say(client, token, "Open it now", session)
    assert "An open lead is owned by you, so Priya Nair won't own it." in body["reply"]
    assert _card(body)["details"]["owner"] == "you"


async def test_cancel_while_collecting_the_contact(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    await _say(client, token, "Open it now", session)
    body = await _say(client, token, "Cancel", session)
    assert "Nothing was created" in body["reply"]
    assert not await _leads(client, token, name)


async def test_a_sales_agent_is_never_asked(client, fake_model, team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True))
    body = await _say(client, team["me"]["token"], f"Add {name}, open it now", _session())
    assert _card(body)["details"]["stage"] in ("owner", "owner_suggested")
    assert "straight away" not in body["reply"]
    assert not _card(body)["details"].get("open_now")


async def test_old_held_draft_still_loads(client, fake_model, boss_team):
    """A conversation held before this change has no open_now key."""
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    async with SessionLocal() as db:
        row = (await db.execute(select(AssistantPendingAction).where(
            AssistantPendingAction.session_id == session))).scalar_one()
        payload = json.loads(row.payload)
        for key in ("open_now", "owner_forced", "email_confirmed", "recheck_email"):
            payload.pop(key, None)
        row.payload = json.dumps(payload)
        await db.commit()
    body = await _say(client, token, "Open it now", session)
    assert _card(body)["details"]["stage"] == "open_contact"


async def test_a_demoted_sales_lead_gets_a_reason_not_a_lead(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    for said in ("Open it now", "Anita Sharma", "Director", EMAIL, "No thanks",
                 "Create it"):
        await _say(client, token, said, session)
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == boss_team["boss"]["id"])
                         .values(role="sales_agent"))
        await db.commit()
    body = await _say(client, token, "Yes", session)
    assert "Only a sales lead can open a lead straight away" in body["reply"]
    assert not await _leads(client, token, name)


# Found with the real model (7 Oct 2026): asked to write "anita dot sharma at
# gmail dot com", the fast model returned anita.dots.sharma, anita.dout.sharma
# and anita.dots.harma on three runs. The address is read from the person's
# own words in code, and that reading wins.

async def test_email_in_the_words():
    cases = {
        "anita dot sharma at gmail dot com": "anita.sharma@gmail.com",
        "her email is ravi underscore k at acme dot co dot in": "ravi_k@acme.co.in",
        "Anita at the rate gmail dot com": "anita@gmail.com",
        "mail me on raj dash 2 at x-corp dot com please": "raj-2@x-corp.com",
        "it's Anita.Sharma@Gmail.com.": "anita.sharma@gmail.com",
        "she is the director": None,
        "meet at noon": None,
        "anita at gmail": None,
    }
    for said, expected in cases.items():
        assert client_draft.email_in(said) == expected, said


async def test_spoken_email_beats_the_models_reading(client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True, contact_name="Anita Sharma",
                              contact_title="Director")
               + [_read(answer="values", contact_email="anita.dots.sharma@gmail.com",
                        contact_phone="98450 12345")])
    session, token = _session(), boss_team["boss"]["token"]
    await _say(client, token, f"Add {name} as an open lead", session)
    body = await _say(client, token,
                      "her email is anita dot sharma at gmail dot com, phone 98450 12345",
                      session)
    contact = _card(body)["details"]["contact"]
    assert contact["email"] == "anita.sharma@gmail.com"
    assert contact["phone"] == "98450 12345"


async def test_an_email_alone_needs_no_model(client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake = fake_model(_ask_to_create(name=name, open_now=True, contact_name="Anita Sharma",
                                     contact_title="Director"))
    session, token = _session(), boss_team["boss"]["token"]
    await _say(client, token, f"Add {name} as an open lead", session)
    calls = len(fake.calls)
    body = await _say(client, token, "anita dot sharma at gmail dot com", session)
    assert _card(body)["details"]["contact"]["email"] == "anita.sharma@gmail.com"
    assert len(fake.calls) == calls


async def test_an_email_in_the_first_sentence_is_taken_from_the_words(
        client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True, contact_name="Anita Sharma",
                              contact_title="Director",
                              contact_email="anita.dout.sharma@gmail.com"))
    body = await _say(client, boss_team["boss"]["token"],
                      f"Open {name} now, contact Anita Sharma, director, "
                      "anita dot sharma at gmail dot com", _session())
    assert _card(body)["details"]["contact"]["email"] == "anita.sharma@gmail.com"


# ── Final review fixes (7 Oct 2026) ──────────────────────────────────────────

async def test_email_in_reads_only_a_real_address():
    """An address is taken from the words only where the words clearly give
    one: at the start, after a cue ("email", "is", "on") or after a pause. A
    sentence with "at" in it is not an address, and spelled letters are
    joined, not cut to the last one."""
    cases = {
        "A N I T A at gmail dot com": "anita@gmail.com",
        "a-n-i-t-a at gmail dot com": "anita@gmail.com",
        "Anita Sharma, director at acme dot com, email anita at acme dot com":
            "anita@acme.com",
        "Ravi Kumar, he is the purchase manager, ravi at the rate deodartest dot in":
            "ravi@deodartest.in",
        "her website is at acme dot com": None,
        "she works at tata dot com": None,
        "anita 123 at gmail dot com": None,
        "anita sharma at gmail dot com": None,
    }
    for said, expected in cases.items():
        assert client_draft.email_in(said) == expected, said


async def _to_read_back(client, fake_model, boss_team, *extra_reads):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True, contact_name="Anita Sharma",
                              contact_title="Director", contact_email=EMAIL)
               + list(extra_reads))
    session, token = _session(), boss_team["boss"]["token"]
    body = await _say(client, token, f"Add {name} as an open lead", session)
    assert _card(body)["details"]["stage"] == "optional"
    body = await _say(client, token, "No thanks", session)
    assert _card(body)["details"]["stage"] == "confirm"
    return name, session, token


async def test_an_open_lead_cannot_be_given_to_someone_else_later(
        client, fake_model, boss_team):
    name, session, token = await _to_read_back(
        client, fake_model, boss_team, _read(answer="values", owner="Priya Nair"))
    body = await _say(client, token, "give it to Priya Nair", session)
    assert "An open lead is owned by you. Say cold calling if Priya Nair should own it." \
        in body["reply"]
    assert _card(body)["details"]["owner"] == "you"
    assert "owned by Priya Nair" not in body["reply"]


async def test_cold_calling_at_the_read_back_switches_back(client, fake_model, boss_team):
    name, session, token = await _to_read_back(client, fake_model, boss_team)
    body = await _say(client, token, "actually start it in cold calling", session)
    assert "Okay, it starts in cold calling." in body["reply"]
    assert _card(body)["details"]["open_now"] is False
    assert _card(body)["details"]["stage"] in ("owner", "owner_suggested")


async def test_open_at_the_read_back_after_choosing_cold_calling(
        client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, owner="me"))
    session, token = _session(), boss_team["boss"]["token"]
    await _say(client, token, f"Add {name}", session)
    await _say(client, token, "Cold calling", session)
    body = await _say(client, token, "No thanks", session)
    assert _card(body)["details"]["stage"] == "confirm"
    body = await _say(client, token, "open it now", session)
    assert _card(body)["details"]["open_now"] is True
    assert f"Who is the contact at {name}?" in body["reply"]


async def test_a_demoted_sales_lead_carries_on_in_cold_calling(
        client, fake_model, boss_team):
    name, session, token = await _to_read_back(client, fake_model, boss_team)
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.id == boss_team["boss"]["id"])
                         .values(role="sales_agent"))
        await db.commit()
    body = await _say(client, token, "Create it", session)
    assert "Only a sales lead can open a lead straight away" in body["reply"]
    assert _card(body)["details"]["open_now"] is False
    assert _card(body)["details"]["stage"] in ("owner", "owner_suggested")
    assert not await _leads(client, token, name)


# ── The email loop Siva hit on 7 Oct 2026 (17:03-17:04 IST, live) ─────────────
# "ekaghni.mukherjee at the rate gmail.com" was stored as ...@therategmail.com,
# and "No, it is not right. At the rate gmail.com." was answered "Sorry, I
# didn't catch that" with the same question, again and again.

WRONG = "ekaghni.mukherjee@therategmail.com"
RIGHT = "ekaghni.mukherjee@gmail.com"


async def test_written_dots_are_part_of_a_spoken_address():
    assert client_draft.email_in(
        "Her name is Supriya Rani and her contact is 9310524629 and her email is "
        "ekaghni.mukherjee at the rate gmail.com.") == RIGHT
    assert client_draft.email_in("anita.sharma at gmail.com") == "anita.sharma@gmail.com"
    assert client_draft.email_in("she works at tata.com") is None


async def test_at_the_rate_is_written_as_at():
    assert client_draft._email_form("ekaghni.mukherjee at the rate gmail.com") == RIGHT


async def _at_email_check(client, fake_model, boss_team, *reads):
    name = f"Deaf Test School {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True, contact_name="Supriya Rani",
                              contact_title="Principal", contact_email=WRONG)
               + list(reads))
    session, token = _session(), boss_team["boss"]["token"]
    await _say(client, token, f"Add {name} as an open lead", session)
    await _say(client, token, "No thanks", session)
    body = await _say(client, token, "Create it", session)
    assert _card(body)["details"]["stage"] == "email_check"
    return name, session, token


async def test_a_corrected_domain_keeps_the_name_part(client, fake_model, boss_team):
    name, session, token = await _at_email_check(
        client, fake_model, boss_team, _read(answer="values"))
    body = await _say(client, token, "No, it is not right. At the rate gmail.com.", session)
    assert "Sorry" not in body["reply"]
    assert _card(body)["details"]["stage"] == "email_check"
    assert f"{RIGHT} is spelled" in body["reply"]
    body = await _say(client, token, "Yes", session)
    [lead] = await _leads(client, token, name)
    detail = (await client.get(f"{API}/leads/{lead['id']}", headers=auth(token))).json()
    assert detail["contacts"][0]["email"] == RIGHT


async def test_the_second_way_siva_said_it(client, fake_model, boss_team):
    name, session, token = await _at_email_check(
        client, fake_model, boss_team, _read(answer="values", contact_email=WRONG))
    body = await _say(client, token,
                      "No, it is not the rate gmail, it is gmail, gmail.com.", session)
    assert f"{RIGHT} is spelled" in body["reply"]


async def test_a_no_that_is_not_understood_asks_for_the_address(
        client, fake_model, boss_team):
    name, session, token = await _at_email_check(
        client, fake_model, boss_team, _read(answer="values"))
    body = await _say(client, token, "No, that is completely wrong, please fix it", session)
    assert "Sorry" not in body["reply"]
    assert "What is the right email address?" in body["reply"]
    assert _card(body)["details"]["stage"] == "open_contact"


async def test_domain_in_reads_a_whole_domain():
    assert client_draft._domain_in("no it is acme dot co dot in") == "acme.co.in"
    assert client_draft._domain_in("No, it is not right. At the rate gmail.com.") == "gmail.com"
    assert client_draft._domain_in("it ends with dot") is None
    assert client_draft._domain_in("the price is 1.5 lakh") is None


# ── Open or cold calling only from the person's words (7 Oct 2026) ───────────
# Replaying Siva's live chat: "You can start in cold calling. No, no, no,
# sorry. You can open it." came back cold calling, and at the owner question
# the model read "She is Principal." as open_now=true, switched the lead to
# open and lost the designation; every "yes" after that was "Sorry".

async def test_the_last_choice_said_wins(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    fake_model([_read(answer="values", open_now=False)])
    body = await _say(client, token,
                      "You can start in cold calling. No, no, no, sorry. You can open it.",
                      session)
    assert _card(body)["details"]["open_now"] is True
    assert _card(body)["details"]["stage"] == "open_contact"


async def test_a_model_switch_without_the_words_is_ignored(client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    await _say(client, token, "Cold calling", session)
    fake_model([_read(answer="values", contact_name="Supriya Rani"),
                _read(answer="values", open_now=True, contact_title="Principal")])
    await _say(client, token, "Her name is Supriya Rani", session)
    body = await _say(client, token, "She is Principal.", session)
    assert _card(body)["details"]["open_now"] is False
    assert _card(body)["details"]["stage"] in ("owner", "owner_suggested")


async def test_the_agents_open_now_needs_the_words(client, fake_model, boss_team):
    name = f"Acme Labs {_hex()}"
    fake_model(_ask_to_create(name=name, open_now=True))
    body = await _say(client, boss_team["boss"]["token"], f"Add a client {name}", _session())
    assert _card(body)["details"]["stage"] == "open_choice"


async def test_yes_while_a_detail_is_missing_says_what_is_needed(
        client, fake_model, boss_team):
    name, session, token, _ = await _start_open(client, fake_model, boss_team)
    await _say(client, token, "Open it now", session)
    await _say(client, token, "Anita Sharma", session)
    body = await _say(client, token, "yes", session)
    assert "Sorry" not in body["reply"]
    assert "To open it now I need the contact's name, designation and email." in body["reply"]
    assert "What is Anita Sharma's designation?" in body["reply"]
