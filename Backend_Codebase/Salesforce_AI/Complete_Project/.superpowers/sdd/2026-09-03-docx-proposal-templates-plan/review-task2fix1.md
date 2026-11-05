# Review package task2fix1

## Commits
```
7f95692 fix(docx): guard xml:space on every replace_span node; pin footer dedup
```

## Files changed
```
 app/services/docx/text.py | 15 +++++++++------
 tests/docx/conftest.py    | 47 ++++++++++++++++++++++++++++++++++++++++++++++
 tests/docx/test_text.py   | 48 +++++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 104 insertions(+), 6 deletions(-)
```

## Diff
```diff
diff --git a/app/services/docx/text.py b/app/services/docx/text.py
index 6b48e1c..765198b 100644
--- a/app/services/docx/text.py
+++ b/app/services/docx/text.py
@@ -68,35 +68,38 @@ def replace_span(p, start: int, end: int, replacement: str) -> bool:
     """
     if start >= end:
         return False
     nodes = own_text_nodes(p)
     spans, offset = [], 0
     for t in nodes:
         s = t.text or ""
         spans.append((t, offset, offset + len(s)))
         offset += len(s)
 
+    def _write(node, value):
+        node.text = value
+        # a w:t whose value has significant leading/trailing whitespace is
+        # collapsed by Word unless xml:space says otherwise
+        if value != value.strip():
+            node.set(XML_SPACE, "preserve")
+
     first = True
     for t, t0, t1 in spans:
         if t1 <= start or t0 >= end:
             continue
         s = t.text or ""
         lo, hi = max(start, t0) - t0, min(end, t1) - t0
         if first:
-            t.text = s[:lo] + replacement + s[hi:]
-            # a w:t whose value has significant leading/trailing whitespace is
-            # collapsed by Word unless xml:space says otherwise
-            if t.text != t.text.strip():
-                t.set(XML_SPACE, "preserve")
+            _write(t, s[:lo] + replacement + s[hi:])
             first = False
         else:
-            t.text = s[:lo] + s[hi:]
+            _write(t, s[:lo] + s[hi:])
     return not first
 
 
 def replace_token_in_paragraph(p, literal: str, replacement: str) -> int:
     if not literal:
         return 0
     count = 0
     while count < _MAX_REPLACEMENTS:
         found = node_text(p).find(literal)
         if found < 0:
diff --git a/tests/docx/conftest.py b/tests/docx/conftest.py
index bb60ddc..e21df02 100644
--- a/tests/docx/conftest.py
+++ b/tests/docx/conftest.py
@@ -27,20 +27,35 @@ def _t(text: str):
 def _run(text: str, *, bold: bool = False):
     r = OxmlElement("w:r")
     if bold:
         rpr = OxmlElement("w:rPr")
         rpr.append(OxmlElement("w:b"))
         r.append(rpr)
     r.append(_t(text))
     return r
 
 
+def _t_plain(text: str):
+    """A w:t with no xml:space attribute, matching how Word writes a run
+    whose own text has no leading/trailing whitespace worth protecting at
+    creation time — the shape that exposes replace_span's whitespace bug."""
+    t = OxmlElement("w:t")
+    t.text = text
+    return t
+
+
+def _run_plain(text: str):
+    r = OxmlElement("w:r")
+    r.append(_t_plain(text))
+    return r
+
+
 def save(doc) -> bytes:
     buf = io.BytesIO()
     doc.save(buf)
     return buf.getvalue()
 
 
 @pytest.fixture
 def fragmented_docx() -> bytes:
     """'School Name' split across three runs, as Word actually writes it."""
     doc = Document()
@@ -106,10 +121,42 @@ def table_docx() -> bytes:
 def header_docx() -> bytes:
     doc = Document()
     doc.add_paragraph("Body mentions School Name once.")
     header = doc.sections[0].header
     header.is_linked_to_previous = False
     header.paragraphs[0]._p.append(_run("Header for School Name"))
     footer = doc.sections[0].footer
     footer.is_linked_to_previous = False
     footer.paragraphs[0]._p.append(_run("Footer for School Name"))
     return save(doc)
+
+
+@pytest.fixture
+def two_run_whitespace_docx() -> bytes:
+    """A span replacement that ends mid-node, leaving a leading-space
+    remainder in the LAST covered w:t. Pins replace_span's `else` branch:
+    without an xml:space="preserve" guard there too, that remainder collapses
+    its leading space when Word renders it.
+    """
+    doc = Document()
+    p = doc.add_paragraph()
+    p._p.append(_run_plain("Dear School"))
+    p._p.append(_run_plain(" Name today"))
+    return save(doc)
+
+
+@pytest.fixture
+def linked_section_footer_docx() -> bytes:
+    """Two sections; the second's footer is left linked to the first's (the
+    python-docx default after add_section()), so the underlying footer part
+    -- and its element -- is shared between sections. Pins all_roots's
+    de-duplication by element identity: a broken dedup would double-count or
+    double-replace text in a footer shared by every linked section.
+    """
+    doc = Document()
+    doc.add_paragraph("Section one body.")
+    footer = doc.sections[0].footer
+    footer.is_linked_to_previous = False
+    footer.paragraphs[0]._p.append(_run("Footer for School Name"))
+    doc.add_section()
+    doc.add_paragraph("Section two body.")
+    return save(doc)
diff --git a/tests/docx/test_text.py b/tests/docx/test_text.py
index 3edd402..c78a75c 100644
--- a/tests/docx/test_text.py
+++ b/tests/docx/test_text.py
@@ -123,10 +123,58 @@ def test_replace_span_out_of_range_is_a_no_op(fragmented_docx):
 
 
 def test_leading_space_survives_a_replacement(fragmented_docx):
     doc = _doc(fragmented_docx)
     p = next(dt.iter_paragraphs(doc.element.body))
     dt.replace_span(p, 0, len("Welcome to"), "  Hello  ")
     buf = io.BytesIO()
     doc.save(buf)
     assert dt.node_text(next(dt.iter_paragraphs(_doc(buf.getvalue()).element.body))) \
         == "  Hello   School Name for the year."
+
+
+def test_replace_span_preserves_whitespace_on_trailing_node(two_run_whitespace_docx):
+    """Pins the fix to replace_span's `else` branch: when a span ends
+    mid-node and the surviving remainder starts with a space, that node must
+    carry xml:space="preserve" or Word collapses the space on render.
+
+    node_text() equality alone does not distinguish buggy from fixed here:
+    python-docx/lxml preserves a w:t's raw text verbatim through save/reopen
+    regardless of the xml:space attribute (verified directly against this
+    repo's python-docx 1.2.0), so a round trip that only checks the joined
+    string would pass even with the bug. The attribute is what actually
+    protects the document once Word -- not python-docx -- renders it, so
+    that is what this test pins, on both the freshly-mutated element and
+    after a save/reopen round trip.
+    """
+    doc = _doc(two_run_whitespace_docx)
+    p = next(dt.iter_paragraphs(doc.element.body))
+    start = dt.node_text(p).index("School Name")
+    assert dt.replace_span(p, start, start + len("School Name"), "Greenwood")
+    assert dt.node_text(p) == "Dear Greenwood today"
+
+    trailing = dt.own_text_nodes(p)[-1]
+    assert trailing.text == " today"
+    assert trailing.get(dt.XML_SPACE) == "preserve"
+
+    buf = io.BytesIO()
+    doc.save(buf)
+    doc2 = _doc(buf.getvalue())
+    p2 = next(dt.iter_paragraphs(doc2.element.body))
+    assert dt.node_text(p2) == "Dear Greenwood today"
+    trailing2 = dt.own_text_nodes(p2)[-1]
+    assert trailing2.text == " today"
+    assert trailing2.get(dt.XML_SPACE) == "preserve"
+
+
+def test_linked_section_footer_is_not_double_counted(linked_section_footer_docx):
+    """Two sections whose footer is shared (second linked to first, the
+    python-docx default). all_roots must de-duplicate by element identity so
+    the shared footer is counted/replaced once, not once per section.
+    """
+    doc = _doc(linked_section_footer_docx)
+    assert len(doc.sections) == 2
+    assert doc.sections[1].footer.is_linked_to_previous is True
+    assert dt.count_token(doc, "School Name") == 1
+    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
+    assert dt.count_token(doc, "School Name") == 0
+    assert "Greenwood" in dt.node_text(doc.sections[0].footer.paragraphs[0]._p)
```
