"""app/insights/common.py: windows in the org's day, the activity union
(spec 7.5), replaying lead history (7.15), the opener and the closer (7.1b),
and what counts as a win (7.1)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.core import clock
from app.insights import common, team
from tests.insights.builders import (
    make_contact, make_followup, make_inbound, make_lead, make_meeting, make_note,
    make_org, make_outbound, make_project, make_task, make_user,
)

NOW = datetime(2026, 10, 22, 6, 0)
DAY = timedelta(days=1)


def test_buckets_follow_org_day_not_utc():
    tz = clock.zone("Asia/Kolkata")
    # 19:00 UTC on the 22nd is 00:30 on the 23rd in Kolkata.
    assert common.local_day(datetime(2026, 10, 22, 19, 0), tz) == date(2026, 10, 23)
    assert common.day_bounds_utc(date(2026, 10, 23), tz) == (
        datetime(2026, 10, 22, 18, 30), datetime(2026, 10, 23, 18, 30))
    assert common.week_start(date(2026, 10, 25)) == date(2026, 10, 19)  # Sunday → Monday
    assert common.month_bounds_utc("2026-10", tz) == (
        datetime(2026, 9, 30, 18, 30), datetime(2026, 10, 31, 18, 30))


async def test_states_as_of_replays_history(db):
    org = await make_org(db, name="Replay Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    lead = await make_lead(db, org, name="Replay Client", state="active", owner=agent,
                           created_by=agent, created_at=NOW - 20 * DAY, moves=(
                               ("cold_calling", "open", agent, NOW - 10 * DAY),
                               ("open", "active", agent, NOW - 3 * DAY)))
    later = await make_lead(db, org, name="Not Yet Made", state="open", owner=agent,
                            created_by=agent, created_at=NOW - DAY)
    assert (await common.states_as_of(db, org.id, NOW - 5 * DAY))[lead.id] == "open"
    assert (await common.states_as_of(db, org.id, NOW - 15 * DAY))[lead.id] == "cold_calling"
    now = await common.states_as_of(db, org.id, NOW)
    assert now[lead.id] == "active" and now[later.id] == "open"
    assert later.id not in await common.states_as_of(db, org.id, NOW - 5 * DAY)


async def test_activity_union_counts_every_source(db):
    org = await make_org(db, name="Activity Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    lead = await make_lead(db, org, name="Busy Client", state="open", owner=agent,
                           created_by=agent, created_at=NOW - 30 * DAY,
                           moves=(("cold_calling", "open", agent, NOW - 9 * DAY),))
    await make_meeting(db, org, lead, by=agent, at=NOW - 8 * DAY)
    await make_outbound(db, org, lead, sender=agent, sent_at=NOW - 7 * DAY)
    await make_outbound(db, org, lead, sender=agent, sent_at=None, status="draft")
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 16),
                        completed_at=NOW - 6 * DAY)
    await make_followup(db, org, lead, owner=agent, due=date(2026, 10, 30))  # not done
    await make_note(db, org, lead, by=agent, at=NOW - 5 * DAY)
    await make_contact(db, org, lead, by=agent, at=NOW - 4 * DAY)
    await make_task(db, org, assignee=agent, due=NOW - 3 * DAY, completed_at=NOW - 3 * DAY,
                    lead=lead)
    await make_task(db, org, assignee=agent, due=NOW + DAY, lead=lead)  # still open
    await make_inbound(db, org, lead, at=NOW - 2 * DAY)
    found = await common.activity_by_lead(db, org.id, NOW - 20 * DAY, NOW)
    assert len(found[lead.id]) == 8
    last = await common.last_activity(db, org.id, [lead.id], NOW)
    assert last[lead.id] == NOW - 2 * DAY
    # The window is honoured: only the inbound reply is in the last 2.5 days.
    assert len((await common.activity_by_lead(db, org.id, NOW - 2.5 * DAY, NOW))[lead.id]) == 1


async def test_deal_people_follow_the_hand_over(db):
    org = await make_org(db, name="People Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    lead_l = await make_user(db, org, name="Lata", role="sales_lead")
    lead_l2 = await make_user(db, org, name="Leela", role="sales_lead")
    lead_l3 = await make_user(db, org, name="Lokesh", role="sales_lead")
    lead_l4 = await make_user(db, org, name="Laxmi", role="sales_lead")
    handed = await make_lead(db, org, name="Handed Over", state="open", owner=agent,
                             created_by=lead_l, created_at=NOW - 10 * DAY)
    projected = await make_lead(db, org, name="Has A Project", state="active", owner=agent,
                                created_by=lead_l, created_at=NOW - 10 * DAY)
    await make_project(db, org, projected, sales_owner=lead_l2)
    met = await make_lead(db, org, name="Agent Made", state="active", owner=agent,
                          created_by=agent, created_at=NOW - 10 * DAY)
    await make_meeting(db, org, met, by=lead_l3, at=NOW - 5 * DAY)
    await make_meeting(db, org, met, by=lead_l3, at=NOW - 4 * DAY)
    await make_meeting(db, org, met, by=agent, at=NOW - 3 * DAY)
    own = await make_lead(db, org, name="Leads Own", state="active", owner=lead_l4,
                          created_by=lead_l4, created_at=NOW - 10 * DAY)
    people = await common.deal_people(db, org.id, [handed, projected, met, own])
    assert people[handed.id] == (agent.id, lead_l.id)
    assert people[projected.id] == (agent.id, lead_l2.id)
    assert people[met.id] == (agent.id, lead_l3.id)
    assert people[own.id] == (None, lead_l4.id)


async def test_lead_without_owner_has_no_people(db):
    org = await make_org(db, name="Nobody Org")
    lead = await make_lead(db, org, name="Orphan Client", state="open", created_at=NOW - DAY)
    assert (await common.deal_people(db, org.id, [lead]))[lead.id] == (None, None)


async def test_won_is_first_entry_into_execution(db):
    org = await make_org(db, name="Win Org")
    head = await make_user(db, org, name="Lata", role="sales_lead")
    lead = await make_lead(db, org, name="Back And Forth", state="execution_in_progress",
                           owner=head, created_by=head, created_at=NOW - 40 * DAY, moves=(
                               ("cold_calling", "open", head, NOW - 30 * DAY),
                               ("open", "active", head, NOW - 20 * DAY),
                               ("active", "execution_in_progress", head, NOW - 10 * DAY),
                               ("execution_in_progress", "active", head, NOW - 8 * DAY),
                               ("active", "execution_in_progress", head, NOW - 5 * DAY)))
    lost = await make_lead(db, org, name="Went Away", state="lost_for_now", owner=head,
                           created_by=head, created_at=NOW - 40 * DAY, moves=(
                               ("cold_calling", "open", head, NOW - 30 * DAY),
                               ("open", "lost_for_now", head, NOW - 4 * DAY)))
    wins, losses = await common.won_and_lost(db, org.id, NOW - 60 * DAY, NOW)
    assert wins == [(lead.id, NOW - 10 * DAY)]
    assert losses == [(lost.id, NOW - 4 * DAY)]
    # A window that starts after the first entry sees no win at all.
    assert (await common.won_and_lost(db, org.id, NOW - 7 * DAY, NOW))[0] == []


async def test_a_meeting_not_yet_held_is_not_activity(db):
    org = await make_org(db, name="Booked Org")
    agent = await make_user(db, org, name="Asha", role="sales_agent")
    lead = await make_lead(db, org, name="Booked Client", state="open", owner=agent,
                           created_by=agent, created_at=NOW - 30 * DAY)
    booked = await make_meeting(db, org, lead, by=agent, at=NOW - DAY)
    booked.status = "scheduled"
    await db.flush()
    assert lead.id not in await common.activity_by_lead(db, org.id, NOW - 7 * DAY, NOW)
    counts = await team.counts_by_person(db, org.id, NOW - 7 * DAY, NOW)
    assert counts.get(agent.id, {}).get("meetings", 0) == 0
