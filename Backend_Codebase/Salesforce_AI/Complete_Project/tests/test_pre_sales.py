"""Pre-sales: a lead is assigned, cold called, and only then opened.

`POST /leads` creates in COLD_CALLING. Only the lead's owner may take it out
of that state, because only they made the calls. Everything from OPEN onward
is the established flow and is deliberately untouched — the last test here
exists to prove that.

The org is built fresh for this module rather than reusing `org_a`: opening a
lead notifies every sales agent and sales lead in the organisation, and adding
people to a session-scoped org would change what unrelated tests see.
"""
from __future__ import annotations

import pytest

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "presales-example.com"


@pytest.fixture(scope="module")
async def org(client, super_token) -> dict:
    """An org with two sales agents and a sales lead."""
    org = await create_org(
        client, super_token,
        name="Presales Co", slug="presales-co", domain=DOMAIN,
    )
    for key, email, name, role in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent"),
        ("ravi", f"ravi@{DOMAIN}", "Ravi Agent", "sales_agent"),
        ("siva", f"siva@{DOMAIN}", "Siva Lead", "sales_lead"),
    ):
        resp = await client.post(
            "/api/v1/admin/users", headers=auth(org["admin_token"]),
            json={"email": email, "name": name, "role": role},
        )
        assert resp.status_code == 200, resp.text
        user = resp.json()
        session = await login(client, email, user["temp_password"])
        org[f"{key}_id"] = user["id"]
        org[f"{key}_token"] = session["access_token"]
    return org


async def _new_lead(client, token: str, name: str, owner_id: str | None = None) -> dict:
    body: dict = {"name": name}
    if owner_id:
        body["owner_id"] = owner_id
    resp = await client.post("/api/v1/leads", headers=auth(token), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _set_state(client, token: str, lead_id: str, state: str,
                     reason: str | None = None):
    return await client.patch(
        f"/api/v1/leads/{lead_id}/state", headers=auth(token),
        json={"state": state, "reason": reason},
    )


# ── creation and assignment ──────────────────────────────────────────────

async def test_a_new_lead_starts_in_cold_calling_owned_by_the_named_agent(
    client, org
):
    lead = await _new_lead(client, org["siva_token"], "XYZ School", org["priya_id"])
    assert lead["state"] == "cold_calling"
    assert lead["owner_id"] == org["priya_id"]

    detail = (
        await client.get(f"/api/v1/leads/{lead['id']}", headers=auth(org["siva_token"]))
    ).json()
    assert detail["owner_name"] == "Priya Agent"
    first = detail["state_history"][-1]
    assert first["to"] == "cold_calling"
    # The timeline's opening node reads as a sentence, naming both people.
    assert "Priya Agent" in first["reason"] and "Siva Lead" in first["reason"]
    assert first["by"] == "Siva Lead"


async def test_assignment_notifies_the_owner_and_nobody_else(client, org):
    await _new_lead(client, org["siva_token"], "Notify One School", org["priya_id"])

    priya = (
        await client.get("/api/v1/notifications", headers=auth(org["priya_token"]))
    ).json()
    assert any(
        n["kind"] == "lead_assigned" and "Notify One School" in n["title"]
        for n in priya
    ), "the new owner was never told"

    ravi = (
        await client.get("/api/v1/notifications", headers=auth(org["ravi_token"]))
    ).json()
    assert not any("Notify One School" in n["title"] for n in ravi), \
        "an unrelated agent was notified about someone else's assignment"


async def test_assigning_to_a_stranger_is_refused(client, org):
    resp = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": "Stranger School", "owner_id": "nosuchuser0000000000000000000000"},
    )
    assert resp.status_code == 422
    assert "organisation" in resp.json()["detail"]


async def test_creating_without_an_owner_still_works_and_owns_it_yourself(
    client, org
):
    """The fallback the API has always had, kept intact."""
    lead = await _new_lead(client, org["priya_token"], "Self Owned School")
    assert lead["owner_id"] == org["priya_id"]
    assert lead["state"] == "cold_calling"


# ── who may leave pre-sales ──────────────────────────────────────────────

async def test_the_owner_opens_the_lead(client, org):
    lead = await _new_lead(client, org["siva_token"], "Owner Opens School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    resp = await _set_state(client, org["priya_token"], lead["id"], "open",
                            "Good response from the school")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open"


async def test_another_agent_cannot_open_someone_elses_lead(client, org):
    lead = await _new_lead(client, org["siva_token"], "Not Ravis School",
                           org["priya_id"])
    resp = await _set_state(client, org["ravi_token"], lead["id"], "open")
    assert resp.status_code == 403
    assert "Priya Agent" in resp.json()["detail"], \
        "the refusal should name who actually owns it"


async def test_a_sales_lead_cannot_overrule_the_owner(client, org):
    """Siva assigned it, but Priya made the calls — the judgement is hers."""
    lead = await _new_lead(client, org["siva_token"], "Not Sivas Call School",
                           org["priya_id"])
    resp = await _set_state(client, org["siva_token"], lead["id"], "open")
    assert resp.status_code == 403


async def test_the_org_admin_keeps_a_break_glass_path(client, org):
    lead = await _new_lead(client, org["siva_token"], "Break Glass School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    resp = await _set_state(client, org["admin_token"], lead["id"], "open",
                            "Priya has left; reopening centrally")
    assert resp.status_code == 200, resp.text


async def test_the_owner_can_drop_a_dead_cold_call(client, org):
    lead = await _new_lead(client, org["siva_token"], "Dead End School",
                           org["priya_id"])
    resp = await _set_state(client, org["priya_token"], lead["id"], "lost_for_now",
                            "Not interested this academic year")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "lost_for_now"


async def test_pre_sales_cannot_skip_straight_to_active(client, org):
    """No shortcut past OPEN: the established flow starts where it always did."""
    lead = await _new_lead(client, org["siva_token"], "No Shortcut School",
                           org["priya_id"])
    resp = await _set_state(client, org["priya_token"], lead["id"], "active")
    assert resp.status_code == 422
    assert "Cannot move lead" in resp.json()["detail"]


# ── opening tells the floor ──────────────────────────────────────────────

async def test_opening_announces_the_lead_to_the_sales_team(client, org):
    lead = await _new_lead(client, org["siva_token"], "Announce School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open",
                     "Good response from the school")

    for who in ("ravi", "siva"):
        feed = (
            await client.get("/api/v1/notifications",
                             headers=auth(org[f"{who}_token"]))
        ).json()
        opened = [n for n in feed
                  if n["kind"] == "lead_opened" and "Announce School" in n["title"]]
        assert opened, f"{who} was not told the lead opened"
        assert "Good response" in (opened[0]["body"] or ""), \
            "the owner's own words should travel with the announcement"


async def test_the_opener_is_not_notified_about_their_own_action(client, org):
    lead = await _new_lead(client, org["siva_token"], "Self Notify School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open", "Positive")
    feed = (
        await client.get("/api/v1/notifications", headers=auth(org["priya_token"]))
    ).json()
    assert not any(
        n["kind"] == "lead_opened" and "Self Notify School" in n["title"]
        for n in feed
    )


# ── the home-screen window ───────────────────────────────────────────────

async def test_a_newly_opened_lead_appears_then_clears(client, org):
    lead = await _new_lead(client, org["siva_token"], "Feed School", org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open", "Keen")

    feed = (
        await client.get("/api/v1/leads/recently-opened",
                         headers=auth(org["ravi_token"]))
    ).json()
    row = next((r for r in feed if r["id"] == lead["id"]), None)
    assert row is not None, "a just-opened lead is not on the floor's home screen"
    assert row["owner_name"] == "Priya Agent"
    assert row["reason"] == "Keen"

    # Someone records a meeting and confirms ACTIVE: the announcement is spent.
    await _set_state(client, org["priya_token"], lead["id"], "active")
    feed = (
        await client.get("/api/v1/leads/recently-opened",
                         headers=auth(org["ravi_token"]))
    ).json()
    assert not any(r["id"] == lead["id"] for r in feed), \
        "the card should clear once the lead is being worked"


async def test_a_lead_still_cold_calling_is_not_announced(client, org):
    lead = await _new_lead(client, org["siva_token"], "Quiet School", org["priya_id"])
    feed = (
        await client.get("/api/v1/leads/recently-opened",
                         headers=auth(org["ravi_token"]))
    ).json()
    assert not any(r["id"] == lead["id"] for r in feed)


# ── the owner picker ─────────────────────────────────────────────────────

async def test_assignable_owners_lists_agents_only(client, org):
    resp = await client.get("/api/v1/leads/assignable-owners",
                            headers=auth(org["siva_token"]))
    assert resp.status_code == 200, "a sales lead must be able to fill the picker"
    people = resp.json()
    ids = {p["id"] for p in people}
    assert org["priya_id"] in ids and org["ravi_id"] in ids
    assert org["siva_id"] not in ids, "a sales lead is not an assignable owner"
    assert all(p["name"] for p in people), "the picker needs something to show"


async def test_assignable_owners_is_not_admin_only(client, org):
    """The regression this endpoint exists for: /admin/users is org-admin
    only, so the person who actually assigns leads could not read it."""
    assert (
        await client.get("/api/v1/admin/users", headers=auth(org["siva_token"]))
    ).status_code == 403
    assert (
        await client.get("/api/v1/leads/assignable-owners",
                         headers=auth(org["siva_token"]))
    ).status_code == 200


# ── gating ───────────────────────────────────────────────────────────────

async def test_a_meeting_cannot_be_booked_while_cold_calling(client, org):
    lead = await _new_lead(client, org["siva_token"], "Too Early School",
                           org["priya_id"])
    resp = await client.post(
        "/api/v1/meetings/schedule", headers=auth(org["priya_token"]),
        json={"lead_id": lead["id"], "started_at": "2026-12-01T10:00:00"},
    )
    assert resp.status_code == 422
    assert "cold calling" in resp.json()["detail"]

    # ...and works the moment the owner opens it.
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open", "Keen")
    resp = await client.post(
        "/api/v1/meetings/schedule", headers=auth(org["priya_token"]),
        json={"lead_id": lead["id"], "started_at": "2026-12-01T10:00:00"},
    )
    assert resp.status_code == 200, resp.text


# ── the promise that nothing after OPEN changed ──────────────────────────

async def test_the_owner_drives_their_own_lead_the_whole_way(client, org):
    """The established flow, walked by the person whose lead it is.

    This used to be walked by Ravi, who does not own the lead, and asserted
    that he was allowed — that was the old rule, where `manage_leads` was the
    entire check and every agent holds it. Ownership now decides from OPEN
    onward too, so the walk belongs to Priya. Nothing else about the flow
    changed, which is what this still exists to prove.
    """
    lead = await _new_lead(client, org["siva_token"], "Usual Flow School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open", "Good response")

    for target in ("active", "execution_in_progress",
                   "client_execution_in_progress", "closed"):
        resp = await _set_state(client, org["priya_token"], lead["id"], target)
        assert resp.status_code == 200, \
            f"the owner was blocked at {target} — the gate is too tight"
        assert resp.json()["state"] == target


async def test_another_agent_cannot_move_someone_elses_lead(client, org):
    """The gap this rule closes.

    Ravi holds `manage_leads` and until now that was enough to walk Priya's
    lead to closed. `closed` means won and delivered and it is what reporting
    counts, so the person who did the work has to be the one who says it
    happened.
    """
    lead = await _new_lead(client, org["siva_token"], "Somebody Elses School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open", "Good response")

    resp = await _set_state(client, org["ravi_token"], lead["id"], "active")
    assert resp.status_code == 403, resp.text
    assert "Priya Agent" in resp.json()["detail"], \
        "the refusal has to name the owner, or it is not actionable"

    detail = (
        await client.get(f"/api/v1/leads/{lead['id']}",
                         headers=auth(org["priya_token"]))
    ).json()
    assert detail["state"] == "open", "a refused move must not have moved it"


async def test_a_sales_lead_moves_any_lead_in_the_team(client, org):
    """Siva did not make the calls, but he runs the team and covers absences.

    Deliberately wider than the cold-calling rule above, which excludes even
    him — the two gates answer different questions.
    """
    lead = await _new_lead(client, org["siva_token"], "Team Cover School",
                           org["priya_id"])
    await add_reached_contact(client, org["priya_token"], lead["id"])
    await _set_state(client, org["priya_token"], lead["id"], "open", "Good response")

    resp = await _set_state(client, org["siva_token"], lead["id"], "active",
                            "Priya is on leave; the client called me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "active"


async def test_the_silence_sweep_never_calls_a_cold_calling_lead_cold(client, org):
    """`cold` means a lead we were working went quiet. A lead nobody has
    phoned yet must never be labelled with it — the two words are close
    enough that a future edit could conflate them."""
    from app.core.constants import LEAD_STATE_TRANSITIONS, LeadState

    assert LeadState.COLD not in LEAD_STATE_TRANSITIONS[LeadState.COLD_CALLING]
    assert LEAD_STATE_TRANSITIONS[LeadState.COLD_CALLING] == {
        LeadState.OPEN, LeadState.LOST_FOR_NOW,
    }
