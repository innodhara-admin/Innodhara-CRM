# tests/docx/test_edit.py
import io

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.services.docx import edit, outline as ol, text as dt


def _styled_docx() -> bytes:
    doc = Document()
    doc.add_heading("Pricing Overview", level=1)          # body[0]
    p = doc.add_paragraph("An existing body paragraph with real formatting.")  # body[1]
    p.runs[0].bold = True
    doc.add_paragraph("Another paragraph.")               # body[2]
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def _reopen(doc) -> Document:
    buf = io.BytesIO(); doc.save(buf)
    return Document(io.BytesIO(buf.getvalue()))


def test_inserts_a_paragraph_directly_after_the_anchor():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_after(doc, "body[0]", "body[1]", ["Inserted sentence."])
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert texts[1] == "Inserted sentence."
    assert texts[2] == "An existing body paragraph with real formatting."


def test_inserted_paragraph_inherits_the_reference_run_formatting():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_after(doc, "body[0]", "body[1]", ["Inserted."])
    reopened = _reopen(doc)
    inserted = [p for p in reopened.paragraphs if p.text == "Inserted."][0]
    assert inserted.runs[0].bold is True


def test_inserts_several_paragraphs_in_order():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_after(doc, "body[0]", "body[1]", ["One.", "Two.", "Three."])
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert texts[1:4] == ["One.", "Two.", "Three."]


def test_inserts_before_the_anchor():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_before(doc, "body[2]", "body[1]", ["Before."])
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert texts[2] == "Before."


def test_set_paragraph_text_keeps_the_paragraph_style():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.set_paragraph_text(doc, "body[1]", "Replaced wording, same look.")
    reopened = _reopen(doc)
    para = [p for p in reopened.paragraphs if p.text == "Replaced wording, same look."][0]
    assert para.runs[0].bold is True


def test_editing_refuses_an_anchor_that_does_not_exist():
    doc = Document(io.BytesIO(_styled_docx()))
    with pytest.raises(ol.AnchorError):
        edit.set_paragraph_text(doc, "body[99]", "nope")


def test_set_cell_text_writes_one_cell(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.set_cell_text(doc, table_path, 1, 1, "Rs 8,50,000")
    assert doc.tables[0].cell(1, 1).text == "Rs 8,50,000"


def test_fill_table_expands_rows_and_writes_the_total(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(
        doc, table_path,
        rows=[["Innovation Lab", "Rs 8,50,000"],
              ["Annual Support", "Rs 1,20,000"],
              ["Teacher Training", "Rs 40,000"]],
        header_rows=1,
        total_row={"label_col": 0, "value_col": 1, "value": "Rs 10,10,000"},
        columns=[0, 1],
    )
    t = doc.tables[0]
    assert len(t.rows) == 5                       # 1 header + 3 body + 1 total
    assert t.cell(0, 0).text == "Description"     # header untouched
    assert t.cell(3, 0).text == "Teacher Training"
    assert t.cell(4, 0).text == "Total"           # total label kept
    assert t.cell(4, 1).text == "Rs 10,10,000"


def test_fill_table_contracts_when_there_are_fewer_rows(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(
        doc, table_path, rows=[["Only Item", "Rs 100"]],
        header_rows=1, total_row={"label_col": 0, "value_col": 1, "value": "Rs 100"},
        columns=[0, 1],
    )
    t = doc.tables[0]
    assert len(t.rows) == 3
    assert t.cell(1, 0).text == "Only Item"
    assert t.cell(2, 1).text == "Rs 100"


def test_fill_table_without_a_total_row_leaves_only_body_rows(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(doc, table_path, rows=[["A", "1"], ["B", "2"]],
                    header_rows=1, total_row=None, columns=[0, 1])
    assert len(doc.tables[0].rows) == 3


@pytest.mark.parametrize("total_row", [
    {"label_col": 0, "value_col": 1, "value": "Rs 3"},
    None,
])
def test_fill_table_with_no_header_row_keeps_the_table_well_formed(table_docx, total_row):
    # A w:tbl must begin w:tblPr, w:tblGrid, then its rows. Inserting a row at
    # index 0 puts it before both; LibreOffice renders that anyway, so only the
    # element order catches it.
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(doc, table_path, rows=[["A", "1"], ["B", "2"]],
                    header_rows=0, total_row=total_row, columns=[0, 1])
    tbl = doc.tables[0]._tbl
    tags = [child.tag for child in tbl.iterchildren()]
    assert tags[0] == qn("w:tblPr")
    assert tags.index(qn("w:tblGrid")) < tags.index(qn("w:tr"))
    body = doc.tables[0]
    assert [body.cell(0, 0).text, body.cell(1, 0).text] == ["A", "B"]


def test_remove_paragraph_drops_it():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.remove_paragraph(doc, "body[2]")
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert "Another paragraph." not in texts
