"""Per-organisation memory store (RAG).

Embeddings are stored as JSON float arrays with cosine search in Python —
correct and fast at current scale. The service layer is the only reader, so
swapping to pgvector/Qdrant later is contained to ai/memory.py (doc §11.4).
"""
from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class MemoryChunk(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "memory_chunks"
    __table_args__ = (Index("ix_memory_org_lead", "org_id", "lead_id"),)

    lead_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("leads.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)  # meeting|note|proposal
    source_id: Mapped[str | None] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
