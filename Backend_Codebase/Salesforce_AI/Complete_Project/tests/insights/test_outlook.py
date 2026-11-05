"""Outlook (spec 6.3, 7.6): expected wins from stage history, smoothed
toward starting estimates while history is small, nudged by deal score."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core import clock
from app.insights import outlook
from tests.insights.builders import make_lead, make_note, make_org, make_user

NOW = datetime(2026, 10, 22, 6, 0)          # Q4 2026, in Kolkata too
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _org(db, name="Outlook Org"):
    org = await make_org(db, name=name)
    agent = await make_user(db, org, name="Asha Agent", role="sales_agent")
    head = await make_user(db, org, name="Lata Lead", role="sales_lead")
    return org, agent, head


async def _open_deal(db, org, owner, creator, *, name="Live Deal", state="open"):
    """A deal scoring exactly 50: open, last touched 5 days ago."""
    moves = [("cold_calling", "open", owner, NOW - 30 * DAY)]
    if state == "active":
        moves.append(("open", "active", creator, NOW - 20 * DAY))
    lead = await make_lead(db, org, name=name, state=state, owner=owner, created_by=creator,
                           created_at=NOW - 40 * DAY, moves=tuple(moves))
    await make_note(db, org, lead, by=owner, at=NOW - 5 * DAY)
    return lead


async def _past_win(db, org, head, i, *, won_days_ago=200):
    w = NOW - won_days_ago * DAY
    return await make_lead(db, org, name=f"Past Win {i}", state="execution_in_progress",
                           owner=head, created_by=head, created_at=w - 90 * DAY, moves=(
                               ("cold_calling", "open", head, w - 80 * DAY),
                               ("open", "active", head, w - 40 * DAY),
                               ("active", "execution_in_progress", head, w)))


def _deals(result):
    return {d["lead_id"]: d for m in result["months"]["items"] for d in m["deals"]}


async def test_prior_dominates_with_no_history(db):
    org, agent, head = await _org(db)
    lead = await _open_deal(db, org, agent, head)
    result = await outlook.build(db, org.id, TZ, NOW)
    assert _deals(result)[lead.id]["p"] == 0.25
    assert _deals(result)[lead.id]["score"] == 50
    assert result["summary"]["won"] == 0
    assert result["summary"]["status"] == "thin"          # nothing decided yet
    assert result["method_note"]


async def test_history_moves_the_rate(db):
    org, agent, head = await _org(db)
    for i in range(10):
        await _past_win(db, org, head, i)
    lead = await _open_deal(db, org, agent, head)
    result = await outlook.build(db, org.id, TZ, NOW)
    # open: (10 wins + 0.25 x 10) / (10 exits + 10) = 0.625, score 50 → x1.0
    assert _deals(result)[lead.id]["p"] == 0.625
    assert result["summary"]["status"] == "ok"


async def test_range_never_below_won(db):
    org, agent, head = await _org(db)
    for i in range(3):
        await _past_win(db, org, head, i, won_days_ago=10)        # won this quarter
    cold = await make_lead(db, org, name="Barely Alive", state="cold", owner=agent,
                           created_by=head, created_at=NOW - 90 * DAY,
                           moves=(("cold_calling", "open", agent, NOW - 80 * DAY),
                                  ("open", "cold", "system", NOW - 60 * DAY)))
    assert cold
    won, expected, low, high = await outlook.expected_wins(db, org.id, TZ, NOW)
    assert won == 3
    assert low >= 3 and expected >= 3 and high >= expected
    summary = (await outlook.build(db, org.id, TZ, NOW))["summary"]
    assert (summary["won"], summary["low"]) == (3, 3)


async def test_expected_month_uses_stage_days(db):
    org, agent, head = await _org(db)
    lead = await _open_deal(db, org, agent, head, state="active")
    result = await outlook.build(db, org.id, TZ, NOW)
    # active: 25 days from 22 Oct = 16 Nov
    month = next(m for m in result["months"]["items"]
                 if lead.id in {d["lead_id"] for d in m["deals"]})
    assert month["month"] == "2026-11"
    assert [m["month"] for m in result["months"]["items"]][:3] == ["2026-10", "2026-11",
                                                                    "2026-12"]


async def test_month_deals_are_listed_most_likely_first(db):
    org, agent, head = await _org(db)
    a = await _open_deal(db, org, agent, head, name="Deal A", state="active")
    b = await _open_deal(db, org, agent, head, name="Deal B", state="active")
    await make_note(db, org, b, by=agent, at=NOW - DAY)          # fresher: higher score
    november = next(m for m in (await outlook.build(db, org.id, TZ, NOW))["months"]["items"]
                    if m["month"] == "2026-11")
    assert [d["lead_id"] for d in november["deals"]] == [b.id, a.id]


async def test_lead_flow_uses_cold_calling_count(db):
    org, agent, head = await _org(db)
    for i in range(20):
        await make_lead(db, org, name=f"Prospect {i}", state="cold_calling", owner=agent,
                        created_by=head, created_at=NOW - 3 * DAY)
    flow = (await outlook.build(db, org.id, TZ, NOW))["lead_flow"]
    assert (flow["expected"], flow["low"], flow["high"]) == (7, 4, 10)
    assert [h["month"] for h in flow["history"]] == ["2026-08", "2026-09", "2026-10"]


async def test_by_person_credits_closer(db):
    org, agent, head = await _org(db)
    for i in range(4):
        await _open_deal(db, org, agent, head, name=f"Handed {i}", state="active")
    people = (await outlook.build(db, org.id, TZ, NOW))["by_person"]["items"]
    assert [(p["user_id"], p["name"]) for p in people] == [(head.id, "Lata Lead")]
    # four active deals at 0.45 x (0.5 + 58/100) = 0.486 each → about 2
    assert people[0]["expected"] == 2


async def test_cumulative_runs_over_the_quarter(db):
    org, _, head = await _org(db)
    await _past_win(db, org, head, 1, won_days_ago=10)            # 12 Oct
    cumulative = (await outlook.build(db, org.id, TZ, NOW))["cumulative"]
    weeks = cumulative["weeks"]
    assert weeks[0]["week_start"] == "2026-09-28"                 # the week of 1 Oct
    assert weeks[-1]["week_start"] == "2026-12-28"
    assert weeks[cumulative["today_index"]]["week_start"] == "2026-10-19"
    assert [w["won_cum"] for w in weeks[:4]] == [0, 0, 1, 1]


async def test_a_deal_that_went_cold_counts_against_its_stage(db):
    """Deals rarely say no; they go quiet. A round that ended in `cold` is a
    deal that did not win from `open`, or the rate only ever hears from the
    deals that were decided out loud and runs high."""
    org, agent, head = await _org(db)
    for i in range(10):
        await _past_win(db, org, head, i)
    for i in range(10):
        went = NOW - 150 * DAY
        await make_lead(db, org, name=f"Went Quiet {i}", state="cold", owner=agent,
                        created_by=head, created_at=went - 30 * DAY, moves=(
                            ("cold_calling", "open", agent, went - 20 * DAY),
                            ("open", "cold", "system", went)))
    lead = await _open_deal(db, org, agent, head)
    result = await outlook.build(db, org.id, TZ, NOW)
    # open: (10 wins + 2.5) / (20 exits + 10) = 0.417
    assert _deals(result)[lead.id]["p"] == round(12.5 / 30, 3)


async def test_a_deal_expected_after_the_quarter_is_not_counted_in_it(db):
    """The headline and the month bars on one screen must agree: a deal the
    screen places in January is not a win expected this quarter."""
    late = datetime(2026, 12, 1, 6, 0)
    org, agent, head = await _org(db)
    colds = [await make_lead(db, org, name=f"Slow Burner {i}", state="cold", owner=agent,
                             created_by=head, created_at=late - 40 * DAY, moves=(
                                 ("cold_calling", "open", agent, late - 30 * DAY),
                                 ("open", "cold", "system", late - 3 * DAY)))
             for i in range(10)]
    cold = colds[0]
    active = await make_lead(db, org, name="Nearly There", state="active", owner=agent,
                             created_by=head, created_at=late - 40 * DAY, moves=(
                                 ("cold_calling", "open", agent, late - 30 * DAY),
                                 ("open", "active", head, late - 3 * DAY)))
    result = await outlook.build(db, org.id, TZ, late)
    months = {m["month"]: m for m in result["months"]["items"]}
    assert cold.id in {d["lead_id"] for d in months["2027-01"]["deals"]}      # 60 days on
    assert active.id in {d["lead_id"] for d in months["2026-12"]["deals"]}    # 25 days on
    p_active = next(d["p"] for d in months["2026-12"]["deals"] if d["lead_id"] == active.id)
    assert result["summary"]["expected"] == round(p_active)
    quarter = sum(months[m]["expected"] for m in ("2026-10", "2026-11", "2026-12"))
    assert quarter == result["summary"]["expected"]
    won, expected, low, high = await outlook.expected_wins(db, org.id, TZ, late)
    assert expected == result["summary"]["expected"]
