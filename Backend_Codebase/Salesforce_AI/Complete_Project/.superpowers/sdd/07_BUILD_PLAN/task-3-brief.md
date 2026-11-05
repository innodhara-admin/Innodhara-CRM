### Task 3: `GET /playbooks` *(change #3)*

**Files:**
- Modify: `app/api/ops.py` — add `list_playbooks`
- Test: `tests/test_dashboard_reads.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/v1/playbooks?program_id=&phase=&current_only=` → `list[dict]` with keys `id`, `program_id`, `phase`, `entries`, `version`, `is_current`, `updated_by`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_reads.py
"""Read paths a setup console needs and the API did not have."""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _program(client, token, code: str) -> str:
    resp = await client.post(
        "/api/v1/admin/programs",
        headers=auth(token),
        json={"name": f"Programme {code}", "code": code,
              "description": "Commissioning and handover of capacity."},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_playbooks_can_be_read_back(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "PBREAD")
    entries = [{"title": "Confirm site access", "required_skill": "scheduling",
                "offset_days": -7, "priority": "P1", "visible_to_client": False}]
    wrote = await client.post(
        "/api/v1/playbooks",
        headers=auth(token),
        json={"program_id": program_id, "phase": "preparation", "entries": entries},
    )
    assert wrote.status_code == 200, wrote.text

    resp = await client.get(
        f"/api/v1/playbooks?program_id={program_id}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["phase"] == "preparation"
    assert rows[0]["entries"] == entries
    assert rows[0]["is_current"] is True


async def test_playbooks_current_only_hides_superseded(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "PBVER")
    for title in ("First wave", "Second wave"):
        resp = await client.post(
            "/api/v1/playbooks",
            headers=auth(token),
            json={"program_id": program_id, "phase": "delivery",
                  "entries": [{"title": title, "required_skill": "general",
                               "offset_days": 0, "priority": "P2",
                               "visible_to_client": False}]},
        )
        assert resp.status_code == 200, resp.text

    current = await client.get(
        f"/api/v1/playbooks?program_id={program_id}&phase=delivery",
        headers=auth(token),
    )
    assert len(current.json()) == 1
    assert current.json()[0]["version"] == 2

    every = await client.get(
        f"/api/v1/playbooks?program_id={program_id}&phase=delivery"
        "&current_only=false",
        headers=auth(token),
    )
    assert len(every.json()) == 2


async def test_playbooks_are_org_scoped(client, org_a, org_b):
    resp = await client.get("/api/v1/playbooks", headers=auth(org_b["admin_token"]))
    assert resp.status_code == 200
    assert resp.json() == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: FAIL — 405 or 404 on `GET /api/v1/playbooks`.

- [ ] **Step 3: Add the route**

In `app/api/ops.py`, immediately **before** the existing
`@router.get("/playbooks/suggestions")`:

```python
@router.get("/playbooks")
async def list_playbooks(
    program_id: str | None = None,
    phase: str | None = None,
    current_only: bool = True,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """A go-live prerequisite that had a write path and no read path: without
    this a console can only overwrite task waves blindly."""
    stmt = select(Playbook).where(Playbook.org_id == ctx.org_id)
    if program_id:
        stmt = stmt.where(Playbook.program_id == program_id)
    if phase:
        stmt = stmt.where(Playbook.phase == phase)
    if current_only:
        stmt = stmt.where(Playbook.is_current.is_(True))
    rows = (
        await db.execute(stmt.order_by(Playbook.phase, Playbook.version))
    ).scalars().all()
    return [
        {
            "id": p.id,
            "program_id": p.program_id,
            "phase": p.phase,
            "entries": p.entries,
            "version": p.version,
            "is_current": p.is_current,
            "updated_by": p.updated_by,
        }
        for p in rows
    ]
```

> `/playbooks` and `/playbooks/suggestions` are distinct literal paths, not a
> prefix collision, so declaration order does not affect matching. Placed
> together only to keep the playbook routes in one block.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: 3 passed.

- [ ] **Step 5: Checkpoint**

Run `python -m pytest -q` — green. Mark change #3 done in `09_BACKEND_CHANGES.md`.

---

