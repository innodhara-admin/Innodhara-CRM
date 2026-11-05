# app/ai/docx_suggest.py
"""Propose placeholders for an uploaded template. Advisory only.

Nothing here reaches a proposal. The output is a list of candidate plan
entries the administrator accepts, rejects, rewords or moves in the console —
so the model is allowed to be wrong, and being wrong costs a click.

What it must not do is be wrong *invisibly*: every suggestion is checked
against the outline before it is returned. A suggestion pointing at a block
that does not exist, or a literal that is not in the document, is dropped
rather than shown, because an administrator cannot be expected to verify
anchors by eye.
"""
from __future__ import annotations

import logging
from typing import Any

from app.ai.llm import TIER_STRONG, get_model_layer

logger = logging.getLogger(__name__)

MAX_BLOCKS = 220
MAX_OCR_CHARS = 4000

BINDABLE_FIELDS = (
    "client_name", "contact_name", "contact_title", "sender_name",
    "sender_email", "org_name", "program_name", "program_description",
    "date", "total_amount",
)

_PROMPT = """You are helping set up a reusable proposal template. Below is an \
existing, professionally designed document broken into numbered blocks. It is \
used for "{program_name}".

Your job is to say WHERE the system should fill things in when a real proposal \
is generated from it. You are not writing content now.

Propose three kinds of placeholder:

1. "token" — a literal phrase in the document that is really a stand-in for a \
field (e.g. the text "School Name" standing in for the client). Give the exact \
literal and which field it maps to. Bindable fields: {fields}.
2. "insert" — a new paragraph the AI should write at generation time, placed \
after (or before) an existing block. Give a "brief" describing what belongs \
there, a word budget, whether it is required, and a "style_ref": the path of an \
existing body paragraph whose formatting it should copy.
3. "table" — an existing table that is really the price list. Map its columns \
to "label", "unit", "unit_price", "quantity" or "line_total", say how many \
header rows it has, and which row is the total.

Be conservative. A document that already reads well needs few inserts. Suggest \
an insert only where something genuinely client-specific is missing — a \
greeting, a summary of what the client asked for, a closing. Never suggest \
replacing the organisation's own descriptive content.

Use only block paths that appear below. Use only literals that appear below.

DOCUMENT BLOCKS:
{blocks}
{ocr}
Return JSON: {{"suggestions": [{{"kind": "token"|"insert"|"table", "key": "...", \
"literal": "...", "path": "...", "after": "...", "before": "...", \
"style_ref": "...", "shape": "paragraph"|"paragraphs"|"bullets", "brief": "...", \
"max_words": 90, "required": true, "columns": [{{"col": 0, "field": "label"}}], \
"header_rows": 1, "total_row": {{"label_col": 0, "value_col": 1}}, \
"confidence": 0.0, "why": "..."}}]}}
Include only the fields each kind needs."""

_SCHEMA = {
    "type": "object",
    "properties": {"suggestions": {"type": "array", "items": {"type": "object"}}},
    "required": ["suggestions"],
}


def _render_blocks(outline: dict) -> str:
    lines = []
    for block in outline["blocks"][:MAX_BLOCKS]:
        kind = block["kind"]
        if kind == "table" and block["table"]:
            head = " | ".join(block["table"]["header"])
            lines.append(
                f'{block["path"]}  TABLE {block["table"]["rows"]}x'
                f'{block["table"]["cols"]}  header: {head}'
            )
        elif kind == "image":
            lines.append(f'{block["path"]}  IMAGE')
        elif kind == "empty":
            continue
        else:
            label = "HEADING" if kind == "heading" else "PARA"
            lines.append(f'{block["path"]}  {label} [{block["style"]}]  '
                         f'{block["text"][:120]}')
    return "\n".join(lines)


def _render_ocr(ocr: dict) -> str:
    if not ocr:
        return ""
    parts, used = [], 0
    for name, value in sorted(ocr.items()):
        if not value:
            continue
        snippet = value[:300]
        used += len(snippet)
        if used > MAX_OCR_CHARS:
            break
        parts.append(f"  {name}: {snippet}")
    if not parts:
        return ""
    return "\nTEXT READ FROM THE IMAGES:\n" + "\n".join(parts) + "\n"


async def suggest(ctx, *, outline: dict, ocr: dict, program_name: str) -> list[dict]:
    prompt = _PROMPT.format(
        program_name=program_name,
        fields=", ".join(BINDABLE_FIELDS),
        blocks=_render_blocks(outline),
        ocr=_render_ocr(ocr),
    )
    data = await get_model_layer().generate_json(
        purpose="proposal.docx_suggest",
        tier=TIER_STRONG,
        org_id=getattr(ctx, "org_id", None),
        user_id=getattr(ctx, "user_id", None),
        messages=[{"role": "user", "content": prompt}],
        json_schema=_SCHEMA,
        temperature=0.2,
        max_tokens=4096,
    )
    return _validate(data or {}, outline)


MIN_LITERAL_CHARS = 4


def _is_plausible_literal(literal: str) -> bool:
    """Could this literal be a stand-in phrase, rather than punctuation?

    The document-membership check on its own is no guard at all: `all_text` is
    the whole document, so any short string is "in" it. Measured against
    `Essential Lab.docx`, a suggested literal of " " was accepted and would
    have rewritten 533 occurrences — every space replaced by the client's
    name — and "e" 369. Token replacement is global and runs over headers and
    footers too, so one such acceptance corrupts the whole file.

    A real stand-in ("School Name", "Client Name") clears this comfortably;
    the curated candidates in `outline["tokens"]` clear it by construction,
    since that regex already demands two or more Title-Case words.
    """
    stripped = (literal or "").strip()
    return len(stripped) >= MIN_LITERAL_CHARS and any(c.isalpha() for c in stripped)


def _validate(data: dict, outline: dict) -> list[dict]:
    by_path = {b["path"]: b for b in outline["blocks"]}
    literals = {t["literal"] for t in outline.get("tokens", [])}
    all_text = " \n".join(b["text"] or "" for b in outline["blocks"])

    kept: list[dict] = []
    seen: set[str] = set()
    for raw in data.get("suggestions", []):
        kind, key = raw.get("kind"), raw.get("key")
        if kind not in ("token", "insert", "table") or not key or key in seen:
            continue

        if kind == "token":
            literal = raw.get("literal") or ""
            if not _is_plausible_literal(literal):
                logger.info("Dropped suggested token %r: too slight to be a "
                            "stand-in phrase", literal)
                continue
            if literal not in literals and literal not in all_text:
                logger.info("Dropped suggested token %r: not in the document", literal)
                continue
            # No occurrence count is attached here on purpose. `all_text` is
            # built from top-level blocks only, so it does not see table cells
            # or text boxes: on Essential Lab.docx it counts "School Name" 4
            # times where dt.count_token finds 7. A count that low would
            # mislead the administrator it was meant to inform. An accurate
            # one needs the document itself, so it belongs where the template
            # service still has the bytes.
            entry = {"kind": "token", "key": key, "literal": literal}

        elif kind == "table":
            path = raw.get("path")
            block = by_path.get(path)
            if block is None or block["kind"] != "table":
                logger.info("Dropped suggested table at %r: not a table here", path)
                continue
            columns = [
                c for c in (raw.get("columns") or [])
                if isinstance(c.get("col"), int) and c.get("field")
            ]
            if not columns:
                continue
            entry = {
                "kind": "table", "key": key, "path": path,
                "fingerprint": block["fingerprint"], "columns": columns,
                "header_rows": int(raw.get("header_rows", 1) or 1),
                "total_row": raw.get("total_row"),
            }

        else:
            anchor = raw.get("after") or raw.get("before")
            style_ref = raw.get("style_ref")
            if anchor not in by_path or style_ref not in by_path:
                logger.info("Dropped suggested insert at %r: unknown anchor", anchor)
                continue
            if by_path[style_ref]["kind"] not in ("paragraph", "heading"):
                continue
            entry = {
                "kind": "insert", "key": key,
                "fingerprint": by_path[anchor]["fingerprint"],
                "style_ref": style_ref,
                "shape": raw.get("shape", "paragraph"),
                "brief": (raw.get("brief") or "").strip(),
                "max_words": int(raw.get("max_words", 90) or 90),
                "required": bool(raw.get("required", False)),
            }
            entry["after" if raw.get("after") else "before"] = anchor
            if not entry["brief"]:
                continue

        entry["confidence"] = float(raw.get("confidence", 0.5) or 0.5)
        entry["why"] = (raw.get("why") or "").strip()
        kept.append(entry)
        seen.add(key)
    return kept
