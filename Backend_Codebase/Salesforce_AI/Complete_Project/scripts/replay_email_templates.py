"""Real-model replays of template emails on the STAGING database (plan Task 12).

    DATABASE_URL=sqlite+aiosqlite:///./data/salesplatform.db EMAIL_MODE=dry_run \
        python scripts/replay_email_templates.py

Each request goes through `orchestrator.handle_command` with its own chat id,
as a real YuviPep sales lead, with the real model from .env. Nothing is sent:
EMAIL_MODE must be dry_run, and the script refuses otherwise.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

REQUESTS = [
    ("en-ibc", ["send the IBC proposal email to Indian Public School", "Mr."]),
    ("hi-ibc", ["Indian Public School ko IBC proposal email bhejo"]),
    ("kn-ibc", ["Indian Public School ge IBC proposal mail kalisi"]),
    ("en-followup", ["send a follow up email to Pirani Scool, they have not replied"]),
    ("hi-followup", ["Pirani Scool ko follow up mail bhejo"]),
    ("kn-confirm", ["Jain Public School ge meeting confirmation mail kalisi"]),
    ("en-intro", ["send the intro email to Delhi Public School"]),
    ("en-custom", ["email Risabh Public School that our visit moves to Thursday"]),
    ("en-fest", ["send the Innovation Fest proposal email to BS Carmel School"]),
    ("en-onboard", ["send the onboarding email to Ollama School of Commerce"]),
    ("en-mou", ["send the MoU cover letter to Orchid International School"]),
    ("en-after", ["send the thank you email after our meeting to SJR Group Of School"]),
]


def _summary(result) -> dict:
    asked = next((a for a in result.actions if a.get("outcome") == "needs_confirmation"), None)
    tools = [a.get("tool") for a in result.actions]
    out = {"agent": result.agent, "tools": tools, "reply": (result.reply or "")[:240]}
    if asked:
        out["question"] = (asked.get("question") or "")[:400]
        out["taps"] = asked.get("candidates")
    for a in result.actions:
        r = a.get("result")
        if isinstance(r, dict) and r.get("waiting_for_document"):
            out["warning"] = r.get("message")
    if result.pending_approvals:
        p = result.pending_approvals[0]
        out["draft"] = {k: p.get(k) for k in ("kind", "template", "to", "subject", "attachments")}
    return out


async def main() -> int:
    if os.environ.get("EMAIL_MODE") != "dry_run":
        print("Set EMAIL_MODE=dry_run: replays must never send.")
        return 2
    from app.ai import orchestrator
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.email_template import EmailFillSession, EmailTemplate
    from app.models.user import User

    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(
            User.email == "siva@yuvipep.com"))).scalar_one()
        ctx = OrgContext(org_id=user.org_id, user_id=user.id, role=user.role,
                         email=user.email, name=user.name)
    report = []
    for label, turns in REQUESTS:
        chat = f"replay-{label}-{uuid.uuid4().hex[:6]}"
        for text in turns:
            async with SessionLocal() as db:
                try:
                    result = await orchestrator.handle_command(db, ctx, text, session_id=chat)
                    await db.commit()
                    row = {"label": label, "said": text, **_summary(result)}
                except Exception as exc:  # noqa: BLE001 -- a replay records, never stops
                    await db.rollback()
                    row = {"label": label, "said": text, "error": repr(exc)[:300]}
            async with SessionLocal() as db:
                fill = (await db.execute(select(EmailFillSession).where(
                    EmailFillSession.chat_session_id == chat))).scalars().first()
                if fill is not None:
                    template = await db.get(EmailTemplate, fill.template_id)
                    row["template"] = template.name if template else None
                    row["fill_status"] = fill.status
                    row["filled"] = {t["raw"]: t.get("value") for t in fill.tags_json
                                     if t.get("outcome") == "filled"}
            report.append(row)
            print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
