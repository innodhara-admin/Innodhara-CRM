"""FINDING F31 — the app-side half of the genericity guard.

Why this exists at all: handoff §6c twice reported the Android app "clean" on
the strength of `grep -i school app/src/main/res/values/strings.xml`. The grep
was accurate and the conclusion was wrong, because the offending string was a
**Java literal**:

    role.setHint("Role at client (e.g. principal, procurement_head)");

A resources grep cannot see that, and Android Lint's own `HardcodedText` check
cannot either — it inspects layout XML, not Java. That is the exact hole this
script closes.

Two checks:
  1. No user-visible literal is passed to setText/setHint/setTitle/... in Java.
     Resources are where copy belongs (the pattern F14's copy pass established).
  2. No domain word appears in any Java string literal, wherever it sits.

Run:  python scripts/check_hardcoded_strings.py [--app-dir <path>]
Exit code 0 = clean, 1 = findings. Prints every offence with file:line.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_APP_DIR = Path(
    r"C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI\app\src\main"
)

# Same list the backend guard uses (tests/test_genericity.py).
INDUSTRY_WORDS = {
    "school", "student", "pupil", "principal", "teacher", "syllabus",
    "classroom", "curriculum", "academic", "education", "headmaster",
    "semester", "tuition",
}

# Setters whose argument lands on screen.
USER_VISIBLE_SETTERS = (
    "setText", "setHint", "setTitle", "setMessage", "setContentDescription",
    "setSubtitle", "setError", "setLabel",
)

# The literal must BE the argument (or the head of a concatenation that becomes
# it) — `(?![.\w])` rejects `setText("recommend".equals(stage) ? a : b)`, where
# the literal is a wire value being compared, not copy. A fence that blocks
# legitimate code is worse than the gap it closes (§6i), so this is asserted by
# `--self-test` below rather than assumed.
SETTER_RE = re.compile(
    r"\.(" + "|".join(USER_VISIBLE_SETTERS) + r")\(\s*\"((?:[^\"\\]|\\.)*)\"\s*(?![.\w])"
)
STRING_RE = re.compile(r"\"((?:[^\"\\]|\\.){2,})\"")

# Literals that are not copy: empty/blank resets, punctuation and glyph
# separators, format skeletons, and the wire values a ternary switches on.
NOT_COPY_RE = re.compile(r"^[\s\W\d]*$")

# `@SerializedName("school")` and the DTO comments explaining it are the four
# documented wire keys — decided with the user 2026-07-22, never rendered.
WIRE_KEY_CONTEXT = re.compile(r"SerializedName|^\s*\*|^\s*//")

# A currency symbol baked into Java means the code is assuming a country. The
# backend has stored a real per-project/per-proposal `currency` all along —
# `core/util/Money.java` resolves the symbol from it and is the one exemption.
CURRENCY_SYMBOL_RE = re.compile(r"[₹$€£¥₩₪₫₱฿](?!\{)")


def _iter_java(app_dir: Path):
    for path in sorted((app_dir / "java").rglob("*.java")):
        yield path


# (line, should_flag, why) — the detector's own precision suite. Every entry
# marked False is real code from this app that must NOT be reported.
_SELF_TEST_CASES = [
    ('binding.title.setText("Foundation is in place");', True, "plain copy"),
    ('descInput.setHint("Description (optional)");', True, "plain copy"),
    ('banner.setText("Blocked: " + reason);', True,
     "copy at the head of a concatenation — the real TaskDetailFragment case"),
    ('row.setText("• " + title);', False,
     "a punctuation-only prefix is a glyph, not copy"),
    ('b.stageBadge.setText("recommend".equals(s) ? x : y);', False,
     "a wire value being compared, not copy"),
    ('chip.setText("all".equals(value) ? getString(R.string.x) : lbl);', False,
     "same shape, inbox filter"),
    ('binding.messageBody.setText("");', False, "a reset, not copy"),
    ('cell.dayNumber.setText("");', False, "a reset"),
    ('prev.setText("‹");', False, "a glyph separator, as it appears in source"),
    ('t.setText(getString(R.string.stakeholder_role_hint));', False,
     "already a resource"),
    # F37: the wrapped form. The first version of this guard scanned line by
    # line and could never see it, so LoginFragment:93-94 sat unreported while
    # the guard said "none" — which is how F31's "nine literals" was really ten.
    ('binding.loginServerChip.setText(\n        "server: " + shortHost(url));',
     True, "a setter call the formatter wrapped onto the next line"),
]


def _self_test() -> int:
    failures = []
    for line, should_flag, why in _SELF_TEST_CASES:
        flagged = any(
            not NOT_COPY_RE.match(m.group(2)) for m in SETTER_RE.finditer(line)
        )
        if flagged != should_flag:
            failures.append(
                f"  {'missed' if should_flag else 'false positive'}: {line}  ({why})"
            )
    if failures:
        print(f"[FAIL] detector precision — {len(failures)}")
        print("\n".join(failures))
        return 1
    print(f"[PASS] detector precision: {len(_SELF_TEST_CASES)}/{len(_SELF_TEST_CASES)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument("--self-test", action="store_true",
                        help="only check the detector against its own fixtures")
    args = parser.parse_args()

    if _self_test():
        return 1
    if args.self_test:
        return 0

    app_dir: Path = args.app_dir
    if not (app_dir / "java").is_dir():
        print(f"[SKIP] no Java sources under {app_dir} — pass --app-dir")
        return 0

    hardcoded: list[str] = []
    domain: list[str] = []
    currency: list[str] = []

    for path in _iter_java(app_dir):
        rel = path.relative_to(app_dir)
        source = path.read_text(encoding="utf-8")

        # Setter calls are matched against the WHOLE FILE, not line by line.
        # A line-based scan misses any call the formatter wrapped, e.g.
        #     binding.loginServerChip.setText(
        #             "server: " + SplashFragment.shortHost(...));
        # which is real code in LoginFragment:93-94 and went unreported by the
        # first version of this guard (FINDINGS F37). `\s*` in SETTER_RE spans
        # newlines already; only the per-line loop prevented it from matching.
        for match in SETTER_RE.finditer(source):
            text = match.group(2)
            if NOT_COPY_RE.match(text):
                continue  # setText("") and friends reset, they do not speak
            lineno = source.count("\n", 0, match.start()) + 1
            hardcoded.append(f"{rel}:{lineno} — {match.group(1)}(\"{text}\")")

        for lineno, line in enumerate(source.splitlines(), 1):
            if CURRENCY_SYMBOL_RE.search(line) and "Money.java" not in str(rel):
                currency.append(f"{rel}:{lineno} — {line.strip()[:100]}")
            if WIRE_KEY_CONTEXT.search(line):
                continue
            for match in STRING_RE.finditer(line):
                lowered = match.group(1).lower()
                for word in sorted(INDUSTRY_WORDS):
                    if word in lowered:
                        domain.append(
                            f"{rel}:{lineno} — '{word}' in a Java literal: "
                            f"\"{match.group(1)[:90]}\""
                        )

    for title, findings, why in (
        ("User-visible literals hardcoded in Java (belong in strings.xml)",
         hardcoded,
         "A strings.xml grep cannot see these — that is how F31's app half hid."),
        ("Domain words in Java literals", domain,
         "Working principle 2: no domain hardcoding anywhere."),
        ("Currency symbols hardcoded in Java", currency,
         "Render project.currency via core/util/Money — a USD project is not rupees."),
    ):
        if findings:
            print(f"\n[FAIL] {title} — {len(findings)}")
            print(f"       {why}")
            for f in findings:
                print(f"       {f}")
        else:
            print(f"[PASS] {title}: none")

    total = len(hardcoded) + len(domain) + len(currency)
    print(f"\n{'FAIL' if total else 'PASS'} — {total} finding(s)")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
