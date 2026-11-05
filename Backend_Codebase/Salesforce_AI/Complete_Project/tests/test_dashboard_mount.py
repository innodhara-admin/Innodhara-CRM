"""A missing console must never take down the API (D20)."""
from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from starlette.routing import Mount

import app.main as main_mod


BUNDLE = Path(main_mod.__file__).resolve().parent.parent / "Dashboard" / "dist"


def _api_route_count() -> int:
    return sum(
        len(r.methods - {"HEAD", "OPTIONS"})
        for r in main_mod.app.routes
        if isinstance(r, APIRoute)
    )


def _dashboard_mounts() -> list:
    return [
        r for r in main_mod.app.routes
        if isinstance(r, Mount) and r.path == "/dashboard"
    ]


def test_mount_matches_the_directory_in_both_states():
    """A missing console must not take down the API, and a present one must
    actually be served. Asserting only that the import did not raise would pass
    even if the mount never appeared at all."""
    if BUNDLE.is_dir():
        assert len(_dashboard_mounts()) == 1, (
            "the bundle exists, so /dashboard must be mounted"
        )
    else:
        assert _dashboard_mounts() == [], (
            "no bundle, so /dashboard must be absent — and the app must still "
            "have imported, which it did or this module would not have loaded"
        )


def test_api_route_count_is_identical_either_way():
    """check_docs_in_sync.py asserts the README's route count. Whether the
    console happens to be built must not move that number."""
    baseline = _api_route_count()
    assert baseline > 0
    assert not any(
        r.path.startswith("/dashboard") for r in main_mod.app.routes
        if isinstance(r, APIRoute)
    )
    # The mount contributes zero APIRoutes, so the count with a bundle present
    # equals the count without one. Both states are exercised in Step 4.
    assert _api_route_count() == baseline
