"""Live verification of the VOICE path: a spoken meeting note (WAV) uploaded
through the real API, transcribed by LOCAL Whisper (STT_PROVIDER=whisper_local
— audio never leaves the machine), analysed by the chat LLM, and turned into
reviewed action items.

Continues the database of verify_generic_planner.py (Green Valley School is a
seeded lead with no project). Expects a WAV path as argv[1] — generate one
with any recording, or Windows TTS:

  Add-Type -AssemblyName System.Speech
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SetOutputToWaveFile("note.wav"); $s.Speak("Meeting with ..."); $s.Dispose()

Run:  python scripts/verify_live_voice.py note.wav
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


async def main() -> None:
    assert DB_PATH.exists(), "Run scripts/verify_generic_planner.py first."
    wav_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    assert wav_path and wav_path.exists(), "Pass a WAV file path as the first argument."

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE voice run — stt={s.stt_provider}/{s.whisper_model}, chat={s.llm_provider}\n")

    from app.database import SessionLocal, init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.jobs.queue import job_queue
    from app.main import app

    await init_db()
    register_handlers()
    sync_engine.register()
    await job_queue.start()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=300)

    async def login(email: str) -> str:
        r = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
        r.raise_for_status()
        return r.json()["access_token"]

    from app.models.action_item import ActionItem
    from app.models.lead import Lead
    from app.models.meeting import Meeting, Transcript

    token = await login("rahul@yuvipep.com")
    headers = {"Authorization": f"Bearer {token}"}

    async with SessionLocal() as db:
        lead = (await db.execute(select(Lead).where(
            Lead.name == "Green Valley School"
        ))).scalar_one()

    print("Uploading the voice note through POST /meetings/upload …")
    # F40: consent is proof captured BEFORE the recording, so the upload links it
    # rather than manufacturing one. The app posts this from its consent sheet.
    await client.post(
        f"/leads/{lead.id}/consent", headers=headers,
        json={"method": "verbal", "note": "Agreed before recording"},
    )
    r = await client.post(
        "/meetings/upload",
        headers=headers,
        data={"lead_id": lead.id, "consent_confirmed": "true",
              "title": "Green Valley — voice note"},
        files={"file": ("note.wav", wav_path.read_bytes(), "audio/wav")},
    )
    assert r.status_code < 400, r.text[:400]
    meeting_id = r.json()["id"]
    check("upload accepted, pipeline queued", r.json()["status"] == "uploaded")

    # The background job: local Whisper (CPU) + one LLM analysis call.
    status = "uploaded"
    for _ in range(72):  # up to 6 minutes
        await asyncio.sleep(5)
        rr = await client.get(f"/meetings/{meeting_id}", headers=headers)
        status = rr.json()["status"]
        if status in ("review_pending", "completed", "failed"):
            break
    check("pipeline finished (not failed)",
          status in ("review_pending", "completed"),
          f"status={status} error={rr.json().get('error')}")

    async with SessionLocal() as db:
        transcript = (await db.execute(select(Transcript).where(
            Transcript.meeting_id == meeting_id
        ))).scalars().first()
        items = (await db.execute(select(ActionItem).where(
            ActionItem.meeting_id == meeting_id
        ))).scalars().all()
        meeting = (await db.execute(select(Meeting).where(
            Meeting.id == meeting_id
        ))).scalar_one()

    assert transcript is not None, "No transcript row"
    text = transcript.text.lower()
    print(f"     whisper transcript ({transcript.confidence:.2f} confidence): "
          f"{transcript.text[:160]}…")
    check("local Whisper transcript captures the meeting",
          sum(w in text for w in ("robotics", "lab", "proposal", "teachers")) >= 3,
          transcript.text[:200])
    check("confidence recorded and above the review threshold",
          transcript.confidence > 0.6 and not transcript.low_confidence,
          str(transcript.confidence))
    check("summary written by the chat LLM", bool(transcript.summary),
          str(transcript.summary)[:120])
    print(f"     summary: {(transcript.summary or '')[:160]}")
    check("action items extracted behind the review gate", len(items) >= 1,
          f"{len(items)} items, meeting status={meeting.status}")
    print("     action items: " + " | ".join(i.title[:60] for i in items))

    await job_queue.stop()
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
