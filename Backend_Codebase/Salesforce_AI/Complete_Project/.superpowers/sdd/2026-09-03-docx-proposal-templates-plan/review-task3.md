# Review package task3

## Commits
```
3f9ea0f test(docx): golden coverage over the four real proposal documents
```

## Files changed
```
 tests/docx/test_golden_samples.py | 91 +++++++++++++++++++++++++++++++++++++++
 1 file changed, 91 insertions(+)
```

## Diff
```diff
diff --git a/tests/docx/test_golden_samples.py b/tests/docx/test_golden_samples.py
new file mode 100644
index 0000000..0270a2c
--- /dev/null
+++ b/tests/docx/test_golden_samples.py
@@ -0,0 +1,91 @@
+# tests/docx/test_golden_samples.py
+"""Opt-in tests against the organisation's four real proposal documents.
+
+They live in `data/samples/` and are not in git — 27 MB of branded material.
+When the directory is absent every test here skips, so a clean checkout stays
+green; on the VM they run and are the real proof.
+"""
+import io
+from pathlib import Path
+
+import pytest
+from docx import Document
+
+from app.services.docx import text as dt
+from tests.docx.test_text import raw_count as raw_count_bytes
+
+SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
+
+# filename -> the client-name literal that document uses
+SAMPLES = {
+    "Essential Lab.docx": "School Name",
+    "Innovation Lab Template.docx": "School Name",
+    "School_YuviPep 360_2 1.docx": "School School",
+    "School_YuviPep 360 EmpowerED_New_compressed.docx": "School Name",
+}
+
+# measured 2026-09-03 against the raw XML
+EXPECTED_OCCURRENCES = {
+    "Essential Lab.docx": 7,
+    "Innovation Lab Template.docx": 7,
+    "School_YuviPep 360_2 1.docx": 9,
+    "School_YuviPep 360 EmpowerED_New_compressed.docx": 14,
+}
+
+pytestmark = pytest.mark.skipif(
+    not SAMPLES_DIR.is_dir(), reason="data/samples/ not present"
+)
+
+
+def raw_count(path: Path, literal: str) -> int:
+    """Path-taking variant of the shared ground-truth tokenizer.
+
+    Reuses the stack-based `raw_count` (bytes-based) from
+    `tests.docx.test_text` rather than re-implementing paragraph-boundary
+    scanning here. See the Task 3 controller ruling: a second copy of that
+    tokenizer logic in this file is exactly the defect (a naive single-pass
+    `<w:p[ >].*?</w:p>` regex undercounting nested text-box paragraphs) the
+    ruling exists to prevent.
+    """
+    return raw_count_bytes(Path(path).read_bytes(), literal)
+
+
+@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
+def test_walker_agrees_with_raw_xml(name, literal):
+    path = SAMPLES_DIR / name
+    if not path.exists():
+        pytest.skip(f"{name} not present")
+    doc = Document(str(path))
+    assert dt.count_token(doc, literal) == raw_count(path, literal)
+
+
+@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
+def test_occurrence_counts_have_not_drifted(name, literal):
+    path = SAMPLES_DIR / name
+    if not path.exists():
+        pytest.skip(f"{name} not present")
+    doc = Document(str(path))
+    assert dt.count_token(doc, literal) == EXPECTED_OCCURRENCES[name]
+
+
+@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
+def test_replacement_leaves_nothing_behind(name, literal):
+    path = SAMPLES_DIR / name
+    if not path.exists():
+        pytest.skip(f"{name} not present")
+    doc = Document(str(path))
+    media_before = len(doc.part.package.image_parts)
+    sections_before = len(doc.sections)
+
+    replaced = dt.replace_token(doc, literal, "Greenwood International School")
+    assert replaced == EXPECTED_OCCURRENCES[name]
+
+    buf = io.BytesIO()
+    doc.save(buf)
+    data = buf.getvalue()
+
+    reopened = Document(io.BytesIO(data))
+    assert dt.count_token(reopened, literal) == 0
+    assert raw_count_bytes(data, literal) == 0
+    assert len(reopened.part.package.image_parts) == media_before
+    assert len(reopened.sections) == sections_before
```
