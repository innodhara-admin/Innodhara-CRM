"""Fixtures for the WhatsApp tests (Wati beside Meta, 4 Nov 2026).

A session on the suite's own temp database, and a fake HTTP server: the
providers build their `httpx.AsyncClient` normally and the fake answers. No
test here reaches Wati, Meta or a model."""
from __future__ import annotations

import httpx
import pytest

from app.database import SessionLocal


@pytest.fixture
async def db(client):
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture
def fake_http(monkeypatch):
    """`fake_http(handler)` routes every httpx.AsyncClient through `handler`
    and returns the list of requests it saw."""
    real = httpx.AsyncClient

    def install(handler):
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def make(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(record)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", make)
        return seen

    return install


@pytest.fixture
def sending_for_real(monkeypatch):
    """WHATSAPP_MODE=cloud_api for one test (the suite runs in dry_run)."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "whatsapp_mode", "cloud_api")
