# tests/docx/test_tagfill_ai.py
"""The fill pass, and every way a resolution is refused (Task C2).

Nothing here calls a model. `FakeLayer` returns whatever the test scripts, so
each case pins one rule about what the code does with an answer it is given --
which is the whole point: the model is allowed to be wrong, and the tests are
about what happens next.
"""
import datetime
import json
import logging

import pytest

from app.ai import docx_tagfill as tf
from app.services import client_dossier


DOSSIER = {
    "client": {"name": "Orchid International School", "city": "Hyderabad",
               "state": "Telangana", "important": True},
    "contacts": [
        {"name": "Sunil Menon", "title": "Principal", "email": "sunil@orchid.edu"},
        {"name": "Rekha Iyer", "title": "Head of Academics", "email": None},
    ],
    "notes": [{"text": "They want the lab live before the October break.",
               "at": "2026-08-02"}],
    "meetings": [
        {"title": "Discovery call", "at": "2026-08-14",
         "transcript": {"text": "The programme should run 28 September to "
                                "2 October, avoiding the exam block."}},
    ],
    "programme": {"name": "Innovation Lab", "code": "IBC",
                  "description": "A hands-on maker lab."},
    "rate_card": {"version": 3, "currency": "INR",
                  "items": [{"label": "Interactive Panel", "unit_price": 250000}]},
    "sender": {"name": "Siva Kumar", "email": "siva@yuvipep.com"},
    "organisation": {"name": "YuviPep"},
    "omitted": [],
}

DOCUMENT_TEXT = (
    "Proposal for <School Name>\n"
    "Kind attention: <Principal Name>\n"
    "Interactive Panel  <ask:1 Unit>\n"
    "Magazine Rack  <ask:1 Unit>\n"
    "Projector  <ask:1 Unit>\n"
    "Total investment <ask_calculate:Rs. 15,00,000/- to Rs. 25,00,000/->\n"
)

OCCURRENCES = [
    {"tag_id": "aaa000000001", "kind": "semantic", "raw": "<School Name>",
     "default": None, "ordinal": 0, "start": 13, "end": 26,
     "context": "Proposal for", "duplicate_of": None},
    {"tag_id": "aaa000000002", "kind": "semantic", "raw": "<Principal Name>",
     "default": None, "ordinal": 1, "start": 16, "end": 32,
     "context": "Kind attention:", "duplicate_of": None},
    {"tag_id": "bbb000000001", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "ordinal": 2, "start": 18, "end": 30,
     "context": "Interactive Panel", "duplicate_of": None},
    {"tag_id": "bbb000000002", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "ordinal": 3, "start": 15, "end": 27,
     "context": "Magazine Rack", "duplicate_of": "bbb000000001"},
    {"tag_id": "bbb000000003", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "ordinal": 4, "start": 11, "end": 23,
     "context": "Projector", "duplicate_of": "bbb000000001"},
    {"tag_id": "ccc000000001", "kind": "ask_calculate",
     "raw": "<ask_calculate:Rs. 15,00,000/- to Rs. 25,00,000/->",
     "default": "Rs. 15,00,000/- to Rs. 25,00,000/-", "ordinal": 5,
     "start": 17, "end": 66, "context": "Total investment",
     "duplicate_of": None},
]


class FakeLayer:
    """Returns a scripted reply and remembers what it was asked."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply

    @property
    def prompt(self) -> str:
        return self.calls[-1]["messages"][-1]["content"]


@pytest.fixture
def ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()


def _use(monkeypatch, reply) -> FakeLayer:
    layer = FakeLayer(reply)
    monkeypatch.setattr(tf, "get_model_layer", lambda: layer)
    return layer


def _by_id(resolutions) -> dict:
    return {r["tag_id"]: r for r in resolutions}


# --- resolve_tags: what gets filled -----------------------------------------


@pytest.mark.asyncio
async def test_a_confident_semantic_fill_with_a_real_citation_is_filled(
        ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "Orchid International School",
         "confidence": 0.97, "citation": "client.name",
         "reason": "the client's own name"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    got = _by_id(out)["aaa000000001"]
    assert got["outcome"] == "filled"
    assert got["value"] == "Orchid International School"
    assert got["source"] == "ai"
    assert got["citation"] == "client.name"
    assert got["computed_by"] is None


@pytest.mark.asyncio
async def test_a_citation_into_a_list_element_resolves(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000002", "value": "Sunil Menon",
         "confidence": 0.93, "citation": "contacts[0].name: Sunil Menon, Principal",
         "reason": "the principal on file"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[1:2])
    assert _by_id(out)["aaa000000002"]["outcome"] == "filled"


# --- resolve_tags: every way a fill is refused -------------------------------


@pytest.mark.asyncio
async def test_a_semantic_below_the_threshold_becomes_a_question(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000002", "value": "Rekha Iyer", "confidence": 0.6,
         "citation": "contacts[1].name", "reason": "might be the signatory",
         "question": "Who should the proposal be addressed to?"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[1:2])
    got = _by_id(out)["aaa000000002"]
    assert got["outcome"] == "question"
    assert got["value"] is None
    assert got["asked_because"] == tf.LOW_CONFIDENCE
    assert got["question"] == "Who should the proposal be addressed to?"


@pytest.mark.asyncio
async def test_a_confident_fill_with_no_citation_is_downgraded(ctx, monkeypatch):
    """D14. Confidence is self-reported; a citation is checkable."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "Orchid International School",
         "confidence": 0.95, "reason": "obvious from the document"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    got = _by_id(out)["aaa000000001"]
    assert got["outcome"] == "question"
    assert got["asked_because"] == tf.NO_CITATION


@pytest.mark.asyncio
async def test_a_confident_fill_citing_a_fact_not_in_the_dossier_is_downgraded(
        ctx, monkeypatch):
    """D14. The dossier has two contacts, so contacts[7] is an invention."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000002", "value": "Dr Ananya Rao", "confidence": 0.95,
         "citation": "contacts[7].name: Dr Ananya Rao, Principal",
         "reason": "the principal"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[1:2])
    got = _by_id(out)["aaa000000002"]
    assert got["outcome"] == "question"
    assert got["value"] is None
    assert got["asked_because"] == tf.UNKNOWN_CITATION


@pytest.mark.asyncio
async def test_a_citation_naming_a_section_that_does_not_exist_is_downgraded(
        ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "Orchid", "confidence": 0.99,
         "citation": "crm_records[0].account_name", "reason": "the CRM"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    assert _by_id(out)["aaa000000001"]["asked_because"] == tf.UNKNOWN_CITATION


@pytest.mark.asyncio
async def test_a_citation_into_an_absent_field_is_downgraded(ctx, monkeypatch):
    """`contacts[1].email` is None in the dossier: there is no such fact."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000002", "value": "rekha@orchid.edu",
         "confidence": 0.99, "citation": "contacts[1].email", "reason": "on file"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[1:2])
    assert _by_id(out)["aaa000000002"]["asked_because"] == tf.UNKNOWN_CITATION


@pytest.mark.asyncio
async def test_an_ask_at_full_confidence_is_still_a_question(ctx, monkeypatch):
    """D4. The author wrote `ask:`; that is the author asking to be asked."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "1 Unit", "confidence": 1.0,
         "citation": "rate_card.items", "reason": "one panel per lab"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[2:3])
    got = _by_id(out)["bbb000000001"]
    assert got["outcome"] == "question"
    assert got["value"] is None
    assert got["asked_because"] == tf.ASK_BY_DESIGN


@pytest.mark.asyncio
async def test_the_author_default_and_the_model_proposal_are_both_candidates(
        ctx, monkeypatch):
    """D5 offers the default as a tappable candidate; D15 lets the model state
    the conclusion it reached. Neither is written until a person picks one."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "confidence": 1.0,
         "citation": "notes[0].text", "reason": "two rooms were mentioned"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[2:3])
    assert _by_id(out)["bbb000000001"]["candidates"] == ["1 Unit", "2 Units"]


@pytest.mark.asyncio
async def test_the_models_own_arithmetic_never_becomes_an_ask_calculate_value(
        ctx, monkeypatch):
    """D15, as the owner amended it. The assistant always asks and writes what
    the person replies; no figure the model produced reaches a document, and a
    wrong one is no more dangerous than a right one because neither is used.
    """
    _use(monkeypatch, {"resolutions": [
        # 3 x 250000 is 750000. The model says 950000, confidently, citing a
        # fact that really is in the dossier.
        {"tag_id": "ccc000000001", "value": "Rs. 9,50,000/-", "confidence": 1.0,
         "citation": "rate_card.items",
         "reason": "three interactive panels at Rs 2,50,000 each"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[5:])
    got = _by_id(out)["ccc000000001"]
    assert got["outcome"] == "question"
    assert got["value"] is None
    assert got["source"] is None
    assert got["computed_by"] is None
    assert got["asked_because"] == tf.ASK_BY_DESIGN


@pytest.mark.asyncio
async def test_a_hallucinated_tag_id_is_dropped(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "Orchid International School",
         "confidence": 0.97, "citation": "client.name", "reason": "the client"},
        {"tag_id": "deadbeefcafe", "value": "invented", "confidence": 0.99,
         "citation": "client.name", "reason": "a tag that is not in this document"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    assert [r["tag_id"] for r in out] == ["aaa000000001"]


@pytest.mark.asyncio
async def test_a_hallucinated_tag_id_is_reported_and_not_merely_ignored(
        ctx, monkeypatch, caplog):
    """The output is built from the occurrence map, so an invented id could
    never have reached it anyway. What the check is FOR is saying so: a model
    inventing tag ids is a thing an operator has to be able to find out, and
    silence is how that goes unnoticed for a month."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "deadbeefcafe", "value": "invented", "confidence": 0.99,
         "citation": "client.name", "reason": "not a tag in this document"},
    ]})
    with caplog.at_level(logging.INFO, logger="app.ai.docx_tagfill"):
        await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                              occurrences=OCCURRENCES[:1])
    assert any("deadbeefcafe" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_tag_the_model_ignored_becomes_a_question(ctx, monkeypatch):
    """Silence is not a fill. Every occurrence comes back with an outcome."""
    _use(monkeypatch, {"resolutions": []})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES)
    assert len(out) == len(OCCURRENCES)
    assert all(r["outcome"] == "question" for r in out)
    assert _by_id(out)["aaa000000001"]["asked_because"] == tf.NO_VALUE


@pytest.mark.asyncio
async def test_a_question_always_has_something_to_ask(ctx, monkeypatch):
    """The model was confident, so it wrote no question; the downgrade still
    has to produce one a person can answer."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000002", "value": "Dr Ananya Rao", "confidence": 0.95,
         "citation": "contacts[7].name", "reason": "the principal"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[1:2])
    question = _by_id(out)["aaa000000002"]["question"]
    assert question and "<Principal Name>" in question
    assert "Kind attention:" in question


@pytest.mark.asyncio
async def test_a_model_value_that_fails_the_scrub_becomes_a_question(
        ctx, monkeypatch):
    """D10. `fill_scrub` is the fence between a model's prose and a client's
    document, and an unlocked price is exactly what it exists to catch."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "the total cost is Rs 8,50,000",
         "confidence": 0.99, "citation": "client.name", "reason": "the price"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    got = _by_id(out)["aaa000000001"]
    assert got["outcome"] == "question"
    assert got["asked_because"] == tf.UNUSABLE_VALUE


@pytest.mark.asyncio
async def test_a_blank_value_is_a_question_not_an_empty_fill(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "   ", "confidence": 0.99,
         "citation": "client.name", "reason": "nothing to say"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    assert _by_id(out)["aaa000000001"]["asked_because"] == tf.NO_VALUE


@pytest.mark.asyncio
async def test_a_confidence_that_is_not_a_number_is_not_confident(
        ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "Orchid International School",
         "confidence": "very high", "citation": "client.name", "reason": "x"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    assert _by_id(out)["aaa000000001"]["asked_because"] == tf.LOW_CONFIDENCE


@pytest.mark.asyncio
async def test_the_first_answer_for_a_tag_wins(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "Orchid International School",
         "confidence": 0.97, "citation": "client.name", "reason": "first"},
        {"tag_id": "aaa000000001", "value": "Something Else",
         "confidence": 0.99, "citation": "client.name", "reason": "second"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    assert len(out) == 1
    assert out[0]["value"] == "Orchid International School"


@pytest.mark.asyncio
async def test_no_occurrences_calls_no_model(ctx, monkeypatch):
    layer = _use(monkeypatch, {"resolutions": []})
    assert await tf.resolve_tags(ctx, dossier=DOSSIER,
                                 document_text=DOCUMENT_TEXT, occurrences=[]) == []
    assert layer.calls == []


# --- resolve_tags: what the model is actually sent ---------------------------


@pytest.mark.asyncio
async def test_the_first_pass_carries_the_document_and_the_whole_dossier(
        ctx, monkeypatch):
    """D7 and section 8: the document goes in whole on the first pass, and so
    does the dossier -- including the transcript sentence that dates the
    programme, which is the single fact this feature exists to find."""
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                          occurrences=OCCURRENCES)
    prompt = layer.prompt
    assert "<ask_calculate:Rs. 15,00,000/-" in prompt
    assert "28 September to 2 October" in prompt
    assert "Interactive Panel" in prompt
    assert "aaa000000001" in prompt
    assert layer.calls[-1]["tier"] == tf.TIER_STRONG
    assert layer.calls[-1]["org_id"] == "org1"


@pytest.mark.asyncio
async def test_the_prompt_says_what_the_ceiling_dropped(ctx, monkeypatch):
    """D7: a model told what was omitted can ask; one handed a silently
    truncated dossier cannot."""
    layer = _use(monkeypatch, {"resolutions": []})
    dossier = dict(DOSSIER, omitted=[{"section": "notes", "dropped": 12}])
    await tf.resolve_tags(ctx, dossier=dossier, document_text=DOCUMENT_TEXT,
                          occurrences=OCCURRENCES[:1])
    assert "WHAT WAS LEFT OUT OF THE DOSSIER" in layer.prompt
    assert '"dropped": 12' in layer.prompt


@pytest.mark.asyncio
async def test_the_dossier_is_sent_as_the_ceiling_measures_it(ctx, monkeypatch):
    """`DOSSIER_CHAR_CEILING` is enforced against `client_dossier.size_of`,
    which is `json.dumps(dossier, default=str)`. Send anything else -- an
    indented render, say -- and the ceiling bounds a string nobody sends."""
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                          occurrences=OCCURRENCES[:1])
    serialised = json.dumps(DOSSIER, default=str)
    assert serialised in layer.prompt
    assert client_dossier.size_of(DOSSIER) == len(serialised)


@pytest.mark.asyncio
async def test_a_clean_dossier_says_nothing_about_omissions(ctx, monkeypatch):
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                          occurrences=OCCURRENCES[:1])
    assert "WHAT WAS LEFT OUT" not in layer.prompt


@pytest.mark.asyncio
async def test_a_value_the_scrub_rejected_is_not_offered_as_a_candidate(
        ctx, monkeypatch):
    """Tapping a candidate is not typing it. D15 admits a number to a document
    only when Python computed it from the locked rate card or a person wrote
    it out, so prose the fence just refused must not come back as one tap."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "the total cost is Rs 8,50,000",
         "confidence": 0.99, "citation": "client.name", "reason": "the price"},
    ]})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES[:1])
    assert _by_id(out)["aaa000000001"]["candidates"] == []


# --- answer_round ------------------------------------------------------------


OPEN = [
    {"tag_id": "bbb000000001", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "context": "Interactive Panel",
     "question": "How many interactive panels?"},
    {"tag_id": "bbb000000002", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "context": "Magazine Rack",
     "question": "How many magazine racks?"},
    {"tag_id": "bbb000000003", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "context": "Projector",
     "question": "How many projectors?"},
]


@pytest.mark.asyncio
async def test_one_reply_settles_three_duplicate_occurrences(ctx, monkeypatch):
    """D8. The same literal in three rows is three questions and three records,
    and one sentence answers all of them."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "two of each"},
        {"tag_id": "bbb000000002", "value": "2 Units", "reason": "two of each"},
        {"tag_id": "bbb000000003", "value": "2 Units", "reason": "two of each"},
    ]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="two of each please", asked=[])
    assert len(out) == 3
    assert {r["tag_id"] for r in out} == {o["tag_id"] for o in OPEN}
    assert all(r["outcome"] == "filled" and r["value"] == "2 Units" for r in out)


@pytest.mark.asyncio
async def test_an_answered_tag_is_recorded_as_the_persons_own_words(
        ctx, monkeypatch):
    """D14: a user value cites the turn in which the person said it."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "said so"},
    ]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN[:1],
                                user_reply="make it two panels",
                                asked=[{"round": 1}, {"round": 2}, {"round": 3}])
    got = out[0]
    assert got["source"] == "user"
    assert got["confidence"] == 1.0
    assert got["computed_by"] is None
    assert got["citation"] == 'turn 4: "make it two panels"'


@pytest.mark.asyncio
async def test_an_ask_calculate_answer_is_written_verbatim(ctx, monkeypatch):
    """D15. A person who answers "18,00,000 all inclusive" gets exactly that.
    The scrub would reject that figure as an unlocked price, and it must not
    run on words a human typed about a tag the author marked to be asked."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "ccc000000001", "value": "Rs. 18,00,000/- all inclusive",
         "reason": "the salesperson's figure"},
    ]})
    open_calc = [{"tag_id": "ccc000000001", "kind": "ask_calculate",
                  "raw": "<ask_calculate:Rs. 15,00,000/- to Rs. 25,00,000/->",
                  "default": "Rs. 15,00,000/- to Rs. 25,00,000/-",
                  "context": "Total investment",
                  "question": "What is the total investment?"}]
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=open_calc,
                                user_reply="18,00,000 all inclusive", asked=[])
    got = out[0]
    assert got["outcome"] == "filled"
    assert got["value"] == "Rs. 18,00,000/- all inclusive"
    assert got["source"] == "user"
    assert got["warnings"] == []


@pytest.mark.asyncio
async def test_a_persons_semantic_answer_is_kept_and_the_scrub_only_warns(
        ctx, monkeypatch):
    """D10 says the scrub runs on every semantic value, and it does. But a
    person cannot be refused their own words, or the same question is asked
    for ever -- so the reasons are reported for the D13 review, not enforced.
    """
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "the fee is Rs 8,50,000 this year",
         "reason": "the salesperson said so"},
    ]})
    open_semantic = [{"tag_id": "aaa000000001", "kind": "semantic",
                      "raw": "<School Name>", "default": None,
                      "context": "Proposal for", "question": "Which client?"}]
    out = await tf.answer_round(ctx, dossier=DOSSIER,
                                open_questions=open_semantic,
                                user_reply="the fee is Rs 8,50,000 this year",
                                asked=[])
    got = out[0]
    assert got["outcome"] == "filled"
    assert got["value"] == "the fee is Rs 8,50,000 this year"
    assert got["warnings"] == ["unlocked_price"]


@pytest.mark.asyncio
async def test_a_question_the_reply_did_not_settle_stays_open(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "answered"},
        {"tag_id": "bbb000000002", "value": None,
         "question": "And how many magazine racks?"},
    ]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="two panels", asked=[])
    got = _by_id(out)
    assert got["bbb000000001"]["outcome"] == "filled"
    assert got["bbb000000002"]["outcome"] == "question"
    assert got["bbb000000002"]["question"] == "And how many magazine racks?"
    assert got["bbb000000003"]["outcome"] == "question"


@pytest.mark.asyncio
async def test_a_question_the_model_ignored_is_asked_in_the_words_already_used(
        ctx, monkeypatch):
    """The reply said nothing about projectors and the model wrote no new
    question for them, so the one the salesperson has already read stands.
    Replacing it with a generated one reads as the assistant losing its place.
    """
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "answered"},
    ]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="two panels", asked=[])
    got = _by_id(out)["bbb000000003"]
    assert got["question"] == "How many projectors?"
    assert got["candidates"] == ["1 Unit"]


#: Every open question accepted at the author's suggestion -- what the live
#: model did on 11 September with the reply "All the suggested values are
#: fine": forty of forty-four, thirty-seven of which nobody had been shown.
ACCEPT_EVERY_SUGGESTION = {"resolutions": [
    {"tag_id": q["tag_id"], "value": q["default"], "reason": "all fine"}
    for q in OPEN
]}


@pytest.mark.asyncio
async def test_accepting_the_suggestions_settles_only_the_questions_on_screen(
        ctx, monkeypatch):
    """The Orchid contract, 11 September. The person was shown a round and
    tapped "All the suggested values are fine". The model is handed every
    outstanding question (D8) and has no way to know which ones "all" meant,
    so it accepted them all. A suggestion nobody was shown is not one they
    agreed to."""
    _use(monkeypatch, ACCEPT_EVERY_SUGGESTION)
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="All the suggested values are fine",
                                asked=[], on_screen=OPEN[:2])
    got = _by_id(out)
    assert got["bbb000000001"]["outcome"] == "filled"
    assert got["bbb000000001"]["value"] == "1 Unit"
    assert got["bbb000000002"]["outcome"] == "filled"
    assert got["bbb000000003"]["outcome"] == "question"
    assert got["bbb000000003"]["question"] == "How many projectors?"


@pytest.mark.asyncio
async def test_a_suggestion_the_person_names_is_accepted_even_off_screen(
        ctx, monkeypatch):
    """The fence is about agreeing to what nobody showed, not about the value.
    A person who SAYS the figure has answered, whichever round it sits in --
    and says it in their own capitals."""
    _use(monkeypatch, ACCEPT_EVERY_SUGGESTION)
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="fine, and 1 unit for the projector",
                                asked=[], on_screen=OPEN[:2])
    assert _by_id(out)["bbb000000003"]["outcome"] == "filled"


@pytest.mark.asyncio
async def test_a_figure_inside_a_longer_one_is_not_naming_the_suggestion(
        ctx, monkeypatch):
    """ "only the date will be 11.09.2026" contains the character 1. It does
    not name a quantity of one, and an off-screen `<ask:1>` must not be
    settled on the strength of a date."""
    one = [{"tag_id": "ddd000000001", "kind": "ask", "raw": "<ask:1>",
            "default": "1", "context": "R&D engineer",
            "question": "How many R&D engineers?"}]
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "ddd000000001", "value": "1", "reason": "all fine"}]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=one,
                                user_reply="all fine, only the date will be "
                                           "11.09.2026",
                                asked=[], on_screen=[])
    assert out[0]["outcome"] == "question"


@pytest.mark.asyncio
async def test_an_answer_of_its_own_still_settles_a_question_off_screen(
        ctx, monkeypatch):
    """D8 is untouched: "two of each" answers quantities in rounds nobody has
    reached, because the person gave a figure rather than agreeing to one."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": q["tag_id"], "value": "2 Units", "reason": "two of each"}
        for q in OPEN]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="two of each", asked=[],
                                on_screen=OPEN[:1])
    assert [r["outcome"] for r in out] == ["filled", "filled", "filled"]


@pytest.mark.asyncio
async def test_a_twin_of_a_question_on_screen_is_on_screen_too(ctx, monkeypatch):
    """A round shows one question per (raw, context) -- D-D -- so an
    occurrence a person could not tell apart from one they were shown WAS
    shown. Keyed on the tag id instead, "all fine" settles the visible one,
    leaves its twin open, and the identical question comes back next round:
    the loop, through a different door."""
    twin = dict(OPEN[0], tag_id="bbb000000009")
    questions = [*OPEN, twin]
    _use(monkeypatch, {"resolutions": [
        {"tag_id": q["tag_id"], "value": q["default"], "reason": "all fine"}
        for q in questions]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=questions,
                                user_reply="All the suggested values are fine",
                                asked=[], on_screen=OPEN[:1])
    got = _by_id(out)
    assert got["bbb000000009"]["outcome"] == "filled"
    assert got["bbb000000002"]["outcome"] == "question"


@pytest.mark.asyncio
async def test_the_model_is_told_which_questions_were_on_screen(ctx, monkeypatch):
    """The other half of the Orchid defect ran the other way: "Yeah all are
    fine, only the date will be 11.09.2026" accepted NOTHING but the date,
    twice out of two on the live model, because "all" had nothing in the
    prompt to refer to. The model sees every question (D8), so the round a
    person was shown has to be marked in what it is given."""
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                          user_reply="all fine", asked=[], on_screen=OPEN[:1])
    lines = {line.split()[0]: line for line in layer.prompt.splitlines()
             if line.startswith("bbb0000000")}
    assert tf.ON_SCREEN in lines["bbb000000001"]
    assert tf.ON_SCREEN not in lines["bbb000000002"]
    assert tf.ON_SCREEN not in lines["bbb000000003"]


@pytest.mark.asyncio
async def test_a_tag_id_that_is_not_even_a_string_is_dropped(ctx, monkeypatch):
    """A malformed reply must not take the fill down with it: `in` against a
    set raises on an unhashable, and every occurrence still needs an outcome.
    """
    _use(monkeypatch, {"resolutions": [
        {"tag_id": {"nested": "nonsense"}, "value": "x", "reason": "malformed"},
        "not even an object",
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "answered"},
    ]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                user_reply="two panels", asked=[])
    assert len(out) == 3
    assert _by_id(out)["bbb000000001"]["value"] == "2 Units"


@pytest.mark.asyncio
async def test_an_answer_for_a_question_that_was_not_asked_is_dropped(
        ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "answered"},
        {"tag_id": "aaa000000001", "value": "A Different School",
         "reason": "not one of the open questions"},
    ]})
    out = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN[:1],
                                user_reply="two panels", asked=[])
    assert [r["tag_id"] for r in out] == ["bbb000000001"]


@pytest.mark.asyncio
async def test_a_clarification_carries_the_dossier_but_not_the_document(
        ctx, monkeypatch):
    """Section 8: re-sending 6k tokens of document per answer is what would
    make this expensive. The dossier is re-sent whole so turn 7 is grounded in
    the same facts as turn 1."""
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                          user_reply="two of each", asked=[])
    prompt = layer.prompt
    assert "28 September to 2 October" in prompt
    assert "How many magazine racks?" in prompt
    assert "two of each" in prompt
    assert "<ask_calculate:Rs. 15,00,000/-" not in prompt
    assert layer.calls[-1]["tier"] == tf.TIER_STRONG


@pytest.mark.asyncio
async def test_a_clarification_turn_cannot_be_handed_the_document(
        ctx, monkeypatch):
    """Where the invariant above actually lives. `answer_round` has no
    document parameter, so re-sending six thousand tokens of Word text per
    answer is not a thing a caller can do by accident -- it would take a
    signature change, and this is the test that notices one."""
    _use(monkeypatch, {"resolutions": []})
    with pytest.raises(TypeError):
        await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                              user_reply="two of each", asked=[],
                              document_text=DOCUMENT_TEXT)


@pytest.mark.asyncio
async def test_nothing_open_calls_no_model(ctx, monkeypatch):
    layer = _use(monkeypatch, {"resolutions": []})
    assert await tf.answer_round(ctx, dossier=DOSSIER, open_questions=[],
                                 user_reply="anything", asked=[]) == []
    assert layer.calls == []


@pytest.mark.asyncio
async def test_a_model_that_returns_nothing_at_all_leaves_the_fill_intact(
        ctx, monkeypatch):
    """A refused or malformed generation must not silently fill a document."""
    _use(monkeypatch, None)
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text=DOCUMENT_TEXT,
                                occurrences=OCCURRENCES)
    assert all(r["outcome"] == "question" for r in out)
    again = await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                                  user_reply="two of each", asked=[])
    assert all(r["outcome"] == "question" for r in again)


# --- revise: a correction made during the review (D13, J2) -------------------


REVIEWED = [
    {"tag_id": "aaa000000001", "kind": "semantic", "raw": "<School Name>",
     "default": None, "context": "Proposal for", "outcome": "filled",
     "value": "Orchid International School", "source": "ai",
     "citation": "client.name"},
    {"tag_id": "bbb000000001", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "context": "Interactive Panel", "outcome": "filled",
     "value": "1 Unit", "source": "user", "citation": 'turn 1: "one of each"'},
    {"tag_id": "bbb000000002", "kind": "ask", "raw": "<ask:1 Unit>",
     "default": "1 Unit", "context": "Magazine Rack", "outcome": "filled",
     "value": "1 Unit", "source": "user", "citation": 'turn 1: "one of each"'},
]


@pytest.mark.asyncio
async def test_a_correction_changes_only_the_tag_it_names(ctx, monkeypatch):
    """The review showed every value; the person objected to one of them. The
    other twenty-four must not be touched by a sentence that was not about
    them."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units",
         "reason": "the panel row"},
    ]})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="the interactive panel should be two")
    assert [r["tag_id"] for r in out] == ["bbb000000001"]
    assert out[0]["value"] == "2 Units"
    assert out[0]["outcome"] == "filled"


@pytest.mark.asyncio
async def test_a_corrected_value_is_the_persons_own(ctx, monkeypatch):
    """D14 for a correction: it cites the words the person actually used, and
    it is theirs -- not the model's -- however the model phrased the mapping."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "said so"},
    ]})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="make the panel two units")
    got = out[0]
    assert got["source"] == "user"
    assert got["confidence"] == 1.0
    assert got["computed_by"] is None
    assert got["citation"] == 'the correction: "make the panel two units"'
    # `reviewed` is not this module's to set: it belongs to the fill session
    # record, and proposal_fill_service._record clears it on every tag a pass
    # touches. Asserted there, where it actually happens.


@pytest.mark.asyncio
async def test_one_correction_can_change_several_tags(ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "2 Units", "reason": "both"},
        {"tag_id": "bbb000000002", "value": "2 Units", "reason": "both"},
    ]})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="two of each of those")
    assert {r["tag_id"] for r in out} == {"bbb000000001", "bbb000000002"}


@pytest.mark.asyncio
async def test_a_correction_naming_a_tag_that_is_not_there_is_dropped(
        ctx, monkeypatch):
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "deadbeefcafe", "value": "2 Units", "reason": "invented"},
    ]})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="two of each")
    assert out == []


@pytest.mark.asyncio
async def test_a_correction_the_model_could_not_place_changes_nothing(
        ctx, monkeypatch):
    """Better to say "I did not understand" and post the review again than to
    guess which of twenty-five values a vague sentence meant."""
    _use(monkeypatch, {"resolutions": []})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="that looks wrong somehow")
    assert out == []


@pytest.mark.asyncio
async def test_a_correction_with_no_value_is_not_a_blank(ctx, monkeypatch):
    """Returning a tag with no value would empty the cell -- a tag resolved to
    "" is REMOVED from the document by tagfill. A correction that says nothing
    about what to write instead is not a correction."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "bbb000000001", "value": "", "reason": "unsure"},
        {"tag_id": "bbb000000002", "value": None, "reason": "unsure"},
    ]})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="change the quantities")
    assert out == []


@pytest.mark.asyncio
async def test_a_corrected_semantic_value_is_kept_and_only_warned_about(
        ctx, monkeypatch):
    """Same rule as an answer: the scrub fences a model's prose, never a
    person's own words. The reasons ride along for the review to show."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "aaa000000001", "value": "the fee is Rs 8,50,000 this year",
         "reason": "said so"},
    ]})
    out = await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                          correction="say the fee is Rs 8,50,000 this year")
    assert out[0]["value"] == "the fee is Rs 8,50,000 this year"
    assert out[0]["warnings"] == ["unlocked_price"]


@pytest.mark.asyncio
async def test_the_review_correction_sees_every_value_and_the_dossier(
        ctx, monkeypatch):
    """The model cannot map "the panel" onto a tag_id without being shown
    which tag is in which row, and what it currently says."""
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.revise(ctx, dossier=DOSSIER, resolutions=REVIEWED,
                    correction="the panel should be two")
    prompt = layer.prompt
    assert "Interactive Panel" in prompt and "Magazine Rack" in prompt
    assert "bbb000000001" in prompt
    assert "Orchid International School" in prompt
    assert "the panel should be two" in prompt
    assert "28 September to 2 October" in prompt      # the dossier went too
    assert layer.calls[-1]["tier"] == tf.TIER_STRONG


@pytest.mark.asyncio
async def test_nothing_to_revise_calls_no_model(ctx, monkeypatch):
    layer = _use(monkeypatch, {"resolutions": []})
    assert await tf.revise(ctx, dossier=DOSSIER, resolutions=[],
                           correction="anything") == []
    assert layer.calls == []


# --- one question standing for several places (D47) --------------------------
#
# A round shows ONE question for every place that reads the same, so a person
# who answers it has answered all of them. Two things follow, and the owner's
# eleven-round contract is what they cost: D46's fence has to count those
# places as shown, and an answer has to reach the ones the model did not name.

SAME_QUESTION_TWICE = [
    {"tag_id": "eee000000001", "kind": "ask", "raw": "<ask:Innovation Nexus>",
     "default": "Innovation Nexus", "context": "Programme Opted",
     "question": "What is the name of the innovation program?"},
    {"tag_id": "eee000000002", "kind": "ask", "raw": "<ask:Innovation Nexus>",
     "default": "Innovation Nexus", "context": "MoU for",
     "question": "What is the name of the innovation program?"},
    {"tag_id": "eee000000003", "kind": "ask", "raw": "<ask:75>",
     "default": "75", "context": "Minimum Enrolment",
     "question": 'What should replace <ask:75> in "Minimum Enrolment"?'},
]


@pytest.mark.asyncio
async def test_a_question_that_reads_the_same_elsewhere_is_on_screen_too(
        ctx, monkeypatch):
    """The Orchid contract, 11 September, after D46 shipped.

    The programme name was asked in four separate rounds and the owner tapped
    "All the suggested values are fine" at every one. Only the round's own
    occurrence was on screen, so the fence refused the other three -- right by
    its own rule, wrong in effect. They read identically and the round now
    draws them as one, so agreeing to it agrees to all of them. The twin that
    merely shares a suggested value is still refused.
    """
    _use(monkeypatch, {"resolutions": [
        {"tag_id": q["tag_id"], "value": q["default"], "reason": "all fine"}
        for q in SAME_QUESTION_TWICE]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=SAME_QUESTION_TWICE,
        user_reply="All the suggested values are fine", asked=[],
        on_screen=SAME_QUESTION_TWICE[:1])
    got = _by_id(out)
    assert got["eee000000002"]["outcome"] == "filled"
    assert got["eee000000003"]["outcome"] == "question"


@pytest.mark.asyncio
async def test_accepting_the_suggestion_settles_every_place_that_reads_the_same(
        ctx, monkeypatch):
    """The owner's round, and the tap that was costing them one each time.

    "All the suggested values are fine" about the programme name is an answer
    for all four places that ask it: the value is what the template's author
    wrote in every one of them. The model answered only the id it was shown;
    the rest are settled here, because leaving one open asks the identical
    question again next round.
    """
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "eee000000001", "value": "Innovation Nexus",
         "reason": "all the suggested values are fine"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=SAME_QUESTION_TWICE,
        user_reply="All the suggested values are fine", asked=[],
        on_screen=SAME_QUESTION_TWICE[:1])
    got = _by_id(out)
    assert got["eee000000002"]["outcome"] == "filled"
    assert got["eee000000002"]["value"] == "Innovation Nexus"
    assert got["eee000000002"]["source"] == "user"


@pytest.mark.asyncio
async def test_a_value_the_person_typed_reaches_only_the_place_they_were_shown(
        ctx, monkeypatch):
    """The guard, and the owner's ruling of 11 September.

    Whether two places that read alike are one question cannot be known from
    the words. The programme name on their contract is asked four times and
    means one answer; a model that writes "How many of these do you want?"
    for the Laptops row and the Interactive Panel row means two, and the
    proposal flow has a round that does exactly that. So the author's own
    suggestion travels and a typed figure does not: putting back what the
    author wrote is no surprise anywhere, and "2 Units" in a row nobody was
    shown is D1's defect arriving through the question layer.
    """
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "eee000000001", "value": "Innovation Nexus Plus",
         "reason": "they named it"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=SAME_QUESTION_TWICE,
        user_reply="call it Innovation Nexus Plus", asked=[],
        on_screen=SAME_QUESTION_TWICE[:1])
    got = _by_id(out)
    assert got["eee000000001"]["value"] == "Innovation Nexus Plus"
    assert got["eee000000002"]["outcome"] == "question"


@pytest.mark.asyncio
async def test_a_place_the_model_answered_itself_keeps_its_own_value(
        ctx, monkeypatch):
    """The guard on the spreading. A person's sentence may tell two places
    apart that the round drew as one, and the model is the thing that read the
    sentence. An answer it gave is never overwritten by a sibling's."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "eee000000001", "value": "Innovation Nexus",
         "reason": "the operation terms row"},
        {"tag_id": "eee000000002", "value": "Innovation Nexus Junior",
         "reason": "the heading says Junior"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=SAME_QUESTION_TWICE,
        user_reply="the heading one is Junior", asked=[],
        on_screen=SAME_QUESTION_TWICE[:1])
    got = _by_id(out)
    assert got["eee000000001"]["value"] == "Innovation Nexus"
    assert got["eee000000002"]["value"] == "Innovation Nexus Junior"


@pytest.mark.asyncio
async def test_an_unanswered_question_spreads_nothing(ctx, monkeypatch):
    """A round the reply did not touch stays open in every one of its places.
    Spreading "still a question" as though it were an answer would fill the
    document with blanks, and tagfill treats a blank as "delete this"."""
    _use(monkeypatch, {"resolutions": []})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=SAME_QUESTION_TWICE,
        user_reply="I will check and come back", asked=[],
        on_screen=SAME_QUESTION_TWICE[:1])
    assert [r["outcome"] for r in out] == ["question", "question", "question"]


# Three gaps the mutation check found: each of these deletes a rule the suite
# could not see, because another rule happened to cover the same fixture.

NO_SUGGESTION_TWICE = [
    {"tag_id": "fff000000001", "kind": "semantic", "raw": "<School Address>",
     "default": None, "context": "whose address is",
     "question": "What is the school's address?"},
    {"tag_id": "fff000000002", "kind": "semantic", "raw": "<School Address>",
     "default": None, "context": "Address:",
     "question": "What is the school's address?"},
]


@pytest.mark.asyncio
async def test_a_twin_answered_instead_of_the_one_on_screen_settles_both(
        ctx, monkeypatch):
    """The model is handed every occurrence (D8) and need not answer the one
    the round happened to draw. Accepting the author's suggestion for the
    other place is the same agreement, so the fence lets it through -- and the
    place that WAS on screen is then settled from it. Without that, the round
    comes back asking what the person just agreed to."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "eee000000002", "value": "Innovation Nexus",
         "reason": "all fine"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=SAME_QUESTION_TWICE,
        user_reply="All the suggested values are fine", asked=[],
        on_screen=SAME_QUESTION_TWICE[:1])
    got = _by_id(out)
    assert got["eee000000002"]["outcome"] == "filled"
    assert got["eee000000001"]["outcome"] == "filled"
    assert got["eee000000003"]["outcome"] == "question"


@pytest.mark.asyncio
async def test_places_with_no_suggestion_never_settle_each_other(
        ctx, monkeypatch):
    """Only the author's own suggestion travels, so a place that HAS none can
    never be settled by its twin.

    And a round nobody answered must spread nothing at all. These records
    carry no value and no suggestion, so a check that compared only those two
    would find them equal and write an empty value into both -- and tagfill
    reads an empty value as "delete this tag", which is a cell silently
    removed from a contract.
    """
    _use(monkeypatch, {"resolutions": []})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=NO_SUGGESTION_TWICE,
        user_reply="I will find out and come back", asked=[],
        on_screen=NO_SUGGESTION_TWICE[:1])
    assert [r["outcome"] for r in out] == ["question", "question"]


@pytest.mark.asyncio
async def test_the_same_wording_with_a_different_suggestion_is_another_question(
        ctx, monkeypatch):
    """The key is the wording AND the value offered, not the wording alone.

    Two places can ask the same sentence about different suggestions, because
    the author wrote each of them, and agreeing to one says nothing about the
    other. Keyed on the wording alone, "all the suggested values are fine"
    would put the first place's value into the second -- a value its author
    never wrote there, which is the one thing spreading must never do.
    """
    other = dict(SAME_QUESTION_TWICE[1], tag_id="eee000000004",
                 default="Innovation Nexus Junior")
    questions = [SAME_QUESTION_TWICE[0], other]
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "eee000000001", "value": "Innovation Nexus",
         "reason": "all fine"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=questions,
        user_reply="All the suggested values are fine", asked=[],
        on_screen=questions[:1])
    assert _by_id(out)["eee000000004"]["outcome"] == "question"


# --- the fill has a clock (D48) ----------------------------------------------
#
# It had none. No date reached any of the three prompts, so on 11 September the
# owner was offered "1.9.2026" for the modified date and "First Day of
# September, Two Thousand Twenty-Six (01-09-2026)" for the agreement date, and
# nothing in the system could tell either of them was in the past. The author
# wrote those; the fill simply could not read a calendar.

STALE_DATE = [
    {"tag_id": "ggg000000001", "kind": "ask", "raw": "<ask:1.9.2026>",
     "default": "1.9.2026", "ordinal": 0, "start": 0, "end": 14,
     "context": "Bookmarks: status: ; author:; acceptor: ; modified:",
     "duplicate_of": None},
]


@pytest.mark.asyncio
async def test_the_first_pass_is_told_what_day_it_is(ctx, monkeypatch):
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.resolve_tags(ctx, dossier=DOSSIER, document_text="A document",
                          occurrences=STALE_DATE,
                          today=datetime.date(2026, 9, 11))
    assert "11 September 2026" in layer.prompt


@pytest.mark.asyncio
async def test_the_answer_pass_is_told_what_day_it_is(ctx, monkeypatch):
    """So that "it's the 11th" and "next Friday" mean a day, and so that the
    model can see for itself that a suggested date has gone by."""
    layer = _use(monkeypatch, {"resolutions": []})
    await tf.answer_round(ctx, dossier=DOSSIER, open_questions=OPEN,
                          user_reply="the 11th", asked=[],
                          today=datetime.date(2026, 9, 11))
    assert "11 September 2026" in layer.prompt


@pytest.mark.asyncio
async def test_a_suggested_date_that_has_passed_is_offered_as_today(
        ctx, monkeypatch):
    """The owner's ruling of 11 September: offer today, and still ask.

    The author's own text is kept and shown -- it is what the document says --
    but the tap a person reaches for is today's date, written the way the
    author wrote theirs.
    """
    _use(monkeypatch, {"resolutions": []})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text="A document",
                               occurrences=STALE_DATE,
                               today=datetime.date(2026, 9, 11))
    assert out[0]["outcome"] == "question"
    assert out[0]["candidates"][0] == "11.9.2026"
    assert "1.9.2026" in out[0]["candidates"], (
        "the author's own suggestion stopped being offered at all")
    assert out[0]["default_has_passed"] is True


@pytest.mark.asyncio
async def test_a_suggested_date_still_to_come_is_left_alone(ctx, monkeypatch):
    """Only a date that has GONE BY is stale. "second week of February 2027"
    is the programme's end and nobody should be nudged away from it."""
    ahead = [dict(STALE_DATE[0], default="1.12.2026", raw="<ask:1.12.2026>")]
    _use(monkeypatch, {"resolutions": []})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text="A document",
                               occurrences=ahead,
                               today=datetime.date(2026, 9, 11))
    assert out[0]["candidates"][0] == "1.12.2026"
    assert not out[0].get("default_has_passed")


@pytest.mark.asyncio
async def test_a_suggestion_that_is_not_purely_a_date_is_never_rewritten(
        ctx, monkeypatch):
    """The agreement date reads "First Day of September, Two Thousand
    Twenty-Six (01-09-2026)". Rewriting prose into today's date is a sentence
    this code would be inventing, and D15's whole point is that it must not.
    The model is told the date and can offer the wording; the tap is not
    substituted here."""
    prose = [dict(STALE_DATE[0],
                  default="First Day of September, Two Thousand Twenty-Six "
                          "(01-09-2026)")]
    _use(monkeypatch, {"resolutions": []})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER, document_text="A document",
                               occurrences=prose,
                               today=datetime.date(2026, 9, 11))
    assert out[0]["candidates"][0].startswith("First Day of September")
    assert not out[0].get("default_has_passed")


@pytest.mark.asyncio
async def test_a_suggestion_that_is_not_a_date_at_all_is_left_alone(
        ctx, monkeypatch):
    """The guard. "1 Set", "32", "Yes" and "75" must never be read as dates."""
    _use(monkeypatch, {"resolutions": []})
    for value in ("1 Set", "32", "Yes", "75", "Rs. 4000", "3, 5, 6, 7, 8 and 9"):
        occurrence = [dict(STALE_DATE[0], default=value,
                           raw="<ask:%s>" % value)]
        out = await tf.resolve_tags(ctx, dossier=DOSSIER,
                                    document_text="A document",
                                    occurrences=occurrence,
                                    today=datetime.date(2026, 9, 11))
        assert out[0]["candidates"][0] == value, value
        assert not out[0].get("default_has_passed"), value


@pytest.mark.asyncio
async def test_a_date_with_words_after_it_is_not_purely_a_date(
        ctx, monkeypatch):
    """The other end of the same rule as the prose case, and the one a
    loose pattern would let through: a suggestion that BEGINS with a date
    and then says something. Rewriting it would keep the author's words
    and move their date, which is worse than leaving both alone.
    """
    trailing = [dict(STALE_DATE[0], default="1.9.2026 or thereabouts")]
    _use(monkeypatch, {"resolutions": []})
    out = await tf.resolve_tags(ctx, dossier=DOSSIER,
                                document_text="A document",
                                occurrences=trailing,
                                today=datetime.date(2026, 9, 11))
    assert out[0]["candidates"][0] == "1.9.2026 or thereabouts"
    assert not out[0].get("default_has_passed")


# --- accepting a suggestion that has passed takes today (D51) ----------------
#
# D48 put today at the front of the taps and said so on the line. It did not
# change what "All the suggested values are fine" MEANS for that question, so
# the owner's contract of 11 September was built with the template author's
# own "modified: 1.9.2026" at the top of it -- ten days stale, on the line the
# reader sees first.

PASSED = [
    {"tag_id": "hhh000000001", "kind": "ask", "raw": "<ask:1.9.2026>",
     "default": "1.9.2026", "context": "Bookmarks: modified:",
     "question": "What is the modified date?",
     "candidates": ["11.9.2026", "1.9.2026"], "default_has_passed": True},
]


@pytest.mark.asyncio
async def test_accepting_a_suggestion_that_has_passed_takes_today(
        ctx, monkeypatch):
    """They agreed to what the round SHOWED them, and what it showed was
    today. The author's ten-day-old date is on the list underneath, and
    nobody tapped it."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "hhh000000001", "value": "1.9.2026", "reason": "all fine"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=PASSED,
        user_reply="All the suggested values are fine", asked=[],
        on_screen=PASSED, today=datetime.date(2026, 9, 11))
    assert out[0]["outcome"] == "filled"
    assert out[0]["value"] == "11.9.2026"


@pytest.mark.asyncio
async def test_a_person_who_asks_for_the_old_date_gets_the_old_date(
        ctx, monkeypatch):
    """The guard, and it is not hypothetical: a contract can be dated the day
    it was agreed rather than the day it was typed. Naming the date is
    choosing it, and nothing here overrules a person who did."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "hhh000000001", "value": "1.9.2026",
         "reason": "they asked for it"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=PASSED,
        user_reply="keep it as 1.9.2026", asked=[],
        on_screen=PASSED, today=datetime.date(2026, 9, 11))
    assert out[0]["value"] == "1.9.2026"


@pytest.mark.asyncio
async def test_a_date_the_person_typed_is_never_replaced_by_today(
        ctx, monkeypatch):
    """An answer of their own is an answer. Only the author's stale suggestion
    is swapped, and only when it was accepted rather than chosen."""
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "hhh000000001", "value": "2.10.2026", "reason": "they said"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=PASSED,
        user_reply="make it the second of October", asked=[],
        on_screen=PASSED, today=datetime.date(2026, 9, 11))
    assert out[0]["value"] == "2.10.2026"


@pytest.mark.asyncio
async def test_a_suggestion_that_has_not_passed_is_accepted_as_written(
        ctx, monkeypatch):
    """Nothing changes for the ordinary question, which is nearly all of
    them: no `default_has_passed`, no substitution."""
    ordinary = [dict(PASSED[0], default_has_passed=False,
                     candidates=["second week of February 2027"],
                     default="second week of February 2027")]
    _use(monkeypatch, {"resolutions": [
        {"tag_id": "hhh000000001", "value": "second week of February 2027",
         "reason": "all fine"}]})
    out = await tf.answer_round(
        ctx, dossier=DOSSIER, open_questions=ordinary,
        user_reply="All the suggested values are fine", asked=[],
        on_screen=ordinary, today=datetime.date(2026, 9, 11))
    assert out[0]["value"] == "second week of February 2027"
