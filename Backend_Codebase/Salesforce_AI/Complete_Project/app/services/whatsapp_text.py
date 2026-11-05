"""Text that a WhatsApp template will accept (4 Nov 2026).

WhatsApp refuses a template value containing a new line, a tab or more than
four spaces in a row, and a template body over 1024 characters. Numbers are
sent as digits with the country code and no "+". Everything sent through
`whatsapp_providers` passes through here first.
"""
from __future__ import annotations

import re

BODY_LIMIT = 1024
MORE = "… more in the app"

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*\*|__|\*|_)(.+?)\1")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def normalise_phone(raw: str | None, country_code: str = "91") -> str | None:
    """Digits with the country code: "09310524629" -> "919310524629".

    A 10-digit national number gets `country_code`; a trunk "0" before it is
    dropped. Anything shorter than 10 digits is not a usable number."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = f"{country_code}{digits}"
    return digits if len(digits) >= 11 else None


def clean_value(text: str | None, *, fallback: str = "-") -> str:
    """One line, no tabs, no runs of spaces; `fallback` when nothing is left
    (WhatsApp refuses an empty value too)."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned or fallback


def fold(values: dict[str, str], *, fixed_len: int, limit: int = BODY_LIMIT,
         shrink_order: tuple[str, ...]) -> dict[str, str]:
    """Shorten the values named in `shrink_order`, first one first, until the
    template's fixed text plus every value fits in `limit`."""
    out = dict(values)
    for name in shrink_order:
        over = fixed_len + sum(len(v) for v in out.values()) - limit
        if over <= 0:
            break
        value = out[name]
        keep = max(0, len(value) - over - len(MORE))
        out[name] = value[:keep].rstrip() + MORE
    return out


def _plain(line: str) -> str:
    line = _LINK.sub(r"\1", line)
    line = _EMPHASIS.sub(r"\2", line)
    return clean_value(line, fallback="")


def markdown_to_line(md: str) -> str:
    """A digest's markdown as one line: "Title: item; item. Title: item"."""
    sections: list[tuple[str, list[str]]] = []
    for raw in (md or "").splitlines():
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            sections.append((_plain(raw.lstrip().lstrip("#")), []))
            continue
        text = _plain(_BULLET.sub("", raw))
        if text.endswith(":") and not _BULLET.match(raw):
            sections.append((text[:-1].strip(), []))
            continue
        if not sections:
            sections.append(("", []))
        sections[-1][1].append(text)
    parts = []
    for title, items in sections:
        body = "; ".join(i for i in items if i)
        if title and body:
            parts.append(f"{title}: {body}")
        else:
            parts.append(title or body)
    return ". ".join(p for p in parts if p)
