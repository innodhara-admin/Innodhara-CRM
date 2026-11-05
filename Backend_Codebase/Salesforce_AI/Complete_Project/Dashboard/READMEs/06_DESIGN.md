# 06 · Design

**The specification for the Innodhara Setup Console.** Written 2026-08-13,
against the decisions in `05_DECISIONS.md`. Where this file and `00`–`04`
disagree, `05` and this file win.

> **Read `08_PROGRESS_AND_HANDOFF.md` first** for where the work actually stands.
> This file is what to build; `07_BUILD_PLAN.md` is the order to build it in.

Every number stated here was computed this session, not recalled. The command
that produced it is named where it matters.

---

## 1 · What this is

A web console that lets an operator take an organisation from nothing to
go-live: create the tenant, staff it, give everyone skills, build the catalogue,
set the governance rules and the behaviour dials, and then **verify** that the
result will actually work — without anyone running a Python seed script.

It replaces `scripts/seed_workflows.py` and
`scripts/reset_for_datacentre_demo.py` as the way setup data is created, with
one crucial difference: **it goes through the HTTP API** (D3), so it gets
validation, audit rows, versioning and encryption that the scripts bypass.

### 1.1 Non-goals, stated so their absence is deliberate

- **It is not a sales or delivery UI.** No leads, meetings, proposals,
  approvals or tasks. That is the Android app's job.
- **It does not create projects.** There is no `POST /projects`; a project is
  born only from a confirmed meeting. The reseed loop covers **the catalogue
  only** (D6), and the UI says so where it could otherwise be misread.
- **It is not a super-admin platform console.** It holds a `super_admin` session
  for exactly one call — `POST /orgs` — and nothing else.
- **It does not mirror the permission matrix.** It is an org_admin tool; where a
  role question arises it lets the server answer with a 403 rather than
  pre-judging. This is a deliberate refusal to create the third copy of `_MATRIX`
  that Q15 warns about.

---

## 2 · Stack

| Layer | Choice |
|---|---|
| Build | Vite + TypeScript |
| UI | React 19 |
| Routing | `react-router-dom` |
| Server state | `@tanstack/react-query` |
| Forms | `react-hook-form` + `zod` + `@hookform/resolvers` |
| CSV | `papaparse` |
| Styling | **CSS Modules + a design-token file. No component library, no CSS framework** |
| Tests | `vitest` |

Eight runtime dependencies, four dev — `vite`, `typescript`, `vitest`, and the
pinned `openapi-zod-client` generator of §3.1. Nothing else.

**Why no component library.** MUI, Ant or shadcn would each guarantee the
generic-admin-panel look the brief rules out, and would add far more surface
than a single-purpose console needs. The styling is small enough to own.

**Why React over Svelte or vanilla TS.** Svelte would be less code but has a
thinner form/validation ecosystem and is less likely to be familiar. Vanilla TS
has the fewest dependencies, but a 16-step dependency-ordered wizard plus
import-preview tables is a lot of stateful UI to hand-roll, and it degrades as
the surface grows.

**Why `zod`.** It is the pivot of §3 — the same schema validates an interactive
form, a CSV row, and generates the downloadable template. That is what stops
those three drifting apart.

---

## 3 · The generated / hand-written boundary

**This is the most important section in the document.** Get it wrong and the
console becomes a third hand-maintained mirror of backend validation — exactly
the defect Q15 records in `RoleGate.java`, which claims to be a 1:1 mirror of
`_MATRIX` and is one permission behind.

### 3.1 Generated from the backend

```
Dashboard/tools/dump_openapi.py       imports app.main, writes openapi.json
        │                              (lives under Dashboard/, touches nothing
        ▼                               in app/ or scripts/)
src/api/openapi.json                  generated, committed
        │  npm run gen:api  →  openapi-zod-client (version pinned)
        ▼
src/api/generated.ts                  Zod schemas + z.infer types, committed
```

Everything OpenAPI can express comes from here and is **never** hand-typed:
field names, types, optionality, `min_length` / `ge` / `le`, regex patterns,
enum members, response shapes.

The dumper imports the FastAPI app rather than fetching from a running server,
so generation works in CI and does not depend on a backend being up.

### 3.2 Drift is a build error

Three mechanisms, in increasing strength:

1. **`npm run gen:check`** regenerates to a temporary file and diffs against the
   committed one. Non-zero exit on any difference. Wired as a `prebuild` script,
   so **`npm run build` fails if the backend has moved and the client has not**.
2. **A Vitest descriptor-to-schema conformance test** asserts that every field
   named in a hand-written descriptor exists in the generated schema for that
   entity. A backend rename turns into a failing test, not a silently dead form
   field.
3. **A Vitest coverage test** asserts every descriptor module resolves to a
   generated schema, so a new entity cannot be half-wired.

> The word *registry* is deliberately not used for `src/descriptors/`. It
> described the earlier design in which the whole entity was hand-declared;
> keeping the name would imply a completeness this layer no longer has and
> should never regain.

### 3.3 Hand-written — only what OpenAPI cannot express

Under `src/descriptors/`, one module per entity. Each field may carry rules, and
**every rule declares who enforces it**:

| Enforcement | Meaning | Rendered as |
|---|---|---|
| `backend` | derived from the generated schema; the server enforces it too | plain caption |
| `ui-only` | **the server will accept anything**; this rule exists only here | caption with a distinct marker |

That distinction is the honest answer to Q6. The console validates client-side
only (`05_DECISIONS.md` Part 3), and it never lets the operator believe the
server is checking something it is not.

What is hand-written, and why OpenAPI cannot carry it:

| Hand-written | Why |
|---|---|
| CSV column order, example rows | not an API concept |
| The manual's verbatim quotes and "if you skip it" text | prose, not schema |
| Dependency ordering between the 16 items | derived from FKs and handler validation, not declared |
| `working_days`, `client_report_day` day labels | Pydantic says `list[str]` / `str` — **`ui-only`** |
| `nudge_gap_days`, `reply_nudge_after_days` key names | Pydantic says `dict` — **`ui-only`** |
| `payment_reminder_schedule` entry shape | Pydantic says `list[dict]` — **`ui-only`** |
| `timezone`, `currency` | unconstrained strings — **`ui-only`** |
| `PlaybookRequest.entries` item shape | `list[dict]`, no sub-model — **`ui-only`** |
| `ApprovalRuleRequest.condition` key vocabulary (13 observed keys) | free `dict` — **`ui-only`** |
| `default_quantity`'s tri-state meaning | OpenAPI can say `number \| null`; it cannot say that `null` means *"this org did not say how many"* rather than *"one of them"* |

> The `default_quantity` control is therefore a **checkbox plus a number**, never
> a number pre-filled with `1`. `admin.py` · `PricingItem` carries a ten-line
> comment explaining that flattening this tri-state was a real regression: a
> default of `1` written into every line made it impossible to distinguish a
> deliberate quantity of one from an unanswered question, and the value estimate
> treats those two cases differently.

### 3.4 The five consumers

```
descriptors/program.ts ──┬──▶ <EntityForm>          renders fields, validates
   + generated schema    ├──▶ import/validate.ts    validates every parsed row
                         ├──▶ <FormatPanel>         the in-app spec
                         ├──▶ import/template.ts    CSV header + example row
                         └──▶ checklist/status.ts   dependency ordering
```

Eleven modules: `staff`, `skills`, `programs`, `pricing`, `proposalTemplates`,
`messageTemplates`, `playbooks`, `approvalRules`, `demoTeams`, `vendors`,
`settings`.

---

## 4 · Application architecture

```
Dashboard/
  tools/dump_openapi.py
  src/
    api/        openapi.json · generated.ts · client.ts · endpoints.ts
    session/    store.ts · handoff.ts
    descriptors/  types.ts + 11 entity modules
    checklist/  items.ts · status.ts
    import/     parse.ts · validate.ts · template.ts · apply.ts
    ui/         tokens.css + primitives
    screens/    one per checklist item, plus import / go-live / reset / bundle
  dist/         built bundle, committed (D10)
```

Each unit answers the three questions cleanly: `descriptors` declares *what an
entity is*, `api` knows *how to talk to the server*, `checklist/status` is pure
functions from API reads to statuses, `import` is parse → validate → preview →
apply with no knowledge of any specific entity.

### 4.1 `api/client.ts`

- Base URL is **a field in the app**, defaulting to `http://127.0.0.1:8000`
  (`config.py`'s default). Nothing hard-codes `9010` — that is a demo-runbook
  override, not a default (Q19).
- Bearer token chosen per call from whichever session the route needs.
- Normalises the backend's `AppError` shape (`{"detail": ...}`) into a typed
  error so every screen renders the server's own refusal message verbatim —
  never a paraphrase.
- **Never auto-retries a write.** See below.

#### `Idempotency-Key` is not honoured by this backend — verified

An earlier draft of this section had the client mint an `Idempotency-Key` per
write intent, "matching what the Android client does". **That would have been
theatre.** Verified this session across all of `app/`:

- The **only** middleware registered is `CORSMiddleware` (`main.py`).
- **No route anywhere reads a header** — there is no `Header(...)` parameter and
  no `request.headers` access in the entire application.
- **No API route takes an idempotency argument** of any kind.
- `idempotency_records` has exactly **one** consumer: `jobs/mail_poller.py`,
  deduping *inbound IMAP* messages by `Message-ID`. It has nothing to do with
  HTTP requests.
- `outbound_messages.idempotency_key` is minted **server-side** — `uuid4().hex`
  in `communication_engine`, or a deterministic string such as
  `f"intro-{contact.id}-{channel}"` in `intro_service`. It is a service-layer
  function argument (`message_service.py` · `queue_message`), never a header.

So the server **drops the header entirely**. The Android
`IdempotencyInterceptor` has always been sending it into a void; this is
harmless there only because the values it protects are minted server-side anyway.

> `03_API_SURFACE.md` §6.3 says *"A dashboard must do the same for any write it
> retries."* **That advice is misleading and this console does not follow it.**
> Doing the same achieves nothing, and would leave the operator believing a retry
> is safe when it is not.

**The design consequence is real.** There is no server-side dedupe on any admin
write, so a retried `POST` genuinely does create a second program, vendor or
approval rule. Therefore:

- `client.ts` **never retries a write automatically.** A failed write surfaces
  the server's message and the operator decides.
- React Query is configured with `retry: 0` for all mutations. Reads may retry
  freely.
- The import applier is re-runnable only through the preview, which pre-reads
  existing rows and marks the collisions (§5.5).

### 4.2 `session/` — two sessions, one hand-off

Two tokens in **`sessionStorage`**, never `localStorage` — the `super_admin`
token especially, and neither should survive the tab.

A persistent session bar names which identity the current action runs as, because
the two are not interchangeable: `POST /orgs` needs `super_admin`, and every
`/admin/*` route **refuses** `super_admin` by design (`deps.py` ·
`get_org_context`). D1 closes that fence permanently.

#### The hand-off is a blocking gate, because it is unrecoverable

The `admin_temp_password` is returned **once** by `POST /orgs` and is stored
nowhere the console can read it back. Lose it and **the organisation is
unreachable**: there is no `PATCH /orgs/{id}`, no admin password-reset that does
not require an existing admin session, and `POST /admin/users/{id}/reset-password`
needs `manage_staff` — which only that lost account holds. The org can only be
deactivated by a `super_admin` and abandoned.

**So the temp password is never handed to a human.** The org-creation form
collects the intended admin password up front, and a single submit runs the whole
chain, with a blocking modal showing which step it is on:

1. `POST /orgs` as `super_admin` → `admin_temp_password`, held **in memory only**.
2. `POST /auth/login` as the new `org_admin` with that temp password.
3. `POST /auth/change-password` to the password collected on the form.
4. The modal releases and the checklist opens.

Step 3 is not optional, because **nothing in the backend enforces
`must_change_password`** — verified: the flag is set at `organisations.py` and
`admin.py`, returned by `auth.py`, and read by no dependency. If the console does
not enforce it, nothing does.

**On the happy path the operator never sees the temp password at all** — there is
no secret to copy, paste, lose or leave on a clipboard.

**On a failed step the modal reveals it, as a recovery key.** If step 2 or 3
fails after step 1 succeeded, the organisation exists and that temp password is
the only way to reach it. The modal switches to a recovery state showing the
password, the step that failed, and the two calls to complete by hand. Hiding it
there would convert a recoverable failure into a stranded organisation.

The modal has no dismiss control, no overlay click-out and no escape key in
either state.

---

## 5 · Screens

### 5.1 The checklist rail

Permanently visible, tiered exactly as the manual tiers it — Essential (7),
Strongly recommended (4), Optional (4), plus item 1 at platform level. Each row
carries its live status and, when incomplete, **the manual's own words for what
will break**. This rail is the product; there is no widget-grid home screen.

### 5.2 Status derivation

Pure functions over real API reads. No local "I did that" flags — a status the
console cannot verify is not shown as done.

| # | Item | Read | `●` when |
|---|---|---|---|
| 1 | Org + first admin | `GET /orgs`, `GET /auth/me` | an org is selected and its admin session is live |
| 2 | Staff + role | `GET /admin/users` | ≥1 active user besides the admin; `◐` if any lacks `department` |
| 3 | A skill on everyone | `GET /skills` | every active user holds ≥1 skill; `◐` if only some do |
| 4 | Programs | `GET /admin/programs` | ≥1 active program |
| 5 | Rate card | `GET /admin/programs/{id}/pricing` per program | every active program has a current pricing table |
| 6 | Proposal template | `GET .../proposal-templates` per program | every active program has a current template |
| 7 | Message templates | `GET /admin/message-templates` | all four `kind × channel` combinations have a current row; `◐` at 1–3 |
| 8 | Playbooks | **`GET /playbooks`** (change #3) | ≥1 current playbook per active program; `◐` if partial |
| 9 | Approval rules | `GET /approval-rules` | ≥1 rule; `◐` if no catch-all `{}` rule exists for an entity type in use |
| 10 | Behaviour dials | `GET /admin/settings` | any dial differs from its model default |
| 11 | Email sending | `GET /admin/settings` (change #2) | **compound — see below** |
| 12 | Retention | `GET /admin/settings` | always satisfied; the current windows are shown |
| 13 | Demo teams | `GET /admin/demo-teams` | ≥1 team (optional tier — `○` is fine) |
| 14 | Calendar | `GET /admin/settings` (change #2) | **compound** |
| 15 | Vendors | `GET /vendors` | ≥1 vendor (optional tier) |
| 16 | Inbound mail | — | **never. Permanently `—`** |

**Item 10 is honest about a limit.** The API cannot distinguish *"deliberately
left at the default"* from *"never looked at"*. Untouched settings therefore show
`◐` with the caption *"defaults apply — the API cannot tell whether you chose
them"*, not a green tick.

**Item 11 is the reason change #2 exists.** `email_integration_configured` is
`bool(smtp_username)` today, which is `true` the moment credentials are stored
regardless of `EMAIL_MODE`. Mail only leaves when **both** halves are set —
`email_service.py` returns a `dry_run:` file path unless `email_mode == "smtp"`
*and* credentials exist. So item 11 renders as one compound line:

> *credentials stored · sending is **OFF** on this server (`EMAIL_MODE=dry_run`)*

and is `◐`, never `●`. This is the failure the manual warns about twice — p.7
*"approved messages are written to a file and everyone believes they were sent"*
and p.16 *"Approved messages never arrive"*. The console must never reproduce it.

**Item 16 is permanently unavailable**, with the reason stated: inbound mail has
no column, no endpoint and no per-org storage — it is `INBOUND_EMAIL_MODE` plus
three env vars — and it is open finding **F35** with a standing instruction to
keep it off. The row shows the manual's fallback verbatim: *"Replies are captured
by hand with Log a reply, which works fully and takes seconds."*

### 5.3 Item screens

One per checklist item, rendering from its descriptor. Each carries the manual's
quote, the format panel, the create form, the current rows, and — where the
entity supports it — delete.

**Versioned families never edit in place.** Pricing tables, proposal templates,
message templates and playbooks all create a new row and flip `is_current`; a
proposal locks `pricing_table_id` + `pricing_version` and `template_id` +
`template_version`, which is what makes editing a rate card safe. So the button
says **"Publish new version"**, and the version history is shown, not hidden.

### 5.4 Where the console warns about the backend

Three places where the API's shape is a hazard and the UI has to say so:

- **Approval rules have no `PATCH`.** Editing is delete-then-create, which
  changes the row id and is **non-atomic** — a failure between the two calls
  leaves the org with *no* rule where it had one, silently changing who approves
  client-facing messages. The edit control states this and re-reads the rule list
  afterwards to confirm the replacement landed.
- **Programs, demo teams and vendors have no `PATCH`.** Editing is
  delete-and-recreate, and for demo teams the name is UNIQUE per org, so the
  delete must succeed before the recreate can.
- **`PATCH /admin/settings` cannot reset a field to null.** It applies with
  `exclude_none=True` over a blind `setattr` loop, so an omitted field is left
  unchanged and there is no way back to null. The settings form says so rather
  than offering a clear control that would silently do nothing.

### 5.5 Import

Ten entities importable as **CSV or JSON**; `settings` is JSON-only, since it is
one row rather than a list.

Flow: **choose entity → drop file → parse → validate every row → preview → apply.**

The preview is a table with one verdict per row, and it is the first defence
against a real limitation: **the backend has no bulk transaction.** Rows are
applied by sequential HTTP calls, and apply is gated on *zero* validation errors.

#### Partial imports are normal, and are designed for

Validation catches what it can see; it cannot see a server-side conflict, and
§4.1 rules out retrying a failed write. So some rows will fail at apply time, and
the design treats that as ordinary rather than exceptional:

- **Apply continues past a failure — it does not halt.** Halting on row 12 of 50
  leaves the operator with a half-applied file and no record of whether rows
  13–50 would have worked. Every row is attempted.
- **The result screen reports a per-row outcome**: applied, or the server's own
  refusal message verbatim.
- **Failed rows are emitted as a file in the input's own format** — CSV in, CSV
  out; JSON in, JSON out — with the original columns intact and an appended
  `_error` column carrying the server's message.
- **That file is directly re-importable.** The parser ignores any column whose
  name begins with `_`, so the operator fixes the rows in place and drops the
  same file back in. No editing of headers, no reformatting, no rebuilding the
  file by hand from a list of errors.

The loop is therefore: import → fix the failures → re-import the failures file →
repeat until it comes back empty. Covered by the Vitest import tests (§10).

**Re-import behaviour differs per entity, and the preview states which applies:**

| Entity | Re-importing the same file |
|---|---|
| skills | **upserts** — level overwritten, `{"updated": true}` |
| staff | fails on duplicate email (globally unique) |
| programs | fails on duplicate `code` (unique per org, upper-cased on write) |
| pricing / proposal templates / message templates / playbooks | **creates a new version** and supersedes the current one — the preview says so explicitly, because a careless re-import silently inflates version numbers |
| approval rules | creates duplicate rows; nothing dedupes. The preview warns |
| demo teams | fails on duplicate name (unique per org) |
| vendors | creates duplicates silently — no uniqueness of any kind. The preview warns |

**CSV has a trap and the console steers around it.** Template bodies (`body_md`,
message `body`) contain newlines, which survive CSV only under correct quoting.
The format panel recommends JSON for those entities and the CSV template carries
a pre-quoted example so the shape is obvious.

### 5.6 Go-live check

The manual's own p.7 acceptance test, made computable — and the single screen
that justifies the console existing rather than a pile of forms:

1. **Skill coverage.** Every `required_skill` across all current playbooks
   (readable now, via change #3), diffed against every skill held by an active
   user (one `GET /skills` with no `user_id` returns the whole org). **The
   unmatched list is finding F25, caught at authoring time instead of at demo
   time** — a task needing a skill nobody holds routes to the phase lead flagged
   *"no skill match"*.
2. **Program completeness.** Each active program × {current pricing, current
   proposal template, playbook per phase}.
3. **Message template completeness.** All four `kind × channel` combinations.
4. **Approval rule ordering.** For each `entity_type` in use, the rules in `rank`
   order with the first match highlighted, plus a flag when no catch-all `{}`
   rule exists. Rank ordering decides which rule fires, and a never-matching
   high-rank rule quietly hands approval to the catch-all.
5. **Delivery honesty.** The compound email and calendar statuses from §5.2.
6. **Domain check.** Every staff email against `org.email_domain` — which also
   catches the `@`-prefix trap recorded as finding F34, where a stored
   `"@domain"` built `"@@domain"` and made adding staff impossible.

### 5.7 Reset

Two steps. The dry run returns exact per-table counts under three headings, and
the apply requires the organisation's own name typed back.

The screen states plainly, per D6:

> Resetting removes transactional data and, if you choose, the catalogue.
> **Projects, plans, tasks and the twelve engine-only tables come back only by
> running the product** — recording a meeting and confirming its review. This
> console cannot restore them.

The three flags are presented as three independent choices with their row counts,
not one button, since they are used in different combinations: a rehearsal reset
clears transactional data only; a full reseed clears all three and re-imports the
bundle.

Two operational notes on the same screen:

- The **job queue and scheduler keep running**. Wiping `jobs` mid-flight is a
  live-system hazard; idle the backend before applying, or expect a few rows to
  reappear.
- **Staff accounts are never removed**, whichever flags are set — including the
  account performing the reset (§7.3).

### 5.8 The reseed bundle — and what it deliberately excludes

Export to a single JSON file; reset; re-import. **The bundle and the reset flags
are designed as one mechanism**: everything the bundle carries, the reset can
clear, and nothing else. Without that pairing the loop does not round-trip — a
re-import collides exactly as §5.5 documents, with staff failing on duplicate
email and approval rules silently duplicating.

**The bundle carries nine of the ten importable entity types:**

| In the bundle | Cleared by |
|---|---|
| programs, pricing, proposal templates, message templates, playbooks, demo teams, vendors | `wipe_catalogue` |
| **skills, approval rules** | **`wipe_org_config`** |

**Staff is the one exclusion, and it is not an oversight.** `users` can never be
wiped, because **you cannot delete the account you are authenticated as** — the
reset runs under an `org_admin` session and destroying that row would end the
session mid-operation and strand the organisation exactly as §4.2 describes. So
staff survives every reset, needs no restoring, and is therefore not in the
bundle. The export screen states this at the point of export, not in a footnote:

> Staff accounts are not exported. They are never removed by a reset — the
> account you are signed in as is one of them — so there is nothing to restore.

**Skills round-trip on `user_id`**, which stays valid precisely because `users`
survives. That makes the bundle **same-organisation only**: it is a reseed loop,
not a cloning tool. Importing a bundle into a different organisation would carry
user ids that do not resolve there, and the console refuses it by comparing the
`org_id` stamped in the bundle against the active session.

The screen carries the same D6 sentence as §5.7: projects and the twelve
engine-only tables come back only by running the product.

---

## 6 · The honesty model

Four statuses, never three:

| | Meaning |
|---|---|
| `●` | satisfied, derived from a real API read |
| `◐` | partial — some of it is done, or **the API cannot confirm the rest** |
| `○` | not started |
| `—` | **cannot be satisfied here**, with the reason |

The rule behind them: **the console never shows a status it cannot verify.** Item
11 is compound because verifying it needs two facts; item 10 is `◐` at defaults
because the API cannot report intent; item 16 is `—` because no HTTP client can
satisfy it. Each of those is a place where the obvious green tick would be a lie.

---

## 7 · Backend changes

Eight, all additive. **The list is closed** (`05_DECISIONS.md` Part 3).

### 7.1 The four small ones

1. **Five staff fields** — `department`, `designation`, `whatsapp_number`,
   `max_open_tasks`, `working_days` onto `CreateUserRequest`,
   `UpdateUserRequest` and `UserResponse` (`admin.py`). Columns already exist;
   no migration. `department` is validated against `Department`
   (`sales` | `operations` | `accounts`) — note `accounts` is a department but
   not a role.
2. **Delivery mode read-only + honest booleans** — `_settings_response`
   (`admin.py`) gains `email_mode`, `whatsapp_mode`, `calendar_mode`,
   `inbound_email_mode` read from `config`, and each `*_configured` boolean
   becomes credentials **AND** mode. Nothing is moved into `org_settings` (D5).
3. **`GET /playbooks`** (`ops.py`) — optional `program_id` and `phase` filters,
   `current_only` defaulting true. Closes a go-live prerequisite that has a write
   path and no read path.
4. **`GET /admin/users/{user_id}`** + widened `UserResponse` (`admin.py`) —
   including `require_action_item_review`, which `UpdateUserRequest` can already
   set but no response returns.

Plus **#7**, `contact_name` / `phone` / `email` onto `list_vendors` (`ops.py`).

**Change #8 — the mount — must tolerate a missing bundle.** It points out of
`app/` by relative path (§8.1), so a backend deployed or checked out without
`Dashboard/` would hit a `StaticFiles` directory error **at import time and fail
to start**. That would let a missing console take down the API, which is
unacceptable for a component the API does not depend on.

So the mount is conditional: check the directory exists, mount if it does, and
otherwise log a warning naming the expected path and continue. The API starts
either way. A pytest asserts the app imports cleanly with the directory absent.

### 7.2 Change #6 — eight guarded DELETEs

Every one calls `audit_service.record` (D13). The existing
`delete_approval_rule` writes no audit row; that is **not** inherited.

| Route | Module | Refused when |
|---|---|---|
| `DELETE /skills` — natural key `user_id` + `skill` | `ops.py` | an open or in-progress `action_item` requires that skill and no other active user holds it |
| `DELETE /admin/programs/{id}` | `admin.py` | any `projects.program_id` or `proposals.program_id` references it |
| `DELETE /admin/programs/{id}/pricing/{version}` | `admin.py` | any `proposals.pricing_table_id` references that row |
| `DELETE /admin/programs/{id}/proposal-templates/{tid}` | `admin.py` | any `proposals.template_id` references it |
| `DELETE /admin/message-templates/{id}` | `admin.py` | never — nothing references it |
| `DELETE /playbooks/{id}` | `ops.py` | never — nothing references it |
| `DELETE /admin/demo-teams/{id}` | `admin.py` | any `demos.team_id` references it. Member rows are removed **in the handler** — there are no `ondelete=` rules anywhere in the schema |
| `DELETE /vendors/{id}` | `ops.py` | any `action_items.external_wait["vendor_id"]` names it — scanned over rows with non-null `external_wait`, since this is a JSON blob no FK can reach |

**The skill delete takes the natural key, not an id**, because `GET /skills`
does not return the row `id` — verified by reading `ops.py` · `list_skills`.
That also makes it symmetric with `POST /skills`, which upserts on the same pair.

**Deleting a current version promotes the highest remaining version back to
`is_current`.** That gives the un-supersede path the API has never had, as a
consequence of the delete rather than a separate endpoint.

The two unguarded deletes are deliberate. Nothing references a message template
or a playbook, so removal cannot orphan anything — but removing the only
`intro`/`email` template breaks business-card intro drafting, so the checklist
turns amber immediately. **The checklist is the guard there, not a 409.**

### 7.3 Change #5 — `POST /admin/reset`

`require_permission("manage_settings")` — org_admin only (D8).

```
POST /api/v1/admin/reset
{
  "dry_run": true,
  "wipe_transactional": true,     # WIPE     — 42 tables
  "wipe_catalogue": false,        # REPLACE  —  7 tables
  "wipe_org_config": false,       # CONFIG   —  2 tables
  "confirm_org_name": "…"         # required when dry_run is false
}
→ { "org": {...}, "counts": {table: n}, "total": n, "applied": bool }
```

#### The taxonomy is four buckets, not three

The script's three lists cannot express this endpoint, for two reasons found
during review:

- **`audit_log` was in WIPE, which contradicts D13.** Requiring every
  destructive route to write an audit row while the reset destroys the audit log
  is incoherent. **It moves to KEEP.** The reset's own audit row therefore
  survives the reset — and the "write the audit row *after* the deletes" caveat
  the earlier draft carried disappears with it.
- **`user_skills` and `approval_rules` were in KEEP, which broke the reseed
  loop.** The bundle exports them, so the reset must be able to clear them, or
  re-import collides (§5.8). They move to a new **CONFIG** bucket that only
  `wipe_org_config` reaches.

| Bucket | n | Tables | Cleared by |
|---|---|---|---|
| **KEEP** | 4 | `organisations`, `org_settings`, `users`, `audit_log` | **nothing, ever** |
| **CONFIG** | 2 | `user_skills`, `approval_rules` | `wipe_org_config` |
| **REPLACE** | 7 | the catalogue | `wipe_catalogue` |
| **WIPE** | 42 | transactional | `wipe_transactional` |

**Verified against `Base.metadata` this session: 4 + 2 + 7 + 42 = 55, a perfect
partition — nothing missing, nothing extra, nothing in two buckets — and every
table carries an `org_id`.**

> **Arithmetic note.** The review said the partition test "still passes at
> 6 + 7 + 42". That is correct for the `audit_log` move considered alone, with
> `user_skills` and `approval_rules` still inside a KEEP of 6. Composing it with
> the CONFIG split gives **4 + 2 + 7 + 42**. Four buckets are used because a
> bucket named KEEP whose contents can be wiped is a lie of the kind §6 exists to
> prevent. Same 55 either way.

**`users` stays in KEEP unconditionally**, and no flag can reach it: the reset
runs under an `org_admin` session, and deleting that row would end the session
mid-operation and strand the organisation (§4.2). This is why the bundle
excludes staff.

#### It is org-scoped, and the script it replaces is not

Every table in every bucket carries an `org_id`, so every delete carries
`WHERE org_id = :org`. Two of the wipeable tables have a **nullable** `org_id` —
`jobs` and `llm_usage` — so that predicate correctly leaves platform-level rows
(`org_id IS NULL`) alone. (`audit_log`, the third nullable one, is now in KEEP
and is not deleted at all.)

`reset_for_datacentre_demo.py` deletes globally with `PRAGMA foreign_keys=OFF`,
which is safe only because the demo database holds one tenant. **An endpoint must
not inherit that.** Deletion order follows the WIPE list, which is already
child-before-parent, then REPLACE, which places `programs` after its children,
then CONFIG.

`audit_service.record` writes `admin.org_reset` with the per-table counts and the
flags used. Ordering no longer matters now that `audit_log` is in KEEP, but the
record is written last so the counts it carries are the counts actually applied.

---

## 8 · What this does to the docs guard

`check_docs_in_sync.py` counts `APIRoute` instances on `app.routes` and asserts
the README's stated counts and its §7.1 breakdown. Adding routes **will fail the
guard** until the docs are resynced. A `StaticFiles` mount is not an `APIRoute`,
so change #8 has no effect — verified by reading the guard.

Eleven new routes: `GET /playbooks`, `GET /admin/users/{id}`,
`POST /admin/reset`, and eight DELETEs.

| Figure | Now | After |
|---|---|---|
| Total routes (incl. 2 health) | 140 | **151** |
| Under `/api/v1` | 138 | **149** |
| Uncalled by the Android app | 59 | **70** |
| §7.1 · Organisation administration (`admin.py`) | 18 | **25** |
| §7.1 · Operations and money (`ops.py`) | 16 | **20** |

The other five §7.1 rows are unchanged: Everything else 13, Platform/Super Admin
4, Incidents 3, Approval rules 3, Device push 2. Both columns sum correctly —
59 and 70.

The build plan therefore ends with: update `BACKEND_README.md`'s counts and
§7.1 rows, then run `check_docs_in_sync.py`, `tests/test_genericity.py` and
`scripts/check_hardcoded_strings.py`. **"The guards are green" is the completion
claim — not "the docs are updated."**

### 8.1 The genericity guards cannot see `dist/` — and that is an invariant

Review raised the concern that the two genericity guards would scan the committed
bundle and fail on the manual's verbatim quotes and the product name. **Checked:
they cannot reach it.**

- `check_hardcoded_strings.py` scans `(app_dir / "java").rglob("*.java")` —
  **Android Java sources only.**
- `tests/test_genericity.py` scans `APP = <repo>/app` `.rglob("*.py")` —
  **Python under `app/` only.**

Neither has a path that reaches `Dashboard/dist/`, so **no exclusion is needed
and none should be added** — an exclusion for a path a guard never visits is dead
configuration that reads as protection.

**What is real is the invariant behind the concern.** The bundle must stay at
`Dashboard/dist/`, **outside `app/`**. Serving it from somewhere like
`app/static/` would put it inside `test_genericity.py`'s scan root, and the
manual quotes would start tripping a guard that is right to flag them in engine
code. Change #8 is a `StaticFiles` mount pointing *out* of `app/` for this
reason, and that is a constraint on the mount, not a preference.

The same invariant is why no dashboard Python lands under `app/`: the OpenAPI
dumper lives at `Dashboard/tools/dump_openapi.py` (§3.1).

---

## 9 · Visual design

**Commissioning document, not admin panel.**

- **Layout.** A fixed left rail that *is* the checklist, permanently visible;
  content pane to the right. No top nav, no widget grid, no home screen.
- **Tiers** are labelled groups separated by a rule line, not cards.
- **Type.** A serif for headings and for the manual's quoted text, which appears
  verbatim throughout — the product's own voice is the strongest asset here and
  it is what stops the page looking like a bootstrapped admin. A grotesque for
  UI. A mono for codes, keys, paths and JSON.
- **Colour.** Near-monochrome paper/ink with a single accent. Status is carried
  by weight and marker glyph, and **only `◐` and `—` take colour**, because those
  are the two that need to be looked at. Light and dark, both from tokens.
- **Forms** are single column, label left, control right, with the constraint
  beneath in small mono — cited by **file and symbol**, never line number
  (`admin.py · CreateUserRequest`). Line numbers are wrong within a week.
  `ui-only` rules carry their distinct marker here (§3.3).
- **Motion.** None beyond 120 ms state transitions.
- **Naming.** "Innodhara · Setup Console" (D15), from a single token.

---

## 10 · Testing

**Pytest — required, and the priority.** The eight delete guards and the reset
endpoint are the highest-risk code in this project: they are the only things here
that destroy data. Written in the existing suite's style, under `tests/`.

Per delete: the happy path, the refusal path with its reason, the audit row, and
— for versioned families — that deleting the current version promotes the
predecessor back to `is_current`.

For reset: dry-run counts match reality; **KEEP survives every combination of
flags**, `users` and `audit_log` included; each of the three flags clears its own
bucket and only its own; the org-name confirmation is enforced; **another
organisation's rows are untouched**, including the `org_id IS NULL` platform rows
in `jobs` and `llm_usage`; and the audit row is written with the counts applied.

Plus **D14's partition test**: every table in `Base.metadata` appears in exactly
one of KEEP / CONFIG / REPLACE / WIPE. It has a green baseline — verified this
session, **4 + 2 + 7 + 42 = 55** with no gaps, extras or overlaps — so a table
added later fails it rather than silently surviving a wipe.

One more, cheap and worth having: a test asserting **no route reads an
`Idempotency-Key` header**, so if that ever changes, §4.1's no-retry rule gets
revisited deliberately rather than staying wrong.

**Vitest** — descriptor-to-schema conformance (§3.2) and the import validator:
CSV quoting with embedded newlines, the `default_quantity` tri-state surviving a
round trip, per-row verdicts, and the re-import behaviours in §5.5.

Plus the partial-import loop, which is the piece most likely to be got subtly
wrong: apply continues past a failure rather than halting; the failures file
carries the original columns plus `_error`; **it round-trips** — parsing the
emitted file yields exactly the failed rows, `_error` ignored; and CSV in gives
CSV out, JSON in gives JSON out.

No E2E and no component tests.

---

## 11 · READMEs strategy

`00`–`04` freeze as the exploration record. Five files are added:

| File | Purpose |
|---|---|
| `05_DECISIONS.md` | Every decision, dated, with the reasoning. The closed backend-change list |
| `06_DESIGN.md` | This spec — what to build |
| `07_BUILD_PLAN.md` | The order to build it in, checkboxed, with the test strategy |
| **`08_PROGRESS_AND_HANDOFF.md`** | **The entry point.** Current state, what is done, what is next, how to run it, what is known-broken |
| `09_BACKEND_CHANGES.md` | One row per backend change: status, files touched, tests written, guard re-run yes/no. The audit trail for each unfreeze of a normally-frozen backend |

Two rules, so a future session lands correctly:

1. **Every file's header points at `08`.** It is read first, always.
2. **A status table is the authority**, not prose — the same convention
   `FINDINGS.md` already uses. If `08`'s table and a paragraph disagree, the
   table wins.

---

## 12 · Known limits of this design

Stated so they are choices, not surprises.

- **Client-side validation only.** The seven unvalidated dials and the two free
  JSON blobs are checked here and nowhere else; another client can still write
  nonsense. Marked `ui-only` everywhere it applies.
- **No bulk transaction.** Import applies row by row over HTTP. The preview gate
  makes a partial apply unlikely, not impossible.
- **No write is safe to retry.** The backend reads no `Idempotency-Key` header
  and has no dedupe on admin writes (§4.1, verified). A retried `POST` creates a
  duplicate, so the console never retries a write automatically and a failed
  write is always the operator's decision.
- **A crash mid-hand-off still strands the organisation.** §4.2 removes the human
  from the chain entirely — the temp password is held in memory, never shown on
  the happy path, and revealed only as a recovery key when a step fails. That
  closes every window a person could lose the secret through. It does not close
  the last one: **if the tab or the process dies between `POST /orgs` returning
  and the password change succeeding, that organisation has no reachable
  administrator.** There is no `PATCH /orgs/{id}`, and the only password-reset
  route needs the very session that was never established. A `super_admin` can
  deactivate the org; nobody can recover it.
- **The reseed bundle is same-organisation only.** Skills round-trip on
  `user_id`, which resolves only in the org that issued them; the console
  refuses a bundle whose `org_id` does not match the session. Cloning one org's
  setup into another is not supported.
- **Staff cannot be reset.** `users` is in KEEP under every flag combination,
  because the reset runs under an org_admin session (§7.3). A wrong staff list
  is corrected by deactivating accounts, not by resetting.
- **Checklist item 16 can never be satisfied**, by this console or any HTTP
  client.
- **Branding is write-once.** `logo_url` and `brand_colors` are set at org
  creation and there is no `PATCH /orgs/{id}`. The form says so at the field.
- **Approval-rule edits stay non-atomic**, because Part F #6 is deferred.
- **The dashboard cannot upload a calendar credentials file** — it can only
  record a server-side path that must already exist, and unlike email and
  WhatsApp that value is stored unencrypted.
