"""Per-organisation memory (RAG) — add and search past notes.

Namespace = org_id: a search can only ever touch rows of the caller's
organisation (doc §2.3 "one company's notes must never appear for another").
Cosine search runs in Python, which is exact and comfortably fast at current
scale. When an organisation outgrows this (doc §11.4 thresholds), only this
module changes.

Embeddings come from EMBEDDING_PROVIDER:

  local  — a sentence-transformers model on this machine (the default). No
           key, no quota, no per-call cost, and a client's notes never leave
           the server. Same trade as STT_PROVIDER=whisper_local.
  gemini — Google's embedding API. Kept so the switch is reversible.
  hash   — the deterministic offline embedder below; also chosen automatically
           when LLM_PROVIDER=stub so dry runs stay instant and offline.

Widths differ between providers (768 local, 3072 gemini, 256 hash), so rows
written by one are not comparable to a query embedded by another. `_cosine`
refuses to compare them and `search_memory` leaves them out — see the note
there. That is the whole migration cost: no schema change, no backfill needed
for correctness.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.models.memory import MemoryChunk

logger = logging.getLogger(__name__)

_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

# One loaded model, shared. Loading costs seconds and ~1 GB of RAM, so it must
# happen once per process, not once per note.
_local_models: dict[str, Any] = {}
# Held only around the load, never around an encode: two requests may encode
# concurrently (torch releases the GIL), but they must not both load.
_local_load_lock = threading.Lock()


def _fallback_embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic bag-of-words hashing embedding — used when no embedding
    provider is configured, so memory keeps working offline (dry-run mode).
    Related texts share tokens → share buckets → nonzero cosine.

    Selected by EMBEDDING_PROVIDER=hash, or automatically for LLM_PROVIDER=stub.
    It matches on shared words, not on meaning: "what did they say about the
    handover pack?" will not find a note that says the same thing in other
    words. That is the whole reason the local model is the default."""
    import zlib

    vec = [0.0] * dim
    for token in text.lower().split():
        token = token.strip(".,!?;:()\"'")
        if len(token) < 3:
            continue
        # crc32 is stable across processes (unlike str hash) — memories written
        # today are still findable after a restart.
        vec[zlib.crc32(token.encode()) % dim] += 1.0
    return vec


def _load_local_model(model_name: str, device: str = "cpu") -> Any:
    model = _local_models.get(model_name)
    if model is not None:
        return model
    with _local_load_lock:
        model = _local_models.get(model_name)  # another thread may have won
        if model is not None:
            return model
        # transformers probes for TensorFlow at import time and loading it costs
        # seconds for nothing — this is a torch-only path. setdefault so an
        # explicit choice in the environment still wins.
        os.environ.setdefault("USE_TF", "0")
        try:
            from sentence_transformers import SentenceTransformer  # heavy (torch)
        except ModuleNotFoundError as exc:
            raise ExternalServiceError(
                "EMBEDDING_PROVIDER=local needs sentence-transformers: "
                "pip install sentence-transformers"
            ) from exc
        try:
            model = SentenceTransformer(model_name, device=device)
        except Exception as exc:  # noqa: BLE001 - surfaces as a skipped memory
            raise ExternalServiceError(
                f"Could not load embedding model {model_name!r}: {exc}"
            ) from exc
        _local_models[model_name] = model
        return model


def _local_embed(text: str, kind: str) -> list[float]:
    """Blocking: always called through asyncio.to_thread."""
    settings = get_settings()
    prefix = (
        settings.embedding_query_prefix
        if kind == "query"
        else settings.embedding_passage_prefix
    )
    model = _load_local_model(settings.embedding_model_local, settings.embedding_device)
    return [float(v) for v in model.encode(f"{prefix}{text}")]


async def embed_text(text: str, *, kind: str = "passage") -> list[float]:
    """`kind` matters for asymmetric models: text being stored is a "passage",
    text being searched for is a "query". Getting the pair wrong does not
    error — it quietly weakens every match — so the two callers below are the
    only places that choose it."""
    settings = get_settings()
    provider = settings.embedding_provider
    # A dry run must stay offline and instant whatever the configured provider.
    if provider == "hash" or settings.llm_provider == "stub":
        return _fallback_embed(text)
    if provider == "local":
        # Blocking CPU work → a worker thread; the async pipeline stays live.
        return await asyncio.to_thread(_local_embed, text[:8000], kind)
    if not settings.gemini_api_key:
        return _fallback_embed(text)
    model = settings.embedding_model
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                _EMBED_URL.format(model=model),
                params={"key": settings.gemini_api_key},
                json={
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": text[:8000]}]},
                },
            )
        if resp.status_code >= 400:
            raise ExternalServiceError(f"Embedding failed ({resp.status_code}): {resp.text[:200]}")
        return resp.json()["embedding"]["values"]
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"Embedding request failed: {exc}") from exc


def _cosine(a: list[float], b: list[float]) -> float:
    # Different widths mean different models. zip() would silently compare only
    # the overlapping head and return a confident-looking number for something
    # meaningless (measured: 0.598 for a 3-wide against a 2-wide). Incomparable
    # is not "somewhat similar" — it is no answer at all.
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def add_memory(
    db: AsyncSession,
    *,
    org_id: str,
    text: str,
    source_type: str,
    source_id: str | None = None,
    lead_id: str | None = None,
) -> MemoryChunk | None:
    """Store a memory chunk. Failures are logged, never fatal — memory is an
    enhancement, not a dependency of the main flow."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        embedding = await embed_text(text, kind="passage")
    except ExternalServiceError as exc:
        logger.warning("Memory embedding skipped: %s", exc)
        return None
    chunk = MemoryChunk(
        org_id=org_id,
        lead_id=lead_id,
        source_type=source_type,
        source_id=source_id,
        text=text[:4000],
        embedding=embedding,
    )
    db.add(chunk)
    return chunk


async def search_memory(
    db: AsyncSession,
    *,
    org_id: str,
    query: str,
    top_k: int = 5,
    lead_id: str | None = None,
) -> list[dict]:
    """Return the most relevant memories for this organisation only."""
    try:
        query_embedding = await embed_text(query, kind="query")
    except ExternalServiceError as exc:
        logger.warning("Memory search skipped: %s", exc)
        return []

    stmt = select(MemoryChunk).where(MemoryChunk.org_id == org_id)
    if lead_id:
        stmt = stmt.where(MemoryChunk.lead_id == lead_id)
    chunks = (await db.execute(stmt)).scalars().all()

    # Rows written by a previous embedding model have a different width and
    # cannot be scored against this query. Drop them rather than offer them at
    # a meaningless score: a wrong note presented as a memory is worse than no
    # memory. They stay in the table, so re-indexing later revives them.
    width = len(query_embedding)
    comparable = [c for c in chunks if len(c.embedding) == width]
    if len(comparable) != len(chunks):
        logger.warning(
            "Memory search ignored %d chunk(s) embedded by a different model "
            "(org %s); re-index to make them searchable again",
            len(chunks) - len(comparable), org_id,
        )

    scored = [
        {
            "text": c.text,
            "source_type": c.source_type,
            "source_id": c.source_id,
            "lead_id": c.lead_id,
            "score": round(_cosine(query_embedding, c.embedding), 4),
            "created_at": c.created_at.isoformat(),
        }
        for c in comparable
    ]
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]
