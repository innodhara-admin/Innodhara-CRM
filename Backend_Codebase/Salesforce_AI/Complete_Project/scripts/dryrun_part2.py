"""Dry-run PART 2 — PEOPLE AND TASKS (Workflows 9–16)."""
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


async def w09_how_ai_picks_people(r: Runner) -> None:
    r.begin("W9 — How the AI picks the right person (deep dive)")
    project_id = r.ctx["svs_project_id"]
    from app.models.project import Project
    from app.models.work import AIDecision

    project = await r.fetch_one(select(Project).where(Project.id == project_id))

    decisions = await r.fetch_all(
        select(AIDecision).where(
            AIDecision.project_id == project_id,
            AIDecision.decision_type == "assignment",
        )
    )
    scored = [d for d in decisions if d.decision != "no assignment"]
    r.check("assignment decisions carry the candidate facts they scored",
            len(scored) >= 5
            and all("Candidates:" in (d.input_summary or "") for d in scored),
            f"{len(scored)} decisions")
    r.check("confidence recorded honestly on every pick",
            all(0.0 <= d.confidence <= 1.0 for d in scored))

    # assign_on=when_ready: deliberately unassigned until dependencies clear.
    from app.engines import planner_engine

    async with r.session() as db:
        project_db = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        await planner_engine.create_plan_version(
            db, org_id=project_db.org_id, project=project_db,
            trigger="manual", trigger_ref=None,
            summary="Vendor selection then print liaison (when_ready demo)",
            changes=["2 tasks added"],
            new_tasks=[
                {"title": "Select print vendor for certificates",
                 "phase": "preparation", "required_skill": "logistics",
                 "due_in_days": 2, "visible_to_client": False},
                {"title": "Coordinate with the selected print vendor",
                 "phase": "preparation", "required_skill": "logistics",
                 "due_in_days": 5, "visible_to_client": False,
                 "assign_on": "when_ready",
                 "depends_on": ["Select print vendor for certificates"]},
            ],
        )
        await db.commit()
    await approve_all(r, EMAILS["akash"], "when_ready demo")
    await confirm_all_assignments(r, EMAILS["mithun"])

    from app.models.action_item import ActionItem

    select_task = await r.fetch_one(
        select(ActionItem).where(
            ActionItem.title == "Select print vendor for certificates"
        )
    )
    liaison = await r.fetch_one(
        select(ActionItem).where(
            ActionItem.title == "Coordinate with the selected print vendor"
        )
    )
    r.check("when_ready task stays deliberately unassigned",
            liaison is not None and liaison.assignee_id is None
            and select_task.assignee_id is not None,
            f"liaison={liaison.assignee_id if liaison else '?'}")
    await r.api(
        "POST", f"/tasks/{select_task.id}/complete", user=EMAILS["mithun"],
        json={"result_note": "PrintCraft selected"},
    )
    liaison = await r.fetch_one(
        select(ActionItem).where(ActionItem.id == liaison.id)
    )
    r.check("dependency done → assigned at ready time with fresh data",
            liaison.assignee_id is not None, liaison.assignment_reason or "")
    r.ctx["liaison_task_id"] = liaison.id


async def w10_three_level_nudge_ladder(r: Runner) -> None:
    r.begin("W10 — The three-level nudge ladder")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem
    from app.models.user import User

    sourav = await r.fetch_one(select(User).where(User.email == EMAILS["sourav"]))
    task = await r.fetch_one(
        select(ActionItem).where(
            ActionItem.project_id == project_id,
            ActionItem.title.like("Prepare Day-1%"),
        )
    )
    if task is None:
        r.fail("expected the playbook's Day-1/2 lab exercises task")
        return
    await r.exec_sql(
        "UPDATE action_items SET assignee_id = :uid, status = 'open', "
        "reminder_level = 0, depends_on_ids = '[]' WHERE id = :tid",
        uid=sourav.id, tid=task.id,
    )

    # Level 1 — gentle, private.
    await r.backdate("action_items", "due_date", task.id, 2)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    task_row = await r.fetch_one(select(ActionItem).where(ActionItem.id == task.id))
    r.check("level 1 fired (gentle, private)", task_row.reminder_level == 1,
            str(task_row.reminder_level))
    r.check("Sourav got the level-1 ping",
            (await notifications_for(r, EMAILS["sourav"], "Reminder")) != [])

    # 'Give new date' with slack → accepted, ladder resets.
    new_due = datetime.utcnow() + timedelta(days=3)
    moved = await r.api(
        "POST", f"/tasks/{task.id}/new-date", user=EMAILS["sourav"],
        json={"new_due": new_due.isoformat(), "reason": "materials arrive Monday"},
    )
    r.check("new date accepted after the ripple check (slack exists)",
            moved["accepted"] is True, str(moved))
    task_row = await r.fetch_one(select(ActionItem).where(ActionItem.id == task.id))
    r.check("ladder reset on the accepted move", task_row.reminder_level == 0)

    # Ignore it long enough → level 2 (firm) then level 3 (lead).
    await r.backdate("action_items", "due_date", task.id, 4)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    task_row = await r.fetch_one(select(ActionItem).where(ActionItem.id == task.id))
    r.check("level 2 fired (firm + WhatsApp mirror)", task_row.reminder_level == 2,
            str(task_row.reminder_level))
    await r.backdate("action_items", "due_date", task.id, 8)
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    task_row = await r.fetch_one(select(ActionItem).where(ActionItem.id == task.id))
    r.check("level 3 escalated to the ops lead with one-tap options",
            task_row.reminder_level == 3
            and (await notifications_for(r, EMAILS["mithun"], "Escalation")) != [],
            str(task_row.reminder_level))
    from app.models.work import ProgressEvent, Reminder

    escalated = await r.fetch_one(
        select(ProgressEvent).where(
            ProgressEvent.event_type == "task_escalated",
            ProgressEvent.entity_id == task.id,
        )
    )
    r.check("task_escalated event on the stream", escalated is not None)
    # Done at any point → pending reminders die instantly.
    await r.api(
        "POST", f"/tasks/{task.id}/complete", user=EMAILS["sourav"],
        json={"result_note": "lab exercises ready"},
    )
    live = await r.fetch_all(
        select(Reminder).where(
            Reminder.target_id == task.id,
            Reminder.sent_at.is_(None), Reminder.cancelled_at.is_(None),
        )
    )
    r.check("completion cancelled every pending reminder", len(live) == 0)


async def w11_blocked_dependencies(r: Runner) -> None:
    r.begin("W11 — Blocked: dependencies and resequencing")
    project_id = r.ctx["svs_project_id"]
    from app.engines import planner_engine
    from app.models.action_item import ActionItem
    from app.models.project import Project

    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        await planner_engine.create_plan_version(
            db, org_id=project.org_id, project=project,
            trigger="manual", trigger_ref=None,
            summary="Approval, printing, dispatch chain",
            changes=["3 chained tasks"],
            new_tasks=[
                {"title": "Get syllabus approved by school", "phase": "preparation",
                 "required_skill": "curriculum_design", "due_in_days": 2,
                 "visible_to_client": True},
                {"title": "Print 400 student workbooks", "phase": "preparation",
                 "required_skill": "logistics", "due_in_days": 5,
                 "visible_to_client": False,
                 "depends_on": ["Get syllabus approved by school"]},
                {"title": "Dispatch materials to school", "phase": "preparation",
                 "required_skill": "logistics", "due_in_days": 7,
                 "visible_to_client": False,
                 "depends_on": ["Print 400 student workbooks"]},
            ],
        )
        await db.commit()
    await approve_all(r, EMAILS["akash"], "chain")
    await confirm_all_assignments(r, EMAILS["mithun"])

    approval_task = await r.fetch_one(
        select(ActionItem).where(ActionItem.title == "Get syllabus approved by school")
    )
    blocked = await r.api(
        "POST", f"/tasks/{approval_task.id}/block", user=EMAILS["meera"],
        json={"reason": "waiting for school approval since 3 days"},
    )
    r.check("task flagged blocked", blocked["ok"])
    # The blocker is the CLIENT → the machine chases the school, not Meera.
    chases = await approvals_for(r, EMAILS["akash"], "quick nod")
    if not chases:
        chases = await approvals_for(r, EMAILS["akash"], "chase")
    r.check("client chase drafted to the day-to-day contact (not a nudge at Meera)",
            len(chases) >= 1)
    await approve_all(r, EMAILS["akash"])
    await r.flush_sends()

    # Kavita replies 'Approved' → unblocked instantly, chain wakes.
    resp = await send_inbound(
        r, from_address="kavita@svs.edu.in", channel="email",
        subject="Re: a quick nod needed",
        body="Approved, go ahead with the printing.",
    )
    r.check("reply classified as approval", resp["intent"] == "approval",
            resp["intent"])
    approval_task = await r.fetch_one(
        select(ActionItem).where(ActionItem.id == approval_task.id)
    )
    r.check("blocked task released by the school's yes",
            approval_task.blocked is False)
    from app.models.work import ProgressEvent

    unblocked = await r.fetch_one(
        select(ProgressEvent).where(
            ProgressEvent.event_type == "task_unblocked",
            ProgressEvent.entity_id == approval_task.id,
        )
    )
    r.check("task_unblocked event recorded", unblocked is not None)


async def w12_someone_goes_on_leave(r: Runner) -> None:
    r.begin("W12 — Someone goes on leave")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem
    from app.models.user import User

    meera = await r.fetch_one(select(User).where(User.email == EMAILS["meera"]))
    leave_from = (datetime.utcnow() + timedelta(days=5)).date()
    leave_to = (datetime.utcnow() + timedelta(days=9)).date()
    async with r.session() as db:
        endangered = ActionItem(
            org_id=meera.org_id, project_id=project_id,
            lead_id=r.ctx["svs_lead_id"],
            title="Finalise junior-track syllabus annexure",
            phase="preparation", required_skill="curriculum_design",
            priority="P1", status="open", assignee_id=meera.id,
            due_date=datetime.utcnow() + timedelta(days=6),
            progress_percent=60, created_by="ai",
        )
        safe = ActionItem(
            org_id=meera.org_id, project_id=project_id,
            lead_id=r.ctx["svs_lead_id"],
            title="Quarterly content library refresh",
            phase="preparation", required_skill="curriculum_design",
            priority="P3", status="open", assignee_id=meera.id,
            due_date=datetime.utcnow() + timedelta(days=20),
            created_by="ai",
        )
        db.add(endangered)
        db.add(safe)
        await db.commit()
        endangered_id, safe_id = endangered.id, safe.id

    await r.api(
        "POST", "/leave", user=EMAILS["ananya"],
        json={"user_id": meera.id, "leave_from": leave_from.isoformat(),
              "leave_to": leave_to.isoformat()},
    )
    endangered_row = await r.fetch_one(
        select(ActionItem).where(ActionItem.id == endangered_id)
    )
    safe_row = await r.fetch_one(select(ActionItem).where(ActionItem.id == safe_id))
    r.check("endangered task reassigned away from Meera",
            endangered_row.assignee_id != meera.id,
            endangered_row.assignment_reason or "")
    r.check("safe task untouched — no noise",
            safe_row.assignee_id == meera.id)
    if endangered_row.assignee_id and endangered_row.assignee_id != meera.id:
        new_owner = await r.fetch_one(
            select(User).where(User.id == endangered_row.assignee_id)
        )
        handovers = await notifications_for(r, new_owner.email, "Handover")
        r.check("the receiver got the AI-assembled handover package (60% progress)",
                any("60%" in (n.body or "") for n in handovers))
    courtesy = await notifications_for(r, EMAILS["meera"], "While you're away")
    r.check("Meera got the courtesy note", len(courtesy) >= 1)
    from app.models.resource import ResourceBooking

    leave_booking = await r.fetch_one(
        select(ResourceBooking).where(
            ResourceBooking.user_id == meera.id, ResourceBooking.kind == "leave"
        )
    )
    r.check("leave lives on the master busy-calendar too", leave_booking is not None)
    # Reset leave so Meera is available for later workflows.
    await r.exec_sql(
        "UPDATE users SET on_leave_from = NULL, on_leave_to = NULL WHERE id = :uid",
        uid=meera.id,
    )
    await r.exec_sql(
        "DELETE FROM resource_bookings WHERE user_id = :uid AND kind = 'leave'",
        uid=meera.id,
    )


async def w13_someone_is_overloaded(r: Runner) -> None:
    r.begin("W13 — Someone is overloaded")
    from app.models.action_item import ActionItem
    from app.models.user import User

    priya = await r.fetch_one(select(User).where(User.email == EMAILS["priya"]))
    async with r.session() as db:
        for i in range(10):
            db.add(
                ActionItem(
                    org_id=priya.org_id, lead_id=r.ctx["svs_lead_id"],
                    title=f"Priya backlog item {i + 1}",
                    phase="sales", priority="P3", status="open",
                    assignee_id=priya.id,
                    due_date=datetime.utcnow() + timedelta(days=10 + i),
                    created_by="ai",
                )
            )
        await db.commit()
    await r.api("POST", "/sync/sweep", user=EMAILS["ananya"])
    from app.models.work import ProgressEvent

    overload = await r.fetch_one(
        select(ProgressEvent).where(
            ProgressEvent.event_type == "user_overloaded",
            ProgressEvent.entity_id == priya.id,
        )
    )
    r.check("overload detected (nobody had to notice)", overload is not None)
    cards = await notifications_for(r, EMAILS["akash"], "overloaded")
    r.check("her manager got the card WITH a rebalance proposal attached",
            any("Rebalance proposal" in (n.body or "") for n in cards))
    # Clean up the synthetic backlog so later loads stay realistic.
    await r.exec_sql(
        "UPDATE action_items SET status = 'cancelled' "
        "WHERE title LIKE 'Priya backlog item%'"
    )


async def w14_task_finishes_school_hears(r: Runner) -> None:
    r.begin("W14 — A task finishes and the school hears about it")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem
    from app.models.project import ClientCommitment

    task_id = r.ctx.get("svs_syllabus_task_id")
    task = await r.fetch_one(select(ActionItem).where(ActionItem.id == task_id))
    if task.status != "done":
        await r.api(
            "POST", f"/tasks/{task.id}/complete", user=EMAILS["meera"],
            json={"result_note": "Syllabus v1 attached; Kotlin intro for classes 8-9",
                  "completion_method": "in_app",
                  "deliverable_type": "syllabus",
                  "deliverable_title": "SVS 7-day syllabus",
                  "deliverable_content_md": "# 7-day syllabus\nBlock-based apps "
                  "days 1-4 for classes 5-7; Kotlin basics days 5-7 for "
                  "classes 8-9 in the computer lab."},
        )
    commitment = await r.fetch_one(
        select(ClientCommitment).where(
            ClientCommitment.linked_action_item_id == task_id
        )
    )
    r.check("the linked promise flipped to KEPT",
            commitment is not None and commitment.status == "kept",
            commitment.status if commitment else "none")
    updates = await approvals_for(r, EMAILS["akash"], "progress update")
    r.check("visible_to_client completion → client update drafted, gated on a human",
            len(updates) >= 1)
    await approve_all(r, EMAILS["akash"], "progress update")
    await r.flush_sends()
    from app.models.messaging import OutboundMessage

    update_msg = await r.fetch_one(
        select(OutboundMessage).where(
            OutboundMessage.project_id == project_id,
            OutboundMessage.triggered_by == "task_completed",
            OutboundMessage.status == "sent",
        )
    )
    r.check("update sent on the project thread (triggered_by=task_completed)",
            update_msg is not None)


async def w15_new_employee_joins(r: Runner) -> None:
    r.begin("W15 — A new employee joins mid-project")
    project_id = r.ctx["svs_project_id"]
    from app.core.security import hash_password
    from app.models.user import User, UserSkill

    async with r.session() as db:
        org_id = (
            await db.execute(select(User.org_id).where(User.email == EMAILS["ananya"]))
        ).scalar_one()
        divya = User(
            org_id=org_id, email="divya@yuvipep.com", name="Divya Menon",
            role="operations_agent", designation="Junior Trainer",
            department="operations", max_open_tasks=5,
            password_hash=hash_password("Password@123"),
        )
        db.add(divya)
        await db.flush()
        db.add(UserSkill(org_id=org_id, user_id=divya.id,
                         skill="android", level="good"))
        db.add(UserSkill(org_id=org_id, user_id=divya.id,
                         skill="teaching", level="basic"))
        await db.commit()
        divya_id = divya.id

    added = await r.api(
        "POST", f"/projects/{project_id}/members", user=EMAILS["mithun"],
        json={"user_id": divya_id, "role_in_project": "assistant_trainer"},
    )
    brief = added["onboarding_brief"]
    # The heading is asserted case-insensitively and without its domain word:
    # it used to read "School-side people" and was neutralised by finding F11.
    r.check("onboarding brief written by the machine, not a human",
            "Objective" in brief and "teammates" in brief.lower()
            and "-side people" in brief.lower())
    briefs = await notifications_for(r, "divya@yuvipep.com", "Welcome")
    r.check("Divya received the brief on joining", len(briefs) >= 1)
    # She simply exists in the candidate pool now.
    from app.engines import assignment_engine
    from app.models.action_item import ActionItem
    from app.models.project import Project

    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        probe = ActionItem(
            org_id=project.org_id, project_id=project_id,
            lead_id=r.ctx["svs_lead_id"],
            title="Prepare junior batch icebreakers",
            phase="preparation", required_skill="android",
            priority="P3", status="open",
            due_date=datetime.utcnow() + timedelta(days=6), created_by="ai",
        )
        db.add(probe)
        await db.flush()
        candidates, _tier = await assignment_engine.build_candidates(
            db, org_id=project.org_id, task=probe
        )
        names = {c.user.name for c in candidates}
        await db.commit()
    r.check("the next android task naturally scores Divya as a candidate",
            "Divya Menon" in names, str(names))


async def w16_declining_a_task(r: Runner) -> None:
    r.begin("W16 — Declining a task ('I cannot do this')")
    project_id = r.ctx["svs_project_id"]
    from app.models.action_item import ActionItem
    from app.models.project import Project
    from app.models.user import User

    baski = await r.fetch_one(select(User).where(User.email == EMAILS["baski"]))
    async with r.session() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        task = ActionItem(
            org_id=project.org_id, project_id=project_id,
            lead_id=r.ctx["svs_lead_id"],
            title="Design robotics demo for parents' day",
            phase="preparation", required_skill="robotics",
            priority="P2", status="open", assignee_id=baski.id,
            assigned_by="ai", assignment_reason="Baski: robotics expert",
            due_date=datetime.utcnow() + timedelta(days=6), created_by="ai",
        )
        db.add(task)
        await db.commit()
        task_id = task.id

    await r.api(
        "POST", f"/tasks/{task_id}/decline", user=EMAILS["baski"],
        json={"reason": "on_site_elsewhere",
              "note": "On-site at Sunrise all of that week"},
    )
    from app.models.resource import ResourceBooking
    from app.models.work import AIDecision, Assignment

    booking = await r.fetch_one(
        select(ResourceBooking).where(
            ResourceBooking.user_id == baski.id,
            ResourceBooking.note.like("%decline%"),
        )
    )
    r.check("the calendar gap was LEARNED — missing booking registered on the spot",
            booking is not None)
    gap_note = await r.fetch_one(
        select(AIDecision).where(AIDecision.decision == "Calendar gap registered")
    )
    r.check("the gap is written into ai_decisions (cannot surprise twice)",
            gap_note is not None)
    history = await r.fetch_all(
        select(Assignment).where(Assignment.action_item_id == task_id)
    )
    r.check("assignment history shows the decline with its reason",
            any(a.status == "declined" and a.decline_reason == "on_site_elsewhere"
                for a in history))
    task_row = await r.fetch_one(select(ActionItem).where(ActionItem.id == task_id))
    r.check("reassignment ran, excluding Baski",
            task_row.assignee_id != baski.id,
            f"assignee={task_row.assignee_id}")

    # Mithun picks 'split': design remotely (Baski) + deliver on-site (Sourav).
    sourav = await r.fetch_one(select(User).where(User.email == EMAILS["sourav"]))
    split = await r.api(
        "POST", f"/tasks/{task_id}/split", user=EMAILS["mithun"],
        json={"parts": [
            {"title": "Design robotics demo remotely (2 hrs)",
             "assignee_id": baski.id},
            {"title": "Deliver robotics demo on parents' day",
             "assignee_id": sourav.id},
        ]},
    )
    r.check("split into linked children", len(split["children"]) == 2)
    child2 = await r.fetch_one(
        select(ActionItem).where(ActionItem.id == split["children"][1]["id"])
    )
    r.check("children carry parent_item_id and a depends_on chain",
            child2.parent_item_id == task_id
            and split["children"][0]["id"] in (child2.depends_on_ids or []))
    # Clean the learned hold so it doesn't distort later feasibility checks.
    await r.exec_sql(
        "DELETE FROM resource_bookings WHERE user_id = :uid AND note LIKE '%decline%'",
        uid=baski.id,
    )


PART2 = [
    w09_how_ai_picks_people,
    w10_three_level_nudge_ladder,
    w11_blocked_dependencies,
    w12_someone_goes_on_leave,
    w13_someone_is_overloaded,
    w14_task_finishes_school_hears,
    w15_new_employee_joins,
    w16_declining_a_task,
]
