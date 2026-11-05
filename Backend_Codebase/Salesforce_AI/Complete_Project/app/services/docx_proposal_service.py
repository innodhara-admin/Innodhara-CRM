# app/services/docx_proposal_service.py
"""Turn a docx template plus a plan into a filled proposal document.

Splits cleanly in two, and the split is the safety property:

  * system values — the client's name, the contact, the date, and every cell
    of the price table — are resolved here from the database and the locked
    pricing version. No model is involved and none can be.
  * prose values — greetings, summaries, closings — come from one call to
    `docx_prose`, which scrubs and retries and refuses to invent.

`proposal_service` keeps ownership of the numbers exactly as before.
"""
from __future__ import annotations

import logging
from typing import Any

from app.ai import docx_prose
from app.services.docx import fill as docx_fill
from app.services.docx import index as docx_index
from app.services.docx import outline as docx_outline

logger = logging.getLogger(__name__)

_SYSTEM_KINDS = ("token", "table")


def _pricing_value(line_items: list[dict[str, Any]], total: str,
                   entry: dict, currency: str) -> dict[str, Any]:
    """Currency is passed explicitly and `line_items` is NEVER mutated: it is
    persisted to `Proposal.line_items` (a JSON column) and returned to the
    Android app, so stashing a private `_currency` key on each item would leak
    it into stored data and into the mobile contract."""
    from app.services.proposal_service import _money  # noqa: PLC0415

    fields = [c["field"] for c in entry["columns"]]
    rows = []
    for item in line_items:
        row = {}
        for field in fields:
            raw = item.get(field)
            if field in ("unit_price", "line_total"):
                row[field] = _money(float(raw or 0), currency)
            elif field == "quantity":
                row[field] = str(int(float(raw or 0)))
            else:
                row[field] = str(raw or "")
        rows.append(row)
    return {"rows": rows, "total": total}


async def build_docx_content(
    db, ctx, *, source_bytes: bytes, plan: dict,
    variables: dict[str, Any], line_items: list[dict[str, Any]],
    total_amount: float, currency: str, facts: dict[str, Any],
    prose_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """`prose_overrides` supplies text for prose placeholders that must NOT be
    regenerated. An edit that names one section re-fills only that section and
    passes the rest back verbatim, so a proposal does not quietly change
    wording nobody asked about. Empty on a first build."""
    from app.services.proposal_service import _allowed_amounts, _money  # noqa: PLC0415

    entries = list(plan.get("entries") or [])
    values: dict[str, Any] = {}

    for entry in entries:
        if entry["kind"] == "token":
            values[entry["key"]] = variables.get(entry["key"])
        elif entry["kind"] == "table":
            values[entry["key"]] = _pricing_value(
                line_items, _money(total_amount, currency), entry, currency
            )

    overrides = prose_overrides or {}
    for key, text in overrides.items():
        values[key] = text

    prose_entries = [
        e for e in entries
        if e["kind"] in ("insert", "replace") and e["key"] not in overrides
    ]
    if prose_entries:
        prose = await docx_prose.fill_prose(
            ctx,
            entries=prose_entries,
            facts=facts,
            allowed_amounts=_allowed_amounts(line_items, total_amount),
        )
        for key, result in prose.items():
            if result["text"]:
                values[key] = result["text"]
            else:
                logger.warning(
                    "Placeholder '%s' left unfilled: %s",
                    key, ", ".join(result["reasons"]) or "no text returned",
                )

    result = docx_fill.apply(source_bytes, plan, values)

    if docx_index.detect_bytes(result["docx"]) == "static":
        result["docx"] = docx_index.refresh_static(result["docx"])

    outline = docx_outline.parse(result["docx"])
    result["content_md"] = docx_outline.project_text(outline)
    return result
