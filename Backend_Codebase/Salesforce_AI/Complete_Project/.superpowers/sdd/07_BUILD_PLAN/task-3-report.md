# Task 3 report — `GET /playbooks` (change #3)

## What changed

- **`app/api/ops.py`** — added `list_playbooks`, a new `GET /playbooks` route,
  inserted immediately before the existing `@router.get("/playbooks/suggestions")`
  (in the "Playbooks & suggestions" block). No new imports were needed:
  `Playbook`, `select`, `AsyncSession`, `Depends`, `get_db`, `get_org_context`,
  `OrgContext` were already imported/used by other routes in this file.

  ```python
  @router.get("/playbooks")
  async def list_playbooks(
      program_id: str | None = None,
      phase: str | None = None,
      current_only: bool = True,
      ctx: OrgContext = Depends(get_org_context),
      db: AsyncSession = Depends(get_db),
  ):
      ...
  ```

  Query params: `program_id`, `phase`, `current_only` (default `True`).
  Response: `list[dict]` with keys `id`, `program_id`, `phase`, `entries`,
  `version`, `is_current`, `updated_by`. Org-scoped (`Playbook.org_id ==
  ctx.org_id`), ordered by `phase, version`. Gated on `Depends(get_org_context)`
  only — readable by any org member, matching its GET siblings (e.g.
  `GET /playbooks/suggestions`, `GET /vendors`). No permission tightening or
  loosening anywhere else in the file.

- **`tests/test_dashboard_reads.py`** (new) — 3 tests, exactly as specified in
  the brief, verbatim:
  - `test_playbooks_can_be_read_back` — posts one playbook, reads it back,
    checks `phase`, `entries` round-trip exactly, `is_current is True`.
  - `test_playbooks_current_only_hides_superseded` — posts the same
    program+phase twice (upsert-versions), confirms `current_only` default
    hides the v1 row and returns only v2, and `current_only=false` returns
    both.
  - `test_playbooks_are_org_scoped` — org B's admin gets `200` with `[]` (no
    cross-org leakage), never a 403/404 — matching "readable by any org
    member" without weakening the org boundary.

- **`Dashboard/READMEs/09_BACKEND_CHANGES.md`** — change #3's row ticked to
  ✅/✅ under State/Tests (Guards green left ⬜, unchanged — the sync guard
  and hardcoded-string guard are Task 10's job per the doc's own §4/change-log
  convention); added a dated change-log line under §5.

## Exact test commands and output

Step 2 (confirm failing before the route existed):
```
python -m pytest tests/test_dashboard_reads.py -v
```
Result: 3 failed — `test_playbooks_can_be_read_back` and
`test_playbooks_current_only_hides_superseded` failed on the assertions that
depend on a working GET (both got `405 Method Not Allowed` under the hood);
`test_playbooks_are_org_scoped` failed with `assert 405 == 200`. This matches
the brief's "Expected: FAIL — 405 or 404" exactly.

Step 4 (after adding the route):
```
python -m pytest tests/test_dashboard_reads.py -v
```
```
tests/test_dashboard_reads.py::test_playbooks_can_be_read_back PASSED    [ 33%]
tests/test_dashboard_reads.py::test_playbooks_current_only_hides_superseded PASSED [ 66%]
tests/test_dashboard_reads.py::test_playbooks_are_org_scoped PASSED      [100%]
============================== 3 passed in 1.22s ==============================
```

Step 5 (full suite checkpoint):
```
python -m pytest -q
```
```
FAILED tests/test_what_is_late.py::test_a_task_due_today_is_not_called_overdue
FAILED tests/test_what_is_late.py::test_the_due_today_header_is_never_empty
FAILED tests/test_what_is_late.py::test_today_and_overdue_never_overlap - Ind...
3 failed, 224 passed in 18.50s
```
227 collected total (224 passed + 3 failed). This is exactly the pre-existing
baseline (221 passed / 3 failed / 224 collected, per the brief) plus this
task's 3 new passing tests (221→224 passed, 224→227 collected, same 3
pre-existing `test_what_is_late.py` failures — unrelated timezone/date-boundary
assumptions on the test side, not touched by this change).

## Anything in the brief that was wrong about the real code

Nothing. The brief's description of `app/api/ops.py` (no router prefix, so
`/api/v1/playbooks` not `/api/v1/ops/playbooks`), the existing `POST
/playbooks` upsert-versioning behavior, the `Playbook` model import location
(`app.models.project`, already imported in `ops.py`), and the exact insertion
point (immediately before `GET /playbooks/suggestions`) all matched the real
code exactly. The route code and test code were used verbatim from the brief
with no adjustments.

## Concerns

None. This was a pure additive read route on top of an existing model/table,
gated identically to its GET siblings, with no new column, no migration, and
no permission change. The only pre-existing test failures (3, in
`tests/test_what_is_late.py`) are unrelated to this change and were present
before it (confirmed by the brief's stated baseline of 221/3/224, which this
task's run reproduced exactly modulo the 3 new tests).
