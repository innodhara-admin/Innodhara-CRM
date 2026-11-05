"""Add `proposal_fill_sessions.mou_id` and `.document_type` (D-C).

The fill session's status machine serves both document types rather than
being duplicated: `mou_id` is where a built MOU is recorded beside
`proposal_id`, and `document_type` is the discriminator without which an MOU
fill and a proposal fill for the same lead, programme and chat are
indistinguishable to `find_for_chat`.

`create_all` creates a missing table but never adds a column, so a database
that already exists needs this run once. A brand-new one does not.

Idempotent PER COLUMN: either, both or neither may already be there, and each
is checked separately. Backs up THROUGH SQLITE, never with the filesystem --
this database is in WAL mode with a multi-megabyte -wal, and a plain file copy
silently drops whatever has not been checkpointed (measured while writing the
D-B migration: a `cp` copy held 17 proposal_templates where the live database
had 18).

    .venv/bin/python scripts/migrations/2026-09-09_fill_session_mou.py [db]
"""
import sqlite3
import sys
from datetime import datetime

DEFAULT_DB = "data/salesplatform.db"
TABLE = "proposal_fill_sessions"
COLUMNS = (
    ("mou_id", "VARCHAR(32)"),
    ("document_type", "VARCHAR(20) NOT NULL DEFAULT 'proposal'"),
)


def has_column(conn, table: str, column: str) -> bool:
    return any(row[1] == column for row in
               conn.execute(f"PRAGMA table_info({table})"))


def _backup_to(db_path: str, dest: str) -> None:
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
    conn.execute("PRAGMA busy_timeout = 30000")

    if not has_column(conn, TABLE, "status"):
        print(f"REFUSING: {db_path} has no {TABLE} table to migrate")
        return 1

    missing = [(c, t) for c, t in COLUMNS if not has_column(conn, TABLE, c)]
    if not missing:
        counts = dict(conn.execute(
            f"SELECT document_type, count(*) FROM {TABLE} "
            f"GROUP BY document_type"))
        print(f"both columns already present - nothing to do. {counts}")
        return 0

    before = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    backup = f"{db_path}.before-fill-mou.{datetime.now():%Y%m%d%H%M%S}"
    _backup_to(db_path, backup)
    print(f"backed up to {backup}")

    for column, decl in missing:
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {column} {decl}")
        print(f"added {column}")

    after = conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    counts = dict(conn.execute(
        f"SELECT document_type, count(*) FROM {TABLE} GROUP BY document_type"))
    orphan_mou = conn.execute(
        f"SELECT count(*) FROM {TABLE} WHERE mou_id IS NOT NULL").fetchone()[0]

    if before != after:
        print(f"REFUSING: row count moved {before} -> {after}")
        return 1
    if violations:
        print(f"REFUSING: foreign key violations {violations}")
        return 1
    if orphan_mou:
        print(f"REFUSING: {orphan_mou} rows already carry an mou_id")
        return 1
    for column, _ in COLUMNS:
        if not has_column(conn, TABLE, column):
            print(f"REFUSING: {column} is still not there")
            return 1

    print(f"ok: {before} -> {after} rows, document_type = {counts}, "
          f"mou_id null on all of them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
