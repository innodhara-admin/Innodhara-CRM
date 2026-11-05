"""FCM push delivery (mobile G1) — dormant until a Firebase service-account
key is configured.

Uses the FCM HTTP v1 API directly: an OAuth2 access token is minted from the
service-account key (RS256-signed JWT grant — no google-auth dependency; the
`cryptography` package already ships with the platform for Fernet secrets).

Config: FCM_SERVICE_ACCOUNT_JSON=<path to the Firebase service-account .json>
in .env. Absent/blank ⇒ `enabled()` is False and every push call is a silent
no-op — the in-app notification row is always the source of truth; push is
only the doorbell.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select

from app.config import get_settings

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0, "creds": None}


def enabled() -> bool:
    path = get_settings().fcm_service_account_json
    return bool(path) and Path(path).exists()


def _b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _load_creds() -> dict[str, Any]:
    if _cache["creds"] is None:
        _cache["creds"] = json.loads(
            Path(get_settings().fcm_service_account_json).read_text(encoding="utf-8")
        )
    return _cache["creds"]


async def _access_token() -> str:
    now = time.time()
    if _cache["access_token"] and now < _cache["expires_at"] - 120:
        return _cache["access_token"]
    creds = _load_creds()

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64url(json.dumps({
        "iss": creds["client_email"],
        "scope": _SCOPE,
        "aud": _TOKEN_URL,
        "iat": int(now),
        "exp": int(now) + 3600,
    }).encode())
    signing_input = header + b"." + claims
    key = serialization.load_pem_private_key(creds["private_key"].encode(), password=None)
    signature = _b64url(key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256()))
    assertion = (signing_input + b"." + signature).decode()

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(_TOKEN_URL, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        })
    resp.raise_for_status()
    payload = resp.json()
    _cache["access_token"] = payload["access_token"]
    _cache["expires_at"] = now + int(payload.get("expires_in", 3600))
    return _cache["access_token"]


async def _send_one(client: httpx.AsyncClient, token: str, fcm_token: str,
                    *, title: str, body: str | None, data: dict[str, str]) -> bool:
    """Returns False when the token is dead and should be pruned."""
    project_id = _load_creds()["project_id"]
    resp = await client.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": {
            "token": fcm_token,
            "notification": {"title": title[:200], "body": (body or "")[:400]},
            "data": data,
            "android": {"priority": "high"},
        }},
    )
    if resp.status_code in (400, 404):
        detail = resp.text
        if "UNREGISTERED" in detail or "INVALID_ARGUMENT" in detail and "token" in detail:
            return False
    elif resp.status_code >= 400:
        logger.warning("FCM send failed (%s): %s", resp.status_code, resp.text[:200])
    return True


async def push_to_user(
    *, org_id: str, user_id: str, title: str, body: str | None,
    kind: str, entity_type: str | None, entity_id: str | None,
) -> None:
    """Fan a notification out to every registered device of one user.
    Runs in its own session/task — a push failure never touches the
    transaction that created the notification row."""
    if not enabled():
        return
    from app.database import SessionLocal
    from app.models.user import DeviceToken

    try:
        async with SessionLocal() as db:
            tokens = (
                await db.execute(
                    select(DeviceToken).where(DeviceToken.user_id == user_id)
                )
            ).scalars().all()
            if not tokens:
                return
            access = await _access_token()
            data = {k: v for k, v in {
                "kind": kind, "entity_type": entity_type or "",
                "entity_id": entity_id or "", "org_id": org_id,
            }.items()}
            dead: list[str] = []
            async with httpx.AsyncClient(timeout=30) as client:
                for t in tokens:
                    alive = await _send_one(
                        client, access, t.fcm_token,
                        title=title, body=body, data=data,
                    )
                    if not alive:
                        dead.append(t.id)
            if dead:
                await db.execute(delete(DeviceToken).where(DeviceToken.id.in_(dead)))
                await db.commit()
    except Exception:  # noqa: BLE001 — push is best-effort by design
        logger.exception("FCM push_to_user failed (user %s)", user_id)


def push_soon(**kwargs: Any) -> None:
    """Fire-and-forget from inside request handlers/engines. No-op when FCM
    is not configured. (A rolled-back enclosing transaction could in theory
    produce one spurious push; the in-app feed stays the source of truth.)"""
    if not enabled():
        return
    try:
        asyncio.get_running_loop().create_task(push_to_user(**kwargs))
    except RuntimeError:  # no running loop (sync scripts) — skip quietly
        pass
