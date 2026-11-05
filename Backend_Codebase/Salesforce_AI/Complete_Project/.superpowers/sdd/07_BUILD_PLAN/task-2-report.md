# Task 2 report — Honest delivery mode (change #2)

## Status: DONE

## What changed and where

`app/api/admin.py` (only file under `app/` touched):

1. **Import** — added `from app.config import get_settings` beside the existing
   `app.api.deps` / `app.core.*` imports.
2. **`_settings_response(s)`** — now opens with three locals:
   ```python
   _cfg = get_settings()
   _email_creds = bool((s.email_integration or {}).get("smtp_username"))
   _whatsapp_creds = bool((s.whatsapp_integration or {}).get("phone_number_id"))
   _calendar_creds = bool((s.calendar_integration or {}).get("calendar_id"))
   ```
   and the returned dict gains four new read-only keys (`email_mode`,
   `whatsapp_mode`, `calendar_mode`, `inbound_email_mode`, all read from
   `_cfg`) plus three new `*_credentials_stored` keys that carry the old
   "credentials exist" meaning forward unchanged. The three existing
   `*_integration_configured` keys now require **both** credentials and the
   matching process-wide mode:
   - `email_integration_configured = _email_creds and _cfg.email_mode == "smtp"`
   - `whatsapp_integration_configured = _whatsapp_creds and _cfg.whatsapp_mode == "cloud_api"`
   - `calendar_integration_configured = _calendar_creds and _cfg.calendar_mode == "google"`

   Copied verbatim from the brief's Step 3, including its comment block.

`tests/test_dashboard_settings_honesty.py` (new file) — the two tests exactly
as given in the brief's Step 1, unmodified.

`Dashboard/READMEs/09_BACKEND_CHANGES.md` — ticked State/Tests for change row
#2, added a dated change-log line, and §3 (the pre-written note explaining
this is the one deliberate meaning-change in the set) was already in place
from planning — left untouched since it already correctly describes what
landed.

No column, no migration added. The env vars (`EMAIL_MODE`, `WHATSAPP_MODE`,
`CALENDAR_MODE`, `INBOUND_EMAIL_MODE`) remain the master switch — `_cfg` is
read fresh from `get_settings()` on every call, nothing was moved into
`OrgSettings`/the DB. `get_org_context` and `require_permission` gates
untouched.

## Test commands and output

Step 2 (confirm failing before implementation) —
`python -m pytest tests/test_dashboard_settings_honesty.py -v`:

```
FAILED tests/test_dashboard_settings_honesty.py::test_settings_expose_the_process_wide_modes
FAILED tests/test_dashboard_settings_honesty.py::test_email_configured_is_false_while_mode_is_dry_run
============================== 2 failed in 1.43s ==============================
```
First test failed on `KeyError: 'email_mode'`; second failed on
`KeyError: 'email_credentials_stored'` (raised before reaching the
`email_integration_configured is False` assertion, since Python evaluates the
dict lookup first — same root cause, matches the brief's predicted failure
mode).

Step 4 (after implementation) —
`python -m pytest tests/test_dashboard_settings_honesty.py -v`:

```
tests/test_dashboard_settings_honesty.py::test_settings_expose_the_process_wide_modes PASSED [ 50%]
tests/test_dashboard_settings_honesty.py::test_email_configured_is_false_while_mode_is_dry_run PASSED [100%]

============================== 2 passed in 0.99s ==============================
```

Step 5 (full suite) — `python -m pytest -q`:

```
........................................................................ [ 32%]
........................................................................ [ 64%]
.....................................................................FF. [ 96%]
F.......                                                                 [100%]
================================== FAILURES ===================================
... (3 failures, all in tests/test_what_is_late.py — same 3 as Task 1's baseline)
3 failed, 221 passed in 16.83s
```

- Baseline going into this task (per Task 1's report / brief context): 219
  passed / 3 failed / 222 collected.
- After this task: 221 passed / 3 failed / 224 collected — passing rose by
  exactly 2 (the two new tests), collected rose by exactly 2, same 3
  pre-existing `test_what_is_late.py` failures (`test_a_task_due_today_is_not_called_overdue`,
  `test_the_due_today_header_is_never_empty`, `test_today_and_overdue_never_overlap`),
  unrelated to this task per the brief's own note (test-side `utcnow()` vs.
  engine-side local `date.today()` boundary mismatch on this UTC+5:30
  machine).

## Step 5 (existing-test check for the meaning change)

Searched the whole repo for every reference to `email_integration_configured`,
`whatsapp_integration_configured`, `calendar_integration_configured`:

```
app\api\admin.py
tests\test_dashboard_settings_honesty.py
Dashboard\READMEs\07_BUILD_PLAN.md
Dashboard\READMEs\09_BACKEND_CHANGES.md
Dashboard\READMEs\05_DECISIONS.md
Dashboard\READMEs\06_DESIGN.md
Dashboard\BRAINSTORM_BRIEF.md
Dashboard\READMEs\04_OPEN_QUESTIONS.md
Dashboard\READMEs\03_API_SURFACE.md
Dashboard\READMEs\02_SEEDING_PREREQUISITES.md
```

No other test file references these keys, and the full-suite run above shows
no test failing on them — **no existing test asserted the old (misleading)
meaning**, so nothing needed updating. This is consistent with these keys
being new-ish/dashboard-facing rather than exercised by the pre-existing
backend suite.

## Where the brief's code was wrong about the real code

Nothing was wrong. `app.config.get_settings()` exists with exactly the four
attributes the brief names (`email_mode` default `"dry_run"`, `whatsapp_mode`
default `"dry_run"`, `calendar_mode` default `"off"`, `inbound_email_mode`
default `"off"`) — confirmed by grepping `app/config.py` before writing the
edit. `_settings_response`'s "before" shape (the three plain `*_configured`
booleans as the last three keys) matched the brief's diff base exactly, so
both edits applied cleanly on the first try. conftest.py pins `EMAIL_MODE`,
`WHATSAPP_MODE`, `CALENDAR_MODE` (not `INBOUND_EMAIL_MODE`, which is left at
its `"off"` default) exactly as the brief's "context" section describes.

## Concerns

None that block this task.

1. Same two pre-existing, out-of-scope items already flagged in Task 1's
   report: `tests/test_what_is_late.py`'s 3 date-boundary failures, and
   `check_docs_in_sync.py` / `check_hardcoded_strings.py` both still red for
   reasons unrelated to and untouched by this task (doc resync is Task 10;
   the 2 Java findings are pre-existing cosmetic literals in Android code
   this task never touched).
2. Ran both guard scripts anyway, out of caution:
   - `python scripts/check_hardcoded_strings.py` — still fails with the same
     2 pre-existing findings (`LoginFragment.java:101`,
     `SplashFragment.java:48`); nothing introduced by this task (no
     Java/Android files touched).
   - `python scripts/check_docs_in_sync.py` — still fails as expected; docs
     resync is explicitly Task 10's job.

## Commit

Single commit (backend + docs only):

- Modified: `app/api/admin.py`
- Added: `tests/test_dashboard_settings_honesty.py`
- Modified: `Dashboard/READMEs/09_BACKEND_CHANGES.md`
