"""Finding F54 — a complaint made in a MEETING never became an incident.

Round 7 Act 13, on a real recording: the client said *"your trainer arrived 40
minutes late"* to a rep's face. The system produced a single P1 task and nothing
else — `incidents` stayed at **0**, no health event, no escalation, no
acknowledgement. The identical words sent by **email** page both leads in
seconds.

The whole of Workflow 22 — incident, severity, the `COMPLAINT_RECEIVED` health
event and the dual-lead P1 escalation — sat inside `_route_complaint`, which had
exactly one caller: the inbound intent router. And the meeting contract had **no
field for a complaint at all**, so the model was never even asked.

⚠ This was the one finding in its family with **no spec sentence behind it** —
W22 is written entirely as an inbound story, so it was a product decision, taken
by the project owner on 2026-08-06.

The fix shares the incident core and does NOT duplicate `_route_complaint`: the
inbound path keeps its holding reply, because emailing "you will hear from us
within the hour" to someone standing in front of you is not an improvement.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def _project(client, org, name: str):
    from app.database import SessionLocal
    from app.models.project import Project

    lead = (
        await client.post("/api/v1/leads", headers=auth(org["admin_token"]),
                          json={"name": f"{name} Client"})
    ).json()
    async with SessionLocal() as db:
        project = Project(
            org_id=org["id"], lead_id=lead["id"], name=name, status="delivery",
        )
        db.add(project)
        await db.flush()
        await db.commit()
        return project.id, lead["id"]


async def _raise(org_id, project_id, complaints):
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.lead import Lead
    from app.models.project import Project

    async with SessionLocal() as db:
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        lead = (
            await db.execute(select(Lead).where(Lead.id == project.lead_id))
        ).scalar_one()
        n = await planner_engine.raise_meeting_complaints(
            db, org_id=org_id, project=project, lead=lead,
            meeting_id="meeting-under-test", complaints=complaints,
        )
        await db.commit()
        return n


async def _incidents(project_id):
    from app.database import SessionLocal
    from app.models.work import Incident

    async with SessionLocal() as db:
        return (
            await db.execute(
                select(Incident).where(Incident.project_id == project_id)
            )
        ).scalars().all()


async def test_a_complaint_in_a_meeting_raises_an_incident(client, org_a):
    """The headline. Act 13's exact words."""
    project_id, _ = await _project(client, org_a, "F54 Late Trainer Co")
    raised = await _raise(org_a["id"], project_id, [
        {"detail": "The trainer arrived 40 minutes late for session two.",
         "raised_by": "Mrs. Kulkarni"},
    ])
    assert raised == 1

    incidents = await _incidents(project_id)
    assert len(incidents) == 1, (
        "F54: a complaint said face-to-face produced no incident, while the same "
        "words by email would have paged both leads"
    )
    assert "40 minutes late" in incidents[0].description
    assert incidents[0].source_type == "meeting", (
        f"the incident does not record that it came from a meeting: "
        f"{incidents[0].source_type}"
    )
    assert incidents[0].status == "open"


async def test_the_health_event_and_both_leads_are_reached(client, org_a, super_token):
    """The incident alone is not the finding — W22 is incident + health event +
    dual-lead P1. A fix that created a row and told nobody misses the point."""
    from app.database import SessionLocal
    from app.models.user import Notification
    from app.models.work import ProgressEvent

    # A dedicated org, NOT the shared org_a.
    #
    # This test needs leads to exist so they can be paged — but adding a
    # sales_lead to org_a changes where every client-message approval in the
    # suite routes, which silently broke an unrelated F2 test that asserts the
    # intro approval reaches the admin. Shared fixtures are shared state.
    from tests.conftest import create_org

    org = await create_org(
        client, super_token, name="F54 Escalation Org", slug="f54-esc",
        domain="f54-example.com",
    )
    for email, role in (("ops@f54-example.com", "operations_lead"),
                        ("sales@f54-example.com", "sales_lead")):
        resp = await client.post(
            "/api/v1/admin/users", headers=auth(org["admin_token"]),
            json={"email": email, "name": role.replace("_", " ").title(),
                  "role": role},
        )
        assert resp.status_code == 200, resp.text

    project_id, _ = await _project(client, org, "F54 Escalation Co")
    await _raise(org["id"], project_id, [
        {"detail": "Nobody turned up for the Tuesday session at all."},
    ])

    async with SessionLocal() as db:
        events = (
            await db.execute(
                select(ProgressEvent).where(
                    ProgressEvent.project_id == project_id,
                    ProgressEvent.event_type == "complaint_received",
                )
            )
        ).scalars().all()
        notes = (
            await db.execute(
                select(Notification).where(Notification.kind == "escalation")
            )
        ).scalars().all()
    assert events, "no COMPLAINT_RECEIVED event — project health never notices"
    assert any("Tuesday session" in (n.body or "") for n in notes), (
        "neither lead was paged about the complaint"
    )


async def test_severity_is_higher_during_delivery(client, org_a):
    """Same rule the inbound path uses — a complaint while you are ON SITE
    delivering is worse than one during planning."""
    from app.database import SessionLocal
    from app.models.project import Project

    project_id, _ = await _project(client, org_a, "F54 Severity Co")
    await _raise(org_a["id"], project_id,
                 [{"detail": "The materials were the wrong version again."}])
    assert (await _incidents(project_id))[0].severity == "high"

    other_id, _ = await _project(client, org_a, "F54 Planning Co")
    async with SessionLocal() as db:
        p = (
            await db.execute(select(Project).where(Project.id == other_id))
        ).scalar_one()
        p.status = "planning"
        await db.commit()
    await _raise(org_a["id"], other_id,
                 [{"detail": "The proposal took three weeks to arrive."}])
    assert (await _incidents(other_id))[0].severity == "medium"


async def test_a_meeting_with_no_complaint_raises_nothing(client, org_a):
    """The control, and the reason validation is conservative: an incident pages
    two leads at P1, so a false positive is expensive."""
    project_id, _ = await _project(client, org_a, "F54 Happy Co")
    assert await _raise(org_a["id"], project_id, []) == 0
    assert await _raise(org_a["id"], project_id, None) == 0
    assert await _incidents(project_id) == []


async def test_thin_complaints_are_dropped_not_escalated():
    """A bare "unhappy" is not something a lead can act on at 2am."""
    from app.ai.planning import validate_complaints

    assert validate_complaints([{"detail": "bad"}]) == []
    assert validate_complaints([{"detail": ""}]) == []
    assert validate_complaints("not a list") == []
    kept = validate_complaints([
        {"detail": "The trainer arrived 40 minutes late.", "raised_by": "Mrs. K"},
        {"detail": "The trainer arrived 40 minutes late.", "raised_by": "Someone"},
    ])
    assert len(kept) == 1, "the same complaint twice must not page the leads twice"
    assert kept[0]["raised_by"] == "Mrs. K"


async def test_both_meeting_prompts_ask_for_complaints():
    """The guard. F54 was, at bottom, a contract with no field for the thing —
    the model was never asked, so it could never answer."""
    from app.ai.planning import _INITIAL_SYSTEM, _MERGE_SYSTEM

    for name, prompt in (("initial", _INITIAL_SYSTEM), ("merge", _MERGE_SYSTEM)):
        assert "complaint" in prompt.lower(), (
            f"the {name} meeting prompt never mentions complaints — that is F54: "
            f"the meeting contract has no field for one"
        )


async def test_the_inbound_path_still_owns_its_holding_reply():
    """Do NOT duplicate `_route_complaint` — the finding is explicit. The email
    path keeps its "within the hour" draft; the meeting path must not send one,
    because you are already in the room."""
    import inspect

    from app.engines import inbound_engine, planner_engine

    inbound = inspect.getsource(inbound_engine._route_complaint)
    assert "holding reply" in inbound.lower(), (
        "the inbound holding reply was lost while extracting the shared core"
    )
    meeting = inspect.getsource(planner_engine.raise_meeting_complaints)
    assert "draft_client_message" not in meeting, (
        "the meeting path emails a holding reply to someone sitting in the room"
    )
