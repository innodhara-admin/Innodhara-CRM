"""Voice mode's transport-free parts: end of turn, speech in, words out.

Used by both voice endpoints (app/api/voice.py) — the streaming WebSocket and
the one-clip HTTP turn — so the rules below hold on either path:

* A transcript is never acted on when Whisper is unsure of it
  (`TranscriptionResult.low_confidence`, the same 0.6 gate as meetings and
  dictation). The person hears what was caught and is asked again.
* What is spoken is a plain version of the reply: markdown and links removed,
  long answers cut at a sentence with a pointer to the screen. The full reply
  and its cards still go to the app.
* Voice audio is transcribed and discarded, like dictation. Nothing here
  writes it anywhere.
"""
from __future__ import annotations

import asyncio
import math
import re
from collections import deque

import numpy as np

from app.ai import stt
from app.config import get_settings

PCM_FORMAT = "pcm_s16le"
PCM_SAMPLE_RATE = 16_000
#: Containers the phone may send whole instead of streaming PCM. Decoded by
#: ffmpeg at end of speech, like /dictate. No server end-of-turn detection on
#: these — the phone says when the person stopped.
CLIP_FORMATS = {
    "audio/ogg", "audio/opus", "audio/webm", "audio/mp4", "audio/m4a",
    "audio/aac", "audio/mpeg", "audio/wav",
}

# ── End of turn ──────────────────────────────────────────────────────────────


class EndOfTurnDetector:
    """Energy-based speech detection over 16 kHz mono PCM, in 20 ms frames.

    Starts an utterance after a short run of loud frames (keeping a little
    audio from before it, so the first syllable is not clipped) and ends it
    after `silence_ms` of quiet. The loudness bar is the higher of a fixed
    floor and a multiple of the running background level, which is learnt only
    from quiet frames so speech never raises it.

    A deliberately simple detector: it needs no model and no extra package.
    The phone may run its own and send `end_of_speech` instead; both work.
    """

    FRAME_MS = 20

    def __init__(
        self,
        *,
        silence_ms: int,
        min_speech_ms: int,
        max_utterance_ms: int,
        sample_rate: int = PCM_SAMPLE_RATE,
        preroll_ms: int = 300,
        start_frames: int = 3,
        floor: float = 0.012,
        over_background: float = 3.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_bytes = sample_rate * self.FRAME_MS // 1000 * 2
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.max_utterance_ms = max_utterance_ms
        self.start_frames = start_frames
        self.floor = floor
        self.over_background = over_background
        self._preroll: deque[bytes] = deque(maxlen=max(preroll_ms // self.FRAME_MS, 1))
        self._background = 0.0
        self._pending = bytearray()
        self.reset()

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def reset(self) -> None:
        self._pending.clear()
        self._preroll.clear()
        self._utterance = bytearray()
        self._in_speech = False
        self._loud_run = 0
        self._quiet_ms = 0
        self._speech_ms = 0

    def feed(self, data: bytes) -> list[tuple[str, bytes | None]]:
        """Add audio; returns events in order: ("speech_start", None),
        ("speech_end", utterance_pcm) or ("noise", None) for a blip too short
        to be speech."""
        events: list[tuple[str, bytes | None]] = []
        self._pending.extend(data)
        size = self.frame_bytes
        while len(self._pending) >= size:
            frame = bytes(self._pending[:size])
            del self._pending[:size]
            event = self._frame(frame)
            if event is not None:
                events.append(event)
        return events

    def flush(self) -> bytes | None:
        """End the utterance now (the phone said the person stopped)."""
        if not self._in_speech:
            self._pending.clear()
            return None
        if self._pending:
            self._utterance.extend(self._pending)
            self._pending.clear()
        event = self._finish()
        return event[1] if event[0] == "speech_end" else None

    def _loud(self, frame: bytes) -> tuple[bool, float]:
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768.0
        level = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        return level >= max(self.floor, self._background * self.over_background), level

    def _frame(self, frame: bytes) -> tuple[str, bytes | None] | None:
        loud, level = self._loud(frame)
        if not self._in_speech:
            self._preroll.append(frame)
            if not loud:
                self._loud_run = 0
                self._background = 0.95 * self._background + 0.05 * level
                return None
            self._loud_run += 1
            if self._loud_run < self.start_frames:
                return None
            self._in_speech = True
            self._utterance = bytearray(b"".join(self._preroll))
            self._preroll.clear()
            self._speech_ms = self._loud_run * self.FRAME_MS
            self._quiet_ms = 0
            return ("speech_start", None)

        self._utterance.extend(frame)
        if loud:
            self._quiet_ms = 0
            self._speech_ms += self.FRAME_MS
        else:
            self._quiet_ms += self.FRAME_MS
        length_ms = len(self._utterance) * 1000 // (2 * self.sample_rate)
        if self._quiet_ms >= self.silence_ms or length_ms >= self.max_utterance_ms:
            return self._finish()
        return None

    def _finish(self) -> tuple[str, bytes | None]:
        utterance, speech_ms = bytes(self._utterance), self._speech_ms
        self._utterance = bytearray()
        self._in_speech = False
        self._loud_run = 0
        self._quiet_ms = 0
        self._speech_ms = 0
        if speech_ms < self.min_speech_ms:
            return ("noise", None)
        return ("speech_end", utterance)


def detector_from_settings() -> EndOfTurnDetector:
    s = get_settings()
    return EndOfTurnDetector(
        silence_ms=s.voice_vad_silence_ms,
        min_speech_ms=s.voice_min_utterance_ms,
        max_utterance_ms=s.voice_max_utterance_seconds * 1000,
    )


def max_utterance_bytes() -> int:
    """Upper bound on one utterance of raw PCM (plus slack for pre-roll)."""
    return (get_settings().voice_max_utterance_seconds + 1) * PCM_SAMPLE_RATE * 2


# ── Speech in ────────────────────────────────────────────────────────────────


def stt_languages() -> tuple[str, ...]:
    """VOICE_STT_LANGUAGES as Whisper codes ("en,hi,kn" -> ("en", "hi", "kn"))."""
    raw = get_settings().voice_stt_languages or ""
    return tuple(dict.fromkeys(code.strip().lower() for code in raw.split(",") if code.strip()))


async def transcribe_utterance(pcm: bytes, prompt: str | None = None) -> stt.TranscriptionResult:
    """16 kHz mono PCM from the streaming session. `prompt` lists words to
    expect (people, clients, cities), which Whisper uses for spelling."""
    return await stt.transcribe_pcm16(pcm, model=get_settings().voice_stt_model,
                                      prompt=prompt, languages=stt_languages())


async def transcribe_clip(audio: bytes, mime: str,
                          prompt: str | None = None) -> stt.TranscriptionResult:
    """A whole recorded clip (the HTTP turn, or a container-format stream)."""
    return await stt.transcribe(audio, mime, model=get_settings().voice_stt_model,
                                prompt=prompt, languages=stt_languages())


async def warm_stt() -> None:
    await asyncio.to_thread(stt.warm, get_settings().voice_stt_model)


# ── Words out ────────────────────────────────────────────────────────────────

_URL = re.compile(r"https?://\S+")
_MARKUP = re.compile(r"\*\*|__|`+|^#+\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
SPOKEN_LIMIT = 600
_MIN_SENTENCE = 25
#: A run of digits long enough to be a phone number rather than a quantity —
#: reported 21 Sep 2026: "contact numbers it is saying is billions, millions
#: and thousands". Seven is short enough to catch a landline and long enough
#: to leave years, counts and amounts ("5000 students") alone.
_PHONE_DIGITS = 7
_DIGIT_RUN = re.compile(r"\+?\d[\d\s-]{%d,}\d" % (_PHONE_DIGITS - 1))


def _spoken_digits(match: re.Match[str]) -> str:
    """A phone number as digits to read one at a time, keeping any +."""
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if len(digits) < _PHONE_DIGITS:
        return raw
    spaced = " ".join(digits)
    return f"+ {spaced}" if raw.lstrip().startswith("+") else spaced


def speakable(text: str, *, limit: int = SPOKEN_LIMIT) -> str:
    """The reply as something worth hearing: no markup, no links read out
    character by character, and not a whole list read aloud."""
    plain = _URL.sub("the link on screen", text or "")
    plain = _MARKUP.sub("", plain)
    plain = _BULLET.sub("", plain)
    plain = _DIGIT_RUN.sub(_spoken_digits, plain)
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    joined = " ".join(
        line if line[-1:] in ".!?:;," else line + "." for line in lines
    )
    joined = re.sub(r"\s+", " ", joined).strip()
    if len(joined) <= limit:
        return joined
    cut = max(joined.rfind(". ", 0, limit), joined.rfind("? ", 0, limit))
    head = joined[: cut + 1] if cut > limit // 3 else joined[:limit].rsplit(" ", 1)[0] + "…"
    return head + " The rest is on your screen."


def sentences(text: str) -> list[str]:
    """Split for sentence-by-sentence speech, merging fragments too short to
    carry their own intonation ("Done." + the sentence after it)."""
    parts = [p.strip() for p in _SENTENCE_END.split(text or "") if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) < _MIN_SENTENCE:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


# Said the moment the router has chosen, while the agent works — a fixed
# template per agent, so it costs no model call (proposal, "Answering").
_ACKNOWLEDGEMENTS = {
    "query": "Let me check.",
    "conversation": "On it.",
    "proposal": "Working on the document.",
    "email": "Drafting that now.",
    "followup": "Checking your follow-ups.",
    "scheduling": "Looking at the calendar.",
    "client": "Getting that client ready.",
}


def acknowledgement(agent: str) -> str:
    return _ACKNOWLEDGEMENTS.get(agent, "One moment.")


def not_understood_reply(heard: str) -> str:
    heard = " ".join((heard or "").split())
    if not heard:
        return "I didn't catch that. Could you say it again?"
    if len(heard) > 120:
        heard = heard[:120].rsplit(" ", 1)[0] + "…"
    return (f"I'm not sure I heard that right — I got “{heard}”. "
            "Could you say it again?")


def audio_seconds(pcm: bytes, sample_rate: int = PCM_SAMPLE_RATE) -> float:
    return len(pcm) / 2 / sample_rate if sample_rate else 0.0


def rms(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return float(math.sqrt(float(np.mean(samples * samples)))) if samples.size else 0.0
