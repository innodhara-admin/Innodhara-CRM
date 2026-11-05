"""Render BACKEND_README.md to BACKEND_README.pdf.

Keeps the identity of the existing PDF (ReportLab, A4, the same title/author/
subject metadata and the running header), so regenerating after a documentation
change produces a comparable document rather than a different-looking one.

Handles the Markdown subset the README actually uses: h1-h4, paragraphs,
bullet and numbered lists, fenced code blocks (including the ASCII architecture
diagram), pipe tables, horizontal rules, block quotes, and inline **bold**,
*italic* and `code`.

    python scripts/render_readme_pdf.py
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "BACKEND_README.md"
TARGET = ROOT / "BACKEND_README.pdf"

# The architecture diagram in §2 is drawn with box-drawing characters
# (U+2500 range). ReportLab's built-in Courier has no glyphs for them and
# silently renders a black square for each, which turns the diagram into a wall
# of blocks. So a Unicode-capable monospace font is registered when one can be
# found, and the diagram is transliterated to ASCII only as a last resort —
# either way it stays readable.
MONO_CANDIDATES = [
    ("DejaVuSansMono", Path(__file__).resolve().parent.parent
     / "assets" / "DejaVuSansMono.ttf"),
    ("Consolas", Path("C:/Windows/Fonts/consola.ttf")),
    ("DejaVuSansMono", Path("C:/Windows/Fonts/DejaVuSansMono.ttf")),
    ("LucidaConsole", Path("C:/Windows/Fonts/lucon.ttf")),
    ("DejaVuSansMono", Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")),
]

_BOX_TO_ASCII = str.maketrans({
    "─": "-", "━": "-", "│": "|", "┃": "|",
    "┌": "+", "┐": "+", "└": "+", "┘": "+",
    "├": "+", "┤": "+", "┬": "+", "┴": "+", "┼": "+",
    "╔": "+", "╗": "+", "╚": "+", "╝": "+", "═": "=", "║": "|",
    "▼": "v", "▲": "^", "◄": "<", "►": ">", "·": "-",
})


def register_mono() -> tuple[str, bool]:
    """(font name, whether it can render box-drawing). Falls back to Courier."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as RLTTFont

    for name, path in MONO_CANDIDATES:
        if path.exists():
            try:
                pdfmetrics.registerFont(RLTTFont(name, str(path)))
                return name, True
            except Exception:  # noqa: BLE001 — try the next candidate
                continue
    # matplotlib ships DejaVu; use it if it happens to be installed.
    try:
        import matplotlib

        p = (Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
             / "DejaVuSansMono.ttf")
        if p.exists():
            pdfmetrics.registerFont(RLTTFont("DejaVuSansMono", str(p)))
            return "DejaVuSansMono", True
    except Exception:  # noqa: BLE001
        pass
    return "Courier", False

TITLE = "YuviPep AI Sales Platform — Backend"
AUTHOR = "Engineering"
SUBJECT = "Backend architecture reference"
RUNNING_HEAD = "Backend architecture reference — internal"

INK = colors.HexColor("#12213d")
ACCENT = colors.HexColor("#1a3d7c")
RULE = colors.HexColor("#c3cdde")
SHADE = colors.HexColor("#f2f5fa")
CODE_BG = colors.HexColor("#f6f7f9")
MUTED = colors.HexColor("#5c6879")


# ── inline markdown → ReportLab markup ───────────────────────────────────────
def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    # `code` first: its content must not then be treated as emphasis.
    holds: list[str] = []

    def hold(match: re.Match[str]) -> str:
        holds.append(match.group(1))
        return f"\x00{len(holds) - 1}\x00"

    out = re.sub(r"`([^`]+)`", hold, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", out)          # links → text
    for i, code in enumerate(holds):
        out = out.replace(
            f"\x00{i}\x00",
            f'<font face="Courier" size="8.5" color="#1a3d7c">{code}</font>',
        )
    return out


def build_styles(mono: str = "Courier"):
    ss = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.4,
        leading=13.6, spaceAfter=6, textColor=INK, alignment=TA_LEFT,
    )
    return {
        "body": body,
        "h1": ParagraphStyle("H1", parent=body, fontName="Helvetica-Bold",
                             fontSize=19, leading=23, spaceBefore=2,
                             spaceAfter=4, textColor=ACCENT),
        "sub": ParagraphStyle("Sub", parent=body, fontSize=10.5, leading=14,
                              textColor=MUTED, spaceAfter=10),
        "h2": ParagraphStyle("H2", parent=body, fontName="Helvetica-Bold",
                             fontSize=14, leading=18, spaceBefore=16,
                             spaceAfter=7, textColor=ACCENT),
        "h3": ParagraphStyle("H3", parent=body, fontName="Helvetica-Bold",
                             fontSize=11, leading=15, spaceBefore=11,
                             spaceAfter=5, textColor=INK),
        "h4": ParagraphStyle("H4", parent=body, fontName="Helvetica-BoldOblique",
                             fontSize=9.8, leading=13, spaceBefore=9,
                             spaceAfter=4, textColor=INK),
        "quote": ParagraphStyle("Quote", parent=body, leftIndent=9,
                                borderPadding=0, textColor=MUTED,
                                fontName="Helvetica-Oblique"),
        "li": ParagraphStyle("Li", parent=body, spaceAfter=2.5, leading=13),
        "code": ParagraphStyle("Code", parent=body, fontName=mono,
                               fontSize=7.4, leading=9.1, textColor=INK,
                               spaceAfter=0, spaceBefore=0),
        "th": ParagraphStyle("Th", parent=body, fontName="Helvetica-Bold",
                             fontSize=8.4, leading=11, textColor=colors.white,
                             spaceAfter=0),
        "td": ParagraphStyle("Td", parent=body, fontSize=8.4, leading=11,
                             spaceAfter=0),
    }


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_divider(cells: list[str]) -> bool:
    return bool(cells) and all(set(c) <= {"-", ":", " "} and c for c in cells)


def render(md: str, st, unicode_mono: bool = True) -> list:
    flow: list = []
    lines = md.splitlines()
    i = 0
    first_heading_seen = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # fenced code
        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            text = "\n".join(buf).rstrip()
            if text:
                if not unicode_mono:
                    text = text.translate(_BOX_TO_ASCII)
                block = Preformatted(text, st["code"])
                tbl = Table([[block]], colWidths=[168 * mm])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
                    ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                flow += [Spacer(1, 3), tbl, Spacer(1, 8)]
            continue

        # table
        if stripped.startswith("|") and i + 1 < len(lines) \
                and is_divider(split_row(lines[i + 1])):
            header = split_row(stripped)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = split_row(lines[i])
                if not is_divider(cells):
                    rows.append(cells)
                i += 1
            width = max([len(header)] + [len(r) for r in rows])
            header += [""] * (width - len(header))
            data = [[Paragraph(inline(c), st["th"]) for c in header]]
            for r in rows:
                r = r + [""] * (width - len(r))
                data.append([Paragraph(inline(c), st["td"]) for c in r])
            # Narrow first column for 4-col route tables; else even split.
            total = 168 * mm
            if width == 4 and header[0].lower() in ("method", ""):
                widths = [total * f for f in (0.11, 0.44, 0.24, 0.21)]
            elif width == 2:
                widths = [total * 0.34, total * 0.66]
            elif width == 3:
                widths = [total * 0.26, total * 0.37, total * 0.37]
            else:
                widths = [total / width] * width
            tbl = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SHADE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]))
            flow += [Spacer(1, 3), tbl, Spacer(1, 9)]
            continue

        # horizontal rule
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flow.append(Spacer(1, 4))
            flow.append(HRFlowable(width="100%", thickness=0.5, color=RULE,
                                   spaceBefore=2, spaceAfter=8))
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level, text = len(m.group(1)), m.group(2)
            if level == 1:
                flow.append(Paragraph(inline(text), st["h1"]))
                first_heading_seen = True
            elif level == 2:
                if first_heading_seen:
                    flow.append(CondPageBreak(58 * mm))
                flow.append(Paragraph(inline(text), st["h2"]))
            elif level == 3:
                flow.append(CondPageBreak(34 * mm))
                flow.append(Paragraph(inline(text), st["h3"]))
            else:
                flow.append(CondPageBreak(26 * mm))
                flow.append(Paragraph(inline(text), st["h4"]))
            i += 1
            continue

        # block quote
        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip().lstrip(">").strip())
                i += 1
            flow.append(Paragraph(inline(" ".join(buf)), st["quote"]))
            flow.append(Spacer(1, 5))
            continue

        # lists (bullet or numbered), including simple nesting
        if re.match(r"^\s*([-*+]|\d+\.)\s+", raw):
            items: list[ListItem] = []
            numbered = bool(re.match(r"^\s*\d+\.\s", raw))
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]):
                indent = len(lines[i]) - len(lines[i].lstrip())
                text = re.sub(r"^\s*([-*+]|\d+\.)\s+", "", lines[i]).rstrip()
                i += 1
                # continuation lines of the same item
                while (i < len(lines) and lines[i].strip()
                       and not re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i])
                       and not lines[i].strip().startswith(("#", "|", "```", ">"))
                       and (len(lines[i]) - len(lines[i].lstrip())) >= 2):
                    text += " " + lines[i].strip()
                    i += 1
                style = st["li"]
                if indent >= 2:
                    style = ParagraphStyle(f"Li{indent}", parent=st["li"],
                                           leftIndent=10)
                items.append(ListItem(Paragraph(inline(text), style),
                                      leftIndent=12))
            flow.append(ListFlowable(
                items, bulletType="1" if numbered else "bullet",
                start="1" if numbered else None,
                bulletFontSize=7.5, bulletOffsetY=-0.6,
                leftIndent=13, bulletDedent=9,
            ))
            flow.append(Spacer(1, 6))
            continue

        # paragraph — join until a blank line or a block starter
        buf = [stripped]
        i += 1
        while (i < len(lines) and lines[i].strip()
               and not re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i])
               and not lines[i].strip().startswith(("#", "|", "```", ">", "---"))):
            buf.append(lines[i].strip())
            i += 1
        text = " ".join(buf)
        # the subtitle right under the H1
        style = st["sub"] if text.startswith("**Architecture and capability") \
            else st["body"]
        flow.append(Paragraph(inline(text), style))

    return flow


def decorate(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.4)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, A4[1] - 12 * mm, RUNNING_HEAD)
    canvas.drawRightString(A4[0] - 20 * mm, A4[1] - 12 * mm, str(doc.page))
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(20 * mm, A4[1] - 14.5 * mm, A4[0] - 20 * mm, A4[1] - 14.5 * mm)
    canvas.drawString(20 * mm, 11 * mm, TITLE)
    canvas.restoreState()


def main() -> None:
    md = SOURCE.read_text(encoding="utf-8")
    mono, unicode_mono = register_mono()
    st = build_styles(mono)
    doc = SimpleDocTemplate(
        str(TARGET), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=17 * mm,
        title=TITLE, author=AUTHOR, subject=SUBJECT,
    )
    doc.build(render(md, st, unicode_mono),
              onFirstPage=decorate, onLaterPages=decorate)
    note = "box-drawing preserved" if unicode_mono \
        else "no Unicode mono font found — diagram transliterated to ASCII"
    print(f"wrote {TARGET.relative_to(ROOT)} "
          f"({TARGET.stat().st_size // 1024} KB) from "
          f"{len(md.splitlines())} markdown lines; mono={mono} ({note})")


if __name__ == "__main__":
    main()
