# The MOU pipeline — measured input for the design

> **SUPERSEDED IN PLACES, 2026-09-10.** This document's measurements of the
> MOU's shape are correct and were reproduced exactly. Two of its judgements
> were disproved by building it:
>
> * **Â§2c is wrong about YuviPep's own details.** A second real MOU for the
>   same product (SSRVM) shows the YuviPep signatory differs between
>   contracts, and the owner tags `<org address>` too. Â§2c is right about the
>   bank details and the footer contact block.
> * **Â§2b's "45-55 occurrences" and Â§4's D-D round projection are withdrawn.**
>   The tagged document has 65 occurrences of 33 distinct literals, and no
>   round count is verifiable until the fill runs against a live model.
>
> Its Â§4 decisions D-A..D-F were all ANSWERED by the owner; see the spec's
> Â§0 table. Authoritative now: the plan's Â§0 amendments, then the spec's Â§12.

**Written 2026-09-09. No code was written for it.** Everything in §1 was
measured against the owner's real MOU, not estimated. §3 lists what is already
built and reusable; §4 lists the decisions the design session has to take,
which are the whole of the work — the mechanism is finished.

The owner's brief, verbatim in substance: *an MOU pipeline exactly similar to
the simple-flow proposal pipeline. Same dossier, same tag system, same `ask`
tags. Uploaded in the same step 6 where the proposal template is uploaded.
Tied to an offering like IBC. "Create the MOU for IBC" in Jarvis follows the
MOU pipeline. It will have far more tags than a proposal, because far more
information lives in it.*

---

## 1 · What was measured

Sample: `data/samples/Sandur Education Centre_IBC Nexus and Lab2_MoU.docx`,
2,109,447 bytes. **Untagged** — the owner supplied it for reference.

| Figure | Value |
|---|---|
| Paragraphs in the walk | **240** |
| — in the body | 193 |
| — in headers | 17 |
| — in footers | **30** |
| Tables | 8 |
| Sections | 3 |
| Images | 11 |

> **47 of 240 paragraphs — nearly a fifth — are in headers and footers.**
> This is the trap that nearly spoiled the YuviPep 360 tagging: the client
> name appeared nine times, six of them in footers past where a reader
> scrolling the body would ever look, and a body-only tagging would have built
> a document with the placeholder still printed at the bottom of every page.
> Here it is worse in proportion. **Count every literal with
> `tests/docx/test_text.raw_count` before tagging, never by eye.**

### Repeated literals, counted

| Literal | Occurrences | What it is |
|---|---|---|
| `Sandur Education Centre` | **10** | the client, across cover, body, headers and footers |
| `Innovation Nexus` | **5** | the programme opted |
| `75` | **5** | student count — pricing table, minimum enrolment, the AY 2026-27 provision, the AY 2027-28 clause |
| `32` | **3** | total workshops — the responsibilities prose AND the annexure row |
| `Rs. 1,50,000` | 2 | the two instalments |
| `Y S Ghorpade` | 2 | the school's signatory |
| `Rs. 4000`, `Rs. 3,00,000` | 1 each | per-student price, annual total |

**Every one of these is a separate occurrence with its own `tag_id` (D1).**
`75` appearing five times is five questions the author may want answered the
same way and the model must resolve together (D8) — and the count is a number
the contract is built on, so a stale one in the fourth place is a real defect.

---

## 2 · Where the tags go

The MOU divides cleanly into three, and only the first two are tagged.

### 2a · Client-specific — always tagged

| Where | Sample value | Suggested tag |
|---|---|---|
| Cover, headers, footers ×10 | Sandur Education Centre | `<School Name>` |
| Party block (¶34) | `Sy. No.: 145/1A, Rayarakere, … KARNATAKA` | `<School Address>` |
| Party block (¶34) | `represented by …` | `<School Representative>` |
| Signature block | `Smt. Y S Ghorpade / President` | `<School Signatory>`, `<School Signatory Title>` |
| Signature block ×2 | `Date: ___________` | `<ask:date of signing>` — **a ruled blank, not a word**; the author replaces the underscores with the tag |
| ¶30 | `First Day of September, Two Thousand Twenty-Six (01-09-2026)` | `<ask:MOU date>` |

### 2b · Commercial and operational — always ASKED

These are what make an MOU an MOU, and every one is negotiated per school.

| Where | Sample value | Suggested tag |
|---|---|---|
| Operation Terms | Innovation Nexus | `<ask:Innovation Nexus>` |
| Operation Terms + ¶49 prose | 32 workshops | `<ask:32>` (×3 places) |
| Operation Terms | `3, 5, 6, 7, 8 and 9` | `<ask:3, 5, 6, 7, 8 and 9>` |
| Programme completion | `second week of February 2027` | `<ask:second week of February 2027>` |
| Pricing | `Rs. 4000/- net (including GST) per student annually.` | `<ask_calculate:Rs. 4000/- net …>` |
| Pricing | `75` | `<ask:75>` |
| Pricing | `Rs. 3,00,000/- Net (Including GST).` | `<ask_calculate:Rs. 3,00,000/- …>` |
| Enrolment ×3 | minimum 75 | `<ask:75>` |
| Academic year ×2 | `AY 2026-27`, `From AY 2027-28` | `<ask:AY 2026-27>` |
| First instalment | `Rs. 1,50,000/-` | `<ask_calculate:Rs. 1,50,000/- …>` |
| Second instalment | `Rs. 1,50,000/-` + `first week of November 2026` | two tags |
| Deliverables table (10 rows) | `1`, `Yes`, `1 Set`, `Eligible` | `<ask:1>`, `<ask:Yes>`, `<ask:1 Set>` … |

**Rough total: 45–55 occurrences of ~30 distinct literals**, against the
tagged YuviPep proposal's 16 of 8. The owner's expectation that an MOU carries
far more is correct, and it changes one thing about the conversation: at
`QUESTIONS_PER_ROUND = 6` this is **eight or nine rounds**, where the proposal
was one or two. §4 asks whether that is acceptable.

### 2c · Never tagged

YuviPep's own address, bank details (account number, IFSC, branch), contact
details, and the Confidentiality and General Terms prose. These are the same
in every MOU and a tag there is a way to get them wrong.

---

## 3 · What is already built, and needs no change

The mechanism is finished. This is the honest scope: the MOU pipeline is
**plumbing plus one data-model decision**, not a new engine.

| Reusable as-is | What it does |
|---|---|
| `app/services/docx/tags.py` | the tag grammar and the occurrence scan — identity per occurrence (D1) |
| `app/services/docx/text.py` | `walk_paragraphs`, which reaches headers and footers — the 47 paragraphs above depend on this |
| `app/services/docx/tagfill.py` | the occurrence-addressed writer; refuses a stale offset |
| `app/ai/docx_tagfill.py` | `resolve_tags`, `answer_round`, `revise` — citation checking (D14), never writes its own figure (D15) |
| `app/services/client_dossier.py` | the whole client, assembled once (D7) — **the MOU needs exactly this** |
| `app/services/docx/convert.py`, `index.py`, `outline.py` | PDF, static contents page, projection |
| `proposal_fill_service` status machine | gathering → asking → reviewing → ready → built, and `mark_ready` as the only door (D13) |

The fill conversation, the review, the correction of a built document, and the
`filled_json` provenance card all work and are deployed. **An MOU that reused
them would inherit every one of those guarantees.**

---

## 4 · The decisions the design session must take

These are genuinely open. Nothing below should be guessed at in code.

### D-A · Where does a built MOU live?

An MOU is not a proposal: it has two parties, signatures, instalments and a
term. But `Proposal` already carries `template_kind`, `filled_json`,
`docx_path`, `pdf_path` and a revision history, and the Android app renders
all of it.

- **A new `mou_documents` table** is free (`create_all` builds a missing table;
  it is a column that costs a migration). It keeps MOUs out of the proposals
  list and the sales pipeline, where they would otherwise appear as deals.
  It costs new API routes and a new Android screen.
- **Reusing `Proposal`** with `template_kind="mou_simple"` ships in a day and
  puts MOUs in the proposals list, which is probably wrong for a contract.

*Recommendation: a new table.* An MOU appearing as a proposal in the pipeline
would corrupt exactly the reporting this project exists to keep honest.

### D-B · Two current templates per programme

`ProposalTemplate` is found by `program_id` + `is_current`. A programme now
needs **two** current templates — one proposal, one MOU — so `is_current` has
to become current-per-kind, and the promote-on-delete logic in
`app/api/admin.py` with it. This is the single most delicate change: get it
wrong and uploading an MOU retires the proposal template.

### D-C · Which fill-session table

`proposal_fill_sessions.proposal_id` is a `ForeignKey("proposals.id")`. An MOU
fill needs to point at an MOU. A second table duplicates a status machine that
is already proven; a nullable `mou_id` column costs a migration — and
`scripts/migrations/` now exists, so a migration is no longer the barrier it
was when D11 refused one.

### D-D · Nine rounds of questions

45–55 occurrences at six per round is eight or nine exchanges. D5 chose six
*"because nineteen round trips is an interrogation"*. Fifty-odd is worse.
Options: a larger round for MOUs; grouping by section (parties, then terms,
then commercials, then deliverables) so each round is coherent; or a console
form for the MOU's structured fields with only the prose asked in chat.

### D-E · The arithmetic is load-bearing here

In a proposal an `ask_calculate` is a figure in a document. In an MOU it is a
payment schedule: `4000 × 75 = 3,00,000`, split into two instalments of
`1,50,000`. D15 says the assistant states its conclusion and asks, and writes
the reply verbatim — no Python arithmetic. That was right for a proposal.
**For a contract, a total that does not equal price × students, or instalments
that do not sum to the total, is a defect a human will not always catch.** The
design must decide whether the review checks the arithmetic it was given —
*without* the model inventing figures, which D15 forbids absolutely.

### D-F · `Date: ___________`

The MOU carries ruled blanks the tag grammar cannot see: `TAG_RE` needs
`<…>`. The author replaces them when tagging. Worth stating in the upload
guidance, because a blank left as underscores is silently not a tag and will
reach the client as underscores.

---

## 5 · What this document does not decide

Nothing about the Android app, the console's upload screen layout, or the
wording of the MOU questions. Those follow the decisions above.
