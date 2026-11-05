# Review package task1

## Commits
```
b3de5a2 feat(docx): LibreOffice DOCX->PDF converter
```

## Files changed
```
 app/services/docx/__init__.py |  0
 app/services/docx/convert.py  | 80 +++++++++++++++++++++++++++++++++++++++++++
 requirements.txt              | 22 ++++++++++++
 tests/docx/__init__.py        |  0
 tests/docx/test_convert.py    | 35 +++++++++++++++++++
 5 files changed, 137 insertions(+)
```

## Diff
```diff
diff --git a/app/services/docx/__init__.py b/app/services/docx/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/app/services/docx/convert.py b/app/services/docx/convert.py
new file mode 100644
index 0000000..d32d5dc
--- /dev/null
+++ b/app/services/docx/convert.py
@@ -0,0 +1,80 @@
+"""DOCX -> PDF through LibreOffice headless.
+
+Why not reportlab: the templates this serves are branded documents with cover
+art, per-section headers and footers, theme fonts and styled tables. Rebuilding
+them from extracted text is what the whole feature exists to stop doing. A
+silently unbranded PDF reaching a client is worse than a refusal, so there is
+no fallback here — a failure raises.
+
+Each call gets its own `-env:UserInstallation` profile directory. A shared
+profile serialises concurrent conversions and, worse, leaves a lock file behind
+after a killed process that makes every later convert hang.
+"""
+from __future__ import annotations
+
+import io
+import logging
+import shutil
+import subprocess
+import tempfile
+import zipfile
+from pathlib import Path
+
+from app.core.exceptions import ExternalServiceError
+
+logger = logging.getLogger(__name__)
+
+SOFFICE = "/usr/bin/soffice"
+
+
+def docx_to_pdf(docx_bytes: bytes, *, timeout: int = 120) -> bytes:
+    if not docx_bytes:
+        raise ExternalServiceError("Cannot convert an empty document to PDF")
+    if not Path(SOFFICE).exists() and shutil.which(SOFFICE) is None:
+        raise ExternalServiceError(
+            "LibreOffice is not installed on this server, so the proposal PDF "
+            "cannot be produced. Install libreoffice-writer, or download the "
+            "DOCX instead."
+        )
+    # A .docx is a zip/OOXML package. LibreOffice's --convert-to autodetect is
+    # lenient enough to fall back to a plain-text importer for unrecognised
+    # bytes and still emit a "successful" PDF, so garbage input would
+    # otherwise pass straight through instead of raising. Reject it here.
+    try:
+        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
+            if "word/document.xml" not in zf.namelist():
+                raise ExternalServiceError(
+                    "The uploaded file is not a valid DOCX document."
+                )
+    except zipfile.BadZipFile:
+        raise ExternalServiceError(
+            "The uploaded file is not a valid DOCX document."
+        ) from None
+    with tempfile.TemporaryDirectory(prefix="docxpdf_") as tmp:
+        work = Path(tmp)
+        src = work / "in.docx"
+        src.write_bytes(docx_bytes)
+        profile = work / "profile"
+        cmd = [
+            SOFFICE, "--headless", "--norestore", "--invisible",
+            f"-env:UserInstallation=file://{profile}",
+            "--convert-to", "pdf", "--outdir", str(work), str(src),
+        ]
+        try:
+            proc = subprocess.run(
+                cmd, capture_output=True, timeout=timeout, check=False,
+                env={"HOME": str(work), "PATH": "/usr/bin:/bin"},
+            )
+        except subprocess.TimeoutExpired as exc:
+            raise ExternalServiceError(
+                f"Converting the proposal to PDF took longer than {timeout}s "
+                "and was stopped."
+            ) from exc
+        out = work / "in.pdf"
+        if not out.exists():
+            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")
+            logger.error("soffice produced no PDF: rc=%s %s", proc.returncode, detail[:400])
+            raise ExternalServiceError(
+                "LibreOffice could not convert this document to PDF."
+            )
+        return out.read_bytes()
diff --git a/requirements.txt b/requirements.txt
index dfc5baf..4c9133d 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -11,20 +11,42 @@ PyJWT>=2.8
 cryptography>=42.0
 python-multipart>=0.0.9
 python-docx>=1.1
 reportlab>=4.1
 
 # ── Speech-to-text (STT_PROVIDER=whisper_local, the default) ──────────────────
 # Pulls torch (~2 GB). Also requires ffmpeg on PATH: https://ffmpeg.org
 # Comment out and set STT_PROVIDER=gemini to skip the heavy install.
 openai-whisper>=20231117
 
+# ── Memory embeddings (EMBEDDING_PROVIDER=local, the default) ─────────────────
+# Reuses the torch that openai-whisper already pulls, so this adds no heavy
+# dependency of its own. The model downloads to the HuggingFace cache on first
+# use (~1.1 GB). Tested on 2.7.0; note that 3.x changed the constructor
+# signature, so pin if you need reproducibility.
+# Comment out and set EMBEDDING_PROVIDER=gemini (or hash) to skip it.
+sentence-transformers>=2.7
+
 # ── Testing ────────────────────────────────────────────────────────────────────
 pytest>=8.2
 pytest-asyncio>=0.23
 
 # ── Optional: PostgreSQL production database (uncomment to use) ───────────────
 # asyncpg>=0.29
 
 # ── Optional: Google Calendar via service account (uncomment to use) ──────────
 # google-auth>=2.29
 pypdf>=6.0
+
+# zoneinfo reads the OS timezone database, and a slim container or a
+# Windows host has none — ZoneInfo('Asia/Kolkata') then raises
+# ZoneInfoNotFoundError. app/core/clock.py degrades to the default rather
+# than crashing, and its last resort is UTC — so without this every date
+# judgement silently falls back to UTC and an eastern tenant's "today"
+# starts five and a half hours late.
+tzdata>=2024.1
+
+# ── System packages required by the DOCX proposal-template path ──────────────
+# These are NOT pip installable and are not installed by this file.
+#   tesseract-ocr   (4.1.1, 'eng' model)  — OCR of images embedded in templates
+#   libreoffice-writer (7.3.7)            — DOCX -> PDF for docx-kind proposals
+# Both are called through subprocess; no Python wrapper package is used.
diff --git a/tests/docx/__init__.py b/tests/docx/__init__.py
new file mode 100644
index 0000000..e69de29
diff --git a/tests/docx/test_convert.py b/tests/docx/test_convert.py
new file mode 100644
index 0000000..55dad50
--- /dev/null
+++ b/tests/docx/test_convert.py
@@ -0,0 +1,35 @@
+import pytest
+from docx import Document
+import io
+
+from app.core.exceptions import ExternalServiceError
+from app.services.docx import convert
+
+
+def _tiny_docx() -> bytes:
+    doc = Document()
+    doc.add_heading("Hello", level=1)
+    doc.add_paragraph("A sentence that will appear in the PDF text layer.")
+    buf = io.BytesIO()
+    doc.save(buf)
+    return buf.getvalue()
+
+
+def test_converts_docx_to_pdf():
+    pdf = convert.docx_to_pdf(_tiny_docx())
+    assert pdf[:5] == b"%PDF-"
+    from pypdf import PdfReader
+    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
+    assert "will appear in the PDF text layer" in text
+
+
+def test_missing_binary_raises(monkeypatch):
+    monkeypatch.setattr(convert, "SOFFICE", "/nonexistent/soffice")
+    with pytest.raises(ExternalServiceError) as err:
+        convert.docx_to_pdf(_tiny_docx())
+    assert "LibreOffice" in str(err.value)
+
+
+def test_garbage_input_raises():
+    with pytest.raises(ExternalServiceError):
+        convert.docx_to_pdf(b"this is not a docx")
```
