# 01 — Backend Contract & Sync Verification

This is the **sync bible**: every endpoint the backend exposes (verified
against `app/main.py` + all 16 routers on 2026-07-17, after the
`role_at_client` rename), mapped to the app feature that consumes it.
If an endpoint has no consumer, or a planned feature has no endpoint, it is
called out in §3 (Gaps) — nothing is silently ignored.

Base URL: `http(s)://<host>/api/v1` — configurable at build time
(`BuildConfig.BASE_URL`) **and** overridable at runtime on the login screen's
"server" field (long-press logo → environment sheet) for dev/demo.

Auth: `Authorization: Bearer <JWT>` on every call after login.
All state-changing calls send an `Idempotency-Key` header (UUID minted
client-side, persisted with the queued request).

> ### ⚠ The server does not read that header — corrected 2026-08-25
>
> **No route in `app/` declares a `Header` parameter and no middleware reads
> one** (the only middleware is CORS). `idempotency_records` is used by exactly
> one thing — `jobs/mail_poller.py`, to dedupe *inbound IMAP* messages by
> Message-ID — and `outbound_messages.idempotency_key` is minted **server-side**
> (`uuid4().hex`, or a deterministic string like
> `proposal-email-{id}-{addr}`). The header the app sends is inert.
>
> **This sentence used to promise that a retry "never duplicates a send or a
> task". It does not, and reading it cost a reviewer a wrong conclusion.**
> What actually protects each retryable path is a rule of its own, and each is
> worth knowing because they are not interchangeable:
>
> | retried call | what really makes it safe |
> |---|---|
> | `POST /meetings/upload` | **the consent record is single-use.** The F40 lookup is `ConsentRecord.meeting_id IS NULL` and a successful upload sets it, so a second attempt finds none and is refused **422**. Measured: 2 uploads → **1 meeting**. |
> | `POST /approvals/{id}/decide` | `decide_approval` refuses a second decision with **409** (`ConflictError`) — "one decision only; a double-tap must never re-decide". |
> | `POST /notifications/{id}/read` | idempotent by nature. |
> | anything else | **nothing.** A retried `POST /leads`, `/vendors`, `/approval-rules` or `/action-items` creates a second row. `client.ts` in the setup console says the same (D17). |
>
> Keep sending the header — it costs nothing and a future server may honour
> it — but do not design against a guarantee that is not there.

---

## 1. Endpoint inventory → app consumer (complete)

### 1.1 `/auth` — identity
| Method & path | Purpose | App consumer |
|---|---|---|
| `POST /auth/login` | email+password → JWT + role + must_change_password | Login screen |
| `GET /auth/me` | who am I (role, org, name, flags, **org branding: slug/logo/colors, designation, department** — G7 done) | Splash session check; Profile screen; role-based nav bootstrap; runtime theming |
| `POST /auth/refresh` | fresh JWT from a still-valid one (G4 done) | Silent session extension before expiry |
| `POST /auth/change-password` | change / forced first-login change | Forced-change screen + Profile → Security |
| `POST /auth/email-app-password` | store user's Gmail App Password (encrypted) | Profile → "Send email as me" setup wizard |

### 1.2 `/orgs` — platform (Super Admin only)
| `POST /orgs` | create organisation + first admin | Super Admin flavor: New Org wizard |
| `GET /orgs` | list orgs | Super Admin: org list |
| `PATCH /orgs/{org_id}/active` | activate/deactivate org | Super Admin: org row toggle |
| `GET /orgs/platform/stats` | platform stats | Super Admin: dashboard |

> Super Admin ships as a separate **build flavor / hidden mode** (§05 doc).
> It can never see org sales data — the UI reflects that honestly.

### 1.3 `/admin` — org administration (Org Admin)
| `POST /admin/users`, `GET /admin/users`, `PATCH /admin/users/{id}` | staff CRUD (+ leave dates, max_open_tasks, skills via /skills) | Admin → Staff screens |
| `POST /admin/users/{user_id}/reset-password` | admin issues a temp password shown once; forced change at next login (G6 done) | Admin → Staff row → "Reset password" |
| `POST/GET /admin/programs` | product catalogue | Admin → Programs |
| `POST/GET /admin/programs/{id}/pricing` | versioned pricing tables | Admin → Pricing (read-only preview for others) |
| `POST/GET /admin/programs/{id}/proposal-templates` | versioned proposal templates | Admin → Templates |
| `POST/GET /admin/message-templates` | message templates | Admin → Templates |
| `POST/GET /admin/demo-teams` | demo teams | Admin → Teams |
| `GET/PATCH /admin/settings` | org behaviour dials (org_settings) | Admin → Org Settings (grouped form; every dial from Data Model §2.2) |
| `PUT /admin/integrations/email`, `PUT /admin/integrations/whatsapp`, `PUT /admin/integrations/calendar` | org integrations (secrets) | Admin → Integrations wizard (incl. Meet link) |
| `GET /admin/audit` | audit log | Admin → Audit trail (search/filter) |

### 1.4 `/leads` — relationships
| `POST /leads` / `GET /leads` / `GET /leads/{id}` / `PATCH /leads/{id}` | CRUD + detail (contacts, projects, intelligence, history) | Leads list (filters: state, owner, important), Lead detail |
| `PATCH /leads/{id}/state` | human-confirmed state moves (incl. accepting AI suggestion) | Lead detail state chip + "AI suggests: cold" banner |
| `POST /leads/{id}/contacts` | add contact manually | Lead detail → Contacts |
| `POST /leads/{id}/contacts/from-card` | business-card photo → OCR contact | Card-scan camera flow (CameraX) |
| `PATCH /leads/contacts/{contact_id}` | edit contact (incl. clearing needs_review) | Contact sheet; "verify scanned card" card |
| `POST /leads/{id}/intelligence` | add a fact by voice/typing | Lead detail → Notebook ("add note" + mic) |
| `POST /leads/{id}/consent` | record recording-consent | Pre-recording consent sheet in Meeting Recorder |

### 1.5 `/meetings`
| `POST /meetings/upload` | multipart audio upload → pipeline (transcribe → plan) | Meeting Recorder (record in-app or pick file) |
| `POST /meetings/notes` | typed/dictated meeting notes → same pipeline | "Type the meeting" composer |
| `POST /meetings/schedule` | schedule a future meeting | Lead/project → Schedule meeting |
| `GET /meetings/{id}` | status + transcript + results | Meeting detail (pipeline progress stepper) |
| `POST /meetings/{id}/retry` | retry failed pipeline | Meeting detail error state |
| `GET /meetings/{id}/review` + `POST /meetings/{id}/review/confirm` | human review gate for extracted action items | "Review extracted tasks" screen (edit titles/assignees/dues, confirm) |

### 1.6 `/action-items` + workflow task lifecycle
| `GET /action-items` (filters) / `POST /action-items` / `PATCH /action-items/{id}` | list/create/edit tasks | My Tasks; Project tasks tab |
| `POST /tasks/{id}/complete` | done (+ result note, completion method, artifacts) | Task card swipe/button + voice ("mark the syllabus done") |
| `POST /tasks/{id}/decline` | decline with structured reason | Task detail |
| `POST /tasks/{task_id}/block`, `POST /tasks/{task_id}/unblock` | block with reason / release | Task detail |
| `POST /tasks/{id}/progress` | update progress_percent | Task detail slider |
| `POST /tasks/{id}/new-date` | request/set new due date | Task detail |
| `POST /tasks/{id}/split` | split into linked children | Task detail overflow |
| `POST /tasks/{task_id}/vendor-promise`, `POST /tasks/{task_id}/vendor-slip` | external waits | Task detail (external wait card) |

### 1.7 `/projects` — the project layer
| `GET /projects` / `GET /projects/{id}` | portfolio + detail (status, health + reason, owners, value) | Projects list (health badges), Project home |
| `GET /projects/{id}/timeline` | progress_events humanised | Project → Timeline tab |
| `GET /projects/{id}/plans` | plan versions + diffs | Project → Plan tab (version picker, diff viewer) |
| `POST /projects/{project_id}/members`, `DELETE /projects/{project_id}/members/{user_id}` | team sheet | Project → Team tab |
| `POST /projects/{id}/status` | human status moves (on_hold, lost…) | Project header menu |
| `POST /projects/{id}/phase-shift` | trigger phase playbook wave | Project header ("Deal agreed → preparation") |
| `POST /projects/{id}/feasibility` | feasibility check | Plan tab action |
| `GET /projects/{id}/whats-blocking` | blockers digest | Project home card + assistant answer |
| `GET /projects/{id}/brief` | onboarding brief for a member | "Catch me up" button (+ assistant) |
| `POST /projects/{id}/stakeholders` | add/edit stakeholder (role_at_client, influence, channel, language, do_not_contact) | Project → People tab (AI-created rows shown with "added by AI from Meeting 2" provenance; humans edit) |
| `GET /projects/{project_id}/conflicts`, `POST /projects/{project_id}/conflicts/{conflict_id}/resolve` | conflict cards, side-by-side sources | **Conflict resolver screen** (both statements, speaker weights, resolve note) |
| `POST /projects/{id}/children` | chain-deal child projects | Chain deal wizard (Org Admin/Sales Lead) |
| `GET /projects/{id}/weekly-report` | client weekly report content | Project → Reports (approve via approvals inbox) |

### 1.8 `/proposals`
| `POST /proposals` | create from meeting/lead + program | Proposal composer (program pick; quantities from meeting) |
| `GET /proposals/{id}` | detail: narrative + locked pricing block + versions | Proposal detail |
| `POST /proposals/{id}/edit` | narrative edit by voice/text instruction (price block machine-reinserted) | Proposal detail → "Change it" (mic/text) |
| `GET /proposals/{id}/download` | rendered DOCX/PDF | In-app PDF viewer; share sheet |
| `POST /proposals/{id}/submit-review` | agent → lead review | Proposal detail |
| `POST /proposals/{proposal_id}/upload-revision` | manually edited .pdf/.docx re-submitted (G3 done): stored as the send artifact, revision recorded, status→draft (must re-pass review); PDF text is scanned for the locked total — a tampered number is refused; unreadable scans are accepted flagged "verify by eye" | Proposal detail → "Upload edited version" |
| `POST /proposals/{id}/approve-send` | one-tap approve & send | Approvals inbox + proposal detail |

### 1.8a `/mous` — contracts
A memorandum of understanding is **not** a proposal (D38). It is signed after
one is accepted, it has no commercial fields at all, and it is listed under
its own key so a contract never appears in the sales pipeline.

| `GET /mous/{id}` | detail: provenance (`filled`), revisions newest-first, `has_docx`/`has_pdf`. **No `total_amount`, no `line_items`, no `currency`** — the table has no such columns. | Client screen → a contract row |
| `GET /mous/{id}/download?format=docx\|pdf` | the contract itself; a missing PDF is converted rather than refused | Share sheet / PDF viewer |
| `GET /leads/{id}` → `mous[]` | **a separate key, beside `proposals` and never inside it** | Client screen, its own section |

**App side.** `MouDto` (`core/net/dto/`) mirrors the detail route; its
`Filled` rows carry the same eight keys the proposal card reads, so renaming
one blanks the card. `LeadDetailResponse.MouRow` is the list row.
`feature/mous/MouLines` holds every decision — `hasProvenance`,
`sourceLabel`, `heading`, `rowTitle`, `isWithTheClient` — kept out of the
fragment because there is no Robolectric and anything left in one cannot be
tested. `sourceLabel` must never let `"user"` or `"default"` fall through to
"From your records": that would tell a salesperson a figure they typed
themselves came out of the database.

**Fixtures** `contract/mou_detail.json` and `contract/lead_detail_with_mou.json`
were captured from a REAL backend run, not typed. The first carries all three
provenance labels (`ai`, `user`, `default`) on purpose — a fixture whose every
value is `"user"` cannot catch the defect above coming back.

**Not built yet:** there is no MOU detail screen. The client screen lists a
contract; tapping it goes nowhere.

### 1.9 Messages & inbox
| `GET /messages` (filters) / `GET /messages/{id}` | outbound list + delivery log | Message center; delivery trace screen |
| `POST /messages/{message_id}/approve`, `POST /messages/{message_id}/reject` | the approval taps | Approvals inbox, message preview |
| `POST /messages/draft` | ask AI to draft a client message (kind, purpose, facts) | "New message" (always lands as pending approval) |
| `POST /inbound/ingest` | manual inbound capture (paste a WhatsApp/text) | "Log client reply" sheet |
| `GET /inbound/triage` + `POST /inbound/{id}/resolve` | unmatched/unclear inbound | Triage screen (attach to lead/project, mark intent) |
| `POST /webhooks/whatsapp` | provider webhook (delivery receipts → delivery log) | *server-only; app shows resulting delivery states* |

**Phase 6 additions (2026-07-29) — all additive, no schema change, old clients unaffected:**
- `GET /inbound/triage` rows also carry `intent`, `change_type`, `matched_lead_id`,
  `matched_project_id`, `created_at`.
- `POST /inbound/{id}/resolve` also accepts `intent` (**422** unless it is an
  `InboundIntent` value) and `project_id` (**404** if it is not a project in your org).
- `GET /messages` and `GET /messages/{id}` also carry `sender_user_id`.
- Still true and deliberately unchanged: `resolve` accepts a `note` it **does not store**;
  there is no `lead_id` on `resolve` (a contact implies the lead); `attachments` are not
  serialised with a message; and no inbound record has a confidence.

### 1.10 Approvals & assignments (the heart of the app)
| `GET /approvals` | unified pending approvals (message, proposal, price_change, plan_change, invoice) with facts | **Waiting-on-you feed** (home) + Approvals inbox |
| `POST /approvals/{id}/decide` | approve / reject with note (recommend→decide stages) | Approve/Reject buttons everywhere |
| `GET /assignments/proposed` | batch of AI assignment proposals (lead_confirm mode) | Lead's "Confirm assignments" screen (per-task reason shown) |
| `POST /assignments/confirm-batch` | confirm the batch | same |

### 1.11 `/followups` & `/demos`
| `GET/POST /followups`, `POST /followups/{id}/complete` | follow-up queue | Follow-ups tab; snooze/complete; AI-drafted message via draft flow |
| `GET /demos`, `GET /demos/calendar`, `POST /demos`, `PATCH /demos/{id}` | demo scheduling, 31-day grid, clash warnings, status updates | Demos calendar screen (month grid + team chips); demo detail (reschedule/cancel → ICS invite email re-sent by backend) |

### 1.12 Ops & money
| `POST /invoices`, `GET /invoices`, `POST /invoices/{id}/send`, `POST /invoices/{id}/record-payment` | invoice lifecycle (amounts derived, never typed; CC decision maker) | Money tab: invoice list/detail, record payment sheet (amount+method+ref), send (→ approval) |
| `POST/GET /vendors` | vendor registry | Ops → Vendors |
| `POST /leave` | record leave (triggers task re-check) | Profile/Team → "I'm on leave" + admin entry |
| `POST/GET /bookings` | resource/calendar bookings | Team availability screen |
| `POST/GET /deliverables` | project deliverables registry | Project → Files/Deliverables tab (upload evidence, view) |
| `POST /playbooks`, `GET /playbooks/suggestions`, `POST /playbooks/suggestions/{id}/decide` | recipe book + AI-suggested lessons | Admin → Playbooks (accept lesson with one tap) |
| `POST/GET /approval-rules`, `DELETE /approval-rules/{id}` | org approval thresholds | Admin → Approval rules |
| `POST /skills`, `GET /skills` | user_skills vocabulary | Admin/Lead → Skills matrix editor |
| `GET /incidents`, `POST /incidents/{id}/fix-tasks`, `POST /incidents/{id}/resolve` | problem tracker (complaint → owner, severity, fix tasks, lesson) | Incidents screen (P1 banner during delivery); resolve-with-lesson sheet |

### 1.13 Assistant, digests, explainability, misc
| `POST /assistant/command` | **the Jarvis endpoint** — text (from typing or on-device STT) + optional `session_id` + optional context ids → reply, actions taken, pending approvals, echoed `session_id` | Assistant screen; global mic; contextual "Ask about this" |
| `GET /assistant/history?session_id=` | replay one conversation (oldest first, plain text turns: `role`, `content`, `agent`, `at`) — private to the caller | Assistant screen restores its transcript after process death |
| `DELETE /assistant/history?session_id=` | forget a conversation | Assistant "new chat" (+) button |
| `GET /digests/daily` | morning briefing content | Home briefing card stack |
| `GET /why/{entity_type}/{entity_id}` | AI decision explanation | "Why?" chip on every AI-produced card |
| `GET /notifications` (supports `limit/offset/since` — G2/G5 done), `POST /notifications/{id}/read` | in-app notification feed + cheap delta polling | Bell icon + notification center (grouped by kind) |
| `POST /devices`, `POST /devices/unregister` | FCM token upsert per user/device; removed on logout (G1 done — server sender dormant until the Firebase service-account key is configured) | App start / token rotation / logout |
| `GET /files/{rel_path}` | authenticated file fetch (PDFs, images, .eml) | PDF viewer, image viewer, attachment opens |
| `POST /privacy/erase-contact` | DPDP right-to-be-removed | Admin → Privacy tools (typed confirmation) |
| `POST /sync/sweep` | manual sync-engine sweep | Hidden dev/debug menu only |
| `POST /meetings/schedule` (listed §1.5) | — | — |

---

## 2. Reverse check — app features → backend (proving nothing is invented)

| App feature | Backend support | Verdict |
|---|---|---|
| Splash session restore | `GET /auth/me` | ✅ |
| Login / forced password change | `/auth/login`, `/auth/change-password` (`must_change_password`) | ✅ |
| **Self-signup** | **None — by design.** Accounts are created by Org Admin (`POST /admin/users` issues temp password); orgs by Super Admin. | ✅ handled: login-only + "ask your admin" copy + first-login change flow |
| Password reset | `POST /admin/users/{id}/reset-password` (G6 closed) | ✅ app copy directs to the admin, who issues a temp password from their Staff screen |
| Role-based home | `/auth/me` role + permissions matrix mirrored client-side | ✅ |
| Morning briefing | `GET /digests/daily` | ✅ |
| Waiting-on-you feed | `/approvals` + `/assignments/proposed` + `/meetings/{id}/review` (review_pending) + `/inbound/triage` + `/notifications` | ✅ (client-side merge) |
| Voice meeting recording + upload | `POST /meetings/upload` (backend: local Whisper) | ✅ |
| Typed meeting notes | `POST /meetings/notes` | ✅ |
| Consent before recording | `POST /leads/{id}/consent` | ✅ |
| Card scan | `POST /leads/{id}/contacts/from-card` | ✅ |
| Jarvis voice/text commands | `POST /assistant/command` (+ on-device `SpeechRecognizer` for STT of commands; meeting audio goes to backend Whisper) | ✅ |
| Jarvis remembers the conversation | `session_id` on `/assistant/command` + `GET`/`DELETE /assistant/history` | ✅ (added 2026-07-21; live 12/12) |
| Proposal PDF view | `GET /proposals/{id}/download`, `GET /files/...` | ✅ |
| Proposal edit by instruction | `POST /proposals/{id}/edit` | ✅ |
| **Manual edited-PDF re-submit** | `POST /proposals/{id}/upload-revision` (G3 closed) | ✅ versioned, total-verified, re-review forced |
| Plan diff viewer / version history | `GET /projects/{id}/plans` | ✅ |
| Conflict resolution UI | `/projects/{id}/conflicts` + resolve | ✅ |
| Stakeholder map (AI-maintained, human-edited) | `POST /projects/{id}/stakeholders`, rows auto-created by Planner/Inbound | ✅ (verified live 2026-07-17) |
| Task lifecycle incl. decline/block/split/vendor | workflow router | ✅ |
| Demos month calendar + invites | `/demos/calendar`, backend sends ICS invites | ✅ |
| Invoices & payments | ops router | ✅ |
| Incidents & complaints | workflow router | ✅ |
| Notifications center | `/notifications` | ✅ |
| **Push notifications (FCM)** | `POST /devices` + FCM fan-out in `notify()` (G1 closed; dormant until Firebase key) | ✅ polling remains the fallback (07 doc) |
| Live updates | `?since=` delta polling (G2 closed) | ✅ |
| Token refresh | `POST /auth/refresh` (G4 closed) | ✅ 401 still → re-auth UX |
| List pagination | `limit/offset` on the four heavy lists (G5 closed) | ✅ |
| Org branding in-app | slug/logo/colors on `/auth/me` (G7 closed) | ✅ |

## 3. Consolidated backend gaps — ALL CLOSED server-side on 2026-07-17

| # | Gap | Status |
|---|---|---|
| G1 | Push | ✅ `POST /devices` + `/devices/unregister`; `notification_service.notify()` fans out to FCM HTTP v1 (`app/services/push_service.py`, OAuth via signed JWT). **Dormant until `FCM_SERVICE_ACCOUNT_JSON` is set in `.env`** — needs the Firebase service-account key (see 10 doc, **Phase 9** credentials). |
| G2 | Live-ish updates | ✅ `GET /notifications?since=<ISO>` delta polling. |
| G3 | Manual proposal file re-submit | ✅ `POST /proposals/{id}/upload-revision` — revision recorded, status→draft (re-review forced), locked total verified inside extractable PDFs, tampered numbers refused, image-PDFs flagged "verify by eye". |
| G4 | Token refresh | ✅ `POST /auth/refresh` (valid token → fresh token). Expired token still → re-login. |
| G5 | Pagination | ✅ `offset` (with existing `limit`) on `/leads`, `/messages`, `/action-items`, `/notifications`. |
| G6 | Password reset | ✅ `POST /admin/users/{id}/reset-password` (admin-issued temp password, forced change). No self-serve email OTP (deliberate — accounts are org-managed). |
| G7 | Branding in `/auth/me` | ✅ org slug/logo/colors + designation/department in the response. |

**Rule stands:** the app never fakes a capability; any future gap is built
server-side first (asking you before backend changes during app phases).

## 4. Vocabularies the app must render (from `app/core/constants.py`)

- Roles: `super_admin, org_admin, sales_agent, sales_lead, operations_agent, operations_lead`
- Lead states: `open, active, cold, execution_in_progress, client_execution_in_progress, closed, lost_for_now` (labels come from backend; app maps to colors only)
- Project status: `planning, proposal_stage, negotiation, agreed, preparation, delivery, payment_pending, closed, on_hold, lost`; health: `on_track / at_risk / delayed`
- Task status: `pending_review, open, in_progress, done, cancelled, declined, superseded`; priority `P1/P2/P3`
- Meeting status: `scheduled, uploaded, transcribing, transcribed, extracting, review_pending, completed, failed`
- Message kinds/status; Approval entity types: `outbound_message, proposal, price_change, plan_change, invoice`; stages `recommend/decide`; status `pending/approved/rejected/expired/escalated`
- Inbound intents & statuses (`new/processed/needs_human/triage`)
- Influence: `decision_maker / influencer / gatekeeper` — **the only fixed people vocabulary**; `role_at_client` is free text and must be rendered verbatim (never mapped to icons/labels from a fixed list)
