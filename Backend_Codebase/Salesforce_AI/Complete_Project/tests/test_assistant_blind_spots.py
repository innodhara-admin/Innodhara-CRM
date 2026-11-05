"""Findings F45, F46 and F57 — three questions the assistant answered
confidently and wrongly, for one underlying reason: the data was not in its view.

**F45** — `who is doing the curriculum` answered with the CLIENT's science
coordinator; `who is assigned to the curriculum task` correctly answered our own
Baski. Retrieval was never broken. The bare phrasing silently resolved to
client-side people, which inverts responsibility for a deliverable: the rep stops
chasing internally and waits on a client who was never asked.

**F46** — `why did you pick baski` explained why it had *mentioned* the name in
conversation, dropping the recorded caveat *"tie; lead should confirm or change"*
— the one clause the question exists to surface. `why_trace` had exactly one
caller (the app's Why? chip) and `assignments.reason` was in no agent's view.

**F57** — `how many approvals are waiting on me` was answered from the TASK LIST.
Device-proven on two roles, including a sales lead who genuinely held approvals
and got her to-do list back under "Due later". No agent exposed approvals at all.

All three are the same spec rule: *"When the AI is unsure, it asks — it never
guesses"* (Workflows §4, stated to stand above all ten engines). The fix for the
last two is **a tool, not a prompt** — you cannot instruct a model into data it
cannot reach.

These tests pin the *reachability* of the data, deterministically. Whether the
model then phrases the answer well is a live-script question
(`verify_live_assistant_context.py`), not a unit-test one.
"""
from __future__ import annotations

import pytest

from tests.conftest import auth


def test_the_query_agent_can_see_approvals_and_reasons():
    """F57 + F46: the tools exist at all. This is the whole finding — no agent
    exposed approvals, so the model reached for the nearest tool and relabelled
    its output."""
    from app.ai.agents.query_agent import QueryAgent

    names = {t.name for t in QueryAgent().tools()}
    assert "list_approvals" in names, (
        "F57: nothing exposes approvals, so 'what is waiting on me' can only be "
        "answered from some other tool's data"
    )
    assert "explain_decision" in names, (
        "F46: the recorded reasoning is reachable only by tapping the app's Why? "
        "chip, never through natural language"
    )


def test_the_approvals_tool_returns_the_stage():
    """F57's second-order trap, named in the finding.

    This org holds a `stage=recommend` approval that deliberately does NOT appear
    in the default decide queue. An answer that counted it alongside decide-stage
    cards would mislead in a quieter way than the original bug.
    """
    from app.ai.agents.query_agent import QueryAgent

    spec = next(t for t in QueryAgent().tools() if t.name == "list_approvals")
    assert "approval" in spec.description.lower()
    # The tool must not be describable as, or mistakable for, the task list.
    assert "not the task list" in spec.description.lower(), (
        "nothing stops the model treating this as another way to list tasks — "
        "which is exactly what it did"
    )


def test_a_task_carries_its_recorded_assignment_reason(client, org_a):
    """F46: the reason must reach the model VERBATIM, caveats included.

    A paraphrase drops "tie; lead should confirm or change", which is the
    difference between a confident staffing decision and one the system itself
    wants reviewed.
    """
    from app.ai.agents.query_agent import _item_dict
    from app.models.action_item import ActionItem

    reason = "Baski: expert skill match, 0/8 open tasks — tie; lead should confirm or change"
    item = ActionItem(
        org_id=org_a["id"], title="Design workshop curriculum for grades 6-8",
        priority="P1", assignment_reason=reason,
    )
    shape = _item_dict(item, owner="Baski", lead="Orchid International School")
    assert shape.get("assignment_reason") == reason, (
        "the recorded reason is not in the model's view of a task — F46: no "
        "agent can answer 'why did you pick X' from data"
    )
    assert "tie" in shape["assignment_reason"], "the caveat was lost"


def test_the_priority_field_survives(client, org_a):
    """The F19 regression guard, re-asserted because F46 changed this exact dict.

    F19 happened when `_item_dict` changed shape: the model stopped seeing
    priority and silently answered "what are the priorities?" by due date. The
    finding warns that adding a field here is how that recurs.
    """
    from app.ai.agents.query_agent import _item_dict
    from app.models.action_item import ActionItem

    item = ActionItem(org_id=org_a["id"], title="A task", priority="P1")
    shape = _item_dict(item, owner="Someone", lead="Someone Co")
    for field in ("id", "title", "status", "priority", "owner", "client",
                  "due_date", "description"):
        assert field in shape, f"_item_dict lost `{field}` — that is how F19 happened"


@pytest.mark.asyncio
async def test_approvals_are_scoped_to_the_caller_and_org(client, org_a, org_b):
    """The tool must not become a cross-org or cross-user leak.

    Adding a reader for the product's central control table is exactly where an
    isolation mistake would matter most.
    """
    from app.ai.agents.base import AgentRuntime
    from app.ai.agents.query_agent import QueryAgent
    from app.core.constants import ApprovalEntityType
    from app.core.context import OrgContext
    from app.database import SessionLocal
    from app.models.comms import Approval

    async with SessionLocal() as db:
        db.add(Approval(
            org_id=org_b["id"], entity_type=ApprovalEntityType.PLAN_CHANGE.value,
            entity_id="other-org-plan", status="pending",
            reason="Another organisation's approval",
        ))
        await db.commit()

    ctx = OrgContext(
        org_id=org_a["id"], user_id=org_a["agent_id"],
        role="sales_agent", email="agent@alpha-example.com",
    )
    async with SessionLocal() as db:
        runtime = AgentRuntime(db=db, ctx=ctx, extra_context={})
        rows = await QueryAgent()._list_approvals(runtime, mine=False, status="all")

    assert all("Another organisation" not in (r["reason"] or "") for r in rows), (
        "the approvals tool leaked another organisation's approvals"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Found live 2026-08-06, on the datacentre demo.
#
#   asked   : "tell me a brief about the project"
#   answered: "I can't find a project brief for Meridian Data Centres in the
#              past notes I searched (no matching results came back). What
#              specific project name/topic should I look up?"
#
# It was not being evasive. NO tool returned a project — all eight were lead- or
# task-scoped — so the only thing left was semantic note search, which is empty
# because the embedding credits are exhausted. The single most natural question
# in the product had no data behind it.
#
# Third instance of F46/F57's pattern, and the same fix: a TOOL, not a prompt.
# ─────────────────────────────────────────────────────────────────────────────


def test_the_agent_can_reach_a_project_at_all():
    from app.ai.agents.query_agent import QueryAgent

    names = {t.name for t in QueryAgent().tools()}
    assert "get_project_brief" in names, (
        "no tool returns a project, so 'tell me about the project' can only be "
        "answered from semantic note search — which is exactly what happened"
    )


def test_the_brief_tool_is_described_in_the_words_a_user_uses():
    """A tool the model cannot recognise is a tool that does not exist."""
    from app.ai.agents.query_agent import QueryAgent

    spec = next(t for t in QueryAgent().tools() if t.name == "get_project_brief")
    d = spec.description.lower()
    for phrase in ("brief", "about the project", "how is it going", "where are we"):
        assert phrase in d, f"the description does not cover {phrase!r}"


@pytest.mark.asyncio
async def test_the_brief_carries_the_facts_a_human_would_ask_for(client, org_a):
    from app.database import SessionLocal
    from app.engines import assistant_engine
    from app.models.project import Project
    from sqlalchemy import select

    lead = (
        await client.post("/api/v1/leads", headers=auth(org_a["admin_token"]),
                          json={"name": "Brief Test Datacentre"})
    ).json()
    async with SessionLocal() as db:
        project = Project(
            org_id=org_a["id"], lead_id=lead["id"],
            name="Brief Test — Commissioning", status="delivery",
            objective="Commission two halls, 120 racks, before the December freeze.",
            current_plan_version=2,
        )
        db.add(project)
        await db.flush()
        pid = project.id
        await db.commit()

    async with SessionLocal() as db:
        row = (
            await db.execute(select(Project).where(Project.id == pid))
        ).scalar_one()
        brief = await assistant_engine.project_brief(
            db, org_id=org_a["id"], project=row
        )

    for key in ("project", "status", "health", "why_that_health", "objective",
                "current_plan_version", "tasks_by_status", "client_people",
                "open_promises", "next_due"):
        assert key in brief, f"the brief cannot answer about `{key}`"
    assert brief["objective"].startswith("Commission two halls")
    assert brief["current_plan_version"] == 2
    # Health must come with its REASON, not a bare word — that is F43's lesson.
    assert isinstance(brief["why_that_health"], list) and brief["why_that_health"]


@pytest.mark.asyncio
async def test_a_client_with_no_project_yet_is_said_plainly(client, org_a):
    """Never "no results found". Say what is actually true."""
    from app.ai.agents.base import AgentRuntime
    from app.ai.agents.query_agent import QueryAgent
    from app.core.context import OrgContext
    from app.database import SessionLocal

    lead = (
        await client.post("/api/v1/leads", headers=auth(org_a["admin_token"]),
                          json={"name": "No Project Yet Co"})
    ).json()
    ctx = OrgContext(org_id=org_a["id"], user_id=org_a["agent_id"],
                     role="sales_agent", email="agent@alpha-example.com")
    async with SessionLocal() as db:
        runtime = AgentRuntime(db=db, ctx=ctx, extra_context={"lead_id": lead["id"]})
        out = await QueryAgent()._project_brief(runtime)
    assert out.get("no_project_yet") is True
    assert "no project yet" in out["note"].lower()


# ── F-21Sep: "show my open tasks" asked which client ─────────────────────────


class _Runtime:
    """Just the part of AgentRuntime `_effective_client` reads."""

    def __init__(self, lead_id: str | None = None):
        self.extra_context = {"lead_id": lead_id} if lead_id else {}


def test_a_placeholder_is_not_a_client_name():
    """Measured live on 21 Sep 2026: the model filled `client` with the word
    "default", the tool looked it up, found nothing, and a plain "show my open
    tasks" came back as "which client did you mean?" — in English as well as
    in Kannada and Hindi."""
    from app.ai.agents.query_agent import _effective_client

    for said in ("default", "none", "N/A", "unknown", "nil", "me", "mine", "", "  "):
        assert _effective_client(_Runtime(), said) is None, said
    assert _effective_client(_Runtime(), None) is None
    # A real name still filters, and still reaches resolve_lead untouched.
    assert _effective_client(_Runtime(), "Greenwood High") == "Greenwood High"


def test_the_screens_client_still_scopes_the_question():
    """F17 must survive the fix: with a lead open on screen, an unnamed
    client means that lead."""
    from app.ai.agents.query_agent import _effective_client

    assert _effective_client(_Runtime("lead-123"), None) == "lead-123"
    # A placeholder means "they did not say", so the screen decides — it does
    # not send "default" to the resolver.
    assert _effective_client(_Runtime("lead-123"), "default") == "lead-123"
    # "all" is the deliberate way to broaden, and beats the screen.
    assert _effective_client(_Runtime("lead-123"), "all") is None
    # A named client still wins over the screen.
    assert _effective_client(_Runtime("lead-123"), "Acme") == "Acme"
