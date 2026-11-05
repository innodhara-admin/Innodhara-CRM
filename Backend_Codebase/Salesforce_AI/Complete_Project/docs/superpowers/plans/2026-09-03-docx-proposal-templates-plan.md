# DOCX Proposal Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an administrator upload a real branded `.docx` as a proposal template, place AI-suggested placeholders in it through a dashboard editor, and have Jarvis fill those placeholders at proposal time without ever re-rendering the document.

**Architecture:** The uploaded `.docx` is stored once and never rewritten. A *fill plan* (JSON) addresses positions inside it. Generation is `source.docx + plan + values -> new file`: system-bound values come from the database, prose comes from one batched LLM call that returns plain text and is passed through a deterministic scrubber. PDF comes from LibreOffice headless. The existing Markdown template path is untouched and still the default.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy 2.0 async, python-docx 1.2.0 + raw lxml, pypdf, tesseract 4.1.1 (via `subprocess`), LibreOffice 7.3.7 headless, React 19 + TypeScript + Vite (console), Java 17 + Retrofit (Android).

**Spec:** `docs/superpowers/specs/2026-09-03-docx-proposal-templates-design.md`

## Global Constraints

- **Backend root:** `/home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project` on `telaverge@172.16.10.55`. Python is `.venv/bin/python`; run pytest as `.venv/bin/python -m pytest`.
- **Branch:** the tree is on `feature/pre-sales-cold-calling` at `aa49e80` with 60 modified and 29 untracked files of unrelated in-flight work. **Do not commit those.** Create `feature/docx-proposal-templates` off the current HEAD and `git add` only the paths each task names.
- **Backup exists** at `Backend_Codebase/backup_2026_09_03_docx_templates/` (tar.gz + git bundle + tracked diff + RESTORE.md). Verified 2026-09-03.
- **Never re-render a DOCX from text.** Every mutation edits a copy of the uploaded file in place.
- **Numbers never come from the AI.** Line items and totals come from the locked `PricingTable` version, exactly as `proposal_service.compute_totals` does today.
- **Text access goes through `docx_text`, never `Paragraph.runs`.** `.runs` omits runs nested in `w:hyperlink` and never descends into text boxes. Measured: it saw 4 of 7 occurrences in `Essential Lab.docx`, 1 of 7 in `Innovation Lab Template.docx`, 1 of 9 in `School_YuviPep 360_2 1.docx`, 2 of 14 in `School_YuviPep 360 EmpowerED_New_compressed.docx`.
- **Markdown path unchanged.** `template.kind == "markdown"` must take byte-identical code paths to today.
- **Sample documents** are on the VM at `data/samples/` (4 files, sha256 in Task 1). They are not in git.
- **Existing tests must stay green:** `.venv/bin/python -m pytest -q` before and after every task.


## Rulings applied during execution

Recorded 2026-09-03 while executing this plan. Each corrects a defect in the
plan's own text; each is already folded into the task it affects. The full
record, including deferred minor findings, is the SDD ledger at
`.superpowers/sdd/2026-09-03-docx-proposal-templates-plan/progress.md`.

| # | Ruling | Cost if wrong |
|---|---|---|
| R1 | Work on a branch in place, **not** a git worktree. A worktree checks out `aa49e80`, whose `main.py` and `models/__init__.py` do not reference the 29 untracked in-flight files the running tree needs, and whose test suite differs. | A stray commit picks up in-flight work — guarded by per-path `git add`, the final `comm` check, and the verified backup. |
| R2 | The SDD workspace lives on the VM; neither the local cwd nor the Android project is a git repo. | Artifacts in an unexpected but git-ignored place. |
| R3 | `reset_taxonomy` has **four** buckets and `proposal_template_docs` joins `REPLACE`; `test_bucket_sizes_are_the_agreed_partition` becomes `(4, 2, 8, 44)`. The plan previously said three buckets. | A reset treats a template and its document inconsistently. |
| R4 | `_pricing_value` takes `currency` explicitly and never mutates `line_items` — that list is persisted to a JSON column and returned to the Android app. | A private `_currency` key leaks into stored proposals and the mobile contract. |
| R5 | Task 22 has no commit step: the Android project is not a git repository. | None — changed files are reported instead. |
| R6 | The raw-XML ground-truth helper is imported from Task 2, never re-implemented; the original regex undercounts nested text-box paragraphs. | A ground-truth test could mask a walker bug — mitigated by the four real documents pinning 7/7/9/14. |

### Defects this plan shipped, found in review

Both of Task 1's and both of Task 2's Important findings were defects in **this
plan's own reference code**, not implementer error:

- `git add requirements.txt` (Task 1 Step 8) did not anticipate that the file
  was already dirty, so the commit swept in unrelated in-flight work.
- Task 1's `docx_to_pdf` could not pass its own `test_garbage_input_raises`:
  LibreOffice 7.3.7.2 emits a valid PDF from arbitrary bytes via its plain-text
  importer, so an OOXML pre-check is required.
- `replace_span` applied the `xml:space="preserve"` guard only to the first
  `w:t` of a multi-node span, so a trailing remainder such as `" today"` was
  written unguarded and Word would render `"Dear Greenwoodtoday"`.
- `all_roots`' header/footer identity de-duplication had no test; every fixture
  was single-section.
---

## File Structure

**New backend modules** — `app/services/docx/` (a package, because five focused files beat one 900-line service):

| File | Responsibility |
|---|---|
| `docx/text.py` | `w:t`-level text access and span replacement. No knowledge of plans. |
| `docx/outline.py` | Parse a document into blocks with paths + fingerprints; text projection. |
| `docx/ocr.py` | Extract embedded images, shell out to `tesseract`, cache per image. |
| `docx/index.py` | Detect `index_kind`; parse and rewrite static TOC entries. |
| `docx/edit.py` | Structural edits: insert paragraph, replace paragraph text, table cell/row writes, anchor resolution with fingerprint verification. |
| `docx/fill.py` | Apply a whole fill plan given resolved values. Pure and deterministic. |
| `docx/convert.py` | LibreOffice DOCX→PDF, and the two-pass page-number refresh. |

**New AI modules:** `app/ai/docx_suggest.py` (suggestion pass), `app/ai/docx_prose.py` (fill contract + retry + escalation), `app/services/fill_scrub.py` (deterministic scrubber, extends `draft_check`).

**Modified backend:** `app/models/program.py`, `app/models/proposal.py`, `app/models/__init__.py`, `app/core/reset_taxonomy.py`, `app/services/proposal_service.py`, `app/services/proposal_email_service.py`, `app/ai/agents/proposal_agent.py`, `app/api/admin.py`, `app/api/proposals.py`, `requirements.txt` (no new packages; a comment recording the two system dependencies).

**Console:** `Dashboard/src/screens/ProposalTemplates.tsx` (mode switch), new `Dashboard/src/screens/docx/` (`DocxEditor.tsx`, `BlockFlow.tsx`, `SuggestionChip.tsx`, `TokenPanel.tsx`, `TableBinding.tsx`, `plan.ts`), `Dashboard/src/api/endpoints.ts`, regenerated `Dashboard/src/api/generated.ts` + `openapi.json`.

**Android:** `ProposalDetailDto.java`, `ProposalDetailFragment.java`, `fragment_proposal_detail.xml`, `strings.xml`.

**Tests:** `tests/docx/` — `conftest.py` (synthetic fixture builders), `test_text.py`, `test_outline.py`, `test_index.py`, `test_edit.py`, `test_fill.py`, `test_scrub.py`, `test_convert.py`, `test_golden_samples.py` (opt-in, skips when `data/samples/` is absent).

---

## Phase 0 — Foundation

### Task 1: Branch, sample fixtures, and the LibreOffice converter

**Files:**
- Create: `app/services/docx/__init__.py`, `app/services/docx/convert.py`
- Create: `tests/docx/__init__.py`, `tests/docx/test_convert.py`
- Modify: `requirements.txt` (comment only)

**Interfaces:**
- Consumes: nothing.
- Produces: `convert.docx_to_pdf(docx_bytes: bytes, *, timeout: int = 120) -> bytes`, raising `ExternalServiceError` when `soffice` is missing or the convert fails or times out. `convert.SOFFICE = "/usr/bin/soffice"`.

- [ ] **Step 1: Create the working branch**

```bash
cd /home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project
git checkout -b feature/docx-proposal-templates
git status --porcelain | wc -l   # expect 89 — the pre-existing dirty tree, untouched
```

- [ ] **Step 2: Confirm the environment (already provisioned on 2026-09-03; re-verify, do not reinstall)**

```bash
which soffice tesseract          # /usr/bin/soffice  /usr/bin/tesseract
soffice --version | head -1      # LibreOffice 7.3.7.2 ...
tesseract --list-langs | tail -2 # eng, osd
ls -l data/samples/              # 4 .docx files
sha256sum data/samples/*.docx
```

Expected sha256 prefixes: `Essential Lab.docx` `80ea1e51f860c6a4`, `Innovation Lab Template.docx` `2fd0cd002e82ed08`, `School_YuviPep 360_2 1.docx` `152e991e7af64c4a`, `School_YuviPep 360 EmpowerED_New_compressed.docx` `48f70ef325c1dbef`.

- [ ] **Step 3: Write the failing test**

```python
# tests/docx/test_convert.py
import pytest
from docx import Document
import io

from app.core.exceptions import ExternalServiceError
from app.services.docx import convert


def _tiny_docx() -> bytes:
    doc = Document()
    doc.add_heading("Hello", level=1)
    doc.add_paragraph("A sentence that will appear in the PDF text layer.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_converts_docx_to_pdf():
    pdf = convert.docx_to_pdf(_tiny_docx())
    assert pdf[:5] == b"%PDF-"
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "will appear in the PDF text layer" in text


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setattr(convert, "SOFFICE", "/nonexistent/soffice")
    with pytest.raises(ExternalServiceError) as err:
        convert.docx_to_pdf(_tiny_docx())
    assert "LibreOffice" in str(err.value)


def test_garbage_input_raises():
    with pytest.raises(ExternalServiceError):
        convert.docx_to_pdf(b"this is not a docx")
```

- [ ] **Step 4: Run it and watch it fail**

```bash
.venv/bin/python -m pytest tests/docx/test_convert.py -q
```

Expected: `ModuleNotFoundError: No module named 'app.services.docx'`.

- [ ] **Step 5: Implement the converter**

```python
# app/services/docx/convert.py
"""DOCX -> PDF through LibreOffice headless.

Why not reportlab: the templates this serves are branded documents with cover
art, per-section headers and footers, theme fonts and styled tables. Rebuilding
them from extracted text is what the whole feature exists to stop doing. A
silently unbranded PDF reaching a client is worse than a refusal, so there is
no fallback here — a failure raises.

Each call gets its own `-env:UserInstallation` profile directory. A shared
profile serialises concurrent conversions and, worse, leaves a lock file behind
after a killed process that makes every later convert hang.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

SOFFICE = "/usr/bin/soffice"


def docx_to_pdf(docx_bytes: bytes, *, timeout: int = 120) -> bytes:
    if not docx_bytes:
        raise ExternalServiceError("Cannot convert an empty document to PDF")
    if not Path(SOFFICE).exists() and shutil.which(SOFFICE) is None:
        raise ExternalServiceError(
            "LibreOffice is not installed on this server, so the proposal PDF "
            "cannot be produced. Install libreoffice-writer, or download the "
            "DOCX instead."
        )
    with tempfile.TemporaryDirectory(prefix="docxpdf_") as tmp:
        work = Path(tmp)
        src = work / "in.docx"
        src.write_bytes(docx_bytes)
        profile = work / "profile"
        cmd = [
            SOFFICE, "--headless", "--norestore", "--invisible",
            f"-env:UserInstallation=file://{profile}",
            "--convert-to", "pdf", "--outdir", str(work), str(src),
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout, check=False,
                env={"HOME": str(work), "PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired as exc:
            raise ExternalServiceError(
                f"Converting the proposal to PDF took longer than {timeout}s "
                "and was stopped."
            ) from exc
        out = work / "in.pdf"
        if not out.exists():
            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")
            logger.error("soffice produced no PDF: rc=%s %s", proc.returncode, detail[:400])
            raise ExternalServiceError(
                "LibreOffice could not convert this document to PDF."
            )
        return out.read_bytes()
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_convert.py -q
```

Expected: 3 passed. First run takes ~5s (LibreOffice cold start), later runs ~2s.

- [ ] **Step 7: Record the system dependencies**

Append to `requirements.txt`:

```
# ── System packages required by the DOCX proposal-template path ──────────────
# These are NOT pip installable and are not installed by this file.
#   tesseract-ocr   (4.1.1, 'eng' model)  — OCR of images embedded in templates
#   libreoffice-writer (7.3.7)            — DOCX -> PDF for docx-kind proposals
# Both are called through subprocess; no Python wrapper package is used.
```

- [ ] **Step 8: Full suite, then commit**

```bash
.venv/bin/python -m pytest -q
git add app/services/docx/__init__.py app/services/docx/convert.py \
        tests/docx/__init__.py tests/docx/test_convert.py requirements.txt
git commit -m "feat(docx): LibreOffice DOCX->PDF converter"
```

---

## Phase 1 — The DOCX engine

### Task 2: `docx/text.py` — text access that sees everything

This is the module the whole feature stands on. It is written first, and against ground truth taken from the raw XML rather than from python-docx, because python-docx is exactly what gets this wrong.

**Files:**
- Create: `app/services/docx/text.py`
- Create: `tests/docx/conftest.py`, `tests/docx/test_text.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `iter_paragraphs(root) -> Iterator[CT_P]` — every `w:p` in document order.
  - `own_text_nodes(p) -> list[CT_Text]` — `w:t` descendants whose nearest `w:p` ancestor is `p`.
  - `node_text(p) -> str`
  - `replace_span(p, start: int, end: int, replacement: str) -> bool`
  - `replace_token_in_paragraph(p, literal: str, replacement: str) -> int`
  - `all_roots(doc) -> list[element]` — body plus every distinct header/footer element.
  - `replace_token(doc, literal, replacement) -> int`
  - `count_token(doc, literal) -> int`

- [ ] **Step 1: Write the fixture builders**

```python
# tests/docx/conftest.py
"""Synthetic .docx fixtures that reproduce the shapes real documents use.

Word fragments runs arbitrarily and buries text in hyperlinks and text boxes.
`Paragraph.runs` sees none of the latter two, so every fixture here exists to
pin one of those shapes.
"""
import io

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _t(text: str):
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    return t


def _run(text: str, *, bold: bool = False):
    r = OxmlElement("w:r")
    if bold:
        rpr = OxmlElement("w:rPr")
        rpr.append(OxmlElement("w:b"))
        r.append(rpr)
    r.append(_t(text))
    return r


def save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def fragmented_docx() -> bytes:
    """'School Name' split across three runs, as Word actually writes it."""
    doc = Document()
    p = doc.add_paragraph()
    for chunk in ("Welcome to ", "School", " ", "Name", " for the year."):
        p._p.append(_run(chunk))
    return save(doc)


@pytest.fixture
def hyperlink_docx() -> bytes:
    """Text inside w:hyperlink — invisible to Paragraph.runs."""
    doc = Document()
    p = doc.add_paragraph()
    p._p.append(_run("Contact "))
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), "_bookmark0")
    link.append(_run("School"))
    link.append(_run(" "))
    link.append(_run("Name"))
    p._p.append(link)
    p._p.append(_run(" today."))
    return save(doc)


@pytest.fixture
def textbox_docx() -> bytes:
    """A whole w:p nested inside a text box within an outer paragraph."""
    doc = Document()
    outer = doc.add_paragraph()
    outer._p.append(_run("Outer School Name text."))
    r = OxmlElement("w:r")
    pict = OxmlElement("w:pict")
    shape = OxmlElement("v:shape")
    tbx = OxmlElement("v:textbox")
    content = OxmlElement("w:txbxContent")
    inner = OxmlElement("w:p")
    inner.append(_run("Inner School Name label."))
    content.append(inner)
    tbx.append(content)
    shape.append(tbx)
    pict.append(shape)
    r.append(pict)
    outer._p.append(r)
    return save(doc)


@pytest.fixture
def table_docx() -> bytes:
    doc = Document()
    t = doc.add_table(rows=3, cols=2)
    t.style = "Table Grid"
    t.cell(0, 0).text = "Description"
    t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Innovation Lab"
    t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total"
    t.cell(2, 1).text = "Rs 0"
    return save(doc)


@pytest.fixture
def header_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Body mentions School Name once.")
    header = doc.sections[0].header
    header.is_linked_to_previous = False
    header.paragraphs[0]._p.append(_run("Header for School Name"))
    footer = doc.sections[0].footer
    footer.is_linked_to_previous = False
    footer.paragraphs[0]._p.append(_run("Footer for School Name"))
    return save(doc)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/docx/test_text.py
import io
import re
import zipfile

from docx import Document

from app.services.docx import text as dt


def raw_count(data: bytes, literal: str) -> int:
    """Ground truth: count per <w:p> across every word/*.xml part.

    Nested paragraphs (text boxes) are removed from a paragraph's own chunk so
    each occurrence is attributed exactly once.
    """
    z = zipfile.ZipFile(io.BytesIO(data))
    total = 0
    for name in z.namelist():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        x = z.read(name).decode("utf8", "replace")
        for m in re.finditer(r"<w:p[ >].*?</w:p>", x, re.S):
            inner = re.sub(r"<w:p[ >].*?</w:p>", "", m.group(0)[3:], flags=re.S)
            body = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", inner, re.S))
            total += body.count(literal)
    return total


def _doc(data: bytes):
    return Document(io.BytesIO(data))


def test_sees_text_split_across_runs(fragmented_docx):
    doc = _doc(fragmented_docx)
    assert dt.count_token(doc, "School Name") == 1


def test_replaces_text_split_across_runs(fragmented_docx):
    doc = _doc(fragmented_docx)
    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
    p = next(dt.iter_paragraphs(doc.element.body))
    assert dt.node_text(p) == "Welcome to Greenwood for the year."


def test_sees_text_inside_hyperlinks(hyperlink_docx):
    doc = _doc(hyperlink_docx)
    # the defect this pins: Paragraph.runs returns nothing useful here
    assert len(doc.paragraphs[0].runs) < 4
    assert dt.count_token(doc, "School Name") == 1
    assert dt.replace_token(doc, "School Name", "Greenwood") == 1
    assert "Greenwood" in dt.node_text(next(dt.iter_paragraphs(doc.element.body)))


def test_sees_text_inside_textboxes(textbox_docx):
    doc = _doc(textbox_docx)
    assert dt.count_token(doc, "School Name") == 2
    assert dt.replace_token(doc, "School Name", "Greenwood") == 2
    assert dt.count_token(doc, "School Name") == 0


def test_textbox_text_is_not_spliced_into_the_outer_paragraph(textbox_docx):
    doc = _doc(textbox_docx)
    outer = next(dt.iter_paragraphs(doc.element.body))
    assert dt.node_text(outer) == "Outer School Name text."


def test_sees_text_in_headers_and_footers(header_docx):
    doc = _doc(header_docx)
    assert dt.count_token(doc, "School Name") == 3
    assert dt.replace_token(doc, "School Name", "Greenwood") == 3
    assert dt.count_token(doc, "School Name") == 0


def test_sees_text_in_table_cells(table_docx):
    doc = _doc(table_docx)
    assert dt.count_token(doc, "Innovation Lab") == 1
    assert dt.replace_token(doc, "Innovation Lab", "Essential Lab") == 1


def test_matches_raw_xml_ground_truth(fragmented_docx, hyperlink_docx,
                                      textbox_docx, header_docx):
    for data in (fragmented_docx, hyperlink_docx, textbox_docx, header_docx):
        assert dt.count_token(_doc(data), "School Name") == raw_count(data, "School Name")


def test_replace_span_preserves_surrounding_text(fragmented_docx):
    doc = _doc(fragmented_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    start = dt.node_text(p).index("School Name")
    assert dt.replace_span(p, start, start + len("School Name"), "X")
    assert dt.node_text(p) == "Welcome to X for the year."


def test_replace_span_out_of_range_is_a_no_op(fragmented_docx):
    doc = _doc(fragmented_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    before = dt.node_text(p)
    assert dt.replace_span(p, 9999, 10000, "X") is False
    assert dt.node_text(p) == before


def test_leading_space_survives_a_replacement(fragmented_docx):
    doc = _doc(fragmented_docx)
    p = next(dt.iter_paragraphs(doc.element.body))
    dt.replace_span(p, 0, len("Welcome to"), "  Hello  ")
    buf = io.BytesIO()
    doc.save(buf)
    assert dt.node_text(next(dt.iter_paragraphs(_doc(buf.getvalue()).element.body))) \
        == "  Hello   School Name for the year."
```

- [ ] **Step 3: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_text.py -q
```

Expected: collection error, `cannot import name 'text' from 'app.services.docx'`.

- [ ] **Step 4: Implement**

```python
# app/services/docx/text.py
"""Text access at the `w:t` level, and span replacement that survives it.

**Do not use `Paragraph.runs` anywhere in this feature.** It omits runs nested
in `w:hyperlink` and never descends into text boxes
(`mc:AlternateContent`/`w:pict` -> `w:txbxContent`). Measured against the four
real sample documents, a `.runs`-based walk found 4 of 7, 1 of 7, 1 of 9 and
2 of 14 occurrences of the client-name literal — and the verification pass,
using the same walk, agreed with itself and reported success. The result would
have been a client-facing proposal still reading "School Name".

Word also fragments runs arbitrarily: `School Name` is commonly three runs,
`['School', ' ', 'Name']`, so a `run.text.replace(...)` matches nothing. Every
replacement here works on the *joined* text of a paragraph's own `w:t` nodes
and then writes back across whichever nodes the match covered.
"""
from __future__ import annotations

from typing import Iterator

from docx.oxml.ns import qn

W_P = qn("w:p")
W_T = qn("w:t")
W_INSTR = qn("w:instrText")
XML_SPACE = qn("xml:space")

_MAX_REPLACEMENTS = 500


def iter_paragraphs(root) -> Iterator:
    """Every `w:p` under `root`, in document order.

    `.iter()` is a full-tree walk, so this reaches paragraphs inside tables,
    structured document tags and text boxes — all places real templates hide
    text that `doc.paragraphs` never yields.
    """
    return root.iter(W_P)


def own_text_nodes(p) -> list:
    """The `w:t` nodes belonging to `p` itself.

    A text box nests a complete `w:p` inside a run of the outer paragraph. Its
    text is a separate paragraph: splicing it into the outer paragraph's string
    would corrupt offsets and let a replacement write into the wrong place.
    """
    out = []
    for t in p.iter(W_T):
        anc = t.getparent()
        while anc is not None and anc.tag != W_P:
            anc = anc.getparent()
        if anc is p:
            out.append(t)
    return out


def node_text(p) -> str:
    return "".join(t.text or "" for t in own_text_nodes(p))


def replace_span(p, start: int, end: int, replacement: str) -> bool:
    """Replace `[start, end)` of `node_text(p)`. Returns whether anything changed.

    The replacement lands in the node holding `start` and inherits that node's
    run formatting; the rest of the covered range is blanked. Nodes outside the
    span are untouched, so a change to one word cannot restyle a paragraph.
    """
    if start >= end:
        return False
    nodes = own_text_nodes(p)
    spans, offset = [], 0
    for t in nodes:
        s = t.text or ""
        spans.append((t, offset, offset + len(s)))
        offset += len(s)

    first = True
    for t, t0, t1 in spans:
        if t1 <= start or t0 >= end:
            continue
        s = t.text or ""
        lo, hi = max(start, t0) - t0, min(end, t1) - t0
        if first:
            t.text = s[:lo] + replacement + s[hi:]
            # a w:t whose value has significant leading/trailing whitespace is
            # collapsed by Word unless xml:space says otherwise
            if t.text != t.text.strip():
                t.set(XML_SPACE, "preserve")
            first = False
        else:
            t.text = s[:lo] + s[hi:]
    return not first


def replace_token_in_paragraph(p, literal: str, replacement: str) -> int:
    if not literal:
        return 0
    count = 0
    while count < _MAX_REPLACEMENTS:
        found = node_text(p).find(literal)
        if found < 0:
            return count
        if not replace_span(p, found, found + len(literal), replacement):
            return count
        count += 1
    return count


def all_roots(doc) -> list:
    """The body plus every distinct header/footer element in the package.

    Sections share header/footer parts when linked to previous, so identity is
    de-duplicated — otherwise a shared footer is rewritten once per section and
    the occurrence count lies.
    """
    roots = [doc.element.body]
    seen: set[int] = set()
    for section in doc.sections:
        for part in (
            section.header, section.footer,
            section.even_page_header, section.even_page_footer,
            section.first_page_header, section.first_page_footer,
        ):
            if part is None:
                continue
            el = part._element
            if id(el) in seen:
                continue
            seen.add(id(el))
            roots.append(el)
    return roots


def replace_token(doc, literal: str, replacement: str) -> int:
    return sum(
        replace_token_in_paragraph(p, literal, replacement)
        for root in all_roots(doc)
        for p in iter_paragraphs(root)
    )


def count_token(doc, literal: str) -> int:
    if not literal:
        return 0
    return sum(
        node_text(p).count(literal)
        for root in all_roots(doc)
        for p in iter_paragraphs(root)
    )
```

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_text.py -q
```

Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add app/services/docx/text.py tests/docx/conftest.py tests/docx/test_text.py
git commit -m "feat(docx): w:t-level text access and span replacement"
```

---

### Task 3: Golden test against the four real documents

Written now, immediately after `text.py`, because it is the test that proved the defect in the first place and it must guard every later change.

**Files:**
- Create: `tests/docx/test_golden_samples.py`

**Interfaces:**
- Consumes: `docx.text` from Task 2.
- Produces: `SAMPLES: dict[str, str]` mapping sample filename to its client-name literal, reused by later golden tests.

- [ ] **Step 1: Write the test**

```python
# tests/docx/test_golden_samples.py
"""Opt-in tests against the organisation's four real proposal documents.

They live in `data/samples/` and are not in git — 27 MB of branded material.
When the directory is absent every test here skips, so a clean checkout stays
green; on the VM they run and are the real proof.
"""
import io
import re
import zipfile
from pathlib import Path

import pytest
from docx import Document

from app.services.docx import text as dt

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"

# filename -> the client-name literal that document uses
SAMPLES = {
    "Essential Lab.docx": "School Name",
    "Innovation Lab Template.docx": "School Name",
    "School_YuviPep 360_2 1.docx": "School School",
    "School_YuviPep 360 EmpowerED_New_compressed.docx": "School Name",
}

# measured 2026-09-03 against the raw XML
EXPECTED_OCCURRENCES = {
    "Essential Lab.docx": 7,
    "Innovation Lab Template.docx": 7,
    "School_YuviPep 360_2 1.docx": 9,
    "School_YuviPep 360 EmpowerED_New_compressed.docx": 14,
}

pytestmark = pytest.mark.skipif(
    not SAMPLES_DIR.is_dir(), reason="data/samples/ not present"
)


> **The ground-truth helper is NOT re-implemented here.** The regex
> `<w:p[ >].*?</w:p>` that earlier drafts of this plan used is defective: a
> non-greedy single-pass scan conflates a nested (text-box) `w:p`'s closing tag
> with its outer paragraph's and silently discards the inner paragraph's text.
> Measured on a nested fixture whose true count is 2, it returns 1. Task 2
> replaced it with a stack-based tokenizer that attributes each `w:t` to the
> innermost open `w:p` — matching `own_text_nodes`' contract while staying
> independent of the tree API under test. **Import Task 2's helper**; add only a
> one-line path wrapper:
>
> ```python
> from tests.docx.test_text import raw_count as raw_count_bytes
>
> def raw_count(path, literal):
>     return raw_count_bytes(Path(path).read_bytes(), literal)
> ```
>
> If the pytest layout makes that import awkward, move the corrected helper and
> its token regex into `tests/docx/conftest.py` as a plain module-level function
> (not a fixture) and import it from both test modules. Do not copy the
> tokenizer body a second time — duplicated ground-truth logic is the defect
> that made this note necessary.

def raw_count(path: Path, literal: str) -> int:
    z = zipfile.ZipFile(path)
    total = 0
    for name in z.namelist():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        x = z.read(name).decode("utf8", "replace")
        for m in re.finditer(r"<w:p[ >].*?</w:p>", x, re.S):
            inner = re.sub(r"<w:p[ >].*?</w:p>", "", m.group(0)[3:], flags=re.S)
            body = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", inner, re.S))
            total += body.count(literal)
    return total


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_walker_agrees_with_raw_xml(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    doc = Document(str(path))
    assert dt.count_token(doc, literal) == raw_count(path, literal)


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_occurrence_counts_have_not_drifted(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    doc = Document(str(path))
    assert dt.count_token(doc, literal) == EXPECTED_OCCURRENCES[name]


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_replacement_leaves_nothing_behind(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    doc = Document(str(path))
    media_before = len(doc.part.package.image_parts)
    sections_before = len(doc.sections)

    replaced = dt.replace_token(doc, literal, "Greenwood International School")
    assert replaced == EXPECTED_OCCURRENCES[name]

    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()

    reopened = Document(io.BytesIO(data))
    assert dt.count_token(reopened, literal) == 0
    assert raw_count_bytes(data, literal) == 0
    assert len(reopened.part.package.image_parts) == media_before
    assert len(reopened.sections) == sections_before


def raw_count_bytes(data: bytes, literal: str) -> int:
    tmp = io.BytesIO(data)
    z = zipfile.ZipFile(tmp)
    total = 0
    for name in z.namelist():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        x = z.read(name).decode("utf8", "replace")
        for m in re.finditer(r"<w:p[ >].*?</w:p>", x, re.S):
            inner = re.sub(r"<w:p[ >].*?</w:p>", "", m.group(0)[3:], flags=re.S)
            body = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", inner, re.S))
            total += body.count(literal)
    return total
```

- [ ] **Step 2: Run it**

```bash
.venv/bin/python -m pytest tests/docx/test_golden_samples.py -q
```

Expected: 12 passed. If any counts differ, the sample files changed — re-measure and update `EXPECTED_OCCURRENCES` deliberately, never to make a red test green.

- [ ] **Step 3: Commit**

```bash
git add tests/docx/test_golden_samples.py
git commit -m "test(docx): golden coverage over the four real proposal documents"
```

---

### Task 4: `docx/outline.py` — blocks, paths, fingerprints, text projection

**Files:**
- Create: `app/services/docx/outline.py`
- Create: `tests/docx/test_outline.py`

**Interfaces:**
- Consumes: `docx.text` (Task 2).
- Produces:
  - `parse(docx_bytes: bytes) -> Outline` where `Outline` is a `TypedDict` with keys `blocks: list[Block]`, `headings: list[dict]`, `tokens: list[dict]`, `media: list[str]`.
  - `Block` keys: `id`, `path`, `kind` (`"paragraph"|"heading"|"table"|"image"|"empty"`), `style`, `level`, `text`, `fingerprint`, `images`, `table`.
  - `resolve(doc, path: str)` -> the lxml element at that path, raising `AnchorError`.
  - `fingerprint(kind, style, text) -> str`
  - `verify(doc, path: str, expected_fingerprint: str) -> element` — raises `AnchorError` on mismatch.
  - `project_text(outline: Outline) -> str` — the `body_md` text projection.
  - `candidate_tokens(outline) -> list[dict]` — `{literal, occurrences, sample_block_ids}`.
  - `class AnchorError(ValidationFailedError)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_outline.py
import io

import pytest
from docx import Document

from app.services.docx import outline as ol


def test_paths_address_top_level_body_children(table_docx):
    out = ol.parse(table_docx)
    paths = [b["path"] for b in out["blocks"]]
    assert paths[0].startswith("body[")
    assert any(b["kind"] == "table" for b in out["blocks"])


def test_table_block_reports_its_shape(table_docx):
    out = ol.parse(table_docx)
    table = next(b for b in out["blocks"] if b["kind"] == "table")
    assert table["table"]["rows"] == 3
    assert table["table"]["cols"] == 2
    assert table["table"]["header"] == ["Description", "Estimation"]


def test_headings_are_classified_with_a_level():
    doc = Document()
    doc.add_heading("Pricing Overview", level=1)
    doc.add_paragraph("Body text here.")
    buf = io.BytesIO(); doc.save(buf)
    out = ol.parse(buf.getvalue())
    heading = next(b for b in out["blocks"] if b["kind"] == "heading")
    assert heading["level"] == 1
    assert heading["text"] == "Pricing Overview"
    assert out["headings"][0]["text"] == "Pricing Overview"


def test_resolve_round_trips_every_path(table_docx):
    out = ol.parse(table_docx)
    doc = Document(io.BytesIO(table_docx))
    for block in out["blocks"]:
        assert ol.resolve(doc, block["path"]) is not None


def test_verify_accepts_a_matching_fingerprint(table_docx):
    out = ol.parse(table_docx)
    doc = Document(io.BytesIO(table_docx))
    block = out["blocks"][0]
    assert ol.verify(doc, block["path"], block["fingerprint"]) is not None


def test_verify_rejects_a_changed_block(table_docx):
    out = ol.parse(table_docx)
    doc = Document(io.BytesIO(table_docx))
    block = out["blocks"][0]
    with pytest.raises(ol.AnchorError) as err:
        ol.verify(doc, block["path"], "sha256:deadbeef")
    assert "no longer matches" in str(err.value)


def test_verify_rejects_a_path_that_does_not_exist(table_docx):
    doc = Document(io.BytesIO(table_docx))
    with pytest.raises(ol.AnchorError):
        ol.verify(doc, "body[9999]", "sha256:whatever")


def test_candidate_tokens_finds_repeated_title_case_literals():
    doc = Document()
    for _ in range(3):
        doc.add_paragraph("Prepared for School Name by YuviPep.")
    buf = io.BytesIO(); doc.save(buf)
    out = ol.parse(buf.getvalue())
    literals = {t["literal"]: t["occurrences"] for t in out["tokens"]}
    assert literals.get("School Name") == 3


def test_text_projection_reads_as_a_document(table_docx):
    out = ol.parse(table_docx)
    projected = ol.project_text(out)
    assert "Description" in projected
    assert "Innovation Lab" in projected
    assert len(projected) >= 20      # ProposalTemplateRequest.body_md min_length


def test_header_and_footer_blocks_are_addressable(header_docx):
    out = ol.parse(header_docx)
    paths = [b["path"] for b in out["blocks"]]
    assert any(p.startswith("sec[0]/hdr") for p in paths)
    assert any(p.startswith("sec[0]/ftr") for p in paths)
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_outline.py -q
```

Expected: `cannot import name 'outline'`.

- [ ] **Step 3: Implement**

```python
# app/services/docx/outline.py
"""Parse a .docx into the read-only block outline the console edits against.

The outline is a *view*. It is never written back: the uploaded file is
immutable, and a new upload is a new template version with its own outline.
That immutability is what makes positional paths (`body[7]`,
`body[29]/tr[2]/tc[1]/p[0]`) safe to store in a fill plan.

Each block also carries a fingerprint. Generation verifies it before writing,
so a plan pointed at the wrong document fails loudly instead of silently
putting the client's greeting in the middle of a pricing table.
"""
from __future__ import annotations

import hashlib
import io
import re
from collections import Counter
from typing import Any

from docx import Document
from docx.oxml.ns import qn

from app.core.exceptions import ValidationFailedError
from app.services.docx import text as dt

W_P = qn("w:p")
W_TBL = qn("w:tbl")
W_TR = qn("w:tr")
W_TC = qn("w:tc")
W_PPR = qn("w:pPr")
W_PSTYLE = qn("w:pStyle")
W_DRAWING = qn("w:drawing")
W_PICT = qn("w:pict")
W_BLIP = qn("a:blip")
R_EMBED = qn("r:embed")

_HEADING_RE = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
_HEADING_COMPACT = re.compile(r"^heading([1-9])$", re.IGNORECASE)
_PATH_RE = re.compile(r"([a-z]+)(?:\[(\d+)\])?")

# A candidate literal: two to five Title-Case words, no digits or punctuation.
# Narrow on purpose — a suggestion the administrator must accept is cheap, but
# a panel listing four hundred phrases is unusable.
_CANDIDATE_RE = re.compile(r"\b(?:[A-Z][a-z]{1,20})(?:\s+[A-Z][a-z]{1,20}){1,4}\b")
_CANDIDATE_STOPWORDS = {
    "Table Of Contents", "All Rights Reserved", "Document Version",
}


class AnchorError(ValidationFailedError):
    """A fill plan points at a block that is not there any more."""


def fingerprint(kind: str, style: str, text: str) -> str:
    payload = f"{kind}|{style}|{(text or '')[:40]}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()[:16]


def _style_of(p) -> str:
    ppr = p.find(W_PPR)
    if ppr is None:
        return ""
    style = ppr.find(W_PSTYLE)
    if style is None:
        return ""
    return style.get(qn("w:val")) or ""


def _heading_level(style: str) -> int | None:
    for pattern in (_HEADING_RE, _HEADING_COMPACT):
        m = pattern.match(style or "")
        if m:
            return int(m.group(1))
    return None


def _image_ids(el) -> list[str]:
    ids = []
    for blip in el.iter(W_BLIP):
        rid = blip.get(R_EMBED)
        if rid:
            ids.append(rid)
    if not ids and (el.find(".//" + W_PICT) is not None or el.find(".//" + W_DRAWING) is not None):
        ids.append("inline")
    return ids


def _paragraph_block(p, path: str, index: int) -> dict[str, Any]:
    style = _style_of(p)
    level = _heading_level(style)
    body = dt.node_text(p)
    images = _image_ids(p)
    if level is not None:
        kind = "heading"
    elif images and not body.strip():
        kind = "image"
    elif not body.strip():
        kind = "empty"
    else:
        kind = "paragraph"
    return {
        "id": f"b{index}",
        "path": path,
        "kind": kind,
        "style": style,
        "level": level,
        "text": body,
        "images": images,
        "table": None,
        "fingerprint": fingerprint(kind, style, body),
    }


def _table_block(tbl, path: str, index: int) -> dict[str, Any]:
    rows = tbl.findall(W_TR)
    header: list[str] = []
    sample: list[list[str]] = []
    for r_i, tr in enumerate(rows[:4]):
        cells = []
        for tc in tr.findall(W_TC):
            cells.append(" ".join(dt.node_text(p) for p in tc.findall(W_P)).strip())
        if r_i == 0:
            header = cells
        sample.append(cells)
    cols = max((len(r) for r in sample), default=0)
    joined = " | ".join(header)
    return {
        "id": f"b{index}",
        "path": path,
        "kind": "table",
        "style": "",
        "level": None,
        "text": joined,
        "images": [],
        "table": {"rows": len(rows), "cols": cols, "header": header, "sample": sample},
        "fingerprint": fingerprint("table", "", joined),
    }


def _walk(root, prefix: str, blocks: list, counter: list) -> None:
    """Top-level children only. Nested paragraphs are reachable through paths,
    but the console flow shows the document's own top-level structure."""
    p_i = tbl_i = 0
    for child in root.iterchildren():
        if child.tag == W_P:
            blocks.append(_paragraph_block(child, f"{prefix}[{p_i + tbl_i}]", counter[0]))
            counter[0] += 1
            p_i += 1
        elif child.tag == W_TBL:
            blocks.append(_table_block(child, f"{prefix}[{p_i + tbl_i}]", counter[0]))
            counter[0] += 1
            tbl_i += 1


def parse(docx_bytes: bytes) -> dict[str, Any]:
    doc = Document(io.BytesIO(docx_bytes))
    blocks: list[dict[str, Any]] = []
    counter = [0]
    _walk(doc.element.body, "body", blocks, counter)

    seen: set[int] = set()
    for s_i, section in enumerate(doc.sections):
        for label, part in (("hdr", section.header), ("ftr", section.footer)):
            if part is None or id(part._element) in seen:
                continue
            seen.add(id(part._element))
            _walk(part._element, f"sec[{s_i}]/{label}/body", blocks, counter)

    headings = [
        {"id": b["id"], "path": b["path"], "level": b["level"], "text": b["text"]}
        for b in blocks if b["kind"] == "heading"
    ]
    media = sorted({
        part.partname.split("/")[-1] for part in doc.part.package.image_parts
    })
    outline = {"blocks": blocks, "headings": headings, "tokens": [], "media": media}
    outline["tokens"] = candidate_tokens(outline)
    return outline


def resolve(doc, path: str):
    """Walk a positional path to its element. Raises AnchorError if absent."""
    node = None
    for segment in path.split("/"):
        m = _PATH_RE.fullmatch(segment)
        if m is None:
            raise AnchorError(f"Malformed anchor '{path}'")
        name, raw_index = m.group(1), m.group(2)
        index = int(raw_index) if raw_index is not None else None
        if name == "body" and node is None:
            node = doc.element.body
            if index is not None:
                node = _nth_block_child(node, index, path)
        elif name == "sec":
            node = ("sec", index)
        elif name in ("hdr", "ftr"):
            if not (isinstance(node, tuple) and node[0] == "sec"):
                raise AnchorError(f"Malformed anchor '{path}'")
            section = doc.sections[node[1]]
            part = section.header if name == "hdr" else section.footer
            node = part._element
        elif name == "body":
            node = _nth_block_child(node, index, path) if index is not None else node
        elif name == "tr":
            node = _nth(node, W_TR, index, path)
        elif name == "tc":
            node = _nth(node, W_TC, index, path)
        elif name == "p":
            node = _nth(node, W_P, index, path)
        else:
            raise AnchorError(f"Unknown anchor segment '{segment}' in '{path}'")
    if node is None or isinstance(node, tuple):
        raise AnchorError(f"Anchor '{path}' does not resolve to an element")
    return node


def _nth_block_child(parent, index: int, path: str):
    children = [c for c in parent.iterchildren() if c.tag in (W_P, W_TBL)]
    if index is None or index >= len(children):
        raise AnchorError(f"Anchor '{path}' is out of range for this document")
    return children[index]


def _nth(parent, tag, index: int | None, path: str):
    if parent is None or index is None:
        raise AnchorError(f"Malformed anchor '{path}'")
    children = parent.findall(tag)
    if index >= len(children):
        raise AnchorError(f"Anchor '{path}' is out of range for this document")
    return children[index]


def _fingerprint_of_element(el) -> str:
    if el.tag == W_TBL:
        rows = el.findall(W_TR)
        header = []
        if rows:
            for tc in rows[0].findall(W_TC):
                header.append(" ".join(dt.node_text(p) for p in tc.findall(W_P)).strip())
        return fingerprint("table", "", " | ".join(header))
    style = _style_of(el)
    level = _heading_level(style)
    body = dt.node_text(el)
    images = _image_ids(el)
    if level is not None:
        kind = "heading"
    elif images and not body.strip():
        kind = "image"
    elif not body.strip():
        kind = "empty"
    else:
        kind = "paragraph"
    return fingerprint(kind, style, body)


def verify(doc, path: str, expected: str):
    el = resolve(doc, path)
    actual = _fingerprint_of_element(el)
    if actual != expected:
        raise AnchorError(
            f"The template block at '{path}' no longer matches what the fill "
            f"plan was built against (expected {expected}, found {actual}). "
            "Re-upload the document and rebuild its placeholders."
        )
    return el


def project_text(outline: dict[str, Any]) -> str:
    """A plain-text rendering of the document.

    Stored as `ProposalTemplate.body_md` for docx templates so every existing
    consumer — draft_check, revisions, the bundle, the Android content view —
    keeps working. Deliberately not Markdown: emitting `##` here would put the
    very markers this feature removes back into the pipeline.
    """
    lines: list[str] = []
    for block in outline["blocks"]:
        if block["kind"] == "table" and block["table"]:
            for row in block["table"]["sample"]:
                lines.append("  ".join(c for c in row if c))
        elif block["kind"] == "image":
            continue
        elif block["text"].strip():
            lines.append(block["text"].strip())
    return "\n\n".join(lines).strip()


def candidate_tokens(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """Repeated Title-Case phrases that look like hand-substituted fill-ins."""
    counts: Counter[str] = Counter()
    where: dict[str, list[str]] = {}
    for block in outline["blocks"]:
        for match in _CANDIDATE_RE.finditer(block["text"] or ""):
            literal = match.group(0)
            if literal in _CANDIDATE_STOPWORDS:
                continue
            counts[literal] += 1
            where.setdefault(literal, [])
            if block["id"] not in where[literal]:
                where[literal].append(block["id"])
    return [
        {"literal": literal, "occurrences": n, "sample_block_ids": where[literal][:5]}
        for literal, n in counts.most_common(60)
    ]
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_outline.py -q
```

Expected: 10 passed.

- [ ] **Step 5: Add a golden outline test**

Append to `tests/docx/test_golden_samples.py`:

```python
from app.services.docx import outline as ol

# measured 2026-09-03
EXPECTED_SHAPE = {
    "Essential Lab.docx": {"sections": 5, "media": 14, "tables": 3},
    "Innovation Lab Template.docx": {"sections": 6, "media": 14, "tables": 2},
    "School_YuviPep 360_2 1.docx": {"sections": 23, "media": 33, "tables": 18},
    "School_YuviPep 360 EmpowerED_New_compressed.docx":
        {"sections": 20, "media": 32, "tables": 14},
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_outline_parses_every_real_document(name):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    out = ol.parse(path.read_bytes())
    shape = EXPECTED_SHAPE[name]
    assert len(out["media"]) == shape["media"]
    assert sum(1 for b in out["blocks"] if b["kind"] == "table") == shape["tables"]
    assert out["headings"], "no headings found"
    assert len(ol.project_text(out)) > 500


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_every_outline_path_resolves_and_verifies(name):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    data = path.read_bytes()
    out = ol.parse(data)
    doc = Document(io.BytesIO(data))
    for block in out["blocks"]:
        ol.verify(doc, block["path"], block["fingerprint"])


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_the_client_literal_is_offered_as_a_token(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    out = ol.parse(path.read_bytes())
    assert literal in {t["literal"] for t in out["tokens"]}, (
        f"{literal!r} was not surfaced as a bindable token for {name}"
    )
```

- [ ] **Step 6: Run the golden tests**

```bash
.venv/bin/python -m pytest tests/docx/test_golden_samples.py -q
```

Expected: 24 passed. Every path in every real document must resolve *and* verify — that is the anchor scheme's proof.

- [ ] **Step 7: Commit**

```bash
git add app/services/docx/outline.py tests/docx/test_outline.py tests/docx/test_golden_samples.py
git commit -m "feat(docx): block outline with positional anchors and fingerprints"
```

---

### Task 5: `docx/ocr.py` — read the images

**Files:**
- Create: `app/services/docx/ocr.py`
- Create: `tests/docx/test_ocr.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ocr_document(docx_bytes: bytes, *, per_image_timeout: int = 20, max_images: int = 60) -> dict[str, str]` mapping media part name (`image3.jpeg`) to recognised text. Never raises for a single bad image — that image maps to `""`.
- Produces: `TESSERACT = "/usr/bin/tesseract"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_ocr.py
import io
import shutil

import pytest
from docx import Document
from docx.shared import Inches

from app.services.docx import ocr

needs_tesseract = pytest.mark.skipif(
    shutil.which(ocr.TESSERACT) is None and not __import__("pathlib").Path(ocr.TESSERACT).exists(),
    reason="tesseract not installed",
)


def _docx_with_text_image(tmp_path, words="PRICING OVERVIEW"):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (900, 220), "white")
    ImageDraw.Draw(img).text((30, 80), words, fill="black")
    png = tmp_path / "label.png"
    img.save(png)
    doc = Document()
    doc.add_paragraph("Intro")
    doc.add_picture(str(png), width=Inches(5))
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


@needs_tesseract
def test_reads_words_out_of_an_embedded_image(tmp_path):
    result = ocr.ocr_document(_docx_with_text_image(tmp_path))
    assert len(result) == 1
    assert "PRICING" in " ".join(result.values()).upper()


def test_a_document_with_no_images_returns_an_empty_map():
    doc = Document()
    doc.add_paragraph("No pictures here.")
    buf = io.BytesIO(); doc.save(buf)
    assert ocr.ocr_document(buf.getvalue()) == {}


def test_an_unreadable_image_maps_to_empty_string_and_does_not_raise(monkeypatch, tmp_path):
    data = _docx_with_text_image(tmp_path)
    monkeypatch.setattr(ocr, "TESSERACT", "/nonexistent/tesseract")
    result = ocr.ocr_document(data)
    assert set(result.values()) == {""}


def test_respects_the_image_cap(monkeypatch, tmp_path):
    data = _docx_with_text_image(tmp_path)
    result = ocr.ocr_document(data, max_images=0)
    assert result == {}
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_ocr.py -q
```

Expected: `cannot import name 'ocr'`.

- [ ] **Step 3: Implement**

```python
# app/services/docx/ocr.py
"""Read text out of the images a template embeds.

These documents carry a great deal of meaning as graphics — measured, 14 to 33
images each, and many paragraphs are nothing but a picture. Without this the
suggestion pass is blind to whole sections and proposes placeholders for the
few pages that happen to be prose.

Runs once at upload and is cached on the template row. It is never on the
proposal-generation path, so a slow OCR costs an administrator seconds while
publishing, and costs a salesperson nothing.

Shells out to the `tesseract` binary rather than adding `pytesseract`: one
fewer dependency, and the timeout is ours.
"""
from __future__ import annotations

import io
import logging
import subprocess
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

TESSERACT = "/usr/bin/tesseract"

_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
_MIN_BYTES = 2048          # below this it is a rule, a bullet or a gradient
_MIN_CHARS = 3


def ocr_document(
    docx_bytes: bytes, *, per_image_timeout: int = 20, max_images: int = 60
) -> dict[str, str]:
    out: dict[str, str] = {}
    if max_images <= 0:
        return out
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        names = [
            n for n in z.namelist()
            if n.startswith("word/media/") and Path(n).suffix.lower() in _EXT
        ]
        for name in sorted(names)[:max_images]:
            info = z.getinfo(name)
            key = name.split("/")[-1]
            if info.file_size < _MIN_BYTES:
                out[key] = ""
                continue
            out[key] = _ocr_one(z.read(name), Path(name).suffix, per_image_timeout)
    return out


def _ocr_one(data: bytes, suffix: str, timeout: int) -> str:
    with tempfile.TemporaryDirectory(prefix="docxocr_") as tmp:
        src = Path(tmp) / f"img{suffix}"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                [TESSERACT, str(src), "stdout", "-l", "eng", "--psm", "6"],
                capture_output=True, timeout=timeout, check=False,
                env={"PATH": "/usr/bin:/bin", "OMP_THREAD_LIMIT": "1"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("OCR skipped for one image: %s", exc)
            return ""
        if proc.returncode != 0:
            return ""
        recognised = " ".join(
            proc.stdout.decode("utf-8", "replace").split()
        ).strip()
        return recognised if len(recognised) >= _MIN_CHARS else ""
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_ocr.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Measure OCR against a real document, so the upload timeout is chosen from evidence**

```bash
.venv/bin/python - <<'PY'
import time
from pathlib import Path
from app.services.docx import ocr
for name in sorted(p.name for p in Path("data/samples").glob("*.docx")):
    data = Path("data/samples", name).read_bytes()
    t0 = time.time()
    result = ocr.ocr_document(data)
    nonempty = sum(1 for v in result.values() if v)
    print(f"{name:52s} images={len(result):3d} withtext={nonempty:3d} {time.time()-t0:6.1f}s")
PY
```

Record the slowest figure. If any document exceeds 120 s, lower `max_images` in the upload route (Task 12) rather than raising the request timeout — an administrator waiting two minutes on an upload is already too long.

- [ ] **Step 6: Commit**

```bash
git add app/services/docx/ocr.py tests/docx/test_ocr.py
git commit -m "feat(docx): tesseract OCR of embedded template images"
```

---

### Task 6: `docx/index.py` — detect and refresh the index

**Files:**
- Create: `app/services/docx/index.py`
- Create: `tests/docx/test_index.py`

**Interfaces:**
- Consumes: `docx.text` (Task 2), `docx.convert` (Task 1).
- Produces:
  - `detect(doc) -> str` — `"field" | "static" | "none"`.
  - `static_entries(doc) -> list[Entry]`, `Entry` = `{path, label, anchor, page_text}`.
  - `mark_fields_dirty(doc) -> None` — sets `<w:updateFields w:val="true"/>`.
  - `refresh_static(docx_bytes: bytes) -> bytes` — two-pass page-number refresh; returns the document unchanged when `detect` is not `"static"`.
  - `heading_pages(pdf_bytes, labels) -> dict[str, int]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_index.py
import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import index as ix


def _toc_paragraph(doc, style, label, page, anchor):
    p = doc.add_paragraph()
    ppr = p._p.get_or_add_pPr()
    ps = OxmlElement("w:pStyle"); ps.set(qn("w:val"), style); ppr.append(ps)
    link = OxmlElement("w:hyperlink"); link.set(qn("w:anchor"), anchor)
    for chunk in (label, page):
        r = OxmlElement("w:r"); t = OxmlElement("w:t")
        t.text = chunk; t.set(qn("xml:space"), "preserve"); r.append(t); link.append(r)
    p._p.append(link)
    return p


def _static_toc_docx() -> bytes:
    doc = Document()
    doc.add_paragraph("Table of Contents")
    _toc_paragraph(doc, "TOC1", "About YuviPep", "2", "_bookmark0")
    _toc_paragraph(doc, "TOC2", "Pricing Structure", "4", "_bookmark1")
    doc.add_page_break()
    doc.add_heading("About YuviPep", level=1)
    doc.add_paragraph("Body. " * 400)
    doc.add_page_break()
    doc.add_heading("Pricing Structure", level=1)
    doc.add_paragraph("More body. " * 400)
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def test_detects_no_index():
    doc = Document()
    doc.add_paragraph("Nothing indexed here.")
    buf = io.BytesIO(); doc.save(buf)
    assert ix.detect(Document(io.BytesIO(buf.getvalue()))) == "none"


def test_detects_a_static_index():
    assert ix.detect(Document(io.BytesIO(_static_toc_docx()))) == "static"


def test_detects_a_real_toc_field():
    doc = Document()
    p = doc.add_paragraph()
    r = OxmlElement("w:r")
    instr = OxmlElement("w:instrText")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    r.append(instr); p._p.append(r)
    buf = io.BytesIO(); doc.save(buf)
    assert ix.detect(Document(io.BytesIO(buf.getvalue()))) == "field"


def test_static_entries_carry_label_anchor_and_page():
    entries = ix.static_entries(Document(io.BytesIO(_static_toc_docx())))
    assert [e["label"] for e in entries] == ["About YuviPep", "Pricing Structure"]
    assert [e["anchor"] for e in entries] == ["_bookmark0", "_bookmark1"]
    assert [e["page_text"] for e in entries] == ["2", "4"]


def test_mark_fields_dirty_is_idempotent():
    doc = Document()
    ix.mark_fields_dirty(doc)
    ix.mark_fields_dirty(doc)
    found = doc.settings.element.findall(qn("w:updateFields"))
    assert len(found) == 1
    assert found[0].get(qn("w:val")) == "true"


def test_heading_pages_skips_the_pages_the_index_itself_sits_on():
    # 'Pricing Structure' appears on the contents page AND on its own page.
    pages = ["Table of Contents About YuviPep 2 Pricing Structure 4",
             "About YuviPep body",
             "Pricing Structure body"]
    mapping = ix.heading_pages_from_pages(pages, ["About YuviPep", "Pricing Structure"])
    assert mapping == {"About YuviPep": 2, "Pricing Structure": 3}


def test_refresh_static_rewrites_stale_page_numbers():
    refreshed = ix.refresh_static(_static_toc_docx())
    entries = ix.static_entries(Document(io.BytesIO(refreshed)))
    assert [e["page_text"] for e in entries] != ["2", "4"]
    assert all(e["page_text"].strip().isdigit() for e in entries)


def test_refresh_static_is_a_no_op_without_a_static_index():
    doc = Document(); doc.add_paragraph("Plain document.")
    buf = io.BytesIO(); doc.save(buf)
    data = buf.getvalue()
    assert ix.refresh_static(data) == data
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_index.py -q
```

Expected: `cannot import name 'index'`.

- [ ] **Step 3: Implement**

```python
# app/services/docx/index.py
"""Detect a document's index and keep it honest after a fill.

Measured against the four real templates on 2026-09-03: three have no index,
and `School_YuviPep 360_2 1.docx` has a **static** one — a `w:sdt` with
`docPartGallery="Table of Contents"` wrapping 32 paragraphs styled TOC1/TOC2/
TOC3, each an internal hyperlink to `_bookmarkN` whose page number is literal
text. `w:instrText` nodes: 0. `w:fldSimple`: 0.

So `w:updateFields` refreshes nothing for this corpus, and the two-pass
LibreOffice route is the primary mechanism rather than a fallback. The `field`
branch is kept because a future upload may genuinely contain a TOC field.
"""
from __future__ import annotations

import io
import re

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import convert
from app.services.docx import text as dt

W_PPR = qn("w:pPr")
W_PSTYLE = qn("w:pStyle")
W_INSTR = qn("w:instrText")
W_FLDSIMPLE = qn("w:fldSimple")
W_HYPERLINK = qn("w:hyperlink")
W_UPDATEFIELDS = qn("w:updateFields")

_TOC_STYLE = re.compile(r"^TOC\d?$", re.IGNORECASE)
_TOC_HEADINGS = {"table of contents", "contents", "index"}
_WS = re.compile(r"\s+")


def _style_of(p) -> str:
    ppr = p.find(W_PPR)
    if ppr is None:
        return ""
    node = ppr.find(W_PSTYLE)
    return (node.get(qn("w:val")) or "") if node is not None else ""


def detect(doc) -> str:
    for root in dt.all_roots(doc):
        for instr in root.iter(W_INSTR):
            if "TOC" in (instr.text or ""):
                return "field"
        for simple in root.iter(W_FLDSIMPLE):
            if "TOC" in (simple.get(qn("w:instr")) or ""):
                return "field"
    body = doc.element.body
    for p in dt.iter_paragraphs(body):
        if _TOC_STYLE.fullmatch(_style_of(p)):
            return "static"
    for p in dt.iter_paragraphs(body):
        if dt.node_text(p).strip().lower() in _TOC_HEADINGS:
            return "static"
    return "none"


def static_entries(doc) -> list[dict]:
    """TOC-styled paragraphs, with their label, anchor and page-number node.

    The final `w:t` of the paragraph is the page number; everything before it
    is the label. That holds for the real document and for the shape Word and
    LibreOffice both emit.
    """
    entries: list[dict] = []
    for p_i, p in enumerate(dt.iter_paragraphs(doc.element.body)):
        if not _TOC_STYLE.fullmatch(_style_of(p)):
            continue
        nodes = dt.own_text_nodes(p)
        if len(nodes) < 2:
            continue
        anchor = None
        for link in p.iter(W_HYPERLINK):
            anchor = link.get(qn("w:anchor"))
            break
        label = "".join(t.text or "" for t in nodes[:-1]).strip()
        entries.append({
            "index": p_i,
            "label": _WS.sub(" ", label),
            "anchor": anchor,
            "page_text": nodes[-1].text or "",
        })
    return entries


def mark_fields_dirty(doc) -> None:
    settings = doc.settings.element
    existing = settings.find(W_UPDATEFIELDS)
    if existing is None:
        existing = OxmlElement("w:updateFields")
        settings.append(existing)
    existing.set(qn("w:val"), "true")


def _norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip().lower()


def heading_pages_from_pages(pages: list[str], labels: list[str]) -> dict[str, int]:
    """Map each label to its 1-based page, ignoring the index's own pages.

    Without that exclusion every label resolves to the contents page, because
    the contents page contains all of them. Measured on the real 29-page
    output: 'Investment and Deliverables' matches pages [2, 27]; 2 is the
    index and 27 is the answer.
    """
    normalised = [_norm(p) for p in pages]
    wanted = [_norm(l) for l in labels if l.strip()]
    index_pages = {
        i for i, page in enumerate(normalised)
        if sum(1 for w in wanted if w and w in page) >= max(3, len(wanted) // 2)
    }
    out: dict[str, int] = {}
    for label in labels:
        needle = _norm(label)
        if not needle:
            continue
        for i, page in enumerate(normalised):
            if i in index_pages:
                continue
            if needle in page:
                out[label] = i + 1
                break
    return out


def heading_pages(pdf_bytes: bytes, labels: list[str]) -> dict[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return heading_pages_from_pages(pages, labels)


def refresh_static(docx_bytes: bytes, *, timeout: int = 120) -> bytes:
    """Rewrite a static index's page numbers from a trial PDF render.

    Pass one converts and reads page positions; pass two writes them back. The
    caller converts again afterwards for the PDF it actually ships.
    """
    doc = Document(io.BytesIO(docx_bytes))
    if detect(doc) != "static":
        return docx_bytes
    entries = static_entries(doc)
    if not entries:
        return docx_bytes

    pdf = convert.docx_to_pdf(docx_bytes, timeout=timeout)
    mapping = heading_pages(pdf, [e["label"] for e in entries])
    if not mapping:
        return docx_bytes

    changed = False
    toc_paragraphs = [
        p for p in dt.iter_paragraphs(doc.element.body)
        if _TOC_STYLE.fullmatch(_style_of(p))
    ]
    for entry, p in zip(entries, toc_paragraphs):
        page = mapping.get(entry["label"])
        if page is None:
            continue
        nodes = dt.own_text_nodes(p)
        if not nodes:
            continue
        if (nodes[-1].text or "").strip() != str(page):
            nodes[-1].text = str(page)
            changed = True
    if not changed:
        return docx_bytes
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_index.py -q
```

Expected: 8 passed. `test_refresh_static_rewrites_stale_page_numbers` invokes LibreOffice, so it takes a few seconds.

- [ ] **Step 5: Add the golden index test**

Append to `tests/docx/test_golden_samples.py`:

```python
from app.services.docx import index as ix

EXPECTED_INDEX = {
    "Essential Lab.docx": "none",
    "Innovation Lab Template.docx": "none",
    "School_YuviPep 360_2 1.docx": "static",
    "School_YuviPep 360 EmpowerED_New_compressed.docx": "none",
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_index_kind_matches_what_was_measured(name):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    assert ix.detect(Document(str(path))) == EXPECTED_INDEX[name]


def test_the_static_index_yields_its_thirty_two_entries():
    path = SAMPLES_DIR / "School_YuviPep 360_2 1.docx"
    if not path.exists():
        pytest.skip("sample not present")
    entries = ix.static_entries(Document(str(path)))
    assert len(entries) == 32
    assert entries[0]["label"].startswith("ABOUT YUVIPEP")
    assert entries[0]["anchor"] == "_bookmark0"
    assert all(e["page_text"].strip().isdigit() for e in entries)
```

- [ ] **Step 6: Run and commit**

```bash
.venv/bin/python -m pytest tests/docx/test_golden_samples.py -q
git add app/services/docx/index.py tests/docx/test_index.py tests/docx/test_golden_samples.py
git commit -m "feat(docx): index detection and static TOC page refresh"
```

---

### Task 7: `docx/edit.py` — structural edits

**Files:**
- Create: `app/services/docx/edit.py`
- Create: `tests/docx/test_edit.py`

**Interfaces:**
- Consumes: `docx.text` (Task 2), `docx.outline` (Task 4).
- Produces:
  - `insert_paragraphs_after(doc, anchor_path, style_ref_path, texts, *, list_style=None) -> list`
  - `insert_paragraphs_before(doc, anchor_path, style_ref_path, texts, *, list_style=None) -> list`
  - `set_paragraph_text(doc, path, text) -> None`
  - `set_cell_text(doc, table_path, row, col, text) -> None`
  - `fill_table(doc, table_path, rows, *, header_rows, total_row, columns) -> None`
  - `remove_paragraph(doc, path) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_edit.py
import io

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.services.docx import edit, outline as ol, text as dt


def _styled_docx() -> bytes:
    doc = Document()
    doc.add_heading("Pricing Overview", level=1)          # body[0]
    p = doc.add_paragraph("An existing body paragraph with real formatting.")  # body[1]
    p.runs[0].bold = True
    doc.add_paragraph("Another paragraph.")               # body[2]
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def _reopen(doc) -> Document:
    buf = io.BytesIO(); doc.save(buf)
    return Document(io.BytesIO(buf.getvalue()))


def test_inserts_a_paragraph_directly_after_the_anchor():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_after(doc, "body[0]", "body[1]", ["Inserted sentence."])
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert texts[1] == "Inserted sentence."
    assert texts[2] == "An existing body paragraph with real formatting."


def test_inserted_paragraph_inherits_the_reference_run_formatting():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_after(doc, "body[0]", "body[1]", ["Inserted."])
    reopened = _reopen(doc)
    inserted = [p for p in reopened.paragraphs if p.text == "Inserted."][0]
    assert inserted.runs[0].bold is True


def test_inserts_several_paragraphs_in_order():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_after(doc, "body[0]", "body[1]", ["One.", "Two.", "Three."])
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert texts[1:4] == ["One.", "Two.", "Three."]


def test_inserts_before_the_anchor():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.insert_paragraphs_before(doc, "body[2]", "body[1]", ["Before."])
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert texts[2] == "Before."


def test_set_paragraph_text_keeps_the_paragraph_style():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.set_paragraph_text(doc, "body[1]", "Replaced wording, same look.")
    reopened = _reopen(doc)
    para = [p for p in reopened.paragraphs if p.text == "Replaced wording, same look."][0]
    assert para.runs[0].bold is True


def test_editing_refuses_an_anchor_that_does_not_exist():
    doc = Document(io.BytesIO(_styled_docx()))
    with pytest.raises(ol.AnchorError):
        edit.set_paragraph_text(doc, "body[99]", "nope")


def test_set_cell_text_writes_one_cell(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.set_cell_text(doc, table_path, 1, 1, "Rs 8,50,000")
    assert doc.tables[0].cell(1, 1).text == "Rs 8,50,000"


def test_fill_table_expands_rows_and_writes_the_total(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(
        doc, table_path,
        rows=[["Innovation Lab", "Rs 8,50,000"],
              ["Annual Support", "Rs 1,20,000"],
              ["Teacher Training", "Rs 40,000"]],
        header_rows=1,
        total_row={"label_col": 0, "value_col": 1, "value": "Rs 10,10,000"},
        columns=[0, 1],
    )
    t = doc.tables[0]
    assert len(t.rows) == 5                       # 1 header + 3 body + 1 total
    assert t.cell(0, 0).text == "Description"     # header untouched
    assert t.cell(3, 0).text == "Teacher Training"
    assert t.cell(4, 0).text == "Total"           # total label kept
    assert t.cell(4, 1).text == "Rs 10,10,000"


def test_fill_table_contracts_when_there_are_fewer_rows(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(
        doc, table_path, rows=[["Only Item", "Rs 100"]],
        header_rows=1, total_row={"label_col": 0, "value_col": 1, "value": "Rs 100"},
        columns=[0, 1],
    )
    t = doc.tables[0]
    assert len(t.rows) == 3
    assert t.cell(1, 0).text == "Only Item"
    assert t.cell(2, 1).text == "Rs 100"


def test_fill_table_without_a_total_row_leaves_only_body_rows(table_docx):
    doc = Document(io.BytesIO(table_docx))
    table_path = next(
        b["path"] for b in ol.parse(table_docx)["blocks"] if b["kind"] == "table"
    )
    edit.fill_table(doc, table_path, rows=[["A", "1"], ["B", "2"]],
                    header_rows=1, total_row=None, columns=[0, 1])
    assert len(doc.tables[0].rows) == 3


def test_remove_paragraph_drops_it():
    doc = Document(io.BytesIO(_styled_docx()))
    edit.remove_paragraph(doc, "body[2]")
    texts = [dt.node_text(p) for p in doc.element.body.iterchildren() if p.tag == qn("w:p")]
    assert "Another paragraph." not in texts
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_edit.py -q
```

Expected: `cannot import name 'edit'`.

- [ ] **Step 3: Implement**

```python
# app/services/docx/edit.py
"""Structural edits to a loaded document.

Everything here mutates a document that was loaded from the immutable source
file. Nothing constructs a paragraph from scratch: a new paragraph is a clone
of a real one in the same document, stripped of its content, so it inherits
that document's font, size, spacing, justification and theme without this
module knowing any of them.

This is what keeps generated prose visually indistinguishable from the
template's own body text — and it is why the model can be asked for plain text
rather than any markup.
"""
from __future__ import annotations

import copy

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.docx import outline as ol
from app.services.docx import text as dt

W_P = qn("w:p")
W_TBL = qn("w:tbl")
W_TR = qn("w:tr")
W_TC = qn("w:tc")
W_PPR = qn("w:pPr")
W_R = qn("w:r")
W_RPR = qn("w:rPr")
W_PSTYLE = qn("w:pStyle")
W_NUMPR = qn("w:numPr")
XML_SPACE = qn("xml:space")


def _blank_clone(style_ref_p, text: str, list_style: str | None):
    """A paragraph shaped like `style_ref_p`, carrying exactly `text`."""
    new_p = copy.deepcopy(style_ref_p)
    for child in list(new_p):
        if child.tag != W_PPR:
            new_p.remove(child)
    if list_style:
        ppr = new_p.find(W_PPR)
        if ppr is None:
            ppr = OxmlElement("w:pPr")
            new_p.insert(0, ppr)
        for existing in ppr.findall(W_PSTYLE):
            ppr.remove(existing)
        for existing in ppr.findall(W_NUMPR):
            ppr.remove(existing)
        style_el = OxmlElement("w:pStyle")
        style_el.set(qn("w:val"), list_style)
        ppr.insert(0, style_el)

    run = OxmlElement("w:r")
    src_run = style_ref_p.find(W_R)
    if src_run is not None:
        src_rpr = src_run.find(W_RPR)
        if src_rpr is not None:
            run.append(copy.deepcopy(src_rpr))
    t = OxmlElement("w:t")
    t.text = text
    t.set(XML_SPACE, "preserve")
    run.append(t)
    new_p.append(run)
    return new_p


def _insert(doc, anchor_path, style_ref_path, texts, list_style, before):
    anchor = ol.resolve(doc, anchor_path)
    style_ref = ol.resolve(doc, style_ref_path)
    if style_ref.tag != W_P:
        raise ol.AnchorError(
            f"The style reference '{style_ref_path}' is not a paragraph, so "
            "there is no formatting to copy."
        )
    created = []
    if before:
        for text in texts:
            new_p = _blank_clone(style_ref, text, list_style)
            anchor.addprevious(new_p)
            created.append(new_p)
    else:
        cursor = anchor
        for text in texts:
            new_p = _blank_clone(style_ref, text, list_style)
            cursor.addnext(new_p)
            cursor = new_p
            created.append(new_p)
    return created


def insert_paragraphs_after(doc, anchor_path, style_ref_path, texts, *, list_style=None):
    return _insert(doc, anchor_path, style_ref_path, list(texts), list_style, before=False)


def insert_paragraphs_before(doc, anchor_path, style_ref_path, texts, *, list_style=None):
    return _insert(doc, anchor_path, style_ref_path, list(texts), list_style, before=True)


def set_paragraph_text(doc, path: str, text: str) -> None:
    p = ol.resolve(doc, path)
    if p.tag != W_P:
        raise ol.AnchorError(f"'{path}' is not a paragraph")
    _write_paragraph_text(p, text)


def _write_paragraph_text(p, text: str) -> None:
    current = dt.node_text(p)
    if current:
        dt.replace_span(p, 0, len(current), text)
        return
    run = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    t.set(XML_SPACE, "preserve")
    run.append(t)
    p.append(run)


def _table_at(doc, path: str):
    tbl = ol.resolve(doc, path)
    if tbl.tag != W_TBL:
        raise ol.AnchorError(f"'{path}' is not a table")
    return tbl


def _cell_paragraphs(tc):
    return tc.findall(W_P)


def _write_cell(tc, text: str) -> None:
    paragraphs = _cell_paragraphs(tc)
    if not paragraphs:
        p = OxmlElement("w:p")
        tc.append(p)
        paragraphs = [p]
    _write_paragraph_text(paragraphs[0], text)
    for extra in paragraphs[1:]:
        tc.remove(extra)


def set_cell_text(doc, table_path: str, row: int, col: int, text: str) -> None:
    tbl = _table_at(doc, table_path)
    rows = tbl.findall(W_TR)
    if row >= len(rows):
        raise ol.AnchorError(f"Row {row} is out of range for the table at '{table_path}'")
    cells = rows[row].findall(W_TC)
    if col >= len(cells):
        raise ol.AnchorError(f"Column {col} is out of range for the table at '{table_path}'")
    _write_cell(cells[col], text)


def fill_table(doc, table_path: str, rows, *, header_rows: int,
               total_row: dict | None, columns: list[int]) -> None:
    """Write body rows into an existing table, keeping its styling.

    Body rows are cloned from the template's own first body row, so borders,
    shading and fonts come from the document rather than from this code. The
    header rows are never touched. A total row keeps its label and gets only
    its value written — the label is the organisation's wording, not ours.
    """
    tbl = _table_at(doc, table_path)
    tr_list = tbl.findall(W_TR)
    if len(tr_list) <= header_rows:
        raise ol.AnchorError(
            f"The table at '{table_path}' has no body row to use as a template."
        )

    total_tr = tr_list[-1] if total_row else None
    body_trs = tr_list[header_rows:len(tr_list) - (1 if total_row else 0)]
    if not body_trs:
        raise ol.AnchorError(
            f"The table at '{table_path}' has no body row to use as a template."
        )

    template_tr = copy.deepcopy(body_trs[0])
    for tr in body_trs:
        tbl.remove(tr)

    anchor = tr_list[header_rows - 1] if header_rows else None
    cursor = anchor
    for values in rows:
        new_tr = copy.deepcopy(template_tr)
        cells = new_tr.findall(W_TC)
        for position, col in enumerate(columns):
            if col < len(cells) and position < len(values):
                _write_cell(cells[col], str(values[position]))
        for idx, tc in enumerate(cells):
            if idx not in columns:
                _write_cell(tc, "")
        if cursor is None:
            tbl.insert(0, new_tr)
        else:
            cursor.addnext(new_tr)
        cursor = new_tr

    if total_row and total_tr is not None:
        cells = total_tr.findall(W_TC)
        value_col = total_row["value_col"]
        if value_col < len(cells):
            _write_cell(cells[value_col], str(total_row["value"]))


def remove_paragraph(doc, path: str) -> None:
    p = ol.resolve(doc, path)
    parent = p.getparent()
    if parent is not None:
        parent.remove(p)
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_edit.py -q
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/docx/edit.py tests/docx/test_edit.py
git commit -m "feat(docx): structural edits with formatting inherited from the document"
```

---

### Task 8: `fill_scrub.py` — the deterministic fence

Written before the module that calls a model, so the fence exists before anything can get past it.

**Files:**
- Create: `app/services/fill_scrub.py`
- Create: `tests/docx/test_scrub.py`

**Interfaces:**
- Consumes: `app.services.draft_check`, `app.services.proposal_service._allowed_amounts`.
- Produces:
  - `scrub(text: str, *, brief: str, max_words: int, allowed_amounts: set[float]) -> list[str]` — the reasons this text is unacceptable; empty means clean.
  - `REJECTION_MARKDOWN`, `REJECTION_META`, `REJECTION_BRIEF_ECHO`, `REJECTION_PRICE`, `REJECTION_LENGTH`, `REJECTION_BLANK` — the reason constants.

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_scrub.py
from app.services import fill_scrub as fs

BRIEF = "A two to three sentence opening greeting from YuviPep to the client."
ALLOWED = {850000.0, 120000.0, 970000.0, 12.0}


def clean(text, **kw):
    return fs.scrub(text, brief=BRIEF, max_words=90, allowed_amounts=ALLOWED, **kw)


def test_accepts_ordinary_prose():
    assert clean(
        "We are delighted to present this proposal to Greenwood International "
        "School. Following our conversation last week, we have shaped the "
        "programme around your Grade 6 to 8 cohort."
    ) == []


def test_rejects_bold_markers():
    assert fs.REJECTION_MARKDOWN in clean("We are **delighted** to present this.")


def test_rejects_heading_markers():
    assert fs.REJECTION_MARKDOWN in clean("## Introduction\nWe are delighted.")


def test_rejects_bullet_markers():
    assert fs.REJECTION_MARKDOWN in clean("- First point\n- Second point")


def test_rejects_table_pipes():
    assert fs.REJECTION_MARKDOWN in clean("| Item | Price |\n| Lab | 100 |")


def test_rejects_a_model_narrating_its_own_task():
    for opener in (
        "I will now draft the greeting paragraph for the client.",
        "Here is the opening paragraph you requested.",
        "Certainly! Below is the greeting.",
        "As requested, the following paragraph introduces YuviPep.",
    ):
        assert fs.REJECTION_META in clean(opener), opener


def test_rejects_a_fill_in_the_blank():
    assert fs.REJECTION_META in clean("Dear [Name], we are delighted to present this.")


def test_rejects_text_that_merely_restates_its_brief():
    assert fs.REJECTION_BRIEF_ECHO in clean(
        "A two to three sentence opening greeting from YuviPep to the client."
    )


def test_rejects_a_price_not_in_the_locked_commercials():
    assert fs.REJECTION_PRICE in clean(
        "We are pleased to offer this at a total cost of Rs 7,45,000 for the year."
    )


def test_accepts_a_price_that_is_in_the_locked_commercials():
    assert fs.REJECTION_PRICE not in clean(
        "The total investment is Rs 970000 for the full programme."
    )


def test_accepts_a_year_that_is_not_money():
    assert clean("YuviPep has worked with schools since 2019 across India.") == []


def test_rejects_text_over_the_word_budget():
    assert fs.REJECTION_LENGTH in fs.scrub(
        "word " * 200, brief=BRIEF, max_words=90, allowed_amounts=ALLOWED
    )


def test_rejects_empty_text():
    assert fs.REJECTION_BLANK in clean("   ")


def test_reports_every_reason_at_once():
    reasons = clean("I will now write **this**. Cost is Rs 7,45,000.")
    assert fs.REJECTION_META in reasons
    assert fs.REJECTION_MARKDOWN in reasons
    assert fs.REJECTION_PRICE in reasons
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_scrub.py -q
```

Expected: `No module named 'app.services.fill_scrub'`.

- [ ] **Step 3: Implement**

```python
# app/services/fill_scrub.py
"""The fence between a model's prose and a client's document.

Four times this project has watched a model ignore an instruction it was given
in capitals — F9, F4, F23, F28. The prompt asking for clean, grounded prose is
worth having; it is the hint. This module is the guard.

It is deliberately narrow. A false rejection costs one retry and, at worst, an
honest blank that a human is told about. A false acceptance is a client reading
"I will now draft the greeting paragraph" in a document with our name on it.
"""
from __future__ import annotations

import re

from app.services import draft_check

REJECTION_MARKDOWN = "markdown_markers"
REJECTION_META = "meta_instruction"
REJECTION_BRIEF_ECHO = "restates_the_brief"
REJECTION_PRICE = "unlocked_price"
REJECTION_LENGTH = "too_long"
REJECTION_BLANK = "empty"

# Markdown the DOCX path can never render: it would be printed literally.
_MARKDOWN = (
    re.compile(r"\*\*|__"),                       # bold
    re.compile(r"(?m)^\s{0,3}#{1,6}\s"),          # ATX headings
    re.compile(r"(?m)^\s{0,3}[-*+]\s"),           # bullet lists
    re.compile(r"(?m)^\s{0,3}\d+[.)]\s"),         # ordered lists
    re.compile(r"\|.*\|"),                        # table rows
    re.compile(r"`{1,3}"),                        # code spans
    re.compile(r"(?m)^\s{0,3}>\s"),               # block quotes
)

# A model that is describing the work instead of doing it.
_META = re.compile(
    r"^\s*(?:certainly|sure|of course|okay|ok)\b"
    r"|^\s*(?:here(?:'s| is)|below is|the following|this is)\b"
    r"|^\s*(?:as requested|as instructed|as you asked)\b"
    r"|\bI (?:will|'ll|can|have|shall) (?:now )?(?:write|draft|create|generate|"
    r"produce|prepare|provide|add|insert)\b"
    r"|\b(?:placeholder|to be (?:filled|completed)|fill in (?:the|this))\b",
    re.IGNORECASE,
)

_MONEY_MARKERS = ("rs", "₹", "inr", "usd", "eur", "$")
_PRICE_WORDS = (
    "per ", "price", "cost", "fee", "total", "discount", "rate", "charge",
    "amount", "invest", "each", "subtotal", "quote", "pricing", "sum",
)
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_WORD_RE = re.compile(r"\S+")
_TOKEN_RE = re.compile(r"[a-z]{4,}")


def _markdown_reasons(text: str) -> bool:
    return any(pattern.search(text) for pattern in _MARKDOWN)


def _meta_reasons(text: str) -> bool:
    if _META.search(text):
        return True
    # this project's own blank markers: [Name], [Insert Date], {client_name}
    return bool(draft_check.find_blanks(text))


def _echoes_brief(text: str, brief: str) -> bool:
    """The first sentence is largely the brief read back.

    Jaccard over content words of length >= 4, which ignores articles and
    prepositions without needing a stopword list.
    """
    if not brief.strip():
        return False
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    a = set(_TOKEN_RE.findall(first.lower()))
    b = set(_TOKEN_RE.findall(brief.lower()))
    if len(b) < 3 or not a:
        return False
    overlap = len(a & b) / len(a | b)
    return overlap >= 0.6


def _unlocked_price(text: str, allowed: set[float]) -> bool:
    """A money-shaped number that is not one of the locked commercials.

    Same window logic as `proposal_service.narrative_price_drift`: a number
    only counts when a currency marker or a price word sits beside it, so a
    cohort size or a year is not mistaken for a rupee figure.
    """
    low = text.lower()
    for match in _NUMBER_RE.finditer(text):
        raw = match.group(0)
        value = float(raw.replace(",", ""))
        if value < 100:
            continue
        if round(value, 2) in allowed:
            continue
        if 1900 <= value <= 2100 and "," not in raw and "." not in raw:
            continue
        window = low[max(0, match.start() - 16):min(len(low), match.end() + 16)]
        if any(m in window for m in _MONEY_MARKERS) or any(w in window for w in _PRICE_WORDS):
            return True
    return False


def scrub(text: str, *, brief: str, max_words: int,
          allowed_amounts: set[float]) -> list[str]:
    """Every reason this text must not go into the document. Empty is clean."""
    reasons: list[str] = []
    if not (text or "").strip():
        return [REJECTION_BLANK]
    if _markdown_reasons(text):
        reasons.append(REJECTION_MARKDOWN)
    if _meta_reasons(text):
        reasons.append(REJECTION_META)
    if _echoes_brief(text, brief):
        reasons.append(REJECTION_BRIEF_ECHO)
    if _unlocked_price(text, allowed_amounts):
        reasons.append(REJECTION_PRICE)
    if max_words and len(_WORD_RE.findall(text)) > max_words:
        reasons.append(REJECTION_LENGTH)
    return reasons
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_scrub.py -q
```

Expected: 14 passed.

- [ ] **Step 5: Check the fence against the real failure this feature exists to stop**

```bash
.venv/bin/python - <<'PY'
from app.services import fill_scrub as fs
brief = "A short opening greeting to the client."
samples = [
    "I will now write the greeting paragraph for this school.",
    "Here is the pricing summary you asked for.",
    "**Dear Principal**, we are delighted to present this proposal.",
    "Dear Principal, we are delighted to present this proposal.",
]
for s in samples:
    print(f"{str(fs.scrub(s, brief=brief, max_words=90, allowed_amounts=set())):45s} {s}")
PY
```

Expected: the first three report reasons, the fourth reports `[]`.

- [ ] **Step 6: Commit**

```bash
git add app/services/fill_scrub.py tests/docx/test_scrub.py
git commit -m "feat: deterministic scrubber for model-written proposal prose"
```

---

### Task 9: `docx/fill.py` — apply a whole fill plan

**Files:**
- Create: `app/services/docx/fill.py`
- Create: `tests/docx/test_fill.py`

**Interfaces:**
- Consumes: `docx.text`, `docx.outline`, `docx.edit`, `docx.index`.
- Produces:
  - `apply(docx_bytes: bytes, plan: dict, values: dict[str, Any]) -> FillResult`
  - `FillResult` = `{"docx": bytes, "filled": list[dict], "unfilled": list[str]}`
  - `validate_plan(plan: dict, outline: dict) -> list[str]` — human-readable problems; empty means the plan is coherent with the outline.
  - `PLAN_KINDS = ("token", "table", "insert", "replace")`

Plan shape, exactly as stored in `proposal_template_docs.plan_json`:

```python
{
  "version": 1,
  "entries": [
    {"kind": "token", "key": "client_name", "literal": "School Name"},
    {"kind": "table", "key": "pricing_table", "path": "body[32]",
     "fingerprint": "sha256:...", "columns": [{"col": 0, "field": "label"},
                                              {"col": 1, "field": "line_total"}],
     "header_rows": 1,
     "total_row": {"label_col": 0, "value_col": 1}},
    {"kind": "insert", "key": "greeting_para", "after": "body[5]",
     "fingerprint": "sha256:...", "style_ref": "body[8]", "shape": "paragraph",
     "brief": "...", "max_words": 90, "required": True},
    {"kind": "replace", "key": "why_us", "path": "body[20]",
     "fingerprint": "sha256:...", "brief": "...", "max_words": 120,
     "required": False}
  ]
}
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_fill.py
import io

import pytest
from docx import Document

from app.services.docx import fill, outline as ol, text as dt


def _template_docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal for School Name", level=1)   # body[0]
    doc.add_paragraph("A body paragraph of a reasonable length for cloning.")  # body[1]
    doc.add_paragraph("Prepared for School Name by YuviPep.")                  # body[2]
    t = doc.add_table(rows=3, cols=2)                                          # body[3]
    t.style = "Table Grid"
    t.cell(0, 0).text = "Description"; t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Item";        t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total";       t.cell(2, 1).text = "Rs 0"
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def _plan(data):
    out = ol.parse(data)
    by_path = {b["path"]: b for b in out["blocks"]}
    table_path = next(b["path"] for b in out["blocks"] if b["kind"] == "table")
    return out, {
        "version": 1,
        "entries": [
            {"kind": "token", "key": "client_name", "literal": "School Name"},
            {"kind": "insert", "key": "greeting", "after": "body[0]",
             "fingerprint": by_path["body[0]"]["fingerprint"],
             "style_ref": "body[1]", "shape": "paragraph",
             "brief": "Opening greeting.", "max_words": 90, "required": True},
            {"kind": "replace", "key": "why_us", "path": "body[2]",
             "fingerprint": by_path["body[2]"]["fingerprint"],
             "brief": "Why us.", "max_words": 120, "required": False},
            {"kind": "table", "key": "pricing_table", "path": table_path,
             "fingerprint": by_path[table_path]["fingerprint"],
             "columns": [{"col": 0, "field": "label"},
                         {"col": 1, "field": "line_total"}],
             "header_rows": 1,
             "total_row": {"label_col": 0, "value_col": 1}},
        ],
    }


VALUES = {
    "client_name": "Greenwood International School",
    "greeting": "We are delighted to present this proposal.",
    "why_us": "YuviPep has worked with two hundred schools.",
    "pricing_table": {
        "rows": [{"label": "Innovation Lab", "line_total": "Rs 8,50,000"},
                 {"label": "Annual Support", "line_total": "Rs 1,20,000"}],
        "total": "Rs 9,70,000",
    },
}


def test_applies_every_entry_kind():
    data = _template_docx()
    _, plan = _plan(data)
    result = fill.apply(data, plan, VALUES)
    doc = Document(io.BytesIO(result["docx"]))

    assert dt.count_token(doc, "School Name") == 0
    assert dt.count_token(doc, "Greenwood International School") == 2

    texts = [dt.node_text(p) for p in dt.iter_paragraphs(doc.element.body)]
    assert "We are delighted to present this proposal." in texts
    assert "YuviPep has worked with two hundred schools." in texts

    table = doc.tables[0]
    assert len(table.rows) == 4
    assert table.cell(0, 0).text == "Description"
    assert table.cell(2, 0).text == "Annual Support"
    assert table.cell(3, 1).text == "Rs 9,70,000"


def test_reports_what_it_filled_and_from_where():
    data = _template_docx()
    _, plan = _plan(data)
    result = fill.apply(data, plan, VALUES)
    by_key = {f["key"]: f for f in result["filled"]}
    assert by_key["client_name"]["source"] == "system"
    assert by_key["pricing_table"]["source"] == "system"
    assert by_key["greeting"]["source"] == "ai"
    assert by_key["greeting"]["text"] == "We are delighted to present this proposal."


def test_a_missing_value_leaves_the_placeholder_unfilled():
    data = _template_docx()
    _, plan = _plan(data)
    values = dict(VALUES); values.pop("greeting")
    result = fill.apply(data, plan, values)
    assert "greeting" in result["unfilled"]
    by_key = {f["key"]: f for f in result["filled"]}
    assert by_key["greeting"]["source"] == "unfilled"


def test_an_unfilled_optional_replace_leaves_the_original_wording():
    data = _template_docx()
    _, plan = _plan(data)
    values = dict(VALUES); values.pop("why_us")
    result = fill.apply(data, plan, values)
    doc = Document(io.BytesIO(result["docx"]))
    texts = [dt.node_text(p) for p in dt.iter_paragraphs(doc.element.body)]
    assert any("Prepared for Greenwood" in t for t in texts)


def test_multi_paragraph_shape_creates_one_paragraph_per_line():
    data = _template_docx()
    _, plan = _plan(data)
    plan["entries"][1]["shape"] = "paragraphs"
    values = dict(VALUES); values["greeting"] = "First para.\n\nSecond para."
    result = fill.apply(data, plan, values)
    doc = Document(io.BytesIO(result["docx"]))
    texts = [dt.node_text(p) for p in dt.iter_paragraphs(doc.element.body)]
    assert "First para." in texts and "Second para." in texts


def test_a_stale_anchor_is_refused_rather_than_written_to_the_wrong_place():
    data = _template_docx()
    _, plan = _plan(data)
    plan["entries"][1]["fingerprint"] = "sha256:0000000000000000"
    with pytest.raises(ol.AnchorError):
        fill.apply(data, plan, VALUES)


def test_the_source_document_is_not_modified():
    data = _template_docx()
    _, plan = _plan(data)
    fill.apply(data, plan, VALUES)
    assert dt.count_token(Document(io.BytesIO(data)), "School Name") == 2


def test_validate_plan_flags_an_unknown_entry_kind():
    data = _template_docx()
    out, plan = _plan(data)
    plan["entries"].append({"kind": "nonsense", "key": "x"})
    problems = fill.validate_plan(plan, out)
    assert any("nonsense" in p for p in problems)


def test_validate_plan_flags_a_duplicate_key():
    data = _template_docx()
    out, plan = _plan(data)
    plan["entries"].append({"kind": "token", "key": "client_name", "literal": "X"})
    assert any("client_name" in p for p in fill.validate_plan(plan, out))


def test_validate_plan_accepts_a_coherent_plan():
    data = _template_docx()
    out, plan = _plan(data)
    assert fill.validate_plan(plan, out) == []
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_fill.py -q
```

Expected: `cannot import name 'fill'`.

- [ ] **Step 3: Implement**

```python
# app/services/docx/fill.py
"""Apply a fill plan to a copy of the template. Pure and deterministic.

No model is called here. Values arrive already resolved — system-bound ones
from the database, prose from `app.ai.docx_prose` after it has passed the
scrubber — so this module can be reasoned about, tested and replayed without a
network. Given the same source, plan and values it produces the same document.

Order matters. Structural entries are applied first, from the END of the
document backwards, because inserting a paragraph at `body[5]` shifts every
later positional path by one. Token replacement runs last, over the whole
document, so it also reaches text that was just inserted.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from docx import Document

from app.services.docx import edit
from app.services.docx import index as ix
from app.services.docx import outline as ol
from app.services.docx import text as dt

logger = logging.getLogger(__name__)

PLAN_KINDS = ("token", "table", "insert", "replace")
_LIST_STYLE = "List Bullet"


def validate_plan(plan: dict, outline: dict) -> list[str]:
    problems: list[str] = []
    entries = plan.get("entries") or []
    known_paths = {b["path"] for b in outline["blocks"]}
    seen_keys: set[str] = set()

    for i, entry in enumerate(entries):
        kind = entry.get("kind")
        key = entry.get("key")
        where = f"entry {i + 1}"
        if kind not in PLAN_KINDS:
            problems.append(f"{where}: unknown placeholder kind '{kind}'")
            continue
        if not key:
            problems.append(f"{where}: has no key")
            continue
        if key in seen_keys:
            problems.append(f"{where}: '{key}' is used more than once")
        seen_keys.add(key)

        if kind == "token":
            if not entry.get("literal"):
                problems.append(f"{where} ('{key}'): no literal to replace")
        elif kind in ("table", "replace"):
            path = entry.get("path")
            if path not in known_paths:
                problems.append(f"{where} ('{key}'): '{path}' is not a block in this document")
        elif kind == "insert":
            anchor = entry.get("after") or entry.get("before")
            if anchor not in known_paths:
                problems.append(f"{where} ('{key}'): '{anchor}' is not a block in this document")
            if entry.get("style_ref") not in known_paths:
                problems.append(
                    f"{where} ('{key}'): style reference "
                    f"'{entry.get('style_ref')}' is not a block in this document"
                )
    return problems


def _paragraph_texts(value: Any, shape: str) -> list[str]:
    text = str(value).strip()
    if shape == "paragraph":
        return [" ".join(text.split())]
    parts = [" ".join(p.split()) for p in text.split("\n") if p.strip()]
    return parts or [text]


def apply(docx_bytes: bytes, plan: dict, values: dict[str, Any]) -> dict[str, Any]:
    doc = Document(io.BytesIO(docx_bytes))
    entries = list(plan.get("entries") or [])
    filled: list[dict[str, Any]] = []
    unfilled: list[str] = []

    structural = [e for e in entries if e["kind"] in ("insert", "replace", "table")]
    tokens = [e for e in entries if e["kind"] == "token"]

    # Verify every anchor BEFORE mutating anything, so a stale plan leaves the
    # document untouched rather than half-written.
    for entry in structural:
        path = entry.get("path") or entry.get("after") or entry.get("before")
        if entry.get("fingerprint"):
            ol.verify(doc, path, entry["fingerprint"])

    # Later blocks first: an insert shifts the positional paths after it.
    def order(entry):
        path = entry.get("path") or entry.get("after") or entry.get("before") or ""
        digits = "".join(ch if ch.isdigit() else " " for ch in path).split()
        return [int(d) for d in digits] or [0]

    for entry in sorted(structural, key=order, reverse=True):
        key = entry["key"]
        kind = entry["kind"]
        value = values.get(key)

        if kind == "table":
            if not value:
                unfilled.append(key)
                filled.append({"key": key, "kind": kind, "source": "unfilled",
                               "text": "", "brief": "", "anchor": entry.get("path")})
                continue
            columns = [c["col"] for c in entry["columns"]]
            fields = [c["field"] for c in entry["columns"]]
            rows = [[row.get(f, "") for f in fields] for row in value["rows"]]
            total = entry.get("total_row")
            total_row = None
            if total and value.get("total") is not None:
                total_row = {"label_col": total["label_col"],
                             "value_col": total["value_col"],
                             "value": value["total"]}
            edit.fill_table(doc, entry["path"], rows,
                            header_rows=entry.get("header_rows", 1),
                            total_row=total_row, columns=columns)
            filled.append({"key": key, "kind": kind, "source": "system",
                           "text": f"{len(rows)} row(s)", "brief": "",
                           "anchor": entry["path"]})
            continue

        if value is None or not str(value).strip():
            unfilled.append(key)
            filled.append({"key": key, "kind": kind, "source": "unfilled",
                           "text": "", "brief": entry.get("brief", ""),
                           "anchor": entry.get("path") or entry.get("after")})
            continue

        shape = entry.get("shape", "paragraph")
        texts = _paragraph_texts(value, shape)
        if kind == "replace":
            edit.set_paragraph_text(doc, entry["path"], texts[0])
            anchor = entry["path"]
        else:
            list_style = _LIST_STYLE if shape == "bullets" else None
            if entry.get("after"):
                edit.insert_paragraphs_after(doc, entry["after"], entry["style_ref"],
                                             texts, list_style=list_style)
                anchor = entry["after"]
            else:
                edit.insert_paragraphs_before(doc, entry["before"], entry["style_ref"],
                                              texts, list_style=list_style)
                anchor = entry["before"]
        filled.append({"key": key, "kind": kind, "source": "ai",
                       "text": " ".join(texts), "brief": entry.get("brief", ""),
                       "anchor": anchor})

    for entry in tokens:
        key, literal = entry["key"], entry["literal"]
        value = values.get(key)
        if value is None or not str(value).strip():
            unfilled.append(key)
            filled.append({"key": key, "kind": "token", "source": "unfilled",
                           "text": "", "brief": "", "anchor": literal})
            continue
        count = dt.replace_token(doc, literal, str(value))
        filled.append({"key": key, "kind": "token", "source": "system",
                       "text": str(value), "brief": "",
                       "anchor": f"{literal} ×{count}"})

    if ix.detect(doc) == "field":
        ix.mark_fields_dirty(doc)

    buf = io.BytesIO()
    doc.save(buf)
    return {"docx": buf.getvalue(), "filled": filled, "unfilled": unfilled}
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_fill.py -q
```

Expected: 10 passed.

- [ ] **Step 5: Add a golden end-to-end fill, including the PDF**

Append to `tests/docx/test_golden_samples.py`:

```python
from app.services.docx import convert, fill


@pytest.mark.parametrize("name,literal", sorted(SAMPLES.items()))
def test_a_real_document_fills_and_converts(name, literal):
    path = SAMPLES_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present")
    data = path.read_bytes()
    out = ol.parse(data)

    heading = next((b for b in out["blocks"] if b["kind"] == "heading"), None)
    body_ref = next(
        (b for b in out["blocks"] if b["kind"] == "paragraph" and len(b["text"]) > 60),
        None,
    )
    if heading is None or body_ref is None:
        pytest.skip(f"{name} has no heading/body pair to anchor against")

    plan = {"version": 1, "entries": [
        {"kind": "token", "key": "client_name", "literal": literal},
        {"kind": "insert", "key": "greeting", "after": heading["path"],
         "fingerprint": heading["fingerprint"], "style_ref": body_ref["path"],
         "shape": "paragraph", "brief": "Opening greeting.",
         "max_words": 90, "required": True},
    ]}
    values = {"client_name": "Greenwood International School",
              "greeting": "We are delighted to present this proposal."}

    result = fill.apply(data, plan, values)
    assert result["unfilled"] == []

    filled_doc = Document(io.BytesIO(result["docx"]))
    assert dt.count_token(filled_doc, literal) == 0
    assert raw_count_bytes(result["docx"], literal) == 0
    assert len(filled_doc.part.package.image_parts) == EXPECTED_SHAPE[name]["media"]
    assert len(filled_doc.sections) == EXPECTED_SHAPE[name]["sections"]

    pdf = convert.docx_to_pdf(result["docx"])
    assert pdf[:5] == b"%PDF-"
    from pypdf import PdfReader
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Greenwood International School" in text
    assert literal not in text
```

- [ ] **Step 6: Run it**

```bash
.venv/bin/python -m pytest tests/docx/test_golden_samples.py -q
```

Expected: 4 more passed. Each converts a real document, so allow ~15s.

- [ ] **Step 7: Commit**

```bash
git add app/services/docx/fill.py tests/docx/test_fill.py tests/docx/test_golden_samples.py
git commit -m "feat(docx): apply a fill plan to a copy of the template"
```

---

## Phase 2 — The model

### Task 10: `app/ai/docx_prose.py` — the fill contract

**Files:**
- Create: `app/ai/docx_prose.py`
- Create: `tests/docx/test_prose.py`

**Interfaces:**
- Consumes: `app.ai.llm.get_model_layer`, `TIER_STRONG`; `app.services.fill_scrub`.
- Produces:
  - `async fill_prose(ctx, *, entries: list[dict], facts: dict, allowed_amounts: set[float]) -> dict[str, ProseResult]`
  - `ProseResult` = `{"text": str | None, "reasons": list[str], "attempts": int}`
  - `build_prompt(entries, facts, retry_notes=None) -> str` — pure, so the prompt is testable without a network.

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_prose.py
import pytest

from app.ai import docx_prose


ENTRIES = [
    {"key": "greeting", "brief": "Two sentence greeting to the client.",
     "max_words": 60, "required": True},
    {"key": "why_us", "brief": "Why YuviPep suits this school.",
     "max_words": 90, "required": False},
]
FACTS = {
    "org_name": "YuviPep", "client_name": "Greenwood International School",
    "contact_name": "Ms Rao", "program_name": "Innovation Lab",
    "program_description": "A hands-on STEAM lab.",
    "project_objective": "Set up a lab for grades 6 to 8 before June.",
    "meeting_notes": "Principal asked about teacher training.",
}


class FakeLayer:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


@pytest.fixture
def ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()


def test_prompt_names_every_placeholder_and_its_budget():
    prompt = docx_prose.build_prompt(ENTRIES, FACTS)
    assert "greeting" in prompt and "why_us" in prompt
    assert "60" in prompt and "90" in prompt
    assert "Greenwood International School" in prompt
    assert "plain text" in prompt.lower()


def test_prompt_tells_the_model_to_return_null_rather_than_invent():
    prompt = docx_prose.build_prompt(ENTRIES, FACTS)
    assert "null" in prompt.lower()


@pytest.mark.asyncio
async def test_clean_text_is_accepted_on_the_first_attempt(ctx, monkeypatch):
    layer = FakeLayer({"placeholders": [
        {"key": "greeting", "text": "We are delighted to write to you. "
                                    "Thank you for your time last week."},
        {"key": "why_us", "text": "YuviPep runs labs in two hundred schools."},
    ]})
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"].startswith("We are delighted")
    assert result["greeting"]["attempts"] == 1
    assert len(layer.calls) == 1


@pytest.mark.asyncio
async def test_a_dirty_fill_is_retried_once_and_then_accepted(ctx, monkeypatch):
    layer = FakeLayer(
        {"placeholders": [{"key": "greeting", "text": "I will now write **this**."},
                          {"key": "why_us", "text": "YuviPep runs many labs."}]},
        {"placeholders": [{"key": "greeting", "text": "We are delighted to write to you."}]},
    )
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"] == "We are delighted to write to you."
    assert result["greeting"]["attempts"] == 2
    assert len(layer.calls) == 2
    assert "markdown_markers" in layer.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_a_fill_dirty_twice_is_left_unfilled(ctx, monkeypatch):
    layer = FakeLayer(
        {"placeholders": [{"key": "greeting", "text": "I will now write the greeting."},
                          {"key": "why_us", "text": "YuviPep runs many labs."}]},
        {"placeholders": [{"key": "greeting", "text": "Here is the greeting."}]},
    )
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"] is None
    assert "meta_instruction" in result["greeting"]["reasons"]


@pytest.mark.asyncio
async def test_an_explicit_null_is_respected_and_not_retried(ctx, monkeypatch):
    layer = FakeLayer({"placeholders": [
        {"key": "greeting", "text": None, "reason": "no meeting notes"},
        {"key": "why_us", "text": "YuviPep runs many labs."},
    ]})
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts=set())
    assert result["greeting"]["text"] is None
    assert result["greeting"]["attempts"] == 1
    assert len(layer.calls) == 1


@pytest.mark.asyncio
async def test_an_invented_price_is_rejected(ctx, monkeypatch):
    layer = FakeLayer(
        {"placeholders": [
            {"key": "greeting", "text": "We can offer this for Rs 7,45,000 in total."},
            {"key": "why_us", "text": "YuviPep runs many labs."}]},
        {"placeholders": [{"key": "greeting", "text": "We look forward to working with you."}]},
    )
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    result = await docx_prose.fill_prose(ctx, entries=ENTRIES, facts=FACTS,
                                         allowed_amounts={970000.0})
    assert result["greeting"]["text"] == "We look forward to working with you."


@pytest.mark.asyncio
async def test_no_entries_makes_no_call(ctx, monkeypatch):
    layer = FakeLayer()
    monkeypatch.setattr(docx_prose, "get_model_layer", lambda: layer)
    assert await docx_prose.fill_prose(ctx, entries=[], facts=FACTS,
                                       allowed_amounts=set()) == {}
    assert layer.calls == []
```

- [ ] **Step 2: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_prose.py -q
```

Expected: `No module named 'app.ai.docx_prose'`.

- [ ] **Step 3: Implement**

```python
# app/ai/docx_prose.py
"""Ask the model for the prose a fill plan needs — and check what comes back.

One call for every prose placeholder in a proposal, because the placeholders
share a document and should share a voice. The model gets a brief per
placeholder and the facts it may use; it returns plain text.

It is never shown the document to rewrite. That is the point. A model handed a
whole document and told to improve it is the mechanism behind the original
defect — it starts describing the work ("I will now draft the greeting")
instead of doing it. Here there is nothing to narrate: each answer is one
paragraph's worth of text, and the brief it was given never enters the file.

Every answer goes through `fill_scrub`. One retry, naming what was wrong. After
that the placeholder is left unfilled and escalated — an honest blank a human
is told about beats a plausible invention in a document that goes to a client.
"""
from __future__ import annotations

import logging
from typing import Any

from app.ai.llm import TIER_STRONG, get_model_layer
from app.services import fill_scrub

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

_FACT_LABELS = [
    ("org_name", "Our organisation"),
    ("sender_name", "Who is sending this"),
    ("client_name", "The client"),
    ("contact_name", "Main contact"),
    ("contact_title", "Their role"),
    ("program_name", "What we are proposing"),
    ("program_description", "What that is"),
    ("project_objective", "What the client wants (from the meeting)"),
    ("meeting_notes", "Notes from the meeting"),
    ("date", "Today"),
]

_PROMPT = """You are writing sections of a sales proposal that will be placed \
into an existing, professionally designed document.

FACTS YOU MAY USE — these are all you know. Do not use anything else, and do \
not invent facts, names, dates, numbers or prices:
{facts}

SECTIONS TO WRITE:
{sections}

RULES — these are not stylistic preferences, they are what makes the output \
usable:
- Return PLAIN TEXT only. No markdown of any kind: no **bold**, no ## headings, \
no bullet characters, no tables, no backticks. The document supplies all \
formatting; any marker you type will be printed literally to the client.
- Write the section itself. Never write about writing it, never introduce your \
answer, never restate the brief, never leave a blank like [Name] or [Insert Date].
- Never state a price, total, discount or payment figure. The document's \
pricing comes from a locked rate table.
- Stay within each section's word budget.
- Match a warm, professional, factual business register.
- If you cannot write a section from the facts above, return null for its text \
and give a short reason. A blank a human can fill is correct; an invention is not.
{retry}
Return JSON: {{"placeholders": [{{"key": "...", "text": "..." or null, \
"reason": "..."}}]}}"""


def build_prompt(entries: list[dict], facts: dict[str, Any],
                 retry_notes: dict[str, list[str]] | None = None) -> str:
    fact_lines = []
    for key, label in _FACT_LABELS:
        value = (facts or {}).get(key)
        if value is not None and str(value).strip():
            fact_lines.append(f"- {label}: {str(value).strip()}")
    if not fact_lines:
        fact_lines.append("- (nothing supplied)")

    section_lines = []
    for entry in entries:
        section_lines.append(
            f'- key "{entry["key"]}": {entry.get("brief", "").strip()} '
            f'(at most {entry.get("max_words", 90)} words)'
        )

    retry = ""
    if retry_notes:
        problems = "\n".join(
            f'- "{key}" was rejected because: {", ".join(reasons)}'
            for key, reasons in retry_notes.items()
        )
        retry = (
            "\nYOUR PREVIOUS ANSWER WAS REJECTED. Fix exactly these problems "
            f"and return only the listed sections:\n{problems}\n"
        )

    return _PROMPT.format(
        facts="\n".join(fact_lines),
        sections="\n".join(section_lines),
        retry=retry,
    )


_SCHEMA = {
    "type": "object",
    "properties": {
        "placeholders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "text": {"type": "string", "nullable": True},
                    "reason": {"type": "string", "nullable": True},
                },
                "required": ["key"],
            },
        }
    },
    "required": ["placeholders"],
}


async def fill_prose(ctx, *, entries: list[dict], facts: dict[str, Any],
                     allowed_amounts: set[float]) -> dict[str, dict[str, Any]]:
    if not entries:
        return {}

    by_key = {e["key"]: e for e in entries}
    results: dict[str, dict[str, Any]] = {
        key: {"text": None, "reasons": [], "attempts": 0} for key in by_key
    }
    pending = list(entries)
    retry_notes: dict[str, list[str]] | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if not pending:
            break
        prompt = build_prompt(pending, facts, retry_notes)
        data = await get_model_layer().generate_json(
            purpose="proposal.docx_fill",
            tier=TIER_STRONG,
            org_id=getattr(ctx, "org_id", None),
            user_id=getattr(ctx, "user_id", None),
            messages=[{"role": "user", "content": prompt}],
            json_schema=_SCHEMA,
            temperature=0.4,
            max_tokens=4096,
        )
        answered = {
            item.get("key"): item
            for item in (data or {}).get("placeholders", [])
            if item.get("key")
        }

        next_pending: list[dict] = []
        next_notes: dict[str, list[str]] = {}
        for entry in pending:
            key = entry["key"]
            results[key]["attempts"] = attempt
            item = answered.get(key)
            text = (item or {}).get("text")

            if text is None or not str(text).strip():
                # An explicit refusal is the contract working. Do not retry it.
                results[key]["reasons"] = [
                    (item or {}).get("reason") or fill_scrub.REJECTION_BLANK
                ]
                continue

            reasons = fill_scrub.scrub(
                str(text),
                brief=entry.get("brief", ""),
                max_words=int(entry.get("max_words", 90) or 90),
                allowed_amounts=allowed_amounts,
            )
            if not reasons:
                results[key]["text"] = " ".join(str(text).split("\n"))
                results[key]["text"] = str(text).strip()
                results[key]["reasons"] = []
                continue

            results[key]["reasons"] = reasons
            logger.warning(
                "Rejected model prose for '%s' (attempt %s): %s",
                key, attempt, ", ".join(reasons),
            )
            if attempt < MAX_ATTEMPTS:
                next_pending.append(entry)
                next_notes[key] = reasons

        pending = next_pending
        retry_notes = next_notes or None

    return results
```

- [ ] **Step 4: Run the tests**

```bash
.venv/bin/python -m pytest tests/docx/test_prose.py -q
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/ai/docx_prose.py tests/docx/test_prose.py
git commit -m "feat(ai): grounded prose fill with a scrub-and-retry contract"
```

---

### Task 11: `app/ai/docx_suggest.py` — propose placeholders

**Files:**
- Create: `app/ai/docx_suggest.py`
- Create: `tests/docx/test_suggest.py`

**Interfaces:**
- Consumes: `app.ai.llm`, `docx.outline`.
- Produces: `async suggest(ctx, *, outline: dict, ocr: dict, program_name: str) -> list[dict]` returning candidate plan entries, each with `confidence` and `why`. Never saved automatically.

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_suggest.py
import pytest

from app.ai import docx_suggest


OUTLINE = {
    "blocks": [
        {"id": "b0", "path": "body[0]", "kind": "heading", "style": "Heading1",
         "level": 1, "text": "Proposal For", "images": [], "table": None,
         "fingerprint": "sha256:a"},
        {"id": "b1", "path": "body[1]", "kind": "paragraph", "style": "Normal",
         "level": None, "text": "School Name", "images": [], "table": None,
         "fingerprint": "sha256:b"},
        {"id": "b2", "path": "body[2]", "kind": "paragraph", "style": "Body Text",
         "level": None, "text": "YuviPep is a global learning ecosystem that "
         "empowers students through experiential education.",
         "images": [], "table": None, "fingerprint": "sha256:c"},
        {"id": "b3", "path": "body[3]", "kind": "table", "style": "", "level": None,
         "text": "Description | Estimation", "images": [], "table":
         {"rows": 3, "cols": 2, "header": ["Description", "Estimation"],
          "sample": [["Description", "Estimation"], ["Item", "Rs 0"], ["Total", "Rs 0"]]},
         "fingerprint": "sha256:d"},
    ],
    "headings": [{"id": "b0", "path": "body[0]", "level": 1, "text": "Proposal For"}],
    "tokens": [{"literal": "School Name", "occurrences": 6, "sample_block_ids": ["b1"]}],
    "media": ["image1.png"],
}


class FakeLayer:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


@pytest.fixture
def ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()


@pytest.mark.asyncio
async def test_returns_entries_that_reference_real_blocks(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "token", "key": "client_name", "literal": "School Name",
         "confidence": 0.95, "why": "repeated stand-in for the client"},
        {"kind": "insert", "key": "greeting_para", "after": "body[0]",
         "style_ref": "body[2]", "shape": "paragraph",
         "brief": "Opening greeting to the client.", "max_words": 90,
         "required": True, "confidence": 0.8, "why": "no greeting present"},
        {"kind": "table", "key": "pricing_table", "path": "body[3]",
         "columns": [{"col": 0, "field": "label"}, {"col": 1, "field": "line_total"}],
         "header_rows": 1, "total_row": {"label_col": 0, "value_col": 1},
         "confidence": 0.9, "why": "priced table"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    out = await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                     program_name="Innovation Lab")
    assert {e["key"] for e in out} == {"client_name", "greeting_para", "pricing_table"}
    assert all("fingerprint" in e for e in out if e["kind"] != "token")


@pytest.mark.asyncio
async def test_drops_a_suggestion_pointing_at_a_block_that_does_not_exist(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "insert", "key": "ghost", "after": "body[99]", "style_ref": "body[2]",
         "shape": "paragraph", "brief": "x", "max_words": 50, "required": False,
         "confidence": 0.5, "why": "invented"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    assert await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                      program_name="Innovation Lab") == []


@pytest.mark.asyncio
async def test_drops_a_token_literal_absent_from_the_document(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "token", "key": "client_name", "literal": "Not In This Document",
         "confidence": 0.9, "why": "guessed"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    assert await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                      program_name="Innovation Lab") == []


@pytest.mark.asyncio
async def test_drops_a_duplicate_key(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": [
        {"kind": "token", "key": "client_name", "literal": "School Name",
         "confidence": 0.9, "why": "a"},
        {"kind": "token", "key": "client_name", "literal": "School Name",
         "confidence": 0.9, "why": "b"},
    ]})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    out = await docx_suggest.suggest(ctx, outline=OUTLINE, ocr={},
                                     program_name="Innovation Lab")
    assert len(out) == 1


@pytest.mark.asyncio
async def test_ocr_text_reaches_the_prompt(ctx, monkeypatch):
    layer = FakeLayer({"suggestions": []})
    monkeypatch.setattr(docx_suggest, "get_model_layer", lambda: layer)
    await docx_suggest.suggest(ctx, outline=OUTLINE,
                               ocr={"image1.png": "OUR MISSION"},
                               program_name="Innovation Lab")
    assert "OUR MISSION" in layer.calls[0]["messages"][0]["content"]
```

- [ ] **Step 2: Run and watch them fail, then implement**

```bash
.venv/bin/python -m pytest tests/docx/test_suggest.py -q
```

```python
# app/ai/docx_suggest.py
"""Propose placeholders for an uploaded template. Advisory only.

Nothing here reaches a proposal. The output is a list of candidate plan
entries the administrator accepts, rejects, rewords or moves in the console —
so the model is allowed to be wrong, and being wrong costs a click.

What it must not do is be wrong *invisibly*: every suggestion is checked
against the outline before it is returned. A suggestion pointing at a block
that does not exist, or a literal that is not in the document, is dropped
rather than shown, because an administrator cannot be expected to verify
anchors by eye.
"""
from __future__ import annotations

import logging
from typing import Any

from app.ai.llm import TIER_STRONG, get_model_layer

logger = logging.getLogger(__name__)

MAX_BLOCKS = 220
MAX_OCR_CHARS = 4000

BINDABLE_FIELDS = (
    "client_name", "contact_name", "contact_title", "sender_name",
    "sender_email", "org_name", "program_name", "program_description",
    "date", "total_amount",
)

_PROMPT = """You are helping set up a reusable proposal template. Below is an \
existing, professionally designed document broken into numbered blocks. It is \
used for "{program_name}".

Your job is to say WHERE the system should fill things in when a real proposal \
is generated from it. You are not writing content now.

Propose three kinds of placeholder:

1. "token" — a literal phrase in the document that is really a stand-in for a \
field (e.g. the text "School Name" standing in for the client). Give the exact \
literal and which field it maps to. Bindable fields: {fields}.
2. "insert" — a new paragraph the AI should write at generation time, placed \
after (or before) an existing block. Give a "brief" describing what belongs \
there, a word budget, whether it is required, and a "style_ref": the path of an \
existing body paragraph whose formatting it should copy.
3. "table" — an existing table that is really the price list. Map its columns \
to "label", "unit", "unit_price", "quantity" or "line_total", say how many \
header rows it has, and which row is the total.

Be conservative. A document that already reads well needs few inserts. Suggest \
an insert only where something genuinely client-specific is missing — a \
greeting, a summary of what the client asked for, a closing. Never suggest \
replacing the organisation's own descriptive content.

Use only block paths that appear below. Use only literals that appear below.

DOCUMENT BLOCKS:
{blocks}
{ocr}
Return JSON: {{"suggestions": [{{"kind": "token"|"insert"|"table", "key": "...", \
"literal": "...", "path": "...", "after": "...", "before": "...", \
"style_ref": "...", "shape": "paragraph"|"paragraphs"|"bullets", "brief": "...", \
"max_words": 90, "required": true, "columns": [{{"col": 0, "field": "label"}}], \
"header_rows": 1, "total_row": {{"label_col": 0, "value_col": 1}}, \
"confidence": 0.0, "why": "..."}}]}}
Include only the fields each kind needs."""

_SCHEMA = {
    "type": "object",
    "properties": {"suggestions": {"type": "array", "items": {"type": "object"}}},
    "required": ["suggestions"],
}


def _render_blocks(outline: dict) -> str:
    lines = []
    for block in outline["blocks"][:MAX_BLOCKS]:
        kind = block["kind"]
        if kind == "table" and block["table"]:
            head = " | ".join(block["table"]["header"])
            lines.append(
                f'{block["path"]}  TABLE {block["table"]["rows"]}x'
                f'{block["table"]["cols"]}  header: {head}'
            )
        elif kind == "image":
            lines.append(f'{block["path"]}  IMAGE')
        elif kind == "empty":
            continue
        else:
            label = "HEADING" if kind == "heading" else "PARA"
            lines.append(f'{block["path"]}  {label} [{block["style"]}]  '
                         f'{block["text"][:120]}')
    return "\n".join(lines)


def _render_ocr(ocr: dict) -> str:
    if not ocr:
        return ""
    parts, used = [], 0
    for name, value in sorted(ocr.items()):
        if not value:
            continue
        snippet = value[:300]
        used += len(snippet)
        if used > MAX_OCR_CHARS:
            break
        parts.append(f"  {name}: {snippet}")
    if not parts:
        return ""
    return "\nTEXT READ FROM THE IMAGES:\n" + "\n".join(parts) + "\n"


async def suggest(ctx, *, outline: dict, ocr: dict, program_name: str) -> list[dict]:
    prompt = _PROMPT.format(
        program_name=program_name,
        fields=", ".join(BINDABLE_FIELDS),
        blocks=_render_blocks(outline),
        ocr=_render_ocr(ocr),
    )
    data = await get_model_layer().generate_json(
        purpose="proposal.docx_suggest",
        tier=TIER_STRONG,
        org_id=getattr(ctx, "org_id", None),
        user_id=getattr(ctx, "user_id", None),
        messages=[{"role": "user", "content": prompt}],
        json_schema=_SCHEMA,
        temperature=0.2,
        max_tokens=4096,
    )
    return _validate(data or {}, outline)


def _validate(data: dict, outline: dict) -> list[dict]:
    by_path = {b["path"]: b for b in outline["blocks"]}
    literals = {t["literal"] for t in outline.get("tokens", [])}
    all_text = " \n".join(b["text"] or "" for b in outline["blocks"])

    kept: list[dict] = []
    seen: set[str] = set()
    for raw in data.get("suggestions", []):
        kind, key = raw.get("kind"), raw.get("key")
        if kind not in ("token", "insert", "table") or not key or key in seen:
            continue

        if kind == "token":
            literal = raw.get("literal") or ""
            if literal not in literals and literal not in all_text:
                logger.info("Dropped suggested token %r: not in the document", literal)
                continue
            entry = {"kind": "token", "key": key, "literal": literal}

        elif kind == "table":
            path = raw.get("path")
            block = by_path.get(path)
            if block is None or block["kind"] != "table":
                logger.info("Dropped suggested table at %r: not a table here", path)
                continue
            columns = [
                c for c in (raw.get("columns") or [])
                if isinstance(c.get("col"), int) and c.get("field")
            ]
            if not columns:
                continue
            entry = {
                "kind": "table", "key": key, "path": path,
                "fingerprint": block["fingerprint"], "columns": columns,
                "header_rows": int(raw.get("header_rows", 1) or 1),
                "total_row": raw.get("total_row"),
            }

        else:
            anchor = raw.get("after") or raw.get("before")
            style_ref = raw.get("style_ref")
            if anchor not in by_path or style_ref not in by_path:
                logger.info("Dropped suggested insert at %r: unknown anchor", anchor)
                continue
            if by_path[style_ref]["kind"] not in ("paragraph", "heading"):
                continue
            entry = {
                "kind": "insert", "key": key,
                "fingerprint": by_path[anchor]["fingerprint"],
                "style_ref": style_ref,
                "shape": raw.get("shape", "paragraph"),
                "brief": (raw.get("brief") or "").strip(),
                "max_words": int(raw.get("max_words", 90) or 90),
                "required": bool(raw.get("required", False)),
            }
            entry["after" if raw.get("after") else "before"] = anchor
            if not entry["brief"]:
                continue

        entry["confidence"] = float(raw.get("confidence", 0.5) or 0.5)
        entry["why"] = (raw.get("why") or "").strip()
        kept.append(entry)
        seen.add(key)
    return kept
```

- [ ] **Step 3: Run the tests and commit**

```bash
.venv/bin/python -m pytest tests/docx/test_suggest.py -q
git add app/ai/docx_suggest.py tests/docx/test_suggest.py
git commit -m "feat(ai): placeholder suggestion pass, validated against the outline"
```

---

## Phase 3 — Data model and service integration

### Task 12: Models, reset taxonomy, and the bundle guard

**Files:**
- Modify: `app/models/program.py`, `app/models/proposal.py`, `app/models/__init__.py`, `app/core/reset_taxonomy.py`
- Create: `tests/docx/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProposalTemplate.kind`, `ProposalTemplateDoc` (table `proposal_template_docs`), `Proposal.filled_json`.

- [ ] **Step 1: Read the two files you are about to change, in full**

```bash
sed -n '1,90p' app/models/program.py
sed -n '1,60p' app/core/reset_taxonomy.py
grep -n "proposal_templates\|ProposalTemplate" app/core/reset_taxonomy.py
```

`reset_taxonomy.py` buckets every table into one of **four** tuples - `KEEP`, `CONFIG`, `REPLACE`, `WIPE` (decision D16). **Verified 2026-09-03: `proposal_templates` is in `REPLACE`, so `proposal_template_docs` goes in `REPLACE` too**, immediately after it, with a comment saying a template's document is part of the template. `tests/test_reset_taxonomy.py::test_every_table_is_in_exactly_one_bucket` already asserts full coverage, so do NOT write a new coverage test. But `test_bucket_sizes_are_the_agreed_partition` asserts exact sizes `(len(KEEP), len(CONFIG), len(REPLACE), len(WIPE)) == (4, 2, 7, 44)` - adding one table to REPLACE makes it **`(4, 2, 8, 44)`**, and you must update that assertion and extend its comment. Touch no other number.

- [ ] **Step 2: Write the failing tests**

```python
# tests/docx/test_models.py
import pytest
from sqlalchemy import inspect

from app.database import Base
from app.models.program import ProposalTemplate, ProposalTemplateDoc
from app.models.proposal import Proposal


def test_templates_default_to_the_markdown_kind():
    assert ProposalTemplate.__table__.c.kind.default.arg == "markdown"
    assert ProposalTemplate.__table__.c.kind.nullable is False


def test_the_template_doc_table_exists_with_its_columns():
    cols = set(ProposalTemplateDoc.__table__.c.keys())
    assert {"template_id", "source_path", "filename", "sha256", "size_bytes",
            "outline_json", "ocr_json", "plan_json", "index_kind",
            "analysis_status", "analysis_error"} <= cols


def test_one_doc_row_per_template_version():
    assert ProposalTemplateDoc.__table__.c.template_id.unique is True


def test_proposals_record_what_was_filled():
    assert "filled_json" in Proposal.__table__.c.keys()


def test_the_template_doc_table_shares_its_templates_reset_bucket():
    """A template's document is part of the template: if a reset replaces one it
    must replace the other, or a surviving template row points at a file that is
    gone and `_current_template` finds a template that cannot build anything."""
    from app.core.reset_taxonomy import CONFIG, KEEP, REPLACE, WIPE

    assert "proposal_templates" in REPLACE
    assert "proposal_template_docs" in REPLACE
    for other in (KEEP, CONFIG, WIPE):
        assert "proposal_template_docs" not in other
```

Adjust the last test to the taxonomy's actual shape once you have read it — the assertion that matters is that `proposal_template_docs` appears in exactly one bucket.

- [ ] **Step 3: Run and watch them fail**

```bash
.venv/bin/python -m pytest tests/docx/test_models.py -q
```

- [ ] **Step 4: Add `kind` to `ProposalTemplate`**

In `app/models/program.py`, inside `ProposalTemplate`, directly after `version`:

```python
    # "markdown" (the original: body_md with {variables}) or "docx" (an uploaded
    # .docx plus a fill plan). Defaulted so every template that already exists
    # keeps its behaviour without a data migration.
    kind: Mapped[str] = mapped_column(String(20), default="markdown", nullable=False)
```

Amend the `body_md` comment to record what it holds for a docx template:

```python
    # Markdown body with {variables} for kind="markdown".
    # For kind="docx" this holds a plain-text projection of the uploaded
    # document, so draft_check, revisions, the bundle export and the Android
    # content view keep working unchanged.
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
```

- [ ] **Step 5: Add `ProposalTemplateDoc` to `app/models/program.py`**

```python
class ProposalTemplateDoc(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """The uploaded .docx behind a kind="docx" template version.

    One row per template VERSION, not per template family: publishing v2
    uploads a new file and gets its own row, so a proposal built on v1 still
    resolves the exact bytes it was built from.

    `source_path` is written once and never rewritten. Every proposal is
    source + plan + values -> a new file.
    """

    __tablename__ = "proposal_template_docs"
    __table_args__ = (Index("ix_ptdocs_org_template", "org_id", "template_id"),)

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("proposal_templates.id"), unique=True, index=True
    )
    source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    outline_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ocr_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    index_kind: Mapped[str] = mapped_column(String(10), default="none")
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")
    analysis_error: Mapped[str | None] = mapped_column(Text)
```

- [ ] **Step 6: Add `filled_json` to `Proposal`** in `app/models/proposal.py`, after `line_items`:

```python
    # What each placeholder in a docx template resolved to, and from where:
    # [{"key","kind","source":"system"|"ai"|"unfilled","text","brief","anchor"}]
    # Empty for markdown templates.
    filled_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
```

- [ ] **Step 7: Export the new model**

In `app/models/__init__.py`, extend the `program` import and `__all__`:

```python
from app.models.program import (
    MessageTemplate, PricingTable, Program, ProposalTemplate, ProposalTemplateDoc,
)
```

and add `"ProposalTemplateDoc",` to `__all__`.

- [ ] **Step 8: Bucket the new table in `reset_taxonomy.py`**

Place `proposal_template_docs` in the **same bucket as `proposal_templates`**. A template's document is part of the template; separating them would leave a template row whose document is gone, and `_current_template` would then find a template that cannot build anything. Add a comment saying so.

- [ ] **Step 9: Guard the bundle export against a silent downgrade**

`Dashboard/src/descriptors/catalogue.ts` marks `proposalTemplates` as `inBundle: true`, exporting `name` + `body_md`. Re-importing a docx template from that bundle would create a **markdown** template holding the text projection: the branding silently disappears and nobody is told.

In `app/api/admin.py::list_proposal_templates`, add `kind` to the response dict so the console can see it:

```python
        {"id": t.id, "name": t.name, "version": t.version, "kind": t.kind,
         "is_current": t.is_current, "body_md": t.body_md}
```

The console-side refusal is Task 19, Step 4. Note it here so the two halves are not separated.

- [ ] **Step 10: Recreate the dev database and run the full suite**

```bash
grep -n "DATABASE_URL" .env | head -2
ls -la data/*.db 2>/dev/null
```

The schema is created by `Base.metadata.create_all` at startup (there is no Alembic in this project). For the dev database, back it up and let it recreate:

```bash
cp data/app.db data/app.db.bak-docx-$(date +%Y%m%d) 2>/dev/null || true
.venv/bin/python -m pytest -q
```

Expected: the whole suite green, including `tests/test_reset_taxonomy.py`.

- [ ] **Step 11: Commit**

```bash
git add app/models/program.py app/models/proposal.py app/models/__init__.py \
        app/core/reset_taxonomy.py app/api/admin.py tests/docx/test_models.py
git commit -m "feat(models): docx template kind, template docs table, filled_json"
```

---

### Task 13: `docx_template_service` — ingest an uploaded document

**Files:**
- Create: `app/services/docx_template_service.py`
- Create: `tests/docx/test_template_service.py`

**Interfaces:**
- Consumes: `docx.outline`, `docx.ocr`, `docx.index`, `storage`, the models from Task 12.
- Produces:
  - `MAX_UPLOAD_BYTES = 25 * 1024 * 1024`
  - `analyse(docx_bytes: bytes) -> dict` — `{outline, ocr, index_kind, projection}`; raises `ValidationFailedError` for a file that is not a readable .docx.
  - `async create_docx_template(db, ctx, *, program_id, name, filename, data, make_current) -> tuple[ProposalTemplate, ProposalTemplateDoc]`
  - `async get_doc(db, org_id, doc_id) -> ProposalTemplateDoc`
  - `async save_plan(db, ctx, doc, plan) -> list[str]` — returns validation problems; saves only when empty.

- [ ] **Step 1: Write the failing tests**

```python
# tests/docx/test_template_service.py
import io

import pytest
from docx import Document

from app.core.exceptions import ValidationFailedError
from app.services import docx_template_service as dts


def _docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("School Name")
    doc.add_paragraph("A body paragraph long enough to serve as a style reference.")
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


def test_analyse_returns_outline_index_and_projection(monkeypatch):
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    result = dts.analyse(_docx())
    assert result["index_kind"] == "none"
    assert result["outline"]["blocks"]
    assert "School Name" in result["projection"]
    assert len(result["projection"]) >= 20


def test_analyse_refuses_a_file_that_is_not_a_docx():
    with pytest.raises(ValidationFailedError) as err:
        dts.analyse(b"PK\x03\x04 not really a document")
    assert "Word document" in str(err.value)


def test_analyse_refuses_an_empty_file():
    with pytest.raises(ValidationFailedError):
        dts.analyse(b"")


def test_analyse_refuses_a_document_with_no_text(monkeypatch):
    monkeypatch.setattr(dts.ocr, "ocr_document", lambda *a, **k: {})
    doc = Document()
    buf = io.BytesIO(); doc.save(buf)
    with pytest.raises(ValidationFailedError) as err:
        dts.analyse(buf.getvalue())
    assert "no text" in str(err.value).lower()
```

- [ ] **Step 2: Run, watch fail, then implement**

```python
# app/services/docx_template_service.py
"""Ingest an uploaded .docx and hold the material the console edits against.

Parsing and OCR happen once, here, at upload. Nothing in this module runs on
the proposal-generation path — a salesperson never waits for tesseract.
"""
from __future__ import annotations

import hashlib
import io
import logging
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.program import Program, ProposalTemplate, ProposalTemplateDoc
from app.services import audit_service, storage
from app.services.docx import fill as docx_fill
from app.services.docx import index as docx_index
from app.services.docx import ocr
from app.services.docx import outline as docx_outline

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024      # largest real sample is 14.8 MB
CATEGORY_TEMPLATES = "proposal_templates"
_MIN_PROJECTION = 20                     # ProposalTemplateRequest.body_md floor


def analyse(docx_bytes: bytes) -> dict:
    if not docx_bytes:
        raise ValidationFailedError("The uploaded file is empty")
    if len(docx_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationFailedError(
            f"That file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            if "word/document.xml" not in z.namelist():
                raise KeyError("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValidationFailedError(
            "That is not a Word document. Upload a .docx file saved from Word "
            "or Google Docs."
        ) from exc

    try:
        outline = docx_outline.parse(docx_bytes)
    except ValidationFailedError:
        raise
    except Exception as exc:  # noqa: BLE001 — a malformed package must not 500
        logger.exception("Failed to parse an uploaded template")
        raise ValidationFailedError(
            "This document could not be read. Try re-saving it from Word as "
            ".docx and uploading again."
        ) from exc

    projection = docx_outline.project_text(outline)
    if len(projection) < _MIN_PROJECTION:
        raise ValidationFailedError(
            "This document has no text the system can read, so there is "
            "nothing to place placeholders into."
        )

    from docx import Document
    index_kind = docx_index.detect(Document(io.BytesIO(docx_bytes)))
    return {
        "outline": outline,
        "ocr": ocr.ocr_document(docx_bytes),
        "index_kind": index_kind,
        "projection": projection,
    }


async def create_docx_template(
    db: AsyncSession, ctx: OrgContext, *, program_id: str, name: str,
    filename: str, data: bytes, make_current: bool = True,
) -> tuple[ProposalTemplate, ProposalTemplateDoc]:
    program = (
        await db.execute(
            select(Program).where(Program.id == program_id, Program.org_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if program is None:
        raise NotFoundError("Program not found")

    analysis = analyse(data)

    same_name = (
        await db.execute(
            select(ProposalTemplate)
            .where(
                ProposalTemplate.org_id == ctx.org_id,
                ProposalTemplate.program_id == program_id,
                ProposalTemplate.name == name,
            )
            .order_by(ProposalTemplate.version.desc())
        )
    ).scalars().first()
    version = (same_name.version + 1) if same_name else 1

    if make_current:
        others = (
            await db.execute(
                select(ProposalTemplate).where(
                    ProposalTemplate.org_id == ctx.org_id,
                    ProposalTemplate.program_id == program_id,
                    ProposalTemplate.is_current.is_(True),
                )
            )
        ).scalars().all()
        for other in others:
            other.is_current = False

    template = ProposalTemplate(
        org_id=ctx.org_id, program_id=program_id, name=name, version=version,
        kind="docx", body_md=analysis["projection"],
        is_current=make_current, created_by=ctx.user_id,
    )
    db.add(template)
    await db.flush()

    rel_path = storage.save_bytes(ctx.org_id, CATEGORY_TEMPLATES, filename, data)
    doc_row = ProposalTemplateDoc(
        org_id=ctx.org_id, template_id=template.id, source_path=rel_path,
        filename=filename, sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data), outline_json=analysis["outline"],
        ocr_json=analysis["ocr"], plan_json={"version": 1, "entries": []},
        index_kind=analysis["index_kind"], analysis_status="ready",
    )
    db.add(doc_row)
    await db.flush()

    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.proposal_template_docx_uploaded",
        entity_type="program", entity_id=program_id,
        detail={"name": name, "version": version, "filename": filename,
                "index_kind": analysis["index_kind"],
                "blocks": len(analysis["outline"]["blocks"])},
    )
    return template, doc_row


async def get_doc(db: AsyncSession, org_id: str, doc_id: str) -> ProposalTemplateDoc:
    row = (
        await db.execute(
            select(ProposalTemplateDoc).where(
                ProposalTemplateDoc.id == doc_id,
                ProposalTemplateDoc.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Template document not found")
    return row


async def save_plan(
    db: AsyncSession, ctx: OrgContext, doc: ProposalTemplateDoc, plan: dict
) -> list[str]:
    problems = docx_fill.validate_plan(plan, doc.outline_json)
    if problems:
        return problems
    doc.plan_json = plan
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id,
        action="admin.proposal_template_plan_saved",
        entity_type="proposal_template", entity_id=doc.template_id,
        detail={"entries": len(plan.get("entries") or [])},
    )
    return []
```

- [ ] **Step 3: Run the tests and commit**

```bash
.venv/bin/python -m pytest tests/docx/test_template_service.py -q
git add app/services/docx_template_service.py tests/docx/test_template_service.py
git commit -m "feat: ingest an uploaded .docx as a proposal template version"
```

---

### Task 14: `build_proposal` branches on `kind`

**Files:**
- Modify: `app/services/proposal_service.py`
- Create: `app/services/docx_proposal_service.py`
- Create: `tests/docx/test_build_docx_proposal.py`

**Interfaces:**
- Consumes: `docx_template_service`, `docx.fill`, `ai.docx_prose`, `proposal_service.render_pricing_block`, `_money`, `_allowed_amounts`.
- Produces: `async build_docx_content(db, ctx, *, source_bytes: bytes, plan: dict, variables: dict, line_items: list[dict], total_amount: float, currency: str, facts: dict) -> dict` returning `{"docx": bytes, "content_md": str, "filled": list[dict], "unfilled": list[str]}`.

- [ ] **Step 1: Read the function you are changing, in full**

```bash
sed -n '120,270p' app/services/proposal_service.py
```

Everything before the `content = template_service.render(...)` line is shared by both kinds and must not move — the lead, program, pricing, org, contact and `context_summary` resolution (including the F66 project-objective fallback) are all still correct for a docx template.

- [ ] **Step 2: Write the failing test**

```python
# tests/docx/test_build_docx_proposal.py
import io

import pytest
from docx import Document

from app.services import docx_proposal_service as dps
from app.services.docx import text as dt


class Template:
    kind = "docx"
    id = "tpl1"
    name = "Standard"
    version = 1


def _source() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("School Name")
    doc.add_paragraph("A body paragraph long enough to be a style reference here.")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "Description"; t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Item"; t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total"; t.cell(2, 1).text = "Rs 0"
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_system_values_fill_without_calling_the_model(monkeypatch):
    from app.services.docx import outline as ol

    data = _source()
    outline = ol.parse(data)
    table_path = next(b["path"] for b in outline["blocks"] if b["kind"] == "table")
    by_path = {b["path"]: b for b in outline["blocks"]}
    plan = {"version": 1, "entries": [
        {"kind": "token", "key": "client_name", "literal": "School Name"},
        {"kind": "table", "key": "pricing_table", "path": table_path,
         "fingerprint": by_path[table_path]["fingerprint"],
         "columns": [{"col": 0, "field": "label"}, {"col": 1, "field": "line_total"}],
         "header_rows": 1, "total_row": {"label_col": 0, "value_col": 1}},
    ]}

    called = []

    async def never(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(dps.docx_prose, "fill_prose", never)

    result = await dps.build_docx_content(
        None, _ctx(), source_bytes=data, plan=plan,
        variables={"client_name": "Greenwood International School"},
        line_items=[{"label": "Innovation Lab", "unit": "per lab",
                     "unit_price": 850000.0, "quantity": 1.0,
                     "line_total": 850000.0}],
        total_amount=850000.0, currency="INR", facts={},
    )
    assert called == []
    doc = Document(io.BytesIO(result["docx"]))
    assert dt.count_token(doc, "School Name") == 0
    assert doc.tables[0].cell(1, 0).text == "Innovation Lab"
    assert "Innovation Lab" in result["content_md"]
    assert result["unfilled"] == []


def _ctx():
    class Ctx:
        org_id = "org1"
        user_id = "u1"
    return Ctx()
```

- [ ] **Step 3: Implement `app/services/docx_proposal_service.py`**

```python
# app/services/docx_proposal_service.py
"""Turn a docx template plus a plan into a filled proposal document.

Splits cleanly in two, and the split is the safety property:

  * system values — the client's name, the contact, the date, and every cell
    of the price table — are resolved here from the database and the locked
    pricing version. No model is involved and none can be.
  * prose values — greetings, summaries, closings — come from one call to
    `docx_prose`, which scrubs and retries and refuses to invent.

`proposal_service` keeps ownership of the numbers exactly as before.
"""
from __future__ import annotations

import logging
from typing import Any

from app.ai import docx_prose
from app.services.docx import fill as docx_fill
from app.services.docx import index as docx_index
from app.services.docx import outline as docx_outline

logger = logging.getLogger(__name__)

_SYSTEM_KINDS = ("token", "table")


def _pricing_value(line_items: list[dict[str, Any]], total: str,
                   entry: dict, currency: str) -> dict[str, Any]:
    """Currency is passed explicitly and `line_items` is NEVER mutated: it is
    persisted to `Proposal.line_items` (a JSON column) and returned to the
    Android app, so stashing a private `_currency` key on each item would leak
    it into stored data and into the mobile contract."""
    from app.services.proposal_service import _money  # noqa: PLC0415

    fields = [c["field"] for c in entry["columns"]]
    rows = []
    for item in line_items:
        row = {}
        for field in fields:
            raw = item.get(field)
            if field in ("unit_price", "line_total"):
                row[field] = _money(float(raw or 0), currency)
            elif field == "quantity":
                row[field] = str(int(float(raw or 0)))
            else:
                row[field] = str(raw or "")
        rows.append(row)
    return {"rows": rows, "total": total}


async def build_docx_content(
    db, ctx, *, source_bytes: bytes, plan: dict,
    variables: dict[str, Any], line_items: list[dict[str, Any]],
    total_amount: float, currency: str, facts: dict[str, Any],
) -> dict[str, Any]:
    from app.services.proposal_service import _allowed_amounts, _money  # noqa: PLC0415

    entries = list(plan.get("entries") or [])
    values: dict[str, Any] = {}

    for entry in entries:
        if entry["kind"] == "token":
            values[entry["key"]] = variables.get(entry["key"])
        elif entry["kind"] == "table":
            values[entry["key"]] = _pricing_value(
                line_items, _money(total_amount, currency), entry, currency
            )

    prose_entries = [e for e in entries if e["kind"] in ("insert", "replace")]
    if prose_entries:
        prose = await docx_prose.fill_prose(
            ctx,
            entries=prose_entries,
            facts=facts,
            allowed_amounts=_allowed_amounts(line_items, total_amount),
        )
        for key, result in prose.items():
            if result["text"]:
                values[key] = result["text"]
            else:
                logger.warning(
                    "Placeholder '%s' left unfilled: %s",
                    key, ", ".join(result["reasons"]) or "no text returned",
                )

    result = docx_fill.apply(source_bytes, plan, values)

    if docx_index.detect_bytes(result["docx"]) == "static":
        result["docx"] = docx_index.refresh_static(result["docx"])

    outline = docx_outline.parse(result["docx"])
    result["content_md"] = docx_outline.project_text(outline)
    return result
```

Add the small helper `detect_bytes` to `app/services/docx/index.py`:

```python
def detect_bytes(docx_bytes: bytes) -> str:
    from docx import Document
    return detect(Document(io.BytesIO(docx_bytes)))
```

- [ ] **Step 4: Branch inside `build_proposal`**

In `app/services/proposal_service.py`, replace the single line

```python
    content = template_service.render(template.body_md, variables)
```

with:

```python
    filled_json: list[dict[str, Any]] = []
    unfilled_placeholders: list[str] = []
    docx_bytes: bytes | None = None

    if getattr(template, "kind", "markdown") == "docx":
        # A docx template is filled, never re-rendered: the uploaded document
        # keeps its cover, images, headers, footers and styled tables, and the
        # model only ever supplies plain text for the placeholders a human
        # approved. See docs/superpowers/specs/2026-09-03-docx-proposal-templates-design.md
        from app.models.program import ProposalTemplateDoc
        from app.services import docx_proposal_service, storage

        doc_row = (
            await db.execute(
                select(ProposalTemplateDoc).where(
                    ProposalTemplateDoc.template_id == template.id,
                    ProposalTemplateDoc.org_id == ctx.org_id,
                )
            )
        ).scalar_one_or_none()
        if doc_row is None:
            raise NotFoundError(
                f"Template '{template.name}' v{template.version} is a document "
                "template but its file is missing. Re-upload it."
            )
        source_bytes = storage.read_bytes(ctx.org_id, doc_row.source_path)
        facts = {
            **{k: v for k, v in variables.items() if isinstance(v, str)},
            "project_objective": context_summary or "",
            "meeting_notes": "",
        }
        built = await docx_proposal_service.build_docx_content(
            db, ctx,
            source_bytes=source_bytes, plan=doc_row.plan_json or {},
            variables=variables, line_items=line_items,
            total_amount=total, currency=currency, facts=facts,
        )
        content = built["content_md"]
        docx_bytes = built["docx"]
        filled_json = built["filled"]
        unfilled_placeholders = built["unfilled"]
    else:
        content = template_service.render(template.body_md, variables)
```

Set `filled_json=filled_json` **and** `template_kind=template.kind` on the `Proposal(...)` constructor (the column itself is added in Task 15, Step 3 - if you reach Task 14 first, add the column now and let Task 15 skip that step). After `await db.flush()`, persist the document:

```python
    if docx_bytes is not None:
        from app.services import storage
        proposal.docx_path = storage.save_bytes(
            ctx.org_id, storage.CATEGORY_PROPOSALS,
            f"{program.name}_{lead.name}.docx", docx_bytes,
        )
```

- [ ] **Step 5: Escalate unfilled placeholders through the existing gate**

Immediately after the existing `unfilled = template_service.missing_variables(content)` block, add:

```python
    # A required placeholder the model would not ground is escalated exactly
    # like a [missing:…] marker (F47): the send gate refuses it, and a human is
    # told which section is blank rather than a plausible invention going out.
    if unfilled_placeholders:
        from app.core.constants import DecisionType
        from app.engines.common import record_decision

        names = ", ".join(sorted(set(unfilled_placeholders)))
        logger.warning("Proposal %s has unfilled placeholders: %s", proposal.id, names)
        await record_decision(
            db, org_id=ctx.org_id, project_id=project_id,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine="document",
            decision="Proposal has unfilled sections", needs_human=True,
            confidence=1.0,
            reason=(
                f"The sections {names} could not be written from what is on "
                f"record, so they are blank in '{template.name}' "
                f"v{template.version}. Fill them in before this goes to the client."
            ),
            input_summary=f"proposal={proposal.title}",
            entity_type="proposal", entity_id=proposal.id,
        )
```

- [ ] **Step 6: Run everything**

```bash
.venv/bin/python -m pytest tests/docx -q && .venv/bin/python -m pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add app/services/proposal_service.py app/services/docx_proposal_service.py \
        app/services/docx/index.py tests/docx/test_build_docx_proposal.py
git commit -m "feat: build proposals from docx templates without re-rendering"
```

---

### Task 15: PDF for docx proposals

**Files:**
- Modify: `app/services/proposal_email_service.py`
- Create: `tests/docx/test_render_files.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/docx/test_render_files.py
import io

import pytest
from docx import Document

from app.services import proposal_email_service as pes


class FakeProposal:
    def __init__(self, kind):
        self.org_id = "org1"
        self.title = "Innovation Lab Proposal"
        self.content_md = "# Heading\n\nBody text for the markdown path."
        self.docx_path = None
        self.pdf_path = None
        self.template_kind = kind


@pytest.mark.asyncio
async def test_a_docx_proposal_converts_its_stored_document(monkeypatch, tmp_path):
    doc = Document(); doc.add_paragraph("Filled document body.")
    buf = io.BytesIO(); doc.save(buf)
    stored = buf.getvalue()

    proposal = FakeProposal("docx")
    proposal.docx_path = "orgs/org1/proposals/x.docx"

    monkeypatch.setattr(pes.storage, "read_bytes", lambda org, path: stored)
    monkeypatch.setattr(pes.storage, "save_bytes",
                        lambda org, cat, name, data: f"orgs/{org}/{cat}/{name}")
    seen = {}

    def fake_convert(data, **kw):
        seen["called"] = True
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(pes.docx_convert, "docx_to_pdf", fake_convert)

    class DB:
        async def flush(self): return None

    await pes.ensure_rendered_files(DB(), proposal)
    assert seen.get("called") is True
    assert proposal.pdf_path.endswith(".pdf")


@pytest.mark.asyncio
async def test_a_markdown_proposal_still_uses_reportlab(monkeypatch):
    proposal = FakeProposal("markdown")
    calls = []
    monkeypatch.setattr(pes.document_service, "render_docx",
                        lambda md, title: calls.append("docx") or b"DOCX")
    monkeypatch.setattr(pes.document_service, "render_pdf",
                        lambda md, title: calls.append("pdf") or b"%PDF-")
    monkeypatch.setattr(pes.storage, "save_bytes",
                        lambda org, cat, name, data: f"orgs/{org}/{cat}/{name}")

    class DB:
        async def flush(self): return None

    await pes.ensure_rendered_files(DB(), proposal)
    assert calls == ["docx", "pdf"]
```

- [ ] **Step 2: Implement**

Add to the imports of `app/services/proposal_email_service.py`:

```python
from app.services.docx import convert as docx_convert
```

Replace `ensure_rendered_files` with:

```python
async def ensure_rendered_files(db: AsyncSession, proposal: Proposal) -> None:
    """Render DOCX + PDF for the current content if not already rendered.

    A docx-backed proposal already HAS its document — `build_proposal` wrote
    it — so there is nothing to render, only to convert. It deliberately does
    not fall back to the reportlab renderer: that would quietly replace a
    branded proposal with a plain one on the way to a client, which is the
    failure this whole path exists to remove.
    """
    if proposal.docx_path and proposal.pdf_path:
        return
    base = _safe_name(proposal.title)

    if getattr(proposal, "template_kind", "markdown") == "docx" and proposal.docx_path:
        docx_bytes = storage.read_bytes(proposal.org_id, proposal.docx_path)
        pdf_bytes = docx_convert.docx_to_pdf(docx_bytes)
        proposal.pdf_path = storage.save_bytes(
            proposal.org_id, storage.CATEGORY_PROPOSALS, f"{base}.pdf", pdf_bytes
        )
        await db.flush()
        return

    docx_bytes = document_service.render_docx(proposal.content_md, proposal.title)
    pdf_bytes = document_service.render_pdf(proposal.content_md, proposal.title)
    proposal.docx_path = storage.save_bytes(
        proposal.org_id, storage.CATEGORY_PROPOSALS, f"{base}.docx", docx_bytes
    )
    proposal.pdf_path = storage.save_bytes(
        proposal.org_id, storage.CATEGORY_PROPOSALS, f"{base}.pdf", pdf_bytes
    )
    await db.flush()
```

- [ ] **Step 3: Add `template_kind` to `Proposal`**

`ensure_rendered_files` needs to know the kind without a query. In `app/models/proposal.py`, beside `template_version`:

```python
    # Copied from the template at build time, so rendering never needs to load
    # the template row (and an old proposal keeps rendering the way it was
    # built even if the template family later changes kind).
    template_kind: Mapped[str] = mapped_column(String(20), default="markdown", nullable=False)
```

Set `template_kind=template.kind` in the `Proposal(...)` constructor in `build_proposal`, and add it to `test_models.py`.

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest tests/docx/test_render_files.py -q
.venv/bin/python -m pytest -q
git add app/services/proposal_email_service.py app/models/proposal.py \
        app/services/proposal_service.py tests/docx/test_render_files.py \
        tests/docx/test_models.py
git commit -m "feat: PDF for docx proposals via LibreOffice, markdown path untouched"
```

---

### Task 16: Per-placeholder re-fill on edit

**Files:**
- Modify: `app/ai/agents/proposal_agent.py`
- Create: `tests/docx/test_docx_edit_path.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/docx/test_docx_edit_path.py
import pytest

from app.ai.agents import proposal_agent


class P:
    id = "p1"; org_id = "org1"; template_kind = "docx"; template_id = "t1"
    content_md = "body"; line_items = []; total_amount = 0.0; currency = "INR"
    filled_json = [
        {"key": "greeting", "kind": "insert", "source": "ai",
         "text": "Old greeting.", "brief": "Opening greeting.", "anchor": "body[0]"},
        {"key": "client_name", "kind": "token", "source": "system",
         "text": "Greenwood", "brief": "", "anchor": "School Name ×6"},
    ]


@pytest.mark.asyncio
async def test_an_instruction_names_the_placeholder_to_redo(monkeypatch):
    async def fake_json(**kwargs):
        return {"line_ops": [], "placeholder_keys": ["greeting"],
                "placeholder_instruction": "warmer, mention the June deadline"}

    class Layer:
        generate_json = staticmethod(fake_json)

    monkeypatch.setattr(proposal_agent, "get_model_layer", lambda: Layer())
    keys, instruction, ops = await proposal_agent.parse_docx_edit(
        _ctx(), P(), "make the greeting warmer and mention the June deadline"
    )
    assert keys == ["greeting"]
    assert "June" in instruction
    assert ops == []


@pytest.mark.asyncio
async def test_a_key_that_is_not_in_the_proposal_is_dropped(monkeypatch):
    async def fake_json(**kwargs):
        return {"line_ops": [], "placeholder_keys": ["nonexistent"],
                "placeholder_instruction": "x"}

    class Layer:
        generate_json = staticmethod(fake_json)

    monkeypatch.setattr(proposal_agent, "get_model_layer", lambda: Layer())
    keys, _, _ = await proposal_agent.parse_docx_edit(_ctx(), P(), "change something")
    assert keys == []


def _ctx():
    class Ctx:
        org_id = "org1"; user_id = "u1"
    return Ctx()
```

- [ ] **Step 2: Implement `parse_docx_edit` in `app/ai/agents/proposal_agent.py`**

```python
_DOCX_EDIT_PROMPT = """A salesperson wants to change a proposal built from a \
document template. Turn their instruction into structured edits.

Commercial line items (code | label | unit_price | quantity):
{items}

Sections of the document the AI wrote, which can be rewritten:
{placeholders}

Instruction: "{instruction}"

Return JSON:
{{
  "line_ops": [ {{"op": "set_quantity"|"set_unit_price"|"add_item"|"remove_item",
                  "code": "...", "quantity": 0, "unit_price": 0,
                  "label": "...", "unit": "..."}} ],
  "placeholder_keys": ["..."],
  "placeholder_instruction": "..." or null
}}

Only list a placeholder key that appears above. Prices and quantities must come \
from the instruction itself — never invent numbers. The document's fixed \
content and its price table cannot be reworded; if the instruction asks for \
that, return empty lists."""


async def parse_docx_edit(ctx, proposal, instruction: str):
    """-> (placeholder_keys, placeholder_instruction, line_ops)"""
    known = {
        f["key"]: f
        for f in (proposal.filled_json or [])
        if f.get("kind") in ("insert", "replace")
    }
    items_desc = "\n".join(
        f"- {i.get('code')} | {i.get('label')} | {i.get('unit_price')} | {i.get('quantity')}"
        for i in (proposal.line_items or [])
    ) or "- (none)"
    placeholders_desc = "\n".join(
        f'- "{key}": {row.get("brief") or "(no brief)"} — currently: '
        f'{(row.get("text") or "")[:90]}'
        for key, row in known.items()
    ) or "- (none)"

    data = await get_model_layer().generate_json(
        purpose="proposal.parse_docx_edit",
        tier=TIER_FAST,
        org_id=getattr(ctx, "org_id", None),
        user_id=getattr(ctx, "user_id", None),
        messages=[{"role": "user", "content": _DOCX_EDIT_PROMPT.format(
            items=items_desc, placeholders=placeholders_desc, instruction=instruction,
        )}],
        json_schema={
            "type": "object",
            "properties": {
                "line_ops": {"type": "array", "items": {"type": "object"}},
                "placeholder_keys": {"type": "array", "items": {"type": "string"}},
                "placeholder_instruction": {"type": "string", "nullable": True},
            },
            "required": ["line_ops"],
        },
        temperature=0.1,
    )
    keys = [k for k in (data.get("placeholder_keys") or []) if k in known]
    line_ops = [
        {k: v for k, v in op.items() if v is not None}
        for op in (data.get("line_ops") or [])
    ]
    return keys, (data.get("placeholder_instruction") or ""), line_ops
```

- [ ] **Step 3: Route docx proposals through it**

At the top of `parse_and_apply_edit`, before the existing markdown logic:

```python
    if getattr(proposal, "template_kind", "markdown") == "docx":
        return await _apply_docx_edit(db, ctx, proposal, instruction)
```

and add `_apply_docx_edit`, which:
1. calls `parse_docx_edit`;
2. applies `line_ops` through `proposal_service.apply_line_item_ops` (unchanged);
3. for each named key, appends the instruction to that entry's brief and re-runs `docx_proposal_service.build_docx_content` **from the template source**, not from the previous output — this is what stops formatting eroding across edits;
4. writes the new document to storage, clears `pdf_path`, updates `filled_json`;
5. calls `proposal_service.record_edit`.

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest tests/docx -q && .venv/bin/python -m pytest -q
git add app/ai/agents/proposal_agent.py tests/docx/test_docx_edit_path.py
git commit -m "feat: edit a docx proposal by re-filling named placeholders"
```

---

### Task 17: The API surface

**Files:**
- Modify: `app/api/admin.py`, `app/api/proposals.py`
- Create: `tests/docx/test_api.py`

Six new routes, all under `require_permission("manage_templates")` except the media read, which uses `get_org_context`:

| Method | Route |
|---|---|
| POST | `/admin/programs/{program_id}/proposal-templates/docx` |
| GET | `/admin/proposal-template-docs/{doc_id}` |
| POST | `/admin/proposal-template-docs/{doc_id}/suggest` |
| PUT | `/admin/proposal-template-docs/{doc_id}/plan` |
| POST | `/admin/proposal-template-docs/{doc_id}/preview` |
| GET | `/admin/proposal-template-docs/{doc_id}/media/{name}` |

- [ ] **Step 1: Write the tests** (`tests/docx/test_api.py`) using the existing `tests/conftest.py` client fixtures — read them first:

```bash
sed -n '1,80p' tests/conftest.py
grep -n "org_admin\|auth_headers\|async_client" tests/conftest.py | head -20
```

Cover: upload creates a template with `kind="docx"` and a doc row; upload rejects a non-docx with a readable message; upload rejects >25 MB; `GET` returns outline, plan and `index_kind`; `PUT /plan` refuses an incoherent plan with the problems listed and saves a coherent one; `POST /preview` returns a PDF; media returns bytes for a real part and 404 otherwise; a doc belonging to another org is not readable.

- [ ] **Step 2: Implement the routes in `app/api/admin.py`**

Key details, all of which the tests above pin:

```python
@router.post("/programs/{program_id}/proposal-templates/docx")
async def add_proposal_template_docx(
    program_id: str,
    name: str = Form(...),
    make_current: bool = Form(True),
    file: UploadFile = File(...),
    ctx: OrgContext = Depends(require_permission("manage_templates")),
    db: AsyncSession = Depends(get_db),
):
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".docx"):
        raise ValidationFailedError("Upload a .docx file")
    data = await file.read()
    template, doc_row = await docx_template_service.create_docx_template(
        db, ctx, program_id=program_id, name=name,
        filename=filename, data=data, make_current=make_current,
    )
    await db.commit()
    return {
        "id": template.id, "name": template.name, "version": template.version,
        "kind": template.kind, "is_current": template.is_current,
        "doc_id": doc_row.id, "index_kind": doc_row.index_kind,
        "blocks": len(doc_row.outline_json.get("blocks", [])),
    }
```

`preview` builds a sample fill with obviously-fake values (`"Sample School"`, `"Ms Example"`) and a two-row price table, calls `docx_fill.apply` **without** any model call — a preview must not spend tokens or vary between runs — and returns the PDF with `Content-Disposition: inline`.

`media` reads the named part straight out of the stored zip, refusing any name that is not in `outline_json["media"]`, so the route cannot be walked.

- [ ] **Step 3: Add `filled_json` to the proposal read**

In `app/api/proposals.py::_proposal_dict`, add:

```python
        "template_kind": p.template_kind,
        "filled": p.filled_json or [],
```

- [ ] **Step 4: Run and commit**

```bash
.venv/bin/python -m pytest tests/docx/test_api.py -q
.venv/bin/python -m pytest -q
git add app/api/admin.py app/api/proposals.py tests/docx/test_api.py
git commit -m "feat(api): docx template upload, plan editing, preview and media"
```

- [ ] **Step 5: End-to-end against a real document, on the VM**

```bash
.venv/bin/python - <<'PY'
import asyncio, io
from pathlib import Path
from docx import Document
from app.services.docx import outline as ol, fill, convert
from app.services.docx import text as dt

data = Path("data/samples/School_YuviPep 360_2 1.docx").read_bytes()
out = ol.parse(data)
heading = next(b for b in out["blocks"] if b["kind"] == "heading")
ref = next(b for b in out["blocks"] if b["kind"] == "paragraph" and len(b["text"]) > 60)
plan = {"version": 1, "entries": [
    {"kind": "token", "key": "client_name", "literal": "School School"},
    {"kind": "insert", "key": "greeting", "after": heading["path"],
     "fingerprint": heading["fingerprint"], "style_ref": ref["path"],
     "shape": "paragraph", "brief": "greeting", "max_words": 90, "required": True},
]}
res = fill.apply(data, plan, {"client_name": "Greenwood International School",
                              "greeting": "We are delighted to present this proposal."})
doc = Document(io.BytesIO(res["docx"]))
print("leftover literal:", dt.count_token(doc, "School School"))
print("media:", len(doc.part.package.image_parts), "sections:", len(doc.sections))
pdf = convert.docx_to_pdf(res["docx"])
Path("/tmp/e2e.pdf").write_bytes(pdf)
print("pdf bytes:", len(pdf))
PY
```

Expected: `leftover literal: 0`, `media: 33`, `sections: 23`, a multi-megabyte PDF. Open `/tmp/e2e.pdf` and look at it — the cover, the images and the index must all still be there. **This is the step where a human confirms the branding survived; do not mark the task done without doing it.**

---

## Phase 4 — The setup console

All console work happens in `Dashboard/`. Read `Dashboard/READMEs/06_DESIGN.md` §5 and `Dashboard/src/ui/ItemScreen.tsx` before writing a component: this console has a house style (Section / Banner / Field / primitives, tokens.css, no ad-hoc colours) and a conformance test that enforces it.

### Task 18: Regenerate the API client and add the endpoints

**Files:**
- Modify: `Dashboard/src/api/openapi.json`, `Dashboard/src/api/generated.ts`, `Dashboard/src/api/endpoints.ts`, `Dashboard/src/api/reads.ts`

**Interfaces:**
- Produces: `endpoints.proposalTemplatesDocx(programId)`, `endpoints.templateDoc(docId)`, `endpoints.templateDocSuggest(docId)`, `endpoints.templateDocPlan(docId)`, `endpoints.templateDocPreview(docId)`, `endpoints.templateDocMedia(docId, name)`; zod shape `TemplateDocRead`.

- [ ] **Step 1: Start the backend and dump the schema**

```bash
cd /home/telaverge/Ekaghni/Salesforce_AI_Project/Backend_Codebase/Salesforce_AI/Complete_Project
.venv/bin/python Dashboard/tools/dump_openapi.py > Dashboard/src/api/openapi.json
git diff --stat Dashboard/src/api/openapi.json
```

- [ ] **Step 2: Regenerate and check**

```bash
cd Dashboard
npm run gen:api
npm run gen:check      # must exit 0; `prebuild` runs it, so a red check blocks the build
npx tsc --noEmit
```

- [ ] **Step 3: Add the routes to `endpoints.ts`**, in the Catalogue block beside the existing `proposalTemplates`:

```ts
  proposalTemplatesDocx: (programId: string) =>
    `${V1}/admin/programs/${programId}/proposal-templates/docx`,
  templateDoc: (docId: string) => `${V1}/admin/proposal-template-docs/${docId}`,
  templateDocSuggest: (docId: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/suggest`,
  templateDocPlan: (docId: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/plan`,
  templateDocPreview: (docId: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/preview`,
  templateDocMedia: (docId: string, name: string) =>
    `${V1}/admin/proposal-template-docs/${docId}/media/${encodeURIComponent(name)}`,
```

None of these is super-admin, so `SUPER_ONLY` is unchanged — but add a line to the file's comment saying they were checked, because that table claims to be verified rather than guessed.

- [ ] **Step 4: Add the read shape to `reads.ts`**, following the existing zod style exactly:

```ts
export const BlockRead = z.object({
  id: z.string(), path: z.string(), kind: z.string(), style: z.string(),
  level: z.number().nullable(), text: z.string(),
  images: z.array(z.string()), table: z.object({
    rows: z.number(), cols: z.number(),
    header: z.array(z.string()), sample: z.array(z.array(z.string())),
  }).nullable(),
  fingerprint: z.string(),
});

export const TemplateDocRead = z.object({
  id: z.string(), template_id: z.string(), filename: z.string(),
  index_kind: z.enum(["field", "static", "none"]),
  analysis_status: z.string(), analysis_error: z.string().nullable(),
  outline: z.object({
    blocks: z.array(BlockRead),
    headings: z.array(z.object({ id: z.string(), path: z.string(),
                                 level: z.number().nullable(), text: z.string() })),
    tokens: z.array(z.object({ literal: z.string(), occurrences: z.number(),
                               sample_block_ids: z.array(z.string()) })),
    media: z.array(z.string()),
  }),
  plan: z.object({ version: z.number(), entries: z.array(z.record(z.unknown())) }),
});
```

- [ ] **Step 5: Commit**

```bash
git add Dashboard/src/api/openapi.json Dashboard/src/api/generated.ts \
        Dashboard/src/api/endpoints.ts Dashboard/src/api/reads.ts
git commit -m "feat(console): generated client and endpoints for docx templates"
```

---

### Task 19: The mode switch on item 6

**Files:**
- Modify: `Dashboard/src/screens/ProposalTemplates.tsx`, `Dashboard/src/descriptors/catalogue.ts`
- Create: `Dashboard/src/screens/docx/DocxUpload.tsx`

- [ ] **Step 1: Add the mode switch**

Keep the existing Markdown form exactly as it is — it is the default and one of the two things this screen already does well. Add a two-option control above "Publish a new version":

```tsx
const [mode, setMode] = useState<"markdown" | "docx">("markdown");
```

Render the existing `<EntityForm>` when `mode === "markdown"` and `<DocxUpload programId={chosen} />` when `mode === "docx"`. Explain the difference in a `Banner` in the console's own voice:

> **Two ways to write a template.** A Markdown body is written here and rendered into a plain document. A Word document is uploaded as it is — its cover, images, headers and footers are kept exactly, and you mark where the system should fill things in. Use the Word document when the proposal has a designed look worth keeping.

- [ ] **Step 2: Show which kind each version is**

In the `VersionHistory` summary, replace the character-count line with:

```tsx
<span className={s.muted}>
  {t.kind === "docx" ? " · Word document" : ` · ${t.body_md.length} characters`}
</span>
```

- [ ] **Step 3: Build the upload component**

`DocxUpload.tsx`: a name field, a file input restricted to `.docx`, a size guard at 25 MB shown before the request rather than after, and a submit that posts `FormData` to `endpoints.proposalTemplatesDocx(programId)`. On success it routes to the editor for the returned `doc_id`. Show `index_kind` in the success banner, in words:

- `static` — "This document's contents page is plain text, so its page numbers are refreshed when a proposal is produced."
- `field` — "This document has a Word contents field; Word will refresh it when the file is opened."
- `none` — nothing.

Errors come back as the backend's own message (`asApiError(...).detail`), which is already written for a human.

- [ ] **Step 4: Refuse to let the bundle silently downgrade a docx template**

This closes the gap noted in Task 12 Step 9. In `Dashboard/src/bundle/export.ts`, when a `proposalTemplates` row has `kind === "docx"`, exclude it from the export and record it in the export's summary as skipped, with the reason:

> "A Word-document template cannot travel in a bundle — the document itself is not part of it. Re-upload the .docx in the target organisation."

In `Dashboard/src/import/validate.ts`, if a `proposalTemplates` row would supersede a current template whose `kind` is `docx`, raise a validation failure rather than a warning. Silently replacing a branded template with a text one is precisely the failure mode this feature exists to remove.

Add tests to `Dashboard/src/bundle/roundtrip.test.ts` and `Dashboard/src/import/validate.test.ts` covering both.

- [ ] **Step 5: Update the descriptor**

In `catalogue.ts`, add to `proposalTemplates`:

```ts
  reimport: "creates a NEW version and supersedes the current one; " +
    "Word-document templates are not carried in a bundle and must be re-uploaded",
```

and add a `kind` field to the read so `conformance.test.ts` stays honest about what the screen displays.

- [ ] **Step 6: Verify and commit**

```bash
cd Dashboard && npm test && npx tsc --noEmit
git add Dashboard/src/screens/ProposalTemplates.tsx Dashboard/src/screens/docx/DocxUpload.tsx \
        Dashboard/src/descriptors/catalogue.ts Dashboard/src/bundle/export.ts \
        Dashboard/src/import/validate.ts Dashboard/src/bundle/roundtrip.test.ts \
        Dashboard/src/import/validate.test.ts
git commit -m "feat(console): upload a Word document as a proposal template"
```

---

### Task 20: The editor

**Files:**
- Create: `Dashboard/src/screens/docx/DocxEditor.tsx`, `BlockFlow.tsx`, `SuggestionChip.tsx`, `plan.ts`
- Create: `Dashboard/src/screens/docx/plan.test.ts`

**Interfaces:**
- Produces, in `plan.ts` (pure, therefore unit-tested without React):
  - `type PlanEntry`, `type Plan`
  - `acceptSuggestion(plan, suggestion): Plan`
  - `rejectSuggestion(plan, key): Plan`
  - `updateBrief(plan, key, brief): Plan`
  - `moveEntry(plan, key, direction, blocks): Plan`
  - `addInsert(plan, afterPath, styleRefPath, blocks): Plan`
  - `entriesForBlock(plan, path): PlanEntry[]`

- [ ] **Step 1: Write the pure-logic tests first** (`plan.test.ts`), covering: accepting a suggestion adds exactly one entry; accepting twice does not duplicate; rejecting removes it; `moveEntry` re-anchors to the previous/next block and refuses to move past the ends; `addInsert` picks the nearest preceding body paragraph as `style_ref` and fails clearly when there is none; `entriesForBlock` returns entries anchored at that path in stable order.

- [ ] **Step 2: Build `BlockFlow.tsx`**

Renders the outline as a vertical flow. Per block kind:

- `heading` — the text at a weight matching its level, with the level shown small and muted.
- `paragraph` — the text, clamped to about six lines with a "show all" toggle.
- `table` — a real `<table>` of the sample rows inside an `overflow-x: auto` wrapper, with the full row/column count stated.
- `image` — an `<img>` at `endpoints.templateDocMedia(docId, name)`, `max-width: 100%`, `loading="lazy"`, with the OCR text beneath in muted small type when there is any. A document with 33 images is a lot to load at once; lazy loading is not optional here.
- `empty` — a thin spacer, so the document's rhythm is visible without noise.

Between every pair of blocks, an insertion affordance. 196 blocks renders fine without virtualisation; do not add any.

- [ ] **Step 3: Build `SuggestionChip.tsx`**

Green, clearly distinct from the document's own content, carrying the `key`, the editable `brief`, the word budget, `required`, the model's `why` and its confidence. Actions: Accept, Reject, Edit brief, Move up, Move down. An accepted entry stays visible in place but changes from "suggested" to "placed" — the administrator needs to see the finished shape of the document, not a list of decisions they have already made.

Colour comes from `tokens.css`. If there is no green token, add one there rather than inlining a hex value; `tokens.test.ts` enforces this.

- [ ] **Step 4: Build `DocxEditor.tsx`**

Composes the above with:
- a header naming the template, its version and its `index_kind`;
- **Suggest placeholders**, calling `templateDocSuggest`, showing a spinner and a plain-language note that this asks the model and takes a few seconds;
- the token panel (Task 21);
- **Save plan**, `PUT`ing to `templateDocPlan`, rendering any returned `problems` array as a `Banner` with one line per problem;
- **Preview with sample data**, opening the returned PDF in a new tab;
- an unsaved-changes guard on navigation.

- [ ] **Step 5: Register the route** in `Dashboard/src/app/router.tsx` as `/item/6/doc/:docId`.

- [ ] **Step 6: Verify and commit**

```bash
cd Dashboard && npm test && npx tsc --noEmit && npm run build
git add Dashboard/src/screens/docx Dashboard/src/app/router.tsx Dashboard/src/ui/tokens.css
git commit -m "feat(console): the placeholder editor"
```

---

### Task 21: Token panel and table binding

**Files:**
- Create: `Dashboard/src/screens/docx/TokenPanel.tsx`, `TableBinding.tsx`
- Modify: `Dashboard/src/screens/docx/DocxEditor.tsx`

- [ ] **Step 1: `TokenPanel.tsx`**

A table of `outline.tokens`: the literal, its occurrence count, and a `Select` of the bindable fields (`client_name`, `contact_name`, `contact_title`, `sender_name`, `sender_email`, `org_name`, `program_name`, `program_description`, `date`, `total_amount`) plus "not a placeholder". Show the occurrence count prominently — binding `School Name` in `Essential Lab.docx` changes **seven** places, and an administrator should know that before they save, not after.

Include a free-text "add a literal we did not detect" row: the detector is deliberately narrow (two to five Title-Case words) and will miss things like `<Client>` or `XXX`. Validate a typed literal by checking it appears in `outline.blocks`, and say so plainly when it does not.

- [ ] **Step 2: `TableBinding.tsx`**

Opened from a table block. Shows the table's real header row and sample rows, and per column a `Select` of `label`, `unit`, `unit_price`, `quantity`, `line_total`, "leave as is". Plus: how many header rows to keep verbatim, and which row is the total (with its label column and value column). Preview the mapping against two dummy line items directly in the dialog so the mapping is visibly right before it is saved.

- [ ] **Step 3: Verify and commit**

```bash
cd Dashboard && npm test && npx tsc --noEmit && npm run build
git add Dashboard/src/screens/docx
git commit -m "feat(console): token binding panel and rate-card table mapping"
```

---

## Phase 5 — The Android app

### Task 22: Show what the AI wrote

**Files:**
- Modify: `app/src/main/java/com/yuvipep/app/core/net/dto/ProposalDetailDto.java`
- Modify: `app/src/main/java/com/yuvipep/app/feature/proposals/ProposalDetailFragment.java`
- Modify: `app/src/main/res/layout/fragment_proposal_detail.xml`, `app/src/main/res/values/strings.xml`

Working directory for this task is the Android project: `C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI`.

- [ ] **Step 1: Extend the DTO**

```java
    @SerializedName("template_kind") public String templateKind;
    @SerializedName("filled") public List<Filled> filled;

    /** One placeholder in a document-template proposal (backend `filled_json`). */
    public static class Filled {
        @SerializedName("key")    public String key;
        @SerializedName("kind")   public String kind;
        /** "system" (from your records), "ai" (written for this client), "unfilled". */
        @SerializedName("source") public String source;
        @SerializedName("text")   public String text;
        @SerializedName("brief")  public String brief;
        @SerializedName("anchor") public String anchor;
    }
```

- [ ] **Step 2: Add the layout section**

A `MaterialCardView` after the existing content view, `android:visibility="gone"` by default, holding a title and a vertical `LinearLayout` the fragment populates.

- [ ] **Step 3: Populate it**

Show the section only when `templateKind` is `"docx"` and `filled` is non-empty. Per entry, one row: the placeholder's brief (falling back to its key), the text, and a small label for its source. Order `unfilled` first — those are what block the send.

Strings in `strings.xml`, never inline, matching the app's existing voice:

```xml
<string name="proposal_filled_title">What went into this proposal</string>
<string name="proposal_filled_ai">Written for this client</string>
<string name="proposal_filled_system">From your records</string>
<string name="proposal_filled_unfilled">Left blank — needs you</string>
<string name="proposal_filled_empty_hint">This section could not be written from what is on record. Fill it in before sending.</string>
```

- [ ] **Step 4: Build and verify no regression**

```powershell
cd C:\Users\Ekaghni\AndroidStudioProjects\YuvipepSalesforceAI
$env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat :app:assembleOrgDebug
.\gradlew.bat :app:testOrgDebugUnitTest
```

Both must succeed. A markdown-template proposal must look exactly as it does today — the new card stays hidden.

- [ ] **Step 5: List the changed files (there is no commit)**

**Verified 2026-09-03: the Android project is NOT a git repository** -
`git rev-parse --show-toplevel` fails at the project path. There is nothing to
commit to. End the task by listing every file changed, with a one-line
description of each, in the report. The Gradle build in Step 4 is the only
verification this task has, so it is not optional.

---

## Phase 6 — Documentation

### Task 23: Record what changed, and why the freeze was reopened

**Files:**
- Modify: `Dashboard/READMEs/09_BACKEND_CHANGES.md`, `Dashboard/READMEs/08_PROGRESS_AND_HANDOFF.md`, `BACKEND_README.md`

- [ ] **Step 1: Add the fifth unfreeze to the freeze history table in `09`**

```markdown
| 5 | **DOCX proposal templates** — owner-directed, 2026-09-03. Ten additive changes (11–20 below), a new subsystem rather than an amendment to the ten. | open |
```

Correct the paragraph that says "The list is now closed at ten" — it is no longer true, and this file claims to be *the authority* on what has actually changed. Say plainly that the owner reopened it on 2026-09-03 for a feature the console could not deliver against the frozen surface, and that the original ten remain closed as their own set.

- [ ] **Step 2: Add the change table** — the ten rows from §13 of the spec, in the same format as the existing table, each with its files and the task that made it.

- [ ] **Step 3: Record the design decisions** in `05_DECISIONS.md` style, at least:
- **D25** — DOCX templates sit alongside Markdown, discriminated by `kind`; `body_md` holds a text projection so every existing consumer is untouched.
- **D26** — the uploaded document is immutable; a proposal is `source + plan + values -> new file`.
- **D27** — text access goes through `docx/text.py`, never `Paragraph.runs`, with the measured miss counts (4/7, 1/7, 1/9, 2/14) as the reason.
- **D28** — no sample document has a live TOC field; the static two-pass page refresh is the primary index mechanism.
- **D29** — a docx template is excluded from the bundle rather than exported as its text projection.
- **D30** — the prose fence is code (`fill_scrub`), not prompt wording, continuing F9/F4/F23/F28.

- [ ] **Step 4: Update `BACKEND_README.md`** where it documents proposal templates and the proposal build path, and add the two system dependencies to its environment section.

- [ ] **Step 5: Commit**

```bash
git add Dashboard/READMEs/09_BACKEND_CHANGES.md Dashboard/READMEs/08_PROGRESS_AND_HANDOFF.md \
        Dashboard/READMEs/05_DECISIONS.md BACKEND_README.md
git commit -m "docs: record the fifth unfreeze and the docx template subsystem"
```

---

## Final verification

- [ ] **Backend suite green**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/docx -q
```

- [ ] **Console green and building**

```bash
cd Dashboard && npm test && npm run gen:check && npx tsc --noEmit && npm run build
```

- [ ] **App building**

```powershell
.\gradlew.bat :app:assembleOrgDebug
```

- [ ] **A real proposal, looked at by a human.** Through the console: upload `Essential Lab.docx`, run Suggest, accept the client-name token and one greeting insert, bind the pricing table, save, Preview. Then from the app, ask Jarvis to create a proposal for a seeded lead on that program, and open the PDF. Confirm by eye: the cover art is there, the images are there, the headers and footers are there, `School Name` appears nowhere, the price table matches the rate card, and the greeting reads like a person wrote it. Repeat with `School_YuviPep 360_2 1.docx` and additionally confirm the contents page numbers point at the right pages.

- [ ] **Leave the pre-existing work alone.** `git status --porcelain` must still show the 89 unrelated paths from `feature/pre-sales-cold-calling` as modified/untracked, and none of them may appear in any commit made by this plan:

```bash
git log --name-only feature/pre-sales-cold-calling..HEAD | sort -u > /tmp/touched.txt
comm -12 /tmp/touched.txt <(sort backup_2026_09_03_docx_templates/GIT_STATUS_BEFORE.txt | cut -c4-)
```

Expected: only `app/api/admin.py` and `app/api/proposals.py` if they were already dirty — check the diff of those two by hand before considering the work finished.
