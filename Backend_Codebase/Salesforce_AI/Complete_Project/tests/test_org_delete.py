# tests/test_org_delete.py
"""Deleting a whole organisation (spec 2026-10-28-org-delete-design.md).

These tests drive the service's step functions directly, on throwaway SQLite
files built from the models, so every table can hold a row for the
organisation being deleted AND for a bystander, and the bystander can be
compared byte for byte afterwards. The API and script tests build on the
helpers here.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.database import Base
from app.services import org_delete

NOW = datetime(2026, 10, 28, 12, 0, 0)


# ── helpers (also used by the API and script tests) ─────────────────────────
def _fresh_db(tmp_path: Path, name: str = "org.db") -> Engine:
    """A new SQLite file with every model table, in WAL mode like live."""
    engine = create_engine(f"sqlite:///{(tmp_path / name).as_posix()}")

    @event.listens_for(engine, "connect")
    def _wal(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    return engine


def _value(col_type: str) -> object:
    if col_type in ("String", "Text"):
        return uuid4().hex
    if col_type in ("Integer", "Float"):
        return 0
    if col_type == "Boolean":
        return 0
    if col_type == "Date":
        return "2026-10-28"
    if col_type == "DateTime":
        return "2026-10-28 00:00:00"
    if col_type == "JSON":
        return "{}"
    raise AssertionError(f"no test value for {col_type}")


def _insert(conn: Connection, table: str, values: dict) -> None:
    cols = ", ".join(values)
    marks = ", ".join(f":{c}" for c in values)
    conn.execute(text(f'INSERT INTO "{table}" ({cols}) VALUES ({marks})'), values)


def _row(table: str, **fixed) -> dict:
    """Every column of a model table filled, then `fixed` on top."""
    values = {
        c.name: _value(type(c.type).__name__)
        for c in Base.metadata.tables[table].columns
    }
    values.update(fixed)
    return values


def _fill(conn: Connection, org_id: str, name: str | None = None) -> dict[str, str]:
    """The organisation row plus ONE row in every org table. Returns table -> row id."""
    _insert(conn, "organisations", _row(
        "organisations", id=org_id, name=name or f"Org {org_id[:6]}",
        slug=uuid4().hex, is_active=1,
    ))
    ids = {}
    for table in org_delete.org_tables(conn):
        cols = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table}")')}
        if table in Base.metadata.tables:
            values = _row(table, org_id=org_id)
        else:
            values = {c: uuid4().hex for c in cols}
            values["org_id"] = org_id
        ids[table] = values.get("id")
        _insert(conn, table, values)
    return ids


def _table_hash(conn: Connection, table: str, where: str = "1=1", params=None) -> str:
    rows = conn.execute(text(f'SELECT * FROM "{table}" WHERE {where}'), params or {}).all()
    blob = json.dumps(sorted(repr(tuple(r)) for r in rows))
    return hashlib.sha256(blob.encode()).hexdigest()


def _org_hashes(conn: Connection, org_id: str) -> dict[str, str]:
    out = {t: _table_hash(conn, t, "org_id = :o", {"o": org_id})
           for t in org_delete.org_tables(conn)}
    out["organisations"] = _table_hash(conn, "organisations", "id = :o", {"o": org_id})
    return out


def _db_hash(conn: Connection) -> dict[str, str]:
    names = [r[0] for r in conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: _table_hash(conn, t) for t in names}


def _two_orgs(engine: Engine) -> tuple[str, str, dict[str, str], dict[str, str]]:
    victim, bystander = uuid4().hex, uuid4().hex
    with engine.begin() as conn:
        v_ids = _fill(conn, victim, "Victim Learning (demo)")
        b_ids = _fill(conn, bystander, "Bystander Academy")
    return victim, bystander, v_ids, b_ids


def _platform_rows(engine: Engine, victim: str, v_ids: dict, b_ids: dict) -> dict[str, str]:
    """Platform rows (org_id NULL) and one bystander row that mentions the victim."""
    ids = {k: uuid4().hex for k in ("names_victim", "names_bystander", "names_nobody",
                                     "super", "mention")}
    with engine.begin() as conn:
        _insert(conn, "audit_log", _row("audit_log", id=ids["names_victim"], org_id=None,
                detail=json.dumps({"task_id": v_ids["leads"]})))
        _insert(conn, "audit_log", _row("audit_log", id=ids["names_bystander"], org_id=None,
                detail=json.dumps({"task_id": b_ids["leads"]})))
        _insert(conn, "audit_log", _row("audit_log", id=ids["names_nobody"], org_id=None,
                detail="{}"))
        _insert(conn, "users", _row("users", id=ids["super"], org_id=None,
                email="superadmin@platform-victim.com", role="super_admin"))
    return ids


# ── Task 1 ─────────────────────────────────────────────────────────────────
def test_org_tables_cover_every_model_table_with_org_id(tmp_path):
    engine = _fresh_db(tmp_path)
    with engine.connect() as conn:
        found = org_delete.org_tables(conn)
    expected = {t.name for t in Base.metadata.sorted_tables if "org_id" in t.c}
    assert set(found) == expected
    assert "organisations" not in found


def test_org_tables_find_a_table_the_models_do_not_know(tmp_path):
    engine = _fresh_db(tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE extra_notes (id TEXT, org_id TEXT, body TEXT)")
        found = org_delete.org_tables(conn)
    assert "extra_notes" in found
    known = [t for t in found if t in Base.metadata.tables]
    assert found.index("extra_notes") < min(found.index(t) for t in known)


@pytest.mark.parametrize("typed, name, ok", [
    ("DELETE YuviPep", "YuviPep", True),
    ("delete yuvipep", "YuviPep", True),
    ("  DELETE   YuviPep ", "YuviPep", True),
    ("delete northwind learning (DEMO)", "Northwind Learning (demo)", True),
    ("DELETE Yuvip", "YuviPep", False),
    ("DELETE YuviPep!", "YuviPep", False),
    ("YuviPep", "YuviPep", False),
    ("", "YuviPep", False),
])
def test_confirmation_matching(typed, name, ok):
    assert org_delete.confirmation_matches(typed, name) is ok


@pytest.mark.parametrize("bad", ["../" + "a" * 30, "A" * 32, "a" * 31, ""])
def test_bad_org_id_is_refused_before_any_file_is_touched(tmp_path, bad):
    storage = tmp_path / "storage"
    keep = storage / "orgs" / ("a" * 32) / "x.pdf"
    keep.parent.mkdir(parents=True)
    keep.write_bytes(b"keep")
    with pytest.raises(ValueError):
        org_delete.check_org_id(bad)
    with pytest.raises(ValueError):
        org_delete.delete_files(storage, bad)
    assert keep.read_bytes() == b"keep"
    assert sorted(p.name for p in storage.rglob("*")) == ["a" * 32, "orgs", "x.pdf"]


def test_preview_counts_and_changes_nothing(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, bystander, v_ids, b_ids = _two_orgs(engine)
    ids = _platform_rows(engine, victim, v_ids, b_ids)
    with engine.begin() as conn:
        _insert(conn, "audit_log", _row("audit_log", id=ids["mention"], org_id=bystander,
                detail=f"copied from {victim}"))
    with engine.connect() as conn:
        before = _db_hash(conn)
        preview = org_delete.preview(conn, victim, tmp_path / "storage")
        after = _db_hash(conn)
        tables = org_delete.org_tables(conn)
    assert before == after
    assert preview.org_exists and preview.org_name == "Victim Learning (demo)"
    assert preview.rows == {t: 1 for t in tables}
    assert preview.total == len(preview.rows)
    assert preview.platform_rows == {"audit_log": [ids["names_victim"]]}
    assert preview.other_org_mentions == {"audit_log": 1}
    assert len(preview.users) == 1 and set(preview.users[0]) == {"email", "role"}
    assert preview.files == 0 and preview.bytes == 0
    assert not preview.nothing_left


def test_delete_rows_leaves_the_bystander_identical(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, bystander, v_ids, b_ids = _two_orgs(engine)
    ids = _platform_rows(engine, victim, v_ids, b_ids)
    with engine.begin() as conn:
        _insert(conn, "audit_log", _row("audit_log", id=ids["mention"], org_id=bystander,
                detail=f"copied from {victim}"))
    with engine.connect() as conn:
        bystander_before = _org_hashes(conn, bystander)
        preview = org_delete.preview(conn, victim, tmp_path / "storage")
    with engine.begin() as conn:
        deleted = org_delete.delete_rows(conn, victim, preview.platform_rows)
    assert deleted["organisations"] == 1
    assert list(deleted)[-1] == "organisations"
    with engine.connect() as conn:
        for table in org_delete.org_tables(conn):
            left = conn.execute(text(f'SELECT count(*) FROM "{table}" WHERE org_id = :o'),
                                {"o": victim}).scalar()
            assert left == 0, table
        assert conn.execute(text("SELECT count(*) FROM organisations WHERE id = :o"),
                            {"o": victim}).scalar() == 0
        # The bystander's rows (its mention of the victim included) are untouched.
        assert _org_hashes(conn, bystander) == bystander_before
        kept = {r[0] for r in conn.execute(text("SELECT id FROM audit_log WHERE org_id IS NULL"))}
        assert kept == {ids["names_bystander"], ids["names_nobody"]}
        assert conn.execute(text("SELECT email FROM users WHERE org_id IS NULL")).scalar() \
            == "superadmin@platform-victim.com"


def test_files_go_and_a_lookalike_folder_stays(tmp_path):
    victim, bystander = uuid4().hex, uuid4().hex
    storage = tmp_path / "storage"
    files = {
        storage / "orgs" / victim / "a" / "b.pdf": b"victim-file",
        storage / "orgs" / bystander / "c.pdf": b"bystander",
        storage / "orgs" / f"{victim}-old" / "d.pdf": b"lookalike",
    }
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    assert org_delete.delete_files(storage, victim) == (1, len(b"victim-file"))
    assert not (storage / "orgs" / victim).exists()
    assert (storage / "orgs" / bystander / "c.pdf").read_bytes() == b"bystander"
    assert (storage / "orgs" / f"{victim}-old" / "d.pdf").read_bytes() == b"lookalike"
    assert org_delete.delete_files(storage, victim) == (0, 0)


def test_outside_credentials_file_is_reported_not_deleted(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, _, _, _ = _two_orgs(engine)
    outside = tmp_path / "sa.json"
    outside.write_text("{}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE org_settings SET calendar_integration = :c WHERE org_id = :o"),
                     {"c": json.dumps({"credentials_file": str(outside)}), "o": victim})
    with engine.connect() as conn:
        preview = org_delete.preview(conn, victim, tmp_path / "storage")
    assert preview.outside_files == [str(outside)]
    org_delete.delete_files(tmp_path / "storage", victim)
    assert outside.exists()


def test_backup_holds_the_database_and_the_files(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, _, _, _ = _two_orgs(engine)
    storage = tmp_path / "storage"
    pdf = storage / "orgs" / victim / "a" / "b.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 victim")
    folder = org_delete.make_backup(tmp_path / "org.db", storage, victim,
                                    tmp_path / "backups", NOW)
    assert folder == tmp_path / "backups" / f"20261028T120000Z_{victim}"
    dbs = list(folder.glob("*.db"))
    assert len(dbs) == 1
    copy = create_engine(f"sqlite:///{dbs[0].as_posix()}")
    with copy.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM leads WHERE org_id = :o"),
                            {"o": victim}).scalar() == 1
    copy.dispose()
    assert (folder / "files" / "a" / "b.pdf").read_bytes() == b"%PDF-1.4 victim"


# ── Task 2 ─────────────────────────────────────────────────────────────────
def test_compact_leaves_no_bytes_of_the_org(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, bystander = uuid4().hex, uuid4().hex
    with engine.begin() as conn:
        _fill(conn, victim, "Zephyrine Trace Org")
        _fill(conn, bystander, "Bystander Academy")
    for _ in range(3):  # leave the victim's pages in the WAL too
        with engine.begin() as conn:
            conn.execute(text("UPDATE leads SET name = name || 'x' WHERE org_id = :o"),
                         {"o": victim})
    with engine.begin() as conn:
        org_delete.delete_rows(conn, victim, {})
    assert org_delete.compact(tmp_path / "org.db") is True
    blobs = [p.read_bytes() for p in tmp_path.glob("org.db*") if p.is_file()]
    joined = b"".join(blobs)
    assert victim.encode() not in joined
    assert b"Zephyrine Trace Org" not in joined
    assert bystander.encode() in joined


def test_sweep_catches_a_late_row(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, _, _, _ = _two_orgs(engine)
    with engine.begin() as conn:
        org_delete.delete_rows(conn, victim, {})
        _insert(conn, "llm_usage", _row("llm_usage", org_id=victim))
        assert org_delete.left_over(conn, victim) == {"llm_usage": 1}
        assert org_delete.sweep(conn, victim) == {}
        assert org_delete.left_over(conn, victim) == {}


def test_prune_removes_only_old_backups(tmp_path):
    root = tmp_path / "backups"
    org = uuid4().hex
    old = root / f"20261020T000000Z_{org}"
    recent = root / f"20261025T000000Z_{org}"
    notes = root / "notes"
    odd = root / "20261001T000000Z_badid"
    for folder in (old, recent, notes, odd):
        folder.mkdir(parents=True)
        (folder / "database.db").write_bytes(b"x")
    assert org_delete.prune_backups(root, NOW) == [old]
    assert not old.exists()
    assert recent.exists() and notes.exists() and odd.exists()
    assert org_delete.prune_backups(tmp_path / "missing", NOW) == []


def _storage_with_files(tmp_path: Path, victim: str, bystander: str) -> Path:
    storage = tmp_path / "storage"
    for org, name in ((victim, "v.pdf"), (bystander, "b.pdf")):
        path = storage / "orgs" / org / "cards" / name
        path.parent.mkdir(parents=True)
        path.write_bytes(f"file of {org}".encode())
    return storage


def test_apply_sync_end_to_end_on_a_copy(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, bystander, v_ids, b_ids = _two_orgs(engine)
    _platform_rows(engine, victim, v_ids, b_ids)
    storage = _storage_with_files(tmp_path, victim, bystander)
    with engine.connect() as conn:
        bystander_before = _org_hashes(conn, bystander)
    result = org_delete.apply_sync(engine, tmp_path / "org.db", storage, victim,
                                   backup_root=tmp_path / "backups", now=NOW)
    assert result.remaining == {}
    assert result.compacted is True
    assert result.org_name == "Victim Learning (demo)"
    assert result.platform_rows_removed == 1
    assert result.files_removed == 1
    assert result.total == len(result.deleted) - 2  # minus platform + organisations
    assert result.backup_folder == str(tmp_path / "backups" / f"20261028T120000Z_{victim}")
    assert result.backup_expires_at == "2026-11-04T12:00:00Z"
    assert Path(result.backup_folder, "database.db").exists()
    assert not (storage / "orgs" / victim).exists()
    assert (storage / "orgs" / bystander / "cards" / "b.pdf").exists()
    with engine.connect() as conn:
        assert _org_hashes(conn, bystander) == bystander_before
        assert org_delete.left_over(conn, victim) == {}


def test_apply_sync_without_backup_makes_none(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, _, _, _ = _two_orgs(engine)
    result = org_delete.apply_sync(engine, tmp_path / "org.db", tmp_path / "storage",
                                   victim, backup_root=None, now=NOW)
    assert result.backup_folder is None and result.backup_expires_at is None
    assert result.remaining == {}
    assert not (tmp_path / "backups").exists()


def test_running_count_and_forget_org():
    from app.jobs import sender
    from app.jobs.queue import JobQueue

    victim, other = uuid4().hex, uuid4().hex
    queue = JobQueue()
    queue._running_orgs = {victim: 2}
    assert queue.running_count(victim) == 2
    assert queue.running_count(other) == 0
    sender._send_history[(victim, "email")] = [1.0]
    sender._send_history[(other, "email")] = [2.0]
    try:
        sender.forget_org(victim)
        assert (victim, "email") not in sender._send_history
        assert sender._send_history[(other, "email")] == [2.0]
    finally:
        sender._send_history.pop((other, "email"), None)
