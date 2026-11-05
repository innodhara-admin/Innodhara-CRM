# Jarvis — client creation and voice mode (Android handover)

Written 15 September 2026, from the backend code as built and tested — not
from the proposal (`documentation/jarvis-voice.html`). Where this file and
that proposal differ, this file describes what the server actually does.

For: the Android developer. You also have backend access; section 8 lists
every backend file involved.

**Updated 17 September 2026:** voice mode is live and the Android app
(0.8.0-voice) uses it. Added since the first version: a per-session server
**voice** (§5.2–5.4, §6, §4 `voices`) and the app's avatar voice screen
(§9, which also records what the app learned about the Duix avatar SDK).

**Updated 17 September 2026 (later): speech recognition accuracy.** Measured
on 63 real recordings from the phone and changed accordingly (§10): voice
turns use Whisper `large-v3` (was `turbo`), limited to English/Hindi/Kannada,
with a richer name hint (people, recent clients, cities); Whisper weights are
stored as float16 on the GPU; the shortest accepted utterance is 150 ms (a
short "Yes." was being dropped); and an owner name that only resembles a
colleague ("Ria Nair" → Priya Nair) is now asked about (§2.1). **Live since
the service restart on 17 Sep 2026** (checked: `/voice/config` reports
`large-v3`; a spoken "What are my open tasks today?" was heard exactly, 0.75,
acted on; first turn after the restart 26 s while the model loaded, the next
4.8 s for the whole HTTP turn including the answer; GPU 4.7 GB for the whole
service, down from 5.9 GB).

---

## 0. The short version

Two things were added to the backend. **Nothing existing changed shape**, so
the current app keeps working exactly as it does today.

1. **Jarvis creates a client (lead) by conversation.** The person says
   *"Create a lead named Bal Bhavan Public School"* and Jarvis asks, one thing
   at a time, for what the app's New Lead form holds — owner, then city /
   source / website / notes — reads everything back, and creates it only when
   told to. It works typed or spoken, and already works with the **current
   app, unchanged**, through `POST /assistant/command`.
2. **Voice mode.** A hands-free conversation with Jarvis:
   - `WS /api/v1/assistant/voice` — streaming: the phone streams microphone
     audio, the server detects when the person stops, transcribes, runs the
     same Jarvis, and streams the spoken answer back. Talking over Jarvis
     stops it.
   - `POST /api/v1/assistant/voice/turn` — one recorded clip in, one answer
     out (text + optional spoken WAV). Works through any proxy.
   - `POST /api/v1/assistant/voice/speak` — any text in the server's voice.
   - `GET /api/v1/assistant/voice/config` — what this server supports now.

What the app needs to build: section 3 (client creation polish, small) and
sections 4–6 (voice mode, the real work).

**Deployment status (17 Sep 2026): LIVE.** The service runs this code, Kokoro
is installed, nginx passes WebSockets, and `wss://<ngrok>/api/v1/assistant/voice`
upgrades through the public URL. The voice code (`app/ai/tts.py`,
`app/api/voice.py`, `tests/test_voice_mode.py`, this file) is still
**uncommitted/untracked** in git. See section 1.

---

## 1. Server prerequisites (backend side, before the app can use voice)

| # | Item | Why | Status |
|---|---|---|---|
| 1 | Restart `salesforce-app-restart.service` | Loads the new code. Creates one new table (`assistant_pending_actions`) automatically; no column migrations. | done (last restart 17 Sep 2026, for the speech accuracy changes, §10) |
| 2 | nginx: pass WebSocket upgrades (snippet below) | `/etc/nginx/sites-enabled/salesforce-public` had no `Upgrade`/`Connection` headers, so `wss://…/assistant/voice` failed through the public URL. The HTTP voice endpoints work without this. | done (`conf.d/websocket-upgrade.conf` + the two headers) |
| 3 | `./.venv/bin/pip install kokoro soundfile` | The server voice. Verified additive (no installed version changes). Without it voice mode still works and `spoken_by` is always `device`. It bundles espeak-ng (GPL-3.0) via `espeakng-loader`. | done |
| 4 | Whisper model files in `~/.cache/whisper` | Voice mode uses `large-v3` since 17 Sep (§10); `turbo` is the faster fallback (`VOICE_STT_MODEL=turbo`). Loading large-v3 takes ~22 s, paid by the first voice session after a restart. | done (both files present) |
| 5 | Warm Kokoro once (downloads ~310 MB weights + spaCy `en_core_web_sm`) | First load ~12 s; later ~0.1 s per sentence. | done; all 19 voice files (§5.2) pre-fetched into the HuggingFace cache |
| 6 | Raise `LLM_DEFAULT_ORG_MONTHLY_BUDGET_USD` if voice is used heavily | The proposal estimates ~$1.80/user/month; the default $3.00/org stops Jarvis early for a team. | decision |

nginx snippet (inside the `http {}` context, e.g. a new `conf.d` file):

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

and inside `location / { … }` of `salesforce-public`:

```nginx
proxy_set_header Upgrade    $http_upgrade;
proxy_set_header Connection $connection_upgrade;
```

The existing `proxy_read_timeout 300s` also bounds an idle socket; the app
pings (section 5.3), so that is fine. ngrok passes WebSockets without
configuration.

GPU memory (RTX 3060, 12 GB; the service held 5.9 GB with turbo loaded the
float32 way): Kokoro ~0.7 GB peak. Whisper peaks, measured 17 Sep while
transcribing: `turbo` 3.3 GB as it used to load, 1.85 GB with float16 weights
(`WHISPER_FP16_WEIGHTS=true`, the default now); `large-v3` 3.5 GB with float16
weights. The meeting pipeline's `large` loads only while a meeting is
transcribing and also gets float16 weights. To run voice without the GPU voice
set `VOICE_TTS_ENGINE=off`.

---

## 2. Client creation — how it works on the server

### 2.1 The conversation

The server runs it (`app/ai/client_draft.py`); the AI model only reads the
person's words into values. Word for word, as specified and as tested against
the live model:

```
You:    Create a lead named Bal Bhavan Public School.
Jarvis: Sure. Who should own it? Priya Nair, Rahul Reddy, or you?
You:    Skip this.
Jarvis: The owner is the one who makes the cold calls, so it needs one. Shall I give it to Priya Nair?
You:    Do whatever you want.
Jarvis: Okay, Priya Nair will own it. Do you want to add a city, source, website or notes? They're optional.
You:    Add city as Pune.
Jarvis: Got it, Pune. So: Bal Bhavan Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?
You:    Create it.
Jarvis: Done — Bal Bhavan Public School is added and Priya Nair owns it and has been notified. It starts in cold calling.
```

The order is fixed; a step already answered is skipped ("Create Zenith Motors
in Mysuru, source referral, I'll own it" goes straight to the read-back).

| step | asked | rules |
|---|---|---|
| name | "What is the client called?" | only when no name was given |
| duplicate | "SJBC Tumkur is already on file (open, owned by Rahul Reddy). Do you want to add another one with this name?" | Only when a client of **that same name** is already on file (difflib ≥ 0.88). Asked before the owner, once per name, and again if the name changes. "Add it anyway" carries on; "no" drops the draft. A name that merely resembles one on file is not stopped, only mentioned in the read-back. |
| owner | "Who should own it? Priya Nair, Rahul Reddy, or you?" | Lists up to three other **sales agents**, fewest leads in cold calling first (ties by name), plus "someone else" when there are more, plus "you". The owner can never be left empty. |
| push back | "The owner is the one who makes the cold calls, so it needs one. Shall I give it to Priya Nair?" | On the first skip. The suggestion is the first agent in that list. |
| suggestion taken | "Okay, Priya Nair will own it." | On "yes", "do whatever you want", "you decide", or a second skip. "Someone else" asks again without that person. |
| optional | "Do you want to add a city, source, website or notes? They're optional." | Asked once, naming only what is still empty. |
| read-back | "So: <name> in <city>, owned by <owner>. <Source/Website/Note>. Anything else, or shall I create it?" | Mentions a client with a similar name already on file. New details are acknowledged ("Got it, Pune.") and read back again — never created in the same breath. |
| create | "Done — … It starts in cold calling." | Only on a clear go-ahead ("create it", "yes", "go ahead"). A bare "no" gets "Just to be sure — shall I create X now?"; a second "no" drops it. |

Also, at any point:

- **Cancel** ("cancel", "drop it", "never mind") → "Okay, I've dropped X. Nothing was created."
- **Something else** ("what are my open tasks?") is answered normally, followed by "…and shall I continue with X?". "Yes" re-asks where it left off; "no" drops it.
- **A different client** ("actually create Orbit Labs") replaces the unfinished one: "Sure — that replaces the unfinished X. …".
- **Spelling** ("can you spell the organisation name?") → "Bal Bhavan Public School is spelled B-A-L, B-H-A-V-A-N, P-U-B-L-I-C, S-C-H-O-O-L." followed by the current question. Corrections work in words ("the second word should be Bhawan with a W") or **letter by letter** ("the first word is S H R E E", "the city is P U N E"); the letters are assembled by the server, never guessed, and the new spelling is read back ("Got it — it's now spelled …"). If it cannot tell which word the letters belong to it asks ("Which word should be X-Y-Z — the first, second, third, or fourth?"); a complaint it cannot act on ("the second word is wrong") gets "Sure — spell the second word for me, letter by letter."
- **Voice only — spelling check.** A name, city or contact that was heard by voice with Whisper confidence below 0.8 (`VOICE_SPELL_CHECK_BELOW_CONFIDENCE`) is spelled back once before "create it" is accepted:
  "Before I create it, let me check the spelling. Bal Bhavan Public School is spelled B-A-L, B-H-A-V-A-N, P-U-B-L-I-C, S-C-H-O-O-L. Pune is spelled P-U-N-E. Is that right?"
  "No" → "Which word is wrong? Tell me the word and spell it, letter by letter." Typed input never gets this step.

Creation goes through the **same code as `POST /leads`**
(`lead_service.create_lead`): state `cold_calling`, the history row, the audit
row (`detail.via = "assistant"`), and the owner's `lead_assigned`
notification. A contact person, if mentioned ("we met their principal Anita"),
is saved as the **primary** contact through the same code as
`POST /leads/{id}/contacts`. Contact details are never asked for.

Other rules:

- The unfinished client belongs to **one chat and one user**, expires 10
  minutes after the last reply (`ASSISTANT_CONFIRMATION_TTL_SECONDS`), and is
  forgotten by **`DELETE /assistant/history`** ("new chat").
- **`session_id` is required.** Without one the tool refuses ("only works
  inside an assistant chat"). The app always sends one.
- **Roles:** sales agent, sales lead, org admin may create. Relationship
  managers and operations staff are refused. An owner must be someone who
  works leads; naming anyone else gets "X is an operations agent and can't own
  a client. Who should own it? …". An unknown name gets "I couldn't find anyone
  called X who can own a client. …"; two matches get "Did you mean Priya Nair
  or Priya Shah?".
- **A name that only resembles a colleague is asked about, never used**
  (17 Sep 2026). "Ria Nair" used to become Priya Nair silently ("ria nair"
  sits inside "priya nair"). Now every word said must be a whole word of the
  person's name ("Rahul", "priya nair", "Nair", "Rahul ji" still resolve at
  once); otherwise: "I couldn't find anyone called Ria Nair. Did you mean
  Priya Nair?" (stage `owner_suggested`, chips `Yes` / `Someone else`). A name
  matching nobody but spelled close to one person (difflib ≥ 0.7, e.g.
  "Rahool") gets the same question. The reading model is told to copy the
  owner's name exactly as said.
- If the chosen owner is deactivated before "create it", nothing is created:
  "Priya Nair can no longer own clients, so I haven't created it. Who should
  own it? …".
- Replies may be in English, Hindi or Kannada, or mixed (tested live:
  "Priya ko de do", "ನಗರ ಪುಣೆ", "ಹೌದು, ಮಾಡಿ"). Jarvis always answers in English,
  and names are stored in English letters.

### 2.2 What `POST /assistant/command` returns

Every turn of the conversation is a normal command response whose last action
is a **question card** (`outcome: "needs_confirmation"`), with `candidates`
for one-tap answers and a `details` object holding the client so far:

```json
{
  "agent": "client",
  "reply": "Got it, Pune. So: Bal Bhavan Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?",
  "actions": [{
    "tool": "create_client",
    "args": {"stage": "confirm"},
    "ok": false,
    "outcome": "needs_confirmation",
    "error": "Got it, Pune. So: … shall I create it?",
    "question": "Got it, Pune. So: … shall I create it?",
    "candidates": ["Create it", "Cancel"],
    "details": {
      "kind": "client_draft", "stage": "confirm",
      "name": "Bal Bhavan Public School", "owner": "Priya Nair",
      "city": "Pune", "source": null, "website": null, "notes": null,
      "address": null, "region": null, "contact": null
    }
  }],
  "pending_approvals": [],
  "session_id": "…"
}
```

`details.owner` is `"you"` when the speaker owns it. `details.stage` is one of
`name`, `duplicate`, `owner`, `owner_suggested`, `optional`, `confirm`,
`spell_check`.

Candidates per stage:

| stage | `candidates` |
|---|---|
| `duplicate` | `["Add it anyway", "Cancel"]` |
| `owner` | up to three names, then `"Me"` (or the names from "Did you mean …?") |
| `owner_suggested` | `["Yes", "Someone else"]` |
| `optional` | `["No thanks"]` |
| `confirm` | `["Create it", "Cancel"]` |
| `spell_check` | `["Yes", "No"]` |

After "Create it":

```json
{
  "agent": "client",
  "reply": "Done — Bal Bhavan Public School is added and Priya Nair owns it and has been notified. It starts in cold calling.",
  "actions": [{
    "tool": "create_client",
    "args": {"stage": "confirm", "name": "Bal Bhavan Public School", "owner": "Priya Nair", "city": "Pune", "…": "…"},
    "ok": true,
    "result": {"lead_id": "dcf2…", "name": "Bal Bhavan Public School", "state": "cold_calling", "owner_id": "48c3…", "owner": "Priya Nair", "contact_id": null}
  }],
  "pending_approvals": [],
  "session_id": "…"
}
```

A reply that answers something else mid-way has that agent's own actions, and
its `reply` ends with "…and shall I continue with X?" (no card — a typed or
spoken "yes" continues).

---

## 3. Client creation — what the app should do

It already works: `AssistantFragment` draws `outcome: needs_confirmation` as
the amber question card with chips, and `AssistantEntities` finds
`result.lead_id` and offers the lead. Recommended polish:

1. **Chips send immediately** for cards whose `details.kind == "client_draft"`
   — every chip there is a complete answer ("Me", "Yes", "Someone else", "No
   thanks", "Create it", "Cancel", a name). Today a chip only fills the input
   box.
2. **Show the draft as a live card** from `details` (name, owner, city,
   source, website, notes, and which step it is on), replacing the previous
   card of the same conversation, so the person sees what will be saved.
3. **After an `ok: true` `create_client` action**, refresh the leads list /
   home data and show "Client added → open".
4. **Restored transcripts** (after process death) are bubbles only. The
   conversation is still alive server-side for 10 minutes, so a typed answer
   still works — nothing to build, just don't fake a card.
5. Add *"Create a lead named …"* to the suggested commands for sales roles
   only (the server refuses RM / operations).

---

## 4. Voice mode — choosing a path

Call `GET /api/v1/assistant/voice/config` (bearer auth) when the voice screen
opens:

```json
{
  "enabled": true,
  "protocol_version": 1,
  "stt": {"provider": "whisper_local", "model": "large-v3"},
  "tts": {"engine": "kokoro", "available": true, "sample_rate": 24000, "error": null},
  "stream_input": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1},
  "clip_formats": ["audio/aac", "audio/m4a", "audio/mp4", "audio/mpeg", "audio/ogg", "audio/opus", "audio/wav", "audio/webm"],
  "end_of_turn_silence_ms": 600,
  "max_utterance_seconds": 30,
  "barge_in": true,
  "confirmation_ttl_seconds": 600,
  "voices": ["af_heart", "af_bella", "af_sarah", "…", "am_michael", "am_fenrir", "am_puck", "…"],
  "default_voice": "af_heart"
}
```

`voices` are the server voices a session may choose (Kokoro's American English
set, `tts.VOICES`); `default_voice` is `VOICE_TTS_VOICE`.

- `enabled: false` → hide voice mode (typed Jarvis and `/dictate` still work).
- `tts.available` is `null` until the server has tried to load its voice in
  that process, `true` once loaded, `false` when it cannot (then `error` says
  why). Never block on it: every reply says who speaks it (`spoken_by`).
- **Preferred:** the WebSocket (section 5). **Fallback** when the socket cannot
  connect (proxy without WebSocket support, captive network): the one-clip
  HTTP turn (section 6).
- **Offline:** no voice mode. Keep today's on-device recogniser fallback for
  typed Jarvis.

---

## 5. The WebSocket protocol (`protocol_version` 1)

### 5.1 Connecting

```
wss://<host>/api/v1/assistant/voice
Authorization: Bearer <access token>
```

Build the URL from `EnvironmentStore`'s current base URL (`https` → `wss`).
OkHttp's `newWebSocket` with the app's client carries the auth header; if the
header cannot be set, put `"token"` in the start message instead. A bad token
is refused after the start message, not at the handshake.

Text frames are JSON. Binary frames are audio. The server sends nothing until
it receives the start message, which must arrive within 15 s.

### 5.2 Start message (first frame, client → server)

```json
{
  "type": "start",
  "session_id": "<AssistantSession's id>",
  "format": "pcm_s16le",
  "sample_rate": 16000,
  "vad": "server",
  "server_voice": true,
  "barge_in": true,
  "lead_id": "<optional, from ContextBus>",
  "proposal_id": null,
  "meeting_id": null,
  "voice": "af_bella",
  "token": "<only if you could not send the Authorization header>"
}
```

| field | required | meaning |
|---|---|---|
| `session_id` | yes | 8–64 of `A-Za-z0-9_-`. **Use the same id as typed Jarvis** (`AssistantSession`), so voice and typed turns are one conversation and history restores both. |
| `format` | no (`pcm_s16le`) | `pcm_s16le` = raw 16-bit little-endian mono PCM at 16 kHz, streamed. Or one of `clip_formats` (e.g. `audio/mp4`) sent as a whole clip — then the server cannot detect end of speech and the app must send `end_of_speech`. |
| `sample_rate` | no | must be `16000` for PCM. |
| `vad` | no (`server`) | `server`: the server ends the turn after 600 ms of silence. `client`: only the app's `end_of_speech` ends a turn (push-to-talk). |
| `server_voice` | no (`true`) | `false`: never send audio, the app speaks `speech` itself. |
| `barge_in` | no (`true`) | `false` on phones without working echo cancellation (see 5.7). |
| `lead_id` / `proposal_id` / `meeting_id` | no | screen context, as `/assistant/command` takes it. Update later with a `context` message. |
| `voice` | no (default voice) | one of `/config` `voices`; the server voice for this session. Unknown values fall back to the default silently; `ready.voice` says which is in use. Change later with a `voice` message. |

### 5.3 Client → server

| message | when |
|---|---|
| **binary frame** | Microphone audio. For PCM send 20 ms frames (640 bytes); any size works, the server re-frames. Keep streaming while Jarvis speaks if `barge_in` is on. |
| `{"type":"end_of_speech"}` | The person stopped (push-to-talk release, or your own detector). Required for clip formats and `vad: client`; optional with server VAD. |
| `{"type":"cancel"}` | Throw away the audio of the utterance in progress. |
| `{"type":"text","text":"Me"}` | A typed turn in the same session — use it for question-card chips during voice mode. |
| `{"type":"interrupt"}` | Stop Jarvis speaking (e.g. a stop button). Does not undo anything already done. |
| `{"type":"context","lead_id":"…","proposal_id":null,"meeting_id":null}` | The screen changed. Replaces the whole context. Echoed back. |
| `{"type":"voice","voice":"am_puck"}` | Speak with another server voice from the next sentence on (the app's avatar picker). Answered with `{"type":"voice","voice":…}`; an unknown voice gets non-fatal error `bad_voice` and the current voice stays. `"voice": null` returns to the default. |
| `{"type":"ping"}` | Keep-alive; answered with `pong`. Send every ~20 s. |
| `{"type":"stop"}` | End the session; the server closes with 1000. |

### 5.4 Server → client

Every turn carries `"turn": n` (1, 2, 3 … in the order turns are processed).

| message | meaning / what the app does |
|---|---|
| `ready` | Session open. Shows the input settings, `server_voice` status and limits. Start the mic. |
| `server_voice` | `{"engine","available","sample_rate","error","ready"}` — the server's voice finished loading (or failed). |
| `speech_started` | Server heard speech begin. **Stop local playback now** and show "listening". |
| `speech_ended` | `{"seconds": 1.9}` — utterance captured, turn queued. |
| `listening` | Nothing usable was heard (a blip, or an empty transcript). Back to idle. |
| `transcribing` | Transcription started. |
| `transcript` | `{"text","language","confidence","low_confidence"}` — show the words as the user bubble. |
| `thinking` | `{"agent":"client","text":"Getting that client ready."}` — Jarvis chose who handles it; a fixed acknowledgement. Not sent for replies inside the client conversation (they are answered without routing). If the server voice is not in use, you may speak it with `TtsSpeaker`. |
| `reply` | The answer (5.5). Render exactly like a `/assistant/command` response. |
| `speak_start` | `{"kind":"ack"\|"reply"\|"error","text","format":"pcm_s16le","sample_rate":24000}` — audio for this text follows as binary frames. |
| **binary frame** | 24 kHz mono s16le PCM, ~100 ms per frame, sent faster than real time. Queue into an `AudioTrack`. |
| `speak_end` | `{"kind","interrupted":bool}` — no more audio for that `speak_start`. |
| `interrupted` | `{"reason":"barge_in"\|"client"\|"new_request"}` — the server stopped mid-speech. Flush what you buffered. |
| `context` | Echo of a `context` message. |
| `pong` | Reply to `ping`. |
| `error` | `{"code","message","fatal"}`. `fatal: true` is followed by a close. |

JSON messages can arrive between the binary frames of a `speak_start`; binary
frames always belong to the most recent `speak_start` without a `speak_end`.

### 5.5 The `reply` message

```json
{
  "type": "reply",
  "turn": 4,
  "spoken_by": "server",
  "acted": true,
  "transcript": "Add city as Pune.",
  "agent": "client",
  "reply": "Got it, Pune. So: Bal Bhavan Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?",
  "speech": "Got it, Pune. So: Bal Bhavan Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?",
  "actions": [ … same as /assistant/command, including the client card's details … ],
  "pending_approvals": [ … same as /assistant/command … ],
  "session_id": "…"
}
```

- `agent`, `reply`, `actions`, `pending_approvals`, `session_id` are the
  **exact** `/assistant/command` fields — reuse `ChatAdapter`, question
  cards, approval bars and the Why chip.
- `speech` is the reply made speakable: markdown and links removed, long
  answers cut at a sentence with *"The rest is on your screen."* Spellings are
  spoken letter by letter ("B-A-L, B-H-A-V-A-N" — measured with Kokoro).
- `spoken_by: "server"` → audio follows (`speak_start kind=reply`).
  `spoken_by: "device"` → speak `speech` with `TtsSpeaker` (the server has no
  voice, the session asked for none, or a newer request is already queued).
- `acted: false` → Jarvis did **not** act: the transcript was too uncertain.
  `reply` says what was heard and asks again (`agent` is `"voice"`). Show the
  transcript so the person can edit and send it as `text`.
- `transcript` is `null` for `text` turns.

### 5.6 Close codes and errors

| close code | cause |
|---|---|
| 1000 | normal (`stop`, or session ended) |
| 1011 | unexpected server error |
| 4400 | bad start (`no_start`, `bad_start`, `bad_session`, `bad_format`) |
| 4401 | `unauthorized` — token missing/expired/invalid, or account deactivated (re-checked on **every** turn). Refresh the login, reconnect. |
| 4403 | `forbidden` (super admin, inactive org) or `disabled` (voice switched off) |
| 4408 | `idle` — no message for `VOICE_IDLE_TIMEOUT_SECONDS` (300 s) |

Non-fatal `error` codes: `too_long`, `bad_message`, `bad_text`,
`unknown_message`, `bad_voice`, and per turn `budget_exceeded` (org AI budget spent),
`forbidden`, `invalid`, `service_unavailable`, `internal`.

Reconnect with backoff on network loss; reuse the same `session_id` — the
conversation (and an unfinished client) survives.

### 5.7 Audio on Android — guidance

- **Capture:** `AudioRecord` with `MediaRecorder.AudioSource.VOICE_COMMUNICATION`,
  16000 Hz, `CHANNEL_IN_MONO`, `ENCODING_PCM_16BIT`; read 640-byte (20 ms)
  buffers and send each as a binary frame. Enable `AcousticEchoCanceler` and
  `NoiseSuppressor` when `isAvailable()`.
- **Playback:** `AudioTrack` (`USAGE_ASSISTANT` or `USAGE_VOICE_COMMUNICATION`),
  24000 Hz mono 16-bit, streaming mode. On `speech_started` or `interrupted`:
  `pause()` + `flush()` immediately.
- **No working echo canceller** (varies by handset; also check car Bluetooth):
  start with `"barge_in": false` and **do not send mic audio while playing**
  (resume after `speak_end`). Otherwise the server hears Jarvis as a request.
- **Bandwidth:** raw PCM is 256 kbit/s up while the mic is open. If too heavy,
  use push-to-talk with a clip format (`"format": "audio/mp4"`,
  `vad: "client"`, then `end_of_speech`).
- **Mic conflicts:** not while `RecorderService` records a meeting. Stop
  listening when the screen goes to background.
- Needs `RECORD_AUDIO`, which the app already requests.

### 5.8 A spoken session, as it ran (scratch server, 15 Sep 2026)

Real Kokoro voice for the person, real Whisper `large-v3`, real model:

```
→ "Create a lead named Bal Bhavan Public School."
← transcript "Create a lead named Bal Bavin Public School." (0.73)     ← misheard
← reply "Sure. Who should own it? Priya Nair, Rahul Reddy, or you?"
→ "Skip this."             ← reply "The owner is the one who makes the cold calls, so it needs one. Shall I give it to Priya Nair?"
→ "Do whatever you want."  ← reply "Okay, Priya Nair will own it. Do you want to add a city, source, website or notes? They're optional."
→ "Add city as Pune."      ← transcript "Ad City is Pune." (0.77)
                           ← reply "Got it, Pune. So: Bal Bavin Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?"
→ "The second word is B-H-A-V-A-N."
                           ← reply "Got it, Bal Bhavan Public School. So: Bal Bhavan Public School in Pune, owned by Priya Nair. Anything else, or shall I create it?"
→ "Create it."             ← reply "Before I create it, let me check the spelling. Bal Bhavan Public School is spelled B-A-L, B-H-A-V-A-N, P-U-B-L-I-C, S-C-H-O-O-L. Pune is spelled P-U-N-E. Is that right?"
→ "Yes."                   ← reply "Done — Bal Bhavan Public School is added and Priya Nair owns it and has been notified. It starts in cold calling."
```

Saved: "Bal Bhavan Public School", Pune, owner Priya Nair, cold calling.

---

## 6. The HTTP endpoints

### 6.1 `POST /api/v1/assistant/voice/turn` — one clip, one answer

`multipart/form-data`, bearer auth:

| field | required | |
|---|---|---|
| `file` | yes | the recorded utterance, any `clip_formats` type (the app's current AAC/m4a from `SpeechInput` is fine), ≤ 10 MB |
| `session_id` | yes | same rules as the WebSocket |
| `lead_id`, `proposal_id`, `meeting_id` | no | screen context |
| `speak` | no (`true`) | `false` = no audio in the response |
| `voice` | no | one of `/config` `voices` for the spoken answer; anything else = default voice |

Response (200):

```json
{
  "transcript": "No thanks.",
  "language": "en",
  "confidence": 0.81,
  "low_confidence": false,
  "acted": true,
  "agent": "client",
  "reply": "Okay. So: Voiced Co in Hubli, owned by you. Anything else, or shall I create it?",
  "speech": "Okay. So: Voiced Co in Hubli, owned by you. Anything else, or shall I create it?",
  "actions": [ … ],
  "pending_approvals": [ … ],
  "session_id": "…",
  "audio": {"format": "wav", "sample_rate": 24000, "base64": "UklGR…"},
  "spoken_by": "server"
}
```

`audio` is `null` (and `spoken_by` `"device"`) when the server has no voice or
`speak=false`. Same `acted: false` rule as 5.5. Errors are the usual
`{"detail": "…"}` (401, 422, 429 budget, 502 speech service, 503 voice off).

### 6.2 `POST /api/v1/assistant/voice/speak`

`{"text": "…", "voice": "af_bella"}` (text 1–2000 chars; `voice` optional,
unknown = default) → `audio/wav` (24 kHz mono). 503 with a `detail` when the
server has no voice. The app uses it for each avatar's voice sample.

### 6.3 `GET /api/v1/assistant/voice/config` — section 4.

---

## 7. Safety rules, measured behaviour and known limits

### 7.1 Rules the server enforces (the app must not work around them)

- **Nothing client-visible is sent by voice.** Emails, WhatsApp messages and
  proposals still land in approvals; voice cannot approve.
- **A low-confidence transcript is never acted on** (`acted: false`) — Whisper
  confidence < 0.6, the same gate as meeting review and `/dictate`.
  Exception: **while a client is being built up in that chat**, a reply down
  to 0.4 (`VOICE_CONFIRMATION_MIN_CONFIDENCE`) is accepted, because Whisper
  scores short replies low however clearly they are said ("Yes." 0.49–0.52 on
  large-v3) and nothing is created before the full read-back and a go-ahead.
- **A client is created only on a clear go-ahead to the read-back**, and a
  name/city/contact heard with doubt (< 0.8) is **spelled back first**.
- **Whisper is told the names to expect** for each voice turn
  (`client_draft.vocabulary_hint`): `"<people who can own a lead>. Clients:
  <20 most recently active clients>. Cities: <the org's client cities, then a
  fixed list of 20 Indian cities>."` Without the people, "Asha Rao" was "a
  show-row"; the clients and cities took names heard right from 66% to 82%
  (§10). Whisper keeps only the last ~223 tokens of a hint, so
  `stt._fit_prompt` cuts an over-long one from the end (cities go first,
  people last). The unfinished client's own name is deliberately not
  included, so a spoken correction is not pulled back to the mistake.
- **Languages are limited to English, Hindi and Kannada**
  (`VOICE_STT_LANGUAGES`): detection picks the likeliest of those. Without
  it large-v3 writes Hindi in Urdu script and loses names.
- **Voice audio is not stored.** Transcribed and discarded; the transcript is
  stored as a conversation turn, as typed text is.
- Replies are **always English**; the person may speak English, Hindi,
  Kannada or a mix.

### 7.2 Measured (15 Sep 2026)

Real model (`openai/gpt-5.4-nano`), typed, 8 scenarios on a scratch server —
the specified dialogue word for word; spell + correct in words; correct letter
by letter; an unrelated question mid-way and continuing; Hindi and Kannada
replies; a change at the last step; "you pick someone"; "the second word is
wrong" → letters. All behaved as specified.

Spoken end to end (section 5.8) with Whisper `large-v3` **on CPU** (to keep the
live service's GPU free): ~9–13 s per turn, first turn ~28 s (model load). Not
representative of production; earlier on the GPU with `tiny`: transcript
0.4–0.6 s after the end of speech, spoken acknowledgement ~2.0 s, answer
~4.6 s. Replies inside the client conversation that match a fixed phrase
("skip this", "create it", "me", a colleague's name, letters) need no model
call at all.

Whisper confidence on clean synthetic speech (CPU):

| said | tiny | large-v3 |
|---|---|---|
| "Yes." | 0.52 | 0.49–0.52 |
| "No." | 0.47–0.55 (once "Now.") | 0.51–0.55 (once "Now.") |
| "Okay." | 0.56–0.66 | 0.44–0.48 |
| "Yes, go ahead." | 0.63 | 0.80–0.82 |
| a full "Add a new client …" sentence | 0.56–0.64 | 0.81–0.82 |

### 7.3 Known limits

- **Names are still sometimes misheard**: 82% exactly right on real speech
  (§10). Many of the rest cannot be told apart by sound at all ("Ria"/"Rhea",
  "Shree"/"Shri", "Ramaiah"/"Ramayya"). The spelling check, letter-by-letter
  correction and the owner "Did you mean …?" are the defence; show the live
  draft card prominently too.
- **Kannada/Hindi speech:** understood, but proper names in those languages are
  the hardest case. Hindi comes back in Devanagari ("प्रिया को दे दो"); the
  reading model writes names in English letters. Earlier measurements recorded in the backend `.env`: Whisper
  `tiny` 6–12% accurate on spoken Kannada, `large` 88–94%. Use `turbo` or
  `large-v3` for voice mode — never `tiny`.
- The server's voice is **English only** (Kokoro).
- **A proposal or MOU being filled in the same chat owns every turn** (existing
  rule D48). Finish the fill or start a new chat before adding a client.
- Jarvis can create a client; **editing an existing client, moving its stage,
  and adding a contact to an existing client are not assistant actions yet**.
- Transcripts are **text only** in history: a restored chat has bubbles, not
  cards.
- `/dictate` is unchanged and still uses Whisper `tiny`.

---

## 8. Backend changes (for whoever touches the server)

| file | change |
|---|---|
| `app/ai/client_draft.py` | **new** — the client conversation: stages, owner suggestion, spelling and letter corrections, voice spelling check, Whisper name hints, creation |
| `app/ai/agents/client_agent.py` | **new** — the client agent: `create_client` (starts the conversation), `list_possible_owners`, `find_existing_clients` |
| `app/ai/confirmations.py` | **new** — conversations held open between turns (`assistant_pending_actions`), the flow registry, `classify_reply` |
| `app/ai/orchestrator.py` | registers `client`; router prompt line; gives a held conversation the message first, pauses it for other requests and offers to continue; `on_routed` callback |
| `app/ai/agents/base.py` | `AgentResult.speech`; question cards carry `details`; context keys starting `_` never reach a prompt |
| `app/ai/conversation.py` | "new chat" also forgets an unfinished client |
| `app/ai/voice.py` | **new** — end-of-turn detector, speakable text, acknowledgements |
| `app/ai/tts.py` | **new** — Kokoro engine switch, WAV helper; `VOICES` + `resolve_voice`, `synthesize(text, voice=)` (a voice that fails falls back to the default) |
| `app/ai/stt.py` | `transcribe_pcm16` (raw PCM), optional vocabulary `prompt`, `warm`; 17 Sep: float16 weights on a GPU (`_halve_weights`), `languages` limit (`_pick_language`), over-long hints cut from the end (`_fit_prompt`) |
| `app/ai/client_draft.py` (17 Sep) | owner near-miss confirmation (`_said_in_full`, `_sounding_like`, `_did_you_mean`); richer `vocabulary_hint` (people, recent clients, cities) |
| `app/ai/voice.py` (17 Sep) | `stt_languages()`; both transcribe paths pass the allowed languages |
| `app/api/voice.py` | **new** — the four voice endpoints and the WebSocket session; per-session `voice` (start field, `voice` message, `/turn` form field, `/speak` body, `/config` `voices`/`default_voice`) |
| `app/api/deps.py` | `org_context_for_token` (same checks as HTTP auth, for the socket) |
| `app/api/leads.py`, `app/services/lead_service.py` | lead + contact creation moved into `lead_service.create_lead` / `add_contact`, shared by the endpoints and Jarvis; endpoint behaviour unchanged |
| `app/core/exceptions.py` | `NeedsConfirmationError(details=…)` |
| `app/models/assistant.py`, `app/models/__init__.py` | **new table** `assistant_pending_actions` |
| `app/core/reset_taxonomy.py`, `tests/test_reset_taxonomy.py` | the table joins WIPE (4/2/8/48, 62 tables) |
| `app/config.py`, `.env.example`, `requirements.txt` | voice and conversation settings; optional Kokoro packages (commented) |
| `app/main.py` | mounts the voice router |
| `tests/test_client_creation.py`, `tests/test_voice_mode.py` | **new** — ~100 tests: the dialogue word for word and every branch; end of turn; HTTP and WebSocket sessions in-process; per-session voices (4 tests, 17 Sep) |

Test suite: before the change 5 failed / 1053 passed; after, 5 failed /
1140+ passed (17 Sep 2026, with per-session voices: 5 failed / 1151 passed;
`tests/test_voice_mode.py` 36 passed; after the speech accuracy work, later on 17 Sep:
baseline 1 failed / 1155 passed → 1 failed / 1169 passed, `test_voice_mode.py` 43,
`test_client_creation.py` 69) — the same date-sensitive tests (`test_what_is_late` ×3,
`test_demos_followups`, `test_relationship_screens`), which fail when the
server's UTC day differs from Asia/Kolkata's (SESSION_HANDOFF rule 11).

Settings (all optional, defaults shown): `ASSISTANT_CONFIRMATION_TTL_SECONDS=600`,
`VOICE_MODE_ENABLED=true`, `VOICE_STT_MODEL=large-v3`, `VOICE_STT_LANGUAGES=en,hi,kn`,
`WHISPER_FP16_WEIGHTS=true`, `VOICE_TTS_ENGINE=kokoro`,
`VOICE_TTS_VOICE=af_heart`, `VOICE_TTS_LANG_CODE=a`, `VOICE_TTS_SPEED=1.0`,
`VOICE_TTS_DEVICE=cuda`, `VOICE_VAD_SILENCE_MS=600`,
`VOICE_MIN_UTTERANCE_MS=150` (was 300), `VOICE_MAX_UTTERANCE_SECONDS=30`,
`VOICE_IDLE_TIMEOUT_SECONDS=300`, `VOICE_BARGE_IN=true`,
`VOICE_CONFIRMATION_MIN_CONFIDENCE=0.4`,
`VOICE_SPELL_CHECK_BELOW_CONFIDENCE=0.8`.

### Trying it without the app

```bash
TOKEN=…   # POST /api/v1/auth/login
curl -H "Authorization: Bearer $TOKEN" https://<host>/api/v1/assistant/voice/config
curl -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"text":"Create a lead named Bal Bhavan Public School.","session_id":"trysession0001"}' \
     https://<host>/api/v1/assistant/command
curl -H "Authorization: Bearer $TOKEN" -F session_id=trysession0001 \
     -F file=@reply.m4a https://<host>/api/v1/assistant/voice/turn
```

---

## 9. The Android app as built (0.8.0-voice, 17 Sep 2026)

Android repo: `C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI`
(no git). Code: `app/src/main/java/com/yuvipep/app/feature/assistant/voice/`
and `core/voice/`.

### 9.1 What the person sees

- The **sound-bars button** in the Jarvis header opens the **voice screen**
  (`VoiceStageDialog`, a full-screen child dialog of `AssistantFragment`,
  which owns the session, transcript, cards and approvals). Closing the screen
  ends voice mode; every turn is in the chat afterwards.
- Top: a talking **avatar** (Duix Mobile SDK, lip-synced to Jarvis's server
  voice). Swipe (or the arrows) to change face **and voice**; dots show the
  position; the choice is remembered. Order: **Ethan, Sofia, Oliver, Lily,
  Leo, Aixia** (`AvatarCatalog.ALL`).
- Under it: live captions (YOU / JARVIS), then the conversation with the same
  cards as the chat (client-draft chips send on tap; approvals work), then
  keyboard / mic (mute, stop, resume) / end-call buttons.
- A face not on the phone shows its picture, says a sample line in its own
  voice (`POST /voice/speak`, cached on the phone) and offers
  **Download · N MB**. ⋮ menu: voice only (no faces), delete this face,
  talk-over-Jarvis (only without a live avatar).

| avatar | model zip | size | server voice | look |
|---|---|---|---|---|
| Ethan (m) | v1.0.0/`bendi3_20240518.zip` | 178 MB | `am_michael` | cut-out; small "DUIX.AI" mark bottom-right |
| Sofia (f) | v2.0.1/`Sofia.zip` | 30 MB | `af_sarah` | video-call frame; "duix.com" watermark |
| Oliver (m) | v2.0.1/`Oliver.zip` | 30 MB | `am_fenrir` | video-call frame; watermark |
| Lily (f) | v2.0.1/`Lily.zip` | 34 MB | `af_bella` | video-call frame; watermark |
| Leo (m) | v2.0.1/`Leo.zip` | 26 MB | `am_puck` | video-call frame; watermark |
| Aixia (f) | v1.0.0/`aixia_2026_08_21.zip` | 217 MB | `af_heart` | cut-out |

Plus a shared base pack `v1.0.0/gj_dh_res.zip` (133 MB) with the first face.
All from github.com/duixcom/Duix-Mobile releases, downloaded at runtime into
the app's external files (`files/duix/model/<zip name>`).

### 9.2 The Duix SDK — facts that cost time

- It is **not 3D**: a pre-recorded clip (encrypted frames) looped, with the
  mouth regenerated on-device from the audio. Only models with a `pha` +
  `raw_sg` folder (bendi3, aixia) have transparency; the rest are full frames.
- Built from `C:\Users\Ekaghni\AndroidStudioProjects\LinguaAI\duix-sdk`
  (`:duix-sdk:assembleRelease`) into `app/libs/duix-sdk-4.1.1.aar`
  (arm64-v8a, armeabi-v7a only; +~45 MB APK).
- It plays the audio itself: 16 kHz PCM via `startPush/pushPcm/stopPush`, on
  STREAM_MUSIC (so no echo cancellation → the mic stays shut while an avatar
  speaks). The app resamples the server's 24 kHz (`PcmResampler`), queues
  utterances (a new `startPush` replaces the playing one), pads to ≥ 1 s, and
  has a watchdog because `stopAudio()` and a never-started clip fire no
  play-end (`AvatarSpeechOutput`).
- **Two Duix instances must never overlap.** The native lib keeps one global
  slot (task 0); a render thread shutting down frees it and a new avatar
  started meanwhile crashes the app (SIGSEGV in `dhduix_free`). `JarvisAvatar`
  waits for any `DUIXRender-Thread` to exit first.
- A `DUIXTextureView` must get its renderer before it has a surface (else an
  NPE on first draw), and takes one renderer per view — the app creates the
  view in code per load. Its native library loads inside Duix's render thread,
  so the app test-loads it first (`JarvisAvatar.deviceSupported`).
- Licence (duix.com Community License): "Powered by Duix.com" must appear in
  a UI **or product documentation** (it is in the Android README), the notice
  ships in `assets/licenses/`, and **>1,000 MAU needs a commercial licence**.

### 9.3 Measured on the phone (Vivo V2514, arm64)

- Spoken turn: end of speech → reply ≈ 3.4 s; replies inside the client
  conversation ≈ 0.1 s. The server sends reply audio far faster than real
  time (25 s of speech in ~0.5 s) — the app times the mic from its own
  playback, not from `speak_end`.
- `POST /voice/speak`: ~0.5 s per sample once Kokoro is warm; 5 s on the
  first call after a restart.
- 12 avatar switches in 20 s: no crash (after the render-thread gate).

### 9.4 Known open points

- ~~Speech is sometimes misheard~~ — measured and improved, see §10. The
  "Ria Nair" → "Priya Nair" owner substitution is now a question (§2.1).
- Voice audio and the draft card are English only (Kokoro English voices).
- Debug builds have a **Speech test recorder** (voice screen ⋮ menu,
  `SpeechEvalDialog`, `SpeechEvalPrompts`), used for §10. `MicStreamer` takes
  a `CaptureMode` (`COMMUNICATION` — what voice mode uses —,
  `COMMUNICATION_NO_NS`, `RECOGNITION`); only `COMMUNICATION` has been measured.

---

## 10. Speech recognition accuracy (measured 17 Sep 2026)

### 10.1 How it was measured

- **Recordings:** 63 sentences read on the Vivo V2514 through the debug app's
  Speech test recorder, with voice mode's own microphone settings
  (`VOICE_COMMUNICATION` + echo canceller + noise suppressor), raw 16 kHz,
  silence included. Categories: creating a client with Indian school/company
  names and cities (15), owner names (9), details (9), short replies (14),
  spelling (5), everyday requests (6), Hindi/Kannada mixes (5). Names to score
  are bracketed in `SpeechEvalPrompts.java`. One speaker — treat differences
  of a few points as noise (±5 on 50 names).
- **Replay:** each recording goes through the server's own
  `EndOfTurnDetector` (as the WebSocket would cut it), then one Whisper
  configuration. Scored: word error rate (normalised; Hindi/Kannada excluded),
  **names heard exactly right** (official/common spelling pairs such as
  Mysuru/Mysore count; "Bavin" for "Bhavan" does not), short replies, the
  0.6 gate, speech-to-text seconds per turn (p50), GPU peak.
- **Where:** `/home/telaverge/Ekaghni/stt_eval/` on the VM, outside the repo
  (`stt_eval.py segment|transcribe|score`, `run_suite.sh`, a separate
  `fwvenv` for faster-whisper). Voice audio is still never stored by the
  server; the test recordings were opt-in and deleted after the evaluation.
  A computer-voice (Kokoro) set was used only to test the harness — Kokoro
  mispronounces Indian names, so its numbers were not used for decisions.

### 10.2 Results on the real recordings

"Hint" = the people names (as before); "richer hint" = people + 20 client
names + 20 cities (§7.1).

| configuration | word errors | names right | cities | clients | people | Hindi | s / turn | GPU |
|---|---|---|---|---|---|---|---|---|
| turbo, hint — **as it was** | 8.9% | 66% | 11/16 | 13/20 | 5/10 | ok | 0.36 | 3.3 GB |
| turbo, no hint | 13.1% | 64% | 11/16 | 13/20 | 4/10 | poor | 0.33 | — |
| turbo, beam search 5 | 9.2% | 68% | 11/16 | 13/20 | 6/10 | ok | 0.41 | 1.9 GB |
| turbo, richer hint | 6.5% | 74% | 13/16 | 15/20 | 6/10 | ok | 0.32 | 1.9 GB |
| large-v3, hint | 7.4% | 76% | 13/16 | 13/20 | 9/10 | **Urdu script** | 0.55 | 3.5 GB |
| large-v3, beam search 5 | 7.7% | 74% | 12/16 | 13/20 | 9/10 | poor | 0.93 | 3.5 GB |
| **large-v3, richer hint, en/hi/kn — now** | **6.5%** | **82%** | 15/16 | 15/20 | 8/10 | ok (Devanagari) | 0.56 | 3.5 GB |
| faster-whisper large-v3, beam 5, hint + cities, en/hi/kn | 6.0% | 84% | 16/16 | 13/20 | 10/10 | ok | 0.73 | 3.9 GB |
| faster-whisper large-v3, beam 5, int8 | 11.3% | 72% | 12/16 | 13/20 | 8/10 | poor | 0.62 | 2.0 GB |

The production code path (`stt._whisper_transcribe_pcm_sync` with the new
settings) was run over the same recordings and gave exactly the chosen row:
6.5%, 82%, 0.56 s, 3.5 GB.

### 10.3 What was learned

1. **The hint and the model matter; decoding tricks do not.** Beam search and
   faster-whisper moved names by one or two out of 50 at +0.1–0.6 s. The
   richer hint (+8 names on turbo) and large-v3 (+4 more, mostly people) did
   the work.
2. **large-v3 writes Hindi in Urdu script** ("Priya ko de do" →
   "فریہ کو دے دو", the name lost). Limiting detection to en/hi/kn fixes it
   (`प्रिया को दे दो`). turbo does not need the limit, and forcing Hindi on
   turbo made it worse.
3. **A short "Yes." was dropped before Whisper.** With the phone's noise
   suppressor the silence is digital zero and "Yes." holds only 280 ms of
   sound; `VOICE_MIN_UTTERANCE_MS=300` threw it away as noise. 150 ms keeps
   it, and no recording produced a false turn.
4. **float16 weights change nothing but memory**: 252 of 252 identical
   transcripts, turbo 3.3 → 1.85 GB — which is what lets large-v3 fit in about
   today's memory.
5. **The retry sampling (temperature fallback) is random.** On a computer-voice
   "Me." one run returned a line of multilingual nonsense. It did not change
   the real-recording scores, so it was left on; comparisons were seeded.
6. **faster-whisper's confidence is on a different scale** (short replies
   0.7–0.85 vs 0.45–0.55): switching engine would need the 0.4/0.6/0.8 gates
   re-measured. Not adopted.
7. **What is left is mostly unhearable**: of the 9 names large-v3 still misses,
   most are spellings speech cannot carry ("Rhea"/"Ria", "Shri"/"Shree",
   "Ramayya"/"Ramaiah", "Hubbali", "Vidyaniketan"). The spelling check and the
   owner "Did you mean …?" handle those.

### 10.4 Cost

- ~0.2 s more per spoken turn (speech-to-text 0.36 → 0.56 s; the whole turn
  was ≈ 3.4 s).
- GPU about the same as before (3.3 GB → 3.5 GB peak for the voice model).
- The first voice session after a restart waits ~22 s while large-v3 loads.
- To go back: `VOICE_STT_MODEL=turbo` (keep the richer hint and the 150 ms
  minimum), or `WHISPER_FP16_WEIGHTS=false` to load exactly as before.

### 10.5 Not measured yet

- The phone's `VOICE_RECOGNITION` capture mode and turning the noise
  suppressor off (the recorder supports both).
- Other speakers, noisy rooms, and Kannada sentences beyond one short reply.


---

## 11. What the 19–21 September 2026 reports changed

Two rounds of customer feedback (the app screenshots from Ajith Sir, and
Neelesh's notes on the "Vaidehi School of Excellence" lead). Each item below
names the cause, not just the symptom.

### 11.1 Backend

| reported | cause | change |
|---|---|---|
| Dictation returned Russian gibberish ("Я с Джебиис. Тумку.") | `POST /dictate` ran Whisper `tiny` with no language limit — with no language to hold on to, tiny picks one | `DICTATION_WHISPER_MODEL=turbo` (and the live `.env` no longer pins `tiny`), limited to `VOICE_STT_LANGUAGES`, and given the same name hint as voice mode (`client_draft.vocabulary_hint`) |
| "Action items missed meeting dates" | extraction resolved the date (verified: every item came back `2026-09-27`), but `GET /meetings/{id}` never sent `due_date` | the payload carries `due_date`; the app shows "— due 27 Sep" |
| Contact numbers read aloud as "billions, millions" | Kokoro reads `9886543210` as a quantity | `voice.speakable` spaces out any run of 7+ digits, leaving counts, years and amounts alone |
| Jarvis answers mid-sentence | 0.6 s of silence ends a turn, and a breath is easily 0.6 s | `VOICE_VAD_SILENCE_MS=900` (+0.3 s per turn) |
| Jarvis started a second "SJBC Tumkur" without mentioning the one on file | duplicates were only named at the read-back, by which point the whole flow had been walked | a `duplicate` stage asks first (§2.1) |
| "Not able to change state from cold calling to open" | Jarvis had **no tool** for it | new `move_client_state` tool (client agent). The rules are not duplicated: `lead_service.change_state_for_user` now holds the permission checks, the history row, the closed round and the "now open" announcement, and `PATCH /leads/{id}/state` calls the same function |

### 11.2 Android

| reported | cause | change |
|---|---|---|
| "See the way 'Assistant' is written towards left" | the title had `layout_weight=1` next to the context chip and three buttons, so it was squeezed to one letter per line | the title takes its own width; the chip is the flexible one and ellipsises |
| "I did approve.. but there after it showed a irrelevant screen" | deciding removes the row from the cached feed, and the detail screen reloads from that cache — painting "Something went wrong · This approval is no longer pending" as it closed | the screen remembers its own decision and ignores the reload; an approval decided elsewhere now says "Already decided" with a way back |
| "It did not capture after sometime..all what I said got cut" | dictation ends a clip after 2.5 s of silence, and a 60 s ceiling | multi-line fields (meeting notes) get 6 s of patience and a 300 s ceiling; one-line fields are unchanged |
| "Can we improve the readability?" | the tool-result card printed every key, including `Important: false`, and glued nested contacts onto one line | `Pretty` drops false flags, puts a block under its heading, and bullets one contact per entry |
| Remove Aixia | — | five avatars (Ethan, Sofia, Oliver, Lily, Leo); a phone that had chosen her falls back to the default |

### 11.3 The Kannada and Hindi sweep (21 Sep 2026)

Typed prompts, because typing takes speech out of the question: 24 requests
(12 romanised Kannada, 6 Kannada script, 5 romanised Hindi, 2 English
controls) across tasks, client lists, client details, creating a lead, booking
a demo, notes, follow-ups, moving a state and chit-chat. Anything that would
write went at a client that does not exist, and every draft was cancelled.
Script: `/home/telaverge/Ekaghni/stt_eval/kn_sweep.py`, results `sweep*.json`.

Four rounds. What it found, all now fixed:

| found | cause | fix |
|---|---|---|
| "SJBC Tumkur bagge maahiti kodi" (tell me about X) started a NEW client | the router read "about a client" as "add a client" | the router names that phrasing, in three languages, as query's |
| "Show my open tasks" answered "I couldn't find a client matching **default**" — in English too | the model fills `client` with a placeholder and the tool looked it up | `_effective_client` treats "default", "none", "me" and friends as "not said" (and "all" still broadens) |
| a Kannada request answered in Kannada | the model ignoring the English-only rule | the rule was already there; see below |
| a lead created from Kannada script was stored as `ವೈದೇಹಿ ಸ್ಕೂಲ್` | nothing said to transliterate | the client agent writes names in Latin letters |
| a client named in Kannada script was never found | records are Latin; the search used the script | the query agent transliterates before searching |
| "nanna kelasagalu torisi" understood on one run, not the next | a nano model guessing at Kannada work words | the router carries a short glossary (kelasa = task, maahiti = information, bagge = about, dikhao = show, …) |

**What is left is model variance, not code.** The fast model is
`openai/gpt-5.4-nano` (OPENROUTER_MODEL_FAST), and across four identical runs
the same prompt sometimes routed well and sometimes did not — "SJBC Tumkur
bagge maahiti kodi" answered fully on rounds 2 and 3 and came back "no results"
on round 4. The deterministic parts (name cleaning, the duplicate question,
the placeholder client, the state words) behave the same every run; the
model-shaped parts wobble. The lever for that is a stronger fast model, which
is a cost decision, not a code change.

### 11.4 Still open

- **"Not able to understand additional languages other than English"** — the
  speech side was fixed on 17 Sep (§10.3): Hindi now comes back in Devanagari
  rather than Urdu script. Worth re-testing on the current build; if it still
  happens, the next place to look is the router and agent prompts, which are
  English-only.
- **"Few times it is telling some other unrelated additional information"** —
  no example captured. One transcript of such a turn would say whether the
  query agent is over-fetching or the model is padding its answer.

## 12. The four customer asks of 21 September 2026 (built 23 Sep 2026)

Research behind these is in `docs/NEXT_FEATURES_RESEARCH.md`. The design
choices were put to the developer before building and answered as follows:
a meeting gets **its own record**; it uses the org's **one shared Meet room**
for now; **anyone who can see clients** may arrange one; a rejected invite is
**redrafted automatically** from the reason; the task card gets a **tappable
client chip**; a colleague who is blocking a task gets **a notification and a
Home card**; an uploaded recording goes through **the same consent sheet** as
a live one.

### 12.1 Tasks name their client

**The Home briefing** (what the customer called the dashboard; a Sales Lead
has no Tasks tab at all). Missed on the first pass and added the same day,
after the developer's screenshot. `assistant_engine.build_daily_digest` ends
every task line with its client, the task's own lead or else its project's:
`- [P1] Send the fee sheet (due 09 Sep) · [ABC School](yuvipep://lead/<id>)`.
The "title (due ...)" text is unchanged, and a task with no client is exactly
as before. The app's Markwon on Home resolves `yuvipep://lead/<id>` to the
lead screen; any other link opens in the browser as before. Tests:
`tests/test_briefing_names_client.py`, `BriefingLinksTest`.

**The Tasks tab card:**

The Tasks tab card showed the project and fell back to the school only when
there was no project, so a task out of a meeting never named its client. Now a
chip under the title shows the school whenever the task has a lead; tapping the
chip opens that lead, tapping anywhere else still opens the task. The meta line
keeps the project. `MyTasksAdapter.clientOf` / `contextOf`, tested in
`TaskClientTest`.

### 12.2 Upload a recording file (Android only)

The recorder screen (reached after the consent sheet, as before) has a
**Choose a recording file** button while nothing is being recorded. The
system picker offers audio files and mp4. The file is copied into app storage
(the upload worker needs a real path it can retry from), its length is read
with `MediaMetadataRetriever`, and the same title / Upload / Discard panel and
the same `UploadMeetingWorker` take over. The worker now sends the file's real
type instead of always `audio/mp4`, and leaves `duration_seconds` out when the
length could not be read (raw `.aac` often has none) rather than claiming one
second. Files over the server's 200 MB cap are refused before copying. The copy
is deleted after upload, on Discard, and when the screen is left without
uploading; the original on the phone is never touched. `PickedRecording`,
tested in `PickedRecordingTest`.

### 12.3 "Blocked, waiting on Siva" reaches Siva

| where | change |
|---|---|
| `app/services/blocker_resolver.py` (new) | finds the colleague a free-text reason names. A full name wins; a first name counts only if exactly one colleague has it; first names under three letters are never matched alone; whole words only; two different colleagues named → nobody. Telling the wrong person is worse than telling nobody. |
| `sync_engine._on_task_blocked` | resolves the colleague (an explicit `blocked_on_user_id` in the request wins, if it is an active member of the org), stores it on the task, and notifies them once (`kind="blocked_on_you"`, pushed to the phone). The tap goes to the task's project, else its client — not to the task, because the app's task screen only finds your own tasks. When a colleague is named, the old "reason contains *approval* → email the client" chase no longer fires: "needs Siva's approval" is Siva's approval. |
| `action_items.blocked_on_user_id` | new column, added by an idempotent `ALTER` in `_apply_light_migrations`; cleared on unblock and re-decided on every re-block |
| `POST /tasks/{id}/block` | answers `{"ok": true, "blocked_on": {"id", "name"} | null}` |
| `GET /action-items/waiting-on-me` (new) | open, blocked tasks waiting on the caller: title, reason, who is waiting, client, project |
| Android Home | a "Mithun Rao is waiting on you" card per task, gone once it is unblocked; the block dialog says "Blocked — Siva has been told and will see it on Home" |

Tests: `tests/test_blocked_on_colleague.py` (18), `WaitingOnYouTest` (6).
Note for tests: the test client skips the app's startup, which is what installs
the Sync Engine as the event reactor, so a test that needs a reaction installs
it itself (see the fixture in that file).

### 12.4 A meeting path separate from demos

**The record.** `ScheduledMeeting` (table `scheduled_meetings`, in the WIPE
bucket before `leads`): client, day, start time (`HH:MM`, may be empty only
when a recording agreed a day but no time), length (default 30 min),
organiser, cc, bcc, source (`app` / `jarvis` / `recording`), the recording it
came from, its task, its calendar event, and the latest invite and what became
of it. Named so because `Meeting` already means a recording.

**Scheduling it** (`app/services/meeting_invite_service.py::schedule`) does
four things: writes the record; puts a task in the organiser's list titled
"Meeting with ABC School on Fri 02 Oct at 11:00" with that date and time as its
due date; mirrors it to Google Calendar when that is configured (with the real
length — `calendar_service.create_event` gained `duration_minutes`); and drafts
the invite.

**The invite** is an `OutboundMessage` of kind `meeting_invite`, filed in
Approvals: to the client's primary contact, cc and bcc as asked, a body a model
writes from the context (who, when, how long, what for, and the recording's
summary when it came from one — with a plain template as the fallback), the
Meet link, and a calendar attachment with its own UID and SEQUENCE. No contact
with an email → the meeting still stands and the answer says no invite was
drafted.

**bcc is new everywhere.** `outbound_messages.bcc` (ALTER), `create_message`
takes it, the SMTP envelope includes it, no header shows it, and it is left
out of the calendar file too (an attendee list is visible). The Approvals
screen in the app shows a BCC line so the approver sees it before saying yes.

**Reject → redraft → Approvals.** Rejecting from the Approvals inbox already
looped messages back through `communication_engine.redraft_rejected`; a
meeting invite now takes its own branch there (and on the direct
`POST /messages/{id}/reject` route). With a reason, the reason is read for
changes — a new day, time or length, people to add to or remove from cc or bcc
— the meeting, its calendar event and its task move if needed, and the invite
is **rebuilt** (new attachment, next SEQUENCE, the reason given to the writer
as an instruction) and filed for approval again. Without a reason it is simply
closed. Approving sends it through the ordinary send queue.

**From a recording.** `analyse_meeting` now also returns `agreed_meeting`
(agreed, date, time, length, purpose) — only a concrete agreement to meet on a
stated day counts, and "let's catch up sometime" does not. The pipeline then
calls `schedule_from_recording`: the task joins the other extracted items (so
it goes through the review gate when that is on), and the invite waits in
Approvals. A retried pipeline does not schedule it twice. A failure here is
contained in a savepoint and cannot cost the recording its other results.

**Jarvis.** The scheduling agent has `schedule_meeting`, `list_meetings` and
`cancel_meeting`, and its prompt says a meeting is not a demo: `book_demo`
only when the person says demo. The router sends meeting requests (and short
answers to its questions) to the scheduling agent. When the client, day and
time are all given, the meeting is scheduled in one turn. When something is
missing, **one** question is asked — "Which client is the meeting with?",
"Sure — which day should the meeting with ABC School be?", "What time on
Friday 2 October should the meeting with ABC School start?" — and the
conversation is held open (`app/ai/meeting_draft.py`, the same mechanism as
adding a client), so the next message is read as the answer before any router
sees it. A model reads the answer, in any of the three languages; plain answers
("4 pm", "11:30", "Friday", "27th") are also read without a model, so an outage
cannot strand the question. "Cancel" drops it; an unrelated question pauses it
and offers to continue. Voice mode runs the same orchestrator with a session,
so all of this works spoken, unchanged; its acknowledgement for this agent is
"Looking at the calendar."

**API.** `GET /scheduled-meetings?lead_id=`, `POST /scheduled-meetings`
(`lead_id`, `date`, `time`, `duration_minutes`, `purpose`, `cc`, `bcc`),
`POST /scheduled-meetings/{id}/cancel` (removes the calendar event, closes the
task, withdraws a pending invite and drafts a cancellation). All need
`view_leads`. There is no meetings screen in the app yet: the task shows in the
Tasks tab (with its client chip) and the invite in Approvals.

Tests: `tests/test_scheduled_meetings.py` (51, including one run through the
real meeting pipeline).

### 12.6 Live test with the real model (23 Sep 2026)

Run on the live server as rahul, three conversations, every meeting cancelled
and every draft rejected afterwards (script: `/tmp/live_meeting_test.py` on
the VM). The router and the tool were right from the first run; three real
problems were found and fixed:

| found | fix |
|---|---|
| The live org has **two clients called "Abc School"** (Siva's, Hyd, no email; Priya Nair's). The shared resolver asked "Abc School, Abc School. Which one?" — unanswerable — and the flow then asked "Which client?" forever. | The meeting flow labels the choices ("Abc School (Hyd, Siva's) or Abc School (Priya Nair's)"), keeps the day and time already given while asking, and understands "Priya's one", "the Hyderabad one", "second wala", "2" or the label itself without a model (`meeting_draft.pick_option`). The shared resolver is unchanged. |
| The model **invented a day and a time**: "Set up a meeting with Abc School" was booked for today at 09:00; "…October 3 ke din" got 09:00; a 60-minute length and filler purposes too — despite the prompt forbidding it. | `meeting_draft.ground`: a value the model hands over is kept only if the person's words hold one of that kind (digits, weekday and month names, today/tomorrow/kal/naale, "4 pm", "10 baje", "5 gante", subah/sanje, Devanagari and Kannada script). The scheduling agent passes the person's words to the tool for this. |
| The invite body came back with markdown (`**Friday, 02 October**`), shown literally in a plain-text email. | The writer is told "plain text only", and `plain_text` strips bold, headings and link syntax anyway. |

After the fixes, all three went right: one sentence + "Priya's one" → 2 Oct
11:00 with the invite in Approvals; "Set up a meeting with Abc School" → "the
Hyderabad one" → "which day?" → "next Monday" → "what time?" → "4 in the
evening" → 28 Sep 16:00 (no invite: that client has no email); the
Kannada/Hindi mix → "second wala" → "what time on Saturday 3 October?" →
"subah 10 baje" → 3 Oct 10:00 with the invite in Approvals.

### 12.5 Found on the way, not changed

- **A redrafted demo invite shows the client the old text.** The generic
  redraft copies the attachments, and a calendar invite's attachment carries
  an `html_body` built from the first draft's text; Gmail shows the HTML part.
  Meeting invites are rebuilt and do not have this problem. For demo invites
  it is a small change in `redraft_rejected` (rebuild `html_body` from the new
  body), left for a decision rather than changed unasked.
- **Rejecting any other message without a note still redrafts it**, with the
  body unchanged, and files a new approval. Meeting invites close instead.
- `tests/docx/test_client_dossier.py` reads the live database file directly,
  so a new column makes its two "measured client" tests fail until the service
  restarts and the light migrations run. Expected; checked by running the
  migrations on a copy of the live database (twice, to prove it is idempotent).

## 13. The notifications flood (24 Sep 2026)

**Reported:** the notifications panel was full of "Good morning / Good
evening" items. They were "Your daily digest" notifications: the Home
briefing, pushed once a day, whose first line is the greeting.

**Cause:** the scheduler's "already ran today" marker lived only in memory, so
**every service restart re-ran the whole daily block** — digests, follow-up
reminders and the sync sweep. Siva got ten digests on 23 Sep, one per restart.

**Changes (decided by the developer):**
- The daily digest notification is gone; the same briefing is on Home.
- The marker is also written to `data/storage/scheduler_last_daily.txt`
  (the server's UTC date), so a restart no longer repeats the daily jobs.
  `tests/test_scheduler_daily_once.py`.
- Deleted from the live database, with a JSON copy first
  (`../backup_2026-09-23/notifications_deleted_2026-09-24.json`): 2,111 digest
  notifications (all users) and 42 "Approval waiting on you" notifications
  whose approvals were already decided (mostly from testing on 23 Sep).
- The app's notification cache only ever added rows, so server-side deletions
  stayed on the phone. Each refresh now drops cached rows the server no longer
  has (`NotificationPrune`, `NotificationPruneTest`).

**Also confirmed the same morning:** the Risabh Public School invite was
approved at 05:13 IST and sent by SMTP to the principal eleven seconds later.

## 14. Jarvis meeting card opened the wrong screen (25 Sep 2026)

"Open" on the card after "schedule a meeting for tomorrow at 10:30 am" went
to the recording screen ("transcribing"). The tool result carried a bare `id`
(the scheduled meeting), and the app infers the screen from the tool name, so
`schedule_meeting` + `id` read as a recording. Now the meeting tools return
`scheduled_meeting_id` and `approval_id` (the invite waiting in Approvals; the
cancellation notice for `cancel_meeting`), and the app opens `approval_id`
first (`AssistantEntities`). The app also never treats a bare `id` from
`schedule_meeting` / `cancel_meeting` / `list_meetings` as a recording, so an
older server shows no Open rather than the wrong screen. No invite (client has
no email) means no Open button. Tests: `test_the_jarvis_card_opens_the_invites_approval`,
`MeetingCardTest`.

## 15. Meeting clashes (25 Sep 2026)

Asked for a meeting at a time already taken, Jarvis booked it anyway.
`meeting_invite_service.find_clash` now checks the organiser's own scheduled
meetings that day. A meeting with no length counts as 30 minutes, back to back
is allowed, and cancelled or day-only meetings block nothing. Jarvis keeps the
client and day and asks again: "You already have a meeting with ABC School on
Friday 2 October from 10:30 to 11:00. You can schedule this one from 11:00
onwards. What time on Friday 2 October should the meeting with ABC School
start?" The new answer is checked again. `POST /scheduled-meetings` refuses a
clash with 409 and the same sentence. Not checked: a meeting agreed in a
recording (the client agreed that time), and a time moved by an approver's
rejection reason. Tests in `tests/test_scheduled_meetings.py`.

## 16. No duplicate client names, and the pick loop (26 Sep 2026)

**Rule.** A client name identical to one already on file in the same
organisation, ignoring upper and lower case and extra spaces, is refused
wherever a lead is created: `POST /leads` (the app form and bulk import),
Jarvis's add-client flow, and chain-deal branches. One place holds it:
`lead_service.refuse_duplicate_name` (409, "<Name> is already on file (<state>,
owned by <owner>). Two clients cannot have the same name. Open that one
instead, or use a name that tells them apart, for example with the city.").
Each refusal is logged. A NEAR name (similar, not identical) is still only
asked about by Jarvis, because two real clients can have similar names. The
same name in two organisations is fine. The app needed no change: the new
client form and the bulk importer already show the server's message.

In Jarvis an identical name no longer offers "Add it anyway". The rest of the
draft is kept and a name that tells the two apart is asked for.

**Existing duplicates** (live, 26 Sep): two "Abc School" (Siva, Hyd; Priya
Nair) and two "Xavier School". They are not changed. Jarvis already asks
which one; the loop when answering was fixed:

**The pick loop.** Answering "owned by Siva" worked when typed exactly, but a
spoken "Shiva" matched neither option, and the model's reading "Abc School
owned by Shiva" was then looked up by name, found both, and the same question
came back. Now near spellings of the owner or city match (similarity 0.8),
the model's reading is matched against the offered options instead of being
searched again, and an answer that still fits neither says "Sorry, I couldn't
tell which one." with the options numbered, so "1" or "2" always works.
Checked live with the real model.

**Tests.** `tests/test_duplicate_lead_names.py`, rewritten duplicate tests in
`tests/test_client_creation.py`, pick tests in `tests/test_scheduled_meetings.py`.
Older tests that created the same client name twice in the shared test
organisations now use `tests/conftest.py::fresh_lead` (a suffix only when the
name is taken) or `lead_named` (reuse, where the name itself is asserted).

## 17. Confirm once, and "Approve plan" (1 Oct 2026)

Found at BS Carmel School (lead `9bcf97b3a85948d09bbe3e46906a0eb9`, 29 Sep):
the review was confirmed twice from two phones; the second confirm created
copies of both items without their dates and ran the Planner a second time;
"a meeting on Thursday", said on Tuesday 29 Sep, was stored as Wednesday 30
Sep; and a 46-second voice note ("we have to plan the kits") gave no to-dos.
The fix was built together with the agreed "Approve plan" step.

### 17.1 Confirm works once

`POST /meetings/{id}/review/confirm` first changes the meeting from
`review_pending` to `completed` with a conditional update, so of two confirms
only one can win, even at the same moment. The other answers 200 with
`already_confirmed: true`, saves nothing and queues no Planner. A kept item
that carries an id which is no longer pending is ignored, never created again.
`plan_meeting` also runs once per meeting: it stops if the meeting already
has a plan. The app disables Confirm on the first tap (`SubmitOnce`).

### 17.2 Weekdays are resolved in code

Extraction now dates the prompt from the day the meeting was recorded (not
the day the pipeline runs) and asks the model for `day_said`, the words used
for the agreed meeting's day. `extraction.resolve_day_words` reads today,
tomorrow, day after tomorrow, a weekday, this/coming/next weekday and
"5 October"; `check_day` keeps the model's date only when it matches the
words, else uses the code's reading. "next Friday" (and a weekday equal to
today) has two readings and either is accepted. Words the code cannot read
("next week", "after the exams") leave the model's date alone. The same check
runs on each to-do's `due_hint`. `day_said` is internal: `agreed_meeting`
still has its four keys. Re-run on BS Carmel's real recording: the meeting is
now Thursday 1 Oct.

### 17.3 Voice notes

The extraction prompt now says a recording can be the salesperson alone
recapping a meeting, and that what our side says it has to do ("we have
to...", "we need to...") is a to-do even with no deadline. Re-run on BS
Carmel's 46-second note: two to-dos ("Plan kits for every student", "Define
what each kit will include"); the 11-second greeting still gives none.

### 17.4 "Approve plan"

After the review is confirmed, the Planner's plan for a recorded meeting is
**held** for the person who recorded it instead of going straight to the
approval rules:

- `create_plan_version(hold_for_meeting=...)` keeps the plan
  `pending_review` and files one Approval of the new entity type
  `meeting_plan` (entity_id = the meeting) addressed to the recorder, with no
  expiry, plus one notification (`kind="plan_ready"`, opens the meeting).
  Only `plan_meeting` (recordings, gate on or off) asks for the hold; typed
  notes (`/meetings/notes`) and every other plan path are unchanged.
- `meetings.plan_state` / `plan_note` (new columns, light migration) say
  where it stands: planning, ready, approved, sent_for_approval, no_plan,
  failed, discarded, superseded. `plan_meeting` maps every Planner outcome to
  one of these with a plain sentence (follow-ups only, no change, a conflict,
  maybe another client, the model unreachable, a dependency loop).
- `GET /meetings/{id}/plan`: the state and, while there is a plan, its tasks
  (`confirmed` = accepted at the review, `promised_to_client` = locked on,
  `depends_on`), the other changes as short lines (new project, moved dates,
  removals, reopened work, project window, moved demo, renegotiated promises,
  and the merge's own diff lines), and `can_approve`.
- `POST /meetings/{id}/plan/approve` with `skip_task_ids`: only the recorder;
  confirmed and promised tasks cannot be skipped (422). It claims the hold
  with a conditional update, so a double tap or a second phone gets
  `already: true`. Skipped tasks are cancelled ("Left out when the plan was
  approved") and removed from every `depends_on_ids`. Then the plan_change
  rules apply with the same facts as before (tasks added, new project, date
  shift): no rule, or the rule names the same person, makes it active now;
  otherwise an ordinary plan_change approval is filed and the answer is
  "Sent to <name> for approval". The live org's rules (new project, 2+ tasks
  go to a sales lead) mean most plans recorded by a sales agent end there.
- From the Approvals inbox (or an app without the sheet) the held card's
  Approve keeps every task; Reject drops the Planner's extras and the plan
  (`discard_meeting_plan`), keeps the confirmed to-dos, and asks nobody else.
- A newer plan for the project expires a pending hold
  (`retire_superseded_plan`) and tells the recorder.
- `POST /meetings/{id}/plan/retry` when the state is `failed`. A planning job
  that uses up its retries (`plan_meeting_safe`, now the registered handler)
  sets `failed` and notifies (`kind="plan_failed"`). Live settings: 4
  attempts, 30/60/120 s apart.
- `GET /meetings/{id}` gains `plan_state` / `plan_note` and no longer lists
  the Planner's tasks that are not live (waiting, left out or dropped); that
  list is what made BS Carmel's 2 confirmed items read as 5.

**App** (the app's `docs/SESSION_HANDOFF.md`): after Confirm the review
screen shows a loader with rotating text, then the plan sheet with a switch
per extra task; the meeting screen, Home and Approvals open the same sheet.

**Tests:** `tests/test_approve_plan.py` (17), `tests/test_day_words.py` (9).
Full suite after the change, in a staging copy: 3 failed / 1,358 passed. The
failures are the clock-sensitive `test_the_worst_neglected_client_is_first`
(also in the morning's baseline, 1 failed / 1,334 passed) and the two
`test_client_dossier.py` "measured client" tests, which read the live
database and pass once the service restart adds the columns (checked on a
copy of the live database, migrated twice). Backups: `../backup_2026-10-01/`.

### 17.5 Waiting tasks are released when their prerequisite is done (1 Oct 2026)

Found on the first "Approve plan" test (Ollama School of Commerce). A plan
task that waits on another gets its owner only when that one is done, by
design. But the Planner names a prerequisite by its title, and only titles in
the plan's own batch were turned into ids. A title a fence had removed after
the model wrote the plan (the recording's meeting, already scheduled, or a
duplicate of a confirmed to-do) was stored as the title itself. A title is
never marked done, so the waiting task never got an owner. Shown on a copy of
the live data: marking the 5 Oct meeting done left "Design workbook content"
unassigned, while a task linked by id was picked up at once.

Now (`planner_engine._resolve_dependency_refs`) such a title is linked to the
client's live task with exactly that title (case and spacing ignored, same
client only); a title that matches only a finished task, or nothing, is not
waited on. `repair_title_dependencies` applied the same rule to the 4 live
tasks stored with title links (two Ollama tasks now wait on the 5 Oct meeting;
BS Carmel's proposal waited on the cancelled 30 Sep meeting and no longer
waits; an IBC proposal dropped a link to a task that no longer exists).
Before/after: `../backup_2026-10-01/dependency_repair_applied.txt` and the
audit log (`data.repair_dependencies`). Tests: `tests/test_plan_dependencies.py`
(6; all fail without the fix). Full suite in staging: 1 failed / 1,366 passed
(the clock-sensitive test only).

### 17.6 People a meeting names are checked by the model (1 Oct 2026)

Found on the Ollama School of Commerce test: speech-to-text wrote "Rishabh
Jain" for the saved contact "Risabh Jain" and the spelling check
(`_name_match`) let a duplicate contact through; the Planner also saved a
contact literally called "Accounts Head"; and two names for one person in the
same meeting would each have become a contact.

Now `planner_engine._resolve_people`, run at the start of
`ensure_contacts_for_specs` (so both the first-meeting shell and
`sync_stakeholder_specs`, including inbound replies, use it), makes ONE model
call per meeting (`planning.review_meeting_people`, strong tier, the model
proposal filling uses: `google/gemini-2.5-flash` on the live `.env`). For
every person the meeting named it returns: a person or only a role; the same
as an earlier name in this meeting (score 0..1); the same as a saved contact
(score 0..1). `SAME_PERSON_THRESHOLD = 0.7`; at or above it means the same.

- Two names for one person in a meeting become one entry under the fuller
  name, keeping the role and influence each gave.
- A name matching a saved contact is renamed to it: no duplicate, and the
  meeting's role lands on the real person.
- A role with no name that is no saved contact's title is not saved; the
  plan's change list says "The meeting mentioned the Accounts Head without a
  name; add them as a contact once you know who they are".
- Model unavailable or failing: names are saved as heard (the old
  behaviour); losing a person is worse than a duplicate.
- Bad answers (an index pointing nowhere, a score outside 0..1) count as no
  match (`planning.parse_people_review`).

Live scores (real model): Rishabh Jain vs saved Risabh Jain 0.95; Mr. Jain
0.80; Rahul Jain vs Risabh Jain 0.00; Mrs. Nair vs Priya Nair (Principal)
0.90; "the accounts head" vs Meera Shah (Accounts Head) 0.80; Anil vs Anil
Kumar 0.90 (not Anita Kumari); "Accounts Head" with no such contact = not a
person; "Rishabh" and "Mr. Jain" with nothing saved are kept apart (nothing
shows they are one person).

**Test note:** the test run reads the live `.env`, whose model key is real.
`tests/conftest.py` therefore stands in for this check with "no opinion" in
every test (the old behaviour); `tests/test_contact_matching.py` (11) scripts
the answers. Full suite in staging: 1 failed / 1,377 passed (the
clock-sensitive test only). The existing "Accounts Head" contact on Ollama
School of Commerce was left as it is.

## 18. Jarvis proposal loop at the last step (2 Oct 2026)

**Reported:** after all the proposal questions, Jarvis sometimes lost the
thread at the very end: "I could not match X to a contact", then, after the
person named someone, "there is no proposal in this conversation", then the
questions all over again.

**Evidence:** Siva's four latest proposal conversations (27 and 29 Sep) and
three replays of the Orchid conversation through the real code and model, on
a sandboxed copy of the data (all three failed the same way). Four causes:

1. **Invented recipient.** After "Yes, these are all correct" the fast-tier
   model builds the proposal and calls `prepare_email` in the same turn, with
   `to_contact` filled from nearby words: the programme ("IBC"), a document
   value ("Operations Manager"), the address just typed as an answer, or the
   client's own name (all three replays), though nobody had named anyone and
   the client had a main contact with an email.
2. **The answer was routed away.** "Dr. Sudhir" in reply to "who did you
   mean?" went through the router, which sent a bare name to the
   conversation agent ("add Dr. Sudhir as a contact?").
3. **The built proposal was out of reach.** A turn could only find a proposal
   it built itself (`_resolve_proposal` used a ref or that turn's context), so
   the next turn said there was none, offered to create one, and opened a new
   fill (two Orchid proposals on 27 Sep).
4. **"All the suggested values are fine" offered with nothing suggested.**
   The YuviPep address question has no suggestion; the tap settled nothing,
   so the same question came back seven times (27 Sep).

**Fixes:**
- `proposal_agent.recipient_said`: a recipient (or CC) is used only if the
  person named it in this chat, outside their answers to the document's
  questions (`asked_json` replies) and the fixed taps, and it is not the
  client or the programme. Otherwise none: `resolve_contact` then uses the
  main contact, the only contact, or asks. `prepare_email`'s description now
  says to leave `to_contact` empty unless the user named someone. The user's
  words reach tools as `extra_context["_said_by_user"]` (set in
  `BaseAgent.run`; "_" keys never reach the prompt).
- `app/ai/proposal_recipient.py` (new held flow, kind `proposal_recipient`):
  when the recipient has to be asked (no main contact, an unmatched name, a
  contact with no email), the question is held like adding a client or
  arranging a meeting. The next message is read as the answer before the
  router: a name, part of it, a title, the option's number, or an email
  address drafts the email for the SAME proposal and returns the approval
  card (`confirmations.Outcome.pending_approvals`, passed on by the
  orchestrator); a contact with no email asks again; "cancel" drafts nothing
  and keeps the proposal; a longer message or a question is routed as usual
  and the reply offers to come back. Registered at import of
  `proposal_agent`, so it is known from the first command after a restart.
- `_resolve_proposal` falls back to the proposal this chat built
  (`find_correctable`, same window as corrections). `create_proposal` for the
  same client and programme in a chat that already built it returns
  `already_built` (send with `prepare_email`, change with
  `correct_proposal`); a fresh fill only with `start_over=true`, when the
  user explicitly asks for a new proposal from scratch.
- `fill_tools.round_message` / `round_candidates`: "All the suggested values
  are fine" only when something in the round has a suggestion; otherwise the
  round says there is no suggestion and to type the answer.

**Checked with the real model after the fix** (sandboxed copies, email,
calendar and push off): Orchid "Create the proposal" x3: approval card to Dr.
Sudhir straight after the approval, no recipient question; "Create the
proposal" again: `already_built`, one proposal per run. Named contact without
email: says so, offers Dr. Sudhir, answer drafts the card. No main contact:
one question with both names as buttons; an unrelated question in between is
answered and the offer to come back appended; "2" picks the second option.
BS Carmel: asks Jyothi or Abhishek instead of inventing one.

**Not changed, noticed:** "send it" right after the card sometimes reaches
the email agent, which drafts a separate follow-up email (seen once in three
runs). The proposal email itself is never duplicated (its idempotency key).
The meeting held flow (`meeting_draft`) registered lazily, so after a
restart a held meeting question was dropped until the scheduling agent had
run once: FIXED the same day, the orchestrator now imports every held flow
(`client_draft`, `meeting_draft`, `proposal_recipient`) at startup;
`tests/test_held_flows_registered.py` checks it in a fresh interpreter.
The YuviPep address in the proposal template is asked of the salesperson; it
could come from the organisation's own record.

**Tests:** `tests/test_proposal_recipient.py` (17). Full suite in staging:
5 failed / 1,390 passed; the 5 are the clock-sensitive tests, failing at that
hour on unchanged code too (checked). Backups: `../backup_2026-10-02/`.
Replay harness: `/home/telaverge/Ekaghni/sfai_replay/replay2.py`.

**Live:** service restarted 2 Oct 2026 (about 22:00 UTC on 1 Oct) with the
proposal fixes and the held-flow registration.

## 19. Meeting days: "next Saturday" and days in the past (2 Oct 2026)

**Found:** "Schedule a meeting with X next Saturday at 11 am", said on Friday
2 October, was booked for Saturday 3 October (tomorrow) in three runs out of
four with the real models. Two causes:

1. The fast agent model often passed the person's words to `schedule_meeting`
   instead of a date ("Saturday", sometimes dropping "next"), which the tool
   allowed.
2. The code that turns words into a date (`meeting_draft.parse_date`) threw
   "next" away, so even a perfect model passing "next Saturday" got tomorrow.
   A stronger agent model alone would not have fixed it.

Asked directly, with today's date, weekday and time in front of it, the
strong model (`google/gemini-2.5-flash`) read 26 of 28 kinds of phrase right
every time (English, Hindi, Kannada, "the 15th", "kal subah 10 baje", year
end). Its two mistakes were both dates in the past ("the 1st" said on 2 Oct
gave 1 Oct; "next Friday" said on 26 Dec gave a date a year back).

**The developer's decision:** "next" + a weekday is always confirmed, because
people use it for two different days.

### 19.1 What changed

| where | change |
|---|---|
| `app/ai/day_reading.py` (new) | `read_when`: one strong-model call that says which day and time each piece of text names, given the moment it was said. Returns nothing when the model is unavailable, and every caller then does what it did before. Plain code checks: the weekday the model names must match its date; `next_weekday_options` gives the two days "next <weekday>" can mean (English "next", Hindi "agle", Kannada "mundina", romanised and in script), and none when the words also give the date ("next Wednesday, the 30th") or say "this"/"coming"/"next week Tuesday"; `is_past`. |
| `app/ai/meeting_draft.py` (Jarvis) | The strong model's date and time replace the agent's, but only for what the person's words actually name (a day in words or a day of the month; a clock time). "next <weekday>" asks "Which Saturday should the meeting with X be: Saturday 3 October or Saturday 10 October?" with both days as chips, keeping the client and time; the answer is read in code first ("2", "second", "the 10th", "the tenth", "the later one", the chip itself), and a bare "Saturday" asks again. A day (or a time today) that has gone by is never booked: "Thursday 1 October has already passed." `parse_date` no longer turns "next Saturday" into the coming one. New stage `date_choice`; new draft key `date_options` (held conversations from before still load). |
| `app/ai/extraction.py` (recordings) | With the recording's moment (`now`), the days a recording names are settled: words the code reads one way stay as they are; words it cannot read ("end of the month") are read by the strong model; "next <weekday>" is set to the strong model's reading and the other day is named beside it, because nobody can be asked; nothing before the recording is kept (a past agreed meeting is not scheduled and becomes a to-do "Agree the day of the next meeting"). Any error here keeps the first reading. |
| `app/jobs/pipelines.py` | Passes the recording's moment, and the note for the agreed meeting. |
| `app/services/meeting_invite_service.py` | `schedule_from_recording(note=...)`: the note goes on the meeting's task (seen at the review) and on its invite's approval card, never in the email. |

Example note: *The recording said "next Friday", which could be Friday 2
October or Friday 9 October. It is set to Friday 9 October; if Friday 2
October was meant, change it.* An approver changes it by rejecting the
invite with the right day, which already moves the meeting.

**Not changed:** the app (the question arrives as a card with chips, spoken in
voice mode, as before), the `POST /scheduled-meetings` form path, demos and
follow-ups, and the approver's "move it to ..." reading of a rejected invite.

### 19.2 Checked

Tests: `tests/test_day_reading.py` (74). `tests/conftest.py` gives every other
test no reading, so they run exactly as before. In `test_scheduled_meetings.py`
the Jarvis tests that booked 2 or 5 October 2026 now book the same days in
2037 (same calendar, so every weekday and sentence is unchanged), because a
day in the past is now refused. Full suite in staging at the same hour as the
unchanged code: 1 failed / 1,469 passed against 1 failed / 1,395 passed (the
same clock-sensitive test; the difference is the 74 new tests). The new tests
also pass with the clock moved 300 days ahead.

Real models, sandboxed copy of the live data (email dry-run, calendar off),
`/home/telaverge/Ekaghni/sfai_replay/replay_dates.py`, 15 conversations on
Friday 2 October:

| said | before | after |
|---|---|---|
| "next Saturday at 11 am", then "the second one" | booked Sat 3 Oct | asked; booked Sat 10 Oct |
| "agle Shanivar 11 baje", then "2" | booked Sat 3 Oct | asked; booked Sat 10 Oct |
| "next week Tuesday at 11" | booked Tue 13 Oct | Tue 6 Oct |
| "on 1st October at 11" | tried to book 1 Oct | "has already passed", asks |
| this Saturday, tomorrow, day after tomorrow, the 15th, kal subah 10 baje, 3rd November, next Friday then "the 9th", an unrelated question in between | right | right |
| "in two days at 4 pm" | asks which day | asks which day |

Recordings re-run with the real model (`replay_rec.py`): every date the same
as before except BS Carmel's "proposal by next Friday" (said Tue 29 Sep),
before silently 2 Oct, now 9 Oct with the note naming both days.

### 19.3 Found, not changed

- "in two days" is not counted as naming a day by the 23 Sep guard against
  invented days, so Jarvis asks which day instead of booking (safe, as before).
- `extraction.resolve_day_words` reads "last Friday" as the coming Friday (no
  meeting is agreed for a past day, so it has not mattered).
- An approver's "move it to next Thursday" on a rejected invite is still read
  by the fast model without the weekday in its prompt.
- `tests/test_scheduled_meetings.py::test_adding_a_contact_later_drafts_the_waiting_invite`
  books 2 Oct 2026 and expects an upcoming meeting, so it fails from 3 Oct
  2026 on unchanged code too (checked with the clock moved ahead).

**Live:** service restarted 00:11 UTC on 2 Oct 2026. Backups:
`../backup_2026-10-02/meeting_days/`. Rollback: copy those files back, delete
`app/ai/day_reading.py` and `tests/test_day_reading.py`, restart.

## 20. Assignments name their client; confirm only what you tick (2 Oct 2026)

**Asked:** the Home briefing names each task's client, but the
confirm-assignments screen did not, and it confirmed the whole batch at once,
which could include an older client's tasks.

### 20.1 Backend (live since 09:50 UTC, 2 Oct 2026)

| where | change |
|---|---|
| `app/api/workflow.py` `GET /assignments/proposed` | each row also carries `lead_id`, `lead_name`, `project_id`, `project_name`, `due_date`. The client is the task's own lead, else its project's lead, the same rule as the Home briefing (`assistant_engine.build_daily_digest`). Null for work with no client. The original six fields and the row order are unchanged. |
| `app/engines/assignment_engine.py` `confirm_batch` | only rows still `proposed` are confirmed. A stale screen, a double tap or a second phone that sends an already-decided id changes nothing, sends no second "New task" notification, and is not counted in `confirmed`. A person change (`overrides`) on a decided row is ignored too. |

The server already confirmed only the ids in `assignment_ids`; ids left out
stay `proposed` and keep showing on the screen and in Home's count.
Tests: `tests/test_assignment_selection.py` (3): rows name their client
(own, via project, none); confirming 2 of 3 leaves the third proposed; a
second confirm of the same id confirms 0 and notifies nobody. Two of the three
fail on the old code.

### 20.2 App (installed 2 Oct 15:57 IST)

- `ProposedAssignmentDto` gains the five fields.
- `AssignmentSelection` (no Android types, `AssignmentSelectionTest`, 8):
  groups rows by client in the server's order, rows with no client last
  under "No client"; nothing starts ticked (the developer's choice); a
  client's header ticks or unticks all its rows; only ticked ids are sent,
  and person changes only for ticked rows; a reload keeps ticks on rows still
  there.
- `AssignmentConfirmFragment`: a header per client with the same client chip
  as the task card (tap opens the client) and a select-all box; a tick box on
  each row (tapping the card toggles it); a line with the project and due
  date; the button reads "Confirm N selected" and is disabled at 0 and while
  a confirm is on its way. After confirming, the screen reloads if anything
  is left and goes back if nothing is.
- Layouts `item_assignment_header.xml` (new) and `item_assignment.xml`;
  strings in `values/strings.xml`; contract fixture
  `assignments_proposed.json` and `ContractTest` assert the new fields.
- An app with this change on an older server shows every row under
  "No client" and still confirms only what is ticked.

## 21. Jarvis redesign and chat history (2 Oct 2026)

**Asked:** the typed Jarvis screen felt plain (no animation, the "About"
text cut off with no way to read it) and there was no way back to an earlier
chat. Redesign the look only, keep every behaviour, leave voice mode exactly
as it is, and add a sidebar of past chats.

### 21.1 Backend (live since 10:23 UTC, 2 Oct 2026)

`GET /api/v1/assistant/sessions?limit=50` (1..100): the caller's own chats,
most recently used first, built from `assistant_turns`, each with
`session_id`, `title` (the first thing the person said in the turns still
kept, one line, at most 80 characters), `preview` (the last thing said by
either side, at most 140), `last_at`, `turns`. Scoped to (org, user) like
every other read of the transcript. Opening a chat is the existing
`GET /assistant/history`; deleting one is the existing
`DELETE /assistant/history`. Tests: `tests/test_assistant_sessions.py` (6).

### 21.2 App (installed 2 Oct 15:57 IST)

- Voice mode is untouched: `VoiceStageDialog`, `VoiceModeController`,
  `ChatAdapter`, `ChatItem` and the `item_chat_*` layouts did not change (the
  voice screen renders its cards with `ChatAdapter`). The typed chat has its
  own `JarvisChatAdapter` with the same rules (which chip answers at once,
  when Open/Why show, approval buttons per state) and new `item_jarvis_*`
  layouts.
- Look: top bar with a history button, the Jarvis orb and a live status
  (Ready / Thinking with a pulsing dot); the context ("About …") in its own
  strip that wraps to two lines, tap for the full name with Keep / Clear; a
  welcome with a breathing orb, a greeting and suggestion cards (the same
  "Create a lead…" and recent commands as the chips, same action); your
  messages in indigo gradient bubbles, replies beside the orb, cards rising
  in; typing dots while Jarvis works; pill composer; "jump to latest";
  colours in `values/jarvis.xml` with dark-mode values in
  `values-night/jarvis.xml`.
- History drawer: New chat, search, chats grouped Today / Yesterday /
  Previous 7 days / Previous 30 days / Older (`ChatHistory`, tested), the
  open chat highlighted; tap opens it (`AssistantSession.switchTo`, then the
  usual text-only restore: old cards are not replayed, as after a restart),
  long-press deletes it after a confirm. Held questions (a meeting being
  arranged, a client being added) are per chat on the server, so going back
  to a chat continues them.
- Behaviour notes: "New chat" keeps the old chat (the developer's choice;
  it used to delete it). Opening another chat or a new chat waits while
  Jarvis is still answering, so a late answer cannot land in the wrong chat;
  opening another chat ends voice mode and cancels a dictation in progress.
  Send, replies, approvals, chips, Open/Why and the voice callbacks are the
  same code as before (only the line that hides the welcome changed).
- Tests: `ChatHistoryTest` (6); 182 unit tests pass.

## 22. Field location: where the sales team was when they opened the app (2-3 Oct 2026)

**Why.** Some sales leads and sales agents said they had reached a client
when they were somewhere else. The org admin wants to see where the sales
team really was. Design and plan (with every decision) are in the Android
folder: `docs/superpowers/specs/2026-10-02-field-location-design.md`,
`docs/superpowers/plans/2026-10-02-field-location.md`, and the progress
ledger next to the plan.

**Status (update when it changes): LIVE since the restart of 2 Oct 2026
18:52 UTC (backups `../backup_2026-10-03/field_location/`); the app is
installed on the developer's Vivo (3 Oct 00:23 IST). Not yet tried by hand
on the phone. One test reading is in the live table (see 22.4).**

What the developer decided:
- A reading is taken only when the app is opened or comes back to the
  screen. No background tracking, no permanent notification.
- Recorded: sales agents and sales leads. Reader: the org admin only.
- Permission refused or GPS off: the app keeps working, asks again on every
  open, and the refusal is recorded so the admin sees "location off".
- Map: MapLibre with OpenFreeMap tiles (free, no key); Google Maps links for
  directions.

### 22.1 Server

| file | change |
|---|---|
| `app/models/location.py` | new table `location_pings` (`LocationPing`): org, user, `client_ref` (unique per org and user, so a retried reading is saved once), status `ok` / `permission_denied` / `gps_off` / `timeout`, lat, lng, accuracy, `is_mock` (fake GPS app), `approximate`, `trigger` (`open` / `resume`), `captured_at` (phone), `received_at` (server) |
| `app/models/__init__.py` | registers it |
| `app/core/reset_taxonomy.py`, `tests/test_reset_taxonomy.py` | WIPE bucket, after `device_tokens`; counts now 4/2/8/50 and 64 tables |
| `app/core/permissions.py` | `track_locations`: org admin only |
| `app/config.py` | `location_retention_days` (90), `location_map_style_light` / `_dark` (OpenFreeMap positron / dark), `location_map_attribution` |
| `app/services/location_service.py` | the rules, saving, `latest`, `points` |
| `app/api/locations.py`, `app/main.py` | router `/api/v1/locations` |
| `app/services/retention_service.py` | step 4: readings older than `location_retention_days` are deleted; counter `location_pings_purged` |
| `tests/test_locations.py` | 18 tests |

New table, so `create_all` makes it at the first start; no ALTER. No model
calls (nothing to stub). No change to any existing table or endpoint.

Endpoints:
- `POST /locations/ping`: sales agents and sales leads only (403 for anyone
  else). Answers `{saved, reason}`; `reason` is `duplicate` or `too_soon`.
- `GET /locations/latest` (`track_locations`): every active sales agent and
  sales lead of the org, even with no reading: last reading, last position,
  `off_today` (org time zone), `fake_gps_7d`.
- `GET /locations/points?from=&to=&user_ids=&roles=` (`track_locations`):
  readings in the window, oldest first; window at most 31 days; at most
  5,000 (the newest kept, `truncated: true`).
- `GET /locations/config` (any signed-in user): map style addresses and the
  credit line, so the tiles can change without a new app.

Rules on the server:
- Thinning (same rule as the app): a reading is kept when 10 minutes have
  passed since the last kept one, or the person moved more than 200 m, or
  the status, fake-GPS flag or approximate flag changed.
- A `captured_at` more than 5 minutes in the future becomes the server's
  time; one older than 7 days is refused (422).
- Every read is limited to the caller's org.

### 22.2 App (Android folder, no git)

Package `feature/location/`: the recorder (`LocationReporter`, `LocationGate`
for the notice and permission prompt, its own small outbox
`LocationOutbox` / `PendingPings` instead of the shared `OfflineQueue`, which
replays approval decisions in order and must not wait behind a reading), the
"Field team" card on the org admin's Home, and the map screen (heatmap,
last-known pins, day replay, filters, Google Maps links). MapLibre's x86
engines are left out of the APK (arm only): 57,980,755 to 81,666,448 bytes.
Voice mode untouched (checksums kept).

Found in the final review and fixed (3 Oct): a reading can take up to 20 s;
if the person signed out and someone else signed in meanwhile, the reading
went out with the new person's login. Now nothing is sent unless the
reading's owner is still the one signed in
(`PendingPingsTest.nothingIsSentWhenSomeoneElseIsNowSignedIn`).

### 22.3 Tests

- Staging and live side by side, 2 Oct 18:40 UTC (IST already 3 Oct):
  live 6 failed / 1,473 passed; staging 6 failed / 1,491 passed (live + the
  18 new). The same 6 on both: `test_the_worst_neglected_client_is_first`,
  `test_adding_a_contact_later_drafts_the_waiting_invite` (from 3 Oct), and
  the clock four (`test_what_is_late` x3,
  `test_demos_followups::test_followup_complete_schedules_next`).
- App: 215 unit tests (contract fixtures `locations_latest.json`,
  `locations_points.json`, `locations_config.json` captured from the staging
  code; `permissions.json` checked byte for byte against the server matrix).

### 22.4 Going live (2 Oct 2026 18:52 UTC)

- Live files checked unchanged since the staging copy (md5), backed up, then
  copied from staging (temp name + mv, md5 equal). Restarted once; health
  OK on 8010 and the public URL; log clean; `location_pings` created, empty.
- Smoke test as `rahul@yuvipep.com`: he is a **sales agent**, not the org
  admin. `/locations/config` 200; `/latest` and `/points` 403 (correct for
  his role). A test reading sent in the belief he was the admin WAS saved
  (200): one row, `client_ref` `smoketest0001`, status `gps_off`, captured
  2 Oct 18:00 UTC. It shows him as "location off" on 2 Oct. Waiting for the
  developer's yes to delete it.

## 23. Open straight away: a sales lead creates a lead already open (7 Oct 2026)

**Asked:** a sales lead creating a lead can choose to open it straight away
instead of starting it in cold calling. Choosing it needs a contact, in the
same form. Jarvis offers the same choice in natural language, asks for the
contact, reads everything back and spells the email before creating it.

**Status (update when it changes): LIVE since the restart of 7 Oct 2026
15:18 UTC (backups `../backup_2026-10-07/open_at_creation/`); the app is
installed on the developer's Vivo (7 Oct 20:48 IST, versionCode 20733). Not
yet tried by hand. The smoke test after the restart created no data.**
Spec, plan and ledger are in the Android folder:
`docs/superpowers/specs/2026-10-07-open-at-creation-design.md`,
`docs/superpowers/plans/2026-10-07-open-at-creation.md` and
`...open-at-creation.progress.md`.

Decisions (developer, 7 Oct 2026): sales lead only (sales agents and the org
admin are unchanged); the lead is owned by the sales lead who creates it (no
owner choice); the contact needs a name, a designation and an email, the phone
is optional; Jarvis always spells the email back, typed or spoken.

### 23.1 Server

| where | change |
|---|---|
| `app/services/lead_service.py` | `looks_like_email`, `check_open_contact` (name, designation, email required; email `^[^@\s]+@[^@\s]+\.[^@\s]+$`; lower-cased), `create_open_lead`: refuses anyone but a sales lead (403) and a bad contact (422) BEFORE writing, then `create_lead` (owner = the sales lead, the cold-calling history row, audit with `opened_at_creation`), `add_contact` (primary, created by the sales lead), `change_state` cold_calling -> open with the reason "Opened at creation by <name>; contact <name>", and the usual "<lead> is now open" announcement. The lead is never inserted as open directly: the Home "recently opened" card finds a lead by that cold_calling -> open history row. |
| `app/api/leads.py` | `POST /leads` gains `open_now` (default false) and `contact {name, title, email, phone}`. `open_now` with an `owner_id` of someone else: 422. Without `open_now` the old path runs unchanged (a `contact` sent without it is ignored, as before). |

No new column, table or permission: no migration, no reset-taxonomy change,
no `permissions.json` change.

### 23.2 Jarvis (`app/ai/client_draft.py`, `app/ai/agents/client_agent.py`)

For a sales lead only, right after the name (and the duplicate check):
"Do you want to open <name> straight away, or start it in cold calling? To
open it now I'll need a contact there." (chips: Open it now, Cold calling).

- Cold calling: today's flow exactly (owner question, optional details,
  read-back, create).
- Open: the sales lead owns it (a colleague already named as owner is told
  not to be: "An open lead is owned by you, so <name> won't own it."). Jarvis
  asks only for what is missing, one question at a time: "Who is the contact
  at <name>? Tell me their name, designation and email address. A phone
  number is optional.", then "What is <contact>'s designation?", "What is
  <contact>'s email address?". The optional question offers the phone first.
  The read-back adds "It will be opened straight away." After "create it":
  "Before I create it, let me check the email: <email> is spelled A-N-I-T-A
  dot S-H-A-R-M-A at G-M-A-I-L dot C-O-M. Is that right?" Yes creates; no
  asks "What is the right email address?" and spells the new one back.
- "Open it now" / "cold calling" / "later" / yes / no are read without a
  model; anything else goes to the existing reading model, which gained an
  `open_now` field. No new model call.
- `create_client` (the agent tool) gained `open_now` ("open it now" in the
  first sentence skips the question). Ignored for anyone who is not a sales
  lead.
- New stages: `open_choice`, `open_contact`, `email_check`. The draft carries
  `open_now`; a draft held from before this change loads as "not decided".

**Found with the real model and fixed in code:** asked to write "anita dot
sharma at gmail dot com", the fast reading model returned anita.dots.sharma,
anita.dout.sharma and anita.dots.harma on three runs. `client_draft.email_in`
now reads an address from the person's own words (written, or spoken with
at / dot / underscore / dash / plus, and "at the rate"), and that reading wins
over the model's, while a lead is being opened. It is taken only where the
words clearly give one: at the start of the reply, after a cue ("email",
"is", "on") or after a pause; spelled letters ("M E E R A at ...") are joined.
"She works at tata dot com" or "anita sharma at gmail dot com" are left to the
model, and the spell-back catches anything still wrong.

**Changing one's mind:** at any later step a sales lead can say "cold calling"
(the owner question comes back) or "open it now" (the contact is asked for). A
colleague named as owner after choosing open is refused: "An open lead is
owned by you. Say cold calling if <name> should own it." Someone who stops
being a sales lead mid-conversation is told "Only a sales lead can open a lead
straight away, so it will start in cold calling." and carries on in cold
calling.

### 23.3 App

- New Lead form: a switch "Open straight away (needs a contact)", shown only
  when the signed-in role is `sales_lead`. On: the owner field goes, contact
  fields appear (name, designation, email, phone optional), checked before
  sending (`OpenLeadForm`). Off: exactly the old request.
- `LeadRequests.Create` gains `open_now` and `contact` (left out when null).
- The Jarvis card (`ClientDraft`) names the new steps and shows "Starts as:
  Open" and the email; the "client added" card says "<name> is saved and
  open." for an opened lead (`AssistantFragment`).
- New text in `res/values/open_at_creation.xml`. Voice mode untouched.

### 23.4 Tests

- `tests/test_open_at_creation.py` (14) and 22 new tests at the end of
  `tests/test_client_creation.py` (the open path end to end, the email
  spelled and the "no" loop, a bad email not kept, spoken emails written as
  addresses and winning over the model, cold calling keeps today's flow, a
  sales agent is never asked, an old held draft still loads, a demoted sales
  lead carries on in cold calling, changing one's mind at the read-back, an
  owner named after choosing open, and which sentences hold an address).
- Staging and live side by side (7 Oct 15:09 UTC, final code): live 2 failed /
  1,495 passed, staging 2 failed / 1,531 passed (the same two known
  failures; +36 new tests).
- Real model on a sandbox copy of live data (email dry-run, calendar off, push
  off): the open path, the cold-calling path, a sales agent, an email
  corrected at the spell-back, a spelled email and a change of mind at the
  read-back all behaved as above.
- One fresh reviewer read the whole change: 0 critical, 4 important (all
  fixed with a failing test first), 6 minor (listed in the ledger, left).
- App: 224 unit tests (`OpenLeadFormTest` 5, `ClientDraftTest` +4).

### 23.5 The email spell-back loop (reported 7 Oct, fixed live 12 Oct 2026)

**Reported by the developer** after go-live, from a real chat as Siva (7 Oct,
17:01-17:04 IST): "ekaghni.mukherjee at the rate gmail.com" was saved as
`ekaghni.mukherjee@therategmail.com`, and both corrections ("No, it is not
right. At the rate gmail.com." and "No, it is not the rate gmail, it is gmail,
gmail.com.") got "Sorry, I didn't catch that" and the same question again.

**Causes, proven with the real model on a sandbox copy (3 runs each):**
the code reader of spoken addresses ignored written dots ("gmail.com"), so the
model decided, and once in three it returned the raw words, which the fallback
formatter turned into "therategmail.com"; a correction that names only the
domain gave the model nothing to change, and a "No, ..." inside a sentence is
not a plain no, so the email check looped. Replaying the whole chat also
showed "start in cold calling ... sorry, you can open it" read as cold calling,
and the model reading "She is Principal." as "open it now", which switched the
lead and lost the designation.

**Fixed in `app/ai/client_draft.py`:** written dots count in spoken addresses;
"at the rate (of)" is always "@"; a correction naming only the domain keeps
the name part and swaps the domain (`_domain_in`), then spells it back; at the
email check, a reply saying no / not / wrong / galat / nahi with no readable
address asks "What is the right email address?"; open or cold calling is taken
only from the person's own words ("open", "khol/kholo", "cold"), the last one
said winning, never from the model's guess, also for the agent's first
sentence; a plain "yes" while a contact detail is missing says what is still
needed. 10 new tests in `tests/test_client_creation.py`. Siva's exact chat
replayed on the real model now opens the lead with
`ekaghni.mukherjee@gmail.com`. Suites side by side 7 Oct 17:18 UTC: live 2
failed / 1,531 passed, staging 2 / 1,541 (the two known failures).

**Live:** copied and restarted 12 Oct 2026 01:22 UTC (backups
`../backup_2026-10-12/email_loop_fix/`). No app change.

## 24. Six fixes from a live Jarvis test of the Innodhara products (12 Oct 2026)

A live test (as Ajith Kumar, sales lead, Innodhara; messy Hinglish replies)
created "Test School Sunrise", built a YuviPep 360 CBSE Intermediate proposal
and tried to email it. Five defects were found, plus a sixth during the live
re-test. All fixed, tested first in staging, LIVE (restarts 12:43, 18:20 and
18:31 UTC; backups `../backup_2026-10-12/five_fixes/`, `five_fixes_step2/`,
`five_fixes_step3/`). Plan: Android folder
`docs/superpowers/plans/2026-10-12-five-fixes.md`.

1. `<School name>` on the PDF cover and every footer. The templates bind
   those spots to docProps dc:title, which held the tag; only MOUs filled
   properties. Now `properties.fill_literals` (tag text in properties only,
   case-insensitive) runs on every proposal build (`proposal_fill_service.build`).
   MOU path unchanged; a real (non-tag) title is untouched.
2. "Yes, these are all correct" looped on `create_proposal`. Tool results are
   not replayed across turns, so `_open_fill` at the REVIEW now returns a
   loop-breaker (`at_review`, the review text, `what_to_do` naming
   `confirm_*_values`) instead of re-raising the review.
3. A correction at the review was refused ("no proposal ... create one").
   `_correct_built` now hands it to the review (`_confirm_values` with the
   correction) when a fill is open; `_resolve_proposal` names the confirm tool
   instead of "create one first" when the chat has an unbuilt fill. Wording
   says a change request must never be approved.
4. Open-client contact loop. The reader copied back owner "you" (what it is
   shown) and "you" was looked up as a person. Now an owner equal to the shown
   value is ignored; a repeated complete contact moves on; an owner problem
   with other changes asks the NEXT question.
5. Innodhara could never send email: one server-wide SMTP host (gmail) but
   innodhara.com mail is Zoho. `email_service` now picks the host from the
   account domain's MX (zoho.in/.com/.eu, outlook; google and unknown keep the
   server host; gmail.com never looked up; cached; explicit
   `smtp_host`/`smtp_port` in the org integration wins). On an own host the
   email goes FROM the login account under the salesperson's name, Reply-To
   the salesperson. YuviPep's path unchanged. Zoho login verified.
   Extra in the same area: a corrected value that repeats its row label
   ("Annual Price Per Student: ₹2,500 net") keeps only the value, in both
   `apply_correction` and `reopen_for_correction`.
6. A dead (dead_letter/failed/rejected) proposal email was returned forever by
   its idempotency key, with the PDF from before a correction.
   `prepare_proposal_email` now gives a dead one a successor key (`#2`...);
   drafts, queued and sent are returned as before (double-send guard intact).

Tests: `tests/docx/test_fill_fixes_12oct.py`, `tests/test_client_contact_loop_12oct.py`,
`tests/test_email_host_12oct.py`, `tests/test_proposal_email_dead_12oct.py`
(all failed on the old code first). Full suite: live before 2 failed / 1,541
passed; staging final 2 / 1,574 (the two known failures). Real-model replays
(`/home/telaverge/Ekaghni/sfai_replay/replay_12oct.py`) on sandbox copies.
Live proof: the rebuilt proposal PDF shows "Test School Sunrise" on all 23
pages, no tag; the email was SENT 18:32 UTC via `smtp:admin@innodhara.com`.

Still open (not changed): vague product names ("the intermediate one") can
misroute; the fast model sometimes writes the person's words verbatim into the
document ("6 se 10", "10.6 lakh"); "approve and send" said to Jarvis drafts a
second, attachment-less email (`draft_custom_email`) and "send the X
proposal" can route to the email agent; the proposal email says "Dear
Sir/Madam" because a docx_simple proposal has no `contact_name` variable;
inbound mail (IMAP) still uses the server-wide host. Test data left in live
Innodhara: lead Test School Sunrise, its proposal, messages 7860f141
(dead_letter), 7cbf2a06 (junk custom email, pending approval), 3b6a4f00 (sent).

### 24.1 RESOLVED 13 Oct 2026, see §25: the generated proposal PDF is not faithful to the template (developer, 12 Oct 2026)

The leads below were checked and both were wrong; the cause was the converter (§25).

The developer opened the PDF sent at 18:32 UTC (proposal
fefb6a69142a40fb9bdc164d7b063f56, YuviPep 360 CBSE with Intermediate Lab,
docx `orgs/e158c595c2154209b5da860956a0cc9f/proposals/109f9257_...docx`,
pdf `.../359a0428_...pdf`) and found:
1. The title (the school name on the cover) is no longer in the template's
   font and size: it is now very small.
2. Pages and their contents are shifted downwards versus the template.
3. Because of that shift, the "Composite Skill Lab Infrastructure" tables
   overlap / are mangled over one another.
The expectation is a PDF identical to the template except for the filled
values.

NOT investigated yet. Leads only, none verified (check each in the code):
- `app/services/docx/index.py` `refresh_static` runs when the template's
  contents page is static (`proposal_fill_service.build`), and it round-trips
  the whole package through LibreOffice (rewrite of the docx), which can
  change fonts, text boxes, table positions and pagination. Check
  `index_kind` of the 8 templates and whether the shift exists without it.
- The cover's school name sits in a content control bound to dc:title; the
  tag fill (`app/services/docx/tagfill.py`, `text.py` replace_span) writes
  into the control's runs and `properties.fill_literals` sets the property;
  check which run's formatting the replacement keeps, and whether the
  bound control's placeholder/run properties decide the rendered size.
- Compare like with like: convert the UNTOUCHED template with the same
  `convert.docx_to_pdf` and the filled docx, page by page (page count, text
  positions, fonts via pdffonts/pypdf), and open both .docx in Word to see
  whether the defect is in the docx or only in LibreOffice's PDF.
- The pre-fix PDF of this proposal (`56115d5f_...pdf`, before 12 Oct 18:20)
  is still in storage for comparison.

## 25. Proposal PDFs now look like the Word template (13 Oct 2026 IST, LIVE 12 Oct 20:49:50 UTC)

The developer opened the PDF of proposal fefb6a69 (§24.1): cover title tiny,
pages shifted down, "Composite Skill Lab Infrastructure" tables on top of each
other. Investigated on a sandbox copy (`/home/telaverge/Ekaghni/sfai_pdf_sandbox`),
measured against Word's own rendering on the developer's laptop. Plan and
ledger: Android folder `docs/superpowers/plans/2026-10-13-pdf-fidelity.md`.

**The build was never the cause.** Rebuilt step by step, every step
(python-docx re-save, `all_roots`, the update-fields flag, `apply_tags`,
`fill_literals`) gives the same layout as the UNTOUCHED template; Word opens
the sent .docx exactly like the template (19 pages, school name Aptos Bold
36 pt). Both §24.1 leads were wrong: `refresh_static` never runs for these
templates (index kind "field" for 7 of 8, "none" for FIL,
`proposal_fill_service.py:852`) and never used LibreOffice's docx anyway
(`index.py:233-257`); the cover value lands in the one 36 pt bold run.

**Causes, all in the converter:**
1. LibreOffice 7.3 drops the formatting of run-level content controls (the
   cover's Title-bound school name printed at 11 pt).
2. The VM had none of the templates' fonts (the Normal style is Aptos; also
   Calibri, Barlow, Poppins, Lato), so text was set wider: 23 pages, not 19.
3. LibreOffice 7.3 cannot place Word's floating tables (the infrastructure
   page is ten of them), even with the right fonts.

**Fix (LIVE):**
- LibreOffice 26.2.6 installed from the official packages into
  `/opt/libreoffice26.2` (`sudo dpkg -i`, checksum verified). 7.3 at
  `/usr/bin/soffice` is untouched and is the fallback.
- A fonts folder only the converter sees:
  `/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/pdf_fonts`
  (outside git; Aptos from Microsoft's download, licence accepted by the
  developer 13 Oct; Carlito for Calibri, Lato, Poppins, Barlow) plus
  `fonts.conf` there (Russo One -> Carlito, which is what Word shows without
  Russo One; the FIL cover title otherwise wraps and is clipped).
- Settings (`app/config.py`, set in live `.env`): `LIBREOFFICE_BIN`,
  `LIBREOFFICE_FALLBACK_BIN`, `PDF_FONTS_DIR`; `libreoffice_first_try_seconds`
  defaults to 15. Unset, everything behaves as before.
- `app/services/docx/convert.py`: converts a prepared COPY; the main soffice
  gets 15 s when a fallback exists, then 7.3 converts it (logged as a
  warning); LibreOffice runs in its own process group and is killed whole on
  a timeout (before, `soffice.bin` kept running after a timeout).
- NEW `app/services/docx/lo_compat.py` (the copy only, never the stored
  .docx): a paragraph holding only a picture whose paragraph mark is hidden is
  un-hidden at a 1 pt line (newer LibreOffice hid the cover art with it; Word
  draws it); `PAGE \* ArabicDash` becomes "- " PAGE " -" (LibreOffice printed
  "5" for Word's "- 5 -"). Never fatal.

**Known limits:**
- Every modern LibreOffice (25.8, 26.2, 26.8 tested) loops forever on the
  CBSE Foundation template (its floating tables "Healthcare and Wellness" and
  "Retail and Enterprise"; un-floating either ends it). It falls back to 7.3
  in about 18 s: better than before (21 pages, was 24) but not like Word.
  Full fix: the owner makes that table non-floating in Word and re-uploads.
- The phone app stops waiting after 30 s (`NetModule.java:38`), which is why
  the first try is 15 s.
- YuviPep's two Innovation Lab templates use Tahoma, Trebuchet MS and Lucida
  Sans Unicode (no free versions): their PDFs are as before.
- Small remaining differences from Word on the 360 templates: page 8 content
  about 5 pt higher, a few points of extra gap between some infrastructure
  tables, "Parameters" wraps on the last page.

**Measured against Word (untouched templates):** 7 of 8 Innodhara templates
now have Word's page and picture counts with a median 0.6-0.8% of pixels
different (7.3: 13-26%, 1-5 extra pages); YuviPep Mou1 7 pages like Word
(7.3: 9). Live proof after the restart: the sent proposal's .docx converted
by the live code gives 19 pages, 74 pictures, cover "Test School Sunrise"
Aptos Bold 36 pt.

**Tests:** new `tests/docx/test_pdf_fidelity_13oct.py` (19; fail on the old
code: the title test reads 11.0 pt on 7.3; on 26.2 without `lo_compat` the
cover art is missing and the page number loses its dashes).
`tests/docx/test_mou_golden.py`: page floor 8 -> 6, because Word lays that
built contract out on 6 (8 was 7.3's overflow). Side by side 12 Oct 20:39
UTC: live 6 failed / 1,570 passed, staging 6 / 1,589 (the same 6: the two
known plus the four clock tests, IST and UTC dates differing). Backups:
`../backup_2026-10-13/pdf_fidelity/` (code, `.env` copy, docs).
