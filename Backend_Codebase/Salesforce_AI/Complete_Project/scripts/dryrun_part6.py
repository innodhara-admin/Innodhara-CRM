"""Dry-run part 6 — workflows that are NOT in the 30-workflow document.

The spec's §6 promise is that any new workflow reduces to the same six-step
loop (sense → understand → decide → act → watch → learn) with data changes
only. These scenarios prove it: a brand-new program sold end to end with zero
code changes, a payment dispute, quiet-hours scheduling, the courtesy cap,
approval expiry → escalation, and the auto assignment mode.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from dryrun_lib import (
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
)


async def x07_new_program_zero_code(r: Runner) -> None:
    """A product that exists NOWHERE in the workflows doc: created by the
    admin as pure data, then sold and planned by the same machinery."""
    r.begin("X7 — A brand-new program works end to end with zero code changes")

    program = await r.api(
        "POST", "/admin/programs", user=EMAILS["ananya"],
        json={"name": "Robotics Club — Annual", "code": "ROBO_CLUB",
              "description": "Weekly robotics club sessions for classes 6-8, "
                             "kits included, annual engagement"},
    )
    await r.api(
        "POST", f"/admin/programs/{program['id']}/pricing", user=EMAILS["ananya"],
        json={"currency": "INR", "items": [
            {"code": "per_student", "label": "Club fee", "unit": "per student",
             "unit_price": 500},
            {"code": "kits", "label": "Robotics kits", "unit": "flat per club",
             "unit_price": 15000},
        ]},
    )
    await r.api(
        "POST", f"/admin/programs/{program['id']}/proposal-templates",
        user=EMAILS["ananya"],
        json={"name": "Robotics club — standard",
              "body_md": "Dear {contact_name},\n\nThank you for considering "
                         "{program_name} at {school_name}.\n\n{pricing_table}\n\n"
                         "Total: {total_amount}\n\n— {sender_name}, {org_name}"},
    )
    await r.api(
        "POST", "/playbooks", user=EMAILS["ananya"],
        json={"program_id": program["id"], "phase": "preparation", "entries": [
            {"title": "Order robotics kits for the club",
             "required_skill": "logistics", "offset_days": -10,
             "priority": "P2", "visible_to_client": False},
            {"title": "Prepare the annual club curriculum",
             "required_skill": "curriculum_design", "offset_days": -14,
             "priority": "P2", "visible_to_client": True},
        ]},
    )
    r.check("program, pricing, template and playbook created as data", True)

    dps = await lead_by_name(r, "Delhi Public School")
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": dps.id, "meeting_type": "first_visit",
              "text": "Meeting with Mrs. Sharma, principal of Delhi Public "
                      "School, about a robotics club for classes 6 to 8 with "
                      "around 200 students. Weekly sessions through the year. "
                      "Budget around one lakh. We must share the club "
                      "curriculum within a week."},
    )
    r.check("planner proposed a project for the NEW program",
            result["planner"]["action"] == "project_proposed",
            str(result["planner"]))
    project_id = result["planner"]["project_id"]
    r.ctx["robo_project_id"] = project_id
    r.ctx["robo_program_id"] = program["id"]

    from app.models.project import Project

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("priced from the NEW pricing table (200×500 + 15,000 = 115,000)",
            project.value_estimate == 115000,
            str(project.value_estimate))
    r.check("project bound to the new program",
            project.program_id == program["id"])

    await approve_all(r, EMAILS["akash"], "plan v1")
    await confirm_all_assignments(r, EMAILS["akash"])
    await confirm_all_assignments(r, EMAILS["mithun"])

    from app.models.action_item import ActionItem

    tasks = await r.fetch_all(
        select(ActionItem).where(ActionItem.project_id == project_id)
    )
    r.check("plan v1 staffed with written reasons",
            len(tasks) >= 1 and all(
                t.assignment_reason for t in tasks if t.assignee_id
            ),
            f"{len(tasks)} tasks")

    # Deal agreed → the phase shift generates the NEW playbook's wave.
    await r.api(
        "POST", f"/projects/{project_id}/status", user=EMAILS["akash"],
        json={"status": "agreed", "reason": "verbal yes from the principal"},
    )
    await confirm_all_assignments(r, EMAILS["mithun"])
    tasks = await r.fetch_all(
        select(ActionItem).where(ActionItem.project_id == project_id)
    )
    titles = [t.title for t in tasks]
    r.check("preparation wave generated from the NEW playbook",
            any("robotics kits" in t.lower() for t in titles)
            and any("club curriculum" in t.lower() for t in titles),
            str(titles))
    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("ops lead co-owns from 'agreed' onward",
            project.ops_owner_id is not None)


async def x08_invoice_dispute(r: Runner) -> None:
    """W25's hard route, exercised fully: proposal → accept → advance invoice
    → the school disputes it → instant P1 with the paper trail, invoice
    `disputed`, reminder ladder paused."""
    r.begin("X8 — The school disputes an invoice: paper trail, P1, ladder pause")
    project_id = r.ctx["robo_project_id"]
    dps = await lead_by_name(r, "Delhi Public School")

    proposal = await r.api(
        "POST", "/proposals", user=EMAILS["rahul"],
        json={"lead_id": dps.id, "program_id": r.ctx["robo_program_id"],
              "project_id": project_id,
              "quantities": {"per_student": 200, "kits": 1}},
    )
    review = await r.api(
        "POST", f"/proposals/{proposal['id']}/submit-review", user=EMAILS["rahul"],
    )
    if review["approval_id"]:
        await decide(r, EMAILS["akash"], review["approval_id"], approve=True)
    await r.api(
        "POST", f"/proposals/{proposal['id']}/approve-send", user=EMAILS["rahul"],
        json={"to_address": "principal@dpskol.edu.in"},
    )
    await r.flush_sends()
    await send_inbound(
        r, from_address="principal@dpskol.edu.in", subject="Robotics club",
        body="We accept the robotics club proposal. Agreed, let's proceed.",
    )
    from app.models.proposal import Proposal

    p = await r.fetch_one(select(Proposal).where(Proposal.id == proposal["id"]))
    r.check("proposal accepted on the school's yes", p.status == "accepted")

    # The school shares billing details → the owner becomes the payments
    # gatekeeper (invoices never go blindly to the principal).
    verma = await contact_by_email(r, "owner@dpskol.edu.in")
    await r.api(
        "POST", f"/projects/{project_id}/stakeholders", user=EMAILS["rahul"],
        json={"contact_id": verma.id, "role_at_client": "owner",
              "influence": "gatekeeper"},
    )
    invoice = await r.api(
        "POST", "/invoices", user=EMAILS["vikram"],
        json={"project_id": project_id, "kind": "advance", "advance_pct": 50},
    )
    r.check("advance computed from the accepted total (50% of 115,000 = 57,500)",
            invoice["amount"] == 57500, str(invoice["amount"]))
    await r.api(
        "POST", f"/invoices/{invoice['id']}/send", user=EMAILS["vikram"], json={},
    )
    await approve_all(r, EMAILS["akash"], "invoice")
    await r.flush_sends()

    # The owner (not the principal) writes back angry.
    resp = await send_inbound(
        r, from_address="owner@dpskol.edu.in", subject="Invoice",
        body="We dispute this invoice. The amount was never signed off by the "
             "management and we disagree with the kit charges.",
    )
    r.check("dispute → needs_human instantly (never argued by the AI)",
            resp["status"] == "needs_human", resp["status"])

    from app.models.action_item import ActionItem
    from app.models.finance import Invoice

    inv = await r.fetch_one(select(Invoice).where(Invoice.id == invoice["id"]))
    r.check("invoice flipped to `disputed` — the chasing ladder stops",
            inv.status == "disputed", inv.status)
    p1 = await r.fetch_one(
        select(ActionItem).where(ActionItem.title.like("Dispute/rejection%"),
                                 ActionItem.project_id == project_id)
    )
    r.check("P1 task carries the assembled paper trail",
            p1 is not None and p1.priority == "P1"
            and "Paper trail" in (p1.description or ""))
    r.check("the relationship owner was alerted",
            (await notifications_for(r, EMAILS["akash"], "dispute")) != [])


async def x09_quiet_hours(r: Runner) -> None:
    """Nothing non-urgent is sent outside the working window — drafts wait
    for the next working moment."""
    r.begin("X9 — Quiet hours: late drafts wait for the morning window")

    # Shrink the working window to one minute after midnight → 'now' is
    # always outside it.
    await r.api(
        "PATCH", "/admin/settings", user=EMAILS["ananya"],
        json={"workday_start": "00:01", "workday_end": "00:02"},
    )
    sharma = await contact_by_email(r, "principal@dpskol.edu.in")
    draft = await r.api(
        "POST", "/messages/draft", user=EMAILS["rahul"],
        json={"contact_id": sharma.id, "kind": "follow_up",
              "purpose": "quiet-hours probe",
              "instruction": "A short friendly check-in."},
    )
    from app.models.messaging import OutboundMessage

    msg = await r.fetch_one(
        select(OutboundMessage).where(OutboundMessage.id == draft["message_id"])
    )
    now = datetime.utcnow()
    r.check("non-urgent draft scheduled INSIDE the next working window",
            msg.scheduled_send_at is not None and msg.scheduled_send_at > now,
            str(msg.scheduled_send_at))

    urgent = await r.api(
        "POST", "/messages/draft", user=EMAILS["rahul"],
        json={"contact_id": sharma.id, "kind": "follow_up",
              "purpose": "urgent probe", "urgent": True,
              "instruction": "Urgent confirmation."},
    )
    msg_u = await r.fetch_one(
        select(OutboundMessage).where(OutboundMessage.id == urgent["message_id"])
    )
    r.check("P1-urgent drafts break quiet hours (org rule)",
            msg_u.scheduled_send_at is not None
            and msg_u.scheduled_send_at <= datetime.utcnow() + timedelta(minutes=1))

    # Restore the working window.
    await r.api(
        "PATCH", "/admin/settings", user=EMAILS["ananya"],
        json={"workday_start": "09:00", "workday_end": "18:30"},
    )


async def x10_courtesy_cap(r: Runner) -> None:
    """One stakeholder is never spammed by enthusiastic pipelines: the weekly
    cap defers the excess message and writes the reason."""
    r.begin("X10 — The weekly courtesy cap protects a busy principal")
    harish = await contact_by_email(r, "principal@svs.edu.in")
    draft = await r.api(
        "POST", "/messages/draft", user=EMAILS["rahul"],
        json={"contact_id": harish.id, "kind": "follow_up",
              "purpose": "courtesy-cap probe",
              "instruction": "A friendly note."},
    )
    from app.models.messaging import OutboundMessage
    from app.models.work import AIDecision

    msg = await r.fetch_one(
        select(OutboundMessage).where(OutboundMessage.id == draft["message_id"])
    )
    r.check("the excess message was deferred, not sent",
            msg.scheduled_send_at is not None
            and msg.scheduled_send_at > datetime.utcnow() + timedelta(hours=12),
            str(msg.scheduled_send_at))
    deferral = await r.fetch_one(
        select(AIDecision).where(
            AIDecision.decision == "Send deferred by courtesy cap"
        )
    )
    r.check("the deferral is explained in ai_decisions", deferral is not None)


async def x11_approval_expiry_escalation(r: Runner) -> None:
    """An unanswered approval never dies in an inbox: reminder at half-life,
    escalation to the org admin at expiry."""
    r.begin("X11 — An ignored approval escalates instead of dying")
    sharma = await contact_by_email(r, "principal@dpskol.edu.in")
    draft = await r.api(
        "POST", "/messages/draft", user=EMAILS["priya"],
        json={"contact_id": sharma.id, "kind": "follow_up",
              "purpose": "escalation probe",
              "instruction": "A note that Akash will ignore."},
    )
    approval_id = draft["approval_id"]
    r.check("draft waits on an approval", approval_id is not None)

    # Akash ignores it past expiry.
    await r.backdate("approvals", "expires_at", approval_id, days=1)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])

    from app.models.comms import Approval

    approval = await r.fetch_one(select(Approval).where(Approval.id == approval_id))
    r.check("escalated to the org admin with a fresh window",
            approval.escalated_to_user_id is not None
            and approval.status == "pending",
            f"status={approval.status}")
    r.check("the new approver was told",
            (await notifications_for(r, EMAILS["ananya"], "Escalated approval")) != [])


async def x12_auto_assignment_mode(r: Runner) -> None:
    """org_settings.assignment_mode = auto: assignments go live immediately
    (auto_accepted) — the assignee can still decline."""
    r.begin("X12 — assignment_mode=auto: live immediately, decline still works")
    await r.api(
        "PATCH", "/admin/settings", user=EMAILS["ananya"],
        json={"assignment_mode": "auto"},
    )
    project_id = r.ctx["robo_project_id"]
    dps = await lead_by_name(r, "Delhi Public School")
    await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": dps.id, "project_id": project_id,
              "meeting_type": "review",
              "text": "Follow-up call with Mrs. Sharma of Delhi Public School. "
                      "The computer lab has only 20 computers for the 200 "
                      "students, so plan batches accordingly."},
    )
    from app.models.action_item import ActionItem
    from app.models.work import Assignment

    batch_task = await r.fetch_one(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.title.like("%batch schedule%"),
        )
    )
    r.check("the new fact became a task", batch_task is not None)
    if batch_task is not None:
        r.check("assigned and LIVE without a confirmation screen",
                batch_task.assignee_id is not None
                and batch_task.status == "open",
                f"assignee={batch_task.assignee_id}")
        assignment = await r.fetch_one(
            select(Assignment).where(
                Assignment.action_item_id == batch_task.id
            ).order_by(Assignment.created_at.desc())
        )
        r.check("assignment recorded as auto_accepted",
                assignment is not None and assignment.status == "auto_accepted",
                assignment.status if assignment else "none")
    await r.api(
        "PATCH", "/admin/settings", user=EMAILS["ananya"],
        json={"assignment_mode": "lead_confirm"},
    )


PART6 = [
    x07_new_program_zero_code,
    x08_invoice_dispute,
    x09_quiet_hours,
    x10_courtesy_cap,
    x11_approval_expiry_escalation,
    x12_auto_assignment_mode,
]
