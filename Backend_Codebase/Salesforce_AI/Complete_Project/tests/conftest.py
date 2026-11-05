"""Test fixtures: isolated temp database, ASGI test client, seeded orgs.

The model layer is faked per-test where needed — tests never hit the network.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

# Isolated DB + storage BEFORE any app import (settings are cached).
_tmp = tempfile.mkdtemp(prefix="salesai_test_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_tmp).as_posix()}/test.db"
os.environ["STORAGE_DIR"] = f"{Path(_tmp).as_posix()}/storage"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"
os.environ["SECRET_KEY"] = "test-secret-key-for-tests-only-0123456789"
# Invalid key on purpose: tests must never hit the real model provider;
# best-effort paths (memory embeddings) degrade gracefully, others are faked.
os.environ["GEMINI_API_KEY"] = "test-invalid-key"
# The deterministic offline embedder, so the suite neither downloads a 1.1 GB
# model nor spends seconds loading one. Note this is also what made the suite
# stop calling Google on every stored note: with EMBEDDING_PROVIDER unset and a
# key present, embed_text used to make a real HTTP request per note and rely on
# it failing. The local provider has its own tests in test_memory_embeddings.py.
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["LLM_MAX_RETRIES"] = "0"
os.environ["SUPER_ADMIN_EMAIL"] = "super@platform-example.com"
os.environ["SUPER_ADMIN_PASSWORD"] = "SuperTest@123"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import _seed_super_admin, app  # noqa: E402

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _people_review_has_no_opinion(monkeypatch):
    """The model check on the people a meeting names (1 Oct 2026) answers
    "no opinion" in every test: each name is a person matching nothing, which
    leaves the spelling check deciding exactly as before. The test run reads
    the live `.env`, whose model key is real, so without this any test that
    reaches contact creation would make a real, paid, unpredictable call.
    `tests/test_contact_matching.py` replaces it with scripted answers."""
    from app.ai import planning

    async def no_opinion(*, org_id, people, contacts):
        return planning.parse_people_review(
            {}, people_count=len(people), contact_count=len(contacts))

    monkeypatch.setattr(planning, "review_meeting_people", no_opinion)


@pytest.fixture(autouse=True)
def _day_reading_reads_nothing(monkeypatch):
    """The strong model's reading of days and times (2 Oct 2026) gives no
    reading in every test, which is what an unavailable model gives: each
    caller then does exactly what it did before. The model key in the live
    `.env` is real, so without this the meeting tests would make real calls.
    `tests/test_day_reading.py` scripts the answers instead."""
    from app.ai import day_reading

    async def nothing(**_):
        return None

    monkeypatch.setattr(day_reading, "read_when", nothing)


@pytest.fixture(scope="session")
async def client():
    """App client without lifespan: no background workers — jobs stay queued
    so tests can run handlers deterministically."""
    await init_db()
    await _seed_super_admin()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    # Dispose DB connections: lingering aiosqlite threads are non-daemon and
    # keep the interpreter alive after the test run finishes.
    from app.database import engine

    await engine.dispose()


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def add_reached_contact(client, token: str, lead_id: str,
                              **fields) -> dict:
    """The contact a cold call produces, added by whoever holds `token` --
    which must be the lead's owner for it to count towards opening."""
    body = {"name": "Cold Call Contact", "phone": "+91 90000 00000", **fields}
    resp = await client.post(
        f"/api/v1/leads/{lead_id}/contacts", headers=auth(token), json=body,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def fresh_lead(client, token: str, name: str, **fields) -> dict:
    """A NEW client for this test, called `name` if that is free.

    Two clients may not share a name (2026-09-26) and the test organisations
    live for the whole run, so when another test already made one with this
    name, this one gets a short suffix instead of a refusal. Each test still
    starts from a client of its own, as it did before the rule.
    """
    import uuid  # noqa: PLC0415

    resp = await client.post("/api/v1/leads", headers=auth(token),
                             json={"name": name, **fields})
    if resp.status_code == 409:
        resp = await client.post("/api/v1/leads", headers=auth(token),
                                 json={"name": f"{name} {uuid.uuid4().hex[:6]}", **fields})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def lead_named(client, token: str, name: str, **fields) -> dict:
    """The client called `name`, created when missing, else the one on file.

    Two clients may not share a name (2026-09-26), and the test organisations
    live for the whole run, so a fixture that makes "the same client" in
    several tests must reuse it rather than create a second.
    """
    resp = await client.post("/api/v1/leads", headers=auth(token),
                             json={"name": name, **fields})
    if resp.status_code == 200:
        return resp.json()
    assert resp.status_code == 409, resp.text
    found = await client.get("/api/v1/leads", headers=auth(token), params={"q": name})
    for lead in found.json():
        if " ".join(lead["name"].split()).casefold() == " ".join(name.split()).casefold():
            return lead
    raise AssertionError(f"{name} refused as a duplicate but not found: {resp.text}")


async def open_lead(client, token: str, lead_id: str,
                    reason: str = "Positive response on the cold call") -> dict:
    """Move a freshly created lead out of pre-sales.

    `POST /leads` creates in COLD_CALLING: a lead is a name and a phone number
    until someone has actually called. Only the owner may open it, and the
    creator is the owner unless the request named someone else — so a test
    that created the lead can always open it.

    Tests about the established flow (meetings, state suggestions, execution)
    call this first, standing in for the cold call itself -- which includes
    the owner recording who they reached: opening needs a contact, added by
    the owner, with a phone or an email (2026-09-24).
    """
    lead = await client.get(f"/api/v1/leads/{lead_id}", headers=auth(token))
    if lead.status_code == 200 and lead.json().get("state") == "cold_calling":
        await add_reached_contact(client, token, lead_id)
    resp = await client.patch(
        f"/api/v1/leads/{lead_id}/state",
        headers=auth(token),
        json={"state": "open", "reason": reason},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(scope="session")
async def super_token(client) -> str:
    data = await login(client, "super@platform-example.com", "SuperTest@123")
    return data["access_token"]


async def create_org(
    client: httpx.AsyncClient, super_token: str, *, name: str, slug: str, domain: str
) -> dict:
    resp = await client.post(
        "/api/v1/orgs",
        headers=auth(super_token),
        json={
            "name": name,
            "slug": slug,
            "email_domain": domain,
            "admin_email": f"admin@{domain}",
            "admin_name": f"{name} Admin",
        },
    )
    assert resp.status_code == 200, resp.text
    org = resp.json()
    admin_login = await login(client, org["admin_email"], org["admin_temp_password"])
    org["admin_token"] = admin_login["access_token"]
    return org


@pytest.fixture(scope="session")
async def org_a(client, super_token) -> dict:
    """Org A with an admin token and one sales agent."""
    org = await create_org(
        client, super_token,
        name="Alpha Education", slug="alpha-edu", domain="alpha-example.com",
    )
    resp = await client.post(
        "/api/v1/admin/users",
        headers=auth(org["admin_token"]),
        json={"email": "agent@alpha-example.com", "name": "Asha Agent",
              "role": "sales_agent"},
    )
    assert resp.status_code == 200, resp.text
    agent = resp.json()
    agent_login = await login(client, "agent@alpha-example.com", agent["temp_password"])
    org["agent_token"] = agent_login["access_token"]
    org["agent_id"] = agent["id"]
    return org


@pytest.fixture(scope="session")
async def org_b(client, super_token) -> dict:
    return await create_org(
        client, super_token,
        name="Beta Learning", slug="beta-learn", domain="beta-example.com",
    )
