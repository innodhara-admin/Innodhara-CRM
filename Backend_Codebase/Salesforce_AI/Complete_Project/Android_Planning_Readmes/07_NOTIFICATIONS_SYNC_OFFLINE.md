# 07 — Notifications, Sync & Offline

## 1. Notification sources (server truth)

The backend writes `notifications` rows for everything that concerns a
person (kinds: task_assigned, meeting_processed, approval_waiting,
plan_updated, reminder, escalation, general). Reminder *ladders* also go
out via WhatsApp/email server-side — the app must not duplicate them; it
mirrors the in-app feed and (later) pushes it.

## 2. Until FCM exists (Phases 1–7): polite polling

- Foreground: lifecycle-aware poller hits `GET /notifications` (+
  `/approvals` count) every 60s; diff against Room; new items → in-app
  banner + bell badge; approval items also refresh the Waiting feed.
- Background: WorkManager periodic (15 min, battery/network constraints)
  → local system notifications for **unread** items, grouped per kind,
  deep-linked. Quiet hours respected client-side too (mirror org
  workday settings — the backend already times its own sends).
- Every screen refreshes its scope on resume; pull-to-refresh everywhere.

## 3. FCM (Phase 9 — backend side ALREADY BUILT, needs your Firebase keys)

- Backend (live since 2026-07-17, dormant until `FCM_SERVICE_ACCOUNT_JSON`
  is set): `POST /devices {fcm_token, platform, app_version}` (per user,
  multi-device), `POST /devices/unregister` on logout; `notify()` fans out
  to FCM HTTP v1 alongside the DB row (`app/services/push_service.py`),
  dead tokens auto-pruned.
- App: `FcmService` maps `kind` → channel; channels:
  **Approvals** (high, sound), **Tasks**, **Escalations** (high),
  **Reminders**, **General** (silent). All user-toggleable in Profile.
  Data payload carries deep link; tap-through marks read via
  `/notifications/{id}/read`.
- P1/escalation channel may bypass quiet hours **only** matching the
  org's `quiet_hours_override_priority` policy.

## 4. Offline model

- **Reads:** Room caches per entity with `fetched_at`; screens render
  cache instantly + "updated Xm ago" subtle stamp; stale >24h shows
  refresh nudge. Offline banner global.
- **Writes:** OfflineQueue rows `{method, path, body, idempotency_key,
  entity_hint, created_at, attempts, state}`. Drained FIFO by
  WorkManager on connectivity; UI marks affected cards "queued ☁".
  - Approvals offline: allowed, queued, card shows "will apply when
    online". **Safe — but not because of the idempotency key**, which the
    server never reads (see `01_BACKEND_CONTRACT.md`). A replayed decide is
    refused **409** by `decide_approval`, which allows one decision only.
  - Meeting audio: recorded to app storage first, upload job resumable
    with progress notification; file kept until server 200 + meeting id
    stored.
  - Assistant commands offline: queued with note; reply arrives as a
    notification-style card in the transcript when sent.
- **Conflict honesty:** 4xx on a queued write → card flips to "couldn't
  apply: <backend message>" with view/dismiss; never silent drop.
- Cache wiped on logout/org switch (isolation).

## 5. Data freshness map (what polls when)

| Data | Foreground | Background |
|---|---|---|
| Notifications + approvals count | 60s | 15 min |
| Home briefing | on resume + 30 min | — |
| Meeting pipeline status | 5s while its screen open (status is short-lived) | — |
| Lists (leads/projects/tasks…) | on resume + pull | — |
| Delivery traces | 30s while open | — |

## 6. Diagnostics

Profile → About shows: last successful sync per feed, queued writes count
(with a drain-now button), current environment. Debug builds add request
log viewer (OkHttp interceptor ring buffer).
