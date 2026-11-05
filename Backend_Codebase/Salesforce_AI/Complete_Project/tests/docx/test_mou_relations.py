# tests/docx/test_mou_relations.py
"""The model says WHICH TAGS RELATE, never what any of them is worth (D-E).

D15 forbids absolutely that a figure a model produced reaches a document.
This pass is how the arithmetic check learns that an annual total is a price
multiplied by a number of students -- knowledge no part of the system holds
otherwise -- without letting the model near a number.
"""
import pytest

from app.ai import docx_tagfill
from app.ai.docx_tagfill import propose_relations

pytestmark = pytest.mark.asyncio


@pytest.fixture
def ctx_stub():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()

OCC = [
    {"tag_id": "price", "raw": "<ask_calculate:Rs. 4000>", "kind": "ask_calculate",
     "context": "Discounted Price", "default": "Rs. 4000"},
    {"tag_id": "students", "raw": "<ask:75>", "kind": "ask",
     "context": "Number of Students", "default": "75"},
    {"tag_id": "total", "raw": "<ask_calculate:Rs. 3,00,000>",
     "kind": "ask_calculate", "context": "Payable Annual Fees",
     "default": "Rs. 3,00,000"},
]
DOC = "Discounted Price Rs. 4000 Number of Students 75 Payable Annual Fees"


class _Layer:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply

    @property
    def prompt(self):
        return self.calls[-1]["messages"][-1]["content"]


def _use(monkeypatch, reply):
    layer = _Layer(reply)
    monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: layer)
    return layer


async def test_a_well_formed_relation_survives(ctx_stub, monkeypatch):
    _use(monkeypatch, {"relations": [
        {"result": "total", "op": "product", "operands": ["price", "students"]}]})
    assert await propose_relations(
        ctx_stub, occurrences=OCC, document_text=DOC) == [
        {"result": "total", "op": "product", "operands": ["price", "students"]}]


async def test_the_model_cannot_smuggle_a_figure_through(ctx_stub, monkeypatch):
    """A relation is REBUILT from result/op/operands, so anything else the
    model attaches is dropped on the floor rather than trusted."""
    _use(monkeypatch, {"relations": [{
        "result": "total", "op": "product", "operands": ["price", "students"],
        "value": "Rs. 3,00,000", "computed": 300000, "currency": "INR",
    }]})
    (relation,) = await propose_relations(
        ctx_stub, occurrences=OCC, document_text=DOC)
    assert set(relation) == {"result", "op", "operands"}


async def test_a_relation_naming_an_unknown_tag_is_dropped(
        ctx_stub, monkeypatch, caplog):
    _use(monkeypatch, {"relations": [
        {"result": "total", "op": "product", "operands": ["price", "invented"]}]})
    with caplog.at_level("INFO"):
        assert await propose_relations(
            ctx_stub, occurrences=OCC, document_text=DOC) == []
    assert "invented" in caplog.text


async def test_an_unknown_operator_is_dropped(ctx_stub, monkeypatch):
    _use(monkeypatch, {"relations": [
        {"result": "total", "op": "exponentiate", "operands": ["price", "students"]}]})
    assert await propose_relations(
        ctx_stub, occurrences=OCC, document_text=DOC) == []


async def test_a_relation_with_one_operand_is_dropped(ctx_stub, monkeypatch):
    _use(monkeypatch, {"relations": [
        {"result": "total", "op": "sum", "operands": ["price"]}]})
    assert await propose_relations(
        ctx_stub, occurrences=OCC, document_text=DOC) == []


async def test_nothing_relating_is_an_empty_list_not_an_error(
        ctx_stub, monkeypatch):
    _use(monkeypatch, {"relations": []})
    assert await propose_relations(
        ctx_stub, occurrences=OCC, document_text=DOC) == []


async def test_no_occurrences_calls_no_model_at_all(ctx_stub, monkeypatch):
    layer = _use(monkeypatch, {"relations": []})
    assert await propose_relations(
        ctx_stub, occurrences=[], document_text=DOC) == []
    assert layer.calls == []


async def test_the_prompt_forbids_calculating(ctx_stub, monkeypatch):
    """The instruction a person could check, rather than a hope."""
    layer = _use(monkeypatch, {"relations": []})
    await propose_relations(ctx_stub, occurrences=OCC, document_text=DOC)
    prompt = layer.prompt.lower()
    assert "you do not calculate anything" in prompt
    assert "product" in prompt and "sum" in prompt
    for occurrence in OCC:
        assert occurrence["tag_id"] in layer.prompt


async def test_a_malformed_reply_is_survived(ctx_stub, monkeypatch):
    """A model that returns a string, or a list of strings, must not take the
    fill down -- the same tolerance resolve_tags applies to its own output."""
    for reply in ({"relations": "nonsense"}, {"relations": ["x"]},
                  {}, None, {"relations": [None]}):
        _use(monkeypatch, reply)
        assert await propose_relations(
            ctx_stub, occurrences=OCC, document_text=DOC) == []
