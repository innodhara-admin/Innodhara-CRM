# MOU pipeline — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MOU pipeline on the YuviPep backend that reuses the
simple-flow proposal engine whole — same tags, same dossier, same review —
while keeping a signed contract out of the sales pipeline entirely.

**Architecture:** The document engine (`docx/tags.py`, `docx/text.py`,
`docx/tagfill.py`, `client_dossier.py`) is reused byte-for-byte. A new
`mou_documents` table holds a built MOU; `proposal_templates` gains a
`document_type` column so a programme can carry one current proposal template
and one current MOU template; `proposal_fill_sessions` gains `mou_id` and
`document_type` so its 500-line status machine serves both document types and
only the ~270-line *build* half becomes polymorphic. One agent owns both
documents, so the fast-tier router never has to tell them apart.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2 (async), SQLite, pytest;
React + TypeScript + Vite + Vitest (console); Java + JUnit (Android).

**Spec:** `docs/superpowers/specs/2026-09-09-mou-pipeline-design.md` — read it
alongside this plan. Every task argues from it.

---

## 0 · Amendments — read this before anything below it

**Written by the build, not by the author of this plan. Where this section
contradicts anything further down, THIS SECTION IS RIGHT.** It records what
the build measured that the plan could not, and what the owner decided after
reading it. Task-by-task detail is in the execution ledger at
`.superpowers/sdd/2026-09-09-mou-pipeline-plan/progress.md` (830+ lines,
gitignored, exists only in the working tree).

**Progress: ALL FIFTEEN TASKS ARE COMPLETE AND COMMITTED** — M1-M3, U1-U2, F1-F3,
A1-A3, G1, R1-R2 and E1, in 61 commits from aa49e80. What still needs the
owner's eyes is listed at the end of the ledger. The `- [ ]` checkboxes below are not
maintained; the ledger is.

### A · There are FIFTEEN tasks, not fourteen

The handover message that introduced this plan said fourteen. Count them:
M1-M3, U1-U2, F1-F3, A1-A3, G1, R1-R2, E1 = 15.

### B · U2 has been deferred, deliberately and with the owner's agreement

The owner chose to reach a working end-to-end pipeline before building the
console (their "option B"). The order being executed is therefore
**M1 → M2 → M3 → U1 → F1 → F2 → F3 → A1 → A2 → A3 → G1 → R1 → R2 → U2 → E1**.
U2 is not cancelled; it is last but one. Until it ships, an MOU template is
uploaded by `POST /admin/programs/{id}/proposal-templates/docx` with
`document_type=mou`, which works today.

### C · M1 also shipped the route's `document_type` field, which the plan gave to U1

The column cannot be exercised at all without a way to set it, so M1's own
tests would otherwise have had to reach past the API. M1's Interfaces block
already named `create_docx_template(..., document_type=...)` as its output;
this is the route half of the same thing. **U1 still owns** the `mou_simple`
kind, the flow validation, the ruled-blank count and the console.

### D · F2's approval gate moved to A2

F2 Step 6 asks for "an approval arriving while a mismatch stands is refused
once". `confirm_*_values` is an AGENT tool and the MOU's does not exist until
A2. F2 shipped the service half — relations proposed and stored, mismatches
surfaced on the review line through `arithmetic_warnings`. **A2 must add the
gate and the `arithmetic_ack` flag**, exactly as F2 Step 6 describes them.

### E · The collapse key is `(raw, context)`, NEVER `raw` alone

F1's text says "collapse on `duplicate_of`". Measured against both real
documents, collapsing on the literal alone is a BUG: the tagged proposal's
`<ask:1 Unit>` appears four times with the contexts "Magazine Rack",
"Projector", "Audio and Mic System" and "First Aid Box" — four questions that
merely share a default — and the MOU's `<ask:Yes>` seven times, once per
deliverables row. Keying on the literal gives them all one answer, which is
the `replace_token` bug D1 exists to prevent, arriving at the question layer.
It broke six of the proposal flow's own tests.

### F · `open_questions(limit=None)` MUST stay uncollapsed and ungrouped

`apply_answers` calls it and hands the result straight to `answer_round`.
Collapsing or grouping there shows the model one of five `<ask:75>` and leaves
the rest open for ever — a fill that can never finish. Six is what a PERSON is
shown (D5); the model gets everything (C3, D8). **Anything that changes
`open_questions` must keep this split.**

### G · Section grouping is MOU-ONLY

Applying it to proposals turned their first round from six questions into two
and broke the golden proposal test. D5 chose flat rounds of six deliberately;
the tagged proposal has sixteen tags in one section. Enforced by
`getattr(session, "document_type", "proposal") != "mou"`.

### H · The section heuristic is a STYLE PREFIX, not a substring

Matching any style containing "Head" matches `TableHead1` — the style of every
table header cell in the owner's MOU — so 26 of them became sections and the
fill fragmented into nine rounds. Now `style.startswith("Heading")` or
`startswith("Title")`. Header and footer paragraphs belong to no section and
are labelled "Header"/"Footer".

### I · `tags.py` WAS changed, at the owner's instruction

The plan says the engine is reused unchanged. `_row_label` now skips a first
cell that is only digits: the MOU's deliverables table numbers its rows and
names the deliverable in column 1, so seven `<ask:Yes>` were labelled "2",
"4", "6" and were unanswerable. The owner asked for it to be fixed in the
shared scanner rather than anywhere MOU-specific, because any proposal
template with a numbered column has the same latent defect. Tables whose first
column is the item name are byte-identical; pinned by a test in both
directions.

### J · The MOU's tagging is done, and it took three passes

`scripts/tag_mou_sample.py` is committed; the tagged fixture is not
(`data/samples` is gitignored). **65 occurrences of 33 distinct literals** —
22 semantic, 39 ask, 4 ask_calculate. Shape identical to the original:
240 paragraphs, 3 sections, 8 tables, 11 images.

The design input's §2c is **wrong about YuviPep's own details**. The owner
supplied a second MOU for the same product (SSRVM, already part-tagged), and
diffing the two showed the YuviPep signatory differs between contracts and
that they tag `<org address>` too. §2c is right about the bank details and the
footer contact block, which the owner also leaves untagged.

### K · A tag cannot reach document PROPERTIES, and that is a defect F3 must close

`scan` and `apply_tags` both walk paragraphs; document properties are not
paragraphs. The owner's MOU carried the client in **thirteen** metadata values
across four parts — `dc:title`, `dc:subject`, `dc:creator` (the school's own
signatory, as the document's author), `cp:keywords`, `cp:category`,
`app.xml`'s `TitlesOfParts` and `<Manager>` (which the body renders through a
`DOCPROPERTY` field, so it is on the page), `custom.xml`'s Status and version,
and Word's `CoverPageProperties` part, which carries the school's address, the
student count and the contract value.

The tagging script now neutralises all of them, so the TEMPLATE names nobody.
**Nothing fills them.** `_write_mou` MUST set the built document's core
properties from the filled values, or every MOU carries literal tag text in
its Word properties. **There must be a test for it.**

### L · The round count is not yet known, and three earlier figures were wrong

The design input projected 8-9 rounds; the spec projected 3-4; a simulation
after the heading fix gave 7, and after the `(raw, context)` correction gave
10. **All of those are wrong or unverifiable.** The simulation marks only
exact `(raw, context)` matches as settled, while a real fill sends the model
every outstanding question, so one answer settles every occurrence of the same
fact (D8). **The honest number will be known when G1 runs the fill against a
live model, and not before.** Do not quote a figure until then.

**CLOSED 2026-09-10 BY G1: THE ANSWER IS NINE.** One full fill against the
live model (openrouter, gpt-5.4-nano fast / gemini-2.5-flash strong) over the
tagged Sandur contract, with a person's answers scripted from the golden
suite's own map. Twelve of the sixty-five tags filled without asking; fifty-
three outstanding; **nine rounds**, shown/settled per round
(6,9) (6,11) (5,8) (2,3) (6,6) (4,4) (4,4) (5,5) (3,3).

**The design input's 8-9 was right.** The spec's 3-4 was wrong, and so were
both simulations. D8 is visible in the first four rounds, which settled
thirty-one questions from nineteen shown — one answer closing every occurrence
of the same fact, which is exactly what a simulation cannot model. A round is
not always six: F1's section grouping stops a round at the section boundary,
which is why round 4 showed two questions with twenty-five outstanding.

### M · The mutation harness has two traps, both paid for twice

1. **Stale bytecode.** pytest's assertion-rewrite cache is keyed on
   (mtime, size). `shutil.move` restores the backup's older mtime, and
   consecutive mutations write the same file within one second — so a
   same-length mutation is served the PREVIOUS mutant's bytecode and reads as
   a survivor. It produced a test that passed alone and failed in the suite
   against a literal that was not in the file. **Purge `__pycache__` before
   every run AND `os.utime` after every restore.**
2. **A mutation that cannot import proves nothing.** pytest reports it as
   ERROR, not FAILED; a harness counting only FAILED reads a `NameError` as a
   surviving mutant. Treat a collection error as "this proved nothing".

### N · Marker discipline, three ways it went wrong

Rule 6 says guard every scripted edit with a marker already in the file. That
is necessary and NOT sufficient. The three failures: a sentinel that was prose
and wrapped across two comment lines; a sentinel that already existed
elsewhere in the same file, so the edit **silently skipped itself and reported
success while doing nothing**; and a sentinel that spanned a newline which the
edit's own inserted comment then split. **A sentinel must be a SINGLE LINE, of
CODE not prose, and UNIQUE TO THE EDIT IT GUARDS.** Verify by running twice
and requiring every line to read "already applied" with exit 0.

### O · A live SQLite database must be copied THROUGH SQLITE

`data/salesplatform.db` runs in WAL mode with a multi-megabyte `-wal`. A plain
`cp` of the main file silently drops everything not yet checkpointed —
measured, 17 `proposal_templates` where the live database had 18. Use
`sqlite3.Connection.backup`.

**This affects an existing migration.**
`scripts/migrations/2026-09-08_optional_rate_card.py` takes its safety backup
with `shutil.copyfile`, so
`data/salesplatform.db.before-optional-rate-card.20260908024448` is missing
whatever was in the WAL. **It should not be trusted as a restore point.**
Reported to the owner, not fixed: editing a migration that has already run on
the live database is their decision.

### P · The handover's restart path is wrong

`restart_script/` is one level ABOVE the project directory, at
`Backend_Codebase/restart_script/`. The `sudo systemctl restart
salesforce-app-restart.service` form is correct.

### Q · F3 added a table, and the owner decided it

F3 step 5 asks the correction path to "save a revision". `ProposalRevision`
could not be reused — its foreign key is `proposal_id → proposals.id`, it
carries `line_items` and `total_amount` (the exact commercial columns D-A
removes so nothing can pick an MOU up), and `mou_documents` is wiped BEFORE
`proposal_revisions`, so such a row would be orphaned by a reset. So it meant
a new table, and **nothing in the planned MOU surface reads one**: for
proposals, revisions feed `client_dossier`, `api/proposals.py` and
`approval_engine`; an MOU is out of the pipeline and R1 is only
`GET /mous/{id}` plus the lead's `mous` key.

That is lesson 2 — *ask whether the premise travels* — so it was put to the
owner rather than assumed. **They chose to keep the history.** `MouRevision`
is in `app/models/mou.py`; the File Structure table below still says that file
holds "the `MouDocument` model. Nothing else", and is wrong about that.

`mou_revisions` is in WIPE **ahead of** `mou_documents`, which it has a
foreign key to. The partition pins moved by one on each tree independently:
the working tree to `(4, 2, 8, 47)` over 61 tables, HEAD to `(4, 2, 8, 45)`
over 59.

### R · The properties are filled for MOUs ONLY, and the proposal flow has the same latent defect

`app/services/docx/properties.py` closes amendment K. It is gated on
`document_type == "mou"`: a proposal template's properties were never
neutralised, so there is nothing to fill, and writing the client into them
anyway would change a flow §10 says this project does not change. A test pins
that a proposal build's properties are untouched.

**But the defect is latent in the proposal flow too.** If a proposal template
ever carries a client in its properties, that client ships to the next one.
Reported to the owner, not fixed: the fix changes their proposals.

Two more things the module decided, both recorded because they are judgement
rather than deduction. A literal it cannot fill is **blanked**, never left
standing — a property reading `<School Name>` is the defect, not a smaller
version of it. And `dc:creator` is **cleared rather than set to YuviPep**,
because naming ourselves the author of a document the client signs is a claim
and an empty field makes none.

An MOU's `.docx` and `.pdf` are stored under `CATEGORY_PROPOSALS`.
`storage.py` is one of the 91 dirty paths and the category only names a
folder, so a `CATEGORY_MOUS` would have cost a third §6a edit for a cosmetic
gain. Worth a line in E1 if the owner wants contracts filed separately.

---

## Global Constraints

Copied verbatim from the spec and the session handover. **Every task's
requirements implicitly include this section.**

- **The code is on a VM.** `/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project`,
  `telaverge@172.16.10.55`. Use the `rc.py` / `put.py` helpers, remote commands
  on a `<<'REMOTE'` heredoc **never** as argv, and `MSYS_NO_PATHCONV=1` in
  front of `put.py` with LOCAL paths in Windows form.
- **Baseline:** branch `feature/docx-proposal-templates`, HEAD `0fe0325`.
  **Backend at HEAD in isolation: 636 passed, 53 skipped.** Working tree: 820
  passed / 1 failed. tests/docx 417. Console 707 / 20 files, `tsc --noEmit`
  exit 0. Android JVM 61.
- **The working tree is deliberately dirty at 91 paths and must read 91 before
  and after every commit.** Never `git add -A`. Stage only the paths the task
  names, and check the count after every commit.
- **The one permitted failure** is
  `tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first`
  — pre-existing, unrelated in-flight work, **must not be fixed**. Up to four
  more are time-of-day sensitive (`tests/test_what_is_late.py`,
  `tests/test_demos_followups.py::test_followup_complete_schedules_next`).
  Confirm they are the only ones and move on.
- **`docs/` is untracked but not ignored** and collapses to a single `?? docs/`
  line. **Never `git add` anything under `docs/`** — it would expand the line
  and take the dirty count from 91 to 99. The spec, this plan and the ledger
  all live there uncommitted.
- **Handover §6a** applies to any file already dirty: the committed content
  must be HEAD + your edit, not the working tree. Write the edit as an
  idempotent script, run it on the working tree **and** on a `git archive HEAD`
  export, then stage the export's blob with `git hash-object -w` +
  `git update-index --cacheinfo`. **Check before you edit anything** — dirty
  files include `app/ai/agents/base.py`, `app/core/constants.py`,
  `app/jobs/pipelines.py`, `app/jobs/scheduler.py`, `app/models/__init__.py`,
  `BACKEND_README.md`, `tests/test_reset_taxonomy.py`,
  `app/core/reset_taxonomy.py`.
- **Guard every scripted edit with a marker already in the file, make it
  idempotent, and make the sentinel a string that survives wrapping.** A
  sentinel spanning a line break silently fails to match.
- **Never upload a local copy of a file you patched on the VM.** Patch on the
  VM only, or pull the VM's copy down first and compare sha256.
- **Line endings:** normalise to LF, patch, restore the original convention.
  `Dashboard/READMEs/09_BACKEND_CHANGES.md` and `Dashboard/src/api/openapi.json`
  are CRLF and bite.
- **Numbers in this plan are measurements.** If a run disagrees, **stop and
  investigate, then tell the owner** — do not edit the pin to make a test green.
- **Never kill the backend PID directly.** Restart with
  `printf '%s\n' 'tela@123' | sudo -S -p '' systemctl restart salesforce-app-restart.service`
  or `restart_script/restart_backend.sh restart`.
- **`Dashboard/dist` is build output and is NEVER committed.** Build the
  console from the WORKING TREE, not a HEAD export (the tree carries
  `session/baseUrl.ts`).
- **Every commit message ends with:**
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01AgT7mFP31rNJVt8vXihu99
  ```
- **Per task:** write the tests, **watch them fail for the right reason**,
  implement, run the task's tests → `tests/docx` → the full backend,
  **mutation-check the behaviour the task is about**, review your own code with
  the tests already green, commit only the named paths, verify the commit in a
  `git archive HEAD` export, append to
  `.superpowers/sdd/2026-09-09-mou-pipeline-plan/progress.md`, then tell the
  owner.
- **Count literals, never read them.** `tests/docx/test_text.raw_count` is the
  ground truth. 47 of the MOU's 240 paragraphs are outside the body.

---

## File Structure

**New backend files**

| File | Responsibility |
|---|---|
| `app/models/mou.py` | The `MouDocument` model. Nothing else. |
| `app/services/mou_arithmetic.py` | Pure. Parse an amount, check a relation. No model, no I/O, no database. |
| `app/api/mous.py` | The MOU read routes. |
| `app/ai/agents/fill_tools.py` | The fill-conversation tool handlers, shared by both document types. |
| `scripts/migrations/2026-09-09_template_document_type.py` | M1's migration. |
| `scripts/migrations/2026-09-09_fill_session_mou.py` | M3's migration. |
| `scripts/tag_mou_sample.py` | Tags the owner's MOU. Idempotent, dry-run by default. |

**New test files:** `tests/docx/test_mou_models.py`,
`tests/docx/test_mou_arithmetic.py`, `tests/docx/test_mou_rounds.py`,
`tests/docx/test_mou_fill.py`, `tests/docx/test_mou_agent.py`,
`tests/docx/test_tool_choice.py`, `tests/docx/test_mou_golden.py`,
`tests/docx/test_mou_api.py`.

**Modified backend files:** `app/models/program.py` (the column),
`app/models/__init__.py` (export, **dirty — §6a**),
`app/core/reset_taxonomy.py` (**dirty — §6a**),
`tests/test_reset_taxonomy.py` (**dirty — §6a**),
`app/services/docx_template_service.py`, `app/api/admin.py`,
`app/services/proposal_service.py`, `app/services/proposal_fill_service.py`,
`app/ai/docx_tagfill.py`, `app/ai/agents/proposal_agent.py`,
`app/ai/orchestrator.py`, `app/main.py` (route registration).

**Console:** `Dashboard/src/.../ProposalTemplates.tsx`, `DocxUpload.tsx`,
`flow.ts`, `flow.test.ts`, plus regenerated `openapi.json`, `generated.ts`,
`vocabularies.generated.ts`.

**Android** (`C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI`, **not
a git repository — back up every file before editing**): `MouDto.java`,
`MouLines.java` + test, a client-screen section, `contract/mou_detail.json`,
`ContractTest.java`.

---

# Phase M — the data model

### Task M1: `document_type` on proposal templates (D-B)

The most delicate task in the plan. Getting it wrong retires or promotes the
wrong template silently.

**Files:**
- Modify: `app/models/program.py` (the `ProposalTemplate` class, ~line 43)
- Modify: `app/services/docx_template_service.py:178-192` (the retire loop)
- Modify: `app/api/admin.py:880-892` (`_promote_predecessor`), `:1037-1044`
  (the proposal-template delete call site)
- Modify: `app/services/proposal_service.py:90-105` (`_current_template`)
- Modify: `app/services/proposal_fill_service.py:823-841` (`_current`)
- Create: `scripts/migrations/2026-09-09_template_document_type.py`
- Test: `tests/docx/test_mou_models.py` (new),
  `tests/docx/test_template_service.py` (existing, add cases)

**Interfaces:**
- Produces: `ProposalTemplate.document_type: str` with values `"proposal"` and
  `"mou"`; module constant `DOCUMENT_TYPES = ("proposal", "mou")` in
  `app/services/docx_template_service.py`.
  `docx_template_service.create_docx_template(..., document_type: str = "proposal")`.
  `proposal_fill_service._current(db, ctx, program_id, template_id, *, document_type: str = "proposal")`.

- [ ] **Step 1: Reproduce the failure before fixing it**

Write this test first. It documents the defect the column exists to fix, and it
must **fail** on today's code.

```python
# tests/docx/test_mou_models.py
async def test_uploading_an_mou_does_not_retire_the_proposal_template(
    client, org, program, tagged_docx
):
    """D-B. Today the retire loop clears every is_current row for a
    programme, so uploading an MOU would leave the programme with no current
    proposal template and `create a proposal for IBC` would answer
    "No proposal template for this program"."""
    proposal_tpl = await upload(client, program, tagged_docx,
                                name="ibc_proposal", document_type="proposal")
    await upload(client, program, tagged_docx,
                 name="ibc_mou", document_type="mou")

    still_current = await get_template(client, proposal_tpl["template_id"])
    assert still_current["is_current"] is True, (
        "uploading an MOU retired the proposal template"
    )
```

- [ ] **Step 2: Run it and watch it fail for the right reason**

Run:
```bash
cd "$SCRATCH" && python rc.py <<'REMOTE'
.venv/bin/python -m pytest tests/docx/test_mou_models.py -q 2>&1 | tail -20
REMOTE
```
Expected: FAIL. First on `document_type` being an unexpected form field, then —
once the column exists — on `is_current` being `False`. **Both failures are the
point.** If it passes at any stage before Step 5, stop: the test is not
exercising what it claims.

- [ ] **Step 3: Add the column**

`app/models/program.py`, inside `ProposalTemplate`, immediately after
`is_current`:

```python
    # D-B. A programme carries ONE current proposal template AND one current
    # MOU template, so `is_current` is current-per-document-type. `kind`
    # cannot serve: markdown, docx and docx_simple are all proposals.
    document_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="proposal",
        server_default="proposal",
    )
```

- [ ] **Step 4: Write the migration**

`scripts/migrations/2026-09-09_template_document_type.py`, modelled on
`2026-09-08_optional_rate_card.py`. SQLite **does** support adding a column
with a constant default — this is not the table rebuild D37 needed.

```python
"""Add proposal_templates.document_type (D-B).

Idempotent: reads the schema and does nothing if the column exists.
Backs up the database first and refuses to report success if the row count
moved or a foreign key broke.
"""
import shutil
import sqlite3
import sys
from datetime import datetime

DB = sys.argv[1] if len(sys.argv) > 1 else "data/salesplatform.db"


def has_column(conn, table, column):
    return any(r[1] == column for r in
               conn.execute(f"PRAGMA table_info({table})"))


def main():
    conn = sqlite3.connect(DB)
    if has_column(conn, "proposal_templates", "document_type"):
        print("document_type already present - nothing to do")
        return 0

    before = conn.execute("select count(*) from proposal_templates").fetchone()[0]
    backup = f"{DB}.before-document-type.{datetime.now():%Y%m%d%H%M%S}"
    shutil.copyfile(DB, backup)
    print(f"backed up to {backup}")

    conn.execute(
        "ALTER TABLE proposal_templates "
        "ADD COLUMN document_type VARCHAR(20) NOT NULL DEFAULT 'proposal'"
    )
    conn.commit()

    after = conn.execute("select count(*) from proposal_templates").fetchone()[0]
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    kinds = dict(conn.execute(
        "select document_type, count(*) from proposal_templates "
        "group by document_type"))
    if before != after or violations:
        print(f"REFUSING: rows {before} -> {after}, fk {violations}")
        return 1
    print(f"ok: {before} -> {after} rows, document_type = {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Move the four call sites together**

All four, in one edit. Missing one is the failure mode.

`app/services/docx_template_service.py` — the retire loop:

```python
    if make_current:
        others = (
            await db.execute(
                select(ProposalTemplate).where(
                    ProposalTemplate.org_id == ctx.org_id,
                    ProposalTemplate.program_id == program_id,
                    # D-B: only retire the current template of THIS document
                    # type. Without this, uploading an MOU leaves the
                    # programme with no current proposal template.
                    ProposalTemplate.document_type == document_type,
                    ProposalTemplate.is_current.is_(True),
                )
            )
        ).scalars().all()
        for other in others:
            other.is_current = False
```

and pass `document_type=document_type` to the `ProposalTemplate(...)`
constructor.

`app/services/proposal_service.py:_current_template` — add, before the
`template_id` branch:

```python
    # D-B: a proposal is never built from an MOU template.
    q = q.where(ProposalTemplate.document_type == "proposal")
```

`app/services/proposal_fill_service.py:_current` — add the keyword argument and
the same filter:

```python
async def _current(
    db: AsyncSession, ctx: OrgContext, program_id: str,
    template_id: str | None, *, document_type: str = "proposal",
) -> ProposalTemplate | None:
    query = select(ProposalTemplate).where(
        ProposalTemplate.org_id == ctx.org_id,
        ProposalTemplate.program_id == program_id,
        ProposalTemplate.document_type == document_type,
    )
```

`app/api/admin.py:_promote_predecessor` — it already takes `**scope`, so only
the **call site** changes:

```python
    if was_current:
        await _promote_predecessor(
            db, ProposalTemplate, org_id=ctx.org_id, program_id=program_id,
            # D-B: deleting the current MOU must not promote a proposal
            # template into its place, or vice versa.
            document_type=row.document_type,
        )
```

- [ ] **Step 6: Run the test and watch it pass**

```bash
cd "$SCRATCH" && python rc.py <<'REMOTE'
.venv/bin/python -m pytest tests/docx/test_mou_models.py tests/docx/test_template_service.py -q 2>&1 | tail -10
REMOTE
```
Expected: PASS.

- [ ] **Step 7: Mutation-check**

Change each of the four call sites back, one at a time, and confirm a test
fails for each:

| Mutation | Must fail |
|---|---|
| Retire loop drops the `document_type` filter | `test_uploading_an_mou_does_not_retire_the_proposal_template` |
| `_current_template` drops its filter | a new test: creating a proposal picks the proposal template even when an MOU is also current |
| `_current` drops its filter | a new test: an MOU fill opens on the MOU template |
| `_promote_predecessor` call drops `document_type` | a new test: deleting the current MOU promotes the previous **MOU**, not a proposal |

Write the three missing tests **before** running the mutations. Restore and
re-verify green.

- [ ] **Step 8: Run the migration on a copy, then for real**

```bash
cd "$SCRATCH" && python rc.py <<'REMOTE'
cp data/salesplatform.db /tmp/mig_test.db
.venv/bin/python scripts/migrations/2026-09-09_template_document_type.py /tmp/mig_test.db
echo "--- second run must be a no-op ---"
.venv/bin/python scripts/migrations/2026-09-09_template_document_type.py /tmp/mig_test.db
echo "--- for real ---"
.venv/bin/python scripts/migrations/2026-09-09_template_document_type.py
REMOTE
```
Expected: `ok: 18 -> 18 rows, document_type = {'proposal': 18}`, then
`already present - nothing to do`.

- [ ] **Step 9: Full suites**

```bash
cd "$SCRATCH" && python rc.py <<'REMOTE'
.venv/bin/python -m pytest tests/docx -q 2>&1 | tail -3
.venv/bin/python -m pytest tests -q 2>&1 | tail -5
REMOTE
```
Expected: tests/docx up from 417; backend 820+N passed / 1 failed (the
pre-existing one).

- [ ] **Step 10: Commit**

```bash
cd "$SCRATCH" && python rc.py <<'REMOTE'
git status --porcelain | wc -l   # must be 91
git add app/models/program.py app/services/docx_template_service.py \
        app/api/admin.py app/services/proposal_service.py \
        app/services/proposal_fill_service.py \
        scripts/migrations/2026-09-09_template_document_type.py \
        tests/docx/test_mou_models.py tests/docx/test_template_service.py
git commit -F - <<'MSG'
feat(mou): current-per-document-type templates (D-B)

A programme now carries one current proposal template and one current MOU
template. Reproduced first: the retire loop cleared every is_current row for
the programme, so uploading an MOU left IBC with no current proposal template
and proposal creation answered "No proposal template for this program."

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01AgT7mFP31rNJVt8vXihu99
MSG
git status --porcelain | wc -l   # must be 91 again
REMOTE
```

---

### Task M2: the `mou_documents` table (D-A)

**Files:**
- Create: `app/models/mou.py`
- Modify: `app/models/__init__.py` (**dirty — handover §6a applies**)
- Modify: `app/core/reset_taxonomy.py` (**dirty — §6a**)
- Modify: `tests/test_reset_taxonomy.py` (**dirty — §6a**)
- Modify: `tests/test_dashboard_reset.py` (the orphan-edge pin)
- Test: `tests/docx/test_mou_models.py` (extend)

**Interfaces:**
- Produces: `app.models.mou.MouDocument` and `MouStatus` (`DRAFT = "draft"`,
  `SENT = "sent"`), exported from `app.models`.

- [ ] **Step 1: Write the model**

```python
# app/models/mou.py
"""A memorandum of understanding, built from a tagged Word template.

**Deliberately not a Proposal.** A Proposal row is read by five things that
describe a DEAL: the lead screen's proposal list, knowledge_engine's client
history, document_engine.accepted_total, approval_engine's routing, and
inbound_engine's rule that a SENT proposal on a project means the deal is
agreed. An MOU is signed AFTER a proposal is accepted, so it would arrive on
an already-closed deal and flip its state (D-A).

**No total_amount, no line_items, no pricing_table_id, no project_id.** Not
merely unused - absent, so no future aggregate can pick an MOU up by
accident. An MOU's prices live in its own document, filled by tags (D37).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class MouStatus:
    DRAFT = "draft"
    SENT = "sent"


class MouDocument(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "mou_documents"
    __table_args__ = (Index("ix_mous_org_lead", "org_id", "lead_id"),)

    lead_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("leads.id"), index=True)
    program_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("programs.id"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=MouStatus.DRAFT, nullable=False)

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("proposal_templates.id"))
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # The projected text of the document that was built. The .docx is the
    # artefact; this is the record of it.
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    # Provenance, read by the Android card. SIX KEYS FROM THE COMPLEX FLOW -
    # key, kind, source, text, brief, anchor - plus computed_by and citation.
    # Renaming one turns a working card into a blank one (J2).
    filled_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    docx_path: Mapped[str | None] = mapped_column(String(500))
    pdf_path: Mapped[str | None] = mapped_column(String(500))

    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_message_id: Mapped[str | None] = mapped_column(String(32))
```

- [ ] **Step 2: Export it, and place it in the reset taxonomy**

`app/models/__init__.py` and `app/core/reset_taxonomy.py` are **both dirty** —
write this as an idempotent, marker-guarded script and run it on the working
tree **and** on a `git archive HEAD` export (§6a).

In `reset_taxonomy.py`, `mou_documents` goes in **WIPE**, between
`proposal_fill_sessions` and `proposal_revisions`:

```python
    # child-before-parent and proposal_fill_sessions.proposal_id is a
    # ForeignKey to proposals, and .mou_id one to mou_documents.
    "proposal_fill_sessions",
    # An MOU is a client's contract - transactional work, not catalogue.
    # AFTER the fill sessions that point at it, BEFORE proposals.
    "mou_documents",
    "proposal_revisions", "proposals",
```

**The sentinel must not span a line break.** Guard on the single-line string
`"proposal_fill_sessions",` and insert after it.

- [ ] **Step 3: Update the two pins BY INCREMENT, never by literal**

`tests/test_reset_taxonomy.py` asserts different numbers at HEAD and in the
tree — **measured: HEAD `(4, 2, 8, 43)` over 57 tables; the working tree
`(4, 2, 8, 45)` over 59.** Writing either literally produces a commit that is
broken in the other tree (A4's defect).

The edit script must read the existing number and add one:

```python
import re

def bump(text):
    def wipe(m):
        return f"{m.group(1)}{int(m.group(2)) + 1})"
    def tables(m):
        return f"{m.group(1)}{int(m.group(2)) + 1}"
    if "mou_documents" in text:          # marker: already applied
        return text, False
    text = re.sub(r"(== \(4, 2, 8, )(\d+)\)", wipe, text)
    text = re.sub(r"(len\(Base\.metadata\.tables\) == )(\d+)", tables, text)
    return text, True
```

**Guard the numeric bump with a marker, not just the string edits** — A4's bug
was a script that guarded its replacements but not its increments, and running
it twice bumped 44 → 45 → 46.

Expected after: HEAD export asserts `(4, 2, 8, 44)` over 58; the working tree
asserts `(4, 2, 8, 46)` over 60. **Measure both. Do not assume.**

- [ ] **Step 4: Update the orphan-edge pin with its reason**

`tests/test_dashboard_reset.py::test_catalogue_orphan_edges_match_the_schema`
will go red. `mou_documents` adds **two** edges: `program_id` → `programs` and
`template_id` → `proposal_templates`. The pinned set goes from nine to eleven.

This is not editing a pin to make a test green — the test's own docstring says
a schema change adding such an edge must fail it rather than silently change
behaviour. Record the decision beside the existing ones: *a built MOU names the
template it was built from, so a catalogue-only reset must refuse rather than
leave it pointing at a template that is gone.*

- [ ] **Step 5: Prove `create_all` builds it, and the reset order holds**

```python
async def test_create_all_builds_the_mou_table(fresh_db):
    tables = await table_names(fresh_db)
    assert "mou_documents" in tables


def test_mou_documents_is_wiped_before_the_proposals_it_may_reference():
    """FK ordering is a constraint, not a preference: nothing in this schema
    declares ondelete=, so child-before-parent is the only thing keeping a
    reset from failing on a constraint."""
    assert WIPE.index("proposal_fill_sessions") < WIPE.index("mou_documents")
    assert WIPE.index("mou_documents") < WIPE.index("proposals")
```

- [ ] **Step 6: Run the suites**

```bash
cd "$SCRATCH" && python rc.py <<'REMOTE'
.venv/bin/python -m pytest tests/test_reset_taxonomy.py tests/test_dashboard_reset.py tests/docx/test_mou_models.py -q 2>&1 | tail -6
.venv/bin/python -m pytest tests -q 2>&1 | tail -4
REMOTE
```

- [ ] **Step 7: Prove the commit is self-consistent IN THE EXPORT**

This is the step A4 proved necessary. Run the partition, model and reset tests
**inside** the `git archive HEAD` export, and read the staged blob to confirm
it says 44/58 while the working tree still says 46/60.

- [ ] **Step 8: Commit** — paths: `app/models/mou.py`,
  `app/models/__init__.py`, `app/core/reset_taxonomy.py`,
  `tests/test_reset_taxonomy.py`, `tests/test_dashboard_reset.py`,
  `tests/docx/test_mou_models.py`. Dirty 91 before and after. Stage the
  export-derived blobs for the three dirty files via `git hash-object -w` +
  `git update-index --cacheinfo`.

---

### Task M3: the fill session learns about MOUs (D-C)

**Files:**
- Modify: `app/models/proposal_fill.py`
- Modify: `app/services/proposal_fill_service.py` (`find_open`, `find_for_chat`,
  `find_correctable`, `open_session`)
- Create: `scripts/migrations/2026-09-09_fill_session_mou.py`
- Test: `tests/docx/test_mou_fill.py` (new)

**Interfaces:**
- Produces: `ProposalFillSession.mou_id: str | None`,
  `ProposalFillSession.document_type: str`.
  `proposal_fill_service.open_session(..., document_type: str = "proposal")`,
  and `find_open` / `find_for_chat` / `find_correctable` all gaining
  `*, document_type: str = "proposal"`.

- [ ] **Step 1: Write the failing test — the discriminator earns its place**

```python
async def test_an_mou_fill_and_a_proposal_fill_do_not_collide(db, ctx, lead, program):
    """Same lead, same programme, same chat. Without document_type these two
    are indistinguishable to find_for_chat and a reply about one lands on the
    other."""
    proposal_fill = await fs.open_session(
        db, ctx, lead_id=lead.id, program_id=program.id,
        chat_session_id="chat-1", document_type="proposal")
    mou_fill = await fs.open_session(
        db, ctx, lead_id=lead.id, program_id=program.id,
        chat_session_id="chat-1", document_type="mou")

    found = await fs.find_for_chat(db, ctx, chat_session_id="chat-1",
                                   document_type="mou")
    assert found.id == mou_fill.id
    assert found.id != proposal_fill.id
```

- [ ] **Step 2: Run it, watch it fail** on the unexpected keyword argument.

- [ ] **Step 3: Add the columns**

```python
    # Set once the document is produced; null for every fill in progress.
    proposal_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("proposals.id"))
    # D-C. The MOU equivalent. Exactly one of these is ever set.
    mou_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("mou_documents.id"))
    # D-C. The discriminator. Without it an MOU fill and a proposal fill for
    # the same lead, programme and chat are indistinguishable to find_for_chat.
    document_type: Mapped[str] = mapped_column(
        String(20), default="proposal", server_default="proposal",
        nullable=False)
```

- [ ] **Step 4: Thread `document_type` through every lookup**

`find_open`, `find_for_chat` and `find_correctable` each gain
`ProposalFillSession.document_type == document_type` in their `where`.
`find_correctable` additionally keys on `mou_id` rather than `proposal_id`
when the type is `"mou"`.

- [ ] **Step 5: Write the migration** — same shape as M1's, two
  `ALTER TABLE ... ADD COLUMN` statements
  (`mou_id VARCHAR(32)` nullable, `document_type VARCHAR(20) NOT NULL DEFAULT
  'proposal'`), idempotent per column, backup first, 4 live rows.

- [ ] **Step 6: Run it and watch the test pass.**

- [ ] **Step 7: Mutation-check**

| Mutation | Must fail |
|---|---|
| `find_for_chat` drops the `document_type` filter | `test_an_mou_fill_and_a_proposal_fill_do_not_collide` |
| `find_open` drops it | a second test, same shape, over `find_open` |
| `document_type` defaults to `"mou"` | every existing proposal-fill test |
| `find_correctable` keys on `proposal_id` for an MOU | a correction test from F3 |

- [ ] **Step 8: Migrate the live database** (copy first, then real, then a
  second run to prove the no-op).

- [ ] **Step 9: Full suites, then commit** — paths: `app/models/proposal_fill.py`,
  `app/services/proposal_fill_service.py`,
  `scripts/migrations/2026-09-09_fill_session_mou.py`,
  `tests/docx/test_mou_fill.py`. Dirty 91 before and after.

---

# Phase U — the upload

### Task U1: `document_type` on the upload route, and the ruled-blank warning (D-F)

**Files:**
- Modify: `app/api/admin.py:491-510` (the route)
- Modify: `app/services/docx_template_service.py` (`create_docx_template`,
  `plan_summary`)
- Test: `tests/docx/test_api.py`, `tests/docx/test_template_service.py`

**Interfaces:**
- Consumes: M1's `DOCUMENT_TYPES` and `ProposalTemplate.document_type`.
- Produces: form field `document_type: str = Form("proposal")`;
  `kind="mou_simple"` for an MOU; `plan_json = {"flow": "simple",
  "document_type": "mou", "version": 1, "tags": [...]}`;
  `plan_summary` gains `"ruled_blanks": int`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_mou_upload_is_stored_as_mou_simple(client, program, tagged_mou):
    body = await upload(client, program, tagged_mou, document_type="mou")
    assert body["kind"] == "mou_simple"
    assert body["document_type"] == "mou"


async def test_the_route_defaults_to_proposal(client, program, tagged_docx):
    """Uploaded with NO document_type field at all - the route's own default,
    not a value a test happened to pass."""
    body = await upload(client, program, tagged_docx, document_type=None)
    assert body["document_type"] == "proposal"


def test_ruled_blanks_are_counted_and_reported(mou_bytes):
    """D-F. `Date: ___________` is not a tag and TAG_RE cannot see it. The
    owner's MOU carries two, at walk ordinals 85 and 87."""
    assert plan_summary(simple_plan(mou_bytes))["ruled_blanks"] == 2


def test_a_ruled_blank_does_not_refuse_the_upload(mou_bytes):
    """A genuinely hand-signed blank is legitimate. Warn, do not refuse."""
    summary = plan_summary(simple_plan(mou_bytes))
    assert summary["ruled_blanks"] > 0 and summary["tags"] > 0
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement the ruled-blank count**

In `docx_template_service`, a small pure helper. It walks the same
`dt.walk_paragraphs` the scanner uses, so headers and footers are included.

```python
_RULED_BLANK = re.compile(r"_{3,}")


def count_ruled_blanks(docx_bytes: bytes) -> int:
    """Runs of three or more underscores - `Date: ___________`.

    TAG_RE needs <...>, so a ruled blank is silently not a tag and reaches the
    client as underscores (D-F). Counted over the full walk, because 47 of the
    owner's MOU's 240 paragraphs are in headers and footers - and both of its
    ruled blanks sit in the signature table.
    """
    from docx import Document
    doc = Document(io.BytesIO(docx_bytes))
    return sum(len(_RULED_BLANK.findall(dt.node_text(p)))
               for p in dt.walk_paragraphs(doc))
```

- [ ] **Step 4: Branch `create_docx_template` on `document_type`**

```python
    if document_type not in DOCUMENT_TYPES:
        raise ValidationFailedError(
            f"Unknown document type '{document_type}'. "
            f"Choose one of: {', '.join(DOCUMENT_TYPES)}."
        )
    # An MOU is always the simple flow: there is no console editor for a
    # contract and every value in it is a tag.
    if document_type == "mou" and flow != "simple":
        raise ValidationFailedError(
            "An MOU template is filled by the assistant. Upload it as the "
            "simple flow."
        )
```

and `kind = "mou_simple" if document_type == "mou" else "docx_simple"`, with
`plan_json` carrying `"document_type"`.

**Decide before storing anything.** Both validations run before the template
row, the doc row and `storage.save_bytes`, exactly as B1's do — pinned by its
own test.

- [ ] **Step 5: Run the tests, watch them pass.**

- [ ] **Step 6: Mutation-check**

| Mutation | Must fail |
|---|---|
| Route defaults to `"mou"` | `test_the_route_defaults_to_proposal` |
| An MOU stored under `kind="docx_simple"` | `test_an_mou_upload_is_stored_as_mou_simple` |
| Ruled blanks counted over the body only | `test_ruled_blanks_are_counted_and_reported` (both blanks are in a table in the body — **write a fixture with a blank in a FOOTER too**, or this mutation survives) |
| A ruled blank refuses the upload | `test_a_ruled_blank_does_not_refuse_the_upload` |
| An MOU accepted as `flow=complex` | a new test |

> **Note the third row.** The owner's MOU has both blanks in the body, so a
> body-only count passes on the real document. Build the synthetic fixture
> first or the mutation check is worthless — this is lesson 4 in miniature.

- [ ] **Step 7: Full suites, then commit** — paths: `app/api/admin.py`,
  `app/services/docx_template_service.py`, `tests/docx/test_api.py`,
  `tests/docx/test_template_service.py`.

---

### Task U2: the console

**Files:**
- Modify: `Dashboard/src/.../ProposalTemplates.tsx`, `DocxUpload.tsx`,
  `flow.ts`, `flow.test.ts`
- Regenerate: `Dashboard/src/api/openapi.json` (**CRLF**), `generated.ts` (LF),
  `vocabularies.generated.ts` (**CRLF**)

- [ ] **Step 1: Extend `flow.ts` with the pure decisions and test them there**

The console suite renders no components (D11), so the decisions live in
`flow.ts` beside the existing ones:

```typescript
export function documentTypeLabel(t: string): string {
  return t === "mou" ? "MOU" : "Proposal";
}

/** A template published before this feature has no document_type key. */
export function documentTypeOf(plan: Plan | undefined): string {
  return plan?.document_type === "mou" ? "mou" : "proposal";
}

export function ruledBlankWarning(n: number): string | null {
  if (n <= 0) return null;
  return `${n} ruled blank${n === 1 ? "" : "s"} (like "Date: ______") ` +
    `found. These are not tags and will reach the client as underscores. ` +
    `Replace each with a tag before using this template.`;
}
```

Tests: a template with no `document_type` key reads as a proposal; the warning
is `null` at zero and singular at one.

- [ ] **Step 2: Add the document-type choice to item 6** — beside the existing
  flow choice, defaulting to Proposal. Selecting MOU forces the simple flow and
  says why.

- [ ] **Step 3: Show the warning in the success panel** — beneath the tag
  counts, styled as a warning, not an error. Upload succeeded.

- [ ] **Step 4: Regenerate the client per handover §6b**

From a `git archive HEAD` export with `Dashboard/node_modules` symlinked in,
nvm node 22.11.0 and the `/tmp/shim/python` shim on PATH. Run `dump_openapi.py`
with **no redirect** — it writes both artefacts itself.

**Write line endings back per file.** `openapi.json` and
`vocabularies.generated.ts` are CRLF; `generated.ts` is LF. Skipping this turns
a ~7-line diff into ~22,000.

Verify afterwards that the in-flight feature did not leak in: zero occurrences
of `relationship_manager`, `lead_open_feed_days`, `relationship_engagements`,
`lead_cycles`.

- [ ] **Step 5: Console suites**

```bash
export PATH="/home/telaverge/.nvm/versions/node/v22.11.0/bin:$PATH"
cd Dashboard && node node_modules/typescript/bin/tsc --noEmit \
  && node node_modules/vitest/vitest.mjs run
```
Expected: `tsc` exit 0; Vitest up from 707.

- [ ] **Step 6: Check `Dashboard/dist` is untouched by mtime**, not by
  assumption. Build to `/tmp/throwaway_dist` to prove it builds.

- [ ] **Step 7: Commit** — the named console paths only. `dist` is never
  committed.

---

# Phase F — the fill

### Task F1: distinct questions, grouped by section (D-D)

**Files:**
- Modify: `app/services/proposal_fill_service.py` (`open_questions`,
  `open_session`)
- Test: `tests/docx/test_mou_rounds.py` (new)

**Interfaces:**
- Produces: `section_label(doc, ordinal) -> str` in
  `app/services/proposal_fill_service.py`; each `tags_json` record gains a
  `"section"` key. `open_questions(session, *, limit=QUESTIONS_PER_ROUND)`
  keeps its signature and changes its behaviour.

- [ ] **Step 1: Write the failing test — the defect, stated plainly**

```python
def test_one_literal_in_five_places_is_asked_once(mou_session):
    """`<ask:75>` is five occurrences of one literal. open_questions slices
    raw occurrences and nothing collapses duplicate_of on the asking path, so
    today it fills five of round one's six slots.

    The D13 review already collapses (proposal_agent._group); asking does not.
    """
    asked = fs.open_questions(mou_session)
    raws = [q["raw"] for q in asked]
    assert raws.count("<ask:75>") == 1
    assert len(set(raws)) == len(raws), "a round asked the same literal twice"


def test_answering_the_first_occurrence_settles_all_five(mou_session):
    """Safe because C3 already sends the model EVERY outstanding question on a
    clarification turn, not just the round shown (D8)."""
    await fs.apply_answers(db, ctx, mou_session, "75 students")
    seventy_fives = [t for t in mou_session.tags_json if t["raw"] == "<ask:75>"]
    assert len(seventy_fives) == 5
    assert all(t["value"] == "75" for t in seventy_fives)


def test_a_round_comes_from_one_section(mou_session):
    asked = fs.open_questions(mou_session)
    assert len({q["section"] for q in asked}) == 1


def test_a_tag_in_a_footer_never_inherits_a_body_heading(every_place_session):
    """47 of the MOU's 240 paragraphs are outside the body and have no
    section. They must not take the nearest preceding body heading."""
    footer = [t for t in every_place_session.tags_json
              if t["ordinal"] > BODY_PARAGRAPHS]
    assert all(t["section"] in ("Header", "Footer") for t in footer)
```

- [ ] **Step 2: Run them and watch them fail** — the first on
  `raws.count(...) == 5`, which is the defect measured.

- [ ] **Step 3: Implement `section_label`**

Measured (spec §1b): the owner's MOU carries genuine heading styles —
`Heading1Center` at ordinals 24 and 89, `Heading2` at 90, 112, 149, 159, 169,
181 (*Operation Terms*, *Agreed Deliveries and Offers*, *Pricing Details*,
*Student Enrolment Structure*, *Payment Terms*, *YuviPep Bank Details*). So the
primary mechanism is the style, and the bold-line rule is a real fallback.

```python
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _style_of(p) -> str:
    node = p.find(f"{W}pPr/{W}pStyle")
    return node.get(f"{W}val") if node is not None else ""


def section_labels(docx_bytes: bytes) -> dict[int, str]:
    """Walk ordinal -> the section heading it sits under.

    Measured on the owner's MOU: real Heading1Center/Heading2 styles land
    exactly on the boundaries a round wants to be coherent about. A paragraph
    in a header or footer belongs to no section and is labelled as such -
    47 of 240 paragraphs are there, and giving them the nearest preceding
    BODY heading would be a lie.
    """
    doc = Document(io.BytesIO(docx_bytes))
    body = doc.element.body
    in_body = {id(p) for p in dt.iter_paragraphs(body)}
    labels, current = {}, "Preamble"
    for ordinal, p in enumerate(dt.walk_paragraphs(doc)):
        if id(p) not in in_body:
            labels[ordinal] = "Header" if _is_header(p) else "Footer"
            continue
        style = _style_of(p)
        text = dt.node_text(p).strip()
        if text and ("Head" in style or "Title" in style):
            current = text
        labels[ordinal] = current
    return labels
```

Store the label on each occurrence at `open_session` time. **`tags.py` is not
touched.**

- [ ] **Step 4: Implement the collapse**

```python
def open_questions(session, *, limit=QUESTIONS_PER_ROUND):
    """The questions still to ask - one per distinct literal, from one
    section, at most a round of them (D5, D8, D-D).

    Collapsing is safe because apply_answers sends the model EVERY
    outstanding question, not just the round shown (C3's ruling), so one
    reply settles all five `<ask:75>` at once. A duplicate the model declines
    to answer stays open and surfaces in a later round.
    """
    waiting = [t for t in session.tags_json if t.get("outcome") == "question"]
    seen, distinct = set(), []
    for tag in waiting:
        if tag["raw"] in seen:
            continue
        seen.add(tag["raw"])
        distinct.append(tag)
    if not distinct:
        return []
    # One section per round, so a round is coherent: Pricing Details, then
    # Payment Terms - never a signatory's name beside an instalment date.
    section = distinct[0].get("section")
    same = [t for t in distinct if t.get("section") == section]
    return same if limit is None else same[:limit]
```

- [ ] **Step 5: Run the tests, watch them pass.**

- [ ] **Step 6: Mutation-check**

| Mutation | Must fail |
|---|---|
| Drop the collapse (slice occurrences again) | `test_one_literal_in_five_places_is_asked_once` |
| Collapse on `tag_id` instead of `raw` | same test (every id is distinct, so it is a no-op) |
| Drop the section filter | `test_a_round_comes_from_one_section` |
| Give header/footer paragraphs the nearest body heading | `test_a_tag_in_a_footer_never_inherits_a_body_heading` |
| Send the model only the round shown | `test_answering_the_first_occurrence_settles_all_five` |

- [ ] **Step 7: Measure and report the real round count**

Once the MOU is tagged (G1), record in the ledger how many rounds a real fill
takes. **The spec projects 3-4 against the design input's 8-9. If it disagrees,
stop and tell the owner** — do not adjust the projection to match.

- [ ] **Step 8: Full suites, then commit.**

---

### Task F2: the arithmetic check (D-E)

**Files:**
- Create: `app/services/mou_arithmetic.py`
- Modify: `app/ai/docx_tagfill.py` (add `propose_relations`)
- Modify: `app/services/proposal_fill_service.py` (`open_session` calls it;
  `review_lines` surfaces the mismatch)
- Test: `tests/docx/test_mou_arithmetic.py` (new),
  `tests/docx/test_tagfill_ai.py` (extend)

**Interfaces:**
- Produces:
  `mou_arithmetic.parse_amount(text: str) -> Decimal | None`;
  `mou_arithmetic.check(relations: list[dict], values: dict[str, str]) -> list[dict]`
  returning `[{"result": tag_id, "expected": Decimal, "actual": Decimal, "message": str}]`;
  `docx_tagfill.propose_relations(ctx, *, occurrences, document_text) -> list[dict]`.
  A relation is `{"result": tag_id, "op": "product" | "sum", "operands": [tag_id, ...]}`.

- [ ] **Step 1: Write the failing tests for the pure module first**

```python
# tests/docx/test_mou_arithmetic.py
@pytest.mark.parametrize("text,expected", [
    ("Rs. 3,00,000/- Net (Including GST).", Decimal("300000")),
    ("Rs. 4000/- net (including GST) per student annually.", Decimal("4000")),
    ("Rs. 1,50,000/-", Decimal("150000")),
    ("75", Decimal("75")),
])
def test_indian_grouping_and_decoration_are_parsed(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", [
    "to be agreed", "", "the range above", "second week of February 2027",
    "Rs. 15,00,000/- to Rs. 25,00,000/-",   # a RANGE is not one amount
])
def test_what_cannot_be_parsed_returns_none_rather_than_guessing(text):
    assert parse_amount(text) is None


def test_a_product_that_does_not_hold_is_reported():
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "Rs. 4000", "students": "75",
              "total": "Rs. 2,50,000/- Net"}
    (mismatch,) = check(relations, values)
    assert mismatch["expected"] == Decimal("300000")
    assert mismatch["actual"] == Decimal("250000")
    assert "3,00,000" in mismatch["message"]


def test_instalments_that_do_not_sum_to_their_total_are_reported():
    relations = [{"result": "total", "op": "sum",
                  "operands": ["first", "second"]}]
    values = {"first": "Rs. 1,50,000/-", "second": "Rs. 1,40,000/-",
              "total": "Rs. 3,00,000/-"}
    assert len(check(relations, values)) == 1


def test_an_unparseable_operand_produces_NO_warning_at_all():
    """Silence beats a false alarm. A spurious warning on a legitimate
    negotiated figure teaches the reader to dismiss the warnings, which
    destroys the only thing this check is for."""
    relations = [{"result": "total", "op": "product",
                  "operands": ["price", "students"]}]
    values = {"price": "as agreed", "students": "75", "total": "Rs. 3,00,000"}
    assert check(relations, values) == []


def test_arithmetic_is_decimal_not_float():
    """No floats anywhere near a payment schedule."""
    relations = [{"result": "t", "op": "product", "operands": ["a", "b"]}]
    values = {"a": "0.1", "b": "3", "t": "0.3"}
    assert check(relations, values) == []
```

- [ ] **Step 2: Run them and watch them fail** with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the pure module** — `Decimal` throughout; a range
  (two amounts in one string) returns `None`; a mismatch message names **both**
  figures in Indian grouping so the reader can see which is wrong.

- [ ] **Step 4: Write the failing tests for `propose_relations`**

```python
async def test_the_model_never_supplies_a_figure(fake_llm):
    """D15 is absolute. propose_relations returns tag ids and an operator.
    A relation carrying a number is malformed and is dropped."""
    fake_llm.returns({"relations": [
        {"result": "t1", "op": "product", "operands": ["t2", "t3"],
         "value": "Rs. 3,00,000"},
    ]})
    (relation,) = await propose_relations(ctx, occurrences=OCC, document_text=DOC)
    assert "value" not in relation


async def test_a_relation_naming_an_unknown_tag_is_dropped_and_reported(fake_llm, caplog):
    fake_llm.returns({"relations": [
        {"result": "t1", "op": "product", "operands": ["t2", "invented"]}]})
    assert await propose_relations(ctx, occurrences=OCC, document_text=DOC) == []
    assert "invented" in caplog.text


async def test_an_unknown_operator_is_dropped(fake_llm):
    fake_llm.returns({"relations": [
        {"result": "t1", "op": "exponentiate", "operands": ["t2"]}]})
    assert await propose_relations(ctx, occurrences=OCC, document_text=DOC) == []
```

- [ ] **Step 5: Implement `propose_relations`** — one call at `open_session`,
  every `tag_id` validated against the occurrence map, unknown ids dropped and
  logged, `op` restricted to `product` / `sum`, any numeric field stripped. The
  relation is stored **on the result tag's own record in `tags_json`** under a
  `"relation"` key. `tags_json` is **reassigned, never mutated** (C3).

- [ ] **Step 6: Surface it, and gate the approval**

`review_lines` appends the mismatch to the result tag's existing `warnings`
list. `_review_message` already renders warnings — extend it to render the
arithmetic message verbatim rather than the price-drift wording.

The approval gate:

```python
async def test_an_approval_with_a_mismatch_standing_is_refused_once(session):
    first = await confirm(session, approved=True)
    assert first["ok"] is False
    assert "3,00,000" in first["message"]
    assert not built(session)

    second = await confirm(session, approved=True)
    assert second["ok"] is True and built(session)


async def test_the_value_written_is_exactly_what_the_person_typed(session):
    """The check NEVER substitutes. D15: no number reaches a document unless
    Python computed it from a locked rate card or a person typed it - and this
    check computes nothing that is written."""
    assert value_in_document(session, "total") == "Rs. 2,50,000/- Net"


async def test_correcting_an_operand_clears_the_acknowledgement(session):
    """A figure that has just changed has not been acknowledged since - the
    same rule _record already applies to `reviewed`."""
    await acknowledge(session)
    await correct(session, "make the price 4500")
    assert tag(session, "total")["arithmetic_ack"] is False
```

`arithmetic_ack: true` is written onto the result tag's record; `_record`
clears it whenever it touches an operand.

- [ ] **Step 7: Mutation-check**

| Mutation | Must fail |
|---|---|
| A model-supplied figure is kept | `test_the_model_never_supplies_a_figure` |
| The check substitutes its computed figure | `test_the_value_written_is_exactly_what_the_person_typed` |
| An unparseable operand warns anyway | `test_an_unparseable_operand_produces_NO_warning_at_all` |
| The first approval builds | `test_an_approval_with_a_mismatch_standing_is_refused_once` |
| The acknowledgement survives a correction | `test_correcting_an_operand_clears_the_acknowledgement` |
| `float` instead of `Decimal` | `test_arithmetic_is_decimal_not_float` |
| An unknown tag id is kept | `test_a_relation_naming_an_unknown_tag_is_dropped_and_reported` |

- [ ] **Step 8: Full suites, then commit.**

---

### Task F3: the fill service builds an MOU

**Files:**
- Modify: `app/services/proposal_fill_service.py` (`open_session`, `build`,
  new `_write_mou`, `_rewrite_mou`, `reopen_for_correction`)
- Test: `tests/docx/test_mou_fill.py` (extend)

**Interfaces:**
- Consumes: M2's `MouDocument`, M3's `document_type`, U1's `mou_simple`.
- Produces: `proposal_fill_service.build(db, ctx, session)` dispatching on
  `session.document_type`; `is_mou_flow(db, ctx, program_id) -> bool` beside
  the existing `is_simple_flow`.

- [ ] **Step 1: Write the failing end-to-end test**

```python
async def test_a_whole_mou_fill_builds_a_document_and_not_a_proposal(db, ctx, lead, program):
    session = await fs.open_session(db, ctx, lead_id=lead.id,
                                    program_id=program.id, document_type="mou")
    while fs.open_questions(session):
        await fs.apply_answers(db, ctx, session, "use the defaults")
    await fs.mark_ready(db, ctx, session)
    mou = await fs.build(db, ctx, session)

    assert isinstance(mou, MouDocument)
    assert mou.docx_path and mou.filled_json
    assert await proposal_count(db, lead.id) == 0, (
        "an MOU created a Proposal row - it would enter the sales pipeline"
    )


async def test_an_mou_has_no_commercial_figures_to_be_wrong_about(built_mou):
    """DEFECT 2's lesson: the chat announced 'Total amount: 2200' from a rate
    card the document never used. An MOU has no such fields at all."""
    assert not hasattr(built_mou, "total_amount")
    assert not hasattr(built_mou, "line_items")


async def test_the_build_refuses_a_document_with_anything_skipped(session):
    """apply_tags reports rather than raises; acting on the report is this
    layer's job (A3's docstring says so)."""
    with pytest.raises(ValidationFailedError, match="not created"):
        await fs.build(db, ctx, session_whose_writes_all_skip)
    assert await mou_count(db) == 0
```

- [ ] **Step 2: Run it and watch it fail.**

- [ ] **Step 3: Implement `_write_mou`**

Mirrors `_write_proposal` and drops everything commercial. It **must**:
refuse if `apply_tags` returns a non-empty `skipped`, naming the tags and
saying plainly that nothing was created; call `index.refresh_static` itself
when the document has a static contents page (exactly as
`docx_proposal_service.py:102` does); produce the PDF, logging and leaving
`pdf_path` null on a converter failure rather than discarding an approved
document; and build `filled_json` with the same eight keys
`proposal_fill_service.filled_json` already produces.

- [ ] **Step 4: Dispatch in `build`, and make idempotence check status first**

J2's defect, and it applies unchanged: check *"is this session already BUILT"*
**before** anything else, so a double tap returns the document that exists
rather than a baffling refusal.

- [ ] **Step 5: The correction path** — `reopen_for_correction` and
  `_rewrite_mou` update the **same** row so the id the salesperson holds keeps
  working, save a revision, write files anew rather than overwriting, and
  **clear `pdf_path` before re-converting** so a failed rebuild cannot leave a
  stale PDF from before the correction. **Refuse once `status == "sent"`.**

- [ ] **Step 6: Mutation-check**

| Mutation | Must fail |
|---|---|
| An MOU writes a `Proposal` row | `test_a_whole_mou_fill_builds_a_document_and_not_a_proposal` |
| Ship a document with `skipped` non-empty | `test_the_build_refuses_a_document_with_anything_skipped` |
| Idempotence checked after status | a double-approval test |
| A stale PDF survives a failed rebuild | a correction test with a broken converter |
| A sent MOU can be corrected | a sent-MOU test |
| `ready` reachable without `reviewing` | the transition assertion |

- [ ] **Step 7: Full suites, then commit.**

---

# Phase A — the agent

### Task A1: extract the fill handlers (pure refactor, no behaviour change)

`proposal_agent.py` is 1,081 lines. Sharing the handlers is what keeps it from
doubling.

**Files:**
- Create: `app/ai/agents/fill_tools.py`
- Modify: `app/ai/agents/proposal_agent.py`
- Test: the existing `tests/docx/test_fill_agent.py` and
  `test_fill_build.py` are the proof — **they must pass unchanged.**

- [ ] **Step 1: Move `_question_line`, `_round_message`, `_round_candidates`,
  `_review_message`, `_group`** into `fill_tools.py`, parameterised by document
  type where the wording differs. `proposal_agent` imports them.

- [ ] **Step 2: Run the existing suites and require them green with NO edits**

```bash
.venv/bin/python -m pytest tests/docx/test_fill_agent.py tests/docx/test_fill_build.py -q
```
Expected: exactly the counts before the move. **If a test needed changing, the
refactor changed behaviour** — stop and find out why.

- [ ] **Step 3: Commit** — a pure move, reviewable as one.

---

### Task A2: the MOU tools, the prompt, and the router — in ONE commit

**This task is where the last session lost three days.** J1 added the fill
tools and never told the agent they existed; the agent ran on the fast tier,
called `create_proposal` six times, and the conversation looped in front of the
owner. **The tools and the words that describe them ship together.**

**Files:**
- Modify: `app/ai/agents/proposal_agent.py` (tools, system prompt, handlers)
- Modify: `app/ai/orchestrator.py` (`_ROUTER_PROMPT`)
- Test: `tests/docx/test_mou_agent.py` (new)

**Interfaces:**
- Produces tools `create_mou`, `answer_mou_questions`, `show_mou_questions`,
  `confirm_mou_values`, `show_mou_review`, `correct_mou`.

- [ ] **Step 1: Widen the router line**

`app/ai/orchestrator.py`, `_ROUTER_PROMPT`:

```
- proposal: anything about proposals OR MOUs - create, edit quantities/prices/
  wording, send a proposal ("create the IBC proposal and email it to their
  finance head"), and memoranda of understanding ("create the MOU for IBC",
  "draft the MoU for Sandur"). One agent owns both documents.
```

**Measured:** today the word "MOU" appears nowhere in the router prompt, so
*"create the MOU for IBC"* matches nothing and falls back to `query`.

- [ ] **Step 2: Add the MOU paragraph to the system prompt — in this same edit**

```
AN MOU IS A SEPARATE DOCUMENT WITH ITS OWN PIPELINE. "Create the MOU for
IBC" means `create_mou`, never `create_proposal`. It opens a fill and asks
you to put questions to the user, exactly as a tagged proposal does. Every
reply they give about those questions goes to `answer_mou_questions` --
NEVER to `create_mou` again. Calling `create_mou` a second time cannot make
progress: the fill is already open and you would ask the same questions
again. Use `show_mou_questions` if they ask what is outstanding,
`confirm_mou_values` when they approve the list or want one changed, and
`correct_mou` to change a value in an MOU that has already been built.
```

- [ ] **Step 3: The deterministic loop-breaker**

A prompt is advice; a tool result is fact. `create_mou` on a fill that already
has open questions **returns** rather than re-raising the round:

```python
async def test_calling_create_mou_again_names_the_right_tool(runtime):
    """The regression test drives the WRONG tool deliberately, the way the
    real model did."""
    result = await agent._create_mou(runtime, program="IBC", client="Sandur")
    assert result["already_open"] is True
    assert result["still_to_answer"] > 0
    assert "answer_mou_questions" in result["what_to_do"]
```

- [ ] **Step 4: Refuse the editing tools for an MOU**

DEFECT 3's lesson transfers exactly: for an MOU, `content_md` is the projection
of a document already written and converted, so `edit_narrative` would change
the record, leave the `.docx` untouched, and **report success over a file that
never moved.**

```python
async def test_edit_narrative_refuses_for_an_mou_and_names_the_way_forward(mou):
    result = await agent._edit_narrative(runtime, instruction="make it warmer")
    assert result["ok"] is False
    assert "correct_mou" in result["message"]


async def test_it_refuses_on_an_instruction_WITHOUT_a_price(mou):
    """DEFECT 3 refused only because the instruction happened to contain a
    price and tripped narrative_price_drift. Ask what the code does on the
    path that does NOT trip the guard."""
    result = await agent._edit_narrative(runtime, instruction="reword the recitals")
    assert result["ok"] is False
```

Both tool **descriptions** must say so too — a refusal the model could have
avoided is one it should not have reached.

- [ ] **Step 5: Run the tests, watch them pass.**

- [ ] **Step 6: Mutation-check**

| Mutation | Must fail |
|---|---|
| Strip the MOU paragraph out of the system prompt | a prompt-content assertion |
| Remove the loop-breaker (the original defect) | `test_calling_create_mou_again_names_the_right_tool` |
| Drop the tool name from `what_to_do` | the same test's third assertion |
| `edit_narrative` allowed for an MOU | `test_it_refuses_on_an_instruction_WITHOUT_a_price` |
| Router line reverted | Task A3's routing test |
| Every template kind treated as an MOU | the proposal-flow regression tests |

- [ ] **Step 7: Full suites, then commit** — tools, prompt and router in **one**
  commit.

---

### Task A3: test the model's CHOICE, not a scripted call

**The single most important test in this plan.** Every J1/J2 test scripted
`ToolCall(name=...)`, which proves what happens *when* a tool is called and
never that a model *would* call it — and that is exactly where the conversation
looped.

**Files:**
- Test: `tests/docx/test_tool_choice.py` (new)

- [ ] **Step 1: Build a fake model layer driven by the PROMPT, not by a script**

It reads the system prompt and tool specs it is actually handed and picks a
tool by matching the user's text against the tool descriptions — a crude
stand-in for a real router, but one that **can be wrong**, which a scripted
call cannot.

```python
def test_create_the_mou_for_ibc_reaches_the_mou_tools(prompt_driven_llm):
    called = run_command("create the MOU for IBC for Sandur Education Centre")
    assert called[0] == "create_mou"


def test_a_reply_to_mou_questions_does_not_reach_create_proposal(prompt_driven_llm):
    """The defect, exactly: six calls to create_proposal and zero to
    answer_proposal_questions."""
    run_command("create the MOU for IBC for Sandur")
    called = run_command("32 workshops, 75 students")
    assert "create_mou" not in called
    assert called[0] == "answer_mou_questions"


def test_the_router_sends_an_mou_request_to_the_proposal_agent(prompt_driven_router):
    assert route("create the MOU for IBC") == "proposal"
    assert route("create the IBC proposal") == "proposal"
```

- [ ] **Step 2: Prove the test can fail** — revert the system-prompt paragraph
  and the router line and watch each test go red. **A test that cannot fail
  proves nothing**, and this whole task exists because three of them could not.

- [ ] **Step 3: Commit.**

---

# Phase G — the golden suite

### Task G1: tag the owner's MOU and run the whole flow

**Files:**
- Create: `scripts/tag_mou_sample.py`
- Test: `tests/docx/test_mou_golden.py` (new, opt-in like the existing goldens)

- [ ] **Step 1: Probe before tagging — print all 240 paragraphs with their
  section labels and row labels.** J3's first tagging was wrong and the golden
  suite caught it; the probe is what makes the decision rather than a guess.

- [ ] **Step 2: Write the tagging script** — idempotent in effect (always reads
  the untagged original, writes the tagged copy), **dry-run by default**,
  printing every replacement before touching anything. Committed even though
  `data/samples` is gitignored, so a reader can tell whether the fixture is
  missing or was never built.

Tag per spec §2a/§2b: client name (×10), address, representative, signatory and
title, MOU date, the two signing dates; and as `ask`/`ask_calculate` the
programme, workshop count (×3), grades, completion date, per-student price,
student count (×5), annual total, academic years (×2), both instalments and the
second's date, and the ten deliverables rows. **Leave alone** YuviPep's own
address, bank details, contacts and the Confidentiality/General Terms prose.

- [ ] **Step 3: Assert the shape is unchanged by tagging**

```python
def test_tagging_changes_no_structure(untagged, tagged):
    """replace_span writes in place and inserts nothing. If tagging changed
    the shape, every later assertion about the BUILT document would be
    measuring the wrong baseline."""
    assert paragraphs(tagged) == paragraphs(untagged) == 240
    assert sections(tagged) == sections(untagged) == 3
    assert tables(tagged) == tables(untagged) == 8
    assert images(tagged) == images(untagged) == 11
```

- [ ] **Step 4: Count literals, never read them**

```python
def test_no_placeholder_survives_anywhere_including_the_footers(built_docx):
    """47 of 240 paragraphs are outside the body. Two of the ten
    `Sandur Education Centre` are among them."""
    for literal in ("Sandur Education Centre", "Innovation Nexus",
                    "Y S Ghorpade", "Rs. 1,50,000"):
        assert raw_count(built_docx, literal) == 0
    assert len(scan(built_docx)) == 0
```

- [ ] **Step 5: Run the whole flow and pin what it measures** — upload → resolve
  → rounds → review → approve → build → PDF. Assert 0 tags left, sections/media/
  tables unchanged, the PDF's text layer carries the client's name and **not**
  `Sandur Education Centre`, and **no `Proposal` row exists.**

- [ ] **Step 6: Record the real round count in the ledger** (F1 Step 7).

- [ ] **Step 7: Report the three `Error!` field references to the owner again**
  if they are still in the source document — they will be in the built one too.

- [ ] **Step 8: Commit** the script and the tests. **Not the fixture**
  (`data/samples` is gitignored).

---

# Phase R — surfacing

### Task R1: the MOU read routes

**Files:**
- Create: `app/api/mous.py`
- Modify: `app/main.py` (register the router), `app/api/leads.py` (add MOUs to
  the lead detail, **beside** proposals, never merged into that list)
- Test: `tests/docx/test_mou_api.py` (new)

- [ ] **Step 1: Write the failing tests** — `GET /mous/{id}` returns the
  provenance and both file paths; `GET /leads/{id}` carries a **separate**
  `mous` key; an MOU **never** appears in that response's `proposals` list; and
  org scoping refuses another organisation's MOU.

- [ ] **Step 2: Implement, run, mutation-check** (merge the lists → the
  separation test fails; drop the org filter → the scoping test fails).

- [ ] **Step 3: Full suites, then commit.**

---

### Task R2: Android

**The project is at `C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI`
on the local machine, NOT the VM. It is not a git repository — back up every
file before editing.** There is no Robolectric, so **anything left in a fragment
cannot be tested**, which is exactly how E1's two defects survived.

**Files:**
- Create: `MouDto.java`, `MouLines.java`, `MouLinesTest.java`,
  `app/src/test/resources/contract/mou_detail.json`
- Modify: the client-screen fragment, `ContractTest.java`, `strings.xml`

- [ ] **Step 1: Capture the fixture from a REAL run**, not by typing it — a
  throwaway pytest that runs upload → resolve → answer → review → build, then
  calls `GET /mous/{id}` through the real route and writes the response.
  Delete the throwaway; record the method in the ledger, because the fixture
  needs regenerating when the shape changes.

- [ ] **Step 2: Put the pure decisions in `MouLines`** — `isMou(kind)`,
  `sourceLabel(source)` returning a `@StringRes int`, `heading(entry)`. E1's
  lesson: `sourceLabel` must not fall `"user"` and `"default"` through to
  "From your records", which would tell a salesperson that a figure they typed
  themselves came out of the database.

- [ ] **Step 3: Add a `ContractTest` case** over the new fixture.

- [ ] **Step 4: Run the JVM suite**

```bash
JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew :app:testOrgDebugUnitTest
```
Expected: up from 61, 0 failures. (The JDK on PATH is Java 8 and Gradle 9.3.1
refuses it; there is no plain `testDebugUnitTest` — the flavours are `org` and
`platform`.)

- [ ] **Step 5: Mutation-check** — hide the card for an MOU; drop the user and
  default labels; credit the template's suggestion to the salesperson. Each
  must fail exactly one test.

- [ ] **Step 6: Check every file is still CRLF**, line by line, as E1 did.
  Nothing is committed — this project has no git.

---

# Phase E — closing

### Task E1: documentation and deploy

**Files:**
- Modify: `Dashboard/READMEs/05_DECISIONS.md` (D38+), 
  `Dashboard/READMEs/09_BACKEND_CHANGES.md` (a seventh unfreeze),
  `BACKEND_README.md` (**dirty — §6a**)

- [ ] **Step 1: Measure which of the three are dirty**, do not assume. E2
  measured that §9's claim about two files was wrong and it applied to one.

- [ ] **Step 2: Write D38-D44** for D-A .. D-F, the routing decision and the
  correction rules. Record explicitly that **D-D fixed a latent defect in the
  proposal flow too** — `open_questions` never collapsed duplicates — and that
  it was invisible there only because the repeated literal was semantic.

- [ ] **Step 3: `09_BACKEND_CHANGES.md` §1c** — the MOU pipeline, the two
  migrations, the new table and the new routes. **The file is CRLF.**

- [ ] **Step 4: `BACKEND_README.md` under §6a.** Three of its figures already
  differ between HEAD and the tree (the app line count, the Tests row, §13's
  opening paragraph), so **every edit must accept either variant** and write
  one result.

- [ ] **Step 5: Deploy**

```bash
printf '%s\n' 'tela@123' | sudo -S -p '' systemctl restart salesforce-app-restart.service
restart_script/restart_backend.sh status
restart_script/restart_backend.sh url
```
A restart is what makes `create_all` build `mou_documents`. **Verify it was
absent before and has every column after.** Verify over the **public** URL, not
just locally.

- [ ] **Step 6: Build the console from the WORKING TREE** (not a HEAD export —
  the tree carries `session/baseUrl.ts`, without which a console served over
  ngrok tells every visitor's browser to call `127.0.0.1:8000`).

- [ ] **Step 7: Tell the owner plainly what you verified yourself and what
  still needs their eyes**, and remind them the three `Error!` field references
  in the source MOU are theirs to fix in Word.

---

## Self-review

**Spec coverage.** D-A → M2, F3, R1, R2. D-B → M1. D-C → M3, F3. D-D → F1.
D-E → F2. D-F → U1, U2. Routing → A2, A3. Corrections → F3. Engine reused
unchanged → no task touches `tags.py`, `text.py`, `tagfill.py` or
`client_dossier.py`, which is the point. Spec §1c (the `Error!` references) →
G1 Step 7 and E1 Step 7, reported not worked around. Spec §11's five risks →
M1 Step 7, A3, F2 Step 7, F1 Step 6 row 4, M2 Step 5.

**Placeholders.** None. Every code step carries real code; every "run this"
step carries the exact command and the expected result.

**Type consistency.** `document_type` is the name everywhere — the column on
`ProposalTemplate` (M1), the column on `ProposalFillSession` (M3), the form
field (U1), the keyword argument on `_current` (M1), `open_session`,
`find_open`, `find_for_chat` and `find_correctable` (M3), and the dispatch key
in `build` (F3). `MouDocument` / `MouStatus` (M2) are what R1 and R2 consume.
A relation is `{"result", "op", "operands"}` in F2's producer and its consumer.
`parse_amount` returns `Decimal | None` in both the tests and the interface
block.

**One gap found and closed while reviewing:** U1's ruled-blank mutation check
would have survived on the owner's real document, because both of its blanks
are in the body. The synthetic footer fixture is now called for explicitly in
that step.
