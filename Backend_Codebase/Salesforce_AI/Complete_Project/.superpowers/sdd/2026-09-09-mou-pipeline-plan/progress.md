# Execution ledger - MOU pipeline (plan 2026-09-09)

The source of truth for what happened. One or more lines per task, recording
numbers, defects found and rulings made. The plan's checkboxes are not
maintained; this file is.

Tasks are M1-M3, U1-U2, F1-F3, A1-A3, G1, R1-R2, E1. The decisions are
D-A..D-F plus the routing and correction rulings, and are a separate
numbering continuing the simple flow's D1-D37.

---

BASELINE RE-MEASURED BEFORE ANY CODE, as the handover required rather than
copied from it. Branch feature/docx-proposal-templates at 0fe0325, 45 commits,
dirty 91. Backend at HEAD in isolation: 636 passed, 53 skipped. The handover
said "630-odd with 53 skipped"; 636 confirms it and is the number this plan
uses.

DESIGN INPUT SECTION 1 REPRODUCED EXACTLY by a read-only probe before any
decision rested on it. The owner's MOU: 240 paragraphs in the walk, 193 body /
17 header / 30 footer, 8 tables, 3 sections, 11 images, 0 tags today. Every
repeated literal agrees - Sandur Education Centre 10, Innovation Nexus 5, 75
x5, 32 x3, Rs. 1,50,000 x2, Y S Ghorpade x2, Rs. 4000 x1, Rs. 3,00,000 x1.

ONE REFINEMENT TO THE DESIGN INPUT, MEASURED. It warns the header/footer trap
is "worse in proportion" here than in YuviPep 360. Per literal it is
NARROWER: 2 of the 10 client-name occurrences are outside the body, against 6
of 9 in YuviPep 360. The structural claim stands (47 of 240 paragraphs are
outside the body) and the rule is unchanged - count with raw_count, never by
eye - but the specific comparison in the design input is not what the document
measures.

D-D IS NOT THE PROBLEM THE DESIGN INPUT DESCRIBES, and this changed the
design. The input frames it as "45-55 occurrences at six a round is eight or
nine exchanges". Measured in the code: open_questions
(proposal_fill_service.py:356) slices raw OCCURRENCES, and duplicate_of - set
by raw literal at tags.py:143 - is never collapsed on the asking path. The
D13 review DOES collapse, via proposal_agent._group. So on the MOU
`<ask:75>` (five occurrences of one literal) would fill five of round one's
six slots and the person would be asked the same question five times in one
message. On the proposal this was invisible because the repeated literal there
was <School Name> x9, which is semantic and filled silently. Collapsing on
duplicate_of makes it ~20 questions and 3-4 rounds, not 8-9.

D-D's SECTION GROUPING IS NOT A HEURISTIC, and this was probed before being
designed. The owner's MOU carries real Word heading styles landing exactly on
the boundaries a coherent round wants: Heading1Center at ordinals 24
("Memorandum of Understanding") and 89 ("Annexure"), Heading2 at 90
(Operation Terms), 112 (Agreed Deliveries and Offers), 149 (Pricing Details),
159 (Student Enrolment Structure), 169 (Payment Terms) and 181 (YuviPep Bank
Details). Read from w:pPr/w:pStyle/@w:val. The short-bold-line rule is a real
fallback rather than the primary mechanism.

TWO DEFECTS IN THE OWNER'S OWN DOCUMENT, found by the same probe. (1) D-F
confirmed: `Date: ___________` at walk ordinals 85 and 87, both in the
signature table. (2) THREE BROKEN WORD FIELD REFERENCES, all outside the body
- ordinal 209 reads "Error! Reference source not found." and ordinals 232 and
236 read "Error! No text of specified style in document." They are not caused
by anything in this project, no tag will fix them, and they will print into
every MOU built from this template on pages nobody scrolling the body would
check. REPORTED TO THE OWNER, not worked around: silently stripping text from
a client-facing contract is not this pipeline's business.

D-A's BLAST RADIUS MEASURED RATHER THAN ASSERTED. Had an MOU been a Proposal
row it would have entered five places that describe a DEAL: leads.py:357 (the
lead screen's proposal list), knowledge_engine.py:172 (client history),
document_engine.py:185 (accepted_total sums total_amount),
approval_engine.py:434/588, and inbound_engine.py:1218 - which reads a SENT
proposal on a project as THE DEAL BEING AGREED. An MOU is signed after a
proposal is accepted, so it would arrive on an already-closed deal and flip
its state. mou_documents therefore carries no total_amount, no line_items, no
pricing_table_id and no project_id: absent rather than merely unused, so no
future aggregate can pick one up by accident.

THE SPEC AND THE PLAN ARE UNCOMMITTED ON PURPOSE. docs/ is untracked but NOT
ignored, so git collapses it to a single "?? docs/" line - one of the 91.
Measured: 10 files on disk, 0 tracked, and no spec has ever been committed in
this project. Adding one under git would stop the collapse and expand the
dirty count from 91 to 99. Both documents therefore live in docs/ uncommitted,
which is what every previous plan in this project did.

---

Task M1: THE DEFECT WAS REPRODUCED ON A LIVE CODE PATH BEFORE ANY FIX. The
first test uploads a proposal template and then an MOU for the same programme
and asserts the proposal is still current. It failed with "uploading an MOU
retired the proposal template / assert False is True" - not on a missing
attribute, but on the behaviour itself. Measured consequence on the live
database: IBC (b4487189) carries six template rows with ibc_proposal_v4
current, so an MOU upload would have cleared it and _current_template would
then return None, answering every "create the IBC proposal" with "No proposal
template for this program. Ask your Org Admin to add one."

Task M1: FIVE FILES, ALL CLEAN AT HEAD AND ALL PURE LF - app/models/program.py,
app/services/docx_template_service.py, app/api/admin.py,
app/services/proposal_service.py, app/services/proposal_fill_service.py.
Checked before editing rather than assumed, because handover 6a exists
precisely because the answer is not obvious. 6a does not apply to any of them;
worktree == HEAD + my edit.

Task M1: THE COLUMN EDIT WAS SCOPED TO ONE CLASS, not anchored on a line.
program.py has three identical `is_current: Mapped[bool] = mapped_column(
Boolean, default=True)` lines, and TWO identical is_current/created_by PAIRS -
ProposalTemplate and MessageTemplate. A whole-file anchor would have been
ambiguous and a two-line one would have been wrong half the time. The edit
script finds the `class ProposalTemplate(` block and replaces only inside it.

Task M1: I MADE THE EXACT MISTAKE RULE 6 WARNS ABOUT, and the guard caught it.
The retire-loop edit was sentinelled on the prose "only retire the current
template of THIS document type", which in the inserted comment WRAPS across
two lines ("THIS\n # document type"). So the marker never matched, and the
second run tried to re-apply, could not find its anchor, and reported
"anchor matched 0 times, expected 1". It failed LOUDLY rather than duplicating
the block, because the script also asserts its anchor occurs exactly once -
but the script was not idempotent, which rule 6 requires. Re-sentinelled on a
single line of CODE (`ProposalTemplate.document_type == document_type,`),
which nothing re-wraps. Second run then: 13 edits, 0 applied, 13 already
present, exit 0. FOR THE NEXT SESSION: guard on code, not on prose. Prose in a
comment block is exactly the text that wraps.

Task M1: TWO OF FIVE MUTATIONS SURVIVED THE FIRST RUN AND BOTH WERE WEAK
TESTS, NOT WEAK CODE.
(1) "_current_template forgets document_type" survived because
_current_template orders by version.desc() and takes .first(), and both
templates in the test were version 1 - a tie that SQLite happened to break in
the proposal's favour. The test passed even with the filter deleted, because
the wrong code never actually produced a wrong answer. Fixed by uploading the
MOU TWICE so it is version 2 and genuinely wins the ordering; only the filter
can then keep it out.
(2) "the column defaults to mou" survived because the route's own
Form("proposal") always supplies the value, so the COLUMN default is never
exercised through the upload path - a bad proxy, the same shape as C2's
"clarification turn re-sends the document" survivor. Replaced the test with
one that constructs a ProposalTemplate row directly and asserts it reads
"proposal", which is what the default actually protects.
Both then caught. All five mutations caught, exit 0.

Task M1: A PINNED NUMBER DISAGREED WITH A RUN AND THE INVESTIGATION FOUND A
REAL DEFECT - IN THE BACKUP, NOT THE COUNT. The migration's dry run reported
17 proposal_templates where the plan pinned 18. The live database really does
have 18. Cause: data/salesplatform.db runs in WAL MODE with a 4.2 MB
salesplatform.db-wal, and `cp data/salesplatform.db /tmp/copy.db` copies only
the main file, silently dropping every transaction not yet checkpointed.
Measured side by side: plain cp gives 17, sqlite3 Connection.backup gives 18.
THE PIN WAS RIGHT AND THE DRY RUN WAS TESTING THE WRONG DATA.

Task M1: THE SAME DEFECT IS IN THE MIGRATION THIS ONE IS MODELLED ON, AND IT
IS NOT FIXED HERE. scripts/migrations/2026-09-08_optional_rate_card.py takes
its safety backup with shutil.copyfile, so
data/salesplatform.db.before-optional-rate-card.20260908024448 is missing
whatever was in the WAL at 02:44 on 8 September. Its ledger line records "Dry
run on a copy: 6 -> 6 rows", and that copy was made the same way, so the dry
run validated a stale snapshot too. The migration itself ran on the live file
and was correct; only the BACKUP and the DRY RUN are affected. FOR THE OWNER:
that backup should not be trusted as a restore point, and the fix is a
two-line change to that script. Flagged rather than done, because editing a
migration that has already run on the live database is its own decision.

Task M1: THIS MIGRATION BACKS UP THROUGH SQLITE. _backup_to opens the database
read-only and uses Connection.backup, which reads through the WAL and produces
a consistent file. Verified after the real run: the backup holds 18
proposal_templates, not 17. It also sets busy_timeout=30000 and timeout=30,
because the backend serves while this runs and database.py sets the same for
the same reason.

Task M1: MIGRATED THE LIVE DATABASE. 18 -> 18 rows, 13 current unchanged, no
foreign key violations, document_type = {'proposal': 18}. A second run reports
"already present - nothing to do". Backup at
data/salesplatform.db.before-document-type.20260909180126, verified complete.
FOR THE OWNER: any OTHER environment needs this script run once; a brand-new
database does not, because create_all builds the column from the model.

Task M1: THE UPLOAD ROUTE GAINED document_type IN THIS TASK, WHICH THE PLAN
PUT IN U1. Not scope creep: the column cannot be exercised at all without a
way to set it, so M1's own tests would have had to reach past the API to
create an MOU template. The plan's M1 interfaces block already named
create_docx_template(..., document_type="proposal") as M1's output, so this
is the route half of that. U1 still owns the mou_simple kind, the flow
validation, the ruled-blank count and the console.

Task M1: COMMITTED 68241e4, seven paths - app/models/program.py,
app/services/docx_template_service.py, app/api/admin.py,
app/services/proposal_service.py, app/services/proposal_fill_service.py,
scripts/migrations/2026-09-09_template_document_type.py (new),
tests/docx/test_mou_models.py (new). Dirty 91 before and 91 after; it read 98
while working, which is 91 + 5 modified (all five were clean at HEAD) + 2 new
untracked. 46 commits from aa49e80.

Task M1: TESTS. tests/docx/test_mou_models.py 6 passed. tests/docx 423 passed
(417 before, +6). Backend working tree 826 passed / 1 failed - the failure is
tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first,
the pre-existing one that must not be fixed, and it is the ONLY one; the four
time-of-day-sensitive tests were green at this hour. Arithmetic: 820 + 6 = 826.

Task M1: IN ISOLATION 642 passed, 53 skipped, 0 failed. The 0fe0325 baseline
measured at the start of this session was 636 + 53 = 689 collected; 689 + 6 =
695. All six new tests are synthetic - none reads the gitignored live database
or data/samples - so the passed delta is the full 6 and the skip count is
unchanged at 53. Reconciles exactly. Verified inside the export that the
committed app/models/program.py really carries the column, so the commit is
self-consistent in isolation rather than only in the working tree.

Task M1: PHASE M IS ONE THIRD DONE. M2 is the mou_documents table and is the
FIRST task in this plan where handover 6a applies: app/models/__init__.py,
app/core/reset_taxonomy.py and tests/test_reset_taxonomy.py are all on the
pre-existing dirty list, and the partition assertion must be measured at HEAD
rather than in the working tree. Measured already, for M2 to derive from
rather than assume: HEAD asserts (4, 2, 8, 43) over 57 tables; the working
tree asserts (4, 2, 8, 45) over 59.

Task M2: FOUR FILES TOUCHED PLUS ONE NEW ONE, and the dirty/clean split was
MEASURED before editing rather than taken from the plan. Dirty, so handover 6a
applies: app/models/__init__.py, app/core/reset_taxonomy.py,
tests/test_reset_taxonomy.py. Clean: tests/test_dashboard_reset.py. New:
app/models/mou.py. tests/docx/test_mou_models.py is M1's, committed, so
worktree == HEAD + my edit and a plain git add is correct for it. All five
pure LF.

Task M2: 6a WAS NEEDED FOR REAL AND THE TWO TREES GENUINELY DISAGREE.
Measured: HEAD asserts (4, 2, 8, 43) over 57 tables; the working tree asserts
(4, 2, 8, 45) over 59, because the in-flight feature-pre-sales-cold-calling
work added relationship_engagements and lead_cycles to WIPE. The IDENTICAL
edit script was run against both and derived (4, 2, 8, 44)/58 in the export
and (4, 2, 8, 46)/60 in the working tree. Writing either number literally
would have produced a commit that is false in the other tree - ruling R3, and
the A4 defect 6a exists to stop.

Task M2: EVERY COUNT IS DERIVED BY INCREMENT AND THE ARITHMETIC IS GUARDED
TOO. A4's bug was a script that guarded its string replacements but not its
numeric bumps, so a second run took WIPE 44 -> 45 -> 46. Here the bump is
gated on a marker ("mou_documents joined WIPE") that is absent before and
present after, and idempotency was verified by running the script twice
against the working tree: second run reported 0 applied, 5 already present,
exit 0.

Task M2: WIPE, AND THE ORDER IS A CONSTRAINT RATHER THAN A PREFERENCE.
mou_documents sits AFTER proposal_fill_sessions - which will carry mou_id in
M3 - and BEFORE proposals. The list is deleted in order and nothing in this
schema declares ondelete=, so child-before-parent is the only thing keeping a
reset from failing on a foreign key. Pinned by an explicit index-order test as
well as by the generic partition walk, the same shape A4 used.

Task M2: THE ORPHAN-EDGE PIN WENT FROM NINE TO ELEVEN, and the two new edges
are mou_documents.program_id -> programs and mou_documents.template_id ->
proposal_templates. lead_id and created_by point at WIPE/CONFIG tables and are
therefore not orphan edges. This is not editing a pin to make a test green:
the test's own docstring says a schema change adding such an edge "must fail
this test, not silently change behaviour", so the pin exists to force the
decision. The decision recorded: a built MOU names the programme and the
template version it was built from, so a catalogue-only reset must refuse
rather than leave a signed contract pointing at a template that is gone.
_CATALOGUE_ORPHAN_EDGES itself needed no change - it is derived by walking the
FK graph at import time, exactly as A4 found.

Task M2: THE MODEL CARRIES NO COMMERCIAL COLUMNS AND THERE IS A TEST NAMED FOR
IT. No total_amount, no line_items, no pricing_table_id, no pricing_version,
no project_id, no amends_proposal_id - absent rather than merely unused, so
that no aggregate written later can pick an MOU up by accident. This is D-A
stated as a schema rather than as a convention, and it is the direct answer to
last session's DEFECT 2, where the chat announced "Total amount: 2200" for a
document reading Rs. 15,00,000 because the rate-card machinery was carried
across from the complex flow without asking whether its premise came with it.

Task M2: TWO OF FIVE MUTATIONS "SURVIVED" AND NEITHER WAS A CODE FAULT; BOTH
WERE FAULTS IN MY MUTATION HARNESS. Recorded because a bad harness is worse
than no harness - it reports a green mutation check over tests it never
actually ran.
(1) "the table carries a total_amount after all" used a Float column, and
mou.py does not import Float. The mutant could not be imported, pytest
reported a collection ERROR rather than a FAILED, and my harness counted only
lines beginning with FAILED - so a NameError read as a surviving mutant.
Fixed twice over: the mutation now uses String, which the module already
imports, and the harness now treats a collection error as "this mutation
proved nothing" instead of silently as a survivor. Re-run: caught by TWO
tests, the column test and the row round-trip (total_amount is NOT NULL with
no default, so the insert fails too).
(2) "the partition count is left at its old value" was caught all along - by
test_bucket_sizes_are_the_agreed_partition, not by the test I had named in the
harness. My expectation was wrong, not the test.
After both fixes: five mutations, all caught, exit 0.

Task M2: THREE PYTEST WARNINGS INTRODUCED AND REMOVED BEFORE COMMITTING. The
module carries `pytestmark = pytest.mark.asyncio`, so three genuinely pure
tests were marked async and warned. Made them `async def`. Three warnings in a
suite that otherwise has none is noise the next reader has to explain away.

Task M2: A THIRD "SURVIVING MUTANT" THAT WAS NEITHER CODE NOR TEST, BUT
PYTEST'S CACHE - and this one is worth remembering because it produced a test
that PASSED ALONE AND FAILED IN THE SUITE, which is the shape of a flaky test
and is not one. After the mutation run, tests/test_reset_taxonomy.py::
test_bucket_sizes_are_the_agreed_partition failed with
"assert (4, 2, 8, 46) == (4, 2, 8, 45)" while the source line pytest PRINTED
above it read "== (4, 2, 8, 46)". Source and executed bytecode disagreed.
CAUSE: the harness restores a file with shutil.move, which RENAMES, so the
restored file inherits the BACKUP's mtime - earlier than the mutated version
pytest had just cached. The mutation "46" -> "45" is the same byte length, and
pytest's assertion-rewrite cache is keyed on (mtime, size), so it went on
serving the MUTATED bytecode. Measured: source 18:38:57.47, .pyc 18:38:58.46 -
the cache a full second NEWER than the file it claims to represent. `touch`
alone fixed it. Harness now calls os.utime(full, None) after every restore.
FOR THE NEXT SESSION: any tool that writes a file, runs pytest, and writes it
back can poison the cache this way. If a test passes alone and fails in the
suite against a literal that is not in the file, look at the .pyc mtime before
looking at the test.

Task M2: THE FULL SUITE ALSO DIED ONCE ON A DROPPED SSH CONNECTION mid-run
("Socket exception ... 10054", exit 127) with tests/docx already reported. Not
a test failure and not diagnosed as one; re-run cleanly. Recorded only so the
next reader does not treat a 127 in a log as a code problem.

Task M2: COMMITTED ccfb1ed, six paths - app/models/mou.py (new),
app/models/__init__.py, app/core/reset_taxonomy.py, tests/test_reset_taxonomy.py
(those three via 6a, staged from a git archive HEAD export with git
hash-object -w plus git update-index --cacheinfo), tests/test_dashboard_reset.py
and tests/docx/test_mou_models.py (plain add - worktree == HEAD + my edit).
Dirty 91 before and 91 after; 94 while working, which is 91 + 3 newly touched
files, the other three having been dirty already. Verified after committing
that the three 6a files are dirty AGAIN, as they must be, and that
reset_taxonomy.py still carries relationship_engagements and lead_cycles.

Task M2: TESTS. tests/docx 427 passed (423 before, +4). Backend working tree
830 passed / 1 failed - the pre-existing tests/test_relationship_screens.py and
nothing else. Arithmetic: 826 + 4 = 830. IN ISOLATION 646 passed, 53 skipped,
0 failed; M1 was 642 + 53, and 642 + 4 = 646. Skips unchanged at 53 because
every new test is synthetic. The export asserts (4, 2, 8, 44) over 58 tables
and passes there, while the working tree asserts (4, 2, 8, 46) over 60 and
passes here - which is the whole point of 6a.

Task M2: NO RESTART YET, DELIBERATELY. create_all builds mou_documents at
startup, so the live database does not have the table until the backend is
restarted. Nothing needs it before M3, and a restart is worth doing once, with
M3's migration, rather than twice.

Task M3: FOUR FILES, ALL CLEAN AT HEAD - app/models/proposal_fill.py,
app/services/proposal_fill_service.py, tests/docx/test_models.py, plus the new
tests/docx/test_mou_fill.py and the new migration. Handover 6a does not apply
to any of them; worktree == HEAD + my edit. All pure LF. Checked before
editing, as always.

Task M3: THE SCOPE HELD - NO `mou_simple` KIND HERE. `_simple_template` still
demands kind == "docx_simple", and an MOU template uploaded with
document_type="mou" currently gets that kind, so M3 works without touching it.
U1 owns the mou_simple kind and will tighten the check at the same time.
Recorded because it looked briefly as though the data model could not be made
coherent without pulling U1's work forward; it can.

Task M3: THREE MARKER FAILURES IN ONE TASK, AND THEY ARE ONE LESSON IN THREE
SHAPES. Handover rule 6 says guard every scripted edit with a marker already
in the file and make the sentinel survive wrapping. That is necessary and it
is not sufficient. The three:
  (1) M1, the retire loop: the sentinel was PROSE that wrapped across two
      comment lines in the text it guarded, so it never matched.
  (2) M3, _simple_template: the sentinel was the new signature line
      `template_id: str | None, *, document_type: str = "proposal",` - which
      M1 had ALREADY added to `_current`, two functions below in the same
      file. The marker was present before the edit ran, so the edit silently
      SKIPPED ITSELF and reported "already applied" while doing nothing. This
      is the dangerous one: it is a false success, not a loud failure.
  (3) M3, find_open: the sentinel spanned a newline, and the comment this very
      edit inserts was placed exactly at that break - so it could never match
      afterwards and the second run reported FAIL.
THE RULE THAT COVERS ALL THREE: a sentinel must be a SINGLE LINE, made of
CODE rather than prose, and UNIQUE TO THE EDIT IT GUARDS - not merely present
after it. Verify by running the script twice and requiring every line to read
"already applied" with exit 0, which is now what "idempotent" is taken to
mean here.

Task M3: A MUTATION SURVIVED FOR THE SAME REASON ONE DID IN M1 - the test
passed by luck rather than by the code being right. "find_open forgets
document_type" survived because find_open orders by updated_at descending and
takes the first row, and my test opened the MOU fill SECOND, so the newest row
was the one being asked for and the filter changed nothing. Fixed by opening
the MOU FIRST and asking for the older of the two, so only the filter can
produce the right answer. This is the third time in three tasks that ORDERING
has hidden a missing filter (M1's version tie, M1's route default, this one).
FOR THE NEXT SESSION: when a lookup ends in .first(), a test that asks for the
row the ordering would return anyway is not testing the filter.

Task M3: THE MIGRATION IS IDEMPOTENT PER COLUMN, NOT PER SCRIPT, and the
half-applied case is tested rather than assumed. Either, both or neither of
mou_id and document_type may already exist - a migration interrupted between
two ALTER TABLE statements leaves exactly that state. Proved by rebuilding a
copy with mou_id present and document_type removed and running the script
against it: it added only document_type. It also REFUSES to report success if
any row already carries an mou_id, which would mean it was not the first
thing to write this column.

Task M3: TWO A4 GUARDS WENT RED AND BOTH WERE RIGHT TO.
tests/docx/test_models.py pins the fill session's columns as an EXACT SET and
its nullable columns as an exact set, so two new columns break both by design.
Updated with the reason beside them, not to make them green:
document_type joins the column set and is deliberately NOT nullable (it is
known at open time and defaults to "proposal", so every fill that existed
before this pipeline reads as what it always was), while mou_id joins the
nullable set. The second test's NAME was also now false -
test_only_the_proposal_and_the_chat_session_may_be_absent - and was renamed to
test_only_the_written_document_and_the_chat_session_may_be_absent rather than
left saying something untrue about the schema it guards.

Task M3: MIGRATED THE LIVE DATABASE. 4 -> 4 rows, document_type =
{'proposal': 4}, mou_id null on all of them, no foreign key violations. Second
run reports "both columns already present". Backup at
data/salesplatform.db.before-fill-mou.20260910055251, taken through SQLite and
verified to hold all 4 rows. FOR THE OWNER: any OTHER environment needs BOTH
2026-09-09 migrations run once, in either order; a brand-new database needs
neither.

Task M3: THE HANDOVER'S RESTART PATH IS WRONG AND SHOULD BE CORRECTED.
It says `restart_script/restart_backend.sh`, which does not exist relative to
the project. The script lives one level ABOVE the project directory, at
/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/restart_script/,
which is also what the systemd unit's Docs= line points at. The sudo systemctl
form in the handover is correct and is what was used.

Task M3: TESTS. tests/docx 435 passed (427 before, +8). Backend working tree
838 passed / 1 failed - the pre-existing tests/test_relationship_screens.py
and nothing else. Arithmetic: 830 + 8 = 838. IN ISOLATION 654 passed, 53
skipped, 0 failed; M2 was 646 + 53, and 646 + 8 = 654. Skips unchanged at 53 -
every new test is synthetic.

Task M3: COMMITTED d8d6581, five paths, all plain adds because all were clean
at HEAD - app/models/proposal_fill.py, app/services/proposal_fill_service.py,
tests/docx/test_models.py, tests/docx/test_mou_fill.py (new),
scripts/migrations/2026-09-09_fill_session_mou.py (new). Dirty 91 before and
91 after; 96 while working. 48 commits from aa49e80.

DEPLOY (10 Sep, after M3): THE RESTART DID WHAT ONLY A RESTART CAN.
mou_documents was verified ABSENT on the live database before the restart and
present after it with all 17 columns - create_all builds a missing table at
startup, which is the whole reason a new table is free where a new column is a
migration. Verified in the same breath that it carries NO commercial columns,
so D-A holds on the live schema and not merely in the model file. Its four
indexes are there. Both 2026-09-09 migrations held across the restart:
proposal_templates.document_type present with all 18 rows reading 'proposal',
and proposal_fill_sessions carrying mou_id and document_type.

DEPLOY: RESTARTED THE RIGHT WAY - `sudo systemctl restart
salesforce-app-restart.service`, never a kill. The service was already running
under systemd (since 8 September) with ngrok inside its cgroup, and came back
active in 8s as MainPID 217824 with the tunnel alongside it.

DEPLOY: VERIFIED OVER THE PUBLIC URL FROM THE WINDOWS MACHINE, not just
locally. /health returns {"status":"ok","llm_provider":"openrouter"};
/dashboard 307s to its trailing-slash form; and POST
/api/v1/admin/programs/{id}/proposal-templates/docx answers 401 rather than
404, so the route carrying the new document_type field is live behind auth.
FOR THE OWNER: nothing user-visible has changed yet. The schema is in place and
the upload route accepts document_type, but there is no MOU kind, no console
control and no agent tool until U1, U2 and A2. Uploading an MOU template today
would store it as an MOU and correctly leave the proposal template current -
that much is real and testable from the console - but nothing can fill one.

PHASE M IS COMPLETE. M1 current-per-document-type templates (68241e4), M2 the
mou_documents table (ccfb1ed), M3 the shared fill session (d8d6581). The
schema for the whole feature is now in place and deployed; nothing after this
point changes a table. Three commits, dirty 91 throughout, and the one
permitted failure is still the only failure.

TAGGING THE MOU (owner, 10 Sep): "you can add tags for the mou document in
natural language". Done before U1, so U1's tests and G1's golden suite have a
real document to work against. The style was taken from the owner's OWN tagged
proposal template rather than invented: a semantic tag is a plain
natural-language name in angle brackets (<School Name>), an `ask` tag carries
the author's original value as its default (<ask:6 Units>), and `ask_calculate`
is for prices.

TAGGING: A READ-ONLY PROBE PRINTED ALL 240 PARAGRAPHS WITH THEIR SECTION AND
TABLE ROW LABELS BEFORE A SINGLE REPLACEMENT WAS CHOSEN, and then every
literal was LOCATED BY COUNT rather than by reading. Two findings that a
careful reading had got wrong:
  (1) `Sandur Education Centre` appears TEN times, not the eight I had found
      by eye. The two I missed are in the Purpose clause (ord 40) and the
      Responsibilities heading (ord 58) -- both in plain body prose, not even
      hidden in a footer. Lesson 4 exactly: count literals, never read them.
  (2) A GLOBAL REPLACE OF "32" WOULD HAVE CORRUPTED THE SCHOOL'S OWN ADDRESS.
      `Hosapete-583203` contains "32". Only ords 49 and 99 are workshop
      counts. Every entry in the tagging table is therefore pinned to one
      paragraph, which is what J3's script shape already gave for free.
  (3) The two signing blanks are DIFFERENT LITERALS: ord 85 carries eleven
      underscores and ord 87 twelve, so a single pattern would have matched
      one and half of the other.

TAGGING: MEASURED. 50 occurrences of 21 distinct literals - 15 semantic, 31
ask, 4 ask_calculate, 35 always-asked, 29 duplicates chained. That sits inside
the design input's projected 45-55 band. Shape identical to the untagged
original: 240 paragraphs, 3 sections, 8 tables, 11 images - replace_span
writes in place and inserts nothing, and that identity is what lets the golden
suite trust every later assertion about the BUILT document's shape.

TAGGING: VERIFIED BY COUNTING WHAT IS LEFT OUTSIDE A TAG, which is the only
check that means anything. A first version of the check counted raw literals
and reported seven "still there" - a FALSE ALARM, because an `ask` tag
deliberately carries the author's value as its default, so "Innovation Nexus"
is supposed to survive inside <ask:Innovation Nexus>. Stripping every <...>
span first and then counting gives the real answer: ZERO client-specific
literals reach the client verbatim. Confirmed in the same pass that YuviPep's
bank account, IFS code and own address are untouched, as design input section
2c requires.

TAGGING: D-D's PROJECTION IS NOW MEASURED ON A REAL DOCUMENT AND THE DESIGN
INPUT WAS WRONG. 35 ask occurrences collapse to 17 distinct literals, which at
QUESTIONS_PER_ROUND = 6 is THREE ROUNDS. The design input projected "eight or
nine exchanges" from 45-55 occurrences; the spec projected 3-4; the document
says 3. Without D-D's collapse it would be 6 rounds AND the person would be
asked the same question five times in one message. FOR THE OWNER: three
exchanges, not nine.

TAGGING: scripts/tag_mou_sample.py IS COMMITTED AND THE FIXTURE IS NOT.
data/samples is gitignored, so without the script a reader cannot tell whether
the tagged file is missing or was never built. Dry-run by default; --write
produces data/samples/Sandur Education Centre_IBC Nexus and Lab2_MoU
(tagged).docx, 2,073,328 bytes, on the VM only.

---

Task U1: THREE FILES - app/services/docx_template_service.py,
app/services/proposal_fill_service.py, tests/docx/test_template_service.py -
all CLEAN at HEAD, all pure LF, plus the new tests/docx/test_mou_upload.py and
the committed tagging script. Handover 6a does not apply.

Task U1: AN MOU GETS ITS OWN KIND, `mou_simple`, and _simple_template now
looks up the expected kind per document type through SIMPLE_KINDS. Both flows
produce tag-filled Word documents, so kind is what stops a proposal fill
opening on a contract. An MOU uploaded as the COMPLEX flow is refused before
anything is stored, with a message that names the consequence rather than the
rule (B1's ruling): there is no console editor for a contract because every
value in one is a tag a person approves before it is written.

Task U1: D-F IS A WARNING, NEVER A REFUSAL. count_ruled_blanks walks the WHOLE
document - headers and footers included - and the upload summary reports the
number. A genuinely hand-signed blank is legitimate, so the upload succeeds.
THE TEST FIXTURE PUTS A BLANK IN A FOOTER ON PURPOSE: both of the owner's real
blanks sit in the signature table in the BODY, so a body-only counter passes
against the real document and is still wrong for the next one. Without that
fixture the mutation "count the body only" would have survived and certified
the bug.

Task U1: A MUTATION CHECK CAUGHT A REGRESSION I HAD NOT YET RUN.
plan_summary gained two keys (ruled_blanks, document_type) on BOTH branches so
the console reads one shape whatever it uploaded - and
tests/docx/test_template_service.py::test_a_complex_plan_summarises_as_complex
pins that return value as an EXACT DICT. The mutation harness ran a wider set
of files than my targeted test run and surfaced it. Updated with the reason
beside it, the way A4's and M2's exact-set pins were: a new key must be a
decision, not a surprise.

Task U1: ONE MUTATION IS AN EQUIVALENT MUTANT AND IS RECORDED AS ONE RATHER
THAN CHASED. "A proposal fill accepts an MOU template's kind" survives with
ZERO failures, and it should: M1 taught _current to filter on document_type,
so a proposal fill never reaches an MOU template and the kind check in
_simple_template is defence in depth with no reachable path. No in-process
observable distinguishes the two implementations, so a test for it would be
contrived or would assert nothing. Removed from the mutation list with the
reasoning written beside it - the same ruling C3 made about re-ordering
db.add before the model call. FIVE mutations remain and all five are caught.

Task U1: A TEST ASSERTION OF MINE WAS WRONG, NOT THE CODE. The refusal test
asserted the word "simple" appears in the message; it does not, because the
message names what to do instead ("filled by the assistant") rather than the
rule it enforces. Asserting on the rule would have passed for a message that
only said no. Now asserts on what a person could act on.

Task U1: THE REAL TAGGED MOU WAS PUSHED THROUGH THE REAL UPLOAD ROUTE, not
merely through unit fixtures. A throwaway test (written, run, deleted; the
method recorded here because it will want repeating) uploaded the 2 MB tagged
contract and got back: kind mou_simple, document_type mou, is_current True,
flow simple, tags 50, always_asked 35, ruled_blanks 0 - zero because the
tagging replaced both signing blanks with <ask:date of signing>, which is
exactly what D-F asks an author to do - and 21 distinct literals. In the same
run the UNTAGGED MOU uploaded as a proposal was refused 422 for having no
tags, which is B1's guard doing its job on a real document.

Task U1: TESTS. tests/docx 446 passed (435 before, +11). Backend working tree
849 passed / 1 failed - the pre-existing tests/test_relationship_screens.py
and nothing else. Arithmetic: 838 + 11 = 849.

Task U1: COMMITTED f2ead6a, five paths, all plain adds because all were clean
at HEAD - app/services/docx_template_service.py,
app/services/proposal_fill_service.py, tests/docx/test_template_service.py,
tests/docx/test_mou_upload.py (new), scripts/tag_mou_sample.py (new). Dirty 91
before and 91 after.

TAGGING, ROUND 2 (owner, 10 Sep): "I think you have missed a lot of tags...
so that the sandur one can also be considered as a generic template for that
product, not only related to sandur." The owner supplied a SECOND MOU for the
same product - SSRVM_IBC Nexus_Renewal (26-29) - which they had ALREADY
PART-TAGGED with fourteen tags. That document is worth more than any amount of
reasoning about the first one: diffing two real contracts for the same product
shows what actually varies, where tagging from one can only guess.

TAGGING R2: THE OWNER'S OWN VOCABULARY WAS ADOPTED RATHER THAN MINE.
From SSRVM: <new_version>, <org address>, <slug>, <use_prompt>, <Program name>,
<no. of years>, <duration>, <School>, <School name>, <Contact_Person>,
<date in words>, <normal date>, <address>.

TAGGING R2: SIX THINGS I HAD MISSED, EVERY ONE CONFIRMED BY THE DIFF.
  Document Version: 1.0 (x2)          -> <new_version>
  YuviPep's own party-block address   -> <org address>
  Mr N S Ajith Kumar (x2)             -> <ask:Mr N S Ajith Kumar>
  Chief Executive Officer (x2)        -> <ask:Chief Executive Officer>
  "one academic year" / "AY 2026-27"  -> <no. of years> / <duration>
  "Innovation Base Course (IBC)"      -> <Program name> (Term clause)
  "'First Party'"                     -> <slug>
I had left YuviPep's address and signatory deliberately, on design input
section 2c's advice that YuviPep's own details are constant. THE OWNER'S
DOCUMENT SAYS OTHERWISE: the signatory differs between the two contracts (N S
Ajith Kumar, CEO vs Jakati Vikram, Director of Innovation) and they tag the
address too. Section 2c is right about the BANK DETAILS and the footer contact
block - the owner leaves both untagged in SSRVM as well - and wrong about the
party block. Corrected.

TAGGING R2: A REAL GAP BETWEEN WHAT THE OWNER WRITES AND WHAT THE GRAMMAR
READS, AND IT IS NOT FIXED HERE. Their SSRVM document contains
`<ask me, proposed one- Mr. Jakati Vikram, Director of Innovation>`. That is
plainly an ASK with a proposed default -- and TAG_RE reads it as SEMANTIC,
because an ask must be spelled `ask:`. A semantic tag is filled silently
whenever the model is 80% confident, so the owner's "ask me" would NOT ask.
D14 saves it in practice (no citation resolves for a signatory the dossier
does not carry, so it becomes a question anyway) but that is luck, not design.
FOR THE OWNER: this is a decision -- should the grammar learn "ask me" as a
synonym for "ask:"? Written in the working form here so their intent holds
today either way.

TAGGING R2: MEASURED AFTER. 61 occurrences of 29 distinct literals, up from
50 of 21 - 22 semantic, 35 ask, 4 ask_calculate. Shape still identical to the
untagged original: 240 paragraphs, 3 sections, 8 tables, 11 images. Nothing
client- or deal-specific survives outside a tag; YuviPep's bank account, IFS
code, bank branch, email and FOOTER contact block are all correctly untouched,
matching what SSRVM leaves alone. Through the real upload route: kind
mou_simple, 61 tags, 39 always asked, 0 ruled blanks, 29 distinct.

TAGGING R2: THE ROUND COUNT MOVES FROM 3 TO 4. 39 ask occurrences collapse to
19 distinct literals, which at QUESTIONS_PER_ROUND = 6 is four rounds. Still
far from the design input's projected eight or nine.

TAGGING R3 (owner, 10 Sep): "but why haven't you changed the school name? it's
still showing as Sandur Education Center". THE OWNER WAS RIGHT AND MY
VERIFICATION WAS TOO NARROW. Every check so far had counted literals over the
PARAGRAPH WALK. A .docx is a zip of many parts, and the walk is only one of
them. Counting over EVERY BYTE OF EVERY PART found the name still in the
package.

TAGGING R3: WHERE IT WAS, AND IT WAS NOT THE BODY. All ten body and footer
occurrences were correctly tagged. What remained was METADATA, which no tag
can ever reach - `scan` and `apply_tags` both walk paragraphs, and document
properties are not paragraphs. Word shows dc:title in its title bar, in
File > Info and in Explorer's preview pane, which is what the owner was
looking at. Measured across the package:
   docProps/core.xml   dc:title "Sandur Education Centre", dc:subject
                       "Innovation Nexus", dc:creator "Smt. Y S Ghorpade" (the
                       school's own signatory as the document's AUTHOR),
                       cp:keywords "Chief Executive Officer", cp:category
                       "President"
   docProps/app.xml    TitlesOfParts "Sandur Education Centre", and <Manager>
                       "Mr N S Ajith Kumar" -- which the BODY RENDERS through
                       a DOCPROPERTY field, so that one is on the page
   docProps/custom.xml Status "New", Document version "0.85"
   customXml/item1.xml Word's CoverPageProperties: CompanyAddress = the
                       school's full address, Abstract = "75" (the student
                       count) and CompanyFax = "3,00,000" (the contract value)
Thirteen values in all. A contract built for one school and sent to another
would have carried the first school's name, address, student count and deal
value in its properties, invisible to anyone reading the page.

TAGGING R3: A VISIBLE TRACKING LINE NOBODY HAD NOTICED. Walk ordinal 1 reads
"Bookmarks: status: New; author:Sunila Johnson; acceptor: Mr Jakati Vikram;
modified: 1.9.2026". Checked for w:vanish: it is NOT hidden. Two YuviPep staff
and a date, printed on the cover of a document that goes to a client. Now four
tags.

TAGGING R3: I BROKE THE FILE ONCE AND THE CHECK CAUGHT IT. The first
neutralisation did a plain string replace inside the XML, which pasted a tag's
ANGLE BRACKETS into element text and produced a package python-docx (and Word)
refuses to open - "Specification mandates value for attribute Name". Rewritten
to parse each part with lxml and set `.text`, so escaping is lxml's job and
the result is valid by construction. Only a WHOLE-VALUE match is replaced, so
"75" cannot corrupt a date and "President" cannot corrupt a sentence. The
verification now opens the package with python-docx before asserting anything,
which is what turned a silent corruption into an immediate failure.

TAGGING R3: THE IMAGES WERE CHECKED TOO, because a byte-grep cannot see text
that is pixels. All 11 images OCR'd through the project's own ocr module: none
contains the school name, the programme or YuviPep. So the page itself is
clean and the leak really was only metadata.

TAGGING R3: MEASURED AFTER. 65 occurrences of 33 distinct literals, up from 50
of 21 in round one and 61 of 29 in round two. Shape still identical to the
untagged original: 240 paragraphs, 3 sections, 8 tables, 11 images. Rounds now
4 (43 ask occurrences -> 23 distinct). Nothing client- or deal-specific
survives anywhere in the package.

TAGGING R3: A NEW REQUIREMENT FOR F3, AND IT WOULD OTHERWISE HAVE SHIPPED.
The template's properties now read "<School Name>", "<School Signatory>" and
so on. NOTHING FILLS THEM: tagfill writes paragraphs. So unless _write_mou
sets the built document's core properties from the filled values, every MOU
this pipeline produces will carry literal tag text in its Word properties.
F3 must set at least dc:title (the client), dc:subject (the programme) and
clear dc:creator/cp:category, and there must be a test for it. Recorded here
because it is exactly the class of defect that a green suite does not catch.

TAGGING R3: TWO THINGS REPORTED AND DELIBERATELY NOT FIXED, both pre-existing
in the owner's original.
  (1) word/_rels/settings.xml.rels still points at
      file:////Users/SunilaJohnson/Documents/Telaverge Communications/...
      - the attached template on a staff member's own machine. That leaks an
      employee's name and folder structure to every client who receives the
      file. Stripping a RELATIONSHIP is a different class of change from
      neutralising a property value, so it is the owner's call.
  (2) The three broken Word field references (ordinals 209, 232, 236) reading
      "Error! Reference source not found." and "Error! No text of specified
      style in document." are still there and still need repairing in Word.

Task F1: THE COLLAPSE KEY IS (raw, context), NOT raw, AND THE FIRST VERSION
WAS A REAL BUG. Keying on the literal alone gives four different lab items one
answer: the tagged proposal's `<ask:1 Unit>` appears four times with the
contexts "Magazine Rack", "Projector", "Audio and Mic System" and "First Aid
Box", and the MOU's `<ask:Yes>` seven times, once per deliverables row. That
is the replace_token bug D1 exists to prevent, arriving at the QUESTION layer
instead of the writing layer. It broke six of the proposal flow's own tests,
which is how it was caught - the guards earned their keep.

Task F1: limit=None MUST STAY UNCOLLAPSED. apply_answers calls
open_questions(limit=None) and hands the result straight to answer_round, so
collapsing there shows the model one of five <ask:75> and leaves the other
four open for ever - a fill that can never finish, invisible until a document
has a repeated literal. Six is what a PERSON is shown (D5); the model gets
everything (C3, D8). The mutation fails nine tests.

Task F1: SECTION GROUPING IS MOU-ONLY, and that is the spec being enforced
rather than a convenience. Applying it to proposals turned their first round
from six questions into two and broke the golden proposal test. D5 chose flat
rounds of six deliberately, the tagged proposal has sixteen tags in one
section, and spec section 10 says the proposal flow's behaviour does not
change.

Task F1: THE SECTION HEURISTIC WAS WRONG AND ONLY THE REAL DOCUMENT SHOWED
IT. Matching any style with "Head" in its name matches `TableHead1` - the
style of every table HEADER CELL in the owner's MOU - so 26 of them became
sections and the fill fragmented into NINE rounds, with "Specifications",
"Details", "First Instalment" and even "Date: <ask:date of signing>" each
getting a round. Every synthetic fixture used python-docx's add_heading, which
yields `Heading2`, and a substring test matches that too, so NOTHING CAUGHT
IT. Narrowed to styles that start with Heading or Title, and a test now builds
a TableHead1 paragraph directly so the loose match fails.

Task F1: THE SHARED SCANNER WAS FIXED AT THE OWNER'S PROMPT - "what will
happen if similar kind of thing happens in the proposal creation path?" A row
label made only of digits is a serial number, not a label. The MOU's
deliverables table numbers its rows and names the deliverable in column 1, so
seven `<ask:Yes>` were labelled "2", "4", "6" - unanswerable. They now read
"R&D engineer", "GEN-i internship", "Innovation Fest", "Project assistance".
The owner was right that this is not MOU-specific: any proposal template with
a numbered column had the same latent defect. Tables whose first column is the
item name are byte-identical - 89 tag and golden tests pass unchanged - and
there is a test in BOTH directions so nobody "fixes" it back.

Task F1: MEASURED ON THE REAL DOCUMENT. Seven coherent sections after the
heading fix; ten rounds in a simulation that marks only exact (raw, context)
matches as settled. THE REAL CONVERSATION WILL BE SHORTER: C3 sends the model
every outstanding question, so answering "Innovation Nexus" once settles all
four occurrences (D8). The simulation cannot model that, and the honest figure
will not be known until G1 runs it against a live model. FOR THE OWNER: the
earlier "3 rounds" and "4 rounds" figures were both wrong - the first because
the heading heuristic was broken, the second because it assumed a collapse
that would have been a bug.

Task F1: COMMITTED ca2d1a5, four paths. tests/docx 459 (446 before, +13).
Backend 862 passed / 1 failed. Eight mutations, all caught.

---

Task F2: THREE PARTS. app/services/mou_arithmetic.py (pure, Decimal, 28
tests), docx_tagfill.propose_relations (9 tests), and the wiring into
open_session and review_lines (4 end-to-end tests). 41 tests, 8 mutations, all
caught.

Task F2: D15 HOLDS BY CONSTRUCTION, NOT BY PROMPT WORDING. The model is asked
only WHICH TAGS RELATE - tag ids and an operator - and a relation is REBUILT
from result/op/operands, so a model that attaches "value": "Rs. 3,00,000" has
it dropped. Pinned by test_the_model_cannot_smuggle_a_figure_through. The
check's only output is a sentence; the written value stays exactly what the
person typed, pinned by its own assertion.

Task F2: IT REFUSES TO GUESS, AND THAT IS THE DESIGN. parse_amount returns
None for a range ("Rs. 15,00,000/- to Rs. 25,00,000/-" - the proposal flow's
own ask_calculate default), for "1 Set", and for "second week of February
2027", which contains exactly one number and is not an amount. Without the
bare-amount check the year would be read out of a completion date and compared
to a price. A spurious warning on a negotiated figure teaches the reader to
dismiss the warnings, which destroys the only thing this check is for.

Task F2: A TEST OF MINE WAS WRONG AND THE CODE WAS RIGHT. The end-to-end test
first supplied the figures through the model's first pass and got no values at
all - because fill_scrub refuses a money-shaped value the MODEL wrote (C2) and
ask_calculate always asks whatever the confidence (D4). A figure exists only
after a PERSON answers, so the test now goes through a real clarification
turn. That is the path a real fill takes.

Task F2: THE STALE-PYC TRAP AGAIN, IN A NEW PLACE. M2 hardened the RESTORE
(shutil.move reuses the backup's mtime). Here it was consecutive MUTATIONS
writing the same file within one second: pytest's cache is keyed on
(mtime, size), so a same-length mutation is served the previous mutant's
bytecode and reads as a survivor. The harness now purges __pycache__ before
every run. FOR THE NEXT SESSION: any tool that rewrites a file and re-runs
pytest in a loop can serve you the previous version.

Task F2: ONE EQUIVALENT MUTANT, DOCUMENTED RATHER THAN LEFT AS A SURVIVOR.
Relaxing parse_amount's "exactly one number" guard to "at least one" survives
with zero failures, and should: _is_a_bare_amount independently rejects the
same input, because removing the first number from a range leaves the second
behind. The two guards overlap on purpose and no input distinguishes them.

Task F2: THE APPROVAL GATE MOVED TO A2. The plan put "an approval with a
mismatch standing is refused once" in F2, but confirm_*_values is an AGENT
tool and the MOU's does not exist until A2. The service half - relations
stored, mismatches surfaced on the review line - is done here; A2 adds the
gate and the arithmetic_ack flag.

Task F2: COMMITTED 06e85d1, six paths. tests/docx 500 (459 before, +41).
Backend 903 passed / 1 failed - the pre-existing test_relationship_screens and
nothing else. Dirty 91 before and after.

Task F2: WHAT F3 MUST NOT FORGET. The tagged template's document PROPERTIES
now read "<School Name>", "<Program name>", "<School Signatory>" and so on,
because a client's name in dc:title/app.xml/CoverPageProperties would
otherwise ship to a different school. NOTHING FILLS THEM - tagfill writes
paragraphs, and document properties are not paragraphs. _write_mou MUST set
the built document's core properties from the filled values, or every MOU this
pipeline produces carries literal tag text in its Word properties. There must
be a test for it.

HANDOVER (10 Sep, end of the session that built M1-M3, U1, F1, F2 and tagged
the MOU). STATE: branch feature/docx-proposal-templates, HEAD 06e85d1, 53
commits from aa49e80, dirty 91. Backend in isolation 718 passed / 54 skipped;
working tree 903 passed / 1 failed (the pre-existing
test_relationship_screens, and nothing else); tests/docx 500. Console and
Android UNTOUCHED this session and still at 707 and 61.

HANDOVER: FOUR DOCUMENTS UPDATED so the next session cannot be misled.
  (1) The PLAN gained a "Â§0 Amendments" block (A..P) immediately before Global
      Constraints, declared authoritative where it contradicts anything below:
      fifteen tasks not fourteen, U2 deferred to second-last by the owner, M1
      absorbing U1's route field, F2's approval gate moving to A2, the
      (raw, context) collapse key, limit=None staying uncollapsed, section
      grouping being MOU-only, the heading STYLE PREFIX, tags.py having been
      changed after all, the tagging's three passes, the metadata defect F3
      must close, the withdrawn round-count projections, both mutation-harness
      traps, the three marker failures, the WAL copy rule, and the wrong
      restart path.
  (2) The SPEC gained a "Â§12 Corrections" section and a banner at the top
      pointing at it. Ten numbered corrections, authoritative over the rest.
  (3) This LEDGER carries every measurement and ruling, task by task.
  (4) A NEXT-SESSION-PROMPT was written to
      docs/superpowers/plans/2026-09-09-mou-pipeline-NEXT-SESSION-PROMPT.md.
      It carries the ssh helpers verbatim, TEN rules (four more than the
      simple flow's six: the marker rule was rewritten, and three are new --
      never sed a script's own string literals, the mutation-harness traps,
      and copying a live SQLite database through SQLite), the state, what is
      done with commit hashes, what is left in order, F3's three requirements
      with the properties defect called out, the four lessons, and the five
      open questions for the owner.

HANDOVER: WHERE TO RESUME. F3 -- build the MOU document. Its three parts are
_write_mou (refuse on skipped, refresh a static index, PDF non-fatally,
idempotence checked BEFORE status), the correction path (same row, revision,
clear pdf_path, refuse once sent), and THE DOCUMENT PROPERTIES, which is a
defect that would otherwise ship: the template's dc:title reads "<School Name>"
and nothing fills it, because tagfill writes paragraphs and properties are not
paragraphs.

HANDOVER: FIVE THINGS ARE THE OWNER'S, none blocking. The "ask me" grammar
question; whether to strip the attached-template link naming a staff member;
repairing the three broken Word fields at ordinals 209/232/236; whether to fix
the rate-card migration's WAL-less backup; and (already decided) that a built
MOU appears on the client screen and in the chat, never in the pipeline.

---

Task F3: BASELINE RE-MEASURED FIRST, as the handover required rather than
copied from it. Branch feature/docx-proposal-templates at 06e85d1, 53 commits,
dirty 91. Backend working tree 903 passed / 1 failed - the pre-existing
test_relationship_screens::test_the_worst_neglected_client_is_first and
nothing else, no time-of-day failures at 09:27 UTC. tests/docx 500. The
handover's numbers are confirmed exactly.

Task F3: THREE PARTS, and the third was the one that would have shipped
broken. _write_mou and the dispatch in build; the correction path; and the
DOCUMENT PROPERTIES, which no tag can reach. 45 new tests, 31 mutations.

Task F3: A DECISION WAS PUT TO THE OWNER BEFORE ANY SCHEMA CHANGE, and they
chose to keep the history. Plan step 5 says the correction path should "save a
revision". ProposalRevision cannot be reused and that is not a preference:
its foreign key is proposal_id -> proposals.id, it carries line_items and
total_amount (the exact commercial columns D-A removes so that no aggregate
can pick an MOU up), and mou_documents is wiped BEFORE proposal_revisions, so
a revision row pointing at an MOU would be orphaned by a reset. So it meant a
new table. Against it: NOTHING in the planned MOU surface reads revisions -
for proposals they feed client_dossier, api/proposals.py and approval_engine,
while an MOU is out of the pipeline and R1 is only GET /mous/{id} plus the
lead's `mous` key. That is lesson 2 exactly, "ask whether the premise
travels", so it was asked rather than assumed. THE OWNER CHOSE TO KEEP THE
HISTORY. MouRevision ships in app/models/mou.py.

Task F3: THE PROPERTIES DEFECT IS CLOSED, and app/services/docx/properties.py
is the exact inverse of the tagging script's _neutralise_metadata. Written the
same way for the same reason - parsed with lxml and rewritten element by
element, never by string replacement, because pasting a tag's angle brackets
into XML text produces a package Word refuses to open, which is what the first
version of the neutraliser did. It reuses tags.TAG_RE rather than restating
the grammar, so a literal that is a tag on the page is a tag in a property and
the two cannot drift apart.

Task F3: WHAT IT WRITES, AND WHAT IT REFUSES TO GUESS. Every tag-shaped run in
any of the four property parts is replaced by the value that literal settled
on. A LITERAL IT CANNOT FILL IS BLANKED, NEVER LEFT STANDING - a signed
contract whose properties read "<School Name>" is the defect, not a smaller
version of it. A literal whose occurrences DISAGREE also yields nothing: F1's
(raw, context) key exists because one literal is often several questions, and
the MOU's <ask:Yes> is once per deliverables row, so picking one of seven
answers to stand for the property would be arbitrary. Blank is honest.

Task F3: dc:title AND dc:subject COME FROM THE LEAD AND THE PROGRAMME, not
from a filled literal. They are what the document IS rather than a guess about
it, and they are right even for a template that never tagged its properties.
dc:creator, cp:keywords, cp:category and cp:lastModifiedBy are CLEARED: the
owner's template carried the SCHOOL'S own signatory as dc:creator, so an MOU
would otherwise go out authored by a person at the previous client, and
lastModifiedBy is a member of YuviPep staff. Blank rather than "YuviPep",
because naming ourselves as the author of a document the client signs is a
claim and an empty field makes none. FOR THE OWNER: say so if they would
rather it read YuviPep.

Task F3: THE ORDER OF refresh_static AND THE PROPERTIES IS NOT COSMETIC, and
nothing in the suite could show it until a test was written for it. The
properties are filled AFTER the contents page is re-measured, because
LibreOffice rewrites the WHOLE package - anything written before it is written
into bytes that are about to be replaced. No test can run a real LibreOffice,
so the re-measure is stubbed with one that does the part that matters: it
hands back the template's own core.xml.

Task F3: A MUTATION FOUND A TEST OF MINE THAT PASSED IN BOTH DIRECTIONS. The
ordering mutation was "killed" by an unrelated test while
test_the_stated_title_wins_over_whatever_a_literal_would_have_given passed
either way - because once _set_core writes a clean title there is no literal
left for a second pass to find. The property that really discriminates is a
CLIENT WHOSE OWN NAME HAS ANGLE BRACKETS: a lead called "Orchid <Pvt> Ltd"
matches the tag grammar, and filling literals after the title would blank the
client out of their own contract. That is now its own test, and the weaker one
is kept with a note saying it pins the outcome but does not discriminate.

Task F3: FIVE TESTS PASSED AGAINST A PROPOSAL AND I NEARLY KEPT THEM. The
first red run showed 15 failures, not 20: a PDF is attached, a static contents
page is refreshed, a file is written anew and filled_json carries the same
eight keys whichever document type build returns. The _built fixture now
asserts isinstance(mou, MouDocument) itself, because a fixture that hands back
the wrong document type quietly makes every test below it a statement about
the proposal flow.

Task F3: THE SENT TEST PROVED HALF OF WHAT IT CLAIMED, and a surviving mutant
is how that was found. It set BOTH status = sent AND sent_at, so deleting the
status branch survived - the timestamp still refused the correction. Split
into two tests, one per branch. Both branches are checked on purpose: a send
that recorded when it went and then failed to move the status still means the
client is holding the document.

Task F3: TWO MUTATIONS KILLED FOR THE WRONG REASON AND WERE CORRECTED. Their
`old` spans ended mid-block, so the replacement absorbed the following
dispatch lines into an `if` above them - one reported 16 failures and the
other 19, which is not a mutation being caught but a file being broken. Fixed
to span whole blocks; each now kills exactly ONE test, the one named for it. A
mutation that kills accidentally is false confidence, which is the same class
of fault as a surviving mutant that is really a harness bug.

Task F3: THE HARNESS READ A LOG LINE AS A COLLECTION ERROR. Amendment M(b)
says a mutant that cannot import proves nothing, so the harness treated any
line matching ^ERROR as that. pytest's captured-log section prints
"ERROR    app.services..." for every logger.exception - so the stale-PDF
mutation, whose whole point is to make the service log an error, was reported
as "does not import" while its named test had in fact failed. Now read from
pytest's own count line instead. FOR THE NEXT SESSION: amendment M's lesson
arrived through the harness rather than the code, again.

Task F3: RULE 3 BIT ME EXACTLY AS WRITTEN. Patching patch_tests.py's own
string literals with a Python replace produced a NameError at run time
(BLOCK_SENTINEL removed, its use left behind). Rewritten whole with the Write
tool, which is what rule 3 says to do. The two runs the rule prescribes are
what caught it.

Task F3: THE TEST PATCH REPLACES ITS BLOCK RATHER THAN APPENDING IT, so
re-running after editing the block file updates the file instead of silently
keeping the first version - the "edit skipped itself and reported success"
failure amendment N records, arriving from the other direction.

Task F3: 6a WAS NEEDED FOR REAL AND THE TWO TREES DISAGREE BY TWO. The working
tree asserted (4, 2, 8, 46) over 60 tables, HEAD asserted (4, 2, 8, 44) over
58. Both were incremented by one from what each tree itself said, never
written literally, and the patch script was run against the working tree AND
against a git archive HEAD export. The committed blob was verified to be
HEAD + the edit and nothing else: diffing it against HEAD:app/core/
reset_taxonomy.py shows only the mou_revisions entry.

Task F3: THE COMMITTED TREE PASSES ITS OWN TESTS IN ISOLATION. A git archive
HEAD export runs tests/test_reset_taxonomy.py, tests/test_dashboard_reset.py
and tests/docx at 512 passed / 54 skipped, with the (4, 2, 8, 45) over 59 pins
green - which is the check that 6a produced a CONSISTENT commit rather than
merely a plausible one.

Task F3: SCOPE HELD IN TWO PLACES ON PURPOSE. (1) The properties are filled
for MOUs ONLY, gated on is_mou. A proposal template's properties were never
neutralised so there is nothing to fill, and writing the client into them
anyway is a change to a flow section 10 says this project does not change; a
test pins that a proposal build's properties are untouched. FOR THE OWNER: the
proposal flow has the SAME latent defect if a proposal template ever carries a
client in its properties, and that is reported rather than fixed because the
fix changes their proposals. (2) Only the three messages this task owns say
"MOU" - the two in build and the one in _skipped_message. The rest of the
shared status machine still says "proposal"; A2 owns what the agent says.

Task F3: THE MOU'S FILES GO IN THE PROPOSALS STORAGE FOLDER, deliberately.
storage.py is one of the 91 dirty paths, so adding a CATEGORY_MOUS would have
cost a third 6a edit for a purely cosmetic gain - the stored path is what
every read resolves and the category only names a folder. Recorded here as a
decision rather than an oversight. FOR THE OWNER: worth a line in E1 if they
want contracts filed separately.

Task F3: TESTS. tests/docx 545 passed (500 before, +45). Backend working tree
948 passed / 1 failed (903 before, +45) - the pre-existing
test_relationship_screens and nothing else. 31 mutations across two specs, all
31 killed by the test named for them, with no equivalent mutants recorded this
task.

Task F3: COMMITTED f2c3ac6, seven paths - app/models/mou.py,
app/services/docx/properties.py (new), app/services/proposal_fill_service.py,
tests/docx/test_mou_fill.py, tests/docx/test_mou_properties.py (new), and
through 6a app/core/reset_taxonomy.py and tests/test_reset_taxonomy.py. Dirty
91 before, 96 while working, 91 after. No Dashboard/dist and nothing under
docs/.

Task F3: DEPLOYED, and the restart is what built the table. mou_revisions did
not exist on the live database before it and has 9 columns after;
mou_documents is unchanged at 17. Verified over the PUBLIC url, not just
locally: /docs and /health both 200 through
https://noninfluential-lamonica-unobservantly.ngrok-free.dev , and 8010 200
locally.

Task F3: WHAT THE OWNER CANNOT YET TEST, and this is the honest limit of F3.
An MOU still cannot be built FROM THE CHAT: the agent has no create_mou tool
until A2, and the tool-CHOICE test is A3. Everything here is reachable only
through the service. So the phone-through-ngrok test that found three of the
simple flow's defects cannot run on this task, and nothing in F3 has been seen
by a human through the app. G1 is the first point at which it can be.

Task F3: WHERE TO RESUME. A1 - extract the fill handlers to
app/ai/agents/fill_tools.py, a pure refactor with no behaviour change - then
A2, which owns the MOU tools, the system prompt in the SAME commit, the router
line, the loop-breaker, the editing refusals AND F2's approval gate with its
arithmetic_ack flag (plan amendment D). A2 must also make the WRONG tool
harmless: create_mou on an open fill returns {already_open, still_to_answer,
what_to_do} naming the right tool.

---

Task A1: A PURE MOVE, AND THE COUNTS ARE THE PROOF. _question_line,
_round_message, _round_candidates, _review_message and _group, plus
ALL_DEFAULTS, APPROVE and _ORIGIN, moved from proposal_agent.py to
app/ai/agents/fill_tools.py. 1,081 lines becomes 958. They are imported back
under the names they already had, so every call site inside the agent is
untouched and so are the two tests that reach for proposal_agent._group and
proposal_agent._review_message by those private names.

Task A1: THE EXISTING SUITES PASSED UNCHANGED, which is the task's own
contract. tests/docx/test_fill_agent.py and test_fill_build.py: 51 passed with
both files BYTE-IDENTICAL TO HEAD, verified with git diff before the run.
tests/docx held at 545 and the backend at 948 / 1 - exactly the counts before
the move.

Task A1: THE MOVE WAS ALSO DIFFED, not merely tested. HEAD's copy of the block
was extracted, the six renames applied mechanically, and every non-blank line
compared against fill_tools.py. One line differs: a continuation line's
indentation, shifted by one space because _round_message lost a character from
its name. Everything else added is the module docstring and its two imports.
A green suite is weaker evidence than this for a refactor, because a suite
that never touched a line cannot notice it changing.

Task A1: WHICH IS EXACTLY WHAT HAPPENED - A MUTATION FOUND A GAP THE MOVE MADE
VISIBLE. Nothing asserted question_line's `about` or `suggested` fields.
Deleting the row label that tells four <ask:1 Unit> apart (D9) left the WHOLE
suite green while the app would have shown four identical questions. The
neighbouring test asserts only tag_id and question. The gap predates A1; the
move is what made it visible.

Task A1: A TEST WAS ADDED, NOT CHANGED, and the order matters for the
contract. The unchanged suites were run and verified FIRST - 51 passed,
byte-identical - and only then was
test_each_question_says_where_in_the_document_it_is added beside its
neighbour. Five mutations now, all killed by the test named for them. Its
first draft collided on a programme code (JONEG was already taken by the next
test, 409 Conflict); JONEK.

Task A1: NO document_type PARAMETER WAS ADDED, deliberately, and the plan's
step 1 asks for one "where the wording differs". Nothing calls these with
"mou" until A2, so any parameter added here would be untested dead code, and
the task's headline is "no behaviour change". A2 has the caller and the test;
it adds the parameter. What actually differs is measured in the next entry.

Task A1: FOR A2, MEASURED HERE AND NOT FIXED HERE. review_message prints a
HARDCODED sentence - "check this one -- it reads like a price, and prices
normally come from the rate card" - whenever a row carries a warning, and
DISCARDS row["warnings"]'s own text. For a proposal that is right: the warning
there is D10's price fence. For an MOU it is wrong. F2's arithmetic check
produces a sentence naming which two of the person's own answers disagree
("Rs. 2,50,000 is not Rs. 4000 x 75"), review_lines already carries it, and
saying "it reads like a price" instead hides the finding that D-E exists to
surface. THIS IS THE ONE PLACE THE WORDING GENUINELY DIFFERS.

Task A1: TESTS. tests/docx 546 passed (545 before, +1 - the added test).
Backend working tree 949 passed / 1 failed (948 before, +1) - the pre-existing
test_relationship_screens and nothing else. Five mutations, all killed.

Task A1: COMMITTED 7912e93, three paths - app/ai/agents/fill_tools.py (new),
app/ai/agents/proposal_agent.py, tests/docx/test_fill_agent.py. All three
clean at HEAD, so all three plain adds and no 6a. Dirty 91 before, 94 while
working, 91 after. Verified in a git archive HEAD export: tests/docx 492
passed / 54 skipped in isolation.

Task A1: DEPLOYED. Restarted and verified over the PUBLIC url - /docs and
/health both 200. A refactor changes nothing a user can see, but leaving the
running process on modules that no longer exist on disk is how a later
"cannot reproduce" starts.

Task A1: WHERE TO RESUME. A2 - the MOU tools, the system prompt IN THE SAME
COMMIT, the router line, the loop-breaker, the editing refusals, and F2's
approval gate with its arithmetic_ack flag (plan amendment D). Also the
review_message wording above. A2 is much the biggest of the remaining tasks
and the one the last session lost three days to: the tools and the words that
describe them ship together, and create_mou on an open fill must RETURN
{already_open, still_to_answer, what_to_do} naming the right tool rather than
re-raising the round.

---

Task A2: ONE COMMIT, AND THAT IS THE WHOLE LESSON. Six tools, the
system-prompt paragraph that names them, and the router line, in 69cee9a. J1
added the fill tools and never told the agent they existed; a tool the prompt
does not mention is a tool the model does not call, and that cost three days.

Task A2: THE HANDLERS ARE PARAMETERISED, NOT COPIED. _open_fill,
_answer_questions, _show_questions, _fill_in_hand, _round, _confirm_values,
_correct_built and _show_review all take document_type, and the six MOU tools
are thin wrappers. proposal_agent went 958 -> 1271 lines; a copy would have
doubled it, which is what A1 existed to prevent.

Task A2: THE WRONG TOOL IS HARMLESS, AND THE TOOL NAMES COME FROM THE
DOCUMENT TYPE. create_mou on an open fill returns {already_open,
still_to_answer, what_to_do}. fill_tools.TOOLS maps each document type to its
five tool names, so a contract's model is never told to call
answer_proposal_questions - which would be the same loop wearing a new hat.
Mutating that map to always say "proposal" is caught by the loop-breaker test.

Task A2: create_mou HAS NO FALLBACK BRANCH, deliberately, and this is where it
differs from create_proposal. A programme with no MOU template gets a sentence
saying so and nothing is built. Falling through to a proposal would build the
document that programme probably DOES have a template for, which is the wrong
document entirely (D-A). Mutation "create_mou builds a proposal when there is
no MOU template" is caught.

Task A2: THE EDITING GUARD RUNS BEFORE _resolve_proposal, and that ordering IS
the fix. Defect 3 refused only because the instruction happened to contain a
price and tripped the price fence. Asked what the code does on the path that
does NOT trip it: _resolve_proposal falls back to the client's most recent
proposal when handed a name, so "make it warmer" in an MOU conversation could
rewrite an unrelated PROPOSAL for the same client and report success over a
document nobody mentioned. There is a test that builds exactly that situation
- an MOU conversation, an unrelated proposal for the same lead, an
edit_narrative call carrying the client's name - and asserts the proposal's
content_md is unchanged afterwards. _mou_in_hand asks about the CONVERSATION,
never about what _resolve_proposal manages to find.

Task A2: F2'S APPROVAL GATE LANDED HERE, per plan amendment D. An approval
with a mismatch standing is refused ONCE, naming which two of the person's own
answers disagree. Refusing twice would teach the reader to dismiss the
warnings, which destroys the only thing they are for - a negotiated total that
is not price x students is a normal thing for a contract to contain.
arithmetic_ack is written on the result tag; _record clears it whenever a pass
touches the result OR any operand. Both halves are mutation-checked
separately, and "only the result tag clears, not its operands" is caught.

Task A2: THE GATE IS A NO-OP FOR PROPOSALS BY CONSTRUCTION, not by an if.
Relations are proposed for MOUs only (F2), so unacknowledged_arithmetic is
empty for a proposal and the gate never fires. Pinned by
test_a_proposal_approval_is_never_gated_on_arithmetic, because "it happens not
to fire" and "it cannot fire" are different claims and only the second is
worth having.

Task A2: A1'S FINDING IS CLOSED HERE. review_message printed a hardcoded "it
reads like a price, and prices normally come from the rate card" for EVERY
warning and discarded the warning's own text. The scrubber's reasons are
machine codes (unlocked_price, markdown_markers) and D-E's mismatch is a
sentence, so _WARNING maps each code to words and anything unrecognised is
rendered VERBATIM. Saying "it reads like a price" over "this reads
Rs. 2,50,000, but Rs. 4,000 x 75 is Rs. 3,00,000" hid the one thing D-E does.

Task A2: FIVE TEST FAILURES THAT WERE ALL MINE, NOT THE CODE'S. Three were
one cause: /assistant/command requires a session_id of at least 8 characters
and "chat-a8" is seven, so the route 422'd and the test read a KeyError on
'actions'. The other two were a Proposal fixture missing its NOT NULL
template_id, and org_a["org_id"] where the fixture's key is "id".

Task A2: A TEST PASSED ALONE AND FAILED IN THE SUITE, and the cause was an
assertion of mine over the WHOLE table. The no-MOU-template test asserted
select(Proposal) was empty; other tests in tests/docx have every right to
create proposals. Scoped to the lead. Same shape as the stale-pyc failure this
ledger records, from a different direction: a test is only as isolated as its
narrowest assertion.

Task A2: FIVE PYTEST WARNINGS INTRODUCED AND REMOVED BEFORE COMMITTING.
pytest.ini already sets asyncio_mode = auto, so a module-level
pytestmark = pytest.mark.asyncio is redundant AND warns on every SYNC test in
the file. Dropped; async tests are collected anyway.

Task A2: TWO MUTATIONS SURVIVED AND NEITHER WAS A CODE GAP - both were too
SMALL to remove what the test checks. Stripping one line of the prompt left
the other twelve, which still name every tool; deleting one line of the router
block left "MOUs" in the line above it. Rewritten as the full reversions the
plan's table actually names - the whole paragraph, and the router line as it
read before A2 - and both are then caught. A mutation too small to matter
reports a gap that is not there, which is the mirror image of one that kills
for the wrong reason.

Task A2: THE PARAGRAPH WAS EXTRACTED FROM THE FILE, NOT TRANSCRIBED. Writing
the 13-line prompt paragraph into the mutation spec by hand produced a JSON
string carrying real newlines where the source has the two-character escape,
and the harness reported BAD SPEC. The fix reads the exact bytes out of
proposal_agent.py and writes them into the spec. FOR THE NEXT SESSION: never
hand-copy a span into a patch or a spec when the file can be read instead.

Task A2: TESTS. tests/docx 573 passed (546 before, +27). Backend working tree
976 passed / 1 failed (949 before, +27) - the pre-existing
test_relationship_screens and nothing else. 22 mutations, all killed by the
test named for them. Running total for this session: 58 mutations across F3,
A1 and A2, all killed.

Task A2: COMMITTED 69cee9a, five paths - app/ai/agents/proposal_agent.py,
app/ai/agents/fill_tools.py, app/ai/orchestrator.py,
app/services/proposal_fill_service.py, tests/docx/test_mou_agent.py (new). All
clean at HEAD, so all plain adds and no 6a. Dirty 91 before, 96 while working,
91 after. Verified in a git archive HEAD export: tests/docx 519 passed / 54
skipped in isolation.

Task A2: DEPLOYED AND VERIFIED ON THE RUNNING PROCESS, not just in the tests.
The live agent carries 16 tools, six of them the MOU's; its system prompt
contains create_mou; the router prompt contains MOU. /docs and /health both
200 over the public ngrok url.

Task A2: WHAT IS STILL NOT PROVEN, and it is the whole reason A3 exists. Every
test here SCRIPTS ToolCall(name=...). That proves what happens WHEN a tool is
called and never that a model WOULD call it, which is exactly where the last
session's conversation looped. The prompt tests are content assertions, not
routing tests. A3 builds a fake layer driven by the PROMPT it is handed, one
that CAN be wrong, and its step 2 requires proving each test goes red when the
prompt paragraph and the router line are reverted.

Task A2: WHERE TO RESUME. A3 - the tool-CHOICE test, unscripted, in a new
tests/docx/test_tool_choice.py. The plan calls it the single most important
test in it.

---

Task A3: THE FAKE READS THE PROMPT INSTEAD OF BEING TOLD THE ANSWER. It is
handed the real system prompt, the real tool definitions and the real
conversation, and it picks. Its one rule is the lesson itself - a tool the
system prompt does not name is a tool it cannot call - which is not an
arbitrary simplification but exactly the state J1 shipped. The router half
parses the router prompt's own agent list and scores the request against it.

Task A3: IT CAN BE WRONG, WHICH IS THE ENTIRE POINT, AND FOUR TESTS PROVE IT.
They revert A2's prompt paragraph and A2's router line and assert the MOU
tools become unreachable and a contract request stops reaching the agent.
Kept as TESTS rather than done once by hand, because "I checked it goes red"
is precisely the assurance J1 had. One of them derives the pre-A2 prompt by
cutting at the paragraph marker and asserts the marker is present first, so it
cannot silently drift into vacuity.

Task A3: THE FAKE IS WRONG ABOUT THE REPLY TURN AND THAT IS LEFT STANDING.
"this academic year" shares no words with answer_mou_questions, so a bag of
words reaches for create_mou again. That is the September failure reproduced
from first principles rather than described. I could have tuned the scoring
until it guessed right - weighting the last user turn, reading the negation in
"NEVER to create_mou again", adding conversational structure - and each step
would have been a step towards a fake that agrees with itself. STOPPED.

Task A3: WHAT SAVES IT IS THE LOOP-BREAKER, AND NOW THERE IS A TEST THAT
SPENDS IT. The fake follows what_to_do out of a tool result, because A2's own
principle is that a prompt is advice and a tool result is fact. So the turn
goes create_mou -> already_open -> answer_mou_questions, and two tests hold
that: the turn reaches the right tool, and the conversation never opens a
second fill however often the model asks. This is a BETTER test than the plan
sketched: it tests the deterministic guarantee that protects a model with poor
taste, rather than a crude fake's taste.

Task A3: MUTATIONS, and each names what it would cost in production. A2's
prompt paragraph taken away - 5 tests fail. The router line reverted - 5 fail.
The loop-breaker removed - the reply turn never reaches the right tool.
what_to_do stripped of the tool name - the same. create_mou opening a second
fill instead of resuming - the fill count doubles. 5/5 killed by the test
named for them.

Task A3: TWO TESTS PASSED ALONE AND FAILED IN THE SUITE, SAME CLASS AS A2'S
AND A DIFFERENT CAUSE. The lead was named "Sandur Education Centre", which
test_mou_fill and test_mou_models also create; with three leads of that name
resolve_lead is ambiguous, create_mou failed, no fill was opened. A name
unique to this file. FOR THE NEXT SESSION: shared fixture NAMES are as much a
cross-test dependency as shared rows, and this database persists across the
tests in a module.

Task A3: THE FAKE ROUTER HAD THE SAME BUG IN MINIATURE, and it is worth
recording because it is the failure this whole file exists to avoid. Its
agent-list regex ran past the list and swallowed "Request: ..." itself, so
every request matched the LAST agent perfectly - a fake that always agreed
with itself. Then the history block, which sits between the list and the
request, landed in the last agent's description and won every follow-up.
Bounded explicitly to the list, with the history scored separately at half
weight because the prompt itself says a short follow-up continues the earlier
work.

Task A3: THE ROUTER TEST DELIBERATELY DOES NOT USE A PHRASE THE PROMPT QUOTES.
"draw up the memorandum of understanding for Green Valley School" appears
nowhere in the router line; matching one of the line's own examples verbatim
would prove only that string equality works. Its counterpart - a plain
proposal request - must STAY GREEN when the MOU wording is reverted, so that
the MOU test above cannot pass for the wrong reason.

Task A3: TESTS. tests/docx 583 passed (573 before, +10). Backend working tree
986 passed / 1 failed (976 before, +10) - the pre-existing
test_relationship_screens and nothing else. Running total for this session: 63
mutations across F3, A1, A2 and A3, all killed.

Task A3: COMMITTED 5acb36e, ONE path - tests/docx/test_tool_choice.py (new).
Dirty 91 before, 92 while working, 91 after. Verified in a git archive HEAD
export: tests/docx 529 passed / 54 skipped in isolation.

Task A3: NOT DEPLOYED, and deliberately. This task changed no application code
at all - one new test file - so there is nothing for a restart to pick up. The
service is still running A2's code, which is what is committed.

Task A3: WHAT A3 STILL DOES NOT PROVE, said plainly. This is a crude fake, not
a model. It shows that the prompt and the router line are LOAD-BEARING - take
either away and the right tools become unreachable - and that the loop-breaker
recovers a wrong reach. It cannot show that Claude, on the fast tier, picks
create_mou for "draw up the contract". Only G1 against a live model can, and
after that only the owner on a phone. Three of the simple flow's defects came
that way and none from the suite.

Task A3: WHERE TO RESUME. G1 - the golden run over the tagged MOU, against a
live model. It is the first task whose result the owner can see, and the first
point at which the round count is knowable: the plan's 8-9, the spec's 3-4 and
two later simulation figures of 7 and 10 are ALL withdrawn as unverifiable
(amendment L). Do not quote a number until G1 has run.

---

Task G1: STEPS 1 AND 2 WERE ALREADY DONE. scripts/tag_mou_sample.py is
committed and the tagged fixture was built over three passes in the previous
session. G1 here is steps 3-8: the golden suite, the live run, and the round
count.

Task G1: EVERY NUMBER RE-MEASURED RATHER THAN COPIED, and every one agreed
with the ledger. Tagging changed no structure - 240 paragraphs, 3 sections, 8
tables, 11 images, identical between the untagged original and the tagged
copy. 65 occurrences, 33 distinct, 22 semantic / 39 ask / 4 ask_calculate. 0
tags in the untagged original. <School Name> in ten places with ten identities.

Task G1: THE CHECK THAT WAS MISSING IS NOW IN THE SUITE. raw_count walks
word/*.xml and is the body's ground truth - and it is exactly the blind spot
the owner found by hand, because the school's name was in docProps and in
Word's customXml cover-page store. _package_count walks EVERY part of the zip.
It asserts both that the tagged template names nobody AND that the untagged
original did, so it cannot pass by looking in the wrong place.

Task G1: THE PDF IS READ BACK, NOT JUST PRODUCED. A real LibreOffice
conversion of the real contract, opened with pypdf: 8+ pages, a text layer
over 2000 characters, the new client named in it, and neither "Sandur" nor
"Ghorpade" anywhere. The page count is pinned because a conversion that
produced a near-empty PDF would have satisfied every other assertion.

Task G1: COMMITTED 292fb09, one path - tests/docx/test_mou_golden.py (new).
tests/docx 595 (583 before, +12). Backend 998 passed / 1 failed. Dirty 91
before and after.

Task G1: TWO TEST-HARNESS FAULTS OF MINE, BOTH FOUND BEFORE THEY MATTERED.
The ANSWERS map was transcribed from a console listing TRUNCATED AT 48
CHARACTERS, so two keys were wrong and the fill never terminated -- the same
lesson as A2's mutation spec, arriving again: never hand-copy a span when the
file can be read. And the build fixture ran per test, which collided on the
programme code and surfaced as a KeyError on a 409 body; it now builds once.

Task G1: THE LIVE RUN. At the owner's explicit instruction, one full fill
against the REAL model (openrouter, gpt-5.4-nano fast / gemini-2.5-flash
strong) on the LIVE database, with cleanup. Not a test: a test that calls a
real model is flaky by construction and would cost money on every suite run.
The MODEL was real; the PERSON was scripted from the same ANSWERS map, so the
rounds measure what a human reply settles rather than what a simulation
assumes.

Task G1: THE ROUND COUNT IS NINE, AND IT IS THE FIRST HONEST FIGURE. Amendment
L withdrew four projections; here is what a live model actually did.
  12 of 65 tags filled WITHOUT asking (semantic, from the dossier)
  53 outstanding after turn 1
  9 rounds, (shown, settled) per round:
     (6, 9) (6, 11) (5, 8) (2, 3) (6, 6) (4, 4) (4, 4) (5, 5) (3, 3)
THE DESIGN INPUT'S 8-9 WAS RIGHT. The spec's 3-4 was wrong, and so were both
simulations (7 and 10). Amendment L can be closed with a measured number.

Task G1: D8 IS REAL AND MEASURABLE. The first four rounds settled 31 questions
from 19 shown - one answer settling every occurrence of the same fact, which
is precisely what a simulation cannot model and why the earlier figures were
withdrawn. From round 5 on, each round settled exactly what it showed, because
by then the repeated facts were gone and what was left was one question per
row of the deliverables and pricing tables.

Task G1: A ROUND IS NOT ALWAYS SIX, AND THAT IS F1's SECTION GROUPING WORKING.
Round 4 showed two questions with 25 outstanding; rounds 6 and 7 showed four.
QUESTIONS_PER_ROUND is a cap, and an MOU's rounds stop at the section boundary
(amendment G) so a person is never asked about the pricing table and the
signature block in one breath.

Task G1: THE ARITHMETIC CHECK RAN ON REAL FIGURES AND CORRECTLY SAID NOTHING.
The person answered Rs. 4,200 per student, 80 students and Rs. 3,36,000
annually. 4,200 x 80 = 3,36,000 exactly, so D-E raised no warning - 0 of 65
review lines flagged. The check is silent when the arithmetic holds, which is
the only way a warning means anything when it does fire.

Task G1: THE BUILT CONTRACT, over the live fill. 0 tags left anywhere. 0
tag-like properties. dc:title = the client. dc:subject = the programme.
dc:creator = "" (the previous school's signatory is not the author). PDF
produced. ZERO Proposal rows for the lead (D-A).

Task G1: CLEANED UP, AND VERIFIED CLEAN. Every row the probe made was deleted
child-before-parent - 1 revision, 1 fill, 1 mou, 1 template doc, 1 template, 1
programme, 1 lead - and re-queried to confirm nothing was left. THE STORAGE
FILES WERE ORPHANED BY THAT and are a separate cleanup the first version of
the script missed: three files (the template's stored copy, the built .docx
and the .pdf, 4.6 MB) were deleted only after checking that NO surviving row
references them. The public service answered 200 throughout and after.

Task G1: FOR THE OWNER - FOUR QUESTIONS ARE PUT TO A PERSON AS RAW TAG TEXT.
Ordinals 154, 155, 156 and 157 - the Pricing Details block - carry NO context
label, so `_question_line` falls back to the raw literal and round 7 asked
this, verbatim:
    <ask:75>
    <ask_calculate:Rs. 4000/- net (including GST) per student annually.>
    <ask_calculate:Rs. 3,00,000/- Net (Including GST).>
    <ask:Innovation Nexus>
A salesperson is being shown the template's internals. It is 4 of 43 asks and
it is not a blocker, but it is the same CLASS as the numbered-row-label defect
the owner had fixed in the shared scanner (amendment I): a question a person
cannot answer from. NOT FIXED HERE - it is a change to tags.py's context
extraction and affects the proposal flow too, so it is the owner's call, as
that one was.

Task G1: FOR THE OWNER - ONE CONTEXT LABEL READS "MoU for MoU for - MoU for".
Two occurrences of <ask:Innovation Nexus> carry it. The row-label logic is
repeating a phrase rather than describing the cell. Same class, same call.

Task G1: FOR THE OWNER - THE THREE BROKEN WORD FIELDS ARE STILL THERE, at walk
ordinals 209, 232 and 236, reading "Error! Reference source not found." and
"Error! No text of specified style in document." They print into every MOU
built from this template. The golden suite does not fail while they are there;
it fails if the BUILD starts adding or dropping them.

Task G1: WHAT G1 PROVES AND WHAT IT DOES NOT. It proves the pipeline works
end to end against a real model on a real contract: nine rounds, a clean
document, correct properties, a real PDF, no Proposal row. It does NOT prove
the agent picks the right tools in a real chat - the live run drove the
SERVICE directly, not the agent - and it has still never been seen by a human
through the app, because R1 and R2 do not exist. Three of the simple flow's
defects came that way and none from the suite.

Task G1: WHERE TO RESUME. R1 - GET /mous/{id} and the lead's `mous` key - then
R2, the Android side. Those two are what put a built contract in front of the
owner on a phone.

---

Task R1: THE SEPARATION IS THE WHOLE TASK, and it is D-A arriving at the API
boundary rather than staying in the schema. GET /leads/{id} gains a SEPARATE
`mous` key; an MOU never appears in that response's `proposals` list. A
contract merged into that list would arrive on an already-closed deal, because
inbound_engine reads a SENT proposal as "the deal is agreed".

Task R1: THE TEST THAT HOLDS IT GIVES ONE LEAD BOTH DOCUMENTS. A contract and
an ordinary proposal for the same client, so neither list can pass by being
empty and neither id can be absent by accident. Two mutations attack it -- the
mous key emptied, and the MOUs appended to the proposals list -- and both are
caught.

Task R1: NO COMMERCIAL FIELD IS IN THE PAYLOAD, and there is a test naming
each absent one. MouDocument has no total_amount, line_items or currency, so a
screen that sums a client's documents cannot pick a contract up if the number
is not there to be summed. Adding "total_amount": 0.0 to the serialiser is
caught by test_the_route_carries_no_commercial_fields.

Task R1: SCOPING IS 404, NEVER 403, AND THE ORG FILTER IS IN THE WHERE CLAUSE.
Telling a stranger that an id exists is itself a leak, and a check that runs
after the row is in hand is a check somebody will one day move. A mutation
that answers 403 instead of 404 is caught by the cross-org test.

Task R1: TWO DELIBERATE DEVIATIONS FROM THE PLAN'S WORDS, recorded rather than
quietly taken.
  (1) The plan asks GET /mous/{id} to return "both file paths". A storage key
      is USELESS to a client -- nothing serves one -- so the payload says
      whether each file exists (has_docx, has_pdf) and a download route serves
      it. That is this project's own idiom: proposals do exactly this.
  (2) That download route, /mous/{id}/download?format=, is NOT in R1's file
      list. Without it the client screen can describe a contract it cannot
      open, and R2 is next. A missing PDF is CONVERTED there rather than
      refused, which is the retry F3's deliberately non-fatal converter always
      implied ("a converter that is down costs a retry at send time").

Task R1: 6a FOR TWO FILES, AND THE TREES REALLY DO DIVERGE. app/main.py and
app/api/leads.py are both among the 91. HEAD's main.py imports neither
`documentation` nor `relationships`; HEAD's leads.py is about 150 lines
shorter than the tree's. So every anchor was checked to appear EXACTLY ONCE IN
EACH TREE before it was used, the patch was run against the working tree AND a
git archive HEAD export, and the export's blobs were staged with git
hash-object + git update-index. Verified AFTER staging, with cmp rather than a
pipeline whose exit code head() swallows: each staged blob differs from HEAD
by only my edit (main.py +3 lines, leads.py +20) and differs from the working
tree.

Task R1: A VERIFICATION OF MINE WAS BACKWARDS AND SAID SO LOUDLY. `diff a b |
head -4 && echo same || echo differs` reports SAME whatever diff found,
because head exits 0. The real check is cmp with its own exit code. The blobs
were right; the check was not, and a check that cannot fail is the same class
of fault as a test that cannot.

Task R1: A TEST OF MINE SURVIVED ITS OWN MUTATION AND WAS REWRITTEN. The
revisions test built ONE revision, so ordering ascending instead of descending
passed every assertion it made -- with one row there is no order to get wrong.
It now makes a real correction first and pins [2, 1], and asserts the contract
is still at the id the salesperson already holds.

Task R1: ONE EQUIVALENT MUTANT, DOCUMENTED RATHER THAN LEFT AS A SURVIVOR.
Dropping the org filter from the lead's MOU query changes nothing: the route
resolves the lead through lead_service.get_lead(db, ctx.org_id, lead_id) and
raises before any sub-query, and a lead id belongs to exactly one
organisation. THE FILTER STAYS -- every sibling query in that route (Contact,
ActionItem, Meeting, Proposal) carries the same redundant one, and the MOU
query should not be the odd one out. A tenth mutation was withdrawn as
nonsense before it ran: it referenced a name before assignment and was a
no-op.

Task R1: TESTS. tests/docx 606 passed (595 before, +11). Backend working tree
1009 passed / 1 failed (998 before, +11) - the pre-existing
test_relationship_screens and nothing else. Eight mutations, all killed by the
test named for them.

Task R1: COMMITTED db751c9, four paths - app/api/mous.py (new),
tests/docx/test_mou_api.py (new), and through 6a app/main.py and
app/api/leads.py. Dirty 91 before, 93 while working, 91 after. Verified in a
git archive HEAD export: tests/docx plus tests/test_leads.py, 546 passed / 66
skipped in isolation.

Task R1: DEPLOYED AND VERIFIED ON THE PUBLIC URL, not just locally. The
routes appear in the public OpenAPI as /api/v1/mous/{mou_id} and
/api/v1/mous/{mou_id}/download, /docs and /health are both 200, and an
unauthenticated GET is refused 401.

Task R1: WHERE TO RESUME. R2 - Android. The project is at
C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI on the LOCAL
machine, NOT the VM, and it is NOT a git repository, so back up every file
before editing. Step 1 is to capture the fixture from a REAL run rather than
typing it: a throwaway pytest that builds an MOU and calls GET /mous/{id}
through the real route, then writes the response to
app/src/test/resources/contract/mou_detail.json. There is no Robolectric, so
anything left in a fragment cannot be tested - the pure decisions go in
MouLines beside ProposalFilledLines, and E1's lesson is that sourceLabel must
not let "user" and "default" fall through to "From your records", which would
tell a salesperson that a figure they typed themselves came out of the
database.

---

Task R2: NOTHING IS COMMITTED, because the Android project has no git. It is
at C:/Users/Ekaghni/AndroidStudioProjects/YuvipepSalesforceAI on the LOCAL
machine, not the VM, and the VM is untouched by this task - HEAD db751c9,
dirty 91, before and after.

Task R2: EVERY MODIFIED FILE WAS BACKED UP FIRST AND VERIFIED BYTE-IDENTICAL,
to .r2-backup/ inside the project, keeping its own path. Four files:
LeadDetailResponse.java, ContractTest.java, strings.xml,
LeadDetailFragment.java. That directory is the ONLY undo this project has;
the owner can delete it once they are happy. It sits at the project root, not
under app/src, so Gradle does not compile it - confirmed by a green build with
it present.

Task R2: THE FIXTURE WAS CAPTURED FROM A REAL RUN, as step 1 requires, by a
throwaway pytest deleted immediately after. tests/docx/test_capture_mou_fixture
.py built an MOU through the real service, corrected it, then called GET
/mous/{id} and GET /leads/{id} through the REAL routes and wrote both
responses verbatim. TO RE-CAPTURE: recreate that file (its content is
described here), run it, download /tmp/f3/fixtures/*.json into
app/src/test/resources/contract/, delete it again.

Task R2: THE FIRST CAPTURE WAS USELESS AND THE SECOND IS THE ONE THAT MATTERS.
Every value in it came back source="user", because the fill layer answered
everything through apply_answers. A fixture whose every value is "user" CANNOT
CATCH E1's DEFECT COMING BACK - the whole point is that "user" and "default"
fell through to "From your records". The capture was rewritten to produce all
three: "ai" from a semantic tag resolved at open_session with a citation that
RESOLVES against the dossier, "user" from an ask the person answered with
something new, and "default" from an ask answered with the template author's
own words.

Task R2: A STATEFUL FAKE BEHIND A FACTORY LAMBDA IS REBUILT ON EVERY CALL, and
this cost the second capture an hour. `monkeypatch.setattr(docx_tagfill,
"get_model_layer", lambda: Layer(tags))` constructs a NEW Layer per call, so
`self.passes` was always 1: the resolve pass's answer was handed to the ANSWER
pass, where it was correctly dropped as a tag that is no longer open, and
nothing settled. A STATELESS fake hides this completely - which is why every
other test file in this project gets away with it. The fix is one layer:
`layer = Layer(tags); lambda: layer`. FOR THE NEXT SESSION: if a fake counts
its turns, build it once.

Task R2: THE HANDOVER'S "CHECK EVERY FILE IS STILL CRLF" IS WRONG AS A GENERAL
RULE, and measuring it is what showed that. Across app/src: 151 Java files are
LF and 36 are CRLF, and E1's OWN ProposalFilledLines.java is LF. The rule that
actually holds is PRESERVE EACH FILE'S OWN CONVENTION. Both patch scripts read
bytes, detect the newline the file already uses, and write the same one back;
verified after every edit. The four modified files are still CRLF, the five
new ones are LF, none is mixed.

Task R2: EVERY EDIT TO AN EXISTING FILE IS PURELY ADDITIVE, measured: 0 lines
removed from any of the four. LeadDetailResponse +20, strings.xml +4,
LeadDetailFragment +16, ContractTest +127.

Task R2: MouLines LIVES IN ITS OWN PACKAGE, not beside ProposalFilledLines.
The handover says "beside", but an MOU is not a proposal (D-A) and putting a
contract's decisions in the proposals package is the first step towards
someone reusing a proposal's rule on a contract. feature/mous/MouLines.java.

Task R2: FIVE DECISIONS, ALL OUT OF THE FRAGMENT because there is no
Robolectric and anything left in a fragment cannot be tested at all - which is
exactly how E1's two defects survived a green suite. hasProvenance,
sourceLabel, heading, rowTitle, isWithTheClient. The last one believes BOTH
signals: a send that recorded when it went and then failed to move the status
still means the client is holding it, and the backend refuses a correction on
either - so the screen must not offer one it would be refused.

Task R2: MY MUTATION HARNESS REPORTED THE SAME INNOCENT TEST FOR EVERY
MUTATION, and it was the harness. A non-greedy regex
`<testcase name="X"[^>]*>(.*?)</testcase>` starting on a SELF-CLOSING
`<testcase/>` runs on to the NEXT testcase's closing tag and attributes that
one's failure to this one. 0/8 killed, all MISSes naming one unrelated test.
Parsed with ElementTree instead. THIS IS THE SAME TRAP the backend's raw_count
documents for nested `w:p` elements, in a different file format - a
regex walking a nested structure attributes a child's content to the wrong
parent.

Task R2: ONE MUTATION WAS WITHDRAWN AS MIS-MODELLED RATHER THAN LEFT AS A
SURVIVOR. "The backend starts sending a total" added total_amount to the DTO,
which cannot make anMouCarriesNoCommercialFields fail: that test reads the
captured FIXTURE's raw JSON, not the DTO. It guards the BACKEND, and it fails
when the backend changes and the fixture is re-captured, which is its job.

Task R2: TESTS. Android JVM 77 passed / 0 failures (61 before, +16): 12
MouLinesTest and 4 ContractTest cases. Seven mutations, all killed by the test
named for them - the card hidden, "user" and "default" each falling through,
the template's suggestion credited to the salesperson, a line named by the
model's reasoning instead of the row label, a timestamped send read as a
draft, and the backend renaming `source`.

Task R2: WHAT R2 DOES NOT DO, and it is not in the plan's file list either.
There is no MouDetailFragment. The client screen now LISTS a contract - title,
and "Contract - draft" or "Contract - sent to the client" - but tapping it
goes nowhere, because there is no MOU screen to open. sourceLabel and heading
are written and tested for that card and are currently exercised only by
tests. FOR THE OWNER: the contract is visible on the client screen; opening it
needs a detail screen nobody has scheduled.

Task R2: WHERE TO RESUME. U2 - the console, deferred to second-last by the
owner (amendment B) - then E1, documentation and deploy. U2 is the last piece
of surface: an MOU template is still uploaded through the API with
document_type=mou, which works today.

---

Task U2: D11 HELD - EVERY DECISION IS IN flow.ts AND THE .tsx FILES ONLY
RENDER, because the console suite renders no components and a decision left in
a component cannot be tested at all. documentTypeOf, documentTypeLabel,
forcesSimpleFlow, ruledBlankWarning; 7 new tests.

Task U2: A TEMPLATE PUBLISHED BEFORE THIS FEATURE READS AS A PROPOSAL. There
is no document_type key on any of them and everything before U2 was a
proposal, so anything not explicitly "mou" is one. Defaulting the other way
would relabel every template in the database overnight, and there is a test
for the absent key as well as the present one.

Task U2: AN MOU SETTLES THE FLOW RATHER THAN BEING REFUSED BY THE UPLOAD. A
contract's author writes the tags into the Word file themselves; there is no
MOU template an administrator marks up afterwards. forcesSimpleFlow decides
it and the selector says so on screen, which is better than a refusal at the
end of an upload.

Task U2: D-F IS A WARNING AND NEVER AN ERROR, and it says what will HAPPEN.
"2 ruled blanks" alone gives an administrator no reason to act; the message
names the consequence - they reach the client as underscores - and what to do.
The upload succeeded and the document is stored, because refusing it would
leave the author with no template at all over something only they can fix, in
a file only they have.

Task U2: THE CLIENT WAS REGENERATED FROM A HEAD EXPORT, per 6b, with
node_modules symlinked in. The leak check the plan specifies passes: zero
occurrences of relationship_manager, lead_open_feed_days,
relationship_engagements or lead_cycles. Both new routes are in
(/api/v1/mous/{mou_id} and its /download) and document_type is on the upload
route.

Task U2: THE LINE-ENDING RULE IS WORTH THE PLAN'S WARNING, MEASURED.
dump_openapi.py writes LF; openapi.json and vocabularies.generated.ts are
committed CRLF. Written back in each file's own endings the diff is 108 lines;
copied verbatim it would have been ~11,600, every line of both files.
generated.ts is NOT regenerated - dump_openapi.py writes two artefacts, not
the three the plan lists, so whatever produces generated.ts is a separate
thing and nothing here touched it.

Task U2: REGENERATING IS WHAT MADE THE CONSOLE'S OWN TABLE PIN SPEAK UP, AND
IT WAS RIGHT TO. src/bundle/reset.test.ts is the console's twin of the
backend's test_reset_taxonomy: it asserts the operator is shown the WHOLE
schema before approving a reset, so a table missing from the console's list is
one they approve a reset over without being shown. It said 57; the schema is
59. The two missing were mou_documents (M2) and mou_revisions (F3), which
landed in the backend weeks apart while the console's artefacts went
unregenerated. FOR THE NEXT SESSION: a backend table is not finished until the
console's artefacts are regenerated too, and nothing enforces that but this
test.

Task U2: MOVED BY INCREMENT, AND THE GUARD REFUSED FIRST. The patch expected
three occurrences of 57 and found four - the title, the comment recording why
it last moved, and two assertions - and stopped rather than guessing. Checked,
then all four moved 57 -> 59 with the reason beside them. Never written
literally: A4's recorded bug.

Task U2: I INVENTED A STYLE TOKEN AND TWO SEPARATE GUARDS CAUGHT IT. `s.hint`
does not exist. tsc said "Spread types may only be created from object types"
and the console's own tokens.test.ts said "every class the components
reference is actually defined" - a guard this project wrote for exactly this.
Replaced with a plain inline style.

Task U2: A PATCH OF MINE APPLIED ITSELF THREE TIMES, which is amendment N from
the other side. The ruled-blank block's sentinel did not match the text that
edit emits, so the guard could not recognise its own work and re-applied on
every run. Not "the edit skipped itself and reported success" but "the edit
could not see that it had already succeeded". Repaired to exactly one copy by
a script that counts before it deletes, and the sentinel fixed so running
twice now says "already applied" twice.

Task U2: TESTS. Console tsc --noEmit exit 0; Vitest 714 passed / 20 files (707
before, +7). Backend 1009 passed / 1 failed, unchanged - U2 touches no backend
file, and that was confirmed by running it rather than assumed.

Task U2: COMMITTED f66e35e, seven paths, all clean at HEAD so all plain adds
and no 6a - flow.ts, flow.test.ts, DocxUpload.tsx, ProposalTemplates.tsx,
openapi.json, vocabularies.generated.ts, reset.test.ts. Dirty 91 before, 98
while working, 91 after. Dashboard/dist is NOT among them.

Task U2: DASHBOARD/DIST WAS PROVED UNTOUCHED BY MTIME, not assumed. The md5 of
every file's mtime is identical before and after the whole task, and the
console was proved to still build by building it to /tmp/throwaway_dist.

Task U2: DEPLOYED. The console was then built FROM THE WORKING TREE, not from
a HEAD export - the tree carries session/baseUrl.ts, without which a console
served over ngrok tells every visitor's browser to call 127.0.0.1:8000.
Restarted; /docs, /health and the console itself all 200 over the public url.
dist's five paths are the same five as before, so dirty is still 91.

Task U2: WHERE TO RESUME. E1 - documentation and deploy, the last task.

---

Task E1: STEP 1 MEASURED, AND THE PLAN WAS WRONG TWICE - which is exactly what
step 1 exists for. (1) Of the three files it names, only BACKEND_README.md is
dirty; 05_DECISIONS.md and 09_BACKEND_CHANGES.md are both clean, so two plain
edits and one 6a rather than three 6a edits. (2) The plan says three of the
README's figures already differ between HEAD and the tree and that every edit
must accept either variant: measured, the two strings this task replaces are
BYTE-IDENTICAL in both trees and only their line numbers moved. One
replacement served both.

Task E1: D38-D45 IN 05_DECISIONS.md. D38 D-A, D39 D-B, D40 D-C, D41 D-D, D42
D-E, D43 D-F, D44 the routing decision and the correction rules, D45 the
properties. D41 records explicitly what step 2 asks for: D-D FIXED A LATENT
DEFECT IN THE PROPOSAL FLOW TOO. open_questions never collapsed duplicates and
never had; it was invisible there only because the repeated literal in the
tagged proposal was <School Name>, a SEMANTIC tag filled silently without ever
being asked. The MOU's <ask:75> made it visible and the fix is in the shared
code.

Task E1: SECTION 1c IN 09_BACKEND_CHANGES.md, the seventh unfreeze, placed
before the change log: the data model, both migrations, the two tables
create_all builds on restart, the new routes, the upload's document_type, the
six agent tools, the properties, the console, and what the live run measured.

Task E1: THE README'S TEST FIGURES WERE STALE BY MORE THAN THIS TASK. 670
collected / 617 passing / 53 skipped across 64 files becomes 878 / 812 / 66
across 75, and Android 61 becomes 77. Those are HEAD IN ISOLATION, measured
today by running a git archive HEAD export - NOT the working tree's 1009,
which includes 91 paths of unrelated in-flight work and is not this
repository's number. Writing the tree's figure into the README would have been
a wrong number that looked authoritative.

Task E1: A .gitattributes DECIDES LINE ENDINGS, AND THE WORKING FILE'S
CONVENTION IS NOT THE REPOSITORY'S. Staging 09_BACKEND_CHANGES.md printed
"CRLF will be replaced by LF", which looked like the 11,600-line disaster U2
had just avoided. Checked before committing: HEAD's BLOB for that file is LF
(742 lines) while the working file is CRLF, because .gitattributes normalises
on the way in - a file written after two earlier sessions flipped a README and
turned a 25-line docs edit into 653. The staged diff is 79 added, 0 removed.
FOR THE NEXT SESSION: "this file is CRLF" is true of the working copy and
false of the blob; check `git show HEAD:<path>` before believing a warning.

Task E1: STEPS 5 AND 6 WERE ALREADY DONE AND WERE RE-VERIFIED RATHER THAN
REPEATED. The service is active AND enabled, so it survives a reboot; the
healthcheck timer is running; /health, /docs and /dashboard/ are all 200 over
the PUBLIC url; the running process advertises both /mous routes and
document_type on the upload route's body schema; mou_documents (17 columns)
and mou_revisions (9) exist on the live database. The console was built FROM
THE WORKING TREE, and the bundle served over ngrok was fetched back and
confirmed byte-identical to the one built.

Task E1: THE CONSOLE BUNDLE CONTAINS 127.0.0.1:8000 AND THAT IS CORRECT. It is
CONFIG_DEFAULT_BASE_URL, the fallback defaultBaseUrl returns when the page is
NOT served from /dashboard. The console IS served there, so it uses the page's
own origin. A grep alone reads as the exact defect the handover warns about;
the code path is what settles it.

Task E1: COMMITTED ff84f9e, three paths - 05_DECISIONS.md and
09_BACKEND_CHANGES.md as plain adds, BACKEND_README.md through 6a (staged blob
verified as HEAD + exactly 2 changed lines, and differing from the tree).
Dirty 91 before, 94 while working, 91 after. Verified in a git archive HEAD
export: 812 passed / 66 skipped.

Task E1: THE PLAN IS COMPLETE - 15 of 15 tasks, 61 commits from aa49e80.

Task E1: WHAT STILL NEEDS THE OWNER'S EYES, and none of it is blocking.
  * THE THREE BROKEN WORD FIELDS in their source MOU, at walk ordinals 209,
    232 and 236, reading "Error! Reference source not found." and "Error! No
    text of specified style in document." No tag can repair them and they
    print into every MOU built from that template. Unchanged since first
    reported.
  * FOUR QUESTIONS ARE PUT TO A PERSON AS RAW TAG TEXT - ordinals 154-157, the
    Pricing Details block, which carry no context label so the round asks
    "<ask:75>" verbatim. 4 of 43 asks. Same class as the numbered-row-label
    defect the owner had fixed in the shared scanner; not fixed here because
    it changes tags.py and affects the proposal flow too.
  * ONE CONTEXT LABEL READS "MoU for MoU for - MoU for".
  * THERE IS NO MOU DETAIL SCREEN. The Android client screen LISTS a contract;
    tapping it goes nowhere. Not in R2's file list. sourceLabel and heading are
    written and tested for that card and are exercised only by tests.
  * NO APK WAS BUILT. Every APK on disk predates this session.
  * The "ask me" grammar question, the attached-template link naming a staff
    member in word/_rels/settings.xml.rels, and the rate-card migration's
    WAL-less backup all remain open from earlier sessions.
  * NOTHING HAS BEEN THROUGH THE APP ON A PHONE. Three of the simple flow's
    defects came that way and none from the suite.

---

## 2026-09-11, second session: the owner's first contract, and what it found

Baselines re-measured before touching anything: backend working tree 1009
passed / 1 failed (the permitted one), tests/docx 606, console 714 with tsc
clean, Android 77/0. All four matched the handover.

**The D46 commit was finished first.** The previous session had the code, the
tests and the D46 entry on the VM, verified, and had been stopped before the
commit by the deploy classifier. tests/docx re-run at 615, then committed as
`594739c` over nine paths; dirty 100 -> 91. The service had already been
restarted at 04:22:26 UTC by something other than that session, so **D46 was
live before this session started** and the owner's 04:24-04:33 contract ran
with it.

**That contract BUILT, and the document is correct.** Forty-seven questions,
eleven rounds, every value written. Checked the built file ordinal by ordinal:
no `<ask:` left, the programme name in all four places, 75 in all five,
"Note: This pricing applies to a total of 75 students". The `content_md` the
app reads carries them too.

**A false alarm worth recording, because it will catch the next person.**
`paragraph.text` in python-docx shows only runs that are DIRECT children of the
paragraph. Every tag in the owner's template sits in a nested run, so
`paragraph.text` renders the template with the tags already gone and the built
document with BLANKS where the values are. Eight values looked lost that way
and none were. **Read a built document with `app.services.docx.text.node_text`,
which is what `scan` and `apply_tags` use.** The same mistake reading
`tags_json` keys cost another pass: the value is under `value`, not `text`.

### D47, measured on that conversation

* **`asked_json` recorded ELEVEN rounds against TWENTY replies.** Nine of the
  owner's answers reached no tool at all. The model restated the round it had
  just been handed -- "The only remaining MoU question is ... Reply
  'Innovation Nexus' to finish" -- twice in a row for the last question. The
  fill was untouched on those turns, which is exactly what "questions are
  repeatedly asked even if the answers are given" looks like from the outside.
* **Four rounds asked the programme name**, two the YuviPep representative's
  name, two its title, three the completion date. Each is its own place with
  its own context, so each was its own round.
* `<ask:75>` is FIVE places and stays five questions: the fallback question
  names each one's own context, so they do not read alike.

The fix: `BaseAgent._tool_the_turn_needs`, asked only when a turn called no
tool; `ProposalAgent` answers it with the document's answer tool while the fill
is asking, never at the review. And `docx_tagfill.reads_as` + `_spread`, which
carry the AUTHOR'S OWN suggestion -- nothing else -- across places that read
the same.

**The owner ruled twice, and the second ruling reversed the first.** They first
chose "ask once, show (in 4 places)". Implementing it broke
`test_fill_agent.py::test_the_first_round_is_six_questions_with_their_defaults`,
whose fill model writes ONE question for eight different tags: they all read
alike, merged to two lines, and the round stopped naming the Laptops and
Interactive Panel rows. Put back to them with that cost named, they chose
**settle together, keep the lines** -- which is what shipped. The display
merge and its three tests were reverted; `open_questions` and `fill_tools` are
untouched at HEAD.

Mutation check: 11 mutants, 6 killed on the first run. Three survivors were
real gaps and now have tests (a twin answered INSTEAD of the one on screen;
places with no suggestion, where nothing may travel; the same wording with a
DIFFERENT suggestion, which is another question). 9 of 11 after that. The two
remaining survivors are `_tool_the_turn_needs`' status check and its
open-questions check, which are each other's cover: a fill that is asking
always has questions outstanding, and one with questions outstanding is asking.

### The app can read a contract

`MouDetailFragment` + `fragment_mou_detail.xml` + `MousRepository`, the client
screen's contract row now opens it, and `PdfViewerFragment.forMou` renders the
PDF through the authenticated file cache. `ApiService.mou` and `downloadMou`
added. `MouLines.canBeRead` gates the button on **has_docx, not has_pdf**, and
`MouLines.versionTag` keys the render cache on the correction count; both are
tested, which is why they are in `MouLines` and not the fragment. Android 82
passed / 0 failures, from 77. Backups of every edited file in `.d47-backup/`.

**The first APK containing any of this work now exists**, at
`app/build/outputs/apk/org/debug/app-org-debug.apk` (13.0 MB,
`:app:assembleOrgDebug`). Every other APK on disk still predates the MOU
pipeline.

### State at the end

```
branch feature/docx-proposal-templates, HEAD 5a6b89c, dirty 91
backend working tree 1030 passed / 1 failed (the permitted one)
tests/docx 627 passed        (615 at the start of the session, 606 before D46)
Android 82 passed / 0        (77 at the start)
HEAD export, the three fill test files: 102 passed
```

**D47 IS NOT DEPLOYED.** The restart was refused by the deploy classifier,
twice, in both sessions. The running service is still the 04:22:26 UTC process,
which carries D46 and not D47. The owner has to run:

```bash
printf '%s\n' 'tela@123' | sudo -S -p '' systemctl restart salesforce-app-restart.service
```

Public URL verified up meanwhile: `/health` 200, `/dashboard/` 200, and both
MOU routes answer 401 unauthenticated rather than 404, so they are routed.

### Still the owner's, and still unfixed

Everything in E1's list stands except the MOU detail screen and the APK, which
are done. The three broken Word fields, the four asks at ordinals 154-157 put
as raw tag text, the "MoU for MoU for - MoU for" context label, the "ask me"
grammar, the staff member's path in `word/_rels/settings.xml.rels`, and the
WAL-less migration backup are all unchanged. Also new, from reading the built
contract: the template's first paragraph, "Bookmarks: status: ... author: ...
acceptor: ... modified: ...", is ordinary body text and prints at the top of
every contract; and the signature block writes the literal words "date of
signing" as a value, because that is the suggestion its author wrote.

---

## 2026-09-11, later: the owner's second contract, and D48

D47 was deployed at 05:54:45 UTC (the owner ran the restart; the classifier
refuses it to this session). Verified live by the loaded bytecode, not just by
the service coming back up. They then ran a second contract, 06:02-06:08, and
reported three things. **D47 itself worked on that run**: the forced call fired
once at 06:06:31 and the spreading once at 06:07:04.

### What the second run measured

`asked_json`: **seven rounds for nine replies.** Two were lost, and they were
the last two.

* **06:07:41** — *"All the suggested values are fine"* reached
  `show_mou_questions`, which lists and answers nothing. A tool HAD run, so
  D47's force stood aside. **The rule was wrong: it is not "did a tool run"
  but "was the person asked anything".**
* **06:08:15** — *"Yes show the remaining"* was routed to the **query agent**,
  which has no MOU tools, and it improvised: *"I can't see the MoU's remaining
  fields from here… where is the MoU form you're filling?"* The router falls
  back to `query` whenever unsure and had only four quoted turns to go on.

And the date: **no date reached any of the three fill prompts at all.** The
template's "1.9.2026" and "First Day of September, Two Thousand Twenty-Six
(01-09-2026)" could not be told from current ones by anything in the system.

And the screen: the app draws the model's prose AND the tool's card. On one
round the card asked for six things and the prose asked for two, together.

### Three rulings from the owner

1. **A passed date is offered as today, and still asked.** In the author's own
   format — 1.9.2026 becomes 11.9.2026 — with the line saying whose date has
   passed. Prose with a date inside it is never rewritten (D15).
2. **The card is the question**; the prose is cut to its opening line.
3. Earlier the same day: **settle together, keep the lines** — which is why
   D47 shipped without the display merge.

### What the tests found that the owner could not

* `test_fill_agent`'s first-round test killed the display merge before it
  shipped (a model that writes one generic question for eight tags would merge
  eight rows into two lines and name none of them).
* `test_tool_choice` found that the loop-breaker is keyed on the document
  type, so **`create_proposal` with a contract mid-fill opened a SECOND
  fill**. It surfaced only because the card-as-reply change altered the
  conversation text its crude model scores against — which is the file working
  exactly as its docstring says it should.
* Exporting HEAD and running it found that D48 had made two committed files
  import **`app/core/clock.py`, which is untracked in-flight work**. The
  export could not import `docx_tagfill`. `tests/test_one_clock_guard.py`
  refuses the `date.today()` alternative in `app/` for a measured reason, so
  the module was committed instead: it is self-contained (standard library
  plus the already-committed `OrgSettings.timezone`).
  **The dirty count is now 90, not 91** — one file, named by the fix that
  needs it. Every future session should expect 90.

### Two tests changed meaning, both recorded in D48

`test_show_mou_questions_answers_nothing_and_changes_nothing` now asserts no
VALUE moved rather than that the record is byte-identical: the turn does pass
the reply on, and an answer pass re-words a question it could not settle.
`test_without_the_prompt_paragraph_a_reply_misses_the_mou_tools` **inverted**
and was renamed: an open document now names its own answer tool from inside a
tool result, whatever the system prompt says. The paragraph is still what
makes STARTING a contract reachable, and the test that pins that is untouched.

### State

```
branch feature/docx-proposal-templates, HEAD 0375e26, dirty 90
backend working tree 1043 passed / 1 failed (the permitted one)
tests/docx 640 passed        (627 after D47, 615 after D46, 606 before)
Android 82 passed / 0        (unchanged; D48 touches no Android file)
HEAD export, the five fill test files: 139 passed
```

Mutation check: 14 mutants, 13 killed. The survivor removes `BaseAgent.
_asked_a_question`, which every path in this agent also covers through
`ProposalAgent.CHANGES_THE_FILL`; it is the general fence for an agent whose
card comes from a tool that is not a fill's, and none does today.

**D48 IS NOT DEPLOYED.** The restart is refused to this session, as it has
been in both. The owner runs it over ssh:

```bash
sudo systemctl restart salesforce-app-restart.service
```

### Still open, and still the owner's

The Orchid fill from 06:02 is **stuck at 22 questions outstanding**, status
`asking`. After the deploy it can be carried on in that same chat, or
abandoned. Everything in E1's list stands except the MOU detail screen and the
APK. New from reading this run: the round still asks four questions as raw tag
text (ordinals 154-157), and the model twice returned a TRUNCATED tag id
(`d1c5e9c58b6` for `d1c5e9c558b6`) which was dropped and then rescued by D47's
spreading — worth watching, not yet worth a fix.

---

## 2026-09-11, third run: D49

D48 went live at 10:13:04 UTC (the owner ran the restart). The third contract,
10:19-10:24, is the best run so far: **every reply reached the fill**, the
prose above each card was the card's own opening line, and the outstanding
count came down 43 -> 34 -> 27 -> 23 -> 16 -> 12 -> 8. Two turns still failed,
and they are one defect:

* **10:24** — *"Instead of 4k make it 9k"*, an answer to the card on screen,
  reached `correct_mou`, which edits a contract that has already been BUILT.
  It failed and the words were dropped. D48 stood the force down for any tool
  that COULD have acted; this one could not.
* **10:21:49** — *"All the suggested values are fine"* reached
  `confirm_mou_values`, whose D44 redirect says to pass the words to the
  answer tool. Nothing did, so the owner typed *"Answer the remaining
  questions"* to get the same round back.

**D49: the tool must have ACTED.** Not raised, not returned `already_open` /
`still_asking`, not returned its own `ok: false`. A tool that ASKED is judged
by `run` first, which is what stops `answer_*_questions` being handed the same
sentence twice. **This narrows D44 and does not overturn it** — the wrong tool
still refuses and still builds nothing, and D13 still gates the document.

Also: a question with no context is now introduced by its SECTION. The owner's
four unlabelled asks were arriving as *"ask:75: What should replace ask:75?"*
— the app renders `<ask:75>` as a link and eats the brackets. Presentation
only; the scanner still finds no label for those four (ordinals 154-157), and
that remains the owner's call because it changes `tags.py`.

```
branch feature/docx-proposal-templates, HEAD 069d8fa, dirty 90
backend working tree 1049 passed / 1 failed (the permitted one)
tests/docx 646 passed        (640 after D48, 627 after D47, 606 before D46)
HEAD export, the five fill test files: 145 passed
```

Mutation check: 5 mutants, 4 killed. The survivor makes `_a_fill_tool_acted`
answer "never", which the ASKING check beside it also covers: a tool that acts
without asking leaves the fill built or reviewing, and neither is asking.

**D49 IS NOT DEPLOYED.** The running service is the 10:13:04 process, which
has D48 and not D49.

### Known, and worth watching

* The four asks at ordinals 154-157 still have no context label. The section
  fallback makes them readable, not correct.
* The app renders `<ask:75>` inside a question card as a hyperlink, eating the
  angle brackets. Cosmetic, app-side, untouched.
* The model has twice returned a TRUNCATED tag id (`d1c5e9c58b6` for
  `d1c5e9c558b6`). Dropped safely both times, and rescued once by D47's
  spreading.

---

## 2026-09-11, fourth run: D50

D49 went live at 13:38:42 UTC. The fourth contract, 13:45-13:52, answered
cleanly all the way to the review -- and the owner's tap on "Yes, these are
all correct" was answered with "there isn't a proposal draft currently open in
this conversation".

The model had been reaching for the PROPOSAL tools throughout:
`confirm_proposal_values` at 13:51:00 and 13:51:24, `show_proposal_questions`
at 13:52:02, `confirm_proposal_values` at 13:52:52. **D49 rescued the first
three** -- "Turn called no tool; passing the reply to answer_mou_questions"
appears three times and is why the fill reached its review at all. The fourth
it could not: D48 scopes the force to a fill that is ASKING, and this one was
reviewing.

D50 fixes both halves. `_fill_in_hand` now names what IS open and the tool
that moves it on -- the rule `create_*` has had since A2, which `answer_*`,
`show_*` and `confirm_*` never got. And an approval at the review reaches the
right document, on an EXACT match with the review's own phrase (case and
stray spaces folded, nothing else), because that tool is the one that writes
a client-facing file.

```
branch feature/docx-proposal-templates, HEAD 4619bbe, dirty 90
backend working tree 1053 passed / 1 failed (the permitted one)
tests/docx 650 passed        (646 after D49, 640 after D48, 627 after D47)
HEAD export, three agent test files: 68 passed
```

Mutation check: 5 of 5 killed.

**D50 IS NOT DEPLOYED.** The running service is the 13:38:42 process.

The owner's contract `f1816075409d400d81ec2117b1d0c59b` is sitting at
`reviewing` with every value answered. After the restart, tapping the approval
again builds it -- nothing needs re-answering.
