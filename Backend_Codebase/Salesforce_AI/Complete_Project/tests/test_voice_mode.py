"""Voice mode: end of turn, the spoken reply, and both voice endpoints.

Speech models are faked — these tests never load Whisper or Kokoro (and so
never download a model). The WebSocket is driven in-process through the ASGI
interface, on the same event loop and database as the rest of the suite.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid

import numpy as np
import pytest

from app.ai import llm as llm_mod
from app.ai import stt, tts, voice
from app.ai.agents import base as agent_base
from app.ai.llm import LlmResponse, ToolCall
from app.config import get_settings
from app.main import app
from tests.conftest import auth, create_org, login

pytestmark = pytest.mark.asyncio

API = "/api/v1"
WS_PATH = f"{API}/assistant/voice"


# ── fakes ────────────────────────────────────────────────────────────────────


class FakeModelLayer:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0) if self.script else LlmResponse(text="Done.")

    async def generate_json(self, **kwargs):
        return llm_mod.extract_json((await self.generate(**kwargs)).text)


class FakeVoice:
    name = "fake"
    sample_rate = 24_000

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.spoken: list[str] = []
        self.voices: list[str | None] = []

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        if self.delay:
            time.sleep(self.delay)
        self.spoken.append(text)
        self.voices.append(voice)
        return b"\x01\x00" * 12_000  # half a second


@pytest.fixture(scope="module")
async def org(client, super_token):
    """This module's own organisation, with one sales agent — kept apart so
    the people these tests add never reach another module's fixtures."""
    org = await create_org(client, super_token, name="Voice Mode Org",
                           slug="voice-mode", domain="voicemode-example.com")
    org["agent_token"] = (await _agent(client, org))["token"]
    return org


@pytest.fixture
def fake_model(monkeypatch):
    def _install(script):
        fake = FakeModelLayer(script)
        monkeypatch.setattr(agent_base, "get_model_layer", lambda: fake)
        monkeypatch.setattr("app.ai.orchestrator.get_model_layer", lambda: fake)
        monkeypatch.setattr("app.ai.client_draft.get_model_layer", lambda: fake)
        return fake

    return _install


@pytest.fixture
def heard(monkeypatch):
    """Replace speech recognition; returns a setter for what is 'heard'."""
    state = {"text": "", "confidence": 0.9, "audio": [], "prompts": []}

    async def fake_transcribe(audio, *args, **kwargs):
        state["audio"].append(audio)
        state["prompts"].append(kwargs.get("prompt"))
        return stt.TranscriptionResult(text=state["text"], language="en",
                                       confidence=state["confidence"])

    async def no_warm():
        return None

    monkeypatch.setattr(voice, "transcribe_utterance", fake_transcribe)
    monkeypatch.setattr(voice, "transcribe_clip", fake_transcribe)
    monkeypatch.setattr(voice, "warm_stt", no_warm)

    def _set(text: str, confidence: float = 0.9):
        state["text"], state["confidence"] = text, confidence
        return state

    return _set


@pytest.fixture
def server_voice():
    engine = FakeVoice()
    tts.install_engine_for_tests(engine)
    yield engine
    tts.install_engine_for_tests(None)


@pytest.fixture
def no_server_voice(monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_tts_engine", "off")
    tts.install_engine_for_tests(None)
    yield
    tts.install_engine_for_tests(None)


def tone(seconds: float, amplitude: float = 0.3) -> bytes:
    t = np.arange(int(seconds * 16_000)) / 16_000
    return (np.sin(2 * np.pi * 220 * t) * amplitude * 32767).astype("<i2").tobytes()


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * 16_000)


def _hex():
    return uuid.uuid4().hex[:8]


async def _agent(client, org) -> dict:
    email = f"voice{_hex()}@voicemode-example.com"
    created = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                                json={"email": email, "name": f"Voice {_hex()}",
                                      "role": "sales_agent"})
    assert created.status_code == 200, created.text
    token = (await login(client, email, created.json()["temp_password"]))["access_token"]
    return {"id": created.json()["id"], "token": token}


# ── an in-process WebSocket client ───────────────────────────────────────────


class WsClient:
    def __init__(self, headers: dict[str, str] | None = None):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.outbox: asyncio.Queue = asyncio.Queue()
        self.events: list[dict] = []
        self.audio_bytes = 0
        self.close_code = None
        scope = {
            "type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws",
            "path": WS_PATH, "raw_path": WS_PATH.encode(), "query_string": b"",
            "root_path": "", "server": ("test", 80), "client": ("127.0.0.1", 5000),
            "subprotocols": [], "extensions": {},
            "headers": [(k.lower().encode(), v.encode())
                        for k, v in (headers or {}).items()],
        }
        self.task = asyncio.create_task(app(scope, self.inbox.get, self.outbox.put))

    async def connect(self):
        await self.inbox.put({"type": "websocket.connect"})
        message = await asyncio.wait_for(self.outbox.get(), 5)
        assert message["type"] == "websocket.accept", message

    async def send_json(self, data):
        await self.inbox.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def send_bytes(self, data: bytes, chunk: int = 640):
        for i in range(0, len(data), chunk):
            await self.inbox.put({"type": "websocket.receive", "bytes": data[i:i + chunk]})

    async def next_event(self, timeout: float = 10) -> dict:
        while True:
            message = await asyncio.wait_for(self.outbox.get(), timeout)
            if message["type"] == "websocket.close":
                self.close_code = message.get("code")
                event = {"type": "__closed__", "code": self.close_code}
                self.events.append(event)
                return event
            if message.get("bytes") is not None:
                self.audio_bytes += len(message["bytes"])
                continue
            event = json.loads(message["text"])
            self.events.append(event)
            return event

    async def wait_for(self, predicate, timeout: float = 10) -> dict:
        while True:
            event = await self.next_event(timeout)
            if predicate(event):
                return event
            if event["type"] == "__closed__":
                raise AssertionError(f"closed ({self.close_code}); saw {self.events}")

    async def disconnect(self):
        await self.inbox.put({"type": "websocket.disconnect", "code": 1000})
        try:
            await asyncio.wait_for(self.task, 10)
        except asyncio.TimeoutError:
            self.task.cancel()


async def _open(token: str | None, **start) -> WsClient:
    ws = WsClient(headers={"authorization": f"Bearer {token}"} if token else None)
    await ws.connect()
    await ws.send_json({"type": "start", "session_id": f"voicesess{uuid.uuid4().hex}",
                        **start})
    return ws


# ── end of turn ──────────────────────────────────────────────────────────────


def _detector(**kw):
    return voice.EndOfTurnDetector(silence_ms=600, min_speech_ms=200,
                                   max_utterance_ms=kw.pop("max_ms", 5000), **kw)


def _feed_in_pieces(detector, data, piece=333):
    events = []
    for i in range(0, len(data), piece):
        events += detector.feed(data[i:i + piece])
    return events


async def test_silence_is_not_speech():
    assert _feed_in_pieces(_detector(), silence(2.0)) == []


async def test_speech_ends_after_the_silence_window():
    detector = _detector()
    events = _feed_in_pieces(detector, silence(0.5) + tone(1.0) + silence(0.5))
    assert [e for e, _ in events] == ["speech_start"]  # 0.5 s of quiet is not the end
    events = _feed_in_pieces(detector, silence(0.2))
    assert [e for e, _ in events] == ["speech_end"]
    utterance = events[0][1]
    # pre-roll + the speech + the 600 ms that ended it
    assert 1.5 <= voice.audio_seconds(utterance) <= 2.0


async def test_a_blip_is_noise_not_a_turn():
    events = _feed_in_pieces(_detector(), tone(0.1) + silence(1.0))
    assert [e for e, _ in events] == ["speech_start", "noise"]


async def test_a_long_utterance_is_cut_at_the_limit():
    events = _feed_in_pieces(_detector(max_ms=2000), tone(3.0))
    # Cut at the cap, and the speech that carries on starts the next utterance.
    assert [e for e, _ in events] == ["speech_start", "speech_end", "speech_start"]
    assert voice.audio_seconds(events[1][1]) <= 2.05


async def test_flush_ends_the_utterance_on_request():
    detector = _detector()
    _feed_in_pieces(detector, tone(0.8))
    assert detector.in_speech
    assert voice.audio_seconds(detector.flush()) >= 0.8
    assert detector.flush() is None


async def test_steady_background_hum_raises_the_bar():
    detector = _detector()
    hum = tone(2.0, amplitude=0.01)  # below the floor: learnt as background
    assert _feed_in_pieces(detector, hum) == []
    events = _feed_in_pieces(detector, tone(0.6, amplitude=0.3) + silence(0.8))
    assert [e for e, _ in events] == ["speech_start", "speech_end"]


async def test_a_short_yes_is_a_turn_with_the_default_settings():
    # Measured 2026-09-17: a clearly spoken "Yes." on the phone held 280 ms of
    # sound, and the old 300 ms minimum dropped it without a word.
    events = _feed_in_pieces(voice.detector_from_settings(), silence(0.5) + tone(0.28)
                             + silence(1.3))
    assert [e for e, _ in events] == ["speech_start", "speech_end"]
    events = _feed_in_pieces(voice.detector_from_settings(), tone(0.1) + silence(1.3))
    assert [e for e, _ in events] == ["speech_start", "noise"]


# ── speech recognition (Whisper itself is never loaded) ──────────────────────


async def test_voice_turns_use_the_voice_model_and_languages(monkeypatch):
    calls = []

    async def fake_pcm16(pcm, **kwargs):
        calls.append(("pcm", kwargs))
        return stt.TranscriptionResult(text="yes", language="en", confidence=0.9)

    async def fake_clip(audio, mime, **kwargs):
        calls.append(("clip", kwargs))
        return stt.TranscriptionResult(text="yes", language="en", confidence=0.9)

    monkeypatch.setattr(stt, "transcribe_pcm16", fake_pcm16)
    monkeypatch.setattr(stt, "transcribe", fake_clip)
    monkeypatch.setattr(get_settings(), "voice_stt_languages", " en, HI ,kn,en ")
    await voice.transcribe_utterance(silence(0.5), prompt="Priya Nair.")
    await voice.transcribe_clip(b"clip", "audio/mp4", prompt="Priya Nair.")
    model = get_settings().voice_stt_model
    for _kind, kwargs in calls:
        assert kwargs == {"model": model, "prompt": "Priya Nair.",
                          "languages": ("en", "hi", "kn")}
    monkeypatch.setattr(get_settings(), "voice_stt_languages", "")
    assert voice.stt_languages() == ()


async def test_the_voice_defaults_are_the_measured_ones():
    fields = type(get_settings()).model_fields  # declared defaults, not .env
    assert fields["voice_stt_model"].default == "large-v3"
    assert fields["voice_stt_languages"].default == "en,hi,kn"
    assert fields["voice_min_utterance_ms"].default == 150
    assert fields["whisper_fp16_weights"].default is True


class _FakeWhisper:
    """Just enough of a Whisper model for the helpers around transcribe()."""

    def __init__(self, probs=None):
        import torch

        self.device = torch.device("cpu")
        self.dims = type("Dims", (), {"n_mels": 80, "n_text_ctx": 448})()
        self.is_multilingual = True
        self.num_languages = 100
        self.probs = probs or {}
        self.mels = []

    def detect_language(self, mel):
        self.mels.append(mel)
        return None, self.probs


async def test_detection_chooses_only_among_the_allowed_languages():
    # large-v3 hears Hindi as Urdu: Urdu may be likeliest, but is not allowed.
    model = _FakeWhisper({"ur": 0.6, "hi": 0.3, "en": 0.1})
    samples = np.zeros(16_000, dtype=np.float32)
    assert stt._pick_language(model, samples, ("en", "hi", "kn")) == "hi"
    assert len(model.mels) == 1
    assert stt._pick_language(model, samples, ("en",)) == "en"
    assert stt._pick_language(model, samples, ()) is None
    assert len(model.mels) == 1  # no detection needed for those two


async def test_a_long_hint_is_cut_from_the_end_not_the_start():
    import whisper

    model = _FakeWhisper()
    tokenizer = whisper.tokenizer.get_tokenizer(True, num_languages=100)
    short = "Priya Nair, Rahul Reddy."
    assert stt._fit_prompt(model, short) == short
    long = ("Priya Nair, Rahul Reddy. Cities: "
            + ", ".join(f"Tumakuru{i}" for i in range(200)) + ".")
    fitted = stt._fit_prompt(model, long)
    assert fitted.startswith("Priya Nair, Rahul Reddy. Cities: Tumakuru0, ")
    assert fitted.endswith(".") and not fitted.endswith(",.")
    assert len(tokenizer.encode(" " + fitted)) <= 448 // 2 - 1
    assert stt._fit_prompt(model, None) is None


async def test_halved_weights_keep_layer_norms_in_float32():
    import torch
    from whisper.model import Conv1d, LayerNorm, Linear

    model = torch.nn.Sequential(Conv1d(4, 4, 3), Linear(4, 4), LayerNorm(4))
    stt._halve_weights(model)
    assert model[0].weight.dtype == torch.float16
    assert model[1].weight.dtype == torch.float16
    assert model[2].weight.dtype == torch.float32
    # A float32 input still runs: the layers cast the weights to the input.
    out = model[2](model[1](torch.ones(1, 4)))
    assert out.dtype == torch.float32


async def test_whisper_filling_a_silence_is_not_a_command():
    """21 Sep 2026: "Thank you for watching." arrived in the chat as if the
    user had typed it. It is what Whisper says when a clip holds no speech —
    and it says it confidently, so the 0.6 gate never saw it."""
    phantom = [{"no_speech_prob": 0.55, "avg_logprob": -0.4}]
    assert stt._heard_or_nothing("Thank you for watching.", phantom) == ""
    assert stt._heard_or_nothing("Thanks for watching!", phantom) == ""
    # Breath and room noise: every segment doubts there was speech at all.
    noise = [{"no_speech_prob": 0.9, "avg_logprob": -1.4}]
    assert stt._heard_or_nothing("Thank you.", noise) == ""


async def test_words_someone_really_said_are_left_alone():
    """The other half: a clip with speech in it keeps every word, including a
    genuine thank-you and anything a phantom phrase merely resembles."""
    spoken = [{"no_speech_prob": 0.02, "avg_logprob": -0.3}]
    for text in ("Thank you for watching.", "Thank you.", "Create a lead named Zenith",
                 "Yes.", "Thank you for watching the demo with them yesterday."):
        assert stt._heard_or_nothing(text, spoken) == text
    # No segments at all: nothing to judge on, so nothing is thrown away.
    assert stt._heard_or_nothing("Skip this.", []) == "Skip this."


# ── what is spoken ───────────────────────────────────────────────────────────


async def test_speakable_strips_markup_and_links():
    text = "**Done.** See https://example.com/x\n- first item\n- second item"
    assert voice.speakable(text) == "Done. See the link on screen. first item. second item."


async def test_a_phone_number_is_read_out_digit_by_digit():
    """Reported 21 Sep 2026: "contact numbers it is saying is billions,
    millions and thousands". Kokoro reads 9886543210 as a quantity unless the
    digits are separated."""
    assert voice.speakable("Call Priya on 9886543210.") == (
        "Call Priya on 9 8 8 6 5 4 3 2 1 0.")
    # speakable() ends a line with a full stop; the digits are what matter.
    assert voice.speakable("Her number is +91 98865 43210") == (
        "Her number is + 9 1 9 8 8 6 5 4 3 2 1 0.")
    assert voice.speakable("Landline 080-2345-6789.") == (
        "Landline 0 8 0 2 3 4 5 6 7 8 9.")


async def test_quantities_and_years_are_still_read_as_numbers():
    """The other half of the same rule: "5000 students" is a count, and
    reading it "5 0 0 0" would be its own bug."""
    for text in ("5000 students.", "Due on 27 September 2026.", "Room 204.",
                 "It costs 45000 rupees."):
        assert voice.speakable(text) == text


async def test_long_replies_are_cut_at_a_sentence():
    text = " ".join(f"Sentence number {i} is here." for i in range(60))
    spoken = voice.speakable(text)
    assert len(spoken) < 700
    assert spoken.endswith("is here. The rest is on your screen.")


async def test_sentences_merge_short_fragments():
    assert voice.sentences("Done. Nexora is added and you own it. OK.") == [
        "Done. Nexora is added and you own it.", "OK."
    ]


async def test_acknowledgements_cover_every_agent():
    from app.ai.orchestrator import _AGENTS

    for name in _AGENTS:
        assert voice.acknowledgement(name) != "One moment.", name


async def test_wav_bytes_is_a_real_wav():
    wav = tts.wav_bytes(tts.Speech(pcm=b"\x00\x00" * 2400, sample_rate=24_000))
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"


async def test_an_unavailable_engine_degrades_quietly(monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_tts_engine", "no-such-engine")
    tts.install_engine_for_tests(None)
    try:
        assert await tts.synthesize("hello") is None
        status = tts.status()
        assert status["available"] is False and "unknown" in status["error"]
    finally:
        tts.install_engine_for_tests(None)


# ── HTTP endpoints ───────────────────────────────────────────────────────────


async def test_config_needs_a_login_and_describes_the_server(client, org, server_voice):
    assert (await client.get(f"{API}/assistant/voice/config")).status_code == 401
    body = (await client.get(f"{API}/assistant/voice/config",
                             headers=auth(org["agent_token"]))).json()
    assert body["enabled"] is True
    assert body["stream_input"] == {"format": "pcm_s16le", "sample_rate": 16000,
                                    "channels": 1}
    assert body["tts"]["available"] is True


async def test_speak_returns_wav(client, org, server_voice):
    resp = await client.post(f"{API}/assistant/voice/speak",
                             headers=auth(org["agent_token"]), json={"text": "Hello."})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content[:4] == b"RIFF"


async def test_speak_without_a_server_voice_is_503(client, org, no_server_voice):
    resp = await client.post(f"{API}/assistant/voice/speak",
                             headers=auth(org["agent_token"]), json={"text": "Hello."})
    assert resp.status_code == 503


async def test_http_turn_builds_a_client_by_voice(client, org, fake_model, heard,
                                                   server_voice):
    agent = await _agent(client, org)
    name = f"Voiced Co {_hex()}"
    session = f"httpvoice{uuid.uuid4().hex}"

    async def turn(said, *, confidence=0.9, speak="true"):
        heard(said, confidence=confidence)
        resp = await client.post(
            f"{API}/assistant/voice/turn", headers=auth(agent["token"]),
            data={"session_id": session, "speak": speak},
            files={"file": ("a.m4a", b"audio", "audio/mp4")},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    fake_model([LlmResponse(text='{"agent": "client"}'),
                LlmResponse(tool_calls=[ToolCall(name="create_client",
                                                 args={"name": name, "city": "Hubli",
                                                       "owner": "me"})])])
    body = await turn(f"create a lead named {name} in Hubli, I'll own it")
    assert body["acted"] is True and body["agent"] == "client"
    assert body["transcript"] == f"create a lead named {name} in Hubli, I'll own it"
    assert body["reply"] == ("Sure. You'll own it. Do you want to add a source, website "
                             "or notes? They're optional.")
    assert body["speech"] == body["reply"]
    assert body["spoken_by"] == "server"
    assert base64.b64decode(body["audio"]["base64"])[:4] == b"RIFF"

    fake = fake_model([])
    body = await turn("No thanks.")
    assert body["reply"] == (f"Okay. So: {name} in Hubli, owned by you. Anything else, "
                             "or shall I create it?")

    body = await turn("Create it.", speak="false")
    assert fake.calls == []
    assert body["reply"].startswith(f"Done — {name} is added")
    assert body["audio"] is None and body["spoken_by"] == "device"
    lead_id = body["actions"][0]["result"]["lead_id"]
    detail = (await client.get(f"{API}/leads/{lead_id}", headers=auth(agent["token"]))).json()
    assert (detail["name"], detail["city"], detail["state"]) == (name, "Hubli", "cold_calling")


async def test_http_turn_never_acts_on_a_doubtful_transcript(client, org, fake_model,
                                                             heard, no_server_voice):
    heard("delete everything maybe", confidence=0.3)
    fake = fake_model([])
    resp = await client.post(
        f"{API}/assistant/voice/turn", headers=auth(org["agent_token"]),
        data={"session_id": f"httpvoice{uuid.uuid4().hex}"},
        files={"file": ("a.m4a", b"audio", "audio/mp4")},
    )
    body = resp.json()
    assert fake.calls == []
    assert body["acted"] is False and body["low_confidence"] is True
    assert "delete everything maybe" in body["reply"]
    assert body["spoken_by"] == "device"


async def test_http_turn_requires_a_session(client, org, heard):
    resp = await client.post(f"{API}/assistant/voice/turn",
                             headers=auth(org["agent_token"]),
                             files={"file": ("a.m4a", b"audio", "audio/mp4")})
    assert resp.status_code == 422


async def test_voice_can_be_switched_off(client, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_mode_enabled", False)
    resp = await client.post(f"{API}/assistant/voice/speak",
                             headers=auth(org["agent_token"]), json={"text": "Hi."})
    assert resp.status_code == 503
    ws = await _open(org["agent_token"])
    event = await ws.wait_for(lambda e: e["type"] in ("error", "__closed__"))
    assert event.get("code") == "disabled"
    await ws.disconnect()


# ── the streaming session ────────────────────────────────────────────────────


async def test_ws_refuses_without_a_token(client, heard):
    ws = await _open(None)
    event = await ws.wait_for(lambda e: e["type"] == "error")
    assert event["code"] == "unauthorized"
    await ws.wait_for(lambda e: e["type"] == "__closed__")
    assert ws.close_code == 4401
    await ws.disconnect()


async def test_ws_accepts_the_token_in_the_start_message(client, org, heard,
                                                         no_server_voice):
    ws = WsClient()
    await ws.connect()
    await ws.send_json({"type": "start", "token": org["agent_token"],
                        "session_id": f"voicesess{uuid.uuid4().hex}"})
    ready = await ws.wait_for(lambda e: e["type"] == "ready")
    assert ready["input"] == {"format": "pcm_s16le", "sample_rate": 16000,
                              "end_of_turn": "server"}
    await ws.disconnect()


async def test_ws_rejects_a_bad_session_id(client, org, heard):
    ws = WsClient(headers={"authorization": f"Bearer {org['agent_token']}"})
    await ws.connect()
    await ws.send_json({"type": "start", "session_id": "bad id!"})
    event = await ws.wait_for(lambda e: e["type"] == "error")
    assert event["code"] == "bad_session"
    await ws.disconnect()


async def test_ws_text_turn_acknowledges_then_answers_aloud(client, org, fake_model,
                                                            heard, server_voice):
    ws = await _open(org["agent_token"])
    await ws.wait_for(lambda e: e["type"] == "ready")
    fake_model([LlmResponse(text='{"agent": "query"}'),
                LlmResponse(text="You have **no** open tasks today.")])
    await ws.send_json({"type": "text", "text": "what are my tasks"})

    thinking = await ws.wait_for(lambda e: e["type"] == "thinking")
    assert thinking == {"type": "thinking", "turn": 1, "agent": "query",
                        "text": "Let me check."}
    reply = await ws.wait_for(lambda e: e["type"] == "reply")
    assert reply["acted"] is True and reply["spoken_by"] == "server"
    assert reply["speech"] == "You have no open tasks today."
    await ws.wait_for(lambda e: e["type"] == "speak_end" and e["kind"] == "reply")
    starts = [e for e in ws.events if e["type"] == "speak_start"]
    assert [s["kind"] for s in starts] == ["ack", "reply"]
    assert starts[0]["sample_rate"] == 24_000
    assert ws.audio_bytes > 0
    await ws.disconnect()


async def test_ws_builds_a_client_by_voice_end_to_end(client, org, fake_model, heard,
                                                      no_server_voice):
    agent = await _agent(client, org)
    name = f"Streamed Co {_hex()}"
    ws = await _open(agent["token"])
    await ws.wait_for(lambda e: e["type"] == "ready")

    async def spoken(said, *, confidence=0.9):
        heard(said, confidence=confidence)
        await ws.send_bytes(silence(0.2) + tone(0.6) + silence(1.2))
        transcript = await ws.wait_for(lambda e: e["type"] == "transcript")
        assert transcript["text"] == said
        return await ws.wait_for(lambda e: e["type"] == "reply")

    fake_model([LlmResponse(text='{"agent": "client"}'),
                LlmResponse(tool_calls=[ToolCall(name="create_client",
                                                 args={"name": name})])])
    reply = await spoken(f"Create a lead named {name}.")
    assert reply["reply"].startswith("Sure. Who should own it?")
    assert reply["reply"].endswith("or you?")
    assert reply["actions"][-1]["candidates"][-1] == "Me"
    assert reply["spoken_by"] == "device"  # no server voice in this test

    fake = fake_model([])
    reply = await spoken("Me.")
    assert reply["reply"] == ("Okay, you'll own it. Do you want to add a city, source, "
                              "website or notes? They're optional.")

    fake_model([LlmResponse(text=json.dumps({"answer": "values", "city": "Pune"}))])
    reply = await spoken("Add city as Pune.")
    assert reply["reply"] == (f"Got it, Pune. So: {name} in Pune, owned by you. "
                              "Anything else, or shall I create it?")

    fake = fake_model([])
    reply = await spoken("Create it.")
    assert fake.calls == []
    assert reply["reply"].startswith(f"Done — {name} is added")
    lead_id = reply["actions"][0]["result"]["lead_id"]
    await ws.disconnect()
    detail = (await client.get(f"{API}/leads/{lead_id}", headers=auth(agent["token"]))).json()
    assert (detail["owner_id"], detail["city"], detail["state"]) == \
        (agent["id"], "Pune", "cold_calling")


async def test_ws_does_not_act_on_a_doubtful_transcript(client, org, fake_model, heard,
                                                        no_server_voice):
    heard("create client something", confidence=0.2)
    fake = fake_model([])
    ws = await _open(org["agent_token"])
    await ws.wait_for(lambda e: e["type"] == "ready")
    await ws.send_bytes(tone(0.6) + silence(1.2))
    transcript = await ws.wait_for(lambda e: e["type"] == "transcript")
    assert transcript["low_confidence"] is True
    reply = await ws.wait_for(lambda e: e["type"] == "reply")
    assert reply["acted"] is False and "create client something" in reply["reply"]
    assert fake.calls == []
    await ws.disconnect()


async def test_ws_quiet_replies_count_only_inside_a_client_draft(client, org, fake_model,
                                                                 heard, no_server_voice):
    """Whisper scores short replies around 0.5 however clearly they were said.
    While a client is being built up, a reply down to 0.4 counts (everything is
    read back before anything is created); outside one, 0.6 still applies."""
    agent = await _agent(client, org)
    name = f"Quiet Co {_hex()}"
    ws = await _open(agent["token"])
    await ws.wait_for(lambda e: e["type"] == "ready")

    async def spoken(said, confidence):
        heard(said, confidence=confidence)
        await ws.send_bytes(tone(0.5) + silence(1.2))
        return await ws.wait_for(lambda e: e["type"] == "reply")

    fake = fake_model([])
    reply = await spoken("Yes.", 0.5)  # nothing open: the full gate
    assert reply["acted"] is False and fake.calls == []

    fake_model([LlmResponse(text='{"agent": "client"}'),
                LlmResponse(tool_calls=[ToolCall(name="create_client",
                                                 args={"name": name, "owner": "me"})])])
    reply = await spoken(f"create a lead named {name}, I'll own it", 0.9)
    assert reply["acted"] is True

    reply = await spoken("No thanks.", 0.3)  # too quiet even inside a draft
    assert reply["acted"] is False

    fake = fake_model([])
    reply = await spoken("No thanks.", 0.5)
    assert reply["acted"] is True and reply["reply"].startswith("Okay. So:")
    reply = await spoken("Create it.", 0.45)
    assert reply["acted"] is True and reply["reply"].startswith(f"Done — {name} is added")
    assert fake.calls == []
    await ws.disconnect()


async def test_ws_names_heard_with_doubt_are_spelled_back_before_creating(
        client, org, fake_model, heard, no_server_voice):
    """Measured: large-v3 heard "Bhavan" as "Bavin" and "Pune" as "Puna" at 0.62,
    and a plain read-back was agreed to. A doubtful name is spelled back once,
    and can be corrected letter by letter, before anything is created."""
    agent = await _agent(client, org)
    ws = await _open(agent["token"])
    await ws.wait_for(lambda e: e["type"] == "ready")

    async def spoken(said, confidence):
        heard(said, confidence=confidence)
        await ws.send_bytes(tone(0.5) + silence(1.2))
        return (await ws.wait_for(lambda e: e["type"] == "reply"))["reply"]

    fake_model([LlmResponse(text='{"agent": "client"}'),
                LlmResponse(tool_calls=[ToolCall(name="create_client", args={
                    "name": "Bal Bavin Public School", "owner": "me"})])])
    assert (await spoken("Create a lead named Bal Bavin Public School, I'll own it.", 0.62)
            ).startswith("Sure. You'll own it. Do you want to add")
    fake_model([LlmResponse(text=json.dumps({"answer": "values", "city": "Puna"}))])
    assert await spoken("Add city as Puna.", 0.62) == (
        "Got it, Puna. So: Bal Bavin Public School in Puna, owned by you. "
        "Anything else, or shall I create it?")

    fake = fake_model([])
    assert await spoken("Create it.", 0.55) == (
        "Before I create it, let me check the spelling. Bal Bavin Public School is "
        "spelled B-A-L, B-A-V-I-N, P-U-B-L-I-C, S-C-H-O-O-L. Puna is spelled P-U-N-A. "
        "Is that right?")
    assert await spoken("No.", 0.5) == (
        "Which word is wrong? Tell me the word and spell it, letter by letter.")
    assert await spoken("The second word is B-H-A-W-A-N.", 0.7) == (
        "Got it — it's now spelled B-A-L, B-H-A-W-A-N, P-U-B-L-I-C, S-C-H-O-O-L. "
        "So: Bal Bhawan Public School in Puna, owned by you. Anything else, or shall I "
        "create it?")
    assert await spoken("The city is P U N E.", 0.7) == (
        "Got it — it's now spelled P-U-N-E. So: Bal Bhawan Public School in Pune, owned "
        "by you. Anything else, or shall I create it?")
    done = await spoken("Create it.", 0.55)
    assert done.startswith("Done — Bal Bhawan Public School is added")
    assert fake.calls == []  # every step above was read without a model
    await ws.disconnect()
    leads = (await client.get(f"{API}/leads", headers=auth(agent["token"]),
                              params={"q": "Bal Bhawan"})).json()
    assert [(l["name"], l["city"]) for l in leads] == [("Bal Bhawan Public School", "Pune")]


async def test_ws_a_confidently_heard_name_is_not_spelled_back(client, org, fake_model,
                                                               heard, no_server_voice):
    agent = await _agent(client, org)
    name = f"Clear Co {_hex()}"
    ws = await _open(agent["token"])
    await ws.wait_for(lambda e: e["type"] == "ready")
    heard(f"Create a lead named {name} in Pune, I'll own it", confidence=0.85)
    fake_model([LlmResponse(text='{"agent": "client"}'),
                LlmResponse(tool_calls=[ToolCall(name="create_client", args={
                    "name": name, "city": "Pune", "owner": "me"})])])
    await ws.send_bytes(tone(0.5) + silence(1.2))
    await ws.wait_for(lambda e: e["type"] == "reply")
    heard("No thanks.", confidence=0.9)
    await ws.send_bytes(tone(0.5) + silence(1.2))
    await ws.wait_for(lambda e: e["type"] == "reply")
    heard("Create it.", confidence=0.9)
    fake_model([])
    await ws.send_bytes(tone(0.5) + silence(1.2))
    reply = await ws.wait_for(lambda e: e["type"] == "reply")
    assert reply["reply"].startswith(f"Done — {name} is added")
    await ws.disconnect()


async def test_ws_whisper_is_told_the_names_to_expect(client, org, fake_model, heard,
                                                     no_server_voice):
    state = heard("what are my tasks")
    fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text="None.")])
    email_name = f"Hinted {_hex()}"
    created = await client.post(f"{API}/admin/users", headers=auth(org["admin_token"]),
                                json={"email": f"h{_hex()}@voicemode-example.com",
                                      "name": email_name, "role": "sales_agent"})
    assert created.status_code == 200
    ws = await _open(org["agent_token"])
    await ws.wait_for(lambda e: e["type"] == "ready")
    await ws.send_bytes(tone(0.5) + silence(1.2))
    await ws.wait_for(lambda e: e["type"] == "reply")
    await ws.disconnect()
    assert state["prompts"] and email_name in (state["prompts"][-1] or "")


async def test_ws_whisper_is_told_recent_clients_and_cities(client, org, fake_model, heard,
                                                            no_server_voice):
    state = heard("what are my tasks")
    fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text="None.")])
    client_name = f"Hebbal Vidyashram {_hex()}"
    created = await client.post(f"{API}/leads", headers=auth(org["agent_token"]),
                                json={"name": client_name, "city": "Davangere"})
    assert created.status_code == 200, created.text
    ws = await _open(org["agent_token"])
    await ws.wait_for(lambda e: e["type"] == "ready")
    await ws.send_bytes(tone(0.5) + silence(1.2))
    await ws.wait_for(lambda e: e["type"] == "reply")
    await ws.disconnect()
    prompt = state["prompts"][-1] or ""
    people, _, rest = prompt.partition(" Clients: ")
    assert people and "Voice " in people              # people come first
    assert client_name in rest.split(" Cities: ")[0]
    cities = rest.split(" Cities: ")[1]
    assert cities.index("Davangere") < cities.index("Bengaluru")  # org's own first
    assert "Mysuru" in cities and prompt.endswith(".")
    assert len(prompt) <= 800


async def test_ws_client_side_end_of_turn_for_a_recorded_clip(client, org, fake_model,
                                                              heard, no_server_voice):
    state = heard("show my follow ups")
    fake_model([LlmResponse(text='{"agent": "followup"}'),
                LlmResponse(text="Nothing is due.")])
    ws = await _open(org["agent_token"], format="audio/ogg")
    ready = await ws.wait_for(lambda e: e["type"] == "ready")
    assert ready["input"]["end_of_turn"] == "client"
    await ws.send_bytes(b"OggS-not-really" * 100, chunk=500)
    await ws.send_json({"type": "end_of_speech"})
    reply = await ws.wait_for(lambda e: e["type"] == "reply")
    assert reply["reply"] == "Nothing is due."
    assert state["audio"] == [b"OggS-not-really" * 100]
    await ws.disconnect()


async def test_ws_talking_over_the_reply_stops_it(client, org, fake_model, heard):
    engine = FakeVoice(delay=0.3)
    tts.install_engine_for_tests(engine)
    try:
        ws = await _open(org["agent_token"])
        await ws.wait_for(lambda e: e["type"] == "ready")
        long_reply = " ".join(f"This is sentence number {i} of the answer." for i in range(8))
        fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text=long_reply)])
        await ws.send_json({"type": "text", "text": "tell me everything"})
        await ws.wait_for(lambda e: e["type"] == "speak_start" and e["kind"] == "reply")

        await ws.send_bytes(tone(0.2))  # the person starts talking
        interrupted = await ws.wait_for(lambda e: e["type"] == "interrupted")
        assert interrupted["reason"] == "barge_in"
        end = await ws.wait_for(lambda e: e["type"] == "speak_end" and e["kind"] == "reply")
        assert end["interrupted"] is True
        assert len(engine.spoken) < len(voice.sentences(long_reply))
        await ws.send_json({"type": "cancel"})
        await ws.disconnect()
    finally:
        tts.install_engine_for_tests(None)


async def test_ws_ping_and_unknown_messages_keep_the_session(client, org, heard,
                                                             no_server_voice):
    ws = await _open(org["agent_token"])
    await ws.wait_for(lambda e: e["type"] == "ready")
    await ws.send_json({"type": "dance"})
    error = await ws.wait_for(lambda e: e["type"] == "error")
    assert error["code"] == "unknown_message" and error["fatal"] is False
    await ws.send_json({"type": "ping"})
    await ws.wait_for(lambda e: e["type"] == "pong")
    await ws.disconnect()



# ── voices ───────────────────────────────────────────────────────────────────


async def test_config_lists_the_voices(client, org, server_voice):
    body = (await client.get(f"{API}/assistant/voice/config",
                             headers=auth(org["agent_token"]))).json()
    assert "af_bella" in body["voices"] and "am_michael" in body["voices"]
    assert body["default_voice"] == get_settings().voice_tts_voice


async def test_speak_uses_the_asked_voice_and_ignores_unknown_ones(client, org, server_voice):
    headers = auth(org["agent_token"])
    r = await client.post(f"{API}/assistant/voice/speak",
                          json={"text": "Hi, I'm Lily.", "voice": "af_bella"}, headers=headers)
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    r = await client.post(f"{API}/assistant/voice/speak",
                          json={"text": "Hello.", "voice": "../etc/passwd"}, headers=headers)
    assert r.status_code == 200
    assert server_voice.voices == ["af_bella", None]


async def test_ws_speaks_in_the_start_voice_and_can_switch(client, org, fake_model, heard,
                                                           server_voice):
    ws = await _open(org["agent_token"], voice="am_fenrir")
    ready = await ws.wait_for(lambda e: e["type"] == "ready")
    assert ready["voice"] == "am_fenrir"

    fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text="All clear.")])
    await ws.send_json({"type": "text", "text": "anything due?"})
    await ws.wait_for(lambda e: e["type"] == "speak_end" and e["kind"] == "reply")
    assert server_voice.voices and set(server_voice.voices) == {"am_fenrir"}

    await ws.send_json({"type": "voice", "voice": "af_sarah"})
    switched = await ws.wait_for(lambda e: e["type"] == "voice")
    assert switched["voice"] == "af_sarah"
    await ws.send_json({"type": "voice", "voice": "robot"})
    error = await ws.wait_for(lambda e: e["type"] == "error")
    assert error["code"] == "bad_voice" and error["fatal"] is False

    server_voice.voices.clear()
    fake_model([LlmResponse(text='{"agent": "query"}'), LlmResponse(text="Still clear.")])
    await ws.send_json({"type": "text", "text": "and now?"})
    await ws.wait_for(lambda e: e["type"] == "speak_end" and e["kind"] == "reply")
    assert set(server_voice.voices) == {"af_sarah"}
    await ws.disconnect()


async def test_ws_an_unknown_start_voice_is_the_default(client, org, heard, server_voice):
    ws = await _open(org["agent_token"], voice="nope")
    ready = await ws.wait_for(lambda e: e["type"] == "ready")
    assert ready["voice"] == get_settings().voice_tts_voice
    await ws.disconnect()
