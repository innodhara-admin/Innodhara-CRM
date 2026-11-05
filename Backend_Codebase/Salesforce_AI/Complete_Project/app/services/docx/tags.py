# app/services/docx/tags.py
"""The simple-flow tag grammar, and the scan that finds every occurrence.

In the simple flow the template author writes the placeholders into the Word
file by hand, as angle-bracket tags: `<School Name>`, `<ask:4 Units>`,
`<ask_calculate:Rs. 15,00,000/- ...>`. Nobody marks anything up in a console
afterwards. This module is the only place that decides what is a tag.

**Identity is per occurrence, never per literal** (D1). `<ask:1 Unit>` appears
four times in the owner's real template, in four different rows, and they are
four different questions about four different items. `docx_text.replace_token`
would have written one answer into all four, which is precisely why nothing
here works on literals.

An occurrence is therefore addressed as **(walk ordinal, start, end)** (D2):
the paragraph's position in `[p for root in all_roots(doc) for p in
iter_paragraphs(root)]` -- `docx_text`'s own walk -- plus a character range in
`node_text` space. Not a positional path: measured against a document with a
tag in every awkward place Word allows, the path scheme reached 5 of 7 and
missed a nested table and a text box, while the walk reached all 7. Both of
those shapes are already in the four real documents.

The ordinal is stable because the source document is immutable (D3): the same
bytes always produce the same walk. The offsets are re-verified against the
live text immediately before anything is written, so a stale one is refused
rather than applied in the wrong place.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import asdict, dataclass

from docx import Document
from docx.oxml.ns import qn

from app.services.docx import text as dt

W_P = qn("w:p")
W_TC = qn("w:tc")
W_TR = qn("w:tr")

#: The longest body a tag may have. The longest real one is 69 characters; the
#: cap stops a stray `<` in prose from swallowing a page of text.
MAX_BODY = 150

#: How much of the text before a tag is kept as its context.
CONTEXT_LEAD = 80

#: `<body>`, where the body carries no bracket and no newline -- a tag never
#: spans a paragraph, and a nested bracket is ambiguous.
#:
#: Only UNAMBIGUOUS MARKUP is refused: a closing `</b>` or a self-closing
#: `<p/>`, neither of which is ever a sensible placeholder name. A bare word
#: is a tag, so `<price>`, `<name>` and `<address>` all work.
#:
#: An earlier version refused any bare lowercase word, to throw out HTML
#: someone had pasted into Word. Measured across all five real documents,
#: that rule caught NOTHING -- there is no HTML inside a .docx, only the
#: literal characters if a person pastes web text as plain text -- while it
#: silently dropped exactly the placeholders an author would write.
#:
#: The two mistakes are not equally priced. A tag wrongly refused is silent
#: and reaches the client as a literal `<price>`. A pasted `<b>` wrongly
#: accepted shows up in the upload summary and costs one question that a
#: human dismisses -- and D13 already puts a human in front of every value.
#: So this errs towards asking.
TAG_RE = re.compile(
    r"<(?!/)(?![^<>\n]{0,%d}/>)([^<>\n]{1,%d})>" % (MAX_BODY, MAX_BODY)
)

# `ask_calculate` is first so the alternation never settles for `ask`. The
# whitespace is tolerated because the owner's file contains both `<ask:1 Unit>`
# and `<ask: (10 units)>`.
_ASK_RE = re.compile(r"(ask_calculate|ask)\s*:\s*", re.IGNORECASE)

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Occurrence:
    """One tag, in one place, with everything needed to ask about it and write it."""

    tag_id: str
    kind: str
    raw: str
    default: str | None
    ordinal: int
    start: int
    end: int
    context: str
    duplicate_of: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def parse_tag(body: str) -> tuple[str, str | None]:
    """Split a tag body into its kind and the default the author proposed.

    The default is kept **verbatim**, brackets and punctuation and all: it is a
    proposal to the human, never something the system silently accepts.

    `<ask:>` is an `ask` with no default rather than a semantic tag named
    "ask:". Reading it the other way would let the model fill silently a tag
    the author explicitly marked to be asked, which is what D4 exists to stop.
    """
    match = _ASK_RE.match(body)
    if match is None:
        return "semantic", None
    return match.group(1).lower(), body[match.end():] or None


def scan(docx_bytes: bytes) -> list[Occurrence]:
    """Every tag occurrence in the document, in reading order.

    Reading order, not writing order: the writer sorts right-to-left within
    each paragraph, because replacing left-to-right invalidates every later
    offset in the same paragraph. Ordering that concern lives with the writer.
    """
    doc = Document(io.BytesIO(docx_bytes))
    found: list[Occurrence] = []
    first_seen: dict[str, str] = {}

    for ordinal, paragraph in enumerate(dt.walk_paragraphs(doc)):
        own_text = dt.node_text(paragraph)
        if "<" not in own_text:
            continue
        for nth, match in enumerate(TAG_RE.finditer(own_text)):
            raw = match.group(0)
            kind, default = parse_tag(match.group(1))
            tag_id = _tag_id(ordinal, nth)
            found.append(Occurrence(
                tag_id=tag_id,
                kind=kind,
                raw=raw,
                default=default,
                ordinal=ordinal,
                start=match.start(),
                end=match.end(),
                context=_context_for(paragraph, own_text, match.start(), match.end()),
                duplicate_of=first_seen.get(raw),
            ))
            first_seen.setdefault(raw, tag_id)
    return found


def _tag_id(ordinal: int, nth: int) -> str:
    """D1. Scoped to one template's occurrence map, so a collision across two
    different documents is meaningless and never looked up."""
    return hashlib.sha1(f"{ordinal}#{nth}".encode("utf-8")).hexdigest()[:12]


def _strip_tags(fragment: str) -> str:
    """Text with its own tags removed, so context never quotes a placeholder."""
    return _WS_RE.sub(" ", TAG_RE.sub("", fragment)).strip()


#: A row label made only of digits, or digits with punctuation around them,
#: names nothing -- it is a serial number column.
_SERIAL_RE = re.compile(r"[\W\d_]+")


def _row_label(paragraph) -> str:
    """The first cell of the row this paragraph sits in, or "" outside a table.

    D9: for a tag in `row[19] col[1]` the disambiguating context is
    `row[19] col[0]` -- the item name. Measured, that is exactly what separates
    the four `<ask:1 Unit>` from each other.
    """
    node, cell = paragraph.getparent(), None
    while node is not None:
        if node.tag == W_TC and cell is None:
            cell = node
        if node.tag == W_TR:
            break
        node = node.getparent()
    if node is None or cell is None:
        return ""
    cells = node.findall(W_TC)
    if not cells:
        return ""
    # A SERIAL NUMBER IS NOT A LABEL. Measured on the owner's MOU: the
    # deliverables table numbers its rows 1..10 in column 0 and names the
    # deliverable in column 1, so the first cell gives every row a "label" of
    # "2", "4", "6" -- and seven `<ask:Yes>` become seven questions a person
    # cannot tell apart. Where the first cell is only digits (or punctuation
    # around them), take the next cell that says something instead. Tables
    # whose first column is the item name -- the tagged proposal's "Laptops",
    # "Projector", "Magazine Rack" -- are unaffected, because those are not
    # numbers.
    label = ""
    for cell in cells:
        candidate = _strip_tags(
            " ".join(dt.node_text(p) for p in cell.iter(W_P)))
        if candidate and not _SERIAL_RE.fullmatch(candidate):
            label = candidate
            break
    if len(label) <= CONTEXT_LEAD:
        return label
    # A label cell can hold a paragraph of prose or a nested table, and this
    # string is stored on every occurrence and re-sent in every prompt. Keep
    # the start, where the item name is, and stop at a word boundary.
    head = label[:CONTEXT_LEAD]
    return head.rsplit(" ", 1)[0] if " " in head else head


def _context_for(paragraph, own_text: str, start: int, end: int) -> str:
    """What a person -- and the model -- needs in order to know what this tag is.

    A row label alone cannot separate two tags that share a cell, and in the
    owner's document one cell carries four. So the label is joined to the text
    immediately before the tag, which is the item it belongs to.
    """
    label = _row_label(paragraph)
    lead = _strip_tags(own_text[:start])
    if len(lead) > CONTEXT_LEAD:
        lead = lead[-CONTEXT_LEAD:]
        lead = lead.split(" ", 1)[-1] if " " in lead else lead
    if not label:
        return lead or _strip_tags(own_text[end:])[:CONTEXT_LEAD].strip()
    if not lead or lead == label:
        return label
    return f"{label} - {lead}"
