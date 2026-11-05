"""An organisation's WhatsApp settings, read from `org_settings.whatsapp_integration`.

Wati beside Meta (4 Nov 2026, docs/superpowers/specs/2026-11-04-whatsapp-wati-design.md).
Everything lives in the one JSON blob the Meta integration already used, so no
column is added. Secrets inside it are Fernet-encrypted (`*_enc`) and are only
ever decrypted here.

A row written before the provider switch existed ({"access_token_enc",
"phone_number_id"}) is a Meta row, and the platform-level .env Meta values still
apply when an organisation stored nothing, exactly as `resolve_credentials` did.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.crypto import decrypt_secret

PROVIDERS = ("off", "meta", "wati")
DEFAULT_WATI_HOST = "https://live-mt-server.wati.io"


@dataclass(frozen=True)
class WhatsAppConfig:
    provider: str
    wati_host: str
    wati_token: str | None
    wati_channel: str | None
    meta_token: str | None
    meta_phone_number_id: str | None
    country_code: str
    language: str
    staff_updates: bool
    kinds_off: frozenset[str]
    webhook_secret: str | None

    def ready(self) -> bool:
        """A provider is chosen and its credentials are there."""
        if self.provider == "wati":
            return bool(self.wati_token and self.wati_host)
        if self.provider == "meta":
            return bool(self.meta_token and self.meta_phone_number_id)
        return False


def _secret(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    return (decrypt_secret(value) or None) if value else None


def load(raw: dict[str, Any] | None) -> WhatsAppConfig:
    raw = raw or {}
    env = get_settings()
    meta_token = _secret(raw, "access_token_enc")
    meta_number = raw.get("phone_number_id") or None
    if not (meta_token and meta_number) and env.whatsapp_access_token \
            and env.whatsapp_phone_number_id:
        meta_token, meta_number = env.whatsapp_access_token, env.whatsapp_phone_number_id
    provider = raw.get("provider")
    if provider not in PROVIDERS:
        provider = "meta" if (meta_token and meta_number) else "off"
    return WhatsAppConfig(
        provider=provider,
        wati_host=(raw.get("wati_host") or DEFAULT_WATI_HOST).rstrip("/"),
        wati_token=_secret(raw, "wati_token_enc"),
        wati_channel=raw.get("wati_channel") or None,
        meta_token=meta_token,
        meta_phone_number_id=meta_number,
        country_code=str(raw.get("country_code") or "91"),
        language=raw.get("language") or "en",
        staff_updates=bool(raw.get("staff_updates", False)),
        kinds_off=frozenset(raw.get("kinds_off") or ()),
        webhook_secret=raw.get("webhook_secret") or None,
    )


async def for_org(db: AsyncSession, org_id: str) -> WhatsAppConfig:
    from app.models.organisation import OrgSettings

    raw = (
        await db.execute(
            select(OrgSettings.whatsapp_integration).where(OrgSettings.org_id == org_id)
        )
    ).scalar_one_or_none()
    return load(raw)
