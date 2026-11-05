"""Client Agent — adds a NEW client (a lead) by voice or text.

The agent's only job is to notice that the person wants a new client and to
pass on what they already said. The conversation after that — who owns it,
the optional details, the read-back, "create it" — is run by the server in
`app/ai/client_draft.py`, not by this prompt: measured on the live fast model,
prompts were not enough to keep it asking the right thing in the right order.
"""
from __future__ import annotations

from typing import Any

from app.ai import client_draft
from app.ai.agents.base import AgentRuntime, BaseAgent, ToolSpec
from app.ai.agents.resolvers import resolve_lead
from app.core.constants import LeadState
from app.core.exceptions import ValidationFailedError

#: What people call the states out loud, beyond the state names themselves.
_STATE_WORDS = {
    "cold calling": LeadState.COLD_CALLING,
    "coldcalling": LeadState.COLD_CALLING,
    "pre sales": LeadState.COLD_CALLING,
    "presales": LeadState.COLD_CALLING,
    "open": LeadState.OPEN,
    "opened": LeadState.OPEN,
    "active": LeadState.ACTIVE,
    "cold": LeadState.COLD,
    "execution": LeadState.EXECUTION_IN_PROGRESS,
    "execution in progress": LeadState.EXECUTION_IN_PROGRESS,
    "client execution": LeadState.CLIENT_EXECUTION_IN_PROGRESS,
    "client execution in progress": LeadState.CLIENT_EXECUTION_IN_PROGRESS,
    "closed": LeadState.CLOSED,
    "won": LeadState.CLOSED,
    "lost": LeadState.LOST_FOR_NOW,
    "lost for now": LeadState.LOST_FOR_NOW,
}


def _state_named(said: str) -> LeadState | None:
    """The state the person meant, or None — never a guess."""
    words = " ".join((said or "").lower().replace("_", " ").replace("-", " ").split())
    if not words:
        return None
    for state in LeadState:
        if words == state.value.replace("_", " "):
            return state
    return _STATE_WORDS.get(words)


class ClientAgent(BaseAgent):
    name = "client"
    description = "Adds new clients (leads) with their owner and details."
    # Measured against openai/gpt-5.4-nano, 2026-09-15: a prompt that LISTED
    # every optional field was read as a form, and the model asked for all of
    # them instead of calling the tool. Only the name is required, and it says so.
    system_prompt = (
        "You are the Client Agent of a sales platform. You add NEW clients "
        "(leads). When the user asks to add, create or register a client, call "
        "create_client IMMEDIATELY, in this same turn, with the client's name "
        "and only the details the user actually said. `name` is the "
        "organisation's own name and nothing else: drop the words around it "
        "that merely ask for a client to be created, in whatever language "
        "they are said. \"SJBC Tumkur ge hosa lead maadi\" (Kannada) and "
        "\"SJBC Tumkur ke liye naya lead banao\" (Hindi) both name \"SJBC "
        "Tumkur\", not the whole sentence. Write the name in Latin letters: if "
        "the user wrote it in Kannada or Devanagari script, transliterate it "
        "(never translate what it means), because every client is recorded in "
        "Latin letters and is matched that way. Only the name is "
        "required; if the user gave no name, call it without one. City, "
        "source, website, notes, address, region and the contact are optional: "
        "never ask for them and never invent them. If the user said who should "
        "own it, pass their words as `owner` exactly as given, even when the "
        "name looks misspelt or garbled (it may come from speech recognition). "
        "If they mentioned a person at the client, pass contact_name, plus "
        "contact_title, contact_phone and contact_email when said. "
        "create_client never saves anything: it starts a short conversation "
        "that the platform runs by itself — the owner, the optional details and "
        "a final go-ahead. So never say a client was created, and never ask for "
        "details or a yes yourself. Use list_possible_owners when the user asks "
        "who can own a client, and find_existing_clients when they ask whether "
        "a client is already on file. When the user asks to MOVE an existing "
        "client to another state — open it, make it active, mark it cold, "
        "closed or lost — call move_client_state with the client's name and "
        "the state they asked for; never guess a state they did not name. "
        "Editing anything else about a client that already exists (its name, "
        "its owner, its details) is not something you can do; say so plainly."
    )
    #: The flow's question IS the reply (D48): the card and the prose cannot differ.
    CARD_TOOLS = frozenset({"create_client"})

    def tools(self) -> list[ToolSpec]:
        text = {"type": "string"}
        return [
            ToolSpec(
                name="create_client",
                description=(
                    "Start adding a new client (lead) with what the user said. "
                    "The platform then asks for anything still needed and creates "
                    "it only when the user says to."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "description": "the client organisation's name"},
                        "city": text,
                        "address": text,
                        "region": text,
                        "website": text,
                        "source": {"type": "string",
                                   "description": "where the lead came from, e.g. "
                                                  "an expo or a referral"},
                        "notes": text,
                        "owner": {"type": "string",
                                  "description": "the colleague who will own it "
                                                 "(name or email), only if said"},
                        "contact_name": {"type": "string",
                                         "description": "first person to talk to "
                                                        "at the client"},
                        "contact_title": text,
                        "contact_phone": text,
                        "contact_email": text,
                        "open_now": {"type": "boolean",
                                     "description": "true only if the user said to "
                                                    "open it straight away instead "
                                                    "of starting in cold calling"},
                    },
                },
                handler=self._create_client,
            ),
            ToolSpec(
                name="list_possible_owners",
                description="List the colleagues who can own a client.",
                parameters={"type": "object", "properties": {}},
                handler=self._list_owners,
            ),
            ToolSpec(
                name="move_client_state",
                description=(
                    "Move a client (lead) that already exists to another state: "
                    "cold calling, open, active, cold, execution in progress, "
                    "client execution in progress, closed or lost for now."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "client": {"type": "string",
                                   "description": "the client's name or id"},
                        "state": {"type": "string",
                                  "description": "the state to move it to, in the "
                                                 "user's words (e.g. 'open')"},
                        "reason": {"type": "string",
                                   "description": "why, if the user said"},
                    },
                    "required": ["client", "state"],
                },
                handler=self._move_state,
            ),
            ToolSpec(
                name="find_existing_clients",
                description="Check whether clients with a similar name are "
                            "already on file.",
                parameters={
                    "type": "object",
                    "properties": {"search": text},
                    "required": ["search"],
                },
                handler=self._find_clients,
            ),
        ]

    async def _create_client(self, runtime: AgentRuntime, **values: Any) -> dict[str, Any]:
        known = {"name", "city", "address", "region", "website", "source", "notes",
                 "owner", "contact_name", "contact_title", "contact_phone",
                 "contact_email", "open_now"}
        unexpected = sorted(set(values) - known)
        if unexpected:
            raise TypeError(f"unexpected argument(s): {', '.join(unexpected)}")
        raise await client_draft.start(runtime, values)

    async def _move_state(self, runtime: AgentRuntime, client: str, state: str,
                          reason: str | None = None) -> dict[str, Any]:
        """Move an existing client to another state.

        The rules are not this agent's to decide: `change_state_for_user` is
        the same function `PATCH /leads/{id}/state` calls, so who may move a
        lead, which moves are allowed, the history row and the "now open"
        announcement are identical whether a person taps or says it.
        """
        from app.services import lead_service  # noqa: PLC0415

        lead = await resolve_lead(runtime, client)
        target = _state_named(state)
        if target is None:
            named = ", ".join(s.value.replace("_", " ") for s in LeadState)
            raise ValidationFailedError(
                f"I don't know a state called \"{state}\". The states are: {named}."
            )
        was = lead.state
        moved = await lead_service.change_state_for_user(
            runtime.db, runtime.ctx, lead_id=lead.id, to_state=target.value,
            reason=reason,
        )
        return {
            "lead_id": moved.id,
            "name": moved.name,
            "from": was.replace("_", " "),
            "state": moved.state.replace("_", " "),
            "unchanged": was == moved.state,
        }

    async def _list_owners(self, runtime: AgentRuntime) -> dict[str, Any]:
        people = await client_draft.people_who_work_leads(runtime.db, runtime.ctx.org_id)
        return {
            "default_owner": "the user themself",
            "people": [
                {"name": u.name or u.email, "role": u.role.replace("_", " "),
                 "email": u.email}
                for u in people
            ],
        }

    async def _find_clients(self, runtime: AgentRuntime, search: str) -> list[dict[str, Any]]:
        term = " ".join((search or "").split())
        if not term:
            return []
        leads = (await client_draft.matching_clients(runtime.db, runtime.ctx.org_id, term))[:10]
        owners = await client_draft.names_by_id(
            runtime.db, runtime.ctx.org_id, {l.owner_id for l in leads if l.owner_id}
        )
        return [
            {"id": l.id, "name": l.name, "state": l.state.replace("_", " "),
             "city": l.city, "owner": owners.get(l.owner_id)}
            for l in leads
        ]
