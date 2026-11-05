"""Live verification of the LLM-judged answer path (W19 upgrade).

The old retrieval picked facts by word overlap; now the model judges — by
meaning — which of OUR OWN recorded facts answer the question and whether
they suffice. Continues the DPS database of verify_live_change_requests.py.

  1. A question sharing almost no words with the stored syllabus ("a real
     industry language" vs "Kotlin") must still be answered from it.
  2. A question we hold no data for (insurance) must go to a human with
     the "never guesses" reason — the model must not stretch loose facts.

Run:  python scripts/verify_live_answers.py
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
    assert DB_PATH.exists(), "Run scripts/verify_live_change_requests.py first."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE answer-path run — provider={s.llm_provider}\n")

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

    from app.models.lead import Lead
    from app.models.messaging import OutboundMessage
    from app.models.project import Project

    PHONE = "+91 9800000060"  # Mrs. Sharma, DPS principal

    async with SessionLocal() as db:
        dps = (await db.execute(select(Lead).where(
            Lead.name == "Delhi Public School"
        ))).scalar_one()
        bootcamp = (await db.execute(select(Project).where(
            Project.lead_id == dps.id
        ).order_by(Project.created_at))).scalars().first()

    # 1. Meaning-only match: no useful word overlap with the stored syllabus.
    resp = await call("POST", "/inbound/ingest", user="ananya@yuvipep.com", json={
        "channel": "whatsapp", "from_address": PHONE,
        "body": "One parent asked me — her daughter wants to be a professional "
                "developer someday. During the bootcamp will the children get "
                "to write in a real industry language, or is everything visual "
                "drag-and-drop?",
    })
    check("paraphrased question answered from our own data (no word overlap)",
          resp["intent"] == "question" and resp["status"] == "processed",
          f"{resp['intent']} / {resp['status']} / {resp.get('needs_human_reason')}")
    async with SessionLocal() as db:
        draft = (await db.execute(
            select(OutboundMessage)
            .where(OutboundMessage.channel == "whatsapp",
                   OutboundMessage.kind == "reply")
            .order_by(OutboundMessage.created_at.desc())
        )).scalars().first()
        check("draft cites the syllabus fact the model matched by MEANING (Kotlin)",
              draft is not None and "kotlin" in draft.body.lower(),
              (draft.body[:220] if draft else "no draft"))

    # 2. Honestly unanswerable: the model must not stretch loose facts.
    resp2 = await call("POST", "/inbound/ingest", user="ananya@yuvipep.com", json={
        "channel": "whatsapp", "from_address": PHONE,
        "body": "Do you provide personal accident insurance coverage for the "
                "children during the sessions?",
    })
    check("no data → needs_human with the 'never guesses' reason",
          resp2["status"] == "needs_human"
          and "never guesses" in (resp2.get("needs_human_reason") or ""),
          f"{resp2['status']} / {resp2.get('needs_human_reason')}")

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
