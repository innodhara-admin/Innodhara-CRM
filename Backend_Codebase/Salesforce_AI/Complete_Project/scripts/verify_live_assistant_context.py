"""Live verification of the Jarvis context chip and task priority (findings
F17 + F19), against a REAL model.

Both findings are the same shape as F10: the app offers an affordance the
backend never honoured.

  F17 — the "About: <client>" chip sends a lead_id, but the query agent only
        dropped it into the system prompt as a hint. So "what are the action
        items?" with a lead selected returned EVERYTHING the caller owned. The
        fix binds the selected lead as the default client filter in code (the
        model may still name another client, or say "all" to broaden).

  F19 — the query agent's item view omitted `priority`, so "which are my most
        important tasks?" silently degraded to "soonest due". The fix adds the
        field so the model can actually see P1/P2/P3.

What this proves against a real model:

  1. No chip: "what are the action items?" spans both clients (the baseline
     the finding said was correct when nothing is selected).
  2. Chip on client A: the SAME question returns only client A's items — the
     tool result itself is scoped, not just the prose. This is the F17 fix.
  3. "all" still broadens back past the chip.
  4. The tool result now carries `priority`, and asked for the most important
     task the model names the P1 one even though it is due LAST — so it is
     reading priority, not the due date. This is the F19 fix.

Runs on its own throwaway database. Model calls only — no mail, no calendar.

Run:  python scripts/verify_live_assistant_context.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "verify_assistant_context.db"
# A dedicated throwaway DB — a verify script must never write llm_usage rows
# into the live salesplatform.db (the §6g lesson).
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

BOTH = {"Aurora Robotics", "Borealis Logistics"}

CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


def _tool_result(resp: dict, tool: str) -> list[dict]:
    """The list a tool returned, as recorded in `actions`.

    ⚠ **`actions[].result` is a PREVIEW, and it is lossy above 800 characters.**
    `agents/base.py::_preview` returns the object when its JSON fits and a
    TRUNCATED STRING when it does not — so the recorded type depends on how
    much the tool returned. A scoped query (2 items, 623 chars) is recorded as
    a list; the same query unscoped (3 items, 941 chars) is recorded as a
    string, and this function used to return `[]` for it.

    **That is the whole of F59.** Two checks were failing with "an EMPTY set",
    and FINDINGS recorded the hypothesis that the model had stopped emitting
    `client="all"`. Measured 2026-08-25 against the live model, it had not: the
    args were `{"owner": "me", "status": "open", "client": "all"}` in both
    cases, the tool returned every client's items, and the replies named both
    clients. The checks were reading a debug preview and calling its truncation
    an empty result. Nothing regressed in the product — the item payload simply
    grew past 800 characters as F19 and F45 added fields to `_item_dict`.
    """
    for action in resp.get("actions", []):
        if action.get("tool") == tool and action.get("ok") and isinstance(
            action.get("result"), list
        ):
            return action["result"]
    return []


def _clients_reached(resp: dict, tool: str, names: set[str]) -> tuple[bool, str]:
    """Whether the answer reached every client in `names`, and on what evidence.

    Prefers the tool result, because "the tool result itself is scoped, not just
    the prose" is what check 2 exists to prove. Falls back to the reply when the
    preview was truncated — the fallback is weaker evidence, so it is named in
    the detail rather than hidden."""
    rows = _tool_result(resp, tool)
    if rows:
        seen = {r.get("client") for r in rows}
        return names <= seen, f"tool result: {sorted(x for x in seen if x)}"
    reply = resp.get("reply", "")
    seen = {n for n in names if n.lower() in reply.lower()}
    return names <= seen, (
        f"reply (the tool preview was truncated past 800 chars): {sorted(seen)}"
    )


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE assistant-context run — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.jobs import register_handlers
    from app.main import _seed_super_admin, app
    from app.models.action_item import ActionItem
    from sqlalchemy import select

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

    # ── Seed: one org, one agent, two clients, tasks on each ────────────────
    super_token = await login(s.super_admin_email, s.super_admin_password)
    org = (
        await client.post(
            "/orgs",
            headers={"Authorization": f"Bearer {super_token}"},
            json={
                "name": "Context Test Co", "slug": "ctx-test",
                "email_domain": "ctx-example.com",
                "admin_email": "admin@ctx-example.com",
                "admin_name": "Ctx Admin",
            },
        )
    ).json()
    tokens["admin"] = await login(org["admin_email"], org["admin_temp_password"])
    created = await call("POST", "/admin/users", user="admin",
                         json={"email": "asha@ctx-example.com", "name": "Asha Agent",
                               "role": "sales_agent"})
    tokens["asha"] = await login("asha@ctx-example.com", created["temp_password"])

    async def make_lead(name: str) -> str:
        return (await call("POST", "/leads", user="asha", json={"name": name}))["id"]

    async def make_item(title: str, lead_id: str, due_in_days: int) -> str:
        due = (datetime.utcnow() + timedelta(days=due_in_days)).isoformat()
        return (await call("POST", "/action-items", user="asha",
                           json={"title": title, "lead_id": lead_id,
                                 "due_date": due}))["id"]

    aurora = await make_lead("Aurora Robotics")
    borealis = await make_lead("Borealis Logistics")
    # Distinctive title tokens so the prose is checkable too.
    aur_soon = await make_item("Share the pilot pricing sheet", aurora, due_in_days=2)
    aur_late = await make_item("Prepare the annual security review", aurora, due_in_days=30)
    await make_item("Confirm the warehouse walkthrough slot", borealis, due_in_days=3)

    # F19 fixture: the P1 is due LAST, so "soonest due" and "most important"
    # give different answers — the model must read `priority` to get it right.
    async with SessionLocal() as db:
        rows = {r.id: r for r in (await db.execute(
            select(ActionItem).where(ActionItem.org_id == org["id"])
        )).scalars().all()}
        rows[aur_late].priority = "P1"   # important but due in 30 days
        rows[aur_soon].priority = "P3"   # due in 2 days, low priority
        await db.commit()

    async def command(text: str, **extra) -> dict:
        return await call("POST", "/assistant/command", user="asha",
                          json={"text": text, "agent": "query", **extra})

    # ── 1. No chip: the answer spans both clients ───────────────────────────
    print("1. No chip — 'what are the action items?' spans every client")
    r1 = await command("what are the action items?")
    ok1, how1 = _clients_reached(r1, "list_action_items", BOTH)
    print(f"     {how1}")
    check("without a chip the query is unscoped (both clients present)", ok1, how1)

    # ── 2. Chip on Aurora: the SAME question scopes to Aurora ───────────────
    print("2. Chip on Aurora — the same question returns only Aurora")
    r2 = await command("what are the action items?", lead_id=aurora)
    items2 = _tool_result(r2, "list_action_items")
    clients2 = {i.get("client") for i in items2}
    print(f"     clients returned: {clients2}\n     reply: {r2['reply'][:200]}")
    check("the chip scopes the tool result to the selected client only (F17)",
          clients2 == {"Aurora Robotics"} and items2, str(clients2))
    check("the reply does not mention the other client's work",
          "walkthrough" not in r2["reply"].lower(), r2["reply"][:160])

    # ── 3. 'all' still broadens back past the chip ──────────────────────────
    print("3. Chip on Aurora but asking across all clients")
    r3 = await command("list the action items for every client, across all clients",
                       lead_id=aurora)
    ok3, how3 = _clients_reached(r3, "list_action_items", BOTH)
    print(f"     {how3}")
    check("an explicit 'all clients' request broadens past the chip", ok3, how3)

    # ── 4. Priority is visible, and it beats due date ───────────────────────
    print("4. 'Which is my most important task?' with Aurora selected")
    r4 = await command("which is my single most important task?", lead_id=aurora)
    items4 = _tool_result(r4, "list_action_items")
    print(f"     reply: {r4['reply'][:220]}")
    check("the tool result now carries a priority field for each item (F19)",
          bool(items4) and all("priority" in i for i in items4),
          str([i.get("priority") for i in items4]))
    reply4 = r4["reply"].lower()
    # The P1 ("security review") is due in 30 days; the P3 ("pricing sheet") in
    # 2 days. Naming the security review as most important proves the model is
    # reading priority, not just the nearest due date.
    check("the model names the P1 as most important, though it is due last",
          "security" in reply4 and "pricing" not in reply4, r4["reply"][:200])

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
