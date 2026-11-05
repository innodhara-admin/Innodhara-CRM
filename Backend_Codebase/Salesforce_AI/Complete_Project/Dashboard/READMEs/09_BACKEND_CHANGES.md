# 09 · Backend Changes

> **Read `08_PROGRESS_AND_HANDOFF.md` first.**
>
> The backend is **frozen by default**. It was unfrozen for this project for
> **exactly ten additive changes** (§1), and that set closed on 2026-08-13.
>
> **It was reopened a fifth time on 2026-09-03**, owner-directed, for the DOCX
> proposal-template subsystem — **changes 11–20 (§1a)**. That is a new subsystem
> rather than an amendment to the ten: the original set stays closed as its own
> set, and anything beyond §1a still stops the work and goes back to the owner.
>
> **This table is the authority** on what has actually been changed.

> ⚠ **Two unrelated task numberings collide in this project, and this table uses
> the older one.** "Task 11" and "Task 12" **here** are the post-Phase-1
> amendment tasks below. `07_BUILD_PLAN.md`'s **Task 11** is something else
> entirely — the Phase 2 scaffold and generation pipeline, the first task of the
> console. When citing one, say which file it comes from.

### Freeze history — rows 1–4 on 2026-08-13

| # | Unfrozen for | Re-frozen |
|---|---|---|
| 1 | **Tasks 1–10** — the eight changes | after Task 10's docs resync |
| 2 | **Task 11** — four owner-directed corrections: the skill guard counts only active holders, the vendor guard removed, two lying comments corrected | same day |
| 3 | **Task 12** — **D23**, closing a hole in D22's orphan guard | same day |
| 4 | **Tasks 10a–10c** — owner-approved reopening for **exactly two** read widenings, changes **#9** and **#10** (**D24**) | after Task 10c's resync |
| 5 | **DOCX proposal templates** — owner-directed, 2026-09-03. Ten additive changes (11–20 below), a new subsystem rather than an amendment to the ten | open |
| 6 | **The DOCX simple flow** — owner-directed, 2026-09-07. Ten more additive changes (21–30 below), one new table and one column widening | open |

**The original ten are complete and re-frozen.** Every row in §1 reads ✅.
Tasks 11 and 12 amended existing rows and added nothing; the fourth unfreeze
added two rows and was the only one that did — both pure response widenings of
the same "write path with no read path" defect the project had already ruled on
twice (D24). Phase 2 (the console) was frontend-only against those routes and
needed no further reopening.

**The fifth unfreeze is open.** It was not planned around: the console genuinely
could not deliver a branded proposal against the frozen surface, because there
was nowhere to put the uploaded document, nowhere to record where it should be
filled in, and no way to produce a file from either. Ten additive changes follow
in §1a. **They add a table and three columns**, which is the first time this
project has changed the schema — see the migration note in §1a.

---

## 1 · The ten changes

| # | Change | Files | Task | State | Tests | Guards green |
|---|---|---|---|---|---|---|
| 1 | 5 staff fields on `CreateUserRequest` / `UpdateUserRequest` / `UserResponse` | `app/api/admin.py` | T1 | ✅ | ✅ | ✅ |
| 4 | `GET /admin/users/{user_id}` + widened `UserResponse` | `app/api/admin.py` | T1 | ✅ | ✅ | ✅ |
| 2 | Delivery mode read-only on `GET /admin/settings`; honest `*_configured` | `app/api/admin.py` | T2 | ✅ | ✅ | ✅ |
| 3 | `GET /playbooks` | `app/api/ops.py` | T3 | ✅ | ✅ | ✅ |
| 7 | `contact_name` / `phone` / `email` on `GET /vendors` | `app/api/ops.py` | T4 | ✅ | ✅ | ✅ |
| 5 | `POST /admin/reset` (dry-run + apply) | `app/api/admin.py`, `app/core/reset_taxonomy.py` *(new)* | T5, T6 | ✅ | ✅ | ✅ |
| 6 | 8 guarded DELETE routes | `app/api/ops.py` (3), `app/api/admin.py` (5) | T7, T8, T11 (amendment) | ✅ (T7 ✅, T8 ✅, T11 ✅) | ✅ T7→T11 8/8, T8 6/6 | ✅ |
| 8 | Conditional `StaticFiles` mount at `/dashboard` | `app/main.py` | T9 | ✅ | ✅ | ✅ |
| 9 | `fallback_role` + `auto_approve` on `GET /approval-rules` | `app/api/ops.py` | T10a | ✅ | ✅ | ✅ |
| 10 | `lead_user_id` / `media_rep_id` / `sales_rep_id` on `GET /admin/demo-teams`, **alongside** the existing name fields | `app/api/admin.py` | T10b | ✅ | ✅ | ✅ |

**Amendments accepted after the list closed** — none of these is an eleventh change:

| Amends | Amendment | Decision |
|---|---|---|
| #5 | `audit_log` moves WIPE → KEEP | D16 |
| #5 | `user_skills` + `approval_rules` move KEEP → a new CONFIG bucket, reached by a third flag `wipe_org_config` | D16 |
| #5 | Every delete is org-scoped (`WHERE org_id = :org`), unlike the script it replaces | `06_DESIGN.md` §7.3 |
| #8 | The mount is conditional on the directory existing; a missing bundle logs a warning and the API still starts | D20 |
| #6 | `DELETE /skills`'s coverage count now joins `User` and counts only `User.is_active` holders — a deactivated user's leftover `UserSkill` row no longer counts as coverage (Task 11) | owner-directed, matches `06_DESIGN.md` §5.6's go-live skill-coverage check, which is also active-only |
| #5 | D22's orphan guard is now FK-derived **plus a declared exception list** (one entry: `playbook_suggestions.program_id`), with a scanner test that fails when a new bare reference appears — proved by emptying the list and by injecting a synthetic column, not merely by passing today (Task 12) | D23 |
| #6 | `DELETE /vendors/{id}`'s reference-scan guard removed entirely — nothing in the schema (no FK, no id-shaped column) ever references `vendors.id`; the only recorded mention, `action_items.external_wait.vendor_name`, is a free-text copy, not a pointer, so no delete can orphan anything (Task 11) | owner-verified, owner-ruled |

---

## 1a · The fifth unfreeze — DOCX proposal templates (11–20)

Owner-directed, 2026-09-03. Spec:
`docs/superpowers/specs/2026-09-03-docx-proposal-templates-design.md`. Plan:
`docs/superpowers/plans/2026-09-03-docx-proposal-templates-plan.md`, 23 tasks.
Execution ledger, which is the authority on what happened:
`.superpowers/sdd/2026-09-03-docx-proposal-templates-plan/progress.md`.

**What it is for.** The proposal path stored a Markdown body, substituted
`{variables}` and rebuilt a document from scratch with python-docx and
reportlab. Three things went wrong with that in real use: the model wrote its
own task list into the client's document, Markdown artefacts survived into the
output, and the rendered file had no branding at all because `render_docx`
starts from a blank `Document()`. The fix is to stop **generating** documents
and start **filling** them — an administrator uploads the organisation's real
`.docx`, marks where the system should write, and every proposal is
`source.docx + plan + values -> a new file`. **The source is never rewritten.**

| # | Change | Files | Task | State | Tests |
|---|---|---|---|---|---|
| 11 | `kind` on `ProposalTemplate` (`"markdown"` \| `"docx"`), defaulting to `markdown` | `app/models/program.py` | T12 | ✅ | ✅ |
| 12 | `proposal_template_docs` table — the uploaded file, its outline, its OCR and its fill plan | `app/models/program.py`, `app/core/reset_taxonomy.py` (REPLACE bucket) | T12 | ✅ | ✅ |
| 13 | `filled_json` on `Proposal`, plus `template_kind` | `app/models/proposal.py` | T12, T15 | ✅ | ✅ |
| 14 | `docx_template_service` — ingest an upload as a template version: parse, OCR, project to text | `app/services/docx_template_service.py` *(new)* | T13 | ✅ | ✅ |
| 15 | The `app/services/docx/` package — `text`, `outline`, `index`, `edit`, `fill`, `ocr`, `convert` | `app/services/docx/` *(new, 7 modules)* | T1–T9 | ✅ | ✅ |
| 16 | `docx_suggest` — the LLM placeholder-suggestion pass, every suggestion validated against the outline before it is returned | `app/ai/docx_suggest.py` *(new)* | T11 | ✅ | ✅ |
| 17 | Six template-doc routes; `template_kind` + `filled` on `GET /proposals/{id}` | `app/api/admin.py`, `app/api/proposals.py` | T17 | ✅ | ✅ |
| 18 | `build_proposal` branches on `kind`; `docx_proposal_service` builds the content | `app/services/proposal_service.py`, `app/services/docx_proposal_service.py` *(new)* | T14 | ✅ | ✅ |
| 19 | `ensure_rendered_files` branches; LibreOffice DOCX→PDF converter | `app/services/proposal_email_service.py`, `app/services/docx/convert.py` | T15 | ✅ | ✅ |
| 20 | `parse_docx_edit` / `_apply_docx_edit` — per-placeholder re-fill on edit | `app/ai/agents/proposal_agent.py`, `app/services/docx_proposal_service.py` | T16 | ✅ | ✅ |

**Also touched, and worth naming because neither is in the list above:**
`app/ai/docx_prose.py` (the grounded prose fill and its scrub-and-retry
contract) and `app/services/fill_scrub.py` (the deterministic scrubber). Both
are new files under the same unfreeze; they are the fence that keeps the model's
task list out of a client's document, and D30 records why that fence is code.

### What this did to the counted figures

`BACKEND_README.md` §"By the numbers" is resynced in the same commit. Measured
at this branch's HEAD, never in the working tree:

| Figure | Before (`aa49e80`) | After | Why |
|---|---|---|---|
| Database tables | 55 | **56** | `proposal_template_docs` |
| Model classes | 55 | **56** | `ProposalTemplateDoc` |
| Columns | 755 | **773** | the new table, plus the three added columns |
| API routes (incl. 2 health) | 151 | **157** | the six template-doc routes |
| Routes the app does not call | 70 | **76** | all six are console-only |
| Permissions | 20 | 20 | the routes reuse `manage_templates` |

> ⚠ **`scripts/check_docs_in_sync.py` cannot confirm two of these, and one of
> those two is not this feature's doing.**
>
> Its route counter imports `app.main` and counts `APIRoute` objects, and it
> returns **2** — `/` and `/health` — at every revision tried, including
> `aa49e80` before any of this work. So the routes check fails identically
> before and after, and the 157 above was instead derived by counting route
> decorators across `app/api/*.py`; that method reproduces the documented 151
> exactly at `aa49e80`, which is why it is trusted here.
>
> The tables check now fails for a different reason: its pattern is
> `\*\*{n_tables}\*\*\s*\|\s*55 model classes`, with **"55 model classes"
> hardcoded**. The README now truthfully says 56. Writing 55 to make the guard
> green would put a known-false number in the document this project calls the
> authority, so it was not done — `scripts/check_docs_in_sync.py:212` needs a
> one-word update, and that is a change to a guard, which is the owner's call.

### The rules in §2 still bind, with one exception that is stated, not assumed

**Rule 1 (additive only) is broken here, deliberately and for the first time.**
Changes 11–13 add a table and three columns. Nothing existing changes meaning:
`kind` and `template_kind` default to `"markdown"`, `filled_json` defaults to
`[]`, and a template that was Markdown yesterday takes byte-identical code paths
today. But **this project has no Alembic**, and `create_all` creates missing
tables while never adding a column to an existing one.

> ⚠ **Any environment running this branch needs three columns added by hand**:
> `proposal_templates.kind`, `proposals.filled_json` and `proposals.template_kind`.
> They were applied to the dev database on 2026-09-04 with three additive
> `ALTER TABLE ... ADD COLUMN` statements whose defaults match the model
> defaults, backup first at `data/salesplatform.db.bak-docx-20260904`.
> `proposal_template_docs` is a new *table*, so `create_all` makes that one.
> **Q17 in `05_DECISIONS.md` said this question was moot because no change added
> a column. That is no longer true** — see the correction there.

**Rules 2–5 hold unchanged.** No route here is destructive, so none writes an
audit row (rule 2); `get_org_context` still rejects `super_admin` and all six
new routes depend on it, five through `require_permission("manage_templates")`
(rule 3); nothing dashboard-related landed under `app/` (rule 4); and every row
above is ✅ only because its tests pass (rule 5).

### Two system dependencies, and no new Python package

`python-docx` 1.2.0, `lxml` 6.1.2, `pypdf` 6.16.2 and `Pillow` 12.3.0 were
already present, so `requirements.txt` gains a comment and nothing else.
`pytesseract` is deliberately **not** installed. Two system binaries are
required and are called through `subprocess`, the same way and for the same
reason:

| Binary | Version | Used by | Without it |
|---|---|---|---|
| `/usr/bin/soffice` | LibreOffice 7.3.7 | `docx/convert.py` | `ExternalServiceError`; a docx proposal produces no PDF |
| `/usr/bin/tesseract` | 4.1.1, `eng` | `docx/ocr.py` | image text is empty; the suggestion pass sees less, nothing fails |

## 1b · The sixth unfreeze — the DOCX simple flow (21–30)

Owner-directed, 2026-09-07. Plan:
`docs/superpowers/plans/2026-09-07-docx-simple-flow-plan.md`, tasks A1–A4,
B1–B3, C1–C3, J1–J3, E1–E2. Execution ledger, which is the authority on
what happened and disagrees with the plan in several places:
`.superpowers/sdd/2026-09-07-docx-simple-flow-plan/progress.md`.

**What it is for.** §1a moved proposals from *generating* documents to
*filling* them, but an administrator still had to mark every placeholder up in
a console editor — precise, and a lot of work per template. The simple flow
moves that work to the person who *designs* the document: the author writes
the placeholders into the Word file as angle-bracket tags (`<School Name>`,
`<ask:4 Units>`) and the administrator only uploads it. The intelligence moves
to proposal time, where the assistant reads the whole client, works out what
each tag means, fills what it can ground in a fact, and asks the salesperson
about the rest. **Both flows exist side by side; nothing about §1a changed.**

| # | Change | Files | Task | State | Tests |
|---|---|---|---|---|---|
| 21 | The tag grammar and the occurrence scanner — identity is per OCCURRENCE, never per literal | `app/services/docx/tags.py` *(new)* | A1 | ✅ | ✅ |
| 22 | `walk_paragraphs` and `label_for` — the walk an occurrence's ordinal indexes into | `app/services/docx/text.py` | A2 | ✅ | ✅ |
| 23 | `apply_tags` — the occurrence-addressed writer, right-to-left, refusing a stale offset | `app/services/docx/tagfill.py` *(new)* | A3 | ✅ | ✅ |
| 24 | `proposal_fill_sessions` — the working memory of one in-progress fill | `app/models/proposal_fill.py` *(new)*, `app/models/__init__.py`, `app/core/reset_taxonomy.py` (WIPE bucket) | A4 | ✅ | ✅ |
| 25 | `docx_simple` joins `markdown` and `docx` on `ProposalTemplate.kind`; `flow=simple\|complex` on the upload route; a zero-tag document refused | `app/services/docx_template_service.py`, `app/api/admin.py` | B1 | ✅ | ✅ |
| 26 | `docx_ocr` background job — OCR leaves the upload path, which drops its latency from ~10 s to under 1 s | `app/jobs/__init__.py`, `app/jobs/docx_ocr.py` *(new)*, `app/services/docx_template_service.py` | B2 | ✅ | ✅ |
| 27 | `client_dossier` — the whole client, assembled once, every section whole, fields listed explicitly so no password hash or embedding can leak | `app/services/client_dossier.py` *(new)* | C1 | ✅ | ✅ |
| 28 | `docx_tagfill` — `resolve_tags`, `answer_round`, `revise`; every resolution validated against the occurrence map and the dossier before it can become a value | `app/ai/docx_tagfill.py` *(new)* | C2, J2 | ✅ | ✅ |
| 29 | `proposal_fill_service` — the status machine, the D13 review, and the build | `app/services/proposal_fill_service.py` *(new)* | C3, J2 | ✅ | ✅ |
| 30 | Four Proposal Agent tools, and the conversation's `session_id` reaching the agent at last | `app/ai/agents/proposal_agent.py`, `app/ai/orchestrator.py` | J1, J2 | ✅ | ✅ |

**Also touched, and worth naming because neither is in the list above:** the
console gained the third flow option and its staged upload panel
(`Dashboard/src/screens/ProposalTemplates.tsx`,
`Dashboard/src/screens/docx/DocxUpload.tsx`, task B3), and the Android app
learned that a `docx_simple` proposal has a provenance card at all (task E1,
below).

### One column widening, and it reverses a decision in the plan

`proposals.pricing_table_id` and `proposals.pricing_version` are **nullable**
since 2026-09-08. The plan's D16 kept them NOT NULL and proposed a console
warning at upload time instead, on the strength of an estimate that called the
change "the most expensive this project has". Measured rather than assumed
when the owner reopened it: the live database held **six** proposals,
`Proposal.total_amount` already defaulted to `0.0`, the only aggregate over it
sums fine with `0.0`, and the Android app was **already** null-safe on all
three fields. An offering whose prices live inside its own Word document has
nothing to put in a rate card, and the simple flow never read one — every
figure in such a document comes from a tag and the salesperson's own answer.

**The markdown and complex-docx paths still require a rate card and still
refuse without one**, and a test says so: they render `{total_amount}` and
`{pricing_table}` into the body. Only the flow whose prices live in its own
document may go without.

This is the second schema change the project has made, and the first that is
not purely additive. `create_all` builds a new database correctly from the
model; **one that already exists needs
`scripts/migrations/2026-09-08_optional_rate_card.py` run once** — the rebuild
SQLite prescribes, which backs the file up first and refuses to report success
if the row count moved or a foreign key broke. Run against the development
database on 2026-09-08: 6 rows in, 6 rows out, no violations.

### What this did to the counted figures

`BACKEND_README.md` §"By the numbers" is resynced in the same commit. Measured
at this branch's HEAD in a `git archive` export, never in the working tree —
the tree carries an unrelated in-flight feature and would inflate every number:

| Figure | After §1a | After §1b | Why |
|---|---|---|---|
| Database tables | 56 | **57** | `proposal_fill_sessions` |
| Model classes | 56 | **57** | `ProposalFillSession` |
| Columns | 773 | **788** | the new table's fifteen |
| API routes (incl. 2 health) | 157 | **157** | unchanged: `flow` is a new form FIELD on an existing route, not a new route |
| Background job types | 3 | **4** | `docx_ocr` |
| AI agents / tools | 6 / 30 | 6 / **34** | `answer_proposal_questions`, `show_proposal_questions`, `confirm_proposal_values`, `show_proposal_review` |
| Permissions | 20 | 20 | the fill reuses `send_proposal` |

> **The route-counting method in §1a undercounts by exactly 2, and this
> section corrects it.** §1a says it counted `@router.*` decorators across
> `app/api/*.py` and that the method "reproduces the documented 151 exactly at
> `aa49e80`". Re-run here it gives **149**. `app/api/messages.py` declares a
> SECOND router object, `webhooks`, included separately at
> `app/main.py:179`, carrying `@webhooks.get` and `@webhooks.post`. Counting
> `@(router|webhooks).*` gives 151 at `aa49e80`, 157 at the end of §1a and 157
> now — so §1a's *totals* were right and only its stated method was
> incomplete. The 157 above is that corrected count, and the deltas in §1a are
> unaffected.

### Android — the app needed two fixes, not none

The plan (§2.6) predicted no Android change at all. Checked against the code
rather than the plan, that is **true of the question card**: `questionCard()`
takes the question verbatim, `questionBody` has no `maxLines` and no
`ellipsize`, and the candidate `ChipGroup` is `singleLine="false"`, so a round
of six questions with eleven tappable answers renders in full.

It was **not** true of the provenance card, which §2.6 never covered because
the simple flow's `source` values did not exist when it was written:

1. `ProposalDetailFragment.renderFilled` gated the whole "What went into this
   proposal" card on `templateKind == "docx"`. A simple-flow proposal carries
   `"docx_simple"`, so the one screen whose job is to say where each value came
   from showed **nothing at all** for the entire flow.
2. `sourceLabel` branched on `"ai"` and `"unfilled"` and fell everything else
   through to "From your records". The simple flow sends `"user"` (the person
   typed it) and `"default"` (they accepted the template author's suggestion
   verbatim), so both told the salesperson that a figure they had typed
   themselves came out of the organisation's database.

Both are fixed, and the three decisions now live in `ProposalFilledLines` so
they can be tested — they survived undetected precisely because they could
not be: the app's JVM suite is pure logic and carries no Robolectric, so
fragment code was untestable. Android JVM tests **38 → 61**.

---

## 2 · Rules binding every change here

1. **Additive only.** No column, no migration, no behaviour change to an existing
   route beyond the two deliberate ones in change #2. **This rule is why change
   #10 adds three ids to `GET /admin/demo-teams` alongside `lead` / `media_rep` /
   `sales_rep` rather than replacing them** — the Android app calls that route
   and may render the names, so a swap would be a behaviour change, not a
   widening.
2. **Every destructive route calls `audit_service.record`** (D13). The existing
   `delete_approval_rule` writes no audit row — that omission is **not**
   inherited, and is the reason this rule is written down. **It binds destructive
   routes only:** changes #9 and #10 widen two GETs and correctly write nothing,
   since an audit row per read would be noise in the log the reset preserves.
3. **`get_org_context` keeps rejecting `super_admin`** (D1, Q14). Untouchable.
4. **Nothing dashboard-related lands under `app/`** beyond these ten changes
   (D19).
5. **A change is not done until its tests pass and the guards are green.** "The
   code is written" and "the docs are updated" are both weaker claims than the
   one this table records.

---

## 3 · Change #2 changes an existing meaning — deliberately

The only non-purely-additive edit in the set, recorded explicitly so it is never
mistaken for a regression.

`email_integration_configured` currently reports `bool(smtp_username)`, which is
`true` the moment credentials are stored **regardless of `EMAIL_MODE`**. Mail only
leaves when both halves are set. After change #2 it reports credentials **AND**
mode, and a new `email_credentials_stored` key carries the old meaning, so nothing
loses information. Same for WhatsApp and calendar.

**If an existing test fails on this, it was asserting the misleading behaviour.**
Update the assertion and note it here.

---

## 4 · Route-count consequences

`check_docs_in_sync.py` asserts `BACKEND_README.md`'s counts and its §7.1
breakdown, and **failed until they were resynced** — Task 10, done 2026-08-13.
`python scripts/check_docs_in_sync.py` now exits 0 ending
`OK - the three documents agree with the code`.

| Figure | Before | After |
|---|---|---|
| Routes (incl. 2 health) | 140 | 151 |
| Routes under `/api/v1` | 138 | 149 |
| DELETE routes | 3 | 11 |
| Uncalled by the Android app | 59 | 70 |
| §7.1 · Organisation administration | 18 | 25 |
| §7.1 · Operations and money | 16 | 20 |

**Changes #9 and #10 move none of these.** Both widen a return dict inside a
handler that already existed, and the guard counts `APIRoute` instances — so the
count stayed **151** and `check_docs_in_sync.py` kept exiting 0 with no resync at
all. Confirmed by running it after both landed, not assumed.

Unchanged §7.1 rows: Everything else 13, Platform / Super Admin 4, Incidents 3,
Approval rules 3, Device push registration 2. Both columns sum — 59 and 70.

The `StaticFiles` mount is a `Mount`, not an `APIRoute`, so change #8 contributes
nothing to these figures. Verified by reading the guard.

---

## 4b · What the "Guards green" column means

It means **the guards were run and are in their expected state** — not that all
four exit 0. Stated exactly, as measured after Task 10c:

| Guard | State |
|---|---|
| `check_docs_in_sync.py` | ✅ exit 0 |
| `tests/test_genericity.py` | ✅ 8 passed |
| `python -m pytest` | ✅ **272 passed, 0 failed** (started 20:53:07 IST — the suite is clock-dependent, see §4a) |
| `check_hardcoded_strings.py` | ❌ 2 findings, **pre-existing and unchanged** |

`check_hardcoded_strings.py` scans Android Java. Phase 1 touched no Android code,
and the same two findings — `LoginFragment.java:101` (`setText("server: ")`) and
`SplashFragment.java:48` (`setText("v")`) — are produced by checking out the
pre-work baseline `19efa98` and re-running it. They are cosmetic and out of the
closed change list.

> **Do not write "all four guards are green."** It is false. The defensible claim
> is that the two guards this work could affect are green and the third fails
> exactly as it did before.

---

## 4a · Known defects found during this work — deliberately NOT fixed

### `playbook_suggestions.program_id` has no `ForeignKey` — schema defect, NOT fixed

`app/models/project.py` declares it as a bare `String(32)`, indexed, NOT NULL,
naming a `programs.id` that nothing enforces. Every sibling reference —
`playbooks.program_id`, `pricing_tables.program_id`,
`proposal_templates.program_id`, `proposals.program_id`, `projects.program_id` —
**does** declare one.

This is what made D22's FK-derived orphan guard blind to it, and it is why D23
had to add a declared exception list. It also means the database will neither
prevent nor clean up an orphaned suggestion row.

**Not fixed here:** adding a `ForeignKey` alters an existing table, and
`create_all` never alters — it would need a hand-written migration, and there is
no Alembic (Q17). Whoever adds one should also delete D23's exception entry and
let the derivation cover it, which the D23 scanner test will then confirm.


Out of scope for the closed change list. Recorded so they are known, not lost.

### `delete_program`'s refusal instructs the operator to do something impossible — **NOT fixed** (P13)

`app/api/admin.py · delete_program` refuses a programme that is in use with:

> *"'{name}' is used by {n} project(s) and {m} proposal(s) and cannot be
> removed. **Mark it inactive instead.**"*

**There is no way to mark a programme inactive.** `Program.is_active` is written
nowhere in `app/api/` — verified by grep, not inferred from the absence of a
`PATCH`. The programme routes are `POST /admin/programs`,
`GET /admin/programs`, `DELETE /admin/programs/{id}` and the nested pricing and
proposal-template ones; none of them touches the flag. `GET /admin/programs`
*returns* `is_active`, so the field is live and readable and simply unsettable —
the same shape of gap as `users.department` before change #1.

**This is a lying message, not merely a missing route**, and the distinction is
the reason it is logged here rather than in a wish list. A missing route leaves
the operator stuck. A message like this one sends them looking for a control
that does not exist, in a product where every other refusal names a real remedy,
and they will reasonably conclude they have missed a screen.

**Not fixed: the list stays at ten.** Changing the string is still a change to
`app/`, and it is not worth reopening a closed list for wording.

**The console must not repeat it.** Every screen renders a server refusal
verbatim (§4.1), which is right — but a verbatim rendering of a false
instruction inherits the falsehood. `Dashboard/src/screens/Programs.tsx` shows
the server's message and then says, in its own voice, that the suggested remedy
has no endpoint. That pattern is the general rule for any refusal this project
knows to be wrong: **quote it, then contradict it — never quote it alone.**

### Retiring a programme that is in use — **post-Task-25 work, not a defect**

Recorded here because P13 exposes it and nothing else records it.

There is today **no way to withdraw a programme from use.** The two candidates
both fail:

- **Delete it** — refused while any project or proposal references it, and
  rightly: `proposals.program_id` is a real foreign key, and a proposal that has
  been sent must keep pointing at what it was for. Forcing the delete would
  orphan sent proposals, which is the one thing D2/D7 kept off the table.
- **Deactivate it** — the column exists and no route writes it.

So a programme created by mistake, or one an organisation has stopped selling,
stays in every picker for ever. That is a real operational need with no path,
and it is **not** a defect in anything built here.

**The eventual fix, when the change list is next opened:** a route that writes
`Program.is_active` (a `PATCH /admin/programs/{id}` taking that field alone
would do), plus filtering inactive programmes out of the console's pickers —
Task 18's rate-card and template screens already read `is_active` and already
filter on it for status derivation, so the console side is close to free. The
checklist's per-programme items (5, 6 and 8) already count active programmes
only, so retiring one would correctly stop it dragging those rows amber.

**Explicitly not now.** The list is closed at ten and this needs an eleventh.

### An approval that silently does not happen — **NOT fixed** (P15)

Found in Task 23, by reading `app/engines/approval_engine.py` rather than by
testing it. **This is a governance hole, not a wording problem.**

`request_approval` calls `find_rule`, which orders by `rank` then `created_at`
and returns the **first** rule whose condition matches; an empty condition
matches everything, so a `{}` rule is the catch-all. When `find_rule` returns
`None`, what happens next is decided entirely by the **caller's**
`default_approver_role` — and the nine call sites under `app/` do not agree:

| entity type | call sites | with no matching rule |
|---|---|---|
| `outbound_message` | 4 | falls to `sales_lead` — a human is still asked |
| `price_change` | 1 | falls to `sales_lead` |
| `plan_change` | 3 | two fall to `sales_lead`; `planner_engine.py:479` passes `None`, and the caller then calls `activate_plan(..., approved_by="system")` |
| `proposal` | 1 | `proposals.py:318` passes `None`, and the caller sets the proposal to `APPROVED_INTERNALLY` |
| `invoice` | **0** | nothing in the backend ever requests one |

**The `proposal` row is the one that matters.** An organisation with no
catch-all `{}` rule for `proposal` — which is the state of every organisation
that has not written one, including a brand-new one — has **every proposal
approved internally with nobody asked**, and the response says
*"below every review threshold"*. That reads as a deliberate finding about the
amount. It is not: it is the absence of any rule at all, and the two are
indistinguishable from the response. The same shape applies to the plan-version
path, which activates the plan as `"system"`.

`invoice`'s zero call sites are the mirror image: an organisation can write a
careful, well-ranked set of invoice approval rules and **none of them will ever
fire**, because no code path requests an approval of that type. Nothing tells
the operator so.

**Not fixed: the list stays at ten.** Every candidate fix is a change to `app/` —
make `default_approver_role=None` require an explicit opt-in, or have
`request_approval` distinguish "matched a rule that says approve" from "matched
nothing", or give `invoice` a caller. None is a one-liner and none is worth
reopening a closed list for.

**What the console does instead.** `Dashboard/src/checklist/golive.ts` check 4
states the consequence **per entity type**, from `APPROVAL_NO_RULE` —
generated by `Dashboard/tools/dump_openapi.py`, which AST-walks every
`request_approval` call under `app/`. Nine call sites hand-copied into
TypeScript is nine things that go stale in silence; `gen:check` re-derives them
on every build, so moving or adding a call site fails the build rather than
quietly making a screen lie.

It also corrected a claim of its own. Checklist item 9's caption read *"a request
matching none of them has no approver"*, which is wrong in both directions at
once — too alarming for the seven sites that name a default, and far too mild
for the two that apply the thing unreviewed. That was a console bug and is
fixed; **the backend hole above is not**, and is what this entry is about.

**Post-Task-25 candidate**, alongside the programme-retirement note above.

### `POST /orgs` applies no domain test to `admin_email` — **NOT fixed** (P16)

`app/api/admin.py · register_staff` refuses any staff address that does not
`endswith("@" + org.email_domain)`, with *"Staff email must use your
organisation's domain @…"*. `app/api/organisations.py · create_organisation`
applies **no such test** to `admin_email` — grepped, not inferred: it validates
`email_domain` against a regex, checks the address is not already taken, and
writes the `User` row.

So the one account created before the rule exists is the one account exempt from
it, and it belongs to the administrator. Nothing is corrupted by this — the
organisation works — but it means:

- an out-of-domain first administrator is **permanent**, since `POST /orgs` has
  no inverse and no route rewrites an email;
- any check that lists staff addresses outside the organisation's domain will
  report the operator's own account as a defect, on an organisation where
  nothing is wrong.

**Not fixed: the list stays at ten.** The fix is a validation added to
`create_organisation`, which is a change to `app/`; and it would need a decision
this project has not taken — whether an existing organisation with an
out-of-domain admin should stay creatable, since the check would have refused it.

**What the console does instead.** Task 23's check 6 names the exception where it
finds it rather than filtering it out silently: an out-of-domain row belonging to
the administrator says which route created it and which rule that route skips.
Excluding it quietly would hide a real fact about the organisation.

**Post-Task-25 candidate.**

### A warning that undercounts what it warns about — **NOT fixed in the docs** (P17)

Found in Task 24, by checking that every verbatim quotation on the reset screen
traces to a file in this repository. It is a **documentation defect with a real
cost**, which is why it is logged here rather than left as an editorial note.

`06_DESIGN.md` §5.7 states the sentence the reset screen must carry, quoting D6:

> *"Resetting removes transactional data and, if you choose, the catalogue.
> Projects, plans, tasks and **the twelve engine-only tables** come back only by
> running the product…"*

`04_OPEN_QUESTIONS.md` Q13 also says twelve and enumerates twelve — but names
`03_API_SURFACE.md` §4.2 as its source, and **§4.2 lists fourteen.** Q13 drops
two: **`memory_chunks`** and **`lead_state_history`**. All fourteen are in
`reset_taxonomy.WIPE`, checked against the generated taxonomy rather than by
counting prose.

**Why this is worth a §4a entry at all.** A wrong figure in a design document
harms nobody. This one does not stay in the design document: §5.7 exists
precisely to be rendered on the reset screen, which is the single place in the
console where an operator reads a warning immediately before destroying data.
A warning that undercounts what it is warning about is the wrong direction of
wrong there — it tells the operator they are losing less than they are.

**What the console does.** `Dashboard/src/screens/Reset.tsx` renders §5.7
**verbatim**, cites it (*"Design, 06_DESIGN.md §5.7 (D6)"*), and then corrects
it in the console's own voice immediately below — the same treatment P13 gets,
and the same standing rule: **quote it, then contradict it; never quote it
alone.** The operator sees both the sentence the design asked for and the number
that is actually true.

**`06` §5.7 and `04` Q13 are still wrong**, and deliberately so: both are frozen
exploration/design records, and this project does not rewrite those in place —
`08_PROGRESS_AND_HANDOFF.md` §0.2 and §0.4 are where a cold reader is pointed at
the correction. So a future reader opening `06` §5.7 will still read "twelve".
**The screen is the only place the figure is right**, and that is the state to
be aware of, not a thing to be surprised by later.

### `BUNDLE_TRANSFORMS` is load-bearing — do not remove it as plumbing (P18)

`Dashboard/src/bundle/export.ts` carries a map with **one entry**, and one entry
with a lambda in it is exactly the shape of thing a later tidy-up deletes as
speculative generality. It is not. Without it **every demo team in a reseed
bundle is refused on re-import** — watched failing, not reasoned about.

The API is asymmetric here in a way the descriptor layer's `aliases` cannot
express:

| | |
|---|---|
| `admin.py · DemoTeamRequest` writes | `member_ids: list[str]` — `["u1", "u2"]` |
| `admin.py · list_demo_teams` reads back | `members: [{"id": …, "name": …}]` |

The descriptor already declares `aliases: { member_ids: "members" }`, and that
is correct as far as it goes — but **an alias renames a field, it cannot convert
one.** Applying the alias alone puts the read's *objects* where the server wants
*ids*, and `register_demo_team` rejects the row. `BUNDLE_TRANSFORMS` is the one
place a read value is converted to a write value, keyed `entity.writeField` so
an entry for a field that no longer exists is visibly dead, and pinned by a test
asserting every key names a real write field.

**Two related things in the same file, recorded for the same reason:**

- **`_program_code`.** `POST /admin/programs` mints a new id and nothing lets a
  client choose one, so a programme id **does not survive the reset the bundle
  exists to undo**. A bundle storing `program_id` restores playbooks pointing at
  programmes that no longer exist — and `ops.py · upsert_playbook` does **not**
  check that the programme exists, so they are stored in silence and no plan
  ever fires them. The bundle carries the programme's `code` instead, which
  `add_program` keeps unique per organisation (compared case-insensitively,
  stored uppercased). `import.ts` resolves it to the id just created and strips
  every underscore-prefixed key before sending.
- **Pricing and proposal templates take their programme in the URL**, not the
  body, so their write schemas have no field for it at all and a projection
  derived from `generated.ts` cannot carry one. Same fix, same reason.

**None of this is a backend defect and none of it needs the change list
reopened** — it is recorded here because §4a is where a reader looks for "things
about the API that are not obvious from the API", and all three are exactly
that.

### `scripts/reset_for_datacentre_demo.py` — false ordering comment — **CORRECTED, Task 11**

Its `WIPE` list carried the header comment:

> *"Everything transactional. Ordered child-before-parent so foreign keys stay
> happy even if enforcement is on."*

**That comment was false.** Five edges have the parent deleted before its child —
verified by walking every `ForeignKey` in `Base.metadata`:

```
stakeholders        -> projects   via project_id  NOT NULL
followups           -> leads      via lead_id     NOT NULL
demos               -> leads      via lead_id     NOT NULL
memory_chunks       -> leads      via lead_id     nullable
client_intelligence -> leads      via lead_id     NOT NULL
```

This is the defect that became Task 5's Critical finding: the build plan copied
this list *and its claim* verbatim. It has never bitten in the script because the
script issues `PRAGMA foreign_keys=OFF` before wiping, so the ordering it
advertises has never actually been exercised. It would bite on PostgreSQL, or on
SQLite with the pragma on.

**Task 11 corrected the comment (text only — the `WIPE` list and its order are
unchanged).** It now states the true fact, names why it has never bitten, and
points at the real source:

> **`app/core/reset_taxonomy.py` is now the correct source.** Its `WIPE` tuple is
> topologically sorted against every FK edge and is guarded by
> `tests/test_reset_taxonomy.py`, which walks the full graph rather than sampling
> pairs. **Whoever next touches the script should import from that module rather
> than maintain a second copy** — two hand-maintained orderings is how this
> divergence happened.

### `app/models/action_item.py` — `external_wait` docstring named a key no caller writes — **CORRECTED, Task 11**

The docstring documented `{"vendor_id", "promised_date", "chase_contact"}`. No
caller has ever written `vendor_id` — the only writer, `record_vendor_promise`
(`app/api/workflow.py`), writes `{"vendor_name", "promised_date",
"chase_contact"}`, and `sync_engine.py` reads `vendor_name` first. This wrong
docstring is what caused change #6 (Task 7) to write a vendor-delete guard
against a key that never exists, alongside the real one. Task 11 corrected the
docstring to the shape callers actually write and noted that `vendor_name` is
free text, not a reference to the `vendors` table — column unchanged.

> **The guard it caused was later REMOVED OUTRIGHT, not repaired**, and that is
> the part a cold reader most needs. `ops.py · delete_vendor` now carries the
> reasoning in its own docstring: nothing in the schema references
> `vendors.id` — no foreign key, no id-shaped column — and the sole appearance
> of a vendor outside its own table is a free-text JSON blob holding a **typed
> name**. Deleting a vendor cannot orphan anything, so **the delete is
> unguarded, correctly**.
>
> This has now misled the plan twice: `07`'s **Task 7 Step 5** still shows the
> guard in its code block and **Task 20 Step 3** described it as current. Both
> are annotated in place. `app/api/ops.py` is the authority.

### `tests/test_what_is_late.py` — 3 failures, timezone-dependent, test-side

Not a product defect. `assistant_engine.py` partitions on
`today_local = date.today()` (local date); the test helper `_task` builds due
dates from `utcnow()` (UTC date). On a UTC+5:30 machine those differ between
00:00 and 05:30 local, so **the suite is green for 18.5 hours a day and red for
5.5.** Proved by patching only `date.today()` to return the UTC date: all 5 tests
in the module pass, nothing else changed. One-line fix in the test helper, and
outside this project's closed change list.

> **To get a green full-suite run inside the red window, set the process
> timezone: `TZ=UTC python -m pytest -q`.** Measured 2026-08-18 at 00:54 IST —
> the plain command gave 269 passed / 3 failed and `TZ=UTC` gave **272 passed**
> on the same tree, nothing deselected and nothing patched. It works because
> `date.today()` and `utcnow().date()` then agree, which is exactly the
> condition the helper assumes; it is a real green run, not a way of hiding a
> red one.
>
> **Do not try to reproduce the patch above by monkeypatching `datetime.date`
> globally.** SQLAlchemy uses it too, so the patch breaks the DB layer and
> produces a different set of failures — attempted 2026-08-18 and discarded as
> invalid evidence.

---

## 1c · The seventh unfreeze — the MOU pipeline (31–43)

A memorandum of understanding is a **contract**, signed after a proposal has
been accepted. It is filled by the same engine as a simple-flow proposal — same
tags, same dossier, same D13 review — and it is kept out of the sales pipeline
entirely, because `inbound_engine` reads a SENT proposal as *"the deal is
agreed"* and a contract wearing a proposal's clothes would advance a closed
deal on its own. See **D38–D45**.

**The data model.** `proposal_templates.document_type` (`proposal` | `mou`),
with `is_current` now current *per (org, programme, document_type)*, so a
programme carries one current proposal template and one current MOU template.
`mou_documents` is a new table with **no commercial columns** — no
`total_amount`, no `line_items`, no `pricing_table_id`, no `project_id` —
absent rather than unused, so no aggregate can pick a contract up.
`mou_revisions` keeps what a contract said before a correction.
`proposal_fill_sessions` gains `mou_id` and `document_type`, the discriminator
without which an MOU fill and a proposal fill for the same client, programme
and chat are indistinguishable to `find_for_chat`.

**Two migrations, both run on the live database and both backing up THROUGH
SQLITE** — `data/salesplatform.db` is in WAL mode and a plain `cp` of the main
file silently drops everything not yet checkpointed (measured: 17 rows where
the live database had 18):

* `scripts/migrations/2026-09-09_template_document_type.py` — 18 rows, all
  back-filled `proposal`.
* `scripts/migrations/2026-09-09_fill_session_mou.py` — 4 rows, all
  `proposal`.

`mou_documents` and `mou_revisions` need no migration: `create_all` builds
them on the next restart, which is what a deploy does.

**New routes.** `GET /api/v1/mous/{mou_id}` returns the provenance the Android
card reads, the revisions newest-first, and whether each file exists;
`GET /api/v1/mous/{mou_id}/download?format=docx|pdf` serves the document, and
converts a missing PDF rather than refusing it. `GET /leads/{id}` gains a
separate `mous` key — **beside** `proposals`, never inside it. The payload
carries no commercial field, so a screen that sums a client's documents has
nothing to sum.

**The upload.** `POST /admin/programs/{id}/proposal-templates/docx` takes
`document_type`, defaulting to `proposal`, so nothing existing changes
behaviour. An MOU may only be uploaded as the simple flow. The response carries
`ruled_blanks` — underscore runs like `Date: ______` that are not tags, will
never be written into, and reach the client as underscores; a **warning**,
never a refusal (D43).

**The agent.** Six tools — `create_mou`, `answer_mou_questions`,
`show_mou_questions`, `confirm_mou_values`, `show_mou_review`, `correct_mou` —
shipped in **one commit** with the system-prompt paragraph that names them and
the router line that routes to them. A tool the prompt does not mention is a
tool the model does not call.

**The properties, which no tag can reach.** `scan` and `apply_tags` walk
paragraphs; document properties are not paragraphs, and the owner found the
previous client's name in thirteen metadata values across four parts of a
document this project had called clean. `app/services/docx/properties.py`
fills them from the built values. See **D45**, and the rule it establishes:
count literals over the whole package, never over the paragraph walk.

**The console** offers the document-type choice at upload, forces the simple
flow for an MOU and says why, and shows the ruled-blank warning in the success
panel.

**Measured end to end against the owner's own contract**, on a live model:
65 tags of 33 distinct literals, 12 filled without asking, **nine rounds**, a
built document with 0 tags and 0 tag-like properties left anywhere in the
package, a real LibreOffice PDF naming the new client and neither the previous
school nor its signatory, and **zero `Proposal` rows**. The four round-count
figures projected before that run (8–9, 3–4, 7, 10) were all withdrawn as
unverifiable; the design input's 8–9 turned out closest.

**The files, and what each one owns.**

| File | Owns |
|---|---|
| `app/models/mou.py` | `MouDocument` and `MouRevision`. No commercial columns, by D38. |
| `app/services/proposal_fill_service.py` | The status machine for BOTH document types. `build()` dispatches on `document_type` to `_write_proposal` or `_write_mou`; `is_mou_flow` answers "would a contract for this programme be filled by the assistant". `acknowledge_arithmetic` / `unacknowledged_arithmetic` hold D42's gate, and `_record` clears the `arithmetic_ack` flag whenever a pass touches a result or any of its operands. |
| `app/services/docx/properties.py` | D45. Fills the document's PROPERTIES, which no tag can reach. `values_from` builds the literal→value map and yields nothing for a literal whose occurrences disagree. |
| `app/services/mou_arithmetic.py` | Pure, `Decimal`. Parses an amount and checks a relation. No model, no I/O, no database. |
| `app/ai/agents/fill_tools.py` | What a fill conversation SAYS — the round, the tap suggestions, the D13 review — shared by both document types. `TOOLS` maps each document type to its five tool names, so a contract's model is never told to call a proposal's tool. |
| `app/ai/agents/proposal_agent.py` | Both documents' tools. The MOU's six are thin wrappers over handlers parameterised on `document_type`. |
| `app/api/mous.py` | `GET /mous/{id}` and `GET /mous/{id}/download`. 404 never 403, and the org filter is in the WHERE clause. |
| `app/services/docx_template_service.py` | The `mou_simple` template kind. An MOU may only be uploaded as the simple flow. |

**Still the owner's to fix, unchanged since it was first reported:** three
broken Word field references in the source MOU, at walk ordinals 209, 232 and
236, reading *"Error! Reference source not found."* and *"Error! No text of
specified style in document."* No tag can repair them and they print into
every MOU built from that template.

## 5 · Change log

*(One dated line per change as it lands: what, where, tests added, guards run.)*

| Date | # | What landed | Tests | Guards |
|---|---|---|---|---|
| 2026-08-13 | 1, 4 | 5 staff fields (`department`, `designation`, `whatsapp_number`, `max_open_tasks`, `working_days`) added to `CreateUserRequest`/`UpdateUserRequest`/`UserResponse`; `GET /admin/users/{user_id}` added (declared after `GET /users`) | `tests/test_dashboard_staff.py` new, 4/4 pass; full suite 219 passed / 3 failed (222 total; count of passing rose 215→219 as expected); the 3 failures are pre-existing `test_what_is_late.py` date-boundary failures, confirmed present before this change via `git stash` | `check_docs_in_sync.py` still fails as expected (route count now 141, resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 2 | `_settings_response` gains `email_mode`/`whatsapp_mode`/`calendar_mode`/`inbound_email_mode` (from `get_settings()`) plus `email_credentials_stored`/`whatsapp_credentials_stored`/`calendar_credentials_stored`; the three `*_integration_configured` booleans now require credentials **AND** the matching process-wide mode (`email_mode=="smtp"`, `whatsapp_mode=="cloud_api"`, `calendar_mode=="google"`) | `tests/test_dashboard_settings_honesty.py` new, 2/2 pass; full suite 221 passed / 3 failed (224 total; passing rose 219→221 as expected, same 3 pre-existing `test_what_is_late.py` failures); no existing test asserted the old meaning, so none needed updating | `check_docs_in_sync.py` still fails as expected (resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 3 | `GET /playbooks` added to `app/api/ops.py` (declared immediately before `GET /playbooks/suggestions`), gated on `get_org_context` (readable by any org member, matching its GET siblings); query params `program_id`, `phase`, `current_only` (default `True`); returns `id`/`program_id`/`phase`/`entries`/`version`/`is_current`/`updated_by` per row, org-scoped, ordered by `phase, version` | `tests/test_dashboard_reads.py` new, 3/3 pass; full suite 224 passed / 3 failed (227 total; passing rose 221→224 as expected, same 3 pre-existing `test_what_is_late.py` failures) | `check_docs_in_sync.py` still fails as expected (route count rose by 1 with this change, resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 7 | `contact_name`/`phone`/`email` fields added to `GET /vendors` response in `app/api/ops.py` (widened return dict, no route signature change, gated on `get_org_context` unchanged) | `tests/test_dashboard_reads.py` appended 1 test (4th in file), 4/4 pass; full suite 225 passed / 3 failed (228 total; passing rose 224→225 as expected, same 3 pre-existing `test_what_is_late.py` failures) | `check_docs_in_sync.py` still fails as expected (route count unchanged, resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 6 (part 1/2, T7) | 3 guarded DELETE routes added to `app/api/ops.py`: `DELETE /skills?user_id=&skill=` (natural key, matches `POST /skills`'s upsert key; refuses 409 when it is the last holder and open/in_progress/pending_review work needs the skill; role-gated identically to `POST /skills`, duplicated tuple kept deliberately per Part F #11 deferral), `DELETE /playbooks/{playbook_id}` (`manage_programs`; no reference guard — nothing points at a playbook; deleting the current version promotes the highest-version predecessor back to `is_current`, the API's only un-supersede path), `DELETE /vendors/{vendor_id}` (`manage_settings`; refuses 409 when a task's `external_wait` JSON blob references it — scanned explicitly since there is no FK; matches on `vendor_name`, not `vendor_id`, because the only writer of that blob, `POST /tasks/{id}/vendor-promise`, records a free-text name and never an id, and the `vendor_id` key in the model's own docstring comment is aspirational and never produced — `vendor_id` is still checked too, defensively). All three call `audit_service.record` (D13). Two of the brief's test setup calls didn't match the real API and were corrected: `POST /action-items` has no `required_skill` field (silently dropped; no route can set it, so the fixture task is built directly via `SessionLocal`, following the precedent already in `tests/test_assignment_skills.py`), and there is no `/tasks/{id}/external-wait` route (the real route is `POST /tasks/{id}/vendor-promise`, taking `vendor_name`/`promised_date`/optional `chase_contact_user_id`, not `vendor_id`) — no assertions were changed | `tests/test_dashboard_deletes_ops.py` new, 7/7 pass; full suite 254 passed / 0 failed (was 247 passed / 0 failed at this task's start — the 3 `test_what_is_late.py` clock-dependent tests noted in change #5's row are currently passing, not failing, at this run's time of day) | `check_docs_in_sync.py` still fails as expected (route count rose by 3 with this change, resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 5 | `POST /admin/reset` added to `app/api/admin.py` (`ResetRequest` + `reset_organisation`), consuming `deletion_order`/`KEEP`/`CONFIG`/`REPLACE`/`WIPE` from `app/core/reset_taxonomy.py` (built in the prior task, T5, already committed/tested). Dry-run vs apply gated on `body.dry_run`; apply requires `confirm_org_name` to exactly match the org's name (422 otherwise); every count/delete is `WHERE org_id = :org` (`Base.metadata.tables[name]`, iterated in `deletion_order`'s child-before-parent order, never sorted/reversed); writes `admin.org_reset` to `audit_log` (KEEP) only on apply, with `counts`/`total`/the 3 flags as detail, before `db.commit()`; gated on `require_permission("manage_settings")` (org_admin only) | `tests/test_dashboard_reset.py` new, 7/7 pass (dry-run counts without deleting; apply requires echoed org name, both wrong-name 422 and missing-name 422; flags clear only their own bucket; KEEP survives a full reset and the session still works — `/auth/me`, `/admin/users`, `/admin/settings` all still 200; another org untouched by a reset scoped to a different org; audit row written and readable after its own bucket is gone; sales agent gets 403). Every test creates its own throwaway org via `create_org(...)` — none touches the session-scoped `org_a`/`org_b` fixtures except the permission test, which only needs a 403 and applies nothing. Full suite 238 passed / 3 failed (241 total; passing rose 231→238 as expected — 231 was this task's starting baseline, not 225, because T5's own tests (`tests/test_reset_taxonomy.py`) landed in the prior task and are already included); the 3 failures are the same pre-existing `test_what_is_late.py` timezone-boundary failures, untouched by this change | `check_docs_in_sync.py` still fails as expected (route count rose by 1 with this change, resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 6 (part 2/2, T8, closes #6) | 5 guarded DELETE routes added to `app/api/admin.py`, plus a shared `_promote_predecessor(db, model, **scope)` helper used by three of them: `DELETE /programs/{id}` (`manage_programs`; refuses 409 when any project or proposal references the program via `program_id`; on success cascades — deletes the program's `pricing_tables`, `proposal_templates`, `playbooks` rows in the handler, since no FK carries `ondelete=`); `DELETE /programs/{id}/pricing/{version}` (`edit_pricing`; refuses 409 when a `Proposal.pricing_table_id` locks that version; deleting the current version promotes the highest remaining version via `_promote_predecessor(..., program_id=...)`); `DELETE /programs/{id}/proposal-templates/{template_id}` (`manage_templates`; refuses 409 when a `Proposal.template_id` locks it; same promotion, scoped by `program_id`); `DELETE /message-templates/{id}` (`manage_templates`; no reference guard — nothing points at a message template; promotion scoped by `(kind, channel)`, not `program_id`, since message templates aren't per-program); `DELETE /demo-teams/{id}` (`manage_teams`; refuses 409 when a `Demo.team_id` books the team; on success deletes its `demo_team_members` rows first, no `ondelete=` there either). All five call `audit_service.record` (D13). The brief's setup call `POST /api/v1/proposals` with body `{lead_id, program_id, title}` needed no correction: the real `BuildProposalRequest` (`app/api/proposals.py`) has no `title` field, but no model in this codebase sets `extra="forbid"`, so pydantic's default `extra="ignore"` silently drops it rather than rejecting the request — verified directly (`BuildProposalRequest(lead_id=..., program_id=..., title=...)` constructs cleanly) before trusting it, not assumed. All other setup calls (`POST /leads` with just `name`, `GET /auth/me` returning `user_id`) already matched. Guard columns were verified against the schema before trusting them: `Project.program_id`/`Proposal.program_id` (nullable, but populated whenever a project/proposal names a program), `Proposal.pricing_table_id`/`Proposal.template_id` (both `Mapped[str]`, non-nullable — every proposal built via `build_proposal` populates them, so the lock guards cannot be dead code), `Demo.team_id` (nullable, populated whenever a demo names a team). The brief's own 6-test suite only exercises refusal for the program-in-use guard; the other three guards (pricing-locked, template-locked, demo-booked) were proven live with a throwaway scratch test file (`tests/test_scratch_guard_verify.py`, not committed) that built a proposal locking a pricing/template version and a demo booked against a team, then asserted each DELETE returned 409 with the expected message — all three fired correctly, then the scratch file was deleted | `tests/test_dashboard_deletes_admin.py` new, 6/6 pass; full suite 260 passed / 0 failed (was 254 passed / 0 failed at this task's start) | `check_docs_in_sync.py` still fails as expected (route count rose by 5 with this change, resync is Task 10); `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | 8 (T9, closes #8, closes the list) | Conditional `StaticFiles` mount added to the end of `app/main.py`: `_DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "Dashboard" / "dist"`; when that directory exists, `app.mount("/dashboard", StaticFiles(directory=_DASHBOARD_DIST, html=True), name="dashboard")`; when it doesn't, `logger.warning(...)` only — no exception, startup unaffected either way. `Path` and `StaticFiles` added to the existing import block; the module's existing `logger` was reused, no second one created. The bundle deliberately lives outside `app/` (D19) so `tests/test_genericity.py` (scans `app/**/*.py`) and `scripts/check_hardcoded_strings.py` (scans Android Java) never see it | `tests/test_dashboard_mount.py` new, 2/2 pass, run and confirmed green in **both** states: bundle present (a placeholder `Dashboard/dist/index.html` created for the red run, then deleted per the brief — `Dashboard/dist/` is absent again at task end) and bundle absent; full suite 265 passed / 0 failed in both states (was 263 passed / 0 failed at this task's start, per the brief; the previously-flaky `test_what_is_late.py` trio is currently passing at this run's time of day, consistent with change #6's note that it is time-of-day dependent, not this change) | `check_docs_in_sync.py` still fails, but its route count (151) is **identical** with the bundle present or absent — verified directly by running the checker in both states — confirming the `Mount` contributes 0 `APIRoute`s exactly as `test_api_route_count_is_identical_either_way` asserts; the 5 drifts it reports (README route-count text, §7.1 breakdown/heading/sums) are the same pre-existing drift already present on HEAD before this task (confirmed via `git stash`), unrelated to this change and left for Task 10's resync; `check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings, unrelated to this change |
| 2026-08-13 | — (T10, docs-only, closes Phase 1) | `BACKEND_README.md` resynced to the code measured by `check_docs_in_sync.py`: routes 140→151 (top count row plus 2 prose mentions in §6's intro), §7.1 heading 59→70 routes, §7.1 rows Organisation administration 18→25 and Operations and money 16→20 (both the rows and their sum independently correct — the guard checks both), §13 test wording corrected from the misleading "218 pytest" to "265 collected, 265 passing" (38 files, 257 test functions, ~27s) with a new time-of-day caveat explaining `tests/test_what_is_late.py`'s 3 clock-dependent failures (test-side timezone assumption — `assistant_engine.py` partitions on local `date.today()`, the test helper on `utcnow()` — not a product defect; window 00:00–05:30 local on this UTC+5:30 machine). No file under `app/` touched. `09_BACKEND_CHANGES.md` guard column ticked for all 8 rows, unfrozen/re-frozen banner updated; `08_PROGRESS_AND_HANDOFF.md` marked Phase 1 complete, Phase 2 next | No new tests (docs-only task); full suite re-run for the record: 265 passed / 0 failed, run at 14:2x local (past the 05:30 boundary, so the `test_what_is_late.py` trio read green) | `python scripts/check_docs_in_sync.py` → **exit 0**, ends `OK - the three documents agree with the code`; `python -m pytest tests/test_genericity.py -q` → **8 passed**; `python scripts/check_hardcoded_strings.py` → **exit 1, unchanged**: the same 2 pre-existing cosmetic Java findings (`LoginFragment.java:101` `setText("server: ")`, `SplashFragment.java:48` `setText("v")`), present before this task, outside the closed change list, deliberately not fixed; `python -m pytest -q` → **265 passed** |
| 2026-08-13 | 6 (T11, amendment, RE-CLOSES the list) | **Four owner-directed corrections to a completed phase — amendments to change #6, or text-only; none is a ninth change.** (1) `delete_skill` in `app/api/ops.py`: the `others` coverage count now `.join(User, User.id == UserSkill.user_id)` and adds `User.is_active.is_(True)`, so a deactivated user's leftover `UserSkill` row no longer counts as coverage — the last *active* holder is treated as the last holder, matching `06_DESIGN.md` §5.6's go-live skill-coverage check, which is also active-only. (2) `delete_vendor` in `app/api/ops.py`: the reference-scan guard removed entirely (the `waiting`/`blockers` query and its `ConflictError`) — owner-verified that no column anywhere in the schema references `vendors.id` and `VendorPromiseRequest.vendor_name` is free text, never validated against the vendors table, so no delete can orphan anything; the route, its `manage_settings` gate, its `audit_service.record` call, and its `{"deleted": True}` response are all unchanged; the docstring now states the plain fact instead of describing a guard. (3) `scripts/reset_for_datacentre_demo.py`: the `WIPE` header's false "ordered child-before-parent" claim corrected to name the 5 real parent-before-child edges, explain why it has never bitten (`PRAGMA foreign_keys=OFF`), and point at `app/core/reset_taxonomy.py` as the correct source — comment only, `WIPE` list and order unchanged. (4) `app/models/action_item.py`: the `external_wait` docstring corrected from the never-written `{"vendor_id", ...}` shape to the shape every caller actually writes, `{"vendor_name", "promised_date", "chase_contact"}`, noting `vendor_name` is free text and not a reference — docstring only, column unchanged. `tests/test_dashboard_deletes_ops.py`: `test_vendor_delete_refuses_when_a_task_waits_on_it` replaced by `test_vendor_delete_succeeds_even_when_a_task_names_it` (asserts 200 + the task's `external_wait.vendor_name` survives the vendor's deletion, read directly via `SessionLocal`); new `test_skill_delete_ignores_a_deactivated_holder` added (skill held by the target user and one deactivated user — created via `POST /admin/users`, deactivated via `PATCH /admin/users/{id}` `{"is_active": false}` — plus an open task requiring the skill, built directly via `SessionLocal` per the existing precedent; asserts 409). All 3 previously-passing tests in the file (`test_skill_delete_uses_the_natural_key`, `test_skill_delete_refuses_when_open_work_needs_it`, `test_missing_skill_is_a_404`, `test_playbook_delete_promotes_the_previous_version`, `test_unreferenced_vendor_deletes`, `test_deletes_are_audited`) kept passing unmodified | `tests/test_dashboard_deletes_ops.py` 8/8 pass (was 7, net +1: one test replaced 1-for-1, one added); full suite 266 passed / 0 failed (was 265 passed / 0 failed at this task's start, run at 15:2x local, past the 05:30 boundary) | `python scripts/check_docs_in_sync.py` → **exit 0**, ends `OK - the three documents agree with the code`, route count confirmed still **151** (a guard-clause removal inside an existing route, not a route removal); `python -m pytest tests/test_genericity.py -q` → **8 passed**; `python -m pytest -q` → **266 passed** |
| 2026-08-13 | 5 (T12, amendment, **D23**) | **The catalogue-orphan reset guard was derived purely by walking `ForeignKey` objects, and that derivation was blind to a reference the ORM was never told about.** `playbook_suggestions.program_id` is a bare `String(32)` (`app/models/project.py`), NOT NULL, holding a `programs.id` with no `ForeignKey` — so a catalogue-only reset (`wipe_catalogue=True`, `wipe_transactional=False`) deleted every `programs` row while those rows survived pointing at dead ids, **reported `blocking_edges: []`, and proceeded, calling it safe**. `app/api/admin.py` now builds `_CATALOGUE_ORPHAN_EDGES` as `derived \| declared`: `_derive_catalogue_orphan_edges()` unchanged, plus a new hand-written `_CATALOGUE_ORPHAN_EDGES_DECLARED` holding exactly one entry (`playbook_suggestions.program_id -> programs`), each commented with why derivation cannot see it; the union is sorted so the 422 message is stable. Nothing else about the guard changed. The missing `ForeignKey` is a schema defect in its own right, logged in §4a and **not fixed** — it needs a migration and there is no Alembic (Q17). Amends change #5; **not a ninth change** | `tests/test_dashboard_reset.py` +2. (1) `test_catalogue_only_on_an_org_with_a_playbook_suggestion_refuses` — the real case end-to-end: the dry run still returns 200 and lists the edge (a dry run must never 422), the apply returns 422 naming both `playbook_suggestions` and `programs`, and **nothing is deleted** — asserted on both the programs list and the suggestion row itself. (2) `test_every_bare_star_id_column_naming_a_replace_table_is_covered` — an independent **name**-based scan of every `*_id` column in `WIPE \| CONFIG` whose stem names a `REPLACE` table, asserting each is either FK-derived or declared; it deliberately does not reuse the FK walk it is checking, and carries a `len(candidates) >= 7` sanity assertion so it cannot pass vacuously by scanning nothing. `test_catalogue_orphan_edges_match_the_schema` was widened to pin the declared set too, so a narrowing cannot hide behind a still-passing comparison. **Proved non-vacuous, not merely passing**: the declared list was monkeypatched empty and the real test confirmed to raise, and a synthetic bare column was injected. Full suite **268 passed / 0 failed** (was 266) | `check_docs_in_sync.py` → **exit 0**, route count still **151** (a widened module-level tuple, not a route); `pytest tests/test_genericity.py -q` → **8 passed**; `check_hardcoded_strings.py` → **exit 1, unchanged**, the same 2 pre-existing cosmetic Java findings |
| 2026-08-13 | 9 (T10a, REOPENS the list) | `list_approval_rules` in `app/api/ops.py` now returns `fallback_role` and `auto_approve`. Both were already accepted by `ApprovalRuleRequest` and stored on `ApprovalRule`; only the read half was missing, so a reseed bundle exported a rule set to auto-approve and re-imported one that waits for a human, silently. Field order in the returned dict now mirrors `ApprovalRuleRequest`'s declaration order (`fallback_role` after `approver_role`, `auto_approve` after `joint_condition`) so the read reads as the write's counterpart. Pure widening of an existing response dict: no new route, no new column, no field renamed or removed. **No audit row** — D13 binds destructive routes and this is a GET. Found as finding **P4** while writing Phase 2's task detail against the live spec; accepted as **D24** | `tests/test_dashboard_reads.py` +2 (6/6 in file). The second test is the one that earns its keep: it asserts a rule naming *neither* field reads back `fallback_role: null` and `auto_approve: false`, so a handler hard-coding the two keys cannot pass — this project has already shipped one guard written against a key no caller writes (§4a, `external_wait.vendor_id`). Confirmed red first with `KeyError: 'fallback_role'`. Full suite **270 passed / 0 failed** (was 268), run 20:44 local | `check_docs_in_sync.py` → **exit 0**, route count still **151** (a widened return dict is not an `APIRoute`) |
| 2026-08-13 | 10 (T10b, RE-CLOSES the list at ten) | `list_demo_teams` in `app/api/admin.py` now returns `lead_user_id`, `media_rep_id` and `sales_rep_id` **alongside** the existing `lead` / `media_rep` / `sales_rep` name fields, each id placed next to the name it resolves. The names are kept deliberately: the Android app calls this route and may render them, so replacing them would be a behaviour change to an existing route and would break rule 1 of §2. Named `lead_user_id`, **not** `lead_id` (owner's choice when asked), to mirror `DemoTeamRequest.lead_user_id` and the `DemoTeam.lead_user_id` column, so the read is a straight mirror of the write and the reseed bundle copies rather than renames; its two siblings were already `media_rep_id` / `sales_rep_id` on both sides. Values are read straight off the row — `_name()` is a second query per field and is not needed for an id. The write took ids while the read returned only names, and `User.name` is not unique, so the delete-and-recreate edit path (there is no `PATCH`) could not restore the three roles and the bundle lost them. Found as finding **P5**; accepted as **D24** | `tests/test_dashboard_reads.py` +2 (8/8 in file). The first asserts the three ids **and** re-asserts the three names still resolve, so a swap fails as loudly as an omission; the second asserts an unset role returns a key that is *present and null* — `assert key in row` before `assert row[key] is None`, because a missing key and a null both read as `None` through `.get()` and the console needs them to be different facts. Confirmed red first with `KeyError: 'lead_user_id'`. Full suite **272 passed / 0 failed** (was 270), run 20:46 local | `check_docs_in_sync.py` → **exit 0**, route count still **151** |
| 2026-08-13 | — (T10c, docs-only, re-freezes at ten) | `05_DECISIONS.md` gains **D24** (the reasoning for reopening: both are the same write-path-with-no-read-path defect already ruled on twice, at change #3 and change #7/D9; refusing buys consistency with a bundle that drops `auto_approve`, which is a correctness bug) and Part 3 re-titled CLOSED **at ten** with both rows added. This file: fourth freeze-history row, two change rows, two rules annotated (§2 rule 1 now names change #10 as its worked example; rule 2 states D13 binds destructive routes only), §4 notes the counts did not move. `BACKEND_README.md` §13 and its counts table refreshed 265→**272** collected/passing and 257→**264** test functions — the guard asserts no test figures (verified by reading it), but the count had also gone stale by 3 across Tasks 11–12 and a quietly wrong count is how "218 pytest" survived to Task 10. Route count and §7.1 untouched: neither moved. `07_BUILD_PLAN.md`: findings P4/P5 marked **FIXED**, and the four warnings they justified removed from Tasks 19, 20, 23 and 24, plus Task 15's two `notReadable` lists — Task 24's round-trip test is now nine faithful entity types with no exceptions, a strictly stronger assertion | No new tests (docs-only). Full suite re-run for the record: **272 passed / 0 failed**, 20:5x local (past the 05:30 boundary, so the `test_what_is_late.py` trio read green) | `check_docs_in_sync.py` → **exit 0**, `OK - the three documents agree with the code`, **151 routes**; `pytest tests/test_genericity.py -q` → **8 passed**; `check_hardcoded_strings.py` → **exit 1, unchanged**, the same 2 pre-existing cosmetic Java findings (`LoginFragment.java:101`, `SplashFragment.java:48`); `python -m pytest -q` → **272 passed** |
