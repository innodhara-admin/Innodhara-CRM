# YuviPep AI Sales Platform — Roles & Responsibilities Reference

## Who Can Do What, Section by Section

This is the third companion document of the specification. **"30 Real-Life Workflows"** tells the stories, **"Data Model & Tables Reference"** defines every table and field — and this document explains the **people**: every role in the system, what each role can and cannot do, who approves what, who gets alerted when things go wrong, and who is responsible for each section of the platform.

Everything here is drawn from the other two documents and stays in sync with them: role names come from `users.role`, approval rights come from `approval_rules`, and every responsibility is the same one the workflows act out. The same cast is used — Ananya the admin, Akash the sales lead, Rahul and Priya in sales, Mithun running operations, and the delivery team.

---

# 1. How to Read This Document

**In simple words:** think of the platform as a well-run office. This document is the page on the noticeboard that says who holds which keys. Section 2 lists the roles. Section 3 gives the golden rules that apply to everyone. Section 4 walks through each role in detail — what they do all day, what buttons they have, what buttons they don't. Section 5 flips the view: it goes through each part of the system and says who is responsible there. Sections 6–8 are quick-reference tables: permissions, approvals, and alerts. Section 9 covers the people who never log in, and Section 10 explains how new roles can be added later.

Three terms that must not be confused:

| Term | What it means | Example |
|---|---|---|
| **Role** (`users.role`) | The powers a person has in the app — which buttons exist for them. Fixed list: `super_admin`, `org_admin`, `sales_lead`, `sales_agent`, `operations_lead`, `operations_agent`. | Sourav is an `operations_agent`. |
| **Designation** (`users.designation`) | The human job title, shown to teammates and in signatures. Free text — it grants no powers. | Sourav's designation is "Trainer"; Vikram's is "Accounts Executive" — both are `operations_agent`. |
| **Skill** (`user_skills`) | What a person is good at. Skills decide which **tasks** the AI routes to someone — they never decide what a person may approve or see. | Vikram has `invoicing (expert)`, so invoice tasks come to him. |

So: the **role** opens doors, the **skills** bring work to your desk, and the **designation** is what's printed on your card.

---

# 2. The Roles at a Glance

Two levels exist. One special role sits at the **platform level**, above all organisations. Every other role lives **inside one organisation** and can never see beyond it.

| Role (`users.role`) | Level | Who in our story | One-line job |
|---|---|---|---|
| `super_admin` | Platform | The platform operator (us) | Creates new organisations and sets them up. Can never read any organisation's sales data. |
| `org_admin` | Organisation | Ananya Iyer | Sets up everything the organisation runs on: programs, prices, templates, staff, rules, and settings. Decides the biggest money questions. |
| `sales_lead` | Organisation | Akash Rathore | Owns the school relationships and the promises. Approves client messages, plans, and recommends discounts. Manages the sales agents. |
| `sales_agent` | Organisation | Rahul Verma, Priya Nair | Meets schools, records meetings, scans cards, sends proposals from their own email — the face the school knows. |
| `operations_lead` | Organisation | Mithun Sharma | Owns delivery: teams, schedules, logistics, vendors, and the fixing of problems. Co-owns every project once the deal is agreed. |
| `operations_agent` | Organisation | Meera, Sourav, Baski, Divya, Shyam, Vikram | Does the delivery work — content, training, media, accounts — each routed by their skills. |

And the people **around** the system who never log in: the school's decision makers, coordinators, and accountants (they live in `contacts` and `stakeholders`), and outside suppliers (they live in `vendors`). Section 9 covers them.

---

# 3. The Golden Rules of Access

These rules stand above every role and never bend:

1. **Email = identity.** Each person logs in with their official company email. The email decides their organisation; the role decides their powers. No shared logins, ever.
2. **One organisation, one world.** Every record carries an `org_id` and the database itself (Row-Level Security) refuses to show anyone another organisation's rows. No role — not even `org_admin` — can see across the fence. The `super_admin` manages the fences but cannot see inside them.
3. **Nothing reaches a school without a human yes.** Whatever the role, no proposal, message, or invoice goes out without a recorded approval (`outbound_messages.approved_by` is the proof).
4. **Prices are never set by hand or by AI.** They come from `pricing_tables` (maintained only by the `org_admin`) or from a recorded human approval of a special price. No role can type a price into a proposal.
5. **Anyone can do any of their steps manually.** Every role's AI assistance has a manual path — type instead of dictate, upload instead of generate, assign by hand instead of accepting a proposal. The engines reconcile manual work; they never block it.
6. **Everything is written down.** Sensitive actions land in `audit_log` (uneditable), AI decisions in `ai_decisions` (with reasons), and every change in `progress_events`. Whoever you are, your actions are traceable — and so are the AI's.

---

# 4. Role by Role

## 4.1 Super Admin — the platform operator

**In simple words:** the landlord of the building. They build new offices and hand over the keys — but they hold no key to any office themselves.

**What they handle:**
- Creates a new organisation: name, logo, colours, unique org id, and the registered email domain (e.g. @brightfuture.com) — one row in `organisations`.
- Invites the organisation's first Org Admin by email.
- Deactivates an organisation that leaves (data exported back to it, then securely deleted).
- Watches platform health: how many organisations are active, how the system performs — counts and dashboards only.

**What they can never do:** read any organisation's leads, projects, messages, or recordings; record meetings; approve anything inside an organisation; appear in any organisation's staff list.

**Example:** the Super Admin creates BrightFuture Labs in an afternoon, registers its domain, invites Meena as its Org Admin — and from that moment sees nothing of what BrightFuture does with the system.

## 4.2 Org Admin — Ananya

**In simple words:** the person who builds the machine their colleagues drive. Ananya rarely talks to schools — she decides what the organisation sells, at what price, with which templates, under which rules, and who works here.

**What they handle:**
- **The catalogue:** programs (`programs`), price lists (`pricing_tables` — the **only** role that can create or change prices), proposal templates, and message templates.
- **The recipe book:** playbooks (`playbooks`) — the standard task waves per program — including accepting the improvement suggestions the Knowledge Engine proposes after incidents.
- **The people:** registers staff (`users`), sets their roles, skills (`user_skills`), capacity (`max_open_tasks`), and records leave. Sets up demo teams (day-to-day team management then belongs to the Operations Lead).
- **The rules:** all organisation settings (`org_settings` — reminder gaps, working hours, quiet-hour exceptions, courtesy caps, retention periods) and all approval rules (`approval_rules` — who must say yes to what).
- **The biggest money decisions:** discounts above the threshold (e.g. above 10%) are decided by the Org Admin, with the Sales Lead recommending first. Group-deal pricing for school chains lands here too.
- **The org-level escalations:** a whole department overloaded, a lead's own tasks overdue, repeated complaints on one project, the AI budget (`llm_usage`) nearing its cap — all end on Ananya's desk.
- **The record:** reads the `audit_log` for reviews.

**What they cannot do:** create organisations (platform level), see any other organisation, or bypass the human-approval rule — even the admin's own client messages follow the approval rules.

**Example:** Ananya adds the "Bootcamp — Learning About Android" program, uploads two proposal templates, sets ₹300 per student in pricing v4, registers Divya as a junior trainer with `max_open_tasks = 5`, and approves the ₹1,10,000 special price that Akash recommends in Workflow 4.

## 4.3 Sales Lead — Akash

**In simple words:** the owner of the relationship and the promises. Almost everything that goes **to** a school passes his phone first, and almost everything that goes wrong **with** a school lands on it.

**What they handle:**
- **Approvals of client-facing work:** progress updates, weekly client reports, proposals above the threshold (e.g. ₹1 lakh), plan changes (jointly with the Operations Lead when delivery dates move), and the wording of every sensitive reply. His edits teach the AI his style.
- **Discounts:** recommends on price asks above the threshold (`stage = recommend`); the Org Admin decides.
- **Plans:** confirms new project plans and re-plans (the plan-diff cards from the Planner Engine); resolves conflicts between what two school-side people said (`conflicts.raised_to_user_id`) — himself, or by asking the client.
- **The sales team:** confirms AI task assignments for sales-phase tasks (lead-confirm mode), receives level-3 escalations when a sales agent's task rots, receives overload alerts for the sales department, can move any sales team member's task.
- **The relationship side of trouble:** complaints alert him together with the Operations Lead — Mithun owns the fix, Akash owns the apology and the wording.
- **Money chasing, last step:** when the payment ladder is exhausted, the "call them" task is his.

**What they cannot do:** change prices or templates (request only — `org_admin` decides), register staff, approve a discount above the threshold alone, or see another organisation.

**Example:** in one day Akash approves plan v5 for the SVS date shift (one card: feasibility + diff + drafted reply), rejects a proposal draft with the note "change payment terms to 50% advance" (the note becomes the instruction), and recommends ₹1,10,000 on the principal's discount ask.

## 4.4 Sales Agent — Rahul and Priya

**In simple words:** the face the school knows. They meet, listen, and stay human — the machine does the paperwork behind them.

**What they handle:**
- **Meetings:** set up and record school meetings (consent first — `consent_records`), or type notes when recording isn't possible. Review the AI-extracted action items when review is switched on.
- **Contacts:** scan business cards; fix any scan the AI wasn't sure about (nothing is sent to an unverified address).
- **Their own client messages:** approve and send template-based intro messages and WhatsApp replies **on their own threads** themselves (`approver_role = thread_owner` — the template was already approved by the admin). Bespoke commercial messages go through the Sales Lead first — but the **final Approve-and-Send is always the sender's**, because the email leaves from their personal address.
- **Proposals:** trigger proposal builds, edit them by voice or typing (words only — never prices), and send after internal approval.
- **Their tasks:** work them, close them by voice/typing/upload, move their **own** tasks to someone else, add school intelligence notes at any time.
- **Asking:** query anything in their scope through the Assistant Engine — "show my open tasks", "which follow-ups are due today", "what is blocking the SVS bootcamp?"

**What they cannot do:** change prices, pricing tables, or templates (they may **request** a special price, which starts the approval chain); move other people's tasks; register staff; change org settings; approve their own bespoke commercial messages.

**Example:** Rahul records the 40-minute SVS meeting, confirms the 4 extracted action items, approves the intro message to the principal with one tap, says "make the workshops 16", and — after Akash approves the content — taps the final Approve and Send. The proposal leaves from rahul@yuvipep.com. Total typing: zero.

## 4.5 Operations Lead — Mithun

**In simple words:** the person who makes the promise physically happen. The moment a deal is agreed, he co-owns the project (`projects.ops_owner_id`) — from that day, dates, people, kits, and problems are his.

**What they handle:**
- **Delivery staffing:** confirms AI task assignments for preparation, delivery, payment, and closure phases (lead-confirm mode); receives level-3 escalations and overload alerts for operations staff; approves reassignments and handovers (leave, declines, splits).
- **Resources and schedules:** demo teams day-to-day (`demo_teams`), demo scheduling, batch schedules, travel, and the master busy-calendar (`resource_bookings`) — the reason nobody is booked in two cities in one week.
- **Vendors:** maintains the supplier list (`vendors`), places orders, records vendor promises (`external_wait`) and slips — the system chases him to chase them.
- **Problems:** owns every incident (`incidents.owner_user_id`) — a complaint alerts him together with the Sales Lead; Mithun owns the fix tasks; the closing lesson feeds the playbooks.
- **Delivery-date promises:** joint approver (with the Sales Lead) whenever a plan change moves delivery dates or an urgent client promise needs both a seller's yes and a deliverer's yes (Workflow 21).
- **Due-date ripples:** when someone's new task date would break a client commitment, the change comes to the phase lead as an approval.
- **Skills:** can adjust `user_skills` levels when reality proves them wrong (shared with the Org Admin).

**What they cannot do:** prices, templates, client commercial approvals (the relationship side is the Sales Lead's), staff registration, org settings.

**Example:** on one Wednesday evening Mithun jointly approves the urgent next-morning demo (Workflow 21), picks "split the task" when Baski declines the robotics demo, and records PrintCraft's one-day slip — which the system checks against the delivery chain and finds harmless.

## 4.6 Operations Agent — Meera, Sourav, Baski, Divya, Shyam, Vikram

**In simple words:** the hands. One role, many trades — the `designation` says what kind of hands, and the `user_skills` bring each person the right work: curriculum tasks find Meera, training days find Sourav and Baski, photos find Shyam, invoices find Vikram.

**What they handle:**
- **Their tasks:** work them any way they like — in the app, by voice, or by doing the work outside and uploading the file (`completion_method = manual_upload` is a first-class way to finish anything). Update progress (`progress_percent`), attach results, write completion notes.
- **Honesty switches:** decline a task with a reason (busy / wrong skill / on-site elsewhere), or flag "I'm blocked" with why — both stop the nudge ladder and start the right machinery instead.
- **On delivery days:** follow the morning runsheet, send one-tap updates ("reached 8:25", "batch 1 done, 34 of 38 attended"), flag issues (a flickering projector silently becomes a task for Mithun), and feed the day's report.
- **Their specialities:** Meera and Divya build and revise syllabi (AI-assisted or manual upload — both equal); Sourav and Baski deliver and report; Shyam picks the photos that make reports look good; **Vikram raises invoices** (amounts always computed, never typed) **and records payments** (`payments.recorded_by`) — the `payment_received` event does the rest.

**What they cannot do:** assign or move other people's tasks; send anything to a school on their own authority (their completed work **triggers** client updates, which the Sales Lead approves); prices, templates, staff, settings.

**Example:** Meera gets the syllabus task with the AI's reason attached ("curriculum_design expert, 3/8 load"), does the revision in Word because she prefers Word, uploads the PDF onto the task, and marks it done. The coverage check ticks the principal's two asks against her file; the client email that follows is drafted by the machine and approved by Akash — Meera never has to write to the school herself.

---

# 5. Section by Section — Who Does What Where

This flips the view: the data model has seven sections of tables; here is who owns and who contributes to each.

## 5.1 Platform & People (`organisations`, `org_settings`, `users`, `user_skills`, `notifications`, `audit_log`, `llm_usage`, `jobs`)

| What happens here | Who |
|---|---|
| Creating an organisation, registering its domain | **Super Admin** only |
| Branding (logo, colours) | **Org Admin** (own organisation) |
| Every behaviour dial (`org_settings`) and approval rule | **Org Admin** |
| Registering staff, roles, capacity, leave | **Org Admin** |
| Adjusting skill levels (`user_skills`) | **Org Admin** or the person's **lead** |
| Reading the audit log, watching the AI budget | **Org Admin** |
| Notifications | Everyone reads their own — nobody reads anyone else's |

## 5.2 Schools & Relationships (`leads`, `contacts`, `stakeholders`, `consent_records`, `client_intelligence`, `memory_chunks`)

| What happens here | Who |
|---|---|
| Creating leads, scanning cards, capturing consent | **Sales Agents** (and their leads) |
| Owning the relationship (`leads.owner_id`) | The named **Sales Agent**; the **Sales Lead** oversees all |
| Confirming lead state changes (open → active → …) | The **owner** confirms; the system only suggests |
| Stakeholder roles per project (who decides, who pays) | Proposed by the **Planner Engine** from meetings; edited by the **sales owner** |
| Adding school intelligence notes | **Anyone** on the account — voice or typed |
| Long-term memory (`memory_chunks`) | The **Knowledge Engine** only — no human writes it directly |

## 5.3 Projects & Plans (`projects`, `project_members`, `action_plans`, `action_items`, `client_commitments`, `conflicts`, `playbooks`)

| What happens here | Who |
|---|---|
| Proposing a project and its plan versions | The **Planner Engine** |
| Approving plans and re-plans | **Sales Lead** — jointly with the **Operations Lead** when delivery dates move |
| Owning the project | **Sales Lead** (`sales_owner_id`) throughout; **Operations Lead** (`ops_owner_id`) from "agreed" onward |
| Adding/removing team members | The **phase lead** (Mithun adds Divya to SVS) |
| Working, closing, declining tasks | The **assignee** — any role can be one |
| Resolving conflicts between school voices | **Sales Lead** (or the client, asked diplomatically) |
| Maintaining playbooks | **Org Admin**, with Knowledge Engine suggestions |

## 5.4 Work Management & Sync (`assignments`, `reminders`, `progress_events`, `incidents`, `ai_decisions`, `digests`)

| What happens here | Who |
|---|---|
| Proposing who does each task | The **Assignment Engine**, with a written reason |
| Confirming assignment batches (lead-confirm mode) | The **phase lead**: sales tasks → Sales Lead; preparation/delivery/payment/closure → Operations Lead |
| Being nudged (levels 1–2), being escalated to (level 3) | Levels 1–2: the **assignee**; level 3: their **lead**; a lead's own overdue work: the **Org Admin** |
| Owning incidents | **Operations Lead** (fix) + **Sales Lead** (relationship), instantly, together |
| Reading "why did the AI do that?" | **Anyone** — `ai_decisions` is open to the whole organisation |
| Digests | Everyone gets their own daily one; the client weekly needs the **Sales Lead's** yes |

## 5.5 Products, Documents & Money (`programs`, `pricing_tables`, templates, `proposals`, `deliverables`, `invoices`, `payments`, `vendors`)

| What happens here | Who |
|---|---|
| Programs, prices, templates | **Org Admin** only |
| Building and editing proposals (words, never numbers) | **Sales Agents** with the Document Engine |
| Approving proposals above the threshold | **Sales Lead**; special prices → **Org Admin** decides |
| Producing deliverables (syllabi, schedules, reports) | The **assigned agent** — AI-generated or manually uploaded, both equal |
| Raising invoices, recording payments | The **accounts person** (Vikram) — amounts always computed |
| Vendors and their promises | **Operations Lead** |

## 5.6 Meetings & Scheduling (`meetings`, `transcripts`, `demo_teams`, `demos`, `resource_bookings`, `followups`)

| What happens here | Who |
|---|---|
| Booking and recording school meetings | **Sales Agents** (ops joins kickoffs and site visits; the sales owner stays responsible for the meeting record) |
| Fixing a low-confidence transcript | The **agent who held the meeting** |
| Demo teams: set up / day-to-day | Set up by the **Org Admin**; run by the **Operations Lead** |
| Booking demos, delivery days, travel | **Operations Lead**; the bookings write themselves into everyone's busy-calendar |
| The demo calendar-invite email to the school | Drafted by the system on booking / reschedule / cancellation; sends only after a one-tap approval by someone with messaging rights (typically the booker or Sales Lead) |
| Simple follow-ups | The **owner** of the lead |

## 5.7 Communication & Approvals (`threads`, `outbound_messages`, `inbound_messages`, `approval_rules`, `approvals`)

| What happens here | Who |
|---|---|
| Drafting every outward message | The **Communication Engine** — always a draft, never a send |
| Approving client messages | Per the rules: bespoke/commercial → **Sales Lead**; WhatsApp replies on your own thread → **you** (`thread_owner`); the final tap → the **sender** |
| Reading and routing inbound messages | The **Inbound Engine**; anything unclear → a **named human** (`needs_human`, triage) |
| Writing the approval rules themselves | **Org Admin** |
| Deciding approvals | Whoever the rule names — with reminders, escalation, and a full record |

---

# 6. The Permission Matrix

The quick-reference card. "Own" means only for records they own; "Phase" means only for their phase's tasks.

| Action | Sales Agent | Sales Lead | Ops Agent | Ops Lead | Org Admin | Super Admin |
|---|---|---|---|---|---|---|
| Record a meeting (with consent) | Yes | Yes | With the visit team | With the visit team | Yes | No |
| Create a lead / scan a card | Yes | Yes | No | No | Yes | No |
| Send a proposal (own deal, after approval) | Yes | Yes | No | No | Yes | No |
| Approve a bespoke client message | No | Yes | No | No | Yes (per rules) | No |
| Approve own-thread WhatsApp reply / template intro | Yes (own) | Yes (own) | No | Yes (own) | Yes (own) | No |
| Move a task to another person | Own only | Whole sales team | Own only | Whole ops team | Yes | No |
| Confirm AI assignment batches | No | Sales phase | No | Prep/delivery/payment/closure phases | Yes | No |
| Decline a task with a reason | Yes | Yes | Yes | Yes | Yes | No |
| Edit a pricing table | No | No | No | No | Yes | No |
| Approve a discount above the threshold | No | Recommends | No | No | Decides | No |
| Add a program / template / playbook | No | No | No | No | Yes | No |
| Register staff / set roles and capacity | No | No | No | No | Yes | No |
| Adjust a person's skill levels | No | Yes (own team) | No | Yes (own team) | Yes | No |
| Record leave | No | No | No | No | Yes | No |
| Manage demo teams day-to-day | No | No | No | Yes | Yes | No |
| Maintain vendors, record vendor promises | No | No | No | Yes | Yes | No |
| Raise an invoice (computed) / record a payment | No | No | Accounts person | Yes | Yes | No |
| Resolve a school-side conflict | No | Yes | No | No | Yes | No |
| Change org settings / approval rules | No | No | No | No | Yes | No |
| Create a new organisation | No | No | No | No | No | Yes |
| See another organisation's data | No | No | No | No | No | No |

---

# 7. Who Says Yes — Approvals by Role

The rules live in `approval_rules` (data, not code — the Org Admin can change them without a rebuild). The standard set, matching the Data Model reference:

| What needs a yes | Who says it | How fast |
|---|---|---|
| Progress updates and reports to the school | **Sales Lead** | 24h, then reminder → escalation |
| Proposal above ₹1,00,000 | **Sales Lead** | 48h |
| Discount above 10% | **Sales Lead recommends** (`stage = recommend`), **Org Admin decides** (`stage = decide`) — two chained rows | 48h |
| Plan change shifting dates by more than 2 days | **Sales Lead** — **jointly with the Operations Lead** when delivery dates move (both must say yes; either no rejects) | 24h |
| Urgent client promise (e.g. "demo tomorrow") | **Sales Lead + Operations Lead jointly** — P1 approvals may break quiet hours | Can be as tight as 30 minutes (`expires_hours = 0.5`) |
| WhatsApp reply on your own thread / template-based intro | **You** (`thread_owner`) — the template was already approved by the admin | Immediate |
| The final Approve-and-Send of any message | **The sender** — it leaves from their personal address | One tap |
| Plan changes below every rule's threshold | Nobody — activates automatically as `approved_by = "system"`, diff still written | Instant |

Unanswered approvals never die quietly: reminder at the deadline, then escalation to the named `escalated_to_user_id`, all recorded.

---

# 8. Who Gets Alerted — Escalations by Role

| When this happens… | …this person hears about it |
|---|---|
| A task is overdue (levels 1–2) | The **assignee** — gentle, then firm; never on leave days, never at night |
| Still overdue (level 3) | The assignee's **lead**, with one-tap options (reassign / call / extend) |
| A **lead's own** task rots at level 3 | The **Org Admin** |
| Someone exceeds their task capacity | Their **department's lead** (sales → Akash, operations → Mithun), with a rebalance proposal attached |
| A whole department is overloaded | The **Org Admin**, with the honest capacity message |
| A complaint arrives from a school | **Operations Lead + Sales Lead instantly, together** — it skips every queue |
| A complaint repeats (2+ on one project) | The **Org Admin**, plus a mandatory review task |
| An invoice passes +20 days unpaid | The **Sales Lead** gets the call task; the **Org Admin** is informed |
| The AI budget nears its monthly cap | The **Org Admin** |
| A message can be matched to nobody | A **human triage queue** — nothing is ever dropped |

---

# 9. People Who Never Log In

**School-side people** (`contacts`, given a per-project role in `stakeholders`): they receive things — proposals, progress reports, invoices — according to their stakeholder role, and their word carries the weight their `influence` records:

| Influence | What it means | Example |
|---|---|---|
| `decision_maker` | Their word is final; conflicts resolve in their favour or by asking them | Mr. Singhania, principal |
| `influencer` | Shapes the decision; heard, but doesn't decide | Mrs. Menon, coordinator |
| `gatekeeper` | Controls access to something — usually the money | Mr. Gupta, accountant: invoices go to **him**, not the principal |

Their preferences are respected by every engine: preferred channel, preferred language, `receives_progress_updates`, and `do_not_contact` (an absolute stop). A courtesy cap (`max_client_messages_per_week`) protects them from being spammed by two enthusiastic projects at once.

**Vendors** (`vendors`): outside suppliers our plans depend on. They never see the app; their promised dates are recorded on tasks (`external_wait`) and watched like deadlines — but the chase always goes to **our own coordinator**, never directly to the vendor.

---

# 10. Growing Beyond These Roles

Six roles are enough for the current size, and they are deliberately few. When an organisation outgrows them, the design already leaves room — because **access is checked centrally on every request**, finer-grained rules can be added without touching the core:

- **Custom roles** — e.g. a read-only manager, a regional lead.
- **Per-team data scoping** — an agent who sees only their own region's leads.
- **New approval routes** — any new "who must say yes" is just a row in `approval_rules`, including joint and chained approvals.
- **New specialities** — a new kind of worker needs no new role at all: a row in `users`, their `user_skills`, and the Assignment Engine finds them work from day one (that is exactly how Divya joined mid-project).

The rule of thumb: **roles change rarely, rules change freely.** The six roles are the skeleton; `approval_rules`, `org_settings`, and `user_skills` are the muscles the Org Admin can retrain any day without a code change.

---

*End of document — YuviPep AI Sales Platform, Roles & Responsibilities Reference.*
