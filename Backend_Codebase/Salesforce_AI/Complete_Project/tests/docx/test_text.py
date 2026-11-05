# tests/docx/test_text.py
import io
import re
import zipfile
from pathlib import Path

import pytest
from docx import Document

from app.services.docx import outline as ol
from app.services.docx import text as dt


_P_TOKEN = re.compile(
    r"(?P<popen><w:p(?:\s[^>]*)?>)"
    r"|(?P<pclose></w:p>)"
    r"|<w:t(?:\s[^>]*)?>(?P<ttext>.*?)</w:t>",
    re.S,
)


def raw_count(data: bytes, literal: str) -> int:
    """Ground truth: count per <w:p> across every word/*.xml part.

    Walks open/close `w:p` tags with an explicit stack so nested paragraphs
    (text boxes) are attributed to their own nearest `w:p`, not to whichever
    ancestor's `.*?</w:p>` a non-overlapping regex scan happens to reach
    first. A naive single-pass `<w:p[ >].*?</w:p>` match conflates a nested
    `w:p`'s closing tag with its outer paragraph's, silently discarding the
    inner paragraph's own text — undercounting exactly the shape this task
    exists to get right. Deliberately still regex/text-based rather than an
    XML-tree walk, so it stays an independent check on the raw markup instead
    of reusing the tree API the implementation under test also uses.
    """
    z = zipfile.ZipFile(io.BytesIO(data))
    total = 0
    for name in z.namelist():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        x = z.read(name).decode("utf8", "replace")
        stack: list[list[str]] = []
        for m in _P_TOKEN.finditer(x):
            if m.group("popen"):
                stack.append([])
            elif m.group("pclose"):
                if stack:
                    own = "".join(stack.pop())
                    total += own.count(literal)
            else:
                if stack:
                    stack[-1].append(m.group("ttext") or "")
    return total


def _doc(data: bytes):
    return Document(io.BytesIO(data))


def test_sees_text_split_across_runs(fragmented_docx):
    doc = _doc(fragmented_docx)
    assert dt.count_token(doc, "School Name") == 1


def test_replaces_text_split_across_runs(fragmented_docx):
    doc = _doc(fragmented_docx)
    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
    p = next(dt.iter_paragraphs(doc.element.body))
    assert dt.node_text(p) == "Welcome to Greenwood for the year."


def test_sees_text_inside_hyperlinks(hyperlink_docx):
    doc = _doc(hyperlink_docx)
    # the defect this pins: Paragraph.runs returns nothing useful here
    assert len(doc.paragraphs[0].runs) < 4
    assert dt.count_token(doc, "School Name") == 1
    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
    assert "Greenwood" in dt.node_text(next(dt.iter_paragraphs(doc.element.body)))


def test_sees_text_inside_textboxes(textbox_docx):
    doc = _doc(textbox_docx)
    assert dt.count_token(doc, "School Name") == 2
    assert dt.replace_token(doc, "School Name", "Greenwood") == 2
    assert dt.count_token(doc, "School Name") == 0


def test_textbox_text_is_not_spliced_into_the_outer_paragraph(textbox_docx):
    doc = _doc(textbox_docx)
    outer = next(dt.iter_paragraphs(doc.element.body))
    assert dt.node_text(outer) == "Outer School Name text."


def test_sees_text_in_headers_and_footers(header_docx):
    doc = _doc(header_docx)
    assert dt.count_token(doc, "School Name") == 3
    assert dt.replace_token(doc, "School Name", "Greenwood") == 3
    assert dt.count_token(doc, "School Name") == 0


def test_sees_text_in_table_cells(table_docx):
    doc = _doc(table_docx)
    assert dt.count_token(doc, "Innovation Lab") == 1
    assert dt.replace_token(doc, "Innovation Lab", "Essential Lab") == 1


def test_matches_raw_xml_ground_truth(fragmented_docx, hyperlink_docx,
                                      textbox_docx, header_docx):
    for data in (fragmented_docx, hyperlink_docx, textbox_docx, header_docx):
        assert dt.count_token(_doc(data), "School Name") == raw_count(data, "School Name")


def test_replace_span_preserves_surrounding_text(fragmented_docx):
    doc = _doc(fragmented_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    start = dt.node_text(p).index("School Name")
    assert dt.replace_span(p, start, start + len("School Name"), "X")
    assert dt.node_text(p) == "Welcome to X for the year."


def test_replace_span_out_of_range_is_a_no_op(fragmented_docx):
    doc = _doc(fragmented_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    before = dt.node_text(p)
    assert dt.replace_span(p, 9999, 10000, "X") is False
    assert dt.node_text(p) == before


def test_leading_space_survives_a_replacement(fragmented_docx):
    doc = _doc(fragmented_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    dt.replace_span(p, 0, len("Welcome to"), "  Hello  ")
    buf = io.BytesIO()
    doc.save(buf)
    assert dt.node_text(next(dt.iter_paragraphs(_doc(buf.getvalue()).element.body))) \
        == "  Hello   School Name for the year."


def test_replace_span_preserves_whitespace_on_trailing_node(two_run_whitespace_docx):
    """Pins the fix to replace_span's `else` branch: when a span ends
    mid-node and the surviving remainder starts with a space, that node must
    carry xml:space="preserve" or Word collapses the space on render.

    node_text() equality alone does not distinguish buggy from fixed here:
    python-docx/lxml preserves a w:t's raw text verbatim through save/reopen
    regardless of the xml:space attribute (verified directly against this
    repo's python-docx 1.2.0), so a round trip that only checks the joined
    string would pass even with the bug. The attribute is what actually
    protects the document once Word -- not python-docx -- renders it, so
    that is what this test pins, on both the freshly-mutated element and
    after a save/reopen round trip.
    """
    doc = _doc(two_run_whitespace_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    start = dt.node_text(p).index("School Name")
    assert dt.replace_span(p, start, start + len("School Name"), "Greenwood")
    assert dt.node_text(p) == "Dear Greenwood today"

    trailing = dt.own_text_nodes(p)[-1]
    assert trailing.text == " today"
    assert trailing.get(dt.XML_SPACE) == "preserve"

    buf = io.BytesIO()
    doc.save(buf)
    doc2 = _doc(buf.getvalue())
    p2 = next(dt.iter_paragraphs(doc2.element.body))
    assert dt.node_text(p2) == "Dear Greenwood today"
    trailing2 = dt.own_text_nodes(p2)[-1]
    assert trailing2.text == " today"
    assert trailing2.get(dt.XML_SPACE) == "preserve"


def test_linked_section_footer_is_not_double_counted(linked_section_footer_docx):
    """Two sections whose footer is shared (second linked to first, the
    python-docx default). all_roots must de-duplicate by element identity so
    the shared footer is counted/replaced once, not once per section.
    """
    doc = _doc(linked_section_footer_docx)
    assert len(doc.sections) == 2
    assert doc.sections[1].footer.is_linked_to_previous is True
    assert dt.count_token(doc, "School Name") == 1
    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
    assert dt.count_token(doc, "School Name") == 0
    assert "Greenwood" in dt.node_text(doc.sections[0].footer.paragraphs[0]._p)


# --- the paragraph walk, and the label that goes with it (Task A2) -----------
#
# The walk is how the simple flow addresses a tag: an occurrence is
# (walk ordinal, start, end), never a positional path. The label is for a human
# reading a fill plan, and it is allowed to be absent -- but it is never
# allowed to be wrong.

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
TAGGED_SAMPLE = SAMPLES_DIR / "Innovation Lab Template (tagged).docx"

# One tag in each of the seven places, and whether a positional path reaches it.
SEVEN_PLACES = [
    ("an ordinary body paragraph", "<School Name>", True),
    ("three runs of one paragraph", "<Ph no. yuvipep>", True),
    ("a table cell", "<ask:6 Units>", True),
    ("a nested table inside a cell", "<ask:(3 Nos)>", False),
    ("a text box", "<Name>", False),
    ("a header", "<website yuv>", True),
    ("a footer", "<email yuvip>", True),
]


def ordinal_of(walk, literal: str) -> int:
    hits = [i for i, p in enumerate(walk) if literal in dt.node_text(p)]
    assert len(hits) == 1, f"{literal!r} appears in {len(hits)} paragraphs"
    return hits[0]


def test_walk_paragraphs_is_the_walk_this_module_already_uses(every_awkward_place_docx):
    doc = _doc(every_awkward_place_docx)
    expected = [p for root in dt.all_roots(doc) for p in dt.iter_paragraphs(root)]
    assert dt.walk_paragraphs(doc) == expected


def test_the_walk_reaches_all_seven_awkward_places(every_awkward_place_docx):
    """Plan section 2.3a: the walk is 7 of 7 where the path is 5 of 7."""
    doc = _doc(every_awkward_place_docx)
    texts = [dt.node_text(p) for p in dt.walk_paragraphs(doc)]
    for where, literal, _ in SEVEN_PLACES:
        assert any(literal in t for t in texts), f"the walk missed {where}"


@pytest.mark.parametrize(
    "where,literal,reachable_by_path",
    SEVEN_PLACES,
    ids=[w.replace(" ", "-") for w, _, _ in SEVEN_PLACES],
)
def test_a_label_exists_for_five_of_the_seven(
    every_awkward_place_docx, where, literal, reachable_by_path
):
    """A nested table and a text box have no positional path, and say so.

    Returning a plausible-looking path for either would be worse than
    returning nothing: it would resolve to a different paragraph.
    """
    doc = _doc(every_awkward_place_docx)
    walk = dt.walk_paragraphs(doc)
    label = dt.label_for(doc, ordinal_of(walk, literal))
    assert (label is not None) is reachable_by_path


def test_the_five_labels_are_the_paths_a_person_can_check_by_eye(every_awkward_place_docx):
    doc = _doc(every_awkward_place_docx)
    walk = dt.walk_paragraphs(doc)
    labels = {
        literal: dt.label_for(doc, ordinal_of(walk, literal))
        for _, literal, reachable in SEVEN_PLACES if reachable
    }
    assert labels == {
        "<School Name>": "body[0]",
        "<Ph no. yuvipep>": "body[1]",
        "<ask:6 Units>": "body[2]/tr[0]/tc[1]/p[0]",
        "<website yuv>": "sec[0]/hdr/body[0]",
        "<email yuvip>": "sec[0]/ftr/body[0]",
    }


def test_no_label_names_a_paragraph_other_than_its_own(every_awkward_place_docx):
    """The whole contract of `label_for`: absent is fine, wrong is not."""
    doc = _doc(every_awkward_place_docx)
    walk = dt.walk_paragraphs(doc)
    labelled = 0
    for ordinal, paragraph in enumerate(walk):
        label = dt.label_for(doc, ordinal)
        if label is None:
            continue
        labelled += 1
        assert ol.resolve(doc, label) is paragraph
    assert labelled == 10


def test_an_even_page_header_gets_no_label(every_awkward_place_docx):
    """`all_roots` materialises six header/footer kinds; `resolve` knows two.

    Accessing `section.even_page_header` creates its definition, so this
    16-paragraph document carries four empty paragraphs in parts that no
    `sec[s]/hdr` or `sec[s]/ftr` path can address. Labelling them would invent
    a path that resolves to the wrong element.
    """
    doc = _doc(every_awkward_place_docx)
    roots = dt.all_roots(doc)
    assert len(roots) == 7
    addressable = {id(doc.sections[0].header._element),
                   id(doc.sections[0].footer._element),
                   id(doc.element.body)}
    unaddressable = [r for r in roots if id(r) not in addressable]
    assert len(unaddressable) == 4

    walk = dt.walk_paragraphs(doc)
    for root in unaddressable:
        for paragraph in dt.iter_paragraphs(root):
            assert dt.label_for(doc, walk.index(paragraph)) is None


def test_the_walk_order_is_identical_across_two_independent_reads(every_awkward_place_docx):
    """The ordinal is only an address because the same bytes give the same walk."""
    first = [dt.node_text(p) for p in dt.walk_paragraphs(_doc(every_awkward_place_docx))]
    second = [dt.node_text(p) for p in dt.walk_paragraphs(_doc(every_awkward_place_docx))]
    assert first == second
    assert len(first) == 16


def test_an_ordinal_outside_the_walk_has_no_label(every_awkward_place_docx):
    doc = _doc(every_awkward_place_docx)
    beyond = len(dt.walk_paragraphs(doc))
    assert dt.label_for(doc, beyond) is None
    assert dt.label_for(doc, -1) is None


golden = pytest.mark.skipif(
    not TAGGED_SAMPLE.exists(), reason="tagged sample not present"
)


@golden
def test_no_label_in_the_real_document_names_the_wrong_paragraph():
    """248 paragraphs of a real branded template, every label checked."""
    doc = _doc(TAGGED_SAMPLE.read_bytes())
    walk = dt.walk_paragraphs(doc)
    assert len(walk) == 248
    for ordinal, paragraph in enumerate(walk):
        label = dt.label_for(doc, ordinal)
        if label is not None:
            assert ol.resolve(doc, label) is paragraph


@golden
def test_every_tag_in_the_real_document_also_has_a_label():
    """Plan section 2.3 reached all 25 by positional path on THIS document.

    That is what makes the label useful here even though the walk is what the
    writer uses: all 25 sit in body paragraphs and first-level table cells.
    A run that disagrees is a finding, not a pin to edit.
    """
    from app.services.docx import tags as tg

    data = TAGGED_SAMPLE.read_bytes()
    doc = _doc(data)
    walk = dt.walk_paragraphs(doc)
    occurrences = tg.scan(data)
    assert len(occurrences) == 25
    for occurrence in occurrences:
        label = dt.label_for(doc, occurrence.ordinal)
        assert label is not None, f"{occurrence.raw} at {occurrence.ordinal} has no path"
        assert ol.resolve(doc, label) is walk[occurrence.ordinal]
