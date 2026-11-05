"""Live verification that the planner picks required_skill from the org's real
skill taxonomy instead of inventing a free-form one (finding F25).

Before the fix, `user_skills` was empty and the planner invented a fresh skill
per task ("forklift_training", "venue_coordination", …), so the assignment
engine — which matches on the exact string — found no one and flagged every task
"no skill match". Now the org's skills are seeded and the planner is told to
choose required_skill from that list (or 'general'), backed by a deterministic
coercion of any invented name onto 'general'.

What this proves against the REAL model, on a transcript deliberately about
warehouse forklift-safety training (which tempts invented skills):

  1. Every task's required_skill is one the org actually has (taxonomy ∪
     {general, none}) — so the assignment engine can match it.
  2. The model maps real work onto real skills (at least one non-'general'
     skill is chosen), rather than everything collapsing to 'general'.

Runs on its own throwaway database. Model calls only — no mail, no calendar.

Run:  python scripts/verify_live_planner_skills.py
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

DB_PATH = PROJECT_ROOT / "data" / "verify_planner_skills.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

CHECKS: list[tuple[str, bool, str]] = []

TRANSCRIPT = (
    "Rahul: Thanks for meeting us. You mentioned safety incidents at the "
    "warehouses. Client: Yes, we need forklift safety training for all operators "
    "across three sites, a certification program, and updated training material. "
    "Rahul: We can prepare a proposal, build the curriculum, arrange the training "
    "sessions and coordinate the logistics across your sites. Client: Please send "
    "the proposal with commercials by Friday and schedule a demonstration."
)


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE planner-skills run — provider={s.llm_provider}\n")

    from app.ai.planning import generate_initial_plan, org_skill_names
    from app.database import SessionLocal, init_db
    from app.main import _seed_super_admin
    from app.models.organisation import Organisation
    from scripts.seed_demo import seed
    from sqlalchemy import select

    await init_db()
    await _seed_super_admin()
    await seed()  # the full YuviPep demo org, including the F25 skill taxonomy

    async with SessionLocal() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.slug == "yuvipep"))
        ).scalar_one()
        taxonomy = set(await org_skill_names(db, org.id))
        print(f"org taxonomy: {sorted(taxonomy)}\n")

        try:
            plan = await generate_initial_plan(
                db, org_id=org.id, lead_name="Nagpur Warehousing Co",
                text=TRANSCRIPT,
            )
        except Exception as exc:  # noqa: BLE001
            check("the planner produced a plan", False, str(exc)[:200])
            plan = {"tasks": [], "skill_gaps": []}

    tasks = plan.get("tasks", [])
    used = [(t["title"], t.get("required_skill")) for t in tasks]
    print(f"{len(tasks)} tasks planned:")
    for title, skill in used:
        print(f"   - {title[:54]:54s} → {skill}")
    print(f"skill_gaps reported: {plan.get('skill_gaps')}\n")

    allowed = taxonomy | {None}
    stray = [(t, sk) for t, sk in used if sk not in allowed]
    check("the planner produced tasks", bool(tasks), f"{len(tasks)} tasks")
    check("every required_skill is one the org actually has (taxonomy ∪ none)",
          not stray, f"stray: {stray}" if stray else "")
    real = {sk for _, sk in used if sk and sk != "general"}
    check("the model mapped work onto real skills, not all 'general'",
          bool(real), f"real skills used: {sorted(real)}")

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
