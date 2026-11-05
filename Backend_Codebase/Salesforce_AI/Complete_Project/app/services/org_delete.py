"""Delete a whole organisation and leave no trace of it.

Spec: docs/superpowers/specs/2026-10-28-org-delete-design.md.

The delete is a row of small sync steps that work on any SQLAlchemy
`Connection` and any storage root. The dashboard runs them on the live engine
(through `run_sync`) and `scripts/delete_organisation.py` runs them on any copy
of the database, so a staging copy is cleaned by exactly the code that cleans
live.

**Tables are read from the database itself, never from a hand-written list.**
Every table with an `org_id` column holds the organisation's rows. That covers
a table added after this was written and an older copy that still has a table
the models have dropped; `reset_taxonomy.py` is a list a person keeps, and a
delete that must leave nothing cannot depend on one.

**Nothing here writes an audit row or a log line that names the organisation.**
The developer decided (28 Oct 2026) that the system keeps no record of an
organisation once it is deleted.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from app.config import PROJECT_ROOT

BACKUP_KEEP_DAYS = 7

_ORG_ID = re.compile(r"[0-9a-f]{32}")
_STAMP = "%Y%m%dT%H%M%SZ"
# A row of an organisation table whose org_id is empty belongs to the platform.
# It is deleted when it names the organisation, except in these tables: the
# super admin is a `users` row with no org_id and is never deleted.
_PLATFORM_KEEP = frozenset({"users"})
_CHUNK = 500


def check_org_id(org_id: str) -> str:
    """The id must be 32 lowercase hex characters: it becomes a folder name."""
    if not isinstance(org_id, str) or not _ORG_ID.fullmatch(org_id):
        raise ValueError("That is not an organisation id.")
    return org_id


def default_backup_root() -> Path:
    """Beside the project folder, so a copy of the project never carries it."""
    return PROJECT_ROOT.parent / "org_delete_backups"


def _normalised(value: str) -> str:
    return " ".join(value.split()).casefold()


def confirmation_matches(typed: str, org_name: str) -> bool:
    """`DELETE <name>`: any case, extra spaces ignored, every other character
    must match."""
    if not org_name or not typed:
        return False
    return _normalised(typed) == _normalised(f"DELETE {org_name}")


def _columns(conn: Connection, table: str) -> list[str]:
    return [row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')]


def org_tables(conn: Connection) -> list[str]:
    """Every table in this database with an org_id column, children first.

    Tables the models do not know come first (nothing points at them from the
    models); the rest follow the models' foreign keys, child before parent.
    """
    import app.models  # noqa: F401  (fills Base.metadata)
    from app.database import Base

    names = [
        row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    owned = {
        name for name in names
        if name != "organisations" and "org_id" in _columns(conn, name)
    }
    unknown = sorted(name for name in owned if name not in Base.metadata.tables)
    known = [
        table.name for table in reversed(Base.metadata.sorted_tables)
        if table.name in owned
    ]
    return unknown + known


@dataclass
class Preview:
    org_id: str
    org_name: str | None
    org_exists: bool
    rows: dict[str, int]
    total: int
    platform_rows: dict[str, list[str]]
    other_org_mentions: dict[str, int]
    files: int
    bytes: int
    folder_exists: bool
    outside_files: list[str]
    users: list[dict[str, str]]

    @property
    def nothing_left(self) -> bool:
        return not (self.org_exists or self.rows or self.platform_rows
                    or self.folder_exists)


def _names_any(row: Any, ids: set[str]) -> bool:
    for value in row:
        if isinstance(value, str) and len(value) >= 32:
            if any(token in ids for token in _ORG_ID.findall(value)):
                return True
    return False


def _credentials_files(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    found: list[str] = []
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "credentials_file" and isinstance(inner, str) and inner:
                found.append(inner)
            else:
                found.extend(_credentials_files(inner))
    elif isinstance(value, list):
        for inner in value:
            found.extend(_credentials_files(inner))
    return found


def _folder(storage_root: Path, org_id: str) -> Path:
    return storage_root / "orgs" / org_id


def _folder_size(folder: Path) -> tuple[int, int]:
    files = size = 0
    if folder.is_dir():
        for path in folder.rglob("*"):
            if path.is_file() and not path.is_symlink():
                files += 1
                size += path.lstat().st_size
    return files, size


def preview(conn: Connection, org_id: str, storage_root: Path) -> Preview:
    """What a delete would remove. Reads only."""
    check_org_id(org_id)
    tables = org_tables(conn)
    org = conn.execute(
        text("SELECT name FROM organisations WHERE id = :o"), {"o": org_id}
    ).first()

    rows: dict[str, int] = {}
    ids = {org_id}
    for table in tables:
        count = conn.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE org_id = :o'), {"o": org_id}
        ).scalar_one()
        if count:
            rows[table] = count
            if "id" in _columns(conn, table):
                ids.update(
                    r[0] for r in conn.execute(
                        text(f'SELECT id FROM "{table}" WHERE org_id = :o'),
                        {"o": org_id},
                    )
                )

    platform: dict[str, list[str]] = {}
    mentions: dict[str, int] = {}
    for table in tables:
        has_id = "id" in _columns(conn, table)
        if has_id and table not in _PLATFORM_KEEP:
            hits = [
                r[0] for r in conn.execute(
                    text(f'SELECT id, * FROM "{table}" WHERE org_id IS NULL')
                )
                if _names_any(r[1:], ids)
            ]
            if hits:
                platform[table] = hits
        others = sum(
            1 for r in conn.execute(
                text(f'SELECT * FROM "{table}" WHERE org_id IS NOT NULL '
                     "AND org_id != :o"),
                {"o": org_id},
            )
            if _names_any(r, ids)
        )
        if others:
            mentions[table] = others

    folder = _folder(storage_root, org_id)
    files, size = _folder_size(folder)
    inside = folder.resolve()
    outside: list[str] = []
    if "org_settings" in tables:
        for row in conn.execute(
            text("SELECT * FROM org_settings WHERE org_id = :o"), {"o": org_id}
        ):
            for value in row:
                for name in _credentials_files(value):
                    if not Path(name).resolve().is_relative_to(inside):
                        outside.append(name)

    users = [
        {"email": r[0], "role": r[1]} for r in conn.execute(
            text("SELECT email, role FROM users WHERE org_id = :o ORDER BY email"),
            {"o": org_id},
        )
    ] if "users" in tables else []

    return Preview(
        org_id=org_id,
        org_name=org[0] if org else None,
        org_exists=org is not None,
        rows=rows,
        total=sum(rows.values()),
        platform_rows=platform,
        other_org_mentions=mentions,
        files=files,
        bytes=size,
        folder_exists=folder.exists(),
        outside_files=outside,
        users=users,
    )


def make_backup(db_path: Path, storage_root: Path, org_id: str,
                backup_root: Path, now: datetime) -> Path:
    """A full copy of the database and of the organisation's folder.

    The database copy goes through SQLite's backup API, which reads a
    consistent snapshot even while the server writes (a file copy would miss
    the WAL). A backup that fails part way is removed, never left half made.
    """
    check_org_id(org_id)
    folder = backup_root / f"{now.strftime(_STAMP)}_{org_id}"
    folder.mkdir(parents=True, exist_ok=False)
    try:
        source = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro",
                                 uri=True)
        target = sqlite3.connect(str(folder / "database.db"))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        org_folder = _folder(storage_root, org_id)
        if org_folder.is_dir():
            shutil.copytree(org_folder, folder / "files", symlinks=True)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def deactivate(conn: Connection, org_id: str) -> None:
    """Close the door first: every request of an inactive organisation is
    refused (app/api/deps.py) and the scheduler and mail poller skip it."""
    conn.execute(text("UPDATE organisations SET is_active = 0 WHERE id = :o"),
                 {"o": check_org_id(org_id)})


def delete_rows(conn: Connection, org_id: str,
                platform_rows: dict[str, list[str]]) -> dict[str, int]:
    """Every row of the organisation, the platform rows that name it, then the
    organisation itself. Counts per table; platform rows as `platform:<table>`."""
    check_org_id(org_id)
    deleted: dict[str, int] = {}
    for table in org_tables(conn):
        count = conn.execute(
            text(f'DELETE FROM "{table}" WHERE org_id = :o'), {"o": org_id}
        ).rowcount
        if count:
            deleted[table] = count
    for table, ids in platform_rows.items():
        if table in _PLATFORM_KEEP:
            continue
        statement = text(
            f'DELETE FROM "{table}" WHERE org_id IS NULL AND id IN :ids'
        ).bindparams(bindparam("ids", expanding=True))
        count = 0
        for start in range(0, len(ids), _CHUNK):
            count += conn.execute(statement, {"ids": ids[start:start + _CHUNK]}).rowcount
        if count:
            deleted[f"platform:{table}"] = count
    deleted["organisations"] = conn.execute(
        text("DELETE FROM organisations WHERE id = :o"), {"o": org_id}
    ).rowcount
    return deleted


def delete_files(storage_root: Path, org_id: str) -> tuple[int, int]:
    """Remove `orgs/<org_id>/`. Refuses anything that does not resolve to a
    folder directly inside `orgs/` with exactly that name."""
    check_org_id(org_id)
    folder = _folder(storage_root, org_id)
    if not folder.exists() and not folder.is_symlink():
        return 0, 0
    resolved = folder.resolve()
    if resolved.parent != (storage_root / "orgs").resolve() or resolved.name != org_id:
        raise ValueError("The organisation's folder is not where it should be.")
    files, size = _folder_size(resolved)
    shutil.rmtree(resolved)
    return files, size


def compact(db_path: Path) -> bool:
    """Leave nothing readable of the deleted rows in the database file.

    SQLite keeps deleted content in free pages, and older page versions sit in
    the WAL until a checkpoint. So: empty the WAL, rebuild the file (VACUUM),
    empty the WAL again. True when the last checkpoint was not blocked by a
    reader; it is retried for up to ten seconds first.
    """
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        for attempt in range(10):
            busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
            if not busy:
                return True
            time.sleep(1)
        return False
    finally:
        conn.close()


def left_over(conn: Connection, org_id: str) -> dict[str, int]:
    """Rows still carrying the organisation's id, and its own row."""
    check_org_id(org_id)
    left: dict[str, int] = {}
    for table in org_tables(conn):
        count = conn.execute(
            text(f'SELECT count(*) FROM "{table}" WHERE org_id = :o'), {"o": org_id}
        ).scalar_one()
        if count:
            left[table] = count
    if conn.execute(text("SELECT count(*) FROM organisations WHERE id = :o"),
                    {"o": org_id}).scalar_one():
        left["organisations"] = 1
    return left


def sweep(conn: Connection, org_id: str) -> dict[str, int]:
    """A request or job already running when the delete began can still write
    a row after it. Delete whatever is left, then count again."""
    if left_over(conn, org_id):
        delete_rows(conn, org_id, {})
    return left_over(conn, org_id)


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


_BACKUP_FOLDER = re.compile(r"(\d{8}T\d{6}Z)_([0-9a-f]{32})")


def prune_backups(backup_root: Path, now: datetime,
                  keep_days: int = BACKUP_KEEP_DAYS) -> list[Path]:
    """Remove delete backups older than `keep_days`. Only folders named
    `<stamp>_<org id>` are ever touched."""
    if not backup_root.is_dir():
        return []
    cutoff = _naive_utc(now) - timedelta(days=keep_days)
    removed: list[Path] = []
    for folder in sorted(backup_root.iterdir()):
        match = _BACKUP_FOLDER.fullmatch(folder.name)
        if not match or not folder.is_dir() or folder.is_symlink():
            continue
        if datetime.strptime(match.group(1), _STAMP) < cutoff:
            shutil.rmtree(folder)
            removed.append(folder)
    return removed


@dataclass
class Result:
    org_id: str
    org_name: str | None
    deleted: dict[str, int]
    total: int
    platform_rows_removed: int
    files_removed: int
    bytes_removed: int
    remaining: dict[str, int]
    compacted: bool
    backup_folder: str | None
    backup_expires_at: str | None


def _result(found: Preview, deleted: dict[str, int], files: tuple[int, int],
            remaining: dict[str, int], compacted: bool,
            backup: Path | None, now: datetime) -> Result:
    expires = _naive_utc(now) + timedelta(days=BACKUP_KEEP_DAYS)
    return Result(
        org_id=found.org_id,
        org_name=found.org_name,
        deleted=deleted,
        total=sum(n for table, n in deleted.items()
                  if not table.startswith("platform:") and table != "organisations"),
        platform_rows_removed=sum(n for table, n in deleted.items()
                                  if table.startswith("platform:")),
        files_removed=files[0],
        bytes_removed=files[1],
        remaining=remaining,
        compacted=compacted,
        backup_folder=str(backup) if backup else None,
        backup_expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ") if backup else None,
    )


def apply_sync(engine: Engine, db_path: Path, storage_root: Path, org_id: str, *,
               backup_root: Path | None, now: datetime) -> Result:
    """The whole delete on any copy of the database (the script's runner).
    `backup_root=None` makes no backup (staging copies)."""
    check_org_id(org_id)
    if backup_root is not None:
        prune_backups(backup_root, now)
    with engine.connect() as conn:
        found = preview(conn, org_id, storage_root)
    backup = (make_backup(db_path, storage_root, org_id, backup_root, now)
              if backup_root is not None else None)
    with engine.begin() as conn:
        deactivate(conn, org_id)
    with engine.begin() as conn:
        deleted = delete_rows(conn, org_id, found.platform_rows)
    files = delete_files(storage_root, org_id)
    compacted = compact(db_path)
    with engine.begin() as conn:
        late = left_over(conn, org_id)
        remaining = sweep(conn, org_id) if late else {}
    if late:
        compacted = compact(db_path)
    return _result(found, deleted, files, remaining, compacted, backup, now)


def sqlite_file(database_url: str) -> Path:
    """The file behind a SQLite URL; anything else is refused."""
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            return Path(database_url[len(prefix):])
    raise ValueError("Deleting an organisation needs the SQLite database.")


async def apply_live(org_id: str, *, backup_root: Path, now: datetime,
                     wait_seconds: int = 60) -> Result:
    """The whole delete on the live engine (the dashboard's runner).

    Same steps as `apply_sync`, plus what only the running server can do:
    wait for the organisation's running jobs, and drop what memory holds.
    Blocking file work runs in a thread so the server keeps answering.
    """
    from app.config import get_settings
    from app.database import engine
    from app.insights import cache
    from app.jobs import sender
    from app.jobs.queue import job_queue

    check_org_id(org_id)
    settings = get_settings()
    db_path = sqlite_file(settings.resolved_database_url)
    storage_root = settings.storage_path

    await asyncio.to_thread(prune_backups, backup_root, now)
    async with engine.connect() as conn:
        found = await conn.run_sync(preview, org_id, storage_root)
    backup = await asyncio.to_thread(make_backup, db_path, storage_root, org_id,
                                     backup_root, now)
    async with engine.begin() as conn:
        await conn.run_sync(deactivate, org_id)
    for _ in range(wait_seconds):
        if job_queue.running_count(org_id) == 0:
            break
        await asyncio.sleep(1)
    async with engine.begin() as conn:
        deleted = await conn.run_sync(delete_rows, org_id, found.platform_rows)
    files = await asyncio.to_thread(delete_files, storage_root, org_id)
    cache.clear()
    sender.forget_org(org_id)
    compacted = await asyncio.to_thread(compact, db_path)
    async with engine.begin() as conn:
        late = await conn.run_sync(left_over, org_id)
        remaining = await conn.run_sync(sweep, org_id) if late else {}
    if late:
        compacted = await asyncio.to_thread(compact, db_path)
    return _result(found, deleted, files, remaining, compacted, backup, now)
