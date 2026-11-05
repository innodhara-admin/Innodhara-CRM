"""Embeddings behind a provider switch (EMBEDDING_PROVIDER).

  local  — a sentence-transformers model on this machine (the default).
           No key, no quota, nothing leaves the server.
  gemini — the previous behaviour, kept so the switch is reversible.
  hash   — the deterministic offline embedder, used by dry runs and tests.

The tests that need the real model skip themselves when it is not installed,
so the suite still runs on a machine that has never downloaded it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai import memory as memory_ai
from app.core.exceptions import ExternalServiceError

pytestmark = pytest.mark.asyncio


def _settings(**overrides):
    """A settings stand-in — memory.py resolves get_settings() per call, so
    patching that one name is enough to steer the provider."""
    base = dict(
        embedding_provider="hash",
        embedding_model_local="intfloat/multilingual-e5-base",
        embedding_query_prefix="query: ",
        embedding_passage_prefix="passage: ",
        embedding_device="cpu",
        embedding_model="gemini-embedding-001",
        gemini_api_key="",
        llm_provider="openrouter",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def use(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(memory_ai, "get_settings", lambda: _settings(**overrides))


def local_model_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


requires_local = pytest.mark.skipif(
    not local_model_available(),
    reason="sentence-transformers not installed",
)


# ── the offline embedder ─────────────────────────────────────────────────────


async def test_hash_provider_is_chosen_by_the_switch_not_by_a_missing_key(
    monkeypatch,
):
    """A key IS configured here, so the only thing that can select the offline
    embedder is EMBEDDING_PROVIDER. That distinction is the bug this migration
    fixes: the old code only fell back when the key was absent, so a key that
    was present but out of credits raised instead, and notes went unindexed.
    Also asserts determinism — memories written today must still be findable
    after a restart."""
    use(monkeypatch, embedding_provider="hash", gemini_api_key="a-real-looking-key")
    first = await memory_ai.embed_text("the busway is running a week late")
    second = await memory_ai.embed_text("the busway is running a week late")
    assert first == second
    assert any(v > 0 for v in first)


async def test_the_stub_llm_provider_never_loads_a_model(monkeypatch):
    """Dry runs (LLM_PROVIDER=stub) must stay offline and instant, even though
    the embedding provider now defaults to a real local model."""
    use(monkeypatch, embedding_provider="local", llm_provider="stub")

    def explode(*_a, **_k):  # pragma: no cover - must never run
        raise AssertionError("stub mode loaded the local model")

    monkeypatch.setattr(memory_ai, "_local_embed", explode)
    vector = await memory_ai.embed_text("a note written during a dry run")
    assert len(vector) == 256  # the hash embedder's width


# ── the dimension guard ──────────────────────────────────────────────────────


async def test_vectors_of_different_widths_score_zero_not_a_truncated_match():
    """zip() would silently compare only the overlapping head of two vectors,
    so a 256-wide fallback row and a 768-wide model row would produce a
    confident, meaningless score. They are not comparable; say so."""
    assert memory_ai._cosine([1.0, 2.0, 3.0], [1.0, 2.0]) == 0.0


async def test_a_chunk_from_another_model_cannot_outrank_a_real_match(
    monkeypatch,
):
    """A database holding vectors from two different models must not return
    the stale ones as top hits."""
    use(monkeypatch, embedding_provider="hash")
    query = await memory_ai.embed_text("busway delay")
    stale = [1.0] * 9999  # a different model's width
    assert memory_ai._cosine(query, stale) == 0.0


async def test_search_ignores_rows_written_by_a_previous_embedding_model(
    client, monkeypatch
):
    """Switching model leaves older rows behind at a different width. They are
    not comparable to anything the new model produces, so they must be left
    out of results rather than offered with a meaningless score."""
    from app.database import SessionLocal
    from app.models.memory import MemoryChunk

    use(monkeypatch, embedding_provider="hash")
    org = "org-for-mixed-width-memory"
    async with SessionLocal() as db:
        db.add(
            MemoryChunk(
                org_id=org, source_type="note", text="written by the old model",
                embedding=[0.1] * 3072,  # gemini-embedding-001's width
            )
        )
        db.add(
            MemoryChunk(
                org_id=org, source_type="note",
                text="the busway is running a week late",
                embedding=await memory_ai.embed_text(
                    "the busway is running a week late", kind="passage"
                ),
            )
        )
        await db.commit()

    async with SessionLocal() as db:
        hits = await memory_ai.search_memory(db, org_id=org, query="busway delay")

    assert [h["text"] for h in hits] == ["the busway is running a week late"]


# ── the local model ──────────────────────────────────────────────────────────


@requires_local
async def test_local_provider_returns_the_models_own_width(monkeypatch):
    use(monkeypatch, embedding_provider="local")
    vector = await memory_ai.embed_text("Fact about the client: 120 racks")
    assert len(vector) == 768  # multilingual-e5-base
    assert any(v != 0 for v in vector)


@requires_local
async def test_the_local_model_stays_off_the_gpu_by_default(monkeypatch):
    """The GPU on the deployment host is Whisper's. Transcription needs ~5 GB
    at `medium` and ~10 GB at `large` on a 12 GB card; an embedding model that
    quietly claims VRAM next to it turns an upgrade into an out-of-memory
    failure in an unrelated subsystem. Embedding is ~8 ms on CPU, so there is
    nothing to win here — sentence-transformers defaults to CUDA when it is
    available, and this is the line that overrides it."""
    use(monkeypatch, embedding_provider="local")
    await memory_ai.embed_text("a note that must not touch the GPU")
    model = memory_ai._local_models[_settings().embedding_model_local]
    assert str(next(model.parameters()).device) == "cpu"


@requires_local
async def test_a_query_and_a_passage_are_embedded_differently(monkeypatch):
    """e5 is asymmetric: the same words must produce different vectors
    depending on whether they are being stored or being searched for."""
    use(monkeypatch, embedding_provider="local")
    as_passage = await memory_ai.embed_text("the handover pack", kind="passage")
    as_query = await memory_ai.embed_text("the handover pack", kind="query")
    assert as_passage != as_query


@requires_local
async def test_a_note_is_found_by_meaning_not_by_keyword(monkeypatch):
    """The whole point of the feature: words that never appear in the note
    still find it, and an unrelated note scores lower."""
    use(monkeypatch, embedding_provider="local")
    question = await memory_ai.embed_text(
        "what did they say about the handover pack?", kind="query"
    )
    right = await memory_ai.embed_text(
        "Fact about the client: the documented handover pack is a priority.",
        kind="passage",
    )
    wrong = await memory_ai.embed_text(
        "Fact about the client: Devendra prefers WhatsApp for urgent issues.",
        kind="passage",
    )
    assert memory_ai._cosine(question, right) > memory_ai._cosine(question, wrong)


@requires_local
async def test_an_indic_script_question_finds_an_english_note(monkeypatch):
    """Why this model was chosen over all-MiniLM-L6-v2: an English-only
    tokeniser turns Kannada into [UNK] tokens, so every Kannada question
    collapses onto the same meaningless vector. This is the regression guard
    on that decision — swapping in an English-only model fails here."""
    use(monkeypatch, embedding_provider="local")
    kannada = await memory_ai.embed_text(
        "ಹ್ಯಾಂಡೋವರ್ ಪ್ಯಾಕ್ ಬಗ್ಗೆ ಅವರು ಏನು ಹೇಳಿದರು?", kind="query"
    )
    right = await memory_ai.embed_text(
        "Fact about the client: the documented handover pack is a priority.",
        kind="passage",
    )
    wrong = await memory_ai.embed_text(
        "Fact about the client: Devendra prefers WhatsApp for urgent issues.",
        kind="passage",
    )
    assert memory_ai._cosine(kannada, right) > memory_ai._cosine(kannada, wrong)


# ── failure is never fatal ───────────────────────────────────────────────────


async def test_a_broken_local_install_degrades_instead_of_crashing(monkeypatch):
    """Memory is an enhancement, not a dependency of the main flow."""
    use(monkeypatch, embedding_provider="local")

    def unavailable(*_a, **_k):
        raise ExternalServiceError("sentence-transformers is not installed")

    monkeypatch.setattr(memory_ai, "_local_embed", unavailable)
    with pytest.raises(ExternalServiceError):
        await memory_ai.embed_text("a note nobody will be able to index")


async def test_the_gemini_path_is_still_reachable(monkeypatch):
    """The switch has to be reversible: selecting gemini must still call
    Google's endpoint and nothing else."""
    use(monkeypatch, embedding_provider="gemini", gemini_api_key="a-key")
    called: dict = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"embedding": {"values": [0.5, 0.25]}}

    class FakeClient:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, url, **kwargs):
            called["url"] = url
            return FakeResponse()

    monkeypatch.setattr(memory_ai.httpx, "AsyncClient", FakeClient)
    vector = await memory_ai.embed_text("a note")
    assert vector == [0.5, 0.25]
    assert "generativelanguage.googleapis.com" in called["url"]
