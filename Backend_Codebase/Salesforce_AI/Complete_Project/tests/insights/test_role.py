"""The sales_head role (23 Oct 2026): it exists, it signs in, and it holds one
permission, `view_sales_insights`, that nobody else holds.

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-23-sales-head-design.md
section 5. The last test is the guard for the user's rule "a new thing
completely": every existing permission still names exactly the roles it named
before this feature (the snapshot was taken before the first edit).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.constants import Role
from app.core.permissions import _MATRIX, has_permission
from tests.conftest import auth, create_org, login

BEFORE = Path(__file__).with_name("permissions_before.json")


@pytest.mark.asyncio
async def test_sales_head_can_be_created_and_sign_in(client, super_token):
    org = await create_org(client, super_token, name="Head Role Org",
                           slug="head-role-org", domain="headrole-example.com")
    made = await client.post(
        "/api/v1/admin/users", headers=auth(org["admin_token"]),
        json={"email": "head@headrole-example.com", "name": "Hema Head",
              "role": "sales_head", "department": "sales"},
    )
    assert made.status_code == 200, made.text
    session = await login(client, "head@headrole-example.com", made.json()["temp_password"])
    me = await client.get("/api/v1/auth/me", headers=auth(session["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "sales_head"


def test_only_sales_head_holds_view_sales_insights():
    for role in Role:
        assert has_permission(role.value, "view_sales_insights") is (role is Role.SALES_HEAD), role


def test_sales_head_holds_nothing_else():
    assert [p for p in _MATRIX if has_permission("sales_head", p)] == ["view_sales_insights"]


def test_existing_roles_unchanged():
    now = {p: sorted(r.value for r in roles) for p, roles in _MATRIX.items()
           if p != "view_sales_insights"}
    assert now == json.loads(BEFORE.read_text())
