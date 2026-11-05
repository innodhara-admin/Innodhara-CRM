import pytest
from docx import Document
import io

from app.core.exceptions import ExternalServiceError
from app.services.docx import convert


def _tiny_docx() -> bytes:
    doc = Document()
    doc.add_heading("Hello", level=1)
    doc.add_paragraph("A sentence that will appear in the PDF text layer.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_converts_docx_to_pdf():
    pdf = convert.docx_to_pdf(_tiny_docx())
    assert pdf[:5] == b"%PDF-"
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "will appear in the PDF text layer" in text


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(convert, "SOFFICE", "/nonexistent/soffice")
    with pytest.raises(ExternalServiceError) as err:
        convert.docx_to_pdf(_tiny_docx())
    assert "LibreOffice" in str(err.value)


def test_garbage_input_raises():
    with pytest.raises(ExternalServiceError):
        convert.docx_to_pdf(b"this is not a docx")
