"""Which day and time a person means (2 Oct 2026).

Measured with the real models on 2 Oct 2026 (a Friday): "Schedule a meeting
with X next Saturday at 11 am" was booked for the next day (3 Oct) in three
runs out of four, and 10 Oct in one. Two causes. The fast agent model often
passed the person's words instead of a date ("Saturday", even dropping
"next"), and the code that read those words threw "next" away. Asked
directly, with today's date, weekday and time in front of it, the strong
model read 26 of 28 kinds of phrase right every time; the two it got wrong
were dates in the past ("the 1st" said on 2 Oct gave 1 Oct; "next Friday"
said on 26 Dec gave a date a year back).

So this module has two halves:

* `read_when` -- one strong-model call that says which day and time each
  piece of text names, given the moment it was said. It returns None when
  the model is unavailable, and callers then keep what they did before.
* plain code checks the model is never trusted with: the weekday it names
  must be the weekday of its date, a day may not be before the moment it was
  said, and "next" + a weekday ("next Saturday", "agle Shanivar", "mundina
  Shanivara") has two readings -- the coming one and the one a week later --
  so it is never settled silently. The developer chose that it is always
  confirmed (2 Oct 2026).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.ai.llm import TIER_STRONG, get_model_layer

logger = logging.getLogger(__name__)

# ── weekday names, in the three languages and both scripts ───────────────

_ENGLISH_DAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "weds": 2, "thursday": 3, "thu": 3, "thur": 3,
    "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6,
    "sun": 6,
}
# Romanised Hindi and Kannada day names as speech recognition writes them:
# a stem, then "var"/"vaar"/"war"/"vara"/"varam".
_STEMS = (
    (0, "som|soma"), (1, "mangal|mangala"), (2, "budh|budha"),
    (3, "guru|brihaspati|brahaspati"), (4, "shukra|sukra|shukr"),
    (5, "shani|sani"), (6, "ravi|bhanu|it|ait"),
)
_SCRIPT_DAYS = {
    "सोमवार": 0, "मंगलवार": 1, "बुधवार": 2, "गुरुवार": 3, "बृहस्पतिवार": 3,
    "शुक्रवार": 4, "शनिवार": 5, "रविवार": 6, "इतवार": 6,
    "ಸೋಮವಾರ": 0, "ಮಂಗಳವಾರ": 1, "ಬುಧವಾರ": 2, "ಗುರುವಾರ": 3,
    "ಶುಕ್ರವಾರ": 4, "ಶನಿವಾರ": 5, "ಭಾನುವಾರ": 6, "ರವಿವಾರ": 6,
}
_ROMAN_DAY_RE = re.compile(
    r"^(?:" + "|".join(f"(?P<d{i}>(?:{s})(?:v|w)aa?r(?:a|am|u|da|ada|adandu)?)"
                       for i, s in _STEMS)
    + r")$"
)
# "next" in English, Hindi and Kannada, romanised and in script.
_NEXT_WORDS = frozenset({"next", "agle", "agla", "agli", "agale", "mundina",
                         "mundhina", "अगले", "अगला", "अगली", "ಮುಂದಿನ"})

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
# Something in the words that pins the day of the month, so "next Wednesday,
# the 30th of September" has one reading. A bare number does not: "at 11"
# is a time.
_DAY_OF_MONTH_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)\b|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}\s+(?:of\s+)?(?:" + _MONTHS + r")\b"
    r"|\b(?:" + _MONTHS + r")\s+\d{1,2}\b"
    r"|\d{1,2}\s*(?:tarikh|tareekh|tarik|तारीख|ತಾರೀಖು)",
    re.IGNORECASE,
)
_SPLIT = re.compile(r"[\s,.;:!?()\"'“”‘’\-–—/]+")


def weekday_of(word: str) -> int | None:
    """The weekday (Monday = 0) a single word names, or None."""
    w = (word or "").strip().lower()
    if w.endswith("'s"):
        w = w[:-2]
    if w in _ENGLISH_DAYS:
        return _ENGLISH_DAYS[w]
    if w in _SCRIPT_DAYS:
        return _SCRIPT_DAYS[w]
    m = _ROMAN_DAY_RE.match(w)
    if m:
        for key, value in m.groupdict().items():
            if value:
                return int(key[1:])
    return None


def next_weekday_options(said: str | None, today: date) -> list[date]:
    """The two days "next <weekday>" can mean, or [] when the words are not
    that, or pin the day some other way.

    The coming one (the first such weekday after today) and the one a week
    later. Said on the same weekday ("next Friday" on a Friday) that is a week
    on and two weeks on. "next week Tuesday" and "this/coming Saturday" are
    not this pattern; nor is "next Wednesday, the 30th", whose date settles
    it. Two different "next" days in one breath ("next Friday or next
    Saturday") are left alone: that is not one day to confirm.
    """
    text = (said or "").replace("’", "'")
    if not text.strip() or _DAY_OF_MONTH_RE.search(text):
        return []
    words = [w for w in _SPLIT.split(text) if w]
    found: set[int] = set()
    for i, word in enumerate(words[:-1]):
        if word.lower() in _NEXT_WORDS:
            day = weekday_of(words[i + 1])
            if day is not None:
                found.add(day)
    if len(found) != 1:
        return []
    day = found.pop()
    ahead = (day - today.weekday()) % 7 or 7
    first = today + timedelta(days=ahead)
    return [first, first + timedelta(days=7)]


def day_label(day: date) -> str:
    """"Saturday 10 October" -- how a choice between two days is put."""
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def is_past(day: date, hhmm: str | None, now: datetime) -> bool:
    """Is this day (and time, when given) before `now`, in now's own zone?"""
    if day < now.date():
        return True
    if day == now.date() and hhmm:
        try:
            hour, minute = (int(x) for x in hhmm.split(":"))
        except ValueError:
            return False
        return (hour, minute) < (now.hour, now.minute)
    return False


# ── the model's reading ──────────────────────────────────────────────────

@dataclass
class When:
    """What one piece of text names. Either may be None."""
    date: date | None
    time: str | None  # "HH:MM", 24-hour


_PROMPT = """Today is {today}, {clock} ({zone}).

Below are numbered pieces of what a person said or wrote. They may be in
English, Hindi or Kannada, romanised or in script, and may be whole
sentences. For each piece, work out the calendar day it names and the clock
time it names, counted from today.

- date: the day as YYYY-MM-DD, or null when the piece names no day.
- weekday: the English name of that date's weekday, or null.
- time: the start time as HH:MM on a 24-hour clock, or null when no clock
  time is said ("morning" or "evening" alone is null; "subah 10 baje" is
  10:00; "shaam 5 baje" is 17:00).
Never invent a day or a time the piece does not contain.

{pieces}

Return JSON: {{"readings": [{{"index": 0, "date": "YYYY-MM-DD" or null,
"weekday": "..." or null, "time": "HH:MM" or null}}]}}"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "date": {"type": "string", "nullable": True},
                    "weekday": {"type": "string", "nullable": True},
                    "time": {"type": "string", "nullable": True},
                },
                "required": ["index"],
            },
        },
    },
    "required": ["readings"],
}

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_readings(data: Any, count: int) -> list[When | None]:
    """The model's answer -> one When per piece, None for a piece it got
    wrong or said nothing about. A date whose weekday is not the weekday the
    model named is not trusted; nor is a time that is not a clock time."""
    out: list[When | None] = [None] * count
    items = data.get("readings") if isinstance(data, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or not 0 <= index < count or out[index] is not None:
            continue
        day = None
        raw = item.get("date")
        if isinstance(raw, str) and raw.strip():
            try:
                day = date.fromisoformat(raw.strip()[:10])
            except ValueError:
                continue
            named = item.get("weekday")
            if isinstance(named, str) and named.strip() and \
                    day.strftime("%A").lower() != named.strip().lower():
                logger.info("Day reading %d: %s is not a %s; not trusted", index, day, named)
                continue
        time = None
        raw_time = item.get("time")
        if isinstance(raw_time, str) and raw_time.strip():
            m = _HHMM.match(raw_time.strip())
            if m is None:
                continue
            time = f"{int(m.group(1)):02d}:{m.group(2)}"
        out[index] = When(date=day, time=time)
    return out


async def read_when(
    *, org_id: str | None, user_id: str | None, pieces: list[str], now: datetime,
) -> list[When | None] | None:
    """One strong-model call for every piece. None when it could not be made
    or read: the caller then does what it did before this existed. `now` is
    the moment the words were said, aware, in the organisation's zone."""
    pieces = [str(p or "") for p in pieces]
    if not pieces:
        return []
    listed = "\n".join(f'{i}. "{p[:500]}"' for i, p in enumerate(pieces))
    try:
        data = await get_model_layer().generate_json(
            purpose="assistant.day_reading", tier=TIER_STRONG,
            org_id=org_id, user_id=user_id,
            messages=[{"role": "user", "content": _PROMPT.format(
                today=now.strftime("%A, %d %B %Y"), clock=now.strftime("%H:%M"),
                zone=str(now.tzinfo), pieces=listed)}],
            json_schema=_SCHEMA, temperature=0.0, max_tokens=150 + 80 * len(pieces),
        )
    except Exception:  # noqa: BLE001 -- the caller keeps its old reading
        logger.warning("Day reading unavailable", exc_info=True)
        return None
    return parse_readings(data, len(pieces))
