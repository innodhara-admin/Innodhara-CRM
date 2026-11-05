# Pre-Sales: lead ownership, cold calling, gated tabs and a state timeline

**Date:** 2026-08-28
**Status:** approved for planning
**Touches:** backend (`Complete_Project`) and the Android app (`YuvipepSalesforceAI`)

## 1. Why

Today a lead enters the system already qualified. `POST /leads` creates it
directly in `open`, and the app immediately offers meetings, projects,
proposals — the full lifecycle. Real sales does not start there. Before any
of that, somebody is handed a name and a phone number and has to find out
whether there is anything worth pursuing.

That step is missing. This spec adds it: a lead is created, assigned to a
named sales agent, and sits in a new `cold_calling` state until that agent
has actually spoken to the school and judged the response. Only then does it
become `open` and the existing flow begins, untouched.

## 2. Scope

In scope:

- A new `cold_calling` lead state, entered by `POST /leads`.
- Owner assignment at creation (single and bulk), from a dropdown of sales agents.
- Owner-only transition out of `cold_calling`.
- Notification to the owner on assignment; fan-out to the sales team on open.
- A home-screen card announcing newly opened leads, for a configurable window.
- Locking Projects and Meetings while a lead is in `cold_calling`.
- A state timeline under the lead header.

Explicitly out of scope:

- Any change to lead behaviour from `open` onward. Permissions, transitions,
  AI suggestions and the meeting flow stay exactly as they are.
- Backfilling existing leads. Every lead currently in the database stays in
  the state it is in.
- A backend bulk-upload endpoint. Bulk upload is an Android-side loop over
  `POST /leads` and remains so.

## 3. The flow

1. Siva (sales lead) creates "XYZ School" and picks Priya (sales agent) as owner.
2. The lead is created in `cold_calling`. Priya is notified.
3. Priya opens the lead. Overview, Contacts, Notebook and History work
   normally. Projects and Meetings are locked, naming her as the owner.
4. Priya calls the school outside the app. It goes well.
5. Priya moves the lead to `open` and logs why. Nobody else can make this move.
6. Every sales agent and sales lead is notified, and the lead appears on their
   home screen for `lead_open_feed_days` (default 3).
7. Someone records a meeting. The existing `open -> active` suggestion fires,
   a human confirms it, the home card disappears and the usual flow proceeds.

If the calls go nowhere, Priya moves it to `lost_for_now` instead — the
existing bucket for "did not work out", which already carries revival
machinery (`lost_reason`, `revival_date`, `revival_context`).

## 4. What already exists

Verified by reading the code, not the docs:

- `Lead.owner_id` — a real FK to `users.id`, already indexed
  (`ix_leads_org_owner`). `POST /leads` already accepts `owner_id` and falls
  back to the creator.
- `LeadStateHistory` — `from_state`, `to_state`, `reason`, `changed_by`,
  `changed_at`. Already written on create and on every transition.
- `GET /leads/{id}` already returns `state_history` (latest 20).
- `lead_service.change_state()` — validates against `LEAD_STATE_TRANSITIONS`,
  writes history, records an audit row.
- `notification_service.notify()` — writes a `Notification` row and
  fire-and-forget FCM push. Already wired to the Android notifications screen.
- Bulk lead upload exists in Android (`BulkLeadImporter.java`), looping
  `POST /leads` per row.

## 5. What does not exist

- Any `cold_calling` state. The enum is `open, active, cold,
  execution_in_progress, client_execution_in_progress, closed, lost_for_now`.
- Any ownership check on state changes. `manage_leads` is granted to
  `SALES_AGENT`, so today any sales agent can move any lead to any state.
- Any endpoint a sales lead can call to list agents. `GET /admin/users`
  requires `manage_staff`, which is `ORG_ADMIN` only.
- Any notification keyed on `owner_id`. The field is set and never used.
- Owner *name* anywhere in a response. `_lead_dict` returns `owner_id` alone.
- An owner control in `NewLeadSheet`, or an owner field in the bulk schema.

## 6. Naming hazard

`cold` already exists and means the opposite end of the lifecycle: a lead
that has gone quiet for 30+ days. `cold_calling` means a lead nobody has
reached yet. They are unrelated and must not be conflated.

Concretely, `sync_engine.py:1278` suggests `cold` for any lead silent past
the org threshold whose state is `open` or `active`. `cold_calling` is not in
that set, so the sweep already ignores it — but only by accident of the
current condition. A test will pin that behaviour so a future edit to the
condition cannot quietly capture cold-calling leads.

## 7. Data model

No new columns on `leads`. Ownership is already modelled, and "when was this
opened" is recoverable from the `LeadStateHistory` row with
`from_state='cold_calling', to_state='open'`.

One new column:

```
org_settings.lead_open_feed_days : int, default 3
```

**Migration mechanics.** This project has no Alembic. `init_db()` calls
`Base.metadata.create_all`, which creates missing *tables* but never adds
columns to an existing one. The new setting therefore needs an explicit
idempotent `ALTER TABLE` inside `_apply_light_migrations()`
(`app/database.py:60`), alongside the existing entries there. Without it the
column appears on a fresh database and is silently missing on the live one.

## 8. State machine

```python
class LeadState(str, Enum):
    COLD_CALLING = "cold_calling"   # new — pre-sales entry
    OPEN = "open"
    # ... unchanged

LEAD_STATE_TRANSITIONS = {
    LeadState.COLD_CALLING: {LeadState.OPEN, LeadState.LOST_FOR_NOW},  # new
    # every other entry unchanged
}
```

`Lead.state`'s model-level default stays `open`. Only `POST /leads` enters
`cold_calling` explicitly. This keeps three other creation paths untouched:

- `app/api/projects.py:607` (chain deals) sets `state="active"` deliberately —
  a branch of a won deal has no pre-sales step.
- `scripts/seed_demo.py` and `scripts/seed_workflows.py` build fixtures in
  whatever state the scenario needs.

## 9. Permissions

A new helper in `app/core/permissions.py`, beside `can_reassign_task`:

```python
def can_leave_cold_calling(role: str, actor_id: str, owner_id: str | None) -> bool:
    if role == Role.ORG_ADMIN.value:
        return True          # break-glass
    return owner_id is not None and owner_id == actor_id
```

Enforced in the `PATCH /leads/{id}/state` endpoint, **not** in
`lead_service.change_state`. The service is called by AI engines and
background jobs acting as the system, which have no `actor_id` and must not
be subject to an ownership rule.

A stranded lead is not a risk: `PATCH /leads/{id}` already lets anyone with
`manage_leads` reassign `owner_id`, so if the owner leaves, a sales lead
reassigns and the new owner opens it.

## 10. API

| Endpoint | Change |
|---|---|
| `POST /leads` | Creates in `cold_calling`. History row reason reads `"Assigned to {owner} by {creator}"`. Notifies the owner. `owner_id` still optional, still falls back to the creator. |
| `GET /leads/assignable-owners` | **New.** `sales_agent` users in the org, guarded by `manage_leads` so a sales lead can call it. |
| `GET /leads/{id}` | Adds `owner_name`. Each `state_history` row gains `by` (resolved actor name). |
| `GET /leads/recently-opened` | **New.** Leads in `open` whose `cold_calling -> open` transition is within `lead_open_feed_days`. |
| `PATCH /leads/{id}/state` | Applies §9 when the lead is in `cold_calling`. Unchanged otherwise. |
| `POST /meetings` (upload, schedule, notes) | Refuses when the lead is `cold_calling`, naming the owner in the message. |

**As built:** project creation is NOT gated in the backend. No endpoint
creates a project from a lead — projects descend from won proposals, which
require meetings, so a cold-calling lead cannot reach one and the guard would
have been dead code. Projects are gated in the app only.

The meeting refusal cannot affect existing data: no lead is currently
in `cold_calling`, and none ever enters it except through the new path.

## 11. Notifications

Two new `notify()` calls, using the existing service unchanged.

- `kind="lead_assigned"` — to the owner only, on creation.
  *"You own XYZ School — start cold calling"*
- `kind="lead_opened"` — to every `sales_agent` and `sales_lead` in the org,
  on the `cold_calling -> open` transition.
  *"XYZ School is now open — Priya: 'Good response from the school'"*

Fan-out is a plain loop. Org populations are in the tens; no batching needed.

## 12. Home feed

A new card section in `HomeFragment`, fed by `GET /leads/recently-opened`.
Visible while the lead is `open` and inside the window; gone as soon as it
leaves `open` or is dropped, whichever comes first.

This goes in the structured "waiting on you" feed, not the daily digest. The
digest is a markdown blob (`content_md`) rendered as text, so a card placed
there could not be tapped through to the lead.

## 13. Android

**Owner dropdown.** `NewLeadSheet` gains a `MaterialAutoCompleteTextView`
populated from `assignable-owners`. `BulkLeadImport.Lead` gains an `owner`
field resolved against `assignable-owners`: matched on email first (exact,
case-insensitive), falling back to an exact case-insensitive full-name match.
An owner string that matches nothing, or matches more than one agent, fails
that row with a named error rather than silently defaulting — the importer
already reports per-row failures. Rows with no `owner` field at all fall back
to the creator, as today.

**Tab gating.** In `LeadDetailFragment.renderTab()`, when `state ==
cold_calling`, `TAB_PROJECTS` and `TAB_MEETINGS` render a locked panel naming
the owner. Overview, Contacts, Notebook and History are untouched.

Tabs stay visible and tappable rather than being hidden, following the
principle already stated in this file for the Book-demo button: *"the button
is discoverable for every role; roles without schedule_demos get the honest
explanation instead of a hidden capability (05 §8)"*.

**Timeline.** A horizontally scrollable stepper under the header:

```
  ●━━━━━━━━●━━━━━━━━◉ ─ ─ ─ ─ ○
  Assigned  Cold      Open      Active
  to Priya  calling   2h ago
  by Siva   3d        "Good response"
  28 Aug
```

Filled `●` completed, `◉` current, dashed `○` the expected next state.
Rendered from `state_history` plus a synthetic first node for the assignment.
Built as a `HorizontalScrollView` with programmatic child views — no custom
drawables, no new dependency.

`LeadStates.ALL` and `LeadStates.color()` gain `cold_calling`, with a new
colour in `res/values/colors.xml` and `values-night`. `LeadStates.label()`
already humanises unknown states generically, so it needs no change.

## 14. Testing

Baseline before any change: **331 passed, 4 failed**. The four failures
(`test_what_is_late` x3, `test_demos_followups` x1) are date-sensitive and
pre-existing. The suite must end at 331+n passed with those same 4 failing.

New tests:

- A lead created via `POST /leads` starts in `cold_calling`.
- The owner can move `cold_calling -> open`; the transition is recorded with
  the reason.
- A non-owner sales agent is refused.
- A sales lead who is not the owner is refused.
- An org admin is allowed (break-glass).
- `cold_calling -> lost_for_now` works for the owner; `-> active` is refused
  as an illegal transition.
- The silence sweep never suggests `cold` for a `cold_calling` lead.
- A lead already in `open` still moves to `active` exactly as before —
  the regression guard for "nothing after open changed".
- `POST /meetings` is refused for a `cold_calling` lead.
- `assignable-owners` returns agents only, and is callable by a sales lead.

## 14a. Verified end to end

Beyond the suite, the flow was walked against a running server (a throwaway
copy of the live database, separate port, live service untouched), using the
org's real people:

1. Siva's owner picker returned 3 sales agents and no sales lead.
2. Creating "XYZ School" with Priya as owner produced state `cold_calling`.
3. Priya received `lead_assigned`; nobody else did.
4. Booking a meeting was refused, naming her.
5. Rahul (another agent) was refused with 403.
6. Siva, who assigned it, was also refused — ownership beats seniority here.
7. Priya opened it with a reason; state became `open`.
8. Rahul and Siva both received `lead_opened` carrying her words.
9. The lead appeared on `recently-opened` with owner and reason.
10. Booking a meeting then returned 200.
11. The timeline read: `(new) -> cold_calling by Siva` /
    `cold_calling -> open by Priya Nair`.
12. Every pre-existing lead was still in its original state.

## 15. Risks

| Risk | Mitigation |
|---|---|
| `cold` / `cold_calling` confusion in future edits | §6, pinned by test |
| New column silently missing on the live DB | Explicit `ALTER TABLE` in `_apply_light_migrations`, §7 |
| Ownership check leaking onto system-driven transitions | Enforced at the endpoint, never in the service, §9 |
| Owner leaves, lead stranded in `cold_calling` | Owner reassignment already exists, §9 |
| Change tangled with 53 pre-existing uncommitted files | Work on `feature/pre-sales-cold-calling`; those files are left untouched and uncommitted |

Full backup taken before any work:
`/home/telaverge/Ekaghni/Salesforce_AI_Project_BACKUP_20260828_192219.tar.gz`
(3.2 GB, verified exit 0).
