# 09 — Security & Privacy (app side)

## 1. Session & credentials

- JWT in `EncryptedSharedPreferences` (Keystore-backed). Never in logs,
  never in crash reports (interceptor scrubs Authorization).
- Login screen never stores the password; "biometric quick unlock"
  stores only the JWT behind a BiometricPrompt gate (device credential
  fallback), re-prompting after 72h or on 401.
- 401 anywhere → token wiped → AuthActivity overlay; queued writes held
  (not dropped) until re-auth (Gap G4 note: proper refresh token later).
- Forced `must_change_password` honored before any other screen.
- Email App Password wizard: value sent once to
  `/auth/email-app-password`, shown never again (server stores
  encrypted); UI treats it like a password field with paste support.

## 2. Transport

- HTTPS enforced in release (`cleartextTrafficPermitted=false`;
  debug allows local http for the dev server).
- Certificate pinning: optional pin set in BuildConfig once a stable
  domain exists (ask me to enable when you have the prod domain);
  pinning failures produce a clear "connection not trusted" screen.

## 3. Data at rest

- Room DB in app-private storage (FBE); no external storage writes;
  logout = DB + files + prefs wipe (org isolation on shared devices).
- Screenshots: allowed generally (sales teams share screens), but
  FLAG_SECURE on: login, app-password wizard, temp-password reveal
  (super admin), audit log.

## 4. Privacy alignment (DPDP — mirrors backend §14)

- Consent sheet before recording (server-recorded, immutable).
- Erase-contact flow (admin) with typed confirmation + explanation of
  scope (DB + files + memory purge server-side).
- Data-minimal analytics: **no third-party analytics SDK in v1**; crash
  reporting only if you approve one later (Firebase Crashlytics
  optional — will ask). Local usage stats only.
- Notification content on lock screen: sensitive marker on approval
  amounts (hidden until unlock), user-configurable.

## 5. Permissions & platform hygiene

- Runtime permissions asked in-context with one-line rationales (08 §5).
- Exported components: none except launcher + deep-link activity with
  verified `yuvipep://` scheme (and later app links on your domain).
- Backups: `android:allowBackup=false` (tokens/DB must not ride
  device-to-device backups).
- Dependency hygiene: only the libraries listed in 02; Renovate-style
  manual review each phase; no SDK that phones home.

## 6. Server-trust principles (respected by the client)

- The app never enforces security *instead of* the server — RBAC hiding
  is UX, the backend check is the lock.
- The app never caches another org's data (single-org token; wipe on
  switch).
- Idempotency keys make retries safe; the app never retries a
  non-idempotent call without one.
