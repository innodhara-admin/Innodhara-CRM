YuviPep AI Sales Platform — 30 Real-Life Workflows

## The Complete Product, Told as 30 Stories

This document describes 30 complete, real-life workflows that our AI sales platform must handle. Each workflow is a story with real people, real steps, and the exact tables and fields the AI reads and writes at every step.

The workflows go deep: many people working together, the AI assigning and re-assigning work, keeping everyone in sync, talking to the client on our behalf, reading the client's replies, and re-planning again and again until the project is done. Together with its companion document — "YuviPep Data Model & Tables Reference", which defines every table and field — this is a complete specification: after reading both, an engineering team can build the full product.

# 1. How to Read This Document

Section 2 introduces the people who appear in the stories. The same cast is used everywhere so the stories are easy to follow.

Section 3 explains the three ideas everything rests on, and points to the companion document — "YuviPep Data Model & Tables Reference" — that defines every table and field the workflows use.

Section 4 defines the ten AI engines that drive everything.

Section 5 contains the 30 workflows, grouped into five parts that follow the life of a client project from first call to final closure.

Section 6 explains why this design can absorb any new workflow — not just these thirty.

Section 7 gives the build order: the pillars to build first, and what stacks on them.

Writing style used in the workflows:

When a step touches the database, the table and field are shown in brackets, like this: (action_items.assignee_id).

When the AI makes a decision, the engine that made it is named, like this: [Assignment Engine].

Every workflow ends with "If things go differently" — the other routes the same story can take. This is how we prove the design handles any route, not just the happy one.

# 2. The People in Our Stories

## 2.1 YuviPep staff (they log in to the app)

Name

Role in app (users.role)

Designation

Skills (user_skills)

Notes

Akash Rathore

sales_lead

Sales Lead

negotiation (expert), proposals (good)

Leads the sales team. Approves client messages and discounts.

Rahul Verma

sales_agent

Sales Executive

field_sales (expert), hindi (expert)

Visits clients, records meetings.

Priya Nair

sales_agent

Sales Executive

field_sales (good), english_writing (expert)

Handles email-heavy accounts.

Meera Joshi

operations_agent

Content Specialist

curriculum_design (expert), android (good)

Builds content plans and training content.

Sourav Das

operations_agent

Specialist

android (expert), teaching (expert)

Delivers sessions in clients.

Baski Murmu

operations_agent

Specialist

robotics (expert), teaching (good)

Second specialist.

Mithun Sharma

operations_lead

Operations Lead

scheduling (expert), logistics (expert)

Owns demo teams, delivery, and logistics.

Shyam Prasad

operations_agent

Media Rep

photography (expert), social_media (expert)

Covers events, makes reports look good.

Vikram Rao

operations_agent

Accounts Executive

invoicing (expert), payments (expert)

Raises invoices, chases payments.

Ananya Iyer

org_admin

Org Admin

—

Manages programs, pricing, templates, staff.

## 2.2 Client-side people (they never log in — they are `contacts` / `stakeholders`)

Name

Client

Role at the client (stakeholders.role_at_client)

Mr. Harish Singhania

Vivekananda Group

managing director (decision maker)

Mrs. Kavita Menon

Vivekananda Group

academic_coordinator (influencer)

Mr. Ramesh Gupta

Vivekananda Group

accountant (gatekeeper for payments)

Mrs. Sharma

Delhi Public Client

managing director

Mr. Verma

Delhi Public Client

owner

Dr. Anita Bose

Sunrise Group of Clients

group director (chain of 12 branches)

# 3. The Building Blocks — Where the Tables Live

Every table and field these workflows use is defined in one companion document: "YuviPep Data Model & Tables Reference." That document is the single source of truth — every table, every field, every status value, and how they connect. Whenever a workflow shows something in brackets, like (action_items.assignee_id), the full definition is there. The two documents are meant to be read side by side.

To read the workflows comfortably, only three core ideas are needed:

1) The Project. A client is not a piece of work — a project is. "7-day Android programme at Vivekananda Group" is a project (projects). The same client can run two projects at once, and one project can have ten meetings. The project holds the team (project_members), the client-side people and how to talk to them (stakeholders), the money, the conversation, and — most importantly — the plan. The client relationship itself (contacts, notes, memory) lives on the leads record and is shared by all of that client's projects.

2) The living plan. Every project has one global action plan (action_plans), and it is versioned: every time the AI re-plans — a new meeting, a client reply, a big progress change — it creates a new version with a written diff, never a silent edit. The plan's tasks (action_items) carry a required skill, an assignee, a priority, dependencies, and one flag that matters everywhere: visible_to_client — "when this finishes, the client should hear about it." Promises made to the client, and by the client to us, live in client_commitments and are watched until kept.

3) The event stream. Every meaningful change — a task done, a reply received, a payment recorded, a person going on leave — becomes a row in progress_events. The engines react to events, not to someone remembering to check. That is what keeps a whole team in sync without a single status meeting.

# 4. The Ten AI Engines

Most of the work in these workflows is not started by a user typing a command — it is started by events: a meeting ends, a task finishes, a reply arrives, a deadline passes, a file is uploaded. So the design is a set of ten engines. (These ten engines refine and supersede the seven-agent design of the earlier architecture document, “YuviPep AI Sales Platform v2”; that document remains the reference for infrastructure, multi-organisation isolation, security, and scaling.) Some respond to people; the most important ones respond to events. Each engine has one job, its own triggers, and its own tables.

#

Engine

What it does

Triggered by

1

Planner Engine

Turns meetings, replies, and progress into a versioned global action plan (action_plans). The plan's content is authored by the language model against the organisation's actual skill taxonomy — any engagement type (a programme, a lab build, an incubation centre), no fixed checklists; a plan needing a skill nobody holds raises an explicit skill-gap decision for a human. Merges new information into the existing plan: adds, removes, re-orders, re-dates tasks — always as a new version with a written diff. Extracts client commitments. Detects conflicts between sources and holds the plan until a human resolves them. Runs a feasibility pass (asking the Resource & Calendar Engine) before anything is promised to a client. If the model is unreachable, the work is held for a human — never guessed from keywords.

meeting processed, inbound message processed, phase shift, big progress change, manual "re-plan"

2

Assignment Engine

Picks the best person for every task: matches action_items.required_skill to user_skills, checks load against max_open_tasks, leave dates, field bookings, project membership, and continuity. Writes the reason into assignment_reason. Proposes; a lead confirms (or auto-assigns, per org setting). Handles declines, reassignments, and rebalancing.

new plan version, task declined, member left, leave recorded, overload detected

3

Resource & Calendar Engine

The single owner of "who and what is free when" — across ALL projects: leave, delivery days, demos, travel, venue and equipment holds (resource_bookings). Consulted by the Planner for feasibility and by the Assignment Engine for real availability. Mirrors bookings to the org's Google Calendar, and booking a demo also drafts a calendar-invite email to the client's contact (CC the demo team): a standard iCalendar invitation that renders natively in the client's mail app — Yes/No/Maybe buttons, the event added to their calendar, the org's reusable Google Meet link stamped in. Rescheduling updates the same event; cancelling retracts it. The invite is an outbound message like any other — it sends only after a human approves it.

any booking change; any feasibility or availability question

4

Sync Engine

The heartbeat. Reads progress_events, updates projects.health, unblocks dependent tasks, runs the three-level reminder ladder, watches commitments, reply timers, payments, and vendor promises, fires client-update drafts when visible_to_client tasks finish, and triggers the digests. Runs on every event plus a daily sweep.

every progress event + daily schedule

5

Communication Engine

Drafts every outward message (email/WhatsApp): language-heavy content (replies, proposals cover text, follow-ups) is authored by the model from project context, thread history, and stakeholder preferences (language, channel, pacing caps); mechanical notices (calendar invites, payment reminders) come from fixed templates so dates, links and amounts are byte-exact. Runs the coverage check: a reply must answer every extracted point of the message it responds to, or say why not. Never invents numbers. Every draft goes to the Approval Engine — never straight to the client.

Sync Engine triggers, inbound replies, user commands

6

Document Engine

Builds every artifact: proposals (prices from pricing_tables only), content plans, schedules, invoices, certificates, reports — all versioned in deliverables. Equally important: it accepts manual uploads. Any document the AI would generate can instead be made by a person and uploaded onto the task; the engine versions it, links it, and the rest of the machine treats it exactly the same.

plan tasks, client asks, user commands, manual uploads

7

Inbound Engine

Reads every incoming email/WhatsApp (voice notes transcribed first). Matches sender → contact → project → thread; when a client has several projects, the model reads the message against them and picks the one it concerns — or all of them, when the message deliberately spans several (recorded on every concerned project and handed to a human). Classifies intent, change type, and sentiment; extracts concrete asks; updates commitments; hands change requests to the Planner; drafts replies via the Communication Engine. Money always takes the money path, whatever the phrasing — a discount ask worded as a question still enters the approval chain. When the org's inbox is polled directly (IMAP), automation mail is skipped on protocol headers, known contacts always ingest, and unknown senders are screened by the model — marketing noise is ignored WITH an audit entry, never silently, and if the model is unreachable the mail is kept for triage, never dropped. Anything unclear → needs_human; anything unmatched → a triage queue for a human. Nothing is ever dropped.

email/WhatsApp webhook; scheduled IMAP inbox polling

8

Approval Engine

Finds the right approver from approval_rules (by role and condition), supports joint approvals (e.g. sales + ops for a delivery-date promise), notifies, reminds, escalates on expiry, and records every decision. A rejection with a note loops the draft back to be redone.

any draft or change that needs a human yes

9

Knowledge Engine

The organisation's memory. Owns playbooks (the standard task waves per program), client_intelligence, and the long-term memory store (memory_chunks). Distils every closed project and incident into lessons, proposes playbook improvements, and briefs the Planner with rich priors so every new plan starts smarter than the last.

project closure, incident resolution, planning requests

10

Assistant Engine

The front door for everything a person types or says. Understands the request and acts: answers questions across everything in plain language ("what is blocking the VG programme?"), executes record commands directly (create a lead, close a task, reassign, add a note, book a meeting), and routes bigger jobs to the right engine (a re-plan to the Planner, a draft to the Communication Engine). Also builds the daily personal digests, the weekly internal and client reports, onboarding briefs, and dashboards.

It holds the thread of the conversation, not just the last sentence. Each exchange is kept in `assistant_turns` for the current chat and read back before the next one, so "make it warmer", "send it to her" and "tell me about the second one" are understood the way a colleague would understand them — and so the routing decision itself knows what "it" refers to. Only the words are remembered, never the keys: when the assistant needs a record again it looks it up again, freshly permission-checked, so a conversation can never become a back door to something the person is no longer allowed to touch. A chat is working memory — trimmed as it grows, cleared on request, and swept on a timer.

user commands and questions (typed or voice), digest and report schedules

Three rules stand above all ten engines:

1.  Nothing reaches the client without a human approval, and every AI decision is written to ai_decisions with its reason — anyone can always ask "why did the AI do that?" and get an answer.

2.  People can always do the work themselves. Every AI step has a manual path: type instead of dictate, upload a file instead of generating one, assign by hand instead of accepting a proposal, write the email yourself instead of editing a draft. The engines reconcile manual work into the same tables — the plan never goes stale just because a human went around the AI.

3.  When the AI is unsure, it asks — it never guesses. Low confidence, conflicting sources, unmatched messages, and missing knowledge all route to a named human with the context attached.

# 5. The 30 Workflows

## PART 1 — WINNING THE CLIENT (Workflows 1–8)

### Workflow 1 — First meeting to first plan: the whole machine starts

The story. Mr. Harish Singhania is the managing director of Vivekananda Group. He wants a 7-day programme at his site for cohorts 5–9 on the topic "Learning About Android". He calls Mr. Akash Rathore (YuviPep sales lead). Akash asks Rahul Verma (sales executive) to visit the client. Rahul sets up a meeting with Mr. Singhania for Monday 10 AM.

Step by step:

1.  Akash opens the app and says: *"New lead — Vivekananda Group, managing director Harish Singhania, phone 98xxxxxx. He wants a 7-day Android programme for cohorts 5 to 9. Rahul will visit Monday 10 AM."*

2.  The [Assistant Engine] routes this to lead creation. A lead is created (leads.name = "Vivekananda Group", leads.state = open, leads.owner_id = Rahul). A contact is created (contacts.name = Harish Singhania, contacts.title = Managing Director). A meeting slot is booked (meetings.status = scheduled, meetings.started_at = Monday 10 AM, meetings.meeting_type = first_visit) and pushed to Rahul's calendar. Rahul gets a notification (notifications: "New lead assigned: Vivekananda Group, meeting Monday 10 AM").

3.  Monday. Rahul reaches the client, confirms consent for recording (consent_records), taps Record, and meets Mr. Singhania for 40 minutes. They discuss: 7 days, cohorts 5–9, around 400 participants, client wants it in December, budget "around one lakh", client will give the equipment room, YuviPep must share a content plan within a week and do a demo session for client staff first. Rahul photographs the managing director's card and taps Stop.

4.  The meeting pipeline runs in the background: transcription (transcripts.text), then analysis. Because this is a first meeting with real discussion, the [Planner Engine] proposes a project:

projects row: name "VG Android Programme — Dec 2026", objective "7-day Android programme for cohorts 5–9 (~400 participants)", program_id = "Programme — Learning About Android", status = planning, sales_owner_id = Akash, value_estimate = ₹1,26,000 (from the current pricing_tables version — never invented).

action_plans v1 with these tasks (action_items, each with project_id, plan_version_added = 1, source = meeting):

#

Task

phase

required_skill

due

visible_to_client

T1

Prepare day-wise content plan for 7-day Android programme (cohorts 5–9)

preparation

curriculum_design

+5 days

yes

T2

Build draft proposal with pricing for ~400 participants

proposal

proposals

+3 days

no

T3

Schedule client staff demo session at VG

sales

scheduling

+7 days

yes

T4

Check specialist availability for first week of December

preparation

scheduling

+4 days

no

T5

Send thank-you + summary email to Managing Director

sales

english_writing

+1 day

yes

client_commitments extracted: "Share content plan within a week" (promised_to = Harish, due = +7 days, linked to T1) and "Client staff demo before the programme" (linked to T3). A stakeholders row is also created: Harish Singhania on this project (role_at_client = managing director, influence = decision_maker, receives_progress_updates = true) — commitments, threads, and conflict-weighing all point at it.

5.  The [Assignment Engine] picks a person for each task and writes its reason into action_items.assignment_reason and ai_decisions:

T1 → Meera (curriculum_design expert, 3/8 open tasks)

T2 → Priya (proposals good + english_writing expert; Akash is fallback)

T3, T4 → Mithun (scheduling expert, operations lead)

T5 → Rahul (he met the managing director; personal touch)

The five picks are made as one batch decision in priority order, not five separate guesses — each pick already counts the load added by the one before it, so the same "free" expert can never win every task. Once assigned, the tasks are *worked on* in parallel by their owners, except where dependencies say otherwise.

6.  Because this is a brand-new project, the plan is not silently activated. Akash (sales lead) gets an approval request (approvals: entity_type = plan_change, "New project + plan v1 with 5 tasks — confirm team and dates"). He opens it, changes nothing, taps Approve (action_plans.status = active, approvals.status = approved).

7.  The moment the plan goes active, everyone is notified on their own phone: Meera, Priya, Mithun, and Rahul each see their tasks with due dates and the AI's reason for picking them. They are all added to project_members.

8.  The [Communication Engine] drafts T5 right away — a thank-you email to Mr. Singhania from rahul@yuvipep.com, summarising what was agreed and what happens next ("content plan by 14 Nov, client staff demo before the programme"). The [Approval Engine] applies the org rule (client messages → sales_lead approves): Akash gets it, approves, and it is sent (outbound_messages, threads row created for Harish/email). T5 is auto-marked done (action_items.completion_method = system) and a progress_events row (task_done) is written.

9.  From this second onwards, the [Sync Engine] owns the heartbeat of the project: it watches every event, chases every task, and keeps the plan alive. That is the subject of the rest of this document.

Behind the scenes: tables written: leads, contacts, consent_records, meetings, transcripts, projects, stakeholders, action_plans, action_items, client_commitments, assignments, project_members, approvals, outbound_messages, threads, progress_events, ai_decisions, notifications.

If things go differently:

Mr. Singhania refuses recording → Rahul types short notes instead; the Planner works from typed notes (meetings.audio_path empty, notes as transcript source).

The discussion is vague (no program, no dates) → the Planner does NOT create a project; it creates 1–2 simple follow-up tasks on the lead, and the lead stays open. Projects are only born when there is a concrete piece of work.

Akash rejects the plan with a note ("Meera is busy with the Sunrise project — give content plan to Sourav") → the Assignment Engine reassigns T1 to Sourav, records the override in assignments (status = overridden) and ai_decisions.human_override.

### Workflow 2 — A business card at an expo becomes a lead

The story. Priya is at an services expo. The director of Little Flowers Client stops by, chats for five minutes, and hands over his card. There is no meeting, no recording — just a card and a short chat.

Step by step:

1.  Priya photographs the card in the app and speaks one line: *"Met at EdTech Expo, interested in robotics for cohorts 6–8, call next week."*

2.  Vision/OCR reads the card → contacts (name, email, phone, needs_review = true if confidence is low). A lead is created (leads.source = "expo", state = open, owner = Priya).

3.  Priya's spoken line is saved as client_intelligence and into memory (memory_chunks), so any future AI step knows the context.

4.  The [Communication Engine] drafts the intro message from the org's intro template (message_templates, kind = intro), filling variables (contact name, client, Priya's name). Priya approves with one tap; it goes out from priya@yuvipep.com (outbound_messages, kind = intro; a threads row is created on the lead — lead_id and contact_id set, project_id empty until a project is born).

5.  The [Assistant Engine] creates one follow-up as part of the same card-scan flow (followups.due_date = +7 days, channel = call, owner = Priya). No project yet — there is no concrete work, and the Planner only enters when a project is born.

6.  Next week the Sync Engine reminds Priya. If the call goes well and a client visit is booked, Workflow 1 takes over from there.

If things go differently:

OCR is unsure about the email → the contact is flagged (contacts.needs_review) and the intro email is held until Priya fixes it. Nothing is sent to a possibly-wrong address.

The director replies to the intro email ("send me a brochure") → Workflow 19 (inbound handling) picks it up, even though no project exists yet — the Inbound Engine matches by contact and lead.

### Workflow 3 — The proposal: built by AI, checked by people, sent by the right person

The story. Continuing the VG programme. Priya's task T2 ("Build draft proposal") is due. The proposal must be correct, priced from the table, internally approved, and sent from the right address.

Step by step:

1.  Priya opens T2 and says: *"Create the programme proposal for VG — 7 days, cohorts 5 to 9, around 400 participants."*

2.  The [Document Engine] builds it: template = current proposal_templates for the Programme program; prices = current pricing_tables version (say v4: ₹300 per participant, min 350 participants). It fills proposals.line_items (400 × ₹300 = ₹1,20,000 + materials kit ₹6,000), locks template_version and pricing_version, renders content_md, and generates the PDF (deliverables row, type = proposal, status = draft).

3.  Priya reads it and edits by voice: *"Add a line that the client provides the equipment room, and mention the client staff demo day."* Every edit is a proposal_revisions row.

4.  Priya marks it ready. Because projects.value_estimate > ₹1,00,000, the org's approval rule fires (proposal over ₹1 lakh → sales_lead approves). The [Approval Engine] creates an approval for Akash with the PDF attached.

5.  Akash reviews on his phone, replies with a note: *"Good. Change payment terms to 50% advance."* — status = rejected with note. The Document Engine applies the change (new proposal_revisions row), and re-requests. Akash approves (approvals.status = approved, proposals.status = internal_review → approved_internally).

6.  Now the send: the email is drafted To managing director@svs.edu.in, CC akash@yuvipep.com, From rahul@yuvipep.com — from Rahul, not Priya, because Rahul is the face the managing director knows (projects relationship: Rahul had the meeting; the engine picks the sender by thread history). Rahul gets the final one-tap: Approve and Send.

7.  Sent → outbound_messages (kind = proposal, thread = Harish/email), proposals.sent_at, progress_events (proposal_sent), T2 marked done, and projects.status moves planning → proposal_stage. The [Sync Engine] schedules a follow-up: if no reply in 4 days, nudge (Workflow 5).

If things go differently:

The managing director's email bounces → message_delivery_log records it, the Inbound/webhook flow flags the message failed, Rahul gets a task "Confirm managing director's email address" (P1), and the thread is paused.

Priya tries to change the per-participant price by voice → not allowed: prices only come from pricing_tables. The app offers "request a special price" instead, which is Workflow 4's discount route.

### Workflow 4 — The managing director asks for changes: the price, or the content itself

Story A — the ask is about money. Two days after the proposal, Mr. Singhania replies by email: *"The proposal looks good, but ₹1.26 lakh is above our budget. Can you do it in one lakh?"*

Step by step:

1.  The email arrives via the org's connected mailbox. The [Inbound Engine] creates inbound_messages: matches sender → contact Harish → project VG Programme → the proposal thread. It classifies: intent = change_request, sentiment = positive, ai_summary = "Accepts scope, asks price ₹1,26,000 → ₹1,00,000 (~21% discount)", extracted_points = [{"type":"discount_request","from":126000,"to":100000}].

2.  This is a price matter, so the engine does NOT draft a casual reply. The org's approval_rules say: discount > 10% → org_admin decides, sales_lead recommends. The [Approval Engine] opens an approval (entity_type = price_change) for Akash first.

3.  Akash gets the context card on his phone: proposal, requested discount, project value, and client intelligence ("400 participants, wants December, chain potential: no"). He recommends: *"Offer ₹1,10,000 as a special price — the December slot and a promised testimonial justify the concession."* His recommendation goes to Ananya (org_admin), who approves the special price (approvals chain: two linked rows — Akash’s stage = recommend, then Ananya’s stage = decide joined by chain_parent_id — both approved; everything logged in ai_decisions).

4.  The [Document Engine] rebuilds the proposal: new proposal_revisions with the approved line items (the special price is entered by Akash as an approved override — recorded with who/why, never invented by AI) and regenerates the PDF; the [Communication Engine] drafts the reply email: warm, thanks him, offers the special price of ₹1,10,000, from rahul@yuvipep.com.

5.  Rahul taps Approve and Send. The thread now shows: proposal → managing director's ask → our counter. The [Planner Engine] updates client_commitments ("Revised offer sent — awaiting decision") and the Sync Engine sets a 3-day reply watch.

6.  Mr. Singhania replies: *"Agreed. Let's proceed."* → Inbound Engine: intent = approval. projects.status → agreed, proposals.status = accepted, progress_events (deal_agreed). The Planner proposes plan v2: preparation tasks become active (Workflow 8 continues this).

Story B — the ask is about content, not money. A different reply arrives instead: *"The proposal looks fine on price, but the content plan inside is too advanced for cohorts 5–6. Please simplify those two days, and add one session on internet safety."*

1.  The [Inbound Engine] classifies it: intent = change_request, change_type = content — not price, so no money approval chain. extracted_points = [{"type":"content_change","detail":"simplify days 1–2 for cohorts 5–6"}, {"type":"content_change","detail":"add internet safety session"}].

2.  The [Planner Engine] creates one task: "Revise content plan per managing director's feedback" (P1, visible_to_client = true, linked to the content plan deliverable and to the reply). The required skill is judged by the model against the org's skill taxonomy — here curriculum_design → Meera; on a lab-fit-out project the same ask would route to whatever skill fits that work, and if nothing in the taxonomy fits, the task routes without a skill for a human to confirm. A short acknowledgement is drafted for Rahul to one-tap ("on it — revised version within two days") so the client is never left hanging.

3.  Meera fulfils the task whichever way she prefers — both paths are first-class:

AI-assisted path: she asks the [Document Engine] to redraft the two days and add the safety session, reviews the result, and saves it as content plan v2 (deliverables.source = ai_generated).

Manual path: she edits the document herself in Word, exports the PDF, uploads it straight onto the task (deliverables v2, source = manual_upload, uploaded_by = Meera), and marks the task done (action_items.completion_method = manual_upload). The system never forces the AI path — an uploaded file is a fully valid way to finish any task, and the rest of the machine treats it exactly like a generated one.

4.  Before anything is sent, the coverage check runs: the draft reply lists the managing director's asks one by one against the new document; if the uploaded version does not clearly answer one of the extracted points, that point is flagged to Meera. The AI checks completeness — it never blocks the human.

5.  Task done + visible_to_client → the [Communication Engine] drafts the reply with the revised PDF attached ("both changes made — simplified days 1–2, new internet-safety session on day 4"), the proposal is re-issued as a revision (proposal_revisions) with the new content plan, Akash approves, Rahul sends. The commitment is kept, and the thread shows ask → fix → delivery in one clean line.

If things go differently:

Ananya rejects any discount → the Communication Engine drafts a polite "value justification" reply (with Akash's talking points), and the project stays in negotiation.

The managing director goes silent after the counter → the follow-up ladder (Workflow 5).

The managing director replies with something ambiguous ("let me think, also can you do it in Hindi?") → intent = question + unknown mix, status = needs_human; Rahul is asked to read it himself; his answer teaches the thread.

The email mixes both asks ("reduce the price AND simplify the content plan") → the Inbound Engine splits the extracted points; Story A's approval chain and Story B's revision task run in parallel; one combined reply goes out at the end, answering both.

Meera's uploaded PDF misses one asked point → the coverage check names exactly which point is unanswered; she either fixes the file or tells the AI to address it in the reply ("internet safety will be a printed handout instead").

### Workflow 5 — Silence: the follow-up ladder

The story. Green Valley Client received a proposal from Rahul twelve days ago. No reply at all.

Step by step:

1.  When the proposal was sent, the [Sync Engine] started a reply watch (no inbound_messages on the thread since outbound_messages.sent_at).

2.  Day 4, no reply → the Communication Engine drafts a gentle email nudge ("just checking you received it, happy to answer questions"), Rahul one-taps, sent. (followups row, channel = email, linked to the thread.)

3.  Day 8, still nothing → drafts a short WhatsApp message instead (the engine switches channel using stakeholders.preferred_channel order and what has already been tried). Rahul approves, sent.

4.  Day 12, still nothing → no more automatic messages (org rule: max 2 unanswered nudges). Instead a call task is created for Rahul (action_items, P2, "Call Green Valley managing director — proposal unanswered 12 days") and the lead is flagged.

5.  Day 30 (org_settings.lead_cold_after_days), still nothing → the Sync Engine suggests leads.state → cold (leads.suggested_state), Rahul confirms. The project (if one exists) goes on_hold. A quiet re-engagement reminder is scheduled for next term (Workflow 28).

6.  Any reply at ANY point kills the ladder instantly: the Inbound Engine matches the thread, cancels pending nudges (reminders cancelled), and routes by intent.

If things go differently:

The managing director replies to the WhatsApp, not the email → same thread family via stakeholder match; the conversation continues on WhatsApp because that is where they answered.

Rahul meets the managing director by chance and they talk → Rahul dictates a note; the Planner treats it like meeting input and re-plans; the ladder resets.

### Workflow 6 — The second meeting: the plan learns

The story. VG programme is agreed. Rahul and Mithun visit the client for a kickoff meeting with Mr. Singhania and Mrs. Kavita Menon (programme coordinator). New facts emerge: the client wants the programme 1–7 December, wants a sponsors' demo on the last day, the lab has only 30 workstations (so batches are needed), and Mrs. Menon will be the day-to-day contact.

Step by step:

1.  Rahul records the meeting (meetings, project_id = VG Programme, meeting_no = 2, meeting_type = kickoff, attendees noted).

2.  Pipeline runs. The [Planner Engine] does not create a new plan from scratch — it loads plan v2 (current active), the open tasks, the commitments, and the client intelligence, and merges the new transcript into it. Output: plan v3 (action_plans.trigger = new_meeting, changes_from_previous written by the AI):

NEW: "Design batch schedule for 30-equipment room (~400 participants → batches)" → required_skill = scheduling → Mithun.

NEW: "Plan sponsors' demo session for Day 7" → Sourav + Shyam (media coverage).

CHANGED: all delivery dates now anchored to 1–7 Dec (action_items.due_date shifted; the AI shows old → new).

NEW stakeholder: Mrs. Kavita Menon added (stakeholders, role = academic_coordinator, receives_progress_updates = true).

NEW commitment: "Sponsors' demo on Day 7" (client_commitments).

UNTOUCHED: tasks already done stay done; in-progress tasks keep their assignee.

3.  The re-plan goes to Akash as an approval (plan_change) with a clean diff view: "3 added, 4 dates moved, 1 new stakeholder." He approves. v3 becomes active; v2 is superseded (never deleted).

4.  Everyone affected is notified with only their own changes: Mithun sees the two new scheduling tasks; Sourav sees the sponsors' demo; Meera sees her content plan deadline unchanged. Nobody gets noise about other people's tasks.

5.  The [Communication Engine] drafts a kickoff summary email to BOTH stakeholders (Harish + Kavita, per receives_progress_updates), listing the agreed dates and what YuviPep will deliver. Akash approves; sent; commitments updated.

Behind the scenes: the merge is the heart of the Planner Engine. Its inputs every time: active plan + open/in-progress/done tasks + commitments + conflicts + full thread history + new transcript. Its output is always a NEW version with an AI-written diff — never an in-place edit. This is what makes "n meetings on one project" safe.

If things go differently:

The new meeting contradicts the old one → Workflow 7 (conflict).

The meeting was with a different client entirely (Rahul picked the wrong project) → the Planner notices the transcript doesn't match the project context (client name, people) and flags it for Rahul before merging anything.

### Workflow 7 — Two people said different things: conflicts

The story. In Meeting 1, Mr. Singhania said "7 days." In Meeting 3, Mrs. Menon says "let's compress it to 5 days, exams are close." Both are real instructions from the client — and they disagree.

Step by step:

1.  While merging Meeting 3, the [Planner Engine] checks new facts against stored ones (client_commitments, projects.objective, client intelligence). "5 days" collides with "7-day programme" (source: Meeting 1, the decision maker).

2.  The AI does not silently pick a side. It writes a conflicts row: description, source_a = meeting 1 (Harish, decision_maker), source_b = meeting 3 (Kavita, influencer), raised_to = Akash. The re-plan is held as draft (action_plans.status = draft) — dates are NOT changed yet.

3.  Akash gets the conflict card: who said what, when, and their stakeholders.influence. He decides the client must confirm. He taps "ask the client" — the [Communication Engine] drafts a short, diplomatic email to Mr. Singhania (CC Mrs. Menon): "We can do either 7 days as planned or a compressed 5-day version; here's what changes; please confirm."

4.  Mr. Singhania replies "make it 5 days, Kavita is right." → Inbound Engine: intent = change_request, links to the conflict. conflicts.status = resolved (resolution_note filled).

5.  Now the held plan proceeds: the Planner produces v4 for a 5-day format — content plan task reopens for compression (new task for Meera, source = ai_refinement), batch schedule redone, pricing checked (5 days may change price → if it does, the price-change approval rule fires again like Workflow 4).

6.  Everything is traceable: months later anyone can ask "why did this become 5 days?" and the Assistant Engine shows conflict → email → managing director's reply → plan v4.

If things go differently:

Akash resolves it himself ("Managing Director already told me 5 days on a call") → he resolves the conflict manually with a note; no client email needed.

The two sources are equal-weight and the client is unreachable → the plan stays held; the Sync Engine reminds Akash daily; the project health goes at_risk with reason "unresolved conflict blocking re-plan."

### Workflow 8 — "We're agreed" — switching from selling to delivering

The story. The VG deal is agreed (end of Workflow 4). A sales-phase project must now become a delivery machine: ops takes co-ownership, preparation tasks activate, and the money trail starts.

Step by step:

1.  projects.status → agreed triggers the [Planner Engine] phase shift: it generates the preparation wave of plan v3 — every task with phase = preparation that was waiting ("draft" tasks are activated), plus standard ones from the program's playbook (playbooks — the per-program checklist the Org Admin maintains, with improvement suggestions from the [Knowledge Engine]): specialist allocation, materials procurement, batch schedule, client staff demo, advance invoice.

2.  The [Assignment Engine] staffs the wave: Mithun becomes projects.ops_owner_id (operations lead), Sourav + Baski assigned as specialists (android expert first), Vikram gets "Raise 50% advance invoice" (invoicing expert; invoices row, status = draft), and all are added to project_members.

3.  The [Approval Engine] routes the advance invoice: amount from the accepted proposal (proposals.total_amount × 50%) → Akash approves → the [Communication Engine] emails it — and here the stakeholder table earns its keep: the invoice goes To Mr. Ramesh Gupta (accountant, the payments gatekeeper — added as a stakeholders row, influence = gatekeeper, when the client shared billing details), CC the managing director. Not everything goes to the managing director.

4.  leads.state moves active → execution_in_progress (suggested by the system, confirmed by Akash — same human-confirm pattern as today).

5.  The Sync Engine starts delivery-grade monitoring: project health checks daily, commitment dates vs task dates cross-checked, and the weekly client progress report is scheduled (Workflow 17).

If things go differently:

The client signs but wants to start in February → the whole plan shifts; the Planner re-dates the preparation wave and the Sync Engine lowers the reminder intensity until January.

The advance never arrives → Workflow 25 (payment chasing) runs before delivery is allowed to start; the org rule "no delivery before advance" makes T-day tasks blocked with blocked_reason = "advance unpaid."

## PART 2 — PEOPLE AND TASKS (Workflows 9–16)

### Workflow 9 — How the AI picks the right person (deep dive)

The story. Plan v3 of the VG programme has a new task: "Design batch schedule for 30-equipment room." Who should do it? This workflow shows exactly how the Assignment Engine thinks, every single time.

Step by step:

1.  Input: the task (action_items.required_skill = scheduling, phase = preparation, priority = P2, due in 6 days) and the project (project_members list).

2.  The engine builds the candidate list, in this strict order:

a. Project members whose user_skills match the required skill (Mithun: scheduling expert).

b. If none: org users in the right department with the skill (any operations person with scheduling).

c. If still none: the phase owner (ops_owner_id) gets it by default, flagged "no skill match."

3.  Each candidate is scored on facts, not vibes:

Skill level — expert > good > basic (user_skills.level).

Load — open + in_progress tasks vs users.max_open_tasks (Mithun: 5/8).

Leave — users.on_leave_from/to vs the task window (Mithun available).

Continuity — has this person done related tasks on this project? (Mithun did T3, T4.)

Due-date fit — can they realistically take it before the deadline given their other due dates?

Field days — delivery days, demos, and travel booked on other projects count as busy time (resource_bookings, via the [Resource & Calendar Engine]).

4.  Winner: Mithun. The engine writes action_items.assignee_id = Mithun, assigned_by = "ai", and — most importantly — assignment_reason = "Mithun: scheduling expert, 5/8 load, did both earlier scheduling tasks." A row goes to assignments (status = proposed) and ai_decisions (confidence 0.94).

5.  Who confirms? Controlled by an org switch (org_settings.assignment_mode):

auto — assignment is live immediately (status = auto_accepted); the assignee can decline (Workflow 16).

lead-confirm — the phase lead (ops lead for preparation tasks, sales lead for sales tasks) gets a batch confirmation: one screen, all proposed assignments, confirm-all or change any — recorded as assignments.status changes (proposed → accepted / overridden), never as approvals rows. YuviPep starts in lead-confirm mode.

6.  Mithun gets the notification with the reason shown. People trust assignments far more when they see *why* they were picked.

7.  A plan is assigned as one batch, in one pass. When a plan version activates, its tasks are assigned in priority-then-due-date order, and the engine updates its working load counts after every pick — decision #3 already includes the load added by decisions #1 and #2. Five tasks never independently pick the same least-loaded person five times.

8.  Assignment can wait for a predecessor. A task whose right owner depends on how an earlier task ends is marked assign_on = when_ready (the Planner sets this; a lead can too). It stays deliberately unassigned until its depends_on_ids clear — then the [Sync Engine] calls the Assignment Engine with *fresh* data: today's loads, today's leave, and the predecessor's actual outcome ("vendor PrintCraft won the selection → the print-liaison task goes to whoever ordered from PrintCraft before"). And even for tasks assigned at plan time, the moment a task becomes ready the Sync Engine re-validates its assignee (still available? not on leave? not overloaded?) and proposes a reassignment if the picture has changed since the plan was made.

If things go differently:

Two candidates tie → the engine prefers the lower load; if still tied, the one with fewer P1 tasks; a tie after that goes to the lead as a question, not a coin flip.

Nobody has the skill at all → the task is assigned to the phase lead with a flag "skill gap: robotics" and ai_decisions.needs_human = true; the lead may add a member or outsource.

The task is P1/urgent → capacity limits can be exceeded, but the engine must then also propose which of the assignee's other tasks to postpone, and says so in the reason.

A task assigned at plan time becomes ready weeks later and its assignee's world has changed (now on leave, now overloaded) → the ready-time re-validation catches it and runs a normal reassignment with a handover note — the plan never relies on a weeks-old guess.

### Workflow 10 — The three-level nudge ladder

The story. Sourav has "Prepare Day-1 and Day-2 lab exercises" due Thursday. Thursday passes. Nothing happens. How the system chases without becoming annoying — and without letting things rot.

Step by step:

1.  Thursday 18:00 (org's workday end): the [Sync Engine] daily sweep finds the task overdue (action_items.due_date < now, status ≠ done). It writes progress_events (task_overdue) and schedules a Level 1 reminder (reminders.level = 1).

2.  Friday 09:00 — Level 1, gentle, private: push notification to Sourav only. *"Reminder: 'Day-1/2 lab exercises' was due yesterday. Reply with a new date if you're blocked."* Sourav can tap: Done / Give new date / I'm blocked. (action_items.reminder_level = 1.)

3.  Sourav taps "Give new date: Monday." The engine checks the ripple before accepting: does any dependent task or client_commitments.due_date break? Here, the specialist rehearsal depends on it but has slack — accepted. Due date moves, the reason is logged, ladder resets. If the new date broke a client commitment, the change would instead go to Mithun (phase lead) as an approval.

4.  Suppose Sourav had ignored it. Monday 09:00 — Level 2, firm: push + WhatsApp to Sourav (*"2nd reminder — task is 4 days late and blocks specialist rehearsal"*), and the task turns red in his list. (reminder_level = 2.)

5.  Two more workdays of silence → Level 3, escalation: Mithun (ops lead) gets a card: task, days late, what it blocks, Sourav's current load, and one-tap options — Reassign (engine already suggests Baski) / Call Sourav / Extend. reminders.level = 3, progress_events (task_escalated), project health → at_risk with reason.

6.  The ladder is org-configurable (org_settings: nudge gaps, quiet hours, channels per level). Reminders never fire on leave days or outside working hours.

If things go differently:

Sourav marks the task done at any point → all pending reminders for it are cancelled instantly; if visible_to_client = true, the client-update flow (Workflow 14) fires.

The task was blocked, not ignored → the moment Sourav taps "I'm blocked" with a reason, the ladder stops and the blocked flow (Workflow 11) starts instead. Chasing a blocked person is pointless — chase the blocker.

The assignee is the lead himself (Mithun overdue) → Level 3 escalates upward to the org admin.

### Workflow 11 — Blocked: dependencies and resequencing

The story. Baski's task "Print 400 participant workbooks" depends on Meera's "Finalise content plan" (action_items.depends_on_ids). Meera's content plan is stuck because the client hasn't approved it. One block, three tasks deep.

Step by step:

1.  Meera's task "Get content plan approved by client" is waiting on Mrs. Menon. Meera taps "I'm blocked — waiting for client approval since 3 days." → action_items.blocked = true, blocked_reason recorded, progress_events (task_blocked).

2.  The [Sync Engine] walks the dependency chain: content plan approval → blocks workbook printing → blocks materials dispatch. It marks the downstream tasks as at-risk (not blocked yet — they still have slack) and recomputes: if approval doesn't arrive within 4 days, the programme start date itself is at risk. Project health → at_risk, reason written.

3.  Because the blocker is the *client*, the engine does not nudge Baski or Meera — it drafts a client chase: the [Communication Engine] writes a polite WhatsApp to Mrs. Menon (her preferred_channel): *"Sharing a gentle reminder about the content plan we sent Monday — a quick nod lets us start printing the workbooks on time."* Approval by Akash, then sent.

4.  Mrs. Menon replies "Approved, go ahead" → [Inbound Engine]: intent = approval, matched to the thread and — via extracted_points — to the blocked task. action_items.blocked = false, progress_events (task_unblocked). The Sync Engine instantly notifies Meera and un-flags the downstream chain. Baski's printing task flips to ready with a fresh due date — and because every task is re-validated at the moment it becomes ready, the Sync Engine first confirms Baski is still available and within capacity before waking it.

5.  client_commitments "Content plan approved by client" → kept. The whole episode is visible on the project timeline.

If things go differently:

The client approval takes so long the timeline breaks → the Planner proposes a re-plan (shift programme start or run printing in parallel at risk); Akash decides; if dates move, the client gets a date-change email (Workflow 18 in reverse — us asking them).

A task is blocked by an internal person → normal nudge ladder targets the blocking task's assignee, and the blocked person is told "your task is waiting on X, we're chasing it."

Circular dependency created by a re-plan (A needs B, B needs A) → the Planner detects the cycle at plan-validation time and refuses to activate the version until a human untangles it.

### Workflow 12 — Someone goes on leave

The story. Meera applies for leave, 20–24 November. Her content plan task for VG is due 21 November. Nobody should have to remember to hand it over — the system should.

Step by step:

1.  Ananya (org admin) records the leave (users.on_leave_from/to = 20–24 Nov). This writes progress_events (leave_recorded).

2.  The [Sync Engine] immediately cross-checks: which of Meera's open tasks (across ALL projects) fall due or run through 20–24 Nov? Finds two — the VG content plan (due 21st, P1, blocks printing) and a Sunrise-project task (due 28th, safe).

3.  For the safe task: nothing happens. No noise.

4.  For the endangered task, the [Assignment Engine] runs (Workflow 9 logic): best alternative = Sourav (android good, teaching expert, 4/8 load). It proposes a reassignment (assignments: Meera → Sourav, reason = "Meera on leave 20–24 Nov; task due 21 Nov; blocks workbook printing").

5.  Mithun (phase lead) confirms. Sourav is notified WITH a handover package the AI assembles automatically: the task, Meera's progress so far (progress_percent = 60, her attached draft in deliverables), relevant thread history, and the commitment date it serves.

6.  Meera gets a courtesy note: "While you're away, the VG content plan moves to Sourav. Your Sunrise task (due 28th) stays with you." On the 25th she is back; nothing returns to her automatically — reassignment is not a loan, it is a transfer (avoids ping-pong).

If things go differently:

Leave is recorded AFTER a reminder already fired at Meera → the Sync Engine cancels her reminders for the leave window and apologises in the notification. Never nudge people on leave.

No good alternative exists (only Meera has the skill) → the engine proposes the honest option: pre-pone. It asks Meera (before leave) "can you finish by the 19th?" and tells Mithun the risk either way.

Emergency leave, same day → identical flow, but all her due-this-week tasks are treated as endangered and the batch goes to Mithun as one card.

### Workflow 13 — Someone is overloaded

The story. Priya has quietly become the bottleneck: 9 open tasks against her max_open_tasks of 8, three of them P1, across three projects. Nobody noticed — except the Sync Engine.

Step by step:

1.  The daily sweep computes load for every user. Priya breaches her cap → progress_events (user_overloaded), and an alert card goes to her manager (department = sales → Akash).

2.  The card is not just an alarm — the [Assignment Engine] attaches a rebalance proposal: her two lowest-priority, not-yet-started tasks, with the best alternative assignee for each (one to Rahul, one back to Akash himself), each with reasons.

3.  Akash confirms one, rejects the other ("Priya knows this client, keep it, extend the date instead"). Confirmed moves are executed as normal reassignments (assignments, handover notes to the receivers); the rejected one gets its due date extended with the reason logged.

4.  Priya is told what was moved and why. The engine also whispers to future planning: while she is above the org’s high-load threshold (org_settings.high_load_caution_pct — 80% here), new assignments avoid her unless she is the only skill match (this is just the load factor in Workflow 9 doing its job).

If things go differently:

Everyone in the department is overloaded → the alert goes up a level to the org admin with a hiring/priority message: "Sales team at 94% average load; these 5 tasks have no good owner." The AI never hides a capacity problem by silently stretching due dates.

The overload is caused by one huge project → the card suggests adding a member to that project instead of shuffling tasks.

### Workflow 14 — A task finishes and the client hears about it

The story. This is the heart of the whole platform: work completes inside YuviPep, and the client automatically hears about it — with a human yes in between. Meera finishes the VG content plan.

Step by step:

1.  Meera marks "Prepare day-wise content plan" done, attaches the PDF (deliverables: type = content plan, v1, status = internal_review), writes a result note. → progress_events (task_done).

2.  The [Sync Engine] reacts to the event, in order:

Unblocks dependents: nothing waiting here yet.

Checks commitments: client_commitments "Share content plan within a week" is linked → this completion should be *sent*, not just logged.

Sees action_items.visible_to_client = true → triggers the Communication Engine.

3.  The [Communication Engine] drafts the client email: To Harish, CC Kavita (both have receives_progress_updates = true), From rahul@yuvipep.com, subject on the existing thread, body written from the task result + commitment ("as promised on Monday, please find the 7-day content plan attached; we'd love Mrs. Menon's feedback by Friday so printing starts on time"), content plan PDF attached. It also proposes the *next* commitment (feedback by Friday) — drafted, not yet promised.

4.  The [Approval Engine] applies the rule (client message → sales_lead): Akash reviews, tweaks one sentence, approves. Sent (outbound_messages.triggered_by = task_completed, thread updated).

5.  On send: client_commitments "share content plan" → kept ✅; a NEW commitment "client feedback by Friday" is created (this one is the client's promise to us — commitments work both directions, promised_by = client side); the Sync Engine sets a Friday watch on it; deliverables.status = sent.

6.  Rahul, Priya, Mithun see the project timeline update: "Content plan sent to client ✅ — awaiting feedback by Fri." Everyone is in sync without a single status meeting.

If things go differently:

Akash rejects the draft ("don't promise Friday, exams are on") → back to the Communication Engine with his note; redraft; re-approve. The task stays done; only the message loops (Workflow 26 covers rejection loops in detail).

The completed task is internal-only (visible_to_client = false, e.g. "book specialist travel") → no client message; just events, timeline, and unblocking. The flag is what separates "the client cares" from "only we care," and the Planner sets it at task-creation time (a human can flip it).

### Workflow 15 — A new employee joins mid-project

The story. YuviPep hires Divya Menon, a junior specialist (android: good, teaching: basic). Three projects are running. She should become useful on day one without anyone writing her a manual.

Step by step:

1.  Ananya registers her (users: role = operations_agent, department = operations, designation = Junior Specialist) with skills (user_skills) and capacity (max_open_tasks = 5 for a junior).

2.  From this moment she simply exists in the Assignment Engine's candidate pool. Nothing else is needed for future tasks — the next android-skill task naturally scores her.

3.  Mithun adds her to the VG project (project_members, role_in_project = assistant_specialist, added_by = Mithun). The system generates her an onboarding brief automatically from project data: objective, plan v4 summary, her teammates, the client stakeholders, upcoming dates, and the open tasks in her skill area. (This is the Assistant Engine reading projects, action_plans, client_commitments — no human writes it.)

4.  The [Assignment Engine] proposes starter tasks: it prefers giving juniors P2/P3 tasks with an expert nearby ("Assist Sourav on Day-1/2 lab exercises" rather than solo ownership). Mithun confirms.

5.  Her first reassignment-in: if any overloaded member (Workflow 13) has tasks matching her skills, the rebalance proposal now includes her.

If things go differently:

She is hired for a specific project only → membership in one project; the candidate pool rule (Workflow 9 step 2a) keeps her out of other projects unless a lead adds her.

Her OCR'd offer-letter skills were overstated → leads can edit user_skills anytime; assignment history (assignments.reason) shows which decisions used the old levels.

### Workflow 16 — "I can't do this" — declining a task

The story. The Assignment Engine gives Baski "Design robotics demo for sponsors' day" (robotics expert — perfect match on paper). But Baski knows he'll be in Kharagpur that whole week for the Sunrise delivery. Paper is wrong; he declines.

Step by step:

1.  Baski opens the task and taps Decline, choosing a reason (busy / wrong skill / on-site elsewhere / other) + one line: "On-site at Sunrise all of that week."

2.  assignments row → status = declined with the reason; action_items.status = declined (task has no owner now); progress_events (task_declined).

3.  The [Assignment Engine] re-runs immediately, excluding Baski, and — this is the learning part — notes the *reason*: "on-site elsewhere" is a calendar fact, so it asks the [Resource & Calendar Engine] why the booking was missed. Answer: Sunrise's delivery week was extended only yesterday and the extension never became a resource_bookings row. The gap is recorded in ai_decisions, and the missing booking is registered on the spot — the same surprise can never happen twice.

4.  Next best: Sourav (robotics basic BUT teaching expert + already doing the sponsors' demo) vs asking Mithun. Confidence is low (0.55, skill downgrade) → the proposal goes to Mithun as a question, not an auto-assignment: "Baski declined (on-site). Options: Sourav (weaker robotics, already owns sponsors' day) / split the task / pull Baski for one day."

5.  Mithun picks "split": Baski designs remotely (2 hrs), Sourav delivers. The engine creates the split as two linked tasks (parent task kept, two children with depends_on_ids), assigns each, and everyone sees the resolution on the timeline.

If things go differently:

Declines with no reason are allowed but always escalate to the lead (silent declining can't be scored).

Serial decliner (3+ declines in a month) → a quiet stat on the lead's team view. The system never shames publicly; it informs the manager.

The task was P1 and due tomorrow → decline still allowed, but the re-assignment goes to the lead as an urgent card with a phone-call suggestion, because software should not negotiate emergencies.

## PART 3 — TALKING TO THE CLIENT WHILE WORK HAPPENS (Workflows 17–22)

### Workflow 17 — The weekly report the managing director actually reads (and the daily digest the team actually uses)

The story. The VG programme preparation is in full swing. Mr. Singhania should never have to call and ask "what's happening?" — and the YuviPep team should never need a status meeting.

Step by step (client side — weekly):

1.  Every Friday 16:00 (org setting), the [Assistant Engine] builds the client progress report for each project in preparation/delivery whose stakeholders have receives_progress_updates = true. Sources: progress_events this week, client_commitments (kept/open), deliverables sent, upcoming dates from the plan.

2.  The draft is plain and honest, in the client's language: *"Done this week: content plan finalised and shared, specialists confirmed (Sourav & Divya), batch schedule agreed. Next week: workbooks printed, client staff demo on Wednesday. On track for 1 December."* No internal names of tasks, no jargon, nothing about internal delays unless a client-facing date moved.

3.  [Approval Engine]: Akash approves (or edits — his edits are learned as style notes for future drafts). Sent to Harish + Kavita on the project thread (digests row kind = weekly_project_client, outbound_messages.triggered_by = weekly_report).

4.  If a week was bad (health = delayed), the AI does not hide it — it drafts the honest version with the recovery step ("printing slipped 2 days; still safe for 1 Dec because..."). Akash decides how it is worded; the rule is only that the AI never silently skips a report.

Step by step (internal side — daily):

5.  Every workday 08:30, each staff member gets a personal digest (kind = daily_user): today's tasks across all projects, anything overdue, approvals waiting on them, replies that came in overnight for their projects. One screen, ordered by priority. No approval needed — it's internal.

6.  Each project also has a live timeline view (all progress_events humanised) — this replaces "quick sync" meetings.

If things go differently:

Nothing happened this week (project on_hold) → no client report is sent (a report saying "nothing happened" hurts); the Sync Engine notes the skip and tells Akash.

The managing director replies to a report ("great, but can Saturday's session start at 10?") → normal inbound flow (Workflow 18/19) — the report thread is a thread like any other.

### Workflow 18 — The client changes something big: a date shift, end to end

The story. Tuesday morning, Mrs. Menon emails: *"Our annual inspection got scheduled for 1–2 December. Can the programme start on 3 December instead, and still finish before the 10th?"* One sentence from the client — a dozen changes for us. This is the workflow that proves the promise of perfect sync.

Step by step:

1.  [Inbound Engine]: matches Kavita → VG project → thread. Intent = change_request, extracted_points = [{"type":"date_change","from":"1 Dec","to":"3 Dec","constraint":"end by 10 Dec"}]. Because a date change touches the plan, it is handed to the Planner, and an acknowledgement is drafted immediately (*"Got it, checking feasibility, we'll confirm by end of day"*) — Akash one-taps it so the client is never left hanging. (inbound_messages.status = processed, ai_summary stored.)

2.  The [Planner Engine] runs a feasibility pass BEFORE promising anything:

Specialist availability 3–9 Dec (asked of the [Resource & Calendar Engine]: leave, delivery days, and travel across all projects) — OK.

Venue/batch schedule — needs regeneration (Mithun's deliverable).

Materials delivery date 30 Nov — still fine.

Sponsors' demo was Sunday 7 Dec → now becomes Tuesday 9 Dec — client must be told this moves too.

Client commitments affected: 2 (client_commitments due dates).

3.  Feasible → the Planner drafts plan v5 (trigger = client_reply, trigger_ref = the inbound message): 9 tasks re-dated, batch schedule task reopened for Mithun, sponsors' demo moved, changes_from_previous written out. Status = pending_review.

4.  [Approval Engine] → Akash sees one card: the client's ask, the feasibility summary, the plan diff, and the drafted confirmation email (*"3–9 Dec works; note the sponsors' demo moves to Tuesday 9th — please confirm that's fine"*). One approval covers plan + reply — the drafted email rides on the plan-change approval as a bundled entity (approvals.bundled_entities) — so they succeed or fail together.

5.  Akash approves. In one transaction: v5 activates, all re-dated tasks notify their assignees (each sees only their own changes), the confirmation email is sent, both commitments are renegotiated (client_commitments.status = renegotiated with new dates), and the project timeline records the whole chain: inbound → feasibility → re-plan → confirmation.

6.  Kavita replies "Perfect, thank you!" → intent = acknowledgement; nothing to do but log it and mark the thread settled.

If things go differently:

NOT feasible (Sourav is delivering at Sunrise 3–6 Dec) → the Planner prepares options instead of a plan: (a) start 8 Dec, (b) swap specialist to Baski, (c) split the programme 3–4 + 7–9. Akash picks; the reply email offers the chosen option. The AI never says yes to the client before the feasibility pass says yes internally.

The ask arrives on WhatsApp as a voice note → speech-to-text first, then the identical flow. Channel changes nothing downstream.

Mid-re-plan, a second email arrives changing it again ("actually inspection moved, original dates fine!") → the Inbound Engine sees an open re-plan on the same topic, supersedes the draft v5 before it activates, and tells Akash the whole thing collapsed back to v4. Nothing half-applies.

### Workflow 19 — A question on WhatsApp: answered from what we know

The story. Mr. Singhania WhatsApps Rahul's business number: *"Will the programme also cover Kotlin, or only block-based apps? Sponsors are asking."*

Step by step:

1.  [Inbound Engine]: sender phone → contact Harish → VG project → WhatsApp thread. Intent = question, sentiment = neutral/positive. No plan impact → no Planner involvement.

2.  To draft the answer, the [Inbound Engine] gathers everything we hold that could answer — the program definition (programs.description), the deliverables (content plan v2 says Days 5–7 use Kotlin basics for cohorts 8–9), and client_intelligence — and the model judges, by meaning rather than shared words, which of those recorded facts genuinely answer THIS question and whether they suffice ("a real industry language" finds the Kotlin content plan even with zero words in common). The [Communication Engine] then composes strictly from the chosen facts — never from the model's general knowledge. Draft: *"Yes sir — cohorts 5–7 build block-based apps; cohorts 8–9 get an introduction to Kotlin on Days 5–7. It's all in the content plan Mrs. Menon has — happy to walk you through it."*

3.  Confidence is high (the content plan literally answers it) → normal approval: this is Rahul's personal WhatsApp relationship, so the draft goes to Rahul (org rule: WhatsApp replies on your own thread → you approve; sales lead only for email/commercial). Rahul reads, taps send.

4.  Thread updated; inbound_messages.status = processed. A client_intelligence note is added ("sponsors ask about Kotlin — selling point") because the Inbound Engine tags reusable facts.

If things go differently:

The AI cannot find the answer in our data ("will you provide certificates signed by the services board?") → no guessing: needs_human, and a task "Answer managing director's question re: board certificates" goes to Akash (P2). The draft shown to Akash says exactly why the AI stopped: "no data on board certification."

The question is commercial ("can we pay in 3 instalments?") → intent = question BUT topic = payment → routed like Workflow 4: approval rules for money override the casual path.

Harish messages at 22:30 → the reply is drafted at once but queued for the org's working-hours window (sending scheduler), unless Rahul overrides manually.

### Workflow 20 — Scope grows: "add cohorts 3 and 4"

The story. After the client staff demo goes well, Mr. Singhania is delighted: *"Include cohorts 3 and 4 as well — another 150 participants."* Everyone is happy. Happiness changes scope, price, batches, materials, and maybe specialists.

Step by step:

1.  [Inbound Engine] (or Rahul dictates it after a call): intent = change_request, type = scope_expansion, detail = +150 participants, cohorts 3–4.

2.  The [Planner Engine] feasibility pass: lab batches recomputed (needs 5 more batch slots — possible if daily hours extend), content plan needs a junior variant for cohorts 3–4 (new work for Meera/Divya), materials +150 kits (vendor lead time 6 days — tight but OK), specialists: Divya can own the junior batches.

3.  Money: scope change = price change. The [Document Engine] computes the delta strictly from pricing_tables (150 × ₹300 = ₹45,000; materials & workbooks are a flat line in the accepted proposal, so the vendor order grows but no new materials charge appears) and prepares a proposal amendment — a new proposals revision that references the accepted one, showing old total, addition, new total. Because the earlier deal had a special approved price (Workflow 4), the amendment applies the same per-participant rate ONLY if the original approval note allows it; otherwise the price-change rule fires again → Akash recommends → Ananya approves.

4.  Plan v6 drafted: the expansion's task wave is authored by the model from THIS project's own objective — here 6 new tasks (junior content plan, extra kits, batch schedule v3, Divya's prep, amended invoice, updated sponsors'-demo plan); on an incubation-centre project the same machinery authors floor fit-out and lab procurement tasks instead. Assignments proposed. One approval card to Akash: scope summary + plan diff + amendment PDF + drafted reply email. (The amendment's money never comes from the model — it is computed from the accepted proposal's locked per-unit line, whatever the unit: per participant, per seat, per rack.)

5.  Approved → reply goes to Harish with the amendment (*"wonderful news — here's the addition for cohorts 3–4; one signature and we fold them in"*), CC Ramesh Gupta because money changed. Tasks activate the moment the client confirms the amendment (they are created blocked with blocked_reason = "awaiting amendment confirmation" — work does not start on unconfirmed money; an org switch can relax this).

6.  Client confirms → tasks unblock, projects.value_estimate updated, invoice task re-computed, everyone notified. The whole expansion took two human approvals and zero meetings.

If things go differently:

The client wants the addition free ("adjust it in the same budget") → pure negotiation: routed to Akash as needs_human with the numbers laid out; the AI computes options (reduce kit spec, shorten junior track) but the humans decide.

Scope shrinks instead ("drop cohorts 8–9, exams") → same machinery in reverse: negative amendment, tasks cancelled (status = cancelled with reason, never deleted), materials order reduced if the vendor allows — and if it doesn't, the card tells Akash the sunk cost honestly.

### Workflow 21 — "Can you come tomorrow?" — the urgent request

The story. Wednesday 17:40. Mr. Singhania calls Rahul: the services minister is visiting the client Friday — can YuviPep run the client staff demo THIS Thursday (tomorrow) instead of next week, so it's fresh for the visit? Rahul says "let me confirm within the hour."

Step by step:

1.  Rahul dictates into the app: *"URGENT — VG wants client staff demo tomorrow 11 AM instead of next Wednesday. Minister visit Friday. I promised confirmation within the hour."*

2.  The word URGENT + the deadline routes this as P1. The [Planner Engine] runs an immediate (not batched) feasibility pass: Sourav's Thursday (checked with the [Resource & Calendar Engine]) — he has two P2 tasks, movable; demo kit — ready since Monday (deliverables.status = approved); travel — Mithun's logistics playbook needs a cab booked tonight.

3.  Within ~2 minutes Akash and Mithun get a joint urgent card (both must say yes — sales owns the promise, ops owns the delivery): feasibility summary, what gets postponed, the cab task, and the drafted confirmation WhatsApp to Harish. Their phones actually ring-style notify (P1 approvals override quiet settings — org rule).

4.  Both approve within 20 minutes. In one stroke: plan v7 (demo moved, Sourav's two tasks pushed with reasons, cab task created P1 for tonight), confirmation sent to Harish (*"Confirmed — Sourav will be there Thursday 11 AM"*), Sourav notified with the full picture, and a new commitment recorded.

5.  Thursday: the demo happens (Workflow 23 covers day-of execution). The postponed tasks were never lost — they carry assignment_reason history showing they moved for the VG urgency.

If things go differently:

Sourav is genuinely unmovable → the card shows options: Baski (robotics guy doing an android demo — flagged risk), or decline gracefully. If Akash declines, the AI drafts the no ("Friday morning instead?") — saying no well is also a communication task.

One approver responds, the other doesn't in 30 min → escalation call task to the silent one + the responder is told; the requester (Rahul) sees live status so HE can call. The system never lets an urgent promise die silently in an inbox.

### Workflow 22 — A complaint: "your specialist came late"

The story. Day 2 of the programme. Mrs. Menon WhatsApps: *"Yesterday's session started 40 minutes late and some class-6 kids had no working laptops. Please fix this today."* Negative sentiment, live delivery, reputation on the line.

Step by step:

1.  [Inbound Engine]: intent = complaint, sentiment = negative, urgency = high (project in delivery). Complaints have their own rule: they NEVER wait in a queue. Instantly: progress_events (complaint_received), project health → at_risk, and a P1 alert to BOTH the ops lead (Mithun — owns the fix) and sales lead (Akash — owns the relationship). The complaint is recorded as an incident (incidents row: severity = high, owner = Mithun) so it stays visible on the timeline until closed.

2.  The [Communication Engine] immediately drafts a holding reply (never auto-sent, but ready in seconds): *"We're very sorry — looking into both issues right now; you'll hear from us within the hour with the fix."* Akash approves from his phone in traffic. The client hears back in 8 minutes.

3.  Mithun investigates via the app: Sourav's Day-1 report (Workflow 23) already noted "cab delay + 4 dead laptops in lab." The fix tasks are created: "Leave 45 min earlier — standing instruction Days 2–7" (Sourav, P1) and "Arrange 5 spare laptops for remaining days" (Mithun → vendor, P1, due today).

4.  The substantive reply is drafted from the fix tasks: what happened (honest), what changes today (spare laptops arriving by noon, specialist on-site 8:30). Akash approves; sent; a client_commitments row per promise ("spare laptops by noon today").

5.  The Sync Engine watches those commitments hourly (delivery-mode cadence). Laptops arrive 11:40 → Mithun marks done → visible_to_client → short confirmation WhatsApp drafted and sent. Health returns to on_track. The incident stays permanently on the timeline for the closure report and for memory_chunks, and the [Knowledge Engine] proposes a playbook addition — "confirm working machines a day early" — which the org admin accepts with one tap; every future project at any client inherits the lesson.

If things go differently:

The complaint is unfair (specialist was on time; the client gate was locked) → the facts from the day-of report go to Akash; HE decides the tone; the AI drafts the gentle correction version and the diplomatic absorb version, and he picks. The AI never argues with a client on its own.

Repeated complaints (2+ on one project) → automatic escalation to org admin + a mandatory review meeting task; the weekly client report gains an "issues and fixes" section until health is restored.

## PART 4 — DELIVERY AND MONEY (Workflows 23–26)

### Workflow 23 — Programme day: running the show

The story. 3 December, Day 1 of the VG programme. Sourav and Divya are on-site. The system's job today is not planning — it is being a checklist, a scribe, and a wire back to base.

Step by step:

1.  07:00 — Sourav's daily digest is a day-of runsheet the Sync Engine assembled from the plan: departure time (from Workflow 22's standing instruction: leave 45 min early), kit list (deliverables for today), batch timings, Kavita's number, and today's micro-tasks ("photograph the first session" → Shyam's remote reminder to Sourav since Shyam isn't on-site).

2.  Through the day, on-site updates are one-tap or voice: "Reached 8:25" / "Batch 1 done, 34 of 38 participants attended" / "Projector in lab-2 flickers, managed with lab-1." Each becomes a progress_events row; attendance numbers land in the day's delivery record (a deliverables row type = daily_report, built incrementally).

3.  Anything tagged as an issue (projector) silently creates a P2 task for Mithun ("arrange backup projector for Days 2–7") — the specialist never has to remember evening paperwork.

4.  17:30 — the [Assistant Engine] drafts the Day-1 summary from the day's events: sessions run, attendance, highlights (photos Shyam picked from Sourav's uploads), issues + fixes. Two versions: internal (full, with the projector grumble) and client (warm, honest, attaches the two best photos). Akash approves the client one → sent to Harish + Kavita on the thread.

5.  Day tasks roll: today's runsheet tasks close, tomorrow's activate. projects.status = delivery; health recomputed nightly from attendance vs plan and open issues.

If things go differently:

A specialist falls sick at 06:30 → Sourav taps the SOS flow: P1 to Mithun with the substitution options precomputed (Baski free today? Divya solo with reduced batches?); the client gets a proactive message BEFORE 08:00, not an apology at 09:15.

The client cancels the day at 07:00 (water problem) → inbound urgent → day's tasks pushed, plan re-dated by one day (Workflow 18 machinery, fast path), everyone including the vendor notified.

### Workflow 24 — Materials and vendors: dependencies that live outside the company

The story. 550 participant kits must exist before Day 1. The vendor (PrintCraft) is not a user in our system — but our plan depends on him.

Step by step:

1.  The task "Order 550 workbook kits" (Mithun, phase = preparation) carries a structured external dependency: action_items gets an external_wait block — who we're waiting on (vendor name from an org-level vendors list), promised date (26 Nov), and chase contact.

2.  Mithun places the order and records the vendor's promise. The Sync Engine treats the promised date like an internal due date — but the chase target is Mithun ("vendor promised 26 Nov — confirm it's on track"), at T-3 and T-1 days.

3.  25 Nov: Mithun taps "vendor confirms 27 Nov now" → one-day slip. The engine walks the chain (kits → dispatch → Day 1 on 3 Dec): slack exists, nothing breaks; the slip is logged, downstream dates auto-adjust inside their slack, nobody is alarmed unnecessarily.

4.  27 Nov: kits arrive short — 500, not 550. Mithun records partial delivery → the gap (50 kits, exactly the Workflow-20 addition for cohorts 3–4) creates a P1 task with options the engine precomputes: partial-print locally / stagger juniors to Day 3 / vendor rush. Mithun picks vendor rush (29 Nov), records it; the Sync Engine now watches THAT promise.

5.  All of this appears in the weekly client report only as "materials on track" — external vendor drama stays internal unless a client-facing date is threatened (the visible_to_client flag doing its quiet work).

If things go differently:

The slip eats all slack → the Planner proposes the re-plan + drafts the client's date-change email (us asking the client this time); Akash approves both together, mirror image of Workflow 18.

Payment to the vendor is due (advance) → a task for Vikram with the invoice attached; vendor money is normal task machinery, not a special system.

### Workflow 25 — Getting paid

The story. The programme ended brilliantly. The final invoice of ₹1,00,000 (accepted special price ₹1,10,000 + amendment ₹45,000 − advance ₹55,000) went to Mr. Ramesh Gupta on 10 December, due 24 December. Clients are slow payers; chasing must be polite, persistent, and aimed at the right person.

Step by step:

1.  invoices row: balance amount (computed from proposals.total_amount + amendment − advance received), due 24 Dec, sent_to = Ramesh (accountant stakeholder — NOT the managing director). projects.status = payment_pending.

2.  The [Sync Engine] runs the payment ladder (gentler and slower than task nudges — org-configurable): T-3 days a friendly heads-up to Ramesh; due date +3 a polite reminder CC nobody; +10 a firmer note CC the managing director (org rule: managing director enters CC only at level 3); +20 → task for Akash to call, and the org admin is informed. Every message drafted by the Communication Engine, approved by Akash, on the accounts thread.

3.  Ramesh replies "cheque ready, collect Friday" → [Inbound Engine]: intent = payment_info → task for Rahul (he's nearby) "Collect cheque Friday" (P2) + the ladder pauses.

4.  Vikram records the payment (invoices.status = paid, progress_events payment_received). The Sync Engine: thanks-note drafted (small thing, big goodwill — one-tap from Akash), projects.status → closed eligibility check (all commitments kept? all deliverables accepted? → Workflow 26 finishes first), and leads.state suggestion → closed.

If things go differently:

Part payment arrives (₹40,000) → invoices.status = part_paid; the ladder resets against the balance with the numbers restated plainly in the next reminder.

The client disputes the amount ("amendment was never signed") → intent = rejection/dispute → needs_human immediately, P1 to Akash with the full paper trail assembled by the Assistant Engine (proposal, amendment, confirmations — all on threads). Paper trails win disputes, and this system never loses paper.

### Workflow 26 — Finishing well: feedback, certificates, closure

The story. Delivery done, money nearly in. Endings decide whether next year's deal exists.

Step by step:

1.  When the last delivery-phase task closes, the [Planner Engine] generates the closure wave from the program playbook (playbooks): collect feedback (Divya), issue 550 certificates (Meera — the [Document Engine] mail-merges them from the attendance records collected in Workflow 23), closure report (Shyam's photos + attendance + content plan coverage), testimonial ask (Rahul), final invoice (done, Workflow 25), internal retrospective note (Mithun).

2.  Feedback: a simple form link goes to Kavita for client staff/participants; results land as deliverables type = feedback_summary; the AI summarises highlights ("4.6/5, kids loved Day-5 app-building").

3.  The closure report — the client-facing crown piece — is drafted from real data: what was promised (client_commitments, all statuses shown honestly — 14 kept, 1 renegotiated) vs delivered, attendance, photos, feedback quotes. Akash polishes, approves; Rahul sends it with the certificates.

4.  The testimonial ask rides two days behind the closure report (sequenced by depends_on_ids + a send-delay — asking on the high of a great report doubles the yes rate; the Communication Engine sequences by design, not luck).

5.  All closure tasks done + invoice paid → project → closed. The [Knowledge Engine] does the archival pass: plan versions frozen, the whole project distilled into memory_chunks (what worked, what stalled, prices, people, the laptop incident) so NEXT year's Planner at any client starts smarter; client_intelligence gains "programme Dec 2026: 4.6/5, managing director receptive to annual program."

6.  One last AI move: the Assistant Engine drafts a cross-sell note to Akash — "VG closed happy; the annual STEM-lab program fits their profile; suggested touch: February, before budget season." That note is Workflow 30's opening scene.

If things go differently:

Feedback is bad (3.1/5) → the closure report draft leads with fixes, and the cross-sell note is replaced by a repair plan; the org admin sees the score in the org dashboard.

The client ghost-ends (never sends feedback, pays, goes silent) → closure proceeds on our side after the ladder exhausts; the project closes with "feedback: not received" — honest data beats pretty data.

## PART 5 — THE LONG GAME AND THE HARD ROUTES (Workflows 27–30)

### Workflow 27 — A 12-branch chain: one deal, many clients

The story. Dr. Anita Bose, group director of Sunrise Group (12 branches), wants the Android programme across all branches over two terms. One negotiation, twelve deliveries.

Step by step:

1.  After the group-level meeting, the [Planner Engine] recognises multi-site scope and proposes a parent project ("Sunrise Group — Android Programme Program", the commercial container: one proposal, one price negotiation at group rate, stakeholder = Dr. Bose) plus child projects per branch (projects.parent_project_id — one new field), each with its own lead record, stakeholders (branch managing directors), plan, team, and dates.

2.  Commercials live ONLY on the parent: one proposal (12 × per-branch price with a group discount → price rule → Ananya approves), one master agreement, group-level invoicing (or per-branch — the choice recorded on the parent’s projects.invoicing_mode).

3.  Delivery lives on the children: the Assignment Engine staffs branches like a tour schedule — the [Resource & Calendar Engine] sees across all children, so Sourav is never booked in two cities in one week. Branch plans are stamped from the first delivered branch's plan as a template, then localised.

4.  Sync rolls up: each child reports health; the parent's health is the worst of its children plus commercial state. Dr. Bose gets ONE weekly report (parent-level: "3 branches done, branch 4 next week, 4.5/5 average"); each branch managing director gets their own branch report. Right altitude for each reader, automatically.

5.  Learning compounds: branch 1's incidents (laptops!) auto-suggest playbook additions; by branch 5 the plan template carries them; delivery quality measurably rises across the sequence — and the data shows it.

If things go differently:

Branch 7's managing director refuses dates repeatedly → that child goes on_hold without touching the other eleven; the parent report flags it to Dr. Bose (group pressure works better than vendor pressure).

The group wants to pause after 6 branches → parent → on_hold cascades to unstarted children only; in-flight branches finish; the commercial reconciliation (6 of 12 delivered against a group price) lands as a needs_human card with the Assistant Engine's computation attached.

### Workflow 28 — "Not this year" — pausing and coming back

The story. Modern Public Client liked everything but the budget died in committee: "Try us in April, new financial year." A no that is really a "later" — most sales systems lose these; ours must not.

Step by step:

1.  Rahul records the outcome. projects.status → lost (reason = budget_timing, structured field + free note), leads.state → lost_for_now — but the difference from a hard loss is the revival record: revival_date = 1 April, revival_context written by the AI ("liked content plan, objection was FY budget only; coordinator was champion; quote group discount next time"), stored on the lead.

2.  Open tasks are cancelled (not deleted); the thread gets a graceful goodbye email (drafted, approved, sent): "we'll check back in April as suggested" — the promise to return is itself a client_commitments row, promised BY us, due 1 April.

3.  Silence until March. No reminders, no digests, no noise. The lead sleeps.

4.  25 March (T-7): the Sync Engine wakes it — Rahul gets a revival card: the whole story replayed by the Assistant Engine (proposal, content plan, the champion coordinator, last year's price vs current pricing_tables), plus a drafted re-opening email referencing the April promise. Rahul sends; the lead moves lost_for_now → open; if it bites, Workflow 1 machinery spins up a fresh project — with all last year's memory attached.

If things go differently:

The client comes back EARLY ("budget approved in Jan!") → the Inbound Engine matches the sleeping lead, wakes it immediately, and the revival card fires ahead of schedule.

April comes, the client passes again → the AI suggests one more cycle or archive; two consecutive passes flip the default to archive (leads.state stays lost_for_now, no next revival) unless a human insists.

### Workflow 29 — Two projects, one client, zero crossed wires

The story. While the VG programme (Rahul's, in delivery) is running, Mr. Singhania separately asks Priya about a permanent STEM lab (a different program, different budget line, different timeline). Same client, same managing director — two projects.

Step by step:

1.  Priya's meeting about the lab creates a second project on the same lead ("VG STEM Lab — 2027", program = STEM Lab, sales_owner = Priya). leads now has two child projects; stakeholders rows exist per-project (Harish is decision_maker on both; Kavita is on the programme only; the lab adds a trustee).

2.  Threads are per project. The lab conversation runs on its own email thread with its own subject; the programme thread stays clean. When Harish replies, the [Inbound Engine] matches to project by thread first, then by content ("regarding the lab quote..." → lab project) — and when it genuinely can't tell ("let's discuss both on Friday"), it attaches the message to BOTH timelines (inbound_messages.related_project_ids) and flags needs_human for the meeting booking.

3.  Plans, tasks, approvals, invoices: fully separate. Sourav can be a member of both, with the [Resource & Calendar Engine]'s cross-project view keeping him sane.

4.  Shared on purpose: client_intelligence and memory_chunks are lead-level — the lab proposal writer automatically knows the programme's laptop incident and the client's Hindi preference. Data isolation between orgs, data SHARING within a client: both by design.

5.  Reports: Harish gets the programme weekly (from Rahul's side) and lab proposal updates (Priya's side) as separate threads — but the Sync Engine coordinates outbound pacing per stakeholder (max messages/week across all projects to one person — an org courtesy rule) so the managing director is never spammed by two enthusiastic pipelines at once.

If things go differently:

The managing director conflates them in one email ("proceed with the lab, and add drone kits to the programme") → the Inbound Engine splits extracted_points by project and routes each to its own Planner run; two plan diffs, two approvals, one polite combined reply (drafted on the thread he wrote on, answering both, signed by the right owner).

The two projects compete for the same week of Sourav's time → cross-project load check catches it at assignment time; the two leads (Akash, Priya) get a shared card to horse-trade openly rather than discovering the clash on-site.

### Workflow 30 — Full circle: the relationship engine

The story. February. The Workflow-26 cross-sell note fires: VG closed happy in December; budget season is near. This last workflow shows the system as a relationship engine across years, not a task tool for weeks.

Step by step:

1.  Rahul's daily digest carries the revival/growth card: last year's project summary (from memory_chunks), the feedback score, the managing director's known preferences, the suggested pitch (annual STEM program), and this year's pricing. Ten seconds of reading replaces an hour of file-digging.

2.  Rahul: "draft the reach-out." The [Communication Engine] writes it grounded in the real past — references the programme outcomes by number (550 participants, 4.6/5), Kavita's client staff' feedback, and proposes a February meeting. Akash approves; sent on the (dormant, reopened) thread.

3.  Harish replies warmly; a meeting is booked; Workflow 1 spins up "VG Annual STEM Program — 2027" — but this time the Planner (briefed by the [Knowledge Engine]) starts from a rich prior: known stakeholders (including that Ramesh pays in cheques, slowly), known logistics (30-equipment room, gate opens 8:00), known risks (laptop spares!), and the playbook improvements the December incidents wrote. Plan v1 of the new project is measurably better than last year's plan v1 — the compounding the whole design exists for.

4.  And the platform effect: everything above happened inside YuviPep's org space. BrightFuture Labs, running on the same platform for its own clients, saw none of it — same machinery, separate worlds, exactly as the multi-organisation foundation promises.

If things go differently:

Harish has retired; a new managing director arrives → the Inbound Engine notices the reply signature mismatch, flags the stakeholder change, and the reach-out becomes an introduction: the AI drafts the "here's who we are and what we did for your client" version, with the closure report attached as proof. Relationships change; the record survives.

# 6. Why Any New Workflow Fits This Design

Thirty workflows cannot cover every situation a real sales organisation meets — and they don't have to. They exist to prove a shape. Every workflow in this document, and every one nobody has written yet, reduces to the same six-step loop:

1.  Sense. Something happens: a meeting ends, a reply arrives, a task closes, a date passes, a person uploads a file, a payment lands. It becomes an event (progress_events) or an inbound message (inbound_messages). Nothing important happens outside the stream — that is the design's one non-negotiable habit.

2.  Understand. The right engine interprets it: the Inbound Engine classifies a message; the Planner merges new facts into the plan; the Knowledge Engine supplies what the organisation already knows.

3.  Decide. Rules decide who must say yes (approval_rules); the Assignment Engine decides who does the work; feasibility is checked (Resource & Calendar) before anything is promised; and anything unclear goes to a named human instead of being guessed (needs_human, conflicts, the triage queue).

4.  Act. Tasks are created or changed, documents are produced by the AI or uploaded by a person, messages are drafted, approved, and sent.

5.  Watch. The Sync Engine chases everything that is open — tasks, commitments, replies, payments, approvals, vendor promises. Nothing rots silently.

6.  Learn. Closures, incidents, and human overrides flow back into playbooks and memory, so the next plan starts smarter than the last one.

The test for any new scenario is six questions, not new code: *What is the event? What does it mean for the plan? Who decides? Who does the work? What must be watched? What should we learn?* If a question has no answer, that is a real gap — and these extension points absorb almost all of them:

A new...

...is handled by

kind of work (a new program, a new delivery style)

a playbooks entry — the Planner generates the right task waves from it

kind of ask from a client

a new intent / change_type / extracted-point type in the Inbound Engine

"who must approve this"

a row in approval_rules — including joint and chained approvals

kind of person or skill

rows in users / user_skills — the Assignment Engine picks them up automatically

document

a template plus the Document Engine — or simply a manual upload

pacing, courtesy, or working-hours rule

an org setting the Sync and Communication Engines respect

outside dependency (vendor, partner)

vendors + external_wait on tasks — promised dates are watched like due dates

And three safety principles hold for every future workflow automatically, because they live in the engines, not in the workflows:

A human approves everything a client sees.

A human can always do any step manually — type, upload, assign, or send by hand — and the engines reconcile it instead of fighting it.

Every AI decision carries a written reason (ai_decisions) that anyone can read later.

# 7. Building the Product — the Order That Works

This section is for the team that builds it. The design rests on four pillars; each build phase is shippable and usable on its own.

The four pillars:

1.  The organisation foundation — organisations, users, roles, org settings, and hard per-organisation isolation (org_id on every row, enforced by the database). Built first because it cannot be retrofitted.

2.  The project layer — projects, versioned plans, action items, members, stakeholders, commitments. Without a project there is nothing to plan, staff, sync, or close.

3.  The event loop — progress_events, inbound_messages, threads, and the Sync + Inbound + Approval Engines. This is what turns a record-keeping app into a system that acts.

4.  People as more than logins — skills, capacity, leave, assignment history, ai_decisions. The AI cannot distribute work among actors it cannot describe.

The build phases:

Phase

What gets built

What becomes possible

1

Pillars 1 + 2, the meeting pipeline (record → transcript → plan v1 → tasks), the Assignment Engine, notifications

A meeting turns into a staffed, versioned plan with reasons (Workflows 1, 2, 9)

2

Pillar 3, the Communication + Document Engines, approval rules, threads, the reminder ladder, manual uploads

The loop closes: work completes, the client hears, replies come back, the plan refines (Workflows 3–7, 10–16, 14, 18, 19)

3

Resource & Calendar Engine, invoices + payments, deliverables lifecycle, incidents, digests, weekly reports, playbooks

The full delivery-and-money lifecycle (Workflows 8, 17, 20–26)

4

Knowledge Engine learning loops, parent/child projects, revival flows, dashboards, cross-year memory

The relationship engine (Workflows 27–30)

Two habits to keep from the first line of code: every business row carries org_id, and every state change writes a progress_events row — the pillars stand on those two habits.

*End of document — YuviPep AI Sales Platform, 30 Real-Life Workflows.*