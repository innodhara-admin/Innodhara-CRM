# 05 · Decisions

**Date: 2026-08-13.** This file records answers, not analysis. It closes the five
blocking questions in `04_OPEN_QUESTIONS.md` and the further questions raised
during design. Where a decision overrides something written in `00`–`04`, this
file wins.

`00`–`04` are frozen as the exploration record, and they are no longer the
current statement of intent.

> ⚠ **This paragraph used to say they were "still accurate about the code". That
> is no longer true, and it was the worst sentence in this folder** — the
> authority document vouching for stale files. Phase 1 added eleven routes and
> eight guarded deletes, so `00` and `03` are out of date on route counts, DELETE
> counts and several 🔴 "no endpoint exists" flags that are now closed, and `03`
> §6.3 was wrong when written. Each of those files now carries its own
> SUPERSEDED banner; **`08_PROGRESS_AND_HANDOFF.md` §0.1 is the full list.** They
> are deliberately not rewritten: rewriting a frozen record destroys what it is
> for.

> **Read `08_PROGRESS_AND_HANDOFF.md` first.** It is the entry point and states
> where the work actually stands. This file states what was decided; that file
> states what has been done.

---

## Part 1 — Decisions given in the brief

### D1 · What the Dashboard is *(closes Q1)*

A **catalogue seeding and administration console**. It spans the full 16-step
go-live checklist and holds **two sessions**: `super_admin` for step 1
(`POST /orgs`), then re-authenticating as the returned `org_admin` for steps
2–16, carrying `admin_temp_password` across the hand-off.

The `super_admin` fence in `deps.py` **stays exactly as it is**. **Q14 is closed
and is not to be reopened.** Nothing in this project may make `get_org_context`
accept a `super_admin`.

### D2 · Deletion *(closes Q4; scopes Q5)*

Option **(d) plus a narrow (a)**:

- One **"reset organisation"** operation, mirroring the KEEP / REPLACE / WIPE
  taxonomy in `reset_for_datacentre_demo.py`. *(Refined by **D16** — that
  taxonomy could not express the endpoint and became four buckets.)*
- **Per-row deletes on setup and catalogue data only.**
- **Transactional data is never per-row deleted.**

Q5's cascade analysis is therefore needed **only for the catalogue entities**.
It is answered in full in `06_DESIGN.md` §7.2 as a guard table — one refusal
condition per deletable entity.

### D3 · Architecture *(closes Q9)*

**HTTP API only.** The dashboard **never** writes to the database directly. The
reset operation is a **new backend endpoint** wrapping the existing reset logic —
not the dashboard touching SQLite.

This is binding on every feature, including bulk import and the reseed loop.

### D4 · Staff fields *(closes Q2)*

Option **(2)**: add `department`, `designation`, `whatsapp_number`,
`max_open_tasks`, `working_days` to `CreateUserRequest` / `UpdateUserRequest` /
`UserResponse`, and add `GET /admin/users/{user_id}`.

The columns already exist, so **no migration** — which also means Q17 (Alembic)
stays closed for this project.

### D5 · The environment wall *(closes Q3)*

Option **(b)**: expose the delivery mode **read-only** on `GET /admin/settings`,
and fix `email_integration_configured` so it cannot report `true` while
`EMAIL_MODE=dry_run`.

The mode is **not** moved into `org_settings`. The env stays the master switch;
the API stops lying about it.

### D6 · The reseed loop covers the catalogue only *(closes Q13)*

Projects and the twelve engine-only tables are regenerated **by running the
product**, not by the dashboard. **The UI must say this plainly** so nobody
expects a full restore. See `06_DESIGN.md` §5.7.

---

## Part 2 — Decisions taken during design, 2026-08-13

### D7 · Catalogue deletes get real endpoints

D2 grants per-row catalogue deletes; D3 bars direct database writes; and the
API has **exactly three DELETE routes**, none of them on catalogue data
(verified this session: `assistant.py:114`, `ops.py:605`, `projects.py:302`).
Those three facts are mutually exclusive as written.

**Resolved:** add **eight guarded DELETE routes**. Each refuses, with a stated
reason, when the row is already referenced by transactional data — so a
pre-go-live typo can be removed, but nothing that has been used in anger is
destroyed. Guard table: `06_DESIGN.md` §7.2.

**Editing is deliberately not added.** Part F #6 (`PATCH` for programs, approval
rules, demo teams, vendors) stays deferred. Versioned families edit by
superseding; programs, demo teams and vendors edit by delete-and-recreate. The
consequence — that an approval-rule edit is a non-atomic delete-then-create
which briefly leaves the org with no rule — is surfaced in the UI as a warning
rather than hidden. See `06_DESIGN.md` §5.4.

### D8 · Reset authorisation and guard

`POST /admin/reset`, gated by `require_permission("manage_settings")` —
**org_admin only**. Two steps: a `dry_run` call returning exact per-table row
counts under KEEP / CONFIG / REPLACE / WIPE (D16), then an apply call that
requires the organisation's own name echoed back in the body. **No environment
flag** — the route is available in every environment.

### D9 · `GET /vendors` is widened

`contact_name`, `phone` and `email` are added to the response
(`ops.py` · `list_vendors`). Without this, a vendor CSV import writes three
fields the dashboard can never read back or verify — the same "write path with
no read path" defect that `GET /playbooks` was accepted to fix.

### D10 · The dashboard is served by FastAPI at `/dashboard`

A built static bundle, mounted with `StaticFiles`. One process, one URL, no
second terminal. The built `dist/` is committed. A `StaticFiles` mount is not an
`APIRoute`, so it does not affect the route counts the docs guard asserts —
verified this session by reading `check_docs_in_sync.py`.

### D11 · Test strategy

**Pytest** for the eight delete guards and the reset endpoint — the
highest-risk code in this project — written in the existing suite's style.
**Vitest** for registry-to-schema conformance and the import validator.
No E2E, no component tests. Full strategy in `07_BUILD_PLAN.md`.

### D12 · Generated, not mirrored *(supersedes the first draft of the registry)*

The first design had a hand-written registry describing every field and its
constraints. **That is a third hand-maintained mirror of backend validation** —
the same defect as Q15, where `RoleGate.java` claims to be a 1:1 mirror of
`_MATRIX` and is one permission behind.

**Resolved:** TypeScript types and base Zod schemas are **generated from the
FastAPI `/openapi.json`**. Only what OpenAPI cannot express is hand-written:
CSV column specs, the manual's verbatim text, and dependency ordering. A
conformance test asserts every hand-written field descriptor names a field the
generated schema actually has, so **drift is a build error**. See
`06_DESIGN.md` §3.

### D13 · Audit rows on every destructive route

All eight new DELETEs and `POST /admin/reset` **must** call
`audit_service.record`. The existing `delete_approval_rule`
(`ops.py:605-622`) writes no audit row; that omission is **not** to be
inherited or copied.

### D14 · The reset taxonomy is guarded by a test

A pytest asserts that **every table in `Base.metadata` appears in exactly one
of KEEP / CONFIG / REPLACE / WIPE**. A table added later must fail that test
rather than silently survive a wipe. Verified green: **4 + 2 + 7 + 42 = 55**.

### D16 · The reset taxonomy is four buckets *(amends change #5)*

Two corrections found in review, both amendments to change #5 — **not new
backend changes**, and the list stayed closed at eight. *(It later reopened once
for two read widenings and closed at ten — D24. D16 itself is unaffected.)*

- **`audit_log` moves from WIPE to KEEP.** Requiring every destructive route to
  write an audit row (D13) while the reset destroys the audit log is incoherent.
  Its "write the audit row after the deletes" caveat disappears with it.
- **`user_skills` and `approval_rules` move from KEEP to a new CONFIG bucket**,
  reached only by a third flag, `wipe_org_config`. Without this **the reseed
  loop does not round-trip**: the bundle exports both, so a post-reset re-import
  collides — staff on duplicate email, approval rules duplicating silently.

`users` stays in KEEP under every flag, because the reset runs under an
`org_admin` session and **you cannot delete the account you are authenticated
as**. The bundle therefore excludes staff, and the export screen says why.

> The review computed the partition as "6 + 7 + 42", which is right for the
> `audit_log` move considered alone. Composed with the CONFIG split it is
> **4 + 2 + 7 + 42** — same 55. Four buckets, because a bucket named KEEP whose
> contents can be wiped is exactly the kind of lie the honesty model exists to
> prevent.

### D22 · A catalogue-only reset refuses when it would orphan *(amends change #5)*

The three reset flags are independent, so `wipe_catalogue=True` with
`wipe_transactional=False` is reachable — and it deletes REPLACE while its
WIPE-side children survive. **Verified against the live schema: 6 broken foreign
key edges, 4 of them NOT NULL.**

| Surviving child | → deleted parent | |
|---|---|---|
| `demo_team_members.team_id` | `demo_teams` | NOT NULL |
| `proposals.program_id` | `programs` | NOT NULL |
| `proposals.template_id` | `proposal_templates` | NOT NULL |
| `proposals.pricing_table_id` | `pricing_tables` | NOT NULL |
| `demos.team_id` | `demo_teams` | nullable |
| `projects.program_id` | `programs` | nullable |

This is a defect in D16's flag design, not in the implementation.
`reset_for_datacentre_demo.py` could never reach this state because it always
deleted WIPE and REPLACE together in one loop; splitting them into flags created
the hole.

**Resolved — refuse only when it would actually orphan:**

- Before applying, when `wipe_catalogue` is true and `wipe_transactional` is
  false, count the rows on those six edges.
- **Zero → proceed.** A pre-go-live org with nothing referencing its catalogue is
  precisely who this flag is for.
- **Non-zero → 422, naming the counts per edge.** Same shape as the change #6
  delete guards: refused, with the reason stated.
- **A dry run never 422s.** It returns its counts *plus* the blocking edges, so
  the conflict appears at preview rather than at apply — matching
  preview-then-apply everywhere else in the design.

**The rationale, which generalises:** *the reset must not permit in bulk what
change #6 refuses per row.* Change #6 refuses to delete a program that a proposal
references; a catalogue-only reset that deletes every program while proposals
survive is the same act at scale, and cannot be more permissive for being bigger.

### D23 · The orphan guard is FK-derived **plus a declared exception list** *(amends change #5)*

D22's guard derives its edges by walking `ForeignKey` objects on every table in
`WIPE | CONFIG` whose target is in `REPLACE`. **That derivation is blind to
references the ORM does not declare**, and this schema has one:

```
playbook_suggestions.program_id -> programs | NOT NULL | ForeignKey: NONE
```

A catalogue-only reset therefore deleted every `programs` row while
`playbook_suggestions` rows survived pointing at dead ids — and the guard
reported **zero blocking edges and proceeded, calling it safe**.

**Resolved:** the edge set is now `derived | declared`, where `declared` is a
short, commented exception list holding exactly that one entry. A test
independently scans every `*_id`-shaped column in `WIPE | CONFIG` naming a
`REPLACE` table and asserts each is either derived or declared — and it was
proved to fail, not merely pass, by emptying the declared list and by injecting
a synthetic bare column.

> **The general lesson, which is why this is a decision and not a bugfix.**
> Deriving from `Base.metadata` is right, and replacing the original
> hand-written edge list with derivation was right. But **derivation is only as
> complete as the schema's own declarations.** This schema uses bare
> `String(32)` columns as soft references in 28 of its 55 tables, so "walk the
> foreign keys" silently means "walk the subset the ORM was told about."
>
> The honest pattern is derivation **plus** a declared exception list **plus** a
> scanner that fails when a new exception appears. Derivation alone trades a
> mirror that drifts visibly for one that drifts invisibly.

Note that `playbook_suggestions.program_id` lacking a `ForeignKey` is a **schema
defect in its own right**, recorded in `09_BACKEND_CHANGES.md` §4a and not fixed
here — adding one is a migration, and there is no Alembic.

### D17 · `Idempotency-Key` is not minted, and writes are never retried

**Verified across all of `app/`:** the only middleware is CORS; no route reads
any header; no route takes an idempotency argument; `idempotency_records` is
consumed solely by `jobs/mail_poller.py` for inbound IMAP `Message-ID` dedupe;
and `outbound_messages.idempotency_key` is minted server-side as a service-layer
argument. **The server drops the header entirely.**

So the console does not send one — it would be theatre — and because there is no
server-side dedupe on admin writes, **it never retries a write automatically**.
React Query mutations run with `retry: 0`.

> This contradicts `03_API_SURFACE.md` §6.3, which advises a dashboard to mint
> keys "for any write it retries". **That advice is wrong** and is superseded
> here. It also means the Android `IdempotencyInterceptor` has always been
> sending a header into a void — harmless there, since the values it protects
> are minted server-side, but worth knowing before anyone relies on it.

### D18 · The org hand-off is one chained submit, not a secret to carry

The `admin_temp_password` is returned once and stored nowhere readable. Losing it
**strands the organisation**: no `PATCH /orgs/{id}`, and the only password-reset
route requires the `manage_staff` session that was never established.

So **no human ever handles it.** The org-creation form collects the intended
admin password up front, and one submit chains `POST /orgs` →
`POST /auth/login` (temp, held in memory) → `POST /auth/change-password`, behind
a blocking modal with no dismiss, no click-out and no escape. The console must
enforce that last call, since **nothing in the backend enforces
`must_change_password`**.

**If a step fails, the modal reveals the temp password as a recovery key**, with
the failed step named and the remaining calls listed. Hiding it there would turn
a recoverable failure into a stranded organisation.

A crash mid-chain remains unrecoverable, and `06_DESIGN.md` §12 says so plainly.

### D20 · The static mount must tolerate a missing bundle *(amends change #8)*

The mount points out of `app/` by relative path (D19), so a backend without
`Dashboard/` present would fail `StaticFiles` at import time **and not start**.
A missing console must never take down the API. The mount is therefore
conditional on the directory existing, logging a warning naming the expected path
otherwise, with a pytest asserting the app imports cleanly when it is absent.

### D21 · Partial imports are designed for, not treated as errors

D17 rules out retrying a failed write, so some rows will fail at apply time.
**Apply continues past a failure rather than halting** — stopping at row 12 of 50
leaves a half-applied file and no knowledge of rows 13–50. Failed rows are
emitted **in the input's own format** with the original columns plus an appended
`_error` column, and the parser ignores `_`-prefixed columns so **the file is
directly re-importable**. Fix in place, drop back in, repeat until it returns
empty.

### D19 · The bundle stays outside `app/` — an invariant, not an exclusion

Review expected the genericity guards to scan the committed `dist/` and fail on
the manual quotes. **Checked: they cannot reach it.**
`check_hardcoded_strings.py` scans Android Java only;
`tests/test_genericity.py` scans `<repo>/app/**/*.py` only.

**No exclusion is added** — configuration guarding a path a guard never visits
reads as protection and is not. The real rule is the invariant: the bundle lives
at `Dashboard/dist/` and the OpenAPI dumper at `Dashboard/tools/`, both **outside
`app/`**. Serving from `app/static/` would move the bundle inside a scan root and
start tripping a guard that is right to flag those strings in engine code.

### D24 · The list reopens for exactly two read widenings, then closes at ten

Found while writing Phase 2's task detail against the live spec, as findings
**P4** and **P5** in `07_BUILD_PLAN.md`:

- **`GET /approval-rules` never returned `fallback_role` or `auto_approve`**,
  though `POST` accepts and stores both.
- **`GET /admin/demo-teams` returned `lead` / `media_rep` / `sales_rep` as
  names**, while the write takes ids — and `User.name` is not unique, so no
  client can recover the id from the name.

**Both are the same defect this project has already ruled on twice: a write path
with no read path.** `GET /playbooks` entered the closed list for exactly that
reason (change #3), and `GET /vendors` was widened for it (change #7, D9). A
third instance is not a new question; it is the same question with the same
answer.

**Accepted as changes #9 and #10.** Accepting them keeps the reseed loop honest.
Refusing would have bought consistency with a bundle that silently drops
`auto_approve` — a rule set to approve itself re-imports as one that waits for a
human, and nobody is told. **That is a correctness bug, not a cosmetic gap**, and
"the list is closed" is not a good enough reason to ship one.

Both are pure widenings of an existing response dict: no new route, no new
column, no migration, and **route count stays 151** — confirmed by running
`check_docs_in_sync.py`, not assumed.

**Change #10 adds the three ids *alongside* the existing name fields, not
instead of them.** The Android app calls that route and may render the names, so
replacing them would be a behaviour change to an existing route and would break
rule 1 of `09_BACKEND_CHANGES.md` §2. The field is `lead_user_id`, not `lead_id`,
mirroring `DemoTeamRequest.lead_user_id` and the column of the same name, so the
read is a straight mirror of the write.

Neither is destructive, so **neither writes an audit row** — D13 binds
destructive routes, and an audit row per GET would be noise in the log the reset
deliberately preserves.

**The list is now CLOSED at ten.** Anything beyond it stops the work and comes
back as a question, exactly as before.

> **Superseded on 2026-09-03, and by the route this sentence prescribes.** The
> owner reopened the backend a fifth time for the DOCX proposal-template
> subsystem, changes 11–20, recorded in `09_BACKEND_CHANGES.md` §1a and in
> **D25–D30** below. The ten remain closed as their own set; the fifth unfreeze
> is a new subsystem, not an eleventh amendment to them.

## Part 2a — Decisions taken during the fifth unfreeze, 2026-09-03

### D25 · DOCX templates sit *alongside* Markdown, never replacing it

`ProposalTemplate.kind` discriminates, and it defaults to `"markdown"`. A
template written before this feature is a `markdown` template and takes
**byte-identical code paths** to the ones it took yesterday — that constraint
was written into the plan as a global one and is what makes a ten-change
subsystem safe to add to a live product.

`body_md` is still populated for a docx template: `docx_template_service` stores
a **plain-text projection** of the document there. So every existing consumer —
the Android app's narrative view, the revision trail, the bundle export, the
`content_md` field on `GET /proposals/{id}` — keeps working without knowing this
feature exists. The projection is a *view*, never the source: the source is the
uploaded file, and it is never rewritten.

### D26 · The uploaded document is immutable; a proposal is `source + plan + values`

The `.docx` is stored once and **never edited in place**. Generation loads the
untouched source, applies a *fill plan* (JSON, addressing positions inside it),
and writes a copy. Editing a proposal by instruction rebuilds from the source
again rather than from the previous output.

Two things follow, and both are the reason for the rule:

- **Formatting cannot erode across edits.** A chain of edits each starting from
  the last output would drift; each starting from the source cannot.
- **A positional path is safe to store.** `body[7]`,
  `body[29]/tr[2]/tc[1]/p[0]` mean something permanent, because the file they
  address does not change. Each plan entry also carries a **fingerprint** of the
  block it points at, verified before anything is written, so a plan aimed at
  the wrong document fails loudly instead of putting a greeting inside a pricing
  table. A new upload is a new template version with its own outline.

### D27 · Text access goes through `docx/text.py`, never `Paragraph.runs`

`python-docx`'s `Paragraph.runs` omits runs nested in `w:hyperlink` and never
descends into text boxes. **Measured across the four real documents, a `.runs`
walk found 4 of 7 occurrences, 1 of 7, 1 of 9 and 2 of 14.** Everything
therefore goes through `app/services/docx/text.py`, which works on `w:t` nodes
and reaches headers, footers, table cells and text boxes.

**The failure mode is what makes this a decision rather than a preference.** A
verification built on the same `.runs` walk agrees with itself and reports
success: the client's name is replaced in four places, the check looks at the
same four, and everyone believes the document is done. Live proof arrived at
Task 17 — on the real cover page, the client name sits in the **footer**.

**Never reintroduce `.runs`.** Word also fragments runs arbitrarily; `School
Name` is commonly three of them.

### D28 · No sample document has a live TOC field, so the static refresh is primary

Of the four real documents, one has a contents page and it is **static**: a
`w:sdt` wrapping 32 TOC1/2/3 paragraphs whose page numbers are literal text.
None has a live `TOC` field.

So the primary mechanism is the **two-pass LibreOffice refresh** — convert once
to learn where the headings actually landed, rewrite the literal page numbers,
and the document now tells the truth. The Word-field path (`mark_fields_dirty`)
is kept for documents that do have one, but it is the secondary case, not the
assumed one. When mapping headings to pages, **the pages the index itself
occupies are excluded**: measured, `Investment and Deliverables` matched pages
`[2, 27]`, where 2 is the index and 27 is the answer.

### D29 · A docx template is excluded from the bundle, not exported as its projection

The reseed bundle carries JSON. A docx template's substance is a Word file that
JSON cannot hold, so exporting it would export `body_md` — the **plain-text
projection** — and re-importing that would silently create a Markdown template
holding the text of the document with none of its design.

That is precisely the failure this whole feature exists to remove, arriving
through the reseed loop instead of through the renderer. So the export **skips**
a docx template and names it in the summary with its reason, and an import that
would supersede a current docx template is a validation **failure**, not a
warning. The bundle stays a same-organisation reseed loop (D6, §5.8); a document
that must travel is re-uploaded, which is one deliberate action rather than a
silent downgrade.

### D30 · The prose fence is code, not prompt wording

Continuing F9, F4, F23 and F28: an instruction in a prompt is a request, and the
model that ignores it is not misbehaving in any way the system can detect.

So the model's output for a placeholder passes through
`app/services/fill_scrub.py`, a **deterministic scrubber**, before it can reach
a document: meta-commentary ("I will now draft the greeting"), bracketed
instructions to the reader ("[Insert pricing summary]"), Markdown emphasis and
list punctuation, and any money figure the pricing table did not authorise are
all rejected in code. A rejection costs a retry with the reason fed back, and a
placeholder that still fails is left **blank and reported**, never filled with
something unchecked. The Android proposal screen shows those blanks first
(Task 22) precisely so a person sees the gap before the client does.

> **Open tuning question, deliberately not resolved here.** `_MONEY_MARKERS`
> contains the bare substring `"rs"` and `_PRICE_WORDS` contains `"each"`, both
> matched inside words. Measured, 5 of 6 realistic sentences were rejected:
> "co**vers** 240 students", "500 tea**chers**", "1,200 lear**ners**", "10,000
> **hours**", "r**each** 450 children". The module's own docstring makes false
> rejections an explicit accepted trade, so this is the owner's call, not a bug
> to fix quietly. The fix, if wanted, is word-boundary matching.

### D15 · Product name *(closes Q18)*

**Every user-visible surface in the dashboard says "Innodhara."** The header
reads **Innodhara · Setup Console**.

Reasoning: this is an onboarding surface, used while standing up a client
organisation, and its screens quote the Innodhara product manual verbatim.
"YuviPep" is the internal name. **No code identifier changes** — `config.app_name`,
the Android package, the database and the `YuviPep_*` documents are untouched.
The name lives in one design token, so this is a one-line reversal.

> ⚠ **Branding is write-once.** `organisations.logo_url` and `brand_colors` are
> set at creation and there is **no `PATCH /orgs/{id}`** — they cannot be changed
> afterwards through any API. The org-creation form must state this inline, at
> the field, before the operator submits.

---

## Part 3 — The backend change list is CLOSED at ten

Every one is additive. **Anything beyond this list stops the work and comes back
as a question.**

> Reopened once, on 2026-08-13, for **#9 and #10** — see **D24**. It closed at
> eight for Tasks 1–10 and closes at ten now.

| # | Change | Ties to |
|---|---|---|
| 1 | 5 staff fields on `CreateUserRequest` / `UpdateUserRequest` / `UserResponse` | D4 |
| 2 | Delivery mode read-only on `GET /admin/settings`; fix `email_integration_configured` | D5 |
| 3 | `GET /playbooks` | Part F #3 |
| 4 | `GET /admin/users/{user_id}` + widen `UserResponse` | D4 |
| 5 | `POST /admin/reset` (dry-run + apply) | D2, D8 |
| 6 | 8 guarded DELETE routes | D7 |
| 7 | 3 fields onto `GET /vendors` | D9 |
| 8 | `StaticFiles` mount at `/dashboard` | D10 |
| 9 | `fallback_role` + `auto_approve` onto `GET /approval-rules` | D24 |
| 10 | `lead_user_id` / `media_rep_id` / `sales_rep_id` onto `GET /admin/demo-teams`, alongside the names | D24 |

**Explicitly still deferred:** Part F #6 (PATCH routes), #7 (webhook auth),
#8 (publish the permission matrix), #9 (Pydantic sub-models for `entries` /
`condition`), #10 (validate the seven dials), #11 (`POST /skills` org check),
#12 (reconcile the ungated GETs).

Consequence of deferring #9 and #10: **the dashboard validates client-side only**
— that is the answer to Q6, option (i). Those rules live in the UI where the
engines cannot see them, and every screen carrying such a rule says so. See
`06_DESIGN.md` §3.3.

---

### D31 · Identity is per occurrence, never per literal

`<ask:1 Unit>` appears four times in the owner's Innovation Lab template and
nine times in the YuviPep 360 one — in different rows, about different items.
They are not one question with one answer. Each occurrence gets its own
`tag_id` from `sha1(walk_ordinal # nth_in_paragraph)`, and each stores its own
value, so a later correction touches one cell.

`docx_text.replace_token` would have written one answer into all of them,
which is exactly why nothing in this flow works on literals. What tells two
occurrences of the same literal apart is the **row label of the table cell**
they sit in — measured, that is what separates the four `<ask:1 Unit>`, and it
is what the question and the review both show the salesperson.

### D32 · The model is given the whole client, assembled once

Measured on the busiest real client: a complete dossier is about 51,500
characters against a context window of a million. There is no size reason to
summarise, sample or cap anything, so `client_dossier.build` does not. The
first draft capped meetings at five and notes at ten and would have hidden
exactly the sentences the fill needs — the transcript line that says which
fortnight in September avoids the exam block.

Two tables are excluded on quality grounds rather than size: `ai_decisions`
(feeding a model its own earlier guesses invites it to treat them as fact) and
`progress_events` (state-machine bookkeeping). Removing them makes the dossier
better and smaller at once.

`DOSSIER_CHAR_CEILING = 60,000` is a safety valve, not a budget. Over it,
records are dropped oldest-first from the largest section and **what was
dropped is stated in the prompt** — a model told "the twelve oldest notes were
omitted" can ask; one handed a silently truncated dossier cannot.

### D33 · A fill is a row, not the chat transcript

`app/ai/conversation.py` replays twelve turns inside a six-thousand-character
budget and prunes at sixty rows. A twenty-five-tag fill with a dozen
clarifications would lose its own working memory half way through. So the
state is `proposal_fill_sessions` — the occurrence map, every resolved value
with its source and citation, and every question asked — and the transcript
stays what it is: a record of what was said.

A fill is found by chat session, client and programme, and is **one person's**:
a chat id is minted by the client app, so the lookup is scoped to the user
whose conversation it is. A session untouched for seven days is abandoned on
the next read rather than resumed, which is what makes "never resumed
silently" true without a scheduled job to forget to run.

### D34 · Confidence decides whether to ask; a human decides whether to write

Two different jobs, and the first draft of the plan conflated them.

`FILL_CONFIDENCE_THRESHOLD = 0.80` decides whether the assistant asks a
question. It is **self-reported by the model and uncalibrated**, so it is not
allowed to decide anything else. Before any document is produced the assistant
posts one message listing **every** value about to be written — including the
ones filled silently at high confidence, which are the reason the review
exists — with where each came from. `ready` is reachable only from
`reviewing`, and `mark_ready` refuses from anywhere else.

`ask` and `ask_calculate` tags always ask, whatever confidence comes back:
writing `ask:` is the template author asking to be asked.

Lines that say exactly the same thing collapse into one carrying a count. Nine
identical lines for a client name repeated in three footers is nine lines a
reader's eye slides over, and a review nobody reads is the formality this
decision exists to prevent.

### D35 · A citation is a path into the dossier, or it is not a citation

A value the model filled must name the fact it came from, and that name is
resolved against the dossier that was actually sent: `client.name`,
`contacts[0].title`, `meetings[2].transcript`. A resolution carrying no
citation, or one naming a fact that is not there, is **downgraded to a
question whatever confidence it claims**.

Free-text citations were considered and refused. "The transcript of the 14 Aug
meeting" cannot be checked, and an unchecked citation is not a guard — it is a
second opinion from the same model that produced the value. The cost of
demanding a resolvable path is one extra question when the model writes a path
that does not resolve; the cost of not demanding one is a fabricated fact in a
client's proposal. This is the same discipline `docx_suggest._validate`
already applies to anchors (D30's family), applied where being wrong is more
expensive.

### D36 · The assistant never writes its own figure

For `<ask_calculate:…>` the assistant reasons as far as the rate card and the
transcripts let it, **states the conclusion it reached in plain language, and
asks**. Whatever the person replies is written verbatim, so someone who
answers "18,00,000 all inclusive" gets exactly that. The default inside the
tag is context for the question, not a rule: nothing validates the answer
against it and nothing silently substitutes it.

The model's own figure is offered as a tappable candidate and is never written
on its own — and a value the scrub rejected is not offered even as a tap,
because tapping is not typing. **No number reaches a document unless Python
computed it from the locked rate card or a person typed it.** There is no
third way in.

`fill_scrub` fences values the MODEL wrote, with an empty set of allowed
amounts, which follows from the same rule. It does not refuse a person their
own words — that re-asks one question for ever — but it still runs on them,
and its reasons ride along for the review to show.

### D37 · A rate card is optional when the document carries its prices *(supersedes the plan's D16)*

An offering whose prices live inside its own Word document has nothing to put
in a rate card. Requiring one made the salesperson meet *"No pricing table for
this program"* at the **end** of a conversation they had already answered every
question in, and nothing the client sees ever depended on it.

The plan kept the requirement and proposed a console warning at upload time
instead, on an estimate that called the alternative "the most expensive change
this project has". Measured when the owner reopened it on 2026-09-08, it was
not: six proposals in the development database, `total_amount` already
defaulting to `0.0`, one aggregate that sums fine with `0.0`, and an Android
app already null-safe on all three fields. **The estimate, not the constraint,
is what kept the worse design.**

So `proposals.pricing_table_id` and `pricing_version` are nullable. Where a
rate card exists it is still used and the commercials are still computed by
`compute_totals` from the locked version. Where it does not, the record
carries an empty commercial — `total_amount` 0.0 and no line items — rather
than a missing one. **The markdown and complex-docx paths still refuse without
one.** This retires the console half of the plan's D16: there is no late
failure left to warn anybody about.

---

## Part 4 — Questions left open, and where they land

| Q | Status |
|---|---|
| Q6 · unvalidated dials and JSON blobs | Answered as **(i) client-side only**, per D12's boundary. Backend validation stays deferred |
| Q7 · create-but-never-edit entities | Accepted. Delete-and-recreate, with the non-atomic risk surfaced in the UI |
| Q8 · five admin GETs readable by any org member | **Not changed.** The dashboard is an org_admin tool, so it never depends on the looseness; flagged, not fixed |
| Q10 · unauthenticated WhatsApp webhook | Out of scope. Remains open for whoever owns risk |
| Q11 · `INBOUND_EMAIL_MODE` / F35 | Checklist item 16 is shown as **permanently unavailable**, with the reason. Option (ii) |
| Q12 · skill vocabulary | Free text, with autocomplete from skills already held in the org, plus the go-live coverage check. **No hard-coded taxonomy** — the genericity guards would reject one |
| Q14 · the super-admin fence | **CLOSED. Do not reopen** |
| Q15 · permission-matrix mirroring | The dashboard **does not mirror the matrix**. It is org_admin-only and lets the server 403 rather than pre-judging. No third copy is created |
| Q16 · push cannot reach a phone | Out of scope. The dashboard surfaces no delivery claims it cannot verify |
| Q17 · no Alembic | **Answered in practice, 2026-09-08: a `scripts/migrations/` directory with one dated, idempotent, self-verifying script per change.** The first is `2026-09-08_optional_rate_card.py` (D37), which backs the database up, does the rebuild SQLite prescribes, and refuses to report success if the row count moved or a foreign key broke. It is not Alembic and does not pretend to be — there is no version table and no downgrade — but it is a documented, repeatable, checked path, which is what this row was asking for. Everything below still stands as the history. **No longer moot — corrected 2026-09-03.** It was moot while no change added a column. The fifth unfreeze adds a table and **three columns** (`proposal_templates.kind`, `proposals.filled_json`, `proposals.template_kind`), and `create_all` creates missing tables but never adds a column to an existing one. The dev database was migrated by hand with three additive `ALTER TABLE` statements on 2026-09-04; **any other environment on that branch needs the same three**. Alembic, or a documented ALTER script, is now a real decision someone has to take. See `09_BACKEND_CHANGES.md` §1a |
| Q19 · demo-only operational facts | The backend base URL is a **field in the app**, defaulting to the config default of `8000`. Nothing hard-codes `9010` |

### D38 · A signed MOU is its own record, never a `Proposal` *(D-A)*

An MOU is signed **after** a proposal has been accepted. A `Proposal` row is
read by five things that describe a live deal, and `inbound_engine` treats a
SENT proposal as *"the deal is agreed"* — so a contract wearing a proposal's
clothes would arrive on an already-closed deal and advance its state on its
own.

`mou_documents` therefore has **no `total_amount`, no `line_items`, no
`pricing_table_id` and no `project_id`** — absent, not merely unused, so that
no aggregate written later can pick a contract up by accident. The previous
session shipped *"Total amount: 2200"* for a document reading Rs. 15,00,000 by
carrying the complex flow's machinery across without asking whether its
premise came too. A table with no total cannot make that mistake.

The separation is kept at every layer, not only in the schema: `GET /leads/{id}`
carries `mous` **beside** `proposals` and never inside it, and the API payload
omits the commercial fields entirely so a screen that sums a client's
documents has nothing to sum.

### D39 · One programme carries one current template *per document type* *(D-B)*

`proposal_templates.document_type` is `proposal` or `mou`, and `is_current` is
current *per (org, programme, document_type)*. Without it a programme could
hold one current template and an MOU upload would retire the proposal's.

Four call sites move together and must stay together: the retire loop in
`docx_template_service`, `_promote_predecessor`'s call site in `admin.py`,
`proposal_service._current_template`, and `proposal_fill_service._current`.

### D40 · One fill session serves both documents *(D-C)*

`proposal_fill_service` is ~1,100 lines, of which only the *build* half is
document-specific. The status machine — `gathering → asking → reviewing →
ready → built`, `mark_ready` as the only door to `ready`, the seven-day sweep,
the correction path — is entirely document-type-agnostic and is inherited
whole rather than duplicated.

`proposal_fill_sessions` gains `mou_id` and `document_type`. The discriminator
earns its place: without it an MOU fill and a proposal fill for the same
client, programme and **chat** are indistinguishable to `find_for_chat`, and a
reply about one would silently land on the other.

### D41 · Each question is asked once, grouped by section *(D-D)*

`open_questions` sliced raw *occurrences*, so a literal appearing five times
filled five of a round's six slots and the person was asked the same question
five times in one message.

**This was a latent defect in the proposal flow too, and had always been.** It
was invisible there only because the repeated literal in the tagged proposal
was `<School Name>` — a *semantic* tag, filled silently without ever being
asked. The MOU's `<ask:75>` made it visible; the fix is in the shared code.

Two corrections the first version got wrong, both measured against real
documents:

* **The collapse key is `(raw, context)`, never `raw` alone.** The tagged
  proposal's `<ask:1 Unit>` appears four times with the contexts "Magazine
  Rack", "Projector", "Audio and Mic System" and "First Aid Box" — four
  questions that merely share a default. Keying on the literal gives them one
  answer, which is the `replace_token` bug D1 exists to prevent arriving at the
  question layer.
* **`open_questions(limit=None)` stays uncollapsed and ungrouped.**
  `apply_answers` hands it straight to the model, and narrowing it there leaves
  occurrences permanently unanswered. Six is what a *person* is shown (D5); the
  model gets everything (D8).

Section grouping is **MOU-only** and keys on a style *prefix*
(`Heading…`/`Title…`), not a substring — `TableHead1` is the style of every
table header cell in the owner's MOU, and a substring test made 26 of them
into sections.

### D42 · A contract's arithmetic is checked, never computed *(D-E)*

Where a contract states a price, a count and a total, the two can disagree and
nothing would notice. The model is asked only **which tags relate** — tag ids
and an operator, never a figure — and the relation is rebuilt from
`result`/`op`/`operands`, so a model that smuggles a value has it dropped. The
check's only output is a sentence on the review line; **the written value stays
exactly what the person typed** (D15).

It refuses to guess, and that is the design: `parse_amount` returns `None` for
a range, for "1 Set", and for "second week of February 2027". A spurious
warning on a negotiated figure teaches the reader to dismiss the warnings,
which destroys the only thing the check is for.

An approval with a mismatch standing is refused **once**, naming the two
figures. Refusing twice would teach the same lesson; a negotiated total that is
not price × students is a normal thing for a contract to contain.

### D43 · A ruled blank is a warning, never a refusal *(D-F)*

`Date: ___________` is an underscore run the author meant as a fill-in. It is
not a tag, nothing will ever write into it, and it reaches the client as
underscores on a document they are asked to sign. The upload **succeeds** and
says so: refusing would leave the author with no template at all over
something only they can fix, in a file only they have. Counted over the whole
walk, not the body.

### D44 · One agent owns both documents; a sent contract is never rewritten

**Routing.** The fast-tier router never has to tell a proposal from a contract,
because one agent owns both. The router line names memoranda of understanding
explicitly — measured before the change, the word appeared nowhere in it, so
*"create the MOU for IBC"* matched nothing and fell back to `query`.

**The tools and the words that describe them ship in one commit.** A tool the
system prompt does not name is a tool the model does not call: the previous
session added the fill tools without telling the agent they existed, and the
agent called `create_proposal` six times and `answer_proposal_questions` zero,
in front of the owner.

**The wrong tool must be harmless.** `create_mou` on a fill that is already
open *returns* `{already_open, still_to_answer, what_to_do}` naming the tool
that moves it on — a prompt is advice, a tool result is fact, and on the fast
tier advice is not enough.

**`edit_narrative` and `update_line_items` refuse for a contract, before
resolving anything.** For a document filled from its own tags they would
rewrite the *record* and leave the `.docx` untouched, reporting success over a
file that never moved. For an MOU it is worse: `_resolve_proposal` falls back
to the client's most recent proposal, so "make it warmer" in a contract
conversation could rewrite an unrelated **proposal** for the same client.

**A correction rewrites the same row** — so the id the salesperson holds keeps
working — writes the file anew rather than over a path a reader may already
have, clears `pdf_path` *before* re-converting so a failed rebuild cannot leave
yesterday's PDF beside today's document, and is **refused once the contract has
been sent**, on the status or on `sent_at`, whichever is set. There is no
`accepted` state: signing an MOU happens on paper and this system cannot
observe it.

### D45 · A tag cannot reach a document's PROPERTIES, and the build must

`scan` and `apply_tags` both walk **paragraphs**. Word's document properties
are not paragraphs, so every part of the fill machinery is blind to them.

The owner found this by opening a contract this project had called clean and
seeing the previous school's name in Word's title bar. Measured across the
package, the client was in **thirteen** metadata values across four parts —
`docProps/core.xml` (including the school's own signatory as `dc:creator`, the
*author* of our document), `docProps/app.xml` (including `<Manager>`, which the
body renders through a `DOCPROPERTY` field, so that one is on the page),
`docProps/custom.xml`, and Word's `customXml` cover-page store, which carried
the school's address, its student count and the contract value.

The template neutralises all of them, so it names nobody — and therefore
**nothing filled them**. `_write_mou` now writes the properties from the filled
values, after `refresh_static` because LibreOffice rewrites the whole package.
A literal it cannot fill is **blanked**, never left standing: a signed contract
whose properties read `<School Name>` is the defect, not a smaller version of
it.

**The general rule this establishes: count literals over the whole package,
never over the paragraph walk.** A `.docx` is a zip of many parts, and the walk
is one of them.

### D46 · "All the suggested values are fine" means the questions on screen *(owner, 2026-09-11)*

The owner's first contract through the assistant, for Orchid International
School, stalled twice in three replies. *"Yeah all are fine, only the date will
be 11.09.2026"* settled the date and nothing else, so the same three questions
came back. The round's own tap, *"All the suggested values are fine"*, was then
read by the fast-tier model as an approval: it called `confirm_mou_values` with
forty-four questions open, the tool crashed on `mark_ready`'s refusal — worded
*"This proposal has not been through its review yet"* — and the model
improvised a paragraph about checkpoints.

**One cause under both.** `apply_answers` hands the model every outstanding
question (D8), and nothing told it which ones the person had been shown, so
"all" had nothing to refer to. Replayed against the live model, twice each,
with nothing written: the first reply accepted none of the round; the tap, had
it reached the right tool, accepted **forty of forty-four — thirty-seven of
them never shown**.

**The owner's ruling: an agreement reaches only the round on screen.** Every
other question is asked in its own round. The round is marked in the answer
prompt, and — because a prompt is advice — `answer_round` also refuses a value
equal to the author's suggestion for a question that was not on screen, unless
the reply itself names it, as whole words: "11.09.2026" does not name a
quantity of 1. A question sharing `(raw, context)` with one on screen *was* on
screen, because a round shows one question per key (D41); keyed on the tag id,
its twin would come back next round and the loop would return by another door.

**D8 is untouched.** A figure the person *states* still settles every question
it answers, whichever round that question sits in. Measured live: *"…but it is
40 workshops, not 32"* set both unseen workshop counts to 40.

**The same ruling covers proposals.** The rounds, the tap and
`_confirm_values` are shared code, and the owner chose to fix both rather than
leave the proposal flow with the defect.

**An approval with questions still open is harmless** — D44's rule, applied to
the tool it had missed. `confirm_*_values` returns `{still_asking,
still_to_answer, what_to_do}` naming the document's own answer tool instead of
crashing, and an early `approved=false` gets the same answer rather than a
review list with holes in it.

Measured after the change, on the live model over the same fill: the first
reply settled all four questions shown, and the tap settled the three shown and
their twin, and nothing else.

### D47 · A reply always reaches the fill, and the author's own suggestion reaches every place that asks for it *(owner, 2026-09-11)*

The owner built their first contract end to end — Orchid International School,
forty-seven questions, a clean document with every value in it — and reported
two things: the MOU could not be opened anywhere in the app, and *"some
questions are repeatedly asked even if the answers are given"*.

**Measured on that conversation, not inferred.** `asked_json` recorded **eleven
rounds against twenty replies**. Nine of the owner's answers reached no tool at
all: the model restated the round it had just been handed — *"The only
remaining MoU question is … Reply 'Innovation Nexus' to finish"* — and the fill
sat where it was. Twice in a row, for the last question of the contract. On top
of that the programme name was asked in **four separate rounds**, the YuviPep
representative's name and title in two each, and the completion date in three:
each is a different place in the document, and every one reads the same to the
person being asked.

**Two causes, and the same sentence under both.** A prompt is advice. The
system prompt has said since A2 that every reply about an open document goes to
the answer tool, and `_open_fill` catches the model reaching for `create_mou`
instead; neither catches the model reaching for *nothing*.

- **`BaseAgent._tool_the_turn_needs`** is asked when a turn called no tool at
  all, and `ProposalAgent` answers it with the document's own answer tool while
  a fill is `asking`, carrying the person's words as they typed them. Asked
  BEFORE the reply is taken, so the model writes its answer from what the tool
  returned rather than from what it guessed. Only when *nothing* ran: a tool the
  model chose for itself — `show_mou_questions` for "which questions?" — is
  never second-guessed.
- **A fill at its REVIEW is never forced.** `confirm_*_values` is the one tool
  that writes a client-facing document, and a tool call nobody made must not be
  the thing that ships one.

**Places that read the same settle together — the suggestion only.** Whether
two places are one question cannot be read off the words. `docx_tagfill.reads_as`
keys a question on what a person actually reads, its own wording and the value
offered, and `answer_round` then treats a place that reads the same as a place
that was on screen (extending D46's fence) and spreads the answer to the others.
**What spreads is the author's own suggestion and nothing else.** It is what
they wrote in every one of those places, so putting it back is a surprise in
none of them, and "All the suggested values are fine" is the sentence that was
costing the owner a round each time. A figure the person *typed* stops at the
place they were shown, and a value the model answered itself is never
overwritten.

**The round is NOT collapsed, and that is the owner's second ruling.** Asking
once and showing "(in 4 places)" was the first choice, and the proposal flow
shows why it cannot be: a model that writes *"How many of these do you want?"*
for the Laptops row and the Interactive Panel row makes them read identically,
so they would merge into one line, the round would stop naming either row
(D9), and one typed quantity would land in both. `test_fill_agent`'s
first-round test is that case, and it caught this. Every place keeps its own
line and its own label; what changed is that one reply now settles all of them.

**The app can read a contract.** `MouDetailFragment` — the client screen's
contract row now opens it — with what went into it, the corrections, the
projected text and the document itself through `PdfViewerFragment.forMou`.
Deliberately without a pricing block, a narrative edit, a re-upload or an
approve-and-send: an MOU has no commercials and no send path, and a screen that
offered them would offer what the backend refuses. `MouLines.canBeRead` gates
the button on **`has_docx`, not `has_pdf`** — F3 leaves `pdf_path` null when
LibreOffice fails and `/download?format=pdf` renders on the way out, so gating
on the PDF would hide the document for exactly the contracts needing the retry.
`MouLines.versionTag` keys the cache on the correction count, because a
correction writes new files against the same row.

### D48 · The fill has a clock, the card is the question, and one conversation fills one document *(owner, 2026-09-11)*

The owner ran a second contract through the app after D47 shipped and reported
three things. All three are in the record, and none was the thing D47 fixed —
that worked: the forced call fired once at 06:06:31 and the spreading once at
06:07:04.

**1. "It has no date awareness — today is 11 September 2026 and it's still
stuck in the past."** It was. **No date reached any of the three fill prompts
at all.** The template's author wrote *"1.9.2026"* for the modified date and
*"First Day of September, Two Thousand Twenty-Six (01-09-2026)"* for the
agreement date, and nothing in the system could tell either had gone by.
`docx_tagfill` now takes `today`, the service passes the ORGANISATION's today
rather than the server's, and all three prompts carry it — so *"the 11th"*
resolves and a stale suggestion can be recognised for what it is.

**The owner's ruling: offer today, and still ask.** Where the author's whole
suggestion is a date that has passed, the round offers today as the tap,
written the way they wrote theirs — `1.9.2026` becomes `11.9.2026`, same
separator, same padding — and the line says *"the template's date has passed;
today is …"* rather than calling today the template's suggestion. The author's
own text stays on the list. **Only when the whole suggestion is a date.**
Turning *"First Day of September, Two Thousand Twenty-Six"* into today's date
is prose this code would be inventing, which D15 forbids; the model is told
the day and can offer the wording instead.

**2. "The questions asked by the AI mismatch the questions in the yellow
chip."** The app draws both the model's prose AND the card the tool built. On
the owner's round of six the prose asked for two, on the same screen. **The
card is built from the document, so the card is the question:** the agent's
reply is now the card's own opening line, and the prose that argued with it is
discarded. `BaseAgent.CARD_TOOLS` is empty by default, so no agent gets this
by accident; `ProposalAgent` sets it to the fill tools.

**3. "In the very last, something went wrong."** Two separate failures in two
consecutive turns, and `asked_json` recorded **seven rounds for nine replies**.

- *06:07:41.* They said *"All the suggested values are fine"*; the model
  called `show_mou_questions`, which lists and answers nothing. A tool HAD
  run, so D47's force stood aside and the answer was lost. The rule is now
  **"was the person asked anything"**, not "did a tool run" — a turn that ends
  without a question card, while a fill waits on them, has not dealt with
  their reply. `_tool_the_turn_needs` is given the tools that ran, and
  `ProposalAgent` stands down only for one that could have ACTED on the
  words. That last clause is D44 kept: `confirm_*_values` with questions open
  returns its redirect and the fill stays exactly where it was, rather than
  being advanced by a sentence nobody read as an answer.
- *06:08:15.* *"Yes show the remaining"* was routed to the **query agent**,
  which has no MOU tools and no idea a document was open, and improvised: *"I
  can't see the MoU's remaining fields from here… where is the MoU form you're
  filling?"* The router is a fast model reading one sentence and four quoted
  turns, and it falls back to `query` whenever unsure. **While a document in
  this conversation is waiting on the person, the conversation belongs to the
  agent that owns it.** Scoped to a fill that is asking or at its review: once
  it is built or abandoned the chat is ordinary again, which matters, because
  otherwise one unfinished contract would capture every question a salesperson
  ever asked in it.

**One conversation fills ONE document at a time.** `test_tool_choice` found
this while the rest was being written: the loop-breaker is keyed on the
document type, so `create_proposal` with a contract mid-fill sailed past it and
opened a SECOND fill — two sets of questions in one chat, and a reply reaching
whichever the model named. It now returns the same shape the loop-breaker does,
naming the other document's answer tool (or its confirm tool, if that document
is at its review — the moment the person is closest to having one and can least
afford to lose it).

**Two tests changed meaning, and both are recorded rather than quietly
adjusted.** `test_show_mou_questions_answers_nothing_and_changes_nothing` now
asserts that no VALUE moved rather than that the whole record is untouched: the
turn does pass the reply on, and an answer pass re-words a question it could
not settle. And
`test_without_the_prompt_paragraph_a_reply_misses_the_mou_tools` **inverted**:
it pinned the system prompt as the only thing making the answer tool reachable
on a reply, and that is no longer true, because an open document now says so
from inside a tool result. The paragraph is still load-bearing for STARTING a
contract, which no tool result can announce, and
`test_without_the_prompt_paragraph_the_mou_tools_go_invisible` pins that,
untouched.

Mutation check: 14 mutants, 13 killed. The survivor removes `_asked_a_question`
from `BaseAgent`, which every current path also covers through
`ProposalAgent.CHANGES_THE_FILL`; it is the general fence for an agent whose
question card comes from a tool that is not a fill's, and nothing in this agent
takes that path today.

### D49 · A tool that could not act has not dealt with the reply *(owner, 2026-09-11)*

The owner's third contract, 10:19–10:24, with D47 and D48 live. Most of it
worked: every reply reached the fill, the prose above each card was the card's
own opening line, and the count came down 43 → 34 → 27 → 23 → 16 → 12 → 8.
Two turns still went wrong, and they are the same defect wearing two hats.

**10:24 — "Instead of 4k make it 9k"**, which answers the question on screen.
The model reached for `correct_mou`, which edits a contract that has already
been BUILT. It failed — *"There is no MOU from this conversation that I can
correct"* — directly under a card asking them for four values, and the words
were dropped. D48 stood the force down for any tool that COULD have acted;
this one could not, and said so.

**10:21:49 — "All the suggested values are fine"**, the round's own tap. The
model read it as an approval and called `confirm_mou_values`, which returned
its D44 redirect. The redirect's own words are *"pass their words to
`answer_mou_questions`"*, and nothing did, so the owner typed *"Answer the
remaining questions"* to get the same round back.

**The rule is now that the tool must have ACTED.** Three ways it has not, and
each leaves the person unanswered: it raised (`ok` false, which is how
`correct_mou` reported having nothing to correct); it returned the
`already_open` or `still_asking` redirect, which say in their own words where
the reply should go; or it returned its own `ok: false`. A tool that ASKED
something is not judged here at all — `run` checks that first, which is what
keeps `answer_*_questions` from being handed the same sentence twice when it
ends, as it always does, by raising the next round.

**This narrows D44 rather than overturning it, and the difference matters.**
The wrong tool is still harmless: it refuses, it builds nothing, and D13's
review still stands between every value and the document. What changes is that
the sentence the tool itself nominates is carried through in the same turn
instead of costing the person one. Two tests stated the old rule as "nothing
moved" and now state what D44 actually protects — nothing was built — with the
September loop test keeping its whole subject: the SAME round must never be
raised again, and what is on screen after a misrouted reply is the NEXT one.

**A question with no context is placed by its section.** Four of the owner's
asks sit alone in a table cell whose column header the scanner does not reach,
so the round introduced them by the tag: *"<ask:75>: What should replace
<ask:75>?"*, twice over, and the app renders the angle brackets as a link so it
arrived as *"ask:75: What should replace ask:75?"*. The section is known —
"Pricing Details" — and is something a person can find in the document, so it
is used when the context is empty. **This is presentation only.** The scanner
still finds no label for those four, which remains the owner's call because it
changes `tags.py` and the proposal flow with it.

Mutation check: 5 mutants, 4 killed. The survivor makes `_a_fill_tool_acted`
answer "never", which the ASKING check in `_tool_the_turn_needs` also covers:
every tool that acts without asking leaves the fill built or reviewing, and
neither is asking. Belt and brace, like D47's pair.

### D50 · The other document's tools are a signpost, not a dead end *(owner, 2026-09-11)*

The owner's fourth contract, 13:45–13:52, with D49 live. They answered every
round, the questions read properly, the review came up with every value on it
— and they tapped **"Yes, these are all correct"** and were told:

> *It looks like there isn't a proposal draft currently open in this
> conversation, so I can't confirm values yet. What client name and programme
> should I create the proposal for?*

There was no proposal. There was an MOU, finished, one tap from being written.
The model had called `confirm_proposal_values`, and it had been doing that all
the way through: `confirm_proposal_values` at 13:51:00, again at 13:51:24,
`show_proposal_questions` at 13:52:02, `confirm_proposal_values` at 13:52:52.
**D49 rescued every one of those turns** — the log says *"Turn called no tool;
passing the reply to answer_mou_questions"* three times, which is how the fill
reached its review at all. The last one it could not rescue, because D48 scopes
the force to a fill that is ASKING and this one was at its review.

**Two things were wrong, and the first is the older.** `_fill_in_hand` — which
backs `answer_*`, `show_*` and `confirm_*` — said *"There is no proposal being
filled in this conversation. Ask me to create one"* without ever looking to see
whether the OTHER kind of document was open. `create_*` has named what is open
and which tool moves it on since A2; the three tools behind `_fill_in_hand`
never had that, so for three rounds the model was told to start a proposal for
a contract it was in the middle of filling.

**And the tap itself must survive the wrong tool.** At the review there is
nothing left to answer, so D48's force had nowhere to send it and the
conversation simply stopped. The approval a person actually gave now reaches
the document it was about.

**The match is exact, and that is the whole of the safety.** `confirm_*_values`
is the one tool that writes a client-facing file, so what carries an approval
is the review's own phrase — compared as a person reads it, case and stray
spaces folded, and nothing else. Anything else said at the review is asking for
a CHANGE, and a document written from that is one nobody approved. D48's rule
that a fill at its review is never forced stands for every sentence but this
one.

Mutation check: 5 mutants, 5 killed. The strictest of them is the last: making
`_said` compare letter for letter leaves a tap that arrived lower-cased doing
nothing, which is exactly where this found the owner.

### D51 · A suggestion the round replaced with today is accepted AS today, and a card opens the document it announces *(owner, 2026-09-11)*

The owner's fifth contract, 17:48–17:53, built cleanly. D50 is visible working
in their screenshot: *"Confirm proposal values — failed — There is no proposal
in this conversation, but there IS a MOU being filled in it… Call
confirm_mou_values instead"*, and immediately under it *"Confirm mou values —
Created: true"*. The model corrected itself inside the same turn.

They then reported three things. **Two of the three were one defect, and the
document was not at fault.**

**Checked against the built file, every figure they asked for is in it.** They
said *"Make it 5k instead of 4k"* and it reads `Rs. 5000/-`. They said
*"Instead of 3 lakhs make it 4 lakhs"* and it reads `Rs. 4,00,000/-`, with both
instalments moved to `Rs. 2,00,000/-` so the two still sum. They said *"Make it
2nd October 2026"* and it reads *Second Day of October, Two Thousand
Twenty-Six (02-10-2026)*. There is no `3,00,000` anywhere in that package, and
no *First Day of September*. **Those figures are in the CONTRACT THEY BUILT AT
04:33**, which is a different document, and they had opened it by mistake.

**Why they opened the wrong one.** The card that announces a built contract
carries an Open button, and it took them to the client's overview instead —
where two contracts sat one above the other with the same title, the same
status and no date between them. `AssistantFragment` chose the screen from a
list of id keys whose FIRST entry was `lead_id`, and `confirm_mou_values`
returns the contract's id and the client's together, so the client always won.
The list had not been revisited since before contracts existed. It now lives in
`AssistantEntities`, where a test can reach it, ordered most-specific-first,
and `MainActivity` knows what a `mou` is. The client screen's contract rows
carry their date.

**The one thing that WAS wrong in the document.** Its first line still read
*"modified: 1.9.2026"* — ten days stale, on the line a reader sees first. D48
put today at the front of the taps for a suggestion that has gone by and said
so on the line, and never changed what *"All the suggested values are fine"*
MEANS for that question, so the author's own date was still what got written.
They agreed to what the round showed them, and what it showed was today.

**Only the author's stale date is swapped, and only when it was ACCEPTED
rather than chosen.** A person who names the old date keeps it: a contract can
be dated the day it was agreed rather than the day it was typed, and naming a
date is choosing it. The whole-word search that tells those apart is now one
helper shared with D46's fence, which is the same question asked twice.

Mutation check: 4 mutants, 4 killed. Android 89 passed, from 82.
