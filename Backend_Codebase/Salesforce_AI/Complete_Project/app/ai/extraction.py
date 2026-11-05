"""Meeting understanding: action items, summary, and lead-state signal.

One combined call keeps the §11.5 chain short (fewer and smaller calls).
"""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.core import clock
from app.ai.llm import TIER_FAST, extract_json, get_model_layer

logger = logging.getLogger(__name__)

_PROMPT = """You are analysing the transcript of a sales meeting between a
salesperson from {org_name} and people at the client organisation
"{client_name}".

Today is {today}.

Extract from the transcript:
1. action_items — concrete to-dos agreed or implied. For each:
   - title: short imperative (max 12 words)
   - description: one sentence of context
   - due_hint: the deadline in the speakers' own words, e.g. "next week",
     "before 15 July", or null when nobody gave one
   - due_date: that same deadline resolved against today's date, as a plain
     YYYY-MM-DD calendar date. Null ONLY when no deadline was given or it is
     genuinely impossible to resolve ("once budget is approved"). "Friday"
     means the next Friday on or after today; "next week" means seven days
     from today; a bare month-day is this year unless that is already past.
   A recording is sometimes a short voice note in which only our salesperson
   speaks, recapping a meeting afterwards ("they agreed the price, we have to
   prepare the order"). What our side says it has to do ("we have to...",
   "we need to...", "I must...", "let's...") is an action item even when
   nobody else speaks and no deadline was given.
2. summary — 3-5 sentence factual summary of the meeting.
3. real_discussion — true if a genuine sales discussion happened (not just
   a missed call or noise).
4. key_facts — up to 5 short facts worth remembering about this client
   (preferences, constraints, names, timelines).
5. agreed_meeting — whether both sides AGREED to meet again (in person or on a
   call) on a particular day. A demo is not a meeting for this purpose, and
   "let's catch up sometime" or "we'll call you" is not an agreement. Return:
   - agreed: true only for a concrete agreement to meet on a stated day
   - date: that day as YYYY-MM-DD, resolved against today exactly like
     due_date above; null if no day was agreed
   - day_said: the words the speakers used for that day, in English
     ("Thursday", "next Friday", "tomorrow", "5 October"); null if none
   - time: the agreed start time as HH:MM on a 24-hour clock, or null when
     none was said ("at 9" in a morning context is 09:00)
   - duration_minutes: only if a length was said, else null
   - purpose: a short phrase on the TOPIC of the meeting, from the
     transcript ("go through the proposal") — not who will attend
   Return null for agreed_meeting when no meeting was agreed. Do NOT also list
   the agreed meeting, attending it, or sending its invitation or calendar
   invite as action_items: the system schedules the meeting, puts it in the
   task list and drafts the invitation itself. Preparation for it (e.g. "print
   the brochure for the meeting") is still an action item.

Never invent tasks that were not discussed. The summary and key_facts are
stored permanently and reused, so describe the client only in the words the
transcript itself uses: never assume an industry, sector or type of
organisation that was not stated, and never substitute a different word for
one the speakers used.

LANGUAGE. Return every value in English — the summary, each key fact, and
every action item's title, description and due_hint — whatever language the
meeting was held in. Transcripts arrive in the language actually spoken, in
that language's own script, and a single sentence may mix two languages;
what you return is stored permanently, re-read by later steps, and shown to
colleagues who may not share the language of the call. Names are the one
exception: write people, organisations, places and products in Latin script
and never translate what they mean, because they are matched against existing
records. Keep due_hint as the deadline the way the speaker framed it, in
English ("next week", "before the December freeze") — not a resolved date.

These two rules do not conflict, so do not split the difference between them.
"Use the words the transcript uses" is about not inventing a vocabulary the
speakers never used — an industry, a sector, a kind of organisation, a
different term for the thing they named. It is not an instruction to preserve
the original language. Never leave an untranslated phrase sitting inside an
otherwise English sentence, and do not quote the source language to stay
faithful to it: state what the speaker meant, in English, using the English
counterpart of the term they actually used.

Return ONLY JSON.

TRANSCRIPT:
{transcript}
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_hint": {"type": "string", "nullable": True},
                    "due_date": {"type": "string", "nullable": True},
                },
                "required": ["title"],
            },
        },
        "summary": {"type": "string"},
        "real_discussion": {"type": "boolean"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "agreed_meeting": {
            "type": "object",
            "nullable": True,
            "properties": {
                "agreed": {"type": "boolean"},
                "date": {"type": "string", "nullable": True},
                "day_said": {"type": "string", "nullable": True},
                "time": {"type": "string", "nullable": True},
                "duration_minutes": {"type": "integer", "nullable": True},
                "purpose": {"type": "string", "nullable": True},
            },
        },
    },
    "required": ["action_items", "summary", "real_discussion"],
}


def _parse_agreed_meeting(raw: Any, today: date | None = None) -> dict[str, Any] | None:
    """The meeting the recording agreed, or None. A day is required — a
    meeting with no day cannot be put in anyone's calendar. A time that is not
    a real clock time is dropped rather than guessed (the invite is then
    all-day until an approver's "make it 11" sets one). The day is checked
    against the words the speakers used for it (`check_day`)."""
    if not isinstance(raw, dict) or not raw.get("agreed"):
        return None
    day = check_day(_parse_due_date(raw.get("date")), raw.get("day_said"), today)
    if day is None:
        return None
    time_text = None
    t = raw.get("time")
    if isinstance(t, str):
        parts = t.strip().split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            hour, minute = int(parts[0]), int(parts[1])
            if hour < 24 and minute < 60:
                time_text = f"{hour:02d}:{minute:02d}"
    duration = raw.get("duration_minutes")
    if not isinstance(duration, int) or not 5 <= duration <= 480:
        duration = None
    purpose = raw.get("purpose") if isinstance(raw.get("purpose"), str) else None
    return {"date": day.date().isoformat(), "time": time_text,
            "duration_minutes": duration, "purpose": (purpose or "").strip() or None}


def _parse_due_date(raw: Any) -> datetime | None:
    """The model's YYYY-MM-DD → a datetime, or None. A date it could not
    resolve stays None: the deadline then survives as `due_hint` prose rather
    than becoming a wrong date the nudge ladder would act on."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


# ── day words, resolved in code (BS Carmel School, 29 Sep 2026) ──────────
# "A meeting on Thursday", said on Tuesday 29 September, was stored as
# Wednesday 30 September. The model resolved the weekday wrongly and nothing
# checked it. The model now also hands back the words that were said for the
# day (`day_said`; for a to-do, its `due_hint`), the code reads those words
# from the day the meeting was RECORDED, and where the words are unambiguous
# the code's date wins.

_WEEKDAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
_WEEKDAYS.update({name.lower(): i for i, name in enumerate(calendar.day_abbr)})
_WEEKDAYS.update({"tues": 1, "weds": 2, "thur": 3, "thurs": 3})
_MONTH_NAMES = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTH_NAMES.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTH_NAMES["sept"] = 9
_WEEKDAY_RE = re.compile(
    r"\b(?:(next|this|coming)\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True))
    + r")(?:'s)?\b"
)
_DAY_MONTH_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)\b")
_MONTH_DAY_RE = re.compile(r"\b([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b")
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _on_or_after(today: date, month: int, day: int) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
    return None


def resolve_day_words(said: str | None, today: date) -> list[date]:
    """The day(s) the words name, counted from `today` (the recording's day).

    One date when the words are clear; two when they are honestly ambiguous
    ("next Friday" on a Tuesday is this Friday or the one after; "Tuesday"
    said on a Tuesday is today or a week on); none when the words name no
    single day the code can read ("next week", "after the exams", "Thursday
    or Friday")."""
    text = " ".join((said or "").lower().replace("’", "'").split())
    if not text:
        return []
    found: list[tuple] = []          # one entry per day expression in the words
    readings: list[list[date]] = []

    def add(key: tuple, days: list[date]) -> None:
        if key not in found:
            found.append(key)
            readings.append(days)

    rest = text
    if "day after tomorrow" in rest:
        add(("rel", 2), [today + timedelta(days=2)])
        rest = rest.replace("day after tomorrow", " ")
    if re.search(r"\b(tomorrow|tmrw)\b", rest):
        add(("rel", 1), [today + timedelta(days=1)])
    if re.search(r"\btoday\b", rest):
        add(("rel", 0), [today])
    for m in _WEEKDAY_RE.finditer(rest):
        modifier, name = m.group(1), m.group(2)
        ahead = (_WEEKDAYS[name] - today.weekday()) % 7
        first = today + timedelta(days=ahead)
        if modifier == "next":
            first = first if ahead else today + timedelta(days=7)
            days = [first, first + timedelta(days=7)]
        elif ahead == 0:
            days = [today + timedelta(days=7)] if modifier == "coming" \
                else [today, today + timedelta(days=7)]
        else:
            days = [first]
        add(("wd", _WEEKDAYS[name], modifier), days)
    for m in _ISO_RE.finditer(rest):
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        add(("date", d), [d])
    for m in _DAY_MONTH_RE.finditer(rest):
        if m.group(2) in _MONTH_NAMES:
            d = _on_or_after(today, _MONTH_NAMES[m.group(2)], int(m.group(1)))
            if d is not None:
                add(("date", d), [d])
    for m in _MONTH_DAY_RE.finditer(rest):
        if m.group(1) in _MONTH_NAMES:
            d = _on_or_after(today, _MONTH_NAMES[m.group(1)], int(m.group(2)))
            if d is not None:
                add(("date", d), [d])
    if not readings:
        return []
    # A weekday and the date it falls on ("Thursday, 1 October") agree; any
    # other mix of two days is a choice the words leave open.
    distinct = {tuple(r) for r in readings}
    if len(distinct) > 1:
        dated = [r for r in readings if len(r) == 1]
        if len({tuple(r) for r in dated}) == 1 and all(
            any(d in r for d in dated[0]) for r in readings
        ):
            return dated[0]
        return []
    return readings[0]


def check_day(model_day: datetime | None, said: str | None,
              today: date | None) -> datetime | None:
    """The model's date, unless the words said resolve to a different day.

    Kept when it is one of the readings of the words (or the words cannot be
    read, or there is no recording day to count from); otherwise replaced by
    the first reading. A day the words name but the model left out is filled."""
    if today is None or not said:
        return model_day
    readings = resolve_day_words(said, today)
    if not readings:
        return model_day
    if model_day is not None and model_day.date() in readings:
        return model_day
    chosen = readings[0]
    logger.info("Day words %r on %s: model said %s, code reads %s",
                said, today, model_day.date() if model_day else None, chosen)
    return datetime(chosen.year, chosen.month, chosen.day)


_RELATIONSHIP_PROMPT = """You are reading the transcript of a catch-up call
between {org_name} and a client organisation they have already delivered work
for, "{client_name}". The purpose of the call is to stay in touch rather than
to sell — but a happy client often mentions what they need next, and noticing
that is part of the job.

Today is {today}.

Extract from the transcript:
1. summary — 3-5 sentences on what was actually said. Write it so a colleague
   who was not on the call can pick up the relationship from it.
2. key_facts — up to 5 short facts worth remembering about this client
   (people, preferences, constraints, plans, dates they mentioned).
3. next_touch_days — how many days from today until it would be natural to
   speak again, as a whole number. Base it on what was said: a client who
   mentioned something happening next month wants to hear from you around
   then. Use 30 if the call gives you nothing to go on.
4. next_touch_topics — one short sentence on what to ask about next time,
   drawn from what they actually mentioned. Empty string if nothing specific
   came up.
5. new_opportunity — true if the client said anything a colleague would want
   to follow up on. Any ONE of these is enough:
     - interest in a product or service that was mentioned or shown to them
     - a need, a problem to solve, or more of what was already delivered
     - a budget, a timeline, or a season they are working towards
     - a question about price, availability or what else is offered
   It does not need to be a firm commitment, a signed intention or a date.
   This raises a card for a person to read and judge; it does not commit
   anybody to anything, so the bar is "worth a colleague's attention", not
   "certain to close".

   What does NOT count is ordinary friendliness with nothing behind it.
   "It was good working with you, we must do something again sometime" is
   warmth, not an opportunity — there is no thing they want and no when.

   Two worked examples, so both edges are clear:
     - "They were interested in the new product we showed them" — TRUE. They
       named a thing and expressed interest in it.
     - "Lovely to catch up, do stay in touch" — FALSE. Nothing was named.
6. opportunity_reason — one sentence on why, if new_opportunity is true.
   Empty string otherwise.
7. opportunity_quote — the client's own words that made you say true, copied
   from the transcript and not paraphrased. Empty string otherwise. A person
   is going to read this to decide, so it has to be what was actually said.

Do not invent tasks, deadlines or commitments. This was a conversation, not a
negotiation, and anything you list here is stored permanently and shown to
colleagues.

Describe the client only in the words the transcript itself uses: never assume
an industry, sector or type of organisation that was not stated.

LANGUAGE. Return every value in English, whatever language the call was held
in. Names are the exception: write people, organisations, places and products
in Latin script and never translate what they mean, because they are matched
against existing records.

Return ONLY JSON.

TRANSCRIPT:
{transcript}
"""

_RELATIONSHIP_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "next_touch_days": {"type": "integer"},
        "next_touch_topics": {"type": "string"},
        "new_opportunity": {"type": "boolean"},
        "opportunity_reason": {"type": "string"},
        "opportunity_quote": {"type": "string"},
    },
    "required": ["summary"],
}

# A suggested next touch has to be a date a person would actually accept.
# Tomorrow is pushy, three years away is the model having given up; both are
# worse than the plain default, so the value is clamped rather than trusted.
_MIN_TOUCH_DAYS = 2
_MAX_TOUCH_DAYS = 180
_DEFAULT_TOUCH_DAYS = 30


@dataclass
class RelationshipAnalysis:
    """What a catch-up produces. Deliberately no action_items field: the
    absence is the feature, and a field nobody fills is an invitation to
    start filling it."""

    summary: str = ""
    key_facts: list[str] = field(default_factory=list)
    next_touch_days: int = _DEFAULT_TOUCH_DAYS
    next_touch_topics: str = ""
    # A hint that the client may want to buy again. Never acted on directly:
    # it raises a card, and a person accepts or dismisses it.
    new_opportunity: bool = False
    opportunity_reason: str = ""
    opportunity_quote: str = ""


def _clamp_touch_days(raw: Any) -> int:
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TOUCH_DAYS
    return max(_MIN_TOUCH_DAYS, min(_MAX_TOUCH_DAYS, days))


async def analyse_relationship_meeting(
    transcript: str,
    *,
    org_name: str,
    client_name: str,
    org_id: str | None = None,
    user_id: str | None = None,
    tz_name: str | None = None,
) -> RelationshipAnalysis:
    """Read a catch-up. Never produces action items -- see the module note."""
    response = await get_model_layer().generate(
        purpose="conversation.analyse_relationship_meeting",
        tier=TIER_FAST,
        org_id=org_id,
        user_id=user_id,
        messages=[
            {
                "role": "user",
                "content": _RELATIONSHIP_PROMPT.format(
                    org_name=org_name,
                    client_name=client_name,
                    today=clock.today(clock.zone(tz_name)).strftime("%A, %d %B %Y"),
                    transcript=transcript[:100_000],
                ),
            }
        ],
        json_schema=_RELATIONSHIP_SCHEMA,
        temperature=0.2,
        max_tokens=4096,
    )
    data = extract_json(response.text)
    # A flag with no reason behind it is not something a person can act on,
    # so it is downgraded rather than shown. The card has to be able to say
    # why, and in the client's own words.
    flagged = bool(data.get("new_opportunity", False))
    reason = (data.get("opportunity_reason") or "").strip()
    quote = (data.get("opportunity_quote") or "").strip()
    if flagged and not (reason or quote):
        flagged = False

    return RelationshipAnalysis(
        summary=(data.get("summary") or "").strip(),
        key_facts=[f for f in data.get("key_facts", []) if isinstance(f, str)],
        next_touch_days=_clamp_touch_days(data.get("next_touch_days")),
        next_touch_topics=(data.get("next_touch_topics") or "").strip(),
        new_opportunity=flagged,
        opportunity_reason=reason if flagged else "",
        opportunity_quote=quote if flagged else "",
    )


@dataclass
class MeetingAnalysis:
    action_items: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    real_discussion: bool = False
    key_facts: list[str] = field(default_factory=list)
    # {"date", "time", "duration_minutes", "purpose"} when a meeting was agreed.
    agreed_meeting: dict[str, Any] | None = None
    # Said beside the agreed meeting when its day was "next <weekday>": which
    # two days that could be and which one it was set to (2 Oct 2026). For the
    # people who approve it, never for the client.
    agreed_meeting_note: str | None = None


# ── days a recording names, settled by the strong model (2 Oct 2026) ─────
# Recordings dated their meetings and to-dos with the fast model, and the
# code's own check accepts either reading of "next Friday". Now: words the
# code reads one way stay as they are (check_day above); words it cannot read
# ("end of the month", "in two weeks") are read by the strong model; "next
# <weekday>" is set to the strong model's reading and the other day is named
# beside it, because nobody is in a chat to be asked; and no day before the
# recording is kept.

def _label(day: date) -> str:
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


async def _settle_days(
    *, items: list[dict[str, Any]], agreed: dict[str, Any] | None,
    agreed_said: str | None, now: datetime, org_id: str | None, user_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str | None]:
    from app.ai import day_reading

    today = now.date()
    # (key, words): key is "meeting" or the item's index.
    asks: list[tuple[Any, str]] = []
    if agreed is not None and agreed_said:
        asks.append(("meeting", agreed_said))
    for i, item in enumerate(items):
        if item.get("due_hint"):
            asks.append((i, str(item["due_hint"])))
    ask_model = [(key, words) for key, words in asks
                 if day_reading.next_weekday_options(words, today)
                 or not resolve_day_words(words, today)]
    readings: dict[Any, Any] = {}
    if ask_model:
        found = await day_reading.read_when(
            org_id=org_id, user_id=user_id, pieces=[w for _, w in ask_model], now=now)
        if found:
            readings = {key: r for (key, _), r in zip(ask_model, found) if r is not None}

    def settle(key: Any, words: str, current: date | None) -> tuple[date | None, str | None]:
        """(the day, a note for the people who check it)."""
        options = day_reading.next_weekday_options(words, today)
        read = readings.get(key)
        read_day = read.date if read is not None else None
        if options:
            chosen = (read_day if read_day in options
                      else current if current in options else options[0])
            other = options[1] if chosen == options[0] else options[0]
            return chosen, (f'The recording said "{words}", which could be '
                            f"{_label(options[0])} or {_label(options[1])}. It is set to "
                            f"{_label(chosen)}; if {_label(other)} was meant, change it.")
        if read_day is not None and read_day >= today:
            return read_day, None
        return current, None

    out_items = [dict(item) for item in items]
    for key, words in asks:
        if key == "meeting":
            continue
        item = out_items[key]
        current = item["due_date"].date() if item.get("due_date") else None
        day, note = settle(key, words, current)
        if day is not None and day < today:
            day = None  # a deadline before the recording is not a deadline
        item["due_date"] = datetime(day.year, day.month, day.day) if day else None
        if note:
            item["description"] = f"{item.get('description') or ''} ({note})".strip()

    note = None
    if agreed is not None:
        current = date.fromisoformat(agreed["date"])
        day, note = settle("meeting", agreed_said, current) if agreed_said else (current, None)
        if day is None or day < today:
            # A meeting "agreed" for a day already gone is not scheduled; the
            # person who recorded it is asked to agree the day instead.
            out_items.append({
                "title": "Agree the day of the next meeting",
                "description": (f'The recording agreed to meet "{agreed_said or agreed["date"]}", '
                                "which falls before the day it was recorded, so no "
                                "meeting was scheduled."),
                "due_hint": None, "due_date": None,
            })
            return out_items, None, None
        agreed = {**agreed, "date": day.isoformat()}
    return out_items, agreed, note


async def analyse_meeting(
    transcript: str,
    *,
    org_name: str,
    client_name: str,
    org_id: str | None = None,
    user_id: str | None = None,
    tz_name: str | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> MeetingAnalysis:
    """`today` is the day the meeting was recorded, in the org's time zone.
    Given, it dates the prompt and the day words are checked against it
    (`check_day`); left out, the prompt uses the current day as before and
    nothing is checked.

    `now` is the moment it was recorded, aware, in the org's zone (2 Oct
    2026). Given, the days the recording names are also settled with the
    strong model (`_settle_days`); left out, nothing more happens."""
    response = await get_model_layer().generate(
        purpose="conversation.analyse_meeting",
        tier=TIER_FAST,
        org_id=org_id,
        user_id=user_id,
        messages=[
            {
                "role": "user",
                "content": _PROMPT.format(
                    org_name=org_name,
                    client_name=client_name,
                    today=(today or clock.today(clock.zone(tz_name))).strftime(
                        "%A, %d %B %Y"),
                    transcript=transcript[:100_000],
                ),
            }
        ],
        json_schema=_SCHEMA,
        temperature=0.2,
        max_tokens=8192,
    )
    data = extract_json(response.text)
    items: list[dict[str, Any]] = []
    for raw in data.get("action_items", []):
        if not raw.get("title"):
            continue
        item = dict(raw)
        item["due_date"] = check_day(
            _parse_due_date(raw.get("due_date")), raw.get("due_hint"), today)
        items.append(item)
    agreed = _parse_agreed_meeting(data.get("agreed_meeting"), today)
    agreed_note = None
    if now is not None:
        raw_agreed = data.get("agreed_meeting")
        said = raw_agreed.get("day_said") if isinstance(raw_agreed, dict) else None
        try:
            items, agreed, agreed_note = await _settle_days(
                items=items, agreed=agreed,
                agreed_said=said if isinstance(said, str) and said.strip() else None,
                now=now, org_id=org_id, user_id=user_id)
        except Exception:  # noqa: BLE001 -- never cost a recording its results
            logger.exception("Settling the recording's days failed; keeping the first reading")
    return MeetingAnalysis(
        action_items=items,
        summary=(data.get("summary") or "").strip(),
        real_discussion=bool(data.get("real_discussion", False)),
        key_facts=[f for f in data.get("key_facts", []) if isinstance(f, str)],
        agreed_meeting=agreed,
        agreed_meeting_note=agreed_note,
    )
