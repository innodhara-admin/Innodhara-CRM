"""Render proposal Markdown into editable DOCX and shareable PDF files.

Supports the Markdown subset our templates use: #/##/### headings, bullet
lists, tables (| cells |), bold **text**, and plain paragraphs.
"""
from __future__ import annotations

import io
import re

from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _strip_md_inline(text: str) -> str:
    return _BOLD.sub(r"\1", text).strip()


def _md_blocks(markdown: str) -> list[dict]:
    """Parse markdown into blocks: heading / table / bullet / paragraph."""
    blocks: list[dict] = []
    lines = [ln for ln in markdown.splitlines() if not ln.strip().startswith("<!--")]
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            blocks.append({"type": "heading", "level": min(level, 3),
                           "text": _strip_md_inline(stripped.lstrip("#"))})
            i += 1
        elif stripped.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= {"-", ":", " "} and c for c in cells):  # skip separator row
                    rows.append([_strip_md_inline(c) for c in cells])
                i += 1
            if rows:
                blocks.append({"type": "table", "rows": rows})
        elif stripped.startswith(("- ", "* ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(_strip_md_inline(lines[i].strip()[2:]))
                i += 1
            blocks.append({"type": "bullets", "items": items})
        else:
            para = [stripped]
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("#", "|", "- ", "* ")):
                para.append(lines[i].strip())
                i += 1
            blocks.append({"type": "paragraph", "text": " ".join(para)})
    return blocks


def render_docx(markdown: str, title: str) -> bytes:
    doc = Document()
    doc.core_properties.title = title
    for block in _md_blocks(markdown):
        if block["type"] == "heading":
            doc.add_heading(block["text"], level=block["level"])
        elif block["type"] == "table":
            rows = block["rows"]
            table = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            table.style = "Light Grid Accent 1"
            for r_idx, row in enumerate(rows):
                for c_idx, cell in enumerate(row):
                    tc = table.cell(r_idx, c_idx)
                    tc.text = cell
                    if r_idx == 0:
                        for p in tc.paragraphs:
                            for run in p.runs:
                                run.bold = True
            doc.add_paragraph()
        elif block["type"] == "bullets":
            for item in block["items"]:
                doc.add_paragraph(item, style="List Bullet")
        else:
            p = doc.add_paragraph(block["text"])
            p.paragraph_format.space_after = Pt(8)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def render_pdf(markdown: str, title: str) -> bytes:
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf, pagesize=A4, title=title,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.5, leading=15, spaceAfter=8)
    h_styles = {1: styles["Heading1"], 2: styles["Heading2"], 3: styles["Heading3"]}
    flow: list = []
    for block in _md_blocks(markdown):
        if block["type"] == "heading":
            flow.append(Paragraph(block["text"], h_styles[block["level"]]))
        elif block["type"] == "table":
            rows = block["rows"]
            width = max(len(r) for r in rows)
            data = [
                [Paragraph(c, body) for c in (r + [""] * (width - len(r)))]
                for r in rows
            ]
            table = Table(data, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3d7c")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7bd")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                         [colors.white, colors.HexColor("#f2f5fa")]),
                    ]
                )
            )
            flow += [table, Spacer(1, 8)]
        elif block["type"] == "bullets":
            for item in block["items"]:
                flow.append(Paragraph(f"•&nbsp;&nbsp;{item}", body))
        else:
            flow.append(Paragraph(block["text"], body))
    pdf.build(flow)
    return buf.getvalue()
