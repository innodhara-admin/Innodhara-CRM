"""Async SQLAlchemy engine and session management.

Default engine is SQLite (zero setup). Point DATABASE_URL at PostgreSQL for
production and run scripts/postgres_rls.sql to add Row-Level Security as the
second isolation layer described in the architecture plan (Section 2.4).
Application-level org_id scoping (level 1) is enforced on every query.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

_is_sqlite = settings.resolved_database_url.startswith("sqlite")

engine = create_async_engine(
    settings.resolved_database_url,
    echo=False,
    pool_pre_ping=True,
    # SQLite: wait for a busy writer instead of failing instantly. The LLM
    # usage recorder and background jobs write from their own sessions while
    # a request transaction may hold the write lock.
    connect_args={"timeout": 30} if _is_sqlite else {},
)

if _is_sqlite:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record) -> None:
        # WAL lets readers proceed while a writer holds its transaction —
        # without it, any long request transaction starves every other
        # session (budget checks, dashboards) on the dev database.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — one session per request."""
    async with SessionLocal() as session:
        yield session


def _apply_light_migrations(sync_conn) -> None:
    """Tiny in-place migrations for pre-Alembic databases (idempotent,
    dialect-agnostic — RENAME COLUMN works on SQLite ≥3.25 and PostgreSQL)."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "stakeholders" in tables:
        cols = {c["name"] for c in inspector.get_columns("stakeholders")}
        # 2026-07-17: stakeholder roles became free-form in the client's own
        # vocabulary; the column name follows (role_at_school → role_at_client).
        if "role_at_school" in cols and "role_at_client" not in cols:
            sync_conn.execute(text(
                "ALTER TABLE stakeholders "
                "RENAME COLUMN role_at_school TO role_at_client"
            ))
    # 2026-07-17 (second pass): the last school-flavoured identifiers went
    # generic — the shared-notebook table and the on-site lead state.
    if "school_intelligence" in tables and "client_intelligence" not in tables:
        sync_conn.execute(text(
            "ALTER TABLE school_intelligence RENAME TO client_intelligence"
        ))
    if "leads" in tables:
        sync_conn.execute(text(
            "UPDATE leads SET state = 'client_execution_in_progress' "
            "WHERE state = 'school_execution_in_progress'"
        ))
        sync_conn.execute(text(
            "UPDATE leads SET suggested_state = 'client_execution_in_progress' "
            "WHERE suggested_state = 'school_execution_in_progress'"
        ))
    # 2026-08-28: the pre-sales announcement window. create_all() creates
    # missing TABLES but never adds a column to one that already exists, so a
    # new setting needs this explicit step or it is silently absent on every
    # database that predates it.
    if "org_settings" in tables:
        cols = {c["name"] for c in inspector.get_columns("org_settings")}
        if "lead_open_feed_days" not in cols:
            sync_conn.execute(text(
                "ALTER TABLE org_settings "
                "ADD COLUMN lead_open_feed_days INTEGER DEFAULT 3"
            ))
    # 2026-08-31: the "they might be ready to buy again" flag on an
    # engagement. `create_all` creates missing TABLES but never adds a column
    # to one that already exists, so a database that got the engagements table
    # from an earlier restart needs these added explicitly.
    if "relationship_engagements" in tables:
        cols = {c["name"] for c in inspector.get_columns("relationship_engagements")}
        for name, ddl in (
            ("opportunity_status",
             "ADD COLUMN opportunity_status VARCHAR(20) DEFAULT 'none'"),
            ("opportunity_reason", "ADD COLUMN opportunity_reason TEXT"),
            ("opportunity_quote", "ADD COLUMN opportunity_quote TEXT"),
            ("opportunity_meeting_id",
             "ADD COLUMN opportunity_meeting_id VARCHAR(32)"),
            ("opportunity_at", "ADD COLUMN opportunity_at TIMESTAMP"),
            ("opportunity_decided_by",
             "ADD COLUMN opportunity_decided_by VARCHAR(32)"),
            ("opportunity_decided_at",
             "ADD COLUMN opportunity_decided_at TIMESTAMP"),
        ):
            if name not in cols:
                sync_conn.execute(
                    text(f"ALTER TABLE relationship_engagements {ddl}")
                )
    # 2026-09-23: meeting invites carry a bcc list.
    if "outbound_messages" in tables:
        cols = {c["name"] for c in inspector.get_columns("outbound_messages")}
        if "bcc" not in cols:
            sync_conn.execute(text("ALTER TABLE outbound_messages ADD COLUMN bcc JSON"))
    # 2026-09-23: "blocked, waiting on Siva" now names the colleague it
    # waits on, so Siva can be told and see it on Home.
    if "action_items" in tables:
        cols = {c["name"] for c in inspector.get_columns("action_items")}
        if "blocked_on_user_id" not in cols:
            sync_conn.execute(text(
                "ALTER TABLE action_items ADD COLUMN blocked_on_user_id VARCHAR(32)"
            ))
    # 2026-09-24: a contact records who added it, because opening a lead now
    # needs a reachable contact added by the lead's owner.
    if "contacts" in tables:
        cols = {c["name"] for c in inspector.get_columns("contacts")}
        if "created_by" not in cols:
            sync_conn.execute(text(
                "ALTER TABLE contacts ADD COLUMN created_by VARCHAR(32)"
            ))
            if "audit_log" in tables:
                _backfill_contact_creators(sync_conn)
    # 2026-10-01: a recorded meeting's plan is held for "Approve plan", and
    # the app follows where that stands (planning, ready, approved...).
    if "meetings" in tables:
        cols = {c["name"] for c in inspector.get_columns("meetings")}
        if "plan_state" not in cols:
            sync_conn.execute(text("ALTER TABLE meetings ADD COLUMN plan_state VARCHAR(20)"))
        if "plan_note" not in cols:
            sync_conn.execute(text("ALTER TABLE meetings ADD COLUMN plan_note TEXT"))
    if "lead_state_history" in tables:
        for col in ("from_state", "to_state"):
            sync_conn.execute(text(
                f"UPDATE lead_state_history SET {col} = "
                "'client_execution_in_progress' "
                f"WHERE {col} = 'school_execution_in_progress'"
            ))


def _backfill_contact_creators(sync_conn) -> None:
    """Fill `contacts.created_by` for rows that predate the column, from the
    audit log. Runs once, in the migration that adds the column.

    A card scan's audit row names the contact itself. A typed contact's row
    names the lead, so it is matched by time: the audit row is written in the
    same request, moments after the contact. A contact with no match stays
    NULL -- it is not counted as the owner's, so its owner adds one before
    opening, which is the safe direction to be wrong in.
    """
    from datetime import datetime

    from sqlalchemy import text

    def _when(value):
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    added: dict[str, list] = {}
    for user_id, lead_id, at in sync_conn.execute(text(
        "SELECT user_id, entity_id, at FROM audit_log "
        "WHERE action = 'contact.added' AND user_id IS NOT NULL"
    )):
        when = _when(at)
        if when is not None:
            added.setdefault(lead_id, []).append((when, user_id))
    scanned = dict(sync_conn.execute(text(
        "SELECT entity_id, user_id FROM audit_log "
        "WHERE action = 'contact.card_scanned' AND user_id IS NOT NULL"
    )).all())

    for contact_id, lead_id, source, created_at in sync_conn.execute(text(
        "SELECT id, lead_id, source, created_at FROM contacts"
    )).all():
        creator = None
        if source == "card":
            creator = scanned.get(contact_id)
        elif source == "manual":
            made = _when(created_at)
            if made is not None:
                near = [
                    (abs((when - made).total_seconds()), user_id)
                    for when, user_id in added.get(lead_id, [])
                ]
                near = [n for n in near if n[0] <= 10]
                if near:
                    creator = min(near)[1]
        if creator:
            sync_conn.execute(
                text("UPDATE contacts SET created_by = :u WHERE id = :i"),
                {"u": creator, "i": contact_id},
            )


async def init_db() -> None:
    """Create all tables (idempotent). Alembic can replace this later.

    Migrations run BEFORE create_all: a table rename must happen while the
    new name does not exist yet — otherwise create_all builds an empty table
    under the new name (index-name collision, stranded data) and the rename
    is skipped."""
    from app import models  # noqa: F401  (registers all models on Base)

    async with engine.begin() as conn:
        await conn.run_sync(_apply_light_migrations)
        await conn.run_sync(Base.metadata.create_all)
