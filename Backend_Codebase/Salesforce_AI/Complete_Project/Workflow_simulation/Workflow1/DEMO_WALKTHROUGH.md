# YuviPep AI Sales Platform — Full App Demo Walkthrough (A → Z)

This is a **click-by-click script** for showing the whole mobile app end to end.
Follow it top to bottom. Every step is written in plain words: *open this, tap
that, play the recording, wait, show this on screen.*

The story: a brand-new client, **Orchid International School**, wants our **IBC
STEM program**. We record the **first meeting**, let the AI plan and split the
work by skill, build and send the proposal, book a demo, and chase follow-ups.
Then we record a **second meeting that changes several of those decisions**, and
show the AI updating the live plan and proposal instead of starting over.
Finally we log into the operations team's own accounts to complete the tasks the
AI assigned them.

**The three files in this folder:**
| File | What it is |
|---|---|
| `DEMO_WALKTHROUGH.md` | This script. |
| `meeting1.py` | Plays + saves the **first** meeting audio (`meeting1.wav`). |
| `meeting2.py` | Plays + saves the **second** meeting audio (`meeting2.wav`) — it *changes* things from meeting 1. |

Run a meeting script with `python meeting1.py`. It shows the script, builds the
audio the first time, waits for you to press **ENTER**, then plays it out loud so
the phone can record it. (`--no-play` = build only, `--regen` = rebuild the WAV.)

**Logins (all use password `Password@123`):**
| Person | Email | Role | Used for |
|---|---|---|---|
| Siva | `siva@yuvipep.com` | Sales Lead | The main demo driver |
| Rahul | `rahul@yuvipep.com` | Sales Agent | (optional) second salesperson |
| Mithun | `mithun@yuvipep.com` | Operations Lead | Completing assigned tasks |
| Sourav | `sourav@yuvipep.com` | Operations Agent | Completing assigned tasks |
| Baski | `baski@yuvipep.com` | Operations Agent | Completing assigned tasks |
| Shyam | `shyam@yuvipep.com` | Operations Agent | Completing assigned tasks |
| Admin | `admin@yuvipep.com` | Org Admin | (optional) the setup story |

---


2. Open the app. On the login screen, sign in as **Siva**
   (`siva@yuvipep.com` / `Password@123`).
3. You land on **Home**. Point out the greeting ("Hello, Siva") and the **My
   day** cards — this is the daily briefing pulling together his demos and
   follow-ups. Because we wiped the data, it's quiet — perfect starting point.
4. Tap the **bell / Notifications** icon to show the Notification Center is
   empty. We start from zero.

> The bottom tabs Siva sees: **Home · Leads · Jarvis · Tasks · Approvals** (plus
> **More**). We'll use every one of them.

---

## PART 3 — Create the new client (Orchid International School)

1. Tap the **Leads** tab.
2. Tap **New lead** (the + / "New lead" button).
3. In **Create lead**, enter:
   - Name: **Orchid International School**
   - City: **Pune**
   - (Leave the rest as default.) Save.

   *Alternative to show the camera feature:* instead of typing, tap **Scan
   card** and scan a real business card — the AI reads the name, title, email
   and phone off the card and fills the contact in. (Use this only if you have a
   card whose name matches the meeting; otherwise type it as above.)

4. Open the new **Orchid International School** lead. You're on the 6-tab lead
   detail (Overview, Contacts, etc.).
5. Add the school's main contact so the meeting has someone to address:
   go to **Contacts → add**, enter **Mrs. Nair, Principal**, mark **primary**.
   - **Email: `ekaghni.mukherjee@gmail.com`** ← use your own Gmail here so the
     live proposal / follow-up / demo invite actually lands in your inbox (the
     app sends from this same account, so you'll get a real email to open on
     screen). Do **not** use the `@...example.edu` sample addresses — they
     bounce.
6. Point out the **Overview** tab — the AI will fill in more (the coordinator,
   the admin officer, the trustee) automatically from the recordings. We don't
   type them; the AI discovers them.

---

## PART 4 — Record the FIRST meeting

This is the heart of the demo: *the salesperson just talks, the AI does the
rest.*

1. On the **Orchid International School** lead, tap **Record meeting**.
2. The **Recording consent** screen appears (this is the DPDP privacy gate).
   Read it aloud: *"Before recording, confirm the client agreed."* Tap **They
   agreed verbally**, then **Consent recorded — continue**.
3. The recorder is now **listening**. Turn the **laptop volume up** and hold the
   phone near the speaker.
4. On the laptop, run the first meeting:
   ```powershell
   cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project\Workflow_simulation
   python meeting1.py
   ```
   It prints the full conversation, then waits. When the phone is recording,
   press **ENTER** — it plays a ~2½ minute meeting between Siva and three people
   at the school.
5. When the audio finishes, tap **Stop** in the app. The meeting uploads and the
   **pipeline** starts.
6. Show the meeting status moving along: **uploaded → transcribing → extracting
   → review pending**. (On CPU this takes a minute or two — narrate it: *"right
   now, on-device Whisper is turning the audio into text, then the AI is pulling
   out the tasks."*)

---

## PART 5 — The review gate (human stays in charge)

1. When the meeting reaches **Review**, open **Review extracted tasks**.
2. Read the banner: *"Edit or drop anything the AI got wrong — nothing goes live
   until you confirm."* This is the point to make: **the AI proposes, the human
   approves.**
3. Scroll the extracted items — you should see things like *prepare and send the
   proposal, design the workshop curriculum, develop the materials, coordinate
   logistics and the maker kits, train facilitators / run a teacher pilot.*
4. Optionally tap one item to show you can **edit** it, and **Add an item the AI
   missed**. Then tap **Confirm … item(s)**.
5. A toast appears: *"… task(s) are live. The Planner is building the plan from
   this meeting — the project and its approvals will appear shortly."* This is
   the moment the AI turns a conversation into a real project.

---

## PART 6 — The AI plans and splits the work **by skill**

1. Wait a few seconds, then go to the **Projects** area (via **More → Projects**,
   or the project link on the lead). Open the new **Orchid International School**
   project.
2. Show the **project home**: the plan the AI wrote — phases, tasks, durations
   and dependencies. Point out this was **not a template** — it was written from
   what was actually said in the meeting.
3. Now the key "wow": open the **Confirm assignments** screen (the assignment
   batch the AI proposed). For each task the AI picked a person **by their real
   skill**, e.g.:
   - *Design the workshop curriculum* → **Baski** (curriculum design — expert)
   - *Coordinate logistics / procure the 40 kits* → **Mithun** (logistics —
     expert)
   - *Train facilitators / run the pilot* → **Mithun / Shyam** (training
     delivery — expert)
   - *Prepare the proposal* → **Siva** (proposal preparation — expert)
   Each row shows the match reason (e.g. **"expert skill match"**). Point out you
   can **Change person** if you disagree — the human still decides.
4. Tap **Confirm … assignment(s)**. The tasks are now assigned to real people
   across the sales *and* operations teams.

> Say it out loud: *"One meeting recording just became a full project plan, with
> every task handed to the right person based on their skills — automatically."*

---

## PART 7 — Ask Jarvis (the assistant) about it

Go to the **Jarvis** tab. Ask several questions in a row — this shows the
assistant understands your data, remembers the conversation, and knows what's on
screen.

Type (or use the mic — see Part 14) these, one at a time:
1. **"What tasks came out of the Orchid International School meeting?"** — it
   lists the plan.
2. **"Who is assigned to design the curriculum?"** — it names the person.
3. **"What is the most important task right now?"** — it answers by **priority**,
   not just by date.
4. **"Tell me about this client."** — open the assistant *from the lead* first so
   the **context chip** ("currently viewing Orchid International School") is set;
   the answer is now **filtered to that client**, proving the chip actually
   scopes the reply.
5. Tap the small **"Why?"** on any suggestion the app shows — it explains the AI's
   reasoning in plain words.

> The point: it's not a chatbot reading a script — it's reading *your* live data
> and staying inside your permissions.

---

## PART 8 — Build and send the proposal (with one approval tap)

1. Still in **Jarvis**, type:
   > **"Create the IBC proposal for Orchid International School — 12 workshops,
   > 40 kits, one showcase — and send it to the Principal, Mrs. Nair."**
2. The assistant drafts the proposal and shows a **Ready for approval** card
   with **Approve & send** / **Reject**. Nothing has gone out yet.
3. Tap **Open** on the card to show the **Proposal detail**:
   - The **pricing is locked** and machine-generated — point out the AI **cannot
     invent a number the client sees**; the totals come from the pricing table
     (12 × ₹2,000 workshops, 40 × ₹500 kits, 1 × ₹15,000 showcase).
   - Tap to open the **PDF** in the built-in viewer.
   - Show **Upload revision** and try uploading a tampered file — the app
     **refuses** it (the price block can't be edited outside the system).
4. Back on the approval card, tap **Approve & send**.
   - **Dry-run:** it's queued and "sent"; you can show the composed email file
     under `data/storage/orgs/<org>/outbox/`.
   - **Live:** the real email goes to the Principal (use your own Gmail address
     if you want to actually receive it).
5. Optionally show **Reject** on a second draft — with a reason box that *"helps
   the AI next time."*

---

## PART 9 — Book the pilot demo (calendar + honest invites)

1. Go back to the **Orchid International School** lead → **Overview** → **Book
   demo** (schedule the teacher pilot).
2. Pick a date and time and confirm. Show the **31-day calendar** (**More →
   Demos / Calendar**): free days, booked days with dots.
3. Try booking a **second demo that clashes** with an existing one — the app
   shows the **clash warning** honestly ("Alpha already has a demo…").
4. Point out **invite honesty**: the app tells you exactly what it did — the
   invite is drafted and waiting for approval, or (live) an ICS invitation with
   an RSVP card was emailed. Nothing is faked.
5. **Reschedule** the demo to another day — show the date flips and a fresh
   updated-invite is drafted.

---

## PART 10 — Follow-ups (the AI writes the chase)

1. Go to **More → Follow-ups** (the Follow-up queue).
2. Show the due items with their **due chips**; flip the **Mine** switch to see
   just Siva's.
3. On one follow-up, tap **AI draft message** — the assistant writes a warm,
   on-brand chase. You approve to send (or it waits in approvals).
4. Tap **Complete** — the next reminder is auto-scheduled and the queue moves to
   the next item.

---

## PART 11 — The Approvals inbox

1. Tap the **Approvals** tab. Show every client-bound message sitting in
   **pending approval** — the proposal email, the follow-up, the demo invite.
2. Open one to see the **draft preview** exactly as the client will get it.
3. Show the two buttons: **Approve** (queued → sent, paced and retried in the
   background — never silent) and **Reject**.
4. Turn off Wi-Fi/data for a second, tap **Approve** — the decision is **queued
   offline** and drains automatically when the connection is back. (Turn the
   connection back on.)

---

## PART 12 — Record the SECOND meeting (the AI updates everything)

Now the highlight: the client **changes their mind**, and we prove the AI
updates the live plan and proposal instead of starting over.

1. Open the **Orchid International School** lead → **Record meeting** again →
   confirm consent → the recorder is listening.
2. On the laptop, run the second meeting:
   ```powershell
   cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project\Workflow_simulation
   python meeting2.py
   ```
   Press **ENTER** when recording; let it play; tap **Stop**.
3. Wait for the pipeline, then open **Review extracted tasks** again. This time
   the AI has understood **changes to an existing plan**, not a brand-new one.
   Note the **⚠ possible-duplicate hints** where it recognises tasks that already
   exist. Confirm the review.
4. Open the **project** and show what the AI did (this is the payoff — call each
   one out):
   - **Workshops 12 → 16:** the plan quantity updated, and it flagged the
     **conflict** with the first meeting ("meeting 1 said 12, meeting 2 says
     16").
   - **Printed kits cancelled:** the kit-procurement task is **removed /
     cancelled** (materials went digital).
   - **New two-day teacher training:** brand-new tasks were **added** (a scope
     addition), and assigned by skill to training-delivery people.
   - **Start date 15 Aug → 1 Aug:** the dates **moved**, and dependent tasks
     shifted with it.
   - **New person — Trustee Mr. Rao:** the AI **added him as a stakeholder** on
     its own (you never typed him) — check the **Contacts / Stakeholders** on the
     lead; he's marked as the budget approver.
5. Show the **plan history / versions** (project → plans) so the audience sees
   the plan went from **v1 → v2** — *"nothing half-applies; it's a clean new
   version."*

---

## PART 13 — Revise the proposal (price changes, new CC)

1. Go to **Jarvis** and type:
   > **"Update the Orchid proposal to 16 workshops, remove the kits, and add the
   > trustee Mr. Rao in copy."**
2. Open the redrafted **Proposal detail**:
   - The **total went up** (16 × ₹2,000 workshops; the kit line is gone) — and
     again, the numbers came from the **pricing table**, not the AI.
   - **Mr. Rao is now CC'd** — because the second meeting told the AI he approves
     the budget, and engines act on **influence** (the decision-maker gets the
     money copy).
3. **Approve & send** the revised proposal.

> Say it: *"The client changed five things by voice, and the plan, the tasks, the
> people, the dates and the price all updated — with the human approving each
> outgoing message."*

---

## PART 14 — Talk to Jarvis by voice

1. In the **Jarvis** tab, tap the **mic**. Speak a command out loud, e.g.
   *"What's the most important task for Orchid International School?"* — your
   words appear live and auto-send.
2. Turn on **Speak replies** so Jarvis reads the answer back to you.
3. Show the mic is in **every dialog field too** (e.g. dictate a rejection note)
   — the whole app is voice-friendly, not just the assistant.

---

## PART 15 — Log in as the OPERATIONS team and finish the work

This proves the assignments in Part 6/12 landed on real people, who log in and
do the work.

1. **Sign out** of Siva. Sign in as **Mithun** (`mithun@yuvipep.com`).
2. Tap the **Tasks** tab (**My Tasks**). Mithun sees exactly the tasks the AI
   assigned **him** (logistics, training) — and *not* other people's.
3. Open a task (**Task detail**) and walk the lifecycle buttons:
   - **Start / Complete** a task → it turns green, and the person who owns the
     project is notified.
   - **Decline** a task with a dictated reason → it goes back for reassignment.
   - **Split** a big task into smaller ones.
   - Change a task's **date** and show the **ripple** on the dependent tasks.
4. Sign out and sign in as **Baski** (`baski@yuvipep.com`) → **Tasks** → show
   Baski has the **curriculum design** task (his expert skill). Complete it.
5. Repeat briefly with **Sourav** and **Shyam** to show the whole team is busy —
   each person only sees and completes their own assigned slice.
6. Sign back in as **Siva** and open the project — the tasks the ops team just
   completed now show as **done**, and Siva got **notifications** about them.

> This is the "distribution of tasks by skill, and each person logging in to
> complete them" story, shown end to end.

---

## PART 16 — (Optional) Two salespeople, one shared client

1. Sign in as **Rahul** (`rahul@yuvipep.com`, another salesperson).
2. Open **Leads → Orchid International School**. Rahul sees the **same** proposal,
   project and tasks Siva created — the client record is shared across the sales
   team.
3. Point out **My Tasks** still only shows each person their **own** assigned
   work — shared visibility, personal to-do lists.

---

## PART 17 — Wrap up: what we just showed

Read this back as the closing summary:

- A salesperson **just talked** — the AI **transcribed** the meeting on-device,
  **pulled out the tasks**, and **wrote a full project plan** from scratch.
- The AI **split the work across the whole team by real skill**, and each person
  **logged in and completed their own tasks**.
- It **wrote and (with one tap) sent** the proposal — with **prices it can never
  invent** — booked a **demo with honest calendar invites**, and **drafted the
  follow-ups**.
- When the client **changed five things in a second meeting**, the AI **updated
  the live plan** — new quantity, a cancelled task, a new scope, moved dates, and
  a **new stakeholder it discovered by itself** — and **revised the proposal and
  its price**, all versioned, with the human approving every outgoing message.
- Everything is **voice-driven, offline-safe, permission-scoped, and audited.**

---

### Quick reference — running the meetings
```powershell
cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project\Workflow_simulation
python meeting1.py          # first meeting (press ENTER to play)
python meeting2.py          # second meeting (the changes)
python meeting1.py --regen  # rebuild the WAV (e.g. after editing the script)
python meeting1.py --no-play  # build the audio only
```

### If something goes wrong
- **App can't reach the backend:** re-run the `adb reverse tcp:8000 tcp:8000`
  line; confirm `run.py` is still running.
- **Transcription is slow:** normal on CPU with `WHISPER_MODEL=medium`; set
  `WHISPER_MODEL=small` in `.env` and restart for a faster (slightly less
  accurate) demo.
- **Transcript got a name/number wrong:** play the meeting in a quieter room
  with the volume up and the phone closer to the speaker, then re-record. The
  scripts read numbers and names slowly on purpose.
- **A stale offline banner won't clear:** it's a known cosmetic issue — pull to
  refresh or reopen the screen; the backend is still online.
- **You want a totally clean run again:** repeat **Part 0**.
