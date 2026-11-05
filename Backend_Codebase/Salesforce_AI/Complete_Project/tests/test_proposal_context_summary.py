"""A proposal draft must not open with `[missing:context_summary]`.

Reported live 2026-08-07, from the app, with a screenshot:

    "when I ask it to create the proposal, why does it still create it
     including the missing context summary?"

    Dear Kavitha Rao,

    [missing:context_summary]

    ## What we will do

The chain, end to end:

  1. the org's proposal template has `{context_summary}` where the opening
     paragraph belongs;
  2. `create_proposal` declares `context_note` OPTIONAL — "optional 1-2
     sentence context from the meeting" — and it is not in `required`;
  3. asked "create the commissioning proposal for meridian", the model omits
     it, because it is optional and no meeting text is in front of it;
  4. `build_proposal` does `context_summary or ""`;
  5. `template_service.render` turns "" into `[missing:context_summary]`.

Nothing was broken. Nothing ever supplied the value.

**This is why F47 and F61 did not fix it, and the distinction matters:**
F47 made the marker BLOCK the approve/send gate, F61 stopped a stale PDF being
attached after a blank was filled. Both act on a draft that already carries the
marker. Neither makes the draft come out clean.

The fix takes the value from where it already exists — the project's
`objective`, written from the meeting by the planner. It is not invented: with
no project and no objective the marker still appears and F47 still escalates.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio

_OBJECTIVE = (
    "Commissioning and handover of two new data halls with 120 racks total, "
    "including rack-level acceptance and one documented handover pack."
)


async def _org_with_template(client, org, body_md: str, code: str):
    """A program + pricing + a template whose body needs {context_summary}."""
    program = (
        await client.post(
            "/api/v1/admin/programs", headers=auth(org["admin_token"]),
            json={"name": f"DC Commissioning {code}", "code": code},
        )
    ).json()
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing",
        headers=auth(org["admin_token"]),
        json={"currency": "INR", "items": [
            {"code": "rack", "label": "Rack acceptance", "unit": "per rack",
             "unit_price": 4500, "default_quantity": 120},
        ]},
    )
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(org["admin_token"]),
        json={"name": "Standard", "body_md": body_md},
    )
    return program


async def _lead_with_project(client, org, objective: str | None):
    from app.database import SessionLocal
    from app.models.project import Project

    lead = (
        await client.post("/api/v1/leads", headers=auth(org["admin_token"]),
                          json={"name": f"Meridian {uuid.uuid4().hex[:8]}"})
    ).json()
    if objective is not None:
        async with SessionLocal() as db:
            db.add(Project(org_id=org["id"], lead_id=lead["id"],
                           name="Meridian Commissioning", objective=objective,
                           status="preparation", current_plan_version=1))
            await db.commit()
    return lead


_BODY = "Dear {contact_name},\n\n{context_summary}\n\n## What we will do\n\n{pricing_table}"


async def test_the_draft_does_not_open_with_the_marker(client, org_a):
    """The headline, in the exact words of the screenshot."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import proposal_service

    program = await _org_with_template(client, org_a, _BODY, "DCC1")
    lead = await _lead_with_project(client, org_a, _OBJECTIVE)

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="a@x.test")
        proposal = await proposal_service.build_proposal(
            db, ctx, lead_id=lead["id"], program_id=program["id"],
            context_summary=None,          # exactly what the model sends
        )
        await db.commit()
        content = proposal.content_md

    assert "[missing:context_summary]" not in content, (
        "the draft still opens with the marker the owner photographed"
    )
    assert _OBJECTIVE.split(",")[0] in content, (
        "the project's objective was not used as the opening paragraph"
    )


async def test_an_explicit_note_still_wins(client, org_a):
    """The caller's own words must never be overwritten by the objective."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import proposal_service

    program = await _org_with_template(client, org_a, _BODY, "DCC2")
    lead = await _lead_with_project(client, org_a, _OBJECTIVE)

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="a@x.test")
        proposal = await proposal_service.build_proposal(
            db, ctx, lead_id=lead["id"], program_id=program["id"],
            context_summary="Following our call on Tuesday about hall three.",
        )
        await db.commit()
        content = proposal.content_md

    assert "Following our call on Tuesday" in content
    assert _OBJECTIVE not in content, "an explicit note was overwritten"


async def test_no_project_still_shows_the_marker_rather_than_inventing(client, org_a):
    """The honesty half. A lead with no project has no context, and a proposal
    that INVENTS an opening paragraph is far worse than one that flags a gap —
    F47 exists to escalate exactly this."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.services import proposal_service

    program = await _org_with_template(client, org_a, _BODY, "DCC3")
    lead = await _lead_with_project(client, org_a, None)   # no project at all

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="a@x.test")
        proposal = await proposal_service.build_proposal(
            db, ctx, lead_id=lead["id"], program_id=program["id"],
            context_summary=None,
        )
        await db.commit()
        content = proposal.content_md

    assert "[missing:context_summary]" in content, (
        "with nothing to say, the marker must remain — never fabricate"
    )


async def test_a_closed_project_is_not_used_as_context(client, org_a):
    """Last year's finished engagement must not open this year's proposal."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.project import Project
    from app.services import proposal_service

    program = await _org_with_template(client, org_a, _BODY, "DCC4")
    lead = await _lead_with_project(client, org_a, None)
    async with SessionLocal() as db:
        db.add(Project(org_id=org_a["id"], lead_id=lead["id"], name="Old",
                       objective="Last year's completed rollout.",
                       status="closed", current_plan_version=1))
        await db.commit()

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="a@x.test")
        proposal = await proposal_service.build_proposal(
            db, ctx, lead_id=lead["id"], program_id=program["id"],
            context_summary=None,
        )
        await db.commit()
        content = proposal.content_md

    assert "Last year" not in content, "a closed project supplied the context"


async def test_the_escalation_still_fires_when_something_is_genuinely_missing(
    client, org_a
):
    """F47's decision record must survive this fix — a template variable that
    nothing can fill still has to reach a human."""
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.work import AIDecision
    from app.services import proposal_service

    body = "Dear {contact_name},\n\n{context_summary}\n\n{unfillable_thing}"
    program = await _org_with_template(client, org_a, body, "DCC5")
    lead = await _lead_with_project(client, org_a, _OBJECTIVE)

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                         role="sales_agent", email="a@x.test")
        await proposal_service.build_proposal(
            db, ctx, lead_id=lead["id"], program_id=program["id"],
            context_summary=None,
        )
        await db.commit()

    async with SessionLocal() as db:
        decisions = (
            await db.execute(
                select(AIDecision).where(AIDecision.org_id == org_a["id"])
            )
        ).scalars().all()
    assert any(d.needs_human for d in decisions), (
        "an unfillable template variable no longer escalates"
    )
