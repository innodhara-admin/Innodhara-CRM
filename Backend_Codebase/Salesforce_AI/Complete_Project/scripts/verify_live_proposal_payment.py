"""Live verification of W3 (proposal) and W25 (getting paid) — real LLM key.

Continues the database of verify_generic_planner.py (run that first) but
tells its own story on Swami Vivekananda School with the Android Bootcamp
program, because proposals price strictly from a program's pricing table:

  W3  — a first meeting births the project (LLM plan), the proposal is built
        with LOCKED template+pricing versions, the >₹1L rule routes it to the
        sales lead, a rejection note loops it back, a natural-language edit
        (LLM) applies the fix WITHOUT touching the machine-computed price,
        and the approved proposal is sent from the salesperson's address.
  W8→ — the principal replies "we are agreed" (LLM classifies approval) →
        the proposal is ACCEPTED, the deal-agreed machinery fires.
  W25 — a 50% advance invoice is derived from the accepted proposal (never
        typed), carried by a drafted email to the payments gatekeeper with
        the principal in CC, chased politely when overdue, paused when the
        school says "cheque ready", and closed with honest part-payment math
        plus a thank-you draft.

Run:  python scripts/verify_live_proposal_payment.py
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

DB_PATH = PROJECT_ROOT / "data" / "verify_generic.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402
from sqlalchemy import select, text as sql_text  # noqa: E402

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


async def approve_pending(api: Api, user: str, contains: str | None = None) -> int:
    n = 0
    for a in await api.call("GET", "/approvals", user=user):
        if a["status"] != "pending":
            continue
        if contains and contains.lower() not in (a.get("reason") or "").lower():
            continue
        await api.call("POST", f"/approvals/{a['id']}/decide", user=user,
                       json={"approve": True})
        n += 1
    return n


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_generic_planner.py first."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE proposal+payment run — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app

    await init_db()
    register_handlers()
    sync_engine.register()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=300)
    api = Api(client)

    from app.core.constants import MessageStatus
    from app.models.action_item import ActionItem
    from app.models.lead import Contact, Lead
    from app.models.messaging import OutboundMessage
    from app.models.program import Program
    from app.models.proposal import Proposal, ProposalRevision
    from app.services.message_service import execute_send

    rahul, priya, akash = "rahul@yuvipep.com", "priya@yuvipep.com", "akash@yuvipep.com"
    vikram, ananya = "vikram@yuvipep.com", "ananya@yuvipep.com"

    async def flush_sends() -> int:
        sent = 0
        async with SessionLocal() as db:
            queued = (await db.execute(select(OutboundMessage).where(
                OutboundMessage.status == MessageStatus.QUEUED.value
            ))).scalars().all()
            for m in queued:
                await execute_send(db, m)
                sent += 1
            await db.commit()
        return sent

    async with SessionLocal() as db:
        svs = (await db.execute(select(Lead).where(
            Lead.name == "Swami Vivekananda School"
        ))).scalar_one()
        program = (await db.execute(select(Program).where(
            Program.code == "ANDROID_BC"
        ))).scalar_one()
        principal = (await db.execute(select(Contact).where(
            Contact.lead_id == svs.id, Contact.email == "principal@svs.edu.in"
        ))).scalars().first()
        accounts = (await db.execute(select(Contact).where(
            Contact.lead_id == svs.id, Contact.email == "accounts@svs.edu.in"
        ))).scalars().first()
    assert principal is not None, "Seeded SVS principal contact missing"
    if accounts is None:
        await api.call("POST", f"/leads/{svs.id}/contacts", user=rahul, json={
            "name": "Mr. Iyer (Accounts)", "title": "Accountant",
            "email": "accounts@svs.edu.in",
        })

    # ── Project birth (LLM initial plan — generic engine, familiar topic) ────
    print("Setup — first meeting births the SVS bootcamp project (LLM plan)")
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": svs.id, "title": "SVS bootcamp — first meeting",
        "text": (
            "Meeting with the Principal of Swami Vivekananda School. They "
            "want our 7-day Android app development bootcamp for classes 5 "
            "to 9, around 400 students. They asked for a formal proposal "
            "with pricing this week. Materials kit needed for the labs."
        ),
        "meeting_type": "first_visit",
    })
    planner = res["planner"]
    if not check("project proposed from the meeting",
                 planner.get("action") == "project_proposed", str(planner)):
        raise SystemExit("Project birth failed (likely rate limits) — aborting cleanly.")
    project_id = planner["project_id"]
    await approve_pending(api, akash)  # activate plan v1

    # ── W3: the proposal ─────────────────────────────────────────────────────
    print("W3 — proposal: built by AI, checked by people, sent by the right person")
    proposal = await api.call("POST", "/proposals", user=priya, json={
        "lead_id": svs.id, "program_id": program.id, "project_id": project_id,
        "context_summary": "7-day bootcamp, classes 5-9, ~400 students",
        "quantities": {"per_student": 400, "materials": 1},
    })
    check("priced strictly from the pricing table (400×300 + 6000 = 126000)",
          proposal["total_amount"] == 126000, str(proposal["total_amount"]))
    check("template + pricing versions locked",
          bool(proposal["template_version"]) and bool(proposal["pricing_version"]),
          f"tmpl v{proposal['template_version']}, pricing v{proposal['pricing_version']}")

    review = await api.call("POST", f"/proposals/{proposal['id']}/submit-review", user=priya)
    check("above ₹1,00,000 → routed to the sales lead", review.get("approval_id") is not None)
    await api.call("POST", f"/approvals/{review['approval_id']}/decide", user=akash,
                   json={"approve": False,
                         "note": "Good, but add payment terms: 50% advance on "
                                 "agreement, balance on completion."})
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("rejection looped it back to draft", p.status == "draft", p.status)
        revs = (await db.execute(select(ProposalRevision).where(
            ProposalRevision.proposal_id == p.id
        ))).scalars().all()
        check("the note is a recorded revision",
              any("50% advance" in (r.instruction or "") for r in revs))

    # The fix applied by NATURAL LANGUAGE — the LLM edits prose, never price.
    await api.call("POST", f"/proposals/{proposal['id']}/edit", user=priya, json={
        "instruction": "Add a payment terms section: 50% advance on agreement, "
                       "balance on completion.",
    })
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("LLM edit added the terms to the narrative",
              "50%" in (p.content_md or ""), (p.content_md or "")[-200:])
        check("machine-computed price untouched by the edit",
              p.total_amount == 126000, str(p.total_amount))

    review2 = await api.call("POST", f"/proposals/{proposal['id']}/submit-review", user=priya)
    await api.call("POST", f"/approvals/{review2['approval_id']}/decide", user=akash,
                   json={"approve": True})
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("approved internally", p.status == "approved_internally", p.status)

    await api.call("POST", f"/proposals/{proposal['id']}/approve-send", user=rahul,
                   json={"to_address": "principal@svs.edu.in", "cc": [akash]})
    await flush_sends()
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("proposal sent from the salesperson", p.status == "sent", p.status)

    # ── Bridge: the school agrees (LLM classifies the yes) ──────────────────
    print("Bridge — 'we are agreed' → proposal accepted, deal machinery fires")
    await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "principal@svs.edu.in",
        "subject": "Re: Android Bootcamp Proposal",
        "body": "We are agreed — the proposal is approved from our side. "
                "Please proceed with the December batch as discussed.",
    })
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("proposal ACCEPTED from the school's reply", p.status == "accepted", p.status)
    await approve_pending(api, akash)   # preparation wave / drafts etc.
    await approve_pending(api, "mithun@yuvipep.com")

    # ── W25: getting paid ────────────────────────────────────────────────────
    print("W25 — getting paid")
    # The payments gatekeeper: the accountant stakeholder (never the principal).
    async with SessionLocal() as db:
        accounts = (await db.execute(select(Contact).where(
            Contact.lead_id == svs.id, Contact.email == "accounts@svs.edu.in"
        ))).scalars().first()
    await api.call("POST", f"/projects/{project_id}/stakeholders", user=akash, json={
        "contact_id": accounts.id, "role_at_client": "accountant",
        "influence": "gatekeeper",
    })

    invoice = await api.call("POST", "/invoices", user=vikram, json={
        "project_id": project_id, "kind": "advance", "advance_pct": 50,
        "due_in_days": 7,
    })
    check("advance derived from the ACCEPTED proposal (50% of 126000 = 63000)",
          invoice["amount"] == 63000, f"{invoice['amount']} — {invoice['computation']}")
    sent = await api.call("POST", f"/invoices/{invoice['id']}/send", user=vikram)
    check("invoice email drafted to the gatekeeper (approval-gated)",
          sent.get("message_id") is not None)
    await approve_pending(api, akash)
    await flush_sends()

    # Overdue +4 days → the polite reminder from the daily sweep.
    async with SessionLocal() as db:
        moment = (datetime.utcnow() - timedelta(days=4)).isoformat(sep=" ")
        await db.execute(sql_text(
            "UPDATE invoices SET due_date = :m, status = 'sent' WHERE id = :i"
        ), {"m": moment, "i": invoice["id"]})
        await db.commit()
    await api.call("POST", "/sync/sweep", user=ananya)
    await approve_pending(api, akash)
    await flush_sends()
    async with SessionLocal() as db:
        reminders = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.kind == "invoice",
            OutboundMessage.triggered_by == "reminder_ladder",
            OutboundMessage.project_id == project_id,
        ))).scalars().all()
        check("overdue → polite reminder drafted by the ladder", len(reminders) >= 1,
              f"{len(reminders)} reminders")

    # 'Cheque ready, collect Friday' → payment info; a collection task; ladder pauses.
    await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "accounts@svs.edu.in",
        "subject": "Re: advance invoice",
        "body": "The cheque for the advance is ready. Please collect it on Friday.",
    })
    async with SessionLocal() as db:
        collect = (await db.execute(select(ActionItem).where(
            ActionItem.title.like("Collect payment%"),
            ActionItem.project_id == project_id,
        ))).scalars().first()
        check("'cheque ready' understood → collection task created",
              collect is not None)

    # Money lands: honest part-payment math, then the thank-you.
    part = await api.call("POST", f"/invoices/{invoice['id']}/record-payment",
                          user=vikram, json={"amount": 30000, "method": "cheque",
                                             "note": "Cheque no. 2201"})
    check("part payment → part_paid", part["invoice_status"] == "part_paid",
          str(part))
    rest = await api.call("POST", f"/invoices/{invoice['id']}/record-payment",
                          user=vikram, json={"amount": 33000, "method": "transfer",
                                             "note": "advance settled"})
    check("full settlement → paid", rest["invoice_status"] == "paid", str(rest))
    thanked = await approve_pending(api, akash, contains="thank")
    check("thank-you note drafted for one-tap approval", thanked >= 1, str(thanked))
    await flush_sends()

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
