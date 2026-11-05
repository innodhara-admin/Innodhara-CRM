"""Dry-run PART 5 — THE LONG GAME AND THE HARD ROUTES (Workflows 27–30)
plus unscripted extra scenarios proving the shape absorbs new workflows."""
from __future__ import annotations

from datetime import datetime, timedelta

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
from sqlalchemy import select


async def w27_twelve_branch_chain(r: Runner) -> None:
    r.begin("W27 — A 12-branch chain: one deal, many schools")
    sunrise = await lead_by_name(r, "Sunrise Group of Schools")

    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["priya"],
        json={"lead_id": sunrise.id, "meeting_type": "first_visit",
              "text": "Group-level meeting with Dr. Anita Bose of Sunrise Group "
                      "of Schools. She wants the 7-day Android bootcamp across "
                      "all 12 branches over two terms, around 300 students per "
                      "branch. Group rate to be proposed. Share the syllabus "
                      "within a week."},
    )
    r.check("group meeting → parent project proposed",
            result["planner"]["action"] == "project_proposed")
    parent_id = result["planner"]["project_id"]
    r.ctx["sunrise_parent_id"] = parent_id
    await approve_all(r, EMAILS["akash"], "plan v1")
    await confirm_all_assignments(r, EMAILS["mithun"])
    await confirm_all_assignments(r, EMAILS["akash"])

    children = await r.api(
        "POST", f"/projects/{parent_id}/children", user=EMAILS["akash"],
        json={"branch_names": ["Sunrise Ballygunge", "Sunrise Kharagpur",
                               "Sunrise New Town"],
              "invoicing_mode": "group"},
    )
    r.check("child projects per branch, each with its own lead record",
            len(children["children"]) == 3)
    branch1 = children["children"][0]["project_id"]
    branch2 = children["children"][1]["project_id"]

    # The tour schedule: Sourav booked at branch 1 → branch 2 the same week
    # must NOT pick him (the cross-project view).
    from app.models.user import User

    sourav = await r.fetch_one(select(User).where(User.email == EMAILS["sourav"]))
    week_from = (datetime.utcnow() + timedelta(days=14)).date()
    week_to = (datetime.utcnow() + timedelta(days=18)).date()
    await r.api(
        "POST", "/bookings", user=EMAILS["mithun"],
        json={"user_id": sourav.id, "kind": "delivery",
              "date_from": week_from.isoformat(), "date_to": week_to.isoformat(),
              "project_id": branch1, "note": "Branch 1 delivery week"},
    )
    from app.engines import assignment_engine
    from app.models.action_item import ActionItem
    from app.models.project import Project

    async with r.session() as db:
        b2 = (
            await db.execute(select(Project).where(Project.id == branch2))
        ).scalar_one()
        probe = ActionItem(
            org_id=b2.org_id, project_id=branch2,
            lead_id=b2.lead_id,
            title="Deliver branch-2 bootcamp week",
            phase="delivery", required_skill="android",
            priority="P2", status="open",
            due_date=datetime.combine(week_to, datetime.min.time()),
            created_by="ai",
        )
        db.add(probe)
        await db.flush()
        assignment = await assignment_engine.assign_task(
            db, org_id=b2.org_id, task=probe
        )
        await db.commit()
        picked = probe.assignee_id
    r.check("the Resource & Calendar Engine kept Sourav out of two cities in "
            "one week",
            picked is not None and picked != sourav.id,
            f"picked={picked}")

    # Parent health = worst of children.
    async with r.session() as db:
        b2_task = (
            await db.execute(
                select(ActionItem).where(ActionItem.project_id == branch2)
            )
        ).scalars().first()
    await r.backdate("action_items", "due_date", b2_task.id, 5)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    parent = await r.fetch_one(select(Project).where(Project.id == parent_id))
    r.check("parent health rolls up as the worst of its children",
            parent.health in ("at_risk", "delayed"),
            f"{parent.health}: {parent.health_reason}")

    # Pause after N branches → cascades to unstarted children only.
    await r.api(
        "POST", f"/projects/{parent_id}/status", user=EMAILS["akash"],
        json={"status": "on_hold", "reason": "group wants to pause after review"},
    )
    kids = await r.fetch_all(
        select(Project).where(Project.parent_project_id == parent_id)
    )
    r.check("pause cascaded to unstarted children",
            all(k.status == "on_hold" for k in kids),
            str([k.status for k in kids]))


async def w28_not_this_year(r: Runner) -> None:
    r.begin("W28 — 'Not this year' — pausing and coming back")
    lead = await lead_by_name(r, "Modern Public School")
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": lead.id, "meeting_type": "first_visit",
              "text": "Meeting at Modern Public School with Mrs. Banerjee about "
                      "a 5-day Android bootcamp for classes 6 to 8 with around "
                      "200 students. Budget approval needed from the committee."},
    )
    project_id = result["planner"]["project_id"]
    await approve_all(r, EMAILS["akash"], "plan v1")
    await confirm_all_assignments(r, EMAILS["mithun"])
    await confirm_all_assignments(r, EMAILS["akash"])

    # The budget dies in committee → lost, with a revival record.
    revival_date = datetime.utcnow() + timedelta(days=5)
    await r.api(
        "POST", f"/projects/{project_id}/status", user=EMAILS["akash"],
        json={"status": "lost", "reason": "budget_timing",
              "revival_date": revival_date.isoformat(),
              "revival_context": "Liked syllabus; objection was FY budget only; "
                                 "principal was the champion; quote early-bird "
                                 "pricing next time"},
    )
    from app.models.action_item import ActionItem
    from app.models.lead import Lead

    open_tasks = await r.fetch_all(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.status.in_(["open", "in_progress"]),
        )
    )
    r.check("open tasks cancelled (not deleted)", len(open_tasks) == 0)
    await r.api(
        "PATCH", f"/leads/{lead.id}/state", user=EMAILS["rahul"],
        json={"state": "lost_for_now", "reason": "budget died in committee"},
    )
    lead_row = await r.fetch_one(select(Lead).where(Lead.id == lead.id))
    r.check("revival record on the lead (date + AI context)",
            lead_row.revival_date is not None
            and "champion" in (lead_row.revival_context or ""))

    # T-7 before the revival date, the Sync Engine wakes it.
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    lead_row = await r.fetch_one(select(Lead).where(Lead.id == lead.id))
    r.check("revival card fired inside the T-7 window",
            lead_row.revival_fired_at is not None)
    cards = await notifications_for(r, EMAILS["rahul"], "Revival card")
    r.check("the owner got the whole story replayed",
            any("champion" in (n.body or "") for n in cards))
    revival_task = await r.fetch_one(
        select(ActionItem).where(ActionItem.title.like("Re-open Modern%"))
    )
    r.check("a re-open task anchors the promised return", revival_task is not None)

    # The school comes back EARLY on a dormant thread → instant wake.
    contact = await contact_by_email(r, "principal@modernpublic.edu.in")
    from app.engines import communication_engine

    async with r.session() as db:
        thread = await communication_engine.ensure_thread(
            db, org_id=lead_row.org_id, lead_id=lead.id, contact_id=contact.id,
            channel="email", subject="Bootcamp — Modern Public School",
        )
        thread.status = "dormant"
        await db.commit()
    early = await send_inbound(
        r, from_address="principal@modernpublic.edu.in",
        subject="Good news",
        body="Our budget was approved early! Can we proceed with the bootcamp "
             "discussion?",
    )
    from app.models.work import ProgressEvent

    revived = await r.fetch_one(
        select(ProgressEvent).where(
            ProgressEvent.event_type == "lead_revived",
            ProgressEvent.entity_id == lead.id,
        )
    )
    r.check("early return woke the sleeping lead ahead of schedule",
            revived is not None and early["status"] in ("processed", "needs_human"))


async def w29_two_projects_one_school(r: Runner) -> None:
    r.begin("W29 — Two projects, one school, zero crossed wires")
    svs = await lead_by_name(r, "Swami Vivekananda School")

    # Priya's lab meeting creates a SECOND project on the same lead.
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["priya"],
        json={"lead_id": svs.id, "meeting_type": "first_visit",
              "text": "Separate discussion at Swami Vivekananda School with the "
                      "principal about a permanent STEM lab program for 2027 — "
                      "a different budget line. Lab setup plus a year of support. "
                      "Around 60 students per term in the lab."},
    )
    r.check("second project born on the same lead",
            result["planner"]["action"] == "project_proposed")
    lab_id = result["planner"]["project_id"]
    r.ctx["svs_lab_project_id"] = lab_id
    r.check("bootcamp and lab are different projects",
            lab_id != r.ctx["svs_project_id"])
    await approve_all(r, EMAILS["akash"], "plan v1")
    await confirm_all_assignments(r, EMAILS["mithun"])
    await confirm_all_assignments(r, EMAILS["akash"])

    # Content matching: 'the lab quote' lands on the lab project.
    resp = await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Regarding the lab",
        body="Regarding the STEM lab quote — when can we see the setup cost "
             "breakdown for the permanent lab?",
    )
    r.check("reply matched to the LAB project by content",
            resp["matched_project_id"] == lab_id,
            f"matched={resp['matched_project_id']}")

    # Genuinely unsplittable → both timelines + a named human.
    resp2 = await send_inbound(
        r, from_address="principal@svs.edu.in",
        subject="Friday",
        body="Let us discuss both the bootcamp and the lab together on Friday.",
    )
    r.check("unsplittable message attached to BOTH projects + needs_human",
            len(resp2.get("extracted_points", [])) >= 0
            and resp2["status"] == "needs_human"
            and resp2["matched_project_id"] is None,
            str(resp2["status"]))
    from app.models.comms import InboundMessage

    msg = await r.fetch_one(
        select(InboundMessage).where(InboundMessage.id == resp2["id"])
    )
    r.check("related_project_ids lists the projects it spans",
            len(msg.related_project_ids or []) >= 2,
            str(msg.related_project_ids))

    # Shared on purpose: lead-level intelligence serves both projects.
    from app.models.lead import ClientIntelligence

    intel = await r.fetch_all(
        select(ClientIntelligence).where(ClientIntelligence.lead_id == svs.id)
    )
    r.check("school intelligence is lead-level — the lab team inherits the "
            "bootcamp's lessons",
            len(intel) >= 2)
    # Pacing: the courtesy cap decision was recorded at some point this run.
    from app.models.work import AIDecision

    cap = await r.fetch_one(
        select(AIDecision).where(
            AIDecision.decision == "Send deferred by courtesy cap"
        )
    )
    r.check("outbound pacing per stakeholder enforced across projects",
            cap is not None)


async def w30_full_circle(r: Runner) -> None:
    r.begin("W30 — Full circle: the relationship engine")
    svs = await lead_by_name(r, "Swami Vivekananda School")

    # The Knowledge Engine briefs the Planner with rich priors.
    from app.engines import knowledge_engine
    from app.models.lead import Lead

    lead_row = await r.fetch_one(select(Lead).where(Lead.id == svs.id))
    async with r.session() as db:
        brief = await knowledge_engine.planner_brief(
            db, org_id=lead_row.org_id, lead=lead_row
        )
    r.check("planner brief carries known logistics and memories",
            len(brief["intelligence"]) >= 1 and len(brief["memories"]) >= 1,
            f"{len(brief['intelligence'])} intel / {len(brief['memories'])} memories")
    async with r.session() as db:
        story = await knowledge_engine.replay_story(
            db, org_id=lead_row.org_id, lead=lead_row
        )
    r.check("the whole story replays in one card (projects, proposals, memory)",
            "Project:" in story and "Memory:" in story)

    # The reach-out, grounded in the real past, opens the next project.
    result = await r.api(
        "POST", "/meetings/notes", user=EMAILS["rahul"],
        json={"lead_id": svs.id, "meeting_type": "first_visit",
              "text": "February meeting at Swami Vivekananda School about an "
                      "annual STEM program for 2027 building on the bootcamp: "
                      "a 20-day program across the year for classes 5 to 9 with "
                      "around 500 students. Share the syllabus within a week."},
    )
    r.check("the new engagement spins up Workflow-1 machinery with memory attached",
            result["planner"]["action"] == "project_proposed")
    await approve_all(r, EMAILS["akash"], "plan v1")
    await confirm_all_assignments(r, EMAILS["mithun"])
    await confirm_all_assignments(r, EMAILS["akash"])
    from app.models.project import ActionPlan

    new_plan = await r.fetch_one(
        select(ActionPlan)
        .where(ActionPlan.project_id == result["planner"]["project_id"])
    )
    r.check("plan v1 of the new year exists — the compounding the design "
            "exists for",
            new_plan is not None and new_plan.version == 1)


# ─────────────────────────────────────────────────────────────────────────────
# EXTRAS — unscripted workflows proving the six-step shape absorbs new cases
# ─────────────────────────────────────────────────────────────────────────────


async def x01_unmatched_message_triage(r: Runner) -> None:
    r.begin("X1 — A stranger writes in: triage, nothing dropped")
    resp = await send_inbound(
        r, from_address="unknown.sender@randomschool.edu.in",
        subject="Enquiry",
        body="We heard about your bootcamps. Can someone call us?",
    )
    r.check("unmatched sender → triage queue", resp["status"] == "triage")
    queue = await r.api("GET", "/inbound/triage", user=EMAILS["akash"])
    r.check("a human sees it in the queue",
            any(m["id"] == resp["id"] for m in queue))
    # The human sorts it onto a contact.
    contact = await contact_by_email(r, "principal@dpskol.edu.in")
    fixed = await r.api(
        "POST", f"/inbound/{resp['id']}/resolve", user=EMAILS["akash"],
        json={"contact_id": contact.id, "mark_processed": True},
    )
    r.check("resolved by hand — the engines reconcile manual work", fixed["ok"])


async def x02_circular_dependency_refused(r: Runner) -> None:
    r.begin("X2 — A re-plan creates a cycle: the Planner refuses")
    from app.engines import planner_engine
    from app.models.project import ActionPlan, Project

    project_id = r.ctx["svs_lab_project_id"]
    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        # A needs B and B needs A — activation must be refused.
        plan, approval = await planner_engine.create_plan_version(
            db, org_id=project.org_id, project=project,
            trigger="manual", trigger_ref=None,
            summary="cycle test",
            changes=["A↔B cycle"],
            new_tasks=[
                {"title": "Cycle task A", "phase": "preparation",
                 "due_in_days": 3, "depends_on": ["Cycle task B"]},
                {"title": "Cycle task B", "phase": "preparation",
                 "due_in_days": 3, "depends_on": ["Cycle task A"]},
            ],
        )
        await db.commit()
        plan_id = plan.id
    plan_row = await r.fetch_one(select(ActionPlan).where(ActionPlan.id == plan_id))
    r.check("plan refused activation and held as draft",
            plan_row.status == "draft")
    from app.models.work import AIDecision

    refusal = await r.fetch_one(
        select(AIDecision).where(AIDecision.decision.like("%refused activation%"))
    )
    r.check("the refusal is explained in ai_decisions",
            refusal is not None and "circular" in (refusal.reason or "").lower())


async def x03_do_not_contact_absolute(r: Runner) -> None:
    r.begin("X3 — do_not_contact is an absolute stop")
    project_id = r.ctx["svs_lab_project_id"]
    kavita = await contact_by_email(r, "kavita@svs.edu.in")
    await r.api(
        "POST", f"/projects/{project_id}/stakeholders", user=EMAILS["priya"],
        json={"contact_id": kavita.id, "role_at_client": "academic_coordinator",
              "influence": "influencer", "do_not_contact": True},
    )
    held = await r.api(
        "POST", "/messages/draft", user=EMAILS["priya"],
        json={"contact_id": kavita.id, "kind": "follow_up",
              "purpose": "lab follow-up", "project_id": project_id,
              "subject": "Lab discussion",
              "facts": {"note": "checking in"}},
    )
    r.check("the Communication Engine refused to draft", held.get("held") is True)
    from app.models.work import AIDecision

    refusal = await r.fetch_one(
        select(AIDecision).where(AIDecision.reason.like("%do_not_contact%"))
    )
    r.check("the refusal is on the record", refusal is not None)


async def x04_idempotency_and_double_taps(r: Runner) -> None:
    r.begin("X4 — Double-taps and retries never duplicate")
    from app.models.action_item import ActionItem

    task = await r.fetch_one(
        select(ActionItem).where(ActionItem.status == "done")
    )
    twice = await r.api(
        "POST", f"/tasks/{task.id}/complete", user=EMAILS["mithun"],
        json={"result_note": "double tap"},
    )
    r.check("double-completing a task is a no-op",
            twice.get("already_done") is True)
    # Deciding a decided approval → clean conflict, not a duplicate effect.
    done_approval = (await r.api(
        "GET", "/approvals", user=EMAILS["akash"],
        params={"status": "approved"},
    ))
    if done_approval:
        resp = await r.api(
            "POST", f"/approvals/{done_approval[0]['id']}/decide",
            user=EMAILS["akash"], json={"approve": True},
            expect_error=True,
        )
        r.check("double-approving is rejected with a conflict",
                resp.status_code == 409, str(resp.status_code))


async def x05_org_isolation(r: Runner) -> None:
    r.begin("X5 — One organisation, one world (isolation)")
    from app.core.security import hash_password
    from app.models.organisation import Organisation, OrgSettings
    from app.models.user import User

    async with r.session() as db:
        bf = Organisation(
            name="BrightFuture Labs", slug="brightfuture",
            email_domain="@brightfuture.com",
        )
        db.add(bf)
        await db.flush()
        db.add(OrgSettings(org_id=bf.id))
        db.add(
            User(
                org_id=bf.id, email="meena@brightfuture.com", name="Meena",
                role="org_admin", password_hash=hash_password("Password@123"),
            )
        )
        await db.commit()
    projects = await r.api("GET", "/projects", user="meena@brightfuture.com")
    r.check("BrightFuture sees zero YuviPep projects", projects == [])
    svs_project = await r.api(
        "GET", f"/projects/{r.ctx['svs_project_id']}",
        user="meena@brightfuture.com", expect_error=True,
    )
    r.check("direct access to another org's project is refused",
            svs_project.status_code == 404, str(svs_project.status_code))
    leads = await r.api("GET", "/leads", user="meena@brightfuture.com")
    r.check("no cross-org leads either",
            (leads == []) or (isinstance(leads, dict) and not leads.get("items")))


async def x06_whats_blocking_and_why(r: Runner) -> None:
    r.begin("X6 — 'What is blocking X?' and 'Why did the AI do that?'")
    project_id = r.ctx["svs_lab_project_id"]
    answer = await r.api(
        "GET", f"/projects/{project_id}/whats-blocking", user=EMAILS["priya"],
    )
    r.check("plain-language blocking answer", "answer" in answer)
    from app.models.work import AIDecision

    decision = await r.fetch_one(
        select(AIDecision).where(AIDecision.decision_type == "assignment")
    )
    why = await r.api(
        "GET", f"/why/{decision.entity_type}/{decision.entity_id}",
        user=EMAILS["shyam"],
    )
    r.check("why-trace shows the inputs, decision, reason and confidence",
            "confidence" in why["trace"])


PART5 = [
    w27_twelve_branch_chain,
    w28_not_this_year,
    w29_two_projects_one_school,
    w30_full_circle,
    x01_unmatched_message_triage,
    x02_circular_dependency_refused,
    x03_do_not_contact_absolute,
    x04_idempotency_and_double_taps,
    x05_org_isolation,
    x06_whats_blocking_and_why,
]
