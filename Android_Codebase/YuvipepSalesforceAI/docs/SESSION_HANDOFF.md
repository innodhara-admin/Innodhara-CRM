# Session handoff — 28 August 2026

This file records what was done in one working session, and everything that was
learned about this codebase along the way. It exists so the next Claude session
does not have to rediscover all of it.

Written in plain language on purpose.

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
| public URL | `https://noninfluential-lamonica-unobservantly.ngrok-free.dev` |
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

---

## 5. State of things right now

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
| `Complete_Project/docs/RELATIONSHIP_MANAGER_PLAN.md` | the next feature, planned but not built |
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
