### Task 1: Staff fields and staff detail *(changes #1 and #4)*

**Files:**
- Modify: `app/api/admin.py` — `CreateUserRequest`, `UpdateUserRequest`, `UserResponse`, `_user_response`, `register_staff`, `update_staff`; add `get_staff_member`
- Test: `tests/test_dashboard_staff.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /api/v1/admin/users/{user_id}` → `UserResponse`. `UserResponse` gains `department: str | None`, `designation: str | None`, `whatsapp_number: str | None`, `max_open_tasks: int`, `working_days: list[str] | None`, `require_action_item_review: bool | None`.

- [ ] **Step 1: Write the failing test**

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

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_dashboard_staff.py -v`
Expected: FAIL — `KeyError: 'department'` on the first test, 404 on the detail route.

- [ ] **Step 3: Widen the request and response models**

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

- [ ] **Step 4: Set the fields on create**

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

- [ ] **Step 5: Apply the fields on update**

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

- [ ] **Step 6: Add the staff detail route**

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

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `python -m pytest tests/test_dashboard_staff.py -v`
Expected: 4 passed.

- [ ] **Step 8: Confirm nothing else broke**

Run: `python -m pytest -q`
Expected: the full suite passes; the count rises by 4.

- [ ] **Step 9: Checkpoint**

Both commands above green. Record the new total in `09_BACKEND_CHANGES.md`
against changes #1 and #4.

---

