# Datacentre Demo — click-by-click

**Client:** Meridian Data Centres · **Work:** commissioning 2 halls → 3 halls
**Full run:** ~75 min · **Short path (⚡ only):** ~25 min

Thirteen parts (0–12), in the order the work actually happens. Every screen in the app is
touched at least once. The **coverage checklist** after Part 12 lists every feature with the
step that proves it — tick as you go, and anything unticked is something the demo missed.

⚡ marks the **short path**: Parts 0 → 1.1–1.5 → 2 → 3.1–3.2 → 4.1–4.3 → 5 → 6.1 → 8.2 →
9 → 10.1, 10.3–10.4 → 11 → 12.3.

---

# PART 0 · Before your manager walks in

## 0.1 Reset the data

```powershell
cd C:\Users\Ekaghni\Downloads\Salesforce_AI\Complete_Project
python scripts/reset_for_datacentre_demo.py
```

> ### ✅ Already done — the DB was reset on 2026-08-06 at 14:03
>
> **leads 0 · projects 0 · tasks 0 · approvals 0 · notifications 0.** Kept: the org,
> **14 logins**, **45 `user_skills` rows**, 16 approval rules, and the datacentre catalogue
> (3 programs · 3 pricing tables · 3 proposal templates · playbooks · demo team · RackLine).
>
> **You only need to re-run it if you rehearse.** A rehearsal leaves a Meridian lead behind,
> and then step 1.3 hits a duplicate client. It is re-runnable and always keeps logins + skills.
>
> Deletes everything else, **including approvals and sent-message history**. Backups:
> `data/_backup_before_demo_reset_20260806-140255.db` (the state just before this reset) and
> `data/_backup_round7_evidence_20260806-101259/` (Round 7's evidence).
>
> ⚠ **Restart the backend after any reset** — it was running against the old database.

## 0.2 Start the backend — LIVE mail and calendar

```powershell
$env:PORT="9010"          # NO EMAIL_MODE / CALENDAR_MODE override — .env applies
python run.py
```

→ Wait for **`Platform ready`**
→ `curl http://127.0.0.1:9010/health` → `{"status":"ok"...}`

⛔ **Real mail leaves. Real Google events appear.** Never set `INBOUND_EMAIL_MODE` (F35).

## 0.3 Expose the backend — cloudflared tunnel

The phone no longer has to be plugged into this laptop. The tunnel puts the backend on the
public internet over HTTPS, so **any phone anywhere** can reach it.

```powershell
cloudflared tunnel --url http://127.0.0.1:9010
```

→ It prints a banner containing a line of the shape
`https://<four-random-words>.trycloudflare.com`
→ **Copy that URL.** That is the only thing anyone needs.

→ Verify it before you trust it — from the laptop is fine, it goes out to the internet
and back:
```powershell
curl https://<your-url>.trycloudflare.com/health      # -> {"status":"ok"...}
```

> ### ⚠ Never write this URL down anywhere. Read it fresh, every time.
>
> A **quick tunnel** mints a **new random hostname on every start**, and the old one dies
> instantly. Any URL recorded in a document, a chat message or a build file is stale the
> moment `cloudflared` restarts. This document deliberately does not name one.
>
> - **Leave the cloudflared window open for the whole demo.** Closing it kills the app's
>   connection mid-sentence.
> - **It can also drop by itself.** Watch for `Serve tunnel error` / `Retrying connection`
>   in its output — that means the URL is down even though the process is alive. Kill it,
>   start it again, take the new URL, re-paste (step 0.4). Nothing needs rebuilding.
> - Only the **laptop** must stay online — the phone can be on mobile data, another Wi-Fi,
>   or another city.
>
> **If this demo really matters**, a quick tunnel is the fragile part of the whole setup.
> A **named** tunnel (Cloudflare account + a domain you own) keeps one fixed hostname
> forever and reconnects on its own — worth 15 minutes of setup beforehand.

## 0.4 Point the phone at it

→ Open the app → **login screen**
→ Tap the **`server: …`** chip (or long-press the logo)
→ Paste the tunnel URL → **Apply**
→ The chip updates immediately to the new host

**It is saved on the device and survives restarts** — you only do this once per URL.

→ Check the version: **`0.7.4-round7fixes`** on the splash screen, under the logo
→ Phone volume **up**, laptop volume **up**
→ Terminal open in `Workflow_simulation/Workflow2/`

> **Sharing the APK:** the `server:` chip is in **every** build now, debug and release, so a
> signed release APK can be sent to anyone and re-pointed at a fresh tunnel by pasting.
>
> **USB is still an option** if the phone is on this laptop and you would rather not run a
> tunnel: `adb reverse tcp:8000 tcp:9010`, then set the chip to `http://127.0.0.1:8000`.
> It clears on every USB reconnect, which is why the tunnel is now the default.

## 0.5 Who you sign in as, and why

All passwords `Password@123`.

| # | Person | Email | Role | What only they can do |
|---|---|---|---|---|
| 1 | **Siva** | `siva@yuvipep.com` | sales_lead | **the whole sales story** — Pipeline, Approvals, book a demo |
| 2 | **Rahul** | `rahul@yuvipep.com` | sales_agent | **Inbox tab** — log a client reply, triage, delivery trace |
| 3 | **Mithun** | `mithun@yuvipep.com` | operations_lead | confirm the assignment batch · **reschedule a demo by hand** |
| 4 | **Sourav** | `sourav@yuvipep.com` | operations_agent | the full task lifecycle |
| 5 | **Baski** | `baski@yuvipep.com` | operations_agent | complete a client-visible task |
| 6 | **Vikram Rao** | `vikram@yuvipep.com` | operations_agent | the invoicing task (only he has the skill) |
| 7 | **admin** | `admin@yuvipep.com` | org_admin | sees every approval in the org |

> **Read this before you demo, it is the point of Part 10.** Nobody can do everything.
> Siva **books** a demo but cannot **reschedule** one; ops can reschedule but cannot book.
> That is `RoleGate`, mirrored from the backend — the refusals are a feature, not a gap.

### Where things live per role — so you never hunt on stage

| | Siva (sales_lead) | Rahul (sales_agent) | Sourav (ops_agent) | Mithun (ops_lead) |
|---|---|---|---|---|
| Tab bar | Home · **Pipeline** · Jarvis · **Approvals** · Team | Home · **Leads** · Jarvis · **Tasks** · **Inbox** | Home · **Tasks** · Jarvis · Projects · More | Home · **Delivery** · Jarvis · Incidents · Team |
| Leads live in | **Pipeline → Leads sub-tab** | the Leads tab | — | — |
| Projects live in | **Pipeline → Projects sub-tab** | lead → Projects tab | Projects tab | Delivery tab |
| Demos / Follow-ups | **Home cards** | Home cards | Home cards | Home cards |

⚠ **Pipeline opens on the Projects sub-tab.** Tap **Leads** first, every time.

---

# PART 1 · The empty desk, and a new client

## 1.1 Cold start ⚡

→ Open app → sign in as **Siva**

**Show:** the greeting · the briefing · **My day** cards (Demos · Follow-ups) · the **bell**
**Say:** *"Nothing is seeded. This is an empty desk on a Monday morning."*

→ Pull down to **refresh** — everything reloads from the server

## 1.2 The server chip (F36)

→ Sign out → on the login screen, note the **`server: …`** chip
→ Tap it → **Environment** sheet → *Current: …* → change nothing → **Apply**
→ **Watch:** the chip refreshes immediately, it does not go stale
→ Sign back in as **Siva**

> **Available in every build since 2026-08-06.** The chip used to be wrapped in
> `BuildConfig.DEBUG`, which made release APKs unable to reach any server but the one
> hardcoded at build time. It is now always on — paste a LAN IP or a tunnel URL and Apply.

## 1.3 Create the client ⚡

→ **Pipeline** → tap the **Leads** sub-tab → **+**
→ Name `Meridian Data Centres` → **Save**
→ Open it

**Show the six tabs:** Overview · Contacts · Projects · Notebook · History · Meetings

> **The action buttons change with the tab** — this is where people get lost on stage:
> **Overview** → Book demo · Change state · **Contacts** → Add contact, Scan card ·
> **Notebook** → Add note · **Meetings** → Record meeting, Type notes.

→ **Overview** → **Change state** → walk the lead states
→ If a banner says *"AI suggests marking …"* → show **Keep as is** as well as accepting it

## 1.4 One contact, typed ⚡

→ **Contacts** → **Add contact**

| Field | Value |
|---|---|
| Name | `Kavitha Rao` |
| Title | `Head of Infrastructure` |
| Email | `ekaghni.mukherjee+kavitha@gmail.com` |
| Primary | ✅ |

→ **Save**

**Say:** *"One contact typed by hand. Every other person in this story, the AI finds by itself."*

## 1.5 Business card scan ⚡ — the scan proposes, the human decides (F38)

→ **Contacts** → **Scan card** → point the camera at any business card → **Capture**
→ Sheet fills in with the read fields **and a confidence score**

→ **Deliberately change one field** — set the email to `ekaghni.mukherjee+devendra@gmail.com`
→ Set the name to `Devendra Shah`, title `Critical Facilities Manager`
→ **Save**

| Watch | Why it matters |
|---|---|
| The contact holds **what you saved**, not what the camera read | the camera is a suggestion |
| An **intro email draft** appears in Approvals | drafted from the *saved* record |
| Nothing was drafted at scan time | **F38** — the draft waits for Save |

**Say:** *"The scan proposes. The human decides. Only the saved version ever reaches a client."*

## 1.6 A note into the AI's memory

→ **Notebook** → **Add note**
→ `Kavitha owns the budget. Devendra runs the floor and is the one who will complain first.`
→ **Save**

**Say:** *"Anything saved here feeds the AI's memory of this client."*

## 1.7 Typed notes instead of a recording

→ Lead → **Meetings** tab → **Type notes**
→ Paste: `Quick call with Devendra. They want the handover pack to be usable by their own shift engineers, not a PDF nobody opens. He asked for a runbook per hall.`
→ **Done**

**Watch:** *"What the Planner did"* — the AI extracts work from **plain text**, no audio needed
→ **Open meeting** to see it recorded like any other

**Say:** *"Not every conversation is recorded. Typed notes go through the same brain."*

---

# PART 2 · The first meeting

## 2.1 Consent, then record ⚡

→ Lead → **Meetings** tab → **Record meeting**
→ Consent sheet → **They agreed verbally** → note `Kavitha and team agreed verbally` → **Confirm**

**Say:** *"It will not record until someone says consent was given, and it stores who said it."*

→ Recording starts
→ Terminal: `python meeting1.py` → **ENTER** → hold the phone near the speaker

⛔ **Never tap Pause.** (F39 — fixed, but do not make it the story.)

→ When the audio ends → **Stop** → **Upload**

## 2.2 Watch the pipeline ⚡

**uploaded → transcribing → extracting → ready for review**

→ If it stalls: **Retry** is on the meeting screen, and it tells you the reason

## 2.3 The review gate — nothing goes live unsigned ⚡

→ Home → **"Meeting needs your review"** card (or Meetings → the meeting)

→ **Edit** one title → make it sharper
→ **Drop** one item
→ **Add an item the AI missed** → `Confirm escort booking with Fatima Sheikh`
→ Note the **duplicate warning** if two items look alike: *"Looks like … — drop if it's the same"*
→ **Confirm N item(s)**

**Watch:** *"N task(s) are live. The Planner is building the plan from this meeting."*
**Say:** *"The AI proposes. A human signs. Nothing becomes work without that tap."*

---

# PART 3 · The plan, and who gets the work

→ **Pipeline** → **Projects** sub-tab → open **the Meridian project**

## 3.1 All eight tabs ⚡

| Tab | Show |
|---|---|
| **Overview** | objective, status, health — **and the reason line** |
| **Plan** | version 1, **active**, the summary the AI wrote |
| **Tasks** | the work, grouped, each with a person |
| **Timeline** | what has happened, in order |
| **People** | client-side stakeholders, with their role at the client |
| **Team** | our side |
| **Conflicts** | empty — for now |
| **Reports** | weekly client report + internal digest |

## 3.2 Skill-based assignment, with the reason ⚡

→ **Tasks** tab → open any task → **"Assigned because"**

**Typical matches** (yours may differ — the AI picks from real `user_skills` rows):

| Work | Skill it needs | Usually lands on |
|---|---|---|
| rack acceptance checks | `quality_assurance` | Mithun |
| commissioning schedule | `scheduling` | Mithun |
| escorts / site access | `logistics_coordination` | Mithun · Baski |
| daily reports / runbook | `content_development` | Shyam · Rahul Reddy |
| operator enablement | `training_delivery` | Sourav · Shyam |
| the proposal | `proposal_preparation` | Siva · Rahul |
| invoicing | `invoicing` | **Vikram only** |

**Say:** *"It matched people by a real recorded skill, and it will tell you why — including
when it is unsure."*

## 3.3 Commitments — both directions

→ **Overview** → **We owe them** / **They owe us**

**Watch:** proposal by Friday (ours) · single-line diagrams + access passes (theirs)
**Say:** *"Every promise made out loud in that room is now chased by the system."*

## 3.4 People and team

→ **People** → **Add stakeholder** → `Fatima Sheikh`, role at client `Security & Access`
→ **Team** → **Add member** → add **Baski**
→ Try **Remove** → it asks first

## 3.5 The client report

→ **Reports** → **Generate this week's client report**
**Watch:** *"Queued for approval before it reaches the client."*
→ **Generate internal digest** → this one is for us, so it is not gated

## 3.6 Project-level actions

→ Top of the project screen:

| Action | What to say |
|---|---|
| **Catch me up** | *"A one-tap briefing on a project you have not touched in a week."* |
| **Change status** | moves the project through its lifecycle |
| **Record meeting here** | records straight against the project |
| **Draft message** | asks the AI for a client message from project context |

---

# PART 4 · Jarvis, properly

→ **Jarvis** tab. Type these **in order** — each group proves a different agent tool.

## 4.1 Knowing the client ⚡

| Type | Watch for |
|---|---|
| `list my clients` | reads the lead list, not a guess |
| `tell me everything about meridian` | state, contacts, recent activity in one answer |
| `give me a brief about the meridian project` | **F62** — objective, health **and why**, plan version, task counts, people, open promises, what's next |
| `what did meridian say about the handover pack` | searches past meeting notes |

## 4.2 Knowing the work ⚡

| Type | Watch for |
|---|---|
| `what's blocking meridian` | **F43** — approvals and conflicts, not just late tasks |
| `what is late` | **F52** — nothing due *today* is called overdue |
| `most important task this week` | **F19** — P1 beats soonest-due |
| `who is doing the rack acceptance` | **our** engineer, never the client's manager |
| `why did you pick <that name>` | **F46** — quotes the recorded reason **verbatim, caveats included** |
| `how many approvals are waiting on me` | **F57** — reads **approvals**, not the task list |

→ Tap the **About / why** chip under any answer → **which agent answered, and on what**

## 4.3 Terse and ambiguous — the F28 rule ⚡

| Type | Watch for |
|---|---|
| `meridian` | it resolves, or asks *"my understanding is X, shall I proceed?"* |
| `proposal` | same — **never** a bare "not found" |
| `chase them` | asks **who**, with candidates |

**Say:** *"A short command is the AI's job to understand, not the user's job to phrase."*

## 4.4 Jarvis that *does* things

| Type | Watch for |
|---|---|
| `add a note to meridian: Devendra prefers WhatsApp for urgent issues` | writes to the notebook |
| `create a task to send Fatima the engineer list by Friday` | a real task appears |
| `schedule a follow-up with Kavitha next Tuesday` | queued in Follow-ups — **this is what fills Part 8.1's queue** |
| `show me the demos this month` | the calendar, in text |

## 4.5 Housekeeping

→ **Start a new conversation** → *"Jarvis will forget what you have said so far in this chat"* → **Start fresh**
→ Toggle **speak replies** on → ask one thing → it reads the answer aloud

---

# PART 5 · Money — the proposal

## 5.1 Create it ⚡

→ **Jarvis** → `create the commissioning proposal for meridian`
→ Open the proposal

**The screen has five sections:** Commercials · Total · Narrative · Revision trail · the actions

| Watch | Why |
|---|---|
| header reads `template v_ · pricing v_` | every unit price came from the **rate card** |
| *"Machine-generated from the pricing table — words are editable"* | the fence, stated on screen |
| per **rack** / per **hall** / per **site** | the datacentre catalogue, not a school one |
| **no invented discount** | **F23** — the AI is fenced out of pricing |

→ Tap the **Why?** chip → what the AI based it on

## 5.2 Change the words, not the numbers ⚡

→ **Change it (by instruction)** → *"Change the proposal"*
→ `make the tone warmer and shorter, and lead with the handover pack`
→ **Apply** → *"Applied."*

**Watch:** the **Narrative** changes · **Commercials and Total do not** · a new row in the
**Revision trail**
**Say:** *"It can rewrite the argument. It cannot touch the price."*

## 5.3 The PDF

→ **View PDF** → it renders in-app
→ Scroll it — **no `[missing:…]` placeholders anywhere** (F47)

## 5.4 The tamper check

→ **Upload edited file** → pick any unrelated PDF or a text file
→ **Watch:** *"Upload refused"* — it will not accept a document it cannot verify

→ Now upload a genuinely edited copy → *"Revision N uploaded"* → it joins the **Revision trail**

## 5.4b Internal review

→ **Submit for internal review**
→ **Watch:** *"Review status: …"* — a colleague signs off before the client ever sees it

## 5.5 Send it — REAL EMAIL ⚡

→ **Jarvis** → `email the proposal to Kavitha`
→ Draft appears inline

→ **If it says "This draft isn't finished"** → it lists the blanks → say `fill them in`
→ Re-open → the blanks are gone → **and the PDF was re-rendered too** (F61)

→ **Approve & send**
→ **Open your Gmail on the projector.** It has arrived, with the attachment.

**Say:** *"Nothing reaches a client without a human tap — and what gets sent is what you last approved,
not an older copy."*

---

# PART 6 · The calendar

## 6.1 Book the site walkthrough ⚡ — REAL CALENDAR

→ **Pipeline → Leads** → Meridian → **Overview** tab → **Book demo**
→ Date → **9 September** → Time → **10:30** → notes `Readiness walkthrough, halls 1 and 2`
→ **Book demo**

| Watch | Why |
|---|---|
| *"Booked for 9 September."* | |
| *"The calendar invite is drafted and waiting in Approvals — nothing has been sent."* | honesty |
| a **clash warning** if the day is busy | it never hides a conflict |

⚠ **Book it on 9 September.** Meeting 2 will ask to move it, and that is the F63 demo.

→ **Approvals** → approve the invite → **check Google Calendar on screen**

## 6.2 The demos calendar

→ **Home** → **Demos** card
→ Month grid: **dots mark days with tasks due**
→ **Long-press** a dotted day → that day's tasks
→ Tap the **9 September** demo → the detail dialog

## 6.3 The role wall

→ Still as **Siva**, tap **Reschedule**
→ **Watch:** *"Your role can't update demos — ask your operations team."*

**Say:** *"He booked it. He cannot move it. Different job, different permission."*

---

# PART 7 · Inbound — the Inbox

→ Sign out → sign in as **Rahul** (`rahul@yuvipep.com`) — he has the **Inbox** tab

> Siva reaches the same screen when the *"N inbound message(s) need a human"* card is on his
> Home. Rahul just has it permanently.

## 7.1 What we actually sent

→ **Inbox** → **Messages** tab → open the proposal email you sent in Part 5
→ **Delivery trace** → **"Exactly what was sent"**

**Watch:** the real `.eml` · every delivery event in order
**Say:** *"Not what we think we sent. The bytes that left."*

## 7.2 Log a client reply ⚡ — the message that arrived off-system

Kavitha replied on WhatsApp, not email. Get it into the system.

→ **Inbox** → **Log a reply** → the *"Log a client reply"* sheet opens
→ **Choose who it came from** → `Meridian Data Centres` → `Kavitha Rao`
→ **Watch:** *"From Kavitha Rao at …"* — it needs a **person**, because that is how a message
finds its client
→ **Subject (optional)** → `Re: commissioning proposal`
→ **What they said**:
`Thanks for the proposal. The commercials look broadly fine but my board wants the handover pack scope spelled out before I sign. Can you send that by Friday?`
→ **Log it**

**Watch:** *"Understood as: `<intent>` · `<confidence>`"* — it **classifies** what the client wants
→ It becomes a real inbound message, on the right client, with a follow-up

**Say:** *"A phone call, a WhatsApp, a corridor conversation — type it in and the machine treats it
exactly like an email."*

## 7.3 Triage — what the AI could not place

→ **Needs a human** tab

> The sheet **will not** let you log a message without a contact — that is deliberate. So the
> triage queue fills from genuinely unplaceable inbound mail, not from this screen. If it is
> empty on the day, show the empty state — *"Messages the AI can't place will wait here for a
> human"* — and walk the actions on any item that is there.

→ Open an item → **Actions**:

| Action | Show |
|---|---|
| **Read the whole message** | nothing is truncated |
| **Attach to a client** | it becomes findable |
| **Attach to a project** | now it is on the right work |
| **Set what it is asking for** | correct the AI's read of the intent |
| **Reply** | drafts an answer — still gated by Approvals |
| **Mark handled** | out of the queue |

**Say:** *"When the AI cannot tell, it does not guess. It queues it for a person."*

---

# PART 8 · Follow-ups and approvals

→ Sign out → back in as **Siva**

## 8.1 The follow-up queue ⚡

> ### ⚠ Fill the queue FIRST — it will be empty otherwise, and that is correct
>
> A meeting produces **either** a project **or** follow-ups, never both
> (`planner_engine:1335`): if the discussion was concrete enough to plan, you get a project;
> if it was vague, you get follow-ups and the lead stays open. **Meridian's meetings are all
> concrete, so they correctly create zero follow-ups.**
>
> Nothing else fills the queue on its own, and **the app has no "new follow-up" button** —
> `POST /followups` is not wired into the UI. **Jarvis is the only way in.** Do this first:

→ **Jarvis**, three commands — deliberately in words, not dates:

| Type | Fills the bucket |
|---|---|
| `schedule a follow-up with Meridian for last Tuesday, note: chase the single line diagrams` | **Overdue** |
| `schedule a follow-up with Meridian for today, note: confirm Kavitha received the proposal` | **Due today** |
| `schedule a follow-up with Meridian for next Monday, note: check the operator name list` | **This week** |

**Say:** *"I never typed a date. It worked out 'last Tuesday' and 'next Monday' itself."*

> This doubles as the proof for the clock fix — until 2026-08-07 the assistant was never told
> what day it was and could not resolve a relative date at all.

→ Now **Home** → **Follow-ups** card

**Four buckets, and all three are populated:** Due today · Overdue · This week · All pending

→ Open the overdue one → **Draft message (AI)** → prompt `check whether they have the diagrams ready`
→ The AI writes the chase → it goes to **Approvals**, not out the door

→ Open the one due today → **Mark done** → note `Spoke to Devendra` →
✅ **Schedule the next one automatically**
**Watch:** *"Done — next follow-up set for …"* — completing one **creates the next**, so the
relationship never goes quiet

→ **Open the lead** from a follow-up — it jumps straight there

**Say:** *"A lead that isn't ready to buy doesn't get dropped. It gets a date."*

## 8.2 The approvals inbox ⚡

→ **Approvals** tab

→ Open a card → **the full body, no truncation** (F45)
→ **Recommend** — the AI's own view, separate from your decision

→ **Reject** one → note `Please shorten the second paragraph and put the date in the first line`
→ **Watch the redraft come back**, incorporating the note

**Say:** *"A rejection is an instruction, not a dead end."*

→ **Approve** one → it applies once

## 8.3 The blanks guard

→ If any draft still has gaps: *"This draft isn't finished — it still has blanks."*
→ Options are **Send as it is** / **Not yet** — never a silent send

## 8.4 Offline ⚡

→ **Airplane mode ON**
→ **Watch:** the offline banner
→ **Approvals** → approve something → *"Queued — will apply when you're back online"*
→ **Airplane mode OFF**
→ **Watch it apply — exactly once**

---

# PART 9 · Meeting 2 — the plan learns, and the demo moves

## 9.1 Record it ⚡

→ **Pipeline → Leads** → Meridian → **Meetings** → **Record meeting** → consent → start
→ Terminal: `python meeting2.py` → **ENTER**
→ **Stop** → **Upload** → review gate → **Confirm**

## 9.2 What must have changed ⚡

→ Open the project:

| # | Watch | Why it matters |
|---|---|---|
| 1 | 120 → **160 racks**, 2 → **3 halls** | scope grew |
| 2 | start 1 Sep → **15 Sep** | a date moved |
| 3 | **site walkthrough 9 Sep → 18 Sep, 14:30** | **F63 — the demo itself moved** |
| 4 | hot-spot mapping **cancelled** | and only on activation, not before |
| 5 | **every meeting-1 task still there**, with its status | a merge, not a rewrite |
| 6 | **Anand Krishnan** is now a contact **and** a stakeholder | discovered from speech alone (F41) |
| 7 | operator **certification** added for 20 staff | new work |
| 8 | **new commitments** on both sides | the register is not write-once (F56) |
| 9 | plan **v2 pending approval**, v1 still **active** | nothing switches without a human |

## 9.3 Approve it, then prove the demo actually moved ⚡

→ **Approvals** → approve **Plan v2** → v2 becomes active

→ **Home** → **Demos** card → the demo now reads **18 September, 14:30**
→ **Approvals** → an **updated calendar invite** is drafted and waiting
→ Approve it → check Google Calendar — the client's event has moved

**Say:** *"The client asked, in a meeting, to move a site visit. The system moved the actual booking
and re-invited them. It did not quietly shift some unrelated task."*

> **This is the newest fix in the build (F63).** Before it, the AI had no way to express
> "move a demo", so it re-dated whatever task happened to mention the word.

---

# PART 10 · Operations — the work gets done

## 10.1 The operations lead confirms the batch ⚡

→ Sign out → **Mithun** (`mithun@yuvipep.com`)

→ **Home** → *"N task assignment(s) proposed"* → open → read the reasons
→ **Change person** on one → **Watch:** an honest refusal — his role cannot read the staff directory
→ **Confirm N assignment(s)**

→ **Delivery** tab → project health, with the reason line

## 10.2 Move the demo by hand

→ **Home** → **Demos** → tap the 18 Sep demo → **Reschedule** → change the time → **Save**
**Watch:** *"Rescheduled — the updated invite is drafted and waiting in Approvals."*

→ Tap it again → **Update status** → **Completed** (or **Cancelled** → *"retract the invite"*)

**Say:** *"Ops can move it. Sales cannot. Same screen, different buttons."*

## 10.3 An agent does the work ⚡

→ Sign out → **Sourav**

→ **Tasks** tab — **five groups:** Blocked · **Overdue** · Today · This week · Later (F53)

→ Open a task → show **"Assigned because"** and, where it applies,
**"Fulfils a client commitment"**

Now run the whole lifecycle:

| Action | Do this | Watch |
|---|---|---|
| **Progress** | add a progress note | it lands on the project Timeline |
| **Decline** | reason **Wrong skill for this**, note `Not my area` | re-routes to someone else with a **better** reason, and the decline stays on record |
| **Block** | `Waiting on site access from Fatima` | red banner names the blocker · *"nudges paused until you unblock"* |
| **Unblock** | | nudges resume |
| **New date** | pick a later date, why `UPS module slipped` | if it breaks something: *"This breaks: … — sent to your phase lead to confirm instead"* |
| **Split** | into `Hall 1 acceptance` + `Hall 2 acceptance` | two real tasks |
| **Vendor promise** | `RackLine`, promised date | recorded against the task |
| **Vendor slipped** | new date a week later | the slip is on record, not hidden |

→ Now open a task assigned to **someone else** → try to **Block** it
→ **Watch:** refused — *"assigned to someone else"* (F51)

**Say:** *"You can only act on your own work. The server enforces it, not the screen."*

## 10.4 Finishing a client-visible task ⚡

→ Sign out → **Baski**
→ Open a **client-visible** task → **Done** → result note `Hall 1 racks accepted, 3 minor snags logged`

**Watch:** a **client update is drafted** and sent to Approvals
**Say:** *"He finished a job. The client email wrote itself, and still waits for a human."*

## 10.5 The invoicing skill

→ Sign out → **Vikram Rao**
→ **Tasks** → the invoicing work is here, and **only** here

**Say:** *"One person in the company has `invoicing` on their record. The AI never had to be told."*

## 10.6 The honest refusal

→ Still as an operations agent → try to reach **Approvals**
**Watch:** a refusal that **names what he can do instead** — no crash, no blank screen

---

# PART 11 · Meeting 3 — it goes wrong

→ Sign out → back in as **Siva**

## 11.1 Record it ⚡

→ Meridian → **Meetings** → **Record meeting** → consent → start
→ Terminal: `python meeting3.py` → **ENTER**
→ **Stop** → **Upload** → review → **Confirm**

## 11.2 Five machines fire from one recording ⚡

| # | Where | What must be there |
|---|---|---|
| 1 | project → **Timeline** / Mithun's escalations | the late engineer became an **INCIDENT**, at severity, **both leads paged** — not just a task (F54) |
| 2 | project → **Conflicts** | December **vs** January, **both positions named, with who said what** |
| 3 | project → **Plan** | the new plan sits in **draft, HELD** — the live plan is untouched and **no approval is even offered** |
| 4 | lead → **Contacts** | **Priya Menon** added as a contact — but **NOT** a stakeholder on this project (F55) |
| 5 | **Tasks** | vendor chase (RackLine) · invoice reminders **paused** · the Thursday write-up |

**Say:** *"Two people in the room contradicted each other. It refused to pick a side, wrote both
down, and stopped the plan until a human decides."*

## 11.3 Resolve it ⚡

→ **Conflicts** → open it → **Resolve** → `Board confirmed January; Devendra's read was correct`
→ **Watch:** the held plan is released and becomes approvable

## 11.4 Branch the work

→ Project → **Split into branches** → add branch `Chennai site — new build`
→ **Watch:** *"1 branch project(s) created"*

→ Project → **Shift phase** → *"Phase shifted."*

**Say:** *"Chennai was mentioned once, in passing, and kept deliberately out of this engagement."*

---

# PART 12 · The last mile

## 12.1 Notifications go somewhere ⚡ (F58)

→ Tap the **bell**

| Tap this | Must land on |
|---|---|
| a **conflict** notification | the project's **Conflicts** tab |
| a **plan** notification | the project's **Plan** tab |
| a **task** notification | that task's detail |
| an **approval** notification | that approval |
| a **message** notification | the delivery trace |

**Say:** *"Every notification opens the exact thing it is about."*

## 12.2 Voice ⚡

→ **Jarvis** → tap the **mic** → allow the permission
→ Say: *"what is blocking meridian"*
→ Watch the dictation appear, then the answer
→ Toggle **speak replies** → ask again → it answers out loud

## 12.3 Wrap ⚡

**One line:**
> *"A rep records three meetings. The plan, the people, the pricing, the chasing, the calendar and
> the client emails — the machine does. A human approves."*

**Numbers to quote:**
- **3 recordings + 1 typed note** → 1 project, 3 plan versions, ~25 tasks
- **0** tasks typed by hand
- **0** client messages sent without a tap
- **1** contact typed; everyone else discovered from speech

---

# Coverage checklist

Tick these off — if one is unticked, the demo missed a feature.

**Auth & shell** ☐ login ☐ environment sheet + server chip (1.2) ☐ sign out ☐ offline banner (8.4)
☐ role-shaped tab bars (0.4) ☐ honest refusals (6.3, 10.1, 10.3, 10.6)

**Home** ☐ briefing ☐ my-day demos card ☐ my-day follow-ups card ☐ approvals list
☐ review-waiting card ☐ assignment-batch card ☐ triage card ☐ bell ☐ pull-to-refresh

**Leads** ☐ create (1.3) ☐ 6 tabs (1.3) ☐ add contact (1.4) ☐ **card scan + edit + save** (1.5)
☐ notebook (1.6) ☐ **typed notes** (1.7) ☐ record meeting (2.1) ☐ book demo (6.1) ☐ history

**Meetings** ☐ consent ☐ recorder ☐ pipeline states ☐ retry ☐ review gate edit/drop/add
☐ duplicate warning ☐ confirm

**Projects** ☐ all 8 tabs (3.1) ☐ assignment reasons (3.2) ☐ commitments both ways (3.3)
☐ add stakeholder ☐ add/remove team member (3.4) ☐ weekly client report ☐ internal digest (3.5)
☐ catch me up ☐ change status ☐ draft message (3.6) ☐ **chain wizard** (11.4) ☐ **shift phase** (11.4)
☐ conflicts + resolve (11.2, 11.3)

**Jarvis** ☐ client tools (4.1) ☐ **project brief** (4.1) ☐ work tools (4.2) ☐ **approvals tool** (4.2)
☐ explain decision (4.2) ☐ why chip ☐ terse commands (4.3) ☐ action tools (4.4) ☐ new chat (4.5)
☐ TTS (4.5, 12.2) ☐ **voice input** (12.2) ☐ inline approve ☐ reject with reason ☐ blanks guard (5.5)

**Proposals** ☐ create ☐ locked pricing ☐ edit narrative ☐ view PDF ☐ **upload-edited-file refusal** ☐ submit for internal review
☐ approve & send ☐ **real email arrives**

**Demos** ☐ book + clash warning ☐ invite held for approval ☐ **real Google event**
☐ month grid + task dots ☐ long-press day ☐ **manual reschedule** (10.2) ☐ update status
☐ **AI reschedule from a meeting — F63** (9.3)

**Follow-ups** ☐ 4 buckets ☐ AI draft ☐ mark done + auto-schedule next ☐ open the lead

**Inbox** ☐ messages ☐ **delivery trace / exactly what was sent** (7.1) ☐ **log a client reply** (7.2)
☐ triage: attach client ☐ attach project ☐ set intent ☐ read full ☐ reply ☐ mark handled (7.3)

**Tasks** ☐ 5 buckets ☐ progress ☐ decline + reroute ☐ block/unblock ☐ **new date + ripple**
☐ **split** ☐ **vendor promise** ☐ **vendor slip** ☐ done + client update ☐ ownership refusal (10.3)

**Approvals** ☐ full body ☐ recommend ☐ approve ☐ **reject → redraft** ☐ blanks guard
☐ **offline queue drains once** (8.4)

**Notifications** ☐ centre ☐ conflict route ☐ plan route ☐ task route ☐ approval route ☐ message route

---

# Quick reference

```
cd Complete_Project/Workflow_simulation/Workflow2
python meeting1.py      # first meeting  — scope, people, promises
python meeting2.py      # merge          — scope grows, dates move, DEMO MOVES
python meeting3.py      # it goes wrong  — incident, conflict, vendor, invoice

# flags
--regen     rebuild the WAV from the script
--no-wait   play immediately, no ENTER
--no-play   build the WAV only
```

# If something goes wrong

| Symptom | Fix |
|---|---|
| *"Network trouble — check your connection"* | **The tunnel died.** Check the cloudflared window is still open, then `curl https://<url>/health`. If it restarted you have a NEW url — re-paste it via the `server:` chip. Check this **before** suspecting the backend |
| Tunnel URL changed | Normal for quick tunnels. Copy the new one, paste it on the login screen, Apply. No rebuild |
| Using USB instead | `adb reverse tcp:8000 tcp:9010` and set the chip to `http://127.0.0.1:8000` |
| `/health` dead | `cd Complete_Project; $env:PORT="9010"; python run.py` |
| Recording stuck | **Stop**, upload anyway — the pipeline shows a reason and a **Retry** |
| Pipeline says failed | **Retry** on the meeting screen |
| No email arrived | `.env` must say `EMAIL_MODE=smtp`; check spam; check the backend started **without** the dry_run override |
| Demo didn't move in 9.3 | the plan must be **approved** — the op applies on activation, not at extraction |
| Jarvis says "no results" on notes | embedding credits are out; semantic search degrades — use `give me a brief about…` instead |
| Need to start over | `python scripts/reset_for_datacentre_demo.py`, then restart the backend |

⛔ **Never** tap Pause in the recorder.
⛔ **Never** `pm clear` the app — it wipes the stored server URL.
