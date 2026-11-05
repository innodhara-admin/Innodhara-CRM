# app/services/email_render.py
"""A filled Word email becomes what an email client shows (28 Oct 2026).

The first non-empty paragraph is the subject, written `Subject: ...`. The rest
of the body becomes two parts of the same email: HTML with inline styles (mail
clients drop `<style>` blocks, so nothing here relies on one) and plain text
for clients that cannot show HTML. Headers and footers are not part of an
email and are ignored.

Covered on purpose, because the developer's templates use them: bold, italic,
underline, links, bulleted and numbered lists, line breaks inside a paragraph,
and headings. Images and text boxes are not (the spec's non-goals).
"""
from __future__ import annotations

import html
import io
import re
from collections import Counter
from dataclasses import dataclass

from docx import Document
from docx.oxml.ns import qn

from app.core.exceptions import ValidationFailedError
from app.services.docx import text as dt

NO_SUBJECT = (
    "The first line of an email template must be the subject, written as "
    "Subject: ... For example: Subject: Proposal for <School Name>."
)

_SUBJECT_RE = re.compile(r"^\s*subject\s*:\s*", re.IGNORECASE)
_FALLBACK_FONT = "Arial, sans-serif"

W_P, W_R, W_T = qn("w:p"), qn("w:r"), qn("w:t")
W_BR, W_TAB, W_CR = qn("w:br"), qn("w:tab"), qn("w:cr")
W_HYPERLINK, W_TBL = qn("w:hyperlink"), qn("w:tbl")
W_PPR, W_RPR, W_NUMPR = qn("w:pPr"), qn("w:rPr"), qn("w:numPr")
W_PSTYLE, W_NUMID, W_ILVL = qn("w:pStyle"), qn("w:numId"), qn("w:ilvl")
W_VAL = qn("w:val")
R_ID = qn("r:id")


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def subject_paragraph(docx_bytes: bytes) -> tuple[int, str] | None:
    """(walk ordinal, subject text) of the subject line, or None.

    The ordinal is in `docx.text.walk_paragraphs` order -- the same order that
    addresses tags -- so a caller can tell which tags sit in the subject.
    """
    doc = Document(io.BytesIO(docx_bytes))
    return _subject_in(doc)


def render(docx_bytes: bytes) -> RenderedEmail:
    doc = Document(io.BytesIO(docx_bytes))
    found = _subject_in(doc)
    if found is None:
        raise ValidationFailedError(NO_SUBJECT)
    subject_p = dt.walk_paragraphs(doc)[found[0]]
    renderer = _Renderer(doc)
    blocks_html, blocks_text = renderer.body(skip=subject_p)
    font, size = renderer.base_font()
    wrapper = (f'<div style="font-family:{html.escape(font, quote=True)};'
               f'font-size:{size}pt;color:#1f1f1f;line-height:1.45">')
    return RenderedEmail(
        subject=found[1],
        html=wrapper + "\n".join(blocks_html) + "</div>",
        text="\n\n".join(t for t in blocks_text if t.strip()).strip() + "\n",
    )


def _subject_in(doc) -> tuple[int, str] | None:
    for ordinal, p in enumerate(dt.walk_paragraphs(doc)):
        if not _in_body(doc, p):
            continue
        text = dt.node_text(p)
        if not text.strip():
            continue
        match = _SUBJECT_RE.match(text)
        if match is None:
            return None
        return ordinal, text[match.end():].strip()
    return None


def _in_body(doc, p) -> bool:
    node = p
    body = doc.element.body
    while node is not None:
        if node is body:
            return True
        node = node.getparent()
    return False


class _Renderer:
    def __init__(self, doc):
        self.doc = doc
        self.part = doc.part
        self.fonts: Counter[str] = Counter()
        self.sizes: Counter[float] = Counter()
        self._num_formats = self._read_numbering()

    # --- the document's own defaults ---------------------------------------

    def base_font(self) -> tuple[str, float]:
        font = self.fonts.most_common(1)[0][0] if self.fonts else None
        if font is None:
            try:
                font = self.doc.styles["Normal"].font.name
            except KeyError:
                font = None
        size = self.sizes.most_common(1)[0][0] if self.sizes else None
        if size is None:
            try:
                normal = self.doc.styles["Normal"].font.size
                size = normal.pt if normal is not None else None
            except KeyError:
                size = None
        family = f"'{font}', {_FALLBACK_FONT}" if font else _FALLBACK_FONT
        return family, size or 11.0

    def _read_numbering(self) -> dict[tuple[str, str], str]:
        """(numId, ilvl) -> numFmt ("bullet", "decimal", ...)."""
        try:
            numbering = self.part.numbering_part.element
        except (KeyError, NotImplementedError, AttributeError):
            return {}
        abstract: dict[str, dict[str, str]] = {}
        for a in numbering.findall(qn("w:abstractNum")):
            levels = {}
            for lvl in a.findall(qn("w:lvl")):
                fmt = lvl.find(qn("w:numFmt"))
                levels[lvl.get(qn("w:ilvl"))] = (
                    fmt.get(W_VAL) if fmt is not None else "decimal")
            abstract[a.get(qn("w:abstractNumId"))] = levels
        out: dict[tuple[str, str], str] = {}
        for num in numbering.findall(qn("w:num")):
            ref = num.find(qn("w:abstractNumId"))
            levels = abstract.get(ref.get(W_VAL) if ref is not None else "", {})
            for ilvl, fmt in levels.items():
                out[(num.get(qn("w:numId")), ilvl)] = fmt
        return out

    # --- blocks --------------------------------------------------------------

    def body(self, *, skip) -> tuple[list[str], list[str]]:
        out_html: list[str] = []
        out_text: list[str] = []
        pending: list[tuple[str, str, str]] = []  # (kind, li html, li text)

        def flush():
            if not pending:
                return
            kind = pending[0][0]
            tag = "ul" if kind == "bullet" else "ol"
            items = "\n".join(
                f'<li style="margin:0 0 4px 0">{h}</li>' for _, h, _ in pending)
            out_html.append(
                f'<{tag} style="margin:0 0 12px 0;padding-left:24px">\n'
                f"{items}\n</{tag}>")
            lines = [
                (f"• {t}" if kind == "bullet" else f"{i}. {t}")
                for i, (_, _, t) in enumerate(pending, start=1)
            ]
            out_text.append("\n".join(lines))
            pending.clear()

        for block in self.doc.element.body.iterchildren():
            if block.tag == W_TBL:
                flush()
                h, t = self._table(block)
                out_html.append(h)
                out_text.append(t)
                continue
            if block.tag != W_P or block is skip:
                continue
            inner_html, inner_text = self._inline(block)
            if not inner_text.strip():
                continue
            kind = self._list_kind(block)
            if kind is not None:
                if pending and pending[0][0] != kind:
                    flush()
                pending.append((kind, inner_html, inner_text))
                continue
            flush()
            if self._is_heading(block):
                out_html.append(
                    f'<p style="margin:0 0 12px 0"><strong>{inner_html}</strong></p>')
            else:
                out_html.append(f'<p style="margin:0 0 12px 0">{inner_html}</p>')
            out_text.append(inner_text)
        flush()
        return out_html, out_text

    def _table(self, tbl) -> tuple[str, str]:
        rows_html, rows_text = [], []
        for tr in tbl.findall(qn("w:tr")):
            cells_html, cells_text = [], []
            for tc in tr.findall(qn("w:tc")):
                parts = [self._inline(p) for p in tc.findall(W_P)]
                cells_html.append(
                    '<td style="border:1px solid #cccccc;padding:4px 8px">'
                    + "<br>".join(h for h, t in parts if t.strip()) + "</td>")
                cells_text.append(" ".join(t for _, t in parts if t.strip()))
            rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
            rows_text.append(" | ".join(cells_text))
        return ('<table style="border-collapse:collapse;margin:0 0 12px 0">'
                + "".join(rows_html) + "</table>", "\n".join(rows_text))

    def _list_kind(self, p) -> str | None:
        num_pr = p.find(f"{W_PPR}/{W_NUMPR}")
        if num_pr is None:
            num_pr = self._style_num_pr(p)
        if num_pr is None:
            return None
        num_id = num_pr.find(W_NUMID)
        if num_id is None or num_id.get(W_VAL) in (None, "0"):
            return None
        ilvl = num_pr.find(W_ILVL)
        fmt = self._num_formats.get(
            (num_id.get(W_VAL), ilvl.get(W_VAL) if ilvl is not None else "0"),
            "decimal")
        return "bullet" if fmt in ("bullet", "none") else "number"

    def _style_num_pr(self, p):
        style_el = p.find(f"{W_PPR}/{W_PSTYLE}")
        if style_el is None:
            return None
        try:
            style = self.doc.styles.get_by_id(style_el.get(W_VAL), 1)
        except Exception:  # noqa: BLE001 -- an unknown style is not a list
            return None
        while style is not None:
            ppr = style.element.find(W_PPR)
            if ppr is not None and ppr.find(W_NUMPR) is not None:
                return ppr.find(W_NUMPR)
            style = style.base_style
        return None

    def _is_heading(self, p) -> bool:
        style_el = p.find(f"{W_PPR}/{W_PSTYLE}")
        value = style_el.get(W_VAL) if style_el is not None else ""
        return value.startswith("Heading") or value.startswith("Title")

    # --- inline --------------------------------------------------------------

    def _inline(self, p) -> tuple[str, str]:
        """The paragraph's own runs, in order, links grouped into one <a>."""
        out_html: list[str] = []
        out_text: list[str] = []
        link_href: str | None = None
        link_html: list[str] = []
        link_text: list[str] = []

        def close_link():
            nonlocal link_href
            if link_href is None:
                return
            label_text = "".join(link_text)
            out_html.append(
                f'<a href="{html.escape(link_href, quote=True)}" '
                f'style="color:#1155cc">{"".join(link_html)}</a>')
            target = link_href[7:] if link_href.startswith("mailto:") else link_href
            if label_text and label_text.strip() not in target \
                    and target.rstrip("/") not in label_text:
                out_text.append(f"{label_text} ({target})")
            else:
                out_text.append(label_text)
            link_href = None
            link_html.clear()
            link_text.clear()

        for run in self._own_runs(p):
            href = self._href_of(run)
            run_html, run_text = self._run(run, linkify=href is None)
            if href is not None:
                if link_href is not None and href != link_href:
                    close_link()
                link_href = href
                link_html.append(run_html)
                link_text.append(run_text)
                continue
            close_link()
            out_html.append(run_html)
            out_text.append(run_text)
        close_link()
        return "".join(out_html), "".join(out_text)

    def _own_runs(self, p):
        for r in p.iter(W_R):
            anc = r.getparent()
            while anc is not None and anc.tag != W_P:
                anc = anc.getparent()
            if anc is p:
                yield r

    def _href_of(self, run) -> str | None:
        node = run.getparent()
        while node is not None and node.tag != W_P:
            if node.tag == W_HYPERLINK:
                rid = node.get(R_ID)
                if rid and rid in self.part.rels:
                    return self.part.rels[rid].target_ref
                anchor = node.get(qn("w:anchor"))
                return f"#{anchor}" if anchor else None
            node = node.getparent()
        return None

    def _run(self, run, *, linkify: bool = False) -> tuple[str, str]:
        pieces_html: list[str] = []
        pieces_text: list[str] = []
        for child in run.iterchildren():
            if child.tag == W_T:
                escaped = html.escape(child.text or "", quote=False)
                pieces_html.append(_linkify(escaped) if linkify else escaped)
                pieces_text.append(child.text or "")
            elif child.tag in (W_BR, W_CR):
                pieces_html.append("<br>")
                pieces_text.append("\n")
            elif child.tag == W_TAB:
                pieces_html.append("&nbsp;&nbsp;&nbsp;&nbsp;")
                pieces_text.append("    ")
        body = "".join(pieces_html)
        text = "".join(pieces_text)
        rpr = run.find(W_RPR)
        if rpr is not None and text.strip():
            fonts = rpr.find(qn("w:rFonts"))
            if fonts is not None and fonts.get(qn("w:ascii")):
                self.fonts[fonts.get(qn("w:ascii"))] += len(text)
            size = rpr.find(qn("w:sz"))
            if size is not None and (size.get(W_VAL) or "").isdigit():
                self.sizes[int(size.get(W_VAL)) / 2] += len(text)
            if body:
                if _on(rpr, "w:u"):
                    body = f"<u>{body}</u>"
                if _on(rpr, "w:i"):
                    body = f"<em>{body}</em>"
                if _on(rpr, "w:b"):
                    body = f"<strong>{body}</strong>"
        return body, text


#: A web address typed as plain text, in already-escaped HTML. Trailing
#: sentence punctuation is not part of it.
_URL_RE = re.compile(r"https?://[^\s<]+?(?=[.,;:!?)]*(?:\s|<|$))")


def _linkify(escaped: str) -> str:
    """Make a typed web address clickable: the links an email asks for (the
    impact videos, the highlights) are answered as plain text, and a mail
    client is not obliged to link them on its own."""
    return _URL_RE.sub(
        lambda m: f'<a href="{m.group(0)}" style="color:#1155cc">{m.group(0)}</a>',
        escaped)


def _on(rpr, name: str) -> bool:
    el = rpr.find(qn(name))
    if el is None:
        return False
    value = el.get(W_VAL)
    return value not in ("0", "false", "none")
