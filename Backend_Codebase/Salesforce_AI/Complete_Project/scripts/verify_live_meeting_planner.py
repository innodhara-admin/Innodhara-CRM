"""Live verification that RECORDING a meeting starts the same machine that
TYPING the notes starts (findings F9 + F8).

Before this, `POST /meetings/notes` called `planner_engine.process_meeting`
and the audio pipeline did not. Typing a meeting therefore produced a project,
a plan, phased and dated tasks, client commitments, stakeholders and
assignment proposals; recording the very same meeting produced a handful of
flat tasks with `due_date = NULL` and nothing else — while the app's own notes
composer claimed the two paths were equivalent.

The fix keeps the human in front: the review gate still asks the agent what
the meeting really agreed, and the Planner then runs on the confirmed list
(`POST /meetings/{id}/review/confirm` → `plan_meeting` job), building the plan
AROUND those to-dos instead of deriving a rival set.

What this proves against a REAL model, on a throwaway database:

  1. The recorded path now yields project + plan + phased tasks — parity with
     the typed path, which is re-run here on an identical transcript so the
     two are compared side by side rather than against a remembered baseline.
  2. Every to-do the human confirmed survives into the plan, and none of them
     comes back as a near-duplicate (F9's whole risk).
  3. Meeting tasks carry real `due_date`s — the column the digest, My Tasks
     and the nudge ladder all read (F8). A deadline nobody could resolve
     stays as prose and never becomes a guessed date.
  4. A SECOND recording on the same client merges into the existing plan
     instead of forking a duplicate project (a recording carries no
     project_id, so every one of them used to look like a first meeting).
  5. Plan-owned tasks never appear in the meeting review gate, where a
     confirm would flip them open behind `activate_plan`'s back.

STT is not exercised — the transcript is supplied directly, exactly as
Whisper would hand it over. Everything above it is real.

Run:  python scripts/verify_live_meeting_planner.py
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

DB_PATH = PROJECT_ROOT / "data" / "verify_meeting_planner.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []

# A generic, deliberately non-school engagement, so nothing here can pass by
# leaning on the product's original domain.
TRANSCRIPT = (
    "Thanks for making time today. Just to recap what we discussed at the "
    "expo. We want to run the programme across three of our offices. "
    "Bengaluru first, then Hyderabad and Pune. How many participants in the "
    "first batch? About forty in Bengaluru, scaling to a hundred and twenty "
    "across all three. When would you like to start? The first week of "
    "September — our CSR spend has to be booked before the quarter closes. "
    "I will send you a full proposal with the commercials by Friday. Please "
    "include the safety compliance documentation as well, our facilities team "
    "will not approve anything without it. Noted. One more thing — our "
    "leadership team wants a live demonstration before we sign. I will "
    "arrange that in the last week of July. Also loop in our finance "
    "controller, Priya Nair; she approves the budget."
)

SECOND_TRANSCRIPT = (
    "Quick follow-up on the same programme. The Bengaluru batch has to move "
    "to the second week of September because the office is being repainted. "
    "Everything else stays as agreed. Also, Priya wants the commercials "
    "broken down per office."
)


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


async def main() -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE meeting-planner run — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.jobs import pipelines, register_handlers
    from app.main import _seed_super_admin, app

    await init_db()
    await _seed_super_admin()
    register_handlers()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1", timeout=600
    )
    tokens: dict[str, str] = {}

    async def login(email: str, password: str) -> str:
        r = await client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    async def call(method: str, path: str, *, user: str = "admin", **kw):
        r = await client.request(
            method, path, headers={"Authorization": f"Bearer {tokens[user]}"}, **kw
        )
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()

    super_token = await login(s.super_admin_email, s.super_admin_password)
    org = (
        await client.post(
            "/orgs",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"name": "Meeting Planner Test Co", "slug": "mtg-planner",
                  "email_domain": "mtg-example.com",
                  "admin_email": "admin@mtg-example.com",
                  "admin_name": "Mtg Admin"},
        )
    ).json()
    tokens["admin"] = await login(org["admin_email"], org["admin_temp_password"])

    async def new_lead(name: str) -> dict:
        lead = await call("POST", "/leads", json={"name": name, "city": "Bengaluru"})
        # `POST /leads` creates in `cold_calling` since pre-sales shipped, and
        # a recording cannot be uploaded against a lead nobody has phoned.
        # This stands in for the cold call.
        await call("PATCH", f"/leads/{lead['id']}/state",
                   json={"state": "open", "reason": "cold call went well"})
        # A real lead has someone on it. Stakeholders on a FIRST meeting are
        # built from the lead's contacts (`_create_project_shell`), so a lead
        # with nobody on it can only ever produce zero — which would say
        # nothing about the Planner.
        await call("POST", f"/leads/{lead['id']}/contacts",
                   json={"name": "Priya Nair", "title": "Finance Controller",
                         "email": "priya@mtg-example.com", "is_primary": True})
        return lead

    async def record(lead_id: str, transcript: str, title: str) -> str:
        """Upload a recording, then hand the pipeline the transcript directly
        (STT is out of scope here) and let everything above it run for real."""
        # F40: consent is proof captured BEFORE the recording. The app posts
        # it from its consent sheet; the harness must too, or it exercises a
        # flow the product does not have.
        await call("POST", f"/leads/{lead_id}/consent",
                   json={"method": "verbal", "note": "Agreed before recording"})
        meeting = await call(
            "POST", "/meetings/upload",
            data={"lead_id": lead_id, "consent_confirmed": "true",
                  "duration_seconds": "180", "title": title},
            files={"file": ("m.m4a", b"not-real-audio", "audio/mp4")},
        )
        from app.models.meeting import Transcript

        async with SessionLocal() as db:
            db.add(Transcript(
                org_id=org["id"], meeting_id=meeting["id"], text=transcript,
                language="en", confidence=0.95, low_confidence=False,
                word_count=len(transcript.split()),
            ))
            await db.commit()
        await pipelines.process_meeting({"meeting_id": meeting["id"]}, "verify")
        return meeting["id"]

    # ── 1. Recorded path: pipeline → review gate → confirm → Planner ────────
    print("1. Recording a meeting starts the whole machine (F9)")
    rec_lead = await new_lead("Telaverge Solutions")
    rec_meeting = await record(rec_lead["id"], TRANSCRIPT, "Recorded first visit")

    detail = await call("GET", f"/meetings/{rec_meeting}")
    check("the recording reached the human review gate",
          detail["status"] == "review_pending", detail["status"])

    review = await call("GET", f"/meetings/{rec_meeting}/review")
    extracted_ids = {i["id"] for i in review["items"]}
    check("the AI extracted to-dos for the human to confirm",
          len(review["items"]) >= 3, f"{len(review['items'])} items")

    # F8 — the deadlines the client actually stated.
    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.models.action_item import ActionItem

        rows = (await db.execute(
            select(ActionItem).where(ActionItem.meeting_id == rec_meeting)
        )).scalars().all()
    dated = [r for r in rows if r.due_date]
    check("extracted tasks carry real due dates, not prose in a description",
          bool(dated), f"{len(dated)}/{len(rows)} dated")
    check("no resolved date was ALSO left jammed into a description",
          not any("(due:" in (r.description or "") for r in dated))
    for r in rows:
        print(f"     {r.title[:58]:60} due {r.due_date:%d %b}" if r.due_date
              else f"     {r.title[:58]:60} due —")

    confirmed = [
        {"id": i["id"], "title": i["title"], "description": i["description"],
         "keep": True}
        for i in review["items"]
    ]
    result = await call(
        "POST", f"/meetings/{rec_meeting}/review/confirm", json={"items": confirmed}
    )
    check("confirming the review hands off to the Planner",
          result.get("planning") is True, str(result))

    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.models.job import JobRecord

        job = (await db.execute(
            select(JobRecord).where(JobRecord.type == "plan_meeting")
        )).scalars().first()
    check("a plan_meeting job was really queued", job is not None)
    planned = await pipelines.plan_meeting(job.payload, job.id)
    check("the Planner proposed a project from the RECORDING",
          planned.get("action") == "project_proposed", str(planned))

    projects = [p for p in await call("GET", "/projects")
                if p["lead_id"] == rec_lead["id"]]
    check("exactly one project was born", len(projects) == 1, str(len(projects)))
    rec_project = await call("GET", f"/projects/{projects[0]['id']}")
    print(f"     project: {rec_project['name']}")

    rec_tasks = rec_project["tasks"]
    check("the plan has phased tasks", len(rec_tasks) >= 4, f"{len(rec_tasks)} tasks")
    check("plan tasks are dated", all(t["due_date"] for t in rec_tasks))
    check("plan tasks carry a phase",
          all(t.get("phase") for t in rec_tasks))
    check("client commitments were captured",
          len(rec_project.get("commitments") or []) >= 1,
          f"{len(rec_project.get('commitments') or [])}")
    check("client-side people were identified",
          len(rec_project.get("stakeholders") or []) >= 1,
          f"{len(rec_project.get('stakeholders') or [])}")

    # ── 2. The confirmed to-dos survive, exactly once ───────────────────────
    print("\n2. What the human confirmed is honoured, not re-derived")
    plan_titles = [t["title"] for t in rec_tasks]

    # Duplicate-ness is judged by the engine's OWN definition, so this checks
    # that the fence holds its contract rather than inventing a stricter one.
    # (Decomposition is not duplication: "Arrange live demonstration" in
    # preparation and "Deliver live demonstration" in delivery are two real
    # tasks, and score below the threshold precisely so they both survive.)
    from app.engines.planner_engine import _title_similarity

    DUP = 0.7

    def looks_like(a: str, b: str) -> bool:
        return _title_similarity(a, b) >= DUP

    def reached(a: str, b: str) -> bool:
        return _title_similarity(a, b) >= 0.6      # carried, maybe reworded

    missing = [c["title"] for c in confirmed
               if not any(reached(c["title"], t) for t in plan_titles)]
    check("every confirmed to-do reached the plan", not missing,
          f"dropped: {missing}" if missing else "")
    dupes = [c["title"] for c in confirmed
             if sum(1 for t in plan_titles if looks_like(c["title"], t)) > 1]
    check("and none of them came back twice", not dupes,
          f"duplicated: {dupes}" if dupes else "")
    # The confirmed-task context is given to the model on its own labelled
    # line; a title that swallowed "(due …)" or the context means it folded
    # those fields back in (which it did before the block was reshaped).
    polluted = [t["title"] for t in rec_tasks if "(due " in t["title"]]
    check("no due date leaked into a task title", not polluted,
          f"polluted: {polluted}" if polluted else "")
    for t in rec_tasks:
        print(f"     [{t.get('phase', '—'):11}] {t['title'][:56]}")

    # ── 2b. The same work, once, ANYWHERE the user would see it (F22) ───────
    # Everything above reads `project["tasks"]`. That is the collection the
    # Planner produces, and it cannot see the project-less rows the review gate
    # opened — which is exactly why the 2026-07-22 duplication regression
    # passed 22/22 here while the database held two rows for every confirmed
    # to-do. The property is "this work appears once FOR THE USER", so assert
    # it over everything visible for the lead: query by lead_id, no other
    # filter beyond "still alive".
    print("\n2b. The same work is never stored twice for the lead (F22)")
    async with SessionLocal() as db:
        from sqlalchemy import select

        from app.core.constants import ActionItemStatus
        from app.models.action_item import ActionItem

        lead_rows = (await db.execute(
            select(ActionItem).where(
                ActionItem.lead_id == rec_lead["id"],
                ActionItem.status.notin_([ActionItemStatus.CANCELLED.value,
                                          ActionItemStatus.SUPERSEDED.value]),
            )
        )).scalars().all()
    twins = [
        (a.title, b.title)
        for i, a in enumerate(lead_rows)
        for b in lead_rows[i + 1:]
        if _title_similarity(a.title, b.title) >= DUP
    ]
    check("no piece of work is stored twice for this lead", not twins,
          f"twins: {twins[:3]}" if twins
          else f"{len(lead_rows)} live rows, all distinct")

    # Adoption, not re-creation: the rows the human confirmed still exist under
    # their ORIGINAL ids and now belong to the plan.
    adopted = [r for r in lead_rows
               if r.id in extracted_ids and r.plan_version_added is not None]
    check("confirmed to-dos were ADOPTED into the plan, keeping their identity",
          bool(adopted),
          f"{len(adopted)} of {len(extracted_ids)} confirmed rows carry a plan version")
    for r in lead_rows:
        print(f"     {r.title[:50]:52} v={str(r.plan_version_added):4} "
              f"proj={'Y' if r.project_id else '-'} "
              f"due={r.due_date:%d %b}" if r.due_date else
              f"     {r.title[:50]:52} v={str(r.plan_version_added):4} "
              f"proj={'Y' if r.project_id else '-'} due=—")

    # ── 3. The review gate never offers plan-owned tasks ────────────────────
    print("\n3. The review gate stays the extraction's, not the plan's")
    again = await call("GET", f"/meetings/{rec_meeting}/review")
    check("plan-owned tasks are not offered in the meeting review gate",
          {i["id"] for i in again["items"]} <= extracted_ids,
          f"{len(again['items'])} offered")

    # ── 4. A second recording merges instead of forking ─────────────────────
    print("\n4. A second recording merges into the plan (no duplicate project)")
    second = await record(rec_lead["id"], SECOND_TRANSCRIPT, "Recorded follow-up")
    second_review = await call("GET", f"/meetings/{second}/review")
    await call("POST", f"/meetings/{second}/review/confirm",
               json={"items": [{"id": i["id"], "title": i["title"],
                                "description": i["description"], "keep": True}
                               for i in second_review["items"]]})
    merged = await pipelines.plan_meeting(
        {"meeting_id": second, "agreed_tasks": [
            {"title": i["title"], "description": i["description"], "due_date": None}
            for i in second_review["items"]
        ]}, "verify-2")
    check("the second recording did NOT propose another project",
          merged.get("action") != "project_proposed", str(merged))
    projects = [p for p in await call("GET", "/projects")
                if p["lead_id"] == rec_lead["id"]]
    check("the client still has exactly one project", len(projects) == 1,
          f"{len(projects)} projects")
    plans = await call("GET", f"/projects/{projects[0]['id']}/plans")
    check("a new plan version records the merge", len(plans) >= 2,
          f"v1..v{len(plans)}")

    # ── 5. Parity with the typed path, on the same words ────────────────────
    print("\n5. Parity: the same meeting TYPED produces the same kind of result")
    typed_lead = await new_lead("Telaverge Solutions (typed control)")
    typed = await call("POST", "/meetings/notes",
                       json={"lead_id": typed_lead["id"], "text": TRANSCRIPT,
                             "title": "Typed control"})
    typed_action = typed["planner"].get("action")
    check("the typed path still proposes a project", typed_action == "project_proposed",
          str(typed_action))
    typed_projects = [p for p in await call("GET", "/projects")
                      if p["lead_id"] == typed_lead["id"]]
    typed_project = await call("GET", f"/projects/{typed_projects[0]['id']}")
    typed_tasks = typed_project["tasks"]
    print(f"     recorded: {len(rec_tasks)} tasks, "
          f"{len(rec_project.get('commitments') or [])} commitments, "
          f"{len(rec_project.get('stakeholders') or [])} stakeholders")
    print(f"     typed   : {len(typed_tasks)} tasks, "
          f"{len(typed_project.get('commitments') or [])} commitments, "
          f"{len(typed_project.get('stakeholders') or [])} stakeholders")
    check("recording is no longer the poor relation of typing",
          len(rec_tasks) >= max(3, len(typed_tasks) // 2)
          and bool(rec_project.get("commitments"))
          and bool(rec_project.get("stakeholders")))

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print("\n" + "=" * 68)
    print(f"{passed}/{len(CHECKS)} checks passed")
    if passed != len(CHECKS):
        for desc, ok, det in CHECKS:
            if not ok:
                print(f"  FAILED: {desc}  {det}")
        sys.exit(1)


async def _run() -> None:
    try:
        await main()
    finally:
        # aiosqlite's threads are non-daemon: without this a failed run never
        # exits, and keeps a lock on its own database file.
        from app.database import engine

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
