"""The relationship_manager role: it exists, it logs in, and it cannot sell.

Step 2 of the Relationship Manager build order adds the role and nothing else.
There is no handover, no engagement and no RM screen yet — so what is worth
testing now is the shape of the hole the role sits in: an RM can be created,
can sign in, can read the clients they will look after, and is refused every
sales action by the server rather than merely being hidden from it in the app.

The last part matters more than it looks. `RoleGate` on the phone only decides
what to draw; the server is the enforcer. A role that is missing from the
matrix does not fail loudly, it fails permissively somewhere else, so each
refusal below is asserted against the API and not against the matrix.
"""
from __future__ import annotations

import pytest

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "rm-example.com"


@pytest.fixture(scope="module")
async def rm_org(client, super_token) -> dict:
    """An org with one sales agent and one relationship manager.

    Built fresh rather than reusing `org_a`: adding people to a session-scoped
    org changes what unrelated tests see, and this module adds a role that did
    not exist when those tests were written.
    """
    org = await create_org(
        client, super_token,
        name="Relationship Co", slug="relationship-co", domain=DOMAIN,
    )
    for key, email, name, role, department in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent", "sales"),
        ("meena", f"meena@{DOMAIN}", "Meena Manager",
         "relationship_manager", "relationship"),
    ):
        resp = await client.post(
            "/api/v1/admin/users", headers=auth(org["admin_token"]),
            json={"email": email, "name": name, "role": role,
                  "department": department},
        )
        assert resp.status_code == 200, resp.text
        user = resp.json()
        session = await login(client, email, user["temp_password"])
        org[f"{key}_id"] = user["id"]
        org[f"{key}_token"] = session["access_token"]
    return org


async def test_a_relationship_manager_can_be_created_and_sign_in(client, rm_org):
    """`POST /admin/users` validates the role against ORG_ROLES and the
    department against the Department enum, so both had to be added for this
    to get past 422 — which is the whole of step 2 on the backend."""
    me = await client.get("/api/v1/auth/me", headers=auth(rm_org["meena_token"]))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["role"] == "relationship_manager"
    assert body["department"] == "relationship"


async def test_the_relationship_manager_can_read_the_clients(client, rm_org):
    """`view_leads` — an RM has to be able to read the history of the client
    they look after, or there is nothing to look after them with."""
    lead = await client.post(
        "/api/v1/leads", headers=auth(rm_org["priya_token"]),
        json={"name": "Longstanding Client"},
    )
    assert lead.status_code == 200, lead.text

    listed = await client.get("/api/v1/leads", headers=auth(rm_org["meena_token"]))
    assert listed.status_code == 200, listed.text
    assert any(row["name"] == "Longstanding Client" for row in listed.json())


async def test_the_relationship_manager_cannot_move_a_lead_or_price_work(
    client, rm_org
):
    """The boundary, asserted against the server.

    An RM holds neither `manage_leads` nor `send_proposal`. Recording that as
    a refusal from the API — not as an entry in the matrix — is the point: the
    matrix is the thing that could be quietly widened later.
    """
    created = await client.post(
        "/api/v1/leads", headers=auth(rm_org["priya_token"]),
        json={"name": "Not Meenas To Sell"},
    )
    lead_id = created.json()["id"]

    refused = await client.patch(
        f"/api/v1/leads/{lead_id}/state", headers=auth(rm_org["meena_token"]),
        json={"state": "open", "reason": "not mine to decide"},
    )
    assert refused.status_code == 403, refused.text

    own = await client.post(
        "/api/v1/leads", headers=auth(rm_org["meena_token"]),
        json={"name": "A Lead An RM Should Not Create"},
    )
    assert own.status_code == 403, own.text


async def test_the_relationship_manager_may_record_a_meeting(client, rm_org):
    """`record_meeting` — catch-up meetings are the job, so the permission has
    to be held; the light relationship pipeline that reads it arrived in step
    5 and is covered by `test_relationship_meetings.py`.

    Asserted through the scheduling route, which needs no audio: what is being
    checked is that the role gets past `require_permission`, not that the
    transcription pipeline runs.
    """
    created = await client.post(
        "/api/v1/leads", headers=auth(rm_org["priya_token"]),
        json={"name": "Client To Keep Warm"},
    )
    lead_id = created.json()["id"]
    # Out of pre-sales first: a meeting cannot be booked against a lead nobody
    # has phoned yet, and that guard is older than this role.
    await add_reached_contact(client, rm_org["priya_token"], lead_id)
    opened = await client.patch(
        f"/api/v1/leads/{lead_id}/state", headers=auth(rm_org["priya_token"]),
        json={"state": "open", "reason": "answered the call"},
    )
    assert opened.status_code == 200, opened.text

    booked = await client.post(
        "/api/v1/meetings/schedule", headers=auth(rm_org["meena_token"]),
        json={"lead_id": lead_id, "title": "Catch-up",
              "started_at": "2026-09-15T10:00:00"},
    )
    assert booked.status_code == 200, booked.text
