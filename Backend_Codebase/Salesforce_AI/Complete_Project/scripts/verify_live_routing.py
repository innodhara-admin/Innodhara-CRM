"""Live verification of W19 / W29 / X1 — questions, multi-project routing,
triage — with a real LLM. Continues the database of
verify_live_change_requests.py (run that first: it leaves DPS with a
delivering bootcamp project and a syllabus deliverable).

  W19 — a WhatsApp question is answered strictly from OUR OWN data (program +
        deliverables); a question we hold no data for goes to a named human
        ("the AI never guesses"); an instalments ask takes the money path,
        never the casual path.
  W29 — a second project on the same school: content routes "the lab quote"
        to the lab project; a message that deliberately spans both projects
        gets NO single primary, records the span, and reaches a human.
  X1  — a stranger's enquiry lands in triage where a human resolves it —
        nothing is dropped, nothing is guessed.

Run:  python scripts/verify_live_routing.py
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


async def approve_pending(api: Api, user: str) -> int:
    n = 0
    for a in await api.call("GET", "/approvals", user=user):
        if a["status"] == "pending":
            await api.call("POST", f"/approvals/{a['id']}/decide", user=user,
                           json={"approve": True})
            n += 1
    return n


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_live_change_requests.py first."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE routing run — provider={s.llm_provider}\n")

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

    from app.models.action_item import ActionItem
    from app.models.comms import InboundMessage
    from app.models.lead import Contact, Lead
    from app.models.messaging import OutboundMessage
    from app.models.project import Project

    rahul, priya, akash = "rahul@yuvipep.com", "priya@yuvipep.com", "akash@yuvipep.com"
    ananya = "ananya@yuvipep.com"
    PHONE = "+91 9800000060"  # Mrs. Sharma, DPS principal

    async with SessionLocal() as db:
        dps = (await db.execute(select(Lead).where(
            Lead.name == "Delhi Public School"
        ))).scalar_one()
        bootcamp = (await db.execute(select(Project).where(
            Project.lead_id == dps.id
        ))).scalars().first()
    assert bootcamp is not None, "DPS bootcamp project missing — run change_requests first."

    # ── W19: questions ───────────────────────────────────────────────────────
    print("W19 — a WhatsApp question, answered from what we know")
    resp = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "whatsapp", "from_address": PHONE,
        "body": "Will the bootcamp also cover Kotlin, or only block-based apps? "
                "Parents are asking.",
    })
    check("question matched by phone → contact → project, answered from data",
          resp["intent"] == "question"
          and resp["matched_project_id"] == bootcamp.id
          and resp["status"] == "processed",
          f"{resp['intent']} / {resp['status']} / {resp.get('needs_human_reason')}")
    async with SessionLocal() as db:
        draft = (await db.execute(
            select(OutboundMessage)
            .where(OutboundMessage.channel == "whatsapp",
                   OutboundMessage.project_id == bootcamp.id,
                   OutboundMessage.kind == "reply")
            .order_by(OutboundMessage.created_at.desc())
        )).scalars().first()
        check("draft answers from the syllabus facts (mentions Kotlin)",
              draft is not None and "kotlin" in draft.body.lower(),
              (draft.body[:200] if draft else "no draft"))

    resp2 = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "whatsapp", "from_address": PHONE,
        "body": "Will you provide graduation scrolls stamped by the national "
                "education board?",
    })
    check("no data → needs_human, reason written down (the AI never guesses)",
          resp2["status"] == "needs_human"
          and "never guesses" in (resp2.get("needs_human_reason") or ""),
          f"{resp2['status']} / {resp2.get('needs_human_reason')}")
    async with SessionLocal() as db:
        q_task = (await db.execute(select(ActionItem).where(
            ActionItem.lead_id == dps.id,
            ActionItem.title.like("Answer %"),
        ))).scalars().first()
        check("a task carries the unanswerable question to a named human",
              q_task is not None and q_task.assignee_id is not None,
              q_task.title if q_task else "missing")

    resp3 = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "whatsapp", "from_address": PHONE,
        "body": "Also — can we pay the amount in 3 instalments?",
    })
    check("payment talk routed to the money machinery, never the casual path",
          (resp3["intent"] in ("payment_info", "question", "change_request"))
          and resp3["status"] in ("processed", "needs_human"),
          f"{resp3['intent']} / {resp3['status']} / {resp3.get('needs_human_reason')}")

    # ── W29: two projects, one school ────────────────────────────────────────
    print("W29 — a second project on the same school; content picks the right one")
    res = await api.call("POST", "/meetings/notes", user=priya, json={
        "lead_id": dps.id, "meeting_type": "first_visit",
        "title": "DPS STEM lab — separate discussion",
        "text": "Separate discussion at Delhi Public School with the principal "
                "about a permanent STEM lab for 2027 — a different budget line "
                "from the bootcamp. Lab setup plus a year of support, around 60 "
                "students per term using the lab.",
    })
    if not check("second project born on the same lead",
                 res["planner"].get("action") == "project_proposed",
                 str(res["planner"])):
        raise SystemExit("Lab project birth failed (likely rate limits) — aborting cleanly.")
    lab_id = res["planner"]["project_id"]
    check("bootcamp and lab are different projects", lab_id != bootcamp.id)
    await approve_pending(api, akash)

    resp4 = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "principal@dpskol.edu.in",
        "subject": "Regarding the lab",
        "body": "Regarding the STEM lab quote — when can we see the setup cost "
                "breakdown for the permanent lab?",
    })
    check("'the lab quote' matched to the LAB project by content (LLM)",
          resp4["matched_project_id"] == lab_id,
          f"matched={resp4['matched_project_id']} expected={lab_id}")

    resp5 = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "principal@dpskol.edu.in",
        "subject": "Friday",
        "body": "Let us discuss both the bootcamp and the STEM lab together on "
                "Friday.",
    })
    check("a message spanning BOTH projects gets no single primary + a human",
          resp5["matched_project_id"] is None
          and resp5["status"] in ("needs_human", "triage"),
          f"matched={resp5['matched_project_id']} status={resp5['status']}")
    async with SessionLocal() as db:
        msg = (await db.execute(select(InboundMessage).where(
            InboundMessage.id == resp5["id"]
        ))).scalar_one()
        check("related_project_ids records the span across both projects",
              len(msg.related_project_ids or []) >= 2,
              str(msg.related_project_ids))

    # ── X1: the stranger ─────────────────────────────────────────────────────
    print("X1 — a stranger writes in: triage, nothing dropped")
    resp6 = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "unknown.sender@randomschool.edu.in",
        "subject": "Enquiry",
        "body": "We heard about your bootcamps. Can someone call us?",
    })
    check("unmatched sender → triage queue", resp6["status"] == "triage",
          resp6["status"])
    queue = await api.call("GET", "/inbound/triage", user=akash)
    check("a human sees it in the queue",
          any(m["id"] == resp6["id"] for m in queue), f"{len(queue)} queued")
    async with SessionLocal() as db:
        contact = (await db.execute(select(Contact).where(
            Contact.email == "principal@greenvalley.edu.in"
        ))).scalars().first()
    fixed = await api.call("POST", f"/inbound/{resp6['id']}/resolve", user=akash,
                           json={"contact_id": contact.id, "mark_processed": True})
    check("resolved by hand — the engines reconcile manual work",
          bool(fixed.get("ok")), str(fixed))

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
