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
    # proposal_fill_sessions joined WIPE: a half-answered fill is a client's work in
    # progress, not a catalogue entry.
    # 43/56 since relationship_engagements joined WIPE. These numbers are
    # meant to be edited by hand when a table is added -- that edit is the
    # moment somebody decides which bucket it belongs in.
    # mou_documents joined WIPE: a built MOU is a client's contract,
    # not a catalogue entry, and it is deleted before the
    # proposals its fill session may also reference.
    # proposal_template_docs joined REPLACE beside proposal_templates:
    # a template's document is part of the template.
    # mou_revisions joined WIPE beside mou_documents: what an MOU
    # said before a correction is part of the contract's record,
    # and it is deleted before the MOU it belongs to.
    # assistant_pending_actions joined WIPE beside assistant_turns: a
    # read-back write waiting on a "yes" belongs to the conversation.
    # scheduled_meetings joined WIPE beside demos (2026-09-23): a meeting
    # arranged with a client is transactional, and goes before leads.
    # location_pings joined WIPE beside device_tokens (2026-10-02): where a
    # salesperson was when they opened the app is transactional data.
    # insight_snapshots joined WIPE before leads (2026-10-23): the sales
    # head's daily deal-score and pulse snapshots are transactional too.
    # email_templates and email_template_attachments joined REPLACE beside
    # message_templates, and email_fill_sessions joined WIPE first
    # (2026-10-28): a template is catalogue, an email being filled is work.
    # whatsapp_log joined WIPE (2026-11-04): staff WhatsApp delivery records.
    assert (len(KEEP), len(CONFIG), len(REPLACE), len(WIPE)) == (4, 2, 10, 53)
    assert len(Base.metadata.tables) == 69


def test_users_and_audit_log_are_kept():
    """users: the reset runs under the session it would destroy.
    audit_log: D13 requires the reset to write an audit row."""
    assert "users" in KEEP
    assert "audit_log" in KEEP


def test_every_wipeable_table_can_be_org_scoped():
    for table in list(CONFIG) + list(REPLACE) + list(WIPE):
        assert "org_id" in Base.metadata.tables[table].columns, table


def test_deletion_order_respects_every_foreign_key():
    """Walk every FK on every table `deletion_order` returns, not a
    hand-picked list of pairs. Cherry-picked pairs are exactly what let a
    bad ordering through: five real violations existed here and none of
    them overlapped an earlier, narrower version of this test."""
    order = deletion_order(transactional=True, catalogue=True, org_config=True)
    index = {table: position for position, table in enumerate(order)}
    order_set = set(order)

    violations = []
    for table_name in order:
        table = Base.metadata.tables[table_name]
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent == table_name:
                    continue  # self-reference
                if parent not in order_set:
                    continue  # parent is in KEEP, e.g. users/organisations
                if index[table_name] > index[parent]:
                    violations.append(
                        f"{table_name} (idx {index[table_name]}) via "
                        f"{table_name}.{column.name} -> {parent} "
                        f"(idx {index[parent]}): child deleted after parent"
                    )

    assert violations == [], "FK ordering violations:\n" + "\n".join(violations)
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
