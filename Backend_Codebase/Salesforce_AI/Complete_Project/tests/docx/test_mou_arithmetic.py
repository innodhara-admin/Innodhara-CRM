# tests/docx/test_mou_arithmetic.py
"""Arithmetic in a contract (D-E).

D15 is not weakened here and cannot be: no figure a model produced ever
reaches a document. The only thing added is a check that the figures A PERSON
SUPPLIED are consistent with each other -- because in an MOU an
`ask_calculate` is not a number in a document, it is a payment schedule, and
instalments that do not sum to their total is a defect a human will not always
catch.

This module is pure. It has no model, no database and no I/O, so every rule
below is decided here rather than argued about in a prompt.
"""
from decimal import Decimal

import pytest

from app.services.mou_arithmetic import check, parse_amount

pytestmark = pytest.mark.asyncio


# ── reading an amount out of a contract's prose ─────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("Rs. 3,00,000/- Net (Including GST).", Decimal("300000")),
    ("Rs. 4000/- net (including GST) per student annually.", Decimal("4000")),
    ("Rs. 1,50,000/-", Decimal("150000")),
    ("75", Decimal("75")),
    ("  Rs. 1,50,000/- Net (including GST).  ", Decimal("150000")),
    ("32", Decimal("32")),
    ("1,00,00,000", Decimal("10000000")),        # a crore, Indian grouping
    ("2,500.50", Decimal("2500.50")),
])
async def test_indian_grouping_and_decoration_are_read(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "to be agreed",
    "as per the annexure",
    "second week of February 2027",
    "Yes",
    "1 Set",
    # A RANGE is not one amount. The proposal flow's own ask_calculate default
    # is exactly this shape, and guessing which end is meant would be worse
    # than declining to check.
    "Rs. 15,00,000/- to Rs. 25,00,000/-net (including GST)",
    "between 70 and 80 students",
])
async def test_what_cannot_be_read_returns_none_rather_than_guessing(text):
    assert parse_amount(text) is None


# ── the checks themselves ───────────────────────────────────────────────────
async def test_a_product_that_does_not_hold_is_reported():
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "Rs. 4000", "students": "75",
              "total": "Rs. 2,50,000/- Net"}
    (mismatch,) = check(relations, values)
    assert mismatch["result"] == "total"
    assert mismatch["expected"] == Decimal("300000")
    assert mismatch["actual"] == Decimal("250000")
    # The message names BOTH figures, so the reader can see which is wrong.
    assert "3,00,000" in mismatch["message"]
    assert "2,50,000" in mismatch["message"]


async def test_a_product_that_holds_is_silent():
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "Rs. 4000", "students": "75",
              "total": "Rs. 3,00,000/- Net (Including GST)."}
    assert check(relations, values) == []


async def test_instalments_that_do_not_sum_to_their_total_are_reported():
    """The defect this whole decision exists for."""
    relations = [{"result": "total", "op": "sum",
                  "operands": ["first", "second"]}]
    values = {"first": "Rs. 1,50,000/-", "second": "Rs. 1,40,000/-",
              "total": "Rs. 3,00,000/-"}
    (mismatch,) = check(relations, values)
    assert mismatch["expected"] == Decimal("290000")
    assert mismatch["actual"] == Decimal("300000")


async def test_instalments_that_do_sum_are_silent():
    relations = [{"result": "total", "op": "sum",
                  "operands": ["first", "second"]}]
    values = {"first": "Rs. 1,50,000/-", "second": "Rs. 1,50,000/-",
              "total": "Rs. 3,00,000/-"}
    assert check(relations, values) == []


async def test_an_unparseable_operand_produces_NO_warning_at_all():
    """Silence beats a false alarm.

    A spurious warning on a legitimately negotiated figure teaches the reader
    to dismiss the warnings, which destroys the only thing this check is for.
    """
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "as agreed", "students": "75", "total": "Rs. 3,00,000"}
    assert check(relations, values) == []


async def test_an_unparseable_result_produces_no_warning_either():
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "Rs. 4000", "students": "75",
              "total": "to be agreed on signing"}
    assert check(relations, values) == []


async def test_a_missing_value_produces_no_warning():
    """A tag nobody has answered yet is not a mismatch."""
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    assert check(relations, {"price": "Rs. 4000"}) == []


async def test_an_unknown_operator_is_ignored():
    relations = [{"result": "t", "op": "exponentiate", "operands": ["a", "b"]}]
    assert check(relations, {"a": "2", "b": "3", "t": "8"}) == []


async def test_a_relation_with_one_operand_is_ignored():
    """Nothing to check: a product of one number is that number."""
    relations = [{"result": "t", "op": "product", "operands": ["a"]}]
    assert check(relations, {"a": "2", "t": "3"}) == []


async def test_arithmetic_is_decimal_not_float():
    """No floats anywhere near a payment schedule. 0.1 * 3 is 0.30000000000000004
    in binary floating point, and a contract that warns about that is worse
    than one that does not check at all."""
    relations = [{"result": "t", "op": "product", "operands": ["a", "b"]}]
    assert check(relations, {"a": "0.1", "b": "3", "t": "0.3"}) == []


async def test_several_relations_are_all_checked():
    relations = [
        {"result": "total", "op": "product", "operands": ["price", "students"]},
        {"result": "total", "op": "sum", "operands": ["first", "second"]},
    ]
    values = {"price": "Rs. 4000", "students": "75", "total": "Rs. 3,00,000",
              "first": "Rs. 1,50,000", "second": "Rs. 1,40,000"}
    mismatches = check(relations, values)
    assert len(mismatches) == 1          # the product holds, the sum does not
    assert mismatches[0]["expected"] == Decimal("290000")


async def test_the_check_never_returns_a_value_to_write():
    """It reports; it never substitutes. D15: no number reaches a document
    unless Python computed it from a locked rate card or a person typed it,
    and this computes neither -- its only output is a sentence."""
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "Rs. 4000", "students": "75", "total": "Rs. 2,50,000"}
    (mismatch,) = check(relations, values)
    assert set(mismatch) == {"result", "expected", "actual", "message"}
    assert "value" not in mismatch
