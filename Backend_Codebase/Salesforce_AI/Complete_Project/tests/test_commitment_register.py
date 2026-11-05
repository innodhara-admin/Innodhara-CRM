"""Finding F56 — the commitment register was write-once.

All 11 commitments on the Round 7 project were created at a single instant —
meeting 1, the create path. Three later merges added **zero**. Six promises read
back aloud in meeting 4 and confirmed by the client became six tasks with
`client_commitment_id = NULL`, so `_sweep_commitments` could never chase any of
them — including "the incident write-up by Thursday", promised to a client who
had just complained.

Data Model §4.5: commitments are "extracted by the Planner and Inbound Engines
**from meetings** and messages". Plural, unqualified.

Nothing was wrong with the plumbing, which is what makes this finding unusual:
the merge path already calls `create_plan_version`, which already persists a
task's `commitment`, and the merge's `new_tasks` already use the schema that
carries the sub-object. The merge **prompt** never asked for one.

Two tests here, doing different jobs:

  * the plumbing test pins the persistence path, so a future refactor cannot
    quietly remove the thing the prompt now relies on;
  * the prompt guard pins the instruction itself. That matters more than it
    looks: F31's lesson, learned the hard way, is that **a sweep is a claim made
    once and a guard is a claim re-made every run**. The behaviour is verified
    against the real model by `scripts/verify_live_commitments.py`; this is what
    notices if the paragraph is ever deleted.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import auth

@pytest.mark.asyncio
async def test_a_merged_task_carrying_a_promise_persists_it(client, org_a):
    """The plumbing F56 said was already correct — pinned so it stays correct."""
    from app.database import SessionLocal
    from app.engines import planner_engine
    from app.models.project import ClientCommitment, Project

    lead = (
        await client.post("/api/v1/leads", headers=auth(org_a["admin_token"]),
                          json={"name": "F56 Register Co"})
    ).json()

    async with SessionLocal() as db:
        project = Project(
            org_id=org_a["id"], lead_id=lead["id"], name="F56 Register",
            status="preparation",
        )
        db.add(project)
        await db.flush()
        project_id = project.id

        # Exactly the shape a merge produces: a new task carrying a commitment.
        await planner_engine.create_plan_version(
            db, org_id=org_a["id"], project=project,
            trigger="new_meeting", trigger_ref=None,
            summary="Merge of meeting 2", changes=["one new promise"],
            new_tasks=[{
                "title": "Send the revised training schedule",
                "phase": "preparation", "required_skill": "general",
                "due_in_days": 10, "priority": "P1", "visible_to_client": True,
                "commitment": {
                    "text": "We will send the revised training schedule by 15 September",
                    "due_in_days": 10, "direction": "ours",
                },
            }],
        )
        await db.commit()

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ClientCommitment).where(
                    ClientCommitment.project_id == project_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1, (
        f"a merged task's promise was not written to the register: {len(rows)} rows"
    )
    assert rows[0].direction == "ours"
    assert rows[0].linked_action_item_id, (
        "the commitment is not linked to its task, so nothing can chase it"
    )


def test_the_merge_prompt_asks_for_new_promises():
    """The guard. F56 was a missing paragraph, so a missing paragraph is what
    this watches for — by meaning, not by exact wording."""
    from app.ai.planning import _MERGE_SYSTEM

    prompt = _MERGE_SYSTEM.lower()
    assert "commitment" in prompt, "the merge prompt never mentions commitments"
    # Before the fix the ONLY mention was renegotiation — the exact shape of the
    # bug: the model was told promises are things that already exist.
    renegotiate_only = (
        "renegotiate_commitment" in prompt
        and '"commitment":' not in prompt
        and "attach its" not in prompt
    )
    assert not renegotiate_only, (
        "the merge prompt mentions commitments only as something to RENEGOTIATE "
        "— that is precisely F56: the register can never gain a row"
    )


def test_the_merge_prompt_forbids_duplicating_a_known_promise():
    """The [F42] interaction, which is the reason this fix needed care.

    Creating commitments on every merge makes F42's double-counting worse unless
    a restated promise is recognised. The rule has to be ID-based: the snapshot
    already lists open commitments with their ids, and the prompt anchors on that
    list. **Text equality is exactly the wrong rule** — F42 says so explicitly,
    because a promise split across two tasks is legitimately two rows.
    """
    from app.ai.planning import _MERGE_SYSTEM

    prompt = _MERGE_SYSTEM.lower()
    assert "open commitments" in prompt, (
        "the anti-duplication rule does not reference the snapshot's own "
        "commitment list, so the model has nothing to check against"
    )
    assert "do not attach" in prompt or "not attach a commitment" in prompt, (
        "nothing tells the model to skip a promise that is already tracked"
    )


def test_the_snapshot_still_shows_the_model_its_open_commitments():
    """The anti-duplication rule is only as good as the list it points at.

    The prompt tells the model not to re-attach a promise that already appears
    under "Open commitments" in the snapshot. If the snapshot ever stops
    building that list — or stops including the ids — the rule silently becomes
    unenforceable: the model would be asked to check against something it cannot
    see, and the failure would look exactly like the model misbehaving.

    That is the shape F37 cost this project: a check blind to the very input it
    exists to judge. Source-level because the snapshot is built inline inside
    `generate_plan_merge`, which also calls the model; the behavioural half runs
    in `scripts/verify_live_commitments.py`.
    """
    import inspect

    from app.ai import planning

    source = inspect.getsource(planning.generate_plan_merge)
    assert "Open commitments" in source, (
        "the merge snapshot no longer lists open commitments, so the prompt's "
        "'do not duplicate what is already tracked' rule has nothing to read"
    )
    assert "c.id" in source, (
        "the snapshot lists commitments without their ids — renegotiate_commitment "
        "needs them, and so does the anti-duplication rule"
    )
