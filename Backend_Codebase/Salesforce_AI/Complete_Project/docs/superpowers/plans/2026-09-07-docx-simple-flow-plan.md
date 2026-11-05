# DOCX proposal templates — the SIMPLE flow

**Design and implementation plan. Written 7 September 2026. No code was written
in the session that produced it.**

Everything in §2 was measured against the running system at commit `cbc2247`
on branch `feature/docx-proposal-templates`, and against the owner's own
hand-tagged document. Where this document disagrees with any other document in
the repository, this one was checked more recently — but check the code before
trusting either.

---

## 0 · Amendments — read this before anything below it

**Written by the build, not by the author of this plan. Where this section
contradicts anything further down, this section is right.** It records what the
build measured that the plan could not, and what the owner decided after
reading it. Full detail, task by task, is in the execution ledger at
`.superpowers/sdd/2026-09-07-docx-simple-flow-plan/progress.md`.

**Progress.** A1-A4, B1-B3 and C1 are complete and committed on
`feature/docx-proposal-templates`. **C2, C3, J1, J2, J3, E1 and E2 remain.**
The `- [ ]` checkboxes below are not maintained; the ledger is.

### A · Section 3's HTML rejection is overridden (owner, 7 September)

The row in the "Not a tag" table reading *anything matching
`</?[a-z][a-z0-9]*\s*/?>`* **is no longer the rule.** Measured across all five
real documents, it rejected **zero** strings -- there is no HTML inside a
`.docx` -- while silently dropping `<price>`, `<name>` and `<address>`, which
are exactly the placeholders an author would write. A refused tag is silent and
reaches the client as a literal `<price>`; an accepted `<b>` shows in the upload
summary and costs one question a human dismisses, and D13 already puts a human
in front of every value.

`TAG_RE` now refuses **only unambiguous markup**: a leading slash (`</b>`) or a
trailing one (`<p/>`). A bare word is a tag. Commit `1b2f2f2`. The tagged
template still yields 25 occurrences of 20 distinct literals, so this was a
pure widening.

### B · An occurrence is addressed by `ordinal`, never by `path`

Task A1's text below says `scan` returns `{..., path, ...}`. It does not, and
should not: §5's data model, D1 and D2 all say the address is the walk ordinal,
and §2.3a is the measurement that settled it (path reaches 5 of 7 places, the
walk reaches 7 of 7). **§5 is correct and §9's A1 line is not.** The
human-readable path is `docx.text.label_for`, added by A2, and is display only
-- it may be `None`, and nothing in this feature calls `outline.resolve`.

### C · The dossier's headroom is about 16%, not 25%

D7 calls `DOSSIER_CHAR_CEILING = 60_000` "about 25% above the busiest client
today". Measured in C1 against the real serialisation, Meridian Data Centres
produces **51,519 characters**, leaving 8,481 -- about 16%. The gap against
D7's projected ~31,955 is almost entirely `action_plans` and
`client_commitments`, project-layer records D7 asks for and that the 47,525
measurement did not count.

**The ceiling is unchanged at 60,000**, exactly as the plan fixed it. What is
corrected is the claim about how much room it leaves. A client meaningfully
busier than Meridian will start trimming, and the first thing trimmed is the
oldest meetings, which are the richest source. Raising it is the owner's call.

### D · A `docx_simple` template refuses to build, until J1

`proposal_service` branches on `kind == "docx"`, so a `docx_simple` template
fell through to the **markdown** path. Reproduced before fixing: `POST
/proposals` returned 200 and a draft whose `content_md` read *"Prepared for
`<School Name>` ... Laptops `<ask:6 Units>`"* -- raw tags in client-facing
content, no branding, nothing failing loudly.

B1 added a loud refusal, because uploading a simple template is what makes that
state reachable. **J1 must replace that guard with the fill conversation**, not
merely add a branch beside it.

### E · Two things that belong to no task

1. **D16's console half.** §6 says the console should check at *upload* time
   whether the offering has a current rate card and offer to publish one in the
   same step. It is not in B3's file list, nor in any other task in §9. Not
   built. Needs an owner decision about where it goes.
2. **The served console bundle is stale.** `Dashboard/dist` is dated
   4 September, older than every Phase B console change, and something rebuilt
   it after the complex flow's deploy note was written. A deploy needs
   `node node_modules/vite/bin/vite.js build`. `dist` is build output and is
   never committed.

### F · How to read the test numbers

The "440 in isolation" figure quoted for `cbc2247` is a **collected** count
(407 passed + 33 skipped), not a passed count. Every later figure in the ledger
states passed and skipped separately for that reason.

`tests/test_what_is_late.py` has four time-of-day-sensitive tests. Depending on
the hour, the working tree shows either 5 failures or 1. The only failure that
is always there is
`tests/test_relationship_screens.py::test_the_worst_neglected_client_is_first`,
which is pre-existing, belongs to unrelated in-flight work, and must not be
fixed.

### G · The plan contradicts itself on `ask_calculate`, and D15 wins

§9's C2 proof list ends by asking for *"an `ask_calculate` whose total is
computed in Python from confirmed quantities... and the code's figure is the
one used"*. **D15 says the opposite**, with a date and an attribution: the
owner changed it on 2026-09-07 so that the assistant always asks and whatever
the person replies is written verbatim, `source: "user"`, `computed_by: null`.
§10 question 1 confirms it. §9's own C2 paragraph agrees with D15 two
sentences earlier — *"`ask`/`ask_calculate` are never auto-accepted"* — and
then contradicts itself.

**D15 is right and §9's last bullet is the first draft left behind**, exactly
as §9's A1 line was left behind on `path` (amendment B). C2 followed D15. The
proof case was replaced rather than dropped: the model returns confidently
wrong arithmetic with a citation that really resolves, and the assertions are
that it becomes a question and that no figure it produced reaches the record.

### H · A rate card is OPTIONAL — D16 is superseded, and its console half is retired

The owner reopened §10 question 3 on 2026-09-08 and the answer changed:
**a rate card is optional when the document carries its own prices.**
`proposals.pricing_table_id` and `pricing_version` are nullable;
`scripts/migrations/2026-09-08_optional_rate_card.py` migrates a database that
already exists. Recorded as **D37** in `Dashboard/READMEs/05_DECISIONS.md`.

D16 rests on an estimate — *"the most expensive change this project has"* —
that was never measured. Measured: six proposals in the development database,
`total_amount` already defaulting to `0.0`, one aggregate that sums fine with
it, and an Android app already null-safe on all three fields. **The estimate,
not the constraint, is what kept the worse design.**

So the item in amendment E below — D16's console half, the check at upload
time — **is retired, not outstanding.** There is no late failure left to warn
anybody about. If the console should still *mention* a missing rate card at
upload, that is now a courtesy and a fresh decision, not this plan's debt.

Two smaller corrections while we are here. §0's amendment E says *"§6 says the
console should check at upload time"*; §6's five numbered items say nothing
about a rate card — the requirement lives in D16's prose alone, which is
probably how it came to belong to no task. And §9's E2 line says handover §6a
applies to two of its three documents; measured, both console READMEs are
clean and it applies only to `BACKEND_README.md`.

### I · §2.6 was right about the question card and silent about the other one

*"The Android app needs no changes for the question-and-answer loop"* is true,
and E1 checked it against the code rather than the plan: the question body has
no `maxLines` and no `ellipsize`, and the candidate chips wrap.

But the app needed **two** changes to the *provenance* card, which §2.6 never
covered because the simple flow's `source` values did not exist when it was
written. `renderFilled` gated the whole "What went into this proposal" card on
`templateKind == "docx"`, so a `docx_simple` proposal showed **no card at
all**; and `sourceLabel` fell `"user"` and `"default"` through to "From your
records", telling a salesperson that a figure they had typed themselves came
out of the database. Both fixed, and the decisions moved into a testable class
because the app's JVM suite has no Robolectric and could not reach them.

---

## 1 · What is being added

The feature shipped in Tasks 1–23 is now called the **complex flow**: an
administrator uploads a `.docx`, an LLM proposes placeholders, and a human
accepts, rewords, moves or adds each one in a console editor before saving a
fill plan. It is precise and it is a lot of work per template.

The **simple flow** moves that work to the person who *designs the document*.
The template author writes the placeholders directly into the Word file as
angle-bracket tags — `<School Name>`, `<ask:1 Unit>` — and the administrator
does nothing but upload the file. No editor, no suggestions to accept, no plan
to save. Upload, a progress indicator, done.

The intelligence moves to proposal time. When a salesperson asks Jarvis to
create a proposal, the model is given the whole picture — the client, their
contacts, the notes and meetings, the programme, the rate card, and the full
text of the template with every tag in place — and it works out what each tag
means and what belongs in it. Where it is confident it fills silently; where it
is not, it asks the salesperson in the chat, in plain language, and the answer
completes the document.

**Both flows exist side by side.** A template carries which one it belongs to,
and nothing about the markdown path or the complex path changes.

---

## 2 · What was measured

Nothing in this section is inferred. Each line names how it was obtained.

### 2.1 · The owner's hand-tagged document

`Innovation Lab Template.docx`, tagged by the owner on 2026-09-07
(sha256 `595cda9f1b93b2dc`, 4,018,636 bytes — the original was
`2fd0cd002e82ed08`). Scanned at `w:t` level through `docx_text`, over
`all_roots`, so headers, footers and text boxes were included.

> **`School_YuviPep 360_2 1.docx` carries no tags.** It is byte-identical to
> the 3 September original (`152e991e7af64c4a`, modified 2026-09-03 10:39).
> The owner believed the tags were in that file; they are in the Innovation Lab
> template. Anything that needs a second tagged fixture must have one made.

**20 distinct tags, 25 occurrences**, in three families:

| Family | Distinct | Occurrences | Examples |
|---|---|---|---|
| Plain semantic | 6 | 6 | `<School Name>`, `<Name>`, `<Ph no. yuvipep>`, `<email yuvip>`, `<website yuv>`, `<Address yuvipep>` |
| `<ask:…>` | 12 | 18 | `<ask:1 Unit>`, `<ask:4 Units>`, `<ask: (10 units)>`, `<ask:(50 Nos)>`, `<ask:1 3D Printer with filaments>`, `<ask:1>` |
| `<ask_calculate:…>` | 1 | 1 | `<ask_calculate:Rs. 15,00,000/- to Rs. 25,00,000/-net (including GST)>` |

**`<ask_calculate:` is not in the owner's brief.** It was found in the file. §3
proposes semantics for it, and the owner settled them on 2026-09-07 — the
assistant always asks and writes the reply verbatim (D15, §10 answer 1).

### 2.2 · Where the tags actually are — the finding that shapes the design

| Fact | Measured |
|---|---|
| Occurrences in body paragraphs | **6** |
| Occurrences in **table cells** | **19** |
| Most tags in a single paragraph | **4** (`table[0] row[9] col[1]`) |
| Paragraphs carrying at least one tag | 21 |
| Occurrences in headers or footers | **0** (two independent walks agreed) |

Three consequences, each of which rules out an obvious implementation:

1. **`docx_text.replace_token` cannot be used.** It replaces a literal
   everywhere in the document. `<ask:1 Unit>` occurs **four times** — in
   `table[0]` rows 19, 20, 21 and 23 — and they are four different questions
   about four different items. `<ask:(3 Nos)>` occurs in `row[9] col[0]` *and*
   `row[9] col[1]`, again meaning different things.
2. **A cell can hold several tags.** `row[9] col[1]` reads
   *"CRO, Safety Glass `<ask: (10 units)>`, Drill Machine, Soldering Station …"*
   and contains four. So a replacement must address a character range, not a
   cell.
3. **The outline does not see 19 of the 25.** `outline.parse` records a table
   as one block whose `text` is only its header row, and never descends into
   cells. The block model the complex flow uses is blind to most of the tags.

### 2.3 · The mechanism that does work — proved, not assumed

`outline.resolve` already walks `body[i]/tr[j]/tc[k]/p[m]`, and
`text.replace_span(p, start, end, replacement)` already replaces a character
range inside one paragraph, inheriting that run's formatting.

A probe addressed each of the 25 occurrences as
**(paragraph, char start, char end)** in `node_text` space and replaced them
right-to-left within each paragraph. Result, after `save()` and a fresh re-open:

```
occurrences found by path walk: 25
paragraphs carrying tags     : 21
max tags in one paragraph    : 4
after save+reopen:
  tags left behind : 0
  markers landed   : 25 of 25
  landed in the WRONG paragraph: 0
  bytes: 4018636 -> 3944974
```

Right-to-left ordering is not a preference: replacing left-to-right invalidates
every later offset in the same paragraph.

> This first probe reached the paragraphs by positional path, which is enough
> for the owner's document — all 25 of its tags are in body paragraphs and
> first-level table cells. **§2.3a shows that is not enough in general**, and
> the plan uses the walk ordinal instead. The replacement mechanism proved here
> is unchanged either way: it is `replace_span` on a paragraph element, and only
> the way that element is found differs.

### 2.3a · Where a tag can live — and which addressing scheme reaches it

The first draft addressed a tag by the positional path `outline.resolve`
accepts. A document was then built with a tag in every awkward place Word
allows, and scanned two ways: by that **path**, and by the **ordinal of the
paragraph in `iter_paragraphs(all_roots(doc))`** — the same walk `docx_text`
uses for everything else.

| A tag in… | WALK ordinal | positional PATH |
|---|---|---|
| an ordinary body paragraph | ✅ | ✅ |
| a table cell | ✅ | ✅ |
| **a nested table inside a cell** | ✅ | ❌ **missed** |
| three runs of one paragraph | ✅ | ✅ |
| **a text box** | ✅ | ❌ **missed** |
| a header | ✅ | ✅ |
| a footer | ✅ | ✅ |
| | **7 of 7** | **5 of 7** |

Writing was then proved through the walk scheme on the same document: all seven
replaced, **0 landed in the wrong paragraph, 0 tags left, paragraph count stable
at 14**.

**So the plan addresses a tag by walk ordinal, not by path** (D1, D2). Nested
tables and text boxes are not exotic — the four real documents already use text
boxes, which is exactly why `Paragraph.runs` was banned in D27 of the complex
flow. An addressing scheme that cannot see them would have failed on a real
branded template, silently, by simply not offering the tag.

The path is still computed **when it can be** and kept as a human-readable
label, because `body[71]/tr[19]/tc[1]/p[0]` is what a person can check by eye;
it is never what the writer uses.

### 2.4 · Cost of processing an upload

| Document | parse | index detect | **OCR** | without OCR |
|---|---|---|---|---|
| Innovation Lab Template.docx (3.8 MB) | 0.02 s | 0.02 s | **2.33 s** | **0.04 s** |
| School_YuviPep 360_2 1.docx (14.1 MB) | 0.10 s | 0.10 s | **9.84 s** | **0.20 s** |

**OCR is 97–98% of the whole cost.** A tag cannot live inside a raster image,
so the simple flow does not need OCR to find its placeholders — only to enrich
what the model later knows about the document. Deferring it turns a 10-second
upload into a 0.2-second one.

### 2.5 · How much text the model must be given

| Document | blocks | tables | projected chars | ≈ tokens |
|---|---|---|---|---|
| Essential Lab.docx | 105 | 3 | 3,811 | 950 |
| Innovation Lab Template.docx | 147 | 2 | 2,986 | 750 |
| School_YuviPep 360 EmpowerED…docx | 222 | 14 | 20,048 | 5,000 |
| School_YuviPep 360_2 1.docx | 188 | 18 | 22,390 | 5,600 |

**No RAG, no vector store, no chunking is needed for the document itself.** The
largest real template is under 6,000 tokens. Building a retrieval layer over
5,600 tokens would add failure modes and hide context, which is the opposite of
what was asked for. Retrieval belongs — if anywhere — to the *client history*,
which is unbounded; see D7.

### 2.6 · What already exists and can be reused

| Need | Already there | Where |
|---|---|---|
| Chat thread that survives app restarts | `session_id`, persisted per device | `AssistantSession.sessionId()` |
| Conversation replay | `GET /assistant/history` | `app/api/assistant.py` |
| The assistant asking a question | `NeedsConfirmationError(message, candidates)` → `actions[].outcome == "needs_confirmation"` | `app/core/exceptions.py`, `agents/base.py` |
| The app rendering that question with one-tap answers | `questionCard()`, `ChatItem.Kind.QUESTION` | `AssistantFragment.java` |
| Addressing a paragraph inside a table cell | `outline.resolve` | `docx/outline.py` |
| Replacing a character range in place | `text.replace_span` | `docx/text.py` |
| Keeping model prose honest | `fill_scrub.scrub` | `app/services/fill_scrub.py` |
| A client dossier | `_client_details` — contacts, notes, proposals, open items | `agents/query_agent.py` |
| Background work | `queue.register(job_type, handler)`; `jobs.type` is `String(100)` | `app/jobs/queue.py` |

**The Android app needs no changes for the question-and-answer loop.** It
already renders any tool that raises `NeedsConfirmationError` as a question card
with tappable candidates, and the conversation already persists.

### 2.7 · Two limits that constrain the design

**Conversation memory cannot hold the fill state.** `app/ai/conversation.py`
replays **12 turns** capped at a **6,000-character budget**, prunes to
**60 rows**, stores **plain text only**, and never replays tool calls, tool
results or entity ids. A fill with 25 tags and a dozen clarifications would be
pruned away mid-job. **The state must be its own durable row**; the transcript
is a record of what was said, not the working memory.

**Schema changes are not equal.** `create_all` creates a missing *table* at
startup but **never adds a column**, and this project has no Alembic — three
columns had to be added by hand on 4 September, and every other environment on
the branch still needs them. Therefore:

* a **new table** is free;
* a **new column** is a manual migration everywhere;
* a **new value in an existing column** is free — `ProposalTemplate.kind` is
  `String(20)`, and `"docx_simple"` is 11 characters.

The design below adds **one table and no columns**.

---

## 3 · The tag grammar

Written to match what the owner actually typed, including its inconsistencies.

```
tag        := "<" body ">"
body       := ask_body | calc_body | semantic_body
ask_body   := "ask"           ws* ":" ws* default
calc_body  := "ask_calculate" ws* ":" ws* default
default    := any text, 1..150 chars, no "<" or ">" or newline
semantic_body := any text, 1..150 chars, no "<" or ">" or newline
```

* **Case-insensitive** on `ask` / `ask_calculate`.
* **Whitespace tolerant** around the colon: the file contains both `<ask:1 Unit>`
  and `<ask: (10 units)>`.
* **The default is free text, kept verbatim**, brackets and all: `(3 Nos)`,
  `1 3D Printer with filaments`, `Rs. 15,00,000/- to Rs. 25,00,000/-net
  (including GST)`. It is a *proposal to the human*, never silently accepted.
* **A tag never spans a paragraph.** The scan is per paragraph, over
  `node_text`, so a tag fragmented across runs is found (Word fragments runs
  arbitrarily and the owner's file already does this).
* **150 characters** is the cap. The longest real tag is 69.

**Not a tag**, and each exclusion has a reason:

| Rejected | Why |
|---|---|
| `<` or `>` inside the body | nesting is ambiguous and no real tag needs it |
| a newline inside the body | it would be a paragraph break, not a placeholder |
| empty body `<>` | nothing to act on |
| body longer than 150 chars | a stray `<` in prose must not swallow a page |
| a leading or trailing slash: `</b>`, `<p/>` | unambiguous markup, and never a sensible placeholder name |
| ~~anything matching `</?[a-z][a-z0-9]*\s*/?>`~~ | **OVERRIDDEN — see §0 amendment A.** A bare word like `<price>` IS a tag. |

**Three kinds, and the behaviour that follows:**

| Kind | Written | Confidence rule | Default |
|---|---|---|---|
| `semantic` | `<School Name>` | fill silently at ≥ 0.80, otherwise ask | none |
| `ask` | `<ask:4 Units>` | **always ask** — the threshold does not apply | `4 Units` |
| `ask_calculate` | `<ask_calculate:Rs. 15…>` | **always ask**, and the model must propose a figure with its reasoning | `Rs. 15,00,000/- …` |

---

## 4 · Design decisions

**D1 · Identity is per occurrence, never per literal.**
Each occurrence gets `tag_id = sha1(f"{walk_ordinal}#{nth_in_paragraph}")[:12]`,
where `walk_ordinal` is the paragraph's position in
`iter_paragraphs(all_roots(doc))` and `nth_in_paragraph` is the tag's index
among the tags of that paragraph. `<ask:1 Unit>` in four cells is four ids and
four answers. Measured necessity: §2.2.

**D2 · A tag is addressed as (walk ordinal, start, end) and written with
`replace_span`, right-to-left within a paragraph.**

The walk is `[p for root in all_roots(doc) for p in iter_paragraphs(root)]` —
`docx_text`'s own, so anything the rest of this codebase can read, this can
write. **Not the positional path**: it cannot reach a nested table or a text box
(§2.3a, 5 of 7), and `replace_span` takes the element directly, so `resolve` is
not needed at all.

The ordinal is stable because **the source document is immutable** (D3): the
same bytes always produce the same walk. The `(start, end)` offsets are captured
at scan time and **re-verified against the live text immediately before
writing** — if `raw` is no longer at `[start, end)`, the write is refused rather
than made in the wrong place. Right-to-left ordering is not a preference:
replacing left-to-right invalidates every later offset in the same paragraph.

Proved on the owner's real document (§2.3, 25/25) and on a synthetic one
covering every awkward position (§2.3a, 7/7).

**D3 · The source document is never rewritten.** Same rule as the complex flow.
Generation is `source.docx + occurrence map + values -> a new file`.

**D4 · The 80% threshold applies to `semantic` tags only.** `ask` and
`ask_calculate` always ask — that is what the author asked for by writing them.

`FILL_CONFIDENCE_THRESHOLD = 0.80` is **a module constant, not an organisation
setting** (owner's decision, 2026-09-07): one place to change, no per-org
surface to build, and it can become a setting later without touching any caller.
Remember that this number is **self-reported by the model and uncalibrated** —
D13's review, not this threshold, is what actually protects the client.

**D5 · Questions are grouped, not fired one at a time.** The Innovation Lab
template alone would generate **19 forced questions**. Nineteen round trips is
not a conversation, it is an interrogation. The assistant asks in **rounds**:
one message carrying up to `QUESTIONS_PER_ROUND = 6` related questions, each
with its default offered as a tappable candidate, plus an "all defaults are
fine" answer that settles the whole round. A round is answered in natural
language and the model maps the answer back onto the questions it asked.

*A departure from the literal brief, put to the owner and **accepted on
2026-09-07**, six per round.* On the Innovation Lab template that is four rounds
instead of nineteen.

**D6 · The fill state is a row, not the chat transcript.** §2.7 measured why.
A new table `proposal_fill_sessions` holds the occurrence map, every resolved
value with its source and confidence, the open questions, and the clarification
transcript. The chat transcript stays what it is: a record of what was said.

**D7 · The model gets the whole document and the whole client.**

**Measured, on the busiest real client in the database** (Meridian Data
Centres): a genuinely complete dossier is **263 rows and 47,525 characters of
text — about 11,900 tokens**. With the document (≤ 5,600) and the instructions
(~1,000) the first pass is **≈ 18,500 tokens** against a one-million-token
window. There is no size reason to summarise, sample or cap anything, so this
plan does not. The first draft of this decision capped meetings at 5 and notes
at 10; that was solving a problem that does not exist, and it would have hidden
from the model exactly the sentences it needs.

**Everything below goes in whole**, assembled once per fill session, stored on
the row, and replayed verbatim on every later turn — so the answer to turn 7 is
grounded in the same facts as turn 1.

| Part | Source |
|---|---|
| Client, state, city, importance, and its state history | `leads`, `lead_state_history` |
| **Every** contact, with title, email, phone | `contacts` |
| **Every** note | `client_intelligence` |
| **Every** meeting, and its **full transcript** | `meetings`, `transcripts` |
| The project, its plans, commitments, stakeholders, deliverables, invoices | `projects`, `action_plans`, `client_commitments`, `stakeholders`, `deliverables`, `invoices` |
| **Every** action item, follow-up and demo | `action_items`, `followups`, `demos` |
| Past proposals and their revisions | `proposals`, `proposal_revisions` |
| What has actually been said to this client | `threads`, `outbound_messages` |
| Consent, and the long-term memory chunks | `consent_records`, `memory_chunks` |
| Programme, its description, and the current rate card | `programs`, `pricing_tables` |
| Sender and organisation | `users`, `organisations` |
| The template's full projected text, and the text read out of its images | outline projection, `ocr_json` |

On the measured client the transcripts alone are **12,063 characters** — the
single richest source, and precisely where *"the programme runs 28 September to
2 October"* would have been said. Capping them would have defeated the feature.

**Two tables are excluded deliberately, on quality grounds rather than size.**

| Excluded | Chars | Why |
|---|---|---|
| `ai_decisions` | 10,199 | The engine's own past reasoning. Feeding a model its earlier guesses invites it to treat them as established fact. |
| `progress_events` | 5,371 | State-machine bookkeeping. Volume without meaning for this task. |

Together they are 15,570 of the 47,525 characters, so removing them makes the
dossier **better and smaller at once**.

**A safety valve, not a budget.** `DOSSIER_CHAR_CEILING = 60_000` (≈ 15k
tokens), about 25% above the busiest client today. A client with fifty meetings
will exceed it eventually. Over the ceiling, drop **oldest-first within the
largest section only**, and **state in the prompt what was dropped and how
much** — a model told "the 12 oldest notes were omitted" can ask; a model handed
a silently truncated dossier cannot. Nothing is ever truncated mid-record.

**Retrieval is still not needed and is still not built.** It would become worth
considering only for a client far past the ceiling, and even then it applies to
notes, messages and transcripts — never to the document, which is small and
whose every line may carry a tag.

**D8 · Duplicates are resolved together, then recorded separately.** All
occurrences of the same literal are presented to the model in one group with
each one's surrounding sentence and, for a table cell, its row label. The model
answers per occurrence and may reuse one value across several. Every occurrence
still stores its own value, so a later correction touches one cell.

**D9 · A row label is the disambiguating context for a tag in a table.** For
`table[0] row[19] col[1]` the question context is `row[19] col[0]` — the item
name. Measured: that is exactly what separates the four `<ask:1 Unit>`.

**D10 · Numbers keep their fence, with one deliberate widening.** The existing
constraint is that line items and totals come from the locked `PricingTable`.
That still holds for the rate-card table. An `ask_calculate` value is a figure
the model *proposes* and a **human confirms in the chat** before it is written —
so it enters as human-supplied, not model-invented, and is recorded as such in
the fill record. `fill_scrub` still runs on every `semantic` value.

**D11 · A new value on `kind`, not a new column.** `"docx_simple"` joins
`"markdown"` and `"docx"`. `Proposal.template_kind` records the same. No ALTER
on any environment.

**D12 · Upload is synchronous; OCR is not.** Parse + tag scan is 0.2 s (§2.4),
so the upload returns a finished template. OCR is queued as a background job
that enriches `ocr_json` for later context; the template is usable before it
finishes, and if it never runs, nothing breaks.

**D13 · Nothing is written into a document until a human has seen every value.**

Before the document is produced, the assistant shows **one** compact list of
every tag and the value about to go into it — **including the ones filled
silently at high confidence** — and the salesperson can correct any line in a
single natural-language message.

This exists because **the 0.80 threshold in D4 is self-reported and
uncalibrated**. A model that is confidently wrong about `<Name>` would otherwise
reach the client unchallenged, and no amount of prompt wording fixes that.
Confidence decides whether the assistant *asks a question*; this review decides
whether the document is *written*. They are different jobs and the first draft
conflated them.

One message, not one per tag: the lines are grouped by kind, and each shows the
tag, its context, the value, and where the value came from. A correction
re-opens the fill and the review runs again on the result.

**D14 · A semantic fill must cite the fact it came from.**

`resolve_tags` returns `citation` beside `value` and `confidence`: the specific
dossier fact used — `"contacts[2]: Sunil Menon, Principal"`, `"transcript of the
14 Aug meeting"`. **A resolution carrying no citation, or naming a fact that is
not in the dossier, is downgraded to a question whatever confidence it claims.**

This is the same discipline `docx_suggest._validate` already applies to anchors:
check the model's answer against the data it was given rather than trusting it.
It turns a hallucination into something the system detects, instead of something
the reviewer in D13 has to notice by eye. A `system` value cites the field it
came from; a `user` value cites the turn in which the person said it.

**D15 · The model supplies the inputs; the arithmetic is done in code.**

A language model is unreliable at multi-step arithmetic, and this project has
refused to let one near a total since the first proposal shipped. That rule
extends to the simple flow unchanged.

This holds absolutely for the **rate-card line items and their totals**, which
come from the locked `PricingTable` through `compute_totals` and never from the
model — unchanged from the day the first proposal shipped.

**For `<ask_calculate:…>` the owner chose something simpler and stricter
(2026-09-07): the assistant always asks, and whatever the person replies is what
gets written.** The model reasons as far as it can — over the rate card, the
transcripts and the notes — states the conclusion it reached in plain language,
and asks. It never writes its own figure. The reply is filled **verbatim**, so a
person who answers *"18,00,000 all inclusive"* gets exactly that, and one who
answers *"quote the range"* gets the range.

The default inside the tag is **context for the question, not a rule**:
`Rs. 15,00,000/- to Rs. 25,00,000/-net (including GST)` tells the model and the
reader what the author had in mind. Nothing validates the answer against it, and
nothing silently substitutes it.

So the record for such a tag is always `source: "user"`, `computed_by: null`,
and a `citation` naming the turn in which the person said it. **No number
reaches a document unless Python computed it from the locked rate card, or a
person typed it.** There is no third way in.

Where a value is genuinely not arithmetic — *"which fortnight in September
avoids the exam block"* — the model reasons over the transcripts and its answer
goes through the ordinary question-and-review path like any other.

**D16 · A simple-flow offering still needs a rate card row — and the console
asks for it at upload, not at proposal time.**

The owner's preference (2026-09-07) was that an offering whose prices live
inside the document should not need a rate card at all. **Measured, that costs a
column migration**: `proposals.pricing_table_id` and `proposals.pricing_version`
are `NOT NULL` in the model *and* in the live database, and SQLite cannot drop a
`NOT NULL` without rebuilding the table — on every environment, with no Alembic
(§2.7). That is the most expensive change this project has, for a field the
simple flow simply does not read.

**So the requirement stays and the pain is moved instead.** Today the failure is
late and confusing: a salesperson asks for a proposal and gets *"No pricing
table for this program. Ask your Org Admin to add one."* Under this plan the
console checks at **upload** time, and if the offering has no current rate card
it says so there and offers to publish one in the same step. The administrator
may publish a minimal one — the prices the client sees come from the document's
own tags either way.

**The backend invents nothing.** An auto-created placeholder rate card would
make checklist item 5 read satisfied when no human had entered a price, and this
console's founding rule is that it never shows a status it cannot verify. A
human publishes it, or it does not exist.

> **If the owner would rather have the real thing** — proposals with no pricing
> link at all — the change is: make both columns nullable, rebuild the
> `proposals` table on every environment, and audit every reader that assumes a
> pricing version exists. Say so and it becomes its own task; it is not folded
> in here because nothing else in this plan needs it.

---

## 5 · Data model

**One new table. No new columns. No migration.**

```python
class ProposalFillSession(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One in-progress fill of one simple-flow template for one client.

    Not the chat transcript: conversation.py replays 12 turns inside a
    6,000-character budget and prunes at 60 rows, so a 25-tag fill with a
    dozen clarifications would lose its own working memory. This row is the
    memory; the transcript is the record.
    """
    __tablename__ = "proposal_fill_sessions"

    lead_id:        Mapped[str]          # ForeignKey leads.id
    program_id:     Mapped[str]
    template_id:    Mapped[str]
    template_doc_id: Mapped[str]
    proposal_id:    Mapped[str | None]   # set once the document is produced
    user_id:        Mapped[str]          # whose conversation this is
    chat_session_id: Mapped[str | None]  # the assistant session_id it belongs to

    status:  Mapped[str]                 # gathering | asking | reviewing | ready
                                         # | built | abandoned
    dossier_json: Mapped[dict]           # D7, assembled once, replayed verbatim
    tags_json:    Mapped[list[dict]]     # the occurrence map + resolutions
    asked_json:   Mapped[list[dict]]     # every question asked and its answer
```

One occurrence inside `tags_json`:

```jsonc
{
  "tag_id": "9f2c1a77b004",
  "kind": "ask",                     // semantic | ask | ask_calculate
  "raw": "<ask:1 Unit>",
  "default": "1 Unit",               // ask/ask_calculate only
  "ordinal": 143,                    // position in the paragraph walk (D2)
  "label": "body[71]/tr[19]/tc[1]/p[0]",  // for humans; null in a text box
  "start": 0, "end": 12,             // re-verified before writing (D2)
  "context": "Interactive Panel",    // the row label, or the sentence (D9)
  "duplicate_of": null,              // first occurrence of the same literal
  "value": "2 Units",
  "source": "user",                  // system | ai | user | default
  "confidence": 1.0,
  "citation": "turn 4: \"make it two panels\"",   // D14 - required for ai/system
  "computed_by": null,               // D15 - "python" when arithmetic produced it
  "reason": "Siva confirmed two panels in the chat on 7 Sep",
  "reviewed": true                   // D13 - a human saw this exact value
}
```

`status` transitions: `gathering` → (`asking` ⇄ `gathering`) → **`reviewing`**
→ `ready` → `built`, and a correction made during review returns it to
`gathering`. Nothing is written into a document until `ready`, and `ready` is
reachable only through `reviewing` (D13).

**Where the occurrence map is stored for the template itself**: in the existing
`proposal_template_docs.plan_json`, as `{"flow": "simple", "version": 1,
"tags": [...]}`. The complex flow's plan uses `{"version": 1, "entries": [...]}`,
so the two are distinguishable and `fill.validate_plan` is never handed a simple
plan by accident.

---

## 6 · The upload flow (console)

1. Item 6 gains a third option on **How this version is written**:
   *Word document — tags filled by the assistant* **(default)**, *Word document
   — placeholders marked here* (today's complex flow), *Markdown body*.
   The simple flow is the default the owner asked for; the existing default
   moves to second place.
2. `POST /admin/programs/{id}/proposal-templates/docx` gains `flow=simple|complex`
   (a form field, defaulting to `simple`).
3. On `simple` the backend parses, scans for tags, stores the occurrence map,
   sets `kind="docx_simple"`, and returns a summary: how many tags, how many
   will always be asked, and the distinct literals found.
4. The console shows a determinate-looking staged progress indicator — *reading
   the document → finding the tags → saving* — and then a success panel listing
   what was found. **No editor, no next step.**
5. **A document with zero tags is refused**, naming the fact plainly: a
   simple-flow template with no tags produces the same document for every
   client. The message offers the complex flow instead.

---

## 7 · The fill conversation (Jarvis)

The salesperson says *"create a proposal for Orchid International School for
IBC"*. The Proposal Agent's `create_proposal` sees the current template is
`docx_simple` and takes this path instead of building immediately.

**Turn 1 — open the fill session.**
Assemble the dossier (D7) and the occurrence map, store a
`ProposalFillSession`, then make **one** model call carrying: the system
contract, the dossier, the full template text with each tag marked by its
`tag_id`, and the occurrence list with contexts. The model returns, per
occurrence, `value`, `confidence` and `reason`.

**Turn 1 result.** Every `semantic` tag at ≥ 0.80 is filled and recorded with
`source: "ai"`. Everything else — the low-confidence ones and every `ask` /
`ask_calculate` — becomes an open question. The agent raises
`NeedsConfirmationError` with the first round of questions and their defaults
as `candidates`, which the app already renders as a question card.

**Turns 2..n — clarify.** Each reply routes back to the Proposal Agent, which
loads the fill session by id, appends the answer, and makes one model call
carrying the dossier, the *outstanding* questions and the answer — not the whole
document again. Answers may settle several questions at once. Anything still
ambiguous is asked again, in the model's own words.

**The review turn — everything, before anything is written.** When no question
is left open, `status` becomes `reviewing` and the assistant posts one message
listing every tag with the value about to be written and where it came from —
the silently-filled ones included (D13). *"All correct"* proceeds; anything else
is read as a correction, applied, and the review is posted again. A value the
model filled without a citation never reaches this list as filled: D14 already
turned it into a question.

**Final turn — build.** When the review is accepted, `status` becomes `ready`, the
occurrence map plus values are applied to a copy of the source document
(right-to-left per paragraph), the index is refreshed if the document has a
static contents page, the PDF is produced by LibreOffice, and the `Proposal`
row is written exactly as the complex flow writes one — including `filled_json`,
so the Android "What went into this proposal" card works unchanged, showing
which values came from records, which the AI wrote and which the salesperson
supplied.

**Resuming.** A fill session is found by `chat_session_id` + `lead` + `program`,
so *"actually make it 3 units"* an hour later still lands on the right fill. A
session untouched for `FILL_SESSION_TTL_DAYS = 7` is **abandoned**: it is never
resumed silently, and a later request starts a fresh fill rather than reviving
week-old half-answers the salesperson has forgotten giving.

---

## 8 · Prompt and token strategy

* **First pass** ≈ document (≤ 5.6k) + dossier (≈ 11.9k measured, 15k ceiling)
  + instructions (≤ 1k) ≈ **18.5k tokens**, once per proposal.
* **Each clarification** ≈ the same dossier + the open questions + the answer ≈
  **13–16k tokens**. The dossier is re-sent whole rather than distilled: the
  requirement was explicitly that the model must not lose context or get
  confused mid-fill, and the owner accepted a higher token bill to get that. At
  three or four rounds a fill costs roughly 60–75k tokens in total, which on the
  strong tier is small against the cost of a wrong proposal reaching a client.
* The strong tier (`gemini-2.5-flash`) is used for the fill pass; routing stays
  on the fast tier.
* The document is **not** re-sent on clarification turns — the occurrence map
  and the dossier carry everything the model needs, and re-sending 6k tokens per
  answer is what would actually make this expensive.
* Every call goes through the existing budget guard, so an organisation that has
  spent its month refuses the fill rather than silently degrading.

---

## 9 · The tasks

Each task states its files, what it produces, and what proves it. The order is
dependency order; every task ends green.

### Phase A — the engine (no AI, no UI)

**A1 · The tag grammar and scanner.**
Create `app/services/docx/tags.py`: `TAG_RE`, `parse_tag(body) -> (kind, default)`,
and `scan(docx_bytes) -> list[Occurrence]` returning per-occurrence
`{tag_id, kind, raw, default, ordinal, start, end, context, duplicate_of}`
(**`ordinal`, not `path` — see §0 amendment B**).
Create `tests/docx/test_tags.py`.
**Proves it:** the owner's real file yields **25 occurrences, 20 distinct, 6 in
body paragraphs and 19 in table cells**, and `<ask:1 Unit>` yields **four**
distinct `tag_id`s. Plus synthetic fixtures for every rejection in §3, and a tag
fragmented across three runs.

**A2 · The paragraph walk, and the label that goes with it.**
Add `walk_paragraphs(doc) -> list[element]` to `app/services/docx/text.py` —
`[p for root in all_roots(doc) for p in iter_paragraphs(root)]`, the walk this
module already uses — and `label_for(doc, ordinal) -> str | None`, a
best-effort human-readable `body[i]/tr[j]/tc[k]/p[m]` for display only,
returning `None` for a paragraph inside a nested table or a text box.
**Proves it:** on a document with a tag in a body paragraph, a table cell, a
nested table, a text box, a header and a footer, the walk reaches **all seven**
where the positional path reaches five (§2.3a); the walk order is identical
across two independent reads of the same bytes; and `label_for` never invents a
path that does not resolve.
*This task shrank when §2.3a was measured: the walk already exists in
`docx_text`, so almost nothing has to be built.*

**A3 · The occurrence-addressed writer.**
Create `app/services/docx/tagfill.py`:
`apply_tags(docx_bytes, occurrences, values) -> {"docx": bytes, "written": [...], "skipped": [...]}`.
Right-to-left within each paragraph; **re-read the live text and refuse the
write if `raw` is no longer at `[start, end)`**; refresh a static index
afterwards exactly as `fill.apply` does.
**Proves it:** the §2.3 result reproduced as a test — 25 written, 0 tags left,
every marker in its own paragraph — plus a stale-offset case that is skipped
rather than written wrongly.

**A4 · The fill-session table.**
Create `app/models/proposal_fill.py` per §5; export it from
`app/models/__init__.py`; add `proposal_fill_sessions` to `WIPE` in
`app/core/reset_taxonomy.py` (it is transactional work, not catalogue) and
update the partition test.
⚠ **`app/models/__init__.py`, `app/core/reset_taxonomy.py` and
`tests/test_reset_taxonomy.py` are all on the 89-path dirty list — handover
§6a applies, and the committed count must be measured at HEAD, not in the
working tree.** At the time of writing the committed assertion is
`(4, 2, 8, 42)` with 56 tables; measure, do not assume.
**Proves it:** the partition test, and `create_all` making the table on a fresh
database.

### Phase B — the upload

**B1 · `flow` on the upload route.**
`POST /admin/programs/{id}/proposal-templates/docx` gains `flow: str = Form("simple")`.
`docx_template_service.create_docx_template` branches: `simple` scans tags,
writes `plan_json = {"flow": "simple", "version": 1, "tags": [...]}` and
`kind="docx_simple"`; `complex` behaves exactly as today.
**Refuse a zero-tag document** in the simple flow with a message that names the
consequence and offers the other flow.
**Proves it:** upload of the owner's file creates a `docx_simple` template with
25 occurrences; upload of `Essential Lab.docx` (0 tags) is refused 422; a
`complex` upload is byte-identical in behaviour to today.

**B2 · OCR moves to the background.**
Register a `docx_ocr` job type; the simple upload enqueues it and returns.
**Proves it:** upload latency for `School_YuviPep 360_2 1.docx` drops from
~10 s to under 1 s (measure both), and `ocr_json` is populated after the job
runs. A failed OCR job leaves a usable template.

**B3 · The console.**
`ProposalTemplates.tsx` third option, defaulting to simple; `DocxUpload.tsx`
gains the staged progress indicator and a success panel listing the tag counts;
no editor is offered for a simple template. Version history shows which flow a
version used.
**Proves it:** Vitest over the pure parts; `tsc --noEmit`; the conformance and
token guards stay green.

### Phase C — the intelligence

**C1 · The client dossier.**
Create `app/services/client_dossier.py`: `build(db, ctx, lead_id, program_id) -> dict`
carrying every source in D7 **whole**, excluding `ai_decisions` and
`progress_events`, with `DOSSIER_CHAR_CEILING` as a safety valve that drops
oldest-first within the largest section and records what it dropped.
**Proves it:** the measured client (Meridian Data Centres) produces every
section and lands near 47,525 characters minus the two exclusions; a client with
no meetings or notes still produces a valid dossier; a synthetic client pushed
past the ceiling drops oldest-first, never mid-record, and the prompt says what
was dropped.

**C2 · The fill model pass.**
Create `app/ai/docx_tagfill.py`:
`resolve_tags(ctx, *, dossier, document_text, occurrences) -> list[resolution]`
and `answer_round(ctx, *, dossier, open_questions, user_reply, asked) -> list[resolution]`.
Every returned `tag_id` is validated against the occurrence map and anything
unknown is dropped — the same discipline `docx_suggest._validate` applies.
`semantic` values pass through `fill_scrub`; `ask`/`ask_calculate` are never
auto-accepted whatever confidence comes back.
**Proves it:** a stubbed model layer covering — a confident semantic fill with a
valid citation, a 0.6 semantic that becomes a question, an `ask` at confidence
1.0 that *still* becomes a question, a hallucinated `tag_id` that is dropped,
one answer settling three duplicate occurrences, **a 0.95 fill with no citation
that is downgraded to a question (D14)**, **a 0.95 fill citing a fact absent
from the dossier, likewise downgraded**, and **an `ask_calculate` whose total is
computed in Python from confirmed quantities rather than taken from the model
(D15)** — including a case where the model returns arithmetic that is simply
wrong and the code's figure is the one used.

**C3 · The fill session service.**
Create `app/services/proposal_fill_service.py`: `open_session`, `find_open`,
`apply_answers`, `open_questions`, `mark_ready`, `abandon`.
**Proves it:** a session survives a reload; answers accumulate; resuming by
`chat_session_id` finds the right one; an abandoned session is never resumed.

### Phase J — Jarvis

**J1 · The agent branch.**
`ProposalAgent._create` detects `kind == "docx_simple"` and opens a fill session
instead of building. New tools: `answer_proposal_questions` and
`show_proposal_questions`. Questions are raised as `NeedsConfirmationError`
with defaults as `candidates`, in rounds of at most N (D5).
**Proves it:** an end-to-end test through `orchestrator.handle_command` with a
stubbed model: create → questions asked → answered → document built, all inside
one `session_id`.

**J2 · The review, then building at the end.**
When nothing is open, post the D13 review — every tag, its value and its origin,
in one message — and accept either an approval or a correction. Only then apply
the values, refresh the index, convert to PDF, and write the `Proposal` with
`template_kind="docx_simple"` and a `filled_json` whose `source` distinguishes
`system` / `ai` / `user` / `default` and whose `computed_by` marks the figures
Python produced.
**Proves it:** a fill cannot reach `ready` without passing through `reviewing`
(assert the transition, not just the outcome); a correction in review changes the
written document; and the Android contract test's fixture is regenerated from a
real run so the app's card is checked against the new source values too.

**J3 · The golden test.**
`tests/docx/test_simple_golden.py`, opt-in like the existing golden suite, over
the owner's tagged document: 25 occurrences found, all filled from a scripted
set of answers, 0 tags left in the output, media count unchanged, section count
unchanged, and the PDF converts.

### Phase E — closing

**E1 · Android check.** Confirm no change is needed (§2.6). If the question card
needs a longer body for a round of questions, that is the only change.
**E2 · Documentation.** `09_BACKEND_CHANGES.md` as a sixth unfreeze;
`05_DECISIONS.md` D31+ for the decisions in §4; `BACKEND_README.md` §8.3 and the
counts. Handover §6a applies to two of those files.

---

## 10 · The eight questions, and the answers

All eight were put to the owner on **2026-09-07** and answered the same day.
**Nothing in this plan is waiting on a decision.** Two answers did not survive
contact with the code exactly as given, and both are recorded with the reason
rather than quietly reinterpreted.

| # | The question, in short | The answer | Written into |
|---|---|---|---|
| 1 | What does an `ask_calculate` default mean? | **Changed by the owner.** The assistant always asks, and whatever the person replies is written **verbatim**. The default is context for the question, not a rule to validate against. | **D15** |
| 2 | One question at a time, or grouped? | Grouped, **6 per round**, with an "all defaults are fine" answer. Four rounds instead of nineteen on the real template. | **D5** |
| 3 | Must a simple-flow offering still have a rate card? | **Not achievable as asked.** `proposals.pricing_table_id` and `pricing_version` are `NOT NULL` in the model and the live database, and SQLite cannot drop that without rebuilding the table on every environment. The requirement stays; the console now asks for the rate card **at upload** instead of failing at proposal time. | **D16** |
| 4 | Is the document's own price table filled by tags only? | **Yes.** No column mapping in the simple flow — a table is filled by whatever tags sit in its cells, like any other text. | **D16**, §6 |
| 5 | Is 0.80 per-organisation configurable? | **No** — a module constant, changeable in one place, promotable to a setting later without touching a caller. | **D4** |
| 6 | A second tagged fixture? | The owner will tag `School_YuviPep 360_2 1.docx` (18 tables). **Outstanding — a fixture, not a decision.** | **J3** |
| 7 | Can the simple flow insert new paragraphs? | **No.** It only replaces tags. A new paragraph is requested by putting a tag where it should go. | §11 |
| 8 | How long may a half-answered fill sit? | **7 days** (`FILL_SESSION_TTL_DAYS`), then abandoned — never resumed silently. | **D6**, §7 |

**The only thing still outstanding is a test fixture (6), not a decision.**
Phases A, B, C and J1–J2 can all be built and finished without it; J3 needs it.

> **If the owner later wants question 3 done properly** — a proposal with no
> pricing link at all — that is: make both columns nullable, rebuild the
> `proposals` table on every environment, and audit every reader that assumes a
> pricing version exists. It is a task of its own and nothing else here depends
> on it.

---

## 11 · What this plan deliberately does not do

* **No vector store, no RAG, no chunking — for the document or the client.**
  The largest real template is 5,600 tokens (§2.5) and the busiest real client
  is 11,900 (D7). Both are sent whole. Retrieval would add failure modes and
  hide context from the model, which is the opposite of the requirement.
* **No new columns**, so no environment needs a manual migration (§2.7).
* **No change to the markdown path or the complex flow.** Both keep their code
  paths exactly.
* **No Android work** beyond a possible string, because the question card and
  the persisted conversation already exist (§2.6).
* **No new paragraphs.** The simple flow *only replaces tags*; it never inserts
  a paragraph the way the complex flow can (owner's decision, question 7). A
  template that wants a written paragraph puts a tag where it belongs, and the
  tag is filled like any other. This keeps the whole feature to one verb —
  replace — and it is why `replace_span` is the only writer it needs.
* **No auto-created rate card.** A placeholder published by the backend would
  make checklist item 5 read satisfied when no human had entered a price, and
  this console's founding rule is that it never shows a status it cannot verify
  (D16).
