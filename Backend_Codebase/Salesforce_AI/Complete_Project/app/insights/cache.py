"""A per-process cache for the sales head's screens (spec 9.1.5).

Keyed by organisation, route and parameters, kept 60 seconds: a sales head
flicking between tabs does not recompute the same screen. Elapsed time is
measured with the monotonic clock -- this is about seconds passing, not about
which day it is.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

TTL_SECONDS = 60.0
MAX_ENTRIES = 500

_store: dict[tuple, tuple[float, Any]] = {}


async def get_or_compute(key: tuple, ttl: float, compute: Callable[[], Awaitable[dict]]) -> dict:
    hit = _store.get(key)
    if hit is not None and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = await compute()
    if len(_store) >= MAX_ENTRIES:
        oldest = min(_store, key=lambda k: _store[k][0])
        _store.pop(oldest, None)
    _store[key] = (time.monotonic(), value)
    return value


def clear() -> None:
    _store.clear()
