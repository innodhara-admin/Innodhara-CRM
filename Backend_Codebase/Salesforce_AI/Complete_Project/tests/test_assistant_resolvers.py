"""Finding F28 — the assistant must resolve a person from a natural phrase,
and when it genuinely cannot, ASK rather than fail.

Two layers, deliberately:

* the resolver ladder is exercised directly against the real database, because
  that is where the defect lived (`resolvers.py:142` matched one-directionally);
* the agent loop is exercised through the API, because the *shape* the app
  consumes — `outcome: "needs_confirmation"` with candidates, never a bare
  failure — is a contract, not an implementation detail.

Every test here asserts **both directions**: the long phrase must resolve AND a
genuinely ambiguous hint must still ask. A fix that resolved everything would
pass one half and violate the user's rule ("ask, never guess") on the other.
"""
from __future__ import annotations

import pytest

from app.ai.agents.base import AgentRuntime
from app.ai.agents.resolvers import resolve_contact, resolve_lead, resolve_user
from app.ai.llm import LlmResponse, ToolCall
from app.core.context import OrgContext
from app.core.exceptions import NeedsConfirmationError
from app.database import SessionLocal
from app.models.lead import Lead
from tests.conftest import auth
from tests.test_assistant import fake_model  # noqa: F401 — pytest fixture

pytestmark = pytest.mark.asyncio


async def _runtime(db, org: dict) -> AgentRuntime:
    return AgentRuntime(
        db=db,
        ctx=OrgContext(
            org_id=org["id"], user_id=org["agent_id"], role="sales_agent",
            email="agent@alpha-example.com", name="Asha Agent",
        ),
    )


async def _lead_with_contacts(client, org: dict, name: str, contacts: list[dict]) -> dict:
    from tests.conftest import fresh_lead

    token = org["admin_token"]
    lead = await fresh_lead(client, token, name)
    for contact in contacts:
        resp = await client.post(
            f"/api/v1/leads/{lead['id']}/contacts", headers=auth(token), json=contact
        )
        assert resp.status_code == 200, resp.text
    return lead


async def _fetch(db, lead_id: str) -> Lead:
    from sqlalchemy import select

    return (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()


# ── The F28 case itself ──────────────────────────────────────────────────

async def test_person_resolves_from_a_natural_phrase(client, org_a):
    """The exact phrase observed failing on the device: the hint is LONGER than
    the stored name, so the pre-F28 test (`hint in name`) could never match it.

    The answer was sitting in the old error message — "Known: EKAGHNI
    MUKHERJEE" — which is what made this a defect rather than a limitation."""
    lead = await _lead_with_contacts(
        client, org_a, "Orchid International School",
        [{"name": "EKAGHNI MUKHERJEE", "title": "CSR Manager",
          "email": "ekaghni@orchid-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])

        # The whole typed phrase, exactly as the model passed it live.
        contact = await resolve_contact(
            runtime, row, "EKAGHNI MUKHERJEE at Orchid International School"
        )
        assert contact.name == "EKAGHNI MUKHERJEE"

        # And the shapes around it: the name alone, in either case, and inside
        # a sentence.
        for hint in (
            "EKAGHNI MUKHERJEE",
            "ekaghni mukherjee",
            "draft a note to EKAGHNI MUKHERJEE about the workshop dates",
        ):
            resolved = await resolve_contact(runtime, row, hint)
            assert resolved.id == contact.id, hint


async def test_a_full_name_in_a_sentence_beats_a_colleague_sharing_a_surname(
    client, org_a
):
    """Precision, not just reachability — and the reason the ladder is ordered.

    "Ravi Kumar" read as a whole name matches one person. Read as loose words
    it also half-matches "Kumar Sethi", and the user gets a needless question
    about two people when they named one of them exactly."""
    lead = await _lead_with_contacts(
        client, org_a, "Sundar Textiles",
        [{"name": "Ravi Kumar", "email": "ravi@sundar-example.com"},
         {"name": "Kumar Sethi", "email": "sethi@sundar-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        assert (
            await resolve_contact(runtime, row, "email Ravi Kumar about the demo")
        ).name == "Ravi Kumar"


async def test_a_job_title_inside_a_sentence_resolves(client, org_a):
    """People name a role rather than a person all the time — "ask the CSR
    manager to confirm". The title is not in the hint and the hint is not in
    the title; only reading the title OUT of the sentence finds them."""
    lead = await _lead_with_contacts(
        client, org_a, "Peninsula Mills",
        [{"name": "Farida Sheikh", "title": "CSR Manager",
          "email": "farida@peninsula-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        assert (
            await resolve_contact(runtime, row, "ask the CSR Manager to confirm the dates")
        ).name == "Farida Sheikh"


async def test_a_first_name_only_resolves(client, org_a):
    """Half a name is what people actually type. Nothing matches it as a
    whole, so only overlapping the words does."""
    lead = await _lead_with_contacts(
        client, org_a, "Talwar Motors",
        [{"name": "Ravi Kumar", "email": "ravi@talwar-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        assert (
            await resolve_contact(runtime, row, "drop Ravi a note about the workshop")
        ).name == "Ravi Kumar"


async def test_an_email_address_inside_a_phrase_resolves(client, org_a):
    """Before F28 the email was compared with `==`, so it had to BE the whole
    hint. This address shares no word with the person's name, so nothing but
    finding the address inside the sentence can resolve it."""
    lead = await _lead_with_contacts(
        client, org_a, "Ashwin Foundation",
        [{"name": "Meera Rao", "title": "Director",
          "email": "m.r.finance@ashwin-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        assert (
            await resolve_contact(
                runtime, row,
                "reply to m.r.finance@ashwin-example.com about the invoice",
            )
        ).name == "Meera Rao"


async def test_client_resolves_from_a_phrase_containing_its_name(client, org_a):
    """`resolve_lead` had the same one-directional shape (:34), so the client
    half of "X at Y" failed for the same reason."""
    lead = await _lead_with_contacts(client, org_a, "Nashik Logistics Park", [])
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        resolved = await resolve_lead(
            runtime, "draft an email to the ops head at Nashik Logistics Park"
        )
        assert resolved.id == lead["id"]
        # An id still resolves — the agent loop passes one from the context chip.
        assert (await resolve_lead(runtime, lead["id"])).id == lead["id"]


async def test_staff_resolve_from_a_phrase_and_from_an_embedded_address(client, org_a):
    """`resolve_user` (:65) too — and its email test was `==`, so an address
    inside a longer phrase never matched either."""
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        assert (
            await resolve_user(runtime, "move the task to Asha Agent please")
        ).id == org_a["agent_id"]
        assert (
            await resolve_user(runtime, "assign it to agent@alpha-example.com today")
        ).id == org_a["agent_id"]


# ── The other direction: unsure must ASK, never guess ────────────────────

async def test_ambiguous_person_asks_and_names_the_candidates(client, org_a):
    """Two people share a surname. The rule is ask, never guess: sending a
    client email to the wrong person is worse than one more tap."""
    lead = await _lead_with_contacts(
        client, org_a, "Kirloskar Industries",
        [{"name": "Priya Nair", "title": "Finance Controller",
          "email": "priya@kirloskar-example.com"},
         {"name": "Anita Nair", "title": "Operations Head",
          "email": "anita@kirloskar-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])

        with pytest.raises(NeedsConfirmationError) as raised:
            await resolve_contact(runtime, row, "Nair")
        # The candidates are carried as DATA, not only prose, so the app can
        # offer them as one-tap answers.
        assert set(raised.value.candidates) == {"Priya Nair", "Anita Nair"}
        assert "Which one?" in raised.value.message

        # Answering the question resolves it — the ask is a step, not a wall.
        assert (await resolve_contact(runtime, row, "Priya Nair")).name == "Priya Nair"


async def test_unknown_person_asks_with_the_names_actually_on_file(client, org_a):
    """"None" must ask too. The candidates the user could have meant are the
    answer, and F28's own evidence was an error that listed them while
    refusing to act on them."""
    lead = await _lead_with_contacts(
        client, org_a, "Aurora Systems",
        [{"name": "Meera Rao", "title": "Director", "email": "meera@aurora-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        with pytest.raises(NeedsConfirmationError) as raised:
            await resolve_contact(runtime, row, "Zoltan Farkas")
        assert raised.value.candidates == ["Meera Rao"]


async def test_no_recipient_named_asks_rather_than_picking_row_zero(client, org_a):
    """The silent-guess path: several contacts, none marked primary. Before
    F28 this returned `contacts[0]` — an arbitrary recipient for a client
    email, chosen by insertion order."""
    lead = await _lead_with_contacts(
        client, org_a, "Borealis Corp",
        [{"name": "Sunil Mehta", "email": "sunil@borealis-example.com"},
         {"name": "Kavita Desai", "email": "kavita@borealis-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        with pytest.raises(NeedsConfirmationError) as raised:
            await resolve_contact(runtime, row, None)
        assert set(raised.value.candidates) == {"Sunil Mehta", "Kavita Desai"}

    # A designated primary is a decision a human made, not a guess — so it is
    # still honoured without a question.
    primary_lead = await _lead_with_contacts(
        client, org_a, "Vidarbha Warehousing",
        [{"name": "Ramesh Patil", "email": "ramesh@vidarbha-example.com"},
         {"name": "Latika Joshi", "email": "latika@vidarbha-example.com",
          "is_primary": True}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, primary_lead["id"])
        assert (await resolve_contact(runtime, row, None)).name == "Latika Joshi"


async def test_a_client_named_like_its_contact_still_resolves_the_person(client, org_a):
    """Why stripping the client's words is a FALLBACK stage and not a
    pre-step: strip first and this contact's name disappears with the
    client's, turning a lookup that works today into a question."""
    lead = await _lead_with_contacts(
        client, org_a, "Nair Industries",
        [{"name": "Mrs. Nair", "title": "Owner", "email": "nair@nair-example.com"},
         {"name": "Devi Krishnan", "email": "devi@nair-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        assert (await resolve_contact(runtime, row, "Nair")).name == "Mrs. Nair"
        assert (
            await resolve_contact(runtime, row, "Mrs. Nair at Nair Industries")
        ).name == "Mrs. Nair"


async def test_the_clients_own_words_do_not_make_a_person_ambiguous(client, org_a):
    """Fix 2's own case. "Ravi at Green Valley School" half-matches a contact
    called "Valley Team" purely on the client's words, so the raw hint is
    ambiguous and the user would be asked a question with an obvious answer.
    Removing the client's words from the hint narrows it to the person they
    actually named — and only ever narrows: the strip may pick one of the
    existing candidates, never introduce a different one."""
    lead = await _lead_with_contacts(
        client, org_a, "Green Valley School",
        [{"name": "Ravi Kumar", "email": "ravi@greenvalley-example.com"},
         {"name": "Valley Team", "email": "team@greenvalley-example.com"},
         {"name": "Valley Desk", "email": "desk@greenvalley-example.com"}],
    )
    async with SessionLocal() as db:
        runtime = await _runtime(db, org_a)
        row = await _fetch(db, lead["id"])
        resolved = await resolve_contact(runtime, row, "Ravi at Green Valley School")
        assert resolved.name == "Ravi Kumar"

        # Still ambiguous when the ambiguity is real rather than an artefact
        # of the client's name: both people genuinely match "Valley".
        with pytest.raises(NeedsConfirmationError):
            await resolve_contact(runtime, row, "Valley")


# ── The contract the app consumes ────────────────────────────────────────

async def test_needs_confirmation_reaches_the_app_as_a_question_not_a_crash(
    client, org_a, fake_model  # noqa: F811 — the imported fixture
):
    """The agent loop must hand the app a question. `ok` stays False (the tool
    genuinely did not act, and an older app must keep rendering exactly what it
    rendered before), and `outcome` is what a newer app draws a question card
    from."""
    token = org_a["admin_token"]
    from tests.conftest import fresh_lead

    for name in ("Sunrise Public Trust", "Sunrise Foundation"):
        await fresh_lead(client, token, name)

    fake_model([
        LlmResponse(tool_calls=[ToolCall(name="get_client_details",
                                         args={"client": "Sunrise"})]),
        LlmResponse(text="I found two clients called Sunrise — which did you mean?"),
    ])
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "what's the latest on Sunrise", "agent": "query"},
    )
    assert resp.status_code == 200, resp.text
    action = resp.json()["actions"][0]
    assert action["ok"] is False                      # honest: nothing was done
    assert action["outcome"] == "needs_confirmation"  # …but it is a question
    assert set(action["candidates"]) == {"Sunrise Public Trust", "Sunrise Foundation"}
    assert action["question"] == action["error"]      # old apps still show the text
