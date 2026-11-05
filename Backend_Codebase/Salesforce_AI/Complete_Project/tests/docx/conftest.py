# tests/docx/conftest.py
"""Synthetic .docx fixtures that reproduce the shapes real documents use.

Word fragments runs arbitrarily and buries text in hyperlinks and text boxes.
`Paragraph.runs` sees none of the latter two, so every fixture here exists to
pin one of those shapes.
"""
import io

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import nsmap, qn

# python-docx's default nsmap omits the VML "v:" prefix (used by w:pict/v:shape
# for legacy text boxes), so OxmlElement("v:shape") raises KeyError without this.
nsmap.setdefault("v", "urn:schemas-microsoft-com:vml")


def _t(text: str):
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    return t


def _run(text: str, *, bold: bool = False):
    r = OxmlElement("w:r")
    if bold:
        rpr = OxmlElement("w:rPr")
        rpr.append(OxmlElement("w:b"))
        r.append(rpr)
    r.append(_t(text))
    return r


def _t_plain(text: str):
    """A w:t with no xml:space attribute, matching how Word writes a run
    whose own text has no leading/trailing whitespace worth protecting at
    creation time — the shape that exposes replace_span's whitespace bug."""
    t = OxmlElement("w:t")
    t.text = text
    return t


def _run_plain(text: str):
    r = OxmlElement("w:r")
    r.append(_t_plain(text))
    return r


def save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def fragmented_docx() -> bytes:
    """'School Name' split across three runs, as Word actually writes it."""
    doc = Document()
    p = doc.add_paragraph()
    for chunk in ("Welcome to ", "School", " ", "Name", " for the year."):
        p._p.append(_run(chunk))
    return save(doc)


@pytest.fixture
def hyperlink_docx() -> bytes:
    """Text inside w:hyperlink — invisible to Paragraph.runs."""
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(_run("Contact "))
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), "_bookmark0")
    link.append(_run("School"))
    link.append(_run(" "))
    link.append(_run("Name"))
    p._p.append(link)
    p._p.append(_run(" today."))
    return save(doc)


@pytest.fixture
def textbox_docx() -> bytes:
    """A whole w:p nested inside a text box within an outer paragraph."""
    doc = Document()
    outer = doc.add_paragraph()
    outer._p.append(_run("Outer School Name text."))
    r = OxmlElement("w:r")
    pict = OxmlElement("w:pict")
    shape = OxmlElement("v:shape")
    tbx = OxmlElement("v:textbox")
    content = OxmlElement("w:txbxContent")
    inner = OxmlElement("w:p")
    inner.append(_run("Inner School Name label."))
    content.append(inner)
    tbx.append(content)
    shape.append(tbx)
    pict.append(shape)
    r.append(pict)
    outer._p.append(r)
    return save(doc)


@pytest.fixture
def table_docx() -> bytes:
    doc = Document()
    t = doc.add_table(rows=3, cols=2)
    t.style = "Table Grid"
    t.cell(0, 0).text = "Description"
    t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Innovation Lab"
    t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total"
    t.cell(2, 1).text = "Rs 0"
    return save(doc)


@pytest.fixture
def header_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Body mentions School Name once.")
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    header.paragraphs[0]._p.append(_run("Header for School Name"))
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    footer.paragraphs[0]._p.append(_run("Footer for School Name"))
    return save(doc)


@pytest.fixture
def two_run_whitespace_docx() -> bytes:
    """A span replacement that ends mid-node, leaving a leading-space
    remainder in the LAST covered w:t. Pins replace_span's `else` branch:
    without an xml:space="preserve" guard there too, that remainder collapses
    its leading space when Word renders it.
    """
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(_run_plain("Dear School"))
    p._p.append(_run_plain(" Name today"))
    return save(doc)


@pytest.fixture
def linked_section_footer_docx() -> bytes:
    """Two sections; the second's footer is left linked to the first's (the
    python-docx default after add_section()), so the underlying footer part
    -- and its element -- is shared between sections. Pins all_roots's
    de-duplication by element identity: a broken dedup would double-count or
    double-replace text in a footer shared by every linked section.
    """
    doc = Document()
    doc.add_paragraph("Section one body.")
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    footer.paragraphs[0]._p.append(_run("Footer for School Name"))
    doc.add_section()
    doc.add_paragraph("Section two body.")
    return save(doc)


# --- simple-flow tag fixtures (Task A1) -------------------------------------
# The tagged documents the scanner is measured against. Each one pins a shape
# the owner's real file uses, or a rejection the grammar in plan section 3
# requires.


@pytest.fixture
def tagged_fragmented_docx() -> bytes:
    """A tag split across three runs, the way Word fragments one.

    `<School Name>` arrives as `['<School', ' ', 'Name>']`, so a scanner that
    looked at run text would find nothing. The scan is over `node_text`.
    """
    doc = Document()
    p = doc.add_paragraph()
    for chunk in ("Welcome to ", "<School", " ", "Name>", " for the year."):
        p._p.append(_run(chunk))
    return save(doc)


@pytest.fixture
def tagged_table_docx() -> bytes:
    """Four tags in a two-column table: the shape 19 of the real 25 are in.

    Row 1 and row 2 carry the SAME literal in different rows -- four different
    questions in the real document -- and row 3 carries two tags in one cell.
    """
    doc = Document()
    t = doc.add_table(rows=4, cols=2)
    t.cell(0, 0).text = "Item"
    t.cell(0, 1).text = "Quantity"
    t.cell(1, 0).text = "Magazine Rack"
    t.cell(1, 1).text = "<ask:1 Unit>"
    t.cell(2, 0).text = "Projector"
    t.cell(2, 1).text = "<ask:1 Unit>"
    t.cell(3, 0).text = "Experimenters Hub"
    t.cell(3, 1).text = (
        "CRO, Safety Glass <ask: (10 units)>, Drill Machine <ask:(3 Nos)>"
    )
    return save(doc)


@pytest.fixture
def tagged_textbox_docx() -> bytes:
    """One tag in a body paragraph and one inside a text box.

    The text box is why the scan walks `iter_paragraphs`, not `doc.paragraphs`:
    the four real documents already use text boxes.
    """
    doc = Document()
    outer = doc.add_paragraph()
    outer._p.append(_run("Prepared for <School Name>."))
    r = OxmlElement("w:r")
    pict = OxmlElement("w:pict")
    shape = OxmlElement("v:shape")
    tbx = OxmlElement("v:textbox")
    content = OxmlElement("w:txbxContent")
    inner = OxmlElement("w:p")
    inner.append(_run("Contact <Name> today."))
    content.append(inner)
    tbx.append(content)
    shape.append(tbx)
    pict.append(shape)
    r.append(pict)
    outer._p.append(r)
    return save(doc)


@pytest.fixture
def tagged_header_docx() -> bytes:
    """A tag in the body, one in the header and one in the footer.

    Pins that the scan walks `all_roots`. A body-only walk still passes the
    text-box test, so this is the fixture that catches it.
    """
    doc = Document()
    doc.add_paragraph("Body for <School Name> follows.")
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    header.paragraphs[0]._p.append(_run("Header <Ph no. yuvipep>"))
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    footer.paragraphs[0]._p.append(_run("Footer <website yuv>"))
    return save(doc)


@pytest.fixture
def tagged_rejects_docx() -> bytes:
    """A paragraph of things that are not tags and must never become one.

    Unambiguous markup only -- a closing tag, a self-closing tag -- plus an
    empty body. A bare `<b>` is deliberately NOT here: it is accepted, and
    costs one question a human dismisses, rather than being dropped in
    silence along with `<price>`.
    """
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(_run("Line </b> and <p/> and <br /> and <> and </div> end."))
    return save(doc)


# --- the seven places a tag can live (Task A2) -------------------------------


@pytest.fixture
def every_awkward_place_docx() -> bytes:
    """One tag in each of the seven places Word lets a paragraph live.

    Plan section 2.3a built this document to compare two ways of addressing a
    paragraph. The walk reaches all seven; the positional path reaches five and
    misses the nested table and the text box. Both of those shapes are already
    in the four real documents, which is why the walk is what the writer uses.

    The tags are all distinct so a test can name one without ambiguity.
    """
    doc = Document()
    doc.add_paragraph("Prepared for <School Name>.")

    fragmented = doc.add_paragraph()
    for chunk in ("Kind Attention: ", "<Ph", " no.", " yuvipep>"):
        fragmented._p.append(_run(chunk))

    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Laptops"
    table.cell(0, 1).text = "<ask:6 Units>"
    table.cell(1, 0).text = "Bundle"
    nested = table.cell(1, 1).add_table(rows=1, cols=1)
    nested.cell(0, 0).text = "<ask:(3 Nos)>"

    outer = doc.add_paragraph()
    outer._p.append(_run("Signed "))
    r = OxmlElement("w:r")
    pict = OxmlElement("w:pict")
    shape = OxmlElement("v:shape")
    tbx = OxmlElement("v:textbox")
    content = OxmlElement("w:txbxContent")
    inner = OxmlElement("w:p")
    inner.append(_run("Contact <Name> today."))
    content.append(inner)
    tbx.append(content)
    shape.append(tbx)
    pict.append(shape)
    r.append(pict)
    outer._p.append(r)

    header = doc.sections[0].header
    header.is_linked_to_previous = False
    header.paragraphs[0]._p.append(_run("Visit <website yuv>"))
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    footer.paragraphs[0]._p.append(_run("Write to <email yuvip>"))
    return save(doc)
