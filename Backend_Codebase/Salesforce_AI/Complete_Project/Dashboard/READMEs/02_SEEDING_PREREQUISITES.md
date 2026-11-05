# 02 · Seeding Prerequisites

> **SUPERSEDED IN PLACES — read `08_PROGRESS_AND_HANDOFF.md` first.**
> This is the frozen exploration record. The manual's words and the checklist
> are unchanged and still authoritative, but **several 🔴 "no endpoint exists"
> flags are now closed**: `DELETE /skills`, `GET /playbooks`, and the program
> and pricing-version deletes all exist as of Phase 1. `08` §0.1 lists them.

**Source:** `Innodhara_Product_Manual.pdf`, **Part 3 — "The go-live checklist"**, pp. 6–7,
extracted in full this session with `pypdf` and read verbatim. The manual's own framing:

> *Work down this list before your first real client. The right-hand column is what
> actually happens if an item is skipped — **these are the product's own refusal
> messages**, not warnings invented here.*

The manual groups the checklist into three tiers: **Essential** (7 items),
**Strongly recommended** (4 items), **Optional** (4 items) — **15 items total**.
Below, each is given in the manual's own words, then resolved to the exact tables,
columns and ordering constraints the dashboard must satisfy, cross-checked against
`app/models/`, `app/api/` and the two working seeders
(`scripts/seed_workflows.py`, `scripts/reset_for_datacentre_demo.py`).

Endpoint availability for each item is stated here in summary; the full analysis,
including every gap, is in `03_API_SURFACE.md`.

---

## 0 · The dependency order

The checklist is presented as a flat list, but it is **not** order-free. Nine of the
fifteen items have a hard predecessor. This is the true ordering — derived from foreign
keys, from unique constraints, and from validation in the request handlers.

```
 TIER 0  ── platform, once ────────────────────────────────────────────────
   1. Organisation  +  its first Org Admin        (one call creates both)
        │  creates: organisations, org_settings, users[org_admin]
        ▼
 TIER 1  ── identity ──────────────────────────────────────────────────────
   2. Staff accounts, with role AND department
        │  HARD DEPENDENCY: org.email_domain must already exist —
        │  admin.py:84 refuses any address not ending "@<domain>"
        ▼
   3. A skill on every person          ◀── "the single highest-value entry"
        │  HARD DEPENDENCY: user_id must exist
        ▼
 TIER 2  ── the catalogue ─────────────────────────────────────────────────
   4. What you sell — one program per offering
        ├──▶ 5. A rate card for each offering       (FK → programs.id)
        ├──▶ 6. A proposal template for each        (FK → programs.id)
        └──▶ 8. Standard task waves (playbooks)     (FK → programs.id)
   7. Message templates: intro + follow-up          (org-wide, NO program FK)
        ▼
 TIER 3  ── governance & behaviour ────────────────────────────────────────
   9. Approval rules            (references ROLE NAMES, not user ids —
                                 so it may precede staff, but is useless
                                 until roles are actually held)
  10. The behaviour dials       (UPDATE of the org_settings row from step 1)
  11. Email sending             (per-org and/or per-user credentials
                                 + a PROCESS-WIDE env var — see §11)
  12. Retention windows         (same org_settings row)
        ▼
 TIER 4  ── optional ──────────────────────────────────────────────────────
  13. Demo teams               (HARD DEPENDENCY: user ids for lead/media/sales rep)
  14. Calendar                 (org_settings.calendar_integration + env)
  15. Vendors                  (independent)
  16. Inbound mail             (env-only — NO per-org storage at all)
```

**Steps 4 and 7 are the only two catalogue items with no predecessor beyond the org.**
Everything in Tier 2 except message templates hangs off a `program_id`.

---

# TIER 0 — Platform

## 1 · Organisation and its first administrator

> **Manual, p.6:** *"Creates the tenant every other record belongs to, and the one account
> that can configure it. Done once by the platform operator."*
> **If you skip it:** *"There is nothing to sign in to."*

**Tables written:** `organisations`, `org_settings`, `users` (one `org_admin`).
All three in a single transaction — `app/api/organisations.py:82-109`.

**Data required:**

| Field | Type | Constraint | Source |
|---|---|---|---|
| `name` | str | 2–200 chars | `organisations.py:33` |
| `slug` | str | 2–100, **pattern `^[a-z0-9-]+$`**, globally UNIQUE | `:34`, uniqueness checked at `:68-72` |
| `email_domain` | str | 3–200, must match `^[a-z0-9.-]+\.[a-z]{2,}$` after lstripping `@` and lowercasing | `:35`, `:65-67` |
| `admin_email` | EmailStr | must not already exist as any user | `:38`, `:73-79` |
| `admin_name` | str | — | `:39` |
| `logo_url` | str? | optional | `:36` |
| `brand_colors` | dict? | optional; returned to the app by `/auth/me` | `:37` |

**Returned once and never again:** `admin_temp_password` (`secrets.token_urlsafe(9)`,
`:99`). The admin is created with `must_change_password=True` (`:108`).

**The `org_settings` row is created here** with three values seeded from env
(`:92-98`): `audio_retention_days`, `transcript_retention_days`,
`llm_monthly_budget_usd`. **Every other one of its 32 columns takes its model default.**
Steps 10 and 12 are therefore *updates* to this row, never inserts.

> ⚠ **`email_domain` must be stored WITHOUT a leading `@`.** This is finding F34,
> recorded in the seeder's own comment (`seed_workflows.py:212-216`): storing
> `"@yuvipep.com"` made `admin.py:84` build `"@@yuvipep.com"`, so **no address could ever
> match and adding a staff member became impossible**. The API route lstrips it
> (`organisations.py:65`); a dashboard writing directly to the DB must do the same.

**Endpoint:** `POST /api/v1/orgs` — **super_admin only**, via `Depends(get_super_admin)`.

---

# TIER 1 — Identity

## 2 · Staff accounts, with the right role

> **Manual, p.6:** *"Email is the identity and decides the organisation; the role decides
> the navigation and the permissions. **Set each person's department too — it decides who
> receives their escalations.**"*
> **If you skip it:** *"People either cannot sign in, or see the wrong app."*

**Table written:** `users`.

**Data the manual explicitly asks for:**

| Field | Column | Settable via API? |
|---|---|---|
| Email | `users.email` | ✅ `POST /admin/users` |
| Name | `users.name` | ✅ |
| Role | `users.role` | ✅ (create and PATCH) |
| Phone | `users.phone` | ✅ |
| **Department** | `users.department` | ❌ **NO ENDPOINT** |

> 🔴 **The manual names `department` as a checklist requirement, and there is no way to
> set it over HTTP.** Verified by grep across `app/` and `scripts/`: the only writers of
> `User.department` are `scripts/seed_workflows.py:233` and
> `scripts/dryrun_part2.py:421` — both direct DB writes. `CreateUserRequest`
> (`admin.py:31-35`) and `UpdateUserRequest` (`admin.py:38-43`) contain no such field.
> `GET /auth/me` *reads* it back (`auth.py:133`), so the field is live and consumed —
> only unsettable. **The same is true of `designation`, `whatsapp_number`,
> `max_open_tasks` and `working_days`.** See `03_API_SURFACE.md` §4.2 and
> `04_OPEN_QUESTIONS.md` Q2.

**Validation the dashboard must respect:**

1. Role must parse as a `Role` and be in `ORG_ROLES` — `super_admin` cannot be
   assigned here (`admin.py:69-73`).
2. Email must be globally unique across all orgs (`:74-80`).
3. **Email must end with `"@" + org.email_domain`** (`:84-87`) — the refusal message is
   *"Staff email must use your organisation's domain @{domain}"*.
4. A `temp_password` is generated and returned **once**; `must_change_password=True`.

**The six roles to assign** (`app/core/constants.py:5-11`): `org_admin`, `sales_lead`,
`sales_agent`, `operations_lead`, `operations_agent`. (`super_admin` is platform-level
and is seeded from `.env` at startup — `main.py:51-73`.)

**`department` vocabulary** (`Department`, `constants.py:161-164`): `sales`,
`operations`, `accounts`. Note **`accounts` is a department but not a role** — the
seeded accounts executive is an `operations_agent` with `department="accounts"`
(`seed_workflows.py:68-69`).

**Endpoints:** `POST /api/v1/admin/users`, `GET /api/v1/admin/users`,
`PATCH /api/v1/admin/users/{id}`, `POST /api/v1/admin/users/{id}/reset-password` —
all `require_permission("manage_staff")` = **org_admin only**.

---

## 3 · A skill on every person's record

> **Manual, p.6:** *"**This is the single highest-value entry in this list.** Tasks are
> matched to people by skill, weighed against workload and leave. Give everyone the
> neutral skill **`general`** plus their real specialisms, at **basic, good or expert**."*
> **If you skip it:** *"Every task falls to the phase lead flagged **"no skill match"**,
> at low confidence, and is routed to a human instead of being assigned."*

**Table written:** `user_skills` — one row per person per skill.

**Data required:** `user_id` (must exist in the org), `skill` (free-form `String(100)`,
**no controlled vocabulary**), `level` ∈ `basic` | `good` | `expert`
(`SkillLevel`, `constants.py:167-171`; scored 1 / 2 / 3 by `SKILL_LEVEL_SCORE`, `:173`).

**Constraint:** `(user_id, skill)` is UNIQUE (`user.py:64`). The endpoint handles this by
**upserting** — an existing pair has its `level` overwritten and returns
`{"updated": true}` (`ops.py:641-659`).

**Why this is the top item, in code:** `action_items.required_skill` is matched against
`user_skills.skill` to build the Assignment Engine's candidate list
(`action_item.py:54`, `user.py:57-58`). The manual's stated failure mode is finding F25.
The demo runbook restates it bluntly (`reset_for_datacentre_demo.py:15-21`):

> *"A task needing a skill nobody holds routes unassigned, which is finding F25 and a bad demo."*

**The manual's own go-live verification** (p.7, "BEFORE YOU GO LIVE") is a concrete
acceptance test the dashboard should arguably surface:

> *"at least one person holds each skill your rate card implies; the quickest check is to
> open any project after the first meeting and confirm every task shows a named person
> rather than the phase lead."*

**A worked example of realistic coverage** — the 10 seeded staff hold 21 skill rows
across 15 distinct skills (`seed_workflows.py:50-70`): `negotiation`, `proposals`,
`field_sales`, `hindi`, `english_writing`, `curriculum_design`, `android`, `teaching`,
`robotics`, `scheduling`, `logistics`, `photography`, `social_media`, `invoicing`,
`payments`. The datacentre demo instead relies on transferable skills already held:
`logistics_coordination`, `scheduling`, `quality_assurance`, `training_delivery`,
`content_development`, `invoicing`, `proposal_preparation`, `client_relationship`,
`general` (`reset_for_datacentre_demo.py:17-20`).

**Endpoints:** `POST /api/v1/skills` (upsert), `GET /api/v1/skills?user_id=`.
Authorisation is an **inline role check, not a permission constant** — `ops.py:639`
hard-codes `("org_admin", "sales_lead", "operations_lead")`.

> 🔴 **There is no way to remove a skill.** No `DELETE /skills` exists. A skill entered
> wrongly can only have its `level` changed, never be withdrawn. See
> `03_API_SURFACE.md` §5 and `04_OPEN_QUESTIONS.md` Q4.

---

# TIER 2 — The catalogue

## 4 · What you sell — one entry per offering

> **Manual, p.6:** *"Named and described. **The description is what the AI reads when it
> decides which of your offerings a conversation was about.**"*
> **If you skip it:** *"Conversations cannot be matched to an offering, and no proposal
> can be built."*

**Table written:** `programs`.

**Data required:**

| Field | Type | Constraint |
|---|---|---|
| `name` | str | required — `admin.py:185` |
| `code` | str | 1–50 chars, **UNIQUE per org**, **upper-cased on write** (`admin.py:207`) |
| `description` | str? | nominally optional, **functionally load-bearing** |

`is_active` defaults to `True` (`program.py:27`).

> **The `description` is not decoration.** The manual states it is what the AI reads to
> match a conversation to an offering. The seeded descriptions are correspondingly
> substantive — e.g. *"Hands-on app-building bootcamp for classes 5–9; block-based apps
> for juniors, Kotlin introduction for seniors on days 5-7"* (`seed_workflows.py:260-263`).
> A dashboard form that treats this as an optional one-liner will silently degrade
> offering matching. It is also a `{program_description}` template variable
> (`seed_workflows.py:107`).

**Duplicate handling:** a case-insensitive code collision raises `ConflictError`
(`admin.py:196-205`).

**Endpoints:** `POST /api/v1/admin/programs` (`manage_programs` = org_admin only);
`GET /api/v1/admin/programs` — note this GET is readable by **any org member**
(`Depends(get_org_context)`, no permission), unlike its POST.

> 🔴 **No update and no delete.** There is no `PATCH /admin/programs/{id}` and no
> `DELETE`. A program's name, description or `is_active` flag cannot be changed once
> created. See `03_API_SURFACE.md` §4.3.

---

## 5 · A rate card for each offering

> **Manual, p.6:** *"Every line: **code, label, unit ("per rack", "per seat", "per site"),
> unit price, and a default quantity where one is sensible**. Rate cards are versioned —
> editing prices creates a new version and never alters a proposal already sent."*
> **If you skip it:** *"**"No pricing table for this offering. Ask your administrator to
> add one."** No proposal can be created."*

**Table written:** `pricing_tables` (a **new row per edit**, never an update).

**Data required per table:** `program_id` (path), `currency` (default `"INR"`),
`items` — **at least one** (`Field(min_length=1)`, `admin.py:254`).

**Data required per item** (`PricingItem`, `admin.py:235-249`):

| Field | Type | Default | Notes |
|---|---|---|---|
| `code` | str | required | machine key, e.g. `per_student`, `lab_setup` |
| `label` | str | required | shown to the client |
| `unit` | str | `"-"` | the manual's examples: *"per rack", "per seat", "per site"* |
| `unit_price` | float | required, **`ge=0`** | |
| `default_quantity` | float? | **`None`** | see the tri-state below |
| `notes` | str? | `None` | |

> **`default_quantity` is a documented tri-state and a dashboard form must not flatten
> it.** From the 10-line comment at `admin.py:240-247`: `None` means *"this org did not
> say how many"* — **not** "one of them". A default of `1` was previously written into
> every line an admin created without thinking about quantities, and downstream could no
> longer tell a deliberate quantity of one (one site, one handover pack) from an
> unanswered question. The value estimate scales an **unanswered** line by the count
> discussed in the meeting, and a **stated** one by itself. A checkbox-style
> "set a default quantity?" control is required; a numeric field pre-filled with 1 is a
> regression.

**Versioning behaviour** (`admin.py:272-292`): the highest existing version is found,
the new row gets `version + 1`, and the previous `is_current` is flipped to `False`.
**Proposals lock `pricing_table_id` + `pricing_version`** (`proposal.py:32-33`), so
editing prices genuinely cannot alter a sent proposal.

**Endpoints:** `POST /api/v1/admin/programs/{program_id}/pricing`
(`edit_pricing` = org_admin only); `GET .../pricing` returns the **full version history**
and is readable by any org member.

> 🔴 **No delete, and no way to reactivate an old version.** A mistaken rate card can only
> be superseded by a newer one. There is no endpoint to flip `is_current` back.

---

## 6 · A proposal template for each offering

> **Manual, p.6:** *"Your document, with placeholders the system fills in — client name,
> contact, the rate table, the total, and a one-line summary of the engagement."*
> **If you skip it:** *"**"No proposal template for this offering. Ask your administrator
> to add one."**"*

**Table written:** `proposal_templates`.

**Data required:** `program_id` (path), `name`, `body_md` (**minimum 20 characters**,
`admin.py:330`), `make_current` (default `True`).

**Placeholders available** (`program.py:56-58`, plus live usage in the seeders):

| Variable | Meaning |
|---|---|
| `{client_name}` | the client's name — **alias `{school_name}` still resolves** |
| `{contact_name}` | the addressee |
| `{sender_name}` / `{sender_email}` | the salesperson |
| `{org_name}` | your organisation |
| `{program_name}` / `{program_description}` | the offering |
| `{pricing_table}` | the rendered commercial block |
| `{total_amount}` | the computed total |
| `{context_summary}` | the one-line engagement summary the manual mentions |

Two complete working examples exist: `seed_workflows.py:96-118` and
`reset_for_datacentre_demo.py:66-88`.

**Versioning** (`admin.py:348-376`): version is scoped to `(org, program, name)` — a
template with a *new* name starts at v1; re-posting an *existing* name increments.
`make_current=True` flips `is_current=False` on **every** current template for that
program, not just same-named ones (`:361-371`).

**Endpoints:** `POST /api/v1/admin/programs/{program_id}/proposal-templates`
(`manage_templates` = org_admin only); `GET` readable by any org member, and it returns
full `body_md` for every version.

---

## 7 · Message templates: introduction and follow-up

> **Manual, p.6:** *"**One of each, for email and for WhatsApp.** These are the words a
> new contact first reads, so they should sound like your organisation."*
> **If you skip it:** *"The introduction that a scanned business card is supposed to
> draft cannot be produced at all."*

**Table written:** `message_templates`. **Org-wide — these carry no `program_id`.**

**The manual asks for four rows:** `{intro, follow_up} × {email, whatsapp}`.

**Data required** (`MessageTemplateRequest`, `admin.py:412-418`):

| Field | Constraint |
|---|---|
| `kind` | `intro` \| `follow_up` — validated against `TemplateKind` (`admin.py:428`) |
| `channel` | `email` \| `whatsapp` — validated against `MessageChannel` |
| `name` | required |
| `subject` | **required when `channel == "email"`** — *"Email templates need a subject"* (`admin.py:432-433`) |
| `body` | **minimum 10 characters** (`admin.py:417`) |
| `make_current` | default `True` |

**Versioning** is scoped to `(org, kind, channel, name)`; `make_current` flips others in
the same `(kind, channel)` (`admin.py:434-459`).

**Connection to step 2 of the app's flow:** the failure mode named in the manual's
troubleshooting table (p.16) — *"A business card scan drafts nothing"* — resolves to
*"No introduction template exists for that channel, or the contact has no address of
that kind."* `POST /leads/{id}/contacts/from-card` takes an `intro_channel` form field
defaulting to `email`.

**Endpoints:** `POST /api/v1/admin/message-templates` (`manage_templates`);
`GET /api/v1/admin/message-templates` readable by any org member.

---

# TIER 3 — Governance & behaviour ("strongly recommended")

## 8 · Standard task waves for each offering and phase — *playbooks*

> **Manual, p.7:** *"Your repeatable checklist — what always happens in preparation, in
> delivery, at payment, at closure — **with day offsets from the start date**."*
> **If you skip it:** *"Each phase is derived from scratch by the AI instead of following
> your known-good routine."*

**Table written:** `playbooks` — one row per `(program, phase)`, versioned.

**Data required:** `program_id`, `phase` ∈ `preparation` | `delivery` | `payment` |
`closure` (`project.py:177`), and `entries` — a **`list[dict]`, completely unvalidated**
(`PlaybookRequest.entries: list[dict]`, `ops.py:436`).

**The entry shape**, from the model comment (`project.py:178-180`) and confirmed against
15 working entries in `seed_workflows.py:162-201`:

| Key | Type | Notes |
|---|---|---|
| `title` | str | the task title |
| `required_skill` | str | **must match a skill somebody actually holds** — this is where steps 3 and 8 meet |
| `offset_days` | int | **relative to the anchor date; negative = before it.** Seeded values range from `-14` to `+7` |
| `priority` | str | `P1` \| `P2` \| `P3` |
| `visible_to_client` | bool | true ⇒ finishing it drafts a client update |

> ⚠ **`entries` is a raw `list[dict]` with no Pydantic sub-model.** Nothing validates the
> keys, the phase vocabulary, or that `required_skill` corresponds to any existing
> `user_skills.skill`. A dashboard is the *only* place this can be validated. See
> `04_OPEN_QUESTIONS.md` Q6.

**Versioning** (`ops.py:446-465`): the current `(org, program, phase)` row is flipped to
`is_current=False` and a new row is written at `version + 1`.

**Endpoints:** `POST /api/v1/playbooks` (`manage_programs` = org_admin only) — an upsert.
`GET /api/v1/playbooks/suggestions` lists **pending Knowledge-Engine suggestions only**.

> 🔴 **There is no `GET /playbooks`.** The dashboard cannot read back the playbooks it
> wrote. Verified against the full 140-route inventory. This is a listed prerequisite
> with a write path and no read path. See `03_API_SURFACE.md` §4.4.

---

## 9 · Approval rules

> **Manual, p.6:** *"Who signs off what, as data: a condition (for example a discount
> above 10%, or an amount above a threshold), a rank, an approver role, an optional
> second approver and an optional recommender. **Changing who approves what is a settings
> edit, never a software change.**"*
> **If you skip it:** *"Everything falls to one default approver, and nothing is escalated
> by value or risk."*

**Table written:** `approval_rules`.

**Data required** (`ApprovalRuleRequest`, `ops.py:553-564`):

| Field | Type | Default | Notes |
|---|---|---|---|
| `entity_type` | str | required | `outbound_message` \| `proposal` \| `price_change` \| `plan_change` \| `invoice` |
| `condition` | dict | `{}` | **unvalidated free-form JSON** |
| `rank` | int | `100` | **lower is checked first; the first match decides** |
| `approver_role` | str | required | an org role, **or `"thread_owner"` / `"sender"`** (`constants.py:537-538`) |
| `fallback_role` | str? | `None` | |
| `recommender_role` | str? | `None` | reviews first, attaches a recommendation |
| `joint_with_role` | str? | `None` | a second approver who must also say yes |
| `joint_condition` | dict? | `None` | joint approver required only when this also matches |
| `auto_approve` | bool | `False` | |
| `expires_hours` | float | `48.0` | a **float** — the seeded urgent rules use `0.5` |
| `description` | str? | `None` | |

**Condition keys observed in the working rule set** (`seed_workflows.py:121-160`, 16 rules):
`discount_pct_gt`, `amount_gt`, `date_shift_days_gt`, `tasks_added_gte`, `urgent`,
`new_project`, `scope_change`, `delivery_dates_moved`, `conflict_resolved`,
`resubmission`, `kind`, `channel`, `sender_is_thread_owner`. **An empty `{}` is the
catch-all** and is given a high rank so it is checked last.

> ⚠ **`condition` and `joint_condition` are plain `dict` with no schema.** A typo in a
> key name produces a rule that silently never matches. Only a dashboard can offer the
> known key vocabulary. See `04_OPEN_QUESTIONS.md` Q6.

**Note on ordering:** approval rules reference **role names**, not user ids, so they can
technically be created before any staff exist. They are inert until somebody holds the
role.

**Endpoints:** `POST /api/v1/approval-rules` and **`DELETE /api/v1/approval-rules/{id}`**
(both `manage_settings` = org_admin); `GET /api/v1/approval-rules` readable by any org
member. **This is one of only three DELETE endpoints in the entire API**, and the only
one that hard-deletes a setup record.

> 🔴 **No update.** A rule can be created and deleted but not edited — the dashboard must
> implement "edit" as delete-then-create, which changes the row id.

---

## 10 · The behaviour dials

> **Manual, p.7:** *"Working days and hours, quiet hours, the three nudge intervals, how
> many messages one client contact may receive per week, the payment-reminder schedule,
> when the weekly report goes out, and whether task assignments apply automatically or
> wait for a lead."*
> **If you skip it:** *"Sensible defaults apply, but **the system will chase on days you
> do not work and at hours you do not keep**."*

**Table written:** `org_settings` — an **UPDATE** of the row created in step 1.

**All 24 settable dials** (`SettingsRequest`, `admin.py:591-618`), with the validation
each carries:

| Field | Type | Validation | Default in model |
|---|---|---|---|
| `assignment_mode` | str | **regex `^(auto\|lead_confirm)$`** | `lead_confirm` |
| `working_days` | list[str] | **none** | `["Mon".."Sat"]` |
| `workday_start` | str | regex `^\d{2}:\d{2}$` | `09:00` |
| `workday_end` | str | regex `^\d{2}:\d{2}$` | `18:30` |
| `quiet_hours_override_priority` | str | regex `^P[123]$` | `P1` |
| `nudge_gap_days` | dict | **none** | `{level1:1, level2:3, level3:5}` |
| `max_unanswered_nudges` | int | 0–10 | `2` |
| `max_client_messages_per_week` | int | 1–50 | `3` |
| `lead_cold_after_days` | int | 1–365 | `30` |
| `high_load_caution_pct` | int | 10–100 | `80` |
| `delivery_requires_advance` | bool | — | `True` |
| `scope_change_requires_confirmation` | bool | — | `True` |
| `client_report_day` | str | **none** | `Friday` |
| `client_report_time` | str | regex `^\d{2}:\d{2}$` | `16:00` |
| `payment_reminder_schedule` | list[dict] | **none** | 4-entry ladder |
| `reply_nudge_after_days` | dict | **none** | `{nudge1:4, nudge2:8, call_task:12}` |
| `ai_confidence_threshold` | float | 0.0–1.0 | `0.6` |
| `require_action_item_review` | bool | — | `True` |
| `auto_suggest_lead_state` | bool | — | `True` |
| `followup_cadence_days` | int | 1–365 | `7` |
| `timezone` | str | **none** | `Asia/Kolkata` |
| `currency` | str | **none** | `INR` |
| `audio_retention_days` | int | 1–3650 | `90` — *step 12* |
| `transcript_retention_days` | int | 1–3650 | `365` — *step 12* |
| `llm_monthly_budget_usd` | float | ≥ 0 | `50.0` |

> ⚠ **Six of these have no validation at all** and are the ones most likely to be typed
> wrong: `working_days` and `client_report_day` are free strings whose values must match
> the day labels the engines compare against (`"Mon".."Sun"` and `"Friday"` respectively);
> `nudge_gap_days`, `reply_nudge_after_days` and `payment_reminder_schedule` are raw
> JSON whose expected key names appear only in model comments; `timezone` and `currency`
> are unconstrained strings. `PATCH /admin/settings` applies with a blind
> `setattr(row, field_name, value)` loop (`admin.py:706-707`) — a nonsense value is
> stored without complaint. See `04_OPEN_QUESTIONS.md` Q6.

**Semantics worth surfacing in the UI:**

- **`assignment_mode`** is the single most visible dial. `lead_confirm` (the default)
  means the phase lead must confirm each assignment batch before anyone is notified —
  which is why `confirm_assignments` is a lead-only permission, and why the Android
  RoleGate gap in `00_CONTEXT.md` §3.2 matters.
- **`max_client_messages_per_week`** is a cap **per stakeholder across ALL projects**
  (`organisation.py:81-82`), not per project.
- **`payment_reminder_schedule[].cc`** may name either an influence level
  (`"decision_maker"`) or a client-vocabulary stakeholder role (`"principal"`, `"cfo"`)
  (`organisation.py:94-97`).

**Endpoints:** `GET` and `PATCH /api/v1/admin/settings` — both
`require_permission("manage_settings")` = org_admin only. `PATCH` uses
`exclude_none=True`, so **omitting a field leaves it unchanged; there is no way to reset
one to null.**

---

## 11 · Email sending

> **Manual, p.7:** *"Either an organisation-wide sending account, or — better — each
> salesperson's own, so the client always sees a real person's address."*
> **If you skip it:** *"**Messages are drafted, approved and written to an outbox file
> instead of being delivered.**"*

**Three separate things, and the dashboard controls only two of them.**

| # | What | Where it lives | Endpoint |
|---|---|---|---|
| 1 | Org-wide sending account | `org_settings.email_integration` — `{"smtp_username", "smtp_app_password_enc"}`, Fernet-encrypted | ✅ `PUT /api/v1/admin/integrations/email` |
| 2 | Per-salesperson account | `users.smtp_app_password_enc`, Fernet-encrypted | ⚠ `POST /api/v1/auth/email-app-password` — **self-service only; there is no admin route to set it for another user** |
| 3 | **Whether mail actually leaves** | `EMAIL_MODE` — a **process-wide environment variable** | ❌ **NO ENDPOINT — not per-org, not in the database at all** |

**Verified at `app/services/email_service.py:147`:**

```python
if settings.email_mode != "smtp" or creds is None:
    ...  # returns f"dry_run:{rel}" — writes the RFC-822 message to a file
```

Both halves are required. Storing perfect credentials through the dashboard while
`EMAIL_MODE=dry_run` (the default, `config.py:87`) produces exactly the failure the
manual warns about on p.7:

> *"verify that sending is switched on if you intend real email to leave — **otherwise
> approved messages are written to a file and everyone believes they were sent**."*

And on p.16: *"Approved messages never arrive → Sending is not switched on, so messages
are being written to a file."*

> 🔴 **A setup dashboard cannot complete this checklist item, and cannot even truthfully
> report its status.** `GET /admin/settings` returns `email_integration_configured` as
> `bool(smtp_username)` (`admin.py:677-679`) — which is `True` while `EMAIL_MODE` is
> `dry_run` and no mail will ever leave. **This is the most dangerous gap found.** See
> `04_OPEN_QUESTIONS.md` Q3.

The same three-way split applies to WhatsApp (`WHATSAPP_MODE`, `config.py:95`) and
calendar (`CALENDAR_MODE`, `config.py:102`).

---

## 12 · Retention windows

> **Manual, p.7:** *"How long recordings and transcripts are kept before they are
> automatically deleted and scrubbed."*
> **If you skip it:** *"Defaults apply: **recordings 90 days, transcripts one year**."*

**Table written:** `org_settings` — the same row as step 10.

| Field | Column | Range | Default |
|---|---|---|---|
| Recordings | `audio_retention_days` | 1–3650 | 90 (`organisation.py:43`) |
| Transcripts | `transcript_retention_days` | 1–3650 | 365 (`organisation.py:44`) |

Seeded from env at org creation (`organisations.py:94-95`); env defaults
`DEFAULT_AUDIO_RETENTION_DAYS=90`, `DEFAULT_TRANSCRIPT_RETENTION_DAYS=365`
(`config.py:119-120`). Enforced by `services/retention_service.py`, which sets
`meetings.audio_deleted_at` and `transcripts.archived_at`.

**A third, undocumented retention window exists** that the manual's checklist does not
mention: `assistant_history_retention_days` (default 90, `config.py:84`) drops assistant
conversations older than that — *"A chat buffer must not quietly become a permanent
store"*. It is **env-only, not per-org**, and has no dashboard control.

**Endpoint:** `PATCH /api/v1/admin/settings`.

---

# TIER 4 — Optional

## 13 · Demo teams

> **Manual, p.7:** *"Named squads with a team lead, a media representative and a sales
> representative, so a booking can be made against a team and clashes detected."*
> **If you skip it:** *"Demos are still bookable; they simply carry no team."*

**Tables written:** `demo_teams`, `demo_team_members`.

**Data required** (`DemoTeamRequest`, `admin.py:497-502`): `name` (**UNIQUE per org**,
case-insensitively checked at `:511-520`), and four optional user references —
`lead_user_id`, `media_rep_id`, `sales_rep_id`, `member_ids: list[str]`.

**Every referenced user id is validated to exist in the org** before anything is written
(`admin.py:522-534`) — a bad id raises *"User {id} not found in your organisation"*.

**Hard dependency on step 2.** `demo_team_members` has a UNIQUE index on
`(team_id, user_id)` (`demo.py:28`).

**Endpoints:** `POST /api/v1/admin/demo-teams` (`manage_teams` = **org_admin or
operations_lead** — the only setup permission not exclusive to org_admin);
`GET /api/v1/admin/demo-teams` readable by any org member and resolves names.

> 🔴 **No update, no delete, no member removal.** A team's composition is fixed at
> creation. Because the name is UNIQUE per org, a mistake cannot even be corrected by
> re-creating under the same name.

---

## 14 · Calendar

> **Manual, p.7:** *"Connect a calendar and confirmed demos are mirrored into it. The
> system's own calendar remains the source of truth either way."*
> **If you skip it:** *"Invitations still reach clients by email; nothing appears in your
> own calendar."*

**Table written:** `org_settings.calendar_integration`.

**Data required** (`CalendarIntegrationRequest`, `admin.py:631-636`):

| Field | Notes |
|---|---|
| `calendar_id` | required |
| `credentials_file` | required — **a filesystem path to a service-account JSON, stored as plain text, not uploaded and not encrypted** |
| `meet_link` | optional — a reusable Google Meet link stamped into demo invites; *"create one at meet.google.com → 'Create a meeting for later'"* |

> ⚠ Unlike the email and WhatsApp integrations, **nothing here is encrypted** — there is
> no `encrypt_secret` call in `set_calendar_integration` (`admin.py:752-768`), because
> the secret lives in a file the server must already be able to read. A dashboard cannot
> upload that file; it can only record a path that must already exist on the server.
> Same env caveat as §11: `CALENDAR_MODE` must be `google` (`config.py:102`).

**Endpoint:** `PUT /api/v1/admin/integrations/calendar` (`manage_settings`).

---

## 15 · Vendors

> **Manual, p.7:** *"Outside suppliers your plans depend on, so a vendor promise can be
> recorded against a task and chased."*
> **If you skip it:** *"Vendor promises can still be typed as free text, but are not
> tracked as vendors."*

**Table written:** `vendors`.

**Data required** (`VendorRequest`, `ops.py:249-255`): `name` (the only required field),
plus optional `contact_name`, `phone`, `email`, `category`, `notes`.
**No validation of any kind** — the body is splatted straight into the model
(`Vendor(org_id=ctx.org_id, **body.model_dump())`, `ops.py:264`).

**Endpoints:** `POST /api/v1/vendors`, `GET /api/v1/vendors` — **both open to any
authenticated org member** (`Depends(get_org_context)`, no permission string), which is
unusually permissive for a setup record.

> 🔴 **No update, no delete.** Also note `GET /vendors` returns only
> `{id, name, category, notes}` — **`contact_name`, `phone` and `email` are written but
> never readable back** (`ops.py:278-281`).

---

## 16 · Suppliers of inbound mail

> **Manual, p.7:** *"Connect a mailbox and client replies are read and classified
> automatically."*
> **If you skip it:** *"Replies are captured by hand with **Log a reply**, which works
> fully and takes seconds."*

**Table written: NONE.**

This is **entirely environment configuration** (`config.py:65-70`):
`INBOUND_EMAIL_MODE` (`off` | `imap`), `IMAP_HOST`, `IMAP_PORT`,
`INBOUND_POLL_SECONDS`. The per-org mailbox reuses the same Gmail App Password as
sending, but the switch itself is process-wide.

> 🔴 **No endpoint, no column, no per-org storage.** A dashboard cannot satisfy this
> checklist item in any form. Additionally, the current operational instruction is to
> **keep it off**: this is open finding **F35**, and the demo runbook says so in bold —
> *"⛔ Never set `INBOUND_EMAIL_MODE` (F35)"* (`DEMO_WALKTHROUGH.md`, part 0.2).
> See `04_OPEN_QUESTIONS.md` Q3 and Q11.

---

# Summary — can the dashboard satisfy the checklist?

| # | Prerequisite | Tier | Create | Read | Update | Delete |
|---|---|---|---|---|---|---|
| 1 | Organisation + first admin | Essential | ✅ super_admin | ✅ | ⚠ `is_active` only | ❌ |
| 2 | Staff accounts + role | Essential | ✅ | ⚠ 6 fields only | ⚠ 5 fields | ❌ deactivate only |
| 2b | **Staff `department`** | Essential | ❌ | ❌ (only via `/auth/me`, self) | ❌ | — |
| 3 | A skill on every person | Essential | ✅ upsert | ✅ | ✅ level only | ❌ |
| 4 | Programs (what you sell) | Essential | ✅ | ✅ | ❌ | ❌ |
| 5 | Rate card per offering | Essential | ✅ versioned | ✅ full history | ✅ = new version | ❌ |
| 6 | Proposal template per offering | Essential | ✅ versioned | ✅ full history | ✅ = new version | ❌ |
| 7 | Message templates ×4 | Essential | ✅ versioned | ✅ full history | ✅ = new version | ❌ |
| 8 | Playbooks (task waves) | Recommended | ✅ upsert | ❌ **no GET** | ✅ = new version | ❌ |
| 9 | Approval rules | Recommended | ✅ | ✅ | ❌ | ✅ |
| 10 | Behaviour dials | Recommended | — | ✅ | ✅ | ❌ no reset-to-null |
| 11 | **Email sending** | Recommended | ⚠ credentials only | ⚠ **misleading** | ⚠ | ❌ |
| 12 | Retention windows | Recommended | — | ✅ | ✅ | — |
| 13 | Demo teams | Optional | ✅ | ✅ | ❌ | ❌ |
| 14 | Calendar | Optional | ⚠ path only | ⚠ boolean only | ⚠ | ❌ |
| 15 | Vendors | Optional | ✅ | ⚠ 4 of 7 fields | ❌ | ❌ |
| 16 | Inbound mail | Optional | ❌ **env only** | ❌ | ❌ | ❌ |

**Verdict.** Of the **7 Essential items**, the dashboard can create **6** over HTTP —
`department`, named explicitly in the checklist, has no write path at all. Of the
**15 items**, **3 cannot be completed by any HTTP client** (staff department, the
`EMAIL_MODE` half of email sending, and inbound mail entirely), **1 has no read-back
path** (playbooks), and **13 of 15 have no delete path**.

Every one of these gaps is carried forward, with the verification behind it, into
`03_API_SURFACE.md` §4–§5 and raised as a question in `04_OPEN_QUESTIONS.md`.
