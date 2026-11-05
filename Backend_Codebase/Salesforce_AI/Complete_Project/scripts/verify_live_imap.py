"""Live verification of the IMAP poller's gates — real LLM screening.

Feeds constructed RFC-822 emails through mail_poller.process_raw_email (the
exact path polled mail takes after the socket) on the verify_generic.db
world. Proves, in order:

  1. a newsletter with mailing-list headers is skipped on protocol hygiene
  2. a marketing blast from a stranger is judged noise by the MODEL and
     ignored WITH an audit-log entry (never silently)
  3. a genuine stranger enquiry is judged human and lands in triage
  4. a known contact's email is always ingested and classified
  5. the same Message-ID a second time is a duplicate no-op
  6. an org user's own address is skipped (loop guard)

Run:  python scripts/verify_live_imap.py   (after verify_live_change_requests.py)
"""
from __future__ import annotations

import asyncio
import os
import sys
from email.message import EmailMessage
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

from sqlalchemy import select  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


def make_email(from_addr: str, subject: str, body: str, message_id: str,
               headers: dict[str, str] | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "sales@yuvipep.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    for k, v in (headers or {}).items():
        msg[k] = v
    msg.set_content(body)
    return msg.as_bytes()


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_generic_planner.py first."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE IMAP-gate run — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.jobs.mail_poller import process_raw_email
    from app.main import app  # noqa: F401 — wires the app config

    await init_db()
    register_handlers()
    sync_engine.register()

    from app.models.audit import AuditLog
    from app.models.comms import InboundMessage
    from app.models.lead import Lead

    async with SessionLocal() as db:
        dps = (await db.execute(select(Lead).where(
            Lead.name == "Delhi Public School"
        ))).scalar_one()
        org_id = dps.org_id

    # 1. Mailing-list newsletter → protocol hygiene, no LLM needed.
    out = await process_raw_email(org_id, make_email(
        "updates@edtech-weekly.example", "Your weekly EdTech digest",
        "Top 10 classroom gadgets this week...", "<nl-1@edtech-weekly.example>",
        headers={"List-Unsubscribe": "<mailto:unsub@edtech-weekly.example>",
                 "Precedence": "bulk"},
    ))
    check("newsletter skipped on mailing-list headers", out == "automation", out)

    # 2. Marketing blast, stranger, no automation headers → model judges noise.
    out = await process_raw_email(org_id, make_email(
        "raj@bulksmsdeals.example", "Boost your sales this week!",
        "Hi team, get 50% OFF bulk SMS credits and WhatsApp blast packages. "
        "Limited offer — buy today and reach 1 lakh customers instantly!",
        "<promo-1@bulksmsdeals.example>",
    ))
    check("marketing blast judged noise by the model", out == "ignored_irrelevant", out)
    async with SessionLocal() as db:
        audit = (await db.execute(select(AuditLog).where(
            AuditLog.org_id == org_id, AuditLog.action == "inbound.email_ignored",
        ))).scalars().all()
        check("ignored mail leaves an audit trail (never silent)",
              len(audit) >= 1 and "bulksmsdeals" in str(audit[-1].detail),
              str(audit[-1].detail if audit else None))

    # 3. Genuine stranger enquiry → kept, lands in triage.
    out = await process_raw_email(org_id, make_email(
        "principal@sunshineacademy.example", "Enquiry about your programs",
        "Hello, I am the principal of Sunshine Academy, Howrah. We heard about "
        "your robotics lab work from a colleague. Could someone call me this "
        "week to discuss options for our school?", "<enq-1@sunshineacademy.example>",
    ))
    check("genuine stranger enquiry kept → triage", out == "ingested:triage", out)

    # 4. Known contact → always ingested and classified.
    out = await process_raw_email(org_id, make_email(
        "principal@dpskol.edu.in", "Quick question",
        "Could you tell me when the teacher orientation for the bootcamp is "
        "planned? We would like to inform the staff early.",
        "<dps-q1@dpskol.edu.in>",
    ))
    check("known contact ingested and classified", out.startswith("ingested:"), out)
    async with SessionLocal() as db:
        msg = (await db.execute(select(InboundMessage).where(
            InboundMessage.org_id == org_id,
            InboundMessage.from_address == "principal@dpskol.edu.in",
        ).order_by(InboundMessage.created_at.desc()))).scalars().first()
        check("classification ran on the ingested email",
              msg is not None and bool(msg.intent), f"intent={msg.intent if msg else None}")

    # 5. Same Message-ID again → duplicate no-op.
    out = await process_raw_email(org_id, make_email(
        "principal@dpskol.edu.in", "Quick question",
        "Could you tell me when the teacher orientation is planned?",
        "<dps-q1@dpskol.edu.in>",
    ))
    check("re-delivery of the same Message-ID is a no-op", out == "duplicate", out)

    # 6. Our own user's address → loop guard.
    out = await process_raw_email(org_id, make_email(
        "rahul@yuvipep.com", "Fwd: something", "internal forward",
        "<own-1@yuvipep.com>",
    ))
    check("an org user's own mail is skipped (loop guard)", out == "own_user", out)

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
