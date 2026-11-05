### Task 9: The conditional static mount *(change #8, D20)*

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_dashboard_mount.py`

**Interfaces:**
- Produces: `/dashboard` serving `Dashboard/dist/` when present. **Not an `APIRoute`** — route counts are unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_mount.py
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


```

- [ ] **Step 2: Run it and confirm it fails**

**Create the bundle directory first**, or the red run is vacuous:

```bash
mkdir -p Dashboard/dist && printf '<!doctype html><title>placeholder</title>' > Dashboard/dist/index.html
```

Run: `python -m pytest tests/test_dashboard_mount.py -v`
Expected: FAIL on `test_mount_matches_the_directory_in_both_states` — the bundle
now exists but nothing mounts it. This is exactly the assertion the old
`assert app is not None` version could not make, which is why it was replaced.

- [ ] **Step 3: Add the mount**

At the end of `app/main.py`, after the health routes:

```python
# ── The setup console, when it has been built ────────────────────────────────
# The bundle lives outside app/ on purpose: tests/test_genericity.py scans
# app/**/*.py and scripts/check_hardcoded_strings.py scans Android Java, so a
# bundle carrying the product manual's verbatim quotes must stay out of both
# scan roots (05_DECISIONS.md D19).
_DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "Dashboard" / "dist"
if _DASHBOARD_DIST.is_dir():
    app.mount(
        "/dashboard",
        StaticFiles(directory=_DASHBOARD_DIST, html=True),
        name="dashboard",
    )
else:
    logger.warning(
        "Setup console not mounted: no bundle at %s. Run `npm run build` in "
        "Dashboard/ to serve it at /dashboard. The API is unaffected.",
        _DASHBOARD_DIST,
    )
```

Add to the imports at the top of `app/main.py`:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles
```

> `html=True` makes `StaticFiles` serve `index.html` for unknown sub-paths, which
> is what a client-side router needs.

- [ ] **Step 4: Run both states — this is the point of the test**

With the placeholder bundle from Step 2 present:

```bash
python -m pytest tests/test_dashboard_mount.py -v          # 2 passed, mount present
```

Then remove it and run again:

```bash
rm -rf Dashboard/dist
python -m pytest tests/test_dashboard_mount.py -v          # 2 passed, mount absent
```

Both must pass. A version that only passes in one state has not tested the
conditional at all. Leave `Dashboard/dist/` **absent** afterwards — Phase 2 Task
11 creates the real one, and a stale placeholder would mount an empty console.

- [ ] **Step 5: Checkpoint**

`python -m pytest -q` green in both states. Mark change #8 done.

---

