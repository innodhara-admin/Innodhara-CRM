# Task 10 report — resync the docs and run every guard

## Status

**Phase 1 is complete.** All four verification commands are green (the
hardcoded-strings guard is green in the sense of "unchanged from before this
task" — see below, exit code 1 with 2 pre-existing findings that predate this
work and are out of scope to fix).

## Step 1 — measured, not assumed

`python scripts/check_docs_in_sync.py` printed, before any edit:

```
code: 55 tables, 755 columns, 151 routes, 20 permissions, 41 event types, 7 plan ops
...
[INFO] §7.1 breakdown from code: 70 uncalled (Approval rules 3, Device push registration 2,
Everything else 13, Incidents 3, Operations and money 20, Organisation administration 25,
Platform / Super Admin 4)
```

Every figure the printout gave **agreed exactly** with the brief's predicted
values (151 routes, 70 uncalled, Organisation administration 25, Operations and
money 20). No brief/printout conflict arose, so nothing needed to be resolved
in the printout's favour — but the printout, not the brief, is what was typed
into the doc.

## Files changed

- **`BACKEND_README.md`**
  - Top counts table: `API routes | **140**` → `**151**` (the exact pattern the
    guard matches).
  - Two more prose mentions of the same total, updated for internal
    consistency (not required by the guard's regex, but left stale would have
    made the document self-contradictory): §6's intro (`**140 routes across 16
    modules**` → `**151 routes across 16 modules**`, and `**81 of the 140**` →
    `**81 of the 151**`), and the top summary row `calls 81 of the 140 routes`
    → `calls 81 of the 151 routes`. The "81 called" figure itself is
    unchanged and self-consistent: 151 − 70 = 81.
  - §7.1: heading `(59 routes)` → `(70 routes)`; row "Organisation
    administration" `18` → `25`; row "Operations and money" `16` → `20`. The
    five other rows (Everything else 13, Platform / Super Admin 4, Incidents 3,
    Approval rules 3, Device push registration 2) were left untouched, per the
    brief. New row sum: 25+20+4+3+3+2+13 = **70**, matching the heading. The
    guard checks the sum independently of the heading — both are now correct.
  - §13 (Testing): replaced the misleading **"218 pytest"** (`**218 passing**`
    in the summary table, `**218 tests pass** across **30 test files** (210
    test functions)`, and the `218 passed in 18.15s` code block) with the
    measured current figures — `**265 collected, 265 passing**` in the summary
    table, `**265 tests collected, 265 passing** across **38 test files** (257
    test functions), in about 27 seconds`, and `265 passed in 26.80s`. Added a
    new "time-of-day caveat" paragraph explaining the `test_what_is_late.py`
    window (see Step 6 below) so a bare pass count doesn't read as an
    unconditional claim.
  - I did **not** touch the full per-route listing tables in §6 (e.g. the
    `**Organisation administration** (20)` sub-heading and its row-by-row
    method/path/access table) or the DELETE-route table. The brief's `Files`
    section scopes Task 10 to "the counts table and §7.1"; enumerating the 11
    new routes' exact paths/methods/access levels in the detailed §6 listing
    would mean inventing content I had not verified against the code, which is
    a larger and riskier expansion than a resync task should make. This is a
    known residual gap, flagged here rather than silently left.

- **`Dashboard/READMEs/09_BACKEND_CHANGES.md`**
  - Guard column ticked ✅ for all 8 rows in the "eight changes" table.
  - §4 ("Route-count consequences") note updated from "fails until resynced —
    Task 10" to "failed until resynced — Task 10, done 2026-08-13" plus the
    guard's exact passing output.
  - Top banner: `Unfrozen: 2026-08-13` → `Unfrozen: 2026-08-13. Re-frozen:
    2026-08-13`, noting every row is ✅ and ticked.
  - Appended a Task 10 row to the §5 change log with the four verification
    commands' exact results.

- **`Dashboard/READMEs/08_PROGRESS_AND_HANDOFF.md`**
  - Top line: `design complete, no code written yet` → `Phase 1 complete —
    all 8 backend changes shipped, docs resynced, all four guards green.
    Phase 2 (the console) is next.`
  - §1 status table: T1–T10 all flipped from ⬜ not started to ✅ done, each
    with an evidence pointer; T11–T25 marked ⬜ next (was ⬜ blocked); "Next
    action" rewritten to point at Phase 2.
  - §2 split into "pre-Phase-1 baseline" (the original, unchanged numbers, now
    correctly labelled as historical, commit `19efa98`, including the honest
    `218 collected, 215 passing, 3 failing`) and a new §2a "current, measured
    after Task 10" with the resynced figures (151 routes, 149 under `/api/v1`,
    11 DELETEs, 70 uncalled, 265/265 pytest with a run timestamp).
  - §3: corrected "This repository is not under git" (it is — branch
    `feat/setup-console-phase1`, confirmed via `git status`/`git log`).
  - §4: added item 8 documenting the `test_what_is_late.py` clock-dependent
    window as a standing "thing that will bite," with the rule "always record
    the local time of a suite run alongside its pass count."
  - §5: added a dated 2026-08-13 handoff entry for this task, newest-first
    above the existing design-session entry.

No file under `app/` was touched. No guard script was modified.

## Step 4 — docs guard

```
$ python scripts/check_docs_in_sync.py
code: 55 tables, 755 columns, 151 routes, 20 permissions, 41 event types, 7 plan ops
[PASS] Data Model covers all 55 tables and every column
[PASS] Data Model uses no renamed identifier
[PASS] Workflows uses no renamed identifier
[PASS] Workflows names all 7 plan operations
[PASS] Workflows still has all 30 workflow headings
[PASS] README domain model lists all 55 tables
[PASS] README's stated counts match the code
[INFO] §7.1 breakdown from code: 70 uncalled (Approval rules 3, Device push registration 2,
Everything else 13, Incidents 3, Operations and money 20, Organisation administration 25,
Platform / Super Admin 4)
[PASS] README §7.1 breakdown matches the code, per category and in total (70)

OK - the three documents agree with the code
```

Exit code: **0**.

(The `WARNING app: Setup console not mounted` line is expected — `Dashboard/dist/`
does not exist, per T9's design, and does not affect the API.)

## Step 5 — the two genericity guards

```
$ python -m pytest tests/test_genericity.py -q
........                                                                 [100%]
8 passed in 0.74s
```

```
$ python scripts/check_hardcoded_strings.py
[PASS] detector precision: 11/11

[FAIL] User-visible literals hardcoded in Java (belong in strings.xml) — 2
       A strings.xml grep cannot see these — that is how F31's app half hid.
       java\com\yuvipep\app\feature\auth\LoginFragment.java:101 — setText("server: ")
       java\com\yuvipep\app\feature\auth\SplashFragment.java:48 — setText("v")
[PASS] Domain words in Java literals: none
[PASS] Currency symbols hardcoded in Java: none

FAIL — 2 finding(s)
```

Exit code: **1**. These 2 findings (`LoginFragment.java:101`, `SplashFragment.java:48`)
are **pre-existing and cosmetic** — `BACKEND_README.md` §13.1 already documented
them before this task ("The two open findings are cosmetic developer
affordances, not domain leakage"), and they are unrelated to any of the 8
backend changes or to this docs-only task. Not fixed, per the brief's explicit
instruction ("Report them as pre-existing; do not fix them") and the global
constraint against touching application code.

Neither guard reacted to anything under `Dashboard/` — confirmed by inspection
of both guards' scan roots (`app/**/*.py` and Android Java only) and by the
fact their output is identical to pre-Task-10 runs recorded in `09_BACKEND_CHANGES.md`'s
change log.

## Step 6 — the test-count wording fix

Baseline provided by the controller (pre-work, commit `19efa98`): **218
collected, 215 passing, 3 failing**. The 3 failures in `tests/test_what_is_late.py`
are a **test-side timezone assumption, not a product defect**: `assistant_engine.py`
partitions on `today_local = date.today()` (local date), while the test helper
builds due dates from `utcnow()` (UTC date). On this UTC+5:30 machine those
dates disagree between 00:00 and 05:30 local, so the suite is green for 18.5
hours a day and red for 5.5. Fixing it is one line in the test helper and is
outside this project's closed change list — not fixed.

`BACKEND_README.md` §13 now states the measured current figures (see "Files
changed" above) rather than the baseline, since the baseline predates all 9
prior tasks' new tests; both numbers and the caveat are recorded together so
neither is mistaken for the whole story.

## Step 7 — full suite, both totals, with timestamp

```
$ python -m pytest -q
........................................................................ [ 27%]
........................................................................ [ 54%]
........................................................................ [ 81%]
.................................................                        [100%]
265 passed in 26.51s
```

**Collected: 265. Passing: 265. 0 failed.**

**Local time of this run: 2026-08-13, 14:59** (measured via `Get-Date`
immediately before and after the run: 14:59:10 → 14:59:42), which is outside
the `test_what_is_late.py` red window (00:00–05:30 local), consistent with all
265 tests passing. An earlier run at 14:26 and another at 14:34 during this
same task also showed 265/265 for the same reason.

Recorded in `Dashboard/READMEs/08_PROGRESS_AND_HANDOFF.md` §2a and §5.

## Step 8 — checkpoint

- `python scripts/check_docs_in_sync.py` → exit 0.
- `python -m pytest tests/test_genericity.py -q` → 8 passed.
- `python scripts/check_hardcoded_strings.py` → exit 1, 2 pre-existing cosmetic
  findings, unchanged from before this task.
- `python -m pytest -q` → 265 passed, 0 failed, run at 14:59 local.

`09_BACKEND_CHANGES.md`: every row's Guards-green column ticked ✅; banner
updated to "Re-frozen: 2026-08-13."

`08_PROGRESS_AND_HANDOFF.md`: status table shows Phase 1 (T1–T10) all ✅ done;
Phase 2 (T11–T25) marked next; handoff note appended.

## Concerns

1. **`check_hardcoded_strings.py` does not exit 0.** The brief's Step 5 says
   "Expected: both pass," but the pre-existing condition documented in this
   task's context (2 cosmetic findings, present before this work) makes that
   literally unachievable without touching Android Java under `app/`, which is
   outside the closed change list and outside a docs-only task's mandate. I am
   treating "green" for this guard as "unchanged from its state before Task
   10, with the same 2 known, already-documented findings" rather than "exit
   0," and flagging the distinction explicitly rather than silently declaring
   success.
2. **§6's detailed per-route listing tables in `BACKEND_README.md` were not
   expanded** to include the 11 new routes' individual rows (method, path,
   access, used-by-app) — only the aggregate counts (top table, §7.1) were
   resynced, per the brief's stated file scope. The guard does not check this,
   so it does not block Phase 1, but it is a known accuracy gap for whoever
   next edits that section by hand.
3. **The `test_what_is_late.py` window was not exercised this run** — the run
   happened at 14:59 local, well outside 00:00–05:30, so the 3 clock-dependent
   tests were not observed failing directly in this session. Their behaviour
   is taken on the basis of the controller-supplied proof (patching
   `date.today()` to return the UTC date turned all 5 tests in that module
   green) rather than re-derived here, per the task's explicit instruction not
   to fix or re-investigate them.
