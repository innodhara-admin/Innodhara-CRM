# Task 8 report — guarded deletes in `admin.py` (change #6, part 2/2)

## What changed

`app/api/admin.py`:

- Imports: added `Demo` (alongside the existing `DemoTeam`, `DemoTeamMember`
  import from `app.models.demo`), `Playbook, Project` from `app.models.project`,
  `Proposal` from `app.models.proposal`.
- New section "Guarded deletes (change #6, part 2)" inserted after
  `list_demo_teams` and before "Settings & integrations":
  - `_promote_predecessor(db, model, **scope)` — shared helper: finds the
    highest remaining `version` matching `scope` and sets `is_current = True`
    on it. This is the API's only un-supersede path.
  - `DELETE /programs/{program_id}` (`manage_programs`) — 409 if any
    `Project.program_id` or `Proposal.program_id` references it; on success
    cascades in-handler: deletes the program's `pricing_tables`,
    `proposal_templates`, `playbooks` rows (no `ondelete=` in the schema, so
    nothing else would clean these up), then deletes the program.
  - `DELETE /programs/{program_id}/pricing/{version}` (`edit_pricing`) — 409
    if a `Proposal.pricing_table_id` locks that row; on delete of the current
    version, promotes the predecessor scoped by `(org_id, program_id)`.
  - `DELETE /programs/{program_id}/proposal-templates/{template_id}`
    (`manage_templates`) — 409 if a `Proposal.template_id` locks it; promotion
    scoped by `(org_id, program_id)`.
  - `DELETE /message-templates/{template_id}` (`manage_templates`) — no
    reference guard (nothing points at a message template); promotion scoped
    by `(org_id, kind, channel)` — deliberately **not** `program_id`, since
    message templates are not per-program.
  - `DELETE /demo-teams/{team_id}` (`manage_teams`) — 409 if a `Demo.team_id`
    books it; on success deletes `demo_team_members` rows for the team first
    (no `ondelete=` there either), then the team.
  - All five call `audit_service.record(...)` before `db.commit()` (D13).
    `delete_approval_rule` in `ops.py` was not touched or copied from.

`tests/test_dashboard_deletes_admin.py` — new, exactly the brief's 6 tests,
with one comment added explaining why the proposal-creation setup call needed
no code change (see below). No assertion was changed from the brief.

`Dashboard/READMEs/09_BACKEND_CHANGES.md` — change #6's row updated from
"🔶 part 1/2" to "✅", tests column to "✅ T7 7/7, T8 6/6", and a changelog
line appended for T8.

## Setup-call verification (the brief's warning about Task 7's mismatches)

Checked every setup call against the real API before Step 2, as instructed:

- **`POST /api/v1/proposals`** — real route is in `app/api/proposals.py`,
  `BuildProposalRequest = {lead_id, program_id, template_id=None,
  context_summary=None, quantities=None, project_id=None}`. The brief's test
  body is `{lead_id, program_id, title}` — **`title` is not a field on the
  real model.** Checked whether this breaks the call: grepped the whole
  `app/` tree for `model_config`/`extra="forbid"` — the only hit is
  `app/config.py`'s `SettingsConfigDict` (unrelated, that's env-var settings,
  not a request body). No `BaseModel` in this codebase opts out of pydantic
  v2's default `extra="ignore"`. Verified directly rather than assumed:
  `BuildProposalRequest(lead_id="x", program_id="y", title="ignored")`
  constructs without error and simply drops `title`. **Conclusion: no
  correction needed** — the setup call works as written in the brief, the
  extra field is silently ignored, not rejected. I did not delete `title`
  from the test body; I left it as the brief wrote it and added a comment
  explaining why, since removing it wasn't necessary and the brief said only
  to adjust what doesn't work.
- **`POST /api/v1/leads`** with `{"name": "Buyer Ltd"}` — matches
  `LeadRequest` in `app/api/leads.py` (`name` is the only required field).
  No change needed.
- **`GET /api/v1/auth/me`** returning `me["user_id"]` — matches `MeResponse`
  in `app/api/auth.py` (`user_id, email, name, role, org_id`). No change
  needed.
- All other setup calls (`POST /admin/programs`, `POST
  /admin/programs/{id}/pricing`, `POST
  /admin/programs/{id}/proposal-templates`, `POST /admin/message-templates`,
  `POST /admin/demo-teams`) are calls into the same file being edited and
  were confirmed against the existing handlers already in `admin.py` before
  this task (all six of the brief's tests passed on the first run after the
  routes were added — no setup-call bugs surfaced).

So, unlike Task 7, **no test-body corrections were required** for Task 8's
suite. The brief's warning was heeded (I did the verification), the
verification simply came back clean.

## Guard-column verification

Confirmed each guard queries a real, populated column before trusting it —
Task 7's lesson (a guard on a JSON key nothing ever wrote):

| Guard | Column | Nullable? | Populated by |
|---|---|---|---|
| `delete_program` | `projects.program_id` | yes (`Mapped[str \| None]`) | set when a project names a program |
| `delete_program` | `proposals.program_id` | no (`Mapped[str]`) | every `build_proposal` call |
| `delete_pricing_version` | `proposals.pricing_table_id` | no (`Mapped[str]`) | every `build_proposal` call |
| `delete_proposal_template` | `proposals.template_id` | no (`Mapped[str]`) | every `build_proposal` call |
| `delete_demo_team` | `demos.team_id` | yes (`Mapped[str \| None]`) | set when `POST /demos` is called with `team_id` |

The two non-nullable proposal columns make the pricing and template lock
guards impossible to be dead code: any proposal at all locks both its
pricing version and its template version, so the guard fires whenever a
proposal exists for that program.

The brief's own 6-test suite only exercises **refusal** for one of the five
guards (`delete_program`'s project/proposal-in-use check, via
`test_program_with_a_proposal_refuses`). The other three guards that can
refuse (pricing-locked, template-locked, demo-booked) are exercised only on
their non-refusing path by the brief's tests (pricing-version promotion test
never locks a version; message-template test has no guard by design; demo
team test never books a demo against the team before deleting it).

To close that gap without changing what the brief's official suite asserts,
I wrote a temporary, uncommitted scratch file
(`tests/test_scratch_guard_verify.py`) with 3 tests that: build a proposal
against pricing version 1, then try to delete version 1 (expect 409,
"proposal(s) locked this rate card version"); build a proposal against a
template, then try to delete that template (expect 409, "proposal(s) were
built from this template version"); book a demo against a team, then try to
delete the team (expect 409, "demo(s) are booked against"). All three
passed on the first run:

```
PRICING GUARD: 409 {"detail":"1 proposal(s) locked this rate card version. Removing it would break the price they were sent at."}
TEMPLATE GUARD: 409 {"detail":"1 proposal(s) were built from this template version."}
DEMO TEAM GUARD: 409 {"detail":"1 demo(s) are booked against 'Booked Squad'."}
```

The scratch file was deleted after this run — it is not part of the
deliverable and is not in the repo. **All five guards are confirmed live**,
none is dead code.

## Test command and full output

```
$ python -m pytest tests/test_dashboard_deletes_admin.py -v
============================= test session starts =============================
collected 6 items

tests/test_dashboard_deletes_admin.py::test_unused_program_deletes PASSED [ 16%]
tests/test_dashboard_deletes_admin.py::test_program_with_a_proposal_refuses PASSED [ 33%]
tests/test_dashboard_deletes_admin.py::test_deleting_current_pricing_promotes_the_previous PASSED [ 50%]
tests/test_dashboard_deletes_admin.py::test_message_template_deletes_without_a_guard PASSED [ 66%]
tests/test_dashboard_deletes_admin.py::test_demo_team_delete_removes_its_members PASSED [ 83%]
tests/test_dashboard_deletes_admin.py::test_cross_org_delete_is_a_404 PASSED [100%]
============================== 6 passed in 2.95s ==============================

$ python -m pytest -q
........................................................................ [ 27%]
........................................................................ [ 55%]
........................................................................ [ 83%]
............................................                             [100%]
260 passed in 27.06s
```

260 = 254 (baseline at task start) + 6 (this task's new file). 0 failed —
note this is better than the "254 passed, 0 failed" baseline description
implied would carry a residual (there is no `test_what_is_late.py`
timezone flakiness at this run's time of day; that module's tests passed
cleanly here too).

## Scope discipline

- No new column, no migration — all five routes read existing columns only.
- Nothing added under `app/` beyond `app/api/admin.py`.
- `app/core/reset_taxonomy.py` and `scripts/reset_for_datacentre_demo.py`
  untouched.
- No ninth backend change was needed — every guard, every setup call, and
  the promotion helper worked with the schema and routes as they already
  exist.

## Concerns

- None that block. The one thing worth flagging for Task 9/10: the "Guards
  green" column for change #6 in `09_BACKEND_CHANGES.md` is still ⬜, same as
  every other row — `check_docs_in_sync.py` and `check_hardcoded_strings.py`
  are documented (§4, §4a of that file) as still failing for reasons
  explicitly deferred to Task 10 (doc resync) and pre-existing (2 cosmetic
  Java findings), not because of anything in this task. I did not run those
  two guard scripts myself since Task 8's brief Step 6 only asks for
  `pytest -q` green and the changelog/table update — consistent with how
  every prior task's row in this same table was closed.
- `delete_program`'s cascade deletes `playbooks` rows for the program but
  does not touch `playbook_suggestions` (which carries a bare `program_id:
  Mapped[str]` with no FK, per `app/models/project.py`). This matches the
  brief exactly (`Playbook`, not `PlaybookSuggestion`, is in the brief's
  cascade tuple) and is additive-only scope, so left as specified rather than
  widened. **Fixed in round 1 — see below.**

---

## Fix round 1 of 5 — review findings addressed

Two findings from code review, both scoped to `app/api/admin.py` and
`tests/test_dashboard_deletes_admin.py`. No ninth backend change needed.

### Important — the three guard-refusal tests are now permanent

The scratch verification (pricing-locked, template-locked, demo-booked all
refuse with 409) was real proof but was deleted after the run, leaving no
committed test standing between a future refactor of `_promote_predecessor`
or a column rename and one of those guards silently becoming dead code — the
exact Task 7 failure mode. Restored as three permanent tests in
`tests/test_dashboard_deletes_admin.py`, modelled on the scratch versions
that already passed:

- `test_pricing_locked_by_a_proposal_refuses` — builds a proposal against
  pricing version 1 (`proposals.pricing_table_id` is non-nullable, so this
  always populates it), then deletes version 1 and asserts 409 with
  `"proposal"` and (`"rate card"` or `"locked"`) in the message.
- `test_template_locked_by_a_proposal_refuses` — same shape for
  `proposals.template_id`; asserts 409 with `"proposal"` and `"template"` in
  the message.
- `test_demo_team_booked_refuses` — books a demo against a team via
  `POST /api/v1/demos` (`demos.team_id`), then deletes the team and asserts
  409 with `"demo"` and the team's own name (`"booked squad"`) in the
  message, so a guard that fires for the wrong reason (e.g. a stray
  `ConflictError` unrelated to the booking) would still be caught by the
  content assertion, not just the status code.

Each of the three follows the existing file's pattern: a throwaway org via
`_org`/`create_org`, not the session-scoped `org_a`/`org_b` fixtures.

Also removed the stale `tests/__pycache__/test_scratch_guard_verify.*.pyc`
left behind by the deleted scratch file.

### Minor — `playbook_suggestions` orphan closed

Walked `Base.metadata` directly (not from memory — that is how the original
gap happened) for every column named `program_id` or `team_id`:

```
demo_team_members.team_id  nullable=False  fk=['demo_teams.id']
demos.team_id               nullable=True   fk=['demo_teams.id']
playbook_suggestions.program_id  nullable=False  fk=[]
playbooks.program_id        nullable=False  fk=['programs.id']
pricing_tables.program_id   nullable=False  fk=['programs.id']
projects.program_id         nullable=True   fk=['programs.id']
proposal_templates.program_id  nullable=False  fk=['programs.id']
proposals.program_id        nullable=False  fk=['programs.id']
```

**Finding reported before acting, per instruction: `playbook_suggestions` is
the only bare (no-FK) `program_id`/`team_id` column in the schema.**
`demo_team_members.team_id` and `demos.team_id` both carry a real FK and are
already handled — `demo_team_members` rows are deleted with the team,
`demos.team_id` is guarded (a booked demo blocks the team delete, so nothing
is orphaned). Every other `program_id` hit has an FK to `programs.id` and is
either already in the cascade (`playbooks`, `pricing_tables`,
`proposal_templates`) or already guarded rather than cascaded
(`proposals.program_id` — deleting a program with proposals is refused, not
cascaded; `projects.program_id` — same). No table beyond
`playbook_suggestions` needed adding.

Added `PlaybookSuggestion` to the imports and to `delete_program`'s cascade
tuple (org-scoped and program-scoped like its three siblings, using the same
generic `sa_delete(model.__table__).where(...org_id..., ...program_id...)`
loop — no special-casing needed since it takes the same two columns as the
others). Extended `test_unused_program_deletes` to build a
`PlaybookSuggestion` fixture directly via `SessionLocal` first (there is no
POST route for suggestions — they're written by the Knowledge Engine
internally, so this follows the `tests/test_assignment_skills.py`
precedent the brief pointed at), then asserts zero rows remain for
`(org_id, program_id)` after the delete.

### Test command and output

```
$ python -m pytest tests/test_dashboard_deletes_admin.py -v
============================= test session starts =============================
collected 9 items

tests/test_dashboard_deletes_admin.py::test_unused_program_deletes PASSED [ 11%]
tests/test_dashboard_deletes_admin.py::test_program_with_a_proposal_refuses PASSED [ 22%]
tests/test_dashboard_deletes_admin.py::test_pricing_locked_by_a_proposal_refuses PASSED [ 33%]
tests/test_dashboard_deletes_admin.py::test_template_locked_by_a_proposal_refuses PASSED [ 44%]
tests/test_dashboard_deletes_admin.py::test_demo_team_booked_refuses PASSED [ 55%]
tests/test_dashboard_deletes_admin.py::test_deleting_current_pricing_promotes_the_previous PASSED [ 66%]
tests/test_dashboard_deletes_admin.py::test_message_template_deletes_without_a_guard PASSED [ 77%]
tests/test_dashboard_deletes_admin.py::test_demo_team_delete_removes_its_members PASSED [ 88%]
tests/test_dashboard_deletes_admin.py::test_cross_org_delete_is_a_404 PASSED [100%]
============================== 9 passed in 3.85s ==============================

$ python -m pytest -q
........................................................................ [ 27%]
........................................................................ [ 54%]
........................................................................ [ 82%]
...............................................                          [100%]
263 passed in 27.46s
```

263 = 254 (baseline before Task 8) + 9 (this file, now 9 tests instead of 6).

### Scope discipline

- Only `app/api/admin.py` and `tests/test_dashboard_deletes_admin.py`
  touched, as instructed.
- No new column, no migration.
- `app/core/reset_taxonomy.py` and `scripts/reset_for_datacentre_demo.py`
  untouched.
- `delete_program`'s `audit_service.record` call is unchanged (still fires
  once per delete, after the cascade, before commit) — the cascade addition
  only widened what gets deleted, not the audit call.
- No ninth backend change was needed for either finding.

### Concerns

None. Both findings are closed and covered by permanent, committed tests.
