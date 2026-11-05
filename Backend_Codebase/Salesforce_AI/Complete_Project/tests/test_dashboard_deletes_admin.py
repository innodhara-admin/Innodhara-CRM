"""Catalogue deletes on the admin surface, and the version promotion that
gives the API its first un-supersede path."""
from __future__ import annotations

import pytest

from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio


async def _org(client, super_token, tag: str) -> dict:
    return await create_org(client, super_token, name=f"Del {tag}",
                            slug=f"del-{tag}", domain=f"del-{tag}-example.com")


async def _program(client, token, code: str) -> dict:
    resp = await client.post(
        "/api/v1/admin/programs", headers=auth(token),
        json={"name": f"Prog {code}", "code": code, "description": "Work."},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_unused_program_deletes(client, super_token):
    org = await _org(client, super_token, "prog")
    token = org["admin_token"]
    program = await _program(client, token, "GONE")

    # A Knowledge-Engine suggestion for this program: `playbook_suggestions`
    # carries a bare `program_id` with no FK (nothing enforces the reference at
    # the database level), and there is no POST route for it — the Engine
    # writes it internally — so the fixture is built directly, following the
    # precedent in tests/test_assignment_skills.py.
    from sqlalchemy import select as sa_select

    from app.database import SessionLocal
    from app.models.project import PlaybookSuggestion

    async with SessionLocal() as db:
        db.add(PlaybookSuggestion(
            org_id=org["id"], program_id=program["id"], phase="preparation",
            entry={"title": "Confirm working machines a day early"},
            reason="Recurring incident pattern",
        ))
        await db.commit()

    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json() == []

    async with SessionLocal() as db:
        remaining = (
            await db.execute(
                sa_select(PlaybookSuggestion).where(
                    PlaybookSuggestion.org_id == org["id"],
                    PlaybookSuggestion.program_id == program["id"],
                )
            )
        ).scalars().all()
    assert remaining == [], (
        "playbook_suggestions row(s) survived the deleted program: "
        f"{[r.id for r in remaining]}"
    )


async def test_program_with_a_proposal_refuses(client, super_token):
    org = await _org(client, super_token, "progused")
    token = org["admin_token"]
    program = await _program(client, token, "USED")
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "items": [
            {"code": "per_rack", "label": "Per rack", "unit": "per rack",
             "unit_price": 1000.0}]},
    )
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Standard", "body_md": "# {client_name}\n\n{pricing_table}"},
    )
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Buyer Ltd"})).json()
    # Real API: POST /api/v1/proposals takes {lead_id, program_id, template_id,
    # context_summary, quantities, project_id} (app/api/proposals.py
    # BuildProposalRequest) — no `title` field. The brief's body still carries
    # `title`; BaseModel's default `extra="ignore"` (no model in this codebase
    # sets extra="forbid") means it is silently dropped, not rejected, so the
    # setup call needs no change to work — kept here for the record.
    proposal = await client.post(
        "/api/v1/proposals", headers=auth(token),
        json={"lead_id": lead["id"], "program_id": program["id"],
              "title": "Proposal for Buyer Ltd"},
    )
    assert proposal.status_code == 200, proposal.text

    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}", headers=auth(token)
    )
    assert resp.status_code == 409
    assert "proposal" in resp.text.lower()


async def test_pricing_locked_by_a_proposal_refuses(client, super_token):
    """The lock guard reads `proposals.pricing_table_id`, which is populated on
    every `build_proposal` call (non-nullable) — this proves it actually fires,
    not just that the column exists."""
    org = await _org(client, super_token, "pricelock")
    token = org["admin_token"]
    program = await _program(client, token, "PLOCK")
    pricing = (await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "items": [
            {"code": "per_rack", "label": "Per rack", "unit": "per rack",
             "unit_price": 1000.0}]},
    )).json()
    assert pricing["version"] == 1
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Standard", "body_md": "# {client_name}\n\n{pricing_table}"},
    )
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Buyer Ltd"})).json()
    proposal = await client.post(
        "/api/v1/proposals", headers=auth(token),
        json={"lead_id": lead["id"], "program_id": program["id"]},
    )
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["pricing_version"] == 1

    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}/pricing/1", headers=auth(token)
    )
    assert resp.status_code == 409, resp.text
    # The refusal must name what actually blocked it, not just refuse.
    assert "proposal" in resp.text.lower()
    assert "rate card" in resp.text.lower() or "locked" in resp.text.lower()


async def test_template_locked_by_a_proposal_refuses(client, super_token):
    """The lock guard reads `proposals.template_id`, which is populated on
    every `build_proposal` call (non-nullable) — this proves it actually fires,
    not just that the column exists."""
    org = await _org(client, super_token, "tmpllock")
    token = org["admin_token"]
    program = await _program(client, token, "TLOCK")
    await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "items": [
            {"code": "per_rack", "label": "Per rack", "unit": "per rack",
             "unit_price": 1000.0}]},
    )
    template = (await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Standard", "body_md": "# {client_name}\n\n{pricing_table}"},
    )).json()
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Buyer Ltd"})).json()
    proposal = await client.post(
        "/api/v1/proposals", headers=auth(token),
        json={"lead_id": lead["id"], "program_id": program["id"]},
    )
    assert proposal.status_code == 200, proposal.text

    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates/{template['id']}",
        headers=auth(token),
    )
    assert resp.status_code == 409, resp.text
    assert "proposal" in resp.text.lower()
    assert "template" in resp.text.lower()


async def test_demo_team_booked_refuses(client, super_token):
    """The guard reads `demos.team_id`, populated whenever a demo is scheduled
    against a team — this proves it actually fires, not just that the column
    exists."""
    org = await _org(client, super_token, "teamlock")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    team = (await client.post(
        "/api/v1/admin/demo-teams", headers=auth(token),
        json={"name": "Booked Squad", "lead_user_id": me["user_id"]},
    )).json()
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Buyer Ltd"})).json()
    demo = await client.post(
        "/api/v1/demos", headers=auth(token),
        json={"lead_id": lead["id"], "scheduled_date": "2026-09-01",
              "team_id": team["id"]},
    )
    assert demo.status_code == 200, demo.text

    resp = await client.delete(
        f"/api/v1/admin/demo-teams/{team['id']}", headers=auth(token)
    )
    assert resp.status_code == 409, resp.text
    assert "demo" in resp.text.lower()
    assert "booked squad" in resp.text.lower()


async def test_deleting_current_pricing_promotes_the_previous(client, super_token):
    org = await _org(client, super_token, "price")
    token = org["admin_token"]
    program = await _program(client, token, "PRICE")
    for price in (1000.0, 1200.0):
        resp = await client.post(
            f"/api/v1/admin/programs/{program['id']}/pricing", headers=auth(token),
            json={"currency": "INR", "items": [
                {"code": "per_rack", "label": "Per rack", "unit": "per rack",
                 "unit_price": price}]},
        )
        assert resp.status_code == 200, resp.text

    history = (await client.get(
        f"/api/v1/admin/programs/{program['id']}/pricing",
        headers=auth(token))).json()
    assert len(history) == 2

    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}/pricing/2", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text

    after = (await client.get(
        f"/api/v1/admin/programs/{program['id']}/pricing",
        headers=auth(token))).json()
    assert len(after) == 1
    assert after[0]["version"] == 1
    assert after[0]["is_current"] is True


async def test_message_template_deletes_without_a_guard(client, super_token):
    org = await _org(client, super_token, "msg")
    token = org["admin_token"]
    created = await client.post(
        "/api/v1/admin/message-templates", headers=auth(token),
        json={"kind": "intro", "channel": "email", "name": "First hello",
              "subject": "Hello from us", "body": "Dear {contact_name}, hello."},
    )
    assert created.status_code == 200, created.text

    resp = await client.delete(
        f"/api/v1/admin/message-templates/{created.json()['id']}",
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text


async def test_demo_team_delete_removes_its_members(client, super_token):
    org = await _org(client, super_token, "team")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    team = (await client.post(
        "/api/v1/admin/demo-teams", headers=auth(token),
        json={"name": "Alpha Squad", "lead_user_id": me["user_id"],
              "member_ids": [me["user_id"]]},
    )).json()

    resp = await client.delete(
        f"/api/v1/admin/demo-teams/{team['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get(
        "/api/v1/admin/demo-teams", headers=auth(token))).json() == []

    # The unique (org, name) index must now allow the corrected re-creation.
    again = await client.post(
        "/api/v1/admin/demo-teams", headers=auth(token),
        json={"name": "Alpha Squad", "lead_user_id": me["user_id"]},
    )
    assert again.status_code == 200, again.text


async def test_cross_org_delete_is_a_404(client, super_token, org_b):
    org = await _org(client, super_token, "xorg")
    program = await _program(client, org["admin_token"], "XORG")
    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}",
        headers=auth(org_b["admin_token"]),
    )
    assert resp.status_code == 404
