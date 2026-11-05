"""The assistant endpoint — voice/text commands go here and the Orchestrator
routes them to the right AI agent (doc §6, Figure 4).

Examples the mobile app sends verbatim:
  "Show my open action items"
  "Move task 2 to Siva"
  "Create the IBC proposal, make it 16 workshops at Rs 1500, and send it to
   the Principal with the Owner in CC"
  "Write a WhatsApp follow-up for Green Valley"
  "Add a note — school prefers Hindi-medium workshops"

Send a `session_id` (any stable id the client mints, one per chat thread) and
the calls become a *conversation*: the assistant sees the previous turns, so
"make it warmer" and "send that to her" work. Leave it out and the endpoint
behaves exactly as it always did — stateless, nothing recorded.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import conversation, orchestrator
from app.api.deps import get_org_context
from app.core.context import OrgContext
from app.database import get_db

router = APIRouter(prefix="/assistant", tags=["assistant"])

# The session id is client-minted, so it is bounded and charset-checked before
# it ever reaches a query. A UUID hex — what the app sends — satisfies it.
_SESSION_RULES = {"min_length": 8, "max_length": 64, "pattern": r"^[A-Za-z0-9_-]+$"}


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # Conversation this command belongs to. Omit for a one-off command.
    session_id: str | None = Field(default=None, **_SESSION_RULES)
    # Optional app context: which screen/entity the user is looking at.
    lead_id: str | None = None
    proposal_id: str | None = None
    meeting_id: str | None = None
    # Force a specific agent (mostly for testing); normally the router decides.
    agent: str | None = None


class CommandResponse(BaseModel):
    agent: str
    reply: str
    actions: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]]
    # Echoed back so the client can confirm which conversation it landed in.
    session_id: str | None = None


class TurnOut(BaseModel):
    role: str  # user | assistant
    content: str
    agent: str | None = None
    at: datetime


@router.post("/command", response_model=CommandResponse)
async def command(
    body: CommandRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    context: dict[str, Any] = {}
    if body.lead_id:
        context["lead_id"] = body.lead_id
    if body.proposal_id:
        context["proposal_id"] = body.proposal_id
    if body.meeting_id:
        context["meeting_id"] = body.meeting_id

    result = await orchestrator.handle_command(
        db, ctx, body.text, context=context, force_agent=body.agent,
        session_id=body.session_id,
    )
    await db.commit()  # persist everything the agent's tools did, and the turns
    return CommandResponse(
        agent=result.agent,
        reply=result.reply,
        actions=result.actions,
        pending_approvals=result.pending_approvals,
        session_id=body.session_id,
    )


@router.get("/history", response_model=list[TurnOut])
async def history(
    session_id: str = Query(**_SESSION_RULES),
    limit: int = Query(default=50, ge=1, le=200),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Replay a conversation, oldest first — so a reopened app shows the chat
    the user left, not an empty screen. A conversation is private to the
    person who had it: only the caller's own turns are ever returned."""
    turns = await conversation.load_turns(
        db, org_id=ctx.org_id, user_id=ctx.user_id, session_id=session_id,
        limit=limit,
    )
    return [
        TurnOut(role=t.role, content=t.content, agent=t.agent, at=t.created_at)
        for t in turns
    ]


class SessionOut(BaseModel):
    session_id: str
    title: str
    preview: str
    last_at: datetime
    turns: int


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(
    limit: int = Query(default=50, ge=1, le=100),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own conversations, most recently used first — the app's
    chat-history sidebar (2 Oct 2026). Open one with GET /history."""
    return await conversation.list_sessions(
        db, org_id=ctx.org_id, user_id=ctx.user_id, limit=limit,
    )


@router.delete("/history")
async def clear_history(
    session_id: str = Query(**_SESSION_RULES),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Forget a conversation — 'new chat' that actually forgets."""
    removed = await conversation.clear_session(
        db, org_id=ctx.org_id, user_id=ctx.user_id, session_id=session_id
    )
    await db.commit()
    return {"cleared": removed}
