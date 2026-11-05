# Four asks from 21 September 2026 — what the code does today

**Status, 23 September 2026 (later the same day): all four are built** —
backend and Android, with tests; see
`docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md` §12 for what was built and
how the open questions at the end were answered. What follows is the research
as it was written before building, kept for its file map, with corrections
marked where it turned out to be wrong.

Written 23 September 2026 by reading the backend on the VM and the Android app
on the developer's PC, so that the next session starts from facts rather than
from a search.

Each section says what exists, what is missing, and where a change would land.
Design choices are left open where they are the customer's call.

---

## 1. A task on the dashboard does not name its client

> **Built 23 Sep 2026** — the Home briefing names each task's client as a
> link to it, and the Tasks tab card has a tappable client chip (§12.1).

**Asked:** show the client ("ABC School") on the task, and tapping it should
open that client.

**Backend — already done.** `GET /api/v1/action-items` returns `lead_id` and
`school` (the lead's name) for every row; `app/api/action_items.py::_item_dict`
joins the lead and puts the name in. The Android DTO already carries both:
`TaskDto.leadId` and `TaskDto.leadName` (`@SerializedName("school")`).

**Android — where it actually shows.**

- `feature/tasks/MyTasksAdapter.bind` puts `projectName` in the meta line, and
  falls back to `leadName` only when there is no project. A task that came out
  of a meeting usually HAS a project, so the school is the one thing missing.
- The card's tap opens `TaskDetailFragment` (`onOpenTask`), never the lead.
- The home screen (`feature/home/HomeFragment`) lists no tasks at all: it shows
  approvals, a demos card, a follow-ups card, the daily briefing
  (`GET /digests/daily`, markdown only) and the assignment / review / triage /
  recently-opened cards. So "dashboard tasks" means either the **Tasks tab**
  (`MyTasksFragment`) or the briefing text.

**The work is app-side**: show the school even when a project exists, and give
a way into the lead. Question for the customer: the row opens the task today,
so should the school be a separate tappable chip, or should the row itself go
to the lead?

---

## 2. A meeting path of its own, separate from demos

> **Built 23 Sep 2026** — `ScheduledMeeting`, invite in Approvals with
> to/cc/bcc, redraft on reject, recordings, Jarvis and voice (§12.4).

The biggest of the four. Today **"schedule something with a client" always
means a demo**, and a demo carries a demo team.

| piece | where | notes |
|---|---|---|
| `Demo` model | `app/models/demo.py` | lead, **team_id**, `scheduled_date` (a DATE), `scheduled_time` (a string, "10:30"), status, `calendar_event_id` |
| Endpoints | `app/api/demos.py` | `GET /demos`, `GET /demos/calendar`, `POST /demos`, `PATCH /demos/{id}` |
| Invite email | `app/services/demo_invite_service.py::compose_demo_invite` | drafts an `OutboundMessage` in `pending_approval` with the ICS attachment and the Meet link; returns None when the lead has no contact with an email |
| ICS + HTML | `app/services/ics_service.py` | `build_invite`, `build_invite_html` |
| Calendar | `app/services/calendar_service.py` | real Google Calendar through a service account when `CALENDAR_MODE=google` (it is, live). `create_event` / `delete_event` |
| Meet link | org settings `calendar_integration.meet_link`, else `GOOGLE_MEET_LINK` | **one reusable room** (the live value is a single fixed link). Nothing creates a per-meeting link: `create_event` sends no `conferenceData` |
| Jarvis | `app/ai/agents/scheduling_agent.py` | tools `list_demos`, `list_demo_teams`, `calendar_view`, `book_demo`, `cancel_demo`. `book_demo` needs the `schedule_demos` permission: **Operations Lead, Sales Lead, Org Admin only** — a sales agent cannot book one |
| From a recording | `app/engines/planner_engine.py` | the Planner can `reschedule_demo` on activation and re-drafts the invite |
| Meeting extraction | `app/ai/extraction.py::analyse_meeting` | already returns `due_hint` and a resolved `due_date` per action item (verified 21 Sep: "we decided to meet on 27th of September … at 9am" gave `2026-09-27` on every item). It returns **no time of day**, and there is no "a meeting was agreed" signal at all |

**What is missing for the ask:**

1. **A meeting that is not a demo.** Either a new model (`ScheduledMeeting`:
   lead, start datetime, attendees, link, `calendar_event_id`, status) or a
   `kind` column on `Demo` with `team_id` made optional. Remember the house
   rules: a new table needs a bucket in `app/core/reset_taxonomy.py` (and the
   hard-coded counts in `tests/test_reset_taxonomy.py` updated); a new column
   needs an idempotent `ALTER` in `_apply_light_migrations` — there is no
   Alembic. Name clash to avoid: `Meeting` already means **a recording**.
2. **A meeting signal out of a recording.** `analyse_meeting` would have to
   return the agreed meeting (date, time, who), and the review/confirm step
   show it. Today a promise to meet becomes an action item and nothing else.
3. **Time of day.** `Demo.scheduled_time` is a free string and extraction gives
   a date only. An invite needs a real start time and a duration.
4. **A redraft-on-reject loop.** *Correction (23 Sep, while building): a loop
   does exist — rejecting from the Approvals inbox runs
   `approval_engine._apply_rejected` → `communication_engine.redraft_rejected`,
   which redrafts with the note as instruction and files a new approval. Only
   the direct route below does not. It copies the old attachments, though,
   which is wrong for an invite (old time, old text in the HTML part), so
   meeting invites got their own branch. The original text follows.*
   `app/services/message_service.py::reject_message` sets the message to
   `rejected`, logs the reason and closes the approval. Nothing re-drafts. The
   ask (reject with a reason, redraft from that reason, back to approvals) is
   new machinery: the reason must reach the drafting prompt and produce a new
   pending-approval message linked to the same meeting.
5. **A Jarvis tool for it**, so "schedule a meeting with X on Friday at 11"
   stops landing on `book_demo`. Voice mode needs no separate work — it runs
   the same orchestrator, so a new tool is available there the moment it
   exists — but the router prompt (`app/ai/orchestrator.py`) must learn the
   difference between a demo and a meeting, and the follow-up questions for
   missing details ("who should be on it?") must work in one turn.
6. **Per-meeting Meet links**, if the customer wants a fresh room each time:
   that is a Google Calendar `conferenceData` request with
   `conferenceDataVersion=1`, and the service account must be allowed to make
   one. Worth checking whether the single fixed room is genuinely a problem.

---

## 3. "Blocked, waiting on Siva" never reaches Siva

> **Built 23 Sep 2026** — the colleague is found in the reason, notified, and
> sees a card on Home until it is unblocked (§12.3).

**Asked:** when a task is blocked on a colleague, that colleague should see it.

**What happens today** (`app/api/workflow.py::block_task`): `blocked = True`, a
free-text `blocked_reason`, reminders cancelled, a `task_blocked` event
emitted. `app/engines/sync_engine.py::_on_task_blocked` then recomputes project
health and — **only when the reason contains "school", "client" or "approval"**
— drafts a chase message to a client stakeholder.

**Nothing happens when the blocker is a colleague.** The reason is never parsed
for a person, no notification is written, no task is raised for them, and the
home screen has no "someone is waiting on you" surface. The blocked task
appears on Siva's **Projects** screen only because `app/api/projects.py`
returns `blocked` and `blocked_reason` with the task rows.

**Where a fix would land:** `_on_task_blocked` (resolve a named colleague, then
notify and/or raise something they can act on), plus a surface on Home in the
app. Open question: a notification, a card on Home, or a real task assigned to
the blocker? The customer asked for the path to be clearer, so the shape is
theirs to choose.

---

## 4. Upload a recording file from the Recording tab

> **Built 23 Sep 2026** — "Choose a recording file" on the recorder screen,
> behind the same consent sheet (§12.2).

**Backend — already supports it.** `POST /api/v1/meetings/upload` takes any
`UploadFile` up to **200 MB** (`_MAX_AUDIO_BYTES`), stores
`audio_mime = file.content_type`, and the pipeline decodes with ffmpeg, so
mp3 / m4a / aac / mp4 / wav / ogg all work. Two conditions the screen must
respect: `consent_confirmed` must be true **and** a `ConsentRecord` for that
lead must exist from the last 24 hours (`_CONSENT_MAX_AGE`);
`duration_seconds` is a form field the server trusts.

**Android — the work.** `feature/meetings/RecorderFragment` records through
`RecorderService` and hands the finished file to
`UploadMeetingWorker.enqueue(context, filePath, leadId, title, seconds, catchUpType)`.
A "choose a file" button would: open the system picker
(`ACTION_OPEN_DOCUMENT`, `audio/*` and `video/*`), copy the picked content URI
into the app's cache as a real file (the worker needs a path), read the length
with `MediaMetadataRetriever` for `duration_seconds`, then call the same
worker. The consent sheet that runs before the recorder must also run for an
upload, and it is worth asking what consent means for a recording made earlier
on another device.

---

## To confirm with the customer before building item 2

> **Answered 23 Sep 2026:** its own record; one shared Meet room for now;
> anyone who can see clients may schedule; redraft automatically from the
> reason.

1. Does a meeting need its own record and screen, or is it a demo without a
   team? (Decides model vs column, and how the calendar shows it.)
2. One shared Meet room, or a fresh link per meeting?
3. Who may schedule a meeting? Demos are Ops Lead / Sales Lead / Org Admin, so
   a sales agent arranging their own visit is refused today.
4. On reject: redraft automatically from the reason, or let the person edit the
   draft themselves? The second is far less machinery.
