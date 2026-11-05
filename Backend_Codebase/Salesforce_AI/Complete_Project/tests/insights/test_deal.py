"""Deal drill-down (spec 6.6): who, the score and why, the client's people,
what happened, and a proposal value only when one is priced."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.core import clock
from app.core.exceptions import NotFoundError
from app.insights import deal
from app.models.insight import InsightSnapshot
from tests.insights.builders import (
    make_followup, make_lead, make_meeting, make_org, make_outbound,
    make_project, make_proposal, make_stakeholder, make_task, make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")


async def _deal(db, name="Drilled Client"):
    org = await make_org(db, name="Deal Org")
    agent = await make_user(db, org, name="Asha Agent", role="sales_agent")
    head = await make_user(db, org, name="Lata Lead", role="sales_lead")
    lead = await make_lead(db, org, name=name, state="active", owner=agent, created_by=head,
                           created_at=NOW - 60 * DAY, moves=(
                               ("cold_calling", "open", agent, NOW - 50 * DAY),
                               ("open", "active", head, NOW - 12 * DAY)))
    return org, agent, head, lead


async def test_deal_header_and_score(db):
    org, agent, head, lead = await _deal(db)
    await make_meeting(db, org, lead, by=head, at=NOW - 10 * DAY)
    db.add(InsightSnapshot(org_id=org.id, day=date(2026, 10, 20), kind="deal_score",
                           subject_id=lead.id, value={"score": 51}))
    await db.flush()
    result = await deal.build(db, org.id, TZ, NOW, lead_id=lead.id)
    header = result["deal"]
    assert (header["name"], header["state"], header["label"]) == ("Drilled Client", "active",
                                                                  "Active")
    assert header["days_in_state"] == 12
    assert (header["opener"], header["closer"]) == ("Asha Agent", "Lata Lead")
    assert (header["key_date_label"], header["key_date"]) == ("Last meeting", "2026-10-12")
    score = result["score"]
    # active +8, one meeting +5, quiet 10 days -8
    assert score["value"] == 55 and score["health"] == "watch"
    assert {f["key"] for f in score["factors"]} == {"stage_active", "meetings", "quiet_8_14"}
    assert score["trend"] == [{"date": "2026-10-20", "score": 51},
                              {"date": "2026-10-22", "score": 55}]
    assert result["proposal_value"] is None


async def test_deal_timeline_newest_first_and_capped(db):
    org, agent, head, lead = await _deal(db)
    await make_meeting(db, org, lead, by=head, at=NOW - 10 * DAY, minutes=42)
    await make_outbound(db, org, lead, sender=head, sent_at=NOW - 9 * DAY)
    await make_outbound(db, org, lead, sender=head, sent_at=None, status="draft")
    await make_proposal(db, org, lead, status="sent", sent_at=NOW - 8 * DAY)
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 14),
                        completed_at=NOW - 7 * DAY)
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 20))   # overdue
    await make_task(db, org, assignee=agent, due=NOW - 6 * DAY, completed_at=NOW - 6 * DAY,
                    lead=lead)
    result = await deal.build(db, org.id, TZ, NOW, lead_id=lead.id)
    items = result["timeline"]["items"]
    kinds = [i["kind"] for i in items]
    assert kinds == ["followup_overdue", "task_done", "followup_done", "proposal_sent",
                     "message_sent", "meeting", "state", "state", "created"]
    assert items == sorted(items, key=lambda i: i["at"], reverse=True)
    assert all(i["at"].endswith("Z") for i in items)
    for i in range(40):
        await make_task(db, org, assignee=agent, due=NOW - (20 + i) * DAY,
                        completed_at=NOW - (20 + i) * DAY, lead=lead)
    capped = await deal.build(db, org.id, TZ, NOW, lead_id=lead.id)
    assert len(capped["timeline"]["items"]) == 30


async def test_proposal_value_only_when_priced(db):
    org, agent, head, unpriced = await _deal(db, name="Unpriced Client")
    await make_proposal(db, org, unpriced, status="sent", sent_at=NOW - 3 * DAY,
                        total_amount=0.0)
    assert (await deal.build(db, org.id, TZ, NOW, lead_id=unpriced.id))["proposal_value"] is None
    priced = await make_lead(db, org, name="Priced Client", state="active", owner=agent,
                             created_by=head, created_at=NOW - 30 * DAY)
    await make_proposal(db, org, priced, status="draft", total_amount=10.0)
    await make_proposal(db, org, priced, status="sent", sent_at=NOW - 3 * DAY,
                        total_amount=950000.0)
    result = await deal.build(db, org.id, TZ, NOW, lead_id=priced.id)
    assert result["proposal_value"] == {"amount": 950000.0, "currency": "INR"}
    assert (result["deal"]["key_date_label"], result["deal"]["key_date"]) == (
        "Proposal sent", "2026-10-19")


async def test_deal_in_other_org_is_not_found(db):
    org, *_ = await _deal(db)
    other = await make_org(db, name="Other Org")
    theirs = await make_lead(db, other, name="Not Yours", state="open", created_at=NOW)
    with pytest.raises(NotFoundError):
        await deal.build(db, org.id, TZ, NOW, lead_id=theirs.id)
    with pytest.raises(NotFoundError):
        await deal.build(db, org.id, TZ, NOW, lead_id="no-such-lead")


async def test_people_met_flag(db):
    org, agent, head, lead = await _deal(db)
    project = await make_project(db, org, lead, sales_owner=head)
    boss = await make_stakeholder(db, org, project, influence="decision_maker",
                                  name="Mrs Rao", role_at_client="owner")
    await make_stakeholder(db, org, project, influence="gatekeeper", name="Mr Das")
    await make_meeting(db, org, lead, by=head, at=NOW - 3 * DAY, stakeholder_ids=[boss.id])
    people = (await deal.build(db, org.id, TZ, NOW, lead_id=lead.id))["people"]
    assert people["status"] == "ok"
    assert people["items"] == [
        {"name": "Mrs Rao", "role_at_client": "owner", "influence": "decision_maker", "met": True},
        {"name": "Mr Das", "role_at_client": None, "influence": "gatekeeper", "met": False},
    ]


async def test_no_project_means_no_people_yet(db):
    org, *_, lead = await _deal(db)
    people = (await deal.build(db, org.id, TZ, NOW, lead_id=lead.id))["people"]
    assert (people["status"], people["items"]) == ("empty", [])
    assert people["note"]
