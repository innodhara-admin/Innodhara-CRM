# tests/docx/test_prose.py
import pytest

from app.ai import docx_prose


ENTRIES = [
    {"key": "greeting", "brief": "Two sentence greeting to the client.",
     "max_words": 60, "required": True},
    {"key": "why_us", "brief": "Why YuviPep suits this school.",
     "max_words": 90, "required": False},
]
FACTS = {
    "org_name": "YuviPep", "client_name": "Greenwood International School",
    "contact_name": "Ms Rao", "program_name": "Innovation Lab",
    "program_description": "A hands-on STEAM lab.",
    "project_objective": "Set up a lab for grades 6 to 8 before June.",
    "meeting_notes": "Principal asked about teacher training.",
}


class FakeLayer:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


@pytest.fixture
def ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()


def test_prompt_names_every_placeholder_and_its_budget():
    prompt = docx_prose.build_prompt(ENTRIES, FACTS)
    assert "greeting" in prompt and "why_us" in prompt
    assert "60" in prompt and "90" in prompt
    assert "Greenwood International School" in prompt
    assert "plain text" in prompt.lower()


def test_prompt_tells_the_model_to_return_null_rather_than_invent():
    prompt = docx_prose.build_prompt(ENTRIES, FACTS)
    assert "null" in prompt.lower()


@pytest.mark.asyncio
async def test_clean_text_is_accepted_on_the_first_attempt(ctx, monkeypatch):
    layer = FakeLayer({"placeholders": [
        {"key": "greeting", "text": "We are delighted to write to you. "
                                    "Thank you for your time last week."},
        {"key": "why_us", "text": "YuviPep runs labs in two hundred schools."},
    ]})
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"].startswith("We are delighted")
    assert result["greeting"]["attempts"] == 1
    assert len(layer.calls) == 1


@pytest.mark.asyncio
async def test_a_dirty_fill_is_retried_once_and_then_accepted(ctx, monkeypatch):
    layer = FakeLayer(
        {"placeholders": [{"key": "greeting", "text": "I will now write **this**."},
                          {"key": "why_us", "text": "YuviPep runs many labs."}]},
        {"placeholders": [{"key": "greeting", "text": "We are delighted to write to you."}]},
    )
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"] == "We are delighted to write to you."
    assert result["greeting"]["attempts"] == 2
    assert len(layer.calls) == 2
    assert "markdown_markers" in layer.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_fill_dirty_twice_is_left_unfilled(ctx, monkeypatch):
    layer = FakeLayer(
        {"placeholders": [{"key": "greeting", "text": "I will now write the greeting."},
                          {"key": "why_us", "text": "YuviPep runs many labs."}]},
        {"placeholders": [{"key": "greeting", "text": "Here is the greeting."}]},
    )
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"] is None
    assert "meta_instruction" in result["greeting"]["reasons"]


@pytest.mark.asyncio
async def test_an_explicit_null_is_respected_and_not_retried(ctx, monkeypatch):
    layer = FakeLayer({"placeholders": [
        {"key": "greeting", "text": None, "reason": "no meeting notes"},
        {"key": "why_us", "text": "YuviPep runs many labs."},
    ]})
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"] is None
    assert result["greeting"]["attempts"] == 1
    assert len(layer.calls) == 1


@pytest.mark.asyncio
async def test_an_invented_price_is_rejected(ctx, monkeypatch):
    layer = FakeLayer(
        {"placeholders": [
            {"key": "greeting", "text": "We can offer this for Rs 7,45,000 in total."},
            {"key": "why_us", "text": "YuviPep runs many labs."}]},
        {"placeholders": [{"key": "greeting", "text": "We look forward to working with you."}]},
    )
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts={970000.0})
    assert result["greeting"]["text"] == "We look forward to working with you."


@pytest.mark.asyncio
async def test_no_entries_makes_no_call(ctx, monkeypatch):
    layer = FakeLayer()
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    assert await docx_prose.fill_prose(ctx, entries=[], facts=FACTS,
                                       allowed_amounts=set()) == {}
    assert layer.calls == []
