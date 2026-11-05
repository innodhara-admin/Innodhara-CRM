"""A sales lead can create a lead that is already open (7 Oct 2026).

Everyone else creates in cold calling exactly as before. The open lead is
built from the same steps as a lead created and later opened: the
cold-calling history row, the contact, the move to open, the announcement.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import ValidationFailedError
from app.services.lead_service import check_open_contact, looks_like_email
from tests.conftest import auth, create_org, login

API = "/api/v1"


def test_email_shapes():
    assert looks_like_email("anita@acme-example.com")
    assert looks_like_email("a.b+c@x.co.in")
    for bad in (None, "", "anita", "anita@acme", "anita at acme.com", "@acme.com",
                "anita@@acme.com", "anita@ acme.com"):
        assert not looks_like_email(bad), bad


def test_contact_rules():
    ok = check_open_contact({"name": " Anita Sharma ", "title": "Director",
                             "email": "Anita@Acme-Example.com", "phone": " "})
    assert ok == {"name": "Anita Sharma", "title": "Director",
                  "email": "anita@acme-example.com", "phone": None}
    cases = [
        (None, "add the contact at the client"),
        ({"title": "Director", "email": "a@b.co"}, "name"),
        ({"name": "Anita", "email": "a@b.co"}, "designation"),
        ({"name": "Anita", "title": "Director"}, "email address is required"),
        ({"name": "Anita", "title": "Director", "email": "anita-at-acme"},
         "doesn't look like an email address"),
    ]
    for contact, words in cases:
        with pytest.raises(ValidationFailedError) as err:
            check_open_contact(contact)
        assert words in err.value.message, (contact, err.value.message)


def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _user(client, org, name, role):
    email = f"{name.split()[0].lower()}{_hex()}@{org['domain']}"
    made = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                             json={"email": email, "name": name, "role": role})
    assert made.status_code == 200, made.text
    token = (await login(client, email, made.json()["temp_password"]))["access_token"]
    return {"id": made.json()["id"], "token": token, "name": name}


@pytest.fixture
async def org(client, super_token):
    slug = _hex()
    domain = f"open{slug}-example.com"
    team = await create_org(client, super_token, name=f"Open {slug}",
                            slug=f"open-{slug}", domain=domain)
    team["domain"] = domain
    team["boss"] = await _user(client, team, "Sunil Rao", "sales_lead")
    team["asha"] = await _user(client, team, "Asha Agent", "sales_agent")
    team["ravi"] = await _user(client, team, "Ravi Agent", "sales_agent")
    return team


CONTACT = {"name": "Anita Sharma", "title": "Director",
           "email": "anita@acme-example.com", "phone": "+91 90000 11111"}


async def _named(client, token, name):
    found = await client.get(f"{API}/leads", headers=auth(token), params={"q": name})
    return [lead for lead in found.json() if lead["name"] == name]


async def test_a_sales_lead_creates_an_open_lead(client, org):
    name = f"Acme Labs {_hex()}"
    made = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]),
                             json={"name": name, "city": "Pune", "open_now": True,
                                   "contact": CONTACT})
    assert made.status_code == 200, made.text
    lead = made.json()
    assert lead["state"] == "open"
    assert lead["owner_id"] == org["boss"]["id"]

    detail = (await client.get(f"{API}/leads/{lead['id']}",
                               headers=auth(org["boss"]["token"]))).json()
    [contact] = detail["contacts"]
    assert contact["name"] == "Anita Sharma" and contact["title"] == "Director"
    assert contact["email"] == "anita@acme-example.com"
    assert contact["is_primary"] and contact["added_by_owner"]
    moves = [(h["from"], h["to"]) for h in detail["state_history"]]
    assert ("cold_calling", "open") in moves and (None, "cold_calling") in moves
    opened = next(h for h in detail["state_history"] if h["to"] == "open")
    assert "Opened at creation by Sunil Rao" in opened["reason"]
    assert opened["by"] == "Sunil Rao"

    # The Home card that announces newly opened leads shows it.
    recent = (await client.get(f"{API}/leads/recently-opened",
                               headers=auth(org["asha"]["token"]))).json()
    assert any(r["id"] == lead["id"] for r in recent)
    # The rest of the sales floor is told; the opener is not.
    for who, told in (("asha", True), ("ravi", True), ("boss", False)):
        notes = (await client.get(f"{API}/notifications",
                                  headers=auth(org[who]["token"]))).json()
        hit = any(n["kind"] == "lead_opened" and n["entity_id"] == lead["id"]
                  for n in notes)
        assert hit is told, who


async def test_phone_is_optional(client, org):
    name = f"No Phone Co {_hex()}"
    contact = {k: v for k, v in CONTACT.items() if k != "phone"}
    made = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]),
                             json={"name": name, "open_now": True, "contact": contact})
    assert made.status_code == 200, made.text
    assert made.json()["state"] == "open"


@pytest.mark.parametrize("who", ["asha", "admin"])
async def test_only_a_sales_lead_may_open_at_creation(client, org, who):
    token = org["admin_token"] if who == "admin" else org[who]["token"]
    name = f"Refused {_hex()}"
    made = await client.post(f"{API}/leads", headers=auth(token),
                             json={"name": name, "open_now": True, "contact": CONTACT})
    assert made.status_code == 403, made.text
    assert "Only a sales lead" in made.json()["detail"]
    assert await _named(client, org["boss"]["token"], name) == []


async def test_an_open_lead_cannot_be_given_to_someone_else(client, org):
    name = f"Given Away {_hex()}"
    made = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]),
                             json={"name": name, "open_now": True, "contact": CONTACT,
                                   "owner_id": org["asha"]["id"]})
    assert made.status_code == 422, made.text
    assert "owned by you" in made.json()["detail"]
    assert await _named(client, org["boss"]["token"], name) == []


@pytest.mark.parametrize("contact, words", [
    (None, "add the contact"),
    ({"title": "Director", "email": "a@b.co"}, "name is required"),
    ({"name": "Anita", "email": "a@b.co"}, "designation is required"),
    ({"name": "Anita", "title": "Director"}, "email address is required"),
    ({"name": "Anita", "title": "Director", "email": "nope"}, "doesn't look like"),
])
async def test_a_bad_contact_creates_nothing(client, org, contact, words):
    name = f"Half Done {_hex()}"
    body = {"name": name, "open_now": True}
    if contact is not None:
        body["contact"] = contact
    made = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]), json=body)
    assert made.status_code == 422, made.text
    assert words in made.json()["detail"]
    assert await _named(client, org["boss"]["token"], name) == []


async def test_a_duplicate_name_is_still_refused(client, org):
    name = f"Twin Co {_hex()}"
    first = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]),
                              json={"name": name})
    assert first.status_code == 200
    again = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]),
                              json={"name": name, "open_now": True, "contact": CONTACT})
    assert again.status_code == 409, again.text
    assert len(await _named(client, org["boss"]["token"], name)) == 1


async def test_without_open_now_nothing_changes(client, org):
    """The old body, and a contact sent without open_now, create exactly what
    they always did: cold calling, the named owner, no contact."""
    name = f"Plain Co {_hex()}"
    made = await client.post(f"{API}/leads", headers=auth(org["boss"]["token"]),
                             json={"name": name, "owner_id": org["asha"]["id"],
                                   "contact": CONTACT})
    assert made.status_code == 200, made.text
    lead = made.json()
    assert lead["state"] == "cold_calling" and lead["owner_id"] == org["asha"]["id"]
    detail = (await client.get(f"{API}/leads/{lead['id']}",
                               headers=auth(org["boss"]["token"]))).json()
    assert detail["contacts"] == []
