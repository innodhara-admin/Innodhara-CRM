# Task 4 report — `GET /vendors` (change #7)

## What changed

- **`app/api/ops.py`** — modified `list_vendors`, the existing `GET /vendors` route.
  The return statement was widened to include three new fields from the
  `Vendor` model:

  Before:
  ```python
  return [
      {"id": v.id, "name": v.name, "category": v.category, "notes": v.notes}
      for v in rows
  ]
  ```

  After:
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

  No imports were added, no database changes, no migration. The route signature
  and gating (org-scoped via `Depends(get_org_context)`, readable by any org member)
  remain unchanged.

- **`tests/test_dashboard_reads.py`** — appended 1 test (4th test in the file):
  - `test_vendor_contact_details_are_readable` — posts a vendor with contact
    details, reads vendors, finds the created one, verifies `contact_name`,
    `phone`, and `email` round-trip exactly. Exact test from the brief.

- **`Dashboard/READMEs/09_BACKEND_CHANGES.md`** — change #7's row will be ticked
  to ✅/✅ under State/Tests (Guards green left ⬜, unchanged — sync guard and
  hardcoded-string guard are Task 10's job per the doc's §4 convention); a
  dated change-log line added under §5.

## Exact test commands and output

Step 2 (confirm failing before the change):
```
python -m pytest tests/test_dashboard_reads.py::test_vendor_contact_details_are_readable -v
```
Result: FAILED with `KeyError: 'contact_name'` — the vendor record was created
successfully, but the GET /vendors response did not include the three contact
fields. Expected failure, as described in the brief.

Step 4 (after widening the response):
```
python -m pytest tests/test_dashboard_reads.py -v
```
```
tests/test_dashboard_reads.py::test_playbooks_can_be_read_back PASSED    [ 25%]
tests/test_dashboard_reads.py::test_playbooks_current_only_hides_superseded PASSED [ 50%]
tests/test_dashboard_reads.py::test_playbooks_are_org_scoped PASSED      [ 75%]
tests/test_dashboard_reads.py::test_vendor_contact_details_are_readable PASSED [100%]

============================== 4 passed in 1.24s ==============================
```

Step 5 (full suite checkpoint):
```
python -m pytest -q
```
```
........................................................................ [ 31%]
........................................................................ [ 63%]
........................................................................ [ 94%]
.FF.F.......                                                             [100%]
3 failed, 225 passed in 21.93s
```

228 collected total (225 passed + 3 failed). This is exactly the pre-existing
baseline (224 passed / 3 failed / 227 collected, per the context provided) plus
this task's 1 new passing test (224→225 passed, 227→228 collected, same 3
pre-existing `test_what_is_late.py` failures — unrelated timezone/date-boundary
assumptions on the test side, not touched by this change).

## Anything in the brief that was wrong about the real code

Nothing. The brief accurately described:
- The existing `list_vendors` function and its current return structure.
- The `Vendor` model fields (`contact_name`, `phone`, `email`) that were already
  stored in the database but not returned in the GET response.
- The exact return statement to use (verbatim from the brief).
- The test to append (verbatim from the brief, with no adjustments needed).

## Concerns

None. This is a pure read-path widening on an existing route serving an existing
model, with no new column, no migration, no permission change, and no validation
changes. The change only adds fields to the response dict; no logic changes.
The three pre-existing test failures in `tests/test_what_is_late.py` are
unrelated and were present before this task (baseline 224/3/227, now 225/3/228).

Commit: `f1fe20d` — "task-4: Widen GET /vendors to include contact details"
