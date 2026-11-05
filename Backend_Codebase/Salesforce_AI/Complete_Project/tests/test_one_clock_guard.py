"""One clock, re-proved every run.

`tests/test_genericity.py` exists because a sweep is a claim made once and a
guard is a claim re-made every run. This is the same idea for time.

Two calls, and only two, may ask what time it is:

* `app.models.base.utcnow()` — an **instant** being recorded. Storage is UTC.
* `app.core.clock` — a **judgement** about which day something falls on, made
  in the organisation's own timezone.

Everything else is banned in `app/`:

* `date.today()` answers in whatever timezone the server process happens to run
  in, which is nobody's setting. Comparing it against a stored instant's
  `.date()` — which answers in UTC — is the F65 defect: a task due 20:00 UTC is
  due 01:30 tomorrow morning in Kolkata, and was reported overdue.
* `datetime.now()` is the same problem without the excuse.
* `datetime.utcnow()` is right about the zone but is the deprecated spelling and
  bypasses the one helper, which is how three prompt builders ended up handing
  the model two different "today"s — `planning.py` and `extraction.py` said UTC
  while `agents/base.py` said server-local.

If a new site genuinely has no organisation to ask, add it to `_ALLOWED` with
the reason. The list is deliberately short and deliberately awkward to grow.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parent.parent / "app"

# Matched on the ATTRIBUTE ALONE, deliberately. Keying on the receiver's name
# missed `from datetime import date as _date` / `_date.today()` in
# `agents/base.py` — the very site F68 added — because the alias did not spell
# "date". An alias is exactly how the next one would hide too.
#
# The discriminator is instead **arity**: every banned spelling takes no
# argument, while `clock.today(tz)`, `clock.now(tz)` and
# `datetime.now(timezone.utc)` all name the zone they mean. `utcnow()` is a bare
# function call rather than an attribute, so it never matches here.
BANNED = {
    "today": "`.today()` — the server's timezone, not the organisation's; use clock.today(tz)",
    "now": "bare `.now()` — the server's timezone; use clock.now(tz) or utcnow()",
    "utcnow": "`.utcnow()` — use models.base.utcnow() for an instant",
}

#: file (relative to app/) -> why this one site cannot ask an organisation.
_ALLOWED: dict[str, str] = {
    # The scheduler's own tick guard: "have I already run today's sweep?" is a
    # question about this process, not about any tenant, and the sweep it gates
    # then does its per-organisation work with each organisation's own zone.
    "jobs/scheduler.py": "process tick guard — belongs to no tenant",
}


def _offences() -> list[str]:
    found: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel == "core/clock.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in BANNED:
                continue
            # Arity is the discriminator: a call that names its zone is fine.
            if node.args or node.keywords:
                continue
            if rel in _ALLOWED:
                continue
            found.append(f"{rel}:{node.lineno} — {BANNED[func.attr]}")
    return found


def test_no_module_asks_the_server_what_day_it_is():
    offences = _offences()
    assert not offences, (
        "these sites read a clock that is not the organisation's:\n  "
        + "\n  ".join(offences)
    )


def test_the_allowlist_still_earns_its_place():
    """An allowlisted file that no longer offends must leave the list, or the
    list quietly becomes a place where new offences hide."""
    for rel, reason in _ALLOWED.items():
        path = APP / rel
        assert path.exists(), f"{rel} is allowlisted but does not exist"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in BANNED
            and not (n.args or n.keywords)
        ]
        assert hits, f"{rel} no longer needs its allowlist entry ({reason})"
        assert len(hits) == 1, (
            f"{rel} is allowlisted for one site ({reason}) but has {len(hits)}; "
            "an allowlist entry covers a file, so a second offence would ride "
            "in free — split it or fix the new one"
        )
