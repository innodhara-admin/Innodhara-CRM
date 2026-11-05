# app/services/docx/fill.py
"""Apply a fill plan to a copy of the template. Pure and deterministic.

No model is called here. Values arrive already resolved — system-bound ones
from the database, prose from `app.ai.docx_prose` after it has passed the
scrubber — so this module can be reasoned about, tested and replayed without a
network. Given the same source, plan and values it produces the same document.

Order matters. Structural entries are applied first, from the END of the
document backwards, because inserting a paragraph at `body[5]` shifts every
later positional path by one. Token replacement runs last, over the whole
document, so it also reaches text that was just inserted.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from docx import Document

from app.services.docx import edit
from app.services.docx import index as ix
from app.services.docx import outline as ol
from app.services.docx import text as dt

logger = logging.getLogger(__name__)

PLAN_KINDS = ("token", "table", "insert", "replace")
_LIST_STYLE = "List Bullet"


def validate_plan(plan: dict, outline: dict) -> list[str]:
    problems: list[str] = []
    entries = plan.get("entries") or []
    known_paths = {b["path"] for b in outline["blocks"]}
    seen_keys: set[str] = set()

    for i, entry in enumerate(entries):
        kind = entry.get("kind")
        key = entry.get("key")
        where = f"entry {i + 1}"
        if kind not in PLAN_KINDS:
            problems.append(f"{where}: unknown placeholder kind '{kind}'")
            continue
        if not key:
            problems.append(f"{where}: has no key")
            continue
        if key in seen_keys:
            problems.append(f"{where}: '{key}' is used more than once")
        seen_keys.add(key)

        if kind == "token":
            if not entry.get("literal"):
                problems.append(f"{where} ('{key}'): no literal to replace")
        elif kind in ("table", "replace"):
            path = entry.get("path")
            if path not in known_paths:
                problems.append(f"{where} ('{key}'): '{path}' is not a block in this document")
        elif kind == "insert":
            anchor = entry.get("after") or entry.get("before")
            if anchor not in known_paths:
                problems.append(f"{where} ('{key}'): '{anchor}' is not a block in this document")
            if entry.get("style_ref") not in known_paths:
                problems.append(
                    f"{where} ('{key}'): style reference "
                    f"'{entry.get('style_ref')}' is not a block in this document"
                )
    return problems


def _paragraph_texts(value: Any, shape: str) -> list[str]:
    text = str(value).strip()
    if shape == "paragraph":
        return [" ".join(text.split())]
    parts = [" ".join(p.split()) for p in text.split("\n") if p.strip()]
    return parts or [text]


def apply(docx_bytes: bytes, plan: dict, values: dict[str, Any]) -> dict[str, Any]:
    doc = Document(io.BytesIO(docx_bytes))
    entries = list(plan.get("entries") or [])
    filled: list[dict[str, Any]] = []
    unfilled: list[str] = []

    structural = [e for e in entries if e["kind"] in ("insert", "replace", "table")]
    tokens = [e for e in entries if e["kind"] == "token"]

    # Verify every anchor BEFORE mutating anything, so a stale plan leaves the
    # document untouched rather than half-written.
    for entry in structural:
        path = entry.get("path") or entry.get("after") or entry.get("before")
        if entry.get("fingerprint"):
            ol.verify(doc, path, entry["fingerprint"])

    # Later blocks first: an insert shifts the positional paths after it.
    def order(entry):
        path = entry.get("path") or entry.get("after") or entry.get("before") or ""
        digits = "".join(ch if ch.isdigit() else " " for ch in path).split()
        return [int(d) for d in digits] or [0]

    for entry in sorted(structural, key=order, reverse=True):
        key = entry["key"]
        kind = entry["kind"]
        value = values.get(key)

        if kind == "table":
            if not value:
                unfilled.append(key)
                filled.append({"key": key, "kind": kind, "source": "unfilled",
                               "text": "", "brief": "", "anchor": entry.get("path")})
                continue
            columns = [c["col"] for c in entry["columns"]]
            fields = [c["field"] for c in entry["columns"]]
            rows = [[row.get(f, "") for f in fields] for row in value["rows"]]
            total = entry.get("total_row")
            total_row = None
            if total and value.get("total") is not None:
                total_row = {"label_col": total["label_col"],
                             "value_col": total["value_col"],
                             "value": value["total"]}
            edit.fill_table(doc, entry["path"], rows,
                            header_rows=entry.get("header_rows", 1),
                            total_row=total_row, columns=columns)
            filled.append({"key": key, "kind": kind, "source": "system",
                           "text": f"{len(rows)} row(s)", "brief": "",
                           "anchor": entry["path"]})
            continue

        if value is None or not str(value).strip():
            unfilled.append(key)
            filled.append({"key": key, "kind": kind, "source": "unfilled",
                           "text": "", "brief": entry.get("brief", ""),
                           "anchor": entry.get("path") or entry.get("after")})
            continue

        shape = entry.get("shape", "paragraph")
        texts = _paragraph_texts(value, shape)
        if kind == "replace":
            edit.set_paragraph_text(doc, entry["path"], texts[0])
            anchor = entry["path"]
        else:
            list_style = _LIST_STYLE if shape == "bullets" else None
            if entry.get("after"):
                edit.insert_paragraphs_after(doc, entry["after"], entry["style_ref"],
                                             texts, list_style=list_style)
                anchor = entry["after"]
            else:
                edit.insert_paragraphs_before(doc, entry["before"], entry["style_ref"],
                                              texts, list_style=list_style)
                anchor = entry["before"]
        filled.append({"key": key, "kind": kind, "source": "ai",
                       "text": " ".join(texts), "brief": entry.get("brief", ""),
                       "anchor": anchor})

    for entry in tokens:
        key, literal = entry["key"], entry["literal"]
        value = values.get(key)
        if value is None or not str(value).strip():
            unfilled.append(key)
            filled.append({"key": key, "kind": "token", "source": "unfilled",
                           "text": "", "brief": "", "anchor": literal})
            continue
        count = dt.replace_token(doc, literal, str(value))
        filled.append({"key": key, "kind": "token", "source": "system",
                       "text": str(value), "brief": "",
                       "anchor": f"{literal} ×{count}"})

    if ix.detect(doc) == "field":
        ix.mark_fields_dirty(doc)

    buf = io.BytesIO()
    doc.save(buf)
    return {"docx": buf.getvalue(), "filled": filled, "unfilled": unfilled}
