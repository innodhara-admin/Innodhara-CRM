# tests/docx/test_ocr.py
import io
import shutil

import pytest
from docx import Document
from docx.shared import Inches

from app.services.docx import ocr

needs_tesseract = pytest.mark.skipif(
    shutil.which(ocr.TESSERACT) is None and not __import__("pathlib").Path(ocr.TESSERACT).exists(),
    reason="tesseract not installed",
)


def _docx_with_text_image(tmp_path, words="PRICING OVERVIEW"):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (900, 220), "white")
    ImageDraw.Draw(img).text((30, 80), words, fill="black")
    png = tmp_path / "label.png"
    img.save(png)
    doc = Document()
    doc.add_paragraph("Intro")
    doc.add_picture(str(png), width=Inches(5))
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


@needs_tesseract
def test_reads_words_out_of_an_embedded_image(tmp_path):
    result = ocr.ocr_document(_docx_with_text_image(tmp_path))
    assert len(result) == 1
    assert "PRICING" in " ".join(result.values()).upper()


def test_a_document_with_no_images_returns_an_empty_map():
    doc = Document()
    doc.add_paragraph("No pictures here.")
    buf = io.BytesIO(); doc.save(buf)
    assert ocr.ocr_document(buf.getvalue()) == {}


def test_an_unreadable_image_maps_to_empty_string_and_does_not_raise(monkeypatch, tmp_path):
    data = _docx_with_text_image(tmp_path)
    monkeypatch.setattr(ocr, "TESSERACT", "/nonexistent/tesseract")
    result = ocr.ocr_document(data)
    assert set(result.values()) == {""}


def test_respects_the_image_cap(monkeypatch, tmp_path):
    data = _docx_with_text_image(tmp_path)
    result = ocr.ocr_document(data, max_images=0)
    assert result == {}
