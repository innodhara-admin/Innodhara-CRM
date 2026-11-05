# tests/test_dashboard_staff.py
"""Staff fields the go-live checklist names but the API could not set (D4)."""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def test_department_survives_create_and_is_readable(client, org_a):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=auth(org_a["admin_token"]),
        json={
            "email": "ops.lead@alpha-example.com",
            "name": "Omar Ops",
            "role": "operations_lead",
            "department": "operations",
            "designation": "Head of Delivery",
            "whatsapp_number": "+919000000001",
            "max_open_tasks": 12,
            "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["department"] == "operations"
    assert created["max_open_tasks"] == 12

    detail = await client.get(
        f"/api/v1/admin/users/{created['id']}", headers=auth(org_a["admin_token"])
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["designation"] == "Head of Delivery"
    assert body["whatsapp_number"] == "+919000000001"
    assert body["working_days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]


async def test_unknown_department_is_refused(client, org_a):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=auth(org_a["admin_token"]),
        json={
            "email": "bad.dept@alpha-example.com",
            "name": "Bad Dept",
            "role": "sales_agent",
            "department": "marketing",
        },
    )
    assert resp.status_code == 422
    assert "marketing" in resp.text


async def test_staff_detail_is_org_scoped(client, org_a, org_b):
    listing = await client.get(
        "/api/v1/admin/users", headers=auth(org_a["admin_token"])
    )
    victim_id = listing.json()[0]["id"]
    resp = await client.get(
        f"/api/v1/admin/users/{victim_id}", headers=auth(org_b["admin_token"])
    )
    assert resp.status_code == 404


async def test_patch_updates_the_new_fields(client, org_a):
    resp = await client.patch(
        f"/api/v1/admin/users/{org_a['agent_id']}",
        headers=auth(org_a["admin_token"]),
        json={"department": "sales", "max_open_tasks": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["department"] == "sales"
    assert resp.json()["max_open_tasks"] == 5
