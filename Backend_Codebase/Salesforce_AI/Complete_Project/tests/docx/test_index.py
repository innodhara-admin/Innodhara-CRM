# tests/docx/test_index.py
import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import index as ix


def _toc_paragraph(doc, style, label, page, anchor):
    p = doc.add_paragraph()
    ppr = p._p.get_or_add_pPr()
    ps = OxmlElement("w:pStyle"); ps.set(qn("w:val"), style); ppr.append(ps)
    link = OxmlElement("w:hyperlink"); link.set(qn("w:anchor"), anchor)
    for chunk in (label, page):
        r = OxmlElement("w:r"); t = OxmlElement("w:t")
        t.text = chunk; t.set(qn("xml:space"), "preserve"); r.append(t); link.append(r)
    p._p.append(link)
    return p


def _static_toc_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Table of Contents")
    _toc_paragraph(doc, "TOC1", "About YuviPep", "2", "_bookmark0")
    _toc_paragraph(doc, "TOC2", "Pricing Structure", "4", "_bookmark1")
    doc.add_page_break()
    doc.add_heading("About YuviPep", level=1)
    doc.add_paragraph("Body. " * 400)
    doc.add_page_break()
    doc.add_heading("Pricing Structure", level=1)
    doc.add_paragraph("More body. " * 400)
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def test_detects_no_index():
    doc = Document()
    doc.add_paragraph("Nothing indexed here.")
    buf = io.BytesIO(); doc.save(buf)
    assert ix.detect(Document(io.BytesIO(buf.getvalue()))) == "none"


def test_detects_a_static_index():
    assert ix.detect(Document(io.BytesIO(_static_toc_docx()))) == "static"


def test_detects_a_real_toc_field():
    doc = Document()
    p = doc.add_paragraph()
    r = OxmlElement("w:r")
    instr = OxmlElement("w:instrText")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    r.append(instr); p._p.append(r)
    buf = io.BytesIO(); doc.save(buf)
    assert ix.detect(Document(io.BytesIO(buf.getvalue()))) == "field"


def test_static_entries_carry_label_anchor_and_page():
    entries = ix.static_entries(Document(io.BytesIO(_static_toc_docx())))
    assert [e["label"] for e in entries] == ["About YuviPep", "Pricing Structure"]
    assert [e["anchor"] for e in entries] == ["_bookmark0", "_bookmark1"]
    assert [e["page_text"] for e in entries] == ["2", "4"]


def test_mark_fields_dirty_is_idempotent():
    doc = Document()
    ix.mark_fields_dirty(doc)
    ix.mark_fields_dirty(doc)
    found = doc.settings.element.findall(qn("w:updateFields"))
    assert len(found) == 1
    assert found[0].get(qn("w:val")) == "true"


def test_heading_pages_skips_the_pages_the_index_itself_sits_on():
    # 'Pricing Structure' appears on the contents page AND on its own page.
    pages = ["Table of Contents About YuviPep 2 Pricing Structure 4",
             "About YuviPep body",
             "Pricing Structure body"]
    mapping = ix.heading_pages_from_pages(pages, ["About YuviPep", "Pricing Structure"])
    assert mapping == {"About YuviPep": 2, "Pricing Structure": 3}


def test_entry_pages_resolves_a_label_that_the_contents_lists_twice():
    # 'Innovation Base Course' is listed twice, as a section and again as a
    # chapter later on. Keyed by label the second entry inherits the first
    # one's page; resolved per entry it gets its own.
    labels = ["Innovation Base Course", "Growing Impact", "Innovation Base Course"]
    pages = ["Contents Innovation Base Course 2 Growing Impact 3 Innovation Base Course 4",
             "Innovation Base Course opening",
             "Growing Impact body",
             "Innovation Base Course again"]
    assert ix.entry_pages(pages, labels) == [2, 3, 4]
    # the keyed route is what this exists to work around
    assert ix.heading_pages_from_pages(pages, labels)["Innovation Base Course"] == 2


def test_entry_pages_never_runs_backwards():
    # A contents listing is monotonic. A heading named in passing on an early
    # page must not drag its entry back above the one before it — which is
    # what the keyed route does with 'Zeta Six' here.
    labels = ["Alpha One", "Beta Two", "Gamma Three",
              "Delta Four", "Epsilon Five", "Zeta Six"]
    pages = ["Contents Alpha One 1 Beta Two 2 Gamma Three 3 "
             "Delta Four 4 Epsilon Five 5 Zeta Six 6",
             "Alpha One body, which mentions Zeta Six in passing",
             "Beta Two body",
             "Gamma Three body",
             "Delta Four body",
             "Epsilon Five body",
             "Zeta Six body"]
    resolved = ix.entry_pages(pages, labels)
    assert resolved == [2, 3, 4, 5, 6, 7]
    assert resolved == sorted(resolved)
    # the keyed route sends the last entry backwards, to the passing mention
    assert ix.heading_pages_from_pages(pages, labels)["Zeta Six"] == 2


def test_refresh_static_rewrites_stale_page_numbers():
    refreshed = ix.refresh_static(_static_toc_docx())
    entries = ix.static_entries(Document(io.BytesIO(refreshed)))
    assert [e["page_text"] for e in entries] != ["2", "4"]
    assert all(e["page_text"].strip().isdigit() for e in entries)


def test_refresh_static_is_a_no_op_without_a_static_index():
    doc = Document(); doc.add_paragraph("Plain document.")
    buf = io.BytesIO(); doc.save(buf)
    data = buf.getvalue()
    assert ix.refresh_static(data) == data
