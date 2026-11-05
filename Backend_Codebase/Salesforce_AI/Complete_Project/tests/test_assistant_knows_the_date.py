"""The assistant must know what day it is.

Reported live 2026-08-07 with three screenshots. Asked *"What tasks do I have
due by this Friday?"* Jarvis answered:

    1) Send Fatima the engineer list  - due **Friday** (P2)
    3) Provide single line diagrams   - due **Friday (2026-09-01)** (P2)

Pushed on it, it said:

    "I can't confirm what dates your team considers 'this Friday' versus
     'today' without checking the actual due dates on the tasks."
    "If **2026-09-01 is 'today' for you**, then those 3 tasks are due today."

Three things wrong, one cause:

  * 2026-09-01 is a TUESDAY. It was called Friday.
  * "Send Fatima the engineer list" has `due_date = NULL`. A due date was
    reported for it anyway.
  * It asked the USER what today's date is.

`app/ai/planning.py` (initial plan and merge) and `app/ai/extraction.py` are
all handed `today` in their prompts. `agents/base.py:_system()` — the prompt
behind the only component a human actually converses with — had no date at all.

The failure mode is the point: a model with no clock does not say "I don't know
the date". It borrows a day name from the question and states it as a fact.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core import clock

pytestmark = pytest.mark.asyncio


class _Ctx:
    org_id = "org-1"
    user_id = "u-1"
    role = "sales_agent"
    email = "rahul@yuvipep.com"
    name = "Rahul"


class _Runtime:
    ctx = _Ctx()
    extra_context: dict = {}
    #: The organisation's timezone, resolved once per run by `BaseAgent.run`.
    #: `_system` is sync, so it cannot look this up itself — which is exactly
    #: why it used to reach for the server's own clock instead.
    tz = clock.zone("Asia/Kolkata")


def _today() -> date:
    """Today as the ORGANISATION reckons it — not `date.today()`, which is the
    server's answer and was the original defect one layer down."""
    return clock.today(_Runtime.tz)


def _system_prompt() -> str:
    """The real prompt, built the way the agent loop builds it."""
    from app.ai.agents.query_agent import QueryAgent

    return QueryAgent()._system(_Runtime(), has_history=False)


async def test_the_prompt_states_todays_date() -> None:
    """The headline. Without this the model cannot resolve 'this Friday'."""
    prompt = _system_prompt()
    today = _today()
    assert today.isoformat() in prompt, (
        f"the assistant is never told the date; {today.isoformat()} is absent"
    )


async def test_the_prompt_states_the_weekday() -> None:
    """'This Friday' cannot be resolved from a bare ISO date — the model needs
    to know which weekday today IS to count forward to Friday."""
    prompt = _system_prompt()
    assert _today().strftime("%A") in prompt, (
        "the weekday is missing, so relative weekday phrases stay unresolvable"
    )


async def test_the_prompt_forbids_inventing_a_weekday() -> None:
    """The specific hallucination: calling 2026-09-01 'Friday'."""
    prompt = _system_prompt().lower()
    assert "weekday" in prompt and "derived" in prompt, (
        "nothing tells the model to derive weekdays from real dates"
    )


async def test_the_prompt_forbids_inventing_a_due_date() -> None:
    """The worse hallucination: a due date announced for a task that has none."""
    prompt = _system_prompt().lower()
    assert "not set" in prompt, (
        "the model is not told to say 'not set' for a missing due date"
    )


async def test_every_agent_gets_the_clock_not_just_one() -> None:
    """The F41/F54/F56/F63 pattern: machinery wired to one entry point. The
    clock belongs on the shared base, so every agent inherits it."""
    from app.ai.agents.conversation_agent import ConversationAgent
    from app.ai.agents.email_agent import EmailAgent
    from app.ai.agents.followup_agent import FollowupAgent
    from app.ai.agents.proposal_agent import ProposalAgent
    from app.ai.agents.query_agent import QueryAgent
    from app.ai.agents.scheduling_agent import SchedulingAgent

    today = _today().isoformat()
    for agent_cls in (QueryAgent, ProposalAgent, FollowupAgent, EmailAgent,
                      SchedulingAgent, ConversationAgent):
        prompt = agent_cls()._system(_Runtime(), has_history=False)
        assert today in prompt, f"{agent_cls.__name__} has no clock"


async def test_the_clock_is_not_hardcoded_to_one_day() -> None:
    """A date frozen at import time is worse than none — it would be silently
    wrong from tomorrow onwards."""
    import inspect

    from app.ai.agents.base import BaseAgent

    src = inspect.getsource(BaseAgent._system)
    assert "clock.today(" in src, (
        "the date must be read per-request, not captured once"
    )
    assert "runtime.tz" in src, (
        "the date must be read in the ORGANISATION's timezone. It was read with "
        "`_date.today()` — the server's — and then compared against instants "
        "stored in UTC, which is the F65 defect one layer down."
    )


async def test_the_date_shown_is_the_organisations_not_the_servers() -> None:
    """The strengthening F65 forced. Two organisations either side of the date
    line must be told different days by the same code path — which a prompt
    built from the server's own clock cannot do."""
    from app.ai.agents.query_agent import QueryAgent

    seen = set()
    for tz_name in ("Pacific/Kiritimati", "Pacific/Midway"):
        runtime = _Runtime()
        runtime.tz = clock.zone(tz_name)
        prompt = QueryAgent()._system(runtime, has_history=False)
        seen.add(clock.today(runtime.tz).isoformat() in prompt)
    assert seen == {True}, "the prompt does not follow the organisation's zone"
