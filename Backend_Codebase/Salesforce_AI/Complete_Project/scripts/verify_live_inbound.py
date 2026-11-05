"""Live verification of two inbound workflows on the generic project
(continues the data of verify_generic_planner.py — run that first).

  W20 — scope grows: "train 10 teachers instead of 6"  → classified as a
        change_request, a new plan version with scope-expansion tasks rides
        through the approval gate, the school gets an acknowledgement draft.
  W22 — complaint: "engineer late, one printer dead"    → incident opened on
        the project, holding reply drafted for one-tap approval, then really
        "sent" (dry-run .eml written to the org outbox).

Run:  python scripts/verify_live_inbound.py     (real LLM key from .env)
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

DB_PATH = PROJECT_ROOT / "data" / "verify_generic.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


class Api:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}

    async def login(self, email: str) -> str:
        if email not in self.tokens:
            r = await self.client.post("/auth/login", json={"email": email, "password": PASSWORD})
            r.raise_for_status()
            self.tokens[email] = r.json()["access_token"]
        return self.tokens[email]

    async def call(self, method: str, path: str, *, user: str, json: dict | None = None):
        token = await self.login(user)
        r = await self.client.request(method, path, json=json,
                                      headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_generic_planner.py first (it builds the project)."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "This verification needs a real LLM provider in .env"
    print(f"LIVE inbound run — provider={s.llm_provider}\n")

    from app.database import init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app

    await init_db()
    register_handlers()
    sync_engine.register()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=300)
    api = Api(client)

    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.comms import InboundMessage
    from app.models.messaging import OutboundMessage
    from app.models.project import ActionPlan, Project
    from app.models.work import Incident

    ananya, akash = "ananya@yuvipep.com", "akash@yuvipep.com"

    async with SessionLocal() as db:
        project = (await db.execute(select(Project).where(
            Project.name.like("%Horizon%")
        ))).scalars().first()
        assert project is not None, "Horizon project not found — run the planner verification first."
        plans_before = (await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project.id
        ))).scalars().all()
        version_before = max(p.version for p in plans_before)
        tasks_before = len((await db.execute(select(ActionItem).where(
            ActionItem.project_id == project.id
        ))).scalars().all())

    # ── W20: scope grows ─────────────────────────────────────────────────────
    print("W20 — scope expansion: '10 teachers instead of 6'")
    res = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email",
        "from_address": "director@horizonintl.example",
        "subject": "Additional teachers for the lab training",
        "body": (
            "Dear team, wonderful progress on the innovation lab. The Director "
            "has decided we want FOUR more teachers trained on the lab "
            "equipment — ten teachers in total instead of the six we agreed. "
            "Please include this in the program and let us know what changes."
        ),
    })
    msg_id = res.get("id") or res.get("message_id")

    async with SessionLocal() as db:
        msg = (await db.execute(select(InboundMessage).where(
            InboundMessage.id == msg_id
        ))).scalar_one()
        check("classified as change_request", msg.intent == "change_request",
              f"intent={msg.intent}, change_type={msg.change_type}")
        check("matched to the Horizon project", msg.matched_project_id == project.id,
              str(msg.matched_project_id))
        check("asks broken into extracted points", bool(msg.extracted_points),
              str(msg.extracted_points)[:200])
        print(f"     intent={msg.intent} change_type={msg.change_type} "
              f"points={[p.get('type') for p in (msg.extracted_points or [])]}")

        plans = (await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project.id
        ))).scalars().all()
        newest = max(plans, key=lambda p: p.version)
        check("a new plan version was drafted from the reply",
              newest.version > version_before and newest.trigger == "client_reply",
              f"v{newest.version} trigger={newest.trigger}")
        print(f"     plan v{newest.version} diff: "
              f"{(newest.changes_from_previous or '')[:180]}")
        drafts = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.project_id == project.id,
            OutboundMessage.status.in_(("draft", "pending_approval")),
        ))).scalars().all()
        check("acknowledgement drafted for the school (approval-gated)",
              len(drafts) >= 1, f"{len(drafts)} drafts")

    # Approve everything pending (plan + message) as the sales lead.
    approved = 0
    for a in await api.call("GET", "/approvals", user=akash):
        if a["status"] == "pending":
            await api.call("POST", f"/approvals/{a['id']}/decide", user=akash,
                           json={"approve": True})
            approved += 1
    async with SessionLocal() as db:
        tasks_after = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project.id
        ))).scalars().all()
        new_tasks = [t for t in tasks_after if t.plan_version_added
                     and t.plan_version_added > version_before]
        check("scope-expansion tasks exist after approval",
              len(tasks_after) > tasks_before and len(new_tasks) >= 1,
              f"{tasks_before} → {len(tasks_after)} tasks")
        print("     new tasks: " + " | ".join(t.title[:70] for t in new_tasks))

    # ── W22: complaint ───────────────────────────────────────────────────────
    print("W22 — complaint: engineer late, printer not working")
    res = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email",
        "from_address": "director@horizonintl.example",
        "subject": "Very disappointed with today's installation visit",
        "body": (
            "I must complain about today. Your installation engineer arrived "
            "three hours late, and one of the 3D printers is still not working "
            "after he left. This is unacceptable — it must be fixed before the "
            "teacher training begins."
        ),
    })
    msg_id = res.get("id") or res.get("message_id")

    async with SessionLocal() as db:
        msg = (await db.execute(select(InboundMessage).where(
            InboundMessage.id == msg_id
        ))).scalar_one()
        check("classified as complaint, negative sentiment",
              msg.intent == "complaint" and msg.sentiment == "negative",
              f"intent={msg.intent} sentiment={msg.sentiment}")
        incident = (await db.execute(select(Incident).where(
            Incident.project_id == project.id, Incident.status == "open"
        ))).scalars().first()
        check("incident opened on the project", incident is not None,
              "no incident row")
        if incident:
            print(f"     incident: {incident.description[:140]} "
                  f"(severity={incident.severity})")
        holding = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.project_id == project.id,
            OutboundMessage.status.in_(("draft", "pending_approval")),
        ))).scalars().all()
        check("holding reply drafted (approval-gated)", len(holding) >= 1,
              f"{len(holding)}")

    # Approve pending message approvals, then actually "send" (dry-run).
    for a in await api.call("GET", "/approvals", user=akash):
        if a["status"] == "pending":
            await api.call("POST", f"/approvals/{a['id']}/decide", user=akash,
                           json={"approve": True})
    from app.core.constants import MessageStatus
    from app.services.message_service import execute_send

    sent = 0
    async with SessionLocal() as db:
        queued = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.status == MessageStatus.QUEUED.value
        ))).scalars().all()
        for m in queued:
            await execute_send(db, m)
            sent += 1
        await db.commit()
    outbox = list((s.storage_path / "orgs").glob("*/outbox/*"))
    check("approved replies really 'sent' (dry-run .eml in the org outbox)",
          sent >= 1 and len(outbox) >= 1, f"sent={sent}, outbox files={len(outbox)}")
    if outbox:
        print(f"     outbox: {outbox[-1].name}")

    await client.aclose()

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    for desc, ok, detail in CHECKS:
        if not ok:
            print(f"FAILED: {desc}  {detail}")
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
