# app/core/reset_taxonomy.py
"""Which tables a reset touches, and in what order.

Four buckets, not the script's three (05_DECISIONS.md D16):

  KEEP     never removed, by any flag.  `users` because the reset runs under
           the org_admin session it would otherwise destroy; `audit_log`
           because D13 requires the reset to leave an audit row behind.
  CONFIG   user_skills + approval_rules.  The reseed bundle exports both, so
           the reset must be able to clear them or a re-import collides.
  REPLACE  the catalogue.
  WIPE     everything transactional.

Ordering is child-before-parent throughout, because the schema declares no
`ondelete=` rule anywhere and SQLite does not enforce foreign keys by default.
WIPE's internal order is topologically sorted against every FK edge among its
own tables (eight edges — stakeholders->projects/contacts, followups/demos/
scheduled_meetings/memory_chunks/client_intelligence/relationship_engagements/
lead_cycles->leads —
are not in declaration order, so do not "tidy" this tuple back to something
more alphabetical-looking).
`deletion_order` then appends REPLACE and CONFIG, which is safe unchecked:
every WIPE->REPLACE and WIPE->CONFIG edge already has the child earlier
because WIPE precedes both in the returned list, and REPLACE's own internal
order (catalogue tables) is child-before-parent by inspection too.
Nothing else may re-derive these lists: tests/test_reset_taxonomy.py asserts
this module is a complete partition of Base.metadata, and walks every FK edge
among the tables `deletion_order` returns to prove the ordering is safe.
"""
from __future__ import annotations

KEEP: tuple[str, ...] = (
    "organisations",
    "org_settings",
    "users",
    "audit_log",
)

CONFIG: tuple[str, ...] = (
    "user_skills",
    "approval_rules",
)

REPLACE: tuple[str, ...] = (
    "pricing_tables",
    # A template's document is part of the template, so it shares the bucket:
    # split them and a reset leaves a surviving template row pointing at a file
    # that is gone, and `_current_template` finds a template that cannot build
    # anything. Listed BEFORE proposal_templates because ordering here is
    # child-before-parent throughout and proposal_template_docs.template_id is
    # a foreign key to it.
    "proposal_template_docs",
    "proposal_templates",
    "message_templates",
    # Word email templates and their default files (2026-10-28). Children
    # first: an attachment points at its template, and a template at its
    # programme, which comes later in this list.
    "email_template_attachments",
    "email_templates",
    "playbooks",
    "programs",
    "demo_teams",
    "vendors",
)

WIPE: tuple[str, ...] = (
    # An email being filled in a conversation (2026-10-28). First: it points
    # at an outbound message, a proposal, an MOU and a lead, all below.
    "email_fill_sessions",
    "message_delivery_log", "outbound_messages", "inbound_messages", "threads",
    # Staff WhatsApp delivery records (2026-11-04): transactional, no FK.
    "whatsapp_log",
    "approvals",
    # A half-answered fill is a client's work in progress, not a
    # catalogue entry: a reset that kept it would resume week-old
    # answers about a client whose records have just been wiped.
    # Listed BEFORE proposals because ordering here is
    # child-before-parent and proposal_fill_sessions.proposal_id is a
    # foreign key to it.
    "proposal_fill_sessions",
    # Ahead of mou_documents, which it carries a foreign key to. This
    # list is deleted in order and nothing in this schema declares
    # ondelete=, so child-before-parent is the only thing keeping a
    # reset from failing.
    "mou_revisions",
    # A signed MOU is a client's contract, not a catalogue entry.
    # AFTER proposal_fill_sessions, which carries a foreign key to
    # it, and BEFORE proposals -- this list is deleted in order and
    # nothing in this schema declares ondelete=.
    "mou_documents",
    "proposal_revisions", "proposals",
    "reminders", "assignments", "progress_events", "ai_decisions",
    "action_items", "action_plans", "client_commitments", "conflicts",
    "project_members", "resource_bookings", "deliverables",
    "payments", "invoices", "incidents",
    "stakeholders", "projects",
    "transcripts", "meetings", "consent_records",
    "contacts", "lead_state_history",
    "followups", "demos",
    # A meeting arranged with a client (not a demo). Before leads: its
    # lead_id is a foreign key to it.
    "scheduled_meetings",
    "memory_chunks", "client_intelligence",
    "relationship_engagements", "lead_cycles",
    # The sales head's daily score and pulse snapshots (2026-10-23). No
    # foreign keys, but each row names a lead, so it goes before leads.
    "insight_snapshots",
    "leads",
    "demo_team_members",
    "notifications", "digests", "assistant_turns",
    # A read-back write waiting on a "yes" is part of a conversation, and a
    # reset that kept it would let a "yes" create a client in a wiped org.
    "assistant_pending_actions",
    "playbook_suggestions",
    "idempotency_records", "jobs", "llm_usage", "device_tokens",
    # Where a salesperson was when they opened the app (2026-10-02). Its
    # only foreign keys point at KEEP tables, so its place here is free.
    "location_pings",
)


def deletion_order(
    *, transactional: bool, catalogue: bool, org_config: bool
) -> list[str]:
    """Tables to delete, children first. KEEP is unreachable from here."""
    order: list[str] = []
    if transactional:
        order.extend(WIPE)
    if catalogue:
        order.extend(REPLACE)
    if org_config:
        order.extend(CONFIG)
    return order
