"""Live proof the machinery is topic-generic: a startup INCUBATION CENTRE
engagement — nothing to do with syllabi, bootcamps or teaching.

Continues the database of verify_generic_planner.py.

  1. First meeting → LLM-authored plan for the centre build+operate scope
     (fit-out, mentor network, founding startups, trust reporting).
  2. Content change ask ("mentor programme too corporate") → revision task
     whose required_skill is PICKED from the org taxonomy by the model,
     not hardcoded to curriculum_design.
  3. Scope expansion ("add a second floor: 3 labs, 40 seats") → the
     expansion task wave is AUTHORED by the model from this project's
     objective — the old hardcoded kits/batches template must not appear.

Run:  python scripts/verify_live_offdomain.py
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

TEMPLATE_TITLES = {
    "order additional kits", "recompute batch schedule for expanded scope",
    "prepare day-wise syllabus", "build draft proposal with pricing",
}

MEETING = """Meeting with Mr. Kejriwal (Director) of TechNest Ventures at their
Rajarhat innovation park. They want us to SET UP AND OPERATE a startup
incubation centre on the 3rd floor (6000 sq ft):
- Fit out the floor: co-working area for 60 seats, 4 incubation labs, one
  event space. Their contractor does civil work; we give the layout and
  the networking/electrical requirement sheet within two weeks.
- We procure and install furniture, high-speed internet, access control and
  a small server room.
- We design the incubation programme: mentor network, weekly founder
  sessions, quarterly demo days.
- We recruit and train two centre managers who will run it day to day.
- Ten founding startups must be signed before the centre opens in March 2027.
- A monthly progress report goes to their investment trust.
Budget indicated around 40 lakh; they want our formal quotation."""


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_generic_planner.py first."

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE off-domain run (incubation centre) — provider={s.llm_provider}\n")

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

    def check(desc: str, ok: bool, detail: str = "") -> bool:
        CHECKS.append((desc, bool(ok), detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail and not ok else ""))
        return bool(ok)

    from app.models.action_item import ActionItem
    from app.models.project import ActionPlan, ClientCommitment

    rahul, akash, ananya = "rahul@yuvipep.com", "akash@yuvipep.com", "ananya@yuvipep.com"

    lead = await call("POST", "/leads", user=rahul, json={
        "name": "TechNest Ventures", "city": "Kolkata", "source": "referral",
    })
    # `POST /leads` creates in `cold_calling` since pre-sales shipped, and a
    # meeting cannot be recorded against a lead nobody has phoned. This stands
    # in for the cold call.
    await call("PATCH", f"/leads/{lead['id']}/state", user=rahul,
               json={"state": "open", "reason": "cold call went well"})
    await call("POST", f"/leads/{lead['id']}/contacts", user=rahul, json={
        "name": "Mr. Kejriwal", "title": "Director",
        "email": "director@technest.example", "is_primary": True,
    })

    # 1. The plan is born from the meeting — any topic.
    print("1. First meeting: incubation centre build + operate")
    res = await call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead["id"], "title": "TechNest incubation centre — first meeting",
        "text": MEETING, "meeting_type": "first_visit",
    })
    planner = res["planner"]
    if not check("project proposed", planner.get("action") == "project_proposed",
                 str(planner)):
        raise SystemExit("Plan birth failed (likely rate limits) — aborting cleanly.")
    project_id = planner["project_id"]

    async with SessionLocal() as db:
        tasks = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id
        ))).scalars().all()
        commitments = (await db.execute(select(ClientCommitment).where(
            ClientCommitment.project_id == project_id
        ))).scalars().all()
    titles = [t.title for t in tasks]
    print("     tasks: " + " | ".join(titles))
    check("healthy plan (5–30 tasks)", 5 <= len(tasks) <= 30, f"{len(tasks)}")
    blob = " ".join(titles).lower()
    check("plan covers the actual scope (fit-out/mentors/startups/managers…)",
          sum(kw in blob for kw in
              ("layout", "fit", "mentor", "startup", "manager", "recruit",
               "server", "network", "report", "furniture")) >= 4, blob[:300])
    check("no education-template titles",
          not any(t.lower() in TEMPLATE_TITLES for t in titles), str(titles))
    check("commitments captured (layout sheet ours, etc.)", len(commitments) >= 1,
          f"{len(commitments)}")
    for a in await call("GET", "/approvals", user=akash):
        if a["status"] == "pending":
            await call("POST", f"/approvals/{a['id']}/decide", user=akash,
                       json={"approve": True})

    # 2. Content change: the skill is judged, not hardcoded.
    print("2. Content change: 'mentor programme too corporate'")
    resp = await call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "director@technest.example",
        "subject": "Re: incubation programme design",
        "body": "The incubation programme design feels too corporate. Please "
                "redesign the weekly sessions to be founder-led, and add a "
                "legal-basics clinic for the startups.",
    })
    async with SessionLocal() as db:
        revision = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.title.like("Revise content%"),
        ))).scalars().first()
    check("revision task created for the programme redesign", revision is not None,
          f"intent={resp['intent']} points={resp.get('extracted_points')}")
    if revision:
        print(f"     required_skill judged by the model: {revision.required_skill!r}")

    # 3. Scope grows: the expansion wave is authored, not templated.
    print("3. Scope expansion: 'second floor — 3 more labs, 40 more seats'")
    plans_before = 0
    async with SessionLocal() as db:
        plans_before = len((await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project_id
        ))).scalars().all())
    resp2 = await call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "director@technest.example",
        "subject": "Second floor",
        "body": "Good progress. The trust has approved expanding the centre to "
                "the 4th floor as well — please add three more incubation labs "
                "and forty more co-working seats to the scope.",
    })
    async with SessionLocal() as db:
        plans = (await db.execute(select(ActionPlan).where(
            ActionPlan.project_id == project_id
        ))).scalars().all()
        newest = max(plans, key=lambda p: p.version)
        expansion = (await db.execute(select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.plan_version_added == newest.version,
        ))).scalars().all()
    check("scope change produced a new plan version",
          len(plans) > plans_before and newest.trigger == "client_reply",
          f"v{newest.version} trigger={newest.trigger} intent={resp2['intent']}")
    exp_titles = [t.title for t in expansion]
    print("     expansion tasks: " + " | ".join(exp_titles))
    check("expansion wave authored for THIS project (≥2 tasks)",
          len(expansion) >= 2, f"{len(expansion)} tasks")
    check("no bootcamp-template task in the wave",
          not any(t.lower() in TEMPLATE_TITLES for t in exp_titles), str(exp_titles))

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
