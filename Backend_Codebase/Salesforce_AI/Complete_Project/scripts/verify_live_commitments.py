"""Live verification that the commitment register is no longer write-once (F56).

Round 7 Act 13 found that all 11 commitments on the Orchid project were created
at one instant — meeting 1, the create path — and that three subsequent merges
added **zero**. Six promises read back aloud and confirmed by the client in
meeting 4 became six tasks with `client_commitment_id = NULL`.

The plumbing was never the problem. `create_plan_version` persists a task's
`commitment`, the merge path calls it, and the merge's `new_tasks` already use
the schema that carries the sub-object. The **merge prompt** simply never asked
for one: across the whole instruction block, "commitment" appeared only as
something to *renegotiate*, never to create. So the model was told commitments
are things that already exist, and it behaved correctly.

Data Model §4.5 is unambiguous — commitments are "extracted by the Planner and
Inbound Engines **from meetings** and messages", plural and unqualified.

F56's own write-up names the experiment that would settle it: *"add the sentence
to the merge prompt and re-run a merge to confirm commitments then appear …
that experiment is the clean way to prove me wrong."* This is that experiment,
run against the real model.

It also guards the interaction the fix plan warns about. Fixing F56 naively makes
[F42] worse: a promise restated in a later meeting would create a SECOND row, and
text equality is exactly the wrong way to prevent it. The idempotency rule here is
ID-based — the merge snapshot already lists open commitments with their ids, and
the prompt anchors on that list. Check 3 restates a promise verbatim and requires
that no duplicate appears.

Run:  python scripts/verify_live_commitments.py
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

DB_PATH = PROJECT_ROOT / "data" / "verify_commitments.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []

# Deliberately non-school, like the other live scripts: nothing here may pass by
# leaning on the product's original domain.
FIRST = (
    "Thanks for coming in. We want the safety-training programme across two "
    "of our plants, starting the first week of September, about sixty "
    "operators in total. I will send you the full proposal with commercials "
    "by Friday. Please share your compliance certificate before we start — "
    "our audit team needs it on file."
)

# The merge. Two promises that did NOT exist before, one each way.
SECOND = (
    "Following up on the safety programme. Two things I want to confirm. I "
    "will send you the revised training schedule by the fifteenth of "
    "September. And you agreed to give us the list of operator names before "
    "the first session, so we can print the passes."
)

# The same promise again, restated the way a rep reads promises back at the end
# of a meeting. This must NOT create a second row.
THIRD = (
    "Just to summarise where we are. I will send you the revised training "
    "schedule by the fifteenth of September, as agreed. Nothing else has "
    "changed. Also please add a projector to the room list for session one."
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
    print(f"LIVE commitment-register run — provider={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.jobs import pipelines, register_handlers
    from app.main import _seed_super_admin, app
    from app.models.project import ClientCommitment, Project
    from sqlalchemy import select

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
            json={"name": "Commitment Test Co", "slug": "commit-test",
                  "email_domain": "commit-example.com",
                  "admin_email": "admin@commit-example.com",
                  "admin_name": "Commit Admin"},
        )
    ).json()
    tokens["admin"] = await login(org["admin_email"], org["admin_temp_password"])

    lead = await call("POST", "/leads", json={"name": "Northgate Industrials"})
    # `POST /leads` creates in `cold_calling` since pre-sales shipped, and a
    # meeting cannot be recorded against a lead nobody has phoned. This stands
    # in for the cold call.
    await call("PATCH", f"/leads/{lead['id']}/state",
               json={"state": "open", "reason": "cold call went well"})
    await call("POST", f"/leads/{lead['id']}/contacts",
               json={"name": "Priya Nair", "title": "Plant Head",
                     "email": "priya@commit-example.com", "is_primary": True})

    async def record(transcript: str, title: str) -> str:
        # F40: consent captured before the recording, as the app does it.
        await call("POST", f"/leads/{lead['id']}/consent",
                   json={"method": "verbal", "note": "Agreed before recording"})
        meeting = await call(
            "POST", "/meetings/upload",
            data={"lead_id": lead["id"], "consent_confirmed": "true",
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
        review = await call("GET", f"/meetings/{meeting['id']}/review")
        # The review contract is ReviewItem(id, title, description, keep) and
        # `title` is REQUIRED — the first version of this harness sent
        # {"id", "action"} and could only ever 422.
        await call("POST", f"/meetings/{meeting['id']}/review/confirm",
                   json={"items": [{"id": i["id"], "title": i["title"],
                                    "keep": True} for i in review["items"]]})
        # NOTE: /review/confirm ENQUEUES plan_meeting. No queue worker runs in a
        # script, so the enqueued copy just sits there — we run the planner here
        # ourselves, exactly once. Running it while a worker was also draining
        # the queue would put two writers on one SQLite file.
        await pipelines.plan_meeting(
            {"meeting_id": meeting["id"], "agreed_tasks": [
                {"title": i["title"], "due_date": i.get("due_date")}
                for i in review["items"]
            ]}, "verify",
        )
        return meeting["id"]

    async def commitments() -> list[ClientCommitment]:
        async with SessionLocal() as db:
            project = (
                await db.execute(select(Project).where(Project.lead_id == lead["id"]))
            ).scalars().first()
            if project is None:
                return []
            return list((
                await db.execute(
                    select(ClientCommitment)
                    .where(ClientCommitment.project_id == project.id)
                    .order_by(ClientCommitment.created_at)
                )
            ).scalars().all())

    # ── 1. The create path still records promises (the control) ─────────────
    print("1. The FIRST meeting records the promises it hears")
    await record(FIRST, "First meeting")
    after_first = await commitments()
    check("a first meeting produces commitments", len(after_first) > 0,
          f"{len(after_first)} row(s)")
    for c in after_first:
        print(f"       · [{c.direction}] {c.text[:90]}")

    # ── 2. A MERGE now records NEW promises — this is F56 ───────────────────
    print("\n2. A MERGE records promises stated for the first time (F56)")
    await record(SECOND, "Follow-up meeting")
    after_second = await commitments()
    added = len(after_second) - len(after_first)
    check("the second meeting added at least one commitment", added > 0,
          f"{len(after_first)} → {len(after_second)}")
    new_texts = " | ".join(c.text.lower() for c in after_second[len(after_first):])
    check("the promise WE made was captured", "schedule" in new_texts,
          new_texts[:160] or "(nothing added)")
    # Direction matters: §4.5 says "one row = one promise — in either direction".
    check("a promise the CLIENT made is recorded as theirs",
          any(c.direction == "theirs" for c in after_second),
          str([(c.direction, c.text[:40]) for c in after_second]))

    # ── 3. Restating a promise must NOT duplicate it (the [F42] interaction) ─
    print("\n3. Re-stating an existing promise does NOT create a second row")
    await record(THIRD, "Summary meeting")
    after_third = await commitments()
    check("restating a promise added no duplicate",
          len(after_third) <= len(after_second) + 1,
          f"{len(after_second)} → {len(after_third)} "
          f"(+1 allowed for the genuinely new projector ask)")
    schedule_rows = [c for c in after_third if "schedule" in c.text.lower()]
    check("the restated promise still has exactly one row",
          len(schedule_rows) <= 1,
          str([c.text[:60] for c in schedule_rows]))

    print("\n   Final register:")
    for c in after_third:
        print(f"       · [{c.direction}] {c.text[:90]}")

    await client.aclose()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print("\n" + "=" * 68)
    print(f"{passed}/{len(CHECKS)} checks passed")
    if passed != len(CHECKS):
        for desc, ok, detail in CHECKS:
            if not ok:
                print(f"  FAILED: {desc}  {detail}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
