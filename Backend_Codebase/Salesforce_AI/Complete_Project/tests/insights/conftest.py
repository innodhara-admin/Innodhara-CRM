"""A database session for the sales head tests, on the suite's own temp
database. Depends on `client` only so the tables exist (`init_db`)."""
from __future__ import annotations

import pytest

from app.database import SessionLocal


@pytest.fixture
async def db(client):
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
def _no_openrouter_balance_call(monkeypatch):
    """The suite reads the live .env, whose OpenRouter key is real. The AI
    usage screen asks OpenRouter for the key's balance, so every test here
    sees "no provider" unless it scripts the call itself, and starts with an
    empty balance cache."""
    from app.insights import ai_usage

    monkeypatch.setattr(ai_usage, "_provider", lambda: ("none", ""))
    ai_usage._balance_cache.clear()
