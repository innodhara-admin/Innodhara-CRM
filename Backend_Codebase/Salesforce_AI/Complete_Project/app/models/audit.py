"""Audit log, idempotency records and LLM usage/cost tracking."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import PKMixin, utcnow


class AuditLog(Base, PKMixin):
    """Who did what, and when — per organisation (doc §13)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_org_at", "org_id", "at"),)

    org_id: Mapped[str | None] = mapped_column(String(32), index=True)  # None = platform level
    user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(32))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class IdempotencyRecord(Base, PKMixin):
    """Remembers processed request keys so retries do not duplicate work."""

    __tablename__ = "idempotency_records"
    __table_args__ = (Index("ix_idem_org_key", "org_id", "key", unique=True),)

    org_id: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(32))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class LlmUsage(Base, PKMixin):
    """Tokens and cost per model call — feeds per-org monthly budgets (§11.5)."""

    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_org_at", "org_id", "at"),)

    org_id: Mapped[str | None] = mapped_column(String(32), index=True)
    user_id: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
