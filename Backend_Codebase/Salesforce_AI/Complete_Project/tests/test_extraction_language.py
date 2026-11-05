"""Meetings are not always held in English, but what the meeting LEAVES BEHIND
must be.

A summary, its key facts and its action-item titles are stored permanently,
re-read by every later prompt, embedded into memory and shown to colleagues who
may not share the language the meeting happened in. Whisper transcribes rather
than translates (`stt.py` calls `model.transcribe` with no `task`), so a
Hindi call arrives here as Devanagari and a Kannada call as Kannada script.

Measured before this instruction existed: the model translated to English
anyway, from Hinglish, Devanagari and Kannada alike. That was luck, not
contract — the prompt never asked, and the fast model has already been swapped
twice in this project's history. These tests make it a contract.
"""
from __future__ import annotations

import pytest

from app.ai import extraction
from app.ai.llm import LlmResponse

pytestmark = pytest.mark.asyncio

DEVANAGARI_TRANSCRIPT = """
राहुल: सर, हम आपके दो हॉल का कमिशनिंग कर सकते हैं, कुल 120 रैक।
कविता: ठीक है, लेकिन हैंडओवर दिसंबर चेंज फ्रीज़ से पहले होना चाहिए।
"""

_VALID_JSON = (
    '{"action_items": [], "summary": "s", "real_discussion": true, '
    '"key_facts": []}'
)


class PromptCapturingModel:
    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return LlmResponse(text=_VALID_JSON)

    async def generate_json(self, **kwargs):
        await self.generate(**kwargs)
        return {}


@pytest.fixture
def captured(monkeypatch) -> PromptCapturingModel:
    model = PromptCapturingModel()
    monkeypatch.setattr(extraction, "get_model_layer", lambda: model)
    return model


async def _analyse(transcript: str) -> None:
    await extraction.analyse_meeting(
        transcript, org_name="YuviPep", client_name="Meridian Data Centres"
    )


def flat(text: str) -> str:
    """The prompt is a wrapped triple-quoted string, so a phrase to assert on
    may straddle a newline. Compare on a single line."""
    return " ".join(text.split())


async def test_the_prompt_asks_for_english_output(captured):
    """Whatever language was spoken, the stored record must be readable by
    everyone who later depends on it."""
    await _analyse(DEVANAGARI_TRANSCRIPT)
    prompt = captured.prompts[0].lower()
    assert "english" in prompt


async def test_the_transcript_still_reaches_the_model_in_its_own_script(captured):
    """Translating the OUTPUT must not mean mangling the INPUT: the model has
    to see what was actually said."""
    await _analyse(DEVANAGARI_TRANSCRIPT)
    assert "हैंडओवर" in captured.prompts[0]


async def test_the_english_instruction_did_not_dissolve_the_genericity_fence(
    captured,
):
    """F4: a prompt that invites the model to reword things is exactly how
    'the school operates offices in Bengaluru' got written into an engineering
    firm's permanent memory. Translation must not become licence to substitute
    a vocabulary the speakers never used."""
    await _analyse(DEVANAGARI_TRANSCRIPT)
    prompt = flat(captured.prompts[0])
    assert "the words the transcript itself uses" in prompt
    assert "never assume an industry" in prompt


async def test_the_prompt_resolves_the_clash_with_the_genericity_rule(captured):
    """Observed live the first time this instruction was added: told both to
    answer in English AND never to substitute a word the speakers used, the
    model split the difference and quoted the source language inside otherwise
    English facts — 'Handover must be "December change freeze se pehle"'. Those
    strings are stored permanently and embedded into memory, so the two rules
    have to be disambiguated in the prompt itself, not left to the model."""
    await _analyse(DEVANAGARI_TRANSCRIPT)
    prompt = flat(captured.prompts[0]).lower()
    assert "untranslated" in prompt
    assert "quote" in prompt


async def test_names_are_protected_from_being_translated(captured):
    """'Meridian' must not come back as a Hindi rendering of itself, and a
    person's name must survive intact — they are database keys downstream."""
    await _analyse(DEVANAGARI_TRANSCRIPT)
    prompt = captured.prompts[0].lower()
    assert "name" in prompt and "english" in prompt
