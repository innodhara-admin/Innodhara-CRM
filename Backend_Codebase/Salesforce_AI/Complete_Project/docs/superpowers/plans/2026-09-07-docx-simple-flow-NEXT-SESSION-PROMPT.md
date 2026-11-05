# The prompt for the next session

Written 8 September 2026, at the end of the session that built A1-A4, B1-B3
and C1. Paste everything between the rules.

---

Continue implementing the DOCX simple flow on the YuviPep backend, starting at
Task C2. Phases A and B are complete; C1 is complete.

THE CODE IS ON A VM, NOT THIS MACHINE.
  path: /home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project
  ssh:  telaverge@172.16.10.55  password tela@123   (the OVPN tunnel must be up)
There are no SSH keys, and sshpass/plink are not installed. Local Python has
paramiko. Create these two helpers in your scratchpad FIRST - they already
carry the retries and encoding hardening that earlier sessions had to learn:

--- rc.py (run a remote command; command text on STDIN only) ---
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

--- put.py (upload one file, with retries) ---
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

Six rules that apply from your very first command:
1. Always send remote commands on stdin via a  <<'REMOTE'  heredoc, never as
   argv - Git Bash silently rewrites /home/... into a Windows path.
2. Put MSYS_NO_PATHCONV=1 in front of  python put.py  for the same reason.
3. Write Python locally with the Write tool and upload it; do NOT compose it
   in a local  cat > f <<'EOF'  heredoc (apostrophes and backslash escapes
   both break it), and keep non-ASCII out of inline remote commands.
4. Never leave a helper script in the project root - use /tmp on the VM.
5. Some files are CRLF on disk while their HEAD blob is LF. Normalise to LF,
   patch, restore the original convention. This bites hardest on
   Dashboard/src/api/openapi.json and vocabularies.generated.ts, which are
   committed CRLF while generated.ts and constraints.generated.ts are LF.
6. When you edit by script, GUARD EVERY EDIT WITH A MARKER ALREADY IN THE FILE
   and make the script idempotent. An unguarded numeric increment run twice
   double-counts; that cost a debugging round in A4.

READ FIRST, in this order:
  docs/superpowers/plans/2026-09-07-docx-simple-flow-plan.md
      -> READ SECTION 0 (Amendments) FIRST. It is authoritative where it
         contradicts the rest of the plan, and it lists six places where the
         plan as written is now stale. Then §2 (measured), §4 (D1-D16),
         §5 (data model), §7 (the fill conversation), §9 (the tasks).
  .superpowers/sdd/2026-09-07-docx-simple-flow-plan/progress.md
      -> the execution ledger. One or more entries per task, with every
         measurement, ruling and defect. This is the source of truth for what
         happened. It is gitignored, so it exists only in the working tree.
  docs/DOCX_TEMPLATES_HANDOFF.md
      -> §3 is SUPERSEDED and says so. §4 (reaching the code), §5 (the
         environment and the console toolchain) and §6 (the two techniques)
         are still accurate and still required.

STATE: branch feature/docx-proposal-templates, HEAD 1b2f2f2, 34 commits from
aa49e80. Nine of them are the simple flow:
  1b2f2f2 fix(docx): a bare word like <price> is a tag, not pasted HTML
  d183436 feat(ai): the whole client, assembled once, for the fill pass  (C1)
  6a90d61 feat(console): upload a Word document the assistant fills      (B3)
  d52daeb feat(jobs): read a template's images after the upload returned (B2)
  e8f0ffe feat(api): upload a Word document whose tags the assistant fills (B1)
  c017e7e feat(models): the simple-flow fill session table               (A4)
  4fc8ed9 feat(docx): the occurrence-addressed writer                    (A3)
  650e5f8 feat(docx): the paragraph walk, and the label                  (A2)
  99db33b feat(docx): the tag grammar and occurrence scanner             (A1)

TEST STATE, measured at 1b2f2f2:
  Backend, HEAD in isolation (git archive HEAD export): 517 passed, 48 skipped,
    0 failed. Note 48 skips: the golden tests need data/samples and
    data/salesplatform.db, both gitignored.
  Backend, working tree: 696 passed / 1 failed. THE ONE FAILURE IS
    tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first
    - pre-existing, belongs to the unrelated in-flight feature in the tree, and
    must NOT be fixed. Depending on the hour you may instead see 5 failures:
    the extra four are tests/test_what_is_late.py, which is time-of-day
    sensitive. Confirm they are the only ones and move on.
  tests/docx: 293 passed.
  Console: 707 passed / 20 files, tsc --noEmit exit 0.
  Android: unchanged since the complex flow; E1 expects to confirm no change.

THE WORKING TREE IS DELIBERATELY DIRTY: 91 paths, and it must read 91 before
and after every commit. Almost all of it is unrelated in-flight
feature-pre-sales-cold-calling work; five of them are Dashboard/dist build
artefacts, which are build output and must NEVER be committed. Never git add -A.
Stage only the paths each task names, and check the count after every commit.

HANDOVER §6a applies to a file that is ALREADY dirty: the committed content
must be HEAD + your edit, NOT the working tree. Write the edit as an idempotent
script, run it on the working tree AND on a `git archive HEAD` export, then
stage the export's blobs with `git hash-object -w` + `git update-index
--cacheinfo` so the working tree is never touched. A4 did this for
app/models/__init__.py, app/core/reset_taxonomy.py and
tests/test_reset_taxonomy.py, where HEAD said (4, 2, 8, 42)/56 tables and the
working tree said (4, 2, 8, 44)/58 - writing either number literally would
have produced a commit broken in the other tree. app/core/constants.py,
app/jobs/pipelines.py, app/jobs/scheduler.py and Dashboard/src/session/store.ts
are also already dirty; check before you edit anything.

THE RUNNING BACKEND: port 8010, NOT the 8000 in .env - port 8000 is held by an
unrelated RAG chatbot. Restart it as
  PORT=8010 setsid nohup .venv/bin/python run.py > /tmp/backend.log 2>&1 &
and remember a restart is what makes create_all build a new table. Nothing has
been deployed: the running process predates proposal_fill_sessions and the
served console bundle in Dashboard/dist is dated 4 September, older than every
Phase B change.

CONSOLE TOOLCHAIN (needed only if you touch Dashboard):
  export PATH="/home/telaverge/.nvm/versions/node/v22.11.0/bin:$PATH"
  /usr/bin/node is v12 and cannot parse ?? , so gen.mjs dies without this.
  gen.mjs spawns a bare python, which Ubuntu lacks - recreate the shim:
    mkdir -p /tmp/shim
    printf '#!/bin/sh\nexec $PROJ/.venv/bin/python "$@"\n' > /tmp/shim/python
    chmod +x /tmp/shim/python ; export PATH="/tmp/shim:$PATH"
  Call tools through node directly:
    node node_modules/typescript/bin/tsc --noEmit
    node node_modules/vitest/vitest.mjs run
    node node_modules/vite/bin/vite.js build --outDir /tmp/throwaway --emptyOutDir
  Regenerate the client ONLY from a `git archive HEAD` export with
  Dashboard/node_modules symlinked in - never from the working tree, which
  pulls the in-flight feature into openapi.json. B3 did this; §6b is the method.

WHAT ALREADY EXISTS, and what C2 must build on:

  app/services/docx/tags.py
    scan(docx_bytes) -> list[Occurrence] frozen dataclasses with .as_dict().
    Fields: tag_id, kind (semantic|ask|ask_calculate), raw, default, ordinal,
    start, end, context, duplicate_of. Identity is per OCCURRENCE, never per
    literal: <ask:1 Unit> appears four times in the owner's template and is
    four different questions. context is the table row label joined to the
    text immediately before the tag, which is what separates them.

  app/services/docx/text.py
    walk_paragraphs(doc) - the walk an ordinal indexes into.
    label_for(doc, ordinal) -> str | None - display only, may be None, and
    nothing in this feature calls outline.resolve.

  app/services/docx/tagfill.py
    apply_tags(docx_bytes, occurrences, values) -> {"docx", "written",
    "skipped"}. Right-to-left within a paragraph; re-reads the live text and
    REFUSES a write whose tag has moved. NOTHING RAISES - refusals are
    reported. SKIP_NO_VALUE / SKIP_STALE / SKIP_NO_SUCH_PARAGRAPH.
    A tag_id absent from `values` leaves its tag in the document; a tag_id
    resolved to "" removes it. J2 MUST refuse to ship a document with a
    non-empty `skipped`, and must call index.refresh_static itself for a
    static contents page, exactly as docx_proposal_service.py:102 does.

  app/models/proposal_fill.py
    ProposalFillSession + FillStatus (gathering/asking/reviewing/ready/built/
    abandoned). One table, no new columns anywhere.

  app/services/client_dossier.py
    build(db, ctx, lead_id, program_id) -> dict with 24 keys, every section
    whole, ai_decisions and progress_events excluded, fields listed explicitly
    so no password hash or embedding can leak. `omitted` records anything the
    60,000-character ceiling dropped. The template's text and OCR are
    deliberately NOT in it - C2's signature takes document_text separately.

  app/services/proposal_service.py
    Refuses to build from a docx_simple template with a message telling the
    salesperson to ask Jarvis. J1 MUST REPLACE that guard with the fill
    conversation, not add a branch beside it. It exists because B1 measured
    that without it POST /proposals returned 200 and a draft containing
    "<ask:6 Units>".

  The model layer, for C2: app/ai/docx_suggest.py is the closest existing
  example - get_model_layer().generate_json(..., tier=TIER_STRONG,
  json_schema=...), with _validate() checking the model's answer against the
  data it was given. Its tests stub with
  monkeypatch.setattr(module, "get_model_layer", lambda: layer).
  Reuse that shape; C2's task text says explicitly to apply the same
  discipline.

DO NOT USE SUBAGENTS. Work sequentially and inline. Per task: read the task in
the plan, write the tests, watch them fail for the right reason, implement, run
the task's tests then both full suites, MUTATION-CHECK the suite (change the
behaviour the task is about and prove the right test fails - this caught real
gaps in every task so far), review your own work, commit only the named paths,
verify the commit in a `git archive HEAD` export, append what happened to the
ledger, then tell the owner the result.

Numbers in the plan are measurements. If a run disagrees with one, STOP AND
INVESTIGATE, then tell the owner - do not edit the pin to make a test green.
Three of the plan's numbers have already been corrected this way and are
recorded in §0; two of them were the plan being right about something it
measured and the build measuring something larger.

REMAINING TASKS: C2, C3, J1, J2, J3, E1, E2.

  C2 is next: app/ai/docx_tagfill.py, resolve_tags and answer_round. Its
  proof list in §9 is unusually specific - eight cases including a 0.95 fill
  with no citation downgraded to a question (D14), a 0.95 fill citing a fact
  absent from the dossier likewise downgraded, and an ask at confidence 1.0
  that STILL becomes a question (D4). Read D14 and D15 before writing.

TWO THINGS OUTSTANDING THAT ARE NOT YOURS TO DECIDE:

  1. J3 NEEDS A FIXTURE THAT DOES NOT EXIST. Only
     "Innovation Lab Template (tagged).docx" is tagged. J3 needs a tagged
     School_YuviPep 360_2 1.docx. Ask the owner for it when you reach J3, and
     build C2, C3, J1 and J2 without it.
  2. D16's console half belongs to no task. §6 says the console should check
     at upload time whether the offering has a current rate card and offer to
     publish one there. It is in no task's file list and is not built. Raise
     it with the owner; do not fold it into another task silently.

EVERY OTHER DESIGN QUESTION IS ANSWERED. §10 records all eight, decided by the
owner on 7 September, and §0 records the amendments made since. Nothing is
waiting on a decision.
