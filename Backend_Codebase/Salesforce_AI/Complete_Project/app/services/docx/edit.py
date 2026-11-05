# app/services/docx/edit.py
"""Structural edits to a loaded document.

Everything here mutates a document that was loaded from the immutable source
file. Nothing constructs a paragraph from scratch: a new paragraph is a clone
of a real one in the same document, stripped of its content, so it inherits
that document's font, size, spacing, justification and theme without this
module knowing any of them.

This is what keeps generated prose visually indistinguishable from the
template's own body text — and it is why the model can be asked for plain text
rather than any markup.
"""
from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import outline as ol
from app.services.docx import text as dt

W_P = qn("w:p")
W_TBL = qn("w:tbl")
W_TR = qn("w:tr")
W_TC = qn("w:tc")
W_PPR = qn("w:pPr")
W_R = qn("w:r")
W_RPR = qn("w:rPr")
W_PSTYLE = qn("w:pStyle")
W_NUMPR = qn("w:numPr")
XML_SPACE = qn("xml:space")


def _blank_clone(style_ref_p, text: str, list_style: str | None):
    """A paragraph shaped like `style_ref_p`, carrying exactly `text`."""
    new_p = copy.deepcopy(style_ref_p)
    for child in list(new_p):
        if child.tag != W_PPR:
            new_p.remove(child)
    if list_style:
        ppr = new_p.find(W_PPR)
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            new_p.insert(0, ppr)
        for existing in ppr.findall(W_PSTYLE):
            ppr.remove(existing)
        for existing in ppr.findall(W_NUMPR):
            ppr.remove(existing)
        style_el = OxmlElement("w:pStyle")
        style_el.set(qn("w:val"), list_style)
        ppr.insert(0, style_el)

    run = OxmlElement("w:r")
    src_run = style_ref_p.find(W_R)
    if src_run is not None:
        src_rpr = src_run.find(W_RPR)
        if src_rpr is not None:
            run.append(copy.deepcopy(src_rpr))
    t = OxmlElement("w:t")
    t.text = text
    t.set(XML_SPACE, "preserve")
    run.append(t)
    new_p.append(run)
    return new_p


def _insert(doc, anchor_path, style_ref_path, texts, list_style, before):
    anchor = ol.resolve(doc, anchor_path)
    style_ref = ol.resolve(doc, style_ref_path)
    if style_ref.tag != W_P:
        raise ol.AnchorError(
            f"The style reference '{style_ref_path}' is not a paragraph, so "
            "there is no formatting to copy."
        )
    created = []
    if before:
        for text in texts:
            new_p = _blank_clone(style_ref, text, list_style)
            anchor.addprevious(new_p)
            created.append(new_p)
    else:
        cursor = anchor
        for text in texts:
            new_p = _blank_clone(style_ref, text, list_style)
            cursor.addnext(new_p)
            cursor = new_p
            created.append(new_p)
    return created


def insert_paragraphs_after(doc, anchor_path, style_ref_path, texts, *, list_style=None):
    return _insert(doc, anchor_path, style_ref_path, list(texts), list_style, before=False)


def insert_paragraphs_before(doc, anchor_path, style_ref_path, texts, *, list_style=None):
    return _insert(doc, anchor_path, style_ref_path, list(texts), list_style, before=True)


def set_paragraph_text(doc, path: str, text: str) -> None:
    p = ol.resolve(doc, path)
    if p.tag != W_P:
        raise ol.AnchorError(f"'{path}' is not a paragraph")
    _write_paragraph_text(p, text)


def _write_paragraph_text(p, text: str) -> None:
    current = dt.node_text(p)
    if current:
        dt.replace_span(p, 0, len(current), text)
        return
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    t.set(XML_SPACE, "preserve")
    run.append(t)
    p.append(run)


def _table_at(doc, path: str):
    tbl = ol.resolve(doc, path)
    if tbl.tag != W_TBL:
        raise ol.AnchorError(f"'{path}' is not a table")
    return tbl


def _cell_paragraphs(tc):
    return tc.findall(W_P)


def _write_cell(tc, text: str) -> None:
    paragraphs = _cell_paragraphs(tc)
    if not paragraphs:
        p = OxmlElement("w:p")
        tc.append(p)
        paragraphs = [p]
    _write_paragraph_text(paragraphs[0], text)
    for extra in paragraphs[1:]:
        tc.remove(extra)


def set_cell_text(doc, table_path: str, row: int, col: int, text: str) -> None:
    tbl = _table_at(doc, table_path)
    rows = tbl.findall(W_TR)
    if row >= len(rows):
        raise ol.AnchorError(f"Row {row} is out of range for the table at '{table_path}'")
    cells = rows[row].findall(W_TC)
    if col >= len(cells):
        raise ol.AnchorError(f"Column {col} is out of range for the table at '{table_path}'")
    _write_cell(cells[col], text)


def fill_table(doc, table_path: str, rows, *, header_rows: int,
               total_row: dict | None, columns: list[int]) -> None:
    """Write body rows into an existing table, keeping its styling.

    Body rows are cloned from the template's own first body row, so borders,
    shading and fonts come from the document rather than from this code. The
    header rows are never touched. A total row keeps its label and gets only
    its value written — the label is the organisation's wording, not ours.
    """
    tbl = _table_at(doc, table_path)
    tr_list = tbl.findall(W_TR)
    if len(tr_list) <= header_rows:
        raise ol.AnchorError(
            f"The table at '{table_path}' has no body row to use as a template."
        )

    total_tr = tr_list[-1] if total_row else None
    body_trs = tr_list[header_rows:len(tr_list) - (1 if total_row else 0)]
    if not body_trs:
        raise ol.AnchorError(
            f"The table at '{table_path}' has no body row to use as a template."
        )

    template_tr = copy.deepcopy(body_trs[0])
    for tr in body_trs:
        tbl.remove(tr)

    anchor = tr_list[header_rows - 1] if header_rows else None
    cursor = anchor
    for values in rows:
        new_tr = copy.deepcopy(template_tr)
        cells = new_tr.findall(W_TC)
        for position, col in enumerate(columns):
            if col < len(cells) and position < len(values):
                _write_cell(cells[col], str(values[position]))
        for idx, tc in enumerate(cells):
            if idx not in columns:
                _write_cell(tc, "")
        if cursor is not None:
            cursor.addnext(new_tr)
        elif total_tr is not None:
            # No header row to hang off. Position relative to the rows that
            # are left rather than at index 0: a w:tbl begins with w:tblPr
            # and w:tblGrid, and a w:tr placed before them is invalid per
            # CT_Tbl — LibreOffice renders it anyway, Word calls the file
            # corrupt and offers to repair it.
            total_tr.addprevious(new_tr)
        else:
            tbl.append(new_tr)
        cursor = new_tr

    if total_row and total_tr is not None:
        cells = total_tr.findall(W_TC)
        value_col = total_row["value_col"]
        if value_col < len(cells):
            _write_cell(cells[value_col], str(total_row["value"]))


def remove_paragraph(doc, path: str) -> None:
    p = ol.resolve(doc, path)
    parent = p.getparent()
    if parent is not None:
        parent.remove(p)
