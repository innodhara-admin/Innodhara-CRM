# FINDINGS — full end-to-end simulation, 2026-07-21/22

Everything built through **Phase 5 + conversation memory** was exercised start-to-end on the
real device against the live backend, and every finding below was **observed live**, not
inferred from reading code. Code references were then confirmed in the source.

## Status (updated 2026-08-25 — audit + fix session; Round 7 remains CLOSED)

**66 findings exist** (F1–F69; F18/F20/F21 were never assigned) — recounted 2026-08-25 with a scanner that tolerates the literal `|` characters inside the F54 and F56 rows, which an earlier pass silently dropped. **58 fixed or dissolved · 1 partly fixed (F58) · 4 open (F35, F54, F56, F67) · 2 no fix planned (F5, F16) · 1 accepted (F26).** That is 66.

> ### ⚠ How to read the status table — it has misled a reader once
>
> A status cell is a **narrative**, not a verdict. Most read
> `**OPEN** <date> — how it was found … **✅ FIXED** <date> — how it was fixed`.
> **A cell beginning "OPEN" is usually not open.** On 2026-08-25 an audit parsed
> all 58 rows and found **eleven whose cell recorded no resolution at all, seven
> of them carrying a green tick** — the fix had happened, the cell had simply
> never been finished. Every one has since been checked against the source and
> completed, so:
>
> **The icon and the cell now agree, and both are safe to read. Trust the icon;
> read the cell for the reasoning.** Where a `## F<n>` section exists further
> down, that section is the authority over the row.
>
> The other half of the same lesson, learned the same day on [F59] and on a
> duplicate-upload claim that turned out to be false: **a failing check is
> evidence about the CHECK until the product has been measured.** Both had a
> plausible cause recorded against them; the first live run refuted both.

> **F60–F63 were found on 2026-08-06 while building the datacentre demo (Workflow2)** — three by the product owner using the app, one (F60) a regression I introduced myself. All four are fixed. **F60 is the one to learn from: an insertion anchored on a `@POST` line split `@Multipart` from its method, compiled perfectly, and crashed only at the first call.**

> **Two remain open, and one is partly done** (verified against the source 2026-08-25):
> - **F35** — the IMAP poller. Mitigated (`INBOUND_EMAIL_MODE=off`) and **needs a policy
>   decision, not a patch**: scope by label? `BODY.PEEK`? refuse a mailbox above N messages?
>   Unchanged: `mail_poller` still does `select("INBOX")`, `search UNSEEN` over the whole
>   mailbox, and a non-PEEK `fetch(RFC822)` that marks real mail read.
> - **F67** — a proposal created through Jarvis has `project_id IS NULL`. **Worse than this
>   entry knew:** `ApiService.java` declares no `POST /proposals`, so **Jarvis is the app's
>   only proposal path**. `document_engine.create_invoice` derives its amount from
>   `accepted_total(project_id=…)`, so a ₹2,00,000 accepted proposal yields a **₹0 invoice**
>   (`computation='50% of (0) = 0'`) — measured 2026-08-25. Not yet reachable from a client:
>   no invoice route is called by the app or the console.
> - **F54** — a complaint made in a meeting never becomes an incident. Re-verified in
>   code 2026-08-25: `Incident(` still has **one** construction site and
>   `COMPLAINT_RECEIVED` **one** emitter, both inside `_route_complaint`, whose only
>   caller is the inbound router. Downgraded to medium and reframed as a **product
>   decision** — which was then mistaken for a resolution and marked ✅. It needs
>   your ruling, like F35.
>
> - **F56** — the commitment register is still write-once. The 2026-08-05 prompt fix
>   is genuinely in the source, and **measured against the live model on 2026-08-25 it
>   does not work**: `verify_live_commitments.py` scores **3/6** and the register goes
>   **4 → 4** across a second meeting. Its anti-duplication half (the [F42]
>   interaction) does hold. The next attempt has to find out *why the model omits
>   them*, not reword the ask again.
>
> **One is partly done:**
> - **F58** — 13 entity types route; five still dead-end because the features behind
>   them (`invoice`, `incident`, `playbook_suggestion`, `client_commitment`, `user`)
>   have no screen anywhere.
>
> - **F59 is CLOSED and was never a product defect** — see its row. The model *does* emit
>   `client="all"`; the harness was asserting on `actions[].result`, which is a preview that
>   turns into a truncated **string** above 800 characters of JSON.
>
> **⚠ F42 was INVESTIGATED AND LARGELY REFUTED** (2026-08-06, at the owner's request): its
> 'structural double-count' is **correct behaviour**, and the claimed spec self-contradiction
> **dissolves** — no decision is owed by anyone. Only its text half was a real defect, and
> that is fixed and live-verified. Read its entry before citing it.

> **F28/F29/F30/F31 are all FIXED and device-verified** (2026-08-03). An older version of this
> heading said "F31 genericity OPEN" — that was stale; the status table below is the authority
> and says FIXED.
>
> **Planning more fixing? `# Round 7 — fix order` near the end of this file has the plan — but
> read it as HISTORY: most of it has been executed** and every row there is tagged ✅ DONE /
> 🟠 PART / 🔴 TODO. Its traps and wrong-fix warnings are still the reason the executed half
> went safely, so they remain worth reading.

> **2026-08-03:** **F28 is CLOSED.** The backend was unfrozen by the user for that one
> named job — *"Phase 7 §7.0, F28, full scope"* — all five fixes are in, and the acceptance
> test passed on the real device: a command typed by hand into the Jarvis tab, *"Draft an
> email to EKAGHNI MUKHERJEE at Orchid International School about the workshop dates"*,
> produced a real draft; an unresolvable person produced a **question card** with one-tap
> candidates instead of a red failure; and Phase 6's labelled-line prompt was reverted to
> natural phrasing and still works. The backend is **RE-FROZEN**.
>
> **F29 and F30 are also CLOSED** (same day, second unfreeze — *"F30 + F29"*, granted after
> the F28 report). **F30**: a draft carrying `[Name]` blanks is now refused at **both**
> approve routes by a deterministic detector, the approver is warned before the tap, and the
> assistant's inline card no longer truncates the body at 300 characters — which is what hid
> the blanks in the first place. It stays a fence and not a veto: an approver who has read
> them can still send. **F29**: the digest now uses the same local date as its six
> neighbours. Both device-verified; backend **RE-FROZEN**.
>
> **F31 is CLOSED (2026-08-03, third unfreeze — *"F31 genericity, full scope incl.
> corrections A/B and item C"*).** All three live defects and the Phase-7.1 landmine are
> fixed, plus **two corrections to F31's own write-up** and **three further sites the new
> regression guard found by itself**. Proven against the real model by
> `scripts/verify_live_genericity.py` — a colocation client priced **per rack in USD** —
> **15/15**, and device-verified on the Vivo (app `0.7.3-f31`). Backend **RE-FROZEN**.
> Full write-up: **"How F31 was fixed"** below.
>
> Deliberate non-fixes unchanged: **F5** = monitor, **F16** = Phase-8 scope, **F26** =
> accepted.
>
> ## ✅ 2026-08-05 — ROUND 7 COMPLETE: ALL 14 ACTS RUN
>
> A full wipe-and-rebuild end-to-end simulation across the whole app, on the real device.
> **The driver is `Workflow_simulation/Workflow1/SIMULATION_RUNBOOK.md`** — read its
> *"WHERE WE ARE RIGHT NOW"* block first; it holds the live position, the environment state
> and the next action. Handoff **§8-pre9** is the state-of-the-world section (§8-pre8 is history).
>
> **Twenty-seven findings (F32–F58) were raised across Acts 1–14. THE SIMULATION IS COMPLETE,
> and two fix tranches have run since — see the status table above for what is actually done.**
>
> **Act 13 (the delivery meeting, `meeting4`) added three: F54, F55, F56** — and produced the
> round's **best extraction** (0.876/408 words, all six promises captured, every task assigned
> *and dated* at confirm, three re-graded P2→P1). **The protected state survived a fourth
> meeting**: plan v6 was raised `pending_review` behind an approval while v4 stayed active, v5
> stayed `draft` and the 4 conflicts stayed open — **F49's failure mode did not recur.**
> Two of the three new findings are the **same shape as F41**: machinery that exists, works,
> and is wired to one entry point only (**F54** complaints; **F56** commitments).
> **W25 could not be tested** — there is no invoice in the DB, so no ladder exists to pause;
> recorded as a precondition, **not** a bug.
>
> **Act 12 (the delivery side — Sourav, Baski, Mithun) added four: F50, F51, F52, F53**, and
> **corrected F43** (conflicts *are* surfaced in a third place — the ops lead's Delivery card,
> via `recompute_health`; F43's "exactly two places" is retracted, the finding itself stands).
> **W16 and W11 both PASSED end to end** — a decline re-routes with its history intact and a
> better-justified reason, and the new-date ripple gate refuses, routes to the lead and says
> what broke. **W14 FAILED**: a completed client-visible task never reached the client and
> **nothing recorded that it hadn't** (**F50**, the act's headline).
>
> Two candidate findings were **withdrawn after checking** rather than filed: the missing
> assignment notification (correct for `lead_confirm`, confirmed in code *and* the Data Model)
> and "new-date does nothing" (a Snackbar my 7-second screenshot missed — see the method note
> under *Verified working*).
>
> Act 11 added **no new finding** and was the round's best result (W7 conflict handling); it did
> strengthen **F43** with a third observation. Acts 9–10 added no new
> finding: Act 9 **widened F44** (not redraft-only — 3 of 3 drafts carry a `Subject:` line in
> the body and replies have no subject at all), and Act 10 **proved F41's cause** (a pure
> wiring gap — meeting 2 created `Mr. Rao, source=meeting` automatically where meeting 1
> created nobody).
>
> **Seed scripts, fixed under a named unfreeze now closed (backend RE-FROZEN):**
> **F32/F33/F34** ✅ — all three in the **seed scripts every session is told to run**. F32
> **corrects a cause §6g/§6i had wrong since 2026-07-22**.
> **F37** ✅ — **the F31 app guard itself was broken** (line-based, blind to wrapped setter
> calls); F31's "nine hardcoded literals" was really **eleven**.
>
> **Open — consent and data integrity (treat as the round's most serious):**
> **F39** 🔴 — **recorder pause is one-way: the mic keeps recording while the UI says
> "Paused"**, and the saved duration freezes with it.
> **F40** 🔴 — the consent record **attached to a meeting** is hardcoded to `in_app /
> "Confirmed at upload"`, discarding the method the user chose; the API never verifies the
> consent claim it is handed.
> **F35** 🔴 — the IMAP poller read the owner's *personal* 45,000-message mailbox and marked
> real mail read. Mitigated (`INBOUND_EMAIL_MODE=off`); **do not re-enable**.
>
> **Open — a correction the system cannot accept:**
> **F38** 🔴 — a corrected contact email reaches the queued message by **no path at all**:
> not the verify sheet, and **not rejecting it** (the redraft re-uses the old address, and its
> approval card no longer even shows the address).
> **F44** 🔴 — a rejection note can only change the **body**, so "wrong recipient" is neither
> applied nor refused; the model wrote a `Subject:` header **into the body**.
>
> **Open — the first meeting drops its people:**
> **F41** 🔴 — people named **with their roles** never become contacts or stakeholders →
> **0 stakeholders, 0 contacts, 11 ownerless commitments**, nothing can be emailed, and
> `_sweep_commitments` silently skips every client-side promise. **A wiring bug:** the
> function that does this correctly exists and is called for meeting 2+ and inbound email.
> **F42** 🔴 — commitments stored as raw transcript fragments; a promise split across two
> tasks is **structurally** double-counted.
>
> **Open — the app says things that aren't so:**
> **F43** 🔴 — project **"What's blocking?"** never looks at pending approvals, so a plan
> frozen awaiting sign-off reports *"Nothing is blocking"*. Deterministic.
> **F45** 🔴 — terse "who is doing X" answers with the **client's** coordinator, not the
> assignee. **F46** 🔴 — "why did you pick X" cannot be answered from data by **any** agent:
> `why_trace` is not a tool and `assignments.reason` is in no agent's view.
> **F28 does not regress** (no lookup errors) — it is the "never silently guess" half of the
> rule that fails.
> **F36** 🔴 — the login screen's `server:` label goes stale after Apply.
>
> **F47** 🔴 — a **`[missing:…]` placeholder went out in a real client PDF**, past a guard the
> app had explicitly run in strict mode: the purpose-built detector is dead code, the general
> fence doesn't match the marker, and neither ever inspects the attachment.
>
> **F48** 🔴 — the demo refusal points at a "ask Jarvis to request one" capability that was
> never built. Low severity, but the app sends the user in a circle.
>
> **F49** 🔴 — a superseded plan keeps a **live approval**, and `activate_plan` has no
> newest-version guard, so approving it would roll the project **backwards** over the merge.
>
> **Open — Act 12 (the delivery side):**
> **F50** 🔴 — a **client-visible task was completed and the client update was dropped with no
> trace at all**: no draft, no approval, no decision row, no log line. Two of the five refusal
> paths in `draft_client_message` record nothing, and the caller discards the return value.
> **F51** 🔴 — the task-lifecycle router enforces ownership on **1 route of 23**; a non-assignee
> blocked another user's task through the UI (device-proven), and `/assignments/confirm-batch`
> is open to any member although `lead_confirm` means "the phase lead confirms".
> **F52 / F53** 🔴 — the product has **no reliable surface for what is late**: the briefing calls
> a task due *today* **Overdue** and renders an always-empty *"Due today:"* header, while
> **My tasks** files work that is five days late under **"Today"**.
>
> **⚠️ 2026-08-05 — every Act 12/13 finding was re-checked against the SPEC, not the runbook.**
> The runbook's pass conditions are a test plan, not a contract. Re-checking
> `YuviPep_30_Workflows.md` and `YuviPep_Data_Model.md` moved two verdicts:
> **F54 was DOWNGRADED to medium** — W22 is written entirely as an *inbound* story, so a
> meeting complaint raising an incident is a reasonable inference, **not** a documented
> contract. **F55 and F56 were STRENGTHENED** — W29 spells out a **per-project** stakeholder
> model (*"Kavita is on the bootcamp only"*) and Data Model **§4.5** says commitments are
> *"extracted … **from meetings**"*, plural. **F50** is backed by W14 (*"if
> `visible_to_client` = true, the client-update flow fires"*). The lesson, recorded because it
> will recur: **a finding's observation and its expectation are two separate claims, and only
> the source docs can settle the second.**
>
> **Open — Act 13 (the delivery meeting):**
> **F54** 🔴 — a **complaint said to your face never becomes an incident**; the whole of W22 is
> reachable from email only. The identical words by email page both leads in seconds.
> **F55** 🔴 — a second campus named in a meeting creates **no opportunity**, and its decision
> maker is attached to the **current** project — latent until someone adds her email, which the
> product's own task instructs them to do.
> **F56** 🔴 — the **commitment register is write-once**: 11 rows from meeting 1, **zero** from
> the three merges after it, so no promise made after the first meeting is ever chased.
>
> **Open — Act 14 (the awkward paths):** **F57** 🔴 an approvals question is answered from the
> **task list** — no agent can see approvals (proven on two roles) · **F58** 🔴 **84 of 125**
> notifications dead-end on *"a later phase"* for screens that are already built.
> **Act 14 otherwise PASSED**: the offline decide queue, logout/login churn (F1) and voice all
> work well — see *Verified working*. **[F49] became device-proven during it, by operator
> error, and its blast radius turned out wider than written.**
>
> ---
>
> ## ⛔ EVERYTHING ABOVE THIS LINE IS THE ACT-BY-ACT NARRATIVE **AS FOUND**
>
> **The 🔴 marks in that narrative are the state on the day each finding was raised, not
> today's state.** Do not read them as open work. **The status table is the only authority.**
>
> ### Current state — 2026-08-06, end of session
>
> **All three fixing tranches are DONE, plus the four demo-build findings.**
>
> | | |
> |---|---|
> | **Tranche 1** (2026-08-05) | F41, F47, F49, F50, F51 |
> | **Tranche 2** (2026-08-06) | F39, F40, F43, F44, F45, F46, F57 |
> | **Tranche 3** (2026-08-06) | F36, F38, F42, F48, F52, F53, F54, F55, F56, F58 |
> | **Demo-build** (2026-08-06) | F60, F61, F62, F63 |
>
> **Open — 2, and only 2:**
> - **F35** — inbound IMAP. **Not a code defect; it needs your policy decision.**
>   `INBOUND_EMAIL_MODE=off` and **must stay off** until you decide.
> - **F59** — `verify_live_assistant_context.py` is 4/6, was 6/6. **Pre-existing**, proven by
>   reverting this session's tools and reproducing the identical 4/6. **Undiagnosed.**
>
> **Closed without a code fix — 3:** F5 (monitor), F16 (Phase-8 scope), F26 (accepted).
>
> **There are no 🟠 part-done findings left.** F38, F54, F55 and F56 were part-done at the end
> of tranche 2 and were **completed in tranche 3**.
>
> ### ⚠ What was NOT tested — stated plainly
>
> - **The 3 Workflow2 meeting WAVs have never been played into the phone.** The demo script is
>   written and the recordings are built, but the end-to-end run has not happened.
> - **F63's model half is unproven.** The op is applied correctly at activation (6 tests), but
>   whether the model *chooses* `reschedule_demo` over `redate` has only been prompted for, not
>   observed live. **F63 is also merge-only** — a FIRST meeting still cannot move a demo.
> - ~~**F59 is undiagnosed**, not just unfixed.~~ **Diagnosed and closed 2026-08-25 —
>   it was never a product defect.** The model does emit `client="all"`; the harness
>   was asserting on a debug preview that truncates past 800 chars. See its row.
>
> ### Environment, as this session left it
>
> - `EMAIL_MODE=smtp` and `CALENDAR_MODE=google` are **LIVE — real mail actually sends.**
> - `INBOUND_EMAIL_MODE=off` (F35).
> - Backend on **`PORT=9010`** with `adb reverse tcp:8000 tcp:9010`. **The tunnel clears on
>   every device reconnect** — check `adb reverse --list` before believing "network trouble".
> - App **`0.7.4-round7fixes`** installed on the Vivo.
> - Suites: `pytest` **194/194** · dryrun 43/43 · gap 21/21 · stakeholders 21/21 · genericity
>   guards green.
> - **The Round 7 evidence database was deliberately WIPED on 2026-08-06** for the datacentre
>   demo, at your instruction, keeping only employees and their skills. A byte-copy is at
>   `data/_backup_round7_evidence_20260806-101259/salesplatform.db`. **The old "do not approve
>   these rows" instructions are therefore MOOT — those rows no longer exist.**
>
> **Environment caveat that still applies:** the **Gemini embedding API is out of credits**
> (HTTP 429, "prepayment credits are depleted"). The backend degrades gracefully —
> `WARNING app.ai.memory: Memory embedding skipped` — but **semantic memory is off**. Do not
> attribute weak recall or matching to a code defect without checking this first. This is the
> likely cause of **F59** and it is exactly why **F62** was raised.


The backend was **unfrozen by the user for a named job — "fix the FINDINGS items"** on 2026-07-22.
As of **2026-07-23 that job is COMPLETE: every fixable finding is fixed** (through F25) and, where
the UI could reach it, device-verified on the Vivo; every completed item carries a "How it was
fixed" block in its own section below. **The backend has been RE-FROZEN** — the default rule
(handoff §7 rule 5) applies again: do not change backend code without a new explicit unfreeze
from the user. The only remaining findings are deliberately *not* code fixes: **F5** (monitor),
**F16** (Phase-8 scope), **F26** (accepted), **F27** (planned as Phase 6). **The status table
below is the single source of truth for what is done** — read it first, and trust it over any
prose elsewhere in this file.

**Symbols:** ✅ fixed & verified · 🔴 open, evidence-backed defect · 🟠 open, but the
*expected* behaviour is a product decision rather than a documented contract (read the entry
before treating it as a bug) · ⚠️ accepted, no fix planned · ➖ deliberately not a code fix.

| | Finding | Status |
|---|---|---|
| ✅ | **F4 / F4b** — "school" hardcoded in the meeting prompt | **FIXED & verified** 2026-07-22 |
| ✅ | **F8** — meeting tasks never get a due date | **FIXED & verified** 2026-07-22 |
| ✅ | **F9** — recording does not start the Planner | **FIXED & verified** 2026-07-22 |
| ✅ | **F22** — review-gate items + Planner tasks stored twice | **FIXED & verified** 2026-07-22 (suites + live script + **real recording on the Vivo**) |
| ✅ | **F23** — proposal rewrite applies a forbidden discount | **FIXED & verified** 2026-07-23 (deterministic prose-price fence; live guard 3/3; not device-tapped — no proposal seeded) |
| ✅ | **F24** — the same to-do re-opens on every recording of a lead | **FIXED & verified** 2026-07-23 (warn at the review gate; app `0.6.5-findings`; on the Vivo) |
| ✅ | **F1** — 401 leaves the previous user's data on the device | **FIXED & verified** 2026-07-22 (app `0.6.3-findings`, reproduced via reseed on the Vivo) |
| ✅ | **F25** — assignment never matches a skill (`user_skills` is empty) | **FIXED & verified** 2026-07-23 (seed taxonomy + constrain the planner + coerce; live 3/3; on the Vivo) |
| ✅ | **F2** — "waiting in Approvals" false for intros + demo invites | **FIXED & verified** 2026-07-22 (demo-invite half on the Vivo; intro half unit-tested only) |
| ✅ | **F10** — the "Why?" sheet could never explain a lead suggestion | **FIXED & verified** 2026-07-22 (5 producers, one writer; on the Vivo) |
| ✅ | **F3** — daily briefing ignored follow-ups/demos, rendered empty | **FIXED & verified** 2026-07-22 (on the Vivo) |
| ✅ | **F11 / F6** — user-visible + LLM-facing "school" strings | **FIXED & verified** 2026-07-22 (~40 sites; §6c rewritten) |
| ⚠️ | **F26** — the new FAST model escalates inbound questions the old one answered | **ACCEPTED** 2026-07-22 — escalating is fine (user) |
| ✅ | **F27** — an AI-escalated question has nowhere to be answered | **CLOSED** 2026-07-29 — Phase 6 (Inbox) built & device-verified; an escalated question was answered, approved and sent from the app |
| ✅ | **F28** — the assistant can't resolve a person from a natural phrase, and fails instead of asking | **FIXED & verified** 2026-08-03 (all five fixes; app `0.7.1-f28`; on the Vivo — the reverted natural prompt is the acceptance test) |
| ✅ | **F30** — drafts reach the approval gate with `[Name]` placeholders, past the 300-char preview cut | **FIXED & verified** 2026-08-03 (detector + fence on both approve routes + full preview; app `0.7.2-f30`; on the Vivo) |
| ✅ | **F29** — the daily briefing drops follow-ups due today, between 00:00 and 05:30 IST | **FIXED & verified** 2026-08-03 (local date, matching its six neighbours; device-checked at 03:06 IST, inside the failure window) |
| ✅ | **F31** — domain-genericity incomplete, backend **and app**: value estimate + amendment unit are education-only, a dead LLM prompt hardcodes the industry, and the app hardcodes `₹` + a "principal" hint | **FIXED & verified** 2026-08-03 (10 fixes + 2 corrections + 3 items the guard itself found; app `0.7.3-f31`; `verify_live_genericity.py` **15/15 against the real model**; on the Vivo) |
| ✅ | **F17** — the context chip is a hint, never a filter | **FIXED & verified** 2026-07-23 (new live script 6/6 + on the Vivo) |
| ✅ | **F19** — the query agent cannot see `priority` | **FIXED & verified** 2026-07-23 (on the Vivo — "most important" now beats "soonest due") |
| ✅ | **F7, F13, F14, F15, F12** — the app copy pass | **FIXED & verified** 2026-07-23 (app `0.6.4-findings` + F15 digest greeting; F12/F14/F7/F13/greeting on the Vivo) |
| ✅ | **F32** — both seed scripts commit, print success, then **never exit**, holding the DB (undisposed `aiosqlite` thread); blocks the next writer. **Corrects §6g/§6i: it happens on SUCCESS, not on a raise** | **FIXED & verified** 2026-08-03 — `try/finally: await engine.dispose()` in both; probe went HUNG→**EXITED (1.9s / 2.8s)** |
| ✅ | **F33** — `seed_demo`'s idempotency guard is **org-level**, so seed ORDER is silently load-bearing: workflows-first leaves no Siva, no IBC, no F25 skills, and reports "already seeded — nothing to do" | **FIXED & verified** 2026-08-03 — the skip is now loud and specific, back-fills the F25 skills, names the correct order and **exits 2**; structure left alone (no per-entity guards exist to merge onto) |
| ✅ | **F34** — `seed_workflows` stores `email_domain='@yuvipep.com'`; `admin.py:84` builds `"@" + domain` → `"@@yuvipep.com"`, so **no staff member can ever be added** to an org it created | **FIXED & verified** 2026-08-03 — stores `'yuvipep.com'`; both seed paths now yield `"@yuvipep.com"` |
| 🔴 | **F35** — the IMAP poller hardcodes `select("INBOX")` with no label/folder/date scoping and fetches **non-PEEK**, so pointing it at the personal Gmail this project's own `.env` designates marked real personal mail as read at up to **750/hour** | **OPEN** 2026-08-03 (Round 7) — observed live on a 45,063-message mailbox; ~25–75 messages affected before it was stopped; `INBOUND_EMAIL_MODE` reverted to `off`; simulation proceeds via the app's *Log a client reply* screen, so **the IMAP transport is knowingly untested** |
| ✅ | **F36** — the login screen's `server:` label stays stale after the Environment sheet applies a new base URL (`refreshServerChip` only runs in `onResume`, which a dialog dismiss never triggers) | **OPEN** 2026-08-03 (Round 7, Act 1) — debug-only, but it misleads on the exact screen used when the backend is unreachable **✅ FIXED — verified in code 2026-08-25.** `LoginFragment:62-64` registers `setFragmentResultListener(EnvironmentSheet.RESULT_APPLIED, …)` → `refreshServerChip()`, so applying a new base URL updates the chip without waiting for an `onResume` a dialog dismiss never fires. Shipped in `0.7.4-round7fixes` (`app/build.gradle:22-26` names it) |
| ✅ | **F57** — **"how many approvals are waiting on me" is answered from the task list.** No agent exposes approvals as a tool (the REST endpoint exists and the Approvals tab uses it; nothing wraps it), so the model reaches for `list_action_items` and relabels the output | **OPEN** 2026-08-05 (Round 7, Act 14) — **device-proven on two roles.** Sourav (no approvals): *"no pending approvals for Orchid … **(0 open items)**"* while Orchid had **6** — and "open items" is `list_action_items` vocabulary, his task count being exactly 0. **Test 2 run to falsify role-scoping:** Siva, who *does* hold approvals, got back her **task list** under *"Due later"*. [F46]'s family, third instance **✅ FIXED & verified 2026-08-05.** A `list_approvals` tool now wraps the endpoint that already existed — the data layer was never the problem, nothing wrapped it. **Returns `stage`**, as the finding insists: this org holds a `stage=recommend` approval that deliberately does not appear in the decide queue, so a count without it would mislead a second, quieter way. The tool description says outright that it is **not** the task list. Org- and user-scoping is pinned by a cross-org leak test, since this reads the product's central control table. 5 tests shared with [F46]. |
| ◐ | **F58** — **84 of 125 notifications dead-end** on *"This opens fully in a later phase"* (`MainActivity.openEntity:297-332` handles 9 entity types, Toasts the rest) — but `conflict`, `action_plan` and `followup` all have **screens that already exist** (`TAB_CONFLICTS`/`renderConflicts`, `TAB_PLAN`/`renderPlan`, `FollowUpQueueFragment`) | **OPEN** 2026-08-05 (Round 7, Act 14) — device-observed at ~600 ms. **[F48] inverted**: the app *denies* a capability it has. Worst for **[F43]** — the bell is one of only two conflict-discovery routes and it goes nowhere. `digest` (65) is the fair exception: no such screen exists **◐ PARTLY FIXED — measured 2026-08-25.** `MainActivity.openEntity` now routes **13** entity types (approval, meeting, lead, proposal, project, inbound_message, outbound_message, message, action_item, followup, conflict, action_plan) plus an honest digest case. **Five emitted types still dead-end on `notification_no_screen_yet`**, and they are the ones with no screen at all: `client_commitment` (sync_engine:1066), `incident` (inbound_engine:583), `invoice` (sync_engine:1361), `playbook_suggestion` (knowledge_engine:146), `user` (sync_engine:1524). Those four features have **no client anywhere** — not the app, not the setup console — so the toast is currently the truth |
| 🔴 | **F54** (severity → **medium**, downgraded 2026-08-05 on re-checking the spec: W22 is written entirely as an *inbound* story, so the meeting path raising an incident is a **reasonable inference, not a documented contract** — a product decision to make, not a contract violation) — **a complaint made in a meeting never becomes an incident.** `_route_complaint` (`inbound_engine.py:510`) is the whole of W22 — incident + severity + `COMPLAINT_RECEIVED` (health) + P1 escalation to **both** leads + holding reply — and it has **one caller**, the inbound intent router (`:459`). `Incident(` has **one** construction site and `COMPLAINT_RECEIVED` **one** emitter, both inside it. `grep -niE "complaint\|incident"` over `planning.py` + `planner_engine.py` returns **nothing**: the meeting contract has no field for it | **OPEN** 2026-08-05 (Round 7, Act 13) — device-observed on a real recording: *"your trainer arrived 40 minutes late"* → a P1 task and **nothing else** (incidents 0→0, no event, no escalation, no client acknowledgement). **[F41]'s shape, but NOT its evidentiary strength** — F41 cites a spec sentence, F54 has none (see the correction inside the entry). The same words by **email** would page both leads in seconds — that contrast is **code-verified, not executed** **⚠ STILL OPEN — re-verified in code 2026-08-25.** `Incident(` still has exactly **one** construction site (`inbound_engine.py:564`) and `COMPLAINT_RECEIVED` exactly **one** emitter (`:575`), both inside `_route_complaint`, whose only caller is the inbound intent router. Nothing on the meeting path raises an incident. **The ✅ on this row was wrong** — the entry was downgraded to medium and reframed as *a product decision*, and that was mistaken for a resolution. It needs your ruling, like [F35]: should a complaint heard in a meeting raise an incident? |
| ✅ | **F55** — a second campus's decision maker is **attached to the current project**, violating the per-project stakeholder model **Workflow 29** spells out (*"stakeholders rows exist per-project … Kavita is on the bootcamp only"*). The *"no opportunity was created"* half is **not** mandated by the spec — W29 describes a separate *meeting about* the new business creating the second project, not a passing mention. `sync_stakeholder_specs` binds every person a meeting names to *that meeting's* project, and `_STAKEHOLDER_ITEM_SCHEMA` has **no field** to say "different engagement" — a contract gap, not a model error. No code path anywhere creates a lead from a meeting (only `api/leads.py:100` and `api/projects.py:573`, both human-driven) | **OPEN** 2026-08-05 (Round 7, Act 13) — Mrs. Kulkarni (Hinjuwadai head) is now a **second `decision_maker`** on the **Orchid** project. **The good half held**: no Hinjuwadai *work* entered plan v6. Latent only because her `email IS NULL`; `ops.py:136` CCs an **arbitrary** `.first()` decision maker on invoices, so it arms the moment someone adds her address — which the product's own task tells them to do. **Code-verified, not executed** (`invoices = 0`) **🟠 HALF FIXED 2026-08-05 — the `.first()` half only.** Both arbitrary `decision_maker` lookups (`ops.py`, `sync_engine.py`) are now ordered `created_at, id`: **oldest first**, so a person attached later can never displace the decision maker a project has known longest — which is precisely the Mrs. Kulkarni shape. This was worth doing on its own merits and is test-pinned. **The contract half is NOT fixed and F55 stays open for it:** `_STAKEHOLDER_ITEM_SCHEMA` still has no way to say "different engagement". Deferred deliberately — a schema/contract change entangled with [F42]'s unresolved spec contradiction. |
| 🔴 | **F56** — **the commitment register is write-once**, violating Data Model **§4.5** (*"Extracted by the Planner and Inbound Engines **from meetings** and messages"* — plural, unqualified). All **11** commitments were created at `2026-08-03 20:57:05` (meeting 1, the create path); **meetings 2, 3 and 4 — three merges — added zero.** The persistence path exists and the merge calls it (`planner_engine.py:1693` → `:334-336`), and the merge's `new_tasks` reuses `_TASK_ITEM_SCHEMA` which includes `commitment` — but the **merge prompt only ever asks to *renegotiate*** one, never to attach one. The initial-plan prompt's *"attach when the task fulfils a promise someone actually stated"* (`planning.py:455`) has no merge-side counterpart | **OPEN** 2026-08-05 (Round 7, Act 13) — six promises read back aloud and confirmed by the client became six tasks with `client_commitment_id = NULL`. `_sweep_commitments` can only chase the register, so no promise made after meeting 1 is **ever chased or marked BROKEN** — including *"the incident write-up by Thursday"*, made to a client who had just complained. **⚠ Interacts with [F42]:** naively creating commitments on every merge worsens its duplication **🟠 FIX APPLIED 2026-08-05, NOT YET BEHAVIOURALLY VERIFIED — stays OPEN until it is.** The merge prompt now carries a PROMISES paragraph asking a `new_tasks` item to attach its `commitment` when it fulfils a promise stated in THIS new information, mirroring `planning.py:455`. **The [F42] interaction is handled ID-based, not by text equality** (which F42 says is exactly wrong): the merge snapshot already lists `Open commitments (id | text | due)`, and the prompt forbids re-attaching anything on that list, directing a moved promise to `renegotiate_commitment` instead. Chain re-read end to end and confirmed: prompt → `_TASK_ITEM_SCHEMA` → `validate_task_specs` (preserves `commitment`) → `create_plan_version` persists — so F56's "no code change needed" holds. **4 tests: the plumbing, plus two guards on the prompt text and one that the snapshot still shows the model the ids the rule depends on** (F31's lesson: a sweep is a claim made once, a guard is a claim re-made every run). ⚠ **What is NOT done:** the controlled experiment F56 itself names — run a real merge and watch commitments appear. `scripts/verify_live_commitments.py` was written for exactly that (3 checks incl. the no-duplicate case) but **hung in the first meeting's plan generation and was killed after 26 minutes with no DB writes**; a direct LLM probe answered in 4.6 s, so the model was fine and the fault is in that harness — most likely `review/confirm` enqueuing `plan_meeting` while the script also calls it directly, two writers on one SQLite file. **Fix the harness and run it before closing F56.** **🔴 STILL OPEN — the fix was applied, and it DOES NOT WORK. Measured 2026-08-25 against the live model, `scripts/verify_live_commitments.py`: 3/6.** The prompt change is genuinely present (`app/ai/planning.py:713`, the `PROMISES — record NEW ones, do not only re-date old ones` paragraph), but a second meeting still adds **zero** commitments — the register went **4 → 4**. Failing checks: *the second meeting added at least one commitment* (4 → 4), *the promise WE made was captured* (nothing added), *a promise the CLIENT made is recorded as theirs* (all four surviving rows are `ours`). **The three passing checks are the [F42] interaction, and it holds** — restating a promise adds no duplicate, and the restated promise still has exactly one row. So the anti-duplication half works and the creation half does not. **This row carried a ✅ for twenty days while its own text said OPEN**; asking the prompt for commitments was not enough, and the next attempt needs to find out why the model omits them — not assume a wording change fixed it |
| ✅ | **F50** — a **client-visible task was completed and the client update was dropped with no trace**: the only stakeholder with `receives_progress_updates` is the addressless Mr. Rao, so `draft_client_message` hit its `if not to_address: return None, None, []` (`communication_engine.py:268-269`) — one of **two** early returns that record nothing, while `do_not_contact`, `needs_review` and the courtesy cap all `record_decision`. The caller (`sync_engine.py:238`) discards the return value | **OPEN** 2026-08-05 (Round 7, Act 12) — **device-observed**: task `done`, note stored, and **0 new outbound, 0 approvals, 0 `ai_decisions`, nothing in the log**. Distinct from [F41], which explains only *why* the recipient is unreachable; F50 is the silent drop. `sender is None` branch **code-verified, not executed** **✅ FIXED & verified 2026-08-05** — both bare `return None, None, []` branches now `record_decision(needs_human=True)`, naming the person, the channel and the dropped purpose, matching the three siblings that always did. The function's own docstring was **false** ("message is None only when drafting is refused (do_not_contact)" — there are four such paths) and is corrected. **The `sender is None` branch is no longer code-verified-only: it is now executed by test.** ⚠ **The write-up under-counted again** — it names `sync_engine:238` as "the caller"; **11 of 16 call sites discard the return**, which is exactly why the fix belongs inside the function rather than at one caller. 4 tests, falsified. |
| ✅ | **F51** — the task-lifecycle router enforces ownership on **1 action of 23**: `/decline` checks the assignee (`workflow.py:142`), nothing else does, and `workflow.py` is the **only** API module that never calls `require_permission` (every other one does — admin 16, leads 11, proposals 8…). `can_reassign_task` (the doc §13 rule) has 2 callers, both on the *reassign* path. `/assignments/confirm-batch` is ungated although `lead_confirm` means "the phase lead confirms" | **OPEN** 2026-08-05 (Round 7, Act 12) — **device-proven**: as Sourav (non-assignee, `operations_agent`) `POST /tasks/{id}/block` → 200 OK on **Mithun's** task, `progress_events.actor=Sourav`. **⚠ `require_permission("manage_tasks")` would NOT fix it** — that grants all 5 org roles; the missing control is ownership. Other routes **code-verified, not executed** **✅ FIXED & verified 2026-08-05** — ownership (`can_reassign_task`, the project's own §13 rule) on `/block`, `/unblock`, `/new-date`, `/split`, `/vendor-promise`, `/vendor-slip`; a new lead-only `confirm_assignments` permission on `/assignments/confirm-batch`; and the app's `renderActions` now mirrors the server so it cannot offer a chip the server refuses. `/complete` and `/progress` left OPEN **by decision with the project owner** (covering for a colleague is teamwork) — recorded as a test so it cannot be mistaken for an oversight. **The spec-check split this finding three ways** — see the F50–F58 pass. 11 tests; every route F51 could only code-verify is now actually executed. |
| ✅ | **F52** — **"Due today:" always renders as an empty header.** `assistant_engine.py:90-91` builds `today` with a **date** compare and `overdue` with a **datetime** compare, so with midnight-stored due dates `overdue ⊇ today`; `:167-170` guards the header on `today` but fills it `if t not in overdue`. A task due **today** is also announced as **Overdue** from 00:00 | **OPEN** 2026-08-05 (Round 7, Act 12) — device-observed on **two users** (Sourav, Mithun). **Shows [F29]'s fix was partial**: `today_local` reached follow-ups/demos (`:139,153,154,189`) but the task lists still use UTC `now`. The UTC-vs-local half is **code-verified, not executed** (both dates were 05 Aug at test time) **✅ FIXED — verified in code 2026-08-25**, and since **SUPERSEDED by the one-clock work**: `today`/`overdue` no longer compare a UTC `.date()` against a server-local `date.today()` at all. Both now run through `clock.local_date(...)` / `clock.today(tz)` in the **organisation's** timezone — see [F65] |
| ✅ | **F53** — **"My tasks" has no Overdue group**; `MyTasksFragment.java:116` buckets `due <= today` as **"Today"**, and only 4 buckets exist (Blocked/Today/This week/Later). No `my_tasks_overdue` string, and `MyTasksAdapter` gives the date no overdue styling — though `followups_overdue` exists at `strings.xml:562` | **OPEN** 2026-08-05 (Round 7, Act 12) — device-observed: Baski's three tasks due **31 Jul, 1 Aug, 3 Aug** all filed under **"Today"**. The app-side mirror of [F52], failing the opposite way: **Home calls today late, My tasks calls late today** **✅ FIXED — verified in code 2026-08-25.** My Tasks has an Overdue bucket, ordered after Blocked and before Today. The bucketing has since moved out of the fragment into `core/util/WorkDay.java` so it is testable — `WorkDayTest`, 13 cases |
| ✅ | **F49** — a plan superseded via the **inbound** path keeps its approval **pending** (`inbound_engine.py:740-758` sets the status but never expires approvals or tasks, unlike the planner sweep at `:180-215`), and `activate_plan` has **no newest-version guard** | **OPEN** 2026-08-04 (Round 7, post-Act 10; **found by the project owner**) — v2 approval still live while v4 is active; approving it would supersede v4 and set `current_plan_version` **backwards 4 → 2**, discarding the meeting-2 merge. Also strands v2's 5 tasks in `pending_review`. **Code-verified, not executed** **✅ FIXED & verified 2026-08-05** (fixing phase, tranche 1) — one shared `retire_superseded_plan` helper called from BOTH supersede paths (the conflict-held exemption moved INSIDE it, since living in the caller is how they diverged), plus a newest-version guard on `activate_plan` that raises `ConflictError` → **409**. A second guard shape was added that the first cannot see: `current_plan_version` ahead while nothing is ACTIVE. **Also repaired a path this fix would have broken** — `resolve_conflict` released a held plan straight into an activation the new guard must refuse; it now retires it and tells the human. 5 tests, falsified. |
| ✅ | **F48** — the demo refusal says *"ask Jarvis to request one"*, but **no request-a-demo capability exists**: the scheduling agent has only `list_demos`/`list_demo_teams`/`calendar_view`/`book_demo`/`cancel_demo`, and Jarvis answers the same permission rule back | **OPEN** 2026-08-04 (Round 7, Act 8) — low severity; costs a wasted attempt and some trust in the app's guidance. Either reword the string (`strings.xml:537`) or build the `request_demo` tool the message promises. The refusal itself is otherwise exemplary **✅ FIXED — verified in code 2026-08-25.** `strings.xml:561` `demos_no_schedule_permission` now reads *"ask your operations lead or an admin to book it for you"*; the old *"or ask Jarvis to request one"* is gone, and the comment above it records why (the scheduling agent has no `request_demo` tool, so Jarvis answered the same permission rule back and the user went in a circle) |
| ✅ | **F47** — a **`[missing:context_summary]` placeholder reached a real client PDF**. Three gaps aligned: `template_service.missing_keys()` has **zero callers**; `draft_check` doesn't match the marker (colon/underscore fail `_LABEL`) — proven with controls; and all four `find_blanks` call sites check **subject+body only, never the attachment** | **OPEN** 2026-08-04 (Round 7, Act 7) — **real email sent** via `approve?allow_blanks=false`, i.e. the strict guard ran and passed because it inspected the wrong text. F30's exact scenario through the one channel F30 does not cover **✅ FIXED & verified 2026-08-05** — `_MISSING_KEY` added to `draft_check` (`_LABEL` NOT loosened; `[see attached]`, `[Rs 59,000]` and prose-with-a-colon all still pass), the blank check now reads the **attached proposal narrative** on both approve routes and in the preview `blanks` field, and `missing_variables` — dead code with zero callers — now fires at proposal BIRTH with a `needs_human` decision row. **Sub-item 3 answered:** `context_summary` is not a misnamed key; it is optional at every layer (`context_note` → `or ""` → the renderer treats empty as missing), so an omitted optional argument prints a placeholder into a client document. ⚠ **Two existing tests were asserting the bug** — they built a proposal with no `context_summary` and asserted it SENT. ⚠ **Name correction:** the dead function is `missing_variables`, not `missing_keys` as this entry says. 6 tests. |
| ✅ | **F46** — "why did you pick X" is routed to the **conversation** agent (per the app's own label, consistently), so it explains why it *said* the name rather than surfacing `assignments.reason`; `why_trace` is never reached from natural language | **OPEN** 2026-08-04 (Round 7, Act 6) — fair re-test on a name it had used returned *"that's why I mentioned Baski"*, **dropping the stored caveat "tie; lead should confirm or change"** — the one clause the question exists to surface. First test of this was unfair; see the method note in the entry **✅ FIXED & verified 2026-08-05.** Confirmed as the finding says — a **tool gap, not a routing bug**. Two changes: `assignment_reason` is now in `_item_dict` so the recorded reason reaches the model **verbatim, caveats included** ("tie; lead should confirm or change" is the clause the question exists to surface, and a paraphrase drops exactly that), and a new `explain_decision` tool wraps `why_trace`, which previously had **one caller** — the app's Why? chip — making DM §5.5's "any human can always ask" true only for people tapping a UI control. **The F19 regression was specifically re-guarded** by test, since F46 changes the very dict F19 broke. |
| ✅ | **F45** — terse `who is doing the curriculum` answers with the **client's** coordinator; `who is assigned to the curriculum task` correctly answers **Baski**. Retrieval works — the bare phrasing silently resolves to client-side people | **OPEN** 2026-08-04 (Round 7, Act 6) — inverts responsibility for a deliverable (rep waits on a client who was never asked). **F28 does not regress** — no lookup error — but the rule's "never silently guess" half is violated **✅ FIXED 2026-08-05 (prompt + data); live phrasing NOT re-verified.** The query agent is now told that "who is doing / owns / handling" means **which of OUR people**, answered from the task's assignee — client staff are contacts, not people work can be given to — and that falling back to the client side must be **said out loud**, never silently. ⚠ This half is a prompt change, so it is weaker evidence than the tool changes beside it: the deterministic tests pin the data's reachability, not the model's phrasing. |
| ✅ | **F44** — drafts put the model's subject **inside the body** as a literal `Subject:` line, and **replies have no subject at all** (`inbound_engine` derives `f"Re: {msg.subject}" if msg.subject else None` at 6 call sites; "Log a client reply" makes Subject optional). Separately, a rejection note can only change the body | **OPEN** 2026-08-04 (Round 7, Acts 5 **and 9**) — **3 of 3** pending drafts affected; both replies have `subject=None` while their body opens `Subject: …`. If approved, the client gets a **subjectless** email whose first line is a header. Scope widened from the original redraft-only write-up **✅ FIXED & verified 2026-08-05.** The two halves solve each other: `split_leading_subject` **promotes** a leading `Subject:` line into the subject field rather than discarding it, on both the draft and redraft paths — so the model's own good subject lands where it belongs. A `reply_subject()` helper replaces the identical expression at **all six** `inbound_engine` sites, falling back to the project name so logging a phone call no longer produces a subjectless email. **Only a *leading* line is touched** — a "Subject:" quoted mid-body is prose, and rewriting it would trade one defect for another (pinned by test). 10 tests. |
| ✅ | **F43** — project **"What's blocking?"** consults only `blocked=True` + overdue over `OPEN`/`IN_PROGRESS` (`assistant_engine.py:486-506`), so it ignores **pending approvals** *and* **open conflicts** — the two things that actually stop work | **OPEN** 2026-08-04 (Round 7, Acts 5 **and 11**) — Act 5: reported *"Nothing is blocking"* with the plan frozen and 10 tasks unstaffed. Act 11: with **4 open conflicts holding plan v5**, it listed **16 OVERDUE rows and never mentioned them**. Silently empty, then noisily wrong. Deterministic; reproduces every time **✅ FIXED & verified 2026-08-05.** `recompute_health`'s ranking is extracted as `sync_engine.health_signals` and **shared** with `whats_blocking`, so the assistant and the ops lead's Delivery card can no longer answer the same question differently — which is what F43's own correction showed was happening. Pending approvals are added **only** to `whats_blocking`, deliberately not to health: a draft awaiting sign-off is normal, and counting it would mark healthy projects `at_risk`. A held re-plan is now reported **before** any single late task (pinned by test) — Act 11's failure was burying the real problem under 16 OVERDUE lines. ⚠ **The overdue-counting half is [F52]'s and is deliberately untouched**; see the trap in the spec-check pass. 6 tests. |
| ✅ | **F41** — people the model identifies in a first meeting (name **and** role, stated explicitly) become free-text notes only; stakeholder creation iterates the lead's **contacts** (`planner_engine.py:1330-1353`), so with none the model's people data is discarded | **OPEN** 2026-08-04 (Round 7, Acts 3-5) — after a full cycle: **0 contacts, 0 stakeholders, 11 commitments ownerless**; nothing at Orchid can be emailed. **Violates the spec**: Data Model **§3.3** says contacts are created "from a business-card scan, **from a meeting**, or typed by hand" (`source` enum includes `meeting`), and **§3.4** says stakeholders are "Created by the Planner Engine **when meetings reveal who is who**". `source='meeting'` has **0 rows** and exactly **one writer** — inside the function the create path never calls. **CAUSE PROVEN 2026-08-04 (Act 10): pure wiring gap.** Meeting **2**, same lead and contract, created `Mr. Rao` as a contact (`source=meeting` — the first such row ever) **and** a `trustee`/`decision_maker` stakeholder, because the merge path calls `sync_stakeholder_specs` and the create path does not. Adding contacts by hand does not repair the project **✅ FIXED & verified 2026-08-05** — the contact-creating block is factored out as `ensure_contacts_for_specs` and called from BOTH paths, so the create path's existing stakeholder loop finally has something to iterate. **Neither documented trap was hit**: no double-creation (pinned by test) and the `is_primary → decision_maker` rule survives (pinned by two tests, because losing it silently re-creates F41's consequence #3). **Consequence #4 is fixed too** — `backfill_stakeholders_for_contact` runs on both contact-creation routes, so adding a person by hand now repairs the project instead of doing nothing. 7 tests, falsified on both halves separately. |
| ✅ | **F42** — the commitment register stores **raw transcript fragments** (3 of 11 begin with "and" or trail off), and **double-counts** any promise the planner splits into two tasks — structurally, since `commitment` is a per-task sub-object linked 1:1 | **OPEN** 2026-08-04 (Round 7, Act 5) — "and the procurement and delivery of the 40 maker kits." stored twice (due 08-23, 08-28). Not an ASR problem (transcript clean at 0.857). **Do not fix by de-duplicating on text** — that breaks the 1:1 task↔commitment linkage **✅ FIXED (text) + REFUTED (the duplicate) — see the `## F42` section below, which is the authority on this one.** The 'structural double-count' is **correct behaviour**: the two rows link to two genuinely different tasks with two deadlines. Only the TEXT was a defect and it is fixed — `app/ai/planning.py:530` now requires a SELF-CONTAINED sentence per task. Verified live 6/6 |
| ✅ | **F40** — the `ConsentRecord` linked to a meeting is created at upload with **hardcoded** `method="in_app"`, `note="Confirmed at upload"` (`meetings.py:100-105`), discarding the method the user actually recorded; and `consent_confirmed` is a self-asserted caller flag, never verified | **OPEN** 2026-08-04 (Round 7, Act 3) — device-observed: user chose *verbal* ("Principal Nair and team agreed verbally"), meeting is linked to an `in_app` record instead. The API both trusts the consent claim and manufactures its evidence **✅ FIXED & verified 2026-08-05.** Upload now **links the consent the human actually captured** instead of manufacturing a second, contradictory one — setting `meeting_id` on the pre-existing row, which is linking rather than editing (method, note, captured_by and captured_at are untouched, as §3.5 requires). **The second gap is closed too:** with no consent record captured beforehand the upload is now **refused**, so `consent_confirmed=true` can no longer manufacture a complete-looking trail for a recording nobody agreed to. A 24-hour staleness window stops a months-old row being attached to today's recording — the same defect in different clothes. **8 test/script upload sites had to start capturing consent first**, which is a gain: they were exercising a flow the product does not have. 3 tests. |
| ✅ | **F39** — recorder **pause is one-way**: `resume()` publishes through `publish()`, which early-returns while the status is `PAUSED`, so the state never leaves `PAUSED` — yet `recorder.resume()` already ran, so **the mic keeps recording while the UI says "Paused"** | **OPEN** 2026-08-03 (Round 7, Act 3) — device-observed: file grew 49 KB/4 s while frozen at `00:26`; stop then reported **"Recorded 00:26"** for a **2.2 MB** (~3 min) file. Consent defect on the DPDP-consent screen. One-line fix identified; APK frozen mid-run **✅ FIXED 2026-08-05 (code); NOT device-verified.** `resume()` posts `RECORDING` directly instead of through the `publish()` guard that always early-returned. The elapsed time is computed **inline** rather than via `elapsed()`, because `elapsed()` branches on `current().status` and `postValue()` is asynchronous — calling it would have republished the frozen value and re-frozen the timer, which is the trap this fix was one line away from. Folded in both UI halves: the dedicated pause button was hardcoded to `ACTION_PAUSE` (so it could only ever pause again) and is now a toggle, and the record button's `contentDescription` now becomes "Resume" — previously a screen-reader user was told "Pause" in both states, on the one screen where knowing whether the mic is live matters. ⚠ **App has no test harness (`test/` and `androidTest/` are empty) and the APK was not installed — compile-verified and reasoned only. The device check is: pause, watch the file stop growing, resume, watch the timer move.** |
| ✅ | **F38** (spec-checked 2026-08-05: **inference, not a contract violation** — W2's `needs_review` gate exists and behaved correctly; nothing in the spec says a *correction* must reach an already-queued message) — a corrected contact email **cannot reach the queued message by any path**: the verify sheet's edit does not re-point it (`leads.py:400-421`), and **rejecting it redrafts with the same wrong address** | **OPEN** 2026-08-03/04 (Round 7, Acts 2, 5) — contact fixed to `mekaghni@` at 17:2x; redraft at 21:46 still `mekaghnni@`, despite a rejection note naming the error and the note being applied. `EMAIL_MODE=smtp` live, so the queue keeps re-offering a send to a dead mailbox **✅ DISSOLVED — verified in code 2026-08-25.** `app/api/leads.py:389-403`: the intro is no longer drafted at card-scan. Drafting moved to the human's SAVE (`PATCH /contacts/{id}`), so a corrected address is simply the address the draft is built from — there is no stale copy left to reach. Abandoning the verify sheet now queues nothing |
| ✅ | **F37** — the F31 app guard scanned line by line and could not see setter calls wrapped onto the next line, so it reported "none" for a file containing one. F31's "nine literals" was really **eleven** | **FIXED & verified** 2026-08-03 — whole-file matching + a wrapped-call fixture (precision 11/11); the 2 literals are reported but **not yet moved to `strings.xml`** (would need an APK rebuild mid-simulation) |
| ✅ | **F59** — **`verify_live_assistant_context.py` is 4/6 and was 6/6** (2026-07-23). Two F17 checks fail: *"without a chip the query is unscoped (both clients present)"* and *"an explicit 'all clients' request broadens past the chip"*. **Both return an EMPTY set**, not the wrong client — so the tool yields nothing rather than over-scoping. The two checks that F17/F19 exist for (chip scoping, and priority beating due-date) still **PASS** | **✅ DIAGNOSED & CLOSED 2026-08-25 — NOT A PRODUCT DEFECT.** Run live against `openrouter`: the model emits `{"owner": "me", "status": "open", **"client": "all"**}` on both failing checks, the tool returns every client's items and the replies name both clients. **The hypothesis recorded here (the model not emitting `client="all"`) is refuted by the args.** The real cause is the harness: `actions[].result` is `agents/base.py::_preview`, which returns the object under 800 chars of JSON and a **truncated string** over it. Scoped = 2 items = 623 chars → list → passed. Unscoped = 3 items = **941 chars** → string → `_tool_result`'s `isinstance(..., list)` returned `[]`, reported as "an EMPTY set". Nothing regressed — the payload grew as F19/F45 added fields to `_item_dict`. Fixed in the script (`_clients_reached` falls back to the reply **and names the weaker evidence**); the lossy contract is now pinned by `tests/test_action_preview_is_lossy.py`. **Script now 6/6.** ⚠ `AssistantFragment.findEntity` reads the same field and needs a `Map`, so a truncated preview also costs an action card its deep link — accepted, recorded |
| ✅ | **F60** — **the card scanner crashed on Capture.** `IllegalArgumentException: @Part parameters can only be used with multipart encoding` for `ApiService.contactFromCard`. **A regression I introduced myself**: the F58 resolver was inserted using the `@POST(...from-card)` line as an anchor, which landed **between `@Multipart` and the method it belonged to**, so `contactFromCard` silently lost it | **FIXED & verified 2026-08-06** — the annotation is glued back, with a comment saying why it must stay. **It compiled perfectly**: Retrofit validates lazily, at the first call, so it sat undetected until someone tapped Capture. Audited all 5 modifier annotations and every `@Part` usage in the interface — no others split. ⚠ **The durable lesson: never anchor a code insertion on a line that may be part of an annotation block.** APK rebuilt + reinstalled |
| ✅ | **F61** — **a corrected proposal was emailed as the OLD PDF and the OLD body.** Live: a proposal drafted while it still read `[missing:context_summary]`, blank then filled, PDF correctly re-rendered — and the client received the stale one. `create_message` did `return existing` when the idempotency key `proposal-email-{id}-{addr}` matched, handing back the first draft untouched | **FIXED & verified 2026-08-06** — proven from the live rows: proposal `pdf_path=7bb628c5…` vs sent `attachments[0]=000567ef…`, two different files. A draft still in `draft`/`pending_approval` is now **refreshed**; anything `queued`/`sent` is untouched, so the double-send guard holds and history is never rewritten. **[F38]'s shape one level up**, and **[F47]'s fence made it sharper** — the fence read the CURRENT proposal (clean, so it passed) while the send used the stale attachment. 2 tests, falsified |
| ✅ | **F62** — **"tell me a brief about the project" had no data behind it.** The assistant fell back to semantic note search, found nothing (embedding credits exhausted) and asked the user what to look up. **No agent tool returned a project at all** — all eight were lead- or task-scoped | **FIXED & verified 2026-08-06** — new `get_project_brief` tool + `assistant_engine.project_brief`: objective, status, health **and why** (reusing F43's shared ranking), live plan version, task counts, the client's people, open promises, what is due next. A client with no project says so plainly instead of "no results". **Third instance of [F46]/[F57]'s pattern** — a question the product invites, no tool exposing it. 4 tests |
| ✅ | **F63** — **a demo the client asks to move IN A MEETING does not move; a task moves instead.** Reported live: demo booked 9 Aug, meeting says "shift it to the 15th", the merge re-dates some other thing and the demo keeps its date. Two structural causes: `VALID_OPS` had **no op that could move a demo** (only `redate`, which moves a TASK), and the merge snapshot **never showed demos at all**, so the model could not even name one | **FIXED 2026-08-06 (application half verified; the model's CHOICE of op is not)** — new `reschedule_demo` op applied at activation like every other op, demos listed in the snapshot **with ids**, the prompt states why re-dating a task is the wrong tool, an unknown id or vague date is dropped, and moving the date **re-invites the client** (drafted, held for a tap). **Fourth instance of the F41/F54/F56 pattern.** ⚠ **Only reachable from a MERGE** — the initial-plan contract has no `ops`, so a FIRST meeting still cannot move a demo. 6 tests, falsified against the activation handler |
| ✅ | **F64** — **the project card overstated the engagement 45x.** Live, off the app: *"projects card — it is showing Rs. 51,540,000, is this correct?"* It was not — the truth is **₹11,50,000**. `_estimate_value` scaled **every** non-flat pricing line by the single `pricing_quantity` the planner extracted, so 120 racks priced the **per-hall** line 120 times and the **per-site** line 120 times | **FIXED & verified 2026-08-07** — each line now scales by its **own** `default_quantity`, falling back to the discussed count only when the line declares none. `proposal_service` has always done exactly this, so the **proposal for the same project totalled 1,150,000 while the card said 51,540,000** — two numbers for one engagement, both on screen. **Second defect found during the fix:** `admin.PricingItem.default_quantity` defaulted to `1` and `model_dump()` **materialised it**, so every admin-created line claimed a quantity of one and "unspecified" was unrepresentable — now `None`. Only 2 of the 6 pricing tables in the repo carry `default_quantity`, both were wrong, both are now right. 8 tests, falsified (6/8 fail without it), `dryrun_workflows` **43/43** with its `==126000` and `==115000` fences intact. **Every earlier catalogue priced in ONE unit, which is why this survived** — the datacentre table is the first with three |
| ✅ | **F65** — **the briefing calls today's work overdue between 00:00 and 05:30 IST.** `assistant_engine:78` uses `date.today()` (**local**) while due dates are stored against `utcnow()` (**UTC**). IST is UTC+5:30, so for those 5.5 hours the local date runs one ahead and every task due today is read as due yesterday | **✅ FIXED & verified 2026-08-25 — and the cause was one layer deeper than this entry says.** The mix is real but its trigger is **narrow**: it bites only when the stored instant's UTC date differs from the reader's, i.e. UTC hour ≥ 18:30 for IST — work created or falling due between 00:00 and 05:30 IST. **Measured on the live DB: 1 of 29 rows.** That is why Jarvis answered "what's due today" correctly in practice and why this looked intermittent. Fixed by `app/core/clock.py`: storage stays UTC, every date JUDGEMENT runs in `org_settings.timezone`. **25 call sites moved** — the briefing, both planner prompts, extraction, `agents/base.py`'s clock note, both follow-up paths, the demo month parser, the resource week and the scheduler (whose follow-up sweep judged every tenant against one server date). Guard: `tests/test_one_clock_guard.py` AST-bans bare `.today()`/`.now()`/`.utcnow()` in `app/`. `MeResponse.org_timezone` added so the app agrees (`WorkDay.java`). `tzdata` added to requirements — `ZoneInfo` has no database on a slim image |
| ✅ | **F66** — **every proposal draft opened with `[missing:context_summary]`.** Reported live with a screenshot: *"why does it still create it including the missing context summary?"* The org template puts `{context_summary}` where the opening paragraph goes; `create_proposal` declares `context_note` **optional**; the model omits it; `build_proposal` does `context_summary or ""`; the renderer turns `""` into the marker. **Nothing was broken — nothing ever supplied the value** | **FIXED & verified 2026-08-07** — it was never the model's to remember. The **project's `objective`**, written from the meeting by the planner, is exactly the one-to-two sentence summary the template asks for; `build_proposal` now reads it when no note is passed. **Why [F47] and [F61] did not cover this, and the distinction is the lesson:** F47 made the marker BLOCK the send gate, F61 stopped a stale PDF being attached after a blank was filled — **both act on a draft that already carries the marker; neither makes the draft come out clean.** *Blocking a bad output is not the same as producing a good one.* Nothing is invented: with no project or no objective the marker remains and F47 still escalates (tested). An explicit note always wins; a `closed`/`lost` project is never used. 5 tests, falsified. **Also observed: assistant-created proposals carry `project_id = None`** — the agent builds from the LEAD and never links the project. Left alone deliberately — linking would feed `inbound_engine`'s `value_estimate` accumulation. Logged as [F67] |
| 🔴 | **F67** — **a proposal created through Jarvis is not linked to its project** (`proposals.project_id IS NULL`). `proposal_agent._create` calls `build_proposal` with `lead_id` only, so anything keyed on `project_id` — project-scoped proposal lists, the weekly report, `inbound_engine`'s amendment accumulation — cannot see it | **OPEN** 2026-08-07 — found while fixing [F66] (that fix resolves the project to read its objective, but deliberately does **not** assign it). **Not fixed on purpose:** `inbound_engine:1242` does `project.value_estimate += proposal.total_amount`, so linking retroactively would start moving project values on a path where it never did before. Needs its own scope and its own falsification |
| ✅ | **F68** — **Jarvis does not know what day it is.** Reported live with three screenshots. Asked *"what tasks do I have due by this Friday?"* it answered *"If **2026-09-01 is 'today' for you**, then those 3 tasks are due today"* — **it asked the user for the date.** `app/ai/planning.py` (initial + merge) and `app/ai/extraction.py` are all handed `today`; `agents/base.py:_system()` — the prompt behind the **only component a human converses with** — had **no date reference at all** | **FIXED & verified 2026-08-07** — the date and weekday are now in the shared `BaseAgent._system()`, so all **6** agents inherit it (test asserts each one, per the F41/F54/F56/F63 "wired to one entry point" pattern), read per-request so it cannot freeze at import. **The failure mode is the lesson: a model with no clock does not say "I don't know the date" — it borrows a day name from the question and states it as fact.** It called **2026-09-01 a Friday** (it is a Tuesday) and reported *"due Friday"* for *Send Fatima the engineer list*, whose `due_date` is **NULL**. The prompt now also forbids naming a weekday not derived from a real date, and requires "not set" for a missing due date. **The stored dates were correct throughout** — *Send full proposal by Friday* really is due 2026-08-07, which really is a Friday. This was pure narration. 6 tests, falsified (5/6 fail without it) |
| ✅ | **F69** — **a rejection note asking for a FACT could not be obeyed.** Reported live: a demo was booked, the owner rejected the draft with *"add the demo date too"*, and the redraft came back asking the CLIENT *"could you please confirm the demo date?"* — **a date we had already scheduled and told them.** `redraft_rejected` called `compose_body` with `facts={"original_draft": ...}`, `sender_name=""`, `org_name=""` and nothing else | **FIXED & verified 2026-08-07** — **not a hallucination; the honest failure of a blind path.** `compose_body`'s system prompt says *"Use ONLY the facts provided — never invent numbers, dates or promises"*, so a model told to add a date it had not been given could only invent one or ask. **It asked — which is why nothing looked broken.** The real defect is asymmetry: `draft_client_message` composes with rich `facts`, the sender's real name, the org name and the stakeholder's language; **the redraft threw all four away and re-derived none of them.** The redraft now receives scheduled demos (date + time), the project name and objective, the real sender and the org. The "only the facts provided" rule is untouched: **with nothing scheduled the key is ABSENT, not an empty list** (tested — an empty list invites the model to fill it), and `cancelled`/`completed` demos are excluded so we never tell a client to attend something we called off. 5 tests, falsified (3/5 fail without it). **Fifth instance of the F41/F54/F56/F63 pattern** — the data existed, the path never looked |
| ➖ | **F5, F16** — not code fixes | **NO FIX PLANNED** — F5 = *monitor* (did not reproduce in 6 recordings); F16 = *scope reality* (org_admin screens are Phase 8) |

> ⚠️ **The two paragraphs below are scoped to the 2026-07-22/23 job only** and were written
> before F27–F31 existed. "All fixable findings are done" meant *all of F1–F26*. **The status
> table above is the single source of truth**; today it says **F31 is OPEN**.

**All fixable findings [of that job] are now done.** F25 was fixed 2026-07-23 (seed a skill
taxonomy + constrain the planner + a deterministic coercion). What remained then was
deliberately *not* a code fix: **F5** (monitor — did not reproduce in 6 recordings), **F16**
(Phase-8 scope), **F26** (accepted), **F27** (planned as Phase 6; since closed).

**Done in that job:** F4/F4b, F8, F9, F22, F1, F2, F10, F3, F11/F6, F17, F19, the copy pass
(F7/F13/F14/F15/F12), F23, F24 and F25 — verified on the Vivo against
the live backend wherever the UI could reach it (exceptions, all covered by unit + live tests
through the production code path: the card-scan half of F2 needs a camera; F23 needs a seeded
proposal the demo org lacks).

**Model switch (2026-07-22, config-only, flagged).** The project no longer runs on the free
tier. A measured bake-off of six candidates against the three live scripts — plus a vision
probe and a STRONG probe, both written because no existing script covered those paths — put
`openai/gpt-5.4-nano` on FAST (42/42 three runs running, **5.9× faster** than the free model,
card scan 0.95) and `google/gemini-2.5-flash` on STRONG. `qwen3.5-flash` (18/22: a 1-task
plan that dropped two confirmed to-dos), `gemini-2.5-flash-lite` (JSONDecodeError on 1 run in
5) and `gemini-3.1-flash-lite` (exhausted its tool-step budget) were each rejected on
recorded evidence. **Lesson: n=1 lies** — two of those three looked fine or looked fatal on a
single sample and reversed on repetition. Details in the `openrouter-paid-model-switch` memory.

**Round 2 (F17, F19, F22)** came from a Jarvis chat review *after* the F4/F8/F9 fixes — the
answers read correctly while the scoping, ordering and counts underneath them were wrong.
**All three are now fixed** (F22, then F17 and F19 on 2026-07-23). See the "Round 2" section
near the end of this file.

**Verification standard applied to every fix in this job** (handoff §7 — all four suites
re-run green after every change, plus device proof):

| suite | latest (2026-07-23) |
|---|---|
| `pytest` | **67/67** (was 50 at the start of the job; +17 new: 3 F17/F19, 1 F15, 1 F23, 1 F24, 3 F25) |
| `scripts/dryrun_workflows.py` | **43/43** |
| `scripts/verify_gap_endpoints.py` | **21/21** |
| `scripts/verify_generic_stakeholders.py --stub` | **21/21** |
| `scripts/verify_live_meeting_extraction.py` | **8/8** |
| `scripts/verify_live_meeting_planner.py` | **24/24** (22 + 2 added for F22) |
| `scripts/verify_live_conversation.py` | **12/12** |
| `scripts/verify_live_assistant_context.py` | **6/6** — **new**, F17/F19 against the real model |
| `scripts/verify_live_proposal_guard.py` | **3/3** — **new**, F23 against the real STRONG model |
| `scripts/verify_live_planner_skills.py` | **3/3** — **new**, F25 (planner picks from the taxonomy) |
| `scripts/verify_live_answers.py` | **2/3** — see **F26**, accepted |

**No schema change was made by any fix in this job**, proven by diffing a copy of
`data/salesplatform.db` against a freshly-initialised schema (55 tables, 0 columns added or
dropped). Every fix except the card-scan half of F2 was additionally verified **on the Vivo**
against the live backend.

---

## Test environment — *as it was during the original simulation (2026-07-21/22)*

> This table records the conditions the findings below were **observed** under. It is history,
> not current state: the app, the models, the port and the database have all changed since.
> **For the current environment always read handoff §8-pre5**, which is maintained per session.

| | |
|---|---|
| App | `0.6.1-conversation` (installed fresh over `0.6.0-phase5`) |
| Device | Vivo V2514, adb serial `10BFBT0TXJ001NP`, `adb reverse tcp:8000 tcp:8000` |
| Backend | `Complete_Project`, port 8000, **live `.env`** — `EMAIL_MODE=smtp`, `CALENDAR_MODE=google`, `LLM_PROVIDER=openrouter` |
| DB | **freshly seeded** (`scripts/seed_demo.py`); previous DB backed up to `data/salesplatform.db.presim-20260721-2242` |
| Accounts | all 9 seeded logins exercised (admin, rahul, siva, mithun, sourav, baski, shyam, rahul.reddy, superadmin) |
| Real inputs | a real Telaverge business card scanned through the camera; a real 2:47 meeting recorded through the phone mic |

**Scenario used throughout:** a new generic (non-school) lead — *Telaverge Solutions*, an
engineering-services company wanting a CSR-funded STEM program. Chosen deliberately to test the
system's claim of domain-genericity.

---

# Priority 1 — functional gaps in the core promise

## F9 — Recording a meeting does NOT start the machine; typing the same notes does

> ### ✅ FIXED 2026-07-22 — see "How F9 was fixed" at the end of this section.

**Severity: highest.** `app/jobs/pipelines.py` (audio) vs `app/api/meetings.py:393` (notes).

`POST /meetings/notes` calls `planner_engine.process_meeting(...)` — the full Workflow-1
machine. The **audio pipeline never calls the planner at all**: transcript → extraction → flat
action items → memory → intelligence → lead-state suggestion, then stops.

**Proven live — same lead, same content, same day.** A 2:47 recording, then the same substance
typed as notes on the same lead:

| | Recorded audio | Typed notes |
|---|---|---|
| Project | none | "Telaverge IBC CSR STEM Program" (planning / on_track) |
| Action plan | none | v1, trigger `first_meeting`, active |
| Tasks | 6 flat | 7 phased (proposal / preparation / sales / delivery), P1/P2 |
| Due dates | **all NULL** (see F8) | real (24 Jul, 31 Jul, 1 Sep, 19 Sep) |
| Client commitments | none | 4, dated, linked to tasks |
| Stakeholders | none | 1 (Ekaghni → csr_manager / influencer / email) |
| Assignment proposals | none | 4 `proposed` |

**The app actively asserts the opposite.** The typed-notes composer says verbatim:

> "The Planner reads these notes **exactly like a recording's transcript**: it extracts tasks,
> updates plans and drafts follow-ups…"

The equivalence is false, and false in the direction a user would never guess — typing gives
strictly *more* than recording. Workflow 1 ("First meeting to first plan: the whole machine
starts") is the product's headline promise; the recorded path does not deliver it.

**Fix:** have the audio pipeline call `planner_engine.process_meeting` with the transcript it
already has, exactly as the notes path does. This also resolves F8.

### How F9 was fixed (2026-07-22)

The naive fix — just calling the Planner from the pipeline — turned out to hit three
problems that this write-up had not seen. All three are handled.

**Shape chosen: the review gate goes first.** (Options were weighed with the user; this one
was picked over "notes parity" because an auto-activated plan would otherwise leave *no*
human gate on task existence at all.) The pipeline is unchanged up to `review_pending`; the
human confirms what the meeting actually agreed; `POST /meetings/{id}/review/confirm` then
enqueues a new **`plan_meeting`** job which runs `planner_engine.process_meeting` seeded with
the confirmed to-dos, so the plan is built AROUND them instead of deriving a rival list.
When the org has the review gate switched off there is no confirm moment, so the pipeline
runs the Planner inline over the items it just opened. Recording is therefore now *richer*
than typing, not merely equal to it.

**The three problems found while building it:**

1. **Task duplication.** Extraction writes flat items; the Planner writes plan tasks *with
   the same `meeting_id`*. Solved by the seeding above (`planning.agreed_block`) plus a
   deterministic fence, `planner_engine._drop_duplicates_of_confirmed` — a weaker model was
   observed live carrying "Provide safety compliance documentation" verbatim AND inventing
   "Prepare safety compliance documentation". The fence drops only a task redundant with an
   already-represented confirmed to-do; it deliberately does NOT merge "schedule the demo"
   vs "confirm the demo" (0.67 < 0.7 threshold). Prompt-only prevention was tried first and
   demonstrably did not hold on the free model.
2. **Review-gate collision — a latent bug that already existed on the notes path.** Plan
   tasks are created `pending_review` and carry the meeting id, so they surfaced in
   `GET /meetings/{id}/review`; confirming would have flipped them open behind
   `activate_plan`'s back (no staffing, no dependency wiring) or cancelled them as "not
   echoed back". Guarded by `plan_version_added IS NULL` in `_review_items_query`, used by
   both the GET and the confirm.
3. **Every recording looked like a FIRST meeting.** `/meetings/upload` carried no
   `project_id`, so a second recording on a live engagement forked a duplicate project.
   Fixed by `planner_engine._resolve_meeting_project`. **The first attempt at this was
   wrong and the dry-run suite caught it** (W30 failed: it hijacked a genuinely *new*
   engagement into a merge). The routing decision is now always the model's — including
   when there is only one live project, because "another meeting on the ongoing work" and
   "a new engagement with an old client" are indistinguishable from a row count — and the
   stub provider explicitly declines to guess. `planning.match_message_project` gained an
   explicit "a fresh engagement with an existing client is new work" instruction and a
   `source_kind` argument. `/meetings/upload` also gained an **optional** `project_id` form
   field so recording from a project home can be explicit.

**Contract changes (all additive, older apps unaffected):** `POST /meetings/upload` accepts
optional `project_id`; `POST /meetings/{id}/review/confirm` returns an extra `planning`
boolean. **No schema change.**

**App:** `ReviewConfirmResponse.planning` + a new toast — *"N task(s) are live. The Planner
is building the plan from this meeting — the project and its approvals will appear
shortly."* Without it the new behaviour would have been invisible, which §7 rule 3 forbids.
Build `0.6.2-findings`.

**Verified on the Vivo** with real recordings: a lead that already had a project **merged**
(plan v1 superseded → v2 active, no fork); two project-less leads each **birthed a project**
with phased, dated tasks, client commitments and a stakeholder in the client's own
vocabulary (`vp_operations`, `safety_head` — both `decision_maker`), confirmed to-dos
carried exactly once, no duplicate pairs, no title pollution.

---

## F8 — Meeting-derived tasks never get a due date

> ### ✅ FIXED 2026-07-22 (with F9).
> `extraction.analyse_meeting` is now given today's date and returns an ISO `due_date`
> alongside `due_hint`; `pipelines.py` writes it to the **column**. A hint the model cannot
> resolve stays as prose in the description rather than becoming a guessed date the nudge
> ladder would act on. Verified live on device: "by Friday" → 26 Jul, "last week of August"
> → 25 Aug, "first week of October" → 5 Oct.

`app/jobs/pipelines.py:111-113`

```python
description=(raw.get("description") or "")
    + (f" (due: {raw['due_hint']})" if raw.get("due_hint") else ""),
```

`due_hint` is concatenated into the **description text** and never parsed into `due_date`.

**Observed live:** the AI correctly extracted "by Friday" and "last week of July"; the review
gate displayed them; the user confirmed them. All six resulting rows have `due_date = NULL`:

```
open | Send the IBC proposal with commercials by Friday | due None
open | Include safety compliance documentation          | due None
open | Arrange live demonstration for leadership        | due None
open | Loop in finance controller Priya Nair            | due None
```

**Why it matters — the rest of the system is date-driven:**
- `build_daily_digest` buckets on `due_date` → these can never show as Overdue / Due today.
- My Tasks groups Today / This week / Later off the same field → every meeting task sinks to
  **"Later · No due date"** permanently (confirmed on screen).
- Reminders and the W10 nudge ladder key off due dates → no nudge ever fires for a meeting task.

The date the client actually heard ("proposal by Friday") survives only as prose in a description.

**Fix:** have extraction return an ISO `due_date` alongside `due_hint` (the model already knows
the meeting date), NULL only when genuinely unparseable. Subsumed by fixing F9.

---

## F4 + F4b — The meeting-analysis prompt hardcodes "school", and writes false facts to permanent memory

> ### ✅ FIXED 2026-07-22 — see "How F4/F4b was fixed" at the end of this section.

`app/ai/extraction.py:12-24`

```
You are analysing the transcript of a sales meeting between a
salesperson from {org_name} and staff of the school "{school_name}".
...
4. key_facts — up to 5 short facts worth remembering about this school
```

**Observed live.** The audio said *"we want to run it across three of our offices."* The AI
summary returned:

> "…outlined a plan to run a pilot across three **school** offices—Bengaluru, Hyderabad, and Pune"

**F4b — the real damage.** After the review gate, `client_intelligence` (the org's long-term
notebook, `category='from_meeting'`, `source='system'`) permanently stored:

> **"The school operates offices in Bengaluru, Hyderabad, and Pune."**

Telaverge Solutions is an engineering-services company. Nobody said "school". The AI wrote a
**false fact into durable storage**, which later feeds `search_past_notes`, the knowledge
engine, and future proposal context. The contamination was also seen propagating back out
through the assistant ("Schedule a live demonstration for the **school's** leadership team").

**Why this outranks the handoff's §6c list:** every item in §6c is a variable name, a stub-path
default, or an example string. This is a **live LLM prompt on the primary meeting path**.

**Fix:** neutral wording — "…and people at the client organisation `{lead_name}`", and "facts
worth remembering about this client".

### How F4/F4b was fixed (2026-07-22)

Neutral wording as prescribed (kwarg renamed `school_name` → `client_name` at all three call
sites; `pipelines.py:138`'s `'school'` memory-index fallback went with it, since it is the
same defect writing into durable storage).

**The wording alone was not the fix.** Removing the word does not stop a model inventing a
domain, so the prompt now also says: *"The summary and key_facts are stored permanently and
reused, so describe the client only in the words the transcript itself uses: never assume an
industry, sector or type of organisation that was not stated, and never substitute a
different word for one the speakers used."*

**Proven against the exact failure.** `scripts/verify_live_meeting_extraction.py` replays the
**verbatim transcript of the real 2:47 simulation recording** (Whisper's F5 hallucination
included) through the live model. That transcript contains the word "school" zero times, so
any occurrence was prompt-injected. It also checks the **opposite** direction — a transcript
that genuinely is about a school must still read as one — because "never say school" would
be the wrong fix. 8/8.

Before → after on that identical input:

| | |
|---|---|
| Summary | "…a pilot across three **school** offices" → "…across three offices—Bengaluru, Hyderabad, and Pune" |
| `client_intelligence` | "The **school** operates offices in Bengaluru, Hyderabad, and Pune." → "Run program across Bengaluru, Hyderabad, and Pune offices" |

**Re-verified on the Vivo** by re-recording the same sentence through the phone mic: a scan
of the new meeting's transcript, summary, action items, `client_intelligence` and
`memory_chunks` returns **0** occurrences of "school".

The **pre-existing** contaminated row from the simulation is still in the live DB
(`client_intelligence.id = b1f04323…`, "The school operates offices in…") — deliberately left
alone as evidence; delete it by hand when convenient.

---

# Priority 2 — honesty / privacy defects

## F1 — 401 session-expiry leaves the previous user's data on the device *(APP)*

> ### ✅ FIXED 2026-07-22 — see "How F1 was fixed" at the end of this section.

`core/net/AuthInterceptor.java:53-56`

```java
if (response.code() == 401 && !loginCall && !changePasswordCall) {
    tokenStore.clear();
    sessionBus.notifySessionExpired();
}
```

Only the token is wiped. `AuthRepository.logout()` — the deliberate Sign-out path — does three
things: `tokenStore.clear(); database.clearAllTables(); assistantSession.reset();` and its own
comment explains why ("the bubbles … are the previous person's words and must not greet the
next one"). The 401 path does one of the three.

**Observed live:** after the DB was reseeded (old user ids gone → `/auth/me` 401 → session
expired), signing in as **Rahul** showed a bell badge of **33** and a notification centre full
of **Siva's** notifications from the *previous database* — "Good morning, Siva", "Plan v3
active", Nexora task assignments. None of those rows existed on the server any more.

Signing out properly and back in dropped the badge to **2**, confirming the diagnosis.

**Impact:** on a shared or reassigned device, user B reads user A's digests, task assignments,
approval cards, Jarvis transcript and recent-command chips.

**Fix:** the 401 path must perform the same wipe as `logout()`.

### How F1 was fixed (2026-07-22)

`AuthInterceptor.wipeSession()` now performs the same three-step wipe
`AuthRepository.logout()` does — `tokenStore.clear()`, `database.clearAllTables()`,
`assistantSession.reset()`. App build **`0.6.3-findings`**.

**Why the interceptor and not the `SessionBus` observer.** A 401 can arrive with no Activity
alive at all — the 15-minute notification worker is exactly that case. A wipe that only runs
when a screen happens to be watching is not a wipe.

Two details that matter:
- **`Lazy<AppDatabase>` / `Lazy<AssistantSession>`.** The interceptor is constructed with the
  OkHttp client at startup; Room should not be opened merely because the network stack exists.
  No dependency cycle — neither Room nor `AssistantSession` needs OkHttp.
- **An `AtomicBoolean` guard.** Concurrent 401s are normal (the 60-second notification poll
  easily races a screen load) and must not each run a full Room wipe. The wipe is also wrapped
  so a cache-clear failure can never crash a background thread — the token is already gone, so
  the session is dead either way and the user still lands on Login.

**Verified on the Vivo by reproducing the original scenario exactly** — the finding was first
seen *because* the database had been reseeded, so the reseed IS the test fixture. Backend
stopped, `data/salesplatform.db` backed up to `…pre-f1reseed-20260722` and reseeded, so every
user id changed (Siva `b5fd7334…` → `eabbac9c…`) and the phone's token pointed at a user that
no longer existed.

| app's Room DB | before the 401 | after |
|---|---|---|
| `cached_user` | 1 (Siva) | **0** |
| `cached_notification` | **29** | **0** |
| `cached_approval` | 1 | **0** |
| `yuvipep_assistant.xml` | session id + recent commands | **`<map />`** |

Then signing in as **Rahul** showed a bell badge of **2** and a notification centre containing
only Rahul's own two rows. The original finding recorded a badge of **33** full of Siva's
notifications in this exact situation, and noted that only an explicit sign-out brought it down
to 2 — that correct value now appears after a plain 401 expiry.

---

## F2 — "waiting in Approvals" is false for card-scan intros and demo invites

> ### ✅ FIXED 2026-07-22 — see "How F2 was fixed" at the end of this section.

`app/services/intro_service.py` and the demo-invite service call
`message_service.create_message` (status `pending_approval`) but **never**
`approval_engine.request_approval` — so no `approvals` row is created and no screen in the app
can reach them.

**Two false claims shown on screen this session:**
- card-scan verify sheet: *"An intro message to … was drafted — it is waiting in Approvals,
  nothing was sent."*
- demo-booking result: *"The calendar invite is drafted and waiting in Approvals — nothing has
  been sent yet."*

Meanwhile `GET /approvals?status=pending` was empty and Siva's Approvals inbox said "No
approvals waiting".

**The machinery works — exactly two services skip it.** The follow-up queue's "Draft message
(AI)" (`POST /messages/draft`) **did** create an approvals row and appeared correctly in Siva's
"Waiting on you" as `outbound message · Decide · expires in 1d`. End-of-session state:

| kind | source | approvals row | reachable in app |
|---|---|---|---|
| `intro` | card scan (`intro_service`) | **none** | **no** |
| `demo_invite` | demo booking | **none** | **no** |
| `follow_up` | `POST /messages/draft` | yes | yes |

**Fix (small):** have those two call `request_approval` the way the draft path already does.
Both strings then become true with no app change.

This generalises what handoff §6f records as demo-invite-only; the card-scan intro has been
making a false statement since Phase 2.

### How F2 was fixed (2026-07-22)

`message_service.create_message` gained an **opt-in** `request_approval: bool = False`, and
`intro_service` and `demo_invite_service` pass `True`. Placing it in `create_message` keeps the
facts/reason/approver shape in one place, mirroring `communication_engine`'s existing
`request_approval` parameter; the approval is filed **after** the idempotency short-circuit, so
a retried card scan returns the original message and does not file a second approval.

**Why opt-in and not automatic — this write-up's "exactly two services" is wrong.** All
**five** `create_message` callers lacked an approval, not two: the Jarvis email agent, the
Jarvis follow-up agent and `proposal_email_service` are the other three. But those three are
*already reachable* — the Jarvis agents show an inline approval bar, a proposal email is sent
from the proposal screen — and `POST /messages/{id}/approve` acts on the **message**,
independent of any approvals row. Filing rows for them would have manufactured a second,
redundant inbox entry that lingers `pending` after the user has already acted elsewhere: the
opposite of the "nothing invisible" rule. The two services fixed here are unreachable by any
other route, so the inbox is the only way in and there is no redundancy to create.
*(The proposal path's existing `request_approval` at `proposals.py:310` is
`entity_type=proposal` — the document, not the email — so it never covered this.)*

**A second, pre-existing bug found while fixing the first.** Nothing closed an approvals row
when its message was decided the *other* way. Approving from the Approvals inbox runs
`approval_engine.decide → _release_message`, which handles both sides; approving with
`POST /messages/{id}/approve` (the follow-up queue and the Jarvis inline bars) updated only the
message and left the approval `pending` for its full 48-hour expiry, pointing at work already
done — and, on reject, already redrafted. `message_service._close_linked_approval` now resolves
it from that side too, with a decision note saying where it was decided. This already affected
the `/messages/draft` path today; F2 would have widened it.

**Verified.** pytest **55/55** (three new tests in `tests/test_message_approvals.py`, each
**proven to fail with the fix disabled**), dryrun 43/43, `verify_gap_endpoints` 21/21,
`verify_generic_stakeholders --stub` 21/21. No model files touched, so no schema change by
construction.

**Verified on the Vivo** (Siva, sales_lead, build `0.6.3-findings`): Approvals inbox empty
→ booked a demo on Delhi Public School → the dialog said *"The calendar invite is drafted and
waiting in Approvals — nothing has been sent yet"* → the inbox showed
**`outbound message · Decide · expires in 1d — Demo invite to principal@dps.example.edu (email)
— approve to send`**, the identical shape this write-up recorded for the *working* follow-up
draft. Approving it queued and sent the message and left the inbox at its honest empty state
("No approvals waiting"), with the approval resolved to `approved`. `EMAIL_MODE=dry_run`
throughout: `provider_message_id = dry_run:…outbox/…eml` and zero SMTP lines in the log, so
nothing left the machine.

**Not device-verified: the card-scan intro half**, which needs a real camera capture. It is
covered by `test_intro_draft_is_reachable_in_the_approvals_inbox` and travels the identical
code path (`create_message(request_approval=True)`), but it was not exercised on the phone.

---

## F10 — The "Why?" affordance can never explain an AI lead-state suggestion

> ### ✅ FIXED 2026-07-22 — see "How F10 was fixed" at the end of this section.

`ai_decisions` had **0 rows** after a card scan (vision AI), a full meeting AI pipeline, and an
AI lead-state suggestion. Tapping **Why?** on the suggestion banner returned the honest but
useless *"No AI decision is recorded for this record."*

`record_decision()` is called widely (planner, assignment, communication, inbound, sync,
approval engines) but **never** by `lead_service.suggest_state`
(`app/services/lead_service.py:94`), `sync_engine`'s suggestion paths, the meeting pipeline, or
card-scan vision.

The Why button Phase 3 deliberately added to the suggestion banner is therefore structurally
dead. (Planner-driven traces *do* work — the project Why sheet showed two real decisions with
confidence 0.90 / 0.95.)

### How F10 was fixed (2026-07-22)

**Five producers, one writer.** `suggest_state` was not the only path: `sync_engine` sets
`suggested_state` directly in three more places (project closed → `closed`, deal agreed →
`execution_in_progress`, silence sweep → `cold`) and `projects.py` in a fourth (project lost →
`lost_for_now`). Every one of them would have had a dead **Why?** too. A new
`lead_service.apply_suggestion` is now the single writer: it sets the two fields **and**
records the decision with `entity_type='lead'`, `entity_id=lead.id` — exactly what
`LeadDetailFragment:219` asks `why_trace` for. All five producers call it.

`needs_human=True` on every one, because a suggestion is by definition awaiting a person, and
each caller passes its own `engine`, `confidence` and `input_summary` so the trace says where
the suggestion came from rather than just what it was.

**Verified on the Vivo:** recorded a real meeting on *Green Valley School* (state `open`) →
the banner appeared, *"AI suggests marking active — A real recorded discussion took place"* →
tapping **Why?** rendered:

> **Why the AI did this** — Decision log for this Lead
> `[22 Jul 16:48] lead_service state_change: Suggested moving 'Green Valley School' from open
> to active — A real recorded discussion took place (confidence 0.80)`

Also covered by `tests/test_explainability_digest.py`, which asserts both the `ai_decisions`
row and that `why_trace` no longer returns "No AI decision is recorded" — **proven to fail with
the fix disabled**.

*Minor, not fixed: the sheet renders the timestamp in UTC (`16:48` for a 22:18 IST event).
Cosmetic, and it affects every Why sheet, not just this one.*

---

## F3 — Daily briefing ignores follow-ups and demos; renders as an empty card

> ### ✅ FIXED 2026-07-22 — see "How F3 was fixed" at the end of this section.

`app/engines/assistant_engine.py:52-129` builds the digest only from open `ActionItem`s,
pending `Approval`s and overnight `InboundMessage`s. Follow-ups and demos are never consulted.

On the fresh DB, Rahul had a follow-up due **today** and a demo this month, yet
`GET /digests/daily` returned exactly `"# Good morning, Rahul\n"`. The Home "Your briefing"
card rendered a heading and nothing else — reading as a broken card, and contradicted by the
"My day" cards immediately below it saying "1 due today".

**Fix:** include follow-ups/demos, or render an honest "Nothing to brief you on today" empty
state when `content_md` has no body.

### How F3 was fixed (2026-07-22)

**Both halves, not either/or.** `build_daily_digest` now also reads pending follow-ups owned by
the user and due today or earlier (marked "— overdue" when they are), and scheduled demos on
leads the user owns in the next 7 days. And when *nothing* is on — no tasks, approvals,
follow-ups, demos or overnight replies — it appends an explicit line rather than leaving a
heading over blank space, because a card showing only "# Good morning, X" reads as broken, not
as calm.

**Verified on the Vivo** (Siva): the briefing card, previously a bare heading, now renders

> **Good morning, Siva**
> **Follow-ups due:**
> • Sunrise School (email) — Share demo agenda

…which also resolves the on-screen contradiction this finding described: the "Follow-ups — 1
due today" tile immediately below it now agrees with the card above it.

Covered by two tests in `tests/test_explainability_digest.py` (a day with a follow-up + demo,
and a genuinely empty day), both **proven to fail with the fix disabled**.

---

# Priority 3 — genericity audit corrections

## F11 — More user-visible "school" strings than §6c claims

> ### ✅ FIXED 2026-07-22 — and it was far worse than this section says.

§6c states the `knowledge_engine` cross-sell copy is "the ONLY user-visible domain-worded
string". That is not correct:

- `app/ai/agents/resolvers.py:40` — rendered verbatim in the Jarvis transcript this session:
  **"No school matching 'Ekaghni' found"**. Also `:23` "Which school do you mean?" and `:43`
  "Several schools match '…'".
- `app/jobs/pipelines.py:138` — `f"Fact about {lead.name if lead else 'school'}: {fact}"`,
  written into the memory index.
- Plus F4 (`extraction.py`, the serious one) and F6 below.

## F6 — Seeded message templates are school-worded *(seed data, low)*

> ### ✅ FIXED 2026-07-22 (with F11).

`scripts/seed_demo.py` INTRO_EMAIL renders, for an engineering company:

> "Thank you for taking the time to discuss how YuviPep can support **your students**."

Org-editable, so cosmetic — but it is what a brand-new org gets on day one, and it is the first
thing the card-scan flow drafts.

### How F11/F6 were fixed (2026-07-22)

**Roughly forty sites, not the four §6c listed.** The sweep is written up in full in the
rewritten handoff **§6c**; the short version is three tiers:

1. **LLM-facing prompts — the dangerous tier, and the one nobody had counted.**
   `communication_engine`'s drafting prompt literally said *"You draft messages from an
   education-services company to schools"* — every message the product has ever drafted was
   written under that instruction. Also `inbound_engine`'s classification context
   (`School: {name}`), three `sync_engine` `purpose=` strings interpolated into that same
   prompt, both the Query and Scheduling agent system prompts, and the router's examples.
   This is the F4 class: a domain word in a prompt makes the model *write in that domain*.
2. **User-visible prose** — all three `resolvers.py` errors (including the exact
   *"No school matching 'Ekaghni' found"* seen in a real transcript), the onboarding brief's
   "School-side people:", `knowledge_engine`'s cross-sell copy, "school gone quiet",
   "Payment ladder exhausted — call the school", and more.
3. **The agent tool surface**, renamed with the user: `get_school_details` →
   `get_client_details`, `add_school_note` → `add_client_note`, and the `school` parameter →
   `client` across 7 tools in 5 agents, plus all 12 tool descriptions. **This was
   user-visible**: the app humanises the raw tool name, so the chat rendered a card titled
   literally *"Get school details"* — the thing spotted in the round-2 review. **No app change
   was required.**

**F6:** the seeded templates lost "support your students" and "sessions inside the school,
aligned with the academic calendar", and now use `{client_name}` — with `school_name` **kept
as an alias**, because removing it would silently blank the variable in every template an org
has already saved.

**Deliberately not changed** (agreed with the user): the API wire keys `"school": <lead name>`
on `/action-items`, `/demos` and `/followups`. The app maps them via `@SerializedName("school")`
and never renders the key, so it is an internal contract name; changing it needs a coordinated
app release for no user benefit.

**Two tests had pinned the OLD wording and went red** — `test_assistant.py` on the literal
`"No school matching"`, and dry-run W15 on `"School-side people" in brief`. Both were rewritten
to assert the **property** rather than the phrasing, so the next genericity fix will not look
like a regression. That is the reusable lesson: *assert what a string must achieve, not how it
is worded.*

**Verified:** pytest 58/58, dryrun 43/43, gap 21/21, stakeholders 21/21, and
`verify_live_meeting_extraction` 8/8 against the real model (which also re-proves F4 both
directions — a genuinely-a-school transcript still reads as one).

---

# Priority 4 — app copy and polish

> ### ✅ F7 / F13 / F14 / F15 / F12 — the copy pass — FIXED & verified 2026-07-23
> One app build (`0.6.4-findings`) plus one small backend change (the F15 digest greeting).
> **On the Vivo:** F12 (Jarvis greeting no longer claims "create leads"), F14 (the Team
> placeholder now reads *"Team is coming in a future update…"* — no phase number, no "build
> plan", grammar fixed), F7 (the add-missed dialog is titled *"Add an item the AI missed"* with
> an *"Item title"* field hint, not *"Edit item"*), F13 (the Draft-message field hints *"What
> should the message say?"*, not *"Type a command…"*), and F15's greeting (*"Good morning,
> Siva"* for a person; the helper keeps *"YuviPep Admin"* whole rather than greeting the org).
> F15's empty-state string (*"You're all caught up."*, replacing the sales-only *"Nothing needs
> you. Go sell."*) is a resource swap in the same build, not individually tapped (Siva's
> Waiting-on-you was not empty). **See "How the copy pass was done" below the table.**

| ID | Where | Issue |
|---|---|---|
| ✅ **F7** | `MeetingReviewFragment.java` | "Add an item the AI missed" opened a dialog titled **"Edit item"** with a field hinting "Edit item" — `editInto()` is shared by both paths and hardcoded `R.string.review_edit_title`. |
| ✅ **F13** | `FollowUpQueueFragment.java:231` **+ `ProjectDetailFragment.java:360`** (under-count: 2 sites) | The "Draft message (AI)" instruction field used `R.string.assistant_input_hint` → hinted **"Type a command…"**. |
| ✅ **F14** | `strings.xml` + `MainActivity`/`PlaceholderFragment` | Live on screen: *"Editing the draft by instruction **arrives in Phase 3**…"*. Orphaned stale strings `assistant_placeholder`, `lead_projects_phase4`. Placeholder tabs exposed the roadmap ("…**of the build plan**") with **stale** phase numbers after the renumber, and "Team arrives in **later phase**" was missing an "a". |
| ✅ **F15** | Home empty state + digest | **"Nothing needs you. Go sell."** shown to every role; the seeded admin greeted **"YuviPep"** (digest used `name.split()[0]` on "YuviPep Admin"). |
| ✅ **F12** | Jarvis greeting | Claimed "I can **create leads**…" — per §6d there is no `create_lead` agent tool. |
| **F5** | Whisper | `language='bn'` detected for an all-English meeting, with ~40 chars of hallucinated Devanagari/Telugu before the speech starts (transcription runs over the silent lead-in). Everything after is near-verbatim. **Mitigating:** `confidence=0.589` → `low_confidence=1` fired correctly and the app warned the user. Fix candidates: pass `language="en"`/org locale, or trim leading silence. |

### How the copy pass was done (2026-07-23)

**One app build (`0.6.4-findings`), one tiny backend change, and two under-counts caught.**

- **F7** — `editInto()` served both "edit" and "add-missed"; the add path passes an `onSaved`
  callback, the edit path passes `null`, so `boolean adding = onSaved != null` picks the dialog
  title (new `review_add_title` = *"Add an item the AI missed"* vs `review_edit_title`) and the
  field hint is now a proper `review_item_title_hint` = *"Item title"* for both.
- **F13 — 2 sites, not 1.** `FollowUpQueueFragment` *and* `ProjectDetailFragment.draftMessage-
  InstructionDialog` both reused `assistant_input_hint`. Both now use a dedicated
  `message_draft_instruction_hint` = *"What should the message say?"*.
- **F14 — the roadmap leak fixed at the source.** `phase_placeholder_body` was
  *"%1$s arrives in %2$s of the build plan."* — it is now *"%1$s is coming in a future update.
  Your work stays safe on the server in the meantime."*, using only `%1$s`. That single edit
  removes **every** placeholder tab's phase number (which had gone stale after the roadmap
  renumber — the code still passed "Phase 6"/"Phase 7"), the "of the build plan" leak, and the
  "later phase" → missing-"a" grammar bug, all at once (the phase arg is now simply unused). The
  two orphaned strings `assistant_placeholder` and `lead_projects_phase4` (both unreferenced)
  were deleted; `message_edit_first_note` lost its "arrives in Phase 3" clause.
- **F15 — two halves.** App: `waiting_empty_title` is now the role-neutral *"You're all caught
  up."*. Backend: a new `assistant_engine._greeting_name` returns a friendly first name for a
  real person ("Siva Kumar" → "Siva") but keeps an org-derived label whole ("YuviPep Admin"
  stays "YuviPep Admin", never "YuviPep"), so the digest no longer greets the organisation.
- **F12** — `assistant_greeting` dropped "create leads" (no `create_lead` tool exists, §6d).

**Verified.** pytest **62/62** (a new `_greeting_name` unit test, proven to fail — old code
returned "YuviPep"), dryrun 43/43, gap 21/21, stakeholders --stub 21/21, and **on the Vivo**
(build `0.6.4-findings`): F12, F14, F7, F13 and the F15 greeting all confirmed by screenshot.
No schema change (no model touched).

---

## F16 — org_admin still has no route to any project, lead or task *(carried from Phase 4)*

Re-confirmed live. org_admin's five tabs are Home · Approvals · Jarvis · **Admin (Phase 8
placeholder)** · **Insights (Phase 8 placeholder)** — 3 usable of 5.

Worth stating more strongly than the handoff does: org_admin holds `manage_staff`,
`edit_pricing`, `manage_programs`, `manage_templates`, `manage_settings`, `view_audit` and
`erase_personal_data` — and **every one of those maps to a screen that does not exist yet**. In
the shipped app the most privileged role can only approve things and talk to Jarvis. Not a
regression; a scope reality worth keeping visible.

---

# Round 2 — the Jarvis chat review (2026-07-22, after the F4/F8/F9 fixes)

The user drove a short Jarvis conversation on the **Vidarbha Warehousing** lead with the
context chip **selected**, and asked four questions about it. Every answer was *technically*
correct, which is what makes these worth writing down: the prose was right while the scoping,
the ordering and the numbers underneath it were not.

**Three findings kept: F17, F19 and F22.** Three more were raised, reviewed with the user and
deliberately dropped as cosmetic — see the note at the end of this section. A fourth thing
spotted, the *"No **school** matching 'Vidarbha Warehouse' found"* wording, is the already-known
**F11**; so is the **"Get school details"** card title rendered in the transcript (that one is
the agent tool name — handoff §6c item 5 warns that renaming tools changes the LLM tool surface).

---

## F22 — Confirmed review-gate items and Planner tasks are the SAME work, stored twice ⚠ REGRESSION

> ### ✅ FIXED 2026-07-22 — see "How F22 was fixed" at the end of this section.

**Severity: highest. This is a regression introduced by the F9 fix on 2026-07-22.**

`app/api/meetings.py::confirm_review` turns each kept item into a real `open` ActionItem
(`plan_version_added = NULL`). The `plan_meeting` job then hands those same titles to the
Planner as `agreed_tasks`, and the Planner — correctly, by design — carries them into the plan
as tasks of their own (`plan_version_added = 1`). The same work now exists as two rows.

**Observed live** on Vidarbha Warehousing (8 open rows, 6 distinct pieces of work):

```
Provide safety compliance documentation and quote   | open | plan_version=None   ← review gate
Provide safety compliance documentation and quote   | open | plan_version=1      ← Planner
Start forklift safety certification program         | open | plan_version=None   ← review gate
Start forklift safety certification program         | open | plan_version=1      ← Planner
Develop forklift safety training curriculum         | open | plan_version=1
Schedule training sessions across three warehouses  | open | plan_version=1
Arrange forklift equipment for practical training   | open | plan_version=1
Conduct trainer certification (train-the-trainer)   | open | plan_version=1
```

**Why the existing tests and the live script all missed it.**
`planner_engine._drop_duplicates_of_confirmed` de-duplicates **within the Planner's own
output**, which is exactly what it was built and unit-tested for. It never compares the plan's
tasks against the already-open review-gate rows, because those are not in the list it is
handed. `verify_live_meeting_planner.py`'s "none of them came back twice" check reads
`project["tasks"]` only — project-less confirmed items are invisible to it. So 22/22 passed
with the duplication present.

**Why it did not show up on screen either.** The assistant *collapsed the identical titles in
its prose*, so the chat showed two clean lines while the DB held four rows. The UI looked
healthier than the data — the opposite of the "nothing invisible" rule.

**Blast radius:** every per-lead open-task count, My Tasks, the daily digest, the nudge ladder,
and any future "what's outstanding" answer. Two people could also work the same task twice.

**Fix direction (decide before coding):** either the confirmed items should be *adopted* by the
plan rather than re-created (link the existing rows into the plan version instead of emitting
new ones), or `confirm_review` should leave them `pending_review` and let plan activation open
them. The first keeps the human's row identity and its `due_date`; the second is simpler but
changes what "confirm" means. **This one should be fixed before F1.**

### How F22 was fixed (2026-07-22)

**Shape chosen: adoption** (option 1), picked with the user over "leave them pending_review"
for three reasons found by reading rather than assumed:

1. **The app already assumes it.** `TasksRepository.myTasks()` (`:113`) unions the
   project-sourced and `/action-items`-sourced lists **by id** — the app's model is "one piece
   of work = one row that may be visible through two endpoints". The duplication produced two
   ids, which is precisely why the app's own dedup could not collapse them. Adoption restores
   that invariant with **no app change at all**.
2. **Option 2 strands work on failure.** `plan_meeting` is explicitly "never fatal to the
   meeting" and can return `{"skipped": …}`; `process_meeting` can bail to
   `_hold_for_ai_failure`. Under option 2 every one of those outcomes leaves what a human
   confirmed stuck at `pending_review` with no screen able to release it.
3. It would also have made the shipped `0.6.2` toasts (`strings.xml:109-110`,
   *"%d task(s) are live"*) false.

**One change point covers both entry points.** All four planner paths (LLM/stub × first
meeting/merge) funnel into `create_plan_version` with `trigger_ref = meeting.id`. And the
review-gate-**OFF** path — which this write-up had missed, `pipelines.py:194-205` opens the
items then hands the same list to the Planner — produces rows that are structurally identical
(`meeting_id` set, `plan_version_added IS NULL`). One lookup catches both.

Before creating a row, `create_plan_version` now looks for an already-open row from this
meeting that no plan owns, matched by `_adoption_match` at the **same 0.7 threshold and the
same `_title_similarity`** the existing fence uses, so the two agree by construction. On a
match the existing row is updated in place: it keeps its **id**, the **human's wording** (they
may have edited it at the gate) and **their due date**; the plan contributes phase, skill,
priority, dependencies. Status is deliberately untouched — work a person already made live is
never retracted into `pending_review`. Each candidate can be claimed only once, so two plan
tasks can never collapse onto one row.

`activate_plan` needed a matching change: it selected only `PENDING_REVIEW` tasks for staffing,
so adopted (already-`open`) rows would never have been staffed. It now spans both statuses,
flips only the pending ones open, and — **because the user chose to have adopted tasks
re-staffed by skill like any plan task** — captures each task's previous assignee and notifies
anyone whose task moves away. Without that, four of a person's confirmed tasks could silently
leave their list, which §7 rule 3 forbids.

**Verification.** pytest **52/52** (up from 50), dryrun **43/43**, `verify_gap_endpoints`
**21/21**, `verify_generic_stakeholders --stub` **21/21**, `verify_live_meeting_planner`
**24/24** (22 + 2 new). **No schema change**, proven by diffing a copy of
`data/salesplatform.db` against a freshly-initialised schema: 55 tables both sides, zero
columns added or dropped in either direction.

**Both new tests were proven to fail without the fix** — the lesson of this very finding is
that a green suite proves only the scope you tested, so the fix was disabled and the
integration test re-run: it failed with
`AssertionError: the same work is stored twice for this lead: [('Send IBC proposal', 'Send IBC
proposal'), ('Share demo dates', 'Share demo dates')]`.

The new assertions are scoped the way the bug demanded — **query by `lead_id`, no other
filter** — in both `tests/test_meetings.py` and `verify_live_meeting_planner.py` (new section
`2b`). Live result on a real model run: **7 live rows for 7 pieces of work** where the same run
would previously have produced 11, with 4 of 4 confirmed to-dos adopted under their original
ids, and *"Loop in finance controller Priya Nair"* — undated at the gate — correctly picking up
the plan's date.

**Live DB cleaned** (backup `data/salesplatform.db.pre-f22cleanup-20260722`): 9 orphan rows
cancelled with an explanatory `result_note` (never deleted — Data Model §4.4), and 3 kept rows
took the orphan's cleaner title, which also cleared the `(due …)` pollution §8-pre3 recorded as
"harmless; clean or ignore". **Vidarbha 8 → 6** (exactly the 6 real pieces of work),
Kirloskar 16 → 11, Telaverge 17 → 15. The plan rows survive because the project's
dependencies, assignments and commitments are wired to them.

**Verified on the Vivo** (build `0.6.2-findings`, unchanged — F22 needed no app change), with a
real 1:26 recording through the phone mic on a lead created on the device itself, *Nashik
Logistics Park*:

- Whisper: `language=en`, confidence 0.76, 95 words, near-verbatim. **F5 did not reproduce.**
- 4 items extracted; *"by Monday"* resolved to the **column** as 2026-07-27 (F8 holding).
- Confirming showed the honest toast — *"4 task(s) are live. The Planner is building the plan
  from this meeting…"* — and the Planner returned `project_proposed`.
- **8 open rows for 8 distinct pieces of work.** Before the fix this same run would have
  produced **12** (4 review-gate + 8 plan). Every confirmed to-do appears exactly once.
- The human's dates survived adoption (both 27 Jul items), and the two to-dos that had **no**
  date at the gate picked one up from the plan (24 Jul, 5 Aug).
- `"Prepare Forklift Safety Program proposal"` correctly did **not** adopt `"Send full proposal
  with commercials"` (0.20 similarity) — prepare and send are different work.
- **The app-side proof:** those tasks now render **rich** on the project screen —
  `Sales · P2 · due 24 Jul`, `Sales · P1 · due 5 Aug` — with phase and priority badges,
  because they are project-sourced. Before, a confirmed item arrived thin via `/action-items`
  with those fields blank, *and* a second rich copy existed alongside it.

*(Incidental, not a defect: Whisper heard "Kavita Desai" as "Hades Covet", which propagated
into a task title. That is exactly what the human review gate exists to catch — it was offered
for editing and kept as-is only because this was an automated run.)*

---

## F17 — The context chip is a hint in a prompt, never a filter in the code

> ### ✅ FIXED 2026-07-23 — see "How F17 was fixed" at the end of this section.

**Observed:** with **About: Vidarbha Warehousing** selected, *"What are the action items?"*
returned **all 23 of Siva's open items across three leads** (Telaverge, Kirloskar, Vidarbha).
The user's own reading is exactly right: *with nothing selected that answer would have been
correct; with something selected it is wrong.*

The chip does reach the backend — `app/api/assistant.py:73` puts `lead_id` into `context`, and
`app/ai/agents/base.py:71-78` injects it into the **system prompt** as a line of JSON:

> `Current app context (already selected by the user): {"lead_id": "f3bb6afca1f14c17856df0ec0e2d84df"}`

…and that is the whole mechanism. `query_agent._list_action_items` (`:131`) defaults to
`owner="me", status="open"` with **no lead filter**, and nothing in the code binds the selected
lead to the query. A capable model might act on the hint; the free model does not.

**Made worse by the shape of the hint:** it is an opaque UUID, while the tool's parameter is
described as *"filter by school name"*. The model has no way to know `f3bb6afc…` **is**
Vidarbha without a second lookup. (`resolve_lead` would in fact accept the raw id —
`resolvers.py:26` — but nothing tells the model that.)

This is the same class of defect as **F10**: the app offers an affordance the backend does not
actually honour.

### How F17 was fixed (2026-07-23)

**Shape chosen with the user: bind the filter in code AND make the hint usable by the model**
— the hybrid, over "prompt only". The whole job's recurring lesson is *a prompt instruction is
not a fence* (F4, F9's duplicates, F23); an affordance that must hold cannot rest on the FAST
model choosing to honour a hint. So the guarantee lives in code, and the readable hint is the
free extra that keeps the model's *prose* accurate too.

**Two halves, both landed:**

1. **Deterministic binding** (`query_agent._effective_client`). The lead-scopable query tools
   — `list_action_items`, `search_past_notes`, `get_client_details` — now default their client
   filter to the selected `lead_id` when the model names no client of its own. An explicit
   client the model passes always wins, and the sentinel **`client="all"`** is the deliberate
   way to broaden back to every client (so the default never becomes a cage). `resolve_lead`
   already accepts a raw id (`resolvers.py:26`), so the opaque UUID from the chip is passed
   straight through — no second lookup needed. This is what actually makes "what are the action
   items?" answer *for the selected lead*.
2. **The hint made usable** (`base._enrich_context` + `_system`). The selected `lead_id` is
   resolved to its **name** once, up front, and the system-prompt context line changed from an
   opaque `{"lead_id": "f3bb…"}` blob to *"The user is currently viewing the client 'Vidarbha
   Warehousing'. If they ask … without naming a different client, they mean this one — the
   tools already default to it."* So even when the model narrates the result, it names the
   right client. Enrichment is best-effort and never fatal; a lookup failure just leaves the
   old JSON hint and the code-level scoping still holds.

**Under-count check, as the job demands.** The finding named only `query_agent`. The
**conversation agent** (`_list_items`) is a *second* place the model sees tasks (for "close
task 1"); it was left listing the caller's items unscoped, which is correct for its mutate-by-
number purpose — but its item view had the same F19 blindness, so `priority` was added there
too. The deterministic *scoping* stays on the three query tools agreed with the user; widening
it to the mutation path would have surprised "close task 3" flows.

**Contract:** fully back-compatible. The `client` param and the two tool descriptions gained
the "defaults to the viewed client / pass 'all'" wording; `get_client_details.client` dropped
from `required` (a viewed client supplies it). An older app that sends **no** `lead_id`
behaves exactly as before — no chip, no scoping. **No app change and no schema change.**

**Verified.** Three new tests in `tests/test_assistant.py` (scoping, the 'all'/explicit
override, and priority), each **watched failing with the fix disabled** — the scoping test
returned every client's items, the override test errored on `client="all"`, the priority test
raised `KeyError: 'priority'`. New live script `scripts/verify_live_assistant_context.py`
proves it **against the real model, 6/6**: no chip → both clients; chip on Aurora → only
Aurora in the *tool result itself*, not just the prose; `all` broadens back; and the P1 (due
last) is named most important. **On the Vivo** (Siva, build `0.6.3-findings`, unchanged — F17
needs no app change): with the *About: Green Valley School* chip up, "what are the action
items?" returned only Green Valley's two tasks — the Delhi Public School task, open and owned
by Siva, was correctly absent.

---

## F19 — The query agent cannot see `priority`, so "priorities" silently means "soonest"

> ### ✅ FIXED 2026-07-23 — see the note at the end of this section.

**Observed:** *"Tell me the priorities"* returned five tasks ordered by due date. The real P1s
are a different set (*Send revised schedule to client*, *Develop safety compliance pack*,
*Schedule and deliver live demonstration*, …).

`query_agent._item_dict` (`:22-31`) returns `id, title, status, owner, school, due_date,
description` — **`priority` is not in it**. The model literally cannot see P1/P2, so it
substituted "earliest" for "most important" and presented it as an answer about priorities.

Not a hallucination — a missing field. The app has shown P1 badges since Phase 4; the assistant
is blind to the same data.

### How F19 was fixed (2026-07-23)

One field: `_item_dict` now returns `"priority": item.priority` (`ActionItem.priority` is
`P1|P2|P3`, default `P2`). The same field was added to the **conversation agent's**
`_list_items` — the under-count check for F17 found it was the other place the model reads
tasks, and it was equally blind. **On the Vivo**, with two Green Valley tasks whose priority
and due date *disagree* on purpose (P1 due 22 Aug, P3 due 25 Jul), "which is my single most
important task?" named the **P1 security review** — the one due *last* — proving the model now
reads priority rather than substituting "soonest due". Covered by the priority assertion in
`tests/test_assistant.py` (proven to fail with `KeyError: 'priority'` when the field is
dropped) and by `verify_live_assistant_context.py` (6/6, real model).

---

---

# Round 3 — found while switching models (2026-07-22)

Both of these were found by work that was not looking for them: F23 by a probe written because
the model bake-off did not cover the STRONG tier at all, F24 by reading the live DB for F22's
reproduction case. Neither is a regression.

## F23 — The proposal rewrite applies a discount it is explicitly forbidden to apply

> ### ✅ FIXED 2026-07-23 — see "How F23 was fixed" at the end of this section.

`app/ai/agents/proposal_agent.py:302-332` (`rewrite_narrative`, `TIER_STRONG`).

The prompt says, in its own words:

> `- Do NOT change, add or remove any prices, quantities or totals.`

Given the instruction *"The client asked for a 10% discount — apply it to every line and update
the grand total"*, **every model tested applied it**, on a proposal whose stored line items were
1450/head, 9500/module, 12000/pack, total 243000:

| model | produced |
|---|---|
| `google/gemini-2.5-flash` | 1305 · 8550 · 10800 · **218700** |
| `openai/gpt-5.4-nano` | 1305 · 8550 · 10800 · **208700** ← also arithmetically wrong |
| `nvidia/nemotron-3-super:free` (the model in use until today) | 1305 · 8550 · 10800 · **218700** |

**This is not a model-selection issue** — the behaviour is identical across all three, including
the one the project has been running on since Phase 3.

**Blast radius is bounded, and by code rather than luck.**
`proposal_service.apply_narrative_edit` (`:373-377`) forcibly re-inserts the computed commercial
block, *"so document numbers cannot drift from the stored ones"* — the **table is safe**. But the
protection stops at the pricing markers: every model above dropped the table and put the
discounted figures in the **prose**, which survives re-insertion. The tool then returns
`{"updated": True, "note": "Wording updated; commercial table unchanged."}` — true of the table,
false of the document. A client would receive a proposal whose narrative says 1305 per head and
whose table says 1450.

**Fix direction:** a deterministic post-check, the same shape as F22's and F9's fences — after
`rewrite_narrative`, scan the narrative for currency-shaped numbers absent from
`proposal.line_items` and reject or strip them, and make the returned note honest. Same lesson,
third time: **a prompt instruction is not a fence.**

Reproduction: `strong_probe.py` in the 2026-07-22 session scratchpad (benign rewrite passes
4/4 on all three models; the adversarial one is the failure).

### How F23 was fixed (2026-07-23)

**A deterministic fence, the same shape as F9's and F22's** — the third confirmed instance of
*a prompt instruction is not a fence* this job. `proposal_service.narrative_price_drift` scans
the rewritten PROSE (the machine-replaced pricing block is excluded — its numbers are about to
be overwritten anyway) for money-shaped numbers that are **not** in the proposal's locked
commercials, and `apply_narrative_edit` now **rejects** the rewrite when it finds any —
validating *before* it mutates, so a rejected edit leaves the document untouched. The tool's
returned note (*"commercial table unchanged"*) is now guaranteed true rather than true-of-the-
table-only.

**How a "money-shaped stray" is told from an innocent number** (to avoid false positives on
years, headcounts and quantities): a number counts only when it is ≥ 100, is **not** already
one of the proposal's unit prices / quantities / line totals / grand total, is not a bare year
(1900–2100), **and** sits next to a currency marker (`Rs ₹ INR USD EUR $`) or a price word
(`per`, `total`, `discount`, `rate`, `fee`, `invest…`, …). So *"Rs 1,305 per head"*, *"1305 per
head"* and *"revised total of 218,700"* are caught, while *"in 2026 we will train 300
students"* is not.

**Verified.** Unit test in `tests/test_proposals.py` covers **both** directions — a benign
rewrite that echoes the real numbers passes; a comma-formatted discount, a comma-less discount,
and a year+headcount false-positive probe are all handled — and it was **watched failing with
the fence disabled** (`narrative_price_drift` forced to `[]` → the discount sailed through).
New live script `scripts/verify_live_proposal_guard.py` proves it end-to-end **against the real
STRONG model, 3/3**: "make it warmer" left the prose clean and applied; "apply a 10% discount to
every line and the total" made the live model emit `1,305 / 8,550 / 10,800 / 218,700` in the
prose — the fence caught all four, rejected the edit, and the stored total stayed **243,000**
with unit price **1,450**. pytest **63/63**, dryrun 43/43, gap 21/21, stakeholders --stub 21/21.
**No schema change.**

**Not device-tapped** (honest per §7): the demo org has **no program / pricing / template**
seeded, so no proposal can be created in the app without standing all three up — out of
proportion to the risk, since the fence is deterministic and was proven catching the real
model's output through the exact `rewrite_narrative → apply_narrative_edit` path the proposal
agent uses. The app already renders a failed tool's error verbatim (Phase 3), so the rejection
surfaces to the user as an honest chat error. *(Same posture as F2's card-scan half.)*

**One wart, left as-is:** on the combined `edit_proposal` path (structured line-ops + a
narrative rewrite in one instruction), the line-ops are applied before the narrative is
validated, so a rejected narrative can leave a **legitimate, explicitly-requested** price
change applied while the wording fails. The price-integrity invariant still holds (no
*unauthorised* number reaches the document); only the atomicity of a two-part edit is imperfect,
and the error tells the user the wording did not apply.

## F27 — An AI-escalated client question has nowhere to be answered *(planning gap)*

Found 2026-07-22 by the user asking a simple question about F26: *"from where will the human
answer that escalation?"* Tracing it turned up a hole in the plan, not the code.

**What escalation actually produces** (`inbound_engine.py:1276-1302`): a P2 `ActionItem`
assigned to the lead/project owner — *"Answer {contact}'s question: …"*, the full question in
the description, due in 2 days — plus a notification, and `msg.status = needs_human`. The task
carries **no link** to the inbound message or thread; the question text is simply copied.

**Where it surfaces:** Home → "Waiting on you" → a triage card → `TriageListFragment`, because
`GET /inbound/triage` returns `needs_human` as well as `triage`. So it is visible — good, and
unlike F2 nothing is silently unreachable.

**But there is no reply route.** That screen offers exactly one action, **"Handled"**, which
calls `POST /inbound/{id}/resolve` — marking the message processed and optionally attaching a
note. **It sends nothing.** The tab where a person would expect to reply is a permanent
placeholder:

```java
placeholder(R.string.tab_inbox, "later phase", R.drawable.ic_tab_inbox)
```

…for sales_agent, and **sales_lead has no Inbox tab at all**. So in practice the person must
either ask Jarvis to draft a reply (which works — the email agent drafts, Approvals sends) or
leave the product and use their own mail client. Nothing on the task or the triage card says so.

**The planning gap this exposed.** `TriageListFragment`'s own comment said the full Inbox
*"arrives with the full Inbox in Phase 4"* — but Phase 4 was **Projects & work**; the Inbox was
never in its scope. It is specified in `02_ARCHITECTURE.md`, `03_SCREENS_NAVIGATION.md §9` and
`05_ROLE_EXPERIENCES.md` (where it is one of the sales agent's **five bottom-bar tabs**), and
Phase 4's acceptance criteria even *reference* the message center — yet **no phase owned it**.
It had fallen between the cracks. (A previous session's memory had guessed "P6"; P6 was money
& ops and did not list it either.)

**Resolved as a plan, not a patch (2026-07-22, user's call):** the Inbox is now
**Phase 6 — Inbox & messages** in `10_ROADMAP_MILESTONES.md`, with Money & ops → 7, Admin &
platform → 8, Push/polish/release → 9. The new phase records that most of the backend already
exists (`GET /messages`, `GET /messages/{id}` with `delivery_log[]`, `/inbound/triage`,
`/inbound/{id}/resolve`, `/inbound/ingest`), names the **two real backend gaps** found while
writing it — `resolve` supports neither "set intent" nor `project_id`, both listed in §9 — and
takes closing this F27 loop as an acceptance criterion. `TriageListFragment`'s misleading
comment is corrected.

**Mild honesty wart, left as-is:** "Handled" marks a question processed whether or not anyone
answered it. Milder than F2 because a human is asserting it rather than the AI, but the button
claims something it cannot verify.

### How it was closed — 2026-07-29, Phase 6 built and device-verified

**The loop now runs entirely in the app,** proven on the Vivo against the live backend with a
real escalation: a client asked about the refund policy, the AI refused to guess (*"No data
found to answer — the AI never guesses"*), and from the triage card **Reply** opened the
assistant scoped to that client with a drafted command; the email agent wrote it, the inline
approval bar sent it, and its delivery trace — drafted → queued → sent, with the `.eml` —
is in the message centre. **No new send endpoint was needed**, exactly as the plan predicted.

**The two named backend gaps were closed, and a third was found while building.**
`resolve` gained `intent` (422-validated) and `project_id`; and `GET /inbound/triage` had
never returned the AI's `intent` **or** `matched_lead_id` at all — so "set intent" would have
been a blind write over an invisible guess, and the reply route could not have scoped itself
to the client the backend had already matched. Rows now carry `intent`, `change_type`,
`matched_lead_id`, `matched_project_id`, `created_at`. `GET /messages` gained
`sender_user_id`. All additive; no schema change; backend re-frozen afterwards.

**The placeholder is gone.** `openEntity("inbound_message", …)` used to fall through to the
honest *"opens fully in a later phase"* toast — **that toast was this finding's dead end in
the app** — and now opens the Inbox. The sales agent's fifth tab is the real screen; every
other role reaches it from the Home "needs a human" card or a notification. `feature/triage/`
and its misleading comment are deleted.

**What is still true from the paragraph above:** "Mark handled" still asserts something it
cannot verify — but it is no longer the *only* action, which was the actual complaint.

**Not fixed, deliberately** (see doc 10's Phase 6 entry): `resolve` still accepts a `note` it
never stores, so no screen offers a note box; there is still no `lead_id` on `resolve`; and
`attachments` are still not serialised with a message.

## F26 — The new FAST model escalates inbound questions the old one answered ⚠ from the model switch

Found while re-running the wider live suite after the F11 sweep — **not** caused by that sweep
(proven by reverting the one inbound-path string and re-running: still 2/3).

`scripts/verify_live_answers.py`, which was **not** part of the model bake-off, is stable and
reproducible in both directions:

| FAST model | result | runs |
|---|---|---|
| `nvidia/nemotron-3-nano-omni:free` (previous) | **3/3** | 3 |
| `openai/gpt-5.4-nano` (now configured) | **2/3** | 3 |

**The failing check:** a parent's paraphrased WhatsApp question — *"will the children get to
write in a real industry language, or is everything visual drag-and-drop?"* — against a stored
syllabus fact mentioning Kotlin. The intent is classified correctly as `question` by both
models; they differ at `planning.select_answer_facts`, which asks the model whether the
candidate facts *suffice* to answer. The free model says yes and the platform answers from its
own data; `gpt-5.4-nano` says no, so `inbound_engine` opens a P2 task for a named human and
sets `needs_human_reason = "No data found to answer — the AI never guesses"`.

**This is the safe direction, not a wrong answer.** The deterministic fence behaved exactly as
designed — answers compose only from facts the model picked, and insufficient goes to a human.
The cost is that fewer client questions get auto-answered, which is a headline capability.

**The real lesson is about the bake-off, not the model:** three scripts were benchmarked
because those were the three named, and this behaviour lives in a fourth. A model swap changes
*every* model-mediated decision in the system, and only the paths with a live script covering
them were measured.

**Decision needed** (deliberately not taken unilaterally — the switch is already applied and
everything else improved): keep `gpt-5.4-nano` and accept more human escalation; try
`gemini-2.5-flash` on FAST, which also swept the three benchmark scripts clean; or split the
tiers so `select_answer_facts` runs on the stronger model.

## F25 — "The AI has matched people to tasks" never matches anyone to anything

> ### ✅ FIXED 2026-07-23 — see "How F25 was fixed" at the end of this section.

Found by the user, opening the 14 assignment proposals produced by the F22 device test: **every
single one** said *"no skill match"*.

`app/engines/assignment_engine.py` documents three candidate tiers:

```
a) project members whose user_skills match the required skill
b) org users in the right department with the skill
c) the phase owner — flagged "no skill match"
```

**`user_skills` has ZERO rows for all 9 users.** Tiers (a) and (b) both require a skill match,
so both return empty every time and everything falls to tier (c), which is *designed* to be
flagged "no skill match". The engine is behaving exactly as specified — the data it needs was
never created. `scripts/seed_demo.py` (which seeds this deployment) creates **no** `UserSkill`
rows at all; only `scripts/seed_workflows.py` does, and it was not run for this org.

Not new and not a regression — the same text is on tasks from `2026-07-21 18:02`, during the
original simulation:

```
Siva: no skill match, 0/8 open tasks — skill gap: proposal_preparation;
      assigned to phase lead by default
```

**Seeding skills would NOT be enough, and this is the real defect.** The LLM planner invents a
free-form skill vocabulary per plan — **29 distinct skills across ~4 projects, nearly all used
exactly once**: `forklift_training`, `venue_coordination`, `safety_compliance_documentation`,
`session_scheduling`, `trainer_certification`, `quote_preparation`, `customization`… while
`seed_workflows.py` seeds a small fixed set. A skill string invented fresh by a model will
essentially never string-match a stored one. This is the generic-LLM-planner pivot (see the
`generic-llm-planner` memory) colliding with a fixed-vocabulary matcher.

**Compounding effect:** because one person is the phase-lead fallback for everything, work
piles onto them — Siva was at **21 open tasks against a cap of 8**, so the reasons also carry
"capacity exceeded".

**Fix direction, two parts:** (1) seed skills for the demo org; (2) make the match tolerant of
model-invented vocabulary — the better direction being to hand the planner the org's **actual**
skill list and have it choose from that, so the model's output is constrained by real data
rather than matched against it after the fact. Until then the headline promise on the
assignment screen — *"The AI has matched people to tasks — review the reasons and confirm"* —
is not true.

### How F25 was fixed (2026-07-23)

**Shape chosen with the user: constrain the planner at the source + seed a real taxonomy** —
over fuzzy-matching invented vocabulary after the fact (which the finding calls the worse
direction) and over seeding alone (which leaves the planner free to invent). Three parts, and
the infrastructure for the middle one **already existed** — it just had no data to draw on and
too soft an instruction:

1. **Seed a taxonomy** (`seed_demo.py::seed_user_skills`, idempotent + reusable). Eight skills
   spread across the demo org's people — `proposal_preparation`, `client_relationship`,
   `content_development`, `curriculum_design`, `logistics_coordination`, `training_delivery`,
   `quality_assurance`, and `general` (the neutral skill **everyone** holds, so a task with no
   specialism still finds a real candidate rather than the phase-lead fallback). 24 rows.
2. **Constrain the planner** (`planning.py`). `_org_context` already fed `org_skill_names(...)`
   into the plan prompt, but the wording said *"invent a new snake_case skill name ONLY when
   nothing here fits"* — with an **empty** taxonomy it always invented. Now: *"Set required_skill
   to ONE of these EXACT names, and 'general' when no specialism applies. Do NOT invent…"*
3. **A deterministic fence** (`validate_task_specs`), because a prompt is not a fence (the job's
   recurring lesson — F4/F9/F22/F23, now F25): if the model still emits a skill outside the
   taxonomy, it is recorded as a gap **and coerced onto `general`** (which has holders), never
   left on a phantom skill. When no taxonomy exists at all, the model's word is kept (bootstrap).

**No change to the assignment engine** — it always matched correctly *when skills existed*; the
defect was that they never did and the planner's vocabulary never lined up. Covered by
`tests/test_assignment_skills.py`: the coercion both directions (watched failing disabled —
`forklift_training` stayed instead of becoming `general`), the bootstrap case, and a
`build_candidates` test proving a seeded member yields an `expert/good skill match`, not the
fallback. pytest **67/67**, dryrun 43/43, gap 21/21, stakeholders --stub 21/21. **No schema
change** (`user_skills` already existed).

**Live proof** (`scripts/verify_live_planner_skills.py`, **3/3**): a warehouse forklift-safety
transcript — the exact kind that used to yield `forklift_training`, `venue_coordination` — now
maps every task onto the real taxonomy (`proposal_preparation`, `client_relationship`,
`curriculum_design`, `logistics_coordination`) with **zero skill gaps**.

**On the Vivo** (build unchanged — F25 is backend + seed only). The live demo DB was back-filled
with the 24 skill rows; a fresh typed-notes plan on *Pune Safety Institute* produced a "Confirm
assignments" screen reading **"Siva: expert skill match"** (proposal_preparation) and **"Baski:
expert skill match"** (curriculum_design) — where this finding recorded that **every single
proposal** said "no skill match". The headline promise is now true.

*One soft edge, not the defect:* one task ("Plan logistics") came back with a **blank**
required_skill from the model, so it still fell to the phase lead ("no skill match"). A blank is
not an invented skill, so the coercion (which only fires on a non-empty out-of-taxonomy name)
leaves it None. Tightening the prompt to forbid blanks is a possible follow-up; 2 of 3 real
matches vs 0 of 3 before is the fix landing.

## F24 — Every recording of the same lead re-opens the same to-dos

> ### ✅ FIXED 2026-07-23 — see "How F24 was fixed" at the end of this section.

Found in the live DB while assembling F22's reproduction. Telaverge Solutions carried, as
separate `open` rows with `plan_version_added IS NULL`:

```
Send proposal with commercials by Friday          ← meeting 1's review gate
Send the IBC proposal with commercials by Friday  ← meeting 2's review gate
Arrange live demonstration for leadership         ← meeting 1
Arrange live demonstration for leadership team    ← meeting 2
```

Each recording runs extraction over its own transcript and opens whatever the human confirms.
Nothing reconciles a to-do against what the *previous* meeting on the same lead already opened,
so a commitment restated across two meetings ("I'll send the proposal by Friday", said again
next week) becomes two tasks. **F22's adoption does not touch this** — it matches a plan task
to a row from *the same meeting*, deliberately, and these pairs are review-gate row vs
review-gate row across different meetings.

Left in the live DB as the reproduction case (the F22 cleanup deliberately did not remove them).

**Fix direction:** at `confirm_review`, before opening a kept item, check it against the lead's
existing live rows the way `_adoption_match` checks against the meeting's — and offer the human
"this looks like the task you already have from 14 Jul; update it instead of adding one?"
rather than deciding silently. Unlike F22 this is genuinely ambiguous — a client can promise
the same thing twice and mean two deliveries — so it should surface, not auto-merge.

### How F24 was fixed (2026-07-23)

**Shape chosen with the user: warn at the review gate** — over auto-merge (which would collapse
two genuine separate deliveries — the ambiguity the finding names) and over a backend-only flag
(which still leaves the twin). The review gate **already** lets the human keep / drop / edit
every extracted item, so the fix is a *warning* on the item they are already deciding on, not a
new dialog.

**Backend (no schema change — a computed field on the GET only).**
`GET /meetings/{id}/review` now annotates each extracted item with `possible_duplicate_of`
`{id, title, at}` — the lead's most-similar **open** task from a *different* meeting (or one
added by hand), or `null`. Detection reuses the **same `_title_similarity` and 0.7 threshold**
as the F22 adoption fence and the F9 duplicate fence (`meetings.py::_duplicate_hints`), so a
warning here and an actual merge elsewhere agree by construction. It **decides nothing** — the
human drops the twin with the existing switch, or keeps it if it is a real second delivery.

**App (`0.6.5-findings`).** The review card shows, under the description, a tertiary-coloured
line: *"⚠ Looks like "Send proposal and fee structure" (23 Jul) — drop if it's the same"* when
`possible_duplicate_of` is present, and nothing when it is `null`. The warning dims with the
keep switch like the rest of the card.

**Verified.** New `tests/test_meetings.py::test_review_flags_a_possible_duplicate_of_an_existing_
task` covers **both** directions (the restated commitment is flagged against the pre-existing
task; genuinely-new work is not) and was **watched failing with the fix disabled**
(`_duplicate_hints` forced to `{}` → the field came back `null`). pytest **64/64**, dryrun
43/43, gap 21/21, stakeholders --stub 21/21. Detection is deterministic (pure token overlap, no
model call), so no live script applies. **On the Vivo** (build `0.6.5-findings`): a matching
open task was created on Green Valley, and the review screen for its pending meeting showed the
⚠ line on *"Send proposal and fee structure"* and **nothing** on *"Arrange teacher
demonstration"* — then the synthetic task was cancelled with a note (never deleted).

**Contract:** additive (`possible_duplicate_of` is a new optional field; older apps ignore it).

---

*Also raised in the round-2 review and **deliberately dropped after discussion with the user (2026-07-22)** as cosmetic, so nobody re-opens them: the `resolve_lead` substring match failing on a near-miss name ("Vidarbha Warehouse" vs "Vidarbha Warehousing" — visible, honest, and the model recovered unaided); `get_school_details`'s all-owners count sitting unlabelled next to `list_action_items`' owner=me count; and the generic `Pretty` renderer printing raw field names such as `Important: false` (the lead's ⭐ star flag, unrelated to task priority). The numbering therefore skips F18, F20 and F21.*

---

# Round 4 — found reviewing Phase 6 (2026-07-29)

> One finding, and it is **the only OPEN item in this file**. It was found by the
> **user**, not by a test run — reviewing the Phase 6 report and asking why a
> salesperson should have to phrase a command precisely. No code has been written for
> it; the fixes are scheduled as Phase 7 §7.0 and need a backend unfreeze.

## F28 — The assistant cannot resolve a person from a natural phrase, and fails instead of asking

> ### ✅ FIXED 2026-08-03 — see "How F28 was fixed" at the end of this section.

**Status when written: OPEN, documented 2026-07-29, no code written.** Scheduled as the
opening work of Phase 7 — see `10_ROADMAP_MILESTONES.md`. The backend was unfrozen for it
on 2026-08-03 and re-frozen after.

**Found by the user**, reviewing the Phase 6 report. Phase 6's reply route only worked
after its pre-filled command was rewritten as labelled lines:

```
Draft an email replying to this client question.
Recipient: EKAGHNI MUKHERJEE
Client: Orchid International School
Their question: …
```

The user's objection is correct and goes deeper than the Phase 6 write-up admitted:

> *"In real life whoever will use this app won't have that much time to label everything.
> He may simply write 'Draft an email to EKAGHNI MUKHERJEE at Orchid International School…'
> and the AI should be able to understand the intent properly and do the needful. The
> question asked to the AI may be a bit ambiguous but it's the role of the AI to resolve
> it — if the AI is confused it can ask a further question: 'ok so my understanding is
> this… Am I correct? Should I proceed?'"*

**The Phase 6 fix was a workaround, not a fix.** It made *one app-generated command* work.
It did nothing for a human typing into the Jarvis tab, who hits exactly the same wall.
Handoff §6h originally framed this as prompt hygiene; that framing was too kind to the
code and has been corrected to point here.

### Root cause — `app/ai/agents/resolvers.py:142`

```python
if hint in c.name.lower() or hint in (c.title or "").lower() or hint == (c.email or "").lower():
```

The name test is **one-directional**: it only asks whether the hint sits *inside* the
stored name.

| what the user types | stored contact | result |
|---|---|---|
| `Nair` | `Mrs. Nair` | ✅ hint is inside the name |
| `EKAGHNI MUKHERJEE at Orchid International School` | `EKAGHNI MUKHERJEE` | ❌ **the hint is longer than the name** — the reverse is never tried |
| `mekaghni@telaverge.com` (inside a longer phrase) | email on file | ❌ email is compared with `==`, so it must be the whole hint |

Observed live on the device: `No contact matching 'EKAGHNI MUKHERJEE at Orchid
International School' at Orchid International School. Known: EKAGHNI MUKHERJEE …` — the
answer is sitting in its own error message. The same one-directional shape is in
`resolve_lead` (:34), `resolve_user` (:65), `resolve_program` (:100), `resolve_team` (:122).

### Second cause — routing (`app/ai/orchestrator.py:46`)

The router's email line reads *"introductory messages and custom/one-off emails NOT about
a proposal"*. A phrase like *"write a reply about our refund policy"* smells commercial, so
the **proposal agent** took it and answered in the chat — beautifully worded, and it created
nothing. **Prose in a chat bubble is not a reply the client ever receives.** There is no
routing line for *replying to an inbound client message*.

### What already works, and must not be rebuilt

**The "ask me a question" behaviour partly exists.** `base.py:228` returns tool errors to
the model rather than crashing, and on the device the model spontaneously did the right
thing:

> *"I can draft it, but the email tool can't find the exact recipient name you used. It
> does recognize **EKAGHNI MUKHERJEE**. Confirm: should I send the reply to them?"*

`resolve_lead`/`resolve_user`/`resolve_program` already raise *"Several match 'X': A, B.
Which one?"* deliberately — the module docstring says *"Ambiguity is reported back to the
model, never guessed."* The intent is right. Two things spoil it:

1. It costs a **failed tool call** first, which the app paints as a red **"failed"** badge —
   so a sensible clarifying question looks like a crash.
2. It only triggers *after* a failure, not when the AI is merely unsure.

### The five fixes (agreed with the user 2026-07-29; none written yet)

1. **Bidirectional, token-aware resolution** *(`resolvers.py` — this is the real fix)*.
   Match in this order: exact id → exact email/phone → **email contained in the hint** →
   hint inside name → **name inside hint** → significant-token overlap. Apply to all five
   resolvers, not just contacts.
2. **Strip the client's own words from the contact hint first.** `resolve_contact` already
   receives the `Lead`, so removing the lead's name tokens kills *"NAME at CLIENT"*
   generically, for every phrasing, without pattern-matching the word "at".
3. **"Unsure" becomes a question, not a failure.** A distinct outcome the agent loop marks
   as *needs confirmation* (not *error*), carrying the candidates, so the agent states its
   understanding and asks, and the app renders a question card instead of a red failure.
   **Resolution policy chosen by the user: ASK, NEVER GUESS.** One clear match → proceed
   *and name the recipient out loud*. Several or none → ask before drafting. Never silently
   pick a recipient: sending a client email to the wrong person is worse than one more tap.
4. **A routing line for replies to inbound messages** (`orchestrator.py`).
5. **Tool descriptions** should say "the person's name only, not the client".
   **A hint, never the fence** — this project has learned three separate times (F9, F4,
   F23) that a prompt instruction is not a fence. Fixes 1–3 are the fence.

**Plus, in the app:** revert Phase 6's labelled-line prompt
(`strings.xml/triage_reply_prompt`) to natural phrasing. That reverted prompt is the
acceptance test — if it works, the resolver is genuinely fixed rather than bypassed.

### The general rule this establishes (applies to the whole Jarvis tab, not just the Inbox)

> **A sales lead or agent may type a very short or ambiguous command about anything. It is
> the AI's job to handle it — either resolve it and proceed, or state its understanding and
> ask one clarifying question. Failing with a lookup error is not an acceptable third
> option.**

Recorded as a working principle in handoff §7 and in `04_JARVIS_ASSISTANT.md`.

### Scope note for whoever picks this up

Fixes 1, 2, 4, 5 are small, deterministic and testable in both directions (assert that
`"NAME at CLIENT"` resolves **and** that a genuinely ambiguous hint still asks). Fix 3 is
the real design change — it touches the agent loop and the app's result rendering, and it
is where a mistake could email the wrong person, so it needs the ask-never-guess guardrail
above and device testing, not unit tests alone.

### How F28 was fixed (2026-08-03)

All five fixes, plus the app change. Backend unfrozen for this one named job and re-frozen
after. **No schema change** (no model file touched), proven by diffing a copy of
`data/salesplatform.db` against a freshly-initialised schema: 55 tables both sides, zero
columns added or dropped.

**Fix 1 — one resolution ladder, shared by all five resolvers.** `resolvers.py` now tries
everything a person might type, strongest first, and **the first stage that matches
anything decides the outcome**:

> exact id → exact name/code → exact email/phone → email/phone found **inside** the hint →
> hint inside the stored name *(what the file always did, kept verbatim)* → **stored name
> inside the hint** → significant-token overlap

Ordering is the design, not decoration: an exact hit is never diluted by a fuzzy one, and
a loose stage only runs when nothing stronger worked. Two details worth keeping:

- `name_in_hint` is **word-bounded**, not substring — a plain `in` test finds the stored
  name "Ann" inside the word "announcement", and this is the stage that reads a name out
  of a whole typed sentence.
- The loosest stage (`token_overlap`) considers **names only**, not job titles. A title
  like "Operations Head" overlapping a hint about operations would over-reach.

**Fix 2 — the client's words are a fallback STAGE, not a pre-step.** This is a deliberate
deviation from the original write-up ("strip the client's own words from the contact hint
**first**"). Stripping first breaks a contact called *"Mrs. Nair"* at a client called
*"Nair Industries"*: the person's name disappears with the client's, and a lookup that
works today becomes a question. So the raw hint always gets the full ladder first, and the
stripped hint runs only when the raw one found **nothing**, or when it found **several and
the client's own words are what made it ambiguous** (e.g. "Ravi at Green Valley School"
also half-matching a contact called "Valley Team"). In the ambiguous case it may only
**narrow** — the stripped hint can pick one *of* the existing candidates, never redirect to
somebody else entirely.

**Fix 3 — unsure is a question, not a failure.** New
`NeedsConfirmationError(ValidationFailedError)` carrying `candidates`. Subclassing is the
point: it stays a 422 and every existing `except ValidationFailedError` keeps catching it.
`base.py::_execute_tool` gained one branch that hands the model
`{needs_confirmation, question, candidates, instruction}` instead of `{error}`, and records
the action as:

```json
{"tool": "...", "ok": false, "outcome": "needs_confirmation",
 "error": "<the question>", "question": "<the question>", "candidates": ["A", "B"]}
```

**`ok` stays false and `error` still carries the text on purpose.** The tool genuinely did
not act, and an app built before this renders exactly what it rendered before rather than a
success that never happened. A newer app reads `outcome` and draws a question card. Both
sides are additive.

`resolve_contact` also stopped picking `contacts[0]` when several contacts exist and none
is marked primary — that was a silent guess at the recipient of a client email. A
**designated primary is still honoured**, because that is a decision a human made rather
than a guess.

**Fix 4** — the router's email line now covers replies to something a client sent, and says
that answering in chat prose is not enough. **Fix 5** — the `contact` / `to_contact`
parameters say "the person's name or job title ONLY, never with the client's name
attached". Both are hints; fixes 1–3 are the fence.

**A fake success caught by the first live run.** With the ambiguity fixed, the model opened
its reply with *"I drafted the email to Nair at Kirloskar Industries — ready for your
one-tap approval"* and only **then** asked which Nair. Nothing had been drafted. The tool
result and the system prompt now say so explicitly, and `verify_live_resolution.py` asserts
the reply does not claim a draft that does not exist. The **app's** question card states it
too — *"Nothing has been drafted or sent yet"* — so the card is true regardless of what the
prose does.

**The test lesson repeated itself, and was caught this time.** The first version of the new
suite passed with `name_in_hint` — *the F28 case itself* — deleted from the ladder, because
the other new stages rescued every fixture. That is §6g's "a green suite proves the scope
you tested" in miniature. The tests were rewritten so each stage is individually
load-bearing (a full name in a sentence beating a colleague who shares a surname; a job
title read out of a sentence; a first name alone; an address whose local part shares no
word with the person's name), and a **falsification matrix** was run: every fix disabled
one at a time, each turning the suite red, plus one entry that reverts all of fix 1 at once
and reds 8 of 13.

**App (`0.7.1-f28`):** new `ChatItem.Kind.QUESTION` + `item_chat_question.xml` — amber like
the approval card because both mean "your turn", never the red *failed* badge. Candidate
chips **fill the input box** rather than answering for the user, the same rule the Inbox
reply route follows. Both `triage_reply_prompt` **and**
`triage_reply_prompt_unknown_sender` reverted to natural phrasing — the write-up named only
the first, and reverting one would have left half the route untested.

**Honest limitation:** `GET /assistant/history` is text-only (handoff §5), so a question
card does not survive process death. The question text does, in the reply bubble, and the
conversation history still lets the model resolve the answer — but the card itself does not
come back.

**Verified.** pytest **86/86** (74 + 13 new, one pre-existing clock failure — see F29),
dryrun **43/43**, `verify_gap_endpoints` **21/21**, `verify_generic_stakeholders --stub`
**21/21**, and new `scripts/verify_live_resolution.py` **16/16 against the real model,
three runs running** (n=1 lies, §6g).

**Verified on the Vivo** (Siva, sales_lead, build `0.7.1-f28`, `EMAIL_MODE=dry_run`, nothing
sent), typed by hand into the Jarvis tab with no context chip and no forced agent:

| typed | result |
|---|---|
| "Draft an email to EKAGHNI MUKHERJEE at Orchid International School about the workshop dates" | real draft + Approve & send; the reply **named the recipient out loud** |
| "Draft an email to the finance head at Orchid International School about the pending invoice" | amber **"One quick check"** card — *"I could not match 'Finance Head' … I have EKAGHNI MUKHERJEE, Mrs. Nair, Mr. Rao. Who did you mean?"* + three chips + "Nothing has been drafted or sent yet" |
| tapped the **Mrs. Nair** chip → sent | drafted to Mrs. Nair about the pending invoice — the question was a step, not a wall |
| Inbox → triage → **Reply** (the reverted natural prompt) | *"Draft an email to EKAGHNI MUKHERJEE at Orchid International School replying to their question: …"* → real draft, *"Re: Refund Policy for Mid-Course Cancellation"* |

---

# Round 5 — found during the F28 fix (2026-08-03)

## F29 — The daily briefing drops follow-ups due today, in the small hours 🔴 OPEN

**Status: OPEN, no code written.** Found by `tests/test_explainability_digest.py::
test_digest_includes_followups_and_demos` going red at 01:49 IST during the F28 job — and
it is not the test that is wrong.

`app/engines/assistant_engine.py:131` filters follow-ups with
`FollowUp.due_date <= now.date()` where `now = utcnow()`. The backend stores and reasons in
**UTC**; the user lives in **IST (UTC+5:30)**. Between 00:00 and 05:30 IST the UTC date is
still yesterday, so a follow-up due *today* is excluded from the digest.

**Observed:** at 01:49 IST, `utcnow().date()` = 2026-08-02 while `date.today()` = 2026-08-03,
and a follow-up due 2026-08-03 was absent from a digest that otherwise rendered correctly
(the demo section, which uses `>=`, was unaffected).

**Impact is small but real:** it is the same class as **F3** — the briefing under-reports
and contradicts the "My day" tile below it, which counts in local time. An early-morning
user reads "nothing due" for a follow-up due that day. The nudge ladder and My Tasks bucket
on the same column and deserve the same look.

**It is a one-line inconsistency, not a timezone-architecture question.** *(Corrected
2026-08-03 — this section first said the honest fix was an org timezone setting. That was
wrong, and the correction matters because it changes the fix from "needs a design decision"
to "make one line agree with its six neighbours".)* **Every other place that filters
follow-ups by date already uses local `date.today()`:** `scheduler.py:39` (the nudge
ladder), `api/followups.py:66-72` (what the "My day" tile and the follow-up queue read),
`query_agent.py:300` (what Jarvis answers), `followup_agent.py:110`.
`assistant_engine.py:131` is the **only** one on `utcnow().date()`, which is precisely why
the briefing and the tile below it disagree on the same screen.

### How F29 was fixed (2026-08-03)

`build_daily_digest` takes `today_local = date.today()` once and uses it for the follow-up
filter, the "— overdue" marker and both ends of the demo window. Four lines, and the digest
now agrees with the six places that already worked this way.

**Proved without depending on the clock.** The original failure only appears between 00:00
and 05:30 IST, so a test that just runs is not a guard — it would pass all afternoon with
the bug present. `test_digest_uses_the_local_date_not_utc` monkeypatches `utcnow` to a
moment whose date is a day behind the reader's, which is exactly what the real clock does in
those hours, and asserts a follow-up due today still appears. Watched failing with the fix
reverted.

**Verified on the Vivo at 03:06 IST — inside the failure window** (`date.today()` =
2026-08-03, `utcnow().date()` = 2026-08-02): the briefing card rendered *"Follow-ups due:
Orchid International School (email) — Confirm the workshop dates"*. Before the fix that row
was dropped at that hour.

Still separate and untouched: the app renders Why-sheet timestamps in UTC (noted under F10),
which is a display concern rather than this filter.

## F30 — Drafts reach the approval gate with `[Name]` placeholders the gate cannot show 🔴 OPEN

**Status: OPEN, no code written.** Noticed as a passing remark in the Phase 6 report
(§8-pre5: *"worth a look if you demo this org"*), then **reproduced twice more** during the
F28 job with a different model and different commands — which turns it from an anecdote
into a behaviour.

**Three of the ten outbound messages in the live demo DB contain literal placeholders:**

| status | subject | placeholders | first one at |
|---|---|---|---|
| **sent** | Re: Refund policy … Vendor-side sign-off contact | `[Name]` `[Designation]` `[Email]` `[Phone]` | char **397** |
| pending_approval | Confirmation: YuviPep Workshop Dates … | `[Insert Date]` `[Insert Start Time]` `[Insert End Time]` `[Insert Location or Virtual Link]` `[Insert Confirmation Deadline]` | char 218 |
| pending_approval | Re: Refund Policy for Mid-Course Cancellation | `[Name]` `[Designation]` | char **474** |

**The compounding defect: the approval card truncates at 300 characters.**
`email_agent` builds `body_preview = message.body[:300]`, and the app renders that. In **2 of
the 3** cases above the first placeholder sits *past* that cut — 397 and 474 — so a person
tapping **Approve & send** is being asked to approve text the card never showed them. The
"human approval gate catches it" defence, which §8-pre5 and this session's first report both
leaned on, does not hold for exactly the cases where it matters most.

**Why the model does it.** In the refund-policy case the client asked *who the vendor-side
sign-off contact is*. The system holds no such person, so the model emitted a blank to be
filled instead of saying it did not know. That is the **same class as F28**: when the AI is
missing a fact its only honest options are to resolve it or to ask — and this is neither. It
is also a direct violation of the product's own "the AI never guesses, it escalates"
principle (doc 04 §6.1), which `inbound_engine` already honours by returning `needs_human`.

**Blast radius:** `.env` is `EMAIL_MODE=smtp` — **live**. One quick approval on a draft like
these sends a client an email reading *"Vendor Sign-off: [Name]"*. For a product whose whole
promise is "the AI does the work, you just approve", that is the single most expensive kind
of bug: it is not wrong, it is visibly unfinished, and the client sees it.

**Fix direction (deterministic, not a prompt).** A prompt instruction is not a fence — this
project has learned that four times (F9, F4, F23, F28). The fence is a check on the body
before it can be approved: a placeholder detector (`[Something]`, `TBD`, `XX`) that either
blocks approval with the offending lines quoted, or marks the draft as needing completion.
The prompt should *also* tell the model to ask rather than emit a blank, but that is the
hint, not the guard. **Independently worth fixing either way: show the whole body at the
approval gate, or say on the card that the preview is truncated.** A gate that hides part of
what it is gating is not a gate.

### How F30 was fixed (2026-08-03)

**New `app/services/draft_check.py` — a pure function, deliberately narrow.** A bracketed
phrase counts as a blank only when it looks like a **field label** rather than prose: an
explicit fill word (`[Insert Date]`, `[Enter your name]`), or letters-only Title/UPPER case
of at most five words (`[Name]`, `[Client Name]`). Plus `{{mustache}}`, an unrendered
`{client_name}` (the shape this project's own templates use — F6 warned a renamed variable
blanks itself silently), and a bare `TBD`. **A fence that blocks a legitimate send is worse
than the bug**, so `[see attached]`, `[Rs 59,000]` and `[subject to confirmation]` all pass
untouched, and that is asserted as its own test.

**Fenced at BOTH approve routes**, because the inbox is the other way into the same send
(handoff §5): `message_service.approve_message` and `approval_engine.decide`. The inbox
check runs **before any state change**, so a refusal leaves the approval exactly as it was —
decided nothing, applied nothing — and it covers `bundled_entities` too, so a finished draft
cannot smuggle an unfinished one out with it (Workflow 18).

**A fence, not a veto.** Working principle 1 is that humans approve or edit, so
`allow_blanks=true` lets an approver who has read the blanks send anyway. Absent = false =
the safe answer, which means an older app is protected rather than broken: it simply gets
the refusal, verbatim, and cannot send blanks it was never shown.

**The gate now shows what it is gating.** One hook in `BaseAgent._enrich_approvals` — rather
than in each agent, so a tool added in a later phase inherits it — raises the inline card's
`body_preview` from 300 to 1200 characters, says so when even that is truncated, and adds
`blanks` + a human `warning`. `GET /messages(/{id})` carries `blanks` too, so a screen can
warn *before* the tap instead of only refusing after it. The Approvals inbox already showed
the whole body; only the assistant's inline card was cutting it.

**Contract changes, all additive:** `POST /messages/{id}/approve?allow_blanks=`,
`allow_blanks` on the decide body, `blanks` on message reads, `blanks`/`warning`/
`preview_note` on `pending_approvals[]`. **No schema change** (55 tables both sides).

**App `0.7.2-f30`:** tapping Approve on a draft with blanks opens *"This draft isn't
finished"*, naming them, with **Send as it is** / **Not yet** — on both the assistant card
and the Approvals inbox.

**Verified.** pytest **96/96** (87 + 9 new), dryrun 43/43, gap 21/21, stakeholders --stub
21/21, `verify_live_resolution.py` **19/19 across three runs**. A **falsification matrix**
disabled each of the six pieces one at a time and every one turned the suite red.

**What only the live run could tell us — no false positives.** Three real AI-written drafts
produced by the live model in that run were checked by the detector and none was flagged,
and one was approved and queued normally. That is the risk the unit tests cannot measure.

**Verified on the Vivo** (Siva, build `0.7.2-f30`, `EMAIL_MODE=dry_run`): the Approvals
inbox showed the whole body; Approve raised the dialog listing all five blanks; **Not yet**
left the message `pending_approval` and the approval undecided; **Send as it is** queued and
"sent" it as a dry-run `.eml` with the approval resolved to `approved`. Nothing left the
machine.

# Round 6 — genericity re-audit (2026-08-03)

## F31 — Domain-genericity is NOT complete: two live defects, one landmine ✅ FIXED 2026-08-03

> **CLOSED 2026-08-03.** The original write-up is kept verbatim below because its reasoning
> is the record; **two of its claims turned out to be wrong** and are corrected in
> "How F31 was fixed" at the end of this section. Read that for what shipped.

**Status when raised: OPEN, no code written. Backend was FROZEN — this needed an unfreeze.**
Raised because the user asked a direct question — *"this thing is totally generic right?"* —
and the honest answer is **no, not quite**. Every claim below was checked by reading the
code and tracing the call path, not by trusting §6c.

**Why this matters more than a tidiness complaint:** domain-genericity is working principle
2 and the product's headline claim. Three of the items below produce a **wrong number**,
**wrong client-visible text**, or **the wrong currency on screen** for a client outside
education or outside India.

> **Scope note (amended 2026-08-03):** this finding was first written as backend-only. A
> second, wider pass added **two app defects** (items 4 and 5) — so closing F31 needs an
> **app build as well as a backend unfreeze**. The first write-up under-counted, which is
> the third time a genericity claim in this project has done so.

> ⚠️ **§6c is over-confident for the second time.** It says the genericity sweep is "done,
> with three deliberate exceptions". That was written after the F11 sweep, which classified
> sites as *prompt / user-visible string / tool name* — and had **no category for branching
> logic**. Everything below is code that makes a decision or writes a value based on a
> domain word, which is why the sweep missed it. §6c has been corrected to point here.

### Confirmed LIVE defects

**1. `planner_engine._estimate_value` (`:833`, called from `propose_project_from_spec:1389`)
— a project's value estimate is silently wrong for any non-education pricing unit.**

```python
if "student" in unit:      total += price * students
elif "flat" in unit:       total += price
# anything else is silently ignored → `return total or None`
```

The irony is that the AI half is already generic: `planning.py:465` asks the model for
`pricing_quantity` — *"the count the client mentioned that pricing scales with"* — with no
domain word at all. The deterministic half then throws that away unless the pricing unit
literally contains `student`. A client priced **per seat / per licence / per rack / per
site** gets `value_estimate = None`.

**Confirmed live**: `propose_project_from_spec` is the LLM path (called at `:1126`, inside
`if nlu.llm_available()`). This is not a stub-only route.

**2. `inbound_engine._handle_scope_change` (`:918`, reached from `_route_change_request:708`)
— a scope-change amendment writes "per student" into a client-visible document.**

The rate *lookup* is generic and the comment says so (`unit.startswith("per")` — "per head /
per seat / per rack, not a domain word"). But the amendment it then creates is hardcoded:

```python
delta_line_items=[{"code": "per_student", "label": "Scope addition",
                   "unit": "per student", ...}]
```

So a logistics client who asks to expand scope gets an amendment line reading **"per
student"**. The lookup was made generic and the write was not.

### Landmine — dead today, directly under the next phase

**3. `document_engine.generate_text_artifact` (`:104`) hardcodes an industry in a live LLM
system prompt** — *"You write clear, warm, factual documents for an **education-services
company**"*. This is the exact **F4** class: a domain word in a prompt makes the model write
in that domain whatever the client is.

**It has zero callers** — verified across `app/`, `scripts/` and `tests/`, with no dynamic
dispatch — so it is harmless *right now*. But `document_engine` is precisely the **Phase 7.1**
surface: `create_invoice`, `record_payment`, `add_deliverable`, `build_amendment`. The next
phase builds invoices and deliverables in this file, next to a function that is one call away
from shipping F4 again.

### Corrected on inspection — NOT defects

Two things this audit first flagged and then cleared, recorded so nobody re-raises them:

- `sync_engine.py:267` and `inbound_engine.py:1093` read
  `"school" in reason or "client" in reason or "approval" in reason`. The generic
  alternatives are present, so a non-education client still matches on *client* /
  *approval*. These are **redundant aliases, not dependencies**. Cosmetic at most.
- `nlu.py`'s regexes (`syllabus`, `teacher demo`) and `planner_engine.DEFAULT_FIRST_PLAN`
  (*"Prepare day-wise syllabus"*, *"Schedule teacher demo session"*) are education-shaped
  but sit behind `if nlu.llm_available():` (`planner_engine:1110`). With OpenRouter
  configured they are **unreachable**. They do run in `pytest` and the 43-workflow dry-run,
  so those suites exercise education-flavoured content — worth knowing when reading them,
  not a production defect.

### Low severity — LLM-facing examples

`orchestrator.py:45` ("email it to the principal"), `proposal_agent.py:167` and
`email_agent.py:43` both use *'Principal'* as the example contact hint. Bias risk in a
prompt, not breakage. **`email_agent.py:43` was added by this session's F28 work** — a
genericity slip introduced while fixing something else, which is worth stating plainly.

### Deliberate and unchanged (agreed previously)

The `"school": <lead name>` wire keys on `/action-items`, `/demos`, `/followups` (never
rendered; the app maps them to `leadName`), docstrings and comments, demo lead names. Add to
that list `constants.py:408` `SYLLABUS = "syllabus"`, a deliverable-type enum value nobody
had catalogued.

### App defects — added 2026-08-03 on a second, wider pass

> ⚠️ **This section corrects an earlier claim in this very finding.** The first pass said
> *"the Android app has no domain vocabulary at all"*, verified by grepping `strings.xml`.
> **That was wrong, and the method was the reason**: the offending string is a Java literal,
> so a `strings.xml` grep could never have found it. F31 was under-counted on its first
> write-up — the same pattern as §6c, one level down. **Verify by behaviour, not by the one
> file the text is supposed to live in.**

**4. `ProjectDetailFragment.java:619` — a user-visible hardcoded domain hint.**

```java
role.setHint("Role at client (e.g. principal, procurement_head)");
```

Runtime hint on the Add-stakeholder dialog. It pairs "principal" with "procurement_head", so
it reads as a mixed example rather than a pure education assumption — but it is domain
vocabulary on screen, and it is hardcoded in Java instead of `strings.xml`, which is both a
genericity miss and a break from the pattern F14's copy pass established. **Nine hardcoded
user-visible literals exist in Java in total** (`setHint`/`setText` with a string constant);
the rest are domain-neutral but they bypass resources the same way.

**5. The app hardcodes ₹ and ignores the currency the backend already stores.**

`ProjectDetailFragment.java:203` and `ProjectsListFragment.java:174` both format money as
`String.format("₹%,.0f", …)`. Meanwhile the backend models currency properly —
`PricingTable.currency`, and `document_engine:295` uses `project.currency or "INR"`. **A
project priced in USD or AED renders as rupees on screen.**

This is a geography gap rather than an industry one, but it is the **same shape as the two
live backend defects**: the data model is generic and the code sitting on top of it is not.
It is also the cheapest of the lot to fix, because the field it needs already exists and is
already populated.

### Verified clean (re-checked on the wider pass)

These came back genuinely generic and are worth knowing so nobody re-audits them:

- **The skill taxonomy is per-org data**, read through `planning.org_skill_names(db, org_id)`
  with an honest fallback when an org has none (`planning.py:102` → `'general'`). F25
  constrained the planner to **the org's own** taxonomy, not a hardcoded education one.
- **No model column anywhere is domain-named** — the schema is clean.
- **No API response key names a domain** except the four documented `"school"` keys
  (`/action-items`, `/demos` ×2, `/followups`), and the app's DTOs document that mapping.
- `program.py:39` and `proposal_service.py:312` "workshop" hits are **docstring examples** of
  a generic `code`/`label`/`unit` shape.
- `inbound_engine:1013`'s `curriculum_design` sits inside the branch explicitly marked
  *"Stub-provider template (deterministic test suites only)"*.
- The education examples scattered through the layouts are **`tools:text`** — design-time
  preview only, stripped from the APK, never rendered.
- `constants.py:408` `SYLLABUS = "syllabus"` has **no logic depending on it** — a dormant
  enum value.
- `strings.xml` itself is clean. That part of the original claim stands; it just was not the
  whole app.

### A separate axis the docs have never stated

The system is **domain-generic in intent but neither language- nor locale-generic**, and
that has never been written down anywhere, so it reads as an unnoticed gap rather than a
choice:

- **Language:** English is assumed throughout — every prompt, `inbound_engine`'s stopword
  list, and (added 2026-08-03) the connector words and fill-word list in `resolvers.py` /
  `draft_check.py`.
- **Locale:** `nlu.py:55-72` parses money in Indian numbering (*lakh* / *crore*, `₹`/`Rs`/
  `INR`), and item 5 above hardcodes `₹` in the app. The backend is better than the app
  here — it stores a real `currency` per pricing table and per project.

Both are defensible scope decisions for the current market. They should be **stated**
decisions, and the currency one is worth separating out because the app is discarding data
the backend already has.

### Fix order when unfrozen

**Note: this is no longer backend-only — items 4 and 5 need an app build too.**

1. `_estimate_value` — accept any `per …` unit and use the generic `pricing_quantity`
   (a wrong number is the worst of these).
2. `_handle_scope_change` — carry the base proposal's own `unit`/`code` into the amendment
   instead of hardcoding one.
3. `generate_text_artifact` — neutral wording **plus** the "never assume an industry" rule
   F4 proved is needed; do it **before** §7.1 builds on that file.
4. **App:** render the project's own `currency` instead of a hardcoded `₹` (the field
   already exists and is already populated — cheapest fix here).
5. **App:** move `ProjectDetailFragment:619`'s hint into `strings.xml` and neutralise the
   example; optionally sweep the other eight hardcoded literals while there.
6. The three `'Principal'` prompt examples.
7. **A regression test that greps every LLM prompt for an industry word, and an app check
   that no user-visible literal is hardcoded outside `strings.xml`** — otherwise this
   recurs, as it now has three times (§6c twice, and F31's own first write-up).

---

## How F31 was fixed (2026-08-03)

Backend unfrozen for one named job — *"F31 genericity, full scope incl. corrections A/B and
item C"* — then **RE-FROZEN**. App built to **`0.7.3-f31`** and verified on the Vivo.

### Two claims in the write-up above were WRONG

**Correction A — the currency fix was never app-only, and the field was NOT on the wire.**
The write-up called it "the cheapest of the lot to fix, because the field it needs already
exists and is already populated". The *column* exists (`models/project.py:46`); the
**response** did not carry it. `app/api/projects.py::_project_dict` — the serializer behind
**both** `GET /projects` and `GET /projects/{id}` — never emitted `currency`, so the app was
not "discarding" it, it was never sent one. The fix needed an additive API change first.

This is F31 committing its own headline error a third time: it verified currency by finding
the model column rather than by reading the response. **Verify by behaviour** applies to the
backend exactly as much as to `strings.xml`.

**Correction B — `_estimate_value` also returned `None` for a flat-priced engagement.**
Line 837 read `if program is None or not students: return None`, short-circuiting *before*
the flat lines were summed. So fixing only the unit vocabulary, as the fix order above
specifies, would still have left a quantity-independent engagement worth nothing. The
quantity now gates only the scaling lines.

### Three more sites — found by the new guard, not by a human

The prompt guard was written to stop *future* regressions and immediately found *present*
ones, which is the strongest argument for it:

- **`app/ai/planning.py:466` and `:472`** — the live initial-planning prompt offered
  `(students, participants, units, seats...)` and `(principal, cto, procurement_head,
  store_manager, plant_supervisor...)`. Both are deliberately mixed-industry lists, but both
  **led with the education term**, and F31 had already ruled that class worth fixing for the
  three `'Principal'` examples. Now `(participants, seats, licences, units, sites...)` and
  `(cto, procurement_head, store_manager, plant_supervisor, site_lead...)`.
  **F31 cited `planning.py:465` as proof the AI half was "already generic … with no domain
  word at all". That was wrong** — the domain word was in the very next clause.
- **`app/engines/nlu.py:398, 403, 433-434`** — the **live** inbound classification schema and
  prompt used `students_delta` and `syllabus_change`, and told the model *"syllabus_change is
  any change to teaching/deliverable content"*. F31 cleared "nlu.py's regexes" as unreachable
  — correctly, but those are lines 279-292 / 475-536, the **heuristic** branch. This is the
  other side of the same `if llm_available():`. Renamed to `quantity_delta` /
  `content_change`; **both readers accept the old names**, so nothing breaks.

### What shipped

| | Fix | File |
|---|---|---|
| B1 | Any `per …` unit scales by quantity; flat tested first (`"flat per bootcamp"` contains both); flat lines survive a missing quantity | `planner_engine.py:833` |
| B2 | The amendment carries the base proposal's own `code`/`unit`; the no-`per` fallback is strictly **wider** than the old `"student" in unit` test | `inbound_engine.py:952` |
| B3 | Neutral prompt + the "never assume an industry" rule F4 proved is needed | `document_engine.py:104` |
| B4 | The three `'Principal'` examples | `orchestrator.py:45`, `proposal_agent.py:167`, `email_agent.py:43` |
| B5 | Live schema/prompt renamed, old names still read | `nlu.py`, `inbound_engine.py:634/929` |
| B6 | `"currency"` on the projects serializer — **additive**, older APK unaffected | `api/projects.py` |
| B7 | The two planning-prompt example lists (found by the guard) | `ai/planning.py:466/472` |
| A1 | New `core/util/Money.java` resolves the ISO code to a symbol; used by the project list, project detail, proposal detail and lead detail | app |
| A2/A3 | All 9 user-visible Java literals moved to `strings.xml`; the role hint neutralised to `procurement_head, plant_supervisor` | app |

**No schema change, no migration, no contract break.** The only wire change is an added key.

### The guards (the durable half)

- **`tests/test_genericity.py`** — *parses*, does not grep. It AST-walks every module under
  `app/`, collects the strings that actually reach a model (prompt kwargs, `messages=`, whole
  tool/JSON schemas **including property names**, following a variable reference one level so
  a prompt held in a constant is not invisible) and fails on an industry word. Docstrings and
  comments stay exempt — that was a recorded decision, and only an AST walk can honour it.
  Plus behavioural tests on `_estimate_value` and structural ones on the amendment line and
  the projects serializer.
- **`scripts/check_hardcoded_strings.py`** — the app half, closing the hole that hid this
  twice: Android Lint's `HardcodedText` inspects layout XML, not Java. Three checks (Java
  literals outside resources, domain words, hardcoded currency symbols) plus a
  **`--self-test`** precision suite, because a guard that blocks legitimate code is worse
  than the gap it closes.
- **`scripts/verify_live_genericity.py`** — the real model, a colocation client priced per
  rack in USD.

### Evidence

- **`verify_live_genericity.py` 15/15 against the real model**: `value_estimate = 970000`
  (= 40 × 18,000 per rack + 250,000 flat per hall) where it would have been `None`; the
  amendment line reads `unit='per rack' code='rack'`; `quantity_delta=30` came through from a
  client counting racks; the `document_engine` artifact leaked **zero** education words;
  `currency=USD` on both project endpoints.
- **Live data**: the demo org's own pricing table (`per workshop` / `per kit` / `per event`)
  produced `None` before and **210,000** after — the seeded Orchid project has carried
  `value_estimate = None` in the real database all along. *(It still does: the estimate is
  computed at project creation, and there is no recompute path. That is a snapshot by design,
  not a residual defect.)*
- **Falsification matrix — 18/18.** Every fix was disabled one at a time and the named check
  required to go red. It earned its keep twice: it proved the prompt guard **did not cover**
  `email_agent.py` (the string lives in a `parameters={...}` dict, not a `description=`
  kwarg) and then that it did not cover `orchestrator.py` or nlu's schema either (prompts
  held in variables). Both blind spots are closed.
- **Suites**: pytest **104/104** (96 + 8 new), dryrun **43/43**, gap **21/21**,
  stakeholders --stub **21/21**, `verify_live_resolution.py` **19/19** (re-run because B4
  edits a prompt the F28 resolver path uses).
- **Device (Vivo, `0.7.3-f31`, Siva)**: a USD project rendered **`$210,000`** on both the
  Projects list and the project detail — the screens that used to print `₹` — and the
  Add-stakeholder dialog showed *"Role at client (e.g. procurement_head,
  plant_supervisor)"*, from `strings.xml`. The `[f31-verify]` fixture has been deleted.

### What is still not generic, and is a stated choice

`nlu.py:55-72` parses money in Indian numbering (*lakh*/*crore*) and English is assumed
everywhere — every prompt, `inbound_engine`'s stopword list (which still contains "school",
"class", "students": it only *removes* words, so a non-education client is unaffected beyond
slightly weaker matching), and the connector/fill-word lists. Reasonable for the current
market; now written down as a decision rather than left to read as an oversight.

# Round 7 — full end-to-end app simulation (2026-08-03, in progress)

A complete wipe-and-rebuild simulation across the whole app and every workflow the
built screens can reach, on the real device with real recordings, a real business-card
scan, real outbound email and real calendar invites. **These three were found during
setup, before the simulation itself began.**

## F32 — Both seed scripts finish their work and then never exit, holding the database ✅ FIXED

**Reproduced deterministically**, twice, on clean throwaway DBs:

```
seed_demo.py           HUNG    after  45.0s   last line:   mithun@yuvipep.com   Operations Lead
seed_workflows.py      HUNG    after  46.1s   last line: Staff: Ananya, Akash, Rahul, …
```

Both scripts **commit, print their success line, and then hang forever**. The work is
done; the process cannot exit. Cause: `aiosqlite` runs a **non-daemon worker thread per
connection**, and neither script calls `await engine.dispose()` — so the thread outlives
`asyncio.run()` and blocks interpreter shutdown.

**Every `verify_*` script already does this correctly** — `engine.dispose()` appears in 20
of them. The two **seed** scripts, which the handoff instructs every new session to run,
are the ones that do not.

**This corrects a diagnosis recorded twice.** Handoff **§6g** and **§6i** both state that
*"a script that **raises** leaves a live `python.exe` holding the DB"*. It is not the
failure path — **it happens on success**, every single time. The recurring orphan-`python`
problem, and the Step-0 orphan check invented to catch it, have both been attributed to the
wrong cause since 2026-07-22.

**Live impact, observed here:** the orphaned seeder holds `salesplatform.db`, so the *next*
writer blocks indefinitely. `seed_demo.py` sat blocked for **540 s** behind a
`seed_workflows.py` that had already finished — which is exactly how this was found. A
`Remove-Item` on the held file then leaves Windows in a delete-pending state: the file
vanishes from directory listings while the holder keeps using it, which makes the symptom
look impossible ("already seeded" against a database that does not exist).

**Fix** (3 lines each, the same shape every `verify_*` script uses; backend is FROZEN so
this is NOT applied):

```python
if __name__ == "__main__":
    try:
        asyncio.run(seed())
    finally:
        from app.database import engine
        asyncio.run(engine.dispose())
```

**Workaround used for this simulation, no code change:** a helper runs each seed, waits for
its success line, then terminates the process. Killing after the COMMIT is safe — the write
is durable in the WAL and SQLite recovers it on next open; row counts were re-read to
confirm.

## F33 — `seed_demo`'s idempotency guard is org-level, so seeding ORDER is silently load-bearing ✅ FIXED

`seed_demo.py:173-177` guards on the **organisation**:

```python
existing = (await db.execute(select(Organisation).where(Organisation.slug == "yuvipep"))).scalar_one_or_none()
if existing:
    print("YuviPep already seeded — nothing to do.")
    return
```

One row named `yuvipep` and it creates **nothing** — no Siva, no `admin@`, no IBC program,
no pricing table, no demo team, and **none of the 24 user-skill rows F25 added**. It reports
this as *"already seeded — nothing to do"*, which reads like success.

`seed_workflows.py` is different: it guards **per entity** (per user, per skill, per
program, per template), so it layers correctly onto an existing org.

**Consequence:** the two scripts compose in exactly one direction.
- `seed_workflows` → `seed_demo` = the workflows cast only. **Observed**: Siva absent, IBC
  absent, 21 skills instead of 45. The run looks successful.
- `seed_demo` → `seed_workflows` = the true union. **Observed**: 13 users, 45 skills, 3
  programs, 6 pricing tables, 4 playbooks, 16 approval rules, 1 vendor.

Nothing in either script, in the handoff, or in the roadmap states this. Both docstrings say
*"idempotent — safe to run twice"*, which is true of each **alone** and misleading together.

**Severity:** it produces a plausible-looking but incomplete environment, and the failure is
silent. Anyone rebuilding a demo box could lose skill-based assignment (F25) without a single
error message.

## F34 — `seed_workflows` writes a malformed `email_domain`; an org seeded by it alone can never add staff ✅ FIXED

`seed_workflows.py:212` creates the org with:

```python
Organisation(name="YuviPep", slug="yuvipep", email_domain="@yuvipep.com")
```

But the column is meant to hold the domain **without** the `@`. Two independent proofs in
`app/`:

- `app/api/admin.py:84` — `if not body.email.lower().endswith("@" + org.email_domain)`.
  With the seeded value this tests `endswith("@@yuvipep.com")`, which **no address can ever
  satisfy**. Adding a staff member is impossible, and the error message it then raises reads
  *"Staff email must use your organisation's domain @@yuvipep.com"*.
- `app/api/organisations.py:65` — `domain = body.email_domain.lstrip("@").lower()`. The API
  strips a leading `@` deliberately, which settles what the intended stored format is.

`seed_demo.py:181` stores `"yuvipep.com"` — correct.

**Reachability:** only when `seed_workflows` **creates** the org. On an existing org it
reuses the row and does not overwrite the field, so the `seed_demo` → `seed_workflows` order
required by F33 also happens to avoid this. Verified in the seeded DB:
`email_domain = 'yuvipep.com'`. A `seed_workflows`-only environment — which is what
`verify_generic_planner.py`, `verify_live_genericity.py` and every dry-run build — carries
the broken value.

**Why no suite caught it:** nothing in pytest, the 43-workflow dry run or the verify scripts
ever calls the add-staff route, so the one consumer of this field is untested.

## How F32 / F33 / F34 were fixed (2026-08-03)

Backend unfrozen by the user for one named job — *"fix the seed scripts"* — scoped to
`scripts/seed_demo.py` and `scripts/seed_workflows.py` only.

- **F32** — `try/finally: await engine.dispose()` inside a single `_main()` coroutine in
  both scripts, the same shape the 20 `verify_*` scripts already use. The probe that
  reproduced the hang now reports **EXITED after 1.9 s / 2.8 s** instead of HUNG.
- **F34** — one literal: `email_domain="yuvipep.com"`. Both seed paths now produce
  `"@" + domain == "@yuvipep.com"`, verified by reading the column back from an org created
  by each script alone.
- **F33** — **deliberately not restructured.** Everything after the guard is bare
  `db.add(...)` with no per-entity checks, so lifting the guard would duplicate the entire
  org on a second run; the constraint is genuine. What was wrong was *reporting* it as
  "nothing to do". The skip now names every entity it did not create, back-fills the F25
  user-skill rows (`seed_user_skills` is already idempotent, and their silent absence is the
  damaging part), states the working order, and **exits 2** so a caller can detect it.
  Principle 3 — nothing invisible: a no-op is allowed, a no-op dressed as success is not.

**Suites after the change** (the dry run builds its world with `seed_workflows`): pytest
**104/104**, dryrun **43/43**, stakeholders --stub **21/21**.

**Falsification:** each fix was reverted in turn — restoring `asyncio.run(seed())` brought
the hang straight back (HUNG at 45 s), and restoring `"@yuvipep.com"` reproduced the
`"@@yuvipep.com"` comparison. The F33 message was verified by re-running `seed_demo` against
an org that already existed: exit code **2**, with the entity list printed.

## F35 — The IMAP poller reads the WHOLE inbox unscoped and marks real mail read 🔴 OPEN

**Observed live, 2026-08-03**, the moment `INBOUND_EMAIL_MODE=imap` was switched on against
the account the project's own `.env` designates (`SMTP_DEFAULT_USERNAME`,
`GOOGLE_CALENDAR_ID` = `ekaghni.mukherjee@gmail.com`):

```
INBOX reachable — 45063 message(s), 38579 unseen
poll_once() -> {'duplicate': 1, 'automation': 24}
Mail skipped (mailing-list headers): notification+…@facebookmail.com
Mail skipped (mailing-list headers): security@facebookmail.com
Mail skipped (mailing-list headers): mail@news.goodgame.com / "ekaghni, confirm your email address"
```

The poller was reading the owner's **personal** Facebook, security and newsletter mail.

**Three properties combine badly:**

1. `mail_poller.py:116` — `box.select("INBOX")` is **hardcoded**. There is no folder, no
   label, no `SINCE` date, and no allow-list: every unseen message in the mailbox is in
   scope. Nothing in `.env` or the admin integration can narrow it.
2. `mail_poller.py:119-121` — the fetch is deliberately **non-PEEK**, with the comment
   *"A non-PEEK fetch marks the message \\Seen on the server; the Message-ID dedupe below
   covers any re-delivery regardless."* Correct for dedupe; it also means **reading someone's
   mailbox permanently alters it**.
3. `_FETCH_LIMIT = 25` per org per poll, `inbound_poll_seconds = 120` → **up to 750 messages
   marked read per hour**, indefinitely.

**Damage in this session:** the backend ran 22:08:40–22:13:11 (~2 scheduled polls) plus one
manual `poll_once()` — so on the order of **25–75 of the owner's personal emails were fetched
and marked as read**. Not recoverable from the application side; Gmail keeps no per-message
read-state history.

**Why "skipped" is not "safe".** All 24 were correctly *classified* as automation and
ignored, and that gate works exactly as designed. But the skip happens **after** the message
has been fetched — and it is the fetch that clears the unread flag. A gate that runs after
the side effect does not prevent the side effect. (Same shape as F30: *a gate that hides part
of what it is gating is not a gate*.)

**This is a deployment-shaped defect, not a coding error.** The design assumes a **dedicated
org mailbox**, which the module docstring says outright — *"each organisation's inbox"*. For
that deployment every property above is reasonable. The gap is that nothing **enforces or
even warns** about it, while the project's own configuration points the feature at a human's
personal account. A first-run guard, a `SINCE` floor, a required label/folder, or
`BODY.PEEK[]` would each have contained it.

**Not fixed:** the backend is frozen for this, and the right fix is a design decision (scope
by label? peek and track UIDs? refuse a mailbox above N messages?) rather than a patch to
make mid-simulation. **Mitigation applied immediately: the backend was stopped within
minutes and `INBOUND_EMAIL_MODE` returned to `off`.**

**Decision (user, 2026-08-03):** the simulation proceeds with **IMAP off**, driving every
inbound moment through the app's *"Log a client reply"* screen — a real user-facing route
into the same Inbound Engine. **Known gap recorded deliberately: the IMAP socket path is
therefore NOT exercised by Round 7.** `verify_live_imap.py` covers `process_raw_email` on a
throwaway DB but never opens a socket, so nothing in the suite proves the transport. Retest
it against a **dedicated** org mailbox when F35 is fixed.

## F36 — The login screen's server label goes stale after the Environment sheet applies ✅ FIXED

✅ **FIXED 2026-08-06 (app; not device-verified).** `EnvironmentSheet` now emits a fragment result on **both** Apply and Reset, and the login screen listens — `onResume()` never fires on a dialog dismiss, which is why the chip kept showing the old server.

**Observed on the Vivo**, Act 1 of the simulation. After `pm clear` the app fell back to the
dead default tunnel URL (a known §3 gotcha). Opening the Environment sheet, typing
`http://127.0.0.1:8000` and tapping **Apply**:

- the sheet re-opened showing **`Current: http://127.0.0.1:8000`** — the preference really was
  saved, and networking used the new value;
- the login screen underneath still read **`server: visits-clicking-fingers-chest.trycloudflare.com`**,
  and still did after dismissing the sheet.

**Cause, confirmed in source.** `LoginFragment.java:92-100`:

```java
private void refreshServerChip() {
    binding.loginServerChip.setText("server: " + SplashFragment.shortHost(environmentStore.getBaseUrl()));
}
@Override public void onResume() { super.onResume(); if (BuildConfig.DEBUG) refreshServerChip(); }
```

The chip only refreshes in `onResume()`. `EnvironmentSheet` is a **`BottomSheetDialogFragment`**
— showing and dismissing a dialog never pauses the host fragment, so `onResume()` does not
fire and the label stays stale until the fragment is recreated. `EnvironmentSheet:62-64`
calls `environmentStore.setBaseUrl(...)` then `dismiss()` and notifies nobody.

**Why it matters more than it looks.** This is the screen a person uses precisely *when the
backend is unreachable*. It reports the old server after a successful change, so the honest
reading is "my change did not take" — and the documented recovery from a `pm clear` runs
straight through it. Debug-only (`BuildConfig.DEBUG`), so it never ships to a user; it misleads
whoever is doing the testing, which during this simulation was the whole point.

**Severity:** low impact, high confusion. Nothing invisible (principle 3) cuts both ways — a
screen must not report a stale fact as a current one.

## F37 — My own F31 guard was line-based and missed wrapped setter calls ✅ FIXED

`scripts/check_hardcoded_strings.py` — the app-side guard written to close F31 — iterated
**line by line**, so any setter call the formatter wrapped was invisible to it:

```java
binding.loginServerChip.setText(
        "server: " + SplashFragment.shortHost(environmentStore.getBaseUrl()));
```

`SETTER_RE` matches this string fine when handed the whole call; only the per-line loop
prevented it. The guard therefore reported **"none"** for a file that contained a hardcoded
user-visible literal, which is exactly the failure mode it exists to prevent.

**Consequence for F31's accounting:** F31 recorded *"nine user-visible literals hardcoded in
Java"*. With the wrapped form included it is **eleven** — `LoginFragment:93` (`"server: "`)
and `SplashFragment:48` (`"v"`, a version prefix, borderline). **That is the fourth
under-count in this project's genericity accounting** (§6c twice, F31's first write-up, now
this), and the first one committed by the guard rather than by a human sweep.

**Fixed:** setter matching now runs against the whole file with line numbers derived from the
match offset, and the precision suite gained a wrapped-call fixture (**11/11**). The two
literals are now reported. **They have NOT been moved to `strings.xml`** — that is an app
change and would mean rebuilding the APK mid-simulation, invalidating the build under test.
Carry it as app work.

**The lesson, which is the durable part:** a guard's fixtures inherit the blind spots of
whoever wrote them. Every fixture in the original suite was a single line, so the whole class
of wrapped calls was untested — and the falsification matrix could not catch it either,
because it only ever asked "does this check notice a fix being removed?", never "is there a
shape of input this check cannot see?". **Falsification tests the fixes; it does not test the
detector's reach.**

## F38 — Correcting a scanned field does not re-address the intro the same screen just queued ✅ FIXED

✅ **FIXED & verified 2026-08-06 — by inverting the flow, not by patching the address.** Product owner's decision: *the scan proposes, the human edits, and only the contact's final saved contents count*. So **nothing is drafted at scan time**; the intro is built on **save** (`PATCH /contacts/{id}`) from values a human has confirmed. A corrected address is simply the address the draft is built from — **there is no stale draft to chase, so F38 dissolves rather than being worked around.** The dangerous re-resolve-from-`contact_id` fix is therefore NOT used, and WhatsApp / typed recipients / contactless proposal emails are untouched. Guarded three ways so an ordinary contact edit never mails anyone: card-sourced only, no existing intro, and an explicit `draft_intro` flag. **Bonus honesty win:** abandoning the verify sheet now queues nothing at all, where before it left a draft nobody had vouched for. 5 tests.

Found 2026-08-03, Round 7 Act 2, on the **real** business card.

The card scan is a **write-then-verify** flow, and the two halves disagree about what the
verify step governs. `app/api/leads.py:344-386` creates the contact from the OCR result,
drafts the intro message to `scan.email`, and **commits** — all before the human sees
anything. The verify sheet then appears. Its Save calls `PATCH /leads/contacts/{id}`, and
`update_contact` (`app/api/leads.py:400-421`) writes contact columns only. It never looks at
`outbound_messages`.

So a corrected address reaches the contact record and **not** the message already queued
against it.

**Observed, not inferred.** OCR misread the card's `mekaghni@telaverge.com` as
`mekaghnni@telaverge.com` (double n) at 86% confidence. The address was corrected on the sheet
and saved; the contact list re-rendered with the right address. The DB before and after:

```
                    before save                after save
contact.email       mekaghnni@telaverge.com    mekaghni@telaverge.com    ✅ corrected
message.to_address  mekaghnni@telaverge.com    mekaghnni@telaverge.com   ❌ unchanged
                    (7bfd057b…, status=pending_approval, both reads)
```

**Why it matters here specifically:** `EMAIL_MODE=smtp` is live for this run. An approver
tapping through that queued intro sends it for real, to an address a human had already looked
at and fixed. The approval screen shows the stale address, but an approver has no way to know
it was ever corrected — it looks like the address the scan found, because it is.

**What makes it a trap rather than a mere gap:** the sheet's own confirmation line *names the
address* — "An intro message to **mekaghnni@telaverge.com** was drafted" — directly beneath
the editable email field. On screen, at save time, both were visible at once and disagreed:

```
email field:  mekaghni@telaverge.com      ← just corrected by the human
intro line:   ...to mekaghnni@telaverge.com was drafted
```

Nothing tells the user those two are not the same address, or that editing one does not touch
the other.

**Related to F2 but not the same defect.** F2 was the app *claiming* a message had been sent
when it had not. Here the claim is accurate — it says "nothing was sent", and nothing was.
The claim is **stale**, not false. Same family: the app's account of the outbound message has
drifted from the outbound message.

### Escalation — rejecting the message does not fix the address either (2026-08-04)

The obvious human recovery is to reject the queued message and let the system redraft it. That
was tried, with a rejection note stating the problem in plain words:

> *"Wrong email address - OCR read mekaghnni instead of mekaghni. Contact is corrected now."*

The redraft **kept the wrong address**:

```
rejected           mekaghnni@telaverge.com   17:18:35   7bfd057b
pending_approval   mekaghnni@telaverge.com   21:46:20   a13c8db7   ← redraft
approval reason:   "Redraft after rejection — note applied: Wrong email address…"
```

The approval record confirms the note *was* applied to the redraft, and the contact had been
corrected **more than four hours earlier**. The redraft carries `to_address` forward from the
rejected message instead of re-resolving it from the contact.

**So there is no path by which the corrected address reaches the message.** Editing the
verify sheet does not; rejecting with an explicit explanation does not. The queue simply
re-presents the same wrong address for approval, and a lead working the queue in good faith
will eventually approve a send to a dead mailbox.

This moves F38 from "a stale field" to "**a correction the system cannot accept**", and it
raises the priority accordingly: the redraft path is where a human's last chance to fix it
lives, and it is closed.

**Cause confirmed** (`app/engines/communication_engine.py:439`): the redraft is built with
`to_address=message.to_address`, copied straight from the rejected message. Note the same
constructor sets `contact_id=message.contact_id` — **the corrected contact is right there**,
one lookup from the correct address. See [F44] for the wider version of this defect.

**And the approvals list now reads as reassurance.** Before rejection the card named the
recipient — *"Intro to mekaghnni@telaverge.com (email) — approve to send"* — so the error was
at least visible. The redraft's card replaces that with the rejection note:

> **outbound message · Decide · expires in 23h**
> *"Redraft after rejection — note applied: Wrong email address - OCR read mekaghnni instead
> of mekaghni. Contact is corrected now."*

The address is **not shown on the card at all**. An approver skimming the queue sees "note
applied" and "Contact is corrected now" and reasonably concludes the problem was dealt with.
The warning has been repurposed into a reassurance for the very defect it describes.

**Partial mitigation:** opening the approval *detail* does show `To: mekaghnni@telaverge.com`
in the draft preview, so a careful approver can still catch it. That is F30's full-body
preview doing its job. The list view is where the risk sits.

### Spec basis — INFERENCE, not a violation (checked 2026-08-05)

**This is the one finding in F35–F49 whose expected behaviour no spec sentence mandates.** It is
recorded here so nobody fixing it assumes a contract exists.

Workflows **Workflow 2** step 2 says: *"Vision/OCR reads the card → contacts (name, email, phone,
**needs_review = true if confidence is low**)."* That mechanism **exists and worked correctly**:

- `vision.py:49-51` — `needs_review = confidence < 0.7 or not name`
- `leads.py:365` — `if draft_intro and not scan.needs_review:` — the intro is drafted **only**
  when the scan is confident, and `communication_engine` carries the matching fence, *"Nothing is
  ever sent to an unverified address (Workflow 2)."*

Our scan read **0.86**, so the gate correctly let it through. Nothing in the spec then addresses
what must happen when a human **corrects** a field after a draft is already queued.

**What this does and does not change.** The observation stands exactly as written — the corrected
address reaches the message by no path, and with `EMAIL_MODE=smtp` live a lead working the queue
in good faith would send to a dead mailbox. But the *expected* behaviour is a **product decision**
("a correction must either re-point the draft or be disclosed on the approval card"), not a
contract breach. Treat it like [F54]: decide the intended behaviour first, then implement.

**The sharper, spec-adjacent point is the per-field one this entry already makes.** W2 ties
`needs_review` to a **single overall** confidence, and 0.86 overall concealed that one field of
four was wrong — the one field that decides whether the mail arrives. A per-field confidence, or
simply flagging the email for confirmation, would have prevented this without touching the
correction path at all. That is the cheapest fix and the one least likely to break anything else.

**Not fixed** — the backend is frozen for Round 7. Candidate fixes, cheapest first:

1. `update_contact` re-points any `pending_approval` message whose `to_address` equals the
   contact's previous email. Narrow, but silently rewrites a queued message — and see the
   regression table in [F44] before generalising this to the redraft path, where the same
   idea is **not** safe.
2. Draft the intro **after** the human verifies, not before — moves the write past the gate,
   which is where a verify step belongs. Changes the response contract (`intro_message` would
   no longer be populated by the scan route).
3. Leave the ordering; have the sheet show the draft's address as *live* and warn on
   divergence. Smallest behavioural change, keeps the human deciding — and it composes with
   the disclosure fix recommended in [F44], giving one consistent rule: **the app never
   silently changes a recipient, it shows the divergence.**

Whichever is chosen, the **per-field** point stands separately: an 86% *overall* confidence
told the user nothing about which field was wrong. The one field that was wrong is the one
that decides whether the email arrives. A per-field confidence, or simply flagging the email
for confirmation, would have caught this without any of the above.

## F39 — Recorder pause is one-way: the mic keeps recording while the app says "Paused" ✅ FIXED

Found 2026-08-03, Round 7 Act 3, setting up the first meeting recording. **This is the most
serious finding of the round so far** — it is a consent defect on the consent-gated screen.

`RecorderService.resume()` never publishes a state itself. It delegates to `publish()`, and
`publish()` refuses to run while the status is `PAUSED` — which it always is at that moment:

```java
private void resume() {
    if (recorder == null || current().status != Status.PAUSED) return;
    recorder.resume();                                  // hardware DOES resume
    pausedTotal += SystemClock.elapsedRealtime() - pauseStartedAt;
    publish();                                          // ...and this bails out
}

private void publish() {
    if (recorder == null) return;
    if (current().status == Status.PAUSED) return;      // ← still PAUSED
    STATE.postValue(new State(Status.RECORDING, elapsed(), amplitude, null));
}
```

`STATE` therefore never leaves `PAUSED`, and because the periodic ticker also goes through
`publish()`, it early-returns on every subsequent tick too. **The status is stuck for the rest
of the session.** `Status.RECORDING ⇄ PAUSED` is documented at `RecorderService:45` as a
two-way transition; only one direction works.

**Three consequences, all observed on the device — not inferred.**

> **Read the method note at the end of this entry before reproducing.** The first pass at
> this finding used `uiautomator dump`, which is **unreliable on this screen**. The evidence
> below is from **screenshots**, which are ground truth.

**1. Resume is dead.** Tapping the record button (which `onRecordTapped` correctly maps to
`ACTION_RESUME` when paused) leaves the screen on "Paused" permanently. Screenshot taken
*after* the resume tap shows the timer frozen at **01:33**, the status **"Paused"**, the
centre button still showing the **play** icon (`ic_play`, i.e. `Status.PAUSED`), and the
amplitude bar flat. A further screenshot ~90 s later is byte-for-byte the same state: still
`01:33`, still "Paused".

**2. The microphone is live the whole time.** `recorder.resume()` *did* run — only the state
publication was lost. Sampling the app-private file **while the screen read "Paused"**:

```
t1  1,521,619 bytes
t2  1,571,217      (+49.6 KB / 4 s)
t3  1,619,974      (+48.8 KB / 4 s)
t4  1,668,731      (+48.8 KB / 4 s)     sustained ≈ 12 KB/s
```

Steady growth over 16 s rules out a post-pause buffer flush: the encoder is still consuming
live microphone input. Total file growth across the frozen period was ~150 KB.

This is the part that matters. The recorder screen exists to satisfy DPDP consent — the
consent sheet immediately before it says *"confirm the client agreed to it. This is stored
with the lead"*. A user who taps pause because the client asked them to stop recording, or
because the conversation turned private, is told the recording is paused **while the mic keeps
running**. Anyone in the room reading that screen is being told something false.

**3. The stored duration is the frozen value.** `elapsed()` returns `state.elapsedMs`
unchanged while `PAUSED`, so `stop()` records the pause-moment figure. In the first
occurrence the post-stop panel read **"Recorded 00:26"** for a **2,208,017-byte** file —
roughly three minutes of audio at the observed rate, under-reporting by ~7×. (That reading is
trustworthy despite the dump caveat below: once stopped, the meter no longer animates, so the
window is idle and the dump is accurate. It is also corroborated by the file size.)

**Reproduction (30 seconds, no fixture needed):** open any lead → Meetings → Record meeting →
consent → record → wait a few seconds → tap the button again (pauses) → tap it again
(should resume). The label stays "Paused"; `adb shell run-as com.yuvipep.app ls -l
files/recordings/` shows the file still growing.

**Note: the only escape from `PAUSED` is Stop.** Because resume can never succeed, a paused
session cannot be continued at all — the recording must be stopped and restarted, losing the
take. That is worth remembering during any simulation run: **do not tap pause.**

### ⚠ Method note — `uiautomator dump` is not trustworthy on the recorder screen

This finding was nearly filed with the wrong evidence, and the tooling trap generalises well
beyond it.

The recorder animates an amplitude meter continuously while recording, so the window **never
reaches an idle state**. `uiautomator dump` prints `ERROR: could not get idle state.` (easy to
miss when the command's output is piped away) and then returns a **stale hierarchy** — the
last one it captured while the window *was* idle. On this screen that means:

```
uiautomator dump   →  "00:00 | Tap the mic to start"       (stale, from before recording)
screenshot         →  "01:03 | Recording — the screen can be turned off"   (truth)
```

Both taken at the same instant. The dump was ~63 seconds out of date.

**Why this is dangerous:** the stale value is not random, it is *the state before the
interaction*. So a dump-driven check reliably "confirms" that the last tap did nothing — which
is exactly the shape of a false bug report. It also cuts the other way: when the recorder was
genuinely stuck in `PAUSED`, the window *did* go idle (no animation), so those dumps were
accurate. The tool is right precisely when the app is broken and wrong when it is working,
which is the worst possible failure mode for a diagnostic.

**Rule for future device work:** for any screen with continuous animation — the recorder, the
voice/mic session, the pipeline progress screen — **verify with `screencap` + `pull`, not with
`uiautomator dump`.** And never pipe the dump's stderr away; the idle-state error is the only
warning you get. (Pull the PNG as a file: redirecting `exec-out screencap -p` through
PowerShell corrupts the binary with a BOM.)

This is the same lesson as F37 in a different costume: **the check that reports "nothing
happened" needs its own reach tested**, or it will happily manufacture findings.

**Why no suite caught it:** pause/resume has no instrumentation test, and every earlier live
run (Phase 2's 3:01 take, the 2:47 take in the first simulation) recorded straight through
without ever pausing. The path had never been exercised on a device. It was found here only
because a stale UI dump made me tap the button a second time by accident.

✅ **FIXED 2026-08-06 (tranche 2) — code only, NOT device-verified.** `resume()` posts RECORDING directly instead of through the `publish()` guard, with elapsed computed **inline** (calling `elapsed()` would re-freeze the timer — it branches on `current().status` and `postValue()` is async). Pause button made a toggle; `contentDescription` now becomes "Resume". **The APK was not installed and the app has no test harness** — the device check is: pause, watch the file stop growing, resume, watch the timer move.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — app change, and the APK under test (`0.7.3-f31`) must not be rebuilt
mid-simulation. The fix is one line in `resume()`: post the `RECORDING` state directly rather
than routing through the `publish()` guard, e.g.

```java
STATE.postValue(new State(Status.RECORDING, elapsed(), 0, null));
```

before calling `publish()`. Note `elapsed()` must be called *after* that post, or it will
still take the `PAUSED` branch and return the frozen value.

**Two smaller things noticed alongside, worth folding into the same fix:**
- `pauseButton`'s `content-desc` stays **"Pause"** while paused; it never becomes "Resume".
  Screen-reader users get no signal that the control's meaning has flipped.
- There are two controls bound to pausing (`pauseButton` → `ACTION_PAUSE`, and `recordButton`
  → toggle) but only the toggle can resume. Tapping the dedicated pause button while paused
  does nothing at all.

**Verified working in the same screen** (so the fix should not disturb them): consent gate
records method + note before the recorder opens; Stop produces a correct post-stop panel;
Discard asks for confirmation and genuinely deletes the file (`ls files/recordings/` returned
empty afterwards).

## F40 — The consent record attached to a meeting states a method that never happened ✅ FIXED

Found 2026-08-04, Round 7 Act 3, on the real `meeting1` recording.

The app asks how consent was obtained — *"They agreed verbally / in writing / captured in
app"* — plus a free-text note, and stores that honestly against the lead via
`POST /leads/{id}/consent`. The upload endpoint then **ignores it and writes a second,
contradictory record**, which is the one linked to the meeting
(`app/api/meetings.py:100-105`):

```python
db.add(
    ConsentRecord(
        org_id=ctx.org_id, lead_id=lead_id, meeting_id=meeting.id,
        method="in_app", note="Confirmed at upload", captured_by=ctx.user_id,
    )
)
```

`method` and `note` are **hardcoded**. Nothing reads the record the user just created, and
nothing reconciles the two.

**Observed on the device.** The recorder's consent sheet was completed with *"They agreed
verbally"* and the note *"Principal Nair and team agreed verbally"*. Both rows are in
`consent_records` for the Orchid lead:

```
20:26:32   method='verbal'   note='Principal Nair and team agreed verbally'   meeting_id=NULL
20:32:51   method='in_app'   note='Confirmed at upload'                       meeting_id=e5e732cf…
```

The truthful record is **not** the one attached to the meeting. Anyone auditing consent for
that recording — which is the entire point of storing it — reads *"in_app / Confirmed at
upload"*. In fact the client agreed **verbally**, and no one confirmed anything in-app at
upload time; tapping **Upload** is not a consent interaction.

**Why this matters more than a mislabelled column.** The consent sheet's own text is
*"Before recording, confirm the client agreed to it. This is stored with the lead (DPDP)."*
The app promises that what you record is what gets stored. For the meeting-linked record, it
is not — and the fabricated value is the more defensible-sounding one ("captured in app"),
which is precisely the direction an audit trail must never drift.

**A second, related gap.** `consent_confirmed: bool` (`meetings.py:59,72-75`) is a
**self-asserted flag from the caller**, not a check that a consent record exists. The endpoint
rejects `false` but never verifies the claim, then manufactures a record asserting consent was
captured. So the DPDP gate is enforced by the *app*, while the *API* both trusts the caller
and generates the evidence. Any direct API call with `consent_confirmed=true` produces a
complete-looking consent trail for a recording nobody ever consented to.

### Spec basis — VIOLATION (Data Model §3.5 `consent_records`)

The table's own definition makes this a contract breach, not a mislabelled column:

> *"One row = **proof** that the other side was told about recording and agreed, captured
> **before** the recording started. This is a **legal-protection table** (data-protection law
> alignment): rows are written at the start of every recorded meeting and **never edited**."*

and the field itself: **`method`** = *"**How consent was captured**: `verbal` (stated on tape) /
`written` / `in_app`."*

Two clauses break at once. `method` is hardcoded, so a legal-protection row asserts a capture
method that **did not happen** — and `verbal` *("stated on tape")* is precisely what did. And the
meeting-linked row is written **at upload**, i.e. *after* the recording, not "before the recording
started". The truthful row the app created before recording exists; it is simply not the one
attached to the meeting.

✅ **FIXED & verified 2026-08-06 (tranche 2).** Upload now **links** the consent the human captured and **refuses** when none exists (closing the self-asserted-flag gap), with a 24h staleness window. 8 upload call sites in tests/scripts now capture consent first. 3 tests.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. The fix is small and does not change the contract: accept the
method/note on the upload (or look up the lead's most recent consent record) and link **that**
to the meeting rather than inventing one. If no consent record exists, that is the moment to
refuse — which would close the second gap at the same time.

**Related to F39** in kind, not mechanism: both are places where the recorder tells a
confident story about consent that the underlying state does not support.

## F41 — People identified in a first meeting never become contacts or stakeholders ✅ FIXED

Found 2026-08-04, Round 7 Acts 3–5, from the real `meeting1` recording.

The transcript names three client people and states each one's role explicitly:

> *"I am Mrs. Nair, the principal. I will be taking the final decision on this program."*
> *"I am Arjan, the science coordinator. I will be your main point of contact…"*
> *"I am Divya from the admin office. I will help you with scheduling and access…"*

The model read all three correctly — they appear verbatim in `client_intelligence` ("Mrs. Nair
is taking the final decision on the program", "Arjan is the main point of contact for
day-to-day work"). But they are stored **only as free-text notes**. After a full
transcribe → extract → review → plan cycle:

> ## ✅ CAUSE ESTABLISHED — 2026-08-04, Act 10. **Pure wiring gap on the create path.**
>
> The Act 10 test below was run and is decisive. `meeting2.wav` — which goes through
> `merge_meeting_llm`, the path that *does* call `sync_stakeholder_specs` — produced:
>
> ```
> Mr. Rao   Trustee   source=meeting      ← contact created automatically
> stakeholders: 1
>    - Mr. Rao   role_at_client=trustee   influence=decision_maker
> ```
>
> **The model does populate `stakeholders`.** Candidate B (extraction putting people only into
> `new_facts`) is **ruled out**. The role came through in the client's own vocabulary
> (`trustee`), and `decision_maker` was correctly inferred from *"Mr. Rao (trustee) will
> approve the final budget"*. This is also the **first row ever written with
> `source='meeting'`** — the enum value that had 0 rows before.
>
> Same org, same lead, same extraction contract, same model — **the only difference is which
> code path ran**. Meeting 1 created nobody; meeting 2 created Rao. The fix is to call the
> contact-creating half on the create path too (see the trap in *"Fix"* below — the obvious
> version double-creates stakeholders).

```
contacts on Orchid : 0
stakeholders       : 0   (zero org-wide)
client_commitments : 11  — promised_to empty: 11,  promised_by empty: 11
```

**Cause** (`app/engines/planner_engine.py:1330-1353`): stakeholder creation iterates the
lead's **contacts**, and uses the model's `stakeholder_specs` only to *enrich* a contact that
already exists:

```python
contacts = (await db.execute(select(Contact).where(Contact.lead_id == lead.id))).scalars().all()
specs = stakeholder_specs or []
for c in contacts:
    spec = _match_stakeholder_spec(specs, c.name) or {}
    stakeholder = Stakeholder(..., role_at_client=spec.get("role") or norm_role(c.title) or "other", ...)
```

With no contacts the loop body never executes, so the model's people data is discarded
entirely. `primary_stakeholder` then falls through to `None` (`:1354-1357`), which is why all
11 commitments carry no holder.

**Why the ordering is backwards.** This is the *first* meeting — the moment you learn who
these people are. Gating people-discovery on contacts already existing means the system can
only recognise people you had already entered by hand, which is precisely the case where
discovery adds nothing.

### The spec already mandates the behaviour — this is a violation, not a design question

Both halves are written into `YuviPep_Data_Model.md`, the source of truth for this project:

**§3.3 `contacts`** — *"Created from a business-card scan, **from a meeting**, or typed by
hand."* The `source` field is a three-value choice: `card` / `manual` / **`meeting`**
("mentioned in a meeting").

**§3.4 `stakeholders`** — *"**Created by the Planner Engine when meetings reveal who is
who**; edited by the sales owner."* No qualification: not "from the second meeting onward",
not "when contacts already exist".

So creating people from a first meeting is not an enhancement — it is the documented contract,
and the schema carries a dedicated enum value for it.

**The enum value has never been used.** Across the whole database after a full first-meeting
cycle:

```
contacts by source:   manual: 13,   card: 1,   meeting: 0
```

and exactly **one line in the entire codebase** writes it — `planner_engine.py:1227`, inside
`sync_stakeholder_specs`, the function the create path does not call. The third documented
route into `contacts` has a single implementation and it is unreachable from a first meeting.

### Candidate A — a wiring gap, not a missing feature: the function already exists

The correct behaviour is **already implemented**, in the same file
(`planner_engine.py:1194-1233`):

```python
async def sync_stakeholder_specs(db, *, org_id, project, specs) -> list[str]:
    """Apply model-discovered client-side people to a live project (Data
    Model §3.4: 'Created by the Planner Engine when meetings reveal who is
    who'). Additive only: creates missing contacts (source=meeting, no
    address — nothing can ever be sent to them until a human records one)
    and missing stakeholder rows, and fills EMPTY fields on existing rows..."""
```

It does exactly what F41 asks for, including the careful part: it creates the contact
**without an address**, because a transcript never contains one.

**It is simply not called on the first-meeting path.** Its callers are:

| Caller | Path | Discovers people? |
|---|---|---|
| `merge_meeting_llm` (`:1574` → `:1606`) | **second and later** meetings | ✅ yes |
| `inbound_engine.py:427` | inbound client email | ✅ yes |
| `_create_project_shell` (`:1280` → `:1330`) | **the first meeting** | ❌ no — contacts-only loop |

So the system discovers people from meeting 2 onward, and from emails, but not from the
meeting that creates the project. The comment at the merge site even states the intended
contract:

> *"People the meeting revealed are synced regardless of what the plan does — the Planner,
> not a human, keeps the stakeholder map current."*

The create path violates that contract.

**Fix — and a trap in the obvious version of it.** My first write-up said "call
`sync_stakeholder_specs` before the existing contacts loop, so the loop then finds them".
**That would be a bug.** `sync_stakeholder_specs` creates *both* contacts and `Stakeholder`
rows (`:1236-1250`, guarded by a `by_contact` map so it is idempotent), whereas the create
path's loop (`:1336-1348`) creates a `Stakeholder` for **every** contact with **no existence
check at all**. Running them in sequence would produce **two stakeholder rows per contact**.

The two also differ in their defaults, so swapping one for the other is not neutral either:

| | `_create_project_shell` loop | `sync_stakeholder_specs` |
|---|---|---|
| `influence` default | `decision_maker` if `c.is_primary`, else `influencer` | always `influencer` |
| `receives_progress_updates` | `spec` **or** `c.is_primary` | `bool(spec)` only |

Replacing the loop with `sync_stakeholder_specs` would silently drop the "primary contact is
the decision maker" rule that `primary_stakeholder` (`:1352-1357`) depends on.

**The minimal safe fix** is to reuse only the *contact-creating* half: before the loop, create
a `Contact` (no address, `source="meeting"`) for each spec with no name match, exactly as
`sync_stakeholder_specs:1223-1231` does. The existing loop then runs unchanged over a complete
contact list, keeps its own defaults, and no stakeholder is created twice. Factoring that
contact-creation block out of `sync_stakeholder_specs` so both paths share it is the tidy
version.

**Regression to check when it is fixed:** any test asserting a stakeholder count for a
project created from a meeting, and `primary_stakeholder` still resolving to the primary
contact.

### Which cause is it? — candidate B, and how to tell them apart

**Candidate A — the wiring gap above.** Proven to exist by reading the code: specs for a
person with no matching contact are discarded on the create path. Real regardless.

**Candidate B — the extraction may never have returned any people.** The initial-plan contract
(`app/ai/planning.py`) makes this entirely possible without the model misbehaving:

- `new_facts` is described as *"reusable facts about this client worth remembering
  (constraints, preferences, infrastructure, **names**)"* (`:468-469`) — it **explicitly
  solicits names**.
- `stakeholders` is described separately (`:470-476`), but is **not in the schema's
  `required` list**, which is only `["concrete", "summary", "tasks"]` (`:498`).

So a model that puts *"Mrs. Nair is taking the final decision on the program"* into `new_facts`
and returns `stakeholders: []` has **satisfied the contract exactly**. And that prose is
precisely what we observe in `client_intelligence`. The prompt asks for people in two places
and requires them in neither.

**The decisive test — Act 10. RUN 2026-08-04. Candidate A confirmed, Candidate B ruled out.**

`meeting2.wav` goes through `merge_meeting_llm`, which *does* call `sync_stakeholder_specs`.
Before and after, same lead:

```
                    after meeting 1        after meeting 2
contacts                  3                      4        ← Mr. Rao, source=meeting
   (all source=manual — typed in by hand)
stakeholders              0                      1        ← Mr. Rao, trustee, decision_maker
```

So the extraction **does** return people; only the create path discards them. Candidate B is
dead. The `new_facts` "names" ambiguity noted below is still an untidy contract, but it is
**not** the cause here and fixing it alone would achieve nothing.

**Residual note on the contract (not the bug):** `new_facts` still solicits "names" and
`stakeholders` is still absent from `required`, so a model *could* legitimately return no
people. Tightening that is defensive hygiene, not the fix.

**Consequences, all observed:**

1. **The project has no stakeholders.** "Who receives progress updates" is empty, so W14-style
   client-visible updates have no addressee.
2. **Nothing can be emailed.** `resolve_contact` (`app/ai/agents/resolvers.py:406-407`) raises
   `NotFoundError("No contacts saved for … yet")` on zero contacts, and
   `demo_invite_service:39-42` returns `None`. Acts 7–9 of the simulation cannot address
   anyone at Orchid without a human adding a contact by hand.
3. **The commitment register records no people.** All 11 rows have empty `promised_to` and
   `promised_by`, even though the transcript states who promised each one — including the two
   correctly marked `direction='theirs'` ("I will book the science lab" — Arjun; "I will share
   the full student list" — Mrs. Nair). The register knows *what* was promised and *by which
   side*, but not *by whom*.

   This is a **direct** consequence, not a coincidence: `promised_to` is defaulted from
   `primary_stakeholder` (`planner_engine.py:1431`, `:1532`), which is `None` precisely
   because the stakeholder loop never ran.

4. **A scheduled job silently no-ops because of it.** `sync_engine._sweep_commitments`
   (`:1013`) is what chases client-side promises — it notifies the owning assignee that *"Client
   promise due tomorrow"* and marks overdue ones `BROKEN`. For commitments held by the client
   it resolves the person via `promised_by` (`:1061-1068`) and, finding nothing, hits
   `continue` and skips the row entirely. So the two `direction='theirs'` commitments — the
   student list and the science lab, both real dependencies for the 15 August start — will
   never be chased. Nothing logs a warning; the sweep simply passes over them.

**This is the concrete answer to "how does the system know where to send mail?"** — for a lead
whose people came from a meeting rather than from a card scan or manual entry, it does not.

**4. Adding the contacts by hand afterwards does NOT repair it.** This is the part that turns
an ordering quirk into a real defect. The stakeholder loop runs **once**, inside project
creation. Having found the gap, all three people were added through the app — Mrs. Nair
(Principal, primary), Arjun (Science coordinator), Divya (Admin office), each with a working
address. The project did not pick them up:

```
                    before adding    after adding
contacts on Orchid        0                3
stakeholders              0                0     ← unchanged
commitments ownerless    11               11     ← unchanged
```

So a user who does exactly the right thing — enters the people they just met — still has a
project with **no stakeholders** and a commitment register with **no owners**, and no UI path
that rebuilds either. The damage is permanent for the life of that project unless the plan is
regenerated. Any fix must therefore also backfill on contact creation, not merely create
contacts earlier.

✅ **FIXED & verified 2026-08-05 (tranche 1).** Contact creation factored out as `ensure_contacts_for_specs`, shared by both paths; neither documented trap hit (no double-creation; `is_primary → decision_maker` preserved); consequence #4 fixed by `backfill_stakeholders_for_contact`. 7 tests, falsified on both halves.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. The natural fix is to create contacts (flagged
`needs_review`, exactly as the card scanner does) from `stakeholder_specs` when the model has
named a person and a role, then let the existing loop build stakeholders from them. Note it
must **not** invent contact details: a transcript yields a name and a role, never an email, so
the contact should be created without one and the app should ask for it at the point of first
use. Populating `promised_to`/`promised_by` falls out of the same change.

**Verified working alongside it, and worth not losing:** the planner's
`direction='ours' | 'theirs'` classification was **correct on all 11 commitments**, and when a
gate-dropped item was re-derived it came back correctly reframed from our side ("Share student
list and class timetable", dropped → "Receive student list and timetable", kept). The
*semantics* are right; only the people are missing.

## F42 — The commitment register stores raw sentence fragments, and duplicates one ✅ FIXED

✅ **INVESTIGATED AND MOSTLY NOT A BUG — 2026-08-06, at the owner's request.** **The 'structural double-count' is CORRECT behaviour.** The two 'duplicate' rows link to two genuinely different tasks — *Procure 40 maker kits* (due 23 Aug) and *Deliver 40 maker kits to school* (due 28 Aug). The client said *"the procurement **and** delivery of the 40 maker kits"*: that is **two deliverables with two deadlines**, and the sweep must chase each against its own task. Collapsing them would give one deadline for two deliverables and make 'kept' undecidable until both finished — strictly worse for the chasing §4.5 exists for. **Two further corrections to this entry:** the schema does **not** enforce 1:1 (`linked_action_item_id` and `client_commitment_id` are plain nullable columns, no unique constraint), so 'the code followed the schema' overstates it; and **§4.5 is satisfied, not contradicted** — procuring is one promise, delivering is another, and they arrived in one sentence, which is a fact about English rather than about promises. **The claimed SPEC SELF-CONTRADICTION dissolves and needs no decision from anyone.** **The real defect was only the TEXT**, and it is fixed: rows stored raw clause fragments, and because the two kit rows carried the *same* fragment, correct two-row behaviour merely LOOKED like duplication. This reaches clients — the weekly report renders `- {c.text} (by {date})`, so a client would have read the same half-sentence twice. The prompt now requires a self-contained, task-specific sentence. **Verified live 6/6**: the register now reads *"We will share our compliance certificate before the training starts."*

Found 2026-08-04, Round 7 Act 5, alongside [F41]. Two defects in the same 11 rows.

**1. One promise is recorded as two commitments — and the data model requires it to be.**
The planner correctly split *"the procurement and delivery of the 40 maker kits"* into two
tasks (procure, deliver). Each carried the same commitment text:

```
"and the procurement and delivery of the 40 maker kits."   due 2026-08-23 → Procure 40 maker kits
"and the procurement and delivery of the 40 maker kits."   due 2026-08-28 → Deliver 40 maker kits to school
```

**This is structural, not a slip.** A commitment is a *sub-object of a task spec* —
`commitment: {text, due_in_days, direction, promised_to}` per task
(`planner_engine.py:130-136`) — created inside the per-task loop at `:334-336`, and the schema
links them **1:1** in both directions (`ClientCommitment.linked_action_item_id`,
`ActionItem.client_commitment_id`). A single promise that legitimately becomes two tasks
therefore *cannot* be represented as one commitment.

So the register double-counts whenever the planner splits a promise — which it is right to do.
**Do not "fix" this by de-duplicating on text**: that would break the 1:1 linkage both models
depend on. The real options are to instruct the model to attach the commitment to only one of
the derived tasks, to de-duplicate at *read* time when rendering the register, or to make the
link many-to-many.

**2. The stored text is a raw clause, not a commitment.** Several rows begin mid-sentence
because the extractor slices the transcript rather than restating the promise:

```
"and develop all the hands-on worksheets and materials."
"and the procurement and delivery of the 40 maker kits."
"On our operations side we will coordinate the logistics, that is the lab space"
```

Three of eleven start with "and" or trail off unterminated. This is the record of what was
promised to a client — it is shown in reviews and is the natural source for a
confirmation email — so fragments beginning with a conjunction read as sloppy at best and
ambiguous at worst ("and the procurement and delivery" of *what*, to a reader who lacks the
preceding sentence).

**Note this is not the ASR's fault** — the transcript itself is clean and well-punctuated
(confidence 0.857). The fragmenting happens at extraction.

### ⚠️ Spec basis — the SPEC CONTRADICTS ITSELF here. Resolve that before fixing.

This entry says the duplication is required by the data model. **That is correct, and it puts the
spec at odds with its own prose** — which whoever fixes this must settle first.

Data Model **§4.5** opens: *"**One row = one promise** — in either direction."*

But the same spec defines the link as **1:1 in both directions**:
- `client_commitments.linked_action_item_id` — *"**The internal task** that fulfils it (for
  `ours`). Completing the task is what keeps the promise."*
- `action_items.client_commitment_id` — *"The promise to the school **this task** fulfils, if
  any."*

A promise that legitimately becomes **two** tasks (procure + deliver) therefore **cannot** be one
row without breaking the link, and cannot keep the link without breaking "one row = one promise".
The implementation followed the schema.

**So this is not "the code violates the spec" — it is "the spec cannot be satisfied as written".**
The decision is which half gives way: make the link many-to-many (keeps one row per promise), or
attach the commitment to a single derived task (keeps 1:1, accepts that the sibling task carries
none). **De-duplicating at read time is now clearly the wrong answer** — it would leave the stored
data contradicting §4.5 and merely hide it from view.

**Not fixed** — backend frozen. The text half is an extraction-prompt issue: the plan
contract (`planner_engine.py:130-136`) specifies `commitment: {text, …}` with **no requirement
that `text` be a complete restatement**, so the model quotes a span. Asking for a self-contained
sentence costs nothing. The duplication half is **not** a prompt fix — see above.

## F43 — "What's blocking?" says nothing is blocking while the whole plan is frozen ✅ FIXED

Found 2026-08-04, Round 7 Act 5.

Immediately after the first meeting the project was in exactly this state:

- project `status = planning`, plan v1 `status = pending_review`
- an **approval pending** on `plan_change`, routed to the sales lead
- **10 tasks frozen in `pending_review`** — nothing staffed, `assignments` table empty
- no work could begin at all until that one approval was decided

The project home's **What's blocking?** answered:

> *"Nothing is blocking Orchid International School - IBC STEM Program — health is on_track."*

**This is deterministic, not a model wobble** (`app/engines/assistant_engine.py:486-506`). The
function considers exactly two things:

```python
blocked  = ActionItem.blocked.is_(True)   AND status IN OPEN_STATUSES
overdue  = ActionItem.due_date < utcnow() AND status IN OPEN_STATUSES
if not blocked and not overdue:
    return f"Nothing is blocking {project.name} — health is {project.health}."
```

and `OPEN_STATUSES = (OPEN, IN_PROGRESS)` (`:44`). So:

1. **Pending approvals are not consulted at all** — not the plan approval, not any other.
2. **`pending_review` is not in `OPEN_STATUSES`**, so the ten frozen tasks were not merely
   judged unblocking, they were never examined.

The single largest blocker a project can have — its plan awaiting sign-off, with every task
unstaffed behind it — is structurally invisible to the feature whose entire job is to name
blockers. And it is the sales lead, the very person the approval is waiting on, who is most
likely to open that project and be told nothing is blocking it.

**Reproduction:** record a meeting → confirm the review gate → open the project **before**
approving the plan → tap *What's blocking?*. Deterministic, so it reproduces every time.

### Spec basis — SUPPORTING, not a mandate (read this before citing it)

Workflows **§4 "The Ten AI Engines"** describes the **Assistant Engine** as one that *"answers
questions across **everything** in plain language (**"what is blocking the SVS bootcamp?"**)"* —
the spec's canonical example is this finding's exact question.

**But note precisely what that does and does not license.** It describes the **Assistant**, which
in practice *does* answer well (see the Act 14 voice result). F43 is about the **project screen's
own separate deterministic implementation**. No spec sentence says that screen must consult
approvals and conflicts.

**So the citation supports F43's recommended fix rather than proving a violation:** the spec
recognises one place where this question is answered "across everything", and the project screen
is a second implementation that answers it worse. That is the argument for making the screen
reuse an answer that already exists — the assistant path, or `recompute_health`'s reason string —
instead of growing a third rule set.

✅ **FIXED & verified 2026-08-06 (tranche 2).** `sync_engine.health_signals` extracted and **shared**, so the assistant and the Delivery card cannot disagree again; pending approvals added to `whats_blocking` only, never to health. A held re-plan now outranks any single late task. 6 tests.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. The fix is additive and needs no schema change: query pending
`approvals` for the project and, when any exist, name them ("waiting on <role> to approve
plan v1 — 10 tasks are unstaffed until then"). Including `PENDING_REVIEW` in the statuses this
function examines would be a second, smaller improvement.

**Note on health:** `health = on_track` is a separate stored field and is not itself wrong —
the defect is that the blocking answer treats an unapproved plan as an unblocked one.

### Supporting observation — the same product answers this question twice, very differently

Re-checked after the plan was approved and all tasks were `open`, so the approval issue above
no longer applies. Same project, same data, minutes apart:

| Where | Answer |
|---|---|
| Project screen → **What's blocking?** | *"Nothing is blocking Orchid International School - IBC STEM Program — health is on_track."* |
| Jarvis → `whats blocking orchid` | **Four** items: pilot date not finalised (due 10 Aug), student list not received (7 Aug), demo dates not sent (7 Aug), proposal not sent to Mrs. Nair (7 Aug) |

**Stated fairly, these are not strictly contradictory.** The project screen answers "is anything
*flagged* blocked or overdue?" — and nothing is: no task carries `blocked=True`, and the 7 Aug
due dates had not passed. Jarvis answers "what is standing between this project and progress?"
and reasons over the actual work.

The point is not that one is lying. It is that **the deterministic version is nearly useless
for the question users actually ask**, and a far better answer already exists elsewhere in the
same product. Whoever fixes F43 should consider whether the project screen should simply call
the assistant path rather than grow its own second-rate rules.

### Third observation (Act 11) — it misses **open conflicts**, which literally hold the plan

After meeting 3 the project had **four open `conflicts`**, and plan v5 sat in `draft` with
`held_plan_id` pointing at it: no re-plan can proceed until a human resolves the client's
internal disagreement. That is the single most blocking state this product can be in.

**What's blocking?** answered with **sixteen OVERDUE lines** and did not mention the conflicts
at all:

```
Blocking Orchid International School - IBC STEM Program:
- OVERDUE: Send two pilot demo dates this week (due 03 Aug)
- OVERDUE: Send full proposal to Mrs. Nair by Friday (due 03 Aug)
… 14 more …
```

So the failure mode inverts but does not improve: earlier it was **silently empty**, now it is
**noisily wrong**. The reader is buried in overdue rows — several of them overdue only because
of a date shift the client requested — while the fact that *the client's trustee and
coordinator contradict each other on scope, dates and audience, and the plan is frozen because
of it* appears nowhere.

This strengthens the fix recommendation: `whats_blocking` should consult **pending approvals
and open conflicts first**, and mention held plans explicitly, before it enumerates overdue
tasks. Sorting by "what stops work" rather than "what has a past date" is the whole job.

**The daily briefing has the same blind spot** (same file). It renders *"Approvals waiting on
you"*, follow-ups, replies-that-came-in and overdue — and `assistant_engine.py` contains
**no reference to conflicts anywhere**. So on the morning after meeting 3, the sales lead's
briefing listed six approvals and said nothing about the four conflicts freezing the plan.

**Net effect on discoverability.** A conflict is surfaced in exactly two places:
a bell notification (*"Two sources said different things"*) and the project's **Conflicts**
tab — which is tab **7 of 8** and only reachable by scrolling the tab strip sideways. It is
absent from both summary surfaces a lead actually reads each morning. **The conflict feature
itself is complete and works well** (see the Verified-working section); this is purely about
where it is announced.

## F44 — Drafts carry a `Subject:` line inside the body, and replies have no subject at all ✅ FIXED

Found 2026-08-04, Round 7 Act 5; **scope substantially widened in Act 9** — the first write-up
framed this as a redraft-only defect. It is not. Two mechanisms combine, and the second is
worse than the first.

### Widened evidence — every pending draft on the system

```
kind    subject field                    first line of body
─────────────────────────────────────────────────────────────────────────────────
intro   "Great meeting you — YuviPep"    Subject: Updated contact email
reply    None                            Subject: Re: Content Change Request
reply    None                            Subject: Scope Expansion Amendment — Addition Included
```

Three for three. The model reliably writes a subject; it reliably lands in the body as literal
text; nothing ever strips it. And for **replies the subject field is null**, so if approved the
client receives an email with **no subject** whose body opens `Subject: Re: Content Change
Request`.

### Mechanism 2 — why replies have no subject

Every reply call site in `inbound_engine` (`:557, 692, 778, 874, 1081, 1338`) derives it from
the inbound message:

```python
subject=f"Re: {msg.subject}" if msg.subject else None,
```

The app's **Log a client reply** sheet labels Subject *"(optional)"* — correctly, since a phone
call or WhatsApp message has none. Leave it blank, as any user logging a call would, and
`msg.subject` is `None`, so **every** generated reply is subjectless. There is no fallback to
the thread, the project, or the client name.

So the model's perfectly good subject exists — in the wrong field — while the right field is
empty. The two halves of the bug are looking straight at each other.

### Mechanism 1 — the redraft path (the original finding)

`redraft_after_rejection` (`app/engines/communication_engine.py:429-447`) builds the new
message by copying every field except one:

```python
redraft = OutboundMessage(
    ...
    contact_id  = message.contact_id,     # the contact IS carried over
    to_address  = message.to_address,     # ← copied verbatim
    subject     = message.subject,        # ← copied verbatim
    body        = body,                   # ← the only field the note can affect
)
```

But the note the approver writes is **free text**, and nothing constrains it to body-only
concerns. A rejection is exactly when a human says "wrong recipient" or "change the subject" —
and neither is representable. The instruction is handed to the model, the model does the only
thing it can, and the correction ends up as prose inside the body.

**Observed.** The intro was rejected with:

> *"Wrong email address - OCR read mekaghnni instead of mekaghni. Contact is corrected now."*

The redraft that came back:

```
to_address : mekaghnni@telaverge.com          ← unchanged (the F38 defect)
subject    : Great meeting you — YuviPep      ← unchanged
body       : "Subject: Updated contact email
              Dear EKAGHNI MUKHERJEE,
              It was a pleasure meeting you at Telaverge today. …"
```

The model understood that something about the email needed to change, could not reach the
subject field, and **emitted an email header into the body**. If approved, the recipient gets
a message whose real subject is *"Great meeting you — YuviPep"* and whose first line of text
reads *"Subject: Updated contact email"* — visibly malformed, and about a topic the rest of
the message never mentions.

**Two distinct problems, one cause:**

1. **Silent mis-application.** An instruction about the recipient or subject is neither applied
   nor refused. Nothing tells the approver their correction could not be honoured — the
   approval card cheerfully reports *"note applied"*. This is the F28 rule in a new place:
   the system should say "I can't change the recipient here" rather than quietly do something
   else.
2. **Header text in the body.** Whatever the instruction, a body that begins `Subject: …` is
   malformed for an email that already has a subject. The redraft prompt permits it and
   nothing strips or detects it.

✅ **FIXED & verified 2026-08-06 (tranche 2).** A leading `Subject:` line is **promoted** into the subject field (both draft and redraft paths); `reply_subject()` replaces the identical expression at all six sites. Mid-body "Subject:" deliberately untouched. 10 tests.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen.

**⚠ "Just re-resolve `to_address` from `contact_id`" is NOT a safe fix.** That was my first
recommendation here and in [F38]; checking the callers shows it would break three cases:

| Case | Why re-resolving breaks it |
|---|---|
| **WhatsApp / non-email channels** | `communication_engine.py:261` sets `to_address = contact.email if channel == EMAIL else contact.phone`. Blindly re-resolving to an email would corrupt every WhatsApp redraft |
| **Explicitly typed recipient** | `proposal_agent.py:268-270` honours a literal address when the user says "email it to finance@…", and never resolves a contact at all. Re-resolving would silently override an instruction the human gave on purpose |
| **Messages with no contact at all** | `proposal_email_service.py:94-108` calls `create_message` **without `contact_id`**, so proposal emails have none. There is nothing to re-resolve from |

A safe fix must therefore be conditional: only when the message **has** a `contact_id`, only
when the channel's address type matches, and only when the stored address equals the contact's
*previous* value (i.e. it was never hand-edited).

**The better fix given this product's principles is not to rewrite at all, but to disclose.**
Silently changing a recipient behind an approver's back is the same class of move the app
elsewhere refuses to make. Since `redraft_rejected` **already loads the contact**
(`communication_engine.py:400-404`) for the compose, it can cheaply compare and surface a
divergence — "this draft goes to `mekaghnni@…`; the contact is now `mekaghni@…`" — on the
approval card, leaving the decision with the human. That closes the dangerous half of [F38]
(an approver unable to see the problem) without any of the three regressions above.

For the body/subject half — now the larger half:

1. **Persist the model's subject instead of stranding it.** The composer already produces one;
   parse a leading `Subject:` line out of the body and write it to the `subject` column.
2. **Strip or reject any remaining `Subject:` line in a body.** This is a deterministic fence
   of the same kind as `draft_check`, and it belongs next to it.
3. **Give replies a subject fallback** when the inbound had none — the thread's subject, or
   `Re: <project name>`. `subject=… if msg.subject else None` is the single line responsible,
   repeated at six call sites in `inbound_engine`.

Items 2 and 3 are independent of the redraft question and fix the more common case: a user
logging a phone call, which is exactly what "Log a client reply" is for.

## F45 — "Who is doing X" silently answers from the client side, not the assignee ✅ FIXED

Found 2026-08-04, Round 7 Act 6. **F28 itself does not regress** — nothing threw a lookup
error, every question was answered. This is the *other* half of the standing rule: it
**silently guessed**, and guessed wrong.

Two phrasings of the same question, same session, same `About: Orchid International School`
context chip, minutes apart:

| Asked | Answered |
|---|---|
| `who is doing the curriculum` | *"the **curriculum** … is being driven by **Arjun**, the **Science coordinator**"* ❌ |
| `who is assigned to the curriculum task` | *"assigned to **Baski** ('Design workshop curriculum for grades 6–8')"* ✅ |

Ground truth:

```
Baski   open   Design workshop curriculum for grades 6-8
               reason: "Baski: expert skill match, 0/8 open tasks"
```

Arjun is the **client's** science coordinator — a contact on the lead, not a person who can be
given work. Baski is our operations agent, holding an assignment with a recorded reason.

**The retrieval is not broken** — the second phrasing proves the agent reaches the assignment
fine. The bare phrasing resolves "who is doing" against client stakeholder/contact data and
returns that instead, with no hedge and no indication a choice was made.

**Why it matters more than a wording quibble.** A rep asking "who is doing the curriculum"
wants to know who to chase. Being told the *client's* coordinator owns it inverts
responsibility for a deliverable: the rep stops chasing internally and waits on a client who
was never asked. It is also the exact shape of question the terse-command rule exists for.

**Per the standing rule** ([jarvis-natural-language-f28]): short or ambiguous commands must be
**resolved, or asked about** — "my understanding is X, shall I proceed?" — and **never
silently guessed**. Here the correct behaviour was either to answer from the assignment (the
only structured, authoritative record) or to ask "do you mean on our side or theirs?".

### Spec basis — VIOLATION (Workflows §4, "Three rules stand above all ten engines", rule 3)

> *"3. **When the AI is unsure, it asks — it never guesses.** Low confidence, **conflicting
> sources**, unmatched messages, and missing knowledge all route to a named human with the
> context attached."*

The rule is explicitly stated to stand **above all ten engines**, so it binds the Assistant
Engine. "Who is doing the curriculum" has two candidate readings — our assignee and the client's
coordinator — which is a conflicting-sources case by any reading. The assistant picked one
**silently, with no hedge**. That is the guess the rule forbids.

This also settles that the standing terse-command rule is **not merely a user preference**: it is
written into the spec. The same sentence covers [F46] and [F57].

✅ **FIXED 2026-08-06 (tranche 2) — prompt + data; live phrasing not re-verified.** The query agent is told "who is doing/owns/handling" means our assignee, and that falling back to client-side people must be said out loud.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. Scope "who is doing / who owns / who is handling" to task
assignments first, and fall back to client stakeholders only when no assignment exists —
saying so when it does.

## F46 — "Why did you pick X" explains the chat, not the assignment engine's recorded reason ✅ FIXED

Found 2026-08-04, Round 7 Act 6.

> **Method note — read this before citing the finding.** My first test of this asked
> `why did you pick sourav` when the assistant had never mentioned Sourav in the conversation.
> It replied *"I didn't pick Sourav … if you mean a different 'Sourav' task, tell me which"* —
> which, reading "you" as *"you, in this conversation"*, is **true and appropriately
> hedged**, and is the F28-compliant shape. I initially wrote that up as the assistant denying
> a database fact. **That was an unfair test and an overstated finding.** The finding below
> rests on a fair re-test asking about a name the assistant *had* used.

Asked `why did you pick baski` — a name the assistant had itself put forward twice:

> *"Because I looked up the Orchid-specific task for the curriculum/workshop work, and its
> **assignee is Baski**. That's why I **mentioned** Baski as the person responsible for the
> curriculum task."*

It explains **why it said Baski in the chat**. The question a user is asking in a staffing
context is why *Baski was staffed*, and that has a recorded answer:

```
to     : Baski
task   : Design workshop curriculum for grades 6-8
reason : "Baski: expert skill match, 0/8 open tasks — tie; lead should confirm or change"
```

**The dropped clause is the important part.** The assignment engine explicitly flagged this
one as a **tie** and said *the lead should confirm or change it*. That caveat is exactly what
"why did you pick Baski" should surface — it is the difference between a confident staffing
decision and one the system itself wants reviewed. The answer conveyed none of it, and instead
implied a clean lookup.

### Root cause — no agent can reach the reasoning, whichever one is chosen

My first two attempts at this entry blamed routing. **That is a symptom, not the cause.**
Reading the agent layer properly:

1. **`why_trace` is not a tool.** `assistant_engine.why_trace` (`:516`) — documented as
   *"'Why did the AI do that?' — inputs, decision, reason, confidence, overrides"* — has
   exactly one caller in the whole codebase: `app/api/workflow.py:835`, the REST endpoint
   behind the app's **"Why?" chip**. No agent exposes it in `tools()`.
2. **The assignment reason is not in any agent's view.** The query agent's task shape
   (`query_agent._item_dict:22-34`) carries `id, title, status, priority, owner, client,
   due_date, description` — **`owner` but never the reason**. `_client_details:240` returns
   contacts (name/title/email/phone) and proposals. Nothing anywhere returns
   `assignments.reason` or an `AIDecision`.

So **no agent can answer "why did you pick X" from data.** The conversation agent answered
from chat history because that was the only material it had; the query agent would have failed
too, differently. Routing is not the defect — the explainability data is reachable only by
tapping a UI chip, never through natural language.

**Why the routing observation is still worth recording, but weaker than I first wrote it:**
the router is **LLM-based** (`orchestrator.py:95-120`, `TIER_FAST`, `temperature=0.0`), not a
rule table, so "it always goes to conversation" is not a structural guarantee — it is two
observations. What the prompt *does* show is that neither category fits: `query` is
*"questions/reports"*, `conversation` is *"notes and task changes"*. "Why did you pick X" is a
question, so `query` is the better match by the prompt's own wording — but sending it there
would only change which agent answers without data.

### Spec basis — STRONG, with one honest qualification

Two independent statements, one in each spec document:

> Data Model **§5.5 `ai_decisions`**: *"This is the **explainability table**: **any human can
> always ask "why did the AI do that?"** and get the inputs, the decision, the reason, and the
> confidence."* — and in plain words, *"**Anyone, at any time**, can ask "why did the AI do that?"
> and get a plain-language answer."*

> Workflows **§4**, rule 1 of the three standing above all engines: *"every AI decision is written
> to `ai_decisions` with its reason — **anyone can always ask "why did the AI do that?" and get an
> answer**."*

**The qualification, which this entry already supports:** the app's **"Why?" chip does work** and
reaches `why_trace`. So the letter of "anyone can always ask" is satisfied on *one* surface. What
fails is asking in **natural language** — the product's own front door, which §4 calls *"the front
door for everything a person types or says"*.

Read together the three sentences make the case: the data is mandated to exist, mandated to be
askable by anyone at any time, and the assistant is the documented front door — yet no agent can
reach it. Rule 3 (*"it never guesses"*) then makes the observed behaviour — explaining the chat
instead — the wrong failure mode.

✅ **FIXED & verified 2026-08-06 (tranche 2).** Confirmed a **tool gap, not routing**: `assignment_reason` added to `_item_dict` (verbatim, caveats included) and a new `explain_decision` tool wraps `why_trace`. The F19 regression is re-guarded by test.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. The fix is a **tool, not a route**: expose assignment
reasoning to the query agent (either a `why_was_this_assigned` tool wrapping `why_trace`, or
simply adding `assignment_reason` to `_item_dict`), and surface it **verbatim, caveats
included**. Only then does routing matter, and the router prompt should gain an explicit
example so "why did you pick / why was X chosen" lands on `query`.

**Regression to watch when fixing:** `_item_dict`'s comment records that omitting `priority`
once caused F19 (the model silently answered by due date instead). Adding a field to that dict
changes every query-agent answer shape, so re-run the live assistant scripts, not just unit
tests.

## F47 — A `[missing:…]` placeholder reached a real client PDF, past a guard running in strict mode ✅ FIXED

Found 2026-08-04, Round 7 Act 7. **A real email was sent** (to a plus-address of the project
owner) carrying a proposal PDF whose body reads:

> *"Thank you for the warm discussion about bringing the IBC program to Orchid International
> School. **[missing:context_summary]**"*

That marker is **deliberate**. `app/services/template_service.py:4` states its purpose:
*"[missing:name] so a human notices instead of silently sending blanks."* It is designed to be
caught. It was not.

**Three independent gaps had to line up, and all three did.**

**1. The purpose-built detector is dead code.** `template_service.missing_keys()` (`:32`)
exists solely to find these markers:

```python
return re.findall(r"\[missing:([a-zA-Z0-9_]+)\]", rendered)
```

`grep -rn "missing_keys" app/` returns **zero callers**.

**2. The general fence does not recognise the project's own marker.** `draft_check` — the
deterministic guard built for F30 — was run against the real body, with controls to prove the
detector itself is healthy:

```
our real PDF body        -> []                      ← MISSED
control [Insert Date]    -> ['[Insert Date]']
control [Name]           -> ['[Name]']
control {{mustache}}     -> ['{{contact_name}}']
control TBD              -> ['TBD']
control [see attached]   -> []                      ← correctly ignored
```

The guard works perfectly on every case it was written for. `[missing:context_summary]` escapes
because `_LABEL` is `^[A-Za-z][A-Za-z /&'-]{0,58}$` — the **colon and underscores disqualify
it** — and "missing" is not in `_FILL_WORDS`. The module's docstring explains it is *"kept
deliberately narrow — a false positive blocks a legitimate send"*. That narrowness is
defensible; excluding the project's *own* marker format is not.

**3. The fence never looks at the attachment.** All four call sites pass the same two fields:

```
ai/agents/base.py:260        find_blanks(message.subject, body)
api/messages.py:47           find_blanks(m.subject, m.body)
engines/approval_engine.py:445  find_blanks(message.subject, message.body)
services/message_service.py:197 find_blanks(message.subject, message.body)
```

The placeholder lives in `proposals.content_md`, which is rendered to the PDF and **attached**.
The email body itself was clean. So even a fence that recognised the marker would not have
found it: **the document the client actually reads is never inspected.**

**The guard ran, in strict mode, and still passed.** From the backend log at the moment of
sending:

```
POST /api/v1/messages/536255229c0c486db528ba94e257b054/approve?allow_blanks=false  200 OK
status: sent   provider: smtp:ekaghni.mukherjee@gmail.com
to: ekaghni.mukherjee+nair@gmail.com
```

`allow_blanks=false` is the app explicitly asking for the strict check. It passed because it
was looking at the wrong text.

**Why it matters.** This is F30's exact scenario — *"a fill-in-the-blank that ends up in a
client's inbox, and `EMAIL_MODE` is live"* — reproduced through the one channel F30's fence
does not cover. The proposal PDF is the highest-stakes document the product sends; it is the
only artefact here that a client would read closely, and it is the only one not checked.

**Separately: why was the field missing at all?** `context_summary` was empty even though this
project has a rich meeting summary, five `client_intelligence` notes and a full transcript.
Worth establishing whether the template key is simply misnamed against what the renderer
supplies — that is a second, smaller defect hiding behind this one, and it is the reason the
marker appeared in the first place.

✅ **FIXED & verified 2026-08-05 (tranche 1).** All three sub-items: `_MISSING_KEY` added to `draft_check` without loosening `_LABEL`; the attached proposal narrative is now checked on both approve routes and in the preview; `missing_variables()` fires at proposal creation. Sub-item 3 answered — `context_summary` is optional at every layer, not misnamed. 6 tests.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. Three fixes, and the first two are independent of each other:

1. Add `\[missing:[a-zA-Z0-9_]+\]` to `draft_check` (or call `missing_keys` from it) so the
   two mechanisms stop being separate. Zero false-positive risk — the pattern is this
   project's own generated marker, never prose.
2. Run the blank check over the **proposal narrative** before a proposal email is approved,
   not only over subject and body.
3. Find out why `context_summary` was unpopulated.

**Regression note:** `draft_check`'s narrowness is deliberate and load-bearing — `[see attached]`
and `[Rs 59,000]` must keep passing. Extend it with a specific pattern; do not loosen `_LABEL`.

## F48 — The demo refusal tells you to ask Jarvis for something Jarvis cannot do ✅ FIXED

✅ **FIXED 2026-08-06 (app; not device-verified).** The refusal now points at a person who can actually do it (*"ask your operations lead or an admin to book it for you"*) instead of at a `request_demo` capability that was never built. The cheap option was taken deliberately; building the tool remains possible.

Found 2026-08-04, Round 7 Act 8.

Tapping **Book demo** as a `sales_agent` correctly refuses, with a message that is honest
about the limit and offers two ways forward
(`app/src/main/res/values/strings.xml:537`):

> **"Your role can't book demos — ask your lead, or ask Jarvis to request one."**

The first suggestion is sound. **The second does not exist.** Asked
`book a demo for orchid on 12 August at 3pm`, Jarvis listed the demo team and then replied:

> *"Only Operations Leads, Sales Leads or Org Admins can schedule demos."*

It did not request anything, and there is nothing for it to request with. The scheduling agent
exposes exactly five tools — `list_demos`, `list_demo_teams`, `calendar_view`, `book_demo`,
`cancel_demo` (`app/ai/agents/scheduling_agent.py:46-92`) — and a codebase-wide search for any
request-a-demo concept returns **nothing**. There is no request entity, no approval path, no
notification to a lead.

**Why it counts.** Both halves are individually honest — the button refuses, and Jarvis refuses
— but together they send the user in a circle: the app names a capability, the user tries it,
and gets the same refusal reworded. For a product whose stated principle is that a role
without a capability gets *"the honest explanation instead of a hidden capability"*, pointing
at a capability that was never built is the same failure one level up.

It is also a near-miss on a genuinely good idea. A sales agent who has just run the meeting is
exactly the person who knows the demo is needed; "ask Jarvis to request one" describes the
feature this product ought to have.

**Severity:** low — nothing is corrupted and nothing is silently wrong. It costs the user a
wasted attempt and some trust in the app's guidance.

**Not fixed** — app string plus (if the capability is wanted) backend work. Two options:
1. **Cheap and honest now:** reword to *"Your role can't book demos — ask your lead"*, matching
   what the system can actually do.
2. **Build what the message promises:** a `request_demo` tool that raises an approval for the
   sales lead, which fits the existing approval machinery exactly and would make the original
   wording true.

**Verified working alongside it — do not lose these in a fix:** the Book demo button is
**visible to every role** rather than hidden, and the refusal names the limit plainly. That is
the documented design (05 §8) and it behaved correctly. Note the refusal is a `Toast`, which
`uiautomator dump` cannot see — it was captured by screenshotting ~600 ms after the tap.

## F49 — A superseded plan keeps a live approval, and approving it rolls the project backwards ✅ FIXED

Found 2026-08-04, Round 7, after Act 10 — **spotted by the project owner**, who noticed a
plan v2 approval still sitting in the queue while v4 was active.

Observed state on the Orchid project:

```
plan versions            plan_change approvals
  v1  superseded           v1  approved
  v2  superseded           v2  PENDING     ← still actionable, no decision_note
  v3  superseded           v3  expired     "Superseded by plan v4 before activation…"
  v4  ACTIVE               v4  approved
```

v3's stale approval was correctly retired. **v2's was not**, and remains tappable in the
approvals queue.

### Cause — two paths supersede a plan, only one retires its approval

```python
# planner_engine.py:180-215 — the plan-creation sweep
old.status = PlanStatus.SUPERSEDED.value
...
for a in stale_approvals:
    a.status = "expired"
    a.decision_note = f"Superseded by plan v{version} before activation — …"
    # it even un-queues bundled messages:
    # "A message bundled on a collapsed approval must never be sent."
```

```python
# inbound_engine.py:740-758 — the date-shift handler (Workflow 18 twist)
for d in open_drafts:                      # DRAFT | PENDING_REVIEW, trigger='client_reply'
    d.status = PlanStatus.SUPERSEDED.value
    await record_decision(...)             # ← no approval expiry, no task handling
```

The first is careful and complete. The second sets the status and stops.

**Sequence that produced it**, all through *Log a client reply*:
1. "Add 30 more students" → plan **v2** created, approval pending.
2. "Move everything to 1 September" → `inbound_engine:752` supersedes v2 **without** expiring
   its approval, then creates v3.
3. Meeting 2 merge → v4 created; the planner sweep expires v3 correctly, but **skips v2**
   because the sweep only selects plans still in `DRAFT`/`PENDING_REVIEW` — v2 is already
   `SUPERSEDED`. The orphan can therefore never be cleaned up by any later sweep.

The same gap leaves v2's five tasks stranded in `pending_review`
("Procure 30 additional maker kits", "Update workshop schedule for 70 students", …) — the
planner sweep would have marked them `SUPERSEDED`; the inbound path does not touch tasks at
all.

### Consequence — `activate_plan` has no newest-version guard

`planner_engine.py:418-450`:

```python
if plan.status == PlanStatus.ACTIVE.value:
    return plan                    # the ONLY guard
...
for p in previous:                 # whatever is currently ACTIVE
    p.status = PlanStatus.SUPERSEDED.value
plan.status = PlanStatus.ACTIVE.value
project.current_plan_version = plan.version
```

Nothing checks that the plan being activated is the latest. So approving the orphaned v2 today
would **supersede the active v4**, install v2 as the active plan, and set
`current_plan_version` **backwards from 4 to 2** — discarding the meeting-2 merge (16
workshops, digital materials, teacher training, moved dates) from the active plan, applying
v2's held ops, and opening its five stale tasks alongside v4's.

**Nothing in the UI hints at this.** The card reads *"Plan v2: Scope expansion asked by
Mrs. Nair: Add 30 more students…"* with Reject / Approve. A sales lead working the queue has
no way to know a newer plan has replaced it — the version number is in the text, but there is
nothing to compare it against.

> ## ✅ EXECUTED 2026-08-05 — accidentally, on the live project. Behaved exactly as predicted.
>
> The original note said this was *"code-verified, not device-verified… until someone runs it on
> a throwaway project."* It was then run **by accident on the real one**: a scripted element
> lookup returned null, the script did not abort, and the hardcoded taps that followed fired
> blind on the admin Home screen and approved this exact card
> (`POST /approvals/79d646f0…/decide 200 OK`, 11:44:06, actor = YuviPep Admin).
>
> **Every predicted consequence occurred:**
>
> ```
> before:  v4 ACTIVE   current_plan_version = 4   v2 superseded, approval pending
> after :  v2 ACTIVE   current_plan_version = 2   v4 SUPERSEDED
> ```
>
> **And one consequence was worse than predicted.** This entry says it "strands v2's 5 tasks in
> `pending_review`". It does not strand them — **it releases them**: all five went
> `pending_review → open` on activation.
>
> **The rollback does not self-heal.** Activating the newest plan afterwards (v6, via the Act 14
> offline test) correctly repaired the pointer — `current_plan_version = 6`, v2 back to
> `superseded` — but **the five released tasks stayed `open`**. `activate_plan` supersedes
> *plans*; nothing retracts *tasks* that a superseded activation let out. They remain open today,
> flagged `blocked=1 "awaiting amendment confirmation"`.
>
> **This raises the priority of fix #2 (the newest-version guard).** The damage is not a
> transient mislabel that the next activation tidies up; part of it is permanent without manual
> cleanup. No email was sent and nothing was deleted — the harm was confined to plan lineage and
> those five tasks.

### Spec basis — VIOLATION (Data Model §4.3 `action_plans`)

The status vocabulary defines the direction of travel:

> **`status`** = *"`draft` (being built, or held by an open conflict) / `pending_review` (waiting
> for the approver) / `active` (the live plan) / **`superseded` (replaced by a newer version)**."*

> **`projects.current_plan_version`** = *"Which `action_plans` version is **live right now**."*
> **`action_plans.version`** = *"1, 2, 3… The project's `current_plan_version` points at the live
> one."*

Approving the orphaned v2 marked **v4 `superseded`** — but v2 is **older**, so the field asserts
"replaced by a newer version" about a replacement four versions behind. The observed
`current_plan_version` of **2** then pointed at a plan that was not the latest, while v4, v5 and
v6 all existed.

**This makes fix #2 (the newest-version guard) a correctness requirement rather than a nicety**:
without it, `superseded` and `current_plan_version` can both hold values the Data Model says are
impossible. Confirmed on the device 2026-08-05 — see the EXECUTED note above.

✅ **FIXED & verified 2026-08-05 (tranche 1).** Shared `retire_superseded_plan` called from both supersede paths (conflict-held guard moved inside it), plus a newest-version guard on `activate_plan` raising 409, plus a second guard shape for `current_plan_version` running ahead. `resolve_conflict` was repaired in the same pass — the guard would otherwise have broken it. 5 tests.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. Three parts, and the first is a two-line change:

1. **Make the inbound supersede path do what the planner path does** — expire pending
   approvals and supersede the plan's `pending_review` tasks. Better: extract the existing
   block into one helper and call it from both, so they cannot diverge again.
2. **Guard `activate_plan`** — refuse (or require an explicit override) when a newer active
   plan exists for the project. This is the safety net that makes any future divergence
   harmless.
3. **Show the version context on the approval card** — "v2 of 4" tells the approver instantly
   what the text alone cannot.

## F50 — A client-visible task was completed and the client update was dropped with no trace ✅ FIXED

Found 2026-08-05, Round 7 Act 12 (W14). **This is the act's headline failure.**

Baski completed **"Revise content per Arjun's feedback"** — `visible_to_client = 1`, P1, with a
real result note ("Simplified the grade 6 content — removed the advanced modules and rewrote
two worksheets"). The app said *Done*. The client was never told, and **nothing anywhere
records that the client was not told.**

**Observed, not inferred.** Before and after the tap:

```
action_items   status=done, progress_percent=100, completed_at=10:08:08,
               result_note stored, visible_to_client=1        ✅ all correct
outbound_messages   2 sent · 4 pending_approval · 2 rejected  ❌ UNCHANGED
approvals           6 pending                                 ❌ UNCHANGED
deliverables        0                                         ❌ UNCHANGED
ai_decisions        no row                                    ❌ nothing recorded
backend log         no WARNING, no ERROR, no line at all      ❌ nothing logged
```

**The wiring is all present and every gate passed.** `sync_engine.react` maps `TASK_DONE →
_on_task_done` (`:93`), and `_on_task_done:176-178` is explicit — *"4. visible_to_client → the
Communication Engine drafts the update."* `_draft_completion_update` then found everything it
needed:

| condition | value |
|---|---|
| `task.visible_to_client` | ✅ 1 |
| `task.project_id` | ✅ matches the project |
| stakeholder with `receives_progress_updates` and not `do_not_contact` | ✅ Mr. Rao |
| `contact` row for that stakeholder | ✅ found |
| **`contact.email`** | ❌ **NULL** |

It reached `communication_engine.draft_client_message`, hit `:262-269`, and returned:

```python
to_address = contact.email if channel == MessageChannel.EMAIL.value else contact.phone
if not to_address:
    channel = MessageChannel.EMAIL.value if contact.email else MessageChannel.WHATSAPP.value
    to_address = contact.email or contact.phone
if not to_address:
    return None, None, []          # ← silent
```

**The defect is the silence, not the refusal.** Refusing to invent an address is correct. But
this function has five refusal paths and they are not instrumented alike:

| refusal | trace |
|---|---|
| `do_not_contact` (`:248-255`) | `record_decision("Draft refused", reason=…)` ✅ |
| `needs_review` (`:270-277`) | `record_decision("Draft held", needs_human=True)` ✅ |
| courtesy cap | `record_decision` ✅ — *observed* in `ai_decisions`: *"Send deferred by courtesy cap — Mrs. Nair already received 3 messages this week (cap 3)"* |
| **no address (`:268-269`)** | **bare `return None, None, []`** ❌ |
| **`sender is None` (`:287-289`)** | **bare `return None, None, []`** ❌ |

Three of five record a decision a human can find. The two that do not are the two that fired
into a void here. And the caller cannot compensate: `sync_engine.py:238` invokes
`draft_client_message(...)` **without capturing the return value**, so even a caller that
wanted to react to `None` could not.

**Why the recipient had no address — and why this is NOT just [F41] restated.** F41's
consequence #1 covers the *zero stakeholders* case ("no addressee"). That is not this. There
**is** a stakeholder, correctly flagged `receives_progress_updates=1`: **Mr. Rao**, created
from meeting 2 by `sync_stakeholder_specs`, deliberately **without an address** — F41's own
write-up praises that as the careful part. Meanwhile **Mrs. Nair**, the primary contact with a
working `+nair@` address, is *not* a stakeholder, because F41 means the hand-added contacts
never became stakeholder rows.

So F41 explains *why the only progress recipient is unreachable*; **F50 is that the system
then drops a client communication and tells nobody.** Fixing F41 would remove this instance
and leave the silent path intact for the next one (a stakeholder whose email is later cleared,
a WhatsApp-only contact on an email-only thread, `sender is None`).

**Severity: high.** This is the "nothing invisible" principle inverted — the same principle
F33's fix was written to defend (*"a no-op is allowed, a no-op dressed as success is not"*).
The completing user is told **Done**; the lead sees nothing; the client hears nothing; and
there is no queue, log, decision row or notification anyone could review to discover it. In a
delivery business, "we told the client" is precisely the fact you cannot afford to be wrong
about.

**Reproduction (deterministic):** give a project exactly one stakeholder whose contact has no
email/phone and `receives_progress_updates=1`, complete any `visible_to_client` task, then
diff `outbound_messages` and `ai_decisions`. Both unchanged; nothing logged.

✅ **FIXED & verified 2026-08-05 (tranche 1).** Both bare returns now `record_decision(needs_human=True)`; the false docstring corrected. The `sender is None` branch is now executed by test. Note the write-up under-counted: **11 of 16 call sites** discard the return, which is why the fix belongs inside the function. 4 tests.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. Fix candidates, and one that is *not* safe:

1. **Record the decision.** Give `:268-269` and `:287-289` a `record_decision(...,
   needs_human=True, decision="Client update not drafted", reason="<contact> has no <channel>
   address")`, exactly as the two neighbouring branches already do. Smallest change, closes
   the invisibility, and needs no schema change.
2. **Raise a task, not just a record** — "Add an email for Mr. Rao so the client can be told
   about completed work" — which is the actionable half.
3. **Have `_draft_completion_update` capture the return** and react to `None`; today it
   discards it (`sync_engine.py:238`).
4. **⚠ Do NOT "fall back to any contact on the lead".** Tempting, and wrong: it would email a
   client contact who was never designated to receive progress updates, silently overriding
   `receives_progress_updates` — the one field that exists to make that choice explicit. It
   would also route round `do_not_contact` for anyone not holding a stakeholder row.

**Tested / not tested.** The drop, the absent draft and the total absence of any record were
all **observed live on the device and in the DB**. I did **not** test the `sender is None`
branch — that one is **code-verified only**, read at `:287-289`, and is included because it is
the same shape.

## F51 — The task-lifecycle router enforces ownership on one action out of twenty-three ✅ FIXED

✅ **FIXED & verified 2026-08-05 (tranche 1).** Ownership (`can_reassign_task`) now gates
`/block`, `/unblock`, `/new-date`, `/split`, `/vendor-promise`, `/vendor-slip`; a new **lead-only
`confirm_assignments`** permission gates `/assignments/confirm-batch`; and the app's
`renderActions` mirrors the server so it cannot offer a chip the server refuses (**app source
compiles but the APK was not installed — that half is not device-verified**). `/complete` and
`/progress` are left open **by an explicit decision with the project owner** — covering for a
colleague is teamwork — and that decision is pinned by its own test so it cannot be mistaken for
an oversight. **11 tests: every route this entry could only code-verify is now actually
executed.** Note the spec-check split this finding three ways (see *Spec-check pass 2*): the
device-proven `/block` case is the *weakest*-cited half, and the quadruple-cited
`confirm-batch` half was the one nobody had tested.

> The analysis below is the ORIGINAL write-up, kept because its reasoning — especially why
> `require_permission("manage_tasks")` is **not** a fix — is what made the fix correct.

Found 2026-08-05, Round 7 Act 12 (W16). **Device-proven.**

As **Sourav** (`operations_agent`) I declined "Train and schedule facilitators". It correctly
re-routed to **Mithun**. I then stayed on the same detail screen — now showing *"· Mithun"* —
and **blocked Mithun's task**:

```
POST /api/v1/tasks/af3a8f8e…/block   200 OK
action_items    blocked=1, blocked_reason="Venue confirmation from the school is still pending"
progress_events task_blocked   actor=eaa8fbe5 (Sourav)   assignee=a6b7065a (Mithun)
```

No refusal, no warning, no hint that the task was not mine. Reached entirely through the UI —
no API poking.

**The app and the server agree, and both are half-gated.** `TaskDetailFragment.renderActions()`
(`:284-313`) computes `isAssignee` and spends it on exactly one chip:

```java
boolean isAssignee = task.assigneeId != null && task.assigneeId.equals(tokenStore.getUserId());
if (!done)              addView(chip(task_action_done,      this::doneDialog));      // ungated
if (isAssignee && !done) addView(chip(task_action_decline,  this::declineDialog));   // gated
if (!done) { ...block/unblock, new_date, split, vendor_promise, vendor_slip... }     // ungated
```

Confirmed on screen: with the task assigned to Mithun, Sourav saw **Done · Block · New date ·
Split · Vendor promise · Vendor slipped** and **no Decline** — the screen knew, and used the
knowledge once.

The server mirrors it. Auditing every route in `app/api/workflow.py`:

```
23 routes — 2 carry any authorization beyond org membership
  GUARDED  POST /tasks/{id}/decline            assignee check + PermissionDeniedError (:142)
  GUARDED  POST /approvals/{id}/decide         PermissionDeniedError
     --    POST /tasks/{id}/complete           /block  /unblock  /progress  /new-date
     --    POST /tasks/{id}/split              /vendor-promise  /vendor-slip
     --    POST /assignments/confirm-batch     GET /assignments/proposed
     --    POST /inbound/ingest  /inbound/{id}/resolve  /incidents/{id}/fix-tasks  …
     --    POST /sync/sweep      /messages/draft
```

`get_org_context` (`deps.py:47-69`) only rejects the Super Admin and inactive orgs — it carries
`role` and never tests it. **`workflow.py` is the only API module that never calls
`require_permission`**, while every other one does: admin 16, leads 11, proposals 8, ops 6,
meetings 6, messages 5, demos 5, followups 4, action_items 4, misc 2, projects 1.

**The ownership rule exists and this router does not use it.** `can_reassign_task`
(`permissions.py:57-65`) implements the doc §13 matrix — *"Sales Agent — own only; Sales Lead —
whole team; Admin — yes"*. It has **exactly two callers**, `action_items.py:154` and
`conversation_agent.py:222`, both on the *reassignment* path. The lifecycle router never calls
it; `/decline`'s check is hand-written inline instead of reusing it.

**Worst case is not the task actions.** `POST /assignments/confirm-batch` is ungated, so any
org member can confirm the whole organisation's AI assignment batch — the step
`assignment_mode=lead_confirm` exists to route to a lead. The Data Model §"assignment_mode"
states it plainly: *"`lead_confirm` = the phase lead confirms each batch before anyone is
notified."* Nothing enforces the "phase lead" half. This org **is** in `lead_confirm`
(`org_settings.assignment_mode`), and Sourav's Home offers him the card — *"14 task
assignment(s) proposed — review the reasons and confirm."*

**⚠ The obvious fix does not work.** Adding `require_permission("manage_tasks")` to these
routes would **not** have stopped Sourav: `manage_tasks` grants **all five org roles**
(`permissions.py:23-26`). The missing control is **ownership/scope**, not role. A correct fix
either reuses `can_reassign_task(ctx.role, ctx.user_id, task.assignee_id, same_team=…)` on the
mutating lifecycle routes, or adds a `confirm_assignments` permission restricted to leads for
the batch route. Anyone fixing this should check the app in the same pass — `renderActions`
would keep offering chips the server then refuses, which is the *opposite* of this product's
"honest refusal" pattern only if the refusal is silent; it must surface the reason.

**Mitigating facts, stated fairly.** Nothing is corrupted and nothing is hidden: every action
emits a `progress_event` carrying `actor`, so *"Sourav blocked Mithun's task"* is fully
reconstructible from the audit trail. And a case can be made that completing another person's
task is legitimate teamwork. But `/decline` having an explicit ownership check eleven lines
away shows the authors did consider ownership on this exact router — the asymmetry is far more
likely an omission than a decision, and `confirm-batch` is not defensible on teamwork grounds
at all.

**Tested / not tested.** `/block` by a non-assignee is **device-proven** (200 OK, DB + event
verified). `/complete`, `/new-date`, `/split`, `/vendor-*` and `/assignments/confirm-batch` are
**code-verified, not executed** — I deliberately did not mark another user's task done or
confirm the org's assignment batch, because both would corrupt Round 7 state that later acts
depend on. They have the identical shape: no check of any kind in the handler.

## F52 — "Due today:" renders as a bare header with nothing under it, every time ✅ FIXED

✅ **FIXED & verified 2026-08-06.** Both lists now use `today_local` and are disjoint (`== today` / `< today`), and the compensating `if t not in overdue` filter is gone. Closes [F29]'s residue — the task lists were the one part F29's fix never reached. ⚠ **The Sync Engine's three `due_date < now` sites were deliberately NOT touched** (Workflow 10 defines the 18:00 ladder that way on purpose) — pinned by its own test. 5 tests, falsified.

Found 2026-08-05, Round 7 Act 12. Deterministic; reproduced on **two different users**.

Sourav's briefing, with exactly one task, due **today** (05 Aug):

```
Overdue:
  [P2] Train and schedule facilitators (due 05 Aug)
Due today:
                     ← nothing. The header renders over empty space.
```

Mithun's briefing, same session:

```
Overdue:
  [P1] Send two pilot demo dates this week (due 03 Aug)
  [P2] Coordinate logistics for lab space (due 31 Jul)
  [P2] Train and schedule facilitators (due 05 Aug)     ← due TODAY, filed under Overdue
Due today:
                     ← nothing again
```

**Cause — two lines that were meant to partition, and don't** (`assistant_engine.py:90-91`):

```python
today   = [t for t in tasks if t.due_date and t.due_date.date() <= now.date()]   # DATE compare
overdue = [t for t in tasks if t.due_date and t.due_date < now]                  # DATETIME compare
```

Due dates are stored at midnight — verified: `due_date = 2026-08-05 00:00:00.000000`. So a task
due today satisfies **both**: `2026-08-05 <= 2026-08-05` **and** `2026-08-05 00:00 < 2026-08-05
09:52`. The two lists are not disjoint; `overdue ⊇ {everything due today}`.

The renderer then guards the header on one list and fills it from the other
(`assistant_engine.py:167-170`):

```python
if today:                                                   # ← true
    lines.append("**Due today:**")                          # ← header emitted
    lines += [f"- [{t.priority}] {t.title}" for t in today if t not in overdue]   # ← always empty
```

So **whenever anything is due today, the header appears and its list is empty** — and the task
is announced under *Overdue* instead, from 00:00 on its own due date.

**Two defects, one root.** (a) a section header rendered over nothing, which reads as data
loss; (b) a task due today reported as late, which is simply false and erodes trust in the one
screen a user reads each morning.

**Related to [F29], and this is the part worth carrying: F29's fix was partial.** F29 fixed the
briefing's *date* handling by introducing `today_local = date.today()` (`:78`) — and
`today_local` is used for follow-ups and demos (`:139, :153, :154, :189`). **The task lists at
`:90-91` still use the UTC `now`.** So the same function now mixes a local-date basis for
follow-ups with a UTC-datetime basis for tasks.

**Tested / not tested.** The empty header and the mislabelled task are **device-observed on two
users** and are caused by the granularity mismatch alone — they reproduce at any hour. The
**UTC-vs-local** half is **code-verified, not executed**: at the time of testing (15:5x IST /
10:2x UTC) both dates were 05 Aug, so the timezone split could not have contributed. It would
bite between **00:00 and 05:30 IST** — F29's exact failure window, in the same function, for
the list F29 did not touch. Someone should re-run F29's 03:06 IST device check against *tasks*.

**Not fixed** — backend frozen. The minimal fix is to make the two lines agree and disjoint:

```python
today   = [t for t in tasks if t.due_date and t.due_date.date() == today_local]
overdue = [t for t in tasks if t.due_date and t.due_date.date() <  today_local]
```

which fixes the empty header, the false "overdue", and the F29 residue in one edit. **Check
`whats_blocking` (`:496`) in the same pass** — it uses the same `due_date < utcnow()` test, so
it also counts everything due today as overdue (see the 16 OVERDUE rows in [F43]).

## F53 — "My tasks" has no Overdue group, so late work is filed under "Today" ✅ FIXED

✅ **FIXED 2026-08-06 (app; not device-verified).** Fifth bucket + `my_tasks_overdue`, placed after Blocked and before Today, with `due.isBefore(today)` / `due.isEqual(today)` replacing the `<=` that swept late work into Today. **Shipped with [F52]**, as required — fixing either alone leaves Home and My tasks contradicting each other.

Found 2026-08-05, Round 7 Act 12. The app-side mirror of [F52], failing in the **opposite**
direction.

Baski's **My tasks**, on 05 Aug — one header, three tasks:

```
Today
  Add two-day teacher training before workshops   …  due 1 Aug     (4 days late)
  Revise content per Arjun's feedback             …  due 3 Aug     (2 days late)
  Design workshop curriculum for grades 6-8       …  due 31 Jul    (5 days late)
```

Every one is overdue. All three are grouped under **Today**.

**Cause** (`MyTasksFragment.java:108-123`) — the bucket test is `<=`, not `==`:

```java
} else if (!due.isAfter(todayDate)) {     // due <= today
    today.add(t);
}
```

and there are only four buckets, which the class doc states as the design (`:32`): *"Blocked /
Today / This week / Later"*. **No Overdue group exists.** `strings.xml` has
`my_tasks_today/week/later/blocked` and **no `my_tasks_overdue`** — although
`followups_overdue` = *"Overdue"* does exist at `:562`, so the app has the concept on another
screen.

**Nothing on the row compensates.** `MyTasksAdapter` renders the date as plain text —
`meta.append("due ").append(Times.dateLabel(...))` (`:96-99`) — with no colour, no icon, no
"overdue" marker. The only cue that a task is five days late is the small grey *"due 31 Jul"*
sitting **underneath a header that says Today**.

**Taken together with [F52], the product has no reliable surface for "what is late".** Same
user, same minute, same task:

| task | Home briefing | My tasks |
|---|---|---|
| Train and schedule facilitators (due **today**) | **Overdue** ❌ | Today ✅ |
| Design workshop curriculum (due **31 Jul**) | Overdue ✅ | **Today** ❌ |

One surface calls today late; the other calls late today. A user who trusts either is misled,
and a user who compares them cannot tell which to believe.

**Not fixed** — app change. ⏹ **The "do not rebuild the APK" rule has EXPIRED** (it lapsed with the simulation on 2026-08-05), so this is actionable; the APK simply has not been rebuilt yet
mid-simulation. The fix is a fifth bucket and a string:

```java
} else if (due.isBefore(todayDate)) { overdue.add(t); }
else if (due.isEqual(todayDate))    { today.add(t);   }
```

with `addSection(getString(R.string.my_tasks_overdue), overdue)` placed **after Blocked and
before Today** (P1-pinned ordering inside each group is already correct and should be kept).
Carry it as app work alongside F37's two unmoved literals.

## Correction to [F43] — conflicts DO reach a third surface, and it is the good one

Recorded 2026-08-05, Round 7 Act 12. **[F43] overstates its own scope and should be amended.**

F43 states: *"A conflict is surfaced in exactly two places: a bell notification … and the
project's Conflicts tab — which is tab 7 of 8."* That is **wrong**. There is a third, and it is
the clearest statement of project state anywhere in the product. Mithun's **Delivery** tab:

> **Orchid International School - IBC STEM Program** — Planning · Delayed
> *"17 task(s) overdue; 1 task(s) blocked; **4 unresolved conflict(s) blocking a re-plan**"*

Not a coincidence — deliberate code. `sync_engine.recompute_health` (`:741-768`) counts open
conflicts *and* open incidents and names them in the health reason:

```python
if blocked:   reasons.append(f"{blocked} task(s) blocked")
if broken:    reasons.append(f"{broken} commitment(s) broken")
if conflicts: reasons.append(f"{conflicts} unresolved conflict(s) blocking a re-plan")
if incidents: reasons.append(f"{incidents} open incident(s)")
```

**This makes F43's recommendation better, not weaker.** F43 asks whoever fixes it to consider
"whether the project screen should call the assistant path rather than grow its own second-rate
rules". There is a third and cheaper option now visible: **`whats_blocking` should reuse
`recompute_health`'s reason string**, which already ranks what stops work (blocked, broken
commitments, conflicts, incidents) above what merely has a past date. The correct answer was
already in the codebase, one engine over, being rendered to the ops lead the whole time.

F43 remains **OPEN and valid** — "What's blocking?" and the daily briefing still ignore
approvals and conflicts. Only the "exactly two places" claim is retracted.

## F54 — A complaint made in a meeting never becomes an incident; W22 is wired to email only ✅ FIXED

✅ **FIXED & verified 2026-08-06 — the product decision was taken: yes, a complaint made in a meeting raises an incident.** The incident core (incident + severity + `COMPLAINT_RECEIVED` + dual-lead P1) is **extracted** as `raise_complaint_incident` and shared — `_route_complaint` is NOT duplicated, and it keeps its holding reply, because emailing *"you'll hear from us within the hour"* to someone standing in front of you is not an improvement. **The deeper half: the meeting contract had no FIELD for a complaint**, so the model was never asked — both prompts now have one, with conservative validation (an incident pages two leads at P1, so a thin complaint is dropped rather than escalated). 7 tests.

Found 2026-08-05, Round 7 Act 13 (W22), from the real `meeting4` recording.

The client opened the meeting with an unambiguous service complaint:

> *"On the third, your trainer arrived 40 minutes late. The children were waiting in the lab."*
> *"If it happens again I will have to answer to the parents."*

**The model understood it perfectly** — the summary reads *"acknowledged an issue in the third
session where the trainer arrived 40 minutes late"* — and the review gate produced a task,
**correctly re-graded to P1** at confirm, due Thursday, with an assignee.

**And that is all that happened.**

```
incidents            0  ->  0      ❌ no incident row
COMPLAINT_RECEIVED   not emitted   ❌ so project health never registered it
escalation to leads  none          ❌ neither ops lead nor sales lead was told
holding reply        none          ❌ the client got nothing
```

**Cause — the entire W22 machinery exists and has exactly one entry point.**
`inbound_engine._route_complaint` (`:510-560`) is the implementation, and its docstring states
the workflow by name: *"Complaints NEVER wait in a queue (Workflow 22)."* It:

1. creates an `Incident` with a computed `severity`,
2. emits `COMPLAINT_RECEIVED`, which `sync_engine:100` maps to `_on_health_touch` so the
   project's health reflects it,
3. notifies **both** the ops lead and the sales lead — *"P1 complaint from …"*,
4. drafts a **holding reply** to the client, never auto-sent.

Its callers, in full:

```
_route_complaint   ->  inbound_engine.py:459   InboundIntent.COMPLAINT -> _route_complaint
                       (the inbound intent router — email / "Log a client reply")
                       ...and nothing else. One caller.

Incident(          ->  inbound_engine.py:526   ONE construction site in the whole codebase
COMPLAINT_RECEIVED ->  inbound_engine.py:537   ONE emitter in the whole codebase
```

And the meeting side has no concept of a complaint at all:
`grep -niE "complaint|incident" app/ai/planning.py app/engines/planner_engine.py` returns
**nothing**. The extraction contract has no field in which a complaint could be reported, so
the model could not have flagged it even if asked — this is a **contract gap, not a model
failure**, which matters for the fix.

**This is [F41]'s shape in a new place:** the correct behaviour is fully implemented, carefully
written, and reachable from one path only. F41 = `sync_stakeholder_specs` called on merge but
not on create. F54 = `_route_complaint` reachable from email but not from a meeting.

### ⚠️ Correction (2026-08-05, on re-checking the spec) — this is NOT a spec violation

**My first write-up leaned on the runbook's Act 13 pass condition ("complaint → incident at
P1") as though it were the contract. It is not — the runbook is a test plan, not a source of
truth, and I partly wrote it.** Checking `YuviPep_30_Workflows.md` **Workflow 22** properly:
the whole story is an **inbound** one — *"Mrs. Menon **WhatsApps**…"*, and step 1 opens
*"[Inbound Engine]: intent = complaint…"*. **The spec never contemplates a complaint arriving
in a meeting**, so it does not mandate that the meeting path raise an incident.

**This matters for how F54 should be read.** Contrast [F41], which can point at Data Model
§3.3/§3.4 saying contacts are created *"from a meeting"* and stakeholders *"when meetings
reveal who is who"* — a documented contract, violated. F54 has no such sentence. What it has:

1. The spec states the rule as a property of **complaints**, not of channels — *"Complaints have
   their own rule: they NEVER wait in a queue."*
2. The stated **purpose** of the incident row is channel-independent — it exists *"so it stays
   visible on the timeline until closed"*, and feeds the closure report and `memory_chunks`.
3. The observed asymmetry is real and large: identical words get a P1 dual-lead escalation plus
   a holding reply by email, and a single to-do item in person.

**So the honest status is: a real and demonstrated behavioural gap, and a strong argument that
it should be closed — but a product decision, not a bug that violates a written contract.**
Whoever triages this should decide *whether* a face-to-face complaint ought to raise an
incident, rather than assume it. (My own view, stated as a view: yes for the incident, health
event and escalation; **no** for the automated holding reply, since you have just spoken to the
client in person — that is called out in the fix notes below.)

**Severity accordingly: medium, not high** — downgraded from my first draft.

**Why it matters.** A complaint delivered *in person* is the most serious kind — it is said to
your face, by a client threatening to answer to parents. The product's own design treats
complaints as the one thing that must never queue; deliver the identical words by email and
the ops lead's phone buzzes within seconds and a holding reply is drafted. Say them in a
meeting and the result is a to-do item on one person's list. Nobody is escalated to, project
health is unchanged, and the client is not acknowledged.

**Supporting observation, weaker, same shape — the vendor slip (W24).** The client also said
*"The maker kits have not arrived. Your supplier told us a week's delay. Session 5 needs those
kits."* That became the task *"Chase kit vendor before session 5"* (P1, due 12 Aug,
`required_skill=logistics_coordination` — all sensible), but with
`depends_on_ids=[]`, `external_wait=None`, `blocked=0` and no link to the `vendors` table. The
machinery for vendor waits exists — the task detail offers **Vendor promise** and **Vendor
slipped**, and `external_wait` is the column — but it is a **manual** action a human takes, and
nothing connects a vendor slip stated in a meeting to it. I am recording this as supporting
evidence rather than a separate finding: a human holding that P1 task will plausibly press
*Vendor slipped* themselves, so unlike the complaint nothing is silently swallowed.

**Not fixed** — backend frozen. The fix is not to duplicate `_route_complaint`, which is tuned
to inbound (it takes `msg`, `thread`, and drafts a reply on the inbound channel). Better:

1. **Add a `complaints` (or `incidents`) array to the meeting/merge extraction contract** so
   the model can report one — today there is nowhere to put it.
2. **Extract the incident-raising core** of `_route_complaint` (steps 1–3 above) into a
   function both paths call, leaving the inbound-specific holding reply at the inbound site.
   The holding-reply half needs thought for meetings: you have just spoken to the client
   face-to-face, so an automated *"we're looking into it"* email minutes later may be wrong —
   that is a product decision, not a mechanical one.
3. `severity` currently keys off `project.status == DELIVERY`; this project is still
   `planning` despite sessions running, so it would have been `MEDIUM`, not `HIGH`. Worth
   checking that rule at the same time.

**Tested / not tested.** The absent incident, absent event, absent escalation and absent
holding reply are all **device-and-DB observed** on a real recording. The claim that an
identical complaint *by email* would raise an incident is **code-verified, not executed** — I
did not re-log the same complaint through *Log a client reply* to demonstrate the contrast,
because it would add a second, confusing complaint to the Round 7 project. That contrast is the
single cheapest way to prove or disprove this finding, and it is one *Log a client reply* away.

## F55 — A second campus named in a meeting creates no opportunity, and its decision maker is attached to the current project ✅ FIXED

✅ **FIXED & verified 2026-08-06 — both halves now.** The `.first()` determinism half landed in tranche 1. The contract half is now done too: `_STAKEHOLDER_ITEM_SCHEMA` gained `other_engagement`, and a person whose involvement belongs to a different site or programme gets a **contact but no project-scoped stakeholder row** — which keeps [F41]'s win (they are still discovered) while honouring W29's per-project model. A hand-designated `is_primary` contact overrides the model's guess. 9 tests.

Found 2026-08-05, Round 7 Act 13 (W29/W30).

The client offered new business and named its decision maker:

> *"Our second campus in Hinjuwadai wants the same program next term. Can you send them a
> separate proposal?"* … *"Their head is Mrs. Kulkarni and she will be the decision maker there."*

**The AI said exactly the right thing.** In the meeting: *"I will treat Hinjuwadai as its own
engagement with its own proposal, so nothing gets confused with this campus."* The summary
records *"prepare a separate proposal for the Hinjuwadai campus, led by Mrs. Kulkarni"*. A task
was created — *"Send separate proposal for Hinjuwadai campus"*, P2, due 3 Nov,
`required_skill=proposal_preparation`.

**What the system then did:**

```
leads         9  ->  9      ❌ no opportunity created for Hinjuwadai
projects      1  ->  1      ❌ (correctly — see below)
contacts     15  -> 16      ⚠  Mrs. Kulkarni, source=meeting, no email
stakeholders  1  ->  2      ❌ Mrs. Kulkarni added to the ORCHID IBC project,
                                role_at_client=head, influence=decision_maker
```

**The good half is real and worth keeping:** no Hinjuwadai *delivery* work was injected into
the Orchid plan. Plan v6 contains no Hinjuwadai sessions, kits or dates. The only Orchid-side
artefact is a proposal task, which genuinely does belong to the Orchid rep. **W29's headline
danger — a second campus silently absorbed into the first campus's plan — did not happen.**

### The spec spells out a per-project stakeholder model — this half IS a violation

`YuviPep_30_Workflows.md` **Workflow 29** step 1, on two projects for one client:

> *"leads now has two child projects; **stakeholders rows exist per-project** (Harish is
> decision_maker on both; **Kavita is on the bootcamp only**; the lab adds a trustee)."*

The spec is explicit that stakeholder membership is **per project and differs between them** —
Kavita is deliberately *not* on the second project. Mrs. Kulkarni, who belongs to the Hinjuwadai
engagement, being a `decision_maker` on the **Orchid IBC** project is exactly the crossed wire
W29 is titled to prevent ("zero crossed wires").

**The other half — "no opportunity was created" — is NOT mandated, and I should not overstate
it.** W29's story is *"Priya's **meeting about the lab** creates a second project"* — i.e. a
separate meeting about the new business, which would run the create path normally. Our case is
a **passing mention** inside another project's meeting, which the spec never addresses. So
"Hinjuwadai should have become a lead automatically" remains a reasonable product idea, **not a
contract violation**. The task the system created is a defensible response.

**The defect is that its *people* were absorbed instead.** `sync_stakeholder_specs` attaches
every client-side person a meeting reveals to *the project the meeting belongs to*. It has no
notion that a named person might belong to a different engagement — and **the contract gives
the model no way to say so**: `_STAKEHOLDER_ITEM_SCHEMA` carries `name`, `role`, `influence`
and `receives_updates`, and nothing else. The prompt asks for *"every CLIENT-side person the
discussion actually names"*. Mrs. Kulkarni was named, so in she went. **The model obeyed its
contract exactly; the contract cannot express "this person is not part of this engagement".**

### How far this can actually go wrong — stated precisely

She is now one of **two** `decision_maker` stakeholders on the Orchid project. Two consumers
select on that field:

| Consumer | Behaviour |
|---|---|
| `api/ops.py:132-146` | When sending an **invoice**, CCs "the client's decision maker" — `select(Stakeholder).where(project_id=…, influence=='decision_maker', id != …).first()`. **No ordering**, so with two decision makers the pick is arbitrary |
| `sync_engine.py:285-288` | Follow-up target = first stakeholder with `receives_progress_updates and influence != 'decision_maker'`, **else any decision maker** — a fallback that ignores `receives_progress_updates` entirely |

**Today neither can fire, for one reason only: Mrs. Kulkarni's contact has `email = NULL`**
(correctly — a transcript never contains an address), and both paths test the address before
using it. So the current state is **latent, not live**.

**It arms itself the moment someone does the obvious next thing.** The task the system itself
created says *"Send separate proposal for Hinjuwadai campus"* — you cannot send a proposal
without recording her email. The instant that address exists, an **Orchid invoice can be CC'd
to the head of a different school**, chosen arbitrarily between two decision makers. That is a
client-confidentiality problem, not a tidiness one.

**Severity: medium now, high once an address is added** — and the action that adds it is the
one the product is prompting for.

🟠 **HALF FIXED 2026-08-05 (tranche 1) — the `.first()` half only.** Both `decision_maker` lookups now order `created_at, id`. **The contract half is NOT fixed and this finding stays open for it.** Note the tie-break: identical timestamps fall back to `id` — stable, but arbitrary.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. Candidates, cheapest first:

1. **Give the stakeholder contract a way to say "not this engagement"** — e.g. an optional
   `belongs_to` / `other_engagement` flag on `_STAKEHOLDER_ITEM_SCHEMA`, and have
   `sync_stakeholder_specs` create the *contact* on the lead but **skip the stakeholder row**.
   Keeps the person (you do want to remember Mrs. Kulkarni) without binding them to the wrong
   project.
2. **Order the `decision_maker` lookups deterministically** (`ops.py:136`,
   `sync_engine.py:288`) — `.first()` over an unordered set is a latent defect independent of
   this finding; prefer the primary contact, or the earliest-created stakeholder.
3. **Detect the new opportunity.** No code path anywhere creates a lead from a meeting — the
   only two `Lead(` constructors are `api/leads.py:100` (the manual New-lead form) and
   `api/projects.py:573` (Workflow 27 chain deals, which takes branch names from a human). So
   "Hinjuwadai becomes an opportunity" is **not implemented**, and the task is the whole of the
   product's response. That is defensible as a deliberate keep-the-human-in-charge choice —
   **but then the runbook's W29 pass condition ("a NEW opportunity") is wrong about what the
   product does**, and one of the two should change.

**⚠ Do not "fix" this by refusing to create contacts from meetings.** That is F41's fix in
reverse and would undo the one thing that demonstrably works here — Mrs. Kulkarni was captured
with the right role and the right influence, from speech, automatically.

**Tested / not tested.** The stakeholder row, its project, both decision makers and the null
email are **DB-observed**. The invoice-CC and follow-up-target consequences are
**code-verified, not executed** — there is no invoice in this database to send (`invoices = 0`),
so I could not demonstrate the misdirected CC. Proving it needs a throwaway project, an
address on her contact, and one invoice.

## F56 — The commitment register is write-once: three later meetings added nothing to it ✅ FIXED

✅ **VERIFIED 2026-08-06 — the experiment this entry asked for has now RUN: 6/6 against the real model.** The harness that hung had two defects of my own: the review-confirm payload omitted the required `title` (so it could only 422), and it double-ran `plan_meeting`. Result: first meeting → 2 commitments; **the MERGE added 2 more (2 → 4)**, where three merges previously added zero; and **restating a promise verbatim added no duplicate (4 → 4)**, confirming the ID-based idempotency rather than text matching. The register now reads in self-contained sentences, which is [F42]'s fix visible in the same run.

Found 2026-08-05, Round 7 Act 13.

At the end of `meeting4` the rep read the promises back, which is exactly the moment a
commitment register exists to capture:

> *"To summarize. I will send you the incident write-up on the late trainer by Thursday, chase
> the kit vendor before session 5, pause and verify the invoice, arrange 40 certificates before
> the showcase, send feedback forms after session 8, and prepare a separate proposal for
> Hinjuwadai."* — *"That is a fair summary."*

Six promises, stated, confirmed by the client, and all six became tasks. **None became a
commitment.** All six rows carry `client_commitment_id = NULL`.

**This is not a one-off — it is every meeting after the first:**

```
client_commitments, by creation time
  2026-08-03 20:57:05   x11      <- meeting 1, plan v1, the CREATE path
  (nothing else)
  total: 11

meetings
  2026-08-03 20:32   First meeting with Orchid          -> 11 commitments
  2026-08-03 23:40   Review meeting with Orchid         ->  0
  2026-08-04 00:08   Trustee and coordinator review     ->  0
  2026-08-05 10:41   Delivery review - session two      ->  0
```

**Three merges, zero commitments.** The register froze the moment the project was created.

**Cause — the plumbing and the schema both support it; only the prompt does not.**

- `create_plan_version` (`planner_engine.py:334-336`) creates `ClientCommitment` from
  `spec.get("commitment")` — and the **merge path calls it** (`planner_engine.py:1693`), passing
  its `new_tasks`. So a commitment attached to a merged-in task *would* be persisted.
- The merge's `new_tasks` uses **`_TASK_ITEM_SCHEMA`** — the same schema as the initial plan,
  which includes the `commitment` sub-object (`planning.py:419`). So the model is *permitted*
  to return one.
- **But the merge prompt never asks.** Across the whole merge instruction block the word
  appears only as something to *change*, never to *create*:
  - `{"op":"renegotiate_commitment","commitment_id":…,"new_due":…}` — renegotiate an existing one
  - *"Only reference task_id / commitment_id values that appear in the snapshot"* — i.e. treat
    commitments as pre-existing
  The initial-plan prompt, by contrast, says plainly: *"commitment: attach when the task
  fulfils a promise someone actually stated"* (`planning.py:455`). **That sentence has no
  counterpart on the merge side.**

So the model was told commitments are things that already exist and may be re-dated. It behaved
correctly. The register is structurally write-once.

### The spec mandates the behaviour — this is a violation, not a design question

`YuviPep_Data_Model.md` **§4.5 `client_commitments`** defines what the table is for:

> *"One row = one promise — **in either direction**… Promises are what destroy trust when
> forgotten, so they get their own table and their own watcher: the Sync Engine checks them
> daily (hourly during delivery) and chases before they break. **Extracted by the Planner and
> Inbound Engines from meetings and messages**; also created when an outgoing message makes a
> new promise."*

**"From meetings"** — plural and unqualified. Not "from the first meeting", not "when the
project is created". The Planner Engine is named as an extractor of commitments *from meetings*,
and it does so from exactly one meeting per project.

This puts F56 in the same class as [F41]: **the spec states the contract, the machinery exists,
and one path does not reach it.** (Unlike [F54], where re-checking the spec showed no such
sentence — see the correction in that entry. The difference is worth noting: two findings that
look identical in shape are not equally well-founded, and only the source docs settle it.)

**Consequence — a scheduled job quietly covers less every meeting.**
`sync_engine._sweep_commitments` chases promises: it warns the owner *"Client promise due
tomorrow"* and marks overdue ones `BROKEN`. It can only chase what is in the register. So every
promise made from meeting 2 onward is **never chased and can never be marked broken** —
including "the incident write-up by Thursday", which is the single most reputationally
sensitive promise in this entire simulation, made to a client who has just complained.

**Relationship to [F42], which is about the same table but a different defect.** F42 says the
11 rows that *do* exist are raw transcript fragments and one is double-counted. F56 says no new
rows are ever added. Both are true; fixing either leaves the other. **Note the interaction: F42
warns against de-duplicating on text — a fix for F56 that starts creating commitments on every
merge will make F42's duplication worse**, because the same promise restated in a later meeting
would produce a second row. Any F56 fix needs an idempotency rule, and text equality is exactly
the wrong one.

🟠 **FIX APPLIED 2026-08-05 (tranche 1), NOT behaviourally verified — stays OPEN.** Merge prompt now asks for new promises with ID-based idempotency; 4 guard tests. **The controlled experiment this entry names has NOT run** — `scripts/verify_live_commitments.py` hung in its own harness.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. The minimal change is one paragraph in the merge prompt: state
that a new task fulfilling a newly stated promise should carry a `commitment`, using the same
wording as `planning.py:455`. No schema change and no code change — the persistence path
already exists and is already called.

**Tested / not tested.** The four-meeting distribution above is **DB-observed** and is the
finding's strongest evidence. That the merge prompt lacks the instruction is **source-verified**
(read in full). I did **not** run a controlled experiment — i.e. add the sentence to the merge
prompt and re-run a merge to confirm commitments then appear — because the backend is frozen.
**That experiment is the clean way to prove me wrong**, and it is a one-line prompt edit.

## F57 — "How many approvals are waiting on me" is answered from the task list ✅ FIXED

Found 2026-08-05, Round 7 Act 14. **Device-proven on two different roles** — the second was
run specifically to try to falsify the first.

**Test 1 — Sourav (`operations_agent`, holds no approvals), context chip on Orchid:**

> asked: `show me the pending approvals`
> answered: *"I don't see any pending approvals for **Orchid International School** right now
> **(0 open items)**."*

Ground truth at that moment: **6 pending approvals on the Orchid project** (7 org-wide).

**The obvious innocent explanation is that the tool is role-scoped** — Sourav has no approval
rights, so "none" would be defensible (badly worded, but defensible). **Test 2 was run to settle
it.**

**Test 2 — Siva (`sales_lead`, genuinely holds pending approvals):**

> asked: `how many approvals are waiting on me`
> answered: a list of **tasks**, under the heading *"Due later"* —
> *"Send parent feedback forms after session 8 (due 2026-09-04) · Answer Mrs. Nair's
> refund-policy question (due today) · Send separate proposal for Hinjuwadai campus
> (due 2026-11-03)"*

Not one of those is an approval. **Role-scoping is ruled out.** The assistant cannot see
approvals for anybody.

**Cause — no agent exposes approvals, at all.** The query agent's tools are
`list_action_items`, `list_leads`, `get_client_details` and siblings; a codebase search for an
approvals tool on any agent returns nothing. The REST endpoint **does** exist
(`GET /api/v1/approvals`, `workflow.py:418`) and the app's own Approvals tab uses it — it is
simply not wrapped as a tool.

**The tell is in the wording.** Sourav's answer said **"(0 open items)"** — *"open items"* is
`list_action_items` vocabulary, not approval vocabulary — and Sourav's open action-item count
was exactly **0**. Siva's answer used the task list's own *"Due later"* grouping. In both cases
the model reached for the nearest available tool and relabelled its output.

**This is [F46]'s family, and the third instance of one pattern:** a question the product
openly invites, for which **no tool exposes the data**, answered with confident wrong content
instead of *"I can't see that."* F46 = "why did you pick X" (`assignments.reason` unreachable).
F57 = "what needs approving" (`approvals` unreachable). The failure is identical in shape and
the fix is the same kind: **a tool, not a prompt.**

**Why it matters more than F46 does.** Approvals are the product's central control — the thing
that stops the AI acting alone. A sales lead who asks the assistant *"what's waiting on me?"*
and is shown their to-do list will reasonably conclude nothing is waiting, while a real send
sits in the queue expiring. Note this org's approvals **do** expire and escalate: five of them
escalated off Siva during this very round.

✅ **FIXED & verified 2026-08-06 (tranche 2).** `list_approvals` tool added, **returning `stage`**, described explicitly as not the task list; org/user scoping pinned by a cross-org leak test. 5 tests shared with F46.

> The paragraph below is the ORIGINAL analysis, kept because its reasoning and
> its warnings are what made the fix safe. It is history, not a to-do.

~~**Not fixed**~~ — backend frozen. The fix is small because the data layer already exists:
1. Add a `list_approvals` tool to the query agent wrapping the existing endpoint logic
   (`status`, `mine`), returning entity type, reason, stage and `expires_at`.
2. **Return the stage**, or the answer will mislead a second way — this org has a
   `stage=recommend` approval that deliberately does not appear in the decide queue.
3. **Regression to watch:** adding a tool changes routing pressure on the query agent, and
   `_item_dict`'s comment records that a similar change caused F19. Re-run the live assistant
   scripts, not just unit tests.

**Tested / not tested.** Both tests are **device-observed with DB ground truth**. I did **not**
test whether an explicit phrasing ("list my approval queue") reaches a different agent — the
finding is that no agent has the data, so routing cannot rescue it, but that specific phrasing
is untested.

## F58 — Most notifications dead-end on "a later phase" for screens that already exist ✅ FIXED

✅ **FIXED 2026-08-06 (app + one backend endpoint; not device-verified).** ⚠ **Bigger than this entry's "three dispatch lines"**: `conflict` and `action_plan` notifications carry only `entity_type` + `entity_id`, so there was **no project id to navigate with**. Added `GET /projects/resolve/{type}/{id}` (a lookup, not a `notifications.project_id` column — additive, no migration, cannot invalidate the 16 existing notify sites), plus a tab-aware `ProjectDetailFragment.create(projectId, tab)`. `followup` needed no id at all. `digest` gets its own honest string, since it genuinely has no screen and never will.

Found 2026-08-05, Round 7 Act 14.

Tapping a notification in the bell centre routes through `MainActivity.openEntity(entityType,
entityId)` (`:297-332`), which handles nine types and sends everything else to a Toast:

> *"This opens fully in a later phase — the work item is safe on the server."*

**Observed on the device** (captured at ~600 ms, per the transient-message rule): tapping
*"Plan v1 active — your changes / New task: 'Train and schedule facilitators'"* produced exactly
that Toast and no navigation.

**How much of the bell this covers**, counted from the live database:

```
entity_type    rows   openEntity
action_item      18   HANDLED
approval         19   HANDLED
meeting           4   HANDLED
action_plan      13   --> Toast
conflict          4   --> Toast
followup          2   --> Toast
digest           65   --> Toast
                ----
84 of 125 notifications (67%) do not navigate
```

**The message is honest in tone and wrong in fact.** It says *"a later phase"*, but the screens
exist and are reachable by other routes:

| Toasted type | The screen that already exists |
|---|---|
| `conflict` | **`TAB_CONFLICTS`** + `renderConflicts()` (`ProjectDetailFragment:418, 730`) — with a working "Resolve this conflict" dialog, verified in Act 11 |
| `action_plan` | **`TAB_PLAN`** + `renderPlan()` (`ProjectDetailFragment:73, 413`) |
| `followup` | **`FollowUpQueueFragment`**, pushed from `HomeFragment:126` |

`digest` is the fair exception — there is no digest screen and the content is already in the
notification body, though *"a later phase"* is still odd wording for something that will never
have one.

**The sharpest consequence is for [F43].** F43 argues conflicts are badly announced, and credits
the bell as one of only two places they surface. **That path is a dead end**: a conflict
notification says *"Two sources said different things"* and then, on tap, *"this opens fully in
a later phase"* — while the Conflicts tab sits built and working, three taps away. So conflicts
effectively have **one** discovery route (tab 7 of 8, reached by scrolling the tab strip
sideways) plus the Delivery health line found in Act 12.

**This is [F48] inverted.** F48: the app names a capability that was never built. F58: the app
**denies** a capability that *is* built. Both cost the same thing — the user stops trusting what
the app says about itself.

**Severity: low-moderate.** Nothing is corrupted; it costs a wasted tap and, for conflicts,
closes the discovery path that matters most.

**Not fixed** — app change. ⏹ **The "do not rebuild the APK" rule has EXPIRED**, so this is actionable now. Three lines of
dispatch: `conflict` → project detail on the Conflicts tab, `action_plan` → project detail on
the Plan tab, `followup` → the follow-up queue. Consider a distinct string for `digest` so the
"later phase" message is reserved for things that genuinely have no screen.

# Round 7 — fix order (the plan for the fixing phase)

> ## ⚠ READ THIS BEFORE THE GROUPS BELOW — most of this plan HAS BEEN EXECUTED
>
> **This section is now a historical PLAN, not a to-do list.** It was written on 2026-08-05 when
> 23 findings were open and nothing had been fixed. Two named unfreezes have since run and
> **both are closed; the backend is FROZEN again.**
>
> **✅ EVERY FINDING IN THIS PLAN HAS BEEN EXECUTED.** All three tranches ran:
> F41, F47, F49, F50, F51 (tranche 1) · F39, F40, F43, F44, F45, F46, F57 (tranche 2) ·
> F36, F38, F42, F48, F52, F53, F54, F55, F56, F58 (tranche 3).
>
> **The only thing this plan named that is still open is F35** — and F35 is not a code defect,
> it needs the product owner's policy decision on inbound IMAP. **F59 was raised later and was
> never in these groups at all**; it is pre-existing and undiagnosed.
>
> **The status table at the top of this file is the authority on what is done.** Everything below
> is still worth reading — the traps, the wrong fixes and the dependencies are what made the
> execution go safely — but **do not read a group table as a work queue.** They are all done.
>
> Three entries below are now **out of date in their advice**, corrected here:
> - **Group 1's "app cannot be rebuilt" caveat has expired.** The APK rule lapsed with the
>   simulation, and the app **has since been rebuilt and installed** — the device runs
>   `0.7.4-round7fixes`.
> - **Group 4's item 4.2 (F52) needed the trap from *Spec-check pass 2*:** F52's fix was **not**
>   propagated to the Sync Engine's three `due_date < now` sites — Workflow 10 defines the
>   reminder ladder that way deliberately. **F52 and F53 shipped together**, as required.
> - **F42 was investigated and REFUTED.** The group table treats it as a spec self-contradiction
>   owing you a decision. It is not one: the two "duplicate" commitments link to genuinely
>   different tasks, and the schema enforces no 1:1. **No decision is owed.** Only the raw
>   fragment text was a real defect, and that was fixed. See F42's own section.

**Originally 23 open (F35–F58), grouped by *shared root cause and shared blast radius* rather
than severity** — several had to be fixed **together** or the first fix would make the second
harder. That grouping is what the executed tranches followed.

### ✅ Spec-check pass — DONE for F35–F49 (2026-08-05). Read this before disputing any entry.

Every open finding F35–F49 was re-read against `YuviPep_30_Workflows.md`, `YuviPep_Data_Model.md`
and `YuviPep_Roles_and_Responsibilities.md`, asking one question: **does a spec sentence mandate
the expected behaviour, or does the finding rest on inference?** **No finding was overturned.**
The affected entries now carry a **"Spec basis"** block.

| Basis | Findings |
|---|---|
| **VIOLATION** — a spec sentence mandates the behaviour | **F40** (§3.5 consent is legal proof, `method` = how it was captured, never edited) · **F41** (§3.3/§3.4) · **F45** (Workflows §4 rule 3, *"it never guesses"*) · **F46** (§5.5 + §4 rule 1, *"anyone can always ask"*) · **F49** (§4.3, `superseded` = *"replaced by a **newer** version"*) |
| **CODE CONTRACT** — the module's own docstring states the intent | **F35** (*"each organisation's inbox"*) · **F47** (*"so a human notices instead of silently sending blanks"*) |
| **SELF-EVIDENT** — an internal contradiction; no spec needed | **F36** · **F39** · **F44** · **F48** |
| **SUPPORTING** — the citation backs the *fix*, not a violation | **F43** (the spec's example question describes the **Assistant**, which answers it well; the project screen is a second, worse implementation) |
| ⚠️ **SPEC SELF-CONTRADICTION** — settle the spec first | **F42** — §4.5 says *"one row = one promise"* while its own schema links commitment↔task **1:1 in both directions**. A split promise cannot satisfy both. The code followed the schema |
| 🟠 **INFERENCE** — real defect, but the expectation is a product decision | **F38** — W2's `needs_review` gate exists and behaved correctly (0.86 > the 0.7 threshold); no spec sentence covers a *correction* after a draft is queued |

**Two lessons worth keeping.** First, the systematic weakness in F35–F49 was the opposite of what
was feared: findings were **under-cited**, not over-claimed — six were carrying weaker
justification than the spec actually gives them. Second, **checking the schema saved a false
claim**: F42 looked like a clean §4.5 violation until the linkage fields were read, at which point
it became a contradiction *inside the spec*. **A finding's observation and its expectation are two
separate claims, and only the source documents settle the second.**

~~**Still unchecked by this pass: F50–F53 and F57–F58.**~~ **✅ DONE 2026-08-05** — see the
second pass immediately below. F54–F56 were spec-checked when they were written (which is what
downgraded F54 and strengthened F55/F56).

### ✅ Spec-check pass 2 — DONE for F50–F53 and F57–F58 (2026-08-05)

Same question as pass 1: **does a spec sentence mandate the expected behaviour, or does the
finding rest on inference?** Again **no finding was overturned** — but two changed shape, one
gained a fix-trap the plan did not carry, and one headline number is overstated.

| Basis | Findings |
|---|---|
| **VIOLATION** — a spec sentence mandates it | **F50** (DM §5.5) · **F52** (W17 step 5 + DM §5.6) · **F57** (Workflows §4 rule 3) · **F58** (DM §2.5) |
| **VIOLATION, but split** | **F51** — see below; the strongest-cited half is the one nobody had tested |
| 🟠 **INFERENCE** — real defect, expectation is a product decision | **F53** — but it is a *dependency* of F52, not an optional extra |

**F50 — strengthened, but not by the sentence the status table cited.** The header credits W14
(*"if `visible_to_client` = true, the client-update flow fires"*). That backs the **trigger**,
which is not what failed — the flow *did* fire. W14's own *"If things go differently"* lists
exactly two variants (approver rejects; internal-only task); **a recipient with no address is
not among them**, so "the client should have been told" is genuinely unmandated — and refusing
to invent an address is correct. What **is** mandated is the *recording*: DM **§5.5** — *"One row
= one decision an engine took… Every decision an engine makes — who to assign, **what to draft**,
when to escalate — is written here"*, with `needs_human` = *"True when the engine stopped and
routed to a person"*; plus Roles **§5.4**: *"Reading 'why did the AI do that?' — **Anyone**"*.
Deciding *not* to draft is a decision about what to draft.

**F51 — this is three findings, and they need different controls.**

| Half | Basis | Citation |
|---|---|---|
| `/assignments/confirm-batch` | **VIOLATION, quadruple-cited** | DM §org_settings (*"`lead_confirm` = **the phase lead confirms** each batch"*), DM §assignments (*"the **lead's** batch screen flips these rows"*), W9 step 5 (*"the **phase lead** … gets a batch confirmation"*), Roles §5.4 + §4.5 |
| `/new-date` | **VIOLATION** | Roles §4.6: *"What they cannot do: assign or **move** other people's tasks"* |
| `/block`, `/complete`, `/split`, `/vendor-*` | 🟠 **INFERENCE** | Roles §4.6 frames them under "**Their** tasks", but no prohibition sentence exists; the finding itself concedes the teamwork case |

**The inversion matters:** the **device-proven** instance (`/block`) is the *weakest*-cited half,
and the **spec-mandated** one (`confirm-batch`) was only ever code-verified. That reordered the
fix — and `confirm-batch` is the one that is role-shaped rather than ownership-shaped.

**F52 — VIOLATION, plus a trap this plan did not name.** W17 step 5 and DM §5.6 both enumerate
the daily digest as distinct categories: *"today's tasks across all projects, **anything
overdue**, approvals waiting on them, overnight replies."* The code makes "today's tasks" empty
by construction, so a mandated category never renders.

> ⚠️ **DO NOT propagate F52's fix to the Sync Engine.** Workflow 10 step 1 defines overdue for the
> reminder ladder as literally **`action_items.due_date < now`** — the very test F52 calls wrong —
> because *that* sweep runs at **18:00, the workday end**, where it is correct. `sync_engine.py`
> has three such sites (`:720` health recompute, `:885` task ladder). Changing them to
> `< today_local` would be a **spec violation**. Fix-order item 4.2 rightly pulls in
> `whats_blocking` (also a briefing-class surface) but says nothing about the sweep. **Scope the
> fix to `assistant_engine`.**

**F53 — no mandate, but not optional.** No spec sentence requires a "My tasks" overdue group, and
the four-bucket design is stated in the class doc. **But it becomes a live contradiction the
moment F52 lands**: Home would say *Overdue* and My tasks *Today* for the same task in the same
minute. **F53 must ship with F52**, not in the "smaller, independent, safe to batch" group.

**F57 — VIOLATION.** Workflows §4 rule 3: *"When the AI is unsure, it asks — **it never guesses**.
Low confidence, conflicting sources, unmatched messages, and **missing knowledge** all route to a
named human."* Plus the Assistant Engine's own definition: *"answers questions **across
everything** in plain language."* Same citation pass 1 used to grade F45 a VIOLATION — consistent.
DM §approvals adds force: *"Unanswered approvals are reminded, then escalated at expiry, **so a
draft never dies silently in an inbox**"* — an assistant telling the holder "no approvals" works
directly against that guarantee.

**F58 — VIOLATION on one clean sentence, but the headline number overstates it.** DM §2.5, field
`entity_type, entity_id`: *"What the notification points at, **so tapping it opens the right
screen**."* That is the field's stated purpose. **However** — F58 itself concedes `digest` is a
fair exception, and **65 of the 84 are digests**. The honest count of *wrongly* Toasted
notifications is **19 of 125** (conflict 4 + action_plan 13 + followup 2). The substance stands
(the conflict half still kills the bell route F43 credits); **the "84" quoted in the status table,
the runbook and MEMORY.md should read "84 dead-end, 19 of them wrongly."**

**A documentation defect found during this pass:** every doc cites `YuviPep_30_Workflows.md`;
the file on disk is **`YuviPep_30_Workflows.extracted.md`**. A broken pointer in four places.

### ⚠️ Two scope facts to settle before any work starts

1. **Some of these are APP fixes, not backend.** ⏹ The original caveat here — *"the app cannot
   be rebuilt until the simulation is finished"* — **EXPIRED on 2026-08-05** when the simulation
   ended. App items are therefore actionable. Current state of them:
   **F39**, **F51's chip half**, **F36**, **F48**, **F53**, **F58** — ✅ **all fixed** ·
   plus **F37's two literals**, deliberately left in Java and **still unmoved** (the guard
   reports them every run — that is expected, not a failure).
   ✅ **The APK HAS since been rebuilt and installed** — the device runs
   **`0.7.4-round7fixes`**, so the app-side fixes are on the phone, not merely compiled.
   (Rebuilding it is also what exposed **F60**, the card-scanner crash.)
2. **F35 is a design decision, not a patch.** Scope by label? `BODY.PEEK`? Refuse a mailbox
   above N messages? Decide the policy first; it is the one item here that should not be
   handed to an implementer as-is.

---

### Group 1 — data integrity and leak risk. Do these first.

These can corrupt project state or send something to the wrong party.

| # | Finding | Fix shape | Trap |
|---|---|---|---|
| ✅ DONE 1.1 | **F49** superseded plan keeps a live approval; `activate_plan` has no newest-version guard | Two parts: give the inbound supersede path the same expiry the planner sweep does (extract one helper, call from both), **and** guard `activate_plan` against activating anything but the newest | The guard is the safety net — add it even if the helper lands first. Also strands v2's 5 `pending_review` tasks |
| ✅ DONE 1.2 | **F47** `[missing:…]` reached a real client PDF | Add `\[missing:[a-zA-Z0-9_]+\]` to `draft_check` (or call the dead detector — note it is actually named **`missing_variables()`**, not `missing_keys()` as written elsewhere in this file), **and** run the blank check over the proposal narrative, not just subject+body | **Do not loosen `_LABEL`** — `[see attached]` and `[Rs 59,000]` must keep passing. Extend with a specific pattern. Third sub-item: find out *why* `context_summary` was empty |
| ✅ DONE 1.3 | **F51** task router enforces ownership on 1 route of 23 | Apply the project's own `can_reassign_task` to the mutating lifecycle routes; add a lead-only permission for `/assignments/confirm-batch` | **`require_permission("manage_tasks")` does NOT fix it** — that grants all five org roles. The missing control is *ownership*. Fix the app's `renderActions` in the same pass or it will offer chips the server refuses |
| ✅ DONE 1.4 | **F55** wrong-project stakeholder + arbitrary `decision_maker` pick | Give the stakeholder contract a way to say "not this engagement"; **separately**, order the two `decision_maker` lookups deterministically (`ops.py:136`, `sync_engine.py:288`) | The `.first()`-over-unordered-set defect is worth fixing **on its own merits** even if the contract change is deferred. Do not fix by refusing to create contacts from meetings — that undoes F41 |
| 🔴 OPEN 1.5 | **F35** IMAP reads/marks-read a personal mailbox | Policy decision first (see above), then implement | Currently mitigated by `INBOUND_EMAIL_MODE=off`. **The IMAP transport is therefore untested by Round 7** — retest against a *dedicated* mailbox once fixed |

---

### Group 2 — the "one entry point" family. Fix together; they share a root cause.

**This is the most important insight of Round 7.** Three findings are the same bug wearing
different clothes: *machinery that exists, works, and is wired to exactly one path.* Whoever
fixes one should fix all three, because the review question is identical each time — **"which
entry points can reach this, and which should?"**

> **These are wiring gaps, and their diagnoses are settled — do not re-open them.** F41's cause
> was **proven** by experiment in Act 10 (meeting 2 created Mr. Rao where meeting 1 created
> nobody, same lead, same contract, same model). F54 and F56 were each established by finding
> the single caller / the single missing prompt clause. The notes below are about **executing**
> the wiring safely, not about re-litigating the cause. None of them makes these bigger jobs
> than they are: each core fix is small.

| # | Finding | The machinery that already exists | Reachable from | Not reachable from |
|---|---|---|---|---|
| ✅ DONE 2.1 | **F41** first meeting drops its people | `sync_stakeholder_specs` | merge, inbound email | **the first meeting** |
| ✅ DONE 2.2 | **F54** meeting complaint never becomes an incident — 🟠 **decide first, then fix** | `_route_complaint` (incident + severity + health event + dual-lead P1 + holding reply) | inbound email only | **any meeting** |
| ✅ DONE 2.3 | **F56** commitment register is write-once | `create_plan_version`'s commitment block — *the merge already calls it* | the first meeting | **every merge** (the prompt never asks) |

**Traps, all documented in the entries:**
- **F41 — what the fix actually creates.** It creates **both contacts and stakeholders**, but
  **only the contact half is new code**. `_create_project_shell` already receives
  `stakeholder_specs` (`:1333`) and its loop (`:1336-1353`) already creates a `Stakeholder` for
  every contact it iterates — it simply has nothing to iterate. So: create the missing
  `Contact` rows from the specs *before* that loop (`source="meeting"`, **no address**, exactly
  as `sync_stakeholder_specs:1223-1231`), and the existing loop produces the stakeholders
  itself. **Do not write new stakeholder code — make the loop's input complete.**
- **F41 — why not just call `sync_stakeholder_specs`.** It creates contacts (`:1223-1231`)
  **and** stakeholders (`:1236-1250`); the create-path loop then runs over every contact with
  **no existence check**, giving **two stakeholder rows per contact**. Nor can you swap one for
  the other — the defaults differ, and `primary_stakeholder` (`:1352-1357`) depends on the
  create-path behaviour:

  | | create-path loop (`:1338-1346`) | `sync_stakeholder_specs` (`:1238-1242`) |
  |---|---|---|
  | `influence` | spec, else **`decision_maker` if `c.is_primary`** else influencer | spec, else **always `influencer`** |
  | `receives_progress_updates` | `bool(spec)` **or `c.is_primary`** | `bool(spec)` only |

  Losing the `is_primary → decision_maker` rule leaves `primary_stakeholder = None`, which is
  precisely F41's consequence #3 (11 ownerless commitments). Factoring the contact-creating
  block out of `sync_stakeholder_specs` so both paths share it is the tidy version.
- **F41 — the backfill. This is F41's own consequence #4, not extra scope.** The entry already
  states it: *"Any fix must therefore also backfill on contact creation, not merely create
  contacts earlier."* The loop runs **once**, inside project creation, so adding contacts by
  hand afterwards still creates no stakeholders — device-proven (contacts 0→3, stakeholders
  0→0). Consequence: the wiring fix makes **new** projects correct while **this** project stays
  broken until its plan is regenerated. Both halves were always part of F41.
- **F41 + F55 touch the same function and the same data** — do them in one pass. The moment the
  *create* path starts making contacts from specs, it inherits F55's problem too: a person who
  belongs to a **different engagement** (the Mrs. Kulkarni case) gets bound to this project on
  the create path exactly as they already are on the merge path.
- **F54 — this one needs a product decision BEFORE any code.** Unlike F41 and F56, no spec
  sentence mandates it (W22 is written entirely as an inbound story). Confirm that a
  face-to-face complaint *should* raise an incident before implementing; if the answer is no,
  F54 closes as "working as specified" and only the wording of the runbook's Act 13 condition
  needs changing.
- **F54:** do not duplicate `_route_complaint` (it is inbound-shaped). Extract its
  incident-raising core; leave the holding reply at the inbound site and *decide* whether a
  face-to-face complaint should trigger an automated email at all.
- **F56:** the fix is one paragraph in the merge prompt — but **it makes F42 worse** (the same
  promise restated in a later meeting would create a second row). Needs an idempotency rule,
  and **text equality is exactly the wrong one** (see F42).
- **Fixing F41 removes F50's current instance** but leaves F50's silent path intact. They are
  not substitutes.

---

### Group 3 — outbound honesty. One principle, three findings.

All three live in `communication_engine` and all three resolve to the same rule:
**the app never silently changes or silently drops a recipient — it discloses.**

| # | Finding | Fix shape |
|---|---|---|
| ✅ DONE 3.1 | **F50** client update dropped with no trace | Give the two bare `return None, None, []` branches (`:268-269` no address, `:287-289` no sender) a `record_decision(..., needs_human=True)`, exactly as `do_not_contact`, `needs_review` and the courtesy cap already do. Have `sync_engine:238` capture the return |
| ✅ DONE 3.2 | **F38** corrected address never reaches the queued message | Prefer **disclosure** over rewriting: `redraft_rejected` already loads the contact, so compare and surface the divergence on the approval card |
| ✅ DONE 3.3 | **F44** `Subject:` inside the body; replies have no subject | Persist the model's subject instead of stranding it; strip/reject a leading `Subject:` line; give replies a fallback subject (6 call sites in `inbound_engine`) |

> **⚠️ The single most dangerous shared wrong fix in this file:** *"just re-resolve `to_address`
> from `contact_id`."* It was the first recommendation in **both** F38 and F44 and it is unsafe
> — it breaks WhatsApp/non-email channels, explicitly-typed recipients (`proposal_agent.py:268`),
> and proposal emails that carry no `contact_id` at all. Any address fix must be conditional on
> channel, on `contact_id` existing, and on the stored address not having been hand-edited.

---

### Group 4 — the app says things that aren't so.

| # | Finding | Fix shape | Note |
|---|---|---|---|
| ✅ DONE 4.1 | **F43** "What's blocking?" ignores approvals *and* conflicts | **Reuse `sync_engine.recompute_health`'s reason string**, which already ranks blocked/broken/conflicts/incidents correctly | This is better than the entry's original advice — see the F43 correction. The good answer was already in the codebase |
| ✅ DONE 4.2 | **F52** empty "Due today:" header; task due today called Overdue | Make `assistant_engine:90-91` agree and be disjoint (`== today_local` / `< today_local`) | **Fix `whats_blocking` in the same pass** — same `due_date < utcnow()` test, so it also counts today as overdue. Closes F29's residue. ⚠ **Two updates:** `whats_blocking` was rewritten for F43 and that comparison was **deliberately left alone**, with a comment pointing here — so this is still to do. And per *Spec-check pass 2*, **do NOT propagate the fix to `sync_engine`'s three `due_date < now` sites**: Workflow 10 defines the reminder ladder that way on purpose. **F53 must ship with this** |
| ✅ DONE 4.3 | **F53** "My tasks" has no Overdue group *(APP)* | Fifth bucket + `my_tasks_overdue` string; place after Blocked, before Today | Keep the P1-pinned ordering inside each group |
| ✅ DONE 4.4 | **F45** "who is doing X" answers client-side | Scope "who is doing/owns/handling" to assignments first; fall back to stakeholders **and say so** | The standing terse-command rule: resolve or ask, never silently guess |
| ✅ DONE 4.5b | **F57** an approvals question answered from the task list | Add a `list_approvals` tool to the query agent wrapping the existing endpoint — **return the `stage`** too, or it will mislead a second way | **Do with F46** — identical shape, identical fix (a tool, not a prompt). Same `_item_dict`/F19 regression risk |
| ✅ DONE 4.6 | **F58** notifications dead-end on built screens *(APP)* | Three dispatch lines in `openEntity`: `conflict`→project/Conflicts, `action_plan`→project/Plan, `followup`→follow-up queue | Give `digest` its own string so *"later phase"* means what it says. **Do with F43** — both are about conflicts being findable |
| ✅ DONE 4.5 | **F46** "why did you pick X" unanswerable by any agent | It is a **tool gap, not a routing bug** — expose `assignments.reason` (or wrap `why_trace`) and surface it **verbatim, caveats included** | Adding a field to `_item_dict` changes every query-agent answer shape — re-run the live assistant scripts, not just unit tests (that is how F19 happened) |

---

### Group 5 — consent and the recorder.

| # | Finding | Fix shape |
|---|---|---|
| ✅ DONE 5.1 | **F39** recorder pause is one-way; mic keeps running behind "Paused" *(APP)* | Post `RECORDING` directly rather than through the `publish()` guard. ⚠ **This row's original advice — "`elapsed()` must be called after that post" — is WRONG and was NOT followed:** `postValue()` is asynchronous, so `current()` can still read `PAUSED` afterwards and `elapsed()` would republish the frozen value, re-freezing the timer. The elapsed time is computed **inline** instead. The `content-desc` and the pause-only button were folded in as advised |
| ✅ DONE 5.2 | **F40** meeting consent record hardcoded to `in_app` | Accept the method/note on upload (or link the lead's most recent consent record) instead of inventing one; refusing when none exists closes the second gap — that `consent_confirmed` is a self-asserted caller flag the API never verifies |

**These two are the round's most serious in kind** — both are places where the recorder tells a
confident story about consent that the underlying state does not support.

---

### Group 6 — smaller, independent, safe to batch.

| # | Finding | Fix shape |
|---|---|---|
| ✅ DONE 6.1 | **F42** commitment fragments + structural double-count | Ask the model for a self-contained sentence. **Do NOT de-duplicate on text** — that breaks the 1:1 task↔commitment link. Real options: attach to one derived task, de-dup at *read* time, or make the link many-to-many. **Coordinate with F56** |
| ✅ DONE 6.2 | **F48** demo refusal points at a capability that doesn't exist | Either reword `strings.xml:537` *(APP)*, or build the `request_demo` tool the message promises — it fits the existing approval machinery |
| ✅ DONE 6.3 | **F36** login `server:` chip stale after Apply *(APP)* | `EnvironmentSheet` should notify; `refreshServerChip` only runs in `onResume`, which a dialog dismiss never fires. Debug-only, but it misleads on the exact screen used when the backend is unreachable |

---

### Verification standard for every fix (project convention, handoff §7)

Re-run **all** of these green after each change, plus a **device check** wherever the UI can
reach it — and say plainly what was not device-tested:

```
pytest                                   (104/104 at the pause)
scripts/dryrun_workflows.py              (43/43)
scripts/verify_gap_endpoints.py          (21/21)
scripts/verify_generic_stakeholders.py --stub   (21/21)
scripts/verify_live_genericity.py        (15/15, against the real model)
scripts/verify_live_resolution.py        (19/19)
pytest tests/test_genericity.py     +    scripts/check_hardcoded_strings.py   ← the two guards
```

**Rule 8's fix half applies to every item above:** grep every caller · check what the schema
assumes · **prove it by behaviour, not by reading**. And prefer a falsification check that asks
*"is there a shape of input this check cannot see?"* — not only *"does it notice the fix being
removed?"* That distinction is what F37 cost.

# Verified working — no defect found

## Round 7 — Act 14, the awkward paths: offline queue, logout churn and voice all PASS

**The offline decide queue is the best-built thing in the round.** With the app's route to the
backend cut (`adb reverse --remove tcp:8000` — airplane mode does *not* work here, the app
reaches the server over USB), approving plan v6 produced:

- a Snackbar — *"Queued — will apply when you're back online"* — **and a persistent inline
  label on the approval card saying the same**. The state survives you looking away, which a
  Toast would not;
- **the server genuinely untouched** while offline (approval still `pending`,
  `current_plan_version` unchanged) — verified in the DB, not inferred;
- on reconnect, **drained within 5 seconds and applied exactly once**
  (`current_plan_version = 6`, v6 `active`, v1–v4 `superseded`). `ApiService` passes an
  explicit idempotency key for precisely this path.

**F1 does not regress, on either half.** Logging out of Rahul and into Sourav, captured ~1.2 s
after the sign-in tap: Sourav's Home rendered **Sourav's** data immediately — his own honest
empty state (*"Nothing needs you this morning — no tasks due, no approvals waiting, no
follow-ups or demos on the calendar, and nothing came in overnight"*, correct, since his one
task had been re-routed to Mithun in Act 12) with **no trace of Rahul's five overdue tasks**.

**Voice works end to end.** Dictating *"what's blocking orchid"* transcribed cleanly, routed to
the query agent, and returned the round's best blocking answer — grounded in meeting-4 content:
the maker-kit supplier delay blocking session 5, the payment-reminder-vs-advance mismatch, the
late-trainer incident, and the cluster of plan/proposal revisions due today. Compare the
project screen's deterministic version in [F43]; this is the answer users actually want.

**Honest caveat on the conflicts point:** this answer *does* reach the conflict indirectly — it
lists *"revise the plan for the two positions"*, the task the conflict produced — but it never
names the four open conflicts as blockers. F43's core claim stands; the user is not wholly
blind, which the F43 entry should not overstate.

### ⚠️ An operator error occurred during this act — recorded because the DB carries its marks

A scripted element lookup returned null, **the script did not abort**, and the hardcoded taps
that followed fired blind on the admin Home screen, approving the **Plan v2** card — the exact
item the runbook forbids. Consequences are written up in [F49], which this accidentally
converted from *code-verified* to *device-proven*. **No email was sent**; the harm was plan
lineage plus five released tasks, and the pointer was repaired by the v6 activation above.

**Two marks remain in the data and are not defects:** plan **v6 is active** (rather than v4 as
Act 13 left it), and **five `blocked=1` scope-expansion tasks from v2 are `open`** that would
otherwise still be `pending_review`. Anyone diffing against Act 13's numbers should expect both.

**The process rule this produced, now applied:** *every element lookup must abort the script when
it finds nothing.* A find that returns null must never fall through to a coordinate tap — on a
screen full of Approve buttons, a blind tap is a live grenade.

## Round 7 — Act 13 delivery meeting (W26, plan-hold, people-discovery), verified end to end

**The extraction and the review gate were the best of the round.** `meeting4.wav`, 3:02, real
recording through the phone's mic: transcript **0.876 / 408 words**, and **all six** commitments
the rep summarised were extracted, each with a faithful description in the client's own terms —
e.g. *"YuviPep will stop the payment reminder, then check the advance payment (28th via bank
transfer) against their own records rather than ask Orchid to prove it."* That is W25's required
behaviour ("pause, don't argue") stated back correctly.

**The review gate did real work at confirm.** All six went `pending_review → open`, every one
got an assignee, and — the part worth checking — **every one got a due date**, including the
three the model left blank (**F8 holds**). The dates are inferred, not defaulted:
certificates → **3 Dec** ("before the showcase in December"), feedback → **4 Sep** ("after
session 8"), vendor chase → **12 Aug** ("before session 5"). And the three urgent items were
**re-graded P2 → P1** at confirm while the closure items stayed P2.

**The protected Round 7 state survived a fourth meeting untouched** — this was the real risk:

```
plan v4  active        (unchanged)     current_plan_version = 4   (unchanged)
plan v5  draft         (unchanged)     conflicts: 4 open          (unchanged)
plan v6  pending_review  <- new, held behind an approval (pending 6 -> 7)
```

A fourth meeting merged into a project whose plan is **already frozen by four open conflicts**,
and it neither activated itself nor disturbed the held v5. **F49's failure mode did not recur.**

**People-discovery worked again, and this is [F41]'s machinery doing its job**: Mrs. Kulkarni
was created from speech alone as a contact (`source=meeting`, **no invented email**) plus a
stakeholder with `role_at_client=head` and `influence=decision_maker` — both inferred correctly
from *"Their head is Mrs. Kulkarni and she will be the decision maker there."* (Where she was
attached is [F55]; that she was captured at all is right.)

**Skills routed sensibly** across the merged vocabularies: `logistics_coordination` for the
vendor chase, `invoicing` for the payment query, `proposal_preparation` for the Hinjuwadai
proposal, `general` for the rest.

### ⚠ Precondition note — W25's "ladder pauses" could NOT be tested. Do not file it as a bug.

Act 13's pass condition says the payment query must **pause the payment ladder**. It could not:

```
invoices  0        payments  0        active reminders  0
```

**There is no invoice in this database and therefore no ladder to pause.** The project never
reached invoicing (it is still `status=planning`), and invoice screens are Phase 7.1 — unbuilt.
The system's actual response was the correct human-level one: a **P1** task due **today**,
assigned, `required_skill=invoicing`, whose description states the right policy. **Checked in
the schema and the data — do not re-file this as a missing pause.** To exercise W25 properly,
create an invoice and let the reminder ladder start first.

**"Hinjuwadai" is the transcript's spelling of Hinjewadi** — a Windows-TTS pronunciation that
Whisper rendered phonetically. A synthetic-speech artifact of the test fixture, **not** an ASR
or extraction defect; the same entity is spelled consistently throughout, so nothing mis-linked.

## Round 7 — W16 decline/re-route and W11 blocked + ripple (Act 12), verified end to end

**W16 — decline re-routes, it does not vanish. Full PASS, device-proven.** Sourav declined
"Train and schedule facilitators" (reason **Wrong skill for this**, plus a typed note):

- The reason is **mandatory** — four options, then an optional note. No way to decline blankly.
- The declined assignment row is **preserved, not overwritten**: `status=declined`,
  `decline_reason=wrong_skill`, `decline_note` stored verbatim, `decided_at` set. The history
  survives the re-route.
- The task **returned to `open`** and was reassigned **excluding both the decliner and the
  previous assignee** (`assignment_engine.decline_task:538-541`).
- It landed on **Mithun** with a *better-justified* reason than the one it left —
  *"Mithun: expert skill match, 2/8 open tasks, did 3 related task(s) on this project"* vs
  Sourav's *"good skill match, 0/8 open tasks"*. The `wrong_skill` reason was genuinely
  honoured: `good` → `expert`.
- The due date was untouched, and **Decline correctly disappeared** from the action set for the
  now-non-assignee.
- It reaches the recipient: Mithun's own briefing next login listed *"[P2] Train and schedule
  facilitators"*.

**No notification was sent to Mithun — and that is correct, not a defect.** Checked three ways
before concluding: `assignment_engine:344-357` defers notification to `confirm_batch` in
`lead_confirm` mode; `org_settings.assignment_mode = lead_confirm`; and the Data Model states
it independently — *"`lead_confirm` = the phase lead confirms each batch **before anyone is
notified**"*. Nearly written up as a finding; the innocent explanation was the right one.

**W11 — blocked tasks and the ripple gate. Full PASS.**

- **"What blocks it" is stated prominently**: a red banner reading *"Blocked: Venue confirmation
  from the school is still pending"*, and the chip correctly flips **Block → Unblock**.
- **The new-date ripple check works exactly as designed.** Proposing 15 Aug for a task whose two
  dependents are due 13 Aug was **refused, not applied** — `{"accepted": false,
  "routed_to_lead": true, "breaks": [...]}` (`workflow.py:255-289`), the task row was left
  completely untouched, and the **phase lead was notified with the full reason**:

  > *"Date change needs your yes: Add two-day teacher training before workshops — Baski asks
  > 15 Aug (reason: Trainer availability slipped…) but it breaks: dependent task 'Plan and
  > develop teacher training content' is due 13 Aug; dependent task 'Schedule teacher training
  > program' is due 13 Aug"*

- **The user is told**, by Snackbar: *"This breaks: dependent task 'Plan and develop teacher
  training content' is due 13 Aug; dependent …"*. The dialog is honestly titled **"Propose a
  new date"**, not "Set".

> ⚠️ **Method note — this was nearly filed as "new-date silently does nothing".** The first
> screenshot was taken **7 s** after the tap; the Snackbar is `LENGTH_LONG` (~3.5 s) and had
> already gone, leaving a screen still reading *"due 1 Aug"* and a DB row with an untouched
> `updated_at`. Every instrument said "nothing happened". Re-shot at **~900 ms**, the message
> was plainly there. This is the third time in Round 7 that a transient message masqueraded as
> silence (see *"Silent mic failure / silent reschedule gate"* below, and F48's Toast).
> **Rule: before reporting that the app said nothing, re-capture inside 1 s.**

**Placeholders behave.** `More` (Sourav), `Incidents` and `Team` (Mithun) all render the honest
*"On its way — <Tab> is coming in a future update. Your work stays safe on the server in the
meantime."* Correctly named per tab, no crash, no fake data. `Sign out` is present on Home for
both roles, below the fold.

**Two small things noticed, neither worth a finding on its own:** the task detail's Progress bar
still reads **0%** immediately after Done (the server sets `progress_percent=100`; the screen
re-renders from the stale local object), and the ripple Snackbar **truncates** the second break
at two lines — though the lead's notification carries both in full.

## Round 7 — W7 conflict handling (Act 11), verified end to end

Worth recording as *working*, because it is the hardest thing this product attempts and it
behaved correctly on a deliberately incoherent meeting (`meeting3.wav`: the client's trustee
and coordinator contradict each other on scope, dates and audience, plus a discount ask).

- **4 conflicts raised**, each stating **both positions with correct attribution** —
  *"Mr. Rao wants the program cut back to eight workshops; **Arjun says** all 16 workshops are
  already on the school timetable…"*. Attribution was right in the conflict rows even though
  the meeting *summary* garbled who said what.
- **The re-plan was held, not applied.** Plan **v5 stayed `draft`** with `held_plan_id` set;
  **v4 remained active**; and **no approval was raised for v5** — the system does not even
  offer a re-plan for sign-off while the client's own people disagree.
- **It refused to pick a side.** The review gate produced exactly **one** neutral task —
  *"Send revised plan for both positions"* — with nothing about 8 workshops or October. The
  temptation was real: Mr. Rao is the recorded `decision_maker`, so following him would have
  looked decisive and been wrong.
- **The discount was routed, not conceded** — recorded as needing the approval process.
- **Escalated to the right person**: all four `raised_to_user_id` = the sales lead, with bell
  notifications.
- **The app can resolve them**: project → **Conflicts** tab lists each one with a *"Resolve
  this conflict"* dialog (*"What's the call, and why?"*), validated against one-word answers,
  posting to `POST /projects/{id}/conflicts/{id}/resolve`. Full round trip, DTO to endpoint.

The only criticism is *where it is announced* — see the briefing/blocking note in [F43]. The
mechanism itself is sound.

- **All 9 seeded logins** + correct role-shaped nav for each; super-admin placeholder correctly
  states "Platform operators cannot read organisation data".
- **Card scan**: real Telaverge card → 100% confidence, all four fields correct, honest
  "Card says: Telaverge Communications" mismatch line against the lead name.
- **Recorder**: consent gate → 2:47 foreground recording → upload → Whisper → extraction →
  review gate; low-confidence warning fired correctly.
- **Review gate**: drop → `cancelled`, edit title → persisted, add-missed → new `open` item.
  All DB-verified.
- **Typed notes → Planner**: project + plan v1 + 7 phased dated tasks + 4 client commitments +
  stakeholder + 4 assignment proposals.
- **Assignment batch**: per-task AI reasons; "Change person" correctly refused for a role
  without `manage_staff` with an honest explanation; confirm cleared the feed.
- **Jarvis**: proposal creation (₹59,000 from the pricing table); **conversation memory
  tap-tested on device for the first time** — nounless "Make it warmer" routed to the proposal
  agent, cold-start transcript restore (text-only, per contract), **+** new chat with backend
  DELETE verified (0 turns remaining), turns strictly alternating in `assistant_turns`.
  *This closes the open item in handoff §8-pre2.*
- **Real SMTP send**: proposal email delivered, `status=sent`,
  `provider_message_id=smtp:ekaghni.mukherjee@gmail.com`.
- **Voice**: mic → live capture → auto-send → reply. Recognition garbled by laptop-speaker
  audio exactly as §6f documents; the pipeline itself is sound.
- **Ripple-break**: new-date past a client commitment refused —
  `{"accepted": false, "routed_to_lead": true, "breaks": ["client commitment '…' is due 24 Jul"]}`.
- **Demo booking**: clash warning "Heads up: Alpha already has a demo on 2026-07-31".
- **Follow-up queue**: filters, AI draft with instruction, complete-with-note, honest empty state.
- **Approvals**: reject → server redraft → new approval (verified twice).
- **Offline queue**: `adb reverse` removed → reject showed "Queued — will apply when you're back
  online" → reconnect → drained and applied, with the offline note carried into the redraft.
- **Project home**: objective, live LLM "What's blocking?", Why sheet with real planner traces,
  8 tabs, task detail with the full lifecycle action set.

## Checked and cleared (not bugs)

- **`RoleGate.has()` misuse** — all 13 call sites pass permission constants. Clean.
- **RoleGate matrix drift** — `core/auth/RoleGate.java` is an exact 1:1 mirror of
  `app/core/permissions.py`. Clean.
- **Approvals "message" filter chip** — display label only; the filter value is
  `outbound_message`. Clean.
- **Silent mic failure / silent reschedule gate** — both *do* surface honest messages, as
  `Toast`s. uiautomator dumps cannot capture toasts; screenshot polls missed them. Not defects.
- **Tab strip mis-tap** — automation artifact (TabLayout still settling after a fling), not the
  Phase-4 indicator-desync bug, which stayed fixed throughout.

---

# Fix order for the 2026-07-22 job — ALL DONE (HISTORICAL, not Round 7)

> ⚠️ **This is not the Round 7 plan.** It is the fix list for the *original* 2026-07-21/22
> simulation (F1–F26) and every item on it is genuinely finished. **Round 7's plan is
> `# Round 7 — fix order` above** — itself now mostly executed and tagged row by row.**

> **Scope of "ALL DONE":** this list is the fix plan for the findings of the original
> 2026-07-21/22 simulation, and every item on it is genuinely finished. It says nothing
> about **F28**, which was found much later (Round 4) and is **OPEN** — see the status
> table at the top of this file.

**✅ Every item below is complete (2026-07-23).** This ordered list is kept as the record of how
the job ran; there is nothing left to "resume". The status table at the top of this file is the
authority.

1. ~~**F9** (audio pipeline → planner) — biggest functional win; **subsumes F8**.~~ ✅
2. ~~**F4/F4b** (extraction prompt) — stops corrupting durable memory. Done FIRST, ahead of
   F9, so F9's live meeting tests would not write more false "school" facts on the way —
   worth repeating for any future prompt fix.~~ ✅
2b. ~~**F22** (the F9 duplication regression)~~ ✅ — adoption in `create_plan_version`;
    device-verified (8 rows for 8 pieces of work where the bug produced 12).
3. ~~**F1** (401 wipe)~~ ✅ — `AuthInterceptor.wipeSession()`, app `0.6.3-findings`;
   reproduced via a DB reseed on the Vivo.
4. ~~**F2** (services must call `request_approval`)~~ ✅ — opt-in
   `create_message(request_approval=True)`; **five** callers lacked it, only the two
   unreachable ones should have it. Also fixed a pre-existing dangling-approval bug.
5. ~~**F10**, **F3**~~ ✅ — `lead_service.apply_suggestion` is now the single writer for lead
   suggestions (five producers had dead Why? buttons, not one); the digest reads follow-ups
   and demos and has an honest empty state.
5b. ~~**F11/F6** (genericity sweep + the §6c correction)~~ ✅ — ~40 sites across three tiers,
    agent tools renamed, handoff §6c rewritten.
6. ~~**F17**, **F19** — the round-2 assistant findings: the context chip never filters, and the
   query agent cannot see `priority`.~~ ✅ 2026-07-23 — hybrid fix (deterministic
   `_effective_client` binding + a resolved-name context hint); `priority` added to both
   item views. New live script 6/6; device-verified on the Vivo (chip scopes; "most important"
   beats "soonest"). No app change, no schema change.
7. ~~**F7/F13/F14/F15/F12** — app copy pass.~~ ✅ 2026-07-23 — one build (`0.6.4-findings`) +
   the F15 digest-greeting backend tweak; device-verified. F13 was **2 sites** (project screen
   too); F15 was **2 halves** (empty state + greeting).
8. ~~**F23**~~ ✅ 2026-07-23 — deterministic prose-price fence; live guard 3/3.
   ~~**F24**~~ ✅ 2026-07-23 — warn at the review gate (`possible_duplicate_of` on GET /review +
   a ⚠ line in the review card, app `0.6.5-findings`); device-verified.
   ~~**F25**~~ ✅ 2026-07-23 — seed a skill taxonomy + constrain the planner + a deterministic
   coercion; live 3/3; on the Vivo the assignment screen shows real "expert skill match" reasons.
   **All fixable findings are done.** F26 is **accepted**
   (no action); F27 is **planned** as Phase 6 (no action here).
9. **F5** — did not reproduce in 6 recordings across two sessions; treat as *monitor*, not fix.
   **F16** is a scope reality (org_admin's screens are Phase 8), not a defect to fix here.

**Backend freeze note (updated 2026-07-23):** the named job "fix the FINDINGS items" is **COMPLETE
and the backend is RE-FROZEN** — do not change backend code without a new explicit unfreeze. While
the job ran, per handoff §7, every backend change kept the contract back-compatible, re-ran
pytest + dryrun + `verify_gap_endpoints` + `verify_generic_stakeholders --stub`, added or extended
a `verify_live_*` script, prove any schema change additive on a **copy** of
`data/salesplatform.db` first, and be verified on the real device — not on unit tests alone.
*(Every fix listed above followed this.)*

**Two process lessons from the 2026-07-22 session, both worth keeping:**
- **The dry-run suite earned its keep.** It caught a design error (W30) that every unit test
  and the live script missed — a project-resolution rule that quietly turned a genuinely new
  engagement into a merge. Run it after *every* engine change, not just at the end.
- **A prompt instruction is not a fence.** The free model ignored an explicit "never emit a
  near-duplicate" twice, live. Where a rule must hold, back it with deterministic code and
  unit-test both directions — what it must catch AND what it must not.
- **A green suite proves the scope you tested, not the property you wanted** (learned the hard
  way from **F22**). "No duplicates" was asserted over `project["tasks"]`, so duplication
  *between* the plan and the project-less review-gate rows passed 22/22 unnoticed. When the
  property is "this work appears once **for the user**", assert it over **everything the user
  would see for that lead** — query by `lead_id` with no other filter — not over the one
  collection the new code happens to produce. Twelve hours of green suites did not catch what
  one human conversation did.
- **A new test is worthless until you have watched it fail.** Both F22 tests were written,
  passed first time, and were then re-run with the fix deliberately disabled to confirm they
  went red *for the stated reason*. The integration test failed with the exact duplicate pair
  it exists to catch. This costs two minutes and is the only thing separating a test from a
  comment.
- **Read the consumer before choosing the fix.** F22's shape was settled by finding that
  `TasksRepository.myTasks()` already dedups **by id** — the app had been encoding the intended
  data model for two phases. The right option was the one that restored an invariant the client
  already assumed, and it needed no app change at all.
- **n=1 lies, in both directions** (2026-07-22 model bake-off). `gemini-2.5-flash-lite` was
  written off after a single `JSONDecodeError`, then passed four consecutive reruns at 8.5s
  each. `qwen3.5-flash` looked merely mediocre on one run and stalled 8 minutes on the next.
  Repeat every candidate, and state how many samples a claim rests on.
- **Verify scripts are code too — two of them were lying.**
  `verify_live_meeting_extraction.py` claimed "touches no database" while writing `llm_usage`
  rows into the **live** `salesplatform.db` (it set no `DATABASE_URL`), and
  `verify_generic_stakeholders.py` never exited after printing results — an "11-minute hang"
  that was really a finished run holding non-daemon aiosqlite threads. Both fixed; the second
  now runs in 4.1s. Audit the suite as carefully as the code it guards.

---

# Session residue — HISTORICAL, superseded by the 2026-07-22 reseed

> ⚠️ **Read this before the two sections below.** The live database was **reseeded on
> 2026-07-22** (deliberately — a reseed is F1's reproduction case). Everything the two
> sections below describe as "in the live DB" — Telaverge Solutions, Kirloskar Industries,
> Vidarbha Warehousing, Nashik Logistics Park, their projects, plans, meetings and
> transcripts — is **no longer in `data/salesplatform.db`**. It is preserved in
> **`data/salesplatform.db.pre-f1reseed-20260722`** (+ `-wal`).
>
> **F24's reproduction rows live in that backup, not in the current database.**
>
> The current database is a fresh `seed_demo.py` seed: 8 users + super admin, 3 leads
> (Delhi Public School, Green Valley School, Sunrise School), 0 notifications — plus the
> handful of rows created while verifying F1/F2/F10/F3 on the device.
> **For current state, read handoff §8-pre5.**

## Residue A — the original simulation (live-mode side effects)

- A **real Google Calendar event** was created: `5260l1giqftps4r0jb11ov6kvk` — Telaverge demo,
  31 Jul 14:30. Delete by hand if unwanted.
- One **real email** was SMTP-delivered to `mekaghni@telaverge.com` (the IBC proposal, standing
  in as the demo client).
- Three `outbound_messages` left at `pending_approval`: `intro` and `demo_invite` (both
  unreachable — F2) and one `follow_up` (reachable, mid redraft chain).
- The pre-simulation database is preserved at
  `data/salesplatform.db.presim-20260721-2242` (+ matching `-wal`). The current
  `data/salesplatform.db` is the fresh simulation DB.
- Backend left running on :8000 with the live `.env`; `adb reverse tcp:8000 tcp:8000` active;
  phone signed in as **Siva**, device auto-rotate restored.

---

## Residue B — the F4/F8/F9 fix session (2026-07-22)

- **The simulation's backend was STILL RUNNING** when this session began (PID from 21 Jul
  22:45), against the live DB with live SMTP — a second scheduler alongside any new one.
  Stopped. **Check for orphaned `run.py` processes at the start of every session:**
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`.
- **Ports 8000 AND 8001 were both taken by ComfyUI** this session (`{"mode":"comfy"}` /
  `{"mode":"segmentation"}`), so the backend ran on **:8010** with
  `adb reverse tcp:8000 tcp:8010`. The phone-side pref stays `http://127.0.0.1:8000`.
- DB backed up before any device work: **`data/salesplatform.db.pref4-20260722`** (+ `-wal`).
- **No mail was sent and no calendar event created** this session. The `outbound_message`
  approval on Siva's Home was deliberately left untouched (approving it would send real mail).
- New data, all real and intentional:
  - Lead **Kirloskar Industries** (Pune, contact Anil Kulkarni) → project *Kirloskar Safety
    Training Program*, plan **v2 active** (a first recording birthed it, a second merged).
    Its **v1 task titles carry cosmetic `(due …) — …` pollution** from before that fix landed;
    `due_date` is correct, titles are ugly. Harmless; clean or ignore.
  - Lead **Vidarbha Warehousing** (Nagpur, contact Meera Joshi) → project *Vidarbha
    Warehousing Forklift Safety Certification Program*, plan v1, 6 phased dated tasks. This is
    the run made against the **final shipped code** — clean titles, no duplicates.
  - **Telaverge Solutions** now has plan **v2 active** (the F4 regression recording merged
    into its existing project) — v1 superseded.
  - Three meetings on Telaverge/Kirloskar/Vidarbha with real audio through the phone mic.
- **F5 did not reproduce** in four recordings this session: all came back `language=en`,
  confidence 0.83–0.86, no hallucinated Devanagari. The difference from the simulation is
  that speech started ~3 s after tapping record instead of after a long silent lead-in —
  which supports the "trim leading silence" fix candidate in F5 over the `language="en"` one.
  Not a fix, just evidence.
- The Gemini embedding key now returns **429 "prepayment credits are depleted"** (was
  quota-exhausted before, §6d) — the memory index still builds nothing. Worth a decision.
- Phone: build **`0.6.2-findings`**, signed in as **Siva**, auto-rotate **restored to 1**.
- **The backend was deliberately STOPPED** at the end of this session so nothing is left
  orphaned (this session opened by finding the simulation's backend still running with live
  SMTP). `adb reverse tcp:8000 tcp:8010` is still mapped but points at a dead port — re-run
  it against whatever port the next backend takes.

---

## Residue C — the F22/F1/F2/F10/F3/F11 session (2026-07-22, this one)

- **The live DB was reseeded** (see the warning above). Backups retained, newest first:
  `salesplatform.db.pre-f1reseed-20260722`, `…pre-f22cleanup-20260722`, `…pref4-20260722`,
  `…presim-20260721-2242`.
- **Live-mode side effects: NONE.** No mail was sent and no calendar event created. The
  backend ran with `EMAIL_MODE=dry_run CALENDAR_MODE=off` for all device work; `.env` itself
  is untouched and still LIVE (`EMAIL_MODE=smtp`, `CALENDAR_MODE=google`). The one demo invite
  approved during F2's device test went out as `provider_message_id = dry_run:…outbox/….eml`,
  with zero SMTP lines in the log.
- **One accidental write, disclosed:** ~5 `llm_usage` accounting rows landed in the live DB
  before `verify_live_meeting_extraction.py`'s missing `DATABASE_URL` was found and fixed. No
  leads, tasks or messages touched.
- **F22's duplicates were cleaned before the reseed** (9 rows cancelled with an explanatory
  `result_note`, 3 titles de-polluted) — that work is now only visible in the
  `…pre-f22cleanup-20260722` backup, since the reseed followed it.
- **In the current DB from device verification:** a demo booked on Delhi Public School
  (14 Aug, invite approved and dry-run "sent"), and a recorded meeting on Green Valley School
  that produced a lead-state suggestion with a working **Why?** trace. Both intentional.
- **Phone:** Vivo `10BFBT0TXJ001NP`, build **`0.6.3-findings`**, signed in as **Siva**.
- **Backend:** left running on **:9010** with `adb reverse tcp:8000 tcp:9010`.
  **Stop it before ending a session** (§6g's orphaned-backend rule).
