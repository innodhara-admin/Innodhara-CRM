# tests/docx/test_tags.py
"""The simple-flow tag grammar and scanner (Task A1).

The numbers pinned against the owner's own tagged document are measurements,
not targets. If a run disagrees with one, the document or the scanner changed
and that is a finding to report -- never a pin to edit.
"""
import io

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.services.docx import tags as tg
from app.services.docx import text as dt

W_TC = qn("w:tc")

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
TAGGED_SAMPLE = SAMPLES_DIR / "Innovation Lab Template (tagged).docx"


def walk_of(docx_bytes: bytes) -> list:
    doc = Document(io.BytesIO(docx_bytes))
    return [p for root in dt.all_roots(doc) for p in dt.iter_paragraphs(root)]


def assert_offsets_are_truthful(docx_bytes: bytes, occurrences) -> None:
    """Every (ordinal, start, end) must actually name its own `raw`.

    This is the invariant the writer in A3 depends on: it re-reads the live
    text at those offsets and refuses the write if `raw` is not there.
    """
    walk = walk_of(docx_bytes)
    for occ in occurrences:
        assert dt.node_text(walk[occ.ordinal])[occ.start:occ.end] == occ.raw


# --- the grammar ------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected_default",
    [
        ("ask:1 Unit", "1 Unit"),
        ("ask: (10 units)", "(10 units)"),
        ("ask:(50 Nos)", "(50 Nos)"),
        ("ask :3 Nos", "3 Nos"),
        ("ASK:4 Units", "4 Units"),
        ("Ask:  1 3D Printer with filaments", "1 3D Printer with filaments"),
    ],
)
def test_ask_is_case_insensitive_and_whitespace_tolerant(body, expected_default):
    assert tg.parse_tag(body) == ("ask", expected_default)


def test_ask_calculate_is_not_read_as_ask():
    kind, default = tg.parse_tag(
        "ask_calculate:Rs. 15,00,000/- to Rs. 25,00,000/-net (including GST)"
    )
    assert kind == "ask_calculate"
    assert default == "Rs. 15,00,000/- to Rs. 25,00,000/-net (including GST)"


def test_a_default_keeps_its_brackets_and_punctuation_verbatim():
    assert tg.parse_tag("ask:(3 Nos)") == ("ask", "(3 Nos)")


@pytest.mark.parametrize("body", ["School Name", "Name", "Ph no. yuvipep", "asking price"])
def test_anything_else_is_semantic_and_has_no_default(body):
    assert tg.parse_tag(body) == ("semantic", None)


def test_ask_with_an_empty_default_still_always_asks():
    """`<ask:>` is an `ask` with no default, not a semantic tag called 'ask:'.

    Reading it as semantic would let the model fill silently a tag the author
    explicitly marked to be asked, which is what D4 exists to prevent.
    """
    assert tg.parse_tag("ask:") == ("ask", None)
    assert tg.parse_tag("ask_calculate:  ") == ("ask_calculate", None)


# --- what the regex accepts and refuses -------------------------------------


def found(text: str) -> list[str]:
    return [m.group(0) for m in tg.TAG_RE.finditer(text)]


@pytest.mark.parametrize(
    "markup", ["</p>", "</b>", "<p/>", "<br />", "</div>", "<hr/>"]
)
def test_unambiguous_markup_is_not_a_tag(markup):
    """A closing or self-closing form is never a sensible placeholder name."""
    assert found(markup) == []


@pytest.mark.parametrize("body", ["price", "name", "address", "b", "br"])
def test_a_bare_word_is_a_tag(body):
    """The owner's decision on 7 September 2026, overriding plan section 3.

    The old rule refused any bare lowercase word so that HTML pasted into
    Word could not become a placeholder. Measured across all five real
    documents it caught NOTHING -- there is no HTML inside a .docx, only
    the literal characters if someone pastes web text as plain text -- while
    it silently dropped `<price>`, `<name>` and `<address>`, which are
    exactly the placeholders an author would write.

    The two mistakes are not equally priced. A tag wrongly refused is silent
    and reaches the client as a literal `<price>`. A pasted `<b>` wrongly
    accepted shows up in the upload summary and costs one question a human
    dismisses -- and D13 already puts a human in front of every value. So
    this errs towards asking, and `b` and `br` are in this list on purpose.
    """
    assert found(f"<{body}>") == [f"<{body}>"]


def test_an_empty_body_is_not_a_tag():
    assert found("nothing <> here") == []


def test_a_newline_inside_the_body_is_not_a_tag():
    assert found("<School\nName>") == []


def test_a_body_of_exactly_the_cap_is_a_tag_and_one_more_is_not():
    at_cap = "<School " + ("x" * (tg.MAX_BODY - 7)) + ">"
    over_cap = "<School " + ("x" * (tg.MAX_BODY - 6)) + ">"
    assert len(at_cap) == tg.MAX_BODY + 2
    assert found(at_cap) == [at_cap]
    assert found(over_cap) == []


def test_a_long_bare_word_is_a_tag_like_any_other():
    """The 150-character cap is the only thing bounding a bare word now."""
    at_cap = "<" + "x" * tg.MAX_BODY + ">"
    assert found(at_cap) == [at_cap]
    assert found("<" + "x" * (tg.MAX_BODY + 1) + ">") == []


def test_a_nested_bracket_yields_only_the_well_formed_inner_tag():
    """`<Foo<Bar>>` is not a tag, but the `<Bar>` inside it is a real one.

    Pinned so the behaviour is a decision rather than an accident: the outer
    body contains a `<`, which section 3 rejects; the inner body does not.
    """
    assert found("<Foo<Bar>>") == ["<Bar>"]


def test_an_uppercase_single_word_tag_survives_the_html_rule():
    assert found("<Name>") == ["<Name>"]


# --- the scanner ------------------------------------------------------------


def test_a_tag_fragmented_across_runs_is_found_whole(tagged_fragmented_docx):
    occurrences = tg.scan(tagged_fragmented_docx)
    assert [o.raw for o in occurrences] == ["<School Name>"]
    assert occurrences[0].kind == "semantic"
    assert occurrences[0].default is None
    assert_offsets_are_truthful(tagged_fragmented_docx, occurrences)


def test_a_tag_in_a_text_box_is_found(tagged_textbox_docx):
    occurrences = tg.scan(tagged_textbox_docx)
    assert sorted(o.raw for o in occurrences) == ["<Name>", "<School Name>"]
    assert_offsets_are_truthful(tagged_textbox_docx, occurrences)


def test_tags_in_a_header_and_a_footer_are_found(tagged_header_docx):
    occurrences = tg.scan(tagged_header_docx)
    assert sorted(o.raw for o in occurrences) == [
        "<Ph no. yuvipep>", "<School Name>", "<website yuv>",
    ]
    assert_offsets_are_truthful(tagged_header_docx, occurrences)


def test_no_markup_in_a_document_becomes_a_placeholder(tagged_rejects_docx):
    assert tg.scan(tagged_rejects_docx) == []


def test_two_tags_in_one_cell_get_their_own_ids_and_offsets(tagged_table_docx):
    occurrences = tg.scan(tagged_table_docx)
    in_cell = [o for o in occurrences if o.raw in ("<ask: (10 units)>", "<ask:(3 Nos)>")]
    assert len(in_cell) == 2
    assert in_cell[0].ordinal == in_cell[1].ordinal
    assert in_cell[0].tag_id != in_cell[1].tag_id
    assert in_cell[0].start < in_cell[1].start
    assert_offsets_are_truthful(tagged_table_docx, occurrences)


def test_the_same_literal_in_two_rows_is_two_questions(tagged_table_docx):
    units = [o for o in tg.scan(tagged_table_docx) if o.raw == "<ask:1 Unit>"]
    assert len(units) == 2
    assert units[0].tag_id != units[1].tag_id
    assert units[0].duplicate_of is None
    assert units[1].duplicate_of == units[0].tag_id


def test_a_tag_in_a_cell_takes_its_row_label_as_context(tagged_table_docx):
    by_context = {o.context: o.raw for o in tg.scan(tagged_table_docx)}
    assert by_context["Magazine Rack"] == "<ask:1 Unit>"
    assert by_context["Projector"] == "<ask:1 Unit>"


def test_several_tags_in_one_cell_are_told_apart_by_what_precedes_them(tagged_table_docx):
    """The row label alone cannot separate two tags that share a cell.

    In the real document one cell carries four, so the context also carries the
    text immediately before the tag -- the item it belongs to.
    """
    contexts = {o.raw: o.context for o in tg.scan(tagged_table_docx)
                if o.raw in ("<ask: (10 units)>", "<ask:(3 Nos)>")}
    assert contexts["<ask: (10 units)>"] == "Experimenters Hub - CRO, Safety Glass"
    assert contexts["<ask:(3 Nos)>"] == (
        "Experimenters Hub - CRO, Safety Glass , Drill Machine"
    )


def test_a_body_tag_takes_the_words_around_it_as_context(tagged_fragmented_docx):
    occurrence = tg.scan(tagged_fragmented_docx)[0]
    assert occurrence.context == "Welcome to"


def test_a_context_is_bounded_however_big_the_row_label_is():
    """Context is stored per occurrence and re-sent in every prompt.

    A first cell holding a nested table or a paragraph of prose would otherwise
    put hundreds of characters into all 25 records of a template.
    """
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Lab equipment " * 60
    table.cell(0, 1).text = "<ask:1 Unit>"
    buf = io.BytesIO()
    doc.save(buf)

    occurrence = tg.scan(buf.getvalue())[0]
    assert len(occurrence.context) <= 2 * tg.CONTEXT_LEAD + 3
    assert occurrence.context.startswith("Lab equipment")


def test_the_scan_is_deterministic_across_two_reads(tagged_table_docx):
    first = [o.as_dict() for o in tg.scan(tagged_table_docx)]
    second = [o.as_dict() for o in tg.scan(tagged_table_docx)]
    assert first == second


def test_occurrences_come_back_in_document_order(tagged_table_docx):
    occurrences = tg.scan(tagged_table_docx)
    keys = [(o.ordinal, o.start) for o in occurrences]
    assert keys == sorted(keys)


def test_as_dict_carries_the_fields_the_fill_plan_stores(tagged_table_docx):
    record = tg.scan(tagged_table_docx)[0].as_dict()
    assert set(record) == {
        "tag_id", "kind", "raw", "default", "ordinal",
        "start", "end", "context", "duplicate_of",
    }


# --- the owner's real document ----------------------------------------------

golden = pytest.mark.skipif(
    not TAGGED_SAMPLE.exists(), reason="tagged sample not present"
)


@pytest.fixture(scope="module")
def tagged_sample_bytes() -> bytes:
    if not TAGGED_SAMPLE.exists():
        pytest.skip("tagged sample not present")
    return TAGGED_SAMPLE.read_bytes()


@golden
def test_the_owners_document_yields_the_measured_occurrences(tagged_sample_bytes):
    """Measured 2026-09-07 against sha256 595cda9f1b93b2dc (plan section 2.1)."""
    occurrences = tg.scan(tagged_sample_bytes)
    assert len(occurrences) == 25
    assert len({o.raw for o in occurrences}) == 20


@golden
def test_nineteen_of_them_are_in_table_cells(tagged_sample_bytes):
    """Plan section 2.2: 6 in body paragraphs, 19 in table cells."""
    walk = walk_of(tagged_sample_bytes)
    in_cell = 0
    for occ in tg.scan(tagged_sample_bytes):
        node = walk[occ.ordinal].getparent()
        while node is not None and node.tag != W_TC:
            node = node.getparent()
        in_cell += node is not None
    assert in_cell == 19


@golden
def test_twenty_one_paragraphs_carry_a_tag_and_one_carries_four(tagged_sample_bytes):
    per_paragraph: dict[int, int] = {}
    for occ in tg.scan(tagged_sample_bytes):
        per_paragraph[occ.ordinal] = per_paragraph.get(occ.ordinal, 0) + 1
    assert len(per_paragraph) == 21
    assert max(per_paragraph.values()) == 4


@golden
def test_one_unit_appears_four_times_and_is_four_questions(tagged_sample_bytes):
    """The reason identity is per occurrence and never per literal (D1).

    `docx_text.replace_token` would have written one answer into all four.
    """
    units = [o for o in tg.scan(tagged_sample_bytes) if o.raw == "<ask:1 Unit>"]
    assert len(units) == 4
    assert len({o.tag_id for o in units}) == 4
    assert [o.context for o in units] == [
        "Magazine Rack", "Projector", "Audio and Mic System", "First Aid Box:",
    ]


@golden
def test_the_three_families_are_counted_as_the_plan_measured_them(tagged_sample_bytes):
    """Plan section 2.1: 6 plain semantic, 18 ask, 1 ask_calculate."""
    kinds: dict[str, int] = {}
    for occ in tg.scan(tagged_sample_bytes):
        kinds[occ.kind] = kinds.get(occ.kind, 0) + 1
    assert kinds == {"semantic": 6, "ask": 18, "ask_calculate": 1}


@golden
def test_the_ask_calculate_default_survives_verbatim(tagged_sample_bytes):
    calc = [o for o in tg.scan(tagged_sample_bytes) if o.kind == "ask_calculate"]
    assert len(calc) == 1
    assert calc[0].default == (
        "Rs. 15,00,000/- to Rs. 25,00,000/-net (including GST)"
    )
    assert calc[0].context == "YuviPep Futuristic Innovation Lab (YFIL)"


@golden
def test_every_offset_in_the_real_document_names_its_own_tag(tagged_sample_bytes):
    assert_offsets_are_truthful(tagged_sample_bytes, tg.scan(tagged_sample_bytes))


@golden
def test_the_untagged_original_yields_nothing(tagged_sample_bytes):
    """`Innovation Lab Template.docx` is the same document before tagging.

    A zero-tag document is what B1 must refuse in the simple flow, so the
    scanner has to report zero rather than guess.
    """
    original = SAMPLES_DIR / "Innovation Lab Template.docx"
    if not original.exists():
        pytest.skip("untagged original not present")
    assert tg.scan(original.read_bytes()) == []


def test_a_serial_number_column_is_not_used_as_the_row_label():
    """A row numbered 1..10 must be labelled by what it NAMES, not by its
    number.

    Measured on the owner's MOU: the deliverables table numbers its rows in
    column 0 and names the deliverable in column 1, so taking the first cell
    gave seven `<ask:Yes>` the labels "2", "4", "6", "7", "8", "9", "10" --
    seven questions a person cannot tell apart, which is exactly what D9's
    context exists to prevent. The same shape can appear in any proposal
    template with a numbered column, so this lives in the shared scanner
    rather than in anything MOU-specific.
    """
    from docx import Document

    doc = Document()
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "Sl. No."
    table.cell(0, 1).text = "Deliveries"
    table.cell(0, 2).text = "Details"
    table.cell(1, 0).text = "2"
    table.cell(1, 1).text = "GEN-i internship"
    table.cell(1, 2).text = "<ask:Yes>"
    table.cell(2, 0).text = "7"
    table.cell(2, 1).text = "Project assistance"
    table.cell(2, 2).text = "<ask:Yes>"
    buf = io.BytesIO()
    doc.save(buf)

    contexts = [o.context for o in tg.scan(buf.getvalue())]
    assert contexts == ["GEN-i internship", "Project assistance"]


def test_a_named_first_column_is_still_the_row_label():
    """The tagged proposal's table names the item in column 0 -- "Laptops",
    "Projector", "Magazine Rack" -- and must keep doing so."""
    from docx import Document

    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Magazine Rack"
    table.cell(0, 1).text = "<ask:1 Unit>"
    table.cell(1, 0).text = "Projector"
    table.cell(1, 1).text = "<ask:1 Unit>"
    buf = io.BytesIO()
    doc.save(buf)

    assert [o.context for o in tg.scan(buf.getvalue())] ==         ["Magazine Rack", "Projector"]
