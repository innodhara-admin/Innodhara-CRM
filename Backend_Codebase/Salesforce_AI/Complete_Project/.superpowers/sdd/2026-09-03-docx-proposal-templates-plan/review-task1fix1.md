# Review package task1fix1

## Commits
```
30a0646 feat(docx): LibreOffice DOCX->PDF converter
```

## Files changed
```
 requirements.txt | 16 ----------------
 1 file changed, 16 deletions(-)
```

## Diff
```diff
diff --git a/requirements.txt b/requirements.txt
index 4c9133d..7df5dcb 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -11,42 +11,26 @@ PyJWT>=2.8
 cryptography>=42.0
 python-multipart>=0.0.9
 python-docx>=1.1
 reportlab>=4.1
 
 # ── Speech-to-text (STT_PROVIDER=whisper_local, the default) ──────────────────
 # Pulls torch (~2 GB). Also requires ffmpeg on PATH: https://ffmpeg.org
 # Comment out and set STT_PROVIDER=gemini to skip the heavy install.
 openai-whisper>=20231117
 
-# ── Memory embeddings (EMBEDDING_PROVIDER=local, the default) ─────────────────
-# Reuses the torch that openai-whisper already pulls, so this adds no heavy
-# dependency of its own. The model downloads to the HuggingFace cache on first
-# use (~1.1 GB). Tested on 2.7.0; note that 3.x changed the constructor
-# signature, so pin if you need reproducibility.
-# Comment out and set EMBEDDING_PROVIDER=gemini (or hash) to skip it.
-sentence-transformers>=2.7
-
 # ── Testing ────────────────────────────────────────────────────────────────────
 pytest>=8.2
 pytest-asyncio>=0.23
 
 # ── Optional: PostgreSQL production database (uncomment to use) ───────────────
 # asyncpg>=0.29
 
 # ── Optional: Google Calendar via service account (uncomment to use) ──────────
 # google-auth>=2.29
 pypdf>=6.0
 
-# zoneinfo reads the OS timezone database, and a slim container or a
-# Windows host has none — ZoneInfo('Asia/Kolkata') then raises
-# ZoneInfoNotFoundError. app/core/clock.py degrades to the default rather
-# than crashing, and its last resort is UTC — so without this every date
-# judgement silently falls back to UTC and an eastern tenant's "today"
-# starts five and a half hours late.
-tzdata>=2024.1
-
 # ── System packages required by the DOCX proposal-template path ──────────────
 # These are NOT pip installable and are not installed by this file.
 #   tesseract-ocr   (4.1.1, 'eng' model)  — OCR of images embedded in templates
 #   libreoffice-writer (7.3.7)            — DOCX -> PDF for docx-kind proposals
 # Both are called through subprocess; no Python wrapper package is used.
```
