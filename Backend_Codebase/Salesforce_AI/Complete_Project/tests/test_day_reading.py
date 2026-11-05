"""Which day and time a person means (2 Oct 2026).

Measured with the real models: "Schedule a meeting with X next Saturday at
11 am", said on Friday 2 October, was booked for Saturday 3 October in three
runs out of four. The fast agent model passed the person's words instead of
a date, and the code that read them dropped "next". The strong model, given
today's date, weekday and time, read 26 of 28 kinds of phrase right every
time; the two it got wrong were dates in the past.

Now the strong model reads the day and time from the person's own words; a
date before now is never booked; and "next <weekday>", which people use for
two different days, is always asked about ("Saturday 3 October or Saturday
10 October?") -- by Jarvis in a chat, and on the review and approval of a
meeting a recording agreed, where nobody can be asked.

The strong model is scripted here (conftest gives every other test no
reading at all, which is what an unavailable model gives).
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.ai import day_reading, extraction, meeting_draft
from app.ai.day_reading import When, read_when as REAL_READ_WHEN
from app.ai.llm import LlmResponse, ToolCall
from app.core import clock
from app.database import SessionLocal
from app.models.action_item import ActionItem
from app.models.comms import Approval
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from app.models.scheduled_meeting import ScheduledMeeting
from app.services import meeting_invite_service
from tests.test_scheduled_meetings import (  # noqa: F401 -- fixtures
    _read, _say, fake_model, org, plain_bodies,
)

IST = ZoneInfo("Asia/Kolkata")
FRI = date(2026, 10, 2)
TUE = date(2026, 9, 29)


# ── "next <weekday>" has two readings ────────────────────────────────────

@pytest.mark.parametrize("said, today, expected", [
    ("next Saturday", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("schedule a meeting with Abc School next Saturday at 11 am", FRI,
     [date(2026, 10, 3), date(2026, 10, 10)]),
    ("next sat", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("agle Shanivar 11 baje", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("agle shaniwaar ko", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("mundina Shanivara 11 gantege", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("अगले शनिवार", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("ಮುಂದಿನ ಶನಿವಾರ", FRI, [date(2026, 10, 3), date(2026, 10, 10)]),
    ("next Friday", FRI, [date(2026, 10, 9), date(2026, 10, 16)]),  # said on a Friday
    ("next Thursday", TUE, [date(2026, 10, 1), date(2026, 10, 8)]),
    ("next Friday at 11", date(2026, 12, 26), [date(2027, 1, 1), date(2027, 1, 8)]),
])
def test_next_weekday_gives_the_coming_one_and_the_one_after(said, today, expected):
    assert day_reading.next_weekday_options(said, today) == expected


@pytest.mark.parametrize("said", [
    "this Saturday", "coming Saturday", "Saturday", "on Saturday at 4 pm",
    "next week Tuesday", "next week", "tomorrow", "next month",
    # The date settles it (Risabh Public School's recording, 23 Sep 2026).
    "by next Wednesday, the 30th of September", "next Saturday 10 October",
    "next Saturday the 10th", "next Saturday, 2026-10-10", "agle Shanivar 10 tarikh",
    # Two different days in one breath are not one day to confirm.
    "next Friday or next Saturday", "", None,
])
def test_anything_else_is_not_that_question(said):
    assert day_reading.next_weekday_options(said, FRI) == []


def test_a_weekday_word_in_any_of_the_three_languages():
    assert [day_reading.weekday_of(w) for w in (
        "Saturday", "sat", "Saturday's", "shanivar", "shaniwaar", "Shanivara",
        "somvar", "somavara", "guruvar", "ravivar", "itwar", "bhanuvara",
        "शनिवार", "ಶನಿವಾರ", "satire", "next", "")] == [
        5, 5, 5, 5, 5, 5, 0, 0, 3, 6, 6, 6, 5, 5, None, None, None]


def test_the_past_is_today_before_now_too():
    now = datetime(2026, 10, 2, 15, 30, tzinfo=IST)
    assert day_reading.is_past(date(2026, 10, 1), None, now)
    assert day_reading.is_past(date(2026, 10, 2), "11:00", now)
    assert not day_reading.is_past(date(2026, 10, 2), "16:00", now)
    assert not day_reading.is_past(date(2026, 10, 2), None, now)
    assert not day_reading.is_past(date(2026, 10, 3), "09:00", now)


def test_a_reading_is_trusted_only_when_it_holds_together():
    out = day_reading.parse_readings({"readings": [
        {"index": 0, "date": "2026-10-10", "weekday": "Saturday", "time": "11:00"},
        {"index": 1, "date": "2026-10-10", "weekday": "Friday", "time": "11:00"},  # wrong day
        {"index": 2, "date": None, "weekday": None, "time": "9:5"},               # not a time
        {"index": 3, "date": "10/10/2026"},                                       # not ISO
        {"index": 9, "date": "2026-10-10"},                                       # no such piece
        {"index": 4, "date": None, "time": "17:00"},
        "junk",
    ]}, 6)
    assert out == [When(date(2026, 10, 10), "11:00"), None, None, None,
                   When(None, "17:00"), None]
    assert day_reading.parse_readings("not json", 2) == [None, None]


class _Model:
    def __init__(self, answer=None, fail=False):
        self.answer, self.fail, self.calls = answer, fail, []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("model down")
        return self.answer


async def test_the_model_is_given_the_moment_and_the_words(monkeypatch):
    model = _Model({"readings": [{"index": 0, "date": "2026-10-10",
                                  "weekday": "Saturday", "time": "11:00"}]})
    monkeypatch.setattr(day_reading, "get_model_layer", lambda: model)
    now = datetime(2026, 10, 2, 10, 30, tzinfo=IST)
    out = await REAL_READ_WHEN(org_id="o", user_id="u", pieces=["agle Shanivar 11 baje"],
                               now=now)
    assert out == [When(date(2026, 10, 10), "11:00")]
    call = model.calls[0]
    assert call["tier"] == "strong"
    prompt = call["messages"][0]["content"]
    assert "Friday, 02 October 2026" in prompt and "10:30" in prompt
    assert "agle Shanivar 11 baje" in prompt


async def test_a_model_that_fails_gives_no_reading(monkeypatch):
    monkeypatch.setattr(day_reading, "get_model_layer", lambda: _Model(fail=True))
    now = datetime(2026, 10, 2, 10, 30, tzinfo=IST)
    assert await REAL_READ_WHEN(org_id="o", user_id="u", pieces=["x"], now=now) is None


# ── answering "which Saturday?" ──────────────────────────────────────────

OPTIONS = ["2026-10-03", "2026-10-10"]


@pytest.mark.parametrize("answer, expected", [
    ("Saturday 10 October", "2026-10-10"), ("saturday 3 october", "2026-10-03"),
    ("10", "2026-10-10"), ("the 10th", "2026-10-10"), ("3rd", "2026-10-03"),
    ("October 10th at 4 pm", "2026-10-10"), ("the 10th at 3 pm", "2026-10-10"),
    ("1", "2026-10-03"), ("2", "2026-10-10"), ("second", "2026-10-10"),
    ("the tenth", "2026-10-10"), ("the third", "2026-10-03"),
    ("the first one", "2026-10-03"), ("the later one", "2026-10-10"),
    ("the week after", "2026-10-10"), ("this Saturday", "2026-10-03"),
    ("Saturday", None), ("next Saturday", None), ("whichever", None), ("", None),
])
def test_the_answer_to_which_saturday(answer, expected):
    assert meeting_draft.pick_day(OPTIONS, answer) == expected


def test_a_number_that_could_mean_either_is_not_guessed():
    # "2" is the second option AND the 2nd of the month, which is the first.
    assert meeting_draft.pick_day(["2026-10-02", "2026-10-09"], "2") is None
    assert meeting_draft.pick_day(["2026-10-02", "2026-10-09"], "9") == "2026-10-09"


def test_the_fallback_reader_never_settles_next_saturday():
    assert meeting_draft.parse_date("next saturday", today=FRI) is None
    assert meeting_draft.parse_date("this saturday", today=FRI) == date(2026, 10, 3)
    assert meeting_draft.parse_date("saturday", today=FRI) == date(2026, 10, 3)
    assert meeting_draft.parse_date("next week", today=FRI) is None


# ── Jarvis ───────────────────────────────────────────────────────────────

@pytest.fixture
def reader(monkeypatch):
    """Script the strong model's reading: `answers` is consumed one call at a
    time (a list of When per call); `calls` is what it was asked."""
    state = {"answers": [], "calls": []}

    async def scripted(*, org_id, user_id, pieces, now):
        state["calls"].append({"pieces": list(pieces), "now": now})
        if not state["answers"]:
            return None
        return state["answers"].pop(0)

    monkeypatch.setattr(day_reading, "read_when", scripted)
    return state


async def _now(org) -> datetime:
    async with SessionLocal() as db:
        return clock.now(await clock.org_zone(db, org["id"]))


async def _meetings(org) -> list[ScheduledMeeting]:
    async with SessionLocal() as db:
        return list((await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == org["id"]))).scalars().all())


def _agent(**args) -> list[LlmResponse]:
    return [LlmResponse(text='{"agent": "scheduling"}'),
            LlmResponse(tool_calls=[ToolCall(name="schedule_meeting", args=args)]),
            LlmResponse(text="Prose the question must replace.")]


async def _ask_which(client, org, fake_model, reader, session):
    """"next Saturday at 11 am": asked, never booked straight away."""
    now = await _now(org)
    options = day_reading.next_weekday_options("next Saturday", now.date())
    fake_model(_agent(client="ABC School", date="Saturday", time="11:00"))
    reader["answers"] = [[When(None, "11:00")]]
    first = await _say(client, org["agent"]["token"],
                       "Schedule a meeting with ABC School next Saturday at 11 am", session)
    return first, options


@pytest.mark.parametrize("answer", ["second", "the later one", "LABEL"])
async def test_next_saturday_is_asked_and_the_answer_books_it(
    client, org, fake_model, reader, answer
):
    session = f"day{uuid.uuid4().hex}"
    first, options = await _ask_which(client, org, fake_model, reader, session)
    later = day_reading.day_label(options[1])
    assert first["reply"] == (f"Which Saturday should the meeting with ABC School be: "
                              f"{day_reading.day_label(options[0])} or {later}?")
    asked = first["actions"][-1]
    assert asked["outcome"] == "needs_confirmation"
    assert asked["candidates"] == [day_reading.day_label(options[0]), later]
    assert await _meetings(org) == [], "nothing is booked before the answer"

    fake_model([_read(about_this=True)])
    second = await _say(client, org["agent"]["token"],
                        later if answer == "LABEL" else answer, session)
    assert "ABC School" in second["reply"], second
    [meeting] = await _meetings(org)
    assert (meeting.meeting_date, meeting.start_time) == (options[1], "11:00")


async def test_a_bare_weekday_does_not_answer_which_saturday(client, org, fake_model, reader):
    session = f"day{uuid.uuid4().hex}"
    _first, options = await _ask_which(client, org, fake_model, reader, session)
    fake_model([_read(about_this=True, date=options[0].isoformat())])
    second = await _say(client, org["agent"]["token"], "Saturday", session)
    assert second["reply"].startswith("Sorry, I couldn't tell which one.")
    assert await _meetings(org) == []
    fake_model([_read(about_this=True)])
    await _say(client, org["agent"]["token"], "the first one", session)
    [meeting] = await _meetings(org)
    assert meeting.meeting_date == options[0]


async def test_a_different_day_named_outright_is_taken(client, org, fake_model, reader):
    session = f"day{uuid.uuid4().hex}"
    _first, options = await _ask_which(client, org, fake_model, reader, session)
    monday = options[0] + timedelta(days=2)
    fake_model([_read(about_this=True)])
    reader["answers"] = [[When(monday, None)]]
    await _say(client, org["agent"]["token"], "make it Monday instead", session)
    [meeting] = await _meetings(org)
    assert (meeting.meeting_date, meeting.start_time) == (monday, "11:00")


async def test_an_unrelated_question_pauses_the_choice(client, org, fake_model, reader,
                                                       monkeypatch):
    from app.ai import orchestrator
    from app.ai.agents.base import AgentResult
    from app.ai.agents.query_agent import QueryAgent

    session = f"day{uuid.uuid4().hex}"
    await _ask_which(client, org, fake_model, reader, session)
    fake_model([_read(about_this=False)])

    async def route(ctx, text, history):
        return "query"

    async def answer(self, db, ctx, text, extra_context=None, history=None):
        return AgentResult(agent="query", reply="You have no tasks today.")

    monkeypatch.setattr(orchestrator, "route", route)
    monkeypatch.setattr(QueryAgent, "run", answer)
    reply = await _say(client, org["agent"]["token"], "what are my tasks today?", session)
    assert reply["reply"].startswith("You have no tasks today.")
    assert "continue arranging the meeting" in reply["reply"]
    assert await _meetings(org) == []


async def test_without_a_reading_next_saturday_is_still_asked(client, org, fake_model, reader):
    """The strong model unavailable: the question is still put, not a guess."""
    session = f"day{uuid.uuid4().hex}"
    now = await _now(org)
    options = day_reading.next_weekday_options("next Saturday", now.date())
    fake_model(_agent(client="ABC School", date=options[0].isoformat(), time="11:00"))
    first = await _say(client, org["agent"]["token"],
                       "meeting with ABC School next Saturday at 11 am", session)
    assert first["reply"].startswith("Which Saturday"), first["reply"]
    assert await _meetings(org) == []


async def test_this_saturday_is_booked_without_asking(client, org, fake_model, reader):
    session = f"day{uuid.uuid4().hex}"
    now = await _now(org)
    saturday = now.date() + timedelta(days=(5 - now.weekday()) % 7 or 7)
    fake_model(_agent(client="ABC School", date="Saturday", time="11:00"))
    reader["answers"] = [[When(saturday, "11:00")]]
    await _say(client, org["agent"]["token"],
               "Schedule a meeting with ABC School this Saturday at 11 am", session)
    [meeting] = await _meetings(org)
    assert (meeting.meeting_date, meeting.start_time) == (saturday, "11:00")
    assert reader["calls"][0]["pieces"] == [
        "Schedule a meeting with ABC School this Saturday at 11 am"]


async def test_the_strong_reading_replaces_the_agents_date(client, org, fake_model, reader):
    session = f"day{uuid.uuid4().hex}"
    now = await _now(org)
    right = now.date() + timedelta(days=2)
    fake_model(_agent(client="ABC School",
                      date=(now.date() + timedelta(days=1)).isoformat(), time="16:00"))
    reader["answers"] = [[When(right, "16:00")]]
    await _say(client, org["agent"]["token"],
               "Schedule a meeting with ABC School day after tomorrow at 4 pm", session)
    [meeting] = await _meetings(org)
    assert (meeting.meeting_date, meeting.start_time) == (right, "16:00")


async def test_a_day_in_the_past_is_never_booked(client, org, fake_model, reader):
    session = f"day{uuid.uuid4().hex}"
    now = await _now(org)
    yesterday = now.date() - timedelta(days=1)
    fake_model(_agent(client="ABC School", date=yesterday.isoformat(), time="11:00"))
    reader["answers"] = [[When(yesterday, "11:00")]]
    first = await _say(client, org["agent"]["token"],
                       "Schedule a meeting with ABC School on the 1st at 11", session)
    assert "has already passed" in first["reply"], first["reply"]
    assert "which day" in first["reply"].lower()
    assert await _meetings(org) == []


async def test_a_time_today_that_has_gone_by_is_asked_again(client, org, fake_model, reader):
    now = await _now(org)
    if now.hour == 0 and now.minute < 2:
        pytest.skip("no earlier time today to ask for")
    session = f"day{uuid.uuid4().hex}"
    gone = f"{0:02d}:{0:02d}"
    fake_model(_agent(client="ABC School", date=now.date().isoformat(), time=gone))
    reader["answers"] = [[When(now.date(), gone)]]
    first = await _say(client, org["agent"]["token"],
                       "Schedule a meeting with ABC School today at midnight 00:00", session)
    assert f"{gone} today has already passed" in first["reply"], first["reply"]
    assert await _meetings(org) == []


async def test_a_bare_number_answering_what_time_never_reaches_the_reader(
    client, org, fake_model, reader
):
    """"11" answering "what time?" is a time, not the 11th of the month."""
    session = f"day{uuid.uuid4().hex}"
    fake_model(_agent(client="ABC School", date="2037-10-02"))
    await _say(client, org["agent"]["token"],
               "Schedule a meeting with ABC School on 2 October 2037", session)
    calls_before = len(reader["calls"])
    fake_model([_read(about_this=True, time="11:00")])
    await _say(client, org["agent"]["token"], "11", session)
    assert len(reader["calls"]) == calls_before
    [meeting] = await _meetings(org)
    assert (meeting.meeting_date, meeting.start_time) == (date(2037, 10, 2), "11:00")


# ── recordings ───────────────────────────────────────────────────────────

class _Extraction:
    def __init__(self, payload):
        self.payload = payload

    async def generate(self, **kwargs):
        return LlmResponse(text=json.dumps(self.payload))


def _payload(agreed=None, items=()):
    return {"action_items": list(items), "summary": "s", "real_discussion": True,
            "key_facts": [], "agreed_meeting": agreed}


async def _analyse(monkeypatch, payload, now):
    monkeypatch.setattr(extraction, "get_model_layer", lambda: _Extraction(payload))
    return await extraction.analyse_meeting("t", org_name="O", client_name="C",
                                            today=now.date(), now=now)


TUE_10AM = datetime(2026, 9, 29, 10, 0, tzinfo=IST)


async def test_a_recordings_next_thursday_is_set_and_the_other_day_named(monkeypatch, reader):
    reader["answers"] = [[When(date(2026, 10, 8), None)]]
    analysis = await _analyse(monkeypatch, _payload(agreed={
        "agreed": True, "date": "2026-10-01", "day_said": "next Thursday", "time": "11:00"}),
        TUE_10AM)
    assert analysis.agreed_meeting["date"] == "2026-10-08"
    assert set(analysis.agreed_meeting) == {"date", "time", "duration_minutes", "purpose"}
    note = analysis.agreed_meeting_note
    assert "Thursday 1 October" in note and "Thursday 8 October" in note
    assert "set to Thursday 8 October" in note
    assert reader["calls"][0]["pieces"] == ["next Thursday"]
    assert reader["calls"][0]["now"] == TUE_10AM


async def test_without_a_reading_a_recordings_next_thursday_keeps_its_date_and_is_named(
    monkeypatch, reader
):
    analysis = await _analyse(monkeypatch, _payload(agreed={
        "agreed": True, "date": "2026-10-01", "day_said": "next Thursday"}), TUE_10AM)
    assert analysis.agreed_meeting["date"] == "2026-10-01"
    assert "Thursday 8 October" in analysis.agreed_meeting_note


async def test_a_date_the_words_settle_needs_no_model_and_no_note(monkeypatch, reader):
    wed = datetime(2026, 9, 23, 11, 0, tzinfo=IST)
    analysis = await _analyse(monkeypatch, _payload(
        agreed={"agreed": True, "date": "2026-09-30",
                "day_said": "next Wednesday, the 30th of September"},
        items=[{"title": "Send the references", "description": "d",
                "due_hint": "by this Friday, the 25th of September", "due_date": "2026-09-25"}]),
        wed)
    assert analysis.agreed_meeting["date"] == "2026-09-30"
    assert analysis.agreed_meeting_note is None
    assert analysis.action_items[0]["description"] == "d"
    assert reader["calls"] == [], "words the code reads one way cost no model call"


async def test_a_todos_next_friday_is_named_in_its_description(monkeypatch, reader):
    reader["answers"] = [[When(date(2026, 10, 9), None)]]
    analysis = await _analyse(monkeypatch, _payload(items=[
        {"title": "Send the proposal", "description": "As promised.",
         "due_hint": "by next Friday", "due_date": "2026-10-02"}]), TUE_10AM)
    item = analysis.action_items[0]
    assert item["due_date"] == datetime(2026, 10, 9)
    assert "Friday 2 October or Friday 9 October" in item["description"]
    assert item["description"].startswith("As promised.")


async def test_words_the_code_cannot_read_are_read_by_the_strong_model(monkeypatch, reader):
    reader["answers"] = [[When(date(2026, 10, 30), None)]]
    analysis = await _analyse(monkeypatch, _payload(items=[
        {"title": "Share the plan", "description": "d",
         "due_hint": "end of the month", "due_date": "2026-10-31"}]), TUE_10AM)
    assert analysis.action_items[0]["due_date"] == datetime(2026, 10, 30)
    assert analysis.action_items[0]["description"] == "d"


async def test_nothing_before_the_recording_is_kept(monkeypatch, reader):
    # "the 1st" said on 29 Sep read as 1 Sep: the kind of slip measured on
    # 2 Oct ("the 1st" said on 2 Oct was read as 1 Oct).
    reader["answers"] = [[When(date(2026, 9, 1), None), When(date(2026, 9, 20), None)]]
    analysis = await _analyse(monkeypatch, _payload(
        agreed={"agreed": True, "date": "2026-09-01", "day_said": "on the 1st"},
        items=[{"title": "Send the list", "description": "d",
                "due_hint": "by the 20th of last month", "due_date": "2026-09-20"}]),
        TUE_10AM)
    assert analysis.agreed_meeting is None, "a meeting in the past is not scheduled"
    titles = [i["title"] for i in analysis.action_items]
    assert titles == ["Send the list", "Agree the day of the next meeting"]
    assert analysis.action_items[0]["due_date"] is None
    assert "on the 1st" in analysis.action_items[1]["description"]


async def test_without_the_recording_moment_nothing_changes(monkeypatch, reader):
    monkeypatch.setattr(extraction, "get_model_layer", lambda: _Extraction(_payload(agreed={
        "agreed": True, "date": "2026-10-01", "day_said": "next Thursday"})))
    analysis = await extraction.analyse_meeting("t", org_name="O", client_name="C",
                                                today=TUE)
    assert analysis.agreed_meeting["date"] == "2026-10-01"
    assert analysis.agreed_meeting_note is None
    assert reader["calls"] == []


async def test_the_note_reaches_the_task_and_the_approval_but_not_the_email(client, org):
    from app.models.meeting import Meeting

    note = ('The recording said "next Thursday", which could be Thursday 1 October or '
            "Thursday 8 October. It is set to Thursday 8 October; if Thursday 1 October "
            "was meant, change it.")
    async with SessionLocal() as db:
        recording = Meeting(org_id=org["id"], lead_id=org["lead_id"],
                            agent_id=org["agent"]["id"], title="Visit")
        db.add(recording)
        await db.flush()
        lead = (await db.execute(select(Lead).where(Lead.id == org["lead_id"]))).scalar_one()
        meeting = await meeting_invite_service.schedule_from_recording(
            db, recording=recording, lead=lead,
            agreed={"date": "2037-10-08", "time": "11:00", "duration_minutes": None,
                    "purpose": "Go through the plan"},
            task_status="pending_review", summary="They agreed to meet.", note=note)
        await db.commit()
        task = (await db.execute(select(ActionItem).where(
            ActionItem.id == meeting.action_item_id))).scalar_one()
        invite = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.id == meeting.invite_message_id))).scalar_one()
        approval = (await db.execute(select(Approval).where(
            Approval.entity_type == "outbound_message",
            Approval.entity_id == invite.id))).scalar_one()
    assert task.description == f"Go through the plan {note}"
    assert approval.reason.endswith(note)
    assert "next Thursday" not in (invite.body or "") and "next Thursday" not in invite.subject
    assert meeting.purpose == "Go through the plan"
