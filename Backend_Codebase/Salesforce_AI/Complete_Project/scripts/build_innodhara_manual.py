"""Build the Innodhara product manual (client-facing PDF).

    python scripts/build_innodhara_manual.py

Output: ../Innodhara_Product_Manual.pdf

Everything in this document was written from the shipped code — the Android
navigation per role (MainActivity + RoleGate), the backend's own refusal
messages, and what the seed scripts must create before a client can use the
product. It is deliberately self-contained: all artwork is drawn as vectors and
all fonts are system fonts, so the file has no external dependencies and no
third-party licensing to clear.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT.parent / "Innodhara_Product_Manual.pdf"

PRODUCT = "Innodhara"
TAGLINE = "Automating Sales Process"
EDITION = f"Product manual · Edition {date.today():%B %Y}"

# ── palette ──────────────────────────────────────────────────────────────────
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
WASH2 = colors.HexColor("#EAF0F8")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def register_fonts() -> dict[str, str]:
    """Segoe UI where present, Helvetica otherwise."""
    fam = {"regular": "Helvetica", "bold": "Helvetica-Bold",
           "light": "Helvetica", "semi": "Helvetica-Bold",
           "italic": "Helvetica-Oblique"}
    want = [
        ("Innodhara", "segoeui.ttf", "regular"),
        ("Innodhara-Bd", "segoeuib.ttf", "bold"),
        ("Innodhara-Lt", "segoeuil.ttf", "light"),
        ("Innodhara-Sb", "seguisb.ttf", "semi"),
        ("Innodhara-It", "segoeuii.ttf", "italic"),
    ]
    for name, filename, slot in want:
        path = Path("C:/Windows/Fonts") / filename
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                fam[slot] = name
            except Exception:  # noqa: BLE001
                pass
    # Registering the faces is not enough: an inline <b> inside a Paragraph is
    # resolved through the FAMILY map, so without this every <b> in the copy
    # renders as regular weight and the emphasis silently disappears.
    for base in {fam["regular"], fam["semi"], fam["light"]}:
        pdfmetrics.registerFontFamily(
            base, normal=base, bold=fam["bold"],
            italic=fam["italic"], boldItalic=fam["bold"])
    return fam


F = register_fonts()


def S(**kw) -> ParagraphStyle:
    base = dict(fontName=F["regular"], fontSize=9.6, leading=14.2,
                textColor=BODY, alignment=TA_LEFT, spaceAfter=0)
    base.update(kw)
    name = kw.pop("_name", f"s{len(base)}{kw.get('fontSize', 0)}"
                           f"{kw.get('textColor', '')}")
    return ParagraphStyle(str(name) + str(id(base)), **base)


BODY_S = S()
LEAD_S = S(fontSize=11, leading=16.4, textColor=INK)
SMALL_S = S(fontSize=8.5, leading=12.2, textColor=MUTED)
H2_S = S(fontName=F["bold"], fontSize=14.5, leading=19, textColor=NAVY)
H3_S = S(fontName=F["semi"], fontSize=11.4, leading=15.5, textColor=INDIGO)
TH_S = S(fontName=F["bold"], fontSize=8.6, leading=11.6, textColor=WHITE)
TD_S = S(fontSize=8.9, leading=12.4)
TDB_S = S(fontName=F["semi"], fontSize=8.9, leading=12.4, textColor=INK)


# ── custom flowables ─────────────────────────────────────────────────────────
class Rule(Flowable):
    def __init__(self, width=CONTENT_W, thickness=0.6, color=RULE, gap=5):
        super().__init__()
        self.width, self.thickness, self.color, self.gap = width, thickness, color, gap
        self.height = gap

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, self.gap / 2, self.width, self.gap / 2)


class SectionOpener(Flowable):
    """A big numbered band that starts a part."""

    def __init__(self, number: str, title: str, blurb: str):
        super().__init__()
        self.number, self.title, self.blurb = number, title, blurb
        self.width = CONTENT_W
        self.height = 30 * mm

    def draw(self):
        c = self.canv
        h = self.height
        c.setFillColor(NAVY)
        c.roundRect(0, 0, self.width, h, 3 * mm, stroke=0, fill=1)
        c.setFillColor(BLUE)
        c.roundRect(0, 0, 6 * mm, h, 3 * mm, stroke=0, fill=1)
        c.setFillColor(NAVY)
        c.rect(3 * mm, 0, 4 * mm, h, stroke=0, fill=1)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.13))
        c.setFont(F["bold"], 46)
        c.drawRightString(self.width - 8 * mm, h / 2 - 15, self.number)
        c.setFillColor(WHITE)
        c.setFont(F["bold"], 15.5)
        c.drawString(12 * mm, h - 12 * mm, self.title)
        c.setFillColor(colors.Color(1, 1, 1, alpha=0.78))
        c.setFont(F["regular"], 9.2)
        text = c.beginText(12 * mm, h - 18.5 * mm)
        text.setLeading(12.4)
        for line in self.blurb.split("\n"):
            text.textLine(line)
        c.drawText(text)


class Callout(Flowable):
    """A tinted box with a coloured spine. kind: info | warn | guard | tip"""

    STYLES = {
        "info": (WASH, BLUE, "How it works"),
        "warn": (colors.HexColor("#FDF3E7"), AMBER, "Before you go live"),
        "guard": (colors.HexColor("#F2F7F7"), TEAL, "The system will refuse"),
        "tip": (colors.HexColor("#F3F1FA"), INDIGO, "Good practice"),
    }

    def __init__(self, kind: str, text: str, title: str | None = None,
                 width=CONTENT_W):
        super().__init__()
        self.bg, self.spine, default_title = self.STYLES[kind]
        self.title = title or default_title
        self.width = width
        self.pad = 5 * mm
        self.style = S(fontSize=9.1, leading=13.2, textColor=BODY)
        self.title_style = S(fontName=F["bold"], fontSize=8.4, leading=11,
                             textColor=self.spine)
        self.tp = Paragraph(self.title.upper(), self.title_style)
        self.bp = Paragraph(text, self.style)

    def wrap(self, availWidth, availHeight):
        w = availWidth - 2 * self.pad - 2 * mm
        _, th = self.tp.wrap(w, availHeight)
        _, bh = self.bp.wrap(w, availHeight)
        self.height = th + bh + 2 * self.pad + 1.5 * mm
        self.width = availWidth
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.roundRect(0, 0, self.width, self.height, 2 * mm, stroke=0, fill=1)
        c.setFillColor(self.spine)
        c.roundRect(0, 0, 1.6 * mm, self.height, 0.8 * mm, stroke=0, fill=1)
        x = self.pad + 2 * mm
        w = self.width - x - self.pad
        _, th = self.tp.wrap(w, self.height)
        _, bh = self.bp.wrap(w, self.height)
        self.tp.drawOn(c, x, self.height - self.pad - th + 1)
        self.bp.drawOn(c, x, self.pad)


class Checkbox(Flowable):
    def __init__(self, size=3.4 * mm):
        super().__init__()
        self.width = self.height = size

    def draw(self):
        c = self.canv
        c.setStrokeColor(INDIGO)
        c.setLineWidth(0.9)
        c.roundRect(0, 0, self.width, self.height, 0.6 * mm, stroke=1, fill=0)


class RoleCard(Flowable):
    def __init__(self, role: str, who: str, tabs: str, sentence: str,
                 width=CONTENT_W / 2 - 3 * mm):
        super().__init__()
        self.role, self.who, self.tabs, self.sentence = role, who, tabs, sentence
        self.width = width
        self.pad = 4 * mm
        self.role_s = S(fontName=F["bold"], fontSize=10.2, leading=13,
                        textColor=NAVY)
        self.who_s = S(fontSize=8.3, leading=11, textColor=TEAL,
                       fontName=F["semi"])
        self.tabs_s = S(fontSize=8.2, leading=11.4, textColor=INK)
        self.sent_s = S(fontSize=8.4, leading=11.8, textColor=MUTED)

    def wrap(self, availWidth, availHeight):
        w = self.width - 2 * self.pad
        self.ps = [Paragraph(self.role, self.role_s),
                   Paragraph(self.who, self.who_s),
                   Paragraph("<b>Bottom bar:</b> " + self.tabs, self.tabs_s),
                   Paragraph(self.sentence, self.sent_s)]
        self.hs = [p.wrap(w, availHeight)[1] for p in self.ps]
        self.height = sum(self.hs) + 2 * self.pad + 3.4 * mm
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(WHITE)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.7)
        c.roundRect(0, 0, self.width, self.height, 2 * mm, stroke=1, fill=1)
        c.setFillColor(BLUE)
        c.roundRect(0, self.height - 1.4 * mm, self.width, 1.4 * mm,
                    0.7 * mm, stroke=0, fill=1)
        y = self.height - self.pad
        for p, h, gap in zip(self.ps, self.hs, (0.6, 1.6, 1.2, 0)):
            y -= h
            p.drawOn(c, self.pad, y)
            y -= gap * mm


class StepFlow(Flowable):
    """A left-to-right chain of numbered steps."""

    def __init__(self, steps: list[str], width=CONTENT_W):
        super().__init__()
        self.steps = steps
        self.width = width
        self.height = 20 * mm

    def draw(self):
        c = self.canv
        n = len(self.steps)
        gap = 5 * mm
        w = (self.width - gap * (n - 1)) / n
        for i, label in enumerate(self.steps):
            x = i * (w + gap)
            c.setFillColor(WASH2)
            c.roundRect(x, 0, w, self.height, 2 * mm, stroke=0, fill=1)
            c.setFillColor(BLUE)
            c.circle(x + 6 * mm, self.height - 6 * mm, 3.1 * mm, stroke=0, fill=1)
            c.setFillColor(WHITE)
            c.setFont(F["bold"], 8)
            c.drawCentredString(x + 6 * mm, self.height - 7.1 * mm, str(i + 1))
            # Wrap to fit, then shrink the type rather than truncate — a chip
            # that silently drops its last word reads as a rendering bug.
            size = 8.1
            lines: list[str] = []
            for size in (8.1, 7.6, 7.1, 6.7):
                lines, line = [], ""
                for word in label.split():
                    trial = (line + " " + word).strip()
                    if c.stringWidth(trial, F["semi"], size) > w - 6 * mm:
                        lines.append(line)
                        line = word
                    else:
                        line = trial
                lines.append(line)
                if len(lines) <= 4:
                    break
            c.setFillColor(INK)
            c.setFont(F["semi"], size)
            ty = self.height - 11.4 * mm
            for ln in lines[:4]:
                c.drawString(x + 3.5 * mm, ty, ln)
                ty -= (size + 1.4) * 0.353 * mm
            if i < n - 1:
                c.setFillColor(RULE)
                c.setFont(F["bold"], 11)
                c.drawCentredString(x + w + gap / 2, self.height / 2 - 4, "›")


# ── table builders ───────────────────────────────────────────────────────────
def feature_table(rows: list[tuple[str, str]],
                  headers=("To do this", "Tap this")) -> Table:
    data = [[Paragraph(headers[0], TH_S), Paragraph(headers[1], TH_S)]]
    for a, b in rows:
        data.append([Paragraph(a, TDB_S), Paragraph(b, TD_S)])
    t = Table(data, colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.58],
              repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, WASH]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    return t


def grid_table(headers: list[str], rows: list[list[str]],
               widths: list[float] | None = None) -> Table:
    data = [[Paragraph(h, TH_S) for h in headers]]
    for r in rows:
        data.append([Paragraph(c, TD_S) for c in r])
    n = len(headers)
    widths = widths or [CONTENT_W / n] * n
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, WASH]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5.5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def checklist(items: list[tuple[str, str, str]]) -> Table:
    """(what to seed, why it matters, what happens without it)"""
    data = [[Paragraph("", TH_S), Paragraph("Set this up", TH_S),
             Paragraph("Why it matters", TH_S),
             Paragraph("If you skip it", TH_S)]]
    for what, why, without in items:
        data.append([Checkbox(), Paragraph(what, TDB_S),
                     Paragraph(why, TD_S),
                     Paragraph(without, S(fontSize=8.7, leading=12.2,
                                          textColor=CRIMSON))])
    t = Table(data, colWidths=[8 * mm, CONTENT_W * 0.25, CONTENT_W * 0.40,
                               CONTENT_W * 0.30],
              repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, WASH]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (0, 0), (0, -1), "CENTRE"),
    ]))
    return t


def h2(text: str) -> list:
    # Generous thresholds on purpose: a heading that lands four lines from the
    # foot of a page drags a table across the break and leaves the next page
    # four-fifths empty, which reads as a rendering fault rather than a choice.
    return [CondPageBreak(64 * mm), Spacer(1, 5 * mm),
            Paragraph(text, H2_S), Rule(gap=4), Spacer(1, 2.5 * mm)]


def h3(text: str) -> list:
    return [CondPageBreak(42 * mm), Spacer(1, 3.4 * mm),
            Paragraph(text, H3_S), Spacer(1, 1.6 * mm)]


def p(text: str, style=BODY_S) -> list:
    return [Paragraph(text, style), Spacer(1, 2.4 * mm)]


def opener(number: str, title: str, blurb: str) -> list:
    return [SectionOpener(number, title, blurb), Spacer(1, 6 * mm)]


def bullets(items: list[str]) -> list:
    out = []
    for it in items:
        out.append(Table(
            [[Paragraph("•", S(fontName=F["bold"], textColor=BLUE, fontSize=10)),
              Paragraph(it, BODY_S)]],
            colWidths=[5 * mm, CONTENT_W - 5 * mm], hAlign="LEFT",
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0.6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
            ])))
    out.append(Spacer(1, 2 * mm))
    return out


def role_grid(cards: list[RoleCard]) -> list:
    out, row = [], []
    for card in cards:
        row.append(card)
        if len(row) == 2:
            out.append(Table([row], colWidths=[CONTENT_W / 2] * 2,
                             hAlign="LEFT",
                             style=TableStyle([
                                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                 ("LEFTPADDING", (0, 0), (0, -1), 0),
                                 ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
                             ])))
            row = []
    if row:
        out.append(Table([[row[0], ""]], colWidths=[CONTENT_W / 2] * 2,
                         hAlign="LEFT",
                         style=TableStyle([
                             ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (0, -1), 0),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
                         ])))
    return out


# ── page furniture ───────────────────────────────────────────────────────────
def cover_page(c, doc):
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    # geometric accent
    c.setFillColor(colors.Color(1, 1, 1, alpha=0.045))
    for i in range(9):
        c.circle(PAGE_W * 0.86, PAGE_H * 0.80, (10 + i * 9) * mm, stroke=0, fill=1)
    c.setFillColor(INDIGO)
    c.rect(0, PAGE_H * 0.335, PAGE_W, 2.2 * mm, stroke=0, fill=1)
    c.setFillColor(BLUE)
    c.rect(0, PAGE_H * 0.335, PAGE_W * 0.34, 2.2 * mm, stroke=0, fill=1)

    c.setFillColor(colors.Color(1, 1, 1, alpha=0.72))
    c.setFont(F["semi"], 9.6)
    c.drawString(MARGIN, PAGE_H - 24 * mm, "PRODUCT MANUAL")
    c.setFont(F["regular"], 9.2)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 24 * mm, EDITION)
    c.setStrokeColor(colors.Color(1, 1, 1, alpha=0.25))
    c.setLineWidth(0.6)
    c.line(MARGIN, PAGE_H - 27 * mm, PAGE_W - MARGIN, PAGE_H - 27 * mm)

    c.setFillColor(WHITE)
    c.setFont(F["bold"], 62)
    c.drawString(MARGIN, PAGE_H * 0.53, PRODUCT)
    c.setFillColor(colors.Color(1, 1, 1, alpha=0.92))
    c.setFont(F["light"], 22)
    c.drawString(MARGIN + 1, PAGE_H * 0.53 - 13 * mm, TAGLINE)

    c.setFillColor(colors.Color(1, 1, 1, alpha=0.80))
    c.setFont(F["regular"], 11.4)
    text = c.beginText(MARGIN, PAGE_H * 0.28)
    text.setLeading(17)
    for line in (
        "A field representative records a conversation. From that alone the",
        "system builds the project, the dated plan, the staffed tasks and every",
        "message that goes back to the client — and stops at every point where",
        "judgement is required, to hand the decision to a named person.",
    ):
        text.textLine(line)
    c.drawText(text)

    c.setFillColor(colors.Color(1, 1, 1, alpha=0.55))
    c.setFont(F["regular"], 8.6)
    c.drawString(MARGIN, 16 * mm,
                 "Setup checklist · role-by-role feature guide · what the system "
                 "refuses to do")
    c.restoreState()


def body_page(c, doc):
    c.saveState()
    c.setFillColor(NAVY)
    c.setFont(F["bold"], 8.4)
    c.drawString(MARGIN, PAGE_H - 12 * mm, PRODUCT)
    c.setFillColor(MUTED)
    c.setFont(F["regular"], 8.4)
    c.drawString(MARGIN + pdfmetrics.stringWidth(PRODUCT, F["bold"], 8.4) + 4,
                 PAGE_H - 12 * mm, f"· {TAGLINE}")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm, str(doc.page))
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.line(MARGIN, PAGE_H - 14.5 * mm, PAGE_W - MARGIN, PAGE_H - 14.5 * mm)
    c.setFillColor(RULE)
    c.rect(MARGIN, 12 * mm, CONTENT_W, 0.4, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont(F["regular"], 7.6)
    c.drawString(MARGIN, 8.5 * mm,
                 "Every screen and refusal described here is the shipped "
                 "behaviour of the application.")
    c.restoreState()


def build() -> None:
    doc = BaseDocTemplate(
        str(TARGET), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=20 * mm, bottomMargin=16 * mm,
        title=f"{PRODUCT} — {TAGLINE} · Product Manual",
        author="Innodhara", subject="Product manual and go-live checklist",
    )
    frame = Frame(MARGIN, 16 * mm, CONTENT_W, PAGE_H - 36 * mm, id="body")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=cover_page),
        PageTemplate(id="body", frames=[frame], onPage=body_page),
    ])

    story: list = [NextPageTemplate("body"), PageBreak()]
    story += CONTENT
    doc.build(story)
    size = TARGET.stat().st_size // 1024
    print(f"wrote {TARGET} ({size} KB)")


# ═════════════════════════════════════════════════════════════════════════════
#  CONTENT
# ═════════════════════════════════════════════════════════════════════════════
CONTENT: list = []
A = CONTENT.extend

# ── Contents ─────────────────────────────────────────────────────────────────
A(p(f"What this manual is", H2_S))
A(p("This is the manual for the people who will use "
    f"<b>{PRODUCT}</b> every day, and for whoever sets it up before they do. "
    "It has two halves.", LEAD_S))
A([Spacer(1, 1 * mm)])
A(role_grid([]))
A([grid_table(
    ["Part", "What it covers", "Who needs it"],
    [["1", "How the product thinks — the five ideas everything rests on",
      "Everyone, once"],
     ["2", "The six roles, and what each person sees when they sign in",
      "Whoever assigns accounts"],
     ["3", "<b>The go-live checklist</b> — what must be in the system before "
      "your first client", "The administrator"],
     ["4", "The feature guide — every screen, and what each button does",
      "Every user"],
     ["5", "What the system refuses to do, and why that is the point",
      "Anyone evaluating trust"],
     ["6", "The daily and weekly rhythm", "Team leads"],
     ["7", "When something looks wrong", "Everyone"]],
    [18 * mm, CONTENT_W - 18 * mm - 42 * mm, 42 * mm])])
A([Spacer(1, 5 * mm)])
A([Callout("info",
           "The product is <b>domain-neutral</b>. Nothing in the engines, the "
           "prompts or the database assumes an industry — you describe what you "
           "sell once, in Part 3, and the same machinery runs for training, "
           "infrastructure, consulting or logistics. The words the system uses "
           "with your clients come from <i>your</i> templates and <i>your</i> "
           "rate card.")])

# ── PART 1 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("1", "How the product thinks",
         "Five ideas. Everything else in this manual is a consequence of one of\n"
         "them, so it is worth five minutes now."))

A(h3("1 · The client is the relationship. The project is the work."))
A(p("A client record holds the relationship — who they are, who works there, "
    "every note and every conversation. A <b>project</b> is one concrete piece "
    "of work for them. One client can have many projects, and each project "
    "carries its own plan, its own team and its own money."))

A(h3("2 · Every project has one living plan, and it is versioned"))
A(p("The plan is never edited in place. When something changes — a new meeting, "
    "a client reply, a slipped date — the system writes a <b>new version</b> "
    "with a plain-language summary of what changed, and the old version stays "
    "readable forever. A new version changes nothing until somebody approves "
    "it: while it waits, the live plan is untouched."))

A(h3("3 · The AI proposes. A person decides."))
A(p("The system drafts, schedules, chases and remembers. It stops at every "
    "point where judgement is required. <b>No message ever reaches your client "
    "without somebody tapping Approve</b>, and every AI decision is recorded "
    "with its reasoning, so \"why did it do that?\" always has an answer."))

A(h3("4 · Work is matched to people by recorded skill"))
A(p("Each person has skills on their record. When the plan needs a task done, "
    "the system builds a candidate list from those skills, weighs current "
    "workload, leave and travel, and picks — then writes down <i>why</i>, in a "
    "sentence the assignee can read. This is why Part 3 treats skills as "
    "non-optional."))

A(h3("5 · Nothing is destroyed"))
A(p("Plans supersede, they do not overwrite. Tasks move to done, cancelled or "
    "superseded. Proposals accumulate revisions. Every state change writes a "
    "history row. You can always reconstruct what was true on any past day."))

A([Spacer(1, 3 * mm)])
A([StepFlow(["Record or type a conversation",
             "AI extracts the work",
             "A human confirms it",
             "Plan version created",
             "Tasks staffed by skill",
             "Client emails drafted"])])

# ── PART 2 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("2", "The six roles",
         "A person's role decides their navigation and their permissions. The\n"
         "server enforces it — the screens simply do not offer what a role\n"
         "cannot do."))

A(p("Assign roles deliberately: the bottom bar of the app is <b>assembled from "
    "the role at sign-in</b>, so the same build looks different for each person. "
    "Below is exactly what each role gets."))
A([Spacer(1, 2 * mm)])

A(role_grid([
    RoleCard("Sales agent", "The field representative",
             "Home · Leads · Jarvis · Tasks · <b>Inbox</b>",
             "The only role with the Inbox tab: logs client replies that "
             "arrived by phone or WhatsApp, works the triage queue, and reads "
             "the delivery trace of anything sent."),
    RoleCard("Sales lead", "Owns the pipeline and signs off",
             "Home · <b>Pipeline</b> · Jarvis · <b>Approvals</b> · Team",
             "Pipeline holds two sub-tabs — Leads and Projects — so this role "
             "does everything from creating a client to reading any project. "
             "Books demos; approves outgoing messages."),
    RoleCard("Operations agent", "Delivers the work",
             "Home · <b>Tasks</b> · Jarvis · Projects · More",
             "Lives in Tasks: progress, decline, block, re-date, split, record "
             "a vendor promise, and finish work — which is what triggers the "
             "client update."),
    RoleCard("Operations lead", "Owns delivery",
             "Home · <b>Delivery</b> · Jarvis · Incidents · Team",
             "Confirms the assignment batch before anyone is notified, watches "
             "project health, and — with the administrator — is the only side "
             "that can reschedule or close a demo."),
    RoleCard("Organisation admin", "Sets the product up",
             "Home · <b>Approvals</b> · Jarvis · Admin · Insights",
             "Sees every approval in the organisation. Owns everything in "
             "Part 3: staff, skills, what you sell, pricing, templates, "
             "approval rules and the behaviour dials."),
    RoleCard("Platform operator", "Runs the platform, not your business",
             "Separate console",
             "Creates organisations and reads aggregate counts only. This role "
             "is blocked from reading any client's sales data — by the server, "
             "not by a screen."),
]))

# Six role cards fill a page on their own, so the summary table is kept whole
# rather than split two rows short of the foot.
A([CondPageBreak(95 * mm), Spacer(1, 1 * mm)])
A(p("Where things live, per role", H3_S))
A([grid_table(
    ["", "Sales agent", "Sales lead", "Ops agent", "Ops lead"],
    [["Clients", "Leads tab", "Pipeline → Leads", "—", "—"],
     ["Projects", "Client → Projects", "Pipeline → Projects", "Projects tab",
      "Delivery tab"],
     ["My work", "Tasks tab", "Home cards", "Tasks tab", "Home cards"],
     ["Approvals", "—", "Approvals tab", "—", "Home cards"],
     ["Client replies", "<b>Inbox tab</b>", "Home card, when one is waiting",
      "—", "Home card"],
     ["Demos & follow-ups", "Home cards", "Home cards", "Home cards",
      "Home cards"]],
    [26 * mm] + [(CONTENT_W - 26 * mm) / 4] * 4)])
A([Spacer(1, 1.6 * mm)])
A(p("Pipeline opens on the Projects sub-tab — tap <b>Leads</b> first when you "
    "want a client list.", SMALL_S))

A([Callout("guard",
           "Two refusals you should expect, because they are correct. A "
           "<b>sales lead can book a demo but cannot reschedule one</b> — "
           "moving a booked visit belongs to operations. And a person can only "
           "act on <b>their own</b> tasks: blocking or re-dating someone "
           "else's is refused, though anyone may report that work is finished, "
           "because covering for a colleague is legitimate teamwork.")])

# ── PART 3 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("3", "The go-live checklist",
         "Work down this list before your first real client. The right-hand\n"
         "column is what actually happens if an item is skipped — these are\n"
         "the product's own refusal messages, not warnings invented here."))

A(p("<b>Essential — the product cannot work without these</b>", H3_S))
A([checklist([
    ("Organisation and its first administrator",
     "Creates the tenant every other record belongs to, and the one account "
     "that can configure it. Done once by the platform operator.",
     "There is nothing to sign in to."),
    ("Staff accounts, with the right role",
     "Email is the identity and decides the organisation; the role decides the "
     "navigation and the permissions. Set each person's department too — it "
     "decides who receives their escalations.",
     "People either cannot sign in, or see the wrong app."),
    ("A skill on every person's record",
     "This is the single highest-value entry in this list. Tasks are matched to "
     "people by skill, weighed against workload and leave. Give everyone the "
     "neutral skill <b>general</b> plus their real specialisms, at basic, good "
     "or expert.",
     "Every task falls to the phase lead flagged “no skill match”, at low "
     "confidence, and is routed to a human instead of being assigned."),
    ("What you sell — one entry per offering",
     "Named and described. The description is what the AI reads when it decides "
     "which of your offerings a conversation was about.",
     "Conversations cannot be matched to an offering, and no proposal can be "
     "built."),
    ("A rate card for each offering",
     "Every line: code, label, unit (“per rack”, “per seat”, “per site”), unit "
     "price, and a default quantity where one is sensible. Rate cards are "
     "versioned — editing prices creates a new version and never alters a "
     "proposal already sent.",
     "“No pricing table for this offering. Ask your administrator to add one.” "
     "No proposal can be created."),
    ("A proposal template for each offering",
     "Your document, with placeholders the system fills in — client name, "
     "contact, the rate table, the total, and a one-line summary of the "
     "engagement.",
     "“No proposal template for this offering. Ask your administrator to add "
     "one.”"),
    ("Message templates: introduction and follow-up",
     "One of each, for email and for WhatsApp. These are the words a new "
     "contact first reads, so they should sound like your organisation.",
     "The introduction that a scanned business card is supposed to draft "
     "cannot be produced at all."),
])])

A([Spacer(1, 4 * mm)])
A(p("<b>Strongly recommended — the product works, but less well</b>", H3_S))
A([checklist([
    ("Approval rules",
     "Who signs off what, as data: a condition (for example a discount above "
     "10%, or an amount above a threshold), a rank, an approver role, an "
     "optional second approver and an optional recommender. Changing who "
     "approves what is a settings edit, never a software change.",
     "Everything falls to one default approver, and nothing is escalated by "
     "value or risk."),
    ("Standard task waves for each offering and phase",
     "Your repeatable checklist — what always happens in preparation, in "
     "delivery, at payment, at closure — with day offsets from the start date.",
     "Each phase is derived from scratch by the AI instead of following your "
     "known-good routine."),
    ("The behaviour dials",
     "Working days and hours, quiet hours, the three nudge intervals, how many "
     "messages one client contact may receive per week, the payment-reminder "
     "schedule, when the weekly report goes out, and whether task assignments "
     "apply automatically or wait for a lead.",
     "Sensible defaults apply, but the system will chase on days you do not "
     "work and at hours you do not keep."),
    ("Email sending",
     "Either an organisation-wide sending account, or — better — each "
     "salesperson's own, so the client always sees a real person's address.",
     "Messages are drafted, approved and written to an outbox file instead of "
     "being delivered."),
    ("Retention windows",
     "How long recordings and transcripts are kept before they are "
     "automatically deleted and scrubbed.",
     "Defaults apply: recordings 90 days, transcripts one year."),
])])

A([Spacer(1, 4 * mm)])
A(p("<b>Optional — turn on when you need them</b>", H3_S))
A([checklist([
    ("Demo teams",
     "Named squads with a team lead, a media representative and a sales "
     "representative, so a booking can be made against a team and clashes "
     "detected.",
     "Demos are still bookable; they simply carry no team."),
    ("Calendar",
     "Connect a calendar and confirmed demos are mirrored into it. The "
     "system's own calendar remains the source of truth either way.",
     "Invitations still reach clients by email; nothing appears in your own "
     "calendar."),
    ("Vendors",
     "Outside suppliers your plans depend on, so a vendor promise can be "
     "recorded against a task and chased.",
     "Vendor promises can still be typed as free text, but are not tracked as "
     "vendors."),
    ("Suppliers of inbound mail",
     "Connect a mailbox and client replies are read and classified "
     "automatically.",
     "Replies are captured by hand with <b>Log a reply</b>, which works fully "
     "and takes seconds."),
])])

A([Spacer(1, 3 * mm)])
A([Callout("warn",
           "<b>Two things to verify on the day, before anyone demonstrates "
           "anything.</b> First, that sending is switched on if you intend "
           "real email to leave — otherwise approved messages are written to a "
           "file and everyone believes they were sent. Second, that at least "
           "one person holds each skill your rate card implies; the quickest "
           "check is to open any project after the first meeting and confirm "
           "every task shows a named person rather than the phase lead.")])

# ── PART 4 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("4", "The feature guide",
         "Screen by screen, in the order the work happens. Everything below is\n"
         "reachable by tapping — nothing here requires a keyboard shortcut, a\n"
         "browser or an administrator."))

A(h2("4.1 Signing in, and pointing the app at your server"))
A([feature_table([
    ("Sign in", "Email and password. Your role decides the tabs you get."),
    ("Change your password", "Forced on first sign-in; available afterwards from "
     "your profile."),
    ("Point the app at a different server",
     "On the sign-in screen, tap the <b>server:</b> chip — or long-press the "
     "logo — paste the address and <b>Apply</b>. It is stored on the device and "
     "survives restarts."),
    ("Work with no signal",
     "A banner appears. Approvals you have already loaded stay readable, and "
     "decisions you make are queued and applied — exactly once — when the "
     "connection returns."),
])])

A(h2("4.2 Home — what needs you today"))
A(p("Home is a single answer to “what should I do now?”. It opens with a "
    "briefing written for you, then a stack of cards for anything waiting."))
A([feature_table([
    ("Read your briefing",
     "Top of Home: work due today, genuinely late work, approvals waiting, "
     "replies that arrived overnight, follow-ups due and demos ahead."),
    ("See what is waiting on you",
     "Cards below the briefing — approvals, a meeting needing review, an "
     "assignment batch to confirm, inbound messages needing a human."),
    ("Refresh", "Pull down anywhere on Home."),
    ("Open your notifications", "Tap the <b>bell</b>. Every notification opens "
     "the exact record it is about."),
    ("Jump to a demo or a follow-up", "The <b>My day</b> cards — Demos and "
     "Follow-ups — open their full screens."),
])])

A(h2("4.3 Clients"))
A([feature_table([
    ("Create a client", "Leads (or Pipeline → Leads) → <b>+</b> → name → Save."),
    ("Open the six tabs",
     "Overview · Contacts · Projects · Notebook · History · Meetings. "
     "<b>The action buttons change with the tab.</b>"),
    ("Add a contact by hand", "Contacts → <b>Add contact</b>. Mark the main "
     "person <b>Primary</b>."),
    ("Scan a business card",
     "Contacts → <b>Scan card</b> → Capture. The reading appears with a "
     "confidence score — <b>correct anything wrong, then Save</b>. Only what "
     "you save counts, and the introduction email is drafted from the saved "
     "version."),
    ("Record something worth remembering",
     "Notebook → <b>Add note</b>. Notes feed the AI's memory of this client."),
    ("Move the client through its stages",
     "Overview → <b>Change state</b>. When the AI suggests a move it appears as "
     "a banner with the reason, and <b>Keep as is</b> beside it."),
    ("See what has happened", "History for the state trail, Meetings for every "
     "conversation."),
])])

A(h2("4.4 Meetings — the way work enters the system"))
A([feature_table([
    ("Record a conversation",
     "Client → Meetings → <b>Record meeting</b>. A consent sheet comes first: "
     "record how the client agreed. It will not record until you do."),
    ("Watch it being processed",
     "The meeting screen shows the stages as they happen — uploaded, "
     "transcribing, extracting, ready for review."),
    ("Retry a failed recording",
     "<b>Retry</b> on the meeting screen. It tells you what went wrong, and "
     "reuses the transcript rather than transcribing again."),
    ("Type or dictate notes instead",
     "Client → Meetings → <b>Type notes</b>. Typed notes go through exactly the "
     "same brain as a recording — useful when recording was declined."),
    ("Confirm what the AI heard",
     "Home card, or the meeting screen. <b>Edit</b> a title, <b>drop</b> "
     "anything wrong, <b>add</b> what it missed, then <b>Confirm</b>. If two "
     "items look alike it says so, so you can drop the repeat. "
     "<b>Nothing becomes work until you confirm.</b>"),
])])

A(h2("4.5 Projects"))
A([feature_table([
    ("See everything about a project",
     "Eight tabs: <b>Overview</b> (objective, status, health <i>and the reason</i>) · "
     "<b>Plan</b> · <b>Tasks</b> · <b>Timeline</b> · <b>People</b> (client side) · "
     "<b>Team</b> (your side) · <b>Conflicts</b> · <b>Reports</b>."),
    ("Understand why someone got a task",
     "Tasks → open one → <b>Assigned because</b> — the recorded reason, "
     "including any caveat such as a tie between equally suited people."),
    ("See the promises in play",
     "Overview → <b>We owe them</b> and <b>They owe us</b>. Every promise made "
     "aloud is tracked and chased."),
    ("Add a client-side person",
     "People → <b>Add stakeholder</b>, with their role in <i>their</i> "
     "organisation and whether they receive progress updates."),
    ("Change who is on the team",
     "Team → <b>Add member</b>. Removing someone asks first, then redistributes "
     "their open work."),
    ("Get a briefing on a project you have not touched",
     "<b>Catch me up</b> at the top of the project."),
    ("Produce the weekly report",
     "Reports → <b>Generate this week's client report</b> — it is queued for "
     "approval, never sent automatically. The internal digest is not gated."),
    ("Move the project on", "<b>Change status</b>, or <b>Shift phase</b> to "
     "generate the next wave of work."),
    ("Split one deal into branches",
     "<b>Split into branches</b> — commercials stay on the parent, delivery "
     "moves to a child project per site."),
    ("Resolve a contradiction",
     "Conflicts → open → <b>Resolve</b> with a note. The plan version that was "
     "held is then released for approval."),
])])

A(h2("4.6 Jarvis — the assistant"))
A(p("Jarvis is the fastest route to almost everything, and the only route to a "
    "few things. Type or speak; short and loose is fine — working out what you "
    "meant is the assistant's job, and when it genuinely cannot it asks one "
    "question rather than guessing."))
A([feature_table([
    ("Ask about a client",
     "“tell me everything about <i>client</i>”, “what did they say about the "
     "handover pack”"),
    ("Ask about a project",
     "“give me a brief about the <i>x</i> project” — objective, health and why, "
     "plan version, task counts, the client's people, open promises, what is "
     "due next"),
    ("Ask what is stuck",
     "“what's blocking <i>x</i>” — includes decisions waiting and "
     "contradictions, not just late work"),
    ("Ask about your own work",
     "“what is late”, “most important task this week”, “how many approvals are "
     "waiting on me”"),
    ("Ask why the AI did something",
     "“why did you pick <i>name</i>” — quotes the recorded reason verbatim, "
     "caveats included"),
    ("Create things",
     "“add a note to <i>client</i>: …”, “create a task to … by Friday”, "
     "“schedule a follow-up with <i>name</i> next Tuesday”"),
    ("Build and send a proposal",
     "“create the <i>x</i> proposal for <i>client</i>”, then “email the "
     "proposal to <i>name</i>”. <b>This is the only way to create a "
     "proposal.</b>"),
    ("Use your voice",
     "Tap the <b>mic</b>. Toggle <b>speak replies</b> and it reads answers "
     "aloud."),
    ("Start again",
     "<b>New conversation</b> — the assistant genuinely forgets the previous "
     "thread rather than hiding it."),
])])
A([Callout("tip",
           "Relative dates work: “last Tuesday”, “next Monday”, “by month "
           "end”. The assistant is told today's date, so you never have to "
           "type one.")])

A(h2("4.7 Proposals"))
A([feature_table([
    ("Create one", "Ask Jarvis (see 4.6). It is built from your template and "
     "the current rate card."),
    ("Read it",
     "Five sections: Commercials · Total · Narrative · Revision trail · "
     "actions. The header names the template and rate-card versions it locked."),
    ("Change the wording",
     "<b>Change it (by instruction)</b> — for example “make the tone warmer and "
     "lead with the handover pack”. The narrative changes; "
     "<b>the commercials and the total cannot</b>."),
    ("Change the numbers",
     "Adjust quantities through the assistant, or change the rate card itself. "
     "A price the AI was not given cannot appear."),
    ("Read the PDF", "<b>View PDF</b> — it renders in the app."),
    ("Submit for internal review",
     "<b>Submit for internal review</b>. Your approval rules decide who signs "
     "off; below every threshold it clears at once."),
    ("Send it",
     "Ask the assistant to email it, then <b>Approve &amp; send</b>. It goes "
     "from the salesperson's own address with the document attached."),
    ("Replace it with a file you edited outside",
     "<b>Upload edited file</b>. The locked total must still appear in the "
     "document or the upload is refused, and the proposal returns to draft for "
     "review."),
])])

A(h2("4.8 Demos and site visits"))
A([feature_table([
    ("Book one",
     "Client → Overview → <b>Book demo</b> → date, time, notes. A clash is "
     "warned about, never hidden. The invitation is drafted and waits in "
     "Approvals."),
    ("See the month",
     "Home → <b>Demos</b> card. Dots mark days with work due; "
     "<b>long-press</b> a day to see that day's tasks."),
    ("Move one",
     "Operations, or an administrator: open the demo → <b>Reschedule</b>. An "
     "updated invitation is drafted for approval. <i>A sales lead who booked it "
     "cannot move it.</i>"),
    ("Close one out",
     "Operations, or an administrator: <b>Update status</b> → Completed, or "
     "Cancelled, which retracts the invitation."),
])])

A(h2("4.9 Follow-ups"))
A([feature_table([
    ("See what is due",
     "Home → <b>Follow-ups</b> card. Four buckets: due today, overdue, this "
     "week, all pending."),
    ("Create one", "Ask Jarvis — “schedule a follow-up with <i>name</i> next "
     "Tuesday, note: …”."),
    ("Let the AI write the chase",
     "Open one → <b>Draft message (AI)</b> with a short prompt. It goes to "
     "Approvals, not out the door."),
    ("Close one",
     "<b>Mark done</b> with a note, leaving <b>Schedule the next one</b> "
     "ticked — so a relationship never quietly goes cold."),
])])

A(h2("4.10 Inbox — what clients send back"))
A(p("The Inbox is permanently available to the sales agent. Everyone else "
    "reaches it from the Home card that appears when something needs a human."))
A([feature_table([
    ("Record a reply that arrived elsewhere",
     "<b>Log a reply</b> → choose the person it came from → paste what they "
     "said → <b>Log it</b>. A phone call, a WhatsApp or a corridor "
     "conversation is then treated exactly like an email, and the system tells "
     "you how it understood the message."),
    ("See exactly what was sent",
     "Messages → open one → <b>Delivery trace</b> — the real message and every "
     "delivery event in order. Not what we think we sent."),
    ("Handle what the AI could not place",
     "<b>Needs a human</b> tab. Read the whole message, attach it to a client "
     "or a project, correct what it is asking for, draft a reply, or mark it "
     "handled."),
])])

A(h2("4.11 Tasks — doing the work"))
A([feature_table([
    ("See your work in order",
     "Tasks tab: <b>Blocked · Overdue · Today · This week · Later</b>."),
    ("Know why it is yours",
     "Open a task → <b>Assigned because</b>, and where it applies "
     "<b>Fulfils a client commitment</b>."),
    ("Report progress", "<b>Progress</b> with a note — it lands on the project "
     "timeline."),
    ("Say it is not for you",
     "<b>Decline</b> with a reason. It is re-routed to someone better suited, "
     "and the decline stays on record."),
    ("Say you are stuck",
     "<b>Block</b> and name the blocker. Nudges to you stop, and the blocker "
     "gets chased instead."),
    ("Ask for a later date",
     "<b>New date</b> with a reason. If it would break a dependent task or a "
     "client promise, it is sent to your phase lead to decide rather than "
     "silently accepted."),
    ("Break it in two", "<b>Split</b> — two real tasks, the second waiting on "
     "the first."),
    ("Record an outside promise",
     "<b>Vendor promise</b> with the date, and <b>Vendor slipped</b> if it "
     "moves. Your coordinator is reminded before the date, not after."),
    ("Finish it",
     "<b>Done</b> with a result note. If the task was client-visible, the "
     "update to your client is drafted automatically — and still waits for "
     "approval."),
])])

A(h2("4.12 Approvals — the human gate"))
A([feature_table([
    ("Read what you are approving",
     "Approvals → open a card. The <b>full</b> message, never a truncated "
     "preview, plus the AI's own recommendation where the rule asks for one."),
    ("Approve", "<b>Approve</b>. It applies once, even if you tap twice."),
    ("Send it back",
     "<b>Reject</b> with a note. <b>The note becomes the instruction</b> — a "
     "redraft comes back having applied it."),
    ("Handle an unfinished draft",
     "If blanks remain you are told, and shown the lines they sit on. Choose "
     "<b>Send as it is</b> or <b>Not yet</b> — there is no silent send."),
    ("Approve while offline",
     "It queues, and applies exactly once when you reconnect."),
])])

# ── PART 5 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("5", "What the system refuses to do",
         "These are not limitations to work around. Each one exists because the\n"
         "alternative caused a real problem, and each is enforced in code\n"
         "rather than asked of the AI in a prompt."))

A([grid_table(
    ["It will not…", "What happens instead"],
    [["Send anything to a client without a human tap",
      "Every outgoing message is created in a pending state and waits for "
      "Approve."],
     ["Send a draft with blanks left in it",
      "The approval is refused, the offending lines are quoted back, and you "
      "may approve again deliberately."],
     ["Invent a price, a discount or a total",
      "Numbers come only from your rate card or a recorded human approval. A "
      "rewrite that slips a new figure into the words is rejected outright."],
     ["Process a recording without consent captured first",
      "The upload is refused. Consent must already have been recorded, and the "
      "system links that record rather than writing its own."],
     ["Pick a side when two people contradict each other",
      "It writes down both positions, names who said what, and holds the "
      "re-plan until a person resolves it."],
     ["Guess when it is unsure",
      "Below a confidence threshold you control, it routes the decision to a "
      "named person with the reason."],
     ["Answer a client question it has no data for",
      "It creates a task for a named person instead of composing something "
      "plausible."],
     ["Apply an out-of-date plan",
      "Approving a stale version is refused, because it would discard "
      "everything a newer version added."],
     ["Let one person act on another's task",
      "Blocking, re-dating and splitting are owner-only; leads act across the "
      "team."],
     ["Write to an address a person has not verified",
      "A contact flagged for review is never messaged."],
     ["Contact someone who asked not to be",
      "An absolute stop, honoured even when the draft has no project context."],
     ["Chase outside your working hours",
      "Reminders respect your working days, your hours and anyone's leave, and "
      "are cancelled the moment the underlying work completes."],
     ["Overwhelm one client contact",
      "A weekly cap per person, which you set, defers rather than floods."],
     ["Stop silently",
      "Every refusal writes a record with the reason and the remedy. Refusing "
      "is allowed; refusing invisibly is not."]],
    [CONTENT_W * 0.42, CONTENT_W * 0.58])])

A([Spacer(1, 4 * mm)])
A([Callout("info",
           "<b>Every decision is explainable.</b> Four independent trails are "
           "kept: who did what, what happened in the business, what the AI "
           "decided and why it was confident, and what every AI call cost. Ask "
           "the assistant “why did you…” about any record, or tap the "
           "<b>Why?</b> chip wherever it appears.")])

# ── PART 6 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("6", "The rhythm",
         "What the product does on its own, and what it will ask of you."))

A(h3("Every day, without being asked"))
A(bullets([
    "A personal briefing is prepared for each person before the working day.",
    "Overdue work is nudged on a three-step ladder — a gentle reminder, then a "
    "firmer one, then the lead, who is offered a specific alternative person.",
    "Promises are checked in both directions: yours are warned about the day "
    "before they break, and the client's are chased politely after.",
    "Silent conversations are followed up, switching channel on the second "
    "attempt, and after your limit a person is asked to make a call instead.",
    "Unpaid invoices are chased on the schedule you set, copying whoever you "
    "nominated.",
    "Anyone carrying more than their capacity is flagged to their lead with "
    "concrete moves to make.",
    "Dormant clients wake up on the date you promised to return, with the "
    "story replayed.",
]))

A(h3("Every week"))
A(bullets([
    "A client-facing progress report is drafted for each active project on the "
    "day you choose — and waits for approval.",
    "An internal digest is produced for your own team, which needs no approval.",
]))

A(h3("What it will ask you for"))
A(bullets([
    "Confirm what a meeting agreed, before it becomes work.",
    "Confirm the assignment batch, if you have chosen lead confirmation.",
    "Approve anything going to a client.",
    "Resolve a contradiction, when two sources disagree.",
    "Decide, when confidence is low or a date change would break a promise.",
]))

# ── PART 7 ───────────────────────────────────────────────────────────────────
A([PageBreak()])
A(opener("7", "When something looks wrong",
         "The most common causes, in the order they are worth checking."))

A([grid_table(
    ["What you see", "What it usually means"],
    [["“Can't reach the server”, or network trouble",
      "The app is pointed at an address that is no longer live. Re-check the "
      "<b>server:</b> chip on the sign-in screen before suspecting anything "
      "else."],
     ["“Your role can't do this”",
      "Working as designed. The message names the role; ask someone whose job "
      "it is, or have an administrator change the role."],
     ["Every task is assigned to the same lead, marked “no skill match”",
      "No skills are recorded. This is the first item in Part 3 and the "
      "single most common setup omission."],
     ["A proposal cannot be created",
      "The offering has no rate card or no proposal template. Both are in "
      "Part 3."],
     ["A business card scan drafts nothing",
      "No introduction template exists for that channel, or the contact has no "
      "address of that kind."],
     ["Approved messages never arrive",
      "Sending is not switched on, so messages are being written to a file. "
      "Check with your administrator."],
     ["A recording will not start",
      "Consent has not been recorded for that client yet."],
     ["A recording stalls",
      "<b>Retry</b> on the meeting screen. It states the reason and reuses the "
      "transcript."],
     ["The follow-up list is empty",
      "That is usually correct: a concrete conversation produces a project, "
      "not follow-ups. Create one through the assistant."],
     ["A plan change has not taken effect",
      "It is waiting for approval. Held changes apply on activation, not when "
      "they are proposed."],
     ["A notification does not open anything",
      "Tell your administrator which kind it was — every notification is "
      "expected to open the record it concerns."]],
    [CONTENT_W * 0.38, CONTENT_W * 0.62])])

A([Spacer(1, 6 * mm)])
A([Rule()])
A([Spacer(1, 3 * mm)])
A(p(f"<b>{PRODUCT}</b> · {TAGLINE}", S(fontName=F["semi"], fontSize=10,
                                       textColor=NAVY)))
A(p("Set the product up once, in Part 3. After that the working day is: read "
    "your briefing, record your conversations, and approve what the machine "
    "prepared for you.", S(fontSize=9.4, leading=13.6, textColor=MUTED)))


if __name__ == "__main__":
    build()
