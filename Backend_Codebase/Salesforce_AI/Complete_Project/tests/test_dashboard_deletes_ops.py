"""Catalogue deletes are for pre-go-live mistakes. Anything a live record
depends on must refuse, with a reason (D7).

Setup-call corrections vs. the original brief (see task-7-report.md for the
full writeup):
  - `POST /api/v1/action-items` (app/api/action_items.py CreateItemRequest)
    has no `required_skill` field and the handler never sets one on create —
    extra JSON keys are silently ignored by pydantic. There is no route that
    lets a caller set `required_skill` on a task. The existing test suite's
    own precedent for this (tests/test_assignment_skills.py,
    test_a_seeded_skill_produces_a_real_match_not_no_skill_match) is to build
    the ActionItem directly through `SessionLocal` — followed here.
  - There is no `/tasks/{id}/external-wait` route. The real vendor-wait route
    is `POST /tasks/{task_id}/vendor-promise`
    (app/api/workflow.py:VendorPromiseRequest), and it takes
    `vendor_name` (free text) + `promised_date` + optional
    `chase_contact_user_id` — there is no `vendor_id` field to send.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio


async def test_skill_delete_uses_the_natural_key(client, super_token):
    org = await create_org(client, super_token, name="Del Skill",
                           slug="del-skill", domain="del-skill-example.com")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()

    await client.post("/api/v1/skills", headers=auth(token),
                      json={"user_id": me["user_id"], "skill": "typo_skill",
                            "level": "basic"})
    assert len((await client.get("/api/v1/skills", headers=auth(token))).json()) == 1

    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={me['user_id']}&skill=typo_skill",
        headers=auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert (await client.get("/api/v1/skills", headers=auth(token))).json() == []


async def test_skill_delete_refuses_when_open_work_needs_it(client, super_token):
    """`POST /api/v1/action-items` cannot set `required_skill` (no such field
    on CreateItemRequest, and create_action_item never assigns one), so the
    open task that needs the 'wiring' skill is built directly through the DB
    session — the same workaround tests/test_assignment_skills.py already
    uses for this exact gap."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem

    org = await create_org(client, super_token, name="Del Skill Busy",
                           slug="del-skill-busy",
                           domain="del-skill-busy-example.com")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    await client.post("/api/v1/skills", headers=auth(token),
                      json={"user_id": me["user_id"], "skill": "wiring",
                            "level": "expert"})
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Site One"})).json()

    async with SessionLocal() as db:
        db.add(ActionItem(
            org_id=org["id"], lead_id=lead["id"], title="Terminate the runs",
            required_skill="wiring", status="open",
        ))
        await db.commit()

    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={me['user_id']}&skill=wiring",
        headers=auth(token),
    )
    assert resp.status_code == 409
    assert "wiring" in resp.text


async def test_skill_delete_ignores_a_deactivated_holder(client, super_token):
    """A deactivated user cannot service an open task, so their leftover
    skill row must not count as coverage — the last ACTIVE holder is still
    the last holder. Before the fix, `others` counted the deactivated user
    too, so this delete would have wrongly succeeded (200) while the open
    task was left needing a skill nobody active holds."""
    from app.database import SessionLocal
    from app.models.action_item import ActionItem

    org = await create_org(client, super_token, name="Del Skill Deactivated",
                           slug="del-skill-deact",
                           domain="del-skill-deact-example.com")
    token = org["admin_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()

    other = (await client.post(
        "/api/v1/admin/users", headers=auth(token),
        json={"email": "f-deact@del-skill-deact-example.com", "name": "Deact",
              "role": "operations_agent"},
    )).json()

    for uid in (me["user_id"], other["id"]):
        resp = await client.post("/api/v1/skills", headers=auth(token),
                                 json={"user_id": uid, "skill": "wiring",
                                       "level": "expert"})
        assert resp.status_code == 200, resp.text

    deactivated = await client.patch(
        f"/api/v1/admin/users/{other['id']}",
        headers=auth(token), json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text

    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Site Three"})).json()
    async with SessionLocal() as db:
        db.add(ActionItem(
            org_id=org["id"], lead_id=lead["id"], title="Terminate the runs",
            required_skill="wiring", status="open",
        ))
        await db.commit()

    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={me['user_id']}&skill=wiring",
        headers=auth(token),
    )
    assert resp.status_code == 409, resp.text
    assert "wiring" in resp.text


async def test_missing_skill_is_a_404(client, org_a):
    resp = await client.request(
        "DELETE",
        f"/api/v1/skills?user_id={org_a['agent_id']}&skill=never_held",
        headers=auth(org_a["admin_token"]),
    )
    assert resp.status_code == 404


async def test_playbook_delete_promotes_the_previous_version(client, super_token):
    org = await create_org(client, super_token, name="Del Playbook",
                           slug="del-playbook",
                           domain="del-playbook-example.com")
    token = org["admin_token"]
    program = (await client.post(
        "/api/v1/admin/programs", headers=auth(token),
        json={"name": "Handover", "code": "DPB", "description": "Handover."},
    )).json()

    for title in ("v1 wave", "v2 wave"):
        await client.post("/api/v1/playbooks", headers=auth(token),
                          json={"program_id": program["id"], "phase": "closure",
                                "entries": [{"title": title,
                                             "required_skill": "general",
                                             "offset_days": 0, "priority": "P3",
                                             "visible_to_client": False}]})

    every = (await client.get(
        f"/api/v1/playbooks?program_id={program['id']}&current_only=false",
        headers=auth(token))).json()
    current = next(p for p in every if p["is_current"])
    assert current["version"] == 2

    resp = await client.delete(
        f"/api/v1/playbooks/{current['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text

    remaining = (await client.get(
        f"/api/v1/playbooks?program_id={program['id']}", headers=auth(token))).json()
    assert len(remaining) == 1
    assert remaining[0]["version"] == 1, (
        "deleting the current version must promote its predecessor"
    )


async def test_vendor_delete_succeeds_even_when_a_task_names_it(client, super_token):
    """Nothing references a vendor row (no FK, no id-shaped column anywhere in
    the schema) — `action_items.external_wait` stores a free-text
    `vendor_name`, never the catalogue row's id. Deleting the vendor cannot
    orphan the task: the task keeps its typed `external_wait` text, and the
    vendor list is just a catalogue. This replaces the old refuse-on-409 test,
    which asserted a guard that misrepresented what it protected."""
    org = await create_org(client, super_token, name="Del Vendor",
                           slug="del-vendor", domain="del-vendor-example.com")
    token = org["admin_token"]
    vendor = (await client.post("/api/v1/vendors", headers=auth(token),
                                json={"name": "Cable Supply Co"})).json()
    lead = (await client.post("/api/v1/leads", headers=auth(token),
                              json={"name": "Site Two"})).json()
    task = (await client.post(
        "/api/v1/action-items", headers=auth(token),
        json={"lead_id": lead["id"], "title": "Await cable delivery"},
    )).json()
    waited = await client.post(
        f"/api/v1/tasks/{task['id']}/vendor-promise", headers=auth(token),
        json={"vendor_name": vendor["name"], "promised_date": "2026-09-01T00:00:00"},
    )
    assert waited.status_code == 200, waited.text

    resp = await client.delete(
        f"/api/v1/vendors/{vendor['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert (await client.get("/api/v1/vendors", headers=auth(token))).json() == []

    from app.database import SessionLocal
    from app.models.action_item import ActionItem

    async with SessionLocal() as db:
        row = await db.get(ActionItem, task["id"])
        assert row.external_wait["vendor_name"] == "Cable Supply Co", (
            "the task's typed vendor_name must survive the vendor's deletion"
        )


async def test_unreferenced_vendor_deletes(client, super_token):
    org = await create_org(client, super_token, name="Del Vendor Free",
                           slug="del-vendor-free",
                           domain="del-vendor-free-example.com")
    token = org["admin_token"]
    vendor = (await client.post("/api/v1/vendors", headers=auth(token),
                                json={"name": "Unused Supplier"})).json()

    resp = await client.delete(
        f"/api/v1/vendors/{vendor['id']}", headers=auth(token)
    )
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/v1/vendors", headers=auth(token))).json() == []


async def test_deletes_are_audited(client, super_token):
    org = await create_org(client, super_token, name="Del Audit",
                           slug="del-audit", domain="del-audit-example.com")
    token = org["admin_token"]
    vendor = (await client.post("/api/v1/vendors", headers=auth(token),
                                json={"name": "Audited Supplier"})).json()
    await client.delete(f"/api/v1/vendors/{vendor['id']}", headers=auth(token))

    audit = (await client.get("/api/v1/admin/audit", headers=auth(token))).json()
    assert "ops.vendor_deleted" in [row["action"] for row in audit], (
        "delete_approval_rule writes no audit row; that is not inherited (D13)"
    )
