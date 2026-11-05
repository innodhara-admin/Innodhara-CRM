#!/usr/bin/env python3
r"""Reset the database for the DATACENTRE demo (Workflow2).

KEEPS   the organisation, its settings, every login and every user_skill row.
WIPES   all transactional data — leads, contacts, stakeholders, projects,
        plans, tasks, meetings, transcripts, proposals, messages, approvals,
        commitments, conflicts, incidents, notifications, digests, decisions,
        events, assignments, follow-ups, demos, invoices, payments, threads.
REPLACES the catalogue: the seeded programs are school offerings (IBC, Android
        Bootcamp, STEM Lab). Pricing a datacentre engagement from "STEM Lab —
        Permanent Installation" would be nonsense on screen, so the catalogue,
        pricing tables, proposal/message templates, playbooks, the demo team and
        the vendor are rebuilt for datacentre work.

⚠ The team's SKILLS are deliberately left untouched, per instruction. The
  datacentre tasks in Workflow2 are therefore written against the transferable
  skills the team already holds — logistics_coordination, scheduling,
  quality_assurance, training_delivery, content_development, invoicing,
  proposal_preparation, client_relationship, general — so the Assignment Engine
  finds a real person with a real reason for every task. A task needing a skill
  nobody holds routes unassigned, which is finding F25 and a bad demo.

Run:  python scripts/reset_for_datacentre_demo.py
      python scripts/reset_for_datacentre_demo.py --dry-run
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "salesplatform.db"

# Everything transactional. NOT topologically sorted: five edges have the
# parent deleted before its child (stakeholders -> projects; followups,
# demos, memory_chunks, client_intelligence -> leads). This has never bitten
# because `main()` issues `PRAGMA foreign_keys=OFF` before wiping, so the
# ordering below is never actually enforced. It would bite on PostgreSQL, or
# on SQLite with the pragma left on.
#
# `app/core/reset_taxonomy.py` is now the correct source: its `WIPE` tuple is
# topologically sorted against every FK edge and is guarded by
# `tests/test_reset_taxonomy.py`. Whoever next touches this script should
# import from that module rather than maintain a second hand-ordered copy —
# two hand-maintained orderings is how this divergence happened.
WIPE = [
    "message_delivery_log", "outbound_messages", "inbound_messages", "threads",
    "approvals", "proposal_revisions", "proposals",
    "reminders", "assignments", "progress_events", "ai_decisions",
    "action_items", "action_plans", "client_commitments", "conflicts",
    "project_members", "resource_bookings", "deliverables",
    "payments", "invoices", "incidents", "projects",
    "transcripts", "meetings", "consent_records",
    "stakeholders", "contacts", "lead_state_history", "leads",
    "followups", "demos", "demo_team_members",
    "notifications", "digests", "assistant_turns", "memory_chunks",
    "client_intelligence", "playbook_suggestions",
    "idempotency_records", "jobs", "llm_usage", "audit_log", "device_tokens",
]

# The catalogue is replaced, not kept.
REPLACE = [
    "pricing_tables", "proposal_templates", "message_templates",
    "playbooks", "programs", "demo_teams", "vendors",
]

KEEP = ["organisations", "org_settings", "users", "user_skills", "approval_rules"]


def nid() -> str:
    return uuid.uuid4().hex


PROPOSAL_BODY = """# {program_name} — proposal for {client_name}

Dear {contact_name},

{context_summary}

## What we will do

{program_description}

## Commercials

{pricing_table}

**Total: {total_amount}**

All figures are computed from our current rate card. Timelines and access
requirements are confirmed jointly at the kick-off.

Regards,
{sender_name}
{org_name}
"""

INTRO_EMAIL = """Dear {contact_name},

It was good to meet you at {client_name}. I am {sender_name} from {org_name}.

We help data centre operators commission, validate and hand over capacity
without surprises on the day. If it is useful, I can share how we have done
this for operators of a similar size.

Warm regards,
{sender_name}
{org_name}
"""

FOLLOWUP_EMAIL = """Dear {contact_name},

Following up on our conversation about {client_name}. Happy to answer anything
outstanding, or to walk your team through the commissioning plan.

Warm regards,
{sender_name}
{org_name}
"""


def main() -> None:
    dry = "--dry-run" in sys.argv
    if not DB.exists():
        sys.exit(f"No database at {DB}")

    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys=OFF")
    cur = con.cursor()

    org = cur.execute("select id, name from organisations limit 1").fetchone()
    if org is None:
        sys.exit("No organisation — nothing to reset onto.")
    org_id, org_name = org
    users = cur.execute(
        "select count(*) from users where role != 'super_admin'"
    ).fetchone()[0]
    skills = cur.execute("select count(*) from user_skills").fetchone()[0]

    print(f"Organisation : {org_name}")
    print(f"Keeping      : {users} logins, {skills} skill rows, org settings, "
          f"approval rules\n")

    print("WIPE (transactional)")
    total = 0
    for t in WIPE + REPLACE:
        try:
            n = cur.execute(f"select count(*) from {t}").fetchone()[0]
        except sqlite3.OperationalError:
            print(f"  - {t:24} (no such table, skipped)")
            continue
        total += n
        tag = "replace" if t in REPLACE else ""
        print(f"  - {t:24} {n:5} rows {tag}")
        if not dry:
            cur.execute(f"delete from {t}")
    print(f"\n  {total} rows to remove\n")

    if dry:
        print("DRY RUN — nothing was changed.")
        con.close()
        return

    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")

    # ── Datacentre catalogue ────────────────────────────────────────────────
    programs = [
        (nid(), "DC Commissioning & Handover", "DCCH",
         "End-to-end commissioning of new data centre capacity: power-on "
         "checks, thermal and airflow validation, rack-level acceptance, "
         "and a documented handover pack the operations team can run from."),
        (nid(), "Thermal & Airflow Audit", "TAA",
         "An independent audit of an operating hall: hot-spot mapping, "
         "containment and airflow review, and a prioritised remediation plan "
         "with measured before-and-after figures."),
        (nid(), "Operations Runbook & Team Enablement", "ORTE",
         "Runbooks written for the site as built, plus hands-on enablement so "
         "the operator's own staff can run day-to-day operations and "
         "first-line incident response without us."),
    ]
    for pid, name, code, desc in programs:
        cur.execute(
            "insert into programs (id, org_id, name, code, description, "
            "is_active, created_at, updated_at) values (?,?,?,?,?,1,?,?)",
            (pid, org_id, name, code, desc, now, now),
        )

    # Pricing — deliberately NOT per-student. Units a data centre actually
    # buys in: racks, kW, sites, operators, halls. (Genericity, finding F31.)
    pricing = {
        programs[0][0]: [
            {"code": "rack_commissioning", "label": "Rack commissioning & acceptance",
             "unit": "per rack", "unit_price": 4500, "default_quantity": 120},
            {"code": "power_on_checks", "label": "Power-on and load-bank checks",
             "unit": "per hall", "unit_price": 185000, "default_quantity": 2},
            {"code": "handover_pack", "label": "Documented handover pack",
             "unit": "per site", "unit_price": 240000, "default_quantity": 1},
        ],
        programs[1][0]: [
            {"code": "thermal_survey", "label": "Thermal and airflow survey",
             "unit": "per hall", "unit_price": 165000, "default_quantity": 2},
            {"code": "hotspot_mapping", "label": "Hot-spot mapping report",
             "unit": "per site", "unit_price": 95000, "default_quantity": 1},
        ],
        programs[2][0]: [
            {"code": "runbook", "label": "Site runbook authoring",
             "unit": "per site", "unit_price": 320000, "default_quantity": 1},
            {"code": "operator_training", "label": "Operator enablement",
             "unit": "per operator", "unit_price": 12000, "default_quantity": 20},
        ],
    }
    for pid, items in pricing.items():
        import json
        cur.execute(
            "insert into pricing_tables (id, org_id, program_id, version, "
            "currency, items, effective_from, is_current, created_at, "
            "updated_at) values (?,?,?,1,'INR',?,?,1,?,?)",
            (nid(), org_id, pid, json.dumps(items), now, now, now),
        )

    for pid, name, _code, _desc in programs:
        cur.execute(
            "insert into proposal_templates (id, org_id, program_id, name, "
            "version, body_md, is_current, created_at, updated_at) "
            "values (?,?,?,?,1,?,1,?,?)",
            (nid(), org_id, pid, f"{name} — standard", PROPOSAL_BODY, now, now),
        )

    for kind, channel, body, subject in (
        ("intro", "email", INTRO_EMAIL, "Good to meet you — {client_name}"),
        ("intro", "whatsapp",
         "Hi {contact_name}, {sender_name} from {org_name} here. Good to meet "
         "you at {client_name}. Happy to share how we commission and hand over "
         "capacity if useful.", None),
        ("follow_up", "email", FOLLOWUP_EMAIL, "Following up — {client_name}"),
        ("follow_up", "whatsapp",
         "Hi {contact_name}, just following up on our conversation about "
         "{client_name}. Anything I can answer?", None),
    ):
        cur.execute(
            "insert into message_templates (id, org_id, kind, channel, name, "
            "version, subject, body, is_current, created_at, updated_at) "
            "values (?,?,?,?,?,1,?,?,1,?,?)",
            (nid(), org_id, kind, channel, f"{kind} {channel}", subject, body,
             now, now),
        )

    # Playbooks — the standard task wave per phase. Skills are chosen from what
    # the team ACTUALLY holds (see the module docstring).
    import json as _json
    playbooks = [
        ("preparation", [
            {"title": "Confirm site access and escort arrangements",
             "required_skill": "logistics_coordination", "offset_days": -14,
             "priority": "P2", "visible_to_client": False},
            {"title": "Lock the commissioning schedule with the site team",
             "required_skill": "scheduling", "offset_days": -10,
             "priority": "P1", "visible_to_client": True},
            {"title": "Stage test equipment and load banks",
             "required_skill": "logistics_coordination", "offset_days": -7,
             "priority": "P2", "visible_to_client": False},
        ]),
        ("delivery", [
            {"title": "Run rack-level acceptance checks",
             "required_skill": "quality_assurance", "offset_days": 2,
             "priority": "P1", "visible_to_client": True},
            {"title": "Daily commissioning report to the client",
             "required_skill": "content_development", "offset_days": 3,
             "priority": "P2", "visible_to_client": True},
        ]),
        ("closure", [
            {"title": "Hand over the runbook pack",
             "required_skill": "content_development", "offset_days": 1,
             "priority": "P1", "visible_to_client": True},
            {"title": "Raise the final invoice",
             "required_skill": "invoicing", "offset_days": 3,
             "priority": "P1", "visible_to_client": False},
        ]),
    ]
    for pid, _n, _c, _d in programs[:1]:
        for phase, entries in playbooks:
            cur.execute(
                "insert into playbooks (id, org_id, program_id, phase, version, "
                "entries, is_current, created_at, updated_at) "
                "values (?,?,?,?,1,?,1,?,?)",
                (nid(), org_id, pid, phase, _json.dumps(entries), now, now),
            )

    team_id = nid()
    cur.execute(
        "insert into demo_teams (id, org_id, name, created_at, updated_at) "
        "values (?,?,?,?,?)",
        (team_id, org_id, "Commissioning Team A", now, now),
    )
    cur.execute(
        "insert into vendors (id, org_id, name, category, contact_name, "
        "email, phone, created_at, updated_at) "
        "values (?,?,?,?,?,?,?,?,?)",
        (nid(), org_id, "RackLine Logistics", "equipment",
         "Suresh Menon", "vendor@rackline.example.com", "+91 99000 11222",
         now, now),
    )

    con.commit()

    print("SEEDED (datacentre catalogue)")
    for _pid, name, code, _d in programs:
        print(f"  + program           {name}  [{code}]")
    print(f"  + pricing tables    {len(pricing)} (per rack / hall / site / operator)")
    print(f"  + proposal templates {len(programs)}")
    print("  + message templates  intro+follow_up x email+whatsapp")
    print(f"  + playbooks          {len(playbooks)} phases")
    print("  + demo team          Commissioning Team A")
    print("  + vendor             RackLine Logistics")

    print("\nVERIFY")
    for t in ("leads", "projects", "meetings", "action_items", "proposals",
              "outbound_messages", "approvals", "incidents", "notifications"):
        n = cur.execute(f"select count(*) from {t}").fetchone()[0]
        print(f"  {t:20} {n}")
    for t in ("users", "user_skills", "programs", "pricing_tables"):
        n = cur.execute(f"select count(*) from {t}").fetchone()[0]
        print(f"  {t:20} {n}")
    con.close()
    print("\nDone. The database is ready for the Workflow2 datacentre demo.")


if __name__ == "__main__":
    main()
