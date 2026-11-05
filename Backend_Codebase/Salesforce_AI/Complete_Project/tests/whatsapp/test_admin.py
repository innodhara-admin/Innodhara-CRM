"""Task 10: the admin's WhatsApp controls."""
from __future__ import annotations

import uuid

import httpx
import pytest

from tests.conftest import auth, create_org, login

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/admin/integrations/whatsapp"


async def _org(client, super_token):
    tag = uuid.uuid4().hex[:8]
    org = await create_org(client, super_token, name=f"WA Admin {tag}", slug=f"wa-admin-{tag}",
                           domain=f"wa-admin-{tag}.example.com")
    return org, auth(org["admin_token"])


async def _settings(client, headers):
    resp = await client.get("/api/v1/admin/settings", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_the_old_meta_body_still_works(client, super_token):
    _, h = await _org(client, super_token)
    resp = await client.put(BASE, headers=h, json={"access_token": "tok-test",
                                                    "phone_number_id": "555"})
    assert resp.status_code == 200, resp.text
    s = await _settings(client, h)
    assert s["whatsapp_provider"] == "meta" and s["whatsapp_credentials_stored"]


async def test_wati_is_stored_and_never_shown(client, super_token):
    _, h = await _org(client, super_token)
    resp = await client.put(BASE, headers=h, json={
        "provider": "wati", "wati_token": "tok-test", "wati_channel": "917975779676"})
    assert resp.status_code == 200, resp.text
    assert "tok-test" not in resp.text
    s = await _settings(client, h)
    assert s["whatsapp_provider"] == "wati" and s["whatsapp_credentials_stored"]
    assert s["whatsapp_webhook_path"].startswith("/api/v1/webhooks/wati/")
    assert s["whatsapp_country_code"] == "91"
    assert "tok-test" not in str(s)

    again = await client.put(BASE, headers=h, json={"provider": "wati", "wati_token": ""})
    assert again.status_code == 200
    s2 = await _settings(client, h)
    assert s2["whatsapp_credentials_stored"], "a blank token must keep the stored one"
    assert s2["whatsapp_webhook_path"] == s["whatsapp_webhook_path"], "the secret must not change"


async def test_staff_updates_round_trip(client, super_token):
    _, h = await _org(client, super_token)
    resp = await client.patch(BASE + "/staff-updates", headers=h,
                              json={"enabled": True, "kinds_off": ["escalation", "daily_brief"]})
    assert resp.status_code == 200, resp.text
    s = await _settings(client, h)
    assert s["whatsapp_staff_updates"] is True
    assert s["whatsapp_kinds_off"] == ["daily_brief", "escalation"]
    assert "task_assigned" in s["whatsapp_notification_kinds"]
    assert "daily_brief" in s["whatsapp_notification_kinds"]
    bad = await client.patch(BASE + "/staff-updates", headers=h,
                             json={"enabled": True, "kinds_off": ["no_such_kind"]})
    assert bad.status_code == 422


async def test_a_test_message_in_dry_run(client, super_token):
    _, h = await _org(client, super_token)
    off = await client.post(BASE + "/test", headers=h, json={"to": "9310524629"})
    assert off.status_code == 422, "no provider chosen yet"
    await client.put(BASE, headers=h, json={"provider": "wati", "wati_token": "tok-test"})
    resp = await client.post(BASE + "/test", headers=h, json={"to": "9310524629"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] and body["dry_run"] and body["to"] == "919310524629"
    bad = await client.post(BASE + "/test", headers=h, json={"to": "123"})
    assert bad.status_code == 422


async def test_templates_check(client, super_token, fake_http):
    _, h = await _org(client, super_token)
    await client.put(BASE, headers=h, json={"provider": "wati", "wati_token": "tok-test"})
    fake_http(lambda r: httpx.Response(200, json={"messageTemplates": [
        {"elementName": "test_message", "status": "APPROVED",
         "body": "Hi {{name}}, this is a test message from the CRM."},
        {"elementName": "staff_update", "status": "PENDING",
         "body": "Hi {{name}}, {{title}}"}]}))
    resp = await client.get(BASE + "/templates", headers=h)
    assert resp.status_code == 200, resp.text
    rows = {r["name"]: r for r in resp.json()["templates"]}
    assert len(rows) == 6 and resp.json()["checked"] is True
    assert rows["test_message"]["found"] and rows["test_message"]["status"] == "APPROVED"
    assert rows["test_message"]["values_match"] is True
    assert rows["staff_update"]["values_match"] is False
    assert rows["client_proposal"]["found"] is False
    assert rows["client_proposal"]["document"] is True


async def test_a_sales_agent_cannot_touch_it(client, super_token):
    org, h = await _org(client, super_token)
    made = await client.post("/api/v1/admin/users", headers=h, json={
        "email": f"agent@{org['admin_email'].split('@')[1]}", "name": "Agent A",
        "role": "sales_agent"})
    assert made.status_code == 200, made.text
    token = (await login(client, f"agent@{org['admin_email'].split('@')[1]}",
                         made.json()["temp_password"]))["access_token"]
    ah = auth(token)
    assert (await client.put(BASE, headers=ah, json={"provider": "off"})).status_code == 403
    assert (await client.post(BASE + "/test", headers=ah, json={"to": "9310524629"})).status_code == 403
    assert (await client.get(BASE + "/templates", headers=ah)).status_code == 403
