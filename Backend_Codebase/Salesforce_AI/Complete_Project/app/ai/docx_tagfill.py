# app/ai/docx_tagfill.py
"""Work out what belongs in each tag of a simple-flow template (D4, D14, D15).

Two calls. `resolve_tags` is the first pass: the model is given the whole
client (D7), the whole document, and every tag with the context that tells it
apart, and it says what each one means. `answer_round` is every turn after
that: the same dossier, the questions still open, and what the salesperson
just said.

**Nothing here decides that a value is good enough.** The model proposes; this
module refuses. Every path out of a resolution is one of two outcomes -- the
value is *filled*, or the tag becomes a *question* a person answers -- and a
tag is never dropped, never silently blanked, and never filled from an answer
that failed a check. `docx_suggest._validate` set this shape: check the
model's answer against the data it was given rather than trusting it. There it
cost a click to be wrong; here it costs a paragraph in a document with the
organisation's name on it, so the checks are stricter.

**Five things turn a proposed fill into a question.**

*The author asked for it.* `<ask:...>` and `<ask_calculate:...>` always ask,
whatever confidence comes back (D4). For `ask_calculate` that is the whole
rule: the owner decided on 7 September that the assistant states the
conclusion it reached and asks, and whatever the person replies is written
verbatim. No figure this module produced ever reaches a document.

*Confidence below `FILL_CONFIDENCE_THRESHOLD`.* Worth having, and worth
remembering that it is self-reported and uncalibrated -- which is why it is
the weakest of the five checks and why D13's human review exists behind them
all.

*No citation, or one that names nothing in the dossier* (D14). This is the
check with teeth, because it is the only one the model cannot satisfy by
asserting. A citation is a **path into the dossier** -- `client.name`,
`contacts[0].name`, `meetings[3].transcript` -- and it is resolved against the
dossier that was actually sent. Free-text citations were considered and
refused: `"the transcript of the 14 Aug meeting"` cannot be checked, and an
unchecked citation is not a guard, it is a second opinion from the same model.
The cost of demanding a path is one extra question when the model writes a
path that does not resolve; the cost of not demanding one is a fabricated fact
in a client's proposal.

*The value does not survive `fill_scrub`* (D10). Markdown that would print
literally, a model describing the work instead of doing it, and -- with an
empty set of allowed amounts -- any money-shaped figure at all. That last one
is deliberate and follows from D15: no number reaches a document unless Python
computed it from the locked rate card or a person typed it, and a value this
module invented has done neither.

The scrub is the fence between a **model's** prose and a document, so it fences
model values. A value a **person** typed is not refused -- refusing someone
their own words re-asks the same question for ever, and they are the authority
here. It is still scrubbed, and the reasons ride along in `warnings` for the
D13 review to show. That is D10's "runs on every semantic value", with the
enforcement pointed at the party that needs fencing.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from app.core import clock

from app.ai.llm import TIER_STRONG, get_model_layer
from app.services import mou_arithmetic
from app.services import fill_scrub

logger = logging.getLogger(__name__)

#: D4. A module constant and not an organisation setting, by the owner's
#: decision on 2026-09-07: one place to change, no per-org surface to build,
#: and it can become a setting later without touching a caller.
FILL_CONFIDENCE_THRESHOLD = 0.80

#: Why a proposed fill became a question instead. Recorded on the resolution
#: so the review in D13, and anyone reading a fill session afterwards, can see
#: which rule fired rather than guessing from the outcome.
ASK_BY_DESIGN = "the author marked this tag to be asked"
NO_VALUE = "the model proposed no value"
LOW_CONFIDENCE = "the model was not confident enough"
NO_CITATION = "the model cited no fact"
UNKNOWN_CITATION = "the citation names nothing in the dossier"
UNUSABLE_VALUE = "the value did not pass the fill scrub"

#: How much of the salesperson's reply is quoted back in a citation (D14: a
#: user value cites the turn in which the person said it).
CITATION_QUOTE_CHARS = 160

_SCHEMA = {
    "type": "object",
    "properties": {"resolutions": {"type": "array", "items": {"type": "object"}}},
    "required": ["resolutions"],
}

_FIRST_PASS_PROMPT = """You are filling in a proposal document for a real \
client. Every tag below is a blank the template's author left for you, written \
as <angle brackets> in the document.

For each tag say what belongs in it, how confident you are, and -- this is the \
part that matters -- WHICH FACT ABOUT THIS CLIENT you got it from.

A citation is a path into the dossier below, and nothing else: "client.name", \
"contacts[0].title", "meetings[2].transcript", "rate_card.items". Write the \
path first; you may add ": " and a few words after it for a human to read. \
A citation that does not resolve against the dossier is thrown away and the \
tag is asked as a question instead, so do not guess at a path and do not cite \
the document -- the document is not evidence about this client.

If no fact supports a value, say so: leave "value" out and write a short, \
plain-language "question" the salesperson can answer in one line. That is a \
good outcome, not a failure.

Tags whose kind is "ask" or "ask_calculate" are ALWAYS asked -- the author \
wrote them that way. Still say what you would have proposed and why: your \
figure is offered to the salesperson as a suggestion they may accept, and it \
is never written into the document on its own. For "ask_calculate", reason as \
far as the rate card and the transcripts let you, state the conclusion you \
reached in plain language in "reason", and put your figure in "value".

Never invent a price. Never write markdown -- this goes into Word and the \
characters would be printed literally.

TODAY IS {today}. Any date you propose has to make sense against it, and a \
date the author suggested that has already gone by is stale -- say so in \
"reason" rather than offering it as though it were current.

THE DOCUMENT, with every tag exactly as it appears:
{document}

THE TAGS TO RESOLVE:
{tags}

EVERYTHING KNOWN ABOUT THIS CLIENT:
{dossier}
{omitted}
Return JSON: {{"resolutions": [{{"tag_id": "...", "value": "...", \
"confidence": 0.0, "citation": "section.field", "reason": "...", \
"question": "..."}}]}}"""

#: How the round a person was actually SHOWN is marked in the answer prompt.
#: The model is given every outstanding question (D8), so without a mark "all
#: the suggested values are fine" has nothing to refer to (11 September).
ON_SCREEN = "ON SCREEN NOW"

_ANSWER_PROMPT = """You are part-way through filling in a proposal document \
for a real client. You asked the salesperson some questions and they have \
just replied. Work out which questions the reply settles, and what each \
answer means for its tag.

One sentence may settle several questions at once -- "two of each" answers \
every quantity you asked about. Map it onto every question it covers.

Write what the person meant, in the form it should appear in the document. Do \
not correct their figures, round them, or substitute the author's default for \
what they said: if they answered "18,00,000 all inclusive", that is the value.

The person was shown only the questions marked {marker}. A reply that \
accepts the suggestions -- "all fine", "the rest are as suggested", "All the \
suggested values are fine" -- settles every {marker} question with the \
author's suggestion, except any the reply answers differently. It settles \
nothing that was not on screen: agreeing with a list is not agreeing to \
questions nobody has shown them yet.

TODAY IS {today}. Resolve the dates they mention against it -- "the 11th", \
"today", "next Friday" -- and never write a date they did not mean.

For a question the reply does NOT settle, leave "value" out and write a \
short "question" asking again -- in your own words, narrower than before.

THE QUESTIONS STILL OPEN:
{questions}

WHAT THE SALESPERSON JUST SAID:
{reply}

EVERYTHING KNOWN ABOUT THIS CLIENT:
{dossier}
{omitted}
Return JSON: {{"resolutions": [{{"tag_id": "...", "value": "...", \
"reason": "...", "question": "..."}}]}}"""


_REVISE_PROMPT = """The salesperson has just been shown every value about to \
be written into a proposal document, and they want something changed. Work out \
WHICH of the values below they mean, and what it should say instead.

Answer ONLY for the values that change. A sentence about one row is not a \
reason to rewrite the others, and a value you do not mention is left exactly \
as it is -- which is the right outcome for all of them but the one they meant.

Write what the person meant, in the form it should appear in the document. Do \
not correct their figures or round them. If you cannot tell which value they \
mean, return nothing at all: they will be shown the list again, and a guess \
here changes a document nobody asked you to change.

Never return a value that is empty. If a value should be removed, that is not \
something to decide here -- return nothing for it.

THE VALUES ABOUT TO BE WRITTEN:
{values}

WHAT THE SALESPERSON SAID:
{correction}

EVERYTHING KNOWN ABOUT THIS CLIENT:
{dossier}
{omitted}
Return JSON: {{"resolutions": [{{"tag_id": "...", "value": "...", \
"reason": "..."}}]}}"""


#: Which document a fill writes into. "proposal" is every caller before 28 Oct
#: 2026 (MOUs included), and for it the prompts and the usage purposes are
#: exactly what they were. "email" puts the same rules to a Word email template.
_PURPOSES = {
    "proposal": ("proposal.docx_tagfill", "proposal.docx_tagfill_answer",
                 "proposal.docx_tagfill_revise"),
    "email": ("email.tagfill", "email.tagfill_answer", "email.tagfill_revise"),
}


def _worded(prompt: str, document: str) -> str:
    if document == "proposal":
        return prompt
    return prompt.replace("a proposal document", "an email")


def _day(today: date | None) -> str:
    """Today, for a prompt, in words a model cannot misread as d/m or m/d.

    Defaulted rather than required: a caller that forgets still gets a date,
    because having no clock at all is the defect this exists to close. The
    organisation's own zone comes from the service, which has the database;
    this fallback is the platform default.
    """
    day = today or clock.today(clock.zone())
    return "%d %s" % (day.day, day.strftime("%B %Y"))


_DATE_RE = re.compile(r"^(\d{1,4})([./-])(\d{1,2})\2(\d{1,4})$")


def _same_day_as(default: Any, today: date | None) -> str | None:
    """Today in the author's own date format, if their suggestion has passed.

    D48, and the owner's report of 11 September: the template offered
    "1.9.2026" for the modified date and nothing in the system could tell it
    was ten days gone. What comes back is written the way THEY wrote theirs --
    same separator, same zero-padding -- because it is going into their
    document beside their other dates.

    **Only when the whole suggestion is a date.** "First Day of September, Two
    Thousand Twenty-Six (01-09-2026)" is prose with a date in it, and turning
    prose into today's date is a sentence this module would be inventing;
    D15 says it must not. The model is told the day instead and can offer the
    wording. "75", "1 Set", "32" and "3, 5, 6, 7, 8 and 9" are not dates and
    never match.

    Day-first, because these documents are Indian and their author wrote
    1.9.2026 for the first of September. A four-digit first field is read as
    a year instead.
    """
    match = _DATE_RE.match(str(default or "").strip())
    if not match:
        return None
    first, sep, middle, last = match.groups()
    parts = ((last, middle, first) if len(first) == 4 else (first, middle, last))
    day_s, month_s, year_s = parts
    try:
        was = date(int(year_s), int(month_s), int(day_s))
    except ValueError:
        return None
    now = today or clock.today(clock.zone())
    if was >= now:
        return None
    fresh = {"d": now.day, "m": now.month, "y": now.year}
    widths = {"d": len(day_s), "m": len(month_s), "y": len(year_s)}
    order = ("y", "m", "d") if len(first) == 4 else ("d", "m", "y")
    return sep.join(str(fresh[k]).zfill(widths[k]) for k in order)


def _offer_today(
    occurrence: Mapping[str, Any],
    record: dict[str, Any],
    today: date | None,
) -> dict[str, Any]:
    """Put today at the front of the taps when the author's date has passed.

    The author's own text is kept and still offered -- it is what the document
    says, and the person may want it -- but the tap their thumb lands on is
    today. Nothing is written either way: this is a suggestion on a question.
    """
    if record.get("outcome") != "question":
        return record
    fresh = _same_day_as(occurrence.get("default"), today)
    if fresh is None:
        return record
    record["candidates"] = [fresh] + [c for c in record.get("candidates") or []
                                      if c != fresh]
    record["default_has_passed"] = True
    return record


async def resolve_tags(
    ctx,
    *,
    dossier: Mapping[str, Any],
    document_text: str,
    occurrences: Sequence[Mapping[str, Any]],
    today: date | None = None,
    document: str = "proposal",
) -> list[dict[str, Any]]:
    """The first pass: one record per occurrence, filled or asked.

    The document goes in whole and so does the dossier (D7, section 8). This
    is the only call that carries the document -- the occurrence map and the
    dossier carry everything later turns need, and re-sending six thousand
    tokens of Word text per answer is what would make this expensive.
    """
    if not occurrences:
        return []

    prompt = _FIRST_PASS_PROMPT.format(
        today=_day(today),
        document=document_text,
        tags=_render_occurrences(occurrences),
        dossier=_render_dossier(dossier),
        omitted=_render_omitted(dossier),
    )
    answered = _answers(
        await _generate(ctx, _PURPOSES[document][0], _worded(prompt, document)),
        {o["tag_id"] for o in occurrences},
    )
    return [_offer_today(o, _first_pass(dossier, o, answered.get(o["tag_id"])),
                         today)
            for o in occurrences]


async def revise(
    ctx,
    *,
    dossier: Mapping[str, Any],
    resolutions: Sequence[Mapping[str, Any]],
    correction: str,
    document: str = "proposal",
) -> list[dict[str, Any]]:
    """A correction made during the D13 review: which values change, and to what.

    Unlike the other two calls this returns records **only for the tags it
    changes**. The review has just shown the person all twenty-five values and
    they objected to one; a sentence about the panel row is not evidence about
    the other twenty-four, and rewriting them from it would be the review
    doing harm rather than catching it.

    A correction is a person speaking, so what comes back is theirs -- `source:
    "user"`, full confidence, and a citation quoting what they actually said.
    """
    if not resolutions:
        return []

    prompt = _REVISE_PROMPT.format(
        values=_render_resolutions(resolutions),
        correction=correction,
        dossier=_render_dossier(dossier),
        omitted=_render_omitted(dossier),
    )
    answered = _answers(
        await _generate(ctx, _PURPOSES[document][2], _worded(prompt, document)),
        {r["tag_id"] for r in resolutions},
    )
    by_id = {r["tag_id"]: r for r in resolutions}
    citation = f'the correction: "{_quote(correction)}"'
    changed: list[dict[str, Any]] = []
    for tag_id, item in answered.items():
        value = _text(item, "value")
        if not value:
            # A tag_id with nothing to write is not a correction. Letting it
            # through as an empty value would REMOVE the tag from the
            # document -- tagfill treats "" as "delete this" -- which is the
            # opposite of what a person querying a value is asking for.
            logger.info("Ignoring correction for %s: no value proposed", tag_id)
            continue
        original = by_id[tag_id]
        warnings = _scrub(value) if original.get("kind") == "semantic" else []
        changed.append(_filled(original, value, source="user", confidence=1.0,
                               citation=citation, reason=_text(item, "reason"),
                               warnings=warnings))
    return changed


async def answer_round(
    ctx,
    *,
    dossier: Mapping[str, Any],
    open_questions: Sequence[Mapping[str, Any]],
    user_reply: str,
    asked: Sequence[Any],
    on_screen: Sequence[Mapping[str, Any]] = (),
    today: date | None = None,
    document: str = "proposal",
) -> list[dict[str, Any]]:
    """One clarification turn: what the reply settled, and what it did not.

    Returns a record for every question it was given, so a caller can replace
    the open set wholesale rather than reconciling two lists. A question the
    reply did not touch comes back still open, with the question to ask again.

    `on_screen` is the round the person was actually shown. The model is given
    every outstanding question (D8), so "all the suggested values are fine"
    had nothing to refer to: on the Orchid contract (11 September) the live
    model accepted NONE of the round when the same sentence named a date, and
    forty of forty-four -- thirty-seven never shown -- when it did not. The
    round is marked in the prompt, and a suggestion accepted for a question
    that was not on screen is refused here, because a prompt is advice.
    """
    if not open_questions:
        return []

    shown = {_screen_key(q) for q in on_screen}
    reads_the_same = {w for w in map(reads_as, on_screen) if w}
    prompt = _ANSWER_PROMPT.format(
        marker=ON_SCREEN,
        today=_day(today),
        questions=_render_questions(open_questions, shown, reads_the_same),
        reply=user_reply,
        dossier=_render_dossier(dossier),
        omitted=_render_omitted(dossier),
    )
    answered = _answers(
        await _generate(ctx, _PURPOSES[document][1], _worded(prompt, document)),
        {q["tag_id"] for q in open_questions},
    )
    citation = _turn_citation(asked, user_reply)
    out = []
    for q in open_questions:
        item = answered.get(q["tag_id"])
        if _accepted_unseen(q, item, shown, reads_the_same, user_reply):
            logger.info("Kept %s open: its suggestion was accepted, but it was "
                        "not on screen and the reply does not name it",
                        q["tag_id"])
            item = None
        out.append(_offer_today(q, _answered(q, item, citation), today))
    out = _freshen_accepted(out, open_questions, user_reply)
    return _spread(out, open_questions, citation)


def reads_as(question: Mapping[str, Any]) -> tuple[str, str] | None:
    """What a PERSON reads: the question's own words, and the value offered.

    D47, and the owner's ruling of 11 September. The programme name on their
    contract is asked in four places, with the same wording and the same
    suggestion behind each, and it took them four rounds: agreeing to one said
    nothing about the other three. Places that read the same now settle
    together -- `answer_round` counts them as on screen (extending D46) and
    spreads the answer across them.

    **The round is NOT collapsed on this key, and that is deliberate.** Every
    place keeps its own line and its own row label (D9). A model that writes
    "How many of these do you want?" for the Laptops row and the Interactive
    Panel row makes two different questions read identically, and a single line
    for both would name neither. What travels between them is the author's own
    suggestion and nothing else -- see `_spread`.

    Deliberately not keyed on the literal either. `<ask:75>` appears five times
    in that same document and those ARE five questions: when the model offers
    no wording, the fill writes a question naming each one's own place, so they
    never read alike. A shared suggestion is not enough, and keying on it is
    the replace_token bug D1 exists to prevent, arriving at the question layer.

    None when there is no wording yet -- nothing to compare, so nothing travels.
    """
    wording = _plain(question.get("question"))
    if not wording:
        return None
    return (wording, _plain(question.get("default")))


def _spread(
    answered: list[dict[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    citation: str,
) -> list[dict[str, Any]]:
    """One answer reaches every place the round drew as one question (D47).

    The model is handed every occurrence (D8) and answers the ids it
    recognises. The places it did not name are filled from their sibling here,
    rather than left for the next round to ask about again -- four rounds of
    "What is the name of the innovation program?" is what this costs when
    nobody does it.

    A value the person TYPED never travels. Whether two places that read the
    same really are one question cannot be known from the words: the owner's
    contract asks for the programme name in four places and means one answer,
    and a model that writes "How many of these do you want?" for the Laptops
    row and the Interactive Panel row means two. So only the AUTHOR'S OWN
    suggestion spreads -- it is what they wrote in every one of those places,
    so putting it back is not a surprise in any of them, and "All the suggested
    values are fine" is the sentence that was costing the owner a round each
    time. A figure a person typed stops at the place they were shown.

    A place the model answered ITSELF is never overwritten either. Their
    sentence may tell two places apart, and the model is the thing that read
    it.
    """
    by_id = {q["tag_id"]: q for q in questions}
    settled: dict[tuple[str, str], dict[str, Any]] = {}
    for record in answered:
        question = by_id[record["tag_id"]]
        key = reads_as(question)
        if not key or record["outcome"] != "filled" or key in settled:
            continue
        if _plain(record.get("value")) != _plain(question.get("default")):
            continue
        settled[key] = record
    if not settled:
        return answered

    out: list[dict[str, Any]] = []
    for record in answered:
        question = by_id[record["tag_id"]]
        key = reads_as(question)
        source = settled.get(key) if key else None
        if record["outcome"] != "question" or source is None:
            out.append(record)
            continue
        logger.info("Answered %s from %s: the same question, another place",
                    record["tag_id"], source["tag_id"])
        warnings = (_scrub(source["value"])
                    if question.get("kind") == "semantic" else [])
        out.append(_filled(question, source["value"], source="user",
                           confidence=1.0, citation=citation,
                           reason=source.get("reason"), warnings=warnings))
    return out


def _freshen_accepted(
    answered: list[dict[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    user_reply: str,
) -> list[dict[str, Any]]:
    """A suggestion the round replaced with today is ACCEPTED as today (D51).

    D48 put today at the front of the taps and said on the line that the
    author's date had gone by. It never changed what "All the suggested values
    are fine" MEANS for that question, so the owner's contract of 11 September
    was built carrying the template's own "modified: 1.9.2026" on the line a
    reader sees first. They agreed to what the round showed them, and what it
    showed was today.

    Only the author's stale date is swapped, and only when it was ACCEPTED
    rather than chosen. A person who names the old date keeps it: a contract
    can be dated the day it was agreed rather than the day it was typed, and
    naming a date is choosing it.
    """
    by_id = {q["tag_id"]: q for q in questions}
    out: list[dict[str, Any]] = []
    for record in answered:
        question = by_id[record["tag_id"]]
        fresh = (question.get("candidates") or [None])[0]
        stale = question.get("default")
        if (record.get("outcome") != "filled"
                or not question.get("default_has_passed")
                or not fresh
                or _plain(record.get("value")) != _plain(stale)
                or _names(user_reply, stale)):
            out.append(record)
            continue
        logger.info("Accepted %s as today: the author's %r has gone by",
                    record["tag_id"], stale)
        out.append(dict(record, value=fresh))
    return out


def _screen_key(question: Mapping[str, Any]) -> tuple[str, str]:
    """What a round shows ONE question for (D-D): the literal and its context.

    The key `proposal_fill_service.open_questions` collapses on, so a twin a
    person could not tell apart from the question they were shown counts as
    shown. Keyed on the tag id instead, "all fine" would settle the visible
    one, leave its twin open, and ask the same question again next round.
    """
    return (question.get("raw") or "", question.get("context") or "")


def _accepted_unseen(
    question: Mapping[str, Any],
    item: Mapping[str, Any] | None,
    shown: set[tuple[str, str]],
    reads_the_same: set[tuple[str, str]] | frozenset,
    user_reply: str,
) -> bool:
    """Did the model accept a suggestion for a question nobody was shown?

    The value is the author's own suggestion, the question was not on screen,
    and the person's words do not name it. A person who SAYS the figure has
    answered whichever round it sits in -- D8 is untouched -- so the reply is
    searched for the suggestion as whole words: "11.09.2026" does not name a
    quantity of 1.
    """
    if _on_screen(question, shown, reads_the_same):
        return False
    default = _plain(question.get("default"))
    if not default or _plain(_text(item, "value")) != default:
        return False
    return not _names(user_reply, default)


def _on_screen(question, shown, reads_the_same) -> bool:
    """Was this question in front of the person, under any description?

    Its own place, or a place that reads exactly the same (D47). The round
    draws one line per place, so strictly only one of them was on screen --
    but they are the same sentence with the same suggestion behind it, and a
    person agreeing to what they read has agreed to every place that reads
    that way. `_spread` is the other half: it carries the answer across.
    """
    if _screen_key(question) in shown:
        return True
    wording = reads_as(question)
    return wording is not None and wording in reads_the_same


def _names(user_reply: str, value: Any) -> bool:
    """Do the person's own words contain this value, as whole words?

    "11.09.2026" does not name a quantity of 1, and "Rs. 4000" inside a longer
    figure is not that figure. Shared by the two rules that have to tell a
    value a person CHOSE from one they merely did not object to.
    """
    wanted = _plain(value)
    if not wanted:
        return False
    return re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)",
                     _plain(user_reply)) is not None


def _plain(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


# --- the two outcomes --------------------------------------------------------


def _first_pass(
    dossier: Mapping[str, Any],
    occurrence: Mapping[str, Any],
    item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    value = _text(item, "value")
    because = _refuse(dossier, occurrence, item, value)
    if because is None:
        return _filled(occurrence, value, source="ai",
                       confidence=_confidence(item),
                       citation=_text(item, "citation") or None,
                       reason=_text(item, "reason"), warnings=[])
    # A value the scrub rejected is not offered as a tappable candidate
    # either. Tapping is not typing, and D15 admits a number to a document
    # only when Python computed it or a person wrote it out.
    proposal = "" if because == UNUSABLE_VALUE else value
    return _question(occurrence, because, proposal=proposal,
                     confidence=_confidence(item), reason=_text(item, "reason"),
                     question=_text(item, "question"))


def _refuse(
    dossier: Mapping[str, Any],
    occurrence: Mapping[str, Any],
    item: Mapping[str, Any] | None,
    value: str,
) -> str | None:
    """Which rule stops this becoming a fill, or None if none of them does."""
    if occurrence.get("kind") in ("ask", "ask_calculate"):
        return ASK_BY_DESIGN
    if not value:
        return NO_VALUE
    if _confidence(item) < FILL_CONFIDENCE_THRESHOLD:
        return LOW_CONFIDENCE
    citation = _text(item, "citation")
    if not citation:
        return NO_CITATION
    if not _cites_a_dossier_fact(dossier, citation):
        logger.info("Downgraded tag %s: citation %r resolves to nothing",
                    occurrence.get("tag_id"), citation)
        return UNKNOWN_CITATION
    reasons = _scrub(value)
    if reasons:
        logger.info("Downgraded tag %s: %s", occurrence.get("tag_id"),
                    ", ".join(reasons))
        return UNUSABLE_VALUE
    return None


def _answered(
    question: Mapping[str, Any],
    item: Mapping[str, Any] | None,
    citation: str,
) -> dict[str, Any]:
    value = _text(item, "value")
    if not value:
        # The model's narrower re-ask if it wrote one, otherwise the question
        # this tag is already carrying. Falling straight through to the
        # generic fallback would replace a question a person has already read
        # with a worse one, which reads as the assistant losing its place.
        return _question(question, NO_VALUE, proposal="", confidence=0.0,
                         reason=_text(item, "reason"),
                         question=_text(item, "question")
                         or _text(question, "question"))
    # The scrub warns about a person's own words; it never refuses them, and
    # for a tag the author marked to be asked it does not run at all -- D15
    # writes that reply verbatim, and an unlocked price is what "verbatim"
    # was decided to mean.
    warnings = _scrub(value) if question.get("kind") == "semantic" else []
    return _filled(question, value, source="user", confidence=1.0,
                   citation=citation, reason=_text(item, "reason"),
                   warnings=warnings)


def _filled(occurrence, value, *, source, confidence, citation, reason,
            warnings) -> dict[str, Any]:
    return {
        "tag_id": occurrence["tag_id"],
        "outcome": "filled",
        "value": value,
        "source": source,
        "confidence": confidence,
        "citation": citation,
        # D15. Python's own arithmetic over the locked rate card is the
        # complex flow's line items and totals, and it happens where the
        # PricingTable is loaded -- never here.
        "computed_by": None,
        "reason": reason,
        "question": None,
        "candidates": [],
        "asked_because": None,
        "warnings": warnings,
    }


def _question(occurrence, because, *, proposal, confidence, reason,
              question) -> dict[str, Any]:
    return {
        "tag_id": occurrence["tag_id"],
        "outcome": "question",
        "value": None,
        "source": None,
        "confidence": confidence,
        "citation": None,
        "computed_by": None,
        "reason": reason,
        "question": question or _fallback_question(occurrence),
        "candidates": _candidates(occurrence, proposal),
        "asked_because": because,
        "warnings": [],
    }


def _candidates(occurrence: Mapping[str, Any], proposal: str) -> list[str]:
    """What the salesperson can tap instead of typing (D5).

    The author's default first -- it is what the template says -- then the
    model's own proposal, which for an `ask_calculate` is the conclusion D15
    asks it to state. Neither is written until a person chooses it.
    """
    out: list[str] = []
    for candidate in (occurrence.get("default"), proposal):
        text = str(candidate).strip() if candidate else ""
        if text and text not in out:
            out.append(text)
    return out


def _fallback_question(occurrence: Mapping[str, Any]) -> str:
    """A model that was confident wrote no question; there must still be one.

    Quotes the tag as the author wrote it, because that is what the person
    will be looking at in the document.
    """
    raw = occurrence.get("raw") or "this tag"
    context = (occurrence.get("context") or "").strip()
    if context:
        return f'What should replace {raw} in "{context}"?'
    return f"What should replace {raw}?"


# --- checking the model's answer against the data it was given ---------------


_PATH_RE = re.compile(r"^([a-z_][a-z0-9_]*)((?:\[\d+\]|\.[a-z_][a-z0-9_]*)*)$")
_STEP_RE = re.compile(r"\[(\d+)\]|\.([a-z_][a-z0-9_]*)")


def _cites_a_dossier_fact(dossier: Mapping[str, Any], citation: str) -> bool:
    """Does this citation resolve to something actually in the dossier? (D14)

    Tolerant about the shape a model writes -- a trailing `": Sunil Menon,
    Principal"` for a human to read is kept out of the path, and a leading
    `dossier.` is ignored -- and unforgiving about the answer. `contacts[7]`
    against a client with two contacts is False, and so is a field that is
    present but empty: an absent email is not a fact about anybody.
    """
    path = citation.split(":", 1)[0].strip()
    if path.startswith("dossier."):
        path = path[len("dossier."):]
    head = _PATH_RE.match(path)
    if head is None:
        return False
    node: Any = dossier
    for key in (head.group(1), *_steps(head.group(2))):
        if isinstance(key, int):
            if not isinstance(node, list) or not 0 <= key < len(node):
                return False
        elif not isinstance(node, Mapping) or key not in node:
            return False
        node = node[key]
    return node is not None and node != "" and node != [] and node != {}


def _steps(tail: str) -> Iterable[Any]:
    for match in _STEP_RE.finditer(tail or ""):
        yield int(match.group(1)) if match.group(1) is not None else match.group(2)


def _scrub(value: str) -> list[str]:
    """Every reason this value must not go into a document, model-supplied.

    `brief` and `max_words` are switched off deliberately. A tag value is a
    value, not prose written to a brief, so the brief-echo check has nothing
    to compare against; and a semantic tag is allowed to hold a whole
    paragraph -- section 11 says a template that wants written prose puts a
    tag where it belongs -- so a word budget would refuse the feature.

    `allowed_amounts` is empty on purpose (D15). Every money-shaped figure in
    a value the model wrote is unlocked by definition: Python did not compute
    it from the rate card and no person typed it.
    """
    return fill_scrub.scrub(value, brief="", max_words=0, allowed_amounts=set())


# --- talking to the model ----------------------------------------------------


async def _generate(ctx, purpose: str, prompt: str) -> Any:
    return await get_model_layer().generate_json(
        purpose=purpose,
        tier=TIER_STRONG,
        org_id=getattr(ctx, "org_id", None),
        user_id=getattr(ctx, "user_id", None),
        messages=[{"role": "user", "content": prompt}],
        json_schema=_SCHEMA,
        temperature=0.2,
        max_tokens=4096,
    )


def _answers(data: Any, known: set[str]) -> dict[str, Mapping[str, Any]]:
    """The model's reply, keyed by tag, with anything invented thrown out.

    First answer wins. A model that contradicts itself about one tag has told
    us nothing about which of the two to believe, and taking the last would
    quietly prefer whichever it happened to write second.
    """
    out: dict[str, Mapping[str, Any]] = {}
    for item in (data or {}).get("resolutions", []) or []:
        if not isinstance(item, Mapping):
            continue
        tag_id = item.get("tag_id")
        if not isinstance(tag_id, str) or tag_id not in known:
            logger.info("Dropped resolution for unknown tag %r", tag_id)
            continue
        out.setdefault(tag_id, item)
    return out


def _turn_citation(asked: Sequence[Any], user_reply: str) -> str:
    """D14: a user value cites the turn in which the person said it."""
    return f'turn {len(asked or []) + 1}: "{_quote(user_reply)}"'


def _confidence(item: Mapping[str, Any] | None) -> float:
    """An unparseable confidence is not a confident one."""
    try:
        return float((item or {}).get("confidence"))
    except (TypeError, ValueError):
        return 0.0


def _text(item: Mapping[str, Any] | None, key: str) -> str:
    value = (item or {}).get(key)
    return str(value).strip() if value is not None else ""


# --- what the model is shown -------------------------------------------------


def _render_occurrences(occurrences: Sequence[Mapping[str, Any]]) -> str:
    """One line per tag: its id, its kind, and what tells it from its twins.

    The context is the whole point of the line. `<ask:1 Unit>` appears four
    times in the owner's real template, in four different rows, and the row
    label is what makes them four different questions rather than one.
    """
    lines = []
    for o in occurrences:
        line = f'{o["tag_id"]}  {o.get("kind")}  {o.get("raw")}'
        if o.get("context"):
            line += f'  |  in: {o["context"]}'
        if o.get("default"):
            line += f'  |  the author suggested: {o["default"]}'
        if o.get("duplicate_of"):
            line += f'  |  same literal as {o["duplicate_of"]}'
        lines.append(line)
    return "\n".join(lines)


def _render_questions(questions: Sequence[Mapping[str, Any]],
                      shown: set[tuple[str, str]] | frozenset = frozenset(),
                      reads_the_same: set[tuple[str, str]] | frozenset = frozenset(),
                      ) -> str:
    lines = []
    for q in questions:
        line = f'{q["tag_id"]}  {q.get("kind")}  {q.get("question")}'
        if q.get("context"):
            line += f'  |  in: {q["context"]}'
        if q.get("default"):
            line += f'  |  the author suggested: {q["default"]}'
        if _on_screen(q, shown, reads_the_same):
            line += f'  |  {ON_SCREEN}'
        lines.append(line)
    return "\n".join(lines)


def _render_resolutions(resolutions: Sequence[Mapping[str, Any]]) -> str:
    """Every value about to be written, as the person has just seen it.

    The row label goes in because that is how a person refers to a value --
    "the panel row", not a twelve-character id -- and the id goes in because
    that is the only thing the model may answer with.
    """
    lines = []
    for r in resolutions:
        about = r.get("context") or r.get("raw") or ""
        line = f'{r["tag_id"]}  {about}: {r.get("value")}'
        if r.get("raw"):
            line += f'  |  tag: {r["raw"]}'
        lines.append(line)
    return "\n".join(lines)


def _quote(text: str) -> str:
    quote = " ".join((text or "").split())
    if len(quote) > CITATION_QUOTE_CHARS:
        quote = quote[:CITATION_QUOTE_CHARS].rsplit(" ", 1)[0] + "..."
    return quote


def _render_dossier(dossier: Mapping[str, Any]) -> str:
    """Exactly the serialisation `client_dossier.size_of` measures.

    Not a cosmetic choice. `DOSSIER_CHAR_CEILING` is enforced against
    `json.dumps(dossier, default=str)`, so sending the model a differently
    serialised dossier -- indented, or with real characters where that one
    counts escapes -- would mean the ceiling bounds a string nobody sends.
    Pretty-printing 263 rows also buys the model nothing it cannot already
    parse, at a measurable cost in tokens on every turn of every fill.
    """
    return json.dumps(dossier, default=str)


def _render_omitted(dossier: Mapping[str, Any]) -> str:
    """D7: say what the ceiling dropped, and how much.

    A model told "the twelve oldest notes were omitted" can ask about them; a
    model handed a silently truncated dossier cannot.
    """
    omitted = (dossier or {}).get("omitted") or []
    if not omitted:
        return ""
    return ("\nWHAT WAS LEFT OUT OF THE DOSSIER, because it did not fit -- ask "
            "if you need it:\n" + json.dumps(omitted, default=str) + "\n")


_RELATIONS_PROMPT = """You are reading a contract's placeholders and saying
which of them are ARITHMETICALLY RELATED to one another.

You do NOT say what any of them is worth. You do not calculate anything. You
name tag ids and an operator, nothing else. Somebody else does the sums, from
the answers a human gives.

A relation is worth reporting only when it is stated or plainly implied by the
document itself -- an annual total that is a price multiplied by a number of
students, a set of instalments that add up to a total. If you are not sure two
tags relate, leave them out: a wrong relation produces a warning about a
correct contract, which is worse than no warning at all.

The placeholders:
{occurrences}

The document:
{document}

Return JSON: {{"relations": [
  {{"result": "<tag_id>", "op": "product" | "sum",
    "operands": ["<tag_id>", "<tag_id>", ...]}}
]}}
`op` must be exactly "product" or "sum". `operands` must name at least two
tag ids. Every tag id must be one of the ids listed above. Return
{{"relations": []}} if nothing in this document relates arithmetically."""


async def propose_relations(
    ctx,
    *,
    occurrences: Sequence[Mapping[str, Any]],
    document_text: str,
) -> list[dict[str, Any]]:
    """Which tags relate arithmetically -- tag ids and an operator only (D-E).

    **The model never supplies a figure here, and could not smuggle one in if
    it tried**: a relation is rebuilt from scratch out of `result`, `op` and
    `operands`, so any other key it returns is dropped on the floor. D15 says
    no number reaches a document unless Python computed it from a locked rate
    card or a person typed it, and this pass computes nothing at all -- it
    only says which of a person's own answers ought to agree.

    Every tag id is checked against the occurrence map, exactly as
    `resolve_tags` checks its own output and `docx_suggest._validate` checks
    anchors. An id the model invented is dropped and logged, because a model
    inventing ids is something an operator should be able to see.

    A relation with fewer than two operands, or an operator that is not
    `product` or `sum`, is dropped: there is nothing to check in the first and
    no way to check the second.
    """
    if not occurrences:
        return []

    known = {o.get("tag_id") for o in occurrences if isinstance(
        o.get("tag_id"), str)}
    prompt = _RELATIONS_PROMPT.format(
        occurrences=_render_occurrences(occurrences),
        document=document_text,
    )
    data = await _generate(ctx, "proposal.docx_tagfill_relations", prompt)

    relations: list[dict[str, Any]] = []
    proposed = data.get("relations") if isinstance(data, Mapping) else data
    if not isinstance(proposed, (list, tuple)):
        proposed = []
    for item in proposed:
        if not isinstance(item, Mapping):
            continue
        operator = item.get("op")
        result = item.get("result")
        operands = item.get("operands")
        if operator not in mou_arithmetic.OPERATORS:
            logger.info("Dropped relation with unknown operator %r", operator)
            continue
        if not isinstance(operands, (list, tuple)) or len(operands) < 2:
            logger.info("Dropped relation with too few operands: %r", operands)
            continue
        named = [result, *operands]
        unknown = [t for t in named if t not in known]
        if unknown:
            logger.info("Dropped relation naming unknown tag(s) %r", unknown)
            continue
        # Rebuilt, never passed through: whatever else the model attached --
        # a value, a total, a currency -- does not survive this line.
        relations.append({"result": result, "op": operator,
                          "operands": list(operands)})
    return relations
