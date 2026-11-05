# Task 9 report — the conditional static mount (change #8)

## What changed

- **`app/main.py`**
  - Imports: added `from pathlib import Path` and `from fastapi.staticfiles import StaticFiles`.
  - At the end of the file (after the `/health` route): added a conditional mount.
    `_DASHBOARD_DIST = Path(__file__).resolve().parent.parent / "Dashboard" / "dist"`.
    If that directory exists, `app.mount("/dashboard", StaticFiles(directory=_DASHBOARD_DIST, html=True), name="dashboard")`.
    Otherwise, `logger.warning(...)` (reusing the module's existing `logger` — no second logger created) and nothing else. Either way, startup completes without raising.
- **`tests/test_dashboard_mount.py`** (new) — the exact test from the brief, verbatim. Two tests:
  - `test_mount_matches_the_directory_in_both_states` — asserts exactly one `/dashboard` `Mount` when `Dashboard/dist/` exists, and none when it doesn't.
  - `test_api_route_count_is_identical_either_way` — asserts the `APIRoute` count is unaffected by the mount's presence.
- **`Dashboard/READMEs/09_BACKEND_CHANGES.md`** — change #8's row ticked (State ✅, Tests ✅; Guards column left ⬜, matching every other row — it's re-ticked in a later closing pass per that doc's own convention), and a change-log line appended at the bottom of §5.
- **`Dashboard/dist/`** — does not exist at the end of this task (placeholder created for the red run per Step 2, deleted before finishing per Step 4's instruction).

No other files touched. No column, no migration, nothing added under `app/` beyond the edits above.

## Test output — both states

### Bundle present (placeholder `Dashboard/dist/index.html` created)

```
tests/test_dashboard_mount.py::test_mount_matches_the_directory_in_both_states PASSED [ 50%]
tests/test_dashboard_mount.py::test_api_route_count_is_identical_either_way PASSED [100%]
============================== 2 passed in 0.04s ==============================
```

Full suite with bundle present:
```
265 passed in 27.55s
```

### Bundle absent (`Dashboard/dist/` removed)

```
tests/test_dashboard_mount.py::test_mount_matches_the_directory_in_both_states PASSED [ 50%]
tests/test_dashboard_mount.py::test_api_route_count_is_identical_either_way PASSED [100%]
============================== 2 passed in 0.03s ==============================
```

Full suite with bundle absent:
```
265 passed in 28.87s
```

265 = the brief's stated baseline of 263, plus the 2 new tests in `test_dashboard_mount.py`. 0 failed in both states, both full-suite runs.

### Red run (Step 2, before the mount code was added, bundle present)

```
tests/test_dashboard_mount.py::test_mount_matches_the_directory_in_both_states FAILED [ 50%]
tests/test_dashboard_mount.py::test_api_route_count_is_identical_either_way PASSED [100%]
1 failed, 1 passed in 0.57s
```

Failed exactly as the brief predicted: `AssertionError: the bundle exists, so /dashboard must be mounted — assert 0 == 1`.

## Route count confirmation

`python scripts/check_docs_in_sync.py` reports `code: ... 151 routes ...` identically whether `Dashboard/dist/` exists or not — checked directly in both states. The `StaticFiles` `Mount` contributes zero `APIRoute` instances, exactly as `test_api_route_count_is_identical_either_way` asserts and as `09_BACKEND_CHANGES.md` §4 already predicted.

`check_docs_in_sync.py` does FAIL, but on 5 pre-existing drifts (README's stated route-count text, and the §7.1 breakdown/heading/sums for "Organisation administration" and "Operations and money") — all unrelated to this task. Confirmed pre-existing by `git stash`-ing this task's changes and re-running the checker against HEAD `727758e`: identical 5 failures, identical numbers. Resync is Task 10, out of scope here.

`scripts/check_hardcoded_strings.py` still fails with the same 2 pre-existing cosmetic Java findings (`LoginFragment.java:101`, `SplashFragment.java:48`) — unrelated to this backend-only task.

## Concerns

None. The change is exactly the brief's verbatim code, both states are proven green, the route count is verified unaffected, `Dashboard/dist/` is absent at completion, and change #8 was the last item on the closed 8-change list — no ninth change was needed.
