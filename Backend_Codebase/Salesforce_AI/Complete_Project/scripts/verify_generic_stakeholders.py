"""Verification: stakeholder roles are GENERIC — any client type, no fixed list.

Scenario: Nexora Technologies, an IT company — nothing school-shaped. Its
people are a CTO, a Procurement Head and a Finance Controller; none of them
fits the old school vocabulary (principal/coordinator/accountant/...).

What must hold:
  A. First meeting → project; every contact becomes a stakeholder whose
     role_at_client is the CLIENT'S OWN vocabulary — never squashed to "other",
     never forced into school labels.
  B. Influence drives the engines, not role strings: the decision maker is
     found by influence; the invoice CC goes to the decision maker (the CTO,
     not any "principal"); the client chase targets the day-to-day contact.
  C. A human stays the approver: the plan and every client message pass the
     approval gate before anything goes out.
  D. People who surface in LATER meetings or messages are added by the AI
     itself (contact source=meeting + stakeholder row); humans only edit.
     A later reading that CONTRADICTS a recorded influence is reported,
     never silently applied.

Run LIVE (model classifies people from the meeting; uses the key in .env):
    python scripts/verify_generic_stakeholders.py
Run STUB (deterministic fallback: role = contact title, influence = primary):
    python scripts/verify_generic_stakeholders.py --stub
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

STUB = "--stub" in sys.argv
DB_PATH = PROJECT_ROOT / "data" / (
    "verify_generic_stakeholders_stub.db" if STUB else "verify_generic_stakeholders.db"
)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"
if STUB:
    os.environ["LLM_PROVIDER"] = "stub"

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []
SCHOOL_VOCAB = {"principal", "academic_coordinator", "trustee", "teacher"}


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}"
          + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


MEETING = """Meeting at Nexora Technologies' Whitefield office with Anita Rao
(their Chief Technology Officer), Vikram Shah (Procurement Head) and Divya
Nair (Finance Controller).

Nexora wants a 2-day hands-on Android development upskilling workshop for
about 40 of their junior engineers, at their office, in the last week of
August 2026. Anita Rao has the final say on the engagement and approved the
outline in the room. Vikram Shah handles vendor onboarding and will raise the
purchase order — he asked us to share our vendor registration documents within
a week. Divya Nair releases all payments once the PO is in place. Vikram will
be our day-to-day contact for logistics and scheduling.

They asked for a formal quotation; budget indicated around 3 lakh. We promised
to send the detailed course outline and the quotation within 5 days."""


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
                   json: dict | None = None, params: dict | None = None):
        token = await self.login(user)
        r = await self.client.request(
            method, path, json=json, params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings
    s = get_settings()
    if STUB:
        print("STUB run — deterministic fallback path (no model)\n")
    else:
        assert s.llm_provider != "stub" and (
            s.gemini_api_key or s.anthropic_api_key or s.openrouter_api_key
        ), "LIVE run needs a real LLM key in .env (or pass --stub)"
        print(f"LIVE run — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app
    from scripts.seed_workflows import seed

    await init_db()
    register_handlers()
    sync_engine.register()
    await seed()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1", timeout=300
    )
    api = Api(client)

    from app.models.action_item import ActionItem
    from app.models.lead import Contact
    from app.models.messaging import OutboundMessage
    from app.models.project import ActionPlan, Stakeholder
    from app.models.user import User

    rahul, akash = "rahul@yuvipep.com", "akash@yuvipep.com"

    # ── The corporate client ─────────────────────────────────────────────────
    lead = await api.call("POST", "/leads", user=rahul, json={
        "name": "Nexora Technologies", "city": "Bengaluru", "source": "referral",
    })
    lead_id = lead["id"]
    # `POST /leads` creates in `cold_calling` since pre-sales shipped, and a
    # meeting cannot be recorded against a lead nobody has phoned. This stands
    # in for the cold call.
    await api.call("PATCH", f"/leads/{lead_id}/state", user=rahul,
                   json={"state": "open", "reason": "cold call went well"})
    people = [
        ("Anita Rao", "Chief Technology Officer", "anita.rao@nexora.example", True),
        ("Vikram Shah", "Procurement Head", "vikram.shah@nexora.example", False),
        ("Divya Nair", "Finance Controller", "divya.nair@nexora.example", False),
    ]
    for name, title, email, primary in people:
        await api.call("POST", f"/leads/{lead_id}/contacts", user=rahul, json={
            "name": name, "title": title, "email": email, "is_primary": primary,
        })

    # ── A. First meeting → project + stakeholders in Nexora's vocabulary ────
    print("A. First meeting: corporate upskilling workshop")
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead_id, "title": "Nexora — first meeting",
        "text": MEETING, "meeting_type": "first_visit",
    })
    planner = res["planner"]
    if not check("project proposed", planner.get("action") == "project_proposed",
                 str(planner)):
        raise SystemExit(
            "No project was proposed (live free-tier rate limits can cause "
            "this — retry in a few minutes). Aborting cleanly."
        )
    project_id = planner["project_id"]

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Stakeholder, Contact)
            .join(Contact, Contact.id == Stakeholder.contact_id)
            .where(Stakeholder.project_id == project_id)
        )).all()
        by_name = {c.name: st for st, c in rows}
        print("     stakeholders: " + "; ".join(
            f"{c.name} → role={st.role_at_client}, influence={st.influence}, "
            f"updates={st.receives_progress_updates}" for st, c in rows
        ))
        check("all three contacts became stakeholders", len(rows) == 3,
              f"{len(rows)} rows")
        roles = {st.role_at_client for st, _ in rows}
        check("no school vocabulary was forced onto a company",
              not (roles & SCHOOL_VOCAB), str(roles))
        check("nobody was squashed to 'other' — the client's own vocabulary survives",
              "other" not in roles, str(roles))
        anita = by_name.get("Anita Rao")
        vikram = by_name.get("Vikram Shah")
        divya = by_name.get("Divya Nair")
        check("the CTO's role speaks Nexora's language",
              anita is not None and any(
                  k in (anita.role_at_client or "")
                  for k in ("cto", "chief", "technology")),
              anita.role_at_client if anita else "missing")
        check("the Procurement Head's role speaks Nexora's language",
              vikram is not None and "procure" in (vikram.role_at_client or ""),
              vikram.role_at_client if vikram else "missing")
        check("the Finance Controller's role speaks Nexora's language",
              divya is not None and any(
                  k in (divya.role_at_client or "")
                  for k in ("financ", "account", "control")),
              divya.role_at_client if divya else "missing")
        check("the CTO holds decision_maker (found by influence, not by title)",
              anita is not None and anita.influence == "decision_maker",
              anita.influence if anita else "missing")
        if not STUB:
            # Soft observations — the model's judgement, reported honestly.
            print(f"     model judged: Vikram influence={vikram.influence}, "
                  f"day-to-day={vikram.receives_progress_updates}; "
                  f"Divya influence={divya.influence}")

    # ── B. Human approver: the plan gate ─────────────────────────────────────
    print("B. Human approves plan v1 (the approver role)")
    approvals = await api.call("GET", "/approvals", user=akash)
    pending_plans = [a for a in approvals if a["status"] == "pending"
                     and a["entity_type"] == "plan_change"]
    check("plan waited for a human", len(pending_plans) >= 1)
    for a in pending_plans:
        await api.call("POST", f"/approvals/{a['id']}/decide", user=akash,
                       json={"approve": True})
    async with SessionLocal() as db:
        plan = (await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project_id, ActionPlan.version == 1
        ))).scalar_one()
        check("plan v1 active after the human's yes", plan.status == "active",
              plan.status)

    # Assignment confirmations (lead_confirm mode) so tasks go live — each
    # phase lead confirms their own batch.
    for lead_email in (akash, "mithun@yuvipep.com"):
        proposed = await api.call("GET", "/assignments/proposed", user=lead_email)
        if proposed:
            await api.call("POST", "/assignments/confirm-batch", user=lead_email,
                           json={"assignment_ids": [a["id"] for a in proposed]})

    # ── C. Client chase targets by generic fields, not role strings ──────────
    print("C. A task blocks on the client → chase goes to the right person")
    async with SessionLocal() as db:
        task = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.status.in_(("open", "in_progress")),
            ActionItem.assignee_id.isnot(None),
        ))).scalars().first()
        assignee_email = None
        if task is not None:
            assignee_email = (await db.execute(
                select(User.email).where(User.id == task.assignee_id)
            )).scalar_one_or_none()
    if check("an open staffed task exists to block", task is not None):
        await api.call("POST", f"/tasks/{task.id}/block", user=assignee_email,
                       json={"reason": "waiting for client approval of the outline"})
        async with SessionLocal() as db:
            chase = (await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.project_id == project_id,
                    OutboundMessage.triggered_by == "reminder_ladder",
                ).order_by(OutboundMessage.created_at.desc())
            )).scalars().first()
            if check("a client chase was drafted (pending approval, not auto-sent)",
                     chase is not None and chase.status == "pending_approval",
                     chase.status if chase else "no draft"):
                target = (await db.execute(select(Contact).where(
                    Contact.id == chase.contact_id
                ))).scalar_one_or_none()
                target_name = target.name if target else "?"
                print(f"     chase drafted to: {target_name}")
                check("chase target is one of Nexora's stakeholders",
                      target_name in {"Anita Rao", "Vikram Shah", "Divya Nair"},
                      target_name)
                if STUB:
                    check("stub fallback: chase goes to the decision maker (CTO)",
                          target_name == "Anita Rao", target_name)

    # ── E. A later meeting reveals a NEW person → the AI syncs them itself ──
    print("E. Second meeting introduces a new person (no human data entry)")
    if STUB:
        # The deterministic suite exercises the sync helper directly (the
        # stub merge path carries no people specs by design).
        from app.engines import planner_engine
        from app.models.project import Project as ProjectModel

        async with SessionLocal() as db:
            proj = (await db.execute(
                select(ProjectModel).where(ProjectModel.id == project_id)
            )).scalar_one()
            notes = await planner_engine.sync_stakeholder_specs(
                db, org_id=proj.org_id, project=proj,
                specs=[{"name": "Rohan Mehta", "role": "l_and_d_manager",
                        "influence": "influencer", "receives_updates": True}],
            )
            await db.commit()
            check("sync created the new person and reported it",
                  len(notes) == 2, str(notes))
            # Second reading with a DIFFERENT influence must not overwrite.
            notes2 = await planner_engine.sync_stakeholder_specs(
                db, org_id=proj.org_id, project=proj,
                specs=[{"name": "Rohan Mehta", "role": "l_and_d_manager",
                        "influence": "decision_maker", "receives_updates": False}],
            )
            await db.commit()
            check("a differing later reading is reported, never overwritten",
                  len(notes2) == 1 and notes2[0].startswith("Noted:"), str(notes2))
    else:
        await api.call("POST", "/meetings/notes", user=rahul, json={
            "lead_id": lead_id, "project_id": project_id,
            "title": "Nexora — logistics call",
            "meeting_type": "review",
            "text": "Quick call with Vikram Shah of Nexora Technologies. "
                    "He introduced Rohan Mehta, their L&D Manager, who will "
                    "own the training calendar and coordinate the workshop "
                    "day-to-day from their side going forward. Everything "
                    "else stays as agreed.",
        })
    async with SessionLocal() as db:
        rohan_contact = (await db.execute(select(Contact).where(
            Contact.lead_id == lead_id, Contact.name.like("%Rohan%")
        ))).scalars().first()
        if check("Rohan Mehta exists as a contact created by the AI",
                 rohan_contact is not None and rohan_contact.source == "meeting",
                 rohan_contact.source if rohan_contact else "missing"):
            rohan_st = (await db.execute(select(Stakeholder).where(
                Stakeholder.project_id == project_id,
                Stakeholder.contact_id == rohan_contact.id,
            ))).scalars().first()
            check("…and as a stakeholder in Nexora's own vocabulary",
                  rohan_st is not None and rohan_st.role_at_client not in (None, "other")
                  and rohan_st.role_at_client not in SCHOOL_VOCAB,
                  rohan_st.role_at_client if rohan_st else "missing")
            print(f"     Rohan → role={rohan_st.role_at_client}, "
                  f"influence={rohan_st.influence}, "
                  f"updates={rohan_st.receives_progress_updates}"
                  if rohan_st else "     Rohan stakeholder missing")

    # ── D. Invoice: CC found by influence — the CTO, no 'principal' anywhere ─
    print("D. Invoice send: money mail CC'd to the decision maker by influence")
    async with SessionLocal() as db:
        divya_st = (await db.execute(
            select(Stakeholder)
            .join(Contact, Contact.id == Stakeholder.contact_id)
            .where(Stakeholder.project_id == project_id,
                   Contact.name == "Divya Nair")
        )).scalars().first()
    invoice = await api.call("POST", "/invoices", user=akash, json={
        "project_id": project_id, "kind": "advance",
        "sent_to_stakeholder_id": divya_st.id,
    })
    await api.call("POST", f"/invoices/{invoice['id']}/send", user=akash)
    async with SessionLocal() as db:
        msg = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.project_id == project_id,
            OutboundMessage.kind == "invoice",
        ).order_by(OutboundMessage.created_at.desc()))).scalars().first()
        if check("invoice message drafted for approval", msg is not None):
            check("addressed to the payments person (Finance Controller)",
                  msg.to_address == "divya.nair@nexora.example", msg.to_address)
            check("CC'd to the decision maker (the CTO) — resolved by influence",
                  msg.cc == ["anita.rao@nexora.example"], str(msg.cc))

    await client.aclose()

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{'='*68}\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed"
          + (f" — {len(failed)} FAILED" if failed else ""))
    for desc, _, detail in failed:
        print(f"  FAILED: {desc}  ({detail})")
    sys.exit(1 if failed else 0)


async def _run() -> None:
    try:
        await main()
    finally:
        # aiosqlite's threads are non-daemon: without disposing the engine this
        # process keeps running AFTER the results have printed (observed
        # 2026-07-22 — an 11-minute "hang" that was really a finished run that
        # would not exit, and which also holds a lock on its own DB file so the
        # next run dies with PermissionError [WinError 32]).
        from app.database import engine

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
