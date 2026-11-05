"""Dry-run of the 30 specification workflows (plus unscripted extras) against
the real backend — real API, real engines, deterministic NLU, dry-run sends.

    python scripts/dryrun_workflows.py

Each workflow drives the same endpoints the mobile app would, then inspects
the database for the evidence the spec demands (tables written, events fired,
approvals recorded). Exit code 0 = every workflow passed.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

from dryrun_lib import (  # noqa: E402  (sets env before app imports)
    EMAILS,
    Runner,
    approvals_for,
    approve_all,
    confirm_all_assignments,
    contact_by_email,
    decide,
    lead_by_name,
    notifications_for,
    send_inbound,
    tasks_of,
)
from sqlalchemy import select  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# PART 1 — WINNING THE SCHOOL (Workflows 1–8)
# ─────────────────────────────────────────────────────────────────────────────


async def w01_first_meeting_to_first_plan(r: Runner) -> None:
    r.begin("W1 — First meeting to first plan: the whole machine starts")
    from app.models.user import User

    svs = await lead_by_name(r, "Swami Vivekananda School")
    r.ctx["svs_lead_id"] = svs.id
    rahul = await r.fetch_one(select(User).where(User.email == EMAILS["rahul"]))

    # Akash books Rahul's Monday visit.
    monday = datetime.utcnow() + timedelta(days=3)
    meeting = await r.api(
        "POST", "/meetings/schedule", user=EMAILS["akash"],
        json={"lead_id": svs.id, "title": "First visit — SVS",
              "started_at": monday.isoformat(), "meeting_type": "first_visit",
              "agent_id": rahul.id},
    )
    r.check("meeting booked in advance (status=scheduled)",
            meeting["status"] == "scheduled")
    r.check("Rahul was notified of the booked visit",
            (await notifications_for(r, EMAILS["rahul"], "Meeting booked")) != [])

    # Rahul visits; recording refused → typed notes are a first-class path.
    notes = (
        "Meeting with Mr. Harish Singhania, principal of Swami Vivekananda School, "
        "about a 7-day Android bootcamp for classes 5 to 9 with around 400 students. "
        "The school wants it in December and the budget is around one lakh. "
        "The school will give the computer lab. YuviPep must share the syllabus "
        "within a week and run a demo session for teachers first. "
        "The lab has only 30 computers so plan batches."
    )
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": svs.id, "text": notes, "meeting_type": "first_visit",
              "meeting_id": meeting["id"]},
    )
    r.check("planner proposed a project from the concrete first meeting",
            result["planner"]["action"] == "project_proposed",
            str(result["planner"]))
    project_id = result["planner"]["project_id"]
    r.ctx["svs_project_id"] = project_id

    from app.models.project import ActionPlan, ClientCommitment, Project, Stakeholder

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("value estimate priced from pricing_tables (400×300+6000=126000)",
            project.value_estimate == 126000, str(project.value_estimate))
    r.check("project status = planning", project.status == "planning")

    plan = await r.fetch_one(
        select(ActionPlan).where(ActionPlan.project_id == project_id)
    )
    r.check("plan v1 exists and waits for a human yes",
            plan is not None and plan.version == 1
            and plan.status == "pending_review", plan.status if plan else "none")

    # Brand-new project → Akash approves the plan (never silently activated).
    approvals = await approvals_for(r, EMAILS["akash"], "plan v1")
    r.check("plan v1 approval card reached the sales lead", len(approvals) == 1)
    await decide(r, EMAILS["akash"], approvals[0]["id"], approve=True)

    tasks = await tasks_of(r, project_id)
    open_tasks = [t for t in tasks if t.status == "open"]
    r.check("plan v1 activated with a staffed task wave", len(open_tasks) >= 5,
            f"{len(open_tasks)} open tasks")
    r.check("every task carries a written assignment reason",
            all(t.assignment_reason for t in open_tasks))

    meera = await r.fetch_one(select(User).where(User.email == EMAILS["meera"]))
    syllabus = next((t for t in open_tasks if "syllabus" in t.title.lower()), None)
    r.check("syllabus task → Meera (curriculum_design expert)",
            syllabus is not None and syllabus.assignee_id == meera.id,
            syllabus.assignment_reason if syllabus else "no task")
    r.ctx["svs_syllabus_task_id"] = syllabus.id if syllabus else None
    r.check("syllabus task is visible_to_client",
            syllabus is not None and syllabus.visible_to_client)

    commitments = await r.fetch_all(
        select(ClientCommitment).where(ClientCommitment.project_id == project_id)
    )
    r.check("client commitments extracted (syllabus within a week, teacher demo)",
            len(commitments) >= 2,
            "; ".join(c.text for c in commitments))
    stakeholders = await r.fetch_all(
        select(Stakeholder).where(Stakeholder.project_id == project_id)
    )
    r.check("stakeholders created from the school's contacts",
            len(stakeholders) >= 3)

    # Lead-confirm mode: the lead's one-screen batch confirmation.
    confirmed = await confirm_all_assignments(r, EMAILS["mithun"])
    r.check("lead confirmed the assignment batch (assignments, not approvals)",
            confirmed >= 1, str(confirmed))

    from app.models.work import AIDecision, ProgressEvent

    decisions = await r.fetch_all(
        select(AIDecision).where(AIDecision.project_id == project_id)
    )
    r.check("every AI decision recorded with reason (ai_decisions)",
            len(decisions) >= 5, str(len(decisions)))
    events_rows = await r.fetch_all(
        select(ProgressEvent).where(ProgressEvent.project_id == project_id)
    )
    r.check("event stream has project_created + plan_activated",
            {"project_created", "plan_activated"}
            <= {e.event_type for e in events_rows})


async def w01b_vague_meeting_no_project(r: Runner) -> None:
    r.begin("W1-alt — Vague discussion: no project is born, follow-ups only")
    lead = await lead_by_name(r, "Delhi Public School")
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": lead.id,
              "text": "Just a chat with Mrs. Sharma, nothing specific discussed. "
                      "No concrete plans yet."},
    )
    r.check("planner refused to create a project",
            result["planner"]["action"] == "followups_only",
            str(result["planner"]))
    from app.models.followup import FollowUp

    followups = await r.fetch_all(
        select(FollowUp).where(FollowUp.lead_id == lead.id)
    )
    r.check("a follow-up was created on the lead instead", len(followups) >= 1)


async def w02_expo_card_to_lead(r: Runner) -> None:
    r.begin("W2 — A business card at an expo becomes a lead")
    lead = await lead_by_name(r, "Little Flowers School")
    contact = await contact_by_email(r, "director@littleflowers.edu.in")

    # OCR was unsure → the intro is HELD until a human verifies the address.
    await r.exec_sql(
        "UPDATE contacts SET needs_review = 1 WHERE id = :cid", cid=contact.id
    )
    held = await r.api(
        "POST", "/messages/draft", user=EMAILS["priya"],
        json={"contact_id": contact.id, "kind": "intro",
              "purpose": "warm intro after expo",
              "subject": "Great meeting you at EdTech Expo",
              "facts": {"context": "robotics for classes 6-8 discussed at the expo"}},
    )
    r.check("intro held while the contact needs review (nothing to unverified addresses)",
            held.get("held") is True, str(held))

    # Priya fixes the scan, then the intro drafts and she one-taps it herself.
    await r.exec_sql(
        "UPDATE contacts SET needs_review = 0 WHERE id = :cid", cid=contact.id
    )
    draft = await r.api(
        "POST", "/messages/draft", user=EMAILS["priya"],
        json={"contact_id": contact.id, "kind": "intro",
              "purpose": "warm intro after expo",
              "subject": "Great meeting you at EdTech Expo",
              "facts": {"context": "robotics for classes 6-8 discussed at the expo"}},
    )
    r.check("intro drafted once verified", draft.get("message_id") is not None)
    # kind=intro rule → thread_owner (Priya) approves her own template intro.
    my_approvals = await approvals_for(r, EMAILS["priya"], "intro")
    r.check("intro approval went to the thread owner (Priya), not the sales lead",
            len(my_approvals) >= 1)
    await decide(r, EMAILS["priya"], my_approvals[0]["id"])
    sent = await r.flush_sends()
    r.check("intro sent (dry-run outbox)", sent >= 1, f"{sent} sends flushed")

    from app.models.comms import Thread

    thread = await r.fetch_one(select(Thread).where(Thread.contact_id == contact.id))
    r.check("thread created on the lead (project_id empty until a project is born)",
            thread is not None and thread.project_id is None)

    # Spoken context saved as school intelligence.
    await r.api(
        "POST", f"/leads/{lead.id}/intelligence", user=EMAILS["priya"],
        json={"note": "Met at EdTech Expo, interested in robotics for classes 6-8",
              "category": "from_meeting", "source": "voice"},
    )
    # The director replies before any project exists → matched by contact+lead.
    reply = await send_inbound(
        r, from_address="director@littleflowers.edu.in",
        subject="Re: Great meeting you",
        body="Can you send me a brochure of the robotics program?",
    )
    r.check("pre-project reply matched by contact and lead (Workflow 19 pickup)",
            reply["matched_project_id"] is None and reply["status"] in
            ("processed", "needs_human"), str(reply["status"]))


async def w03_proposal_built_checked_sent(r: Runner) -> None:
    r.begin("W3 — The proposal: built by AI, checked by people, sent by the right person")
    svs = await lead_by_name(r, "Swami Vivekananda School")
    project_id = r.ctx["svs_project_id"]

    from app.models.program import Program

    program = await r.fetch_one(select(Program).where(Program.code == "ANDROID_BC"))
    proposal = await r.api(
        "POST", "/proposals", user=EMAILS["priya"],
        json={"lead_id": svs.id, "program_id": program.id,
              "project_id": project_id,
              "context_summary": "7-day bootcamp, classes 5-9, ~400 students",
              "quantities": {"per_student": 400, "materials": 1}},
    )
    r.ctx["svs_proposal_id"] = proposal["id"]
    r.check("proposal priced strictly from pricing v4 (400×300+6000 = 126000)",
            proposal["total_amount"] == 126000, str(proposal["total_amount"]))
    r.check("template + pricing versions locked",
            proposal["template_version"] == 2 and proposal["pricing_version"] == 4)

    # Ready → the >₹1L rule fires → Akash. He rejects with a note first.
    review = await r.api(
        "POST", f"/proposals/{proposal['id']}/submit-review", user=EMAILS["priya"],
    )
    r.check("proposal above ₹1,00,000 routed to the sales lead",
            review["approval_id"] is not None)
    await decide(r, EMAILS["akash"], review["approval_id"], approve=False,
                 note="Good. Change payment terms to 50% advance.")
    from app.models.proposal import Proposal, ProposalRevision

    p = await r.fetch_one(select(Proposal).where(Proposal.id == proposal["id"]))
    r.check("rejection looped the proposal back to draft with the note as instruction",
            p.status == "draft")
    revisions = await r.fetch_all(
        select(ProposalRevision).where(ProposalRevision.proposal_id == p.id)
    )
    r.check("the rejection note is a recorded revision",
            any("50% advance" in (rev.instruction or "") for rev in revisions))

    # The human applies the change (manual path) and resubmits; Akash approves.
    await r.exec_sql(
        "UPDATE proposals SET content_md = content_md || :terms WHERE id = :pid",
        terms="\n\n**Payment terms:** 50% advance on agreement, balance on completion.",
        pid=p.id,
    )
    review2 = await r.api(
        "POST", f"/proposals/{p.id}/submit-review", user=EMAILS["priya"],
    )
    await decide(r, EMAILS["akash"], review2["approval_id"], approve=True)
    p = await r.fetch_one(select(Proposal).where(Proposal.id == p.id))
    r.check("proposal approved internally", p.status == "approved_internally")

    # The send: from Rahul — the face the principal knows.
    await r.api(
        "POST", f"/proposals/{p.id}/approve-send", user=EMAILS["rahul"],
        json={"to_address": "principal@svs.edu.in", "cc": ["akash@yuvipep.com"]},
    )
    await r.flush_sends()
    p = await r.fetch_one(select(Proposal).where(Proposal.id == p.id))
    r.check("proposal sent from the salesperson's own address", p.status == "sent")
    from app.models.project import Project

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("project moved planning → proposal_stage",
            project.status == "proposal_stage", project.status)


async def w04_principal_asks_for_changes(r: Runner) -> None:
    r.begin("W4 — The principal asks for changes: price (A) and content (B)")
    project_id = r.ctx["svs_project_id"]

    # Story A — money: the discount ask starts the recommend→decide chain.
    resp = await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Re: Android Bootcamp Proposal",
        body="The proposal looks good, but 1.26 lakh is above our budget. "
             "Can you do it in one lakh?",
    )
    r.check("inbound classified as a change request",
            resp["intent"] == "change_request", resp["intent"])
    r.check("discount extracted (126000 to 100000)",
            any(p.get("type") == "discount_request" for p in resp["extracted_points"]),
            str(resp["extracted_points"]))

    recommend = await approvals_for(r, EMAILS["akash"], "discount")
    recommend = [a for a in recommend if a["stage"] == "recommend" and a["status"] == "pending"]
    r.check("discount >10% → sales lead gets the RECOMMEND stage", len(recommend) == 1)
    step = await decide(
        r, EMAILS["akash"], recommend[0]["id"], approve=True,
        note="Offer 1,10,000 as a special price — December slot and a "
             "testimonial justify the concession.",
    )
    r.check("recommendation chained to the org admin's DECIDE stage",
            step["chained_next"] is True and step["stage"] == "decide")
    decide_cards = await approvals_for(r, EMAILS["ananya"], "discount")
    decide_cards = [a for a in decide_cards if a["status"] == "pending"]
    r.check("org admin sees the recommendation on the decide card",
            bool(decide_cards) and "1,10,000" in (decide_cards[0]["recommendation"] or ""))
    final = await decide(r, EMAILS["ananya"], decide_cards[0]["id"], approve=True)
    r.check("special price approved by the org admin", final["status"] == "approved")
    r.ctx["special_price_approval_id"] = decide_cards[0]["id"]

    # The approved special price is applied as a recorded human override —
    # a discount line, never an invented number.
    proposal_id = r.ctx["svs_proposal_id"]
    from app.models.proposal import Proposal

    p = await r.fetch_one(select(Proposal).where(Proposal.id == proposal_id))
    import json as _json

    items = list(p.line_items) + [{
        "code": "special_discount",
        "label": "Special price concession (approved by org admin)",
        "unit": "flat", "unit_price": -16000, "quantity": 1,
        "line_total": -16000,
    }]
    await r.exec_sql(
        "UPDATE proposals SET line_items = :items, total_amount = 110000, "
        "special_price_approval_id = :appr WHERE id = :pid",
        items=_json.dumps(items), appr=r.ctx["special_price_approval_id"], pid=p.id,
    )

    # Story B — content, not money: two asks in one email.
    resp_b = await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Re: Android Bootcamp Proposal",
        body="The proposal looks fine on price, but the syllabus inside is too "
             "advanced for classes 5-6. Please simplify days 1-2 for the juniors, "
             "and add one session on internet safety.",
    )
    r.check("content change classified (no money chain)",
            resp_b["intent"] == "change_request"
            and resp_b["change_type"] == "content",
            f"{resp_b['intent']}/{resp_b['change_type']}")
    from app.models.action_item import ActionItem

    revision_task = await r.fetch_one(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.title.like("Revise content%"),
        )
    )
    r.check("revision task created P1, visible to client, skill-routed",
            revision_task is not None and revision_task.priority == "P1"
            and revision_task.visible_to_client
            and revision_task.required_skill == "curriculum_design")
    ack = await approvals_for(r, EMAILS["akash"], "acknowledge")
    r.check("acknowledgement drafted so the school is never left hanging",
            len(ack) >= 1)
    await approve_all(r, EMAILS["akash"], "acknowledge")
    await r.flush_sends()

    # Meera fulfils it the MANUAL way: edits in Word, uploads the PDF.
    done = await r.api(
        "POST", f"/tasks/{revision_task.id}/complete", user=EMAILS["meera"],
        json={"result_note": "Simplified days 1-2; added internet safety session on day 4",
              "completion_method": "manual_upload",
              "deliverable_type": "syllabus",
              "deliverable_title": "SVS syllabus v2 (simplified juniors + internet safety)",
              "deliverable_content_md": "# Syllabus v2\nDays 1-2 simplified for "
              "classes 5-6.\nDay 4: internet safety session.\nDays 5-7: Kotlin "
              "introduction for classes 8-9 and block-based apps for juniors."},
    )
    r.check("manual upload completed the task (first-class path)",
            done["ok"] and done["deliverable_id"] is not None)
    from app.models.finance import Deliverable

    deliverable = await r.fetch_one(
        select(Deliverable).where(Deliverable.id == done["deliverable_id"])
    )
    r.check("deliverable versioned with source=manual_upload",
            deliverable.source == "manual_upload")
    # Task done + visible_to_client → client update drafted automatically.
    updates = await approvals_for(r, EMAILS["akash"], "progress update")
    r.check("client update drafted for the completed visible task",
            len(updates) >= 1)
    await approve_all(r, EMAILS["akash"], "progress update")
    await r.flush_sends()

    # The school agrees → deal agreed → the machine switches to delivering.
    agree = await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Re: Android Bootcamp Proposal",
        body="Agreed. Let's proceed with the special price.",
    )
    r.check("'Agreed. Let's proceed.' classified as approval",
            agree["intent"] == "approval", agree["intent"])
    from app.models.project import Project

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("project status → agreed → preparation (phase shift ran)",
            project.status in ("agreed", "preparation"), project.status)
    r.check("ops lead co-owns the project from 'agreed' onward",
            project.ops_owner_id is not None)
    proposal = await r.fetch_one(
        select(Proposal).where(Proposal.id == r.ctx["svs_proposal_id"])
    )
    r.check("proposal accepted at the special price",
            proposal.status == "accepted" and proposal.total_amount == 110000)

    # The preparation wave (playbook) needs the lead's yes (≥2 tasks rule).
    await approve_all(r, EMAILS["akash"], "plan v")
    tasks = await tasks_of(r, project_id)
    prep = [t for t in tasks if t.source == "playbook"]
    r.check("preparation wave generated from the playbook and staffed",
            len(prep) >= 5, f"{len(prep)} playbook tasks")
    await confirm_all_assignments(r, EMAILS["mithun"])
    from app.models.user import User

    vikram = await r.fetch_one(select(User).where(User.email == EMAILS["vikram"]))
    invoice_task = next((t for t in prep if "invoice" in t.title.lower()), None)
    r.check("advance-invoice task → Vikram (invoicing expert)",
            invoice_task is not None and invoice_task.assignee_id == vikram.id,
            invoice_task.assignment_reason if invoice_task else "missing")


async def w05_silence_followup_ladder(r: Runner) -> None:
    r.begin("W5 — Silence: the follow-up ladder")
    lead = await lead_by_name(r, "Green Valley School")
    contact = await contact_by_email(r, "principal@greenvalley.edu.in")

    await r.api(
        "POST", "/messages/draft", user=EMAILS["rahul"],
        json={"contact_id": contact.id, "kind": "proposal",
              "purpose": "proposal share", "subject": "STEM proposal — Green Valley",
              "facts": {"note": "proposal PDF shared for review"}},
    )
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()
    from app.models.comms import Thread

    thread = await r.fetch_one(select(Thread).where(Thread.contact_id == contact.id))
    r.check("outbound thread open, ball in the school's court",
            thread is not None and thread.last_direction == "outbound")

    # Day 4 — gentle email nudge.
    await r.backdate("threads", "last_message_at", thread.id, 5)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    nudges = await approvals_for(r, EMAILS["akash"], "nudge")
    r.check("day-4 gentle nudge drafted (needs a human tap, as ever)",
            len(nudges) >= 1)
    await approve_all(r, EMAILS["akash"], "nudge")
    await r.flush_sends()

    # Day 8 — channel switches to WhatsApp.
    await r.backdate("threads", "last_message_at", thread.id, 9)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    from app.models.messaging import OutboundMessage

    whatsapp_nudge = await r.fetch_one(
        select(OutboundMessage).where(
            OutboundMessage.contact_id == contact.id,
            OutboundMessage.channel == "whatsapp",
        )
    )
    r.check("day-8 nudge switched channel to WhatsApp",
            whatsapp_nudge is not None)
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()

    # Day 12 — no more automatic messages; a person calls.
    await r.backdate("threads", "last_message_at", thread.id, 13)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    from app.models.action_item import ActionItem

    call_task = await r.fetch_one(
        select(ActionItem).where(
            ActionItem.lead_id == lead.id, ActionItem.title.like("Call%")
        )
    )
    r.check("day-12: max nudges reached → call task created (org rule: max 2)",
            call_task is not None)

    # Day 30 — the system SUGGESTS cold; a human confirms.
    await r.backdate("threads", "last_message_at", thread.id, 31)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    from app.models.lead import Lead

    lead_row = await r.fetch_one(select(Lead).where(Lead.id == lead.id))
    r.check("day-30: lead cold suggested, never auto-moved",
            lead_row.suggested_state == "cold" and lead_row.state != "cold",
            f"suggested={lead_row.suggested_state} state={lead_row.state}")

    # ANY reply kills the ladder instantly.
    await send_inbound(
        r, from_address="principal@greenvalley.edu.in",
        subject="Re: STEM proposal",
        body="Thank you for the reminders — we are still reviewing it.",
    )
    thread = await r.fetch_one(select(Thread).where(Thread.id == thread.id))
    r.check("reply flipped the thread (ladder dead)",
            thread.last_direction == "inbound")


async def w06_second_meeting_plan_learns(r: Runner) -> None:
    r.begin("W6 — The second meeting: the plan learns (merge, not rewrite)")
    svs = await lead_by_name(r, "Swami Vivekananda School")
    project_id = r.ctx["svs_project_id"]

    # Kavita and Ramesh become stakeholders (edited by the sales owner).
    kavita = await contact_by_email(r, "kavita@svs.edu.in")
    await r.api(
        "POST", f"/projects/{project_id}/stakeholders", user=EMAILS["rahul"],
        json={"contact_id": kavita.id, "role_at_client": "academic_coordinator",
              "influence": "influencer", "preferred_channel": "whatsapp",
              "receives_progress_updates": True},
    )
    ramesh = await contact_by_email(r, "accounts@svs.edu.in")
    await r.api(
        "POST", f"/projects/{project_id}/stakeholders", user=EMAILS["rahul"],
        json={"contact_id": ramesh.id, "role_at_client": "accountant",
              "influence": "gatekeeper", "receives_progress_updates": False},
    )

    from app.models.project import ActionPlan, Project

    versions_before = await r.fetch_all(
        select(ActionPlan).where(ActionPlan.project_id == project_id)
    )
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": svs.id, "project_id": project_id,
              "meeting_type": "kickoff",
              "text": "Kickoff at Swami Vivekananda School with the principal and "
                      "Mrs. Kavita Menon. The school wants the bootcamp from "
                      "1 December 2026 to 7 December 2026, and a parents' demo on "
                      "the last day. The lab has only 30 computers for 400 "
                      "students so batches are needed. Kavita Menon will be the "
                      "day-to-day contact."},
    )
    r.check("planner merged the kickoff into a NEW version (never edited v1)",
            result["planner"]["action"] == "plan_merged", str(result["planner"]))

    # The re-plan diff goes to Akash.
    await approve_all(r, EMAILS["akash"], "plan v")
    await confirm_all_assignments(r, EMAILS["mithun"])

    versions_after = await r.fetch_all(
        select(ActionPlan).where(ActionPlan.project_id == project_id)
    )
    r.check("plan versions grew; old version superseded, never deleted",
            len(versions_after) > len(versions_before)
            and any(p.status == "superseded" for p in versions_after))
    active = [p for p in versions_after if p.status == "active"]
    r.check("exactly one active plan with an AI-written diff",
            len(active) == 1 and bool(active[0].changes_from_previous),
            active[0].changes_from_previous if active else "none")

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("delivery window anchored to 1–7 Dec",
            project.start_date is not None and project.start_date.month == 12
            and project.start_date.day == 1,
            str(project.start_date))
    tasks = await tasks_of(r, project_id)
    batch = next((t for t in tasks if "batch schedule" in t.title.lower()
                  and "30-computer" in t.title.lower()), None)
    r.check("new task born from the new fact (30-computer lab → batches)",
            batch is not None)
    from app.models.user import User

    mithun = await r.fetch_one(select(User).where(User.email == EMAILS["mithun"]))
    if batch is not None:
        r.check("batch schedule task → Mithun (scheduling expert)",
                batch.assignee_id == mithun.id, batch.assignment_reason or "")


async def w07_conflict_two_voices(r: Runner) -> None:
    r.begin("W7 — Two people said different things: conflicts")
    svs = await lead_by_name(r, "Swami Vivekananda School")
    project_id = r.ctx["svs_project_id"]

    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": svs.id, "project_id": project_id,
              "meeting_type": "review",
              "text": "Meeting at Swami Vivekananda School with Mrs. Kavita Menon. "
                      "She asked: let's compress the bootcamp to a 5-day format, "
                      "exams are close."},
    )
    r.check("merge held by a conflict — the AI never picks a side silently",
            result["planner"]["action"] == "held_by_conflict",
            str(result["planner"]))
    conflict_id = result["planner"]["conflict_id"]

    from app.models.project import ActionPlan, Conflict

    conflict = await r.fetch_one(select(Conflict).where(Conflict.id == conflict_id))
    r.check("conflict row records both sources",
            conflict is not None and conflict.status == "open"
            and conflict.source_a is not None and conflict.source_b is not None)
    held_plan = await r.fetch_one(
        select(ActionPlan).where(ActionPlan.id == conflict.held_plan_id)
    )
    r.check("the re-plan is held as draft (dates NOT changed yet)",
            held_plan is not None and held_plan.status == "draft")
    r.check("conflict raised to the sales lead",
            (await notifications_for(r, EMAILS["akash"], "different things")) != [])

    # The principal settles it (via Akash's resolution note).
    await r.api(
        "POST", f"/projects/{project_id}/conflicts/{conflict_id}/resolve",
        user=EMAILS["akash"],
        json={"resolution_note": "Principal confirmed by email: keep 7 days as planned"},
    )
    conflict = await r.fetch_one(select(Conflict).where(Conflict.id == conflict_id))
    r.check("conflict resolved with a permanent note", conflict.status == "resolved")
    # The held plan proceeds through normal review.
    await approve_all(r, EMAILS["akash"], "held plan")
    held_plan = await r.fetch_one(
        select(ActionPlan).where(ActionPlan.id == conflict.held_plan_id)
    )
    r.check("held plan released after resolution",
            held_plan.status in ("active", "superseded", "pending_review"),
            held_plan.status)
    why = await r.api(
        "GET", f"/why/conflict/{conflict_id}", user=EMAILS["sourav"],
    )
    r.check("'why did this happen?' has an answer months later (open to anyone)",
            "conflict" in why["trace"].lower() or "held" in why["trace"].lower())


async def w08_agreed_to_delivering(r: Runner) -> None:
    r.begin("W8 — 'We're agreed' — switching from selling to delivering")
    project_id = r.ctx["svs_project_id"]

    # The advance invoice: computed, gatekeeper-addressed, principal CC'd.
    invoice = await r.api(
        "POST", "/invoices", user=EMAILS["vikram"],
        json={"project_id": project_id, "kind": "advance", "advance_pct": 50},
    )
    r.check("advance = 50% of the accepted special price (55,000)",
            invoice["amount"] == 55000, invoice["computation"])
    r.check("invoice auto-addressed to the payments gatekeeper (Ramesh)",
            invoice["sent_to_stakeholder_id"] is not None)
    r.ctx["svs_advance_invoice_id"] = invoice["id"]

    sent = await r.api(
        "POST", f"/invoices/{invoice['id']}/send", user=EMAILS["vikram"],
    )
    r.check("invoice email drafted with an approval gate",
            sent["approval_id"] is not None)
    await approve_all(r, EMAILS["akash"], "invoice")
    flushed = await r.flush_sends()
    r.check("invoice email delivered to the accountant", flushed >= 1)
    from app.models.messaging import OutboundMessage

    invoice_msg = await r.fetch_one(
        select(OutboundMessage).where(OutboundMessage.kind == "invoice")
    )
    r.check("addressed To the accountant, CC the principal",
            invoice_msg is not None
            and invoice_msg.to_address == "accounts@svs.edu.in"
            and "principal@svs.edu.in" in (invoice_msg.cc or []),
            f"to={invoice_msg.to_address if invoice_msg else None}")

    # Advance arrives → recorded by Vikram → thank-you + delivery gates open.
    paid = await r.api(
        "POST", f"/invoices/{invoice['id']}/record-payment", user=EMAILS["vikram"],
        json={"amount": 55000, "method": "transfer", "note": "advance received"},
    )
    r.check("payment recorded; invoice fully paid", paid["invoice_status"] == "paid")


PART1 = [
    w01_first_meeting_to_first_plan,
    w01b_vague_meeting_no_project,
    w02_expo_card_to_lead,
    w03_proposal_built_checked_sent,
    w04_principal_asks_for_changes,
    w05_silence_followup_ladder,
    w06_second_meeting_plan_learns,
    w07_conflict_two_voices,
    w08_agreed_to_delivering,
]


async def main() -> int:
    r = Runner()
    await r.setup()
    try:
        from dryrun_part2 import PART2
        from dryrun_part3 import PART3
        from dryrun_part4 import PART4
        from dryrun_part5 import PART5
        from dryrun_part6 import PART6

        for workflow in PART1 + PART2 + PART3 + PART4 + PART5 + PART6:
            try:
                await workflow(r)
            except Exception as exc:  # noqa: BLE001 — record and continue
                import traceback

                r.fail(f"{type(exc).__name__}: {exc}")
                traceback.print_exc()
        ok = r.report()
        return 0 if ok else 1
    finally:
        await r.teardown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
