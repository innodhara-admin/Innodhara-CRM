"""Clients screen (spec 6.5, 7.8): client health from the deal score,
score against silence, the mood in replies, promises, and clients who look
ready to buy again."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core import clock
from app.insights import clients
from tests.insights.builders import (
    make_commitment, make_engagement, make_inbound, make_lead, make_note, make_org,
    make_project, make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _org(db):
    org = await make_org(db, name="Clients Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    return org, agent


async def _deal(db, org, agent, name, state, touched_days_ago):
    lead = await make_lead(db, org, name=name, state=state, owner=agent, created_by=agent,
                           created_at=NOW - 90 * DAY)
    await make_note(db, org, lead, by=agent, at=NOW - touched_days_ago * DAY)
    return lead


async def test_health_counts_match_scores(db):
    org, agent = await _org(db)
    await _deal(db, org, agent, "Fresh Active", "active", 1)       # 50+8+10 = 68 healthy
    await _deal(db, org, agent, "Fresh Open", "open", 2)           # 60 healthy
    await _deal(db, org, agent, "Quiet Open", "open", 10)          # 42 watch
    await _deal(db, org, agent, "Cold One", "cold", 20)            # 20 at risk
    await _deal(db, org, agent, "Delivered", "closed", 1)          # not in play
    health = (await clients.build(db, org.id, TZ, NOW))["health"]
    assert (health["healthy"], health["watch"], health["at_risk"]) == (2, 1, 1)


async def test_scatter_days_quiet(db):
    org, agent = await _org(db)
    lead = await _deal(db, org, agent, "Quiet Open", "open", 10)
    points = (await clients.build(db, org.id, TZ, NOW))["scatter"]["points"]
    assert points == [{"lead_id": lead.id, "name": "Quiet Open", "days_quiet": 10,
                       "score": 42, "health": "watch"}]


async def test_mood_empty_when_no_replies(db):
    org, agent = await _org(db)
    await _deal(db, org, agent, "Silent Client", "open", 1)
    mood = (await clients.build(db, org.id, TZ, NOW))["mood"]
    assert mood["status"] == "empty"
    assert mood["note"] == "No client replies have been read yet."


async def test_mood_by_month(db):
    org, agent = await _org(db)
    lead = await _deal(db, org, agent, "Talkative Client", "open", 1)
    await make_inbound(db, org, lead, at=datetime(2026, 10, 5), sentiment="positive")
    await make_inbound(db, org, lead, at=datetime(2026, 10, 6), sentiment="negative")
    await make_inbound(db, org, lead, at=datetime(2026, 9, 6), sentiment="neutral")
    await make_inbound(db, org, lead, at=datetime(2026, 6, 6), sentiment="negative")  # too old
    mood = (await clients.build(db, org.id, TZ, NOW))["mood"]
    assert mood["months"] == [
        {"month": "2026-08", "positive": 0, "neutral": 0, "negative": 0},
        {"month": "2026-09", "positive": 0, "neutral": 1, "negative": 0},
        {"month": "2026-10", "positive": 1, "neutral": 0, "negative": 1},
    ]


async def test_promises_by_direction(db):
    org, agent = await _org(db)
    lead = await _deal(db, org, agent, "Promised Client", "active", 1)
    project = await make_project(db, org, lead)
    for direction, status in (("ours", "kept"), ("ours", "kept"), ("ours", "broken"),
                              ("ours", "open"), ("theirs", "kept"), ("theirs", "broken"),
                              ("theirs", "broken")):
        await make_commitment(db, org, project, direction=direction, status=status,
                              due=NOW - 5 * DAY)
    promises = (await clients.build(db, org.id, TZ, NOW))["promises"]
    assert promises["ours"] == {"kept": 2, "total": 3}
    assert promises["theirs"] == {"kept": 1, "total": 3}


async def test_ready_to_buy_again(db):
    org, agent = await _org(db)
    rm = await make_user(db, org, name="Meena", role="relationship_manager")
    lead = await _deal(db, org, agent, "Happy Client", "closed", 3)
    await make_engagement(db, org, lead, manager=rm, opportunity_status="open",
                          reason="Asked about a second batch", at=NOW - 2 * DAY)
    other = await _deal(db, org, agent, "Quiet Client", "closed", 3)
    await make_engagement(db, org, other, manager=rm)
    items = (await clients.build(db, org.id, TZ, NOW))["opportunities"]["items"]
    assert items == [{"lead_id": lead.id, "name": "Happy Client",
                      "reason": "Asked about a second batch",
                      "at": (NOW - 2 * DAY).isoformat() + "Z"}]


async def test_an_org_without_clients_is_empty(db):
    org, _ = await _org(db)
    result = await clients.build(db, org.id, TZ, NOW)
    for name in ("health", "scatter", "mood", "promises", "opportunities"):
        assert result[name]["status"] == "empty", name
