"""Finding F41 — people identified in a FIRST meeting never became contacts or
stakeholders; and F55(a) — an arbitrary `decision_maker` pick.

meeting1 named three people and stated each one's role outright ("I am Mrs. Nair,
the principal. I will be taking the final decision"). The model read all three
correctly. After a full transcribe → extract → review → plan cycle the project
had **0 contacts, 0 stakeholders and 11 ownerless commitments**, and nothing at
that client could be emailed.

The cause was proven by experiment in Act 10, not guessed: meeting **2** on the
same lead, same contract, same model, created Mr. Rao automatically — because the
merge path calls `sync_stakeholder_specs` and the create path does not. A pure
wiring gap.

Data Model §3.3 lists "from a meeting" as one of three documented routes into
`contacts`; §3.4 says stakeholders are "created by the Planner Engine when
meetings reveal who is who". Neither is qualified.

⚠ Two traps are pinned below, because the obvious fix hits both:
  * calling `sync_stakeholder_specs` from the create path DOUBLE-CREATES
    stakeholders (it makes them too, and the create loop then runs over every
    contact with no existence check);
  * it also silently drops `is_primary → decision_maker`, which is what gives
    `primary_stakeholder` a value — and therefore what gives commitments an
    owner. That loss IS F41's consequence #3.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import auth

pytestmark = pytest.mark.asyncio

# The three people meeting1 actually named, in the model's own output shape.
SPECS = [
    {"name": "Mrs. Nair", "role": "principal", "influence": "decision_maker",
     "receives_updates": True},
    {"name": "Arjan", "role": "science_coordinator", "influence": "influencer"},
    {"name": "Divya", "role": "admin_officer"},
]


async def _lead(client, org, name: str) -> str:
    return (
        await client.post("/api/v1/leads", headers=auth(org["admin_token"]),
                          json={"name": name})
    ).json()["id"]


async def _shell(org_id: str, lead_id: str, specs, name: str, agent_id: str):
    """Run the real first-meeting project birth, specs and all."""
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.lead import Lead
    from app.models.meeting import Meeting

    async with SessionLocal() as db:
        lead = (
            await db.execute(select(Lead).where(Lead.id == lead_id))
        ).scalar_one()
        meeting = Meeting(
            org_id=org_id, lead_id=lead_id, meeting_type="first_visit",
            agent_id=agent_id,
        )
        db.add(meeting)
        await db.flush()
        project, primary = await planner_engine._create_project_shell(
            db, org_id=org_id, lead=lead, meeting=meeting, program=None,
            name=name, objective=None, value_estimate=None,
            stakeholder_specs=specs,
        )
        await db.commit()
        return project.id, (primary.id if primary else None)


async def test_a_first_meeting_creates_its_people(client, org_a):
    """The headline: three named people, zero contacts, before this fix."""
    from app.database import SessionLocal
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F41 First Meeting School")
    project_id, _ = await _shell(org_a["id"], lead_id, SPECS, "F41 Project", org_a["agent_id"])

    async with SessionLocal() as db:
        contacts = (
            await db.execute(select(Contact).where(Contact.lead_id == lead_id))
        ).scalars().all()
        stakeholders = (
            await db.execute(
                select(Stakeholder).where(Stakeholder.project_id == project_id)
            )
        ).scalars().all()

    assert len(contacts) == 3, (
        f"F41: a first meeting named three people and created {len(contacts)} "
        f"contacts"
    )
    assert {c.name for c in contacts} == {"Mrs. Nair", "Arjan", "Divya"}
    assert all(c.source == "meeting" for c in contacts), (
        f"Data Model §3.3's `meeting` source is the whole point: "
        f"{[(c.name, c.source) for c in contacts]}"
    )
    # A transcript never contains an address. Inventing one is how a client gets
    # mail meant for someone else.
    assert all(c.email is None and c.phone is None for c in contacts), (
        "an address was invented from speech"
    )
    assert len(stakeholders) == 3, (
        f"expected one stakeholder per discovered person, got {len(stakeholders)}"
    )


async def test_people_are_not_double_created(client, org_a):
    """Trap 1. The obvious fix — call `sync_stakeholder_specs` here — yields TWO
    stakeholder rows per contact, because it creates them and then the create
    loop runs over every contact with no existence check."""
    from app.database import SessionLocal
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F41 No Doubles School")
    project_id, _ = await _shell(org_a["id"], lead_id, SPECS, "F41 No Doubles", org_a["agent_id"])

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Stakeholder).where(Stakeholder.project_id == project_id)
            )
        ).scalars().all()
    by_contact = [r.contact_id for r in rows]
    assert len(by_contact) == len(set(by_contact)), (
        f"duplicate stakeholder rows for the same contact: {by_contact}"
    )


async def test_the_meetings_decision_maker_owns_the_commitments(client, org_a):
    """Trap 2, and F41's consequence #3.

    `primary_stakeholder` is what commitments hang off. All 11 of meeting1's
    commitments were ownerless precisely because it fell through to None. A fix
    that creates people but loses the influence mapping still leaves them
    ownerless — and would pass both tests above.
    """
    from app.database import SessionLocal
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F41 Owner School")
    project_id, primary_id = await _shell(org_a["id"], lead_id, SPECS, "F41 Owner", org_a["agent_id"])

    assert primary_id is not None, (
        "F41 consequence #3: no primary stakeholder, so every commitment this "
        "meeting produced is ownerless"
    )
    async with SessionLocal() as db:
        primary = (
            await db.execute(select(Stakeholder).where(Stakeholder.id == primary_id))
        ).scalar_one()
        from app.models.lead import Contact

        contact = (
            await db.execute(select(Contact).where(Contact.id == primary.contact_id))
        ).scalar_one()
    assert primary.influence == "decision_maker"
    assert contact.name == "Mrs. Nair", (
        f"the wrong person holds the commitments: {contact.name}"
    )


async def test_the_is_primary_rule_survives(client, org_a):
    """Trap 2 from the other side: an EXISTING primary contact with no spec.

    `sync_stakeholder_specs` always defaults influence to `influencer`; the
    create path maps `is_primary → decision_maker`. Swapping one for the other
    quietly leaves `primary_stakeholder = None`.
    """
    from app.database import SessionLocal
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F41 Primary School")
    async with SessionLocal() as db:
        db.add(Contact(
            org_id=org_a["id"], lead_id=lead_id, name="Hand Entered Head",
            title="Principal", email="head@alpha-example.com", is_primary=True,
        ))
        await db.commit()

    # No specs at all — the pre-F41 world, which must keep working.
    project_id, primary_id = await _shell(org_a["id"], lead_id, [], "F41 Primary", org_a["agent_id"])
    assert primary_id is not None, "the is_primary → decision_maker rule was lost"

    async with SessionLocal() as db:
        row = (
            await db.execute(select(Stakeholder).where(Stakeholder.id == primary_id))
        ).scalar_one()
    assert row.influence == "decision_maker"
    assert row.receives_progress_updates is True


async def test_a_contact_added_by_hand_afterwards_becomes_a_stakeholder(client, org_a):
    """F41 consequence #4 — the half that decides whether F41 is actually fixed.

    The create-path loop runs ONCE. Device-proven during Round 7: contacts went
    0 → 3 by hand and stakeholders stayed 0, so the project remained unreachable
    and the only progress recipient left was an addressless person — the state
    [F50] then tripped over.
    """
    from app.database import SessionLocal
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F41 Backfill School")
    project_id, _ = await _shell(org_a["id"], lead_id, [], "F41 Backfill", org_a["agent_id"])

    resp = await client.post(
        f"/api/v1/leads/{lead_id}/contacts", headers=auth(org_a["admin_token"]),
        json={"name": "Late Arrival", "title": "Principal",
              "email": "late@alpha-example.com", "is_primary": True},
    )
    assert resp.status_code == 200, resp.text

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Stakeholder).where(Stakeholder.project_id == project_id)
            )
        ).scalars().all()
    assert len(rows) == 1, (
        "adding a contact by hand still creates no stakeholder — the project "
        "cannot be reached no matter how many people you enter"
    )
    assert rows[0].influence == "decision_maker", (
        "the backfill must use the create path's defaults, not a second set"
    )


async def test_the_backfill_does_not_duplicate_on_a_second_add(client, org_a):
    """A backfill that runs per contact must stay idempotent per project."""
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F41 Idempotent School")
    project_id, _ = await _shell(org_a["id"], lead_id, [], "F41 Idempotent", org_a["agent_id"])
    resp = await client.post(
        f"/api/v1/leads/{lead_id}/contacts", headers=auth(org_a["admin_token"]),
        json={"name": "Only Once", "email": "once@alpha-example.com"},
    )
    contact_id = resp.json()["id"]

    async with SessionLocal() as db:
        contact = (
            await db.execute(select(Contact).where(Contact.id == contact_id))
        ).scalar_one()
        added = await planner_engine.backfill_stakeholders_for_contact(
            db, org_id=org_a["id"], contact=contact
        )
        await db.commit()
    assert added == 0, "re-running the backfill created another stakeholder row"

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Stakeholder).where(
                    Stakeholder.project_id == project_id,
                    Stakeholder.contact_id == contact_id,
                )
            )
        ).scalars().all()
    assert len(rows) == 1


async def test_the_decision_maker_pick_is_deterministic(client, org_a):
    """F55(a): `.first()` over an unordered set decided who gets CC'd on money mail.

    A project can hold more than one `decision_maker` — Round 7 ended with a
    second campus's head attached to the wrong project. Oldest-first means a
    person attached later cannot displace the one the project has known longest.
    """
    from app.database import SessionLocal
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F55 Two Makers School")
    project_id, _ = await _shell(org_a["id"], lead_id, [], "F55 Two Makers", org_a["agent_id"])

    # Explicit, distinct timestamps. Rows created in one loop can land in the
    # same microsecond, and then "oldest" is decided by `id` — stable, but
    # arbitrary, and asserting insertion order against it makes a flaky test out
    # of a sound fix. The guarantee F55(a) needs is that the pick never CHANGES;
    # the guarantee that matters in practice is that a person attached days later
    # cannot displace the original, which is what distinct times model.
    from datetime import timedelta

    from app.models.base import utcnow

    ids = []
    async with SessionLocal() as db:
        for name, age_days in (("First Known", 30), ("Later Arrival", 1)):
            contact = Contact(org_id=org_a["id"], lead_id=lead_id, name=name)
            db.add(contact)
            await db.flush()
            stakeholder = Stakeholder(
                org_id=org_a["id"], project_id=project_id, contact_id=contact.id,
                role_at_client="head", influence="decision_maker",
                created_at=utcnow() - timedelta(days=age_days),
            )
            db.add(stakeholder)
            await db.flush()
            ids.append(stakeholder.id)
        await db.commit()

    # Same query shape the invoice CC uses, ten times over.
    seen = set()
    for _ in range(10):
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(Stakeholder)
                    .where(
                        Stakeholder.project_id == project_id,
                        Stakeholder.influence == "decision_maker",
                    )
                    .order_by(Stakeholder.created_at, Stakeholder.id)
                )
            ).scalars().first()
        seen.add(row.id)
    assert len(seen) == 1, f"the pick is still order-dependent: {seen}"
    assert seen.pop() == ids[0], "the later arrival displaced the original"


# ─────────────────────────────────────────────────────────────────────────────
# F55's contract half — a person from a DIFFERENT engagement.
#
# Round 7 ended with Mrs. Kulkarni, head of the *Hinjuwadai* campus, sitting on
# the **Orchid** project as a `decision_maker`. Workflow 29 spells out a
# per-project stakeholder model ("Kavita is on the bootcamp only"), but
# `_STAKEHOLDER_ITEM_SCHEMA` had no field to say "different engagement", so
# every person a meeting named was bound to that meeting's project.
#
# The fix keeps [F41]'s win: they ARE a real person at this client, so the
# lead-scoped contact is still created. Only the project-scoped stakeholder row
# is withheld.
# ─────────────────────────────────────────────────────────────────────────────


async def test_a_person_from_another_engagement_is_a_contact_but_not_a_stakeholder(
    client, org_a
):
    from app.database import SessionLocal
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    specs = [
        {"name": "Mrs. Nair", "role": "principal", "influence": "decision_maker"},
        {"name": "Mrs. Kulkarni", "role": "head", "influence": "decision_maker",
         "other_engagement": True},
    ]
    lead_id = await _lead(client, org_a, "F55 Two Campus School")
    project_id, _ = await _shell(org_a["id"], lead_id, specs, "F55 Two Campus",
                                 org_a["agent_id"])

    async with SessionLocal() as db:
        contacts = {c.name for c in (
            await db.execute(select(Contact).where(Contact.lead_id == lead_id))
        ).scalars().all()}
        holders = (
            await db.execute(
                select(Stakeholder).where(Stakeholder.project_id == project_id)
            )
        ).scalars().all()
        names = set()
        for h in holders:
            c = (
                await db.execute(select(Contact).where(Contact.id == h.contact_id))
            ).scalar_one()
            names.add(c.name)

    assert "Mrs. Kulkarni" in contacts, (
        "the person was discarded entirely — that undoes F41, which is exactly "
        "the wrong fix this finding warns against"
    )
    assert "Mrs. Kulkarni" not in names, (
        "F55: a person whose involvement is a different engagement is still a "
        "decision_maker on THIS project"
    )
    assert "Mrs. Nair" in names, "the real stakeholder was dropped too"


async def test_a_hand_designated_primary_contact_is_never_demoted(client, org_a):
    """The override. A human marking someone `is_primary` is an explicit choice,
    and the model does not get to overrule it with a passing remark."""
    from app.database import SessionLocal
    from app.models.lead import Contact
    from app.models.project import Stakeholder

    lead_id = await _lead(client, org_a, "F55 Primary Override School")
    async with SessionLocal() as db:
        db.add(Contact(
            org_id=org_a["id"], lead_id=lead_id, name="Chosen By A Human",
            title="Principal", email="chosen@alpha-example.com", is_primary=True,
        ))
        await db.commit()

    specs = [{"name": "Chosen By A Human", "role": "principal",
              "other_engagement": True}]
    project_id, primary_id = await _shell(org_a["id"], lead_id, specs,
                                          "F55 Primary Override", org_a["agent_id"])
    assert primary_id is not None, (
        "the model's 'different engagement' guess demoted a contact a human had "
        "explicitly made primary"
    )
    async with SessionLocal() as db:
        holders = (
            await db.execute(
                select(Stakeholder).where(Stakeholder.project_id == project_id)
            )
        ).scalars().all()
    assert len(holders) == 1
