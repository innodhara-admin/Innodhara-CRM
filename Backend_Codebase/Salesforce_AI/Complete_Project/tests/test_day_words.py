"""Weekday words are resolved in code, from the recording's own day
(BS Carmel School, 29 Sep 2026).

"Arrange a meeting on Thursday", said on Tuesday 29 September, was stored as
Wednesday 30 September: the model resolved the weekday wrongly and nothing
checked it. The model now also returns the words the speaker used for the
day, the code resolves those words from the day the meeting was recorded,
and the code's date wins whenever the words are unambiguous.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from app.ai import extraction
from app.ai.llm import LlmResponse


TUE_29_SEP = date(2026, 9, 29)


def test_plain_words_resolve_from_the_recording_day():
    r = extraction.resolve_day_words
    assert r("Thursday", TUE_29_SEP) == [date(2026, 10, 1)]
    assert r("on thursday", TUE_29_SEP) == [date(2026, 10, 1)]
    assert r("this Thursday", TUE_29_SEP) == [date(2026, 10, 1)]
    assert r("coming Thursday", TUE_29_SEP) == [date(2026, 10, 1)]
    assert r("Thu", TUE_29_SEP) == [date(2026, 10, 1)]
    assert r("tomorrow", TUE_29_SEP) == [date(2026, 9, 30)]
    assert r("today", TUE_29_SEP) == [TUE_29_SEP]
    assert r("day after tomorrow", TUE_29_SEP) == [date(2026, 10, 1)]
    assert r("5 October", TUE_29_SEP) == [date(2026, 10, 5)]
    assert r("October 5th", TUE_29_SEP) == [date(2026, 10, 5)]


def test_ambiguous_words_give_both_readings():
    r = extraction.resolve_day_words
    # "next Friday" on a Tuesday: the coming Friday, or the one after.
    assert r("next Friday", TUE_29_SEP) == [date(2026, 10, 2), date(2026, 10, 9)]
    # The weekday it already is: later today is unlikely, a week on is likely.
    assert r("Tuesday", TUE_29_SEP) == [TUE_29_SEP, date(2026, 10, 6)]


def test_words_the_code_cannot_read_resolve_to_nothing():
    r = extraction.resolve_day_words
    for said in (None, "", "next week", "after the exams", "sometime soon",
                 "Thursday or Friday", "end of the month"):
        assert r(said, TUE_29_SEP) == [], said


def test_the_check_keeps_or_corrects_the_models_date():
    check = extraction.check_day
    thu = datetime(2026, 10, 1)
    wed = datetime(2026, 9, 30)
    # The BS Carmel case: model said Wednesday for "Thursday".
    assert check(wed, "Thursday", TUE_29_SEP) == thu
    assert check(thu, "Thursday", TUE_29_SEP) == thu
    # Ambiguous: either reading the model picked is kept...
    assert check(datetime(2026, 10, 9), "next Friday", TUE_29_SEP) == datetime(2026, 10, 9)
    assert check(datetime(2026, 10, 2), "next Friday", TUE_29_SEP) == datetime(2026, 10, 2)
    # ...a date that is neither is replaced by the first reading.
    assert check(datetime(2026, 10, 3), "next Friday", TUE_29_SEP) == datetime(2026, 10, 2)
    # Words the code cannot read: the model's date stands, None stays None.
    assert check(wed, "after the exams", TUE_29_SEP) == wed
    assert check(None, "after the exams", TUE_29_SEP) is None
    # Words the code CAN read fill a date the model left out.
    assert check(None, "tomorrow", TUE_29_SEP) == datetime(2026, 9, 30)
    # No recording day: nothing is checked.
    assert check(wed, "Thursday", None) == wed


def test_a_due_hint_is_read_for_its_day_words():
    check = extraction.check_day
    assert check(datetime(2026, 9, 30), "by Thursday", TUE_29_SEP) == datetime(2026, 10, 1)
    assert check(datetime(2026, 9, 30), "before Thursday's meeting", TUE_29_SEP) \
        == datetime(2026, 10, 1)
    assert check(datetime(2026, 10, 6), "next week", TUE_29_SEP) == datetime(2026, 10, 6)


class _Fake:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return LlmResponse(text=json.dumps(self.payload))


async def test_analyse_meeting_corrects_the_weekday_from_the_recording_day(monkeypatch):
    fake = _Fake({
        "action_items": [
            {"title": "Send the price list", "description": "d",
             "due_hint": "by Thursday", "due_date": "2026-09-30"},
        ],
        "summary": "s", "real_discussion": True, "key_facts": [],
        "agreed_meeting": {"agreed": True, "date": "2026-09-30", "time": None,
                           "day_said": "Thursday", "duration_minutes": None,
                           "purpose": "discuss the order"},
    })
    monkeypatch.setattr(extraction, "get_model_layer", lambda: fake)
    analysis = await extraction.analyse_meeting(
        "t", org_name="O", client_name="C", today=TUE_29_SEP)
    assert analysis.agreed_meeting["date"] == "2026-10-01"
    # The dictionary the pipeline reads keeps its four keys.
    assert set(analysis.agreed_meeting) == {"date", "time", "duration_minutes", "purpose"}
    assert analysis.action_items[0]["due_date"] == datetime(2026, 10, 1)
    # The prompt is dated from the recording, not from the day it is processed.
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "Tuesday, 29 September 2026" in prompt
    assert "day_said" in json.dumps(fake.calls[0]["json_schema"])


async def test_without_a_recording_day_nothing_changes(monkeypatch):
    fake = _Fake({
        "action_items": [], "summary": "s", "real_discussion": True,
        "agreed_meeting": {"agreed": True, "date": "2026-09-30", "day_said": "Thursday"},
    })
    monkeypatch.setattr(extraction, "get_model_layer", lambda: fake)
    analysis = await extraction.analyse_meeting("t", org_name="O", client_name="C")
    assert analysis.agreed_meeting["date"] == "2026-09-30"


async def test_the_prompt_asks_for_implied_todos_in_a_voice_note(monkeypatch):
    """BS Carmel's 46-second voice note ("we have to plan the ...") gave no
    action items. The prompt must say that a recording can be one person
    recapping, and that what our side has to do is a to-do."""
    fake = _Fake({"action_items": [], "summary": "s", "real_discussion": True})
    monkeypatch.setattr(extraction, "get_model_layer", lambda: fake)
    await extraction.analyse_meeting("t", org_name="O", client_name="C")
    prompt = fake.calls[0]["messages"][0]["content"].lower()
    assert "voice note" in prompt
    assert "we have to" in prompt and "we need to" in prompt
