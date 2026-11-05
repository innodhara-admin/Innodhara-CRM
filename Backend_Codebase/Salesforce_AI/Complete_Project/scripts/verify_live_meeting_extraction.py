"""Live verification that meeting analysis is DOMAIN-NEUTRAL (finding F4/F4b).

The bug: `app/ai/extraction.py`'s prompt hardcoded the word "school" into the
instructions. Against a real recorded meeting with an engineering-services
client the model dutifully wrote "…a pilot across three SCHOOL offices…" into
the summary and then stored *"The school operates offices in Bengaluru,
Hyderabad, and Pune."* in `client_intelligence` — a false fact in permanent
org memory, which later feeds search_past_notes and proposal context.

The regression input below is the VERBATIM transcript of the real 2:47
recording from the 2026-07-21/22 simulation (Whisper's leading hallucination
included — that is genuine F5 residue and part of what the model must cope
with). It contains the word "school" exactly zero times, so any occurrence in
the model's OUTPUT was invented by the prompt.

Two directions are checked, because "never say school" would be the wrong fix:
  A. Neutral client, no domain words in the transcript  -> none may appear in
     the summary or key_facts (the F4b regression).
  B. A transcript that genuinely IS about a school      -> the client's own
     words must survive; the fix must not launder real vocabulary away.

Needs a real LLM provider in .env. Creates no leads, meetings or tasks — but
it is NOT database-free: every model call writes an `llm_usage` accounting row,
so this points DATABASE_URL at its own throwaway file. Without that override it
inherits .env and those rows land in the live `data/salesplatform.db` (observed
2026-07-22 — the docstring used to claim "touches no database", and was wrong).

Run:  python scripts/verify_live_meeting_extraction.py
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

DB_PATH = PROJECT_ROOT / "data" / "verify_meeting_extraction.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

CHECKS: list[tuple[str, bool, str]] = []

# Vocabulary that belongs to ONE industry. None of it is banned — it may only
# appear in an answer when the speakers themselves used it.
DOMAIN_WORDS = [
    "school", "student", "pupil", "principal", "teacher", "classroom",
    "campus", "syllabus", "academic", "headmaster", "parent",
]

# ── A. The real recording that exposed F4b (engineering-services client) ─────
NEUTRAL_TRANSCRIPT = (
    "दुर्धू लैक साध्याफा उतरूग करहेता है, अपर यह Judah. तर démocrता को पाLED से "
    "Long-Tight Collector peer-VAB Thanks for making time today, Ekakny. Just to "
    "recap what we discussed at the Expo. ఆికులు అన్న్కు పుంద్స్ పత్రు పోట్ర్దిలోలికు. "
    "కొన్న్తులికరంచి సండిపెలిక్లిన్ను అన్న్తుతుతుత్లు. That is right. We want to run "
    "it across three of our offices. Bengaluru first, then Hyderabad and Pune. "
    "Understood. How many participants are you expecting in the first batch? About "
    "40 in Bengaluru. If it goes well we will scale to 120 across all three. Good. "
    "On timing, when would you like the first batch to start? We want to start in "
    "the first week of September. Our corporate social responsibility spend has to "
    "be booked before the quarter closes. That works. I will send you a full "
    "proposal with the commercials by Friday. Please include the safety compliance "
    "documentation as well. Our facilities team will not approve anything without "
    "it? Noted. I will get the safety compliance pack prepared and attached. One "
    "more thing. Our leadership team wants to see a live demonstration before we "
    "sign anything. Of course. I will arrange a demonstration session for your "
    "leadership team in the last week of July. Also please loop in our finance "
    "controller, Priya Nair, for the commercial discussion. She approves the "
    "budget. I will add Priya Nair to the thread. Anything else on your side? No, "
    "that covers it. Send the proposal and we will review it internally. Perfect. "
    "Thank you Akakni. I will follow up by Friday."
)

# ── B. The opposite direction: a client that really is a school ─────────────
DOMAIN_TRANSCRIPT = (
    "Thanks for seeing us, Mrs Rao. As principal you know the timetable best. "
    "We would run the programme for students of classes six to eight, about two "
    "hundred pupils in all. The teachers would need a half-day briefing first. "
    "Could we use the science classroom on the first floor? Yes, that room is "
    "free after lunch. Please send the syllabus and the fee structure by Tuesday "
    "so I can put it to the parent committee."
)


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


def invented_words(transcript: str, produced: str) -> list[str]:
    """Domain words the model produced that the speakers never used."""
    src, out = transcript.lower(), produced.lower()
    return sorted({w for w in DOMAIN_WORDS if w in out and w not in src})


async def main() -> None:
    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE extraction run — provider={s.llm_provider}\n")

    from app.ai import extraction

    # ── A ────────────────────────────────────────────────────────────────────
    print("A. Neutral client — the prompt must not invent an industry (F4/F4b)")
    assert not invented_words("", NEUTRAL_TRANSCRIPT), "fixture is not neutral"
    check("the transcript itself contains no domain vocabulary",
          not any(w in NEUTRAL_TRANSCRIPT.lower() for w in DOMAIN_WORDS))

    a = await extraction.analyse_meeting(
        NEUTRAL_TRANSCRIPT, org_name="YuviPep", client_name="Telaverge Solutions"
    )
    check("a summary came back", bool(a.summary))
    check("the discussion was recognised as real", a.real_discussion is True)
    check("action items were extracted", len(a.action_items) >= 3,
          f"{len(a.action_items)} items")

    bad = invented_words(NEUTRAL_TRANSCRIPT, a.summary)
    check("summary invents no industry the speakers never named",
          not bad, f"invented: {bad}" if bad else "")
    print(f"     summary: {a.summary[:220]}")

    facts_text = " || ".join(a.key_facts)
    bad = invented_words(NEUTRAL_TRANSCRIPT, facts_text)
    check("key_facts (which are stored permanently) invent nothing",
          not bad, f"invented: {bad}" if bad else "")
    for f in a.key_facts:
        print(f"     fact: {f}")

    items_text = " || ".join(
        f"{i.get('title', '')} {i.get('description') or ''}" for i in a.action_items
    )
    bad = invented_words(NEUTRAL_TRANSCRIPT, items_text)
    check("action items invent nothing either", not bad,
          f"invented: {bad}" if bad else "")

    # ── B ────────────────────────────────────────────────────────────────────
    print("\nB. A client that really IS a school — its own words must survive")
    b = await extraction.analyse_meeting(
        DOMAIN_TRANSCRIPT, org_name="YuviPep", client_name="Green Valley School"
    )
    spoken = (b.summary + " " + " || ".join(b.key_facts)).lower()
    check("the school's own vocabulary is still used when it is real",
          any(w in spoken for w in ("school", "student", "pupil", "principal",
                                    "teacher", "classroom")),
          "" if any(w in spoken for w in ("school", "student", "pupil",
                                          "principal", "teacher", "classroom"))
          else "neutralised real vocabulary — over-corrected")
    print(f"     summary: {b.summary[:220]}")

    # ── Report ───────────────────────────────────────────────────────────────
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
