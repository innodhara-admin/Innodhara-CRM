# app/services/docx/properties.py
"""The document's PROPERTIES, which no tag can reach.

`tags.scan` and `tagfill.apply_tags` both walk PARAGRAPHS. Word's document
properties are not paragraphs, so every part of the fill machinery is blind to
them -- and the owner found this the way it is always found, by opening a
"clean" MOU and seeing the previous school's name in Word's title bar.

Measured on their file, the client was in THIRTEEN metadata values across four
parts: `docProps/core.xml` (dc:title, dc:subject, and the school's own
signatory as dc:creator -- the AUTHOR of our document), `docProps/app.xml`
(TitlesOfParts, and `<Manager>`, which the body renders through a DOCPROPERTY
field, so that one is on the page), `docProps/custom.xml` (the
document-control block) and `customXml/item1.xml`, Word's cover-page property
store, which carried the school's address, its student count and the contract
value.

`scripts/tag_mou_sample.py` neutralises all of them, so the TEMPLATE names
nobody: its dc:title reads "<School Name>". That is deliberate -- an unfilled
property that looks like the bug it is beats one that silently names the wrong
client -- but it means NOTHING FILLS THEM, and without this module every MOU
built from that template ships literal tag text in its Word properties.

This is the exact inverse of that neutralisation, and it is written the same
way for the same reason: parsed with lxml and rewritten element by element,
never by string replacement. A tag contains angle brackets, and pasting one
into XML text produces a package Word refuses to open -- which is precisely
what the first version of the neutraliser did.

**A tag that cannot be filled is BLANKED, never left standing.** A signed
contract whose properties read "<School Name>" is the defect this module
exists to prevent, and leaving one because no value was found is that same
defect wearing a different hat.

The body's own grammar is reused rather than restated -- `tags.TAG_RE` -- so a
literal that is a tag on the page is a tag here too, and the two cannot drift
apart.
"""
from __future__ import annotations

import io
import logging
import zipfile
from typing import Any

from app.services.docx.tags import TAG_RE

logger = logging.getLogger(__name__)

#: Which parts carry properties. `customXml/item1.xml` is Word's cover-page
#: property store and is the surprising one -- it held the school's address,
#: its student count and the contract value.
PARTS = ("docProps/core.xml", "docProps/app.xml",
         "docProps/custom.xml", "customXml/item1.xml")

CORE = "docProps/core.xml"

_DC = "http://purl.org/dc/elements/1.1/"
_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"

#: The core properties this module writes, and the namespace each belongs to.
_CORE_NS = {"title": _DC, "subject": _DC, "creator": _DC,
            "keywords": _CP, "category": _CP, "lastModifiedBy": _CP}

#: Cleared on every build, and none of them is housekeeping.
#:
#: `creator` is Word's "Author". The owner's template carried the SCHOOL'S own
#: signatory there, so a contract we generate would go out authored by a
#: person at the client -- and, once it is a template, by a person at the
#: PREVIOUS client. `keywords` held an office ("Chief Executive Officer") and
#: `category` a title ("President"). `lastModifiedBy` is whoever last saved
#: the template, which is a member of staff, not this document's business.
#:
#: Blank rather than "YuviPep": naming ourselves as the author of a document
#: the client signs is a claim, and an empty field makes none.
_CLEARED = ("creator", "keywords", "category", "lastModifiedBy")


def values_from(tags: list[dict[str, Any]]) -> dict[str, str]:
    """The literal -> value map, from the fill's own record.

    A property carries a tag's LITERAL and nothing else -- no ordinal, no
    context -- so the only thing that can fill it is the value that literal
    settled on. Where the fill gave one literal SEVERAL different values that
    is not a defect but the point of F1's `(raw, context)` key: the MOU's
    `<ask:Yes>` occurs once per deliverables row and they are seven separate
    questions. Picking one of seven answers to stand for the property would be
    arbitrary, so a literal whose occurrences disagree yields no value at all
    and the property is blanked. Blank is honest; an arbitrary answer is not.

    Only `filled` occurrences count. One still carrying its question has no
    value to give, and its `value` key holds whatever the author proposed.
    """
    candidates: dict[str, set[str]] = {}
    for tag in tags:
        raw = tag.get("raw")
        if not raw or tag.get("outcome") != "filled":
            continue
        value = str(tag.get("value") or "").strip()
        if value:
            candidates.setdefault(raw, set()).add(value)
    return {raw: values.pop() for raw, values in candidates.items()
            if len(values) == 1}


def fill(
    docx_bytes: bytes,
    values: dict[str, str],
    *,
    title: str | None = None,
    subject: str | None = None,
) -> bytes:
    """Write the built document's properties, and leave no tag text behind.

    Two passes over the same package, in this order:

    1. Every tag-shaped run in every property, wherever it sits, is replaced
       by the value that literal settled on -- or by nothing at all, because
       an unfillable tag must not survive. A run is replaced in place rather
       than the whole property overwritten, so a property that merely CONTAINS
       a tag keeps its surrounding words.
    2. The core properties that identify the document are set outright:
       `dc:title` to the client, `dc:subject` to the programme, and the four
       in `_CLEARED` emptied. These win over anything pass 1 wrote, which is
       what the ledger asked for -- they are not guesses from a literal, they
       are what this document IS.
    """
    from lxml import etree  # noqa: PLC0415 -- heavy, and only needed here

    source, out = io.BytesIO(docx_bytes), io.BytesIO()
    with zipfile.ZipFile(source) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        names = set(zin.namelist())
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in PARTS:
                root = etree.fromstring(data)
                _fill_literals(root, values)
                if item.filename == CORE:
                    _set_core(etree, root, title=title, subject=subject)
                data = etree.tostring(root, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    if CORE not in names:
        logger.warning(
            "This document has no %s, so its title and subject were not set; "
            "the tag text in its other properties was still removed", CORE)
    return out.getvalue()


def fill_literals(docx_bytes: bytes, values: dict[str, str]) -> bytes:
    """Pass 1 of `fill` alone: tag text in the properties, and nothing else.

    For a PROPOSAL (12 Oct 2026). The owner's proposal templates show the
    school's name on the cover and in every footer through content controls
    BOUND to dc:title -- and dc:title is the literal "<School name>". The tag
    fill walks paragraphs, so the page said "Test School Sunrise" while the
    property it is bound to still said "<School name>", and LibreOffice (like
    Word on opening) shows the property: 23 pages of a real proposal PDF read
    "<School name>".

    Not `fill`, deliberately. `fill` also sets the title to the client and
    blanks the author fields, which is right for a contract and would change
    what an existing proposal template whose title is real text shows on its
    cover. Here only text that is a tag is touched -- and that text has only
    ever reached a client as a literal tag.

    A literal is looked up as written first, then ignoring case, so a title
    of "<School Name>" over a body tag "<School name>" still fills rather
    than blanks.
    """
    folded = {raw.casefold(): value for raw, value in values.items()}
    from lxml import etree  # noqa: PLC0415 -- heavy, and only needed here

    source, out = io.BytesIO(docx_bytes), io.BytesIO()
    with zipfile.ZipFile(source) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in PARTS:
                root = etree.fromstring(data)
                if _has_tag_text(root):
                    _fill_literals(root, values, folded)
                    data = etree.tostring(root, xml_declaration=True,
                                          encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    return out.getvalue()


def _has_tag_text(root) -> bool:
    return any(TAG_RE.search(node.text or "") for node in root.iter())


def _fill_literals(root, values: dict[str, str],
                   folded: dict[str, str] | None = None) -> None:
    def value_for(literal: str) -> str:
        if literal in values:
            return values[literal]
        return (folded or {}).get(literal.casefold(), "")

    for node in root.iter():
        text = node.text or ""
        if not TAG_RE.search(text):
            continue
        node.text = TAG_RE.sub(
            lambda m: value_for(m.group(0)), text).strip()


def _set_core(etree, root, *, title: str | None, subject: str | None) -> None:
    """Set-or-create, because a property that is absent cannot be assigned.

    The parts this module is aimed at all carry the full core set, but a
    document assembled by something else may not -- and silently declining to
    write `dc:title` because the element was missing would reproduce exactly
    the defect this module closes.
    """
    wanted = {name: "" for name in _CLEARED}
    if title is not None:
        wanted["title"] = title
    if subject is not None:
        wanted["subject"] = subject

    found = {}
    for node in root.iter():
        name = etree.QName(node).localname
        if name in wanted:
            found[name] = node
    for name, text in wanted.items():
        node = found.get(name)
        if node is None:
            node = etree.SubElement(root, "{%s}%s" % (_CORE_NS[name], name))
        node.text = text


def read(docx_bytes: bytes) -> list[tuple[str, str, str]]:
    """Every non-empty property in the package, as (part, name, text).

    A reader, so a test can assert over the WHOLE package rather than over the
    handful of properties python-docx exposes. Counting over the paragraph
    walk is what let the original defect through.
    """
    from lxml import etree  # noqa: PLC0415

    out: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin:
        for name in zin.namelist():
            if name not in PARTS:
                continue
            for node in etree.fromstring(zin.read(name)).iter():
                text = (node.text or "").strip()
                if text:
                    out.append((name, etree.QName(node).localname, text))
    return out


def tag_like(docx_bytes: bytes) -> list[tuple[str, str, str]]:
    """Every property still carrying tag text. Must be empty on a built MOU.

    The guard the owner needed and nobody had: it asks the question over the
    whole package instead of over the page.
    """
    return [entry for entry in read(docx_bytes) if TAG_RE.search(entry[2])]
