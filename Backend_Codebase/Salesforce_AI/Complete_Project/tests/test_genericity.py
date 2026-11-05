"""FINDING F31 — the guard that stops domain vocabulary coming back.

Working principle 2 is "everything generic — no domain hardcoding anywhere",
and it has now been *claimed* complete three times and been wrong three times:
handoff §6c said so twice, and F31's own first write-up under-counted by two
items. Every one of those misses came from checking the wrong artefact — a
`strings.xml` grep for a Java literal, a "prompt / string / tool name" taxonomy
with no category for branching logic.

So this file does not grep. It parses. `test_no_industry_word_reaches_a_prompt`
walks the AST of every module under `app/`, collects the strings that actually
reach a model, and fails on a domain word in any of them. Docstrings and
comments are deliberately exempt — they were a recorded decision, not an
oversight — and an AST walk is what makes that distinction possible at all.

The second test guards the *logic* tier, which is the one §6c had no category
for and which produced all three of F31's live defects: a wrong number, a wrong
client-visible string, and the wrong currency on screen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

# Words that name an industry or its furniture. A model told it works for one of
# these writes in that industry's vocabulary whatever the client actually is —
# that is F4, observed live: a prompt saying "school" put "the school operates
# offices in Bengaluru" into permanent org memory for an engineering firm.
INDUSTRY_WORDS = {
    "school", "student", "pupil", "principal", "teacher", "syllabus",
    "classroom", "curriculum", "academic", "education", "headmaster",
    "bootcamp", "semester", "tuition",
}

# Kwargs whose value is handed to a model, and the parameter names of the model
# layer itself. `description=` is included because tool descriptions are part of
# the prompt the model sees when choosing a tool (§6c tier 3).
PROMPT_KWARGS = {"system", "prompt", "instruction", "description", "purpose"}

# Kwargs whose ENTIRE subtree is model-facing: a tool's JSON schema is sent to
# the model verbatim, so every `"description"` and every property NAME inside it
# is part of the prompt. Scanning only `description=` kwargs missed
# `email_agent.py`'s 'Principal', which lives in a `parameters={...}` dict — the
# F31 falsification matrix caught that blind spot, which is what it is for.
SCHEMA_KWARGS = {"parameters", "schema", "json_schema", "response_schema"}


def _iter_module_files() -> list[Path]:
    return sorted(p for p in APP.rglob("*.py") if "__pycache__" not in p.parts)


def _string_value(node: ast.AST) -> str | None:
    """The literal text of a string expression, including implicit concatenation
    and f-string literal parts. Returns None for anything not textual."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):  # f-string: only the literal segments
        return "".join(
            v.value for v in node.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_value(node.left), _string_value(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _assignments(tree: ast.AST) -> dict[str, ast.AST]:
    """name → assigned value, for simple `NAME = <expr>` bindings anywhere in
    the module. Prompts and schemas are usually held in a constant
    (`_ROUTER_PROMPT`) or a local (`schema = {...}`) and passed by reference, so
    a guard that only reads inline literals sees almost nothing. The
    falsification matrix caught exactly that: reverting `_ROUTER_PROMPT` and
    nlu's schema left the check green."""
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
    return out


def _collect(node: ast.AST, names: dict[str, ast.AST], depth: int,
             out: list[tuple[int, str]], default_line: int) -> None:
    """Every string under `node`, following a reference ONE level into its
    assigned value.

    Depth matters. One level reaches `system=_ROUTER_PROMPT` and
    `json_schema=schema`, which is the whole point. Following further chases
    *data flow* rather than prompt text — it reported `'syllabus_change'` as
    model-facing because a comprehension filtering on it fed a variable that
    fed a message body, when only the filtered details ever reach the model.
    """
    for sub in ast.walk(node):
        text = _string_value(sub)
        if text:
            out.append((getattr(sub, "lineno", default_line), text))
        elif depth > 0 and isinstance(sub, ast.Name) and sub.id in names:
            _collect(names[sub.id], names, depth - 1, out,
                     getattr(sub, "lineno", default_line))


def _prompt_strings(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string in this module that reaches a model: prompt-ish kwargs,
    `messages=[...]`, and whole tool/JSON schemas — following variable
    references so a prompt held in a constant is not invisible."""
    names = _assignments(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg in PROMPT_KWARGS:
                text = _string_value(kw.value)
                if text:
                    found.append((kw.value.lineno, text))
                elif isinstance(kw.value, ast.Name):
                    _collect(kw.value, names, 1, found, kw.value.lineno)
            elif kw.arg in SCHEMA_KWARGS or kw.arg == "messages":
                # Every string in a tool schema — property NAMES included. A
                # field called `students_delta` invites the model to leave it
                # empty for a client counting racks.
                _collect(kw.value, names, 1, found, node.lineno)
    return found


def test_no_industry_word_reaches_a_prompt() -> None:
    """No string handed to a model may name an industry.

    This is the tier F4, F11 and F31 all landed in. It is deliberately blind to
    docstrings and comments: those still say "school" in places, that was
    decided with the user (§6c, "internal only; churn without benefit"), and
    grepping could not tell the two apart — which is precisely how the
    `document_engine` prompt survived the 2026-07-22 sweep.
    """
    offences: list[str] = []
    for path in _iter_module_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a parse failure is a bug
            pytest.fail(f"{path} does not parse: {exc}")
        for lineno, text in _prompt_strings(tree):
            lowered = text.lower()
            for word in sorted(INDUSTRY_WORDS):
                if word in lowered:
                    offences.append(
                        f"{path.relative_to(APP.parent)}:{lineno} — '{word}' in a "
                        f"model-facing string: {text[:120]!r}"
                    )
    assert not offences, (
        "An industry word reached an LLM prompt. A model told it works for one "
        "industry writes in that industry whatever the client is (F4/F11/F31).\n"
        + "\n".join(offences)
    )


class _FakeProgram:
    id = "prog-1"


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakePricing:
    def __init__(self, items):
        self.items = items


class _FakeDb:
    """Just enough session to run `_estimate_value` against chosen pricing rows.

    Behavioural, not structural: these tests call the real function and check
    the number it returns, so they still fail if the domain word is removed but
    the arithmetic is wrong.
    """

    def __init__(self, pricing):
        self._pricing = pricing

    async def execute(self, _stmt):
        return _FakeResult(self._pricing)


@pytest.mark.asyncio
async def test_value_estimate_prices_a_per_seat_client() -> None:
    """The defect, stated as a number: a per-seat client used to get None."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([{"code": "seat", "unit": "per seat", "unit_price": 1200}]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 40) == 48000


@pytest.mark.asyncio
async def test_value_estimate_prices_the_demo_orgs_own_table() -> None:
    """Reproduces the live data. `seed_demo`'s current pricing table is
    per workshop / per kit / per event — not one line matched the old
    student/flat test, so the seeded project carried `value_estimate = None`
    in the real database while the screen showed nothing."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([
        {"code": "workshop", "unit": "per workshop", "unit_price": 2000},
        {"code": "kit", "unit": "per kit", "unit_price": 500},
        {"code": "showcase", "unit": "per event", "unit_price": 15000},
    ]))
    # 12 of each, priced from the org's own table: (2000+500+15000) × 12.
    assert await _estimate_value(db, "org-1", _FakeProgram(), 12) == 210000


@pytest.mark.asyncio
async def test_value_estimate_still_prices_a_flat_engagement_without_a_count() -> None:
    """Correction B, found while fixing F31 and not in its write-up: the old
    guard returned None before the flat lines were ever summed, so a
    quantity-independent engagement was worth nothing whatever its units."""
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([{"code": "lab", "unit": "flat per lab", "unit_price": 450000}]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), None) == 450000


@pytest.mark.asyncio
async def test_value_estimate_mixes_flat_and_scaling_lines() -> None:
    from app.engines.planner_engine import _estimate_value

    db = _FakeDb(_FakePricing([
        {"code": "rack", "unit": "per rack", "unit_price": 3000},
        {"code": "setup", "unit": "one-time", "unit_price": 25000},
    ]))
    assert await _estimate_value(db, "org-1", _FakeProgram(), 10) == 55000


def test_pricing_units_are_not_domain_gated() -> None:
    """`_estimate_value` must price ANY unit the org uses, not only education's.

    The logic tier — the one the 2026-07-22 sweep had no category for. Every
    live defect in F31 was of this shape: generic data underneath, a domain word
    in the code deciding what to do with it. A per-seat client used to get
    `value_estimate = None`, and the demo org's own table (per workshop / per
    kit / per event) already produced exactly that.
    """
    from app.engines.planner_engine import _is_flat_unit

    for scaling in ("per student", "per seat", "per licence", "per rack",
                    "per site", "per workshop", "per kit", "per event"):
        assert not _is_flat_unit(scaling), f"{scaling!r} must scale by quantity"

    for flat in ("flat", "flat per bootcamp", "flat per lab", "one-time setup"):
        assert _is_flat_unit(flat), f"{flat!r} must be quantity-independent"

    # "flat per bootcamp" contains BOTH cues. Order of testing decides the
    # answer, so this is not a redundant case.
    assert _is_flat_unit("flat per bootcamp")


def test_amendment_line_carries_the_clients_own_unit() -> None:
    """A client-visible amendment must never restate a unit we invented.

    `_handle_scope_change` looked the rate up generically and then wrote
    `"unit": "per student"` into the document the client reads. The lookup being
    generic is not enough — the write is the client-visible half.
    """
    tree = ast.parse((APP / "engines" / "inbound_engine.py").read_text(encoding="utf-8"))
    handler = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_handle_scope_change"
    )
    # Scoped to the CLIENT-VISIBLE surface: the delta_line_items handed to
    # build_amendment. Not the whole function — the back-compat read of the old
    # `students_delta` key and the stub branch's `curriculum_design` default are
    # both deliberate and both live in here. String constants only, so a comment
    # explaining the fix is not mistaken for the defect. (The first two versions
    # of this test failed on exactly those, which is why it is scoped now.)
    delta_arg = next(
        kw.value for n in ast.walk(handler)
        if isinstance(n, ast.Call)
        and getattr(n.func, "attr", None) == "build_amendment"
        for kw in n.keywords if kw.arg == "delta_line_items"
    )
    literals = {
        n.value.lower() for n in ast.walk(delta_arg)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    offenders = {s for s in literals if any(w in s for w in INDUSTRY_WORDS)}
    assert not offenders, (
        f"a client-visible amendment line restates a domain unit: {sorted(offenders)}"
    )
    reads = {
        n.args[0].value for n in ast.walk(delta_arg)
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "get"
        and n.args and isinstance(n.args[0], ast.Constant)
    }
    assert {"unit", "code"} <= reads, (
        "the amendment must carry the base proposal's OWN unit and code, "
        f"but it only reads {sorted(reads)}"
    )


def test_projects_api_sends_the_currency_it_stores() -> None:
    """`value_estimate` without its currency forces the client to assume one.

    The app hardcoded ₹ because there was nothing else to render: the column
    existed on the model but `_project_dict` never serialised it. F31's own
    write-up called this "the cheapest fix since the field exists" — it was
    checking the model rather than the response.
    """
    source = (APP / "api" / "projects.py").read_text(encoding="utf-8")
    serializer = source.split("def _project_dict")[1].split("\n@")[0]
    assert '"value_estimate"' in serializer
    assert '"currency"' in serializer, (
        "an amount must travel with the currency it is denominated in"
    )
