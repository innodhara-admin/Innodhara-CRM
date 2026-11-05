"""Meeting pipeline: upload -> (faked) transcribe -> extract -> review gate ->
confirmed action items -> Planner. STT and extraction are faked and the
Planner is forced onto its deterministic stub path; the pipeline, review flow,
job hand-off and persistence all run for real."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.ai import extraction as extraction_mod
from app.ai import stt as stt_mod
from app.jobs import pipelines
from tests.conftest import auth, open_lead

pytestmark = pytest.mark.asyncio

FAKE_TRANSCRIPT = (
    "Rahul: Thanks for meeting us, Mrs. Principal. We discussed the IBC "
    "program. Principal: Please send the proposal and demo dates."
)

# The model resolves "this week" itself now (finding F8) — the pipeline stores
# the DATE, not prose in a description.
FAKE_DUE = datetime.utcnow().replace(microsecond=0) + timedelta(days=4)


@pytest.fixture
def fake_ai(monkeypatch):
    async def fake_transcribe(audio, mime, *, org_id=None, user_id=None):
        return stt_mod.TranscriptionResult(
            text=FAKE_TRANSCRIPT, language="en", confidence=0.93
        )

    # **kwargs so this fake does not pin the real signature: a new keyword
    # on `analyse_meeting` is a change to the caller's contract, not to
    # what this test is about (the pipeline's handling of the result).
    async def fake_analyse(transcript, *, org_name, client_name, **kwargs):
        return extraction_mod.MeetingAnalysis(
            action_items=[
                {"title": "Send IBC proposal", "description": "Email it",
                 "due_hint": "this week", "due_date": FAKE_DUE},
                {"title": "Share demo dates", "description": None,
                 "due_hint": "when the hall is free", "due_date": None},
            ],
            summary="Good first discussion about IBC; school wants a proposal.",
            real_discussion=True,
            key_facts=["School prefers morning sessions"],
        )

    monkeypatch.setattr(pipelines.stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(pipelines.extraction, "analyse_meeting", fake_analyse)


@pytest.fixture
def stub_planner(monkeypatch):
    """Force the Planner onto its deterministic keyword path.

    Without this the meeting pipeline would reach for the real model provider
    (conftest sets a deliberately invalid key), so the tests would be slow,
    network-dependent and non-deterministic."""
    from app.engines import planner_engine

    monkeypatch.setattr(planner_engine.nlu, "llm_available", lambda: False)


async def _record_consent(client, token: str, lead_id: str, *, method="verbal") -> None:
    """F40: consent is proof captured BEFORE the recording, not a checkbox at
    upload. The app does this from its consent sheet; the harness has to as
    well, or it is testing a flow the product does not have."""
    resp = await client.post(
        f"/api/v1/leads/{lead_id}/consent",
        headers=auth(token),
        json={"method": method, "note": "Agreed before recording"},
    )
    assert resp.status_code == 200, resp.text


async def _upload_meeting(client, token: str, lead_id: str) -> dict:
    # You cannot meet a school nobody has called yet: meetings are refused
    # while a lead is in pre-sales. Every caller here is testing what happens
    # after that point, so open the lead first.
    await open_lead(client, token, lead_id)
    await _record_consent(client, token, lead_id)
    resp = await client.post(
        "/api/v1/meetings/upload",
        headers=auth(token),
        data={"lead_id": lead_id, "consent_confirmed": "true",
              "duration_seconds": "1800"},
        files={"file": ("meeting.mp3", b"fake-audio-bytes-000", "audio/mpeg")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_consent_is_mandatory(client, org_a):
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "No Consent School"})
    ).json()
    # Open it so the refusal under test is the CONSENT one, not pre-sales.
    await open_lead(client, token, lead["id"])
    resp = await client.post(
        "/api/v1/meetings/upload",
        headers=auth(token),
        data={"lead_id": lead["id"], "consent_confirmed": "false"},
        files={"file": ("m.mp3", b"x", "audio/mpeg")},
    )
    assert resp.status_code == 422


async def test_full_pipeline_with_review_gate(client, org_a, fake_ai):
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Pipeline School"})
    ).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    assert meeting["status"] == "uploaded"

    # Run the pipeline job directly (workers are off in tests).
    result = await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job1")
    assert result["action_items"] == 2
    assert result["review_required"] is True  # org default switch is ON

    detail = (
        await client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth(token))
    ).json()
    assert detail["status"] == "review_pending"
    assert detail["transcript"]["text"] == FAKE_TRANSCRIPT
    assert detail["state_suggestion"] == "active"  # open -> active suggested

    # Review: keep one (edited), drop one, add one manually (doc §9.1.4)
    review = (
        await client.get(
            f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token)
        )
    ).json()
    assert len(review["items"]) == 2
    keep, drop = review["items"]
    resp = await client.post(
        f"/api/v1/meetings/{meeting['id']}/review/confirm",
        headers=auth(token),
        json={
            "items": [
                {"id": keep["id"], "title": "Send IBC proposal TODAY", "keep": True},
                {"id": drop["id"], "title": drop["title"], "keep": False},
                {"id": None, "title": "Call the trustee", "keep": True},
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json()["action_items_saved"] == 2

    items = (
        await client.get(
            "/api/v1/action-items?status=open&owner=me", headers=auth(token)
        )
    ).json()
    titles = {i["title"] for i in items}
    assert "Send IBC proposal TODAY" in titles
    assert "Call the trustee" in titles
    assert drop["title"] not in titles

    # Lead state suggestion recorded on the lead; human confirms via endpoint.
    lead_detail = (
        await client.get(f"/api/v1/leads/{lead['id']}", headers=auth(token))
    ).json()
    assert lead_detail["suggested_state"] == "active"
    resp = await client.patch(
        f"/api/v1/leads/{lead['id']}/state",
        headers=auth(token),
        json={"state": "active", "reason": "Confirmed suggestion"},
    )
    assert resp.json()["state"] == "active"


async def test_due_dates_land_in_the_column_not_the_description(
    client, org_a, fake_ai, stub_planner
):
    """F8: the digest, My Tasks grouping and the nudge ladder all read
    `due_date`. A deadline the client actually said must reach that column."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Due Date Co"})
    ).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-due")

    review = (
        await client.get(f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token))
    ).json()
    shown = {i["title"]: (i["description"] or "") for i in review["items"]}
    assert "(due:" not in shown["Send IBC proposal"], \
        "a resolved date must not ALSO be jammed into the description"
    # An unresolvable hint is not silently dropped, and never becomes a guess.
    assert "when the hall is free" in shown["Share demo dates"]

    await client.post(
        f"/api/v1/meetings/{meeting['id']}/review/confirm",
        headers=auth(token),
        json={"items": [{"id": i["id"], "title": i["title"],
                         "description": i["description"], "keep": True}
                        for i in review["items"]]},
    )
    items = (
        await client.get("/api/v1/action-items?owner=me", headers=auth(token))
    ).json()
    by_title = {i["title"]: i for i in items}

    dated = by_title["Send IBC proposal"]
    assert dated["due_date"] is not None, "a resolved deadline must reach due_date"
    assert dated["due_date"].startswith(FAKE_DUE.strftime("%Y-%m-%d"))
    assert by_title["Share demo dates"]["due_date"] is None


async def test_the_meeting_screen_gets_each_items_due_date(
    client, org_a, fake_ai, stub_planner
):
    """Reported 19 Sep 2026: "action items missed meeting dates". Extraction
    had resolved the date all along — `GET /meetings/{id}` simply did not
    carry it, so the screen could only list titles."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Dated Screen Co"})
    ).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-screen")

    detail = (
        await client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth(token))
    ).json()
    by_title = {i["title"]: i for i in detail["action_items"]}
    assert by_title, detail
    dated = by_title["Send IBC proposal"]
    assert dated["due_date"] is not None, "the screen needs the date to show it"
    assert dated["due_date"].startswith(FAKE_DUE.strftime("%Y-%m-%d"))
    # An item nobody gave a deadline for says so rather than inventing one.
    assert by_title["Share demo dates"]["due_date"] is None


async def test_review_confirm_starts_the_planner(client, org_a, fake_ai, stub_planner):
    """F9: recording a meeting must start the same machine typing the notes
    starts. The human confirms what was heard; the Planner then plans AROUND
    the confirmed to-dos rather than producing a rival list."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Planner Start Co"})
    ).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-p1")

    # Nothing planned yet — the human has not confirmed anything.
    assert (await client.get("/api/v1/projects", headers=auth(token))).json() == [] \
        or all(p["lead_id"] != lead["id"]
               for p in (await client.get("/api/v1/projects",
                                          headers=auth(token))).json())

    review = (
        await client.get(f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token))
    ).json()
    resp = await client.post(
        f"/api/v1/meetings/{meeting['id']}/review/confirm",
        headers=auth(token),
        json={"items": [{"id": i["id"], "title": i["title"], "keep": True}
                        for i in review["items"]]},
    )
    assert resp.status_code == 200
    assert resp.json()["planning"] is True, "confirming must hand off to the Planner"

    # Workers are off in tests: run the queued job the way the queue would.
    result = await pipelines.plan_meeting(
        {"meeting_id": meeting["id"], "agreed_tasks": [
            {"title": i["title"], "description": None, "due_date": None}
            for i in review["items"]
        ]},
        "job-p2",
    )
    assert result["action"] == "project_proposed", result

    projects = [p for p in (await client.get("/api/v1/projects", headers=auth(token))).json()
                if p["lead_id"] == lead["id"]]
    assert len(projects) == 1, "a recorded meeting now births a project"
    detail = (
        await client.get(f"/api/v1/projects/{projects[0]['id']}", headers=auth(token))
    ).json()
    titles = {t["title"] for t in detail["tasks"]}
    # Every confirmed to-do is carried into the plan, exactly once.
    for item in review["items"]:
        assert item["title"] in titles, f"{item['title']} was dropped by the Planner"
    assert len(titles) > len(review["items"]), "the Planner adds work of its own too"
    assert all(t["due_date"] for t in detail["tasks"]), "plan tasks are dated"


async def test_plan_tasks_never_appear_in_the_meeting_review_gate(
    client, org_a, fake_ai, stub_planner
):
    """A plan version's tasks are also created pending_review and also carry
    the meeting id — but they belong to the plan and go live through
    activate_plan. Offering them here would let a confirm flip them open
    behind the plan's back, or cancel them as 'not echoed back'."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Review Gate Co"})
    ).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-g1")
    review = (
        await client.get(f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token))
    ).json()
    extracted_ids = {i["id"] for i in review["items"]}
    await client.post(
        f"/api/v1/meetings/{meeting['id']}/review/confirm",
        headers=auth(token),
        json={"items": [{"id": i["id"], "title": i["title"], "keep": True}
                        for i in review["items"]]},
    )
    await pipelines.plan_meeting({"meeting_id": meeting["id"], "agreed_tasks": []}, "job-g2")

    again = (
        await client.get(f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token))
    ).json()
    assert {i["id"] for i in again["items"]} <= extracted_ids, \
        "plan-owned tasks leaked into the meeting review gate"


async def test_second_recording_merges_instead_of_forking_a_project(
    client, org_a, fake_ai, stub_planner, monkeypatch
):
    """A recording carries no project id, so without resolution every one of
    them would look like a first meeting and fork another project."""
    from app.engines import planner_engine

    token = org_a["admin_token"]
    # Named from words the transcript actually uses: on the stub provider the
    # "wrong project" guard is a word-overlap check, and a lead nobody in the
    # transcript names would (correctly, for a stub) be held for a human.
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Proposal Program Co"})
    ).json()
    first = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": first["id"]}, "job-m1")
    await pipelines.plan_meeting({"meeting_id": first["id"], "agreed_tasks": []}, "job-m2")

    # The routing decision is the model's (exercised on its own below); here
    # it is fixed so the MERGE is what gets tested.
    from app.models.project import Project
    from sqlalchemy import select as _select

    async def resolve_to_the_live_project(db, *, org_id, lead_id, text):
        return (
            await db.execute(_select(Project).where(Project.lead_id == lead_id))
        ).scalars().first()

    monkeypatch.setattr(
        planner_engine, "_resolve_meeting_project", resolve_to_the_live_project
    )

    second = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": second["id"]}, "job-m3")
    result = await pipelines.plan_meeting(
        {"meeting_id": second["id"], "agreed_tasks": [
            {"title": "Confirm the venue", "description": None, "due_date": None}
        ]},
        "job-m4",
    )
    assert result["action"] == "plan_merged", result
    projects = [p for p in (await client.get("/api/v1/projects", headers=auth(token))).json()
                if p["lead_id"] == lead["id"]]
    assert len(projects) == 1, "the second recording forked a duplicate project"
    detail = (
        await client.get(f"/api/v1/projects/{projects[0]['id']}", headers=auth(token))
    ).json()
    assert "Confirm the venue" in {t["title"] for t in detail["tasks"]}


async def test_meeting_project_routing_is_the_models_call(client, org_a, monkeypatch):
    """Which engagement a project-less meeting belongs to is a judgement, not
    a row count: "another meeting on the ongoing work" and "a new engagement
    with an old client" look identical from the project list alone. The engine
    must obey the model — including its "none of these" answer, which is what
    keeps a genuinely new engagement from being swallowed into an old plan
    (the dry-run suite's W30)."""
    from app.ai import planning
    from app.engines import planner_engine

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Routing Judgement Co"})
    ).json()
    org_id = (await client.get("/api/v1/auth/me", headers=auth(token))).json()["org_id"]

    from app.database import SessionLocal
    from app.models.project import Project

    async with SessionLocal() as db:
        project = Project(org_id=org_id, lead_id=lead["id"], name="Ongoing work",
                          status="planning")
        db.add(project)
        await db.commit()
        project_id = project.id

    async def resolve(matcher, available=True):
        monkeypatch.setattr(planner_engine.nlu, "llm_available", lambda: available)
        if matcher is not None:
            monkeypatch.setattr(planning, "match_message_project", matcher)
        async with SessionLocal() as db:
            return await planner_engine._resolve_meeting_project(
                db, org_id=org_id, lead_id=lead["id"], text="we met again"
            )

    async def match(*, org_id, text, projects, source_kind="message"):
        return [projects[0].id]

    async def no_match(*, org_id, text, projects, source_kind="message"):
        return []

    picked = await resolve(match)
    assert picked is not None and picked.id == project_id, "a match must merge"

    assert await resolve(no_match) is None, \
        "'none of these' must open a new project, not swallow new work"

    assert await resolve(None, available=False) is None, \
        "the stub provider cannot make this call and must not guess"


async def test_confirmed_todo_duplicates_are_dropped_but_new_work_is_kept():
    """The deterministic fence behind F9: a weaker model sometimes carries a
    confirmed to-do verbatim AND invents a near-twin. Only the twin is dropped
    — the verbatim carry and every genuinely new task survive, and two truly
    different tasks (schedule vs confirm) are never collapsed."""
    from app.engines.planner_engine import _drop_duplicates_of_confirmed

    specs = [
        {"title": "Provide safety compliance documentation"},  # verbatim carry
        {"title": "Prepare safety compliance documentation"},  # model's near-twin
        {"title": "Send full proposal with commercials"},      # verbatim carry
        {"title": "Confirm participant numbers for pricing"},  # genuine new work
    ]
    agreed = [
        {"title": "Provide safety compliance documentation"},
        {"title": "Send full proposal with commercials"},
    ]
    kept = {s["title"] for s in _drop_duplicates_of_confirmed(specs, agreed)}
    assert "Prepare safety compliance documentation" not in kept
    assert "Provide safety compliance documentation" in kept
    assert "Confirm participant numbers for pricing" in kept
    assert "Send full proposal with commercials" in kept

    # Distinct verbs on the same object are distinct tasks — never merged.
    distinct = _drop_duplicates_of_confirmed(
        [{"title": "Schedule the demo"}, {"title": "Confirm the demo"}],
        [{"title": "Schedule the demo"}],
    )
    assert {"Schedule the demo", "Confirm the demo"} == {s["title"] for s in distinct}

    # Nothing confirmed → nothing touched.
    assert len(_drop_duplicates_of_confirmed(specs, None)) == len(specs)
    assert len(_drop_duplicates_of_confirmed(specs, [])) == len(specs)


async def test_adoption_claims_the_confirmed_row_but_never_a_different_task():
    """F22's fence, both directions.

    A plan task that IS a confirmed to-do must adopt that row; a plan task that
    merely resembles one must not. Each existing row can be claimed once, so two
    plan tasks can never collapse onto a single row."""
    from app.engines.planner_engine import _adoption_match

    class Row:
        def __init__(self, rid, title):
            self.id, self.title = rid, title

    rows = [
        Row("r1", "Provide safety compliance documentation and quote"),
        Row("r2", "Schedule the demo"),
    ]
    taken: set[str] = set()

    # Reworded but the same work — the tightest real pair seen in the live DB
    # ("Send revised schedule by Monday" vs "... to client") scores 0.75.
    hit = _adoption_match("Provide safety compliance documentation and quote",
                          rows, taken)
    assert hit is not None and hit.id == "r1"
    taken.add(hit.id)

    # r1 is claimed: a second plan task must NOT collapse onto it.
    assert _adoption_match("Provide safety compliance documentation and quote",
                           rows, taken) is None

    # Same object, different verb — distinct work, never adopted (0.67 < 0.7).
    assert _adoption_match("Confirm the demo", rows, set()) is None
    # Genuinely new work matches nothing.
    assert _adoption_match("Book the training venue", rows, set()) is None
    # Nothing to adopt is not an error.
    assert _adoption_match("Anything", [], set()) is None


async def test_confirmed_todos_are_adopted_by_the_plan_not_duplicated(
    client, org_a, fake_ai, stub_planner
):
    """F22: a confirmed review-gate to-do and the Planner's carry of it are the
    SAME work. Before the fix both were written as rows.

    The assertion here is deliberately scoped the way the bug demanded: EVERY
    live row for the lead, queried by lead_id with no other filter. The
    regression shipped on 2026-07-22 survived 50/50 pytest, 43/43 dryrun and a
    22/22 live script because "no duplicates" was asserted over
    `project["tasks"]` — the one collection the new code produces — while the
    duplicate lived between the plan and the project-less review-gate rows.
    """
    from sqlalchemy import select

    from app.core.constants import ActionItemStatus
    from app.database import SessionLocal
    from app.engines.planner_engine import _title_similarity
    from app.models.action_item import ActionItem

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Adoption Co"})
    ).json()
    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-f22a")

    review = (
        await client.get(f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token))
    ).json()
    confirmed = review["items"]
    assert confirmed, "the fixture must produce something to confirm"

    await client.post(
        f"/api/v1/meetings/{meeting['id']}/review/confirm",
        headers=auth(token),
        json={"items": [{"id": i["id"], "title": i["title"],
                         "description": i["description"], "keep": True}
                        for i in confirmed]},
    )
    # Row identity and the human's date, captured BEFORE the Planner runs.
    async with SessionLocal() as db:
        before = {
            r.id: (r.title, r.due_date)
            for r in (await db.execute(
                select(ActionItem).where(ActionItem.meeting_id == meeting["id"])
            )).scalars().all()
        }

    await pipelines.plan_meeting(
        {"meeting_id": meeting["id"], "agreed_tasks": [
            {"title": i["title"], "description": i["description"], "due_date": None}
            for i in confirmed
        ]},
        "job-f22b",
    )

    # EVERYTHING the user would see for this lead — no project filter, no
    # status filter beyond "still alive".
    async with SessionLocal() as db:
        live = (await db.execute(
            select(ActionItem).where(
                ActionItem.lead_id == lead["id"],
                ActionItem.status.notin_([ActionItemStatus.CANCELLED.value,
                                          ActionItemStatus.SUPERSEDED.value]),
            )
        )).scalars().all()

    pairs = [
        (a.title, b.title)
        for i, a in enumerate(live)
        for b in live[i + 1:]
        if _title_similarity(a.title, b.title) >= 0.7
    ]
    assert not pairs, f"the same work is stored twice for this lead: {pairs}"

    # Adopted, not re-created: the row the human confirmed still exists, under
    # its original id, and now belongs to the plan.
    adopted = [r for r in live if r.id in before]
    assert adopted, "the confirmed rows were replaced instead of adopted"
    for row in adopted:
        original_title, original_due = before[row.id]
        assert row.title == original_title, "adoption overwrote the human's wording"
        if original_due is not None:
            assert row.due_date == original_due, "adoption overwrote the human's date"
    assert any(r.plan_version_added is not None and r.project_id for r in adopted), \
        "no confirmed row was taken into the plan at all"


async def test_auto_save_when_review_switched_off(client, org_a, fake_ai, stub_planner):
    token = org_a["admin_token"]
    # Flip the org switch off
    resp = await client.patch(
        "/api/v1/admin/settings",
        headers=auth(token),
        json={"require_action_item_review": False},
    )
    assert resp.status_code == 200
    try:
        lead = (
            await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Autosave School"})
        ).json()
        meeting = await _upload_meeting(client, token, lead["id"])
        result = await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job2")
        assert result["review_required"] is False
        detail = (
            await client.get(
                f"/api/v1/meetings/{meeting['id']}", headers=auth(token)
            )
        ).json()
        assert detail["status"] == "completed"
        assert all(i["status"] == "open" for i in detail["action_items"])
    finally:
        await client.patch(
            "/api/v1/admin/settings",
            headers=auth(token),
            json={"require_action_item_review": True},
        )


async def test_review_flags_a_possible_duplicate_of_an_existing_task(client, org_a, fake_ai):
    """F24: a commitment restated in a later meeting must be flagged at the gate
    against the lead's existing open task, so the human can drop the twin —
    while genuinely new work is left unflagged. Advisory only; decides nothing."""
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Repeat Promise School"})
    ).json()
    # A task the lead already has (here created directly; in life, from an
    # earlier meeting). Same title the next meeting will re-extract.
    existing = (
        await client.post("/api/v1/action-items", headers=auth(token),
                          json={"title": "Send IBC proposal", "lead_id": lead["id"]})
    ).json()

    meeting = await _upload_meeting(client, token, lead["id"])
    await pipelines.process_meeting({"meeting_id": meeting["id"]}, "job-f24")

    review = (
        await client.get(f"/api/v1/meetings/{meeting['id']}/review", headers=auth(token))
    ).json()
    by_title = {i["title"]: i for i in review["items"]}

    # The restated commitment is flagged against the pre-existing task...
    dup = by_title["Send IBC proposal"]["possible_duplicate_of"]
    assert dup and dup["id"] == existing["id"], review["items"]
    assert dup["title"] == "Send IBC proposal"
    # ...while genuinely new work carries no warning.
    assert by_title["Share demo dates"]["possible_duplicate_of"] is None, review["items"]


# ─────────────────────────────────────────────────────────────────────────────
# Finding F40 — the consent record attached to a meeting stated a method that
# never happened.
#
# The app asks how consent was obtained (verbal / written / in app) plus a note,
# and stores it honestly against the lead. The upload endpoint then IGNORED that
# and wrote a second, contradictory record with method="in_app" and
# note="Confirmed at upload" hardcoded — and that fabricated row is the one
# linked to the meeting. Device-observed: the user chose "verbal" with the note
# "Principal Nair and team agreed verbally"; the meeting's record said "in_app".
#
# Data Model §3.5 breaks twice: `method` is "how consent was captured", and rows
# are "captured BEFORE the recording started" and "never edited". Tapping Upload
# is not a consent interaction.
#
# The second gap: `consent_confirmed` was a self-asserted caller flag the API
# trusted while manufacturing the evidence for it, so any direct call with
# consent_confirmed=true produced a complete-looking consent trail for a
# recording nobody ever consented to.
# ─────────────────────────────────────────────────────────────────────────────


async def test_the_meetings_consent_record_is_the_one_the_human_captured(client, org_a):
    """The method the user chose must survive to the meeting-linked record."""
    from app.database import SessionLocal
    from app.models.lead import ConsentRecord
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F40 Consent School"})
    ).json()
    await open_lead(client, token, lead["id"])
    resp = await client.post(
        f"/api/v1/leads/{lead['id']}/consent", headers=auth(token),
        json={"method": "verbal", "note": "Principal Nair and team agreed verbally"},
    )
    assert resp.status_code == 200, resp.text

    meeting = (
        await client.post(
            "/api/v1/meetings/upload", headers=auth(token),
            data={"lead_id": lead["id"], "consent_confirmed": "true"},
            files={"file": ("m.mp3", b"audio", "audio/mpeg")},
        )
    ).json()

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ConsentRecord).where(ConsentRecord.lead_id == lead["id"])
            )
        ).scalars().all()

    assert len(rows) == 1, (
        f"F40: upload wrote a SECOND consent record instead of using the one the "
        f"human captured — {[(r.method, r.note) for r in rows]}"
    )
    linked = rows[0]
    assert linked.meeting_id == meeting["id"], "the consent proof is not linked to its meeting"
    assert linked.method == "verbal", (
        f"the meeting's consent record claims a capture method that never "
        f"happened: {linked.method!r}"
    )
    assert "verbally" in (linked.note or ""), linked.note


async def test_an_upload_with_no_captured_consent_is_refused(client, org_a):
    """F40's second gap: the API used to trust the flag AND generate its evidence.

    `consent_confirmed=true` alone must no longer be enough — otherwise a direct
    API call manufactures a complete consent trail for a recording nobody agreed
    to.
    """
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F40 Unconsented School"})
    ).json()
    resp = await client.post(
        "/api/v1/meetings/upload", headers=auth(token),
        data={"lead_id": lead["id"], "consent_confirmed": "true"},
        files={"file": ("m.mp3", b"audio", "audio/mpeg")},
    )
    assert resp.status_code == 422, (
        f"an upload asserting consent, with no consent ever captured, was "
        f"accepted — got {resp.status_code}"
    )
    assert "consent" in resp.text.lower()

    from app.database import SessionLocal
    from app.models.lead import ConsentRecord
    from sqlalchemy import select

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ConsentRecord).where(ConsentRecord.lead_id == lead["id"])
            )
        ).scalars().all()
    assert rows == [], "the refusal still manufactured a consent record"


async def test_a_stale_consent_record_does_not_get_attached(client, org_a):
    """A proof that does not belong to the thing it proves is the same defect.

    Linking "the most recent unlinked consent" without a window would attach a
    months-old row to today's recording.
    """
    from datetime import timedelta

    from app.database import SessionLocal
    from app.models.base import utcnow
    from app.models.lead import ConsentRecord
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "F40 Stale School"})
    ).json()
    async with SessionLocal() as db:
        db.add(ConsentRecord(
            org_id=org_a["id"], lead_id=lead["id"], method="verbal",
            note="Agreed months ago, for a different recording",
            captured_at=utcnow() - timedelta(days=90),
        ))
        await db.commit()

    resp = await client.post(
        "/api/v1/meetings/upload", headers=auth(token),
        data={"lead_id": lead["id"], "consent_confirmed": "true"},
        files={"file": ("m.mp3", b"audio", "audio/mpeg")},
    )
    assert resp.status_code == 422, (
        "a 90-day-old consent record was accepted as proof for today's recording"
    )
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(ConsentRecord).where(ConsentRecord.lead_id == lead["id"])
            )
        ).scalars().one()
    assert row.meeting_id is None, "the stale record was linked anyway"
