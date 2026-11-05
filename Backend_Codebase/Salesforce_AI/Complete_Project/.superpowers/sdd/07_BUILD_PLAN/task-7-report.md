# Task 7 report — guarded deletes in `ops.py` (change #6, part 1 of 2)

## What changed

`app/api/ops.py`:

- **Imports**: added `func` (from `sqlalchemy`), `ConflictError` (from
  `app.core.exceptions`), `ActionItem` (from `app.models.action_item`), and
  `audit_service` (from `app.services`). `NotFoundError` and
  `PermissionDeniedError` were already imported. `UserSkill` was already
  imported further down the file (before the skills section) and is reused
  as-is.
- **`DELETE /skills?user_id=&skill=`** — added immediately after `list_skills`.
  Natural-key delete (matches `POST /skills`'s upsert key, since `GET /skills`
  returns no row id). Role-gated with the same `("org_admin", "sales_lead",
  "operations_lead")` tuple `POST /skills` hard-codes, with the brief's comment
  kept verbatim explaining why it is *not* centralised (Part F #11, deferred —
  the backend change list is closed at eight). 404 if the pair doesn't exist.
  409 if it is the last holder of that skill and there is open/in_progress/
  pending_review work needing it. Calls `audit_service.record(..., action="ops.skill_deleted")`.
- **`DELETE /playbooks/{playbook_id}`** — added after `list_playbooks`, before
  the suggestions section. Gated on `require_permission("manage_programs")`.
  No reference guard (nothing points at a playbook). Deleting the current
  version promotes the highest-`version` predecessor back to `is_current` —
  the API's only un-supersede path. Calls `audit_service.record(...,
  action="ops.playbook_deleted")`.
- **`DELETE /vendors/{vendor_id}`** — added after `list_vendors`. Gated on
  `require_permission("manage_settings")`. Scans `action_items` with
  non-null `external_wait` (no FK exists to join on) and refuses with 409 if
  any blob references the vendor. Calls `audit_service.record(..., action="ops.vendor_deleted")`.
  **One deliberate deviation from the brief's verbatim code, explained below.**

`tests/test_dashboard_deletes_ops.py` — new file, 7 tests, all from the brief,
with two setup calls corrected (see next section). All assertions are
unchanged from the brief.

`Dashboard/READMEs/09_BACKEND_CHANGES.md` — change #6's row updated to show
part 1/2 done (T7 ✅ 7/7, T8 still ⬜); one change-log line appended
documenting T7.

## The two setup-call corrections (as required by the brief's own warning)

Ran the verification command the brief specified before writing tests:

```
python -c "import app.main as m; from fastapi.routing import APIRoute; print([...])"
```

Both flagged routes were wrong, in different ways:

### 1. `POST /api/v1/action-items` has no `required_skill` field

`app/api/action_items.py`'s `CreateItemRequest` has no `required_skill`
field, and `create_action_item` never sets one on the created row — it isn't
silently dropped by a stray default, it simply isn't wired at all. FastAPI/
pydantic ignore unknown JSON keys by default, so the brief's
`json={..., "required_skill": "wiring"}` would have posted successfully but
produced a task with `required_skill=None`, and the guard in `delete_skill`
would never have found it — the test would have failed to reach 409, not
because the implementation is wrong, but because the fixture never existed.

No route anywhere in the app lets a caller set `required_skill` directly
(confirmed by grepping every `required_skill` write site — they're all
inside `planner_engine.py`, `inbound_engine.py`, and `workflow.py`'s
task-split/replan paths, none of which are simple, single-call test
fixtures). This exact gap already has a precedent fix in this codebase:
`tests/test_assignment_skills.py::test_a_seeded_skill_produces_a_real_match_not_no_skill_match`
builds the `ActionItem` directly through `SessionLocal` for the same reason.
I followed that precedent rather than reporting BLOCKED, since it is an
established, already-in-use technique in this exact test suite for this
exact gap — not an invented route and not a weakened assertion. The 409 and
the `"wiring" in resp.text` assertion are both unchanged.

### 2. There is no `/tasks/{id}/external-wait` route, and the real route's body shape differs

The real route is `POST /tasks/{task_id}/vendor-promise`
(`app/api/workflow.py:404`, `VendorPromiseRequest`), which takes
`vendor_name: str`, `promised_date: datetime`, and optional
`chase_contact_user_id`. There is no `vendor_id` field on that request model,
and — this is the part worth flagging — **the handler never touches the
`Vendor` table at all**. It writes:

```python
task.external_wait = {
    "vendor_name": body.vendor_name,
    "promised_date": body.promised_date.isoformat(),
    "chase_contact": body.chase_contact_user_id or ctx.user_id,
}
```

`action_item.py`'s own docstring comment on the column says the blob looks
like `{"vendor_id": ..., "promised_date": ..., "chase_contact": ...}`, but no
code anywhere writes `vendor_id` into it — that key is aspirational, not
real. `app/engines/sync_engine.py:1635` already knows this and defensively
reads `wait.get("vendor_name") or wait.get("vendor_id")`.

**This meant the brief's verbatim `delete_vendor` guard — which only checks
`external_wait.get("vendor_id") == vendor_id` — would never fire against any
data the real API can actually produce.** Adjusting only the test's setup
call (to hit `vendor-promise` with `vendor_name`) without touching the
implementation would have made `test_vendor_delete_refuses_when_a_task_waits_on_it`
fail — not because the test was wrong, but because the shipped guard would be
dead code against the only writer that exists. I judged this in-scope for
Task 7 itself (it's still the vendor-delete route's own body, not a new
route, no new column/migration, nothing added outside `ops.py`) and changed
the guard to match on **either** key:

```python
blockers = [
    t for t in waiting
    if (t.external_wait or {}).get("vendor_id") == vendor_id
    or (t.external_wait or {}).get("vendor_name") == row.name
]
```

`vendor_id` is kept in the check (harmless, and future-proofs it if a writer
ever starts producing that key, matching `sync_engine.py`'s existing
defensive pattern); `vendor_name == row.name` is what makes the guard
actually reachable today. Documented inline in the route's docstring. No
test assertion changed — the test still asserts 409 and the substring check.

## Exact test command and output

```
$ python -m pytest tests/test_dashboard_deletes_ops.py -v
============================= test session starts =============================
collected 7 items

tests/test_dashboard_deletes_ops.py::test_skill_delete_uses_the_natural_key PASSED [ 14%]
tests/test_dashboard_deletes_ops.py::test_skill_delete_refuses_when_open_work_needs_it PASSED [ 28%]
tests/test_dashboard_deletes_ops.py::test_missing_skill_is_a_404 PASSED  [ 42%]
tests/test_dashboard_deletes_ops.py::test_playbook_delete_promotes_the_previous_version PASSED [ 57%]
tests/test_dashboard_deletes_ops.py::test_vendor_delete_refuses_when_a_task_waits_on_it PASSED [ 71%]
tests/test_dashboard_deletes_ops.py::test_unreferenced_vendor_deletes PASSED [ 85%]
tests/test_dashboard_deletes_ops.py::test_deletes_are_audited PASSED     [100%]
============================== 7 passed in 3.17s ==============================
```

Full-suite checkpoint (Step 7):

```
$ python -m pytest -q
........................................................................ [ 28%]
........................................................................ [ 56%]
........................................................................ [ 85%]
......................................                                   [100%]
254 passed in 25.77s
```

254 = the 247 baseline stated in the task instructions + 7 new. 0 failures —
this run landed inside the `test_what_is_late.py` window where the
clock-dependent tests pass (documented as time-of-day-sensitive and out of
scope; not touched).

Guard scripts (context only, not part of Step 6/7, run to confirm the
change-log claims in `09_BACKEND_CHANGES.md` are accurate):

- `python scripts/check_hardcoded_strings.py` — still `FAIL — 2 finding(s)`,
  same two pre-existing cosmetic Java findings (`LoginFragment.java:101`,
  `SplashFragment.java:48`), unrelated to this change.
- `python scripts/check_docs_in_sync.py` — still fails as expected: route
  count is now 146 (was 143 before this task, +3 for the three new DELETE
  routes); resync is Task 10, out of scope here.

## Concerns / notes for whoever does Task 8 or the Task 10 resync

1. **The `vendor_id`-in-`external_wait` idea is dead code in the live system
   today.** Nothing writes it. If Task 8 (the 5 admin.py deletes) or any
   later change adds a real caller that sets `vendor_id`, the guard already
   handles it for free; if not, it's inert but harmless. Worth flagging to
   whoever eventually revisits `VendorPromiseRequest` — matching a vendor by
   free-text name rather than id is itself a small latent correctness gap
   (two vendors with the same name, or a renamed vendor, would both be
   invisible to this guard), but fixing that is a `workflow.py` change and
   is out of scope for the closed eight.
2. Change #6's row in `09_BACKEND_CHANGES.md` is marked part 1/2 done (not a
   full ✅) since T8 (5 more DELETE routes in `admin.py`) hasn't landed —
   the guard-script figures (146 routes, etc.) reflect only T7's 3 routes.
3. No files touched outside `app/api/ops.py`, `tests/test_dashboard_deletes_ops.py`,
   and `Dashboard/READMEs/09_BACKEND_CHANGES.md`. No column/migration added.
   `app/core/reset_taxonomy.py` and `scripts/reset_for_datacentre_demo.py`
   untouched.
