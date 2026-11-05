"""The relationship manager's two screens.

Home answers one question — who needs me today — so the ordering is the
feature, not a detail. A client nobody has ever spoken to sorts above every
real gap, because being handed a client and never calling them is the failure
this screen exists to make visible.

The client page assembles what we already know rather than storing anything
new. The test that matters there is that it stays readable when there is
nothing to read: a client with no projects, no notes and no meetings must
produce a page, not an exception and not a blank.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "rmscreens-example.com"


async def _add(client, org, email, name, role, department=None):
    resp = await client.post(
        "/api/v1/admin/users", headers=auth(org["admin_token"]),
        json={"email": email, "name": name, "role": role,
              **({"department": department} if department else {})},
    )
    assert resp.status_code == 200, resp.text
    user = resp.json()
    session = await login(client, email, user["temp_password"])
    return user["id"], session["access_token"]


@pytest.fixture(scope="module")
async def org(client, super_token) -> dict:
    org = await create_org(
        client, super_token,
        name="RM Screens Co", slug="rm-screens-co", domain=DOMAIN,
    )
    for key, email, name, role, dept in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent", "sales"),
        ("siva", f"siva@{DOMAIN}", "Siva Lead", "sales_lead", "sales"),
        ("meena", f"meena@{DOMAIN}", "Meena Manager",
         "relationship_manager", "relationship"),
        ("nikhil", f"nikhil@{DOMAIN}", "Nikhil Manager",
         "relationship_manager", "relationship"),
    ):
        uid, token = await _add(client, org, email, name, role, dept)
        org[f"{key}_id"] = uid
        org[f"{key}_token"] = token
    return org


async def _handed_over(client, org, name, manager_key="meena") -> dict:
    """A client walked to closed and handed to a named manager."""
    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": name, "city": "Kolkata", "owner_id": org["priya_id"]},
    )
    lead = created.json()
    await add_reached_contact(client, org["priya_token"], lead["id"])
    for state in ("open", "active", "execution_in_progress",
                  "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state",
            headers=auth(org["priya_token"]),
            json={"state": state, "reason": "walking to closed"},
        )
        assert resp.status_code == 200, f"{state}: {resp.text}"
    handed = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]),
        json={"manager_id": org[f"{manager_key}_id"]},
    )
    assert handed.status_code == 200, handed.text
    return lead


# ── Home ────────────────────────────────────────────────────────────────────

async def test_home_lists_only_my_own_clients(client, org):
    """Meena's Home is Meena's. Nikhil's clients are not her workload, and
    showing them would make the count on the screen a lie."""
    mine = await _handed_over(client, org, "Meenas Client", "meena")
    theirs = await _handed_over(client, org, "Nikhils Client", "nikhil")

    resp = await client.get("/api/v1/relationships/mine",
                            headers=auth(org["meena_token"]))
    assert resp.status_code == 200, resp.text
    names = {row["lead_name"] for row in resp.json()}
    assert "Meenas Client" in names
    assert "Nikhils Client" not in names

    other = await client.get("/api/v1/relationships/mine",
                             headers=auth(org["nikhil_token"]))
    assert {r["lead_name"] for r in other.json()} == {"Nikhils Client"}
    assert mine["id"] != theirs["id"]


async def test_a_client_never_spoken_to_is_flagged_quiet(client, org):
    """No conversation at all is the worst case, not a missing value. It has
    to read as quiet or the screen quietly excuses the thing it exists to
    catch."""
    await _handed_over(client, org, "Never Called Client", "meena")

    rows = (await client.get("/api/v1/relationships/mine",
                             headers=auth(org["meena_token"]))).json()
    row = next(r for r in rows if r["lead_name"] == "Never Called Client")
    assert row["days_quiet"] is None
    assert row["is_quiet"] is True, row
    assert row["next_touch_date"] is None


async def test_the_worst_neglected_client_is_first(client, org):
    """The ordering is the whole point of the screen."""
    await _handed_over(client, org, "Sorting Client A", "meena")
    lead_b = await _handed_over(client, org, "Sorting Client B", "meena")

    # B was spoken to today; every never-spoken-to client outranks it.
    booked = await client.post(
        "/api/v1/meetings/schedule", headers=auth(org["meena_token"]),
        json={"lead_id": lead_b["id"], "title": "Catch-up",
              "started_at": "2026-08-31T10:00:00"},
    )
    assert booked.status_code == 200, booked.text

    rows = (await client.get("/api/v1/relationships/mine",
                             headers=auth(org["meena_token"]))).json()
    order = [r["lead_name"] for r in rows]
    assert order.index("Sorting Client A") < order.index("Sorting Client B"), order

    spoken = next(r for r in rows if r["lead_name"] == "Sorting Client B")
    assert spoken["last_touch_at"] is not None
    assert spoken["days_quiet"] is not None


async def test_a_planned_touch_shows_up_and_overdue_is_marked(client, org):
    """Relationship follow-ups are ordinary `followups` rows. Step 5 starts
    writing them from meetings; the screen has to read them correctly first.

    Booked here by the admin, not by Meena, and that is worth explaining.
    `POST /followups` is gated on `manage_leads`, which a relationship manager
    deliberately does not hold — it is the permission that also moves sales
    states. So an RM currently cannot book or complete a touch of their own,
    which is a real gap in the RM's job and belongs to step 5, where the
    follow-up lifecycle is built and the AI starts writing these rows itself.
    Widening the permission here, as a side effect of a screen that only reads,
    would be the wrong place to decide it.

    The screen shows whoever's touch it is: `_next_touch` filters by client and
    pending status, not by owner, because "when is this client next being
    spoken to" does not depend on who booked it.
    """
    lead = await _handed_over(client, org, "Planned Touch Client", "meena")
    yesterday = date.today() - timedelta(days=1)
    made = await client.post(
        "/api/v1/followups", headers=auth(org["admin_token"]),
        json={"lead_id": lead["id"], "due_date": yesterday.isoformat(),
              "channel": "call", "note": "Ask about the new lab"},
    )
    assert made.status_code == 200, made.text

    rows = (await client.get("/api/v1/relationships/mine",
                             headers=auth(org["meena_token"]))).json()
    row = next(r for r in rows if r["lead_name"] == "Planned Touch Client")
    assert row["next_touch_date"] == yesterday.isoformat()
    assert row["next_touch_note"] == "Ask about the new lab"
    assert row["next_touch_overdue"] is True


async def test_sales_cannot_open_the_relationship_managers_home(client, org):
    """`manage_relationships` is the RM's and the admin's. A sales agent
    asking for "my clients" is asking a question that has no answer for them."""
    resp = await client.get("/api/v1/relationships/mine",
                            headers=auth(org["priya_token"]))
    assert resp.status_code == 403, resp.text


# ── the client page ─────────────────────────────────────────────────────────

async def test_the_client_page_carries_the_story_and_what_we_know(client, org):
    """Reuses `replay_story` — the block already written for the revival card
    — rather than inventing a second summary that could disagree with it."""
    lead = await _handed_over(client, org, "Storied Client", "meena")
    note = await client.post(
        f"/api/v1/leads/{lead['id']}/intelligence",
        headers=auth(org["priya_token"]),
        json={"note": "The director prefers a call to an email", "category": "approach"},
    )
    assert note.status_code == 200, note.text

    resp = await client.get(f"/api/v1/leads/{lead['id']}/relationship",
                            headers=auth(org["meena_token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["engagement"]["manager_name"] == "Meena Manager"
    assert isinstance(body["story"], str) and body["story"], body
    notes = [n["note"] for n in body["intelligence"]]
    assert "The director prefers a call to an email" in notes, notes


async def test_a_client_with_no_history_still_renders(client, org):
    """`replay_story` returns "No prior history recorded." rather than an
    empty string, so the screen has a sentence to show on day one."""
    lead = await _handed_over(client, org, "Blank Slate Client", "meena")

    body = (await client.get(f"/api/v1/leads/{lead['id']}/relationship",
                             headers=auth(org["meena_token"]))).json()
    assert body["story"], "the page must never be blank"
    assert body["last_touch_at"] is None
    assert body["days_quiet"] is None
    assert body["next_touch_date"] is None


async def test_the_page_still_answers_for_a_client_nobody_looks_after(client, org):
    """Most clients will never have a relationship manager. The extra fields
    have to be present anyway, or every caller needs two code paths."""
    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": "Ordinary Client", "owner_id": org["priya_id"]},
    )
    lead = created.json()

    body = (await client.get(f"/api/v1/leads/{lead['id']}/relationship",
                             headers=auth(org["priya_token"]))).json()
    assert body["engagement"] is None
    assert "story" in body and body["story"]
    assert body["intelligence"] == []
