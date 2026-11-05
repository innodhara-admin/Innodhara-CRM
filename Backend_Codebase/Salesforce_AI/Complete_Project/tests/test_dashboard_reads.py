"""Read paths a setup console needs and the API did not have."""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _program(client, token, code: str) -> str:
    resp = await client.post(
        "/api/v1/admin/programs",
        headers=auth(token),
        json={"name": f"Programme {code}", "code": code,
              "description": "Commissioning and handover of capacity."},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_playbooks_can_be_read_back(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "PBREAD")
    entries = [{"title": "Confirm site access", "required_skill": "scheduling",
                "offset_days": -7, "priority": "P1", "visible_to_client": False}]
    wrote = await client.post(
        "/api/v1/playbooks",
        headers=auth(token),
        json={"program_id": program_id, "phase": "preparation", "entries": entries},
    )
    assert wrote.status_code == 200, wrote.text

    resp = await client.get(
        f"/api/v1/playbooks?program_id={program_id}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["phase"] == "preparation"
    assert rows[0]["entries"] == entries
    assert rows[0]["is_current"] is True


async def test_playbooks_current_only_hides_superseded(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "PBVER")
    for title in ("First wave", "Second wave"):
        resp = await client.post(
            "/api/v1/playbooks",
            headers=auth(token),
            json={"program_id": program_id, "phase": "delivery",
                  "entries": [{"title": title, "required_skill": "general",
                               "offset_days": 0, "priority": "P2",
                               "visible_to_client": False}]},
        )
        assert resp.status_code == 200, resp.text

    current = await client.get(
        f"/api/v1/playbooks?program_id={program_id}&phase=delivery",
        headers=auth(token),
    )
    assert len(current.json()) == 1
    assert current.json()[0]["version"] == 2

    every = await client.get(
        f"/api/v1/playbooks?program_id={program_id}&phase=delivery"
        "&current_only=false",
        headers=auth(token),
    )
    assert len(every.json()) == 2


async def test_playbooks_are_org_scoped(client, org_a, org_b):
    resp = await client.get("/api/v1/playbooks", headers=auth(org_b["admin_token"]))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_vendor_contact_details_are_readable(client, org_a):
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/vendors",
        headers=auth(token),
        json={"name": "Northgate Logistics", "contact_name": "Ravi Menon",
              "phone": "+919000000010", "email": "ravi@northgate-example.com",
              "category": "transport", "notes": "Two-day lead time."},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get("/api/v1/vendors", headers=auth(token))).json()
    row = next(v for v in rows if v["name"] == "Northgate Logistics")
    assert row["contact_name"] == "Ravi Menon"
    assert row["phone"] == "+919000000010"
    assert row["email"] == "ravi@northgate-example.com"


async def test_approval_rule_fallback_and_auto_approve_are_readable(client, org_a):
    """Both fields are accepted by POST and stored, and were unreadable — so a
    reseed bundle exported a rule that came back waiting for a human when it had
    been set to auto-approve, with nothing to tell anyone (change #9)."""
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/approval-rules",
        headers=auth(token),
        json={"entity_type": "readback_probe", "condition": {},
              "rank": 10, "approver_role": "sales_lead",
              "fallback_role": "org_admin", "auto_approve": True,
              "description": "Reads back what the write accepted."},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/approval-rules", headers=auth(token))).json()
    row = next(r for r in rows if r["entity_type"] == "readback_probe")
    assert row["fallback_role"] == "org_admin"
    assert row["auto_approve"] is True


async def test_approval_rule_defaults_read_back_as_stored(client, org_a):
    """A rule that names neither must read back null and False — not absent, and
    not the truthy-looking values of the rule above. Without this, a response
    that hard-coded the two keys would pass the test above."""
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/approval-rules",
        headers=auth(token),
        json={"entity_type": "readback_defaults", "approver_role": "sales_lead"},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/approval-rules", headers=auth(token))).json()
    row = next(r for r in rows if r["entity_type"] == "readback_defaults")
    assert row["fallback_role"] is None
    assert row["auto_approve"] is False


async def test_demo_team_role_ids_are_readable_alongside_the_names(client, org_a):
    """The write takes ids and the read returned only names, and User.name is not
    unique — so a delete-and-recreate edit (there is no PATCH) could not restore
    the three roles, and the reseed bundle lost them (change #10)."""
    token = org_a["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()

    created = await client.post(
        "/api/v1/admin/demo-teams",
        headers=auth(token),
        json={"name": "Readback Demo Crew", "lead_user_id": me["user_id"],
              "media_rep_id": me["user_id"], "sales_rep_id": me["user_id"]},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/admin/demo-teams", headers=auth(token))).json()
    row = next(t for t in rows if t["name"] == "Readback Demo Crew")

    assert row["lead_user_id"] == me["user_id"]
    assert row["media_rep_id"] == me["user_id"]
    assert row["sales_rep_id"] == me["user_id"]

    # Rule 1 of 09 §2 is additive-only. The Android app calls this route and may
    # render these; an id that arrived by replacing a name is a behaviour change.
    assert row["lead"] == me["name"]
    assert row["media_rep"] == me["name"]
    assert row["sales_rep"] == me["name"]


async def test_demo_team_unset_roles_read_back_as_null_ids(client, org_a):
    """A team naming nobody must return null ids, not absent keys — the bundle
    distinguishes 'no lead' from 'the API cannot tell you'."""
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/admin/demo-teams",
        headers=auth(token), json={"name": "Readback Empty Crew"},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/admin/demo-teams", headers=auth(token))).json()
    row = next(t for t in rows if t["name"] == "Readback Empty Crew")

    # Presence first, then value: a missing key and a null both read as None
    # through .get(), and the console needs them to be different facts.
    for key in ("lead_user_id", "media_rep_id", "sales_rep_id"):
        assert key in row, f"{key} must be present and null, not absent"
        assert row[key] is None
    assert row["lead"] is None
