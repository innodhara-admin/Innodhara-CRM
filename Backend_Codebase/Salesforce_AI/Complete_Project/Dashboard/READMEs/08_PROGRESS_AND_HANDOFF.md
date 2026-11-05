# 08 · Progress and Handoff

> **This is the entry point. Read it before any other file in this folder.**
> It states where the work actually stands. `06_DESIGN.md` says what to build,
> `07_BUILD_PLAN.md` says in what order, `05_DECISIONS.md` says why.
>
> **The status table below is the authority.** If a paragraph anywhere — here or
> in any other document — disagrees with it, the table wins.

**Last updated: 2026-09-04.**

# ✅ Finished. Tasks 1–25, every box in `07` ticked.

**Nothing in *this plan* is outstanding.** This document is no longer a hand-off
mid-build; it is the record of a completed piece of work plus the short list of
things that are genuinely still unverified (§1.2).

> **A separate piece of work has since landed on top of it.** The **DOCX
> proposal-template subsystem** (2026-09-03/04, branch
> `feature/docx-proposal-templates`) reopened the backend freeze a fifth time and
> added a new editor to checklist item 6. It is **not** one of Tasks 1–25 and
> does not change their state. See the newest §5 hand-off note, and
> `09_BACKEND_CHANGES.md` §1a for the ten changes it made.

---

## What this is

**The Innodhara Setup Console** — a browser front end for the sixteen things an
organisation must have entered before the product will work, served by the
backend itself at `/dashboard/`.

It is **not** an admin panel with a dashboard home screen. The product *is* the
go-live checklist: a permanently visible rail of sixteen rows, each carrying a
status **derived from a live API read** and, where a row is not satisfied, the
product manual's own words for what breaks. The console never shows a status it
cannot verify — that single rule is what most of the design decisions defend.

| Screen | What it is for |
|---|---|
| `/dashboard/#/sign-in` | the two sessions: the platform operator, and an organisation admin |
| `/dashboard/#/orgs` | create an organisation — the D18 three-call hand-off, the one place a crash strands a tenant |
| `/dashboard/#/checklist` | **the product**: the rail, plus a screen for each of the sixteen items |
| `/dashboard/#/import` | CSV/JSON in bulk, with a per-row verdict before anything is sent, and a failures file to fix and re-feed |
| `/dashboard/#/go-live` | six computable checks over what was entered — *"will this actually work?"* rather than *"is it filled in?"* |
| `/dashboard/#/reset` | the destructive screen: four buckets, exact per-table counts, two confirmations |
| `/dashboard/#/bundle` | export nine entity types, reset, re-import — the reseed loop |
| `/dashboard/#/styleguide` | the primitives and the three enforcement voices |

**Phase 1 added ten backend changes and the list is closed at ten** (D24). No
Phase 2 task touches a file under `app/` — measured, not asserted: 151 routes,
55 tables and 755 columns are unchanged from the pre-Phase-2 baseline.

## Running it

```bash
cd Complete_Project && python run.py          # serves the console at /dashboard/
```

The bundle is committed (D10), so a plain checkout serves it with no build step.
Rebuild after changing anything under `Dashboard/src/`:

```bash
cd Dashboard && npm install && npm run build  # prebuild runs gen:check
```

Full commands, guards and traps are in **§3**. Read **§0** before trusting any
other document in this folder, and **§4** before debugging anything surprising.

## 0 · Before you trust anything else

**Seven** things in this folder will mislead a reader who takes them at face
value. They are listed here rather than fixed in place, because four of them
live in documents that are deliberately frozen. **This section is the first
thing to read and it has not gone stale with completion** — the frozen documents
still say what they said.

> **`00`–`04` are the frozen exploration record and their figures are
> deliberately NOT rewritten.** The `SUPERSEDED` headers on those files plus
> this section are the treatment. Everything below states what is true now; the
> frozen files state what was true when they were written, which is what makes
> them useful as a record.

### 0.1 · `00` and `03` are stale, and `05` vouches for them

`05_DECISIONS.md` says *"`00`–`04` are frozen as the exploration record. They are
still accurate about the code."* **The second sentence is no longer true.** Those
two documents were written before Phase 1, and Phase 1 added eleven routes.

| Stated in `00` / `03` | Actually |
|---|---|
| 140 routes · 138 under `/api/v1` | **151 · 149** |
| "only **3** DELETE endpoints exist in the entire API" (`00`, as evidence for the *nothing is destroyed* principle) | **11** — D2/D7 deliberately amended that principle |
| "the app calls 81 of the backend's 140 routes; **59** are unused" | **70** uncalled |
| method split "… 3 DELETE" (`03`) | 11 DELETE |
| `00` §RoleGate: "it maps **19 of the backend's 20**. `confirm_assignments` is missing" | **Fixed 2026-08-25.** `RoleGate` maps all 20, `HomeFragment` gates the assignment-batch card, and `RoleGateTest` now diffs the app's matrix against `permissions.json` so the next omission fails an Android build (note: that fixture is hand-maintained, not generated — see BACKEND_README §7.3) |
| `00` §files: "`FINDINGS.md` … findings **F1–F63**" | **F1–F69** (F18/F20/F21 never assigned) — 66 findings, **4 open** (F35, F54, F56, F67). Read `FINDINGS.md`'s new *"How to read the status table"* note before trusting any single cell |

**`03` and `02` also still flag gaps that Phase 1 closed**, with the 🔴 *no
endpoint exists* marker: `GET /playbooks` (change #3), `DELETE /skills` and the
program / pricing-version deletes (change #6), `GET /vendors` missing three
fields (change #7), `email_integration_configured` reporting `true` while mail
goes to a file (change #2), and `require_action_item_review` "not returned"
(changes #1/#4). All exist or are fixed.

`03` §6.3 (Idempotency) is wrong in a way `03` does not admit: the server reads
no headers at all. See D17 and `06` §4.1.

### 0.2 · Twelve sections of `06` have been superseded by execution

`06` is the spec and is still right about intent, but it contains **no reference
to P1–P14 or A1–A8** — the findings made while building, which live in
`07_BUILD_PLAN.md` §Phase 2. **Do not build a screen from `06` §3 or §5.2
without reading this table first**; four of the eight rows below are places
where following `06` literally produces a console that states something untrue.

| `06` says | Replaced by | Because |
|---|---|---|
| §3.1 field names, types **and response shapes** come from the generator and are "never hand-typed" | **P1 / A1** | 11 of the 15 reads return `"schema": {}`; `src/api/reads.ts` is hand-written and pinned by fixtures |
| §3.3 enforcement has **two** values, `backend` / `ui-only` | **P2 / A2** | Three. The generator drops 16 console-relevant constraints, which are enforced but not declared |
| §5.2 item 1 reads `GET /orgs` | **P6 / A5** | `GET /orgs` is super-admin-only; item 1 derives from `GET /auth/me` |
| §5.2 item 10 — "any dial differs from its model default ⇒ `●`" | **P11** | `POST /orgs` seeds **three dials from the server's environment**, so a brand-new org ticks green with nobody having opened the screen. `ENV_SEEDED` carves those three out |
| §5.2 item 12 — "always satisfied; the current windows are shown" | **P12** | It can **never** be verified. Item 12 reads only the two retention columns, both seeded from env vars **no route returns**, so `◐` for every input — not `●` |
| §7.1 change #8 and §8.1 imply `StaticFiles(html=True)` serves `index.html` for unknown sub-paths | **P10 / A8** | It does not — only for a directory URL. The console uses **hash routing** |
| §7 "**Eight**, all additive. The list is closed" | **D24** | Closed at **ten** |
| §3.4 / §4 "**eleven** entity modules" | — | Eleven descriptors, in **three** files: `staff.ts`, `catalogue.ts`, `governance.ts` |
| §5.7 "per-table counts under **three** headings" | **Task 24** | Four. `KEEP` is a real bucket of the taxonomy and no reset response mentions it, so the screen shows it with its tables and **no counts** rather than omitting it |
| §5.7's D6 quote — "the **twelve** engine-only tables" | **P17** | `03_API_SURFACE.md` §4.2, which `04` Q13 cites for the figure, lists **fourteen** — Q13 drops `memory_chunks` and `lead_state_history` |
| §5.8 / Task 24 Step 4 — nine entity types, "all of them faithful", no exceptions named | **P18** | Programme **ids** do not survive the reset the bundle undoes, and two of the nine take their programme in the URL. The bundle carries the programme **code** |
| §5.6 check 4 — flag when no catch-all `{}` rule exists | **P15** | The flag is right; the implied consequence is not. `find_rule` returning None hands the decision to the **caller's** `default_approver_role`, and the nine call sites disagree — `proposal` and one `plan_change` path apply it **unreviewed** |

**Five more findings have no `06` section to contradict, and are recorded here
because nothing else points a cold reader at them:**

- **P15 — "no catch-all" does not cost the same for every entity type.**
  `find_rule` returning None hands the decision to the *caller's*
  `default_approver_role`, and the nine `request_approval` call sites disagree:
  seven name `sales_lead`, but `proposals.py` and one `planner_engine` path pass
  `None` and apply the thing **unreviewed**. Item 9's caption said "a request
  matching none of them has no approver", which is wrong in both directions at
  once; corrected, with a `notCaption` case pinning the removed phrase. The
  per-type table is **generated** (`APPROVAL_NO_RULE`), not transcribed.
- **P16 — `POST /orgs` does not apply the domain rule it creates.**
  `register_staff` refuses an address outside `org.email_domain`;
  `create_organisation` applies no such test to `admin_email`. So the first
  administrator is the one account that can legitimately sit outside the domain,
  and check 6 names that exception where it finds it instead of hiding it.

- **P13 — a server refusal that instructs the impossible.** `delete_program`
  ends its refusal *"Mark it inactive instead"*, and **no route writes
  `Program.is_active`**. §4.1's rule is that refusals are rendered verbatim, so
  a screen that quotes it and stops **inherits the lie**. The standing rule:
  **quote it, then contradict it — never quote it alone.** `09` §4a has the
  finding and the eventual fix.
- **P14 — four generated templates did not validate against their own
  validator.** Found by a round-trip test, not by review. Anything this console
  *generates for an operator* must be fed back through the thing that reads it;
  `import/validate.test.ts` does that on every run.
- **A7 — the import column check must run BEFORE Zod.** Every generated schema
  is `.passthrough()` (P9), so an unknown column validates clean and writes a
  row with the field you meant left empty. `.strict()` is not the fix: the
  schemas are regenerated from the backend, and a field the backend *adds* must
  not break a running console. The check lives in `import/validate.ts`, as this
  console's own rule.

### 0.3 · `04`'s questions are all answered

`04_OPEN_QUESTIONS.md` opens with *"None of these is resolved here"* and gives no
forward pointer. **All nineteen are answered in `05_DECISIONS.md`** — Q1–Q4, Q9
and Q13 in Part 1, Q5 by D2, Q18 by D15, and the rest in Part 4. `04` is also the
only place **Part F** is defined (§Part F), which `05` Part 3 relies on when it
lists what stays deferred.

### 0.4 · `09` §4a exists, and nothing else points at it

**Nine** known defects and one piece of future work are recorded **only** in
`09_BACKEND_CHANGES.md` §4a — **all of them post-Task-25, and every one needs
the change list reopened past ten**:

- **`playbook_suggestions.program_id` has no `ForeignKey`** — a bare NOT NULL
  `String(32)` naming `programs.id`. This is why D23 needs a declared exception
  list. Not fixed: it needs a migration and there is no Alembic.
- **`delete_program`'s refusal instructs the operator to do something
  impossible** (P13) — *"Mark it inactive instead"*, and no route writes
  `Program.is_active`. A **lying message**, not merely a missing route. Not
  fixed; the console quotes it and then contradicts it.
- **Retiring a programme that is in use** has no path at all — delete is
  rightly refused, deactivate has no route. Recorded as post-Task-25 work,
  **not** a defect in anything built here.
- `scripts/reset_for_datacentre_demo.py`'s "child-before-parent" comment was
  false for five edges — corrected to say so; the list itself is unchanged.
- `app/models/action_item.py`'s `external_wait` docstring named a `vendor_id`
  key no caller writes — corrected. **The vendor-delete guard that read that key
  was removed outright**, which `07`'s Task 20 Step 3 did not know; that step is
  corrected in place.
- **P15 — an approval that silently does not happen.** `find_rule` returning
  `None` hands the decision to the **caller's** `default_approver_role`, and the
  nine call sites disagree. `proposals.py:318` passes `None`, so an organisation
  with no catch-all `{}` rule for `proposal` — the state of every organisation
  that has not written one — has **every proposal set `APPROVED_INTERNALLY`
  with nobody asked**, reported as *"below every review threshold"*. `invoice`
  has **zero** call sites, so rules written for it can never fire. Not fixed;
  post-Task-25.
- **P17 — the reset screen's quoted warning undercounts itself.** `06` §5.7
  quotes D6's "the twelve engine-only tables"; `03` §4.2, which `04` Q13 cites
  for that figure, lists **fourteen**. Harmless in a design document and not
  harmless immediately above a destructive control, so `Reset.tsx` quotes it
  verbatim and then corrects it. Not fixed in `04`/`06`, which are frozen. **`06` §5.7 still
  reads "twelve" — the screen is the only place the figure is right.**
- **P18 — `BUNDLE_TRANSFORMS` is load-bearing, not plumbing.** One entry with a
  lambda in it is the shape of thing a later tidy-up deletes. Without it **every
  demo team in a reseed bundle is refused on re-import**: `member_ids` writes
  `["u1","u2"]` and reads back `[{id, name}]`, and an alias renames a field
  where a *conversion* is needed. `_program_code` is in `09` §4a for the same
  reason.
- **P16 — `POST /orgs` applies no domain test to `admin_email`** while
  `register_staff` refuses any staff address outside `org.email_domain`. The one
  account created before the rule exists is the one account exempt from it, and
  it is permanent. Not fixed; post-Task-25.

### 0.5 · "Task 11" and "Task 12" mean two different things

In **`09`** they are the post-Phase-1 amendment tasks (the skill-guard fix; D23).
In **`07`** and in this file's status table they are the Phase 2 scaffold and the
design tokens. When citing one, say which file it comes from. `09`'s header
carries the same warning.

### 0.6 · `07`'s checkboxes are now meaningful again

They were all unticked while Tasks 1–15 were complete, so the plan read as though
nothing had started. **Every box in `07` is now ticked — Tasks 1–25.** The
status table below remains the authority.

### 0.7 · `02` disagrees with itself about which tier item 8 is in

Task 16 had to place all sixteen rows in a tier and found the source ambiguous.
The manual's counts are **Essential 7 · Strongly recommended 4 · Optional 4** over
the fifteen items 2–16 (item 1 sits outside them, at platform level), and fifteen
items with those counts admit exactly one split: **2–8, 9–12, 13–16**. That is
what `06` §5.1 and `07` Task 16 both say, and it is what `items.ts` implements.

`02` agrees in its §0 dependency diagram, which puts item 8 (playbooks) in
`TIER 2 — the catalogue`, hanging off item 4's `program_id`. It disagrees in two
other places: §8's markdown heading sits under `TIER 3 — Governance & behaviour
("strongly recommended")`, and its closing summary table marks item 8
"Recommended". **The §0 diagram is the one that matches the arithmetic.** `02`'s
tier *headings* are dependency tiers wearing the manual's tier names, which is
where the collision came from. `02` is frozen, so this is recorded rather than
fixed there.

> **Guard state, stated exactly — UPDATED 2026-08-25.**
> `check_hardcoded_strings.py` now **passes: exit 0, 0 findings.**
>
> When this was written it failed with 2 cosmetic Android-Java findings
> (`LoginFragment.java:101`, `SplashFragment.java:48`), matching the pre-work
> baseline `19efa98`. Both have since been fixed in the Android repo — the two
> lines now read `getString(R.string.login_server_chip, …)` and
> `getString(R.string.splash_version, …)`, so the literals live in `strings.xml`
> where the guard wants them. That happened outside this project, alongside
> [F36], which is why nothing here recorded it.
>
> **So "all the guards are green" is now TRUE, and may be written** — measured
> 2026-08-25, not recalled. The instinct behind the old wording is still the
> right one: state the guard's actual exit code, never a summary of it.
>
> ⚠ **One caveat that has not changed and matters more than the result:**
> `check_hardcoded_strings.py`'s default path is the Android project under
> `AndroidStudioProjects/YuvipepSalesforceAI/app/src/main` — **outside this
> repository**. There are zero `.java` files under `Complete_Project` and git
> tracks none, so on CI or any other machine this guard prints
> `[SKIP] no Java sources` and **exits 0 having checked nothing**. A green
> result is only meaningful on a workstation that has the Android project
> checked out at that path.
>
> **Every screen has been reviewed in a browser, in both themes** — Tasks 12,
> 16–20 on 2026-08-17, then go-live, reset and the bundle on 2026-08-18, and
> finally the whole console driven end to end as an operator in Task 25.
> **Thirteen defects came out of those reviews and every one is fixed**, several
> of a class no test could have caught: a focus trap that looked contained and
> was not, a comparison against a styles object that could never be true, and
> markdown rendering as punctuation above a destructive control.
>
> **The one that matters most was verified by hand, as `07` Task 19 Step 5
> demands:** credentials were stored through the console against a server
> running `EMAIL_MODE=dry_run`, and item 11 **stayed `◐`** — *credentials stored
> · sending is OFF on this server (EMAIL_MODE=dry_run) — approved messages are
> written to a file*. The API agreed: `email_credentials_stored: true`,
> `email_integration_configured: false`.
>
> **Three things are still unverified and they are listed in one place — §1.2.**
> The narrow viewport, the sign-in field and the hand-off's step 3. Nothing else
> on this console is unexercised.

Measured 2026-08-18, after Task 25 — the final figures **for that day**.

> ⚠ **These are a dated record, not current state.** Re-measured 2026-08-25:
> **pytest 335** (was 272 — the backend gained tests for the one-clock work, the
> `auto_approve` fence and the orphaned-audio fix), `npm test` **630** (was 622 —
> `baseUrl.test.ts`), and `check_hardcoded_strings.py` now **exits 0**. The
> figures this console owns — 151 routes, 55 tables, 755 columns — are unchanged,
> which `check_docs_in_sync.py` still asserts on every run. **The route count is
still 151**, and 55 tables / 755 columns are unchanged from the pre-Phase-2
baseline: no Phase 2 task adds an `APIRoute` or touches a file under `app/`,
confirmed by running `check_docs_in_sync.py` rather than assuming it.

| Guard | State |
|---|---|
| `check_docs_in_sync.py` | ✅ exit 0 — *"the three documents agree with the code"*, **151 routes** |
| `tests/test_genericity.py` | ✅ 8 passed |
| `python -m pytest` | ✅ **272 passed, run at 12:22 IST on 2026-08-18** — past the 00:00–05:30 window, so no `TZ=UTC` was needed and nothing was deselected. No Phase 2 task touches a file under `app/` or `tests/`, and the count is unchanged from Task 10. |
| `check_hardcoded_strings.py` | ✅ exit 0, 0 findings **as of 2026-08-25** (was ❌ 2 pre-existing Java findings when this table was written; both since fixed in the Android repo). ⚠ Scans a path *outside this repo* — see §0 |
| `cd Dashboard && npm test` | ✅ **622 passed** across 16 files — the jump from 324 is **prose 298**, which is one case per rendered string rather than 298 new ideas |
| `cd Dashboard && npm run build` | ✅ `tsc --noEmit` clean, bundle written to `dist/` |
| `cd Dashboard && npm run gen:check` | ✅ *"all four generated artefacts match the backend"* |

---

## 1 · Status

| Phase | Task | State | Evidence |
|---|---|---|---|
| — | Exploration (`00`–`04`) | ✅ done | 5 documents, all figures computed |
| — | Decisions (`05`) | ✅ done | D1–D24; backend list closed at **ten** (D24) |
| — | Design (`06`) | ✅ done | 12 sections, reviewed twice |
| — | Build plan (`07`) | ✅ done | Tasks 1–25 detailed; **every box ticked** |
| 1 | T1 · Staff fields + staff detail | ✅ done | `09_BACKEND_CHANGES.md` §5, change 1 |
| 1 | T2 · Honest delivery mode | ✅ done | `09_BACKEND_CHANGES.md` §5, change 2 |
| 1 | T3 · `GET /playbooks` | ✅ done | `09_BACKEND_CHANGES.md` §5, change 3 |
| 1 | T4 · Widen `GET /vendors` | ✅ done | `09_BACKEND_CHANGES.md` §5, change 7 |
| 1 | T5 · Reset taxonomy + partition guard | ✅ done | `app/core/reset_taxonomy.py`, `tests/test_reset_taxonomy.py` |
| 1 | T6 · `POST /admin/reset` | ✅ done | `09_BACKEND_CHANGES.md` §5, change 5 |
| 1 | T7 · Guarded deletes — `ops.py` | ✅ done | `tests/test_dashboard_deletes_ops.py` 7/7 |
| 1 | T8 · Guarded deletes — `admin.py` | ✅ done | `tests/test_dashboard_deletes_admin.py` 6/6 |
| 1 | T9 · Conditional static mount | ✅ done | `tests/test_dashboard_mount.py` 2/2 |
| 1 | T10 · Docs resync + all guards green | ✅ done | four guard commands below, all green |
| 2 | Task-level detail for T11–T25 | ✅ done | `07_BUILD_PLAN.md` §Phase 2, written from the live spec + the generator actually run |
| 1b | T10a · change #9 — `GET /approval-rules` widened | ✅ done | commit `1e8287f`, `tests/test_dashboard_reads.py` 6/6 |
| 1b | T10b · change #10 — `GET /admin/demo-teams` widened | ✅ done | commit `2dfaaaf`, `tests/test_dashboard_reads.py` 8/8 |
| 1b | T10c · resync + re-freeze at ten | ✅ done | `05` D24, `09` freeze history row 4, guards below |
| 2 | T11 · Scaffold + generation pipeline | ✅ done | `Dashboard/`, 4 generated artefacts, `gen:check` proved failing |
| 2 | T12 · Design tokens + primitives | ✅ done | `ui/tokens.css`, 14 primitives, `/#/styleguide`, 6 token guards |
| 2 | T13 · Client + session + router | ✅ done | `api/client.ts`, dual token store, hash router, `npm test` 34/34 |
| 2 | T14 · Org creation + chained hand-off | ✅ done | `session/handoff.ts`, D18 modal 3 states, `npm test` 47/47, chain replayed live 12/12 |
| 2 | T15 · Descriptors + read shapes + drift tests | ✅ done | 11 descriptors, `api/reads.ts`, 13 live fixtures, `npm test` 102/102 |
| 2 | T16 · Checklist rail + status derivation | ✅ done | `checklist/items.ts`, `status.ts`, `ui/Rail.tsx`, 55 status tests, driven live in Chrome |
| 2 | T17 · Staff and skills (items 2–3) | ✅ done | `EntityForm`, `FormatPanel`, 3 screens, 19 validation tests, guard refusal seen live |
| 2 | T18 · The catalogue (items 4–7) | ✅ done | 4 screens, `VersionHistory`, promote-on-delete seen live, items 4 and 7 green |
| 2 | T19 · Governance and behaviour (items 8–12) | ✅ done | 5 screens, `JsonField`, `IntegrationPanel`; item 11 held `◐` with credentials stored |
| 2 | T20 · Optional (items 13–16) | ✅ done | 4 screens; **all sixteen rows now have one** |
| 2 | T21 · Import — parse, validate, preview, template | ✅ done | `import/parse.ts`, `validate.ts`, `template.ts`, `Import.tsx`; 32 tests; **P14** — the round-trip caught four broken templates |
| 2 | T22 · Import — apply and the failures file | ✅ done | `apply.ts`, `failures.ts`, `ImportResult.tsx`; 22 tests; the D21 loop closed live, 8 rows → 5/3 → fix → 3/0 |
| 2 | T23 · The go-live check | ✅ done | `checklist/golive.ts`, `screens/GoLive.tsx`, 37 tests; **driven live against a real gap** by `tools/verify_golive_live.ts` |
| 2 | T24 · Reset and the reseed bundle | ✅ done | `bundle/reset.ts`, `export.ts`, `import.ts`, 2 screens, 50 tests; **the loop closed live, and D22 refused a real catalogue-only reset** |
| 2 | T25 · Build, mount, verify | ✅ done | mount + deep-link matrix measured, every guard re-run, **the console driven end to end as an operator**; `ui/prose.test.ts` |

**All twenty-five are done.** The three things still unverified are in **§1.2**,
and they are the whole list.

**Next action: none in this plan.** Tasks 1–25 are complete, and every branch is
merged into `master`. What is left is **recorded rather than scheduled**: `09`
§4a's nine findings and the programme-retirement note are post-Task-25 work, and
**every one of them needs the backend change list reopened past ten.**

---

## 1.2 · What is genuinely still unverified

**Three things, and they are the whole list.** Everything else on this console
has been driven against a live backend and reviewed in a browser in both themes.
None of the three is a defect; each is a check that could not be made here.

### 1 · The narrow viewport has been read, not seen

The `@media (max-width: 60rem)` breakpoint — where the rail stops being a
sidebar and becomes a page header, because hiding the checklist would hide the
thing the operator is working through.

**What is verified**, by rewriting the live rule's `conditionText` so it matched
and observing the result: the declarations inside that block produce the intended
layout — the rail goes `static` with no `100vh` cap, the shell collapses to one
column, the field grid goes single-column, and the body does not scroll sideways.

**What is not**: that the breakpoint fires at 60rem on a real narrow window.
`resize_window` reported success three times while `window.innerWidth` did not
move, and **the owner has instructed that it not be attempted again** — they will
check a real narrow viewport by hand. **The declarations are checked; the
breakpoint firing is still only read.**

### 2 · The sign-in field · 3 · The hand-off's step 3

The two screens that take a password have **never been driven through their own
form fields**, because entering a password into a field is not something this
assistant does, even on localhost.

Everything either side of both is verified:

- **Sign-in** — every org-admin session used in every browser review was minted
  through `POST /auth/login` the same way `tools/capture_fixtures.mjs` mints one,
  then written into `sessionStorage`. The route, the token store and every screen
  behind it are exercised; the form's own submit is not.
- **The hand-off's step 3** — the three-call chain (`POST /orgs` →
  `POST /auth/login` with the temp password → `POST /auth/change-password`) was
  replayed against the live server 12/12 in Task 14, including the part that
  matters: the chosen password signs in, `must_change_password` flips to false,
  and **the temporary password then returns 401**. The modal's three states were
  reviewed in a browser from the styleguide. The password box itself is untyped.

**To close all three:** open the console at a narrow window, and sign in at
`/dashboard/#/sign-in` as the platform operator, then create an organisation
through `/#/orgs`. Nothing else is outstanding.

---

**Look at it:** `http://127.0.0.1:8000/dashboard/` (rebuild with
`cd Dashboard && npm run build` after any change; the backend needs restarting
only if `dist/` did not exist when it started).

> ⚠ **Chrome caches `dashboard/index.html`, and the asset names are hashed.** A
> rebuilt bundle can therefore appear to have changed nothing at all — the page
> keeps loading the previous CSS and JS. This cost a wrong conclusion once in
> Task 16. Check with
> `[...document.querySelectorAll("link[rel=stylesheet]")].map(l => l.href)` and
> compare against `dist/assets/`; `?v=<n>` on `index.html` forces the reload.

> **The two escalations are CLOSED.** The owner reopened the change list for
> **exactly two** read widenings and it is **re-frozen at ten** (D24). Both were
> the same defect the project had already ruled on twice — a write path with no
> read path — and both are pure response widenings:
>
> - **#9** `GET /approval-rules` now returns `fallback_role` and `auto_approve`.
> - **#10** `GET /admin/demo-teams` now returns `lead_user_id` / `media_rep_id` /
>   `sales_rep_id` **alongside** the existing `lead` / `media_rep` / `sales_rep`
>   names, which stay because the Android app calls this route and may render
>   them (rule 1 of `09` §2 is additive-only).
>
> **Route count stayed 151** — confirmed by running `check_docs_in_sync.py` after
> both landed, not assumed. Four warnings and two `notReadable` lists came out of
> `07`'s Tasks 15, 19, 20, 23 and 24 as a result, and Task 24's round-trip test
> strengthened to nine faithful entity types with no exceptions.

---

## 2 · Baseline, measured 2026-08-13 — pre-Phase-1 (commit `19efa98`)

Kept for reference: what the code looked like before any of the eight changes
landed.

| Figure | Value | How |
|---|---|---|
| Tables | 55 | `Base.metadata.tables` |
| Columns | 755 | same |
| Routes (incl. 2 health) | 140 | `APIRoute` count on `app.routes` |
| Routes under `/api/v1` | 138 | decorator count in `app/api/*.py` |
| DELETE routes in the whole API | 3 | `assistant.py`, `ops.py`, `projects.py` |
| Routes the Android app does not call | 59 | `check_docs_in_sync.py` §7.1 |
| pytest | 218 collected, 215 passing, 3 failing | measured against commit `19efa98` |
| Reset taxonomy partition | KEEP 4 · CONFIG 2 · REPLACE 7 · WIPE 42 = 55 | verified against `Base.metadata` |

## 2a · Measured 2026-08-13 after Task 10 (HEAD `7704eef` + docs commit)

> **This section is no longer "current" and the heading used to say it was.**
> It is a dated snapshot taken at the end of Phase 1. Everything structural in
> it still holds — nothing since Task 10 has touched `app/` — but the **test
> count has moved: 265 → 272**. The guard table in §0 carries the live figures.
> Re-measured 2026-08-18 and unchanged: 151 routes (149 under `/api/v1`), 11
> DELETE, 55 tables, 755 columns, KEEP 4 · CONFIG 2 · REPLACE 7 · WIPE 42 = 55.

Everything here was computed, not recalled, by the run recorded in
`.superpowers/sdd/07_BUILD_PLAN/task-10-report.md`. Re-measure rather than
trusting these if more than a few days have passed.

| Figure | Value | How |
|---|---|---|
| Tables | 55 | `Base.metadata.tables` (unchanged) |
| Columns | 755 | same (unchanged) |
| Routes (incl. 2 health) | **151** | `check_docs_in_sync.py` printout |
| Routes under `/api/v1` | 149 | `140 - 2 health + 11 new`, `/api/v1` unchanged elsewhere |
| DELETE routes in the whole API | **11** | 3 pre-existing + 8 guarded deletes (T7 + T8) |
| Routes the Android app does not call | **70** | `check_docs_in_sync.py` §7.1 (Organisation administration 25, Operations and money 20, unchanged: Everything else 13, Platform / Super Admin 4, Incidents 3, Approval rules 3, Device push registration 2) |
| pytest | 265 collected, 265 passing at time of run | run at 14:2x local, past the `test_what_is_late.py` 00:00–05:30 window — see §4 item 8 |
| Reset taxonomy partition | KEEP 4 · CONFIG 2 · REPLACE 7 · WIPE 42 = 55 | unchanged, `tests/test_reset_taxonomy.py` |

`BACKEND_README.md` is resynced to these figures. `check_docs_in_sync.py` now
exits 0.

---

## 3 · How to run things

```bash
# backend (default port 8000; PORT=9010 in the demo runbook is an override)
cd Complete_Project && python run.py

# the whole suite
python -m pytest -q

# the three python guards
python scripts/check_docs_in_sync.py
python -m pytest tests/test_genericity.py -q
python scripts/check_hardcoded_strings.py

# the console. node_modules/ is gitignored, so a fresh checkout MUST install
# first — without it gen:check, npm test and npm run build all fail.
cd Dashboard && npm install
npm test                    # the twelve Vitest suites
npm run gen:api             # regenerate the four artefacts from the backend
npm run build               # prebuild runs gen:check, then writes dist/
# the backend then serves it at http://127.0.0.1:8000/dashboard/#/sign-in

# the go-live check, against a LIVE organisation rather than the fixtures.
# Seeds a real org with a real gap, asserts, and deactivates on the way out.
# --keep leaves it active so the same data can be opened in a browser.
npx vite-node tools/verify_golive_live.ts -- --base http://127.0.0.1:9010 [--keep]

# reset + the bundle loop, live. Seeds an org WITH A REAL PROPOSAL so D22 has
# something to refuse, then export -> reset -> re-import and checks change #9's
# auto_approve and change #10's three role ids survived.
npx vite-node tools/verify_reset_bundle_live.ts -- --base http://127.0.0.1:9010 [--keep]
```

> ### `.gitattributes`'s exclusions are load-bearing — do not tidy them away
>
> The repository normalises everything to LF (`* text=auto eol=lf`), because two
> sessions running turned a 25-line docs edit into a 653-line diff by writing a
> README from Python on Windows. **Five paths are deliberately excluded with
> `-text`, and they look like oversights.**
>
> - **`*.patch`** — a patch file's bytes **are** its content. The `+`/`-` lines
>   describe exactly what to write, so normalising them changes what applying
>   the patch produces. One is tracked today,
>   `scripts/assets/erd/0001-regenerate-er-diagram.patch`, and it is mixed
>   (790 CRLF / 590 LF) on purpose — left exactly as it is.
> - **The four artefacts `npm run gen:api` writes** —
>   `Dashboard/src/api/openapi.json`, `generated.ts`, `constraints.generated.ts`
>   and `vocabularies.generated.ts`. `npm run gen:check` compares them
>   **byte-for-byte** against a fresh regeneration, which is the whole reason it
>   is a guard rather than a formality. Their line endings belong to the
>   generator that writes them — `dump_openapi.py` emits CRLF on Windows — not to
>   `.gitattributes`. **Normalising them to LF broke `gen:check` the moment it
>   was tried** (commit `7721d20` exists only to undo exactly that), and it
>   breaks `npm run build` with it, since `gen:check` is the `prebuild` step.
>
> Regenerate those four with `npm run gen:api`; never hand-edit or reformat them,
> and never "fix" their line endings. A later tidy-up that removes these five
> lines will look like housekeeping and will fail every build.

> ⚠ **Check what is answering the port, not whether something is.** On this
> machine an unrelated FastAPI app ("Ekagni AI ML") holds **:8000** and returns
> 200 on `GET /health`, so a live run against it fails at
> `POST /auth/login → 404` and looks like a routing bug. `curl :PORT/openapi.json`
> and read the `info.title`. Task 23's live run used `PORT=9010`.

> ⚠ **`node tools/capture_fixtures.mjs` writes to the live database.** It reads
> `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` from `Complete_Project/.env`,
> **creates a real organisation**, seeds one row in every entity, captures the
> 13 fixtures, and deactivates the organisation on the way out. It does not
> delete it — `POST /orgs` has no inverse. Only run it when the read shapes have
> actually changed, and expect a `fixtures-<timestamp>` row to remain in `GET
> /orgs` afterwards. Eight such rows exist already (`verify-9-10-*`, `handoff-*`,
> `fixtures-*`, and `t16-*` / `t1718-*` / `t1920-*` / `t21-*` / `t22-*` from the
> browser reviews), all deactivated. **`t22-*` holds ten real staff accounts** —
> Task 22's checkpoint writes bulk data, which is what it exists to prove. The `t1718-*` one also holds two `action_items` rows inserted
> straight into SQLite to arm the skill-delete guard — the guard needs open work
> needing the skill, and no console route can create any.
> **Deactivating is the only cleanup there is, and it must come last:**
> `deps.py · get_org_context` refuses an inactive organisation (`:61`), so a
> review org deactivated before the browser check 403s every read the rail makes.

**Running the console needs a session, and this assistant cannot make one:**
entering a password into a form field is off-limits, so the credentialed
sign-in has to be done by a human. Sign in at `/dashboard/#/sign-in` as the
platform operator to reach org creation.

**This repository is under git as of Phase 1. Everything is on `master` and
there is no live feature branch** — Phase 2 closed with Task 25. Each task landed
on its own branch and was merged back with `--no-ff` at the phase boundary, so
the log shows the shape of the work rather than a flat line: `1b8f3f7` Tasks
11–16, `7f0d31c` 17–18, `f286db2` 19–20, `ecc9924` 21–22, `0c1ef41` 23,
`b0b2168` 24, `ac1a2bb` 25. Measured with `git merge-base --is-ancestor`, not
recalled:

| Branch | Head | State |
|---|---|---|
| **`master`** | `ac1a2bb` merge | **everything** — Phase 1, Phase 1b (#9/#10) and Tasks 11–25 |
| `feat/console-golive-verify` | `621bcb5` | fully merged (Task 25) |
| `feat/console-reset-bundle` | `8521c25` | fully merged (Task 24) |
| `feat/console-go-live` | `e99f088` | fully merged (Task 23) |
| `feat/console-import` | `5e03aee` | fully merged (Tasks 21–22) |
| `feat/console-governance-optional` | `21be1bb` | fully merged (Tasks 19–20) |
| `feat/console-item-screens` | `b703e6a` | fully merged (Tasks 17–18) |
| `feat/backend-changes-9-10` | `6f4427f` | fully merged; holds nothing `master` does not |
| `feat/setup-console-phase1` | `b6d3470` | fully merged; superseded long ago |
| `fix/d23-bare-reference-guard` | `10cd2e3` | fully merged |

**Every feature branch is an ancestor of `master` and carries no unique
commits.** `master` is the branch to be on.
 They are kept rather than deleted only because nobody asked for them
to go; `git branch -d <name>` will remove any of them without a warning, which
is itself the proof they are merged.

`feat/backend-changes-9-10` was never renamed after its scope grew past changes
#9/#10, so its name badly understates what it ended up holding. Each task landed
as its own commit; `git log --oneline --graph` has the per-task history.

> ### The branch rule, because it was broken twice — and still applies
>
> **Work happens on a feature branch off `master`. The branch is created BEFORE
> the first edit, and merged back with `--no-ff` at the phase boundary.**
>
> Not after the first edit, not once the work looks worth keeping — before. Two
> sessions in a row began editing on `master` and had to move the working tree
> to a branch afterwards. It came out clean both times because the changes were
> still uncommitted, and that is luck rather than process: the recovery is only
> available while nothing has been committed, and there is no signal that tells
> you which state you are in until you look.
>
> `--no-ff` is deliberate even when a fast-forward is possible, so the merge
> commit marks where a phase ended and the log shows the shape of the work
> rather than a flat line.

---

## 4 · Things that will bite

Recorded because each one has a non-obvious failure mode.

1. **The pytest fixtures `org_a` / `org_b` are session-scoped.** Any test that
   calls the reset endpoint against them wipes data every later test depends on,
   and the failure surfaces in an unrelated module. **Reset tests create their own
   org with `create_org(...)`.**
2. **`check_docs_in_sync.py` counts `APIRoute` instances**, so the StaticFiles
   mount is free but all eleven new routes are not.
3. **The genericity guards cannot see `Dashboard/`** — `check_hardcoded_strings.py`
   scans Android Java, `test_genericity.py` scans `app/**/*.py`. **Keep the bundle
   at `Dashboard/dist/` and the dumper at `Dashboard/tools/`.** Moving either
   under `app/` would start tripping a guard that is right to flag the manual's
   verbatim quotes in engine code.
4. **The server reads no `Idempotency-Key` header** — verified: CORS is the only
   middleware, no route reads a header. So no admin write is safe to retry, and
   the console never retries one. `03_API_SURFACE.md` §6.3 says otherwise and is
   wrong.
5. **`admin_temp_password` is returned once and recoverable from nowhere.** A
   crash between `POST /orgs` and the password change leaves an organisation with
   no reachable administrator. Task 14's modal is what stands between the
   operator and that.
6. **Never reopen the super-admin fence** (D1, Q14).
7. **`EMAIL_MODE`, `CALENDAR_MODE` and `INBOUND_EMAIL_MODE` are process-wide env
   vars.** `INBOUND_EMAIL_MODE` is open finding **F35** — keep it off.
8. **`tests/test_what_is_late.py` is clock-dependent, not flaky.** `assistant_engine.py`
   partitions "late" on `today_local = date.today()` (local date); the test
   helper `_task` builds due dates from `utcnow()` (UTC date). On this UTC+5:30
   machine those two dates disagree between **00:00 and 05:30 local**, so those 3
   tests — and only those 3 — fail in that window and pass the rest of the day.
   **Always record the local time of a suite run alongside its pass count.** Not
   fixed; it is outside Phase 1's closed change list (a one-line fix belongs in
   the test helper, not `assistant_engine.py`).

   > **Inside the window, run it under `TZ=UTC`** — measured at 00:54 IST on
   > 2026-08-18: `python -m pytest -q` gave 269/3, and `TZ=UTC python -m pytest -q`
   > gave **272 passed** on the same tree, same command, nothing deselected and
   > nothing patched. Setting the process timezone makes `date.today()` and
   > `utcnow().date()` agree, which is precisely the condition the helper assumes,
   > so it is a real green run rather than a way of hiding a red one.
   >
   > It is also the *stronger* evidence: it isolates the cause to the timezone
   > disagreement without touching a line of code. An earlier attempt to prove the
   > same thing by monkeypatching `datetime.date` was **invalid** — SQLAlchemy uses
   > `datetime.date` too, so the patch broke the DB layer and produced four
   > different failures. Do not repeat it.

---

## 5 · Handoff notes

*(Append one dated block per working session. Newest first. Say what changed,
what is now true, and what the next person should do first.)*

### 2026-09-04 — the DOCX proposal-template subsystem (fifth unfreeze)

**Not part of Tasks 1–25.** A separate, owner-directed piece of work on branch
`feature/docx-proposal-templates`, planned as its own 23 tasks. It is recorded
here because this file is the entry point and because it reopened the backend
freeze this document twice calls closed.

**What it is.** An administrator uploads the organisation's real branded `.docx`
at checklist item 6 instead of writing a Markdown body. The backend parses it,
OCRs its images, and an LLM proposes placeholders which a human accepts, rejects,
rewords or moves in a new console editor. At proposal time the backend loads the
**untouched source**, resolves system fields from the database, asks the model
for plain text for the prose placeholders only, and writes into a copy. The
source file is never rewritten: every proposal is
`source.docx + plan + values -> a new file`.

**Why it exists.** Three failures reported from real use: the model wrote its own
task list into a client's document; Markdown artefacts survived into the output;
and the rendered document had no branding at all, because `render_docx` starts
from a blank `Document()`.

| | |
|---|---|
| Backend | `app/services/docx/` (7 modules), `docx_template_service`, `docx_proposal_service`, `fill_scrub`, `ai/docx_suggest`, `ai/docx_prose` |
| Console | `Dashboard/src/screens/docx/` — upload, the placeholder editor, the token panel, the rate-card table mapping; one new route, `#/item/6/doc/:docId` |
| Android | `ProposalDetailFragment` gained a card naming which sections the AI wrote, which came from records, and which are **still blank** — those sort first |
| Recorded in | `09_BACKEND_CHANGES.md` §1a (changes 11–20), `05_DECISIONS.md` D25–D30, `BACKEND_README.md` §8.3 / §12 / §14 |

**What this changes about the documents in this folder.** Three statements that
were true when written are not any more, and each has been corrected in place
rather than left to mislead:

- `09_BACKEND_CHANGES.md`'s "the list is CLOSED at ten" — now records a fifth
  unfreeze, with the ten still closed as their own set.
- `05_DECISIONS.md` **Q17 · no Alembic**, previously "moot, no change adds a
  column" — the subsystem adds a table and three columns.
- `BACKEND_README.md`'s counts: **55 → 56 tables** and **151 → 157 routes**.

> ⚠ **A database on this branch needs three columns added by hand.**
> `proposal_templates.kind`, `proposals.filled_json`, `proposals.template_kind`.
> `create_all` makes the new table but never adds a column to an existing one,
> and there is no Alembic. Applied to the dev database on 2026-09-04, backup at
> `data/salesplatform.db.bak-docx-20260904`.

**State at the time of writing.** Backend `pytest -q`: **571 passed, 1 failed** —
that one failure is `tests/test_relationship_screens.py`, pre-existing and
belonging to an unrelated in-flight feature. Console: **688 passed / 18 files**,
`tsc --noEmit` clean, bundle builds. Android: `assembleOrgDebug` and
`testOrgDebugUnitTest` both green, 51 unit tests.

**What the next person should do first.** Two things are genuinely unverified,
and both are the same kind of gap as §1.2's:

1. **No screen of this feature has been rendered in a browser.** `tsc`, Vitest
   and a real Vite build pass, but this suite has no jsdom component tests by
   design (D11) and no dev server was started. Unexercised end to end: the
   upload flow, the suggestion round trip, the preview PDF, the image loading,
   and the leave-without-saving guard.
2. **There is only one way into the editor** — straight after an upload.
   `list_proposal_templates` returns no `doc_id`, so an administrator who
   uploads, leaves and comes back cannot reach the editor at all. Fixing it
   means adding `doc_id` to that read and regenerating the client. It is the
   difference between an editor and a one-shot wizard.

Full execution record, with every measurement and every defect found in the
plan's own reference code:
`.superpowers/sdd/2026-09-03-docx-proposal-templates-plan/progress.md`.

### 2026-08-18 — Task 25: build, mount, verify — Phase 2 complete

**Every box in `07` is ticked.** The console is built, served from the backend's
own mount, and driven end to end by hand.

**The deep-link case that motivated hash routing, finally seen rather than
reasoned about.** `/dashboard/#/go-live` opened in a **fresh tab with no
session**: the hash survives, the app boots, and the route renders its own
no-session state. Meanwhile every path-style link 404s —
`/dashboard/checklist`, `/go-live`, `/reset`, `/bundle` — which is **correct**
and is the whole of A8's argument. A path router would have worked perfectly
while clicking through and broken on every refresh, bookmark and shared link.
**If a path-style deep link ever starts working, someone has added an SPA
fallback, and that is an eleventh backend change.**

**Driven as an operator, not as a build check.** A fresh organisation, taken
through the rail:

| | |
|---|---|
| rail, before | ● 4 · ◐ 2 · ○ 9 · — 1 |
| staff, through the form | a wrong-domain address was **refused by the server and rendered verbatim**; corrected and created. Item 2 went ○ → ◐, naming the one account with no department |
| import, applied | a 5-row CSV with one bad row: apply **gated** — *"gated on zero problems, not on most of them"* — and the row flagged *"Must be one of intro, follow_up (admin.py · add_message_template)"*. Fixed → **4 applied · 0 refused**. Item 7 ○ → ● |
| delete, refused | the programme delete with a proposal against it: the server's words verbatim, then the console contradicting its last sentence. **P13 working live** |
| reset, previewed | four buckets, per-flag counts, **three blocking edges** from the real proposal, apply disabled with the reason |
| rail, after | ● 5 · ◐ 3 · ○ 7 · — 1 |

**The domain rule is a server-side fact, and the run proved it rather than
assuming it.** The wrong-domain address was *not* stopped by the form — it went
to the server and came back refused. That is right: the organisation's domain is
not something the client can know, and Task 22 already recorded it as such.

**P19 — markdown in prose reaches the screen as punctuation.** Two more
instances, both found by *looking*: `Staff.tsx` rendered a backticked `users`
beneath the account table, and `skills.quote` carried *"the neutral skill
`general`"* — which is `02` §3's **own markdown emphasis**, inside a quotation
§9 requires to be verbatim. A quotation carrying the emphasis of the document it
was transcribed *from* is not verbatim either.

**The guard for it is narrower than the problem, deliberately.**
`src/ui/prose.test.ts` checks prose that exists as **data** — the reset
constants, every descriptor field, every checklist item — which is exact. It
does **not** scan JSX text, and two attempts that did were worse than nothing: a
backtick pair in JSX is character-for-character a template literal, so telling
them apart needs a parser, and the guessing versions reported five correct files
as broken; an earlier pattern flagged eight correct captions by reading the
underscore in `super_admin` as emphasis. **A guard that cries wolf gets deleted
— and would take the exact half with it.** Watched failing by reintroducing both
defects: three tests went red, and green again on revert.

**Guard state, stated exactly.** `check_docs_in_sync.py` exits 0 with **151
routes, 55 tables, 755 columns** — unchanged from the pre-Phase-2 baseline,
because no Phase 2 task touches `app/`. `test_genericity.py` 8/8. Neither
genericity guard reacted to `Dashboard/`, which is D19 holding.
`check_hardcoded_strings.py` exited 1 at the time of writing with the same two
cosmetic Java findings it produced at commit `19efa98`. **Both were fixed in the
Android repo on or before 2026-08-25 and it now exits 0** — see the updated
guard-state note in §0, including why a green result from it means nothing on a
machine without the Android project.

**pytest: 272 passed at 12:22 IST.** `npm test` 622 across 16 files — the jump
from 324 is prose's 298, which is one case per rendered string rather than 298
new ideas. `gen:check` OK, `tsc --noEmit` clean, `dist/` rebuilt and committed
(D10 — it is deliberately not gitignored).

### 2026-08-18 — Task 24: reset, and the reseed bundle

**The destructive screen, and the loop that makes it survivable.** Reset at
`/#/reset`, bundle at `/#/bundle`, both derived in `bundle/reset.ts`,
`bundle/export.ts` and `bundle/import.ts` — pure, tested without a DOM, for the
reason this screen more than any other needs it.

**The preview needs TWO dry runs, and that is a property of the endpoint.**
`reset_organisation` returns `counts` for only the tables the flags it was
called with cover, and computes `blocking_edges` **only** when
`wipe_catalogue and not wipe_transactional`. Those pull in opposite directions,
so the screen makes an all-three call for the counts — the operator sees what
each flag *would* clear before ticking it, and the screen says so — and a
catalogue-only call for the edges, **always**, so D22's refusal is visible
before the combination is chosen rather than after.

**The fourth bucket has no counts, and that is the answer.** `KEEP` is
unreachable from `deletion_order`, so no reset response mentions
`organisations`, `org_settings`, `users` or `audit_log` at all. The bucket is
shown with its four tables and D16's reasons and **no numbers**, rather than
invented or hidden. `06` §5.7 says "three headings"; there are four.

**The 55 table names are generated, not retyped.** `dump_openapi.py` now emits
`RESET_TAXONOMY` — the four buckets by importing `app/core/reset_taxonomy.py`,
and the **flag → bucket** map by AST-reading `deletion_order`'s body, because
that is where it is decided. The failure mode this prevents is the quiet one: a
table missing from the console's list simply does not appear in the preview, so
the operator approves a reset having been shown less than it does. Two guards
watched failing — dropping `device_tokens` from `WIPE` fails the dump's own
partition check against `Base.metadata` (*"54 named, 55 tables"*), and pointing
`catalogue` at `CONFIG` fails `gen:check`. `app/` untouched; the list stays at ten.

**P18 — two things Step 4 does not mention, and either breaks the loop.**
`POST /admin/programs` mints a new id, so a bundle storing `program_id` restores
playbooks pointing at programmes that no longer exist — and `upsert_playbook`
does not check, so they would be stored in silence. And pricing and proposal
templates take their programme in the **URL**, so their write schemas have no
field for it at all. The bundle carries the programme **code** under
`_program_code` instead; `add_program` makes it unique per organisation. A third,
smaller one from the same reading: `demoTeams`' alias `member_ids → members`
renames a field where a **conversion** is needed — the read returns
`[{id, name}]`, the write wants `["u1","u2"]` — so without `BUNDLE_TRANSFORMS`
every demo team is refused on re-import. Watched failing.

**P17 — the quoted warning undercounts itself.** Every verbatim quotation on
these two screens was traced to a file in this repository, which is how this
surfaced: §5.7's D6 sentence says "the **twelve** engine-only tables", and
`03` §4.2 — the source `04` Q13 cites for that figure — lists **fourteen**,
adding `memory_chunks` and `lead_state_history`. All fourteen are in `WIPE`,
checked against the generated taxonomy. Harmless in a design document; not
harmless immediately above a destructive control. `Reset.tsx` quotes §5.7
verbatim, cites it, and corrects it in the console's own voice.

> **There is no product-manual quotation on either screen, and the absence is
> deliberate.** Reset is not one of the sixteen checklist items and the manual
> has no words for it. Task 23's first draft invented a plausible p.7 quotation;
> the same instinct here would have produced a fabricated warning at the one
> moment an operator is least able to check it.

**The whole loop, live against `t24-1787033081`** (since deactivated), with a
real proposal seeded via `POST /leads` + `POST /proposals` so D22 had something
real to refuse:

| | |
|---|---|
| four buckets | WIPE 42 tables · 6 rows · REPLACE 7 · 9 · CONFIG 2 · 3 · **KEEP 4 tables, no counts** |
| D22 at preview | **four** blocking edges, not the one predicted — `demo_team_members.team_id`, `proposals.pricing_table_id`, `proposals.program_id`, `proposals.template_id` |
| D22 at apply | refused verbatim, and **both programmes were still there afterwards** |
| bundle | 9 entity types · 12 rows |
| reset, all three | 18 rows removed · **all three staff accounts survived** |
| re-import | **12 restored · 0 refused** |
| change #9 | the restored rule is still auto-approving, with its fallback approver |
| change #10 | the restored team's three role ids are all still assigned |
| P18 | the restored programme has a new id; the playbook and rate card followed it |

**18 removed against 12 restored is correct arithmetic, not a loss** — the six
extra are `WIPE` rows the bundle deliberately does not carry, which is exactly
what D6's sentence on the screen warns about.

**`BUNDLE_ENTITIES.length` is nine, asserted rather than assumed.** The
post-Task-22 audit flagged it as unverified. It is derived —
`ALL_DESCRIPTORS.filter(d => d.inBundle)` — so the test asserts the derivation
lands on nine, that the nine are exactly §5.8's two rows, that the two
exclusions are `staff` and `settings`, and that **everything the bundle carries
the reset can clear and nothing else**, by mapping each entity onto its table in
the generated taxonomy. Three more guards were watched failing: emptying
`BUNDLE_TRANSFORMS`, exporting `program_id`, and removing the cross-organisation
`org_id` check.

**Two defects from the browser, neither findable from a test.** `BUCKET_NOTE`
carried markdown backticks and rendered *`users`* with its punctuation on screen
— now swept for across every user-facing string. And the blocking-edge banner
told the operator their selection was fine *because transactional data was also
ticked*, when in fact the catalogue box was simply unticked: right conclusion,
wrong reason, on the destructive screen. Both themes reviewed; console clean on
a fresh load.

**pytest: 272 passed at 11:40 IST** — past the clock window. `npm test` 324.
`gen:check` OK. `check_hardcoded_strings.py` still exits 1 with the same 2
pre-existing Android findings.

### 2026-08-18 — Task 23: the go-live check

**The screen that justifies the console rather than the sixteen forms.** Six
checks at `/dashboard/#/go-live`, derived in `checklist/golive.ts` — pure, over
the reads the rail has already fetched, in `status.ts`'s own four-marker
vocabulary. No score, no percentage, and **no "you are ready" verdict**: the
sheet reports and the operator signs off.

**Step 1 is a join, and that is the whole finding.** `GET /skills` returns
`user_id`, `skill`, `level` and **no activity flag**, so a set difference against
it reports a skill as covered when its only holder has been deactivated — the row
is still there. `ops.py · delete_skill` counts holders with
`User.is_active.is_(True)` and says in its own comment that this check has to
agree, "because two definitions of 'covered' is how the next divergence starts";
matching it means joining against `GET /admin/users`. Watched failing: with the
join removed, the deactivated-holder test reported `●`.

**Verified against a real organisation with a real gap, not a fixture.**
`tools/verify_golive_live.ts` (run with `vite-node`, so it can import
`runGoLive` itself rather than reimplement it) creates an org, seeds it
deliberately incomplete, deactivates the sole holder of `cable-management`, and
asserts three things together — the skill reads **uncovered**, a skill an
*active* person holds still reads **covered**, and `GET /skills` **still returns
the deactivated holder's row**. Without that third assertion the case is not
being exercised. Live against `t23-1787028485`, since deactivated:

| | |
|---|---|
| check 1 | `○` 1 of 3 skills covered |
| `cable-management` | `○` *"the only holder is deactivated (Priya Nair)"* |
| `power-commissioning` | `○` *"nobody holds it"* — a different sentence for a different defect |
| `rack-and-stack` | `●` *"held by Ravi Menon"* — the control, so the check is not simply failing everything |
| one entry with no `required_skill` | `○` — same outcome as uncovered (`_skill_map` returns `{}`), so it is counted |

**Two new findings, both from reading the backend rather than from a test.**

- **P15 — "no catch-all" does not cost the same for every entity type.** The
  nine `request_approval` call sites disagree about `default_approver_role`:
  seven name `sales_lead`, `proposals.py` and one `planner_engine` path pass
  `None` and apply the thing **unreviewed**, and `invoice` has **zero** call
  sites, so rules for it are dead configuration. **Item 9's caption said "has no
  approver", which is wrong in both directions at once** — corrected, and pinned
  by a `notCaption` case watched failing against the old wording.
- **P16 — `POST /orgs` applies no domain test to `admin_email`**, though
  `register_staff` refuses any staff address outside it. The administrator is
  therefore the one account that can legitimately differ, and check 6 says so at
  the row rather than excluding it silently.

**The per-entity-type table is generated, because nine hand-copied call sites go
stale in silence.** `dump_openapi.py` now AST-walks every `request_approval` call
under `app/` and emits `APPROVAL_NO_RULE` into `vocabularies.generated.ts`,
resolving `Role.X.value` against the real enum rather than string-munging the
attribute name. **Proved live rather than assumed**: changing `proposals.py`'s
`default_approver_role` to a role made `gen:check` fail with
*"vocabularies.generated.ts is not what the backend produces"*, and the reverted
tree passes. `app/` is untouched — the change list is still closed at ten.

**Four guards were watched failing before being believed**, each by breaking the
thing it guards: the active-only join, the shadowing check (rules ranked after a
catch-all can never fire — `find_rule` returns the *first* match), the domain
fallback's inability to be `●`, and per-phase playbook coverage. A fifth,
`APPROVAL_NO_RULE` keeping both kinds of fallback, failed once every `null` was
stubbed to a role.

**One real defect the tests did not find, and could not have.** A rule for an
entity type the backend never requests an approval for reported `●` — it has a
catch-all and a sensible rank, so it read as the healthiest row on the sheet.
`invoice` is that type. Now `◐` with *"nothing in the backend requests an
approval of this type, so these rules never fire"*.

**Reviewed in Chrome, both themes, and two legibility defects came out of it:**
the subject column broke `power-commissioning` across its own hyphen, and the
approval row read `10 when discount_pct_gt → sales_lead` — the rank and the
threshold, both unlabelled, with the threshold's value dropped entirely. Now
`rank 10 · when discount_pct_gt=10 → sales_lead (else org_admin)`. Console clean
on a fresh load; no page-level horizontal scroll; assets checked against
`dist/assets/` so the cache trap in §1 was not repeated.

**The manual's own words are on the screen and were not invented.** The first
draft carried a plausible p.7 quotation that does not exist in any source in this
folder. The real one is in `02` §3 — *"at least one person holds each skill your
rate card implies…"* — and check 1 is exactly that test, run against the data
instead of against a project.

> **A trap worth recording: port 8000 was answering, and not with this backend.**
> `GET /health` returned 200 from an unrelated FastAPI app ("Ekagni AI ML"), so
> the first live run failed with `POST /auth/login → 404`. **Check what is on the
> port, not whether something is.** The run used `PORT=9010` with
> `EMAIL_MODE=dry_run` / `CALENDAR_MODE=dry_run`, deliberately: the repo's `.env`
> has both live, and seeding an organisation is not worth the risk of real mail.
> Check 5 therefore shows the `dry_run` captions above, which is the honest
> reading of that server.

**pytest: 272 passed at 10:31 IST** — past the 00:00–05:30 window, so no `TZ=UTC`
was needed. Task 23 touches no file under `app/` or `tests/`.

### 2026-08-18 — Task 22: apply, and the failures file

**The first thing in this console that writes real data in bulk**, against a
backend with no bulk transaction and no idempotency. Three rules fall out of
that and all three are load-bearing: every row is attempted (D21), nothing is
retried (D17), and the server's refusal is carried verbatim into the report and
from there into the `_error` column.

**The continue-on-error test puts the failure in the middle, on purpose.** A
suite that only ever fails the last row passes against an applier that halts —
which is the exact bug D21 exists to prevent. Row 3 of 5 is refused and the
assertion is that rows 4 and 5 were **sent**, not merely that the counts add up.
Proved by making the applier `break` on failure: three tests went red.

**A gap between two modules that no test covered.** Swapping `source: row.source`
for `row.body` in `apply.ts` passed every test in `apply.test.ts` *and* every
test in `failures.test.ts` — the latter build their own outcomes, so neither
suite crossed the seam. It would have silently rewritten the operator's file on
every round trip: a blank cell coming back absent, `mon|tue` coming back as a
JSON array. Two tests now assert the seam directly, and were watched failing
against the swap.

**The plan's checkpoint named an entity that cannot fail.** Task 22 Step 5 asked
for *"10 vendors where 3 collide"* — and vendors have **no uniqueness of any
kind**, as this plan's own Task 20 Step 3 says. Ten vendors with three repeats
applies ten and demonstrates nothing. Corrected in place and done with `staff`,
which refuses a duplicate email *and* an address outside the organisation's
domain — two different refusals in one file.

**The loop closed live, end to end:**

| | |
|---|---|
| 8 staff rows, failures at **3, 5 and 7** | 5 applied · 3 refused · **all 8 attempted** |
| staff count | 2 → 7 |
| refusals, verbatim | *"User ravi@… already exists"* · *"Staff email must use your organisation's domain @…"* · *"User admin@… already exists"* |
| failures file | `staff-failures.csv`, original columns + `_error` |
| operator's edit | three addresses, in place — header and `_error` untouched |
| same file back in | recognised as a failures file, 3 ready, **3 applied · 0 refused** |
| and then | **no failures file offered** — the loop terminates |
| staff count | 7 → 10 |

All eight rows passed client-side validation first, which is the point of the
"what this preview cannot see" banner: a duplicate email and a wrong domain are
server-side facts.

> **A clean full-suite run, at last, inside the window.** `pytest` at 00:54 IST
> gives 269/3 on the machine's clock and **272 passed under `TZ=UTC`** — same
> tree, same command, nothing deselected and nothing patched. §4 item 8 now
> records that, and records that the earlier monkeypatch probe was invalid.

### 2026-08-18 — Task 21: import, as far as the preview

**A7 is implemented as an ordering, and the reason is written next to it.**
Column set first, then coerce, then Zod — because the other order does not work
at all. Every generated schema is `.passthrough()` (P9), so `unit_pirce` parses
clean, validates clean, and writes a rate-card line with no price. A test
asserts **both halves**: that the layer rejects it, and that the generated
schema on its own does not. If that second assertion ever fails, the generator
has started emitting `.strict()` and the check could in principle be dropped.

**The round-trip test earned its keep four times over — P14.** Feed each
entity's own template back through the parser and the validator and assert it
comes out clean: four templates failed, each differently, and none would have
surfaced until an operator downloaded one and had it rejected. The staff CSV's
`working_days` (`mon|tue|…` is not JSON); the same example carried into JSON as
a string rather than an array; the pricing JSON template built from *line*
columns, describing a body no route accepts; and the three JSON-only entities,
whose example the builder was inventing from field controls — producing a
playbook with no programme and an empty entry list.

All three fixes move in the same direction: **declare rather than guess.** The
pipe-delimited list is now a stated CSV convention (it was already the
project's — both list-bearing descriptors ship pipe-delimited examples — it
just had nowhere to be implemented). `csv.linesOf` names the field a CSV row
populates, rather than inferring it from whether the column set happens to
overlap the field names. And `jsonExample` gives the three JSON-only entities a
real worked example, because the honest fix for a bad guess is not a better
guess.

**The tri-state survives the whole path, and it was checked in a browser rather
than only in a test.** A three-line rate-card CSV rendered as
`default_quantity=4`, **no `default_quantity` key at all**, and
`default_quantity=0` — the three outcomes §3.3 exists to keep apart — with
`unit_price=0` surviving alongside as a real zero rather than a blank.

**One thing the preview does that no test asked for.** A CSV's unknown-column
error repeats on every row, and fifty identical messages bury the fifty
different ones underneath. The file-wide problem is hoisted into its own banner
with *"almost always the header line"*, and the rows below say "the file-wide
problem above" instead of restating it.

Also verified live: apply is disabled with the reason (`2 rows would have to be
fixed first`), a `_error` column is recognised and the file announced as a
failures file, the format list for `settings` comes from the descriptor and
offers JSON alone, and the proposal-template CSV template shows its quoted
embedded newline so the shape is visible rather than described.

**Task 22 has everything it needs:** `RowVerdict.body` is the exact body to
send, and `FileVerdict.shape` distinguishes one-call-per-row from the `pricing`
CSV whose whole file is a single versioned card.

> **The suite ran inside the clock window, and this is what that looks like.**
> `pytest` at **00:10 IST**: 269 passed, 3 failed — exactly
> `test_what_is_late.py`'s three, which §4 item 8 predicts for 00:00–05:30.
> Deselecting that one file gives 267 passed and nothing else red. Task 21
> touches no file under `app/` or `tests/` (checked with
> `git diff --name-only`), and the same suite was 272/272 at 15:31 IST on this
> tree's parent. **This is not a green run and is not written up as one** —
> re-run it after 05:30.

### 2026-08-17 — Tasks 19 and 20: the last ten item screens

**All sixteen checklist rows now have a screen.** `ITEM_SCREENS` is complete;
it stays a `Partial` map only so the "no screen yet" branch still type-checks.

**Two dependencies came out of `package.json`.** `react-hook-form` and
`@hookform/resolvers` were named by the plan for Task 17, never imported, and
Task 19 was the decision point: `JsonField` is a textarea plus `JSON.parse`, so
nothing here wanted a form library either. Removed. **Six runtime dependencies
now** — react, react-dom, react-router-dom, @tanstack/react-query, zod,
papaparse — and §2's budget is intact rather than merely claimed.

**A stale claim in this plan was caught and corrected in place, not deleted.**
Task 20 Step 3 said the vendor delete is refused when
`action_items.external_wait["vendor_id"]` names the vendor. **That guard no
longer exists** — it was checking a key no caller writes and was removed
outright rather than repaired (`09` §4a). A screen built on the plan would have
promised the operator a protection the server does not provide, which is the
exact failure this console is written against. `Vendors.tsx` says the delete is
unguarded and offers no confirmation: a confirmation implies a consequence.

**P13 is now logged as a lying message, not a missing route.**
`delete_program`'s refusal ends *"Mark it inactive instead"* and nothing writes
`Program.is_active`. `Programs.tsx` still quotes the server verbatim — §4.1 is
right — and then contradicts its last sentence in the console's own voice. The
general rule is recorded in `09` §4a: **quote it, then contradict it; never
quote it alone.** `09` also now carries retiring-a-programme-in-use as
post-Task-25 work rather than a defect.

**A deliberate reversal on `playbooks.phase`.** Task 19 Step 1 asks for the six
phases as suggestions with the free value *allowed*, and the first
implementation used a select, which forbade it. The server takes any string, so
refusing one is this console inventing a rule the backend does not have. The
field is now free text with the six offered, an off-list value goes through, and
both the field and the list say what happens: *no plan will ever fire it*. One
new descriptor flag — `optionsAreSuggestions` — with a test asserting it is used
**exactly once**, so the exception cannot quietly spread.

**A defect the CSS guard found in code it was not written for.** `s` is the
conventional name for the primitives styles import, and the integration screens
shadowed it in a lambda: `configured={(s) => … s.email_mode === "smtp"}`. That
compiles, and `s.email_mode` is the *styles object*, so the comparison is
permanently false and item 11's panel could never have reported "on".
`tokens.test.ts`'s class check flagged it as twelve undefined CSS classes.
TypeScript did not, and no test would have — the screens have no unit tests
(D11). Renamed to `live`.

**What the live run confirmed:**

- item 11 held `◐` with credentials stored and `EMAIL_MODE=dry_run` — the single
  most important behaviour, verified by hand and cross-checked against the API;
- item 10 moved `◐` → `●` on one non-env-seeded dial, and the PATCH carried
  **only** that dial;
- item 12 stayed `◐` and explained why (P12);
- the approval-rule edit deleted and recreated, changed the row id, re-read to
  confirm, and the rank ordering rendered with the catch-all last;
- a playbook filed under `handover` was accepted, warned about at the field, and
  flagged in the list;
- the demo-team edit carried all three role assignments across by **id** — the
  thing backend change #10 exists for — confirmed against the API afterwards;
- item 16 renders with no form, no input and no textarea at all.

Two statuses were re-derived with `curl` as usual, plus the demo team's three
role ids. Console clean on a fresh load.

### 2026-08-17 — Tasks 17 and 18: the first six item screens

**The audit came first, and it found one.** The standing instruction after P11
was to treat `ENV_SEEDED` as a pattern rather than a one-off, so every column
`POST /orgs` writes was checked against every item that reads it *before* any
screen was built. **Item 12 was the second instance and is worse than the
first** — it reads only the two retention columns, both seeded from env vars no
route returns, so it can never be verified at all and P11's carve-out has
nothing to carve. It is now `◐` for every input, with the windows shown and the
reason stated, pinned by a truth table and by a test asserting the whole audit:
**on an untouched organisation, item 1 is the only green row.** Written up as
**P12**; the full four-row audit is in `status.ts`'s `ENV_SEEDED` comment.

**`EntityForm` is three validation layers, and two of them are the point.** The
generated schema alone would silently permit `max_open_tasks: 500` — the bound
sits inside an `anyOf` and the generator drops it (P2) — so `CONSTRAINTS` is
layer 2 and the descriptor's option lists and cross-field rules are layer 3.
Every message names who enforces the rule, in the same three-valued vocabulary
as the provenance line: *"At most 100 (admin.py · CreateUserRequest)"* against
*"…(checked here only)"*. Proved by disabling each layer and watching five tests
go red, then live in the browser: 500 was refused with the handler named, and an
email template with no subject was refused **with no network request at all**.

**A real defect, found by using it rather than by reading it.** The form
validated `bodyFor(values)` and then posted **`values`** — so an untouched
`working_days` box went out as `""` and the server answered *"working_days:
Input should be a valid list"* for a field the operator had never touched.
`onSubmit` now receives the body, not the form state, and a test asserts that an
untouched form of every descriptor sends nothing. That test immediately found a
second case and was tightened rather than the code: an unchecked checkbox is a
real `false`, not a blank, and `approvalRules.auto_approve` is right to be sent.

**A second, smaller one from the same session:** after a successful create the
form still held the previous person's details, so "Add somebody" looked empty
and was not. `resetSignal` clears it — but only on the create-many screens.
The versioned families deliberately keep their values, because publishing v2 of
a rate card means changing one price, not retyping five lines.

**What the live run confirmed that no unit test could:**

- the temporary password is shown once, with the copy control, and the screen
  states the asymmetry P8 cares about — a staff password is recoverable, the org
  admin's is not;
- `POST /skills` reports **which** of its two outcomes happened, so "I added
  Ravi's scheduling" is distinguishable from "I just changed it to basic";
- the skill delete guard fired with its refusal verbatim — *"2 open task(s) need
  'rack-and-stack' and nobody else holds it"* — after arming it with an open
  action item;
- `code` typed as `dc-commission` came back `DC-COMMISSION`, which is why the
  field says so;
- the **tri-state held**: one rate-card line with a stated quantity and one
  without, and the second line's number box stays disabled rather than
  pre-filled with 1;
- publishing v2 and deleting it promoted v1 back to current — and since the
  server answers only `{"deleted": true}`, the screen re-reads and says *"v2 is
  gone. v1 is now the current rate card."*, which is the whole reason that
  re-read exists.

Two statuses were re-derived by hand with `curl`: item 5's per-programme
coverage (`DC-COMMISSION` v1 current, `DC-AUDIT` none) and item 7's four
combinations. Both matched the rail exactly. Console clean on a fresh load.

**Also found: P13.** `delete_program`'s refusal ends *"Mark it inactive
instead."* and **no route writes `Program.is_active`** — grepped, not inferred.
The screen renders the server's message verbatim, as always, and then says that
its suggestion has no endpoint.

**One deviation from the plan, recorded rather than hidden:** Task 17 Step 1
named `react-hook-form` + `@hookform/resolvers/zod`, and neither is used. The
entire validation surface is `validate(descriptor, values)` — a pure function
over a plain object, tested without a DOM — and what a form library would have
added is the resolver plumbing that function replaces. Both packages are still
in `package.json`; Task 19's `JsonField` is the next chance to decide whether
they come out.

### 2026-08-17 — Task 16: the checklist rail and status derivation

**The rail is the product now, not a placeholder.** Sixteen rows in three
labelled tier groups plus item 1 at platform level, each carrying a live status
derived from a real read and — where the row is not satisfied — the manual's own
words for what breaks, set in the serif so the product's voice is visibly the
product's.

`status.ts` is pure and takes the reads as an argument, which is what lets its 52
tests run against the **Task 15 fixtures** rather than against payloads written
to agree with the function. Every read slot is `pending | ok | unreadable`, and
the two failure directions are kept apart on purpose: a read still in flight is
`pending` and renders muted, a read that failed or drifted is `—` **with the
server's own reason**, and neither is ever `○`. `deriveStatus(item, PENDING_READS)`
is asserted to be `pending` for all fifteen data-backed rows, so "not started"
can never mean "still loading".

**Four guards were watched failing before being believed**, each by breaking the
thing it guards and re-running: item 11 returning `●` on `dry_run` (three tests
red, including the truth table), item 10 returning `●` at untouched defaults, a
drifted read collapsing into `○`, and item 16 taking a read at all.

**Two real defects came out of driving it in a browser, and neither was
findable from the spec.**

1. **P11 — item 10 ticked green on an organisation ninety seconds old.**
   `POST /orgs` seeds `audio_retention_days`, `transcript_retention_days` and
   `llm_monthly_budget_usd` from the **server's** environment, and this repo's
   `.env` sets a budget of `3.0` against a model default of `50.0`. §5.2's
   "any dial differs from its model default ⇒ `●`" therefore reported a
   deliberate choice nobody made — the same lie item 10 exists to prevent,
   arriving from the other side. `ENV_SEEDED` now confines those three to `◐`
   with the caption naming them. Written up as **P11** in `07`.
2. **The rail was never actually "permanently visible" (§5.1).** `.rail` carried
   `overflow-y: auto`, which can never fire on a grid item: the row stretches to
   its tallest child, so the rail was always exactly as tall as its own content
   and the *page* scrolled instead — measured, 2145px of rail against a 674px
   viewport, with the checklist leaving the screen entirely. It is now
   `position: sticky` with `block-size: 100vh`, reset to static at the narrow
   breakpoint where the rail becomes a page header.

**The generic guards were extended rather than trusted.** `Rail.module.css` is
the first component-scoped stylesheet, and `tokens.test.ts` only knew `s.` and
`styles.` — a typo'd `r.tallyCount` was invisible to it. It now resolves each
`.tsx`'s own `*.module.css` imports and checks those too, and the `var()` check
walks every module found on disk instead of the one it named. Both extensions
were proved by introducing a typo of each kind and watching them go red.

**Verified in Chrome against a live backend** holding a deliberately partial
organisation — three accounts with two missing a department, one of three
holding a skill, two offerings with only one priced/templated/playbooked, three
of four message templates, rules with no catch-all, credentials stored with
`EMAIL_MODE=dry_run`. Both themes. Console clean on a fresh load. **Two statuses
were re-derived by hand with `curl`** as Step 4 requires: item 7's three current
`kind × channel` rows and item 9's two rules with no `{}` condition, both
matching the rail exactly.

> **How the session was obtained, stated plainly.** This assistant still does not
> type a password into a field. The org-admin token was minted programmatically
> — the same route `tools/capture_fixtures.mjs` already takes — and written into
> `sessionStorage`. So **the sign-in screen itself is still unexercised
> end-to-end**; everything behind it now is.

Also corrected: the guard table's `npm test` breakdown had the right total and
the wrong split (it said descriptors 40 / reads 15; measured, they are 34 / 21).
The figures above are per-file counts from `vitest --reporter=basic`.

The screen beside the rail is deliberately thin — status, quote, consequence,
dependencies — and says so. Task 17 replaces it.

### 2026-08-17 — Task 15: descriptors, read shapes, and the drift tests

**The eleven descriptors** carry only what OpenAPI cannot: the manual's verbatim
words, CSV column order, dependency ordering, per-entity re-import behaviour,
and who enforces each rule. Every option list comes from `VOCAB`; every bound
comes from `CONSTRAINTS`. No role list, no pattern and no numeric range is typed
by hand anywhere in this layer.

**`api/reads.ts` is the one layer with no generated source** (P1), so it is
pinned four ways rather than trusted:

1. Each shape **cites the handler it was transcribed from**, and the citation is
   asserted to be file-and-symbol shaped with no line number.
2. **13 fixtures captured from a live backend** by `tools/capture_fixtures.mjs`,
   which seeds one row in *every* entity first — an empty array validates under
   any shape, and a suite built on one would prove nothing. A test asserts no
   list fixture is empty, so that failure mode cannot creep back.
3. **Strictness is deliberately asymmetric.** Fields the handler always returns
   are required, so a rename or removal fails loudly; unknown keys pass, so a
   field the backend *adds* cannot break a running console. Both directions are
   tested.
4. `client.ts` parses every read and turns a mismatch into the drift banner,
   with the affected statuses `—` rather than `○`.

**The round-trip test is the one that earns its keep.** Derived entirely from
`generated.ts`, it asserts every field a write schema accepts is readable back
for the nine bundle entities. Proved by deleting `fallback_role` from the read
shape — it fails with:

> `approvalRules: the write accepts these and ops.py · list_approval_rules does
> not return them, so the reseed bundle would drop them`

**That is P4, reproduced and caught automatically.** P4 and P5 were both found
by hand and cost a backend unfreeze; that class of defect is now guarded.

**A guard caught my own laziness on its first run.** The rule that a `ui-only`
enforcement must say *what the server does instead* failed on
`approvalRules.description`, whose reason was "free text" — nine characters that
tell an operator nothing. Fourteen such reasons were rewritten to say what
actually happens: an unknown role name leaves nobody able to approve, a zero
`expires_hours` expires the request immediately, an unrecognised
`nudge_gap_days` key is stored and never read.

**Also added, for Task 16:** `SETTINGS_DEFAULTS` in the generated vocabularies —
the 25 `OrgSettings` column defaults, dumped from `Base.metadata`. Item 10 is
`◐` when every dial still equals its default, and comparing needs those numbers.
Generated rather than hand-copied, and the three `*_integration` credential
blobs are excluded because the settings response has no field to compare them
against.

### 2026-08-17 — Task 14: the org hand-off (D18)

The one place in this console where a crash strands an organisation, so the
state machine lives in `session/handoff.ts` with no React in it and is tested
on its own. **13 tests**, and they are about the *secret* rather than the happy
path: where it goes, where it must never go, and whether it appears at exactly
the moment it becomes the only way in.

Three states, all three reviewed in a browser (they render from the styleguide,
so the worst-day screen is not first seen on the worst day):

- **running** — three steps with live markers, no control of any kind.
- **step 1 failed** — *"Nothing was created"*, the server's refusal verbatim, and
  a way back to the form. **No password box**: an empty one here would read as
  "the recovery key is missing", which is worse than the truth.
- **recovery** — steps 2 or 3 failed, so the organisation exists and the
  temporary password is the only way in. Revealed, with the two remaining calls
  written out and the consequence stated.

**A real defect came out of the browser check, and it is the exact thing D18
cares about.** Escape did not dismiss the modal — correct — but clicking the
page behind moved focus to `<body>`, and Tab from there walked into the rail and
focused a button *behind* the dialog. The modal stayed open the whole time, so
it looked contained and was not. The Tab handler only fired while focus was
already inside. Fixed with a document-level `focusin` guard that pulls focus
back; re-verified by repeating the exact sequence.

A second, smaller one: auto-focusing the first control scrolled the recovery
dialog **past its own heading** — "the organisation exists" is the sentence that
explains why a password is on screen, and the operator landed below it. The
modal now focuses its panel, so it opens at the top.

**The chain was replayed against the live server** (12/12): `POST /orgs` →
`POST /auth/login` with the temp password → `POST /auth/change-password`. What
matters is what comes after — the chosen password signs in,
`must_change_password` flips to false, and **the temporary password then returns
401**, which is the only real proof step 3 applied. It also re-confirmed P7:
`/auth/me` carries no `email_domain`, so `POST /orgs` is the single moment the
session can capture it, and `handoff.ts` does.

**Not done: the credentialed browser run.** Entering a password into a field is
not something this assistant does, even on localhost, so the button itself has
not been clicked end-to-end. Everything either side of it is verified. Sign in
at `/dashboard/#/sign-in` to close that gap.

Also added: `src/test-setup.ts`, a real in-memory `sessionStorage` for the node
test environment — "the temporary password is never written anywhere readable"
is a claim about storage, and asserting it against a store that silently no-ops
would prove nothing.

### 2026-08-17 — Tasks 12 and 13: tokens, primitives, client, session, router

**Task 12 — the visual language.** §9 pins the direction (paper/ink, one accent,
serif + grotesque + mono, hairline rules, no motion beyond 120 ms), so the brief
won on every axis it names. Where it left room, the grounding is the artefact
this console actually is: **a commissioning sign-off sheet**. The accent is
aniline stamp violet — the ink commissioning certificates were stamped with —
rather than the terracotta-on-cream that every generated "document" design
reaches for.

**The signature is the provenance line.** Under every control, in small mono, is
who enforces the rule, in three visually distinct states: a solid rule for
`schema`, a **dotted** rule for `backend-undeclared` (real, but not
machine-checkable the way a generated constraint is), and a solid ochre rule
plus a `UI ONLY` stamp for the rules the server does not check at all. That is
§6's honesty model made visible at the point of entry instead of described in a
footnote, and it is the reason A2's third enforcement value exists.

Fonts are **stacks, not downloads** — a webfont would be a network dependency
the console cannot rely on and a build asset §2's dependency budget did not
allow for.

`Modal` has **no dismiss behaviour at all** rather than a `dismissible` flag.
D18's hand-off must have no dismiss, no click-out and no escape in either state,
and a flag is something Task 14 could forget to set.

**Task 13 — the client.** The error shapes were read from
`app/core/exceptions.py` and `app/main.py` and then **confirmed against the
running server**, which is how the important one surfaced: **422 has two
different bodies**. `AppError` returns `{"detail": "<string>"}` and FastAPI's
`RequestValidationError` returns `{"detail": [{loc, msg, …}]}`. Same status. A
client discriminating on status would render `[object Object]` to an operator
for half of all validation failures, so `normaliseError` discriminates on the
type of `detail` and maps `loc` to field paths (`["body","items",0,"code"]` →
`items.0.code`).

Also in Task 13: the two-token store in `sessionStorage` with
`releaseSuper()` (§1.1 — the super-admin token has no reason to outlive the one
call it exists for), `retry: 0` on every mutation with the D17 reasoning written
next to it, the read-drift log, and the hash router from A8.

**Every guard in both tasks was observed failing before being believed** — and
two of Task 12's failed on their very first run, which is the whole argument for
writing them:

- *the same token set in both dark blocks* failed because **the test** matched
  the selector where its own header comment described it, then read the next
  `{` — the light block. It reported 45 tokens against 14 and looked like a
  palette bug. Comments are now stripped before parsing. A parser that reads its
  own documentation is worse than no parser.
- *the product name lives in one place* failed on a real hit: the styleguide's
  quote cited "Innodhara Product Manual", a second place to edit if D15 is ever
  reversed. Now "Product manual".
- Deliberately proved afterwards: a typo'd CSS-module class, a typo'd `var()`
  token, a minted `Idempotency-Key`, and a client that hands back a drifted body
  each fail their guard.

**Reviewed in a browser afterwards, and three defects came out of it.** The
extension connected later in the session, so the styleguide was walked through
in both themes:

1. **The masthead wrapped mid-suffix** — "Innodhara · Setup" / "Console". At
   21 rem the rail cannot hold that on one line. Replaced with a deliberate
   two-line lockup: the serif name, then `SETUP CONSOLE` in small-caps
   grotesque under it, the way a document names itself and then says what kind
   of document it is.
2. **Native checkboxes and selects rendered in the OS default** and read as
   foreign objects in a near-monochrome palette. `accent-color: var(--accent)`.
3. **The rail was 4% away from the page background in light** and did not read
   as a separate surface. `--paper-sunken` deepened to `#e6e3db`.

Then a fourth, found by using it rather than looking at it: **the modal did not
move focus into itself.** Escape correctly did not dismiss it (D18, verified
live), but an operator could still Tab out to the page behind and act on it
while the chain was running. "No dismiss control" has to mean the whole
surface, so `Modal` now focuses its first control on mount and traps Tab.
Verified in the browser: focus lands on the dialog's button and stays there.

Console is clean on a fresh load — no errors, no React warnings.

**Still unverified: the narrow layout.** `resize_window` reported success but
the viewport did not change, so the `max-width: 60rem` breakpoint — where the
rail becomes a page header rather than collapsing behind a hamburger, because
hiding the checklist would hide the thing the operator is working through — is
confirmed only by reading the built CSS.

Hash routing is live and behaves as P10 requires: `/dashboard/` 200,
`/dashboard/styleguide` **404** (correct — no SPA fallback exists, which is why
A8 chose hash routing).

### 2026-08-17 — Task 11: the generation pipeline

`Dashboard/` scaffolded and the type layer generated. **Four committed
artefacts**, all produced by `npm run gen:api`:

| Artefact | Size | From |
|---|---|---|
| `src/api/openapi.json` | 285,297 chars · 127 paths · 85 schemas | `tools/dump_openapi.py`, importing `app.main` |
| `src/api/generated.ts` | 25,734 chars · 86 Zod schemas | `openapi-zod-client@1.18.3`, `schemas-only.hbs` |
| `src/api/constraints.generated.ts` | 5,050 chars · 37 fields, 17 of them recoverable nowhere else | `tools/lift_constraints.mjs` |
| `src/api/vocabularies.generated.ts` | 892 chars · 7 vocabularies | the dumper, from `app/core/constants.py` |

**Measured, not predicted:** the dump is **identical** to the spec served on
:8000; regeneration is **byte-idempotent** (md5 of all four unchanged across two
runs); the generator drops **17** constraints spec-wide, **16 of them
console-relevant**, exactly matching P2's count; `SettingsRequest` accounts for
14 and the count is recomputed from the spec in the test rather than hard-coded.

`schemas-only.hbs` was used rather than the default template: **25 KB importing
only `zod`, against 107 KB importing `@zodios/core`**. Zod resolved to 3.25.76
and the generator is pinned exactly, no caret — `gen:check` diffs generated
output, so a reformatting bump would fail every build with no code change.

**Every guard in this task was observed failing before being believed:**

- tampering with `generated.ts` makes `npm run build` stop at `prebuild` with
  `gen:check FAILED`, and the check restores the working tree it stashed;
- emptying the lift's `droppedOnly()` fails *"lifts every constraint the
  generator is known to drop"*;
- emptying `lift()` fails *"carries every constraint in the spec"*, reporting all
  17 by name.

One test asserts P2 **as behaviour, not as a claim about a library**:
`SettingsRequest.safeParse({assignment_mode: "nonsense"})` succeeds while
`ProgramRequest` rejects a 51-character code. If a future generator starts
carrying `anyOf` constraints, that test fails — and that is the signal to
collapse the descriptor layer back to two enforcement values.

**A false claim in this plan was caught here — see P10.** `StaticFiles(html=True)`
does **not** fall back to `index.html` for unknown sub-paths; it does so only for
a directory URL. `/dashboard/` and its assets serve 200, but
`/dashboard/checklist` returns **404**. The plan asserted otherwise twice; both
places are corrected, and `app/main.py` carries no such comment, so no code
comment is lying. **The console therefore uses hash routing** (A8, now Task 13
Step 2) — no backend change, which the change list being closed at ten requires.

**Deviation from the plan, noted:** the build script is `tsc --noEmit && vite build`,
not `tsc -b`. `-b` wants a composite project and buys nothing for a single one.

### 2026-08-13 — Changes #9 and #10; the list is re-frozen at ten

Owner reopened the change list for **exactly two** read widenings, both found as
findings P4 and P5 while writing Phase 2's detail. Done as Tasks 10a–10c in the
Phase 1 style — test first and confirmed red for the right reason
(`KeyError: 'fallback_role'`, `KeyError: 'lead_user_id'`), then implemented, own
commit each, on branch `feat/backend-changes-9-10`.

- **#9** — `ops.py · list_approval_rules` returns `fallback_role` and
  `auto_approve` (commit `1e8287f`).
- **#10** — `admin.py · list_demo_teams` returns `lead_user_id` /
  `media_rep_id` / `sales_rep_id` **alongside** the three name fields
  (commit `2dfaaaf`).

**Neither writes an audit row**, and that is correct: D13 binds *destructive*
routes, and an audit row per GET would be noise in the log the reset preserves.
`09` §2 rule 2 now says so, because "every route calls `audit_service.record`"
was an easy misreading.

**The route count did not move — confirmed, not assumed.** `check_docs_in_sync.py`
prints **151** and exits 0; the guard counts `APIRoute` instances and a widened
return dict is invisible to it. So no §7.1 or route-count resync was needed.

Four tests added (2 per change), and in each pair the **second** test is the one
that earns its keep: a rule naming neither field must read back `null` / `false`,
and an unset demo-team role must return a key that is **present and null** —
`assert key in row` before `assert row[key] is None`, since a missing key and a
null both read as `None` through `.get()`. A single happy-path assertion is
satisfied by a handler returning literals, which is how this project already
shipped a guard written against a key no caller writes (`09` §4a).

Docs: **D24** in `05` with the reasoning; `09` gains a fourth freeze-history row,
two change rows and two annotated rules; `BACKEND_README.md` §13 refreshed
265→**272** (it had also gone stale by 3 across Tasks 11–12 — the guard asserts
no test figures, verified by reading it). In `07`, **P4 and P5 are marked FIXED
rather than deleted** — they are why two of the ten changes exist — and the four
warnings they justified are gone from Tasks 19, 20, 23 and 24, along with Task
15's two `notReadable` lists.

**Next person: Task 11.** The backend is re-frozen at ten and Phase 2 needs no
further backend work.

### 2026-08-13 — Phase 2 task detail written from the live spec

Fetched `/openapi.json` from the running backend (151 operations, 85 component
schemas) and **ran `openapi-zod-client@1.18.3` over it** in a scratch directory
rather than predicting its output. Nine findings, written up as P1–P9 in
`07_BUILD_PLAN.md` §Phase 2, four of which falsify claims in `06_DESIGN.md` §3
and change the shape of Tasks 11, 15 and 16:

- **P1 — 11 of the 15 reads this console makes return `"schema": {}`.** Only
  `GET /auth/me`, `GET /orgs` and the two `/admin/users` routes declare a
  response model. §5.2 derives every checklist status from the untyped eleven,
  so **response shapes cannot be generated** — `src/api/reads.ts` plus live
  fixtures plus a drift banner replace the generation that isn't available.
- **P2 — the generator drops every constraint declared inside an `anyOf`,**
  which is how FastAPI renders every optional field. Measured: **12 survive,
  16 are dropped**, including all seven `SettingsRequest` patterns and bounds
  and `max_open_tasks`. Marking those `ui-only` would tell the operator the
  server accepts anything, which is false. `enforcement` is now three-valued,
  and the 16 are **lifted from `openapi.json`** (which has them) rather than
  hand-typed.
- **P3/A4 — `role`, `department`, `kind`, `channel` and the 8-char password
  rule are enforced in handler bodies**, so OpenAPI types them `string`. The
  dumper now also emits the `constants.py` enums, so no role list is ever typed
  by hand — `RoleGate.java` is one permission behind because one was.
- **P6 — `GET /orgs` is super-admin-only**, so §5.2 item 1's stated read is
  unreachable from the session that runs the console. Item 1 derives from
  `GET /auth/me` alone.

Also verified, because both would have cost a debugging session later: the
in-process `app.openapi()` dump is **identical** to the served spec key-for-key,
and the descriptions carry `§ — →`, so every read and write in the pipeline
must name UTF-8 explicitly on this machine.

**No code was written and no file under `app/` was touched.** Two open
escalations (P4, P5) are recorded in §1 above.

### 2026-08-13 — Task 10, docs resync — Phase 1 complete

Ran `python scripts/check_docs_in_sync.py` first and used its printed figures
rather than the build plan's predictions (they agreed: 151 routes, 70 uncalled,
Organisation administration 25, Operations and money 20). Updated
`BACKEND_README.md`: the routes count (140→151, three prose mentions), §7.1's
heading and its two changed rows (rows and their independently-checked sum both
now 70), and §13's test wording — replaced the misleading "218 pytest" with
"265 collected, 265 passing" plus a note explaining `test_what_is_late.py`'s
clock-dependent window (§4 item 8 above). Touched no file under `app/` — this
task is docs-only, as the closed change list requires.

All four verification commands are green: `check_docs_in_sync.py` exits 0
(`OK - the three documents agree with the code`); `pytest tests/test_genericity.py`
8/8; `python -m pytest -q` 265/265 (run at 14:2x local, past the 05:30
boundary); `scripts/check_hardcoded_strings.py` exits 1 with the same 2
pre-existing cosmetic Java findings (`LoginFragment.java:101`,
`SplashFragment.java:48`) that predate this work — reported, not fixed, per the
brief.

Ticked the guard column for all 8 rows in `09_BACKEND_CHANGES.md` and marked the
list re-frozen. **Phase 1 is done.**

**Next person: Phase 2.** Its task-level detail (Tasks 11+) is written from the
live `/openapi.json` per `07_BUILD_PLAN.md`'s note on why that was deferred —
start there, then Task 11 (scaffold + generation pipeline).

### 2026-08-13 — design session

Read `00`–`04` in full, verified their load-bearing claims independently, and
took the brief's five decisions plus nine more. Wrote `05`, `06`, `07` and these
two stubs. **No application code was written and no backend file was touched.**

Four things were found by verification rather than inherited:

- **Q4 and Q9 contradicted each other.** Per-row catalogue deletes were granted,
  direct DB writes were barred, and no catalogue DELETE endpoint exists. Raised
  rather than planned around; the owner added changes #6, #7 and #8.
- **The reset taxonomy could not express the endpoint.** `audit_log` in WIPE
  contradicts D13, and `user_skills` / `approval_rules` in KEEP break the reseed
  round-trip. Now four buckets (D16).
- **`Idempotency-Key` is not read anywhere in the backend.** The design dropped
  it rather than performing it (D17).
- **The genericity guards cannot reach `Dashboard/dist/`**, so the proposed
  exclusion would have been dead configuration. Replaced with an invariant (D19).

**Next person: start at Task 1 of `07_BUILD_PLAN.md`.** Nothing is half-done.
