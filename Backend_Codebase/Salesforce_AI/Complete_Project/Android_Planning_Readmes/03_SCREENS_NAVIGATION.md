# 03 — Screens & Navigation (every screen, from splash onward)

Input rule that applies to EVERY screen: anything typeable is also
**dictatable** (mic on every text field via `VoiceEditText`), anything
doable by taps is also **askable** (assistant reachable from everywhere,
pre-loaded with the current screen's context). Buttons are the fast path,
voice is the hands-free path, the assistant is the "just do it" path.

## 0. Splash

- Full-bleed brand Lottie (2s cap, skippable by tap), version + env label.
- Work: read token → `GET /auth/me`.
  - valid → Home (role graph); `must_change_password` → Forced Change.
  - invalid/absent → Login.
  - offline + cached session → Home in offline mode (banner).
- Long-press logo (debug builds): Environment sheet (base URL, org label).

## 1. Login (no self-signup — honest copy)

- Fields: email, password (both dictatable), "server" chip in debug.
- Primary: **Sign in**. Secondary: "Don't have an account?" → sheet
  explaining accounts are created by your organisation's admin (and, for
  new companies, by the platform) — with a "copy request template" button
  that drafts an email to the admin. No fake signup form.
- Errors: backend messages verbatim; lockout-friendly (no client retries).
- On success: store JWT (encrypted), warm caches (`/auth/me`,
  `/notifications`, `/digests/daily`), offer **biometric quick unlock**
  enrolment.
- Forced password change screen when flagged: old+new+rules, then
  continues to Home.

## 2. Home — the Morning Briefing (role-shaped, detail in 05)

Layout (single scroll, cards):
1. **Greeting header** — name, date, org logo; mic button (big, centered
   in bottom bar) always visible.
2. **Briefing card** (`GET /digests/daily`): today's tasks across
   projects, overdue count, approvals waiting, overnight replies — each
   line tappable straight to the thing.
3. **Waiting on you** — merged feed (approvals + assignment confirmations
   + meeting reviews + triage), each card decidable **inline**
   (Approve / Reject-with-note / Confirm batch / Review) without leaving
   Home. Empty state: "Nothing needs you. Go sell." + Lottie.
4. **Quick actions row** (role-dependent): Record meeting · Scan card ·
   New lead · Ask the assistant · Log client reply.
5. **My day** — tasks due today (swipe right = done w/ note sheet, swipe
   left = snooze→new-date), demos today, meetings scheduled.
6. **Attention strip** — project health regressions, P1 incidents,
   AI-held work (`ai_unavailable` / `needs_human`) as first-class cards.

Bottom navigation (5 slots, role-shaped, see 05): e.g. sales_agent =
Home · Leads · **Mic (assistant)** · Tasks · Inbox.

## 3. Assistant (full doc: 04)

Reached by: center mic tap (voice sheet), long-press (type mode), "Ask
about this" on any entity screen, or notification deep link.

## 4. Leads & contacts

- **Leads list**: search, filter chips (state, owner, important, city),
  state-colored dots, last-activity age. FAB: New lead (form or voice:
  "create a lead for Nexora Technologies in Bengaluru, source referral").
- **Lead detail** (collapsing header: name, state chip, owner, important
  star):
  - *Suggestion banner* when `suggested_state` present: "AI suggests
    marking cold — no reply for 30 days. [Accept] [Keep active]" →
    `PATCH /leads/{id}/state`.
  - Tabs: **Overview** (facts, next steps, revival info for lost),
    **Contacts** (cards incl. needs_review badge → verify sheet),
    **Projects**, **Notebook** (client_intelligence entries + add by
    voice/text), **History** (state journey), **Meetings**.
- **Card scan**: CameraX with card-guide overlay → crop preview → upload →
  OCR result sheet (fields editable; unclear scans arrive flagged
  `needs_review`; nothing is ever messaged until a human verifies —
  banner explains this).
- **Consent sheet** (before recording): method picker
  (verbal/written/in_app), note; writes `POST /leads/{id}/consent`.

## 5. Meetings

- **Recorder**: giant record button, elapsed time, pause/resume, level
  meter; foreground service + notification; consent gate first (skippable
  only if consent already on file for this lead — shown). Post-stop:
  meeting type picker (first_visit/kickoff/review/...), optional title,
  Upload (WorkManager, resumable, progress in notification).
- **Typed notes composer**: full-screen editor with mic dictation;
  lead/project picker; sends `POST /meetings/notes`.
- **Pipeline progress screen** (`GET /meetings/{id}` polled):
  stepper Uploaded → Transcribing → Extracting → (Review) → Done,
  each step timestamped; FAILED shows reason + Retry
  (`POST /meetings/{id}/retry`).
- **Review gate** (`/review` + `/review/confirm`): editable list of
  extracted action items (title, assignee suggestion + reason, due,
  skill), per-row accept/edit/drop, then Confirm → tasks go live.
- **Result sheet**: what the Planner did — project proposed (open it),
  plan merged vN (see diff), conflict raised (open resolver), follow-ups
  only, or *held for human* with reason.

## 6. Projects

- **Portfolio list**: health badge (green/amber/red + reason on tap),
  status, value, phase progress bar, owners' avatars. Filters: status,
  health, owner. Sort: health first.
- **Project home**: header (name, client, status pill, health + why),
  "What's blocking?" card, next 3 tasks, open commitments (ours/theirs
  with due), quick actions (Record meeting here · Draft message · Book
  demo · Catch me up = `/brief`).
- **Plan tab**: version picker (v1…vN, active highlighted), per-version
  summary + **diff viewer** (changes_from_previous rendered as
  added/moved/cancelled groups), pending version banner ("waiting for
  Akash's approval"), feasibility button.
- **Tasks tab**: grouped by phase; task rows show status, assignee,
  due, blocked chip, progress bar; batch nudge is server-side —
  no client spam button (by design).
- **Timeline tab**: humanised `progress_events` (icons per event_type),
  infinite scroll.
- **People tab**: stakeholder cards — name, `role_at_client` verbatim,
  influence chip, channel/language, receives-updates toggle,
  do_not_contact (with warning), provenance line ("added by AI from
  Meeting 2 — why?"); edit sheet posts to `/stakeholders`.
- **Team tab**: members + roles, add member (search staff), leave
  handling notes; load/leave visibility.
- **Conflicts**: list + **resolver screen** — two source cards side by
  side (speaker, influence weight, quote, date), the held plan version
  note, resolution note field (dictatable), Resolve button.
- **Reports tab**: weekly client report preview (`/weekly-report`),
  status of its approval, past sent reports.
- **Chain wizard** (multi-branch deals): parent project → add children
  (name each branch), invoicing mode picker (group/per_branch).

## 7. Tasks (Mine)

- **My Tasks**: Today / This week / Blocked / Waiting-on-vendor groups;
  P1 pinned with colored edge; each card: title, project, due, progress.
- **Task detail**: description, "assigned by AI because…" reason line
  (+ Why chip), dependencies (tappable), commitment linkage ("fulfils:
  share syllabus by Fri"), progress slider (`/progress`), buttons:
  Done (result note + method; attach photo/file → deliverables), Decline
  (reason picker: busy/wrong_skill/on_site_elsewhere/other + note),
  Block (reason) / Unblock, New date (reason), Split (two titled halves,
  auto dependency), Vendor promise/slip for external waits.

## 8. Approvals & assignments

- **Approvals inbox**: filter chips by entity type (message / proposal /
  price_change / plan_change / invoice), stage badge (recommend/decide),
  age, expiry countdown when set. Card body shows the backend-provided
  facts (amount, diff summary, recipient…). Actions: Approve /
  Reject+note (note dictatable). Message approvals preview the full
  draft (subject, body, attachments list, CC) with an "Edit first" that
  routes to the redraft flow (`/messages/draft` with instruction).
- **Assignment confirmation** (leads only): batch list, per-task reason
  ("Meera: curriculum_design expert, 3/8 load"), tap-to-override
  (pick someone else — records override), Confirm batch.

## 9. Inbox & messages

- **Message center**: outbound list w/ status trail chips
  (draft→pending→queued→sent→delivered/failed); detail = **delivery
  trace** timeline + open .eml/attachments.
- **Inbound triage**: unmatched or needs_human messages; card shows the
  intent guess + why the AI stopped + summary; actions: attach to
  lead/project, set intent, resolve (`/inbound/{id}/resolve`), or open
  assistant with it as context.
  *(Corrected 2026-07-29, when this was built: this line used to say the
  card shows a **confidence**. There is no confidence — `InboundMessage`
  has no such column and `inbound_engine` never computes one. The card
  shows `needs_human_reason`, which is the honest equivalent: the AI's own
  words for why it would not answer.)*
- **Log client reply** sheet: paste text / dictate, channel picker,
  from-contact picker → `POST /inbound/ingest` (for calls & WhatsApp
  received outside the system).

## 10. Proposals

- **Detail**: rendered header (client, program, version), narrative
  preview, **locked pricing table** (visually distinct, lock icon,
  "prices come from the pricing table — ask for a special price to start
  an approval"), version history, status.
- **PDF viewer**: inline pages, share/download; **Edit by instruction**:
  text/voice ("make the tone warmer, add a line about teacher
  certification") → new version diff shown; **submit for review** /
  **approve & send** per role.
- **Manual revision upload** (after backend G3): "Upload edited file"
  → new version, marked human_edited, still approval-gated before send.

## 11. Demos

- **Calendar**: 31-day grid, dots per team, free-day highlighting, clash
  warnings surfaced from backend; day tap → slots + demos.
- **Demo detail**: team, lead/project link, status updates
  (completed/cancelled), reschedule (date/time) — backend re-sends the
  ICS invite (SEQUENCE bump) automatically; the app just says so.
- **Book demo**: from lead/project or assistant; picks team+slot.

## 12. Follow-ups

- Queue grouped by due (overdue/today/this week); each: lead, reason,
  last activity; actions: Done (`/complete`), Draft message (AI), open
  lead. Snooze = new due date.

## 13. Money (invoices & payments)

- **Invoice list**: per project or global (role-gated), status chips
  (draft/sent/partially_paid/paid/overdue), ladder state ("reminder 2 of
  3 sent").
- **Invoice detail**: computation shown verbatim (backend string), linked
  payments, sent message trace, **Record payment** sheet (amount, method,
  reference, date — validated server-side), **Send** (→ approval; CC'd
  decision maker shown by name).
- Creation: from project (kind advance/balance/full) — amounts derived
  server-side, never typed.

## 14. Ops

- **Incidents**: open/fixing/resolved lists, severity color, owner; detail:
  description, fix tasks (add via `/fix-tasks`), resolve sheet requiring
  a **lesson** (dictatable) — lesson becomes a playbook suggestion.
- **Vendors**: registry + per-task external waits overview.
- **Leave**: my leave (start/end) + admin/lead entry for others; shows
  which tasks the backend re-checked as a result.
- **Bookings**: team availability strip (who's booked when).
- **Deliverables**: per-project file registry, upload (camera/file),
  preview via `/files/...`.

## 15. Admin (org_admin; some screens shared with leads)

Staff (CRUD, roles, skills editor, capacity, leave) · Programs ·
Pricing tables (versioned; new version wizard) · Proposal & message
templates (versioned, variable hints) · Demo teams · Org settings (all
behaviour dials grouped: review gates, quiet hours, nudge ladder, caps,
report day…) · Integrations (email/WhatsApp/calendar + Meet link, secrets
write-only) · Approval rules (thresholds) · Playbooks (+ AI suggestions
inbox with one-tap accept) · Audit log (filter by action/user/date) ·
Privacy tools (erase-contact with typed confirmation).

## 16. Platform flavor (super_admin)

Orgs list + create-org wizard (name, slug, domain, first admin — shows
temp password once) + activate/deactivate + platform stats. Explicit
empty screen for anything org-private: "Platform operators cannot read
organisation data."

## 17. Profile & settings

Me (name, role, designation) · Security (change password, biometric
toggle, **email App Password wizard** with Google walkthrough) ·
Notification prefs (channels, quiet-hours mirror of org policy — read
only where org-controlled) · About/diagnostics (env, version, last sync).

## 18. Navigation & deep links

- Per-role nav graphs assembled at login (05 doc, incl. bottom-bar maps).
- Deep links: `yuvipep://approvals/{id}`, `task/{id}`, `meeting/{id}`,
  `project/{id}`, `inbound/{id}`, `assistant?prompt=...` — used by
  notifications (and FCM later).
- Every entity screen registers itself on the **ContextBus** so the
  assistant always knows "this" (04 doc).
