"""Who is a blocked task waiting on? (customer ask, 21 Sep 2026)

"Blocked — waiting for inputs from Siva" is typed as free text. This finds
the colleague it names, so the Sync Engine can tell them.

Deliberately conservative, because telling the wrong person is worse than
telling nobody (the blocked person can still chase by hand):

* a full name ("Ravi Teja") beats a first name ("Ravi");
* a first name counts only when exactly one colleague has it;
* first names shorter than three letters are never matched alone;
* whole words only — "Sivakumar Street" is not "Siva";
* two different colleagues named → nobody, since we cannot tell which one
  actually holds the work.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

_MIN_FIRST_NAME = 3


def _words(text: str) -> list[str]:
    # Letters only, so "Siva's" and "Siva," both give "siva".
    return re.findall(r"[^\W\d_]+", text.lower())


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def find_colleague(
    reason: str | None,
    people: Iterable[tuple[str, str]],
    exclude: set[str] | None = None,
) -> str | None:
    """The id of the one colleague `reason` names, or None.

    `people` is (user_id, display name) for the org's active members.
    `exclude` holds ids that can never be the blocker (the blocked person).
    """
    if not reason:
        return None
    exclude = exclude or set()
    said = _words(reason)
    if not said:
        return None

    candidates = [(uid, _words(name)) for uid, name in people if uid not in exclude]
    candidates = [(uid, w) for uid, w in candidates if w]

    full = {uid for uid, w in candidates if len(w) > 1 and _contains(said, w)}
    if len(full) == 1:
        return next(iter(full))
    if len(full) > 1:
        return None

    first_owners: dict[str, set[str]] = {}
    for uid, w in candidates:
        first_owners.setdefault(w[0], set()).add(uid)
    named = [
        first for first in first_owners
        if len(first) >= _MIN_FIRST_NAME and first in said
    ]
    if len(named) != 1:
        return None
    owners = first_owners[named[0]]
    return next(iter(owners)) if len(owners) == 1 else None
