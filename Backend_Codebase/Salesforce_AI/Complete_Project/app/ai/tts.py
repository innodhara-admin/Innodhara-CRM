"""Text-to-speech for voice mode, with an engine switch (VOICE_TTS_ENGINE).

  kokoro — Kokoro-82M (Apache-2.0) on this machine, English voices, 24 kHz.
           Needs `pip install kokoro soundfile`; the weights (~310 MB) download
           to the HuggingFace cache on first load, and its English phonemiser
           fetches spaCy's `en_core_web_sm` the first time too. Measured on the
           office RTX 3060: ~12 s to load, ~0.1 s to speak a 4 s sentence once
           warm, ~0.7 GB of VRAM.
  off    — no server voice. Voice mode still runs; its `reply` messages say
           `spoken_by: device` and the phone speaks the text itself.

An engine that fails to import or load is reported, not raised: voice mode
must degrade to the phone's voice, never break. Callers only see
`synthesize()` -> Speech | None.
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import wave
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

ENGINE_OFF = "off"
ENGINE_KOKORO = "kokoro"

# The voices a client may ask for: Kokoro's American English set, the ones the
# loaded pipeline (VOICE_TTS_LANG_CODE "a") can speak. Each is a ~0.5 MB file
# fetched from the HuggingFace cache on first use. Anything else falls back to
# VOICE_TTS_VOICE — a voice is a preference, never a reason to fail.
VOICES = (
    "af_heart", "af_bella", "af_sarah", "af_nicole", "af_kore", "af_aoede",
    "af_alloy", "af_jessica", "af_nova", "af_river", "af_sky",
    "am_michael", "am_fenrir", "am_puck", "am_adam", "am_echo", "am_eric",
    "am_liam", "am_onyx",
)


def resolve_voice(voice: Any) -> str | None:
    """`voice` if the server can speak with it, else None (= the default)."""
    return voice if isinstance(voice, str) and voice in VOICES else None


@dataclass(frozen=True)
class Speech:
    """Mono 16-bit little-endian PCM."""

    pcm: bytes
    sample_rate: int

    @property
    def seconds(self) -> float:
        return len(self.pcm) / 2 / self.sample_rate if self.sample_rate else 0.0


def float_to_pcm16(samples: Any) -> bytes:
    audio = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    return (audio * 32767.0).astype("<i2").tobytes()


def wav_bytes(speech: Speech) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(speech.sample_rate)
        out.writeframes(speech.pcm)
    return buffer.getvalue()


class _KokoroEngine:
    name = ENGINE_KOKORO
    sample_rate = 24_000

    def __init__(self) -> None:
        settings = get_settings()
        from kokoro import KPipeline  # heavy (torch, spaCy) — deferred

        device = settings.voice_tts_device
        if device.startswith("cuda"):
            import torch

            if not torch.cuda.is_available():
                device = "cpu"
        self._pipeline = KPipeline(
            lang_code=settings.voice_tts_lang_code, device=device,
            repo_id="hexgrad/Kokoro-82M",
        )
        self._voice = settings.voice_tts_voice
        self._speed = settings.voice_tts_speed

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        chosen = voice or self._voice
        try:
            return self._run(text, chosen)
        except Exception:  # noqa: BLE001 — e.g. the voice file could not be fetched
            if chosen == self._voice:
                raise
            logger.warning("Voice mode: voice %s failed; using %s", chosen, self._voice,
                           exc_info=True)
            return self._run(text, self._voice)

    def _run(self, text: str, voice: str) -> bytes:
        chunks = []
        for result in self._pipeline(text, voice=voice, speed=self._speed):
            audio = getattr(result, "audio", None)
            if audio is None:
                continue
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            chunks.append(np.asarray(audio, dtype=np.float32))
        return float_to_pcm16(np.concatenate(chunks)) if chunks else b""


_engine: Any = None
_error: str | None = None
_tried = False
# One load, and one synthesis at a time: a pipeline is a shared object.
_lock = threading.Lock()


def configured_engine() -> str:
    return (get_settings().voice_tts_engine or ENGINE_OFF).strip().lower()


def _load() -> Any:
    global _engine, _error, _tried
    with _lock:
        if _tried:
            return _engine
        _tried = True
        name = configured_engine()
        if name == ENGINE_OFF:
            _error = "server voice is switched off (VOICE_TTS_ENGINE=off)"
            return None
        if name != ENGINE_KOKORO:
            _error = f"unknown VOICE_TTS_ENGINE '{name}'"
            logger.warning("Voice mode: %s; replies will be spoken by the phone", _error)
            return None
        try:
            _engine = _KokoroEngine()
            logger.info("Voice mode: Kokoro loaded")
        except Exception as exc:  # noqa: BLE001 — degrade to the phone's voice
            _error = f"{type(exc).__name__}: {exc}"
            logger.warning("Voice mode: Kokoro unavailable (%s); replies will be "
                           "spoken by the phone", _error)
        return _engine


def is_ready() -> bool:
    """Loaded and usable right now — never triggers a load."""
    return _engine is not None


def status() -> dict[str, Any]:
    return {
        "engine": configured_engine(),
        # null until a load has been attempted in this process
        "available": (_engine is not None) if _tried else None,
        "sample_rate": _engine.sample_rate if _engine is not None else None,
        "error": _error,
    }


async def warm() -> bool:
    return await asyncio.to_thread(_load) is not None


def _synthesize_locked(engine: Any, text: str, voice: str | None) -> bytes:
    with _lock:
        if voice is None:
            return engine.synthesize(text)
        return engine.synthesize(text, voice)


async def synthesize(text: str, voice: str | None = None) -> Speech | None:
    """Speak `text` (in `voice` when it is one of VOICES), or None when there
    is no usable engine (or no text)."""
    text = (text or "").strip()
    if not text:
        return None
    engine = await asyncio.to_thread(_load)
    if engine is None:
        return None
    pcm = await asyncio.to_thread(_synthesize_locked, engine, text, resolve_voice(voice))
    return Speech(pcm=pcm, sample_rate=engine.sample_rate) if pcm else None


def install_engine_for_tests(engine: Any) -> None:
    """Swap the engine (None = reset to "not tried"). Tests only."""
    global _engine, _error, _tried
    with _lock:
        _engine = engine
        _error = None
        _tried = engine is not None
