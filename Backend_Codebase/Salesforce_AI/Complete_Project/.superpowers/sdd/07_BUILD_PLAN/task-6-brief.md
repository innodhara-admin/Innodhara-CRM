### Task 6: `POST /admin/reset` *(change #5)*

**Files:**
- Modify: `app/api/admin.py` — add `ResetRequest` and `reset_organisation`
- Test: `tests/test_dashboard_reset.py`

**Interfaces:**
- Consumes: `app.core.reset_taxonomy.deletion_order`, `KEEP`, `CONFIG`, `REPLACE`, `WIPE`.
- Produces: `POST /api/v1/admin/reset` → `{"org": {"id", "name"}, "counts": dict[str, int], "total": int, "applied": bool}`.

> ⚠ **The `org_a` / `org_b` fixtures are session-scoped. A reset test that used
> them would wipe data every later test depends on.** Every test below creates a
> throwaway organisation with `create_org(...)`. This is not optional.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_reset.py
"""The reset endpoint: the only route in the system that destroys in bulk.

Every test creates its own organisation — org_a/org_b are session-scoped and
wiping them would corrupt every test that runs afterwards.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio


async def _seed(client, token) -> None:
    """One lead (transactional) + one program (catalogue) + one skill (config)."""
    lead = await client.post(
        "/api/v1/leads", headers=auth(token), json={"name": "Meridian Data"}
    )
    assert lead.status_code == 200, lead.text
    prog = await client.post(
        "/api/v1/admin/programs", headers=auth(token),
        json={"name": "Commissioning", "code": "RSTC", "description": "Halls."},
    )
    assert prog.status_code == 200, prog.text
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    skill = await client.post(
        "/api/v1/skills", headers=auth(token),
        json={"user_id": me["user_id"], "skill": "scheduling", "level": "good"},
    )
    assert skill.status_code == 200, skill.text


async def test_dry_run_counts_without_deleting(client, super_token):
    org = await create_org(client, super_token, name="Reset Dry",
                           slug="reset-dry", domain="reset-dry-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": True, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["counts"]["leads"] == 1
    assert body["counts"]["programs"] == 1
    assert body["counts"]["user_skills"] == 1

    still_there = await client.get("/api/v1/leads", headers=auth(token))
    assert len(still_there.json()) == 1, "a dry run must delete nothing"


async def test_apply_requires_the_org_name_echoed_back(client, super_token):
    org = await create_org(client, super_token, name="Reset Echo",
                           slug="reset-echo", domain="reset-echo-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    wrong = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "confirm_org_name": "Reset Wrong"},
    )
    assert wrong.status_code == 422
    assert "Reset Echo" in wrong.text

    missing = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True},
    )
    assert missing.status_code == 422

    assert len((await client.get("/api/v1/leads", headers=auth(token))).json()) == 1


async def test_flags_clear_only_their_own_bucket(client, super_token):
    org = await create_org(client, super_token, name="Reset Flags",
                           slug="reset-flags", domain="reset-flags-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": False, "wipe_org_config": False,
              "confirm_org_name": "Reset Flags"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is True

    assert (await client.get("/api/v1/leads", headers=auth(token))).json() == []
    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 1
    assert len((await client.get("/api/v1/skills", headers=auth(token))).json()) == 1


async def test_keep_survives_a_full_reset_and_the_session_still_works(
    client, super_token
):
    org = await create_org(client, super_token, name="Reset Full",
                           slug="reset-full", domain="reset-full-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Full"},
    )
    assert resp.status_code == 200, resp.text

    me = await client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200, "the resetting account must survive its own reset"
    assert len((await client.get(
        "/api/v1/admin/users", headers=auth(token))).json()) >= 1
    assert (await client.get(
        "/api/v1/admin/settings", headers=auth(token))).status_code == 200


async def test_another_organisation_is_untouched(client, super_token):
    keeper = await create_org(client, super_token, name="Reset Bystander",
                              slug="reset-bystand",
                              domain="reset-bystand-example.com")
    await _seed(client, keeper["admin_token"])
    victim = await create_org(client, super_token, name="Reset Victim",
                              slug="reset-victim",
                              domain="reset-victim-example.com")
    await _seed(client, victim["admin_token"])

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(victim["admin_token"]),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Victim"},
    )
    assert resp.status_code == 200, resp.text

    kept = keeper["admin_token"]
    assert len((await client.get("/api/v1/leads", headers=auth(kept))).json()) == 1
    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(kept))).json()) == 1
    assert len((await client.get("/api/v1/skills", headers=auth(kept))).json()) == 1


async def test_reset_writes_an_audit_row_that_survives(client, super_token):
    org = await create_org(client, super_token, name="Reset Audit",
                           slug="reset-audit", domain="reset-audit-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Audit"},
    )
    assert resp.status_code == 200, resp.text

    audit = await client.get("/api/v1/admin/audit", headers=auth(token))
    assert audit.status_code == 200, audit.text
    actions = [row["action"] for row in audit.json()]
    assert "admin.org_reset" in actions, (
        "audit_log is in KEEP precisely so this row outlives the reset"
    )


async def test_a_sales_agent_cannot_reset(client, org_a):
    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(org_a["agent_token"]),
        json={"dry_run": True, "wipe_transactional": True},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reset.py -v`
Expected: FAIL — 404 on `POST /api/v1/admin/reset`.

- [ ] **Step 3: Add the request model and route**

At the end of `app/api/admin.py`:

```python
# ══════════════════════════ Reset ══════════════════════════════════════════
class ResetRequest(BaseModel):
    dry_run: bool = True
    wipe_transactional: bool = True
    wipe_catalogue: bool = False
    wipe_org_config: bool = False
    confirm_org_name: str | None = None


@router.post("/reset")
async def reset_organisation(
    body: ResetRequest,
    ctx: OrgContext = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Bulk removal, scoped to one organisation.

    Unlike scripts/reset_for_datacentre_demo.py — which deletes globally and is
    safe only because the demo database holds one tenant — every statement here
    carries `WHERE org_id = :org`. Tables whose org_id is nullable (jobs,
    llm_usage) keep their platform-level rows, which belong to no tenant.
    """
    org = (
        await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
    ).scalar_one()

    if not body.dry_run and (body.confirm_org_name or "").strip() != org.name:
        raise ValidationFailedError(
            f"To apply this reset, send confirm_org_name exactly as '{org.name}'"
        )

    tables = deletion_order(
        transactional=body.wipe_transactional,
        catalogue=body.wipe_catalogue,
        org_config=body.wipe_org_config,
    )

    counts: dict[str, int] = {}
    for name in tables:
        table = Base.metadata.tables[name]
        scoped = table.c.org_id == ctx.org_id
        counts[name] = (
            await db.execute(select(func.count()).select_from(table).where(scoped))
        ).scalar_one()
        if not body.dry_run and counts[name]:
            await db.execute(sa_delete(table).where(scoped))

    total = sum(counts.values())
    if not body.dry_run:
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id, action="admin.org_reset",
            entity_type="organisation", entity_id=ctx.org_id,
            detail={
                "counts": counts,
                "total": total,
                "wipe_transactional": body.wipe_transactional,
                "wipe_catalogue": body.wipe_catalogue,
                "wipe_org_config": body.wipe_org_config,
            },
        )
        await db.commit()

    return {
        "org": {"id": org.id, "name": org.name},
        "counts": counts,
        "total": total,
        "applied": not body.dry_run,
    }
```

Extend the imports at the top of `app/api/admin.py`:

```python
from sqlalchemy import delete as sa_delete, func, select

from app.core.reset_taxonomy import deletion_order
from app.database import Base, get_db
```

> `sa_delete` is aliased because `admin.py` has no other `delete` symbol and an
> unaliased import reads as a route verb at a glance.
> The audit row is written last so its `counts` are the counts actually applied.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_reset.py -v`
Expected: 7 passed.

- [ ] **Step 5: Confirm the suite is not corrupted**

Run: `python -m pytest -q`
Expected: full suite green. **A failure in an unrelated module here means a
reset test touched a session-scoped fixture org** — find it and give it its own
`create_org`.

- [ ] **Step 6: Checkpoint**

Both green. Mark change #5 done in `09_BACKEND_CHANGES.md`.

---

