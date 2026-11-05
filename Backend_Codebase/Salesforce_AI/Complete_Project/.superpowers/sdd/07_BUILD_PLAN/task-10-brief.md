### Task 10: Resync the docs and run every guard

Phase 1 is not done until the guards are green. **"The docs are updated" is not
the completion claim.**

**Files:**
- Modify: `BACKEND_README.md` — the counts table and §7.1

- [ ] **Step 1: Measure, do not assume**

Run: `python scripts/check_docs_in_sync.py`

It prints the live figures before it compares them, e.g.
`code: 55 tables, 755 columns, 151 routes, ...` and
`[INFO] §7.1 breakdown from code: 70 uncalled (...)`.

**Use the numbers it prints.** The expected values are 151 routes and 70 uncalled,
with Organisation administration 25 and Operations and money 20 — but if the
printout disagrees, the printout is right and this plan is stale.

- [ ] **Step 2: Update the README's counts table**

Change the routes row from `**140** | 16 endpoint modules` to
`**151** | 16 endpoint modules`. The guard matches that exact pattern.

- [ ] **Step 3: Update §7.1**

Set the heading to `### 7.1 What the app does not call (70 routes)` and the two
changed rows to **Organisation administration 25** and **Operations and money 20**.
Leave Everything else 13, Platform / Super Admin 4, Incidents 3, Approval rules 3,
Device push registration 2. The rows must sum to 70 — the guard checks the sum
independently of the heading, because a table has been wrong in the rows while
right in the total before.

- [ ] **Step 4: Run the docs guard**

Run: `python scripts/check_docs_in_sync.py`
Expected: exit 0, ending `OK - the three documents agree with the code`.

- [ ] **Step 5: Run the two genericity guards**

```bash
python -m pytest tests/test_genericity.py -q
python scripts/check_hardcoded_strings.py
```

Expected: both pass. Neither scans `Dashboard/`, so neither should react to
Phase 1 at all — if one does, something landed in the wrong directory.

- [ ] **Step 6: Fix the README's test-count wording**

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

- [ ] **Step 7: Run the full suite and record both totals**

Run: `python -m pytest -q`

Record collected **and** passing in `08_PROGRESS_AND_HANDOFF.md`, plus the local
time of the run — because of the window above, "green" without a timestamp is
not a reproducible claim.

- [ ] **Step 8: Checkpoint — Phase 1 complete**

All four commands green, **with the `test_what_is_late.py` window noted** rather
than silently absorbed. Mark every row in `09_BACKEND_CHANGES.md` done with its
guard column ticked, and update `08_PROGRESS_AND_HANDOFF.md` to say Phase 2 is next.

---

# PHASE 2 — The console

## Why Phase 2's tasks are written after Task 10, not now

**The console's entire type layer is generated from the backend's
`/openapi.json` (D12).** Writing task-level detail now would mean inventing the
schema and type names `openapi-zod-client` will emit — for routes that do not
exist yet, from a generator whose output naming depends on its pinned version.
Those invented names would be wrong, and a plan that names a type no task defines
is the exact failure mode the plan format forbids.

So Phase 2's plan is written **immediately after Task 10**, from the real
generated client, and appended to this file as Tasks 11 onward.

This is not a deferral of decisions — every design decision is already made in
`06_DESIGN.md`. It is a deferral of *symbol names* until the symbols exist.

## What Phase 2 covers, in build order

Each row is one task, sized to end with something testable.

| # | Task | Deliverable |
|---|---|---|
| 11 | Scaffold + generation pipeline | `dump_openapi.py`, `npm run gen:api`, `gen:check` wired as `prebuild`, committed `generated.ts` |
| 12 | Design tokens + primitives | `tokens.css`, light/dark, the four status markers, type scale |
| 13 | `api/client.ts` + `session/` | base-URL field, dual token store, `retry: 0`, `AppError` normalisation |
| 14 | Org creation + chained hand-off | the D18 blocking modal, including the recovery state |
| 15 | Descriptor layer + conformance tests | 11 modules, `backend` / `ui-only` rules, the drift tests of §3.2 |
| 16 | Checklist rail + status derivation | pure functions, four statuses, the compound email status |
| 17 | Item screens: Tiers 0–1 | staff, skills |
| 18 | Item screens: Tier 2 catalogue | programs, pricing, proposal templates, message templates |
| 19 | Item screens: Tier 3 governance | playbooks, approval rules, settings, integrations, retention |
| 20 | Item screens: Tier 4 | demo teams, calendar, vendors, and item 16's permanent `—` |
| 21 | Import: parse + validate + preview | papaparse, per-row verdicts, template download |
| 22 | Import: apply + failures file | continue-on-error, `_error` column, round-trip re-import (D21) |
| 23 | Go-live check | skill coverage, program completeness, rule ordering, delivery honesty |
| 24 | Reset + catalogue bundle | three flags, dry-run counts, org-name confirmation, export/import |
| 25 | Build, mount, verify | `npm run build`, confirm `/dashboard` serves, re-run all guards |

## Phase 2 test strategy

**Vitest only. No E2E, no component tests** (D11).

Three suites, each covering the logic where a silent bug is expensive:

1. **Drift** (Task 15) — every descriptor field exists in its generated schema;
   every descriptor resolves to a schema; `gen:check` fails on a stale
   `generated.ts`.
2. **Import** (Tasks 21–22) — CSV quoting with embedded newlines in `body_md`;
   the `default_quantity` tri-state surviving a round trip without becoming `1`;
   per-row verdicts; the re-import behaviours of §5.5; apply continuing past a
   failure; and the failures file round-tripping — parse what was emitted and get
   exactly the failed rows back, `_error` ignored.
3. **Status derivation** (Task 16) — pure functions, so table-driven: fixture API
   payloads in, expected status out. Must include the compound email case
   (credentials stored + `EMAIL_MODE=dry_run` → `◐`, never `●`) and item 10's
   untouched-defaults case.

Screens themselves are verified by using them against a live backend, which the
reset endpoint makes cheap to repeat.

---

## Self-review against the spec

| `06_DESIGN.md` section | Covered by |
|---|---|
| §2 Stack | Task 11 |
| §3 Generated/hand-written boundary | Tasks 11, 15 |
| §4.1 client, no retry | Task 13 |
| §4.2 chained hand-off | Task 14 |
| §5.1–5.2 rail and status | Task 16 |
| §5.3–5.4 item screens and warnings | Tasks 17–20 |
| §5.5 import, partial applies | Tasks 21–22 |
| §5.6 go-live check | Task 23 |
| §5.7–5.8 reset and bundle | Tasks 6, 24 |
| §6 honesty model | Tasks 16, 20 |
| §7.1 four small backend changes | Tasks 1, 2, 3, 4 |
| §7.2 eight guarded deletes | Tasks 7, 8 |
| §7.3 reset endpoint | Tasks 5, 6 |
| §8 docs guard | Task 10 |
| §8.1 dist/ invariant | Tasks 9, 10 |
| §9 visual design | Task 12 |
| §10 testing | Tasks 5–9 (pytest), Phase 2 strategy (Vitest) |
| §11 READMEs | `08`, `09` stubs, updated at every checkpoint |
| §12 known limits | Surfaced in Tasks 14, 20, 22, 24 |

**Gap check:** every section maps to a task. Change #8's D20 amendment is
Task 9; D21's failures file is Task 22; D17's `retry: 0` is Task 13.
