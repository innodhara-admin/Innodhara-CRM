# DOCX proposal templates with AI-suggested placeholders

**Date:** 2026-09-03
**Status:** approved design, ready for an implementation plan
**Touches:** backend (`app/`), setup console (`Dashboard/`), Android app
(`YuvipepSalesforceAI`)

---

## 1 · The problem

Checklist item 6 ("A proposal template for each offering") stores a Markdown
body with `{variables}`. `proposal_service.build_proposal` substitutes the
variables; `document_service.render_docx` / `render_pdf` then rebuild a
document from that Markdown with python-docx and reportlab.

Three defects follow from that pipeline, all reported from real use:

1. **The AI writes its own task list into the client's document.** Prose
   reaches the proposal through `rewrite_narrative` and `parse_and_apply_edit`,
   which hand the model a whole Markdown document and take back whatever it
   returns. A model that is unsure writes *about* the work instead of doing it
   — "I will now draft the greeting", "[Insert pricing summary]". This is the
   same failure the project already recorded as F28 and F30 and fenced for
   messages in `draft_check.py`; the proposal body was never put behind that
   fence at generation time.

2. **Markdown artefacts survive into the document.** `document_service._BOLD`
   is `\*\*(.+?)\*\*` — non-greedy, single-line, pairs only. An unpaired `**`,
   a `**` spanning a line break, `*italic*`, `***both***`, numbered lists and
   nested lists all pass through untouched and are printed literally. The
   renderer strips the marker rather than applying the formatting, so even a
   well-formed `**Total**` loses its bold.

3. **The rendered document has no branding.** `render_docx` starts from
   `Document()` — a blank python-docx default. Everything the organisation's
   real proposals carry (cover art, logos, per-section headers and footers,
   theme fonts, styled tables, photography) cannot be expressed in the Markdown
   subset and therefore does not exist in the output.

The organisation's actual proposals are `.docx` files: 14–33 embedded images
each, 5–23 sections with their own headers and footers, styled tables for
pricing, and hand-substituted literals such as `School Name` and
`Kind Attention: Name`. Nothing in the current pipeline can produce them.

## 2 · The approach

Stop generating documents and start **filling** them.

An administrator uploads the real `.docx` at checklist item 6. The backend
parses it into a block outline and OCRs its images. An LLM pass proposes
placeholders — where a greeting belongs, which literal is really the client's
name, which table is the rate card — and the administrator accepts, rejects,
rewords, moves or adds each one in a dashboard editor. The accepted set is
saved as a **fill plan**.

When Jarvis creates a proposal from the Android app, the backend loads the
**untouched source `.docx`**, resolves every system-bound field from the
database, asks the model for plain text for the prose placeholders only, and
writes the results into a copy.

The source file is never rewritten. Every proposal is
`source.docx + plan + values -> new file`, so generating the same proposal
twice gives the same bytes, and a bad fill can be re-run without the document
degrading across edits.

### 2.1 Why this removes the defects rather than filtering them

- The model receives a **brief for one placeholder** and returns **plain text**
  for a paragraph that already carries its formatting, cloned from a real
  neighbouring block. No Markdown parser exists anywhere in the path, so there
  is nothing for `**` to leak through. Defect 2 becomes structurally impossible
  rather than filtered.
- The model never sees, and cannot rewrite, the document as a whole. It cannot
  restate the brief into the document, because the brief is not part of the
  document. Defect 1 loses its mechanism, and a deterministic scrubber (§7)
  catches the residue.
- Branding is preserved because it is never re-created. Defect 3 disappears.

### 2.2 Decisions taken before this document

| # | Decision |
|---|---|
| D1 | Editor is a **placeholder overlay**, not a WYSIWYG. The document's structure and styling are edited in Word; the console edits placeholders, literal-token bindings and paragraph text only. |
| D2 | PDF for DOCX-backed proposals comes from **LibreOffice headless**. `libreoffice-writer` is not yet on the VM and is installed as the plan's first step. |
| D3 | DOCX templates sit **alongside** Markdown ones, discriminated by a `kind` column. Existing templates and every existing consumer are untouched. |
| D4 | The backend freeze in `Dashboard/READMEs/09_BACKEND_CHANGES.md` is **reopened by the owner** for this work, and the reopening is recorded there. |
| D5 | The rate card **fills the cells of the table already in the document**; it does not replace the table. |
| D6 | A prose placeholder the model cannot ground in supplied facts is **left unfilled and escalated**, never invented. |
| D7 | Tesseract OCRs embedded images **once at upload**, cached on the template. No vision-model call. |
| D8 | The Android app changes **minimally**: `content_md` stays faithful, plus a "what the AI wrote" summary. |

## 3 · Data model

### 3.1 `ProposalTemplate` — one new column

```
kind: Mapped[str] = mapped_column(String(20), default="markdown", nullable=False)
# "markdown" | "docx"
```

`body_md` stays `nullable=False`. For a DOCX template it holds a **text
projection** of the document — headings, paragraph text, table cells rendered
as plain lines. This is deliberate: `draft_check`, `ProposalRevision`,
the bundle export/import contract, the go-live checklist, the descriptor
conformance test and the Android `content_md` view all keep working with no
change, and the projection is genuinely useful as a searchable body.

### 3.2 `proposal_template_docs` — new table, 1:1 with a template *version*

```
id, org_id, template_id (FK, unique)
source_path      str    # storage rel path; the uploaded bytes, never rewritten
filename         str
sha256           str
size_bytes       int
outline_json     JSON   # the editor's model (§4)
ocr_json         JSON   # image_id -> tesseract text
plan_json        JSON   # the fill plan (§5)
index_kind       str    # "field" | "static" | "none"
analysis_status  str    # "pending" | "ready" | "failed"
analysis_error   str|None
created_at
```

Keying on `template_id` rather than `(program, name)` keeps the existing
versioning rule intact: publishing a new version uploads a new file and gets a
new row, and old proposals still resolve their exact locked version.

### 3.3 `Proposal` — one new column

```
filled_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
# [{"key","kind","source":"system"|"ai"|"unfilled","text","brief","anchor"}]
```

Feeds the audit trail, the Android summary, and the per-placeholder re-fill in
§9.

## 4 · The outline

Produced once at upload by `docx_template_service.parse()`. Read-only; it is a
*view* of the source, never a thing that is written back.

A block is:

```
{ "id": "b7",                       # stable within this outline
  "path": "body[7]",                # positional address into the source
  "kind": "paragraph"|"heading"|"table"|"image"|"pagebreak",
  "style": "Heading 1",
  "level": 1,                       # headings only
  "text": "About YuviPep's ...",
  "runs": [{"text":"About ","bold":false}, ...],
  "images": ["image3.jpeg"],        # rels resolved to media part names
  "ocr": "…tesseract text…",        # from ocr_json, images only
  "table": {"rows":13,"cols":3,"header":[...],"sample":[[...]]} }
```

Header and footer parts are parsed the same way and addressed as
`sec[1]/hdr/body[0]`. Two of the four sample documents carry real
header/footer parts; `Essential Lab.docx` fakes them as body paragraphs. The
outline covers both without special-casing.

**Positional paths are stable** because the source `.docx` is immutable once
uploaded — a new upload is a new version with a new row. Each anchor
additionally stores a **fingerprint** (`kind` + `style` + first 40 characters
of text). Generation verifies the fingerprint and raises rather than writing
into the wrong place if it ever disagrees.

## 5 · The fill plan

Four entry kinds. The split between them is the safety property: numbers and
identities are `token`/`table` entries resolved from the database, and only
`insert`/`replace` entries ever reach a model.

### 5.1 `token` — document-wide literal binding

```
{"kind":"token", "key":"client_name",
 "literal":"School Name", "occurrences":6, "scope":"document"}
```

Replaces every occurrence of a literal, in body paragraphs, table cells and
header/footer parts. This is what handles `School Name` (×6 in
`Essential Lab.docx`), `Kind Attention: Name`, and the `School School` typo in
`School_YuviPep 360_2 1.docx`.

Bindable keys are exactly the variables `build_proposal` already computes:
`client_name`, `contact_name`, `contact_title`, `sender_name`, `sender_email`,
`org_name`, `program_name`, `program_description`, `date`, `total_amount`.

### 5.2 `cell` and `table` — the rate card

```
{"kind":"table", "path":"body[32]",
 "columns":[{"col":0,"field":"label"},{"col":1,"field":"line_total"}],
 "header_rows":1,
 "total_row":{"row":-1,"label_col":0,"value_col":1,"keep_label":true},
 "body_rows":"expand"}          # expand | fixed
```

At generation the body rows are written from the **locked `PricingTable`
version**, adding or removing rows to match the line items while cloning the
formatting of an existing body row. `header_rows` are copied verbatim. The
total row's label is kept and only its value written.

The existing invariant holds unchanged: **numbers never come from the AI.**
`compute_totals` still computes, `line_items` are still stored on the proposal,
and a `cell`/`table` entry cannot be filled by a model.

### 5.3 `insert` — AI-written prose at a position

```
{"kind":"insert", "key":"greeting_para",
 "after":"body[5]",             # or "before"
 "shape":"paragraph",           # paragraph | paragraphs | bullets
 "style_ref":"body[8]",         # clone this block's pPr/rPr
 "brief":"2-3 sentence opening from YuviPep to the client, referencing the meeting",
 "max_words":90,
 "required":true}
```

`style_ref` defaults to the nearest body-text sibling, so generated paragraphs
inherit the document's real font, size, spacing and justification. `shape`
decides how many paragraph elements are created and whether a list style is
applied.

### 5.4 `replace` — AI-written text into an existing paragraph

```
{"kind":"replace", "key":"why_us_para", "path":"body[20]",
 "brief":"…", "max_words":120, "required":false}
```

Formatting of the existing paragraph is preserved; only its text changes.

## 6 · Run-span rewriting

The one genuinely fiddly algorithm, and the reason a naive implementation would
fail on these files. Word fragments runs arbitrarily. In `Essential Lab.docx`:

```python
paragraph.runs  ->  ['School', ' ', 'Name']
paragraph.runs  ->  ['YuviPep will transform an existing workshop area or a '
                     'dedicated classroom at School', ' ', 'Name', ' ',
                     'into', ' ', 'an', ' ', 'Essential', ' ', 'Lab.', ...]
```

`run.text.replace("School Name", …)` matches nothing, in either case.

The algorithm, applied to any paragraph (body, table cell, header, footer):

1. Join the run texts, building an `offset -> run index` map.
2. Find the match span in the **joined** text.
3. Write the replacement into the run containing the span's start.
4. Blank the remaining characters of the runs the span covers.
5. Leave every other run untouched.

The first covered run's formatting wins. For `['School',' ','Name']` that is
exactly right, the fragments being uniform. Where a span's runs differ, taking
the first is a choice rather than a certainty, so the editor's preview (§11)
exists to let an administrator see the result before publishing.

The same primitive serves `replace` entries: the span is the whole paragraph.

## 7 · The fill contract

One LLM call per proposal, batched over every `insert`/`replace` entry, JSON
out, one field per placeholder key.

**Given:** the org, program and program description; the lead and primary
contact; the project objective; the meeting notes summary; the accepted brief
and `max_words` for each placeholder; and the surrounding block text so the
model can match the document's voice.

**Contract:** plain text only; one entry per key; a key it cannot ground in the
supplied facts is returned as `null` with a `reason`.

**Then a deterministic scrubber rejects a fill that contains:**

- Markdown markers — `**`, `__`, `##`, a leading `- ` or `* `, `|` table pipes,
  backticks.
- Meta-instructions — a bracketed fill-in (`[Insert …]`, `[Name]`) via the
  existing `draft_check.find_blanks`; opening phrases such as
  "I will", "Here is", "Below is", "As requested", "Certainly"; or text whose
  first sentence restates its own brief above a similarity threshold.
- A money-shaped number outside the locked set, reusing
  `proposal_service._allowed_amounts` and the `narrative_price_drift` window
  logic.
- More than `max_words` words.

A rejected fill is retried **once** with the failure named. Still rejected, or
returned `null`: the placeholder is left unfilled, `filled_json` records
`source: "unfilled"`, and the existing `record_decision(..., needs_human=True)`
path fires — the same escalation `build_proposal` already raises for
`[missing:…]`, so the send gate blocks it exactly as it does today.

This is a fence, not a prompt. The prompt asking for clean text is worth
having; it is the hint. The scrubber is the guard. This project has four
recorded findings (F9, F4, F23, F28) of a model ignoring an instruction given
in capitals.

## 8 · The index

**Corrected after measuring the real documents.** The design originally assumed
`School_YuviPep 360_2 1.docx` carried a live Word TOC field. It does not:
`w:instrText` nodes = 0, `w:fldSimple` = 0. What it has is a `w:sdt` with
`docPartGallery="Table of Contents"` wrapping 32 paragraphs styled `TOC1`,
`TOC2` and `TOC3`, each an internal hyperlink to `_bookmarkN` with the page
number as **literal text** in its last `w:t`. Nothing in Word will refresh it,
so `<w:updateFields>` would be dead code for this corpus. Measured across all
four samples: three are `none`, one is `static`, none is `field`.

Three cases, detected at upload and recorded as `index_kind`:

**`field`** — a real TOC field code (`w:instrText` containing `TOC`, or a
`w:fldSimple` whose `w:instr` contains `TOC`). Left alone, with
`<w:updateFields w:val="true"/>` set in `settings.xml`. Supported because a
future upload may have one; none of the current four does.

**`static`** — paragraphs styled `TOC1`–`TOC9`, or a `Table of Contents` /
`Contents` / `Index` paragraph followed by entry paragraphs. Each entry yields
`(paragraph, label, anchor, page_node)`, where `page_node` is its final `w:t`.

Refreshed by a **two-pass LibreOffice convert**:

1. Convert the filled DOCX to PDF.
2. Read per-page text with `pypdf` (already a dependency).
3. For each entry, find the first page whose text contains the entry's label —
   **skipping the pages the TOC itself occupies**. This exclusion is not
   optional: the TOC page contains every heading, so without it every entry
   resolves to the TOC's own page. Measured on the real file,
   `Investment and Deliverables` matches pages `[2, 27]`; page 2 is the TOC and
   27 is the answer.
4. Write the page numbers into the `page_node`s and convert again.

Entry *labels* are also regenerated from the live heading tree, so a
placeholder that adds or renames a heading is reflected.

**`none`** — nothing to do.

The editor states which case the uploaded document is, so an administrator with
a static index understands why the second pass exists.

## 9 · Generation and editing

### 9.1 Creation

`proposal_service.build_proposal` branches on `template.kind`:

- `markdown` — today's path, byte-for-byte unchanged.
- `docx` — `docx_fill_service.build()`:
  1. Load the source `.docx` from storage.
  2. Resolve system-bound values (§5.1, §5.2) from the database.
  3. One LLM call for the prose placeholders; scrub; retry once; escalate.
  4. Write into a copy: token spans, table cells and rows, inserted and
     replaced paragraphs.
  5. Refresh the index (§8).
  6. Save to storage, set `proposal.docx_path`.
  7. Build `content_md` (the text projection), `line_items`, `total_amount`,
     `filled_json`.

`variables`, `line_items`, `total_amount`, `template_version` and
`pricing_version` are populated identically for both kinds, so approvals,
audit, revisions and the price-drift fence are unaffected.

### 9.2 PDF

`proposal_email_service.ensure_rendered_files` branches:

- `markdown` — reportlab, unchanged.
- `docx` — `soffice --headless --convert-to pdf` into a per-call profile
  directory, with a timeout and an explicit error if the binary is missing.
  Never falls back to reportlab: a silently unbranded PDF going to a client is
  worse than a refusal.

### 9.3 Editing an existing DOCX proposal

`rewrite_narrative` on a whole document is wrong here — it is the mechanism of
defect 1, and re-rendering would erode the branding across edits.

For a `docx` proposal, `parse_and_apply_edit` maps the instruction to:

- **line-item operations** — unchanged, still `apply_line_item_ops`; and/or
- **a per-placeholder re-fill** — the instruction names one or more placeholder
  keys, those are re-filled through §7, and the document is regenerated from
  the source with the updated `filled_json`.

Regeneration from source means an edit can never compound formatting damage,
and a revision is fully reproducible from `(template version, pricing version,
filled_json)`.

## 10 · API surface

All under the existing `require_permission("manage_templates")` for authoring
and `send_proposal` for generation.

| Method | Route | Does |
|---|---|---|
| POST | `/admin/programs/{program_id}/proposal-templates/docx` | multipart upload; creates a `kind="docx"` template version, parses, OCRs; returns the doc id |
| GET | `/admin/proposal-template-docs/{id}` | outline + plan + `index_kind` + analysis status |
| POST | `/admin/proposal-template-docs/{id}/suggest` | run the LLM suggestion pass; returns suggested entries (advisory, not saved) |
| PUT | `/admin/proposal-template-docs/{id}/plan` | save the edited fill plan |
| POST | `/admin/proposal-template-docs/{id}/preview` | render a sample filled DOCX+PDF with dummy values |
| GET | `/admin/proposal-template-docs/{id}/media/{name}` | image thumbnail for the editor |

Upload limits follow the existing `upload_manual_revision` guard in shape but
not in size: `.docx` only, non-empty, **25 MB** — the largest sample document is
14.8 MB, which the 15 MB proposal-upload limit would very nearly refuse.

`GET /proposals/{id}` gains `filled_json` (change #7 below).

## 11 · Dashboard

Item 6 gains a mode switch. **Markdown body** is today's `EntityForm`, entirely
unchanged. **DOCX template** is a new editor screen built from the existing
primitives (`Section`, `Banner`, `Field`, `primitives.tsx`, `tokens.css`) with
**no new dependency** — no WYSIWYG library, consistent with D1.

The editor shows:

- the block flow, read-only: headings, paragraphs, tables, image thumbnails;
- green suggestion chips inline, each with Accept / Reject / Edit brief /
  Move up / Move down, and an "add a placeholder here" affordance between any
  two blocks;
- a **token panel** listing every detected literal with its occurrence count
  and a field to bind it to;
- a **table binding** dialog for column mapping, header rows and the total row;
- the detected `index_kind`, stated plainly;
- **Preview with sample data**, which renders a real DOCX and PDF so the
  administrator sees the result before publishing.

New routes go through `npm run gen:api`, so `gen:check` (which `prebuild` runs)
and the generated client stay green.

## 12 · Android

`content_md` remains a faithful text projection, so `ProposalDetailFragment`,
the revision trail, PDF preview, manual re-upload and approve-and-send keep
working with no change.

Added: `filled_json` on the proposal DTO and a compact "what the AI wrote"
section listing each placeholder, its source (`system` / `ai` / `unfilled`) and
its text — so the salesperson can see the model's contribution before tapping
approve. Unfilled required placeholders are shown in the blocked state the
approval gate already produces.

## 13 · Backend changes to record

Recorded in `Dashboard/READMEs/09_BACKEND_CHANGES.md` as a fifth unfreeze (D4):

| # | Change | Files |
|---|---|---|
| 11 | `kind` on `ProposalTemplate` | `app/models/program.py` |
| 12 | `proposal_template_docs` table | `app/models/program.py` |
| 13 | `filled_json` on `Proposal` | `app/models/proposal.py` |
| 14 | `docx_template_service` (parse, OCR, project) | `app/services/` *(new)* |
| 15 | `docx_fill_service` (fill, index, run-spans) | `app/services/` *(new)* |
| 16 | `docx_suggest` (LLM suggestion pass) | `app/ai/` *(new)* |
| 17 | six template-doc routes; `filled_json` on `GET /proposals/{id}` | `app/api/admin.py`, `app/api/proposals.py` |
| 18 | `build_proposal` branches on `kind` | `app/services/proposal_service.py` |
| 19 | `ensure_rendered_files` branches; LibreOffice converter | `app/services/proposal_email_service.py`, `app/services/` *(new)* |
| 20 | `parse_and_apply_edit` per-placeholder re-fill | `app/ai/agents/proposal_agent.py` |

New Python dependency: none. `python-docx` 1.2.0, `lxml` 6.1.2, `pypdf` 6.16.2
and `Pillow` 12.3.0 are already in the venv. `pytesseract` is **not** installed
and is not added — OCR shells out to the `tesseract` binary through
`subprocess`, the same way the LibreOffice converter calls `soffice`.

System packages: `tesseract-ocr` 4.1.1 with the `eng` model is already present;
`libreoffice-writer` must be installed (D2).

## 14 · Verification

**Unit, in-repo, fast.** Synthetic `.docx` fixtures built in-test with
python-docx, covering: fragmented runs across a token boundary; a token in a
table cell; a token in a header part; paragraph insert with style clone; table
row expansion and contraction; the total row; fingerprint mismatch raising;
every scrubber rejection class; static-index regeneration.

**Golden, opt-in.** The four real documents copied to `data/samples/` on the VM
(too large for git; skipped when absent). Asserts: the filled document opens,
its media part count is unchanged, its section count is unchanged, every bound
literal is gone, and the PDF converts.

**End-to-end.** Validated on `Essential Lab.docx` (no index, fake footers as
body paragraphs, 3 tables, 6 token occurrences) and
`School_YuviPep 360_2 1.docx` (real TOC field, 23 sections, 18 tables, 33
images) — the two extremes. `Innovation Lab Template.docx` and
`School_YuviPep 360 EmpowerED_New_compressed.docx` are left for the owner.

**Regression.** The existing pytest suite must stay green; the Markdown path
has no behaviour change. The Android app is built (`:app:assembleOrgDebug`).

## 15 · Risks

| Risk | Handling |
|---|---|
| Run-span rewriting misbehaves on documents 3 and 4 | Written test-first against the real files; the fingerprint check turns a silent mis-write into a loud failure |
| ~~LibreOffice does not refresh the TOC field~~ — resolved: no sample has a field, so the static two-pass is the primary path, verified end to end | LibreOffice 7.3.7 installed and measured: 1.5 s / 3.1 s per convert, ~250 MB RSS; `pypdf` heading→page mapping verified on the 29-page output |
| The suggestion pass proposes poor placeholders | Advisory only — nothing enters the plan without a human accepting it |
| A 14.8 MB upload times out or exhausts memory | Parse is streamed; OCR runs per image with a per-image timeout; `analysis_status` makes a failure visible instead of silent |
| The in-flight `feature/pre-sales-cold-calling` work is disturbed | Full backup taken before any change (archive + git bundle + tracked diff); no commits made to that branch without asking |

## 16 · Out of scope

- Editing document structure, styling or images in the console (Word's job).
- Migrating existing Markdown templates to DOCX.
- Per-placeholder review UI in the Android app beyond the summary (D8).
- Multi-language proposals.

## 17 · Gap found while planning: the bundle

`Dashboard/src/descriptors/catalogue.ts` marks `proposalTemplates` as
`inBundle: true`, exporting `name` + `body_md`. A DOCX template's `body_md` is
its **text projection** (§3.1), so a bundle round trip would silently recreate
it as a Markdown template: the cover, images, headers, footers and styled
tables would vanish and nobody would be told.

The document is not in the bundle and cannot be — it is up to 25 MB of binary.
So the export **skips** a `kind="docx"` template and says so in its summary, and
the import **refuses** to supersede a current DOCX template with a Markdown row
rather than warning. Recorded as **D29**.

This was not in the original design. It is in the implementation plan as Task
19, Step 4, with tests in `roundtrip.test.ts` and `validate.test.ts`.

## 18 · Corrections made during execution

Section 8 was rewritten mid-execution after measuring the real documents (no
sample has a live TOC field). Six further rulings corrected defects in the
implementation plan rather than in this design — the reset-taxonomy bucket
count, a `_currency` key that would have leaked into stored proposals and the
Android payload, the Android project not being a git repository, and a
defective raw-XML ground-truth helper that undercounted text-box paragraphs.

They are tabulated in the plan's **"Rulings applied during execution"** section,
and the running record — including deferred minor findings — is the SDD ledger
at `.superpowers/sdd/2026-09-03-docx-proposal-templates-plan/progress.md`.
