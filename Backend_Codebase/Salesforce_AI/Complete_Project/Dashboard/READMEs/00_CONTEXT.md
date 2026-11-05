# 00 · Context

> **SUPERSEDED IN PLACES — read `08_PROGRESS_AND_HANDOFF.md` first.**
> This is the frozen exploration record, written before Phase 1, and it is
> deliberately not rewritten. **Its route and DELETE counts are stale:** it says
> 140 routes and "only 3 DELETE endpoints exist in the entire API"; there are
> now **151** and **11**, and the *nothing is destroyed* principle it cites was
> deliberately amended by D2/D7. `08` §0.1 lists every stale figure.

> **Status of this document set.** Exploration only — no application code was written.
> Everything below was read from source. Where a number is stated it was *computed*,
> not recalled; the command that produced it is named. Anything not read from source
> is marked **INFERRED** and must be confirmed before it is relied on.

---

## 1. What this system is

A **multi-tenant, AI-driven sales-and-delivery automation backend** with an Android
client. The product name in client-facing material is **"Innodhara: Automating Sales
Process"**; the codebase, database and internal docs still use the older name
**YuviPep** (`app/config.py:23` — `app_name: str = "YuviPep AI Sales Platform"`).
They are the same product. The Android package is `com.yuvipep.app`.

The one-sentence version, from the product manual (`Innodhara_Product_Manual.pdf` p.1):

> A field representative records a conversation. From that alone the system builds
> the project, the dated plan, the staffed tasks and every message that goes back to
> the client — and stops at every point where judgement is required, to hand the
> decision to a named person.

### 1.1 The five ideas the product rests on

From `Innodhara_Product_Manual.pdf` p.3, each verified against code:

| # | Idea | Where it is enforced in code |
|---|---|---|
| 1 | The client is the relationship; the project is the work | `leads` ↔ `projects`, `app/models/lead.py:14`, `app/models/project.py:19` |
| 2 | Every project has one living plan, and it is versioned | `action_plans` with `version` + `changes_from_previous`, `app/models/project.py:92-118`; unique index on `(project_id, version)` at `:101` |
| 3 | The AI proposes, a person decides | `approvals` / `approval_rules`, `app/models/comms.py:79-144`; `OutboundMessage.status` defaults to `pending_approval`, `app/models/messaging.py:29-31` |
| 4 | Work is matched to people by recorded skill | `user_skills` ↔ `action_items.required_skill`, `app/models/user.py:54-69`, `app/models/action_item.py:54` |
| 5 | Nothing is destroyed | Statuses `superseded` / `cancelled` (`app/core/constants.py:77-84`); `lead_state_history`; `proposal_revisions`; only **3 DELETE endpoints exist in the entire API** (see `03_API_SURFACE.md` §5) |

### 1.2 Domain-neutrality

The manual (p.2) states the product is domain-neutral — "nothing in the engines, the
prompts or the database assumes an industry". This is an enforced claim, not a
marketing one: two guards exist and are run before any prompt/engine/screen change.

- `tests/test_genericity.py` — AST-parses every prompt
- `scripts/check_hardcoded_strings.py` — covers Java strings that Android Lint's
  XML-only `HardcodedText` check cannot see

Residue of the original school-sales domain survives in **identifier names only**, and
`app/database.py:62-99` carries live migrations that renamed the worst of them
(`role_at_school` → `role_at_client`, `school_intelligence` → `client_intelligence`,
lead state `school_execution_in_progress` → `client_execution_in_progress`).

---

## 2. The backend

**Location:** `C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project` (this repo).

| Property | Value | Source |
|---|---|---|
| Framework | FastAPI, async SQLAlchemy 2.0 (`Mapped[...]` / `mapped_column`) | `app/main.py:12`, `app/models/base.py:13` |
| API prefix | `/api/v1` | `app/main.py:168` |
| Default port | **8000** | `app/config.py:26` (`PORT=9010` in the demo runbook is an env override, not the default) |
| Database | SQLite by default, `sqlite+aiosqlite:///./data/salesplatform.db`; PostgreSQL supported via `DATABASE_URL` | `app/config.py:35`, `app/database.py:28-51` |
| Migrations | **No Alembic.** `init_db()` runs hand-written "light migrations" then `Base.metadata.create_all` | `app/database.py:102-113` |
| Primary keys | `uuid4().hex` — 32-char strings, not integers, not UUID columns | `app/models/base.py:16-25` |
| Timestamps | Naïve UTC (`datetime.now(timezone.utc).replace(tzinfo=None)`) | `app/models/base.py:20-21` |
| Tenancy | `org_id` stamped on every business row via `OrgScopedMixin`, plus optional PostgreSQL RLS | `app/models/base.py:35-40`, `scripts/postgres_rls.sql` |

### 2.1 Measured size

Computed this session, not recalled. `python scripts/check_docs_in_sync.py` reports and
I independently reproduced every figure:

```
55 tables · 755 columns · 140 routes · 20 permissions · 41 event types · 7 plan ops
```

- **55 tables / 755 columns** — reproduced by iterating `Base.metadata.sorted_tables`.
- **140 routes** — 138 decorators in `app/api/*.py` + 2 health routes in `app/main.py:187,197`.
  Reproduced with an independent regex pass over the decorators.
- **20 permissions** — counted from `_MATRIX`, `app/core/permissions.py:12-57`.
- **41 event types** — counted from `EventType`, `app/core/constants.py:332-375`.

The guard passes: *"OK - the three documents agree with the code"*.

### 2.2 Layering

```
app/api/        15 route modules            ← HTTP, Pydantic bodies, RBAC
app/engines/    14 engines                  ← business rules (planner, assignment,
                                              approval, communication, sync, resource,
                                              document, knowledge, inbound, nlu, …)
app/services/   18 services                 ← I/O adapters (email, calendar, storage,
                                              push, documents, notifications, …)
app/ai/         orchestrator + 7 agents     ← LLM layer (conversation, proposal, email,
                                              followup, query, scheduling, resolvers)
app/models/     21 modules → 55 tables
app/jobs/       queue, scheduler, pipelines, sender, mail_poller
```

**Critical for the dashboard:** the API layer is *not* a CRUD skin over the models.
Several tables are written **only** by engines and have no HTTP creation route at all —
most importantly `projects` (see `03_API_SURFACE.md` §4.1).

### 2.3 The six roles

`app/core/constants.py:5-11`, and the navigation each gets per the manual p.4:

| Role | Constant | Android bottom bar (manual p.4) |
|---|---|---|
| Sales agent | `sales_agent` | Home · Leads · Jarvis · Tasks · **Inbox** |
| Sales lead | `sales_lead` | Home · Pipeline · Jarvis · Approvals · Team |
| Operations agent | `operations_agent` | Home · Tasks · Jarvis · Projects · More |
| Operations lead | `operations_lead` | Home · Delivery · Jarvis · Incidents · Team |
| Organisation admin | `org_admin` | Home · Approvals · Jarvis · Admin · Insights |
| Platform operator | `super_admin` | Separate console |

`super_admin` is **deliberately barred from all organisation data** — not by a screen but
by `get_org_context`, which raises `PermissionDeniedError` for that role before any
handler runs (`app/api/deps.py:53-57`).

---

## 3. The Android client

**Location:** `C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI`.

| Property | Value | Source |
|---|---|---|
| Package | `com.yuvipep.app` | `app/build.gradle:18` |
| Version | `0.7.4-round7fixes` | `app/build.gradle:26` |
| minSdk / targetSdk | 26 / 35 | `app/build.gradle:19-20` |
| Language / pattern | Java, MVVM, Hilt DI, Retrofit, Room | `BACKEND_README.md:670` |
| Flavours | `org` and `platform` (dimension `audience`); platform build carries `applicationIdSuffix ".platform"` and is an honest placeholder | `app/build.gradle:47,56-57` |
| Source files | 171 `.java` under `app/src/main` | counted this session |

### 3.1 How backend and Android relate

The app is the **only client today**. The relationship is a plain REST contract over
`/api/v1` with a bearer JWT, plus five behaviours the backend *depends on the app to
provide*.

**Contract size — verified independently this session** by parsing
`app/src/main/java/com/yuvipep/app/core/net/ApiService.java`:

- **82 Retrofit methods** declared
- **81 distinct (verb, path) pairs** — the one duplicate is `GET api/v1/projects`,
  declared twice with different query signatures
- Every one resolves to a route the backend actually serves (`BACKEND_README.md:671-673`,
  machine-checked by `scripts/check_docs_in_sync.py`)

So the app calls **81 of the backend's 140 routes; 59 are unused by it.** The 59 split,
generated from code rather than counted by hand (`BACKEND_README.md:677-690`, and the
guard re-derives the same breakdown every run):

| Area | Unused routes | Why |
|---|---|---|
| Organisation administration (`api/admin.py`) | 18 | Configured server-side or by seed script; the in-app Admin tab is a placeholder |
| Operations and money (`api/ops.py`) | 16 | Backend-complete; the Delivery tab is a placeholder |
| Everything else | 13 | incl. `POST /proposals`, `POST /action-items`, both webhooks, `GET /` + `/health` |
| Platform / Super Admin (`api/organisations.py`) | 4 | The `platform` flavour is unimplemented |
| Incidents (`api/workflow.py`) | 3 | Incidents tab is a placeholder |
| Approval rules (`api/ops.py`) | 3 | Rules are data, edited server-side |
| Device push registration (`api/misc.py`) | 2 | A real gap — see §3.2 |

> **This is the single most important fact for the dashboard project.** The 34 routes in
> `admin.py` + `ops.py` that no client calls are almost exactly the go-live checklist
> surface. The backend for setup already exists and is simply unexposed to any UI.

### 3.2 Two places where app and backend genuinely diverge

Both verified by me directly, not taken on trust:

1. **Push notifications cannot reach a phone.** The backend half is complete —
   `push_service.py` implements FCM HTTP v1, `device_tokens` stores registrations,
   `POST /devices` accepts them (`app/api/misc.py:74`). The **app has no Firebase
   dependency at all**: grepping `app/build.gradle` and all of `app/src/main` for
   `firebase` returns only three *comments* saying FCM arrives "in Phase 8"
   (`AndroidManifest.xml:7`, `NotificationPollWorker.java:34`, `YuviPepApp.java:31`).
   No token is ever registered. Delivery today is polling only — a 60 s foreground
   poller and a 15 min `WorkManager` job raising *local* notifications.

2. **The client's permission mirror is one entry behind.** `RoleGate.java` describes
   itself as a 1:1 mirror of `app/core/permissions.py`. I extracted its permission
   strings: it maps **19 of the backend's 20**. **`confirm_assignments` is missing.**
   The Home screen therefore offers the assignment-batch card with no role check, and a
   non-lead receives the server's 403. The server is the enforcer, so this is cosmetic —
   but the file's own comment claims a parity it does not have.

### 3.3 What the app contributes to the contract

Behaviour the backend relies on (`BACKEND_README.md:739-751`): consent captured
*before* upload; idempotency keys minted at intent time so an offline-queued approval
and its replay share one key; an offline write queue replaying `{method, path, body}`
in order; a stable assistant `session_id` across process death; cache-first approvals
in Room.

**A dashboard is a second client and inherits none of this for free.** Any write path
it duplicates must mint its own idempotency keys and respect the same ordering.

---

## 4. What Workflow2 describes

**Location:** `Complete_Project/Workflow_simulation/Workflow2/`.

It is **not a test suite and not a specification.** It is a *staged live demo* — a
scripted, click-by-click walkthrough the owner performs on a real phone against a live
backend, to show a manager the whole product in about 75 minutes.

### 4.1 Contents

| File | What it is |
|---|---|
| `DEMO_WALKTHROUGH.md` | 37 KB, 13 parts (0–12), every screen touched at least once, plus a coverage checklist and a troubleshooting section |
| `meeting1.py` / `.wav` | ~10.7 MB Windows-TTS recording of a first client meeting |
| `meeting2.py` / `.wav` | ~10.5 MB — the *merge* test: the plan must update, not be rewritten |
| `meeting3.py` / `.wav` | ~8.9 MB — the *it-goes-wrong* meeting |
| `_speak.py` | The TTS driver that renders the scripts to WAV |

### 4.2 The scenario

**Client:** Meridian Data Centres. **Work:** commissioning 2 halls → 3 halls.
Deliberately *not* the school-training domain the codebase grew up in — the demo is
itself a genericity proof.

The three recordings are a designed progression:

- **Meeting 1** establishes the engagement: programme *DC Commissioning & Handover*,
  2 halls / 120 racks, start 1 September, three named client people with distinct
  influence levels (decision maker, day-to-day contact, security/access), and promises
  in both directions.
- **Meeting 2**, three weeks on, **changes** it: racks 120 → 160, start 1 Sep → 15 Sep,
  the booked demo moves 9 Sep → 18 Sep, one item dropped, operator certification added,
  and a **new decision maker** (Group CTO) appears. The assertion is that the plan gains
  a **new version held behind an approval** while the old one stays active, and that
  every meeting-1 task survives with its status.
- **Meeting 3** introduces failure, and asserts that *five machines fire from one
  recording* (conflict, incident, re-plan, branch, escalation).

### 4.3 What it tells the dashboard project

Three things, and they matter:

1. **`scripts/reset_for_datacentre_demo.py` is the closest existing thing to a
   "dashboard".** It is a 321-line script that does by direct `sqlite3` writes what a
   setup UI would do over HTTP. Its own taxonomy is the cleanest statement of what
   setup data *is* (verified by me — the three lists sum to exactly 55, matching the
   table count):
   - `KEEP` (5): `organisations`, `org_settings`, `users`, `user_skills`, `approval_rules`
   - `REPLACE` (7): `pricing_tables`, `proposal_templates`, `message_templates`,
     `playbooks`, `programs`, `demo_teams`, `vendors`
   - `WIPE` (43): every transactional table
2. **Setup is currently done by script, not by UI** — and the script bypasses the API
   entirely, so it also bypasses validation, audit rows and versioning. See
   `04_OPEN_QUESTIONS.md` Q9.
3. **Skills are treated as immovable.** The reset script's header says the team's skills
   are "deliberately left untouched, per instruction", and the datacentre tasks were
   *rewritten around the skills the team already held* rather than the skills being
   changed — because "a task needing a skill nobody holds routes unassigned, which is
   finding F25 and a bad demo." There is no API to delete a skill (`03_API_SURFACE.md`
   §5), which may be why.

---

## 5. Supporting documents read

| Document | What it is | Authority |
|---|---|---|
| `Innodhara_Product_Manual.pdf` | 16 pp, client-facing. Part 3 (pp. 6-7) is the **go-live checklist** — the direct input to `02_SEEDING_PREREQUISITES.md` | Product behaviour as shipped |
| `YuviPep_Data_Model.docx` / `.md` | Table-by-table reference, §1-§8, one section per table | Machine-checked against code by `check_docs_in_sync.py` |
| `BACKEND_README.md` / `.pdf` | 16 sections, 60 KB. §6 API surface, §7 mobile divergences, §12 domain model | Machine-checked; §7.1's breakdown is generated from code |
| `YuviPep_30_Workflows.docx` | The 30 numbered workflows | Machine-checked for the 30 headings and 7 plan ops |
| `FINDINGS.md` | 394 KB, findings F1–F63 | The status table is the authority |

All three machine-checked documents currently agree with the code.

---

## 6. Working premise for the dashboard — needs confirmation

Nothing in the repository defines what "the Dashboard" is. `Complete_Project/Dashboard/`
was empty but for this new `READMEs/` directory.

**The premise these documents are written against**, inferred from the brief's own
wording — *"the complete ordered list of prerequisites … that the dashboard must be able
to satisfy"* and *"endpoints relevant to creating, reading, and deleting this data"*:

> **INFERRED.** The Dashboard is a new administrative/setup client — most plausibly a
> web console — whose first job is to let an organisation complete the Part 3 go-live
> checklist without anyone running a Python seed script, and to create, inspect and
> remove that setup data afterwards.

Everything in `02` and `03` is scoped to that premise. If the Dashboard is instead an
*analytics* surface, or a super-admin platform console, or a replacement for the
Android Admin tab, the prerequisite list stands but the API gap analysis changes shape.
**This is Q1 in `04_OPEN_QUESTIONS.md` and is the one ambiguity that changes the most
downstream work.**
