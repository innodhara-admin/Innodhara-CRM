"""Signed, expiring links to one document (4 Nov 2026).

A WhatsApp provider fetches a template's PDF header from a URL, without our
login. The link names exactly one thing and stops working after `ttl_seconds`
(7 days by default): `{"k": "file", "o": org, "p": path, "n": filename}` or
`{"k": "transcript", "o": org, "m": meeting}`. The signature is an HMAC over
the payload with SECRET_KEY, so a link cannot be edited to name another file.
The route that serves it (app/api/public_files.py) still checks the path
against the organisation's own folder.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.config import get_settings

DEFAULT_TTL_SECONDS = 7 * 86400
ROUTE = "/api/v1/public/wa/"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    key = get_settings().secret_key.encode("utf-8")
    return _b64(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())


def make(payload: dict[str, Any], *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    data = dict(payload, exp=int(time.time()) + ttl_seconds)
    body = _b64(json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def read(token: str) -> dict[str, Any] | None:
    """The payload, or None when the token is malformed, altered or expired."""
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        data = json.loads(_unb64(body))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    return data


def public_url(token: str) -> str | None:
    base = get_settings().public_base_url.strip().rstrip("/")
    return f"{base}{ROUTE}{token}" if base else None
