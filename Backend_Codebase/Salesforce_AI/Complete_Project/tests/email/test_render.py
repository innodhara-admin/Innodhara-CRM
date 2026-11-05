"""A filled Word email becomes a subject, an HTML body and a plain-text body."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.exceptions import ValidationFailedError
from app.services import email_render

FIXTURES = Path(__file__).parent / "fixtures"


def _save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _doc(*lines: str):
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    return doc


def _add_link(paragraph, text: str, url: str) -> None:
    rid = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rid)
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)


def test_subject_is_the_first_line_and_not_in_the_body():
    data = _save(_doc("Subject: Hello Acme", "Dear Ms. Rao,", "Body line."))
    found = email_render.subject_paragraph(data)
    assert found == (0, "Hello Acme")
    out = email_render.render(data)
    assert out.subject == "Hello Acme"
    assert "Subject" not in out.html and "Subject" not in out.text
    assert out.text.startswith("Dear Ms. Rao,")


def test_no_subject_is_refused():
    data = _save(_doc("Dear Ms. Rao,", "Body line."))
    assert email_render.subject_paragraph(data) is None
    with pytest.raises(ValidationFailedError) as err:
        email_render.render(data)
    assert "Subject:" in err.value.message


def test_bold_italic_underline_survive():
    doc = _doc("Subject: s")
    p = doc.add_paragraph("Plain ")
    p.add_run("bold").bold = True
    p.add_run(" and ")
    p.add_run("slanted").italic = True
    p.add_run(" and ")
    p.add_run("lined").underline = True
    html = email_render.render(_save(doc)).html
    assert re.search(r"<strong>bold</strong>", html)
    assert re.search(r"<em>slanted</em>", html)
    assert re.search(r"<u>lined</u>", html)


def test_hyperlink_becomes_a_link():
    doc = _doc("Subject: s")
    p = doc.add_paragraph("See ")
    _add_link(p, "our site", "https://example.org/x")
    out = email_render.render(_save(doc))
    assert '<a href="https://example.org/x"' in out.html
    assert ">our site</a>" in out.html
    assert "our site (https://example.org/x)" in out.text


def test_bullets_and_numbers_become_lists():
    doc = _doc("Subject: s", "Before")
    doc.add_paragraph("first point", style="List Bullet")
    doc.add_paragraph("second point", style="List Bullet")
    doc.add_paragraph("Between")
    doc.add_paragraph("step one", style="List Number")
    doc.add_paragraph("step two", style="List Number")
    out = email_render.render(_save(doc))
    assert re.search(r"<ul[^>]*>\s*<li[^>]*>first point</li>\s*<li[^>]*>second point</li>\s*</ul>", out.html)
    assert re.search(r"<ol[^>]*>\s*<li[^>]*>step one</li>\s*<li[^>]*>step two</li>\s*</ol>", out.html)
    assert "• first point\n• second point" in out.text
    assert "1. step one\n2. step two" in out.text


def test_line_breaks_inside_a_paragraph():
    doc = _doc("Subject: s")
    p = doc.add_paragraph("Warm regards,")
    run = p.add_run()
    run.add_break()
    run.add_text("Asha")
    out = email_render.render(_save(doc))
    assert "Warm regards,<br>Asha" in out.html
    assert "Warm regards,\nAsha" in out.text


def test_html_is_escaped():
    data = _save(_doc("Subject: a < b & c", "x < y & <script>alert(1)</script>"))
    out = email_render.render(data)
    assert out.subject == "a < b & c"
    assert "<script>" not in out.html
    assert "x &lt; y &amp; &lt;script&gt;" in out.html
    assert "x < y & <script>alert(1)</script>" in out.text


def test_styles_are_inline():
    out = email_render.render(_save(_doc("Subject: s", "one", "two")))
    assert "<style" not in out.html
    assert all("style=" in m for m in re.findall(r"<(?:p|ul|ol|li|div)\b[^>]*>", out.html))


def test_signature_of_a_real_template_renders_as_lines():
    out = email_render.render((FIXTURES / "IBC proposal email.docx").read_bytes())
    assert out.subject.startswith("Proposal for <School Name>")
    assert "Warm regards,\n\n<Your Name>" in out.text or "Warm regards,\n<Your Name>" in out.text
    assert "info@yuvipep.com" in out.html


@pytest.mark.parametrize("filename", sorted(p.name for p in FIXTURES.glob("*.docx")))
def test_every_fixture_renders(filename):
    out = email_render.render((FIXTURES / filename).read_bytes())
    assert out.subject and out.html and out.text
    assert "Subject:" not in out.text


def test_a_typed_web_address_becomes_a_link():
    """The video and highlights links are answered as plain text; in the email
    they must be clickable, without their trailing full stop."""
    out = email_render.render(_save(_doc(
        "Subject: s", "Innovation in Action: https://youtu.be/abc?x=1&y=2.")))
    assert ('<a href="https://youtu.be/abc?x=1&amp;y=2" style="color:#1155cc">'
            'https://youtu.be/abc?x=1&amp;y=2</a>.') in out.html
    assert "Innovation in Action: https://youtu.be/abc?x=1&y=2." in out.text


def test_an_existing_link_is_not_linked_twice():
    doc = _doc("Subject: s")
    p = doc.add_paragraph("See ")
    _add_link(p, "https://example.org/x", "https://example.org/x")
    out = email_render.render(_save(doc))
    assert out.html.count("<a ") == 1
