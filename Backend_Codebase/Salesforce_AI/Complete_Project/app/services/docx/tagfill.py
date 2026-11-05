# app/services/docx/tagfill.py
"""Write resolved values into a copy of a simple-flow template.

Pure and deterministic. No model is called here and nothing is read from the
database: values arrive already resolved and already reviewed by a human (D13),
so given the same source, occurrence map and values this produces the same
document every time.

**The source document is never rewritten** (D3), the same rule the complex flow
follows. Generation is `source + occurrence map + values -> a new file`.

Two things about the order and they are not preferences:

*Right to left within each paragraph.* Replacing left to right invalidates
every later offset in the same paragraph -- the owner's template has a cell
carrying four tags, and the first replacement would move the other three.

*Re-verify before writing.* The offsets were captured when the document was
scanned. Immediately before each write the live text is read back, and if
`raw` is no longer sitting at `[start, end)` the write is **refused** and
recorded as skipped. A stale offset must never become a value written into the
wrong sentence of a client-facing proposal.
"""
from __future__ import annotations

import io
from collections import defaultdict
from typing import Any, Iterable, Mapping

from docx import Document

from app.services.docx import index as ix
from app.services.docx import text as dt

#: Why an occurrence was not written. Reported rather than raised: one bad
#: entry must not cost the other twenty-four their values, and the caller
#: needs to be able to tell a person exactly what was left behind.
SKIP_NO_VALUE = "no value"
SKIP_STALE = "the tag is no longer at those offsets"
SKIP_NO_SUCH_PARAGRAPH = "no such paragraph in this document"


def apply_tags(
    docx_bytes: bytes,
    occurrences: Iterable[Mapping[str, Any]],
    values: Mapping[str, str],
) -> dict[str, Any]:
    """Replace each occurrence with its value, and say what happened.

    `occurrences` are the records as stored -- `Occurrence.as_dict()`, or the
    `tags` list out of `plan_json`. `values` maps `tag_id` to the text to
    write. Returns the new document plus a `written` and a `skipped` list, so
    a caller can refuse to ship a document that still has tags in it.
    """
    doc = Document(io.BytesIO(docx_bytes))
    walk = dt.walk_paragraphs(doc)

    by_paragraph: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for occurrence in occurrences:
        ordinal = occurrence["ordinal"]
        if not 0 <= ordinal < len(walk):
            skipped.append(_note(occurrence, SKIP_NO_SUCH_PARAGRAPH))
            continue
        value = values.get(occurrence["tag_id"])
        if value is None:
            skipped.append(_note(occurrence, SKIP_NO_VALUE))
            continue
        by_paragraph[ordinal].append(occurrence)

    for ordinal, group in by_paragraph.items():
        paragraph = walk[ordinal]
        for occurrence in sorted(group, key=lambda o: o["start"], reverse=True):
            start, end, raw = occurrence["start"], occurrence["end"], occurrence["raw"]
            # Read the live text back every time: an earlier write in this same
            # paragraph was to the right of this one and must not have moved it.
            if dt.node_text(paragraph)[start:end] != raw:
                skipped.append(_note(occurrence, SKIP_STALE))
                continue
            value = str(values[occurrence["tag_id"]])
            dt.replace_span(paragraph, start, end, value)
            written.append({
                "tag_id": occurrence["tag_id"],
                "ordinal": ordinal,
                "raw": raw,
                "value": value,
            })

    # Exactly what fill.apply does. A static contents page needs LibreOffice to
    # re-measure its page numbers, so `index.refresh_static` stays the caller's
    # job, as it is for the complex flow in docx_proposal_service.
    if ix.detect(doc) == "field":
        ix.mark_fields_dirty(doc)

    buf = io.BytesIO()
    doc.save(buf)
    return {"docx": buf.getvalue(), "written": written, "skipped": skipped}


def _note(occurrence: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "tag_id": occurrence.get("tag_id"),
        "ordinal": occurrence.get("ordinal"),
        "raw": occurrence.get("raw"),
        "reason": reason,
    }
