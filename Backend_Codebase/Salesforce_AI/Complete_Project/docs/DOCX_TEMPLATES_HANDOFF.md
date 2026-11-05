# Handover — DOCX proposal templates

**Updated 4 September 2026, at the end of Task 23 — the plan is COMPLETE.**
All 23 tasks are done, 24 commits, `aa49e80..c81fb08`. What remains is listed in
§8, and the one thing the plan itself asks for and did not get is at the top of
it: nobody has looked at a generated proposal by eye.

This file exists so the next session does not have to rediscover anything. It
follows the convention of `docs/SESSION_HANDOFF.md`, which is about a
*different* feature (the relationship manager) and is unrelated to this work.

---

## 1 · What this work is

The proposal path used to store a Markdown body with `{variables}`, substitute
them, and rebuild a document from scratch with python-docx and reportlab. Three
things went wrong with that, all reported from real use:

1. The AI wrote its own task list into the client's document ("I will now draft
   the greeting", "[Insert pricing summary]").
2. Markdown artefacts survived into the output — stray `**`, unrendered
   `*italic*`, numbered lists printed literally.
3. The rendered document had no branding at all, because `render_docx` starts
   from a blank `Document()`.

The fix is to stop **generating** documents and start **filling** them. An
administrator uploads the organisation's real `.docx` at checklist item 6. The
backend parses it, OCRs its images, and an LLM proposes placeholders which a
human accepts, rejects, rewords or moves in a dashboard editor. At proposal
time the backend loads the **untouched source `.docx`**, resolves system fields
from the database, asks the model for **plain text** for the prose placeholders
only, and writes into a copy.

The source file is never rewritten. Every proposal is
`source.docx + plan + values -> new file`.

---

## 2 · Where everything lives

| Thing | Path |
|---|---|
| Design spec (the binding authority) | `docs/superpowers/specs/2026-09-03-docx-proposal-templates-design.md` |
| Implementation plan, 23 tasks | `docs/superpowers/plans/2026-09-03-docx-proposal-templates-plan.md` |
| **Execution ledger — the source of truth for what happened** | `.superpowers/sdd/2026-09-03-docx-proposal-templates-plan/progress.md` |
| The four real sample documents | `data/samples/` (27 MB, **not in git**) |
| Backup taken before any change | `../../backup_2026_09_03_docx_templates/` |

**The plan's `- [ ]` checkboxes are NOT maintained.** All 131 are still
unticked, including for the nineteen finished tasks. Do not read them as
progress — the ledger is authoritative, and it has one or more lines per task
recording numbers, defects found, and rulings made.

---

## 3 · The state right now

> **SUPERSEDED for anything after 4 September 2026.** This section describes
> the COMPLEX flow at the end of its own build. A second feature -- the SIMPLE
> flow -- has since been built on the same branch, and HEAD, the commit count
> and the test totals below are all out of date. For current state read
> `docs/superpowers/plans/2026-09-07-docx-simple-flow-plan.md` §0 and the ledger
> at `.superpowers/sdd/2026-09-07-docx-simple-flow-plan/progress.md`.
>
> **Sections 4, 5 and 6 of this document are still accurate and still
> required** -- how to reach the code, the environment, the console toolchain,
> and the two techniques in §6. Those are why this file is still worth reading.

Branch **`feature/docx-proposal-templates`**, created off `aa49e80`.
**HEAD is `c81fb08`. 24 commits. All 23 tasks are complete.** Nothing is merged
and the branch has not been pushed.

```
c81fb08 docs: record the fifth unfreeze and the docx template subsystem  (T23)
a83da62 feat(console): token binding panel and rate-card table mapping   (T21)
3be126f feat(console): the placeholder editor                            (T20)
```

**Task 22 made no commit**: the Android project is not a git repository
(ruling R5, re-verified). Seven files changed there —
`ProposalDetailDto.java` (+`Filled`), `ProposalDetailFragment.java`
(`renderFilled`), `fragment_proposal_detail.xml`, the new
`item_filled_line.xml`, `strings.xml`, and a new `ContractTest` fixture plus
three tests over it.

**Test state, verified at `c81fb08`:** backend `571 passed / 1 failed` (the
pre-existing `test_relationship_screens.py`) and `tests/docx` 168 passed;
console `688 passed / 18 files`, `tsc --noEmit` exit 0, and the bundle builds;
Android `assembleOrgDebug` and `testOrgDebugUnitTest` green, 51 unit tests.

<details>
<summary>The commit list up to Task 19 (unchanged)</summary>


```
a469b8b feat(console): upload a Word document as a proposal template      (T19)
d8fafba test(console): reset preview now covers 56 tables                 (T18 fix)
11bd63d feat(console): generated client and endpoints for docx templates  (T18)
c7006e5 feat(api): docx template upload, plan editing, preview and media  (T17)
21354f4 feat: edit a docx proposal by re-filling named placeholders       (T16)
b1ee486 feat: PDF for docx proposals via LibreOffice                      (T15)
5a408f8 feat: build proposals from docx templates without re-rendering    (T14)
ddd13f2 feat: ingest an uploaded .docx as a proposal template version     (T13)
b1c786b feat(models): docx template kind, template docs table, filled_json (T12)
da821b5 feat(ai): placeholder suggestion pass, validated against outline  (T11)
21f5f46 feat(ai): grounded prose fill with a scrub-and-retry contract     (T10)
0861241 feat(docx): apply a fill plan to a copy of the template           (T9)
e6055e4 feat: deterministic scrubber for model-written proposal prose     (T8)
872d51b feat(docx): structural edits, formatting inherited from document  (T7)
9dd1784 feat(docx): index detection and static TOC page refresh           (T6)
98ccf1c feat(docx): tesseract OCR of embedded template images             (T5)
47c6cf5 feat(docx): block outline with positional anchors + fingerprints  (T4)
3f9ea0f test(docx): golden coverage over the four real documents          (T3)
7f95692 fix(docx): guard xml:space on every replace_span node             (T2 fix)
16a8a76 feat(docx): w:t-level text access and span replacement            (T2)
30a0646 feat(docx): LibreOffice DOCX->PDF converter                       (T1)
```

</details>

The one failure to expect is
`tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first`
— pre-existing, part of the unrelated in-flight feature. **Do not try to fix
it. Just confirm it stays the only failure.**

### The working tree is deliberately dirty — this still matters

`git status --porcelain | wc -l` must read **89** at all times: unrelated
in-flight `feature/pre-sales-cold-calling` work. **Never commit any of it.**
Never `git add -A`, never `git add .`, never commit `Dashboard/dist/`.

After every commit: `git show --stat --oneline HEAD` must list exactly the
paths the task names, and the dirty count must be back to 89.

---

## 4 · How to reach the code

**The repository is on a VM, not on this machine.**
`/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project`
on `telaverge@172.16.10.55`, password `tela@123`, reachable only while the OVPN
tunnel is up. `sshpass` and `plink` are not installed; there are no SSH keys.

Recreate two helpers in your scratchpad. **Include the retries and the
encoding hardening** — both were added after real failures in the last session.

`rc.py` — run a remote command (command text on STDIN only):

```python
import sys, io, time, paramiko
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", newline="")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", newline="")
HOST, USER, PASS = "172.16.10.55", "telaverge", "tela@123"
PROJ = "/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project"

def _connect(attempts=6):
    last = None
    for i in range(attempts):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username=USER, password=PASS, timeout=30,
                      banner_timeout=30, auth_timeout=30,
                      allow_agent=False, look_for_keys=False)
            return c
        except Exception as exc:
            last = exc; time.sleep(2 + i * 3)
    raise last

def main():
    script = sys.stdin.read()
    if not script.strip():
        sys.stderr.write("rc.py: empty command on stdin\n"); return 2
    cli = _connect()
    wrapper = "cd %s || exit 97\n%s" % (PROJ, script)
    chan = cli.get_transport().open_session()
    chan.settimeout(1800)
    chan.exec_command("bash -s")
    # "replace": lone surrogates arrive from the host shell (e.g. a pasted
    # U+276F) and would otherwise raise UnicodeEncodeError and lose the call.
    chan.sendall(wrapper.encode("utf-8", "replace"))
    chan.shutdown_write()
    out, err = b"", b""
    while True:
        if chan.recv_ready(): out += chan.recv(65536); continue
        if chan.recv_stderr_ready(): err += chan.recv_stderr(65536); continue
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready(): break
    rc = chan.recv_exit_status(); cli.close()
    sys.stdout.write(out.decode("utf-8", "replace"))
    if err: sys.stderr.write(err.decode("utf-8", "replace"))
    return rc

if __name__ == "__main__":
    sys.exit(main())
```

`put.py` — upload one file, with retries (SFTP loses negotiation under load):

```python
import sys, time, paramiko
HOST, USER, PASS = "172.16.10.55", "telaverge", "tela@123"

def _once(local, remote):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=30,
              allow_agent=False, look_for_keys=False)
    s = c.open_sftp()
    parts, cur = remote.split("/")[1:-1], ""
    for p in parts:
        cur += "/" + p
        try: s.stat(cur)
        except IOError: s.mkdir(cur)
    s.put(local, remote)
    print("uploaded %s -> %s (%d bytes)" % (local, remote, s.stat(remote).st_size))
    s.close(); c.close()

def main():
    local, remote = sys.argv[1], sys.argv[2]
    last = None
    for attempt in range(6):
        try: _once(local, remote); return
        except Exception as exc: last = exc; time.sleep(3 + attempt * 4)
    raise SystemExit("upload failed after retries: %s" % last)

if __name__ == "__main__":
    main()
```

A `get.py` (same shape, `s.get(remote, local)`) is useful for pulling PDFs back.

### Six rules that cost real time to learn

1. **Always pass remote commands on stdin via a `<<'REMOTE'` heredoc, never as
   argv.** Git Bash rewrites any `/home/...` argument into a Windows path.
2. **`MSYS_NO_PATHCONV=1` in front of `python put.py`** for the same reason.
3. **Never use a `pgrep`/`pkill` pattern that matches its own command line.**
4. **Write Python locally and upload it** rather than embedding it in a remote
   heredoc. Apostrophes in docstrings break the local heredoc too — use the
   Write tool for the local file, not `cat > file <<'EOF'`.
5. **Keep non-ASCII out of inline remote commands.** Curly quotes and `❯`
   arrive as lone surrogates. The `errors="replace"` above stops the crash,
   but the character is still mangled — put such text in an uploaded file.
6. **Never leave a helper script in the project root.** `/tmp` on the VM is the
   place; a stray file shows up as a 90th dirty path.

---

## 5 · The environment

| | |
|---|---|
| OS | Ubuntu 22.04.4, Python 3.10.12, venv at `.venv/` |
| Python packages | `python-docx` 1.2.0, `lxml` 6.1.2, `pypdf` 6.16.2, `Pillow` 12.3.0 — **no new pip dependency is needed** |
| LibreOffice | 7.3.7 at `/usr/bin/soffice`. Converts the real documents in 1.5–3.1 s |
| Tesseract | 4.1.1 at `/usr/bin/tesseract`, `eng`. Called via `subprocess`; `pytesseract` deliberately NOT installed |
| Database | `data/salesplatform.db` (SQLite, from `.env`). **Not `data/app.db`** — the plan names the wrong file in Task 12 Step 10 |
| Sample documents | `data/samples/`, 4 files |

### Console toolchain — none of this is in the plan, all of it is required

1. **`/usr/bin/node` is v12.22.9 and cannot parse `??`**, so `tools/gen.mjs`
   dies. Use nvm's Node 22:
   `export PATH="/home/telaverge/.nvm/versions/node/v22.11.0/bin:$PATH"`
2. **`gen.mjs` spawns a bare `python`**, which Ubuntu does not have. Create a
   shim before running `gen:api` or `gen:check`; `/tmp` does not survive a
   reboot, so recreate it each session:
   ```bash
   mkdir -p /tmp/shim
   printf '#!/bin/sh\nexec %s/.venv/bin/python "$@"\n' "$PROJ" > /tmp/shim/python
   chmod +x /tmp/shim/python
   export PATH="/tmp/shim:$PATH"
   ```
3. **`node_modules` was reinstalled on 4 Sep** (`npm ci`, 181 packages, ~7 min).
   It had been installed on Windows, so rollup's Linux binding was missing and
   **vitest could not run at all**. It works now. If it breaks again, that is
   the cause. npm warns `EBADENGINE` because Vite 7 wants Node ≥22.12 and nvm
   has 22.11.0 — harmless today.
4. `npx tsc` may still say "Permission denied" for a Windows-era shim; call the
   tool directly: `node node_modules/typescript/bin/tsc --noEmit`.

---

## 6 · Two techniques you will need, and must not improvise

### 6a · Committing a file that is ALREADY dirty

Three plan-touched files carry unrelated in-flight changes:
`app/models/__init__.py`, `app/core/reset_taxonomy.py`,
`tests/test_reset_taxonomy.py`. Their HEAD content and their working-tree
content differ, and **the correct commit is HEAD + your edit, not the working
tree**. Committing the working tree sweeps in the other feature; committing a
number measured in the working tree produces a commit that is broken in
isolation (this nearly happened in Task 12: ruling R3's `(4, 2, 8, 44)` is the
working-tree number; the committed file needed `(4, 2, 8, 42)`).

The method, used in Tasks 12 and 18:

```bash
# 1. export HEAD clean, apply the SAME edit script from its own baseline
rm -rf /tmp/base && mkdir -p /tmp/base
git archive HEAD | tar -x -C /tmp/base
python3 /tmp/apply.py /tmp/base <its baseline numbers>

# 2. stage the HEAD-based content WITHOUT touching the working tree
blob=$(git hash-object -w /tmp/base/path/to/file)
git update-index --cacheinfo 100644,$blob,path/to/file

# 3. prove the commit is self-consistent, not merely green in a dirty tree
cd /tmp/base && $PROJ/.venv/bin/python -m pytest tests/the_affected_test.py -q
```

Files that were **clean** at HEAD need none of this — a plain `git add` is
correct, because worktree == HEAD + your edit.

### 6b · Regenerating the console client without swallowing the other feature

`Dashboard/tools/dump_openapi.py` and `gen.mjs` read whatever backend is in the
tree. Run in the working tree, they pull the in-flight feature into
`openapi.json`, `generated.ts` and `vocabularies.generated.ts` (measured:
`relationship_manager`, the `relationship` department, `lead_open_feed_days`,
`relationship_engagements`, `lead_cycles`, and 11 extra API paths). Generate
from a `git archive HEAD` export instead, with `Dashboard/node_modules`
symlinked in and the python shim on PATH.

**Also: the plan's Step 1 command is destructive.** It says
`dump_openapi.py > Dashboard/src/api/openapi.json`, but the tool writes both
artefacts itself and prints only a summary — that redirect truncates the
285 KB spec to a log line. Run it with no redirect.

**Line endings are per-file and `.gitattributes` marks these paths `-text`**, so
a newline flip is a real content change:
`openapi.json` and `vocabularies.generated.ts` are committed **CRLF**;
`generated.ts` and `constraints.generated.ts` are committed **LF**. Match each
file's own convention after regenerating or the diff explodes from ~355 lines
to ~22,000.

---

## 7 · What is known about the real documents

Measured, pinned by `tests/docx/test_golden_samples.py`. **If a run disagrees,
that is a finding to report, not a pin to edit.**

| Document | Client literal | Occurrences | Media | Sections | Tables | Index |
|---|---|---|---|---|---|---|
| `Essential Lab.docx` | `School Name` | 7 | 14 | 5 | 3 | none |
| `Innovation Lab Template.docx` | `School Name` | 7 | 14 | 6 | 2 | none |
| `School_YuviPep 360_2 1.docx` | `School School` | 9 | 33 | 23 | 18 | **static** |
| `School_YuviPep 360 EmpowerED_New_compressed.docx` | `School Name` | 14 | 32 | 20 | 14 | none |

**`Paragraph.runs` is unusable here.** It omits runs nested in `w:hyperlink`
and never descends into text boxes; a `.runs` walk found 4 of 7, 1 of 7, 1 of 9
and 2 of 14 occurrences — and a verification built on the same walk agreed with
itself and reported success. Everything goes through `app/services/docx/text.py`,
which works on `w:t` nodes. **Never reintroduce `.runs`.** Live proof from Task
17: on the real cover page the client name sits in the **footer**.

**Word fragments runs arbitrarily.** `School Name` is commonly three runs.

**No document has a live TOC field.** The static index in
`School_YuviPep 360_2 1.docx` is a `w:sdt` wrapping 32 TOC1/2/3 paragraphs with
page numbers as literal text, so the two-pass LibreOffice refresh is the primary
mechanism. When mapping headings to pages, **exclude the pages the index itself
occupies** — measured, `Investment and Deliverables` matches pages `[2, 27]`;
2 is the index, 27 is the answer.

---

## 8 · Open items to settle before merge

**Read items 0 and 0a first — they are the two the plan itself asked for and
did not get.**

**0 · Nobody has looked at a generated proposal.** The plan's final
verification asks a human to upload `Essential Lab.docx`, mark it up, generate
a real proposal from the app and confirm by eye that the cover art, the images,
the headers and footers survived, that `School Name` appears nowhere, that the
price table matches the rate card, and that the greeting reads like a person
wrote it — then repeat with `School_YuviPep 360_2 1.docx` and check the
contents-page numbers. Task 17 verified all of that programmatically (33 media
parts carried into a 29-page PDF, 0 leftover literals, index intact) and sent
the PDF to the owner, but no visual confirmation was ever recorded.

**0a · No screen of this feature has been rendered in a browser.** Across
Tasks 19, 20 and 21: `tsc`, 688 Vitest tests and a real Vite build all pass,
but this suite has no jsdom component tests by design (D11) and no dev server
was started. Unexercised end to end: the upload flow, the suggestion round trip
(it costs a model call), the preview PDF and its pop-up-blocker fallback, the
lazy image loading, the modal focus trap, and the leave-without-saving guard.

**0b · There is one way into the editor, and it is a dead end on return.**
`list_proposal_templates` returns `id/name/version/kind/is_current/body_md` and
no `doc_id`, so `#/item/6/doc/:docId` is reachable only from the upload banner.
An administrator who uploads a document, leaves, and comes back cannot reach
its editor at all. Fixing it means adding `doc_id` to that read plus a
regenerated client — a backend change, deliberately not made inside Tasks 20–21.
It is the difference between an editor and a one-shot wizard.

**0c · Two guards need an owner decision, neither touched.**
`scripts/check_docs_in_sync.py:212` hardcodes `"55 model classes"` inside its
tables pattern; the README now truthfully says 56, so that check fails and
writing 55 to green it would put a known-false number in the file this project
calls the authority. Line 213's route counter is separately broken — it imports
`app.main`, counts `APIRoute` objects and returns **2** at every revision tried
including `aa49e80`, so it has never worked here. And `gen:check` fails against
a fresh checkout for a third reason that is **not drift**: the committed
`openapi.json` is CRLF (`.gitattributes` marks it `-text`), `dump_openapi.py`
on Linux writes LF, and `gen.mjs` compares bytes. Measured: both specs carry
133 paths and are **identical ignoring line endings**.

**0d · The Data Model Word document is stale and is not in the repository.**
`../YuviPep_Data_Model.docx` has no section for `proposal_template_docs` and
does not carry `proposal_templates.kind`, `proposals.filled_json` or
`proposals.template_kind`. `check_docs_in_sync.py` reports all three.


1. **The scrubber rejects ordinary prose.** `fill_scrub._MONEY_MARKERS`
   contains the bare substring `"rs"` and `_PRICE_WORDS` contains `"each"`,
   both matched inside words. Measured, 5 of 6 realistic sentences were
   rejected: "co**vers** 240 students", "500 tea**chers**", "1,200
   lear**ners**", "10,000 **hours**", "r**each** 450 children". Each rejection
   costs a retry and can end in a blank placeholder. **Not fixed** because the
   module's own docstring makes false rejections an explicit accepted trade —
   this is the owner's tuning call. Fix if wanted: match on word boundaries.
2. **`proposal_service._NUMBER_RE` (line 458) cannot read Indian digit
   grouping**, so `narrative_price_drift` misreads `Rs 8,50,000` as `50,000`
   for **markdown** proposals. Pre-existing. Left alone deliberately: the
   markdown path must stay byte-identical. `fill_scrub` has the fixed pattern.
3. **There is no migration tool.** `create_all` makes missing tables but never
   adds columns. Three columns were added to the dev DB by hand on 4 Sep
   (`proposal_templates.kind`, `proposals.filled_json`,
   `proposals.template_kind`); backup at
   `data/salesplatform.db.bak-docx-20260904`. **Any other environment running
   this branch needs the same three.** Decide on Alembic or a documented ALTER
   script — Task 23 is the place to record it.
4. **Nothing has been seen in a browser.** `tsc` and `vitest` pass, but this
   suite has no jsdom component tests for these screens and no dev server was
   started. The Task 19 upload flow, mode switch and banners are unexercised
   end to end.
5. **The Task 17 Step 5 human check is outstanding.** The filled real document
   converts correctly (29 pages, 4.4 MB, all 33 images, index intact, literal
   gone) and the PDF was sent to the owner, but nobody has confirmed visually
   that the branding looks right. Neither machine has poppler.
6. `gen:check` fails against the **working tree** and always did — the tree's
   backend carries in-flight routes deliberately absent from the committed
   spec. It **passes** against a fresh checkout of this branch, which it did
   not before Task 18. Whoever merges the in-flight feature must run `gen:api`.

---

## 9 · How to continue

**There is no next task — the plan is finished.** What is left is §8, and the
first four items there are the ones to settle before this merges.

The ledger,
`.superpowers/sdd/2026-09-03-docx-proposal-templates-plan/progress.md`, is the
authority on what happened. It records every measurement and roughly **twenty
defects found in the plan's own reference code and tests** across Tasks 4–23 —
a threshold that made a function unable to pass its own test, an ordering that
wiped the document it had just written, a guard that accepted a single space as
a token literal, table XML that Word would call corrupt, an inline image
thumbnail that could not be addressed because block ids and media names do not
intersect, and a column mapping the plan labelled "leave as is" that in fact
empties the column. **Run the code before trusting a document, this one
included.**

### If you are picking up the remaining work

- **Before merging**, settle §8 items 0–0d, and note that whoever merges the
  in-flight `feature/pre-sales-cold-calling` work must run `npm run gen:api`
  themselves: `gen:check` fails against the working tree by design, because the
  tree's backend carries routes deliberately absent from the committed spec.
- **The pre-existing dirty tree still matters.** `git status --porcelain | wc -l`
  must read **89**. Six paths were both pre-existing-dirty and touched by this
  branch — `app/core/reset_taxonomy.py`, `app/models/__init__.py`,
  `requirements.txt`, `tests/test_reset_taxonomy.py`, `BACKEND_README.md` and
  `Dashboard/READMEs/08_PROGRESS_AND_HANDOFF.md`. Each was committed as HEAD +
  the edit via §6a, and each was audited: zero in-flight content in any of them.
- **§6a is not optional and it fired twice more.** Task 23 measured the
  README's counts in the working tree first and got 58 tables and 22
  permissions — the other feature's numbers. The committed values are the HEAD
  ones: 56 tables, 157 routes. Task 23 also hit a file that is **CRLF on disk
  while its HEAD blob is LF**, which `git status` reports as clean and which
  makes every multi-line anchor fail to match.
