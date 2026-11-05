"""Calendar integration.

The internal database calendar (Demos + FollowUps) is always the source of
truth and always works. When CALENDAR_MODE=google and a service-account JSON
is configured, events are mirrored to Google Calendar as well — failures are
logged, never blocking (graceful degradation).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/calendar"
_token_cache: dict[str, tuple[str, float]] = {}


def _load_service_account(credentials_file: str) -> dict | None:
    try:
        return json.loads(Path(credentials_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _make_jwt_assertion(sa: dict) -> str:
    import jwt  # PyJWT with cryptography handles RS256

    now = int(time.time())
    payload = {
        "iss": sa["client_email"],
        "scope": _SCOPE,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, sa["private_key"], algorithm="RS256")


async def _access_token(credentials_file: str) -> str | None:
    cached = _token_cache.get(credentials_file)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    sa = _load_service_account(credentials_file)
    if sa is None:
        return None
    try:
        assertion = _make_jwt_assertion(sa)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        _token_cache[credentials_file] = (token, time.time() + 3300)
        return token
    except Exception as exc:  # noqa: BLE001 — calendar is best-effort
        logger.warning("Google Calendar auth failed: %s", exc)
        return None


def _resolve_calendar_config(org_calendar_integration: dict | None) -> tuple[str, str] | None:
    settings = get_settings()
    integ = org_calendar_integration or {}
    creds_file = integ.get("credentials_file") or settings.google_calendar_credentials_file
    calendar_id = integ.get("calendar_id") or settings.google_calendar_id
    if settings.calendar_mode != "google" or not creds_file or not calendar_id:
        return None
    return creds_file, calendar_id


async def create_event(
    *,
    org_calendar_integration: dict | None,
    title: str,
    description: str,
    on_date: date,
    time_hhmm: str | None = None,
    duration_minutes: int = 60,
) -> str | None:
    """Mirror an event to Google Calendar. Returns event id or None."""
    config = _resolve_calendar_config(org_calendar_integration)
    if config is None:
        return None
    creds_file, calendar_id = config
    token = await _access_token(creds_file)
    if token is None:
        return None

    if time_hhmm:
        try:
            hour, minute = (int(x) for x in time_hhmm.split(":"))
        except ValueError:
            hour, minute = 10, 0
        start = datetime(on_date.year, on_date.month, on_date.day, hour, minute)
        end = start + timedelta(minutes=duration_minutes)
        body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Asia/Kolkata"},
        }
    else:
        body = {
            "summary": title,
            "description": description,
            "start": {"date": on_date.isoformat()},
            "end": {"date": (on_date + timedelta(days=1)).isoformat()},
        }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google Calendar event creation failed: %s", exc)
        return None


async def delete_event(
    *, org_calendar_integration: dict | None, event_id: str
) -> None:
    config = _resolve_calendar_config(org_calendar_integration)
    if config is None or not event_id:
        return
    creds_file, calendar_id = config
    token = await _access_token(creds_file)
    if token is None:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.delete(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google Calendar event deletion failed: %s", exc)
