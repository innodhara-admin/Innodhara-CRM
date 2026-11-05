"""POST /dictate tells the caller when it did not hear well.

The assistant's mic auto-sends what it transcribes, so a bad transcript becomes
a command nobody typed. Measured with real neural Kannada speech: Whisper at
`tiny` returned 6-12% similarity to what was said, at confidence 0.01-0.41 —
correctly low. The signal was there; the response simply never carried the
verdict, so the app had nothing to gate on and sent the garbage.

The 0.6 threshold stays in ONE place (TranscriptionResult.low_confidence) and
travels to the client as a boolean. Duplicating the number in Java would let
the two drift apart silently.
"""
from __future__ import annotations

import pytest

from app.ai.stt import TranscriptionResult
from tests.conftest import auth

pytestmark = pytest.mark.asyncio


def _fake_transcribe(result: TranscriptionResult):
    async def _run(*_args, **_kwargs):
        return result

    return _run


async def _dictate(client, token, monkeypatch, result: TranscriptionResult):
    from app.ai import stt

    monkeypatch.setattr(stt, "transcribe", _fake_transcribe(result))
    return await client.post(
        "/api/v1/dictate",
        headers=auth(token),
        files={"file": ("clip.m4a", b"not-real-audio", "audio/mp4")},
    )


async def test_a_confident_transcript_is_not_flagged(client, org_a, monkeypatch):
    resp = await _dictate(
        client, org_a["agent_token"], monkeypatch,
        TranscriptionResult(text="Show my open tasks", language="en", confidence=0.82),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["low_confidence"] is False


async def test_a_poor_transcript_is_flagged_so_the_app_can_refuse_to_send(
    client, org_a, monkeypatch
):
    """This is the real Kannada-at-tiny case: words came back, and they were
    nonsense."""
    resp = await _dictate(
        client, org_a["agent_token"], monkeypatch,
        TranscriptionResult(
            text="らんu nabakieduakaregala nutoreco", language="kn", confidence=0.01
        ),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["low_confidence"] is True
    # The text still comes back: the user should see what was heard and be able
    # to fix it. Silently discarding it is its own kind of lying.
    assert body["text"] == "らんu nabakieduakaregala nutoreco"


async def test_the_flag_uses_the_same_threshold_as_the_meeting_review_gate(
    client, org_a, monkeypatch
):
    """0.6 is defined once, on TranscriptionResult. If someone changes it there,
    this endpoint must move with it rather than keep its own copy."""
    just_under = TranscriptionResult(text="hmm", language="en", confidence=0.59)
    just_over = TranscriptionResult(text="hmm", language="en", confidence=0.61)
    assert just_under.low_confidence is True
    assert just_over.low_confidence is False

    under = await _dictate(client, org_a["agent_token"], monkeypatch, just_under)
    over = await _dictate(client, org_a["agent_token"], monkeypatch, just_over)
    assert under.json()["low_confidence"] is True
    assert over.json()["low_confidence"] is False


async def test_dictation_is_limited_to_the_languages_people_here_speak(
    client, org_a, monkeypatch
):
    """Reported 21 Sep 2026: a dictated client name came back as Russian
    ("Я с Джебиис. Тумку."). Whisper `tiny` with no language to hold on to
    picks one; dictation now runs the same ladder and the same language limit
    as voice mode, and is told the organisation's names."""
    from app.ai import stt, voice
    from app.config import get_settings

    seen: dict = {}

    async def _capture(audio, mime, **kwargs):
        seen.update(kwargs)
        return TranscriptionResult(text="SJBC Tumkur", language="en", confidence=0.8)

    monkeypatch.setattr(stt, "transcribe", _capture)
    resp = await client.post(
        "/api/v1/dictate",
        headers=auth(org_a["agent_token"]),
        files={"file": ("clip.m4a", b"not-real-audio", "audio/mp4")},
    )
    assert resp.status_code == 200, resp.text
    assert seen["model"] == get_settings().dictation_whisper_model != "tiny"
    assert seen["languages"] == voice.stt_languages() == ("en", "hi", "kn")
    # The same names voice mode expects: people, recent clients, cities.
    assert seen["prompt"] and "Cities:" in seen["prompt"]


async def test_a_hint_that_cannot_be_built_never_costs_the_sentence(
    client, org_a, monkeypatch
):
    """The hint is a nicety. If it fails, the words still come back."""
    from app.ai import client_draft, stt

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("no database today")

    monkeypatch.setattr(client_draft, "vocabulary_hint", _boom)
    monkeypatch.setattr(stt, "transcribe", _fake_transcribe(
        TranscriptionResult(text="Add a note", language="en", confidence=0.9)))
    resp = await client.post(
        "/api/v1/dictate",
        headers=auth(org_a["agent_token"]),
        files={"file": ("clip.m4a", b"not-real-audio", "audio/mp4")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "Add a note"


async def test_dictation_and_voice_share_one_loaded_model():
    """Same model name on purpose (21 Sep 2026): a text field then hears
    Kannada and Hindi as well as a spoken turn does, and the GPU holds one
    copy rather than two. They also share its lock — a long dictation makes a
    spoken turn wait, which is the price of not loading 3.5 GB twice."""
    from app.config import Settings

    fields = Settings.model_fields
    assert fields["dictation_whisper_model"].default == "large-v3"
    assert fields["voice_stt_model"].default == "large-v3"
    assert (fields["dictation_whisper_model"].default
            == fields["voice_stt_model"].default)
