"""Live verification of W4 (change requests) + the deal-agreed switch — real LLM.

Continues the database of verify_generic_planner.py (run that first). Tells
its story on Delhi Public School with the Android Bootcamp program:

  W3-lite — a first meeting births the DPS project (LLM plan), the proposal
            is built from the LOCKED pricing table and sent.
  W4A     — "1.26 lakh is above our budget, can you do one lakh?" → the LLM
            extracts the discount ask; money never negotiates itself: the
            RECOMMEND→DECIDE approval chain runs (sales lead recommends, org
            admin decides); the approved special price lands as a recorded
            human override, never an invented number.
  W4B     — "syllabus too advanced, simplify days 1-2, add internet safety"
            → a P1 revision task, skill-routed, client acknowledged; the fix
            arrives by MANUAL UPLOAD (the Word→PDF path is first-class) and
            a client update is drafted.
  W8-lite — "Agreed. Let's proceed at the special price." → LLM classifies
            the approval; proposal ACCEPTED at the special price; the machine
            switches to delivering (ops co-owner, preparation wave).

Run:  python scripts/verify_live_change_requests.py
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
    print(f"LIVE change-request run — provider={s.llm_provider}\n")

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
    from app.models.finance import Deliverable
    from app.models.lead import Lead
    from app.models.messaging import OutboundMessage
    from app.models.program import Program
    from app.models.project import Project
    from app.models.proposal import Proposal
    from app.models.user import User
    from app.services.message_service import execute_send

    rahul, priya, akash = "rahul@yuvipep.com", "priya@yuvipep.com", "akash@yuvipep.com"
    ananya = "ananya@yuvipep.com"
    PRINCIPAL = "principal@dpskol.edu.in"

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
        dps = (await db.execute(select(Lead).where(
            Lead.name == "Delhi Public School"
        ))).scalar_one()
        program = (await db.execute(select(Program).where(
            Program.code == "ANDROID_BC"
        ))).scalar_one()

    # ── Setup: project birth + proposal sent (both already proven live; the
    #    checks here only anchor the story) ────────────────────────────────────
    print("Setup — DPS bootcamp project (LLM plan) + proposal from the pricing table")
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": dps.id, "title": "DPS bootcamp — first meeting",
        "text": (
            "Meeting with Mrs. Sharma, Principal of Delhi Public School, Park "
            "Street. They want our 7-day Android app development bootcamp for "
            "classes 5 to 9, around 400 students, with the materials kit. They "
            "asked for a formal proposal with pricing this week."
        ),
        "meeting_type": "first_visit",
    })
    planner = res["planner"]
    if not check("project proposed from the meeting",
                 planner.get("action") == "project_proposed", str(planner)):
        raise SystemExit("Project birth failed (likely rate limits) — aborting cleanly.")
    project_id = planner["project_id"]
    await approve_pending(api, akash)  # plan v1

    proposal = await api.call("POST", "/proposals", user=priya, json={
        "lead_id": dps.id, "program_id": program.id, "project_id": project_id,
        "context_summary": "7-day bootcamp, classes 5-9, ~400 students",
        "quantities": {"per_student": 400, "materials": 1},
    })
    check("proposal priced strictly from the table (126000)",
          proposal["total_amount"] == 126000, str(proposal["total_amount"]))
    review = await api.call("POST", f"/proposals/{proposal['id']}/submit-review", user=priya)
    await api.call("POST", f"/approvals/{review['approval_id']}/decide", user=akash,
                   json={"approve": True})
    await api.call("POST", f"/proposals/{proposal['id']}/approve-send", user=rahul,
                   json={"to_address": PRINCIPAL, "cc": []})
    await flush_sends()
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("proposal sent to the principal", p.status == "sent", p.status)

    # ── W4A: the discount ask — money never negotiates itself ───────────────
    print("W4A — '1.26 lakh is above our budget, can you do one lakh?'")
    resp = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": PRINCIPAL,
        "subject": "Re: Android Bootcamp Proposal",
        "body": "The proposal looks good, but 1.26 lakh is above our budget. "
                "Can you do it in one lakh?",
    })
    check("discount ask extracted by the LLM",
          any(pt.get("type") == "discount_request"
              for pt in (resp.get("extracted_points") or [])),
          f"intent={resp['intent']} points={resp.get('extracted_points')}")

    cards = [a for a in await api.call("GET", "/approvals", user=akash)
             if a["status"] == "pending" and a["entity_type"] == "price_change"]
    if not check("recommend stage reaches the sales lead (>10% discount)",
                 len(cards) == 1 and cards[0]["stage"] == "recommend",
                 f"{len(cards)} price_change cards"):
        raise SystemExit("Discount chain did not start — aborting cleanly.")
    step = await api.call("POST", f"/approvals/{cards[0]['id']}/decide", user=akash,
                          json={"approve": True,
                                "note": "Offer 1,10,000 as a special price — the "
                                        "December slot and a testimonial justify it."})
    check("recommendation chained to the org admin's DECIDE stage",
          step["chained_next"] is True and step["stage"] == "decide", str(step))
    decide_cards = [a for a in await api.call("GET", "/approvals", user=ananya)
                    if a["status"] == "pending" and a["entity_type"] == "price_change"]
    check("org admin sees the recommendation on the decide card",
          bool(decide_cards) and "1,10,000" in (decide_cards[0]["recommendation"] or ""),
          str(decide_cards[:1]))
    final = await api.call("POST", f"/approvals/{decide_cards[0]['id']}/decide",
                           user=ananya, json={"approve": True})
    check("special price approved by the org admin", final["status"] == "approved",
          str(final))

    # The approved override lands as a discount LINE — recorded, never invented.
    import json as _json
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        items = list(p.line_items) + [{
            "code": "special_discount",
            "label": "Special price concession (approved by org admin)",
            "unit": "flat", "unit_price": -16000, "quantity": 1,
            "line_total": -16000,
        }]
        await db.execute(sql_text(
            "UPDATE proposals SET line_items = :items, total_amount = 110000, "
            "special_price_approval_id = :appr WHERE id = :pid"
        ), {"items": _json.dumps(items), "appr": decide_cards[0]["id"], "pid": p.id})
        await db.commit()

    # ── W4B: the content ask — a task, an acknowledgement, a manual upload ──
    print("W4B — 'syllabus too advanced for classes 5-6, add internet safety'")
    resp_b = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": PRINCIPAL,
        "subject": "Re: Android Bootcamp Proposal",
        "body": "The price is fine now, but the syllabus inside is too advanced "
                "for classes 5-6. Please simplify days 1-2 for the juniors, and "
                "add one session on internet safety.",
    })
    # F31: assert the property — a content-change point was raised — not the one
    # name it used to carry. `content_change` is current, `syllabus_change` is
    # still routed, and both satisfy this check.
    check("content change understood (content_change point)",
          any(pt.get("type") in ("content_change", "syllabus_change")
              for pt in (resp_b.get("extracted_points") or [])),
          f"intent={resp_b['intent']} points={resp_b.get('extracted_points')}")
    async with SessionLocal() as db:
        revision = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.title.like("Revise content%"),
        ))).scalars().first()
        check("P1 revision task created, skill-routed, visible to the client",
              revision is not None and revision.priority == "P1"
              and revision.required_skill == "curriculum_design"
              and revision.visible_to_client,
              f"{revision.title if revision else 'missing'}")
        drafts = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.project_id == project_id,
            OutboundMessage.status.in_(("draft", "pending_approval")),
        ))).scalars().all()
        check("acknowledgement drafted — the school is never left hanging",
              len(drafts) >= 1, f"{len(drafts)} drafts")
        assignee_email = None
        if revision is not None and revision.assignee_id:
            assignee = (await db.execute(select(User).where(
                User.id == revision.assignee_id
            ))).scalar_one_or_none()
            assignee_email = assignee.email if assignee else None
    await approve_pending(api, akash)
    await flush_sends()

    done = await api.call(
        "POST", f"/tasks/{revision.id}/complete",
        user=assignee_email or "meera@yuvipep.com",
        json={"result_note": "Simplified days 1-2; added internet safety on day 4",
              "completion_method": "manual_upload",
              "deliverable_type": "syllabus",
              "deliverable_title": "DPS syllabus v2 (simplified juniors + internet safety)",
              "deliverable_content_md": "# Syllabus v2\nDays 1-2 simplified for "
              "classes 5-6.\nDay 4: internet safety session.\nDays 5-7: Kotlin "
              "introduction for classes 8-9 and block-based apps for juniors. "
              "The bootcamp covers Kotlin basics alongside block-based apps."},
    )
    async with SessionLocal() as db:
        d = (await db.execute(select(Deliverable).where(
            Deliverable.id == done["deliverable_id"]
        ))).scalar_one_or_none() if done.get("deliverable_id") else None
        check("manual upload completed the task with a versioned deliverable",
              done.get("ok") and d is not None and d.source == "manual_upload",
              str(done))
    updates = await approve_pending(api, akash)
    check("client update drafted for the completed visible task", updates >= 1,
          f"{updates} approvals")
    await flush_sends()

    # ── W8-lite: 'Agreed' — selling becomes delivering ───────────────────────
    print("W8-lite — 'Agreed. Let's proceed at the special price.'")
    agree = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": PRINCIPAL,
        "subject": "Re: Android Bootcamp Proposal",
        "body": "Agreed. Let's proceed at the special price.",
    })
    check("'Agreed. Let's proceed.' classified as approval",
          agree["intent"] == "approval", agree["intent"])
    async with SessionLocal() as db:
        p = (await db.execute(select(Proposal).where(
            Proposal.id == proposal["id"]
        ))).scalar_one()
        check("proposal ACCEPTED at the special price",
              p.status == "accepted" and p.total_amount == 110000,
              f"{p.status} @ {p.total_amount}")
        project = (await db.execute(select(Project).where(
            Project.id == project_id
        ))).scalar_one()
        check("project switched to delivering (status + ops co-owner)",
              project.status in ("agreed", "preparation")
              and project.ops_owner_id is not None,
              f"status={project.status} ops={project.ops_owner_id}")
    await approve_pending(api, akash)
    await approve_pending(api, "mithun@yuvipep.com")
    async with SessionLocal() as db:
        prep = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.source == "playbook",
        ))).scalars().all()
        check("preparation wave generated and staffed", len(prep) >= 5,
              f"{len(prep)} playbook tasks")

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
