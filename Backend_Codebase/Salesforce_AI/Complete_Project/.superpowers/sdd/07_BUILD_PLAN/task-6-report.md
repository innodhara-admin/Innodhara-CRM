# Task 6 report: `POST /admin/reset`

## What changed

- `app/api/admin.py`
  - Imports extended: `delete as sa_delete` and `func`/`select` from
    `sqlalchemy` (delete added, func/select already present); added
    `from app.core.reset_taxonomy import deletion_order`; `Base` added to the
    existing `from app.database import get_db` import.
  - Added `ResetRequest` (Pydantic model: `dry_run`, `wipe_transactional`,
    `wipe_catalogue`, `wipe_org_config`, `confirm_org_name`) and
    `reset_organisation` (`POST /reset`, i.e. `/api/v1/admin/reset`), gated on
    `require_permission("manage_settings")` (org_admin only), appended at the
    end of the file exactly as the brief specified — verbatim, no changes
    needed to the brief's code.
- `tests/test_dashboard_reset.py` (new) — the brief's 7-test suite, copied
  verbatim. Every test creates its own throwaway organisation via
  `create_org(client, super_token, ...)`; the only exception is
  `test_a_sales_agent_cannot_reset`, which uses the session-scoped `org_a`
  fixture but only asserts a 403 and applies nothing, matching the brief's
  stated exception.
- `Dashboard/READMEs/09_BACKEND_CHANGES.md` — row for change #5 (`State` and
  `Tests` columns) ticked to ✅; a dated change-log line added under §5
  describing what landed, the exact test count, and guard status.

Nothing else under `app/` was touched. `scripts/reset_for_datacentre_demo.py`
was not modified. No new column, no migration.

## Exact commands and full output

### Step 2 — confirm the test fails first (404)

```
python -m pytest tests/test_dashboard_reset.py -v
```

Result: all 7 failed, each on `404 Not Found` for `POST /api/v1/admin/reset`
(confirmed before the route existed).

### Step 4 — route added, re-run

```
python -m pytest tests/test_dashboard_reset.py -v
```

```
tests/test_dashboard_reset.py::test_dry_run_counts_without_deleting PASSED [ 14%]
tests/test_dashboard_reset.py::test_apply_requires_the_org_name_echoed_back PASSED [ 28%]
tests/test_dashboard_reset.py::test_flags_clear_only_their_own_bucket PASSED [ 42%]
tests/test_dashboard_reset.py::test_keep_survives_a_full_reset_and_the_session_still_works PASSED [ 57%]
tests/test_dashboard_reset.py::test_another_organisation_is_untouched PASSED [ 71%]
tests/test_dashboard_reset.py::test_reset_writes_an_audit_row_that_survives PASSED [ 85%]
tests/test_dashboard_reset.py::test_a_sales_agent_cannot_reset PASSED    [100%]

============================== 7 passed in 2.64s ==============================
```

### Step 5 — full suite

```
python -m pytest -q
```

```
........................................................................ [ 29%]
........................................................................ [ 59%]
........................................................................ [ 89%]
..............FF.F.......                                                [100%]
================================== FAILURES ===================================
FAILED tests/test_what_is_late.py::test_a_task_due_today_is_not_called_overdue
FAILED tests/test_what_is_late.py::test_the_due_today_header_is_never_empty
FAILED tests/test_what_is_late.py::test_today_and_overdue_never_overlap - Ind...
3 failed, 238 passed in 17.09s
```

**Suite is not corrupted.** Starting baseline (per the brief) was 231 passed /
3 failed / 234 collected. This task adds exactly 7 tests: 231 + 7 = 238 passed,
234 + 7 = 241 collected, 3 failed unchanged. The 3 failures are the same
pre-existing `test_what_is_late.py` timezone-boundary failures named in the
brief as out of scope (a test-side timezone assumption, unrelated to this
task) — same file, same three test names, same assertion shape as before.
No failure appeared in any other module, which is the specific signal that
would indicate a reset test had corrupted a session-scoped fixture (`org_a` /
`org_b`). None did.

Also re-ran `tests/test_reset_taxonomy.py` standalone as a sanity check that
the prior task's guard (the 55-table/4+2+7+42 partition and FK-ordering walk)
is untouched: 6 passed, unchanged.

## Where the brief's code was verbatim vs. anything I had to reconcile

The brief's Step 3 code was used exactly as given — no deviation. The only
work beyond copy-and-paste was:
- Confirming `manage_settings` maps to `{Role.ORG_ADMIN}` in
  `app/core/permissions.py` (so the 403 test is meaningful) and `view_audit`
  likewise, so the org_admin token used in the audit test can read
  `GET /admin/audit`.
- Confirming `audit_service.record`'s signature matches the call in the
  brief's route (`org_id`, `user_id`, `action`, `entity_type`, `entity_id`,
  `detail`) — it does, no adjustment needed.
- Confirming `Base` (from `app.database`) exposes `Base.metadata.tables` with
  the exact table names `deletion_order` returns (verified indirectly: the
  dry-run test's counts for `leads`, `programs`, `user_skills` all matched,
  and the apply tests deleted the right rows).

Nothing in the brief was wrong about the real code. No blockers, no need for
a ninth backend change — this task stayed entirely inside change #5's two
files (`app/api/admin.py`, plus the already-existing
`app/core/reset_taxonomy.py` from the prior task).

## Concerns

- `Base.metadata.tables[name]` will `KeyError` if `reset_taxonomy.py`'s bucket
  tuples ever drift from the actual schema (e.g. a table renamed without
  updating the taxonomy). `tests/test_reset_taxonomy.py` is the guard against
  that drift and is out of this task's scope to touch — flagging only as a
  latent coupling, not a defect found here.
- The "Guards green" column for change #5 is left ⬜, consistent with every
  other already-landed row in the table — `check_docs_in_sync.py` and
  `check_hardcoded_strings.py` are both still failing for reasons unrelated
  to this task (route-count resync is Task 10; the 2 cosmetic Java findings
  predate this work), so I did not tick that column. No other concerns.

---

## Fix round 1 of 5 — catalogue-only orphan guard + rollback test

Owner-approved amendments to change #5, not a ninth change. Both items from
the coordinator's review addressed; nothing needed beyond `app/api/admin.py`
and `tests/test_dashboard_reset.py`, so no BLOCKED report was needed.

### 1. The orphan guard

Added `_CATALOGUE_ORPHAN_EDGES` (a local tuple of the 6 FK edges from a
WIPE-bucket child into a REPLACE-bucket parent) and `_catalogue_blocking_edges`
(counts org-scoped rows on those edges where the FK column IS NOT NULL) to
`app/api/admin.py`. `app/core/reset_taxonomy.py` was not touched, per the
instruction that it is frozen and guarded — the edges are derived in
`admin.py` instead.

`reset_organisation` now runs this check only when `wipe_catalogue=True` and
`wipe_transactional=False` (the only combination where REPLACE can be deleted
while its WIPE-side children survive — when `wipe_transactional=True`, WIPE
precedes REPLACE in `deletion_order`, so the children are already gone and
nothing can be orphaned):

- **Dry run:** never refuses. Returns its normal 200 with a new
  `blocking_edges` key — a list of `{table, column, references, count}`,
  populated only for edges with `count > 0`, and `[]` when nothing blocks
  (including whenever the guard condition doesn't apply, so the key's shape
  is stable across every request). This lets a client show the conflict at
  preview.
- **Apply, total zero:** proceeds normally — a pre-go-live org with nothing
  referencing its catalogue is not refused.
- **Apply, total non-zero:** raises `ValidationFailedError` (422) before any
  delete runs, naming each blocking edge and its count, e.g.
  `proposals.program_id -> programs (1 row)`. Same shape as change #6's
  per-row delete guards — refused, with the reason stated.

Docstring on `_CATALOGUE_ORPHAN_EDGES` records the generalising rationale
verbatim from the review: this reset must not permit in bulk what change #6
already refuses per row.

### 2. The rollback test

`test_a_mid_loop_failure_rolls_back_everything` in
`tests/test_dashboard_reset.py`: monkeypatches `app.api.admin.deletion_order`
to return the real ordering (so real deletes run first) plus one appended
table name absent from `Base.metadata` (so `Base.metadata.tables[name]`
raises `KeyError` on the last entry). httpx's `ASGITransport` re-raises
unhandled app exceptions to the caller by default (there is no
`app.exception_handler` for bare `KeyError`, only for `AppError` in
`app/main.py`), so the request is wrapped in `pytest.raises(KeyError)`.
Confirmed afterward: leads/programs/user_skills counts unchanged, no
`admin.org_reset` row in the audit log, and `/auth/me` still 200 for the
resetting account. This exercises `app/database.py`'s `get_db` — `async with
SessionLocal() as session: yield session` — whose `AsyncSession.close()` on
an uncommitted transaction rolls it back; the route only calls `db.commit()`
once, after the full delete loop and the audit write, both of which are
unreached when the loop raises.

### New tests, in full

Added to `tests/test_dashboard_reset.py`, each against its own throwaway org:

- `test_catalogue_only_on_a_clean_org_proceeds` — no proposals/demos/etc.;
  200, `applied: true`, `blocking_edges: []`, programs deleted, lead (WIPE)
  untouched since `wipe_transactional=False`.
- `test_catalogue_only_on_an_org_with_a_proposal_refuses` — seeds a full
  proposal (program + pricing + template + lead + contact +
  `POST /proposals`, occupying 3 of the 6 edges); 422, response text names
  both `proposals` and `programs`; program count unchanged (nothing deleted).
- `test_catalogue_only_dry_run_reports_blocking_edges` — same seed, `dry_run:
  true`; 200 (never 422), `blocking_edges` non-empty and includes `proposals`,
  programs count unchanged (nothing deleted).
- `test_all_flags_reset_is_unaffected_by_the_catalogue_guard` — same seed,
  `wipe_transactional: true` added; 200, `applied: true`, `blocking_edges:
  []`, programs deleted — proves the guard is a no-op on the combination that
  already existed.
- `test_a_mid_loop_failure_rolls_back_everything` — described above.

`_seed_proposal` helper reuses the template body from `tests/test_proposals.py`
(program → pricing → proposal-template → lead → contact → `POST /proposals`)
to get a proposal whose `program_id`/`template_id`/`pricing_table_id` are all
populated.

### Commands and output

```
python -m pytest tests/test_dashboard_reset.py -v
```

```
collected 12 items

tests/test_dashboard_reset.py::test_dry_run_counts_without_deleting PASSED [  8%]
tests/test_dashboard_reset.py::test_apply_requires_the_org_name_echoed_back PASSED [ 16%]
tests/test_dashboard_reset.py::test_flags_clear_only_their_own_bucket PASSED [ 25%]
tests/test_dashboard_reset.py::test_keep_survives_a_full_reset_and_the_session_still_works PASSED [ 33%]
tests/test_dashboard_reset.py::test_another_organisation_is_untouched PASSED [ 41%]
tests/test_dashboard_reset.py::test_reset_writes_an_audit_row_that_survives PASSED [ 50%]
tests/test_dashboard_reset.py::test_a_sales_agent_cannot_reset PASSED    [ 58%]
tests/test_dashboard_reset.py::test_catalogue_only_on_a_clean_org_proceeds PASSED [ 66%]
tests/test_dashboard_reset.py::test_catalogue_only_on_an_org_with_a_proposal_refuses PASSED [ 75%]
tests/test_dashboard_reset.py::test_catalogue_only_dry_run_reports_blocking_edges PASSED [ 83%]
tests/test_dashboard_reset.py::test_all_flags_reset_is_unaffected_by_the_catalogue_guard PASSED [ 91%]
tests/test_dashboard_reset.py::test_a_mid_loop_failure_rolls_back_everything PASSED [100%]

============================= 12 passed in 3.79s ==============================
```

```
python -m pytest -q
```

```
3 failed, 243 passed in 20.22s
```

Same 3 pre-existing `test_what_is_late.py` timezone-boundary failures as
before this fix round, no others. 238 → 243 (+5, exactly the 5 new tests
added). Baseline before this round was 238 passed / 3 failed / 241 collected
(this task's own prior state); 243 + 3 = 246 collected = 241 + 5. No
session-scoped fixture (`org_a`/`org_b`) was corrupted.

### Concerns

- None blocking. `_CATALOGUE_ORPHAN_EDGES` is a second place (alongside
  `reset_taxonomy.py`) that knows about these 6 FK edges; if the schema grows
  a new WIPE→REPLACE edge, nothing forces this list to be updated the way
  `tests/test_reset_taxonomy.py` forces `reset_taxonomy.py` to stay a
  complete partition. Flagging as a latent gap, not a defect in this round —
  the instruction was explicit that `reset_taxonomy.py` is frozen and the
  edges must be derived locally in `admin.py`.

---

## Fix round 2 of 5 — derive `_CATALOGUE_ORPHAN_EDGES`, don't hand-list it

Closes the latent gap flagged at the end of fix round 1: the hand-written
6-tuple had nothing forcing it to stay complete if the schema grew a new
WIPE/CONFIG → REPLACE edge. Owner-flagged defect in the prior round's own
work; same pattern (D12: generated, not mirrored) that produced a Critical
finding in the task immediately before this one.

### The fix

`app/api/admin.py`: `_CATALOGUE_ORPHAN_EDGES` is now the output of
`_derive_catalogue_orphan_edges()`, which walks `Base.metadata` once at
import time — for every table in `set(WIPE) | set(CONFIG)` (the tables that
survive a catalogue-only reset), for every column's `ForeignKey`, keep the
edge if the FK's target table is in `REPLACE`. `WIPE`, `CONFIG`, `REPLACE`
are imported (read-only) from `app.core.reset_taxonomy`, which is untouched.
The result is `tuple(sorted(edges))` so the 422 message stays stable across
runs (the walk iterates set-typed buckets, so raw insertion order is not
guaranteed). Everything downstream — `_catalogue_blocking_edges`, the
dry-run/apply behaviour, the response shape and keys, the NOT-NULL-only
counting, the org scoping — is unchanged; only how the edge list itself is
produced changed.

**Sanity check before changing anything**, per the brief: ran the derivation
standalone against the current schema first. It reproduced exactly the same
six edges as the hand-written tuple (as a set) — no STOP condition was hit.

```
('demo_team_members', 'team_id', 'demo_teams')
('demos', 'team_id', 'demo_teams')
('projects', 'program_id', 'programs')
('proposals', 'pricing_table_id', 'pricing_tables')
('proposals', 'program_id', 'programs')
('proposals', 'template_id', 'proposal_templates')
count: 6
```

### The completeness test

`tests/test_dashboard_reset.py::test_catalogue_orphan_edges_match_the_schema`
— independently re-walks the same FK graph inside the test body (not by
calling `_derive_catalogue_orphan_edges`, so it can't share a bug with it),
asserts `set(_CATALOGUE_ORPHAN_EDGES) == expected`, asserts the tuple is
already sorted, and pins the current six edges as a literal set so a
derivation bug that narrows both sides identically (e.g. only walking one
bucket) can't hide behind an equally-narrow `expected`.

Verified the test actually falsifies narrowing, without touching the real
file (a raw-Python rewrite of `admin.py` during this round briefly
corrupted its line endings LF→CRLF, caught via `git diff --stat` showing a
1045/1025-line rewrite for a 2-line change; reverted with `git checkout --`
and redone through the `Edit` tool only, which preserved the file's LF
endings — `git diff --stat` after redoing showed the expected small diff).
The falsification itself was done out-of-process: computed `expected` from
the real schema, then compared it against a deliberately narrowed set
(edges whose target is only `programs`) — `expected != narrowed` (2 of 6
edges survive the narrowing), confirming the test's equality assertion
would catch a derivation that silently stopped covering some of the buckets
or targets.

### Commands and output

```
python -m pytest tests/test_dashboard_reset.py -v
```

```
collected 13 items

tests/test_dashboard_reset.py::test_dry_run_counts_without_deleting PASSED [  7%]
tests/test_dashboard_reset.py::test_apply_requires_the_org_name_echoed_back PASSED [ 15%]
tests/test_dashboard_reset.py::test_flags_clear_only_their_own_bucket PASSED [ 23%]
tests/test_dashboard_reset.py::test_keep_survives_a_full_reset_and_the_session_still_works PASSED [ 30%]
tests/test_dashboard_reset.py::test_another_organisation_is_untouched PASSED [ 38%]
tests/test_dashboard_reset.py::test_reset_writes_an_audit_row_that_survives PASSED [ 46%]
tests/test_dashboard_reset.py::test_a_sales_agent_cannot_reset PASSED    [ 53%]
tests/test_dashboard_reset.py::test_catalogue_only_on_a_clean_org_proceeds PASSED [ 61%]
tests/test_dashboard_reset.py::test_catalogue_only_on_an_org_with_a_proposal_refuses PASSED [ 69%]
tests/test_dashboard_reset.py::test_catalogue_only_dry_run_reports_blocking_edges PASSED [ 76%]
tests/test_dashboard_reset.py::test_all_flags_reset_is_unaffected_by_the_catalogue_guard PASSED [ 84%]
tests/test_dashboard_reset.py::test_a_mid_loop_failure_rolls_back_everything PASSED [ 92%]
tests/test_dashboard_reset.py::test_catalogue_orphan_edges_match_the_schema PASSED [100%]

============================= 13 passed in 5.64s ==============================
```

```
python -m pytest -q
```

```
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 87%]
...............................                                          [100%]
247 passed in 23.67s
```

246 (this task's prior state: 243 passed + 3 failed) + 1 new test = 247
collected — matches. The 3 previously-failing `test_what_is_late.py` tests
now pass too; re-ran that file alone and it is 5/5 green. That module's
failures were already documented as a test-side timezone-boundary
assumption, out of scope for this task — nothing in this round touched
dates, times, or that file, so the boundary simply moved with the clock
between sessions. Also re-ran `tests/test_reset_taxonomy.py` standalone as
a sanity check that the frozen module and its guard are untouched: 6
passed, unchanged.

### Where the brief's sketch was used vs. adjusted

Used the brief's sketch almost verbatim (`for child in set(WIPE) | set(CONFIG)`,
walk columns, walk `column.foreign_keys`, check `fk.column.table.name in
REPLACE`), wrapped in a named function so it can run once at import time and
its result be sorted before being frozen into the module-level tuple, per
the brief's "if you derive at import time... sort the result" instruction.

### Concerns

- None blocking. `_derive_catalogue_orphan_edges` still does a fresh
  `Base.metadata` walk at import time (same latent coupling to
  `reset_taxonomy.py`'s bucket tuples noted in fix round 1 — a table
  renamed without updating the taxonomy would `KeyError`, which
  `tests/test_reset_taxonomy.py` already guards against). No new coupling
  was introduced; the gap that existed at the end of fix round 1 is closed.
