"""Live verification of the GENERIC (LLM-native) planner — real Gemini calls.

Proves the four pillars of the generic product on a topic that shares nothing
with the old template vocabulary (no syllabus, no proposal, no demo):

  A. First meeting on ANY topic  → project + LLM-authored plan v1
     (tasks, phases, skills, dependencies, commitments), approval-gated,
     deterministically staffed.
  B. Contradicting follow-up      → the merge raises a CONFLICT and holds
     the re-plan; nobody's side is picked.
  C. Date-shift follow-up         → the merge emits redate/set_window ops,
     applied only at activation.
  D. Vague chat                   → no project; follow-ups only.

Run:  python scripts/verify_generic_planner.py   (uses the key in .env)
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
# LLM_PROVIDER / GEMINI_API_KEY come from .env — this run is LIVE.

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


# The old hardcoded template — the plan must NOT be this.
TEMPLATE_TITLES = {
    "prepare day-wise syllabus", "build draft proposal with pricing",
    "schedule teacher demo session", "check trainer availability",
    "send thank-you + summary email",
}

MEETING_A = """Meeting with Dr. Kapoor (Director) and Mr. Bose (Estate Manager) of
Horizon International School, Salt Lake campus.

They do not want a training program. They want us to DESIGN, BUILD AND HAND
OVER a permanent Robotics & 3D-Printing Innovation Lab in the junior building.
Scope discussed and agreed in the room:
- Convert the old library room (40ft x 25ft) — civil work is theirs, but we
  must give them a floor layout and electrical load sheet within 10 days.
- We procure and install 8 3D printers, 20 robotics kits and 2 laser cutters.
  Dr. Kapoor insisted every machine must clear an electrical safety audit
  before any student touches it.
- We must train 6 of their teachers to run the lab independently — Dr. Kapoor
  wants the teacher certification finished before the lab opens.
- Grand inauguration event on 20 September 2026 with the school trust
  present; we handle the event run-sheet and a live student showcase.
- Mr. Bose promised to share the room's wiring diagram within a week.
- Budget mentioned around 18 lakh but they want our formal quotation.
They asked for a single point of contact from our side for the whole build."""

MEETING_B = """Quick call with Mr. Bose (Estate Manager), Horizon International School.
He says the trust has decided the inauguration must be a quiet internal affair —
NO grand event, no trust members, no student showcase; just a ribbon cut by the
Director. He was clear this comes from the trust chairman himself.
(Note: Dr. Kapoor's office separately re-confirmed the grand showcase plan in
writing yesterday — these two instructions cannot both be right.)"""

MEETING_C = """Meeting with Dr. Kapoor, Horizon International School.
The junior building renovation is running late, so everything moves: the lab
handover and inauguration shift from 20 September 2026 to 15 October 2026.
She also asked us to add one thing: a monthly maintenance visit for the first
three months after handover. Everything else stays exactly as agreed."""

MEETING_D = """Bumped into the librarian of Horizon International School at a
book fair. Pure hello-hello, nothing specific discussed, no concrete asks —
she just said the Director may call us sometime."""


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

    async def call(self, method: str, path: str, *, user: str, json: dict | None = None,
                   params: dict | None = None):
        token = await self.login(user)
        r = await self.client.request(method, path, json=json, params=params,
                                      headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub" and (s.gemini_api_key or s.anthropic_api_key), \
        "This verification needs a real LLM key in .env"
    strong = {
        "claude": s.claude_model_strong,
        "openrouter": s.openrouter_model_strong,
    }.get(s.llm_provider, s.llm_model_strong)
    print(f"LIVE run — provider={s.llm_provider}, strong={strong}\n")

    from app.database import init_db, engine
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app
    from scripts.seed_workflows import seed

    await init_db()
    register_handlers()
    sync_engine.register()
    await seed()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=300)
    api = Api(client)

    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.followup import FollowUp
    from app.models.lead import Lead
    from app.models.project import ActionPlan, ClientCommitment, Conflict, Project

    rahul, akash = "rahul@yuvipep.com", "akash@yuvipep.com"

    # A dedicated lead so old seed data can't help the model.
    lead = await api.call("POST", "/leads", user=rahul, json={
        "name": "Horizon International School",
        "city": "Kolkata", "source": "referral",
    })
    lead_id = lead["id"]
    # `POST /leads` creates in `cold_calling` since pre-sales shipped, and a
    # meeting cannot be recorded against a lead nobody has phoned. This stands
    # in for the cold call.
    await api.call("PATCH", f"/leads/{lead_id}/state", user=rahul,
                   json={"state": "open", "reason": "cold call went well"})
    await api.call("POST", f"/leads/{lead_id}/contacts", user=rahul, json={
        "name": "Dr. Kapoor", "title": "Principal",
        "email": "director@horizonintl.example", "is_primary": True,
    })

    # ── A. Off-domain first meeting → generic plan ───────────────────────────
    print("A. First meeting: robotics innovation lab (nothing like the old template)")
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead_id, "title": "Horizon lab build — first meeting",
        "text": MEETING_A, "meeting_type": "first_visit",
    })
    planner = res["planner"]
    if not check("project proposed", planner.get("action") == "project_proposed",
                 str(planner)):
        raise SystemExit(
            "Scenario A did not produce a project (likely free-tier "
            "rate/quota limits — retry in a few minutes). Aborting cleanly."
        )
    project_id = planner.get("project_id")

    async with SessionLocal() as db:
        tasks = (await db.execute(
            select(ActionItem).where(ActionItem.project_id == project_id)
        )).scalars().all()
        project = (await db.execute(
            select(Project).where(Project.id == project_id)
        )).scalar_one()
        commitments = (await db.execute(
            select(ClientCommitment).where(ClientCommitment.project_id == project_id)
        )).scalars().all()

        check("plan has a healthy number of tasks (5–30)", 5 <= len(tasks) <= 30,
              f"{len(tasks)} tasks")
        titles = [t.title for t in tasks]
        print("     tasks: " + " | ".join(titles))
        check("ZERO template titles used",
              not any(t.lower() in TEMPLATE_TITLES for t in titles), str(titles))
        blob = " ".join(titles).lower()
        check("plan covers the actual scope (printers/safety/teachers/inauguration…)",
              sum(kw in blob for kw in
                  ("printer", "3d", "robot", "safety", "audit", "teacher",
                   "inaugur", "layout", "electrical", "quotation", "kit",
                   "laser", "maintenance", "install")) >= 4, blob[:300])
        check("dependencies were wired", any(t.depends_on_ids for t in tasks))
        check("every task has a required_skill", all(t.required_skill for t in tasks))
        check("commitments captured (≥2: load sheet ours, wiring diagram theirs…)",
              len(commitments) >= 2, f"{len(commitments)}: {[c.text for c in commitments]}")
        check("objective is factual and reusable",
              project.objective and ("lab" in project.objective.lower()
                                     or "robot" in project.objective.lower()),
              project.objective or "—")

    # Approve plan v1 → activation staffs it deterministically.
    approvals = await api.call("GET", "/approvals", user=akash)
    plan_approvals = [a for a in approvals if a["status"] == "pending"
                      and a["entity_type"] == "plan_change"]
    check("plan v1 went through the approval gate", len(plan_approvals) >= 1)
    for a in plan_approvals:
        await api.call("POST", f"/approvals/{a['id']}/decide", user=akash,
                       json={"approve": True})
    async with SessionLocal() as db:
        plan = (await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project_id, ActionPlan.version == 1
        ))).scalar_one()
        check("plan v1 ACTIVE after approval", plan.status == "active", plan.status)
        open_tasks = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id, ActionItem.status.in_(("open", "in_progress"))
        ))).scalars().all()
        staffed = [t for t in open_tasks if t.assignee_id]
        check("tasks staffed by the deterministic engine, with written reasons",
              staffed and all(t.assignment_reason for t in staffed),
              f"{len(staffed)}/{len(open_tasks)} staffed")
        from app.models.work import AIDecision

        gap_rows = (await db.execute(select(AIDecision).where(
            AIDecision.decision.like("Skill gap:%")
        ))).scalars().all()
        print(f"     skill-gap decisions recorded: {len(gap_rows)}"
              + (f" — {gap_rows[0].decision}" if gap_rows else ""))

    # ── B. Contradiction → conflict, plan held ───────────────────────────────
    print("B. Contradicting instruction (trust vs Director on the inauguration)")
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead_id, "title": "Bose call — inauguration",
        "text": MEETING_B, "meeting_type": "review", "project_id": project_id,
    })
    planner = res["planner"]
    check("merge held by conflict", planner.get("action") == "held_by_conflict", str(planner))
    async with SessionLocal() as db:
        conflicts = (await db.execute(select(Conflict).where(
            Conflict.project_id == project_id, Conflict.status == "open"
        ))).scalars().all()
        check("open conflict row exists, naming both sides", len(conflicts) >= 1)
        if conflicts:
            print(f"     conflict: {conflicts[0].description[:180]}")
            held = (await db.execute(select(ActionPlan).where(
                ActionPlan.id == conflicts[0].held_plan_id
            ))).scalar_one_or_none()
            check("the re-plan is held as draft (no side applied)",
                  held is not None and held.status == "draft",
                  held.status if held else "no held plan")
        # Resolve so scenario C starts clean.
        for c in conflicts:
            await api.call("POST", f"/projects/{project_id}/conflicts/{c.id}/resolve",
                           user=akash,
                           json={"resolution_note":
                                 "Director confirmed with the trust: grand showcase stays."})
    for a in await api.call("GET", "/approvals", user=akash):
        if a["status"] == "pending" and a["entity_type"] == "plan_change":
            await api.call("POST", f"/approvals/{a['id']}/decide", user=akash,
                           json={"approve": True})

    # ── C. Date shift → redate/set_window ops at activation ─────────────────
    print("C. Date shift (20 Sep → 15 Oct) + small scope add")
    async with SessionLocal() as db:
        before = {t.id: t.due_date for t in (await db.execute(
            select(ActionItem).where(ActionItem.project_id == project_id)
        )).scalars().all()}
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead_id, "title": "Kapoor — reschedule",
        "text": MEETING_C, "meeting_type": "review", "project_id": project_id,
    })
    planner = res["planner"]
    check("merge produced a new plan version", planner.get("action") == "plan_merged",
          str(planner))
    async with SessionLocal() as db:
        newest = (await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project_id
        ).order_by(ActionPlan.version.desc()))).scalars().first()
        ops = newest.pending_ops or []
        check("diff carries date ops (redate/set_window)",
              any(op.get("op") in ("redate", "set_window") for op in ops),
              str(ops)[:300])
        check("diff is written for humans", bool(newest.changes_from_previous),
              newest.changes_from_previous or "—")
        print(f"     diff: {(newest.changes_from_previous or '')[:220]}")
    for a in await api.call("GET", "/approvals", user=akash):
        if a["status"] == "pending" and a["entity_type"] == "plan_change":
            await api.call("POST", f"/approvals/{a['id']}/decide", user=akash,
                           json={"approve": True})
    async with SessionLocal() as db:
        project = (await db.execute(select(Project).where(
            Project.id == project_id
        ))).scalar_one()
        after = {t.id: t.due_date for t in (await db.execute(
            select(ActionItem).where(ActionItem.project_id == project_id)
        )).scalars().all()}
        moved = [i for i in before if before[i] and after.get(i) and before[i] != after[i]]
        window_moved = (
            project.target_end_date and project.target_end_date.month == 10
        ) or (project.start_date and project.start_date.month == 10)
        check("dates actually moved after activation (tasks or window)",
              bool(moved) or bool(window_moved),
              f"{len(moved)} task dates moved; window={project.start_date}"
              f"→{project.target_end_date}")

    # ── D. Vague chat → no project ───────────────────────────────────────────
    print("D. Vague hallway chat → follow-ups only")
    lead2 = await api.call("POST", "/leads", user=rahul, json={
        "name": "Meadowbrook Academy", "city": "Kolkata", "source": "event",
    })
    await api.call("PATCH", f"/leads/{lead2['id']}/state", user=rahul,
                   json={"state": "open", "reason": "cold call went well"})
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead2["id"], "title": "book fair chat",
        "text": MEETING_D, "meeting_type": "first_visit",
    })
    check("no project born from small talk",
          res["planner"].get("action") == "followups_only", str(res["planner"]))
    async with SessionLocal() as db:
        fups = (await db.execute(select(FollowUp).where(
            FollowUp.lead_id == lead2["id"]
        ))).scalars().all()
        check("a follow-up was created instead", len(fups) >= 1)

    await client.aclose()
    await engine.dispose()

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
        # Always drop DB connections — lingering aiosqlite threads are
        # non-daemon and would keep a crashed run alive forever, holding
        # the database file lock.
        from app.database import engine

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
