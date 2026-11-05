# app/services/mou_arithmetic.py
"""Does the arithmetic in a contract hold? (D-E)

**D15 is not weakened here and cannot be.** No figure a model produced ever
reaches a document: this module never returns a value to write, only a
sentence saying two figures disagree. In a proposal an `ask_calculate` is a
number on a page; in an MOU it is a payment schedule, and instalments that do
not sum to their total is a defect a human will not always catch.

Pure by design -- no model, no database, no I/O -- so every rule is decided in
code rather than argued about in a prompt.

**Decimal throughout.** `0.1 * 3` is `0.30000000000000004` in binary floating
point, and a contract that warns about that is worse than one that does not
check at all.

**Silence beats a false alarm.** If any figure in a relation cannot be read
with certainty, there is no warning. A spurious warning on a legitimately
negotiated figure teaches the reader to dismiss the warnings, which destroys
the only thing this check is for.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

#: One run of digits, with Indian or Western grouping and an optional decimal.
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Words a contract puts around an amount that do not change what it is.
_DECORATION_RE = re.compile(
    r"\b(?:rs|inr|net|nett|only|incl|including|inclusive|of|gst|tax|taxes|"
    r"per|student|students|annually|annual|annum|year|yearly|amount|"
    r"payable|paid|approximately|approx|total)\b",
    re.IGNORECASE,
)

#: Punctuation and currency marks that likewise mean nothing here.
_PUNCTUATION_RE = re.compile(r"[₹$()\[\]/,.\-–—:;\s]+")

OPERATORS = ("product", "sum")


def _is_a_bare_amount(text: str, number: str) -> bool:
    """Is `text` that number and nothing else that matters?

    This is what separates "Rs. 3,00,000/- Net (Including GST)." -- an amount
    -- from "1 Set" and "second week of February 2027", which each contain
    exactly one number and are not amounts at all. Without it the check would
    read the year out of a completion date and compare it to a price.
    """
    rest = text.replace(number, " ", 1)
    rest = _DECORATION_RE.sub(" ", rest)
    rest = _PUNCTUATION_RE.sub(" ", rest)
    return rest.strip() == ""


def parse_amount(text: Any) -> Decimal | None:
    """The single amount `text` states, or None if it does not state one.

    None -- never a guess -- for: nothing at all, prose with no number, a
    number embedded in words ("1 Set"), and a RANGE. The proposal flow's own
    `ask_calculate` default is a range ("Rs. 15,00,000/- to Rs. 25,00,000/-"),
    and choosing an end of it would be worse than declining to check.
    """
    if not isinstance(text, str):
        return None
    found = _NUMBER_RE.findall(text)
    if len(found) != 1:
        return None
    if not _is_a_bare_amount(text, found[0]):
        return None
    try:
        return Decimal(found[0].replace(",", ""))
    except InvalidOperation:
        return None


def _indian(value: Decimal) -> str:
    """3,00,000 rather than 300,000 -- the grouping the documents use."""
    whole = int(abs(value))
    fraction = abs(value) - whole
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    if fraction:
        digits += ("%.2f" % fraction)[1:]
    return ("-" if value < 0 else "") + digits


def check(relations: list[dict[str, Any]] | None,
          values: dict[str, Any]) -> list[dict[str, Any]]:
    """Every relation whose arithmetic does not hold, as a report.

    A relation is `{"result": tag_id, "op": "product"|"sum", "operands":
    [tag_id, ...]}` -- tag ids and an operator, never a number. It says which
    tags relate, and this decides whether the PERSON'S OWN ANSWERS agree.

    Returns `result`, `expected`, `actual` and a `message` naming both figures
    so a reader can see which one is wrong. It deliberately returns no value
    to write: this reports, it never substitutes.
    """
    mismatches: list[dict[str, Any]] = []
    for relation in relations or []:
        operator = relation.get("op")
        operands = relation.get("operands") or []
        if operator not in OPERATORS or len(operands) < 2:
            continue

        actual = parse_amount(values.get(relation.get("result")))
        if actual is None:
            continue
        parsed = [parse_amount(values.get(tag_id)) for tag_id in operands]
        if any(amount is None for amount in parsed):
            continue

        expected = parsed[0]
        for amount in parsed[1:]:
            expected = expected * amount if operator == "product" \
                else expected + amount
        if expected == actual:
            continue

        how = "x".join(_indian(a) for a in parsed) if operator == "product" \
            else " + ".join(_indian(a) for a in parsed)
        mismatches.append({
            "result": relation.get("result"),
            "expected": expected,
            "actual": actual,
            "message": (
                f"this reads {_indian(actual)}, but {how} is "
                f"{_indian(expected)}"
            ),
        })
    return mismatches
