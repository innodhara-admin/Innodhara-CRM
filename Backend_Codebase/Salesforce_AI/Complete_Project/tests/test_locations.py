"""Field location (2 Oct 2026): sales agents and sales leads send a reading
each time they open the app; only the org admin reads them. Design:
YuvipepSalesforceAI/docs/superpowers/specs/2026-10-02-field-location-design.md
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.location import LocationPing
from app.services import location_service
from tests.conftest import auth, create_org, login

pytestmark = pytest.mark.asyncio

HERE = (12.9716, 77.5946)
NEAR = (12.9726, 77.5946)   # about 111 m north
FAR = (12.9900, 77.5946)    # about 2 km north


async def test_distance_is_in_metres():
    near = location_service.distance_m(*HERE, *NEAR)
    far = location_service.distance_m(*HERE, *FAR)
    assert 100 < near < 125, near
    assert 1950 < far < 2150, far


def _ping(status="ok", where=HERE, minutes=0, mock=False, approx=False):
    at = datetime(2030, 1, 1, 10, 0) + timedelta(minutes=minutes)
    return LocationPing(status=status, lat=where[0] if where else None,
                        lng=where[1] if where else None, is_mock=mock,
                        approximate=approx, captured_at=at)


async def test_thinning_rules():
    last = _ping()
    def keep(**kw):
        p = _ping(**kw)
        return location_service.worth_saving(
            last, status=p.status, lat=p.lat, lng=p.lng, is_mock=p.is_mock,
            approximate=p.approximate, captured_at=p.captured_at)
    assert location_service.worth_saving(
        None, status="ok", lat=1.0, lng=1.0, is_mock=False, approximate=False,
        captured_at=datetime(2030, 1, 1))
    assert not keep(where=NEAR, minutes=3)        # close and soon: nothing new
    assert keep(where=FAR, minutes=3)             # moved 2 km
    assert keep(where=NEAR, minutes=10)           # ten minutes passed
    assert keep(status="gps_off", where=None, minutes=1)   # status changed
    assert keep(where=HERE, minutes=1, mock=True)          # fake GPS appeared
    assert keep(where=HERE, minutes=1, approx=True)        # went approximate


def _when(minutes_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _reading(*, where=HERE, status="ok", minutes_ago=0.0, **extra) -> dict:
    body = {"client_ref": uuid.uuid4().hex, "status": status,
            "captured_at": _when(minutes_ago), "trigger": "open"}
    if where is not None:
        body["lat"], body["lng"] = where
        body["accuracy_m"] = 12.0
    body.update(extra)
    return body


@pytest.fixture(scope="module")
async def field_org(client, super_token) -> dict:
    """An org of its own, so other tests' people never appear here."""
    return await create_org(client, super_token, name="Field Location Org",
                            slug="field-loc", domain="fieldloc-example.com")


async def _person(client, org, role: str) -> dict:
    tag = uuid.uuid4().hex[:8]
    email = f"{role.replace('_', '.')}.{tag}@fieldloc-example.com"
    name = f"{role.title()} {tag}"
    resp = await client.post("/api/v1/admin/users", headers=auth(org["admin_token"]),
                             json={"email": email, "name": name, "role": role})
    assert resp.status_code == 200, resp.text
    made = resp.json()
    session = await login(client, email, made["temp_password"])
    return {"id": made["id"], "token": session["access_token"], "name": name}


async def _send(client, person, body) -> dict:
    resp = await client.post("/api/v1/locations/ping", headers=auth(person["token"]), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _points(client, token, user_ids, *, hours=3, roles=None):
    now = datetime.now(timezone.utc)
    params = {"from": (now - timedelta(hours=hours)).isoformat(),
              "to": (now + timedelta(minutes=10)).isoformat(),
              "user_ids": user_ids}
    if roles:
        params["roles"] = roles
    return await client.get("/api/v1/locations/points", headers=auth(token), params=params)


async def test_an_agents_reading_is_saved_with_its_flags(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    out = await _send(client, agent, _reading(is_mock=True, approximate=True))
    assert out == {"saved": True, "reason": None}
    body = (await _points(client, field_org["admin_token"], [agent["id"]])).json()
    assert len(body["points"]) == 1 and body["truncated"] is False
    point = body["points"][0]
    assert (point["status"], point["is_mock"], point["approximate"]) == ("ok", True, True)
    assert point["lat"] == pytest.approx(HERE[0]) and point["accuracy_m"] == 12.0


async def test_a_sales_lead_sends_too(client, field_org):
    lead = await _person(client, field_org, "sales_lead")
    assert (await _send(client, lead, _reading()))["saved"] is True


async def test_a_refusal_is_saved_without_a_position(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    assert (await _send(client, agent, _reading(status="permission_denied")))["saved"]
    point = (await _points(client, field_org["admin_token"], [agent["id"]])).json()["points"][0]
    assert point["status"] == "permission_denied"
    assert (point["lat"], point["lng"], point["accuracy_m"]) == (None, None, None)


async def test_other_roles_cannot_send(client, field_org):
    ops = await _person(client, field_org, "operations_agent")
    for token in (ops["token"], field_org["admin_token"]):
        resp = await client.post("/api/v1/locations/ping", headers=auth(token), json=_reading())
        assert resp.status_code == 403, resp.text


async def test_the_same_reading_is_saved_once(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    body = _reading()
    assert (await _send(client, agent, body))["saved"] is True
    assert await _send(client, agent, body) == {"saved": False, "reason": "duplicate"}


async def test_close_readings_are_thinned_and_real_changes_kept(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    assert (await _send(client, agent, _reading(minutes_ago=30)))["saved"]
    assert await _send(client, agent, _reading(where=NEAR, minutes_ago=27)) == \
        {"saved": False, "reason": "too_soon"}
    assert (await _send(client, agent, _reading(where=FAR, minutes_ago=26)))["saved"]
    assert (await _send(client, agent, _reading(status="gps_off", where=None,
                                                minutes_ago=25)))["saved"]
    assert (await _send(client, agent, _reading(status="gps_off", where=None,
                                                minutes_ago=15)))["saved"]


async def test_a_position_is_required_for_ok(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    resp = await client.post("/api/v1/locations/ping", headers=auth(agent["token"]),
                             json=_reading(where=None))
    assert resp.status_code == 422, resp.text


async def test_old_and_future_readings(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    old = await client.post("/api/v1/locations/ping", headers=auth(agent["token"]),
                            json=_reading(minutes_ago=8 * 24 * 60))
    assert old.status_code == 422, old.text
    assert (await _send(client, agent, _reading(minutes_ago=-60)))["saved"]
    point = (await _points(client, field_org["admin_token"], [agent["id"]])).json()["points"][0]
    stored = datetime.fromisoformat(point["captured_at"])
    assert stored <= datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1)


async def test_only_the_org_admin_reads(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    lead = await _person(client, field_org, "sales_lead")
    for token in (agent["token"], lead["token"]):
        latest = await client.get("/api/v1/locations/latest", headers=auth(token))
        assert latest.status_code == 403, latest.text
        assert (await _points(client, token, [agent["id"]])).status_code == 403


async def test_latest_lists_every_tracked_person(client, field_org):
    seen = await _person(client, field_org, "sales_agent")
    never = await _person(client, field_org, "sales_lead")
    ops = await _person(client, field_org, "operations_agent")
    await _send(client, seen, _reading(minutes_ago=0.5, is_mock=True))
    await _send(client, seen, _reading(status="gps_off", where=None, minutes_ago=0))
    resp = await client.get("/api/v1/locations/latest", headers=auth(field_org["admin_token"]))
    assert resp.status_code == 200, resp.text
    people = {p["user_id"]: p for p in resp.json()["people"]}
    assert seen["id"] in people and never["id"] in people
    assert ops["id"] not in people
    mine = people[seen["id"]]
    assert mine["last_status"] == "gps_off"
    assert mine["last_ok"]["lat"] == pytest.approx(HERE[0])
    assert mine["last_ok"]["is_mock"] is True
    assert mine["off_today"] == 1 and mine["fake_gps_7d"] == 1
    nobody = people[never["id"]]
    assert (nobody["last_ok"], nobody["last_seen_at"], nobody["off_today"]) == (None, None, 0)


async def test_points_filter_by_person_and_role(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    lead = await _person(client, field_org, "sales_lead")
    await _send(client, agent, _reading())
    await _send(client, lead, _reading(where=FAR))
    only_agent = (await _points(client, field_org["admin_token"], [agent["id"]])).json()
    assert {p["user_id"] for p in only_agent["points"]} == {agent["id"]}
    leads = (await _points(client, field_org["admin_token"], [agent["id"], lead["id"]],
                           roles=["sales_lead"])).json()
    assert {p["user_id"] for p in leads["points"]} == {lead["id"]}


async def test_points_window_rules(client, field_org):
    now = datetime.now(timezone.utc)
    head = auth(field_org["admin_token"])
    backwards = await client.get("/api/v1/locations/points", headers=head, params={
        "from": now.isoformat(), "to": (now - timedelta(hours=1)).isoformat()})
    assert backwards.status_code == 422, backwards.text
    too_long = await client.get("/api/v1/locations/points", headers=head, params={
        "from": (now - timedelta(days=32)).isoformat(), "to": now.isoformat()})
    assert too_long.status_code == 422, too_long.text


async def test_another_org_sees_nothing(client, field_org, org_b):
    agent = await _person(client, field_org, "sales_agent")
    await _send(client, agent, _reading())
    theirs = await client.get("/api/v1/locations/latest", headers=auth(org_b["admin_token"]))
    assert agent["id"] not in {p["user_id"] for p in theirs.json()["people"]}
    seen = (await _points(client, org_b["admin_token"], [agent["id"]])).json()
    assert seen["points"] == []


async def test_points_are_capped_keeping_the_newest(client, field_org, monkeypatch):
    agent = await _person(client, field_org, "sales_agent")
    for minutes in (50, 40, 30, 20):
        assert (await _send(client, agent, _reading(minutes_ago=minutes)))["saved"]
    monkeypatch.setattr(location_service, "MAX_POINTS", 3)
    body = (await _points(client, field_org["admin_token"], [agent["id"]])).json()
    assert body["truncated"] is True and len(body["points"]) == 3
    times = [p["captured_at"] for p in body["points"]]
    assert times == sorted(times)


async def test_config_names_the_map_styles(client, field_org):
    agent = await _person(client, field_org, "sales_agent")
    resp = await client.get("/api/v1/locations/config", headers=auth(agent["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["style_light"].startswith("https://")
    assert body["style_dark"].startswith("https://")
    assert "OpenStreetMap" in body["attribution"]


async def test_retention_sweep_drops_old_readings(client, field_org):
    from sqlalchemy import select as sql_select

    from app.database import SessionLocal
    from app.models.base import utcnow
    from app.models.user import User
    from app.services import retention_service

    agent = await _person(client, field_org, "sales_agent")
    assert (await _send(client, agent, _reading()))["saved"]
    async with SessionLocal() as db:
        user = (await db.execute(sql_select(User).where(User.id == agent["id"]))).scalar_one()
        old = utcnow() - timedelta(days=100)
        db.add(LocationPing(org_id=user.org_id, user_id=user.id, client_ref=uuid.uuid4().hex,
                            status="ok", lat=HERE[0], lng=HERE[1], captured_at=old,
                            received_at=old))
        await db.commit()
        counters = await retention_service.run_retention_sweep(db)
        await db.commit()
        assert counters["location_pings_purged"] >= 1, counters
        left = (await db.execute(sql_select(LocationPing).where(
            LocationPing.user_id == user.id))).scalars().all()
    assert len(left) == 1 and left[0].captured_at > utcnow() - timedelta(days=1)
