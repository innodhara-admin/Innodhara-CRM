"""Re-test just the W29 matching checks (the first run lost network mid-way).
Reuses the DPS bootcamp + STEM lab projects created by verify_live_routing.py.

Run:  python scripts/verify_live_w29_retest.py
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


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_live_routing.py first."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE W29 retest — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app

    await init_db()
    register_handlers()
    sync_engine.register()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=300)

    async def call(method: str, path: str, *, user: str, json: dict | None = None):
        r = await client.post("/auth/login", json={"email": user, "password": PASSWORD})
        token = r.json()["access_token"]
        r = await client.request(method, path, json=json,
                                 headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()

    from app.models.comms import InboundMessage
    from app.models.lead import Lead
    from app.models.project import Project

    async with SessionLocal() as db:
        dps = (await db.execute(select(Lead).where(
            Lead.name == "Delhi Public School"
        ))).scalar_one()
        projects = (await db.execute(select(Project).where(
            Project.lead_id == dps.id
        ).order_by(Project.created_at))).scalars().all()
    assert len(projects) >= 2, f"Expected bootcamp + lab, found {len(projects)}"
    bootcamp, lab = projects[0], projects[1]
    print(f"bootcamp={bootcamp.name} | lab={lab.name}\n")

    resp = await call("POST", "/inbound/ingest", user="ananya@yuvipep.com", json={
        "channel": "email", "from_address": "principal@dpskol.edu.in",
        "subject": "Regarding the lab",
        "body": "Regarding the STEM lab quote — when can we see the setup cost "
                "breakdown for the permanent lab?",
    })
    check("'the lab quote' matched to the LAB project by content (LLM)",
          resp["matched_project_id"] == lab.id,
          f"matched={resp['matched_project_id']} expected={lab.id}")

    resp2 = await call("POST", "/inbound/ingest", user="ananya@yuvipep.com", json={
        "channel": "email", "from_address": "principal@dpskol.edu.in",
        "subject": "Friday",
        "body": "Let us discuss both the bootcamp and the STEM lab together on "
                "Friday.",
    })
    check("a message spanning BOTH projects gets no single primary + a human",
          resp2["matched_project_id"] is None
          and resp2["status"] in ("needs_human", "triage"),
          f"matched={resp2['matched_project_id']} status={resp2['status']}")
    async with SessionLocal() as db:
        msg = (await db.execute(select(InboundMessage).where(
            InboundMessage.id == resp2["id"]
        ))).scalar_one()
        check("related_project_ids records the span across both projects",
              len(msg.related_project_ids or []) >= 2,
              str(msg.related_project_ids))

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
