"""YuviPep AI Sales Platform — application entry point.

Layers (doc §5): this Backend API resolves the organisation context for every
request, applies business rules, and hands work to the AI orchestrator and
the background job queue. Nothing reaches the AI without passing through here.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api import (
    action_items,
    admin,
    email_templates,
    assistant,
    auth,
    demos,
    documentation,
    followups,
    insights,
    leads,
    locations,
    meetings,
    messages,
    misc,
    mous,
    ops,
    organisations,
    projects,
    proposals,
    public_files,
    relationships,
    scheduled_meetings,
    voice,
    workflow,
)
from app.config import get_settings
from app.core.constants import Role
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.database import SessionLocal, init_db
from app.jobs import register_handlers
from app.jobs import scheduler
from app.jobs.queue import job_queue
from app.models.user import User

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


async def _seed_super_admin() -> None:
    """Ensure the platform Super Admin from .env exists."""
    settings = get_settings()
    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(User).where(
                    func.lower(User.email) == settings.super_admin_email.lower()
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                User(
                    org_id=None,
                    email=settings.super_admin_email.lower(),
                    name="Platform Super Admin",
                    role=Role.SUPER_ADMIN.value,
                    password_hash=hash_password(settings.super_admin_password),
                )
            )
            await db.commit()
            logger.info("Super admin seeded: %s", settings.super_admin_email)


def _warm_dictation_model() -> None:
    """Load the /dictate model into memory in the background, so the first
    person to tap a mic doesn't pay for it.

    Whisper loads lazily on first use — about five seconds for `tiny`. That
    cost lands entirely on whoever dictates first after a restart, who has no
    way to tell a one-off model load from a hung mic. Warming it here moves
    those seconds to a moment when nobody is waiting.

    Deliberately fire-and-forget, and deliberately swallowing everything: this
    is an optimisation, not a dependency. If openai-whisper isn't installed,
    or the provider is gemini, or the download fails, the server must still
    come up exactly as before — /dictate will just be slow, or report its own
    error, on the first call.
    """
    settings = get_settings()
    if settings.stt_provider != "whisper_local":
        return

    async def _warm() -> None:
        import asyncio

        from app.ai import stt

        model_name = settings.dictation_whisper_model

        def _load() -> None:
            # Same lock the transcribe path takes. Without it, a dictation
            # arriving mid-warm-up would load a second copy of the model
            # concurrently — the exact double-RAM case the lock exists to
            # prevent.
            with stt._lock_for(model_name):  # noqa: SLF001
                stt._load_whisper(model_name)  # noqa: SLF001

        try:
            await asyncio.to_thread(_load)
            logger.info("Dictation model '%s' warmed", model_name)
        except Exception as exc:  # noqa: BLE001 — never block startup
            logger.warning(
                "Dictation model '%s' not pre-warmed (%s); /dictate will load "
                "it on first use", model_name, exc,
            )

    import asyncio

    asyncio.create_task(_warm())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _seed_super_admin()
    register_handlers()
    # The Sync Engine owns the heartbeat: every emitted event triggers it.
    from app.engines import sync_engine

    sync_engine.register()
    await job_queue.start()
    await scheduler.start()
    _warm_dictation_model()
    logger.info("Platform ready")
    yield
    await scheduler.stop()
    await job_queue.stop()


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Zero-touch sales automation backend — multi-organisation, AI-agent "
        "driven. Every request is organisation-scoped; every client message "
        "needs a one-tap human approval."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(organisations.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
# Word email templates (2026-10-28), item 7 of the dashboard.
app.include_router(email_templates.router, prefix=API_PREFIX)
app.include_router(leads.router, prefix=API_PREFIX)
app.include_router(relationships.router, prefix=API_PREFIX)
app.include_router(meetings.router, prefix=API_PREFIX)
app.include_router(action_items.router, prefix=API_PREFIX)
app.include_router(proposals.router, prefix=API_PREFIX)
# Beside proposals, never inside them: a contract is not a proposal (D-A).
app.include_router(mous.router, prefix=API_PREFIX)
app.include_router(messages.router, prefix=API_PREFIX)
app.include_router(messages.webhooks, prefix=API_PREFIX)
app.include_router(followups.router, prefix=API_PREFIX)
app.include_router(demos.router, prefix=API_PREFIX)
# Meetings arranged with a client — their own path, not demos (2026-09-23).
app.include_router(scheduled_meetings.router, prefix=API_PREFIX)
app.include_router(assistant.router, prefix=API_PREFIX)
# Voice mode: the same assistant, spoken (WS /assistant/voice and friends).
app.include_router(voice.router, prefix=API_PREFIX)
app.include_router(misc.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(workflow.router, prefix=API_PREFIX)
app.include_router(ops.router, prefix=API_PREFIX)
# Field location (2 Oct 2026): readings from the sales team, the admin's map.
app.include_router(locations.router, prefix=API_PREFIX)
# The sales head's read-only screens (23 Oct 2026):
# YuvipepSalesforceAI/docs/superpowers/specs/2026-10-23-sales-head-design.md §9.1.
app.include_router(insights.router, prefix=API_PREFIX)
# The one route outside the login: a signed, expiring link to one PDF that a
# WhatsApp provider fetches (4 Nov 2026, app/core/signed_links.py).
app.include_router(public_files.router, prefix=API_PREFIX)
# Deliberately NOT under API_PREFIX: /documentation serves human-readable
# pages a person opens in a browser, not JSON for the app.
app.include_router(documentation.router)


@app.get("/", tags=["health"])
async def root():
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "api": API_PREFIX,
    }


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "llm_provider": settings.llm_provider}


# ── The setup console, when it has been built ────────────────────────────────
# The bundle lives outside app/ on purpose: tests/test_genericity.py scans
# app/**/*.py and scripts/check_hardcoded_strings.py scans Android Java, so a
# bundle carrying the product manual's verbatim quotes must stay out of both
# scan roots (05_DECISIONS.md D19).
_DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "Dashboard" / "dist"
if _DASHBOARD_DIST.is_dir():
    app.mount(
        "/dashboard",
        StaticFiles(directory=_DASHBOARD_DIST, html=True),
        name="dashboard",
    )
else:
    logger.warning(
        "Setup console not mounted: no bundle at %s. Run `npm run build` in "
        "Dashboard/ to serve it at /dashboard. The API is unaffected.",
        _DASHBOARD_DIST,
    )
