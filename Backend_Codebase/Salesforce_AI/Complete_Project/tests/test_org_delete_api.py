# tests/test_org_delete_api.py
"""POST /admin/delete-organisation: the dashboard's "delete this organisation".

Every test makes its own organisations: org_a/org_b are session-scoped, and
deleting one would break every test that runs afterwards.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.database import engine
from app.services import org_delete, storage
from tests.conftest import auth, create_org, login

pytestmark = pytest.mark.asyncio

URL = "/api/v1/admin/delete-organisation"


@pytest.fixture(autouse=True)
def _backups_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(org_delete, "default_backup_root", lambda: tmp_path / "backups")


async def _seed(client, org) -> None:
    """One lead, one program, one skill and one stored file."""
    token = org["admin_token"]
    lead = await client.post("/api/v1/leads", headers=auth(token),
                             json={"name": f"Lead of {org['name']}"})
    assert lead.status_code == 200, lead.text
    prog = await client.post("/api/v1/admin/programs", headers=auth(token),
                             json={"name": "Commissioning", "code": "ODEL",
                                   "description": "Halls."})
    assert prog.status_code == 200, prog.text
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    skill = await client.post("/api/v1/skills", headers=auth(token),
                              json={"user_id": me["user_id"], "skill": "scheduling",
                                    "level": "good"})
    assert skill.status_code == 200, skill.text
    storage.save_bytes(org["id"], "cards", "card.png", b"\x89PNG card")


async def _org(client, super_token, tag: str) -> dict:
    org = await create_org(client, super_token, name=f"Odel {tag} Learning",
                           slug=f"odel-{tag}", domain=f"odel-{tag}-example.com")
    await _seed(client, org)
    return org


async def _dry_run(client, org) -> dict:
    resp = await client.post(URL, headers=auth(org["admin_token"]), json={"dry_run": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _left(org_id: str) -> dict:
    async with engine.connect() as conn:
        return await conn.run_sync(org_delete.left_over, org_id)


async def test_dry_run_reports_and_changes_nothing(client, super_token):
    org = await _org(client, super_token, "dry")
    first = await _dry_run(client, org)
    assert first["applied"] is False
    assert first["org"] == {"id": org["id"], "name": org["name"]}
    assert first["rows"]["leads"] == 1
    assert first["files"] == 1
    assert [u["email"] for u in first["users"]] == [org["admin_email"]]
    assert first["expected_confirmation"] == f"DELETE {org['name']}"
    assert (await _dry_run(client, org))["rows"] == first["rows"]
    me = await client.get("/api/v1/auth/me", headers=auth(org["admin_token"]))
    assert me.status_code == 200


async def test_wrong_text_is_refused_and_nothing_changes(client, super_token):
    org = await _org(client, super_token, "text")
    before = await _dry_run(client, org)
    resp = await client.post(URL, headers=auth(org["admin_token"]), json={
        "dry_run": False, "confirm_text": f"DELETE {org['name']}x",
        "password": org["admin_temp_password"],
    })
    assert resp.status_code == 422, resp.text
    assert "Nothing was deleted" in resp.text
    assert (await _dry_run(client, org))["rows"] == before["rows"]
    await login(client, org["admin_email"], org["admin_temp_password"])


async def test_wrong_password_is_refused_and_nothing_changes(client, super_token):
    org = await _org(client, super_token, "pass")
    before = await _dry_run(client, org)
    resp = await client.post(URL, headers=auth(org["admin_token"]), json={
        "dry_run": False, "confirm_text": f"DELETE {org['name']}", "password": "wrong-one",
    })
    assert resp.status_code == 422, resp.text
    assert "password" in resp.text
    assert (await _dry_run(client, org))["rows"] == before["rows"]
    assert (await client.get("/api/v1/auth/me",
                             headers=auth(org["admin_token"]))).status_code == 200


async def test_a_sales_agent_cannot_delete(client, super_token):
    org = await _org(client, super_token, "agent")
    made = await client.post("/api/v1/admin/users", headers=auth(org["admin_token"]), json={
        "email": "agent@odel-agent-example.com", "name": "Odel Agent", "role": "sales_agent",
    })
    assert made.status_code == 200, made.text
    token = (await login(client, "agent@odel-agent-example.com",
                         made.json()["temp_password"]))["access_token"]
    for body in ({"dry_run": True},
                 {"dry_run": False, "confirm_text": f"DELETE {org['name']}",
                  "password": made.json()["temp_password"]}):
        resp = await client.post(URL, headers=auth(token), json=body)
        assert resp.status_code == 403, resp.text
    assert (await _left(org["id"]))["leads"] == 1


async def test_a_super_admin_cannot_delete(client, super_token):
    resp = await client.post(URL, headers=auth(super_token), json={"dry_run": True})
    assert resp.status_code == 403, resp.text


async def test_delete_removes_everything_and_ends_every_login(client, super_token):
    victim = await _org(client, super_token, "victim")
    bystander = await _org(client, super_token, "bystander")
    resp = await client.post(URL, headers=auth(victim["admin_token"]), json={
        "dry_run": False, "confirm_text": f"  delete   {victim['name'].lower()} ",
        "password": victim["admin_temp_password"],
    })
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["applied"] is True
    assert result["remaining"] == {}
    assert result["files_removed"] == 1
    assert result["deleted"]["organisations"] == 1
    assert result["backup_folder"].endswith(f"_{victim['id']}")
    assert "backups" in result["backup_folder"]

    # No login is left, and the old token is dead.
    gone = await client.post("/api/v1/auth/login", json={
        "email": victim["admin_email"], "password": victim["admin_temp_password"]})
    assert gone.status_code == 401
    me = await client.get("/api/v1/auth/me", headers=auth(victim["admin_token"]))
    assert me.status_code == 401

    # No row, no file, no audit trace.
    assert await _left(victim["id"]) == {}
    assert not (get_settings().storage_path / "orgs" / victim["id"]).exists()
    async with engine.connect() as conn:
        traces = (await conn.execute(text(
            "SELECT count(*) FROM audit_log WHERE org_id = :o OR entity_id = :o "
            "OR detail LIKE :like"), {"o": victim["id"], "like": f"%{victim['id']}%"}
        )).scalar_one()
    assert traces == 0

    # The bystander is untouched.
    await login(client, bystander["admin_email"], bystander["admin_temp_password"])
    assert (await _left(bystander["id"]))["leads"] == 1
    assert (get_settings().storage_path / "orgs" / bystander["id"]).is_dir()


async def test_the_slug_and_emails_are_free_again(client, super_token):
    org = await _org(client, super_token, "again")
    resp = await client.post(URL, headers=auth(org["admin_token"]), json={
        "dry_run": False, "confirm_text": f"DELETE {org['name']}",
        "password": org["admin_temp_password"],
    })
    assert resp.status_code == 200, resp.text
    again = await create_org(client, super_token, name=org["name"], slug="odel-again",
                             domain="odel-again-example.com")
    assert again["id"] != org["id"]
