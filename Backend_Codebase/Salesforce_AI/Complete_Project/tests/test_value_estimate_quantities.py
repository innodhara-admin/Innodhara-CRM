"""A pricing line is scaled by ITS OWN count, not by one count for all lines.

Found live 2026-08-06 on the datacentre demo, from the app's project card:

    "in the app - projects card - it is showing an amount - Rs. 51,540,000
     is this correct amount according to you?"

It was not. The datacentre programme prices in three different units:

    per rack     4,500  x 120 racks =   540,000
    per hall   185,000  x   2 halls =   370,000
    per site   240,000  x   1 site  =   240,000
                                      ---------
                                      1,150,000     <- the truth

`_estimate_value` took the single `pricing_quantity` the planner extracted
(120, the rack count) and multiplied EVERY non-flat line by it:

    per rack     4,500  x 120 =    540,000
    per hall   185,000  x 120 = 22,200,000
    per site   240,000  x 120 = 28,800,000
                               ----------
                               51,540,000     <- 45x overstated

Why it survived: every earlier catalogue priced in ONE unit (per student, per
seat, per workshop), where "one count for all lines" and "each line's own
count" give the same answer. The datacentre catalogue is the first with three
units in one programme.

Why it matters beyond a wrong number: `proposal_service` has always read each
line's `default_quantity`, so the PROPOSAL for this project totalled 1,150,000
while the project CARD said 51,540,000. Two numbers for one engagement, both on
screen, in front of a client.
"""
from __future__ import annotations

import pytest

from tests.test_genericity import _FakeDb, _FakePricing, _FakeProgram

pytestmark = pytest.mark.asyncio


# The live datacentre table, verbatim from scripts/reset_for_datacentre_demo.py
_DATACENTRE = [
    {"code": "rack_commissioning", "unit": "per rack",
     "unit_price": 4500, "default_quantity": 120},
    {"code": "power_on_checks", "unit": "per hall",
     "unit_price": 185000, "default_quantity": 2},
    {"code": "handover_pack", "unit": "per site",
     "unit_price": 240000, "default_quantity": 1},
]


async def test_the_reported_number_is_gone() -> None:
    """The headline, as the number the product owner read off the screen."""
    from app.engines.planner_engine import _estimate_value

    value = await _estimate_value(
        _FakeDb(_FakePricing(_DATACENTRE)), "org-1", _FakeProgram(), 120
    )
    assert value != 51_540_000, "the 45x overstatement is back"
    assert value == 1_150_000, (
        f"expected 4500*120 + 185000*2 + 240000*1 = 1,150,000, got {value:,.0f}"
    )


async def test_a_bigger_client_count_cannot_inflate_the_other_lines() -> None:
    """The failure mode, isolated: the discussed count must not leak onto lines
    that carry their own. 160 racks must not mean 160 sites."""
    from app.engines.planner_engine import _estimate_value

    value = await _estimate_value(
        _FakeDb(_FakePricing(_DATACENTRE)), "org-1", _FakeProgram(), 160
    )
    # Deliberately unchanged: every line declares its own count (see the
    # "known limit" note in _estimate_value's docstring).
    assert value == 1_150_000, (
        "a line with its own default_quantity was scaled by the client's count"
    )


async def test_a_line_without_its_own_count_still_uses_the_discussed_one() -> None:
    """The fallback that keeps every pre-existing catalogue working. Nothing in
    seed_workflows or the dry-run fixtures declares default_quantity."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([{"code": "seat", "unit": "per seat", "unit_price": 1200}]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 40) == 48000


async def test_mixed_table_takes_each_line_from_the_right_place() -> None:
    """One line with its own count, one without, one flat — all in one table."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([
        {"code": "rack", "unit": "per rack", "unit_price": 1000, "default_quantity": 5},
        {"code": "seat", "unit": "per seat", "unit_price": 100},   # falls back to 10
        {"code": "setup", "unit": "one-time", "unit_price": 7000},  # flat
    ]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 10) == 5000 + 1000 + 7000


async def test_a_zero_default_is_an_answer_not_a_missing_value() -> None:
    """`default_quantity: 0` means "none of these are included" — it must not
    fall through to the client's count and silently charge for them."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([
        {"code": "spare", "unit": "per rack", "unit_price": 9999, "default_quantity": 0},
        {"code": "base", "unit": "flat", "unit_price": 1000},
    ]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 50) == 1000


async def test_a_junk_default_falls_back_instead_of_crashing() -> None:
    """`default_quantity` comes from admin-entered JSON. A bad value must not
    take the whole planner down mid-meeting."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([
        {"code": "x", "unit": "per unit", "unit_price": 100, "default_quantity": "many"},
    ]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 3) == 300


async def test_the_card_and_the_proposal_agree() -> None:
    """The real defect was DISAGREEMENT. Price the same table both ways and
    require one number — this is the assertion that would have caught it."""
    from app.services.proposal_service import compute_totals

    line_items = [
        {"unit_price": float(i["unit_price"]),
         "quantity": float(i.get("default_quantity", 1) or 1)}
        for i in _DATACENTRE
    ]
    proposal_total = compute_totals(line_items)

    from app.engines.planner_engine import _estimate_value

    card_value = await _estimate_value(
        _FakeDb(_FakePricing(_DATACENTRE)), "org-1", _FakeProgram(), 120
    )
    assert card_value == proposal_total, (
        f"project card says {card_value:,.0f} but the proposal for the same "
        f"engagement totals {proposal_total:,.0f}"
    )


async def test_the_seeded_education_table_prices_its_own_quantities() -> None:
    """seed_demo's table also declares per-line counts (12 workshops, 40 kits,
    1 showcase). It was being priced as 12 of everything — including 12 annual
    showcases, of which there is one."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([
        {"code": "workshop", "unit": "per workshop", "unit_price": 2000,
         "default_quantity": 12},
        {"code": "kit", "unit": "per kit", "unit_price": 500, "default_quantity": 40},
        {"code": "showcase", "unit": "per event", "unit_price": 15000,
         "default_quantity": 1},
    ]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 12) == (
        2000 * 12 + 500 * 40 + 15000 * 1
    ) == 59000
