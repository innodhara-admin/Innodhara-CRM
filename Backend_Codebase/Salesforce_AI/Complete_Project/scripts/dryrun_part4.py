"""Dry-run PART 4 — DELIVERY AND MONEY (Workflows 23–26)."""
from __future__ import annotations

from datetime import datetime, timedelta

from dryrun_lib import (
    EMAILS,
    Runner,
    approvals_for,
    approve_all,
    notifications_for,
    send_inbound,
)
from sqlalchemy import select


from app.engines.assistant_engine import _greeting_name  # noqa: E402


async def w23_bootcamp_day(r: Runner) -> None:
    r.begin("W23 — Bootcamp day: running the show")
    project_id = r.ctx["svs_project_id"]
    from app.engines import events as event_stream
    from app.models.project import Project
    from app.models.user import User

    sourav = await r.fetch_one(select(User).where(User.email == EMAILS["sourav"]))
    # The day-of runsheet is the daily digest, assembled from the plan.
    digest = await r.api("GET", "/digests/daily", user=EMAILS["sourav"])
    # Checks a digest was produced, not which salutation the hour earned —
    # the greeting now follows the org's clock.
    r.check("morning digest doubles as the day-of runsheet",
            _greeting_name(sourav.name) in digest["content_md"])

    # One-tap on-site updates become events; issues silently become tasks.
    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        for update in ("Reached 8:25", "Batch 1 done, 34 of 38 students attended",
                       "Projector in lab-2 flickers, managed with lab-1"):
            await event_stream.emit(
                db, org_id=project.org_id, event_type="on_site_update",
                project_id=project_id, entity_type="project",
                entity_id=project_id, actor=sourav.id,
                details={"update": update},
            )
        await db.commit()
    timeline = await r.api(
        "GET", f"/projects/{project_id}/timeline", user=EMAILS["mithun"],
    )
    onsite = [e for e in timeline if e["event"] == "on_site_update"]
    r.check("on-site one-tap updates land on the live timeline", len(onsite) == 3)

    # The projector issue → a P2 task for Mithun (the trainer does no paperwork).
    from app.models.action_item import ActionItem
    from app.models.user import User as U

    mithun = await r.fetch_one(select(U).where(U.email == EMAILS["mithun"]))
    async with r.session() as db:
        db.add(
            ActionItem(
                org_id=mithun.org_id, project_id=project_id,
                lead_id=r.ctx["svs_lead_id"],
                title="Arrange backup projector for Days 2-7",
                phase="delivery", priority="P2", status="open",
                assignee_id=mithun.id, assigned_by="ai",
                assignment_reason="On-site issue flagged by the trainer",
                due_date=datetime.utcnow() + timedelta(days=1),
                source="ai_refinement", created_by="ai",
            )
        )
        await db.commit()

    # The Day-1 report: a deliverable built incrementally + a client summary.
    day_report = await r.api(
        "POST", "/deliverables", user=EMAILS["sourav"],
        json={"project_id": project_id, "type": "daily_report",
              "title": "Day 1 report",
              "content_md": "# Day 1\nSessions: 5 batches run.\nAttendance: "
              "34/38, 36/39, 33/35, 38/40, 30/33.\nHighlight: first apps built.\n"
              "Issue: projector flicker in lab-2 (worked around).",
              "source": "manual_upload"},
    )
    r.check("day report recorded as a versioned deliverable",
            day_report.get("id") is not None)
    from app.models.lead import Contact

    principal = await r.fetch_one(
        select(Contact).where(Contact.email == "principal@svs.edu.in")
    )
    draft = await r.api(
        "POST", "/messages/draft", user=EMAILS["akash"],
        json={"contact_id": principal.id,
              "kind": "progress_update", "purpose": "day-1 client summary",
              "project_id": project_id,
              "subject": "Day 1 — a lovely start",
              "facts": {"sessions": "5 batches run",
                        "attendance": "171 of 185 students",
                        "highlight": "first apps built by class 6"}},
    )
    r.check("client day summary drafted (internal version stays internal)",
            draft.get("message_id") is not None)
    await approve_all(r, EMAILS["akash"], "day")
    await r.flush_sends()


async def w24_materials_and_vendors(r: Runner) -> None:
    r.begin("W24 — Materials and vendors: dependencies outside the company")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem
    from app.models.user import User

    mithun = await r.fetch_one(select(User).where(User.email == EMAILS["mithun"]))
    async with r.session() as db:
        kits = ActionItem(
            org_id=mithun.org_id, project_id=project_id,
            lead_id=r.ctx["svs_lead_id"],
            title="Order 550 workbook kits",
            phase="preparation", priority="P2", status="open",
            assignee_id=mithun.id, assigned_by="ai",
            assignment_reason="logistics owner",
            due_date=datetime.utcnow() + timedelta(days=10),
            created_by="ai",
        )
        db.add(kits)
        await db.commit()
        kits_id = kits.id

    promised = datetime.utcnow() + timedelta(days=3)
    await r.api(
        "POST", f"/tasks/{kits_id}/vendor-promise", user=EMAILS["mithun"],
        json={"vendor_name": "PrintCraft", "promised_date": promised.isoformat()},
    )
    # T-3 chase goes to OUR coordinator, never the vendor.
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    chases = await notifications_for(r, EMAILS["mithun"], "Vendor check")
    r.check("T-3 vendor check chases our own coordinator",
            any("T-3" in n.title for n in chases))

    # One-day slip inside slack → absorbed quietly.
    slip1 = promised + timedelta(days=1)
    await r.api(
        "POST", f"/tasks/{kits_id}/vendor-slip", user=EMAILS["mithun"],
        json={"new_promised_date": slip1.isoformat(),
              "note": "vendor confirms one day late"},
    )
    from app.models.work import AIDecision

    absorbed = await r.fetch_one(
        select(AIDecision).where(
            AIDecision.decision == "Vendor slip absorbed by slack"
        )
    )
    r.check("slip inside slack absorbed — nobody alarmed unnecessarily",
            absorbed is not None)

    # A slip past the delivery start → the human hears the honest options.
    from app.models.project import Project

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    big_slip = (project.start_date or datetime.utcnow()) + timedelta(days=2)
    await r.api(
        "POST", f"/tasks/{kits_id}/vendor-slip", user=EMAILS["mithun"],
        json={"new_promised_date": big_slip.isoformat(),
              "note": "printer breakdown"},
    )
    threats = await notifications_for(r, EMAILS["mithun"], "threatens the plan")
    r.check("slack-eating slip escalates with options", len(threats) >= 1)
    await r.api(
        "POST", f"/tasks/{kits_id}/complete", user=EMAILS["mithun"],
        json={"result_note": "kits arrived after rush order",
              "completion_method": "external"},
    )


async def w25_getting_paid(r: Runner) -> None:
    r.begin("W25 — Getting paid")
    project_id = r.ctx["svs_project_id"]
    await r.api(
        "POST", f"/projects/{project_id}/status", user=EMAILS["akash"],
        json={"status": "payment_pending"},
    )
    invoice = await r.api(
        "POST", "/invoices", user=EMAILS["vikram"],
        json={"project_id": project_id, "kind": "balance", "due_in_days": 14},
    )
    r.check("balance derived from the whole paper trail "
            "(110,000 + 45,000 − 55,000 = 100,000)",
            invoice["amount"] == 100000, invoice["computation"])
    await r.api("POST", f"/invoices/{invoice['id']}/send", user=EMAILS["vikram"])
    await approve_all(r, EMAILS["akash"], "invoice")
    await r.flush_sends()
    r.ctx["svs_balance_invoice_id"] = invoice["id"]

    # +3 days late → polite; +10 → firm with the principal CC'd; +20 → call task.
    await r.backdate("invoices", "due_date", invoice["id"], 4)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()
    from app.models.messaging import OutboundMessage

    reminders = await r.fetch_all(
        select(OutboundMessage).where(
            OutboundMessage.kind == "invoice",
            OutboundMessage.triggered_by == "reminder_ladder",
        )
    )
    r.check("polite reminder aimed at the accountant", len(reminders) >= 1)

    await r.backdate("invoices", "due_date", invoice["id"], 11)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()
    reminders = await r.fetch_all(
        select(OutboundMessage).where(
            OutboundMessage.kind == "invoice",
            OutboundMessage.triggered_by == "reminder_ladder",
        )
    )
    firm = [m for m in reminders if "principal@svs.edu.in" in (m.cc or [])]
    r.check("firm note CCs the principal only at this level", len(firm) >= 1)

    await r.backdate("invoices", "due_date", invoice["id"], 21)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    from app.models.action_item import ActionItem

    call_task = await r.fetch_one(
        select(ActionItem).where(ActionItem.title.like("Call about unpaid invoice%"))
    )
    r.check("+20 days: writing stops, the sales lead gets the call task; "
            "the org admin is informed",
            call_task is not None
            and (await notifications_for(r, EMAILS["ananya"], "overdue")) != [])

    # 'Cheque ready, collect Friday' → a collection task; the ladder pauses.
    resp = await send_inbound(
        r, from_address="accounts@svs.edu.in",
        subject="Re: balance invoice",
        body="The cheque is ready for the payment. Please collect it on Friday.",
    )
    r.check("payment info understood", resp["intent"] == "payment_info",
            resp["intent"])
    collect = await r.fetch_one(
        select(ActionItem).where(ActionItem.title.like("Collect payment%"))
    )
    r.check("collection task created for the person nearby", collect is not None)

    # The money lands → thank-you drafted; part-payment math is honest.
    part = await r.api(
        "POST", f"/invoices/{invoice['id']}/record-payment", user=EMAILS["vikram"],
        json={"amount": 40000, "method": "cheque", "note": "Cheque no. 1123"},
    )
    r.check("part payment → part_paid, balance restated",
            part["invoice_status"] == "part_paid")
    rest = await r.api(
        "POST", f"/invoices/{invoice['id']}/record-payment", user=EMAILS["vikram"],
        json={"amount": 60000, "method": "transfer", "note": "balance settled"},
    )
    r.check("full settlement → paid", rest["invoice_status"] == "paid")
    thanks = [a for a in await approvals_for(r, EMAILS["akash"], "thank")
              if a["status"] == "pending"]
    r.check("thank-you note drafted (small thing, big goodwill)", len(thanks) >= 1)
    await approve_all(r, EMAILS["akash"], "thank")
    await r.flush_sends()


async def w26_finishing_well(r: Runner) -> None:
    r.begin("W26 — Finishing well: feedback, certificates, closure")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem

    # The closure wave from the playbook.
    wave = await r.api(
        "POST", f"/projects/{project_id}/phase-shift", user=EMAILS["mithun"],
        json={"phase": "closure"},
    )
    r.check("closure wave generated from the playbook",
            wave["action"] == "wave_generated" and wave["tasks"] >= 4, str(wave))
    await approve_all(r, EMAILS["akash"], "closure")
    await r.api("GET", "/assignments/proposed", user=EMAILS["mithun"])
    from dryrun_lib import confirm_all_assignments

    await confirm_all_assignments(r, EMAILS["mithun"])

    # Feedback lands; certificates mail-merged; closure report drafted from
    # real data — commitments shown honestly.
    closure_tasks = await r.fetch_all(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.phase == "closure",
            ActionItem.status.in_(["open", "in_progress"]),
        )
    )
    r.check("closure tasks staffed", len(closure_tasks) >= 4)
    for task in closure_tasks:
        payload = {"result_note": "done", "completion_method": "in_app"}
        title = task.title.lower()
        if "feedback" in title:
            payload.update({
                "deliverable_type": "feedback_summary",
                "deliverable_title": "Feedback 4.6/5",
                "deliverable_content_md": "4.6/5 from 210 responses; kids loved "
                "the day-5 app building; teachers ask for an annual program.",
            })
        elif "certificates" in title:
            payload.update({
                "deliverable_type": "certificates",
                "deliverable_title": "550 participation certificates",
                "deliverable_content_md": "Mail-merged from the attendance records.",
            })
        elif "closure report" in title or "report" in title:
            payload.update({
                "deliverable_type": "closure_report",
                "deliverable_title": "SVS closure report",
                "deliverable_content_md": "# Closure\nPromised vs delivered: "
                "commitments kept, one renegotiated (dates). Attendance 92%. "
                "Feedback 4.6/5.",
            })
        owner_email = None
        from app.models.user import User

        owner = await r.fetch_one(select(User).where(User.id == task.assignee_id))
        owner_email = owner.email if owner else EMAILS["mithun"]
        await r.api("POST", f"/tasks/{task.id}/complete", user=owner_email,
                    json=payload)
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()

    # Any straggler tasks are tidied, then the sweep closes the project.
    await r.exec_sql(
        "UPDATE action_items SET status = 'cancelled' WHERE project_id = :pid "
        "AND status IN ('open', 'in_progress')", pid=project_id,
    )
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    from app.models.project import Project

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("all done + all paid → project closed", project.status == "closed",
            project.status)
    from app.models.memory import MemoryChunk

    memories = await r.fetch_all(
        select(MemoryChunk).where(MemoryChunk.source_id == project_id)
    )
    r.check("the Knowledge Engine distilled the project into memory",
            len(memories) >= 1,
            memories[0].text[:120] if memories else "")
    crosssell = await notifications_for(r, EMAILS["akash"], "Cross-sell")
    r.check("cross-sell note fired — Workflow 30's opening scene",
            len(crosssell) >= 1)


PART4 = [
    w23_bootcamp_day,
    w24_materials_and_vendors,
    w25_getting_paid,
    w26_finishing_well,
]
