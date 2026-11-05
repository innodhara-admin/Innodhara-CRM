"""Conversations the assistant holds open between turns — and the plain yes/no.

Some requests take more than one turn. Adding a client (app/ai/client_draft.py)
asks who owns it, offers the optional details, reads everything back and waits
for "create it". While such a conversation is open it is held here, in
`assistant_pending_actions`: one row per (org, user, chat session), the flow's
own state as JSON, refreshed on every turn and dropped after
ASSISTANT_CONFIRMATION_TTL_SECONDS without a reply.

The orchestrator hands each new message to the open flow first
(`flow_for(kind).handle`). The flow answers it — without the router, so a
"skip this" or a "create it" can never be sent to some other agent — or
returns None when the message is about something else. Then the flow is
paused, the message is routed as usual, and the reply offers to continue.

`classify_reply` is the model-free reader of a plain yes or no, used wherever
"yes" must mean the question on screen and nothing a model might make of it.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.context import OrgContext
from app.models.assistant import AssistantPendingAction
from app.models.base import utcnow

logger = logging.getLogger(__name__)

YES = "yes"
NO = "no"

# Understood in English, Hindi and Kannada (romanised and in script), because
# voice mode understands all three and a "yes" is the shortest thing anyone
# says. Deliberately small: a word that is not here makes the reply something
# other than a plain yes or no — the safe direction.
_AFFIRM = frozenset({
    "yes", "yeah", "yep", "yup", "ya", "yea", "sure", "ok", "okay", "okey",
    "correct", "right", "confirm", "confirmed", "proceed", "fine", "alright",
    "absolutely", "definitely", "perfect", "haan", "han", "haa", "ha",
    "haanji", "hanji", "theek", "thik", "accha", "achha", "sari", "howdu",
    "houdu", "हाँ", "हां", "हा", "हाँजी", "ठीक", "ಹೌದು", "ಸರಿ", "ಹೂಂ", "ಹೂ",
})
_DENY = frozenset({
    "no", "nope", "nah", "cancel", "stop", "dont", "don", "not", "never",
    "abort", "wrong", "incorrect", "nahi", "nahin", "mat", "beda", "illa",
    "नहीं", "नही", "ना", "मत", "ಬೇಡ", "ಇಲ್ಲ",
})
# Words that may sit beside a yes or a no without changing it: "yes please",
# "ok go ahead", "no don't create it".
_FILLER = frozenset({
    "please", "it", "that", "this", "do", "go", "ahead", "create", "add",
    "save", "make", "book", "the", "is", "all", "good", "looks", "sounds",
    "thanks", "thank", "you", "anyway", "now", "just", "then", "great", "t",
    "ji", "hai", "है", "जी", "mind", "for", "with",
    # "do it" in Kannada and Hindi, romanised as speech recognition writes it.
    # Without these, "Houdu maadi" was not a yes, and at the owner step it was
    # read as a person's name: "I couldn't find anyone called Houdu Maddi"
    # (reported 21 Sep 2026).
    "maadi", "madi", "maddi", "maado", "karo", "kar", "kardo", "kijiye",
    "banao", "bana", "de", "dedo", "ಮಾಡಿ", "करो", "कर", "बनाओ",
})
_AFFIRM_PHRASES = frozenset({
    "do it", "go ahead", "go for it", "sounds good", "looks good",
    "that is right", "thats right",
})
_SPLIT = re.compile(r"[\s.,!?;:।॥\"“”‘’()\[\]\-–—]+")
_MAX_WORDS = 6


def words(text: str | None) -> list[str]:
    """Lower-cased words, apostrophes dropped ("don't" -> "dont"), in any
    script — a split on spaces and punctuation, never on letters, so Hindi and
    Kannada vowel signs stay inside their words."""
    lowered = (text or "").lower().replace("'", "").replace("’", "")
    return [w for w in _SPLIT.split(lowered) if w]


def classify_reply(text: str) -> str | None:
    """YES, NO, or None when the reply is not a clear answer on its own."""
    found = words(text)
    if not found or len(found) > _MAX_WORDS:
        return None
    if " ".join(found) in _AFFIRM_PHRASES:
        return YES
    has_yes = any(w in _AFFIRM for w in found)
    has_no = any(w in _DENY for w in found)
    if has_yes == has_no:  # neither, or both ("yes no", "ok cancel")
        return None
    allowed = (_AFFIRM if has_yes else _DENY) | _FILLER
    if all(w in allowed for w in found):
        return YES if has_yes else NO
    return None


@dataclass
class Outcome:
    """What a flow says back, in the assistant's reply shape. `speech`, when
    set, is what voice mode says instead of the reply (a spelling is shown as
    "B-A-L" but spoken letter by letter)."""

    reply: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    speech: str | None = None
    #: Drafts waiting for the person's one-tap approval, shaped as an agent's
    #: `pending_approvals` (a proposal email drafted once the recipient
    #: question was answered). Empty for every other flow.
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)


class Flow(Protocol):
    async def handle(self, db: AsyncSession, ctx: OrgContext,
                     row: AssistantPendingAction, text: str,
                     context: dict[str, Any] | None = None) -> Outcome | None:
        """Answer the person's message, or None when it is about something else.
        `context` is the command's context (screen ids, and `_voice_confidence`
        on a spoken turn)."""

    async def pause(self, db: AsyncSession, ctx: OrgContext,
                    row: AssistantPendingAction) -> str:
        """Set the conversation aside; return the offer to continue."""


_FLOWS: dict[str, Flow] = {}


def register_flow(kind: str, flow: Flow) -> None:
    _FLOWS[kind] = flow


def flow_for(kind: str) -> Flow | None:
    return _FLOWS.get(kind)


def is_expired(row: AssistantPendingAction) -> bool:
    return row.expires_at < utcnow()


async def load(
    db: AsyncSession, ctx: OrgContext, session_id: str | None,
    *, include_expired: bool = False,
) -> AssistantPendingAction | None:
    """The conversation held open in this chat, if any. An expired one is
    dropped (or returned, with include_expired, so a late "yes" can be told
    why nothing happened). Never fatal: a failure reads as nothing held."""
    if not session_id:
        return None
    try:
        row = (
            await db.execute(
                select(AssistantPendingAction)
                .where(
                    AssistantPendingAction.org_id == ctx.org_id,
                    AssistantPendingAction.user_id == ctx.user_id,
                    AssistantPendingAction.session_id == session_id,
                )
                .order_by(AssistantPendingAction.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
    except Exception:  # noqa: BLE001 — a held conversation is an enhancement
        logger.exception("Could not read the held conversation; continuing without it")
        return None
    if row is not None and is_expired(row) and not include_expired:
        await drop(db, row)
        return None
    return row


async def save(
    db: AsyncSession,
    ctx: OrgContext,
    session_id: str,
    *,
    kind: str,
    agent: str,
    payload: dict[str, Any],
    summary: str,
    row: AssistantPendingAction | None = None,
) -> AssistantPendingAction:
    """Write the flow's state, restarting its TTL. Without `row` this starts a
    new conversation and replaces whatever this chat was holding."""
    ttl = max(int(get_settings().assistant_confirmation_ttl_seconds), 1)
    data = json.dumps(payload, default=str, ensure_ascii=False)
    expires = utcnow() + timedelta(seconds=ttl)
    if row is None:
        await clear_session(db, org_id=ctx.org_id, user_id=ctx.user_id,
                            session_id=session_id)
        row = AssistantPendingAction(
            org_id=ctx.org_id, user_id=ctx.user_id, session_id=session_id,
            kind=kind, agent=agent, payload=data, summary=summary,
            expires_at=expires,
        )
        db.add(row)
    else:
        row.kind, row.agent, row.payload = kind, agent, data
        row.summary, row.expires_at = summary, expires
    await db.flush()
    return row


async def drop(db: AsyncSession, row: AssistantPendingAction) -> None:
    await db.execute(
        delete(AssistantPendingAction).where(AssistantPendingAction.id == row.id)
    )


async def has_pending(db: AsyncSession, ctx: OrgContext, session_id: str | None) -> bool:
    """Is a live conversation held open in this chat? Looks, never changes."""
    if not session_id:
        return False
    try:
        found = (
            await db.execute(
                select(AssistantPendingAction.id).where(
                    AssistantPendingAction.org_id == ctx.org_id,
                    AssistantPendingAction.user_id == ctx.user_id,
                    AssistantPendingAction.session_id == session_id,
                    AssistantPendingAction.expires_at >= utcnow(),
                ).limit(1)
            )
        ).first()
        return found is not None
    except Exception:  # noqa: BLE001
        logger.exception("Could not check for a held conversation")
        return False


async def clear_session(
    db: AsyncSession, *, org_id: str, user_id: str, session_id: str
) -> None:
    """Drop whatever a chat is holding ("new chat" forgets it too)."""
    await db.execute(
        delete(AssistantPendingAction).where(
            AssistantPendingAction.org_id == org_id,
            AssistantPendingAction.user_id == user_id,
            AssistantPendingAction.session_id == session_id,
        )
    )
