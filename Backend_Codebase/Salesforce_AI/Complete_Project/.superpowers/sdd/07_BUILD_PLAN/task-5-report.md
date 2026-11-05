# Task 5 report — reset taxonomy and partition guard

## What was created

- `app/core/reset_taxonomy.py` — new module (the one new file this phase adds
  under `app/`), verbatim from the brief's Step 3: `KEEP` (4), `CONFIG` (2),
  `REPLACE` (7), `WIPE` (42) tuples and `deletion_order(*, transactional,
  catalogue, org_config) -> list[str]`.
- `tests/test_reset_taxonomy.py` — verbatim from the brief's Step 1, six tests.

No route, no migration, no other file touched. `scripts/reset_for_datacentre_demo.py`
was not modified.

## Pre-flight verification (before writing the module)

Before trusting the brief's hard-coded lists, I computed `Base.metadata.tables`
directly against the current code (`app.models` imported first to register all
mappers) and diffed it against the brief's four lists programmatically:

- `Base.metadata.tables` has exactly **55** tables today.
- `set(buckets) - tables == set()` — no bucket names a non-existent table.
- `tables - set(buckets) == set()` — no table is unclassified.
- No table appears in more than one bucket.
- Every `CONFIG`/`REPLACE`/`WIPE` table has an `org_id` column.

All held. The brief's lists are an exact, correct partition of the real
schema as it stands today — **no bucket reassignment was needed**, and the
expected sizes (4/2/7/42 = 55) did not need adjusting.

## Test run — Step 2 (expected failure)

`python -m pytest tests/test_reset_taxonomy.py -v`

```
ERROR collecting tests/test_reset_taxonomy.py
ModuleNotFoundError: No module named 'app.core.reset_taxonomy'
```

Matches the brief's expected failure exactly.

## Test run — Step 4 (expected pass, after writing the module)

`python -m pytest tests/test_reset_taxonomy.py -v`

```
tests/test_reset_taxonomy.py::test_every_table_is_in_exactly_one_bucket PASSED
tests/test_reset_taxonomy.py::test_bucket_sizes_are_the_agreed_partition PASSED
tests/test_reset_taxonomy.py::test_users_and_audit_log_are_kept PASSED
tests/test_reset_taxonomy.py::test_every_wipeable_table_can_be_org_scoped PASSED
tests/test_reset_taxonomy.py::test_deletion_order_puts_children_before_parents PASSED
tests/test_reset_taxonomy.py::test_flags_select_only_their_own_bucket PASSED

6 passed in 0.04s
```

## Full-suite checkpoint — Step 5

`python -m pytest -q`

```
FAILED tests/test_what_is_late.py::test_a_task_due_today_is_not_called_overdue
FAILED tests/test_what_is_late.py::test_the_due_today_header_is_never_empty
FAILED tests/test_what_is_late.py::test_today_and_overdue_never_overlap - IndexError

3 failed, 231 passed in 18.23s
```

This matches the brief's stated pre-existing baseline exactly: 225 passed / 3
failed / 228 collected → 231 passed / 3 failed / 234 collected, i.e. +6 new
passing tests, zero regressions, and the same 3 pre-existing failures in
`tests/test_what_is_late.py` (the documented timezone/"due today" bug,
unrelated to this task).

## Whether the 55-table partition held

Yes, exactly. `len(Base.metadata.tables) == 55` and the brief's bucket sizes
(4, 2, 7, 42) required no changes. No new table has been added to the schema
since the plan was written.

## Anything in the brief that was wrong about the real code

Nothing. `Base` imports cleanly from `app.database` as stated, `app.models`
registers all mappers as stated, every table named in the four buckets exists,
every `CONFIG`/`REPLACE`/`WIPE` table carries `org_id`, and the deletion-order
child/parent pairs asserted in the test (`action_items`/`projects`,
`payments`/`invoices`, `contacts`/`leads`, `pricing_tables`/`programs`,
`demo_team_members`/`demo_teams`) are all satisfied by list order as written.
No corrections were required to either the test file or the module.

## Concerns

None. This task is additive-only (one new module, one new test file), stayed
within the closed backend-change list (foundation for change #5, no route
added), and did not touch `scripts/reset_for_datacentre_demo.py`.

## Commit

`3d36b73` — "Add reset taxonomy module and partition guard test (Task 5)"
on branch `feat/setup-console-phase1`.

---

## Fix round 1 of 5 — WIPE ordering (Critical, review-found)

**Finding (verified independently, confirmed real):** `WIPE`'s declared order
was not child-before-parent. I re-derived the full FK graph among the 42
WIPE tables directly from `Base.metadata` (every `ForeignKey` on every WIPE
table whose target is also a WIPE table) and it reproduced exactly the 5
violations the coordinator reported, no more, no fewer:

```
stakeholders        (idx 25) -> projects (idx 21)  via project_id
followups           (idx 29) -> leads    (idx 28)  via lead_id
demos               (idx 30) -> leads    (idx 28)  via lead_id
memory_chunks       (idx 35) -> leads    (idx 28)  via lead_id
client_intelligence (idx 36) -> leads    (idx 28)  via lead_id
```

The 5 pairs the original test hand-picked (`action_items`/`projects`,
`payments`/`invoices`, `contacts`/`leads`, `pricing_tables`/`programs`,
`demo_team_members`/`demo_teams`) were all genuinely satisfied and none of
them overlapped the 5 that were broken — confirming the coordinator's point
that cherry-picked pairs are exactly what let this through.

### 1. Reordered `WIPE` in `app/core/reset_taxonomy.py`

Computed the minimal fix algorithmically: repeatedly find a child whose
index exceeds its parent's, remove it, and reinsert it immediately before
that parent's current position; repeat to a fixed point. This converged in
6 iterations to zero violations while leaving every other table's relative
order untouched. Net effect:

- `stakeholders` moved from index 25 to immediately before `projects`
  (also keeps it before `contacts`, its other FK parent, since `contacts`
  remains after `projects` in the list).
- `followups`, `demos`, `memory_chunks`, `client_intelligence` moved to
  immediately before `leads`, in that same relative order.

All 42 entries retained, none moved between buckets, `KEEP`/`CONFIG`/`REPLACE`
untouched. New `WIPE` order (verbatim from the file):

```python
WIPE: tuple[str, ...] = (
    "message_delivery_log", "outbound_messages", "inbound_messages", "threads",
    "approvals", "proposal_revisions", "proposals",
    "reminders", "assignments", "progress_events", "ai_decisions",
    "action_items", "action_plans", "client_commitments", "conflicts",
    "project_members", "resource_bookings", "deliverables",
    "payments", "invoices", "incidents",
    "stakeholders", "projects",
    "transcripts", "meetings", "consent_records",
    "contacts", "lead_state_history",
    "followups", "demos", "memory_chunks", "client_intelligence", "leads",
    "demo_team_members",
    "notifications", "digests", "assistant_turns",
    "playbook_suggestions",
    "idempotency_records", "jobs", "llm_usage", "device_tokens",
)
```

I also checked whether `deletion_order`'s later `REPLACE`/`CONFIG` appends
introduce any cross-bucket violation: every WIPE→REPLACE edge (e.g.
`proposals`→`programs`, `demos`→`demo_teams`) and WIPE→CONFIG edge is
automatically safe because WIPE precedes both in the returned list, and
`REPLACE`'s own internal order (`pricing_tables`, `proposal_templates`,
`playbooks` all before `programs`; `demo_team_members`... wait, that one's
in WIPE, not REPLACE — REPLACE's `demo_teams` has no WIPE-side check needed
since it's a pure parent) is child-before-parent by inspection. No further
reordering was needed outside `WIPE`.

### 2. Replaced `test_deletion_order_puts_children_before_parents`

New test `test_deletion_order_respects_every_foreign_key` in
`tests/test_reset_taxonomy.py` walks every `ForeignKey` on every table
`deletion_order(transactional=True, catalogue=True, org_config=True)`
returns, skips self-references and any parent not in the returned list
(i.e. `KEEP` tables such as `users`/`organisations`/`org_settings`/
`audit_log`), and asserts child index < parent index for every remaining
edge, collecting *all* violations into one assertion message rather than
stopping at the first. Kept `assert "users" not in order` and
`assert "audit_log" not in order`.

I confirmed the new test actually detects the class of bug it's meant to
catch: temporarily substituting the old (broken) `WIPE` tuple into the
module at runtime and re-running the FK walk reproduced exactly the same
5 violations reported above, then re-running against the real (fixed) file
content gave zero.

### 3. Docstring

Updated to state the true, now-truthful claim: WIPE's internal order is
topologically sorted against every FK edge among its own 42 tables (calling
out the 5 non-obvious edges by name so nobody "tidies" the tuple back into
declaration order), and explains why appending REPLACE/CONFIG afterward is
still safe unchecked. It also now says the test walks the FK graph, not
just that it "asserts a complete partition" — that sentence undersold what
the test does before this fix and now matches reality.

### Verification — FK walk over the reordered list, zero violations

Ran the same graph-walk script the coordinator's finding was checked
against, directly on the module as written to disk:

```
violations: []
```

(Also re-ran it against the deliberately-reinstated old `WIPE` tuple in the
same session, confirming it reproduces exactly the 5 reported violations —
i.e. the check itself is not vacuously passing.)

### Test run — `tests/test_reset_taxonomy.py`

`python -m pytest tests/test_reset_taxonomy.py -v`

```
tests/test_reset_taxonomy.py::test_every_table_is_in_exactly_one_bucket PASSED
tests/test_reset_taxonomy.py::test_bucket_sizes_are_the_agreed_partition PASSED
tests/test_reset_taxonomy.py::test_users_and_audit_log_are_kept PASSED
tests/test_reset_taxonomy.py::test_every_wipeable_table_can_be_org_scoped PASSED
tests/test_reset_taxonomy.py::test_deletion_order_respects_every_foreign_key PASSED
tests/test_reset_taxonomy.py::test_flags_select_only_their_own_bucket PASSED

6 passed in 0.04s
```

### Full-suite re-check

`python -m pytest -q`

```
FAILED tests/test_what_is_late.py::test_a_task_due_today_is_not_called_overdue
FAILED tests/test_what_is_late.py::test_the_due_today_header_is_never_empty
FAILED tests/test_what_is_late.py::test_today_and_overdue_never_overlap - IndexError

3 failed, 231 passed in 15.77s
```

Same 3 pre-existing, out-of-scope failures as before the fix; no regressions.

### Out of scope, confirmed untouched

`scripts/reset_for_datacentre_demo.py` was not modified — its identical
ordering bug (masked there by `PRAGMA foreign_keys=OFF`) is being reported
to the owner separately per the coordinator's instruction.

### Commit

`1b4bf2b` — "Fix WIPE deletion ordering to satisfy every FK edge (Task 5,
review round 1)" on branch `feat/setup-console-phase1`.
