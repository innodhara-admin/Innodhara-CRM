"""Add `proposal_templates.document_type` (D-B).

A programme carries ONE current proposal template and ONE current MOU
template, so `is_current` becomes current-per-document-type. `create_all`
creates a missing table but never adds a column, so a database that already
exists needs this script run once. A brand-new one does not.

**This is not the table rebuild D37 needed.** Dropping a NOT NULL forces
SQLite to rebuild a table; ADDING a column with a constant default does not,
so this is a single cheap statement and every existing row becomes
'proposal', which is what all 18 of them are.

Idempotent: reads the schema and does nothing if the column is already there.
Backs the database up first, and REFUSES to report success if the row count
moved or a foreign key broke.

    .venv/bin/python scripts/migrations/2026-09-09_template_document_type.py [db]
"""
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = "data/salesplatform.db"
TABLE = "proposal_templates"
COLUMN = "document_type"


def has_column(conn, table: str, column: str) -> bool:
    return any(row[1] == column for row in
               conn.execute(f"PRAGMA table_info({table})"))


def _backup_to(db_path: str, dest: str) -> None:
    """Copy the database THROUGH SQLITE, never with the filesystem.

    This database runs in WAL mode and its `-wal` file is 4 MB: a plain
    `shutil.copyfile` of `salesplatform.db` alone silently drops every
    transaction not yet checkpointed back into the main file. Measured while
    writing this script: a `cp` copy showed 17 `proposal_templates` where the
    live database had 18. A backup like that is not a backup -- it restores a
    database missing whatever was most recently written, which is exactly the
    work someone would most want back.

    `Connection.backup` reads through the WAL and produces a consistent file.
    """
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    conn = sqlite3.connect(db_path, timeout=30)
    conn.isolation_level = None
    # The backend may be serving while this runs; wait for the
    # write lock rather than failing on it (database.py sets the
    # same 30s busy_timeout for exactly this reason).
    conn.execute("PRAGMA busy_timeout = 30000")

    if not has_column(conn, TABLE, "is_current"):
        print(f"REFUSING: {db_path} has no {TABLE} table to migrate")
        return 1

    if has_column(conn, TABLE, COLUMN):
        counts = dict(conn.execute(
            f"SELECT {COLUMN}, count(*) FROM {TABLE} GROUP BY {COLUMN}"))
        print(f"{COLUMN} already present - nothing to do. {counts}")
        return 0

    before = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    current_before = conn.execute(
        f"SELECT count(*) FROM {TABLE} WHERE is_current = 1").fetchone()[0]

    backup = f"{db_path}.before-document-type.{datetime.now():%Y%m%d%H%M%S}"
    _backup_to(db_path, backup)
    print(f"backed up to {backup}")

    conn.execute(
        f"ALTER TABLE {TABLE} "
        f"ADD COLUMN {COLUMN} VARCHAR(20) NOT NULL DEFAULT 'proposal'"
    )

    after = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    current_after = conn.execute(
        f"SELECT count(*) FROM {TABLE} WHERE is_current = 1").fetchone()[0]
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    counts = dict(conn.execute(
        f"SELECT {COLUMN}, count(*) FROM {TABLE} GROUP BY {COLUMN}"))

    if before != after:
        print(f"REFUSING: row count moved {before} -> {after}")
        return 1
    if current_before != current_after:
        print(f"REFUSING: current count moved "
              f"{current_before} -> {current_after}")
        return 1
    if violations:
        print(f"REFUSING: foreign key violations {violations}")
        return 1
    if not has_column(conn, TABLE, COLUMN):
        print("REFUSING: the column is still not there")
        return 1

    print(f"ok: {before} -> {after} rows, {current_before} current unchanged, "
          f"{COLUMN} = {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
