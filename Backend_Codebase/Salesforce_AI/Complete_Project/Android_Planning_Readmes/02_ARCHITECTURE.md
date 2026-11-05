# 02 — App Architecture (Java · MVVM · Android Studio)

## 1. Ground rules

- **Language:** Java 17 (desugaring on for java.time). No Kotlin source.
- **minSdk 26 / targetSdk 35**, AndroidX everywhere, ViewBinding (no
  findViewById, no DataBinding expressions — keep logic in ViewModels).
- **One Activity** (`MainActivity`) hosting Navigation-Component graphs +
  a second `AuthActivity` for splash/login (keeps the back stack honest),
  plus a lightweight `AssistantOverlayActivity` for the global mic sheet.
- **MVVM**: Fragment → ViewModel (LiveData) → Repository → (Retrofit API +
  Room cache). Fragments never touch Retrofit or Room directly.
- **Single source of truth:** Room. Network writes go through repositories
  which update Room; screens observe Room. Lists render instantly from
  cache, refresh in background (stale-while-revalidate).

## 2. Libraries (each with its exact job — no kitchen sink)

| Library | Job |
|---|---|
| **OkHttp 4 + Retrofit 2 + Gson** | HTTP, JSON, auth/idempotency interceptors, file upload/download progress |
| **Hilt** (Java-friendly) | DI: singletons for ApiService, TokenStore, Repos, WorkManager factories |
| **Room** | offline cache: leads, projects, tasks, approvals, notifications, messages, digests, pending-command queue |
| **WorkManager** | reliable background: audio upload, card upload, queued approvals/commands when offline, notification polling |
| **Glide** | logos, card images, avatars (with auth header loader for `/files/...`) |
| **Lottie** | splash brand animation, empty states, listening/thinking mic states, success ticks |
| **Navigation Component (fragment-ktx works with Java)** | nav graphs per role, deep links `yuvipep://approval/{id}` etc. |
| **Material Components 3** | theming, bottom nav, sheets, chips, badges |
| **CameraX** | business-card capture (auto-crop guide overlay) |
| **MediaRecorder / AudioRecord** | meeting recording (AAC .m4a, pause/resume, foreground service) |
| **android.speech.SpeechRecognizer** | on-device STT for assistant commands & dictation into any field (mic icon on every text input via a custom `VoiceEditText`) |
| **sherpa-onnx (k2-fsa/sherpa-onnx, Apache-2.0)** | **neural on-device TTS** for Jarvis's spoken replies — NOT the robotic system TTS. Runs open voices from GitHub/HF: **Kokoro-82M** (hexgrad/Kokoro-82M, Apache-2.0 — remarkably natural) as the primary voice, **Piper VITS** voices (rhasspy/piper, MIT — lighter, many accents) for low-end devices. Voice model downloaded on first "voice replies" enable (~80–160MB pack, kept out of the APK); fully offline afterwards. System `TextToSpeech` remains only as a last-resort fallback. Same library later unlocks offline STT (Zipformer/Whisper) if we ever want dictation without Google services. |
| **AndroidPdfViewer (com.github.mhiew:android-pdf-viewer, PdfRenderer-based fallback)** | inline proposal/invoice PDF viewing |
| **MPAndroidChart** | admin/lead dashboards (pipeline funnel, health, costs) |
| **Firebase Messaging (Phase 9)** | push — backend sender already built (dormant); lights up with the Firebase keys |
| **EncryptedSharedPreferences (security-crypto)** | JWT + app-password flags |
| **LeakCanary (debug)** | leak detection |

## 3. Package layout (feature-packaged, one Gradle module to keep Java builds simple)

```
com.yuvipep.app
├── core/
│   ├── net/        ApiService (Retrofit interface: 136 endpoints, grouped),
│   │               AuthInterceptor, IdempotencyInterceptor, ErrorMapper,
│   │               TokenStore, EnvironmentStore (base URL override)
│   ├── db/         AppDatabase, DAOs, entities, Converters
│   ├── sync/       PollScheduler (WorkManager), DeltaMerger, OfflineQueue
│   ├── voice/      SpeechInput (RecognizerBridge), Dictation, TtsSpeaker
│   ├── ui/         BaseFragment, StateView (loading/empty/error/offline),
│   │               ApproveBar, WhyChip, VoiceEditText, HealthBadge, RoleGate
│   └── util/       Result<T>, AppExecutors, TimeFmt, Money (render-only)
├── feature/
│   ├── auth/       Splash, Login, ForcedPasswordChange, EnvironmentSheet
│   ├── home/       Briefing, WaitingOnYouFeed, QuickActions
│   ├── assistant/  AssistantFragment, ActionCardRenderer, ContextBus
│   ├── approvals/  ApprovalsInbox, ApprovalDetail, AssignmentConfirm
│   ├── leads/      LeadsList, LeadDetail, ContactSheet, CardScan, Consent
│   ├── meetings/   Recorder, NotesComposer, PipelineProgress, ReviewGate
│   ├── projects/   ProjectsList, ProjectHome, PlanTab(+DiffViewer),
│   │               TimelineTab, TeamTab, PeopleTab(stakeholders),
│   │               ConflictResolver, ChainWizard, ReportsTab
│   ├── tasks/      MyTasks, TaskDetail, SplitSheet, VendorWait
│   ├── proposals/  ProposalDetail, EditByInstruction, PdfViewer
│   ├── inbox/      MessageCenter, DeliveryTrace, InboundTriage, LogReply  ✅ built (Phase 6)
│   ├── demos/      DemoCalendar(31-day grid), DemoDetail
│   ├── followups/  FollowUpQueue
│   ├── money/      Invoices, InvoiceDetail, RecordPayment
│   ├── ops/        Incidents, Vendors, Leave, Bookings, Deliverables
│   ├── admin/      Staff, Programs, Pricing, Templates, Teams, Settings,
│   │               Integrations, ApprovalRules, Skills, Playbooks, Audit,
│   │               PrivacyTools
│   ├── platform/   (super_admin flavor) Orgs, PlatformStats
│   └── profile/    Me, Security(app password, biometric), NotificationPrefs
└── notifications/  NotificationCenter, FcmService(Phase 9), Channels
```

## 4. Networking plumbing

- **AuthInterceptor**: injects Bearer; on `401` → clears token → posts a
  `SessionExpired` event → `AuthActivity` on top with "quick unlock"
  (biometric re-login using stored email + prompt for password until G4
  refresh exists).
- **IdempotencyInterceptor**: adds `Idempotency-Key` to POST/PATCH/DELETE;
  key is created *when the user intent is created* (e.g. tapping Approve)
  and stored with the queued call so an offline retry reuses it.
- **ErrorMapper**: backend error envelope → typed `ApiError(code, human
  message, field errors)`; every screen shows the backend's own message
  (they are written for humans) inside `StateView` or a snackbar with
  Retry.
- **Timeouts**: connect 15s; read 120s for `/assistant/command`,
  `/meetings/notes` (LLM latency), 600s upload for `/meetings/upload`
  (progress UI + foreground service). Normal reads 30s.
- **File client**: separate OkHttp client with progress listeners for
  `/files/...` + `/proposals/{id}/download`; Glide wired to it for images.

## 5. Offline & sync model (detailed in 07)

- Reads: Room-first render; background refresh per screen-visible scope.
- Writes: **OfflineQueue** table (endpoint, payload, idempotency key,
  created_at, state). WorkManager drains on connectivity. UI shows queued
  items with a small "waiting for network" cloud badge. Conflicts (409 or
  changed server state) surface as cards, never silent drops.
- Polling cadence (until FCM): notifications+approvals every 60s while app
  foregrounded (lifecycle-aware), 15-min WorkManager sweep in background
  with system-friendly constraints; per-screen refresh on resume.

## 6. State & threading

- `Result<T> = Loading | Success<T> | Error(ApiError)` sealed-by-convention
  class; ViewModels expose `LiveData<Result<T>>`.
- `AppExecutors`: io / db / main. No raw threads in features.
- Long LLM calls (assistant, meeting notes) show *streaming-feeling* UI:
  staged Lottie ("listening → thinking → drafting") driven by optimistic
  timers + real completion, never a frozen spinner (backend has no
  streaming; the UI still narrates).

## 7. Role gating in code

- `RoleGate.require(permission)` mirrors `app/core/permissions.py` matrix
  1:1 (checked in a table in 05 doc). Server remains the enforcer; the app
  only *hides* what a role can't do (and shows a friendly "ask your lead"
  when relevant).
- Navigation graphs assembled at login by role (see 05).

## 8. Build flavors & config

- Flavors: `org` (the normal app) and `platform` (Super Admin console —
  separate launcher, minimal graph). Debug builds add the Environment
  sheet + `/sync/sweep` dev menu.
- `BuildConfig`: BASE_URL default, feature flags (FCM on/off until G1).
- Versioning: semantic, `versionCode = epoch-days`.

## 9. Testing strategy (summary; details in 10)

- Unit: repositories with MockWebServer replaying **real backend response
  JSON captured from the dry-run server** (fixtures generated by a script
  against `LLM_PROVIDER=stub` — keeps app tests as honest as backend's).
- Instrumented: auth flow, approvals flow, recorder lifecycle.
- Contract check: a CI script diffs `ApiService` route list against the
  backend's OpenAPI (`/openapi.json`) so drift fails the build.
