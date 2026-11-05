# app/ai/docx_prose.py
"""Ask the model for the prose a fill plan needs — and check what comes back.

One call for every prose placeholder in a proposal, because the placeholders
share a document and should share a voice. The model gets a brief per
placeholder and the facts it may use; it returns plain text.

It is never shown the document to rewrite. That is the point. A model handed a
whole document and told to improve it is the mechanism behind the original
defect — it starts describing the work ("I will now draft the greeting")
instead of doing it. Here there is nothing to narrate: each answer is one
paragraph's worth of text, and the brief it was given never enters the file.

Every answer goes through `fill_scrub`. One retry, naming what was wrong. After
that the placeholder is left unfilled and escalated — an honest blank a human
is told about beats a plausible invention in a document that goes to a client.
"""
from __future__ import annotations

import logging
from typing import Any

from app.ai.llm import TIER_STRONG, get_model_layer
from app.services import fill_scrub

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

_FACT_LABELS = [
    ("org_name", "Our organisation"),
    ("sender_name", "Who is sending this"),
    ("client_name", "The client"),
    ("contact_name", "Main contact"),
    ("contact_title", "Their role"),
    ("program_name", "What we are proposing"),
    ("program_description", "What that is"),
    ("project_objective", "What the client wants (from the meeting)"),
    ("meeting_notes", "Notes from the meeting"),
    ("date", "Today"),
]

_PROMPT = """You are writing sections of a sales proposal that will be placed \
into an existing, professionally designed document.

FACTS YOU MAY USE — these are all you know. Do not use anything else, and do \
not invent facts, names, dates, numbers or prices:
{facts}

SECTIONS TO WRITE:
{sections}

RULES — these are not stylistic preferences, they are what makes the output \
usable:
- Return PLAIN TEXT only. No markdown of any kind: no **bold**, no ## headings, \
no bullet characters, no tables, no backticks. The document supplies all \
formatting; any marker you type will be printed literally to the client.
- Write the section itself. Never write about writing it, never introduce your \
answer, never restate the brief, never leave a blank like [Name] or [Insert Date].
- Never state a price, total, discount or payment figure. The document's \
pricing comes from a locked rate table.
- Stay within each section's word budget.
- Match a warm, professional, factual business register.
- If you cannot write a section from the facts above, return null for its text \
and give a short reason. A blank a human can fill is correct; an invention is not.
{retry}
Return JSON: {{"placeholders": [{{"key": "...", "text": "..." or null, \
"reason": "..."}}]}}"""


def build_prompt(entries: list[dict], facts: dict[str, Any],
                 retry_notes: dict[str, list[str]] | None = None) -> str:
    fact_lines = []
    for key, label in _FACT_LABELS:
        value = (facts or {}).get(key)
        if value is not None and str(value).strip():
            fact_lines.append(f"- {label}: {str(value).strip()}")
    if not fact_lines:
        fact_lines.append("- (nothing supplied)")

    section_lines = []
    for entry in entries:
        section_lines.append(
            f'- key "{entry["key"]}": {entry.get("brief", "").strip()} '
            f'(at most {entry.get("max_words", 90)} words)'
        )

    retry = ""
    if retry_notes:
        problems = "\n".join(
            f'- "{key}" was rejected because: {", ".join(reasons)}'
            for key, reasons in retry_notes.items()
        )
        retry = (
            "\nYOUR PREVIOUS ANSWER WAS REJECTED. Fix exactly these problems "
            f"and return only the listed sections:\n{problems}\n"
        )

    return _PROMPT.format(
        facts="\n".join(fact_lines),
        sections="\n".join(section_lines),
        retry=retry,
    )


_SCHEMA = {
    "type": "object",
    "properties": {
        "placeholders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "text": {"type": "string", "nullable": True},
                    "reason": {"type": "string", "nullable": True},
                },
                "required": ["key"],
            },
        }
    },
    "required": ["placeholders"],
}


async def fill_prose(ctx, *, entries: list[dict], facts: dict[str, Any],
                     allowed_amounts: set[float]) -> dict[str, dict[str, Any]]:
    if not entries:
        return {}

    by_key = {e["key"]: e for e in entries}
    results: dict[str, dict[str, Any]] = {
        key: {"text": None, "reasons": [], "attempts": 0} for key in by_key
    }
    pending = list(entries)
    retry_notes: dict[str, list[str]] | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if not pending:
            break
        prompt = build_prompt(pending, facts, retry_notes)
        data = await get_model_layer().generate_json(
            purpose="proposal.docx_fill",
            tier=TIER_STRONG,
            org_id=getattr(ctx, "org_id", None),
            user_id=getattr(ctx, "user_id", None),
            messages=[{"role": "user", "content": prompt}],
            json_schema=_SCHEMA,
            temperature=0.4,
            max_tokens=4096,
        )
        answered = {
            item.get("key"): item
            for item in (data or {}).get("placeholders", [])
            if item.get("key")
        }

        next_pending: list[dict] = []
        next_notes: dict[str, list[str]] = {}
        for entry in pending:
            key = entry["key"]
            results[key]["attempts"] = attempt
            item = answered.get(key)
            text = (item or {}).get("text")

            if text is None or not str(text).strip():
                # An explicit refusal is the contract working. Do not retry it.
                results[key]["reasons"] = [
                    (item or {}).get("reason") or fill_scrub.REJECTION_BLANK
                ]
                continue

            reasons = fill_scrub.scrub(
                str(text),
                brief=entry.get("brief", ""),
                max_words=int(entry.get("max_words", 90) or 90),
                allowed_amounts=allowed_amounts,
            )
            if not reasons:
                # Line breaks are kept: `fill._paragraph_texts` needs them to
                # split a "paragraphs" shape into one paragraph per line, and
                # collapses them itself for a single-paragraph shape.
                results[key]["text"] = str(text).strip()
                results[key]["reasons"] = []
                continue

            results[key]["reasons"] = reasons
            logger.warning(
                "Rejected model prose for '%s' (attempt %s): %s",
                key, attempt, ", ".join(reasons),
            )
            if attempt < MAX_ATTEMPTS:
                next_pending.append(entry)
                next_notes[key] = reasons

        pending = next_pending
        retry_notes = next_notes or None

    return results
