# The MOU pipeline is BUILT. Your job is to fix what testing finds.

The fifteen-task plan is complete: 62 commits from `aa49e80` on branch
`feature/docx-proposal-templates`, HEAD `ef672c5`. **You are not building
features. The owner is testing, and will report symptoms.** Read this whole
file before your first command.

---

## THE CODE IS ON A VM, NOT THIS MACHINE

```
path: /home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project
ssh:  telaverge@172.16.10.55   password tela@123   (the OVPN tunnel must be up)
sudo: the same password, with `sudo -S`
```

If `ping 172.16.10.55` times out but the public URL below answers, **the VM is
fine and your tunnel is down** — ask the owner to bring the OVPN up. That
happened once mid-session; nothing was broken.

There are no SSH keys and no sshpass/plink. Local Python has paramiko. Create
`rc.py`, `put.py` and `get.py` in your scratchpad FIRST.

**--- rc.py (run a remote command; command text on STDIN only) ---**

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

**--- put.py (upload one file, with retries) ---**

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

`get.py` is the same shape with `s.get`. Write it too — you will want to pull
a built `.docx` down and look at it.

Python on the VM is `.venv/bin/python`. **There is no bare `python` on PATH.**

---

## TWELVE RULES, EVERY ONE PAID FOR

1. **Remote commands go on a `<<'REMOTE'` heredoc, never as argv.** Git Bash
   silently rewrites `/home/...` into a Windows path.
2. **`MSYS_NO_PATHCONV=1` in front of `put.py`/`get.py`**, and pass LOCAL paths
   in Windows form (`C:/Users/...`), never `/c/Users/...`. `$(pwd)` returns a
   POSIX path and will fail.
3. **NEVER patch a Python string literal through a bash heredoc.** `\n` inside
   `<<'PY'` becomes a real newline and breaks the file. This bit SIX times in
   one session. Write the whole file with the Write tool, or use the Edit tool.
   No exceptions — you will think your case is different; it is not.
4. **Never leave a helper script in the project root** — use `/tmp` on the VM.
5. **Guard every scripted edit with a marker that is a SINGLE LINE, of CODE not
   prose, and UNIQUE to that edit.** Verify by running twice and requiring
   every line to say "already applied" with exit 0. Two failure modes, both
   real: an edit that *skips itself and reports success*, and an edit whose
   sentinel does not match its own output so it **re-applies every run** — that
   one inserted the same block three times.
6. **Match a whole block, and refuse to guess.** Check `text.count(old) == 1`
   and raise otherwise. A span that ends mid-block absorbs the following lines
   into an `if` above them.
7. **Never upload a local copy of a file you patched on the VM.** Patch on the
   VM only, or pull it down and compare sha256 first.
8. **Never kill the backend PID.** See DEPLOYING.
9. **Copy a live SQLite database THROUGH SQLITE**, never with `cp`. It is in
   WAL mode; a file copy silently drops what is not checkpointed (measured: 17
   rows where the database had 18).
10. **Mutation-check every fix**, and treat the harness as suspect:
    - purge `__pycache__` before every run and `os.utime` after every restore —
      pytest's cache is keyed on (mtime, size);
    - a mutant that cannot import is **ERROR, not FAILED**: it proves nothing;
    - parse test results as XML, never with a regex — a non-greedy
      `<testcase>(.*?)</testcase>` starting on a self-closing tag blames the
      next test's failure on this one (0/8 killed, all lies);
    - a mutation too SMALL to remove what the test checks reports a gap that
      is not there.
11. **A stateful fake behind a factory lambda is rebuilt on every call.**
    `monkeypatch.setattr(mod, "get_model_layer", lambda: Layer(tags))` makes a
    NEW layer per call, so a layer that counts its turns always thinks it is on
    turn one. Build it once: `layer = Layer(tags); lambda: layer`.
12. **Never hand-copy a span into a patch or a spec.** Read the exact bytes out
    of the file. A console listing truncated at 48 characters produced two
    wrong keys and a fill that never terminated.

---

## THE WORKING TREE IS DELIBERATELY DIRTY AT 91 PATHS

It must read **91 before and after every commit**. Almost all of it is
unrelated in-flight `feature-pre-sales-cold-calling` work; five paths are
`Dashboard/dist` build artefacts which are build output and **must never be
committed**. Never `git add -A`. Stage only the paths your fix names.

`docs/` is **untracked but not ignored** and collapses to one `?? docs/` line.
**Never `git add` anything under `docs/`** — it would take the count to 99.

### Handover §6a — a file that is ALREADY dirty

The committed content must be **HEAD + your edit**, not the working tree.
Write the edit as an idempotent script, run it on the working tree **and** on a
`git archive HEAD` export, then stage the export's blob:

```bash
sha=$(git hash-object -w /tmp/export/path/to/file)
git update-index --cacheinfo "100644,$sha,path/to/file"
```

Then **verify with `cmp`, not a pipeline**: `diff a b | head -4 && echo same`
reports "same" whatever diff found, because `head` exits 0. The staged blob
must differ from HEAD (your edit landed) and differ from the tree (you did not
commit the in-flight work).

Dirty files you are likely to touch: `app/main.py`, `app/api/leads.py`,
`BACKEND_README.md`, `Android_Planning_Readmes/01_BACKEND_CONTRACT.md`,
`app/core/reset_taxonomy.py`, `tests/test_reset_taxonomy.py`,
`app/services/storage.py`, `app/models/__init__.py`.

### Line endings

**A `.gitattributes` decides them, and the working copy's convention is not the
blob's.** Staging a CRLF file prints "CRLF will be replaced by LF" — that is
usually CORRECT, not a disaster: check `git show HEAD:<path>` before believing
it. Rule: **preserve each working file's own endings when you edit it**, and
let git normalise. In the Android project (no git) the rule is the same, and
LF dominates 151 files to 36 — "everything is CRLF" is false there.

---

## STATE, measured 2026-09-11

```
branch feature/docx-proposal-templates, HEAD ef672c5, 62 commits from aa49e80
dirty 91

Backend, HEAD in isolation:  812 passed, 66 skipped
Backend, working tree:       1009 passed / 1 failed
tests/docx:                  606 passed
Console:                     714 passed / 20 files, tsc --noEmit exit 0
Android JVM:                 77 passed / 0 failures
```

**MEASURE THE BASELINE YOURSELF BEFORE YOU START** and use your own number.

**THE ONE PERMITTED FAILURE** is
`tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first`
— pre-existing, unrelated in-flight work, **MUST NOT BE FIXED**. Depending on
the hour you may see up to four more, all time-of-day sensitive:
`tests/test_what_is_late.py` (3–4) and
`tests/test_demos_followups.py::test_followup_complete_schedules_next`.
Confirm they are the only ones and move on.

The 66 skips are the opt-in golden suites, which need `data/samples` and
`data/salesplatform.db` — both gitignored, both present on the VM.

---

## READ THESE, IN THIS ORDER

Everything below is **committed** and is the source of truth. The plan and spec
under `docs/` are uncommitted but present on the VM.

1. **`Dashboard/READMEs/05_DECISIONS.md`, D38–D45** — WHY the system is shaped
   the way it is. Read this before changing anything; most "bugs" you will be
   tempted to fix are decisions.
2. **`Dashboard/READMEs/09_BACKEND_CHANGES.md` §1c** — WHAT landed, and a
   **file map naming which file owns which behaviour.** Start here when you
   have a symptom and need a file.
3. **`Android_Planning_Readmes/01_BACKEND_CONTRACT.md` §1.8a** — the routes and
   the app side.
4. **`.superpowers/sdd/2026-09-09-mou-pipeline-plan/progress.md`** — 1,865
   lines, gitignored, exists only in the working tree. Every measurement,
   ruling and defect, task by task. **The source of truth for what actually
   happened**, and it disagrees with the plan in places.
5. `docs/superpowers/plans/2026-09-09-mou-pipeline-plan.md` §0 amendments A–R,
   and `docs/superpowers/specs/2026-09-09-mou-pipeline-design.md` §12
   corrections. Both are authoritative over the rest of their own document.

---

## HOW THE MOU SYSTEM WORKS, END TO END

**An MOU is a contract, signed AFTER a proposal is accepted.** It reuses the
simple-flow proposal engine whole — same tags, same dossier, same review — and
is kept out of the sales pipeline entirely.

```
  admin uploads a tagged .docx          POST /admin/programs/{id}/proposal-templates/docx
    document_type=mou, flow=simple        -> kind "mou_simple", plan_json holds every tag
             |
  "create the MOU for IBC"              agent tool create_mou
             |                            -> proposal_fill_service.open_session(document_type="mou")
             |                            -> resolve pass fills SEMANTIC tags it can cite (D14)
             |                            -> relation pass asks WHICH tags multiply (D42, MOUs only)
             |
  rounds of questions                   answer_mou_questions -> apply_answers
    six per round, grouped by section     -> the model sees EVERY outstanding question (D8)
             |                            -> nine rounds on the owner's real contract
             |
  the D13 review                        confirm_mou_values
    every value, its origin, warnings     -> a standing arithmetic mismatch is refused ONCE
             |
  the build                             proposal_fill_service.build -> _write_mou
    apply_tags, refuse if skipped         -> refresh_static if the contents page is static
    -> properties.fill (D45)              -> THEN the properties, because LibreOffice rewrites all
    -> MouDocument + MouRevision          -> PDF, non-fatal
             |
  read it back                          GET /mous/{id}, GET /leads/{id}.mous[]
  correct it                            correct_mou -> same row, new files, pdf_path cleared first
                                          -> REFUSED once sent
```

**The five things most likely to be misunderstood:**

- **`mou_documents` has no `total_amount`, `line_items`, `pricing_table_id` or
  `project_id`.** Absent, not unused. If a symptom is "the MOU has no total",
  that is D38 and it is correct.
- **A tag cannot reach document PROPERTIES** — `scan` and `apply_tags` walk
  paragraphs. `properties.py` fills them separately, AFTER `refresh_static`.
- **The collapse key is `(raw, context)`, never `raw`** — one literal is often
  several different questions.
- **`open_questions(limit=None)` must stay uncollapsed** — `apply_answers`
  hands it to the model, and narrowing it strands occurrences for ever.
- **The wrong tool must be harmless.** `create_mou` on an open fill RETURNS
  `{already_open, still_to_answer, what_to_do}`. A prompt is advice; a tool
  result is fact.

---

## WHEN THE OWNER REPORTS A SYMPTOM

**Use `superpowers:systematic-debugging`. Reproduce before you fix.**

| Symptom | Look first at |
|---|---|
| A client's name / old figure survives in a built MOU | `properties.py` and **count over the WHOLE PACKAGE, not the paragraph walk** — `raw_count` only walks `word/*.xml`. Use `tests/docx/test_mou_golden.py::_package_count`. |
| The document still shows `<ask:...>` | `apply_tags` reported `skipped`; the build refuses. Read the message — it names the tags. |
| The assistant loops, asking the same thing | The loop-breaker in `_open_fill`, and `fill_tools.TOOLS`. Check `what_to_do` names the right tool. |
| It asks a question as `<ask:75>` | **KNOWN.** Four asks at ordinals 154–157 have no context label. Owner's call; it changes `tags.py` and affects proposals too. |
| "Error! Reference source not found." in the MOU | **KNOWN, and the owner's to fix in Word** — ordinals 209, 232, 236 in their source document. No tag can repair them. |
| A contract appears in the sales pipeline | D38. Check `GET /leads/{id}` keeps `mous` separate and that nothing wrote a `Proposal` row. |
| An arithmetic warning is wrong or missing | `mou_arithmetic.py`. It refuses to guess on ranges and non-amounts, deliberately. |
| The console shows the wrong document type | `Dashboard/src/screens/docx/flow.ts` — `documentTypeOf` reads a missing key as `proposal`. |
| The app card is blank | `filled_json`'s eight keys. Renaming one blanks it; `ContractTest` guards it. |
| A correction is refused | Once `status == "sent"` OR `sent_at` is set, by design. |

**Per fix:** reproduce → write the failing test → watch it fail *for the right
reason* → fix → run the task's tests, then `tests/docx`, then the full backend
→ mutation-check → review your own code with the tests green → commit only the
named paths → verify in a `git archive HEAD` export → append to the ledger →
tell the owner.

---

## DEPLOYING

Backend on **:8010** (NOT the 8000 in `.env` — that is an unrelated RAG
chatbot). nginx on 127.0.0.1:8080; ngrok fronts nginx at
**https://noninfluential-lamonica-unobservantly.ngrok-free.dev**

```bash
printf '%s\n' 'tela@123' | sudo -S -p '' systemctl restart salesforce-app-restart.service
```

The restart script is at `Backend_Codebase/restart_script/` — **one level
ABOVE the project directory.** Never kill the PID: the teardown takes ngrok
with it and leaves the public URL down. An hourly healthcheck timer restarts
the service after three failures. A restart is what makes `create_all` build a
new table.

**Verify over the PUBLIC url, not just locally.** The console lives at
`/dashboard/`, not `/` (`/` is the API status JSON).

**The console bundle contains `127.0.0.1:8000` and that is CORRECT** — it is
the fallback for pages not served from `/dashboard`. Do not "fix" it.

Rebuild the console **from the WORKING TREE**, never a HEAD export — the tree
carries `session/baseUrl.ts`:

```bash
export PATH="/home/telaverge/.nvm/versions/node/v22.11.0/bin:$PATH"
mkdir -p /tmp/shim
printf '#!/bin/sh\nexec $PROJ/.venv/bin/python "$@"\n' > /tmp/shim/python
chmod +x /tmp/shim/python; export PATH="/tmp/shim:$PATH"
cd Dashboard && node node_modules/typescript/bin/tsc --noEmit \
  && node node_modules/vitest/vitest.mjs run \
  && node node_modules/vite/bin/vite.js build
```

`Dashboard/dist` is build output and is **NEVER committed**.

---

## THE ANDROID APP

`C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI` — on the machine
you are running on, **NOT the VM**, and **NOT a git repository**. Back up every
file before editing; this session's backups are in `.r2-backup/` and the owner
may delete them.

```bash
JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew :app:testOrgDebugUnitTest
```
77 passing. From Windows Python use `gradlew.bat`, not `./gradlew`. There is no
Robolectric, so **anything left in a fragment cannot be tested** — pure
decisions go in `MouLines`.

**No APK has ever been built with this work in it.** Every APK on disk predates
it. `./gradlew :app:assembleOrgDebug` if the owner asks.

---

## WHAT IS NOT BUILT, AND IS NOT A BUG

- **No MOU detail screen.** The client screen lists a contract; tapping it goes
  nowhere. `MouLines.sourceLabel` and `heading` are written and tested for that
  card and are currently exercised only by tests.
- **No send path for an MOU.** `MouStatus.SENT` and `sent_at` exist and the
  correction path respects them, but nothing sets them yet.
- **Properties are filled for MOUs only.** The proposal flow has the same
  latent defect if a proposal template ever carries a client in its
  properties. Reported, not fixed — it is the owner's call.

## OPEN QUESTIONS FOR THE OWNER — ask before assuming

- The three broken Word fields (ordinals 209, 232, 236) — theirs to fix.
- Four questions asked as raw tag text (ordinals 154–157), and one context
  label reading "MoU for MoU for - MoU for". Same class as the
  numbered-row-label defect they had fixed in the shared scanner.
- `word/_rels/settings.xml.rels` still points at a staff member's own machine,
  leaking a name and folder structure to every client. Strip it or leave it?
- Should the tag grammar learn "ask me" as a synonym for `ask:`? The owner
  writes asks in natural language; `TAG_RE` reads that as SEMANTIC.
- `scripts/migrations/2026-09-08_optional_rate_card.py`'s backup was taken with
  `shutil.copyfile` and is missing the WAL. It should not be trusted as a
  restore point.
- Should MOU files live in their own storage category? They are currently under
  `CATEGORY_PROPOSALS`.

---

## FINALLY

The owner tests in the real app, on a phone, through the ngrok URL, and finds
things a green suite does not — **three of the simple flow's defects came that
way and none from the suite.** Nothing in this pipeline has been through the
app on a phone yet.

Numbers in any document are measurements. **If a run disagrees, STOP AND
INVESTIGATE, then tell the owner** — do not edit the pin to make a test green.
Deploy after each meaningful change and say plainly what you verified yourself
and what still needs their eyes.
