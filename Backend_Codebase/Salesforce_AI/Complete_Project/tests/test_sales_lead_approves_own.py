"""A sales lead's own draft waits in that sales lead's own Approvals.

Live, 2 Nov 2026: a sales lead asked Jarvis for a meeting. The invite was
drafted with `request_approval=True`, and the approval went to the OLDEST
sales lead in the organisation (`find_role_user` takes the first created).
The Approvals list only shows items addressed to you and only that person may
decide, so the sales lead who asked saw nothing to approve, in Jarvis or in
the Approvals tab. Every sales lead but the first one hit this.

Decided 4 Nov 2026: when the sender holds the approving role, the approval is
theirs. Anyone else (a sales agent) still goes to a sales lead as before.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.comms import Approval
from app.services import message_service
from tests.conftest import auth, create_org, login

pytestmark = pytest.mark.asyncio


async def _add_user(client, admin_token, email, name, role):
    resp = await client.post(
        "/api/v1/admin/users", headers=auth(admin_token),
        json={"email": email, "name": name, "role": role})
    assert resp.status_code == 200, resp.text
    user = resp.json()
    token = (await login(client, email, user["temp_password"]))["access_token"]
    return user["id"], token


async def _draft_as(org_id, user_id, role, email, name):
    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_id, user_id=user_id, role=role,
                         email=email, name=name)
        message = await message_service.create_message(
            db, ctx, channel="email", kind="meeting_invite",
            to_address="principal@client-example.com",
            subject="Meeting invitation", body="Dear Principal,\n\nSee you Tuesday.",
            request_approval=True)
        await db.commit()
        approval = (await db.execute(select(Approval).where(
            Approval.entity_id == message.id))).scalar_one()
        return approval


@pytest.fixture(scope="module")
async def team(client, super_token):
    org = await create_org(client, super_token, name="Own Approvals",
                           slug="own-approvals", domain="own-approvals-example.com")
    people = {}
    for key, name, role in (("first_lead", "Rahul First", "sales_lead"),
                            ("second_lead", "Ekta Second", "sales_lead"),
                            ("agent", "Indu Agent", "sales_agent")):
        email = f"{key}@own-approvals-example.com"
        uid, token = await _add_user(client, org["admin_token"], email, name, role)
        people[key] = {"id": uid, "token": token, "email": email,
                       "name": name, "role": role}
    return org, people


async def test_a_second_sales_lead_approves_their_own_draft(client, team):
    org, people = team
    me = people["second_lead"]
    approval = await _draft_as(org["id"], me["id"], me["role"], me["email"], me["name"])
    assert approval.requested_from_user_id == me["id"], (
        "the draft went to another sales lead, so the one who asked has nothing "
        "to approve (live, 2 Nov 2026)"
    )
    listed = await client.get("/api/v1/approvals?status=pending",
                              headers=auth(me["token"]))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    rows = body if isinstance(body, list) else body.get("items", body.get("approvals", []))
    assert approval.id in [r["id"] for r in rows]


async def test_a_sales_agents_draft_still_goes_to_a_sales_lead(team):
    org, people = team
    agent = people["agent"]
    approval = await _draft_as(org["id"], agent["id"], agent["role"],
                               agent["email"], agent["name"])
    assert approval.requested_from_user_id == people["first_lead"]["id"]
    assert approval.requested_from_role == "sales_lead"
