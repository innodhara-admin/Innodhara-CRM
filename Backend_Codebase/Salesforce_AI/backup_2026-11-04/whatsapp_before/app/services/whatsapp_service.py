"""WhatsApp sending via the Meta WhatsApp Business Cloud API, with dry-run.

Org-level credentials (org settings) win over platform-level .env values.
"""
from __future__ import annotations

import json

import httpx

from app.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import ExternalServiceError
from app.services import storage

_GRAPH_URL = "https://graph.facebook.com/v20.0"


def resolve_credentials(org_whatsapp_integration: dict | None) -> dict | None:
    settings = get_settings()
    integ = org_whatsapp_integration or {}
    if integ.get("access_token_enc") and integ.get("phone_number_id"):
        token = decrypt_secret(integ["access_token_enc"])
        if token:
            return {"access_token": token, "phone_number_id": integ["phone_number_id"]}
    if settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
        return {
            "access_token": settings.whatsapp_access_token,
            "phone_number_id": settings.whatsapp_phone_number_id,
        }
    return None


async def send_whatsapp(
    *, org_id: str, to_phone: str, body: str, creds: dict | None
) -> str:
    """Send (or dry-run) a WhatsApp text message. Returns provider message id."""
    settings = get_settings()
    if settings.whatsapp_mode != "cloud_api" or creds is None:
        rel = storage.save_text(
            org_id,
            storage.CATEGORY_OUTBOX,
            f"whatsapp_{to_phone}.json",
            json.dumps({"to": to_phone, "body": body}, indent=2, ensure_ascii=False),
        )
        return f"dry_run:{rel}"

    url = f"{_GRAPH_URL}/{creds['phone_number_id']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone.lstrip("+"),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {creds['access_token']}"},
            )
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"WhatsApp request failed: {exc}") from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ExternalServiceError(f"WhatsApp rate-limited/unavailable ({resp.status_code})")
    if resp.status_code >= 400:
        raise ExternalServiceError(f"WhatsApp send rejected: {resp.text[:500]}")
    data = resp.json()
    try:
        return data["messages"][0]["id"]
    except (KeyError, IndexError):
        return "whatsapp:unknown"
