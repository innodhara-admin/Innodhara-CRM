# Session handoff — 28 August 2026

This file records what was done in one working session, and everything that was
learned about this codebase along the way. It exists so the next Claude session
does not have to rediscover all of it.

Written in plain language on purpose.

---

## READ THIS FIRST: current state on 13 October 2026 (IST)

This section is the one place that says what is true now. Everything below it
is a dated history of earlier sessions, kept for the reasons behind the code.
Where history and this section disagree, this section wins; where this section
and the CODE disagree, the code wins. Docs in this repo have lagged the code
before (a 1 Oct reading of this file raised "open problems" the code had
already fixed), so check the code before stating anything as fact.

**Stale history below, on purpose:** §2's public URL and any `noninfluential-...` link (that address was retired 24 Sep 2026),
§5 "State on 31 August 2026", and every per-session "state" heading.

### Live server (verified 2 Oct 2026, 10:23 UTC)

| thing | value |
|---|---|
| VM | `telaverge@172.16.10.55`, reachable only while the developer's OpenVPN is up |
| code | `/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project` (own git repo; checked-out branch `feature/docx-proposal-templates`, NOT `master` (verified 2 Oct 2026); about 150 uncommitted or untracked paths that belong to the developer: never commit unless asked) |
| service | systemd `salesforce-app-restart` (uvicorn on 8010, no hot reload; ngrok in the same group) |
| health | `curl -s http://127.0.0.1:8010/health` |
| public URL | `https://unaltered-uncommon-bottling.ngrok-free.dev` |
| last restart | 12 Oct 2026 20:49:50 UTC (proposal PDF converter, §25 of `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`); before that 18:31 for the six fixes of §24 |
| daily jobs marker | `data/storage/scheduler_last_daily.txt` holds the UTC date of the last daily run; restart only when it holds today's UTC date, otherwise the daily jobs run again |
| live models (`.env` overrides code defaults) | `LLM_PROVIDER=openrouter`; fast `openai/gpt-5.4-nano` (router and every agent); strong `google/gemini-2.5-flash` (proposal and MOU filling, the Planner's plans and merges (`app/ai/planning.py` defaults to strong), the people check, the day reader) |
| PDF converter | LibreOffice 26.2.6 at `/opt/libreoffice26.2` (fallback 7.3 at `/usr/bin/soffice`), fonts folder `../../pdf_fonts` (outside git); settings `LIBREOFFICE_BIN`, `LIBREOFFICE_FALLBACK_BIN`, `PDF_FONTS_DIR` in `.env` (§25) |
| database | SQLite in WAL mode, `data/salesplatform.db`; copy only with Python's sqlite3 backup API, read-only |

### What is live (all of it, as of the last restart)

Detail per item in `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`:
§12 the four customer asks (client chip, recording upload, blocked on a
colleague, scheduled meetings), §13 notifications flood, §14 meeting card,
§15 clashes, §16 no duplicate client names, §17 confirm once and "Approve
plan" (17.1 to 17.6), §18 Jarvis proposal loop, §19 meeting days ("next
<weekday>" confirmed, the strong-model day reader, no past days, a
recording's note), §20 assignments name their client and only the ticked
ones are confirmed (backend live 2 Oct 09:50 UTC), §21 Jarvis redesign and
chat-history sidebar (`GET /assistant/sessions`, backend live 2 Oct 10:23
UTC). The app with §20 and §21 is installed on the developer's Vivo (2 Oct 15:57 IST).

### LIVE: "open straight away" for a sales lead (7 Oct 2026)

A sales lead can create a lead already open, with its contact (name,
designation, email; phone optional), from the New Lead form and from Jarvis,
which asks in conversation and always spells the email back. Everyone else is
unchanged. Detail: §23 of `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`;
spec, plan and ledger in the Android folder (`docs/superpowers/...
2026-10-07-open-at-creation*`). Built and tested in the STAGING copy only
(staging 2 failed / 1,531 passed vs live 2 / 1,495, 7 Oct 15:09 UTC; app 224
unit tests). Changed files: `app/services/lead_service.py`, `app/api/leads.py`,
`app/ai/client_draft.py`, `app/ai/agents/client_agent.py`,
`tests/test_client_creation.py`, new `tests/test_open_at_creation.py`. Waiting
LIVE since the restart of 7 Oct 2026 15:18 UTC (backups
`../backup_2026-10-07/open_at_creation/`); app installed on the Vivo 7 Oct
20:48 IST (versionCode 20733). The email spell-back loop the developer hit
on 7 Oct is fixed and live since 12 Oct 01:22 UTC (§23.5).

### Tests

- The suite reads the live `.env`, so the model in tests is REAL. Every model
  call added must be stubbed in `tests/conftest.py` (done for
  `planning.review_meeting_people` and `day_reading.read_when`). Test fakes
  script answers in order per module, so a new model call belongs in its own
  module.
- Last measured, 2 Oct 2026 10:10 UTC, side by side: live code before §21
  1 failed / 1,472 passed; with §21 (staging) 1 failed / 1,478 passed
  (1,479 tests; the 6 new are `tests/test_assistant_sessions.py`; §20 added
  `tests/test_assignment_selection.py`, 3). The one
  failure both times: `test_the_worst_neglected_client_is_first`, which books
  a fixed 2026-08-31 date and failed at an hour when IST and UTC agreed, so
  it may be a stale fixed-date test rather than an hour-sensitive one
  (not yet confirmed).
- Clock-sensitive: `test_what_is_late` x3, `test_demos_followups` x1,
  `test_relationship_screens` x1 fail when IST and UTC dates differ.
- From 3 Oct 2026,
  `tests/test_scheduled_meetings.py::test_adding_a_contact_later_drafts_the_waiting_invite`
  fails on its own (it books 2 Oct 2026 and expects an upcoming meeting).
- Always measure your own baseline before changing anything.

### Field location: LIVE since the restart of 2 Oct 2026 18:52 UTC

App installed on the Vivo 3 Oct 00:23 IST; not yet tried by hand. Detail: §22 of
`docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` and the ledger in the Android folder,
`docs/superpowers/plans/2026-10-02-field-location.progress.md`. One smoke-test reading for
rahul@yuvipep.com (a sales agent) sits in `location_pings` until the developer
says to delete it (§22.4). New table `location_pings` (reset taxonomy 4/2/8/50, 64 tables),
permission `track_locations` (org admin), router `/api/v1/locations`, and
18 more tests (staging 6 failed / 1,491 passed vs live 6 / 1,473 at the same
moment, 2 Oct 18:40 UTC, when IST and UTC dates differed).

### Live org "Innodhara" (created 5 Oct 2026, no code change)

Created in the dashboard Setup Console (`/dashboard`) by hand, through the forms
(no bundle import): slug `innodhara`, domain innodhara.com; Admin
(admin@innodhara.com, org_admin), Ajith Kumar and Neelesh (sales_lead), Ekaghni
Mukherjee (sales_agent), all in the sales department; skills (general plus a few
specialisms). YuviPep's catalogue was copied from YuviPep's live data: offerings
DCCH, TAA, ORTE, IBC with rate cards v1 (all four deleted 12 Oct 2026 and
replaced by 8 products, next section); the four message templates; DCCH
playbooks (preparation, delivery, closure); 14 of YuviPep's 16 approval rules;
the same dials (AI budget 50); demo team "Commissioning Team A"; vendor RackLine
Logistics. Proposal templates and MOUs left blank on purpose; email and calendar
credentials not set. Waiting for the developer's decision: three plan_change rules
are joint with operations_lead and Innodhara has none (corrected 7 Oct from the
code: they DO complete, as plain sales-lead approvals, because the joint slot
is only added when an operations lead exists, `approval_engine.py:236-238`;
the question is only whether joint was wanted);
the DCCH playbook skills are held by nobody; YuviPep's two `thread_owner`
outbound rules cannot be set from the console (its approver list has no
thread_owner); 3 of the 4 offerings are YuviPep's old data-centre demo.

### Innodhara catalogue replaced: 8 products with Word templates (12 Oct 2026, no code change)

Done by hand in the live Dashboard (Claude in Chrome; the developer signed in
as admin@innodhara.com and picked the four large files in the file dialog).
The 4 copied offerings DCCH, TAA, ORTE and IBC were deleted through item 4
(none was used by a project, proposal, fill or MOU; the delete also removed
their 4 rate cards and DCCH's 3 playbooks, `admin.py:938-949`). JSON backup of
those rows: `../backup_2026-10-12/innodhara_old_products/rows.json`.

Every template below is v1, current, document type proposal, kind
`docx_simple` ("Word document, tags filled by the assistant"), analysis
`ready`, image reading (`docx_ocr` job) done, stored SHA-256 equal to the
developer's file. No rate card on purpose: `proposal_fill_service.py:942-986`
makes it optional for this kind (side effects: no project value estimate,
`planner_engine.py:1517-1527`; checklist item 5 and go-live show "no rate card").

| code | product | program_id | template_id | doc_id | tags / always asked |
|---|---|---|---|---|---|
| CSL-F | Composite Skill Lab - Foundation | ee883c832b0146049fd77481245bb4b9 | 034395bcfa4c41bf9c32a33a6c5f0a42 | 3d2630127423435c9876efd1bdaf040d | 6 / 2 |
| CSL-I | Composite Skill Lab - Intermediate | 039df96be7204c97bea3ae1f4c087154 | b6b44222c73a491f958ec0d86f0eb80b | 091414cc584f4dc1a45f9ef0855c448d | 6 / 2 |
| CSL-A | Composite Skill Lab - Advanced | cb40cd6db9a64e8693e168b54f7b88e7 | 85c9cccafc6e453984b911f77db01603 | 4547a2649e984c47a8ee280b5e7e3254 | 6 / 2 |
| YFIL | Futuristic Innovation Lab | efe1aac60004465d912b48d4f9aca331 | 97f574e6733e435bbf034049e7c6be78 | 2fd536badeca4ec7b2b8eed890fd84b3 | 7 / 1 |
| Y360-CBSE-F | YuviPep 360 CBSE with Foundation Lab | 363870c9a8024cec87c0f47cdc3ecd43 | 947dee4883774d7493fb94e47340cf8b | 860be07301de409bbd17af9c6dacdcbb | 11 / 7 |
| Y360-CBSE-I | YuviPep 360 CBSE with Intermediate Lab | 72c8eeddef264f8fb564712dda819496 | ffa8ade6458b4968b0beff1a2b9e4f6b | bd81655185da4ca8be8ca01cfe05aa00 | 11 / 7 |
| Y360-CBSE-A | YuviPep 360 CBSE with Advanced Lab | c7034f1654e746dfa13ad8ec6195bd1a | b16b840464fd4e6998edb114b00cfe8a | 20ee8aaee73f473d95e74306f1a0cd06 | 11 / 7 |
| Y360-NCBSE | YuviPep 360 Non-CBSE (IBC) | 345adef519214b2f93fb0331663510c6 | e09d181ef47341baab5aee752b4aa7e5 | a0b3eacad90a4b69a3cc881705703e77 | 9 / 5 |

Traps learned: item 6's offering picker defaults to the first product
(`ProposalTemplates.tsx:67`), pick it every time; the upload limit is 25 MiB =
26,214,400 bytes (`docx_template_service.py:31`), nginx allows 512 MB; a bare
`<ask>` (no colon) is a SEMANTIC tag the model fills silently, only `<ask:...>`
is always asked (`tags.py:76,99-112`); `analysis_status` is "ready" at once,
the `jobs` row `docx_ocr` says when image reading finished; Claude in Chrome
cannot attach files over 10 MB (the developer picks them); the console's
delete click may be blocked by Claude Code's auto-mode classifier. Not yet
done: no proposal has been generated from any of the 8 (the 21-24 MB ones are
larger than any file proven at proposal time, 14.8 MB). VM disk was 98% full
(9.6 GB free) on 12 Oct.

### LIVE: six fixes from the 12 Oct live Jarvis test (§24)

A live test as Ajith (Innodhara) found, and this session fixed: proposal PDFs
showing `<School name>` on the cover and every footer (Title-bound controls);
"Yes, these are all correct" looping on create_proposal; corrections at the
review refused; the open-client contact loop; Innodhara email never sending
(Zoho, not gmail: host now picked from the account's MX); a dead proposal email
returned forever. Plus: a corrected value no longer repeats its row label.
Detail, tests and what is still open: §24 of
`docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`. Suites: staging final 2
failed / 1,574 passed (the two known failures). Innodhara's first email was
sent 12 Oct 18:32 UTC. Test data left in live Innodhara: lead "Test School
Sunrise" and its proposal and messages (developer to decide about deleting).

### LIVE: proposal PDFs look like the Word template (§25, 12 Oct 2026 20:49:50 UTC)

The §24.1 report (tiny cover title, pages shifted, infrastructure tables on
top of each other) was the CONVERTER, not the fill: the untouched template
printed the same way, and Word opens our .docx correctly. LibreOffice 7.3
dropped the cover's content-control formatting, the VM had none of the
templates' fonts (body text is Aptos), and 7.3 cannot place Word's floating
tables. Now: LibreOffice 26.2 in /opt with a fonts folder only the converter
sees, a prepared copy for LibreOffice (`app/services/docx/lo_compat.py`), and
a fallback to 7.3 after 15 s. 7 of 8 Innodhara templates now match Word's
pages (median under 1% of pixels different). Open: the CBSE Foundation
template makes every modern LibreOffice loop forever, so it falls back to 7.3
(about 18 s, not like Word) until the owner makes its "Healthcare and
Wellness" table non-floating in Word and re-uploads; YuviPep's two Innovation
Lab templates use Tahoma/Trebuchet (no free versions) and print as before.
Detail, limits and tests: §25 of `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`.

Also found on 13 Oct while reading the code (NOT fixed, ask before acting):
`proposal_email_service._live_key` treats a `failed` email as dead although
`failed` is the retrying state (`jobs/sender.py:69-74`), so a "send it" during
a retry can lead to two emails; `email_service._smtp_server_for` caches a
failed MX lookup until the next restart; `ensure_rendered_files`
(`proposal_email_service.py:41`) only converts kind "docx", so a docx_simple
proposal with no PDF would get a plain re-rendered document on send/download.

### Tools on the VM

- `/home/telaverge/Ekaghni/sfai_staging_1oct`: a copy of the project for
  testing changes (`.venv` symlinked to live; `data` points to
  `sfai_staging_data`, a copy of the live DB from 1 Oct). Re-sync `app/`,
  `tests/` and `docs/` from live before use; its code matched live at the
  2 Oct restart.
- `/home/telaverge/Ekaghni/sfai_replay/`: `replay2.py` (proposal
  conversations), `replay_dates.py` (15 meeting-date conversations),
  `replay_rec.py` (re-runs real recordings' extraction). Each copies the live
  DB read-only into a sandbox with email dry-run, calendar off, push off.
  Delete the sandbox folders afterwards.
- Backups of replaced files: `../backup_2026-09-23`, `-09-25`, `-09-26`,
  `-10-01`, `-10-02` (and `-10-02/meeting_days/`,
  `-10-02/assignment_selection/`, `-10-02/jarvis_history/`).

### Open, not done (ask the developer before acting)

Each was seen in the code or data on 1 or 2 Oct 2026; re-check before relying
on it.
- "send it" right after a proposal approval card sometimes routes to the
  email agent, which drafts a separate email.
- The proposal template asks the salesperson for YuviPep's own address.
- The old "Accounts Head" contact on Ollama School of Commerce is still there.
- The 30 Sep BS Carmel Google Calendar event was left (it is in the past).
- The public download page served app v0.7.4 on 29 Sep; the phone runs
  0.8.0-voice debug builds. Check before sharing the link.
- Jarvis asks "which day?" for "in two days at 4 pm" (the 23 Sep guard does
  not count it as naming a day).
- `extraction.resolve_day_words` reads "last Friday" as the coming Friday.
- An approver's "move it to next Thursday" on a rejected invite is read by the
  fast model without the weekday in its prompt.
- Small: doc §17.6 says an out-of-range people-check score counts as no
  match, but `planning.parse_people_review` clamps it to 0..1; the Approvals
  inbox in the app has no filter chip for `meeting_plan`; the header of
  `tests/conftest.py` still says tests never hit the network.

---

## 1. Where everything lives

**Backend** — on a VM, not on this laptop.

```
telaverge@172.16.10.55
/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project
```

Python, FastAPI, SQLAlchemy (async), SQLite. It is its own git repository.

**Android app** — on the laptop.

```
C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI
```

Java (not Kotlin), Fragments, Retrofit, Hilt, Room. Two build flavours,
`org` and `platform`. The one that ships is `org`.

### Getting onto the VM

The VM is only reachable while the user's OVPN tunnel is up. Ask them to
confirm it is connected.

This laptop has **no `sshpass` and no `plink`**, so a password cannot be piped
into `ssh` the usual way. What works is an `SSH_ASKPASS` helper:

```sh
# askpass.sh
#!/bin/sh
printf '%s\n' "<the password>"

# then
export SSH_ASKPASS=/path/to/askpass.sh
export SSH_ASKPASS_REQUIRE=force
export DISPLAY=:0
ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password \
    -o PubkeyAuthentication=no -n telaverge@172.16.10.55 '<command>'
```

Make two wrappers: one with `-n` for plain commands, and one **without** `-n`
so you can pipe a file in with `cat local | wrapper "cat > remote"`. There is
no scp helper set up.

Ask the user for the password each session. Do not write it into the repo.

The connection drops now and then with `Connection timed out` even when the
tunnel is healthy. Just retry. Each command is a fresh session, so shell state
does not carry over — chain anything that must run together.

### Running things

```sh
# backend tests, from Complete_Project
./.venv/bin/python -m pytest -q

# android, from the project root
export JAVA_HOME="/c/Program Files/Android/Android Studio/jbr"   # Java 8 on PATH is too old
./gradlew :app:assembleOrgDebug
./gradlew :app:testOrgDebugUnitTest
```

---

## 2. The live server

The backend runs as a systemd service and is exposed to the internet.

| thing | value |
|---|---|
| service | `salesforce-app-restart.service` |
| backend port | **8010** |
| nginx | listens on 127.0.0.1:8080, proxies `/` to 8010 |
| public URL | retired 24 Sep 2026; now `https://unaltered-uncommon-bottling.ngrok-free.dev` |
| restart | `sudo systemctl restart salesforce-app-restart` (password needed) |

**Watch out:** port **8000** is a *different* application
(`yuvipep_learning_platform_chatbot`). Do not touch it. Early in this session it
was mistaken for the backend.

Restarting the service tears down the whole group, ngrok included, and brings
both back. The ngrok domain is pinned with `--domain=`, so **the public URL
survives a restart**. A restart takes about 6 seconds.

The database is a single SQLite file:
`Complete_Project/data/salesplatform.db`

---

## 3. Rules of this codebase, learned the hard way

These are not obvious from reading the code and each one can waste an hour.

1. **There is no Alembic.** `init_db()` runs `Base.metadata.create_all`, which
   creates missing **tables** but never adds a **column** to a table that
   already exists. Any new column needs a hand-written, idempotent
   `ALTER TABLE` inside `_apply_light_migrations()` in `app/database.py`.
   Skip that and it works on a fresh database and silently fails on the live
   one.

2. **The AI never changes a lead's state.** It only writes `suggested_state`
   and `suggested_state_reason`, plus an `ai_decisions` row. A person confirms.

   `lead_service.change_state()` used to have exactly **one** caller. As of
   31 Aug 2026 it has **two**, and both are endpoints where a person acted:

   - `PATCH /leads/{id}/state` — the ordinary path.
   - `POST /leads/{id}/relationship/opportunity/accept` — a relationship
     manager confirming a client wants to buy again, which moves the lead
     `closed -> open`. It is the single lead-state move that role can make,
     and the boundary of the role rather than a hole in it: they hold no
     `manage_leads`, so `PATCH /state` refuses them every other transition.

   The invariant that matters is unchanged and is worth stating precisely:
   **no engine, background job or AI agent ever moves a lead.** Only a
   human-initiated request does. If you add a third caller, it had better be
   an endpoint too.

3. **`test_genericity.py` walks `app/**/*.py`** and fails if an industry word
   ("school", "principal", "student"…) reaches a prompt. Client-facing prose
   must live **outside** `app/`. This is recorded as decision D19.

4. **The Android permission matrix is checked against the backend on every
   build.** `RoleGate.java` must match
   `app/src/test/resources/contract/permissions.json`, which is a copy of the
   backend's matrix. Change the backend and not the fixture, and the Android
   build fails. This is deliberate.

5. **Unknown roles degrade safely.** `MainActivity.buildTabsForRole()` ends
   with a generic Home / Tasks / Assistant fallback, so the backend can add a
   role before the app knows about it.

6. **The working tree has ~68 modified files that belong to the user.**
   (It said 53; measured 68 on 31 Aug 2026 — it grows, so count it, don't
   quote it.) Never commit them by accident. Stage explicit paths, never
   `git add -A`.

7. **Every new table must be classified in `app/core/reset_taxonomy.py`.**
   `tests/test_reset_taxonomy.py` asserts that KEEP + CONFIG + REPLACE + WIPE
   is a complete partition of `Base.metadata`, and it hard-codes the bucket
   sizes and the total table count. Add a table and two tests fail until you
   say which bucket it belongs in and update the numbers. That is deliberate.
   (Currently 4/2/7/44 across 57 tables — `relationship_engagements` and
   `lead_cycles` both went into WIPE, both immediately before `leads`.)

   Ordering inside WIPE matters too: deletion is child-before-parent, the
   schema declares no `ondelete=` anywhere, and SQLite does not enforce
   foreign keys by default. A table with an FK to `leads` goes before `leads`.

8. **Nothing regenerates `contract/permissions.json`.** The README calls it
   "generated" and `RoleGateTest` treats it as authoritative, but
   `capture_android_contract.py` does not write it and no other script does.
   Regenerate it by dumping `_MATRIX` rather than hand-editing, and keep the
   **CRLF** line endings the file already has.

9. **`scripts/verify_*.py` are not covered by pytest and rot silently.**
   Six of them were dead from the pre-sales change and nobody noticed, because
   nothing runs them in CI. `POST /leads` creates in `cold_calling`, and both
   `get_workable_lead` (every `/meetings/` route) and the state machine refuse
   it — so a script that creates a lead and immediately works it dies on the
   spot and takes every later check down with it.
   `verify_gap_endpoints.py` had silently stopped running G3 altogether.

   All six now open the lead first. If you change lead lifecycle rules again,
   re-run these by hand; the test suite will not tell you.

   Most of them refuse to start without a real LLM provider, so to exercise
   them cheaply: copy the script, lift only that assertion in the copy, and run
   the copy with `LLM_PROVIDER=stub` (an env var beats `.env`).
   `verify_generic_stakeholders.py` has a proper `--stub` flag and needs none
   of that.

10. **Three different model switches. Do not confuse them.** This org runs
    almost entirely on local models; only text generation leaves the machine.

    | job | setting | value | where it runs |
    |---|---|---|---|
    | Text generation | `LLM_PROVIDER` | `openrouter` (`openai/gpt-5.4-nano` fast) | remote API |
    | Memory embeddings (RAG) | `EMBEDDING_PROVIDER` | `local` (`intfloat/multilingual-e5-base`, CPU, 768-dim) | **on the VM** |
    | Speech to text | `STT_PROVIDER` | `whisper_local` (`WHISPER_MODEL=large`) | **on the VM** |

    **Gemini is not used at all in normal operation.** `llm_model_fast` /
    `llm_model_strong` still hold Gemini model names in `config.py`, but those
    are defaults read only by `GeminiProvider`; with `LLM_PROVIDER=openrouter`
    the OpenRouter models are used instead. Seeing a Gemini name in the config
    does not mean Gemini is being called.

    **The trap that produced a false alarm here:** `app/ai/llm.py:571` is
    `providers.get(self.settings.llm_provider, GeminiProvider)()`, and the
    registry holds only `claude`, `openrouter`, `gemini`. **Any unrecognised
    value silently becomes Gemini** — including `stub`, and including a typo.
    Setting `LLM_PROVIDER=stub` therefore does NOT stub generation; it routes
    every call to Gemini, whose prepayment credits are depleted
    (`429 RESOURCE_EXHAUSTED`), which then looks like a provider bug and is not.

    `"stub"` is only honoured in two places — `app/ai/memory.py:124` (falls
    back to hash embeddings) and `app/engines/nlu.py:27`. The model layer
    knows nothing about it. Engines have deterministic fallbacks, which is why
    `verify_generic_stakeholders.py --stub` still passes 21/21.

11. **Four tests are flaky by time of day.** `test_what_is_late` (3 tests) and
   `test_demos_followups` (1) compare "today" in the org's timezone
   (`Asia/Kolkata`) against a server running in UTC. For part of each day the
   two disagree and the tests fail. They failed at the start of this session
   and passed at the end, with no change from us. **Do not assume you broke
   them, and do not assume you fixed them.**

---

## 4. What was built this session

### 4a. Pre-sales / cold calling — DONE and LIVE on the backend

A new stage before a lead becomes real. A lead is created, assigned to a sales
agent, and sits in `cold_calling` until that agent phones the client and opens
it.

**Backend files changed**

| file | change |
|---|---|
| `app/core/constants.py` | new `LeadState.COLD_CALLING`; transitions `cold_calling -> {open, lost_for_now}` |
| `app/core/permissions.py` | new `can_leave_cold_calling()` |
| `app/api/leads.py` | create in `cold_calling`; notify owner; ownership guard on state change; team fan-out on open; `GET /leads/assignable-owners`; `GET /leads/recently-opened`; `owner_name` and actor names on history |
| `app/services/lead_service.py` | new `get_workable_lead()` |
| `app/api/meetings.py` | 3 call sites now refuse meetings on a cold-calling lead |
| `app/models/organisation.py` | new `org_settings.lead_open_feed_days` (default 3) |
| `app/database.py` | the `ALTER TABLE` for that column |

**Android files changed**

| file | change |
|---|---|
| `dto/LeadRequests.java` | `ownerId` on create |
| `dto/LeadDetailResponse.java` | `ownerName`, and `by` on each history row |
| `dto/RecentlyOpenedDto.java` | new |
| `net/ApiService.java` | the two new endpoints |
| `leads/LeadsRepository.java` | the two new calls |
| `leads/LeadStates.java` | `cold_calling` plus `isPreSales()` |
| `leads/NewLeadSheet.java` | owner dropdown |
| `leads/LeadDetailFragment.java` | tab gating, owner line, timeline, open/drop actions |
| `leads/LeadTimelineView.java` | new — the journey strip, custom-drawn |
| `leads/BulkLeadImport(er).java` | `owner` per row, resolved by email then name |
| `home/HomeViewModel.java`, `HomeFragment.java` | the "newly opened" cards |
| `res/values/strings.xml`, `colors.xml`, layouts | supporting bits |

**Rules that were agreed**

- Only the **owner** can move a lead out of `cold_calling` (org admin is
  break-glass). Not even the sales lead who assigned it.
- Dropping a dead cold call goes to `lost_for_now`, never `closed`.
  `closed` means won and delivered, and mixing them corrupts reporting.
- The owner dropdown lists **sales agents only**.
- The "now open" announcement shows for 3 days, configurable per org.
- Existing leads were **not** touched. Only new leads start in `cold_calling`.

**Tests:** `tests/test_pre_sales.py` — 19 new tests, all passing.

Five existing test files needed updating, because they asserted that a new lead
is immediately `open` — which is exactly what changed. A shared helper
`open_lead()` was added to `tests/conftest.py` and called where a test needs a
workable lead.

### 4b. Greeting fixed — DONE and LIVE

The daily briefing always said "Good morning", even at 3am. It was **not** in
the Android app — the app's own string is "Hello, %s". It came from the backend
digest (`app/engines/assistant_engine.py`).

New `_greeting_word(hour)` using the **org's** timezone, not the server's:

| local time | greeting |
|---|---|
| 05:00–11:59 | Good morning |
| 12:00–16:59 | Good afternoon |
| 17:00–20:59 | Good evening |
| 21:00–04:59 | Working late |

The empty-state line "Nothing needs you this morning" became "right now".
Two dry-run scripts that asserted the literal words "Good morning" were fixed.

### 4c. Meetings tab moved before History — DONE, app only

In `LeadDetailFragment` the tab order is now
`Overview · Contacts · Projects · Notebook · Meetings · History`.

Note for whoever touches this: the `TAB_*` constants **are** the tab positions,
and the titles array is what builds the strip. Change one without the other and
the wrong tab renders with no compile error.

### 4d. Documentation endpoint — DONE and LIVE

A human-readable page explaining the pre-sales flow.

```
https://noninfluential-lamonica-unobservantly.ngrok-free.dev/documentation/pre-sales
https://noninfluential-lamonica-unobservantly.ngrok-free.dev/documentation      (index)
```

- Router: `app/api/documentation.py`, mounted **outside** `/api/v1`.
- Page: `Complete_Project/documentation/pre-sales.html`, deliberately outside
  `app/` because of rule 3 above.
- Pages are served from an explicit registry dict, not a directory listing, so
  there is no path-traversal risk.
- **The pages are public** — no login. A phone browser opening a shared link
  cannot send a bearer token. Write them assuming anyone with the link can
  read them.
- The file is read per request, so **editing the HTML needs no restart**.
- Styled to match the existing download page
  (`APK_and_Manual/index.html`): Innodhara navy `#1a3d7c`, amber `#f5a623`.

### 4e. Jarvis voice mode + avatars — DONE and LIVE (15–17 Sep 2026)

Full detail, protocol and the Android side: **`docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`**
(section 9 is the app as built). In short:

- Backend: client creation by conversation, `WS /api/v1/assistant/voice`,
  `/voice/turn`, `/voice/speak`, `/voice/config`; Whisper `turbo` for speech
  in, Kokoro for speech out, and (17 Sep) a per-session server voice.
  **These files are still untracked in git** (`app/ai/tts.py`,
  `app/api/voice.py`, `tests/test_voice_mode.py`, the doc) — not committed on
  purpose; pre-change copies are in `/home/telaverge/Ekaghni/backup_voice_20260917/`.
- Android 0.8.0-voice (installed on the user's Vivo, adb serial
  `10BFBT0TXJ001NP`): voice screen with six swipeable Duix avatars, each with
  its own voice. Built on the Duix SDK from the user's LinguaAI project.
- Backend suite on 17 Sep: 5 failed / 1151 passed (the usual date-sensitive five).
- Speech accuracy (later 17 Sep, doc section 10): measured on 63 real phone
  recordings, then switched voice turns to Whisper large-v3 (en/hi/kn only,
  float16 weights, richer name hint) - names heard right 66% -> 82%, +0.2 s
  per turn; minimum utterance 150 ms (a short "Yes." was dropped); owner
  near-misses ("Ria Nair") are now asked about. LIVE (service restarted 17 Sep).
  Suite: 1 failed / 1169 passed. Backups: /home/telaverge/Ekaghni/backup_stt_20260917/.
  Evaluation harness (outside the repo): /home/telaverge/Ekaghni/stt_eval/.
- Customer bug round (19-21 Sep, doc section 11): dictation was Whisper tiny
  with no language limit and returned Russian -> turbo + en/hi/kn + name hint
  (.env DICTATION_WHISPER_MODEL was pinned to tiny; changed there too);
  meeting action items now carry due_date to the screen; phone numbers are
  spoken digit by digit; VOICE_VAD_SILENCE_MS 600 -> 900 (Jarvis interrupted);
  new move_client_state tool, with PATCH /leads/{id}/state and Jarvis sharing
  lead_service.change_state_for_user. Android: assistant title layout, the
  approval screen after deciding, long-form dictation, 5 avatars (Aixia out),
  card readability. Suite 1 failed / 1195 passed (after the Kannada round); app 121 tests.
  Backups: /home/telaverge/Ekaghni/backup_bugs_20260921/ (incl. env.backup)
  and C:/Users/Ekaghni/AndroidStudioProjects/backup_bugs_20260921.
- Next round asked for on 21 Sep (task->client link on the dashboard, a
  meeting path separate from demos with its own invite mail and a
  redraft-on-reject loop, blocked-on-a-colleague reaching that colleague, and
  uploading a recording file): researched 23 Sep, NOTHING built. Findings and
  where each change lands: docs/NEXT_FEATURES_RESEARCH.md.

---

## 5. State on 31 August 2026 (history; see READ THIS FIRST at the top)

| | state |
|---|---|
| Backend tests | 371 passing, 0 failing as of 31 Aug 2026 00:0x UTC. It was `4 failed, 350 passed` an hour earlier — same code, different hour. See rule 11 and measure your own baseline before you change anything. |
| Android build | `assembleOrgDebug` succeeds; unit tests pass |
| Backend deployed | **yes** — pre-sales 28 Aug; Relationship Manager (all 7 steps) 31 Aug 02:40 UTC. 57 tables, data verified intact. |
| Android deployed | **no** — the APK is built but not installed on phones |
| Backup | `/home/telaverge/Ekaghni/Salesforce_AI_Project_BACKUP_20260828_192219.tar.gz` (3.2 GB) |
| DB snapshot before the migration | `Complete_Project/data/salesplatform_PRE_PRESALES_20260828_202841.db` |

**One consequence worth remembering:** the backend is live with pre-sales but
the phones still run the old app. So a lead created from the current app lands
in `cold_calling` owned by whoever created it, and only that person can open
it. That is coherent, not broken, but it will confuse people until the new APK
ships.

There is no `rar` on the VM, only `unrar`. Backups are `tar` + `pigz`.

---

## 6. Where the design documents are

| file | what it is |
|---|---|
| `Complete_Project/docs/superpowers/specs/2026-08-28-pre-sales-cold-calling-design.md` | the pre-sales design, as built |
| `Complete_Project/docs/RELATIONSHIP_MANAGER_PLAN.md` | the Relationship Manager plan (since built) |
| `Complete_Project/docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` | voice mode + client creation, as built (backend and app) |
| `Complete_Project/docs/SESSION_HANDOFF.md` | this file |

---

## 7. How the user likes to work

- They want the code studied, not the documents trusted. Several documents in
  this repo are out of date. Read the code.
- They care most about **not breaking what already works**. Run the full test
  suite before and after every change and compare.
- They do not want git ceremony. Committing is not expected unless asked.
- They want plain language in anything written for them or their manager.
- They approve deployment explicitly. Ask before restarting the live service.


---

## Session 23-30 September 2026 (handover)

Everything below is live: the service was restarted and the debug APK is
installed on the developer's Vivo. Detail per change is in
`docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` §12-16.

- §12 the four customer asks: task client chip and client links in the Home
  briefing; recording file upload; "blocked on a colleague" notifies them and
  shows a Home card; meetings separate from demos (`ScheduledMeeting`, invite
  email with to/cc/bcc in Approvals, reject-with-reason redraft, scheduled
  from recordings, Jarvis `schedule_meeting` / `list_meetings` /
  `cancel_meeting`).
- §12.6 live test of Jarvis meetings with the real model: day/time must be in
  the person's own words (`meeting_draft.ground`), same-named clients get
  labelled choices.
- §13 notifications flood: digest notification removed; the scheduler's daily
  marker is on disk (`data/storage/scheduler_last_daily.txt`).
- §14 Jarvis meeting card opens the invite's approval (`approval_id`).
- §15 meeting clash check (`meeting_invite_service.find_clash`).
- §16 no duplicate client names (`lead_service.refuse_duplicate_name`), and
  the pick loop for existing duplicates (fuzzy owner/city match, numbered
  choices).
- Also: invite drafted when a contact email is added later
  (`invite_waiting_meetings`); Planner drops invite/meeting tasks for a
  meeting already scheduled from that recording; invite body written to the
  reader ("you"), plain text, no false "updated".
- Another session (24 Sep) added: a lead opens only with an owner-added
  contact that has a phone or email; Jarvis refuses meetings, demos,
  proposals and MOUs on cold-calling leads; `add_client_contact` tool. The
  public URL moved to `https://unaltered-uncommon-bottling.ngrok-free.dev`.

Tests: baseline on 26 Sep was 5 failed / 1330 passed; the 5 are clock
sensitive (`test_what_is_late` x3, `test_demos_followups` x1,
`test_relationship_screens` x1) and fail when IST and UTC dates differ.
Tests that create leads in the shared test orgs must use
`tests/conftest.py::fresh_lead` or `lead_named` (two clients may not share a
name). File backups: `../backup_2026-09-23/`, `../backup_2026-09-25/`,
`../backup_2026-09-26/`. Deleted notifications (JSON copy):
`../backup_2026-09-23/notifications_deleted_2026-09-24.json`.

**Open:** BS Carmel School (lead `9bcf97b3a85948d09bbe3e46906a0eb9`). The
latest recording (29 Sep) showed 2 action items for review, but the meeting
later shows 5; an earlier recording that day produced none. Not investigated
yet.

**BS Carmel findings (30 Sep, not fixed yet):** recording 1 (11 s greeting) gave no items, correctly. Recording 2 (a 46 s voice note) gave none, but "we have to plan the kits" was an implied to-do the model missed. Recording 3: the review correctly showed 2 items; the "5" are those 2, plus 2 copies created because the review was confirmed twice (Siva, 12:45:54 and 12:46:36, from two network addresses; confirm_review in app/api/meetings.py re-creates any kept item whose id is no longer pending), plus 1 Planner task later superseded. Also "a meeting on Thursday", said on Tue 29 Sep, was stored as Wed 30 Sep: the model resolved the weekday wrongly, and that invite still waits in Approvals with the wrong date. Fixes to make: an idempotent confirm, weekday resolution in code, and the app disabling Confirm after a tap.


### Next session: fix the review duplicates and add "Approve plan" (agreed 1 Oct 2026)

**Part A, BS Carmel fixes (see findings above):**
1. `confirm_review` (app/api/meetings.py) must be idempotent: once the meeting
   is no longer `review_pending`, a second confirm changes nothing and says so;
   a kept item that carries an id is never re-created as a new item. Each
   confirm must not enqueue a second `plan_meeting`.
2. Weekday words ("on Thursday") are resolved in code from the recording's
   date, and the model's date is checked against them.
3. Short voice notes: implied to-dos ("we have to plan the kits") should be
   extracted.
4. Clean-up of BS Carmel's live data (2 copies, the wrong-date meeting and its
   invite) only with the developer's explicit OK.

**Part B, "Approve plan" after the review:**
Flow: confirm the extracted items as today; the same screen then shows an
animated loader with rotating text while the Planner runs ("Reading the
conversation…", "Planning next steps…", "Finding who should do what…",
"Almost ready…"); when the Planner finishes, a sheet opens with an animation
listing the extra tasks the Planner wants to add, each with an on/off switch;
the button says "Approve plan"; the plan activates with only the tasks left on.
Must cover:
1. Leaving the screen loses nothing: the held plan also appears as a Home card
   and in Approvals, with a notification when ready.
2. A slow or failed Planner gets a timeout and a clear message.
3. Other plan changes (moved dates, reassignments, removals) are shown as short
   lines; a first meeting also creates the project.
4. Switching off a task that others depend on clears the dependency.
5. Already-confirmed items appear greyed out as accepted.
6. Approval rules are respected ("Sent to X for approval" when a rule applies).
7. Approve is idempotent (double tap, two phones).
8. With the review gate off, the plan sheet appears right after processing.
Existing pieces to build on: plan versions, approval holding for plan changes,
`planner_engine.plan_rejected`, `activate_plan`. New: hold meeting-made plans,
one approve-with-kept-tasks endpoint, idempotent confirm and approve, a
"plan ready" notification.


## Session 1 October 2026: BS Carmel fixes and "Approve plan"

Built and tested (detail: `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md`
§17). LIVE (service restarted 1 Oct).

- Confirm works once (conditional update; a second confirm answers 200
  `already_confirmed`, saves nothing, runs no second Planner); an item with
  an id is never re-created; `plan_meeting` runs once per meeting.
- Weekday words resolved in code from the recording's day
  (`extraction.resolve_day_words` / `check_day`; the model returns `day_said`).
- The extraction prompt treats "we have to / we need to" in a voice note as a
  to-do.
- "Approve plan": a recorded meeting's plan is held for its recorder
  (Approval `meeting_plan`, notification `plan_ready`, `meetings.plan_state`),
  `GET /meetings/{id}/plan`, `POST .../plan/approve` (skip_task_ids,
  idempotent, approval rules apply after), `POST .../plan/retry`, failure
  wrapper `plan_meeting_safe`.
- Decisions by the developer: tasks promised to the client are locked on;
  Reject on the held plan drops the extras and keeps the confirmed to-dos;
  only the recorder approves.
- New columns `meetings.plan_state`, `meetings.plan_note` (light migration).
- Tests: baseline 1 failed / 1,334 passed (10:18 UTC); after, in staging,
  3 failed / 1,358 passed = the same clock test plus the two live-database
  dossier tests that need the restart.
- Backups: `../backup_2026-10-01/`. Staging copy used for testing:
  `/home/telaverge/Ekaghni/sfai_staging_1oct` (its data folder
  `sfai_staging_data` holds a copy of the live database); safe to delete.

BS Carmel's live data was cleaned up with the developer's OK on 1 Oct: the 2
copies and the wrong 30 Sep meeting and its task cancelled, no email drafted
(the invite had already gone to the test address).

- Later on 1 Oct: plan tasks waiting on a prerequisite named by a title the plan no longer held never got an owner; now linked to the client's live task with that title, and the 4 stored title links repaired (doc §17.5). Live (service restarted again).
- Service restarted again after the dependency fix (live). Merged the Planner-made duplicate contact "Rishabh Jain" into "Risabh Jain" on Ollama School of Commerce (removed the duplicate contact and its stakeholder row; nothing else pointed at them; copy in `../backup_2026-10-01/ollama_duplicate_contact.json`, audit `contact.merged`). The Planner creating near-duplicate contacts from speech-to-text spellings is not fixed.
- Later still: people a meeting names are checked by the model before they become contacts (misspelt saved contact, role-only names, two names for one person; threshold 0.7; doc §17.6). Live since the restart at about 12:10 UTC.


## Session 2 October 2026: Jarvis proposal loop

Root causes found from real conversations and real-model replays, and fixed (doc §18): invented email recipient, the answer routed to another agent, the built proposal out of reach on the next turn, and "All the suggested values are fine" offered when nothing was suggested. New held flow `app/ai/proposal_recipient.py`. Live since the restart of 2 Oct. Also fixed: the meeting held flow is now registered at startup (orchestrator imports every held flow), so a half-answered meeting question survives a restart. Backups: `../backup_2026-10-02/`.


## State in the morning of 2 October 2026 (history; see READ THIS FIRST at the top)

**Everything below is LIVE**: last service restart 2 Oct (about 22:00 UTC on
1 Oct); the debug APK with "Approve plan" is installed on the developer's
Vivo (10BFBT0TXJ001NP).

What the 1-2 October sessions built (detail in
`docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` §17-18):

| § | what | where |
|---|---|---|
| 17.1 | review confirm accepted once; Planner runs once per meeting | `api/meetings.py::confirm_review`, `jobs/pipelines.py::plan_meeting` |
| 17.2 | weekday words resolved from the recording's day | `ai/extraction.py::resolve_day_words`, `check_day` |
| 17.3 | voice-note to-dos ("we have to...") extracted | extraction prompt |
| 17.4 | "Approve plan": recorded meeting's plan held for its recorder | `planner_engine` (`_hold_for_recorder`, `approve_meeting_plan`, `discard_meeting_plan`), `GET/POST /meetings/{id}/plan[/approve|/retry]`, Approval `meeting_plan`, `meetings.plan_state/plan_note` |
| 17.5 | waiting tasks released when their prerequisite is done | `planner_engine._resolve_dependency_refs`, `repair_title_dependencies` |
| 17.6 | people a meeting names checked by the model (0.7) | `planner_engine._resolve_people`, `ai/planning.py::review_meeting_people` |
| 18 | Jarvis proposal loop: recipient from the user's words only, held recipient question, built proposal remembered, "all fine" chip only with a suggestion; every held flow registered at startup | `ai/agents/proposal_agent.py` (`recipient_said`, `_proposal_from_this_chat`), `ai/proposal_recipient.py`, `ai/agents/fill_tools.py`, `ai/orchestrator.py` |

Live data changed, each with a JSON copy first and an audit row:
BS Carmel duplicates and the wrong 30 Sep meeting cancelled
(`../backup_2026-10-01/bs_carmel_rows_before_cleanup.json`); 4 title
dependency links repaired (`../backup_2026-10-01/dependency_repair_applied.txt`);
duplicate contact "Rishabh Jain" merged into "Risabh Jain" on Ollama School
of Commerce (`../backup_2026-10-01/ollama_duplicate_contact.json`).
Test client created by the developer: Ollama School of Commerce (Delhi,
principal Risabh Jain, Siva), with one recorded meeting, an approved plan v1
and a meeting invite for Mon 5 Oct 11:00 waiting in Approvals.

**Tests:** last full run 1,391 passed. Failures to expect: the clock
sensitive five (`test_what_is_late` x3, `test_demos_followups` x1,
`test_relationship_screens` x1), which fail whenever IST and UTC are on
different dates (fewer, often only one, when they agree). Measure your own
baseline before changing anything.

**Traps learnt in these sessions (also in the developer's memory notes):**
- The test run reads the live `.env`: the model in tests is REAL
  (OpenRouter, live key). Stub every new model call in `tests/conftest.py`
  (as done for `planning.review_meeting_people`).
- The live DB runs in WAL mode. Copy it only with Python's sqlite3 backup API
  (`?mode=ro`); never symlink `-wal`/`-shm` next to a copy.
- A new column fails the two `test_client_dossier` "measured client" tests
  until the restart runs the light migration.
- Live models: fast `openai/gpt-5.4-nano` (the agents, including the proposal
  agent), strong `google/gemini-2.5-flash` (proposal filling, people check).

**Tools left on the VM for the next session:**
- `/home/telaverge/Ekaghni/sfai_staging_1oct` — a copy of the project
  (`.venv` symlinked) to test edited code without touching the live folder;
  its `data` points at `/home/telaverge/Ekaghni/sfai_staging_data` (a copy of
  the live DB from 1 Oct). Re-sync it from the live folder before using it.
- `/home/telaverge/Ekaghni/sfai_replay/replay2.py` — replays a Jarvis
  conversation through the real code and model on a sandboxed copy of the live
  data (email dry-run, calendar off, push off). Delete the sandbox folders it
  creates afterwards (~150 MB each).

**Open, not done (ask the developer before acting):**
- "send it" right after a proposal approval card sometimes routes to the email
  agent, which drafts a separate follow-up email.
- The proposal template asks the salesperson for YuviPep's own address; it
  could come from the organisation's record.
- The old "Accounts Head" contact on Ollama School of Commerce (made by the
  Planner before §17.6) is still there.
- The 30 Sep BS Carmel Google Calendar event was left (it is in the past).
- The public download page served app v0.7.4 on 29 Sep; the phone runs a
  newer debug build. Check before sharing the link.


## Session 2 October 2026 (later): meeting days

"next Saturday" said on a Friday was booked for the next day. Now (doc §19):
the strong model reads the day and time from the person's own words
(`app/ai/day_reading.py`), "next <weekday>" is always confirmed by Jarvis
("Saturday 3 October or Saturday 10 October?") and named beside the date on
a recording's review and approval card, and a day in the past is never
booked. Files: `app/ai/day_reading.py` (new), `app/ai/meeting_draft.py`,
`app/ai/extraction.py`, `app/jobs/pipelines.py`,
`app/services/meeting_invite_service.py`, `tests/conftest.py` (stub),
`tests/test_day_reading.py` (74), `tests/test_scheduled_meetings.py` (Jarvis
test dates moved to 2037). No app change, no new table or column.
Staging: 1 failed / 1,469 passed (unchanged code at the same hour: 1 failed /
1,395 passed). Real-model replays: `sfai_replay/replay_dates.py`,
`sfai_replay/replay_rec.py`. Status: see the line below.

**Status: LIVE** since the restart at 00:11 UTC on 2 Oct 2026 (backups of the
replaced files: `../backup_2026-10-02/meeting_days/`). Smoke-tested live as
rahul: "next Saturday" asked which Saturday, "cancel" booked nothing.

Expect from 3 Oct 2026: `test_adding_a_contact_later_drafts_the_waiting_invite`
fails on its own (it books 2 Oct 2026 and expects an upcoming meeting).


## Session 2 October 2026 (afternoon): assignments per client, confirm what you tick

Asked by the developer: the confirm-assignments screen should name each
task's client (as the Home briefing does) and confirm only the assignments
the lead ticks, so an older client's work is not confirmed with today's.
Detail: `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` §20.

- `GET /assignments/proposed` rows gain `lead_id`, `lead_name`, `project_id`,
  `project_name`, `due_date` (client = the task's own, else its project's).
  Additive: an older app ignores them.
- `assignment_engine.confirm_batch` confirms only rows still `proposed`; an
  id already decided is skipped and not counted (no second notification).
  The server already confirmed only the ids it was sent.
- Tests: `tests/test_assignment_selection.py` (3). Staging 1 failed / 1,472
  passed vs live 1 failed / 1,469 passed at the same hour (09:44 UTC).
- LIVE since the restart at 09:50 UTC on 2 Oct 2026. Live smoke test
  (read-only): 4 proposed rows, all named "Ollama School of Commerce".
  Backups: `../backup_2026-10-02/assignment_selection/`.
- App: unit-tested (176), installed on the Vivo 2 Oct 15:57 IST with the §21 build.


## Session 2 October 2026 (afternoon): Jarvis redesign and chat history

Asked by the developer: redesign the typed Jarvis screen (look and feel only,
voice mode untouched) and add a chat-history sidebar like the ChatGPT and
Claude apps. Detail: `docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` §21.

- Backend: `GET /api/v1/assistant/sessions?limit=` (1..100, default 50) lists
  the caller's own chats from `assistant_turns`, newest first: `session_id`,
  `title` (first thing the person said), `preview` (last thing said),
  `last_at`, `turns`. Read only; no table or column; no model call.
  `app/ai/conversation.py::list_sessions`, `app/api/assistant.py`.
- Tests: `tests/test_assistant_sessions.py` (6). Staging 1 failed / 1,478
  passed vs live 1 failed / 1,472 passed at the same hour (10:10 UTC).
- LIVE since the restart at 10:23 UTC on 2 Oct 2026. Smoke test (read only,
  as rahul): 5 chats listed newest first; 401 without a token.
  Backups: `../backup_2026-10-02/jarvis_history/`.
- Behaviour change the developer chose: the app's "New chat" no longer
  deletes the chat being left (it stays in the sidebar); deleting is a
  long-press in the sidebar, using the existing `DELETE /assistant/history`.
- App: unit-tested (182), installed on the Vivo 2 Oct 15:57 IST (versionCode 20728, same day as before; lastUpdateTime is the proof).
