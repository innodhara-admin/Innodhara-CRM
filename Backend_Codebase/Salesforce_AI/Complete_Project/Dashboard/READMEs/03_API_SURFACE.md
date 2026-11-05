# 03 · API Surface

> **SUPERSEDED IN PLACES — read `08_PROGRESS_AND_HANDOFF.md` first.**
> This is the frozen exploration record, written before Phase 1 added eleven
> routes, and it is deliberately not rewritten. **Stale here:** 140 routes
> (now **151**, 149 under `/api/v1`), the 3-DELETE method split (now **11**),
> several 🔴 gap flags that Phase 1 closed, and **§6.3 Idempotency, which is
> simply wrong** — the server reads no headers at all (D17). `08` §0.1 has the
> full list.

**140 routes.** 138 under `/api/v1` (`app/api/*.py`) + 2 health routes in
`app/main.py:187,197`. Counted this session by an independent regex pass over every
decorator, and confirmed by `python scripts/check_docs_in_sync.py`
(*"code: 55 tables, 755 columns, **140 routes**, 20 permissions…"*).

Method split, computed: **75 POST · 51 GET · 8 PATCH · 3 PUT · 3 DELETE**.

This document covers what a **setup/administration dashboard** needs — creating, reading
and deleting the data in `02_SEEDING_PREREQUISITES.md`. It is not a full API reference;
§7 points at the routes deliberately left out of scope.

> **How to read the gap flags**
> 🔴 = **no endpoint exists** for something the dashboard will need.
> ⚠ = an endpoint exists but is partial, misleading, or unauthorisable as needed.

---

## 1 · Routing and auth mechanics

### 1.1 Prefixes

`API_PREFIX = "/api/v1"` (`main.py:168`); every router is mounted with it
(`main.py:169-184`). **Four routers declare no prefix of their own**, so their paths sit
directly under `/api/v1` — this is easy to get wrong when reading a single file:

| Module | Router prefix | Effective base |
|---|---|---|
| `auth.py:20` | `/auth` | `/api/v1/auth` |
| `organisations.py:29` | `/orgs` | `/api/v1/orgs` |
| `admin.py:27` | `/admin` | `/api/v1/admin` |
| `leads.py:30` | `/leads` | `/api/v1/leads` |
| `meetings.py:29` | `/meetings` | `/api/v1/meetings` |
| `action_items.py:23` | `/action-items` | `/api/v1/action-items` |
| `proposals.py:28` | `/proposals` | `/api/v1/proposals` |
| `followups.py:22` | `/followups` | `/api/v1/followups` |
| `demos.py:23` | `/demos` | `/api/v1/demos` |
| `assistant.py:31` | `/assistant` | `/api/v1/assistant` |
| `projects.py:38` | `/projects` | `/api/v1/projects` |
| `messages.py:169` (`webhooks`) | `/webhooks` | `/api/v1/webhooks` |
| **`messages.py:20`** | **none** | `/api/v1` |
| **`misc.py:18`** | **none** | `/api/v1` |
| **`workflow.py:54`** | **none** | `/api/v1` |
| **`ops.py:37`** | **none** | `/api/v1` |

So the skills endpoint is `POST /api/v1/skills` — **not** `/api/v1/ops/skills`, and not
under `/admin` despite being an administrative concern.

### 1.2 The three authorisation gates

Read in full from `app/api/deps.py` (86 lines):

| Dependency | Behaviour | Line |
|---|---|---|
| `get_current_user` | Bearer JWT → `User`. 401 on missing/invalid/expired token or inactive account. **Does not check role or org** — a super_admin passes | `:29-44` |
| `get_org_context` | Depends on the above, then **rejects `super_admin` and any user without an `org_id`**, and rejects an inactive org. Returns `OrgContext(org_id, user_id, role, email, name)` | `:47-69` |
| `get_super_admin` | Requires `role == "super_admin"` | `:72-75` |
| `require_permission(p)` | Factory wrapping `get_org_context` + `has_permission(ctx.role, p)` | `:78-86` |

**Consequence for the dashboard:** a single account cannot both create organisations and
configure one. `POST /orgs` needs `super_admin`; every `/admin/*` route needs
`get_org_context`, which **refuses `super_admin` by design** (`deps.py:53-57`). Any
dashboard covering the whole go-live checklist must hold **two sessions**. See
`04_OPEN_QUESTIONS.md` Q1.

### 1.3 Two permission constants are dead

`create_organisation` and `platform_stats` exist in `_MATRIX`
(`permissions.py:55-56`) but **no route ever passes them to `require_permission`** —
verified by grep; `organisations.py` gates all four of its routes with
`Depends(get_super_admin)` instead. 18 of the 20 permissions are actually reachable.

### 1.4 `has_permission` fails closed on typos

`permissions.py:60-65` — an unknown *permission* string resolves to an empty set and
returns `False`; an unrecognised *role* string raises `ValueError`, which is caught and
also returns `False`. Safe, but it means a misspelled permission silently denies rather
than erroring.

---

## 2 · Endpoints for the go-live checklist

Everything the dashboard needs, in checklist order. Auth column gives the exact gate.

### 2.1 Organisation (checklist item 1)

| Method | Path | Handler | Auth | Notes |
|---|---|---|---|---|
| POST | `/api/v1/orgs` | `create_organisation` `organisations.py:59` | `get_super_admin` | Creates org + `org_settings` + first `org_admin`; returns `admin_temp_password` **once** |
| GET | `/api/v1/orgs` | `list_organisations` `:123` | `get_super_admin` | id, name, slug, email_domain, is_active |
| PATCH | `/api/v1/orgs/{org_id}/active` | `set_organisation_active` `:137` | `get_super_admin` | ⚠ `active: bool` is a **required query parameter, not a body field** (`:140`) |
| GET | `/api/v1/orgs/platform/stats` | `platform_stats` `:159` | `get_super_admin` | Aggregate counts only |

🔴 **No `PATCH /orgs/{id}`** — `name`, `slug`, `email_domain`, `logo_url` and
`brand_colors` are write-once at creation. `logo_url` and `brand_colors` are read back by
`GET /auth/me` and drive the app's theming, so branding **cannot be changed after
onboarding**.
🔴 **No `DELETE /orgs/{id}`** — deactivation via `PATCH .../active` is the only removal.

### 2.2 Staff (checklist item 2)

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/admin/users` | `register_staff` `admin.py:62` | `manage_staff` |
| GET | `/api/v1/admin/users` | `list_staff` `:107` | `manage_staff` |
| PATCH | `/api/v1/admin/users/{user_id}` | `update_staff` `:118` | `manage_staff` |
| POST | `/api/v1/admin/users/{user_id}/reset-password` | `reset_staff_password` `:156` | `manage_staff` |
| POST | `/api/v1/leave` | `record_leave` `ops.py:295` | `manage_staff` |

**Field coverage — the important part.** `users` has 21 columns; the API reaches 9.

| Column | Create (`CreateUserRequest` `:31-35`) | Update (`UpdateUserRequest` `:38-43`) | Read (`UserResponse` `:46-52`) |
|---|---|---|---|
| `email` | ✅ | — | ✅ |
| `name` | ✅ | ✅ | ✅ |
| `role` | ✅ | ✅ | ✅ |
| `phone` | ✅ | ✅ | ✅ |
| `is_active` | — | ✅ | ✅ |
| `require_action_item_review` | — | ✅ | 🔴 **not returned** |
| **`department`** | 🔴 | 🔴 | 🔴 |
| **`designation`** | 🔴 | 🔴 | 🔴 |
| **`whatsapp_number`** | 🔴 | 🔴 | 🔴 |
| **`max_open_tasks`** | 🔴 | 🔴 | 🔴 |
| **`working_days`** | 🔴 | 🔴 | 🔴 |
| `on_leave_from` / `on_leave_to` | — | ⚠ via `POST /leave` only | 🔴 |
| `smtp_app_password_enc` | — | ⚠ self-service only | ⚠ boolean via `/auth/me` |

🔴 **`department` is named as a requirement in the go-live checklist and has no write
path.** Verified by grep across `app/` and `scripts/`: the only writers are
`scripts/seed_workflows.py:233` and `scripts/dryrun_part2.py:421`, both direct DB writes.
It *is* read back by `GET /auth/me` (`auth.py:133`) — for the calling user only.
The same applies to `designation`, `whatsapp_number`, `max_open_tasks` and `working_days`.

🔴 **`GET /admin/users` returns only 6 of 21 columns** and there is **no
`GET /admin/users/{id}`.** A staff-detail screen cannot be built from this API.

🔴 **No `DELETE /admin/users/{id}`** — `is_active=False` is the only removal.

⚠ **No admin route to set another user's email app-password.**
`POST /auth/email-app-password` (`auth.py:184`) acts on `Depends(get_current_user)` —
i.e. always on *yourself*. An admin cannot complete checklist item 11's "better" option
on a colleague's behalf.

### 2.3 Skills (checklist item 3 — "the single highest-value entry")

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/skills` | `set_skill` `ops.py:631` | ⚠ **inline role check**, not a permission constant |
| GET | `/api/v1/skills?user_id=` | `list_skills` `ops.py:662` | `get_org_context` — **any org member** |

`POST /skills` is an **upsert**: an existing `(user_id, skill)` has its `level`
overwritten and returns `{"updated": true}` (`ops.py:641-653`).

⚠ **Authorisation is hard-coded**, not centralised: `ops.py:639` reads
`if ctx.role not in ("org_admin", "sales_lead", "operations_lead")`. That trio happens to
match `confirm_assignments`, but it is a **separate, uncentralised rule** — changing the
permission matrix will not change this route.

⚠ `POST /skills` does **not validate that `user_id` belongs to the caller's org.** It
filters by `org_id` when looking for an existing row (`:643-646`) but the insert at
`:654-656` stamps `ctx.org_id` onto whatever `user_id` was supplied. A caller can create
a `user_skills` row referencing a user in another org, scoped to their own org.
Not exploitable for data *reading*, but it produces orphan rows.

🔴 **No `DELETE /skills`.** A skill can be added and its level changed, but **never
removed**. Given that the manual calls skills the highest-value setup item and that a
wrong skill actively mis-routes work, this is the most consequential missing delete.
See `04_OPEN_QUESTIONS.md` Q4.

### 2.4 Programs, pricing, templates (checklist items 4–7)

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/admin/programs` | `add_program` `admin.py:190` | `manage_programs` |
| GET | `/api/v1/admin/programs` | `list_programs` `:219` | ⚠ `get_org_context` — **any org member** |
| POST | `/api/v1/admin/programs/{id}/pricing` | `set_pricing` `:257` | `edit_pricing` |
| GET | `/api/v1/admin/programs/{id}/pricing` | `get_pricing_history` `:303` | ⚠ **any org member** |
| POST | `/api/v1/admin/programs/{id}/proposal-templates` | `add_proposal_template` `:334` | `manage_templates` |
| GET | `/api/v1/admin/programs/{id}/proposal-templates` | `list_proposal_templates` `:388` | ⚠ **any org member** |
| POST | `/api/v1/admin/message-templates` | `add_message_template` `:421` | `manage_templates` |
| GET | `/api/v1/admin/message-templates` | `list_message_templates` `:475` | ⚠ **any org member** |

⚠ **Five "admin" GETs are readable by every authenticated org member**, including a
sales agent: programs, pricing history, proposal templates, message templates and demo
teams all use bare `Depends(get_org_context)` with no permission string. **The full rate
card and every template body — including all superseded versions — is org-wide readable.**
Whether that is intended is `04_OPEN_QUESTIONS.md` Q8.

🔴 **No `PATCH` and no `DELETE` for programs.** `name`, `description` and `is_active`
are immutable after creation. Since `code` is UNIQUE per org, a mistyped program cannot
be replaced under the same code — it becomes permanent clutter that the AI will still
read when matching offerings.

🔴 **No `DELETE` for pricing tables, proposal templates or message templates**, and no
way to re-activate a superseded version. "Undo" for a bad rate card is only "publish
another version", which permanently inflates the version number.

**Versioning is correct and must be respected by the UI.** All four families create a new
row and flip `is_current` (`admin.py:282-292`, `:359-376`, `:446-464`; `ops.py:456-465`).
Editing is never an UPDATE. `proposals` lock `template_version` + `pricing_version`
(`proposal.py:31,33`), which is what makes this safe.

### 2.5 Playbooks (checklist item 8)

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/playbooks` | `upsert_playbook` `ops.py:439` | `manage_programs` |
| GET | `/api/v1/playbooks/suggestions` | `list_suggestions` `ops.py:470` | `get_org_context` |
| POST | `/api/v1/playbooks/suggestions/{id}/decide` | `decide_suggestion` `ops.py:496` | `manage_programs` |

🔴 **There is no `GET /playbooks`.** Verified against the complete 140-route inventory:
the only playbook GET is `/playbooks/suggestions`, which returns **pending
Knowledge-Engine suggestions**, not the playbooks themselves. A dashboard **cannot read
back the task waves it wrote** — it can only blindly overwrite them. This is a listed
go-live prerequisite with a write path and no read path.

🔴 **No `DELETE`.** An unwanted phase wave can only be replaced by posting an empty
`entries` list, which still creates a version.

⚠ **`entries` is `list[dict]` with no sub-model** (`ops.py:436`) — nothing validates the
keys, the `phase` vocabulary, or that `required_skill` matches any real
`user_skills.skill`. See `04_OPEN_QUESTIONS.md` Q6.

### 2.6 Approval rules (checklist item 9)

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/approval-rules` | `create_approval_rule` `ops.py:567` | `manage_settings` |
| GET | `/api/v1/approval-rules` | `list_approval_rules` `ops.py:580` | ⚠ **any org member** |
| **DELETE** | `/api/v1/approval-rules/{rule_id}` | `delete_approval_rule` `ops.py:605` | `manage_settings` |

**The best-covered setup entity** — the only one with a genuine hard delete
(`await db.delete(rule)`, `ops.py:620`).

🔴 **No `PATCH`.** Editing a rule means delete-then-create, which changes the row id.
Any dashboard "edit" is therefore non-atomic: a failure between the two calls leaves the
org with **no** rule where it had one, silently changing who approves what.

⚠ `POST` splats the body straight into the model
(`ApprovalRule(org_id=ctx.org_id, **body.model_dump())`, `ops.py:574`) with **no
validation** of `entity_type`, `approver_role`, or the `condition` keys.

### 2.7 Settings, integrations, retention (checklist items 10–12, 14)

| Method | Path | Handler | Auth |
|---|---|---|---|
| GET | `/api/v1/admin/settings` | `get_org_settings` `admin.py:689` | `manage_settings` |
| PATCH | `/api/v1/admin/settings` | `update_org_settings` `admin.py:699` | `manage_settings` |
| PUT | `/api/v1/admin/integrations/email` | `set_email_integration` `admin.py:716` | `manage_settings` |
| PUT | `/api/v1/admin/integrations/whatsapp` | `set_whatsapp_integration` `admin.py:734` | `manage_settings` |
| PUT | `/api/v1/admin/integrations/calendar` | `set_calendar_integration` `admin.py:752` | `manage_settings` |
| GET | `/api/v1/admin/audit` | `view_audit_log` `admin.py:772` | `view_audit` |

`GET /admin/settings` **auto-creates the row if missing** and commits
(`_get_settings_row`, `admin.py:639-647`) — a GET with a side effect, but a harmless one.

⚠ **`PATCH /admin/settings` applies with a blind `setattr` loop**
(`admin.py:706-707`) over `model_dump(exclude_none=True)`. Two consequences:
1. **Omitting a field leaves it unchanged; there is no way to reset one to null.**
2. Fields with no Pydantic validation (`working_days`, `client_report_day`,
   `nudge_gap_days`, `reply_nudge_after_days`, `payment_reminder_schedule`, `timezone`,
   `currency`) accept **any** value of the right JSON type and store it silently.

⚠ **The three `*_configured` booleans are shallow and one of them is misleading.**
`_settings_response` (`admin.py:677-685`) reports `email_integration_configured` as
`bool(smtp_username)`, `whatsapp_integration_configured` as `bool(phone_number_id)`, and
`calendar_integration_configured` as `bool(calendar_id)`. None of them checks the
process-wide mode — see §3.

🔴 **No `DELETE` for any integration.** Credentials, once set, can only be overwritten.
There is no way to disconnect a mailbox or calendar through the API.

⚠ `set_calendar_integration` stores `credentials_file` **as an unencrypted filesystem
path** (`admin.py:759-763`) — unlike email and WhatsApp, which call `encrypt_secret`. The
dashboard cannot upload the service-account JSON; it can only name a path that must
already exist on the server.

### 2.8 Demo teams and vendors (checklist items 13, 15)

| Method | Path | Handler | Auth |
|---|---|---|---|
| POST | `/api/v1/admin/demo-teams` | `register_demo_team` `admin.py:505` | `manage_teams` (org_admin **or operations_lead**) |
| GET | `/api/v1/admin/demo-teams` | `list_demo_teams` `admin.py:552` | ⚠ **any org member** |
| POST | `/api/v1/vendors` | `create_vendor` `ops.py:258` | ⚠ **any org member** |
| GET | `/api/v1/vendors` | `list_vendors` `ops.py:270` | ⚠ **any org member** |

**Demo teams** validate every referenced user id against the caller's org before writing
(`admin.py:522-534`) — the most careful validation in the whole admin surface.

🔴 **No `PATCH`/`DELETE` for demo teams**, and **no way to add or remove a member** after
creation. Because `name` is UNIQUE per org (`demo.py:18`), a mistake cannot even be
fixed by re-creating under the same name.

🔴 **Vendors have no `PATCH` and no `DELETE`**, no validation whatsoever
(`Vendor(org_id=ctx.org_id, **body.model_dump())`, `ops.py:264`), and
⚠ **`GET /vendors` returns only 4 of the 7 written fields** — `contact_name`, `phone` and
`email` are write-only in practice (`ops.py:278-281`).

---

## 3 · 🔴 The environment wall — three settings no HTTP client can reach

The single most important structural gap. Four operational modes are **process-wide
environment variables**, not per-org columns, and **no endpoint exposes them**:

| Setting | Env var | Default | Where read |
|---|---|---|---|
| Email delivery | `EMAIL_MODE` | `dry_run` | `config.py:87` |
| WhatsApp delivery | `WHATSAPP_MODE` | `dry_run` | `config.py:95` |
| Calendar mirroring | `CALENDAR_MODE` | `off` | `config.py:102` |
| Inbound mail | `INBOUND_EMAIL_MODE` | `off` | `config.py:67` |

**Both halves are required for mail to leave.** Verified at
`app/services/email_service.py:147`:

```python
if settings.email_mode != "smtp" or creds is None:
    ...  # returns f"dry_run:{rel}" — writes the RFC-822 message to a file
```

So `PUT /admin/integrations/email` can store perfect credentials and **`GET
/admin/settings` will report `email_integration_configured: true`, while every approved
message is silently written to a file.** That is precisely the failure the manual warns
about twice — p.7 (*"otherwise approved messages are written to a file and everyone
believes they were sent"*) and p.16 (*"Approved messages never arrive → Sending is not
switched on"*).

**A setup dashboard cannot complete these checklist items, and cannot even report their
status honestly.** Raised as `04_OPEN_QUESTIONS.md` Q3.

---

## 4 · 🔴 Entities with no create endpoint

### 4.1 Projects — engine-created only

**There is no `POST /api/v1/projects`.** Verified twice: absent from the 140-route
inventory, and by grepping `Project(` across `app/` — only **two** construction sites
exist:

- `app/engines/planner_engine.py:1658` — a project is **born from a confirmed meeting**
- `app/api/projects.py:613` — `POST /projects/{id}/children` (branch projects only)

The 17 routes under `/projects` are all read, mutate or transition operations on a
project that already exists. **The only way to bring a project into being is to record or
type a meeting and confirm its review.** A dashboard cannot seed a project directly, and
any demo-data feature must drive `POST /meetings/notes` →
`POST /meetings/{id}/review/confirm`.

### 4.2 Other engine-only writes

Tables with no direct HTTP creation route, written only by engines:

| Table | Written by |
|---|---|
| `action_plans` | `planner_engine` |
| `assignments` | `assignment_engine` |
| `approvals` | `approval_engine` (via `communication_engine.draft_client_message` etc.) |
| `progress_events` | `engines/events.emit` |
| `ai_decisions` | every engine |
| `reminders` | `sync_engine` |
| `conflicts` | `planner_engine` / `inbound_engine` |
| `client_commitments` | `planner_engine` |
| `digests` | `knowledge_engine` |
| `playbook_suggestions` | `knowledge_engine` |
| `memory_chunks` | `ai/memory` |
| `threads`, `inbound_messages` | `inbound_engine` |
| `lead_state_history` | `lead_service` |
| `llm_usage`, `audit_log`, `idempotency_records`, `jobs` | infrastructure |

This is correct design — but it means **a "seed a realistic org" dashboard feature cannot
be built from CRUD endpoints.** It must either drive the real flows or write to the
database directly, as the existing seed scripts do.

---

## 5 · 🔴 Deletion — only three DELETE endpoints exist

**The entire 140-route API has three DELETE routes.** Verified by grep and by the route
inventory:

| # | Route | File | Semantics |
|---|---|---|---|
| 1 | `DELETE /api/v1/assistant/history?session_id=` | `assistant.py:114` | Hard-deletes chat turns |
| 2 | `DELETE /api/v1/projects/{project_id}/members/{user_id}` | `projects.py:302` | **Soft** — sets `left_at` and redistributes open work |
| 3 | `DELETE /api/v1/approval-rules/{rule_id}` | `ops.py:605` | Hard `db.delete(rule)` |

**None of the setup entities except approval rules can be deleted.** Complete list of
what the dashboard cannot remove:

| Entity | Removal available? |
|---|---|
| Organisation | ⚠ deactivate only (`PATCH /orgs/{id}/active`) |
| User | ⚠ deactivate only (`PATCH` `is_active=false`) |
| **User skill** | 🔴 **nothing** |
| **Program** | 🔴 **nothing** — not even `is_active` |
| **Pricing table** | 🔴 supersede only |
| **Proposal template** | 🔴 supersede only |
| **Message template** | 🔴 supersede only |
| **Playbook** | 🔴 supersede only |
| **Demo team** | 🔴 **nothing** |
| **Demo team member** | 🔴 **nothing** |
| **Vendor** | 🔴 **nothing** |
| Lead / contact / project / meeting / proposal | 🔴 **nothing** |
| Integration credentials | 🔴 overwrite only |

**This is deliberate, not an oversight.** It is idea 5 of the product — *"Nothing is
destroyed"* (manual p.3) — and the codebase enforces it consistently: tasks move to
`superseded`, plans supersede, every state change writes a history row.

**But the brief asks for a dashboard that can delete this data.** Those two facts are in
direct tension, and it is not mine to resolve — see `04_OPEN_QUESTIONS.md` **Q4**, the
question that most changes the shape of the work.

The one existing precedent for bulk removal is
`scripts/reset_for_datacentre_demo.py`, which bypasses the API entirely and issues raw
`sqlite3` DELETEs with `PRAGMA foreign_keys=OFF` (`:120`).

### 5.1 What makes deletion genuinely risky here

Three properties of the schema, established in `01_DATA_MODEL.md`:

1. **28 of 55 tables have no non-`org_id` foreign key.** `action_items.project_id`,
   `deliverables.project_id`, `invoices.project_id`, `incidents.project_id`,
   `payments.invoice_id` and `projects.parent_project_id` are **all soft references**.
2. **No `ondelete=` cascade rules exist anywhere.**
3. **FK enforcement is off by default on SQLite** — `app/database.py:43-51` sets only
   `journal_mode=WAL` and `busy_timeout`.

So the database will not stop a delete that orphans rows, and will not clean up after
one. Any delete feature must implement its own dependency ordering — the
`WIPE` list in `reset_for_datacentre_demo.py:38-51` is a working, child-before-parent
ordering of all 43 transactional tables and is the best starting point that exists.

---

## 6 · Other findings relevant to a second client

### 6.1 ⚠ `POST /api/v1/webhooks/whatsapp` is unauthenticated and not org-scoped

`messages.py:184` declares no auth dependency at all. Its lookup at `:197-203` selects
`OutboundMessage` by `provider_message_id` with **no `org_id` filter**, then mutates
`status` and writes a delivery-log row. Its GET sibling (`:172`) at least checks
`hub.verify_token`; the POST checks nothing. **I read this handler in full to confirm it.**

This is not a dashboard concern directly, but a dashboard that surfaces message delivery
state is surfacing data any unauthenticated caller can currently alter across every
tenant. Raised as `04_OPEN_QUESTIONS.md` Q10.

### 6.2 ⚠ 16 of 17 `/projects` routes carry no permission check

Only `GET /projects/resolve/{type}/{id}` requires anything (`view_leads`). The rest —
including `POST /projects/{id}/status`, `POST /projects/{id}/children`,
`POST /projects/{id}/phase-shift` and `DELETE /projects/{id}/members/{user_id}` — are open
to **any authenticated member of the org, of any role**.

Likewise `POST /api/v1/messages/draft` (`workflow.py:927`) does **not** require
`send_messages`, unlike every route in `messages.py`; and `POST /api/v1/sync/sweep`
(`workflow.py:898`) lets any org member trigger the org-wide sweep.

### 6.3 Idempotency

`outbound_messages` has a UNIQUE `(org_id, idempotency_key)` index (`messaging.py:24`)
and `idempotency_records` has UNIQUE `(org_id, key)` (`audit.py:33`). The Android client
mints keys at intent time so an offline-queued approval and its replay share one
(verified: `IdempotencyInterceptor` adds a random `Idempotency-Key` to every
POST/PATCH/PUT/DELETE lacking one). **A dashboard must do the same** for any write it
retries.

### 6.4 Params that look like bodies

Three routes take what a form would naturally send as a body:

- `PATCH /orgs/{org_id}/active` → `active: bool` as a **required query param**
  (`organisations.py:140`)
- `POST /messages/{id}/approve` → `allow_blanks: bool = False` as a query param
  (`messages.py:133`)
- `GET /deliverables` → `project_id` is **required**; a bare call returns 422
  (`ops.py:406`)

---

## 7 · What this document deliberately excludes

Out of scope for a setup dashboard, listed so the omission is visible rather than
accidental. All were read and inventoried; none contains a setup-data gap.

| Area | Routes | Module |
|---|---|---|
| Leads, contacts, consent, intelligence | 10 | `leads.py` |
| Meetings, upload, review gate | 7 | `meetings.py` |
| Task lifecycle (`/tasks/*`), approvals, assignments, inbound, incidents, digests, sweep | 23 | `workflow.py` |
| Projects (read/mutate/transition) | 17 | `projects.py` |
| Proposals | 7 | `proposals.py` |
| Messages + webhooks | 6 | `messages.py` |
| Assistant (Jarvis) | 3 | `assistant.py` |
| Demos | 4 | `demos.py` |
| Follow-ups | 3 | `followups.py` |
| Action items (legacy CRUD) | 3 | `action_items.py` |
| Notifications, devices, files, dictate, privacy | 7 | `misc.py` |
| Invoices, payments, bookings, leave, deliverables | 11 | `ops.py` |
| Auth | 5 | `auth.py` |
| Health | 2 | `main.py` |

---

## 8 · Summary of every gap

### 🔴 No endpoint exists

| # | What is missing | Impact | Checklist item |
|---|---|---|---|
| 1 | Write path for `users.department` | **Named in the checklist.** Escalation routing cannot be configured | 2 |
| 2 | Write path for `designation`, `whatsapp_number`, `max_open_tasks`, `working_days` | Capacity and contact routing unconfigurable | 2 |
| 3 | `GET /admin/users/{id}` and 15 of 21 user columns in any read | No staff-detail screen is buildable | 2 |
| 4 | `DELETE /skills` | A wrong skill mis-routes work permanently | 3 |
| 5 | `PATCH` / `DELETE` for programs | A mistyped offering is permanent and still read by the AI | 4 |
| 6 | `GET /playbooks` | **Write-only prerequisite** — cannot read back task waves | 8 |
| 7 | `PATCH /approval-rules/{id}` | Edit = non-atomic delete-then-create | 9 |
| 8 | Any control over `EMAIL_MODE` / `WHATSAPP_MODE` / `CALENDAR_MODE` / `INBOUND_EMAIL_MODE` | **Checklist items 11 and 16 uncompletable** | 11, 16 |
| 9 | `PATCH /orgs/{id}` | Org name, logo, brand colours are write-once | 1 |
| 10 | `POST /projects` | Projects exist only via a meeting or as branch children | — |
| 11 | Delete for 11 setup entity types | See §5 | all |
| 12 | Admin route to set another user's email app-password | Checklist item 11's preferred option is self-service only | 11 |
| 13 | Any way to un-supersede a version | No undo for a bad rate card or template | 5, 6, 7 |

### ⚠ Exists but partial or misleading

| # | What | Where |
|---|---|---|
| 14 | `email_integration_configured` reports `true` while mail goes to a file | `admin.py:677-679` |
| 15 | 5 admin GETs readable by **any** org member (pricing, templates, programs, demo teams) | §2.4 |
| 16 | `POST /skills` uses a hard-coded role list, not a permission | `ops.py:639` |
| 17 | `POST /skills` doesn't verify `user_id` is in the caller's org | `ops.py:654-656` |
| 18 | `PATCH /admin/settings` blind `setattr`; 7 dials unvalidated; no reset-to-null | `admin.py:706-707` |
| 19 | `entries` / `condition` / `joint_condition` are unvalidated raw JSON | `ops.py:436`, `:555`, `:561` |
| 20 | `GET /vendors` omits `contact_name`, `phone`, `email` | `ops.py:278-281` |
| 21 | Calendar `credentials_file` stored unencrypted as a server path | `admin.py:759-763` |
| 22 | `POST /webhooks/whatsapp` unauthenticated **and cross-tenant** | `messages.py:184-203` |
| 23 | 16/17 `/projects` routes ungated; `/messages/draft` and `/sync/sweep` ungated | §6.2 |
| 24 | Super admin cannot reach `/admin/*` — two sessions required | `deps.py:53-57` |

Every item above is carried into `04_OPEN_QUESTIONS.md` as a question rather than a
recommendation.
