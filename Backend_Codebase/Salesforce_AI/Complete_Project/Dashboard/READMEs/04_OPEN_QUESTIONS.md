# 04 · Open Questions

> **ANSWERED — read `08_PROGRESS_AND_HANDOFF.md` first.**
> This document says below that none of its questions is resolved. That was
> true when it was written. **All nineteen are now answered in
> `05_DECISIONS.md`** — Q1–Q4, Q9 and Q13 in Part 1, Q5 by D2, Q18 by D15, and
> the rest in Part 4. It is kept unedited as the record of what was unknown,
> and it remains the only place **Part F** is defined (§Part F), which `05`
> Part 3 relies on.

Every ambiguity hit during this exploration, and everything in the backend core logic
that I believe must change before a dashboard can do its job.

**None of these is resolved here.** Each states the question, the evidence behind it, and
what turns on the answer. Where options exist they are listed as options, not as a
recommendation.

**Legend**
🚧 **BLOCKING** — work cannot start on the affected area until this is answered.
⚙️ **SHAPES THE BUILD** — work can start, but the answer changes the design.
🔍 **NEEDS A DECISION** — a smaller call, but a real one.
🔐 **SECURITY** — needs a decision from whoever owns risk, not just the builder.

---

# Part A · Scope and premise

## Q1 🚧 What is the Dashboard, exactly — and who signs into it?

**The ambiguity.** Nothing in the repository defines it. `Complete_Project/Dashboard/`
was empty before this document set. The brief's wording — *"the complete ordered list of
prerequisites … that the dashboard must be able to satisfy"* and *"endpoints relevant to
creating, reading, and deleting this data"* — points at a **setup/administration
console**, and these four documents are written against that premise. But it is an
inference, and three quite different products fit the same sentence:

- **(a)** A web admin console replacing the Android app's "Admin" placeholder tab, run by
  an `org_admin` for one organisation.
- **(b)** A platform console for the `super_admin` — onboarding organisations, the job
  the `platform` Android flavour was reserved for and never built.
- **(c)** A seeding/demo tool that stands up a whole realistic organisation at once —
  the job `scripts/seed_workflows.py` and `scripts/reset_for_datacentre_demo.py` do today.

**Why the answer changes everything.** These are not shades of the same thing:

| | (a) org console | (b) platform console | (c) seeding tool |
|---|---|---|---|
| Signs in as | `org_admin` | `super_admin` | both, or neither |
| Can call `POST /orgs`? | ❌ | ✅ | ✅ |
| Can call `/admin/*`? | ✅ | ❌ **refused by design** | needs a second session |
| Needs the missing DELETEs? | some | few | **all of them** |
| Needs to create projects? | no | no | **yes — and it can't** (Q13) |

**The hard constraint underneath.** `get_org_context` **explicitly rejects
`super_admin`** (`app/api/deps.py:53-57`), with the message *"This endpoint is
organisation-scoped; the Super Admin has no access to organisation data."* And
`POST /orgs` requires `get_super_admin` (`organisations.py:62`).

> **No single account can complete the go-live checklist.** Step 1 needs `super_admin`;
> steps 2–16 refuse `super_admin`. A dashboard spanning both must hold **two sessions**
> and hand off between them — including transporting the `admin_temp_password` returned
> once by `POST /orgs` (`organisations.py:119`) into a first login as that new admin.

**What is needed:** which of (a)/(b)/(c), or which combination; and if it spans the
boundary, whether the two-session hand-off is acceptable or whether the backend's
super-admin fence should change (which would contradict a stated product principle —
see Q14).

## Q2 🚧 `users.department` is a stated prerequisite with no write path. Which way is wrong?

**The ambiguity.** The product manual, p.6, lists under **Essential**:

> *"**Set each person's department too — it decides who receives their escalations.**"*

There is **no API that can set it.** Verified by grep across `app/` and `scripts/`: the
only writers of `User.department` are `scripts/seed_workflows.py:233` and
`scripts/dryrun_part2.py:421` — both direct database writes. `CreateUserRequest`
(`admin.py:31-35`) and `UpdateUserRequest` (`admin.py:38-43`) have no such field. The
column is live and consumed — `GET /auth/me` returns it (`auth.py:133`) and the Android
`MeResponse` carries it.

The same is true of four more columns the assignment and reminder engines read:
`designation`, `whatsapp_number`, `max_open_tasks`, `working_days`.

**Which of these is the defect?**
1. The manual over-promises, and department is genuinely a seed-script-only concern; or
2. The API is incomplete and `CreateUserRequest`/`UpdateUserRequest` should carry these
   fields; or
3. Staff configuration was always meant to be done by script, and the dashboard should
   write to the database directly (see Q9).

**What turns on it.** Under (2) this is a small, safe backend change — five optional
fields on two existing Pydantic models plus the assignment loop, no schema migration,
since the columns already exist. Under (1) or (3) the dashboard needs a non-HTTP write
path, which changes its architecture completely.

**Also unresolved regardless:** there is no `GET /admin/users/{id}`, and
`GET /admin/users` returns **6 of 21 columns** (`UserResponse`, `admin.py:46-52`). Even
if writes are added, **a staff-detail screen cannot be rendered from this API.**

## Q3 🚧 Email, WhatsApp, calendar and inbound are env-only. How does a dashboard own them?

**The ambiguity.** Four operational switches are **process-wide environment variables**,
not per-organisation columns:

| Setting | Env var | Default | `config.py` |
|---|---|---|---|
| `EMAIL_MODE` | `dry_run` \| `smtp` | `dry_run` | `:87` |
| `WHATSAPP_MODE` | `dry_run` \| `cloud_api` | `dry_run` | `:95` |
| `CALENDAR_MODE` | `off` \| `google` | `off` | `:102` |
| `INBOUND_EMAIL_MODE` | `off` \| `imap` | `off` | `:67` |

**Both halves are required.** Verified at `app/services/email_service.py:147`:

```python
if settings.email_mode != "smtp" or creds is None:
    ...  # returns f"dry_run:{rel}" — writes the RFC-822 message to a file
```

**This is the most dangerous gap found**, because the API actively reports success.
`GET /admin/settings` returns `email_integration_configured` as `bool(smtp_username)`
(`admin.py:677-679`) — which is `true` the moment credentials are stored, **regardless of
`EMAIL_MODE`**. A dashboard showing a green tick against checklist item 11 would be
reproducing exactly the failure the manual warns about on p.7:

> *"otherwise approved messages are written to a file and **everyone believes they were
> sent**."*

and again on p.16: *"Approved messages never arrive → Sending is not switched on."*

**Options, none chosen:**
- **(a)** Move the mode into `org_settings` as a per-org column — the largest change, and
  the only one that makes the setting genuinely multi-tenant.
- **(b)** Leave the env as the master switch but **expose it read-only** through
  `GET /admin/settings` so the dashboard can display *"credentials stored, but sending is
  OFF on this server"*. Small change; fixes the lie without moving the control.
- **(c)** Change `email_integration_configured` to `AND` the env mode — cheapest, but
  then the dashboard cannot distinguish "no credentials" from "server is in dry-run".
- **(d)** Accept it, and have the dashboard state plainly that it cannot verify delivery.

**Related, and separate:** `INBOUND_EMAIL_MODE` has **no per-org storage at all** — no
column, no endpoint. See Q11.

---

# Part B · The deletion question

## Q4 🚧 The brief asks for deletion. The product's stated principle is that nothing is destroyed. Which wins?

**The direct conflict.** The brief asks for *"endpoints relevant to creating, reading,
and **deleting** this data"*. The product's fifth founding idea (manual p.3) is:

> *"**Nothing is destroyed.** Plans supersede, they do not overwrite. Tasks move to done,
> cancelled or superseded. Proposals accumulate revisions. Every state change writes a
> history row. You can always reconstruct what was true on any past day."*

The codebase enforces this consistently: **the entire 140-route API has three DELETE
endpoints** (`assistant.py:114`, `projects.py:302`, `ops.py:605`), and one of those three
is a soft delete. Verified against the full route inventory.

**Nothing in this list can be deleted through the API today:** user skills, programs,
pricing tables, proposal templates, message templates, playbooks, demo teams, demo team
members, vendors, leads, contacts, projects, meetings, proposals, integration
credentials. Users and organisations can only be **deactivated**.

**The tension is real, not semantic.** Concrete cases found this session:

- A **wrong skill actively mis-routes work** and can never be withdrawn — only its level
  changed (`ops.py:641-659`). The manual calls skills the highest-value setup item.
- A **mistyped program is permanent**. `code` is UNIQUE per org (`program.py:22`), so it
  cannot be replaced under the same code, and its `description` — *"what the AI reads
  when it decides which of your offerings a conversation was about"* — keeps being read.
- A **demo team's composition is fixed at creation**, and the UNIQUE name means it cannot
  be re-created correctly.

**Options, none chosen:**
- **(a)** Deletion is only ever for *setup* data an org got wrong before going live, and
  transactional data stays immutable. Needs a crisp line between the two — the
  `KEEP`/`REPLACE`/`WIPE` taxonomy in `reset_for_datacentre_demo.py:38-59` is one that
  already exists and sums to exactly 55 tables.
- **(b)** Deactivation everywhere instead of deletion — needs `is_active` columns added
  to `user_skills`, `programs`, `demo_teams`, `vendors` (a real migration, and there is
  no Alembic — Q17).
- **(c)** True deletes, restricted to rows with no dependants — needs the orphan analysis
  in Q5 first.
- **(d)** A "reset organisation" bulk operation only, mirroring the existing script,
  rather than per-row deletes.

**This is the single question that most changes the shape of the work.**

## Q5 🚧 If deletion is in scope, what are the cascade semantics? Nothing in the schema answers this.

Three properties of the schema make deletion genuinely dangerous, all established in
`01_DATA_MODEL.md` §8–§9:

1. **Only 27 of 55 tables declare a foreign key other than `org_id`** (computed from
   `Base.metadata` this session). `action_items.project_id`, `deliverables.project_id`,
   `invoices.project_id`, `incidents.project_id`, `payments.invoice_id` and
   `projects.parent_project_id` are **all soft `String(32)` references**.
2. **No `ondelete=` cascade rule exists anywhere in the schema.**
3. **Foreign-key enforcement is off by default on SQLite.** `app/database.py:43-51` sets
   only `journal_mode=WAL` and `busy_timeout`.

So the database will neither prevent an orphaning delete nor clean up after one.

**Unanswered, per entity:**

- Delete a **program** that has pricing tables, proposal templates, playbooks and
  **proposals that locked its versions** (`proposals.template_id`,
  `proposals.pricing_table_id`)? A sent proposal that can no longer resolve its own
  pricing table breaks the version-locking guarantee that is the point of the design.
- Delete a **user** who is `leads.owner_id`, `action_items.assignee_id`,
  `projects.sales_owner_id`, a `project_member`, a `demo_team.lead_user_id`, and the
  `requested_from_user_id` on live approvals?
- Delete a **vendor** referenced from `action_items.external_wait["vendor_id"]` — a
  **JSON blob**, unreachable by any FK and invisible to any dependency check?
- Delete a **lead** with meetings, transcripts, consent records, proposals, threads and
  projects beneath it — the DPDP question, given `POST /privacy/erase-contact` already
  exists for contacts (`misc.py:220`) but has no lead-level equivalent?

**Also unanswered:** does deletion need to be audited? `audit_service.record` is called
throughout `admin.py` but **not** by `delete_approval_rule` (`ops.py:605-622`) — the one
hard delete that exists writes no audit row.

---

# Part C · Validation and correctness

## Q6 ⚙️ Six settings and three JSON blobs have no validation. Should the dashboard become the validator?

**The ambiguity.** A dashboard is the first place these could be validated — but doing so
means the *rules* live in the UI, where the engines cannot see them.

**Unvalidated `org_settings` dials** (`SettingsRequest`, `admin.py:591-618`), applied by a
blind `setattr` loop (`admin.py:706-707`):

| Field | Accepts | Must actually be |
|---|---|---|
| `working_days` | any `list[str]` | day labels the engines compare against (`"Mon".."Sun"`) |
| `client_report_day` | any string | a weekday name (default `"Friday"`) |
| `nudge_gap_days` | any dict | `{"level1","level2","level3"}` |
| `reply_nudge_after_days` | any dict | `{"nudge1","nudge2","call_task"}` |
| `payment_reminder_schedule` | any `list[dict]` | `[{"offset","tone"\|"action","cc"?}]` |
| `timezone` / `currency` | any string | a real tz / ISO currency |

**Unvalidated JSON bodies:**

- `PlaybookRequest.entries: list[dict]` (`ops.py:436`) — nothing checks the keys
  (`title`, `required_skill`, `offset_days`, `priority`, `visible_to_client`), the
  `phase` vocabulary, or **that `required_skill` matches a skill anybody holds**. That
  last one is the exact condition the manual describes as the most common setup failure
  and that finding F25 records.
- `ApprovalRuleRequest.condition` / `joint_condition` (`ops.py:555`, `:561`) — free dicts.
  The 13 condition keys in use appear **only** in the seeded rule set
  (`seed_workflows.py:121-160`) and in model comments. **A typo produces a rule that
  silently never matches** — and since `rank` ordering decides which rule fires, a
  never-matching high-rank rule quietly hands approval to the catch-all.

**The question:** should the dashboard (i) validate client-side only, (ii) also propose
backend Pydantic sub-models so every client benefits, or (iii) neither — treat these as
expert fields? Related: should there be a **`GET` endpoint publishing the valid
vocabularies** (condition keys, playbook entry keys, phases, skills in use) so a UI need
not hard-code them and drift?

## Q7 ⚙️ Several setup entities can be created but never edited. Is delete-then-create acceptable?

Entities with **create but no update**: programs, approval rules, demo teams, vendors,
demo team members.

The sharpest case is **approval rules**, which have `POST` and `DELETE` but no `PATCH`.
A dashboard "edit rule" must therefore be delete-then-create, which:
- changes the row id (breaking anything referencing it);
- is **non-atomic** — a failure between the two calls leaves the org with **no** rule
  where it had one, **silently changing who approves what** until someone notices.

For **demo teams** it is worse: no update, no delete, and `name` is UNIQUE per org
(`demo.py:18`), so a mistake cannot even be corrected by re-creating under the same name.

**The question:** add `PATCH` routes (small, additive), have the dashboard do
delete-then-create and accept the race, or treat these as immutable by design?

## Q8 🔐 Five "admin" GETs are readable by every org member. Intended?

These use bare `Depends(get_org_context)` with **no permission string**, so any
authenticated org member — including a `sales_agent` — can read them:

| Route | Line | Exposes |
|---|---|---|
| `GET /admin/programs` | `admin.py:221` | every offering |
| `GET /admin/programs/{id}/pricing` | `admin.py:306` | **the full rate card, every version, all `unit_price` values** |
| `GET /admin/programs/{id}/proposal-templates` | `admin.py:391` | full `body_md` of every version |
| `GET /admin/message-templates` | `admin.py:477` | every template body |
| `GET /admin/demo-teams` | `admin.py:555` | team composition |

Their POST counterparts are correctly restricted (`manage_programs`, `edit_pricing`,
`manage_templates`, `manage_teams`).

Plausibly deliberate — a salesperson needs to see prices to sell. But it is
**inconsistent with `GET /admin/settings`**, which does require `manage_settings`, and it
means **superseded pricing history is org-wide readable**. A dashboard rendering these
screens must know whether to gate them itself.

Two adjacent cases, same question: `POST /vendors` and `GET /vendors` are open to **any
org member** (`ops.py:261`, `:272`), and `POST /skills` uses a **hard-coded role tuple**
rather than a permission constant (`ops.py:639`).

---

# Part D · Architecture

## Q9 ⚙️ Should the dashboard use the HTTP API, or write to the database like the seed scripts?

**The ambiguity.** Both working seeders bypass the API entirely.
`scripts/seed_workflows.py` uses the SQLAlchemy models directly;
`scripts/reset_for_datacentre_demo.py` uses raw `sqlite3` with `PRAGMA foreign_keys=OFF`
(`:120`). Direct writes are how every prerequisite gets satisfied today — and it is the
**only** way to set `department` (Q2) or delete anything (Q4).

**But direct writes bypass four things the API provides:**
1. **Audit rows** — `audit_service.record` is called throughout `admin.py`.
2. **Validation** — e.g. the `@domain` email rule (`admin.py:84-87`), the `ORG_ROLES`
   check, the demo-team user-existence check (`admin.py:522-534`).
3. **Versioning** — the `is_current` flip logic lives in the route handlers, not the
   models. A direct insert into `pricing_tables` leaves **two** rows with
   `is_current=True`, and nothing detects it.
4. **Encryption** — `encrypt_secret` is called in the route, not the model. A direct
   write of `smtp_app_password_enc` would store plaintext.

**The question:** is the dashboard a proper API client (and therefore blocked on the gaps
in Q2, Q4, Q6, Q7), or an in-process tool with database access (and therefore responsible
for reproducing all four behaviours above)? A hybrid — API where routes exist, direct
writes for the gaps — is possible but would apply **two different validation and audit
regimes to the same setup session**.

## Q10 🔐 `POST /api/v1/webhooks/whatsapp` is unauthenticated and crosses tenants.

**Read in full and verified** (`messages.py:184-217`). The handler declares **no auth
dependency**. Its lookup at `:197-203`:

```python
select(OutboundMessage).where(
    OutboundMessage.provider_message_id == provider_id
)   # <- no org_id filter
```

…then mutates `message.status` and writes a `message_delivery_log` row. Its GET sibling
(`:172-181`) at least checks `hub.verify_token`; **the POST checks nothing at all** —
neither a signature, nor the verify token, nor a shared secret.

So any unauthenticated caller who can guess or observe a `provider_message_id` can mark
messages `delivered` or `failed` **in any organisation**. Malformed payloads are
deliberately swallowed (`:216-217`, *"acknowledge anyway per Meta guidance"*).

Mitigating context: `WHATSAPP_MODE` defaults to `dry_run`, so `provider_message_id` is
likely null in practice today. **That is a reason it has not bitten, not a reason it is
safe.**

**Not a dashboard bug** — but a dashboard that surfaces delivery state is surfacing data
any anonymous caller can currently alter. Flagged for whoever owns risk.

## Q11 🔍 `INBOUND_EMAIL_MODE` is finding F35 and is deliberately off. Is it in scope at all?

Checklist item 16 ("Suppliers of inbound mail", manual p.7) has **no column, no endpoint
and no per-org storage** — it is purely `INBOUND_EMAIL_MODE` + `IMAP_HOST` +
`IMAP_PORT` + `INBOUND_POLL_SECONDS` (`config.py:65-70`).

It is also an **open finding (F35)** and the standing instruction is to keep it off. The
demo runbook says so in bold: *"⛔ Never set `INBOUND_EMAIL_MODE` (F35)"*
(`DEMO_WALKTHROUGH.md`, part 0.2).

**The question:** does the dashboard (i) omit it, (ii) show it as a
permanently-unavailable checklist row with the reason, or (iii) is resolving F35 a
prerequisite for the dashboard at all? The manual is explicit that the manual fallback
(*"Log a reply"*) *"works fully and takes seconds"*, so omission may be entirely fine.

## Q12 🔍 `user_skills.skill` is free-form text. Should the dashboard impose a vocabulary?

`skill` is `String(100)` with **no controlled vocabulary** (`user.py:68`), matched by
string equality against `action_items.required_skill` (`action_item.py:54`).

The consequence is unforgiving in both directions: `"scheduling"` and `"Scheduling"` are
different skills, and a playbook requiring a skill nobody holds routes the task to the
phase lead flagged *"no skill match"* — the manual's most-common-omission case and
finding F25.

The two working datasets use **entirely disjoint vocabularies**: `seed_workflows.py:50-70`
has `field_sales`, `curriculum_design`, `android`, `robotics`, `teaching`…;
`reset_for_datacentre_demo.py:17-20` has `logistics_coordination`, `quality_assurance`,
`training_delivery`, `client_relationship`, `general`. The manual (p.6) names exactly one
canonical value: *"the neutral skill **`general`**"*.

**The question:** free text with autocomplete from existing rows; a per-org managed skill
list (a new table, and a migration); or a fixed taxonomy? Note the genericity guards
(`tests/test_genericity.py`, `scripts/check_hardcoded_strings.py`) would likely **reject a
hard-coded taxonomy** in code — so a fixed list may not even be permissible.

## Q13 ⚙️ Projects cannot be created over HTTP. How does the dashboard seed a realistic org?

**There is no `POST /api/v1/projects`.** Verified twice — absent from the 140-route
inventory, and by grepping `Project(` across `app/`, which yields exactly two
construction sites:

- `app/engines/planner_engine.py:1658` — born from a confirmed meeting
- `app/api/projects.py:613` — `POST /projects/{id}/children` (branch projects only)

This is coherent with the product's first principle, but it means **the only way to bring
a project into being is to record or type a meeting and confirm its review.**

Twelve more tables are engine-only writes (`03_API_SURFACE.md` §4.2): `action_plans`,
`assignments`, `approvals`, `progress_events`, `ai_decisions`, `reminders`, `conflicts`,
`client_commitments`, `digests`, `playbook_suggestions`, `threads`, `inbound_messages`.

**The question, only if the dashboard needs demo/sample data (Q1 option c):** drive the
real flow (`POST /meetings/notes` → `POST /meetings/{id}/review/confirm`, which costs LLM
calls and is non-deterministic), write directly to the database (Q9), or **not seed
transactional data at all** and restrict the dashboard to the catalogue?

## Q14 🔍 Is the super-admin fence negotiable?

`get_org_context` rejects `super_admin` outright (`deps.py:53-57`), and the manual states
it as a product guarantee (p.4): the platform operator *"is blocked from reading any
client's sales data — **by the server, not by a screen**."*

If Q1 lands on a dashboard that spans org creation *and* org configuration, either the
two-session hand-off is accepted, or this fence is opened. **Opening it would contradict
a documented product principle** and is not a decision for the builder.

A narrower variant, which may not breach the principle at all: should `super_admin` be
allowed to reach **configuration** routes (`/admin/programs`, `/admin/settings`) while
still being barred from **sales data** (leads, meetings, proposals)? The current gate does
not distinguish them — it is one dependency covering both.

---

# Part E · Client-side and operational

## Q15 🔍 The Android RoleGate is one permission behind. Does the dashboard inherit the same mirror problem?

**Verified myself** by extracting the permission strings from
`app/src/main/java/com/yuvipep/app/core/auth/RoleGate.java`: it maps **19** permissions;
the backend `_MATRIX` has **20** (`permissions.py:12-57`). **`confirm_assignments` is
absent**, and the file's own comment claims to be a *"1:1 mirror"*.

The live consequence: the Home screen renders the assignment-batch card with no role
check, so a `sales_agent` can open the batch, tap Confirm, and receive the server's 403.
`GET /assignments/proposed` is open to any org member (`workflow.py:553`) while
`POST /assignments/confirm-batch` requires `confirm_assignments` (`workflow.py:592`) —
the mismatch that makes the card reachable.

**The question for the dashboard:** hard-code a third copy of the permission matrix and
accept the same drift, or should the backend **publish the matrix** (e.g.
`GET /api/v1/permissions`, or an array on `/auth/me`) so clients stop mirroring it?
The latter is a small additive backend change that would fix the Android gap too.

Two related client-side notes, both verified: **only 8 of the 19** RoleGate permissions
are ever consulted by any screen, and three screens bypass `has()` to hard-code role
equality instead (`ApprovalsInboxFragment:123`, `ProjectDetailFragment:295-296`,
`TaskDetailFragment:302-304`).

## Q16 🔍 Push cannot reach a phone. Does the dashboard need to know?

**Verified myself.** The backend half is complete — `push_service.py` implements FCM
HTTP v1, `device_tokens` stores registrations, `POST /devices` accepts them
(`misc.py:74`). The Android app has **no Firebase dependency**: grepping `app/build.gradle`
and all of `app/src/main` for `firebase` returns only three *comments* deferring it to
"Phase 8" (`AndroidManifest.xml:7`, `NotificationPollWorker.java:34`,
`YuviPepApp.java:31`). `POST /devices` is never called, so `device_tokens` is always empty.

Delivery today is polling: 60 s in the foreground, 15 min via `WorkManager`. With the app
swiped away, **the fastest anyone learns about an approval is ~15 minutes.**

**The question:** if the dashboard surfaces "who has been notified", it will be reporting
in-app rows that may not have reached anybody. Should it show delivery honestly, and is
closing the FCM gap in scope?

## Q17 ⚙️ There is no Alembic. How does a dashboard-driven schema change ship?

`init_db()` runs hand-written "light migrations" then `Base.metadata.create_all`
(`app/database.py:102-113`). The docstring says *"Alembic can replace this later."* The
existing migrations are four idempotent `ALTER`/`UPDATE` statements
(`database.py:62-99`).

`create_all` **creates missing tables but never alters existing ones** — so any new column
this project needs (an `is_active` on `user_skills` for Q4 option (b), a per-org
`email_mode` for Q3 option (a), a skills-vocabulary table for Q12) requires either
another hand-written migration or adopting Alembic.

**The question:** if the answers to Q2/Q3/Q4/Q12 require schema changes, does Alembic get
adopted first? That is a larger piece of work than the dashboard itself.

## Q18 🔍 The product has two names. Which does the dashboard wear?

Client-facing material says **"Innodhara: Automating Sales Process"**
(`Innodhara_Product_Manual.pdf` p.1). The code says **YuviPep** — `app_name` is
`"YuviPep AI Sales Platform"` (`config.py:23`), the Android package is `com.yuvipep.app`,
and `GET /` returns the YuviPep name. The internal docs are all `YuviPep_*`.

Cosmetic, but it is a user-visible string on a login screen and needs an answer before
the first screen is drawn. Note the org's `logo_url` and `brand_colors` are **write-once**
at org creation (Q1/§2.1 of `03_API_SURFACE.md`) — there is no `PATCH /orgs/{id}` — so
branding decisions are hard to reverse.

## Q19 🔍 Operational facts that were true for the demo, not in general

Recorded because they are easy to inherit as assumptions and are all **environment
overrides, not defaults**:

- **Port.** `config.py:26` defaults to **8000**. The demo runbook uses `PORT=9010` with
  `adb reverse tcp:8000 tcp:9010`. Anything hard-coding 9010 is encoding a demo artefact.
- **Base URL.** The Android APK ships `DEFAULT_BASE_URL` =
  `https://surfing-singles-wax-pads.trycloudflare.com` (`app/build.gradle:42-43`) — a
  **Cloudflare quick tunnel**, which the surrounding comment admits rotates on every
  `cloudflared` restart. **It is certainly dead now.** A fresh install talks to nothing
  until someone pastes a new URL into the `server:` chip. Should the dashboard host a
  stable endpoint, or publish the current one?
- **Database state.** The live database was reset on 2026-08-06 for the demo. Per the
  reset script, it keeps the org, logins, `user_skills` and `approval_rules`, and holds a
  **datacentre** catalogue — not the school catalogue the older docs describe.
- **Test coverage.** The Android project declares JUnit, MockWebServer and Espresso but
  `app/src/test/` and `app/src/androidTest/` contain **zero files** (verified by
  `find … | wc -l` → 0). The backend has 218 pytest tests. Is the dashboard expected to
  carry tests?

---

# Part F · Backend core logic I believe must change

Stated as beliefs with the evidence behind them, **not as decisions**. Ordered by how
hard they block a dashboard.

| # | Change | Why I believe it is necessary | Size | Ties to |
|---|---|---|---|---|
| 1 | Add `department`, `designation`, `whatsapp_number`, `max_open_tasks`, `working_days` to `CreateUserRequest` / `UpdateUserRequest` / `UserResponse` | A **stated Essential prerequisite** is otherwise unreachable over HTTP. Columns already exist — **no migration** | Small, additive | Q2 |
| 2 | Make the delivery mode visible to clients — either per-org, or read-only on `GET /admin/settings`; and stop `email_integration_configured` reporting `true` while `EMAIL_MODE=dry_run` | The API currently **reports success for a setup step that will silently fail**. This is the manual's own named failure mode, and no client can detect it | Small (b/c) or large (a) | Q3 |
| 3 | Add `GET /playbooks` | A go-live prerequisite with a **write path and no read path**. A dashboard can only blindly overwrite task waves | Trivial | §2.5 |
| 4 | Add `GET /admin/users/{user_id}`, and widen `UserResponse` beyond 6 of 21 columns | No staff-detail screen is buildable from the current API | Small | Q2 |
| 5 | Decide and implement a removal story for setup data — deletes, `is_active` flags, or an explicit "no removal" policy | 11 setup entity types have **no removal of any kind**; a wrong skill or a mistyped program is permanent | **Depends entirely on Q4** | Q4, Q5 |
| 6 | Add `PATCH /approval-rules/{id}` (and probably programs, demo teams, vendors) | Edit-as-delete-then-create is **non-atomic on the rules that decide who approves client-facing messages** | Small, additive | Q7 |
| 7 | Authenticate `POST /webhooks/whatsapp` and scope its query by `org_id` | Unauthenticated **cross-tenant** write. Currently masked by `WHATSAPP_MODE=dry_run` | Small | Q10 |
| 8 | Publish the permission matrix (`GET /api/v1/permissions`, or on `/auth/me`) | Every client re-implements it and **the one that exists is already a permission behind**. Would fix the Android gap in the same change | Small | Q15 |
| 9 | Replace `PlaybookRequest.entries: list[dict]` and `ApprovalRuleRequest.condition: dict` with Pydantic sub-models | A typo yields a rule that **silently never matches** or a task wave requiring a skill nobody holds — F25's exact failure | Medium; **may break existing callers** | Q6 |
| 10 | Validate `working_days`, `client_report_day`, `nudge_gap_days`, `reply_nudge_after_days`, `payment_reminder_schedule`, `timezone`, `currency` | `PATCH /admin/settings`'s blind `setattr` stores nonsense silently | Small | Q6 |
| 11 | Make `POST /skills` verify `user_id` belongs to the caller's org, and move its hard-coded role tuple into `_MATRIX` | Currently creates orphan rows and bypasses the central permission model | Trivial | §2.3 |
| 12 | Reconcile the five ungated admin GETs, `POST /vendors`, and the 16 ungated `/projects` routes | Either they are intended and should say so, or they are gaps. Right now the intent is unreadable | Small, but **needs a policy decision first** | Q8 |

**Two things I explicitly do not believe should change**, recorded so they are not
"fixed" by accident:

- **Version-and-supersede for pricing tables and templates.** It is what makes
  `proposals`' locked `template_version`/`pricing_version` meaningful. A dashboard "edit
  price" button must create a new version, never update a row.
- **Projects being engine-created only.** It is the product's first principle expressed
  in code. If the dashboard needs sample projects, that is an argument for a seeding
  path — not for a `POST /projects`.

---

# Summary — what blocks what

| Question | Blocks |
|---|---|
| **Q1** — what the dashboard is, and whose session it holds | **Everything.** Nothing else can be sized until this is answered |
| **Q4** — deletion vs "nothing is destroyed" | The whole delete surface, and change #5 |
| **Q2** — `department` has no write path | Any staff-management screen |
| **Q3** — the environment wall | Checklist items 11 and 16; honest status reporting anywhere |
| **Q9** — API client or direct DB writes | The dashboard's entire architecture |
| Q5, Q13, Q17 | Fall out of Q4, Q1 and Q2 respectively |
| Q6, Q7, Q8, Q12, Q15 | Shape individual screens; none blocks starting |
| Q10, Q11, Q16, Q18, Q19 | Should be answered, but block nothing |

**Five questions — Q1, Q2, Q3, Q4, Q9 — should be answered before any code is written.**
The rest can be resolved as the affected screens are built.
