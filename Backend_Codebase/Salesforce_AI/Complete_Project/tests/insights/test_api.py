"""The /insights routes (spec 9.1.2): the sales head reads them, nobody else
does, every block says how much it knows, an empty organisation gets honest
empty blocks, bad parameters are 422, other organisations' ids are 404."""
from __future__ import annotations

import pytest

from app.insights import cache
from tests.conftest import auth, create_org, login

ROLES = ("org_admin", "sales_agent", "sales_lead", "operations_agent", "operations_lead",
         "relationship_manager", "sales_head")
PLAIN_ROUTES = ("pulse", "pipeline", "outlook", "team", "clients", "meetings", "field", "ai")
NOT_BLOCKS = {"generated_at", "timezone", "method_note", "note", "accuracy_note",
              "proposal_value"}


async def _org(client, super_token, tag: str) -> dict:
    domain = f"{tag}-example.com"
    org = await create_org(client, super_token, name=f"Insights {tag}", slug=f"insights-{tag}",
                           domain=domain)
    org["tokens"], org["ids"] = {}, {}
    for role in ROLES[1:]:
        if role == "sales_head" or tag != "empty":
            made = await client.post("/api/v1/admin/users", headers=auth(org["admin_token"]),
                                     json={"email": f"{role}@{domain}", "name": role.title(),
                                           "role": role})
            assert made.status_code == 200, made.text
            session = await login(client, f"{role}@{domain}", made.json()["temp_password"])
            org["tokens"][role] = session["access_token"]
            org["ids"][role] = made.json()["id"]
    org["tokens"]["org_admin"] = org["admin_token"]
    return org


@pytest.fixture(scope="module")
async def full(client, super_token):
    org = await _org(client, super_token, "full")
    lead = await client.post("/api/v1/leads", headers=auth(org["tokens"]["sales_agent"]),
                             json={"name": "Insights Client"})
    assert lead.status_code == 200, lead.text
    org["lead_id"] = lead.json()["id"]
    return org


@pytest.fixture(scope="module")
async def empty(client, super_token):
    return await _org(client, super_token, "empty")


def _routes(org) -> list[str]:
    agent = org["ids"]["sales_agent"]
    return [f"/api/v1/insights/{r}" for r in PLAIN_ROUTES] + [
        f"/api/v1/insights/people/{agent}", f"/api/v1/insights/deals/{org['lead_id']}",
        f"/api/v1/insights/field/{agent}"]


async def test_only_sales_head_reads_insights(client, full, super_token):
    routes = _routes(full)
    assert len(routes) == 11
    for role in ROLES:
        for path in routes:
            resp = await client.get(path, headers=auth(full["tokens"][role]))
            expected = 200 if role == "sales_head" else 403
            assert resp.status_code == expected, (role, path, resp.text)
    for path in routes:
        assert (await client.get(path, headers=auth(super_token))).status_code == 403
        assert (await client.get(path)).status_code == 401


def _blocks(body: dict):
    for key, value in body.items():
        if key in NOT_BLOCKS or not isinstance(value, dict):
            continue
        yield key, value
        if key == "tiles":
            yield from ((f"tiles.{k}", v) for k, v in value.items() if isinstance(v, dict)
                        and k not in ("status", "note"))


async def test_every_block_has_status(client, full):
    head = auth(full["tokens"]["sales_head"])
    for path in _routes(full):
        body = (await client.get(path, headers=head)).json()
        assert body["generated_at"].endswith("Z") and body["timezone"] == "Asia/Kolkata"
        blocks = list(_blocks(body))
        if "/field/" in path:
            assert body["status"] in ("ok", "thin", "empty")
            continue
        assert blocks, path
        for name, block in blocks:
            assert block.get("status") in ("ok", "thin", "empty"), (path, name)


INT_FIELDS = {
    "pulse": [("pulse", "score")] + [("pulse", "parts", k) for k in
                                     ("moving", "follow_through", "client_health", "activity")]
    + [("tiles", "in_play", "value"), ("tiles", "wins", "won"), ("tiles", "wins", "expected"),
       ("tiles", "win_rate", "won"), ("tiles", "win_rate", "decided")],
    "outlook": [("summary", k) for k in ("won", "expected", "low", "high", "near_certain",
                                         "likely")] + [("lead_flow", "expected")],
    "clients": [("health", k) for k in ("healthy", "watch", "at_risk")],
    "meetings": [("summary", k) for k in ("count", "tasks_created", "plans_approved",
                                          "plans_total")],
    "field": [("trust", k) for k in ("ok", "gps_off", "timeout", "permission_denied")],
    "ai": [("health", "calls"), ("health", "failed")],
}


async def test_empty_org_every_route_is_honest(client, empty):
    head = auth(empty["tokens"]["sales_head"])
    for route in PLAIN_ROUTES:
        resp = await client.get(f"/api/v1/insights/{route}", headers=head)
        assert resp.status_code == 200, (route, resp.text)
        body = resp.json()
        for name, block in _blocks(body):
            if name == "map":
                continue            # the map style is configuration, not data
            assert block["status"] == "empty", (route, name, block)
            assert block["note"], (route, name)
        for path in INT_FIELDS.get(route, []):
            value = body
            for part in path:
                value = value[part]
            assert isinstance(value, int), (route, path, value)
    me = empty["ids"]["sales_head"]
    assert (await client.get(f"/api/v1/insights/people/{me}", headers=head)).status_code == 200


async def test_bad_params_are_422(client, full):
    head = auth(full["tokens"]["sales_head"])
    for query in ("pipeline?range=week", "team?days=8", "team?metric=bogus", "meetings?days=1",
                  "people/{agent}?days=14", "ai?month=2026-13", "ai?month=October",
                  "field?date=yesterday", "field/{agent}?date=2026-02-30"):
        path = "/api/v1/insights/" + query.format(agent=full["ids"]["sales_agent"])
        resp = await client.get(path, headers=head)
        assert resp.status_code == 422, (query, resp.status_code, resp.text)
    ok = await client.get("/api/v1/insights/team?metric=emails&days=30", headers=head)
    assert ok.status_code == 200 and ok.json()["people"]["metric"] == "emails"


async def test_other_org_ids_are_404(client, full, empty):
    head = auth(empty["tokens"]["sales_head"])
    for path in (f"/api/v1/insights/deals/{full['lead_id']}",
                 f"/api/v1/insights/people/{full['ids']['sales_agent']}",
                 f"/api/v1/insights/field/{full['ids']['sales_agent']}",
                 "/api/v1/insights/deals/not-a-lead"):
        assert (await client.get(path, headers=head)).status_code == 404, path


async def test_cache_returns_same_generated_at_within_ttl(client, full):
    head = auth(full["tokens"]["sales_head"])
    first = (await client.get("/api/v1/insights/pulse", headers=head)).json()
    second = (await client.get("/api/v1/insights/pulse", headers=head)).json()
    assert first["generated_at"] == second["generated_at"]


async def test_cache_recomputes_after_ttl():
    calls = []

    async def compute():
        calls.append(1)
        return {"n": len(calls)}

    key = ("test-org", "probe", ())
    assert (await cache.get_or_compute(key, 60, compute))["n"] == 1
    assert (await cache.get_or_compute(key, 60, compute))["n"] == 1
    assert (await cache.get_or_compute(key, 0, compute))["n"] == 2
