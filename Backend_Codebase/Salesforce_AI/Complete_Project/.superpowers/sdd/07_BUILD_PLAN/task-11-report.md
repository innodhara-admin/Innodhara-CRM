# Task 11 report — four owner-directed corrections, closing out a completed backend phase

Branch `feat/setup-console-phase1`, prior HEAD `65ff8f0`. All four items are
amendments to change #6 or text-only corrections — **none is a ninth backend
change**; the eight-change list in `Dashboard/READMEs/09_BACKEND_CHANGES.md`
stays closed.

## 1 · Skill-delete guard now counts only ACTIVE holders

`delete_skill` in `app/api/ops.py`: the `others` coverage query now
`.join(User, User.id == UserSkill.user_id)` and filters `User.is_active.is_(True)`,
so a deactivated user's leftover `UserSkill` row no longer counts as coverage.
Comment added explaining why (a deactivated user cannot service an open task)
and pointing at `06_DESIGN.md` §5.6's go-live skill-coverage check, which is
also active-only — "two definitions of covered is how the next divergence
starts."

New test `test_skill_delete_ignores_a_deactivated_holder` in
`tests/test_dashboard_deletes_ops.py`: skill held by the target user and one
deactivated user (created via `POST /api/v1/admin/users`, deactivated via
`PATCH /api/v1/admin/users/{id}` `{"is_active": false}`), plus an open task
requiring the skill — asserts 409. All prior skill-delete tests
(`test_skill_delete_uses_the_natural_key`,
`test_skill_delete_refuses_when_open_work_needs_it`,
`test_missing_skill_is_a_404`) kept passing unmodified.

## 2 · Vendor-delete guard removed entirely

`delete_vendor` in `app/api/ops.py`: removed the `waiting`/`blockers` scan and
its `ConflictError`. Verified before removing: no column anywhere in the
schema references `vendors.id` (no FK, no id-shaped column), and
`VendorPromiseRequest.vendor_name` (`app/api/workflow.py`) is free text, never
validated against the vendors table. The route, its `manage_settings` gate,
its `audit_service.record` call, and its `{"deleted": True}` response are all
unchanged. Docstring replaced with the plain fact: nothing references a
vendor, so removal cannot orphan; the vendor list is a catalogue, and a
recorded promise stores a typed name independent of it.

`test_vendor_delete_refuses_when_a_task_waits_on_it` replaced with
`test_vendor_delete_succeeds_even_when_a_task_names_it`: asserts 200, the
vendor list is empty afterward, and the task's `external_wait.vendor_name`
text survives (read directly via `SessionLocal`).

The other seven guarded deletes (`delete_playbook`, `delete_approval_rule`,
and the five in `app/api/admin.py`) were not touched.

## 3 · Two lying comments corrected — text only, no behaviour change

- `scripts/reset_for_datacentre_demo.py`: the `WIPE` header's false
  "ordered child-before-parent" claim replaced with the true fact (5 edges
  have the parent before the child: `stakeholders`→`projects`;
  `followups`/`demos`/`memory_chunks`/`client_intelligence`→`leads`), why it
  has never bitten (`PRAGMA foreign_keys=OFF`), and a pointer to
  `app/core/reset_taxonomy.py` as the correct, topologically-sorted,
  test-guarded source for any future touch of this script. The `WIPE` list
  and its order are unchanged; `app/core/reset_taxonomy.py` was not touched.
- `app/models/action_item.py`: the `external_wait` docstring corrected from
  the never-written `{"vendor_id", "promised_date", "chase_contact"}` shape
  to what every caller (`record_vendor_promise`, `app/api/workflow.py`)
  actually writes: `{"vendor_name", "promised_date", "chase_contact"}`, with
  a note that `vendor_name` is free text and not a reference to the
  `vendors` table. Column unchanged.

## 4 · Re-freeze

`Dashboard/READMEs/09_BACKEND_CHANGES.md` updated:
- Banner: records the brief reopen-for-Task-11 and re-freeze, states plainly
  that all eight changes are complete and the list stays closed at eight.
- §1 amendments table: two new rows recording the skill-guard and
  vendor-guard amendments to change #6.
- §1 change table: change #6's Task/Tests columns updated to mention T11 and
  the new 8/8 test count.
- §4a: the reset-script defect write-up marked CORRECTED (Task 11), and a new
  entry added for the `action_item.py` docstring defect, also CORRECTED.
- §5 change log: one new dated row for Task 11 covering all four corrections,
  the test file diff, and the guard results.

## Verification

```
python -m pytest -q                          → 266 passed, 0 failed
python scripts/check_docs_in_sync.py         → exit 0, "OK - the three documents agree with the code"
python -m pytest tests/test_genericity.py -q → 8 passed
```

Route count confirmed still **151** (`check_docs_in_sync.py`'s own count line)
— this task removed a guard clause inside an existing route, not a route.

## Files touched

- `app/api/ops.py` (skill-delete guard fix; vendor-delete guard removal)
- `tests/test_dashboard_deletes_ops.py` (1 test replaced, 1 test added)
- `scripts/reset_for_datacentre_demo.py` (comment only)
- `app/models/action_item.py` (docstring only)
- `Dashboard/READMEs/09_BACKEND_CHANGES.md` (change log + re-freeze)

No other files touched. `app/core/reset_taxonomy.py` was not modified, per
constraint.
