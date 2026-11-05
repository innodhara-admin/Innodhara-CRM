"""Multi-organisation isolation and RBAC — the non-negotiables (doc §2, §13)."""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def test_org_isolation_between_tenants(client, org_a, org_b):
    """Two orgs with a same-named lead can never see each other's data."""
    import uuid

    # One name, fresh for this run, in both organisations: the same name in
    # two organisations is allowed; twice in one is not (2026-09-26).
    name = f"Green Valley School {uuid.uuid4().hex[:6]}"
    for org in (org_a, org_b):
        resp = await client.post(
            "/api/v1/leads",
            headers=auth(org["admin_token"]),
            json={"name": name, "city": "Delhi"},
        )
        assert resp.status_code == 200, resp.text

    a_leads = (
        await client.get("/api/v1/leads", headers=auth(org_a["admin_token"]))
    ).json()
    b_leads = (
        await client.get("/api/v1/leads", headers=auth(org_b["admin_token"]))
    ).json()
    a_ids = {lead["id"] for lead in a_leads}
    b_ids = {lead["id"] for lead in b_leads}
    assert a_ids and b_ids
    assert a_ids.isdisjoint(b_ids), "Lead ids leaked across organisations!"

    # Org B cannot fetch Org A's lead by id.
    resp = await client.get(
        f"/api/v1/leads/{next(iter(a_ids))}", headers=auth(org_b["admin_token"])
    )
    assert resp.status_code == 404


async def test_super_admin_cannot_read_org_data(client, super_token, org_a):
    resp = await client.get("/api/v1/leads", headers=auth(super_token))
    assert resp.status_code == 403


async def test_platform_stats_are_aggregates_only(client, super_token, org_a):
    resp = await client.get("/api/v1/orgs/platform/stats", headers=auth(super_token))
    assert resp.status_code == 200
    stats = resp.json()["organisations"]
    assert all(set(s) <= {"org", "active", "users", "leads", "meetings",
                          "ai_cost_usd_total"} for s in stats)


async def test_sales_agent_cannot_edit_pricing_or_staff(client, org_a):
    headers = auth(org_a["agent_token"])
    resp = await client.post(
        "/api/v1/admin/programs",
        headers=headers,
        json={"name": "X", "code": "X"},
    )
    assert resp.status_code == 403
    resp = await client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={"email": "x@alpha-example.com", "name": "X Y", "role": "sales_agent"},
    )
    assert resp.status_code == 403


async def test_staff_email_must_match_org_domain(client, org_a):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=auth(org_a["admin_token"]),
        json={"email": "someone@gmail.com", "name": "Out Sider", "role": "sales_agent"},
    )
    assert resp.status_code == 422


async def test_wrong_password_rejected(client, org_a):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "agent@alpha-example.com", "password": "not-the-password"},
    )
    assert resp.status_code == 401


async def test_unauthenticated_requests_rejected(client):
    resp = await client.get("/api/v1/leads")
    assert resp.status_code in (401, 403)
