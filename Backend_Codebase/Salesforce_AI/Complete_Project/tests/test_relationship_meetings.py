"""Catch-up meetings take the light path.

The feature here is mostly an absence. A relationship meeting must produce a
summary, a feed entry and a suggested next touch — and must NOT produce action
items, a project plan, or a lead-state suggestion. Meena does not need a
project plan generated because she asked a client how their holidays went.

Absences are easy to break silently, so each one is asserted separately rather
than as "the light path ran". The last test in this file is the one that
matters most: a first_visit meeting in the same org must still do all the
things a relationship meeting must not, or this change has quietly broken
selling to make catching-up work.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import add_reached_contact, auth, create_org, login

pytestmark = pytest.mark.asyncio

DOMAIN = "rmmeet-example.com"

CATCH_UP = """
Meena: Good morning sir, just calling to see how things have been.
Client: All good, we finished the new wing last month. Busy but good.
Meena: That is good to hear. How did the programme land in the end?
Client: The team liked it. We are thinking about the exam season plan in
        November, might need something then.
Meena: I will check in closer to that. Anything else on your mind?
Client: No, just the computer lab we keep talking about. Next year maybe.
"""


@pytest.fixture
def fake_ai(monkeypatch):
    """Stub both analyses.

    `test_meetings.py` has a fixture of the same name, but fixtures are not
    shared across modules and it only stubs `analyse_meeting` — the catch-up
    call would reach a real provider. Both are stubbed here, and the catch-up
    one deliberately returns NO action-item field at all, because
    `RelationshipAnalysis` has none: if the light path ever tries to read one,
    it fails here rather than in front of a user.
    """
    from app.ai import extraction as extraction_mod
    from app.jobs import pipelines

    async def fake_relationship(transcript, *, org_name, client_name, **kwargs):
        return extraction_mod.RelationshipAnalysis(
            summary="Friendly catch-up. The new wing is finished and the team "
                    "liked the programme. Exam season plan may need something "
                    "in November.",
            key_facts=["Finished the new wing last month",
                       "Thinking about an exam season plan for November"],
            next_touch_days=21,
            next_touch_topics="Ask about the exam season plan and the computer lab",
        )

    async def fake_analyse(transcript, *, org_name, client_name, **kwargs):
        from datetime import datetime, timedelta
        return extraction_mod.MeetingAnalysis(
            action_items=[
                {"title": "Send the proposal", "description": "By Friday",
                 "due_hint": "Friday",
                 "due_date": datetime.utcnow().replace(microsecond=0)
                 + timedelta(days=4)},
            ],
            summary="A real discussion about the programme and pricing.",
            real_discussion=True,
            key_facts=["Wants three sessions a week"],
        )

    monkeypatch.setattr(
        pipelines.extraction, "analyse_relationship_meeting", fake_relationship)
    monkeypatch.setattr(pipelines.extraction, "analyse_meeting", fake_analyse)


@pytest.fixture
def stub_planner(monkeypatch):
    """Force the Planner onto its deterministic keyword path, so the sales
    regression test below does not need a live model."""
    from app.engines import planner_engine

    monkeypatch.setattr(planner_engine.nlu, "llm_available", lambda: False)


async def _add(client, org, email, name, role, department=None):
    resp = await client.post(
        "/api/v1/admin/users", headers=auth(org["admin_token"]),
        json={"email": email, "name": name, "role": role,
              **({"department": department} if department else {})},
    )
    assert resp.status_code == 200, resp.text
    user = resp.json()
    session = await login(client, email, user["temp_password"])
    return user["id"], session["access_token"]


@pytest.fixture(scope="module")
async def org(client, super_token) -> dict:
    org = await create_org(
        client, super_token,
        name="RM Meetings Co", slug="rm-meetings-co", domain=DOMAIN,
    )
    for key, email, name, role, dept in (
        ("priya", f"priya@{DOMAIN}", "Priya Agent", "sales_agent", "sales"),
        ("siva", f"siva@{DOMAIN}", "Siva Lead", "sales_lead", "sales"),
        ("meena", f"meena@{DOMAIN}", "Meena Manager",
         "relationship_manager", "relationship"),
    ):
        uid, token = await _add(client, org, email, name, role, dept)
        org[f"{key}_id"] = uid
        org[f"{key}_token"] = token
    return org


async def _open_lead(client, org, name) -> dict:
    created = await client.post(
        "/api/v1/leads", headers=auth(org["siva_token"]),
        json={"name": name, "city": "Kolkata", "owner_id": org["priya_id"]},
    )
    lead = created.json()
    await add_reached_contact(client, org["priya_token"], lead["id"])
    resp = await client.patch(
        f"/api/v1/leads/{lead['id']}/state", headers=auth(org["priya_token"]),
        json={"state": "open", "reason": "answered"},
    )
    assert resp.status_code == 200, resp.text
    return lead


async def _record(client, org, lead_id, token, meeting_type, text=CATCH_UP):
    """Type the meeting in rather than upload audio — `/meetings/notes` runs
    the same pipeline without needing a transcription stub."""
    resp = await client.post(
        "/api/v1/meetings/notes", headers=auth(token),
        json={"lead_id": lead_id, "title": "Catch-up", "text": text,
              "meeting_type": meeting_type},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── what a catch-up produces ────────────────────────────────────────────────

async def test_a_catch_up_is_summarised_and_lands_in_the_feed(
    client, org, fake_ai, stub_planner
):
    lead = await _open_lead(client, org, "Feed Client")
    await _record(client, org, lead["id"], org["meena_token"], "relationship")

    from app.database import SessionLocal
    from app.models.lead import ClientIntelligence

    async with SessionLocal() as db:
        feed = (await db.execute(
            select(ClientIntelligence).where(
                ClientIntelligence.lead_id == lead["id"],
                ClientIntelligence.category == "relationship",
            )
        )).scalars().all()
    assert feed, "the catch-up left nothing on the relationship feed"
    assert feed[0].note.strip(), "the feed entry is empty"


async def test_a_catch_up_plans_the_next_touch(client, org, fake_ai, stub_planner):
    """The suggested next touch is an ordinary `followups` row, owned by
    whoever recorded the meeting — a reminder, not a commitment."""
    from datetime import date

    from app.database import SessionLocal
    from app.models.followup import FollowUp

    lead = await _open_lead(client, org, "Next Touch Client")
    await _record(client, org, lead["id"], org["meena_token"], "relationship")

    async with SessionLocal() as db:
        rows = (await db.execute(
            select(FollowUp).where(FollowUp.lead_id == lead["id"])
        )).scalars().all()
    assert len(rows) == 1, f"expected one planned touch, got {len(rows)}"
    touch = rows[0]
    assert touch.owner_id == org["meena_id"], "the touch belongs to whoever called"
    assert touch.status == "pending"
    assert touch.due_date > date.today(), "a next touch in the past is not a plan"
    assert (touch.due_date - date.today()).days <= 180, \
        "the suggested date has to be one a person would accept"


async def test_a_catch_up_creates_no_tasks_and_no_plan(
    client, org, fake_ai, stub_planner
):
    """The absence IS the feature. Meena does not need a project plan because
    she asked how the holidays went."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from app.models.project import Project

    lead = await _open_lead(client, org, "No Tasks Client")
    result = await _record(client, org, lead["id"], org["meena_token"], "relationship")

    assert result.get("planner") is None, \
        f"the Planner ran on a catch-up: {result.get('planner')}"

    async with SessionLocal() as db:
        tasks = (await db.execute(
            select(ActionItem).where(ActionItem.lead_id == lead["id"])
        )).scalars().all()
        projects = (await db.execute(
            select(Project).where(Project.lead_id == lead["id"])
        )).scalars().all()
    assert tasks == [], f"a catch-up produced {len(tasks)} action item(s)"
    assert projects == [], f"a catch-up produced {len(projects)} project(s)"


async def test_a_catch_up_never_suggests_a_lead_state(
    client, org, fake_ai, stub_planner
):
    """Keeping in touch is not selling. A catch-up must not nudge the lead
    back toward the pipeline — that is step 6's job, and only with a person
    accepting it."""
    lead = await _open_lead(client, org, "No Suggestion Client")
    await _record(client, org, lead["id"], org["meena_token"], "relationship")

    detail = (await client.get(f"/api/v1/leads/{lead['id']}",
                               headers=auth(org["priya_token"]))).json()
    assert detail["suggested_state"] is None, detail["suggested_state"]
    assert detail["state"] == "open", "the catch-up moved the lead"


async def test_the_catch_up_shows_up_on_the_managers_home(
    client, org, fake_ai, stub_planner
):
    """End to end: the meeting is the touch, so Home must stop calling the
    client quiet and must show the planned next conversation."""
    lead = await _open_lead(client, org, "Home Refresh Client")
    for state in ("active", "execution_in_progress",
                  "client_execution_in_progress", "closed"):
        resp = await client.patch(
            f"/api/v1/leads/{lead['id']}/state", headers=auth(org["priya_token"]),
            json={"state": state, "reason": "walking to closed"},
        )
        assert resp.status_code == 200, resp.text
    handed = await client.post(
        f"/api/v1/leads/{lead['id']}/relationship/handover",
        headers=auth(org["priya_token"]), json={"manager_id": org["meena_id"]},
    )
    assert handed.status_code == 200, handed.text

    await _record(client, org, lead["id"], org["meena_token"], "relationship")

    rows = (await client.get("/api/v1/relationships/mine",
                             headers=auth(org["meena_token"]))).json()
    row = next(r for r in rows if r["lead_name"] == "Home Refresh Client")
    assert row["last_touch_at"] is not None
    assert row["is_quiet"] is False, "just-spoken-to must not read as quiet"
    assert row["next_touch_date"] is not None
    assert row["next_touch_overdue"] is False


# ── the relationship manager can keep their own touches ─────────────────────

async def test_a_manager_can_complete_and_book_a_touch(
    client, org, fake_ai, stub_planner
):
    """The gap step 4 recorded, now closed. `manage_leads` was doing two jobs:
    "may work the pipeline" and "may plan a conversation". Only the first
    should exclude a relationship manager."""
    from datetime import date, timedelta

    lead = await _open_lead(client, org, "Own Touch Client")
    await _record(client, org, lead["id"], org["meena_token"], "relationship")

    listed = await client.get("/api/v1/followups?due=all",
                              headers=auth(org["meena_token"]))
    assert listed.status_code == 200, listed.text
    mine = [f for f in listed.json() if f["lead_id"] == lead["id"]]
    assert mine, "the manager cannot see the touch the AI planned for them"

    done = await client.post(
        f"/api/v1/followups/{mine[0]['id']}/complete",
        headers=auth(org["meena_token"]), json={"note": "Called, all well"},
    )
    assert done.status_code == 200, done.text

    booked = await client.post(
        "/api/v1/followups", headers=auth(org["meena_token"]),
        json={"lead_id": lead["id"],
              "due_date": (date.today() + timedelta(days=14)).isoformat(),
              "channel": "call", "note": "Ask about the exam season plan"},
    )
    assert booked.status_code == 200, booked.text


async def test_an_operations_agent_still_cannot_book_a_touch(client, org):
    """Widening the gate to relationship managers must not have opened it to
    everyone. Operations holds neither permission."""
    from datetime import date, timedelta

    uid, token = await _add(
        client, org, f"ops@{DOMAIN}", "Ops Person", "operations_agent", "operations"
    )
    assert uid
    lead = await _open_lead(client, org, "Ops Cannot Book Client")
    resp = await client.post(
        "/api/v1/followups", headers=auth(token),
        json={"lead_id": lead["id"],
              "due_date": (date.today() + timedelta(days=3)).isoformat(),
              "channel": "call", "note": "should be refused"},
    )
    assert resp.status_code == 403, resp.text


# ── the sales path is untouched ─────────────────────────────────────────────

async def test_a_sales_meeting_still_does_everything_it_did_before(
    client, org, fake_ai, stub_planner
):
    """The regression guard, and the most important test in this file.

    A first_visit meeting through the same endpoint must still run the Planner
    and still produce work. If making catch-ups light has made selling light
    too, this fails.

    It deliberately does NOT assert a lead-state suggestion, and that is worth
    writing down because the obvious version of this test asserts one and then
    fails for the wrong reason — this one did. `lead_service.suggest_state`
    has exactly one caller in the codebase: `app/jobs/pipelines.py`, the
    pipeline behind an audio UPLOAD. `POST /meetings/notes` calls
    `planner_engine` directly and has never suggested a state, before this
    change or after it. Asserting one here tests a behaviour the typed path
    never had.

    The upload pipeline's own sales path — action items, the review gate and
    the state suggestion — is guarded by `test_meetings.py`, which exercises
    it end to end in the same suite run.
    """
    from app.database import SessionLocal
    from app.models.action_item import ActionItem

    lead = await _open_lead(client, org, "Still Sells Client")
    result = await _record(
        client, org, lead["id"], org["priya_token"], "first_visit",
        text="Priya: We discussed the programme and pricing in detail. "
             "The director asked for a proposal by Friday and wants "
             "three sessions a week for two hundred people.")

    assert result.get("planner") is not None, \
        "the Planner stopped running on a sales meeting"

    async with SessionLocal() as db:
        tasks = (await db.execute(
            select(ActionItem).where(ActionItem.lead_id == lead["id"])
        )).scalars().all()
    assert tasks, "a sales meeting stopped producing action items"
