"""Assistant/orchestrator: a fake model layer drives the real agent tool loop
against the real database — proving tools execute org-scoped and the
pending-approval contract works end to end."""
from __future__ import annotations

import pytest

from app.ai import llm as llm_mod
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from tests.conftest import auth

pytestmark = pytest.mark.asyncio


class FakeModelLayer:
    """Feeds a scripted sequence of responses to the agent loop."""

    def __init__(self, script: list[LlmResponse]):
        self.script = list(script)
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return LlmResponse(text="Done.")
        return self.script.pop(0)

    async def generate_json(self, **kwargs):
        response = await self.generate(**kwargs)
        return llm_mod.extract_json(response.text)


@pytest.fixture
def fake_model(monkeypatch):
    def _install(script: list[LlmResponse]) -> FakeModelLayer:
        fake = FakeModelLayer(script)
        monkeypatch.setattr(agent_base, "get_model_layer", lambda: fake)
        monkeypatch.setattr(
            "app.ai.orchestrator.get_model_layer", lambda: fake, raising=True
        )
        return fake

    return _install


async def test_query_agent_lists_tasks_via_tool_loop(client, org_a, fake_model):
    token = org_a["agent_token"]
    # Give the agent a task to find.
    created = await client.post(
        "/api/v1/action-items",
        headers=auth(token),
        json={"title": "Call Green Valley about demo"},
    )
    assert created.status_code == 200

    fake_model(
        [
            # Agent decides to call the tool...
            LlmResponse(tool_calls=[ToolCall(name="list_action_items",
                                             args={"owner": "me", "status": "open"})]),
            # ...then answers with the results.
            LlmResponse(text="You have 1 open task: Call Green Valley about demo."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "Show my open action items", "agent": "query"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent"] == "query"
    assert "Green Valley" in body["reply"]
    tool_action = body["actions"][0]
    assert tool_action["tool"] == "list_action_items"
    assert tool_action["ok"] is True
    assert any(
        "Call Green Valley" in item["title"] for item in tool_action["result"]
    )


async def _fresh_agent_token(client, org_a) -> str:
    """A brand-new sales agent, so `owner='me'` queries see only the items this
    test creates — the recorded tool result is previewed (truncated to a string
    past ~800 chars), so broad-result assertions need a clean owner."""
    import uuid

    email = f"a{uuid.uuid4().hex[:8]}@alpha-example.com"
    created = (
        await client.post(
            "/api/v1/admin/users",
            headers=auth(org_a["admin_token"]),
            json={"email": email, "name": "Temp Agent", "role": "sales_agent"},
        )
    ).json()
    login_resp = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": created["temp_password"]},
        )
    ).json()
    return login_resp["access_token"]


async def _make_lead(client, token: str, name: str) -> dict:
    return (
        await client.post("/api/v1/leads", headers=auth(token), json={"name": name})
    ).json()


async def _make_item(client, token: str, title: str, lead_id: str | None = None) -> dict:
    body = {"title": title}
    if lead_id:
        body["lead_id"] = lead_id
    return (
        await client.post("/api/v1/action-items", headers=auth(token), json=body)
    ).json()


async def test_context_chip_scopes_action_items_to_selected_lead(client, org_a, fake_model):
    """F17: with a lead selected (the app's context chip), 'what are the action
    items?' must answer FOR THAT LEAD, not for everything the caller owns —
    even though the model called the tool with no client of its own. The bind
    is in code, so it holds regardless of what the model chooses."""
    token = org_a["admin_token"]
    lead_a = await _make_lead(client, token, "Vidarbha Warehousing")
    lead_b = await _make_lead(client, token, "Kirloskar Industries")
    await _make_item(client, token, "Send Vidarbha the safety quote", lead_a["id"])
    await _make_item(client, token, "Call Kirloskar about the demo", lead_b["id"])

    fake_model(
        [
            # The model asks for open items WITHOUT naming a client — exactly the
            # F17 case. The chip must still scope the query.
            LlmResponse(tool_calls=[ToolCall(name="list_action_items",
                                             args={"owner": "me", "status": "open"})]),
            LlmResponse(text="Here are the action items."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "What are the action items?", "agent": "query",
              "lead_id": lead_a["id"]},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["actions"][0]["result"]
    titles = {i["title"] for i in result}
    assert titles == {"Send Vidarbha the safety quote"}, titles  # only the selected lead


async def test_context_chip_all_and_explicit_client_override_the_default(client, org_a, fake_model):
    """The deterministic default must not become a cage: 'all' broadens back to
    every client, and an explicit client the model names always wins."""
    token = await _fresh_agent_token(client, org_a)  # clean owner: exactly 2 items
    lead_a = await _make_lead(client, token, "Aurora Systems")
    lead_b = await _make_lead(client, token, "Borealis Corp")
    await _make_item(client, token, "Aurora onboarding call", lead_a["id"])
    await _make_item(client, token, "Borealis renewal", lead_b["id"])

    # 'all' escape hatch: chip on lead_a, model passes client='all' -> both.
    fake_model(
        [
            LlmResponse(tool_calls=[ToolCall(name="list_action_items",
                                             args={"status": "open", "client": "all"})]),
            LlmResponse(text="All action items."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "Show me everything across all clients", "agent": "query",
              "lead_id": lead_a["id"]},
    )
    titles = {i["title"] for i in resp.json()["actions"][0]["result"]}
    # 'all' broadens past the chip back to every client this owner has.
    assert titles == {"Aurora onboarding call", "Borealis renewal"}, titles

    # Explicit override: chip on lead_a, model names lead_b -> only lead_b.
    fake_model(
        [
            LlmResponse(tool_calls=[ToolCall(name="list_action_items",
                                             args={"status": "open", "client": "Borealis"})]),
            LlmResponse(text="Borealis items."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "What about Borealis?", "agent": "query",
              "lead_id": lead_a["id"]},
    )
    titles = {i["title"] for i in resp.json()["actions"][0]["result"]}
    assert titles == {"Borealis renewal"}, titles


async def test_query_agent_reports_task_priority(client, org_a, fake_model):
    """F19: the query agent's item view must carry `priority`, or 'tell me the
    priorities' silently degrades to 'soonest due'."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem
    from sqlalchemy import select

    token = org_a["admin_token"]
    lead = await _make_lead(client, token, "Compliance Co")
    item = await _make_item(client, token, "Escalate the compliance pack", lead["id"])
    # Nothing in the API sets priority; make it a genuine P1 in the DB.
    async with SessionLocal() as db:
        row = (await db.execute(
            select(ActionItem).where(ActionItem.id == item["id"])
        )).scalar_one()
        row.priority = "P1"
        await db.commit()

    fake_model(
        [
            LlmResponse(tool_calls=[ToolCall(name="list_action_items",
                                             args={"owner": "me", "status": "open"})]),
            LlmResponse(text="Your P1: Escalate the compliance pack."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "Tell me the priorities", "agent": "query",
              "lead_id": lead["id"]},  # scope keeps the recorded result a full list
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()["actions"][0]["result"]
    match = [i for i in result if i["id"] == item["id"]]
    assert match, result
    assert match[0]["priority"] == "P1", match[0]  # the model can now see it


async def test_conversation_agent_close_task(client, org_a, fake_model):
    token = org_a["agent_token"]
    created = (
        await client.post(
            "/api/v1/action-items",
            headers=auth(token),
            json={"title": "Send brochure to Sunrise"},
        )
    ).json()

    fake_model(
        [
            LlmResponse(tool_calls=[ToolCall(
                name="close_action_item",
                args={"task_id": created["id"],
                      "result_note": "Brochure emailed, receipt confirmed"},
            )]),
            LlmResponse(text="Done — task closed with your note."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": "Close the brochure task, receipt confirmed",
              "agent": "conversation"},
    )
    assert resp.status_code == 200
    assert resp.json()["actions"][0]["ok"] is True

    items = (
        await client.get(
            "/api/v1/action-items?status=done&owner=me", headers=auth(token)
        )
    ).json()
    match = [i for i in items if i["id"] == created["id"]]
    assert match and match[0]["result_note"] == "Brochure emailed, receipt confirmed"


async def test_agent_tools_are_org_scoped(client, org_a, org_b, fake_model):
    """Org B's agent asking about an Org A client gets 'not found' — the tool
    error goes back to the model, no data crosses the fence.

    The assertion below is on the PROPERTY (a not-found error that leaks no id),
    not on the exact wording: this test previously pinned the string "No school
    matching", which made a genericity fix (finding F11) look like a
    regression."""
    lead = (
        await client.post(
            "/api/v1/leads",
            headers=auth(org_a["admin_token"]),
            json={"name": "Secret Alpha School"},
        )
    ).json()
    fake = fake_model(
        [
            LlmResponse(tool_calls=[ToolCall(name="get_client_details",
                                             args={"client": "Secret Alpha School"})]),
            LlmResponse(text="I could not find that client."),
        ]
    )
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(org_b["admin_token"]),
        json={"text": "Tell me about Secret Alpha School", "agent": "query"},
    )
    assert resp.status_code == 200
    action = resp.json()["actions"][0]
    assert action["ok"] is False
    assert "matching" in action["error"] and "Secret Alpha School" in action["error"], \
        action["error"]
    assert lead["id"] not in str(resp.json())
    # Genericity (F11): the error a user reads must not name an industry.
    assert "school matching" not in action["error"].lower(), action["error"]


async def test_router_falls_back_to_query_on_model_failure(client, org_a, fake_model):
    class ExplodingModel:
        async def generate(self, **kwargs):
            raise RuntimeError("model down")

        async def generate_json(self, **kwargs):
            raise RuntimeError("model down")

    # Router explodes -> falls back to query agent; agent loop also explodes,
    # which surfaces as a 5xx-free handled response? No: agent.run raises.
    # The contract we verify: routing failure alone must not crash — so give
    # the router a broken model but the agent a working script.
    fake = fake_model([LlmResponse(text="Here are your results.")])

    import app.ai.orchestrator as orch
    orig = orch.get_model_layer

    calls = {"n": 0}

    def switching():
        calls["n"] += 1
        if calls["n"] == 1:
            return ExplodingModel()
        return fake

    orch.get_model_layer = switching
    try:
        resp = await client.post(
            "/api/v1/assistant/command",
            headers=auth(org_a["agent_token"]),
            json={"text": "anything at all"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent"] == "query"
    finally:
        orch.get_model_layer = orig
