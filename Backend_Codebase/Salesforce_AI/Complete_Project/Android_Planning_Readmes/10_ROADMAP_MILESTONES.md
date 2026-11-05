# 10 — Roadmap, Milestones, Testing & Credentials

Each phase ends **runnable and demoable**; nothing merges without its
acceptance list green against the real backend (stub provider for
deterministic runs, live provider for the AI-feel demos).

## Phase 0 — Foundation (scaffold week)

Build: project skeleton, theming (06), core/net (auth, idempotency,
error mapper), TokenStore, Room shell, StateView, Splash, Login, Forced
password change, Environment sheet, role bootstrap + empty role homes.
Backend prep: **none — G1–G7 were all closed server-side on 2026-07-17**
(branding + refresh + pagination + upload-revision + devices/FCM +
admin password reset all live).
**Accept:** login as all six seeded users; kill app → session restores;
wrong password shows backend message; forced-change works; offline start
shows cached session banner.

## Phase 1 — The pulse (home, notifications, approvals)

Briefing card (`/digests/daily`), notification center + polling + bell,
Waiting-on-you feed (approvals + assignment batches + review-pending +
triage counts), ApprovalDetail with facts, decide flows incl.
reject-with-note; assignment confirm batch with per-task reasons.
**Accept (against dry-run script data):** every approval type renders
its facts; approve→backend state flips→feed clears; offline approve
queues and applies.

## Phase 2 — Relationships & meetings

Leads list/detail (all tabs), state suggestions banner, contacts +
card scan (CameraX), consent sheet, notebook entries; Meeting recorder
(foreground service) + upload worker + pipeline progress + review gate +
result sheet; typed notes composer.
**Accept:** record 2-min audio → watch pipeline → confirm review →
tasks appear; scan the sample card image → contact w/ needs_review;
"AI suggests cold" accept/reject round-trips.

## Phase 3 — Assistant v1 + proposals + files

Assistant screen (text first), ContextBus, action cards +
inline approvals, WhyChip everywhere; Proposal detail (locked pricing
rendering), edit-by-instruction, PDF viewer, submit-review /
approve-send; file client + cache.
Backend prep: none — G3 upload-revision already live.
**Accept:** "create a lead… draft the proposal… make it warmer… send
it" full conversation on live provider; manual PDF re-upload creates
human_edited version; tampered-total upload rejected with clear message.

## Phase 4 — Projects & work

Projects list/home/plan-diff/timeline/people/team, conflict resolver,
chain wizard, what's-blocking, brief; My Tasks + full task lifecycle
(complete w/ artifacts, decline, block, split, vendor promise/slip,
progress).
**Accept:** replay dry-run W6 (second meeting merges; new stakeholder
appears with provenance), W11 (block→chase visible in message center),
X2 (cycle refusal shown honestly).

## Phase 5 — Voice everywhere + demos + follow-ups

SpeechRecognizer integration (VoiceEditText across app + assistant voice
sheet + TTS replies), demo 31-day calendar + booking + reschedule
(invite resend messaging), follow-up queue.
**Accept:** book a demo by voice from a lead screen; dictate a rejection
note; calendar clash warning renders.

## Phase 6 — Inbox & messages ✅ **DONE & device-verified 2026-07-29** (app `0.7.0-phase6`)

> **Why this phase exists.** The Inbox is specified in `02_ARCHITECTURE.md`
> (`inbox/ MessageCenter, DeliveryTrace, InboundTriage, LogReply`), in
> `03_SCREENS_NAVIGATION.md §9`, and in `05_ROLE_EXPERIENCES.md §25` where it is one
> of the **five bottom-bar tabs** for a sales agent — but it was never assigned to a
> phase. Phase 4's acceptance criteria even *reference* the message center
> ("W11 block→chase visible in message center") without building it. Discovered
> 2026-07-22 while tracing where a human answers an AI-escalated client question:
> the answer was "nowhere" (**FINDINGS F27**). Scheduled here as its own phase.

**Screens (all four are specified already — build to the spec, do not redesign):**
- **Message center** — outbound list with status-trail chips
  (draft→pending→queued→sent→delivered/failed), filterable.
- **Delivery trace** — per-message timeline from `delivery_log[]`, plus open
  .eml/attachments.
- **Inbound triage** — unmatched/`needs_human` messages with the AI's intent guess,
  why it stopped and its summary (**not** a confidence — see the correction below);
  actions: attach to lead/project, set intent, resolve, or
  **open the assistant with the message as context** (this is the reply route — no
  new send endpoint is needed, the Jarvis email agent already drafts and routes
  through Approvals).
- **Log client reply** sheet — paste/dictate, channel picker, from-contact picker →
  `POST /inbound/ingest`, for calls and WhatsApp received outside the system.

**Backend readiness — verified 2026-07-22, most of it already exists:**

| endpoint | state |
|---|---|
| `GET /messages` (status filter) | ✅ exists |
| `GET /messages/{id}` → includes `delivery_log[]` (event, detail, at) | ✅ exists — delivery trace needs no new backend |
| `POST /messages/{id}/approve` / `reject` | ✅ exists |
| `POST /messages/draft` | ✅ exists |
| `POST /inbound/ingest` | ✅ exists |
| `GET /inbound/triage` (returns `triage` **and** `needs_human`, with `reason`/`summary`) | ✅ exists |
| `POST /inbound/{id}/resolve` | ⚠️ partial — takes `contact_id`, `mark_processed`, `note` |
| `POST /webhooks/whatsapp` | ✅ **CORRECTION (2026-07-29): it IS implemented** — `app/api/messages.py:132` takes provider delivery receipts and writes them to the delivery log. This row said "❌ not implemented" and was simply wrong. |

**Backend gaps closed in this phase — three, not the two originally listed. All additive,
no schema change, no migration** (backend unfrozen by the user for this named job, then
re-frozen):
1. **"Set intent" is not supported.** `TriageResolveRequest` gained `intent`, validated
   against `InboundIntent` (422 on anything else — the engines route on that vocabulary,
   so an invented value would route nowhere at all, silently).
2. **"Attach to project" is not supported.** `resolve` gained optional `project_id`,
   checked for existence *and* org.
3. **The roadmap missed one: `GET /inbound/triage` never returned the AI's reading.**
   The row had no `intent`, so a "set intent" picker would open blank over a guess the
   human could not see, and no `matched_lead_id`, so the reply route could not scope the
   assistant to the client the backend had already matched. Rows now carry `intent`,
   `change_type`, `matched_lead_id`, `matched_project_id`, `created_at`.

Plus one key on the other side: **`GET /messages` gained `sender_user_id`**, because that
endpoint is org-wide and the message centre cannot otherwise offer Mine/All.

**Roles (the question this entry raised):** `GET /messages` needs `send_messages`
(sales_agent / sales_lead / org_admin), `GET /inbound/triage` needs nothing. So a role that
cannot send gets the triage queue **with no tab strip at all** rather than a Messages tab
that would 403, and no Reply button — replying ends in an outbound message they cannot
create (§7 rule 3). Only the sales agent's bar has an Inbox slot (05 §2); every other role
reaches it from the Home "needs a human" card or a notification, pushed with a back arrow.

**Deliberately NOT done, and why** (recorded so nobody "discovers" them again):
- `resolve` still accepts a **`note` it never stores**. Rather than ship a box whose text
  is silently dropped, no screen offers one. Wiring it would be a real (small) fix.
- `resolve` still has **no `lead_id`** — attaching goes through a contact, so a client with
  no contacts dead-ends with an honest "add a contact first" message.
- `GET /messages` still omits **`attachments`**, so the delivery trace says on screen that
  it cannot list them. The `.eml` of a dry-run send *is* reachable with no backend change:
  the `sent` event's `detail` carries `dry_run:<path>` for the existing `GET /files/{path}`.
- **There is no confidence anywhere.** 03 §9 and this entry both said the triage card shows
  the AI's confidence; `InboundMessage` has no such column and `inbound_engine` computes
  none. The card shows intent + reason + summary instead. Doc 03 §9 corrected.

**Accept:** replay dry-run **X1** (a stranger writes in → lands in triage → a human
attaches it to a lead and resolves it, nothing dropped) and **W11** (a blocked task's
chase is visible in the message center with its full delivery trail) **from the app**;
and close the F27 loop end-to-end — an AI-escalated question is opened from triage into
the assistant, answered, approved and sent, without leaving the app.

**Accepted 2026-07-29, all three, on the Vivo against the live backend:**
- **X1** — a stranger wrote in → triage → intent corrected to `scheduling` → attached to a
  client's contact → marked handled and left the queue. Nothing dropped at any step.
- **W11** — the ladder chase to Mrs. Nair is in the message centre with its status trail,
  and its delivery trace shows drafted → queued → sent with who approved it.
- **F27** — a client question the AI refused to guess at ("No data found to answer — the AI
  never guesses") was opened from triage into the assistant, drafted by the email agent,
  approved and sent, entirely in the app. Its delivery trace, .eml included, is in the
  message centre.
Suites after the backend change: **pytest 74/74** (67 + 7 new, each watched failing with
its own fix disabled), dryrun **43/43**, gap **21/21**, stakeholders --stub **21/21**, new
`scripts/verify_live_inbox.py` **17/17** against the real model.

## Phase 7 — Money & ops

### 7.0 — FIRST: close FINDING F28 (the assistant must understand short, natural commands) ✅ **DONE & device-verified 2026-08-03** (app `0.7.1-f28`)

> **DONE.** The backend was unfrozen for this one named job and **re-frozen** after. All
> five fixes are in; the acceptance below passed on the real device, typed by hand into the
> Jarvis tab. Full write-up — including the two deliberate deviations from the plan and the
> test that passed with the fix deleted — is **`FINDINGS.md` → F28 → "How F28 was fixed"**;
> the lessons are handoff **§6i**. What follows is the original plan, kept as the record of
> what was agreed.
>
> **Do this before the money screens.** It is not an invoicing task; it is the assistant's
> core competence, and every phase from here adds more agent tools that would inherit the
> same weakness. Full write-up, with the observed device evidence and the
> exact code references, is **`FINDINGS.md` → F28**. Read that first; this is the summary.

**The problem, in one line:** a person typing *"Draft an email to EKAGHNI MUKHERJEE at
Orchid International School"* gets a lookup failure, because `resolvers.py:142` only checks
whether the typed hint sits *inside* the stored name and never the reverse. Phase 6 worked
around it by pre-filling labelled lines; that fixed one app-generated command and nothing
a human types.

**The rule this phase must deliver** — it applies to the **whole Jarvis tab**, not only the
Inbox reply route:

> A sales lead or agent may type a very short or ambiguous command about anything. The AI
> either resolves it and proceeds, or states its understanding and asks one clarifying
> question — *"my understanding is X, shall I proceed?"*. **Failing with a lookup error is
> not an acceptable third option.**

**The five fixes (agreed with the user 2026-07-29):**
1. **Bidirectional, token-aware resolution** in `resolvers.py` — exact id → exact
   email/phone → email *contained in* the hint → hint inside name → **name inside hint** →
   significant-token overlap. All five resolvers, not just contacts.
2. **Strip the client's words from the contact hint** before matching (`resolve_contact`
   already has the `Lead`) — kills *"NAME at CLIENT"* generically.
3. **"Unsure" becomes a question, not a failure** — a *needs confirmation* outcome carrying
   candidates, rendered as a question card instead of the red "failed" badge.
   **Policy: ASK, NEVER GUESS** (user's decision). One clear match → proceed *and name the
   recipient out loud*; several or none → ask first. Never silently pick a recipient.
4. **A routing line for replying to an inbound message** in `orchestrator.py` — today
   "write a reply…" is grabbed by the proposal agent, which answers in the chat and creates
   nothing.
5. **Tool descriptions** say "the person's name only" — a hint, **never the fence**
   (F9/F4/F23: a prompt instruction is not a fence; fixes 1–3 are).

**App change that comes with it:** revert `strings.xml/triage_reply_prompt` from Phase 6's
labelled lines back to natural phrasing.

**Accept 7.0:** from the **Jarvis tab**, typed by hand, on the device — *"draft an email to
<person> at <client> about X"* produces a real draft; a genuinely ambiguous name produces a
clarifying **question** (not a red failure) and proceeds once answered; a one-word command
naming nobody asks who rather than guessing. Plus unit tests asserting **both** directions
(the long phrase resolves, the ambiguous hint still asks) — each watched failing with its
fix disabled — and the usual pytest + dryrun + gap + stakeholders --stub all green.

**✅ Accepted 2026-08-03**, every clause, on the Vivo as Siva with `EMAIL_MODE=dry_run`:
*"Draft an email to EKAGHNI MUKHERJEE at Orchid International School about the workshop
dates"* → real draft + Approve & send, and the reply named the recipient out loud;
*"…to the finance head at…"* → amber **"One quick check"** card, three candidate chips and
*"Nothing has been drafted or sent yet"* — no red badge; tapping **Mrs. Nair** filled the
box and sending it completed the draft to her; the reverted natural triage prompt drafted
the refund-policy reply. Suites: pytest **86/86** (+13 new, falsification matrix run —
every fix disabled one at a time turned it red), dryrun 43/43, gap 21/21, stakeholders
--stub 21/21, new `verify_live_resolution.py` **16/16, three runs running**. No schema
change. **Two findings were opened while doing this and then also fixed the same day** under
a second unfreeze — **F30** (drafts reaching the approval gate with `[Name]` blanks, most of
them past the card's 300-char preview) and **F29** (the digest bucketing follow-ups on the
UTC date). Final state after both: app `0.7.2-f30`, pytest **96/96**,
`verify_live_resolution.py` **19/19 across three runs**. See FINDINGS → F30 / F29.

### 7.0b — BEFORE the money screens: close FINDING F31 (genericity) ✅ **DONE & device-verified 2026-08-03** (app `0.7.3-f31`)

> ✅ **DONE.** All of it, plus two corrections to F31's own write-up (the `currency` field was
> never on the wire — `_project_dict` had never serialised it; and `_estimate_value` also
> returned `None` for a flat-priced engagement) and **three further sites the new guard found
> by itself**, two of them in `planning.py`, which F31 had certified clean.
>
> **Accept criteria, met:** a per-seat/per-rack client gets a correct `value_estimate`
> (`970000 = 40 × 18,000 + 250,000`, live); the amendment carries **their** unit
> (`unit='per rack'`, live); no LLM prompt names an industry (AST-enforced); a USD project
> renders as **`$210,000`** on the Vivo; no user-visible literal is hardcoded outside
> `strings.xml`; and **two regression guards** now check all of it —
> `tests/test_genericity.py` and `scripts/check_hardcoded_strings.py` — so it cannot recur a
> fourth time. `verify_live_genericity.py` **15/15 against the real model**; falsification
> matrix **18/18**. Backend **RE-FROZEN**. Write-up: `FINDINGS.md` → F31 → "How F31 was
> fixed"; lessons: handoff **§6j**.

<details><summary>The original argument for doing this before §7.1 (kept for provenance)</summary>

> Same shape of argument as §7.0, and it is the reason §7.1 is not the front of the queue.
> **Domain-genericity is working principle 2 and the product's headline claim, and a
> 2026-08-03 re-audit found it incomplete in two LIVE places** — a project's value estimate
> is silently `None` for any client not priced "per student", and a scope-change amendment
> writes *"per student"* into a client-visible document. A third, a live LLM prompt
> hardcoding *"education-services company"*, is dead code today **but lives in
> `document_engine` — the exact file §7.1 builds in** (`create_invoice`, `record_payment`,
> `add_deliverable`).
>
> **It is not backend-only.** A wider pass added two **app** defects: the money formatter
> hardcodes `₹` and throws away the `currency` the backend already stores per project (a USD
> project renders as rupees), and `ProjectDetailFragment:619` hardcodes a user-visible
> *"e.g. principal…"* hint as a Java literal — invisible to a `strings.xml` grep, which is
> how the first write-up missed it. **So this needs a backend unfreeze AND an app build.**
>
> **Do it first**, because §7.1 works in these files: fixing after means editing the same
> code twice and risks copying the pattern into new code. **Backend is FROZEN — F31 needs an
> explicit unfreeze.** Full write-up with verified call paths and fix order:
> **`FINDINGS.md` → F31**.

</details>

**Accept 7.0b (all met — see the DONE block above):** a client whose pricing unit is *per seat* gets a correct `value_estimate`;
a scope amendment for that client carries **their** unit, not "per student"; no LLM prompt
names an industry; **a project in a non-INR currency renders in its own currency on the
device**; no user-visible domain hint is hardcoded outside `strings.xml`; and **regression
tests grep every prompt for industry words and check for hardcoded user-visible literals**,
so this cannot recur a fourth time (§6c was over-confident twice, and F31's own first
write-up under-counted). Plus the usual pytest + dryrun + gap + stakeholders --stub green,
each new test watched failing with its fix disabled, and device verification of the two app
items.

### 7.1 — Money & ops proper ← queued behind **Round 7**

> ⏸ **NOT the current work.** A full end-to-end simulation (**Round 7**) is **in progress and
> paused at Act 2** — driver: `Workflow_simulation/SIMULATION_RUNBOOK.md`, state: handoff
> **§8-pre8**. Finish or formally abandon that before starting §7.1.
>
> Round 7 is also **direct input** to this phase: the screens §7.1 builds — invoices,
> incidents, vendors, leave, bookings, deliverables — are precisely the ones Round 7 cannot
> reach from the app, so its Track B results say what the backend already does and what the
> UI must expose.
>
> Builds in `document_engine` (`create_invoice`, `record_payment`, `add_deliverable`,
> `build_amendment`) — the file §7.0b just cleaned. **Before adding a prompt or a screen
> here, run `pytest tests/test_genericity.py` and
> `python scripts/check_hardcoded_strings.py`**; they are what stops F31 recurring, and new
> code is exactly where it would.


Invoices (create/send/record-payment/ladder trail), incidents lifecycle
with lesson→playbook suggestion visibility, vendors, leave, bookings,
deliverables.
**Accept:** replay W25 (advance invoice→reminders→payments→closure) and
W22 (complaint→incident→fix tasks→resolve w/ lesson) from the app.

## Phase 8 — Admin & platform

Full admin area (staff/programs/pricing/templates/teams/settings/
integrations/approval-rules/skills/playbooks/audit/privacy), insights
dashboards (MPAndroidChart), org onboarding wizard; `platform` flavor
(super admin).
**Accept:** X7 from the app — onboard a brand-new program end-to-end
with zero code changes; create an org from the platform flavor and log
into it.

## Phase 9 — Push, polish, release

FCM end-to-end (backend G1 **already built & dormant** — supply the two
Firebase files and it lights up; app side: FcmService + channels + deep
links + `/devices` registration), performance pass (cold start <2s on
mid-range, list jank zero), accessibility audit, pen-test checklist
(09), Play internal track.
**Accept:** approval push arrives <5s after backend event with app
killed; full offline day survives; release build signed.

## Testing continuously (not a phase)

- Fixture harness: script hits the dry-run backend and freezes JSON
  fixtures for MockWebServer unit tests (repositories, mappers).
- Contract check in CI: ApiService route list ⟷ backend `/openapi.json`
  diff fails the build on drift.
- One instrumented smoke per phase (Espresso): login→home→key flow.
- Manual device matrix: one small (SD 680/4GB), one mid, one flagship;
  Android 8, 12, 15.

## Credentials & assets I will ask YOU for (per phase — never hesitate list)

| When | What I need from you |
|---|---|
| Phase 0 | Backend reachable from the phone: LAN IP or a tunnel (ngrok/cloudflared) + confirmation of demo logins (seeded users use `Password@123`) |
| Phase 0 | App name final ("YuviPep"?), logo files (SVG/PNG hi-res), brand color confirmation |
| Phase 3 | Go-ahead to add backend G3 endpoint (+ G7 if not done in Phase 0) |
| Phase 5 | A physical device test session for mic/locale quality (Indian-English) |
| Phase 9 | **Firebase — TWO files from ONE free Firebase project** (I'll walk you through creating it, ~10 minutes): ① `google-services.json` (Project settings → Add Android app) goes into the app module; ② a **service-account private key .json** (Project settings → Service accounts → Generate new private key) goes on the backend server, path set as `FCM_SERVICE_ACCOUNT_JSON` in `.env` — the moment it's set, the already-built push sender wakes up. Nothing works without these; that's why push is Phase 9 and polling carries us until then. |
| Phase 9 | Release keystore decisions (I generate; you store passwords), Play Console account if publishing |
| Optional | Crashlytics yes/no; production domain for cert pinning |

## Definition of "impressive" (the bar every phase is judged by)

1. Cold start to useful briefing < 2 seconds (cache-first).
2. Any client-visible artifact is one tap from approved-and-sent.
3. Every AI output can answer "why?" in one tap.
4. Voice can do anything typing can.
5. Zero dead ends: every error names a next step.
6. A school, an IT company, and a caterer all see *their* vocabulary —
   never each other's.
