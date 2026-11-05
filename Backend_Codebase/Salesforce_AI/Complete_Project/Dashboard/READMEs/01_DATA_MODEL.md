# 01 · Data Model

> **Read `08_PROGRESS_AND_HANDOFF.md` first.**
> This is the frozen exploration record. Its figures — **55 tables, 755
> columns** — were re-measured against the code and are still correct; no
> column has been added or removed since. One known schema defect is recorded
> elsewhere: `playbook_suggestions.program_id` carries no `ForeignKey`
> (`09` §4a).

**55 tables · 755 columns.** Both figures computed this session by iterating
`Base.metadata.sorted_tables` after importing `app.models`, and independently confirmed
by `python scripts/check_docs_in_sync.py` (*"code: 55 tables, 755 columns…"*).

Every table below was read from its model file. File and line are given for each table
and for any field whose meaning is not obvious from its name. Anything **INFERRED** is
labelled as such — there are only three such marks in this document, all collected in §11.

---

## 0 · Conventions that apply to every table

Read from `app/models/base.py` (40 lines, read in full).

| Mixin | Columns it contributes | Definition |
|---|---|---|
| `PKMixin` | `id` — `String(32)`, **primary key**, `default=new_id` | `base.py:24-25` |
| `TimestampMixin` | `created_at` — `DateTime`, `default=utcnow`, NOT NULL<br>`updated_at` — `DateTime`, `default=utcnow`, `onupdate=utcnow`, NOT NULL | `base.py:28-32` |
| `OrgScopedMixin` | `org_id` — `String(32)`, **FK → `organisations.id`**, NOT NULL, indexed | `base.py:35-40` |

- `new_id()` = `uuid4().hex` → a **32-character hex string**, not an integer and not a
  native UUID column (`base.py:16-17`).
- `utcnow()` = `datetime.now(timezone.utc).replace(tzinfo=None)` → **naïve UTC**.
  Every `DateTime` in this schema is naïve; nothing stores an offset (`base.py:20-21`).
- The design rule behind `OrgScopedMixin`, quoted in its own docstring: *"Every row also
  stores the org_id directly, so the database can fence rows off even without following
  the links"* (`base.py:3-5`).
- **Two tables deliberately break the org rule.** `users.org_id` is *nullable* and has
  **no foreign key** (`user.py:23`) so the platform Super Admin can exist above all
  organisations; `audit_log.org_id` and `llm_usage.org_id` are nullable for
  platform-level rows (`audit.py:20`, `audit.py:48`).

In the tables below, columns supplied by a mixin are **not repeated**. A table marked
*PK + TS + Org* has `id`, `created_at`, `updated_at`, `org_id` in addition to what is listed.

### Type notation

`String(n)` = VARCHAR(n) · `Text` = unbounded · `JSON` = SQLAlchemy `JSON` (a JSON1 text
column on SQLite) · `Float` · `Integer` · `Boolean` · `DateTime` (naïve) · `Date`.
Python-side, a `Mapped[X | None]` is nullable and a `Mapped[X]` without a default is not.

---

## 1 · Platform & People

### 1.1 `organisations` — 9 columns
`Organisation`, `app/models/organisation.py:13`. Mixins: **PK + TS** (no org scope — it *is* the org).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `String(200)` | NOT NULL | `:18` |
| `slug` | `String(100)` | **UNIQUE**, indexed, NOT NULL | `:19` — the tenant key used at login |
| `email_domain` | `String(200)` | indexed, NOT NULL | `:20` — stored **without** a leading `@`; `admin.py:84` tests `email.endswith("@" + org.email_domain)`, and `organisations.py:65` lstrips `@` for that reason |
| `logo_url` | `String(500)` | nullable | `:21` |
| `brand_colors` | `JSON` | `default=dict` | `:22` — returned to the app by `/auth/me` |
| `is_active` | `Boolean` | `default=True`, NOT NULL | `:23` — false blocks login (`auth.py:85-86`) and `get_org_context` (`deps.py:61-62`) |

**Parent of every other record.** No table references it by FK except through `OrgScopedMixin`.

### 1.2 `org_settings` — 32 columns
`OrgSettings`, `app/models/organisation.py:26`. Mixins: **PK + TS**.
The single widest configuration row in the system, and the dashboard's main settings target.

| Column | Type | Default | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | — | **UNIQUE**, FK → `organisations.id`, NOT NULL, indexed. `:34-36`. One row per org |
| `require_action_item_review` | `Boolean` | `True` | `:39` — overridable per user |
| `auto_suggest_lead_state` | `Boolean` | `True` | `:40` |
| `audio_retention_days` | `Integer` | `90` | `:43` |
| `transcript_retention_days` | `Integer` | `365` | `:44` |
| `llm_monthly_budget_usd` | `Float` | `50.0` | `:47` |
| `timezone` | `String(50)` | `"Asia/Kolkata"` | `:50` |
| `currency` | `String(10)` | `"INR"` | `:51` |
| `followup_cadence_days` | `Integer` | `7` | `:54` |
| `email_integration` | `JSON` | `dict` | `:60` — `{"from_domain","smtp_username","smtp_app_password_enc"}`; the password is **Fernet-encrypted** (`core/crypto.py`) |
| `whatsapp_integration` | `JSON` | `dict` | `:61` — `{"access_token_enc","phone_number_id"}` |
| `calendar_integration` | `JSON` | `dict` | `:62` — `{"calendar_id","credentials_file","meet_link"}` |
| `assignment_mode` | `String(20)` | `"lead_confirm"` | `:66` — `auto` \| `lead_confirm` |
| `working_days` | `JSON` | `["Mon".."Sat"]` | `:68-70` |
| `workday_start` | `String(5)` | `"09:00"` | `:71` |
| `workday_end` | `String(5)` | `"18:30"` | `:72` |
| `quiet_hours_override_priority` | `String(5)` | `"P1"` | `:74` — the one priority allowed to break quiet hours |
| `nudge_gap_days` | `JSON` | `{"level1":1,"level2":3,"level3":5}` | `:76-78` — working days after due date per nudge level |
| `max_unanswered_nudges` | `Integer` | `2` | `:80` — then stop and create a call task |
| `max_client_messages_per_week` | `Integer` | `3` | `:82` — courtesy cap **per stakeholder across ALL projects** |
| `lead_cold_after_days` | `Integer` | `30` | `:84` |
| `high_load_caution_pct` | `Integer` | `80` | `:86` — % of `max_open_tasks` at which work is steered away |
| `delivery_requires_advance` | `Boolean` | `True` | `:88` |
| `scope_change_requires_confirmation` | `Boolean` | `True` | `:90` |
| `client_report_day` | `String(10)` | `"Friday"` | `:92` |
| `client_report_time` | `String(5)` | `"16:00"` | `:93` |
| `payment_reminder_schedule` | `JSON` | 4-entry ladder | `:98-106` — `[{"offset":-3,"tone":"heads_up"},{"offset":3,"tone":"polite"},{"offset":10,"tone":"firm","cc":"decision_maker"},{"offset":20,"action":"call_task"}]`. `cc` names an influence level **or** a client-vocabulary stakeholder role |
| `reply_nudge_after_days` | `JSON` | `{"nudge1":4,"nudge2":8,"call_task":12}` | `:108-110` |
| `ai_confidence_threshold` | `Float` | `0.6` | `:112` — below this, engines route to a human |

### 1.3 `users` — 21 columns
`User`, `app/models/user.py:13`. Mixins: **PK + TS** (org handled manually).
Index: `ix_users_org_role` on `(org_id, role)` — `:21`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | **nullable, NO FK**, indexed | `:23` — null **only** for the Super Admin |
| `email` | `String(320)` | **UNIQUE**, indexed, NOT NULL | `:24` — email *is* the identity and implies the org |
| `name` | `String(200)` | NOT NULL | `:25` |
| `phone` | `String(30)` | nullable | `:26` |
| `role` | `String(30)` | NOT NULL | `:27` — one of the 6 `Role` values; **not a DB enum**, validated in the API layer |
| `password_hash` | `String(300)` | NOT NULL | `:28` |
| `is_active` | `Boolean` | `default=True`, NOT NULL | `:29` |
| `must_change_password` | `Boolean` | `default=False` | `:30` |
| `smtp_app_password_enc` | `Text` | nullable | `:34` — per-user Gmail app password, Fernet-encrypted, so mail leaves from the salesperson's own address |
| `require_action_item_review` | `Boolean` | **nullable** | `:38` — `None` means "follow the org setting". Tri-state |
| `last_login_at` | `DateTime` | nullable | `:40` |
| `designation` | `String(100)` | nullable | `:43` — human job title |
| `department` | `String(20)` | nullable | `:44` — `sales` \| `operations` \| `accounts`; **decides who receives this person's escalations** |
| `whatsapp_number` | `String(30)` | nullable | `:45` |
| `max_open_tasks` | `Integer` | `default=8` | `:47` — the size of this person's plate; the AI never loads beyond it except P1 |
| `working_days` | `JSON` | nullable | `:49` — `None` = follow the org |
| `on_leave_from` | `Date` | nullable | `:50` |
| `on_leave_to` | `Date` | nullable | `:51` |

> **Dashboard-critical.** The last six fields (`designation`, `department`,
> `whatsapp_number`, `max_open_tasks`, `working_days`, `on_leave_*`) have **no write
> path in the API**. Verified by grep: the only writers are `scripts/seed_workflows.py:232-233`
> and `scripts/dryrun_part2.py:420-421` — direct DB writes. `on_leave_*` is the sole
> exception, written by `resource_engine.record_leave` (`:198-199`) behind `POST /leave`.
> See `03_API_SURFACE.md` §4.2.

### 1.4 `user_skills` — 7 columns
`UserSkill`, `app/models/user.py:54`. Mixins: **PK + TS + Org**.
*"the heart of task assignment"* (`:55`).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `user_id` | `String(32)` | indexed, NOT NULL | `:67` — **no FK declared** |
| `skill` | `String(100)` | NOT NULL | `:68` — free-form text, no controlled vocabulary |
| `level` | `String(10)` | `default="good"` | `:69` — `basic` \| `good` \| `expert` |

**Indexes:** `ix_user_skills_org_skill` on `(org_id, skill)`; `ix_user_skills_user_skill`
on `(user_id, skill)` **UNIQUE** — `:62-65`. One row per person per skill.

**Relationship:** matched against `action_items.required_skill` to build the Assignment
Engine's candidate list. Scoring: `SKILL_LEVEL_SCORE = {expert:3, good:2, basic:1}`
(`constants.py:173`).

### 1.5 `notifications` — 11 columns
`Notification`, `app/models/user.py:88`. Mixins: **PK + TS**.
Index: `ix_notifications_org_user_read` on `(org_id, user_id, is_read)` — `:92`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | NOT NULL, indexed | `:94` — declared manually, **no FK** |
| `user_id` | `String(32)` | NOT NULL, indexed | `:95` |
| `title` | `String(300)` | NOT NULL | `:96` |
| `body` | `Text` | nullable | `:97` |
| `kind` | `String(50)` | `default="general"` | `:98` |
| `entity_type` | `String(50)` | nullable | `:99` — polymorphic pointer, no FK |
| `entity_id` | `String(32)` | nullable | `:100` |
| `is_read` | `Boolean` | `default=False`, NOT NULL | `:101` |

### 1.6 `device_tokens` — 9 columns
`DeviceToken`, `app/models/user.py:72`. Mixins: **PK + TS**.
Index: `ix_device_tokens_user` on `(user_id)` — `:78`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | NOT NULL, indexed | `:80` |
| `user_id` | `String(32)` | NOT NULL | `:81` |
| `fcm_token` | `String(512)` | **UNIQUE**, NOT NULL | `:82` |
| `platform` | `String(20)` | `default="android"` | `:83` |
| `app_version` | `String(30)` | nullable | `:84` |
| `last_seen_at` | `DateTime` | nullable | `:85` |

**This table is always empty in practice** — the Android app never calls `POST /devices`
(see `00_CONTEXT.md` §3.2).

### 1.7 `audit_log` — 8 columns
`AuditLog`, `app/models/audit.py:14`. Mixins: **PK only** (no timestamps, no org mixin).
Index: `ix_audit_org_at` on `(org_id, at)` — `:18`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | **nullable**, indexed | `:20` — `None` = platform level |
| `user_id` | `String(32)` | nullable, indexed | `:21` |
| `action` | `String(100)` | NOT NULL | `:22` — e.g. `admin.staff_registered`, `platform.org_created` |
| `entity_type` | `String(50)` | nullable | `:23` |
| `entity_id` | `String(32)` | nullable | `:24` |
| `detail` | `JSON` | nullable | `:25` |
| `at` | `DateTime` | `default=utcnow`, NOT NULL | `:26` |

### 1.8 `idempotency_records` — 6 columns
`IdempotencyRecord`, `app/models/audit.py:29`. Mixins: **PK only**.
Index: `ix_idem_org_key` on `(org_id, key)` **UNIQUE** — `:33`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | NOT NULL | `:35` |
| `key` | `String(200)` | NOT NULL | `:36` |
| `endpoint` | `String(200)` | NOT NULL | `:37` |
| `entity_id` | `String(32)` | nullable | `:38` |
| `at` | `DateTime` | `default=utcnow`, NOT NULL | `:39` |

### 1.9 `llm_usage` — 12 columns
`LlmUsage`, `app/models/audit.py:42`. Mixins: **PK only**.
Index: `ix_llm_usage_org_at` on `(org_id, at)` — `:46`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | nullable, indexed | `:48` |
| `user_id` | `String(32)` | nullable | `:49` |
| `provider` | `String(30)` | NOT NULL | `:50` |
| `model` | `String(100)` | NOT NULL | `:51` |
| `purpose` | `String(100)` | NOT NULL | `:52` |
| `input_tokens` | `Integer` | `default=0` | `:53` |
| `output_tokens` | `Integer` | `default=0` | `:54` |
| `cost_usd` | `Float` | `default=0.0` | `:55` |
| `duration_ms` | `Integer` | `default=0` | `:56` |
| `error` | `Text` | nullable | `:57` |
| `at` | `DateTime` | `default=utcnow`, NOT NULL | `:58` |

Feeds `org_settings.llm_monthly_budget_usd` enforcement.

### 1.10 `jobs` — 14 columns
`JobRecord`, `app/models/job.py:15`. Mixins: **PK only**.
Index: `ix_jobs_status_next_run` on `(status, next_run_at)` — `:17`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `org_id` | `String(32)` | nullable, indexed | `:19` |
| `type` | `String(100)` | NOT NULL | `:20` |
| `payload` | `JSON` | `default=dict` | `:21` |
| `status` | `String(30)` | `default="queued"`, NOT NULL | `:22-24` — `queued`\|`running`\|`done`\|`failed`\|`dead_letter` |
| `priority` | `Integer` | `default=100` | `:27` — **lower = higher priority** |
| `attempts` | `Integer` | `default=0` | `:28` |
| `max_attempts` | `Integer` | `default=4` | `:29` |
| `next_run_at` | `DateTime` | `default=utcnow`, NOT NULL | `:30` |
| `last_error` | `Text` | nullable | `:31` |
| `result` | `JSON` | nullable | `:32` |
| `created_at` | `DateTime` | `default=utcnow`, NOT NULL | `:33` — declared explicitly, not from the mixin |
| `started_at` | `DateTime` | nullable | `:34` |
| `finished_at` | `DateTime` | nullable | `:35` |

### 1.11 `assistant_turns` — 10 columns
`AssistantTurn`, `app/models/assistant.py:22`. Mixins: **PK + TS + Org**.
Index: `ix_assistant_turns_session` on `(org_id, user_id, session_id, seq)` — `:25-28`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `session_id` | `String(64)` | NOT NULL | `:32` — minted by the client, one per chat thread |
| `user_id` | `String(32)` | FK → `users.id`, NOT NULL, indexed | `:33-35` |
| `seq` | `Integer` | NOT NULL, `default=0` | `:39` — position; `created_at` alone is insufficient because both turns of one exchange are written in the same instant |
| `role` | `String(16)` | NOT NULL | `:40` — `user` \| `assistant` |
| `content` | `Text` | NOT NULL | `:41` |
| `agent` | `String(30)` | nullable | `:44` — which specialist answered; null on user turns |

**Deliberate constraint** (`:6-11`): rows hold **plain text only** — never tool calls,
tool results or entity ids, because replaying yesterday's id would let the model act on
a record whose permissions may since have changed.

---

## 2 · Clients & Relationships

### 2.1 `leads` — 21 columns
`Lead`, `app/models/lead.py:14`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, state)`, `(org_id, owner_id)`, `(org_id, name)` — `:19-21`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `String(300)` | NOT NULL | `:24` |
| `state` | `String(50)` | `default="open"`, NOT NULL | `:25` — see the state machine below |
| `is_important` | `Boolean` | `default=False`, NOT NULL | `:27` — *"Active and Important"* = `active` + this flag |
| `owner_id` | `String(32)` | FK → `users.id`, indexed, nullable | `:29` |
| `address` | `Text` | nullable | `:30` |
| `city` | `String(100)` | nullable | `:31` |
| `region` | `String(100)` | nullable | `:32` |
| `website` | `String(300)` | nullable | `:33` |
| `source` | `String(100)` | nullable | `:34` |
| `notes` | `Text` | nullable | `:35` |
| `last_activity_at` | `DateTime` | `default=utcnow`, nullable | `:36` |
| `suggested_state` | `String(50)` | nullable | `:38` — system-suggested move awaiting human confirmation |
| `suggested_state_reason` | `Text` | nullable | `:39` |
| `lost_reason` | `String(30)` | nullable | `:42` — `budget_timing`\|`chose_competitor`\|`no_need`\|`other` |
| `revival_date` | `DateTime` | nullable | `:43` |
| `revival_context` | `Text` | nullable | `:45` — AI-written wake-up brief |
| `revival_fired_at` | `DateTime` | nullable | `:46` |

**Lead state machine.** Seven states (`constants.py:23-32`), with allowed transitions
declared as data in `LEAD_STATE_TRANSITIONS` (`constants.py:35-55`):

| From | May go to |
|---|---|
| `open` | `active`, `cold`, `lost_for_now` |
| `active` | `execution_in_progress`, `cold`, `lost_for_now` |
| `cold` | `active`, `open`, `lost_for_now` |
| `execution_in_progress` | `client_execution_in_progress`, `lost_for_now`, `active` |
| `client_execution_in_progress` | `closed`, `execution_in_progress`, `lost_for_now` |
| `closed` | `lost_for_now` |
| `lost_for_now` | `open`, `active` (retry later) |

### 2.2 `lead_state_history` — 8 columns
`LeadStateHistory`, `app/models/lead.py:49`. Mixins: **PK + Org** (no `TimestampMixin`).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:52` |
| `from_state` | `String(50)` | nullable | `:53` |
| `to_state` | `String(50)` | NOT NULL | `:54` |
| `reason` | `Text` | nullable | `:55` |
| `changed_by` | `String(32)` | nullable | `:56` — a user id **or the literal string `"system"`** |
| `changed_at` | `DateTime` | `default=utcnow`, NOT NULL | `:57` |

### 2.3 `contacts` — 13 columns
`Contact`, `app/models/lead.py:60`. Mixins: **PK + TS + Org**.
Index: `ix_contacts_org_lead` on `(org_id, lead_id)` — `:64`.
*"A decision maker at a school (Principal, Owner...). Does not log in."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:66` |
| `name` | `String(200)` | NOT NULL | `:67` |
| `title` | `String(200)` | nullable | `:68` |
| `email` | `String(320)` | nullable | `:69` — **not unique, not validated at the DB** |
| `phone` | `String(30)` | nullable | `:70` |
| `is_primary` | `Boolean` | `default=False` | `:71` |
| `source` | `String(20)` | `default="manual"` | `:72` — `card`\|`manual`\|`meeting` |
| `card_image_path` | `String(500)` | nullable | `:73` |
| `needs_review` | `Boolean` | `default=False` | `:75` — low-confidence OCR is flagged, not hidden. A flagged contact **is never messaged** (manual p.14) |

### 2.4 `consent_records` — 10 columns
`ConsentRecord`, `app/models/lead.py:78`. Mixins: **PK + TS + Org**.
*"Proof the contact was told about recording (DPDP alignment)."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:83` |
| `meeting_id` | `String(32)` | nullable, indexed | `:84` — **no FK** |
| `method` | `String(50)` | `default="verbal"` | `:85` — `verbal`\|`written`\|`in_app` |
| `note` | `Text` | nullable | `:86` |
| `captured_by` | `String(32)` | nullable | `:87` |
| `captured_at` | `DateTime` | `default=utcnow`, NOT NULL | `:88` |

**Hard gate:** `POST /meetings/upload` refuses without a pre-existing consent row ≤24 h old.

### 2.5 `client_intelligence` — 9 columns
`ClientIntelligence`, `app/models/lead.py:91`. Mixins: **PK + TS + Org**.
Index: `ix_intel_org_lead` on `(org_id, lead_id)` — `:95`.
Renamed from `school_intelligence`; migration at `database.py:80-83`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:97` |
| `note` | `Text` | NOT NULL | `:98` |
| `category` | `String(100)` | nullable | `:99` |
| `source` | `String(20)` | `default="typed"` | `:100` — `voice`\|`typed`\|`system` |
| `added_by` | `String(32)` | nullable | `:101` |

### 2.6 `memory_chunks` — 9 columns
`MemoryChunk`, `app/models/memory.py:16`. Mixins: **PK + TS + Org**.
Index: `ix_memory_org_lead` on `(org_id, lead_id)` — `:18`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, nullable, indexed | `:20` |
| `source_type` | `String(30)` | NOT NULL | `:21` — `meeting`\|`note`\|`proposal` |
| `source_id` | `String(32)` | nullable | `:22` |
| `text` | `Text` | NOT NULL | `:23` |
| `embedding` | `JSON` | NOT NULL | `:24` — a JSON float array; cosine search runs **in Python** (`ai/memory.py`) |

### 2.7 `stakeholders` — 12 columns
`Stakeholder`, `app/models/project.py:70`. Mixins: **PK + TS + Org**.
Index: `ix_stakeholders_proj_contact` on `(project_id, contact_id)` — `:74`.
*"One contact in the context of one project."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | FK → `projects.id`, indexed | `:76` |
| `contact_id` | `String(32)` | FK → `contacts.id`, indexed | `:77` |
| `role_at_client` | `String(50)` | nullable | `:82` — **free-form snake_case in the client's own vocabulary** (`principal`, `cto`, `procurement_head`, `store_manager`). Deliberately **not** an enum (`constants.py:290-293`). Renamed from `role_at_school`; migration at `database.py:73-77` |
| `influence` | `String(20)` | nullable | `:84` — `decision_maker`\|`influencer`\|`gatekeeper`. **This is the fixed vocabulary the engines act on**; weights `{decision_maker:3, gatekeeper:2, influencer:1}` (`constants.py:302-306`) |
| `preferred_channel` | `String(20)` | `default="email"` | `:85` |
| `preferred_language` | `String(30)` | `default="english"` | `:86` |
| `receives_progress_updates` | `Boolean` | `default=False` | `:87` |
| `do_not_contact` | `Boolean` | `default=False` | `:89` — **absolute stop**; the Communication Engine refuses drafts while true |

---

## 3 · Projects & Plans

### 3.1 `projects` — 22 columns
`Project`, `app/models/project.py:19`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, status)`, `(org_id, lead_id)` — `:24-25`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:28` |
| `program_id` | `String(32)` | FK → `programs.id`, nullable | `:29` |
| `name` | `String(300)` | NOT NULL | `:30` |
| `objective` | `Text` | nullable | `:31` |
| `status` | `String(30)` | `default="planning"`, NOT NULL | `:34` — 10 values: `planning`, `proposal_stage`, `negotiation`, `agreed`, `preparation`, `delivery`, `payment_pending`, `closed`, `on_hold`, `lost` (`constants.py:183-193`). **No transition table exists** — unlike leads |
| `status_reason` | `Text` | nullable | `:35` |
| `health` | `String(20)` | `default="on_track"` | `:37` — `on_track`\|`at_risk`\|`delayed`, **recomputed by the Sync Engine** |
| `health_reason` | `Text` | nullable | `:38` |
| `sales_owner_id` | `String(32)` | FK → `users.id`, nullable | `:39` |
| `ops_owner_id` | `String(32)` | FK → `users.id`, nullable | `:40` |
| `current_plan_version` | `Integer` | `default=0` | `:41` |
| `start_date` | `DateTime` | nullable | `:42` |
| `target_end_date` | `DateTime` | nullable | `:43` |
| `value_estimate` | `Float` | nullable | `:45` — *"Always computed from pricing tables and approved special prices"*, never typed |
| `currency` | `String(10)` | `default="INR"` | `:46` |
| `parent_project_id` | `String(32)` | nullable, indexed | `:48` — chain deals: commercials on the parent, delivery on children. **No FK** |
| `invoicing_mode` | `String(20)` | nullable | `:49` — `group`\|`per_branch` |
| `created_from_meeting_id` | `String(32)` | nullable | `:50` |

> **A `Project` row can only be created two ways** (verified by grepping `Project(`
> across `app/`): by `planner_engine.py:1658` (born from a meeting), or by
> `projects.py:613` (`POST /projects/{id}/children`). **There is no `POST /projects`.**

### 3.2 `project_members` — 10 columns
`ProjectMember`, `app/models/project.py:53`. Mixins: **PK + TS + Org**.
Index: `ix_project_members_proj_user` on `(project_id, user_id)` — `:57` (**not** unique).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | FK → `projects.id`, indexed | `:59` |
| `user_id` | `String(32)` | FK → `users.id`, indexed | `:60` |
| `role_in_project` | `String(50)` | nullable | `:63` — `trainer`\|`assistant_trainer`\|`proposal_writer`\|`coordinator`\|`accounts`\|`media`\|`owner` |
| `added_by` | `String(32)` | nullable | `:64` — a user id **or the literal `"ai"`** |
| `joined_at` | `DateTime` | nullable | `:65` |
| `left_at` | `DateTime` | nullable | `:67` — **filled instead of deleting the row**; open tasks get redistributed. This is what `DELETE /projects/{id}/members/{user_id}` does |

### 3.3 `action_plans` — 14 columns
`ActionPlan`, `app/models/project.py:92`. Mixins: **PK + TS + Org**.
Index: `ix_action_plans_proj_version` on `(project_id, version)` **UNIQUE** — `:101`.
*"Every re-plan creates a new version with a written diff — the old version is never edited and never deleted."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | FK → `projects.id`, indexed | `:104` |
| `version` | `Integer` | NOT NULL | `:105` |
| `summary` | `Text` | nullable | `:106` |
| `trigger` | `String(30)` | nullable | `:108` — `first_meeting`\|`new_meeting`\|`client_reply`\|`progress_review`\|`phase_shift`\|`manual` |
| `trigger_ref` | `String(32)` | nullable | `:109` |
| `changes_from_previous` | `Text` | nullable | `:111` — the AI-written human-readable diff |
| `status` | `String(20)` | `default="draft"`, NOT NULL | `:113` — `draft`\|`pending_review`\|`active`\|`superseded` |
| `approved_by` | `String(32)` | nullable | `:114` — user id **or `"system"`** |
| `approved_at` | `DateTime` | nullable | `:115` |
| `pending_ops` | `JSON` | `default=list` | `:118` — operations **held until activation**: `[{"op":"redate","task_id":"…","new_due":"…","old_due":"…"}]`. **7 distinct ops exist**, machine-checked by `check_docs_in_sync.py` |

### 3.4 `action_items` — 34 columns (the widest table in the system)
`ActionItem`, `app/models/action_item.py:20`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, assignee_id, status)` — the hot "my open tasks" query; `(org_id, lead_id)`;
`(org_id, project_id, status)`; `(org_id, due_date, status)` — `:22-28`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, nullable, indexed | `:30` |
| `meeting_id` | `String(32)` | FK → `meetings.id`, nullable, indexed | `:31` |
| `title` | `String(500)` | NOT NULL | `:32` |
| `description` | `Text` | nullable | `:33` |
| `assignee_id` | `String(32)` | FK → `users.id`, nullable, indexed | `:36-38`. **`owner_id` is a SQLAlchemy `synonym` for this column** (`:39`) — the same column under two Python names, kept for pre-project-layer code paths |
| `status` | `String(30)` | `default="open"`, NOT NULL | `:40-42` — `pending_review`\|`open`\|`in_progress`\|`done`\|`cancelled`\|`declined`\|`superseded` |
| `due_date` | `DateTime` | nullable | `:43` |
| `result_note` | `Text` | nullable | `:44` |
| `completed_at` | `DateTime` | nullable | `:45` |
| `created_by` | `String(32)` | nullable | `:46` — user id **or `"ai"`/`"system"`** |
| `project_id` | `String(32)` | nullable, indexed | `:49` — **no FK** |
| `plan_version_added` | `Integer` | nullable | `:50` |
| `phase` | `String(20)` | nullable | `:52` — `sales`\|`proposal`\|`preparation`\|`delivery`\|`payment`\|`closure` |
| `required_skill` | `String(100)` | nullable | `:54` — **matched against `user_skills.skill`** |
| `assigned_by` | `String(32)` | nullable | `:55` — user id or `"ai"` |
| `assignment_reason` | `Text` | nullable | `:57` — *"always shown to the assignee"* |
| `priority` | `String(5)` | `default="P2"` | `:58` — `P1`\|`P2`\|`P3` |
| `depends_on_ids` | `JSON` | `default=list` | `:60` — array of task ids; the assignee is not nudged while these are open |
| `assign_on` | `String(20)` | `default="plan_activation"` | `:62` — or `when_ready` |
| `blocked` | `Boolean` | `default=False` | `:63` |
| `blocked_reason` | `Text` | nullable | `:64` |
| `external_wait` | `JSON` | nullable | `:67` — `{"vendor_id","promised_date","chase_contact"}` |
| `progress_percent` | `Integer` | `default=0` | `:68` |
| `visible_to_client` | `Boolean` | `default=False` | `:70` — true ⇒ finishing it drafts a client update |
| `client_commitment_id` | `String(32)` | nullable | `:71` |
| `reminder_level` | `Integer` | `default=0` | `:73` — 0 none / 1 gentle / 2 firm / 3 escalated to the lead |
| `source` | `String(20)` | `default="manual"` | `:75` — `meeting`\|`client_reply`\|`ai_refinement`\|`playbook`\|`manual` |
| `completion_method` | `String(20)` | nullable | `:77` — `in_app`\|`manual_upload`\|`voice`\|`external`\|`system` |
| `superseded_by` | `String(32)` | nullable | `:78` |
| `parent_item_id` | `String(32)` | nullable | `:80` — filled on children when a task is split |

*"they die by being done, cancelled, or superseded — never by deletion"* (`:4-5`).

### 3.5 `client_commitments` — 14 columns
`ClientCommitment`, `app/models/project.py:121`. Mixins: **PK + TS + Org**.
Index: `ix_commitments_proj_status` on `(project_id, status)` — `:125`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | FK → `projects.id`, indexed | `:127` |
| `text` | `Text` | NOT NULL | `:128` |
| `direction` | `String(10)` | `default="ours"` | `:129` — `ours` (we promised them) \| `theirs` |
| `promised_to` | `String(32)` | nullable | `:130` — a stakeholder id |
| `promised_by` | `String(32)` | nullable | `:132` — **polymorphic: a user id when `ours`, a stakeholder id when `theirs`** |
| `due_date` | `DateTime` | nullable | `:133` |
| `linked_action_item_id` | `String(32)` | nullable | `:134` |
| `status` | `String(20)` | `default="open"`, NOT NULL | `:136` — `open`\|`kept`\|`broken`\|`renegotiated` |
| `source_type` | `String(30)` | nullable | `:138` — `meeting`\|`inbound_message`\|`outbound_message` |
| `source` | `String(32)` | nullable | `:139` |

### 3.6 `conflicts` — 16 columns
`Conflict`, `app/models/project.py:142`. Mixins: **PK + TS + Org**.
Index: `ix_conflicts_proj_status` on `(project_id, status)` — `:150`.
*"The AI never picks a side silently."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | FK → `projects.id`, indexed | `:152` |
| `description` | `Text` | NOT NULL | `:153` |
| `source_a_type` | `String(30)` | nullable | `:154` — `meeting`\|`inbound_message`\|`note` |
| `source_a` | `String(32)` | nullable | `:155` |
| `source_b_type` | `String(30)` | nullable | `:156` |
| `source_b` | `String(32)` | nullable | `:157` |
| `raised_to_user_id` | `String(32)` | nullable | `:158` |
| `status` | `String(20)` | `default="open"` | `:159` — `open`\|`resolved` |
| `resolution_note` | `Text` | nullable | `:160` |
| `resolved_by` | `String(32)` | nullable | `:161` |
| `resolved_at` | `DateTime` | nullable | `:162` |
| `held_plan_id` | `String(32)` | nullable | `:164` — the draft plan version this conflict is blocking |

### 3.7 `playbooks` — 10 columns
`Playbook`, `app/models/project.py:167`. Mixins: **PK + TS + Org**.
Index: `ix_playbooks_program_phase` on `(program_id, phase, version)` — `:172`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `program_id` | `String(32)` | FK → `programs.id`, indexed | `:175` |
| `phase` | `String(20)` | NOT NULL | `:177` — `preparation`\|`delivery`\|`payment`\|`closure` |
| `entries` | `JSON` | `default=list` | `:180` — task recipes: `[{"title","required_skill","offset_days","priority","visible_to_client"}]`. `offset_days` may be **negative** (before the anchor date) — see `seed_workflows.py:163-200` |
| `version` | `Integer` | `default=1` | `:181` |
| `is_current` | `Boolean` | `default=True` | `:182` |
| `updated_by` | `String(32)` | nullable | `:183` |

### 3.8 `playbook_suggestions` — 12 columns
`PlaybookSuggestion`, `app/models/project.py:186`. Mixins: **PK + TS + Org**.
A Knowledge-Engine proposal awaiting an admin's one tap.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `program_id` | `String(32)` | indexed | `:194` — **no FK** |
| `phase` | `String(20)` | NOT NULL | `:195` |
| `entry` | `JSON` | `default=dict` | `:197` — a **single** recipe, same shape as one `playbooks.entries` item |
| `reason` | `Text` | nullable | `:198` |
| `source_incident_id` | `String(32)` | nullable | `:199` |
| `status` | `String(20)` | `default="pending"` | `:200` — `pending`\|`accepted`\|`rejected` |
| `decided_by` | `String(32)` | nullable | `:201` |
| `decided_at` | `DateTime` | nullable | `:202` |

---

## 4 · Work Management & Sync

### 4.1 `assignments` — 13 columns
`Assignment`, `app/models/work.py:16`. Mixins: **PK + TS + Org**.
Index: `ix_assignments_org_item` on `(org_id, action_item_id)` — `:24`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `action_item_id` | `String(32)` | indexed, NOT NULL | `:26` — **no FK** |
| `from_user_id` | `String(32)` | nullable | `:27` |
| `to_user_id` | `String(32)` | nullable, indexed | `:28` |
| `assigned_by` | `String(32)` | nullable | `:29` — user id or `"ai"` |
| `reason` | `Text` | nullable | `:30` — *"always written, always shown"* |
| `status` | `String(20)` | `default="proposed"`, NOT NULL | `:32` — `proposed`\|`accepted`\|`auto_accepted`\|`declined`\|`overridden` |
| `decline_reason` | `String(30)` | nullable | `:33` — `busy`\|`wrong_skill`\|`on_site_elsewhere`\|`other` |
| `decline_note` | `Text` | nullable | `:34` |
| `decided_at` | `DateTime` | nullable | `:35` |

**Important:** in `lead_confirm` mode the lead's batch screen flips **these** rows, not
`approvals` rows (`:19-21`).

### 4.2 `reminders` — 13 columns
`Reminder`, `app/models/work.py:38`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, scheduled_at, sent_at, cancelled_at)`, `(target_type, target_id)` — `:46-49`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `target_type` | `String(30)` | NOT NULL | `:52` — `action_item`\|`followup`\|`approval`\|`client_commitment`\|`invoice` |
| `target_id` | `String(32)` | NOT NULL | `:53` |
| `remind_user_id` | `String(32)` | NOT NULL | `:54` |
| `level` | `Integer` | `default=1` | `:55` — 1 gentle / 2 firm / 3 lead |
| `channel` | `String(20)` | `default="push"` | `:56` — `push`\|`whatsapp`\|`email` |
| `scheduled_at` | `DateTime` | NOT NULL | `:57` |
| `sent_at` | `DateTime` | nullable | `:58` |
| `cancelled_at` | `DateTime` | nullable | `:59` — *"cancelled the instant the underlying thing completes"* |
| `note` | `Text` | nullable | `:60` |

### 4.3 `progress_events` — 9 columns
`ProgressEvent`, `app/models/work.py:63`. Mixins: **PK + Org** (**no `TimestampMixin`**).
Indexes: `(org_id, project_id, at)`, `(org_id, event_type, at)` — `:69-72`.
*"the heartbeat… The project timeline screen is this stream, humanised."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | nullable, indexed | `:74` |
| `event_type` | `String(50)` | NOT NULL | `:75` — **41 values** in `EventType` (`constants.py:332-375`), counted this session |
| `entity_type` | `String(50)` | nullable | `:76` |
| `entity_id` | `String(32)` | nullable | `:77` |
| `actor` | `String(32)` | nullable | `:78` — user id / `"ai"` / `"system"` |
| `at` | `DateTime` | `default=utcnow`, NOT NULL | `:79` |
| `details` | `JSON` | `default=dict` | `:80` |

### 4.4 `incidents` — 14 columns
`Incident`, `app/models/work.py:83`. Mixins: **PK + TS + Org**.
Index: `ix_incidents_org_proj_status` on `(org_id, project_id, status)` — `:88`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | indexed, NOT NULL | `:90` — no FK |
| `source_type` | `String(30)` | nullable | `:92` — `inbound_message`\|`progress_event` |
| `source` | `String(32)` | nullable | `:93` |
| `severity` | `String(10)` | `default="medium"` | `:94` — `low`\|`medium`\|`high` |
| `description` | `Text` | NOT NULL | `:95` |
| `owner_user_id` | `String(32)` | nullable | `:96` |
| `fix_task_ids` | `JSON` | `default=list` | `:97` |
| `status` | `String(20)` | `default="open"` | `:98` — `open`\|`fixing`\|`resolved` |
| `resolved_at` | `DateTime` | nullable | `:99` |
| `lesson` | `Text` | nullable | `:101` — the takeaway at closure; **becomes a `playbook_suggestion`** |

### 4.5 `ai_decisions` — 15 columns
`AIDecision`, `app/models/work.py:104`. Mixins: **PK + TS + Org**.
Index: `ix_ai_decisions_org_proj` on `(org_id, project_id)` — `:111`.
*"'Why did the AI do that?' always has an answer here."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | nullable, indexed | `:113` |
| `decision_type` | `String(30)` | NOT NULL | `:116` — `assignment`\|`plan_update`\|`draft_message`\|`state_change`\|`conflict_raised`\|`escalation`\|`feasibility` |
| `engine` | `String(40)` | nullable | `:117` |
| `input_summary` | `Text` | nullable | `:118` |
| `decision` | `Text` | nullable | `:119` |
| `reason` | `Text` | nullable | `:120` |
| `confidence` | `Float` | `default=1.0` | `:121` — compared against `org_settings.ai_confidence_threshold` |
| `needs_human` | `Boolean` | `default=False` | `:122` |
| `human_override` | `Text` | nullable | `:123` |
| `entity_type` | `String(50)` | nullable | `:124` |
| `entity_id` | `String(32)` | nullable | `:125` |

### 4.6 `digests` — 10 columns
`Digest`, `app/models/work.py:128`. Mixins: **PK + TS + Org**.
Index: `ix_digests_org_kind` on `(org_id, kind, generated_at)` — `:132`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `kind` | `String(40)` | NOT NULL | `:135` — `daily_user`\|`weekly_project_internal`\|`weekly_project_client` |
| `for_user_id` | `String(32)` | nullable, indexed | `:136` |
| `project_id` | `String(32)` | nullable, indexed | `:137` |
| `content_md` | `Text` | NOT NULL | `:138` |
| `generated_at` | `DateTime` | `default=utcnow`, NOT NULL | `:139` |
| `sent_message_id` | `String(32)` | nullable | `:141` — for the client kind only, after approval |

---

## 5 · Products, Documents & Money

### 5.1 `programs` — 8 columns
`Program`, `app/models/program.py:18`. Mixins: **PK + TS + Org**.
Index: `ix_programs_org_code` on `(org_id, code)` **UNIQUE** — `:22`.
*"A product an organisation sells."* The manual calls these **"what you sell — one entry per offering"**.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `String(200)` | NOT NULL | `:24` |
| `code` | `String(50)` | NOT NULL, unique per org | `:25` — **upper-cased on write** (`admin.py:207`) |
| `description` | `Text` | nullable | `:26` — **load-bearing**: this is what the AI reads to decide which offering a conversation was about (manual p.6) |
| `is_active` | `Boolean` | `default=True` | `:27` |

### 5.2 `pricing_tables` — 11 columns
`PricingTable`, `app/models/program.py:30`. Mixins: **PK + TS + Org**.
Index: `ix_pricing_org_program` on `(org_id, program_id, version)` — `:34` (**not unique**).
*"Numbers NEVER come from the AI."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `program_id` | `String(32)` | FK → `programs.id`, indexed | `:36` |
| `version` | `Integer` | NOT NULL, `default=1` | `:37` |
| `currency` | `String(10)` | `default="INR"` | `:38` |
| `items` | `JSON` | NOT NULL, `default=list` | `:41` — `[{"code","label","unit","unit_price","default_quantity","notes"}]` |
| `effective_from` | `DateTime` | `default=utcnow` | `:42` |
| `is_current` | `Boolean` | `default=True` | `:43` |
| `created_by` | `String(32)` | nullable | `:44` |

**`items[].default_quantity` carries a documented tri-state** (`admin.py:240-249`):
`None` means *"this org did not say how many"* — **not** "one of them". The value
estimate scales an unanswered line by the count discussed in the meeting, and a stated
one by itself. Proposals still start such a line at 1.

### 5.3 `proposal_templates` — 10 columns
`ProposalTemplate`, `app/models/program.py:47`. Mixins: **PK + TS + Org**.
Index: `ix_ptemplates_org_program` on `(org_id, program_id)` — `:51`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `program_id` | `String(32)` | FK → `programs.id`, indexed | `:53` |
| `name` | `String(200)` | NOT NULL | `:54` |
| `version` | `Integer` | NOT NULL, `default=1` | `:55` |
| `body_md` | `Text` | NOT NULL | `:59` — Markdown with `{variables}` |
| `is_current` | `Boolean` | `default=True` | `:60` |
| `created_by` | `String(32)` | nullable | `:61` |

**Template variables** (`:56-58`): `{client_name}` (alias `{school_name}`),
`{contact_name}`, `{sender_name}`, `{org_name}`, `{program_name}`, `{pricing_table}`,
`{total_amount}`, `{context_summary}`. Live templates also use `{program_description}`
and `{sender_email}` (`seed_workflows.py:96-118`).
**INFERRED:** the variable list in the docstring is not exhaustive and no validator
enforces it — an unknown `{placeholder}` is presumably left as literal text. *Not verified.*

### 5.4 `message_templates` — 12 columns
`MessageTemplate`, `app/models/program.py:64`. Mixins: **PK + TS + Org**.
Index: `ix_mtemplates_org_kind` on `(org_id, kind, channel)` — `:68`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `kind` | `String(30)` | NOT NULL | `:70` — `intro`\|`follow_up` |
| `channel` | `String(20)` | NOT NULL | `:71` — `email`\|`whatsapp` |
| `name` | `String(200)` | NOT NULL | `:72` |
| `version` | `Integer` | NOT NULL, `default=1` | `:73` |
| `subject` | `String(300)` | nullable | `:74` — **required for email** (`admin.py:432-433`) |
| `body` | `Text` | NOT NULL | `:75` |
| `is_current` | `Boolean` | `default=True` | `:76` |
| `created_by` | `String(32)` | nullable | `:77` |

**Not scoped to a program** — these are org-wide, unlike proposal templates.

### 5.5 `proposals` — 25 columns
`Proposal`, `app/models/proposal.py:15`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, lead_id)`, `(org_id, status)` — `:18-19`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:22` |
| `program_id` | `String(32)` | FK → `programs.id`, indexed | `:23` |
| `title` | `String(300)` | NOT NULL | `:24` |
| `status` | `String(30)` | `default="draft"`, NOT NULL | `:25` — `draft`\|`internal_review`\|`approved_internally`\|`pending_approval` (legacy alias)\|`sent`\|`accepted`\|`declined` |
| `template_id` | `String(32)` | FK → `proposal_templates.id` | `:30` |
| `template_version` | `Integer` | NOT NULL | `:31` |
| `pricing_table_id` | `String(32)` | FK → `pricing_tables.id` | `:32` |
| `pricing_version` | `Integer` | NOT NULL | `:33` |
| `content_md` | `Text` | NOT NULL | `:37` |
| `variables` | `JSON` | `default=dict` | `:40` — kept so the commercial block can be regenerated after edits |
| `line_items` | `JSON` | `default=list` | `:41` — `[{"code","label","unit","unit_price","quantity","line_total"}]` |
| `total_amount` | `Float` | `default=0.0` | `:42` |
| `currency` | `String(10)` | `default="INR"` | `:43` |
| `docx_path` | `String(500)` | nullable | `:45` |
| `pdf_path` | `String(500)` | nullable | `:46` |
| `created_by` | `String(32)` | FK → `users.id` | `:48` |
| `sent_at` | `DateTime` | nullable | `:49` |
| `sent_message_id` | `String(32)` | nullable | `:50` |
| `project_id` | `String(32)` | nullable, indexed | `:53` |
| `amends_proposal_id` | `String(32)` | nullable | `:55` — the accepted proposal this amendment modifies |
| `special_price_approval_id` | `String(32)` | nullable | `:58` — *"no number ever exists without a recorded human yes"* |

**The version-locking rule** (`:29`, and `program.py:2-4`): a proposal copies the exact
template and pricing **version** it used, so editing a rate card never alters a proposal
already sent. This is the single most important integrity rule for the dashboard's
pricing screens.

### 5.6 `proposal_revisions` — 10 columns
`ProposalRevision`, `app/models/proposal.py:61`. Mixins: **PK + Org** (**no `TimestampMixin`**).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `proposal_id` | `String(32)` | FK → `proposals.id`, indexed | `:66` |
| `revision_no` | `Integer` | NOT NULL | `:67` |
| `instruction` | `Text` | nullable | `:68` — **the human command that caused the edit** |
| `content_md` | `Text` | NOT NULL | `:69` |
| `line_items` | `JSON` | `default=list` | `:70` |
| `total_amount` | `Float` | `default=0.0` | `:71` |
| `edited_by` | `String(32)` | nullable | `:72` |
| `edited_at` | `DateTime` | `default=utcnow`, NOT NULL | `:73` |

### 5.7 `deliverables` — 14 columns
`Deliverable`, `app/models/finance.py:14`. Mixins: **PK + TS + Org**.
Index: `ix_deliverables_proj_type` on `(project_id, type, version)` — `:22`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | indexed, NOT NULL | `:24` — no FK |
| `type` | `String(30)` | NOT NULL | `:27` — 10 values incl. `proposal`, `syllabus`, `schedule`, `invoice`, `daily_report`, `closure_report`, `certificates`, `feedback_summary`, `photo_set`, `other` |
| `title` | `String(300)` | nullable | `:28` |
| `file_path` | `String(500)` | nullable | `:29` |
| `content_md` | `Text` | nullable | `:30` |
| `version` | `Integer` | `default=1` | `:31` |
| `source` | `String(20)` | `default="ai_generated"` | `:32` — or `manual_upload`. *"Two equal births… the rest of the machine treats both identically"* |
| `uploaded_by` | `String(32)` | nullable | `:33` |
| `status` | `String(20)` | `default="draft"` | `:35` — `draft`\|`internal_review`\|`approved`\|`sent`\|`accepted` |
| `linked_action_item_id` | `String(32)` | nullable | `:36` |

### 5.8 `invoices` — 16 columns
`Invoice`, `app/models/finance.py:39`. Mixins: **PK + TS + Org**.
Index: `ix_invoices_org_status` on `(org_id, status, due_date)` — `:43`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | indexed, NOT NULL | `:45` |
| `kind` | `String(10)` | `default="full"` | `:46` — `advance`\|`balance`\|`full` |
| `amount` | `Float` | NOT NULL | `:47` — *"amounts always derived"*, never typed |
| `currency` | `String(10)` | `default="INR"` | `:48` |
| `computation` | `Text` | nullable | `:50` — the arithmetic, kept: e.g. `"110000 + 45000 - 55000 = 100000"` |
| `due_date` | `DateTime` | nullable | `:51` |
| `status` | `String(20)` | `default="draft"`, NOT NULL | `:53` — `draft`\|`sent`\|`part_paid`\|`paid`\|`overdue`\|`disputed` |
| `sent_to_stakeholder_id` | `String(32)` | nullable | `:54` |
| `pdf_path` | `String(500)` | nullable | `:55` |
| `sent_message_id` | `String(32)` | nullable | `:56` |
| `sent_at` | `DateTime` | nullable | `:57` |
| `ladder_fired` | `JSON` | `default=list` | `:59` — which `payment_reminder_schedule` offsets have already fired |

### 5.9 `payments` — 10 columns
`Payment`, `app/models/finance.py:62`. Mixins: **PK + TS + Org**. No extra index.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `invoice_id` | `String(32)` | indexed, NOT NULL | `:67` — no FK |
| `amount` | `Float` | NOT NULL | `:68` |
| `received_on` | `DateTime` | nullable | `:69` |
| `method` | `String(20)` | nullable | `:70` — `cheque`\|`transfer`\|`upi`\|`cash` |
| `recorded_by` | `String(32)` | nullable | `:71` |
| `note` | `Text` | nullable | `:72` |

### 5.10 `vendors` — 10 columns
`Vendor`, `app/models/finance.py:75`. Mixins: **PK + TS + Org**. No extra index.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `String(200)` | NOT NULL | `:80` |
| `contact_name` | `String(200)` | nullable | `:81` |
| `phone` | `String(30)` | nullable | `:82` |
| `email` | `String(320)` | nullable | `:83` |
| `category` | `String(100)` | nullable | `:84` |
| `notes` | `Text` | nullable | `:85` |

---

## 6 · Meetings & Scheduling

### 6.1 `meetings` — 22 columns
`Meeting`, `app/models/meeting.py:14`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, lead_id)`, `(org_id, agent_id)`, `(org_id, created_at)` — the last one
exists because retention sweeps scan by month (`:16-22`).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:24` |
| `agent_id` | `String(32)` | FK → `users.id`, indexed | `:25` |
| `title` | `String(300)` | nullable | `:26` |
| `status` | `String(30)` | `default="uploaded"`, NOT NULL | `:27-29` — `scheduled`\|`uploaded`\|`transcribing`\|`transcribed`\|`extracting`\|`review_pending`\|`completed`\|`failed` |
| `audio_path` | `String(500)` | nullable | `:30` |
| `audio_mime` | `String(100)` | nullable | `:31` |
| `audio_deleted_at` | `DateTime` | nullable | `:32` — retention |
| `duration_seconds` | `Integer` | nullable | `:33` |
| `started_at` | `DateTime` | `default=utcnow`, nullable | `:34` |
| `consent_captured` | `Boolean` | `default=False` | `:35` |
| `error` | `Text` | nullable | `:36` |
| `state_suggestion` | `String(50)` | nullable | `:38` |
| `project_id` | `String(32)` | nullable, indexed | `:42` — empty for a first meeting |
| `meeting_no` | `Integer` | nullable | `:43` |
| `meeting_type` | `String(20)` | nullable | `:45` — `first_visit`\|`negotiation`\|`kickoff`\|`review`\|`closure` |
| `attendee_stakeholder_ids` | `JSON` | `default=list` | `:47` — lets conflict resolution weigh voices |
| `attendee_user_ids` | `JSON` | `default=list` | `:48` |
| `notes_text` | `Text` | nullable | `:50` — typed/dictated notes used **instead of** audio |

### 6.2 `transcripts` — 12 columns
`Transcript`, `app/models/meeting.py:53`. Mixins: **PK + TS + Org**.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `meeting_id` | `String(32)` | FK → `meetings.id`, **UNIQUE**, indexed | `:56-58` — strictly one per meeting |
| `text` | `Text` | NOT NULL | `:59` |
| `summary` | `Text` | nullable | `:60` |
| `language` | `String(30)` | nullable | `:61` |
| `confidence` | `Float` | nullable | `:62` |
| `low_confidence` | `Boolean` | `default=False` | `:63` |
| `word_count` | `Integer` | nullable | `:64` |
| `archived_at` | `DateTime` | nullable | `:65` — retention |

### 6.3 `demo_teams` — 8 columns
`DemoTeam`, `app/models/demo.py:14`. Mixins: **PK + TS + Org**.
Index: `ix_demo_teams_org_name` on `(org_id, name)` **UNIQUE** — `:18`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `String(200)` | NOT NULL, unique per org | `:20` |
| `lead_user_id` | `String(32)` | FK → `users.id`, nullable | `:21` |
| `media_rep_id` | `String(32)` | FK → `users.id`, nullable | `:22` |
| `sales_rep_id` | `String(32)` | FK → `users.id`, nullable | `:23` |

### 6.4 `demo_team_members` — 5 columns (the narrowest table)
`DemoTeamMember`, `app/models/demo.py:26`. Mixins: **PK + Org** (**no `TimestampMixin`**).
Index: `ix_dtm_team_user` on `(team_id, user_id)` **UNIQUE** — `:28`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `team_id` | `String(32)` | FK → `demo_teams.id`, indexed | `:30` |
| `user_id` | `String(32)` | FK → `users.id`, indexed | `:31` |
| `role_in_team` | `String(50)` | `default="member"` | `:32` |

### 6.5 `demos` — 15 columns
`Demo`, `app/models/demo.py:35`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, scheduled_date)`, `(org_id, team_id, scheduled_date)` — `:37-40`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:42` |
| `team_id` | `String(32)` | FK → `demo_teams.id`, nullable, indexed | `:43` |
| `scheduled_date` | **`Date`** | NOT NULL | `:44` — a `Date`, not a `DateTime` |
| `scheduled_time` | `String(10)` | nullable | `:45` — **a string**, e.g. `"10:30"`; time is not a typed column |
| `status` | `String(30)` | `default="scheduled"` | `:46` — `scheduled`\|`completed`\|`cancelled` |
| `notes` | `Text` | nullable | `:47` |
| `calendar_event_id` | `String(200)` | nullable | `:48` |
| `created_by` | `String(32)` | nullable | `:49` |
| `completed_at` | `DateTime` | nullable | `:50` |
| `project_id` | `String(32)` | nullable, indexed | `:54` — empty for early sales demos on a bare lead |
| `action_item_id` | `String(32)` | nullable | `:56` — the plan task that scheduled it |

### 6.6 `resource_bookings` — 13 columns
`ResourceBooking`, `app/models/resource.py:13`. Mixins: **PK + TS + Org**.
Index: `ix_bookings_org_user_window` on `(org_id, user_id, date_from, date_to)` — `:22`.
*"The single source of truth for 'who and what is busy when'… why nobody is ever booked in two cities in the same week."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `user_id` | `String(32)` | indexed, NOT NULL | `:25` |
| `project_id` | `String(32)` | nullable, indexed | `:26` |
| `kind` | `String(20)` | NOT NULL | `:28` — `delivery`\|`demo`\|`travel`\|`leave`\|`hold` |
| `date_from` | `DateTime` | NOT NULL | `:29` |
| `date_to` | `DateTime` | NOT NULL | `:30` |
| `source_type` | `String(30)` | nullable | `:32` — `action_item`\|`demo`\|`leave`\|`hold` |
| `source` | `String(32)` | nullable | `:33` |
| `calendar_event_id` | `String(300)` | nullable | `:34` |
| `note` | `Text` | nullable | `:35` |

### 6.7 `followups` — 14 columns
`FollowUp`, `app/models/followup.py:14`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, due_date, status)`, `(org_id, lead_id)` — `:16-19`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | FK → `leads.id`, indexed | `:21` |
| `owner_id` | `String(32)` | FK → `users.id`, nullable, indexed | `:22` |
| `due_date` | **`Date`** | NOT NULL | `:23` — a `Date`, not a `DateTime` |
| `channel` | `String(20)` | `default="email"` | `:24` — `email`\|`whatsapp`\|`call` |
| `status` | `String(20)` | `default="pending"` | `:25` — `pending`\|`done`\|`skipped` |
| `note` | `Text` | nullable | `:26` |
| `message_id` | `String(32)` | nullable | `:27` |
| `completed_at` | `DateTime` | nullable | `:28` |
| `created_by` | `String(32)` | nullable | `:29` |
| `reminded` | `Boolean` | `default=False` | `:30` — declared without an explicit type; SQLAlchemy infers `Boolean` from the annotation |

---

## 7 · Communication & Approvals

### 7.1 `threads` — 14 columns
`Thread`, `app/models/comms.py:14`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, lead_id)`, `(org_id, project_id)`, `(contact_id, channel)` — `:20-24`.
*"One conversation: one person + one channel."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `lead_id` | `String(32)` | indexed, NOT NULL | `:26` — no FK |
| `project_id` | `String(32)` | nullable, indexed | `:27` — null before any project exists |
| `contact_id` | `String(32)` | indexed, NOT NULL | `:28` |
| `stakeholder_id` | `String(32)` | nullable | `:29` |
| `channel` | `String(20)` | NOT NULL | `:30` — `email`\|`whatsapp` |
| `subject` | `String(500)` | nullable | `:31` |
| `last_message_at` | `DateTime` | nullable | `:32` |
| `last_direction` | `String(10)` | nullable | `:34` — `inbound` = the client wrote last (**ball in our court**); `outbound` = we wait |
| `status` | `String(20)` | `default="open"` | `:35` — `open`\|`settled`\|`dormant` |
| `owner_user_id` | `String(32)` | nullable | `:37` — resolves the `thread_owner` approver role |

### 7.2 `outbound_messages` — 30 columns
`OutboundMessage`, `app/models/messaging.py:19`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, status)`, `(org_id, created_at)`, and **`(org_id, idempotency_key)` UNIQUE** — `:21-25`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `kind` | `String(30)` | NOT NULL | `:27` — 8 values in `MessageKind`: `intro`, `proposal`, `follow_up`, `progress_update`, `reply`, `report`, `invoice`, `notification` |
| `channel` | `String(20)` | NOT NULL | `:28` — `email`\|`whatsapp` |
| `status` | `String(30)` | `default="pending_approval"`, NOT NULL | `:29-31` — `draft`\|`pending_approval`\|`queued`\|`sending`\|`sent`\|`delivered`\|`failed`\|`dead_letter`\|`rejected`. **The default is the human gate** |
| `lead_id` | `String(32)` | FK → `leads.id`, nullable, indexed | `:33` |
| `contact_id` | `String(32)` | nullable | `:34` |
| `proposal_id` | `String(32)` | nullable | `:35` |
| `followup_id` | `String(32)` | nullable | `:36` |
| `sender_user_id` | `String(32)` | FK → `users.id` | `:37` |
| `to_address` | `String(320)` | NOT NULL | `:39` — **email address or phone number**, depending on channel |
| `cc` | `JSON` | `default=list` | `:40` |
| `subject` | `String(500)` | nullable | `:41` |
| `body` | `Text` | NOT NULL | `:42` |
| `attachments` | `JSON` | `default=list` | `:43` — `[{"path","filename"}]` |
| `idempotency_key` | `String(100)` | NOT NULL, unique per org | `:46` — so retries never double-send |
| `attempts` | `Integer` | `default=0` | `:47` |
| `last_error` | `Text` | nullable | `:48` |
| `approved_by` | `String(32)` | nullable | `:49` |
| `approved_at` | `DateTime` | nullable | `:50` |
| `queued_at` | `DateTime` | nullable | `:51` |
| `sent_at` | `DateTime` | nullable | `:52` |
| `provider_message_id` | `String(300)` | nullable, indexed | `:53` — **the only key the WhatsApp webhook matches on** |
| `project_id` | `String(32)` | nullable, indexed | `:56` |
| `thread_id` | `String(32)` | nullable, indexed | `:57` |
| `triggered_by` | `String(30)` | nullable | `:60` — `task_completed`\|`plan_updated`\|`weekly_report`\|`inbound_reply`\|`reminder_ladder`\|`manual` |
| `approval_id` | `String(32)` | nullable | `:62` |
| `scheduled_send_at` | `DateTime` | nullable | `:64` — late-night drafts wait for the morning window |

### 7.3 `message_delivery_log` — 6 columns
`MessageDeliveryLog`, `app/models/messaging.py:67`. Mixins: **PK + Org** (**no `TimestampMixin`**).
Index: `ix_mdl_org_message` on `(org_id, message_id)` — `:71`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `message_id` | `String(32)` | FK → `outbound_messages.id`, indexed | `:73-75` |
| `event` | `String(50)` | NOT NULL | `:76` — queued/sent/delivered/failed/bounced/`provider_*` |
| `detail` | `Text` | nullable | `:77` |
| `at` | `DateTime` | `default=utcnow`, NOT NULL | `:78` |

This is what the app's **"Delivery trace"** screen renders — *"Not what we think we sent."*

### 7.4 `inbound_messages` — 23 columns
`InboundMessage`, `app/models/comms.py:40`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, status)`, `(org_id, thread_id)` — `:47-50`.
*"Nothing is ever dropped: a message that matches nothing goes to triage."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `channel` | `String(20)` | NOT NULL | `:52` |
| `from_address` | `String(320)` | nullable | `:53` |
| `to_address` | `String(320)` | nullable | `:54` |
| `subject` | `String(500)` | nullable | `:55` |
| `body` | `Text` | NOT NULL | `:56` |
| `received_at` | `DateTime` | nullable | `:57` |
| `matched_contact_id` | `String(32)` | nullable | `:58` |
| `matched_lead_id` | `String(32)` | nullable, indexed | `:59` |
| `matched_project_id` | `String(32)` | nullable, indexed | `:60` |
| `related_project_ids` | `JSON` | `default=list` | `:62` — one message spanning several projects |
| `thread_id` | `String(32)` | nullable, indexed | `:63` |
| `intent` | `String(30)` | nullable | `:66` — 9 values: `question`, `change_request`, `approval`, `rejection`, `complaint`, `payment_info`, `scheduling`, `acknowledgement`, `unknown` |
| `change_type` | `String(20)` | nullable | `:68` — `price`\|`content`\|`date`\|`scope`\|`other` |
| `sentiment` | `String(10)` | nullable | `:69` — `positive`\|`neutral`\|`negative` |
| `ai_summary` | `Text` | nullable | `:70` |
| `extracted_points` | `JSON` | `default=list` | `:72` — the checklist the coverage check ticks off |
| `status` | `String(20)` | `default="new"`, NOT NULL | `:74` — `new`\|`processed`\|`needs_human`\|`triage` |
| `linked_plan_version` | `Integer` | nullable | `:75` |
| `needs_human_reason` | `Text` | nullable | `:76` |

### 7.5 `approval_rules` — 15 columns
`ApprovalRule`, `app/models/comms.py:79`. Mixins: **PK + TS + Org**.
Index: `ix_approval_rules_org_entity` on `(org_id, entity_type)` — `:86`.
*"Rules are data — changing who approves what never needs a code change."*

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `entity_type` | `String(30)` | NOT NULL | `:89` — `outbound_message`\|`proposal`\|`price_change`\|`plan_change`\|`invoice` |
| `condition` | `JSON` | `default=dict` | `:93` — e.g. `{"discount_pct_gt":10}`, `{"amount_gt":100000}`, `{"date_shift_days_gt":2}`, `{"kind":"progress_update"}` |
| `rank` | `Integer` | `default=100` | `:94` — **lower = checked first; the first matching rule decides** |
| `approver_role` | `String(30)` | NOT NULL | `:96` — an org role, **or the special values `"thread_owner"` / `"sender"`** (`constants.py:537-538`) |
| `fallback_role` | `String(30)` | nullable | `:97` |
| `recommender_role` | `String(30)` | nullable | `:99` — chained: this role reviews first and attaches a recommendation |
| `joint_with_role` | `String(30)` | nullable | `:101` — a second approver when both sides must say yes |
| `joint_condition` | `JSON` | nullable | `:104` — the joint approver is only required when this also matches |
| `auto_approve` | `Boolean` | `default=False` | `:105` |
| `expires_hours` | `Float` | `default=48.0` | `:106` — a **float**, so sub-hour windows work (the seeded urgent rules use `0.5`) |
| `description` | `String(300)` | nullable | `:107` |

### 7.6 `approvals` — 25 columns
`Approval`, `app/models/comms.py:110`. Mixins: **PK + TS + Org**.
Indexes: `(org_id, status)`, `(requested_from_user_id, status)` — `:114-117`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `project_id` | `String(32)` | nullable, indexed | `:119` |
| `entity_type` | `String(30)` | NOT NULL | `:120` |
| `entity_id` | `String(32)` | nullable, indexed | `:121` |
| `requested_from_user_id` | `String(32)` | nullable | `:122` |
| `requested_from_role` | `String(30)` | nullable | `:123` |
| `stage` | `String(15)` | `default="decide"` | `:125` — `recommend`\|`decide` |
| `chain_parent_id` | `String(32)` | nullable | `:126` |
| `recommendation` | `Text` | nullable | `:128` — attached by the recommend stage, travels with the approval |
| `joint_with_user_id` | `String(32)` | nullable | `:129` |
| `joint_status` | `String(15)` | nullable | `:130` — `pending`\|`approved`\|`rejected` |
| `joint_decision_note` | `Text` | nullable | `:131` |
| `joint_decided_at` | `DateTime` | nullable | `:132` |
| `bundled_entities` | `JSON` | `default=list` | `:135` — records released by this same yes, succeeding or failing together |
| `reason` | `Text` | nullable | `:136` |
| `status` | `String(20)` | `default="pending"`, NOT NULL | `:138` — `pending`\|`approved`\|`rejected`\|`expired`\|`escalated` |
| `decision_note` | `Text` | nullable | `:139` — on rejection this **becomes the redraft instruction** |
| `requested_at` | `DateTime` | nullable | `:140` |
| `decided_at` | `DateTime` | nullable | `:141` |
| `expires_at` | `DateTime` | nullable | `:142` |
| `escalated_to_user_id` | `String(32)` | nullable | `:143` |
| `reminded_at` | `DateTime` | nullable | `:144` |

---

## 8 · Relationship map

Computed from `Base.metadata` this session:

- **47 of 55 tables declare at least one `ForeignKey`** — but for 20 of those the *only*
  FK is `org_id`, contributed by `OrgScopedMixin`.
- **Only 27 tables declare a `ForeignKey` other than `org_id`.** The remaining 28 use
  bare `String(32)` columns as soft references.

The 27: `action_items`, `action_plans`, `assistant_turns`, `client_commitments`,
`client_intelligence`, `conflicts`, `consent_records`, `contacts`, `demo_team_members`,
`demo_teams`, `demos`, `followups`, `lead_state_history`, `leads`, `meetings`,
`memory_chunks`, `message_delivery_log`, `outbound_messages`, `playbooks`,
`pricing_tables`, `project_members`, `projects`, `proposal_revisions`,
`proposal_templates`, `proposals`, `stakeholders`, `transcripts`.

Soft references are a deliberate, consistent pattern for polymorphic and cross-aggregate
pointers — but it means **the database will not stop you deleting a parent row**, which
is critical for any dashboard delete feature (see `04_OPEN_QUESTIONS.md` Q5). Note in
particular that `action_items.project_id`, `deliverables.project_id`,
`invoices.project_id`, `incidents.project_id`, `payments.invoice_id` and
`projects.parent_project_id` are **all soft**.

```
organisations ─┬─< org_settings (1:1, UNIQUE org_id)
               └─< (org_id on all 50 org-scoped tables, FK via OrgScopedMixin)

users ─┬─< user_skills (user_id, no FK)          leads ─┬─< contacts (FK)
       ├─< device_tokens (no FK)                        ├─< lead_state_history (FK)
       ├─< notifications (no FK)                        ├─< consent_records (FK)
       ├─< assistant_turns (FK)                         ├─< client_intelligence (FK)
       ├── leads.owner_id (FK)                          ├─< memory_chunks (FK)
       ├── action_items.assignee_id (FK)                ├─< meetings (FK)
       ├── proposals.created_by (FK)                    ├─< proposals (FK)
       ├── outbound_messages.sender_user_id (FK)        ├─< followups (FK)
       ├── projects.sales_owner_id / ops_owner_id (FK)  ├─< demos (FK)
       ├── project_members.user_id (FK)                 ├─< outbound_messages (FK)
       ├── demo_teams.lead/media_rep/sales_rep (FK)     ├─< projects (FK)
       └── demo_team_members.user_id (FK)               └─< threads (no FK)

programs ─┬─< pricing_tables (FK) ──┐
          ├─< proposal_templates (FK)│  proposals lock (template_id, template_version,
          ├─< playbooks (FK)         │                  pricing_table_id, pricing_version)
          └── projects.program_id (FK)┘

projects ─┬─< project_members (FK)        contacts ──< stakeholders (FK)
          ├─< stakeholders (FK)
          ├─< action_plans (FK, UNIQUE version)
          ├─< client_commitments (FK)
          ├─< conflicts (FK) ── held_plan_id ──> action_plans (no FK)
          ├─< action_items.project_id (NO FK)
          ├─< deliverables / invoices / incidents / digests (NO FK)
          ├─< resource_bookings (NO FK)
          └── parent_project_id ──> projects (NO FK, self-ref for chain deals)

meetings ──< transcripts (FK, UNIQUE meeting_id)
meetings ──< action_items.meeting_id (FK)
invoices ──< payments (invoice_id, NO FK)
outbound_messages ──< message_delivery_log (FK)
demo_teams ──< demo_team_members (FK) ; demos.team_id (FK)
```

### 8.1 Polymorphic pointer pairs (never FK-enforceable)

| Table | Discriminator | Id | Line |
|---|---|---|---|
| `notifications` | `entity_type` | `entity_id` | `user.py:99-100` |
| `audit_log` | `entity_type` | `entity_id` | `audit.py:23-24` |
| `progress_events` | `entity_type` | `entity_id` | `work.py:76-77` |
| `ai_decisions` | `entity_type` | `entity_id` | `work.py:124-125` |
| `approvals` | `entity_type` | `entity_id` | `comms.py:120-121` |
| `reminders` | `target_type` | `target_id` | `work.py:52-53` |
| `client_commitments` | `source_type` | `source` | `project.py:138-139` |
| `conflicts` | `source_a_type`/`source_b_type` | `source_a`/`source_b` | `project.py:154-157` |
| `incidents` | `source_type` | `source` | `work.py:92-93` |
| `resource_bookings` | `source_type` | `source` | `resource.py:32-33` |
| `memory_chunks` | `source_type` | `source_id` | `memory.py:21-22` |

### 8.2 String columns that carry non-user sentinels

Several `String(32)` "who did it" columns legitimately hold a **literal word** instead of
a user id. A dashboard that renders these as user lookups will show blanks.

| Column | Sentinels | Line |
|---|---|---|
| `lead_state_history.changed_by` | `"system"` | `lead.py:56` |
| `action_items.created_by` | `"ai"`, `"system"` | `action_item.py:46` |
| `action_items.assigned_by` | `"ai"` | `action_item.py:55` |
| `assignments.assigned_by` | `"ai"` | `work.py:29` |
| `project_members.added_by` | `"ai"` | `project.py:64` |
| `action_plans.approved_by` | `"system"` | `project.py:114` |
| `progress_events.actor` | `"ai"`, `"system"` | `work.py:78` |

---

## 9 · Constraint summary for the dashboard

### 9.1 Every UNIQUE constraint in the schema (11)

| Table | Unique on | Line |
|---|---|---|
| `organisations` | `slug` | `organisation.py:19` |
| `org_settings` | `org_id` | `organisation.py:35` |
| `users` | `email` | `user.py:24` |
| `user_skills` | `(user_id, skill)` | `user.py:64` |
| `device_tokens` | `fcm_token` | `user.py:82` |
| `idempotency_records` | `(org_id, key)` | `audit.py:33` |
| `programs` | `(org_id, code)` | `program.py:22` |
| `action_plans` | `(project_id, version)` | `project.py:101` |
| `transcripts` | `meeting_id` | `meeting.py:57` |
| `demo_teams` | `(org_id, name)` | `demo.py:18` |
| `demo_team_members` | `(team_id, user_id)` | `demo.py:28` |
| `outbound_messages` | `(org_id, idempotency_key)` | `messaging.py:24` |

*(12 rows — `organisations.slug` and `org_settings.org_id` are column-level `unique=True`;
the rest are `Index(..., unique=True)`.)*

### 9.2 What the database does **not** enforce

- **No CHECK constraints anywhere.** Every status, role, phase, priority and enum-like
  value is a plain `String`. `app/core/constants.py` defines 40+ Python enums, but none
  reaches the DDL. Validation lives entirely in the Pydantic request models and the
  engines.
- **No cascade rules.** No `ondelete=` appears on any `ForeignKey` in the schema.
- **No `NOT NULL` on most business fields** — `Mapped[X]` without `nullable=False` is
  non-nullable in SQLAlchemy 2.0 typing, but many optional-looking fields are genuinely
  nullable by `| None`.
- **Foreign keys are not enforced at runtime on SQLite** unless
  `PRAGMA foreign_keys=ON` is issued. `app/database.py:43-51` sets only
  `journal_mode=WAL` and `busy_timeout`, so **FK enforcement is OFF by default** in the
  dev database. (`reset_for_datacentre_demo.py:120` explicitly issues
  `PRAGMA foreign_keys=OFF` for its own wipe.)

### 9.3 Versioned-and-superseded families

Four families follow the same "new row, flip `is_current`/status" pattern. A dashboard
edit screen for any of them must **create**, never update:

| Family | Version column | Current marker | Created by |
|---|---|---|---|
| `pricing_tables` | `version` | `is_current` | `admin.py:282-292` |
| `proposal_templates` | `version` | `is_current` | `admin.py:359-376` |
| `message_templates` | `version` | `is_current` | `admin.py:446-464` |
| `playbooks` | `version` | `is_current` | `ops.py:456-465` |
| `action_plans` | `version` | `status` = `active`/`superseded` | `planner_engine` |

---

## 10 · Enumerations (values are strings in the DB, never DB enums)

Complete list read from `app/core/constants.py` (539 lines, read in full):

| Enum | Values | Line |
|---|---|---|
| `Role` | 6 | `:5` |
| `LeadState` | 7 (+ transition table at `:35`) | `:23` |
| `MeetingStatus` | 8 | `:58` |
| `MeetingType` | 5 | `:69` |
| `ActionItemStatus` | 7 | `:77` |
| `ProposalStatus` | 7 | `:87` |
| `MessageChannel` | 2 | `:97` |
| `MessageKind` | 8 | `:102` |
| `MessageStatus` | 9 | `:113` |
| `TemplateKind` | 2 | `:125` |
| `FollowUpStatus` | 3 | `:130` |
| `DemoStatus` | 3 | `:136` |
| `JobStatus` | 5 | `:142` |
| `ContactSource` | 3 | `:150` |
| `Department` | 3 | `:161` |
| `SkillLevel` | 3 (+ `SKILL_LEVEL_SCORE`) | `:167` |
| `LostReason` | 4 | `:176` |
| `ProjectStatus` | 10 | `:183` |
| `ProjectHealth` | 3 | `:196` |
| `InvoicingMode` | 2 | `:202` |
| `Phase` | 6 (+ `PHASE_LEAD_ROLE` map at `:217`) | `:207` |
| `TaskPriority` | 3 (+ `PRIORITY_ORDER`) | `:227` |
| `AssignOn` | 2 | `:236` |
| `TaskSource` | 5 | `:241` |
| `CompletionMethod` | 5 | `:249` |
| `PlanStatus` | 4 | `:257` |
| `PlanTrigger` | 6 | `:264` |
| `CommitmentDirection` | 2 | `:273` |
| `CommitmentStatus` | 4 | `:278` |
| `ConflictStatus` | 2 | `:285` |
| `Influence` | 3 (+ `INFLUENCE_WEIGHT`) | `:296` |
| `AssignmentStatus` | 5 | `:309` |
| `DeclineReason` | 4 | `:317` |
| `ReminderTargetType` | 5 | `:324` |
| `EventType` | **41** | `:332` |
| `IncidentSeverity` | 3 | `:378` |
| `IncidentStatus` | 3 | `:384` |
| `DecisionType` | 7 | `:390` |
| `DigestKind` | 3 | `:400` |
| `DeliverableType` | 10 | `:406` |
| `DeliverableSource` | 2 | `:419` |
| `DeliverableStatus` | 5 | `:424` |
| `InvoiceKind` | 3 | `:432` |
| `InvoiceStatus` | 6 | `:438` |
| `PaymentMethod` | 4 | `:447` |
| `BookingKind` | 5 | `:454` |
| `ThreadStatus` | 3 | `:462` |
| `InboundIntent` | 9 | `:468` |
| `ChangeType` | 5 | `:480` |
| `Sentiment` | 3 | `:488` |
| `InboundStatus` | 4 | `:494` |
| `ApprovalEntityType` | 5 | `:501` |
| `ApprovalStage` | 2 | `:509` |
| `ApprovalStatus` | 5 | `:514` |
| `AssignmentMode` | 2 | `:522` |
| `TriggeredBy` | 6 | `:527` |

**Deliberately not an enum:** `stakeholders.role_at_client`. The comment at
`constants.py:290-293` is explicit — the role is free-form text in the client's own
vocabulary, authored by the model or a human, and *"Only `influence` below is a fixed
vocabulary — it is what the engines act on."* Also free-form: `user_skills.skill`.

---

## 11 · Everything marked INFERRED in this document

Three items. Each needs confirming before it is relied on.

1. **§5.3** — that an unrecognised `{placeholder}` in a proposal template is left as
   literal text rather than raising. The docstring's variable list is not exhaustive and
   I found no validator; I did not read `template_service.py`/`proposal_service.py`
   rendering code to confirm the failure mode.
2. **`followups.reminded`** (`followup.py:30`) is declared `Mapped[bool] = mapped_column(default=False)`
   with **no explicit type argument**. I state it resolves to a `Boolean` column from the
   annotation — that is standard SQLAlchemy 2.0 behaviour, but I did not inspect the
   emitted DDL to prove it.
3. **§9.2, FK enforcement** — I read that `app/database.py` sets only `journal_mode` and
   `busy_timeout`, and that SQLite defaults `foreign_keys` to OFF. I did not execute
   `PRAGMA foreign_keys` against the live database to observe the value.
*(A fourth item — the foreign-key count in §8 — was originally inferred and has since
been computed from `Base.metadata`; it is now a measured figure.)*
