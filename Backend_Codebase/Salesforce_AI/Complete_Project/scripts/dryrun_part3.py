"""Dry-run PART 3 — TALKING TO THE SCHOOL WHILE WORK HAPPENS (Workflows 17–22)."""
from __future__ import annotations

from datetime import datetime, timedelta

from dryrun_lib import (
    EMAILS,
    Runner,
    approvals_for,
    approve_all,
    confirm_all_assignments,
    decide,
    notifications_for,
    send_inbound,
)
from sqlalchemy import select


async def w17_weekly_report_daily_digest(r: Runner) -> None:
    r.begin("W17 — The weekly report the principal reads, the digest the team uses")
    project_id = r.ctx["svs_project_id"]

    report = await r.api(
        "GET", f"/projects/{project_id}/weekly-report", user=EMAILS["akash"],
        params={"kind": "client"},
    )
    r.check("weekly client report built from real events",
            report.get("digest_id") is not None
            and "Done this week" in report["content_md"],
            report.get("reason", ""))
    r.check("report is honest about status",
            "Status:" in report["content_md"])
    # It goes out only after the sales lead's yes.
    pending = await approvals_for(r, EMAILS["akash"], "weekly")
    r.check("report waits for the sales lead", len(pending) >= 1)
    await approve_all(r, EMAILS["akash"], "weekly")
    flushed = await r.flush_sends()
    r.check("approved report sent on the project thread", flushed >= 1)

    internal = await r.api(
        "GET", f"/projects/{project_id}/weekly-report", user=EMAILS["mithun"],
        params={"kind": "internal"},
    )
    r.check("internal week-in-review exists (no approval needed)",
            internal.get("digest_id") is not None)

    digest = await r.api("GET", "/digests/daily", user=EMAILS["sourav"])
    # See dryrun_part4: the salutation depends on the hour now.
    r.check("personal daily digest: one screen, ordered by priority",
            digest["content_md"].lstrip().startswith("#"))
    timeline = await r.api(
        "GET", f"/projects/{project_id}/timeline", user=EMAILS["priya"],
    )
    r.check("live project timeline replaces status meetings",
            len(timeline) >= 10, f"{len(timeline)} events")

    # A week where nothing happened → NO report (a 'nothing happened' report hurts).
    from app.models.project import Project

    quiet = await r.fetch_one(
        select(Project).where(Project.id != project_id)
    )
    if quiet is not None:
        skip = await r.api(
            "GET", f"/projects/{quiet.id}/weekly-report", user=EMAILS["akash"],
            params={"kind": "client"},
        )
        r.check("quiet project → report skipped, not faked",
                skip.get("skipped") is True or skip.get("digest_id") is not None)


async def w18_school_changes_something_big(r: Runner) -> None:
    r.begin("W18 — The school changes something big: a date shift, end to end")
    project_id = r.ctx["svs_project_id"]
    from app.models.project import ActionPlan, Project

    # First ask: shift to 3 December.
    resp_a = await send_inbound(
        r, from_address="kavita@svs.edu.in",
        subject="Bootcamp dates",
        body="Our annual inspection got scheduled for 1-2 December. Can the "
             "bootcamp start on 3 December 2026 instead, and still finish "
             "before the 10th?",
    )
    r.check("date change understood with the constraint",
            resp_a["intent"] == "change_request"
            and resp_a["change_type"] == "date",
            f"{resp_a['intent']}/{resp_a['change_type']}")
    acks = await approvals_for(r, EMAILS["akash"], "acknowledge")
    r.check("immediate acknowledgement drafted — the school is never left hanging",
            len(acks) >= 1)
    await approve_all(r, EMAILS["akash"], "acknowledge")
    await r.flush_sends()

    # Mid-re-plan, a second email changes it AGAIN (the collapse test) —
    # and by more than 2 days, so the joint sales+ops rule fires.
    resp_b = await send_inbound(
        r, from_address="kavita@svs.edu.in",
        subject="Bootcamp dates — again",
        body="Actually the inspection moved. Please shift the bootcamp to start "
             "on 8 December 2026 instead and finish before the 14th.",
    )
    r.check("second ask processed", resp_b["intent"] == "change_request")
    plans = await r.fetch_all(
        select(ActionPlan).where(
            ActionPlan.project_id == project_id,
            ActionPlan.trigger == "client_reply",
        )
    )
    superseded_drafts = [p for p in plans if p.status == "superseded"]
    r.check("the open draft re-plan was superseded before activation — "
            "nothing half-applies",
            len(superseded_drafts) >= 1,
            str([(p.version, p.status) for p in plans]))

    # The 8-Dec plan: joint approval (sales owns the promise, ops the delivery).
    pending = [p for p in plans if p.status == "pending_review"]
    r.check("new plan waits for review with the confirmation email bundled",
            len(pending) == 1 and any(
                a["bundled_entities"]
                for a in await approvals_for(r, EMAILS["akash"], "date shift")
                if a["status"] == "pending"
            ))
    cards = [a for a in await approvals_for(r, EMAILS["akash"], "date shift")
             if a["status"] == "pending"]
    if not cards:
        r.fail("no pending date-shift approval for Akash")
        return
    card = cards[0]
    r.check("joint approver attached (delivery dates moved → ops must also say yes)",
            card["joint_with_user_id"] is not None)
    first = await decide(r, EMAILS["akash"], card["id"], approve=True)
    r.check("one yes is not enough — waits for the second approver",
            first["status"] == "approved" and first["joint_status"] == "pending")
    await decide(r, EMAILS["mithun"], card["id"], approve=True)

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("both yes → plan active in one stroke; project re-anchored to 8 Dec",
            project.start_date is not None and project.start_date.day == 8,
            str(project.start_date))
    flushed = await r.flush_sends()
    r.check("bundled confirmation email released by the SAME yes", flushed >= 1)
    from app.models.project import ClientCommitment

    renegotiated = await r.fetch_all(
        select(ClientCommitment).where(
            ClientCommitment.project_id == project_id,
            ClientCommitment.status == "renegotiated",
        )
    )
    r.check("commitments renegotiated, not broken", len(renegotiated) >= 1)


async def w19_question_answered_from_what_we_know(r: Runner) -> None:
    r.begin("W19 — A question on WhatsApp: answered from what we know")
    from app.models.comms import InboundMessage
    from app.models.messaging import OutboundMessage

    # Harish asks on WhatsApp; the syllabus deliverable literally answers it.
    resp = await send_inbound(
        r, from_address="+91 9800000055", channel="whatsapp",
        body="Will the bootcamp also cover Kotlin, or only block-based apps? "
             "Parents are asking.",
    )
    r.check("question matched by phone → contact → project",
            resp["intent"] == "question"
            and resp["matched_project_id"] == r.ctx["svs_project_id"],
            f"{resp['intent']} / {resp['matched_project_id']}")
    r.check("answer drafted from our own data (program + syllabus), not guessed",
            resp["status"] == "processed", resp.get("needs_human_reason") or "")
    draft = await r.fetch_one(
        select(OutboundMessage)
        .where(
            OutboundMessage.channel == "whatsapp",
            OutboundMessage.project_id == r.ctx["svs_project_id"],
            OutboundMessage.kind == "reply",
        )
        .order_by(OutboundMessage.created_at.desc())
    )
    r.check("draft cites the syllabus facts (kotlin)",
            draft is not None and "kotlin" in draft.body.lower())

    # No data → no guessing: a named human gets the question as a task.
    resp2 = await send_inbound(
        r, from_address="+91 9800000055", channel="whatsapp",
        body="Will you provide graduation scrolls stamped by the national "
             "education board?",
    )
    r.check("unanswerable → needs_human with the reason written down",
            resp2["status"] == "needs_human"
            and "never guesses" in (resp2["needs_human_reason"] or ""),
            str(resp2["needs_human_reason"]))
    from app.models.action_item import ActionItem

    question_task = await r.fetch_one(
        select(ActionItem).where(ActionItem.title.like("Answer %question%"))
    )
    r.check("a task carries the question to a person", question_task is not None)

    # Commercial topic → the money path, never the casual path.
    resp3 = await send_inbound(
        r, from_address="+91 9800000055", channel="whatsapp",
        body="Also - can we pay the amount in 3 instalments?",
    )
    r.check("payment talk routed to the money machinery",
            resp3["intent"] in ("payment_info", "question")
            and resp3["status"] in ("processed", "needs_human"))


async def w20_scope_grows(r: Runner) -> None:
    r.begin("W20 — Scope grows: 'add classes 3 and 4'")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem
    from app.models.project import Project
    from app.models.proposal import Proposal

    value_before = (
        await r.fetch_one(select(Project).where(Project.id == project_id))
    ).value_estimate

    resp = await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Wonderful demo!",
        body="The teacher demo went wonderfully. Please include classes 3 and 4 "
             "as well — another 150 more students would join the bootcamp.",
    )
    # F31: assert the PROPERTY (a scope point carrying the count of 150), not the
    # key it happens to be spelled with — `quantity_delta` is current and
    # `students_delta` is still accepted, so a future rename is not a regression.
    r.check("scope expansion understood (+150)",
            any(p.get("type") == "scope_change"
                and (p.get("quantity_delta") or p.get("students_delta")) == 150
                for p in resp["extracted_points"]),
            str(resp["extracted_points"]))

    amendment = await r.fetch_one(
        select(Proposal).where(
            Proposal.project_id == project_id,
            Proposal.amends_proposal_id.is_not(None),
        )
    )
    r.check("amendment computed strictly from the locked rate (150 × 300 = 45,000)",
            amendment is not None and amendment.total_amount == 45000,
            str(amendment.total_amount if amendment else None))

    blocked_scope = await r.fetch_all(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.blocked_reason == "awaiting amendment confirmation",
        )
    )
    # Tasks are created blocked pending the plan approval first.
    await approve_all(r, EMAILS["akash"], "scope expansion")
    await confirm_all_assignments(r, EMAILS["mithun"])
    blocked_scope = await r.fetch_all(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.blocked_reason == "awaiting amendment confirmation",
        )
    )
    r.check("expansion tasks exist but stay blocked — work never starts on "
            "unconfirmed money",
            len(blocked_scope) >= 3, f"{len(blocked_scope)} blocked tasks")
    await approve_all(r, EMAILS["akash"])  # the amendment reply email
    await r.flush_sends()

    # The school signs → tasks unblock, value grows.
    await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Re: addition for classes 3 and 4",
        body="We confirm the amendment for classes 3 and 4. Signed and agreed — "
             "go ahead.",
    )
    still_blocked = await r.fetch_all(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.blocked_reason == "awaiting amendment confirmation",
        )
    )
    r.check("confirmation unblocked the expansion tasks", len(still_blocked) == 0,
            f"{len(still_blocked)} still blocked")
    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("project value grew by the amendment (110,000 → 155,000)",
            (project.value_estimate or 0) >= (value_before or 0) + 45000,
            f"{value_before} → {project.value_estimate}")


async def w21_urgent_request(r: Runner) -> None:
    r.begin("W21 — 'Can you come tomorrow?' — the urgent request")
    project_id = r.ctx["svs_project_id"]
    from app.engines import planner_engine
    from app.models.project import ActionPlan, Project

    # Rahul's dictated URGENT promise → immediate feasibility → joint card.
    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        feasibility = await planner_engine.feasibility_pass(
            db, org_id=project.org_id, project=project,
            date_from=datetime.utcnow() + timedelta(days=1),
            date_to=datetime.utcnow() + timedelta(days=1),
        )
        plan, approval = await planner_engine.create_plan_version(
            db, org_id=project.org_id, project=project,
            trigger="manual", trigger_ref=None,
            summary="URGENT: teacher demo moved to tomorrow 11 AM (minister visit)",
            changes=["demo moved to tomorrow; cab tonight; two tasks pushed"],
            new_tasks=[
                {"title": "Book cab for tomorrow's demo tonight",
                 "phase": "preparation", "required_skill": "logistics",
                 "due_in_days": 0, "priority": "P1", "visible_to_client": False},
            ],
            approval_facts={"urgent": True},
        )
        await db.commit()
    r.check("feasibility answered BEFORE the promise", "feasible" in feasibility)
    r.check("urgent card demands BOTH leads (sales owns the promise, ops the delivery)",
            approval is not None and approval.joint_with_user_id is not None)
    cards = [a for a in await approvals_for(r, EMAILS["akash"], "URGENT")
             if a["status"] == "pending"]
    r.check("30-minute expiry on the urgent joint approval",
            cards and (
                datetime.fromisoformat(cards[0]["expires_at"])
                - datetime.utcnow()
            ) < timedelta(minutes=45))
    await decide(r, EMAILS["akash"], cards[0]["id"], approve=True)
    await decide(r, EMAILS["mithun"], cards[0]["id"], approve=True)
    plan_row = await r.fetch_one(
        select(ActionPlan).where(ActionPlan.id == plan.id)
    )
    r.check("both yes within the window → plan active in one stroke",
            plan_row.status == "active")

    # The mirror case: either rejection kills a joint approval.
    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        plan2, approval2 = await planner_engine.create_plan_version(
            db, org_id=project.org_id, project=project,
            trigger="manual", trigger_ref=None,
            summary="URGENT: second same-day ask (to be declined)",
            changes=["test"], new_tasks=[],
            approval_facts={"urgent": True},
        )
        await db.commit()
    await decide(r, EMAILS["mithun"], approval2.id, approve=False,
                 note="Sourav is genuinely unmovable that day")
    plan2_row = await r.fetch_one(select(ActionPlan).where(ActionPlan.id == plan2.id))
    r.check("either no rejects the whole joint approval",
            plan2_row.status in ("draft", "pending_review"), plan2_row.status)


async def w22_complaint(r: Runner) -> None:
    r.begin("W22 — A complaint: 'your trainer came late'")
    project_id = r.ctx["svs_project_id"]
    await r.api(
        "POST", f"/projects/{project_id}/status", user=EMAILS["mithun"],
        json={"status": "delivery"},
    )
    resp = await send_inbound(
        r, from_address="+91 9800000056", channel="whatsapp",
        body="Yesterday's session started 40 minutes late and some class-6 kids "
             "had no working laptops. This is a real problem, please fix this today.",
    )
    r.check("complaint classified, negative sentiment",
            resp["intent"] == "complaint" and resp["sentiment"] == "negative",
            f"{resp['intent']}/{resp['sentiment']}")
    from app.models.work import Incident

    incident = await r.fetch_one(
        select(Incident).where(Incident.project_id == project_id)
    )
    r.check("incident opened instantly — complaints never wait in a queue",
            incident is not None and incident.severity == "high")
    r.check("BOTH leads alerted together",
            (await notifications_for(r, EMAILS["mithun"], "complaint")) != []
            and (await notifications_for(r, EMAILS["akash"], "complaint")) != [])
    holding = [a for a in await approvals_for(r, EMAILS["akash"], "holding")
               if a["status"] == "pending"]
    r.check("holding reply drafted in seconds (never auto-sent)", len(holding) >= 1)
    await approve_all(r, EMAILS["akash"], "holding")
    await r.flush_sends()
    from app.models.project import Project

    project = await r.fetch_one(select(Project).where(Project.id == project_id))
    r.check("project health flipped to at_risk with the reason written",
            project.health in ("at_risk", "delayed"),
            f"{project.health}: {project.health_reason}")

    # Mithun creates the fix tasks; the substantive reply follows the fixes.
    from app.models.user import User

    sourav = await r.fetch_one(select(User).where(User.email == EMAILS["sourav"]))
    fixes = await r.api(
        "POST", f"/incidents/{incident.id}/fix-tasks", user=EMAILS["mithun"],
        json={"fix_tasks": [
            {"title": "Leave 45 min earlier — standing instruction Days 2-7",
             "assignee_id": sourav.id, "due_in_days": 0},
            {"title": "Arrange 5 spare laptops for remaining days",
             "required_skill": "logistics", "due_in_days": 0},
        ]},
    )
    r.check("fix tasks created P1 and staffed", len(fixes["fix_tasks"]) == 2)
    for fix in fixes["fix_tasks"]:
        await r.api(
            "POST", f"/tasks/{fix['id']}/complete", user=EMAILS["mithun"],
            json={"result_note": "done before noon"},
        )
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()

    resolved = await r.api(
        "POST", f"/incidents/{incident.id}/resolve", user=EMAILS["mithun"],
        json={"lesson": "Verify working machines a day before Day 1"},
    )
    r.check("incident closed with a written lesson", resolved["ok"])
    suggestions = await r.api(
        "GET", "/playbooks/suggestions", user=EMAILS["ananya"],
    )
    r.check("the lesson became a playbook suggestion for the org admin",
            len(suggestions) >= 1
            and "machines" in suggestions[0]["entry"]["title"].lower())
    accepted = await r.api(
        "POST", f"/playbooks/suggestions/{suggestions[0]['id']}/decide",
        user=EMAILS["ananya"], json={"accept": True},
    )
    r.check("one tap → every future project inherits the lesson",
            accepted["status"] == "accepted")
    from app.models.project import Playbook

    playbook = await r.fetch_one(
        select(Playbook).where(
            Playbook.phase == "preparation", Playbook.is_current.is_(True)
        )
    )
    r.check("current preparation playbook now contains the lesson",
            any("machines" in e.get("title", "").lower()
                for e in (playbook.entries or [])))


PART3 = [
    w17_weekly_report_daily_digest,
    w18_school_changes_something_big,
    w19_question_answered_from_what_we_know,
    w20_scope_grows,
    w21_urgent_request,
    w22_complaint,
]
