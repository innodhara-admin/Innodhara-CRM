"""The deal score (spec 7.7): start at 50, add each factor that fires, clamp
to 0..100, and say which factors fired. Each test builds a deal on which
exactly the factor under test fires: a note five days ago keeps the "days
quiet" factor at zero points, and the deal is in `open`, which scores 0."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core import clock
from app.insights import scoring
from tests.insights.builders import (
    make_commitment, make_demo, make_followup, make_inbound, make_lead, make_meeting,
    make_note, make_org, make_project, make_proposal, make_stakeholder, make_thread,
    make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _deal(db, *, state="open", touched_days_ago=5, important=False):
    org = await make_org(db, name="Score Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    lead = await make_lead(db, org, name="Scored Client", state=state, owner=agent,
                           created_by=agent, created_at=NOW - 60 * DAY,
                           is_important=important)
    if touched_days_ago is not None:
        await make_note(db, org, lead, by=agent, at=NOW - touched_days_ago * DAY)
    return org, agent, lead


async def _score(db, org, lead):
    return (await scoring.score_deals(db, org.id, [lead], NOW, tz=TZ))[lead.id]


def _keys(score):
    return [f["key"] for f in score.factors]


async def test_quiet_four_to_seven_days_scores_nothing(db):
    org, _, lead = await _deal(db)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (50, [])


@pytest.mark.parametrize("days, key, points", [
    (1, "quiet_0_3", 10), (3, "quiet_0_3", 10),
    (8, "quiet_8_14", -8), (14, "quiet_8_14", -8),
    (15, "quiet_15_plus", -18), (40, "quiet_15_plus", -18),
])
async def test_days_quiet(db, days, key, points):
    org, _, lead = await _deal(db, touched_days_ago=days)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score), score.days_quiet) == (50 + points, [key], days)


async def test_never_touched_counts_quiet_from_creation(db):
    org, _, lead = await _deal(db, touched_days_ago=None)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score), score.days_quiet) == (32, ["quiet_15_plus"], 60)


async def test_stage_active(db):
    org, _, lead = await _deal(db, state="active")
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (58, ["stage_active"])


async def test_stage_cold(db):
    org, _, lead = await _deal(db, state="cold")
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (38, ["stage_cold"])


async def test_meetings_count_up_to_three(db):
    org, agent, lead = await _deal(db)
    # A meeting is activity too: keep the newest one five days back.
    for days in (9, 8, 7, 6, 5):
        await make_meeting(db, org, lead, by=agent, at=NOW - days * DAY)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (65, ["meetings"])
    assert score.factors[0]["points"] == 15


async def test_demo_done(db):
    org, _, lead = await _deal(db)
    await make_demo(db, org, lead, status="completed", completed_at=NOW - 20 * DAY)
    await make_demo(db, org, lead, status="scheduled")
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (56, ["demo_done"])


async def test_proposal_sent_and_answered(db):
    org, _, lead = await _deal(db)
    await make_proposal(db, org, lead, status="sent", sent_at=NOW - 10 * DAY)
    await make_inbound(db, org, lead, at=NOW - 9 * DAY)  # they answered...
    # ...and that reply is itself activity, but older than the note: quiet stays 5 days.
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (56, ["proposal_sent"])


async def test_proposal_unanswered_for_a_week(db):
    org, _, lead = await _deal(db)
    await make_proposal(db, org, lead, status="sent", sent_at=NOW - 8 * DAY)
    await make_thread(db, org, lead, last_direction="outbound", last_message_at=NOW - 8 * DAY)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (44, ["proposal_sent", "proposal_unanswered"])


async def test_a_proposal_sent_six_days_ago_is_not_unanswered_yet(db):
    org, _, lead = await _deal(db)
    await make_proposal(db, org, lead, status="sent", sent_at=NOW - 6 * DAY)
    score = await _score(db, org, lead)
    assert _keys(score) == ["proposal_sent"]


async def test_draft_proposal_scores_nothing(db):
    org, _, lead = await _deal(db)
    await make_proposal(db, org, lead, status="draft")
    assert _keys(await _score(db, org, lead)) == []


async def test_decision_maker_never_met(db):
    org, agent, lead = await _deal(db)
    project = await make_project(db, org, lead)
    boss = await make_stakeholder(db, org, project, influence="decision_maker")
    helper = await make_stakeholder(db, org, project, influence="influencer")
    await make_meeting(db, org, lead, by=agent, at=NOW - 30 * DAY, stakeholder_ids=[helper.id])
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (43, ["meetings", "decision_maker_unmet"])
    # Once the decision maker is in a meeting, the factor goes.
    await make_meeting(db, org, lead, by=agent, at=NOW - 29 * DAY, stakeholder_ids=[boss.id])
    assert "decision_maker_unmet" not in _keys(await _score(db, org, lead))


async def test_negative_reply_in_thirty_days(db):
    org, _, lead = await _deal(db)
    await make_inbound(db, org, lead, at=NOW - 29 * DAY, sentiment="negative")
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (40, ["negative_reply"])


async def test_an_old_negative_reply_is_forgotten(db):
    org, _, lead = await _deal(db)
    await make_inbound(db, org, lead, at=NOW - 31 * DAY, sentiment="negative")
    assert _keys(await _score(db, org, lead)) == []


async def test_our_broken_promises_count_up_to_two(db):
    org, _, lead = await _deal(db)
    project = await make_project(db, org, lead)
    for _ in range(3):
        await make_commitment(db, org, project, direction="ours", status="broken",
                              due=NOW - 20 * DAY)
    await make_commitment(db, org, project, direction="theirs", status="broken",
                          due=NOW - 20 * DAY)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (34, ["promise_broken"])
    assert score.factors[0]["points"] == -16


async def test_followup_overdue(db):
    org, agent, lead = await _deal(db)
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 21))
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 22))  # due today
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (44, ["followup_overdue"])


async def test_marked_important(db):
    org, _, lead = await _deal(db, important=True)
    score = await _score(db, org, lead)
    assert (score.value, _keys(score)) == (54, ["important"])


async def test_score_clamps(db):
    org, agent, lead = await _deal(db, state="cold", touched_days_ago=20)
    await make_proposal(db, org, lead, status="sent", sent_at=NOW - 20 * DAY)
    project = await make_project(db, org, lead)
    await make_stakeholder(db, org, project, influence="decision_maker")
    await make_inbound(db, org, lead, at=NOW - 25 * DAY, sentiment="negative")
    for _ in range(2):
        await make_commitment(db, org, project, direction="ours", status="broken",
                              due=NOW - 20 * DAY)
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 1))
    score = await _score(db, org, lead)
    assert score.value == 0
    assert score.health == "at_risk"


async def test_scores_many_deals_at_once(db):
    org, agent, quiet = await _deal(db, touched_days_ago=20)
    busy = await make_lead(db, org, name="Busy Client", state="active", owner=agent,
                           created_by=agent, created_at=NOW - 60 * DAY)
    await make_note(db, org, busy, by=agent, at=NOW - DAY)
    scores = await scoring.score_deals(db, org.id, [quiet, busy], NOW, tz=TZ)
    assert (scores[quiet.id].value, scores[busy.id].value) == (32, 68)


def test_health_thresholds():
    assert scoring.health_of(100) == "healthy"
    assert scoring.health_of(60) == "healthy"
    assert scoring.health_of(59) == "watch"
    assert scoring.health_of(40) == "watch"
    assert scoring.health_of(39) == "at_risk"
    assert scoring.health_of(0) == "at_risk"
