# YuviPep AI Sales Platform — Backend

Zero-touch sales automation using AI agents, built as a **multi-organisation
platform** (design doc v2.0 implemented in full). The salesperson talks; the
AI listens, writes the notes, finds the tasks, reads the business card, sends
a warm introduction, builds the proposal and sends the email — with **one
human approval tap** before anything reaches a client.

---

## Quick start (Windows / anywhere with Python 3.10+)

```bash
cd Complete_Project
pip install -r requirements.txt

# 1) Seed the YuviPep demo organisation (staff, IBC program, pricing,
#    templates, Team Alpha, sample schools)
python scripts/seed_demo.py

# 2) Start the backend
python run.py
```

Open **http://localhost:8000/docs** for the interactive API explorer.

**Demo logins** (password `Password@123`):

| Email | Role |
|---|---|
| `admin@yuvipep.com`  | Org Admin |
| `rahul@yuvipep.com`  | Sales Agent |
| `siva@yuvipep.com`   | Sales Lead |
| `mithun@yuvipep.com` | Operations Lead |

Platform **Super Admin** (from `.env`): `superadmin@platform.local` /
`SuperAdmin@123` — can create organisations, cannot read any org's sales data.

Run the test suite:

```bash
python -m pytest tests -q            # 42 unit/API tests (stub provider)
python scripts/dryrun_workflows.py   # 43 end-to-end workflow scenarios (stub provider)
python scripts/verify_demo_invites.py # demo calendar invites: book → approve/send → reschedule → cancel
python scripts/verify_generic_stakeholders.py --stub # corporate-client stakeholder lifecycle, deterministic
python scripts/verify_gap_endpoints.py # mobile-prep endpoints G1–G7 (refresh, devices, pagination, reset-password, upload-revision incl. tamper refusal)

# LIVE suites (real LLM key from .env) — run in this order, they share a DB:
python scripts/verify_generic_planner.py      # generic planning A–D (any-topic plan, conflict, date shift)
python scripts/verify_generic_stakeholders.py # corporate client: model-authored roles/influence, AI-added people (own fresh DB)
python scripts/verify_live_change_requests.py # W4 discount/content changes + deal-agreed switch
python scripts/verify_live_routing.py         # W19 questions, W29 multi-project routing, X1 triage
python scripts/verify_live_answers.py         # W19 upgrade: facts picked by meaning, not word overlap
python scripts/verify_live_offdomain.py       # incubation-centre engagement: plan, judged skills, authored scope wave
python scripts/verify_live_voice.py note.wav  # voice note → local Whisper → LLM analysis → reviewed action items
python scripts/verify_live_imap.py            # IMAP poller gates: hygiene, noise screening, triage, dedupe
python scripts/verify_live_inbound.py         # W20 scope growth, W22 complaint
python scripts/verify_live_proposal_payment.py # W3 proposal loop, W25 getting paid
python scripts/verify_live_conversation.py    # assistant conversation memory (own fresh DB, no prerequisites)
```

---

## Generic, LLM-native planning (no templates, no keyword rules)

The Planner is **topic-agnostic**: any first meeting on any subject — a lab
build-out, an event, a procurement job, a training program — becomes a full
task breakdown authored by the model layer (`app/ai/planning.py`), and any
follow-up meeting becomes a **diff** against the live plan. The division of
labour is strict:

- **The LLM authors the WHAT** — tasks, phases, skills, dependencies,
  durations, commitments, contradictions ("conflict: X says 5 days, Y says
  7"), date moves, cancellations — as schema-constrained JSON that is then
  **re-validated field by field** (unknown ops dropped, unknown task ids
  dropped, dates parsed, phases/priorities clamped to the vocabulary).
- **Deterministic code keeps the HOW** — plan versioning ("nothing
  half-applies"), approval gates, the assignment scoring formula
  (skill/load/leave/continuity facts from the DB — never model guesses),
  cycle refusal, reminder ladders, and **prices strictly from pricing
  tables** (a model output can never invent a number a client sees).
- **Skill mapping** — the model plans against the org's *actual* skill
  taxonomy (passed into every planning prompt); a plan needing a skill nobody
  holds raises an explicit **skill-gap decision** for a human instead of a
  silent fallback. The same judgement staffs one-off work: a client's
  content-change ask gets its `required_skill` picked from the taxonomy
  (`planning.pick_skill`), never a hardcoded default.
- **Scope changes are authored, not templated** — "add a second floor" on an
  incubation-centre project produces fit-out and procurement tasks derived
  from *that* project's objective (`planning.generate_scope_wave`); the
  amendment's money still comes only from the accepted proposal's locked
  per-unit line (per student, per seat, per rack — whatever the unit).
- **Questions answered from our own data, matched by meaning** — the model
  judges which recorded facts (program, deliverables, client intelligence)
  genuinely answer a client's question and whether they *suffice*
  (`planning.select_answer_facts`); "a real industry language" finds the
  Kotlin syllabus with zero words in common. Replies compose strictly from
  the chosen facts; insufficient data routes to a named human ("the AI never
  guesses").
- **Stakeholders speak the client's language, and the AI keeps the map** —
  `stakeholders.role_at_client` is free-form in the client's own vocabulary
  (a school has a `principal`, a company a `cto` or `procurement_head`; no
  fixed list exists). The model classifies who is who at the first meeting,
  and people who surface in **later** meetings or inbound messages are added
  by the Planner itself — contact (`source=meeting`) plus stakeholder row —
  never by human data entry. Engines act on **influence**
  (decision_maker / influencer / gatekeeper), never on role strings: the
  invoice is CC'd to the decision maker, the gentle chase goes to the
  day-to-day contact. The sync is additive-only — it never overwrites a
  value a human set; a contradicting later reading becomes a "Noted:" line
  for a human to act on.
- **Message routing is judged, not keyword-matched** — with several projects
  on one client, the model picks the project a message concerns, or lists
  all of them when it deliberately spans several (`related_project_ids`
  records the span; a human sorts it). Money always takes the money path:
  a discount ask phrased as a question still enters the recommend→decide
  approval chain, and "the cheque is ready, collect Friday" is payment
  information even though it proposes a time.
- **Failure = human, never a guess** — if the model layer is unreachable
  after retries, meetings are held for review and inbound messages route to
  triage. Keyword heuristics run **only** under `LLM_PROVIDER=stub`, which is
  what keeps the test suites deterministic and free.

Deliberately deterministic, by design: **pricing tables** (a model output can
never invent a number a client sees), **approval gates and plan versioning**,
and the **assignment scoring formula** over database facts. Those are policy,
not language understanding — they must be identical every time.

---

## Configuration — one file: `.env`

Everything lives in `.env` next to `run.py`. **Paste your keys there.**
Anything left blank degrades gracefully — the platform always runs:

| Setting | What it does | Without a key |
|---|---|---|
| `GEMINI_API_KEY` | Gemini models + embeddings (already filled in) | AI features error politely; memory falls to an offline embedder |
| `STT_PROVIDER` | `whisper_local` (default — open-source Whisper **on this machine**, audio never leaves the server, no key/quota; needs `openai-whisper` + ffmpeg) \| `gemini` | — |
| `WHISPER_MODEL` | `tiny`–`large` accuracy/speed trade (first use downloads to `~/.cache/whisper`) | — |
| `OPENROUTER_API_KEY` | One key → hundreds of models, many **free** (already filled in) | — |
| `LLM_PROVIDER` | `gemini` \| `claude` \| `openrouter` — one-line switch (doc §8) | — |
| `EMAIL_MODE` + `SMTP_DEFAULT_*` | Real Gmail sending via App Passwords | **dry-run**: full `.eml` written to `data/storage/orgs/<org>/outbox/` |
| `INBOUND_EMAIL_MODE=imap` | Polls each org's inbox (same App Password) every `INBOUND_POLL_SECONDS` and feeds new mail to the Inbound Engine — automation headers skipped, strangers screened by the model (noise ignored **with an audit entry**), known contacts always ingested, model-down = kept, never dropped | **off**: inbound arrives only via `POST /inbound/ingest` |
| `WHATSAPP_MODE` + tokens | Meta WhatsApp Cloud API | **dry-run**: message JSON written to outbox |
| `CALENDAR_MODE` + service-account file | Mirrors demos to Google Calendar | internal calendar only (always works) |
| `FCM_SERVICE_ACCOUNT_JSON` | Path to a Firebase service-account key → every in-app notification also pushes to registered mobile devices (`POST /devices`) via FCM HTTP v1 | push stays dormant; in-app notifications + polling unaffected |

**Demo calendar invites (over plain SMTP — no Workspace needed):** booking a
demo drafts an approval-gated email to the lead's primary contact (CC the demo
team) carrying an iCalendar `invite.ics` (`METHOD:REQUEST`) — Gmail/Outlook
render the native invitation card with **Yes/No/Maybe** RSVP buttons and add
the event to the recipient's calendar. Rescheduling re-sends the same event
UID with a higher SEQUENCE ("This event has been updated"); cancelling sends
`METHOD:CANCEL`. The org's **reusable Google Meet link** (create once at
meet.google.com → "Create a meeting for later"; set via
`PUT /api/v1/admin/integrations/calendar` `meet_link`, or platform-wide via
`GOOGLE_MEET_LINK` in `.env`) is stamped into the event location, the
Join-with-Google-Meet button in the styled HTML body, and the plain-text
body. The ICS mirrors Google Calendar's own invitation format byte-for-byte
(small SEQUENCE, `VTIMEZONE` Asia/Kolkata, `X-GOOGLE-CONFERENCE`) — Gmail is
strict about this. See `app/services/ics_service.py` and
`app/services/demo_invite_service.py`.
| `DATABASE_URL` | SQLite by default; point at PostgreSQL for production | — |

Per-organisation overrides (each org's own Gmail/WhatsApp/Calendar) are set by
the Org Admin at runtime via `PUT /api/v1/admin/integrations/...` — secrets are
stored **encrypted** (Fernet, key derived from `SECRET_KEY`).

Per-user sending: each salesperson stores their own Gmail App Password via
`POST /api/v1/auth/email-app-password`, so proposals go out **from their own
address** (create one at https://myaccount.google.com/apppasswords).

### Switching providers

```
LLM_PROVIDER=claude        # + ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=openrouter    # + OPENROUTER_API_KEY=sk-or-v1-...
LLM_PROVIDER=gemini        # + GEMINI_API_KEY=...
```

That's it — the model layer (`app/ai/llm.py`) speaks all three providers,
including tool calling and image parts. OpenRouter gives access to hundreds
of models with one key — the `:free` model ids cost nothing (choose per tier
via `OPENROUTER_MODEL_FAST` / `OPENROUTER_MODEL_STRONG`).

**Current configuration (2026-07-22):** this project runs on PAID models after a
measured bake-off — `OPENROUTER_MODEL_FAST=openai/gpt-5.4-nano` and
`OPENROUTER_MODEL_STRONG=google/gemini-2.5-flash`, with
`LLM_DEFAULT_ORG_MONTHLY_BUDGET_USD=3.0`. Measured cost is ~$0.09 for a heavy
day's work. See `FINDINGS.md` (status header) for why each candidate won or lost.

Speech-to-text has its own switch (`STT_PROVIDER`): **`whisper_local`** runs
the open-source Whisper model on your own machine — audio never leaves the
server, no key, no quota (needs `openai-whisper` + ffmpeg) — while `gemini`
uses Google's audio understanding and always calls Gemini directly, whatever
the chat provider is. RAG embeddings ride on `GEMINI_API_KEY` (OpenRouter
exposes no embeddings endpoint); without a key, a deterministic offline
embedder keeps the memory features alive.

### Switching to PostgreSQL + Row-Level Security

1. `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/salesai` and
   `pip install asyncpg`
2. Start once (tables are created), then run `scripts/postgres_rls.sql` —
   this turns on the **Level-2 database fence** (doc §2.4). Level 1
   (application-side org_id filtering on every query) is always on.

---

## What's implemented (mapped to the design doc)

| Doc section | Implementation |
|---|---|
| §2 Multi-organisation | `org_id` stamped on every row; every query org-filtered; per-org file folders `orgs/{org_id}/...`; per-org RAG namespace; RLS script for PostgreSQL |
| §3 Roles | 6 roles + platform Super Admin; central RBAC matrix `app/core/permissions.py`; email = identity, org domain enforced |
| §4 Lead states | Full state machine with validated transitions, history, "important" flag, and system **suggestions** a human confirms |
| §5/§6 Architecture & agents | Orchestrator (`app/ai/orchestrator.py`) routes to 6 specialist agents (conversation, proposal, email, follow-up, query, scheduling), each with org-scoped tools; the model can never choose an org |
| §8 Model strategy | Provider switch Gemini↔Claude; model tiers (fast for simple steps, strong for proposals); per-org monthly budgets; usage+cost tracked per call |
| §9.1 Meeting flow | `POST /meetings/upload` → background pipeline: transcribe (Gemini STT, Files API for big audio) → action items → optional human review gate → contacts by card OCR → intro message from template → proposal → voice edits → approve & send |
| §9.2 Status fetch | Query agent + `/action-items` (list, reassign with notification, close with result) |
| §9.3 Demos | Teams, schedules, **31-day calendar grid** with free-day detection, clash warnings |
| §9.4 Follow-ups | Due lists, AI-drafted messages, complete → next reminder auto-scheduled; daily reminder notifications |
| §9.5 Admin | Programs, **versioned** pricing tables, **versioned** proposal & message templates (multiple per program), staff, demo teams, feature switches |
| §11 Scale | Composite `(org_id, ...)` indexes; job queue with priorities + per-org fairness; LLM concurrency limit; send pacing per provider; reuse (no re-transcribe, template filling) |
| §12 Reliability | **Numbers never come from the AI** (pricing block is machine-generated and re-inserted after every narrative edit); proposals lock template+pricing versions; idempotency keys on sends; retry w/ exponential backoff → dead-letter + alert; low-confidence transcripts/cards flagged for review |
| §13 Security | JWT auth, PBKDF2 passwords, encrypted integration secrets, org isolation, human approval gate on every outbound message, full audit log |
| §14 DPDP | Consent required before processing; per-org retention (audio deleted before transcripts); right-to-be-removed (`POST /privacy/erase-contact`) purges DB + files + memory |
| §15 Onboarding | Super Admin creates org + first admin (temp password) → admin sets up everything via API; no code changes |

## The one-tap approval contract (for the Android app)

Every client-bound message is created in `pending_approval`. The app shows it
and calls:

- `POST /api/v1/messages/{id}/approve` → queued → sent (background, paced,
  retried, dead-lettered on repeated failure — never silent)
- `POST /api/v1/messages/{id}/reject`

`POST /api/v1/proposals/{id}/approve-send` is the combined "Approve & Send"
tap for proposals. Delivery status: `GET /api/v1/messages/{id}` (delivery log:
drafted → queued → sent → delivered/failed, fed by provider webhooks at
`/api/v1/webhooks/whatsapp`).

## The assistant endpoint (voice/text commands)

```
POST /api/v1/assistant/command
{ "text": "Create the IBC proposal, make it 16 workshops at Rs 1500,
           and send it to the Principal with the Owner in CC",
  "session_id": "9f1c…"  }
```

Response: which agent handled it, a plain-language `reply`, the `actions`
taken (every tool call recorded), and `pending_approvals` for the app to
render approve buttons. Optional context (`lead_id`, `proposal_id`) tells the
agent what's on screen.

**Conversation memory.** Send a `session_id` (any stable 8–64 char token the
client mints, one per chat thread) and the calls become a conversation: the
previous turns are replayed to the agent *and to the router*, so "make it
warmer", "send it to her" and "the second one" resolve instead of arriving as
the first thing ever said. Omit it and the endpoint is stateless and records
nothing, exactly as before — scripts and tests rely on that.

- `GET /api/v1/assistant/history?session_id=…` — replay the transcript
  (oldest first) so a restarted app carries on instead of showing an empty
  screen. Private to the caller: a colleague passing the same id gets nothing.
- `DELETE /api/v1/assistant/history?session_id=…` — "new chat" that actually
  forgets.

Turns store **plain text only**. Tool calls, tool results and entity ids stay
inside the request that produced them: replaying an id later would let the
model act on a record whose permissions may since have changed, and an
unpaired `tool_result` is rejected outright by the providers. The model gets
what was *said* and re-resolves anything it needs through org-scoped tools.
Conversations are trimmed per session (`ASSISTANT_SESSION_MAX_TURNS`), swept
after `ASSISTANT_HISTORY_RETENTION_DAYS`, and purged when a person is erased
under a data-subject request — a chat buffer must not become a filing cabinet.
Verified live by `scripts/verify_live_conversation.py` (12/12).

## Project layout

```
app/
  config.py            .env-driven settings
  database.py          async SQLAlchemy (SQLite dev / PostgreSQL prod)
  main.py              FastAPI wiring, startup, error handling
  core/                constants (states/roles), RBAC matrix, JWT, crypto
  models/              55 tables — every business row carries org_id
  services/            leads, proposals (versioned), docs (DOCX/PDF), email,
                       whatsapp, calendar, calendar invites (ics_service +
                       demo_invite_service), messages, retention, storage...
  ai/
    llm.py             provider switch + tiers + budgets + retries
    planning.py        LLM-native planner brain: initial plans, plan diffs,
                       conflict detection, phase & scope waves, skill picking,
                       answer-fact selection, project matching, skill-gap
                       flagging — schema-validated, any topic
    stt.py vision.py   audio transcription (local Whisper | Gemini switch) /
                       business-card OCR
    memory.py          per-org RAG (embeddings + cosine search)
    orchestrator.py    request router
    agents/            6 specialist agents with org-scoped tools
  jobs/                persisted queue (priorities, fairness, backoff, DLQ),
                       meeting pipeline, send worker, daily scheduler,
                       IMAP inbox poller (mail_poller.py)
scripts/
  seed_demo.py         YuviPep demo data
  postgres_rls.sql     Row-Level Security (production level-2 fence)
tests/                 58 tests: isolation, RBAC, states, proposals,
                       meetings pipeline, agents, demos, follow-ups,
                       message approvals, explainability + digest
```

## Notes & deliberate choices

- **Jobs**: an in-process asyncio queue persisted in the DB (restart-safe,
  priorities, per-org fairness, backoff, dead-letter). The job contract is
  Celery-shaped; moving to Celery+Redis later touches only `app/jobs/queue.py`.
  Callers already inside a request transaction pass their session to
  `enqueue(db=...)` so the job commits **atomically with the work it
  carries** — a second session's insert would deadlock on SQLite's single
  write lock (this exact bug once made every "Approve & Send" take 32s).
- **Schema migrations**: `init_db` applies tiny idempotent in-place
  migrations after `create_all` (`database._apply_light_migrations`) — e.g.
  the `stakeholders.role_at_school → role_at_client` rename lands
  automatically on old SQLite/PostgreSQL databases at startup. Alembic can
  replace this when the schema starts moving faster.
- **SQLite concurrency**: WAL mode + `busy_timeout=30s` are set on every
  connection; LLM usage rows are written by a background task so a request
  transaction that is waiting on a model call never blocks them.
- **RAG**: embeddings stored in the DB, cosine search in Python — exact and
  fast at current scale, namespaced per org. The §11.4 migration path
  (pgvector/Qdrant) is contained to `app/ai/memory.py`.
- **Gemini free tier** (only when `LLM_PROVIDER=gemini`): `gemini-2.5-flash` +
  `gemini-2.5-flash-lite` are used (2.5-pro isn't on the free tier). The active
  provider is `openrouter` — see "Current configuration" above. Change tiers in
  `.env` anytime.
- **Dry-run modes** mean the *entire* system — including "sent" emails — is
  testable today; flip `EMAIL_MODE=smtp` when you paste an app password.
