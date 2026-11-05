# app/services/docx/ocr.py
"""Read text out of the images a template embeds.

These documents carry a great deal of meaning as graphics — measured, 14 to 33
images each, and many paragraphs are nothing but a picture. Without this the
suggestion pass is blind to whole sections and proposes placeholders for the
few pages that happen to be prose.

Runs once at upload and is cached on the template row. It is never on the
proposal-generation path, so a slow OCR costs an administrator seconds while
publishing, and costs a salesperson nothing.

Shells out to the `tesseract` binary rather than adding `pytesseract`: one
fewer dependency, and the timeout is ours.
"""
from __future__ import annotations

import io
import logging
import subprocess
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

TESSERACT = "/usr/bin/tesseract"

_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
_MIN_BYTES = 2048          # below this it is a rule, a bullet or a gradient
_MIN_CHARS = 3


def ocr_document(
    docx_bytes: bytes, *, per_image_timeout: int = 20, max_images: int = 60
) -> dict[str, str]:
    out: dict[str, str] = {}
    if max_images <= 0:
        return out
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        names = [
            n for n in z.namelist()
            if n.startswith("word/media/") and Path(n).suffix.lower() in _EXT
        ]
        for name in sorted(names)[:max_images]:
            info = z.getinfo(name)
            key = name.split("/")[-1]
            if info.file_size < _MIN_BYTES:
                out[key] = ""
                continue
            out[key] = _ocr_one(z.read(name), Path(name).suffix, per_image_timeout)
    return out


def _ocr_one(data: bytes, suffix: str, timeout: int) -> str:
    with tempfile.TemporaryDirectory(prefix="docxocr_") as tmp:
        src = Path(tmp) / f"img{suffix}"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                [TESSERACT, str(src), "stdout", "-l", "eng", "--psm", "6"],
                capture_output=True, timeout=timeout, check=False,
                env={"PATH": "/usr/bin:/bin", "OMP_THREAD_LIMIT": "1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("OCR skipped for one image: %s", exc)
            return ""
        if proc.returncode != 0:
            return ""
        recognised = " ".join(
            proc.stdout.decode("utf-8", "replace").split()
        ).strip()
        return recognised if len(recognised) >= _MIN_CHARS else ""
