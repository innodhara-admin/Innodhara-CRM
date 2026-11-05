"""The chat-history sidebar: GET /assistant/sessions lists a person's own
conversations, most recently used first (2 Oct 2026). Read only; opening one
is the existing GET /assistant/history.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth, login

pytestmark = pytest.mark.asyncio

FIRST = "sidebarsessionaaaaaaaaaaaaaaaa01"
SECOND = "sidebarsessionbbbbbbbbbbbbbbbb02"


@pytest.fixture(scope="module")
async def people(client, org_a):
    """Two people of their own, so other tests' chats never show up here."""
    out = {}
    for key in ("owner", "other"):
        email = f"sidebar.{key}@alpha-example.com"
        resp = await client.post(
            "/api/v1/admin/users", headers=auth(org_a["admin_token"]),
            json={"email": email, "name": f"Sidebar {key}", "role": "sales_agent"},
        )
        assert resp.status_code == 200, resp.text
        made = resp.json()
        session = await login(client, email, made["temp_password"])
        out[key] = {"id": made["id"], "token": session["access_token"],
                    "org_id": org_a["id"]}
    return out


async def _say(person: dict, session_id: str, user_text: str, reply: str) -> None:
    from app.ai import conversation
    from app.database import SessionLocal

    async with SessionLocal() as db:
        await conversation.save_exchange(
            db, org_id=person["org_id"], user_id=person["id"],
            session_id=session_id, user_text=user_text, reply=reply, agent="query",
        )
        await db.commit()


async def _list(client, person: dict, **params) -> list[dict]:
    resp = await client.get("/api/v1/assistant/sessions",
                            headers=auth(person["token"]), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_a_person_with_no_chats_gets_an_empty_list(client, people):
    assert await _list(client, people["other"]) == []


async def test_chats_are_listed_newest_first_with_title_and_preview(client, people):
    owner = people["owner"]
    await _say(owner, FIRST, "Show my open tasks", "You have 3 open tasks.")
    await _say(owner, SECOND, "Tell me   about\nAcme", "Acme is an active client.")
    await _say(owner, FIRST, "Which one is due first?", "The kit list, due Friday.")

    rows = await _list(client, owner)
    assert [r["session_id"] for r in rows] == [FIRST, SECOND]
    first = rows[0]
    # The title is the first thing the person said; the preview, the last
    # thing said by either side.
    assert first["title"] == "Show my open tasks"
    assert first["preview"] == "The kit list, due Friday."
    assert first["turns"] == 4
    # Flattened to one line for the sidebar.
    assert rows[1]["title"] == "Tell me about Acme"
    assert rows[1]["last_at"]


async def test_another_person_never_sees_these_chats(client, people):
    assert await _list(client, people["other"]) == []


async def test_a_long_title_is_cut_for_the_sidebar(client, people):
    owner = people["owner"]
    session = "sidebarsessionccccccccccccccccc03"
    await _say(owner, session, "word " * 60, "ok")
    row = next(r for r in await _list(client, owner) if r["session_id"] == session)
    assert len(row["title"]) <= 80
    assert row["title"].endswith("…")


async def test_the_limit_is_respected_and_bounded(client, people):
    owner = people["owner"]
    assert len(await _list(client, owner, limit=1)) == 1
    resp = await client.get("/api/v1/assistant/sessions",
                            headers=auth(owner["token"]), params={"limit": 0})
    assert resp.status_code == 422


async def test_a_deleted_chat_leaves_the_list(client, people):
    owner = people["owner"]
    resp = await client.delete("/api/v1/assistant/history",
                               headers=auth(owner["token"]),
                               params={"session_id": SECOND})
    assert resp.status_code == 200, resp.text
    ids = [r["session_id"] for r in await _list(client, owner)]
    assert SECOND not in ids
    assert FIRST in ids
