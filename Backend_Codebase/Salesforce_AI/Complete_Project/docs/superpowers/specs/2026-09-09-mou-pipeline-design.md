# The MOU pipeline — design

> **CORRECTED 2026-09-10.** Six statements in this document were
> disproved by measurement while it was being built. **Read Â§12 first**;
> it is authoritative over everything above it.

**Written 2026-09-09, after the six decisions were put to the owner and
answered.** Every number here was measured in this session against the real
document and the live database, not copied from the design input. Where a
figure disagrees with `2026-09-09-mou-pipeline-design-input.md`, this document
says so explicitly and the measurement wins.

Baseline at the time of writing: branch `feature/docx-proposal-templates`,
HEAD `0fe0325`, working tree dirty 91.
**Backend at HEAD in isolation: 636 passed, 53 skipped** (measured here; the
handover said "630-odd", which this confirms).

---

## 0 · The decisions, as answered

| # | Decision | Answer |
|---|---|---|
| **D-A** | Where a built MOU lives | **A new `mou_documents` table.** Not a `Proposal`. |
| **D-B** | Two current templates per programme | **A new `document_type` column** on `proposal_templates`. |
| **D-C** | Which fill-session table | **Reuse `proposal_fill_sessions`**, plus a nullable `mou_id`. |
| **D-D** | The shape of the conversation | **Collapse duplicates when asking, and group each round by document section.** |
| **D-E** | Arithmetic in a contract | **The model proposes a relation; Python checks it; a mismatch warns and never substitutes.** |
| **D-F** | `Date: ___________` | **Warn in the upload summary.** Do not refuse. |
| — | Where a built MOU is visible | **Its own section on the client screen, and the chat card where it was built.** |
| — | Routing | **One agent owns both documents.** No seventh agent. |
| — | Corrections | **Same rules as a proposal**: reopen, re-review, rewrite the same row; refused once sent. |

Two assumptions were stated to the owner rather than asked, and not
contradicted: **an MOU needs no rate card** (D37 already exempts a document
that carries its own prices), and **an MOU may be built with no proposal in
existence** — there is no precondition.

---

## 1 · What was measured in this session

### 1a · The document reproduces exactly

Sample: `data/samples/Sandur Education Centre_IBC Nexus and Lab2_MoU.docx`,
2,109,447 bytes, **untagged**.

| Figure | Design input | Measured here |
|---|---|---|
| Paragraphs in the walk | 240 | **240** |
| — body / header / footer | 193 / 17 / 30 | **193 / 17 / 30** |
| Tables | 8 | **8** |
| Sections | 3 | **3** |
| Images | 11 | **11** |
| Tag occurrences today | 0 | **0** |

Every repeated literal in the design input's table reproduces: `Sandur
Education Centre` 10, `Innovation Nexus` 5, `75` 5, `32` 3, `Rs. 1,50,000` 2,
`Y S Ghorpade` 2, `Rs. 4000` 1, `Rs. 3,00,000` 1.

**One refinement.** The design input warns that the header/footer trap is
"worse in proportion" here. Measured per literal, it is *narrower* than the
YuviPep 360 case: of the 10 `Sandur Education Centre`, **2 are outside the
body** (not 6, as in YuviPep 360), and of the 5 `Innovation Nexus`, 1 is.
The structural claim stands — 47 of 240 paragraphs are outside the body — and
a body-only tagging still prints the wrong school at the foot of pages. The
rule is unchanged: **count with `tests/docx/test_text.raw_count`, never by
eye.**

### 1b · The document carries real heading styles — D-D's grouping is not a heuristic

This was probed because the design decided to group questions by section and a
guess was not acceptable. The document has genuine Word heading styles, and
they land exactly on the boundaries D-D wants:

| Ordinal | Style | Text |
|---|---|---|
| 24 | `Heading1Center` | Memorandum of Understanding |
| 89 | `Heading1Center` | Annexure |
| 90 | `Heading2` | **Operation Terms** |
| 112 | `Heading2` | **Agreed Deliveries and Offers** |
| 149 | `Heading2` | **Pricing Details** |
| 159 | `Heading2` | **Student Enrolment Structure** |
| 169 | `Heading2` | **Payment Terms** |
| 181 | `Heading2` | YuviPep Bank Details |

These map almost one-to-one onto the commercial tag groups in the design
input's §2b. So the section label is read from
`w:pPr/w:pStyle/@w:val`, and the fallback (nearest preceding short bold line)
is a genuine fallback rather than the primary mechanism.

**A caveat that must be tested, not assumed:** a heading style tells us where
a section *starts* in the walk, and 47 paragraphs of the walk are in headers
and footers, which have no section at all. Occurrences there take the label
`"Header"` / `"Footer"`, never the nearest preceding body heading.

### 1c · Two defects in the owner's own document

**Ruled blanks (D-F confirmed).** `Date: ___________` at ordinals **85 and
87**, both in the signature table (style `TableHead1`). Exactly the case D-F
describes.

**Broken Word field references.** Three paragraphs, all **outside the body**,
read literally:

- ordinal 209 — `Error! Reference source not found.`
- ordinal 232 — `Error! No text of specified style in document.`
- ordinal 236 — `Error! No text of specified style in document.`

These are broken cross-references in the source document's headers and
footers. **They are not caused by anything in this project and no tag will fix
them** — they will print into every MOU built from this template, on pages
where nobody scrolling the body would look. This needs the owner to repair the
source `.docx` in Word. Flagged, not worked around: silently stripping text
from a client-facing contract is not this pipeline's business.

### 1d · The live database

| Table | Rows |
|---|---|
| `proposals` | 9 |
| `proposal_templates` | 18 |
| `proposal_template_docs` | 5 |
| `proposal_fill_sessions` | 4 |
| `programs` | 29 |

IBC (`b4487189…`) carries six template rows; `ibc_proposal_v4`
(`docx_simple`) is the current one.

---

## 2 · Why D-A is a new table — the measured blast radius

Had an MOU been a `Proposal` row, it would have entered five places that
exist to describe a *deal*:

| Where | What would happen |
|---|---|
| `app/api/leads.py:357` | The MOU appears in the lead's `proposals` list (top 10) — the app's client screen shows a contract as a proposal. |
| `app/engines/knowledge_engine.py:172` | The MOU is fed back as client history. |
| `app/engines/document_engine.py:185` | `accepted_total` sums `total_amount` over accepted proposals for a project. |
| `app/engines/inbound_engine.py:1218` | **A SENT proposal on a project is read as the deal being agreed.** |
| `app/engines/approval_engine.py:434,588` | Approval routing treats it as a priced proposal. |

The fourth is the decisive one. An MOU is signed *after* a proposal is
accepted, so it would arrive on an already-closed deal and could flip its
state on its own. This is the same class of error as the last session's
"Total amount: 2200" defect — **reasoning by analogy with a neighbouring flow
instead of asking whether the premise travels.** It does not.

`mou_documents` therefore carries **no `total_amount`, no `line_items`, no
`pricing_table_id`, no `project_id`**. Not merely unused — absent, so that no
future aggregate can pick it up by accident.

---

## 3 · Data model

### 3a · `proposal_templates.document_type` (D-B)

```python
document_type: Mapped[str] = mapped_column(
    String(20), nullable=False, default="proposal", server_default="proposal"
)   # proposal | mou
```

`is_current` becomes **current per (org, program, document_type)**. Four call
sites move together, and getting any one of them wrong is the failure the
design input warned about:

| File | Line | Change |
|---|---|---|
| `app/services/docx_template_service.py` | ~184 | The retire loop filters on `document_type`, so uploading an MOU cannot retire the proposal template. |
| `app/api/admin.py` `_promote_predecessor` | ~880 | Gains `document_type` in its scope, so deleting the current MOU cannot promote a proposal template. |
| `app/services/proposal_service.py` | ~99 | `_current_template` filters `document_type == "proposal"`. |
| `app/services/proposal_fill_service.py` | ~837 | `_current` takes the type as an argument. |

**Reproduced before designing:** with today's code, `docx_template_service`
retires *every* `is_current` row for (org, program). Uploading an MOU for IBC
would clear `ibc_proposal_v4`, and `_current_template` would then return
`None` → *"No proposal template for this program. Ask your Org Admin to add
one."* **Proposal creation for IBC would break.** The first task must
reproduce this failure before fixing it.

**Migration** `scripts/migrations/2026-09-09_template_document_type.py`:
`ALTER TABLE proposal_templates ADD COLUMN document_type VARCHAR(20) NOT NULL
DEFAULT 'proposal'`. SQLite supports adding a column with a default; this is
*not* the table rebuild D37 needed to drop a `NOT NULL`. All 18 live rows
become `"proposal"`, which is correct. Idempotent: reads the schema and does
nothing if the column exists. Follows `2026-09-08_optional_rate_card.py` —
back up first, verify row counts and foreign keys afterwards, refuse to report
success if anything moved.

### 3b · `mou_documents` (D-A)

```python
class MouDocument(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    __tablename__ = "mou_documents"

    lead_id:          Mapped[str]            # FK leads.id
    program_id:       Mapped[str]            # FK programs.id
    title:            Mapped[str]
    status:           Mapped[str]            # draft | sent
    template_id:      Mapped[str]            # FK proposal_templates.id
    template_version: Mapped[int]
    content_md:       Mapped[str]            # the projected text of what was built
    filled_json:      Mapped[list[dict]]     # provenance, the app's card reads this
    docx_path:        Mapped[str | None]
    pdf_path:         Mapped[str | None]
    created_by:       Mapped[str]            # FK users.id
    sent_at:          Mapped[datetime | None]
    sent_message_id:  Mapped[str | None]
```

Built by `create_all` on the next restart — free, no migration.

`filled_json` keeps the complex flow's six keys (`key`, `kind`, `source`,
`text`, `brief`, `anchor`) plus `computed_by` and `citation`, exactly as
`proposal_fill_service.filled_json` produces them today. **Renaming one turns
a working Android card into a blank one** — J2 recorded that, and it applies
here unchanged.

`app/core/reset_taxonomy.py`: `mou_documents` goes in **WIPE** — a client's
contract is transactional work, not catalogue. **Order matters and is a
constraint, not a preference:** `proposal_fill_sessions` carries an FK to
`mou_documents`, and nothing in this schema declares `ondelete=`, so
child-before-parent is the only thing keeping a reset from failing. The order
becomes `proposal_fill_sessions` → `mou_documents` → `proposals`.

`tests/test_dashboard_reset.py::test_catalogue_orphan_edges_match_the_schema`
will go red: `mou_documents` adds two catalogue orphan edges (`program_id` →
`programs`, `template_id` → `proposal_templates`). That test exists to force
this decision, exactly as it did for `proposal_fill_sessions` in A4 — the pin
is updated with the reason beside it, and **the partition counts are derived
by increment from whatever the baseline says, never hardcoded** (A4's bug).

### 3c · `proposal_fill_sessions` gains two columns (D-C)

```python
mou_id:        Mapped[str | None]   # FK mou_documents.id
document_type: Mapped[str]          # proposal | mou, default "proposal"
```

`document_type` is the discriminator. Without it, an MOU fill and a proposal
fill for the same lead, programme and chat are indistinguishable to
`find_open` and `find_for_chat`, and a reply about one would land on the
other. Every lookup gains it.

Migration `scripts/migrations/2026-09-09_fill_session_mou.py`, same shape as
above; 4 live rows, all become `"proposal"`.

**Honest cost of D-C**, measured: `proposal_fill_service` is 868 lines. Only
`_write_proposal`, `_commercials`, `_rewrite_proposal` and `_attach_pdf`
(~270 lines) are proposal-specific. The status machine — `open_session`,
`find_open`, `find_for_chat`, `find_correctable`, `apply_answers`,
`open_questions`, `review_lines`, `apply_correction`, `mark_ready`,
`abandon`, `filled_json`, `_record`, `_document_text`, `_must_be_resumable`,
~500 lines — is entirely document-type-agnostic and is inherited whole,
including `mark_ready` as the only door to `ready`, the 7-day sweep, and the
correction path.

Only the **build half** becomes polymorphic: `build()` dispatches on
`document_type` to `_write_proposal` or a new `_write_mou`.

---

## 4 · The engine — reused, unchanged

`app/services/docx/tags.py`, `text.py`, `tagfill.py` and
`app/services/client_dossier.py` are used **byte-for-byte as they are**. No
edits. The MOU needs exactly what they already do:

- per-occurrence identity (D1) — the 10 client-name occurrences are 10 ids;
- a walk that reaches headers and footers (A2) — 47 of 240 paragraphs;
- a writer that refuses a stale offset and reports rather than raises (A3);
- the whole client, assembled once, with `ai_decisions` and `progress_events`
  excluded and fields listed explicitly (C1).

`app/ai/docx_tagfill.py` is reused with **one addition** (§6), not a change:
`resolve_tags`, `answer_round` and `revise` keep their behaviour and their
five downgrade rules exactly.

---

## 5 · D-D · The conversation

### 5a · The defect this fixes, measured

`open_questions` (`proposal_fill_service.py:356`) is:

```python
waiting = [t for t in session.tags_json if t.get("outcome") == "question"]
return waiting if limit is None else waiting[:limit]
```

It slices raw **occurrences**. `duplicate_of` is set by raw literal
(`tags.py:143`, `first_seen.get(raw)`) but **nothing collapses it on the
asking path.** The D13 review *does* collapse, via `_group` in
`proposal_agent.py:194`.

On the proposal this was invisible: the repeated literal there was
`<School Name>` ×9, which is `semantic` and filled silently, so it never
became a question. On the MOU, `<ask:75>` is **five occurrences of one
literal** — so round one would ask the same question five times in six slots,
and `<ask:32>` three more. The person would read it as broken.

### 5b · The change

**Collapse on `duplicate_of` when asking.** A round shows the *first*
occurrence of each distinct literal. Nothing else moves, and this is why it is
safe: C3's ruling already sends the model **every** outstanding question on a
clarification turn, not just the round shown, so one reply settles all five
`<ask:75>` at once (D8). A duplicate the model declines to answer simply stays
open and surfaces in a later round.

**Group each round by section.** The round is filled from the earliest
document section that still has anything outstanding, so a round is coherent —
*Pricing Details*, then *Payment Terms* — rather than mixing a signatory's
name with an instalment date. The section label is derived at `open_session`
time from the occurrence's `ordinal` against the walk (§1b) and stored on the
`tags_json` record. **`tags.py` is not touched.**

**Expected effect**, to be measured rather than assumed once the MOU is
tagged: ~30 `ask` occurrences of ~20 distinct literals become ~20 questions,
which is **3-4 rounds**, against the design input's projection of eight or
nine. `QUESTIONS_PER_ROUND` stays 6 — D5 chose it deliberately and nothing
measured here argues against it.

---

## 6 · D-E · Arithmetic in a contract

**D15 is not weakened. No figure a model produced ever reaches a document.**
The only thing added is a check on the consistency of figures *a person
supplied*.

### 6a · The problem

Nothing in the system knows that `<ask_calculate:Rs. 3,00,000>` is
`<ask:Rs. 4000>` × `<ask:75>`. The relation is knowledge no part of the
pipeline currently holds.

### 6b · The mechanism

**A new model pass proposes relations, never values.** In
`app/ai/docx_tagfill.py`:

```python
propose_relations(ctx, *, occurrences, document_text) -> list[Relation]
```

A relation is `{"result": tag_id, "op": "product" | "sum", "operands":
[tag_id, ...]}` — **tag ids and an operator, and no numbers at all.** Called
once, at `open_session`. Every `tag_id` is validated against the occurrence
map and anything unknown is dropped and reported, the same discipline
`resolve_tags` and `docx_suggest._validate` already apply.

**Where a relation is stored, explicitly:** on the **result tag's own record
inside `tags_json`**, as a `relation` key. Not a new column — the fill session
already has three migrations' worth of change in §3c and a relation belongs to
the tag it computes, so it travels with that tag through `_record`,
corrections and rebuilds without any extra bookkeeping. `tags_json` is
**reassigned, never mutated** (C3's ruling — a SQLAlchemy JSON column tracks
assignment, not mutation), which the relation must respect like every other
key.

**A new pure module does the arithmetic.** `app/services/mou_arithmetic.py`,
no model, no I/O:

```python
parse_amount(text) -> Decimal | None
check(relations, values) -> list[Mismatch]
```

`parse_amount` handles Indian digit grouping and the document's own
decoration: `Rs. 3,00,000/- Net (Including GST)` → `300000`. It returns
`None` rather than guessing.

**If any operand or the result fails to parse, there is no check and no
warning.** Silence beats a false alarm in a contract: a spurious warning on a
legitimate negotiated figure teaches the reader to dismiss the warnings, which
destroys the only thing this feature is for.

### 6c · Where it surfaces

A mismatch attaches to the result tag's existing `warnings` list, which
`review_lines` already carries and `_review_message` already renders. The
message names **both** figures — *"the annual total reads Rs. 3,00,000 but
Rs. 4,000 × 75 is Rs. 3,00,000"* — so the person can see which is wrong.

**An approval arriving while a mismatch stands is refused once**, naming it; a
second approval proceeds. Warn loudly, do not block forever — a negotiated
contract may legitimately round, and that is the person's call, not the code's.

**How "once" is remembered, explicitly:** the refusal writes
`arithmetic_ack: true` onto the result tag's record in `tags_json` and
re-posts the review. The next approval sees the acknowledgement and proceeds.
No new column, and the flag lives with the tag, so **a correction that changes
either operand clears it** — the same rule `_record` already applies to
`reviewed`, and for the same reason: a figure that has just changed has not
been acknowledged since.

Decimal arithmetic throughout. No floats anywhere near a payment schedule.

---

## 7 · The agent, and the lesson that cost the last session three days

### 7a · Routing

`_ROUTER_PROMPT` (`app/ai/orchestrator.py:37`) lists six agents and the word
"MOU" appears nowhere; the `proposal` line reads *"anything about
proposals"*. **Today, "create the MOU for IBC" matches nothing and falls back
to `query`** — the owner's literal sentence does not work.

**One agent owns both documents.** The `proposal` router line becomes
*"proposals and MOUs"*. There is then no routing decision to get wrong — the
router never has to tell "create the IBC proposal" from "create the MOU for
IBC", which is a discrimination it would be making on the **fast tier**, the
same tier that called `create_proposal` six times in a row.

### 7b · Tools, and the system prompt in the same commit

New tools: `create_mou`, `answer_mou_questions`, `show_mou_questions`,
`confirm_mou_values`, `show_mou_review`, `correct_mou`.

**The system prompt gains its MOU paragraph in the same commit as the
tools.** This is lesson 1 stated as a rule: J1 added the fill tools and never
told the agent they existed, and the conversation looped in front of the
owner.

**And the wrong tool is made harmless.** `create_mou` called on a fill that
already has open questions **returns** `{already_open, still_to_answer,
what_to_do}` naming `answer_mou_questions`, rather than re-raising the round.
A tool result is read as fact where a system prompt is read as advice, so the
loop is impossible rather than merely unlikely.

### 7c · The editing tools must refuse for an MOU too

`edit_narrative` and `update_line_items` already refuse for `docx_simple`
(DEFECT 3). The reasoning transfers **exactly**: for an MOU, `content_md` is
the *projection* of a document already written and converted, so a rewrite
would change the record, leave the `.docx` the client receives untouched, and
report success over a file that never moved. The refusal must name the way
forward — `correct_mou` — rather than only saying no.

### 7d · File organisation

`proposal_agent.py` is already 1,081 lines. The fill-conversation handlers —
`_open_fill`, `_answer_questions`, `_show_questions`, `_round`,
`_confirm_values`, `_show_review`, `_correct_built` — move to a shared
`app/ai/agents/fill_tools.py` parameterised by document type, so the two
document types share one implementation and the agent file does not grow.

---

## 8 · Console and Android

**Console.** Item 6 gains a document-type choice (Proposal / MOU) beside the
existing flow choice. `POST /admin/programs/{id}/proposal-templates/docx`
gains `document_type: str = Form("proposal")`. The success panel reports the
tag counts as today **plus the ruled-blank warning (D-F)**: counting runs of
three or more underscores across the walk is nearly free, and the upload
summary is the one moment someone can still fix it. It does not refuse — a
genuinely hand-signed blank is legitimate.

Version history shows which document type a version is. `openapi.json` and
`generated.ts` are regenerated per handover §6b, **written back per file with
their existing line endings** — `openapi.json` and
`vocabularies.generated.ts` are CRLF, `generated.ts` is LF, and skipping this
turns a 7-line diff into ~22,000.

**Android.** A Documents section on the client screen, an `MouDto`, a contract
fixture captured from a real run, and a `ContractTest` case. The pure
decisions go in a testable class beside `ProposalFilledLines` — **there is no
Robolectric, so anything left in a fragment cannot be tested**, which is
exactly how E1's two defects survived. The project is not a git repository:
back up every file before editing.

---

## 9 · Testing

Per task: write the tests, **watch them fail for the right reason**,
implement, run the task's tests then `tests/docx` then the full backend,
**mutation-check the behaviour the task is about**, review the code with the
tests already green, then commit only the named paths and verify the commit in
a `git archive HEAD` export.

Four things this feature specifically must prove, each aimed at a failure the
last session actually shipped:

1. **Tool choice, not scripted tool calls.** Every J1/J2 test scripted
   `ToolCall(name=...)`, which proves what happens *when* a tool is called and
   never that a model *would* call it — and that is precisely where the
   conversation looped. The MOU gets a test where the tool is **not**
   scripted: the fake model layer is driven by the prompt it receives, and the
   assertions are that "create the MOU for IBC" reaches the MOU tools and that
   a reply to MOU questions does not reach `create_proposal`.

2. **Literals counted, never read.** `raw_count` over the tagged MOU for every
   repeated literal, and the built document asserted to contain **zero**
   occurrences of the placeholder — including in headers and footers, where
   `Error!` and the two `Date: ___________` also live.

3. **The proposal flow is untouched.** Uploading an MOU for IBC must leave
   `ibc_proposal_v4` current, and creating a proposal for IBC afterwards must
   still work. This is the D-B failure reproduced as a regression test.

4. **A mismatch is reported and never substituted.** An `ask_calculate` whose
   instalments do not sum to the total must warn, must refuse the first
   approval, and the value written must still be **exactly what the person
   typed**.

A golden suite over a tagged MOU, opt-in like the existing ones. The tagging
is done by a committed, idempotent, dry-run-by-default script the way
`scripts/tag_school_sample.py` was, because `data/samples` is gitignored and
without the script a reader cannot tell whether the fixture is missing or was
never built.

---

## 10 · Deliberately not in scope

- **No change to the proposal flow's behaviour.** Every change to a shared
  file is additive or parameterised, and the proposal path is pinned by tests.
- **No new paragraphs.** The MOU flow only replaces tags, exactly as the
  simple flow does (§11 of the simple-flow plan, owner's question 7).
- **No repair of the source document's broken field references** (§1c). That
  is the owner's to fix in Word; stripping text from a contract is not this
  pipeline's business.
- **No rate card.** D37 already exempts a document carrying its own prices,
  and `mou_documents` has no pricing columns to fill.
- **No MOU in the sales pipeline, in any aggregate, or in any deal-stage
  rule.** That is the whole point of D-A.

---

## 11 · Risks, ranked

1. **D-B's four call sites.** Getting one wrong retires or promotes the wrong
   template silently. Mitigated by reproducing the failure first and by a
   regression test that builds a proposal for IBC after an MOU upload.
2. **Tool choice.** Mitigated by one agent, the system prompt shipping with
   the tools, the deterministic loop-breaker, and an unscripted routing test.
3. **The arithmetic warning being wrong.** A false alarm is worse than no
   alarm because it teaches dismissal. Mitigated by parsing that returns
   `None` rather than guessing, and by warning only when every operand parses.
4. **The section heuristic on a different MOU.** This document has real
   heading styles; another might not. The fallback must be tested on a
   document with none, and an occurrence in a header or footer must never
   inherit a body heading.
5. **The reset ordering.** `proposal_fill_sessions` → `mou_documents` →
   `proposals`, pinned by an explicit index-order test as well as the generic
   FK walk, exactly as A4 did.

---

## 12 · Corrections — written by the build, and authoritative over the rest

**Where this section contradicts anything above it, this section is right.**
Added 2026-09-10, after M1-M3, U1, F1 and F2 shipped. Full detail per task is
in `.superpowers/sdd/2026-09-09-mou-pipeline-plan/progress.md`.

### 12.1 · §5's collapse key is wrong

§5 says "collapse on `duplicate_of`". **Collapsing on the literal alone is a
bug.** The tagged proposal's `<ask:1 Unit>` occurs four times with the contexts
"Magazine Rack", "Projector", "Audio and Mic System", "First Aid Box" — four
questions that share a default — and the MOU's `<ask:Yes>` seven times, once
per deliverables row. The key is **`(raw, context)`**: collapse only when a
person could not tell the two apart, which is the rule
`proposal_agent._group` already applies to the D13 review.

### 12.2 · §5's grouping applies to MOUs only

Applied to proposals it turns their first round from six questions into two
and breaks the golden proposal test. §10's "no change to the proposal flow's
behaviour" is the binding statement; the grouping is gated on
`document_type == "mou"`.

### 12.3 · §5's `limit=None` contract

`open_questions(limit=None)` must return **every outstanding occurrence**,
uncollapsed and ungrouped: `apply_answers` hands it straight to the model, and
narrowing it there leaves occurrences permanently unanswered.

### 12.4 · §1b's heading rule was too loose

"Nearest preceding heading" must test a **style prefix** (`Heading…`,
`Title…`), not a substring. `TableHead1` is the style of every table header
cell in the owner's MOU; a substring test made 26 of them into sections.

### 12.5 · §4 said the engine is reused unchanged. `tags.py` changed.

At the owner's instruction, `_row_label` now skips a first cell that is only
digits. The MOU's deliverables table numbers its rows and names the deliverable
in column 1, so seven `<ask:Yes>` were labelled "2", "4", "6". Any proposal
template with a numbered column had the same latent defect, so the fix is in
the shared scanner. Tables whose first column is the item name are unchanged.

### 12.6 · §10's "no rate card" assumption held; §2c's did not

The design input's §2c says YuviPep's own address and contact details are
never tagged. Measured against a **second** real MOU for the same product
(SSRVM, supplied by the owner already part-tagged), the YuviPep signatory
differs between contracts and the owner tags `<org address>` too. §2c is right
about the bank details and the footer contact block.

### 12.7 · A tag cannot reach document PROPERTIES — F3 must close this

Neither §3b nor §9 anticipated it. `scan` and `apply_tags` walk paragraphs;
properties are not paragraphs. The owner's MOU carried the client in
**thirteen** metadata values across `docProps/core.xml`, `docProps/app.xml`,
`docProps/custom.xml` and Word's `CoverPageProperties` custom part — including
the school's signatory as `dc:creator`, and the school's address, student
count and contract value in the cover-page properties. The tagging script
neutralises them so the template names nobody; **nothing fills them**, so
`_write_mou` must set the built document's properties from the filled values,
with a test.

### 12.8 · The round-count projections are all withdrawn

§5 projected 3-4 rounds. That figure, the design input's 8-9, and two later
simulation figures (7 and 10) are all unverifiable: a simulation cannot model
one answer settling every occurrence of the same fact (D8). **The honest
number is not known until G1 runs the fill against a live model.**

### 12.9 · The approval gate belongs to A2, not F2

`confirm_*_values` is an agent tool and the MOU's does not exist until A2. F2
shipped the service half: relations proposed and stored, mismatches surfaced
through `arithmetic_warnings` on the review line.

### 12.10 · U2 is deferred to second-last, by the owner's choice

The execution order is M1 → M2 → M3 → U1 → F1 → F2 → F3 → A1 → A2 → A3 → G1
→ R1 → R2 → **U2** → E1, so a working end-to-end pipeline arrives before the
console. Until U2, an MOU template is uploaded through the API with
`document_type=mou`.

### 12.11 · F3 added `mou_revisions`, by the owner's decision

§3b lists `MouDocument` alone. The correction path rewrites that row in place,
so without a revision the superseded wording of a contract is gone — and
`ProposalRevision` cannot be reused (its FK is to `proposals`, it carries the
commercial columns §3b deliberately omits, and `mou_documents` is wiped before
`proposal_revisions`). **Nothing reads MOU revisions yet**, which is why it was
put to the owner rather than assumed; they chose to keep the history.
`mou_revisions` joins WIPE ahead of `mou_documents`.

### 12.12 · §12.7 is closed, for MOUs only

`app/services/docx/properties.py` fills the properties after `refresh_static`
— LibreOffice rewrites the whole package, so anything written before it is
written into bytes about to be replaced. A literal it cannot fill, or one
whose occurrences disagree (§12.1's `(raw, context)` again), is **blanked**
rather than left standing. `dc:title` and `dc:subject` come from the lead and
the programme rather than from a filled literal, because they are what the
document is; `dc:creator`, `cp:keywords`, `cp:category` and
`cp:lastModifiedBy` are cleared, so no previous client's signatory is left as
the author of a contract.

Gated on the document type. **The proposal flow has the same latent defect**
and it is reported, not fixed.

### 12.13 · §12.8 is closed: the round count is nine

Measured 2026-09-10 by G1, against a live model over the tagged Sandur
contract: 12 of 65 tags filled without asking, 53 outstanding, **nine rounds**.
§12.8 withdrew four projections; the design input's 8-9 turns out to have been
the closest and this spec's own 3-4 the furthest out. The first four rounds
settled thirty-one questions from nineteen shown, which is D8 doing the work
no simulation could model.
