# 04 — The Assistant ("Jarvis") — the soul of the app

Tony Stark never navigated menus. He said what he wanted; Jarvis had
already read everything and answered with the *thing*, not a link to the
thing. The backend was built for exactly this — `POST /assistant/command`
routes free text to six specialist agents with org-scoped tools, returns a
plain-language reply, the actions it took, and any `pending_approvals` —
so the app's job is to make that endpoint feel alive.

## 1. Entry points (always ≤1 gesture away)

| Gesture | Result |
|---|---|
| Tap center mic (bottom bar, every screen) | Voice sheet slides up, already listening |
| Long-press center mic | Assistant in type mode |
| "Ask about this" chip on any entity screen | Assistant pre-loaded with that entity as context |
| Notification "Ask why" actions | Assistant opens with the question prefilled |
| Home quick action / cold start voice | Full assistant screen |

## 2. The conversation screen

- Chat-style transcript (bubbles), but replies are **cards, not prose**,
  whenever the backend's `actions` say something happened:
  - *Lead created* card → open lead.
  - *Proposal drafted (v2, ₹1,26,000 — from pricing table)* card →
    preview + **Approve & Send** button right there (wired to
    `pending_approvals`).
  - *Demo booked Tue 10:00, Team Alpha* card → calendar peek.
  - *3 tasks created* card → expandable list.
- Every AI-made card carries the **Why chip** → `GET /why/...` rendered
  as a friendly explanation sheet (inputs, decision, reason, confidence).
- **Approvals in the flow:** when a command produces `pending_approvals`,
  the approve/reject bar is inline — command → result → tap Approve →
  "Sent." without ever leaving the conversation. This is the Iron-Man
  loop: *human speaks → machine does → human nods.*
- Long operations narrate: listening → thinking → "reading the pricing
  table…" staged Lottie states (the backend isn't streaming; the UI still
  keeps the user company; stages are picked by command type).
- **The transcript is a conversation, not a list of unrelated commands** —
  follow-ups resolve against what was just said (§4a). A restored transcript
  (after the app was killed) shows bubbles only; a **+** button in the header
  starts a new conversation and makes the backend forget the old one.
- TTS toggle: Jarvis can speak replies (short-form summary line only).

## 3. Voice pipeline (commands ≠ meeting audio)

- **Commands/dictation:** on-device `SpeechRecognizer` (fast, private,
  free). Final text goes to `/assistant/command`. Locale from device;
  works for Indian-English out of the box; partial results shown live.
- **Meeting recordings:** NEVER through SpeechRecognizer — recorded as
  audio and uploaded to `/meetings/upload`; the backend's local Whisper
  transcribes (higher accuracy, full-length, consented, stored).
- **Jarvis's voice (spoken replies): neural, open-source, offline.**
  Engine: **sherpa-onnx** (github.com/k2-fsa/sherpa-onnx, Apache-2.0,
  official Android AAR with a Java API). Primary voice: **Kokoro-82M**
  (huggingface.co/hexgrad/Kokoro-82M, Apache-2.0) — near-human prosody,
  nothing like the robotic system TTS. Fallback voice for low-end
  phones: a **Piper** VITS voice (github.com/rhasspy/piper, MIT).
  The voice pack downloads on first enable (~80–160MB, with progress and
  wifi-only option), then runs fully offline. Profile → Voice offers
  voice choice + speaking rate + "speak replies" toggle. System TTS is
  kept only as an emergency fallback if the model fails to load.
  (Exact model builds re-verified against the sherpa-onnx releases at
  Phase 5 start — the library is moving fast in a good way.)
- Fallback: recognizer unavailable → type mode with a gentle note.

## 4. Context injection (how Jarvis "already knows")

Two independent mechanisms, and they answer different questions.

**(a) Conversation memory — "what did we just say?"** (added 2026-07-21)

`AssistantSession` mints a `session_id` (UUID hex, persisted in prefs) and
sends it on every command. The backend stores each exchange in
`assistant_turns` keyed by (org, user, session) and replays the last turns —
to the agent *and to the orchestrator's router* — so:

- "list my open tasks" → "tell me more about **the second one**".
- "create the IBC proposal" → "**make it warmer**" (and it still routes to
  the proposal agent, which a nounless command never could before).
- "draft a follow-up" → "**send it**".

Rules the app must respect:

- **Text only.** The backend deliberately stores no tool calls, tool results
  or entity ids — replaying an id would let the model act on a record whose
  permissions may since have changed. So a *restored* transcript is bubbles
  only: no action cards, no live approval bars. Do not fake them.
- **Restore on cold start.** `GET /assistant/history?session_id=` refills the
  transcript after process death; one attempt, and a failed attempt is
  retried on the next visit rather than losing the chat for the process.
  Live bubbles always win over a replay that would duplicate them.
- **"New chat" (+) must actually forget** — `DELETE /assistant/history`, not
  just a local clear. If the delete fails, say so; the copy promises only
  that it will age out.
- **Logout wipes it** (`AssistantSession.reset()`): the backend keys turns by
  user, but the bubbles already on the device are the previous person's
  words. Shared-device isolation, 09 §3.
- Conversations are trimmed per session, swept after 90 days, and purged when
  a contact is erased under a data-subject request.

**(b) Screen context — "what am I looking at?"**

`ContextBus` (a singleton the fragments feed): the currently visible
entity (type+id+title) and the previous one. Every `/assistant/command`
call includes them (the endpoint accepts optional context ids, e.g.
`lead_id`, `proposal_id`). So:

- On a lead: "book a demo next Tuesday" needs no lead name.
- On an invoice: "chase this politely" → drafts the reminder (approval).
- On a conflict: "what did the principal actually say?" → grounded answer.

The transcript shows the context chip ("about: SVS Bootcamap — Dec") so
the user always sees what "this" means; tap to change/clear.

## 5. Command surface (examples the app will showcase in onboarding)

Sales: "Create a lead for Nexora Technologies, met their CTO Anita at
the expo" · "What's pending with VTU college?" · "Draft a follow-up to
the coordinator in Hindi" · "Mark SVS important".
Meetings: "I just met the principal — take notes" (opens notes composer
in dictation) · "Why did meeting 2 change the plan?"
Work: "What am I doing today?" · "Mark the syllabus task done, note:
shared v1" · "I can't take the robotics task, I'm on site" (decline).
Money: "Did SVS pay the advance?" · "Raise the balance invoice" (→
approval) · "Why is this invoice 63,000?" (computation).
Leads/leads-of-people: "Who decides at Nexora?" (stakeholders + influence)
· "Remind me what we know about their lab" (memory/notebook).
Admin/lead: "Who's overloaded this week?" · "Confirm today's assignments"
(opens batch) · "Show projects at risk".

The assistant does **not** invent client-side sends: anything
client-visible it produces lands as a pending approval — the app copy
says so ("Drafted. Waiting for your approve.").

## 6. Honest failure & guardrails (mirrors backend design)

### 6.0 Short, ambiguous commands are the AI's job — not the user's problem

> **The rule (user's, 2026-07-29 — non-negotiable):** a sales lead or agent will type
> **very short or loosely worded** commands about anything. The assistant must either
> **resolve it and proceed**, or **state its understanding and ask one clarifying
> question** — *"my understanding is X. Am I correct, shall I proceed?"*. **Failing with a
> lookup error is not an acceptable third option.** The user is not required to phrase
> things precisely, label fields, or know how the tools are shaped.

**This was broken and is now FIXED** — `FINDINGS.md` → F28, closed 2026-08-03 as Phase 7
§7.0 (doc 10). Typing *"draft an email to <person> at <client>"* used to fail because
`resolvers.py` only checked whether the typed hint sat *inside* the stored name and never
the reverse; Phase 6's Inbox reply route worked around it with labelled lines, which did
nothing for anyone typing into this tab by hand. Both are gone: the resolvers share one
ordered ladder that also reads a stored name **out of** a typed phrase, and the labelled
prompt was reverted to natural phrasing as the acceptance test.

**Resolution policy — ASK, NEVER GUESS:** one clear match → proceed *and name the person out
loud in the reply*; several or none → ask before acting. Never silently pick a recipient for
a client-visible message.

**How "ask" reaches the screen.** A resolver that is unsure raises `NeedsConfirmationError`
with its candidates. The agent loop marks that action `outcome: "needs_confirmation"` (with
`ok` still `false` and `error` still carrying the text, so an older build degrades to its
previous behaviour), and the app renders an amber **question card** — never the red *failed*
badge — carrying the question, one chip per candidate, and the line *"Nothing has been
drafted or sent yet."* Tapping a chip fills the input box; the user still taps send.

**This rule binds every new agent tool**, not just the ones that existed in Phase 7: a tool
that can fail to find something must ask with candidates rather than raise a bare
`NotFoundError`.

### 6.1 Other guardrails

- `needs_human` / low confidence → the card says "I'd rather a human
  looks at this" with a route to the right screen — never a fake answer.
  *(This "confidence" is `ai_decisions.confidence`, which is a real column and is what the
  WhyChip renders. Do not confuse it with an **inbound message's** confidence, which has
  never existed anywhere — see 03 §9.)*
- Model down (`ai_unavailable`) → "The brain is unreachable; your request
  is saved" → OfflineQueue keeps the command, retries, notifies on
  completion.
- Prices: if the user asks to change a number, the reply explains the
  approval chain and starts it (`price_change` approval) — the assistant
  never negotiates numbers itself.
- do_not_contact: refusals are surfaced verbatim with the reason.

## 7. Personalisation touches (cheap, high-delight)

- Greeting uses time + first name; briefing summary spoken on request
  ("give me my morning brief" → TTS reads it).
- Recent-command chips (from local history) above the keyboard.
- Per-role suggested commands (a sales agent sees selling commands, an
  ops lead sees delivery ones).
- Haptic + Lottie tick on approve; subtle sound only if user enables.

## 8. What the assistant is NOT (scope fences)

- No client-side LLM, no direct model keys in the app — all intelligence
  is the backend's (org budgets, audit, isolation stay intact).
- No hotword ("Hey YuviPep") in v1 — battery/permission cost outweighs;
  the center mic is one tap. Revisit post-launch.
- No offline speech understanding — offline queues the text, that's all.
