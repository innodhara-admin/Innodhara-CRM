# Round 7 — Full end-to-end simulation runbook

---

## ⛔ THIS FILE IS HISTORY. Round 7 is CLOSED and its database is GONE.

> **Read this before anything else in this file.**
>
> **The Round 7 database was deliberately WIPED on 2026-08-06**, with the owner's authorisation,
> to build the Workflow2 datacentre demo. Backed up first to
> `data/_backup_round7_evidence_20260806-101259/` (DB + `.env`).
>
> **Therefore, everywhere below:**
> - the DB-state block (leads 9 · contacts 16 · 4 open conflicts · plan v5 draft …) **no longer
>   describes anything.** Those rows are in the backup only.
> - the **5 "do not approve" protected items are gone.** Nothing to protect; nothing to avoid.
> - hard rule 3 (*"do not wipe — the DB is the evidence"*) has **expired**. It did its job:
>   every finding it protected is now written up in `FINDINGS.md`, which is the durable record.
> - `EMAIL_MODE` is **`smtp` (LIVE)** again, not `dry_run` — restored for the demo. Any "it is
>   dry_run" line below is stale.
>
> **The current work is `Workflow_simulation/Workflow2/`** — the datacentre demo: three meeting
> recordings and a click-by-click walkthrough. This Workflow1 folder is the Round 7 simulation
> that produced findings F32–F58, kept so the reasoning behind them can be traced.
>
> **`FINDINGS.md` is the authority on every finding** and is current.

---

## ⏸ Where Round 7 ended — historical (2026-08-06)

## ✅ ROUND 7 COMPLETE · ⚙ FIXING PHASE TRANCHES 1, 2 & 3 DONE

**60 findings exist across the project (F1–F63). 55 fixed · 2 open · 3 closed without a
code fix.** Only **F35** (needs an IMAP policy decision) and **F59** (a pre-existing,
undiagnosed live-script regression) remain. **F60–F63 were raised after Round 7**, while
building the datacentre demo, and are all fixed. `FINDINGS.md` is the authority and
its **status table** carries a "how it was fixed" verdict on every row.

Three named unfreezes were used and all are now **closed; the backend is FROZEN again**:
tranche 1 (*"Group 1 + Group 2 minus F35/F54, plus F50"*), tranche 2 (*"F39, F40, F44, F43,
F45, F46+F57"*) and tranche 3 (*"investigate F42; fix F36, F48, F52, F53, F58, F38, F54, F55,
F56"*).

#### Tranche 1 (2026-08-05)

| Finding | State |
|---|---|
| **F49** superseded plan kept a live approval | ✅ **FIXED** — shared `retire_superseded_plan` + newest-version guard (409) + a second guard shape, and a path this fix would have broken was repaired |
| **F47** `[missing:…]` in a real client PDF | ✅ **FIXED** — all three sub-items, incl. *why* `context_summary` was empty |
| **F51** task router ownership | ✅ **FIXED** — ownership on 6 routes, lead-only `confirm_assignments`, app chips mirrored |
| **F50** client update dropped silently | ✅ **FIXED** — both bare returns record a decision |
| **F41** first meeting drops its people | ✅ **FIXED** — incl. consequence #4 (the backfill) |
| **F55** wrong-project stakeholder | ✅ **FIXED** — the `.first()` half here in tranche 1; the contract half in tranche 3 |
| **F56** commitment register write-once | ✅ **FIXED** — prompt + guards here; **live-verified 6/6 in tranche 3** |

**Two spec-check passes are now DONE** — F35–F49 (2026-08-05, before tranche 1) and
**F50–F53 + F57–F58** (2026-08-05, also before tranche 1). No finding was overturned in either. The second pass **split F51 three ways**, found a
**fix-trap for F52** (do NOT propagate its fix to the Sync Engine — Workflow 10 defines the
ladder's overdue as `due_date < now` on purpose), established that **F53 must ship with F52**,
and found that **F58's "84" should read "84 dead-end, 19 of them wrongly"** (65 are `digest`,
which F58 itself concedes is fair).

### ⚠ Three things the next session must know

1. ⏹ **STALE — `EMAIL_MODE` is `smtp` (LIVE) again since 2026-08-06.** (Historical: it was set to
   `dry_run` for the fixing phase
   so no fix could mail the 4 protected outbound approvals. **The `.env` line is commented with
   this.** Restore `smtp` when you next want live mail; nothing else was touched
   (`CALENDAR_MODE=google`, `INBOUND_EMAIL_MODE=off` both unchanged).
2. ✅ **The APK WAS rebuilt and installed on 2026-08-06 — the device now runs
   `0.7.4-round7fixes`** (was `0.7.3-f31`, the build all of Round 7's evidence came from; the owner
   authorised the replacement). Installed with `adb install -r`, so **`base_url` survived at
   `http://127.0.0.1:8000`** and the session restored. Smoke-checked: the app launches, signs in
   and pulls a live briefing. **The app-side fixes are still only smoke-tested, not exercised** —
   except F52, which the briefing incidentally proved (see below).
3. **NOTHING from ANY of the three tranches was device-tested.** Everything is proven by the suites and by
   **falsification** — removing each fix and watching its own test fail — never by tapping the
   phone. Suites at the end of tranche 3: `pytest` **182/182** (baseline 104), dryrun 43/43,
   gap 21/21, stakeholders 21/21, live genericity 15/15, live resolution 19/19,
   `verify_live_commitments` **6/6**, both guards unchanged (the 2 reported literals are
   F37's, deliberately unmoved).
4. ⚠ **`verify_live_resolution` failed once and passed on re-run** — the model emitted `[Date]`
   placeholders and F30's fence correctly refused the send. Model non-determinism, not a
   regression; the script assumes the model leaves no blanks. **n=1 lies** — re-run before
   filing anything.

#### Tranche 2 (2026-08-06) — F39, F40, F43, F44, F45, F46, F57 all fixed

**F39** the recorder's mic no longer runs behind a "Paused" label (**app code; the APK was still not installed, so this is compile-verified, not device-verified** — and the app has no test harness at all) · **F40** upload now LINKS the consent the human captured and REFUSES when none exists, so the API can no longer manufacture its own evidence · **F44** a leading `Subject:` line is promoted into the subject field and all six reply sites get a fallback · **F43** shares `sync_engine`'s ranking so the assistant and the Delivery card cannot disagree again · **F45/F46/F57** the query agent gained `list_approvals` and `explain_decision` and now carries `assignment_reason` verbatim.

**⚠ F59 is NEW and pre-existing** — `verify_live_assistant_context.py` is **4/6, was 6/6**. Found while checking for an F19-class regression; **isolated by reverting the new tools and reproducing the identical 4/6**, so it is not from this session. That script is **not in the standard suite list**, which is why it went unnoticed for two weeks.

#### Tranche 3 (2026-08-06) — F36, F38, F42(text), F48, F52, F53, F54, F55, F56, F58

**F42 was INVESTIGATED and largely REFUTED** at the owner's request — its "structural
double-count" is correct behaviour (two tasks, two deadlines) and the claimed spec
self-contradiction dissolves; only the raw-fragment TEXT was a defect · **F38** fixed by
**inverting the flow** (the scan proposes, the SAVE decides) rather than patching the address ·
**F54** now raises an incident from a meeting, sharing the inbound core · **F56 is now LIVE-
VERIFIED 6/6** — the merge adds commitments and a restated promise adds no duplicate ·
**F52+F53** shipped together · **F55** both halves done.

### ✅ F52 is device-verified (2026-08-06)

Siva's briefing on 06 Aug, with every task due **05 Aug**: **Overdue → Coming up → Follow-ups,
with NO "Due today:" heading.** Under the old code `today` was `due <= today`, so those tasks
were in BOTH lists and the header would have rendered over empty space. Its absence is the fix.

### 🔴 Still open — 2: **F35** (IMAP; needs a policy decision) and **F59** (pre-existing regression)

**Act 14 result in one line:** the **offline decide queue, logout/login churn (F1) and voice all
PASSED** — the offline queue notably well (persistent card label, server untouched, drained in
5 s, applied once). Two findings: **F57** (an approvals question is answered from the *task
list* — no agent can see approvals; proven on two roles) and **F58** (**84 of 125**
notifications dead-end on *"a later phase"* for screens that are already built). **[F49] became
device-proven during this act by operator error** — see the state note below.

**Act 13 result in one line:** the **best extraction of the round** (0.876/408 words, all six
promises captured, every task assigned *and* dated at confirm, three re-graded P2→P1) and the
**protected state survived a fourth meeting** — but a complaint said face-to-face never became
an incident (**F54**), a second campus produced no opportunity while its decision maker was
attached to *this* project (**F55**), and the commitment register turned out to be **write-once**
(**F56**). **W25 was not testable** — no invoice exists, so no ladder to pause; that is a
precondition, **not** a bug.

### ⏹ What remains — HISTORICAL, all of it has happened

> The paragraphs below were written while Act 14 was still pending. **Act 14 ran on 2026-08-05
> and two fix tranches have landed since.** They are kept only so the sequence can be traced.
> **Do not act on them** — the live position is the block at the very top of this file.

~~**One act is left: Act 14.**~~ It ran. ~~**Do not start fixing before Act 14 runs.**~~ That
condition was met, and fixing has since happened under two named unfreezes, both now closed.
`FINDINGS.md` → *"Round 7 — fix order"* still holds the fix plan, but its group tables are a
**historical plan, not a to-do list** — read the status table for what is actually done.

~~**Do not start fixing before Act 14 runs.**~~ ⏹ **Satisfied** — Act 14 ran first, exactly as
this rule intended, and F51 was fixed afterwards.

**Act 12 result in one line:** **W16 and W11 PASSED** end to end; **W14 FAILED** — a completed
client-visible task never reached the client and nothing recorded that it hadn't (**F50**).
Four findings (**F50, F51, F52, F53**) and one **correction to F43**.

### ⚠ The environment did NOT survive the gap between sessions — it was restarted 2026-08-05

The previous handoff said the backend was left running. **It was not running at 15:10 on
2026-08-05**: `/health` refused the connection, no `python.exe` was alive, nothing listened on
9010, and the `adb` daemon had to cold-start (which clears `reverse` tunnels). The app was
sitting on the **login screen** — no session. All of this was restored per §8-pre8, and the
**DB was verified intact against the baseline below before any tapping**.

**Do not trust "left running" in a handoff — verify it.** `/health`, `adb reverse --list`, and
the app's foreground activity each took one command.

### Environment — verified at session end 2026-08-06

> ⏹ **STALE — `EMAIL_MODE` is `smtp` (LIVE) again since 2026-08-06.** (Historical: it was
> `dry_run` for the fixing phase
> so no fix could mail the 4 protected outbound approvals, and the `.env` line carries a comment
> saying so. **Restore `smtp` when you next want live mail.** The row below is otherwise current;
> the backend was last restarted on the FIXED code, log
> `…\scratchpadackend_fixphase.log(.err)`.

| | |
|---|---|
| Backend | **RUNNING**, `PORT=9010`, restarted 15:12, `Platform ready` in the NEW log, `/health` → `{"status":"ok","llm_provider":"openrouter"}` |
| Backend log | `…\scratchpad\backend_act12.log` (**access log = stdout**) + `.log.err` (startup/warnings) |
| `adb reverse` | **SET** — `UsbFfs tcp:8000 tcp:9010` |
| `.env` | ⏹ **STALE.** Now: **`EMAIL_MODE=smtp` (LIVE)** · `CALENDAR_MODE=google` (LIVE) · `INBOUND_EMAIL_MODE=off` · `WHATSAPP_MODE=dry_run` |
| App | **`0.7.4-round7fixes`** (rebuilt + installed 2026-08-06), foreground, **signed in as Siva (sales_lead)**, on Home |
| `logcat` | **restricted on this Vivo** — returns 0 lines. Do not plan on it; use the backend log + DB |
| Embeddings | **DEAD** — Gemini 429 "prepayment credits are depleted". Semantic memory off for the whole round; do not mis-attribute weak recall to code |

`adb` is not on PATH: `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`.

### Database state — FINAL, after all 14 acts (machine-verified 2026-08-05)

```
leads 9 · contacts 16 · stakeholders 2 · meetings 4 · demos 3 (1 real Google event)
plans        v1-v4 superseded · v5 DRAFT (held by conflicts) · v6 ACTIVE
             current_plan_version = 6
conflicts    4 OPEN                                     ← protected evidence, do not resolve
approvals    5 pending · 5 approved · 1 rejected · 1 expired
outbound     2 sent · 4 pending_approval · 2 rejected   ← unchanged since Act 11; 4 of the
                                                          pending are protected evidence
action_items 34 open · 3 cancelled · 1 done · 0 pending_review
assignments  14 proposed · 1 declined
client_commitments 11 — ALL from meeting 1 (that IS F56)
incidents 0 · invoices 0 · payments 0 · deliverables 0  ← never reached; incidents 0 IS F54,
                                                          invoices 0 is why W25 was untestable
```

> **Three of those zeros are findings, not gaps in the run:** `incidents 0` after a real
> face-to-face complaint is **F54**; `client_commitments 11, all from meeting 1` after four
> meetings is **F56**; `stakeholders 2` with **neither holding an email address** is what
> **F50** trips over. Do not "fix the data" — it is the evidence.

**⚠ Act 14 changed the plan state — expect these when diffing against Act 13:**
- **Plan v6 is now ACTIVE** (`current_plan_version = 6`), v1–v4 all `superseded`, **v5 still
  `draft`**, **4 conflicts still open**. v6 was approved as the Act 14 offline-queue test.
- **An operator error approved the Plan v2 card** (the F49 landmine) at 11:44 — a scripted
  element lookup returned null and the script did not abort, so hardcoded taps fired blind on
  admin's Home. It rolled `current_plan_version` **4 → 2** exactly as F49 predicted; the v6
  activation then repaired the pointer. **No email was sent.** **Residue: five `blocked=1`
  scope-expansion tasks from v2 are now `open`** that would otherwise be `pending_review` —
  activating a newer plan does **not** retract them. This converted F49 from *code-verified* to
  *device-proven*; see its entry.

**Act 13 changed only:** meeting 4 + its transcript, 6 new `open` tasks (assigned & dated),
plan **v6 `pending_review`** + its approval, and Mrs. Kulkarni (contact + stakeholder).
**v4/v5 and the 4 conflicts were not touched.**

**What Act 12 changed, and nothing else:**
- `Revise content per Arjun's feedback` → **done** (Baski, with a result note) — F50's evidence.
- `Train and schedule facilitators` → **declined by Sourav, re-routed to Mithun**, then
  **blocked** by Sourav with reason *"Venue confirmation from the school is still pending"* —
  F51's evidence. Leave it blocked; it is the only blocked task on the project.
- 2 notifications to Mithun about a refused date change (I fired the ripple test twice to catch
  the Snackbar — the duplicate is mine, not a bug).

### ⚠ The protected approvals MOVED — they are in YuviPep Admin's queue now, not Siva's

The restart's startup sweep escalated **5 of the 6 pending approvals** from Siva to
**YuviPep Admin** (*"Approver did not act before expiry"* — they expired while the backend was
down). **Nothing was approved; all are still `pending` and the evidence is intact.** But the
old instruction "parked in Siva's queue" is stale. Current holders:

```
PENDING NOW (5) — re-verified 2026-08-05 after Acts 13–14:
eedb263b  YuviPep Admin  outbound_message  Telaverge intro redraft         ← F38, DO NOT APPROVE (sends real mail)
1aa4fc77  YuviPep Admin  outbound_message  Reply to Arjun (content change) ← F44, DO NOT APPROVE
85eb8a81  YuviPep Admin  outbound_message  Reply to Mrs. Nair (scope)      ← F44, DO NOT APPROVE
c74f132e  YuviPep Admin  outbound_message  Reply to Mrs. Nair (date)       ← F44, DO NOT APPROVE
99ea84d2  Siva           price_change      59,000 → 50,000 (~15%)          ← legitimate; stage=recommend,
                                                                             so it does NOT show in the
                                                                             default decide-stage queue

DECIDED 2026-08-05, no longer pending — do not go looking for them:
79d646f0  plan_change  APPROVED by operator error → became F49's device proof (see F49)
1c7419f6  plan_change  APPROVED deliberately — plan v6, the Act 14 offline-queue test + the repair
```

### ⏹ Things that must NOT be touched — ALL MOOT since the 2026-08-06 wipe

> Every row named below was deleted with the Round 7 database. **Nothing here is protected any
> more and nothing here can be broken by accident.** Kept because it records what each finding
> was proven against. Original text follows.

1. **Plan v5 must stay `draft` and the 4 conflicts must stay open.** 🔴 **Still true.** They are
   Act 11's proof that a re-plan is held while the client's own people disagree, and they are
   live evidence for **F43** (neither the briefing nor "What's blocking?" mentions them) and
   **F58** (a conflict notification does not even navigate). Verified still intact after Acts
   13–14: **v5 `draft`, 4 conflicts `open`.** Do not resolve them.
2. ⏹ **MOOT — "Plan v2: Scope expansion" was approved on 2026-08-05** (by operator error during
   Act 14; see the state note above). **There is nothing left to protect here** — the card is
   decided and cannot be re-approved. It did exactly what F49 predicted: `current_plan_version`
   rolled **4 → 2**, which the v6 activation then repaired to **6**. The lasting residue is
   **five `blocked=1` tasks left `open`** that activating a newer plan did not retract. F49 is
   now **device-proven** rather than code-verified — that is the finding's strongest evidence, so
   do not "tidy up" those five tasks without recording what you did.
3. **Do not approve the "Telaverge intro redraft"** — **F38**. Still addressed to the dead
   `mekaghnni@`. ⏹ **MOOT since 2026-08-06** — this message was deleted with the Round 7 wipe. There is nothing left to approve by accident. (It lives on in the backup only.)
4. **Do not approve the two reply drafts** unless you intend to demonstrate **F44** — both
   have `subject=NULL` and open with a literal `Subject:` line, so they send as subjectless
   email.
5. **Do not re-send the proposal email** — the one already delivered carries F47's
   `[missing:context_summary]` placeholder and is that finding's evidence.

The other two pending approvals are legitimate and may be decided as the story requires:
the **price_change** (Siva) and **plan v6** (raised by Act 13's merge, held for sign-off).
There is no pending "plan v3" approval — v3's was correctly expired; only **v2's** was orphaned,
which is exactly what F49 is about.

### Already sent for real — do not repeat

- IBC proposal, **₹59,000**, PDF attached → `ekaghni.mukherjee+nair@gmail.com` (F47 evidence)
- Demo invite, *"Demo confirmed for Thursday, 13 August 2026 at 10:00"*
- **Real Google Calendar event** `gktjtjndt67acf0phnp6k4toi8`, 13 Aug 10:00, team Alpha —
  deliberately booked into Alpha's existing slot to test clash detection (it warned correctly)

### Scenario artifacts that are NOT bugs — do not file these

- **Tasks born overdue.** `meeting2` asks to move the start from 15 Aug to **1 Aug**, which is
  in the *past* relative to the real clock (4 Aug 2026). The recordings were written assuming
  an earlier "today". Whether the app *should* push back on a client naming a past date is a
  fair feature question, not a finding.
- **The scope-growth amendment never priced.** `accepted_proposal` requires
  `status == ACCEPTED`; ours is only `sent`. There is no locked baseline to amend, and the
  engine correctly declined to invent one. **To exercise W19 properly, mark the proposal
  accepted first.** Checked in code — do not re-file.

| Act | State |
|---|---|
| 1 — Cold start, Rahul logs in | ✅ **PASS** — correct role + tabs (Home·Leads·Jarvis·Tasks·Inbox), briefing pulled real data ("Green Valley School (whatsapp) — Check interest after first call"), My-day cards (Demos 2 this month, Follow-ups 1 due today), honest empty state on *Waiting on you* |
| 2 — Business card (W2) | ✅ **PASS, with F38 found.** Real card scanned at 86%: all four fields real, confidence labelled, org-mismatch line honest, draft queued with "nothing was sent" (F2 holds). **OCR misread the email** (`mekaghnni@` for `mekaghni@`) → correcting it fixed the contact but **not the queued intro** → **F38** |
| 3 — First meeting (W1) | ✅ **PASS.** Real 03:09 recording, transcript clean (**0.857**, 383 words), all six pipeline stages advanced. Found **F40** (consent record attached to the meeting is hardcoded `in_app`, discarding the *verbal* method the user chose) |
| 4 — Review gate | ✅ **PASS.** Edit persisted, drop → `cancelled`, added item → `open`, meeting → `completed`, **no duplicates (F22 holds)**. The one item with no due date got one at confirm, so **F8 holds** too |
| 5 — Plan & who gets the work | ✅ **PASS on assignment.** Plan v1 → approval → **Siva (sales_lead)** approved → activated → **9 assignments, each with a real reason** ("expert skill match, 0/8 open tasks", "did 2 related task(s) on this project", ties flagged "lead should confirm or change"). No "no skill match" fallback. 3 tasks unassigned **by design** (`assign_on='when_ready'`). **The skill-vocabulary watch item did NOT materialise.** Found **F41**, **F42**, **F43** along the way |
| 6 — Ask Jarvis (X6) | ✅ **PASS on F28 — no lookup errors**, every terse command answered. But two answers were wrong: **F45** (`who is doing the curriculum` → the *client's* coordinator; `who is assigned to the curriculum task` → correctly Baski) and **F46** (`why did you pick X` cannot be answered from data by any agent) |
| 7 — Proposal + one approval tap (W3) | ✅ **PASS, with F47 found.** ₹59,000 with **every unit price locked from the pricing table** (2000×12, 500×40, 15000×1), no discount (**F23 holds**), PDF renders, `the principal` → Mrs. Nair resolved correctly, **real email SENT** (`status=sent`, `smtp:…`). **But the PDF body carries `[missing:context_summary]`** → **F47** |
| 8 — Book the demo (W21) | ✅ **PASS on all three conditions.** **Real Google event** (`calendar_event_id=gktjtjndt67acf0phnp6k4toi8`; the seeded demos have none) + **real invite sent** to `+nair@`. **Clash detected and stated honestly** ("Heads up: Alpha already has a demo on 2026-08-13"), and the app said *"the calendar invite is drafted and waiting in Approvals — nothing has been sent yet"* rather than pretending. Found **F48** (the role refusal points at a capability that doesn't exist) |
| 9 — Client replies (W4, W19, W20, W18) | ✅ **4 of 5 PASS, 1 not exercisable.** Price push → `price_change` approval to **sales_lead** with the discount computed (~15%), no casual yes. Content complaint → revision task **+** acknowledgement draft. Date shift → **plan v3, 12 tasks re-dated by 17 days**, held behind approval. Question → `needs_human`, *"No data found to answer — the AI never guesses"*. **Scope growth could not be tested** — see the precondition note below. **F44 widened substantially** |
| 10 — Second meeting (W6) | ✅ **PASS — the best act of the round.** Transcript **0.896**/354 words. A true **merge**: plan v4 active, v1–v3 superseded, **every prior task survived with its status**, and the superseded ones (`Procure/Deliver 40 maker kits`) were **cancelled on activation**, not at merge time — the change was correctly held behind the approval. 12→16 workshops, digital materials, teacher training (3 tasks), start date moved, all captured. **F41's cause PROVEN** — see below |
| 11 — Contradiction (W7) | ✅ **PASS — the best behaviour of the round.** **4 conflicts raised**, each naming *both* positions with correct attribution ("Mr. Rao wants…; **Arjun says**…") across scope, dates, audience **and** the discount. All `open`, all raised to **Siva**. Plan **v5 held in `draft`** with `held_plan_id` set, **v4 still active**, and **no approval was even offered** for v5. The review gate extracted exactly **one** neutral task — *"Send revised plan for both positions"* — it did **not** pick a side. Transcript 0.845/287 words |
| 12 — The other side of the house (W16, W11, W14) | ✅ **2 of 3 PASS, 1 FAIL.** **W16 PASS** — decline needs a reason, keeps the declined row with its note, re-routes excluding the decliner, and lands on Mithun with a *better* reason (`good`→`expert` skill match). **W11 PASS** — red banner names the blocker; a new date that breaks two dependents is **refused, routed to the phase lead with both breaks named**, and the user is told by Snackbar. **W14 FAIL → F50** — a client-visible task completed and the client update was **silently dropped**. Also **F51** (a non-assignee blocked another user's task), **F52/F53** (nothing tells you what is late), and a **correction to F43**. Placeholders (More/Incidents/Team) all honest |
| 13 — Delivery goes wrong (W22, W24, W25, W26, W30) | ✅ **DONE — best extraction of the round, 3 findings.** Real 3:02 recording, transcript **0.876/408 words**; all **6** promises extracted with faithful descriptions; at confirm all 6 got an assignee **and a due date** (F8 holds — dates *inferred*: certificates→3 Dec, feedback→4 Sep, vendor→12 Aug) and three were re-graded **P2→P1**. **Plan v6 raised `pending_review` behind an approval while v4 stayed active, v5 stayed `draft` and the 4 conflicts stayed open — F49 did not recur.** Mrs. Kulkarni discovered from speech (contact `source=meeting`, no invented email, + stakeholder `head`/`decision_maker`). **W26 PASS**, **W24 partial** (task yes, dependency no), **W22 FAIL → F54**, **W29/W30 FAIL → F55**, **W25 not testable** (no invoice ⇒ no ladder — precondition, not a bug). Also **F56**: the commitment register is write-once |
| 14 — The awkward paths | ✅ **DONE — 3 PASS, 2 findings.** **Offline queue PASS** (tunnel removed → Snackbar **+ persistent card label** → server untouched → drained in **5 s**, applied once, idempotency key). **Logout churn PASS** — F1 does not regress (captured 1.2 s after sign-in; Sourav saw only Sourav's data). **Voice PASS** — clean dictation, best blocking answer of the round. **F57**: "how many approvals are waiting on me" answered from the **task list**, proven on an ops agent *and* a sales lead. **F58**: 84/125 notifications dead-end on *"a later phase"* for screens that exist — including `conflict`, which kills the bell route F43 credits |

**🎯 F41 IS NOW DIAGNOSED — do not re-open the question.** Act 10 was the decisive test and it
ran. Meeting 2 (merge path) automatically created **`Mr. Rao, Trustee, source=meeting`** plus a
`trustee`/`decision_maker` stakeholder — the **first `source='meeting'` row ever written**.
Same lead, same contract, same model as meeting 1, which created nobody. **The extraction does
return people; only the create path discards them.** F41 is a pure wiring gap. The
"maybe the prompt never returns people" theory is dead — don't revive it.

**⚠ Precondition the runbook was missing — Act 9's scope-growth row cannot pass as written.**
"Add 30 more students" is supposed to produce an amendment priced from the locked rate. It
did not, and **that is correct behaviour**: `document_engine.accepted_proposal` requires
`status == ACCEPTED`, and our proposal is only `sent`. There is no locked baseline to amend
against, so the engine rightly declined to invent one (it created plan v2 + a reply saying
"commercials to follow"). **To exercise W19 properly, mark the proposal accepted first**, then
re-log the scope request. Do not file the missing amendment as a bug — it was checked in code.

**Contacts now exist on Orchid** (added by hand after F41): Mrs. Nair `+nair@` (Principal,
**primary**), Arjun `+arjun@` (Science coordinator), Divya `+divya@` (Admin office).
**Acts 7–9 can now address someone.** ⚠️ **That "stakeholders are still 0" line was true when
written and is now OUT OF DATE:** Act 10 created **Mr. Rao** and Act 13 created **Mrs. Kulkarni**,
both via `sync_stakeholder_specs` on the merge path — **stakeholders = 2**. F41's point stands
unchanged: *adding contacts by hand never back-fills stakeholders*, and the **first-meeting**
path still creates none. Neither of the two has an email address, which is what [F50] trips over.

**The phone right now:** app `0.7.3-f31`, signed in as **Rahul (sales_agent)**, on the Orchid
lead's **Meetings** tab. Base URL pref `http://127.0.0.1:8000`.

> **Navigation note for Act 13+:** *Record meeting* lives on the lead's **Meetings** tab, which
> is the **6th tab and off-screen by default** — swipe the tab strip left to reveal it. The
> visible five are Overview · Contacts · Projects · Notebook · History. (Same discoverability
> shape F43 notes for the project's Conflicts tab.)

**Logins used so far** (all `Password@123`): `rahul@yuvipep.com` (sales_agent, the driver for
Acts 1–11), `siva@yuvipep.com` (sales_lead — **plan approvals route to the sales lead, not to
the agent who recorded the meeting**), and in Act 12 `sourav@`, `baski@`, `mithun@`.
Act 13 was recorded as **Rahul**, who is the account still signed in. **Act 14 needs a
role-switch** (its wrong-role step wants an operations_agent, and its offline step wants an
account with something to approve).

**⚠ The "do not approve" list has MOVED to YuviPep Admin's queue** — see the escalation table
above. It still includes the Telaverge intro redraft, which carries F38's stale `mekaghnni@`
address. ⏹ **MOOT since 2026-08-06** — deleted with the Round 7 wipe; nothing to avoid. Kept for the story of how F38 was found. It has
already been rejected once — that was the F38 experiment, and the redraft came back **with the
same wrong address**. Leave all five queued as evidence.

**Act 2 left this state behind, which later acts depend on:**
- Lead **"Telaverge"** (created by me so the card had something to attach to; the card's own
  organisation is *Telaverge Communications (I) Pvt. Ltd*).
- Contact **EKAGHNI MUKHERJEE**, `mekaghni@telaverge.com`, +91 93105 24629, **primary**.
- One `pending_approval` intro message, `7bfd057b…`, **addressed to the wrong `mekaghnni@`**
  (F38). **Do not approve it as-is** — approving sends for real. Either leave it queued as
  evidence, or reject it and let the redraft pick up the corrected address.

**When the user says "continue":** show them the act table above, then pick up at the act
marked ⏳. **All four recordings have now been played** — Act 14 needs the user only for the
voice-dictation step. Never re-do a completed act and **never re-seed**.

### Environment — extra details (the authoritative table is the one at the top)

- Device = Vivo, adb serial `10BFBT0TXJ001NP`. `adb` is not on PATH:
  `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`. Use `MSYS_NO_PATHCONV=1` for
  on-device paths in Git-Bash.
- **Verify, don't assume.** The backend has already failed to survive one session gap — see
  the ⚠ block at the top. `/health`, `adb reverse --list` and the foreground activity are one
  command each.
- If the backend is not answering, restart per handoff **§8-pre8** (no `EMAIL_MODE` overrides
  — this run is deliberately live) and confirm **`Platform ready` in the NEW log**; `/health`
  alone is not proof (§6g).

### Hard rules — ⚠️ READ THE STATUS COLUMN. The simulation is over; two rules have expired.

| # | Rule | Still in force? |
|---|---|---|
| 1 | **Do not rebuild/reinstall the APK** — `0.7.3-f31` was the build under test | ⏹ **EXPIRED** with the simulation (2026-08-05). Its only purpose was protecting the build being tested. **App fixes are no longer blocked by this** — F36, F39, F48, F53, F58 and F37's two unmoved literals are now actionable. Rebuilding is still a change like any other and needs the same unfreeze |
| 2 | **Do not re-enable IMAP** (F35) — it marks the owner's personal mail as read | 🔴 **STILL IN FORCE**, indefinitely. This one is not about the simulation |
| 3 | **Do not wipe or re-seed** | ⏹ **EXPIRED 2026-08-06.** The DB was wiped with the owner's authorisation for the Workflow2 demo (backup: `data/_backup_round7_evidence_20260806-101259/`). Its job is done — the findings it protected are all written up in `FINDINGS.md` |
| 4 | **Backend is FROZEN** — findings get written up, not fixed | 🔴 **IN FORCE AGAIN.** The fixing-phase unfreeze (*"Group 1 + Group 2 minus F35/F54, plus F50"*) was granted 2026-08-05, used for that scope only, and is now **closed**. Tranche 2 needs a new one |
5. Sending real mail and creating real calendar events **is already authorised**; wiping,
   rebuilding and IMAP are **not**.
6. **Never tap pause in the recorder** — F39: resume is dead, the mic keeps running behind a
   "Paused" label, and the only way out is Stop (which loses the take).
7. **On animated screens, trust `screencap`, not `uiautomator dump`.** The recorder, the voice
   session and the pipeline progress screen animate continuously, so the window never goes
   idle and the dump silently returns a **stale** tree — the state from *before* your last
   tap. That is the exact shape of a false bug report; it nearly produced one for F39. Pull
   the PNG as a file (`adb shell screencap -p /sdcard/s.png` then `adb pull`); redirecting
   `exec-out screencap -p` through PowerShell corrupts it with a BOM.

   **7b — the same trap, inverted: before reporting that the app said *nothing*,
   re-capture inside 1 second.** Refusals and
   confirmations here are `Snackbar`s (`LENGTH_LONG` ≈ 3.5 s) and `Toast`s (≈ 2 s). A
   screenshot taken 5–7 s after a tap shows an unchanged screen, and the DB row is genuinely
   untouched *because the server correctly refused* — so **every instrument agrees that
   "nothing happened", and all of them are wrong**. This has now cost three near-misses in
   Round 7 (F48's Toast, the "silent reschedule gate", and Act 12's new-date ripple).
   `uiautomator dump` cannot see either widget at all.

### 🔴 Rule 8 — the three-pass rule. Read this before writing any finding or any fix.

**The system is now complex enough that a careless claim is worse than no claim.** In this
session alone, four write-ups had to be corrected *after* the owner challenged them, and four
recommended fixes would each have broken something else. Every one was caught by the owner,
not by me. So:

**Before calling something a bug — check it three times, three different ways:**
1. **Observe it** on the device, with a *reliable* instrument (screenshot, not a stale dump)
   or straight from the DB.
2. **Read the code path end to end** — the function *and its callers*. Nearly every bad
   write-up here came from reading one function and stopping.
3. **Look for the innocent explanation.** A precondition unmet (the amendment needed an
   ACCEPTED proposal), a scenario artifact (a past-dated request), a different reading of the
   question (F46's first test was unfair) — these looked exactly like bugs and were not.

If it survives all three, write it up with the evidence *and* say plainly what you did **not**
test. "Code-verified, not executed" is an honest and useful statement; a confident claim that
turns out to be untested is not.

**Before calling something a fix — check it three times, three different ways:**
1. **Who else touches this field/function?** `grep` every caller. The F41 fix would have
   double-created stakeholders; the F38 fix would have broken WhatsApp, explicitly-typed
   recipients, and proposal emails that carry no `contact_id`.
2. **What does the schema/design assume?** F42's "duplicate" is required by a 1:1 link —
   de-duplicating would break it.
3. **Prove it by behaviour, not by reading.** Run the guards
   (`pytest tests/test_genericity.py`, `python scripts/check_hardcoded_strings.py`), the
   suites, and a device check. F37 exists because a guard reported "none" for a file that
   contained the very thing it was built to catch.

**A finding that names how it could be proven wrong is worth several that merely sound
confident.** F41's write-up contained a testable prediction; Act 10 ran it and settled the
cause. That is the standard to aim for.

### Findings raised during Round 7 — 27 (F32–F58)

> ⛔ **The open/fixed split below is the state on 2026-08-05 and is now WRONG.**
> **All three fix tranches have since landed.** Of the 21 listed as "Open" below, **20 are
> fixed** — the only survivor is **F35** (it needs a policy decision, not a patch).
> **`FINDINGS.md`'s status table is the authority.**
> Project-wide the count is now **60 findings (F1–F63): 55 fixed · 2 open (F35, F59) ·
> 3 closed without a code fix (F5, F16, F26).** There are no part-done findings left.

**Fixed:** **F32** seeds never exited (corrects §6g/§6i: it happens on *success*) · **F33**
seed order silently load-bearing · **F34** malformed `email_domain` blocked adding staff ·
**F37** the F31 guard itself was blind to wrapped setter calls.

**Open (21):** **F35** IMAP read/marked-read a personal mailbox · **F36** login `server:`
label stale · **F38** a corrected address reaches the queued message by **no path**, not even
rejection · **F39** recorder pause is one-way, mic keeps running behind "Paused" · **F40**
meeting consent record hardcoded to `in_app` · **F41** first meeting drops its people
(**cause PROVEN in Act 10: wiring gap**) · **F42** commitment fragments + structural
double-count · **F43** "What's blocking?" and the briefing ignore approvals **and conflicts**
· **F44** drafts carry `Subject:` in the body; replies have no subject · **F45** "who is doing
X" → client side · **F46** "why did you pick X" unanswerable by **any** agent (no tool
exposes it) · **F47** a `[missing:…]` placeholder went out in a **real client PDF** ·
**F48** the demo refusal points at a capability that doesn't exist · **F49** a superseded plan
keeps a live approval and `activate_plan` has no newest-version guard · **F50** a completed
client-visible task's client update is **dropped with no trace whatsoever** · **F51** the task
router enforces ownership on **1 route of 23** (a non-assignee blocked another user's task —
device-proven) · **F52** *"Due today:"* is always an empty header and a task due today is
called Overdue · **F53** *"My tasks"* has no Overdue group, so late work is filed under
"Today".

**Correction recorded, not a new finding:** **F43's** claim that conflicts appear in "exactly
two places" is **retracted** — the ops lead's **Delivery** card names them
(*"4 unresolved conflict(s) blocking a re-plan"*, from `sync_engine.recompute_health`). F43
itself stands, and its fix is now clearer: `whats_blocking` should reuse that reason string.

**Act 13 added:** **F54** 🟠 a complaint made **in a meeting** never becomes an incident — the
whole of W22 (`_route_complaint`) is reachable from **email only**, and the meeting contract has
no field for a complaint. **Re-checked against the spec 2026-08-05 and DOWNGRADED to medium:**
W22 is written entirely as an *inbound* story, so this is a **product decision, not a contract
violation** — decide whether it should raise an incident before anyone fixes it · **F55** a second campus named in a meeting creates **no opportunity**,
and its decision maker is attached as a `decision_maker` on **this** project (latent only
because her email is NULL) · **F56** the **commitment register is write-once** — 11 rows from
meeting 1, **zero** from three subsequent merges, because the merge prompt only ever asks to
*renegotiate* a commitment.

**Two candidates were withdrawn rather than filed**, both by Rule 8's third pass: the missing
assignment notification (**correct** for `lead_confirm` — confirmed in code *and* the Data
Model) and "new-date does nothing" (a **Snackbar** a 7-second screenshot had missed).

**One Act 13 condition was NOT testable and must not be filed:** W25's *"payment query pauses
the ladder"*. `invoices = 0`, `payments = 0`, active reminders `0` — **there is no ladder in
existence to pause**, because the project never reached invoicing and invoice screens are
Phase 7.1. Checked in the schema and the data. To exercise W25, create an invoice first.

Full write-ups: `FINDINGS.md` → Round 7. **`FINDINGS.md` is the authority** — this list is a
pointer, not a substitute, and several entries carry corrections that matter (F41's cause,
F44's widened scope, F46's real root cause, and the fix-safety tables in F38/F41/F42/F44).

### Watch item — ✅ CLEARED (kept for the record)

The merged seed left **two overlapping skill vocabularies** — `logistics` vs
`logistics_coordination`, `proposals` vs `proposal_preparation`, `teaching` vs
`training_delivery`, where F25's premise was a single vocabulary the planner picks from.

**It never materialised.** Act 5 assigned sensibly across both vocabularies (Baski→curriculum,
Shyam→worksheets, Sourav→facilitators, Mithun→logistics), each with a real reason and ties
disclosed; Act 13 did the same (`logistics_coordination` for the vendor chase, `invoicing` for
the payment query, `proposal_preparation` for the Hinjuwadai proposal). **Treat as cleared**
unless a later act contradicts it. (Handoff §8-pre8 says the same — the two agree.)

---

**Purpose:** exercise every feature the built app can reach, on the real device, against a
freshly wiped database, with real recordings, a real business-card scan, real outbound email
and real calendar invites — and write down everything that misbehaves.

**This is not the demo script.** `DEMO_WALKTHROUGH.md` is a polished A→Z story for showing
the product. This is a *test plan*: it goes looking for trouble, includes the awkward paths
(decline, conflict, complaint, offline, wrong role), and every step has a pass condition.

---

## 0. Ground rules

| | |
|---|---|
| Backend | `PORT=9010` + `adb reverse tcp:8000 tcp:9010`; phone pref stays `http://127.0.0.1:8000` |
| Email | **LIVE** (`EMAIL_MODE=smtp`) — real mail from and to `ekaghni.mukherjee@gmail.com` |
| Calendar | **LIVE** (`CALENDAR_MODE=google`) — real events on that account |
| Inbound | **`INBOUND_EMAIL_MODE=off`** — see **F35**. Client replies go through the app's *Log a client reply* screen, never IMAP |
| WhatsApp | `dry_run` (no `WHATSAPP_PHONE_NUMBER_ID` configured) |
| Backend code | **FROZEN.** Bugs get written to `FINDINGS.md`, not fixed |
| Backup | `data/_backup_pre_sim_20260803-211931` (DB + storage + .env, 31.8 MB) |

**Logins** — all `Password@123`:

| Person | Email | Role | Tabs they get |
|---|---|---|---|
| Rahul | `rahul@yuvipep.com` | sales_agent | Home · Leads · Jarvis · Tasks · Inbox |
| Siva | `siva@yuvipep.com` | sales_lead | Home · Pipeline · Jarvis · Approvals · ~~Team~~ |
| Akash | `akash@yuvipep.com` | sales_lead | (second lead — for two-approver paths) |
| Mithun | `mithun@yuvipep.com` | operations_lead | Home · Delivery · Jarvis · ~~Incidents~~ · ~~Team~~ |
| Sourav | `sourav@yuvipep.com` | operations_agent | Home · Tasks · Jarvis · Projects · ~~More~~ |
| Baski | `baski@yuvipep.com` | operations_agent | " |
| Ananya | `ananya@yuvipep.com` | org_admin | Home · Approvals · Jarvis · ~~Admin~~ · ~~Insights~~ |
| admin | `admin@yuvipep.com` | org_admin | " |

Struck-through tabs are `PlaceholderFragment`s — Phase 7.1/8, not built. **That is the
ceiling of this simulation**, and it is why Track B exists.

---

## 1. Scope — what can and cannot be tested from the app

**Track A — reachable from the app (the bulk of this runbook).**
W1 first meeting → plan · W2 card → lead · W3 proposal built/checked/sent · W4 price +
content change · W5 follow-up ladder · W6 second meeting merge · W7 conflicts · W8 agreed →
delivering · W9 skill assignment · W10 nudge ladder · W11 blocked/dependencies · W14 task
done → client hears · W16 declining · W17 briefing/digest · W18 date shift · W19 inbound
question · W20 scope growth · W21 urgent · W26 closure (partial) · W27 branch chain ·
W28 pause/resume · W29 two projects one client · W30 relationship · X1 triage · X6 why/
blocking · X11 escalation.

**Track B — no app screens exist (driven by script, labelled as such).**
W12 leave · W13 overload · W15 new joiner · W22 incident *lifecycle* · W23 delivery day ·
W24 vendors · W25 invoices/payments · X2 cycles · X3 do_not_contact · X4 idempotency ·
X5 org isolation · X7 new program · X8 invoice dispute · X9 quiet hours · X10 courtesy cap ·
X12 auto-assign.

> ⚠️ **"Track B" means the SCREEN is missing, not that the workflow is out of scope.**
> Act 13 drove **W22, W24 and W25** through an app-recorded meeting, and their *engines* are
> backend code that a meeting can reach. So:
> - **[F54] is a valid finding, not out-of-scope.** The Incidents *screen* is a placeholder
>   (Track B), but the *incident record* is backend and should have been created. Do not
>   dismiss F54 with "W22 is Track B".
> - **W24** was likewise reachable — partially; see F54's supporting observation.
> - **W25 genuinely could not be tested**, but for a *data* reason, not a screen reason: there
>   is no invoice in the database, so no ladder exists to pause. See the precondition note.

---

## 2. The acts

Each act: **what you do**, **what must happen**, **how it fails**. Record every deviation.

> **This section is the TEST PLAN, written in the imperative — it does not change as acts
> complete.** For *status* (what is done, what passed, what is next) read the **act table** in
> the "WHERE WE ARE RIGHT NOW" block at the top. If the two ever seem to disagree, the act
> table is describing the past and this section is describing the intent; neither overrides
> `FINDINGS.md`, which is the authority on every finding.

### Act 1 — A cold start (Rahul, sales_agent)
1. Log in as **Rahul**. Home should be quiet but not empty — a fresh org still has seeded
   leads and the reminder ladder has already produced notifications.
2. Open the **bell**. Expect notifications, none of them alarming.
3. **PASS:** briefing renders, no crash, no "loading" that never resolves, offline banner
   absent.
4. **Watch for:** a briefing that is empty when data exists (that was F3).

### Act 2 — The business card (W2) — **YOU SCAN**
1. **Leads → New lead** (create the lead first — the scanner attaches a *contact* to an
   existing lead, so there is no scanner on the create screen), then **open the lead →
   Contacts tab → Scan card**. Point the camera at the real card.
   *Verified 2026-08-03 at `LeadDetailFragment:302`; an earlier draft of this runbook said
   "New lead → Scan card", which is a dead end.*
2. Verify sheet must show the fields it read **and a confidence**, plus an honest line if the
   organisation on the card differs from the lead name.
3. Save. **PASS:** contact created with the real name/email/phone off the card; an intro
   draft is queued for approval and the app says so *without claiming it was sent* (F2).
4. **Watch for:** silent send, invented fields, confidence shown as a bare number with no
   meaning.

### Act 3 — First meeting (W1) — **YOU PLAY `meeting1.py`**
1. Open the lead → **Record meeting** → consent sheet (verbal) → recording starts.
2. Run `python meeting1.py`, press ENTER, hold the phone near the speaker.
3. Stop. Watch the pipeline: uploaded → transcribing → extracting → review_pending.
4. **PASS:** all six steps advance; failure shows a reason and a Retry.

### Act 4 — The review gate (human stays in charge)
1. Open **Review**. Edit one item, drop one, **add one the AI missed**, confirm.
2. **PASS:** edited → open, dropped → cancelled, added → open, meeting → completed.
3. **Watch for:** items stored twice (F22), tasks with no due date (F8).

### Act 5 — The plan, and who gets the work (W9)
1. Open the project → **Plan** and **Tasks**. Each task should name a person **and a reason**.
2. **PASS:** assignment cites a real skill, not "no skill match" fallback.
3. **Watch for:** the two overlapping skill vocabularies from the merged seed —
   `logistics` vs `logistics_coordination`, `proposals` vs `proposal_preparation`,
   `teaching` vs `training_delivery`. A planner picking one while the right person holds the
   other is a **finding**.

### Act 6 — Ask Jarvis (X6)
Type, by hand — terse, the way a real salesperson does:
`what's blocking orchid` · `who is doing the curriculum` · `most important task this week` ·
`why did you pick sourav`
**PASS:** each answers or asks one clarifying question. **A lookup error is a finding** (F28
is closed; this is the regression check).

### Act 7 — The proposal, and one approval tap (W3) — **REAL EMAIL**
1. Jarvis: `create the IBC proposal for orchid`.
2. Open it: pricing locked from the table, totals computed, PDF renders.
3. `email it to the principal` → draft → **Approve & send**.
4. **PASS:** a real email arrives at `ekaghni.mukherjee+…@gmail.com`; the approval card shows
   the **full** body (F30) and refuses anything with `[blanks]`.
5. **Watch for:** a discount that no one approved (F23), a claim it was sent before approval.

### Act 8 — Book the demo (W21) — **REAL CALENDAR**
1. **Book demo** → pick date + time.
2. **PASS:** a real Google event + invite; a clash is detected and stated honestly; the app
   does not pretend the client accepted.

### Act 9 — Client replies (W4, W19, W20, W18) — via *Log a client reply*
Feed these one at a time, checking the routing after each:
| Reply | Must produce |
|---|---|
| "Can you do 1,10,000 instead of 1,32,000?" | price → **approval chain**, never a casual yes |
| "The content is too advanced for grade 6" | content change → revision task + acknowledgement |
| "Add 30 more students" | scope growth → amendment priced from the locked rate |
| "Can we move everything to 1 September?" | date shift → re-dated tasks + confirmation email |
| "What is your refund policy?" | question → answered from our own data, or escalated to Inbox |

### Act 10 — Second meeting: the plan learns (W6) — **YOU PLAY `meeting2.py`**
**PASS:** a *merge*, not a rewrite — 12→16 workshops, kits cancelled, teacher training added,
dates moved, Trustee Rao discovered as a stakeholder. Existing task history survives.

⚠️ **This act is also the decisive test for F41.** The merge path calls
`sync_stakeholder_specs`; the first-meeting path does not. So check `contacts` and
`stakeholders` for the Orchid lead **before and after**:
- **People appear** → the model does populate `stakeholders`, and F41 is purely a wiring gap
  on the create path.
- **Still nobody** → the extraction is putting people in `new_facts` instead, and fixing the
  wiring alone would not fix it.

**Do not close F41 without this result.**

### Act 11 — Contradiction (W7) — **YOU PLAY `meeting3.py`**
**PASS:** a **conflict is raised and the re-plan is HELD**. Both positions shown with who said
what. **A silent re-plan to either version is a finding.** The discount goes to approvals.

### Act 12 — The other side of the house (W16, W11, W14)
Log out. Log in as **Sourav**, then **Baski**, then **Mithun**:
- Complete a task → the client-visible ones should reach the client (W14).
- **Decline** one with a reason → it must re-route, not vanish (W16).
- A blocked task must show *what* blocks it and offer a New-date that ripples (W11).
- Mithun (ops lead) sees Delivery; **Incidents is a placeholder** — note it, do not test it.

### Act 13 — Delivery goes wrong (W22, W24, W25, W26, W30) — **YOU PLAY `meeting4.py`**
**PASS:** complaint → incident at P1; vendor slip → a real dependency; payment query →
**ladder pauses**; certificates/feedback → closure tasks; **Hinjewadi → a NEW opportunity,
never merged into this project** (W29).

### Act 14 — The awkward paths
- **Offline:** airplane mode → approve something → "Queued"; reconnect → it applies (F1).
- **Wrong role:** as Sourav, try to reach Approvals. Must be honest, not a crash.
- **Voice:** the mic in Jarvis — dictate a command.
- **Logout/login churn:** log out mid-task; the next user must NOT see the previous user's
  cached data (that was F1).
- **Notification deep-links:** tap a notification → lands on the right entity.

---

## 3. Recording every finding

For each one: **what I did → what I expected → what happened → the call path in source.**
Never infer a cause from a symptom; open the file. Then add it to `FINDINGS.md` Round 7 with
a severity and whether it is live.

Already found during setup, before the app was even opened:
**F32** (seeds never exit — fixed), **F33** (seed order silently load-bearing — fixed),
**F34** (malformed `email_domain` blocks adding staff — fixed), **F35** (IMAP poller reads
and marks-read an entire personal mailbox — open, mitigated).
