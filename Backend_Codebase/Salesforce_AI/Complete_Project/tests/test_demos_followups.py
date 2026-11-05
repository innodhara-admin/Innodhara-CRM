"""Demos (calendar view, clash warning) and follow-ups (auto next reminder)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def demo_setup(client, org_a):
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Demo Calendar School"})
    ).json()
    team = (
        await client.post(
            "/api/v1/admin/demo-teams",
            headers=auth(token),
            json={"name": "Team Gamma", "member_ids": []},
        )
    ).json()
    return {"token": token, "lead": lead, "team": team}


async def test_schedule_and_calendar_view(client, demo_setup):
    token = demo_setup["token"]
    demo_date = date.today() + timedelta(days=200)  # own empty month
    resp = await client.post(
        "/api/v1/demos",
        headers=auth(token),
        json={"lead_id": demo_setup["lead"]["id"],
              "scheduled_date": demo_date.isoformat(),
              "scheduled_time": "10:00",
              "team_id": demo_setup["team"]["id"]},
    )
    assert resp.status_code == 200, resp.text

    cal = (
        await client.get(
            f"/api/v1/demos/calendar?year={demo_date.year}&month={demo_date.month}",
            headers=auth(token),
        )
    ).json()
    assert cal["total_demos"] >= 1
    assert demo_date.isoformat() in cal["days"]
    assert cal["days"][demo_date.isoformat()][0]["school"] == "Demo Calendar School"
    assert demo_date.isoformat() not in cal["free_days"]
    assert len(cal["days"]) == cal["days_in_month"]  # full-month grid (≤31)


async def test_same_team_same_day_warns(client, demo_setup):
    token = demo_setup["token"]
    demo_date = (date.today() + timedelta(days=200)).isoformat()
    resp = await client.post(
        "/api/v1/demos",
        headers=auth(token),
        json={"lead_id": demo_setup["lead"]["id"],
              "scheduled_date": demo_date,
              "team_id": demo_setup["team"]["id"]},
    )
    assert resp.status_code == 200
    assert "warning" in resp.json()


async def test_followup_complete_schedules_next(client, org_a):
    token = org_a["admin_token"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Followup School"})
    ).json()
    followup = (
        await client.post(
            "/api/v1/followups",
            headers=auth(token),
            json={"lead_id": lead["id"], "due_date": date.today().isoformat(),
                  "channel": "whatsapp", "note": "check in"},
        )
    ).json()

    due = (
        await client.get("/api/v1/followups?due=today", headers=auth(token))
    ).json()
    assert any(f["id"] == followup["id"] for f in due)

    resp = await client.post(
        f"/api/v1/followups/{followup['id']}/complete",
        headers=auth(token),
        json={"note": "Sent WhatsApp", "schedule_next": True},
    )
    body = resp.json()
    assert body["completed"] is True
    expected_next = (date.today() + timedelta(days=7)).isoformat()
    assert body["next_followup_due"] == expected_next  # default cadence 7 days
