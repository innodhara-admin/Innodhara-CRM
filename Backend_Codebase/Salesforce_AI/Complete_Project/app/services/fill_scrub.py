# app/services/fill_scrub.py
"""The fence between a model's prose and a client's document.

Four times this project has watched a model ignore an instruction it was given
in capitals — F9, F4, F23, F28. The prompt asking for clean, grounded prose is
worth having; it is the hint. This module is the guard.

It is deliberately narrow. A false rejection costs one retry and, at worst, an
honest blank that a human is told about. A false acceptance is a client reading
"I will now draft the greeting paragraph" in a document with our name on it.
"""
from __future__ import annotations

import re

from app.services import draft_check

REJECTION_MARKDOWN = "markdown_markers"
REJECTION_META = "meta_instruction"
REJECTION_BRIEF_ECHO = "restates_the_brief"
REJECTION_PRICE = "unlocked_price"
REJECTION_LENGTH = "too_long"
REJECTION_BLANK = "empty"

# Markdown the DOCX path can never render: it would be printed literally.
_MARKDOWN = (
    re.compile(r"\*\*|__"),                       # bold
    re.compile(r"(?m)^\s{0,3}#{1,6}\s"),          # ATX headings
    re.compile(r"(?m)^\s{0,3}[-*+]\s"),           # bullet lists
    re.compile(r"(?m)^\s{0,3}\d+[.)]\s"),         # ordered lists
    re.compile(r"\|.*\|"),                        # table rows
    re.compile(r"`{1,3}"),                        # code spans
    re.compile(r"(?m)^\s{0,3}>\s"),               # block quotes
)

# A model that is describing the work instead of doing it.
_META = re.compile(
    r"^\s*(?:certainly|sure|of course|okay|ok)\b"
    r"|^\s*(?:here(?:'s| is)|below is|the following|this is)\b"
    r"|^\s*(?:as requested|as instructed|as you asked)\b"
    r"|\bI (?:will|'ll|can|have|shall) (?:now )?(?:write|draft|create|generate|"
    r"produce|prepare|provide|add|insert)\b"
    r"|\b(?:placeholder|to be (?:filled|completed)|fill in (?:the|this))\b",
    re.IGNORECASE,
)

_MONEY_MARKERS = ("rs", "₹", "inr", "usd", "eur", "$")
_PRICE_WORDS = (
    "per ", "price", "cost", "fee", "total", "discount", "rate", "charge",
    "amount", "invest", "each", "subtotal", "quote", "pricing", "sum",
)
# Western grouping (1,234,567), then Indian lakh/crore grouping (8,50,000 —
# how this organisation writes every price in its own templates), then a plain
# run of digits. The Indian branch is required, not decorative: without it
# "Rs 8,50,000" tokenises as ['8', '50,000'], and since 50000 is not one of the
# locked amounts the scrubber rejects prose quoting the *correct* total. That
# is a false rejection of good text, so the retry burns and the placeholder
# ends up blank.
#
# This deliberately diverges from `proposal_service._NUMBER_RE`, which has the
# same blind spot. That one is left alone: it belongs to the markdown path,
# which this feature must not change.
_NUMBER_RE = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d+)?"
    r"|\d+(?:\.\d+)?"
)
_WORD_RE = re.compile(r"\S+")
_TOKEN_RE = re.compile(r"[a-z]{4,}")


def _markdown_reasons(text: str) -> bool:
    return any(pattern.search(text) for pattern in _MARKDOWN)


def _meta_reasons(text: str) -> bool:
    if _META.search(text):
        return True
    # this project's own blank markers: [Name], [Insert Date], {client_name}
    return bool(draft_check.find_blanks(text))


def _echoes_brief(text: str, brief: str) -> bool:
    """The first sentence is largely the brief read back.

    Jaccard over content words of length >= 4, which ignores articles and
    prepositions without needing a stopword list.
    """
    if not brief.strip():
        return False
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    a = set(_TOKEN_RE.findall(first.lower()))
    b = set(_TOKEN_RE.findall(brief.lower()))
    if len(b) < 3 or not a:
        return False
    overlap = len(a & b) / len(a | b)
    return overlap >= 0.6


def _unlocked_price(text: str, allowed: set[float]) -> bool:
    """A money-shaped number that is not one of the locked commercials.

    Same window logic as `proposal_service.narrative_price_drift`: a number
    only counts when a currency marker or a price word sits beside it, so a
    cohort size or a year is not mistaken for a rupee figure.
    """
    low = text.lower()
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0)
        value = float(raw.replace(",", ""))
        if value < 100:
            continue
        if round(value, 2) in allowed:
            continue
        if 1900 <= value <= 2100 and "," not in raw and "." not in raw:
            continue
        window = low[max(0, match.start() - 16):min(len(low), match.end() + 16)]
        if any(m in window for m in _MONEY_MARKERS) or any(w in window for w in _PRICE_WORDS):
            return True
    return False


def scrub(text: str, *, brief: str, max_words: int,
          allowed_amounts: set[float]) -> list[str]:
    """Every reason this text must not go into the document. Empty is clean."""
    reasons: list[str] = []
    if not (text or "").strip():
        return [REJECTION_BLANK]
    if _markdown_reasons(text):
        reasons.append(REJECTION_MARKDOWN)
    if _meta_reasons(text):
        reasons.append(REJECTION_META)
    if _echoes_brief(text, brief):
        reasons.append(REJECTION_BRIEF_ECHO)
    if _unlocked_price(text, allowed_amounts):
        reasons.append(REJECTION_PRICE)
    if max_words and len(_WORD_RE.findall(text)) > max_words:
        reasons.append(REJECTION_LENGTH)
    return reasons
