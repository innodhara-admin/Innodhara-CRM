# 05 — Role-Based Experiences (mirrors `app/core/permissions.py` exactly)

The app is one APK whose navigation, bottom bar, quick actions and
suggested assistant commands are assembled at login from `/auth/me`.
The server enforces; the app *shapes*.

## 1. Permission matrix mirrored client-side (RoleGate)

| Permission | org_admin | sales_lead | sales_agent | ops_lead | ops_agent |
|---|---|---|---|---|---|
| record_meeting / send_proposal / manage_leads / send_messages | ✅ | ✅ | ✅ | — | — |
| view_leads / view_demos / manage_tasks | ✅ | ✅ | ✅ | ✅ | ✅ |
| schedule_demos | ✅ | ✅ | — | ✅ | — |
| update_demo_status | ✅ | — | — | ✅ | ✅ |
| edit_pricing / manage_programs / manage_templates / manage_staff / manage_settings / view_audit / erase_personal_data | ✅ | — | — | — | — |
| manage_teams | ✅ | — | — | ✅ | — |
| create_organisation / platform_stats | super_admin only (platform flavor) |

Task reassignment scope (matches `can_reassign_task`): agent = own tasks;
leads = their team; admin = all. The UI hides reassign controls
accordingly and explains when hidden.

## 2. sales_agent — "the hunter's cockpit"

- Bottom bar: **Home · Leads · Mic · Tasks · Inbox**.
- Home emphasis: today's meetings & demos, follow-ups due, my approvals
  (proposals I must fix after rejection), overnight replies from *my*
  leads.
- Quick actions: Record meeting · Scan card · New lead · Log reply.
- Sees: own + team leads (view), own tasks, own proposals/messages.
- Assistant suggestions: selling verbs.

## 3. sales_lead — "the pipeline commander"

- Bottom bar: **Home · Pipeline · Mic · Approvals · Team**.
- Home emphasis: **Waiting-on-you** (message/proposal approvals,
  assignment confirmations, conflicts raised to them, escalation cards
  when ladders hit level 3), pipeline deltas, at-risk projects.
- Pipeline: leads by state + projects by health; drill into any member's
  view. Team: load bars (open tasks vs max), leave, declines pattern
  (from assignments history), skills matrix (read; edit levels).
- Approvals default filter: stage=decide.
- Assistant: "who's overloaded?", "confirm assignments", "why is SVS at
  risk?".

## 4. operations_agent — "the doer"

- Bottom bar: **Home · Tasks · Mic · Projects · More**.
- Home: today's delivery runsheet (delivery-day tasks in order), blocked
  items I own, vendor waits I chase, incident fix-tasks assigned to me.
- Can update demo status (ran the demo), complete/decline/block tasks,
  upload deliverables/photos, report on-site problems → incident.
- Assistant: "what's my runsheet?", "flag 4 dead laptops in the lab"
  (creates incident report), "mark day-1 photos uploaded".

## 5. operations_lead — "mission control"

- Bottom bar: **Home · Delivery · Mic · Incidents · Team**.
- Home: delivery-phase projects board (health-first), incidents (P1
  pinned), vendor promises approaching, assignment confirmations for
  prep/delivery phases, leave impacts.
- Delivery board: per-project prep checklist state, kit/vendor waits,
  demo teams calendar; phase-shift button (agreed → preparation).
- Incidents: full lifecycle incl. resolve-with-lesson (feeds playbooks).
- Manage teams (demo-teams), bookings; schedule demos.

## 6. org_admin — "the org's control room"

- Bottom bar: **Home · Approvals · Mic · Admin · Insights**.
- Everything the leads see, plus the Admin area (staff, programs,
  pricing, templates, settings, integrations, approval rules, playbooks,
  audit, privacy) and Insights dashboards (pipeline funnel, health mix,
  invoice aging, LLM budget burn from llm_usage-backed stats where
  exposed, audit highlights).
- Onboarding wizard on first run of a fresh org: create staff → programs
  → pricing → templates → integrations → settings dials — matching the
  backend's "no code changes to onboard" promise (X7).

## 7. super_admin — platform flavor

- Separate flavor/launcher ("YuviPep Platform").
- Screens: Orgs (list/create/deactivate; temp password shown once with
  copy button), Platform stats. Nothing else — and an explicit statement
  that org data is invisible to platform operators (matches backend
  guarantee).

## 7b. Who reaches the Inbox (decided 2026-07-29, when Phase 6 shipped)

Only the **sales agent** has an Inbox slot in the bottom bar, exactly as §2 specifies. The
bars above were **not** redesigned to add one. Every other role reaches the Inbox from the
Home "N inbound messages need a human" card, from a notification deep link
(`inbound_message`), or from `MainActivity.openInbox()` — pushed on top of their current
screen with a back arrow.

Two rules the Inbox enforces, both from §7 rule 3 (no empty screens, no dead ends):
- `GET /messages` requires `send_messages` (sales_agent / sales_lead / org_admin). A role
  without it gets the triage queue **with no tab strip at all**, never a Messages tab that
  would 403.
- Replying produces an outbound message, which also needs `send_messages` — so ops roles
  see **no Reply button**. They can still triage: attach, classify, mark handled, and log a
  client reply (`/inbound/ingest` needs no permission).

## 8. Cross-role rules

- Unknown/new role string from backend → generic "member" experience
  (Home + Tasks + Assistant) rather than a crash — forward-compatible
  with §13.1 finer roles.
- Role changes take effect on next `/auth/me` (login or resume refresh):
  graphs rebuilt, caches kept (server filters anyway).
- Every hidden capability has a discoverable explanation ("Your role
  can't edit pricing — ask your org admin") the first time its natural
  place is visited.
