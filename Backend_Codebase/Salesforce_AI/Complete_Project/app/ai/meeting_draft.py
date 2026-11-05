"""Jarvis arranges a meeting by conversation (customer ask, 21 Sep 2026).

"Schedule a meeting with ABC School" is a meeting, not a demo. The scheduling
agent's `schedule_meeting` tool lands here. When the request already names
the client, the day and the time, the meeting is scheduled at once — its
invite waits in Approvals, which is the human check. When something is
missing, ONE question is asked ("What time on Friday 2 October?") and the
conversation is held open (app/ai/confirmations.py), so the next message —
typed or spoken, in any wording — is read as the answer before any router
sees it. "cancel" drops it; an unrelated question pauses it.

The reading of a free answer is a model's job (it handles "4 in the evening",
Hindi and Kannada); `parse_time` / `parse_date` are the model-free fallback
for the plain answers people give most, so a model outage cannot strand the
conversation.
"""
from __future__ import annotations

import calendar
import logging
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import confirmations, day_reading
from app.ai.llm import TIER_FAST, get_model_layer
from app.core import clock
from app.core.context import OrgContext
from app.core.exceptions import (
    LeadNotOpenError,
    NeedsConfirmationError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.models.assistant import AssistantPendingAction
from app.models.lead import Lead

logger = logging.getLogger(__name__)

KIND = "meeting_draft"
AGENT = "scheduling"

# ── model-free readers ───────────────────────────────────────────────────

_TIME_RE = re.compile(
    r"^(?:at\s+|around\s+|by\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.?|p\.m\.?)?$"
)


def parse_time(text: str | None) -> str | None:
    """A clock time in a short answer → "HH:MM", else None.

    A bare hour is read as office hours: 8–11 morning, 12 noon, 1–7 afternoon
    or evening — nobody books a client meeting for 3 in the morning.
    """
    said = (text or "").strip().lower().rstrip(".")
    if said in ("noon", "midday", "12 noon"):
        return "12:00"
    m = _TIME_RE.match(said)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if minute > 59:
        return None
    meridian = (m.group(3) or "").replace(".", "")
    if meridian:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridian == "pm" else 0)
    elif m.group(2) is None:
        if not 1 <= hour <= 12:
            return None
        if 1 <= hour <= 7:
            hour += 12
    elif hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"


_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_DAYS = {name.lower(): i for i, name in enumerate(calendar.day_name)}
_DAYS.update({name.lower(): i for i, name in enumerate(calendar.day_abbr)})


def _next_on_or_after(today: date, month: int, day: int) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
    return None


def parse_date(text: str | None, *, today: date) -> date | None:
    """A day in a short answer → a date on or after today, else None."""
    said = re.sub(r"[,]", " ", (text or "").strip().lower())
    if day_reading.next_weekday_options(said, today):
        # "next Saturday" has two readings (2 Oct 2026); the flow asks which.
        return None
    said = re.sub(r"^(on|this|next|coming)\s+", "", said).strip()
    if not said:
        return None
    if said == "today":
        return today
    if said in ("tomorrow", "tmrw"):
        return today + timedelta(days=1)
    if said == "day after tomorrow":
        return today + timedelta(days=2)
    try:
        return date.fromisoformat(said)
    except ValueError:
        pass
    if said in _DAYS:
        return today + timedelta(days=(_DAYS[said] - today.weekday()) % 7)
    words = said.split()
    day = month = None
    for word in words:
        number = re.fullmatch(r"(\d{1,2})(st|nd|rd|th)?", word)
        if number:
            day = int(number.group(1))
        elif word in _MONTHS:
            month = _MONTHS[word]
        elif word in ("the", "of"):
            continue
        else:
            return None
    if day is None:
        return None
    if month is None:
        # "the 27th": this month if still ahead, else next month.
        found = _next_on_or_after(today, today.month, day) if day >= today.day else None
        if found is None or found.month != today.month:
            nxt = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
            try:
                found = date(nxt.year, nxt.month, day)
            except ValueError:
                return None
        return found
    return _next_on_or_after(today, month, day)


# ── only what was said ───────────────────────────────────────────────────
# Live test, 23 Sep 2026: asked "Set up a meeting with Abc School", the model
# called the tool with today's date and 09:00, and "…October 3 ke din" came
# with 09:00 too — despite the prompt forbidding it. So a value the model hands
# over is kept only when the person's own words hold one of that kind; the
# rest is asked for. Checked against the message, in all three languages and
# both scripts, because a spoken turn arrives in whatever script was heard.

_DAY_WORDS = re.compile(
    r"\d|\b(today|tonight|tomorrow|tmrw|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|jan|feb|mar|apr|"
    r"may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|"
    r"august|september|october|november|december|week|aaj|kal|parso|parson|naale|"
    r"nale|naadiddu|indu|somvar|mangalvar|budhvar|guruvar|shukravar|shanivar|"
    r"ravivar|somavara|mangalavara|budhavara|guruvara|shukravara|shanivara|"
    r"bhanuvara|ravivara)\b|वार|आज|कल|परसों|तारीख|ವಾರ|ಇಂದು|ನಾಳೆ|ನಾಡಿದ್ದು|ತಾರೀಖು",
    re.IGNORECASE,
)
_TIME_WORDS = re.compile(
    r"\d\s*(am|pm|a\.m|p\.m|baje|o'?clock|gante|ghante|hrs)\b|\d{1,2}[:.]\d{2}|\bat\s+\d{1,2}\b|"
    r"\b(noon|midday|morning|afternoon|evening|night|subah|dopahar|shaam|raat|"
    r"beligge|madhyana|madhyahna|sanje|ratri)\b|बजे|सुबह|दोपहर|शाम|रात|"
    r"ಗಂಟೆ|ಬೆಳಿಗ್ಗೆ|ಮಧ್ಯಾಹ್ನ|ಸಂಜೆ|ರಾತ್ರಿ",
    re.IGNORECASE,
)
_LENGTH_WORDS = re.compile(
    r"\b(min|mins|minute|minutes|hour|hours|hr|hrs|ghanta|ghante)\b|half an hour|"
    r"मिनट|घंटा|ನಿಮಿಷ",
    re.IGNORECASE,
)
# The same day words without the bare-digit catch-all: what lets the strong
# reader's date replace the agent's (a bare "11" answering "what time?" is not
# a day). A day of the month ("the 15th", "5 October") counts too.
_DAY_NAMES = re.compile(_DAY_WORDS.pattern[len(r"\d|"):], re.IGNORECASE)


def _day_text(text: str) -> str:
    """`text` without its clock times and lengths: "at 4 pm" names no date."""
    return re.sub(r"\d+\s*(min|mins|minute|minutes|hour|hours|hr|hrs)\b", " ",
                  _TIME_WORDS.sub(" ", text), flags=re.IGNORECASE)


def _names_a_day(text: str | None) -> bool:
    day_text = _day_text(text or "")
    return bool(_DAY_NAMES.search(day_text)
                or day_reading._DAY_OF_MONTH_RE.search(day_text))


_GENERIC = {"meeting", "meet", "schedule", "scheduled", "call", "visit", "with",
            "client", "discussion", "discuss", "set"}


def ground(values: dict[str, Any], text: str | None,
           client: str | None = None, asked: str | None = None) -> dict[str, Any]:
    """`values` with anything the words in `text` do not support removed.
    `asked` is the question the text answers: a bare "11" answering "what
    time?" is a time."""
    if not text:
        return dict(values)
    out = dict(values)
    day_text = _day_text(text)
    if out.get("date") and not _DAY_WORDS.search(day_text):
        out["date"] = None
    if out.get("time") and not (_TIME_WORDS.search(text)
                                or (asked == "time" and parse_time(text))):
        out["time"] = None
    if out.get("duration_minutes") and not _LENGTH_WORDS.search(text):
        out["duration_minutes"] = None
    purpose = out.get("purpose")
    if purpose:
        skip = _GENERIC | {w.lower() for w in re.findall(r"\w+", " ".join(
            [client or "", str(out.get("client") or "")]))}
        said = {w.lower() for w in re.findall(r"\w+", text)}
        meaningful = [w.lower() for w in re.findall(r"\w+", str(purpose))
                      if len(w) >= 4 and w.lower() not in skip]
        if not any(w in said for w in meaningful):
            out["purpose"] = None
    return out


# ── the draft ────────────────────────────────────────────────────────────

def _new_draft() -> dict[str, Any]:
    return {"lead_id": None, "client": None, "date": None, "time": None,
            "duration_minutes": None, "purpose": None, "cc": [], "bcc": [],
            "stage": None, "question": "", "candidates": [], "paused": False,
            # Clients the person must choose between, each {"id", "label",
            # "words"}, and the question that offers them.
            "options": [], "client_question": None,
            # The two days a "next Saturday" can mean (ISO) while it is asked.
            "date_options": []}


def _load(row: AssistantPendingAction) -> dict[str, Any]:
    import json

    draft = _new_draft()
    try:
        draft.update(json.loads(row.payload or "{}"))
    except ValueError:
        pass
    return draft


def _day_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


def lead_service_name(name: Any) -> str:
    from app.services.lead_service import normalise_name

    return normalise_name(str(name or ""))


def _question(draft: dict[str, Any]) -> tuple[str, str]:
    """(stage, question) for the first thing still missing."""
    who = draft["client"]
    if not draft["lead_id"]:
        return "client", draft.get("client_question") or "Which client is the meeting with?"
    if not draft["date"] and len(draft.get("date_options") or []) == 2:
        first, second = (date.fromisoformat(d) for d in draft["date_options"])
        return "date_choice", (f"Which {first.strftime('%A')} should the meeting with "
                               f"{who} be: {day_reading.day_label(first)} or "
                               f"{day_reading.day_label(second)}?")
    if not draft["date"]:
        return "date", f"Sure — which day should the meeting with {who} be?"
    return "time", f"What time on {_day_label(draft['date'])} should the meeting with {who} start?"


async def _client_options(db: AsyncSession, ctx: OrgContext,
                          names: list[str]) -> list[dict[str, Any]]:
    """The clients behind the resolver's candidate names, each labelled so
    two with the same name can be told apart: "Abc School (Hyd, Siva's)".

    Found in the live test (23 Sep 2026): the org holds two "Abc School"
    leads, and the resolver's "Abc School, Abc School. Which one?" could not
    be answered."""
    from sqlalchemy import func

    from app.models.user import User

    wanted = {n.strip().lower() for n in names if n and n.strip()}
    if not wanted:
        return []
    leads = (await db.execute(
        select(Lead).where(Lead.org_id == ctx.org_id, func.lower(Lead.name).in_(wanted))
        .order_by(Lead.created_at)
    )).scalars().all()
    owner_ids = {lead.owner_id for lead in leads if lead.owner_id}
    owners = dict((await db.execute(
        select(User.id, User.name).where(User.id.in_(owner_ids or {""}))
    )).all())
    options = []
    for lead in leads:
        owner = owners.get(lead.owner_id)
        bits = [b for b in (lead.city, f"{owner}'s" if owner else None) if b]
        label = f"{lead.name} ({', '.join(bits)})" if bits else lead.name
        words = [w for w in re.findall(r"[^\W\d_]+", " ".join(
            [lead.city or "", owner or ""]).lower()) if len(w) >= 3]
        options.append({"id": lead.id, "label": label, "name": lead.name, "words": words})
    labels = [o["label"] for o in options]
    for o, lead in zip(options, leads):
        if labels.count(o["label"]) > 1:
            o["label"] += f" — added {lead.created_at:%d %b %Y}"
    return options


_ORDINALS = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1,
             "third": 2, "3rd": 2, "3": 2, "fourth": 3, "4th": 3, "4": 3}


def _similar(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio()


def pick_option(options: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    """Which offered client an answer means, without a model: the label
    itself, "the second one", or a word only one option has — its city ("the
    Hyderabad one" for Hyd) or its owner ("Priya's")."""
    said = (text or "").strip().lower()
    if not said or not options:
        return None
    for o in options:
        if said == o["label"].lower():
            return o
    tokens = [t[:-2] if t.endswith("'s") else t for t in re.findall(r"[\w']+", said)]
    ordinals = {_ORDINALS[t] for t in tokens if t in _ORDINALS}
    if "last" in tokens:
        ordinals.add(len(options) - 1)
    if len(ordinals) == 1:
        index = ordinals.pop()
        return options[index] if index < len(options) else None

    def near(t: str, w: str) -> bool:
        # "Shiva" is how speech recognition writes Siva (26 Sep 2026).
        return len(t) >= 4 and len(w) >= 4 and _similar(t, w) >= 0.8

    def names_it(o: dict[str, Any]) -> bool:
        return any(t.startswith(w) or (len(t) >= 3 and w.startswith(t)) or near(t, w)
                   for w in o["words"] for t in tokens)

    hits = [o for o in options if names_it(o)]
    return hits[0] if len(hits) == 1 else None


def _choice_question(options: list[dict[str, Any]], hint: str) -> str:
    # Numbered, so "1" or "2" always works, whatever else was misheard.
    labels = [f"{i}. {o['label']}" for i, o in enumerate(options, 1)]
    listed = ", ".join(labels[:-1]) + f" or {labels[-1]}" if len(labels) > 1 else labels[0]
    names = {o["name"].lower() for o in options}
    if len(names) == 1:
        return f"There are {len(options)} clients called {options[0]['name']}: {listed}. Which one?"
    return f"Which client do you mean — {listed}?"


async def _resolve_client(db: AsyncSession, ctx: OrgContext, name: str
                          ) -> tuple[Lead | None, str | None, list[dict[str, Any]]]:
    """(lead, question, options): one lead, or a question and the clients
    it offers."""
    from app.ai.agents.base import AgentRuntime
    from app.ai.agents.resolvers import resolve_lead

    try:
        lead = await resolve_lead(AgentRuntime(db=db, ctx=ctx), name)
        return lead, None, []
    except NeedsConfirmationError as exc:
        options = await _client_options(db, ctx, list(exc.candidates or []))
        if len(options) >= 2:
            return None, _choice_question(options, name), options
        return None, exc.message, options


async def _apply(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any],
                 values: dict[str, Any], today: date) -> str | None:
    """Fold what was said into the draft. Returns a problem to say, or None."""
    from app.services.meeting_invite_service import normalise_time

    problem = None
    client = (values.get("client") or "").strip()
    if client and not draft["lead_id"]:
        lead, question, options = await _resolve_client(db, ctx, client)
        if lead is not None:
            draft["lead_id"], draft["client"] = lead.id, lead.name
            draft["options"], draft["client_question"], draft["candidates"] = [], None, []
        else:
            # Held in the draft, so every later turn asks the same choice
            # (and keeps whatever day and time were already said).
            draft["options"] = options
            draft["candidates"] = [o["label"] for o in options]
            draft["client_question"] = question
    raw_date = values.get("date")
    if values.get("date_options"):
        # "next Saturday": the day is asked, never settled silently.
        draft["date"], draft["date_options"] = None, list(values["date_options"])
    elif raw_date:
        found = parse_date(str(raw_date), today=today)
        if found is not None:
            draft["date"], draft["date_options"] = found.isoformat(), []
    raw_time = values.get("time")
    if raw_time:
        try:
            draft["time"] = normalise_time(str(raw_time))
        except ValidationFailedError:
            draft["time"] = parse_time(str(raw_time)) or draft["time"]
    if values.get("duration_minutes"):
        try:
            minutes = int(values["duration_minutes"])
            if 5 <= minutes <= 480:
                draft["duration_minutes"] = minutes
        except (TypeError, ValueError):
            pass
    if values.get("purpose"):
        draft["purpose"] = str(values["purpose"]).strip()[:2000]
    for key in ("cc", "bcc"):
        for address in values.get(key) or []:
            address = str(address).strip()
            if "@" in address and address not in draft[key]:
                draft[key].append(address)
    return problem


async def _ask(db: AsyncSession, ctx: OrgContext, session_id: str,
               row: AssistantPendingAction | None, draft: dict[str, Any],
               prefix: str | None = None) -> confirmations.Outcome:
    stage, question = _question(draft)
    if prefix:
        question = f"{prefix} {question}"
    draft["stage"], draft["question"] = stage, question
    await confirmations.save(db, ctx, session_id, kind=KIND, agent=AGENT,
                             payload=draft, summary=question, row=row)
    # A choice between two days offers the two days as taps.
    candidates = ([day_reading.day_label(date.fromisoformat(d))
                   for d in draft["date_options"]] if stage == "date_choice"
                  else list(draft.get("candidates") or []))
    action = {"tool": "schedule_meeting", "args": {"stage": stage}, "ok": False,
              "outcome": "needs_confirmation", "error": question, "question": question,
              "candidates": candidates,
              "details": {"kind": KIND, "client": draft["client"], "date": draft["date"],
                          "time": draft["time"]}}
    return confirmations.Outcome(reply=question, actions=[action])


async def _create(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any]) -> dict[str, Any]:
    from app.services import meeting_invite_service

    lead = (await db.execute(select(Lead).where(
        Lead.org_id == ctx.org_id, Lead.id == draft["lead_id"]))).scalar_one()
    meeting, invite = await meeting_invite_service.schedule(
        db, ctx, lead=lead, on_date=date.fromisoformat(draft["date"]),
        time_hhmm=draft["time"], duration_minutes=draft["duration_minutes"],
        purpose=draft["purpose"], cc=draft["cc"], bcc=draft["bcc"], source="jarvis",
    )
    when = meeting_invite_service.when_text(meeting)
    if invite is not None:
        reply = (f"Done — the meeting with {lead.name} is set for {when}. The invite "
                 f"to {invite.to_address} is waiting in Approvals.")
    else:
        reply = (f"Done — the meeting with {lead.name} is set for {when}. {lead.name} "
                 "has no contact with an email address, so no invite was drafted.")
    # Named "scheduled_meeting_id", not a bare "id": the app reads a bare id on
    # a *meeting* tool as a recording and opened the transcribing screen
    # (25 Sep 2026). "approval_id" is what the card's Open should reach: the
    # invite waiting in Approvals.
    return {"scheduled": True, "scheduled_meeting_id": meeting.id, "client": lead.name,
            "date": meeting.meeting_date.isoformat(), "time": meeting.start_time,
            "duration_minutes": meeting.duration_minutes,
            "invite_email": ("drafted and waiting in Approvals" if invite is not None
                             else "no contact email on the client"),
            "approval_id": (await meeting_invite_service.approval_id_for(db, invite)
                            if invite is not None else None),
            "reply": reply}


async def _clash(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any]) -> str | None:
    """Does the chosen slot overlap one of this person's meetings? (25 Sep 2026)"""
    from app.services.meeting_invite_service import find_clash

    if not (draft["date"] and draft["time"]):
        return None
    return await find_clash(
        db, org_id=ctx.org_id, organizer_id=ctx.user_id,
        on_date=date.fromisoformat(draft["date"]), time_hhmm=draft["time"],
        duration_minutes=draft["duration_minutes"])


async def _not_open(db: AsyncSession, ctx: OrgContext,
                    draft: dict[str, Any]) -> str | None:
    """The refusal to say when the chosen client is still in cold calling.

    Asked as soon as the client is known, not at the end: asking for a day
    and a time for a meeting that cannot be booked wastes both answers."""
    from app.services import lead_service

    if not draft["lead_id"]:
        return None
    lead = (await db.execute(select(Lead).where(
        Lead.org_id == ctx.org_id, Lead.id == draft["lead_id"]))).scalar_one_or_none()
    if lead is None:
        return None
    try:
        lead_service.ensure_opened(lead, "scheduling a meeting")
    except LeadNotOpenError as exc:
        return exc.message
    return None


def _missing(draft: dict[str, Any]) -> bool:
    return not (draft["lead_id"] and draft["date"] and draft["time"])


# ── the day and time, read by the strong model (2 Oct 2026) ──────────────
# The fast agent model passed "Saturday" for "next Saturday", or a wrongly
# counted date. The strong model, given the moment and the person's own
# words, reads them right (day_reading's docstring has the measurements), so
# its date and time replace the agent's -- but only for what the words
# actually name: a date only when they name a day in words, a time only when
# they name a clock time. Without a reading, everything is as before.

async def _with_day_reading(ctx: OrgContext, values: dict[str, Any],
                            text: str | None, now) -> dict[str, Any]:
    """`values` with "date"/"time" from the person's own `text`, and
    "date_options" (two ISO days) when it says "next <weekday>"."""
    out = dict(values)
    if not text or not text.strip():
        return out
    options = day_reading.next_weekday_options(text, now.date())
    if options:
        out["date"] = None
        out["date_options"] = [d.isoformat() for d in options]
    wants_day = not options and _names_a_day(text)
    wants_time = bool(_TIME_WORDS.search(text))
    if not (wants_day or wants_time):
        return out
    readings = await day_reading.read_when(
        org_id=ctx.org_id, user_id=ctx.user_id, pieces=[text], now=now)
    found = readings[0] if readings else None
    if found is None:
        return out
    if wants_day and found.date is not None:
        out["date"] = found.date.isoformat()
    if wants_time and found.time is not None:
        out["time"] = found.time
    return out


def _already_past(draft: dict[str, Any], now) -> str | None:
    """A day (or a time today) that has gone by is not booked: it is taken
    out of the draft and the sentence to say is returned."""
    if not draft["date"]:
        return None
    day = date.fromisoformat(draft["date"])
    if day < now.date():
        draft["date"] = None
        return f"{_day_label(day.isoformat())} has already passed."
    if draft["time"] and day_reading.is_past(day, draft["time"], now):
        said, draft["time"] = draft["time"], None
        return f"{said} today has already passed."
    return None


_CLOCK = re.compile(
    r"\b\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.?|p\.m\.?|baje|o'?clock|hrs?|gante\w*)"
    r"|\bat\s+\d{1,2}(?:[:.]\d{2})?\b|\b\d{1,2}[:.]\d{2}\b",
    re.IGNORECASE,
)
_EARLIER = {"first", "earlier", "former", "sooner", "this", "coming"}
_LATER = {"second", "later", "latter", "following", "after"}
# A day of the month said as a word, as speech recognition may write it.
# "first" and "second" are not here: they name the two options.
_DAY_ORDINALS = {w: n for n, w in enumerate(
    "third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
    "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth "
    "nineteenth twentieth".split(), start=3)}
_DAY_ORDINALS["thirtieth"] = 30


def pick_day(options: list[str], text: str) -> str | None:
    """Which of the two offered days an answer means, without a model: the
    label itself, "10", "the 10th", "first"/"second", "the later one", or the
    number of the option. An answer that could mean either is None."""
    days = [date.fromisoformat(d) for d in options]
    said = " ".join((text or "").lower().split()).strip(" .!?")
    if not said:
        return None
    for d, iso in zip(days, options):
        if said == day_reading.day_label(d).lower():
            return iso
    tokens = re.findall(r"[a-z]+|\d+", said)
    # Numbers that are not a clock time: "the 10th at 3 pm" names the 10th.
    numbers = [int(t) for t in re.findall(r"\d+", _CLOCK.sub(" ", said))]
    numbers += [_DAY_ORDINALS[t] for t in tokens if t in _DAY_ORDINALS]
    by_day = {iso for d, iso in zip(days, options) if d.day in numbers}
    by_place: set[str] = set()
    if tokens in (["1"], ["one"]):
        by_place.add(options[0])
    if tokens in (["2"], ["two"]):
        by_place.add(options[1])
    words = set(tokens)
    if words & _EARLIER:
        by_place.add(options[0])
    if words & _LATER:
        by_place.add(options[1])
    chosen = by_day | by_place
    return chosen.pop() if len(chosen) == 1 else None


# ── entry from the tool ──────────────────────────────────────────────────

async def start(runtime: Any, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule now if everything is known; otherwise ask and hold the chat.
    Raises NeedsConfirmationError carrying the question."""
    from app.services.meeting_invite_service import may_schedule

    db, ctx = runtime.db, runtime.ctx
    if not may_schedule(ctx.role):
        raise PermissionDeniedError("Your role cannot arrange client meetings.")
    now = clock.now(await clock.org_zone(db, ctx.org_id))
    today = now.date()
    text = runtime.extra_context.get("_user_text")
    values = ground(values, text)
    values = await _with_day_reading(ctx, values, text, now)
    draft = _new_draft()
    problem = await _apply(db, ctx, draft, values, today)
    refusal = await _not_open(db, ctx, draft)
    if refusal:
        raise LeadNotOpenError(refusal)
    problem = _already_past(draft, now) or problem
    clash = await _clash(db, ctx, draft)
    if not _missing(draft) and not clash:
        return await _create(db, ctx, draft)
    session_id = runtime.extra_context.get("session_id")
    if clash:
        # The time is taken: keep the client and the day, ask for another time.
        draft["time"] = None
        problem = clash
        if not session_id:
            raise ValidationFailedError(f"{clash} Tell me another time.")
    if not session_id:
        stage, question = _question(draft)
        raise ValidationFailedError(
            f"{problem or question} (Tell me the client, the day and the time together "
            "and I'll schedule it.)")
    outcome = await _ask(db, ctx, session_id, None, draft, prefix=problem)
    action = outcome.actions[0]
    raise NeedsConfirmationError(outcome.reply, candidates=action["candidates"],
                                 details=action["details"])


# ── reading the answer ───────────────────────────────────────────────────

_READ_PROMPT = """You are helping arrange a meeting with a client. The assistant
asked: "{question}"

What is known so far: client={client}, day={day}, time={time}.
Today is {today}. The person may answer in English, Hindi or Kannada,
romanised or in script, and may mix languages.

Their reply: "{reply}"

Return JSON:
  "about_this": false if the reply is about something else entirely (a new,
      unrelated request or question), else true
  "cancel": true if they want to drop the meeting
  "client": the client name if they gave one, else null
  "date": the day as YYYY-MM-DD resolved against today (on or after today),
      else null
  "time": the start time as HH:MM on a 24-hour clock, else null ("4 in the
      evening" is 16:00; a bare "11" is 11:00; "3" alone is 15:00)
  "duration_minutes": a number only if a length was said, else null
  "purpose": what the meeting is for, only if they said, else null
  "cc", "bcc": email addresses they asked to copy in, else []
Never invent a value the reply does not contain."""

_READ_SCHEMA = {
    "type": "object",
    "properties": {
        "about_this": {"type": "boolean"}, "cancel": {"type": "boolean"},
        "client": {"type": "string", "nullable": True},
        "date": {"type": "string", "nullable": True},
        "time": {"type": "string", "nullable": True},
        "duration_minutes": {"type": "integer", "nullable": True},
        "purpose": {"type": "string", "nullable": True},
        "cc": {"type": "array", "items": {"type": "string"}},
        "bcc": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["about_this"],
}


async def _read_reply(ctx: OrgContext, draft: dict[str, Any], text: str,
                      today: date) -> dict[str, Any] | None:
    """The model's reading, or None when it could not give one."""
    try:
        data = await get_model_layer().generate_json(
            purpose="assistant.meeting_draft.read", tier=TIER_FAST,
            org_id=ctx.org_id, user_id=ctx.user_id,
            messages=[{"role": "user", "content": _READ_PROMPT.format(
                question=draft["question"], client=draft["client"] or "unknown",
                day=draft["date"] or "unknown", time=draft["time"] or "unknown",
                today=today.strftime("%A %Y-%m-%d"), reply=text[:500],
            )}],
            json_schema=_READ_SCHEMA, temperature=0.0, max_tokens=300,
        )
    except Exception:  # noqa: BLE001 — the fallback reader takes over
        logger.warning("Meeting draft: the reading model failed", exc_info=True)
        return None
    return data if isinstance(data, dict) and "about_this" in data else None


def _plain_reading(draft: dict[str, Any], text: str, today: date) -> dict[str, Any]:
    """Model-free: the plain answer to the question that was asked."""
    stage = draft["stage"]
    if stage == "client":
        if draft.get("options"):
            # An answer that picked none of the offered clients: ask again.
            return {"about_this": False}
        return {"about_this": True, "client": text.strip()}
    time_hhmm = parse_time(text)
    if stage == "time":
        return {"about_this": time_hhmm is not None, "time": time_hhmm}
    day = parse_date(text, today=today)
    if day is None:
        # "friday at 11" — split the day from the time.
        m = re.match(r"^(.*?)\s+at\s+(.+)$", text.strip(), re.IGNORECASE)
        if m:
            day = parse_date(m.group(1), today=today)
            time_hhmm = parse_time(m.group(2))
    if day is None and day_reading.next_weekday_options(text, today):
        # "next Saturday" is an answer: which of the two is asked next.
        return {"about_this": True, "date": None, "time": time_hhmm}
    return {"about_this": day is not None,
            "date": day.isoformat() if day else None, "time": time_hhmm}


def _dropped(draft: dict[str, Any]) -> confirmations.Outcome:
    who = f" with {draft['client']}" if draft["client"] else ""
    return confirmations.Outcome(reply=f"Okay, I've dropped the meeting{who}. Nothing was scheduled.")


async def handle(db: AsyncSession, ctx: OrgContext, row: AssistantPendingAction,
                 text: str, context: dict[str, Any] | None = None
                 ) -> confirmations.Outcome | None:
    from app.services.meeting_invite_service import may_schedule

    draft = _load(row)
    if not may_schedule(ctx.role):
        await confirmations.drop(db, row)
        return confirmations.Outcome(reply="Your role can no longer arrange meetings, "
                                           "so nothing was scheduled.")
    verdict = confirmations.classify_reply(text)
    if draft["paused"]:
        if verdict == confirmations.YES:
            draft["paused"] = False
            return await _ask(db, ctx, row.session_id, row, draft, prefix="Okay, back to the meeting.")
        if verdict == confirmations.NO:
            await confirmations.drop(db, row)
            return _dropped(draft)
    if verdict == confirmations.NO:
        await confirmations.drop(db, row)
        return _dropped(draft)

    now = clock.now(await clock.org_zone(db, ctx.org_id))
    today = now.date()
    # Answering "which Saturday: the 3rd or the 10th?" (2 Oct 2026).
    choosing = draft["stage"] == "date_choice" and len(draft.get("date_options") or []) == 2
    chosen_day = pick_day(draft["date_options"], text) if choosing else None
    picked = pick_option(draft["options"], text) if not draft["lead_id"] else None
    if picked is not None:
        draft["lead_id"], draft["client"] = picked["id"], picked["name"]
        draft["options"], draft["client_question"], draft["candidates"] = [], None, []
    reading = await _read_reply(ctx, draft, text, today)
    offered = [o["id"] for o in draft["options"]]
    if picked is None and offered and reading and reading.get("client"):
        # The model heard a client in the answer ("Twin School owned by
        # Shiva"). Match it against the choices on offer; looking it up by
        # name again finds both and asks the same question for ever (the
        # loop reported 26 Sep 2026).
        picked = (pick_option(draft["options"], str(reading["client"]))
                  or pick_option(draft["options"], f"{text} {reading['client']}"))
        if picked is not None:
            draft["lead_id"], draft["client"] = picked["id"], picked["name"]
            draft["options"], draft["client_question"], draft["candidates"] = [], None, []
        elif lead_service_name(reading["client"]) in {lead_service_name(o["name"])
                                                      for o in draft["options"]}:
            # Just the shared name again: that answers nothing.
            reading = {k: v for k, v in reading.items() if k != "client"}
            reading["about_this"] = True
            reading["_undecided"] = True
    if picked is not None:
        # The choice is made; the model may still hear a day or time in it.
        reading = dict(reading or {"about_this": True})
        reading["about_this"], reading["client"] = True, None
    elif chosen_day is not None:
        # "2" or "the 10th" answers the question on screen, whatever a model
        # makes of it on its own.
        reading = dict(reading or {"about_this": True})
        reading["about_this"] = True
    elif reading is None:
        reading = _plain_reading(draft, text, today)
        if not reading.get("about_this"):
            return await _ask(db, ctx, row.session_id, row, draft,
                              prefix="Sorry, I didn't catch that.")
    if not reading.get("about_this"):
        return None
    if reading.get("cancel"):
        await confirmations.drop(db, row)
        return _dropped(draft)
    draft["paused"] = False
    undecided = bool(reading.pop("_undecided", False))
    reading = ground(reading, text, client=draft["client"], asked=draft["stage"])
    choice_problem = None
    if choosing:
        # Only the person's answer settles which of the two days: never a
        # model's guess of a bare weekday.
        reading.pop("date", None)
        reading.pop("date_options", None)
        if chosen_day is None or _TIME_WORDS.search(text):
            better = await _with_day_reading(ctx, {}, text, now)
            if better.get("time"):
                reading["time"] = better["time"]
            # A day the answer names outright ("the 10th", "5 October"), or a
            # different day altogether ("make it Monday") -- but a bare
            # "Saturday" is the same question again.
            named = better.get("date")
            if chosen_day is None and named and not better.get("date_options") and (
                    named not in draft["date_options"]
                    or day_reading._DAY_OF_MONTH_RE.search(text)):
                chosen_day = named
        if chosen_day is not None:
            reading["date"] = chosen_day
        else:
            choice_problem = "Sorry, I couldn't tell which one."
    else:
        reading = await _with_day_reading(ctx, reading, text, now)
    problem = await _apply(db, ctx, draft, reading, today)
    if not draft["lead_id"] and draft["options"] and (
            undecided or [o["id"] for o in draft["options"]] == offered):
        # Still the same choice: say so, rather than repeating it silently.
        problem = "Sorry, I couldn't tell which one."
    problem = choice_problem or problem
    problem = _already_past(draft, now) or problem

    refusal = await _not_open(db, ctx, draft)
    if refusal:
        await confirmations.drop(db, row)
        return confirmations.Outcome(reply=refusal, actions=[{
            "tool": "schedule_meeting", "args": {"client": draft["client"]},
            "ok": False, "outcome": "not_allowed", "error": refusal,
        }])
    if _missing(draft):
        return await _ask(db, ctx, row.session_id, row, draft, prefix=problem)
    clash = await _clash(db, ctx, draft)
    if clash:
        draft["time"] = None
        return await _ask(db, ctx, row.session_id, row, draft, prefix=clash)
    await confirmations.drop(db, row)
    result = await _create(db, ctx, draft)
    return confirmations.Outcome(reply=result.pop("reply"), actions=[{
        "tool": "schedule_meeting", "args": {k: draft[k] for k in ("client", "date", "time")},
        "ok": True, "result": result,
    }])


class _MeetingDraftFlow:
    async def handle(self, db, ctx, row, text, context=None):
        return await handle(db, ctx, row, text, context)

    async def pause(self, db, ctx, row):
        draft = _load(row)
        draft["paused"] = True
        await confirmations.save(db, ctx, row.session_id, kind=KIND, agent=AGENT,
                                 payload=draft, summary=draft["question"], row=row)
        who = f" with {draft['client']}" if draft["client"] else ""
        return f"…and shall I continue arranging the meeting{who}?"


confirmations.register_flow(KIND, _MeetingDraftFlow())
