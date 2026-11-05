# tests/test_org_delete_script.py
"""scripts/delete_organisation.py: the same delete, on any copy of the database."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.services import org_delete
from tests.test_org_delete import _db_hash, _fresh_db, _org_hashes, _storage_with_files, _two_orgs

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "delete_organisation.py"


def _script():
    spec = importlib.util.spec_from_file_location("delete_organisation", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup(tmp_path):
    engine = _fresh_db(tmp_path)
    victim, bystander, _, _ = _two_orgs(engine)
    storage = _storage_with_files(tmp_path, victim, bystander)
    return engine, victim, bystander, storage


def _args(tmp_path, storage, org_id, *extra) -> list[str]:
    return ["--org-id", org_id, "--db", str(tmp_path / "org.db"),
            "--storage", str(storage), *extra]


def test_script_dry_run_changes_nothing(tmp_path, capsys):
    engine, victim, _, storage = _setup(tmp_path)
    with engine.connect() as conn:
        before = _db_hash(conn)
    assert _script().main(_args(tmp_path, storage, victim)) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "org.db") in out
    assert "records" in out and "1 file" in out
    with engine.connect() as conn:
        assert _db_hash(conn) == before
    assert (storage / "orgs" / victim).is_dir()


def test_script_apply_no_backup(tmp_path):
    engine, victim, bystander, storage = _setup(tmp_path)
    with engine.connect() as conn:
        bystander_before = _org_hashes(conn, bystander)
    code = _script().main(_args(tmp_path, storage, victim, "--apply", "--no-backup"))
    assert code == 0
    with engine.connect() as conn:
        assert org_delete.left_over(conn, victim) == {}
        assert _org_hashes(conn, bystander) == bystander_before
    assert not (storage / "orgs" / victim).exists()
    assert not any(p.name.endswith(victim) for p in tmp_path.rglob("*") if p.is_dir())


def test_script_finishes_a_half_done_delete(tmp_path, capsys):
    engine, victim, _, storage = _setup(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM organisations WHERE id = :o"), {"o": victim})
    script = _script()
    assert script.main(_args(tmp_path, storage, victim, "--apply", "--no-backup")) == 0
    with engine.connect() as conn:
        assert org_delete.left_over(conn, victim) == {}
    assert not (storage / "orgs" / victim).exists()
    capsys.readouterr()
    assert script.main(_args(tmp_path, storage, victim, "--apply", "--no-backup")) == 2
    assert "Nothing is left" in capsys.readouterr().out


def test_script_refuses_a_bad_id(tmp_path):
    engine, victim, _, storage = _setup(tmp_path)
    with engine.connect() as conn:
        before = _db_hash(conn)
    assert _script().main(_args(tmp_path, storage, "../x", "--apply", "--no-backup")) == 2
    with engine.connect() as conn:
        assert _db_hash(conn) == before
    assert (storage / "orgs" / victim).is_dir()
