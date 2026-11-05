"""The demo organisation for the sales head's screens (spec 11): it fills
every screen, shows every alert and every flag, can be run again without
adding anything, and touches no other organisation."""
from __future__ import annotations

import importlib.util
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, or_, select

from app.core import clock
from app.database import Base
from app.insights import (ai_usage, clients, deal, field, meetings, outlook, person,
                          pipeline, pulse, team)
from app.models.lead import Lead
from app.models.organisation import Organisation
from app.models.user import User
from tests.insights.builders import make_lead, make_org, make_user

NOW = datetime(2026, 10, 22, 6, 0)          # Thursday 22 Oct, 11:30 in Kolkata
TODAY = date(2026, 10, 22)
TZ = clock.zone("Asia/Kolkata")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_sales_head_demo.py"
ALERT_KINDS = {"deal_quiet", "proposal_unanswered", "negative_reply", "promise_broken",
               "over_capacity", "overdue_tasks", "location_refused"}
FLAG_KINDS = {"moved_without_activity", "task_burst", "followup_nothing_sent", "location",
              "silent_working_day"}
#: Blocks that are allowed to be empty in a seeded demo org: the Prospect
#: Finder is not ported yet, and tests never ask OpenRouter for a balance.
MAY_BE_EMPTY = {"prospect", "balance"}


def _load():
    spec = importlib.util.spec_from_file_location("seed_sales_head_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seed(db, name):
    return await _load().seed(db, org_name=name, today=TODAY, now=NOW)


def _blocks(body):
    for key, value in body.items():
        if isinstance(value, dict) and "status" in value:
            yield key, value


async def _people(db, org_id):
    return {u.name: u for u in (await db.execute(
        select(User).where(User.org_id == org_id))).scalars().all()}


async def test_seed_fills_every_screen(db):
    summary = await _seed(db, "Seed Screens (demo)")
    org_id = summary["org_id"]
    assert len(summary["logins"]) == 7
    assert {l["role"] for l in summary["logins"]} == {
        "sales_head", "sales_lead", "sales_agent", "relationship_manager"}
    people = await _people(db, org_id)
    agent = people[summary["poor_performer"]]
    lead_id = summary["showcase_lead_id"]
    screens = {
        "pulse": await pulse.build(db, org_id, TZ, NOW),
        "pipeline": await pipeline.build(db, org_id, TZ, NOW, range="quarter"),
        "outlook": await outlook.build(db, org_id, TZ, NOW),
        "team": await team.build(db, org_id, TZ, NOW, metric="meetings", days=7),
        "person": await person.build(db, org_id, TZ, NOW, user_id=agent.id, days=7),
        "clients": await clients.build(db, org_id, TZ, NOW),
        "deal": await deal.build(db, org_id, TZ, NOW, lead_id=lead_id),
        "meetings": await meetings.build(db, org_id, TZ, NOW, days=7),
        "field": await field.build(db, org_id, TZ, NOW, day=TODAY),
        "ai": await ai_usage.build(db, org_id, TZ, NOW, month="2026-10"),
    }
    for screen, body in screens.items():
        for name, block in _blocks(body):
            if name in MAY_BE_EMPTY:
                continue
            assert block["status"] != "empty", (screen, name, block.get("note"))
    trail = await field.person(db, org_id, TZ, NOW, user_id=people["Asha Iyer"].id, day=TODAY)
    assert trail["status"] == "ok" and len(trail["trail"]) >= 2
    leads = (await db.execute(select(func.count()).select_from(Lead)
                              .where(Lead.org_id == org_id))).scalar_one()
    assert 100 <= leads <= 140


async def test_seed_triggers_every_alert_and_flag(db):
    summary = await _seed(db, "Seed Alerts (demo)")
    org_id = summary["org_id"]
    assert {a["kind"] for a in await pulse.alerts(db, org_id, TZ, NOW)} == ALERT_KINDS
    people = await _people(db, org_id)
    poor = people[summary["poor_performer"]]
    assert {f["kind"] for f in await person.flags(db, org_id, TZ, NOW, poor.id, 7)} == FLAG_KINDS


async def _counts(db, org_id=None, other_than=None):
    out = {}
    for name, table in Base.metadata.tables.items():
        if "org_id" not in table.columns:
            continue
        query = select(func.count()).select_from(table)
        if org_id is not None:
            query = query.where(table.c.org_id == org_id)
        if other_than is not None:
            query = query.where(or_(table.c.org_id != other_than, table.c.org_id.is_(None)))
        out[name] = (await db.execute(query)).scalar_one()
    return out


async def test_seed_is_idempotent(db):
    module = _load()
    first = await module.seed(db, org_name="Seed Twice (demo)", today=TODAY, now=NOW)
    before = await _counts(db, org_id=first["org_id"])
    with pytest.raises(module.AlreadySeeded):
        await module.seed(db, org_name="Seed Twice (demo)", today=TODAY, now=NOW)
    again = await module.seed(db, org_name="Seed Twice (demo)", today=TODAY, now=NOW,
                              again=True)
    assert again["org_id"] == first["org_id"]
    assert await _counts(db, org_id=first["org_id"]) == before
    orgs = (await db.execute(select(func.count()).select_from(Organisation)
                             .where(Organisation.name == "Seed Twice (demo)"))).scalar_one()
    assert orgs == 1


async def test_seed_touches_only_its_org(db):
    other = await make_org(db, name="Bystander Org")
    someone = await make_user(db, other, name="Bystander", role="sales_agent")
    await make_lead(db, other, name="Bystander Client", state="open", owner=someone,
                    created_at=NOW)
    before = await _counts(db)
    summary = await _seed(db, "Seed Fence (demo)")
    after_others = await _counts(db, other_than=summary["org_id"])
    assert after_others == before


@pytest.mark.parametrize("now", [
    datetime(2026, 10, 19, 5, 0),       # Monday morning
    datetime(2026, 10, 24, 9, 0),       # Saturday
    datetime(2026, 10, 25, 6, 0),       # Sunday, not a working day
    datetime(2026, 10, 27, 15, 0),      # Tuesday evening
])
async def test_seed_shows_everything_whatever_the_day(db, now):
    today = clock.local_date(now, TZ)
    module = _load()
    summary = await module.seed(db, org_name=f"Seed {now:%a} (demo)", today=today, now=now)
    org_id = summary["org_id"]
    assert {a["kind"] for a in await pulse.alerts(db, org_id, TZ, now)} == ALERT_KINDS
    people = await _people(db, org_id)
    poor = people[summary["poor_performer"]]
    assert {f["kind"] for f in await person.flags(db, org_id, TZ, now, poor.id, 7)} == FLAG_KINDS
    for screen, body in (("pulse", await pulse.build(db, org_id, TZ, now)),
                         ("meetings", await meetings.build(db, org_id, TZ, now, days=7)),
                         ("field", await field.build(db, org_id, TZ, now, day=today))):
        for name, block in _blocks(body):
            assert block["status"] != "empty", (screen, name, block.get("note"))
