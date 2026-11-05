# 11 — Progress & Handoff (state of the world as of 2026-08-03, post-Phase 7 §7.0 / F28)

This file is the **session-independent memory** of the Android build. A fresh
assistant (or human) starting cold should read this AFTER the master README
and docs 01–10. Those docs say what to build; this one says what is already
built, how to run everything, and every gotcha learned the hard way.
**Update this file at the end of every phase.**

---

## 1. Where everything lives

| Thing | Path |
|---|---|
| Backend (**FROZEN — ask the user before changing any backend code**. Unfrozen **seven times** by explicit user instruction; all seven jobs are DONE and the backend is re-frozen: 2026-07-21 assistant conversation memory; 2026-07-22→23 "fix the FINDINGS.md items"; 2026-07-29 "Phase 6 Inbox — additive contract fields"; 2026-08-03 "Phase 7 §7.0 — FINDING F28, full scope"; 2026-08-03 "F30 + F29"; 2026-08-03 "F31 genericity"; 2026-08-05→06 "the Round 7 fixing phase" (three tranches, F36–F58, plus the demo-build findings F60–F63). **No unfreeze is currently granted.** See FINDINGS.md status table + §8-pre10.) | `C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project` |
| Android Studio project (ALL app work happens here) | `C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI` |
| Planning docs (the approved blueprint — follow, don't re-plan) | `Complete_Project\Android_Planning_Readmes\` (README + 01–10 + this file) |
| Product spec set | `Complete_Project\YuviPep_30_Workflows.extracted.md`, `YuviPep_Data_Model.md`, `YuviPep_Roles_and_Responsibilities.md` |

## 2. Phase status

> **Current: Phases 0–6 + Phase 7 §7.0 (F28) + §7.0b (F31) DONE & device-verified**, app
> **`0.7.4-round7fixes`**, backend **FROZEN**.
>
> ⏹ **Round 7 is CLOSED** (it ran 2026-08-03/05; three fix tranches followed, all done).
> The current work is the **datacentre demo** in `Workflow_simulation/Workflow2/`.
>
> **→ The live state of the world is §8-pre10 IN THIS FILE**, then **§8-pre11**
> (2026-08-25) below it, which is the newest. Every earlier `§8-pre*` is history
> and says so.
>
> **Project-wide, re-measured 2026-08-25: 66 findings F1–F69** (F18/F20/F21 never
> assigned) — **58 fixed or dissolved · 1 partly fixed (F58) · 4 open
> (F35, F54, F56, F67) · 2 no-fix (F5, F16) · 1 accepted (F26)**. That is 66.
> **`FINDINGS.md`'s status table is the authority** — and read its new *"How to
> read the status table"* note first: a cell beginning "OPEN" is usually not open,
> and eleven rows were found carrying no resolution at all, seven of them with a
> green tick. They have all been completed against the source.
>
> **The earlier claim on this line — "F1–F63, 2 open, F59 undiagnosed" — was wrong
> on every count** and is corrected above: the findings run to F69, and F59 turned
> out not to be a product defect at all.
>
> ⚠ **`Workflow_simulation/Workflow1/SIMULATION_RUNBOOK.md` is HISTORY, not the driver.** It
> drove Round 7 and its *"WHERE WE ARE RIGHT NOW"* block, its DB state and its do-not-touch
> list are all **expired** — the database it describes was wiped on 2026-08-06. Read it for
> the Round 7 story only. **The demo driver is
> `Workflow_simulation/Workflow2/DEMO_WALKTHROUGH.md`.**

- **Phase 0 — DONE & verified 2026-07-18** (emulator + real Vivo phone):
  scaffold, theming, networking core (auth + idempotency + host-override
  interceptors), encrypted TokenStore, Room shell, StateView, Splash, Login,
  forced password change, Environment sheet, role bootstrap — all six seeded
  roles logged in; kill→restore; wrong-password shows backend message
  verbatim; forced-change e2e via real admin reset; airplane-mode start shows
  cached-session banner.
- **Phase 1 — DONE & verified 2026-07-19** (real Vivo vs live backend):
  - Briefing card (`GET /digests/daily`, markdown via Markwon, "updated Xm
    ago", honest offline error).
  - Waiting-on-you feed on Home: pending approvals (Room cache-first) +
    proposed-assignment batch + review-pending meetings + triage count,
    inline Approve / Reject-with-note.
  - Approvals inbox (entity chips, stage filter — sales_lead defaults to
    Decide stage, expiry countdown) + ApprovalDetail (facts verbatim;
    message approvals preview the full draft via `GET /messages/{id}`).
  - **OfflineQueue**: generic {method, path, body, idempotency-key} rows in
    Room, drained FIFO by WorkManager; offline decide shows "Queued — will
    apply when you're back online", auto-applies on reconnect; a 4xx replay
    would show the backend's message on the card (never silent).
  - Notification center + bell badge + 60s foreground `?since=` delta
    polling + in-app snackbar + 15-min background WorkManager poll posting
    grouped system notifications (channels: approvals/escalations HIGH,
    tasks, reminders, general) — carries us until FCM in Phase 9.
  - Assignment confirm batch (per-task AI reasons; Change-person picker for
    manage_staff roles, honest explanation otherwise), minimal meeting
    review gate (keep/edit/drop → confirm → tasks live), triage list with
    Mark handled.
  - Acceptance verified live: approve→backend flips→feed clears; message
    approve→sent (dry-run email); plan_change reject-with-note→rejected;
    offline invoice approve queued then applied on reconnect; review
    confirm: kept→open, dropped→cancelled, meeting→completed; triage 2→1.
- **Phase 2 — DONE & verified 2026-07-19** (real Vivo vs live backend,
  build `0.3.0-phase2`):
  - **Leads list** (search w/ debounce, Mine/Important + state chips,
    state-colored dots, last-activity age, New-lead sheet → opens detail)
    + **Lead detail**: header (state chip → change-state dialog, importance
    star), 6 tabs (Overview facts/next-steps/followups/proposals, Contacts,
    Projects via `GET /projects?lead_id=`, Notebook, History, Meetings) all
    rendered through one generic `RowAdapter`; per-tab bottom action bar,
    role-gated (manage_leads / record_meeting).
  - **Suggestion banner** verified round-trip: seeded `suggested_state` →
    banner shows reason → Accept → `PATCH /state` → chip flips + history
    row "Accepted AI suggestion"; Keep-as-is = **local dismissal only**
    (prefs `yuvipep_lead_ui`, key per lead+state) because a same-state
    PATCH is a server no-op that does NOT clear the suggestion — the
    snackbar says so honestly.
  - **Contacts**: add/edit sheet (PATCH clears needs_review — "human just
    fixed it"); **card scan** (CameraX + guide overlay + torch, ≤2MB
    re-encode) verified with a REAL Telaverge card → OCR 100% confidence,
    verify-sheet with confidence/org-on-card lines + honest intro-draft
    notice ("waiting in Approvals, nothing was sent") → saved contact.
  - **Notebook** add-note → `POST /intelligence` (also feeds memory_ai).
  - **Consent sheet** (verbal/written/in_app + note) gates the recorder
    every time — there is no consent-on-file lookup endpoint, so the app
    never pretends to know.
  - **Recorder**: foreground service (mic type, AAC m4a 44.1k mono 96k,
    pause/resume, elapsed+amplitude LiveData), post-stop title+upload
    panel → `UploadMeetingWorker` (idempotency key minted at enqueue,
    IOException→retry, HTTP error→failure w/ verbatim message +
    notification; file deleted only after 200). Verified with a real 3:01
    recording (laptop TTS speech): upload → transcribe (local Whisper) →
    extract → **review_pending**.
    - ⚠ **The key is not what makes the retry safe** (2026-08-25): no route
      reads the header. What stops a duplicate is that the **consent record
      is single-use** — `ConsentRecord.meeting_id IS NULL` in the F40 lookup,
      set by the successful upload — so a retried upload is refused **422**
      with the consent message. Measured: two uploads of the same bytes → one
      meeting. **Two consequences to know:** the user sees a DPDP consent
      error for a recording that actually succeeded, and until 2026-08-25 the
      refused attempt also left a second copy of the audio in `STORAGE_DIR`
      that no retention sweep could reach (fixed: every refusal now precedes
      `save_bytes` — `tests/test_upload_no_orphan_audio.py`).
  - **Pipeline screen** (`MeetingDetailFragment`): 6-step stepper polled
    5s, failed→reason+Retry, review_pending→Review button, result section
    (LLM summary, action items, low-confidence warning, state suggestion).
    Also the deep-link target for `meeting` entities now (replaces direct
    review-gate link).
  - **Review gate full editor**: edit title/description, keep/drop
    switches, **Add-an-item-the-AI-missed** (id=null→created OPEN);
    verified in live DB: edited→open, kept→open, dropped→cancelled,
    added→open, meeting→completed.
  - **Typed-notes composer**: title + meeting-type dropdown + big text →
    `POST /meetings/notes` (120s timeout, "Planner is reading…" row) →
    generic "What the Planner did" dialog — live run produced
    `action: project_proposed` + project/plan ids from a 3-sentence note.
- **Phase 3 — DONE & verified 2026-07-20** (real Vivo vs live backend,
  build `0.4.0-phase3`, LLM = openrouter live):
  - **Assistant v1 (text)** — `AssistantFragment` on the Jarvis tab for
    every role: chat transcript (user/reply bubbles), personalized
    greeting, recent-command chips (prefs, newline-separated), IME-send.
    Replies carry "answered by the X agent" meta. Transcript lives in a
    singleton `AssistantSession` (survives tab switches, not process
    death — it's a working view; the backend keeps the audit).
  - **Action cards**: one card per `actions[]` entry, title = humanized
    tool name, body = generic `Pretty` renderer (maps→"Label: value"
    lines, ids skipped, empties dropped — new backend tools render day
    one with zero app changes). Failed tools show a "failed" badge with
    the error verbatim. Cards resolve their entity generically: explicit
    `*_id` keys first, then bare `id` + entity word from the tool name
    (`create_proposal`→proposal) → Open chip routes via
    `MainActivity.openEntity`, Why chip → WhySheet.
  - **Inline approvals (the Iron-Man loop)**: `pending_approvals[]` render
    as amber cards with the draft's facts + Approve&Send / Reject (reason
    dialog) wired to `POST /messages/{id}/approve|reject`; status becomes
    "Approved — queued to send." in place. Verified live end-to-end:
    "Create the IBC proposal for Nexora Technologies" → real proposal
    (₹59,000 from the pricing table) → "Make it warmer and more personal"
    → edit_narrative ("commercial table unchanged") → "Email the proposal
    to Anita" → prepare_email → inline Approve → **real SMTP send**
    (delivery log drafted→queued→sent; recipient was the user's OWN
    address standing in as the demo client contact — no third parties).
  - **ContextBus**: lead/proposal/meeting screens feed it on load; the
    assistant shows a closable "About: X" chip and passes
    lead_id/proposal_id/meeting_id with every command.
  - **WhyChip everywhere**: `WhySheet` (`GET /why/{type}/{id}`, trace
    verbatim incl. the honest "No AI decision is recorded for this
    record.") reachable from assistant cards, proposal detail header, and
    the lead suggestion banner (new Why button). Real trace confirmed via
    API on the Phase-2 project (planner assignment/plan_update entries).
  - **Honest failure**: tunnel cut → command shows mapped network error
    bubble + "your text is back in the box"; reconnect + resend worked
    (scheduling agent answered "You have no scheduled demos today.").
  - **Proposal detail** (`ProposalDetailFragment`, reached from lead
    Overview rows and assistant cards): status chip, total/template-v/
    pricing-v/sent-ago meta, **locked pricing card** rendered from
    `line_items` with "words editable, numbers not" note, narrative with
    the machine `<!--PRICING_START/END-->` block stripped, revision trail
    (v1 Initial draft, v2 instruction…), role+status-gated buttons
    (hidden once sent — verified on the sent Nexora proposal).
  - **Edit-by-instruction** from the detail screen (`POST /edit`) and via
    assistant both verified; revision rows update.
  - **PDF viewer**: `GET /proposals/{id}/download` → `FileRepository`
    (auth client, disk cache keyed by proposal+revision-count so edits
    bust the cache) → platform `PdfRenderer` page list in-app. Rendered
    server PDF verified on device (commercials table intact).
  - **Upload-revision (G3)** via SAF picker: valid hand-made PDF
    containing the locked total → accepted, "Revision 2 uploaded /
    Re-submit for internal review", DB row "Manually edited file
    uploaded (…)", proposal pdf_path→manual file, status→draft; tampered
    PDF (total 49,000) → **refused** with the backend's message shown
    verbatim in a dialog ("The locked total 59,000 INR was not found…").
  - **Submit-review**: `POST /submit-review` → ₹59,000 is below every org
    rule → status `approved_internally` immediately (DB-confirmed).
  - **Approve&Send sheet** (to/CC validation, optional note, "this really
    emails the client" warning) built; the assistant path exercised the
    same backend route live.
- **Phase 4 — built and verified live on the real Vivo phone against the
  live backend across two passes, 2026-07-20/21** (build `0.5.0-phase4`
  + two post-verification hotfixes; **one item still open, see below —
  do not call this phase fully closed until it is**):
  - **Projects portfolio** (`ProjectsListFragment`): health-first sort
    (delayed→at_risk→on_track→unknown), status filter chips, health dot +
    reason line.
  - **Project home** (`ProjectDetailFragment`, reached from a lead's
    Projects tab or the portfolio): header (status pill, health chip, Why
    link → `WhySheet` on `entity_type="project"`), **live "What's
    blocking?" card** (`GET /whats-blocking`, LLM-backed, Retry button) —
    verified live: "Nothing is blocking Green Valley School IBC Demo —
    health is on_track." Quick actions row: Record meeting here (reuses
    the Phase-2 consent→recorder flow against the project's lead), Draft
    message (contact picker → `POST /messages/draft`, new wiring this
    phase), Catch me up (`GET /brief`), Split into branches (Chain
    wizard, hidden on projects that are already a branch).
  - **8 tabs**, all through the same generic `RowAdapter` as lead detail:
    Overview (next 3 open tasks + open commitments), **Plan** (version
    list, tap → diff dialog via `Pretty.value(changes_from_previous)`),
    **Tasks** (grouped/sorted by phase, P1 badge, blocked badge, tap →
    Task detail), **Timeline** (`progress_events` humanised, details via
    `Pretty`), **People** (stakeholders — role/influence/channel, Why
    button per row for provenance, Add-stakeholder flow via the lead's
    contact list), **Team** (members, Add-member gated to `MANAGE_STAFF`
    since it needs `GET /admin/users` to search staff — honest toast
    otherwise, matches the Phase-1 assignment-override precedent),
    **Conflicts** (list + inline resolve dialog; honest empty state
    verified — Green Valley project has none), **Reports** (weekly
    client/internal report generation, honest "nothing happened this
    week" skip path).
  - **Chain wizard** (`ChainWizardSheet`): branch-name chips + invoicing
    mode → `POST /projects/{id}/children`.
  - **My Tasks** (`MyTasksFragment`, now the real screen behind the
    `tab_tasks` bottom-nav slot for sales_agent/operations_agent):
    Blocked / Today / This week / Later groups (no "waiting on vendor"
    group — see §6e), P1-first sort within each group, colored left edge
    on P1 cards. Verified live: opened a real task, ran **Block → Unblock
    round-trip** against the live backend (Snackbar confirmed each step,
    a real push-style notification "Unblocked: …" arrived back through
    the existing Phase-1 notification pipeline, and the list correctly
    dropped the task from Blocked back to Later on return).
  - **Task detail** (`TaskDetailFragment`): description, "assigned
    because" + Why chip, dependencies (tappable when resolvable),
    commitment linkage, progress slider (`POST /progress`), and the full
    lifecycle action set — Done, Decline (assignee-gated, hidden
    otherwise — verified: a task assigned to Siva showed no Decline
    button when viewed by Rahul), Block/Unblock, New date (shows the
    ripple-break routing honestly), Split, Vendor promise/slip. A task
    opened via the project (rich) is enriched with the thin
    `/action-items` fields too (description, assignee name) — verified
    live: a project-sourced task rendered its full narrative AND its
    `assignment_reason` simultaneously.
  - **Follow-up verification round (2026-07-21, same day, user asked to
    "test it man, no concern regarding timing")** closed almost every gap
    left open above, switching accounts on-device across all four roles
    (Rahul/sales_agent, Sourav/operations_agent, Siva/sales_lead,
    Mithun/operations_lead) via the real Sign-out → login flow. Verified
    live with DB cross-checks after each write:
    - **Projects portfolio + its status filter chips**: confirmed the
      filter actually narrows the list (picking "Proposal stage" against
      two Planning-only projects correctly emptied it with the honest
      empty state, not just a visual toggle).
    - **Chain wizard**: created a real branch ("Bengaluru Campus") —
      verified in DB: new child `Project` row with `parent_project_id`
      set + a new `Lead` row with `source="chain_deal"`.
    - **Pipeline tab (sales_lead)**: both the Leads and Projects
      sub-tabs render live data; the nested `LeadsListFragment` (incl.
      its own New-lead FAB) works correctly embedded inside
      `PipelineFragment`'s child container.
    - **Delivery tab (operations_lead)**: confirmed reachable and
      rendering the portfolio correctly.
    - **Task lifecycle — every remaining action**: **Split** (DB-verified
      two new linked child ActionItems, second `depends_on_ids` the
      first); **Vendor promise** (DB-verified `external_wait` JSON
      written) and **Vendor slip** (DB-verified `promised_date` updated)
      — slip additionally triggered a genuine backend side effect worth
      knowing about, see §6e; **New date** — verified BOTH outcomes: the
      ripple-break path fired for real (a client-commitment conflict was
      detected, the app showed "This breaks: …" verbatim, and a real
      notification landed on the phase lead's device, screenshotted
      live); **Decline** — verified hidden for two different non-assignee
      viewers (Rahul and Sourav, both looking at Siva's task) and then
      verified working end-to-end as Siva declining her own task
      (backend correctly returned the honest "no one else found — your
      phase lead has been notified" outcome, since Siva already *is* the
      phase lead).
  - **Two real bugs found live and fixed in this same round** (not just
    noted — fixed, rebuilt, reinstalled):
    1. **TabLayout indicator desync**: returning from a pushed screen
       (e.g. Task detail) recreates `ProjectDetailFragment`'s view, which
       re-adds all 8 tabs and defaults the visual indicator to position 0
       while the actually-rendered content stayed on whatever tab
       `currentTab` remembered — content and indicator disagreed. Fixed
       by explicitly re-selecting `binding.tabs.getTabAt(currentTab)`
       after re-adding tabs, *before* attaching the selection listener
       (so the restore doesn't re-trigger a render). This was the exact
       same bug already known and merely documented (not fixed) in
       `LeadDetailFragment` since Phase 2 — fixed there too while at it.
    2. **Missing UI trigger**: `phase-shift` had a repository method but
       *no button anywhere* — the handoff claim that ops_lead's Delivery
       board reaches phase-shift "from each project's home screen" was
       false until this was caught. Added a "Shift phase" quick-action
       chip (gated to operations_lead/org_admin) that opens a 6-phase
       picker. Building it exposed a **second** bug: the gate first used
       `RoleGate.has(role, RoleGate.OPERATIONS_LEAD)` — `has()` expects a
       *permission* string as its second argument, not a *role* string;
       passing a role there compiles fine (both are `String`) but always
       silently returns `false` (`MATRIX.get("operations_lead")` is
       null). Fixed to a direct `RoleGate.OPERATIONS_LEAD.equals(role) ||
       RoleGate.ORG_ADMIN.equals(role)` check. Re-verified the chip now
       renders for Mithun (operations_lead) and its dialog opens with all
       six phase options. **Lesson for any future `RoleGate.has()` call**:
       its second argument must be one of the `RoleGate.*` *permission*
       constants (RECORD_MEETING, MANAGE_STAFF, …), never a role constant
       — check by grepping which `setOf(...)` list a constant appears in
       inside `RoleGate`'s static block before using it as a permission.
  - **All five open items CLOSED on 2026-07-21** (Phase 4 is now fully
    done). What closing them revealed:
    1. **Shift-phase works end-to-end** — verified with exact-bound tap:
       plan v3 "Preparation wave derived from the project objective"
       (trigger `phase_shift`, active) created + rendered in the Plan
       tab. **Discovery**: the previous session's "inconclusive" tap HAD
       submitted — it hit list item 0 ("Sales"), creating plan v2's
       sales wave, whose LLM-derived commitments were due "now" →
       instantly broken → Nexora health `delayed`. That cascade was the
       stray shift, not a bug. Note: phase-shift does NOT change
       `project.status`; it creates a plan version + task wave (and an
       assignment batch for the phase lead). A `no_playbook` outcome is
       still HTTP 200 → the app would show the generic success snackbar
       (minor honesty nit, unfixed).
    2. **TabLayout-indicator regression passed** (Tasks stays highlighted
       after back from Task detail, content agrees).
    3. **Reports "Generate" was never silent** — `GET /weekly-report`
       returns instantly (`{"skipped":true,"reason":"nothing happened
       this week / on hold"}`) and the skip-reason Snackbar (2.75s) had
       simply fallen between screenshot polls both sessions. Captured on
       screen this time.
    4. **Add stakeholder verified end-to-end** (as Siva): contact picker
       → fields dialog → Save → "Saved." snackbar + row reload;
       DB-confirmed UPSERT by (project, contact) — re-adding an existing
       stakeholder updates, never duplicates. **Add member**: honest
       toast verified in-app for ops_lead; the org_admin end-to-end run
       is BLOCKED — see the finding below — so the contract was verified
       at API level (GET /admin/users → POST /members 200; Sourav is now
       a real Nexora member, DB-confirmed) and the in-app run waits for
       Phase 8.
       **FINDING: org_admin currently has NO navigation path to any
       project, lead, or task screen** (bar = Home·Approvals·Jarvis +
       two Phase-7 placeholders; admin notifications are digests-only;
       no assistant tool result carries a project_id/lead_id key an Open
       chip could use). The org_admin-gated Team-tab "Add member" is
       therefore dead UI until Phase 8 builds the admin area. Revisit
       then.
    5. adb reverse re-established at session start (no drop this time).
  - Genericity: zero new domain vocabulary; `LeadStates.label()` (Phase 2)
    reused as-is for status/health/phase/priority humanisation.
  - New backend surface used (all pre-existing, none added — backend
    stayed frozen): `/projects` (list/detail/timeline/plans/status/
    phase-shift/whats-blocking/brief/stakeholders/conflicts+resolve/
    children/weekly-report/members), `/action-items`, `/tasks/{id}/...`
    (complete/decline/block/unblock/progress/new-date/split/vendor-
    promise/vendor-slip), `/messages/draft`.
- **Phase 5 — CORE BUILT & verified live 2026-07-21** (real Vivo vs live
  backend, build `0.6.0-phase5`; three same-day builds — base + calendar
  cell fix + dictatable assistant-reject):
  - **core/voice** (02 §2, 04 §3): `SpeechInput` (SpeechRecognizer
    wrapper, live partials, honest per-error-code messages),
    `VoiceEditText` (TextInputEditText subclass with a tappable mic end
    icon → in-place dictation; swapped into EVERY programmatic dialog
    EditText — reject notes via `DecideDialogs` + assistant reject, all
    task-lifecycle note/reason/date fields, stakeholder fields, conflict
    resolution, meeting-review edits — and the notes-composer XML),
    `TtsSpeaker` (speak-replies toggle, prefs `yuvipep_voice`, system
    `TextToSpeech` engine; **the sherpa-onnx/Kokoro neural voice is NOT
    integrated yet** — doc 04 gates it on a Phase-5-start model
    re-verification that hasn't been run; the speaker interface is built
    so the neural engine slots in behind it, and the voice-picker/rate
    settings screen is deferred with it).
  - **Assistant voice**: mic button beside send — tap → listening (stop
    icon + "Listening…" hint), live partials fill the input, final text
    AUTO-SENDS (the Iron-Man loop); RECORD_AUDIO requested via
    ActivityResult; speak-replies toggle (volume icon) in the header
    speaks reply summaries (≤300 chars) when on.
  - **Demos** (03 §11): `DemoCalendarFragment` — Monday-first month grid
    (RecyclerView 7-span), per-day demo dots (max 3 + "+"), free-day
    count, month meta line, day tap → that day's demos, demo tap →
    detail dialog with Reschedule/Update-status (gated
    `update_demo_status`, honest toast otherwise); `BookDemoDialog` from
    the lead Overview action bar (gated `schedule_demos`, honest toast
    otherwise): date/time/notes + team Spinner fed by
    `GET /admin/demo-teams` (auth-only — readable by every role); result
    dialog renders the backend's `warning` (clash) AND the invite
    outcome (`invite_message_id` → "drafted and waiting in Approvals —
    nothing has been sent yet." / `invite_note` verbatim / "No invite
    was drafted.").
  - **Follow-ups** (03 §12): `FollowUpQueueFragment` — due filter chips
    (today/overdue/this_week/all_pending) + "Mine only" switch, overdue
    badge, row tap → Mark done (note + "schedule next" checkbox; relays
    the backend's `next_followup_due` honestly) / Draft message (AI —
    lead contacts → `POST /messages/draft`, approval-gated) / Open lead.
  - **Home "My day" row**: two always-visible cards (all roles hold
    view_demos/view_leads) — Demos (today/this-month count) and
    Follow-ups (due-today count) — the stable entry points to both new
    screens; counts refresh on resume, honest "unavailable offline".
  - **Polish**: raw-ISO due dates ("due 2026-07-30T00:05:28.480060")
    humanised everywhere via new `Times.dateLabel` ("due 30 Jul"; year
    added when not current; raw string on parse failure).
  - **Verified live on the Vivo, DB-checked after every write**:
    calendar render + day drill-down (real seeded demos); **reschedule**
    (DPS demo 27→28 Jul as admin) → "Rescheduled — the updated invite is
    drafted and waiting in Approvals." + DB `scheduled_date` flipped +
    real `demo_invite` outbound_message `pending_approval`; **booking
    with clash** (Green Valley, 2 Aug, team Alpha — Alpha already busy)
    → result dialog with "Heads up: Alpha already has a demo on
    2026-08-02" verbatim + invite-drafted line, DB row confirmed; the
    SAME clash warning also rendered through the **scheduling agent's
    action card** ("Booked: true … Warning: Alpha already has a demo at
    Delhi Public School on 2026-07-28." + Open/Why chips) for a second
    booking on 28 Jul; **follow-up complete** (Siva's overdue Sunrise
    row) → "Done — next follow-up set for 2026-07-28." + DB
    done-with-note + auto-scheduled next `pending`; **voice**: three
    live SpeechRecognizer sessions (laptop-TTS-through-speakers audio) —
    live partials, auto-send with the lead context chip, honest
    recognizer errors ("Didn't catch that — tap the mic and try
    again."); **dictation into the reject-note field** (mic inside the
    dialog) landed spoken text live in the field, then reject completed
    → card flipped to "Rejected — nothing was sent." + DB
    `status='rejected'` (no server redraft on the message-level reject
    path — that behaviour belongs to the approvals-table path).
  - **One real bug found+fixed live**: recycled blank leading cells in
    the calendar grid kept the selected-day circle (background never
    reset in the null-day bind branch).
  - **Honest deferrals within Phase 5**: neural TTS + voice settings
    (above); app shortcuts (long-press icon); TTS spoken audio not
    audio-verified (adb can't hear the phone; code path is plain
    system-TTS `speak`); **STT accuracy with faint speaker audio garbles
    entity names** ("team Alpha"→"Gmail") — the pipeline is verified,
    but doc 10's Phase-5 "physical device mic/locale session" with the
    user is still worth doing for real-voice quality.
  - **New backend surface used (all pre-existing, backend still
    frozen)**: `GET/POST /demos`, `GET /demos/calendar`,
    `PATCH /demos/{id}`, `GET /admin/demo-teams`, `GET /followups`,
    `POST /followups/{id}/complete`.
- **Conversation memory — DONE 2026-07-21 (backend unfrozen on user
  instruction; the only backend change since the freeze).** The user asked
  why the chat "forgets the previous message". Root cause was structural,
  not the model and not embeddings: `/assistant/command` accepted only
  `text`, and `BaseAgent.run` opened a fresh message list every call, so
  each turn was an island. `ai/memory.py` (embeddings) was never involved —
  it is the org's long-term notebook, and chat turns were never written to
  it.
  - **Backend**: new `assistant_turns` table (Data_Model §2.10) +
    `app/ai/conversation.py` (load/save/prune/clear);
    `BaseAgent.run(..., history=)` seeds `messages` and the system prompt
    gains an "ongoing conversation" note; `orchestrator.route(ctx, text,
    history)` puts the last 4 turns in the router prompt (a nounless
    "make it warmer" used to fall through to `query`); `handle_command`
    takes `session_id`. New `GET`/`DELETE /assistant/history`.
    Settings: `ASSISTANT_HISTORY_TURNS` (12), `..._CHAR_BUDGET` (6000),
    `ASSISTANT_SESSION_MAX_TURNS` (60), `..._RETENTION_DAYS` (90).
  - **Deliberate fences**: plain text only (no tool calls / results /
    entity ids replayed — stale ids would dodge a permission change, and an
    unpaired `tool_result` is rejected by all three providers); scoped to
    (org, user, session); strictly alternating starting with the user;
    never fatal (a failed history read/write logs and the command still
    runs). Retention sweep drops old conversations; `erase_contact` purges
    turns naming the erased person.
  - **App** (`0.6.1`): `AssistantSession` mints/persists a `session_id`,
    sends it on every command, restores the transcript on cold start,
    a **+** button starts a new conversation (and DELETEs the old one),
    and logout wipes it (shared-device isolation).
  - **Back-compatible**: no `session_id` = the old stateless behaviour,
    nothing recorded — scripts/tests unchanged. An APK built before this
    still works against the new backend (Gson ignores the extra field).
  - **Verified**: pytest 42/42, dryrun 43/43, verify_gap_endpoints 21/21,
    `scripts/verify_live_conversation.py` **12/12 live on OpenRouter**
    (pronoun follow-up answered, nounless command routed to `followup`,
    session isolation, cross-user isolation, replay/forget, stateless
    path untouched); schema migration proven additive on a copy of
    `data/salesplatform.db` (no drops, zero row-count deltas). **Not yet
    tap-tested on the Vivo** — see §8-pre.
- **Full end-to-end simulation — DONE 2026-07-21/22. See `Complete_Project/FINDINGS.md`.**
  Everything through Phase 5 + conversation memory was exercised on the real
  Vivo against a **freshly seeded DB** with **live SMTP + live Google
  Calendar**, across all 9 seeded accounts, using a **real business card**
  and a **real 2:47 recorded meeting**. 16 findings, all observed live.
  - **This closes §8-pre2**: conversation memory is now tap-tested on the
    device (nounless follow-up routed to the proposal agent, cold-start
    transcript restore, **+** new chat with the backend DELETE verified).
  - **Top 3 (all backend, all previously unknown):** (1) the **audio meeting
    pipeline never calls the planner** — `POST /meetings/notes` does, so
    typing notes yields a project + plan + dated tasks + commitments +
    stakeholders + assignments while recording the same meeting yields six
    flat tasks; the notes composer's own copy claims parity, which is false.
    (2) `pipelines.py:111-113` puts `due_hint` in the *description* only, so
    **every meeting task has `due_date = NULL`** and is invisible to the
    digest buckets, My Tasks grouping and the nudge ladder. (3)
    `ai/extraction.py:12-24` hardcodes "school" in the prompt, which wrote
    *"The school operates offices in Bengaluru, Hyderabad, and Pune"* into
    `client_intelligence` for an engineering-services client — a **false fact
    in permanent org memory**.
  - **§6c is out of date**: its claim that `knowledge_engine` holds "the ONLY
    user-visible domain-worded string" is wrong — `ai/agents/resolvers.py:40`
    printed "No school matching 'Ekaghni' found" straight into the Jarvis chat.
  - **Nothing was fixed** (backend frozen; most findings are backend). Fix
    order and the live-mode residue list are at the end of FINDINGS.md.
    *(Superseded — see the fix session below.)*
- **FINDINGS fix session #1 — DONE 2026-07-22** (backend unfrozen by the user for
  the named job "fix the FINDINGS items"; **F4/F4b, F8 and F9 fixed, verified and
  shipped** as app build `0.6.2-findings`). Full write-ups live in `FINDINGS.md`
  itself — each fixed finding now carries a "How it was fixed" block, and the file
  opens with a ✅/⬜ status table. Handoff-level facts only here:
  - **F4/F4b** — `app/ai/extraction.py` no longer hardcodes "school" (kwarg is
    `client_name` at all three call sites). Crucially the prompt now ALSO forbids
    assuming an unstated industry — removing the word alone does not stop a model
    inventing a domain. New `scripts/verify_live_meeting_extraction.py` (8/8 live)
    replays the **verbatim transcript of the real 2:47 simulation recording** and
    checks BOTH directions: nothing invented for a neutral client, and a client
    that really IS a school still described as one.
  - **F8** — extraction is given today's date and returns an ISO `due_date`;
    `pipelines.py` writes it to the **column**, not into the description text. A
    hint the model cannot resolve stays as prose rather than becoming a guessed
    date the nudge ladder would act on.
  - **F9** — **recording now starts the Planner.** Shape chosen with the user: the
    review gate goes FIRST, then `POST /meetings/{id}/review/confirm` enqueues a
    new **`plan_meeting`** job seeded with the human-confirmed to-dos, so the plan
    is built AROUND them (inline in the pipeline when the org has the review gate
    switched off). Recording is now *richer* than typing, not merely equal to it.
  - **New backend surface — all additive, older APKs unaffected:**
    `POST /meetings/upload` accepts an optional `project_id`;
    `POST /meetings/{id}/review/confirm` returns an extra `planning` boolean; new
    job type `plan_meeting`. **No schema change at all**, proven by diffing a copy
    of `data/salesplatform.db` against a freshly-initialised schema (55 tables,
    0 columns added or dropped) — so there was nothing to migrate, and the §7
    "prove it additive" step is recorded as vacuous rather than skipped.
  - **App:** `ReviewConfirmResponse.planning` + new
    `review_confirmed_planning_toast` ("…The Planner is building the plan from this
    meeting — the project and its approvals will appear shortly."). Without it the
    new behaviour would have been invisible, which §7 rule 3 forbids.
  - **Verified:** pytest **50/50** (44→50, six new tests), dryrun **43/43**,
    `verify_gap_endpoints` **21/21**, `verify_generic_stakeholders --stub`
    **21/21**, `verify_live_meeting_planner.py` **22/22 live**,
    `verify_live_meeting_extraction.py` **8/8 live**, plus **four real recordings
    on the Vivo** against the live backend covering both branches — a lead that
    already had a project **merged** (plan v1 superseded → v2 active, no fork), and
    two project-less leads each **birthed a project** with phased dated tasks,
    client commitments and a stakeholder in the client's own vocabulary
    (`vp_operations`, `safety_head`).
  - **Three problems the FINDINGS write-up had not seen, all fixed — see §6g.**
  - **A regression shipped with F9 and was fixed the same day — `FINDINGS.md` F22**
    (each confirmed to-do stored twice). Fixed by plan-task **adoption**; see F22's
    "How it was fixed" block and §6g.
- **FINDINGS job — COMPLETE 2026-07-23.** Every fixable finding is fixed & (where the UI could
  reach it) device-verified: 2026-07-22 F4/F4b, F8, F9, F22, F1, F2, F10, F3, F11, F6; 2026-07-23
  F17, F19, the copy pass F7/F13/F14/F15/F12, F23, F24, F25. **Backend re-frozen.** pytest 67/67,
  three new live scripts, no schema change. Non-fixes remaining: F5 (monitor), F16 (Phase-8
  scope), F26 (accepted), F27 (**since CLOSED** by Phase 6 on 2026-07-29). **The ✅ status
  table at the top of `FINDINGS.md` is the single source of truth**; read it before this
  list. The build at the end of *that* job was `0.6.5-findings`; **the current build is
  `0.7.0-phase6`** (§8-pre5).
- **Phase 6 — DONE & verified 2026-07-29** (real Vivo vs live backend, build
  `0.7.0-phase6`): the **Inbox** — `feature/inbox/` — closing **FINDINGS F27**.
  - **InboxFragment**: two halves behind a tab strip, plus "Log a reply". A role
    without `send_messages` gets the triage queue with **no tab strip at all**
    rather than a Messages tab that would 403 (§7 rule 3), and no Reply button.
  - **Message centre**: org-wide `GET /messages` with status chips
    (draft→pending→queued→sent→delivered/failed) rendered as a humanised trail,
    plus a **visible** Mine/All filter (agents default to Mine, leads/admin to
    All) — the server's scope is unchanged, the client filters honestly.
  - **Delivery trace**: the `delivery_log[]` timeline in the reader's own
    timezone, and "Open the message that was sent" for a dry-run send — the
    `sent` event's `detail` is `dry_run:<path>`, fetched through the existing
    `GET /files/{path}` and shown as raw RFC-822. It says on screen that it
    cannot list attachments, because the payload does not carry them.
  - **Inbound triage** (replaces the Phase-1 `feature/triage/` slice, now
    deleted): intent + reason + summary — **no confidence, because none
    exists** — with attach-to-client (lead→contact), attach-to-project, set
    intent, read-in-full and mark-handled.
  - **The reply route (F27)**: from a triage card straight into the assistant,
    scoped to the client and pre-filled with a drafted command. The email agent
    writes it and parks it for the one-tap approval the assistant already
    renders. **No new send endpoint, and the Inbox itself sends nothing.**
  - **Log client reply**: dictatable, channel-aware (a call picks contacts by
    phone, email by address), through `POST /inbound/ingest` — and it shows
    what the engines *made* of it rather than a "Saved" toast.
  - Nav: `openEntity("inbound_message")` now opens the Inbox instead of the
    honest "later phase" toast — **that toast was F27's dead end in the app**;
    `outbound_message`/`message` open the delivery trace.
- **Phase 7 §7.0 — DONE & verified 2026-08-03** (real Vivo vs live backend, build
  `0.7.1-f28`): **FINDING F28 closed** — the assistant now understands a short, natural
  command, and when it genuinely cannot it **asks** instead of failing. Backend unfrozen
  for this one named job and **RE-FROZEN**.
  - **`resolvers.py` is one shared ladder** used by all five resolvers: exact id → exact
    name/code → exact email/phone → address **inside** the hint → hint inside the name
    (the old behaviour, kept verbatim) → **name inside the hint** → significant-token
    overlap. First productive stage wins, so an exact hit is never diluted by a fuzzy one.
  - **The client's words are stripped as a fallback stage, never as a pre-step** — that
    ordering is what keeps "Mrs. Nair" at "Nair Industries" working. It may only narrow an
    ambiguity, never redirect it to a different person.
  - **`NeedsConfirmationError`** (a `ValidationFailedError` subclass, so it stays a 422 and
    existing handlers still catch it) turns "unsure" into a question carrying candidates.
    `resolve_contact` also stopped picking `contacts[0]` when nobody is marked primary — a
    silent guess at the recipient of a client email. A designated primary is still honoured.
  - **App `0.7.1-f28`**: a `QUESTION` chat card (amber, never the red *failed* badge) with
    one chip per candidate that fills the input box; **both** triage reply prompts reverted
    to natural phrasing — reverting only the one the write-up named would have left half
    the route untested.
  - Suites: pytest **86/86** (+13, each watched failing with its own fix disabled — and the
    first version of the suite passed with the F28 stage deleted, which is why they were
    rewritten), dryrun 43/43, gap 21/21, stakeholders --stub 21/21, new
    `verify_live_resolution.py` **16/16 three runs running**. **No schema change.**
  - **Two findings opened and then also fixed the same day** under a second, separate
    unfreeze (*"F30 + F29"*), app `0.7.2-f30`:
    - **F30** — drafts reached the approval gate carrying `[Name]` blanks, and most sat past
      the card's 300-character preview, so the approver was asked to approve text they were
      never shown. New `draft_check.py` refuses them at **both** approve routes, with an
      explicit `allow_blanks` override; the inline preview went to 1200 characters and says
      when it is still truncated. Live-model check found **no false positives** on real
      drafts. Device-verified end to end, including "Send as it is".
    - **F29** — `build_daily_digest` was the lone place bucketing follow-ups on
      `utcnow().date()` while six neighbours used the local date. Fixed; proven with a test
      that forces the condition rather than waiting for 1am, and seen on the device at 03:06
      IST inside the real failure window.
    - Suites after both: pytest **96/96**, dryrun 43/43, gap 21/21, stakeholders --stub
      21/21, `verify_live_resolution.py` **19/19 three runs running**. No schema change.
- **Phase work NOT yet started (everything above this line is built):**
  - **Phase 7 §7.1 — Money & ops ← THIS IS NEXT.** §7.0 (F28) is done, so the money screens
    are now the front of the queue: invoices, incidents, vendors, leave, bookings,
    deliverables. **Backend is FROZEN again** — ask before changing it.
  - **Phase 8 — Admin & platform.**
  - **Phase 9 — Push, polish, release.**
  - **Phase 5's deferred slice** (not a phase of its own — pick up when convenient):
    neural TTS (sherpa-onnx + Kokoro, wifi-only model download, voice settings), app
    shortcuts, and a real-mic quality session with the user.

## 3. How to run everything (Windows)

> **This is THE current recipe — use it, not the older tunnel-based one.** Rewritten
> 2026-07-29 because this section still said "run on port 8001 behind a cloudflared
> tunnel", which contradicted §6g and §8-pre5 and would have sent a newcomer straight into
> an occupied port. **`adb reverse` replaced the tunnel** — no rotating URLs, no rebuild to
> change the base URL, and the phone's stored preference never has to change.

**Step 0 — check for an orphaned backend before starting one** (§6g: one survived a whole
session once, serving stale code against the live DB with live SMTP):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId, CommandLine
```

**Step 1 — start the backend.** Use **port 9010**. Avoid the whole **8xxx** family: VS Code
holds a loopback forward on 8000 and ComfyUI has taken both 8000 and 8001.
`EMAIL_MODE=dry_run CALENDAR_MODE=off` are **environment overrides**, so `.env` stays
untouched and a plain restart returns to live email/calendar (`EMAIL_MODE` in `.env` is
`smtp` = **LIVE** — see §7 rule 5 and ask the user before anything that really sends):

```powershell
cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project
$env:PORT="9010"; $env:EMAIL_MODE="dry_run"; $env:WHATSAPP_MODE="dry_run"; $env:CALENDAR_MODE="off"
python run.py
```

> ⚠ **The datacentre demo is the exception — it needs real mail and real invites.** Start it
> **without** the `EMAIL_MODE` / `CALENDAR_MODE` overrides so `.env` applies (`smtp` +
> `google`), i.e. only `$env:PORT="9010"`. **That configuration really sends.** Never add an
> `INBOUND_EMAIL_MODE` override — it must stay `off` (**F35**).

```powershell
# demo / live-mail configuration
cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project
$env:PORT="9010"
python run.py
```

Confirm it is **your** backend and not a survivor: the log must print **`Platform ready`**,
and `http://127.0.0.1:9010/health` must return `{"status":"ok","llm_provider":…}`. Checking
`/health` alone is not enough — a stale process answers it too.

**Step 2 — point the phone at it.** `adb` is **not on PATH**:

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb devices                          # Vivo = 10BFBT0TXJ001NP
& $adb reverse tcp:8000 tcp:9010        # phone's :8000 → laptop's :9010
```

The phone's in-app base URL preference **stays `http://127.0.0.1:8000`** and never changes.
Use `MSYS_NO_PATHCONV=1` when passing on-device paths through Git-Bash.

**Step 3 — build and install:**

```powershell
cd C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat :app:installOrgDebug      # builds AND installs on the attached device
# .\gradlew.bat :app:assembleOrgDebug   # APK only → app\build\outputs\apk\org\debug
```

**Step 4 — when you finish**, stop the backend, `& $adb reverse --remove-all`, and re-check
for orphans with the Step 0 command.

- **Emulator instead of a phone?** No `adb reverse` needed — use the in-app **Environment
  sheet** (debug builds: long-press the logo on Splash/Login) and its "Emulator localhost"
  preset `http://10.0.2.2:8000`, with the backend on 8000.
- A public tunnel (cloudflared) is only needed for a device **not** attached over USB. Its
  URL rotates on every restart, so you must then update `DEFAULT_BASE_URL` in
  `app\build.gradle` and rebuild, or set it in the Environment sheet. `adb reverse` avoids
  all of that — prefer it.
- ⚠️ **`pm clear` wipes the stored base URL** and the app falls back to a dead default
  tunnel URL. If the app suddenly cannot reach the backend after a data wipe, reset the
  preference to `http://127.0.0.1:8000` in the Environment sheet.
- Logins (seeded by `scripts/seed_demo.py`, idempotent), password
  `Password@123`: admin@ (org_admin), rahul@ (sales_agent), siva@
  (sales_lead), mithun@ (operations_lead), sourav@/baski@ (operations_agent)
  — all `@yuvipep.com`. Super admin: `superadmin@platform-yuvipep.com` /
  `SuperAdmin@123` (changed in `.env` because pydantic EmailStr rejects the
  reserved `.local` TLD; config-only change, flagged to the user).

### Device-driving tricks (automated verification)
- User's Vivo V2514, adb serial `10BFBT0TXJ001NP`. Drive with
  `input tap/text` + `uiautomator dump` for exact bounds.
- `adb shell input text` needs `%s` for spaces.
- Screenshots: `adb shell screencap -p /sdcard/x.png` then `adb pull` —
  NEVER PowerShell `>` redirect (corrupts binary).
- Tunnel-independent testing: `adb reverse tcp:8000 tcp:<backend port —
  8001 while VS Code owns loopback 8000>`, then write the override pref
  `shared_prefs/yuvipep_env.xml` (base_url = `http://127.0.0.1:8000` —
  the PHONE side always stays 8000) via `adb push` to /data/local/tmp +
  `run-as com.yuvipep.app cp` (echo mangles the XML quoting). Delete the
  pref + `adb reverse --remove-all` when done so the app falls back to
  the tunnel default. (As of 2026-07-20 the pref IS present on the phone
  — see §8.)
- Deterministic Phase-1-style test data can be inserted straight into the
  live SQLite DB with a script importing the app's models (pattern: the
  Phase 1 seeder created real OutboundMessage/Approval/Assignment/Meeting/
  ActionItem/InboundMessage rows tagged `[phase1-verify]`).

## 4. Toolchain facts (do not relearn)

- Java 17 only (no Kotlin), MVVM + LiveData + Hilt + Room + Retrofit/OkHttp,
  Material 3, ViewBinding, minSdk 26 / targetSdk 35 / compileSdk 36,
  flavors `org` | `platform`.
- AGP 9.1.1 + Gradle 9.3.1: Hilt plugin **must be ≥ 2.58** (using 2.60.1) —
  older fails with "Android BaseExtension not found".
- targetSdk 35 forces edge-to-edge → `fitsSystemWindows=true` on activity
  roots.
- FLAG_SECURE on AuthActivity is release-only (debug allows screencap).
- WorkManager Workers use the Hilt **EntryPoint** pattern (no androidx.hilt
  extension): see `QueueDrainWorker` / `NotificationPollWorker`.
- Room v2 entities: cached_user, cached_notification, cached_approval
  (localState: `""` | `queued` | `failed:<backend msg>`), queued_write.
  `fallbackToDestructiveMigration` is ON (dev phase).
- Key singletons: `OfflineQueue` (core/net — generic replay, mint the
  idempotency key at intent time and pass it explicitly on decide),
  `ForegroundPoller` (60s, started/stopped by MainActivity),
  `NotificationRepository`, `ApprovalsRepository`, `WorkflowRepository`.
- Navigation: MainActivity role-shaped bottom tabs + `push(Fragment)` back
  stack; `openEntity(type, id)` deep-links approval→detail,
  meeting→pipeline, lead→detail, proposal→detail (Phase 3), project→detail,
  action_item→task detail (Phase 4, no project context from a bare id —
  the screen still works, just narrower); unknown types get an honest
  "later phase" toast. Phase 4 tabs: sales_agent/operations_agent
  `tab_tasks`→`MyTasksFragment`; operations_agent `tab_projects`,
  operations_lead `tab_delivery`→`ProjectsListFragment`; sales_lead
  `tab_pipeline`→`PipelineFragment` (Leads/Projects toggle). The two
  staff-roster "Team" tabs (sales_lead, operations_lead — load bars,
  skills matrix) and sales_agent's "Inbox" (message center) are still
  placeholders, deliberately relabelled off "Phase 4" this session so the
  UI doesn't contradict a phase marked done.

## 5. Backend contract gotchas

- Approval `entity_type` values: **`outbound_message`**, `proposal`,
  `price_change`, `plan_change`, `invoice` (NOT "message").
- Review-pending meetings are found via notifications
  (`kind=meeting_processed`, entity meeting) → `GET /meetings/{id}/review`
  (`meeting_status == "review_pending"`).
- Error envelope: `{"detail": string | pydantic-list}` — always show
  verbatim (ErrorMapper handles both).
- `GET /admin/users` needs manage_staff (org_admin) — that's why the
  assignment override picker is role-gated with an explanation.
- Rejecting an outbound_message triggers a server-side REDRAFT (note
  becomes the instruction) → a NEW approval appears. Expected, not a bug.
- 401 wipes the session EXCEPT on /auth/login and /auth/change-password.
- `session_id` on `/assistant/command` must match `^[A-Za-z0-9_-]{8,64}$`
  (a UUID hex with the dashes stripped is what the app sends) — anything
  else is a 422, not a silent ignore.
- `GET /assistant/history` returns **plain text turns only** — no actions,
  no pending approvals. A restored transcript therefore has no action cards
  and no live approval bars; that is the contract, not a gap to paper over.
- History is scoped to (org, **user**, session): a colleague passing the
  same `session_id` legitimately gets `[]`.
- Omitting `session_id` is the stateless contract and writes nothing. Do not
  "helpfully" mint one server-side.
- NEW (2026-07-22, F9): **`POST /meetings/{id}/review/confirm` is what starts the
  Planner** on a recorded meeting. It returns an additive `planning` boolean —
  true when a `plan_meeting` job was enqueued (i.e. at least one item was kept).
  The project/plan/approvals appear a model-call later, via the existing
  notification pipeline; the endpoint does NOT wait for them.
- NEW (2026-07-22, F9): `POST /meetings/upload` accepts an **optional**
  `project_id` form field. Omit it (the old contract) and the Planner resolves the
  project from the lead's live projects by asking the model; pass it when
  recording from a project home and the meeting is pinned to that project.
- NEW (2026-07-22, F9): `GET /meetings/{id}/review` returns **only extraction
  items**, never plan-owned tasks (`plan_version_added IS NULL`). Plan tasks are
  also created `pending_review` and also carry the meeting id, but they go live
  through `activate_plan`; the review gate must never offer them.
- NEW (2026-07-22, F22): **no contract change, but the data got more complete.**
  A to-do confirmed at the review gate is now ADOPTED by the plan instead of
  being duplicated, so the same row is reachable through BOTH
  `GET /action-items` and `GET /projects/{id}.tasks[]` — which is what
  `TasksRepository.myTasks()` already assumed when it unions the two lists **by
  id**. Practical effect for the app: those tasks now arrive `rich` (phase,
  priority, dependencies) where they previously came thin from `/action-items`
  only, and the duplicate row is gone. Older builds are unaffected.
- NEW (2026-07-22, F2): a message is `pending_approval` **and** may or may not have an
  `approvals` row — they are separate tables and the inbox is driven by the row.
  `POST /messages/{id}/approve` acts on the MESSAGE and works with or without one;
  the inbox route (`approvals/{id}/decide` → `_release_message`) drives the message
  from the other end. Both now resolve the approval, so a message decided either way
  leaves nothing pending. Only file an approval (`create_message(request_approval=True)`)
  when the inbox is the ONLY route to that draft — otherwise you create a redundant
  entry that outlives the user's action.
- NEW (2026-07-22, F22): a task confirmed at the review gate **can change
  assignee** when the plan activates, because adopted rows are now staffed by
  skill with the rest of the plan. The previous assignee is notified via the
  existing `plan_updated` "your changes" notification — do not treat that
  reassignment as a bug.

- NEW (2026-07-29, Phase 6): `GET /inbound/triage` rows carry `intent`,
  `change_type`, `matched_lead_id`, `matched_project_id`, `created_at`;
  `POST /inbound/{id}/resolve` accepts `intent` (422 unless it is an
  `InboundIntent`) and `project_id` (404 unless it is a project in your org);
  `GET /messages(/{id})` carries `sender_user_id`. All additive.
- NEW (2026-07-29): **`POST /inbound/{id}/resolve` accepts a `note` and never
  stores it.** Not a typo in the docs — read `workflow.py`: `body.note` is
  declared and never referenced. No screen offers a note box because of it.
- NEW (2026-07-29): **there is no confidence on an inbound message.** Docs 03 §9
  and doc 10 both promised one. `InboundMessage` has no column and
  `inbound_engine` never computes one. Do not build a UI that implies otherwise.
- NEW (2026-07-29): **`GET /messages` is org-wide and needs `send_messages`.**
  Both halves matter: ops roles get 403 (so they get triage only), and everyone
  else sees the whole org's outbound mail, which is why the app filters Mine/All
  client-side on `sender_user_id` instead of the server narrowing the response.
- NEW (2026-08-03, F28): an assistant `actions[]` entry may carry
  **`outcome: "needs_confirmation"`** with `question` and `candidates[]` — the tool is
  *unsure*, not broken, and the user is being asked. **`ok` is still `false` and `error`
  still holds the same text**, deliberately: the tool did not act, and an older app keeps
  rendering exactly what it rendered before. Only a newer app reads `outcome`. Additive on
  both sides.
- NEW (2026-08-03, F30): **approving a message with `[Name]`-style blanks is refused (422)**
  on BOTH routes — `POST /messages/{id}/approve` and `POST /approvals/{id}/decide`. Pass
  **`allow_blanks=true`** (query param on the first, body field on the second) to send it
  anyway. Absent = false = refuse, so an older client is protected rather than broken: it
  gets the refusal verbatim and cannot send blanks it was never shown. The refusal quotes
  the offending lines back.
- NEW (2026-08-03, F30): `GET /messages(/{id})` carries **`blanks[]`**, and an assistant
  `pending_approvals[]` entry carries `blanks[]` + a human `warning` + `preview_note`. The
  inline card's `body_preview` is now **1200** characters, not 300 — the placeholders that
  prompted F30 sat at 397 and 474, past the old cut, so the approver was shown a clean
  opening and asked to approve the rest unseen. All additive.
- NEW (2026-08-03, F28): `resolve_contact` **no longer returns an arbitrary contact** when
  the command names nobody and several contacts exist with **no primary marked** — it asks.
  A designated primary is still returned without a question. Anything calling an agent tool
  with no recipient hint should expect a question where it previously got row zero.
- NEW (2026-07-29): a message's `attachments` exist on the model but are **not
  serialised**. The dry-run `.eml` is still reachable — `message_service.py:280`
  logs the provider ref as the `sent` event's `detail`, i.e.
  `dry_run:orgs/<org>/outbox/<file>.eml`, which `GET /files/{path}` serves.

## 6. Known cosmetic warts (NOT fixed — carried to Phase 4 polish)

- Sticky `decideEvent` LiveData re-shows the last decide toast when Home is
  re-entered.
- Briefing keeps the last error text until the next resume/pull refresh
  (doesn't auto-clear the moment connectivity returns).
- ApprovalDetail for an already-decided approval shows an empty chip above
  the honest "no longer pending" error.
- Real logo files still pending from the user (placeholder amber "Y");
  Inter font not bundled; biometric quick unlock deferred.
- NEW (Phase 2): after a ContactSheet save reloads LeadDetail, the
  TabLayout indicator can show Overview while the content still renders the
  previously selected tab (currentTab survives; indicator doesn't).
- NEW (Phase 2): the lead-detail per-tab action bar buttons sit above the
  bottom nav; on the recorder/notes screens the bottom nav stays visible
  (harmless but a full-screen treatment would look better).
- NEW (Phase 3): assistant transcript is in-memory only (by design — tab
  switches keep it, process death clears it); commands are stateless
  server-side, so "send it" pronouns only resolve via the ContextBus chip
  or explicit names — a small hint in the UI would help.
- NEW (Phase 3): Open chip on a `message` entity lands on the honest
  "opens fully in a later phase" toast (no message screen yet).
- FIXED post-phase (2026-07-20, after user screenshots): reply-bubble text
  was INVISIBLE in dark mode (hardcoded light bubble + theme-following
  text color → white-on-white; now fixed dark-on-light pair) and action
  cards dumped RAW JSON when the backend string-previews big tool results
  (Pretty now re-parses JSON previews, omits broken ones, caps card
  bodies at 14 lines). Lesson: XML-dump testing reads text the eye
  cannot — screenshot-verify every new screen in BOTH themes.

## 6b. Phase 2 gotchas learned (do not relearn)

- **OpenRouter free models & vision**: a text-only model 404s on image
  input ("no endpoints support image input") → the app sees the backend's
  502 verbatim. Fixed CONFIG-ONLY in `.env` (flagged to the user):
  `OPENROUTER_MODEL_FAST=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
  (same nemotron family, vision-capable; old value kept in a comment).
  STRONG tier unchanged. If card scan 502s again, re-check the free-model
  roster via `GET https://openrouter.ai/api/v1/models` (filter
  `architecture.input_modalities` contains "image").
- `/meetings/upload` takes NO meeting_type (only lead_id, consent_confirmed,
  duration_seconds, title, file); meeting_type exists on /schedule and
  /notes only — the post-stop sheet therefore asks title only.
- Review-confirm contract is `{items:[{id,title,description,keep}]}` —
  assignee/due/skill are NOT part of it; anything not echoed back is
  cancelled server-side; id=null + keep=true creates a user-added OPEN item.
- `lead_service.change_state` returns early on same-state PATCH (does not
  clear suggested_state) — hence the client-side dismissal for "Keep as is".
- WorkManager survived an app crash: the upload enqueued right before an
  NPE ran to completion on next app start (same idempotency key). Fixed
  NPE: never call `getActivity()` after `onBackPressed()` pops the
  fragment — capture the activity reference first.
- uiautomator `dump` can fail with "could not get idle state" and silently
  leave a STALE ui.xml — always re-run the dump in the same command as the
  grep, and prefer `screencap` for ground truth.
- `adb push` to /sdcard then `run-as cp` fails (permission); push to
  `/data/local/tmp` instead. Git-Bash mangles `/sdcard` args — set
  `MSYS_NO_PATHCONV=1`.
- Laptop TTS (`System.Speech`) through speakers is a workable stand-in for
  a real meeting: Whisper's verbatim text was partly hallucinated from the
  faint audio, but the summary + extracted action items matched the spoken
  script exactly (4/4).

## 6c. Genericity — swept 2026-07-22 (F11/F6), completed 2026-08-03 (**F31 CLOSED**)

> ✅ **F31 IS FIXED (2026-08-03).** Everything the corrections below describe has been
> repaired, in the backend **and** the app, and — this is the part that matters — the project
> now has **automated guards** instead of a claim: `tests/test_genericity.py` (AST-parses
> every module and fails on an industry word in anything that reaches a model) and
> `scripts/check_hardcoded_strings.py` (Java literals, domain words and currency symbols
> outside resources). **Do not re-derive this section's history; read `FINDINGS.md` → F31 →
> "How F31 was fixed".**
>
> **The guard found three sites nobody had spotted, including two in `planning.py` that F31
> had explicitly certified clean.** That is the argument for a guard over a sweep: a sweep is
> a claim made once, a guard is a claim re-made on every run. **Nothing below should ever
> again be summarised as "genericity is done" — the correct sentence is "the guards are
> green", and that one is checkable.**

> ⚠️ **CORRECTION (2026-08-03). This section had been over-confident twice.** It first
> claimed the `knowledge_engine` cross-sell string was "the ONLY user-visible domain-worded
> string" — wrong by roughly forty sites. It then claimed the sweep was "done, with three
> deliberate exceptions" — **also wrong**, because the sweep classified sites as *prompt /
> user-visible string / tool name* and **had no category for branching logic**.
>
> A re-audit on 2026-08-03 (the user asked outright whether the system is generic) found
> **two live defects and one landmine**, all of them code that decides or writes based on a
> domain word:
> - `planner_engine._estimate_value` recognises only pricing units containing `student` or
>   `flat`, so a client priced *per seat / per licence* gets `value_estimate = None` — on
>   the **live LLM path**.
> - `inbound_engine._handle_scope_change` looks the rate up generically and then writes a
>   hardcoded `"unit": "per student"` into a **client-visible** amendment.
> - `document_engine.generate_text_artifact` hardcodes *"education-services company"* in a
>   live LLM system prompt. **Dead today (zero callers)** — but it lives in the file Phase
>   7.1 builds in.
>
> **Read `FINDINGS.md` → F31 before trusting the "done" framing below.** The three tiers
> that follow are accurate about what WAS swept; they are not a statement that nothing is
> left. **The lesson: a genericity audit must include a tier for logic, not just for text.**
>
> The original note: this section previously claimed the `knowledge_engine` cross-sell string
> was "the ONLY user-visible domain-worded string". That was wrong by roughly forty sites.
> What follows is the 2026-07-22 picture, including what was deliberately NOT changed and why.

**What "generic" means here, and the three tiers that actually matter:**

1. **LLM-facing text — the dangerous tier.** A domain word in a prompt does not just read
   oddly, it makes the model *write in that domain* whatever the client is. F4 proved this
   (a prompt saying "school" put "the school operates offices in Bengaluru…" into permanent
   org memory for an engineering firm). Swept 2026-07-22:
   - `communication_engine` drafting prompt — was *"from an education-services company to
     schools"*, now neutral **and** carries an explicit "never assume an industry" rule.
   - `inbound_engine` classification context — was `School: {name}`, now `Client:`.
   - Three `purpose=` strings in `sync_engine` that are interpolated into that drafting
     prompt (`"tell the school a visible task finished"` etc.).
   - `query_agent` and `scheduling_agent` system prompts, and the orchestrator's routing
     examples.
   **Rule for the future: grep prompts before shipping any new engine.**
2. **User-visible strings.** All three `resolvers.py` errors (the *"No school matching
   'Ekaghni' found"* seen in a real transcript), the onboarding brief's "School-side
   people:", `knowledge_engine`'s cross-sell copy, "school gone quiet", "Payment ladder
   exhausted — call the school", "Relationship owner books school meetings", the card-scan
   prompt's "(e.g. Principal)" and "school/company name".
3. **Agent tool surface.** Renamed with the user 2026-07-22: `get_school_details` →
   `get_client_details`, `add_school_note` → `add_client_note`, and the `school` parameter →
   `client` across 7 tools in 5 agents. **This was user-visible**: the app humanises the raw
   tool name (`LeadStates.label()` → `replace('_',' ')` + capitalise), so the chat rendered a
   card titled literally "Get school details". No app change was needed. All 12 tool
   *descriptions* were neutralised too.

**Seed data (F6).** `seed_demo.py`'s templates no longer say "support your students" or
"sessions inside the school, aligned with the academic calendar", and now use
`{client_name}`. **`school_name` is still supplied as an alias** by `intro_service` and
`proposal_service` — removing it would silently blank the variable in every template an org
has already saved.

**Three things deliberately NOT changed:**

- **API wire keys.** `/action-items`, `/demos` and `/followups` return `"school": <lead
  name>`, which the Android app maps via `@SerializedName("school")` → `leadName`. It is
  never rendered as a label, so it is an internal contract name, not a user-visible string.
  Changing it needs a coordinated app release for zero user benefit. Decided with the user
  2026-07-22.
- **Docstrings and comments** across `models/`, `engines/` and `api/` still say "school" in
  places. Internal only; churn without benefit.
- **Demo lead names** ("Delhi Public School", "Green Valley School") are legitimate sample
  data, not hardcoding.

**Two tests had pinned the OLD wording and went red during the sweep** — `test_assistant.py`
asserted the literal string `"No school matching"`, and dry-run W15 asserted
`"School-side people" in brief`. Both now assert the **property** (a not-found error that
leaks no id; a "-side people" heading) so the next genericity fix does not look like a
regression. **If you are about to assert on a user-facing string, assert what it must
achieve, not how it is phrased.**

**`strings.xml` is clean**: `grep -i` for school/student/principal/teacher/syllabus/pupil
returns nothing, re-verified 2026-08-03. **This sentence is exactly the trap** — it is true,
it was used twice to conclude "the app is clean", and it never was. Run
`python scripts/check_hardcoded_strings.py` instead; it reads the Java too.

> ⚠️ **But "the app is clean" does NOT follow, and was claimed here in error.** A wider pass
> the same day found **`ProjectDetailFragment.java:619`** —
> `role.setHint("Role at client (e.g. principal, procurement_head)")` — a **user-visible**
> domain hint hardcoded as a **Java literal**, which is exactly why a `strings.xml` grep
> could not see it. The app also hardcodes **`₹`** (`ProjectDetailFragment:203`,
> `ProjectsListFragment:174`) while the backend stores a real `currency` per project and
> pricing table, so a USD project renders as rupees. Both are now part of **F31**, which
> therefore needs an **app build**, not only a backend unfreeze.
>
> **The method lesson, which is the durable part: verify by behaviour, not by the one file
> the text is supposed to live in.** Nine user-visible literals are hardcoded in Java in
> total, bypassing the resources F14's copy pass established.

**A separate axis nobody had written down:** the system is domain-generic *in intent* but
neither **language-** nor **locale-**generic. English is assumed everywhere (every prompt,
`inbound_engine`'s stopword list, and the connector/fill-word lists added 2026-08-03), and
money is assumed Indian (`nlu.py:55-72` parses *lakh*/*crore*; the app hardcodes `₹`). Both
are reasonable scope decisions for the current market; they just need to be stated ones, so
they read as choices rather than oversights — and the currency one is worth separating,
because there the app is discarding data the backend already has.

## 6d. Phase 3 gotchas learned (do not relearn)

- **Doc-10 acceptance vs. reality**: the "create a lead… draft the
  proposal… send it" line predates the final agent tool surface — there
  is NO `create_lead` agent tool (tools: list_leads, get_client_details,
  add_client_note, create/get/edit proposal, emails, follow-ups, demos,
  action items — renamed from `*_school_*` on 2026-07-22, F11). Lead creation stays a tap path (NewLeadSheet); the rest
  of the conversation runs through the assistant. Do not "fix" this by
  adding a backend tool — frozen.
- **Loopback port 8000 can be stolen**: VS Code (user's session) held a
  port-forward bound specifically to `127.0.0.1:8000`, which WINS over
  uvicorn's `0.0.0.0:8000` for loopback traffic — `curl 127.0.0.1:8000`
  answered with a ComfyUI health JSON. Do NOT kill the user's process.
  **⚠️ The `PORT=8001` advice below is SUPERSEDED — 8001 was later taken too
  (§6g). Use `PORT=9010`, per §3, which is the current recipe.** The
  principle still stands: override the port with an env var, never edit
  `.env`, and map the phone with `adb reverse`. Historic wording:
  run the backend with `PORT=8001 python run.py` (env override, no .env
  edit) and map the phone with `adb reverse tcp:8000 tcp:8001` — the
  phone-side base_url (`http://127.0.0.1:8000` in prefs `yuvipep_env`,
  key `base_url`, pushed via /data/local/tmp + run-as cp) stays unchanged.
- Assistant contract: `actions[]` = `{tool, args, ok, result|error}` where
  `result` is a preview truncated at 800 chars (may arrive as a string —
  render generically, never assume a map). `pending_approvals[]` always
  carry `message_id` on this backend → approve = `POST /messages/{id}/
  approve` (needs send_messages), reject body `{reason}`.
- Agent tool results use bare `"id"`, not `proposal_id` — entity inference
  must fall back to tool-name words (create_proposal → proposal).
- `/assistant/command` is **stateless** — no conversation memory server-
  side. "It" only resolves through the context ids or explicit names.
- Proposal narrative embeds the commercials between
  `<!--PRICING_START-->…<!--PRICING_END-->`; strip for display and render
  `line_items` yourself. Upload-revision total check uses
  `f"{total:,.0f}"` (e.g. `59,000`) — a hand-made "edited" PDF must
  contain that exact grouped string (or the plain digits) to verify.
- Proposal statuses seen live: draft → (submit-review below threshold) →
  approved_internally; approve-send / assistant send → sent; sent hides
  all mutating buttons (backend refuses anyway with "already sent").
- `PdfRenderer` opens the cached file directly; on open failure DELETE the
  cache entry before retry (a half-written file would wedge the screen —
  FileRepository also writes via .part + rename for the same reason).
- Vivo SAF picker: the navigation drawer hamburger did not respond to
  taps in automation; pushed files only appear in "Recent" after a
  MEDIA_SCANNER_SCAN_FILE broadcast. BACK does not always close the
  picker — one blind tap selected a random user PDF and uploaded it (the
  backend's total-check refused it; nothing stored). Always re-dump and
  tap the file by name.
- The phone auto-rotated to landscape mid-run (uiautomator bounds
  suddenly >1260 wide): lock with `settings put system
  accelerometer_rotation 0`, restore to 1 after.
- Writing exotic separator chars (U+001F) into Java source via tooling
  kept getting mangled — use plain `"\n"` separators + flatten stored
  strings instead.
- **Semantic memory ("search_past_notes") is currently EMPTY**: the
  memory index (`memory_chunks`, 0 rows) is built with Gemini embeddings
  regardless of LLM_PROVIDER, and the free GEMINI_API_KEY is
  quota-exhausted (tested 2026-07-20: HTTP 429) — every note ingestion
  silently skips indexing (server logs "Memory search skipped"). Effect:
  "who is the science head?" → agent picks search_past_notes → [] → the
  free model gives up and asks for the client name instead of chaining
  `get_client_details` (which DOES answer it — verified: "what do we know
  about Green Valley School and who is the science head there?" →
  "The science head is Ms Iyer"). Remedies: fresh/paid Gemini key (quota
  resets daily) + a one-off backfill script over client_intelligence
  (script-only, no backend change — Phase-1 seeder pattern); a stronger
  chat model also chains tools instead of giving up.
- **OpenRouter :free models rate-limit under load**: seen live —
  "ResourceExhausted: Worker local total request limit reached (16/16)"
  → backend 502 → app shows it verbatim and restores the command text.
  Transient (a retry ~30s later succeeded). Demo risk: consider a paid
  OpenRouter key (or a second :free model as fallback) before showing
  the assistant to an audience.

## 6e. Phase 4 gotchas learned (do not relearn)

- **No single "rich my-tasks" endpoint exists.** The ActionItem table is
  exposed two ways with disjoint field sets: `GET /action-items` (thin —
  title/description/status/owner/lead-name/due/result_note/completed_at/
  created_at, **no** phase/priority/blocked/progress/assignment_reason/
  depends_on_ids/client_commitment_id) vs. `GET /projects/{id}.tasks[]`
  (rich — phase/priority/blocked/progress/assignment_reason/depends_on_ids,
  **no** description/result_note/completed_at/owner_name/project_id). No
  `GET /tasks/{id}` or `GET /action-items/{id}` exists either. `TaskDto`
  (core/net/dto) unifies both shapes with `@SerializedName` alternates;
  `TasksRepository.myTasks()` walks every project (`GET /projects` then
  per-project `GET /projects/{id}`), keeps this user's tasks (rich), then
  unions in whatever `/action-items?owner=me` didn't already surface
  (thin, project-less). `TaskDetailFragment` additionally backfills the
  narrative fields onto a rich task by re-querying `/action-items?
  owner=<assignee_id>` and matching by id — this works for ANY assignee,
  not just "me", since `manage_tasks` is granted to every role. Fine at
  demo/org scale (few projects); a real "my tasks, fully detailed"
  endpoint would be needed at scale — flagged to the user, not built
  (backend frozen).
- **No vendor-wait signal is exposed anywhere.** `external_wait` (set by
  `POST /tasks/{id}/vendor-promise`) is on the ActionItem model but
  neither API surface above returns it. My Tasks therefore has NO
  "waiting on vendor" group — showing an always-empty one would be a fake
  empty state; the app just doesn't claim to know.
- **Conflicts API doesn't expose its sources.** `GET /projects/{id}/
  conflicts` returns `id, description, status, raised_to_user_id,
  resolution_note` only — `source_a/source_a_type/source_b/source_b_type/
  held_plan_id` exist on the `Conflict` model but are not serialized. The
  "two source cards side by side" mock in 03 §6 isn't buildable from the
  wire contract; the resolver instead shows the full `description` prose
  (the planner writes conflicts as a narrative, so this reads fine) plus
  a resolution-note field and Resolve button.
- **Provenance on People rows is generic, not a field**: stakeholders
  have no `added_by`/`source` column exposed either — the "why" affordance
  is just `WhySheet` pointed at `entity_type="stakeholder"`, which works
  because `why_trace` is generic over any `(entity_type, entity_id)` with
  `AIDecision` rows. Zero new backend surface needed.
- **Team-tab "Add member" is gated to `MANAGE_STAFF`, not `MANAGE_TEAMS`**,
  even though `POST /projects/{id}/members` itself has no permission
  dependency server-side. The gate exists because the only way to search
  for a person to add is `GET /admin/users`, which needs `manage_staff`
  (org_admin only) — same reasoning as the Phase-1 assignment-override
  picker. `operations_lead` holds `manage_teams` but not `manage_staff`,
  so they see the honest "ask your org admin" explanation, not a picker
  that would 403.
- **ContextBus is deliberately NOT fed from Project/Task screens.**
  `/assistant/command`'s `CommandRequest` only has `lead_id`/`proposal_id`/
  `meeting_id` (01 §1.13, unchanged since Phase 3) — there is no
  `project_id`/`task_id` field, so anything sent would be silently
  dropped by pydantic. Showing an "About: X" chip that doesn't actually
  do anything would repeat the Phase-3 "nothing invisible" lesson in a
  new place; the assistant's context chip stays lead/proposal/meeting-only
  until the backend contract grows.
- **"Draft message" quick action is new wiring**: `POST /messages/draft`
  (workflow.py) existed since before Phase 3 but had no client — it's the
  proper "ask for a client message directly" path (still approval-gated).
  Phase 4's project-home quick action uses it with a contact picked from
  the project's lead; response is rendered honestly (held vs. drafted,
  verbatim body/status).
- Re-dumping the UI after a keyboard opens is still required every time
  (same Phase-3 lesson) — a `MaterialAlertDialogBuilder` with an
  `EditText` shifts its buttons upward by ~450px when the IME appears;
  tapping pre-keyboard coordinates hits nothing and the dialog just
  closes via the theme's outside-touch dismiss, which looks identical to
  a successful no-op unless you check the resulting state.
- **`RoleGate.has(role, X)` — X must be a permission constant, never a
  role constant.** Both are typed `String`, so `RoleGate.has(role,
  RoleGate.OPERATIONS_LEAD)` compiles and silently always returns
  `false` (it looks up `MATRIX.get("operations_lead")`, which is null —
  there's no permission by that name). Caught live when a role-gated
  "Shift phase" chip never appeared for an operations_lead account. Fix
  is a direct `RoleGate.OPERATIONS_LEAD.equals(tokenStore.getRole())`
  check when the gate is really "is this role", not "can this role do X".
- **TabLayout tabs must be re-selected after being re-added, or the
  indicator desyncs from the content.** Any fragment that (a) keeps a
  `currentTab` int field and (b) calls `binding.tabs.addTab(...)` fresh
  in `onViewCreated` (which happens every time the view is recreated,
  e.g. returning from a pushed screen via the back stack) will visually
  reset to tab 0 while `renderTab()` still renders whatever `currentTab`
  actually is — the strip and the content disagree. Fix: right after the
  `addTab` loop and *before* attaching the `OnTabSelectedListener` (so
  the restore doesn't itself trigger a redundant render), call
  `binding.tabs.getTabAt(currentTab).select()`. Found in
  `ProjectDetailFragment`, fixed there and retroactively in
  `LeadDetailFragment` (its Phase-2 instance of the same bug had only
  been documented as a "cosmetic wart," never fixed, until now).
- **Vendor-slip has a real, non-obvious backend side effect**: recording
  a slip (`POST /tasks/{id}/vendor-slip`) doesn't just update
  `external_wait` — it emits a `VENDOR_SLIP` progress event, and
  `sync_engine._on_vendor_slip` (Workflow 24) reacts by silently bumping
  the task's own `due_date` to match the new promised date *when the
  project has slack*, or escalating to the ops owner when the slip eats
  into it. This is correct, intentional product behaviour, not a bug —
  but it means a task's `due_date` can change from an action that never
  looks like it touches dates, and the daily digest (a totally separate
  code path) is a reliable way to cross-check what the backend actually
  believes a due date is.
- **`adb reverse` mappings do not survive indefinitely** — one dropped
  silently mid-session (no USB event visible, just started failing),
  and the app correctly showed "You're offline — showing your last known
  session" even though the backend process was healthy the whole time.
  Re-run `adb reverse tcp:8000 tcp:8000` (or whatever port) at the start
  of any new testing session, and again if the offline banner appears
  unexpectedly mid-session — it's usually the tunnel, not the backend.

## 6f. Phase 5 gotchas learned (do not relearn)

- **Demo invites never create `approvals` rows.** Booking, rescheduling
  and cancelling a demo draft a `demo_invite` `outbound_message` with
  `status='pending_approval'` — but `GET /approvals` (approvals table)
  doesn't know about them, so the Approvals inbox and Waiting-on-you
  feed can't show them. Today they're only actionable when the
  assistant returns them in `pending_approvals[]`, or via
  `POST /messages/{id}/approve` directly. The Phase-6 message center is
  the natural surfacing place — don't forget these when building it.
- **The calendar integration is LIVE even when EMAIL_MODE=dry_run** —
  they're separate settings. Demo booking calls
  `calendar_service.create_event` immediately (no approval gate on the
  org-calendar event, only on the client-facing invite email), so this
  session's bookings likely created REAL Google Calendar events.
  Flagged to the user; delete from the calendar by hand if unwanted.
- **`GET /admin/demo-teams` needs auth only** (get_org_context, no
  permission) — every role can fill the team picker; only team WRITES
  need manage_teams.
- **`POST /demos` response carries three honesty fields** —
  `invite_message_id` (invite drafted), `invite_note` ("No contact
  email on the lead — no invite drafted"), `warning` (team clash).
  Render all three; never claim an invite exists when the id is null.
- **VoiceEditText owns its right edge** — in uiautomator flows tap text
  fields on the LEFT side; a tap near the end drawable starts dictation
  instead of focusing the field.
- **SpeechRecognizer finalises on short pauses** — a slow TTS voice
  (rate −2) gets cut mid-sentence; rate 0…−1 and starting speech <1s
  after `startListening` works. Laptop-TTS-through-speakers is a usable
  stand-in but garbles entity names ("team Alpha"→"Gmail") — treat
  entity-heavy voice tests as pipeline tests, not accuracy tests.
- `TextInputEditText` has NO 4-arg constructor (3-arg max), and
  `colorPrimary` is not in `com.google.android.material.R.attr` — use
  `androidx.appcompat.R.attr.colorPrimary` with `MaterialColors`.
- `registerForActivityResult` in `onViewCreated` is fine (before
  STARTED); it's what the assistant's mic-permission launcher uses.
- **Message-level reject (`POST /messages/{id}/reject`) does NOT
  redraft** — the reject-triggers-redraft behaviour documented in §5
  belongs to the approvals-table decide path only.
- **Weekly-report skips even after a very active week**: Nexora had two
  phase-shift waves, a decline, a vendor slip etc. within 24h, yet
  `GET /weekly-report` returned `skipped: "nothing happened this week /
  on hold"`. The report evidently counts a narrower event scope (likely
  client-visible progress only). Backend behaviour, not an app bug —
  don't chase it as one; ask the user before changing it (frozen).
- **Copy nit (app, unfixed)**: `project_team_no_permission` says "ask
  your operations lead or org admin" — awkward when the viewer IS the
  operations lead (the gate is really manage_staff/org_admin because of
  the /admin/users search dependency, §6e). Reword during polish.
- **Assistant Open-chips are limited by tool result shapes**: NO agent
  tool result currently carries a `lead_id`/`project_id` key, and most
  return bare `"id"` with tool names that don't contain a known entity
  word (`get_client_details` → "client", which is still not "lead" or
  "project"), so many cards can't offer
  Open. Fixing properly means touching agent tool outputs (backend,
  frozen — ask the user).

## 6g. FINDINGS-fix gotchas learned 2026-07-22 (do not relearn)

**Engine / design**

- **Plan tasks and extraction items share `meeting_id` and both start
  `pending_review`.** `create_plan_version` sets `meeting_id = trigger_ref` for
  `first_meeting`/`new_meeting` triggers, and its tasks stay `pending_review`
  until `activate_plan`. The meeting review gate selected on exactly those two
  columns, so a plan needing approval would have leaked its tasks into the review
  gate — where confirming flips them open behind activation's back (no staffing,
  no dependency wiring) or cancels them as "not echoed back". This was a **latent
  bug on the notes path too**, invisible only because that plan happened to
  auto-activate. Guard: `plan_version_added IS NULL`
  (`app/api/meetings.py::_review_items_query`).
- **A recording carries no project id**, so before F9 every recording looked like a
  FIRST meeting and a second one would fork a duplicate project.
  `planner_engine._resolve_meeting_project` now decides — and the decision is
  **always the model's**, even when the lead has exactly one live project, because
  "another meeting on the ongoing work" and "a new engagement with an old client"
  are indistinguishable from a row count. **The first version of this rule was
  wrong and `dryrun_workflows.py` caught it** (W30 went red: a genuinely new
  engagement with an existing client got hijacked into a merge). The stub provider
  now explicitly returns None rather than guessing, which also keeps the dry-run
  deterministic. `planning.match_message_project` gained a `source_kind` arg and an
  explicit "a fresh engagement with an existing client is new work" instruction.
- **A prompt instruction is not a fence.** The free model was told twice, in
  capitals, never to emit a near-duplicate of a human-confirmed to-do — and did it
  anyway, live ("Provide safety compliance documentation" + "Prepare safety
  compliance documentation"). Where a rule must hold, back it with deterministic
  code: `planner_engine._drop_duplicates_of_confirmed` keeps, per confirmed to-do,
  only the closest model task. Threshold 0.7 on significant-token overlap, verb
  **kept** — "schedule the demo" vs "confirm the demo" scores 0.67 and must NOT
  merge; "arrange live demonstration" (preparation) vs "deliver live demonstration"
  (delivery) is decomposition, not duplication. Unit-test both directions.
- **Do not let the model see a prompt line it can copy into a field.** Formatting
  confirmed to-dos as `- title (due 2026-07-24) — description` produced task titles
  reading *"Send the proposal (due 2026-07-24) — Provide a training proposal…"*.
  Fixed by giving each field its own labelled line (`planning.agreed_block`) plus an
  explicit "the due date goes in the due_date field, not the title".

- **A green suite proves the scope you tested, not the property you wanted.** F22 (the
  regression this session shipped) hid behind 50/50 pytest, 43/43 dryrun and a 22/22
  live script because "no duplicates" was asserted over `project["tasks"]` — the one
  collection the new code produces — while the duplicate lived *between* the plan and
  the project-less review-gate rows. When the property is "this work appears once **for
  the user**", assert it over everything the user would see for that lead (query by
  `lead_id`, no other filter). One human conversation found in minutes what twelve hours
  of green suites did not.

- **Plan tasks ADOPT the meeting's already-open rows** (F22, 2026-07-22). A to-do the
  human confirmed at the review gate and the Planner's carry of it are one piece of
  work; before this both were written as rows. `create_plan_version` now looks for an
  open row from the same meeting that no plan owns (`meeting_id == trigger_ref`,
  `plan_version_added IS NULL`) and updates it in place — keeping its **id**, the
  human's **title** and their **due_date**, adding phase/skill/priority/dependencies.
  One lookup covers BOTH entry points, because the review-gate-off path
  (`pipelines.py:194-205`) produces structurally identical rows. Matching uses
  `_adoption_match` at the **same 0.7 threshold and same `_title_similarity`** as
  `_drop_duplicates_of_confirmed`, so the two fences agree by construction; each row
  can be claimed only once.
- **`activate_plan` staffs two statuses now.** It selected only `PENDING_REVIEW`, so
  adopted rows (already `open` — a person made them live) would never have been
  staffed. It spans `PENDING_REVIEW` + `OPEN` for its own version, flips only the
  pending ones open, and notifies the **previous** assignee when a re-staffed task
  moves away. `assign_task` has no already-assigned guard, so widening that query
  DOES re-assign — that is deliberate (agreed with the user) but it is why the
  "moved away" notification exists.
- **A prompt instruction is not a fence — third confirmed instance.** After F9's
  duplicate-task case and F4's domain-word case, the STRONG-tier proposal rewrite was
  found applying a 10% discount it is explicitly forbidden to apply (**F23**), on all
  three models tested including the free one. `apply_narrative_edit` re-inserts the
  priced block so the TABLE is safe; the discounted figures survive in the PROSE.

**Harness / tooling**

- **The model bake-off harness lives in the 2026-07-22 scratchpad** (`bakeoff.py`,
  `bakeoff2.py`, `vision_probe.py`, `strong_probe.py`, `schema_check.py`,
  `cleanup_f22.py`). Vary models by **environment variable, never by editing `.env`** —
  pydantic-settings gives real env vars priority, so the live file stays untouched.
  **Never edit `app/**.py` while a comparison is running**: later configs would test
  different code than the baseline and the comparison silently becomes meaningless.
- **n=1 lies, in both directions.** `gemini-2.5-flash-lite` was written off on one
  `JSONDecodeError` then passed four reruns at 8.5s; `qwen3.5-flash` looked mediocre
  once and stalled 8 minutes the next time. Repeat before judging.
- **`verify_live_meeting_extraction.py` was writing to the LIVE database** — it set no
  `DATABASE_URL` (its docstring claimed "touches no database and writes nothing") so
  its `llm_usage` rows landed in `data/salesplatform.db`. Fixed 2026-07-22. **Any new
  verify script must set `DATABASE_URL` even if it "only" makes model calls** —
  every call writes a usage row.
- **`verify_generic_stakeholders.py` never exited** after printing its results: no
  `engine.dispose()`, so non-daemon aiosqlite threads kept the process alive. Presented
  as an 11-minute hang; it had actually finished in seconds. Fixed with the same
  try/finally the other scripts use — now 4.1s, exit 0.
- **Do not pipe a long-running script through `Select-Object`/`grep`/`tail`** — the
  pipeline buffers and you see NOTHING until the process exits, which is exactly what
  disguised the hang above. Redirect to a file and read the file. (Already in §6g; it
  bit again.)
- **Orphaned backends survive sessions.** The simulation's `run.py` from the
  previous day was still running against the live DB with live SMTP — a second
  scheduler. Always check first:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`. A `pkill -f run.py`
  from Git-Bash did **not** kill it (the replacement then failed to bind :8010 and
  the STALE backend kept serving, so a device test silently ran against old code —
  check `Platform ready` in the new log, not just `/health`).
- **Both :8000 and :8001 can be taken.** ComfyUI held both this session. Any free
  port works — `PORT=8010 python run.py` + `adb reverse tcp:8000 tcp:8010`; the
  phone-side pref stays `http://127.0.0.1:8000`.
- **`uiautomator dump` silently serves a STALE tree** (already in §6b) — it bit
  again and made a running recorder look like it had never started. Always
  `adb shell rm -f /sdcard/ui.xml` before dumping and fail loudly when the dump
  contains no `<node`. The scratchpad helper does both now.
- **`asyncio.run(main())` in a verify script never exits if it raises** — aiosqlite's
  threads are non-daemon, so a failed run keeps a lock on its own DB file and the
  next run dies with `PermissionError [WinError 32]`. Wrap in try/finally with
  `await engine.dispose()` (conftest already does this for tests).
- **`JobRecord`'s column is `type`, not `job_type`.**
- **Don't redirect two background runs to the same log file**, and remember
  `python -u … | grep | tail` shows nothing until the process exits — write to a
  file and tail it instead.
- **Laptop-TTS-through-speakers is a good meeting stand-in**: four recordings, all
  `language=en`, confidence 0.83–0.86, transcripts near-verbatim. **F5 did not
  reproduce** — speech started ~3 s after tapping record rather than after a long
  silent lead-in, which supports F5's "trim leading silence" fix candidate over the
  `language="en"` one.
- **Gemini embeddings now 429 "prepayment credits are depleted"** (was quota
  exhaustion, §6d) — the memory index still builds nothing. Needs a user decision.

## 6h. Phase 6 gotchas learned 2026-07-29 (do not relearn)

> ⚠️ **CORRECTION (2026-07-29, same day): this section originally read as a lesson about
> prompt hygiene. That framing was too kind to the code.** The user pointed out that a real
> salesperson will type *"draft an email to X at Y"* and the AI must cope — labelling fields
> is not their job. The deeper defect is that **the assistant's person-lookup is brittle and
> fails instead of asking** (`resolvers.py:142` matches one-directionally). Phase 6's
> labelled-line prompt is a **workaround**, not a fix: it repaired one app-generated command
> and nothing a human types into the Jarvis tab. That became **FINDING F28**, whose five
> fixes opened Phase 7 and which is **FIXED as of 2026-08-03** — the labelled-line prompt
> below has since been reverted to natural phrasing, and that revert was the acceptance
> test. Read F28 and §6i before treating the story below as settled: the *observations* are
> accurate, the original conclusion was too narrow, and the fix it describes is now history.

**The reply route took THREE tries on the device, and unit tests would have caught none
of them.** The command the app pre-fills for the assistant is a prompt, and prompts fail
in ways a green suite cannot see. Each failure and its fix:

1. **"Reply to `<email address>`"** → the email agent's `draft_custom_email` resolves a
   recipient by **name**, not address. It failed with *"No contact matching 'Siva'"* — the
   model had substituted the signed-in user. **Fix:** look the client up first and match
   `from_address` back to a contact, then name that person. This also fixed the context
   chip, which had been reading a useless *"About: Lead"*.
2. **"Write a reply to X at Y"** → the router sent it to the **proposal agent**, which
   answered *in the chat*. It read beautifully and created nothing: prose in a bubble is
   not a reply the client ever receives. **Fix:** say *"Draft an email"* — the router picks
   the agent from the words.
3. **"…to NAME at CLIENT"** → the model passed the whole phrase `"NAME at CLIENT"` as the
   contact parameter and the lookup failed again. **Fix:** one labelled line per value
   (`Recipient:` / `Client:` / `Their question:`) — which is **§6g's lesson exactly**
   ("do not let the model see a prompt line it can copy into a field"), rediscovered on
   the app side. It is not only about prompts *inside* the backend.

**Every one of these looked like a working feature until it ran on the phone.** The
suites, the dry-run and a 17/17 live script were all green throughout.

**And note what tries 1 and 3 really prove** (this is F28, not a prompt lesson): the
assistant was handed a perfectly reasonable human phrase and answered with a lookup error
instead of a question — even though its own error message *listed the right person*. Fixing
the sentence hid that. Fixing the resolver is Phase 7 §7.0.

**Other Phase 6 lessons**

- **Colour names outlive their first meaning.** `lead_execution` is amber and
  `lead_active` is green. Mapping message statuses by *name* put a green dot on
  "Pending approval" and an amber one on "Sent" — backwards to anyone reading it.
  Map by what the colour must *say* on this screen.
- **Do not slice a timestamp string to get a time.** The backend stores naive UTC, so
  `iso.substring(11,16)` printed *08:24* to a phone whose clock said *13:54*. A delivery
  trace that disagrees with the wall clock reads like the wrong message. `Times`
  now has `dateTimeLabel()`, which converts to the reader's own zone.
- **A chip must not credit a human's correction to the AI.** The intent chip read
  *"AI: Scheduling"* immediately after a person set it by hand — the payload cannot say
  who set an intent, so the chip now just states the classification and only the picker
  talks about whose reading it is.
- **Role-gate the whole path, not just the screen.** An ops agent legitimately reaches
  triage (that endpoint needs no permission) but cannot create an outbound message, so a
  Reply button would have led them into a 403. Hidden — and the message centre half is
  hidden for them too, tab strip and all.
- **`adb shell input text` splits on spaces** — escape them as `%s` — and its taps land
  by absolute coordinate, so re-dump between fields: the soft keyboard moves everything.
  `input keycombination 113 29` (Ctrl+A) then keyevent 67 is the reliable way to clear a
  field; repeated backspaces leave debris when the cursor is not where you assume.
- **A `-Unique` filter on a UI dump hides duplicates that matter.** Two cards both showing
  "Client identified" looked like one until the raw XML was counted. Count nodes, don't
  eyeball a de-duplicated text list.

## 6i. Phase 7 §7.0 / F28 + F29/F30 gotchas learned 2026-08-03 (do not relearn)

- **Order the ladder, don't union it.** Matching stages must be tried strongest-first with
  the **first productive stage winning**, not all at once. Union-style matching turns a
  precise command into a needless question: "email Ravi Kumar about the demo" matches
  *Ravi Kumar* exactly as a whole name, but also half-matches a colleague *Kumar Sethi* on
  loose word overlap. Precision is a stage-ordering property.
- **Word-bound the reverse match.** `name in hint` as a plain substring finds the stored
  name "Ann" inside "announcement". The stage that reads a name out of a sentence must
  compare **runs of words**, not characters.
- **A "clean up the input first" step can destroy the answer.** Stripping the client's
  words from a contact hint is right *as a fallback* and wrong *as a pre-step*: a contact
  called "Mrs. Nair" at "Nair Industries" loses their name to the strip. Rule of thumb —
  a normalisation that can only ever be applied is a risk; one that runs only after the
  faithful attempt failed is safe. And when it resolves an ambiguity, constrain it to
  **narrowing**: it may pick one of the existing candidates, never introduce a new one.
- **Overlapping fixes hide each other from the tests — this bit again.** The first version
  of `test_assistant_resolvers.py` passed with `name_in_hint` (the actual F28 case) deleted,
  because `token_overlap` and the fix-2 fallback covered every fixture. Green suite, absent
  fix. The cure is a **falsification matrix**: disable each fix one at a time and require a
  red run for each, and write at least one fixture that only that fix can satisfy. A
  scratchpad harness (`falsify.py`) did this automatically and is worth rebuilding.
- **A model will announce work it did not do.** Given a needs-confirmation result the model
  opened with *"I drafted the email … ready for your one-tap approval"* and only then asked
  which person — with nothing drafted. Telling it not to is necessary but is a prompt, not a
  fence (F9/F4/F23, fourth instance): the **card** must state the truth itself, which is why
  the question card says "Nothing has been drafted or sent yet" in its own layout.
- **Subclass an existing exception when adding a new outcome.** `NeedsConfirmationError`
  extends `ValidationFailedError`, so it keeps the same HTTP status and every existing
  `except ValidationFailedError` still catches it. New behaviour, zero blast radius.
- **Keep `ok:false` when the tool did not act.** It is tempting to invent a third truth
  value; leaving `ok` false and *adding* `outcome` means an older APK degrades to exactly
  its previous behaviour instead of showing a success that never happened.
- **A "clean up the input first" step and a "show less" step are the same bug in two
  places** (F30). The approval card sliced `body_preview` to 300 characters because that
  reads nicely; the blanks it was meant to guard against sat at 397 and 474. **A gate that
  hides part of what it is gating is not a gate** — if a screen asks for a decision, it owes
  the reader everything the decision covers, or an explicit line saying it does not.
- **Fence every route into the same effect, not the one you found the bug on.** A message
  can be released two ways (§5), so fencing only `approve_message` would have moved F30
  rather than fixed it. Check `bundled_entities` as well, or a clean draft carries a dirty
  one out with it.
- **Refuse before you mutate.** The inbox fence runs at the top of `approval_engine.decide`,
  ahead of any state change, so a refusal leaves the approval genuinely undecided and still
  actionable. Raising it deeper, from `_apply_approved`, would have left an approval marked
  approved with nothing released.
- **A detector's precision needs its own test.** A fence that blocks legitimate sends is
  worse than the bug it stops, so `[see attached]` and `[Rs 59,000]` have a test asserting
  they pass, and the falsification matrix includes an entry that makes the detector
  over-match and requires *that* test to go red.
- **Only a live model can tell you about false positives.** The unit tests prove the
  detector on strings you chose; the live script checks it against emails the real model
  actually wrote. Different question, and the one that would have embarrassed us.
- **A verify/scratchpad script that raises leaves a live python.exe holding the DB.** §6g
  already recorded this and it bit again, this time in a *scratchpad seeding* script rather
  than a verify one: the failed first run was still alive an hour later, holding
  `salesplatform.db`. Any script touching the DB needs the `try/finally` +
  `await engine.dispose()`, scratchpad or not — and the Step-0 orphan check catches it.
- **`adb shell input` taps and the soft keyboard** — §6h said re-dump between fields, and
  it bit again anyway: the send button sits at y≈1355 with the keyboard up and y≈2284 with
  it down, and a tap at the wrong one silently does nothing. Re-dump after *every* keyboard
  state change, not just between fields.
- **`bc` does not exist in this Git-Bash.** Compute tap centres in the shell you are already
  using, or read the bounds and do the arithmetic yourself.
- **Git-Bash mangles on-device paths** — `adb pull /sdcard/x.png` became
  `C:/Program Files/Git/sdcard/x.png`. `MSYS_NO_PATHCONV=1` fixes the device side, but the
  **destination** must then be a real Windows path (`C:\...`), not a `/c/...` one.

## 6j. F31 / genericity gotchas learned 2026-08-03 (do not relearn)

- **A guard beats a sweep, and the difference is measurable.** The F11 sweep was careful and
  still wrong three times. The guard written to prevent the *fourth* recurrence found three
  *existing* defects within minutes of first running — including two in `planning.py` that
  F31 had explicitly certified as "already generic … with no domain word at all". If a
  property matters, encode it as a check; a claim in a doc decays, a check does not.
- **Grep the artefact, miss the defect. Parse the artefact, find it.** Every one of the three
  under-counts came from inspecting the file the text *should* live in: `strings.xml` for a
  Java literal, the model column for a wire field, the regex branch for a prompt. The guard
  is an AST walk precisely so it can honour the deliberate exemptions (docstrings, comments,
  the four `"school"` wire keys) that a grep has to either ignore or drown in.
- **A falsification matrix finds blind spots in the GUARD, not just gaps in the fixes.** It
  reported "still green" three times, and each time the fix was fine and the *check* was
  blind: tool descriptions inside a `parameters={...}` dict, and prompts held in a variable
  (`system=_ROUTER_PROMPT`, `json_schema=schema`) rather than inline. A guard you have not
  tried to fool is a guard you do not know the reach of.
- **Bound the reference-following, or data flow masquerades as prompt text.** Resolving a
  name one level reaches the prompt held in a constant. Resolving transitively reported
  `'syllabus_change'` as model-facing because a comprehension filtering on it fed a variable
  that fed a message body — when only the filtered *details* ever reach the model.
- **Check the response, not the column.** `Project.currency` existed and was populated, and
  `_project_dict` had never serialised it. "The backend already stores it" and "the app
  receives it" are different claims and F31 conflated them.
- **Order matters in a cue list.** A real seeded pricing unit reads `"flat per bootcamp"` and
  contains both "flat" and "per". Test flat first or every flat line silently starts scaling.
- **When you remove a domain word from a match, widen rather than narrow.** Dropping
  `or "student" in unit` from the amendment's rate lookup would have *lost* matches; the
  replacement falls back to the first priced line, which is a strict superset of the old test.
- **Rename a model-facing key by adding, not switching.** `quantity_delta` / `content_change`
  ship with both readers still accepting `students_delta` / `syllabus_change`, so a model
  reply or a stored point written against the old vocabulary routes exactly as before.
- **Assert the property, not the phrasing** (§6c already said this; it applied again). Two
  suites pinned the old key names. They now accept either, so the *next* rename does not look
  like a regression.
- **A detector needs its own precision suite.** `check_hardcoded_strings.py` first flagged
  `setText("recommend".equals(stage) ? … )` — a wire value in a ternary, not copy. Its
  `--self-test` now pins ten cases, and the falsification matrix includes an entry that makes
  the detector over-match and requires *that* to go red.
- **Write the fixtures from the real source, not from memory.** Two cases in that precision
  suite were wrong because I typed `"\\u2039"` where the file actually contains `"‹"`.
- **PowerShell here-strings mangle a Python `-c` payload** (§6i's Git-Bash warning, other
  shell). Put the script in a file under the scratchpad and run it.

## 7. Working principles (agreed with the user — non-negotiable)

1. The AI/system does the work; humans only approve or edit.
2. Everything generic — no domain hardcoding anywhere.
3. Nothing invisible: honest errors, honest empty states, no fake success.
3b. **A short or ambiguous command is the AI's problem to solve, not the user's problem to
   avoid** (user, 2026-07-29). Sales leads and agents type tersely about anything. The
   assistant either resolves it and proceeds, or states its understanding and asks one
   clarifying question — *"my understanding is X, shall I proceed?"*. **A lookup error is
   not an acceptable third option, and neither is silently guessing** on anything
   client-visible. Was broken and tracked as **F28**; **fixed 2026-08-03** (Phase 7 §7.0).
   It stays a principle, not a closed ticket: every new agent tool inherits it, so a tool
   that can fail to find something must raise `NeedsConfirmationError` with candidates
   rather than a bare `NotFoundError`.
4. Verify end-to-end against the real backend before calling anything done;
   report with total honesty (including what was NOT done).
5. Backend is frozen **unless the user unfreezes it for a named piece of
   work** (as they did on 2026-07-21 for assistant conversation memory).
   Config-only changes (.env, env vars) are acceptable when unavoidable —
   flag them to the user every time. When it IS unfrozen: keep the existing
   contract back-compatible, re-run pytest + dryrun + verify_gap_endpoints,
   add a live verify script, and prove any schema change is additive against
   a COPY of `data/salesplatform.db` before it touches the real one.
6. Ask the user for credentials/assets per the doc-10 table (mic session at
   Phase 5; Firebase `google-services.json` + service-account key at
   Phase 9; keystore at Phase 9).  *(Renumbered 2026-07-22 when the Inbox
   became Phase 6 — see §8-pre5.)*

## 8-pre11. State — READ THIS FIRST (2026-08-25, audit + fix session)

> **§8-pre11 is the current state. §8-pre10 below is history** — still right about
> the demo and the environment, wrong about the finding counts and about
> idempotency. `FINDINGS.md`'s status table wins over any prose anywhere,
> including here.

### What this session was

An end-to-end audit of the product — the Android app and every backend engine —
run by **reproducing** each claim rather than reading about it, followed by four
fixes. Three things it found are worth a newcomer's attention before anything
else, because each one had a plausible, confidently-written, **wrong** account
of it in these documents.

### 1 · One clock (F65, and F52 with it)

Instants are stored in **UTC**. Every *date judgement* now runs in the
**organisation's** timezone via `app/core/clock.py` — `clock.today(tz)`,
`clock.local_date(instant, tz)`. Storing local time instead was considered and
rejected on the numbers: 75 `DateTime` columns, 148 `utcnow()` sites, and a
naive-local column is byte-identical to an unconverted naive-UTC one, so a
half-finished migration would be invisible.

**25 call sites moved.** `tests/test_one_clock_guard.py` AST-bans bare
`.today()` / `.now()` / `.utcnow()` in `app/`, matching on the **attribute and
arity** — an earlier version keyed on the receiver's name and missed
`from datetime import date as _date` in `agents/base.py`, which was the very site
[F68] had added.

The app agrees now too: `MeResponse.org_timezone` (additive) →
`core/util/WorkDay.java`, which is where My Tasks' bucketing moved so it could be
tested at all.

**Scope, stated honestly:** the mix only bites when the instant's UTC date differs
from the reader's — UTC hour ≥ 18:30 for IST. On the live database that was
**1 row in 29**, which is why Jarvis answered "what's due today" correctly and
why this looked intermittent for weeks.

### 2 · The `Idempotency-Key` header is inert — the app's docs promised otherwise

**No backend route reads any header.** `01_BACKEND_CONTRACT.md` used to state
that `idempotency_records` "guarantees a retry never duplicates a send or a
task"; it does not, and that sentence cost a reviewer a wrong conclusion in this
very session. It is corrected there, with a table of what actually protects each
retryable path. In short: message creation is keyed **server-side**; a retried
meeting upload is refused **422** because the consent record is single-use; a
replayed approval decide is refused **409**; everything else duplicates.

### 3 · `auto_approve` could send an unfinished draft with nobody's name on it

`_refuse_unfinished_drafts` (the F30/F47 placeholder fence) was reachable only
from `decide()`. An `auto_approve` rule released the message without it, and
built its `Approval` with no `requested_from_user_id` — so
`outbound_messages.approved_by`, the column Roles §2 calls *"the proof"*, was
**NULL**. Both fixed: one shared `_unfinished_draft_reason`, and a draft with
blanks now becomes an ordinary **pending** approval naming why, rather than
being released or stranded.

### Also fixed

- **RoleGate 19 → 20** (`confirm_assignments`), and `HomeFragment` no longer
  offers the assignment-batch card to a role the server will refuse. Guarded by
  `RoleGateTest`, which diffs against a **generated** matrix.
- **A refused meeting upload no longer leaves the audio on disk.** `save_bytes`
  ran before the consent check, so every refusal left real client audio that
  `retention_service` — which sweeps by walking `Meeting` rows — could never
  reach.
- **F59 closed, and it was never a product defect.** See its row.
- **F56 measured, and its fix does not work.** `verify_live_commitments.py` run
  live: **3/6**, register **4 → 4** across a second meeting. The 2026-08-05
  prompt change is genuinely in `planning.py:713` and the model still omits the
  commitments; the anti-duplication half ([F42]'s interaction) does hold. The row
  had carried a ✅ for twenty days while its own text said OPEN.

### The Android app has tests now

`./gradlew testOrgDebugUnitTest --offline` — **38, headless, no emulator.**
`ContractTest` parses 17 fixtures captured from a live seeded backend with the
app's own DTOs; it found on its first run that `GET /action-items` omits
`priority` and `blocked`, which My Tasks reads. `src/androidTest` is **still
empty** — UI, recorder and WorkManager remain manual.

### Counts, measured 2026-08-25

**pytest 335** · **Vitest 630** · **Android JVM 38** · `check_docs_in_sync` exit 0
· `test_genericity` 8 · `check_hardcoded_strings` **exit 0** (it used to fail
with 2 Java findings; both fixed — but note it scans a path *outside* this repo
and prints `[SKIP]` on a machine without the Android checkout).

### Still open — and what each one needs

| | Needs |
|---|---|
| **F35** IMAP | Your policy decision. `INBOUND_EMAIL_MODE=off` and must stay off. |
| **F54** complaint → incident | Your ruling. `Incident(` still has one construction site, in the inbound path only. |
| **F67** proposal not linked to project | A fix. Jarvis is the app's *only* proposal path, and a ₹2,00,000 accepted proposal yields a **₹0 invoice**. |
| **F58** notification routing | Five entity types dead-end because the features behind them have no screen anywhere. |
| **F56** commitments on merge | **A real fix — the 2026-08-05 one does not work.** Run live 2026-08-25: `verify_live_commitments.py` **3/6**, register **4 → 4**. The prompt now asks for new commitments and the model still omits them; its anti-duplication half holds. |

Beyond the findings list, the audit also recorded backend items with no client at
all (invoices, incidents, playbook suggestions) and deployment gaps (public
`/docs`, no login rate limiting, CORS `*` with credentials). Those are in the
assistant's project memory rather than here, because they are decisions for the
owner rather than defects against a spec.

---

## 8-pre10. State — 2026-08-06 evening (SUPERSEDED by §8-pre11, kept for history)

> **§8-pre10 was the current state until 2026-08-25.** Its finding counts
> ("F1–F63, 2 open") are **superseded** — see §8-pre11. It remains correct about
> the demo, the database and the environment. §8-pre9 below is older still.
> `FINDINGS.md`'s status table wins over any prose anywhere, including here.

### The one-paragraph version

Round 7 is **CLOSED**. Its simulation database was **deliberately wiped** (backup:
`data/_backup_round7_evidence_20260806-101259/`) to build a **datacentre demo** for the owner's
manager. ~~**60 findings F1–F63: 55 fixed, 2 open** (**F35** needs an IMAP policy decision,
**F59** is a pre-existing live-script regression).~~ **← every figure in that sentence is
superseded; see §8-pre11.** The findings run to **F69**, four are open (F35, F54, F56, F67), and
F59 turned out not to be a product defect at all. The app is rebuilt and installed. Email and
calendar are **LIVE**.

### Where things are now

| | |
|---|---|
| Current work | `Workflow_simulation/Workflow2/` — datacentre demo: 3 recordings + `DEMO_WALKTHROUGH.md` |
| Round 7 | `Workflow_simulation/Workflow1/` — **history**, and its runbook says so at the top |
| Findings | `FINDINGS.md` — the authority, current |
| Backend | `PORT=9010`, started from `Complete_Project`, `Platform ready` |
| `adb reverse` | `tcp:8000 → tcp:9010` — **clears whenever the phone reconnects; this caused a "Network trouble" scare** |
| App | **`0.7.4-round7fixes`**, installed |
| Email | **`EMAIL_MODE=smtp` — LIVE.** Real mail leaves |
| Calendar | **`CALENDAR_MODE=google` — LIVE.** Real events |
| Inbound | **`INBOUND_EMAIL_MODE=off` — F35, keep it off** |
| Database | Wiped + reseeded for the demo: **13 logins + 45 skills KEPT**, catalogue REPLACED with datacentre programs/pricing/templates |

### What the demo build itself uncovered — F60–F63, all fixed

Three found by the owner using the app, one a regression of mine:

- **F60** — the card scanner crashed on Capture. **Mine**: an insertion anchored on a `@POST`
  line split `@Multipart` from its method. Compiled fine; Retrofit validates lazily, so it only
  died at the first call. **Never anchor an insertion on a line that may belong to an annotation
  block.**
- **F61** — a corrected proposal emailed the **old PDF and old body**, because idempotency
  returned the first draft untouched. [F38] one level up.
- **F62** — "tell me a brief about the project" had **no tool behind it**. Third instance of
  [F46]/[F57]'s pattern.
- **F63** — a demo the client asks to move **in a meeting** did not move; a task moved instead.
  Fourth instance of the F41/F54/F56 pattern: machinery wired to one entry point.

### ⚠ What is NOT verified

- **Very little has been tapped through on the device.** The APK is installed and smoke-checked
  (launches, signs in, live briefing), and **F52 is device-verified** (the briefing shows no empty
  "Due today:" header). Everything else is suites + falsification.
- **F63's model half is unproven.** The op is applied correctly (test-proven); whether the model
  *chooses* `reschedule_demo` over `redate` needs one live merge run. Note it is **merge-only** —
  a first meeting has no `ops` at all.
- **The three demo recordings have never been played into the phone.** Transcription quality and
  what the model extracts from them is unknown. Worth one dry run of `meeting1.py` first.
- **No recording asks to move a demo**, so F63 is not exercised by Workflow2 as written.

---

## 8-pre9. State — 2026-08-06, fixing phase (SUPERSEDED by §8-pre10, kept for history)

> ⛔ **HISTORY — do not act on this section.** It was current during the fixing phase and is now
> wrong about two things that matter: the database (since wiped for the demo) and the email mode
> (`dry_run` here, **`smtp` now**). **§8-pre10 above is the current state.**

### What happened

**Tranche 3 (2026-08-06)** fixed **F36, F38, F42(text), F48, F52, F53, F54, F55, F56, F58** — leaving only **F35** (needs an IMAP policy decision) and **F59** (pre-existing) open. `pytest` **182/182**. **F42 was investigated and largely REFUTED**; **F38 was fixed by inverting the card-scan flow** on the owner's decision (the scan proposes, the save decides), which dissolves it rather than patching it; **F56 is now live-verified 6/6** after two defects in my own harness were fixed. ⚠ Still **no device testing** and the APK is still not installed.

---

**Tranche 2 (2026-08-06)** fixed **F39, F40, F43, F44, F45, F46, F57**. Suites: `pytest` **163/163** (baseline 104), dryrun 43/43, gap 21/21, stakeholders 21/21, live genericity 15/15, live resolution 19/19, both guards unchanged. **Still no device testing and the APK is still not installed** — F39 in particular is compile-verified only, and the app has no test harness (`test/`, `androidTest/` are empty). **F40 changed 8 upload call sites** across tests and live scripts, which now capture consent first as the app does. **New finding F59**: `verify_live_assistant_context.py` is 4/6 and was 6/6 — **pre-existing**, isolated by reverting the new tools and reproducing the identical failures; that script is not in the standard suite list.

---

The backend was unfrozen for one named job — **"fixing phase tranche 1: Group 1 + Group 2 minus
F35/F54, plus F50"** — and that job is **complete**. **Backend RE-FROZEN.**

**Fixed & verified: F49, F47, F51, F50, F41.** **Half fixed: F55** (the `.first()` determinism
half; the contract half stays open). **Applied but NOT behaviourally verified: F56** (prompt +
guards are in; the live experiment hung in its own harness and was killed — see its entry).

**Both spec-check passes are now done.** The second (F50–F53, F57–F58) overturned nothing but
**split F51 three ways**, added a **fix-trap for F52**, made **F53 a dependency of F52**, and
corrected **F58's headline count**. All recorded in `FINDINGS.md` → *"Spec-check pass 2"*.

### Environment as left ⏹ **SUPERSEDED — see §8-pre10 for the live environment**

> **⛔ Three rows below are no longer true.** They were true at the end of tranche 2 and are
> kept as the record of that moment. **Do not configure anything from this table.**

| | |
|---|---|
| Backend | **RUNNING**, `PORT=9010`, restarted on the FIXED code, `Platform ready` in `…\scratchpad\backend_fixphase.log.err`, no errors |
| `adb reverse` | **SET** — `tcp:8000 → tcp:9010` (it cleared twice today; verify it) |
| Email | ⏹ **STALE.** Said `EMAIL_MODE=dry_run`. **It is `smtp` again** — restored for the datacentre demo, which needs real mail. **Live mail actually sends.** |
| Calendar / Inbound / WhatsApp | `google` / **`off` (F35 — do not re-enable)** / `dry_run` — all unchanged, and still true |
| App | **`0.7.4-round7fixes` — rebuilt and installed 2026-08-06** (replacing `0.7.3-f31`, with the owner's go-ahead). `adb install -r`, so `base_url` and the session survived |
| DB | ⏹ **STALE.** Said "untouched, every protected count re-verified". **The database was deliberately WIPED later the same day** at the owner's instruction, to give the datacentre demo a clean start — employees and skills kept, everything else fresh. Byte-copy at `data/_backup_round7_evidence_20260806-101259/salesplatform.db`. **The protected "do not approve" rows no longer exist.** |

### Suites — all green

`pytest` **139/139** (baseline 104; **+35 new tests**) · `dryrun_workflows` **43/43** ·
`verify_gap_endpoints` **21/21** · `verify_generic_stakeholders --stub` **21/21** ·
`verify_live_genericity` **15/15** · `verify_live_resolution` **19/19** ·
`tests/test_genericity.py` **8/8** · `check_hardcoded_strings` precision **11/11** with its
**2 known F37 literals** (unchanged from baseline — the Java edit introduced none).

### ⚠ What was NOT done — say this plainly

- **Barely any device testing.** The APK is now installed and smoke-checked (launches, signs in,
  pulls a live briefing), and **F52 is device-verified** by that briefing showing no empty
  "Due today:" header. Everything else is proven by suites and by **falsification** (removing
  each fix and watching its own test fail) — not by tapping through the app.
- **Still untapped on the device:** F39's recorder pause, F51's action chips, F53's Overdue
  bucket, F36's server chip, F48's wording, F58's notification routing, F38's card-scan flow.
- **F56's live experiment did not run.** `scripts/verify_live_commitments.py` exists and is the
  right test; it hung in the first meeting's plan generation with no DB writes for 26 minutes
  while a direct LLM probe answered in 4.6 s, so the fault is in that harness — most likely
  `review/confirm` enqueuing `plan_meeting` while the script also calls it directly.

### Suggested next steps

1. **Fix `verify_live_commitments.py`'s harness and run it** — that closes F56.
2. **Decide on the APK**: rebuilding replaces the build that produced Round 7's evidence.
3. ✅ **Tranche 2 RAN on 2026-08-06** — F39, F40, F43, F44, F45, F46, F57. What is left of that
   suggestion: **F52 + F53 must still ship as a pair**, and **F58** is still open (F43 is done,
   so the "both about conflicts being findable" pairing is now one-sided).
5. **Verify tranche 1 & 2 on the device** — nothing from either has been tapped on the phone,
   and the APK has not been installed, so **F39 and F51's chip half are compile-verified only**.
4. **Decisions still owed by the owner, blocking their findings:** F35's IMAP policy, F54's
   product question, and F42's spec self-contradiction.

---

## 8-pre8. State — 2026-08-03, Round 7 in progress

> ## ⛔ HISTORY — do not act on this section
> Superseded by §8-pre9, which is itself superseded by **§8-pre10 (the live state)**.
> The simulation it describes finished, the fixing phase it points to has run in full, and
> the database it describes has been wiped. Kept only for the Round 7 story.

### ⏸ A simulation is HALF-RUN and PAUSED. Do not start new work.

**Phase 7 §7.1 is NOT the next action.** The user asked for a full end-to-end simulation of
the whole app — wipe the data, seed fresh, drive every feature on the real device with real
recordings, a real business-card scan, real outbound email and real calendar invites, and
write up everything that misbehaves. **That run is COMPLETE — all 14 acts ran (2026-08-05).**
The next job is the **fixing phase**, which needs a new named unfreeze; see *"After Round 7
finishes"* below. ⏹ **That fixing phase has since run to completion — all three tranches.**

**The driver was `Complete_Project/Workflow_simulation/Workflow1/SIMULATION_RUNBOOK.md`**
(it has since moved into `Workflow1/`). ⏹ **Its "WHERE WE ARE RIGHT NOW" block is EXPIRED** —
do not read it as the live position. This section holds the Round 7 environment and standing
rules as they were.

**The user is a participant, not a spectator.** Three things need them physically: scanning
the business card, playing the recordings near the phone, and confirming before anything
irreversible. **All four recordings are now played; Act 14 needs them only for the voice step.**

### Environment as left — the backend is RUNNING, not stopped

This differs from every previous handoff, which left everything stopped.

> ⚠️ **2026-08-05: it did NOT survive the gap.** At the start of the Act 12 session the backend
> was dead (no `python.exe`, nothing on 9010), `adb reverse` was gone (the adb daemon had
> cold-started), and the app was on the **login screen** with no session. Everything was
> restored with the block below and the DB verified intact first. **Treat "left running" as a
> claim to check, not a fact** — `/health`, `adb reverse --list` and the foreground activity
> are one command each. Two further gotchas found the same day: **`logcat` is restricted on
> this Vivo** (returns 0 lines), and **uvicorn's access log goes to stdout** while startup and
> warnings go to stderr — redirect both or you will think no request arrived.

| | |
|---|---|
| Backend | **RUNNING**, `PORT=9010`, started from `Complete_Project` with **no env overrides** so `.env` governs |
| `adb reverse` | **SET** — `tcp:8000 → tcp:9010`; phone pref is `http://127.0.0.1:8000` |
| Email | **LIVE — `EMAIL_MODE=smtp`.** Real mail, from and to `ekaghni.mukherjee@gmail.com` |
| Calendar | **LIVE — `CALENDAR_MODE=google`.** Real events on that personal calendar |
| Inbound | **`INBOUND_EMAIL_MODE=off` — see F35. DO NOT RE-ENABLE.** Client replies go through the app's *Log a client reply* screen |
| WhatsApp | `dry_run` (no `WHATSAPP_PHONE_NUMBER_ID` configured) |
| App | **`0.7.3-f31` installed, signed in as Rahul (sales_agent)**, on the Orchid lead's **Meetings** tab |
| Backend code | **FROZEN.** The seed-script unfreeze is complete and closed |

**If the backend died**, restart it exactly like this — note there are **no** `EMAIL_MODE`
overrides, because this run is deliberately live:

```powershell
cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project
$env:PORT="9010"
Remove-Item Env:EMAIL_MODE,Env:WHATSAPP_MODE,Env:CALENDAR_MODE -ErrorAction SilentlyContinue
python run.py
```

Confirm **`Platform ready`** in the NEW log, then
`& $adb reverse tcp:8000 tcp:9010`. `/health` alone is not proof (§6g).

### Standing rules for the rest of this run

1. ⏹ **“Do not rebuild the APK” has EXPIRED** (2026-08-05, when the simulation finished). It
   existed only to protect `0.7.3-f31` while it was the build under test. **App-side fixes are
   no longer blocked by it** — F36, F39, F48, F53, F58 and F37's two deliberately-unmoved
   literals are all actionable now. A rebuild is still a change and needs the same unfreeze as
   backend work.
2. **Do not re-enable IMAP** (F35). It reads and marks-read the owner's personal mailbox.
3. **Do not wipe again.** The pre-simulation backup is
   `data/_backup_pre_sim_20260803-211931` (DB + storage + `.env`, 31.8 MB).
4. **Backend stays frozen.** Bugs go into `FINDINGS.md` Round 7; they do not get fixed unless
   the user grants a new named unfreeze.
5. **Ask before anything irreversible or outward-facing** — and note that in this run
   *sending mail and creating calendar events is expected and already authorised*, while
   wiping, rebuilding and IMAP are not.
6. **Verify a cause in the source before writing a finding.** Every Round 7 entry so far
   names the file and line; keep that bar.

### The database — AS SEEDED (not as it is now)

> ⚠️ **These are the numbers the seed produced on 2026-08-03, kept because they document the
> seeding contract. They are NOT current** — thirteen acts have run since. For the live counts
> always read the runbook's *"Database state — the numbers to diff against"* block, which is
> updated after every act (as of Act 13: 9 leads, 16 contacts, 2 stakeholders, 4 meetings,
> 6 plan versions).

Wiped and re-seeded fresh. **Seed order is load-bearing (F33): `seed_demo.py` THEN
`seed_workflows.py`.** Result: 1 org, **13 logins**, 45 user-skills, 3 programs, 6 pricing
tables, 3 proposal templates, 4 playbooks, 16 approval rules, 1 vendor, 7 leads, 10 contacts.

**All 10 contact addresses were rewritten to `ekaghni.mukherjee+<name>@gmail.com`** so live
SMTP never bounces against the seeds' fake `.edu` domains, while TO-vs-CC routing stays
distinguishable per person.

✅ **Watch item — CLEARED (kept for the record).** The merged seed produced **two overlapping
skill vocabularies** — `logistics` vs `logistics_coordination`, `proposals` vs
`proposal_preparation`, `teaching` vs `training_delivery`, where F25's premise was one
vocabulary. **It never materialised**: Acts 5 and 13 both assigned sensibly across both
vocabularies, each with a real reason. See the confirmation further down this section — the two
statements now agree. The runbook says the same.

### Findings raised in Round 7 — 27 (F32–F58)

> ⚠ **This section's open/fixed split is from 2026-08-03 and is WRONG now.** Two fix tranches
> have run since. **`FINDINGS.md`'s status table is the authority.**

`FINDINGS.md` → Round 7 has the full write-ups and **is the authority**. Below: a one-line
summary per act-group, then detail on only the **first six** (found *before* the app simulation
really began). Everything from F38 onward lives in `FINDINGS.md` alone — do not re-derive it.
**Open: F35, F36, F38, F39, F40, F41, F42, F43, F44, F45, F46, F47, F48, F49, F50, F51, F52,
F53, F54, F55, F56, F57, F58.**

**Act 13 (2026-08-05) added F54–F56** — a complaint made **in a meeting** never becomes an
incident (W22 is reachable from email only; 🟠 **downgraded to medium on re-checking the spec** —
W22 is an *inbound* story, so this is a product decision, not a contract violation), a second campus creates no opportunity while its
decision maker is attached to *this* project, and the **commitment register is write-once**
(11 rows from meeting 1, zero from three merges). Act 13 also produced the round's **best
extraction** and proved the **protected plan state survives a fourth meeting** (v6 held
`pending_review`; v4 active, v5 draft, 4 conflicts open — F49 did not recur).

**Act 12 (2026-08-05) added F50–F53** — a completed client-visible task whose client update was
dropped with **no trace at all** (F50), a task router that enforces ownership on **1 route of
23** (F51, device-proven), and two surfaces that disagree about what is late (F52/F53). It also
**corrected F43** ("exactly two places" retracted) and confirmed **W16 and W11 pass** end to
end. Do not re-derive any of it from here — read `FINDINGS.md`.

The twelve found *during* Acts 2–11 — **F38** (a corrected address reaches a queued message by
no path, not even rejection), **F39** (recorder pause is one-way; the mic keeps running while
the UI says "Paused"), **F40** (meeting consent record hardcoded to `in_app`), **F41** (the
first meeting drops its people — **cause proven in Act 10: a wiring gap, not a prompt
problem**), **F42**, **F43**, **F44**, **F45**, **F46**, **F47** (a `[missing:…]` placeholder
went out in a **real client PDF**), **F48**, **F49** — are written up in `FINDINGS.md` only.
**Do not re-derive them from this section**; several carry corrections that matter, including
fix-safety tables showing which obvious fixes would break other things.

⚠️ **From 2026-08-04, the three-pass rule governs all findings and fixes** — runbook
*"Hard rules for this run" → Rule 8*. Check a suspected bug three ways (observe with a
reliable instrument · read the code path **and its callers** · look for the innocent
explanation) and a proposed fix three ways (grep every caller · check what the schema assumes ·
prove by behaviour). Say plainly what you did **not** test.

⚠️ **The skill-vocabulary watch item above did NOT materialise.** Act 5's assignments were
sensible across the merged vocabularies (Baski→curriculum, Shyam→worksheets,
Sourav→facilitators, Mithun→logistics/procurement), each with a real reason. Treat the watch
item as cleared unless a later act contradicts it.

- **F32** ✅ both seed scripts committed, printed success and **never exited**, holding the
  SQLite file so the next writer blocked. Undisposed `aiosqlite` worker thread.
  **This corrects §6g/§6i, which have blamed "a script that raises" since 2026-07-22 — it
  happens on SUCCESS.**
- **F33** ✅ `seed_demo`'s guard is org-level, so seed order silently decides whether you get
  Siva/IBC/the F25 skills at all. Now loud and exits 2.
- **F34** ✅ `seed_workflows` stored `email_domain='@yuvipep.com'`; `admin.py:84` builds
  `"@" + domain`, so **no staff could ever be added**. Verified live: `POST /admin/users` 200.
- **F35** 🔴 the IMAP poller hardcodes `select("INBOX")`, no scoping, **non-PEEK** — pointed
  at the personal Gmail this `.env` designates it marked ~25–75 real emails read at up to
  750/hour. Mitigated by turning it off. **The IMAP transport is therefore knowingly
  untested by Round 7.**
- **F36** 🔴 login screen's `server:` label stale after Environment-sheet Apply
  (`refreshServerChip` only in `onResume`; a dialog dismiss never fires it).
- **F37** ✅ **the F31 app guard was itself broken** — line-based, blind to wrapped setter
  calls, so it reported "none" on a file containing one. F31's "nine hardcoded literals" was
  really **eleven**. Guard fixed (11/11); the two literals are deliberately still in Java.

**Lesson worth carrying (F37):** a falsification matrix asks *"does this check notice a fix
being removed?"* It never asks *"is there a shape of input this check cannot see?"* Every
fixture in that guard was a single line, so the whole wrapped-call class went untested.

### Suites, all green as of the pause

pytest **104/104**, dryrun **43/43**, stakeholders --stub **21/21**, gap **21/21**,
`verify_live_genericity.py` **15/15**, `verify_live_resolution.py` **19/19**,
`check_hardcoded_strings.py` precision **11/11** (now reporting its 2 real findings).

### After Round 7 finishes — the order is: Act 14, then FIXES, then §7.1

**1. ✅ The simulation is FINISHED** — all 14 acts ran on 2026-08-05.

**1b. Do the spec-check pass over F35–F49 first.** For each, establish whether a *spec sentence*
mandates the expected behaviour or whether it rests on inference. This check downgraded **F54**
(W22 is written entirely as an inbound story) and strengthened **F55/F56** (W29's per-project
stakeholders; Data Model §4.5 "from meetings"). Only 7 of the open findings currently cite a
contract; the rest are deterministic defects that may not need one — but that has not been
verified finding-by-finding.

**2. Then the fixing phase, which needs a NEW named unfreeze.** Standing rule 4 still applies:
the backend is frozen and Round 7 has been *documenting* bugs. Twenty-one findings are open.
**The fix plan is `FINDINGS.md` → "Round 7 — fix order"** — grouped, ordered, with the
dependencies and the fix-safety warnings that several findings earned the hard way (F38/F41/
F42/F44/F50/F51/F56 each have a documented wrong fix). Note some findings are **app** changes,
not backend, so they also need the APK-rebuild rule lifted — which cannot happen until the
simulation is finished, because `0.7.3-f31` is the build under test.

**3. Then — and only then — Phase 7 §7.1, money & ops.** Doc 10 → Phase 7 §7.1. Note that §7.1
builds the screens Round 7 currently *cannot* reach (invoices, incidents, vendors, leave,
bookings, deliverables), so Round 7's Track B results are direct input to it.

---

# ⛔ EVERYTHING BELOW THIS LINE IS FROZEN HISTORY — DO NOT ACT ON IT

Sections §8-pre7 → §8c are the state of the world at the end of **earlier** sessions, kept
only so a decision can be traced back to its reason. They are **all superseded by §8-pre8**.
Anything they describe as "next", "open" or "environment as left" is **stale by definition**.

## 8-pre7. State — 2026-08-03, post-F31 (SUPERSEDED by §8-pre8, kept for history)

> ⚠️ **SUPERSEDED.** Its "resume at Phase 7 §7.1" instruction and its "NO FINDING IS OPEN"
> claim are both **out of date** — Round 7 intervened. Its account of how F31 was closed
> remains accurate and is the reason it is kept.

**Where to resume: Phase 7 §7.1 — money & ops.** Invoices, incidents, vendors, leave,
bookings, deliverables. Doc 10 → Phase 7 §7.1. **Nothing blocks it.** Phone build
**`0.7.3-f31`**, signed in as **Siva**.

**FINDING F31 is CLOSED, and with it every finding — the list is empty.** The backend was
unfrozen for one named job — *"F31 genericity, full scope incl. corrections A/B and item C"*
— and is now **RE-FROZEN**. §7 rule 5 applies again: no backend code changes without a new
explicit unfreeze.

**F31 in one paragraph.** Domain-genericity had three live defects and a landmine. All fixed:
a project's `value_estimate` now prices **any** unit the org uses (per seat, per licence, per
rack) instead of only "per student"; a scope amendment carries the **client's own** unit into
the client-visible document; `document_engine` — the file §7.1 builds in — no longer tells
the model it works for an "education-services company"; and the app renders each project's
own **currency** instead of a hardcoded `₹`. **Two of F31's own claims were wrong** (the
currency field was never on the wire — `_project_dict` had never serialised it; and
`_estimate_value` also returned `None` for a flat-priced engagement), and **the new guard
found three further sites by itself**, two of them in `planning.py`, which F31 had certified
clean. Full write-up: `FINDINGS.md` → F31 → "How F31 was fixed". Lessons: **§6j**.

**The durable part is two guards, not the ten fixes.** Read this before writing any new
engine, prompt or screen:
- `pytest tests/test_genericity.py` — AST-walks every module under `app/` and fails on an
  industry word in anything that reaches a model (prompt kwargs, `messages=`, whole tool/JSON
  schemas **including property names**, following a variable reference one level).
- `python scripts/check_hardcoded_strings.py` — the app half: user-visible Java literals
  outside `strings.xml`, domain words, and hardcoded currency symbols. Android Lint's
  `HardcodedText` is **XML-only**, which is the hole that hid this twice.
- `python scripts/verify_live_genericity.py` — the real model, a colocation client priced per
  rack in USD (needs a live key; writes only to a throwaway DB).

**Suites:** pytest **104/104** (96 + 8 new), dryrun **43/43**, gap **21/21**, stakeholders
--stub **21/21**, `verify_live_resolution.py` **19/19** (re-run because F31 edits a prompt the
F28 resolver path uses), `verify_live_genericity.py` **15/15 against the real model**.
**Falsification matrix 18/18** — every fix disabled in turn and the named check required to go
red; it caught three blind spots *in the guard itself*, which is why §6j says to run one.

**What the backend gained (all additive — no schema change, no migration, no contract
break):** one new response key, `"currency"`, on `GET /projects` and `GET /projects/{id}`.
Everything else is behaviour. `quantity_delta` / `content_change` replace `students_delta` /
`syllabus_change` in the live LLM schema, and **both readers still accept the old names**.
Files touched: `planner_engine.py`, `inbound_engine.py`, `document_engine.py`, `nlu.py`,
`ai/planning.py`, `ai/orchestrator.py`, `ai/agents/proposal_agent.py`,
`ai/agents/email_agent.py`, `api/projects.py`, `scripts/dryrun_part3.py`,
`scripts/verify_live_change_requests.py`, **new** `tests/test_genericity.py`, **new**
`scripts/check_hardcoded_strings.py`, **new** `scripts/verify_live_genericity.py`.
App: **new** `core/util/Money.java`, `ProjectDto`, `ProjectDetailFragment`,
`ProjectsListFragment`, `ProposalDetailFragment`, `LeadDetailFragment`, `RoleHomeFragment`,
`MeetingReviewFragment`, `TaskDetailFragment`, `ApprovalAdapter`, `ApprovalDetailFragment`,
`strings.xml`, `build.gradle`.

**Environment as left: backend STOPPED, `adb reverse` cleared, no orphan `python.exe`
(all three re-checked).** `.env` **untouched and LIVE** (`EMAIL_MODE=smtp`,
`CALENDAR_MODE=google`, paid models) — a plain restart returns to live email/calendar.
Everything ran with `EMAIL_MODE=dry_run CALENDAR_MODE=off` as environment overrides, on
**PORT=9010** + `adb reverse tcp:8000 tcp:9010`. **No mail was sent and no calendar event was
created.**

**Live DB writes this session, all disclosed:**
- **One `[f31-verify]` fixture** — a USD project + its lead, seeded so the currency fix could
  be seen on a phone whose only project was INR. **Already deleted** (both rows).
- Nothing else. The scope-change, amendment and document tests all ran against throwaway DBs
  (`data/verify_genericity.db`, since deleted).
- ⚠️ **The Orchid project still carries `value_estimate = None`**, and that is correct, not
  residue: the estimate is computed at project creation and there is no recompute path. The
  fixed function against that org's own table now yields **210,000** — verified — but an
  existing row keeps its snapshot. If §7.1 wants a recompute, that is new scope.
- ⚠️ The Phase-6 residue in §8-pre5 and the four F28-era drafts in §8-pre6 are untouched.

---

*(Sections §8-pre6 → §8c continue below, all equally frozen — the single divider above
§8-pre7 governs everything from there down.)*

## 8-pre6. State — 2026-08-03, post-F28/F29/F30 (SUPERSEDED by §8-pre7, kept for history)

> ⚠️ **SUPERSEDED.** Its "NEXT WORK — FINDING F31" block is **done**. Kept for provenance.

**Where to resume: Phase 7 §7.0 (F28) plus findings F29 and F30 are DONE and
device-verified; the backend is RE-FROZEN.** It was unfrozen twice this session, each time
for a named job — *"Phase 7 §7.0, F28, full scope"*, then *"F30 + F29"* — and both are
complete. The default rule applies again (§7 rule 5): **no backend code changes without a
new explicit unfreeze.** Phone build **`0.7.2-f30`**, signed in as **Siva**, dark theme.

**NEXT WORK — recommended order: FINDING F31 (genericity) first, then Phase 7 §7.1.**

**F31 is open and it is not cosmetic.** A re-audit on 2026-08-03 found that domain-genericity
— working principle 2 and the product's headline claim — is incomplete in two places that
are **live**, plus a landmine sitting in the very file §7.1 builds in:

- `planner_engine._estimate_value` → a project's `value_estimate` is silently `None` for any
  client whose pricing unit is not "student"/"flat" (per seat, per licence, per rack…).
- `inbound_engine._handle_scope_change` → a scope amendment writes a hardcoded
  `"unit": "per student"` into a **client-visible** document.
- `document_engine.generate_text_artifact` → a live LLM prompt hardcoding
  *"education-services company"*. Zero callers today, so harmless now — but §7.1 is
  `create_invoice` / `record_payment` / `add_deliverable`, all in that same file.
- **App:** `ProjectDetailFragment:203` / `ProjectsListFragment:174` hardcode **`₹`** and
  ignore the `currency` the backend already stores per project — a USD project renders as
  rupees. Plus `ProjectDetailFragment:619`'s hardcoded *"e.g. principal…"* hint, which a
  `strings.xml` grep cannot see because it is a Java literal.

**So F31 needs a backend unfreeze AND an app build** — it was first written as backend-only
and that was an under-count.

**Why first, not after:** §7.1 builds invoices, amendments and deliverables in exactly the
files that carry these defects. Fixing afterwards means editing the same code twice and
risks copying the pattern into new code. The fix is small — full write-up, verified call
paths and fix order are in **`FINDINGS.md` → F31**.

**Then Phase 7 §7.1 — money & ops** (invoices, incidents, vendors, leave, bookings,
deliverables). Doc 10 → Phase 7 §7.1. Nothing else blocks it.

**FINDINGS F28 is CLOSED.** A command typed by hand into the Jarvis tab — *"Draft an email
to EKAGHNI MUKHERJEE at Orchid International School about the workshop dates"* — produced a
real draft; an unresolvable person produced an amber **question card** with one-tap
candidates and the line *"Nothing has been drafted or sent yet"*; tapping a candidate and
sending completed the job; and Phase 6's labelled-line triage prompt was reverted to
natural phrasing and still works (that revert is the acceptance test). Full write-up:
`FINDINGS.md` → F28 → "How F28 was fixed". Lessons: handoff **§6i**.

**Open: F31 only** (genericity — see the NEXT WORK block above; **no code written**). F28,
F29 and F30 are all closed and device-verified. Deliberate non-fixes unchanged: F5 =
monitor, F16 = Phase-8 scope, F26 = accepted.

**F29 and F30 in one line each**, both found *while* fixing F28 and both fixed under a
second unfreeze:
- **F30** — a draft carrying `[Name]` blanks could be approved and sent, and most blanks sat
  past the inline card's 300-character preview, so the approver was never shown them. Now
  refused at both approve routes by `app/services/draft_check.py`, with an explicit
  `allow_blanks` override; preview raised to 1200 and honest when truncated.
- **F29** — the digest was the lone place bucketing follow-ups on `utcnow().date()` while
  six neighbours used the local date, so a follow-up due today vanished between 00:00 and
  05:30 IST. Now local. *(An earlier note in this file called this a timezone-architecture
  question — that was wrong and has been corrected in FINDINGS → F29.)*

**What the backend gained (all additive, no schema change, no migration):** an assistant
action may carry `outcome: "needs_confirmation"` + `question` + `candidates[]` alongside the
unchanged `ok:false`/`error`; new `NeedsConfirmationError` (a `ValidationFailedError`
subclass); **`allow_blanks`** on both approve routes; **`blanks[]`** on message reads and on
`pending_approvals[]` (plus `warning` / `preview_note`, and a 1200-char preview). Files
touched: `app/core/exceptions.py`, `app/ai/agents/resolvers.py` (rewritten),
`app/ai/agents/base.py`, `app/ai/orchestrator.py`, `email_agent.py` / `followup_agent.py` /
`proposal_agent.py` (tool descriptions only), **new** `app/services/draft_check.py`,
`app/services/message_service.py`, `app/engines/approval_engine.py`,
`app/engines/assistant_engine.py`, `app/api/messages.py`, `app/api/workflow.py`, **new**
`tests/test_assistant_resolvers.py`, **new** `tests/test_draft_blanks.py`, **new**
`scripts/verify_live_resolution.py`.

**Suites:** pytest **96/96** (74 + 13 F28 + 9 F29/F30), dryrun **43/43**, gap **21/21**,
stakeholders --stub **21/21**, `verify_live_resolution.py` **19/19 against the real model,
three runs running**. Every new test was watched failing with its own fix disabled via a
**falsification matrix** — and the first version of the F28 suite passed with the F28 fix
deleted, which is why §6i now insists on one.

**Environment as left: backend STOPPED, `adb reverse` cleared, no orphan `python.exe`.**
`.env` **untouched and LIVE** (`EMAIL_MODE=smtp`, `CALENDAR_MODE=google`, paid models) — a
plain restart returns to live email/calendar. Everything this session ran with
`EMAIL_MODE=dry_run CALENDAR_MODE=off` as **environment overrides**, on **PORT=9010** +
`adb reverse tcp:8000 tcp:9010` (phone pref stays `http://127.0.0.1:8000`). **No mail was
sent and no calendar event was created.**

**Live DB writes this session, all disclosed. Nothing was emailed** — `EMAIL_MODE=dry_run`
throughout:
- Four `pending_approval` drafts from the F28 device tests and the scheduler's normal sweep
  (workshop dates → `mekaghni@telaverge.com`; pending invoice → Mrs. Nair; the refund-policy
  reply; one ladder chase). Safe to reject or leave. **Two of them still carry `[Name]` /
  `[Insert Date]` blanks** — they now trigger the F30 dialog if anyone taps Approve, which
  makes them useful as live fixtures.
- **One seeded fixture for the F30 device test**, tagged `[f30-verify]` in its subject and
  body: an unfinished draft plus its approvals row. It was approved via **Send as it is** to
  prove the override, so it is now `sent` as a dry-run `.eml` — that is the evidence.
  Delete it whenever.
- A `[f29-verify]` follow-up was seeded for the briefing check and **has been deleted
  again** (a pending follow-up nags the reminder ladder daily).
- Throwaway DBs outside the live one: `data/verify_resolution.db`. Safe to delete.
- ⚠️ The Phase-6 residue described in §8-pre5 is untouched: two open triage items and the
  dry-run reply carrying `[Name]` placeholders. Those predate the F30 fence, so they exist
  as already-sent history; the fence stops new ones.

---

Sections §8-pre5 → §8c are the state of the world at the end of **earlier** sessions, kept
only so a decision can be traced back to its reason. They are **all superseded by §8-pre8**.
Anything they describe as "next", "open", "to do" or "environment as left" is **stale by
definition**. If you want to know what is true now: **§8-pre8** for state and
**`FINDINGS.md`'s status table** for what is done vs open.

---

## 8-pre5. State — 2026-07-29, post-Phase-6 (SUPERSEDED by §8-pre6, kept for history)

**Where to resume: Phase 6 is DONE and device-verified; the backend is RE-FROZEN.** It was
unfrozen by the user for one named job — *"Phase 6 Inbox — additive contract fields"* — and
that job is complete. The default rule applies again (§7 rule 5): **no backend code changes
without a new explicit unfreeze.** Phone build **`0.7.0-phase6`**, signed in as **Siva**,
dark theme.

**NEXT WORK: Phase 7, and it opens with FINDING F28 — not with invoices.**
F28 (found by the user on 2026-07-29, **no code written**): the assistant cannot resolve a
person from a natural phrase — *"draft an email to X at Y"* fails with a lookup error
instead of asking a clarifying question — because `resolvers.py:142` matches
one-directionally. Phase 6's labelled-line prompt was a workaround for one app-generated
command and does nothing for the Jarvis tab. **Five fixes are agreed and written up: read
`FINDINGS.md` → F28, then `10_ROADMAP_MILESTONES.md` → Phase 7 §7.0.** It needs an explicit
backend unfreeze before any of it is coded. The rule it enforces is now working principle
**§7.3b** and `04_JARVIS_ASSISTANT.md` §6.0.

**FINDINGS F27 is CLOSED** — an AI-escalated question was answered from the app end to end.
Open: **F28** only. Deliberate non-fixes: F5 = monitor, F16 = Phase-8 scope, F26 = accepted.

**What the backend gained (all additive, no schema change, no migration):**
`GET /inbound/triage` rows carry `intent`, `change_type`, `matched_lead_id`,
`matched_project_id`, `created_at`; `POST /inbound/{id}/resolve` accepts `intent`
(422-validated against `InboundIntent`) and `project_id` (404-checked, org-scoped);
`GET /messages(/{id})` carries `sender_user_id`. Files touched: `app/api/workflow.py`,
`app/api/messages.py`, **new** `tests/test_inbound_triage.py`, **new**
`scripts/verify_live_inbox.py`.

**Suites:** pytest **74/74** (67 + 7 new — every new test was watched failing with its own
fix disabled, one fix at a time), dryrun **43/43**, gap **21/21**, stakeholders --stub
**21/21**, `verify_live_inbox.py` **17/17** against the real model.

**Three known gaps left deliberately open** (decided with the user, not oversights — see
doc 10's Phase 6 entry): `resolve` accepts a **`note` it never stores** (so no screen
offers one), `resolve` has **no `lead_id`** (attach goes through a contact; a client with
none dead-ends honestly), and `GET /messages` omits **`attachments`** (the trace says so
on screen; the dry-run `.eml` is still openable). Also: **there is no confidence field
anywhere** — docs 03/10 promised one and were corrected.

**Environment as left: backend STOPPED, `adb reverse` cleared.** `.env` **untouched and
LIVE** (`EMAIL_MODE=smtp`, `CALENDAR_MODE=google`, paid models) — a plain restart returns
to live email/calendar. Everything this session ran with `EMAIL_MODE=dry_run
CALENDAR_MODE=off` as **environment overrides**, on **PORT=9010** + `adb reverse tcp:8000
tcp:9010` (phone pref stays `http://127.0.0.1:8000`). **No mail was sent and no calendar
event was created.**

**Live DB writes this session, all disclosed:**
- **Two seeded inbound messages** for the device test: a stranger
  (`priya.menon@brightpath-academy.example`) which was triaged, re-intented to `scheduling`,
  attached to Orchid International School and **marked handled**; and a refund-policy
  question from the real contact, which the AI escalated (`needs_human`, *"No data found to
  answer — the AI never guesses"*) and which **remains in the queue** as the F27 evidence.
- **One logged call** (the "Log a reply" test) — a reschedule request from August to early
  September, classified `change_request` / needs_human. Still in the queue.
- **One outbound message really "sent"** (dry-run `.eml`, nothing left the machine): the
  approved reply about the refund policy. Its delivery trace is the Phase 6 evidence.
  ⚠️ Its body contains literal `[Name] / [Designation] / [Email]` placeholders — the model
  had no sign-off contact on file. The human approval gate is what would normally catch
  that; it was approved here to prove the pipeline. **Worth a look if you demo this org.**
- The scheduler's normal sweep drafted its usual ladder chases while the backend was up
  (`overdue_laddered: 5`, `reply_nudges: 1`) — all dry-run.
- Test databases created outside the live one: `data/verify_inbox.db`,
  `data/test_baseline.db`. Safe to delete.

---

## 8-pre4. State — 2026-07-23, post-FINDINGS-job (SUPERSEDED, kept for history)

**Where to resume:** the FINDINGS job is **CLOSED** — **all fixable items are DONE** (F25 was the
last, 2026-07-23) and the **backend has been RE-FROZEN** (default rule again: no backend code
changes without a new explicit unfreeze). What remains is deliberately not a code fix: F5
(monitor), F16 (Phase-8 scope), F26 (accepted), F27 (planned as Phase 6). **Next work: Phase 6 —
Inbox & messages** (see §2 and doc 10), or the user's next ask. Phone build **`0.6.5-findings`**.

**Environment now: backend STOPPED, `adb reverse` cleared** (no orphan — §6g checked). `.env`
untouched and LIVE (`EMAIL_MODE=smtp`, `CALENDAR_MODE=google`, **paid models** — see
`openrouter-paid-model-switch` memory; ask before anything that sends mail / creates calendar
events). To restart for device work: `PORT=9010 EMAIL_MODE=dry_run CALENDAR_MODE=off python
run.py` + `adb reverse tcp:8000 tcp:9010` (avoid the 8xxx port family; phone pref stays
`http://127.0.0.1:8000`). `adb` at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`; use
`MSYS_NO_PATHCONV=1` for on-device paths.

**F25 is DONE (2026-07-23), backend + seed only, no schema change, user chose "constrain the
planner + seed".** `seed_demo.seed_user_skills` seeds an 8-skill taxonomy (incl. `general` for
everyone); `planning._context_block` now tells the planner to pick required_skill from that list
(the infra to feed it already existed); `validate_task_specs` coerces any invented skill onto
`general` (a prompt is not a fence). New `verify_live_planner_skills.py` **3/3** — a forklift
transcript maps to real skills, 0 gaps. **The live demo DB was back-filled with 24 skill rows.**
On the Vivo the assignment screen now reads *"Siva: expert skill match"* / *"Baski: expert skill
match"* where every proposal used to say "no skill match". *(Soft edge: a task the model leaves
with a blank skill still shows "no skill match" — blank isn't invented, so it isn't coerced.)*

**F24 is DONE (2026-07-23), user chose "warn at the review gate".** No schema change: `GET
/meetings/{id}/review` gained a computed `possible_duplicate_of {id,title,at}` per item
(`meetings.py::_duplicate_hints`, same `_title_similarity`/0.7 as the F22 fence — the lead's
most-similar open task from another meeting or added by hand, else null). App `0.6.5-findings`:
a ⚠ line under the review card. Device-verified on the Vivo — flagged the restated
"Send proposal and fee structure", left "Arrange teacher demonstration" clean. Advisory only;
the human keeps/drops as before. New test both directions (watched failing disabled).

**F23 is DONE (2026-07-23), backend-only, no schema change.** `proposal_service.narrative_price_
drift` + a reject in `apply_narrative_edit`: a deterministic fence (3rd "a prompt is not a
fence" instance) that scans the rewritten PROSE for money-shaped numbers not in the locked
commercials and rejects the edit before mutating. New `scripts/verify_live_proposal_guard.py`
**3/3** — the real STRONG model emitted `1,305/8,550/10,800/218,700` on a discount instruction
and the fence caught all four. Not device-tapped (no proposal/program seeded in the demo org).

**The copy pass is DONE (2026-07-23), app `0.6.4-findings` + one backend tweak.** F7/F13/F14/
F15/F12 — see FINDINGS "How the copy pass was done". Two under-counts caught: F13 was **2
sites** (`FollowUpQueueFragment` + `ProjectDetailFragment`), F15 was **2 halves** (empty-state
string + the digest greeting). F12/F14/F7/F13 and the "Good morning, Siva" greeting were all
screenshot-verified on the Vivo; the F15 empty-state string is a resource swap in the same
build (Siva's Waiting-on-you was not empty to photograph it).

**F17 and F19 are DONE (2026-07-23), backend-only, no app change, no schema change.**
- **F17** — the Jarvis context chip now actually filters. Hybrid fix (chosen with the user over
  prompt-only): `query_agent._effective_client` binds the selected `lead_id` as the default
  client filter for `list_action_items` / `search_past_notes` / `get_client_details` (explicit
  client wins; `client="all"` broadens back); and `base._enrich_context` resolves the lead id
  to a name so the system-prompt hint reads *"currently viewing 'X'"* instead of an opaque UUID.
- **F19** — `_item_dict` (and the conversation agent's `_list_items`) now return `priority`.
- Verified: pytest **61/61** (+3, each watched failing with the fix off), dryrun 43/43, gap
  21/21, stakeholders --stub 21/21, **new** `scripts/verify_live_assistant_context.py` **6/6**
  against the real model, and **on the Vivo** — the *About: Green Valley* chip scoped "what are
  the action items?" to that lead only, and "most important task" named the P1 due *last*, not
  the soonest-due. Three synthetic device-test tasks were created on Green Valley/DPS and
  **cancelled with a note afterward** (never deleted).

**Read `FINDINGS.md`'s status table first — it is the single source of truth for what is done.**
**Every fixable finding is now FIXED** (2026-07-22: F4/F4b, F8, F9, F22, F1, F2, F10, F3, F11,
F6; 2026-07-23: F17, F19, the copy pass F7/F13/F14/F15/F12, F23, F24, F25) — device-verified on
the Vivo wherever the UI could reach it (exceptions covered by unit + live tests through the
production code path: the card-scan half of F2 needs a camera; F23 needs a proposal the demo org
doesn't seed). Job totals: **pytest 67/67**, dryrun 43/43, gap 21/21, stakeholders --stub 21/21,
three new live scripts (`verify_live_assistant_context` 6/6, `verify_live_proposal_guard` 3/3,
`verify_live_planner_skills` 3/3). **No schema change** by any fix in the whole job.

**The only remaining findings are NOT code fixes** (do not "resume" them as work):
- **F5** — Whisper `bn`/hallucinated lead-in. **Monitor** — did not reproduce in 6 recordings.
- **F16** — org_admin has no route to projects/leads/tasks. **Scope reality** — those are
  Phase-8 admin screens; not a defect.
- **F26** — new FAST model escalates some inbound questions the old one answered. **Accepted** —
  escalating to a human is fine; no model change.
- **F27** — an escalated question had nowhere to be answered. **Resolved as a plan** — the Inbox
  is now **Phase 6** (below).

**⚠ THE ROADMAP WAS RENUMBERED (2026-07-22).** The Inbox/message centre was specified in
docs 02/03/05 — it is one of the sales agent's five bottom-bar tabs — but belonged to **no
phase**. It is now **Phase 6 — Inbox & messages**; Money & ops → **7**, Admin & platform →
**8**, Push/polish/release → **9**. All doc references were updated. Note the app's
placeholder tabs still print the OLD numbers to users ("Incidents arrives in Phase 6…");
**F14 in the copy pass removes those roadmap leaks from user-facing copy**, which resolves it.

**Models: the project is OFF the free tier** (config-only, flagged).
`OPENROUTER_MODEL_FAST=openai/gpt-5.4-nano`, `OPENROUTER_MODEL_STRONG=google/gemini-2.5-flash`,
`LLM_DEFAULT_ORG_MONTHLY_BUDGET_USD=3.0`. Chosen by a measured bake-off of six candidates
(42/42 three runs running, ~5.9× faster than the free model, card scan 0.95). `MODEL_COSTS` in
`app/ai/llm.py` gained the OpenRouter ids — **keys must carry the provider prefix** or spend is
recorded at the (0.5, 1.5) default. **The budget guard has never executed in this project's
life** (`:free` always cost $0.00); 3.0 arms it for the first time, and its failure mode is
`BudgetExceededError` on every AI call.

**Current live DB (2026-07-23), intentional writes disclosed:**
- **F25 back-fill: 24 `UserSkill` rows** across the 8 demo users (the fix — see the F25 block
  above). The org skill taxonomy is now: `client_relationship, content_development,
  curriculum_design, general, logistics_coordination, proposal_preparation, quality_assurance,
  training_delivery`.
- A demo project **"Forklift Safety Training – Pune Safety Institute"** with a plan + 3
  **unconfirmed** assignment proposals — left as the F25 device evidence (the screen shows real
  "expert skill match" reasons). Cancel/ignore at will.
- F17/F19/F24 synthetic test tasks were **cancelled with a note** (never deleted). No mail was
  sent and no calendar event created all session (`EMAIL_MODE=dry_run` throughout).
- **Multi-user sync demo (2026-07-23, user-requested, not a finding):** a 2nd `sales_lead`
  **Anita Rao** (`anita@yuvipep.com`, password `Password@123` after first-login change) was
  created to prove two sales leads share one client record. As Siva: Jarvis drafted + sent
  (dry-run) an **IBC proposal on Delhi Public School** (₹59,000, status `sent`) and a typed-notes
  meeting spun up project **"Delhi Public School - IBC STEM Program"** (7 phased tasks, F25 skill
  assignments to Siva/Baski/Mithun). Signed in as Anita on the Vivo → she saw the sent proposal,
  the project, all tasks, and "7 assignments proposed" — **verified the shared record syncs**;
  tasks assigned by skill (none to Anita) illustrated the shared-vs-personal-view split. These
  demo artifacts are left in the live DB; cancel/ignore at will.
- Phone: Vivo `10BFBT0TXJ001NP`, build **`0.6.5-findings`**, signed back in as **Siva**.

---

**Environment as left — 2026-07-22 checkpoint (SUPERSEDED; current state is "Where to resume"
+ "Current live DB" at the top of this section):**
- Backend **STOPPED** — no orphaned `run.py` (§6g). **`.env` untouched and LIVE**
  (`EMAIL_MODE=smtp`, `CALENDAR_MODE=google`): a plain restart returns to live email/calendar.
- `adb reverse` **cleared** (`--remove-all`). Phone pref stays `http://127.0.0.1:8000`. Avoid
  the **8xxx** port family (VS Code/ComfyUI take 8000/8001) — :9010 worked well.
- **`adb` is not on PATH** — `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`.

**⚠ THE LIVE DB WAS RESEEDED on 2026-07-22** (deliberately — a reseed is F1's reproduction case).
`data/salesplatform.db` is now a fresh `seed_demo.py` seed: 8 users + super admin, 3 leads,
0 notifications, all-new user ids. Everything from the simulation and the earlier fixes —
Telaverge, Kirloskar, Vidarbha, Nashik and their projects/plans/meetings — is in
**`data/salesplatform.db.pre-f1reseed-20260722`** (+ `-wal`). Earlier backups retained:
`…pre-f22cleanup-20260722`, `…pref4-20260722`, `…presim-20260721-2242`.

**Live-mode side effects: NONE.** No mail sent, no calendar event created. One accidental
write is disclosed: ~5 `llm_usage` rows reached the live DB before
`verify_live_meeting_extraction.py`'s missing `DATABASE_URL` was found and fixed.

**Files changed this session** — backend: `planner_engine.py`, `lead_service.py`,
`message_service.py`, `intro_service.py`, `demo_invite_service.py`, `proposal_service.py`,
`assistant_engine.py`, `sync_engine.py`, `inbound_engine.py`, `knowledge_engine.py`,
`communication_engine.py`, `orchestrator.py`, `vision.py`, `llm.py`, all six files in
`app/ai/agents/`, `app/api/{projects,meetings}.py`, `app/models/{program,proposal}.py`,
`.env` (3 config lines, all commented); tests/scripts: `test_meetings.py`,
`test_assistant.py`, **new** `test_message_approvals.py`, **new**
`test_explainability_digest.py`, `dryrun_part2.py`, `verify_live_meeting_planner.py`,
`verify_live_meeting_extraction.py`, `verify_generic_stakeholders.py`, `seed_demo.py`;
app: `AuthInterceptor.java`, `TriageListFragment.java` (comment), `build.gradle`;
docs: `FINDINGS.md`, `README.md`, `10_ROADMAP_MILESTONES.md`, this file.

## 8-pre3. State at the end of the F4/F8/F9 fix session (2026-07-22) — SUPERSEDED by §8-pre4

> Historical. Its "resume at F22" instruction is **done**; do not act on it.

**Where to resume:** `FINDINGS.md`, item **F22 — the regression this session shipped**
(confirmed review-gate items and Planner tasks are the same work stored twice), and
only then **F1** (401 session-expiry must wipe Room + AssistantSession like
`AuthRepository.logout()` does; app-side, no unfreeze needed). The ✅/⚠️/⬜ status
table is at the top of `FINDINGS.md`; the full order is at the bottom of it.

**A late chat review added three more findings — F17, F19 and F22** — the assistant
answered a four-question conversation about one lead *correctly in prose* while the
scoping, ordering and counts underneath were wrong: the context chip is only a prompt
hint and never filters (**F17**), the query agent cannot see `priority` at all so
"priorities" silently means "soonest" (**F19**), and **F22** above. Three further
nits from the same review were reviewed with the user and **deliberately dropped as
cosmetic** (so the numbering skips F18/F20/F21) — `resolve_lead`'s substring match
failing on Warehousing/Warehouse, two count scopes rendered as one unlabelled number,
and raw field names like `Important: false` reaching the chat. Full write-ups are in
the "Round 2" section of `FINDINGS.md`.

**Environment as left:**
- **Backend deliberately STOPPED** at end of session — no orphaned `run.py`, no live-SMTP
  scheduler left running (this session began by finding exactly that from the previous
  one; §6g). Start it fresh next time. It ran on **:8010** here because both 8000 and
  8001 were held by ComfyUI — check `curl 127.0.0.1:8000/health` first and pick any free
  port. `.env` is untouched and LIVE (`EMAIL_MODE=smtp`, `CALENDAR_MODE=google`,
  `LLM_PROVIDER=openrouter`).
- `adb reverse tcp:8000 tcp:8010` was left mapped but now points at a dead port —
  re-run it against whatever port the new backend takes. Phone pref `base_url` is
  unchanged at `http://127.0.0.1:8000` and needs no edit.
- Phone: Vivo `10BFBT0TXJ001NP`, build **`0.6.2-findings`**, signed in as **Siva**
  (sales_lead). Auto-rotate **restored to 1**.
- DB backup taken before device work: **`data/salesplatform.db.pref4-20260722`**
  (+ `-wal`). The pre-simulation backup `…presim-20260721-2242` is still there too.

**Live-mode side effects: NONE.** No mail was sent and no calendar event created this
session. The `outbound_message` approval sitting on Siva's Home was deliberately left
untouched — approving it sends a real email.

**New data in the live DB (all real and intentional, from device verification):**
- **Kirloskar Industries** (Pune, contact Anil Kulkarni) → project *Kirloskar Safety
  Training Program*, plan **v2 active** (first recording birthed it, second merged).
  Its **v1 task titles carry cosmetic `(due …) — …` pollution** from before that fix
  landed — `due_date` is correct, the titles are just ugly. Harmless.
- **Vidarbha Warehousing** (Nagpur, contact Meera Joshi) → project *Vidarbha
  Warehousing Forklift Safety Certification Program*, plan v1, 6 phased dated tasks.
  This is the run against the **final shipped code** — clean titles, no duplicates.
- **Telaverge Solutions** → plan **v2 active** (the F4 regression recording merged
  into its existing project; v1 superseded).
- The **pre-existing contaminated row** from the simulation is still there on purpose
  as evidence: `client_intelligence.id = b1f04323…`, *"The school operates offices in
  Bengaluru, Hyderabad, and Pune."* Delete by hand when convenient.

**Files changed this session** — backend: `app/ai/extraction.py`, `app/ai/planning.py`,
`app/jobs/pipelines.py`, `app/jobs/__init__.py`, `app/api/meetings.py`,
`app/engines/planner_engine.py`; tests/scripts: `tests/test_meetings.py`,
`scripts/smoke_live.py` (kwarg rename), **new** `scripts/verify_live_meeting_extraction.py`
and `scripts/verify_live_meeting_planner.py`; app: `ReviewConfirmResponse.java`,
`MeetingReviewFragment.java`, `strings.xml`, `build.gradle` (versionName).

## 8-pre2. Open after the conversation-memory change (2026-07-21) — SUPERSEDED

> Historical. Its open item (device tap-test of conversation memory) was closed 2026-07-22.

- **Not tap-tested on the Vivo.** Everything below the UI is proven (42/42,
  43/43, 21/21, 12/12 live, wire-contract checked field-by-field against the
  Gson DTOs, APK builds). What has NOT been exercised by hand: the **+**
  new-chat dialog, the cold-start transcript restore, and dictating a
  follow-up ("make it warmer") through the mic. Deliberately not done in
  that session: `EMAIL_MODE=smtp` is LIVE and a backend was already running
  on :8000 against `data/salesplatform.db`, so starting a second instance
  (second scheduler, same DB) risked sending real email. Do the device pass
  with the user's backend restarted on the new code, not alongside it.
- **The running backend on :8000 predates this change** — it must be
  restarted before the phone can use `session_id` (its process has the old
  code, and its DB has no `assistant_turns` table until `init_db` runs).
- **Reasoning leak, pre-existing, worth a look**: with
  `OPENROUTER_MODEL_FAST=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`
  a reply occasionally arrives as visible chain-of-thought ("We have the
  list of action items. The user asks …") instead of an answer. Seen during
  this run and unrelated to conversation memory — it is the model tier, not
  the plumbing. Candidate fix: a non-reasoning fast model, or strip
  `<think>`-style preambles in the provider adapter.

## 8-pre. Residue from the Phase-4 closeout + Phase 5 verification (2026-07-21, live demo DB) — SUPERSEDED

> Historical, and its database no longer exists — the live DB was reseeded 2026-07-22 (§8-pre4).

- **Nexora CSR STEM Pilot**: plan **v3 "Preparation wave"** is active
  (my deliberate shift-phase test) on top of the accidental **v2 "Sales
  wave"** from last session (which also left 5 sales tasks — one
  in_progress by Siva — plus 3 instantly-broken commitments and 2 open
  "theirs" commitments with nonsense due-dates, all LLM-derived; the
  broken ones are why health = `delayed`). **8 assignment proposals**
  from the preparation wave sit in Siva's Waiting-on-you feed (3 were
  briefly in Mithun's from the sales wave). Anita Rao's stakeholder row
  now reads `csr_program_director` / decision_maker / gets-updates (my
  add-stakeholder test — an update, no duplicate). **Sourav is now a
  real project member** (API-level add-member verification).
- **Demos**: DPS demo moved to **2026-07-28 10:00** (reschedule test);
  new **Green Valley demos on 2026-08-02 and 2026-07-28 11:00**, both
  team Alpha, both deliberately double-booking Alpha (clash-warning
  tests — warnings were shown, bookings kept). **Three `demo_invite`
  outbound messages sit at `pending_approval`** (invisible in Approvals —
  see §6f) and one Phase-2 `intro` message is still pending too.
  **Real Google Calendar events were likely created** for the two new
  bookings (calendar integration is live; see §6f) — delete by hand if
  unwanted.
- **Follow-ups**: Siva's Sunrise follow-up is `done` (note "Sent the
  demo agenda by email") + an auto-scheduled next one `pending` for
  **2026-07-28**. Rahul's Green Valley follow-up (due 17 Jul) is still
  pending.
- **Messages**: one `follow_up` email draft to anita.desai@ (Green
  Valley) **rejected** with note "Too formal - make it warmer and
  shorter" (the dictate-a-rejection acceptance test; nothing sent).
- Phone: signed in as **Siva**, build `0.6.0-phase5`, prefs base_url
  `127.0.0.1:8000` (needs adb reverse). Backend still running on port
  8000 with EMAIL_MODE=dry_run + WHATSAPP_MODE=dry_run env overrides
  (restart plain `python run.py` for live email before a demo).

## 8. Residue from Phase 4 verification (2026-07-20/21, in the live demo DB)

- Port 8000 was free this session (VS Code was not holding it) — backend
  ran directly on `PORT=8000` with `EMAIL_MODE=dry_run` and
  `WHATSAPP_MODE=dry_run` (env-only, not `.env`) so automated device
  testing couldn't send anything real. Still check
  `curl 127.0.0.1:8000/health` first next time — the port-theft gotcha
  (§6d) is a VS-Code-session fact, not a permanent one. **`adb reverse`
  dropped mid-session once** (see §6e) — re-run
  `adb reverse tcp:8000 tcp:8000` at the start of the next session before
  assuming anything is broken.
- The Green Valley School IBC Demo project's task "Draft kit safety
  certificate" was blocked with reason "Waiting on principal
  confirmation" then unblocked again as a live lifecycle test — net
  effect on the DB is nil (back to its original open, unblocked state),
  but its `progress_events` timeline now carries both events permanently
  (harmless, expected).
- **Follow-up round residue (2026-07-21)**, all on the Nexora CSR STEM
  Pilot project unless noted:
  - New child project **"Bengaluru Campus — Nexora CSR STEM Pilot"**
    (`parent_project_id` set) + new lead **"Bengaluru Campus"**
    (`source="chain_deal"`) — real, intentional Chain-wizard output, not
    test debris to clean up; it exercises the Delivery/Pipeline tabs too
    (it has no tasks of its own, so its Overview honestly says so).
  - "Prepare safety compliance documents" task **split** into two real
    children: "Draft the safety checklist" and "Get it reviewed by ops
    lead" (the second depends on the first); original task now
    `superseded`.
  - "Coordinate venue access with HR head Suresh" (Siva's task): vendor
    promise recorded (Sunrise Hall Caterers, 29 Jul) then a vendor slip
    to 1 Aug — the backend's own slack-absorption logic (§6e) then
    *silently moved the task's own due_date to 1 Aug*, confirmed
    independently via Siva's daily-digest text. A New-date attempt to 31
    Jul on the same task was correctly **refused** (breaks a client
    commitment due 30 Jul) and never touched the DB — the notification
    it generated is still sitting unread in Mithun's (operations_lead)
    "Waiting on you" feed.
  - "Prepare facilitator profile" (Siva's task): **declined** by Siva
    herself (reason: wrong_skill, note "No design experience for profile
    write-ups") — backend found no reassignment target (Siva already is
    the phase lead), so `assignee_id` is now null and the task is
    unassigned/open. Pick this back up (reassign or accept) before using
    this project in a demo.
  - A "Shift phase" attempt on this same project was left **inconclusive
    ** — the picker dialog was confirmed to open correctly, but whether
    the final phase selection actually submitted was not confirmed (see
    the open item in §2). If a stray phase change shows up on this
    project next session, that's why — check `project.status` and the
    project's `progress_events` for a `phase_shift`-ish entry to see
    whether it landed.
- Phone signed in as **Mithun (operations_lead)** at end of session
  (account-switched through rahul → sourav → siva → mithun via the real
  Sign-out flow to cover all four roles), build `0.5.0-phase4` **plus two
  post-verification hotfixes** (TabLayout indicator restore, Shift-phase
  chip + its RoleGate fix — same versionName, not re-bumped). System dark
  mode restored after a light-mode screenshot check earlier in the
  session; auto-rotate untouched.
- Backend was left running (background) on port 8000 in dry-run
  email/WhatsApp mode — restart with the live `.env` settings (or just a
  plain `python run.py` without the env overrides) before a real demo.

## 8a. Residue from Phase 3 verification (2026-07-20, in the live demo DB)

- New lead **Nexora Technologies** (Bengaluru, source expo) with contact
  "Anita Rao, CTO, mekaghni@telaverge.com" (the user's own address used
  as the safe stand-in client — EMAIL_MODE=smtp is LIVE now).
- Its proposal `IBC Proposal — Nexora Technologies` (₹59,000) status
  **sent**: one REAL email was SMTP-delivered to mekaghni@telaverge.com
  (message a90540a9…, log drafted→queued→sent) — approved from the
  assistant's inline card as the Phase-3 acceptance send.
- Green Valley proposal 06d44ce1… status **approved_internally** with
  revision trail: v1 Initial draft, v2 "Manually edited file uploaded
  (proposal_edited_ok.pdf)"; its pdf_path is that manual upload. A
  tampered PDF (₹49,000) and — via an automation mis-tap — one random
  PDF from the phone's Downloads were POSTed and **refused** by the
  total check (nothing stored server-side). Test PDFs deleted from the
  phone's Downloads afterwards.
- The Phase-2 pending intro approval to mekaghni@telaverge.com is STILL
  pending — now that EMAIL_MODE=smtp, approving it sends a real email.
- Phone: signed in as rahul, build `0.4.0-phase3`, prefs base_url
  `http://127.0.0.1:8000` (needs `adb reverse` to work), auto-rotate
  restored. Backend was left running on **port 8001**.

## 8b. Residue from Phase 2 verification (harmless, in the live demo DB)

- Green Valley School: state open→cold ("Accepted AI suggestion" history
  row), a dismissed `active` suggestion still stored server-side, one
  notebook note, contacts: "Anita Desai" (full) + a stray bare "Anita
  Desai" (mis-tap during automation — no delete-contact endpoint exists;
  edit/repurpose it later) + "EKAGHNI MUKHERJEE" (real card scan; card
  image under data/storage/.../cards/; an intro email to
  mekaghni@telaverge.com is pending approval — DO NOT approve-send unless
  intended, EMAIL_MODE was dry_run).
- One completed meeting "Robotics program first visit [phase2-verify]"
  (3:01 audio, transcript, 4 open + 1 cancelled action items) and one
  notes-meeting that made the Planner propose a project
  (bc1f43f4…, plan 9462e173…) for Green Valley.
- Phone left signed in as rahul; installed build `0.3.0-phase2`
  (DEFAULT_BASE_URL = tunnel of 2026-07-19, rotates); env-override pref
  and adb reverse were removed after testing.

## 8c. Residue from Phase 1 verification (harmless, in the live demo DB)

- Decided approvals tagged `[phase1-verify]` (audit/history rows).
- 3 confirmed DPS preparation tasks assigned to Sourav/Baski; 1 completed
  meeting with 2 open + 1 cancelled action items; 1 open triage item
  (email from unknown@newschool.edu.in); notifications for siva/rahul.
- One follow-up OutboundMessage marked `sent` (dry-run transport — no real
  email left the machine). DB backup from the pre-G7 era:
  `data\salesplatform.db.bak-20260717`.


## 9. Word email templates (live 28 Oct 2026)

What it is: emails written as tagged Word files, like the proposal templates.
Common emails are grouped by category (intro, meeting confirmation, after
meeting, follow-up, final follow-up, onboarding, or an admin's own), product
emails by product. Jarvis picks the template from what the person says, fills
the tags from the client's record, asks only what it must (always the
salutation, Mr., Ms. or Mrs.), and drafts the email for the usual one-tap
approval. The Word formatting is kept (the email has an HTML part). A product
email can carry the client's built proposal or MoU; if none is built, Jarvis
says so and does not send. When no template fits, Jarvis writes the email
freely, as before.

Where: app/models/email_template.py (3 new tables), app/services/
email_template_service.py, email_render.py, email_fill_service.py,
email_choice.py, app/api/email_templates.py (/admin/email-templates),
app/ai/agents/email_fill_tools.py, the email agent's new tools. The proposal
email (Jarvis) and email follow-ups use a template when one exists. Unchanged:
the business card scan intro, meeting booking and its calendar invite,
WhatsApp, the proposal screen's Approve and Send button.

Dashboard: item 7 is now "Email templates" (upload, list, default files); the
old four text templates sit in a section kept for the card scan and WhatsApp.
The checklist's item 7 needs intro/email, intro/whatsapp, follow_up/whatsapp
and at least one Word email template.

State on 28 Oct: code live (restart 05:16 UTC), tables empty; the templates
are to be uploaded from the dashboard. Design, plan and ledger:
YuvipepSalesforceAI/docs/superpowers/specs/2026-10-28-email-templates-design.md
and docs/superpowers/plans/2026-10-28-email-templates(.progress).md.
Note: Dashboard/src/api generated files were already out of date before this
work (gen:check fails); they were not regenerated.
