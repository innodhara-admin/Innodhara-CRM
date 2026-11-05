"""Make `proposals.pricing_table_id` and `pricing_version` nullable.

Owner's decision, 2026-09-08: a rate card is OPTIONAL. An offering whose
prices live inside its own Word document has nothing to put in one, and the
simple flow never reads one -- every figure in that document comes from a tag
and the salesperson's own answer.

**Only a database that already exists needs this.** `create_all` builds a new
one correctly from the model, so a fresh environment must not run it and will
say so if you try.

SQLite cannot drop a NOT NULL in place, so this is the rebuild SQLite's own
documentation prescribes: create the new shape, copy every row, swap, restore
the indexes. Foreign keys are off for the swap and checked again afterwards --
`proposal_revisions` points at this table.

Safe to run twice: it looks at the live schema first and does nothing if the
columns are already nullable. It refuses to finish if the row count changed.

    python scripts/migrations/2026-09-08_optional_rate_card.py [path/to.db]

Defaults to data/salesplatform.db. Takes a timestamped copy of the file
before touching it and prints where it put it.
"""
import os
import shutil
import sqlite3
import sys
import time

DEFAULT_DB = os.path.join("data", "salesplatform.db")

NEW_TABLE = """
CREATE TABLE proposals_migrated (
	lead_id VARCHAR(32) NOT NULL,
	program_id VARCHAR(32) NOT NULL,
	title VARCHAR(300) NOT NULL,
	status VARCHAR(30) NOT NULL,
	template_id VARCHAR(32) NOT NULL,
	template_version INTEGER NOT NULL,
	pricing_table_id VARCHAR(32),
	pricing_version INTEGER,
	content_md TEXT NOT NULL,
	variables JSON NOT NULL,
	line_items JSON NOT NULL,
	total_amount FLOAT NOT NULL,
	currency VARCHAR(10) NOT NULL,
	docx_path VARCHAR(500),
	pdf_path VARCHAR(500),
	created_by VARCHAR(32) NOT NULL,
	sent_at DATETIME,
	sent_message_id VARCHAR(32),
	project_id VARCHAR(32),
	amends_proposal_id VARCHAR(32),
	special_price_approval_id VARCHAR(32),
	id VARCHAR(32) NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	org_id VARCHAR(32) NOT NULL,
	filled_json TEXT DEFAULT '[]',
	template_kind VARCHAR(20) DEFAULT 'markdown',
	PRIMARY KEY (id),
	FOREIGN KEY(lead_id) REFERENCES leads (id),
	FOREIGN KEY(program_id) REFERENCES programs (id),
	FOREIGN KEY(template_id) REFERENCES proposal_templates (id),
	FOREIGN KEY(pricing_table_id) REFERENCES pricing_tables (id),
	FOREIGN KEY(created_by) REFERENCES users (id),
	FOREIGN KEY(org_id) REFERENCES organisations (id)
)
"""

INDEXES = [
    "CREATE INDEX ix_proposals_program_id ON proposals (program_id)",
    "CREATE INDEX ix_proposals_project_id ON proposals (project_id)",
    "CREATE INDEX ix_proposals_org_status ON proposals (org_id, status)",
    "CREATE INDEX ix_proposals_lead_id ON proposals (lead_id)",
    "CREATE INDEX ix_proposals_org_id ON proposals (org_id)",
    "CREATE INDEX ix_proposals_org_lead ON proposals (org_id, lead_id)",
]


def notnull(conn) -> dict:
    return {row[1]: row[3] for row in conn.execute("PRAGMA table_info(proposals)")}


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    if not os.path.exists(path):
        print("no database at %s -- nothing to migrate. A new one is built "
              "from the model and is already correct." % path)
        return 0

    conn = sqlite3.connect(path)
    columns = notnull(conn)
    if not columns:
        print("%s has no `proposals` table; create_all will build it "
              "correctly. Nothing to do." % path)
        return 0
    if not columns.get("pricing_table_id") and not columns.get("pricing_version"):
        print("%s is already migrated (both columns nullable)." % path)
        return 0

    before = conn.execute("SELECT count(*) FROM proposals").fetchone()[0]
    backup = "%s.before-optional-rate-card.%s" % (path, time.strftime("%Y%m%d%H%M%S"))
    conn.close()
    shutil.copyfile(path, backup)
    print("backed up %s -> %s" % (path, backup))

    conn = sqlite3.connect(path)
    # Foreign keys must be off for the swap: proposal_revisions references
    # this table, and SQLite would otherwise repoint it at the temporary one.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        with conn:
            conn.executescript(NEW_TABLE)
            columns_sql = ", ".join(
                row[1] for row in conn.execute("PRAGMA table_info(proposals)"))
            conn.execute("INSERT INTO proposals_migrated (%s) SELECT %s FROM proposals"
                         % (columns_sql, columns_sql))
            conn.execute("DROP TABLE proposals")
            conn.execute("ALTER TABLE proposals_migrated RENAME TO proposals")
            for statement in INDEXES:
                conn.execute(statement)
    except Exception:
        conn.close()
        sys.stderr.write("migration failed; %s is untouched and your backup is "
                         "at %s\n" % (path, backup))
        raise

    after = conn.execute("SELECT count(*) FROM proposals").fetchone()[0]
    columns = notnull(conn)
    violations = list(conn.execute("PRAGMA foreign_key_check"))
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()

    print("rows %d -> %d" % (before, after))
    print("pricing_table_id notnull=%s  pricing_version notnull=%s"
          % (columns["pricing_table_id"], columns["pricing_version"]))
    if before != after:
        sys.stderr.write("ROW COUNT CHANGED -- restore %s from %s\n" % (path, backup))
        return 3
    if violations:
        sys.stderr.write("foreign key violations after the rebuild: %s\n"
                         % violations[:5])
        return 4
    if columns["pricing_table_id"] or columns["pricing_version"]:
        sys.stderr.write("the columns are still NOT NULL\n")
        return 5
    print("migrated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
