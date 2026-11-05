# Task 12 report — close the bare-reference hole in the catalogue-orphan guard

Branch `fix/d23-bare-reference-guard`, prior HEAD `b6d3470`. This is an
**amendment to change #5** (the catalogue-only reset orphan guard), not a
ninth backend change — it closes a gap in a guard that already exists. The
eight-change list stays closed at eight.

## The hole

`_CATALOGUE_ORPHAN_EDGES` in `app/api/admin.py` was derived purely by
walking `ForeignKey` objects on every table in `WIPE | CONFIG` whose target
is in `REPLACE`. `playbook_suggestions.program_id`
(`app/models/project.py`) is a bare `String(32)`, `nullable=False`, with no
`ForeignKey` — invisible to that walk by construction. A catalogue-only
reset (`wipe_catalogue=True`, `wipe_transactional=False`) therefore deleted
every `programs` row while `playbook_suggestions` rows survived pointing at
dead ids, reporting `blocking_edges: []` and proceeding.

Confirmed this is the *only* such column: enumerated every `*_id`-shaped
column on every `WIPE | CONFIG` table and its FK status — `playbook_
suggestions.program_id` is the sole `FK->NONE` entry whose stem names a
`REPLACE` table.

## The fix

`app/api/admin.py`:
- Kept `_derive_catalogue_orphan_edges()` (the FK walk) unchanged.
- Added `_CATALOGUE_ORPHAN_EDGES_DECLARED`, a one-entry tuple:
  `("playbook_suggestions", "program_id", "programs")`, commented with why
  derivation can't see it (bare column, no `ForeignKey`) and why that isn't
  being schema-fixed here (needs a migration; no Alembic in this project).
- `_CATALOGUE_ORPHAN_EDGES` is now
  `tuple(sorted(set(_derive_catalogue_orphan_edges()) | set(_CATALOGUE_ORPHAN_EDGES_DECLARED)))`
  — derived | declared, still sorted for stable 422 messages.
- Extended the block comment above `_derive_catalogue_orphan_edges` to
  explain the blind spot and point at the new declared list.
- Everything else about the guard is unchanged: still counts only
  non-null, org-scoped rows; still 422s only on apply, never on a dry run;
  `audit_service.record` call in `reset_organisation` untouched.

## Tests (`tests/test_dashboard_reset.py`)

1. **Updated** `test_catalogue_orphan_edges_match_the_schema` — now compares
   `_CATALOGUE_ORPHAN_EDGES` against `fk_derived | declared` (both
   independently recomputed, `declared` imported from
   `_CATALOGUE_ORPHAN_EDGES_DECLARED`), and pins both the known 6 FK edges
   and the 1 known declared edge separately, so a narrowing in either
   bucket can't hide behind a still-passing union comparison.

2. **New** `test_every_bare_star_id_column_naming_a_replace_table_is_covered`
   — the test that matters most. Independently scans every table in
   `WIPE | CONFIG` (its own name-based logic, not a reuse of admin.py's FK
   walk or the declared list's own reasoning) for `*_id` columns whose stem
   plausibly names a `REPLACE` table — e.g. `team_id` → `demo_teams`,
   `pricing_table_id` → `pricing_tables` — and asserts every candidate found
   is present in `_CATALOGUE_ORPHAN_EDGES` (FK-derived or declared). On
   today's schema it finds exactly 7 candidates (the 6 FK edges +
   `playbook_suggestions.program_id`) and a sanity assert (`>= 7`) guards
   against the scan silently finding nothing.

3. **New** `test_catalogue_only_on_an_org_with_a_playbook_suggestion_refuses`
   — the real-case reset test. Creates a throwaway org (`create_org`, not
   `org_a`/`org_b`, which are session-scoped), a program via the API, and a
   `PlaybookSuggestion` row inserted directly through `SessionLocal` (no
   POST route for it — same pattern as
   `tests/test_dashboard_deletes_admin.py::test_unused_program_deletes`).
   Asserts: dry run returns 200 and lists `playbook_suggestions` in
   `blocking_edges`; apply returns 422 naming both `playbook_suggestions`
   and `programs`; the program and the suggestion row both survive the
   refusal.

### Counterfactual proof the scanner test isn't vacuous

Per the task's requirement (proof in the spirit of Task 5's re-review), ran
the *actual* test function, imported straight from
`tests.test_dashboard_reset`, against a live process with
`admin_module._CATALOGUE_ORPHAN_EDGES_DECLARED` monkeypatched to `()` and
`_CATALOGUE_ORPHAN_EDGES` recomputed from FK-derivation alone (simulating
"the one bare reference lost its declaration"):

```
CORRECTLY RAISED AssertionError:
playbook_suggestions.program_id names a REPLACE table by its column name
but is not in _CATALOGUE_ORPHAN_EDGES — if it has no ForeignKey, add it to
_CATALOGUE_ORPHAN_EDGES_DECLARED in app/api/admin.py
```

Also ran a second counterfactual (reproduced scan logic against an injected
synthetic column, since injecting a column onto a live mapped model isn't
practical): appended a synthetic `vendor_id` `String(32)` column (no FK) to
the real `incidents` table's `Base.metadata` object, then ran the scan —
it flagged `("incidents", "vendor_id")` as uncovered, confirming the scan
mechanism itself (not just the assertion) reacts to a schema change it
wasn't told about, not only to the one case it was written against. Full
script and both runs' output captured during development; not checked in
(scratchpad only), since the task asked for the proof recorded in this
report, not a permanent test-of-the-test.

Restored `_CATALOGUE_ORPHAN_EDGES_DECLARED` / `_CATALOGUE_ORPHAN_EDGES` to
their real values after both counterfactuals; reran the full suite
afterward to confirm no state leaked (see Verification).

## Verification

Local time of the suite run: **2026-08-13, 15:49 IST** — outside the
00:00–05:30 window `tests/test_what_is_late.py` is sensitive to; those three
tests were not touched.

```
python -m pytest -q                          → 268 passed, 0 failed
python scripts/check_docs_in_sync.py         → exit 0, "OK - the three documents agree with the code"
python -m pytest tests/test_genericity.py -q → 8 passed
```

`check_docs_in_sync.py`'s own count line: `55 tables, 755 columns,
151 routes, 20 permissions, 41 event types, 7 plan ops` — **route count
unchanged at 151**, as required (no route added or removed; this task added
one declared tuple entry and closed an assertion gap inside an existing
route's guard).

268 = the prior 266 passed + 2 new tests
(`test_every_bare_star_id_column_naming_a_replace_table_is_covered`,
`test_catalogue_only_on_an_org_with_a_playbook_suggestion_refuses`).
`test_catalogue_orphan_edges_match_the_schema` was updated in place, not
added.

## Files touched

- `app/api/admin.py` — declared exception list + merged edge set + comment
  updates. No route added/removed, no schema change.
- `tests/test_dashboard_reset.py` — 1 test updated, 2 tests added.

No other files touched, per constraint. `app/core/reset_taxonomy.py` was
not modified. No `ForeignKey` was added to `playbook_suggestions`. No
migration, no new column, no new route.

## Concerns

- The name-stem heuristic in the new scanner test is deliberately
  conservative-but-real: it catches multi-word table names (`demo_teams` →
  `team_id`, `pricing_tables` → `pricing_table_id`) as well as exact
  matches (`programs` → `program_id`). It is a test-only heuristic, not
  shipped in `app/api/admin.py` — the production guard still only ever
  acts on the explicit `derived | declared` tuple, never on a name guess.
- `_CATALOGUE_ORPHAN_EDGES_DECLARED` is intentionally a manual list with one
  entry and a comment requiring justification for any addition — it is an
  escape hatch for "the ORM can't see this," not a general substitute for
  fixing the schema (which the task explicitly puts out of scope).
