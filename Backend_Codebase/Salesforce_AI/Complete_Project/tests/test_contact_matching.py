"""People a meeting names are checked by the model before they become
contacts (Ollama School of Commerce, 1 Oct 2026).

Speech-to-text wrote "Rishabh Jain" for the saved contact "Risabh Jain", and
the spelling check let a duplicate contact through. The Planner also saved a
contact literally called "Accounts Head", and two names for one person in the
same meeting ("Rishabh", "Mr. Jain") would each become a contact.

Now one model call scores every person the meeting named: is it a person or
only a role, is it the same as an earlier name in this meeting, and is it the
same as a saved contact. 0.7 or above means the same; below means different.
The model's answers are stood in for here; `test_the_parse_*` checks what is
done with a bad answer.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.ai import planning
from app.database import SessionLocal
from app.engines import planner_engine
from app.models.lead import Contact
from app.models.project import Project, Stakeholder
from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio

API = "/api/v1"


@pytest.fixture
async def org(client, super_token):
    tag = uuid.uuid4().hex[:8]
    org = await create_org(client, super_token, name=f"People {tag}",
                           slug=f"people-{tag}", domain=f"people{tag}-example.com")
    me = (await client.get(f"{API}/auth/me", headers=auth(org["admin_token"]))).json()
    org["admin_id"] = me["user_id"]
    return org


@pytest.fixture
def model(monkeypatch):
    """Stand in for the model: `answers` is what it returns; `calls` what it
    was asked."""
    state = {"answers": [], "calls": [], "fail": False}

    async def review(*, org_id, people, contacts):
        state["calls"].append({"people": people, "contacts": contacts})
        if state["fail"]:
            raise planning.PlanningUnavailable("model down")
        return planning.parse_people_review(
            {"people": state["answers"]}, people_count=len(people),
            contact_count=len(contacts))

    monkeypatch.setattr(planner_engine.nlu, "llm_available", lambda: True)
    monkeypatch.setattr(planning, "review_meeting_people", review)
    return state


def _answer(i, *, person=True, same_as=None, same_as_score=0.0,
            contact=None, contact_score=0.0):
    return {"index": i, "is_person": person, "same_as": same_as,
            "same_as_score": same_as_score, "contact": contact,
            "contact_score": contact_score, "reason": "test"}


async def _lead_with_contact(client, org, name="Risabh Jain", title="Principal"):
    lead = (await client.post(f"{API}/leads", headers=auth(org["admin_token"]),
                              json={"name": f"Client {uuid.uuid4().hex[:6]}"})).json()
    async with SessionLocal() as db:
        db.add(Contact(org_id=org["id"], lead_id=lead["id"], name=name, title=title,
                       email="principal@example.com", is_primary=True))
        project = Project(org_id=org["id"], lead_id=lead["id"], name="Work",
                          status="planning")
        db.add(project)
        await db.commit()
        return lead["id"], project.id


async def _contacts(lead_id):
    async with SessionLocal() as db:
        return (await db.execute(select(Contact).where(Contact.lead_id == lead_id)
                                 .order_by(Contact.created_at))).scalars().all()


async def _sync(org, project_id, specs):
    async with SessionLocal() as db:
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()
        notes = await planner_engine.sync_stakeholder_specs(
            db, org_id=org["id"], project=project, specs=specs)
        await db.commit()
        return notes


async def test_a_misspelt_saved_contact_is_not_added_again(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org)
    model["answers"] = [_answer(0, contact=0, contact_score=0.92)]
    await _sync(org, project_id, [{"name": "Rishabh Jain", "role": "principal",
                                   "influence": "decision_maker"}])
    assert [c.name for c in await _contacts(lead_id)] == ["Risabh Jain"]
    async with SessionLocal() as db:
        roles = (await db.execute(select(Stakeholder).where(
            Stakeholder.project_id == project_id))).scalars().all()
    assert [(s.role_at_client, s.influence) for s in roles] == [("principal", "decision_maker")], \
        "the meeting's reading of the person attaches to the saved contact"


async def test_below_the_threshold_a_new_contact_is_added(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org)
    model["answers"] = [_answer(0, contact=0, contact_score=0.5)]
    await _sync(org, project_id, [{"name": "Rahul Jain", "role": "teacher_in_charge"}])
    assert [c.name for c in await _contacts(lead_id)] == ["Risabh Jain", "Rahul Jain"]


async def test_exactly_the_threshold_counts_as_the_same_person(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org)
    model["answers"] = [_answer(0, contact=0, contact_score=0.7)]
    await _sync(org, project_id, [{"name": "Mr. Jain"}])
    assert [c.name for c in await _contacts(lead_id)] == ["Risabh Jain"]


async def test_a_role_with_no_name_is_not_saved_as_a_contact(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org)
    model["answers"] = [_answer(0, person=False, contact=0, contact_score=0.1)]
    notes = await _sync(org, project_id, [{"name": "Accounts Head", "role": "accounts_head"}])
    assert [c.name for c in await _contacts(lead_id)] == ["Risabh Jain"]
    assert any("Accounts Head" in n and "name" in n for n in notes), notes


async def test_a_role_that_is_a_saved_contacts_title_maps_to_them(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org, name="Meera Shah",
                                                   title="Accounts Head")
    model["answers"] = [_answer(0, person=False, contact=0, contact_score=0.85)]
    await _sync(org, project_id, [{"name": "the accounts head", "role": "accounts_head"}])
    assert [c.name for c in await _contacts(lead_id)] == ["Meera Shah"]


async def test_two_names_for_one_person_in_a_meeting_become_one_contact(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org, name="Priya Nair")
    model["answers"] = [
        _answer(0),
        _answer(1, same_as=0, same_as_score=0.88),
    ]
    await _sync(org, project_id, [
        {"name": "Mr. Jain", "role": "principal"},
        {"name": "Rishabh Jain", "influence": "decision_maker", "receives_updates": True},
    ])
    names = [c.name for c in await _contacts(lead_id)]
    assert names == ["Priya Nair", "Rishabh Jain"], \
        "one contact, under the fuller of the two names"
    async with SessionLocal() as db:
        contact = (await db.execute(select(Contact).where(
            Contact.lead_id == lead_id, Contact.name == "Rishabh Jain"))).scalar_one()
        st = (await db.execute(select(Stakeholder).where(
            Stakeholder.contact_id == contact.id))).scalar_one()
    assert (st.role_at_client, st.influence, st.receives_progress_updates) == \
        ("principal", "decision_maker", True), "what each name told us is kept"


async def test_the_first_meeting_path_uses_the_same_check(client, org, model):
    """The first meeting builds the project shell, which creates the contacts
    and stakeholders itself (F41); it must not save the duplicate either."""
    from app.models.meeting import Meeting

    lead_id, _ = await _lead_with_contact(client, org)
    model["answers"] = [_answer(0, contact=0, contact_score=0.95),
                        _answer(1, person=False)]
    async with SessionLocal() as db:
        from app.models.lead import Lead
        lead = (await db.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()
        meeting = Meeting(org_id=org["id"], lead_id=lead_id,
                          agent_id=org["admin_id"], status="completed")
        db.add(meeting)
        await db.flush()
        project, _primary = await planner_engine._create_project_shell(
            db, org_id=org["id"], lead=lead, meeting=meeting, program=None,
            name="Shell", objective=None, value_estimate=None,
            stakeholder_specs=[{"name": "Rishabh Jain", "role": "principal"},
                               {"name": "Accounts Head", "role": "accounts_head"}],
        )
        await db.commit()
        stakeholders = (await db.execute(select(Stakeholder).where(
            Stakeholder.project_id == project.id))).scalars().all()
    assert [c.name for c in await _contacts(lead_id)] == ["Risabh Jain"]
    assert [s.role_at_client for s in stakeholders] == ["principal"]


async def test_when_the_model_is_down_people_are_still_saved(client, org, model):
    lead_id, project_id = await _lead_with_contact(client, org)
    model["fail"] = True
    await _sync(org, project_id, [{"name": "Rishabh Jain"}])
    assert [c.name for c in await _contacts(lead_id)] == ["Risabh Jain", "Rishabh Jain"], \
        "losing a person is worse than a duplicate a human can merge"


async def test_nothing_named_means_no_model_call(client, org, model):
    _lead_id, project_id = await _lead_with_contact(client, org)
    await _sync(org, project_id, [])
    assert model["calls"] == []


async def test_the_model_is_shown_the_saved_contacts_and_the_new_names(client, org, model):
    _lead_id, project_id = await _lead_with_contact(client, org)
    model["answers"] = [_answer(0)]
    await _sync(org, project_id, [{"name": "Rishabh Jain", "role": "principal"}])
    call = model["calls"][0]
    assert call["contacts"] == [{"name": "Risabh Jain", "title": "Principal"}]
    assert call["people"] == [{"name": "Rishabh Jain", "role": "principal"}]


def test_the_parse_ignores_bad_answers():
    parse = planning.parse_people_review
    raw = {"people": [
        {"index": 0, "is_person": True, "contact": 5, "contact_score": 0.99},  # no such contact
        {"index": 1, "is_person": True, "same_as": 1, "same_as_score": 0.9},   # itself
        {"index": 2, "is_person": True, "same_as": 0, "same_as_score": 7},     # score out of range
        {"index": 9, "is_person": False},                                        # no such person
        "junk",
    ]}
    out = parse(raw, people_count=3, contact_count=1)
    assert out[0]["contact"] is None
    assert out[1]["same_as"] is None
    assert out[2]["same_as"] == 0 and out[2]["same_as_score"] == 1.0
    assert set(out) == {0, 1, 2}
    # A person the model said nothing about is a person, matching nothing.
    assert parse({"people": []}, people_count=1, contact_count=0) == {
        0: {"is_person": True, "same_as": None, "same_as_score": 0.0,
            "contact": None, "contact_score": 0.0}}
