"""Live verification of the Phase 6 (Inbox) contract against the real model.

The screens this backs are the message centre, the delivery trace, inbound
triage and the reply route — and the reply route is how FINDING **F27** is
closed: a question the AI escalates now has somewhere to be answered.

  1. A stranger writes in           → lands in triage (X1), nothing dropped.
  2. The triage row carries the AI's own reading — intent, matched ids — so a
     human sees the guess they are about to overwrite.
  3. A human resolves it: attaches the contact, corrects the intent, attaches
     the project. An invented intent is refused rather than stored.
  4. A known contact asks something the AI cannot answer → needs_human, and
     the reply route drafts an answer through the email agent that lands
     pending approval and really "sends" (dry-run .eml in the org outbox).
  5. The message centre can tell whose message each row is, and the delivery
     trace has the full event trail.

Run:  python scripts/verify_live_inbox.py     (real model key from .env)

Self-contained: builds its own database, sends no real mail, creates no
calendar events. Note the DATABASE_URL below — every model call writes an
`llm_usage` row, so a script without one silently writes to the LIVE db.
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

DB_PATH = PROJECT_ROOT / "data" / "verify_inbox.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}"
          + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


class Api:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}

    async def login(self, email: str) -> str:
        if email not in self.tokens:
            r = await self.client.post(
                "/auth/login", json={"email": email, "password": PASSWORD}
            )
            r.raise_for_status()
            self.tokens[email] = r.json()["access_token"]
        return self.tokens[email]

    async def call(self, method: str, path: str, *, user: str,
                   json: dict | None = None, expect: int | None = None):
        token = await self.login(user)
        r = await self.client.request(
            method, path, json=json, headers={"Authorization": f"Bearer {token}"}
        )
        if expect is not None:
            if r.status_code != expect:
                raise AssertionError(
                    f"{method} {path} → {r.status_code}, expected {expect}: {r.text[:300]}"
                )
            return r
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "This verification needs a real model provider in .env"
    print(f"LIVE inbox run — provider={s.llm_provider}\n")

    from app.database import init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app
    from scripts.seed_workflows import seed

    await init_db()
    register_handlers()
    sync_engine.register()
    await seed()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1",
                               timeout=300)
    api = Api(client)

    rahul, akash = "rahul@yuvipep.com", "akash@yuvipep.com"

    # ── 1. A stranger writes in ──────────────────────────────────────────────
    print("1. A stranger writes in — triage, nothing dropped (X1)")
    stranger = await api.call("POST", "/inbound/ingest", user=rahul, json={
        "channel": "email",
        "from_address": "nobody@we-never-heard-of-them.example",
        "subject": "Enquiry",
        "body": "We heard about your programmes. Could someone call us this week?",
    })
    check("an unmatched sender goes to triage", stranger["status"] == "triage",
          stranger["status"])

    queue = await api.call("GET", "/inbound/triage", user=akash)
    row = next((m for m in queue if m["id"] == stranger["id"]), None)
    check("a human can see it in the queue", row is not None)

    # ── 2. The row carries the AI's reading ──────────────────────────────────
    print("\n2. The triage row shows what the AI thought")
    missing = [k for k in ("intent", "change_type", "matched_lead_id",
                           "matched_project_id", "created_at")
               if row is None or k not in row]
    check("the row carries intent + matched ids + created_at (Phase 6)",
          not missing, f"missing {missing}")
    old_keys = [k for k in ("id", "channel", "from_address", "subject", "body",
                            "status", "reason", "summary")
                if row is None or k not in row]
    check("and every pre-Phase-6 key is still there", not old_keys,
          f"missing {old_keys}")

    # ── 3. A human resolves it ───────────────────────────────────────────────
    print("\n3. A human sorts it out")
    leads = await api.call("GET", "/leads", user=rahul)
    lead = leads[0]
    detail = await api.call("GET", f"/leads/{lead['id']}", user=rahul)
    contact = detail["contacts"][0]
    projects = await api.call("GET", "/projects", user=rahul)

    bad = await api.call(
        "POST", f"/inbound/{stranger['id']}/resolve", user=akash,
        json={"intent": "call_me_back", "mark_processed": False}, expect=422,
    )
    check("an invented intent is refused, not stored",
          "call_me_back" in bad.text)

    resolve_body: dict = {
        "contact_id": contact["id"], "intent": "scheduling", "mark_processed": False,
    }
    if projects:
        resolve_body["project_id"] = projects[0]["id"]
    await api.call("POST", f"/inbound/{stranger['id']}/resolve",
                   user=akash, json=resolve_body)

    queue = await api.call("GET", "/inbound/triage", user=akash)
    row = next((m for m in queue if m["id"] == stranger["id"]), None)
    check("the human's intent stuck", row is not None and row["intent"] == "scheduling",
          str(row and row["intent"]))
    check("the message now names its client",
          row is not None and row["matched_lead_id"] == lead["id"],
          str(row and row["matched_lead_id"]))
    if projects:
        check("and its project", row is not None
              and row["matched_project_id"] == projects[0]["id"])

    await api.call("POST", f"/inbound/{stranger['id']}/resolve",
                   user=akash, json={"mark_processed": True})
    queue = await api.call("GET", "/inbound/triage", user=akash)
    check("a processed message leaves the queue",
          not [m for m in queue if m["id"] == stranger["id"]])

    # ── 4. F27: an escalated question gets answered ──────────────────────────
    print("\n4. F27 — a question the AI cannot answer, answered by a human")
    question = await api.call("POST", "/inbound/ingest", user=rahul, json={
        "channel": "email",
        "from_address": contact["email"],
        "subject": "One more thing",
        "body": "What is the exact refund policy if we cancel midway, and who "
                "signs off on it at your end?",
    })
    escalated = question["status"] in ("needs_human", "triage")
    check("the AI escalates rather than guessing", escalated,
          f"status={question['status']}, intent={question['intent']}")

    # The reply route: the app opens the assistant scoped to this client. The
    # email agent drafts; nothing leaves without a human tap.
    reply = await api.call("POST", "/assistant/command", user=rahul, json={
        "text": f"Write a short email to {contact['name']} at {lead['name']} "
                "replying to their question about our refund policy — say a "
                "written policy is on its way and offer a call this week.",
        "lead_id": lead["id"],
    })
    pending = reply.get("pending_approvals") or []
    check("the reply route produced a draft waiting for approval",
          bool(pending), f"agent={reply.get('agent')}, reply={reply.get('reply', '')[:200]}")

    if pending:
        message_id = pending[0]["message_id"]
        await api.call("POST", f"/messages/{message_id}/approve", user=rahul)

        from app.core.constants import MessageStatus
        from app.database import SessionLocal
        from app.models.messaging import OutboundMessage
        from app.services.message_service import execute_send
        from sqlalchemy import select

        async with SessionLocal() as db:
            queued = (await db.execute(select(OutboundMessage).where(
                OutboundMessage.id == message_id
            ))).scalars().all()
            for m in queued:
                await execute_send(db, m)
            await db.commit()

        trace = await api.call("GET", f"/messages/{message_id}", user=rahul)
        events = [e["event"] for e in trace.get("delivery_log", [])]
        check("the delivery trace has the full trail",
              "drafted" in events and "queued" in events and "sent" in events,
              str(events))
        check("the message centre can tell whose message it is",
              bool(trace.get("sender_user_id")), str(trace.get("sender_user_id")))
        sent_event = next(
            (e for e in trace["delivery_log"] if e["event"] == "sent"), None
        )
        check("the .eml the trace links to really exists",
              sent_event is not None
              and str(sent_event.get("detail", "")).startswith("dry_run:")
              and (s.storage_path / str(sent_event["detail"])[len("dry_run:"):]).exists(),
              str(sent_event and sent_event.get("detail")))
        check("F27 closed: escalated question → reply → approved → sent",
              trace["status"] in (MessageStatus.SENT.value,
                                  MessageStatus.DELIVERED.value),
              trace["status"])

    # ── 5. The message centre list ───────────────────────────────────────────
    print("\n5. The message centre")
    listed = await api.call("GET", "/messages?status=all&limit=200", user=rahul)
    check("the list returns messages", bool(listed), f"{len(listed)} rows")
    check("every row names its sender",
          all("sender_user_id" in m for m in listed))
    check("and every row carries its status trail chip's value",
          all(m.get("status") for m in listed))

    await client.aclose()

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    for desc, ok, detail in CHECKS:
        if not ok:
            print(f"FAILED: {desc}  {detail}")
    print(f"{passed}/{len(CHECKS)} checks passed")
    sys.exit(0 if passed == len(CHECKS) else 1)


async def _run() -> None:
    # aiosqlite's threads are non-daemon: without this the process never exits
    # on failure and locks its own database file (handoff §6g).
    try:
        await main()
    finally:
        from app.database import engine

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
