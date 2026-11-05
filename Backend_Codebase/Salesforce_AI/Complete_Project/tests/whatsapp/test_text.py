"""Task 2: what a WhatsApp template will accept."""
from __future__ import annotations

from app.services.whatsapp_text import clean_value, fold, markdown_to_line, normalise_phone


def test_normalise_phone():
    assert normalise_phone("09310524629") == "919310524629"
    assert normalise_phone("+91 93105 24629") == "919310524629"
    assert normalise_phone("9310524629") == "919310524629"
    assert normalise_phone("919310524629") == "919310524629"
    assert normalise_phone("4479460000", "44") == "444479460000"
    assert normalise_phone("12345") is None
    assert normalise_phone("") is None
    assert normalise_phone(None) is None


def test_clean_value_has_no_line_breaks_tabs_or_long_space_runs():
    assert clean_value("a\nb\tc     d") == "a b c d"
    assert clean_value("a\r\n\r\nb") == "a b"
    assert clean_value("  ") == "-"
    assert clean_value(None, fallback="none") == "none"


def test_fold_keeps_the_body_inside_the_limit():
    values = {"client": "C" * 50, "summary": "s" * 2000}
    out = fold(values, fixed_len=200, shrink_order=("summary",))
    assert out["client"] == "C" * 50
    assert out["summary"].endswith("… more in the app")
    assert 200 + sum(len(v) for v in out.values()) <= 1024


def test_fold_leaves_short_values_alone():
    values = {"a": "x", "b": "y"}
    assert fold(values, fixed_len=100, shrink_order=("a", "b")) == values


def test_markdown_to_line():
    assert markdown_to_line("# Hi\n- [Abc](yuvipep://lead/1) task\n- two") == "Hi: Abc task; two"
    md = "# Good morning, Asha\n\n**Due today:**\n- Call **Acme**\n\n**Overdue:**\n- Send deck"
    assert markdown_to_line(md) == "Good morning, Asha. Due today: Call Acme. Overdue: Send deck"
    assert "\n" not in markdown_to_line("a\n\nb")
