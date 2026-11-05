"""The API must not report a setup step as done when it will silently fail.

Manual p.7: "otherwise approved messages are written to a file and everyone
believes they were sent."  conftest pins EMAIL_MODE=dry_run.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def test_settings_expose_the_process_wide_modes(client, org_a):
    resp = await client.get(
        "/api/v1/admin/settings", headers=auth(org_a["admin_token"])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_mode"] == "dry_run"
    assert body["calendar_mode"] == "off"
    assert body["inbound_email_mode"] == "off"
    assert "whatsapp_mode" in body


async def test_email_configured_is_false_while_mode_is_dry_run(client, org_a):
    stored = await client.put(
        "/api/v1/admin/integrations/email",
        headers=auth(org_a["admin_token"]),
        json={"smtp_username": "sales@alpha-example.com",
              "smtp_app_password": "abcd efgh ijkl mnop"},
    )
    assert stored.status_code == 200, stored.text

    resp = await client.get(
        "/api/v1/admin/settings", headers=auth(org_a["admin_token"])
    )
    body = resp.json()
    assert body["email_credentials_stored"] is True
    assert body["email_integration_configured"] is False, (
        "credentials are stored but EMAIL_MODE=dry_run, so no mail will leave"
    )
