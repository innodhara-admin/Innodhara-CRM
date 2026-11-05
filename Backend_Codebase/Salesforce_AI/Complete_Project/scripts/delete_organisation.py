"""Delete one organisation from a copy of the database, leaving no trace (28 Oct 2026).

    python scripts/delete_organisation.py --org-id ID --db PATH --storage PATH
    python scripts/delete_organisation.py --org-id ID --db PATH --storage PATH --apply
    python scripts/delete_organisation.py ... --apply --no-backup

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-28-org-delete-design.md.
Runs exactly the steps of the dashboard's "delete this organisation"
(app/services/org_delete.py), so a staging copy is cleaned by the code that
cleans live. What only the running server can do (waiting for its jobs,
dropping what its memory holds) is not done here.

* --db and --storage are required, so the database is never a guess, and both
  are printed before anything else.
* Without --apply it only reads and prints what would go.
* --no-backup is for staging copies: backing up a copy only makes another copy.
* It still finds and removes what is left after a delete that stopped half
  way, and says "Nothing is left" when there is nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402

from app.models.base import utcnow  # noqa: E402
from app.services import org_delete  # noqa: E402


def _size(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 100_000 else f"{n} bytes"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _print_preview(found: org_delete.Preview) -> None:
    name = found.org_name or "(organisation row already gone)"
    print(f"Organisation: {name} ({found.org_id})")
    print(f"Would delete {_plural(found.total, 'record')} in "
          f"{_plural(len(found.rows), 'table')}:")
    for table, count in sorted(found.rows.items()):
        print(f"  {table}: {count}")
    platform = sum(len(ids) for ids in found.platform_rows.values())
    print(f"Platform rows naming it: {platform} {dict((t, len(i)) for t, i in found.platform_rows.items())}")
    print(f"Files: {_plural(found.files, 'file')}, {_size(found.bytes)}"
          f"{'' if found.folder_exists else ' (no folder)'}")
    print(f"People who lose their sign-in: {len(found.users)}")
    for user in found.users:
        print(f"  {user['email']} ({user['role']})")
    if found.outside_files:
        print("Files outside its folder named in its settings (kept):")
        for path in found.outside_files:
            print(f"  {path}")
    if found.other_org_mentions:
        print(f"Rows of OTHER organisations that mention it (kept): {found.other_org_mentions}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--storage", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)

    print(f"Database: {args.db}")
    print(f"Storage:  {args.storage}")
    try:
        org_id = org_delete.check_org_id(args.org_id)
    except ValueError as exc:
        print(f"Refused: {exc}")
        return 2
    if not args.db.is_file():
        print("Refused: that database file does not exist.")
        return 2

    engine = create_engine(f"sqlite:///{args.db.resolve().as_posix()}",
                           connect_args={"timeout": 30})
    try:
        with engine.connect() as conn:
            found = org_delete.preview(conn, org_id, args.storage)
        if found.nothing_left:
            print("Nothing is left of this organisation here.")
            return 2
        _print_preview(found)
        if not args.apply:
            print("Dry run: nothing was changed. Add --apply to delete.")
            return 0

        backup_root = None if args.no_backup else org_delete.default_backup_root()
        result = org_delete.apply_sync(engine, args.db, args.storage, org_id,
                                       backup_root=backup_root, now=utcnow())
    finally:
        engine.dispose()

    print(f"Deleted {_plural(result.total, 'record')}, "
          f"{_plural(result.platform_rows_removed, 'platform row')}, "
          f"{_plural(result.files_removed, 'file')} ({_size(result.bytes_removed)}).")
    print(f"Database compacted: {'yes' if result.compacted else 'NO (a reader held it)'}")
    print(f"Backup: {result.backup_folder or 'none'}"
          f"{f' (removed after {result.backup_expires_at})' if result.backup_expires_at else ''}")
    if result.remaining:
        print(f"STILL LEFT: {result.remaining}")
        return 1
    print("Nothing of this organisation is left in this database or its storage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
