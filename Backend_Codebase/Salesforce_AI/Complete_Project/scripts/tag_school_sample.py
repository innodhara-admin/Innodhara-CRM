"""Tag School_YuviPep 360_2 1.docx the way its author would have.

Only values that genuinely vary from school to school are tagged, and each one
is REPLACED IN PLACE with `replace_span` -- the same writer the fill uses -- so
the document keeps every image, section, table and style it had. Nothing is
inserted and nothing is deleted, which is what lets the golden test assert the
media and section counts are unchanged.

Run with no argument for a dry run. Pass --write to produce the tagged file.
"""
import io
import sys

from docx import Document

sys.path.insert(0, ".")
from app.services.docx import text as dt   # noqa: E402

SOURCE = "data/samples/School_YuviPep 360_2 1.docx"
TARGET = "data/samples/School_YuviPep 360_2 1 (tagged).docx"

#: (walk ordinal, the exact text to replace, the tag to put there, why).
#: The ordinal pins WHICH occurrence -- "School School" appears three times and
#: they are three different questions about the same literal (D1).
#: All NINE "School School" occurrences, not the three the body shows. Six of
#: them live in the footers of three sections, past where a reader scrolling
#: the body would ever look -- and a document tagged in the body only would
#: build with the placeholder still printed at the bottom of every page.
TAGS = [
    (2, "School School", "<School Name>",
     "cover, first block"),
    (4, "School School", "<School Name>",
     "cover, second block"),
    (6, "School School", "<School Name>",
     "the cover title"),
    (766, "School School", "<School Name>", "footer, section 1"),
    (767, "School School", "<School Name>", "footer, section 1"),
    (773, "School School", "<School Name>", "footer, section 2"),
    (774, "School School", "<School Name>", "footer, section 2"),
    (781, "School School", "<School Name>", "footer, section 3"),
    (782, "School School", "<School Name>", "footer, section 3"),
    (646, "Nexus", "<ask:Nexus>",
     "which deliverables tier this school is being offered"),
    (654, "1 Set", "<ask:1 Set>",
     "how many sets of study materials and workbooks"),
    (675, "Rs. 2500/- net", "<ask_calculate:Rs. 2500/- net>",
     "the negotiated annual price per student"),
    (676, "10 months", "<ask:10 months>",
     "programme duration"),
    (678, "Weekly once", "<ask:Weekly once>",
     "workshop frequency"),
    (680, "2700", "<ask:2700>",
     "number of students"),
    (684, "1 to 10", "<ask:1 to 10>",
     "which grades the programme covers"),
]


def main() -> int:
    write = "--write" in sys.argv
    with open(SOURCE, "rb") as fh:
        source_bytes = fh.read()
    doc = Document(io.BytesIO(source_bytes))
    walk = dt.walk_paragraphs(doc)
    print("source: %s (%d bytes, %d paragraphs)"
          % (SOURCE, len(source_bytes), len(walk)))
    print("-" * 96)

    failures = 0
    # Right to left within a paragraph, and by descending ordinal, for the same
    # reason the writer does: an earlier replacement must not move a later one.
    for ordinal, old, new, why in sorted(TAGS, reverse=True):
        if not 0 <= ordinal < len(walk):
            print("MISSING  %4d  no such paragraph" % ordinal)
            failures += 1
            continue
        paragraph = walk[ordinal]
        text = dt.node_text(paragraph)
        start = text.rfind(old)
        if start < 0:
            print("MISSING  %4d  %r not in %r" % (ordinal, old, text[:70]))
            failures += 1
            continue
        if write:
            dt.replace_span(paragraph, start, start + len(old), new)
        print("%s %4d  %-32s -> %-34s  (%s)"
              % ("tagged " if write else "would  ", ordinal, repr(old), new, why))

    if failures:
        print("\n%d target(s) not found; nothing written." % failures)
        return 1
    if not write:
        print("\ndry run only. Pass --write to produce:\n  %s" % TARGET)
        return 0

    buf = io.BytesIO()
    doc.save(buf)
    with open(TARGET, "wb") as fh:
        fh.write(buf.getvalue())
    print("\nwrote %s (%d bytes)" % (TARGET, len(buf.getvalue())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
