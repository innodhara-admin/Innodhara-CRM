"""No two clients with the same name (26 Sep 2026).

Asked for after the live org ended up with two "Abc School" and two "Xavier
School" leads. A name identical to one already on file, ignoring upper and
lower case and extra spaces, is refused wherever a lead is created: the app
(POST /leads), Jarvis, and chain deals. The message names the client on file
and its owner, so the person can go to it instead.
"""
from __future__ import annotations

import uuid

from tests.conftest import auth, create_org, login

API = "/api/v1"


async def _org(client, super_token):
    slug = uuid.uuid4().hex[:8]
    org = await create_org(client, super_token, name=f"Dup {slug}", slug=f"dup-{slug}",
                           domain=f"dup{slug}-example.com")
    created = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                                json={"email": f"siva@dup{slug}-example.com",
                                      "name": "Siva", "role": "sales_agent"})
    token = (await login(client, f"siva@dup{slug}-example.com",
                         created.json()["temp_password"]))["access_token"]
    return org, token


async def _create(client, token, name):
    return await client.post(f"{API}/leads", headers=auth(token), json={"name": name})


async def test_the_same_name_in_any_case_is_refused(client, super_token):
    org, token = await _org(client, super_token)
    assert (await _create(client, token, "ABC School")).status_code == 200
    for same in ("abc school", "ABC SCHOOL", "  Abc   School "):
        resp = await _create(client, token, same)
        assert resp.status_code == 409, (same, resp.text)
        detail = resp.json()["detail"]
        assert "ABC School is already on file" in detail
        assert "owned by Siva" in detail


async def test_a_different_name_is_fine(client, super_token):
    org, token = await _org(client, super_token)
    assert (await _create(client, token, "ABC School")).status_code == 200
    assert (await _create(client, token, "ABC School Hyderabad")).status_code == 200
    assert (await _create(client, token, "ABC Schools")).status_code == 200


async def test_another_organisation_may_use_the_name(client, super_token):
    _, first = await _org(client, super_token)
    _, second = await _org(client, super_token)
    assert (await _create(client, first, "Shared Name School")).status_code == 200
    assert (await _create(client, second, "Shared Name School")).status_code == 200
