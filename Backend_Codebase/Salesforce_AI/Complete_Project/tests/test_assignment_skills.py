"""Finding F25 — assignment could never match a skill: `user_skills` was empty
AND the planner invented a free-form vocabulary, so every task fell to the
phase-lead fallback flagged "no skill match". The fix seeds a real taxonomy,
constrains the planner to it, and backs that with a deterministic coercion."""
from __future__ import annotations

import pytest

from tests.conftest import auth

pytestmark = pytest.mark.asyncio


async def test_invented_skill_is_coerced_to_general_when_a_taxonomy_exists():
    """A prompt instruction is not a fence (the job's recurring lesson): if the
    model invents a skill outside the org's taxonomy it would match nobody, so
    it is recorded as a gap but coerced onto 'general', which everyone holds."""
    from app.ai.planning import validate_task_specs

    org_skills = ["general", "proposal_preparation", "logistics_coordination"]
    tasks = [
        {"title": "Draft the proposal", "required_skill": "proposal_preparation",
         "due_in_days": 3},
        {"title": "Book forklift training", "required_skill": "forklift_training",
         "due_in_days": 5},
        {"title": "Coordinate logistics", "required_skill": "Logistics Coordination",
         "due_in_days": 2},
    ]
    specs, gaps = validate_task_specs(tasks, org_skills)
    by_title = {s["title"]: s for s in specs}

    # A real skill is kept as-is.
    assert by_title["Draft the proposal"]["required_skill"] == "proposal_preparation"
    # An invented skill matches nobody -> coerced to 'general', gap recorded.
    assert by_title["Book forklift training"]["required_skill"] == "general"
    assert "forklift_training" in gaps
    # A taxonomy skill written in prose is normalised and kept, not coerced.
    assert by_title["Coordinate logistics"]["required_skill"] == "logistics_coordination"


async def test_no_taxonomy_keeps_the_models_word():
    """Bootstrap: an org that has never defined skills keeps the invented name —
    there is nothing to coerce onto."""
    from app.ai.planning import validate_task_specs

    specs, gaps = validate_task_specs(
        [{"title": "X", "required_skill": "forklift_training", "due_in_days": 1}], []
    )
    assert specs[0]["required_skill"] == "forklift_training"
    assert "forklift_training" in gaps


async def test_a_seeded_skill_produces_a_real_match_not_no_skill_match(client, org_a):
    """With a project member holding the required skill, the assignment engine
    returns them at the project_member tier with a real skill_level — the reason
    is a skill match, not the 'no skill match' phase-lead fallback."""
    from app.database import SessionLocal
    from app.engines.assignment_engine import build_candidates
    from app.models.action_item import ActionItem
    from app.models.project import Project, ProjectMember
    from app.models.user import UserSkill

    token = org_a["admin_token"]
    org_id = org_a["id"]
    agent_id = org_a["agent_id"]
    lead = (
        await client.post("/api/v1/leads", headers=auth(token),
                          json={"name": "Skill Match School"})
    ).json()

    async with SessionLocal() as db:
        db.add(UserSkill(org_id=org_id, user_id=agent_id,
                         skill="proposal_preparation", level="good"))
        project = Project(org_id=org_id, lead_id=lead["id"], name="Skill Match Project")
        db.add(project)
        await db.flush()
        db.add(ProjectMember(org_id=org_id, project_id=project.id, user_id=agent_id))
        task = ActionItem(
            org_id=org_id, lead_id=lead["id"], project_id=project.id,
            title="Draft the proposal", required_skill="proposal_preparation",
            status="open",
        )
        db.add(task)
        await db.flush()

        candidates, tier = await build_candidates(db, org_id=org_id, task=task)

    assert tier == "project_member", tier
    assert candidates, "expected the skilled member as a candidate"
    assert candidates[0].skill_level == "good", candidates[0].skill_level
