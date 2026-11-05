"""Unfinished-draft detection — the blanks a model leaves behind (finding F30).

A model that is missing a fact sometimes writes a fill-in-the-blank instead of
saying it does not know: *"Vendor Sign-off: [Name]"*, *"Date: [Insert Date]"*.
That is F28's failure wearing a different coat — neither resolving nor asking —
except this one ends up in a client's inbox, and `EMAIL_MODE` is live.

This is a **deterministic fence, not a prompt**. Four times now (F9, F4, F23,
F28) this project has watched a model ignore an instruction it was given in
capitals. The prompt asking the model to escalate instead of leaving a blank is
worth having; it is the hint. This module is the guard.

Kept deliberately narrow — a false positive blocks a legitimate send, so a
bracketed phrase only counts when it looks like a **field label** rather than
prose. `[see attached]` is not a blank; `[Name]` and `[Insert Date]` are.
"""
from __future__ import annotations

import re

# "[Insert Date]", "[Enter your name]" — an explicit instruction to fill in.
_FILL_WORDS = r"(?:insert|enter|add|specify|choose|select|your|tbd|placeholder|xxx)"
_BRACKETED = re.compile(r"\[([^\[\]\n]{1,60})\]")
_FILL_PREFIX = re.compile(rf"^\s*{_FILL_WORDS}\b", re.IGNORECASE)
# "[Name]", "[Designation]", "[Client Name]" — a label, not a sentence: only
# letters and simple separators, at most five words, and capitalised the way a
# form field is. Digits, punctuation or lower-case prose disqualify it, which is
# what keeps "[see attached]" and "[Rs 59,000]" out.
_LABEL = re.compile(r"^[A-Za-z][A-Za-z /&'-]{0,58}$")
# "{{name}}" and an unrendered "{client_name}" — the shape this project's own
# message templates use, so one that survives into a body is a real defect
# (F6 warned that a renamed variable silently blanks itself).
_MUSTACHE = re.compile(r"\{\{\s*[\w.]+\s*\}\}")
# The lookarounds keep "{{contact_name}}" from ALSO being reported as the inner
# "{contact_name}" — one blank, one entry.
_TEMPLATE_VAR = re.compile(r"(?<!\{)\{\s*[a-z][a-z0-9_]{1,40}\s*\}(?!\})")
_TBD = re.compile(r"\bTBD\b")
# "[missing:context_summary]" — this project's OWN marker, emitted by
# `template_service` for exactly one reason: "so a human notices instead of
# silently sending blanks". F47: one of these reached a real client PDF past
# this guard running in strict mode. It escaped because `_LABEL` rejects the
# colon and the underscores, and "missing" is not a fill word — so the single
# token designed to be caught was the one token nothing looked for.
#
# Safe to match exactly, with no risk to the deliberate narrowness above: this
# is generated text in a fixed shape, never prose a person would write.
_MISSING_KEY = re.compile(r"\[missing:[a-zA-Z0-9_]+\]")


def _is_label(inner: str) -> bool:
    if not _LABEL.match(inner):
        return False
    words = inner.split()
    if len(words) > 5:
        return False
    # Title Case or ALL CAPS: how a form field is written, not how prose is.
    return all(w[0].isupper() for w in words if w[:1].isalpha())


def find_blanks(*texts: str | None) -> list[str]:
    """Every fill-in-the-blank in these texts, de-duplicated, in order found.

    Empty list means the draft is finished as far as this check can tell — it
    is a floor, not a proof of quality.
    """
    found: list[str] = []

    def keep(token: str) -> None:
        if token not in found:
            found.append(token)

    for text in texts:
        if not text:
            continue
        for match in _BRACKETED.finditer(text):
            inner = match.group(1)
            if _FILL_PREFIX.search(inner) or _is_label(inner):
                keep(match.group(0))
        for pattern in (_MISSING_KEY, _MUSTACHE, _TEMPLATE_VAR, _TBD):
            for match in pattern.finditer(text):
                keep(match.group(0))
    return found


def blank_lines(text: str | None, blanks: list[str]) -> list[str]:
    """The actual lines the blanks sit on — so a refusal can quote the draft
    back rather than just naming tokens. This is the part the 300-character
    approval preview was hiding."""
    if not text or not blanks:
        return []
    return [
        line.strip()
        for line in text.splitlines()
        if any(blank in line for blank in blanks)
    ]


def refusal_message(blanks: list[str], lines: list[str]) -> str:
    """What the person tapping Approve is told. Their words, their draft — no
    jargon, and it says exactly how to get past it."""
    listed = ", ".join(blanks[:6])
    message = (
        f"This draft still has {len(blanks)} blank(s) to fill in: {listed}. "
        "Nothing was sent."
    )
    if lines:
        quoted = " / ".join(line[:120] for line in lines[:3])
        message += f" It reads: {quoted}"
    message += (
        " Ask the assistant to fill them in, reject it with a note so it is "
        "redrafted, or approve again confirming you want to send it as it is."
    )
    return message
