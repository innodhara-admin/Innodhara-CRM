"""The proposal PDF looks like the Word document (13 Oct 2026).

The PDF of the Innodhara proposal sent on 12 Oct had an 11 pt cover title,
four extra pages and overlapping tables. Measured: the untouched template
printed the same way, so the cause was the converter, not the fill --
LibreOffice 7.3, none of the templates' fonts on the server, a picture in a
paragraph with a hidden mark, and Word's "- 5 -" page numbers.

The unit tests need no LibreOffice. The rendering tests convert with whatever
soffice the settings name, so on the old 7.3 the title test fails, which is
the defect it exists to catch.
"""
from __future__ import annotations

import io
import zipfile

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm

from app.config import Settings
from app.services.docx import convert, lo_compat

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# --- documents shaped like the owner's templates -----------------------------


def _png() -> io.BytesIO:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (120, 120), (200, 30, 30)).save(buf, "PNG")
    buf.seek(0)
    return buf


def _save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _hide_mark(paragraph) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    ppr.append(parse_xml(f"<w:rPr {nsdecls('w')}><w:vanish/></w:rPr>"))


def _anchored_picture(paragraph) -> None:
    """A picture floating behind the text, as the templates' cover art is."""
    run = paragraph.add_run()
    run.add_picture(_png(), width=Cm(8))
    inline = run._r.find(".//" + qn("wp:inline"))
    anchor = parse_xml(
        f'<wp:anchor {nsdecls("wp")} distT="0" distB="0" distL="0" distR="0" '
        'simplePos="0" relativeHeight="1" behindDoc="1" locked="0" '
        'layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="page"><wp:posOffset>720000</wp:posOffset>'
        '</wp:positionH><wp:positionV relativeFrom="paragraph">'
        '<wp:posOffset>0</wp:posOffset></wp:positionV></wp:anchor>')
    anchor.append(inline.find(qn("wp:extent")))
    anchor.append(parse_xml(f"<wp:wrapNone {nsdecls('wp')}/>"))
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        node = inline.find(qn(tag))
        if node is not None:
            anchor.append(node)
    inline.getparent().replace(inline, anchor)


def _cover_art_doc() -> bytes:
    doc = Document()
    art = doc.add_paragraph()
    _anchored_picture(art)
    _hide_mark(art)
    doc.add_paragraph("Text after the cover art")
    return _save(doc)


def _title_control_doc() -> bytes:
    """The cover's school name: a plain-text control bound to the Title."""
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(parse_xml(
        f"<w:sdt {nsdecls('w')}><w:sdtPr><w:rPr><w:b/><w:sz w:val=\"72\"/>"
        "</w:rPr><w:alias w:val=\"Title\"/><w:text/></w:sdtPr><w:sdtContent>"
        "<w:r><w:rPr><w:b/><w:sz w:val=\"72\"/><w:szCs w:val=\"72\"/></w:rPr>"
        "<w:t>Sunrise Public School</w:t></w:r></w:sdtContent></w:sdt>"))
    doc.add_paragraph("Body text")
    return _save(doc)


def _dash_footer_doc(simple: bool = False) -> bytes:
    doc = Document()
    doc.add_paragraph("Page body")
    footer = doc.sections[0].footer.paragraphs[0]
    if simple:
        footer._p.append(parse_xml(
            f"<w:fldSimple {nsdecls('w')} w:instr=\" PAGE  \\* ArabicDash \">"
            "<w:r><w:t>- 1 -</w:t></w:r></w:fldSimple>"))
    else:
        for xml in ("<w:r><w:fldChar w:fldCharType=\"begin\"/></w:r>",
                    "<w:r><w:instrText xml:space=\"preserve\"> PAGE  \\* "
                    "ArabicDash  \\* MERGEFORMAT </w:instrText></w:r>",
                    "<w:r><w:fldChar w:fldCharType=\"separate\"/></w:r>",
                    "<w:r><w:t>- 1 -</w:t></w:r>",
                    "<w:r><w:fldChar w:fldCharType=\"end\"/></w:r>"):
            footer._p.append(parse_xml(xml.replace("<w:r>", f"<w:r {nsdecls('w')}>", 1)))
    return _save(doc)


def _part(docx: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(docx)).read(name).decode("utf-8")


def _footer_name(docx: bytes) -> str:
    return next(n for n in zipfile.ZipFile(io.BytesIO(docx)).namelist()
                if n.startswith("word/footer"))


# --- lo_compat: the copy LibreOffice reads (no LibreOffice needed) -----------


def test_picture_in_a_hidden_mark_paragraph_is_unhidden_and_thin():
    before = _cover_art_doc()
    after = lo_compat.prepare(before)
    xml = _part(after, "word/document.xml")
    assert "vanish" not in xml
    assert 'w:line="20"' in xml and 'w:lineRule="exact"' in xml
    assert "vanish" in _part(before, "word/document.xml")  # the input is kept


def test_a_hidden_mark_with_words_is_left_alone():
    doc = Document()
    p = doc.add_paragraph("Words, no picture")
    _hide_mark(p)
    before = _save(doc)
    assert lo_compat.prepare(before) == before


def test_a_picture_without_a_hidden_mark_is_left_alone():
    doc = Document()
    _anchored_picture(doc.add_paragraph())
    before = _save(doc)
    assert lo_compat.prepare(before) == before


def test_nothing_to_do_returns_the_same_bytes():
    before = _title_control_doc()
    assert lo_compat.prepare(before) == before


def test_only_the_changed_part_differs():
    before = _cover_art_doc()
    after = lo_compat.prepare(before)
    zin, zout = (zipfile.ZipFile(io.BytesIO(b)) for b in (before, after))
    assert zin.namelist() == zout.namelist()
    for name in zin.namelist():
        if name != "word/document.xml":
            assert zin.read(name) == zout.read(name), name


@pytest.mark.parametrize("simple", [False, True])
def test_arabic_dash_page_number_becomes_dashes_around_a_plain_page(simple):
    before = _dash_footer_doc(simple)
    after = lo_compat.prepare(before)
    xml = _part(after, _footer_name(after))
    assert "ArabicDash" not in xml and "PAGE" in xml
    assert ">- </w:t>" in xml and "> -</w:t>" in xml


def test_a_broken_document_is_converted_as_it_arrived():
    garbage = b"PK\x03\x04 not really a zip"
    assert lo_compat.prepare(garbage) == garbage


# --- convert.docx_to_pdf: what LibreOffice is handed -------------------------


class _FakeSoffice:
    """Stands in for LibreOffice: records what it was handed, writes a PDF."""

    seen: dict = {}

    def __init__(self, cmd, **kwargs):
        from pathlib import Path

        work = Path(cmd[-1]).parent
        fonts = work / ".fonts"
        conf = work / ".config" / "fontconfig" / "fonts.conf"
        type(self).seen.update(
            docx=(work / "in.docx").read_bytes(),
            fonts_target=fonts.resolve() if fonts.exists() else None,
            conf_target=conf.resolve() if conf.exists() else None,
            new_session=kwargs.get("start_new_session"))
        (work / "in.pdf").write_bytes(b"%PDF-1.4 fake")
        self.returncode, self.pid = 0, 0

    def communicate(self, timeout=None):
        return b"", b""


@pytest.fixture
def fake_soffice(monkeypatch):
    _FakeSoffice.seen = {}
    monkeypatch.setattr(convert.subprocess, "Popen", _FakeSoffice)
    monkeypatch.setattr(convert, "SOFFICE", "/bin/sh")
    monkeypatch.setattr(convert, "FALLBACK_SOFFICE", "")
    monkeypatch.setattr(convert, "FONTS_DIR", "")
    return _FakeSoffice.seen


def test_libreoffice_gets_the_prepared_copy_and_the_document_is_unchanged(fake_soffice):
    original = _cover_art_doc()
    keep = bytes(original)
    convert.docx_to_pdf(original)
    assert original == keep
    assert "vanish" not in _part(fake_soffice["docx"], "word/document.xml")
    assert fake_soffice["new_session"] is True


def test_the_converter_fonts_folder_is_its_home_fonts(fake_soffice, monkeypatch, tmp_path):
    (tmp_path / "fonts.conf").write_text("<fontconfig/>")
    monkeypatch.setattr(convert, "FONTS_DIR", str(tmp_path))
    convert.docx_to_pdf(_title_control_doc())
    assert fake_soffice["fonts_target"] == tmp_path.resolve()
    assert fake_soffice["conf_target"] == (tmp_path / "fonts.conf").resolve()


def test_a_missing_fonts_folder_does_not_stop_the_pdf(fake_soffice, monkeypatch, tmp_path):
    monkeypatch.setattr(convert, "FONTS_DIR", str(tmp_path / "gone"))
    assert convert.docx_to_pdf(_title_control_doc()).startswith(b"%PDF")
    assert fake_soffice["fonts_target"] is None


# --- a LibreOffice that never finishes (real processes, no LibreOffice) ------


def _script(path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


def _hanging(tmp_path) -> str:
    """Starts a child and sleeps, the way soffice.bin outlives its launcher."""
    return _script(tmp_path / "hangs.sh",
                   f"sleep 300 &\necho $! > {tmp_path}/child.pid\nwait\n")


def _working(tmp_path) -> str:
    """Writes in.pdf into --outdir, the one thing the converter reads."""
    return _script(tmp_path / "works.sh",
                   'while [ "$1" != "--outdir" ]; do shift; done\n'
                   'printf "%%PDF-1.4 fallback" > "$2/in.pdf"\n')


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A killed child the shell has not reaped yet is a zombie, not running.
    with open(f"/proc/{pid}/stat") as stat:
        return stat.read().split()[2] != "Z"


def test_a_hanging_libreoffice_falls_back_and_leaves_nothing_running(monkeypatch, tmp_path):
    import time

    monkeypatch.setattr(convert, "SOFFICE", _hanging(tmp_path))
    monkeypatch.setattr(convert, "FALLBACK_SOFFICE", _working(tmp_path))
    monkeypatch.setattr(convert, "FIRST_TRY_SECONDS", 2)
    monkeypatch.setattr(convert, "FONTS_DIR", "")
    assert convert.docx_to_pdf(_title_control_doc()) == b"%PDF-1.4 fallback"
    child = int((tmp_path / "child.pid").read_text())
    time.sleep(0.3)
    assert not _alive(child), "the hung LibreOffice was left running"


def test_without_a_fallback_a_hang_still_raises_and_is_stopped(monkeypatch, tmp_path):
    import time
    from app.core.exceptions import ExternalServiceError

    monkeypatch.setattr(convert, "SOFFICE", _hanging(tmp_path))
    monkeypatch.setattr(convert, "FALLBACK_SOFFICE", "")
    monkeypatch.setattr(convert, "FONTS_DIR", "")
    with pytest.raises(ExternalServiceError):
        convert.docx_to_pdf(_title_control_doc(), timeout=2)
    child = int((tmp_path / "child.pid").read_text())
    time.sleep(0.3)
    assert not _alive(child)


def test_a_failed_conversion_also_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(convert, "SOFFICE", _script(tmp_path / "fails.sh", "exit 1\n"))
    monkeypatch.setattr(convert, "FALLBACK_SOFFICE", _working(tmp_path))
    monkeypatch.setattr(convert, "FONTS_DIR", "")
    assert convert.docx_to_pdf(_title_control_doc()) == b"%PDF-1.4 fallback"


def test_settings_default_to_the_system_libreoffice(monkeypatch):
    monkeypatch.delenv("LIBREOFFICE_BIN", raising=False)
    monkeypatch.delenv("PDF_FONTS_DIR", raising=False)
    monkeypatch.delenv("LIBREOFFICE_FALLBACK_BIN", raising=False)
    monkeypatch.delenv("LIBREOFFICE_FIRST_TRY_SECONDS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.libreoffice_bin == "/usr/bin/soffice"
    assert settings.libreoffice_fallback_bin == ""
    assert settings.libreoffice_first_try_seconds == 15
    assert settings.pdf_fonts_dir == ""


# --- rendering, with the soffice the settings name ---------------------------


def _spans(pdf: bytes) -> list[tuple[str, float]]:
    """(text, effective font size) for every text show in the PDF."""
    from pypdf import PdfReader

    out: list[tuple[str, float]] = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            out.append((text.strip(), abs(size * tm[3] * (cm[3] or 1))))
    for page in PdfReader(io.BytesIO(pdf)).pages:
        page.extract_text(visitor_text=visit)
    return out


def _images(pdf: bytes) -> int:
    from pypdf import PdfReader

    return sum(len(page.images) for page in PdfReader(io.BytesIO(pdf)).pages)


def test_the_cover_title_keeps_its_36_pt():
    pdf = convert.docx_to_pdf(_title_control_doc())
    sizes = [size for text, size in _spans(pdf) if "Sunrise" in text]
    assert sizes and max(sizes) == pytest.approx(36, abs=0.5), _spans(pdf)


def test_the_cover_art_is_drawn():
    pdf = convert.docx_to_pdf(_cover_art_doc())
    assert _images(pdf) == 1


def test_page_numbers_print_with_their_dashes():
    from pypdf import PdfReader

    pdf = convert.docx_to_pdf(_dash_footer_doc())
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "- 1 -" in text, text


def test_a_font_from_the_converter_folder_is_used():
    from pathlib import Path
    from pypdf import PdfReader

    folder = Path(convert.FONTS_DIR) if convert.FONTS_DIR else None
    if folder is None or not any(folder.glob("Lato-*.ttf")):
        pytest.skip("no converter fonts folder with Lato configured here")
    doc = Document()
    run = doc.add_paragraph().add_run("Set in Lato")
    run.font.name = "Lato"
    pdf = convert.docx_to_pdf(_save(doc))
    fonts = {str(f.get("/BaseFont")) for page in PdfReader(io.BytesIO(pdf)).pages
             for f in (page.get("/Resources") or {}).get("/Font", {}).values()
             for f in [f.get_object()]}
    assert any("Lato" in name for name in fonts), fonts
