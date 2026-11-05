# tests/docx/test_suggest.py
import pytest

from app.ai import docx_suggest


OUTLINE = {
    "blocks": [
        {"id": "b0", "path": "body[0]", "kind": "heading", "style": "Heading1",
         "level": 1, "text": "Proposal For", "images": [], "table": None,
         "fingerprint": "sha256:a"},
        {"id": "b1", "path": "body[1]", "kind": "paragraph", "style": "Normal",
         "level": None, "text": "School Name", "images": [], "table": None,
         "fingerprint": "sha256:b"},
        {"id": "b2", "path": "body[2]", "kind": "paragraph", "style": "Body Text",
         "level": None, "text": "YuviPep is a global learning ecosystem that "
         "empowers students through experiential education.",
         "images": [], "table": None, "fingerprint": "sha256:c"},
        {"id": "b3", "path": "body[3]", "kind": "table", "style": "", "level": None,
         "text": "Description | Estimation", "images": [], "table":
         {"rows": 3, "cols": 2, "header": ["Description", "Estimation"],
          "sample": [["Description", "Estimation"], ["Item", "Rs 0"], ["Total", "Rs 0"]]},
         "fingerprint": "sha256:d"},
    ],
    "headings": [{"id": "b0", "path": "body[0]", "level": 1, "text": "Proposal For"}],
    "tokens": [{"literal": "School Name", "occurrences": 6, "sample_block_ids": ["b1"]}],
    "media": ["image1.png"],
}


class FakeLayer:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


@pytest.fixture
def ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()


@pytest.mark.asyncio
async def test_returns_entries_that_reference_real_blocks(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "token", "key": "client_name", "literal": "School Name",
         "confidence": 0.95, "why": "repeated stand-in for the client"},
        {"kind": "insert", "key": "greeting_para", "after": "body[0]",
         "style_ref": "body[2]", "shape": "paragraph",
         "brief": "Opening greeting to the client.", "max_words": 90,
         "required": True, "confidence": 0.8, "why": "no greeting present"},
        {"kind": "table", "key": "pricing_table", "path": "body[3]",
         "columns": [{"col": 0, "field": "label"}, {"col": 1, "field": "line_total"}],
         "header_rows": 1, "total_row": {"label_col": 0, "value_col": 1},
         "confidence": 0.9, "why": "priced table"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    out = await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                     program_name="Innovation Lab")
    assert {e["key"] for e in out} == {"client_name", "greeting_para", "pricing_table"}
    assert all("fingerprint" in e for e in out if e["kind"] != "token")


@pytest.mark.asyncio
async def test_drops_a_suggestion_pointing_at_a_block_that_does_not_exist(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "insert", "key": "ghost", "after": "body[99]", "style_ref": "body[2]",
         "shape": "paragraph", "brief": "x", "max_words": 50, "required": False,
         "confidence": 0.5, "why": "invented"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    assert await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                      program_name="Innovation Lab") == []


@pytest.mark.asyncio
async def test_drops_a_token_literal_absent_from_the_document(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "token", "key": "client_name", "literal": "Not In This Document",
         "confidence": 0.9, "why": "guessed"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    assert await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                      program_name="Innovation Lab") == []


@pytest.mark.parametrize("literal", [" ", "e", "the", "", "  \n ", "-", "12"])
def test_drops_a_literal_too_slight_to_be_a_stand_in(literal):
    # "in the document" is no guard by itself: all_text is the whole document,
    # so any short string is in it. A literal of " " accepted here would have
    # replace_token rewrite every space in the file with the client's name.
    kept = docx_suggest._validate(
        {"suggestions": [{"kind": "token", "key": "client_name",
                          "literal": literal, "confidence": 0.9, "why": "x"}]},
        OUTLINE,
    )
    assert kept == []


def test_keeps_a_real_stand_in_phrase():
    kept = docx_suggest._validate(
        {"suggestions": [{"kind": "token", "key": "client_name",
                          "literal": "School Name", "confidence": 0.9, "why": "x"}]},
        OUTLINE,
    )
    assert len(kept) == 1
    assert kept[0]["literal"] == "School Name"


@pytest.mark.asyncio
async def test_drops_a_duplicate_key(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "token", "key": "client_name", "literal": "School Name",
         "confidence": 0.9, "why": "a"},
        {"kind": "token", "key": "client_name", "literal": "School Name",
         "confidence": 0.9, "why": "b"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    out = await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                     program_name="Innovation Lab")
    assert len(out) == 1


@pytest.mark.asyncio
async def test_ocr_text_reaches_the_prompt(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": []})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    await docx_suggest.suggest(ctx, outline=OUTLINE,
                               ocr={"image1.png": "OUR MISSION"},
                               program_name="Innovation Lab")
    assert "OUR MISSION" in layer.calls[0]["messages"][0]["content"]
