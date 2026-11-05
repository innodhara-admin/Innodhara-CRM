### Task 8: Guarded deletes in `admin.py` *(change #6, part 2 of 2)*

Five routes: programs, pricing versions, proposal templates, message templates, demo teams.

**Files:**
- Modify: `app/api/admin.py`
- Test: `tests/test_dashboard_deletes_admin.py`

**Interfaces:**
- Produces: `DELETE /api/v1/admin/programs/{program_id}`, `DELETE /api/v1/admin/programs/{program_id}/pricing/{version}`, `DELETE /api/v1/admin/programs/{program_id}/proposal-templates/{template_id}`, `DELETE /api/v1/admin/message-templates/{template_id}`, `DELETE /api/v1/admin/demo-teams/{team_id}`. Each returns `{"deleted": True}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_deletes_admin.py
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

    resp = await client.delete(
        f"/api/v1/admin/programs/{program['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json() == []


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
```

> As in Task 7, confirm the setup routes (`POST /api/v1/proposals` and its body)
> match the real API before Step 2, and adjust the **setup** calls only.

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_deletes_admin.py -v`
Expected: FAIL — 405 on every DELETE.

- [ ] **Step 3: Add a shared version-promotion helper**

In `app/api/admin.py`, above the delete routes:

```python
async def _promote_predecessor(db: AsyncSession, model, **scope) -> None:
    """After deleting the current row of a versioned family, make the highest
    remaining version current again. This is the API's only un-supersede path
    and it exists as a consequence of deletion, not as its own endpoint."""
    predecessor = (
        await db.execute(
            select(model)
            .filter_by(**scope)
            .order_by(model.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if predecessor is not None:
        predecessor.is_current = True
```

- [ ] **Step 4: Add the five delete routes**

```python
@router.delete("/programs/{program_id}")
async def delete_program(
    program_id: str,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    """`code` is UNIQUE per org, so without this a typo is permanent — and its
    description keeps being read by the offering matcher."""
    program = (
        await db.execute(
            select(Program).where(
                Program.id == program_id, Program.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")

    used_by_projects = (
        await db.execute(
            select(func.count()).select_from(Project).where(
                Project.org_id == ctx.org_id, Project.program_id == program_id
            )
        )
    ).scalar_one()
    used_by_proposals = (
        await db.execute(
            select(func.count()).select_from(Proposal).where(
                Proposal.org_id == ctx.org_id, Proposal.program_id == program_id
            )
        )
    ).scalar_one()
    if used_by_projects or used_by_proposals:
        raise ConflictError(
            f"'{program.name}' is used by {used_by_projects} project(s) and "
            f"{used_by_proposals} proposal(s) and cannot be removed. Mark it "
            f"inactive instead."
        )

    for model, scope in (
        (PricingTable, {"program_id": program_id}),
        (ProposalTemplate, {"program_id": program_id}),
        (Playbook, {"program_id": program_id}),
    ):
        await db.execute(
            sa_delete(model.__table__).where(
                model.__table__.c.org_id == ctx.org_id,
                model.__table__.c.program_id == program_id,
            )
        )

    await db.delete(program)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.program_deleted",
        entity_type="program", entity_id=program_id,
        detail={"name": program.name, "code": program.code},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/programs/{program_id}/pricing/{version}")
async def delete_pricing_version(
    program_id: str,
    version: int,
    ctx: OrgContext = Depends(require_permission("edit_pricing")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(PricingTable).where(
                PricingTable.org_id == ctx.org_id,
                PricingTable.program_id == program_id,
                PricingTable.version == version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Pricing version not found")

    locked = (
        await db.execute(
            select(func.count()).select_from(Proposal).where(
                Proposal.org_id == ctx.org_id, Proposal.pricing_table_id == row.id
            )
        )
    ).scalar_one()
    if locked:
        raise ConflictError(
            f"{locked} proposal(s) locked this rate card version. Removing it "
            f"would break the price they were sent at."
        )

    was_current = row.is_current
    await db.delete(row)
    await db.flush()
    if was_current:
        await _promote_predecessor(
            db, PricingTable, org_id=ctx.org_id, program_id=program_id
        )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.pricing_deleted",
        entity_type="pricing_table", entity_id=row.id,
        detail={"program_id": program_id, "version": version},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/programs/{program_id}/proposal-templates/{template_id}")
async def delete_proposal_template(
    program_id: str,
    template_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(ProposalTemplate).where(
                ProposalTemplate.id == template_id,
                ProposalTemplate.org_id == ctx.org_id,
                ProposalTemplate.program_id == program_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Proposal template not found")

    locked = (
        await db.execute(
            select(func.count()).select_from(Proposal).where(
                Proposal.org_id == ctx.org_id, Proposal.template_id == template_id
            )
        )
    ).scalar_one()
    if locked:
        raise ConflictError(
            f"{locked} proposal(s) were built from this template version."
        )

    was_current, name = row.is_current, row.name
    await db.delete(row)
    await db.flush()
    if was_current:
        await _promote_predecessor(
            db, ProposalTemplate, org_id=ctx.org_id, program_id=program_id
        )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.proposal_template_deleted",
        entity_type="proposal_template", entity_id=template_id,
        detail={"program_id": program_id, "name": name},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/message-templates/{template_id}")
async def delete_message_template(
    template_id: str,
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    """No reference guard: nothing points at a message template. Removing the
    last intro/email one breaks card-scan drafting, and the console's checklist
    turns amber immediately — that is the guard (06_DESIGN.md §7.2)."""
    row = (
        await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.id == template_id,
                MessageTemplate.org_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Message template not found")

    was_current, kind, channel = row.is_current, row.kind, row.channel
    await db.delete(row)
    await db.flush()
    if was_current:
        await _promote_predecessor(
            db, MessageTemplate, org_id=ctx.org_id, kind=kind, channel=channel
        )
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.message_template_deleted",
        entity_type="message_template", entity_id=template_id,
        detail={"kind": kind, "channel": channel},
    )
    await db.commit()
    return {"deleted": True}


@router.delete("/demo-teams/{team_id}")
async def delete_demo_team(
    team_id: str,
    ctx: OrgContext = Depends(require_permission("manage_teams")),
    db: AsyncSession = Depends(get_db),
):
    """Member rows go with it: the schema declares no `ondelete=` anywhere, so
    the handler is the only thing that will clean them up."""
    team = (
        await db.execute(
            select(DemoTeam).where(
                DemoTeam.id == team_id, DemoTeam.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if team is None:
        raise NotFoundError("Demo team not found")

    booked = (
        await db.execute(
            select(func.count()).select_from(Demo).where(
                Demo.org_id == ctx.org_id, Demo.team_id == team_id
            )
        )
    ).scalar_one()
    if booked:
        raise ConflictError(
            f"{booked} demo(s) are booked against '{team.name}'."
        )

    await db.execute(
        sa_delete(DemoTeamMember.__table__).where(
            DemoTeamMember.__table__.c.team_id == team_id
        )
    )
    await db.delete(team)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.demo_team_deleted",
        entity_type="demo_team", entity_id=team_id, detail={"name": team.name},
    )
    await db.commit()
    return {"deleted": True}
```

Add the models these need to `admin.py`'s imports:

```python
from app.models.demo import Demo, DemoTeam, DemoTeamMember
from app.models.project import Playbook, Project
from app.models.proposal import Proposal
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_deletes_admin.py -v`
Expected: 6 passed.

- [ ] **Step 6: Checkpoint**

`python -m pytest -q` green. Mark change #6 done in `09_BACKEND_CHANGES.md`.

---

