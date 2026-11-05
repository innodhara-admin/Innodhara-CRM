# app/services/docx/outline.py
"""Parse a .docx into the read-only block outline the console edits against.

The outline is a *view*. It is never written back: the uploaded file is
immutable, and a new upload is a new template version with its own outline.
That immutability is what makes positional paths (`body[7]`,
`body[29]/tr[2]/tc[1]/p[0]`) safe to store in a fill plan.

Each block also carries a fingerprint. Generation verifies it before writing,
so a plan pointed at the wrong document fails loudly instead of silently
putting the client's greeting in the middle of a pricing table.
"""
from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from typing import Any

from docx import Document
from docx.oxml.ns import qn

from app.core.exceptions import ValidationFailedError
from app.services.docx import text as dt

W_P = qn("w:p")
W_TBL = qn("w:tbl")
W_TR = qn("w:tr")
W_TC = qn("w:tc")
W_PPR = qn("w:pPr")
W_PSTYLE = qn("w:pStyle")
W_DRAWING = qn("w:drawing")
W_PICT = qn("w:pict")
W_BLIP = qn("a:blip")
R_EMBED = qn("r:embed")

_HEADING_RE = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
_HEADING_COMPACT = re.compile(r"^heading([1-9])$", re.IGNORECASE)
_PATH_RE = re.compile(r"([a-z]+)(?:\[(\d+)\])?")

# A candidate literal: two to five Title-Case words, no digits or punctuation.
# Narrow on purpose — a suggestion the administrator must accept is cheap, but
# a panel listing four hundred phrases is unusable.
_CANDIDATE_RE = re.compile(r"\b(?:[A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20}){1,4}\b")
_CANDIDATE_STOPWORDS = {
    "Table Of Contents", "All Rights Reserved", "Document Version",
}


class AnchorError(ValidationFailedError):
    """A fill plan points at a block that is not there any more."""


def fingerprint(kind: str, style: str, text: str) -> str:
    payload = f"{kind}|{style}|{(text or '')[:40]}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()[:16]


def _style_of(p) -> str:
    ppr = p.find(W_PPR)
    if ppr is None:
        return ""
    style = ppr.find(W_PSTYLE)
    if style is None:
        return ""
    return style.get(qn("w:val")) or ""


def _heading_level(style: str) -> int | None:
    for pattern in (_HEADING_RE, _HEADING_COMPACT):
        m = pattern.match(style or "")
        if m:
            return int(m.group(1))
    return None


def _image_ids(el) -> list[str]:
    ids = []
    for blip in el.iter(W_BLIP):
        rid = blip.get(R_EMBED)
        if rid:
            ids.append(rid)
    if not ids and (el.find(".//" + W_PICT) is not None or el.find(".//" + W_DRAWING) is not None):
        ids.append("inline")
    return ids


def _paragraph_block(p, path: str, index: int) -> dict[str, Any]:
    style = _style_of(p)
    level = _heading_level(style)
    body = dt.node_text(p)
    images = _image_ids(p)
    if level is not None:
        kind = "heading"
    elif images and not body.strip():
        kind = "image"
    elif not body.strip():
        kind = "empty"
    else:
        kind = "paragraph"
    return {
        "id": f"b{index}",
        "path": path,
        "kind": kind,
        "style": style,
        "level": level,
        "text": body,
        "images": images,
        "table": None,
        "fingerprint": fingerprint(kind, style, body),
    }


def _table_block(tbl, path: str, index: int) -> dict[str, Any]:
    rows = tbl.findall(W_TR)
    header: list[str] = []
    sample: list[list[str]] = []
    for r_i, tr in enumerate(rows[:4]):
        cells = []
        for tc in tr.findall(W_TC):
            cells.append(" ".join(dt.node_text(p) for p in tc.findall(W_P)).strip())
        if r_i == 0:
            header = cells
        sample.append(cells)
    cols = max((len(r) for r in sample), default=0)
    joined = " | ".join(header)
    return {
        "id": f"b{index}",
        "path": path,
        "kind": "table",
        "style": "",
        "level": None,
        "text": joined,
        "images": [],
        "table": {"rows": len(rows), "cols": cols, "header": header, "sample": sample},
        "fingerprint": fingerprint("table", "", joined),
    }


def _walk(root, prefix: str, blocks: list, counter: list) -> None:
    """Top-level children only. Nested paragraphs are reachable through paths,
    but the console flow shows the document's own top-level structure."""
    p_i = tbl_i = 0
    for child in root.iterchildren():
        if child.tag == W_P:
            blocks.append(_paragraph_block(child, f"{prefix}[{p_i + tbl_i}]", counter[0]))
            counter[0] += 1
            p_i += 1
        elif child.tag == W_TBL:
            blocks.append(_table_block(child, f"{prefix}[{p_i + tbl_i}]", counter[0]))
            counter[0] += 1
            tbl_i += 1


def parse(docx_bytes: bytes) -> dict[str, Any]:
    doc = Document(io.BytesIO(docx_bytes))
    blocks: list[dict[str, Any]] = []
    counter = [0]
    _walk(doc.element.body, "body", blocks, counter)

    seen: set[int] = set()
    for s_i, section in enumerate(doc.sections):
        for label, part in (("hdr", section.header), ("ftr", section.footer)):
            if part is None or id(part._element) in seen:
                continue
            seen.add(id(part._element))
            _walk(part._element, f"sec[{s_i}]/{label}/body", blocks, counter)

    headings = [
        {"id": b["id"], "path": b["path"], "level": b["level"], "text": b["text"]}
        for b in blocks if b["kind"] == "heading"
    ]
    media = sorted({
        part.partname.split("/")[-1] for part in doc.part.package.image_parts
    })
    outline = {"blocks": blocks, "headings": headings, "tokens": [], "media": media}
    outline["tokens"] = candidate_tokens(outline)
    return outline


def resolve(doc, path: str):
    """Walk a positional path to its element. Raises AnchorError if absent."""
    node = None
    for segment in path.split("/"):
        m = _PATH_RE.fullmatch(segment)
        if m is None:
            raise AnchorError(f"Malformed anchor '{path}'")
        name, raw_index = m.group(1), m.group(2)
        index = int(raw_index) if raw_index is not None else None
        if name == "body" and node is None:
            node = doc.element.body
            if index is not None:
                node = _nth_block_child(node, index, path)
        elif name == "sec":
            node = ("sec", index)
        elif name in ("hdr", "ftr"):
            if not (isinstance(node, tuple) and node[0] == "sec"):
                raise AnchorError(f"Malformed anchor '{path}'")
            section = doc.sections[node[1]]
            part = section.header if name == "hdr" else section.footer
            node = part._element
        elif name == "body":
            node = _nth_block_child(node, index, path) if index is not None else node
        elif name == "tr":
            node = _nth(node, W_TR, index, path)
        elif name == "tc":
            node = _nth(node, W_TC, index, path)
        elif name == "p":
            node = _nth(node, W_P, index, path)
        else:
            raise AnchorError(f"Unknown anchor segment '{segment}' in '{path}'")
    if node is None or isinstance(node, tuple):
        raise AnchorError(f"Anchor '{path}' does not resolve to an element")
    return node


def _nth_block_child(parent, index: int, path: str):
    children = [c for c in parent.iterchildren() if c.tag in (W_P, W_TBL)]
    if index is None or index >= len(children):
        raise AnchorError(f"Anchor '{path}' is out of range for this document")
    return children[index]


def _nth(parent, tag, index: int | None, path: str):
    if parent is None or index is None:
        raise AnchorError(f"Malformed anchor '{path}'")
    children = parent.findall(tag)
    if index >= len(children):
        raise AnchorError(f"Anchor '{path}' is out of range for this document")
    return children[index]


def _fingerprint_of_element(el) -> str:
    if el.tag == W_TBL:
        rows = el.findall(W_TR)
        header = []
        if rows:
            for tc in rows[0].findall(W_TC):
                header.append(" ".join(dt.node_text(p) for p in tc.findall(W_P)).strip())
        return fingerprint("table", "", " | ".join(header))
    style = _style_of(el)
    level = _heading_level(style)
    body = dt.node_text(el)
    images = _image_ids(el)
    if level is not None:
        kind = "heading"
    elif images and not body.strip():
        kind = "image"
    elif not body.strip():
        kind = "empty"
    else:
        kind = "paragraph"
    return fingerprint(kind, style, body)


def verify(doc, path: str, expected: str):
    el = resolve(doc, path)
    actual = _fingerprint_of_element(el)
    if actual != expected:
        raise AnchorError(
            f"The template block at '{path}' no longer matches what the fill "
            f"plan was built against (expected {expected}, found {actual}). "
            "Re-upload the document and rebuild its placeholders."
        )
    return el


def project_text(outline: dict[str, Any]) -> str:
    """A plain-text rendering of the document.

    Stored as `ProposalTemplate.body_md` for docx templates so every existing
    consumer — draft_check, revisions, the bundle, the Android content view —
    keeps working. Deliberately not Markdown: emitting `##` here would put the
    very markers this feature removes back into the pipeline.
    """
    lines: list[str] = []
    for block in outline["blocks"]:
        if block["kind"] == "table" and block["table"]:
            for row in block["table"]["sample"]:
                lines.append("  ".join(c for c in row if c))
        elif block["kind"] == "image":
            continue
        elif block["text"].strip():
            lines.append(block["text"].strip())
    return "\n\n".join(lines).strip()


def candidate_tokens(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """Repeated Title-Case phrases that look like hand-substituted fill-ins."""
    counts: Counter[str] = Counter()
    where: dict[str, list[str]] = {}
    for block in outline["blocks"]:
        for match in _CANDIDATE_RE.finditer(block["text"] or ""):
            literal = match.group(0)
            if literal in _CANDIDATE_STOPWORDS:
                continue
            counts[literal] += 1
            where.setdefault(literal, [])
            if block["id"] not in where[literal]:
                where[literal].append(block["id"])
    return [
        {"literal": literal, "occurrences": n, "sample_block_ids": where[literal][:5]}
        for literal, n in counts.most_common(60)
    ]
