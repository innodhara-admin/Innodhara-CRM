"""Speech-to-Text with a provider switch (STT_PROVIDER in .env).

  whisper_local — open-source Whisper running on this machine (default).
                  Audio never leaves the server; no API key, no quota.
                  Needs `pip install openai-whisper` and ffmpeg on PATH;
                  the model file downloads to ~/.cache/whisper on first use.
  gemini        — Google's audio understanding via GEMINI_API_KEY. Small
                  files travel inline; larger recordings go through the
                  Gemini Files API first. Always calls the Gemini provider
                  directly — the active chat provider (LLM_PROVIDER) may be
                  OpenRouter/Claude, which cannot accept audio.

Callers only ever see transcribe() -> TranscriptionResult.
"""
from __future__ import annotations

import asyncio
import base64
import math
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from app.ai.llm import GeminiProvider, extract_json
from app.config import get_settings
from app.core.exceptions import ExternalServiceError

_INLINE_LIMIT = 15 * 1024 * 1024  # stay under Gemini's ~20MB request cap
_UPLOAD_BASE = "https://generativelanguage.googleapis.com/upload/v1beta/files"

_TRANSCRIBE_PROMPT = (
    "Transcribe this sales-meeting recording verbatim. Indian accents and "
    "Hinglish may occur — transcribe what is actually said. Then return JSON with:\n"
    '  "text": the full transcript,\n'
    '  "language": main language (e.g. "en", "hi"),\n'
    '  "confidence": your 0.0-1.0 confidence in transcript accuracy.\n'
    "Return ONLY the JSON object."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "language": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["text", "confidence"],
}


@dataclass
class TranscriptionResult:
    text: str
    language: str | None
    confidence: float

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.6


# ─────────────────────────────────────────────────────────────────────────────
# Local Whisper
# ─────────────────────────────────────────────────────────────────────────────

_MIME_EXT = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
    "audio/mp4": ".m4a", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a",
    "audio/aac": ".aac", "audio/ogg": ".ogg", "audio/opus": ".opus",
    "audio/flac": ".flac", "audio/webm": ".webm",
    "video/mp4": ".mp4", "video/webm": ".webm",
}

_whisper_models: dict[str, Any] = {}
# One transcription at a time PER MODEL: a whisper model is a shared in-memory
# object and running two passes over the same one concurrently would double
# peak RAM/CPU for no throughput gain.
#
# Per-model rather than one global lock, because /dictate and the meeting
# pipeline load *different* models (tiny vs medium) and there is no shared
# state between them. Under a single lock, tapping the mic while a meeting was
# transcribing would park the user behind a multi-minute batch job with the
# keyboard open — a foreground request waiting on background work. Distinct
# models are distinct objects, so letting them run side by side is safe; the
# original invariant still holds for each one individually.
_whisper_locks: dict[str, threading.Lock] = {}
# Guards the two dicts above only — held for a dict lookup, never for a
# transcription.
_whisper_registry_lock = threading.Lock()


def _lock_for(model_name: str) -> threading.Lock:
    with _whisper_registry_lock:
        lock = _whisper_locks.get(model_name)
        if lock is None:
            lock = threading.Lock()
            _whisper_locks[model_name] = lock
        return lock


def _load_whisper(model_name: str) -> Any:
    # Called with that model's lock held, so the load below cannot race itself.
    model = _whisper_models.get(model_name)
    if model is None:
        try:
            import whisper  # heavy import (torch) — deferred until needed
        except ModuleNotFoundError as exc:
            raise ExternalServiceError(
                "STT_PROVIDER=whisper_local needs the open-source Whisper: "
                "pip install openai-whisper (and ffmpeg on PATH)"
            ) from exc
        import torch  # noqa: PLC0415 — comes with whisper

        if torch.cuda.is_available() and get_settings().whisper_fp16_weights:
            # Loaded on the CPU and moved once halved, so the GPU never holds
            # the float32 copy.
            model = whisper.load_model(model_name, device="cpu")
            _halve_weights(model)
            model = model.to("cuda")
        else:
            model = whisper.load_model(model_name)  # cached in ~/.cache/whisper
        _whisper_models[model_name] = model
    return model


def _halve_weights(model: Any) -> None:
    """Store Whisper's Linear and Conv1d weights as float16.

    Those layers cast their weights to the input's dtype on every call, and on
    a GPU the input is float16 — so the numbers are the same, in half the
    memory. LayerNorm computes in float32 and keeps float32 weights."""
    from whisper.model import Conv1d, Linear  # noqa: PLC0415

    for module in model.modules():
        if isinstance(module, (Linear, Conv1d)):
            module.half()


def _pick_language(model: Any, samples: Any, allowed: Sequence[str]) -> str | None:
    """The most likely of `allowed` for this audio; None = let Whisper detect
    freely. One allowed language is simply used."""
    if not allowed:
        return None
    if len(allowed) == 1:
        return allowed[0]
    import whisper  # noqa: PLC0415

    mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(samples), model.dims.n_mels,
                                      device=model.device)
    if model.device.type == "cuda":
        mel = mel.half()
    _tokens, probs = model.detect_language(mel)
    return max(allowed, key=lambda code: probs.get(code, 0.0))


def _fit_prompt(model: Any, prompt: str | None) -> str | None:
    """Whisper keeps only the LAST n_text_ctx // 2 - 1 tokens of a prompt, so
    an over-long hint silently loses its most important words — the people,
    which come first. Cut from the end instead, at a word."""
    if not prompt:
        return prompt
    import whisper  # noqa: PLC0415

    tokenizer = whisper.tokenizer.get_tokenizer(
        model.is_multilingual, num_languages=model.num_languages)
    limit = model.dims.n_text_ctx // 2 - 1
    words = prompt.split()
    if len(tokenizer.encode(" " + " ".join(words))) <= limit:
        return prompt
    while words and len(tokenizer.encode(" " + " ".join(words) + ".")) > limit:
        words.pop()
    text = " ".join(words).rstrip(",;:.")
    return f"{text}." if text else None


#: Whisper fills silence with what it heard most in training — the outro of a
#: video. These come back from clips with no speech in them at all, and
#: confidently: "Thank you for watching." was sent to Jarvis as a command on
#: 21 Sep 2026. Matched only when the WHOLE transcript is one of them and the
#: model also suspected there was no speech, so a real "thank you" survives.
_PHANTOM_PHRASES = frozenset({
    "thank you for watching", "thanks for watching", "thank you for watching this video",
    "thanks for watching this video", "please subscribe", "like and subscribe",
    "subtitles by the amaraorg community", "subtitles by the amara org community",
    "thank you for your watching", "see you in the next video", "bye bye",
})
_PHANTOM_NO_SPEECH = 0.4


def _heard_or_nothing(text: str, segments: list[dict]) -> str:
    """`text` when someone really said it, "" when Whisper filled a silence.

    Two signs, either of which is enough:
      * every segment says "probably not speech" AND the words scored badly —
        breath and room noise ("Thank you.");
      * the whole transcript is one of Whisper's stock phantom sentences and
        the model had some doubt there was speech at all.
    """
    if not text or not segments:
        return text
    if all(
        s.get("no_speech_prob", 0.0) > 0.6 and s.get("avg_logprob", 0.0) < -1.0
        for s in segments
    ):
        return ""
    plain = re.sub(r"[^a-z ]", " ", text.lower())
    plain = " ".join(plain.split())
    doubted = max((s.get("no_speech_prob", 0.0) for s in segments), default=0.0)
    if plain in _PHANTOM_PHRASES and doubted > _PHANTOM_NO_SPEECH:
        return ""
    return text


def _whisper_confidence(segments: list[dict]) -> float:
    """Whisper reports per-segment avg log-probability; e^(mean) maps it onto
    0–1 so the existing low-confidence review gate (< 0.6) keeps working."""
    if not segments:
        return 0.0
    mean_logprob = sum(s.get("avg_logprob", -1.0) for s in segments) / len(segments)
    return max(0.0, min(1.0, math.exp(mean_logprob)))


def _whisper_transcribe_sync(audio: bytes, mime: str, model_name: str,
                             prompt: str | None = None,
                             languages: Sequence[str] = ()) -> TranscriptionResult:
    suffix = _MIME_EXT.get(mime, ".mp3")
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio)
        tmp.close()  # Windows: ffmpeg can't open a file another handle holds
        with _lock_for(model_name):
            model = _load_whisper(model_name)
            try:
                options: dict[str, Any] = {}
                source: Any = tmp.name
                # `initial_prompt` / a language only when a caller asks;
                # meetings and dictation pass neither and behave as before.
                if prompt:
                    options["initial_prompt"] = _fit_prompt(model, prompt)
                if languages:
                    import whisper  # noqa: PLC0415

                    source = whisper.load_audio(tmp.name)
                    options["language"] = _pick_language(model, source, languages)
                result = model.transcribe(source, **options)
            except FileNotFoundError as exc:
                raise ExternalServiceError(
                    "Whisper needs ffmpeg on PATH to decode audio "
                    "(https://ffmpeg.org) — not found"
                ) from exc
    finally:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    segments = result.get("segments") or []
    # The same silence guard the streaming path has always had. Without it,
    # dictation sent Whisper's phantom "Thank you for watching." to Jarvis as
    # if someone had typed it (21 Sep 2026).
    return TranscriptionResult(
        text=_heard_or_nothing((result.get("text") or "").strip(), segments),
        language=result.get("language"),
        confidence=_whisper_confidence(segments),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Gemini audio understanding
# ─────────────────────────────────────────────────────────────────────────────


async def _upload_to_files_api(data: bytes, mime: str) -> str:
    """Resumable upload; returns the file URI usable in generateContent."""
    settings = get_settings()
    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(len(data)),
        "X-Goog-Upload-Header-Content-Type": mime,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=300) as client:
        start = await client.post(
            _UPLOAD_BASE,
            params={"key": settings.gemini_api_key},
            headers=headers,
            json={"file": {"display_name": "meeting_audio"}},
        )
        if start.status_code >= 400:
            raise ExternalServiceError(f"Gemini file upload init failed: {start.text[:300]}")
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise ExternalServiceError("Gemini file upload: no upload URL returned")
        finish = await client.post(
            upload_url,
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
                "Content-Length": str(len(data)),
            },
            content=data,
        )
        if finish.status_code >= 400:
            raise ExternalServiceError(f"Gemini file upload failed: {finish.text[:300]}")
        return finish.json()["file"]["uri"]


async def _transcribe_gemini(audio: bytes, mime: str) -> TranscriptionResult:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise ExternalServiceError(
            "STT_PROVIDER=gemini needs GEMINI_API_KEY (or use whisper_local)"
        )
    if len(audio) <= _INLINE_LIMIT:
        media_part = {
            "inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}
        }
    else:
        file_uri = await _upload_to_files_api(audio, mime)
        media_part = {"fileData": {"mimeType": mime, "fileUri": file_uri}}

    # Straight to the Gemini provider: the active chat provider may be
    # OpenRouter/Claude, and neither accepts audio parts.
    provider = GeminiProvider()
    response = await provider.generate(
        model=settings.llm_model_fast,
        system=None,
        messages=[{"role": "user", "content": [media_part, {"text": _TRANSCRIBE_PROMPT}]}],
        tools=None,
        json_schema=_SCHEMA,
        temperature=0.1,
        max_tokens=65000,
    )
    try:
        data = extract_json(response.text)
    except Exception as exc:  # noqa: BLE001
        raise ExternalServiceError(f"Could not parse transcription output: {exc}") from exc
    return TranscriptionResult(
        text=(data.get("text") or "").strip(),
        language=data.get("language"),
        confidence=float(data.get("confidence", 0.5) or 0.5),
    )


# ─────────────────────────────────────────────────────────────────────────────
# The one entry point
# ─────────────────────────────────────────────────────────────────────────────


def warm(model_name: str) -> None:
    """Load a Whisper model now, under its lock, so the first request that
    needs it does not pay for the load. whisper_local only; a no-op otherwise."""
    if get_settings().stt_provider != "whisper_local":
        return
    with _lock_for(model_name):
        _load_whisper(model_name)


def _whisper_transcribe_pcm_sync(pcm: bytes, model_name: str,
                                 prompt: str | None = None,
                                 languages: Sequence[str] = ()) -> TranscriptionResult:
    """Voice mode's path: raw 16 kHz mono PCM straight into Whisper, with no
    temporary file and no ffmpeg — the audio is already in the shape Whisper
    resamples everything to."""
    import numpy as np  # noqa: PLC0415 — only this path needs it

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    with _lock_for(model_name):
        model = _load_whisper(model_name)
        options: dict[str, Any] = {}
        if prompt:
            options["initial_prompt"] = _fit_prompt(model, prompt)
        if languages:
            options["language"] = _pick_language(model, samples, languages)
        # A voice turn is one short utterance: conditioning on "previous text"
        # only invites Whisper's repetition loops.
        result = model.transcribe(samples, condition_on_previous_text=False, **options)
    segments = result.get("segments") or []
    text = _heard_or_nothing((result.get("text") or "").strip(), segments)
    return TranscriptionResult(
        text=text,
        language=result.get("language"),
        confidence=_whisper_confidence(segments),
    )


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    import io  # noqa: PLC0415
    import wave  # noqa: PLC0415

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()


async def transcribe_pcm16(
    pcm: bytes, *, sample_rate: int = 16_000, model: str | None = None,
    prompt: str | None = None, languages: Sequence[str] = (),
) -> TranscriptionResult:
    """Transcribe mono 16-bit PCM. whisper_local takes it directly (16 kHz);
    any other rate, or the Gemini provider, goes through a WAV wrapper.
    `languages` limits detection to those Whisper codes (whisper_local)."""
    settings = get_settings()
    if settings.stt_provider == "whisper_local":
        if sample_rate == 16_000:
            return await asyncio.to_thread(
                _whisper_transcribe_pcm_sync, pcm, model or settings.whisper_model,
                prompt, tuple(languages),
            )
        return await transcribe(
            _pcm_to_wav(pcm, sample_rate), "audio/wav", model=model, prompt=prompt,
            languages=languages,
        )
    return await _transcribe_gemini(_pcm_to_wav(pcm, sample_rate), "audio/wav")


async def transcribe(
    audio: bytes,
    mime: str,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
    languages: Sequence[str] = (),
) -> TranscriptionResult:
    """Transcribe `audio`. `model` overrides WHISPER_MODEL for this one call
    (whisper_local only — the Gemini path has no per-call size ladder). Left
    at None, behaviour is exactly what it always was: settings.whisper_model.
    Used by /dictate to run a small, fast model without disturbing the
    meeting pipeline's."""
    if mime.startswith("audio/") is False and mime not in ("video/mp4", "video/webm"):
        mime = "audio/mpeg"
    settings = get_settings()
    if settings.stt_provider == "whisper_local":
        # Blocking CPU work → a worker thread; the async pipeline stays live.
        return await asyncio.to_thread(
            _whisper_transcribe_sync, audio, mime, model or settings.whisper_model,
            prompt, tuple(languages),
        )
    return await _transcribe_gemini(audio, mime)
