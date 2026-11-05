"""Findings F10 and F3 — two affordances the backend never populated.

F10: the lead suggestion banner offers a **Why?** button, which reads
`ai_decisions` for (entity_type='lead', entity_id=lead.id). Every producer of a
suggestion set `suggested_state`/`suggested_state_reason` directly and recorded
nothing, so the table held 0 rows and the button could only ever answer
"No AI decision is recorded for this record".

F3: the daily digest consulted tasks, approvals and overnight replies only. A
person whose day was a follow-up and a demo got a heading and nothing under it,
while the "My day" cards on the same screen said "1 due today".
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import auth, open_lead

pytestmark = pytest.mark.asyncio


async def test_a_lead_suggestion_can_explain_itself(client, org_a):
    """F10: suggesting a state must leave a trace the Why? sheet can read."""
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.work import AIDecision
    from app.services import lead_service
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F10 Why Co"})
    ).json()
    # ACTIVE is only suggestible once the lead is out of pre-sales.
    await open_lead(client, token, lead["id"])

    async with SessionLocal() as db:
        await lead_service.suggest_state(
            db, org_id=org_a["id"], lead_id=lead["id"], to_state="active",
            reason="A real recorded discussion took place",
        )
        await db.commit()

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(AIDecision).where(
                AIDecision.entity_type == "lead",
                AIDecision.entity_id == lead["id"],
            )
        )).scalars().all()
    assert rows, "the suggestion recorded no decision — Why? is structurally dead (F10)"
    assert any("discussion" in r.reason for r in rows), \
        f"the reason shown to the user was not recorded: {[r.reason for r in rows]}"

    # And the sheet the app opens must actually render it.
    async with SessionLocal() as db:
        trace = await assistant_engine.why_trace(
            db, org_id=org_a["id"], entity_type="lead", entity_id=lead["id"]
        )
    assert "No AI decision is recorded" not in trace, trace
    assert "F10 Why Co" in trace or "active" in trace, trace


async def test_digest_includes_followups_and_demos(client, org_a):
    """F3: a day made of a follow-up and a demo must produce a digest with a
    body, not a bare heading."""
    from app.core.constants import DemoStatus, FollowUpStatus
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.demo import Demo
    from app.models.followup import FollowUp
    from app.models.lead import Lead
    from app.models.user import User
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F3 Digest Co"})
    ).json()
    await open_lead(client, token, lead["id"])

    async with SessionLocal() as db:
        agent = (await db.execute(
            select(User).where(User.id == org_a["agent_id"])
        )).scalar_one()
        lead_row = (await db.execute(
            select(Lead).where(Lead.id == lead["id"])
        )).scalar_one()
        lead_row.owner_id = agent.id
        db.add(FollowUp(
            org_id=org_a["id"], lead_id=lead["id"], owner_id=agent.id,
            due_date=date.today(), channel="whatsapp",
            status=FollowUpStatus.PENDING.value, note="Check interest",
        ))
        db.add(Demo(
            org_id=org_a["id"], lead_id=lead["id"],
            scheduled_date=date.today() + timedelta(days=3),
            scheduled_time="10:30", status=DemoStatus.SCHEDULED.value,
        ))
        await db.commit()

    async with SessionLocal() as db:
        agent = (await db.execute(
            select(User).where(User.id == org_a["agent_id"])
        )).scalar_one()
        digest = await assistant_engine.build_daily_digest(
            db, org_id=org_a["id"], user=agent
        )
        content = digest.content_md
        await db.commit()

    body = content.split("\n", 1)[1].strip() if "\n" in content else ""
    assert body, f"the digest is a heading and nothing else (F3): {content!r}"
    assert "Follow-ups due" in content, content
    assert "Demos coming up" in content, content
    assert "F3 Digest Co" in content, content


async def test_an_empty_day_says_so_instead_of_rendering_a_bare_heading(client, org_a):
    """F3's other half: with genuinely nothing on, the card must say so."""
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.user import User
    from sqlalchemy import select

    # A brand-new user owns nothing at all.
    created = (
        await client.post(
            "/api/v1/admin/users", headers=auth(org_a["admin_token"]),
            json={"email": "idle@alpha-example.com", "name": "Idle Ivy",
                  "role": "sales_agent"},
        )
    ).json()

    async with SessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.id == created["id"])
        )).scalar_one()
        digest = await assistant_engine.build_daily_digest(
            db, org_id=org_a["id"], user=user
        )
        content = digest.content_md
        await db.commit()

    body = content.split("\n", 1)[1].strip() if "\n" in content else ""
    assert body, f"an empty day rendered as a bare heading (F3): {content!r}"
    assert "Nothing needs you" in content, content


async def test_greeting_name_uses_first_name_but_not_the_org():  # noqa: D103
    """F15: 'YuviPep Admin' must not be greeted as 'YuviPep' (the org)."""
    from app.engines.assistant_engine import _greeting_name

    assert _greeting_name("Siva Kumar") == "Siva"
    assert _greeting_name("Mithun") == "Mithun"
    # The seeded admin — the finding's exact case: keep the whole label.
    assert _greeting_name("YuviPep Admin") == "YuviPep Admin"
    assert _greeting_name("Alpha Education Admin") == "Alpha Education Admin"
    assert _greeting_name("") == "there"
    assert _greeting_name(None) == "there"
