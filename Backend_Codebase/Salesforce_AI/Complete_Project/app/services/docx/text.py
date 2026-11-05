# app/services/docx/text.py
"""Text access at the `w:t` level, and span replacement that survives it.

**Do not use `Paragraph.runs` anywhere in this feature.** It omits runs nested
in `w:hyperlink` and never descends into text boxes
(`mc:AlternateContent`/`w:pict` -> `w:txbxContent`). Measured against the four
real sample documents, a `.runs`-based walk found 4 of 7, 1 of 7, 1 of 9 and
2 of 14 occurrences of the client-name literal — and the verification pass,
using the same walk, agreed with itself and reported success. The result would
have been a client-facing proposal still reading "School Name".

Word also fragments runs arbitrarily: `School Name` is commonly three runs,
`['School', ' ', 'Name']`, so a `run.text.replace(...)` matches nothing. Every
replacement here works on the *joined* text of a paragraph's own `w:t` nodes
and then writes back across whichever nodes the match covered.
"""
from __future__ import annotations

from typing import Iterator

from docx.oxml.ns import qn

W_P = qn("w:p")
W_T = qn("w:t")
W_TBL = qn("w:tbl")
W_TR = qn("w:tr")
W_TC = qn("w:tc")
W_INSTR = qn("w:instrText")
XML_SPACE = qn("xml:space")

_MAX_REPLACEMENTS = 500


def iter_paragraphs(root) -> Iterator:
    """Every `w:p` under `root`, in document order.

    `.iter()` is a full-tree walk, so this reaches paragraphs inside tables,
    structured document tags and text boxes — all places real templates hide
    text that `doc.paragraphs` never yields.
    """
    return root.iter(W_P)


def own_text_nodes(p) -> list:
    """The `w:t` nodes belonging to `p` itself.

    A text box nests a complete `w:p` inside a run of the outer paragraph. Its
    text is a separate paragraph: splicing it into the outer paragraph's string
    would corrupt offsets and let a replacement write into the wrong place.
    """
    out = []
    for t in p.iter(W_T):
        anc = t.getparent()
        while anc is not None and anc.tag != W_P:
            anc = anc.getparent()
        if anc is p:
            out.append(t)
    return out


def node_text(p) -> str:
    return "".join(t.text or "" for t in own_text_nodes(p))


def replace_span(p, start: int, end: int, replacement: str) -> bool:
    """Replace `[start, end)` of `node_text(p)`. Returns whether anything changed.

    The replacement lands in the node holding `start` and inherits that node's
    run formatting; the rest of the covered range is blanked. Nodes outside the
    span are untouched, so a change to one word cannot restyle a paragraph.
    """
    if start >= end:
        return False
    nodes = own_text_nodes(p)
    spans, offset = [], 0
    for t in nodes:
        s = t.text or ""
        spans.append((t, offset, offset + len(s)))
        offset += len(s)

    def _write(node, value):
        node.text = value
        # a w:t whose value has significant leading/trailing whitespace is
        # collapsed by Word unless xml:space says otherwise
        if value != value.strip():
            node.set(XML_SPACE, "preserve")

    first = True
    for t, t0, t1 in spans:
        if t1 <= start or t0 >= end:
            continue
        s = t.text or ""
        lo, hi = max(start, t0) - t0, min(end, t1) - t0
        if first:
            _write(t, s[:lo] + replacement + s[hi:])
            first = False
        else:
            _write(t, s[:lo] + s[hi:])
    return not first


def replace_token_in_paragraph(p, literal: str, replacement: str) -> int:
    if not literal:
        return 0
    count = 0
    while count < _MAX_REPLACEMENTS:
        found = node_text(p).find(literal)
        if found < 0:
            return count
        if not replace_span(p, found, found + len(literal), replacement):
            return count
        count += 1
    return count


def all_roots(doc) -> list:
    """The body plus every distinct header/footer element in the package.

    Sections share header/footer parts when linked to previous, so identity is
    de-duplicated — otherwise a shared footer is rewritten once per section and
    the occurrence count lies.
    """
    roots = [doc.element.body]
    seen: set[int] = set()
    for section in doc.sections:
        for part in (
            section.header, section.footer,
            section.even_page_header, section.even_page_footer,
            section.first_page_header, section.first_page_footer,
        ):
            if part is None:
                continue
            el = part._element
            if id(el) in seen:
                continue
            seen.add(id(el))
            roots.append(el)
    return roots


def replace_token(doc, literal: str, replacement: str) -> int:
    return sum(
        replace_token_in_paragraph(p, literal, replacement)
        for root in all_roots(doc)
        for p in iter_paragraphs(root)
    )


def count_token(doc, literal: str) -> int:
    if not literal:
        return 0
    return sum(
        node_text(p).count(literal)
        for root in all_roots(doc)
        for p in iter_paragraphs(root)
    )


def walk_paragraphs(doc) -> list:
    """Every paragraph in the document, in the order that defines an ordinal.

    This is the walk this module already uses -- `replace_token` and
    `count_token` are the same comprehension -- named so the simple flow can
    address a tag by a paragraph's position in it (D2). Because it goes through
    `all_roots` and `iter_paragraphs`, anything the rest of this codebase can
    read, the tag writer can write: nested tables, text boxes, headers and
    footers included.

    The position is an address only because the source document is immutable
    (D3): the same bytes always produce the same walk.
    """
    return [p for root in all_roots(doc) for p in iter_paragraphs(root)]


def label_for(doc, ordinal: int) -> str | None:
    """A positional path for a paragraph, for a human to read. Or None.

    `body[71]/tr[19]/tc[1]/p[0]` is what a person can check by eye in a fill
    plan, which is the whole reason this exists. It is **never** what the
    writer uses: measured in plan section 2.3a, the path scheme reaches 5 of
    the 7 places a tag can live and misses a nested table and a text box, both
    of which the four real documents already contain.

    So a label is allowed to be absent, and is never allowed to be wrong.
    Every path returned here resolves, through `outline.resolve`, to the very
    paragraph it was asked about. Anything this cannot address that way gets
    None rather than a plausible-looking guess that would point at some other
    paragraph -- which is worse than no label at all.
    """
    roots = all_roots(doc)
    walk = [p for root in roots for p in iter_paragraphs(root)]
    if not 0 <= ordinal < len(walk):
        return None

    root_ids = {id(r) for r in roots}
    chain, node = [], walk[ordinal]
    while node is not None and id(node) not in root_ids:
        chain.append(node)
        node = node.getparent()
    if node is None:
        return None
    prefix = _root_path(doc, node)
    if prefix is None:
        return None
    chain.reverse()

    if len(chain) == 1:
        block = _block_index(node, chain[0])
        return None if block is None else f"{prefix}[{block}]"
    if len(chain) == 4 and [c.tag for c in chain] == [W_TBL, W_TR, W_TC, W_P]:
        parts = (
            _block_index(node, chain[0]),
            _child_index(chain[0], W_TR, chain[1]),
            _child_index(chain[1], W_TC, chain[2]),
            _child_index(chain[2], W_P, chain[3]),
        )
        if any(part is None for part in parts):
            return None
        return "%s[%d]/tr[%d]/tc[%d]/p[%d]" % ((prefix,) + parts)
    # Deeper than that is a nested table or a text box, and has no path.
    return None


def _root_path(doc, root) -> str | None:
    """The prefix `outline.resolve` accepts for this root, if it has one.

    `all_roots` yields six kinds of header and footer; `resolve` understands
    two. Merely reading `section.even_page_header` creates its definition, so
    an ordinary one-section document already carries four parts that no
    `sec[i]/hdr` or `sec[i]/ftr` path can name. A paragraph in one of those
    gets no label.
    """
    if root is doc.element.body:
        return "body"
    for i, section in enumerate(doc.sections):
        if section.header is not None and section.header._element is root:
            return f"sec[{i}]/hdr/body"
        if section.footer is not None and section.footer._element is root:
            return f"sec[{i}]/ftr/body"
    return None


def _block_index(parent, child) -> int | None:
    """`resolve` numbers paragraphs and tables together, as one block sequence."""
    blocks = [c for c in parent.iterchildren() if c.tag in (W_P, W_TBL)]
    return blocks.index(child) if child in blocks else None


def _child_index(parent, tag, child) -> int | None:
    children = parent.findall(tag)
    return children.index(child) if child in children else None
