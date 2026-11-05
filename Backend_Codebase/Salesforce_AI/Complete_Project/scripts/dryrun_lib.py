"""Infrastructure for the 30-workflow dry run.

Boots the real FastAPI app on an in-process ASGI transport against a fresh
SQLite database, with the deterministic NLU (LLM_PROVIDER=stub) and dry-run
email/WhatsApp — so every run is reproducible and no external key is needed.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Windows consoles default to cp1252 — arrows/₹ in check text must never
# kill a run. Force UTF-8 (errors replaced, never raised).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "dryrun.db"

# Environment MUST be set before any app import (settings are cached).
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["LLM_PROVIDER"] = "stub"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"
os.environ["GEMINI_API_KEY"] = ""

import httpx  # noqa: E402
from sqlalchemy import select, text as sql_text  # noqa: E402

PASSWORD = "Password@123"


@dataclass
class CheckResult:
    description: str
    passed: bool
    detail: str = ""


@dataclass
class WorkflowResult:
    name: str
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)


class Runner:
    """Drives the real app end to end and records evidence per workflow."""

    def __init__(self) -> None:
        self.results: list[WorkflowResult] = []
        self._current: WorkflowResult | None = None
        self.tokens: dict[str, str] = {}
        self.client: httpx.AsyncClient | None = None
        self.ctx: dict[str, Any] = {}  # shared state across workflows

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def setup(self) -> None:
        if DB_PATH.exists():
            DB_PATH.unlink()
        from app.database import init_db
        from app.engines import sync_engine
        from app.jobs import register_handlers
        from app.main import app

        await init_db()
        register_handlers()
        sync_engine.register()

        # Seed the workflow cast.
        from scripts.seed_workflows import seed

        await seed()

        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(
            transport=transport, base_url="http://test/api/v1", timeout=60
        )

    async def teardown(self) -> None:
        if self.client is not None:
            await self.client.aclose()
        # Dispose DB connections — lingering aiosqlite threads otherwise keep
        # the interpreter alive and hold the DB file lock after a crash.
        from app.database import engine

        await engine.dispose()

    # ── Auth / API helpers ───────────────────────────────────────────────────

    async def login(self, email: str) -> str:
        if email in self.tokens:
            return self.tokens[email]
        resp = await self.client.post(
            "/auth/login", json={"email": email, "password": PASSWORD}
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        self.tokens[email] = token
        return token

    async def api(
        self,
        method: str,
        path: str,
        *,
        user: str,
        json: dict | None = None,
        params: dict | None = None,
        expect_error: bool = False,
    ) -> Any:
        token = await self.login(user)
        resp = await self.client.request(
            method, path, json=json, params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if expect_error:
            return resp
        if resp.status_code >= 400:
            raise AssertionError(
                f"{method} {path} as {user} → {resp.status_code}: {resp.text[:400]}"
            )
        return resp.json()

    # ── DB helpers (evidence inspection + time travel) ───────────────────────

    def session(self):
        from app.database import SessionLocal

        return SessionLocal()

    async def fetch_all(self, stmt) -> list:
        async with self.session() as db:
            return (await db.execute(stmt)).scalars().all()

    async def fetch_one(self, stmt):
        async with self.session() as db:
            return (await db.execute(stmt)).scalars().first()

    async def exec_sql(self, statement: str, **params) -> None:
        async with self.session() as db:
            await db.execute(sql_text(statement), params)
            await db.commit()

    async def backdate(self, table: str, column: str, row_id: str, days: float) -> None:
        """Move a timestamp into the past — how the dry run simulates the
        passage of time for ladders, watches and revivals."""
        moment = datetime.utcnow() - timedelta(days=days)
        await self.exec_sql(
            f"UPDATE {table} SET {column} = :moment WHERE id = :row_id",
            moment=moment.isoformat(sep=" "), row_id=row_id,
        )

    async def flush_sends(self) -> int:
        """Deliver every QUEUED message via the real send path (dry-run mode
        writes .eml / .json files to the org outbox) — stands in for the send
        worker, which isn't running under the test transport."""
        from app.core.constants import MessageStatus
        from app.models.messaging import OutboundMessage
        from app.services.message_service import execute_send

        sent = 0
        async with self.session() as db:
            queued = (
                await db.execute(
                    select(OutboundMessage).where(
                        OutboundMessage.status == MessageStatus.QUEUED.value
                    )
                )
            ).scalars().all()
            for message in queued:
                await execute_send(db, message)
                sent += 1
            await db.commit()
        return sent

    # ── Result recording ─────────────────────────────────────────────────────

    def begin(self, name: str) -> None:
        self._current = WorkflowResult(name=name)
        self.results.append(self._current)
        print(f"\n=== {name} ===")

    def check(self, description: str, condition: bool, detail: str = "") -> bool:
        result = CheckResult(description=description, passed=bool(condition), detail=detail)
        self._current.checks.append(result)
        mark = "PASS" if condition else "FAIL"
        line = f"  [{mark}] {description}"
        if detail and not condition:
            line += f"  ({detail})"
        print(line)
        return bool(condition)

    def fail(self, error: str) -> None:
        self._current.error = error
        print(f"  [ERROR] {error}")

    def report(self) -> bool:
        print("\n" + "=" * 72)
        print("DRY-RUN REPORT")
        print("=" * 72)
        passed = 0
        for r in self.results:
            ok = r.passed
            passed += ok
            status = "PASS" if ok else "FAIL"
            n_checks = len(r.checks)
            n_ok = sum(1 for c in r.checks if c.passed)
            print(f"[{status}] {r.name}  ({n_ok}/{n_checks} checks)")
            if r.error:
                print(f"        error: {r.error}")
            for c in r.checks:
                if not c.passed:
                    print(f"        failed: {c.description} {c.detail}")
        print("-" * 72)
        print(f"{passed}/{len(self.results)} workflows passed")
        return passed == len(self.results)


# Convenience: the cast's emails.
EMAILS = {
    "ananya": "ananya@yuvipep.com",
    "akash": "akash@yuvipep.com",
    "rahul": "rahul@yuvipep.com",
    "priya": "priya@yuvipep.com",
    "meera": "meera@yuvipep.com",
    "sourav": "sourav@yuvipep.com",
    "baski": "baski@yuvipep.com",
    "mithun": "mithun@yuvipep.com",
    "shyam": "shyam@yuvipep.com",
    "vikram": "vikram@yuvipep.com",
}


# ─────────────────────────────────────────────────────────────────────────────
# Scenario helpers shared by every workflow part
# ─────────────────────────────────────────────────────────────────────────────

from sqlalchemy import select  # noqa: E402


async def lead_by_name(r: "Runner", name: str):
    from app.models.lead import Lead

    return await r.fetch_one(select(Lead).where(Lead.name == name))


async def contact_by_email(r: "Runner", email: str):
    from app.models.lead import Contact

    return await r.fetch_one(select(Contact).where(Contact.email == email))


async def approvals_for(r: "Runner", user_email: str, contains: str | None = None):
    rows = await r.api("GET", "/approvals", user=user_email)
    if contains:
        rows = [a for a in rows if contains.lower() in (a["reason"] or "").lower()]
    return rows


async def decide(r: "Runner", user_email: str, approval_id: str,
                 approve: bool = True, note: str | None = None):
    return await r.api(
        "POST", f"/approvals/{approval_id}/decide", user=user_email,
        json={"approve": approve, "note": note},
    )


async def approve_all(r: "Runner", user_email: str, contains: str | None = None) -> int:
    """Approve every pending approval addressed to this user."""
    count = 0
    for a in await approvals_for(r, user_email, contains):
        if a["status"] == "pending":
            await decide(r, user_email, a["id"], approve=True)
            count += 1
    return count


async def confirm_all_assignments(r: "Runner", user_email: str) -> int:
    rows = await r.api("GET", "/assignments/proposed", user=user_email)
    if not rows:
        return 0
    await r.api(
        "POST", "/assignments/confirm-batch", user=user_email,
        json={"assignment_ids": [a["id"] for a in rows]},
    )
    return len(rows)


async def tasks_of(r: "Runner", project_id: str):
    from app.models.action_item import ActionItem

    return await r.fetch_all(
        select(ActionItem).where(ActionItem.project_id == project_id)
    )


async def notifications_for(r: "Runner", user_email: str, contains: str = ""):
    from app.models.user import Notification, User

    user = await r.fetch_one(select(User).where(User.email == user_email))
    rows = await r.fetch_all(
        select(Notification).where(Notification.user_id == user.id)
    )
    if contains:
        rows = [
            n for n in rows
            if contains.lower() in (n.title + " " + (n.body or "")).lower()
        ]
    return rows


async def send_inbound(r: "Runner", *, from_address: str, body: str,
                       subject: str | None = None, channel: str = "email"):
    return await r.api(
        "POST", "/inbound/ingest", user=EMAILS["ananya"],
        json={"channel": channel, "from_address": from_address,
              "subject": subject, "body": body},
    )
