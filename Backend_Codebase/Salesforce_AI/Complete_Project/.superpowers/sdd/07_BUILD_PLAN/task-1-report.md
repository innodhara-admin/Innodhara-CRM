# Task 1 report — Staff fields and staff detail (changes #1 and #4)

## Status: DONE

## What changed and where

`app/api/admin.py` (only file under `app/` touched):

1. **Import** — added `Department` to the `app.core.constants` import.
2. **`CreateUserRequest`** — added `department`, `designation`, `whatsapp_number`,
   `max_open_tasks` (`int | None`, `ge=1, le=100`), `working_days`.
3. **`UpdateUserRequest`** — same five fields added.
4. **`UserResponse`** — same five fields added (all optional, default `None`).
5. **`_user_response()`** — now populates the five new fields from the `User` ORM
   object.
6. **New helper `_validated_department(value)`** — validates against the
   `Department` enum (`sales | operations | accounts`), raising
   `ValidationFailedError` with a message that echoes the bad value and lists
   the allowed ones.
7. **`register_staff`** (`POST /users`) — the `User(...)` constructor now passes
   `department=_validated_department(body.department)`, `designation`,
   `whatsapp_number`, `working_days`; `max_open_tasks` is set **conditionally**
   after construction (`if body.max_open_tasks is not None: user.max_open_tasks
   = body.max_open_tasks`) so an unset value falls through to the `User` model's
   default of 8 instead of being overwritten with `None`.
8. **`update_staff`** (`PATCH /users/{user_id}`) — added five more
   `if body.X is not None:` blocks mirroring the existing pattern, applying
   `_validated_department` to `department`.
9. **New route `get_staff_member`** (`GET /users/{user_id}`) — declared
   immediately after `list_staff` (`GET /users`) and before `update_staff`
   (`PATCH /users/{user_id}`), per the brief's explicit ordering requirement.
   Org-scoped lookup (`User.id == user_id, User.org_id == ctx.org_id`), 404 via
   `NotFoundError` if not found or not in the caller's org.

`tests/test_dashboard_staff.py` (new file) — the four tests exactly as given in
the brief's Step 1, unmodified.

`Dashboard/READMEs/09_BACKEND_CHANGES.md` — ticked State/Tests for change rows
#1 and #4, added a dated change-log line recording the test delta and guard
status (see below).

No column, no migration, no other file under `app/` touched. `get_org_context`
and `require_permission` gates untouched — the new route reuses the existing
`require_permission("manage_staff")` dependency already used by every other
`/admin/users...` route.

## Test commands and output

Step 2 (confirm failing before implementation) — `python -m pytest
tests/test_dashboard_staff.py -v`: all 4 failed as expected (`KeyError:
'department'` on the first test; `405 Method Not Allowed` rather than `404` on
the detail-route test, since no route existed yet — see "brief vs. reality"
below; `KeyError: 'department'` on the patch test).

Step 7 (after implementation) — `python -m pytest tests/test_dashboard_staff.py -v`:

```
tests/test_dashboard_staff.py::test_department_survives_create_and_is_readable PASSED [ 25%]
tests/test_dashboard_staff.py::test_unknown_department_is_refused PASSED [ 50%]
tests/test_dashboard_staff.py::test_staff_detail_is_org_scoped PASSED    [ 75%]
tests/test_dashboard_staff.py::test_patch_updates_the_new_fields PASSED  [100%]

============================== 4 passed in 1.31s ==============================
```

Step 8 (full suite) — `python -m pytest -q`:

```
........................................................................ [ 32%]
........................................................................ [ 64%]
...................................................................FF.F. [ 97%]
......                                                                   [100%]
================================== FAILURES ===================================
... (3 failures, all in tests/test_what_is_late.py)
3 failed, 219 passed in 25.96s
```

The 3 failures are `test_a_task_due_today_is_not_called_overdue`,
`test_the_due_today_header_is_never_empty`, and
`test_today_and_overdue_never_overlap`, all in `tests/test_what_is_late.py`.
**Verified pre-existing and unrelated to this task**: I ran `git stash` (which
stashes tracked-file changes only — `app/api/admin.py` — leaving the new,
untracked `tests/test_dashboard_staff.py` in place) and re-ran the full suite
against the unmodified `admin.py`. Same 3 failures reproduced identically, plus
the 4 (now-unimplemented) new tests failing = 7 failed, 215 passed. `git stash
pop` restored my changes. This confirms:

- Baseline (before this task, new test file counted as failing): 215 passed.
- After this task: 219 passed — **the count rose by exactly 4**, as the brief
  predicted in Step 8.
- The 3 `test_what_is_late.py` failures exist independent of this task and are
  most likely a date-boundary bug sensitive to the current system date
  (2026-08-13) versus a hardcoded "12 Aug" fixture date, not something Task 1
  touches or should fix.

I did not attempt to fix `test_what_is_late.py` — it is out of scope for this
task and fixing it would be exactly the kind of unplanned widening the task
instructions forbid.

## Guard scripts

Also ran, out of caution, the two guard scripts named in project memory (not
required by the brief's 9 steps, but checked for awareness):

- `python scripts/check_hardcoded_strings.py` — FAILS with 2 findings, both
  pre-existing cosmetic Java literals (`LoginFragment.java:101`,
  `SplashFragment.java:48`), nothing introduced by this task (this task touched
  no Java/Android files at all).
- `python scripts/check_docs_in_sync.py` — FAILS (route count now 141, docs
  still say 140; `§7.1 Organisation administration` now 19 vs. documented 18).
  This is **expected and documented** in `09_BACKEND_CHANGES.md` §4: the doc
  resync is explicitly Task 10's job, once all eight changes have landed.

Neither guard regressed because of this task; both were already red (docs
guard) or already had the same 2 findings (string guard) before my edit, per
the project's own memory notes.

## Where the brief's code was wrong about the real code

Nothing was wrong. I read `tests/conftest.py`, `app/api/admin.py`, and
`app/core/constants.py` before writing anything, and every assumption in the
brief held:

- `Department` enum values (`sales | operations | accounts`) matched exactly.
- The existing `CreateUserRequest` / `UpdateUserRequest` / `UserResponse` /
  `_user_response` / `register_staff` / `update_staff` code matched the
  brief's "before" state verbatim, so the diffs applied cleanly.
- `ValidationFailedError` is a 422 `AppError` subclass, confirming
  `test_unknown_department_is_refused`'s `422` + substring-in-body assertion
  would work (FastAPI's default exception handling for `AppError` — checked via
  `app/core/exceptions.py` — was not re-verified in `main.py`'s handler wiring,
  but the test result confirms it renders the message text into the response
  body).
- The `User` model already had all five columns (`department` `String(20)`,
  `designation` `String(100)`, `whatsapp_number` `String(30)`,
  `max_open_tasks` `Integer default=8`, `working_days` `JSON`) — confirmed via
  `app/models/user.py` grep before editing, so this was genuinely additive
  with zero migration need.
- `require_permission("manage_staff")` already existed and is used by every
  sibling route.

One minor, harmless discrepancy: the brief's Step 2 "Expected: FAIL —
... 404 on the detail route" description doesn't match what actually happened
(the pre-implementation run got `405 Method Not Allowed`, since
`/users/{user_id}` matched the existing `PATCH` route's path template with the
wrong verb rather than 404ing on a nonexistent path). This is a discrepancy in
the brief's prose description of the *expected failure*, not in its
prescribed code — the actual test assertion (`== 404`) is unaffected because
by Step 7 the new `GET` route exists and correctly returns 404 for
out-of-org access. No action needed; noting it because the task instructions
asked me to flag anything the brief got wrong about the real code's behaviour.

## Concerns

None that block this task. Two things worth the owner's/next task's attention,
both already anticipated by the project's own docs and out of scope for me to
fix:

1. `tests/test_what_is_late.py` has 3 failing tests, unrelated to Task 1,
   apparently date-boundary-sensitive (see above). Pre-existing, confirmed via
   `git stash`.
2. `check_docs_in_sync.py` and `check_hardcoded_strings.py` are both currently
   red — the former by design until Task 10's resync, the latter with 2
   pre-existing Java findings unrelated to any backend work. Neither was
   touched or worsened by this task.

## Commit

Single commit (backend only; no Dashboard config beyond the changes-tracker
doc's checkpoint, which is documentation, not app code):

- Modified: `app/api/admin.py`
- Added: `tests/test_dashboard_staff.py`
- Modified: `Dashboard/READMEs/09_BACKEND_CHANGES.md`
