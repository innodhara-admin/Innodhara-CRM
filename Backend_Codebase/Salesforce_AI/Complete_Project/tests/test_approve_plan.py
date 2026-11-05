"""Confirm once, then "Approve plan" (BS Carmel School, 29 Sep 2026; design
agreed 1 Oct 2026).

What went wrong: the review was confirmed twice (two phones, 42 seconds
apart). The second confirm re-created both kept items as new rows without
their due dates, and enqueued the Planner a second time.

What replaces it: a confirm is accepted once. The Planner's plan for a
recorded meeting is then HELD for the person who recorded it, who sees the
extra tasks with a switch each and taps "Approve plan". Only the tasks left
on go live, and the org's approval rules still apply after that tap.

STT and extraction are faked and the Planner runs on its deterministic stub
path, as in tests/test_meetings.py. Each test gets an organisation of its
own, because approval rules and the review switch are org-wide.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.ai import extraction as extraction_mod
from app.ai import stt as stt_mod
from app.database import SessionLocal
from app.jobs import pipelines
from app.models.action_item import ActionItem
from app.models.comms import Approval
from app.models.job import JobRecord
from app.models.meeting import Meeting
from app.models.project import ActionPlan, ClientCommitment
from tests.conftest import auth, create_org, login
from tests.test_meetings import _upload_meeting

pytestmark = pytest.mark.asyncio

API = "/api/v1"
TRANSCRIPT = (
    "Rahul: Thanks for meeting us. We discussed the program. "
    "Client: Please send the proposal and the demo dates."
)
DUE = datetime.utcnow().replace(microsecond=0) + timedelta(days=4)


@pytest.fixture
def fake_ai(monkeypatch):
    async def fake_transcribe(audio, mime, **_):
        return stt_mod.TranscriptionResult(text=TRANSCRIPT, language="en", confidence=0.93)

    async def fake_analyse(transcript, **_):
        return extraction_mod.MeetingAnalysis(
            action_items=[
                {"title": "Send the program proposal", "description": "Email it",
                 "due_hint": "this week", "due_date": DUE},
                {"title": "Share the demo dates", "description": None,
                 "due_hint": None, "due_date": None},
            ],
            summary="First discussion; the client wants a proposal.",
            real_discussion=True, key_facts=[],
        )

    from app.engines import planner_engine

    monkeypatch.setattr(pipelines.stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(pipelines.extraction, "analyse_meeting", fake_analyse)
    monkeypatch.setattr(planner_engine.nlu, "llm_available", lambda: False)


@pytest.fixture
async def org(client, super_token):
    tag = uuid.uuid4().hex[:8]
    domain = f"plan{tag}-example.com"
    org = await create_org(client, super_token, name=f"Plan {tag}",
                           slug=f"plan-{tag}", domain=domain)
    org["domain"] = domain
    me = (await client.get(f"{API}/auth/me", headers=auth(org["admin_token"]))).json()
    org["admin_id"] = me["user_id"]
    return org


async def _add_user(client, org, name: str, role: str) -> dict:
    email = f"{name.split()[0].lower()}{uuid.uuid4().hex[:6]}@{org['domain']}"
    made = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                             json={"email": email, "name": name, "role": role})
    assert made.status_code == 200, made.text
    token = (await login(client, email, made.json()["temp_password"]))["access_token"]
    return {"id": made.json()["id"], "token": token, "name": name}


async def _rule(client, org, condition: dict, approver_role: str) -> None:
    resp = await client.post(f"{API}/approval-rules", headers=auth(org["admin_token"]),
                             json={"entity_type": "plan_change", "condition": condition,
                                   "approver_role": approver_role, "rank": 1})
    assert resp.status_code == 200, resp.text


async def _processed_meeting(client, org, name="Program Client") -> dict:
    token = org["admin_token"]
    lead = (await client.post(f"{API}/leads", headers=auth(token),
                              json={"name": name})).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-process")
    return meeting


async def _review(client, token, meeting_id) -> list[dict]:
    resp = await client.get(f"{API}/meetings/{meeting_id}/review", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


async def _confirm(client, token, meeting_id, items) -> dict:
    resp = await client.post(
        f"{API}/meetings/{meeting_id}/review/confirm", headers=auth(token),
        json={"items": [{"id": i.get("id"), "title": i["title"],
                         "description": i.get("description"), "keep": True}
                        for i in items]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _plan_jobs(meeting_id: str) -> list[JobRecord]:
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(JobRecord).where(JobRecord.type == "plan_meeting"))).scalars().all()
    return [j for j in rows if (j.payload or {}).get("meeting_id") == meeting_id]


async def _run_queued_planner(meeting_id: str) -> dict:
    """Workers are off in tests: run the queued job the way the queue would."""
    jobs = await _plan_jobs(meeting_id)
    assert jobs, "nothing was queued for the Planner"
    return await pipelines.plan_meeting(jobs[-1].payload, jobs[-1].id)


async def _ready_meeting(client, org) -> dict:
    meeting = await _processed_meeting(client, org)
    items = await _review(client, org["admin_token"], meeting["id"])
    await _confirm(client, org["admin_token"], meeting["id"], items)
    await _run_queued_planner(meeting["id"])
    return meeting


async def _plan(client, token, meeting_id) -> dict:
    resp = await client.get(f"{API}/meetings/{meeting_id}/plan", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _approve(client, token, meeting_id, skip=()) -> tuple[int, dict]:
    resp = await client.post(f"{API}/meetings/{meeting_id}/plan/approve",
                             headers=auth(token), json={"skip_task_ids": list(skip)})
    return resp.status_code, resp.json()


# ── Part A: a confirm is accepted once ───────────────────────────────────


async def test_a_second_confirm_changes_nothing_and_plans_once(client, org, fake_ai):
    token = org["admin_token"]
    meeting = await _processed_meeting(client, org)
    items = await _review(client, token, meeting["id"])
    first = await _confirm(client, token, meeting["id"], items)
    assert first["action_items_saved"] == 2 and first["planning"] is True
    assert first.get("already_confirmed") is False

    async with SessionLocal() as db:
        before = {r.id for r in (await db.execute(select(ActionItem).where(
            ActionItem.meeting_id == meeting["id"]))).scalars().all()}

    # The same payload again, as the second phone sent it.
    second = await _confirm(client, token, meeting["id"], items)
    assert second["already_confirmed"] is True
    assert second["action_items_saved"] == 0 and second["planning"] is False

    async with SessionLocal() as db:
        after = (await db.execute(select(ActionItem).where(
            ActionItem.meeting_id == meeting["id"]))).scalars().all()
    assert {r.id for r in after} == before, "the second confirm created rows"
    assert len(await _plan_jobs(meeting["id"])) == 1, "the Planner was queued twice"


async def test_an_item_carrying_an_id_is_never_created_again(client, org, fake_ai):
    token = org["admin_token"]
    meeting = await _processed_meeting(client, org)
    items = await _review(client, token, meeting["id"])
    # An id that is not one of this review's pending items (a stale screen):
    # ignored, never written as a new task with that title.
    ghost = {"id": uuid.uuid4().hex, "title": "Ghost of an older item"}
    await _confirm(client, token, meeting["id"], items + [ghost])
    async with SessionLocal() as db:
        titles = [r.title for r in (await db.execute(select(ActionItem).where(
            ActionItem.meeting_id == meeting["id"]))).scalars().all()]
    assert "Ghost of an older item" not in titles


async def test_confirming_marks_the_meeting_as_planning(client, org, fake_ai):
    token = org["admin_token"]
    meeting = await _processed_meeting(client, org)
    await _confirm(client, token, meeting["id"], await _review(client, token, meeting["id"]))
    detail = (await client.get(f"{API}/meetings/{meeting['id']}", headers=auth(token))).json()
    assert detail["plan_state"] == "planning"
    assert (await _plan(client, token, meeting["id"]))["state"] == "planning"


async def test_the_planner_runs_once_per_meeting(client, org, fake_ai):
    meeting = await _ready_meeting(client, org)
    again = await _run_queued_planner(meeting["id"])
    assert again.get("skipped"), again
    async with SessionLocal() as db:
        plans = (await db.execute(select(ActionPlan).where(
            ActionPlan.trigger_ref == meeting["id"]))).scalars().all()
    assert len(plans) == 1


# ── Part B: the plan is held for the person who recorded the meeting ─────


async def test_the_plan_is_held_and_offered_in_three_places(client, org, fake_ai):
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)

    plan = await _plan(client, token, meeting["id"])
    assert plan["state"] == "ready", plan
    assert plan["can_approve"] is True
    assert plan["new_project"] is True and plan["project_name"]
    confirmed = [t for t in plan["tasks"] if t["confirmed"]]
    extra = [t for t in plan["tasks"] if not t["confirmed"]]
    assert {t["title"] for t in confirmed} == {"Send the program proposal",
                                             "Share the demo dates"}
    assert extra, "the stub Planner adds tasks of its own"
    assert any("New project" in line for line in plan["changes"])

    # Nothing extra is live yet.
    async with SessionLocal() as db:
        rows = (await db.execute(select(ActionItem).where(
            ActionItem.id.in_([t["id"] for t in extra])))).scalars().all()
        assert {r.status for r in rows} == {"pending_review"}
        held = (await db.execute(select(ActionPlan).where(
            ActionPlan.trigger_ref == meeting["id"]))).scalar_one()
        assert held.status == "pending_review"

    # Approvals: one card for the recorder.
    cards = (await client.get(f"{API}/approvals", headers=auth(token))).json()
    mine = [c for c in cards if c["entity_type"] == "meeting_plan"]
    assert len(mine) == 1 and mine[0]["entity_id"] == meeting["id"]

    # A notification that opens the meeting.
    notes = (await client.get(f"{API}/notifications", headers=auth(token))).json()
    ready = [n for n in notes if n["kind"] == "plan_ready"]
    assert len(ready) == 1
    assert (ready[0]["entity_type"], ready[0]["entity_id"]) == ("meeting", meeting["id"])

    # The meeting's own list stays what the person confirmed (the "5" at BS Carmel).
    detail = (await client.get(f"{API}/meetings/{meeting['id']}", headers=auth(token))).json()
    assert {i["title"] for i in detail["action_items"]} == {
        "Send the program proposal", "Share the demo dates"}
    assert detail["plan_state"] == "ready"


async def test_approve_activates_only_the_tasks_left_on(client, org, fake_ai):
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    plan = await _plan(client, token, meeting["id"])
    extra = [t for t in plan["tasks"] if not t["confirmed"]]
    off, waiting = extra[0], extra[1]

    # `waiting` depends on `off`; switching `off` off must free it.
    async with SessionLocal() as db:
        row = (await db.execute(select(ActionItem).where(
            ActionItem.id == waiting["id"]))).scalar_one()
        row.depends_on_ids = [off["id"]]
        await db.commit()
    shown = {t["id"]: t for t in (await _plan(client, token, meeting["id"]))["tasks"]}
    assert shown[waiting["id"]]["depends_on"] == [off["id"]]

    status, out = await _approve(client, token, meeting["id"], skip=[off["id"]])
    assert status == 200, out
    assert out["state"] == "approved" and out["already"] is False
    assert out["skipped"] == 1

    async with SessionLocal() as db:
        rows = {r.id: r for r in (await db.execute(select(ActionItem).where(
            ActionItem.id.in_([t["id"] for t in plan["tasks"]])))).scalars().all()}
        held = (await db.execute(select(ActionPlan).where(
            ActionPlan.trigger_ref == meeting["id"]))).scalar_one()
        hold = (await db.execute(select(Approval).where(
            Approval.entity_type == "meeting_plan",
            Approval.entity_id == meeting["id"]))).scalar_one()
    assert rows[off["id"]].status == "cancelled"
    assert rows[waiting["id"]].status == "open"
    assert off["id"] not in (rows[waiting["id"]].depends_on_ids or [])
    assert all(r.status == "open" for i, r in rows.items() if i != off["id"])
    assert held.status == "active"
    assert hold.status == "approved"
    assert (await _plan(client, token, meeting["id"]))["state"] == "approved"


async def test_confirmed_and_promised_tasks_cannot_be_switched_off(client, org, fake_ai):
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    plan = await _plan(client, token, meeting["id"])
    confirmed = next(t for t in plan["tasks"] if t["confirmed"])
    status, _ = await _approve(client, token, meeting["id"], skip=[confirmed["id"]])
    assert status == 422

    promised = next(t for t in plan["tasks"] if not t["confirmed"])
    async with SessionLocal() as db:
        row = (await db.execute(select(ActionItem).where(
            ActionItem.id == promised["id"]))).scalar_one()
        c = ClientCommitment(org_id=row.org_id, project_id=row.project_id,
                             text="Promised in the meeting", linked_action_item_id=row.id)
        db.add(c)
        await db.flush()
        row.client_commitment_id = c.id
        await db.commit()
    shown = {t["id"]: t for t in (await _plan(client, token, meeting["id"]))["tasks"]}
    assert shown[promised["id"]]["promised_to_client"] is True
    status, _ = await _approve(client, token, meeting["id"], skip=[promised["id"]])
    assert status == 422
    # Neither refusal changed anything.
    assert (await _plan(client, token, meeting["id"]))["state"] == "ready"


async def test_only_the_recorder_can_approve(client, org, fake_ai):
    meeting = await _ready_meeting(client, org)
    other = await _add_user(client, org, "Other Person", "sales_agent")
    plan = await _plan(client, other["token"], meeting["id"])
    assert plan["can_approve"] is False
    status, _ = await _approve(client, other["token"], meeting["id"])
    assert status == 403


async def test_a_rule_still_sends_the_plan_to_its_approver(client, org, fake_ai):
    lead_user = await _add_user(client, org, "Priya Nair", "sales_lead")
    await _rule(client, org, {"tasks_added_gte": 1}, "sales_lead")
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)

    status, out = await _approve(client, token, meeting["id"])
    assert status == 200, out
    assert out["state"] == "sent_for_approval"
    assert out["approver_name"] == "Priya Nair"

    async with SessionLocal() as db:
        held = (await db.execute(select(ActionPlan).where(
            ActionPlan.trigger_ref == meeting["id"]))).scalar_one()
        waiting = (await db.execute(select(Approval).where(
            Approval.entity_type == "plan_change", Approval.entity_id == held.id,
            Approval.status == "pending"))).scalars().all()
    assert held.status == "pending_review"
    assert [a.requested_from_user_id for a in waiting] == [lead_user["id"]]
    assert (await _plan(client, token, meeting["id"]))["state"] == "sent_for_approval"

    # The lead's yes activates it, and the meeting then reads as approved.
    resp = await client.post(f"{API}/approvals/{waiting[0].id}/decide",
                             headers=auth(lead_user["token"]), json={"approve": True})
    assert resp.status_code == 200, resp.text
    assert (await _plan(client, token, meeting["id"]))["state"] == "approved"


async def test_when_the_rules_approver_taps_approve_it_goes_live(client, org, fake_ai):
    await _rule(client, org, {"tasks_added_gte": 1}, "org_admin")
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    status, out = await _approve(client, token, meeting["id"])
    assert status == 200 and out["state"] == "approved", out
    async with SessionLocal() as db:
        pending = (await db.execute(select(Approval).where(
            Approval.entity_type == "plan_change",
            Approval.status == "pending", Approval.org_id == org["id"]))).scalars().all()
    assert pending == []


async def test_approve_twice_does_nothing_the_second_time(client, org, fake_ai):
    lead_user = await _add_user(client, org, "Priya Nair", "sales_lead")
    await _rule(client, org, {"tasks_added_gte": 1}, "sales_lead")
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    _, first = await _approve(client, token, meeting["id"])
    status, second = await _approve(client, token, meeting["id"])
    assert status == 200
    assert second["already"] is True and second["state"] == first["state"]
    async with SessionLocal() as db:
        waiting = (await db.execute(select(Approval).where(
            Approval.entity_type == "plan_change", Approval.status == "pending",
            Approval.requested_from_user_id == lead_user["id"]))).scalars().all()
    assert len(waiting) == 1, "the second tap asked the lead again"


async def test_approving_from_the_inbox_keeps_every_task(client, org, fake_ai):
    """An older app, or the Approvals inbox, approves the card itself."""
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    card = next(c for c in (await client.get(f"{API}/approvals", headers=auth(token))).json()
                if c["entity_type"] == "meeting_plan")
    resp = await client.post(f"{API}/approvals/{card['id']}/decide",
                             headers=auth(token), json={"approve": True})
    assert resp.status_code == 200, resp.text
    plan = await _plan(client, token, meeting["id"])
    assert plan["state"] == "approved"
    async with SessionLocal() as db:
        rows = (await db.execute(select(ActionItem).where(
            ActionItem.id.in_([t["id"] for t in plan["tasks"]])))).scalars().all()
    assert {r.status for r in rows} == {"open"}


async def test_rejecting_the_card_drops_the_extras_and_keeps_what_was_confirmed(
    client, org, fake_ai
):
    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    plan = await _plan(client, token, meeting["id"])
    card = next(c for c in (await client.get(f"{API}/approvals", headers=auth(token))).json()
                if c["entity_type"] == "meeting_plan")
    resp = await client.post(f"{API}/approvals/{card['id']}/decide",
                             headers=auth(token), json={"approve": False, "note": "not now"})
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as db:
        rows = {r.id: r for r in (await db.execute(select(ActionItem).where(
            ActionItem.id.in_([t["id"] for t in plan["tasks"]])))).scalars().all()}
        pending = (await db.execute(select(Approval).where(
            Approval.org_id == org["id"], Approval.status == "pending"))).scalars().all()
    for t in plan["tasks"]:
        expected = "open" if t["confirmed"] else "superseded"
        assert rows[t["id"]].status == expected, t
    assert pending == [], "a reject must not loop the plan to a lead"
    assert (await _plan(client, token, meeting["id"]))["state"] == "discarded"


async def test_with_the_review_switch_off_the_plan_is_ready_after_processing(
    client, org, fake_ai
):
    token = org["admin_token"]
    resp = await client.patch(f"{API}/admin/settings", headers=auth(token),
                              json={"require_action_item_review": False})
    assert resp.status_code == 200, resp.text
    meeting = await _processed_meeting(client, org)
    plan = await _plan(client, token, meeting["id"])
    assert plan["state"] == "ready", plan
    assert {t["title"] for t in plan["tasks"] if t["confirmed"]} == {
        "Send the program proposal", "Share the demo dates"}


async def test_a_planner_that_could_not_plan_says_so_and_can_be_retried(
    client, org, fake_ai, monkeypatch
):
    from app.engines import planner_engine

    token = org["admin_token"]
    meeting = await _processed_meeting(client, org)
    await _confirm(client, token, meeting["id"], await _review(client, token, meeting["id"]))

    async def unavailable(db, **kwargs):
        return {"action": "held_for_review", "reason": "ai_unavailable"}

    monkeypatch.setattr(planner_engine, "process_meeting", unavailable)
    await _run_queued_planner(meeting["id"])
    plan = await _plan(client, token, meeting["id"])
    assert plan["state"] == "failed" and plan["note"]

    monkeypatch.undo()
    from app.engines import planner_engine as pe

    monkeypatch.setattr(pe.nlu, "llm_available", lambda: False)
    resp = await client.post(f"{API}/meetings/{meeting['id']}/plan/retry", headers=auth(token))
    assert resp.status_code == 200, resp.text
    assert (await _plan(client, token, meeting["id"]))["state"] == "planning"
    await _run_queued_planner(meeting["id"])
    assert (await _plan(client, token, meeting["id"]))["state"] == "ready"

    again = await client.post(f"{API}/meetings/{meeting['id']}/plan/retry", headers=auth(token))
    assert again.status_code == 409


async def test_a_planning_job_that_keeps_failing_tells_the_recorder(
    client, org, fake_ai, monkeypatch
):
    from app.engines import planner_engine

    token = org["admin_token"]
    meeting = await _processed_meeting(client, org)
    await _confirm(client, token, meeting["id"], await _review(client, token, meeting["id"]))
    job = (await _plan_jobs(meeting["id"]))[-1]
    async with SessionLocal() as db:
        row = (await db.execute(select(JobRecord).where(JobRecord.id == job.id))).scalar_one()
        row.attempts = row.max_attempts - 1
        await db.commit()

    async def boom(db, **kwargs):
        raise RuntimeError("model timed out")

    monkeypatch.setattr(planner_engine, "process_meeting", boom)
    with pytest.raises(RuntimeError):
        await pipelines.plan_meeting_safe(job.payload, job.id)
    plan = await _plan(client, token, meeting["id"])
    assert plan["state"] == "failed"
    notes = (await client.get(f"{API}/notifications", headers=auth(token))).json()
    assert any(n["kind"] == "plan_failed" and n["entity_id"] == meeting["id"] for n in notes)


async def test_a_newer_plan_retires_the_held_one(client, org, fake_ai):
    from app.engines import planner_engine
    from app.models.project import Project

    token = org["admin_token"]
    meeting = await _ready_meeting(client, org)
    async with SessionLocal() as db:
        project = (await db.execute(select(Project).join(
            Meeting, Meeting.project_id == Project.id).where(
            Meeting.id == meeting["id"]))).scalar_one()
        await planner_engine.create_plan_version(
            db, org_id=org["id"], project=project, trigger="manual", trigger_ref=None,
            summary="A later re-plan", changes=["later"], new_tasks=[],
        )
        await db.commit()
        hold = (await db.execute(select(Approval).where(
            Approval.entity_type == "meeting_plan",
            Approval.entity_id == meeting["id"]))).scalar_one()
    assert hold.status == "expired"
    assert (await _plan(client, token, meeting["id"]))["state"] == "superseded"
    status, _ = await _approve(client, token, meeting["id"])
    assert status == 409


async def test_typed_notes_are_not_held(client, org, monkeypatch):
    """The typed-notes path calls the Planner directly and is unchanged."""
    from app.engines import planner_engine

    monkeypatch.setattr(planner_engine.nlu, "llm_available", lambda: False)
    token = org["admin_token"]
    lead = (await client.post(f"{API}/leads", headers=auth(token),
                              json={"name": "Notes Client"})).json()
    from tests.conftest import open_lead

    await open_lead(client, token, lead["id"])
    resp = await client.post(f"{API}/meetings/notes", headers=auth(token), json={
        "lead_id": lead["id"],
        "text": "Notes Client wants a 5 day program for 200 people from 10 November."})
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as db:
        holds = (await db.execute(select(Approval).where(
            Approval.org_id == org["id"],
            Approval.entity_type == "meeting_plan"))).scalars().all()
    assert holds == []
