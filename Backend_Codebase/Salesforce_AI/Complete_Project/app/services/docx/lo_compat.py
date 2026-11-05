# app/services/docx/lo_compat.py
"""What LibreOffice needs told differently, applied to the copy it converts.

Measured on 13 Oct 2026 against Word's own rendering of the Innodhara
proposal templates. The stored .docx is correct -- Word opens it page for page
like the template -- so nothing here is ever written back into a document a
person downloads. `convert.docx_to_pdf` hands LibreOffice a copy passed through
`prepare`, and that copy is thrown away with the PDF's temporary folder.

Two things, each one proven by converting with and without it:

*A picture in a paragraph whose mark is hidden.* The templates' cover art is a
full-page picture anchored in an otherwise empty paragraph whose paragraph
mark carries `w:vanish`. Word treats a hidden mark as "join this paragraph to
the next one" and still draws the picture. LibreOffice 24 and later hide the
whole paragraph, picture included, so the cover came out blank. The mark is
un-hidden and the paragraph squeezed to a 1 pt line, which puts the picture
and the text below it where Word puts them (measured: cover title within 2 pt
of Word). Only paragraphs holding a picture and no text are touched; a hidden
mark on a paragraph with words in it is left to LibreOffice.

*`PAGE \\* ArabicDash`.* Word prints "- 5 -"; LibreOffice does not know the
switch and prints "5". The switch is dropped and the dashes written as text
either side of the field, which is exactly what Word shows.

**Never fatal.** A document this cannot parse is converted exactly as it
arrived, which is what happened before this module existed.
"""
from __future__ import annotations

import copy
import io
import logging
import re
import zipfile

logger = logging.getLogger(__name__)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

#: The parts that carry paragraphs a reader sees on the page.
_PARTS = re.compile(r"^word/(document|header\d*|footer\d*)\.xml$")

#: A switch spelled the way Word writes it, with any spacing.
_ARABIC_DASH = re.compile(r"\\\*\s*ArabicDash", re.IGNORECASE)

#: 1 pt, in twentieths of a point: the line an un-hidden mark is given.
_THIN_LINE = "20"

_OFF = {"0", "false", "off"}


def _q(tag: str) -> str:
    return f"{{{W}}}{tag}"


def prepare(docx_bytes: bytes) -> bytes:
    """The copy LibreOffice converts. Unchanged bytes when nothing applies."""
    try:
        return _prepare(docx_bytes)
    except Exception:  # noqa: BLE001 -- the conversion must still happen
        logger.exception("Could not prepare a document for LibreOffice; "
                         "converting it as it is")
        return docx_bytes


def _prepare(docx_bytes: bytes) -> bytes:
    from lxml import etree  # noqa: PLC0415 -- heavy, and only needed here

    changed: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin:
        for name in zin.namelist():
            if not _PARTS.match(name):
                continue
            data = zin.read(name)
            if b"vanish" not in data and b"ArabicDash" not in data:
                continue
            root = etree.fromstring(data)
            marks = _unhide_picture_marks(etree, root)
            dashes = _arabic_dash(etree, root)
            if marks or dashes:
                changed[name] = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True)
                logger.info("Prepared %s for LibreOffice: %d picture mark(s), "
                            "%d dashed page number(s)", name, marks, dashes)
        if not changed:
            return docx_bytes
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                zout.writestr(item, changed.get(item.filename)
                              or zin.read(item.filename))
    return out.getvalue()


def _on(element) -> bool:
    return element is not None and (
        element.get(_q("val")) or "true").lower() not in _OFF


def _own_text(p) -> str:
    """The paragraph's own words: a text box's paragraph is a different one."""
    out = []
    for t in p.iter(_q("t")):
        anc = t.getparent()
        while anc is not None and anc.tag != _q("p"):
            anc = anc.getparent()
        if anc is p:
            out.append(t.text or "")
    return "".join(out)


def _unhide_picture_marks(etree, root) -> int:
    count = 0
    for p in root.iter(_q("p")):
        ppr = p.find(_q("pPr"))
        mark = None if ppr is None else ppr.find(f"{_q('rPr')}/{_q('vanish')}")
        if not _on(mark):
            continue
        if p.find(f".//{_q('drawing')}") is None and \
                p.find(f".//{_q('pict')}") is None:
            continue
        if _own_text(p).strip():
            continue
        mark.getparent().remove(mark)
        spacing = ppr.find(_q("spacing"))
        if spacing is None:
            spacing = etree.Element(_q("spacing"))
            # CT_PPrBase order: spacing sits before the mark's rPr.
            rpr = ppr.find(_q("rPr"))
            if rpr is not None:
                rpr.addprevious(spacing)
            else:
                ppr.append(spacing)
        spacing.set(_q("line"), _THIN_LINE)
        spacing.set(_q("lineRule"), "exact")
        count += 1
    return count


def _dash_run(etree, text: str, like=None):
    run = etree.Element(_q("r"))
    if like is not None and like.find(_q("rPr")) is not None:
        run.append(copy.deepcopy(like.find(_q("rPr"))))
    t = etree.SubElement(run, _q("t"))
    t.text = text
    t.set(XML_SPACE, "preserve")
    return run


def _field_type(run) -> str | None:
    char = run.find(_q("fldChar")) if run.tag == _q("r") else None
    return None if char is None else char.get(_q("fldCharType"))


def _arabic_dash(etree, root) -> int:
    count = 0
    for instr in list(root.iter(_q("instrText"))):
        text = instr.text or ""
        if not _ARABIC_DASH.search(text) or "PAGE" not in text.upper():
            continue
        run = instr.getparent()
        begin = run
        while begin is not None and _field_type(begin) != "begin":
            begin = begin.getprevious()
        end, depth = run.getnext(), 1  # inside the field, past its begin
        while end is not None:
            kind = _field_type(end)
            depth += kind == "begin"
            depth -= kind == "end"
            if depth == 0:
                break
            end = end.getnext()
        if begin is None or end is None:
            continue  # a field split across paragraphs: leave it alone
        instr.text = _ARABIC_DASH.sub("", text)
        begin.addprevious(_dash_run(etree, "- ", begin))
        end.addnext(_dash_run(etree, " -", end))
        count += 1
    for simple in list(root.iter(_q("fldSimple"))):
        text = simple.get(_q("instr")) or ""
        if not _ARABIC_DASH.search(text) or "PAGE" not in text.upper():
            continue
        simple.set(_q("instr"), _ARABIC_DASH.sub("", text))
        inner = simple.find(_q("r"))
        simple.addprevious(_dash_run(etree, "- ", inner))
        simple.addnext(_dash_run(etree, " -", inner))
        count += 1
    return count
