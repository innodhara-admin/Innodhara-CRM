# tests/docx/test_mou_rounds.py
"""What a person is ASKED, and in what order (D-D).

Two changes, and the first is a defect fix that the proposal flow was carrying
silently. `open_questions` sliced raw OCCURRENCES. `duplicate_of` is set by
raw literal in `tags.scan`, but nothing collapsed it on the asking path -- the
D13 review does collapse, in `proposal_agent._group`, and asking did not.

On a proposal that was invisible: the repeated literal there was `<School
Name>` nine times, which is `semantic` and filled silently, so it never became
a question. On the owner's MOU `<ask:75>` is FIVE occurrences of one literal
and `<ask:Yes>` is six, so round one would have asked the same question five
times in six slots and the person would have read it as broken.

Collapsing is safe because `apply_answers` already sends the model EVERY
outstanding question rather than the round shown (C3's ruling), so one reply
settles all five at once (D8).

The second change is grouping: a round is drawn from ONE section of the
document, so it is coherent -- Pricing Details, then Payment Terms -- rather
than mixing a signatory's name with an instalment date.
"""
import io

import pytest
from docx import Document

from app.ai.agents import fill_tools as ft
from app.services import proposal_fill_service as fs

pytestmark = pytest.mark.asyncio


def _sectioned() -> bytes:
    """Three headed sections, with one literal repeated ACROSS them.

    `<ask:75>` appears three times in two different sections, which is what
    tells collapsing apart from merely slicing.
    """
    doc = Document()
    doc.add_heading("Parties", level=2)
    doc.add_paragraph("Between <School Name> and YuviPep.")
    doc.add_paragraph("Represented by <School Signatory>.")

    doc.add_heading("Pricing Details", level=2)
    doc.add_paragraph("Price per student <ask:Rs. 4000>.")
    doc.add_paragraph("Students <ask:75>.")
    doc.add_paragraph("Total <ask_calculate:Rs. 3,00,000>.")

    doc.add_heading("Student Enrolment Structure", level=2)
    doc.add_paragraph("Minimum <ask:75> students required.")
    doc.add_paragraph("From AY 2027-28 a minimum of <ask:75> applies.")
    doc.add_paragraph("Grades <ask:1 to 10>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _footer_tagged() -> bytes:
    """A tag in a FOOTER, which belongs to no section of the body."""
    doc = Document()
    doc.add_heading("Parties", level=2)
    doc.add_paragraph("Between <School Name> and YuviPep.")
    doc.sections[0].footer.paragraphs[0].text = "<School Name>"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── the section label ───────────────────────────────────────────────────────
async def test_a_paragraph_takes_the_heading_above_it():
    labels = fs.section_labels(_sectioned())
    text = _walk_text(_sectioned())
    assert labels[text.index("Students <ask:75>.")] == "Pricing Details"
    assert labels[text.index("Grades <ask:1 to 10>.")] == \
        "Student Enrolment Structure"


async def test_a_paragraph_before_any_heading_is_not_given_one():
    doc = Document()
    doc.add_paragraph("Prepared for <School Name>.")
    doc.add_heading("Pricing Details", level=2)
    doc.add_paragraph("Students <ask:75>.")
    buf = io.BytesIO()
    doc.save(buf)
    labels = fs.section_labels(buf.getvalue())
    assert labels[0] != "Pricing Details"


async def test_a_tag_in_a_footer_never_inherits_a_body_heading():
    """47 of the owner's 240 MOU paragraphs are in headers and footers. They
    belong to no section, and giving them the nearest preceding BODY heading
    would be a lie about where they live."""
    labels = fs.section_labels(_footer_tagged())
    footer_ordinals = [o for o, lab in labels.items()
                       if lab in ("Header", "Footer")]
    assert footer_ordinals, "the footer paragraph was not labelled as one"
    assert all(labels[o] in ("Header", "Footer") for o in footer_ordinals)
    assert "Parties" not in {labels[o] for o in footer_ordinals}


# ── the collapse ────────────────────────────────────────────────────────────
def _session(docx_bytes):
    """A bare session object carrying only what open_questions reads."""
    from app.services.docx import tags as dtags

    labels = fs.section_labels(docx_bytes)
    tags = []
    for occ in dtags.scan(docx_bytes):
        row = occ.as_dict()
        row["section"] = labels.get(occ.ordinal, "")
        row["outcome"] = "question"
        tags.append(row)

    class _S:
        tags_json = tags
        # Section grouping is MOU-only: the proposal keeps D5's flat rounds
        # of six, which its golden test pins.
        document_type = "mou"
    return _S()


def _duplicates_in_the_first_section() -> bytes:
    """Two occurrences a person COULD NOT TELL APART, and two they could.

    `<ask:date of signing>` twice under an identical "Date:" lead-in is one
    question asked twice -- exactly the owner's MOU, where both signature
    dates carry the same context. `<ask:75>` twice under different sentences
    is two questions that merely share a default, and must stay two.
    """
    doc = Document()
    doc.add_heading("Signatures", level=2)
    doc.add_paragraph("Date: <ask:date of signing>")
    doc.add_paragraph("Date: <ask:date of signing>")
    doc.add_paragraph("Students <ask:75>.")
    doc.add_paragraph("Note: this pricing applies to <ask:75> students.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def test_two_occurrences_a_person_cannot_tell_apart_are_asked_once():
    session = _session(_duplicates_in_the_first_section())
    raws = [q["raw"] for q in fs.open_questions(session)]
    assert raws.count("<ask:date of signing>") == 1


async def test_two_occurrences_with_DIFFERENT_context_stay_two_questions():
    """The key is (raw, context), never raw alone.

    Measured on both real documents: the proposal's `<ask:1 Unit>` appears
    four times with the contexts "Magazine Rack", "Projector", "Audio and Mic
    System" and "First Aid Box", and the MOU's `<ask:Yes>` seven times, once
    per deliverables row. Collapsing on the literal would give all of them one
    answer -- the replace_token bug D1 exists to prevent, arriving at the
    question layer instead of the writing layer. It also broke six of the
    proposal flow's own tests, which is how it was caught.
    """
    session = _session(_duplicates_in_the_first_section())
    raws = [q["raw"] for q in fs.open_questions(session)]
    assert raws.count("<ask:75>") == 2


async def test_the_model_still_gets_EVERY_occurrence():
    """The collapse describes what a PERSON is shown, never what the model is
    given. apply_answers calls open_questions(limit=None) and hands the result
    to answer_round, so collapsing there would leave occurrences permanently
    unanswered -- a fill that can never finish."""
    session = _session(_duplicates_in_the_first_section())
    everything = fs.open_questions(session, limit=None)
    assert len(everything) == 4
    assert [q["raw"] for q in everything].count("<ask:date of signing>") == 2
    assert len({q["tag_id"] for q in everything}) == 4


async def test_a_round_is_drawn_from_one_section():
    asked = fs.open_questions(_session(_sectioned()))
    assert len({q["section"] for q in asked}) == 1


async def test_the_earliest_outstanding_section_is_asked_first():
    asked = fs.open_questions(_session(_sectioned()))
    assert asked[0]["section"] == "Parties"


async def test_a_round_is_still_capped(monkeypatch):
    """D5's six survives: collapsing changes WHICH questions a round holds,
    never how many a person is shown at once."""
    doc = Document()
    doc.add_heading("Deliverables", level=2)
    for i in range(9):
        doc.add_paragraph("Item %d <ask:value %d>." % (i, i))
    buf = io.BytesIO()
    doc.save(buf)
    assert len(fs.open_questions(_session(buf.getvalue()))) == 6
    assert len(fs.open_questions(_session(buf.getvalue()), limit=None)) == 9


async def test_nothing_outstanding_is_no_questions():
    session = _session(_sectioned())
    for row in session.tags_json:
        row["outcome"] = "filled"
    assert fs.open_questions(session) == []


def _walk_text(docx_bytes):
    from app.services.docx import text as dt

    doc = Document(io.BytesIO(docx_bytes))
    return [dt.node_text(p) for p in dt.walk_paragraphs(doc)]


async def test_a_table_header_cell_is_not_a_section():
    """The bug this test exists for was found by measuring, not by testing.

    The first version matched any style with "Head" in its name -- which is
    `TableHead1`, the style of every table HEADER CELL in the owner's MOU. All
    26 of them became their own section, so "Specifications", "Details",
    "First Instalment" and even "Date: <ask:date of signing>" each got a round
    to themselves and the fill fragmented into NINE rounds instead of seven.
    Every synthetic fixture here uses python-docx's add_heading, which yields
    `Heading2`, and a substring test matches that too -- so nothing caught it.
    """
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    doc = Document()
    doc.add_heading("Pricing Details", level=2)
    header_cell = doc.add_paragraph("Payable Annual Fees")
    pPr = header_cell._p.get_or_add_pPr()
    style = pPr.makeelement(f"{W}pStyle", {f"{W}val": "TableHead1"})
    pPr.append(style)
    doc.add_paragraph("Students <ask:75>.")
    buf = io.BytesIO()
    doc.save(buf)

    labels = fs.section_labels(buf.getvalue())
    assert labels[2] == "Pricing Details", (
        "a table header cell was treated as a section heading"
    )
    assert "Payable Annual Fees" not in set(labels.values())


# â”€â”€ a suggested date that has gone by (D48) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def test_a_round_says_when_the_templates_date_has_passed():
    """The tap offers today, so the line must not call today "the template's
    suggestion" -- that would be putting a date into the author's mouth that
    they never wrote. It says whose date has passed and what today is.
    """
    line = ft.round_message(
        [{"tag_id": "t1", "question": "What is the modified date?",
          "context": "Bookmarks: modified:", "candidates": ["11.9.2026"],
          "default_has_passed": True}], 1, "")
    assert "the template's date has passed" in line
    assert "today is 11.9.2026" in line
    assert "the template suggests" not in line


async def test_an_ordinary_suggestion_is_still_the_templates():
    line = ft.round_message(
        [{"tag_id": "t1", "question": "How many workshops?",
          "context": "Conduct a total of", "candidates": ["32"]}], 1, "")
    assert "the template suggests 32" in line


async def test_a_question_with_no_context_is_placed_by_its_section():
    """Four of the owner's asks carry no context label -- they are alone in
    a table cell whose column header the scanner does not reach -- so the
    round introduced them by the tag itself: "<ask:75>: What should replace
    <ask:75>?". The section the tag sits in is known and is something a
    person can find in the document.
    """
    line = ft.round_message(
        [{"tag_id": "t1", "raw": "<ask:75>", "context": "",
          "section": "Pricing Details", "candidates": ["75"],
          "question": "What should replace <ask:75>?"}], 1, "")
    assert "1. Pricing Details: What should replace" in line


async def test_a_question_with_a_context_still_uses_it():
    line = ft.round_message(
        [{"tag_id": "t1", "raw": "<ask:75>", "context": "Minimum Enrolment",
          "section": "Student Enrolment Structure", "candidates": ["75"],
          "question": "How many students?"}], 1, "")
    assert "1. Minimum Enrolment: How many students?" in line
