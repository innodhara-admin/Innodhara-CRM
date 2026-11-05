"""`actions[].result` is a preview, and its TYPE depends on payload size.

`agents/base.py::_preview` returns the object when its JSON fits in 800
characters and a truncated **string** when it does not. Anything reading that
field gets a list sometimes and a string other times for the same tool.

This is not hypothetical. It is the whole of **F59**, which sat open and
"undiagnosed" for two weeks with the wrong cause recorded against it:
`verify_live_assistant_context.py` asserted `isinstance(result, list)`, so a
result that grew past the limit read as an *empty* one. Two checks failed, and
the conclusion drawn was that the model had stopped emitting `client="all"`.
Measured against the live model on 2026-08-25, it had not — the args were
`{"owner": "me", "status": "open", "client": "all"}` and the answer named every
client. The item payload had simply grown as F19 and F45 added fields.

`AssistantFragment.findEntity` reads the same field and requires a `Map`, so a
truncated preview also costs an action card its deep link. That is a small,
deliberate cost of a preview being a preview — recorded here so it stays a
decision rather than becoming a surprise a third time.
"""
from __future__ import annotations

import json

from app.ai.agents.base import _preview


def _rows(n: int) -> list[dict]:
    return [
        {
            "id": "a" * 32, "title": "Prepare the annual security review",
            "status": "open", "priority": "P1", "owner": "Asha Agent",
            "client": "Aurora Robotics", "due_date": "2026-09-24T13:43:48.123456",
            "description": None, "blocked": False, "blocked_reason": None,
            "assignment_reason": None,
        }
        for _ in range(n)
    ]


def test_a_small_result_is_recorded_as_itself():
    rows = _rows(2)
    assert len(json.dumps(rows, default=str)) <= 800
    assert _preview(rows) == rows
    assert isinstance(_preview(rows), list)


def test_a_large_result_is_recorded_as_a_truncated_string():
    rows = _rows(3)
    assert len(json.dumps(rows, default=str)) > 800
    recorded = _preview(rows)
    assert isinstance(recorded, str), (
        "the preview no longer changes type on size — every reader that "
        "compensates for it (verify_live_assistant_context._clients_reached, "
        "AssistantFragment.findEntity) can be simplified, and this test deleted"
    )
    assert recorded.endswith("…")


def test_the_limit_is_measured_on_the_json_not_the_value():
    """800 characters of *encoded* JSON, so a 799-character string is already
    over once its quotes are counted. The 800 is quoted in two places that
    compensate for it; if it moves, they should be re-read rather than drift."""
    assert _preview("x" * 798) == "x" * 798          # 798 + 2 quotes = 800
    assert isinstance(_preview("x" * 799), str)      # 801 — truncated
    assert _preview("x" * 799).endswith("…")
    assert _preview({"k": "v" * 2000}).endswith("…")
