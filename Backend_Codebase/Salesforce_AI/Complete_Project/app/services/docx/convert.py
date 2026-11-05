"""DOCX -> PDF through LibreOffice headless.

Why not reportlab: the templates this serves are branded documents with cover
art, per-section headers and footers, theme fonts and styled tables. Rebuilding
them from extracted text is what the whole feature exists to stop doing. A
silently unbranded PDF reaching a client is worse than a refusal, so there is
no fallback here — a failure raises.

Each call gets its own `-env:UserInstallation` profile directory. A shared
profile serialises concurrent conversions and, worse, leaves a lock file behind
after a killed process that makes every later convert hang.

Which soffice, and which extra fonts, come from settings (13 Oct 2026):
LibreOffice 7.3 printed the owner's templates with an 11 pt cover title, four
extra pages and overlapping tables, and the VM had none of their fonts. The
copy LibreOffice reads goes through `lo_compat.prepare` first; the document
itself is never changed here.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.services.docx import lo_compat

logger = logging.getLogger(__name__)

SOFFICE = get_settings().libreoffice_bin
FALLBACK_SOFFICE = get_settings().libreoffice_fallback_bin
FONTS_DIR = get_settings().pdf_fonts_dir

#: How long the main LibreOffice gets when there is a fallback to try. Every
#: real template converts in 2-6 s; the one that sends 25.8/26.x into an
#: endless layout loop (CBSE Foundation, 13 Oct 2026) never finishes at all.
#: Short, because the phone app stops waiting after 30 s (NetModule).
FIRST_TRY_SECONDS = get_settings().libreoffice_first_try_seconds


def docx_to_pdf(docx_bytes: bytes, *, timeout: int = 120) -> bytes:
    if not docx_bytes:
        raise ExternalServiceError("Cannot convert an empty document to PDF")
    if not Path(SOFFICE).exists() and shutil.which(SOFFICE) is None:
        raise ExternalServiceError(
            "LibreOffice is not installed on this server, so the proposal PDF "
            "cannot be produced. Install libreoffice-writer, or download the "
            "DOCX instead."
        )
    # A .docx is a zip/OOXML package. LibreOffice's --convert-to autodetect is
    # lenient enough to fall back to a plain-text importer for unrecognised
    # bytes and still emit a "successful" PDF, so garbage input would
    # otherwise pass straight through instead of raising. Reject it here.
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            if "word/document.xml" not in zf.namelist():
                raise ExternalServiceError(
                    "The uploaded file is not a valid DOCX document."
                )
    except zipfile.BadZipFile:
        raise ExternalServiceError(
            "The uploaded file is not a valid DOCX document."
        ) from None
    prepared = lo_compat.prepare(docx_bytes)
    fallback = FALLBACK_SOFFICE if (
        FALLBACK_SOFFICE and FALLBACK_SOFFICE != SOFFICE
        and Path(FALLBACK_SOFFICE).exists()) else None
    if fallback is None:
        return _convert(SOFFICE, prepared, timeout)
    try:
        return _convert(SOFFICE, prepared, min(timeout, FIRST_TRY_SECONDS))
    except ExternalServiceError as exc:
        # Never worse than before the upgrade: the fallback is the converter
        # every document used until 13 Oct 2026.
        logger.warning("%s could not convert this document (%s); using %s",
                       SOFFICE, exc, fallback)
        return _convert(fallback, prepared, timeout)


def _convert(soffice: str, docx_bytes: bytes, timeout: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix="docxpdf_") as tmp:
        work = Path(tmp)
        src = work / "in.docx"
        src.write_bytes(docx_bytes)
        profile = work / "profile"
        _private_fonts(work)
        cmd = [
            soffice, "--headless", "--norestore", "--invisible",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to", "pdf", "--outdir", str(work), str(src),
        ]
        # Its own process group, so a timeout stops all of LibreOffice: the
        # launcher alone used to be killed, and soffice.bin kept running.
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"HOME": str(work), "PATH": "/usr/bin:/bin"},
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _stop(proc)
            raise ExternalServiceError(
                f"Converting the proposal to PDF took longer than {timeout}s "
                "and was stopped."
            ) from exc
        out = work / "in.pdf"
        if not out.exists():
            detail = (stderr or stdout or b"").decode("utf-8", "replace")
            logger.error("soffice produced no PDF: rc=%s %s", proc.returncode, detail[:400])
            raise ExternalServiceError(
                "LibreOffice could not convert this document to PDF."
            )
        return out.read_bytes()


def _private_fonts(work: Path) -> None:
    """HOME is `work`, so fontconfig reads ~/.fonts and ~/.config/fontconfig
    from here: the converter's own fonts and substitutions, seen by no other
    process on the server."""
    if not FONTS_DIR:
        return
    folder = Path(FONTS_DIR)
    if not folder.is_dir():
        logger.error("PDF fonts folder %s is missing; converting with the "
                     "server's fonts only", FONTS_DIR)
        return
    os.symlink(folder, work / ".fonts")
    if (folder / "fonts.conf").is_file():
        conf = work / ".config" / "fontconfig"
        conf.mkdir(parents=True)
        os.symlink(folder / "fonts.conf", conf / "fonts.conf")


def _stop(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.communicate()
