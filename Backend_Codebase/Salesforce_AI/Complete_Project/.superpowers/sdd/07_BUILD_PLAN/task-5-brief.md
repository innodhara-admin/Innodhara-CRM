### Task 5: The reset taxonomy and its partition guard *(D14, D16)*

Foundational: no route yet, so the guard exists before anything can rely on it.

**Files:**
- Create: `app/core/reset_taxonomy.py`
- Test: `tests/test_reset_taxonomy.py`

**Interfaces:**
- Produces: `KEEP: tuple[str, ...]` (4), `CONFIG: tuple[str, ...]` (2), `REPLACE: tuple[str, ...]` (7), `WIPE: tuple[str, ...]` (42), and `deletion_order(*, transactional: bool, catalogue: bool, org_config: bool) -> list[str]` returning table names child-before-parent.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reset_taxonomy.py
"""Every table must be classified. A table added later must fail this test
rather than silently surviving — or silently losing — a reset."""
from __future__ import annotations

import app.models  # noqa: F401  (registers every mapper)
from app.core.reset_taxonomy import CONFIG, KEEP, REPLACE, WIPE, deletion_order
from app.database import Base


def test_every_table_is_in_exactly_one_bucket():
    buckets = list(KEEP) + list(CONFIG) + list(REPLACE) + list(WIPE)
    tables = set(Base.metadata.tables)

    assert set(buckets) - tables == set(), "taxonomy names a non-existent table"
    assert tables - set(buckets) == set(), "a table is in no bucket"
    duplicates = {t for t in buckets if buckets.count(t) > 1}
    assert duplicates == set(), f"table in more than one bucket: {duplicates}"


def test_bucket_sizes_are_the_agreed_partition():
    assert (len(KEEP), len(CONFIG), len(REPLACE), len(WIPE)) == (4, 2, 7, 42)
    assert len(Base.metadata.tables) == 55


def test_users_and_audit_log_are_kept():
    """users: the reset runs under the session it would destroy.
    audit_log: D13 requires the reset to write an audit row."""
    assert "users" in KEEP
    assert "audit_log" in KEEP


def test_every_wipeable_table_can_be_org_scoped():
    for table in list(CONFIG) + list(REPLACE) + list(WIPE):
        assert "org_id" in Base.metadata.tables[table].columns, table


def test_deletion_order_puts_children_before_parents():
    order = deletion_order(transactional=True, catalogue=True, org_config=True)
    assert order.index("action_items") < order.index("projects")
    assert order.index("payments") < order.index("invoices")
    assert order.index("contacts") < order.index("leads")
    assert order.index("pricing_tables") < order.index("programs")
    assert order.index("demo_team_members") < order.index("demo_teams")
    assert "users" not in order
    assert "audit_log" not in order


def test_flags_select_only_their_own_bucket():
    assert deletion_order(
        transactional=False, catalogue=False, org_config=True
    ) == list(CONFIG)
    assert set(
        deletion_order(transactional=False, catalogue=True, org_config=False)
    ) == set(REPLACE)
    assert deletion_order(
        transactional=False, catalogue=False, org_config=False
    ) == []
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m pytest tests/test_reset_taxonomy.py -v`
Expected: FAIL — `ModuleNotFoundError: app.core.reset_taxonomy`.

- [ ] **Step 3: Write the module**

```python
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
Nothing else may re-derive these lists: tests/test_reset_taxonomy.py asserts
this module is a complete partition of Base.metadata.
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
    "proposal_templates",
    "message_templates",
    "playbooks",
    "programs",
    "demo_teams",
    "vendors",
)

WIPE: tuple[str, ...] = (
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
    "idempotency_records", "jobs", "llm_usage", "device_tokens",
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
```

- [ ] **Step 4: Run it and confirm it passes**

Run: `python -m pytest tests/test_reset_taxonomy.py -v`
Expected: 6 passed.

If `test_bucket_sizes_are_the_agreed_partition` fails on 55, a table has been
added since this plan was written. **Do not adjust the number to match.**
Classify the new table into a bucket, then update the expected sizes.

- [ ] **Step 5: Checkpoint**

`python -m pytest -q` green.

---

