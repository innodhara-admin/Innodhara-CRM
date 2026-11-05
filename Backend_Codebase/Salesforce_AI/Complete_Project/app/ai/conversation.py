"""Conversation memory for the assistant — the previous turns of *this* chat,
loaded before a command runs and appended after it finishes.

This is not `ai/memory.py`. That one is the organisation's long-term notebook
(embeddings over meetings and notes, searched by meaning). This one is short
and literal: the last few things this person and the assistant actually said
to each other, so "make it warmer", "send that to her" and "the second one"
mean something.

Four fences, all deliberate:

* **Plain text only.** Tool calls and tool results are never replayed. They
  are provider-specific *paired* structures — a tool_result whose tool_call
  is missing is rejected outright by the OpenAI-shaped and Anthropic APIs —
  and they would multiply the token bill of every follow-up. Entity ids stay
  out too: the model re-resolves things by name through tools, so every
  access is freshly org-scoped and permission-checked (models/assistant.py).
* **Scoped to (org, user, session).** A conversation belongs to one person in
  one organisation; nothing else can ever be loaded into it.
* **Strictly alternating, starting with the user.** Both providers require
  it, and a tail-slice of rows can easily begin mid-exchange.
* **Never fatal.** A failed read or write is logged and skipped — the command
  still runs, just without memory. Same rule as `ai/memory.py`: conversation
  memory is an enhancement, not a dependency.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import Message
from app.config import get_settings
from app.models.assistant import AssistantTurn

logger = logging.getLogger(__name__)

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"


async def load_turns(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str,
    limit: int | None = None,
) -> list[AssistantTurn]:
    """The most recent `limit` turns of one conversation, oldest first."""
    settings = get_settings()
    take = limit if limit is not None else settings.assistant_history_turns
    if take <= 0:
        return []
    rows = (
        await db.execute(
            select(AssistantTurn)
            .where(
                AssistantTurn.org_id == org_id,
                AssistantTurn.user_id == user_id,
                AssistantTurn.session_id == session_id,
            )
            .order_by(AssistantTurn.seq.desc())
            .limit(take)
        )
    ).scalars().all()
    return list(reversed(rows))


def to_messages(turns: list[AssistantTurn]) -> list[Message]:
    """Turn rows into the model layer's neutral message format, applying the
    character budget (newest turns win) and the alternation rules."""
    budget = get_settings().assistant_history_char_budget
    kept: list[AssistantTurn] = []
    spent = 0
    for turn in reversed(turns):  # newest first — drop the oldest when full
        cost = len(turn.content or "")
        if kept and spent + cost > budget:
            break
        kept.append(turn)
        spent += cost
    kept.reverse()

    messages: list[Message] = []
    for turn in kept:
        role = ROLE_ASSISTANT if turn.role == ROLE_ASSISTANT else ROLE_USER
        content = (turn.content or "").strip()
        if not content:
            continue
        if messages and messages[-1]["role"] == role:
            # Two turns of the same role in a row (a reply that never got
            # saved because the model was down). Merge instead of dropping —
            # both providers require alternation, and the words still matter.
            messages[-1]["content"] += "\n" + content
        else:
            messages.append({"role": role, "content": content})
    # A conversation the model sees must open with the user.
    while messages and messages[0]["role"] != ROLE_USER:
        messages.pop(0)
    return messages


async def load_history(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str | None,
) -> list[Message]:
    """Previous turns as model messages. Empty list when there is no session,
    no history, or anything at all goes wrong."""
    if not session_id:
        return []
    try:
        return to_messages(
            await load_turns(
                db, org_id=org_id, user_id=user_id, session_id=session_id
            )
        )
    except Exception:  # noqa: BLE001 — memory must never break a command
        logger.exception("Assistant history load failed; continuing without it")
        return []


async def save_exchange(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str | None,
    user_text: str,
    reply: str,
    agent: str | None = None,
) -> None:
    """Append this command and its reply to the conversation.

    Rides the caller's session — the turns commit atomically with everything
    the agent's tools did, and a second session would deadlock against
    SQLite's single write lock (the JobQueue lesson, see database.py)."""
    if not session_id:
        return
    try:
        settings = get_settings()
        last_seq = (
            await db.execute(
                select(func.coalesce(func.max(AssistantTurn.seq), 0)).where(
                    AssistantTurn.org_id == org_id,
                    AssistantTurn.user_id == user_id,
                    AssistantTurn.session_id == session_id,
                )
            )
        ).scalar_one()
        db.add(
            AssistantTurn(
                org_id=org_id, user_id=user_id, session_id=session_id,
                seq=last_seq + 1, role=ROLE_USER, content=user_text[:8000],
            )
        )
        db.add(
            AssistantTurn(
                org_id=org_id, user_id=user_id, session_id=session_id,
                seq=last_seq + 2, role=ROLE_ASSISTANT,
                content=(reply or "")[:8000], agent=agent,
            )
        )
        await db.flush()
        await _prune(
            db, org_id=org_id, user_id=user_id, session_id=session_id,
            keep=settings.assistant_session_max_turns, newest_seq=last_seq + 2,
        )
    except Exception:  # noqa: BLE001 — a lost transcript must not lose the work
        logger.exception("Assistant history save failed; the command still ran")


async def _prune(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    session_id: str,
    keep: int,
    newest_seq: int,
) -> None:
    """Keep a conversation bounded: drop turns older than the last `keep`."""
    if keep <= 0 or newest_seq <= keep:
        return
    await db.execute(
        delete(AssistantTurn).where(
            AssistantTurn.org_id == org_id,
            AssistantTurn.user_id == user_id,
            AssistantTurn.session_id == session_id,
            AssistantTurn.seq <= newest_seq - keep,
        )
    )


def _one_line(text: str | None, limit: int) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


async def list_sessions(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    limit: int = 50,
) -> list[dict]:
    """This person's own conversations, the most recently used first: the
    app's chat-history sidebar (2 Oct 2026). Read only.

    The title is the first thing the person said in the chat (of the turns
    still kept: a long chat is pruned to its last turns), the preview is the
    last thing said by either side. Scoped to (org, user) like every other
    read of the transcript; nobody can list another person's chats."""
    if limit <= 0:
        return []
    last_at = func.max(AssistantTurn.created_at)
    latest = (
        await db.execute(
            select(AssistantTurn.session_id, last_at, func.count())
            .where(
                AssistantTurn.org_id == org_id,
                AssistantTurn.user_id == user_id,
            )
            .group_by(AssistantTurn.session_id)
            .order_by(last_at.desc(), AssistantTurn.session_id)
            .limit(limit)
        )
    ).all()
    if not latest:
        return []
    ids = [row[0] for row in latest]
    first_said: dict[str, str] = {}
    last_said: dict[str, str] = {}
    for session_id, role, content in (
        await db.execute(
            select(AssistantTurn.session_id, AssistantTurn.role, AssistantTurn.content)
            .where(
                AssistantTurn.org_id == org_id,
                AssistantTurn.user_id == user_id,
                AssistantTurn.session_id.in_(ids),
            )
            .order_by(AssistantTurn.session_id, AssistantTurn.seq)
        )
    ).all():
        if not (content or "").strip():
            continue
        if role == ROLE_USER and session_id not in first_said:
            first_said[session_id] = content
        last_said[session_id] = content
    return [
        {
            "session_id": session_id,
            "title": _one_line(first_said.get(session_id) or last_said.get(session_id), 80),
            "preview": _one_line(last_said.get(session_id), 140),
            "last_at": when,
            "turns": count,
        }
        for session_id, when, count in latest
    ]


async def clear_session(
    db: AsyncSession, *, org_id: str, user_id: str, session_id: str
) -> int:
    """Forget one conversation. Returns how many turns were removed.

    A write still waiting on a "yes" in it is forgotten too: a new chat must
    not be able to agree to something asked in the old one."""
    from app.ai import confirmations  # noqa: PLC0415 — confirmations imports models only

    await confirmations.clear_session(
        db, org_id=org_id, user_id=user_id, session_id=session_id
    )
    result = await db.execute(
        delete(AssistantTurn).where(
            AssistantTurn.org_id == org_id,
            AssistantTurn.user_id == user_id,
            AssistantTurn.session_id == session_id,
        )
    )
    return result.rowcount or 0
