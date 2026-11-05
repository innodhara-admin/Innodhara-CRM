# SDD ledger — plan: Dashboard/READMEs/07_BUILD_PLAN.md

Branch: `feat/setup-console-phase1`
Baseline: `19efa98` (repo baseline, pre-work) → `8ea4e73` (ignore .superpowers/)

Human instruction: **stop after Task 1 and report before starting Task 2.**
Standing instruction to every implementer: if a task needs a backend change
beyond the closed eight, STOP and report — do not plan around it and do not
widen an existing change to cover it.

## Log

- Setup: `git init`, `.gitignore` hardened (secrets/ held a live GCP
  service-account private key and was NOT previously ignored), baseline commit
  `19efa98`, branch `feat/setup-console-phase1` created off master.
- Task 1: BASE `8ea4e7335dfa061f71dad5ec58047f7f53089f56`
- Task 1: review clean — spec ✅, quality approved, no Critical/Important.
- Task 1: reviewer's ⚠ "UserResponse used elsewhere?" resolved by controller —
  `grep -rn UserResponse app/` returns hits only in `app/api/admin.py`. Not a gap.
- Task 1: **complete** (commits `8ea4e73..9fed77c`, review clean)

### Measured facts established during Task 1

- **The suite was NOT green at baseline.** `19efa98` → `3 failed, 215 passed`
  (218 collected). The 3 failures are `tests/test_what_is_late.py` date-boundary
  tests and are pre-existing — verified by the controller checking out the
  baseline commit directly, not merely by trusting the implementer.
  Docs saying "218 pytest" count collected tests, not passing ones.
- After Task 1: `3 failed, 219 passed` (222 collected). +4, all passing.
- Route count 140 → **141** (exactly the one new `GET /admin/users/{user_id}`).
- `check_docs_in_sync.py` is red and stays red until Task 10 — expected, by design.

### Deferred minors (for the final whole-branch review)

- Task 1: brief's Step 2 predicted a 404 on the detail-route red run; the real
  behaviour is 405. Prose-only defect in the plan, no effect on assertions.

- Task 2: **complete** (commit `f315283`, review clean — spec ✅, quality approved)
- Task 3: **complete** (commit `065038a`, review clean — spec ✅, quality approved)
- Task 4: **complete** (commits `f1fe20d..e7cacfc`, review clean — spec ✅, approved)
- Task 5: BASE `e7cacfc`; implemented at `3d36b73`. Review found **1 Critical**.
- Task 5: fix round 1/5 dispatched — WIPE ordering violates the child-before-parent
  contract on 5 FK edges (`stakeholders`→`projects`; `followups`, `demos`,
  `memory_chunks`, `client_intelligence`→`leads`). **Controller-verified by an
  independent FK-graph walk before dispatching.** Root cause is a plan defect:
  the WIPE list was copied verbatim from `scripts/reset_for_datacentre_demo.py`,
  whose header asserts child-before-parent ordering — **that claim is false in
  the script too**, masked there by `PRAGMA foreign_keys=OFF`. Our endpoint does
  not disable FKs, so the ordering is load-bearing for us.
  Fix also replaces the 5 cherry-picked test pairs with a full FK-graph assertion:
  the 5 pairs the test checked were all genuinely fine and none overlapped the 5
  that were broken, which is exactly how it passed.

### For the owner — a pre-existing bug found, NOT fixed here

`scripts/reset_for_datacentre_demo.py`'s WIPE list has the same 5 ordering
violations and the same false header comment. Out of scope (closed change list),
left untouched, reported to the owner.

- Task 5: fix round 1/5 (1 addressed, 0 open; commits `3d36b73..1b4bf2b`).
  Re-review verified independently against the live schema: 0 FK violations,
  all 42 WIPE entries retained, partition intact, and the new test confirmed to
  FAIL against the old ordering (i.e. genuinely strengthened, not a coincidental pass).
- Task 5: **complete** (commits `e7cacfc..1b4bf2b`, review clean)
- Task 6: BASE `1b4bf2b`; implemented at `256d727`. 7/7 tests, suite 238 passed /
  3 failed / 241 collected. Route count now **143**.
- Task 6: review verified tenant isolation at the compiled-SQL level, `users`
  unreachable across all 8 flag combinations, dry-run non-mutating, the
  confirmation gate against 8 bypass shapes, and — beyond the brief — that a
  mid-loop exception rolls back entirely, leaving no half-wiped org.

### Task 6: ONE Important finding — PLAN-MANDATED, awaiting the owner's ruling

`wipe_catalogue=True, wipe_transactional=False` is reachable and returns 200,
but deletes REPLACE while its WIPE-side children survive. **Controller-verified:
6 broken FK edges, 4 of them NOT NULL:**

    demo_team_members.team_id -> demo_teams        NOT NULL
    proposals.program_id      -> programs          NOT NULL
    proposals.template_id     -> proposal_templates NOT NULL
    proposals.pricing_table_id-> pricing_tables    NOT NULL
    demos.team_id             -> demo_teams        nullable
    projects.program_id       -> programs          nullable

Not an implementation defect — the three independent flags are `06_DESIGN.md`
§7.3 / D16, i.e. MY spec. The old script could never reach this state because it
always deleted WIPE+REPLACE together. **Per protocol a finding that conflicts
with the plan's own text is the human's decision — not dispatched as a fix.**
Options put to the owner: (a) refuse the combination with 422, (b) make
`wipe_catalogue` imply `wipe_transactional`, (c) accept and document.

### Task 6 rulings and fix rounds

- Owner ruled on the catalogue-only orphan finding: **refuse only when it would
  actually orphan** (D22). Dry run never 422s; it reports the blocking edges so
  the conflict shows at preview. Rationale, which generalises: *the reset must
  not permit in bulk what change #6 refuses per row.*
- Task 6: fix round 1/5 (orphan guard + rollback test; commit `d04f007`,
  12/12 tests, suite 243 passed / 3 failed).
- Task 6: fix round 2/5 — **DISPATCHED BUT NEVER RAN.** The agent terminated on
  an API session limit (resets 07:20 Asia/Calcutta) before making any edit.
  Verified: working tree clean, HEAD still `d04f007`, `_CATALOGUE_ORPHAN_EDGES`
  still present and still hand-written. **Nothing partial to unwind.**
  Re-dispatch this round from scratch. The finding, verbatim:
  `_CATALOGUE_ORPHAN_EDGES` was a hand-maintained tuple of 6 edges with no guard.
  Same pattern as Task 5's Critical, and what D12 forbids ("generated, not
  mirrored"). Fix derives the edges from `Base.metadata` by walking FKs from
  `WIPE | CONFIG` into `REPLACE`, plus a test that independently re-walks the
  graph and asserts equality — so a new edge is picked up with no code change.

- Task 6: fix round 2/5 (1 addressed, 0 open; commit `da7c595`). Re-review
  verified the derivation live, confirmed a narrowed derivation is caught, and
  confirmed no CRLF survived the implementer's intermediate mishap.
- Task 6: **complete** (commits `1b4bf2b..da7c595`, review clean)
- Task 7: BASE `da7c595`, implemented `2afb8fb`. Spec ✅, quality approved.
  **Suite now 254 passed, 0 failed** — the 3 `test_what_is_late.py` tests pass
  because local time is now past 05:30, empirically confirming the timezone
  diagnosis rather than any change we made.
- Task 7: **two brief defects found by the implementer, both accepted** —
  (a) `POST /action-items` has no `required_skill` and no route sets it, so the
  fixture builds the task via `SessionLocal`, matching the precedent already in
  `tests/test_assignment_skills.py`; (b) there is no `/tasks/{id}/external-wait`
  route — the real one is `POST /tasks/{id}/vendor-promise`, which writes
  `vendor_name` and **never** `vendor_id`. My brief's vendor guard checked only
  `vendor_id` and would have been **dead code**. Widened to match either key,
  which is what `sync_engine.py:1635` already does.
- Task 7: **complete** (commits `da7c595..2afb8fb`, review clean)

### Deferred minors (for the final whole-branch review)

- **Task 7 · design-vs-code divergence, needs a ruling.** `06_DESIGN.md` §7.2
  says the skill delete refuses when "an open task requires it and no other
  **active** user holds it". The shipped `others` count — copied verbatim from
  my brief — counts any `user_skills` row regardless of `User.is_active`. So a
  deactivated user's leftover skill row reads as "another holder" and lets the
  delete through, even though nobody active can do the open work. Narrow, but
  the doc and the code disagree. Fix is one line (join `User`, filter
  `is_active`) or correct the doc. **Do not close this silently — pick one.**
- **`action_item.py`'s `external_wait` docstring is wrong.** It documents
  `{"vendor_id","promised_date","chase_contact"}`; the only writer
  (`workflow.py` · `record_vendor_promise`) writes `vendor_name`. This is what
  made my brief's guard dead code. Out of the closed change list; log in 09.
- **Vendor name matching is fragile** (accepted, not a defect): `Vendor.name` has
  no uniqueness constraint and `create_vendor` inserts unconditionally, so two
  same-named vendors are possible, and promise-time `vendor_name` is typed
  independently of the catalogue. Both are false negatives — the guard fails to
  block — never over-blocking.
- Task 1: brief predicted 404 on a red run; actual 405. Prose-only.
- Task 6: `confirm_org_name` strips input but not `org.name`, so an org whose
  stored name has leading/trailing whitespace can never be reset.
- Task 6: `reset_organisation` re-selects the `Organisation` that
  `get_org_context` already loaded (needs `.name`, which `ctx` lacks).
- Task 6: test coverage gaps — dry-run asserts only `/leads` not all 51 tables;
  no case/whitespace variants of the confirmation; no rollback test.

## Paused

Human instruction: stop after Task 1 and report before starting Task 2.
Next action when resumed: Task 2 (honest delivery mode), BASE = `9fed77c`.
