# tests/docx/test_tagfill.py
"""The occurrence-addressed writer (Task A3).

The mechanism proved in plan section 2.3 and reproduced here: address a tag as
(walk ordinal, start, end), re-verify it is still there, and replace it with
`replace_span` -- right to left within each paragraph, because replacing left
to right invalidates every later offset in the same paragraph.
"""
import io
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import tagfill as tf
from app.services.docx import tags as tg
from app.services.docx import text as dt

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
TAGGED_SAMPLE = SAMPLES_DIR / "Innovation Lab Template (tagged).docx"


def occurrences_for(data: bytes) -> list[dict]:
    return [o.as_dict() for o in tg.scan(data)]


def texts_of(data: bytes) -> list[str]:
    doc = Document(io.BytesIO(data))
    return [dt.node_text(p) for p in dt.walk_paragraphs(doc)]


def marker_values(occurrences) -> dict[str, str]:
    """A distinct, traceable value per occurrence."""
    return {o["tag_id"]: f"VALUE-{o['tag_id']}" for o in occurrences}


# --- the ordinary case ------------------------------------------------------


def test_a_tag_is_replaced_and_its_paragraph_keeps_everything_else(tagged_fragmented_docx):
    occurrences = occurrences_for(tagged_fragmented_docx)
    result = tf.apply_tags(
        tagged_fragmented_docx, occurrences,
        {occurrences[0]["tag_id"]: "Greenwood High"},
    )
    assert texts_of(result["docx"])[0] == "Welcome to Greenwood High for the year."
    assert [w["tag_id"] for w in result["written"]] == [occurrences[0]["tag_id"]]
    assert result["skipped"] == []


def test_the_source_document_is_never_rewritten(tagged_fragmented_docx):
    """D3. Generation is source + occurrence map + values -> a NEW file."""
    before = bytes(tagged_fragmented_docx)
    occurrences = occurrences_for(tagged_fragmented_docx)
    result = tf.apply_tags(
        tagged_fragmented_docx, occurrences,
        {occurrences[0]["tag_id"]: "Greenwood High"},
    )
    assert tagged_fragmented_docx == before
    assert result["docx"] != before
    assert tg.scan(tagged_fragmented_docx) != []


def test_a_replacement_inherits_the_formatting_of_the_run_it_lands_in():
    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run("Dear ")
    bold = paragraph.add_run("<School Name>")
    bold.bold = True
    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()

    occurrences = occurrences_for(data)
    result = tf.apply_tags(data, occurrences, {occurrences[0]["tag_id"]: "Greenwood"})

    runs = Document(io.BytesIO(result["docx"])).paragraphs[0].runs
    carrying = [r for r in runs if "Greenwood" in r.text]
    assert len(carrying) == 1
    assert carrying[0].bold is True


# --- right to left, which is the whole mechanism ----------------------------


def test_two_tags_in_one_paragraph_are_both_written_correctly(tagged_table_docx):
    """Left to right would shift the second tag's offsets by the length change.

    The first replacement is 9 characters shorter than the tag it replaces, so
    a left-to-right writer either corrupts the second one or -- with the
    staleness check in place -- refuses it. Either way this test fails.
    """
    occurrences = occurrences_for(tagged_table_docx)
    shared = [o for o in occurrences
              if o["raw"] in ("<ask: (10 units)>", "<ask:(3 Nos)>")]
    assert len({o["ordinal"] for o in shared}) == 1

    result = tf.apply_tags(tagged_table_docx, shared, {
        shared[0]["tag_id"]: "12 units",
        shared[1]["tag_id"]: "4 Nos",
    })

    assert result["skipped"] == []
    assert texts_of(result["docx"])[shared[0]["ordinal"]] == (
        "CRO, Safety Glass 12 units, Drill Machine 4 Nos"
    )


# --- refusing to write in the wrong place -----------------------------------


def test_a_stale_offset_is_skipped_rather_than_written_in_the_wrong_place(tagged_table_docx):
    occurrences = occurrences_for(tagged_table_docx)
    target = dict(occurrences[0])
    target["start"] += 1
    target["end"] += 1

    result = tf.apply_tags(tagged_table_docx, [target], {target["tag_id"]: "NEVER"})

    assert result["written"] == []
    assert [s["reason"] for s in result["skipped"]] == [tf.SKIP_STALE]
    after = texts_of(result["docx"])
    assert target["raw"] in after[target["ordinal"]]
    assert not any("NEVER" in t for t in after)


def test_an_occurrence_map_from_a_different_document_writes_nothing(
    tagged_table_docx, tagged_fragmented_docx
):
    """The realistic way offsets go stale: a plan pointed at the wrong file."""
    foreign = occurrences_for(tagged_table_docx)
    result = tf.apply_tags(tagged_fragmented_docx, foreign, marker_values(foreign))

    assert result["written"] == []
    assert len(result["skipped"]) == len(foreign)
    assert texts_of(result["docx"]) == texts_of(tagged_fragmented_docx)


def test_a_tag_with_no_value_is_left_alone_and_reported(tagged_table_docx):
    occurrences = occurrences_for(tagged_table_docx)
    result = tf.apply_tags(tagged_table_docx, occurrences, {})

    assert result["written"] == []
    assert {s["reason"] for s in result["skipped"]} == {tf.SKIP_NO_VALUE}
    assert len(tg.scan(result["docx"])) == len(occurrences)


def test_an_empty_value_removes_the_tag_rather_than_leaving_it(tagged_fragmented_docx):
    """Absent and empty are different answers.

    A tag_id missing from `values` was never resolved, and the tag stays so a
    caller can refuse to ship. A tag_id resolved to "" was reviewed by a person
    who decided nothing belongs there, and leaving `<School Name>` in a
    client-facing document instead would be worse than writing nothing.
    """
    occurrences = occurrences_for(tagged_fragmented_docx)
    result = tf.apply_tags(
        tagged_fragmented_docx, occurrences, {occurrences[0]["tag_id"]: ""}
    )
    assert len(result["written"]) == 1
    assert result["skipped"] == []
    assert texts_of(result["docx"])[0] == "Welcome to  for the year."
    assert tg.scan(result["docx"]) == []


def test_an_ordinal_past_the_end_of_the_walk_is_skipped(tagged_fragmented_docx):
    occurrences = occurrences_for(tagged_fragmented_docx)
    target = dict(occurrences[0], ordinal=9999)
    result = tf.apply_tags(tagged_fragmented_docx, [target], {target["tag_id"]: "NEVER"})

    assert result["written"] == []
    assert [s["reason"] for s in result["skipped"]] == [tf.SKIP_NO_SUCH_PARAGRAPH]
    assert not any("NEVER" in t for t in texts_of(result["docx"]))


def test_one_stale_occurrence_does_not_stop_the_others(tagged_table_docx):
    occurrences = occurrences_for(tagged_table_docx)
    values = marker_values(occurrences)
    poisoned = [dict(occurrences[0], start=occurrences[0]["start"] + 1)] + occurrences[1:]

    result = tf.apply_tags(tagged_table_docx, poisoned, values)

    assert len(result["written"]) == len(occurrences) - 1
    assert len(result["skipped"]) == 1


# --- every place a tag can live ---------------------------------------------


def test_every_one_of_the_seven_awkward_places_is_written(every_awkward_place_docx):
    """Plan section 2.3a, the writing half: all seven replaced, none astray.

    A nested table and a text box have no positional path, so a path-based
    writer would silently leave two tags in a client-facing document.
    """
    occurrences = occurrences_for(every_awkward_place_docx)
    assert len(occurrences) == 7
    values = marker_values(occurrences)

    result = tf.apply_tags(every_awkward_place_docx, occurrences, values)
    after = texts_of(result["docx"])

    assert len(result["written"]) == 7
    assert result["skipped"] == []
    assert tg.scan(result["docx"]) == []
    assert len(after) == len(texts_of(every_awkward_place_docx)) == 16
    for occurrence in occurrences:
        marker = values[occurrence["tag_id"]]
        assert [i for i, t in enumerate(after) if marker in t] == [occurrence["ordinal"]]


# --- the index, handled exactly as fill.apply handles it --------------------


def _field_toc_docx(tagged: str) -> bytes:
    doc = Document()
    paragraph = doc.add_paragraph()
    run = OxmlElement("w:r")
    instr = OxmlElement("w:instrText")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    run.append(instr)
    paragraph._p.append(run)
    doc.add_paragraph(tagged)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _update_fields(data: bytes) -> str | None:
    settings = Document(io.BytesIO(data)).settings.element
    flag = settings.find(qn("w:updateFields"))
    return None if flag is None else flag.get(qn("w:val"))


def test_a_field_index_is_marked_dirty():
    data = _field_toc_docx("Prepared for <School Name>.")
    occurrences = occurrences_for(data)
    result = tf.apply_tags(data, occurrences, marker_values(occurrences))
    assert _update_fields(result["docx"]) == "true"


def test_a_document_with_no_index_is_not_marked_dirty(tagged_fragmented_docx):
    occurrences = occurrences_for(tagged_fragmented_docx)
    result = tf.apply_tags(tagged_fragmented_docx, occurrences, marker_values(occurrences))
    assert _update_fields(result["docx"]) is None


# --- the owner's real document ----------------------------------------------


golden = pytest.mark.skipif(
    not TAGGED_SAMPLE.exists(), reason="tagged sample not present"
)


@golden
def test_the_owners_document_is_written_end_to_end():
    """Plan section 2.3, reproduced: 25 written, 0 left, none in the wrong place."""
    data = TAGGED_SAMPLE.read_bytes()
    occurrences = occurrences_for(data)
    assert len(occurrences) == 25
    values = marker_values(occurrences)

    result = tf.apply_tags(data, occurrences, values)
    after = texts_of(result["docx"])

    assert len(result["written"]) == 25
    assert result["skipped"] == []
    assert tg.scan(result["docx"]) == []
    assert len(after) == 248
    for occurrence in occurrences:
        marker = values[occurrence["tag_id"]]
        assert [i for i, t in enumerate(after) if marker in t] == [occurrence["ordinal"]]


@golden
def test_the_four_ask_one_unit_cells_get_four_different_answers():
    """The reason the whole feature is addressed per occurrence (D1).

    `replace_token` would have written one answer into all four cells.
    """
    data = TAGGED_SAMPLE.read_bytes()
    occurrences = occurrences_for(data)
    units = [o for o in occurrences if o["raw"] == "<ask:1 Unit>"]
    assert len(units) == 4

    answers = ["2 Units", "1 Unit", "3 Units", "6 Units"]
    result = tf.apply_tags(
        data, units, {o["tag_id"]: a for o, a in zip(units, answers)}
    )
    after = texts_of(result["docx"])
    assert [after[o["ordinal"]] for o in units] == answers
