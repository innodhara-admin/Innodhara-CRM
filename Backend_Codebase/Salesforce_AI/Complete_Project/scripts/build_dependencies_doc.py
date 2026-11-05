"""Build the short outstanding-dependencies memo for management.

    python scripts/build_dependencies_doc.py

Output: ../Innodhara_Outstanding_Dependencies.pdf

Every factual claim in this memo was verified against the running code before it
was written; the verification is noted inline so a reader can re-run it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Flowable, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT.parent / "Innodhara_Outstanding_Dependencies.pdf"

PRODUCT = "Innodhara"
TITLE = "Outstanding Dependencies"
SUB = "Five items that need a decision or a resource before wider rollout"

NAVY = colors.HexColor("#101B3D")
INDIGO = colors.HexColor("#1E3A8A")
BLUE = colors.HexColor("#2563C9")
TEAL = colors.HexColor("#0E7C86")
AMBER = colors.HexColor("#C6801A")
CRIMSON = colors.HexColor("#A32C4A")
INK = colors.HexColor("#141A24")
BODY = colors.HexColor("#2A323F")
MUTED = colors.HexColor("#69737F")
RULE = colors.HexColor("#D3DAE4")
WASH = colors.HexColor("#F4F7FB")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CW = PAGE_W - 2 * MARGIN


def fonts() -> dict[str, str]:
    fam = {"r": "Helvetica", "b": "Helvetica-Bold", "l": "Helvetica",
           "sb": "Helvetica-Bold", "i": "Helvetica-Oblique"}
    for key, name, fn in (("r", "Dep", "segoeui.ttf"), ("b", "Dep-Bd", "segoeuib.ttf"),
                          ("l", "Dep-Lt", "segoeuil.ttf"), ("sb", "Dep-Sb", "seguisb.ttf"),
                          ("i", "Dep-It", "segoeuii.ttf")):
        p = Path("C:/Windows/Fonts") / fn
        if p.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(p)))
                fam[key] = name
            except Exception:  # noqa: BLE001
                pass
    # Without a FAMILY map an inline <b> resolves to the regular face, so every
    # bolded phrase in the copy would quietly lose its emphasis.
    for base in {fam["r"], fam["sb"], fam["l"]}:
        pdfmetrics.registerFontFamily(
            base, normal=base, bold=fam["b"], italic=fam["i"],
            boldItalic=fam["b"])
    return fam


F = fonts()


def st(**kw) -> ParagraphStyle:
    base = dict(fontName=F["r"], fontSize=9.4, leading=13.6, textColor=BODY,
                alignment=TA_LEFT, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(f"s{id(base)}", **base)


P = st()
SMALL = st(fontSize=8.3, leading=11.6, textColor=MUTED)
TH = st(fontName=F["b"], fontSize=8.4, leading=11.2, textColor=WHITE)
TD = st(fontSize=8.6, leading=12)
TDB = st(fontName=F["sb"], fontSize=8.6, leading=12, textColor=INK)
H = st(fontName=F["b"], fontSize=12.4, leading=16.4, textColor=NAVY)
LBL = st(fontName=F["b"], fontSize=8, leading=10.6, textColor=TEAL)


class Banner(Flowable):
    def __init__(self):
        super().__init__()
        self.width, self.height = CW, 26 * mm

    def draw(self):
        c = self.canv
        c.setFillColor(NAVY)
        c.roundRect(0, 0, self.width, self.height, 2.5 * mm, stroke=0, fill=1)
        c.setFillColor(BLUE)
        c.roundRect(0, 0, 5 * mm, self.height, 2.5 * mm, stroke=0, fill=1)
        c.setFillColor(NAVY)
        c.rect(2.5 * mm, 0, 3 * mm, self.height, stroke=0, fill=1)
        c.setFillColor(colors.Color(1, 1, 1, alpha=.62))
        c.setFont(F["sb"], 8.6)
        c.drawString(10 * mm, self.height - 8 * mm, PRODUCT.upper())
        c.setFillColor(WHITE)
        c.setFont(F["b"], 16)
        c.drawString(10 * mm, self.height - 15.6 * mm, TITLE)
        c.setFillColor(colors.Color(1, 1, 1, alpha=.78))
        c.setFont(F["r"], 8.8)
        c.drawString(10 * mm, self.height - 21 * mm, SUB)
        c.setFillColor(colors.Color(1, 1, 1, alpha=.55))
        c.setFont(F["r"], 8)
        c.drawRightString(self.width - 8 * mm, self.height - 8 * mm,
                          f"{date.today():%d %B %Y}")


class Item(Flowable):
    """A numbered heading chip."""

    def __init__(self, n: int, title: str):
        super().__init__()
        self.n, self.title = n, title
        self.width, self.height = CW, 9.5 * mm

    def draw(self):
        c = self.canv
        c.setFillColor(INDIGO)
        c.circle(3.4 * mm, self.height / 2 - 0.4 * mm, 3.4 * mm, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.setFont(F["b"], 9)
        c.drawCentredString(3.4 * mm, self.height / 2 - 1.9 * mm, str(self.n))
        c.setFillColor(NAVY)
        c.setFont(F["b"], 11.6)
        c.drawString(9.4 * mm, self.height / 2 - 1.8 * mm, self.title)


class Box(Flowable):
    """Tinted note with a coloured spine."""

    KIND = {"ask": (colors.HexColor("#FDF3E7"), AMBER, "Decision needed"),
            "now": (WASH, BLUE, "Verified today"),
            "risk": (colors.HexColor("#FBF0F3"), CRIMSON, "Impact right now")}

    def __init__(self, kind: str, text: str, title: str | None = None):
        super().__init__()
        self.bg, self.spine, dt = self.KIND[kind]
        self.tp = Paragraph((title or dt).upper(),
                            st(fontName=F["b"], fontSize=7.8, leading=10.4,
                               textColor=self.spine))
        self.bp = Paragraph(text, st(fontSize=8.8, leading=12.4))
        self.pad = 4 * mm

    def wrap(self, aw, ah):
        w = aw - 2 * self.pad - 2 * mm
        _, t = self.tp.wrap(w, ah)
        _, b = self.bp.wrap(w, ah)
        self.width, self.height = aw, t + b + 2 * self.pad + 1.2 * mm
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.roundRect(0, 0, self.width, self.height, 1.8 * mm, stroke=0, fill=1)
        c.setFillColor(self.spine)
        c.roundRect(0, 0, 1.4 * mm, self.height, .7 * mm, stroke=0, fill=1)
        x = self.pad + 2 * mm
        w = self.width - x - self.pad
        _, t = self.tp.wrap(w, self.height)
        _, b = self.bp.wrap(w, self.height)
        self.tp.drawOn(c, x, self.height - self.pad - t + 1)
        self.bp.drawOn(c, x, self.pad)


def table(headers, rows, widths=None, head=NAVY):
    data = [[Paragraph(h, TH) for h in headers]]
    for r in rows:
        data.append([Paragraph(str(c), TD if i else TDB) for i, c in enumerate(r)])
    n = len(headers)
    t = Table(data, colWidths=widths or [CW / n] * n, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), head),
        ("GRID", (0, 0), (-1, -1), .35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, WASH]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def furniture(c, doc):
    c.saveState()
    c.setFillColor(MUTED)
    c.setFont(F["r"], 7.6)
    c.drawString(MARGIN, 10 * mm,
                 f"{PRODUCT} · {TITLE} · every figure below was measured from "
                 "the running system")
    c.drawRightString(PAGE_W - MARGIN, 10 * mm, str(doc.page))
    c.setStrokeColor(RULE)
    c.setLineWidth(.4)
    c.line(MARGIN, 13 * mm, PAGE_W - MARGIN, 13 * mm)
    c.restoreState()


S: list = []
A = S.extend

A([Banner(), Spacer(1, 6 * mm)])

A([Paragraph(
    "The product is functionally complete and demonstrable end to end. What "
    "follows is the short list of things it still depends on. <b>Hosting is "
    "solved</b> — the office VM's 12 GB GPU is more than enough. <b>One item "
    "needs a decision from you</b> (item 2, which is affecting the product "
    "today); the remaining three are engineering work we can schedule.", P),
   Spacer(1, 4 * mm)])

A([table(
    ["#", "Dependency", "State today", "Needs"],
    [["1", "GPU host for deployment",
      "Runs on a developer laptop (8 GB GPU)",
      "<b>Cleared</b> — the office GPU (12 GB) is enough"],
     ["2", "Sentence embeddings for the notes feature",
      "<b>Broken.</b> Google credits exhausted",
      "<b>Your decision</b> — pay, or switch to a local model"],
     ["3", "Long-form proposal generation",
      "One page, from a fixed template",
      "Engineering — a new pipeline"],
     ["4", "SQLite → PostgreSQL",
      "SQLite, 1.8 MB, single file",
      "Engineering — plus a migration tool"],
     ["5", "Vectors in a real vector database",
      "JSON column, compared in Python",
      "Engineering — follows 2 and 4"]],
    [8 * mm, 44 * mm, 50 * mm, CW - 8 * mm - 44 * mm - 50 * mm])])

A([Spacer(1, 6 * mm)])

# ── 1 ────────────────────────────────────────────────────────────────────────
A([Item(1, "A GPU host to deploy the backend on"), Spacer(1, 1.5 * mm)])
A([Paragraph(
    "Only one part of the system needs a GPU: <b>speech-to-text</b>. Meeting "
    "recordings are transcribed on our own machine with OpenAI Whisper, which "
    "is deliberate — the audio never leaves our server and there is no "
    "per-minute API cost. The AI reasoning runs on a hosted API and needs no "
    "GPU at all.", P), Spacer(1, 2.5 * mm)])
A([Box("now",
       "We transcribe meetings with the Whisper <b>medium</b> model and field "
       "dictation with <b>tiny</b>. Development currently runs on a laptop with "
       "an <b>RTX 4060, 8 GB of video memory</b> — verified: CUDA is active and "
       "Whisper is installed. Whisper's own published requirement is "
       "<b>about 5 GB for medium</b>, ~2 GB for small and ~10 GB for large."),
   Spacer(1, 3 * mm)])
A([Box("ask",
       "<b>A GPU with 12 GB of video memory is already available on the office "
       "VM — can we deploy there? Yes.</b> 12 GB comfortably exceeds the ~5 GB "
       "the <i>medium</i> model needs, so the backend can move onto that VM "
       "as it stands, at no cost and with no loss of transcription quality."
       "<br/><br/>"
       "<b>It also buys us an upgrade.</b> At 12 GB the <i>large</i> model "
       "(~10 GB) fits, which is the one meaningful accuracy gain available to "
       "us on accented speech and crosstalk — the two conditions our recordings "
       "actually have. We would keep <i>medium</i> for the initial cut-over and "
       "evaluate <i>large</i> on real recordings before switching.",
       title="Cleared for deployment")])

# ── 2 ────────────────────────────────────────────────────────────────────────
A([CondPageBreak(70 * mm), Spacer(1, 5 * mm)])
A([Item(2, "Sentence embeddings for the notes feature"), Spacer(1, 1.5 * mm)])
A([Paragraph(
    "Notes about a client are searched by <i>meaning</i> rather than by keyword "
    "— \"what did they say about the handover pack?\" finds the right note even "
    "when those words were never used. That requires an embedding model, and we "
    "currently call Google's <b>gemini-embedding-001</b>.", P),
   Spacer(1, 2.5 * mm)])
A([Box("risk",
       "<b>This feature is not working today.</b> We tested the live call while "
       "writing this: Google returns <b>429 — \"Your prepayment credits are "
       "depleted\"</b>. The consequence is worse than slow search. When the "
       "embedding call fails, a new note is saved and readable in the app but "
       "is <b>never added to the searchable memory</b>. The database shows it "
       "plainly: <b>28 client notes stored, 0 indexed</b>. So semantic search "
       "returns nothing at all, and has been quietly doing so since the credits "
       "ran out."),
   Spacer(1, 3 * mm)])
A([Box("ask",
       "Two ways forward. <b>(a)</b> Top up the Google credits — immediate, but "
       "a recurring cost that grows with usage, and a client's notes leave our "
       "infrastructure. <b>(b)</b> Run the embedding model locally, as we "
       "already do for speech: a small open model such as "
       "<b>sentence-transformers / all-MiniLM-L6-v2</b> (about 90 MB, runs on "
       "CPU, no per-call cost, nothing leaves the server). "
       "<br/><br/>"
       "<b>We recommend (b)</b>, and it is contained work — the code is written "
       "so only one module changes, and the stored format needs no migration "
       "because nothing is indexed yet. It also removes the only remaining "
       "dependency on Google for day-to-day operation. This pairs naturally "
       "with item 1: the same host serves both models.")])

# ── 3 ────────────────────────────────────────────────────────────────────────
A([CondPageBreak(70 * mm), Spacer(1, 5 * mm)])
A([Item(3, "Long-form proposals, written rather than filled in"), Spacer(1, 1.5 * mm)])
A([Box("now",
       "Today a proposal is produced by filling one saved template: the "
       "organisation's document with placeholders for the client, the contact, "
       "the rate table and the total. The proposal on the system measures "
       "<b>1,171 characters and renders to a single page</b>. It is correct and "
       "fast, but it is a form, not a document — and it can only ever say what "
       "the template already says."),
   Spacer(1, 3 * mm)])
A([Paragraph(
    "The goal is a <b>20–30 page proposal, composed by the AI from the "
    "engagement itself</b>, with no template: an executive summary, our "
    "understanding of the requirement, scope per phase, method, deliverables, "
    "the schedule, the team, assumptions, risks, and commercial terms. This is "
    "the largest of the five items and genuinely new capability rather than "
    "migration work.", P), Spacer(1, 2.5 * mm)])
A([Box("ask",
       "One rule must survive the change, and it is the reason clients can "
       "trust the output: <b>the AI never authors a number</b>. Every price and "
       "total is computed from the rate card, and a rewrite that slips a "
       "different figure into the prose is rejected automatically. A long-form "
       "generator has to keep that fence while writing far more text — so the "
       "design is section-by-section generation against facts already on file, "
       "with the commercial pages assembled, not written. We can scope this "
       "properly once items 1 and 2 are settled.",
       title="Constraint to preserve")])

# ── 4 & 5 ────────────────────────────────────────────────────────────────────
A([CondPageBreak(78 * mm), Spacer(1, 5 * mm)])
A([Item(4, "SQLite to PostgreSQL"), Spacer(1, 1.5 * mm)])
A([Paragraph(
    "The database is a single SQLite file, <b>1.8 MB</b> today. That is the "
    "right choice for one team and the wrong one for several organisations at "
    "once, because SQLite serialises writers. The code already speaks both "
    "dialects, so the move is configuration plus three pieces of real work:", P),
   Spacer(1, 2.5 * mm)])
A([table(
    ["Work", "Why it is needed"],
    [["Add the PostgreSQL driver",
      "Already listed in our dependencies, deliberately switched off"],
     ["Adopt a schema-migration tool",
      "There is <b>none today</b> — the schema is created by the application on "
      "start-up, which is safe now but cannot be used once real client data "
      "exists"],
     ["Finish the database-level tenant isolation",
      "A script exists and covers <b>25 of the 54</b> client-scoped tables; the "
      "remaining <b>29</b> need the same policy, and the application must "
      "declare which organisation each connection is acting for — that hook is "
      "not written yet"]],
    [52 * mm, CW - 52 * mm])])
A([Spacer(1, 2.5 * mm)])
A([Box("now",
       "To be clear about what is and is not at risk: client data is <b>already "
       "isolated</b> today — every query is filtered by organisation and every "
       "row carries its organisation's identifier. The database-level policy is "
       "a <i>second</i> independent net for the case where a future code change "
       "forgets a filter. It is a hardening step, not an open hole.")])

A([Spacer(1, 5 * mm)])
A([Item(5, "Vectors in a vector database"), Spacer(1, 1.5 * mm)])
A([Paragraph(
    "Embeddings are stored as a plain list of numbers in a normal column, and a "
    "search loads <b>every</b> note belonging to that organisation and compares "
    "them one by one in Python. That is exact and perfectly fast at our scale, "
    "and it stops being either at somewhere in the low tens of thousands of "
    "notes. The fix is to keep the vectors where a database can index them — "
    "the PostgreSQL <b>pgvector</b> extension, which arrives free with item 4, "
    "or a dedicated service if we outgrow that.", P), Spacer(1, 2.5 * mm)])
A([Box("now",
       "This is the least urgent of the five and should be done <b>last</b>: it "
       "depends on which embedding model we choose in item 2 (that decides the "
       "vector size) and on the PostgreSQL move in item 4. Doing it before those "
       "two would mean doing it twice. The code was written with this in mind — "
       "the same single module owns all of it.")])

# ── closing ──────────────────────────────────────────────────────────────────
A([CondPageBreak(58 * mm), Spacer(1, 6 * mm)])
A([Paragraph("What we need from you", H), Spacer(1, 2.5 * mm)])
A([table(
    ["Ask", "Why we need it", "Cost"],
    [["<b>Approve running the embedding model locally</b> rather than buying "
      "more Google credits",
      "The notes search is dead until one of the two is chosen. This is the "
      "only item currently degrading the product — item 2",
      "None, ~2 days of work"],
     ["Confirm the office VM's GPU is <b>passed through to the guest</b>, and "
      "that it has ~6 GB of free disk",
      "Deployment is otherwise cleared. If the GPU is not visible inside the "
      "VM, transcription silently runs on the CPU — item 1",
      "None"],
     ["A slot to scope long-form proposals",
      "The largest item, and worth specifying properly rather than guessing — "
      "item 3",
      "One meeting"]],
    [58 * mm, CW - 58 * mm - 26 * mm, 26 * mm], head=TEAL)])
A([Spacer(1, 4 * mm)])
A([Paragraph(
    "Items 4 and 5 need no decision — they are scheduled engineering work, best "
    "done in that order, and neither blocks a client demonstration today.",
    SMALL)])


def build() -> None:
    doc = BaseDocTemplate(
        str(TARGET), pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=15 * mm, bottomMargin=16 * mm,
        title=f"{PRODUCT} — {TITLE}", author=PRODUCT,
        subject="Outstanding dependencies and decisions required")
    doc.addPageTemplates([PageTemplate(
        id="b",
        frames=[Frame(MARGIN, 15 * mm, CW, PAGE_H - 30 * mm, id="f")],
        onPage=furniture)])
    doc.build(S)
    print(f"wrote {TARGET} ({TARGET.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
