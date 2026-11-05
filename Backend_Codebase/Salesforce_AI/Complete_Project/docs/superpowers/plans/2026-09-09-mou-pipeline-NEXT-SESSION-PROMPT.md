# Continue building the MOU pipeline on the YuviPep backend.

THE CODE IS ON A VM, NOT THIS MACHINE.
  path: /home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project
  ssh:  telaverge@172.16.10.55   password tela@123   (the OVPN tunnel must be up)
  sudo: the same password works with `sudo -S`; you need it to restart the service.
There are no SSH keys and sshpass/plink are not installed. Local Python has
paramiko. Create these two helpers in your scratchpad FIRST.

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

(A `get.py` that downloads is worth writing too — same shape, `s.get`.)

TEN RULES THAT APPLY FROM YOUR VERY FIRST COMMAND
1. Always send remote commands on stdin via a  <<'REMOTE'  heredoc, never as
   argv — Git Bash silently rewrites /home/... into a Windows path.
2. Put MSYS_NO_PATHCONV=1 in front of  python put.py  for the same reason, and
   pass LOCAL paths in Windows form (C:/Users/...), not /c/Users/... .
3. Write Python locally with the Write tool and upload it; do NOT compose it in
   a local  cat > f <<'EOF'  heredoc, and do NOT try to patch a script's own
   string literals with sed — backslash escapes will bite you. Rewrite the
   whole entry instead.
4. Never leave a helper script in the project root — use /tmp on the VM.
5. Some files are CRLF on disk while their HEAD blob is LF. Normalise to LF,
   patch, restore. Dashboard/READMEs/09_BACKEND_CHANGES.md and
   Dashboard/src/api/openapi.json are the ones that bite.
6. GUARD EVERY SCRIPTED EDIT WITH A MARKER, AND THE MARKER MUST BE A SINGLE
   LINE, OF CODE NOT PROSE, AND UNIQUE TO THE EDIT IT GUARDS. This went wrong
   three times this session: a prose sentinel that wrapped; a sentinel that
   already existed elsewhere in the file, so the edit SILENTLY SKIPPED ITSELF
   AND REPORTED SUCCESS; and a sentinel split by the comment its own edit
   inserted. Verify by running twice and requiring every line to say "already
   applied" with exit 0.
7. If you edit a file on the VM with a patch script, DO NOT later upload a
   local copy — you will clobber the edit. Compare sha256 first if unsure.
8. Never kill the backend PID directly. See DEPLOYING below.
9. A MUTATION HARNESS HAS TWO TRAPS AND BOTH COST TIME THIS SESSION:
   (a) pytest's assertion-rewrite cache is keyed on (mtime, size). shutil.move
       restores the backup's OLDER mtime, and consecutive mutations write the
       same file within one second — so a same-length mutation is served the
       PREVIOUS mutant's bytecode and reads as a survivor. It produced a test
       that passed alone and failed in the suite against a literal that was
       not in the file. Purge __pycache__ before every run AND os.utime after
       every restore.
   (b) A mutation that cannot be imported proves nothing: pytest reports it as
       ERROR, not FAILED. A harness counting only FAILED reads a NameError as
       a surviving mutant.
10. COPY A LIVE SQLITE DATABASE THROUGH SQLITE, never with cp. It is in WAL
   mode with a multi-megabyte -wal; a file copy silently drops everything not
   checkpointed (measured: 17 rows where the live database had 18). Use
   sqlite3.Connection.backup.

READ FIRST, in this order:
  docs/superpowers/plans/2026-09-09-mou-pipeline-plan.md
      -> §0 AMENDMENTS FIRST (A..P). It is authoritative where it contradicts
         the rest, and it records everything the plan got wrong. Then the task
         you are about to do.
  docs/superpowers/specs/2026-09-09-mou-pipeline-design.md
      -> §12 CORRECTIONS FIRST, then the rest. §12 is authoritative.
  .superpowers/sdd/2026-09-09-mou-pipeline-plan/progress.md
      -> the execution ledger, 830+ lines, gitignored so it exists only in the
         working tree. Every measurement, ruling and defect. THE SOURCE OF
         TRUTH for what actually happened, and it disagrees with the plan in
         places.
  docs/superpowers/plans/2026-09-09-mou-pipeline-design-input.md
      -> the MOU's measured shape. NOTE: its §2c is WRONG about YuviPep's own
         details (see plan §0 amendment J), and its round-count projection is
         withdrawn (§0 amendment L).
  docs/superpowers/plans/2026-09-07-docx-simple-flow-plan.md §0, §4, §5, §7
      -> the pipeline this one copies. Its D1-D16 are the decisions inherited.
  Dashboard/READMEs/05_DECISIONS.md D31-D37

STATE, measured 2026-09-10
  branch feature/docx-proposal-templates, HEAD 06e85d1, 53 commits from aa49e80.
  Backend, HEAD in isolation: 718 passed, 54 skipped. MEASURE IT YOURSELF
  BEFORE YOU START and use your own number as the baseline.
  Backend, working tree: 903 passed / 1 failed.
    THE ONE FAILURE IS
    tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first
    — pre-existing, unrelated in-flight work, MUST NOT BE FIXED. Depending on
    the hour you may see up to four more, all time-of-day sensitive:
    tests/test_what_is_late.py (3-4) and
    tests/test_demos_followups.py::test_followup_complete_schedules_next.
    Confirm they are the only ones and move on.
  tests/docx: 500 passed.
  Console: 707 passed / 20 files, tsc --noEmit exit 0 (UNTOUCHED this session).
  Android JVM: 61 passed (UNTOUCHED this session).
  The 54 skips are the opt-in golden suites, which need data/samples and
  data/salesplatform.db — both gitignored, both present on the VM.

THE WORKING TREE IS DELIBERATELY DIRTY: 91 paths, and it must read 91 before
and after every commit. Almost all of it is unrelated in-flight
feature-pre-sales-cold-calling work; five paths are Dashboard/dist build
artefacts, which are build output and must NEVER be committed. Never git add -A.
Stage only the paths each task names, and check the count after every commit.
NOTE: docs/ is UNTRACKED BUT NOT IGNORED and collapses to a single "?? docs/"
line — one of the 91. NEVER `git add` anything under docs/; it would expand
that line and take the count from 91 to 99. Plans and specs live there
uncommitted, which is what every previous plan in this project did.

HANDOVER §6a applies to a file that is ALREADY dirty: the committed content
must be HEAD + your edit, NOT the working tree. Write the edit as an idempotent
script, run it on the working tree AND on a `git archive HEAD` export, then
stage the export's blob with `git hash-object -w` + `git update-index
--cacheinfo`. It was needed for real in M2: HEAD asserted (4, 2, 8, 43) over 57
tables while the tree asserted (4, 2, 8, 45) over 59, and every count must be
DERIVED BY INCREMENT from whatever each tree already says, never written
literally. CHECK BEFORE YOU EDIT ANYTHING.

WHAT IS DONE, and where it lives
  M1 68241e4  proposal_templates.document_type; is_current is now current per
              (org, programme, document_type). FOUR call sites move together:
              the retire loop in docx_template_service, _promote_predecessor's
              call site in admin.py, proposal_service._current_template and
              proposal_fill_service._current. Migration
              scripts/migrations/2026-09-09_template_document_type.py, RUN on
              the live database (18 rows, all 'proposal').
  M2 ccfb1ed  app/models/mou.py — MouDocument. NO total_amount, line_items,
              pricing_table_id or project_id: absent, not merely unused, so no
              aggregate can pick an MOU up. WIPE, ordered after
              proposal_fill_sessions and before proposals.
  M3 d8d6581  proposal_fill_sessions.mou_id + .document_type. find_open,
              find_for_chat and find_correctable all filter on the type;
              find_correctable asks about mou_id for an MOU. Migration
              scripts/migrations/2026-09-09_fill_session_mou.py, RUN live.
              DEPLOYED: the restart built mou_documents (17 columns).
  U1 f2ead6a  kind "mou_simple"; an MOU may not be uploaded as the complex
              flow; count_ruled_blanks over the WHOLE walk; plan_summary gains
              ruled_blanks and document_type on both branches.
  -- d7dab1f  the MOU tagged from a SECOND real document the owner supplied.
     b2c74a4  the client's name removed from THIRTEEN metadata values.
  F1 ca2d1a5  open_questions collapses on (raw, context) and groups by section
              for MOUs only; section_labels; and tags.py's _row_label now
              skips a serial-number column (both flows).
  F2 06e85d1  app/services/mou_arithmetic.py (pure, Decimal);
              docx_tagfill.propose_relations (tag ids and an operator, never a
              figure); arithmetic_warnings surfaced on the D13 review line.

WHAT IS LEFT, in order
  F3  build the MOU document          <- START HERE
  A1  extract the fill handlers to app/ai/agents/fill_tools.py (pure refactor)
  A2  the MOU tools, the system prompt, the router line, the loop-breaker,
      the editing refusals, AND F2's approval gate (see plan §0 amendment D)
  A3  the tool-CHOICE test (unscripted)
  G1  the golden run over the tagged MOU
  R1  GET /mous/{id} and the lead's `mous` key
  R2  Android: MouDto, MouLines, a contract fixture, a ContractTest case
  U2  the console (deferred by the owner; see plan §0 amendment B)
  E1  documentation and deploy

F3 IN PARTICULAR — three things, and the third is a defect you would otherwise ship
  1. `_write_mou`: apply the tags, REFUSE TO SHIP if apply_tags reports
     anything in `skipped`, call index.refresh_static yourself for a static
     contents page exactly as docx_proposal_service.py:102 does, produce the
     PDF (a LibreOffice failure must leave pdf_path null, not lose an approved
     document), and write the MouDocument with the eight-key filled_json the
     Android card reads. Check "is this session already BUILT" BEFORE anything
     else, so a double tap returns the document that exists (J2's defect).
  2. The correction path: reopen a built MOU, rewrite the SAME row, save a
     revision, clear pdf_path before re-converting, and REFUSE once sent.
  3. **THE DOCUMENT PROPERTIES.** A tag cannot reach them — scan and
     apply_tags walk paragraphs, and properties are not paragraphs. The
     template's dc:title now reads "<School Name>" because a client's name in
     the properties would otherwise ship to a different school. NOTHING FILLS
     THEM. _write_mou MUST set the built document's core properties from the
     filled values, WITH A TEST. See plan §0 amendment K.

FOUR LESSONS FROM THE SIMPLE FLOW. Do not re-learn them.
  1. A GREEN SUITE PROVED NOTHING ABOUT TOOL CHOICE. Every J1/J2 test scripted
     the tool call, so none tested that a model WOULD call it. In real use the
     agent called create_proposal six times and answer_proposal_questions
     zero. WHEN A FEATURE DEPENDS ON A MODEL PICKING ONE TOOL OVER ANOTHER,
     THAT CHOICE IS THE THING TO TEST — that is A3, and it is not optional.
     Add the MOU's tools to the system prompt in the SAME COMMIT as the tools,
     and make the wrong tool harmless: create_mou on an open fill must RETURN
     {already_open, still_to_answer, what_to_do} naming the right tool.
  2. DO NOT REASON BY ANALOGY WITH THE COMPLEX FLOW. A simple-flow proposal
     was given the rate card's line items and the chat announced "Total
     amount: 2200" for a document reading Rs 15,00,000-25,00,000. ASK WHETHER
     THE PREMISE TRAVELS. mou_documents has no commercial columns for exactly
     this reason.
  3. A SAFE-LOOKING FAILURE CAN HIDE AN UNSAFE SUCCESS. edit_narrative refused
     on a simple-flow proposal only because the instruction happened to
     contain a price; without one it would have rewritten the RECORD of a
     document it cannot touch and reported success. A2 must refuse
     edit_narrative and update_line_items for an MOU, and test the path that
     does NOT trip the guard.
  4. COUNT LITERALS, NEVER READ THEM — AND COUNT THEM OVER THE WHOLE PACKAGE,
     NOT THE PARAGRAPH WALK. This session: I verified the tagged MOU by
     walking paragraphs and declared it clean; the owner opened it and the
     school's name was still there, in dc:title. A .docx is a zip of many
     parts. Also OCR the images — text that is pixels is invisible to a grep.

PER TASK, the process that worked
  Read the task. Write the tests. WATCH THEM FAIL FOR THE RIGHT REASON.
  Implement. Run the task's tests, then tests/docx, then the full backend.
  MUTATION-CHECK: change the behaviour the task is about and prove the right
  test fails. This caught a real gap in EVERY task this session, including two
  cases where a "surviving mutant" was a fault in the harness rather than the
  code, and one that was pytest's bytecode cache. Review your own work — three
  defects were found reading the code after the tests were green. Commit only
  the named paths, verify the commit in a `git archive HEAD` export, append
  what happened to the ledger, then tell the owner.

  Numbers in a plan are measurements. If a run disagrees, STOP AND
  INVESTIGATE, then tell the owner — do not edit the pin to make a test green.
  Several pins were corrected this way, and three round-count projections were
  withdrawn as unverifiable.

DEPLOYING — the backend runs under systemd and fronts an ngrok tunnel
  Backend on :8010 (NOT the 8000 in .env — that is an unrelated RAG chatbot).
  nginx listens on 127.0.0.1:8080 and proxies to 8010; ngrok fronts nginx at
  https://noninfluential-lamonica-unobservantly.ngrok-free.dev .
  Restart:  printf '%s\n' 'tela@123' | sudo -S -p '' systemctl restart salesforce-app-restart.service
  The restart script is at Backend_Codebase/restart_script/ — ONE LEVEL ABOVE
  the project directory, not inside it.
  NEVER kill the backend PID directly — the script's teardown takes ngrok with
  it and you will leave the public URL down. Verify over the PUBLIC url, not
  just locally. An hourly healthcheck timer restarts the service on three
  failures.
  A restart is what makes create_all build a new table.
  Console bundle: build from the WORKING TREE (not a HEAD export) — the tree
  carries session/baseUrl.ts, without which a console served over ngrok tells
  every visitor's browser to call 127.0.0.1:8000. Toolchain:
    export PATH="/home/telaverge/.nvm/versions/node/v22.11.0/bin:$PATH"
    mkdir -p /tmp/shim
    printf '#!/bin/sh\nexec $PROJ/.venv/bin/python "$@"\n' > /tmp/shim/python
    chmod +x /tmp/shim/python ; export PATH="/tmp/shim:$PATH"
    cd Dashboard && node node_modules/typescript/bin/tsc --noEmit
                 && node node_modules/vitest/vitest.mjs run
                 && node node_modules/vite/bin/vite.js build
  Dashboard/dist is build output and is NEVER committed.

THE ANDROID APP is at C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI
on the machine you are running on — NOT on the VM. It is NOT a git repository,
so back up any file before editing. Run its tests with
  JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew :app:testOrgDebugUnitTest
Contract fixtures live in app/src/test/resources/contract/. There is no
Robolectric, so anything left in a fragment cannot be tested — extract pure
decisions into a class beside ProposalFilledLines, as E1 did.

OPEN QUESTIONS FOR THE OWNER — ask before assuming
  * `<ask me, proposed one- ...>`. The owner writes asks in natural language;
    TAG_RE reads that as SEMANTIC, because an ask must be spelled `ask:`. So
    their "ask me" would be filled silently rather than asked. Should the
    grammar learn "ask me"? Recommended yes; not yet decided.
  * word/_rels/settings.xml.rels points at
    file:////Users/SunilaJohnson/Documents/Telaverge Communications/... — the
    attached template on a staff member's machine, leaking a name and folder
    structure to every client. Strip it or leave it? Their call.
  * THE OWNER MUST REPAIR THREE BROKEN WORD FIELDS in the source MOU, at walk
    ordinals 209, 232 and 236: "Error! Reference source not found." and
    "Error! No text of specified style in document." No tag can fix them and
    they will print into every MOU built from this template.
  * scripts/migrations/2026-09-08_optional_rate_card.py's backup was taken
    with shutil.copyfile and is missing the WAL. It should not be trusted as a
    restore point. Fixing a migration that has already run is the owner's call.
  * Whether a built MOU should appear anywhere in the sales pipeline was
    DECIDED: no. It gets its own section on the client screen (R2) and the
    chat card where it was built.

FINALLY: the owner tests in the real app, on a phone, through the ngrok URL,
and finds things a green suite does not — three of the simple flow's defects
came that way and none from the suite. Deploy after each meaningful change and
say plainly what you have verified yourself and what still needs their eyes.

Start with F3. Measure the baseline first.
