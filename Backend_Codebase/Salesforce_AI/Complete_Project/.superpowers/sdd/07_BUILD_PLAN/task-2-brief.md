### Task 2: Honest delivery mode *(change #2)*

**Files:**
- Modify: `app/api/admin.py` — `_settings_response`
- Test: `tests/test_dashboard_settings_honesty.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/v1/admin/settings` gains `email_mode`, `whatsapp_mode`, `calendar_mode`, `inbound_email_mode` (all `str`, read-only). The three `*_configured` booleans change meaning to *credentials AND mode*.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_settings_honesty.py
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
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_settings_honesty.py -v`
Expected: FAIL — `KeyError: 'email_mode'`, and `email_integration_configured` is `True`.

- [ ] **Step 3: Rewrite `_settings_response`'s tail**

In `app/api/admin.py`, replace the last three keys of `_settings_response` with:

```python
        # ── Delivery honesty (D5) ────────────────────────────────────────────
        # Two halves are required for anything to leave: stored credentials AND
        # a process-wide mode. email_service returns a "dry_run:<path>" file
        # unless email_mode == "smtp" AND creds is not None. Reporting only the
        # first half is how "everyone believes they were sent" happens.
        "email_mode": _cfg.email_mode,
        "whatsapp_mode": _cfg.whatsapp_mode,
        "calendar_mode": _cfg.calendar_mode,
        "inbound_email_mode": _cfg.inbound_email_mode,
        "email_credentials_stored": _email_creds,
        "whatsapp_credentials_stored": _whatsapp_creds,
        "calendar_credentials_stored": _calendar_creds,
        "email_integration_configured": _email_creds and _cfg.email_mode == "smtp",
        "whatsapp_integration_configured": (
            _whatsapp_creds and _cfg.whatsapp_mode == "cloud_api"
        ),
        "calendar_integration_configured": (
            _calendar_creds and _cfg.calendar_mode == "google"
        ),
    }
```

and open the function body with the three locals it now needs:

```python
def _settings_response(s: OrgSettings) -> dict[str, Any]:
    _cfg = get_settings()
    _email_creds = bool((s.email_integration or {}).get("smtp_username"))
    _whatsapp_creds = bool((s.whatsapp_integration or {}).get("phone_number_id"))
    _calendar_creds = bool((s.calendar_integration or {}).get("calendar_id"))
    return {
```

Add the config import beside the existing ones:

```python
from app.config import get_settings
```

> `*_credentials_stored` is kept as a separate key deliberately. Without it the
> console could not distinguish "no credentials" from "server is in dry-run" —
> that is Q3 option (c), which was rejected for exactly this reason.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_settings_honesty.py -v`
Expected: 2 passed.

- [ ] **Step 5: Confirm no existing test asserted the old meaning**

Run: `python -m pytest -q`
Expected: full suite passes. If anything fails on
`email_integration_configured`, it was asserting the misleading behaviour —
update that assertion, and note it in `09_BACKEND_CHANGES.md`.

- [ ] **Step 6: Checkpoint**

Both green. Mark change #2 done in `09_BACKEND_CHANGES.md`.

---

