"""Jarvis answers in English, whatever language it was asked in.

The user may type or SPEAK in any language — the voice path is
`POST /dictate` (Whisper, which transcribes rather than translates) and the
resulting text goes to `POST /assistant/command` like any typed command, so
the backend cannot tell the two apart and neither can this rule.

Measured before this instruction existed, asking the same question three times:

    devanagari -> English, English, English
    kannada    -> English, KANNADA, KANNADA   <- same question, different language

Nothing chose that; the prompt was silent, so the model decided per call. A
reply that flips language between identical runs is unusable in a product, and
the reply is also what the app's TTS reads aloud.
"""
from __future__ import annotations

import pytest

from app.ai.agents.base import AgentRuntime, BaseAgent
from app.core.context import OrgContext

pytestmark = pytest.mark.asyncio


def _prompt() -> str:
    ctx = OrgContext(org_id="o1", user_id="u1", role="sales_agent",
                     email="rep@example.com", name="Rahul")
    runtime = AgentRuntime(db=None, ctx=ctx, extra_context={})
    agent = BaseAgent()
    agent.system_prompt = "You are a test agent."
    return " ".join(agent._system(runtime).split())


async def test_the_assistant_is_told_to_answer_in_english():
    prompt = _prompt().lower()
    assert "english" in prompt


async def test_the_rule_is_stated_to_survive_a_non_english_question():
    """It must be unambiguous that the INPUT language does not decide the
    OUTPUT language — that is exactly the inference the model made on its own
    when the prompt said nothing."""
    prompt = _prompt().lower()
    assert "english" in prompt
    # The instruction has to mention the user's language, or it reads as a
    # generic style note and the model keeps mirroring the question.
    assert "language" in prompt


async def test_the_english_rule_did_not_displace_the_terse_command_rule():
    """F28 is a standing rule: a short or loose command is the AI's problem to
    solve. Adding a language line must not push it out of the prompt."""
    prompt = _prompt()
    assert "short, loosely worded commands" in prompt
    assert "ask ONE clarifying question" in prompt


async def test_the_english_rule_did_not_displace_the_clock():
    """F68: the assistant must still be told today's date."""
    prompt = _prompt()
    assert "Today is" in prompt
