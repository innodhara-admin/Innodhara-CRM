# tests/docx/test_scrub.py
import pytest

from app.services import fill_scrub as fs

BRIEF = "A two to three sentence opening greeting from YuviPep to the client."
ALLOWED = {850000.0, 120000.0, 970000.0, 12.0}


def clean(text, **kw):
    return fs.scrub(text, brief=BRIEF, max_words=90, allowed_amounts=ALLOWED, **kw)


def test_accepts_ordinary_prose():
    assert clean(
        "We are delighted to present this proposal to Greenwood International "
        "School. Following our conversation last week, we have shaped the "
        "programme around your Grade 6 to 8 cohort."
    ) == []


def test_rejects_bold_markers():
    assert fs.REJECTION_MARKDOWN in clean("We are **delighted** to present this.")


def test_rejects_heading_markers():
    assert fs.REJECTION_MARKDOWN in clean("## Introduction\nWe are delighted.")


def test_rejects_bullet_markers():
    assert fs.REJECTION_MARKDOWN in clean("- First point\n- Second point")


def test_rejects_table_pipes():
    assert fs.REJECTION_MARKDOWN in clean("| Item | Price |\n| Lab | 100 |")


def test_rejects_a_model_narrating_its_own_task():
    for opener in (
        "I will now draft the greeting paragraph for the client.",
        "Here is the opening paragraph you requested.",
        "Certainly! Below is the greeting.",
        "As requested, the following paragraph introduces YuviPep.",
    ):
        assert fs.REJECTION_META in clean(opener), opener


def test_rejects_a_fill_in_the_blank():
    assert fs.REJECTION_META in clean("Dear [Name], we are delighted to present this.")


def test_rejects_text_that_merely_restates_its_brief():
    assert fs.REJECTION_BRIEF_ECHO in clean(
        "A two to three sentence opening greeting from YuviPep to the client."
    )


def test_rejects_a_price_not_in_the_locked_commercials():
    assert fs.REJECTION_PRICE in clean(
        "We are pleased to offer this at a total cost of Rs 7,45,000 for the year."
    )


def test_accepts_a_price_that_is_in_the_locked_commercials():
    assert fs.REJECTION_PRICE not in clean(
        "The total investment is Rs 970000 for the full programme."
    )


@pytest.mark.parametrize("written", ["Rs 8,50,000", "Rs 850,000", "Rs 850000"])
def test_accepts_a_locked_price_however_it_is_grouped(written):
    # 8,50,000 is how this organisation writes it. Read as ['8', '50,000'] the
    # scrubber rejects its own correct total, which costs a retry and ends in
    # a blank placeholder.
    assert fs.REJECTION_PRICE not in clean(
        f"The total investment is {written} for the full programme."
    )


@pytest.mark.parametrize("written", ["Rs 7,45,000", "Rs 745,000", "Rs 745000"])
def test_rejects_an_unlocked_price_however_it_is_grouped(written):
    assert fs.REJECTION_PRICE in clean(
        f"We are pleased to offer this at a total cost of {written} for the year."
    )


def test_reads_indian_grouping_as_one_number():
    assert [m.group(0) for m in fs._NUMBER_RE.finditer("Rs 8,50,000")] == ["8,50,000"]
    assert [m.group(0) for m in fs._NUMBER_RE.finditer("Rs 1,23,45,678")] == ["1,23,45,678"]
    assert [m.group(0) for m in fs._NUMBER_RE.finditer("Rs 1,234,567")] == ["1,234,567"]


def test_accepts_a_year_that_is_not_money():
    assert clean("YuviPep has worked with schools since 2019 across India.") == []


def test_rejects_text_over_the_word_budget():
    assert fs.REJECTION_LENGTH in fs.scrub(
        "word " * 200, brief=BRIEF, max_words=90, allowed_amounts=ALLOWED
    )


def test_rejects_empty_text():
    assert fs.REJECTION_BLANK in clean("   ")


def test_reports_every_reason_at_once():
    reasons = clean("I will now write **this**. Cost is Rs 7,45,000.")
    assert fs.REJECTION_META in reasons
    assert fs.REJECTION_MARKDOWN in reasons
    assert fs.REJECTION_PRICE in reasons
