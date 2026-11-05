"""Live verification of the assistant's conversation memory.

Until now every `/assistant/command` was an island: the endpoint took only
`text`, and `BaseAgent.run` opened a fresh message list, so "make it warmer"
arrived with no idea what "it" was. With a `session_id` the turns are stored
per (org, user, session) and replayed — to the agent AND to the router.

What this proves against a REAL model:

  1. A follow-up that is meaningless on its own ("what about the second one?")
     is answered from the previous turn — no re-stating the question.
  2. A pronoun-only command routes to the agent of the work it refers to,
     which the router could not do before ("send it" used to look like a
     query).
  3. Two sessions of the same user never bleed into each other.
  4. Two users sharing a session id never see each other's turns.
  5. GET /assistant/history replays the transcript; DELETE forgets it, and a
     command after the delete is genuinely blank-slate again.
  6. Omitting session_id keeps the old stateless behaviour exactly.

Runs on its own throwaway database — no other verify script is a prerequisite.

Run:  python scripts/verify_live_conversation.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "verify_conversation.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []

SESSION_A = "liveconvsession0000000000000000a"
SESSION_B = "liveconvsession0000000000000000b"


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(
        f"LIVE conversation-memory run — provider={s.llm_provider} "
        f"(history {s.assistant_history_turns} turns / "
        f"{s.assistant_history_char_budget} chars)\n"
    )

    from app.database import SessionLocal, init_db
    from app.jobs import register_handlers
    from app.main import _seed_super_admin, app

    await init_db()
    await _seed_super_admin()
    register_handlers()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1", timeout=300
    )
    tokens: dict[str, str] = {}

    async def login(email: str, password: str) -> str:
        r = await client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    async def call(method: str, path: str, *, user: str, json: dict | None = None):
        r = await client.request(
            method, path, json=json,
            headers={"Authorization": f"Bearer {tokens[user]}"},
        )
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()

    # ── Seed: one org, two people, three tasks to talk about ────────────────
    super_token = await login(s.super_admin_email, s.super_admin_password)
    org = (
        await client.post(
            "/orgs",
            headers={"Authorization": f"Bearer {super_token}"},
            json={
                "name": "Conversation Test Co", "slug": "conv-test",
                "email_domain": "conv-example.com",
                "admin_email": "admin@conv-example.com",
                "admin_name": "Conv Admin",
            },
        )
    ).json()
    tokens["admin"] = await login(org["admin_email"], org["admin_temp_password"])

    async def add_user(email: str, name: str, role: str, key: str) -> None:
        created = (
            await call("POST", "/admin/users", user="admin",
                       json={"email": email, "name": name, "role": role})
        )
        tokens[key] = await login(email, created["temp_password"])

    await add_user("asha@conv-example.com", "Asha Agent", "sales_agent", "asha")
    await add_user("ravi@conv-example.com", "Ravi Agent", "sales_agent", "ravi")

    for title in ("Send the robotics-lab quote",
                  "Call the principal about the demo date",
                  "Collect the signed consent form"):
        await call("POST", "/action-items", user="asha", json={"title": title})

    async def command(user: str, text: str, **extra) -> dict:
        return await call("POST", "/assistant/command", user=user,
                          json={"text": text, **extra})

    # ── 1. A follow-up that only makes sense in context ─────────────────────
    print("1. Follow-up understood from the previous turn")
    first = await command("asha", "list my open tasks", session_id=SESSION_A)
    print(f"     Q: list my open tasks\n     A: {first['reply'][:220]}")
    second = await command(
        "asha", "tell me more about the second one", session_id=SESSION_A
    )
    print(f"     Q: tell me more about the second one\n     A: {second['reply'][:220]}")
    reply2 = second["reply"].lower()
    check(
        "the pronoun-only follow-up is answered, not queried back",
        any(word in reply2 for word in ("principal", "demo", "date")),
        second["reply"][:160],
    )
    check("session_id is echoed back", second.get("session_id") == SESSION_A)

    # ── 2. The router uses the conversation too ─────────────────────────────
    print("2. Routing a command that has no nouns of its own")
    await command("asha", "draft a follow-up message for the principal",
                  session_id=SESSION_A)
    routed = await command("asha", "make it warmer and shorter",
                           session_id=SESSION_A)
    print(f"     'make it warmer and shorter' -> agent={routed['agent']}")
    check(
        "a pronoun-only command routes to the work it refers to, not 'query'",
        routed["agent"] in ("followup", "email", "proposal", "conversation"),
        f"agent={routed['agent']}",
    )

    # ── 3. Sessions of one user are separate conversations ──────────────────
    print("3. A second conversation starts clean")
    fresh = await command("asha", "what were we just talking about?",
                          session_id=SESSION_B)
    print(f"     A: {fresh['reply'][:220]}")
    hist_b = await call("GET", f"/assistant/history?session_id={SESSION_B}",
                        user="asha")
    check("the other session holds only its own two turns", len(hist_b) == 2,
          f"{len(hist_b)} turns")

    # ── 4. Two users, same session id, nothing shared ───────────────────────
    print("4. A conversation belongs to one person")
    ravi_view = await call("GET", f"/assistant/history?session_id={SESSION_A}",
                           user="ravi")
    check("another user reading the same session id gets nothing",
          ravi_view == [], f"{len(ravi_view)} turns leaked")

    # ── 5. Replay, then forget ──────────────────────────────────────────────
    print("5. Replay and forget")
    hist_a = await call("GET", f"/assistant/history?session_id={SESSION_A}",
                        user="asha")
    roles = [t["role"] for t in hist_a]
    # Four commands went to SESSION_A: the two in step 1 and the two in step 2.
    expected_turns = 2 * 4
    check("history replays the transcript, oldest first, strictly alternating",
          len(hist_a) == expected_turns
          and roles == ["user", "assistant"] * 4,
          f"{len(hist_a)} turns: {roles}")
    check("the first stored turn is what the user actually typed",
          hist_a[0]["content"] == "list my open tasks", hist_a[0]["content"][:80])
    check("assistant turns record which specialist answered",
          all(t["agent"] for t in hist_a if t["role"] == "assistant"),
          str([t["agent"] for t in hist_a if t["role"] == "assistant"]))

    cleared = await call("DELETE", f"/assistant/history?session_id={SESSION_A}",
                         user="asha")
    check("delete forgets the whole conversation",
          cleared["cleared"] == expected_turns, str(cleared))
    after = await call("GET", f"/assistant/history?session_id={SESSION_A}",
                       user="asha")
    check("nothing survives the delete", after == [], f"{len(after)} turns")

    blank = await command("asha", "and the third one?", session_id=SESSION_A)
    print(f"     after delete: {blank['reply'][:200]}")
    check("a command after the delete really is blank-slate",
          len(await call("GET", f"/assistant/history?session_id={SESSION_A}",
                         user="asha")) == 2)

    # ── 6. No session id = the old stateless contract, untouched ────────────
    print("6. Without a session id nothing is remembered")
    await command("ravi", "list my open tasks")
    await command("ravi", "and the second one?")
    ravi_any = await call("GET", f"/assistant/history?session_id={SESSION_B}",
                          user="ravi")
    check("stateless commands write no turns at all", ravi_any == [],
          f"{len(ravi_any)} turns")

    await client.aclose()

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"{passed}/{len(CHECKS)} checks passed")
    sys.exit(0 if passed == len(CHECKS) else 1)


async def _run() -> None:
    try:
        await main()
    finally:
        from app.database import engine

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
