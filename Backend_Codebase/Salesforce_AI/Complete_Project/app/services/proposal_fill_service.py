# app/services/proposal_fill_service.py
"""The working memory of one in-progress fill (D6).

A fill is a conversation that has to remember twenty-five answers across a
dozen turns, and the chat transcript cannot hold it: `conversation.py` replays
twelve turns inside a six-thousand-character budget, prunes at sixty rows,
stores plain text only, and never replays tool calls or entity ids. So the
state is a row -- `ProposalFillSession` -- and the transcript stays what it is,
a record of what was said.

This module owns the status machine and nothing else owns any part of it:

    gathering -> (asking <-> gathering) -> reviewing -> ready -> built

`reviewing` is not a formality. The 0.80 threshold in D4 is self-reported and
uncalibrated, so **`ready` is reachable only from `reviewing`** and
`mark_ready` refuses from anywhere else (D13). A fill where the model happened
to be confident about every single tag still stops for a human -- that is the
case the review exists for, not the one it is a nuisance in.

The two model calls live in `app.ai.docx_tagfill` and are made from here
rather than from the agent, because section 7 describes each turn as one unit:
assemble, ask, record. The agent's job is to render questions and route
replies, and J1 stays small because this is where the turn is.
"""
from __future__ import annotations

import io
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import docx_tagfill
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.base import utcnow
from app.models.lead import Lead
from app.models.mou import MouDocument, MouRevision, MouStatus
from app.models.organisation import OrgSettings
from app.models.program import (
    PricingTable,
    Program,
    ProposalTemplate,
    ProposalTemplateDoc,
)
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import client_dossier, mou_arithmetic, storage
from app.services.docx import convert
from app.services.docx import index as ix
from app.services.docx import outline as dox
from app.services.docx import properties as props
from app.services.docx import tagfill
from app.services.docx import text as dt

logger = logging.getLogger(__name__)

#: D5, and the owner's decision on 2026-09-07. The Innovation Lab template
#: alone forces nineteen questions; nineteen round trips is not a conversation,
#: it is an interrogation. Six per round makes it four exchanges.
QUESTIONS_PER_ROUND = 6

#: Question 8, answered by the owner: a half-answered fill may sit for a week.
#: After that it is abandoned rather than resumed, because reviving week-old
#: half-answers the salesperson has forgotten giving is worse than starting
#: again -- and worse in a way nobody notices until the document is wrong.
FILL_SESSION_TTL_DAYS = 7

#: What to call the built thing when speaking to the person who asked for
#: it, with its article. A salesperson correcting a contract must not be told
#: about a proposal -- and "a MOU" reads as carelessly as the wrong noun does.
#:
#: Only the THREE messages this task owns are translated: the two in `build`
#: and the one in `_skipped_message`. The rest of the status machine still
#: says "proposal", because it is shared and rewording it is not this task's
#: to do; A2 owns what the agent says.
_NOUNS = {"proposal": ("proposal", "a proposal"),
          "mou": ("MOU", "an MOU")}


def _nouns(session: ProposalFillSession) -> tuple[str, str]:
    return _NOUNS.get(getattr(session, "document_type", "proposal"),
                      _NOUNS["proposal"])


def _is_mou(session: ProposalFillSession) -> bool:
    return getattr(session, "document_type", "proposal") == "mou"


#: A fill that can still be picked up. `built` and `abandoned` are terminal.
#: `ready` is resumable on purpose: a person who approved the review and then
#: said one more thing before the document was produced should reach the same
#: fill, not start a second one.
RESUMABLE = (FillStatus.GATHERING, FillStatus.ASKING,
             FillStatus.REVIEWING, FillStatus.READY)

#: Which template kind fills each document type. Both are tag-filled
#: Word documents, so the kind is what keeps a proposal fill from
#: opening on a contract.
SIMPLE_KINDS = {"proposal": "docx_simple", "mou": "mou_simple"}
NOT_SIMPLE = (
    "Template '{name}' v{version} is not filled by the assistant. Only a "
    "Word document uploaded as \"filled by the assistant\" has tags in it "
    "for this conversation to work through."
)
NO_TAGS = (
    "Template '{name}' v{version} has no tags in it, so there is nothing to "
    "fill. Re-upload the document with its placeholders written in."
)


async def open_session(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    lead_id: str,
    program_id: str,
    chat_session_id: str | None = None,
    template_id: str | None = None,
    document_type: str = "proposal",
) -> ProposalFillSession:
    """Section 7, turn 1: assemble everything, ask the model, store the row.

    The dossier and the occurrence map are written down before the model is
    called and are replayed verbatim on every later turn, so the answer to
    turn 7 is grounded in the same facts as turn 1.
    """
    template, doc_row, occurrences = await _simple_template(
        db, ctx, program_id, template_id, document_type=document_type)

    # Read once: the section labels and the document text both need it.
    source_bytes = storage.read_bytes(ctx.org_id, doc_row.source_path)
    sections = section_labels(source_bytes)

    session = ProposalFillSession(
        org_id=ctx.org_id, lead_id=lead_id, program_id=program_id,
        template_id=template.id, template_doc_id=doc_row.id,
        user_id=ctx.user_id, chat_session_id=chat_session_id,
        document_type=document_type,
        status=FillStatus.GATHERING,
        dossier_json=await client_dossier.build(db, ctx, lead_id, program_id),
        # D-D. Which section of the document each tag sits in, worked
        # out once here rather than every time a round is drawn.
        # tags.py is not touched: the label is added to the RECORD.
        tags_json=[dict(o, section=sections.get(o.get("ordinal"), ""))
                   for o in occurrences],
        asked_json=[],
    )
    # The model is called BEFORE the row is added, so the write transaction is
    # never held open across it. SQLite blocks every other writer for the life
    # of a write transaction, and a fill pass is seconds of model time; the
    # organisation's whole database must not wait on it. Nothing is lost by
    # waiting either: a first pass that fails leaves no half-built row for a
    # later turn to resume out of, and J1 simply opens a fresh fill.
    resolutions = await docx_tagfill.resolve_tags(
        ctx,
        dossier=session.dossier_json,
        document_text=_document_text(source_bytes),
        occurrences=session.tags_json,
    )
    _record(session, resolutions)

    # D-E. WHICH tags relate arithmetically -- tag ids and an operator, never
    # a figure. Asked once, here, and stored on the RESULT tag's own record so
    # it travels with that tag through corrections and rebuilds without any
    # extra bookkeeping. MOUs only: a proposal's ask_calculate is a number on
    # a page, an MOU's is a payment schedule, and there is no reason to spend
    # a model call on the former.
    if document_type == "mou":
        relations = await docx_tagfill.propose_relations(
            ctx,
            occurrences=session.tags_json,
            document_text=_document_text(source_bytes),
        )
        if relations:
            by_result = {r["result"]: r for r in relations}
            # Reassigned, never mutated: a SQLAlchemy JSON column tracks
            # assignment and not mutation (C3).
            session.tags_json = [
                dict(t, relation=by_result[t["tag_id"]])
                if t.get("tag_id") in by_result else t
                for t in session.tags_json
            ]

    db.add(session)
    await db.commit()
    return session


async def find_open(
    db: AsyncSession,
    ctx: OrgContext,
    *,
    lead_id: str,
    program_id: str,
    chat_session_id: str | None,
    document_type: str = "proposal",
) -> ProposalFillSession | None:
    """The fill this reply belongs to, or None to start a fresh one.

    Keyed on the chat session as well as the client and the programme, so
    "actually make it 3 units" an hour later lands on the right fill and not
    on a different salesperson's.

    A session past its time to live is **abandoned here rather than returned**.
    Sweeping it lazily on the read is what makes "never resumed silently" true
    without a scheduled job: the only path that could revive one is the path
    that retires it.
    """
    row = (await db.execute(
        select(ProposalFillSession).where(
            ProposalFillSession.org_id == ctx.org_id,
            # A fill is one person's conversation (section 5's `user_id`:
            # "whose conversation this is"). Two colleagues quoting the same
            # client and programme are having two different conversations, and
            # a chat id is minted by the client app -- not something to stake
            # one salesperson's half-answered document on.
            ProposalFillSession.user_id == ctx.user_id,
            ProposalFillSession.lead_id == lead_id,
            ProposalFillSession.program_id == program_id,
            # D-C: a proposal fill and an MOU fill for the same
            # client and programme are two different conversations.
            ProposalFillSession.document_type == document_type,
            ProposalFillSession.chat_session_id == chat_session_id,
            ProposalFillSession.status.in_(RESUMABLE),
        ).order_by(ProposalFillSession.updated_at.desc())
    )).scalars().first()
    return await _fresh_or_abandon(db, row)


async def find_for_chat(
    db: AsyncSession, ctx: OrgContext, *,
    chat_session_id: str | None, document_type: str = "proposal"
) -> ProposalFillSession | None:
    """The fill this conversation is in the middle of, whatever it is about.

    `find_open` needs the client and the programme; a person answering "two of
    each" has named neither, and asking the model to remember them across
    turns is how the wrong client's document gets filled. The chat is the
    thing that is actually known at that moment.

    **A conversation with no id matches nothing.** Every one-off command has a
    null `chat_session_id`, so keying on the chat alone would let an unrelated
    command answer somebody else's half-finished fill -- the one lookup in
    this module where a null is a wildcard rather than a value.
    """
    if not chat_session_id:
        return None
    row = (await db.execute(
        select(ProposalFillSession).where(
            ProposalFillSession.org_id == ctx.org_id,
            ProposalFillSession.user_id == ctx.user_id,
            ProposalFillSession.chat_session_id == chat_session_id,
            ProposalFillSession.document_type == document_type,
            ProposalFillSession.status.in_(RESUMABLE),
        ).order_by(ProposalFillSession.updated_at.desc())
    )).scalars().first()
    return await _fresh_or_abandon(db, row)


async def find_correctable(
    db: AsyncSession, ctx: OrgContext, *,
    chat_session_id: str | None, document_type: str = "proposal"
) -> ProposalFillSession | None:
    """The finished proposal this conversation could still correct.

    Built, not resumable -- `find_for_chat` deliberately excludes it, because
    a finished fill must not be picked up as if it were half-answered. This is
    the narrower question: is there a document we could write again?

    Bounded by the same window as resuming, and for the same reason. The
    dossier a correction reasons over was assembled when the fill was opened;
    past the window it describes a client who has moved on, and a fresh
    proposal is the honest answer. Unlike `find_for_chat` this does NOT
    abandon what it rejects -- the proposal is real and its record stays.
    """
    if not chat_session_id:
        return None
    # D-C: "is there a document we could write again?" is asked of a
    # different column per type. An MOU fill never sets proposal_id,
    # so keying on the wrong one makes a built MOU permanently
    # uncorrectable and answering every question afresh the only route.
    written_id = (ProposalFillSession.mou_id if document_type == "mou"
                  else ProposalFillSession.proposal_id)
    row = (await db.execute(
        select(ProposalFillSession).where(
            ProposalFillSession.org_id == ctx.org_id,
            ProposalFillSession.user_id == ctx.user_id,
            ProposalFillSession.chat_session_id == chat_session_id,
            ProposalFillSession.document_type == document_type,
            ProposalFillSession.status == FillStatus.BUILT,
            written_id.isnot(None),
        ).order_by(ProposalFillSession.updated_at.desc())
    )).scalars().first()
    if row is None:
        return None
    if row.updated_at < utcnow() - timedelta(days=FILL_SESSION_TTL_DAYS):
        return None
    return row


async def reopen_for_correction(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    correction: str,
) -> ProposalFillSession:
    """Change one value in a finished document, and put it back to the review.

    **D13 is not bypassed by a correction.** The changed value goes back
    through `reviewing`, so the person sees the whole list again before the
    document is written a second time -- the same gate a first build passes,
    for the same reason.

    A document the client already has is refused. Once it is sent they are
    holding it, and rewriting the file behind that would leave our record
    disagreeing with what they were sent; an amendment is a new document, not
    a quiet edit of the old one. For an MOU that is not a policy but the whole
    of `MouStatus`: there is no `accepted`, because accepting a contract is a
    signature on paper and this system cannot observe one.
    """
    is_mou = _is_mou(session)
    noun = _nouns(session)[0]
    written_id = session.mou_id if is_mou else session.proposal_id

    if session.status != FillStatus.BUILT or not written_id:
        raise ValidationFailedError(
            f"There is no finished {noun} here to correct."
        )
    document = await db.get(MouDocument if is_mou else Proposal, written_id)
    if document is None:
        raise NotFoundError(f"That {noun} is gone; create a new one.")
    # An MOU has two states and a proposal has four, so the "gone out" test is
    # per type. `sent_at` is checked for both because a send that recorded the
    # timestamp and failed to move the status still means the client has it.
    gone_out = (MouStatus.SENT,) if is_mou else _SENT_ONWARDS
    if document.sent_at is not None or document.status in gone_out:
        raise ValidationFailedError(
            f"That {noun} has already been sent, so I will not rewrite the "
            f"document the client is holding. Ask me to create a new {noun} "
            "for this client and we can set the values differently."
        )

    changed = await docx_tagfill.revise(
        ctx,
        dossier=session.dossier_json,
        resolutions=session.tags_json,
        correction=correction,
    )
    if not changed:
        return session

    session.asked_json = list(session.asked_json) + [{
        "round": len(session.asked_json) + 1,
        "correction": correction,
        "at": utcnow().isoformat(),
    }]
    _record(session, _without_row_label(session.tags_json, changed))
    # `_record` lands it in `reviewing` because a correction fills rather than
    # asks, which is exactly where it has to be: `ready` is reachable from
    # nowhere else, and the document is written from `ready`.
    await db.commit()
    return session


#: A proposal at or past these has left the building.
_SENT_ONWARDS = ("sent", "accepted", "declined")


async def is_simple_flow(
    db: AsyncSession, ctx: OrgContext, program_id: str,
    template_id: str | None = None,
) -> bool:
    """Would a proposal for this programme be filled through the assistant?

    False when there is no template at all, deliberately: the ordinary build
    path raises its own "ask your Org Admin to add one", and this must not
    replace a message that is already right with one about tags.
    """
    template = await _current(db, ctx, program_id, template_id)
    return template is not None and getattr(
        template, "kind", "markdown") == "docx_simple"


async def is_mou_flow(
    db: AsyncSession, ctx: OrgContext, program_id: str,
    template_id: str | None = None,
) -> bool:
    """Would an MOU for this programme be filled through the assistant?

    Beside `is_simple_flow` and false in the same case for the same reason:
    where there is no template at all the ordinary path raises its own "ask
    your Org Admin to add one", and this must not replace a message that is
    already right with one about tags.

    A programme may carry a current proposal template and a current MOU
    template at once (D-B), so this asks about the MOU one specifically. A
    programme with only a proposal template is NOT an MOU flow, which is what
    keeps "draw up the contract" from opening a fill on the proposal.
    """
    template = await _current(db, ctx, program_id, template_id,
                              document_type="mou")
    return template is not None and getattr(
        template, "kind", "markdown") == SIMPLE_KINDS["mou"]


async def _fresh_or_abandon(
    db: AsyncSession, row: ProposalFillSession | None
) -> ProposalFillSession | None:
    if row is None:
        return None
    if row.updated_at < utcnow() - timedelta(days=FILL_SESSION_TTL_DAYS):
        logger.info("Abandoning fill session %s: untouched since %s",
                    row.id, row.updated_at)
        await abandon(db, row)
        return None
    return row


async def _today(db: AsyncSession, ctx: OrgContext):
    """Today where this organisation is (D48). Never `date.today()`, which
    answers for whichever machine the server happens to be on."""
    from app.core import clock  # noqa: PLC0415 -- avoids an import cycle

    return clock.today(await clock.org_zone(db, ctx.org_id))


async def apply_answers(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    user_reply: str,
) -> ProposalFillSession:
    """Section 7, turns 2..n: what the reply settled, and what it did not.

    The model is given every outstanding question, not only the six the person
    was shown. One sentence often answers more than it was asked -- "two of
    each" settles every quantity in the document -- and D8 wants the
    duplicates of a literal resolved together whichever round they surfaced
    in. Nothing reaches the document without the D13 review either way.
    """
    _must_be_resumable(session)
    outstanding = open_questions(session, limit=None)
    if not outstanding:
        return session

    resolutions = await docx_tagfill.answer_round(
        ctx,
        dossier=session.dossier_json,
        open_questions=outstanding,
        user_reply=user_reply,
        # Before the append, so C2 numbers this turn and not the next one.
        asked=session.asked_json,
        # The round the person was just SHOWN: the same pure slice `_round`
        # drew it from, over tags nothing has changed since. "All the
        # suggested values are fine" is about these and nothing else
        # (owner, 11 September).
        on_screen=open_questions(session),
        # D48. The fill had no clock at all, so a suggestion the author wrote
        # in a document could not be told from one that has gone by. The
        # ORGANISATION's today, not the server's.
        today=await _today(db, ctx),
    )
    session.asked_json = list(session.asked_json) + [{
        "round": len(session.asked_json) + 1,
        "reply": user_reply,
        "asked": [q["tag_id"] for q in outstanding],
        "at": utcnow().isoformat(),
    }]
    _record(session, resolutions)
    await db.commit()
    return session


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _style_of(paragraph) -> str:
    node = paragraph.find(f"{_W}pPr/{_W}pStyle")
    return (node.get(f"{_W}val") or "") if node is not None else ""


def _place_of(paragraph, body) -> str:
    """Where this paragraph lives: the body, a header, or a footer."""
    node = paragraph
    while node is not None:
        if node is body:
            return "body"
        tag = node.tag.split("}")[-1]
        if tag == "hdr":
            return "Header"
        if tag == "ftr":
            return "Footer"
        node = node.getparent()
    return "body"


def section_labels(docx_bytes: bytes) -> dict[int, str]:
    """Walk ordinal -> the section heading the paragraph sits under (D-D).

    Not a heuristic. Measured on the owner's MOU, the document carries real
    Word heading styles that land exactly on the boundaries a coherent round
    wants: Heading1Center at ordinals 24 and 89, Heading2 at 90 (Operation
    Terms), 112 (Agreed Deliveries and Offers), 149 (Pricing Details), 159
    (Student Enrolment Structure), 169 (Payment Terms) and 181 (YuviPep Bank
    Details). The style is read from w:pPr/w:pStyle, so "Heading 2", "Title"
    and a house style like "Heading1Center" are all recognised.

    A paragraph in a header or a footer belongs to NO section and is labelled
    "Header" or "Footer". 47 of that document's 240 paragraphs are there, and
    giving them the nearest preceding BODY heading would be a lie about where
    they live -- and would put a footer's client name in the middle of a round
    about payment terms.

    A paragraph before the first heading keeps the empty label rather than
    borrowing one from below it.
    """
    from docx import Document  # noqa: PLC0415 -- heavy, and only needed here

    document = Document(io.BytesIO(docx_bytes))
    body = document.element.body
    labels: dict[int, str] = {}
    current = ""
    for ordinal, paragraph in enumerate(dt.walk_paragraphs(document)):
        place = _place_of(paragraph, body)
        if place != "body":
            labels[ordinal] = place
            continue
        style = _style_of(paragraph)
        text = dt.node_text(paragraph).strip()
        # A HEADING style, not merely a style with "Head" in its name.
        # Measured on the owner's MOU: `TableHead1` is the style of
        # every table HEADER CELL, and a substring test matched all 26
        # of them -- so "Specifications", "Details", "First Instalment"
        # and even "Date: <ask:date of signing>" each became their own
        # section and the fill fragmented into NINE rounds instead of
        # four. The document's real headings are Heading1Center,
        # Heading2 and Title.
        if text and (style.startswith("Heading")
                     or style.startswith("Title")):
            current = text[:60]
        labels[ordinal] = current
    return labels


def open_questions(
    session: ProposalFillSession, *, limit: int | None = QUESTIONS_PER_ROUND
) -> list[dict[str, Any]]:
    """The questions still to ask, at most one round of them (D5).

    Pure, and deliberately so: J1 needs to count what is outstanding without
    touching the database, and a round is a slice of a list rather than a
    thing that has to be stored and kept in step.
    """
    waiting = [t for t in session.tags_json if t.get("outcome") == "question"]
    # Everything outstanding, uncollapsed -- what the MODEL is given.
    # apply_answers calls this with limit=None and hands the result
    # straight to answer_round, so collapsing HERE would show the model
    # one of the five <ask:75> and leave the other four permanently
    # unanswered. Six is how many a PERSON is shown (D5); what the
    # model gets is every outstanding question (C3, D8). Different
    # questions, and conflating them is a fill that never finishes.
    if limit is None:
        return waiting

    # D-D. One question per distinct literal. `duplicate_of` is set by
    # raw literal in tags.scan and the D13 review already collapses on
    # it; the asking path did not, so a round of six would have asked
    # about <ask:75> five times. Safe because one reply settles the
    # whole group through the uncollapsed list above.
    seen: set[tuple[str, str]] = set()
    distinct: list[dict[str, Any]] = []
    for tag in waiting:
        # (raw, context), NEVER raw alone. Measured on both real documents:
        # the proposal's `<ask:1 Unit>` appears four times with contexts
        # "Magazine Rack", "Projector", "Audio and Mic System" and "First Aid
        # Box" -- FOUR questions that merely share a default -- and the MOU's
        # `<ask:Yes>` appears seven times, once per deliverables row. Keying
        # on the literal alone would give all of them one answer, which is
        # the replace_token bug D1 exists to prevent, resurfacing at the
        # question layer. Context is the row label joined to the text before
        # the tag (D9), so two occurrences match only when a person could not
        # tell the questions apart -- the same rule proposal_agent._group
        # applies to the D13 review.
        key = (tag.get('raw') or '', tag.get('context') or '')
        if key in seen:
            continue
        seen.add(key)
        distinct.append(tag)
    if not distinct:
        return []

    # D-D. One SECTION per round, so a round is coherent -- Pricing
    # Details, then Payment Terms -- instead of mixing a signatory's
    # name with an instalment date. The earliest outstanding section
    # goes first, which is document order.
    #
    # MOUs ONLY, and that is a scope decision rather than a convenience.
    # D5 chose flat rounds of six for the proposal deliberately, and the
    # tagged proposal has sixteen tags in one section -- grouping buys it
    # nothing and would turn its first round from six questions into two,
    # which its golden test pins. D-D was raised because forty-odd
    # occurrences across eight headed sections is a different problem from
    # sixteen. The spec says the proposal flow's behaviour does not change;
    # this is where that is enforced.
    if getattr(session, "document_type", "proposal") != "mou":
        return distinct[:limit]
    section = distinct[0].get('section')
    return [t for t in distinct if t.get('section') == section][:limit]


def arithmetic_warnings(session: ProposalFillSession) -> dict[str, str]:
    """tag_id -> the sentence saying its arithmetic does not hold (D-E).

    Computed from the relations stored at open time and THE PERSON'S OWN
    ANSWERS. Nothing here produces a value: D15 says no number reaches a
    document unless Python computed it from a locked rate card or a person
    typed it, and this computes neither -- it only says two of a person's
    answers disagree, on the one screen where they are already looking.

    Silent when a figure cannot be read with certainty, which is most of the
    time: a spurious warning on a negotiated figure teaches the reader to
    dismiss the warnings.
    """
    relations = [t["relation"] for t in session.tags_json if t.get("relation")]
    if not relations:
        return {}
    values = {t["tag_id"]: t.get("value") for t in session.tags_json}
    return {m["result"]: m["message"]
            for m in mou_arithmetic.check(relations, values)}


async def acknowledge_arithmetic(
    db: AsyncSession, session: ProposalFillSession
) -> ProposalFillSession:
    """Record that a person has been shown a mismatch and meant it anyway.

    D-E reports; it never substitutes, and it must never refuse TWICE. A
    figure that does not equal price x students is a normal thing for a
    contract to contain -- a rounded total, a discount nobody wrote down, a
    number that was negotiated in a room. So the check earns exactly one
    interruption. Refusing again would teach the reader to dismiss the
    warnings, which destroys the only thing they are for.
    """
    standing = arithmetic_warnings(session)
    if not standing:
        return session
    # Reassigned, never mutated: a SQLAlchemy JSON column tracks assignment
    # and not mutation (C3), so editing the dicts under it would leave the
    # acknowledgement unwritten and the next approval would be refused again.
    session.tags_json = [
        dict(tag, arithmetic_ack=True) if tag.get("tag_id") in standing else tag
        for tag in session.tags_json
    ]
    await db.commit()
    return session


def unacknowledged_arithmetic(session: ProposalFillSession) -> dict[str, str]:
    """The mismatches this person has not yet stood behind. Empty is clear."""
    acked = {tag["tag_id"] for tag in session.tags_json
             if tag.get("arithmetic_ack")}
    return {tag_id: message
            for tag_id, message in arithmetic_warnings(session).items()
            if tag_id not in acked}


def review_lines(session: ProposalFillSession) -> list[dict[str, Any]]:
    """Every value about to be written, and where each one came from (D13).

    **Every** value, including the ones filled silently at high confidence --
    that is the whole point. The 0.80 threshold decides whether the assistant
    asks a question; this decides whether the document is written, and the
    first draft of the plan conflated the two. A model that is confidently
    wrong about the client's name would otherwise reach the client unchallenged.
    """
    arithmetic = arithmetic_warnings(session)
    return [
        {
            "tag_id": tag["tag_id"],
            "about": tag.get("context") or tag.get("raw"),
            "value": tag.get("value"),
            "source": tag.get("source"),
            "citation": tag.get("citation"),
            # D-E joins D10's price fence on the SAME field, so the review
            # renders one kind of warning rather than two.
            "warnings": list(tag.get("warnings") or [])
            + ([arithmetic[tag["tag_id"]]] if tag["tag_id"] in arithmetic
               else []),
            "reviewed": bool(tag.get("reviewed")),
        }
        for tag in session.tags_json
    ]


async def apply_correction(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    correction: str,
) -> ProposalFillSession:
    """Section 5: a correction made during the review returns it to `gathering`.

    Distinct from `apply_answers` because the two are different acts. An
    answer settles a question that was asked; a correction changes a value the
    person has already been shown, and nothing is open to map it onto -- so it
    needs its own model call over the filled values.

    Section 5 draws this as a hop through `gathering`. In practice `_record`
    lands it straight back in `reviewing`, because a correction FILLS values
    rather than opening questions -- and `reviewing` is where it has to end up
    anyway, since the review runs again on the result (section 7) and `ready`
    is reachable from nowhere else. The status is left alone when the
    correction changed nothing, so the caller posts the same list again rather
    than pretending to have acted.
    """
    _must_be_resumable(session)
    if session.status == FillStatus.READY:
        raise ValidationFailedError(
            "This proposal has already been approved. Ask me to create it "
            "again if something needs to change."
        )
    changed = await docx_tagfill.revise(
        ctx,
        dossier=session.dossier_json,
        resolutions=session.tags_json,
        correction=correction,
    )
    if not changed:
        return session
    _record(session, _without_row_label(session.tags_json, changed))
    await db.commit()
    return session


def _without_row_label(tags: list[dict[str, Any]],
                       changed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A corrected value that repeats its own row label, without the label.

    Replayed with the real model on 12 Oct 2026: correcting "Annual Price Per
    Student" to "₹2,500 net" came back, two runs in three, as "Annual Price Per
    Student: ₹2,500 net" -- and the value is written into the cell beside that
    very label. Only an exact "<label>:" prefix is removed, so a value that
    merely begins with the same words is left as the person approved it.
    """
    context = {t["tag_id"]: (t.get("context") or "").strip() for t in tags}
    out = []
    for resolution in changed:
        label = context.get(resolution.get("tag_id"), "")
        value = resolution.get("value")
        if label and isinstance(value, str):
            head, sep, rest = value.partition(":")
            if sep and rest.strip() and head.strip().casefold() == label.casefold():
                resolution = {**resolution, "value": rest.strip()}
        out.append(resolution)
    return out


async def mark_ready(
    db: AsyncSession, session: ProposalFillSession
) -> ProposalFillSession:
    """D13. The only door to `ready`, and it opens only from `reviewing`.

    Asserted as a transition rather than an outcome because the mistake this
    prevents is a caller that has the values and skips the review -- which is
    precisely the state a confident model produces, and precisely the one the
    review exists for.
    """
    if session.status != FillStatus.REVIEWING:
        raise ValidationFailedError(
            "This proposal has not been through its review yet. Every value, "
            "including the ones filled without asking, is shown to you before "
            "anything is written into the document."
        )
    session.tags_json = [dict(t, reviewed=True) for t in session.tags_json]
    session.status = FillStatus.READY
    await db.commit()
    return session


async def build(
    db: AsyncSession, ctx: OrgContext, session: ProposalFillSession
) -> Proposal | MouDocument:
    """Write the values into a copy of the document and record what was built.

    **Which document is decided here and nowhere else.** Everything above this
    point -- the status machine, the rounds, the review, the correction path --
    is shared, because a contract and a proposal are filled in exactly the same
    way. Only the writing differs, and D-A says how: an MOU gets its own row,
    with no `total_amount`, no `line_items` and no `project_id`, so that no
    aggregate written later can pick it up and advance a deal that is already
    closed.

    Reachable only from `ready`, which is reachable only from `reviewing`
    (D13). By the time anything here runs, a human has seen every value --
    including the ones the model filled without asking.

    **A document with anything skipped is not shipped.** `apply_tags` refuses a
    write whose tag has moved rather than putting a value in the wrong
    sentence, and it reports rather than raises so one bad entry does not cost
    the other twenty-four theirs. That makes the report this function's to
    act on: a document missing a value, or carrying a literal `<ask:6 Units>`,
    is worse than no document at all. For a CONTRACT it is worse again:
    a proposal that reads like a template is embarrassing, and an MOU that
    does is a signature block over an unfilled term.
    """
    is_mou = _is_mou(session)
    noun, a_noun = _nouns(session)
    written_id = session.mou_id if is_mou else session.proposal_id

    # Asked FIRST, and the order matters: a built session is no longer `ready`,
    # so checking the status first turns a repeated approval -- a double tap, a
    # retried request, a model that calls the tool twice -- into "this has not
    # been approved yet", which is both wrong and confusing. The document that
    # exists is the answer to being asked for it again.
    # Asked as "is this one already BUILT", not "does it have a document": a
    # fill reopened for a correction still points at what it built and must be
    # allowed to write it again. Before corrections existed the two questions
    # had the same answer.
    if session.status == FillStatus.BUILT and written_id:
        existing = await db.get(MouDocument if is_mou else Proposal, written_id)
        if existing is not None:
            return existing
    if session.status != FillStatus.READY:
        raise ValidationFailedError(
            f"This {noun} has not been approved yet. Every value is shown to "
            "you before anything is written into the document."
        )

    doc_row = await db.get(ProposalTemplateDoc, session.template_doc_id)
    template = await db.get(ProposalTemplate, session.template_id)
    if doc_row is None or template is None:
        raise NotFoundError(
            f"The template this {noun} was being filled from is gone. "
            "Re-upload it and start again."
        )

    result = tagfill.apply_tags(
        storage.read_bytes(ctx.org_id, doc_row.source_path),
        session.tags_json,
        {t["tag_id"]: str(t.get("value") or "") for t in session.tags_json
         if t.get("outcome") == "filled"},
    )
    if result["skipped"]:
        raise ValidationFailedError(
            _skipped_message(result["skipped"], noun, a_noun))

    docx_bytes = result["docx"]
    if ix.detect_bytes(docx_bytes) == "static":
        # A static contents page carries page numbers that only LibreOffice
        # can re-measure, and the replacements have just changed the text they
        # count. Exactly what docx_proposal_service does after its own fill.
        docx_bytes = ix.refresh_static(docx_bytes)

    if is_mou:
        docx_bytes = await _mou_properties(db, session, docx_bytes)
        previous = (await db.get(MouDocument, session.mou_id)
                    if session.mou_id else None)
        document = (
            await _write_mou(db, ctx, session, template, docx_bytes)
            if previous is None else
            await _rewrite_mou(db, ctx, session, previous, docx_bytes))
        session.mou_id = document.id
    else:
        # Last, after refresh_static, for the reason _mou_properties gives.
        # Only tag text in the properties is replaced: the owner's proposal
        # templates bind the cover and every footer to dc:title "<School
        # name>", which no paragraph walk reaches (12 Oct 2026).
        docx_bytes = props.fill_literals(
            docx_bytes, props.values_from(session.tags_json))
        previous = (await db.get(Proposal, session.proposal_id)
                    if session.proposal_id else None)
        document = (
            await _write_proposal(db, ctx, session, template, docx_bytes)
            if previous is None else
            await _rewrite_proposal(db, ctx, session, previous, docx_bytes))
        session.proposal_id = document.id
    session.status = FillStatus.BUILT
    await db.commit()
    return document


async def abandon(
    db: AsyncSession, session: ProposalFillSession
) -> ProposalFillSession:
    session.status = FillStatus.ABANDONED
    await db.commit()
    return session


def _skipped_message(skipped: list[dict[str, Any]], noun: str = "proposal",
                     a_noun: str = "a proposal") -> str:
    names = ", ".join(
        f'{s.get("raw")} ({s.get("reason")})' for s in skipped[:6]
    )
    more = "" if len(skipped) <= 6 else f" and {len(skipped) - 6} more"
    return (
        f"{len(skipped)} placeholder{'' if len(skipped) == 1 else 's'} could "
        f"not be written into the document: {names}{more}. Nothing has been "
        f"created -- {a_noun} that still reads like a template is worse than "
        f"no {noun}. Ask me to start this one again."
    )


async def _write_proposal(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    template: ProposalTemplate,
    docx_bytes: bytes,
) -> Proposal:
    """The Proposal row, written exactly as the complex flow writes one.

    The commercials still come from the locked `PricingTable` through
    `compute_totals` -- unchanged from the day the first proposal shipped
    (D10, D15). The document shows whatever the author's tags say; the RECORD
    carries the locked figures, and no number in it was produced by a model.
    """
    from app.services import audit_service, proposal_service

    lead = await db.get(Lead, session.lead_id)
    program = await db.get(Program, session.program_id)
    pricing, line_items, total, currency = await _commercials(db, ctx, session)

    proposal = Proposal(
        org_id=ctx.org_id,
        lead_id=session.lead_id,
        program_id=session.program_id,
        title=f"{program.name} Proposal - {lead.name}",
        template_id=template.id,
        template_version=template.version,
        pricing_table_id=None if pricing is None else pricing.id,
        pricing_version=None if pricing is None else pricing.version,
        content_md=dox.project_text(dox.parse(docx_bytes)),
        variables={"client_name": lead.name, "program_name": program.name},
        line_items=line_items,
        total_amount=total,
        currency=currency,
        filled_json=filled_json(session),
        template_kind="docx_simple",
        created_by=ctx.user_id,
    )
    db.add(proposal)
    await db.flush()
    proposal.docx_path = storage.save_bytes(
        ctx.org_id, storage.CATEGORY_PROPOSALS,
        f"{program.name}_{lead.name}.docx", docx_bytes,
    )
    _attach_pdf(proposal, program, lead, docx_bytes)

    await proposal_service._save_revision(
        db, proposal, instruction="Filled from the document's own tags",
        edited_by=ctx.user_id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="proposal.created",
        entity_type="proposal", entity_id=proposal.id,
        detail={"lead_id": session.lead_id, "program_id": session.program_id,
                "total": total, "fill_session_id": session.id},
    )
    return proposal


async def _commercials(
    db: AsyncSession, ctx: OrgContext, session: ProposalFillSession
) -> tuple[Any, list[dict[str, Any]], float, str]:
    """The rate card, the line items and the total -- or an empty commercial.

    A rate card is OPTIONAL here (owner, 2026-09-08). An offering whose prices
    live inside its own document has nothing to put in one, and requiring it
    made the salesperson meet "No pricing table for this program" at the end
    of a conversation they had already answered every question in. Nothing the
    CLIENT sees depended on it either: every figure in a simple-flow document
    comes from a tag and the person's own answer, never from the PricingTable.

    Where a rate card DOES exist it is still used, and still through
    `compute_totals` -- D10 and D15 are unchanged, and no number in the record
    was produced by a model. Where it does not, the record carries an empty
    commercial rather than a missing one: `total_amount` 0.0 and no line
    items, which the Android screen already renders as a dash because
    `totalAmount` and `pricingVersion` are boxed and null-checked there.
    """
    pricing = (await db.execute(select(PricingTable).where(
        PricingTable.org_id == ctx.org_id,
        PricingTable.program_id == session.program_id,
        PricingTable.is_current.is_(True),
    ).order_by(PricingTable.version.desc()))).scalars().first()

    if pricing is None:
        settings_row = (await db.execute(select(OrgSettings).where(
            OrgSettings.org_id == ctx.org_id))).scalar_one_or_none()
        currency = (settings_row.currency if settings_row else None) or "INR"
        logger.info("Proposal for programme %s has no rate card; the document's "
                    "own tags carry its prices", session.program_id)
        return None, [], 0.0, currency

    # The rate card is RECORDED but not CLAIMED. Which rate card was current
    # when this proposal was made is worth knowing, so the link stays; its
    # figures are not this proposal's, so they do not become its commercials.
    #
    # In the complex flow they would be: there the rate card is written into
    # the document's own price table, so the total IS the document's total. In
    # this flow the document's price table is filled by tags only (section 10,
    # question 4) and the rate card never reaches the page. Copying it into
    # the record put "Total amount: 2200" in front of a salesperson whose
    # document said "Rs. 15,00,000/- to Rs. 25,00,000/-" -- the unit price of
    # a per-student line wearing a total's label, because the item carried no
    # default_quantity and the quantity fell back to 1. Reported 8 September.
    #
    # What this proposal is worth is stated in the document, in the words the
    # person approved, and `filled_json` carries it for the app to show. A
    # number nobody computed is not improved by being displayed.
    return pricing, [], 0.0, (pricing.currency or "INR")


async def _rewrite_proposal(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    proposal: Proposal,
    docx_bytes: bytes,
) -> Proposal:
    """Write a corrected document into the proposal that already exists.

    The same row, so the id the salesperson already has keeps working, and a
    revision so the record remembers what the document used to say -- that
    history is the only place the old wording survives, and the app reads it.

    The files are written anew rather than overwritten: someone may already
    have downloaded the old one, and a path that quietly changes underneath a
    reader is worse than a second file. `pdf_path` is cleared FIRST, so a
    conversion that fails leaves no PDF at all rather than yesterday's PDF
    beside today's document.
    """
    from app.services import audit_service, proposal_service

    lead = await db.get(Lead, session.lead_id)
    program = await db.get(Program, session.program_id)
    instruction = "Corrected in the chat"
    for entry in reversed(session.asked_json or []):
        if entry.get("correction"):
            instruction = entry["correction"]
            break

    proposal.content_md = dox.project_text(dox.parse(docx_bytes))
    proposal.filled_json = filled_json(session)
    proposal.docx_path = storage.save_bytes(
        ctx.org_id, storage.CATEGORY_PROPOSALS,
        f"{program.name}_{lead.name}.docx", docx_bytes,
    )
    proposal.pdf_path = None
    _attach_pdf(proposal, program, lead, docx_bytes)

    await proposal_service._save_revision(
        db, proposal, instruction=instruction, edited_by=ctx.user_id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="proposal.corrected",
        entity_type="proposal", entity_id=proposal.id,
        detail={"fill_session_id": session.id, "instruction": instruction},
    )
    return proposal


def _attach_pdf(document, program, lead, docx_bytes: bytes, *,
                filename: str | None = None, noun: str = "proposal") -> None:
    """Produce the PDF now, and do not lose the document if LibreOffice will not.

    Section 7 asks for the PDF at build time, and a person who has just
    approved a review expects a finished document rather than one that
    materialises later. But the document itself is already written and stored
    by this point, and `proposal_email_service` converts on demand and skips
    the work when `pdf_path` is already set -- so a converter that is down
    costs a retry at send time, while raising here would throw away an
    approved document over it. **An approved CONTRACT is not cheaper to lose.**

    Shared by both document types rather than copied, so the rule that a
    converter failure is never fatal has exactly one place to be got wrong.
    """
    try:
        document.pdf_path = storage.save_bytes(
            document.org_id, storage.CATEGORY_PROPOSALS,
            filename or f"{program.name}_{lead.name}.pdf",
            convert.docx_to_pdf(docx_bytes),
        )
    except Exception:  # noqa: BLE001 -- never fatal to an approved document
        logger.exception(
            "Could not produce the PDF for %s %s; the document is saved "
            "and the send path will convert it", noun, document.id)


async def _mou_properties(
    db: AsyncSession, session: ProposalFillSession, docx_bytes: bytes
) -> bytes:
    """Fill the document's PROPERTIES, which no tag reached (amendment K).

    `scan` and `apply_tags` walk paragraphs; properties are not paragraphs. So
    the tagging script neutralised the owner's thirteen client-specific
    metadata values to tag text -- the template names nobody -- and until this
    ran, NOTHING filled them back in. Without it every MOU ships a literal
    "<School Name>" in Word's title bar, in File > Info and in Explorer's
    preview pane, which is exactly where the owner found the previous school's
    name in a document this project had called clean.

    Run LAST, after `refresh_static`: LibreOffice rewrites the whole package
    when it re-measures a contents page, so anything written before it is
    written into bytes that are about to be replaced.

    The title and subject come from the LEAD and the PROGRAMME rather than
    from a filled tag. They are what this document is, not a guess about it,
    and they are right even for a template that never tagged its properties.
    """
    lead = await db.get(Lead, session.lead_id)
    program = await db.get(Program, session.program_id)
    return props.fill(
        docx_bytes,
        props.values_from(session.tags_json),
        title=lead.name,
        subject=program.name,
    )


async def _write_mou(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    template: ProposalTemplate,
    docx_bytes: bytes,
) -> MouDocument:
    """The MouDocument row -- and NOT a Proposal, which is the whole of D-A.

    No commercials are computed and none are stored, because there are no
    columns to store them in. That is not an oversight carried over from
    `_write_proposal`: `_commercials` exists there to record which rate card
    was current, and an MOU has no rate card, no total and no line items by
    construction, so that no aggregate can pick it up. The last session
    shipped "Total amount: 2200" for a document reading Rs. 15,00,000 by
    carrying that machinery across without asking whether its premise came
    too.

    A revision is saved for the FIRST build as well as for corrections, so
    revision 1 is the contract as it was originally written and the wording
    before the Nth correction is revision N.
    """
    from app.services import audit_service

    lead = await db.get(Lead, session.lead_id)
    program = await db.get(Program, session.program_id)
    stem = f"{program.name}_{lead.name}_MOU"

    mou = MouDocument(
        org_id=ctx.org_id,
        lead_id=session.lead_id,
        program_id=session.program_id,
        title=f"{program.name} MOU - {lead.name}",
        status=MouStatus.DRAFT,
        template_id=template.id,
        template_version=template.version,
        content_md=dox.project_text(dox.parse(docx_bytes)),
        filled_json=filled_json(session),
        created_by=ctx.user_id,
    )
    db.add(mou)
    await db.flush()
    mou.docx_path = storage.save_bytes(
        ctx.org_id, storage.CATEGORY_PROPOSALS, f"{stem}.docx", docx_bytes)
    _attach_pdf(mou, program, lead, docx_bytes,
                filename=f"{stem}.pdf", noun="MOU")

    await _save_mou_revision(
        db, mou, instruction="Filled from the document's own tags",
        edited_by=ctx.user_id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="mou.created",
        entity_type="mou", entity_id=mou.id,
        detail={"lead_id": session.lead_id, "program_id": session.program_id,
                "fill_session_id": session.id},
    )
    return mou


async def _rewrite_mou(
    db: AsyncSession,
    ctx: OrgContext,
    session: ProposalFillSession,
    mou: MouDocument,
    docx_bytes: bytes,
) -> MouDocument:
    """Write a corrected contract into the MOU that already exists.

    The same row, so the id the salesperson is already holding keeps working,
    and a revision so the record remembers what the contract used to say --
    that history is the only place the old wording survives, because the file
    is written anew rather than overwritten. Someone may already have
    downloaded the old one, and a path that quietly changes underneath a
    reader is worse than a second file.

    **`pdf_path` is cleared FIRST**, so a conversion that fails leaves no PDF
    at all rather than the PDF made BEFORE the correction sitting beside the
    corrected document -- which is the version a person would then send.
    """
    from app.services import audit_service

    lead = await db.get(Lead, session.lead_id)
    program = await db.get(Program, session.program_id)
    stem = f"{program.name}_{lead.name}_MOU"
    instruction = "Corrected in the chat"
    for entry in reversed(session.asked_json or []):
        if entry.get("correction"):
            instruction = entry["correction"]
            break

    mou.content_md = dox.project_text(dox.parse(docx_bytes))
    mou.filled_json = filled_json(session)
    mou.docx_path = storage.save_bytes(
        ctx.org_id, storage.CATEGORY_PROPOSALS, f"{stem}.docx", docx_bytes)
    mou.pdf_path = None
    _attach_pdf(mou, program, lead, docx_bytes,
                filename=f"{stem}.pdf", noun="MOU")

    await _save_mou_revision(db, mou, instruction=instruction,
                             edited_by=ctx.user_id)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="mou.corrected",
        entity_type="mou", entity_id=mou.id,
        detail={"fill_session_id": session.id, "instruction": instruction},
    )
    return mou


async def _save_mou_revision(
    db: AsyncSession, mou: MouDocument, *,
    instruction: str | None, edited_by: str | None,
) -> None:
    """What this contract says, kept before the next correction replaces it.

    Numbered exactly as `proposal_service._save_revision` numbers a proposal's:
    counted from what is already stored rather than from a column on the row,
    so two corrections racing cannot both claim revision 2 silently.
    """
    count = (await db.execute(select(func.count(MouRevision.id)).where(
        MouRevision.mou_id == mou.id))).scalar_one()
    db.add(MouRevision(
        org_id=mou.org_id,
        mou_id=mou.id,
        revision_no=count + 1,
        instruction=instruction,
        content_md=mou.content_md,
        filled_json=mou.filled_json,
        edited_by=edited_by,
    ))


def filled_json(session: ProposalFillSession) -> list[dict[str, Any]]:
    """What went into this proposal, for the Android card.

    The same six keys `docx.fill.apply` produces for the complex flow --
    renaming one would turn a working card into a blank one -- plus
    `computed_by` and `citation`, which Gson ignores on an older app and a
    newer one can show.

    `source` distinguishes where a value actually came from. A value the
    person supplied that is word for word the template author's own suggestion
    is recorded as `default`: they chose it, but the words are the template's,
    and "the salesperson wrote this" would overstate it. `system` does not
    occur in this flow -- every value is resolved by the model, answered by a
    person, or taken from the author's default -- and it is in the vocabulary
    because the complex flow uses it for the fields it resolves in code.
    """
    out = []
    for tag in session.tags_json:
        source = tag.get("source")
        if source == "user" and tag.get("default") and \
                str(tag.get("value")) == str(tag.get("default")):
            source = "default"
        out.append({
            "key": tag["tag_id"],
            "kind": tag.get("kind"),
            "source": source or "unfilled",
            "text": str(tag.get("value") or ""),
            "brief": tag.get("reason") or "",
            "anchor": tag.get("context") or tag.get("raw"),
            "computed_by": tag.get("computed_by"),
            "citation": tag.get("citation"),
        })
    return out


# --- what the row is made of -------------------------------------------------


def _record(session: ProposalFillSession, resolutions: list[dict[str, Any]]) -> None:
    """Merge a pass's resolutions into the occurrence map, and set the status.

    `tags_json` is reassigned rather than mutated in place: it is a SQLAlchemy
    JSON column, which tracks assignment and not mutation, so editing the
    dicts under it would leave the change unwritten at commit and the fill
    would forget the answer it had just been given.

    An occurrence the pass did not speak about keeps whatever it had, so an
    answer from round 1 survives round 2.
    """
    by_id = {r["tag_id"]: r for r in resolutions}
    merged = []
    for tag in session.tags_json:
        resolution = by_id.get(tag["tag_id"])
        entry = dict(tag)
        if resolution is not None:
            entry.update(resolution)
            # D13: a value is not reviewed until a human has actually seen it,
            # and a value that has just changed has not been seen since.
            entry["reviewed"] = False
        entry.setdefault("reviewed", False)
        merged.append(entry)

    # D-E. An acknowledgement belongs to the figures it was given for. If this
    # pass touched a result or ANY of its operands, the arithmetic the person
    # stood behind is not the arithmetic in front of them now -- exactly the
    # rule `reviewed` follows three lines above, for exactly the same reason.
    touched = set(by_id)
    if touched:
        merged = [dict(tag, arithmetic_ack=False)
                  if _relation_touches(tag, touched) else tag
                  for tag in merged]
    session.tags_json = merged
    session.status = (
        FillStatus.ASKING if open_questions(session, limit=None)
        else FillStatus.REVIEWING
    )


def _relation_touches(tag: dict[str, Any], touched: set[str]) -> bool:
    """Did this pass change anything the tag's arithmetic rests on?

    The result's own value counts as well as its operands: a total that has
    just been retyped needs checking against the operands again, and it is the
    result that carries the acknowledgement.
    """
    relation = tag.get("relation")
    if not relation:
        return False
    return (tag.get("tag_id") in touched
            or bool(set(relation.get("operands") or []) & touched))


async def _simple_template(
    db: AsyncSession, ctx: OrgContext, program_id: str,
    template_id: str | None, *, document_type: str = "proposal",
) -> tuple[ProposalTemplate, ProposalTemplateDoc, list[dict[str, Any]]]:
    """The current template of this document type, its document row
    and its tags. A programme may carry one of each (D-B)."""
    template = await _current(db, ctx, program_id, template_id,
                              document_type=document_type)
    if template is None:
        raise NotFoundError(
            "No proposal template for this program. Ask your Org Admin to add one."
        )
    expected = SIMPLE_KINDS.get(document_type, "docx_simple")
    if getattr(template, "kind", "markdown") != expected:
        raise ValidationFailedError(
            NOT_SIMPLE.format(name=template.name, version=template.version))

    doc_row = (await db.execute(select(ProposalTemplateDoc).where(
        ProposalTemplateDoc.template_id == template.id,
        ProposalTemplateDoc.org_id == ctx.org_id,
    ))).scalar_one_or_none()
    if doc_row is None:
        raise NotFoundError(
            f"Template '{template.name}' v{template.version} is a document "
            "template but its file is missing. Re-upload it."
        )
    occurrences = (doc_row.plan_json or {}).get("tags") or []
    if not occurrences:
        raise ValidationFailedError(
            NO_TAGS.format(name=template.name, version=template.version))
    return template, doc_row, occurrences


async def _current(
    db: AsyncSession, ctx: OrgContext, program_id: str,
    template_id: str | None, *, document_type: str = "proposal",
) -> ProposalTemplate | None:
    """The template a proposal for this programme would be built from.

    The same selection `proposal_service._current_template` makes -- named
    version if asked for, otherwise the current one, highest version first --
    so the two paths can never disagree about which template a request means.
    """
    query = select(ProposalTemplate).where(
        ProposalTemplate.org_id == ctx.org_id,
        ProposalTemplate.program_id == program_id,
        # D-B: a proposal fill must not open on the MOU template, nor
        # an MOU fill on the proposal one.
        ProposalTemplate.document_type == document_type,
    )
    query = (query.where(ProposalTemplate.id == template_id) if template_id
             else query.where(ProposalTemplate.is_current.is_(True)))
    return (await db.execute(
        query.order_by(ProposalTemplate.version.desc())
    )).scalars().first()


def _document_text(docx_bytes: bytes) -> str:
    """The document as the model reads it -- the same walk the tags came from.

    Not the outline projection. The projection is built from top-level blocks
    and would leave out a tag in a text box, and a model asked to reason about
    a tag it cannot see in the document is being set up to invent one. This
    walk is `docx.tags.scan`'s own, so every occurrence in the map is by
    construction a substring of what the model is shown.

    Structure is not lost by flattening it: an occurrence carries the row
    label of its table cell as its context (D9), which is the part that tells
    four `<ask:1 Unit>` apart.
    """
    from docx import Document  # noqa: PLC0415 -- heavy, and only needed here

    document = Document(io.BytesIO(docx_bytes))
    lines = [dt.node_text(p) for p in dt.walk_paragraphs(document)]
    return "\n".join(line for line in lines if line.strip())


def _must_be_resumable(session: ProposalFillSession) -> None:
    if session.status not in RESUMABLE:
        raise ValidationFailedError(
            "That proposal fill is finished. Ask me to create the proposal "
            "again and we will start a fresh one."
        )
