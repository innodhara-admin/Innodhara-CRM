"""A meeting path of its own, separate from demos (customer ask, 21 Sep 2026).

A meeting is not a demo: it has no demo team and anyone who can see the
client may arrange one. Scheduling it — from the app, from Jarvis (typed or
spoken), or because a recording contains an agreed meeting — records a
`ScheduledMeeting`, puts a task in the organiser's list with the date and
time, and drafts an invite email (to / cc / bcc, a body written from the
context, the Meet link, a calendar attachment) that waits in Approvals.

Rejecting that invite with a reason redrafts it from the reason — including
moving the meeting when the reason says so — and puts it back in Approvals.
Rejecting without a reason just closes it. Approving sends it.

The model is scripted wherever the code asks one; what these tests pin down is
what no model is trusted with: the records written, the recipients, the
calendar attachment, the approval loop, and the questions Jarvis asks.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.ai import llm as llm_mod
from app.ai import meeting_draft, orchestrator
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.database import SessionLocal
from app.models.action_item import ActionItem
from app.models.comms import Approval
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.scheduled_meeting import ScheduledMeeting
from app.services import email_service, meeting_invite_service
from tests.conftest import auth, create_org, login

API = "/api/v1"
WEDNESDAY = date(2026, 9, 23)


# ── reading a time and a date out of a short answer ──────────────────────

@pytest.mark.parametrize("said, expected", [
    ("4 pm", "16:00"), ("4pm", "16:00"), ("4:30 pm", "16:30"), ("4.30pm", "16:30"),
    ("16:00", "16:00"), ("9.30 am", "09:30"), ("11", "11:00"), ("at 11 am", "11:00"),
    ("3", "15:00"), ("noon", "12:00"), ("12 pm", "12:00"), ("12 am", "00:00"),
    ("half past ten", None), ("whenever", None), ("", None), ("25:00", None),
])
def test_a_time_is_read_from_a_short_answer(said, expected):
    assert meeting_draft.parse_time(said) == expected


@pytest.mark.parametrize("said, expected", [
    ("today", date(2026, 9, 23)), ("tomorrow", date(2026, 9, 24)),
    ("friday", date(2026, 9, 25)), ("on Friday", date(2026, 9, 25)),
    ("wednesday", date(2026, 9, 23)),  # today is Wednesday: the next one on or after
    ("27 september", date(2026, 9, 27)), ("27th", date(2026, 9, 27)),
    ("September 27", date(2026, 9, 27)), ("2026-10-02", date(2026, 10, 2)),
    ("5 sep", date(2027, 9, 5)),  # already past this year
    ("sometime soon", None), ("", None),
])
def test_a_date_is_read_from_a_short_answer(said, expected):
    assert meeting_draft.parse_date(said, today=WEDNESDAY) == expected


# ── fixtures ────────────────────────────────────────────────────────────

def _hex() -> str:
    return uuid.uuid4().hex[:8]


async def _add_user(client, org, name: str, role: str) -> dict:
    email = f"{name.split()[0].lower()}{_hex()}@{org['domain']}"
    created = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                                json={"email": email, "name": name, "role": role})
    assert created.status_code == 200, created.text
    token = (await login(client, email, created.json()["temp_password"]))["access_token"]
    return {"id": created.json()["id"], "token": token, "name": name, "email": email}


@pytest.fixture
async def org(client, super_token):
    slug = _hex()
    domain = f"meet{slug}-example.com"
    org = await create_org(client, super_token, name=f"Meet {slug}",
                           slug=f"meet-{slug}", domain=domain)
    org["domain"] = domain
    org["agent"] = await _add_user(client, org, "Rahul Verma", "sales_agent")
    async with SessionLocal() as db:
        lead = Lead(org_id=org["id"], name="ABC School", owner_id=org["agent"]["id"])
        db.add(lead)
        await db.flush()
        db.add(Contact(org_id=org["id"], lead_id=lead.id, name="Anita Rao",
                       email="anita@abc-school.example", is_primary=True))
        bare = Lead(org_id=org["id"], name="No Email Academy", owner_id=org["agent"]["id"])
        db.add(bare)
        await db.commit()
        org["lead_id"], org["bare_lead_id"] = lead.id, bare.id
    return org


@pytest.fixture(autouse=True)
def plain_bodies(monkeypatch):
    """The invite body is model-written; here it is a fixed text built from
    the facts it was given, so tests can see which facts reached it."""
    async def fake_body(*, facts, instruction=None, **_):
        text = f"Dear {facts.get('contact_name')}, meeting on {facts['when']}."
        if instruction:
            text += f" [{instruction}]"
        return text

    monkeypatch.setattr(meeting_invite_service, "_write_body", fake_body)


async def _schedule(client, org, **extra) -> dict:
    body = {"lead_id": org["lead_id"], "date": "2026-10-02", "time": "11:00",
            "purpose": "Walk through the pilot plan"}
    body.update(extra)
    resp = await client.post(f"{API}/scheduled-meetings",
                             headers=auth(org["agent"]["token"]), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _message(message_id: str) -> OutboundMessage:
    async with SessionLocal() as db:
        return (await db.execute(
            select(OutboundMessage).where(OutboundMessage.id == message_id)
        )).scalar_one()


async def _pending_approval_for(message_id: str) -> Approval | None:
    async with SessionLocal() as db:
        return (await db.execute(
            select(Approval).where(Approval.entity_type == "outbound_message",
                                   Approval.entity_id == message_id,
                                   Approval.status == "pending")
        )).scalars().first()


# ── scheduling ──────────────────────────────────────────────────────────

async def test_a_sales_agent_can_schedule_a_meeting(client, org):
    """Demos are for leads and the admin; a meeting is anyone's who sees the client."""
    out = await _schedule(client, org)
    assert out["client"] == "ABC School"
    assert (out["date"], out["time"], out["duration_minutes"]) == ("2026-10-02", "11:00", 30)
    assert out["status"] == "scheduled"
    assert out["invite"]["status"] == "pending_approval"


async def test_it_is_a_meeting_not_a_demo(client, org):
    from app.models.demo import Demo

    out = await _schedule(client, org)
    async with SessionLocal() as db:
        meeting = (await db.execute(
            select(ScheduledMeeting).where(ScheduledMeeting.id == out["id"])
        )).scalar_one()
        demos = (await db.execute(
            select(Demo).where(Demo.lead_id == org["lead_id"])
        )).scalars().all()
    assert meeting.organizer_id == org["agent"]["id"]
    assert demos == []


async def test_the_task_list_shows_it_with_date_and_time(client, org):
    out = await _schedule(client, org)
    async with SessionLocal() as db:
        task = (await db.execute(
            select(ActionItem).where(ActionItem.id == out["action_item_id"])
        )).scalar_one()
    assert task.assignee_id == org["agent"]["id"]
    assert task.lead_id == org["lead_id"]
    assert "ABC School" in task.title and "11:00" in task.title
    assert task.due_date.date() == date(2026, 10, 2)
    assert (task.due_date.hour, task.due_date.minute) == (11, 0)


async def test_the_invite_waits_in_approvals_with_to_cc_bcc(client, org):
    out = await _schedule(client, org, cc=["ravi@partner.example"],
                          bcc=["records@" + org["domain"]])
    message = await _message(out["invite"]["message_id"])
    assert message.kind == "meeting_invite"
    assert message.status == "pending_approval"
    assert message.to_address == "anita@abc-school.example"
    assert message.cc == ["ravi@partner.example"]
    assert message.bcc == ["records@" + org["domain"]]
    assert "Dear Anita Rao" in message.body
    assert await _pending_approval_for(message.id) is not None


async def test_the_invite_carries_the_calendar_event_and_meet_link(client, org):
    out = await _schedule(client, org, duration_minutes=45)
    message = await _message(out["invite"]["message_id"])
    ics = message.attachments[0]["ics_text"]
    assert f"UID:meeting-{out['id']}@" in ics
    assert "DTSTART;TZID=Asia/Kolkata:20261002T110000" in ics
    assert "DTEND;TZID=Asia/Kolkata:20261002T114500" in ics
    assert "meet.google.com" in ics
    html = message.attachments[0]["html_body"]
    assert "meet.google.com" in html and "Dear Anita Rao" in html


async def test_no_client_email_still_schedules_but_drafts_nothing(client, org):
    out = await _schedule(client, org, lead_id=org["bare_lead_id"])
    assert out["status"] == "scheduled"
    assert out["invite"] is None
    assert "no contact" in out["invite_note"].lower()


async def test_a_bad_time_is_refused(client, org):
    resp = await client.post(f"{API}/scheduled-meetings", headers=auth(org["agent"]["token"]),
                             json={"lead_id": org["lead_id"], "date": "2026-10-02",
                                   "time": "25:61"})
    assert resp.status_code == 422


async def test_meetings_are_listed_per_client(client, org):
    out = await _schedule(client, org)
    resp = await client.get(f"{API}/scheduled-meetings", headers=auth(org["agent"]["token"]),
                            params={"lead_id": org["lead_id"]})
    assert resp.status_code == 200, resp.text
    assert [m["id"] for m in resp.json()] == [out["id"]]


async def test_cancelling_drafts_a_cancellation(client, org):
    out = await _schedule(client, org)
    resp = await client.post(f"{API}/scheduled-meetings/{out['id']}/cancel",
                             headers=auth(org["agent"]["token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    message = await _message(resp.json()["invite"]["message_id"])
    assert "METHOD:CANCEL" in message.attachments[0]["ics_text"]


# ── bcc really is blind ──────────────────────────────────────────────────

def test_bcc_is_delivered_but_never_shown():
    payload = email_service.EmailPayload(
        sender_name="Rahul", sender_email="rahul@x.example", to_address="a@x.example",
        subject="Hi", body="Hello", cc=["c@x.example"], bcc=["hidden@x.example"],
    )
    assert email_service.recipients(payload) == ["a@x.example", "c@x.example",
                                                 "hidden@x.example"]
    mime = email_service._build_mime(payload)
    assert "hidden@x.example" not in mime.as_string()
    assert mime["Bcc"] is None


# ── reject with a reason → redraft → back in Approvals ──────────────────

async def _decide(client, org, approval_id: str, approve: bool, note: str | None):
    resp = await client.post(f"{API}/approvals/{approval_id}/decide",
                             headers=auth(org["admin_token"]),
                             json={"approve": approve, "note": note})
    assert resp.status_code == 200, resp.text


async def test_rejecting_with_a_reason_redrafts_and_moves_the_meeting(client, org, monkeypatch):
    async def fake_read(*, reason, **_):
        assert reason == "Make it 4 pm and copy Ravi"
        return {"time": "16:00", "add_cc": ["ravi@partner.example"]}

    monkeypatch.setattr(meeting_invite_service, "_read_rejection", fake_read)
    out = await _schedule(client, org)
    first = await _message(out["invite"]["message_id"])
    approval = await _pending_approval_for(first.id)

    await _decide(client, org, approval.id, False, "Make it 4 pm and copy Ravi")

    assert (await _message(first.id)).status == "rejected"
    async with SessionLocal() as db:
        meeting = (await db.execute(
            select(ScheduledMeeting).where(ScheduledMeeting.id == out["id"])
        )).scalar_one()
        redraft = (await db.execute(
            select(OutboundMessage).where(OutboundMessage.id == meeting.invite_message_id)
        )).scalar_one()
        task = (await db.execute(
            select(ActionItem).where(ActionItem.id == meeting.action_item_id)
        )).scalar_one()
    assert meeting.start_time == "16:00"
    assert redraft.id != first.id
    assert redraft.status == "pending_approval"
    assert redraft.cc == ["ravi@partner.example"]
    assert "[Make it 4 pm and copy Ravi]" in redraft.body
    # The first draft was never sent, so to the client this is still the
    # first invitation — not an "Updated: moved to" notice.
    assert redraft.subject.startswith("Meeting invitation:")
    # The attachment is rebuilt, not copied: new time, next SEQUENCE, new text.
    ics = redraft.attachments[0]["ics_text"]
    assert "DTSTART;TZID=Asia/Kolkata:20261002T160000" in ics
    assert "SEQUENCE:1" in ics
    assert "Make it 4 pm" in redraft.attachments[0]["html_body"]
    # The task follows the meeting.
    assert (task.due_date.hour, task.due_date.minute) == (16, 0)
    assert "16:00" in task.title
    assert await _pending_approval_for(redraft.id) is not None


async def test_rejecting_without_a_reason_just_closes_it(client, org):
    out = await _schedule(client, org)
    first = await _message(out["invite"]["message_id"])
    approval = await _pending_approval_for(first.id)

    await _decide(client, org, approval.id, False, None)

    async with SessionLocal() as db:
        invites = (await db.execute(
            select(OutboundMessage).where(OutboundMessage.org_id == org["id"],
                                          OutboundMessage.kind == "meeting_invite")
        )).scalars().all()
        meeting = (await db.execute(
            select(ScheduledMeeting).where(ScheduledMeeting.id == out["id"])
        )).scalar_one()
    assert [m.status for m in invites] == ["rejected"]
    assert meeting.invite_status == "rejected"


async def test_approving_sends_it(client, org):
    out = await _schedule(client, org)
    first = await _message(out["invite"]["message_id"])
    approval = await _pending_approval_for(first.id)
    await _decide(client, org, approval.id, True, None)
    assert (await _message(first.id)).status in ("queued", "sending", "sent")


# ── Jarvis: its own tool, and a follow-up question when something is missing

class FakeModelLayer:
    def __init__(self, script: list[LlmResponse]):
        self.script = list(script)
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return LlmResponse(text="Done.")
        return self.script.pop(0)

    async def generate_json(self, **kwargs):
        return llm_mod.extract_json((await self.generate(**kwargs)).text)


@pytest.fixture
def fake_model(monkeypatch):
    def _install(script: list[LlmResponse]) -> FakeModelLayer:
        fake = FakeModelLayer(script)
        for target in (agent_base, orchestrator, meeting_draft):
            monkeypatch.setattr(target, "get_model_layer", lambda: fake)
        return fake

    return _install


async def _say(client, token, text, session_id):
    resp = await client.post(f"{API}/assistant/command", headers=auth(token),
                             json={"text": text, "session_id": session_id})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _read(**fields) -> LlmResponse:
    return LlmResponse(text=json.dumps(fields))


def test_the_scheduling_agent_has_a_meeting_tool_apart_from_demos():
    from app.ai.agents.scheduling_agent import SchedulingAgent

    tools = {t.name: t for t in SchedulingAgent().tools()}
    assert {"schedule_meeting", "list_meetings", "cancel_meeting", "book_demo"} <= set(tools)
    assert "not a demo" in tools["schedule_meeting"].description.lower()
    assert "meeting" in orchestrator._ROUTER_PROMPT.split("- scheduling:")[1].split("- client:")[0]


async def test_jarvis_asks_for_the_time_then_schedules(client, org, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting",
                                         args={"client": "ABC School", "date": "2037-10-02"})]),
        LlmResponse(text="Prose the question must replace."),
    ])
    first = await _say(client, org["agent"]["token"],
                       "Schedule a meeting with ABC School on 2 October", session)
    assert "what time" in first["reply"].lower()
    async with SessionLocal() as db:
        assert (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all() == []

    fake_model([_read(about_this=True, time="16:00")])
    second = await _say(client, org["agent"]["token"], "4 in the evening", session)
    assert "ABC School" in second["reply"]
    assert "approvals" in second["reply"].lower()
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalar_one()
    assert (meeting.meeting_date, meeting.start_time) == (date(2037, 10, 2), "16:00")
    assert meeting.source == "jarvis"
    assert meeting.invite_message_id is not None


async def test_jarvis_understands_a_plain_time_without_the_model(client, org, fake_model):
    """If the reading model fails, a plain answer to the question asked still works."""
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting",
                                         args={"client": "ABC School", "date": "2037-10-02"})]),
        LlmResponse(text="x"),
    ])
    await _say(client, org["agent"]["token"], "meeting with ABC on 2 Oct", session)
    fake_model([LlmResponse(text="not json at all")])
    reply = await _say(client, org["agent"]["token"], "11:30 am", session)
    assert "ABC School" in reply["reply"]
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalar_one()
    assert meeting.start_time == "11:30"


async def test_jarvis_asks_for_the_day_when_only_the_client_is_given(client, org, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting",
                                         args={"client": "ABC School"})]),
        LlmResponse(text="x"),
    ])
    first = await _say(client, org["agent"]["token"], "set up a meeting with ABC School", session)
    assert "which day" in first["reply"].lower()
    fake_model([_read(about_this=True, date="2037-10-05", time="10:00")])
    second = await _say(client, org["agent"]["token"], "Monday the 5th at 10", session)
    assert "ABC School" in second["reply"]
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalar_one()
    assert (meeting.meeting_date, meeting.start_time) == (date(2037, 10, 5), "10:00")


async def test_cancelling_the_question_creates_nothing(client, org, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting",
                                         args={"client": "ABC School", "date": "2037-10-02"})]),
        LlmResponse(text="x"),
    ])
    await _say(client, org["agent"]["token"], "meeting with ABC on 2 Oct", session)
    fake_model([])
    reply = await _say(client, org["agent"]["token"], "cancel", session)
    assert "nothing" in reply["reply"].lower()
    async with SessionLocal() as db:
        assert (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all() == []


async def test_a_complete_request_schedules_in_one_turn(client, org, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting", args={
            "client": "ABC School", "date": "2037-10-02", "time": "15:00",
            "purpose": "budget review"})]),
        LlmResponse(text="Booked the meeting; the invite is waiting in Approvals."),
    ])
    await _say(client, org["agent"]["token"],
               "schedule a meeting with ABC School on 2 Oct at 3pm for the budget review",
               session)
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalar_one()
    assert meeting.start_time == "15:00"
    assert meeting.purpose == "budget review"


# ── a recording that agrees a meeting ────────────────────────────────────

async def test_an_agreed_meeting_in_a_recording_is_scheduled(client, org):
    from app.models.meeting import Meeting

    async with SessionLocal() as db:
        recording = Meeting(org_id=org["id"], lead_id=org["lead_id"],
                            agent_id=org["agent"]["id"], title="Visit")
        db.add(recording)
        await db.commit()
        rec_id = recording.id

    agreed = {"date": "2026-09-27", "time": "09:00", "duration_minutes": None,
              "purpose": "Review the pilot proposal with the principal"}
    for _ in range(2):  # a retried pipeline must not schedule it twice
        async with SessionLocal() as db:
            recording = (await db.execute(select(Meeting).where(Meeting.id == rec_id))).scalar_one()
            lead = (await db.execute(select(Lead).where(Lead.id == org["lead_id"]))).scalar_one()
            await meeting_invite_service.schedule_from_recording(
                db, recording=recording, lead=lead, agreed=agreed,
                task_status="pending_review", summary="They agreed to meet on Saturday.",
            )
            await db.commit()

    async with SessionLocal() as db:
        meetings = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all()
        assert len(meetings) == 1
        meeting = meetings[0]
        task = (await db.execute(
            select(ActionItem).where(ActionItem.id == meeting.action_item_id)
        )).scalar_one()
        invite = (await db.execute(
            select(OutboundMessage).where(OutboundMessage.id == meeting.invite_message_id)
        )).scalar_one()
    assert meeting.source == "recording" and meeting.recording_meeting_id == rec_id
    assert (meeting.meeting_date, meeting.start_time) == (date(2026, 9, 27), "09:00")
    assert task.status == "pending_review" and task.meeting_id == rec_id
    assert invite.kind == "meeting_invite" and invite.status == "pending_approval"


async def test_extraction_reads_an_agreed_meeting(monkeypatch):
    from app.ai import extraction

    fake = FakeModelLayer([LlmResponse(text=json.dumps({
        "action_items": [], "summary": "s", "real_discussion": True, "key_facts": [],
        "agreed_meeting": {"agreed": True, "date": "2026-09-27", "time": "9:00",
                           "duration_minutes": 45, "purpose": "Pilot review"},
    }))])
    monkeypatch.setattr(extraction, "get_model_layer", lambda: fake)
    analysis = await extraction.analyse_meeting("t", org_name="O", client_name="C")
    assert analysis.agreed_meeting == {"date": "2026-09-27", "time": "09:00",
                                       "duration_minutes": 45, "purpose": "Pilot review"}


async def test_no_agreement_or_no_date_is_no_meeting(monkeypatch):
    from app.ai import extraction

    for agreed in ({"agreed": False, "date": "2026-09-27"},
                   {"agreed": True, "date": None, "time": "10:00"}, None):
        fake = FakeModelLayer([LlmResponse(text=json.dumps({
            "action_items": [], "summary": "s", "real_discussion": True,
            "agreed_meeting": agreed}))])
        monkeypatch.setattr(extraction, "get_model_layer", lambda: fake)
        analysis = await extraction.analyse_meeting("t", org_name="O", client_name="C")
        assert analysis.agreed_meeting is None


async def test_the_meeting_pipeline_schedules_what_the_recording_agreed(client, org, monkeypatch):
    """End to end through the real pipeline (speech-to-text and extraction
    faked, as in test_meetings.py): the agreed meeting becomes a task in the
    review gate beside the others, a ScheduledMeeting, and an invite."""
    from app.ai import extraction as extraction_mod
    from app.ai import stt as stt_mod
    from app.jobs import pipelines
    from tests.test_meetings import _upload_meeting

    async def fake_transcribe(audio, mime, **_):
        return stt_mod.TranscriptionResult(text="We decided to meet on the 27th at 9am.",
                                           language="en", confidence=0.9)

    async def fake_analyse(transcript, **_):
        return extraction_mod.MeetingAnalysis(
            action_items=[{"title": "Send the fee sheet", "description": "",
                           "due_hint": None, "due_date": None}],
            summary="They agreed to meet on the 27th at 9am.", real_discussion=True,
            agreed_meeting={"date": "2026-09-27", "time": "09:00",
                            "duration_minutes": None, "purpose": "Pilot review"},
        )

    monkeypatch.setattr(pipelines.stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(pipelines.extraction, "analyse_meeting", fake_analyse)
    recording = await _upload_meeting(client, org["agent"]["token"], org["lead_id"])
    result = await pipelines.process_meeting({"meeting_id": recording["id"]}, "job-meet")
    assert result["action_items"] == 2  # the fee sheet, and the meeting

    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.recording_meeting_id == recording["id"]))).scalar_one()
        items = (await db.execute(select(ActionItem).where(
            ActionItem.meeting_id == recording["id"]))).scalars().all()
    assert (meeting.meeting_date, meeting.start_time) == (date(2026, 9, 27), "09:00")
    assert sorted(i.status for i in items) == ["pending_review", "pending_review"]
    assert any("09:00" in i.title for i in items)
    assert (await _message(meeting.invite_message_id)).kind == "meeting_invite"


# ── two clients with the same name (found in the live test, 23 Sep 2026) ──
# The live data holds two "Abc School" leads. The shared resolver asked
# "Several clients match: Abc School, Abc School. Which one?" — unanswerable —
# and the flow then asked "Which client?" forever.

@pytest.fixture
async def twins(client, org):
    async with SessionLocal() as db:
        other = await _add_user(client, org, "Priya Nair", "sales_agent")
        hyd = Lead(org_id=org["id"], name="Twin School", city="Hyd", owner_id=org["agent"]["id"])
        db.add(hyd)
        await db.flush()  # separately, so "first" and "second" are well defined
        blr = Lead(org_id=org["id"], name="Twin School", owner_id=other["id"])
        db.add(blr)
        await db.flush()
        db.add(Contact(org_id=org["id"], lead_id=blr.id, name="Kiran",
                       email="kiran@twin.example", is_primary=True))
        await db.commit()
        org["hyd"], org["blr"] = hyd.id, blr.id
    return org


def _ask_twin(**args):
    return [LlmResponse(text='{"agent": "scheduling"}'),
            LlmResponse(tool_calls=[ToolCall(name="schedule_meeting",
                                             args={"client": "Twin School", **args})]),
            LlmResponse(text="x")]


async def _only_meeting(org_id):
    async with SessionLocal() as db:
        return (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org_id))).scalar_one()


async def test_same_named_clients_are_told_apart_and_a_pick_keeps_the_day(client, twins, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model(_ask_twin(date="2037-10-02", time="11:00"))
    first = await _say(client, twins["agent"]["token"], "meeting with Twin School 2 Oct 11am", session)
    reply = first["reply"]
    assert "Twin School (Hyd, Rahul Verma's)" in reply
    assert "Twin School (Priya Nair's)" in reply
    assert first["actions"][-1]["candidates"] == ["Twin School (Hyd, Rahul Verma's)",
                                                  "Twin School (Priya Nair's)"]
    fake_model([_read(about_this=True)])  # the model finds no client name in it
    second = await _say(client, twins["agent"]["token"], "Priya's one", session)
    assert "Twin School" in second["reply"] and "approvals" in second["reply"].lower()
    meeting = await _only_meeting(twins["id"])
    assert meeting.lead_id == twins["blr"]
    assert (meeting.meeting_date, meeting.start_time) == (date(2037, 10, 2), "11:00")


@pytest.mark.parametrize("answer, which", [
    ("the Hyderabad one", "hyd"), ("Hyd", "hyd"), ("the second one", "blr"),
    ("first", "hyd"), ("2", "blr"), ("Twin School (Priya Nair's)", "blr"),
])
async def test_a_pick_can_be_worded_many_ways(client, twins, fake_model, answer, which):
    session = f"meet{uuid.uuid4().hex}"
    fake_model(_ask_twin(date="2037-10-02", time="11:00"))
    await _say(client, twins["agent"]["token"], "meeting with Twin School on 2 Oct at 11am", session)
    fake_model([LlmResponse(text="not json")])
    await _say(client, twins["agent"]["token"], answer, session)
    assert (await _only_meeting(twins["id"])).lead_id == twins[which]


async def test_an_answer_that_picks_neither_repeats_the_choice_and_keeps_the_day(client, twins, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model(_ask_twin(date="2037-10-02"))
    await _say(client, twins["agent"]["token"], "meeting with Twin School on 2 Oct", session)
    fake_model([_read(about_this=True, time="16:00")])
    again = await _say(client, twins["agent"]["token"], "at 4 in the evening", session)
    assert "Twin School (Hyd, Rahul Verma's)" in again["reply"]
    fake_model([_read(about_this=True)])
    await _say(client, twins["agent"]["token"], "Hyd", session)
    meeting = await _only_meeting(twins["id"])
    assert (meeting.lead_id, meeting.meeting_date, meeting.start_time) == (
        twins["hyd"], date(2037, 10, 2), "16:00")


# ── the model may not invent a day, a time, a length or a purpose ────────
# Live test, 23 Sep 2026: "Set up a meeting with Abc School" was booked for
# TODAY at 09:00, and "…October 3 ke din" got 09:00, both filled in by the
# model. A value now counts only when the person's words hold one.

@pytest.mark.parametrize("text, expected", [
    ("Set up a meeting with Abc School", set()),
    ("meeting with Abc School on 3 October", {"date"}),
    ("Abc School jothe meeting schedule maadi, October 3 ke din", {"date"}),
    ("meeting with Abc next Monday at 4 pm", {"date", "time"}),
    ("kal subah 10 baje Abc ke saath meeting", {"date", "time"}),
    ("naale sanje 5 gante Abc jothe meeting", {"date", "time"}),
    ("ಸೋಮವಾರ ಬೆಳಿಗ್ಗೆ Abc ಜೊತೆ ಮೀಟಿಂಗ್", {"date", "time"}),
    ("सोमवार शाम 4 बजे Abc के साथ मीटिंग", {"date", "time"}),
    ("meeting with Abc tomorrow at 11:30 for 45 minutes", {"date", "time", "duration_minutes"}),
])
def test_only_what_was_said_counts(text, expected):
    invented = {"client": "Abc School", "date": "2026-09-23", "time": "09:00",
                "duration_minutes": 60, "purpose": "Meeting with Abc School"}
    kept = meeting_draft.ground(invented, text)
    assert kept["client"] == "Abc School"
    assert {k for k in ("date", "time", "duration_minutes") if kept.get(k)} == expected
    assert not kept.get("purpose")


def test_a_purpose_in_the_persons_own_words_is_kept():
    kept = meeting_draft.ground({"purpose": "Go through the pilot plan"},
                                "meeting with Abc on 2 Oct to go through the pilot plan")
    assert kept["purpose"] == "Go through the pilot plan"


async def test_jarvis_asks_for_the_day_instead_of_inventing_one(client, org, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting", args={
            "client": "ABC School", "date": "2026-09-23", "time": "09:00",
            "purpose": "Meeting with ABC School"})]),
        LlmResponse(text="x"),
    ])
    first = await _say(client, org["agent"]["token"], "Set up a meeting with ABC School", session)
    assert "which day" in first["reply"].lower()
    async with SessionLocal() as db:
        assert (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all() == []


def test_the_invite_body_is_plain_text():
    """Live test, 23 Sep 2026: the model bolded the date with ** — shown
    literally in a plain-text email."""
    written = ("Hi Suresh,\n\nWe meet on **Friday, 02 October 2026 at 11:00** to "
               "__go through the plan__.\n\n**Join:** [Meet](https://meet.google.com/x)")
    assert meeting_invite_service.plain_text(written) == (
        "Hi Suresh,\n\nWe meet on Friday, 02 October 2026 at 11:00 to "
        "go through the plan.\n\nJoin: Meet: https://meet.google.com/x")


# ── found on the first real upload (Risabh Public School, 23 Sep 2026) ────

async def test_adding_a_contact_later_drafts_the_waiting_invite(client, org):
    """The recording scheduled the meeting before the lead had any contact,
    so the invite was skipped — and nothing ever drafted it afterwards."""
    out = await _schedule(client, org, lead_id=org["bare_lead_id"])
    assert out["invite"] is None
    resp = await client.post(
        f"{API}/leads/{org['bare_lead_id']}/contacts", headers=auth(org["admin_token"]),
        json={"name": "Ekaghni", "email": "ekaghni@no-email.example", "is_primary": True},
    )
    assert resp.status_code == 200, resp.text
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.id == out["id"]))).scalar_one()
    assert meeting.invite_status == "pending_approval"
    invite = await _message(meeting.invite_message_id)
    assert invite.to_address == "ekaghni@no-email.example"
    # Sent as the organiser, not as whoever typed the contact in.
    assert invite.sender_user_id == org["agent"]["id"]
    assert await _pending_approval_for(invite.id) is not None


async def test_a_contact_without_email_or_a_past_meeting_drafts_nothing(client, org):
    out = await _schedule(client, org, lead_id=org["bare_lead_id"], date="2020-01-06")
    await client.post(f"{API}/leads/{org['bare_lead_id']}/contacts",
                      headers=auth(org["admin_token"]), json={"name": "No Mail"})
    await client.post(f"{API}/leads/{org['bare_lead_id']}/contacts",
                      headers=auth(org["admin_token"]),
                      json={"name": "Late", "email": "late@x.example"})
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.id == out["id"]))).scalar_one()
    assert meeting.invite_status == "no_contact" and meeting.invite_message_id is None


async def test_the_agreed_meeting_is_not_listed_twice(client, org, monkeypatch):
    """The first real upload gave "Send calendar invite…" and "Attend follow-up
    meeting…" beside the pipeline's own meeting task. Only real to-dos stay."""
    from app.ai import extraction as extraction_mod
    from app.ai import stt as stt_mod
    from app.jobs import pipelines
    from tests.test_meetings import _upload_meeting

    async def fake_transcribe(audio, mime, **_):
        return stt_mod.TranscriptionResult(text="t", language="en", confidence=0.9)

    monday = datetime(2026, 9, 28)

    async def fake_analyse(transcript, **_):
        return extraction_mod.MeetingAnalysis(
            action_items=[
                {"title": "Send calendar invite with video link for Monday meeting",
                 "description": "", "due_date": monday},
                {"title": "Attend follow-up meeting with principal and coordinator",
                 "description": "", "due_date": monday},
                {"title": "Print the brochure for the meeting", "description": "",
                 "due_date": datetime(2026, 9, 26)},
                {"title": "Share references of schools running IBC", "description": "",
                 "due_date": datetime(2026, 9, 30)},
            ],
            summary="s", real_discussion=True,
            agreed_meeting={"date": "2026-09-28", "time": "10:30",
                            "duration_minutes": 45, "purpose": "Curriculum walk-through"},
        )

    monkeypatch.setattr(pipelines.stt, "transcribe", fake_transcribe)
    monkeypatch.setattr(pipelines.extraction, "analyse_meeting", fake_analyse)
    recording = await _upload_meeting(client, org["agent"]["token"], org["lead_id"])
    await pipelines.process_meeting({"meeting_id": recording["id"]}, "job-dup")
    async with SessionLocal() as db:
        titles = sorted(i.title for i in (await db.execute(select(ActionItem).where(
            ActionItem.meeting_id == recording["id"]))).scalars().all())
    assert titles == ["Meeting with ABC School on Mon 28 Sep at 10:30",
                      "Print the brochure for the meeting",
                      "Share references of schools running IBC"]


def test_extraction_no_longer_asks_for_the_meeting_as_a_to_do():
    from app.ai import extraction

    prompt = " ".join(extraction._PROMPT.lower().split())
    assert "also belongs in action_items" not in prompt
    assert "do not also list the agreed meeting" in prompt


async def test_the_planner_drops_invite_tasks_for_a_meeting_already_scheduled(client, org):
    """On confirm, the Planner added "Prepare calendar invite for follow-up
    meeting" and "Send calendar invite with video link to principal" for a
    meeting the recording had already scheduled (Risabh, 23 Sep 2026)."""
    from app.engines.planner_engine import _drop_scheduled_meeting_tasks
    from app.models.meeting import Meeting

    specs = [{"title": "Prepare calendar invite for follow-up meeting"},
             {"title": "Send calendar invite with video link to principal"},
             {"title": "Prepare IBC curriculum details and fee structure"},
             {"title": "Identify 2-3 school references"}]
    async with SessionLocal() as db:
        recording = Meeting(org_id=org["id"], lead_id=org["lead_id"],
                            agent_id=org["agent"]["id"], title="Visit")
        other = Meeting(org_id=org["id"], lead_id=org["lead_id"],
                        agent_id=org["agent"]["id"], title="Another")
        db.add_all([recording, other])
        await db.flush()
        db.add(ScheduledMeeting(org_id=org["id"], lead_id=org["lead_id"],
                                meeting_date=date(2026, 9, 28), start_time="10:30",
                                organizer_id=org["agent"]["id"], source="recording",
                                recording_meeting_id=recording.id))
        await db.flush()
        kept = await _drop_scheduled_meeting_tasks(db, org_id=org["id"], meeting=recording,
                                                   task_specs=specs)
        untouched = await _drop_scheduled_meeting_tasks(db, org_id=org["id"], meeting=other,
                                                        task_specs=specs)
    assert [s["title"] for s in kept] == ["Prepare IBC curriculum details and fee structure",
                                          "Identify 2-3 school references"]
    assert untouched == specs  # no meeting scheduled from that recording: nothing dropped


async def test_the_invite_writer_knows_who_it_is_writing_to(client, org, monkeypatch):
    """The first real invite said "a video call with the principal" to the
    principal. The writer now gets the reader's role and is told to write to
    them as "you"."""
    seen = {}

    async def spy(*, facts, **_):
        seen.update(facts)
        return "Dear Anita, see you."

    monkeypatch.setattr(meeting_invite_service, "_write_body", spy)
    async with SessionLocal() as db:
        contact = (await db.execute(select(Contact).where(
            Contact.lead_id == org["lead_id"]))).scalar_one()
        contact.title = "Principal"
        await db.commit()
    await _schedule(client, org)
    assert seen["contact_name"] == "Anita Rao" and seen["contact_role"] == "Principal"
    # The reader's own organisation is labelled as theirs, not as "the client".
    assert seen["reader_organisation"] == "ABC School" and "client" not in seen
    prompt = meeting_invite_service._BODY_SYSTEM.lower()
    assert "never describe the reader in the third person" in prompt


async def test_the_jarvis_card_opens_the_invites_approval(client, org, fake_model):
    """25 Sep 2026: "Open" on the scheduled-meeting card went to the recording
    screen ("transcribing"), because the result's bare "id" was read by the app
    as a recording's. The result now names the meeting plainly and carries the
    invite's approval, which is what the person wants to open."""
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting", args={
            "client": "ABC School", "date": "2037-10-02", "time": "10:30"})]),
        LlmResponse(text="Booked."),
    ])
    body = await _say(client, org["agent"]["token"],
                      "schedule a meeting with ABC School on 2 Oct at 10:30 am", session)
    result = next(a["result"] for a in body["actions"] if a.get("tool") == "schedule_meeting")
    assert "id" not in result
    async with SessionLocal() as db:
        meeting = (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalar_one()
    assert result["scheduled_meeting_id"] == meeting.id
    approval = await _pending_approval_for(meeting.invite_message_id)
    assert result["approval_id"] == approval.id


# ── clashes with the organiser's own meetings (25 Sep 2026) ──────────────
# Asked for a meeting at a time already taken, Jarvis booked it anyway.

async def test_the_api_refuses_a_clash_and_says_when_it_is_free(client, org):
    await _schedule(client, org, time="10:30")  # 30 minutes: 10:30 to 11:00
    resp = await client.post(f"{API}/scheduled-meetings", headers=auth(org["agent"]["token"]),
                             json={"lead_id": org["lead_id"], "date": "2026-10-02",
                                   "time": "10:45"})
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "You already have a meeting with ABC School" in detail
    assert "from 10:30 to 11:00" in detail and "from 11:00 onwards" in detail


async def test_back_to_back_and_other_peoples_meetings_are_fine(client, org):
    await _schedule(client, org, time="10:30")
    await _schedule(client, org, time="11:00")  # starts as the first one ends
    resp = await client.post(f"{API}/scheduled-meetings", headers=auth(org["admin_token"]),
                             json={"lead_id": org["lead_id"], "date": "2026-10-02",
                                   "time": "10:30"})  # someone else's diary
    assert resp.status_code == 200, resp.text


async def test_a_cancelled_meeting_frees_its_time(client, org):
    first = await _schedule(client, org, time="10:30")
    await client.post(f"{API}/scheduled-meetings/{first['id']}/cancel",
                      headers=auth(org["agent"]["token"]))
    await _schedule(client, org, time="10:30")


async def test_jarvis_says_the_time_is_taken_and_asks_again(client, org, fake_model):
    await _schedule(client, org, time="10:30", date="2037-10-02")
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting", args={
            "client": "ABC School", "date": "2037-10-02", "time": "10:30"})]),
        LlmResponse(text="x"),
    ])
    first = await _say(client, org["agent"]["token"],
                       "schedule a meeting with ABC School on 2 Oct at 10:30 am", session)
    assert "You already have a meeting with ABC School" in first["reply"]
    assert "from 10:30 to 11:00" in first["reply"]
    assert "what time" in first["reply"].lower()
    async with SessionLocal() as db:
        assert len((await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all()) == 1

    fake_model([_read(about_this=True, time="11:15")])
    second = await _say(client, org["agent"]["token"], "11:15 am", session)
    assert "11:15" in second["reply"]
    async with SessionLocal() as db:
        times = sorted(m.start_time for m in (await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all())
    assert times == ["10:30", "11:15"]


async def test_a_second_clash_is_caught_too(client, org, fake_model):
    await _schedule(client, org, time="10:30", date="2037-10-02")
    await _schedule(client, org, time="11:00", date="2037-10-02")
    session = f"meet{uuid.uuid4().hex}"
    fake_model([
        LlmResponse(text='{"agent": "scheduling"}'),
        LlmResponse(tool_calls=[ToolCall(name="schedule_meeting", args={
            "client": "ABC School", "date": "2037-10-02", "time": "10:30"})]),
        LlmResponse(text="x"),
    ])
    await _say(client, org["agent"]["token"], "meeting with ABC School 2 Oct 10:30 am", session)
    fake_model([_read(about_this=True, time="11:00")])
    again = await _say(client, org["agent"]["token"], "11 am", session)
    assert "from 11:00 to 11:30" in again["reply"]


# ── picking between same-named clients, the loop (26 Sep 2026) ────────────
# "owned by Shiva" (Siva as speech recognition spells it) matched neither
# option; the model's reading "Twin School owned by Shiva" was then looked up
# by name, found both, and the same question came back for ever.

def test_a_near_spelling_of_the_owner_picks_the_client():
    options = [{"id": "a", "label": "Abc School (Hyd, Siva's)", "name": "Abc School",
                "words": ["hyd", "siva"]},
               {"id": "b", "label": "Abc School (Priya Nair's)", "name": "Abc School",
                "words": ["priya", "nair"]}]
    assert meeting_draft.pick_option(options, "owned by Shiva")["id"] == "a"
    assert meeting_draft.pick_option(options, "the one owned by Siva")["id"] == "a"
    assert meeting_draft.pick_option(options, "Priya Nair wala")["id"] == "b"
    assert meeting_draft.pick_option(options, "the Mumbai one") is None


async def test_the_models_reading_picks_instead_of_searching_again(client, twins, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model(_ask_twin(date="2037-10-02", time="11:00"))
    await _say(client, twins["agent"]["token"], "meeting with Twin School on 2 Oct at 11am", session)
    fake_model([_read(about_this=True, client="Twin School owned by Raahul")])
    body = await _say(client, twins["agent"]["token"], "the one owned by Raahul ji", session)
    assert "Done" in body["reply"], body["reply"]
    assert (await _only_meeting(twins["id"])).lead_id == twins["hyd"]


async def test_an_answer_that_fits_neither_says_so_and_numbers_the_choices(client, twins, fake_model):
    session = f"meet{uuid.uuid4().hex}"
    fake_model(_ask_twin(date="2037-10-02", time="11:00"))
    await _say(client, twins["agent"]["token"], "meeting with Twin School on 2 Oct at 11am", session)
    fake_model([_read(about_this=True, client="Twin School")])
    body = await _say(client, twins["agent"]["token"], "the Mumbai one", session)
    assert body["reply"].startswith("Sorry, I couldn't tell which one.")
    assert "1. Twin School (Hyd, Rahul Verma's)" in body["reply"]
    assert "2. Twin School (Priya Nair's)" in body["reply"]
    fake_model([LlmResponse(text="not json")])
    await _say(client, twins["agent"]["token"], "2", session)
    assert (await _only_meeting(twins["id"])).lead_id == twins["blr"]
