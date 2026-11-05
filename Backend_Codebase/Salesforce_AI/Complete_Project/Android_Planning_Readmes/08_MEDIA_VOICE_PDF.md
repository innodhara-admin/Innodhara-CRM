# 08 — Media: Meeting Audio, Card Scan, PDF & Files

## 1. Meeting audio (the flagship input)

**Recording:**
- `MediaRecorder`, AAC in .m4a, 44.1kHz mono 96kbps (speech-optimized,
  ~0.7MB/min → a 60-min meeting ≈ 42MB, well under limits).
- Foreground service + persistent notification (mic-use compliance),
  pause/resume, elapsed timer, amplitude meter; screen-off safe; call
  interruption auto-pauses.
- Storage: app-private `recordings/` until confirmed uploaded (then
  user-configurable keep/delete; default delete after server confirms —
  mirrors backend audio-retention philosophy).
- **Consent gate first** (POST /leads/{id}/consent) — sheet with method
  (verbal/written/in_app) and note; remembered per lead per meeting.

**Upload:**
- WorkManager `UploadMeetingWorker`: multipart to `/meetings/upload`
  with lead/project ids + meeting type; progress in notification;
  resumes on network change (retry with same Idempotency-Key; whole-file
  retry is acceptable at these sizes).
- After 202/200: navigate/deep-link to Pipeline Progress screen; poll
  `GET /meetings/{id}` (5s) through transcribing→extracting→review/done.

**Alternatives:** pick an existing audio file (SAF) — same pipeline;
typed/dictated notes via `/meetings/notes` for no-audio situations.

## 2. Business-card scan

- CameraX capture with card-outline guide + torch toggle; auto-crop
  preview; JPEG ≤2MB re-encode.
- Upload to `/leads/{id}/contacts/from-card`; response contact rendered
  in an editable sheet. `needs_review=true` → amber "verify before any
  message goes out" banner (backend enforces it anyway; the app explains
  it). Card image viewable later (kept as proof, via `/files/...`).

## 3. Voice (summary; full pipeline in 04)

- Commands & dictation: on-device SpeechRecognizer.
- Meetings: recorded audio → backend Whisper. Never mix the two paths.

## 4. PDFs & documents

**Viewing:** proposals (`/proposals/{id}/download`), invoices, weekly
reports, .eml previews (rendered as text headers + body), deliverables —
all fetched through the authenticated file client, cached in app-private
`files/` (LRU 200MB), opened in the in-app PDF viewer (page thumbs,
pinch zoom, night-mode invert). Share/export via FileProvider (user's
explicit action; file leaves the sandbox only then).

**Manual edit & re-submit (your requirement):**
1. Open proposal PDF → "Edit outside" → share to user's editor of
   choice (or download).
2. "Upload edited version" → picks file → `POST
   /proposals/{id}/upload-revision` (**backend G3 — ALREADY LIVE,
   verified incl. tamper refusal**): records a revision, drops status
   back to draft (re-review forced), and verifies the locked total
   inside extractable PDFs — a tampered number is refused with the
   pricing rule spelled out; image-only scans are accepted flagged
   "verify by eye". Then normal review → approve-send flow.

**Other uploads:** task completion artifacts and project deliverables →
`POST /deliverables` (photos from camera or files); incident photos via
the same path, linked from the incident.

## 5. Permissions matrix (runtime, with graceful denials)

| Permission | When asked | Denied behaviour |
|---|---|---|
| RECORD_AUDIO | first record / first mic tap | typed input remains fully functional |
| CAMERA | first card scan / deliverable photo | file picker fallback |
| POST_NOTIFICATIONS (13+) | after first login, with rationale | in-app bell still works |
| None for storage — SAF + app-private only (no legacy WRITE_EXTERNAL) | — | — |

## 6. Media hygiene

- All caches app-private; recordings encrypted-at-rest by FBE (device);
  logout wipes files; no media ever added to public galleries; EXIF
  stripped from uploads.
