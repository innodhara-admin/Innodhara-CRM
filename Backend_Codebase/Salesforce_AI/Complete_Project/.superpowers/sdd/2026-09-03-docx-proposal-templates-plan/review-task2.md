# Review package task2

## Commits
```
16a8a76 feat(docx): w:t-level text access and span replacement
```

## Files changed
```
 app/services/docx/text.py | 150 ++++++++++++++++++++++++++++++++++++++++++++++
 tests/docx/conftest.py    | 115 +++++++++++++++++++++++++++++++++++
 tests/docx/test_text.py   | 132 ++++++++++++++++++++++++++++++++++++++++
 3 files changed, 397 insertions(+)
```

## Diff
```diff
diff --git a/app/services/docx/text.py b/app/services/docx/text.py
new file mode 100644
index 0000000..6b48e1c
--- /dev/null
+++ b/app/services/docx/text.py
@@ -0,0 +1,150 @@
+# app/services/docx/text.py
+"""Text access at the `w:t` level, and span replacement that survives it.
+
+**Do not use `Paragraph.runs` anywhere in this feature.** It omits runs nested
+in `w:hyperlink` and never descends into text boxes
+(`mc:AlternateContent`/`w:pict` -> `w:txbxContent`). Measured against the four
+real sample documents, a `.runs`-based walk found 4 of 7, 1 of 7, 1 of 9 and
+2 of 14 occurrences of the client-name literal — and the verification pass,
+using the same walk, agreed with itself and reported success. The result would
+have been a client-facing proposal still reading "School Name".
+
+Word also fragments runs arbitrarily: `School Name` is commonly three runs,
+`['School', ' ', 'Name']`, so a `run.text.replace(...)` matches nothing. Every
+replacement here works on the *joined* text of a paragraph's own `w:t` nodes
+and then writes back across whichever nodes the match covered.
+"""
+from __future__ import annotations
+
+from typing import Iterator
+
+from docx.oxml.ns import qn
+
+W_P = qn("w:p")
+W_T = qn("w:t")
+W_INSTR = qn("w:instrText")
+XML_SPACE = qn("xml:space")
+
+_MAX_REPLACEMENTS = 500
+
+
+def iter_paragraphs(root) -> Iterator:
+    """Every `w:p` under `root`, in document order.
+
+    `.iter()` is a full-tree walk, so this reaches paragraphs inside tables,
+    structured document tags and text boxes — all places real templates hide
+    text that `doc.paragraphs` never yields.
+    """
+    return root.iter(W_P)
+
+
+def own_text_nodes(p) -> list:
+    """The `w:t` nodes belonging to `p` itself.
+
+    A text box nests a complete `w:p` inside a run of the outer paragraph. Its
+    text is a separate paragraph: splicing it into the outer paragraph's string
+    would corrupt offsets and let a replacement write into the wrong place.
+    """
+    out = []
+    for t in p.iter(W_T):
+        anc = t.getparent()
+        while anc is not None and anc.tag != W_P:
+            anc = anc.getparent()
+        if anc is p:
+            out.append(t)
+    return out
+
+
+def node_text(p) -> str:
+    return "".join(t.text or "" for t in own_text_nodes(p))
+
+
+def replace_span(p, start: int, end: int, replacement: str) -> bool:
+    """Replace `[start, end)` of `node_text(p)`. Returns whether anything changed.
+
+    The replacement lands in the node holding `start` and inherits that node's
+    run formatting; the rest of the covered range is blanked. Nodes outside the
+    span are untouched, so a change to one word cannot restyle a paragraph.
+    """
+    if start >= end:
+        return False
+    nodes = own_text_nodes(p)
+    spans, offset = [], 0
+    for t in nodes:
+        s = t.text or ""
+        spans.append((t, offset, offset + len(s)))
+        offset += len(s)
+
+    first = True
+    for t, t0, t1 in spans:
+        if t1 <= start or t0 >= end:
+            continue
+        s = t.text or ""
+        lo, hi = max(start, t0) - t0, min(end, t1) - t0
+        if first:
+            t.text = s[:lo] + replacement + s[hi:]
+            # a w:t whose value has significant leading/trailing whitespace is
+            # collapsed by Word unless xml:space says otherwise
+            if t.text != t.text.strip():
+                t.set(XML_SPACE, "preserve")
+            first = False
+        else:
+            t.text = s[:lo] + s[hi:]
+    return not first
+
+
+def replace_token_in_paragraph(p, literal: str, replacement: str) -> int:
+    if not literal:
+        return 0
+    count = 0
+    while count < _MAX_REPLACEMENTS:
+        found = node_text(p).find(literal)
+        if found < 0:
+            return count
+        if not replace_span(p, found, found + len(literal), replacement):
+            return count
+        count += 1
+    return count
+
+
+def all_roots(doc) -> list:
+    """The body plus every distinct header/footer element in the package.
+
+    Sections share header/footer parts when linked to previous, so identity is
+    de-duplicated — otherwise a shared footer is rewritten once per section and
+    the occurrence count lies.
+    """
+    roots = [doc.element.body]
+    seen: set[int] = set()
+    for section in doc.sections:
+        for part in (
+            section.header, section.footer,
+            section.even_page_header, section.even_page_footer,
+            section.first_page_header, section.first_page_footer,
+        ):
+            if part is None:
+                continue
+            el = part._element
+            if id(el) in seen:
+                continue
+            seen.add(id(el))
+            roots.append(el)
+    return roots
+
+
+def replace_token(doc, literal: str, replacement: str) -> int:
+    return sum(
+        replace_token_in_paragraph(p, literal, replacement)
+        for root in all_roots(doc)
+        for p in iter_paragraphs(root)
+    )
+
+
+def count_token(doc, literal: str) -> int:
+    if not literal:
+        return 0
+    return sum(
+        node_text(p).count(literal)
+        for root in all_roots(doc)
+        for p in iter_paragraphs(root)
+    )
diff --git a/tests/docx/conftest.py b/tests/docx/conftest.py
new file mode 100644
index 0000000..bb60ddc
--- /dev/null
+++ b/tests/docx/conftest.py
@@ -0,0 +1,115 @@
+# tests/docx/conftest.py
+"""Synthetic .docx fixtures that reproduce the shapes real documents use.
+
+Word fragments runs arbitrarily and buries text in hyperlinks and text boxes.
+`Paragraph.runs` sees none of the latter two, so every fixture here exists to
+pin one of those shapes.
+"""
+import io
+
+import pytest
+from docx import Document
+from docx.oxml import OxmlElement
+from docx.oxml.ns import nsmap, qn
+
+# python-docx's default nsmap omits the VML "v:" prefix (used by w:pict/v:shape
+# for legacy text boxes), so OxmlElement("v:shape") raises KeyError without this.
+nsmap.setdefault("v", "urn:schemas-microsoft-com:vml")
+
+
+def _t(text: str):
+    t = OxmlElement("w:t")
+    t.text = text
+    t.set(qn("xml:space"), "preserve")
+    return t
+
+
+def _run(text: str, *, bold: bool = False):
+    r = OxmlElement("w:r")
+    if bold:
+        rpr = OxmlElement("w:rPr")
+        rpr.append(OxmlElement("w:b"))
+        r.append(rpr)
+    r.append(_t(text))
+    return r
+
+
+def save(doc) -> bytes:
+    buf = io.BytesIO()
+    doc.save(buf)
+    return buf.getvalue()
+
+
+@pytest.fixture
+def fragmented_docx() -> bytes:
+    """'School Name' split across three runs, as Word actually writes it."""
+    doc = Document()
+    p = doc.add_paragraph()
+    for chunk in ("Welcome to ", "School", " ", "Name", " for the year."):
+        p._p.append(_run(chunk))
+    return save(doc)
+
+
+@pytest.fixture
+def hyperlink_docx() -> bytes:
+    """Text inside w:hyperlink — invisible to Paragraph.runs."""
+    doc = Document()
+    p = doc.add_paragraph()
+    p._p.append(_run("Contact "))
+    link = OxmlElement("w:hyperlink")
+    link.set(qn("w:anchor"), "_bookmark0")
+    link.append(_run("School"))
+    link.append(_run(" "))
+    link.append(_run("Name"))
+    p._p.append(link)
+    p._p.append(_run(" today."))
+    return save(doc)
+
+
+@pytest.fixture
+def textbox_docx() -> bytes:
+    """A whole w:p nested inside a text box within an outer paragraph."""
+    doc = Document()
+    outer = doc.add_paragraph()
+    outer._p.append(_run("Outer School Name text."))
+    r = OxmlElement("w:r")
+    pict = OxmlElement("w:pict")
+    shape = OxmlElement("v:shape")
+    tbx = OxmlElement("v:textbox")
+    content = OxmlElement("w:txbxContent")
+    inner = OxmlElement("w:p")
+    inner.append(_run("Inner School Name label."))
+    content.append(inner)
+    tbx.append(content)
+    shape.append(tbx)
+    pict.append(shape)
+    r.append(pict)
+    outer._p.append(r)
+    return save(doc)
+
+
+@pytest.fixture
+def table_docx() -> bytes:
+    doc = Document()
+    t = doc.add_table(rows=3, cols=2)
+    t.style = "Table Grid"
+    t.cell(0, 0).text = "Description"
+    t.cell(0, 1).text = "Estimation"
+    t.cell(1, 0).text = "Innovation Lab"
+    t.cell(1, 1).text = "Rs 0"
+    t.cell(2, 0).text = "Total"
+    t.cell(2, 1).text = "Rs 0"
+    return save(doc)
+
+
+@pytest.fixture
+def header_docx() -> bytes:
+    doc = Document()
+    doc.add_paragraph("Body mentions School Name once.")
+    header = doc.sections[0].header
+    header.is_linked_to_previous = False
+    header.paragraphs[0]._p.append(_run("Header for School Name"))
+    footer = doc.sections[0].footer
+    footer.is_linked_to_previous = False
+    footer.paragraphs[0]._p.append(_run("Footer for School Name"))
+    return save(doc)
diff --git a/tests/docx/test_text.py b/tests/docx/test_text.py
new file mode 100644
index 0000000..3edd402
--- /dev/null
+++ b/tests/docx/test_text.py
@@ -0,0 +1,132 @@
+# tests/docx/test_text.py
+import io
+import re
+import zipfile
+
+from docx import Document
+
+from app.services.docx import text as dt
+
+
+_P_TOKEN = re.compile(
+    r"(?P<popen><w:p(?:\s[^>]*)?>)"
+    r"|(?P<pclose></w:p>)"
+    r"|<w:t(?:\s[^>]*)?>(?P<ttext>.*?)</w:t>",
+    re.S,
+)
+
+
+def raw_count(data: bytes, literal: str) -> int:
+    """Ground truth: count per <w:p> across every word/*.xml part.
+
+    Walks open/close `w:p` tags with an explicit stack so nested paragraphs
+    (text boxes) are attributed to their own nearest `w:p`, not to whichever
+    ancestor's `.*?</w:p>` a non-overlapping regex scan happens to reach
+    first. A naive single-pass `<w:p[ >].*?</w:p>` match conflates a nested
+    `w:p`'s closing tag with its outer paragraph's, silently discarding the
+    inner paragraph's own text — undercounting exactly the shape this task
+    exists to get right. Deliberately still regex/text-based rather than an
+    XML-tree walk, so it stays an independent check on the raw markup instead
+    of reusing the tree API the implementation under test also uses.
+    """
+    z = zipfile.ZipFile(io.BytesIO(data))
+    total = 0
+    for name in z.namelist():
+        if not (name.startswith("word/") and name.endswith(".xml")):
+            continue
+        x = z.read(name).decode("utf8", "replace")
+        stack: list[list[str]] = []
+        for m in _P_TOKEN.finditer(x):
+            if m.group("popen"):
+                stack.append([])
+            elif m.group("pclose"):
+                if stack:
+                    own = "".join(stack.pop())
+                    total += own.count(literal)
+            else:
+                if stack:
+                    stack[-1].append(m.group("ttext") or "")
+    return total
+
+
+def _doc(data: bytes):
+    return Document(io.BytesIO(data))
+
+
+def test_sees_text_split_across_runs(fragmented_docx):
+    doc = _doc(fragmented_docx)
+    assert dt.count_token(doc, "School Name") == 1
+
+
+def test_replaces_text_split_across_runs(fragmented_docx):
+    doc = _doc(fragmented_docx)
+    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
+    p = next(dt.iter_paragraphs(doc.element.body))
+    assert dt.node_text(p) == "Welcome to Greenwood for the year."
+
+
+def test_sees_text_inside_hyperlinks(hyperlink_docx):
+    doc = _doc(hyperlink_docx)
+    # the defect this pins: Paragraph.runs returns nothing useful here
+    assert len(doc.paragraphs[0].runs) < 4
+    assert dt.count_token(doc, "School Name") == 1
+    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
+    assert "Greenwood" in dt.node_text(next(dt.iter_paragraphs(doc.element.body)))
+
+
+def test_sees_text_inside_textboxes(textbox_docx):
+    doc = _doc(textbox_docx)
+    assert dt.count_token(doc, "School Name") == 2
+    assert dt.replace_token(doc, "School Name", "Greenwood") == 2
+    assert dt.count_token(doc, "School Name") == 0
+
+
+def test_textbox_text_is_not_spliced_into_the_outer_paragraph(textbox_docx):
+    doc = _doc(textbox_docx)
+    outer = next(dt.iter_paragraphs(doc.element.body))
+    assert dt.node_text(outer) == "Outer School Name text."
+
+
+def test_sees_text_in_headers_and_footers(header_docx):
+    doc = _doc(header_docx)
+    assert dt.count_token(doc, "School Name") == 3
+    assert dt.replace_token(doc, "School Name", "Greenwood") == 3
+    assert dt.count_token(doc, "School Name") == 0
+
+
+def test_sees_text_in_table_cells(table_docx):
+    doc = _doc(table_docx)
+    assert dt.count_token(doc, "Innovation Lab") == 1
+    assert dt.replace_token(doc, "Innovation Lab", "Essential Lab") == 1
+
+
+def test_matches_raw_xml_ground_truth(fragmented_docx, hyperlink_docx,
+                                      textbox_docx, header_docx):
+    for data in (fragmented_docx, hyperlink_docx, textbox_docx, header_docx):
+        assert dt.count_token(_doc(data), "School Name") == raw_count(data, "School Name")
+
+
+def test_replace_span_preserves_surrounding_text(fragmented_docx):
+    doc = _doc(fragmented_docx)
+    p = next(dt.iter_paragraphs(doc.element.body))
+    start = dt.node_text(p).index("School Name")
+    assert dt.replace_span(p, start, start + len("School Name"), "X")
+    assert dt.node_text(p) == "Welcome to X for the year."
+
+
+def test_replace_span_out_of_range_is_a_no_op(fragmented_docx):
+    doc = _doc(fragmented_docx)
+    p = next(dt.iter_paragraphs(doc.element.body))
+    before = dt.node_text(p)
+    assert dt.replace_span(p, 9999, 10000, "X") is False
+    assert dt.node_text(p) == before
+
+
+def test_leading_space_survives_a_replacement(fragmented_docx):
+    doc = _doc(fragmented_docx)
+    p = next(dt.iter_paragraphs(doc.element.body))
+    dt.replace_span(p, 0, len("Welcome to"), "  Hello  ")
+    buf = io.BytesIO()
+    doc.save(buf)
+    assert dt.node_text(next(dt.iter_paragraphs(_doc(buf.getvalue()).element.body))) \
+        == "  Hello   School Name for the year."
```
