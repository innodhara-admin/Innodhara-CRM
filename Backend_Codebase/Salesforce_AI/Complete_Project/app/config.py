"""Central application configuration.

Every key the platform needs lives in the .env file next to run.py.
Anything not configured degrades gracefully (dry-run modes) so the
backend always runs end-to-end.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "YuviPep AI Sales Platform"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 1440

    # ── Super admin ──────────────────────────────────────────────────────────
    super_admin_email: str = "superadmin@platform.local"
    super_admin_password: str = "SuperAdmin@123"

    # ── Data layer ───────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/salesplatform.db"
    storage_dir: str = "./data/storage"

    # ── Model layer ──────────────────────────────────────────────────────────
    llm_provider: str = "gemini"  # gemini | claude | openrouter
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    llm_model_fast: str = "gemini-2.5-flash-lite"
    llm_model_strong: str = "gemini-2.5-flash"
    claude_model_fast: str = "claude-haiku-4-5-20251001"
    claude_model_strong: str = "claude-sonnet-5"
    # OpenRouter models (":free" suffix = zero-cost tier; swap for any
    # paid model id anytime — https://openrouter.ai/models)
    openrouter_model_fast: str = "nvidia/nemotron-3-nano-30b-a3b:free"
    openrouter_model_strong: str = "nvidia/nemotron-3-super-120b-a12b:free"
    # Memory embeddings (RAG). Same shape as the STT switch above:
    #   local  — a sentence-transformers model on this machine (the default).
    #            No key, no quota, no per-call cost, and a client's notes never
    #            leave the server.
    #   gemini — Google's embedding API via GEMINI_API_KEY. Kept so the switch
    #            is reversible in one line.
    #   hash   — the deterministic offline embedder. Chosen automatically when
    #            LLM_PROVIDER=stub, so dry runs stay instant and offline.
    embedding_provider: str = "local"  # local | gemini | hash
    # Chosen on a measured bake-off against the real note corpus rather than on
    # reputation. The decisive axis was Indic scripts: an English-only tokeniser
    # (all-MiniLM-L6-v2, bge-*-en) turns Kannada into [UNK] tokens, so every
    # Kannada question collapses onto near-identical vectors and retrieval is
    # 0/6. This model scored 5/6 there and 26/33 overall.
    # Downloads (~1.1 GB) to the HuggingFace cache on first use, like Whisper's.
    # A filesystem path works here too, for an installation with no internet.
    embedding_model_local: str = "intfloat/multilingual-e5-base"
    # This model family is asymmetric: text being stored and text being searched
    # for take different prefixes, and the pair must agree or stored notes stop
    # matching queries. Blank both when using a symmetric model.
    embedding_query_prefix: str = "query: "
    embedding_passage_prefix: str = "passage: "
    # Deliberately CPU, though sentence-transformers would pick the GPU on its
    # own. The GPU on the deployment host belongs to Whisper (~5 GB at medium,
    # ~10 GB at large on a 12 GB card); an embedding model quietly taking VRAM
    # beside it turns a transcription upgrade into an out-of-memory failure
    # somewhere else entirely. Embedding a note costs ~8 ms on CPU and happens
    # a few dozen times a day, so there is nothing to win. Set "cuda" only on a
    # host where nothing else wants the card.
    embedding_device: str = "cpu"
    embedding_model: str = "gemini-embedding-001"  # used only when provider=gemini
    # Speech-to-text: whisper_local (open-source Whisper on this machine,
    # needs openai-whisper + ffmpeg) | gemini (Google API via GEMINI_API_KEY)
    stt_provider: str = "whisper_local"
    whisper_model: str = "medium"  # tiny | base | small | medium | large
    # Field dictation (POST /dictate) is a DIFFERENT job from meeting
    # transcription: a few seconds of speech that a human is waiting on with
    # the keyboard still open, not a 40-minute recording processed in the
    # background. Latency is the whole product here, so it gets its own,
    # smaller model — "medium" would make every tap-to-dictate feel broken.
    # Same ladder as whisper_model. `tiny` was the default until 21 Sep 2026,
    # when a dictated client name came back as Russian: with no language to
    # hold on to, tiny picks one. Dictation is now limited to
    # VOICE_STT_LANGUAGES and runs the SAME model name as voice mode, so the
    # two share one loaded copy (no extra GPU) and Kannada and Hindi are heard
    # as well in a text field as they are in a spoken turn. The cost of
    # sharing is the lock: a five-minute notes dictation holds the model while
    # it runs, and a spoken turn arriving then waits for it. Set this to
    # `turbo` to give dictation its own faster model again (+1.85 GB).
    dictation_whisper_model: str = "large-v3"
    # On a GPU, store Whisper's linear/convolution weights as float16. Whisper
    # already casts them to float16 on every call, so transcripts are
    # identical (measured 2026-09-17: 252 of 252 clips) in about half the GPU
    # memory (turbo 3.3 GB -> 1.85 GB peak). false = load exactly as before.
    whisper_fp16_weights: bool = True
    # Inbound email: off | imap — when imap, each org's inbox (same Gmail App
    # Password as sending) is polled and fed to the Inbound Engine.
    inbound_email_mode: str = "off"
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    inbound_poll_seconds: int = 120
    llm_max_concurrency: int = 4
    llm_max_retries: int = 4
    llm_default_org_monthly_budget_usd: float = 50.0

    # ── Assistant conversation memory ────────────────────────────────────────
    # How much of the current chat the assistant sees. Turns are plain text,
    # so the real cost is small; the char budget is the hard ceiling that
    # keeps a long chat from crowding out the system prompt on a small model.
    assistant_history_turns: int = 12  # ~6 exchanges replayed to the model
    assistant_history_char_budget: int = 6000
    assistant_session_max_turns: int = 60  # rows kept per conversation
    # A chat buffer must not quietly become a permanent store — the retention
    # sweep drops conversations older than this (services/retention_service).
    assistant_history_retention_days: int = 90
    # How long a write the assistant has read back ("Shall I create …?")
    # waits for the person's "yes". Past this the "yes" confirms nothing and
    # the assistant says so — a stale agreement must not create a record.
    assistant_confirmation_ttl_seconds: int = 600

    # ── Field location (2 Oct 2026) ──────────────────────────────────────────
    # Readings older than this are deleted by the retention sweep.
    location_retention_days: int = 90
    # The map's look, handed to the app by GET /locations/config so the tile
    # server can change without a new app. OpenFreeMap: free, no key.
    location_map_style_light: str = "https://tiles.openfreemap.org/styles/positron"
    location_map_style_dark: str = "https://tiles.openfreemap.org/styles/dark"
    location_map_attribution: str = "OpenFreeMap © OpenMapTiles Data from OpenStreetMap"

    # ── Voice mode (WS /assistant/voice, POST /assistant/voice/turn) ─────────
    # Master switch. Off = both voice endpoints refuse; typed Jarvis and
    # /dictate are unaffected either way.
    voice_mode_enabled: bool = True
    # The Whisper model a live voice turn uses. Separate from whisper_model
    # (meetings, a background job) and dictation_whisper_model (a text field):
    # voice mode acts on what it hears, so it needs Kannada/Hindi accuracy
    # close to `large` at a latency a conversation can bear.
    # Measured 2026-09-17 on 63 real recordings (Indian English, client names,
    # cities, owners): `large-v3` got 82% of names exactly right against
    # turbo's 74% (both with the richer hint; 66% for turbo as it was), at
    # 0.56 s instead of 0.32 s per turn and 3.5 GB of GPU with fp16 weights.
    # `turbo` remains the faster choice. Both files are ~/.cache/whisper.
    voice_stt_model: str = "large-v3"
    # The languages a voice turn may be heard in, comma-separated Whisper
    # codes; detection chooses only among these. Empty = any language.
    # Without it large-v3 writes Hindi in Urdu script ("Priya ko de do" came
    # out as "فریہ کو دے دو"), which loses the name.
    voice_stt_languages: str = "en,hi,kn"
    # Spoken replies: kokoro (Kokoro-82M, needs `pip install kokoro soundfile`)
    # | off. When the engine is off or cannot load, voice mode still works — the
    # server says so in its `ready` message and sends the text to speak, and
    # the phone uses its own voice.
    voice_tts_engine: str = "kokoro"
    voice_tts_voice: str = "af_heart"
    voice_tts_lang_code: str = "a"  # Kokoro's code for its English voices
    voice_tts_speed: float = 1.0
    voice_tts_device: str = "cuda"
    # End of turn: this much silence after speech ends the utterance. Was the
    # proposal's 0.6 s until 21 Sep 2026 — people reported Jarvis "not waiting
    # to listen completely, in the midway start answering", because a breath
    # mid-sentence is easily 0.6 s. 0.9 s costs every turn 0.3 s and is still
    # well under the 2.5 s the dictation mic waits.
    voice_vad_silence_ms: int = 900
    # Less loud speech than this is a noise, not a turn. Was 300: a clearly
    # spoken "Yes." on the phone (noise suppressor on) holds only 280 ms of
    # sound and was dropped without a word (measured 2026-09-17).
    voice_min_utterance_ms: int = 150
    voice_max_utterance_seconds: int = 30
    # A session with no audio and no messages for this long is closed.
    voice_idle_timeout_seconds: int = 300
    # Talking over a spoken reply stops it. A phone without echo cancelling
    # can turn this off per session ("barge_in": false in its start message).
    voice_barge_in: bool = True
    # While a client is being built up by conversation, a spoken reply may
    # clear this lower bar instead of the usual 0.6. Measured 2026-09-15 on
    # clean synthetic speech: one-word replies score 0.44-0.55 even on
    # large-v3 ("Yes." 0.49-0.52), while "Yes, go ahead." scores 0.80. Safe
    # because nothing is created until the whole record is read back and the
    # person says to create it. Every other transcript keeps the 0.6 gate.
    voice_confirmation_min_confidence: float = 0.4
    # A client's name, city or contact heard by voice below this confidence is
    # spelled back once before "create it" is accepted. Measured 2026-09-15 on
    # large-v3: misheard names came in at 0.62 ("Bal Bavin", "Puna"), clearly
    # heard full sentences at 0.81-0.82. Typed input is never checked.
    voice_spell_check_below_confidence: float = 0.8

    # ── Email ────────────────────────────────────────────────────────────────
    email_mode: str = "dry_run"  # dry_run | smtp
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_default_username: str = ""
    smtp_default_app_password: str = ""
    email_max_per_minute: int = 10

    # ── Word -> PDF (LibreOffice) ───────────────────────────────────────────
    # The soffice that converts proposals and MOUs. 7.3 (/usr/bin) loses the
    # templates' cover title size and floating tables; 26.2 in /opt does not
    # (measured 13 Oct 2026). Pointing this back at /usr/bin/soffice undoes it.
    libreoffice_bin: str = "/usr/bin/soffice"
    # Used when libreoffice_bin hangs or fails on a document. Every modern
    # LibreOffice loops forever on one owner template's floating tables while
    # 7.3 converts it, so live sets this to /usr/bin/soffice. Blank = none.
    libreoffice_fallback_bin: str = ""
    # How long libreoffice_bin gets before the fallback is tried. Real
    # templates convert in 2-6 s; the phone app gives up after 30 s.
    libreoffice_first_try_seconds: int = 15
    # A folder of fonts only the converter sees (the templates' Aptos,
    # Calibri-compatible Carlito, Lato, Poppins, Barlow), with an optional
    # fonts.conf of substitutions beside them. Blank = none. Kept outside the
    # repository: some of these fonts may not be redistributed.
    pdf_fonts_dir: str = ""

    # ── WhatsApp ─────────────────────────────────────────────────────────────
    whatsapp_mode: str = "dry_run"  # dry_run | cloud_api
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_max_per_minute: int = 10
    whatsapp_webhook_verify_token: str = "change-me-webhook-verify"
    # The address the outside world reaches this server on (the ngrok URL on
    # live). A WhatsApp provider fetches a proposal or transcript PDF from a
    # signed link under it. Blank = documents cannot be sent on WhatsApp.
    public_base_url: str = ""

    # ── Calendar ─────────────────────────────────────────────────────────────
    calendar_mode: str = "off"  # off | google
    google_calendar_credentials_file: str = ""
    google_calendar_id: str = ""
    # Reusable Meet link stamped into demo invites (orgs can override via
    # their calendar integration's "meet_link").
    google_meet_link: str = ""

    # ── Mobile push (FCM HTTP v1) ────────────────────────────────────────────
    # Path to the Firebase service-account .json. Blank = push disabled;
    # in-app notifications keep working regardless.
    fcm_service_account_json: str = ""

    # ── Jobs ─────────────────────────────────────────────────────────────────
    job_workers: int = 3
    job_max_attempts: int = 4

    # ── Data protection defaults ─────────────────────────────────────────────
    default_audio_retention_days: int = 90
    default_transcript_retention_days: int = 365

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def resolved_database_url(self) -> str:
        """Make relative SQLite paths absolute (anchored at the project root)."""
        url = self.database_url
        prefix = "sqlite+aiosqlite:///"
        if url.startswith(prefix):
            raw = url[len(prefix):]
            p = Path(raw)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            p.parent.mkdir(parents=True, exist_ok=True)
            return prefix + p.as_posix()
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
