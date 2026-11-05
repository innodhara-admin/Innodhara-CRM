"""Voice mode — talk to the assistant and hear it answer.

Three ways in, one assistant behind them (`orchestrator.handle_command`, the
same router, agents, tools, question cards and approvals as typed commands):

  WS   /api/v1/assistant/voice        streaming, hands-free session
  POST /api/v1/assistant/voice/turn   one recorded clip in, one answer out
  POST /api/v1/assistant/voice/speak  text in, the server's voice out (WAV)
  GET  /api/v1/assistant/voice/config what this server supports right now

The WebSocket needs the reverse proxy to pass `Upgrade` headers; the HTTP turn
works through any proxy. The full protocol, for the app, is in
docs/JARVIS_VOICE_AND_CLIENT_CREATION_ANDROID.md.

Rules that hold on every path (see app/ai/voice.py): a low-confidence
transcript is never acted on; voice audio is transcribed and discarded;
anything outbound still lands in approvals — voice cannot press send.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.ai import client_draft, confirmations, orchestrator, tts, voice
from app.api.deps import UnauthorizedError, get_org_context, org_context_for_token
from app.config import get_settings
from app.core.context import OrgContext
from app.core.exceptions import (
    AppError,
    BudgetExceededError,
    ExternalServiceError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.database import SessionLocal, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant/voice", tags=["voice"])

PROTOCOL_VERSION = 1
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONTEXT_KEYS = ("lead_id", "proposal_id", "meeting_id")
_MAX_CLIP_BYTES = 10 * 1024 * 1024
_MAX_TEXT = 4000
_START_TIMEOUT_S = 15
_AUDIO_CHUNK_BYTES = 4_800  # 100 ms of 24 kHz PCM per binary frame

# WebSocket close codes (4000-4999 are the application's own).
CLOSE_BAD_REQUEST = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_IDLE = 4408


class _Unavailable(AppError):
    status_code = 503


def _require_enabled() -> None:
    if not get_settings().voice_mode_enabled:
        raise _Unavailable("Voice mode is switched off on this server.")


def _error_code(exc: AppError) -> str:
    if isinstance(exc, UnauthorizedError):
        return "unauthorized"
    if isinstance(exc, PermissionDeniedError):
        return "forbidden"
    if isinstance(exc, BudgetExceededError):
        return "budget_exceeded"
    if isinstance(exc, ExternalServiceError):
        return "service_unavailable"
    if isinstance(exc, ValidationFailedError):
        return "invalid"
    return "error"


def _reply_payload(result: Any, session_id: str | None) -> dict[str, Any]:
    """The /assistant/command response, plus what voice mode speaks."""
    return {
        "agent": result.agent,
        "reply": result.reply,
        "speech": getattr(result, "speech", None) or voice.speakable(result.reply),
        "actions": result.actions,
        "pending_approvals": result.pending_approvals,
        "session_id": session_id,
    }


def _not_acted_payload(heard: str, session_id: str | None) -> dict[str, Any]:
    reply = voice.not_understood_reply(heard)
    return {
        "agent": "voice",
        "reply": reply,
        "speech": reply,
        "actions": [],
        "pending_approvals": [],
        "session_id": session_id,
    }


async def _confident_enough(
    db: AsyncSession, ctx: OrgContext, heard: Any, session_id: str | None
) -> bool:
    """May this transcript be acted on?

    The 0.6 gate, with one exception: while a conversation is held open in
    this chat (a client being built up), a reply may clear
    VOICE_CONFIRMATION_MIN_CONFIDENCE instead. Whisper scores short replies
    ("Yes.", "Skip this.", "Pune.") low however clearly they were said (see
    config.py), and nothing in such a conversation is created until the whole
    record has been read back and the person says to create it."""
    if not heard.low_confidence:
        return True
    if heard.confidence < get_settings().voice_confirmation_min_confidence:
        return False
    return await confirmations.has_pending(db, ctx, session_id)


def _clean_context(values: dict[str, Any]) -> dict[str, str]:
    context: dict[str, str] = {}
    for key in _CONTEXT_KEYS:
        value = values.get(key)
        if isinstance(value, str) and _ID_RE.match(value):
            context[key] = value
    return context


# ══════════════════════════ Capabilities ════════════════════════════════════
@router.get("/config")
async def voice_config(ctx: OrgContext = Depends(get_org_context)):
    """What voice mode can do on this server right now, so the app can decide
    between the streaming session, the one-clip turn and its own voice."""
    s = get_settings()
    return {
        "enabled": s.voice_mode_enabled,
        "protocol_version": PROTOCOL_VERSION,
        "stt": {"provider": s.stt_provider, "model": s.voice_stt_model},
        "tts": tts.status(),
        "stream_input": {"format": voice.PCM_FORMAT,
                         "sample_rate": voice.PCM_SAMPLE_RATE, "channels": 1},
        "clip_formats": sorted(voice.CLIP_FORMATS),
        "end_of_turn_silence_ms": s.voice_vad_silence_ms,
        "max_utterance_seconds": s.voice_max_utterance_seconds,
        "barge_in": s.voice_barge_in,
        "confirmation_ttl_seconds": s.assistant_confirmation_ttl_seconds,
        # Voices a session may pick (start/voice messages, the `voice` field).
        "voices": list(tts.VOICES),
        "default_voice": s.voice_tts_voice,
    }


# ══════════════════════════ Server voice ════════════════════════════════════
class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    # One of /config's `voices`; anything else speaks in the default voice.
    voice: str | None = Field(default=None, max_length=32)


@router.post("/speak")
async def speak(body: SpeakRequest, ctx: OrgContext = Depends(get_org_context)):
    """Say `text` in the server's voice, as a WAV file."""
    _require_enabled()
    speech = await tts.synthesize(voice.speakable(body.text, limit=2000), voice=body.voice)
    if speech is None:
        raise _Unavailable(
            "The server voice is not available: "
            + (tts.status().get("error") or "no speech was produced")
        )
    return Response(content=tts.wav_bytes(speech), media_type="audio/wav")


# ══════════════════════════ One clip, one answer ════════════════════════════
@router.post("/turn")
async def voice_turn(
    file: UploadFile = File(...),
    session_id: str = Form(..., min_length=8, max_length=64,
                           pattern=r"^[A-Za-z0-9_-]+$"),
    lead_id: str | None = Form(default=None),
    proposal_id: str | None = Form(default=None),
    meeting_id: str | None = Form(default=None),
    speak_reply: bool = Form(default=True, alias="speak"),
    voice_name: str | None = Form(default=None, alias="voice", max_length=32),
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """A recorded utterance → transcript → the assistant → its answer, with
    the answer spoken as base64 WAV when the server has a voice.

    Works through any HTTP proxy. The session id is required: voice turns are
    always a conversation, and a read-back needs a next turn to be agreed in.
    """
    _require_enabled()
    audio = await file.read()
    if not audio:
        raise ValidationFailedError("Empty audio file")
    if len(audio) > _MAX_CLIP_BYTES:
        raise ValidationFailedError("Voice clip too large (max 10 MB)")

    hint = await client_draft.vocabulary_hint(db, ctx, session_id)
    heard = await voice.transcribe_clip(audio, file.content_type or "audio/mp4",
                                        prompt=hint)
    body: dict[str, Any] = {
        "transcript": heard.text,
        "language": heard.language,
        "confidence": heard.confidence,
        "low_confidence": heard.low_confidence,
    }
    if not heard.text.strip() or not await _confident_enough(db, ctx, heard, session_id):
        body.update(acted=False, **_not_acted_payload(heard.text, session_id))
    else:
        result = await orchestrator.handle_command(
            db, ctx, heard.text,
            context={**_clean_context({"lead_id": lead_id, "proposal_id": proposal_id,
                                       "meeting_id": meeting_id}),
                     "_voice_confidence": heard.confidence},
            session_id=session_id,
        )
        await db.commit()
        body.update(acted=True, **_reply_payload(result, session_id))

    body["audio"] = None
    if speak_reply:
        speech = await tts.synthesize(body["speech"], voice=voice_name)
        if speech is not None:
            body["audio"] = {
                "format": "wav",
                "sample_rate": speech.sample_rate,
                "base64": base64.b64encode(tts.wav_bytes(speech)).decode("ascii"),
            }
    body["spoken_by"] = "server" if body["audio"] else "device"
    return body


# ══════════════════════════ Streaming session ═══════════════════════════════
@router.websocket("")
async def voice_session(websocket: WebSocket):
    await websocket.accept()
    await _VoiceSession(websocket).run()


class _Closed(Exception):
    """The socket is gone; stop quietly."""


class _VoiceSession:
    """One hands-free conversation over one WebSocket.

    Three tasks: the receive loop (audio, control messages, end-of-turn
    detection), the turn worker (transcribe → assistant → reply, one turn at a
    time and in order) and the speaker (server voice, sentence by sentence,
    stoppable). Interrupting stops speech only — a turn already carried out is
    never silently undone.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self.ws = websocket
        self.settings = get_settings()
        self.token: str | None = None
        self.session_id: str = ""
        self.context: dict[str, str] = {}
        self.input_format = voice.PCM_FORMAT
        self.server_vad = True
        self.want_voice = True
        self.barge_in = self.settings.voice_barge_in
        # The server voice this session speaks with (None = VOICE_TTS_VOICE).
        self.voice: str | None = None
        self.detector = voice.detector_from_settings()
        self.clip = bytearray()
        self.turns: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self.speech: asyncio.Queue[tuple[int, str, str]] = asyncio.Queue()
        self.turn_no = 0
        self.silenced_through = 0
        self.speaking: int | None = None
        self.send_lock = asyncio.Lock()
        self.closed = False
        self.tasks: list[asyncio.Task] = []

    # ── plumbing ────────────────────────────────────────────────────────────
    async def send(self, message: dict[str, Any]) -> None:
        if self.closed:
            raise _Closed()
        try:
            async with self.send_lock:
                await self.ws.send_text(json.dumps(message, default=str))
        except Exception as exc:  # noqa: BLE001 — any send failure = gone
            self.closed = True
            raise _Closed() from exc

    async def send_audio(self, data: bytes) -> None:
        if self.closed:
            raise _Closed()
        try:
            async with self.send_lock:
                await self.ws.send_bytes(data)
        except Exception as exc:  # noqa: BLE001
            self.closed = True
            raise _Closed() from exc

    async def close(self, code: int, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if (self.ws.application_state != WebSocketState.DISCONNECTED
                    and self.ws.client_state != WebSocketState.DISCONNECTED):
                await self.ws.close(code=code, reason=reason[:120])
        except Exception:  # noqa: BLE001
            pass

    async def fail(self, code: int, error: str, message: str) -> None:
        try:
            await self.send({"type": "error", "code": error, "message": message,
                             "fatal": True})
        except _Closed:
            return
        await self.close(code, message)

    # ── lifecycle ───────────────────────────────────────────────────────────
    async def run(self) -> None:
        try:
            if not self.settings.voice_mode_enabled:
                await self.fail(CLOSE_FORBIDDEN, "disabled",
                                "Voice mode is switched off on this server.")
                return
            if not await self._start():
                return
            self.tasks = [asyncio.create_task(self._turn_worker()),
                          asyncio.create_task(self._speaker())]
            await self._receive_loop()
        except (_Closed, WebSocketDisconnect):
            pass
        except Exception:  # noqa: BLE001 — never leak a traceback to the socket
            logger.exception("Voice session failed")
            await self.fail(1011, "internal", "Voice mode hit an unexpected error.")
        finally:
            self.closed = True
            for task in self.tasks:
                task.cancel()
            for task in self.tasks:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            await self.close(1000)

    async def _start(self) -> bool:
        try:
            raw = await asyncio.wait_for(self.ws.receive_text(), _START_TIMEOUT_S)
            start = json.loads(raw)
        except asyncio.TimeoutError:
            await self.fail(CLOSE_BAD_REQUEST, "no_start",
                            "Send a start message first.")
            return False
        except (ValueError, KeyError, RuntimeError):
            await self.fail(CLOSE_BAD_REQUEST, "bad_start",
                            "The first message must be a JSON start message.")
            return False
        if not isinstance(start, dict) or start.get("type") != "start":
            await self.fail(CLOSE_BAD_REQUEST, "bad_start",
                            "The first message must be {\"type\": \"start\", ...}.")
            return False

        header = self.ws.headers.get("authorization") or ""
        self.token = (header[7:].strip() if header.lower().startswith("bearer ")
                      else None) or start.get("token")
        try:
            async with SessionLocal() as db:
                await org_context_for_token(db, self.token)
        except UnauthorizedError as exc:
            await self.fail(CLOSE_UNAUTHORIZED, "unauthorized", exc.message)
            return False
        except PermissionDeniedError as exc:
            await self.fail(CLOSE_FORBIDDEN, "forbidden", exc.message)
            return False

        session_id = start.get("session_id")
        if not isinstance(session_id, str) or not _SESSION_RE.match(session_id):
            await self.fail(CLOSE_BAD_REQUEST, "bad_session",
                            "session_id is required: 8-64 letters, digits, _ or -.")
            return False
        self.session_id = session_id
        self.context = _clean_context(start)

        fmt = str(start.get("format") or voice.PCM_FORMAT).lower()
        if fmt == voice.PCM_FORMAT:
            rate = start.get("sample_rate", voice.PCM_SAMPLE_RATE)
            if rate != voice.PCM_SAMPLE_RATE:
                await self.fail(CLOSE_BAD_REQUEST, "bad_format",
                                "Streamed PCM must be 16000 Hz mono s16le.")
                return False
        elif fmt not in voice.CLIP_FORMATS:
            await self.fail(CLOSE_BAD_REQUEST, "bad_format",
                            f"Unsupported audio format '{fmt}'.")
            return False
        self.input_format = fmt
        # Server end-of-turn detection only works on PCM it can read as it
        # arrives; a container clip ends when the phone says so.
        self.server_vad = fmt == voice.PCM_FORMAT and start.get("vad", "server") != "client"
        self.want_voice = bool(start.get("server_voice", True))
        self.voice = tts.resolve_voice(start.get("voice"))
        if "barge_in" in start:
            self.barge_in = bool(start["barge_in"]) and self.settings.voice_barge_in

        # Load models in the background: the session is usable at once, the
        # first turn simply waits for the speech model if it is still loading.
        asyncio.create_task(self._warm())
        await self.send({
            "type": "ready",
            "protocol_version": PROTOCOL_VERSION,
            "session_id": self.session_id,
            "input": {"format": self.input_format,
                      "sample_rate": voice.PCM_SAMPLE_RATE
                      if self.input_format == voice.PCM_FORMAT else None,
                      "end_of_turn": "server" if self.server_vad else "client"},
            "server_voice": {**tts.status(), "requested": self.want_voice,
                             "format": voice.PCM_FORMAT},
            "barge_in": self.barge_in,
            "voice": self.voice or self.settings.voice_tts_voice,
            "end_of_turn_silence_ms": self.settings.voice_vad_silence_ms,
            "max_utterance_seconds": self.settings.voice_max_utterance_seconds,
        })
        return True

    async def _warm(self) -> None:
        try:
            await voice.warm_stt()
        except Exception as exc:  # noqa: BLE001 — the turn will report it
            logger.warning("Voice mode: speech model did not warm (%s)", exc)
        if self.want_voice:
            ready = await tts.warm()
            try:
                await self.send({"type": "server_voice", **tts.status(),
                                 "ready": ready})
            except _Closed:
                pass

    # ── receiving ───────────────────────────────────────────────────────────
    async def _receive_loop(self) -> None:
        idle = max(self.settings.voice_idle_timeout_seconds, 5)
        while not self.closed:
            try:
                message = await asyncio.wait_for(self.ws.receive(), idle)
            except asyncio.TimeoutError:
                await self.fail(CLOSE_IDLE, "idle", "Closed after a long silence.")
                return
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await self._on_audio(message["bytes"])
            elif message.get("text") is not None:
                if await self._on_control(message["text"]) is False:
                    return

    async def _on_audio(self, data: bytes) -> None:
        if not self.server_vad:
            if len(self.clip) + len(data) > _MAX_CLIP_BYTES:
                self.clip.clear()
                await self.send({"type": "error", "code": "too_long",
                                 "message": "That was too long to process — "
                                            "try a shorter request.",
                                 "fatal": False})
                return
            self.clip.extend(data)
            return
        for event, utterance in self.detector.feed(data):
            if event == "speech_start":
                # Also drops speech still queued, not only what is playing:
                # the person has started a new request.
                if self.barge_in:
                    await self._interrupt("barge_in")
                await self.send({"type": "speech_started"})
            elif event == "speech_end" and utterance:
                await self.send({"type": "speech_ended",
                                 "seconds": round(voice.audio_seconds(utterance), 2)})
                self.turns.put_nowait(("pcm", utterance))
            elif event == "noise":
                await self.send({"type": "listening"})

    async def _on_control(self, raw: str) -> bool | None:
        try:
            message = json.loads(raw)
            kind = message.get("type")
        except (ValueError, AttributeError):
            await self.send({"type": "error", "code": "bad_message",
                             "message": "Messages must be JSON objects.",
                             "fatal": False})
            return None
        if kind == "end_of_speech":
            if self.server_vad:
                utterance = self.detector.flush()
                if utterance:
                    self.turns.put_nowait(("pcm", utterance))
            elif self.clip:
                self.turns.put_nowait(("clip", bytes(self.clip)))
                self.clip.clear()
        elif kind == "cancel":
            self.detector.reset()
            self.clip.clear()
        elif kind == "text":
            text = message.get("text")
            if isinstance(text, str) and 0 < len(text.strip()) <= _MAX_TEXT:
                if self.barge_in and self.speaking is not None:
                    await self._interrupt("new_request")
                self.turns.put_nowait(("text", text.strip()))
            else:
                await self.send({"type": "error", "code": "bad_text",
                                 "message": f"text must be 1-{_MAX_TEXT} characters.",
                                 "fatal": False})
        elif kind == "interrupt":
            await self._interrupt("client")
        elif kind == "context":
            self.context = _clean_context(message)
            await self.send({"type": "context", **self.context})
        elif kind == "voice":
            # Speak with another voice from the next sentence on.
            chosen = tts.resolve_voice(message.get("voice"))
            if chosen is None and message.get("voice") is not None:
                await self.send({"type": "error", "code": "bad_voice",
                                 "message": "Unknown voice.", "fatal": False})
            else:
                self.voice = chosen
                await self.send({"type": "voice",
                                 "voice": chosen or self.settings.voice_tts_voice})
        elif kind == "ping":
            await self.send({"type": "pong"})
        elif kind == "stop":
            return False
        else:
            await self.send({"type": "error", "code": "unknown_message",
                             "message": f"Unknown message type '{kind}'.",
                             "fatal": False})
        return None

    async def _interrupt(self, reason: str) -> None:
        """Stop speaking now and drop anything queued to be said so far."""
        self.silenced_through = self.turn_no
        if self.speaking is not None:
            await self.send({"type": "interrupted", "turn": self.speaking,
                             "reason": reason})

    # ── turns ───────────────────────────────────────────────────────────────
    async def _turn_worker(self) -> None:
        while not self.closed:
            kind, data = await self.turns.get()
            self.turn_no += 1
            try:
                await self._run_turn(self.turn_no, kind, data)
            except _Closed:
                return
            except Exception:  # noqa: BLE001 — one bad turn must not end the session
                logger.exception("Voice turn failed")
                await self.send({"type": "error", "turn": self.turn_no,
                                 "code": "internal",
                                 "message": "Something went wrong with that request.",
                                 "fatal": False})

    async def _run_turn(self, turn: int, kind: str, data: Any) -> None:
        transcript: str | None = None
        heard = None
        if kind == "text":
            text = data
        else:
            await self.send({"type": "transcribing", "turn": turn})
            try:
                hint = await self._vocabulary()
                if kind == "pcm":
                    heard = await voice.transcribe_utterance(data, prompt=hint)
                else:
                    heard = await voice.transcribe_clip(data, self.input_format,
                                                        prompt=hint)
            except AppError as exc:
                await self._report(turn, exc, "I couldn't process that audio just now.")
                return
            await self.send({"type": "transcript", "turn": turn, "text": heard.text,
                             "language": heard.language,
                             "confidence": heard.confidence,
                             "low_confidence": heard.low_confidence})
            if not heard.text.strip():
                await self.send({"type": "listening", "turn": turn})
                return
            text = transcript = heard.text

        async with SessionLocal() as db:
            try:
                ctx = await org_context_for_token(db, self.token)
            except UnauthorizedError as exc:
                await self.fail(CLOSE_UNAUTHORIZED, "unauthorized", exc.message)
                raise _Closed() from exc
            except PermissionDeniedError as exc:
                await self.fail(CLOSE_FORBIDDEN, "forbidden", exc.message)
                raise _Closed() from exc

            if heard is not None and not await _confident_enough(
                db, ctx, heard, self.session_id
            ):
                payload = _not_acted_payload(heard.text, self.session_id)
                await self._deliver(turn, {"acted": False, "transcript": heard.text,
                                           **payload})
                return

            async def on_routed(agent: str) -> None:
                said = voice.acknowledgement(agent)
                await self.send({"type": "thinking", "turn": turn, "agent": agent,
                                 "text": said})
                self._say(turn, "ack", said)

            try:
                result = await orchestrator.handle_command(
                    db, ctx, text,
                    # `_voice_confidence` (spoken turns only) lets a flow spell
                    # back what was heard with doubt; it never reaches a prompt.
                    context={**self.context,
                             **({"_voice_confidence": heard.confidence}
                                if heard is not None else {})},
                    session_id=self.session_id, on_routed=on_routed,
                )
                await db.commit()
            except AppError as exc:
                await db.rollback()
                await self._report(turn, exc, exc.message)
                return
        await self._deliver(turn, {"acted": True, "transcript": transcript,
                                   **_reply_payload(result, self.session_id)})

    async def _vocabulary(self) -> str | None:
        """Words Whisper should expect. Best-effort: a failure here only costs
        the hint, and an auth problem is reported by the turn itself."""
        try:
            async with SessionLocal() as db:
                ctx = await org_context_for_token(db, self.token)
                return await client_draft.vocabulary_hint(db, ctx, self.session_id)
        except Exception:  # noqa: BLE001
            return None

    async def _deliver(self, turn: int, payload: dict[str, Any]) -> None:
        # A newer request already waiting means this answer is stale to hear
        # (its cards still arrive): the person has moved on.
        will_speak = self._can_speak() and self.turns.empty() \
            and turn > self.silenced_through
        await self.send({"type": "reply", "turn": turn,
                         "spoken_by": "server" if will_speak else "device",
                         **payload})
        if will_speak:
            self._say(turn, "reply", payload["speech"])

    async def _report(self, turn: int, exc: AppError, spoken: str) -> None:
        await self.send({"type": "error", "turn": turn, "code": _error_code(exc),
                         "message": exc.message, "fatal": False})
        self._say(turn, "error", voice.speakable(spoken))

    # ── speaking ────────────────────────────────────────────────────────────
    def _can_speak(self) -> bool:
        return self.want_voice and tts.is_ready()

    def _say(self, turn: int, kind: str, text: str) -> None:
        if text and self._can_speak():
            self.speech.put_nowait((turn, kind, text))

    async def _speaker(self) -> None:
        while not self.closed:
            turn, kind, text = await self.speech.get()
            if turn <= self.silenced_through:
                continue
            speech = None
            parts = voice.sentences(text) or [text]
            self.speaking = turn
            started = False
            interrupted = False
            try:
                for part in parts:
                    if turn <= self.silenced_through:
                        interrupted = True
                        break
                    speech = await tts.synthesize(part, voice=self.voice)
                    if speech is None:
                        break
                    if not started:
                        await self.send({"type": "speak_start", "turn": turn,
                                         "kind": kind, "text": text,
                                         "format": voice.PCM_FORMAT,
                                         "sample_rate": speech.sample_rate})
                        started = True
                    for offset in range(0, len(speech.pcm), _AUDIO_CHUNK_BYTES):
                        if turn <= self.silenced_through:
                            interrupted = True
                            break
                        await self.send_audio(speech.pcm[offset:offset + _AUDIO_CHUNK_BYTES])
                    if interrupted:
                        break
            except _Closed:
                return
            except Exception:  # noqa: BLE001 — a voice failure must not end the session
                logger.exception("Voice mode: speaking failed")
            finally:
                self.speaking = None
            if started:
                await self.send({"type": "speak_end", "turn": turn, "kind": kind,
                                 "interrupted": interrupted})
