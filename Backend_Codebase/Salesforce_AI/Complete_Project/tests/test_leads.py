"""Lead journey: state machine, importance flag, contacts, intelligence."""
from __future__ import annotations

import pytest

from tests.conftest import auth, open_lead

pytestmark = pytest.mark.asyncio


async def _make_lead(client, token: str, name: str) -> dict:
    resp = await client.post(
        "/api/v1/leads", headers=auth(token), json={"name": name}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_valid_state_progression(client, org_a):
    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "State Progress School")
    # Pre-sales first: a new lead is nobody's conversation yet.
    assert lead["state"] == "cold_calling"
    assert (await open_lead(client, token, lead["id"]))["state"] == "open"

    for target in ("active", "execution_in_progress",
                   "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state",
            headers=auth(token),
            json={"state": target, "reason": "test"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == target


async def test_invalid_state_jump_rejected(client, org_a):
    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "Invalid Jump School")
    resp = await client.patch(
        f"/api/v1/leads/{lead['id']}/state",
        headers=auth(token),
        json={"state": "closed"},
    )
    assert resp.status_code == 422
    assert "Cannot move lead" in resp.json()["detail"]


async def test_cold_and_reengage(client, org_a):
    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "Cold School")
    await open_lead(client, token, lead["id"])
    for target in ("active", "cold", "active"):  # goes quiet, re-engages
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state",
            headers=auth(token),
            json={"state": target},
        )
        assert resp.status_code == 200, resp.text
    history = (
        await client.get(f"/api/v1/leads/{lead['id']}", headers=auth(token))
    ).json()["state_history"]
    assert len(history) >= 4  # created + 3 moves


async def test_important_flag_is_not_a_state(client, org_a):
    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "Important School")
    await open_lead(client, token, lead["id"])
    resp = await client.patch(
        f"/api/v1/leads/{lead['id']}",
        headers=auth(token),
        json={"is_important": True},
    )
    body = resp.json()
    assert body["is_important"] is True
    assert body["state"] == "open"  # unchanged — flag, not state (doc §4)


async def test_contacts_and_intelligence(client, org_a):
    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "Contact School")
    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/contacts",
        headers=auth(token),
        json={"name": "Mrs. Sharma", "title": "Principal",
              "email": "sharma@contact.test", "is_primary": True},
    )
    assert resp.status_code == 200

    # Intelligence note (memory embedding is best-effort; may be skipped offline)
    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/intelligence",
        headers=auth(token),
        json={"note": "Prefers Hindi-medium workshops", "source": "voice"},
    )
    assert resp.status_code == 200

    detail = (
        await client.get(f"/api/v1/leads/{lead['id']}", headers=auth(token))
    ).json()
    assert detail["contacts"][0]["name"] == "Mrs. Sharma"
    assert any("Hindi" in n["note"] for n in detail["intelligence"])


async def test_consent_record(client, org_a):
    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "Consent School")
    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/consent",
        headers=auth(token),
        json={"method": "verbal", "note": "Agreed at meeting start"},
    )
    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
