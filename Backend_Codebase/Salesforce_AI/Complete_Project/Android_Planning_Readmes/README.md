# YuviPep Android App — Master Plan (Index)

> **Status (updated 2026-08-03): BUILDING — Phases 0–6 and Phase 7 §7.0 are DONE and
> verified on a real device.** This header used to say *"PLANNING — no app code exists yet"*,
> which has been wrong since 2026-07-18. These documents remain the blueprint;
> **`11_PROGRESS_AND_HANDOFF.md` §8-pre6 is the current state of the world** and
> `FINDINGS.md`'s status table is the single source of truth for what is done vs open.
>
> **Where to start if you are new to this project:**
> 1. `11_PROGRESS_AND_HANDOFF.md` **§8-pre6** — state as left, environment, what is next.
>    (Everything below its "FROZEN HISTORY" divider is old and must not be acted on.)
> 2. `FINDINGS.md` — the status table at the top. **F31 (genericity) is the one open
>    finding**; F28, F29 and F30 were all closed on 2026-08-03.
> 3. `10_ROADMAP_MILESTONES.md` — **§7.0b (close F31) is the next work, then §7.1 (money &
>    ops).** F31 lives in the same files §7.1 builds in, which is why it goes first. It spans
>    **backend and app**, so it needs a backend unfreeze *and* an app build.
>
> **Stack decided:** Java 17 · Android Studio · single Gradle project,
> feature-packaged · MVVM · minSdk 26 (Android 8.0) · targetSdk 35.
> App project lives at `C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI`;
> current build **`0.7.2-f30`**.
>
> **Backend:** `Complete_Project/` FastAPI at `/api/v1` (mobile gaps G1–G7 were closed
> server-side on 2026-07-17). **The backend is FROZEN by default** — it is unfrozen only
> when the user names a specific job, and re-frozen when that job is done (it has been
> unfrozen five times: assistant conversation memory, the FINDINGS fix job, Phase 6's
> additive contract fields, Phase 7 §7.0 / F28, and F30+F29 — all complete). See handoff
> §7 rule 5.

---

## The one-line vision

**The salesperson talks; the app handles everything else.** Iron Man never
opened a menu — he spoke, and Jarvis had already done the reading. This app
is that experience for a sales/operations team: every screen can be reached
by tapping, but *everything* can also be done by talking or typing to the
assistant, and the machine only ever pauses to ask a human one thing —
**"approve this?"**

## The three laws of this app (derived from the backend's own design)

1. **The AI does the work; the human approves and edits.** Every
   client-bound artifact (message, proposal, invoice, plan change) arrives
   in the app as a *pending approval card* with a one-tap **Approve** /
   **Reject-with-note**. The app never asks the user to compose from a
   blank page — it asks them to confirm or correct something already made.
2. **Generic, always.** No school words hardcoded anywhere in the app.
   Client roles (`role_at_client`), skills, programs, event types are
   free-vocabulary strings rendered as-is from the backend. The same APK
   serves an ed-tech company, an IT vendor, a catering firm.
3. **Nothing is invisible.** Every AI decision has a "Why?" affordance
   (backend: `GET /why/{entity_type}/{entity_id}`); every plan change has a
   written diff; every send has a delivery log. Trust is a feature.

## Document map (read in order when coding)

| Doc | Contents |
|---|---|
| `01_BACKEND_CONTRACT.md` | **The sync bible.** Every backend endpoint → the screen/feature that consumes it. Feature-coverage matrix proving nothing is missed. Gap ledger G1–G7 — all closed server-side (FCM sender dormant until Firebase keys). |
| `02_ARCHITECTURE.md` | Java/MVVM architecture, package layout, every library with its exact job, networking/auth plumbing, offline cache, error & state handling. |
| `03_SCREENS_NAVIGATION.md` | Every screen from splash onward: wireframe-level descriptions, inputs (voice/text/tap), navigation graph, deep links. |
| `04_JARVIS_ASSISTANT.md` | The assistant-first experience: global mic, conversation UI, context injection, action cards, approvals-as-conversation, "Why?" explainability. |
| `05_ROLE_EXPERIENCES.md` | The six roles, what each sees at home, tab layouts, permission-driven UI rules (mirrors `app/core/permissions.py`). |
| `06_DESIGN_SYSTEM.md` | Theme, typography, color (org-brandable), components, Lottie/motion, empty/loading/error states, accessibility. |
| `07_NOTIFICATIONS_SYNC_OFFLINE.md` | FCM plan (backend sender already built, dormant until Firebase keys), polling fallback, offline queue, idempotency keys, WorkManager jobs. |
| `08_MEDIA_VOICE_PDF.md` | Meeting audio record/upload pipeline, business-card camera scan, PDF view/annotate/re-submit, file downloads. |
| `09_SECURITY.md` | JWT storage, forced password change, biometric unlock, cert pinning, privacy/DPDP touchpoints in the UI. |
| `10_ROADMAP_MILESTONES.md` | Build phases 0–8, acceptance criteria per phase, test plan, and the **credentials I will ask you for** before coding each phase. |

## What the app is, in five screens (elevator tour)

1. **Splash** → brand Lottie, token check, version gate.
2. **Login** (no self-signup — accounts are created by the Org Admin; the
   app explains this politely and supports first-login forced password
   change).
3. **Home (role-shaped)** — the *Morning Briefing*: "Today" digest, the
   **Waiting-on-you** approval feed, overnight replies, and the ever-present
   assistant mic.
4. **The Assistant** — full-screen Jarvis: talk or type; watch it create
   leads, draft proposals, book demos; approve results inline.
5. **The Work** — leads, projects (plan/timeline/health), tasks, demos
   calendar, inbox triage, invoices — every entity screen is also a
   *context* the assistant automatically knows about when opened.

## Non-negotiables carried over from the backend

- **Prices are never typed in the app.** They come from pricing tables and
  locked proposals; the app renders them read-only and routes discount asks
  through the approval chain.
- **Send requires approval.** There is no client-visible action in the app
  that bypasses `pending_approval`.
- **Org isolation is server-enforced**; the app never caches across
  accounts (cache is wiped on logout / account switch).
- **AI failure = honest hold.** When the backend holds work as
  `ai_unavailable` / `needs_human`, the app shows it as a first-class card,
  never a spinner or a silent nothing.

## Phase summary (details in `10_ROADMAP_MILESTONES.md`)

> ⚠️ **This table was renumbered on 2026-07-22** when the Inbox was found to belong to no
> phase (FINDINGS F27) and became Phase 6, pushing everything after it up by one. An older
> copy of this table listing "6 = Ops & money, 7 = Admin, 8 = FCM" was stale and is
> corrected below. **`10_ROADMAP_MILESTONES.md` is authoritative** if these ever disagree.

| Phase | Deliverable | Status |
|---|---|---|
| 0 | Project scaffold, theming, networking core, login + splash | ✅ done 2026-07-18 |
| 1 | Home briefing + notifications list + approvals inbox (read/decide) | ✅ done 2026-07-19 |
| 2 | Leads & contacts (incl. card scan), meetings record/upload/review | ✅ done 2026-07-19 |
| 3 | Assistant v1 (text), proposals view/edit/approve-send, files/PDF | ✅ done 2026-07-20 |
| 4 | Projects: plans, tasks, timeline, conflicts, stakeholders | ✅ done 2026-07-21 |
| 5 | Voice everywhere, demos calendar, follow-ups | ✅ core done 2026-07-21 (neural TTS + shortcuts deferred) |
| 6 | **Inbox & messages**: message centre, delivery trace, inbound triage, reply route, log-client-reply | ✅ done 2026-07-29 |
| 7 | **NEXT** — §7.0 close **F28** (assistant must understand short/ambiguous commands), then money & ops: invoices, payments, vendors, incidents, leave | ⏭ not started |
| 8 | Admin & platform: settings, staff, programs, pricing, audit; Super Admin build flavor | ⏭ not started |
| 9 | FCM push (backend already built & dormant — needs Firebase keys), polish, offline hardening, release | ⏭ not started |

## Beyond-the-obvious backlog (delight items, scheduled into phases)

Small things big apps get right — each already assigned a phase owner:

- **First-run tour** — 4-screen intro of the three laws + a guided first
  command ("try: what am I doing today?"); per-role sample commands. (P3)
- **Share INTO the app** — share a PDF → "attach to proposal/deliverable";
  share text → "log as client reply". Android share-target. (P6)
- **App shortcuts** (long-press icon): Record meeting · Approvals ·
  Ask Jarvis. (P5)
- **Home-screen widget**: approvals-waiting count + today's top 3 tasks,
  tap-through deep links. (P8)
- **Per-app language** (Android 13+) + full localisation scaffolding from
  day one (all strings in resources; Hindi first candidate). (P0 rule)
- **Voice picker & speaking rate** for Jarvis's neural voice; wifi-only
  model download toggle. (P5)
- **In-app "what's new"** after updates; Play in-app-update prompt for
  stale versions. (P8)
- **Demo/portfolio mode** — one tap connects to the seeded dry-run server
  so YOU can demo the app to anyone without touching real data. (P1)
- **Tablet/landscape layouts** for calendar, dashboards, approvals
  triage. (post-launch)
- **Battery & data respect** — poll backoff when idle, wifi-only media
  toggle, data-saver awareness. (P7)
- **Diagnostics screen** — last sync times, queued writes, environment,
  version; "copy support bundle" (no third-party analytics). (P1)
