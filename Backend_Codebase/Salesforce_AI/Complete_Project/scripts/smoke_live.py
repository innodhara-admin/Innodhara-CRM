"""Live smoke test against the REAL Gemini API (uses the key in .env).

Run after seeding, with the server NOT required (talks to the app directly):

    python scripts/smoke_live.py

Exercises: model layer (both tiers), JSON mode, business-card OCR on a
generated image, action-item extraction, embeddings + org-scoped memory,
orchestrator routing, and a full assistant command through the Query agent.
Costs a fraction of a cent on the free tier.
"""
from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK = "  [OK]"


async def main() -> None:
    from sqlalchemy import select

    from app.ai import extraction, memory, orchestrator, vision
    from app.ai.llm import TIER_FAST, TIER_STRONG, get_model_layer
    from app.core.context import OrgContext
    from app.database import SessionLocal, init_db
    from app.models.organisation import Organisation
    from app.models.user import User

    await init_db()

    async with SessionLocal() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.slug == "yuvipep"))
        ).scalar_one_or_none()
        if org is None:
            print("Run scripts/seed_demo.py first.")
            return
        rahul = (
            await db.execute(select(User).where(User.email == "rahul@yuvipep.com"))
        ).scalar_one()
        ctx = OrgContext(org_id=org.id, user_id=rahul.id, role=rahul.role,
                         email=rahul.email, name=rahul.name)

    model = get_model_layer()

    print("1. Model layer — fast tier")
    r = await model.generate(purpose="smoke.fast", tier=TIER_FAST, org_id=ctx.org_id,
                             messages=[{"role": "user", "content": "Reply with exactly: PONG"}])
    assert "PONG" in r.text.upper(), r.text
    print(OK, r.model, f"({r.input_tokens}in/{r.output_tokens}out)")

    print("2. Model layer — strong tier + JSON mode")
    data = await model.generate_json(
        purpose="smoke.json", tier=TIER_STRONG, org_id=ctx.org_id,
        messages=[{"role": "user",
                   "content": 'Return JSON {"city": "Delhi", "n": 3}'}],
        json_schema={"type": "object",
                     "properties": {"city": {"type": "string"}, "n": {"type": "integer"}},
                     "required": ["city", "n"]},
    )
    assert data["city"] == "Delhi" and data["n"] == 3, data
    print(OK, data)

    print("3. Business-card OCR (generated card image)")
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (640, 360), "white")
        d = ImageDraw.Draw(img)
        d.text((40, 60), "Mrs. Anita Sharma", fill="black")
        d.text((40, 110), "Principal", fill="black")
        d.text((40, 160), "Delhi Public School", fill="black")
        d.text((40, 210), "principal@dps.example.edu", fill="black")
        d.text((40, 260), "+91 98100 12345", fill="black")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        scan = await vision.read_business_card(buf.getvalue(), "image/png",
                                               org_id=ctx.org_id)
        assert scan.name and "sharma" in scan.name.lower(), scan
        assert scan.email == "principal@dps.example.edu", scan
        print(OK, f"{scan.name} | {scan.title} | {scan.email} "
                  f"(confidence {scan.confidence:.2f})")
    except ImportError:
        print("  [SKIP] Pillow not installed (pip install pillow) — OCR untested")

    print("4. Action-item extraction from a transcript")
    analysis = await extraction.analyse_meeting(
        "Rahul: Great meeting, madam. I will email the IBC proposal by Friday "
        "and my colleague will call you Monday to fix the demo date. "
        "Principal: Yes please, and do share the safety certificates too.",
        org_name="YuviPep", client_name="Delhi Public School", org_id=ctx.org_id,
    )
    assert len(analysis.action_items) >= 2, analysis.action_items
    assert analysis.real_discussion is True
    print(OK, f"{len(analysis.action_items)} items:",
          "; ".join(i["title"] for i in analysis.action_items))

    print("5. Memory: embed, store, org-scoped semantic search")
    async with SessionLocal() as db:
        await memory.add_memory(db, org_id=ctx.org_id, text=
                                "Delhi Public School prefers Hindi-medium workshops "
                                "and morning slots.", source_type="note")
        await db.commit()
        hits = await memory.search_memory(db, org_id=ctx.org_id,
                                          query="what language does DPS prefer?")
        assert hits and "Hindi" in hits[0]["text"], hits
        other_org = await memory.search_memory(db, org_id="nonexistent-org",
                                               query="Hindi workshops")
        assert not other_org, "memory leaked across orgs!"
    print(OK, f"top hit score {hits[0]['score']:.3f}; other-org search empty")

    print("6. Orchestrator routing")
    for text, expected in [
        ("Show my open action items", "query"),
        ("Write a WhatsApp follow-up for Green Valley", "followup"),
        ("Create the IBC proposal for Sunrise School", "proposal"),
        ("Book a demo for DPS next Tuesday", "scheduling"),
    ]:
        agent = await orchestrator.route(ctx, text)
        marker = "" if agent == expected else f"  (expected {expected})"
        print(f"     '{text}' -> {agent}{marker}")

    print("7. Full assistant command (Query agent, real tool loop)")
    async with SessionLocal() as db:
        result = await orchestrator.handle_command(
            db, ctx, "Which schools are in my pipeline right now?")
        await db.commit()
    assert result.reply, result
    print(OK, f"[{result.agent}] {result.reply[:200]}")
    print("\nAll live smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
