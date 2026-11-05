# Innodhara Setup Console — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the eight accepted backend changes with full test coverage, then build a web console that takes an organisation through the 16-step go-live checklist over HTTP.

**Architecture:** Phase 1 is additive backend work in `app/api/admin.py`, `app/api/ops.py`, `app/main.py` and one new `app/core/reset_taxonomy.py`. Phase 2 is a React/TypeScript SPA under `Dashboard/`, whose entire type layer is generated from the backend's `/openapi.json` and served by FastAPI from `Dashboard/dist/`.

**Tech Stack:** FastAPI · async SQLAlchemy 2.0 · pytest (`asyncio_mode=auto`) · React 19 · TypeScript · Vite · Zod · TanStack Query · Vitest

> **Read `08_PROGRESS_AND_HANDOFF.md` first.** It states where the work actually
> stands. This file is the order to build in; `06_DESIGN.md` is what to build and
> `05_DECISIONS.md` is why.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **The backend change list is CLOSED at ten.** Anything requiring an eleventh stops the work and goes back to the owner. The ten are enumerated in `05_DECISIONS.md` Part 3. *(It was closed at eight for Tasks 1–10; the owner reopened it once, for changes #9 and #10 — D24, Tasks 10a–10c — after that rule did exactly what it exists to do.)*
- **The dashboard never writes to the database directly** (D3). HTTP API only, including the reset.
- **`get_org_context` must keep rejecting `super_admin`** (D1, Q14). No task may weaken it.
- **Every destructive route calls `audit_service.record`** (D13). No exceptions, including the eight DELETEs and the reset.
- **No new column, no migration.** There is no Alembic; `create_all` never alters an existing table.
- **Nothing dashboard-related lands under `app/`** except the eight changes themselves (D19). The OpenAPI dumper lives at `Dashboard/tools/`, the bundle at `Dashboard/dist/`.
- **No `Idempotency-Key` is minted and no write is ever auto-retried** (D17). The server reads no headers.
- **Product name on user-visible surfaces is `Innodhara`** (D15). Code identifiers stay `YuviPep`. One design token.
- **Constraint captions cite file and symbol, never line numbers** — `admin.py · CreateUserRequest`.
- **Reset taxonomy is four buckets: KEEP 4 · CONFIG 2 · REPLACE 7 · WIPE 42 = 55** (D16).
- **`users` is never deleted by any flag combination.** The reset runs under the session it would destroy.

### This repository is not under git

`Complete_Project` is **not a git repository** (verified). Every task therefore ends
with a **Checkpoint** step rather than a commit: run the named verification and
confirm it passes before starting the next task.

Running `git init` here first would make the plan's commit discipline real and give
per-task rollback. That is the owner's call, not this plan's — the plan works either
way.

### Test conventions in this repo

Read from `tests/conftest.py`. Do not invent alternatives.

- `pytest.ini` sets `asyncio_mode = auto`; every test module starts `pytestmark = pytest.mark.asyncio`.
- Fixtures: `client`, `super_token`, `org_a`, `org_b` — **all `scope="session"`**.
- Helpers: `auth(token) -> dict`, `login(client, email, password)`, `create_org(client, super_token, *, name, slug, domain)`.
- `create_org` returns a dict including `admin_token`; `org_a` also carries `agent_token` and `agent_id`.

> ⚠ **The fixtures are session-scoped, so a test that wipes `org_a` corrupts every
> test that runs after it.** Any test touching the reset endpoint **must create its
> own throwaway organisation** with `create_org(...)` inside the test body. This is
> stated again in Task 6, where it bites.

---

# PHASE 1 — Backend (Tasks 1–10)

Ships working, testable software on its own: the API becomes complete for any
client, not just this console.

## File Structure — Phase 1

| File | Responsibility |
|---|---|
| `app/api/admin.py` *(modify)* | staff fields, `GET /users/{id}`, honest settings, 5 DELETEs, reset route |
| `app/api/ops.py` *(modify)* | `GET /playbooks`, widened `GET /vendors`, 3 DELETEs |
| `app/core/reset_taxonomy.py` *(create)* | the four buckets and their ordering — the single source of truth, imported by both the route and its test |
| `app/main.py` *(modify)* | conditional `StaticFiles` mount |
| `tests/test_dashboard_staff.py` *(create)* | Task 1 |
| `tests/test_dashboard_settings_honesty.py` *(create)* | Task 2 |
| `tests/test_dashboard_reads.py` *(create)* | Tasks 3, 4 |
| `tests/test_reset_taxonomy.py` *(create)* | Task 5 — the partition guard |
| `tests/test_dashboard_reset.py` *(create)* | Task 6 |
| `tests/test_dashboard_deletes_ops.py` *(create)* | Task 7 |
| `tests/test_dashboard_deletes_admin.py` *(create)* | Task 8 |
| `tests/test_dashboard_mount.py` *(create)* | Task 9 |
| `BACKEND_README.md` *(modify)* | counts and §7.1 rows — Task 10 |

---

### Task 1: Staff fields and staff detail *(changes #1 and #4)*

**Files:**
- Modify: `app/api/admin.py` — `CreateUserRequest`, `UpdateUserRequest`, `UserResponse`, `_user_response`, `register_staff`, `update_staff`; add `get_staff_member`
- Test: `tests/test_dashboard_staff.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/v1/admin/users/{user_id}` → `UserResponse`. `UserResponse` gains `department: str | None`, `designation: str | None`, `whatsapp_number: str | None`, `max_open_tasks: int`, `working_days: list[str] | None`, `require_action_item_review: bool | None`.

- [x] **Step 1: Write the failing test**

```python
# tests/test_dashboard_staff.py
"""Staff fields the go-live checklist names but the API could not set (D4)."""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def test_department_survives_create_and_is_readable(client, org_a):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=auth(org_a["admin_token"]),
        json={
            "email": "ops.lead@alpha-example.com",
            "name": "Omar Ops",
            "role": "operations_lead",
            "department": "operations",
            "designation": "Head of Delivery",
            "whatsapp_number": "+919000000001",
            "max_open_tasks": 12,
            "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert created["department"] == "operations"
    assert created["max_open_tasks"] == 12

    detail = await client.get(
        f"/api/v1/admin/users/{created['id']}", headers=auth(org_a["admin_token"])
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["designation"] == "Head of Delivery"
    assert body["whatsapp_number"] == "+919000000001"
    assert body["working_days"] == ["Mon", "Tue", "Wed", "Thu", "Fri"]


async def test_unknown_department_is_refused(client, org_a):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=auth(org_a["admin_token"]),
        json={
            "email": "bad.dept@alpha-example.com",
            "name": "Bad Dept",
            "role": "sales_agent",
            "department": "marketing",
        },
    )
    assert resp.status_code == 422
    assert "marketing" in resp.text


async def test_staff_detail_is_org_scoped(client, org_a, org_b):
    listing = await client.get(
        "/api/v1/admin/users", headers=auth(org_a["admin_token"])
    )
    victim_id = listing.json()[0]["id"]
    resp = await client.get(
        f"/api/v1/admin/users/{victim_id}", headers=auth(org_b["admin_token"])
    )
    assert resp.status_code == 404


async def test_patch_updates_the_new_fields(client, org_a):
    resp = await client.patch(
        f"/api/v1/admin/users/{org_a['agent_id']}",
        headers=auth(org_a["admin_token"]),
        json={"department": "sales", "max_open_tasks": 5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["department"] == "sales"
    assert resp.json()["max_open_tasks"] == 5
```

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_staff.py -v`
Expected: FAIL — `KeyError: 'department'` on the first test, 404 on the detail route.

- [x] **Step 3: Widen the request and response models**

In `app/api/admin.py`, replace the three model classes and `_user_response`:

```python
class CreateUserRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=2)
    role: str
    phone: str | None = None
    department: str | None = None
    designation: str | None = None
    whatsapp_number: str | None = None
    max_open_tasks: int | None = Field(default=None, ge=1, le=100)
    working_days: list[str] | None = None


class UpdateUserRequest(BaseModel):
    name: str | None = None
    role: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    require_action_item_review: bool | None = None
    department: str | None = None
    designation: str | None = None
    whatsapp_number: str | None = None
    max_open_tasks: int | None = Field(default=None, ge=1, le=100)
    working_days: list[str] | None = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    phone: str | None
    is_active: bool
    department: str | None = None
    designation: str | None = None
    whatsapp_number: str | None = None
    max_open_tasks: int | None = None
    working_days: list[str] | None = None
    require_action_item_review: bool | None = None


def _user_response(u: User) -> UserResponse:
    return UserResponse(
        id=u.id, email=u.email, name=u.name, role=u.role,
        phone=u.phone, is_active=u.is_active,
        department=u.department, designation=u.designation,
        whatsapp_number=u.whatsapp_number, max_open_tasks=u.max_open_tasks,
        working_days=u.working_days,
        require_action_item_review=u.require_action_item_review,
    )


def _validated_department(value: str | None) -> str | None:
    """`Department` is sales | operations | accounts. Note `accounts` is a
    department but not a role — the accounts executive is an operations_agent."""
    if value is None:
        return None
    try:
        return Department(value).value
    except ValueError:
        raise ValidationFailedError(
            f"Unknown department '{value}'. Use one of: "
            + ", ".join(d.value for d in Department)
        )
```

Add `Department` to the existing constants import:

```python
from app.core.constants import (
    ORG_ROLES, Department, MessageChannel, Role, TemplateKind,
)
```

- [x] **Step 4: Set the fields on create**

In `register_staff`, after the `temp_password` line, replace the `User(...)`
construction:

```python
    temp_password = secrets.token_urlsafe(9)
    user = User(
        org_id=ctx.org_id,
        email=body.email.lower(),
        name=body.name,
        role=role.value,
        phone=body.phone,
        password_hash=hash_password(temp_password),
        must_change_password=True,
        department=_validated_department(body.department),
        designation=body.designation,
        whatsapp_number=body.whatsapp_number,
        working_days=body.working_days,
    )
    if body.max_open_tasks is not None:
        user.max_open_tasks = body.max_open_tasks
```

`max_open_tasks` is set conditionally so `None` falls through to the model
default of 8 rather than overwriting it with null.

- [x] **Step 5: Apply the fields on update**

In `update_staff`, after the existing `if body.name is not None:` block and
before the commit, add:

```python
    if body.department is not None:
        user.department = _validated_department(body.department)
    if body.designation is not None:
        user.designation = body.designation
    if body.whatsapp_number is not None:
        user.whatsapp_number = body.whatsapp_number
    if body.max_open_tasks is not None:
        user.max_open_tasks = body.max_open_tasks
    if body.working_days is not None:
        user.working_days = body.working_days
```

- [x] **Step 6: Add the staff detail route**

Immediately after `list_staff` in `app/api/admin.py`:

```python
@router.get("/users/{user_id}", response_model=UserResponse)
async def get_staff_member(
    user_id: str,
    ctx: OrgContext = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    """A staff-detail screen cannot be built from `list_staff` alone."""
    user = (
        await db.execute(
            select(User).where(User.id == user_id, User.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    return _user_response(user)
```

> Declare this **after** `GET /users` and before any other `/users/...` route.
> FastAPI matches in declaration order and `/users/{user_id}` would otherwise
> shadow a literal sibling path added later.

- [x] **Step 7: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_staff.py -v`
Expected: 4 passed.

- [x] **Step 8: Confirm nothing else broke**

Run: `python -m pytest -q`
Expected: the full suite passes; the count rises by 4.

- [x] **Step 9: Checkpoint**

Both commands above green. Record the new total in `09_BACKEND_CHANGES.md`
against changes #1 and #4.

---

### Task 2: Honest delivery mode *(change #2)*

**Files:**
- Modify: `app/api/admin.py` — `_settings_response`
- Test: `tests/test_dashboard_settings_honesty.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/v1/admin/settings` gains `email_mode`, `whatsapp_mode`, `calendar_mode`, `inbound_email_mode` (all `str`, read-only). The three `*_configured` booleans change meaning to *credentials AND mode*.

- [x] **Step 1: Write the failing test**

```python
# tests/test_dashboard_settings_honesty.py
"""The API must not report a setup step as done when it will silently fail.

Manual p.7: "otherwise approved messages are written to a file and everyone
believes they were sent."  conftest pins EMAIL_MODE=dry_run.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def test_settings_expose_the_process_wide_modes(client, org_a):
    resp = await client.get(
        "/api/v1/admin/settings", headers=auth(org_a["admin_token"])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email_mode"] == "dry_run"
    assert body["calendar_mode"] == "off"
    assert body["inbound_email_mode"] == "off"
    assert "whatsapp_mode" in body


async def test_email_configured_is_false_while_mode_is_dry_run(client, org_a):
    stored = await client.put(
        "/api/v1/admin/integrations/email",
        headers=auth(org_a["admin_token"]),
        json={"smtp_username": "sales@alpha-example.com",
              "smtp_app_password": "abcd efgh ijkl mnop"},
    )
    assert stored.status_code == 200, stored.text

    resp = await client.get(
        "/api/v1/admin/settings", headers=auth(org_a["admin_token"])
    )
    body = resp.json()
    assert body["email_credentials_stored"] is True
    assert body["email_integration_configured"] is False, (
        "credentials are stored but EMAIL_MODE=dry_run, so no mail will leave"
    )
```

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_settings_honesty.py -v`
Expected: FAIL — `KeyError: 'email_mode'`, and `email_integration_configured` is `True`.

- [x] **Step 3: Rewrite `_settings_response`'s tail**

In `app/api/admin.py`, replace the last three keys of `_settings_response` with:

```python
        # ── Delivery honesty (D5) ────────────────────────────────────────────
        # Two halves are required for anything to leave: stored credentials AND
        # a process-wide mode. email_service returns a "dry_run:<path>" file
        # unless email_mode == "smtp" AND creds is not None. Reporting only the
        # first half is how "everyone believes they were sent" happens.
        "email_mode": _cfg.email_mode,
        "whatsapp_mode": _cfg.whatsapp_mode,
        "calendar_mode": _cfg.calendar_mode,
        "inbound_email_mode": _cfg.inbound_email_mode,
        "email_credentials_stored": _email_creds,
        "whatsapp_credentials_stored": _whatsapp_creds,
        "calendar_credentials_stored": _calendar_creds,
        "email_integration_configured": _email_creds and _cfg.email_mode == "smtp",
        "whatsapp_integration_configured": (
            _whatsapp_creds and _cfg.whatsapp_mode == "cloud_api"
        ),
        "calendar_integration_configured": (
            _calendar_creds and _cfg.calendar_mode == "google"
        ),
    }
```

and open the function body with the three locals it now needs:

```python
def _settings_response(s: OrgSettings) -> dict[str, Any]:
    _cfg = get_settings()
    _email_creds = bool((s.email_integration or {}).get("smtp_username"))
    _whatsapp_creds = bool((s.whatsapp_integration or {}).get("phone_number_id"))
    _calendar_creds = bool((s.calendar_integration or {}).get("calendar_id"))
    return {
```

Add the config import beside the existing ones:

```python
from app.config import get_settings
```

> `*_credentials_stored` is kept as a separate key deliberately. Without it the
> console could not distinguish "no credentials" from "server is in dry-run" —
> that is Q3 option (c), which was rejected for exactly this reason.

- [x] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_settings_honesty.py -v`
Expected: 2 passed.

- [x] **Step 5: Confirm no existing test asserted the old meaning**

Run: `python -m pytest -q`
Expected: full suite passes. If anything fails on
`email_integration_configured`, it was asserting the misleading behaviour —
update that assertion, and note it in `09_BACKEND_CHANGES.md`.

- [x] **Step 6: Checkpoint**

Both green. Mark change #2 done in `09_BACKEND_CHANGES.md`.

---

### Task 3: `GET /playbooks` *(change #3)*

**Files:**
- Modify: `app/api/ops.py` — add `list_playbooks`
- Test: `tests/test_dashboard_reads.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/v1/playbooks?program_id=&phase=&current_only=` → `list[dict]` with keys `id`, `program_id`, `phase`, `entries`, `version`, `is_current`, `updated_by`.

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: FAIL — 405 or 404 on `GET /api/v1/playbooks`.

- [x] **Step 3: Add the route**

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

- [x] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: 3 passed.

- [x] **Step 5: Checkpoint**

Run `python -m pytest -q` — green. Mark change #3 done in `09_BACKEND_CHANGES.md`.

---

### Task 4: Widen `GET /vendors` *(change #7)*

**Files:**
- Modify: `app/api/ops.py` — `list_vendors`
- Test: `tests/test_dashboard_reads.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: each `GET /api/v1/vendors` row gains `contact_name`, `phone`, `email`.

- [x] **Step 1: Append the failing test**

```python
async def test_vendor_contact_details_are_readable(client, org_a):
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/vendors",
        headers=auth(token),
        json={"name": "Northgate Logistics", "contact_name": "Ravi Menon",
              "phone": "+919000000010", "email": "ravi@northgate-example.com",
              "category": "transport", "notes": "Two-day lead time."},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get("/api/v1/vendors", headers=auth(token))).json()
    row = next(v for v in rows if v["name"] == "Northgate Logistics")
    assert row["contact_name"] == "Ravi Menon"
    assert row["phone"] == "+919000000010"
    assert row["email"] == "ravi@northgate-example.com"
```

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reads.py::test_vendor_contact_details_are_readable -v`
Expected: FAIL — `KeyError: 'contact_name'`.

- [x] **Step 3: Widen the response**

In `app/api/ops.py`, replace the return of `list_vendors`:

```python
    return [
        {
            "id": v.id,
            "name": v.name,
            "contact_name": v.contact_name,
            "phone": v.phone,
            "email": v.email,
            "category": v.category,
            "notes": v.notes,
        }
        for v in rows
    ]
```

- [x] **Step 4: Run it and confirm it passes**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: 4 passed.

- [x] **Step 5: Checkpoint**

`python -m pytest -q` green. Mark change #7 done.

---

### Task 5: The reset taxonomy and its partition guard *(D14, D16)*

Foundational: no route yet, so the guard exists before anything can rely on it.

**Files:**
- Create: `app/core/reset_taxonomy.py`
- Test: `tests/test_reset_taxonomy.py`

**Interfaces:**
- Produces: `KEEP: tuple[str, ...]` (4), `CONFIG: tuple[str, ...]` (2), `REPLACE: tuple[str, ...]` (7), `WIPE: tuple[str, ...]` (42), and `deletion_order(*, transactional: bool, catalogue: bool, org_config: bool) -> list[str]` returning table names child-before-parent.

- [x] **Step 1: Write the failing test**

```python
# tests/test_reset_taxonomy.py
"""Every table must be classified. A table added later must fail this test
rather than silently surviving — or silently losing — a reset."""
from __future__ import annotations

import app.models  # noqa: F401  (registers every mapper)
from app.core.reset_taxonomy import CONFIG, KEEP, REPLACE, WIPE, deletion_order
from app.database import Base


def test_every_table_is_in_exactly_one_bucket():
    buckets = list(KEEP) + list(CONFIG) + list(REPLACE) + list(WIPE)
    tables = set(Base.metadata.tables)

    assert set(buckets) - tables == set(), "taxonomy names a non-existent table"
    assert tables - set(buckets) == set(), "a table is in no bucket"
    duplicates = {t for t in buckets if buckets.count(t) > 1}
    assert duplicates == set(), f"table in more than one bucket: {duplicates}"


def test_bucket_sizes_are_the_agreed_partition():
    assert (len(KEEP), len(CONFIG), len(REPLACE), len(WIPE)) == (4, 2, 7, 42)
    assert len(Base.metadata.tables) == 55


def test_users_and_audit_log_are_kept():
    """users: the reset runs under the session it would destroy.
    audit_log: D13 requires the reset to write an audit row."""
    assert "users" in KEEP
    assert "audit_log" in KEEP


def test_every_wipeable_table_can_be_org_scoped():
    for table in list(CONFIG) + list(REPLACE) + list(WIPE):
        assert "org_id" in Base.metadata.tables[table].columns, table


def test_deletion_order_puts_children_before_parents():
    order = deletion_order(transactional=True, catalogue=True, org_config=True)
    assert order.index("action_items") < order.index("projects")
    assert order.index("payments") < order.index("invoices")
    assert order.index("contacts") < order.index("leads")
    assert order.index("pricing_tables") < order.index("programs")
    assert order.index("demo_team_members") < order.index("demo_teams")
    assert "users" not in order
    assert "audit_log" not in order


def test_flags_select_only_their_own_bucket():
    assert deletion_order(
        transactional=False, catalogue=False, org_config=True
    ) == list(CONFIG)
    assert set(
        deletion_order(transactional=False, catalogue=True, org_config=False)
    ) == set(REPLACE)
    assert deletion_order(
        transactional=False, catalogue=False, org_config=False
    ) == []
```

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_reset_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: app.core.reset_taxonomy`.

- [x] **Step 3: Write the module**

```python
# app/core/reset_taxonomy.py
"""Which tables a reset touches, and in what order.

Four buckets, not the script's three (05_DECISIONS.md D16):

  KEEP     never removed, by any flag.  `users` because the reset runs under
           the org_admin session it would otherwise destroy; `audit_log`
           because D13 requires the reset to leave an audit row behind.
  CONFIG   user_skills + approval_rules.  The reseed bundle exports both, so
           the reset must be able to clear them or a re-import collides.
  REPLACE  the catalogue.
  WIPE     everything transactional.

Ordering is child-before-parent throughout, because the schema declares no
`ondelete=` rule anywhere and SQLite does not enforce foreign keys by default.
Nothing else may re-derive these lists: tests/test_reset_taxonomy.py asserts
this module is a complete partition of Base.metadata.
"""
from __future__ import annotations

KEEP: tuple[str, ...] = (
    "organisations",
    "org_settings",
    "users",
    "audit_log",
)

CONFIG: tuple[str, ...] = (
    "user_skills",
    "approval_rules",
)

REPLACE: tuple[str, ...] = (
    "pricing_tables",
    "proposal_templates",
    "message_templates",
    "playbooks",
    "programs",
    "demo_teams",
    "vendors",
)

WIPE: tuple[str, ...] = (
    "message_delivery_log", "outbound_messages", "inbound_messages", "threads",
    "approvals", "proposal_revisions", "proposals",
    "reminders", "assignments", "progress_events", "ai_decisions",
    "action_items", "action_plans", "client_commitments", "conflicts",
    "project_members", "resource_bookings", "deliverables",
    "payments", "invoices", "incidents", "projects",
    "transcripts", "meetings", "consent_records",
    "stakeholders", "contacts", "lead_state_history", "leads",
    "followups", "demos", "demo_team_members",
    "notifications", "digests", "assistant_turns", "memory_chunks",
    "client_intelligence", "playbook_suggestions",
    "idempotency_records", "jobs", "llm_usage", "device_tokens",
)


def deletion_order(
    *, transactional: bool, catalogue: bool, org_config: bool
) -> list[str]:
    """Tables to delete, children first. KEEP is unreachable from here."""
    order: list[str] = []
    if transactional:
        order.extend(WIPE)
    if catalogue:
        order.extend(REPLACE)
    if org_config:
        order.extend(CONFIG)
    return order
```

- [x] **Step 4: Run it and confirm it passes**

Run: `python -m pytest tests/test_reset_taxonomy.py -v`
Expected: 6 passed.

If `test_bucket_sizes_are_the_agreed_partition` fails on 55, a table has been
added since this plan was written. **Do not adjust the number to match.**
Classify the new table into a bucket, then update the expected sizes.

- [x] **Step 5: Checkpoint**

`python -m pytest -q` green.

---

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

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reset.py -v`
Expected: FAIL — 404 on `POST /api/v1/admin/reset`.

- [x] **Step 3: Add the request model and route**

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

- [x] **Step 4: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_reset.py -v`
Expected: 7 passed.

- [x] **Step 5: Confirm the suite is not corrupted**

Run: `python -m pytest -q`
Expected: full suite green. **A failure in an unrelated module here means a
reset test touched a session-scoped fixture org** — find it and give it its own
`create_org`.

- [x] **Step 6: Checkpoint**

Both green. Mark change #5 done in `09_BACKEND_CHANGES.md`.

---

### Task 7: Guarded deletes in `ops.py` *(change #6, part 1 of 2)*

Three routes: skills, playbooks, vendors.

**Files:**
- Modify: `app/api/ops.py`
- Test: `tests/test_dashboard_deletes_ops.py`

**Interfaces:**
- Produces: `DELETE /api/v1/skills?user_id=&skill=`, `DELETE /api/v1/playbooks/{playbook_id}`, `DELETE /api/v1/vendors/{vendor_id}`. Each returns `{"deleted": True}` or raises `ConflictError` (409) / `NotFoundError` (404).

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_deletes_ops.py -v`
Expected: FAIL — 405 on every DELETE.

- [x] **Step 3: Add the skill delete**

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
    #
    # [AS SHIPPED this comment names NO count. The list reopened once and
    #  closed at ten (D24), which would have made "eight" a lie in the code.
    #  ops.py now points at 09_BACKEND_CHANGES.md as the authority instead —
    #  "the count has already moved once and a comment naming it goes stale
    #  silently". This block is the plan as written; ops.py is the authority.]
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

- [x] **Step 4: Add the playbook delete**

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

- [x] **Step 5: Add the vendor delete**

> ⚠ **The guard in the code block below no longer exists.** It was written as
> planned here, then found to be checking `external_wait["vendor_id"]` — **a key
> no caller ever writes**, since the only writer records `vendor_name` — and
> **removed outright** rather than repaired. `09` §4a records that decision, and
> `ops.py · delete_vendor`'s own docstring now carries the reasoning: nothing in
> the schema references `vendors.id`, so deleting a vendor cannot orphan
> anything. **The delete is unguarded, correctly.** The block is kept as the
> record of what was built at the time; `app/api/ops.py` is the authority.
> (Task 20 Step 3 repeated this same stale claim and is corrected there too.)

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

- [x] **Step 6: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_deletes_ops.py -v`
Expected: 7 passed.

- [x] **Step 7: Checkpoint**

`python -m pytest -q` green.

---

### Task 8: Guarded deletes in `admin.py` *(change #6, part 2 of 2)*

Five routes: programs, pricing versions, proposal templates, message templates, demo teams.

**Files:**
- Modify: `app/api/admin.py`
- Test: `tests/test_dashboard_deletes_admin.py`

**Interfaces:**
- Produces: `DELETE /api/v1/admin/programs/{program_id}`, `DELETE /api/v1/admin/programs/{program_id}/pricing/{version}`, `DELETE /api/v1/admin/programs/{program_id}/proposal-templates/{template_id}`, `DELETE /api/v1/admin/message-templates/{template_id}`, `DELETE /api/v1/admin/demo-teams/{team_id}`. Each returns `{"deleted": True}`.

- [x] **Step 1: Write the failing test**

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

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_deletes_admin.py -v`
Expected: FAIL — 405 on every DELETE.

- [x] **Step 3: Add a shared version-promotion helper**

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

- [x] **Step 4: Add the five delete routes**

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

- [x] **Step 5: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_deletes_admin.py -v`
Expected: 6 passed.

- [x] **Step 6: Checkpoint**

`python -m pytest -q` green. Mark change #6 done in `09_BACKEND_CHANGES.md`.

---

### Task 9: The conditional static mount *(change #8, D20)*

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_dashboard_mount.py`

**Interfaces:**
- Produces: `/dashboard` serving `Dashboard/dist/` when present. **Not an `APIRoute`** — route counts are unaffected.

- [x] **Step 1: Write the failing test**

```python
# tests/test_dashboard_mount.py
"""A missing console must never take down the API (D20)."""
from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import Mount

import app.main as main_mod


BUNDLE = Path(main_mod.__file__).resolve().parent.parent / "Dashboard" / "dist"


def _api_route_count() -> int:
    return sum(
        len(r.methods - {"HEAD", "OPTIONS"})
        for r in main_mod.app.routes
        if isinstance(r, APIRoute)
    )


def _dashboard_mounts() -> list:
    return [
        r for r in main_mod.app.routes
        if isinstance(r, Mount) and r.path == "/dashboard"
    ]


def test_mount_matches_the_directory_in_both_states():
    """A missing console must not take down the API, and a present one must
    actually be served. Asserting only that the import did not raise would pass
    even if the mount never appeared at all."""
    if BUNDLE.is_dir():
        assert len(_dashboard_mounts()) == 1, (
            "the bundle exists, so /dashboard must be mounted"
        )
    else:
        assert _dashboard_mounts() == [], (
            "no bundle, so /dashboard must be absent — and the app must still "
            "have imported, which it did or this module would not have loaded"
        )


def test_api_route_count_is_identical_either_way():
    """check_docs_in_sync.py asserts the README's route count. Whether the
    console happens to be built must not move that number."""
    baseline = _api_route_count()
    assert baseline > 0
    assert not any(
        r.path.startswith("/dashboard") for r in main_mod.app.routes
        if isinstance(r, APIRoute)
    )
    # The mount contributes zero APIRoutes, so the count with a bundle present
    # equals the count without one. Both states are exercised in Step 4.
    assert _api_route_count() == baseline


```

- [x] **Step 2: Run it and confirm it fails**

**Create the bundle directory first**, or the red run is vacuous:

```bash
mkdir -p Dashboard/dist && printf '<!doctype html><title>placeholder</title>' > Dashboard/dist/index.html
```

Run: `python -m pytest tests/test_dashboard_mount.py -v`
Expected: FAIL on `test_mount_matches_the_directory_in_both_states` — the bundle
now exists but nothing mounts it. This is exactly the assertion the old
`assert app is not None` version could not make, which is why it was replaced.

- [x] **Step 3: Add the mount**

At the end of `app/main.py`, after the health routes:

```python
# ── The setup console, when it has been built ────────────────────────────────
# The bundle lives outside app/ on purpose: tests/test_genericity.py scans
# app/**/*.py and scripts/check_hardcoded_strings.py scans Android Java, so a
# bundle carrying the product manual's verbatim quotes must stay out of both
# scan roots (05_DECISIONS.md D19).
_DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "Dashboard" / "dist"
if _DASHBOARD_DIST.is_dir():
    app.mount(
        "/dashboard",
        StaticFiles(directory=_DASHBOARD_DIST, html=True),
        name="dashboard",
    )
else:
    logger.warning(
        "Setup console not mounted: no bundle at %s. Run `npm run build` in "
        "Dashboard/ to serve it at /dashboard. The API is unaffected.",
        _DASHBOARD_DIST,
    )
```

Add to the imports at the top of `app/main.py`:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles
```

> ⚠ **This blockquote was wrong and is corrected here rather than deleted.** It
> read: *"`html=True` makes `StaticFiles` serve `index.html` for unknown
> sub-paths, which is what a client-side router needs."* It does not. `html=True`
> serves `index.html` for a **directory** URL and 404s an unknown sub-path
> (`404.html` if one exists). Proved in Task 11 by requesting
> `/dashboard/checklist` and getting a 404. See **P10 / A8** in Phase 2: the
> console uses hash routing, so it never depends on a fallback that is not there.
> The mount itself is correct and unchanged.

- [x] **Step 4: Run both states — this is the point of the test**

With the placeholder bundle from Step 2 present:

```bash
python -m pytest tests/test_dashboard_mount.py -v          # 2 passed, mount present
```

Then remove it and run again:

```bash
rm -rf Dashboard/dist
python -m pytest tests/test_dashboard_mount.py -v          # 2 passed, mount absent
```

Both must pass. A version that only passes in one state has not tested the
conditional at all. Leave `Dashboard/dist/` **absent** afterwards — Phase 2 Task
11 creates the real one, and a stale placeholder would mount an empty console.

- [x] **Step 5: Checkpoint**

`python -m pytest -q` green in both states. Mark change #8 done.

---

### Task 10: Resync the docs and run every guard

Phase 1 is not done until the guards are green. **"The docs are updated" is not
the completion claim.**

**Files:**
- Modify: `BACKEND_README.md` — the counts table and §7.1

- [x] **Step 1: Measure, do not assume**

Run: `python scripts/check_docs_in_sync.py`

It prints the live figures before it compares them, e.g.
`code: 55 tables, 755 columns, 151 routes, ...` and
`[INFO] §7.1 breakdown from code: 70 uncalled (...)`.

**Use the numbers it prints.** The expected values are 151 routes and 70 uncalled,
with Organisation administration 25 and Operations and money 20 — but if the
printout disagrees, the printout is right and this plan is stale.

- [x] **Step 2: Update the README's counts table**

Change the routes row from `**140** | 16 endpoint modules` to
`**151** | 16 endpoint modules`. The guard matches that exact pattern.

- [x] **Step 3: Update §7.1**

Set the heading to `### 7.1 What the app does not call (70 routes)` and the two
changed rows to **Organisation administration 25** and **Operations and money 20**.
Leave Everything else 13, Platform / Super Admin 4, Incidents 3, Approval rules 3,
Device push registration 2. The rows must sum to 70 — the guard checks the sum
independently of the heading, because a table has been wrong in the rows while
right in the total before.

- [x] **Step 4: Run the docs guard**

Run: `python scripts/check_docs_in_sync.py`
Expected: exit 0, ending `OK - the three documents agree with the code`.

- [x] **Step 5: Run the two genericity guards**

```bash
python -m pytest tests/test_genericity.py -q
python scripts/check_hardcoded_strings.py
```

Expected: both pass. Neither scans `Dashboard/`, so neither should react to
Phase 1 at all — if one does, something landed in the wrong directory.

- [x] **Step 6: Fix the README's test-count wording**

`BACKEND_README.md` says **"218 pytest"**, which reads as 218 passing. It is not:
at the pre-work baseline the suite was **215 passed, 3 failed, 218 collected**
(measured by the controller against commit `19efa98`).

**State both numbers**, in this shape:

> `<collected>` tests collected, `<passed>` passing.

Then add the known-failure note, because a bare "3 failing" invites someone to
assume it is a product bug:

> The 3 failures in `tests/test_what_is_late.py` are a **test-side timezone
> assumption, not a product defect**. The engine partitions on
> `today_local = date.today()` (`assistant_engine.py`), while the test helper
> builds due dates from `utcnow()`. On a UTC+5:30 machine those dates differ
> between 00:00 and 05:30 local, so the suite is **green for 18.5 hours a day
> and red for 5.5**. Fixing it is one line in the test helper and is outside
> this project's closed change list.

- [x] **Step 7: Run the full suite and record both totals**

Run: `python -m pytest -q`

Record collected **and** passing in `08_PROGRESS_AND_HANDOFF.md`, plus the local
time of the run — because of the window above, "green" without a timestamp is
not a reproducible claim.

- [x] **Step 8: Checkpoint — Phase 1 complete**

All four commands green, **with the `test_what_is_late.py` window noted** rather
than silently absorbed. Mark every row in `09_BACKEND_CHANGES.md` done with its
guard column ticked, and update `08_PROGRESS_AND_HANDOFF.md` to say Phase 2 is next.

---

# PHASE 1b — Two reopened changes (Tasks 10a–10b)

**The list was reopened on 2026-08-13 for exactly two changes and re-frozen at
ten** (D24). Both are the defect this project has already ruled on twice — **a
write path with no read path**. `GET /playbooks` entered the closed list for that
reason; `GET /vendors` was widened for it. These two were found while writing
Phase 2's task detail, as findings **P4** and **P5**.

**Why they were accepted rather than worked around.** Refusing buys consistency
with a reseed bundle that silently drops `auto_approve` — a rule that
auto-approves comes back waiting for a human, and nobody is told. That is a
correctness bug, not a cosmetic gap.

| # | Change | Route | Adds |
|---|---|---|---|
| 9 | Read back what the write accepts | `GET /approval-rules` | `fallback_role`, `auto_approve` |
| 10 | Read back what the write accepts | `GET /admin/demo-teams` | `lead_user_id`, `media_rep_id`, `sales_rep_id` |

**Both are pure widenings of an existing response.** No new route, no new column,
no migration, **and no field is renamed or removed** — change #10 adds the three
ids **alongside** `lead` / `media_rep` / `sales_rep`, which the Android app calls
this route for and may render. Replacing them would be a behaviour change to an
existing route and would break rule 1 of `09_BACKEND_CHANGES.md` §2.

**Neither route is destructive, so neither writes an audit row.** D13 binds
destructive routes; a GET that gained two fields is not one, and adding an audit
write to a read path would be noise in the log the reset deliberately preserves.

**Route count stays 151.** Nothing is added to `app.routes` — `check_docs_in_sync.py`
counts `APIRoute` instances, and a widened return dict is invisible to it.
**Confirm that by running it; do not assume it.**

---

### Task 10a: `GET /approval-rules` returns `fallback_role` and `auto_approve` *(change #9)*

**Files:**
- Modify: `app/api/ops.py` — `list_approval_rules`
- Test: `tests/test_dashboard_reads.py` *(append — this file already owns the
  read-widenings of changes #3 and #7; a third one belongs beside them)*

**Interfaces:**
- Consumes: nothing.
- Produces: two more keys on every `GET /api/v1/approval-rules` row.
  `ApprovalRuleRequest` already accepts both and `ApprovalRule` already stores
  both — this closes the read half only.

- [x] **Step 1: Write the failing test**

```python
async def test_approval_rule_fallback_and_auto_approve_are_readable(client, org_a):
    """Both fields are accepted by POST and stored, and were unreadable — so a
    reseed bundle exported a rule that came back waiting for a human when it had
    been set to auto-approve, with nothing to tell anyone (P4)."""
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/approval-rules",
        headers=auth(token),
        json={"entity_type": "readback_probe", "condition": {},
              "rank": 10, "approver_role": "sales_lead",
              "fallback_role": "org_admin", "auto_approve": True,
              "description": "Reads back what the write accepted."},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/approval-rules", headers=auth(token))).json()
    row = next(r for r in rows if r["entity_type"] == "readback_probe")
    assert row["fallback_role"] == "org_admin"
    assert row["auto_approve"] is True


async def test_approval_rule_defaults_read_back_as_stored(client, org_a):
    """A rule that names neither must read back null and False — not absent, and
    not the truthy-looking values of the rule above. Without this, a response
    that hard-coded the two keys would pass the test above."""
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/approval-rules",
        headers=auth(token),
        json={"entity_type": "readback_defaults", "approver_role": "sales_lead"},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/approval-rules", headers=auth(token))).json()
    row = next(r for r in rows if r["entity_type"] == "readback_defaults")
    assert row["fallback_role"] is None
    assert row["auto_approve"] is False
```

> The second test is the one that earns its keep. A single happy-path assertion
> is satisfied by a handler that returns the literal values, and this project has
> already shipped one guard written against a key no caller ever writes
> (`09` §4a, `external_wait.vendor_id`). Assert the *stored* value, both ways.

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: both new tests FAIL with `KeyError: 'fallback_role'`. A failure for any
other reason means the setup is wrong, not the product.

- [x] **Step 3: Widen the response**

In `app/api/ops.py` · `list_approval_rules`, add the two keys to the returned
dict. Place `fallback_role` immediately after `approver_role` and `auto_approve`
immediately after `joint_condition`, so the response reads in the same order as
`ApprovalRuleRequest` declares them — the read is now a mirror of the write and
should look like one.

- [x] **Step 4: Confirm green, and that nothing else moved**

```bash
python -m pytest tests/test_dashboard_reads.py -v     # 6 passed
python -m pytest -q                                   # record collected AND passing
```

- [x] **Step 5: Checkpoint — commit**

Commit `app/api/ops.py` and the test together. One change, one commit.

---

### Task 10b: `GET /admin/demo-teams` returns the three user ids *(change #10)*

**Files:**
- Modify: `app/api/admin.py` — `list_demo_teams`
- Test: `tests/test_dashboard_reads.py` *(append)*

**Interfaces:**
- Consumes: nothing.
- Produces: `lead_user_id`, `media_rep_id`, `sales_rep_id` **alongside** the
  existing `lead`, `media_rep`, `sales_rep` name fields.

> **The names stay.** The Android app calls this route and may render them.
> Rule 1 of `09` §2 is additive-only, and swapping a name for an id would be a
> behaviour change to an existing route.

> **The field is `lead_user_id`, not `lead_id`** — it mirrors
> `DemoTeamRequest.lead_user_id` and the `DemoTeam.lead_user_id` column, so the
> read is a straight mirror of the write and the reseed bundle copies rather than
> renames. Its two siblings are already `media_rep_id` / `sales_rep_id` on both
> sides.

- [x] **Step 1: Write the failing test**

```python
async def test_demo_team_role_ids_are_readable_alongside_the_names(client, org_a):
    """The write takes ids and the read returned only names, and User.name is not
    unique — so a delete-and-recreate edit (there is no PATCH) could not restore
    the three roles, and the reseed bundle lost them (P5)."""
    token = org_a["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()

    created = await client.post(
        "/api/v1/admin/demo-teams",
        headers=auth(token),
        json={"name": "Readback Demo Crew", "lead_user_id": me["user_id"],
              "media_rep_id": me["user_id"], "sales_rep_id": me["user_id"]},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/admin/demo-teams", headers=auth(token))).json()
    row = next(t for t in rows if t["name"] == "Readback Demo Crew")

    assert row["lead_user_id"] == me["user_id"]
    assert row["media_rep_id"] == me["user_id"]
    assert row["sales_rep_id"] == me["user_id"]

    # Rule 1 of 09 §2: additive only. The Android app calls this route and may
    # render these; an id that arrived by replacing a name is a behaviour change.
    assert row["lead"] == me["name"]
    assert row["media_rep"] == me["name"]
    assert row["sales_rep"] == me["name"]


async def test_demo_team_unset_roles_read_back_as_null_ids(client, org_a):
    """A team naming nobody must return null ids, not absent keys — the bundle
    distinguishes 'no lead' from 'the API cannot tell you'."""
    token = org_a["admin_token"]
    created = await client.post(
        "/api/v1/admin/demo-teams",
        headers=auth(token), json={"name": "Readback Empty Crew"},
    )
    assert created.status_code == 200, created.text

    rows = (await client.get(
        "/api/v1/admin/demo-teams", headers=auth(token))).json()
    row = next(t for t in rows if t["name"] == "Readback Empty Crew")

    for key in ("lead_user_id", "media_rep_id", "sales_rep_id"):
        assert key in row, f"{key} must be present and null, not absent"
        assert row[key] is None
    assert row["lead"] is None
```

> `assert key in row` before `assert row[key] is None` is deliberate: a missing
> key and a null value both read as `None` through `.get()`, and the console
> needs them to be different facts. Test the presence, then the value.

- [x] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_reads.py -v`
Expected: both new tests FAIL with `KeyError: 'lead_user_id'`.

- [x] **Step 3: Widen the response**

In `app/api/admin.py` · `list_demo_teams`, add the three ids to the dict it
appends, each **next to the name it corresponds to** so the pairing is obvious at
a glance:

```python
"lead": await _name(team.lead_user_id),
"lead_user_id": team.lead_user_id,
"media_rep": await _name(team.media_rep_id),
"media_rep_id": team.media_rep_id,
"sales_rep": await _name(team.sales_rep_id),
"sales_rep_id": team.sales_rep_id,
```

The values come straight off the row — `_name()` is a second query per field and
is not needed for the id.

- [x] **Step 4: Confirm green**

```bash
python -m pytest tests/test_dashboard_reads.py -v     # 8 passed
python -m pytest -q                                   # record collected AND passing
```

- [x] **Step 5: Checkpoint — commit**

Commit `app/api/admin.py` and the test together.

---

### Task 10c: Resync, re-freeze at ten, and drop the four warnings

- [x] **Step 1: Confirm the route count did not move**

Run: `python scripts/check_docs_in_sync.py`

Expected: **exit 0**, ending `OK - the three documents agree with the code`, with
the printed figure still **151 routes**. Both changes widen a return dict inside
an existing handler; neither adds an `APIRoute`. **Read the printed number rather
than assuming it** — that is the rule Task 10 was written under and the reason
this step exists at all.

If it moved, something other than a return dict changed. Stop and find out what.

- [x] **Step 2: Refresh `BACKEND_README.md`'s test count**

The guard does not assert it — verified, `check_docs_in_sync.py` reads no test
figures — so this will not fail a build. Update it anyway: §13 states a
`<collected>` / `<passing>` pair and four new tests have landed. A count that is
quietly wrong is how "218 pytest" survived to Task 10.

Leave the route count and §7.1 untouched; neither moved.

- [x] **Step 3: Record D24 in `05_DECISIONS.md`**

The reasoning, not the diff: both changes are the same defect the project has
already ruled on twice, accepting them keeps the reseed loop honest, and the
list re-closes at **ten**.

- [x] **Step 4: Update `09_BACKEND_CHANGES.md`**

Add a fourth freeze-history row, two rows to the change table, two rows to the
§5 change log, and change every "closed at eight" to **ten** — including the
header banner, which is the first thing the next session reads.

- [x] **Step 5: Drop the warnings from Tasks 19, 20, 23 and 24**

Findings **P4** and **P5** are now fixed, so four pieces of interface text
describing the gap must go, or the console will warn about a limit that no longer
exists:

| Task | Warning to remove |
|---|---|
| 19 | approval rules: hazard 2, "`fallback_role` and `auto_approve` cannot be read back", and the "cannot preserve them" caveat on the delete-then-create edit path |
| 20 | demo teams: the three ids marked *not readable*, and the "cannot restore the three role assignments" warning before the delete |
| 23 | the go-live check's note that auto-approving rules cannot be distinguished from ones that wait |
| 24 | the bundle's second export-screen paragraph, and the round-trip test's "two lossy entity types" case |

Task 15's two `notReadable` lists go with them, and Task 24's round-trip test
becomes **nine faithful entity types with no exceptions** — a strictly stronger
assertion. Mark P4 and P5 **FIXED** in the findings section rather than deleting
them; they are the reason two of the ten changes exist.

- [x] **Step 6: Run every guard and record the local time**

```bash
python scripts/check_docs_in_sync.py           # exit 0
python -m pytest tests/test_genericity.py -q   # 8 passed
python scripts/check_hardcoded_strings.py      # exit 1, the same 2 Java findings
python -m pytest -q                            # collected AND passing, with local time
```

`tests/test_what_is_late.py` is clock-dependent between 00:00 and 05:30 local
(`08` §4 item 8). **"Green" without a timestamp is not a reproducible claim.**

**Do not write "all four guards are green."** The honest claim is that the two
guards this work could affect are green and the third fails exactly as it did
before.

- [x] **Step 7: Checkpoint — re-frozen at ten**

`09`'s banner reads ten and CURRENTLY RE-FROZEN; `08`'s status table shows both
tasks done. **Phase 2 starts at Task 11 and needs no further backend work.**

---

# PHASE 2 — The console

## Why Phase 2's tasks are written after Task 10, not now

**The console's entire type layer is generated from the backend's
`/openapi.json` (D12).** Writing task-level detail before Phase 1 shipped would
have meant inventing the schema and type names `openapi-zod-client` will emit —
for routes that did not exist yet, from a generator whose output naming depends
on its pinned version. Those invented names would be wrong, and a plan that
names a type no task defines is the exact failure mode the plan format forbids.

This is not a deferral of decisions — every design decision is already made in
`06_DESIGN.md`. It was a deferral of *symbol names* until the symbols existed.

> **Written 2026-08-13, after Task 10, against the live spec** served by the
> running backend at `http://127.0.0.1:8000/openapi.json` (151 operations,
> 85 component schemas, `openapi: 3.1.0`) and against
> `openapi-zod-client@1.18.3` **actually run over it**, not predicted.
>
> **Deferring paid off, and not only for naming.** Four load-bearing claims in
> `06_DESIGN.md` §3 turned out to be false about this spec and this generator.
> They are corrected in the next section, and the corrections change the shape
> of Tasks 11, 15 and 16. A plan written in advance would have shipped all four.

---

## What the live spec revealed — nine findings, and the amendments they force

Every figure below was computed from the served `/openapi.json` this session,
and every generator behaviour was observed by running the generator, not
recalled. **Findings P1 and P2 are the important ones**; they are the reason
Task 11 grew a second and third generation step and Task 15 grew a read layer.

### P1 · Eleven of the fifteen reads the console makes are untyped

FastAPI only emits a response schema where the route declares `response_model=`.
**Exactly two routes in the whole API that this console reads do so** —
`GET /admin/users` and `GET /admin/users/{user_id}`, both `UserResponse`. Every
other console read returns `"schema": {}`, which is OpenAPI for *anything*.

| Read | Response schema |
|---|---|
| `GET /auth/me` | `MeResponse` ✅ |
| `GET /orgs` | `OrgResponse[]` ✅ |
| `GET /admin/users`, `GET /admin/users/{id}` | `UserResponse` ✅ |
| `GET /skills` · `GET /admin/programs` · `GET /admin/programs/{id}/pricing` · `GET .../proposal-templates` · `GET /admin/message-templates` · `GET /playbooks` · `GET /approval-rules` · `GET /admin/settings` · `GET /admin/demo-teams` · `GET /vendors` · `POST /admin/reset` (dry run) | **`{}`** ❌ |

**So `06_DESIGN.md` §3.1's "response shapes … never hand-typed" is false for
11 of 15 reads**, and §5.2 — which derives every checklist status from exactly
those reads — sits entirely on top of them. Generation cannot help here.

**Amendment (A1).** `src/api/reads.ts` holds hand-written Zod schemas for the
eleven untyped reads, in a file that says so at the top, with a **third
provenance value** (see P2) and three defences that generation cannot give:

1. `client.ts` `safeParse`s every read against its shape and, on failure,
   raises a **visible drift banner** naming the route and the failing path —
   never a blank screen and never a silent `undefined`.
2. `npm run fixtures:capture` records real payloads from a live seeded backend
   into `src/api/__fixtures__/*.json`, and a Vitest suite parses every fixture
   with its read shape. A backend rename then fails a test on the next capture.
3. Each read shape's fields are transcribed from a **named handler**, cited
   file-and-symbol in a comment (`ops.py · list_approval_rules`), so the next
   person can re-derive it in one grep.

This is not the hand-written mirror D12 forbids. D12 forbids re-declaring
validation the generator *can* produce; there is no generated alternative for a
response the server never declared.

### P2 · The generator silently drops every constraint declared inside an `anyOf`

FastAPI renders `int | None = Field(ge=1, le=100)` as
`anyOf: [{type: integer, minimum: 1, maximum: 100}, {type: null}]`.
`openapi-zod-client@1.18.3` emits `z.union([z.number(), z.null()])` for that —
**the bounds are gone**. Constraints survive only on required, non-nullable
fields.

Measured over the 21 schemas this console writes: **12 constraints survive,
16 are dropped.**

| Survive (emitted into `generated.ts`) | Dropped (present in `openapi.json`, absent from `generated.ts`) |
|---|---|
| `CreateOrgRequest.name` 2–200 · `.slug` 2–100 `^[a-z0-9-]+$` · `.email_domain` 3–200 · `.admin_email` email · `CreateUserRequest.email` email · `.name` ≥2 · `LoginRequest.email` email · `MessageTemplateRequest.body` ≥10 · `PricingItem.unit_price` ≥0 · `PricingRequest.items` ≥1 item · `ProgramRequest.code` 1–50 · `ProposalTemplateRequest.body_md` ≥20 | `CreateUserRequest.max_open_tasks` 1–100 · `UpdateUserRequest.max_open_tasks` 1–100 · `SettingsRequest`: `audio_retention_days` 1–3650 · `transcript_retention_days` 1–3650 · `llm_monthly_budget_usd` ≥0 · `followup_cadence_days` 1–365 · `assignment_mode` `^(auto\|lead_confirm)$` · `workday_start` `^\d{2}:\d{2}$` · `workday_end` same · `quiet_hours_override_priority` `^P[123]$` · `max_unanswered_nudges` 0–10 · `max_client_messages_per_week` 1–50 · `lead_cold_after_days` 1–365 · `high_load_caution_pct` 10–100 · `client_report_time` `^\d{2}:\d{2}$` · `ai_confidence_threshold` 0–1 |

**This breaks §3.3's two-value honesty model in the worst possible direction.**
Those 16 rules *are* enforced by the server. Marking them `ui-only` — "the
server will accept anything" — would be a lie, and it is exactly the class of
lie §6 exists to prevent. Marking them `backend` would claim they came from the
generated schema, and the conformance test would go looking for bounds that are
not there.

**Amendment (A2) — `enforcement` becomes three-valued:**

| Value | Meaning | Rendered as | Guarded by |
|---|---|---|---|
| `schema` | in `generated.ts`; server enforces it | plain caption | the descriptor→schema conformance test |
| `backend-undeclared` | server enforces it; the generator did not carry it | plain caption **+ its citation** | the constraint-lift test (below) |
| `ui-only` | **server accepts anything**; the rule exists only here | caption with the distinct marker | nothing — that is the point, and the marker says so |

**Amendment (A3) — the 16 dropped constraints are lifted, not hand-typed.**
`openapi.json` *has* them; only the generator loses them. Task 11 adds
`tools/lift_constraints.mjs`, which walks the committed `openapi.json`, pulls
`minimum` / `maximum` / `minLength` / `maxLength` / `pattern` / `minItems` out
of `anyOf` branches, and emits `src/api/constraints.generated.ts`. A Vitest test
asserts **every constraint in `openapi.json` is represented in either
`generated.ts` or the lift** — so a bound added to a Pydantic field later shows
up in the console instead of being silently lost. Drift stays a build error, and
`backend-undeclared` stays derived rather than copied.

### P3 · `role`, `department`, `kind`, `channel` and the 8-character password rule are enforced in handler bodies, not in Pydantic

OpenAPI types them `string`. The server rejects bad values anyway:

| Rule | Enforced at |
|---|---|
| `role` ∈ the five org roles | `admin.py · register_staff` (`Role(...)`, then `ORG_ROLES`) |
| `department` ∈ sales/operations/accounts | `admin.py · _validated_department` |
| `kind` ∈ intro/follow_up, `channel` ∈ email/whatsapp | `admin.py · add_message_template` |
| an email template must have a subject | `admin.py · add_message_template` |
| staff email must end `@<org.email_domain>` | `admin.py · register_staff` |
| new password ≥ 8 characters | `auth.py · change_password` |
| skills editable only by org_admin / sales_lead / operations_lead | `ops.py · set_skill`, `ops.py · delete_skill` |

These are `backend-undeclared` (A2), and the first four are **vocabularies** —
lists that would rot the moment `constants.py` gained a member.

**Amendment (A4).** `dump_openapi.py` already imports `app.main`; it also dumps
`Role`, `ORG_ROLES`, `Department`, `TemplateKind`, `MessageChannel`, `SkillLevel`
and `Phase` from `app/core/constants.py` into `src/api/vocabularies.generated.ts`.
That is generation, not mirroring: it lives under `Dashboard/tools/`, writes
nothing under `app/`, and `gen:check` makes a drift a build failure — the same
protection the schemas get. **No role or department list is ever typed by hand
in this console.** (Q15's `RoleGate.java` is one permission behind precisely
because it was typed by hand.)

### P4 · `GET /approval-rules` cannot read back two fields `POST /approval-rules` accepts — **FIXED, change #9**

> **Fixed 2026-08-13 as change #9** (D24, Task 10a). Kept here because it is the
> reason that change exists. Everything below describes the defect as found; the
> route now returns both fields.

`ops.py · list_approval_rules` returns `id`, `entity_type`, `condition`, `rank`,
`approver_role`, `recommender_role`, `joint_with_role`, `joint_condition`,
`expires_hours`, `description`. It omits **`fallback_role`** and
**`auto_approve`**, both of which `ApprovalRuleRequest` accepts and both of which
are stored.

**This falsifies §5.8's pairing claim** — "everything the bundle carries, the
reset can clear, and nothing else" — for approval rules: export → reset →
re-import silently drops the fallback approver and the auto-approve flag. An
`auto_approve` rule would come back as a rule that now waits for a human, and
nobody would be told.

**The fix was a ninth backend change against a list closed at eight.** Per
Global Constraints this stopped and went to the owner, who **reopened the list
for exactly this and P5** and re-closed it at ten (D24). `list_approval_rules`
now returns `fallback_role` and `auto_approve`, so **the bundle round-trips
approval rules faithfully** and Tasks 19, 23 and 24 carry no warning about them.

### P5 · `GET /admin/demo-teams` returns names where the write takes ids — **FIXED, change #10**

> **Fixed 2026-08-13 as change #10** (D24, Task 10b). Kept here for the same
> reason as P4.

`admin.py · list_demo_teams` returns `lead`, `media_rep`, `sales_rep` as **user
names**, while `DemoTeamRequest` takes `lead_user_id`, `media_rep_id`,
`sales_rep_id`. `members` does carry ids. `User.name` is not unique, so a
name→id resolution is ambiguous by construction.

Same consequence as P4 — demo teams did not round-trip through the bundle — and
the same resolution: `list_demo_teams` now returns `lead_user_id`,
`media_rep_id` and `sales_rep_id` **alongside** the three name fields, which stay
because the Android app calls this route and may render them (rule 1 of `09` §2).

**The delete-and-recreate edit path is therefore whole**: §5.4 flags demo teams
as `PATCH`-less, and the recreate can now restore the three roles from ids the
read supplies.

### P6 · `GET /orgs` is `super_admin`-only, so §5.2 item 1's stated read is unreachable

`organisations.py · list_organisations` depends on `get_super_admin`. §5.2 item 1
says its read is `GET /orgs`, `GET /auth/me`; §1.1 says the console holds a
`super_admin` session "for exactly one call — `POST /orgs` — and nothing else".
Both cannot be true, and after a tab reload there is no super-admin session at
all.

**Amendment (A5).** Item 1 derives from **`GET /auth/me` alone** — it returns
`org_id`, `org_name`, `org_slug` and `role`, which is the whole of "an org is
selected and its admin session is live". `GET /orgs` is used only by the
optional org **picker** on the create screen, which is visible only while a
super-admin session exists and is absent otherwise.

### P7 · No `org_admin`-readable route returns `email_domain`

`MeResponse` carries `org_name`, `org_slug`, `org_logo_url`, `org_brand_colors`
— **not `email_domain`**. `OrgResponse` has it and is super-admin-only. So
§5.6's check 6, "every staff email against `org.email_domain`", cannot run as
written from the session that runs the console.

**Amendment (A6).** Task 23 runs the check against the domain it can actually
know, in this order, and **says which one it used**:

1. the value returned by `POST /orgs` earlier in this same tab, if present;
2. otherwise, the distinct domains across `GET /admin/users` emails — the
   server enforces `endswith("@" + domain)` on every staff create, so more than
   one distinct domain among staff is itself the defect worth reporting;
3. if neither is available, the row renders `—` with the reason, per §6.

Note the F34 trap this was written for is now **closed server-side**:
`organisations.py · create_organisation` does `email_domain.lstrip("@")` before
the regex. The check stays, because it also catches the multi-domain case.

### P8 · Every staff account also returns a one-time temporary password

`admin.py · register_staff` returns `{...UserResponse, "temp_password": ...}`
and sets `must_change_password=True`, which — as §4.2 established — **nothing in
the backend enforces**. `06_DESIGN.md` §4.2 designs the hand-off for the *org
admin's* password and never mentions this one, so an implementer following the
design would drop a credential on the floor for every staff member created.

**The asymmetry matters and Task 17 must state it:** a staff temp password is
**recoverable** — `POST /admin/users/{user_id}/reset-password` issues a fresh
one — whereas the org admin's is not, which is the whole reason for D18's modal.
So staff creation shows the password once, with a copy control and a plain "if
this is lost, reset it here" pointing at the recovery route. No modal, no chain.

### P9 · Everything the generator emits is `.passthrough()`

`z.object({...}).passthrough()` on every schema, and `.partial()` on top for
all-optional models such as `UpdateUserRequest`, `SettingsRequest` and
`ResetRequest`. **An unknown key never fails validation.** For an interactive
form that is harmless; for **CSV import it is not** — a header typo'd
`unit_pirce` would validate clean, apply clean, and write a pricing line with no
price.

**Amendment (A7).** `import/validate.ts` checks the column set itself against
the descriptor before any Zod parse: unknown columns are a **row-level error**,
except columns whose name begins with `_`, which D21 requires be ignored so a
failures file round-trips.

### P10 · `StaticFiles(html=True)` does **not** fall back to `index.html`, so path routing would break on refresh

**Found in Task 11 by requesting a deep link, not by reading about it.** With the
bundle built and the backend restarted:

```
GET /dashboard/            → 200  text/html
GET /dashboard/assets/…js  → 200      (base: "/dashboard/" resolves correctly)
GET /dashboard/checklist   → 404      ← the one that matters
```

Starlette's source settles it: `StaticFiles.get_response` serves `index.html`
only when the path resolves to a **directory**, and for a missing path it looks
for `404.html` and otherwise raises 404. **There is no SPA fallback.**

> This plan claimed the opposite, at Task 9 Step 3 and again at Task 25 Step 2 —
> *"`html=True` makes `StaticFiles` serve `index.html` for unknown sub-paths,
> which is what a client-side router needs."* **That is false.** It is prose in
> this document only; `app/main.py` carries no such comment, so no code comment
> is lying. Both places are corrected in place.

The failure mode is nasty precisely because the happy path works: every
in-app navigation is client-side and fine, and the console only breaks when
someone **refreshes, bookmarks, or is sent a link** to any screen but the root.
It would have surfaced at Task 25 at the earliest, and plausibly at a client.

**Amendment (A8) — the console uses hash routing.** `createHashRouter`, so every
URL is `/dashboard/#/staff` and the server only ever sees `/dashboard/`. No
backend change, which matters: the change list is closed at ten and a
SPA-fallback mount would be an eleventh.

The alternative — shipping a `404.html` that is a copy of `index.html` — was
rejected. It works, but every deep link would then return **HTTP 404 with a
working page in the body**, which lies to caches, crawlers and the browser's own
history. A console built around §6's honesty model should not serve a 404 that
is not one.

### P11 · Item 10 ticks green on an organisation nobody has opened — `POST /orgs` seeds three dials from the **server's** environment

**Found in Task 16, in a browser, against an organisation created ninety seconds
earlier.** §5.2 says item 10 is `●` when "any dial differs from its model
default" and `◐` otherwise, on the stated ground that the API cannot tell a
deliberate default from an untouched one. But `organisations.py`'s `OrgSettings(...)`
does not take the model defaults for three of the twenty-five:

```python
audio_retention_days=settings.default_audio_retention_days,
transcript_retention_days=settings.default_transcript_retention_days,
llm_monthly_budget_usd=settings.llm_default_org_monthly_budget_usd,
```

This repository's `.env` carries `LLM_DEFAULT_ORG_MONTHLY_BUDGET_USD=3.0`
against a model default of `50.0` (`config.py:73`), so **every new organisation
on this server is born with a dial that differs**, and §5.2's rule ticks item 10
green before anyone has opened the settings screen. That is the same lie as
showing untouched defaults as done, arriving from the other direction.

`status.ts` therefore carries `ENV_SEEDED`: a difference confined to those three
is `◐`, and the caption names them. A difference in any of the other
twenty-two is a real choice and still `●`. **`06` §5.2's one-line rule is
narrower than it looks and should be read with this**; the two retention dials
are also item 12's, which is why they cannot simply be dropped from the set.

### P12 · Item 12 can never be verified at all, and P11's carve-out is a pattern rather than a fix

**Found in Task 17, by auditing every column `POST /orgs` writes** before
building screens on any of them — the rule P11 should have prompted immediately
and did not. Org creation writes exactly four things a checklist item reads:

| Seeded | Read by | Verdict |
|---|---|---|
| `audio_retention_days`, `transcript_retention_days`, `llm_monthly_budget_usd` | item 10 | carved out by `ENV_SEEDED` (P11) |
| the first two of those, again | **item 12** | **unverifiable — no carve-out possible** |
| one `users` row, the org admin | item 2 | already excluded from "staff besides the admin" |
| `organisations.name` / `slug` / `email_domain` | item 1 | fine — the operator supplied them to `POST /orgs`, and item 1 asserts only that an organisation exists and the session is live |

Item 12 reads **only** the two retention columns, and both are seeded from
`DEFAULT_AUDIO_RETENTION_DAYS` / `DEFAULT_TRANSCRIPT_RETENTION_DAYS`. Grepped
across `app/`: `config.py` declares them and `organisations.py` reads them, and
that is the whole of it — **no route returns either value**. So no response, and
no combination of responses, separates "the operator chose 90 days" from "the
server's environment said 90 days". Unlike item 10 this cannot be rescued by
excluding a few columns, because excluding both leaves nothing.

§5.2's "always satisfied" therefore cannot be shown as `●`. Item 12 is **`◐`
for every input**, with the windows named and the reason stated — which is
exactly what this console means by "true, but unverifiable". A truth-table test
pins it, and a second test asserts the whole audit: **on an untouched
organisation, item 1 is the only green row.**

### P13 · The programme-delete refusal recommends something the API cannot do

`delete_program` refuses a programme in use with:

> *"'X' is used by N project(s) and M proposal(s) and cannot be removed. **Mark
> it inactive instead.**"*

There is no route that marks a programme inactive. The four programme routes are
`POST`, `GET`, `DELETE` and the nested pricing/template ones; `Program.is_active`
is written nowhere in `app/api/` — verified by grep, not inferred from the
absence of a `PATCH`. `GET /admin/programs` returns the flag, so the console can
*show* inactive, and nothing can *set* it.

Task 18's screen renders the server's message verbatim, as every screen does,
and then says plainly that its suggestion has no endpoint. Not fixed: the change
list is closed at ten and this is a message string, not a defect in behaviour.

### Two more things worth knowing before Task 11

- **The dumper and the served spec agree exactly.** `app.openapi()` imported
  in-process was compared key-by-key against the spec served on `:8000` this
  session: **identical**. Generating without a running backend (§3.1) is sound.
- **Encoding will bite on Windows.** The docstrings feeding `description` carry
  `§`, `—` and `→`. Python and Node both default to the system codepage here, so
  `dump_openapi.py` must write with `encoding="utf-8", ensure_ascii=False` and
  every reader must open UTF-8 explicitly. Get this wrong and `gen:check` diffs
  forever against a file that only *looks* the same.

---

## What Phase 2 covers, in build order

Each row is one task, sized to end with something testable.

| # | Task | Deliverable |
|---|---|---|
| 11 | Scaffold + generation pipeline | `dump_openapi.py`, **four** generated artefacts, `gen:api` / `gen:check` wired as `prebuild` |
| 12 | Design tokens + primitives | `tokens.css`, light/dark, the four status markers, type scale |
| 13 | `api/client.ts` + `session/` | base-URL field, dual token store, `retry: 0`, `AppError` normalisation, the read-drift banner |
| 14 | Org creation + chained hand-off | the D18 blocking modal including the recovery state, plus sign-in to an existing org |
| 15 | Descriptor layer + read shapes + conformance tests | 11 descriptors, `reads.ts`, the three `enforcement` values, four drift tests |
| 16 | Checklist rail + status derivation | pure functions, four statuses, the compound email status |
| 17 | Item screens: dependency Tiers 0–1 | staff (items 1–2), skills (item 3) |
| 18 | Item screens: the catalogue | programs, pricing, proposal templates, message templates (items 4–7) |
| 19 | Item screens: governance | playbooks, approval rules, settings, integrations, retention (items 8–12) |
| 20 | Item screens: optional | demo teams, calendar, vendors, and item 16's permanent `—` (items 13–16) |
| 21 | Import: parse + validate + preview | papaparse, per-row verdicts, template download |
| 22 | Import: apply + failures file | continue-on-error, `_error` column, round-trip re-import (D21) |
| 23 | Go-live check | skill coverage, program completeness, rule ordering, delivery honesty, domain |
| 24 | Reset + catalogue bundle | three flags, dry-run counts, blocking edges, org-name confirmation, export/import |
| 25 | Build, mount, verify | `npm run build`, confirm `/dashboard` serves, re-run all guards |

> **Two different tier numberings are in play and must not be conflated.** The
> **rail** groups by the manual's tiers — Essential (items 2–8), Strongly
> recommended (9–12), Optional (13–16), item 1 at platform level (§5.1). The
> **build order** above groups by the *dependency* tiers of
> `02_SEEDING_PREREQUISITES.md` §0. They disagree on item 8 (playbooks), which
> depends on programs but is built with governance in Task 19. That is
> deliberate: Task 19 owns every screen whose descriptor carries a free `dict`.

## File structure — Phase 2

| File | Responsibility |
|---|---|
| `Dashboard/package.json`, `tsconfig.json`, `vite.config.ts`, `index.html` | Task 11 |
| `Dashboard/tools/dump_openapi.py` | dumps `openapi.json` **and** the constants vocabularies |
| `Dashboard/tools/gen.mjs` | orchestrates dump → generate → lift; `--check` mode |
| `Dashboard/tools/lift_constraints.mjs` | A3 — the 16 dropped constraints |
| `src/api/openapi.json` · `generated.ts` · `constraints.generated.ts` · `vocabularies.generated.ts` | generated, all four committed |
| `src/api/client.ts` · `endpoints.ts` · `errors.ts` | Task 13 |
| `src/api/reads.ts` · `src/api/__fixtures__/` | A1 — Task 15 |
| `src/session/store.ts` · `handoff.ts` | Tasks 13, 14 |
| `src/descriptors/types.ts` + 11 entity modules | Task 15 |
| `src/checklist/items.ts` · `status.ts` | Task 16 |
| `src/import/parse.ts` · `validate.ts` · `template.ts` · `apply.ts` · `failures.ts` | Tasks 21–22 |
| `src/ui/tokens.css` + primitives | Task 12 |
| `src/screens/**` | Tasks 14, 17–20, 23, 24 |
| `src/**/*.test.ts` | the four suites of the test strategy |
| `Dashboard/dist/` | Task 25 — committed (D10) |

---

### Task 11: Scaffold and the generation pipeline

**Files:**
- Create: `Dashboard/package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `src/main.tsx`, `src/App.tsx`
- Create: `Dashboard/tools/dump_openapi.py`, `Dashboard/tools/gen.mjs`, `Dashboard/tools/lift_constraints.mjs`
- Generated: `src/api/openapi.json`, `src/api/generated.ts`, `src/api/constraints.generated.ts`, `src/api/vocabularies.generated.ts`
- Test: `src/api/generation.test.ts`

**Interfaces:**
- Produces: `schemas` (85 Zod schemas + `state`, keyed by component name) from
  `generated.ts`; `CONSTRAINTS` from `constraints.generated.ts`; `VOCAB` from
  `vocabularies.generated.ts`. Every later task consumes these three and
  hand-types none of them.
- Consumes: the FastAPI app, by import — **not** by HTTP.

- [x] **Step 1: Scaffold with pinned versions**

`Dashboard/package.json`. Eight runtime dependencies and six dev, no more
(§2 allowed four dev; `@vitejs/plugin-react` and `@types/*` are build plumbing
the stack choice already implies, and are listed here rather than smuggled in):

```
dependencies:  react ^19  react-dom ^19  react-router-dom ^7
               @tanstack/react-query ^5  react-hook-form ^7
               zod ^3.25  @hookform/resolvers ^3  papaparse ^5
devDependencies: vite ^7  @vitejs/plugin-react ^5  typescript ^5
               vitest ^3  openapi-zod-client 1.18.3  @types/papaparse ^5
```

> **As shipped this is SIX runtime dependencies, not eight.**
> `react-hook-form` and `@hookform/resolvers` were installed here, never
> imported by any task, and **removed at Task 19** — the whole validation
> surface is `validate(descriptor, values)`, a pure function over a plain
> object, and what a form library would have added is the resolver plumbing
> that function replaces. The list above is left as it was written so the
> decision is visible; `package.json` is the authority. Do not reinstate them
> from this block.

> **`zod` must stay on 3.x.** `openapi-zod-client@1.18.3` emits v3 syntax —
> `.passthrough()`, `z.string().email()`, `.partial()`. Zod 4 changes all three.
> Verified: the generator resolved `zod@3.25.76` in a scratch install and its
> output parses under it.
>
> **`openapi-zod-client` is pinned exactly, no caret.** `gen:check` diffs
> generated output; a minor bump that reformats one schema would fail every
> build with no code change. Bumping it is a deliberate act with a regenerate.

`vite.config.ts` sets `base: "/dashboard/"` — the bundle is served from a
sub-path by change #8, and a default `base` of `/` emits asset URLs that 404
there. Set `build.outDir: "dist"`.

- [x] **Step 2: Write the dumper**

`Dashboard/tools/dump_openapi.py`. It imports the app and writes two files.

```python
"""Dump the backend's OpenAPI spec and its closed vocabularies for the console.

Lives under Dashboard/ on purpose: nothing dashboard-related goes under app/
(05_DECISIONS.md D19). Imports the app rather than fetching from a running
server, so generation works with the backend down (06_DESIGN.md §3.1) —
verified this session to produce a spec identical to the served one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # Complete_Project/
sys.path.insert(0, str(ROOT))

from app.core import constants                      # noqa: E402
from app.main import app                            # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "src" / "api"


def _members(enum) -> list[str]:
    return [m.value for m in enum]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # ensure_ascii=False + explicit utf-8: the descriptions carry § — → and
    # both Python and Node default to the system codepage on Windows. A
    # mis-encoded dump makes gen:check diff forever against a file that only
    # looks identical.
    spec = app.openapi()
    (OUT / "openapi.json").write_text(
        json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # A4: the four vocabularies the API validates in handler bodies and so
    # cannot express in OpenAPI. Generated, never hand-typed — RoleGate.java
    # is one permission behind because it was hand-typed (Q15).
    vocab = {
        "role": _members(constants.Role),
        "org_role": sorted(r.value for r in constants.ORG_ROLES),
        "department": _members(constants.Department),
        "template_kind": _members(constants.TemplateKind),
        "message_channel": _members(constants.MessageChannel),
        "skill_level": _members(constants.SkillLevel),
        "phase": _members(constants.Phase),
    }
    body = json.dumps(vocab, indent=2, ensure_ascii=False)
    (OUT / "vocabularies.generated.ts").write_text(
        "// GENERATED by Dashboard/tools/dump_openapi.py — do not edit.\n"
        "// Source: app/core/constants.py. Enforced in handler bodies, so it\n"
        "// cannot appear in openapi.json (07_BUILD_PLAN.md P3/A4).\n"
        f"export const VOCAB = {body} as const;\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
```

**Confirm it agrees with the running server before trusting it:**

```bash
curl -s http://127.0.0.1:8000/openapi.json -o /tmp/served.json
python Dashboard/tools/dump_openapi.py
python -c "import json;a=json.load(open('Dashboard/src/api/openapi.json',encoding='utf-8'));b=json.load(open('/tmp/served.json',encoding='utf-8'));print('identical:',a==b)"
```

Expected: `identical: True`. (It was, this session — 151 operations,
85 schemas.) If it is False, **read the diff before going further**; a dumper
that disagrees with the server generates a client for an API nobody is running.

- [x] **Step 3: Write the constraint lift (A3)**

`Dashboard/tools/lift_constraints.mjs` reads the committed `openapi.json` and
emits `src/api/constraints.generated.ts`:

```
export const CONSTRAINTS = {
  SettingsRequest: {
    assignment_mode: { pattern: "^(auto|lead_confirm)$" },
    audio_retention_days: { minimum: 1, maximum: 3650 },
    ...
  },
  CreateUserRequest: { max_open_tasks: { minimum: 1, maximum: 100 } },
  ...
} as const;
```

Rules: for every component schema, for every property, collect
`minimum`/`maximum`/`exclusiveMinimum`/`exclusiveMaximum`/`minLength`/
`maxLength`/`pattern`/`minItems`/`maxItems` from the property **and** from each
`anyOf` branch, merging branch values up. Emit only non-empty entries.

**The output must contain the 16 rows of P2's right-hand column.** Assert that
in Step 5 rather than eyeballing it.

- [x] **Step 4: Wire the three npm scripts**

`Dashboard/tools/gen.mjs` runs the pipeline in one Node process, so the scripts
work identically in PowerShell, Git Bash and CI — chained `cd .. && python ...`
in an npm script does not:

1. spawn `process.env.PYTHON ?? "python"` on `tools/dump_openapi.py`
2. spawn `openapi-zod-client` on `src/api/openapi.json`:
   `-o src/api/generated.ts --export-schemas -t node_modules/openapi-zod-client/src/templates/schemas-only.hbs`
3. run the lift

```json
"scripts": {
  "gen:api":   "node tools/gen.mjs",
  "gen:check": "node tools/gen.mjs --check",
  "prebuild":  "npm run gen:check",
  "build":     "tsc -b && vite build",
  "test":      "vitest run"
}
```

`--check` writes all four artefacts to a temp directory and byte-compares
against the committed ones (**reading both as UTF-8**), printing the first
differing file and exiting non-zero. As `prebuild`, that makes **`npm run build`
fail when the backend has moved and the client has not** (§3.2 mechanism 1).

> **Use `schemas-only.hbs`, not the default template.** The default emits a
> Zodios client (`import { makeApi, Zodios } from "@zodios/core"`) and pulls
> Zodios + axios into the dependency list; §4.1 needs a hand-written client with
> a settable base URL, per-call token choice and `retry: 0` anyway. Measured on
> this spec: default template 107 KB with a Zodios import; `schemas-only`
> **25 KB, one import — `zod`**, still exporting all 85 schemas under
> `export const schemas`.

- [x] **Step 5: Write the failing test, then make it pass**

```ts
// src/api/generation.test.ts
// The generated layer is only worth having if it is provably the backend's.
import { describe, expect, it } from "vitest";
import spec from "./openapi.json";
import { schemas } from "./generated";
import { CONSTRAINTS } from "./constraints.generated";
import { VOCAB } from "./vocabularies.generated";

const CONSTRAINT_KEYS = ["minimum","maximum","exclusiveMinimum","exclusiveMaximum",
  "minLength","maxLength","pattern","minItems","maxItems"] as const;

it("every component schema is exported", () => {
  for (const name of Object.keys(spec.components.schemas))
    expect(schemas, name).toHaveProperty(name);
});

it("every constraint in the spec survives into generated.ts or the lift", () => {
  // P2: openapi-zod-client drops constraints declared inside an anyOf branch.
  // Whichever side carries a rule, it must be carried by one of them — a rule
  // present in neither is a server rule the console does not know about.
  const missing: string[] = [];
  for (const [name, s] of Object.entries<any>(spec.components.schemas)) {
    for (const [field, prop] of Object.entries<any>(s.properties ?? {})) {
      const rules = [prop, ...(prop.anyOf ?? [])]
        .flatMap((n) => CONSTRAINT_KEYS.filter((k) => n?.[k] !== undefined));
      if (!rules.length) continue;
      const lifted = (CONSTRAINTS as any)[name]?.[field];
      const inZod = !!(prop as any)[rules[0]];   // declared directly ⇒ emitted
      if (!inZod && !lifted) missing.push(`${name}.${field}`);
    }
  }
  expect(missing).toEqual([]);
});

it("carries the constraints the generator is known to drop", () => {
  // Named explicitly: a lift that silently started emitting nothing would
  // pass the test above (which only checks 'one side has it') if the zod
  // branch also regressed. These are the observed drops of P2.
  expect(CONSTRAINTS.SettingsRequest.assignment_mode.pattern)
    .toBe("^(auto|lead_confirm)$");
  expect(CONSTRAINTS.CreateUserRequest.max_open_tasks)
    .toEqual({ minimum: 1, maximum: 100 });
  expect(Object.keys(CONSTRAINTS.SettingsRequest)).toHaveLength(14);
});

it("vocabularies are non-empty and org roles exclude super_admin", () => {
  expect(VOCAB.department).toEqual(["sales", "operations", "accounts"]);
  expect(VOCAB.org_role).not.toContain("super_admin");   // D1, Q14
  expect(VOCAB.phase.length).toBeGreaterThan(0);
});
```

Run it **before** generating: it must fail on the missing files, not pass
vacuously. Then `npm run gen:api` and run it again — 4 passing.

> The `toHaveLength(14)` above is the count of `SettingsRequest` fields carrying
> a dropped constraint (15 rows of P2's right column minus the two
> `max_open_tasks` rows, which live on `CreateUserRequest` and
> `UpdateUserRequest`). **Re-derive it from the lift output rather than trusting
> this number** if the spec has moved.

- [x] **Step 6: Prove `gen:check` actually fails**

Edit one character in `src/api/generated.ts`, run `npm run build`, and confirm
it stops at `prebuild`. Restore. **A guard never observed failing is not a
guard** — this is the same rule Task 9 applied to the mount.

- [x] **Step 7: Checkpoint**

`npm run gen:api` is idempotent (run twice, `git status` clean); `npm test`
green; `npm run build` succeeds and `dist/index.html` exists. Commit all four
generated artefacts.

---

### Task 12: Design tokens and primitives

**Files:**
- Create: `src/ui/tokens.css`, `src/ui/*.tsx` primitives, `src/screens/Styleguide.tsx`

**Interfaces:**
- Produces: `Button`, `TextField`, `NumberField`, `SelectField`, `CheckboxField`,
  `Caption`, `StatusMarker`, `Panel`, `DataTable`, `Modal`, `Banner`, `Quote`.
- Consumes: nothing. No task before 12 renders anything but the styleguide.

- [x] **Step 1: Tokens**

`tokens.css`, per §9. Near-monochrome paper/ink, one accent. Three families:
serif (headings **and the manual's quoted text**), grotesque (UI), mono (codes,
keys, paths, JSON, and every constraint caption). Light and dark both defined
from tokens — `:root` carries the full light palette, a
`@media (prefers-color-scheme: dark)` block redefines only the values.

`--product-name: "Innodhara"` is **one token** (D15) and the header reads
`Innodhara · Setup Console`. Nothing else in the console names the product.

- [x] **Step 2: The four status markers**

`●` `◐` `○` `—`, from §6. **Only `◐` and `—` take colour**, because those are
the two the operator must look at; `●` and `○` are carried by weight alone. Each
marker takes a required `label` prop and renders it to assistive text — a glyph
alone is not a status to a screen reader.

- [x] **Step 3: The form row**

Single column, label left, control right, constraint beneath in small mono
(§9). The constraint line renders from a descriptor field's `enforcement`:

- `schema` → plain caption, e.g. `admin.py · ProgramRequest — 1–50 characters`
- `backend-undeclared` → plain caption **plus its citation**, e.g.
  `admin.py · _validated_department — sales, operations or accounts`
- `ui-only` → the distinct marker plus, verbatim,
  **"this console checks this; the server does not"**

**Captions cite file and symbol, never line numbers** (Global Constraints).

- [x] **Step 4: Styleguide route + checkpoint**

`/styleguide` renders every primitive in every state, both themes. It is the
only way this task is verifiable without the later screens. `npm run build`
green; open it in both colour schemes.

---

### Task 13: `api/client.ts` and the session layer

**Files:**
- Create: `src/api/client.ts`, `src/api/errors.ts`, `src/api/endpoints.ts`, `src/session/store.ts`, `src/ui/SessionBar.tsx`
- Test: `src/api/errors.test.ts`

**Interfaces:**
- Produces: `request<T>(spec, {as: "super" | "org", shape?})`; `AppError`;
  `useSuper()` / `useOrg()`; the base-URL field; `reportDrift()`.
- Consumes: Task 11's `schemas`.

- [x] **Step 1: The error shape, from the backend's own handler**

Read `app/core/exceptions.py` and `app/main.py`'s handlers before writing this
and match what they actually emit. `AppError` carries `status`, `detail`
(**the server's message, verbatim, never paraphrased** — §4.1) and, for 422,
the `HTTPValidationError.detail[]` array mapped to field paths so a form can
show a server error against the right field.

- [x] **Step 2: The router — hash, not path (A8)**

`createHashRouter`, so every URL is `/dashboard/#/staff`. The mount serves no
SPA fallback (**P10**, proved in Task 11), so a `createBrowserRouter` console
would 404 on every refresh and every shared link while working perfectly during
a click-through — the worst kind of bug to find late. Do not "improve" this to
path routing without a backend fallback route, which the closed change list does
not have.

- [x] **Step 3: Base URL and tokens**

Base URL is a **field in the app**, defaulting to `http://127.0.0.1:8000`
(`config.py`'s default). **Nothing hard-codes `9010`** — that is a demo-runbook
override, not a default (Q19).

Two tokens in **`sessionStorage`**, never `localStorage` (§4.2). The session bar
names which identity the current action runs as, and is permanent.

- [x] **Step 4: `retry: 0` on every mutation**

The `QueryClient` sets `mutations: { retry: 0 }`. Reads may retry.

Add the one-line comment that makes this survive a future refactor: *the server
reads no `Idempotency-Key` and has no dedupe on admin writes (D17, verified), so
a retried POST creates a second row.* Someone will otherwise "fix" this by
turning retries on.

- [x] **Step 5: Read-shape parsing and the drift banner (A1)**

When `request` is given a `shape`, `safeParse` the body. On failure:
**do not throw and do not render the data.** Record a drift report (route,
Zod issue path, the received keys) and render the app-level banner:

> The server's reply for `GET /approval-rules` no longer matches what this
> console expects at `[0].rank`. Statuses derived from it are shown as `—`
> until this is fixed.

Every checklist status derived from a drifted read becomes `—` with that reason
(§6: never show a status you cannot verify). **A drifted read must never
degrade to `○`** — "not started" and "cannot be read" are different facts.

- [x] **Step 6: Test and checkpoint**

`errors.test.ts`: a 422 `HTTPValidationError` maps to per-field messages; a 403
`{"detail": "..."}` surfaces the string unchanged; a network failure is
distinguishable from a 500. Table-driven. `npm test` green.

---

### Task 14: Org creation and the chained hand-off

**Files:**
- Create: `src/session/handoff.ts`, `src/screens/CreateOrg.tsx`, `src/screens/SignIn.tsx`, `src/ui/HandoffModal.tsx`
- Test: `src/session/handoff.test.ts`

**Interfaces:**
- Produces: `runHandoff(...) -> {orgId, orgName, emailDomain, adminToken}`, and a
  live org_admin session. `emailDomain` is stashed for Task 23 (A6 step 1).
- Consumes: Task 13's client; `schemas.CreateOrgRequest`, `CreateOrgResponse`,
  `LoginRequest`, `LoginResponse`, `ChangePasswordRequest`.

- [x] **Step 1: `handoff.ts` as a pure, testable state machine**

Four states, from D18 / §4.2:

1. `POST /orgs` as `super_admin` → `admin_temp_password`, **in memory only**
2. `POST /auth/login` as the new org_admin with that temp password
3. `POST /auth/change-password` to the password collected on the form
4. release; the checklist opens

The chain runs behind a modal with **no dismiss control, no overlay click-out
and no escape key, in either state.**

**Step 3 is not optional**: `must_change_password` is set by the server and read
by no dependency — verified. If the console does not enforce it, nothing does.

- [x] **Step 2: The recovery state**

If step 2 or 3 fails after step 1 succeeded, the modal switches to recovery:
**reveal the temp password**, name the failed step, and list the two calls to
complete by hand. Hiding it there converts a recoverable failure into a stranded
organisation (§12).

On the happy path the operator never sees it at all.

- [x] **Step 3: Constraints on the form, from the right sources**

`name` 2–200, `slug` 2–100 `^[a-z0-9-]+$`, `email_domain` 3–200,
`admin_email` email — all four `schema` (P2 confirmed they survive).
`new_password` ≥ 8 is **`backend-undeclared`**, cited `auth.py · change_password`
(P3).

**Branding is write-once** — `logo_url` and `brand_colors` cannot be changed by
any API afterwards (no `PATCH /orgs/{id}`). The form says so **inline at the
field, before submit** (D15).

- [x] **Step 4: Sign in to an existing org (P6/A5)**

A returning operator has no super-admin session, so `CreateOrg` cannot be the
only entry. `SignIn` posts `POST /auth/login` with email + password
(+ optional `org_slug`) and, if `must_change_password` comes back `true`, forces
the change before the checklist opens — the same rule as step 3, for the same
reason. The org **picker** built on `GET /orgs` renders only while a super-admin
session exists.

- [x] **Step 5: Test and checkpoint**

`handoff.test.ts` with a stubbed client: happy path never exposes the password;
a step-2 failure and a step-3 failure each produce the recovery state carrying
it; the modal state machine has no path to "dismissed". Then **run it against
the live backend once** and create a throwaway org — this is the one flow whose
failure is unrecoverable, and a stub cannot prove the server agrees.

---

### Task 15: Descriptors, read shapes, and the four drift tests

**Files:**
- Create: `src/descriptors/types.ts` + `staff.ts`, `skills.ts`, `programs.ts`, `pricing.ts`, `proposalTemplates.ts`, `messageTemplates.ts`, `playbooks.ts`, `approvalRules.ts`, `demoTeams.ts`, `vendors.ts`, `settings.ts`
- Create: `src/api/reads.ts`, `src/api/__fixtures__/*.json`, `tools/capture_fixtures.mjs`
- Test: `src/descriptors/conformance.test.ts`, `src/api/reads.test.ts`

**Interfaces:**
- Produces: `Descriptor` (schema name, write endpoint, CSV column order, example
  row, per-field rules, the manual's quote, the "if you skip it" text,
  dependencies); `READS` (11 Zod schemas).
- Consumes: `schemas`, `CONSTRAINTS`, `VOCAB` from Task 11.

- [x] **Step 1: `types.ts` — three enforcement values, not two (A2)**

```ts
export type Enforcement =
  | { kind: "schema" }                                  // in generated.ts
  | { kind: "backend-undeclared"; source: string }      // e.g. "admin.py · _validated_department"
  | { kind: "ui-only"; why: string };                   // the server accepts anything

export type FieldRule = {
  field: string;              // must exist in the entity's generated schema
  label: string;
  control: "text" | "number" | "select" | "checkbox" | "textarea" | "json" | "quantity";
  enforcement: Enforcement;
  caption: string;            // rendered beneath the control (§9)
  options?: readonly string[];// from VOCAB — never a literal list
};
```

A `ui-only` rule **must** carry `why`, so the caption can say what the server
does instead. Make it structurally required, not a convention.

- [x] **Step 2: The eleven descriptors**

Quotes come from `02_SEEDING_PREREQUISITES.md` §§1–16, which extracted them
verbatim from `Innodhara_Product_Manual.pdf` pp. 6–7. **Quote, do not
paraphrase** — the product's own voice is the point (§9).

Worked examples, so the three enforcement values are unambiguous:

| Field | Enforcement | Why |
|---|---|---|
| `ProgramRequest.code` | `schema` | `minLength`/`maxLength` are in `generated.ts` |
| `CreateUserRequest.role` | `backend-undeclared`, `admin.py · register_staff` | options from `VOCAB.org_role` |
| `CreateUserRequest.department` | `backend-undeclared`, `admin.py · _validated_department` | options from `VOCAB.department` |
| `CreateUserRequest.max_open_tasks` | `backend-undeclared`, `admin.py · CreateUserRequest` | bounds from `CONSTRAINTS` (P2) |
| `SettingsRequest.assignment_mode` | `backend-undeclared`, `admin.py · SettingsRequest` | pattern from `CONSTRAINTS` |
| `SkillRequest.level` | **`ui-only`** | `ops.py · set_skill` stores the string unchecked; `VOCAB.skill_level` is the engine's vocabulary, not a validation |
| `PlaybookRequest.phase` | **`ui-only`** | `ops.py · upsert_playbook` accepts any string; a phase outside `VOCAB.phase` produces a playbook **no plan will ever fire** — say exactly that in `why` |
| `SettingsRequest.working_days`, `client_report_day` | `ui-only` | Pydantic says `list[str]` / `str` |
| `SettingsRequest.nudge_gap_days`, `reply_nudge_after_days`, `payment_reminder_schedule` | `ui-only` | free `dict` / `list[dict]` |
| `ApprovalRuleRequest.condition` | `ui-only` | free `dict`; the 13 observed keys are a suggestion list, not a schema |
| `PlaybookRequest.entries` | `ui-only` | `list[dict]`, no sub-model |
| `PricingItem.default_quantity` | `ui-only` | OpenAPI can say `number \| null`; it cannot say `null` means *"this org did not say how many"* |

**`default_quantity` is a checkbox plus a number, never a number pre-filled with
`1`** (§3.3). `admin.py · PricingItem` carries the ten-line comment explaining
that flattening this tri-state was a real regression.

- [x] **Step 3: `reads.ts` — the eleven untyped reads (A1)**

One Zod schema per untyped read, each with a header comment citing the handler
it was transcribed from. Transcribe from the handler's literal `return` — that
is the contract, whatever the route's docstring says. The eleven, with their
handlers:

`list_skills`, `list_programs`, `get_pricing_history`, `list_proposal_templates`,
`list_message_templates`, `list_playbooks`, `list_approval_rules`,
`get_org_settings` (i.e. `_settings_response`), `list_demo_teams`,
`list_vendors`, `reset_organisation`.

Two of them read back **everything the write accepts**, which they did not before
changes #9 and #10 — model every field, and there is **no `notReadable` list on
any descriptor**:

- **`list_approval_rules` includes `fallback_role` and `auto_approve`** (P4,
  fixed). Field order in the response mirrors `ApprovalRuleRequest`.
- **`list_demo_teams` includes `lead_user_id` / `media_rep_id` /
  `sales_rep_id` alongside `lead` / `media_rep` / `sales_rep`** (P5, fixed).
  Model **both**: the names are what the screen shows, the ids are what the
  recreate and the bundle need. `members` stays `[{id, name}]`.

`_settings_response` returns the 25 dial fields **plus** the 10 delivery-honesty
fields added by change #2: `email_mode`, `whatsapp_mode`, `calendar_mode`,
`inbound_email_mode`, the three `*_credentials_stored` booleans and the three
`*_integration_configured` booleans. Task 16's compound statuses need all ten.

- [x] **Step 4: Fixture capture**

`tools/capture_fixtures.mjs` signs in against a live backend and writes one
response per read to `src/api/__fixtures__/`. Run it against an org with data in
**every** entity — an empty array parses under any shape and proves nothing.
Redact nothing: these are catalogue rows from a throwaway org, and a fixture
edited by hand stops being evidence.

- [x] **Step 5: The four drift tests (§3.2)**

```
1. field-exists  — every descriptor FieldRule.field exists in
                   schemas[descriptor.schemaName].shape
2. coverage      — all 11 descriptor modules resolve to a generated schema,
                   and all 11 read shapes are exercised by a fixture
3. constraints   — every `schema` rule is actually IN generated.ts, and every
                   `backend-undeclared` rule that claims a bound resolves in
                   CONSTRAINTS. A rule claiming a source that carries nothing
                   is the failure being caught.
4. fixtures      — every captured fixture parses under its read shape
```

Test 3 is the one that earns its keep: without it, a field could be labelled
`schema` while the generator dropped its constraint (P2) and the caption would
claim server enforcement the console never validates.

- [x] **Step 6: Prove tests 1 and 4 fail**

Rename a descriptor field to `nam` → test 1 red. Delete a key from a fixture →
test 4 red. Restore both. `npm test` green.

---

### Task 16: The checklist rail and status derivation

**Files:**
- Create: `src/checklist/items.ts`, `src/checklist/status.ts`, `src/ui/Rail.tsx`
- Test: `src/checklist/status.test.ts`

**Interfaces:**
- Produces: `ITEMS` (16 rows: number, tier, title, quote, ifSkipped, deps) and
  `deriveStatus(item, reads) -> {marker, caption}` — **pure functions**.
- Consumes: Task 15's `READS`.

- [x] **Step 1: `items.ts`**

16 items, tiered as the **manual** tiers them (§5.1): item 1 at platform level,
Essential = items 2–8, Strongly recommended = 9–12, Optional = 13–16. Each row
carries the manual's own words for what breaks if it is skipped
(`02_SEEDING_PREREQUISITES.md` §§1–16). Tiers are **labelled groups separated by
a rule line, not cards** (§9). The rail is permanently visible and **is** the
product — there is no widget-grid home screen.

- [x] **Step 2: `status.ts` — pure, and never optimistic**

Implement §5.2's table exactly. **No local "I did that" flags**: a status the
console cannot verify is not shown as done.

Three cases carry the whole honesty model and must be written first:

- **Item 1 derives from `GET /auth/me` alone** (P6/A5) — `org_id` present and a
  live admin session. Not `GET /orgs`, which this session cannot call.
- **Item 10 is `◐` at untouched defaults**, captioned *"defaults apply — the API
  cannot tell whether you chose them"*. Compare against the model defaults in
  `app/models/organisation.py · OrgSettings`; equal on every dial ⇒ `◐`.
- **Item 11 is compound and never `●` on `dry_run`.** Mail leaves only when
  **both** halves hold. Render one line:
  *credentials stored · sending is **OFF** on this server (`EMAIL_MODE=dry_run`)*
  and mark it `◐`. `email_integration_configured` is now honest (change #2), but
  derive from the two halves anyway — the compound caption needs both facts and
  a single boolean cannot say which one is missing.
- **Item 14** is the same compound over `calendar_mode` + `calendar_credentials_stored`.
- **Item 16 is permanently `—`**, showing the manual's fallback verbatim:
  *"Replies are captured by hand with Log a reply, which works fully and takes
  seconds."* — with the reason: inbound mail has no column, no endpoint and no
  per-org storage, and is open finding **F35** with a standing instruction to
  keep it off.

Add the case A1 introduced: **a read that failed to parse yields `—` with the
drift reason**, never `○`.

- [x] **Step 3: Table-driven tests**

Fixture payloads in, expected `{marker, caption}` out — the fixtures captured in
Task 15, trimmed. Cover: each of the four markers at least once; item 10's
untouched-defaults case; item 11 with credentials + `dry_run` (**must be `◐`,
must never be `●`**); item 11 with credentials + `smtp` (`●`); item 3 partial
coverage (`◐`) vs full (`●`); item 7 at 1, 3 and 4 of the four `kind × channel`
combinations; a drifted read (`—`).

- [x] **Step 4: Checkpoint**

`npm test` green; the rail renders against the live backend and its statuses
match what the API actually holds — check two by hand against `curl`.

---

### Task 17: Item screens — staff and skills (items 2–3)

**Files:**
- Create: `src/screens/Staff.tsx`, `src/screens/StaffDetail.tsx`, `src/screens/Skills.tsx`, `src/ui/EntityForm.tsx`, `src/ui/FormatPanel.tsx`

**Interfaces:**
- Produces: `<EntityForm descriptor={...}>` — the generic screen every later
  item screen reuses. Getting it right here is most of Tasks 18–20.
- Consumes: descriptors, `READS`, client.

- [x] **Step 1: `EntityForm` and `FormatPanel` from the descriptor**

~~`react-hook-form` + `@hookform/resolvers/zod`, resolver built from~~ the
entity's generated schema **extended with** its `CONSTRAINTS` entry and its
`ui-only` rules. The `FormatPanel` is the in-app spec, rendered from the same
descriptor (§3.4) — never a second copy of the field list.

> **Neither library was used, and both are now uninstalled.** The three
> validation layers live in `src/ui/entityValidation.ts` as
> `validate(descriptor, values)` — a pure function over a plain object, tested
> without a DOM (D11). A resolver would have been a wrapper around it, and
> `EntityForm` needs seven `useState` calls, not a form library. Recorded rather
> than quietly diverged from; **Task 19 was the decision point and removed the
> packages.**

- [x] **Step 2: Staff**

Fields from `CreateUserRequest` (change #1). `role` and `department` are selects
fed from `VOCAB.org_role` / `VOCAB.department` (A4).

**Handle the temp password (P8).** `POST /admin/users` returns
`{...UserResponse, temp_password}`. Show it once, with a copy control, and state
plainly:

> This password is shown once. If it is lost, issue a new one from this
> person's row — nothing else is affected.

pointing at `POST /admin/users/{user_id}/reset-password`. **State the contrast
with the org admin's temp password explicitly**, because they look identical and
behave oppositely: a staff password is recoverable; the org admin's is not,
which is why Task 14 has a modal and this does not.

The domain rule (`admin.py · register_staff`) is `backend-undeclared`, captioned
with the org's own domain when known (Task 14 step 1 / A6).

- [x] **Step 3: Staff detail and edit**

`GET /admin/users/{user_id}` (change #4) drives detail; `PATCH` drives edit.
Deactivate rather than delete — there is no staff DELETE, deliberately (§12,
D16: `users` is in KEEP under every reset flag).

`UpdateUserRequest` is `.partial().passthrough()` (P9), so send only changed
fields; an omitted field is left alone.

- [x] **Step 4: Skills**

`POST /skills` **upserts** on `(user_id, skill)`; `DELETE /skills` takes that
same natural key, because `GET /skills` returns no row id. Free-text skill name
with autocomplete drawn from skills already held in the org (Q12) —
**no hard-coded taxonomy**, ever.

Surface the delete guard's refusal verbatim when it fires: *"N open task(s) need
'X' and nobody else holds it."*

`level` is **`ui-only`** — the select offers `VOCAB.skill_level`, and the caption
says the server stores whatever it is sent.

- [x] **Step 5: Checkpoint**

Against a live throwaway org: create staff, see the temp password once, set
skills, delete a skill, hit the guard on the last holder of a skill with open
work. Items 2 and 3 go green in the rail.

---

### Task 18: Item screens — the catalogue (items 4–7)

**Files:**
- Create: `src/screens/Programs.tsx`, `Pricing.tsx`, `ProposalTemplates.tsx`, `MessageTemplates.tsx`, `src/ui/VersionHistory.tsx`

- [x] **Step 1: Programs**

`code` is upper-cased on write and unique per org (`admin.py · add_program`) —
say so at the field, since the operator's typed value comes back changed.
No `PATCH`: editing is delete-and-recreate, and the delete is **refused** when a
project or proposal references the program. Say both, up front (§5.4).

- [x] **Step 2: Pricing — the tri-state, and versioning**

`default_quantity` is **a checkbox plus a number**. Unchecked sends `null`.
Never pre-fill `1` (§3.3, Task 15 step 2).

The button says **"Publish new version"**, not "Save" (§5.3), and the version
history is shown, not hidden — a proposal locks `pricing_table_id` +
`pricing_version`, which is what makes editing a rate card safe.

`DELETE .../pricing/{version}` is refused when a proposal references that row,
and **deleting the current version promotes the highest remaining one back to
`is_current`** (§7.2) — show the promotion in the result, or the operator will
think the delete did nothing.

- [x] **Step 3: Proposal templates**

`body_md` ≥ 20 chars (`schema`). Same "Publish new version" model. Same
promote-on-delete.

- [x] **Step 4: Message templates**

All four `kind × channel` combinations drive item 7's status. `kind` and
`channel` come from `VOCAB` and are `backend-undeclared`
(`admin.py · add_message_template`). **An email template requires a subject** —
same enforcement, same citation; enforce it client-side too so the operator
learns before the round trip.

The delete is unguarded by design, but **removing the only `intro`/`email`
template breaks business-card intro drafting**, so item 7 turns amber
immediately: *the checklist is the guard there, not a 409* (§7.2). Say that on
the delete confirmation.

- [x] **Step 5: Checkpoint**

Live: create a program, publish two pricing versions, delete the current one and
watch v1 return to current, publish a template, create all four message
templates. Items 4–7 green.

---

### Task 19: Item screens — governance and behaviour (items 8–12)

**Files:**
- Create: `src/screens/Playbooks.tsx`, `ApprovalRules.tsx`, `Settings.tsx`, `Integrations.tsx`, `Retention.tsx`, `src/ui/JsonField.tsx`

- [x] **Step 1: Playbooks (item 8)**

`GET /playbooks` is change #3 — the read that made this screen possible.
`entries` is `list[dict]` with no sub-model: a `JsonField` with an example, an
in-app format panel, and a `ui-only` marker.

`phase` is `ui-only` and dangerous: the server accepts any string, and a phase
outside `VOCAB.phase` yields a playbook **no plan will ever fire**. Offer
`VOCAB.phase` as a select, allow the free value, and say exactly that.

`POST /playbooks` supersedes the current playbook for that `(program_id, phase)`
— "Publish new version". Delete promotes the predecessor.

- [x] **Step 2: Approval rules (item 9)**

**Two hazards on one screen**, both of which must be said out loud:

1. **No `PATCH`.** Editing is delete-then-create, which changes the row id and
   is **non-atomic** — a failure between the two leaves the org with *no* rule
   where it had one, silently changing who approves client-facing messages. The
   edit control states this, and **re-reads the rule list afterwards** to confirm
   the replacement landed (§5.4).
2. **Rank ordering decides which rule fires.** Show rules grouped by
   `entity_type` in `rank` order, and flag an `entity_type` with no catch-all
   `{}` rule (item 9's `◐`).

**Every field the write accepts now reads back**, `fallback_role` and
`auto_approve` included (change #9), so the delete-then-create edit path
preserves the whole rule and there is nothing to warn about on that front.

`condition` is a free `dict` (`ui-only`); offer the 13 observed keys as
suggestions and say they are suggestions.

- [x] **Step 3: Settings — items 10 and 12**

25 dials from `SettingsRequest`. **14 of them carry `backend-undeclared` bounds
that only `CONSTRAINTS` knows** (P2) — pattern, min and max must reach the
controls, or the console silently permits values the server will reject.

**`PATCH /admin/settings` cannot reset a field to null.** It applies with
`exclude_none=True` over a blind `setattr` loop
(`admin.py · update_org_settings`), so an omitted field is left unchanged and
there is no way back to null. **Offer no clear control** — one that silently did
nothing would be worse than its absence — and say why (§5.4).

Item 12 (retention) reads the same row; show the current windows and note they
are always satisfied.

- [x] **Step 4: Integrations (items 11 and 14)**

Three `PUT` routes, none of which returns what it stored. Render the compound
status from Task 16 above each: *credentials stored · sending is **OFF** on this
server*.

State the two facts §12 records: the calendar credentials value is a
**server-side path that must already exist** — the console cannot upload a file
— and unlike email and WhatsApp **it is stored unencrypted**.

`EMAIL_MODE`, `CALENDAR_MODE` and `INBOUND_EMAIL_MODE` are **process-wide env
vars** the console cannot change; show them read-only and say so.

- [x] **Step 5: Checkpoint**

Live: publish a playbook, create rules at two ranks and see the ordering,
change a dial and watch item 10 go from `◐` to `●`, store email credentials and
watch item 11 stay `◐` while `EMAIL_MODE=dry_run`. **That last one is the single
most important behaviour in the console** — verify it by hand.

---

### Task 20: Item screens — optional (items 13–16)

**Files:**
- Create: `src/screens/DemoTeams.tsx`, `Calendar.tsx`, `Vendors.tsx`, `InboundMail.tsx`

- [x] **Step 1: Demo teams (item 13)**

The read now carries **both** halves (change #10): `lead` / `media_rep` /
`sales_rep` for display, and `lead_user_id` / `media_rep_id` / `sales_rep_id` for
the form and the bundle. Show the names, edit against the ids — **never infer an
id from a name**, since `User.name` is not unique, and the id is now supplied.

No `PATCH`: editing is delete-and-recreate, and **the name is UNIQUE per org**,
so the delete must succeed before the recreate can. The delete is refused when a
demo references the team. The recreate **does** restore the three role
assignments, because the read supplies their ids.

- [x] **Step 2: Calendar (item 14)** — the compound status, per Task 19 step 4.

- [x] **Step 3: Vendors (item 15)**

All six fields now read back (change #7). **No uniqueness of any kind**: a
re-import creates duplicates silently.

> ~~The delete is refused when an `action_items.external_wait["vendor_id"]`
> names the vendor — a JSON blob no FK can reach, so the guard scans rows with
> non-null `external_wait`.~~
>
> **That was written against a guard that no longer exists, and it is corrected
> here rather than deleted, because a screen built on it would have promised the
> operator a protection the server does not provide.** The guard was written,
> found to be checking `external_wait["vendor_id"]` — **a key no caller ever
> writes**, since the only writer records `vendor_name` — and then **removed
> outright** rather than repaired. `09` §4a records that decision.
>
> `ops.py · delete_vendor` now carries the reasoning in its own docstring:
> nothing in the schema references `vendors.id`, no foreign key and no id-shaped
> column; the sole appearance of a vendor outside its own table is a free-text
> JSON blob holding a **typed name**, not a reference. Deleting a vendor
> therefore cannot orphan anything, and a task's recorded promise keeps reading
> exactly as it did.
>
> **So the delete is unguarded, and correctly so.** Task 20's screen says that
> in as many words and offers no confirmation dialog — a confirmation implies a
> consequence.

- [x] **Step 4: Item 16 — permanently unavailable**

`—`, with the reason and the manual's fallback verbatim (Task 16 step 2). **No
form, no fields, no "coming soon".** The screen exists to say why this cannot be
done here and what to do instead.

- [x] **Step 5: Checkpoint** — items 13–15 reachable and green; item 16 `—`.

---

### Task 21: Import — parse, validate, preview, template

**Files:**
- Create: `src/import/parse.ts`, `validate.ts`, `template.ts`, `src/screens/Import.tsx`
- Test: `src/import/parse.test.ts`, `src/import/validate.test.ts`

**Interfaces:**
- Produces: `parse(file) -> Row[]`, `validate(descriptor, rows) -> Verdict[]`,
  `templateFor(descriptor) -> string`.
- Consumes: descriptors (column order, example row), generated schemas,
  `CONSTRAINTS`.

- [x] **Step 1: Parse**

CSV via `papaparse` and JSON, ten entities; **`settings` is JSON-only**, being
one row rather than a list (§5.5).

**Columns whose name begins with `_` are dropped at parse time** (D21) — that is
what makes a failures file directly re-importable.

- [x] **Step 2: Validate, including the unknown-column check (A7/P9)**

Order matters: check the **column set** against the descriptor first, then
coerce, then Zod. Every generated schema is `.passthrough()`, so an unknown
column would otherwise sail through and write a row with a missing field. An
unknown column is a row-level error naming the column and the expected set.

CSV gives strings; coerce per `control` before parsing, and **empty string is not
zero and not null** — an empty numeric cell means "not provided". Get this wrong
and `default_quantity` collapses to the very default the tri-state exists to
avoid.

- [x] **Step 3: The preview, with per-entity re-import behaviour**

One verdict per row. Apply is gated on **zero validation errors**. The preview
states which re-import behaviour applies (§5.5): skills upsert; staff, programs
and demo teams fail on their unique key; pricing / proposal templates / message
templates / playbooks **create a new version and supersede the current one**;
approval rules and vendors **duplicate silently**.

Say the version-inflation one loudly — a careless re-import silently inflates
version numbers, and nothing refuses it.

- [x] **Step 4: Template download**

Header + a pre-quoted example row from the descriptor. **Template bodies contain
newlines**, which survive CSV only under correct quoting, so the panel
recommends JSON for `proposalTemplates`, `messageTemplates` and `playbooks`, and
the CSV template ships an example that already carries an embedded newline.

- [x] **Step 5: Tests**

CSV quoting with embedded newlines in `body_md`; `default_quantity` tri-state
surviving parse (`""` → absent, `"0"` → 0, `"1"` → 1 — three distinct
outcomes); unknown column rejected; `_error` column ignored; per-row verdicts.

---

### P14 · The templates did not validate against their own validator — four of them

**Found in Task 21 by a round-trip test**, not by review: take each entity's
template, feed it back through `parseFile` + `validateFile`, and assert it comes
out clean. Four failed, each for a different reason, and none of the four would
have been noticed until an operator downloaded a template and had it rejected.

| Template | Why it failed |
|---|---|
| `staff` CSV | `working_days` is `mon\|tue\|wed\|thu\|fri`, and `JSON.parse` of that is not JSON |
| `staff` JSON | same example, carried into JSON as the pipe **string** rather than an array |
| `pricing` JSON | built from `csv.example`, whose columns are rate-card **lines** — so it described a body no route accepts |
| `playbooks` / `approvalRules` / `settings` JSON | no `csv.example` to derive from, so the builder invented one from the field controls and produced a playbook with no programme and an empty entry list |

Three fixes, all in the direction of declaring rather than guessing:

- **The pipe-delimited list is a declared CSV convention.** It was already the
  project's — both descriptors that expose a list field to CSV ship a
  pipe-delimited example — it simply had nowhere to be implemented. A cell that
  opens `[` or `{` and fails to parse is still a genuine JSON error.
- **`csv.linesOf`** names the field a CSV row populates, so `pricing`'s JSON
  template carries the entity shape and its CSV stays line-level. Named rather
  than inferred from the column set.
- **`jsonExample`** on the three JSON-only descriptors, because the honest fix
  for "the builder guessed badly" is a real example, not a cleverer guess.

The round-trip test is the durable part: **the file the console hands an
operator is a file the console accepts**, re-asserted on every run.

### Task 22: Import — apply and the failures file

**Files:**
- Create: `src/import/apply.ts`, `failures.ts`, `src/screens/ImportResult.tsx`
- Test: `src/import/apply.test.ts`, `src/import/failures.test.ts`

- [x] **Step 1: Apply continues past a failure (D21)**

Sequential HTTP, **every row attempted**. Halting at row 12 of 50 leaves a
half-applied file and no knowledge of rows 13–50. **No retries** — D17.

- [x] **Step 2: Per-row outcome**

Applied, or **the server's own refusal message verbatim**. Never a paraphrase.

- [x] **Step 3: The failures file**

Emitted in **the input's own format** — CSV in, CSV out; JSON in, JSON out —
with the original columns intact and an appended `_error` column carrying the
server's message.

- [x] **Step 4: Prove the round trip**

`failures.test.ts`: parse the emitted file and get **exactly the failed rows
back**, `_error` ignored, values byte-identical to the input (embedded newlines
included). That closes the loop — import → fix → re-import → repeat until empty.

- [x] **Step 5: Checkpoint**

> ~~Live, against a throwaway org: import 10 vendors where 3 collide, confirm 7
> applied and the failures file re-imports cleanly after editing.~~
>
> **Vendors cannot collide.** `ops.py · add_vendor` splats the body straight
> into the row and there is no uniqueness of any kind — this plan's own Task 20
> Step 3 says so, and the descriptor's `reimport` reads *"creates duplicates
> silently"*. Ten vendors with three repeats applies **ten**, which demonstrates
> nothing about continue-on-error.
>
> **Done with `staff` instead**, which refuses duplicates on a globally unique
> email *and* refuses an address outside the organisation's domain — two
> different refusals in one file. Eight rows with failures at **3, 5 and 7**,
> deliberately in the middle: 5 applied, 3 refused, all 8 attempted, staff
> count 2 → 7. Then the failures file downloaded, three addresses edited in
> place with the header and `_error` column untouched, dropped straight back
> in: recognised as a failures file, 3 ready, 3 applied, 0 refused, **and no
> failures file offered** — the loop terminates. Staff 7 → 10.

---

### P15 · "No catch-all" does not cost the same for every entity type

**Found in Task 23** by reading `approval_engine` rather than by testing it.
`find_rule` orders by `rank` then `created_at` and returns the **first** rule
whose condition matches; an empty condition matches everything. So a `{}` rule
that is ranked first makes every rule below it dead — checkable — and an entity
type with no `{}` rule at all has requests that reach no rule.

**What happens then is decided by the caller, and the nine `request_approval`
call sites disagree**:

| entity type | call sites | with no matching rule |
|---|---|---|
| `outbound_message` | 4 | falls to `sales_lead` |
| `price_change` | 1 | falls to `sales_lead` |
| `plan_change` | 3 | two fall to `sales_lead`; the plan-version path passes `None` and **activates as "system"** |
| `proposal` | 1 | passes `None` — the proposal is set `APPROVED_INTERNALLY` with nobody asked |
| `invoice` | **0** | nothing in the backend ever requests one, so rules for it are dead configuration |

**Item 9's caption said "a request matching none of them has no approver"**,
which is wrong in both directions at once: too alarming for the seven sites that
name a default, and far too mild for the two that apply the thing unreviewed.
Corrected in `status.ts`, with a `notCaption` case pinning the removed phrase.

**The table is generated, not transcribed** — `dump_openapi.py` AST-walks every
`request_approval` call under `app/` and emits `APPROVAL_NO_RULE` into
`vocabularies.generated.ts`. Nine call sites hand-copied into TypeScript is nine
things that go stale in silence; `gen:check` re-derives them on every build.
Proved by changing `proposals.py`'s `default_approver_role` and watching
`gen:check` fail, then reverting.

### P16 · `POST /orgs` does not apply the domain rule it creates

`admin.py · register_staff` refuses any staff address that does not
`endswith("@" + org.email_domain)`. `organisations.py · create_organisation`
applies **no such test to `admin_email`** — grepped, not inferred. So the
organisation's first administrator is the one account that can legitimately sit
outside the domain, and a go-live domain check that simply listed offenders
would report the operator's own account as a defect.

Task 23's check 6 names the exception where it finds it rather than excluding it
silently: an out-of-domain row belonging to the administrator says which route
created it and which rule that route skips.

### Task 23: The go-live check

**Files:**
- Create: `src/screens/GoLive.tsx`, `src/checklist/golive.ts`
- Test: `src/checklist/golive.test.ts`

**Interfaces:**
- Produces: `runGoLive(reads, session) -> Check[]` — pure, over reads already fetched.

> **Deviation, recorded: the signature takes two arguments, not one.** Check 6
> cannot be answered from the reads at all (P7), and A6's first fallback is the
> `email_domain` that `POST /orgs` handed this tab — session data, which
> `session/handoff.ts` already stashes for exactly this. Passing it in keeps the
> function pure; reading `session.get()` inside it would not.
>
> **Also created, and not in the file list:** `tools/verify_golive_live.ts`.
> `golive.test.ts` proves the derivation against committed fixtures; that tool
> proves it against a **live** organisation seeded with a real gap, by importing
> `runGoLive` itself rather than reimplementing it. See Step 7.

- [x] **Step 1: Skill coverage — the check that justifies the console**

Every `required_skill` across all current playbooks (readable now, via change #3)
diffed against every skill held by an **active** user (one `GET /skills` with no
`user_id` returns the whole org).

**The unmatched list is finding F25, caught at authoring time instead of demo
time** — a task needing a skill nobody holds routes to the phase lead flagged
*"no skill match"*.

**Active-only, and that is not a detail.** `ops.py · delete_skill` defines
coverage as active holders only, with a comment saying two definitions of
"covered" is how the next divergence starts. Match it exactly.

- [x] **Step 2: Program completeness**

Each active program × {current pricing, current proposal template, a playbook
per phase}.

- [x] **Step 3: Message template completeness** — all four `kind × channel`.

- [x] **Step 4: Approval rule ordering**

Per `entity_type`, rules in `rank` order with the first match highlighted, plus a
flag when no catch-all `{}` rule exists. A never-matching high-rank rule quietly
hands approval to the catch-all.

Both `fallback_role` and `auto_approve` are readable (change #9), so the check
covers the whole rule: **flag every `auto_approve` rule explicitly**, since a
rule that approves itself is exactly what an operator wants to see listed before
going live, and name the fallback approver alongside the primary.

- [x] **Step 5: Delivery honesty** — the compound email and calendar statuses.

- [x] **Step 6: Domain check, with the fallback (P7/A6)**

Run against the domain the console can actually know, in the A6 order, and
**name which source was used**. With no source available the check renders `—`
with the reason — not a pass.

- [x] **Step 7: Tests and checkpoint**

Table-driven over fixtures. Must include: a playbook requiring a skill only a
**deactivated** user holds ⇒ **uncovered**; a program missing its pricing; three
of four message templates; an entity type with no catch-all.

**Done — 37 tests in `golive.test.ts`, all four named cases present**, plus the
`pending` / `unreadable` split and a purity pair. Four were watched failing
against a deliberately broken derivation before being believed: the active-only
join (reported `●` for a deactivated holder), the shadowing check, the domain
fallback's inability to be `●`, and phase coverage.

**And driven against a real organisation, which the fixtures cannot do.**
`npx vite-node tools/verify_golive_live.ts -- --base http://127.0.0.1:9010`
creates an org, seeds a deliberately incomplete one, deactivates the sole holder
of `cable-management`, then runs `runGoLive` over live reads and asserts three
things together: the skill reads **uncovered**, a skill an *active* person holds
still reads **covered**, and `GET /skills` **still returns the deactivated
holder's row** — without that last assertion the case is not being exercised at
all, since the whole defect is that the row looks like coverage.

Verified 2026-08-18 against `t23-1787028485` (since deactivated); the screen was
then driven in Chrome in both themes, console clean on a fresh load. Two
legibility defects came out of looking at it rather than testing it: the subject
column broke `power-commissioning` across its hyphen, and the approval row read
`10 when discount_pct_gt → sales_lead` — the rank and the threshold, both
unlabelled, and the threshold's value dropped.

---

### P17 · "the twelve engine-only tables" — the source it cites says fourteen

Found in Task 24, while checking that every verbatim quotation on the reset
screen traces to a file in this repository.

`06_DESIGN.md` §5.7 quotes D6: *"Projects, plans, tasks and **the twelve
engine-only tables** come back only by running the product."*
`04_OPEN_QUESTIONS.md` Q13 also says twelve and enumerates twelve — but names
`03_API_SURFACE.md` §4.2 as its source, and **§4.2 lists fourteen**: Q13 drops
`memory_chunks` and `lead_state_history`. All fourteen are in `WIPE`, checked
against the generated taxonomy rather than by counting the prose.

**Nobody is harmed by the number in a design document. The reset screen is
different**, which is why this was worth chasing: it is the one place in the
console where an operator reads a warning immediately before destroying data,
and a warning that undercounts what it is warning about is the wrong kind of
wrong there.

`Reset.tsx` therefore renders §5.7 **verbatim**, cited, and then corrects it in
the console's own voice — `09` §4a's standing rule for a quotation known to be
off. `04` and `06` are frozen, so this is recorded rather than fixed in them.

### P18 · Programme ids do not survive the reset the bundle exists to undo

Task 24 Step 4 says the bundle carries nine entity types, all faithful, and
lists no exceptions. Two things it does not mention break the loop outright:

1. **`POST /admin/programs` mints a new id** and nothing lets a client choose
   one. A bundle storing `program_id` therefore restores playbooks pointing at
   programmes that no longer exist — and `upsert_playbook` **does not check that
   the programme exists** (the descriptor already says so), so they would be
   stored in silence and no plan would ever fire them.
2. **Pricing and proposal templates take their programme in the URL**, not the
   body, so their write schemas have no field for it at all and a projection
   derived from `generated.ts` cannot carry one.

Both are solved the same way: the bundle carries the programme **code**, under
`_program_code`. `add_program` refuses a duplicate code compared
case-insensitively and stores it uppercased, so it is unique per organisation
and stable across the round trip. `import.ts` resolves it to the id that was
just created, and strips every underscore-prefixed key before sending — pinned
by a test asserting `_program_code` is the only such key in the whole bundle.

**A third, smaller one from the same reading.** `demoTeams` declares
`aliases: { member_ids: "members" }`, and the read returns `[{id, name}]` where
the write wants `["u1", "u2"]`. An alias renames a field; it cannot convert one.
`BUNDLE_TRANSFORMS` does, with exactly one entry, and without it **every demo
team in the bundle is refused on re-import** — watched failing.

### Task 24: Reset and the reseed bundle

**Files:**
- Create: `src/screens/Reset.tsx`, `src/screens/Bundle.tsx`, `src/bundle/export.ts`, `src/bundle/import.ts`
- Test: `src/bundle/roundtrip.test.ts`

> **Two additions, recorded rather than left to the handoff note.**
>
> - **`src/bundle/reset.ts` + `reset.test.ts`.** The reset derivation is pure and
>   is kept out of the screen for the reason `status.ts` and `golive.ts` are:
>   this is the one screen where being wrong destroys data, so what it claims has
>   to be testable without a DOM. 17 tests.
> - **`tools/verify_reset_bundle_live.ts`.** Step 6 asks for a live checkpoint;
>   this is it, importing `buildBundle`, `parseBundle` and the reset derivation
>   themselves so it cannot verify a reimplementation.
>
> **And a property of the endpoint the plan does not mention: the preview needs
> TWO dry runs.** `reset_organisation` returns `counts` for only the tables the
> flags it was called with cover, and computes `blocking_edges` **only** when
> `wipe_catalogue and not wipe_transactional`. One call cannot answer both, so
> the screen makes an all-three call for the counts and a catalogue-only call for
> the edges. Both are `dry_run: true`; neither writes.

- [x] **Step 1: Reset, two steps**

Dry run returns exact per-table counts; apply requires the organisation's own
name typed back. **Three independent flags with their row counts**, not one
button — a rehearsal reset clears transactional data only; a full reseed clears
all three and re-imports the bundle.

- [x] **Step 2: Show `blocking_edges` at preview, because that is where the API puts them**

A catalogue-only reset (`wipe_catalogue` without `wipe_transactional`) would
orphan surviving rows. Per D22/D23 the endpoint returns `blocking_edges` on a
**dry run without refusing**, and 422s on apply. So the preview must render them
— table, column, referenced table and count — with the remedy the server names:
wipe transactional data too, or clear those rows first. **A preview that hides
them turns a stated refusal into a surprise.**

- [x] **Step 3: The three sentences the screen must carry**

- D6, verbatim in substance: *Resetting removes transactional data and, if you
  choose, the catalogue. **Projects, plans, tasks and the twelve engine-only
  tables come back only by running the product** — recording a meeting and
  confirming its review. This console cannot restore them.*
- The **job queue and scheduler keep running**; wiping `jobs` mid-flight is a
  live-system hazard. Idle the backend before applying, or expect a few rows to
  reappear.
- **Staff accounts are never removed**, whichever flags are set — including the
  account performing the reset.

- [x] **Step 4: The bundle — nine entity types, all of them faithful**

Export to one JSON file stamped with `org_id`; **the console refuses a bundle
whose `org_id` does not match the session** (§5.8 — skills round-trip on
`user_id`, so this is a reseed loop, not a cloning tool).

The export screen states, at the point of export:

> Staff accounts are not exported. They are never removed by a reset — the
> account you are signed in as is one of them — so there is nothing to restore.

**Nothing else needs disclaiming.** Changes #9 and #10 closed the two gaps that
made approval rules and demo teams lossy (P4, P5), so **every field the write
accepts is now readable for all nine entity types** and the bundle carries them
all. Export the demo-team **ids**, not the display names.

- [x] **Step 5: Round-trip test**

`roundtrip.test.ts` over fixtures: export → parse → re-import produces the same
rows for **all nine entity types, with no exceptions** — including
`fallback_role` and `auto_approve` on approval rules, and the three role ids on
demo teams. Assert field-by-field equality rather than a shape check, so a field
silently dropping out fails here rather than at a client's reseed.

- [x] **Step 6: Checkpoint**

Live, against a throwaway org: export, reset with all three flags, re-import,
and confirm the checklist returns to exactly where it was — **including** an
`auto_approve` rule that is still auto-approving and a demo team whose three
roles are still assigned. Those two are the point of changes #9 and #10; check
them by hand, not only in the test.

**Done, 2026-08-18, against `t24-1787033081`** (since deactivated), with a real
proposal seeded through `POST /leads` + `POST /proposals` so D22 had something
real to refuse:

| | |
|---|---|
| dry run, all four buckets | WIPE 42 tables · 6 rows · REPLACE 7 · 9 · CONFIG 2 · 3 · **KEEP 4 tables, no counts reported** |
| D22 at preview | **4 blocking edges**, not the one predicted: `demo_team_members.team_id`, `proposals.pricing_table_id`, `proposals.program_id`, `proposals.template_id` |
| D22 at apply | refused verbatim — *"Catalogue reset refused: it would orphan rows that still reference it — … Wipe transactional data too"*; **both programmes still there afterwards** |
| bundle | 9 entity types · 12 rows |
| reset, all three flags | 18 rows removed; programmes, rules, teams and skills gone; **all three staff accounts survived** |
| re-import | **12 restored · 0 refused** |
| change #9 | the restored rule is **still auto-approving**, and kept its fallback approver |
| change #10 | the restored team's three role ids are **all still assigned** |
| P18 | the restored programme has a **new id**, and the playbook and rate card followed it |

**18 removed against 12 restored is the correct arithmetic, not a loss.** The
six extra are `WIPE` rows the bundle deliberately does not carry — the lead, the
proposal and its revision, the lead-state history and two demo-team member rows
— which is precisely what D6's sentence on the screen warns about.

---

### P19 · Markdown in prose reaches the screen as punctuation

Three instances shipped, and **all three were found by looking at a browser, not
by a test**:

| where | what an operator saw |
|---|---|
| `BUCKET_NOTE` (Task 24) | a backticked `users`, on the reset screen, immediately above a destructive control |
| `Staff.tsx` (Task 25) | the same, beneath the account table |
| `skills.quote` (Task 25) | *"the neutral skill `general`"* — `02` §3's **own markdown emphasis**, inside a quotation §9 requires to be verbatim |

The third is the sharpest. Everything in this console is written in markdown —
the plans, the READMEs, the JSDoc — and the habit follows the author's hand into
strings that are rendered as plain text. A quotation that carries the emphasis
of the document it was transcribed **from** is not verbatim either, which is a
different defect wearing the same clothes.

**`src/ui/prose.test.ts` guards the exact half and says so.** It checks prose
that exists as **data** — the two exported reset constants, every descriptor
field, every checklist item — which needs no parsing.

**It deliberately does not scan JSX text**, and the reason is worth keeping:
two attempts did, and both were worse than nothing. A backtick pair in JSX text
is character-for-character identical to a template literal, so telling them
apart needs a real parser; the versions that guessed reported five correct files
as broken, and a first pass at the pattern flagged eight correct captions because
it treated the underscore in `super_admin` as emphasis. **A guard that cries
wolf gets deleted**, and it would take the exact half with it. Screens have no
unit tests by design (D11); the browser pass that ends every task is what covers
them, and is what caught all three of these.

### Task 25: Build, mount, verify

- [x] **Step 1: Build**

`cd Dashboard && npm run build`. `prebuild` runs `gen:check` — if the backend has
moved since Task 11, this fails here, which is the whole point.

- [x] **Step 2: Confirm the mount serves it**

> **Measured 2026-08-18, and P10/A8 hold exactly.** The warning is gone and the
> bundle is served; every path-style deep link 404s and every hash one resolves.
>
> | URL | |
> |---|---|
> | `/dashboard/` · `/dashboard/index.html` · `/dashboard/assets/…` | **200** |
> | `/dashboard/checklist` · `/dashboard/go-live` · `/dashboard/reset` · `/dashboard/bundle` | **404** — correct, and the reason A8 chose hash routing |
> | `/dashboard/#/go-live` **in a fresh tab with no session** | resolves: the hash survives, the app boots, and the route renders its own no-session state rather than 404ing |
>
> The last row is the case hash routing exists for and had never been driven
> before: a path router would have worked while clicking through and broken on
> every refresh, bookmark and shared link.

Restart the backend — the mount is evaluated at import time, so a running
process will not pick up a newly built bundle — and confirm the change #8
warning is **gone** and `http://127.0.0.1:8000/dashboard/` serves the console.
`base: "/dashboard/"` in `vite.config.ts` is what makes the assets resolve.

Then check a deep link. **`/dashboard/#/checklist` must work and
`/dashboard/checklist` must 404** — that is correct, not a regression: the mount
does no SPA fallback (**P10**) and the console uses hash routing (**A8**) so it
never needs one. If a path-style deep link ever starts working, someone has
added a fallback route, which is an eleventh backend change.

- [x] **Step 3: Re-run every guard**

```bash
python scripts/check_docs_in_sync.py          # must still exit 0
python -m pytest tests/test_genericity.py -q  # 8 passed
python scripts/check_hardcoded_strings.py     # 2 pre-existing Java findings
python -m pytest -q                           # record collected AND passing, with local time
cd Dashboard && npm test                      # the four Vitest suites
```

**Phase 2 adds no `APIRoute`**, so `check_docs_in_sync.py`'s counts must not
move: 55 tables, 755 columns, **151 routes**. If that number changed, something
landed under `app/` that should not have.

**Neither genericity guard scans `Dashboard/`** (D19, verified: one scans
Android Java, the other `app/**/*.py`). If either reacts to this work, a file is
in the wrong directory — **fix the location, do not add an exclusion.**

**`check_hardcoded_strings.py` will exit 1** with the same two cosmetic findings
at `LoginFragment.java:101` and `SplashFragment.java:48` it produced at the
pre-work baseline. That is the expected state. **"All four guards are green" is
false and must not be written** — the honest claim is *the guards this work
could affect are green, and the third fails exactly as it did before.*

- [x] **Step 4: Commit `dist/`**

`Dashboard/dist/` is deliberately **not** in `.gitignore` (D10) — the bundle is
committed so the backend serves it from a plain checkout. `.gitignore` already
says so; do not "tidy" it.

- [x] **Step 5: Update `08_PROGRESS_AND_HANDOFF.md`**

> **And the console was driven as an operator, not as a build check** — a fresh
> organisation taken through the rail end to end:
>
> | | |
> |---|---|
> | rail, before | ● 4 · ◐ 2 · ○ 9 · — 1 |
> | staff created through the form | wrong-domain address **refused by the server, verbatim** (*"Staff email must use your organisation's domain @…"*), then created; item 2 ○ → ◐, naming the account with no department |
> | import applied | 5-row CSV, one row naming `bogus_kind` → **apply gated**: *"Apply is gated on zero problems, not on most of them — 1 row would have to be fixed first"*, the row flagged *"Must be one of intro, follow_up (admin.py · add_message_template)"*. Fixed, then **4 applied · 0 refused**; item 7 ○ → ● |
> | delete refused | the programme delete, with a proposal against it: the server's message verbatim, and the console contradicting its last sentence — **P13, working live** |
> | reset previewed | four buckets, per-flag counts, **three blocking edges** from the real proposal, apply disabled with the reason |
> | rail, after | ● 5 · ◐ 3 · ○ 7 · — 1 |
>
> **Two form fields remain unexercised and always will be**: `/#/sign-in` and
> the hand-off's step 3 both take a password, which this assistant does not type.
> The org-admin token was minted the way `tools/capture_fixtures.mjs` mints one
> and written into `sessionStorage`. Everything either side of those two fields
> is driven.

Tick Tasks 11–25 and record the measured figures **with the local time of the
pytest run** (§4 item 8). No escalations are outstanding — P4 and P5 were fixed
as changes #9 and #10 before Task 11 began.

---

## Phase 2 test strategy

**Vitest only. No E2E, no component tests** (D11).

Four suites — the three §10 named, plus the one P1 and P2 made necessary:

1. **Generation** (Task 11) — every component schema exported; every constraint
   in `openapi.json` survives into `generated.ts` **or** the lift; the
   vocabularies are non-empty and exclude `super_admin`; `gen:check` fails on a
   stale artefact. *This suite exists because the generator silently drops 16 of
   the 28 constraints this console needs.*
2. **Drift** (Task 15) — every descriptor field exists in its generated schema;
   every descriptor resolves to a schema; every `schema`-enforced rule is really
   in `generated.ts`; every read shape parses a captured live fixture.
3. **Import** (Tasks 21–22) — CSV quoting with embedded newlines in `body_md`;
   the `default_quantity` tri-state surviving a round trip without becoming `1`;
   unknown columns rejected despite `.passthrough()`; per-row verdicts; the
   re-import behaviours of §5.5; apply continuing past a failure; the failures
   file round-tripping exactly, `_error` ignored.
4. **Status derivation** (Tasks 16, 23, 24) — pure functions, table-driven:
   fixture payloads in, expected status out. Must include the compound email case
   (credentials stored + `EMAIL_MODE=dry_run` → `◐`, **never** `●`), item 10's
   untouched-defaults case, a drifted read yielding `—` rather than `○`, and the
   bundle round-trip losing exactly the five unreadable fields.

Screens themselves are verified by using them against a live backend, which the
reset endpoint makes cheap to repeat.

---

## Self-review against the spec

| `06_DESIGN.md` section | Covered by | Amended by |
|---|---|---|
| §2 Stack | Task 11 | zod pinned to 3.x; generator pinned exactly |
| §3.1 Generated boundary | Tasks 11, 15 | **A1** — 11 of 15 reads are untyped and hand-shaped |
| §3.2 Drift is a build error | Tasks 11, 15 | **A3** — the constraint lift is a fourth mechanism |
| §3.3 Enforcement | Task 15 | **A2** — three values, not two; **A4** — vocabularies generated |
| §4.1 client, no retry | Task 13 | drift banner added |
| §4.2 chained hand-off | Task 14 | **P8** — staff temp passwords too, and they are recoverable |
| §5.1–5.2 rail and status | Task 16 | **A5** — item 1 reads `/auth/me`, not `/orgs` |
| §5.3–5.4 item screens and warnings | Tasks 17–20 | **P5** — demo-team recreate cannot restore three ids |
| §5.5 import, partial applies | Tasks 21–22 | **A7** — unknown columns rejected despite `.passthrough()` |
| §5.6 go-live check | Task 23 | **A6** — the domain check's fallback chain |
| §5.7 reset | Tasks 6, 24 | `blocking_edges` rendered at preview (D22/D23) |
| §5.8 bundle | Task 24 | **P4/P5 fixed as changes #9/#10** — all nine entity types round-trip |
| §6 honesty model | Tasks 16, 20 | a drifted read is `—`, never `○` |
| §7 backend changes | Phase 1, done | — |
| §8 docs guard · §8.1 dist/ invariant | Task 25 | — |
| §9 visual design | Task 12 | the constraint caption gains a third form |
| §10 testing | Phase 1 pytest + four Vitest suites | a fourth suite (generation) |
| §11 READMEs | `08`, `09` at every checkpoint | — |
| §12 known limits | Tasks 14, 22 | P4 and P5 were limits; both are now fixed |

**Gap check:** every section maps to a task, and every amendment maps to the
finding that forced it.

**The two escalations are closed.** P4 (`fallback_role`, `auto_approve`
unreadable) and P5 (demo-team role ids unreadable) went back to the owner, who
**reopened the change list for exactly those two and re-closed it at ten**
(D24, Tasks 10a–10c). Four warnings and two `notReadable` lists came out of this
plan as a result, and Task 24's round-trip test strengthened from *seven faithful
entity types plus two lossy ones* to **nine, with no exceptions**.

**Nothing else is outstanding.** Phase 2 needs no further backend work: Task 11
starts against a re-frozen API.
