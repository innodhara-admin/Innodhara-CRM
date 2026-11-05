### Task 7: Guarded deletes in `ops.py` *(change #6, part 1 of 2)*

Three routes: skills, playbooks, vendors.

**Files:**
- Modify: `app/api/ops.py`
- Test: `tests/test_dashboard_deletes_ops.py`

**Interfaces:**
- Produces: `DELETE /api/v1/skills?user_id=&skill=`, `DELETE /api/v1/playbooks/{playbook_id}`, `DELETE /api/v1/vendors/{vendor_id}`. Each returns `{"deleted": True}` or raises `ConflictError` (409) / `NotFoundError` (404).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_deletes_ops.py
"""Catalogue deletes are for pre-go-live mistakes. Anything a live record
depends on must refuse, with a reason (D7)."""
from __future__ import annotations

import pytest

from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio


async def test_skill_delete_uses_the_natural_key(client, super_token):
    org = await create_org(client, super_token, name="Del Skill",
                           slug="del-skill", domain="del-skill-example.com")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()

    await client.post("/api/v1/skills", headers=auth(token),
                      json={"user_id": me["user_id"], "skill": "typo_skill",
                            "level": "basic"})
    assert len((await client.get("/api/v1/skills", headers=auth(token))).json()) == 1

    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={me['user_id']}&skill=typo_skill",
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert (await client.get("/api/v1/skills", headers=auth(token))).json() == []


async def test_skill_delete_refuses_when_open_work_needs_it(client, super_token):
    org = await create_org(client, super_token, name="Del Skill Busy",
                           slug="del-skill-busy",
                           domain="del-skill-busy-example.com")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    await client.post("/api/v1/skills", headers=auth(token),
                      json={"user_id": me["user_id"], "skill": "wiring",
                            "level": "expert"})
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Site One"})).json()
    task = await client.post(
        "/api/v1/action-items", headers=auth(token),
        json={"lead_id": lead["id"], "title": "Terminate the runs",
              "required_skill": "wiring"},
    )
    assert task.status_code == 200, task.text

    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={me['user_id']}&skill=wiring",
        headers=auth(token),
    )
    assert resp.status_code == 409
    assert "wiring" in resp.text


async def test_missing_skill_is_a_404(client, org_a):
    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={org_a['agent_id']}&skill=never_held",
        headers=auth(org_a["admin_token"]),
    )
    assert resp.status_code == 404


async def test_playbook_delete_promotes_the_previous_version(client, super_token):
    org = await create_org(client, super_token, name="Del Playbook",
                           slug="del-playbook",
                           domain="del-playbook-example.com")
    token = org["admin_token"]
    program = (await client.post(
        "/api/v1/admin/programs", headers=auth(token),
        json={"name": "Handover", "code": "DPB", "description": "Handover."},
    )).json()

    for title in ("v1 wave", "v2 wave"):
        await client.post("/api/v1/playbooks", headers=auth(token),
                          json={"program_id": program["id"], "phase": "closure",
                                "entries": [{"title": title,
                                             "required_skill": "general",
                                             "offset_days": 0, "priority": "P3",
                                             "visible_to_client": False}]})

    every = (await client.get(
        f"/api/v1/playbooks?program_id={program['id']}&current_only=false",
        headers=auth(token))).json()
    current = next(p for p in every if p["is_current"])
    assert current["version"] == 2

    resp = await client.delete(
        f"/api/v1/playbooks/{current['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text

    remaining = (await client.get(
        f"/api/v1/playbooks?program_id={program['id']}", headers=auth(token))).json()
    assert len(remaining) == 1
    assert remaining[0]["version"] == 1, (
        "deleting the current version must promote its predecessor"
    )


async def test_vendor_delete_refuses_when_a_task_waits_on_it(client, super_token):
    org = await create_org(client, super_token, name="Del Vendor",
                           slug="del-vendor", domain="del-vendor-example.com")
    token = org["admin_token"]
    vendor = (await client.post("/api/v1/vendors", headers=auth(token),
                                json={"name": "Cable Supply Co"})).json()
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Site Two"})).json()
    task = (await client.post(
        "/api/v1/action-items", headers=auth(token),
        json={"lead_id": lead["id"], "title": "Await cable delivery"},
    )).json()
    waited = await client.post(
        f"/api/v1/tasks/{task['id']}/external-wait", headers=auth(token),
        json={"vendor_id": vendor["id"], "promised_date": "2026-09-01"},
    )
    assert waited.status_code == 200, waited.text

    resp = await client.delete(
        f"/api/v1/vendors/{vendor['id']}", headers=auth(token)
    )
    assert resp.status_code == 409
    assert "Cable Supply Co" in resp.text or "task" in resp.text.lower()


async def test_unreferenced_vendor_deletes(client, super_token):
    org = await create_org(client, super_token, name="Del Vendor Free",
                           slug="del-vendor-free",
                           domain="del-vendor-free-example.com")
    token = org["admin_token"]
    vendor = (await client.post("/api/v1/vendors", headers=auth(token),
                                json={"name": "Unused Supplier"})).json()

    resp = await client.delete(
        f"/api/v1/vendors/{vendor['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/v1/vendors", headers=auth(token))).json() == []


async def test_deletes_are_audited(client, super_token):
    org = await create_org(client, super_token, name="Del Audit",
                           slug="del-audit", domain="del-audit-example.com")
    token = org["admin_token"]
    vendor = (await client.post("/api/v1/vendors", headers=auth(token),
                                json={"name": "Audited Supplier"})).json()
    await client.delete(f"/api/v1/vendors/{vendor['id']}", headers=auth(token))

    audit = (await client.get("/api/v1/admin/audit", headers=auth(token))).json()
    assert "ops.vendor_deleted" in [row["action"] for row in audit], (
        "delete_approval_rule writes no audit row; that is not inherited (D13)"
    )
```

> **Before writing the implementation, confirm the two helper routes the tests
> use actually exist as written**: `POST /api/v1/action-items` and the
> external-wait route on `/tasks/{id}`. Run
> `python -c "import app.main as m; print([r.path for r in m.app.routes if 'external' in r.path or 'action-items' in r.path])"`
> and adjust the test's setup calls to the real paths and bodies before Step 2.
> Do **not** change what is being asserted.

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_deletes_ops.py -v`
Expected: FAIL — 405 on every DELETE.

- [ ] **Step 3: Add the skill delete**

In `app/api/ops.py`, after `list_skills`:

```python
@router.delete("/skills")
async def delete_skill(
    user_id: str,
    skill: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Natural key, not a row id — GET /skills does not return one, and this
    mirrors POST /skills, which upserts on the same pair."""
    # This role tuple is duplicated from POST /skills above, deliberately.
    # Centralising it into core/permissions.py _MATRIX is Part F #11, which is
    # DEFERRED — the backend change list is closed at eight (05_DECISIONS.md
    # Part 3), and moving it would be a ninth. Kept identical to its sibling so
    # the two cannot drift apart while they both exist.
    if ctx.role not in ("org_admin", "sales_lead", "operations_lead"):
        raise PermissionDeniedError("Only the admin or a lead can adjust skills")
    row = (
        await db.execute(
            select(UserSkill).where(
                UserSkill.org_id == ctx.org_id,
                UserSkill.user_id == user_id,
                UserSkill.skill == skill,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"No '{skill}' skill recorded for that person")

    others = (
        await db.execute(
            select(func.count()).select_from(UserSkill).where(
                UserSkill.org_id == ctx.org_id,
                UserSkill.skill == skill,
                UserSkill.user_id != user_id,
            )
        )
    ).scalar_one()
    if others == 0:
        open_work = (
            await db.execute(
                select(func.count()).select_from(ActionItem).where(
                    ActionItem.org_id == ctx.org_id,
                    ActionItem.required_skill == skill,
                    ActionItem.status.in_(("open", "in_progress", "pending_review")),
                )
            )
        ).scalar_one()
        if open_work:
            raise ConflictError(
                f"{open_work} open task(s) need '{skill}' and nobody else holds "
                f"it. Give the skill to someone else first, or close that work."
            )

    await db.delete(row)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="ops.skill_deleted",
        entity_type="user_skill", entity_id=row.id,
        detail={"user_id": user_id, "skill": skill},
    )
    await db.commit()
    return {"deleted": True}
```

- [ ] **Step 4: Add the playbook delete**

```python
@router.delete("/playbooks/{playbook_id}")
async def delete_playbook(
    playbook_id: str,
    ctx: OrgContext = Depends(require_permission("manage_programs")),
    db: AsyncSession = Depends(get_db),
):
    """Nothing references a playbook, so there is no reference guard. Removing
    the current version promotes its predecessor — the un-supersede path the
    API has never had."""
    row = (
        await db.execute(
            select(Playbook).where(
                Playbook.id == playbook_id, Playbook.org_id == ctx.org_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Playbook not found")

    was_current, program_id, phase = row.is_current, row.program_id, row.phase
    await db.delete(row)
    await db.flush()

    if was_current:
        predecessor = (
            await db.execute(
                select(Playbook)
                .where(
                    Playbook.org_id == ctx.org_id,
                    Playbook.program_id == program_id,
                    Playbook.phase == phase,
                )
                .order_by(Playbook.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if predecessor is not None:
            predecessor.is_current = True

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="ops.playbook_deleted",
        entity_type="playbook", entity_id=playbook_id,
        detail={"program_id": program_id, "phase": phase},
    )
    await db.commit()
    return {"deleted": True}
```

- [ ] **Step 5: Add the vendor delete**

```python
@router.delete("/vendors/{vendor_id}")
async def delete_vendor(
    vendor_id: str,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """action_items.external_wait is a JSON blob no foreign key can reach, so
    the reference check is an explicit scan (04_OPEN_QUESTIONS.md Q5)."""
    row = (
        await db.execute(
            select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Vendor not found")

    waiting = (
        await db.execute(
            select(ActionItem).where(
                ActionItem.org_id == ctx.org_id,
                ActionItem.external_wait.is_not(None),
            )
        )
    ).scalars().all()
    blockers = [
        t for t in waiting if (t.external_wait or {}).get("vendor_id") == vendor_id
    ]
    if blockers:
        raise ConflictError(
            f"{len(blockers)} task(s) are waiting on '{row.name}'. "
            f"Clear those before removing the vendor."
        )

    await db.delete(row)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="ops.vendor_deleted",
        entity_type="vendor", entity_id=vendor_id, detail={"name": row.name},
    )
    await db.commit()
    return {"deleted": True}
```

Ensure `ops.py` imports everything used above — add whichever are missing:

```python
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.models.action_item import ActionItem
from app.models.finance import Vendor
from app.models.project import Playbook
from app.models.user import UserSkill
```

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_deletes_ops.py -v`
Expected: 7 passed.

- [ ] **Step 7: Checkpoint**

`python -m pytest -q` green.

---

