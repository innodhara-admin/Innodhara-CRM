"""Conversation memory: with a session_id the assistant remembers what was
just said; without one it stays exactly as stateless as it always was.

The fake model layer records the messages it was handed, so these tests
assert on what the model actually *saw* — not merely on what was stored.
"""
from __future__ import annotations

import pytest

from app.ai import llm as llm_mod
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from tests.conftest import auth

pytestmark = pytest.mark.asyncio

SESSION = "sessionaaaaaaaaaaaaaaaaaaaaaaaa01"
OTHER_SESSION = "sessionbbbbbbbbbbbbbbbbbbbbbbbb02"


class RecordingModel:
    """Answers from a script and keeps every call for inspection."""

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

    def agent_calls(self) -> list[dict]:
        return [c for c in self.calls if str(c.get("purpose", "")).startswith("agent.")]

    def router_calls(self) -> list[dict]:
        return [c for c in self.calls if c.get("purpose") == "orchestrator.route"]


@pytest.fixture
def recording_model(monkeypatch):
    def _install(script: list[LlmResponse]) -> RecordingModel:
        model = RecordingModel(script)
        monkeypatch.setattr(agent_base, "get_model_layer", lambda: model)
        monkeypatch.setattr(
            "app.ai.orchestrator.get_model_layer", lambda: model, raising=True
        )
        return model

    return _install


async def _command(client, token, text, **extra):
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(token),
        json={"text": text, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_second_command_sees_the_first(client, org_a, recording_model):
    """The point of the whole feature: turn two knows what turn one said."""
    token = org_a["agent_token"]
    model = recording_model(
        [
            LlmResponse(text="I drafted the IBC proposal for Nexora."),
            LlmResponse(text="I warmed up the wording — pricing untouched."),
        ]
    )

    await _command(client, token, "Create the IBC proposal for Nexora",
                   session_id=SESSION, agent="proposal")
    second = await _command(client, token, "make it warmer",
                            session_id=SESSION, agent="proposal")
    assert "warmed" in second["reply"]
    assert second["session_id"] == SESSION

    messages = model.agent_calls()[-1]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "Create the IBC proposal for Nexora"
    assert "IBC proposal for Nexora" in messages[1]["content"]
    assert messages[-1]["content"] == "make it warmer"
    # And the agent is told these are earlier turns of one conversation.
    assert "ongoing conversation" in model.agent_calls()[-1]["system"]


async def test_history_is_plain_text_only(client, org_a, recording_model):
    """Tool calls and their results stay inside the request that made them —
    replaying an unpaired tool_result is rejected by the model providers."""
    token = org_a["agent_token"]
    model = recording_model(
        [
            LlmResponse(tool_calls=[ToolCall(name="list_action_items",
                                             args={"owner": "me"}, call_id="c1")]),
            LlmResponse(text="You have no open tasks."),
            LlmResponse(text="Nothing new since then."),
        ]
    )
    await _command(client, token, "what am I doing today",
                   session_id=OTHER_SESSION, agent="query")
    await _command(client, token, "anything else",
                   session_id=OTHER_SESSION, agent="query")

    messages = model.agent_calls()[-1]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert all("tool_calls" not in m for m in messages)
    assert not any(m["role"] == "tool_result" for m in messages)


async def test_router_sees_the_conversation(client, org_a, recording_model):
    """"send it" routes on what "it" was, so the router gets the tail too."""
    token = org_a["agent_token"]
    model = recording_model(
        [
            LlmResponse(text='{"agent": "proposal", "reason": "proposal work"}'),
            LlmResponse(text="Drafted the proposal."),
            LlmResponse(text='{"agent": "proposal", "reason": "same proposal"}'),
            LlmResponse(text="Sent for approval."),
        ]
    )
    session = "routerhistorysession0000000000aa"
    await _command(client, token, "draft a proposal for Nexora", session_id=session)
    await _command(client, token, "send it", session_id=session)

    router_prompt = model.router_calls()[-1]["messages"][0]["content"]
    assert "draft a proposal for Nexora" in router_prompt
    assert "Drafted the proposal." in router_prompt
    assert 'Request: "send it"' in router_prompt


async def test_no_session_id_records_nothing(client, org_a, recording_model):
    """Back-compatible: a command without a session is stateless, as before."""
    token = org_a["agent_token"]
    model = recording_model(
        [LlmResponse(text="First."), LlmResponse(text="Second.")]
    )
    await _command(client, token, "one", agent="query")
    await _command(client, token, "two", agent="query")

    messages = model.agent_calls()[-1]["messages"]
    assert messages == [{"role": "user", "content": "two"}]
    assert "ongoing conversation" not in model.agent_calls()[-1]["system"]

    # ...and nothing was written, so no session can accidentally pick it up.
    listed = await client.get(
        "/api/v1/assistant/history?session_id=neverusedsession00000000000000aa",
        headers=auth(token),
    )
    assert listed.status_code == 200
    assert listed.json() == []


async def test_history_endpoint_replays_the_transcript(client, org_a, recording_model):
    token = org_a["agent_token"]
    recording_model([LlmResponse(text="Here you go.")])
    session = "replaysession000000000000000000aa"
    await _command(client, token, "show my tasks", session_id=session, agent="query")

    turns = (
        await client.get(
            f"/api/v1/assistant/history?session_id={session}", headers=auth(token)
        )
    ).json()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"] == "show my tasks"
    assert turns[1]["content"] == "Here you go."
    assert turns[1]["agent"] == "query"


async def test_a_conversation_is_private_to_its_owner(client, org_a, recording_model):
    """Same session id, different person: nothing crosses. (org_a's admin and
    agent share an organisation — the fence here is the user, not just the
    org.)"""
    token = org_a["agent_token"]
    recording_model([LlmResponse(text="Only the agent should see this.")])
    session = "privatesession00000000000000000aa"
    await _command(client, token, "a private question", session_id=session,
                   agent="query")

    other = (
        await client.get(
            f"/api/v1/assistant/history?session_id={session}",
            headers=auth(org_a["admin_token"]),
        )
    ).json()
    assert other == []


async def test_clear_history_forgets_the_conversation(client, org_a, recording_model):
    token = org_a["agent_token"]
    recording_model([LlmResponse(text="Noted."), LlmResponse(text="Fresh start.")])
    session = "clearsession0000000000000000000aa"
    await _command(client, token, "remember this", session_id=session, agent="query")

    cleared = await client.request(
        "DELETE",
        f"/api/v1/assistant/history?session_id={session}",
        headers=auth(token),
    )
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] == 2

    turns = (
        await client.get(
            f"/api/v1/assistant/history?session_id={session}", headers=auth(token)
        )
    ).json()
    assert turns == []


async def test_a_long_conversation_stays_bounded(client, org_a, recording_model):
    """A chat that runs all day must not grow without limit — old turns are
    pruned, and what survives is still a usable, alternating transcript."""
    from app.config import get_settings

    token = org_a["agent_token"]
    keep = get_settings().assistant_session_max_turns
    commands = keep  # two turns each, so ~half of them get pruned away
    recording_model([LlmResponse(text=f"Reply {i}.") for i in range(commands)])
    session = "longsession00000000000000000000a"
    for i in range(commands):
        await _command(client, token, f"command {i}", session_id=session,
                       agent="query")

    turns = (
        await client.get(
            f"/api/v1/assistant/history?session_id={session}&limit=200",
            headers=auth(token),
        )
    ).json()
    assert len(turns) == keep, f"kept {len(turns)}, expected {keep}"
    # The survivors are the NEWEST turns, still in order and still alternating.
    assert turns[-1]["content"] == f"Reply {commands - 1}."
    assert turns[-2]["content"] == f"command {commands - 1}"
    assert [t["role"] for t in turns] == ["user", "assistant"] * (keep // 2)


async def test_retention_sweep_drops_old_conversations(client, org_a, recording_model):
    """The nightly sweep ages conversations out — and the rest of the sweep
    (audio deletion, transcript archiving) must keep working alongside it."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models.assistant import AssistantTurn
    from app.models.base import utcnow
    from app.services import retention_service

    token = org_a["agent_token"]
    recording_model([LlmResponse(text="Old."), LlmResponse(text="Recent.")])
    stale, fresh = "staleconv0000000000000000000000a", "freshconv0000000000000000000000a"
    await _command(client, token, "long ago", session_id=stale, agent="query")
    await _command(client, token, "just now", session_id=fresh, agent="query")

    # Backdate one conversation past the window.
    cutoff_days = get_settings().assistant_history_retention_days
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(AssistantTurn).where(AssistantTurn.session_id == stale)
            )
        ).scalars().all()
        assert len(rows) == 2
        for row in rows:
            row.created_at = utcnow() - timedelta(days=cutoff_days + 1)
        await db.commit()

        counters = await retention_service.run_retention_sweep(db)
        await db.commit()

    assert counters["assistant_turns_purged"] == 2, counters
    assert "audio_deleted" in counters and "transcripts_archived" in counters

    gone = (
        await client.get(f"/api/v1/assistant/history?session_id={stale}",
                         headers=auth(token))
    ).json()
    kept = (
        await client.get(f"/api/v1/assistant/history?session_id={fresh}",
                         headers=auth(token))
    ).json()
    assert gone == []
    assert len(kept) == 2, "a recent conversation must survive the sweep"


async def test_malformed_session_id_is_rejected(client, org_a):
    resp = await client.post(
        "/api/v1/assistant/command",
        headers=auth(org_a["agent_token"]),
        json={"text": "hello", "session_id": "../../etc/passwd"},
    )
    assert resp.status_code == 422


async def test_erasing_a_contact_scrubs_them_from_conversations(
    client, org_a, recording_model
):
    """Right-to-be-removed has to reach the chat buffer too — it is free text
    people typed a person's name into (services/retention_service.py)."""
    admin = org_a["admin_token"]
    contact_lead = (
        await client.post(
            "/api/v1/leads", headers=auth(admin), json={"name": "Erasure Test School"}
        )
    ).json()
    contact = (
        await client.post(
            f"/api/v1/leads/{contact_lead['id']}/contacts",
            headers=auth(admin),
            json={"name": "Priya Erasable", "email": "priya@erasable-example.com"},
        )
    ).json()

    recording_model([LlmResponse(text="Drafted a note for Priya Erasable.")])
    session = "erasuresession00000000000000000a"
    await _command(client, admin, "write to Priya Erasable please",
                   session_id=session, agent="email")
    assert len(
        (await client.get(f"/api/v1/assistant/history?session_id={session}",
                          headers=auth(admin))).json()
    ) == 2

    erased = await client.post(
        "/api/v1/privacy/erase-contact",
        headers=auth(admin),
        json={"contact_id": contact["id"]},
    )
    assert erased.status_code == 200, erased.text
    assert erased.json()["assistant_turns_deleted"] == 2

    left = (
        await client.get(
            f"/api/v1/assistant/history?session_id={session}", headers=auth(admin)
        )
    ).json()
    assert left == []


async def test_a_broken_history_write_does_not_lose_the_work(
    client, org_a, recording_model, monkeypatch
):
    """Conversation memory is an enhancement: if it fails, the command that
    the user actually asked for still succeeds."""
    token = org_a["agent_token"]
    recording_model([LlmResponse(text="The work still happened.")])

    from app.ai import conversation as conv

    def _explode(*_args, **_kwargs):
        raise RuntimeError("transcript store unavailable")

    monkeypatch.setattr(conv, "load_turns", _explode)

    body = await _command(client, token, "do the thing",
                          session_id="brokensession000000000000000aa1",
                          agent="query")
    assert body["reply"] == "The work still happened."
