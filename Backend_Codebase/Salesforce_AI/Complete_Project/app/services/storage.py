"""File storage under per-organisation folders: orgs/{org_id}/{category}/...

Local filesystem now; the same relative-path contract maps 1:1 onto S3/GCS
keys later (doc §2.4 "Files and memory are namespaced too").
"""
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from app.config import get_settings
from app.core.exceptions import NotFoundError, PermissionDeniedError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

CATEGORY_AUDIO = "audio"
CATEGORY_CARDS = "cards"
CATEGORY_PROPOSALS = "proposals"
CATEGORY_OUTBOX = "outbox"  # dry-run email/whatsapp dumps


def _root() -> Path:
    root = get_settings().storage_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize(filename: str) -> str:
    cleaned = _SAFE_NAME.sub("_", filename.strip()) or "file"
    return cleaned[-120:]


def save_bytes(org_id: str, category: str, filename: str, data: bytes) -> str:
    """Store bytes; returns the org-relative path kept in the database."""
    rel = f"orgs/{org_id}/{category}/{uuid4().hex[:8]}_{_sanitize(filename)}"
    target = _root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel


def save_text(org_id: str, category: str, filename: str, text: str) -> str:
    return save_bytes(org_id, category, filename, text.encode("utf-8"))


def resolve(org_id: str, rel_path: str) -> Path:
    """Resolve a stored path, refusing anything outside the caller's org folder.

    **Containment is tested on the RESOLVED path, never on the string that was
    sent.** The prefix check this replaced ran first, so
    `orgs/{mine}/../{theirs}/x` satisfied `startswith("orgs/{mine}/")` and then
    resolved into another tenant's folder — one organisation reading another's
    meeting audio, business-card images and generated proposals. Only the walk
    out of STORAGE_DIR was caught; the tenant boundary inside it was not.

    `is_relative_to` compares path components rather than characters, so a
    sibling directory whose name merely begins the same way (`orgs/{id}-old`)
    is outside `orgs/{id}` — which a `startswith` on the two paths would have
    called inside.
    """
    org_root = (_root() / "orgs" / org_id).resolve()
    target = (_root() / rel_path).resolve()
    if not target.is_relative_to(org_root):
        raise PermissionDeniedError("File does not belong to your organisation")
    if not target.exists():
        raise NotFoundError("File not found")
    return target


def read_bytes(org_id: str, rel_path: str) -> bytes:
    return resolve(org_id, rel_path).read_bytes()


def delete_file(org_id: str, rel_path: str) -> bool:
    try:
        resolve(org_id, rel_path).unlink()
        return True
    except (NotFoundError, OSError):
        return False


def org_path(rel_path: str) -> Path:
    """Absolute path without org check — for internal system use only."""
    return _root() / rel_path
