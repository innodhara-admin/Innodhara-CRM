"""Regenerate the schema ER diagram from the live SQLAlchemy models.

    python scripts/build_schema_erd.py            # writes scripts/assets/erd/index.html
    python scripts/build_schema_erd.py --out DIR  # writes into a checkout to publish

The page published at ekaghni.github.io/yuvipep-schema-diagram was hand-written
against an older schema: 29 tables, and it still named `school_intelligence`,
which has since been renamed `client_intelligence`. Hand-patching it would drift
again, so the DATA is generated from `Base.metadata` and only the presentation
(CSS, layout, the hover-to-trace behaviour) is kept from the original page as a
template.

The template's contract, which this script emits against:
    field  = [name, type, flag]
    flag   = 'pk' | 'fk:<table>' | 'fk-soft:<table>' | 'org' | 'soft' | ''
             'fk:'      -> solid connector to that table's id
             'fk-soft:' -> dashed connector (nullable FK)
             'org'      -> org_id column; drawn as a tenant badge, not a wire
             'soft'     -> an id stored without a database constraint
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMPLATE = ROOT / "scripts" / "assets" / "erd_template.html"
DEFAULT_OUT = ROOT / "scripts" / "assets" / "erd"

from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401

# ── domains ──────────────────────────────────────────────────────────────────
# Ordered, and asserted to cover every table exactly once — a new table added to
# the models without a home here fails the build rather than vanishing from the
# diagram.
ZONES: list[tuple[str, str, str, list[str]]] = [
    ("identity", "Tenancy &amp; Identity",
     "The tenant, the staff who work it, and what each of them can do.",
     ["organisations", "org_settings", "users", "user_skills",
      "device_tokens", "notifications"]),
    ("leads", "Clients &amp; Relationships",
     "Clients in the pipeline, the people at them, and the consent trail.",
     ["leads", "lead_state_history", "contacts", "consent_records",
      "client_intelligence"]),
    ("meetings", "Meetings &amp; Memory",
     "Recorded and typed conversations, and what the organisation remembers.",
     ["meetings", "transcripts", "memory_chunks"]),
    ("projects", "The Project Layer",
     "One concrete piece of work: its versioned plan, its people, its promises.",
     ["projects", "project_members", "stakeholders", "action_plans",
      "client_commitments", "conflicts", "playbooks", "playbook_suggestions"]),
    ("work", "Work Management",
     "Tasks and everything the engines do about them.",
     ["action_items", "assignments", "reminders", "progress_events",
      "incidents", "ai_decisions", "digests", "resource_bookings"]),
    ("catalogue", "Catalogue &amp; Commercials",
     "What is sold, at what price, and every document and rupee that follows.",
     ["programs", "pricing_tables", "proposal_templates", "message_templates",
      "proposals", "proposal_revisions", "deliverables", "invoices",
      "payments", "vendors"]),
    ("comms", "Communication &amp; Approvals",
     "Everything said to a client, everything they said back, and the human gate.",
     ["threads", "inbound_messages", "outbound_messages",
      "message_delivery_log", "approvals", "approval_rules", "followups",
      "demos", "demo_teams", "demo_team_members"]),
    ("ops", "Platform &amp; Audit",
     "The machinery, and the four trails that make every action explainable.",
     ["jobs", "audit_log", "idempotency_records", "llm_usage",
      "assistant_turns"]),
]

# Colours for the zone ids the original page did not have. Defined once in
# `:root` only, because the template's dark-mode block deliberately does not
# override the --z-* lane colours — they are chosen to read on either ground.
NEW_ZONE_COLOURS = {
    "projects": "#7d6fa0", "work": "#5f8f5a", "catalogue": "#a97418",
}

# Columns whose name ends in _id but which are deliberately not constraints.
SOFT_SUFFIX = ("_id", "_by")


def type_label(col) -> str:
    """Render a column type in the diagram's own shorthand."""
    t = col.type
    name = type(t).__name__.upper()
    length = getattr(t, "length", None)
    if name in ("VARCHAR", "STRING", "UNICODE"):
        base = f"str({length})" if length else "str"
    elif name == "TEXT":
        base = "text"
    elif name == "INTEGER":
        base = "int"
    elif name == "BOOLEAN":
        base = "bool"
    elif name == "FLOAT":
        base = "float"
    elif name == "DATETIME":
        base = "datetime"
    elif name == "DATE":
        base = "date"
    elif name == "JSON":
        base = "JSON"
    else:
        base = name.lower()
    return base + ("?" if col.nullable else "")


def flag_for(table_name: str, col) -> str:
    if col.primary_key:
        return "pk"
    if col.foreign_keys:
        target = sorted(fk.column.table.name for fk in col.foreign_keys)[0]
        # A nullable constraint is drawn dashed: the row may legitimately have
        # no parent (a lead with no owner yet, a task on no project).
        return f"{'fk-soft' if col.nullable else 'fk'}:{target}"
    if col.name == "org_id":
        return "org"
    if col.name.endswith(SOFT_SUFFIX) and col.name not in ("created_by",):
        return "soft"
    if col.name == "created_by":
        return "soft"
    return ""


def emit_zones() -> tuple[str, dict[str, int]]:
    real = dict(Base.metadata.tables)
    placed = [t for _, _, _, tables in ZONES for t in tables]

    missing = sorted(set(real) - set(placed))
    unknown = sorted(set(placed) - set(real))
    dupes = sorted({t for t in placed if placed.count(t) > 1})
    if missing or unknown or dupes:
        lines = ["The domain map in build_schema_erd.py is out of date:"]
        if missing:
            lines.append(f"  tables in the models with no domain: {missing}")
        if unknown:
            lines.append(f"  domains name tables that do not exist: {unknown}")
        if dupes:
            lines.append(f"  tables placed in more than one domain: {dupes}")
        raise SystemExit("\n".join(lines))

    out = ["const ZONES = ["]
    n_fk = 0
    for zid, label, desc, tables in ZONES:
        out.append(f"  {{ id:'{zid}', label:'{label}', desc:'{desc}', tables:[")
        for tname in tables:
            table = real[tname]
            out.append(f"    T('{tname}', [")
            row: list[str] = []
            for col in table.columns:
                flag = flag_for(tname, col)
                if flag.startswith(("fk:", "fk-soft:")):
                    n_fk += 1
                row.append(f"['{col.name}','{type_label(col)}','{flag}']")
            # wrap at a readable width
            line = "      "
            for item in row:
                if len(line) + len(item) > 96:
                    out.append(line.rstrip())
                    line = "      "
                line += item + ","
            out.append(line.rstrip())
            out.append("    ]),")
        out.append("  ]},")
    out.append("];")
    stats = {
        "tables": len(real),
        "columns": sum(len(t.columns) for t in real.values()),
        "fks": n_fk,
        "domains": len(ZONES),
    }
    return "\n".join(out), stats


def build(out_dir: Path) -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    zones_js, stats = emit_zones()

    # 1 ── swap the data block
    start = html.index("const ZONES = [")
    end = html.index("\n];", start) + len("\n];")
    html = html[:start] + zones_js + html[end:]

    # 2 ── zone colours the original page never defined
    anchor = "--z-ops:      #838da0;"
    if anchor not in html:
        raise SystemExit("template changed: the --z-ops anchor is gone, so the "
                         "new lane colours have nowhere to attach")
    html = html.replace(
        anchor,
        anchor + "".join(f"\n    --z-{k}: {v};"
                         for k, v in NEW_ZONE_COLOURS.items()), 1)

    # 3 ── headline copy, with the real numbers in it
    html = html.replace(
        "<p class=\"dek\">Every table drawn to scale with its fields, grouped "
        "into the eight domains that make up the sales platform.",
        f"<p class=\"dek\">All <b>{stats['tables']} tables</b> and "
        f"<b>{stats['columns']} columns</b> drawn to scale, grouped into the "
        f"{stats['domains']} domains that make up the platform.")
    html = html.replace(
        "drawing all 20+ of those lines",
        f"drawing all {stats['tables'] - 1} of those lines")
    html = html.replace(
        "<p class=\"eyebrow\">Complete_Project · SQLAlchemy models</p>",
        "<p class=\"eyebrow\">Complete_Project · SQLAlchemy models · generated "
        f"{date.today():%d %B %Y}</p>")
    # the legend still explained the old lead vocabulary
    html = html.replace("how a lead moves through the pipeline",
                        "how a client moves from first contact to closure")

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(html, encoding="utf-8")

    print(f"wrote {target}")
    print(f"  {stats['tables']} tables · {stats['columns']} columns · "
          f"{stats['fks']} foreign keys · {stats['domains']} domains")
    for stale in ("school_intelligence", "role_at_school", "Leads (Schools)"):
        if stale in html:
            print(f"  !! stale identifier still present: {stale}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="directory to write index.html into")
    build(ap.parse_args().out)


if __name__ == "__main__":
    main()
