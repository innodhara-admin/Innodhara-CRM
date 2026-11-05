# app/ai/agents/fill_tools.py
"""What a fill conversation SAYS -- shared by both document types.

`proposal_agent.py` is 1,081 lines and every one of these belongs equally to
an MOU: a round of questions, the suggestions offered as taps, and the D13
review are the same act whichever document is being filled. Sharing them is
what keeps the agent from doubling when A2 adds the MOU's tools.

**Moved verbatim from `proposal_agent`, and nothing here changed on the way.**
That is A1's whole contract: `tests/docx/test_fill_agent.py` and
`test_fill_build.py` are the proof, and they pass UNCHANGED -- including the
two that reach for `proposal_agent._group` and `proposal_agent._review_message`
by their old private names, which the import in `proposal_agent` still binds.

Nothing in here writes to the database or calls a model. These build the words;
`proposal_fill_service` owns the state machine and `docx_tagfill` owns the two
model calls.
"""
from __future__ import annotations

from typing import Any

from app.services import fill_scrub, proposal_fill_service

#: D5's round-settling answer. Offered as a tap so a salesperson who agrees
#: with the template's own suggestions can close six questions in one gesture.
ALL_DEFAULTS = "All the suggested values are fine"

#: The one answer that lets a document be written. Anything else the person
#: types is read as a correction, which is the safe way round: a sentence
#: nobody parsed correctly re-posts the list instead of shipping a document.
APPROVE = "Yes, these are all correct"

#: What each origin means to the person reading the review. D13 exists because
#: the 0.80 threshold is self-reported, so the list has to say plainly which
#: values nobody was asked about.
ORIGIN = {
    "ai": "worked out from the records",
    "user": "you told me",
    "default": "the template's own suggestion",
    "system": "from the record",
}


#: The scrubber's reasons are machine CODES; D-E's mismatch is a SENTENCE.
#:
#: Until A2 this rendered every warning with the price-drift wording, whatever
#: it actually said. For a proposal that was right -- the only warning a
#: proposal raises is D10's price fence. For an MOU it threw the arithmetic
#: finding away and told the reader about a rate card instead, which is the
#: one thing D-E exists to say: WHICH TWO of the person's own answers
#: disagree, on the screen where they are already looking.
_WARNING = {
    fill_scrub.REJECTION_PRICE:
        "it reads like a price, and prices normally come from the rate card",
    fill_scrub.REJECTION_MARKDOWN:
        "it carries markdown, which Word would print literally",
    fill_scrub.REJECTION_META:
        "it reads like an instruction to the assistant, not a value",
    fill_scrub.REJECTION_BRIEF_ECHO:
        "it restates the brief rather than answering it",
    fill_scrub.REJECTION_LENGTH:
        "it is longer than this placeholder expects",
    fill_scrub.REJECTION_BLANK: "it is empty",
}

#: What each document type's tools are called. The loop-breaker and the
#: "nothing is open" message both have to NAME a tool, and naming the wrong
#: one is how the last session's conversation looped: the model was told to
#: call something that does not exist for the document in hand.
TOOLS = {
    "proposal": {
        "noun": "proposal",
        "create": "create_proposal",
        "answer": "answer_proposal_questions",
        "show": "show_proposal_questions",
        "confirm": "confirm_proposal_values",
        "correct": "correct_proposal",
    },
    "mou": {
        "noun": "MOU",
        "create": "create_mou",
        "answer": "answer_mou_questions",
        "show": "show_mou_questions",
        "confirm": "confirm_mou_values",
        "correct": "correct_mou",
    },
}


def warning_line(warning: str) -> str:
    """One warning, in words.

    Anything that is not a known code is ALREADY a sentence and is rendered
    verbatim -- which is how D-E's "this reads Rs. 2,50,000, but Rs. 4,000 x
    75 is Rs. 3,00,000" reaches the person who has to decide about it.
    """
    return f"   (check this one -- {_WARNING.get(warning, warning)})"


def question_line(question: dict[str, Any]) -> dict[str, Any]:
    """One open question, as the model and the app both need to see it."""
    return {
        "tag_id": question["tag_id"],
        "question": question.get("question"),
        "about": question.get("context") or question.get("raw"),
        "suggested": question.get("candidates") or [],
    }


def round_message(waiting: list[dict[str, Any]], total: int,
                  lead_name: str) -> str:
    """One message carrying the whole round, numbered, each with its suggestion.

    The document's own words are quoted -- the row label a tag sits in -- so a
    person can find the cell being asked about without opening the file.
    """
    who = f" for {lead_name}" if lead_name else ""
    more = "" if total <= len(waiting) else (
        f" (there {'is' if total - len(waiting) == 1 else 'are'} "
        f"{total - len(waiting)} more after these)"
    )
    lines = [
        f"I have the document open{who} and I need "
        f"{len(waiting)} thing{'' if len(waiting) == 1 else 's'} "
        f"from you before I can fill it in{more}:",
        "",
    ]
    for number, question in enumerate(waiting, start=1):
        # D49. Four of the owner's asks carry no context label -- they sit
        # alone in a table cell whose column header the scanner does not reach
        # -- and introducing them by the tag itself gave them "<ask:75>: What
        # should replace <ask:75>?", which reads as broken. The section is
        # known, and is something a person can find in the document.
        about = (question.get("context") or question.get("section")
                 or question.get("raw") or "")
        text = question.get("question") or f"What goes in {question.get('raw')}?"
        suggestion = (question.get("candidates") or [None])[0]
        line = f"{number}. {about}: {text}" if about else f"{number}. {text}"
        if question.get("default_has_passed") and suggestion:
            # D48. The author's date has gone by, so the tap offers today and
            # the line says why -- naming today as "the template's suggestion"
            # would be putting words in their document's mouth.
            line += f" (the template's date has passed; today is {suggestion})"
        elif suggestion:
            line += f" (the template suggests {suggestion})"
        lines.append(line)
    if _anything_suggested(waiting):
        lines += [
            "",
            f'Answer in one message -- "two of each" is fine, or "{ALL_DEFAULTS}".',
        ]
    else:
        # Nothing in this round has a suggestion, so "all the suggested values
        # are fine" would settle nothing -- and offered anyway, it asked the
        # same address question seven times in a row (27 Sep 2026).
        lines += [
            "",
            "There is no suggestion for "
            + ("this one, so please type the answer." if len(waiting) == 1
               else "these, so please type the answers in one message."),
        ]
    return "\n".join(lines)


def _anything_suggested(waiting: list[dict[str, Any]]) -> bool:
    return any(c for q in waiting for c in (q.get("candidates") or []))


def round_candidates(waiting: list[dict[str, Any]]) -> list[str]:
    """What the app offers as one-tap answers.

    The suggestions the author wrote into the document, in the order they were
    asked, and then the answer that settles the whole round. Distinct: a
    template with `<ask:1 Unit>` in seven rows would otherwise offer the same
    chip seven times.
    """
    out: list[str] = []
    for question in waiting:
        for candidate in question.get("candidates") or []:
            if candidate and candidate not in out:
                out.append(candidate)
    # Only when there is something to accept: with no suggestion on screen
    # the tap settles nothing and the same question comes straight back.
    if out:
        out.append(ALL_DEFAULTS)
    return out


def review_message(session: Any) -> str:
    """Every value, its origin, and one question (D13).

    One message, not one per tag: twenty-five approval taps is not a review,
    it is a formality, and a formality is what lets a confidently wrong value
    through. The silently-filled ones are in here with the rest -- they are
    the reason this exists.
    """
    lines = [
        "Here is everything I am about to write into the document. Check it "
        "and tell me if anything is wrong -- nothing has been written yet.",
        "",
    ]
    for number, (row, count) in enumerate(
            group(proposal_fill_service.review_lines(session)), 1):
        origin = ORIGIN.get(row["source"], row["source"] or "unset")
        where = "" if count == 1 else f" (in {count} places)"
        lines.append(
            f'{number}. {row["about"]}{where}: {row["value"]}  [{origin}]')
        for warning in row["warnings"]:
            lines.append(warning_line(warning))
    lines += ["", f'Reply "{APPROVE}", or tell me what to change.']
    return "\n".join(lines)


def group(rows):
    """Collapse rows that say exactly the same thing, keeping the count.

    A client's name appears NINE times in the real YuviPep document -- once on
    the cover and twice in the footer of each of three sections -- and every
    one of them is its own tag with its own identity (D1). Listed one per line
    they are nine lines a reader's eye slides over, which is the formality
    this review exists to not be. Six of them also have no row label to tell
    them apart, so the lines are not merely repetitive, they are
    indistinguishable.

    Grouped only when the WHOLE row matches: the same place description, the
    same value, the same origin and the same warnings. Two tags that differ in
    any of those are two things to check and stay two lines.
    """
    grouped: list[list] = []
    index: dict[tuple, int] = {}
    for row in rows:
        key = (row["about"], row["value"], row["source"],
               tuple(row["warnings"]))
        if key in index:
            grouped[index[key]][1] += 1
            continue
        index[key] = len(grouped)
        grouped.append([row, 1])
    return [(row, count) for row, count in grouped]
