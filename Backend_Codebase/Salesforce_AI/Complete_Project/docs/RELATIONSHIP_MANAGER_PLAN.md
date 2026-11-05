# Relationship Manager — the plan

This file explains a new role we want to add: the **Relationship Manager**.
It is written in plain language. Anyone should be able to read it.

All seven steps of section 10 are built. See section 12.

---

## 1. First, the question that had to be answered

Before planning anything, we had to know one thing:

> **When a lead becomes "closed", who does that? The AI or a person?**

**Answer: a person. Always. The AI can only suggest.**

Here is what the code actually does. This was checked by reading the code, not
the documents.

- When a project is delivered and fully paid, the Sync Engine
  (`app/engines/sync_engine.py`, around line 573) notices and calls
  `lead_service.apply_suggestion(...)`.
- `apply_suggestion` does **not** change the lead. It only fills two fields on
  the lead: `suggested_state` and `suggested_state_reason`. It also writes a
  row into `ai_decisions` so the app's "Why?" button has something to show.
- The app then shows a banner: *"AI suggests moving this to closed"*.
- A person taps to accept. That sends `PATCH /leads/{id}/state`.

**The important fact:** `lead_service.change_state()` — the function that
actually moves a lead — is called from **exactly one place in the whole
codebase**: the `PATCH /leads/{id}/state` endpoint
(`app/api/leads.py`, line 490).

No engine, no background job, and no AI agent ever moves a lead by itself.
So the manual path is not just present — **it is the only path.**

### Does the manual path have the right permissions?

Not yet. Right now the endpoint is guarded only by the `manage_leads`
permission, which is held by:

- `sales_agent`
- `sales_lead`
- `org_admin`

That means **any sales agent can change the state of any lead**, including
leads belonging to other agents. There is no ownership check today, except the
one we added this session for cold calling.

You asked for this rule instead:

> all sales leads, and only the lead owner (one sales agent), can change states

### Proposed rule

Add one helper next to the existing `can_leave_cold_calling`:

```
can_change_lead_state(role, actor_id, lead.owner_id):
    org_admin                -> yes  (break-glass)
    sales_lead               -> yes  (any lead, they run the team)
    the lead's owner         -> yes
    any other sales agent    -> no
```

The stricter cold-calling rule we already shipped stays on top of this:
leaving `cold_calling` needs the **owner** (or an org admin). Not even a sales
lead can do it, because only the person who made the phone calls knows what was
said.

### Will this conflict with anything?

Three things to know before this is implemented.

1. **It changes behaviour for people using the app today.** An agent who is
   used to nudging a colleague's lead along will start getting refused. This is
   the intended change, but it is a real change and should be announced.

2. **One of our own tests will fail and must be updated.**
   `tests/test_pre_sales.py::test_the_established_flow_after_open_is_untouched`
   deliberately uses Rahul (a sales agent who does *not* own the lead) to walk
   a lead from open all the way to closed. That test exists to prove the
   pre-sales gate did not leak into the rest of the flow. Under the new rule
   Rahul is refused, so the test must be rewritten to use the owner or a sales
   lead. This is expected, not a bug.

3. **Nothing else breaks** — but not for the reason first given here. The
   original text said the engines and seed scripts call
   `lead_service.change_state` directly. **They do not. Nothing does.** A
   search for every caller finds exactly one, the endpoint at
   `app/api/leads.py:490`. The engines call `apply_suggestion`, which writes
   `suggested_state` and moves nothing. The conclusion survives; the reasoning
   was wrong.

   Two dry-run scripts do drive lead states over HTTP, and both were checked:

   - `scripts/dryrun_part5.py` is **fine**. `seed_workflows.py:410` gives every
     seeded lead `owner_id = Rahul`, and Rahul is the one patching the state.
   - `scripts/verify_gap_endpoints.py` was **already broken**, and not by this
     change — see the note below, which turned out to be much bigger than one
     script.

**The verification scripts were broken by pre-sales, and nobody noticed.**

`POST /leads` now creates in `cold_calling`, and two gates then refuse the
lead: `get_workable_lead` blocks every `/meetings/` route, and
`cold_calling -> anything except open|lost_for_now` is not a legal transition.
Six scripts create a lead and immediately work it, so each died at its first
meeting or state call and took everything after it down as well.
`verify_gap_endpoints.py` had stopped running G3 — the proposal tamper check —
entirely, and said nothing about it.

Fixed in all six by the one move the state machine now expects: `open` straight
after creation. In every case the creator owns the lead, so the owner is
exactly who may take it out of cold calling.

| script | how it was verified |
|---|---|
| `verify_gap_endpoints.py` | full run — **22/22**, G3 running again |
| `verify_generic_stakeholders.py` | full run under `--stub` — **21/21** |
| `verify_generic_planner.py` | probe: `POST /leads` → `PATCH /state` → `POST /meetings/notes`, all 200 |
| `verify_live_offdomain.py` | probe: past the meeting stage |
| `verify_live_genericity.py` | probe: past the meeting stage |
| `verify_live_commitments.py` | probe: reached `pipelines.process_meeting` |
| `verify_live_meeting_planner.py` | probe: reached the model layer |

"Probe" means a **copy** of the script with only its "needs a real LLM
provider" assertion lifted, run under a stub. Those five refuse to start
without a live provider, so running them unmodified proves nothing — the run
dies at the assertion, well before any of the changed code. The originals were
never modified for this.

**A correction to an earlier note here.** The probe runs hit
`429 RESOURCE_EXHAUSTED` from Gemini, which was first written up as "the
Gemini credits are depleted, so no live script can run". That reading was
wrong on the part that mattered.

`app/ai/llm.py:571` is `providers.get(settings.llm_provider, GeminiProvider)()`
and the registry holds only `claude`, `openrouter`, `gemini`. Setting
`LLM_PROVIDER=stub` for the probes did not stub anything — it fell through to
Gemini. The 429 was caused by the probe technique, not by the configuration.

In normal operation this org uses `LLM_PROVIDER=openrouter` for generation,
and **Gemini is not called at all**. Embeddings and speech-to-text are local
(see handoff rule 10). The Gemini credits genuinely are depleted, but nothing
in normal operation depends on them.

The probe conclusions still stand: reaching the model layer proves every gate
before it was passed, whichever provider the call went to.

---

## 2. What a Relationship Manager is

A Relationship Manager (RM) looks after a client **after** the selling and the
delivery are finished. They are not part of the sales process. Their job is to
keep the client warm, keep talking to them, and notice when the client is ready
to buy something again.

Example used throughout this file:

- **ABC School** is a lead.
- We sold them a project. The project was delivered and paid.
- The lead is now `closed`.
- **Priya** was the sales agent who owned it.
- **Meena** is a Relationship Manager.

---

## 3. The whole journey, end to end

```
Sales                                Relationship                    Sales again
─────────────────────────────        ────────────────────            ───────────────
cold calling → open → active
   → execution → closed
                  │
                  ├── owner chooses: leave it closed (do nothing)
                  │
                  └── owner chooses: "Hand to Relationship Manager"
                                │
                                ▼
                      AI picks the best RM (Meena)
                                │
                                ▼
                      Meena keeps in touch
                      · informal meetings
                      · AI summarises each one
                      · AI suggests the next touch date
                                │
                      A meeting hints the client wants to buy again
                                │
                                ▼
                      AI: "this looks like a new opportunity"
                      Meena taps Accept
                                │
                                ▼
                      All sales leads are notified
                      A sales lead assigns a new lead owner
                                │
                                ▼
                      New sales cycle starts at OPEN
                      (no cold calling — we already know them)
```

---

## 4. Step by step

### Step 1 — The lead is closed

Nothing new. The project finishes, the AI suggests `closed`, a person confirms.

### Step 2 — The owner decides what happens next

On a `closed` lead, the owner (and sales leads) see a new button:

**"Hand to Relationship Manager"**

If they do nothing, the lead simply stays closed. That is a valid choice and
must remain the default. We are not forcing every client into relationship
management.

### Step 3 — The AI picks the Relationship Manager

When the button is tapped, the AI looks at every Relationship Manager in the
organisation and scores them. Then it assigns the best one and explains why.

**Correction, found by reading the code:** we *do* have to write the scoring.
`assignment_engine.build_candidates()` and `assign_task()` both take an
`ActionItem`; load is a count of open action items and continuity is action
items on a project. Neither means anything for "who should keep talking to this
client for the next year". Bending an `ActionItem` into the shape of a client
would make both engines harder to read.

What was built instead is `app/engines/relationship_engine.py` — a sibling,
not a subclass. It reuses the parts worth reusing: the candidate / `score()` /
`reason()` shape, `SKILL_LEVEL_SCORE`, and `resource_engine.conflicts_for()`
for leave and bookings. Its three ingredients are focus, load and experience,
and no more, because each one has to survive being read aloud to the person who
was not chosen.

**On "area of expertise":** the engine carries no vocabulary of its own. It
reads the manager's `user_skills` rows and looks for one that the client's own
record already mentions (`city`, `region`, `source`). Hard-coding a list like
`k12_schools` or `cbse` would be a domain assumption, which `test_genericity.py`
exists to prevent. The trade is honest and is stated in the code: the match is
only as good as what the organisation typed, and an unmatched manager's
recorded reason says "no particular focus match" rather than implying one.

The original text below described the engine we were going to reuse. It is kept
because the *facts* about `assignment_engine` are still correct — it scores on:

- skill level (`user_skills` table: `basic` / `good` / `expert`)
- how much work they already have (`max_open_tasks` vs current load)
- whether they are on leave (`on_leave_from` / `on_leave_to`)
- continuity (have they worked with this client before)

For RM matching we reuse the same shape and add:

- **Past relationship history** — how many engagements this RM has handled,
  and how they went.
- **Area of expertise** — stored as `user_skills` rows on the RM, for example
  `k12_schools`, `cbse`, `south_india`, `large_accounts`.
- **What kind of client this is** — taken from the lead's own summary. We
  already have this: `knowledge_engine.replay_story()` produces a short
  readable history of a lead, and `distil_project()` writes a summary into
  `client_intelligence` the moment a project closes.

The AI must record its choice through `record_decision(...)` — the same
mechanism the rest of the system uses — so the app can show a **"Why this
person?"** answer. This is not optional. There is a recorded past bug (F10)
where a suggestion was shown with no decision recorded, and the "Why?" button
could only answer "no decision recorded".

**If there is only one Relationship Manager**, the AI still records a decision,
it just says so plainly. **If there are none**, the button should be hidden or
should explain that no Relationship Manager exists yet.

### Step 4 — Meena's screens

The RM sees a different app from a salesperson. Suggested screens:

**a) Home**
- Clients I look after
- Who I have not spoken to in a while (overdue touches)
- Suggested next touches for this week

**b) Client page** — for each client:
- **AI summary of everything we know.** Reuse `knowledge_engine.replay_story()`
  which already gathers projects, proposals, known facts and memories into a
  short readable block.
- **Contacts** — reuse the existing contacts list exactly as it is.
- **How to approach them** — AI-written notes on what this client responds to,
  built from `client_intelligence` and past meeting summaries.
- **The relationship feed** — a running list of past touches and their
  summaries (see step 5).
- **Meetings** — reuse the existing meeting recorder.

**c) The lead's sales history** — read-only. Meena should be able to see what
was sold and how it went, but not change sales states.

### Step 5 — Meetings, the two kinds

Meena records a meeting the same way a salesperson does. What changes is what
happens *after* the transcript.

**Correction:** "the recorder, upload and transcription are reused with no
change" is not true. **`POST /meetings/upload` has no `meeting_type` parameter
at all** — it exists only on `/meetings/schedule` and `/meetings/notes`. So a
*recorded* catch-up currently has no way to be marked `relationship`. Upload
needs an additive optional `meeting_type: str | None = Form(default=None)`.
Additive is the important word: the shipping APK sends nothing and keeps
behaving exactly as it does now.

`meeting_type` is a free `String(20)` on the model and is not validated against
the enum anywhere, so adding the value itself is safe.

Today the pipeline (`app/jobs/pipelines.py`) does this: transcribe → extract
action items → review gate → memory → suggest lead state → run the Planner.
For a relationship meeting most of that is wrong. Meena does not need a project
plan generated because she asked a principal how his holidays were.

**Kind 1 — a friendly catch-up**

- AI writes a short summary.
- The summary goes into the client's relationship feed.
- AI suggests when to talk next and what to talk about.
  Example: *"That went well. Suggest a call in about 5 days. Ask about the new
  computer lab he mentioned, and about the exam season plan."*
- The suggested next touch becomes a **follow-up** row. We already have a
  `followups` table with `lead_id`, `owner_id`, `due_date`, `channel` and
  `note` — it fits exactly and needs no new table.
- **No action items. No project plan. No lead-state suggestion.**

**Kind 2 — the client hints at buying again**

Everything from kind 1 happens, and in addition:

- The AI flags that a new opportunity may exist.
- A card appears on Meena's screen:
  *"This sounds like a new opportunity. Move ABC School back to the sales
  process?"* with the AI's reason and the exact words that triggered it.
- Meena accepts or dismisses. **A person always decides.** The AI never moves
  the lead itself — this matches how the rest of the system already works.

To make this work we extend the meeting analysis. Today
`extraction.MeetingAnalysis` returns `action_items`, `summary`,
`real_discussion` and `key_facts`. We add two fields:

- `new_opportunity: bool`
- `opportunity_reason: str`

And we add a meeting type. `MeetingType` today is
`first_visit | negotiation | kickoff | review | closure`. We add:

- `relationship` — a catch-up

The pipeline then branches on the meeting type: relationship meetings take the
light path described above.

### Step 6 — Back into the sales process

When Meena accepts, this happens:

1. The lead moves from `closed` back to `open`.
   **This transition does not exist today.** `LEAD_STATE_TRANSITIONS` currently
   allows `CLOSED -> {LOST_FOR_NOW}` only. We must add `CLOSED -> OPEN`.
2. A new **sales cycle** starts (see section 5 below).
3. Every sales lead gets a notification:
   *"Meena had a discussion with ABC School and accepted the AI's suggestion to
   move it back to sales."*
4. Tapping the notification opens ABC School.
5. The lead has **no owner yet** for this new cycle. A sales lead picks one
   from a dropdown.
6. Once an owner is picked, the cycle is live and behaves exactly like the
   normal flow.

**Important difference: no cold calling.** We already know this client. The new
cycle starts at `open`, not `cold_calling`. The cold-calling stage exists to
find out whether there is interest; here we already know there is.

---

## 5. The "cards" — how repeat business is stored

You described the lead page growing a new card each time the loop repeats: one
card for the old closed business, one card for the new round.

Here is what the code allows today, and what we propose.

**What already works:** a lead can already have many projects.
`Project.lead_id` is an ordinary foreign key with a non-unique index, and
`knowledge_engine.replay_story()` already loops over *all* projects for a lead.
So the database does not fight us here.

**What does not work:** a lead has exactly one `state` column. It cannot say
"round 1 is closed and round 2 is open" at the same time.

**Proposal: a new small table, `lead_cycles`.**

| column | meaning |
|---|---|
| `id` | |
| `lead_id` | which client |
| `cycle_number` | 1, 2, 3 … |
| `owner_id` | the sales agent for this round |
| `source` | `cold_call` for the first round, `relationship` for later ones |
| `opened_at` | when this round started |
| `closed_at` | when it finished (empty if still running) |
| `outcome` | `closed` / `lost_for_now` / still running |
| `project_id` | the project for this round, if any |

Then:

- The lead keeps one `state`, and it always means **the current cycle's state**.
  Every piece of existing code that reads `lead.state` keeps working unchanged.
  This is the main reason to prefer this design.
- Each card on screen is one row of `lead_cycles`.
- Contacts, the notebook and the client intelligence stay attached to the
  **lead**, not the cycle. They are shared across rounds, which is what we want
  — you do not want to re-enter the principal's phone number for round two.

**Two designs we rejected, and why:**

- *Create a brand new lead for each round.* This is what chain deals do
  (`app/api/projects.py:607`). It splits contacts and history across two
  records, so "everything we know about ABC School" would be in two places.
- *Turn the lead into a client and add a separate Engagement entity.* Cleanest
  on paper, but it means touching almost every query in the system. Too big and
  too risky for the value.

---

## 6. Adding the role — the checklist

A new role touches more places than expected. All of these were found by
searching the code.

**Backend**

1. `app/core/constants.py` — add `RELATIONSHIP_MANAGER = "relationship_manager"`
   to `Role`, and add it to `ORG_ROLES`.
2. `app/core/permissions.py` — decide what it can do (see below).
3. `app/models/user.py` — `department` currently holds
   `sales | operations | accounts`. Add `relationship`.

**Android — and this part is enforced by a test**

4. `RoleGate.java` — add the role constant, add it to the `MATRIX`, and add it
   to `isKnownRole()`.
5. `app/src/test/resources/contract/permissions.json` — this fixture is a copy
   of the backend's permission matrix, and `RoleGateTest` compares the two on
   every build. **If you change the backend matrix and not this file, the
   Android build fails.** That is deliberate and it is a good thing.
6. `RoleGateTest.java` — it has a hard-coded `ROLES` array listing the six
   roles it checks. A new role must be added there too, otherwise the test
   quietly does not check it.
7. `MainActivity.buildTabsForRole()` — add the RM's bottom bar.

**A helpful safety net:** `buildTabsForRole` ends with
*"Unknown role → generic member experience"*. So if the backend ships the new
role before the app does, an RM logging in gets a plain Home / Tasks /
Assistant app instead of a crash. **This means the backend can go first.**

### Suggested permissions for the RM

| permission | RM has it? | why |
|---|---|---|
| `view_leads` | yes | must read the client's history |
| `record_meeting` | yes | catch-up meetings are the job |
| `manage_tasks` | yes | own reminders |
| `manage_leads` | **no** | must not move sales states |
| `send_messages` | yes | keeps in touch |
| `view_demos` | yes | read-only awareness |

Plus two new permissions:

- `assign_relationship_manager` — sales leads, the lead owner, org admin.
  Used by the "Hand to Relationship Manager" button.
- `manage_relationships` — RM and org admin. Used for the RM's own screens and
  for accepting the "move back to sales" suggestion.

---

## 7. New endpoints

| endpoint | who | what it does |
|---|---|---|
| `POST /leads/{id}/relationship/handover` | owner, sales lead, admin | AI picks an RM, assigns, notifies |
| `GET /relationships/mine` | RM | the RM's client list for Home |
| `GET /leads/{id}/relationship` | RM, sales | the engagement plus the AI summary |
| `POST /leads/{id}/relationship/opportunity/accept` | RM, admin | reopens the lead, starts a new cycle |
| `POST /leads/{id}/relationship/opportunity/dismiss` | RM, admin | records that it was not real |
| `POST /leads/{id}/cycles/{cycle}/owner` | sales lead, admin | assigns the owner of the new round |
| `GET /relationship-managers` | sales lead, admin | list, for the manual override |

Every AI choice must also write an `AIDecision` row so the "Why?" sheet works.

---

## 8. New tables

**`relationship_engagements`** — one row each time a client is handed to an RM.

| column | meaning |
|---|---|
| `lead_id` | the client |
| `manager_id` | the RM |
| `assigned_by` | who pressed the button |
| `ai_reason` | why the AI chose this RM |
| `started_at`, `ended_at` | |
| `status` | `active` / `ended` / `returned_to_sales` |

**`lead_cycles`** — see section 5.

**`relationship_touches`** *(optional — decide during implementation)* — a feed
row per contact with the client. It may be simpler to reuse
`client_intelligence` with `category="relationship"` instead of adding a table.
Decide this when building, not now.

---

## 9. Open questions — ANSWERED 31 August 2026

All six were put to the user before any code was written. These are decisions,
not suggestions.

1. **Does the RM belong to a department?**
   **Yes — a new `relationship` value, and their escalations go to the sales
   lead.** No branch was needed for that: `find_department_lead()` in
   `app/engines/common.py` already routes anything that is not operations or
   accounts to the sales lead. That is now the intended reporting line rather
   than an accident of the fallback, and it is written down in the enum.

2. **Can one client have two RMs over time?**
   **No — one RM per client, permanently.** There is at most one engagement
   row per lead and the manager does not rotate.

3. **Can a sales lead override the AI's choice of RM?**
   **Yes — pick at handover, and reassign later.**

   *These two answers pull against each other, and the reconciliation the user
   accepted is:* one **active** engagement per client, and reassignment moves
   `manager_id` on the row that already exists rather than opening a second
   one. A wrong first pick is a correction, not a new chapter in the client's
   history. `test_reassignment_moves_the_manager_on_the_same_engagement`
   asserts the row count stays at one.

4. **What happens to the RM while a new sales cycle runs?**
   **The engagement ends outright** — status `returned_to_sales`, an
   `ended_at`, nothing scheduled. Not paused. If they want a manager again
   after the next close, somebody presses the button again.

5. **Should the cross-sell note change?**
   **No. `distil_project()` is not touched at all.** The note keeps going to
   the sales owner.

6. **Does the RM see money?**
   **Yes, the same as every other role today.** This one turned on a fact
   worth recording: `GET /projects` and `GET /projects/{id}` are guarded by
   plain `get_org_context`, not by a permission, so *every* logged-in org
   member already sees `value_estimate`. Hiding amounts from the RM was never
   a permission toggle — it would have meant role-conditional field filtering
   on endpoints every role uses. That work is not being done.

Answers 5 and 6 together removed every change to code that works today outside
the lead and permission path. The build is materially safer than the plan as
originally written.

---

## 10. Suggested build order

Each step should leave the system working and the tests green.

1. **The permission change** from section 1 (state changes limited to sales
   leads and the owner). Small, self-contained, and it fixes a real gap today.
   Update the affected test.
2. **The role**: add `relationship_manager` everywhere in the section 6
   checklist. No behaviour yet. Verify an RM can log in and gets the generic
   app.
3. **Handover**: the button, the AI matching, the engagement table, the
   notification.
4. **The RM's screens**: Home and the client page, reusing `replay_story`.
5. **Relationship meetings**: the new meeting type and the light pipeline path.
6. **Opportunity detection**: the two new analysis fields and the accept card.
7. **`closed -> open`, `lead_cycles`, and the new-owner card.** This is the
   biggest step and should be last, because it touches the lead page that
   everyone uses.

---

## 11. Things to be careful about

- **`cold` and `cold_calling` are different things.** `cold` means a lead we
  were working has gone quiet. `cold_calling` means nobody has phoned yet. They
  are at opposite ends of the lifecycle. Do not merge them.
- **The AI must never move a lead by itself.** Suggest, then a person confirms.
  This is the pattern everywhere in this codebase and it should not be broken
  for the RM flow.
- **There is no Alembic.** `create_all` builds missing tables but never adds a
  column to a table that already exists. New tables are fine automatically; new
  **columns** need a hand-written `ALTER TABLE` in `_apply_light_migrations()`
  in `app/database.py`.
- **Do not put client-facing wording inside `app/`.** `tests/test_genericity.py`
  walks `app/**/*.py` and fails on industry words that reach the AI.
- **Keep the Android permission fixture in step with the backend**, or the
  build fails. See section 6. Nothing generates
  `contract/permissions.json` despite the README calling it "generated" —
  `capture_android_contract.py` does not touch it. Regenerate it from `_MATRIX`
  rather than hand-editing, and remember the file is **CRLF**:

  ```sh
  ./.venv/bin/python -c "
  import json
  from app.core.permissions import _MATRIX
  print(json.dumps({p: sorted(r.value for r in roles)
                    for p, roles in sorted(_MATRIX.items())},
                   indent=2, sort_keys=True))"
  ```

- **Every new table must be classified in `app/core/reset_taxonomy.py`.**
  This is not in any document and it cost a full-suite failure to find.
  `tests/test_reset_taxonomy.py` asserts the four buckets are a complete
  partition of `Base.metadata` **and** hard-codes their sizes, so a new table
  fails two tests until somebody decides where it belongs. That is the test
  working as designed — the numbers are meant to be edited by hand.

  Ordering matters as much as the bucket: deletion runs child-before-parent,
  the schema declares no `ondelete=` anywhere, and SQLite does not enforce
  foreign keys by default. `relationship_engagements` therefore sits
  immediately before `leads` in WIPE.

---

## 12. Build progress

Steps refer to the build order in section 10.

| step | state | evidence |
|---|---|---|
| 1. Ownership on lead state changes | **done** | `can_change_lead_state`; 3 tests in `test_pre_sales.py` replacing the one that documented the old rule |
| 2. The `relationship_manager` role | **done** | backend matrix, regenerated fixture, `RoleGate`, `RoleGateTest`, `tests/test_relationship_manager.py` (4) |
| 3. Handover | **done** | `relationship_engine`, `relationship_engagements`, `app/api/relationships.py`, the lead-detail button; `tests/test_relationship_handover.py` (11) |
| 4. The RM's screens | **done** | `GET /relationships/mine`, enriched `GET /leads/{id}/relationship`, `RelationshipHomeFragment`, the RM tab bar, the relationship section on Overview; `tests/test_relationship_screens.py` (8) |
| 5. Relationship meetings | **done** | `MeetingType.RELATIONSHIP`, `analyse_relationship_meeting`, the shared light path in both entry points, `meeting_type` on `/upload`, the follow-up permission; `tests/test_relationship_meetings.py` (8) |
| 6. Opportunity detection | **done** | `new_opportunity` / `opportunity_reason` / `opportunity_quote`, columns on the engagement plus the `ALTER`, accept + dismiss endpoints, the card on Home and the client page; `tests/test_relationship_opportunity.py` (9) |
| 7. `closed -> open`, `lead_cycles` | **done** | the transition, the `lead_cycles` table, lazy cycle creation, owner assignment, cycle cards and the new-owner prompt; `tests/test_lead_cycles.py` (8) |

**Test counts, measured not assumed.** Backend baseline before any of this was
`4 failed, 350 passed`, the four being the time-of-day set the handoff names.
After step 3 the suite is `371 passed` — the four now pass because the clock
moved past midnight UTC, **not** because anything here fixed them. Android went
47 tests to 48, zero failures throughout, `assembleOrgDebug` green.

### Deployed — 31 August 2026, 02:40 UTC

`salesforce-app-restart` restarted. Verified after:

| check | result |
|---|---|
| service | active, listening on 8010 |
| tables | 55 → **57**; `relationship_engagements` (20 cols) and `lead_cycles` (13) created complete |
| opportunity columns | all 7 present |
| data | 15 leads, 61 users, 5 meetings, 2 projects, 36 tasks — unchanged; `integrity_check` ok |
| lead states | unchanged (8 open, 4 cold_calling, 2 cold, 1 active) |
| routes | 9 new paths registered, 138 total |
| public URL | 200 — the pinned ngrok domain survived, as expected |
| startup log | no errors, no tracebacks |

Pre-deploy snapshot: `data/salesplatform_PRE_RM_DEPLOY_20260831_023939.db`
(integrity ok, 55 tables). Full archive from the start of the session:
`/home/telaverge/Ekaghni/Salesforce_AI_Project_BACKUP_PRE_RM_20260830_234101.zip`.

**The feature is live but inert until somebody creates a relationship manager.**
There are no users with that role yet, so the "Hand to relationship manager"
button will correctly refuse with *"There is no relationship manager in this
organisation yet"*. Create one via `POST /admin/users` with
`role: relationship_manager`, `department: relationship`.

**The phones still run the old APK.** Every backend change is additive except
the ownership rule, so the current app keeps working; it simply cannot see the
relationship screens. A sales agent trying to move a colleague's lead will now
be refused — that is the announced change.

### Found in use, after deployment

**Opportunity detection never fired.** The first real catch-up — *"I presented
our new server product and they got interested in it"* — produced a summary, a
feed entry and a next touch, but no opportunity card.

The pipeline was fine. `meeting_type` was `relationship`, the light path ran,
the engagement existed. The model simply answered false. Probing it live showed
how far off the calibration was: a deliberately stronger transcript with a
stated need, a price question AND a budget timeline — three of the four things
the prompt itself listed as qualifying — also came back false.

So it was not a strict threshold, it was a broken one, and the cause was
framing rather than criteria. The qualifying list was surrounded by "true ONLY
if", "When unsure, false", a vivid negative example, and an opening line saying
nobody is selling anything. Everything pushed one way and nothing pushed back.

Recalibrated: criteria stated positively with "any one is enough", firm
commitment explicitly not required, a positive worked example beside the
negative one, and the opening no longer denies that anything commercial can
come up. Verified against four transcripts — the two real misses now flag, and
ordinary politeness and small talk still do not. `test_genericity` still passes;
the examples carry no industry vocabulary.

**The lesson for the next prompt:** a rule with only a negative example and no
positive one is not a threshold, it is a veto. Test detection prompts against
cases that must fire, not only against cases that must not.



**The relationship manager could not sign out.** Logout lives in exactly two
fragments in this app — `HomeFragment` and `RoleHomeFragment` — and every other
role's tab bar starts with `home`, so they all inherit the button. The RM bar is
Clients / Tasks / Jarvis, which contains neither. Fixed by putting "Sign out" in
the RM Home header, using the same confirm dialog and `authRepository.logout()`
path as the other two.

Worth recording *why no test caught it*: `RoleGateTest` checks the permission
matrix, not navigation, and `src/androidTest` is empty by project decision — so
nothing in this codebase asserts which screens a role can actually reach. Any
new role's tab bar has to be walked by a person. The check to run for the next
one: can they log out, and can they reach everything their permissions imply?

### Decisions taken while building step 7

**Cycles are written lazily.** A client sold to once has no `lead_cycles` rows
and needs none — their lead page is exactly what it always was, and there is no
data migration for the leads that already exist. The first time a client comes
back, the round that already finished is reconstructed from the lead itself
(its owner, its creation date, the moment it was closed, its latest project)
and written alongside the new one. A page showing "Round 2" and nothing else
would be worse than no page.

**The lead keeps one `state` column.** It always means the current round. That
is the whole reason this design was chosen over a new lead per round (which
splits contacts and history across records) or a separate Client entity (which
touches almost every query in the system). Every existing query that reads
`lead.state` is untouched.

**`change_state` now has two callers, and the handoff says so.** Accepting an
opportunity moves the lead `closed -> open`. Rather than quietly falsifying
handoff rule 2, the rule is rewritten: the invariant that matters is that no
engine, background job or AI agent moves a lead — only a human-initiated
endpoint does, and both callers are that.

**A relationship manager may make exactly one lead-state move:** handing a
client back to sales. They hold no `manage_leads`, so `PATCH /leads/{id}/state`
refuses them every other transition. That is the boundary of the role, not a
hole in it.

**A reopened round starts with no owner.** `lead.owner_id` is cleared, which
means `can_change_lead_state` limits the lead to a sales lead or the org admin
until one of them assigns someone — exactly the next thing that should happen.
An agent cannot quietly take an unowned round for themselves, and a test
asserts it.

**Rounds are closed where leads are moved.** `PATCH /leads/{id}/state` marks the
running cycle finished when the lead reaches `closed` or `lost_for_now`, rather
than an engine reacting to an event. The lifecycle stays something people
drive.

### Decisions taken while building step 6

**The card stores the client's own words.** `opportunity_quote` is the verbatim
line from the transcript, and it is shown on the card and in the notification
sent to sales leads. A person is being asked to decide; "the assistant thinks
so" is not evidence, what the client actually said is. A flag that arrives with
neither a reason nor a quote is downgraded to "not an opportunity" rather than
shown, because it cannot be answered.

**Accepting does not move the lead — yet.** `closed -> open` is still not a
legal transition, so accept records the decision, marks the engagement
`accepted` and tells every sales lead. The response says `lead_state` plainly
rather than implying the lead moved. Step 7 completes it. This keeps the rule
that `PATCH /leads/{id}/state` is the only thing that ever changes a lead's
state.

**Columns on `relationship_engagements`, not a new table.** At most one
opportunity is open per client, and a second hint arriving before the first is
answered replaces it — what closes the question is a person deciding, not how
many times the assistant noticed. New columns on an existing table need a
hand-written `ALTER` (rule 1), which is in `_apply_light_migrations` and was
tested against a database built in the *old* shape, not just a fresh one: the
columns appear and the existing row survives with the `none` default.

**A hint about a client nobody looks after raises nothing.** A card with no
owner is a card nobody answers. The catch-up still saves.

### Decisions taken while building step 5

**The relationship feed reuses `client_intelligence`, category `relationship`.**
Section 8 left `relationship_touches` open. The existing table already has the
shape, and `knowledge_engine.replay_story` already reads it — so the feed
appears in the client's story for free, and there is one less table to classify
in the reset taxonomy. No new table.

**`POST /meetings/notes` needed the same branch as the pipeline.** It does not
call `pipelines.process_meeting` at all; it calls `planner_engine` directly. So
branching only inside the pipeline covered recorded catch-ups and left *typed*
ones building a project plan. The light path is now one public function called
from both entry points.

**A relationship manager's meetings are catch-ups by role, not by picker.**
Every listed `MeetingType` is a stage of selling and an RM holds neither
`manage_leads` nor `send_proposal`, so offering the picker would offer five
wrong answers. The Notes composer shows a disabled "Catch-up" instead, and the
recorder sends `meeting_type=relationship` for that role only. Every other role
sends nothing, which is byte-for-byte the request the server has always had.

### Gap from step 4 — now closed

`POST /followups` and `/complete` were gated on `manage_leads`, which an RM
must not hold. `manage_leads` was doing two jobs at once: "may work the sales
pipeline" and "may plan a conversation with a client". Only the first should
exclude an RM.

Fixed with a new `require_any_permission("manage_leads",
"manage_relationships")` on those two endpoints — *not* by widening
`manage_leads`, which would have handed the RM the sales states as well. A test
asserts an operations agent is still refused, so the gate did not simply open.

### Superseded note (kept so the reasoning is visible)

**A relationship manager cannot book or complete a follow-up.** `POST
/followups` and `POST /followups/{id}/complete` are gated on `manage_leads`,
which the RM deliberately does not hold — it is the same permission that moves
sales states. Planning the next touch is the RM's core job, so this has to be
resolved, but it belongs to step 5, where the follow-up lifecycle is built and
the AI starts writing these rows itself. Widening a permission as a side effect
of a screen that only *reads* touches would be the wrong place to decide it.

Step 4's Home reads follow-ups correctly whoever booked them — `_next_touch`
filters by client and pending status, not by owner, because "when is this
client next being spoken to" does not depend on who wrote it down.
