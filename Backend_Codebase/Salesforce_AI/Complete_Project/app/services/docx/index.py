# app/services/docx/index.py
"""Detect a document's index and keep it honest after a fill.

Measured against the four real templates on 2026-09-03: three have no index,
and `School_YuviPep 360_2 1.docx` has a **static** one — a `w:sdt` with
`docPartGallery="Table of Contents"` wrapping 32 paragraphs styled TOC1/TOC2/
TOC3, each an internal hyperlink to `_bookmarkN` whose page number is literal
text. `w:instrText` nodes: 0. `w:fldSimple`: 0.

So `w:updateFields` refreshes nothing for this corpus, and the two-pass
LibreOffice route is the primary mechanism rather than a fallback. The `field`
branch is kept because a future upload may genuinely contain a TOC field.
"""
from __future__ import annotations

import io
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import convert
from app.services.docx import text as dt

W_PPR = qn("w:pPr")
W_PSTYLE = qn("w:pStyle")
W_INSTR = qn("w:instrText")
W_FLDSIMPLE = qn("w:fldSimple")
W_HYPERLINK = qn("w:hyperlink")
W_UPDATEFIELDS = qn("w:updateFields")

_TOC_STYLE = re.compile(r"^TOC\d?$", re.IGNORECASE)
_TOC_HEADINGS = {"table of contents", "contents", "index"}
_WS = re.compile(r"\s+")


def _style_of(p) -> str:
    ppr = p.find(W_PPR)
    if ppr is None:
        return ""
    node = ppr.find(W_PSTYLE)
    return (node.get(qn("w:val")) or "") if node is not None else ""


def detect(doc) -> str:
    for root in dt.all_roots(doc):
        for instr in root.iter(W_INSTR):
            if "TOC" in (instr.text or ""):
                return "field"
        for simple in root.iter(W_FLDSIMPLE):
            if "TOC" in (simple.get(qn("w:instr")) or ""):
                return "field"
    body = doc.element.body
    for p in dt.iter_paragraphs(body):
        if _TOC_STYLE.fullmatch(_style_of(p)):
            return "static"
    for p in dt.iter_paragraphs(body):
        if dt.node_text(p).strip().lower() in _TOC_HEADINGS:
            return "static"
    return "none"


def detect_bytes(docx_bytes: bytes) -> str:
    """`detect` for a document still in memory as bytes."""
    from docx import Document

    return detect(Document(io.BytesIO(docx_bytes)))


def static_entries(doc) -> list[dict]:
    """TOC-styled paragraphs, with their label, anchor and page-number node.

    The final `w:t` of the paragraph is the page number; everything before it
    is the label. That holds for the real document and for the shape Word and
    LibreOffice both emit.
    """
    entries: list[dict] = []
    for p_i, p in enumerate(dt.iter_paragraphs(doc.element.body)):
        if not _TOC_STYLE.fullmatch(_style_of(p)):
            continue
        nodes = dt.own_text_nodes(p)
        if len(nodes) < 2:
            continue
        anchor = None
        for link in p.iter(W_HYPERLINK):
            anchor = link.get(qn("w:anchor"))
            break
        label = "".join(t.text or "" for t in nodes[:-1]).strip()
        entries.append({
            "index": p_i,
            "label": _WS.sub(" ", label),
            "anchor": anchor,
            "page_text": nodes[-1].text or "",
        })
    return entries


def mark_fields_dirty(doc) -> None:
    settings = doc.settings.element
    existing = settings.find(W_UPDATEFIELDS)
    if existing is None:
        existing = OxmlElement("w:updateFields")
        settings.append(existing)
    existing.set(qn("w:val"), "true")


def _norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip().lower()


def heading_pages_from_pages(pages: list[str], labels: list[str]) -> dict[str, int]:
    """Map each label to its 1-based page, ignoring the index's own pages.

    Without that exclusion every label resolves to the contents page, because
    the contents page contains all of them. Measured on the real 29-page
    output: 'Investment and Deliverables' matches pages [2, 27]; 2 is the
    index and 27 is the answer.

    A page counts as index if it carries at least half the labels, and never
    fewer than two. The half-rule is what identifies a contents page; the
    floor of two stops a single ordinary page that happens to mention one
    heading from being mistaken for the index. Below two labels there is
    nothing to tell a contents page apart from a real one, so no page is
    excluded and each label simply takes its first occurrence.
    """
    normalised = [_norm(p) for p in pages]
    index_pages = _index_pages(normalised, labels)
    out: dict[str, int] = {}
    for label in labels:
        needle = _norm(label)
        if not needle:
            continue
        for i, page in enumerate(normalised):
            if i in index_pages:
                continue
            if needle in page:
                out[label] = i + 1
                break
    return out


def _index_pages(normalised: list[str], labels: list[str]) -> set[int]:
    """The pages the contents listing itself occupies.

    A page counts as index if it carries at least half the labels, and never
    fewer than two. The half-rule is what identifies a contents page; the
    floor of two stops a single ordinary page that happens to mention one
    heading from being mistaken for the index. Below two labels there is
    nothing to tell a contents page apart from a real one, so no page is
    excluded and each label simply takes its first occurrence.

    Counted over *distinct* labels: a contents listing that repeats a heading
    would otherwise score that heading twice on every page it appears on, and
    an ordinary body page could reach the threshold on one repeated phrase.
    """
    wanted = sorted({_norm(l) for l in labels if l.strip()})
    if len(wanted) < 2:
        return set()
    threshold = max(2, (len(wanted) + 1) // 2)
    return {
        i for i, page in enumerate(normalised)
        if sum(1 for w in wanted if w and w in page) >= threshold
    }


def entry_pages(pages: list[str], labels: list[str]) -> list[int | None]:
    """One page per entry, in order, tolerating a label that repeats.

    `heading_pages` is keyed by label, so a heading listed twice in the
    contents collapses to one answer and the second entry inherits the
    first one's page. Measured on `School_YuviPep 360_2 1.docx`, whose
    contents lists 'INNOVATION BASE COURSE (IBC)' at both page 3 and page 9:
    the keyed route answers 4 for both, where the second belongs on 10, and
    the printed contents then reads ... 9, 4, 10 ...

    A table of contents is monotonic — it lists sections in the order they
    occur — so each entry is resolved at or after the page the previous entry
    resolved to. That fixes the repeat and, on the same document, also moves
    'Innovation Pipeline' off page 3 (where the phrase merely appears in
    passing) onto page 4 with the section it belongs to.
    """
    normalised = [_norm(p) for p in pages]
    index_pages = _index_pages(normalised, labels)

    def _first_at_or_after(needle: str, floor: int) -> int | None:
        for i in range(floor, len(normalised)):
            if i not in index_pages and needle in normalised[i]:
                return i
        return None

    out: list[int | None] = []
    floor = 0
    for label in labels:
        needle = _norm(label)
        hit = None
        if needle:
            hit = _first_at_or_after(needle, floor)
            if hit is None:
                # Out of order, or only ever printed before the contents page:
                # fall back to a whole-document scan rather than give up.
                hit = _first_at_or_after(needle, 0)
        out.append(None if hit is None else hit + 1)
        if hit is not None:
            floor = hit
    return out


def heading_pages(pdf_bytes: bytes, labels: list[str]) -> dict[str, int]:
    return heading_pages_from_pages(_pdf_pages(pdf_bytes), labels)


def _pdf_pages(pdf_bytes: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "") for page in reader.pages]


def refresh_static(docx_bytes: bytes, *, timeout: int = 120) -> bytes:
    """Rewrite a static index's page numbers from a trial PDF render.

    Pass one converts and reads page positions; pass two writes them back. The
    caller converts again afterwards for the PDF it actually ships.
    """
    doc = Document(io.BytesIO(docx_bytes))
    if detect(doc) != "static":
        return docx_bytes
    entries = static_entries(doc)
    if not entries:
        return docx_bytes

    pdf = convert.docx_to_pdf(docx_bytes, timeout=timeout)
    # Resolved per entry, not per label: two entries can share a label.
    resolved = entry_pages(_pdf_pages(pdf), [e["label"] for e in entries])
    if not any(p is not None for p in resolved):
        return docx_bytes

    changed = False
    toc_paragraphs = [
        p for p in dt.iter_paragraphs(doc.element.body)
        if _TOC_STYLE.fullmatch(_style_of(p))
    ]
    for entry, p, page in zip(entries, toc_paragraphs, resolved):
        if page is None:
            continue
        nodes = dt.own_text_nodes(p)
        if not nodes:
            continue
        if (nodes[-1].text or "").strip() != str(page):
            nodes[-1].text = str(page)
            changed = True
    if not changed:
        return docx_bytes
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
