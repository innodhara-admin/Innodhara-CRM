# tests/test_dashboard_reset.py
"""The reset endpoint: the only route in the system that destroys in bulk.

Every test creates its own organisation — org_a/org_b are session-scoped and
wiping them would corrupt every test that runs afterwards.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio


async def _seed(client, token) -> None:
    """One lead (transactional) + one program (catalogue) + one skill (config)."""
    lead = await client.post(
        "/api/v1/leads", headers=auth(token), json={"name": "Meridian Data"}
    )
    assert lead.status_code == 200, lead.text
    prog = await client.post(
        "/api/v1/admin/programs", headers=auth(token),
        json={"name": "Commissioning", "code": "RSTC", "description": "Halls."},
    )
    assert prog.status_code == 200, prog.text
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    skill = await client.post(
        "/api/v1/skills", headers=auth(token),
        json={"user_id": me["user_id"], "skill": "scheduling", "level": "good"},
    )
    assert skill.status_code == 200, skill.text


async def test_dry_run_counts_without_deleting(client, super_token):
    org = await create_org(client, super_token, name="Reset Dry",
                           slug="reset-dry", domain="reset-dry-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": True, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is False
    assert body["counts"]["leads"] == 1
    assert body["counts"]["programs"] == 1
    assert body["counts"]["user_skills"] == 1

    still_there = await client.get("/api/v1/leads", headers=auth(token))
    assert len(still_there.json()) == 1, "a dry run must delete nothing"


async def test_apply_requires_the_org_name_echoed_back(client, super_token):
    org = await create_org(client, super_token, name="Reset Echo",
                           slug="reset-echo", domain="reset-echo-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    wrong = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "confirm_org_name": "Reset Wrong"},
    )
    assert wrong.status_code == 422
    assert "Reset Echo" in wrong.text

    missing = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True},
    )
    assert missing.status_code == 422

    assert len((await client.get("/api/v1/leads", headers=auth(token))).json()) == 1


async def test_flags_clear_only_their_own_bucket(client, super_token):
    org = await create_org(client, super_token, name="Reset Flags",
                           slug="reset-flags", domain="reset-flags-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": False, "wipe_org_config": False,
              "confirm_org_name": "Reset Flags"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] is True

    assert (await client.get("/api/v1/leads", headers=auth(token))).json() == []
    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 1
    assert len((await client.get("/api/v1/skills", headers=auth(token))).json()) == 1


async def test_keep_survives_a_full_reset_and_the_session_still_works(
    client, super_token
):
    org = await create_org(client, super_token, name="Reset Full",
                           slug="reset-full", domain="reset-full-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Full"},
    )
    assert resp.status_code == 200, resp.text

    me = await client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200, "the resetting account must survive its own reset"
    assert len((await client.get(
        "/api/v1/admin/users", headers=auth(token))).json()) >= 1
    assert (await client.get(
        "/api/v1/admin/settings", headers=auth(token))).status_code == 200


async def test_another_organisation_is_untouched(client, super_token):
    keeper = await create_org(client, super_token, name="Reset Bystander",
                              slug="reset-bystand",
                              domain="reset-bystand-example.com")
    await _seed(client, keeper["admin_token"])
    victim = await create_org(client, super_token, name="Reset Victim",
                              slug="reset-victim",
                              domain="reset-victim-example.com")
    await _seed(client, victim["admin_token"])

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(victim["admin_token"]),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Victim"},
    )
    assert resp.status_code == 200, resp.text

    kept = keeper["admin_token"]
    assert len((await client.get("/api/v1/leads", headers=auth(kept))).json()) == 1
    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(kept))).json()) == 1
    assert len((await client.get("/api/v1/skills", headers=auth(kept))).json()) == 1


async def test_reset_writes_an_audit_row_that_survives(client, super_token):
    org = await create_org(client, super_token, name="Reset Audit",
                           slug="reset-audit", domain="reset-audit-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Audit"},
    )
    assert resp.status_code == 200, resp.text

    audit = await client.get("/api/v1/admin/audit", headers=auth(token))
    assert audit.status_code == 200, audit.text
    actions = [row["action"] for row in audit.json()]
    assert "admin.org_reset" in actions, (
        "audit_log is in KEEP precisely so this row outlives the reset"
    )


async def test_a_sales_agent_cannot_reset(client, org_a):
    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(org_a["agent_token"]),
        json={"dry_run": True, "wipe_transactional": True},
    )
    assert resp.status_code == 403


# ══════════════ Fix round 1: catalogue-only orphan guard ═══════════════════
# A catalogue-only reset (wipe_catalogue=True, wipe_transactional=False)
# deletes REPLACE (programs, templates, pricing tables, demo teams...) while
# leaving WIPE-side children (proposals, demos, demo_team_members, projects)
# untouched — 4 of the 6 FK edges between them are NOT NULL, so that orphans
# rows. The guard below refuses that (422, naming the edges) only when it
# would actually orphan something; a clean org sails through, and a dry run
# never refuses — it reports what would block instead.

_PROPOSAL_TEMPLATE = """# {program_name} Proposal for {school_name}

Dear {contact_name},

{context_summary}

## Commercials

{pricing_table}

Total: {total_amount}

Regards, {sender_name} ({org_name})
"""


async def _seed_proposal(client, token) -> dict:
    """Program + pricing + template + lead + contact + a built proposal —
    occupies 3 of the 6 catalogue-orphan edges (proposals.program_id,
    proposals.template_id, proposals.pricing_table_id all NOT NULL)."""
    program = (
        await client.post(
            "/api/v1/admin/programs", headers=auth(token),
            json={"name": "Orphan Program", "code": "ORPH", "description": "x"},
        )
    ).json()
    pricing = await client.post(
        f"/api/v1/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "items": [
            {"code": "unit", "label": "Unit", "unit": "each", "unit_price": 100},
        ]},
    )
    assert pricing.status_code == 200, pricing.text
    template = await client.post(
        f"/api/v1/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Standard", "body_md": _PROPOSAL_TEMPLATE},
    )
    assert template.status_code == 200, template.text
    lead = (
        await client.post(
            "/api/v1/leads", headers=auth(token), json={"name": "Orphan Client"}
        )
    ).json()
    contact = await client.post(
        f"/api/v1/leads/{lead['id']}/contacts", headers=auth(token),
        json={"name": "Contact Person", "title": "Owner",
              "email": "contact@orphan-example.com", "is_primary": True},
    )
    assert contact.status_code == 200, contact.text
    proposal = await client.post(
        "/api/v1/proposals", headers=auth(token),
        json={"lead_id": lead["id"], "program_id": program["id"]},
    )
    assert proposal.status_code == 200, proposal.text
    return {"program": program, "lead": lead, "proposal": proposal.json()}


async def test_catalogue_only_on_a_clean_org_proceeds(client, super_token):
    org = await create_org(client, super_token, name="Reset Clean Cat",
                           slug="reset-clean-cat",
                           domain="reset-clean-cat-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": False,
              "wipe_catalogue": True, "wipe_org_config": False,
              "confirm_org_name": "Reset Clean Cat"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["blocking_edges"] == [], (
        "a pre-go-live org with nothing referencing its catalogue must not "
        "be refused"
    )

    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 0
    assert len((await client.get("/api/v1/leads", headers=auth(token))).json()) == 1


async def test_catalogue_only_on_an_org_with_a_proposal_refuses(client, super_token):
    org = await create_org(client, super_token, name="Reset Orphan",
                           slug="reset-orphan", domain="reset-orphan-example.com")
    token = org["admin_token"]
    await _seed_proposal(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": False,
              "wipe_catalogue": True, "wipe_org_config": False,
              "confirm_org_name": "Reset Orphan"},
    )
    assert resp.status_code == 422, resp.text
    assert "proposals" in resp.text and "programs" in resp.text, (
        "the refusal must name the blocking edge, not just refuse"
    )

    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 1, (
        "a refused reset must delete nothing"
    )


async def test_catalogue_only_dry_run_reports_blocking_edges(client, super_token):
    org = await create_org(client, super_token, name="Reset Orphan Dry",
                           slug="reset-orphan-dry",
                           domain="reset-orphan-dry-example.com")
    token = org["admin_token"]
    await _seed_proposal(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": True, "wipe_transactional": False,
              "wipe_catalogue": True, "wipe_org_config": False},
    )
    assert resp.status_code == 200, (
        "a dry run must never 422 — the conflict shows at preview"
    )
    body = resp.json()
    assert body["applied"] is False
    assert len(body["blocking_edges"]) > 0
    edge_tables = {e["table"] for e in body["blocking_edges"]}
    assert "proposals" in edge_tables

    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 1, (
        "a dry run must delete nothing"
    )


async def test_all_flags_reset_is_unaffected_by_the_catalogue_guard(
    client, super_token
):
    org = await create_org(client, super_token, name="Reset Orphan Full",
                           slug="reset-orphan-full",
                           domain="reset-orphan-full-example.com")
    token = org["admin_token"]
    await _seed_proposal(client, token)

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": True,
              "wipe_catalogue": True, "wipe_org_config": True,
              "confirm_org_name": "Reset Orphan Full"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert body["blocking_edges"] == [], (
        "wipe_transactional=True already removes the WIPE-side children "
        "before REPLACE is deleted, so nothing can be orphaned"
    )

    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 0


# ══════ Task 12: playbook_suggestions.program_id is a bare (non-FK) edge ═══
async def test_catalogue_only_on_an_org_with_a_playbook_suggestion_refuses(
    client, super_token
):
    """Before Task 12, `_CATALOGUE_ORPHAN_EDGES` was derived purely by
    walking ForeignKey objects, and playbook_suggestions.program_id carries
    none (see app/models/project.py) — so a catalogue-only reset silently
    deleted every `programs` row while these NOT NULL rows survived,
    reporting `blocking_edges: []` and proceeding. It must now refuse, the
    same way it already refuses for proposals.program_id."""
    from sqlalchemy import select as sa_select

    from app.database import SessionLocal
    from app.models.project import PlaybookSuggestion

    org = await create_org(client, super_token, name="Reset Suggestion",
                           slug="reset-suggestion",
                           domain="reset-suggestion-example.com")
    token = org["admin_token"]

    program = (
        await client.post(
            "/api/v1/admin/programs", headers=auth(token),
            json={"name": "Suggestion Program", "code": "SUGG",
                  "description": "x"},
        )
    ).json()

    # No POST route creates playbook_suggestions rows — the Knowledge Engine
    # writes them internally — so insert directly, following the precedent
    # in tests/test_dashboard_deletes_admin.py::test_unused_program_deletes.
    async with SessionLocal() as db:
        db.add(PlaybookSuggestion(
            org_id=org["id"], program_id=program["id"], phase="preparation",
            entry={"title": "Confirm working machines a day early"},
            reason="Recurring incident pattern",
        ))
        await db.commit()

    dry = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": True, "wipe_transactional": False,
              "wipe_catalogue": True, "wipe_org_config": False},
    )
    assert dry.status_code == 200, (
        "a dry run must never 422 — the conflict shows at preview"
    )
    edge_tables = {e["table"] for e in dry.json()["blocking_edges"]}
    assert "playbook_suggestions" in edge_tables

    resp = await client.post(
        "/api/v1/admin/reset", headers=auth(token),
        json={"dry_run": False, "wipe_transactional": False,
              "wipe_catalogue": True, "wipe_org_config": False,
              "confirm_org_name": "Reset Suggestion"},
    )
    assert resp.status_code == 422, resp.text
    assert "playbook_suggestions" in resp.text and "programs" in resp.text, (
        "the refusal must name the blocking edge, not just refuse"
    )

    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 1, (
        "a refused reset must delete nothing"
    )
    async with SessionLocal() as db:
        remaining = (
            await db.execute(
                sa_select(PlaybookSuggestion).where(
                    PlaybookSuggestion.org_id == org["id"],
                )
            )
        ).scalars().all()
    assert len(remaining) == 1, (
        "a refused reset must delete nothing, including the bare-reference row"
    )


# ══════════════════════ Fix round 1: rollback on mid-loop failure ══════════
async def test_a_mid_loop_failure_rolls_back_everything(
    client, super_token, monkeypatch
):
    """The most valuable property this endpoint has: a failure partway
    through the delete loop must leave no partial damage — no rows deleted,
    no audit row, org still reachable."""
    org = await create_org(client, super_token, name="Reset Rollback",
                           slug="reset-rollback",
                           domain="reset-rollback-example.com")
    token = org["admin_token"]
    await _seed(client, token)

    from app.api import admin as admin_module

    real_deletion_order = admin_module.deletion_order

    def _broken_deletion_order(**kwargs):
        # Real tables first (so real deletes actually run), then a table
        # that doesn't exist in Base.metadata — the loop raises after doing
        # real damage, exactly as it would from an unanticipated bug.
        return [*real_deletion_order(**kwargs), "not_a_real_table"]

    monkeypatch.setattr(admin_module, "deletion_order", _broken_deletion_order)

    with pytest.raises(KeyError):
        await client.post(
            "/api/v1/admin/reset", headers=auth(token),
            json={"dry_run": False, "wipe_transactional": True,
                  "wipe_catalogue": True, "wipe_org_config": True,
                  "confirm_org_name": "Reset Rollback"},
        )

    monkeypatch.undo()

    assert len((await client.get("/api/v1/leads", headers=auth(token))).json()) == 1, (
        "the injected failure must have rolled back the leads delete"
    )
    assert len((await client.get(
        "/api/v1/admin/programs", headers=auth(token))).json()) == 1, (
        "the injected failure must have rolled back the programs delete"
    )
    assert len((await client.get("/api/v1/skills", headers=auth(token))).json()) == 1, (
        "the injected failure must have rolled back the user_skills delete"
    )

    audit = await client.get("/api/v1/admin/audit", headers=auth(token))
    assert audit.status_code == 200, audit.text
    actions = [row["action"] for row in audit.json()]
    assert "admin.org_reset" not in actions, (
        "the audit row is written after the delete loop — it must not "
        "survive a failure inside that loop"
    )

    me = await client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200, "the org must still be reachable after rollback"


# ══════════════ Fix round: derive the orphan edges, don't hand-list them ═══
async def test_catalogue_orphan_edges_match_the_schema():
    """`_CATALOGUE_ORPHAN_EDGES` must be exactly the FK-derived edges from a
    surviving (WIPE|CONFIG) table into a deleted (REPLACE) table, UNIONED
    with the small hand-written `_CATALOGUE_ORPHAN_EDGES_DECLARED` list for
    bare references the FK walk cannot see (Task 12: playbook_suggestions.
    program_id is a String with no ForeignKey). This re-walks the FK graph
    independently of app.api.admin's derivation and asserts the two sets are
    identical modulo the declared additions, in the spirit of
    tests/test_reset_taxonomy.py: the guard a hand-written list never had. A
    schema change that adds or removes a WIPE/CONFIG -> REPLACE FK edge must
    fail this test, not silently change behaviour."""
    import app.models  # noqa: F401  (registers every mapper)
    from app.api.admin import (
        _CATALOGUE_ORPHAN_EDGES,
        _CATALOGUE_ORPHAN_EDGES_DECLARED,
    )
    from app.core.reset_taxonomy import CONFIG, REPLACE, WIPE
    from app.database import Base

    fk_derived: set[tuple[str, str, str]] = set()
    replace_set = set(REPLACE)
    for child in set(WIPE) | set(CONFIG):
        table = Base.metadata.tables[child]
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent in replace_set:
                    fk_derived.add((child, column.name, parent))

    declared = set(_CATALOGUE_ORPHAN_EDGES_DECLARED)
    expected = fk_derived | declared

    assert set(_CATALOGUE_ORPHAN_EDGES) == expected
    assert list(_CATALOGUE_ORPHAN_EDGES) == sorted(_CATALOGUE_ORPHAN_EDGES), (
        "must be sorted so the 422 message is stable across runs"
    )
    # Pin the currently-known nine FK-derived edges too: if this narrows, the
    # derivation itself is broken (e.g. only checking one bucket) even
    # though a set comparison against an equally-broken `expected` could
    # still pass.
    assert fk_derived == {
        ("demo_team_members", "team_id", "demo_teams"),
        ("proposals", "program_id", "programs"),
        ("proposals", "template_id", "proposal_templates"),
        ("proposals", "pricing_table_id", "pricing_tables"),
        # A fill session in progress names the programme, the template
        # and the template document it is filling, so a catalogue-only
        # reset would leave it pointing at a template that is gone.
        ("proposal_fill_sessions", "program_id", "programs"),
        ("proposal_fill_sessions", "template_id", "proposal_templates"),
        ("proposal_fill_sessions", "template_doc_id",
         "proposal_template_docs"),
        # A built MOU names the programme and the template version
        # it was built from, so a catalogue-only reset must refuse
        # rather than leave a signed contract pointing at a
        # template that is gone.
        ("mou_documents", "program_id", "programs"),
        ("mou_documents", "template_id", "proposal_templates"),
        ("demos", "team_id", "demo_teams"),
        ("projects", "program_id", "programs"),
        # An email being filled names the Word email template it is
        # filled from (2026-10-28), so a catalogue-only reset must refuse
        # rather than leave it pointing at a template that is gone.
        ("email_fill_sessions", "template_id", "email_templates"),
    }
    # And pin the one currently-known declared (bare, non-FK) edge — same
    # reasoning: a narrowing here would hide behind a still-passing set
    # comparison.
    assert declared == {
        ("playbook_suggestions", "program_id", "programs"),
    }


# ══════════════ Fix round: catch bare (non-FK) catalogue references ════════
async def test_every_bare_star_id_column_naming_a_replace_table_is_covered():
    """The FK walk above is blind by construction to a `*_id` column with no
    `ForeignKey` — that is exactly the hole Task 12 closes for
    playbook_suggestions.program_id. This test does NOT reuse that FK walk;
    it independently finds candidate bare references by NAME (does a
    WIPE/CONFIG column named e.g. "team_id" or "pricing_table_id" plausibly
    name a REPLACE table?) and asserts every one it finds is accounted for
    in `_CATALOGUE_ORPHAN_EDGES` — whether because the column actually does
    carry a ForeignKey (so the other derivation already caught it) or
    because it is a bare reference listed in
    `_CATALOGUE_ORPHAN_EDGES_DECLARED`. A new bare reference introduced
    later — a column named after a REPLACE table with no ForeignKey, and
    not added to the declared list — must fail this test.
    """
    import app.models  # noqa: F401  (registers every mapper)
    from app.api.admin import _CATALOGUE_ORPHAN_EDGES
    from app.core.reset_taxonomy import CONFIG, REPLACE, WIPE
    from app.database import Base

    def _stems(table_name: str) -> set[str]:
        """Name fragments a *_id column might plausibly use to refer to
        `table_name` — the whole name singularised, and its last
        underscore-separated word singularised. e.g. "demo_teams" ->
        {"demo_teams", "demo_team", "teams", "team"}, so both a
        "demo_team_id" and a bare "team_id" column are recognised."""
        words = {table_name}
        if table_name.endswith("s"):
            words.add(table_name[:-1])
        last_word = table_name.rsplit("_", 1)[-1]
        words.add(last_word)
        if last_word.endswith("s"):
            words.add(last_word[:-1])
        return words

    replace_stems: set[str] = set()
    for table_name in REPLACE:
        replace_stems |= _stems(table_name)

    candidates: list[tuple[str, str]] = []
    for child in sorted(set(WIPE) | set(CONFIG)):
        table = Base.metadata.tables[child]
        for column in table.columns:
            if column.name in ("id", "org_id") or not column.name.endswith("_id"):
                continue
            stem = column.name[: -len("_id")]
            if stem in replace_stems:
                candidates.append((child, column.name))

    # Sanity: the independent name-scan must find at least the known edges,
    # or it isn't scanning anything and every assertion below is vacuous.
    assert len(candidates) >= 7, candidates

    covered = {(child, column) for child, column, _ in _CATALOGUE_ORPHAN_EDGES}
    for child, column in candidates:
        assert (child, column) in covered, (
            f"{child}.{column} names a REPLACE table by its column name but "
            "is not in _CATALOGUE_ORPHAN_EDGES — if it has no ForeignKey, "
            "add it to _CATALOGUE_ORPHAN_EDGES_DECLARED in app/api/admin.py"
        )
