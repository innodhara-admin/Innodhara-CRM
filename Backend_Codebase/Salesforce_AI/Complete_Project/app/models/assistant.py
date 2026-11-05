"""The assistant's conversation transcript — what was said, turn by turn.

Kept server-side rather than in the app so a conversation survives an app
restart, follows the user to a second device, and lives inside the same
organisation fence and audit story as every other row.

Rows hold **plain text only**. A turn never stores tool calls, tool results
or entity ids: those belong to the request that produced them (doc §6), and
replaying an id from yesterday would let the model act on a record whose
permissions may since have changed. The model gets what was *said*; it calls
tools again — org-scoped, freshly authorised — for anything it needs to do.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class AssistantTurn(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "assistant_turns"
    __table_args__ = (
        Index(
            "ix_assistant_turns_session",
            "org_id", "user_id", "session_id", "seq",
        ),
    )

    # Conversation id minted by the client (one per chat thread on the device).
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, index=True
    )
    # Position in the conversation. created_at alone is not enough: the two
    # turns of one exchange are written in the same instant, so a timestamp
    # sort could put the reply before the question.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Which specialist answered (null on user turns) — shown as the app's
    # "answered by …" meta line and useful when reading a transcript back.
    agent: Mapped[str | None] = mapped_column(String(30))


class AssistantPendingAction(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """A write the assistant has read back and is waiting on a "yes" for.

    The assistant never creates a record from one sentence: it reads the
    details back and stops. What it read back is held here, exactly, so the
    person's "yes" carries out THAT and nothing else — not whatever the model
    would make of "yes" on a second pass, and not an older question further up
    the chat (the D46/D50 lesson: an agreement reaches only the question on
    screen).

    One row per conversation at most, and short-lived: a new request, a "no",
    or the TTL (ASSISTANT_CONFIRMATION_TTL_SECONDS) all discard it. Unlike
    `assistant_turns` this row does carry resolved ids (the chosen owner), and
    that is safe for the same reason the transcript rule exists: every id is
    re-checked against the organisation and the person's role at the moment
    the "yes" arrives.
    """

    __tablename__ = "assistant_pending_actions"
    __table_args__ = (
        Index(
            "ix_assistant_pending_actions_session",
            "org_id", "user_id", "session_id",
        ),
    )

    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), nullable=False, index=True
    )
    # Which write this is ("create_client") — the key of the executor that
    # carries it out.
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # The agent that proposed it, so the confirmed turn is recorded against it.
    agent: Mapped[str] = mapped_column(String(30), nullable=False)
    # The exact values that were read back, as JSON.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    # The read-back sentence itself.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
