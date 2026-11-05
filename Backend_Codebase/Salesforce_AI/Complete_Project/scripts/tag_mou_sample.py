"""Tag the Sandur Education Centre MOU the way its author would have.

Only what genuinely varies from school to school is tagged, and every value is
REPLACED IN PLACE with `replace_span` -- the same writer the fill uses -- so
the document keeps every image, section, table and style it had. Nothing is
inserted and nothing is deleted, which is what lets the golden test assert
that the media, section and table counts are unchanged.

WHAT IS DELIBERATELY NOT TAGGED (design input section 2c): YuviPep's own
address, its bank details, its contact block in the footer, and the
Confidentiality / General Terms / Disclaimer prose. Those are the same in
every MOU and a tag there is only a way to get them wrong.

EVERY ORDINAL BELOW WAS MEASURED, NOT READ. Two of them would have been
missed by eye: `Sandur Education Centre` also appears in the Purpose clause
(ord 40) and in the Responsibilities heading (ord 58), which makes ten
occurrences rather than the eight a careful reading found. And a global
replace of "32" would have corrupted the school's own address, because
`Hosapete-583203` contains it -- which is why every entry here is pinned to
one paragraph.

Run with no argument for a dry run. Pass --write to produce the tagged file.
"""
import io
import sys

from docx import Document

sys.path.insert(0, ".")
from app.services.docx import text as dt   # noqa: E402

SOURCE = "data/samples/Sandur Education Centre_IBC Nexus and Lab2_MoU.docx"
TARGET = "data/samples/Sandur Education Centre_IBC Nexus and Lab2_MoU (tagged).docx"

ADDRESS = ("Sy. No.: 145/1A, Rayarakere, Opp: Joladarashi Gudda, "
           "Hosapete-583203, Vijayanagara-Dist, KARNATAKA")
YUVIPEP_ADDRESS = ("I, Neil Rao Towers, Plot #117, Rd Number 3, Vijayanagar, "
                   "EPIP Zone, Whitefield, Bengaluru, Karnataka 560066")
MOU_DATE = "First Day of September, Two Thousand Twenty-Six (01-09-2026)"
PER_STUDENT = "Rs. 4000/- net (including GST) per student annually."
ANNUAL_TOTAL = "Rs. 3,00,000/- Net (Including GST)."
INSTALMENT = "Rs. 1,50,000/- Net (including GST)."

#: (walk ordinal, the exact text to replace, the tag, why).
#: The ordinal pins WHICH occurrence: ten `Sandur Education Centre` are ten
#: ids and ten questions about the same literal (D1), and the fill collapses
#: them into one question by `duplicate_of` (D-D).
TAGS = [
    # ── the client, everywhere it appears, including two footers ──────────
    (3,   "Sandur Education Centre", "<School Name>", "cover, first line"),
    (4,   "Sandur Education Centre", "<School Name>", "cover, second line"),
    (34,  "Sandur Education Centre", "<School Name>", "party block, First Party"),
    (34,  "Sandur Education Centre", "<School Name>", "party block, after the signatory"),
    (40,  "Sandur Education Centre", "<School Name>", "the Purpose clause"),
    (58,  "Sandur Education Centre", "<School Name>", "Responsibilities heading"),
    (79,  "Sandur Education Centre", "<School Name>", "signature block, school column"),
    (86,  "Sandur Education Centre", "<School Name>", "signature block, under the signatory"),
    (200, "Sandur Education Centre", "<School Name>", "FOOTER of section 1"),
    (214, "Sandur Education Centre", "<School Name>", "FOOTER of section 2"),

    # ── who the school is, and who signs for it ───────────────────────────
    (34, ADDRESS, "<School Address>", "the school's registered address"),
    (34, "Smt. Y S Ghorpade", "<School Signatory>", "who represents the school"),
    (34, "President", "<School Signatory Title>", "their office"),
    (86, "Smt. Y S Ghorpade", "<School Signatory>", "signature block"),
    (86, "President", "<School Signatory Title>", "signature block"),

    # ── the tracking line on the cover, which is VISIBLE ──────────────────
    # Ordinal 1 reads "Bookmarks: status: New; author:Sunila Johnson;
    # acceptor: Mr Jakati Vikram; modified: 1.9.2026". Checked for w:vanish --
    # it is NOT hidden text. It names two YuviPep staff and a date on the
    # cover of a document that goes to a client, and all four values differ
    # from one MOU to the next. They are the cached results of AUTHOR and
    # DOCPROPERTY fields, so the metadata below is neutralised to match.
    (1, "New", "<ask:New>", "document status"),
    (1, "Sunila Johnson", "<ask:Sunila Johnson>", "who wrote this MOU"),
    (1, "Mr Jakati Vikram", "<ask:Mr Jakati Vikram>",
     "who accepts it on YuviPep's side"),
    (1, "1.9.2026", "<ask:1.9.2026>", "when it was last modified"),

    # ── what varies on YUVIPEP'S side of the contract ─────────────────────
    # Added after the owner supplied a SECOND MOU for the same product -- the
    # SSRVM renewal -- which they had already part-tagged. Diffing the two is
    # what turns "a Sandur contract" into "a generic IBC Nexus template", and
    # every tag name below is the owner's own from that document.
    (22, "1.0", "<new_version>", "document version, cover block 1"),
    (23, "1.0", "<new_version>", "document version, cover block 2"),
    (38, YUVIPEP_ADDRESS, "<org address>", "YuviPep's registered address"),
    # The owner wrote this one as `<ask me, proposed one- Mr. Jakati Vikram,
    # Director of Innovation>`. That reads as SEMANTIC to the grammar, because
    # an ask must be spelled `ask:` -- so it would be filled silently instead
    # of put to them. Written here in the form that actually asks, carrying
    # their proposed value as its default, which is what they meant.
    (38, "Mr N S Ajith Kumar", "<ask:Mr N S Ajith Kumar>",
     "who signs for YuviPep, in the party block"),
    (38, "Chief Executive Officer", "<ask:Chief Executive Officer>",
     "their office, in the party block"),
    (84, "Mr N S Ajith Kumar", "<ask:Mr N S Ajith Kumar>",
     "who signs for YuviPep, in the signature block"),
    (84, "Chief Executive Officer", "<ask:Chief Executive Officer>",
     "their office, in the signature block"),

    # ── the term, which a renewal changes completely ──────────────────────
    # SSRVM runs three years and three instalments where Sandur runs one and
    # two, so none of this is boilerplate.
    (34, "‘First Party’", "<slug>",
     "what the school is referred to as thereafter"),
    (42, "Innovation Base Course (IBC)", "<Program name>",
     "the course, in the Term clause"),
    (42, "one academic year", "<no. of years>", "how long the MOU runs"),
    (42, "AY 2026–27", "<duration>", "which academic years it covers"),

    # ── the programme opted ───────────────────────────────────────────────
    (5,   "Innovation Nexus", "<ask:Innovation Nexus>", "cover title"),
    (6,   "Innovation Nexus", "<ask:Innovation Nexus>", "cover subtitle"),
    (96,  "Innovation Nexus", "<ask:Innovation Nexus>", "Operation Terms, Programme Opted"),
    (154, "Innovation Nexus", "<ask:Innovation Nexus>", "Pricing Details, Opted Programme"),
    (196, "Innovation Nexus", "<ask:Innovation Nexus>", "HEADER of section 1"),

    # ── dates ─────────────────────────────────────────────────────────────
    (30, MOU_DATE, "<ask:%s>" % MOU_DATE, "the date the MOU is entered into"),
    # D-F: a ruled blank is NOT a tag -- TAG_RE needs angle brackets -- so an
    # author who leaves it reaches the client as underscores. Ord 85 carries
    # eleven and ord 87 carries twelve, which are different literals.
    (85, "___________", "<ask:date of signing>", "YuviPep's signing date"),
    (87, "____________", "<ask:date of signing>", "the school's signing date"),

    # ── the operational terms ─────────────────────────────────────────────
    (49,  "32", "<ask:32>", "workshops, in the responsibilities prose"),
    (99,  "32", "<ask:32>", "workshops, in the annexure"),
    (102, "3, 5, 6, 7, 8 and 9", "<ask:3, 5, 6, 7, 8 and 9>", "which grades"),
    (51,  "second week of February 2027",
     "<ask:second week of February 2027>", "completion, in the prose"),
    (111, "second week of February 2027",
     "<ask:second week of February 2027>", "completion, in the annexure"),

    # ── the deliverables table, one question per row ──────────────────────
    (118, "1", "<ask:1>", "R&D engineers allocated"),
    (121, "Yes", "<ask:Yes>", "GEN-i internship"),
    (124, "1 Set", "<ask:1 Set>", "study materials and workbooks"),
    (127, "Yes", "<ask:Yes>", "tools, components and kits"),
    (130, "Eligible", "<ask:Eligible>", "Innovation Fest"),
    (133, "Yes", "<ask:Yes>", "timely assessments"),
    (136, "Yes", "<ask:Yes>", "project assistance"),
    (139, "Yes", "<ask:Yes>", "IBC certificates"),
    (142, "Yes", "<ask:Yes>", "parent orientation support"),
    (145, "Yes", "<ask:Yes>", "exclusive account manager"),

    # ── the commercials ───────────────────────────────────────────────────
    (155, PER_STUDENT, "<ask_calculate:%s>" % PER_STUDENT,
     "the negotiated price per student"),
    (156, "75", "<ask:75>", "students, in the pricing table"),
    (157, ANNUAL_TOTAL, "<ask_calculate:%s>" % ANNUAL_TOTAL,
     "the annual total -- price x students"),
    (158, "75", "<ask:75>", "students, in the pricing note"),
    (163, "75", "<ask:75>", "students, minimum enrolment"),
    (165, "75", "<ask:75>", "students, the AY 2026-27 provision"),
    (168, "75", "<ask:75>", "students, the AY 2027-28 clause"),
    (164, "AY 2026-27", "<ask:AY 2026-27>", "the first academic year"),
    (167, "AY 2027-28", "<ask:AY 2027-28>", "the year the terms roll into"),

    # ── the payment schedule ──────────────────────────────────────────────
    (176, INSTALMENT, "<ask_calculate:%s>" % INSTALMENT, "first instalment"),
    (179, INSTALMENT, "<ask_calculate:%s>" % INSTALMENT, "second instalment"),
    (180, "first week of November 2026",
     "<ask:first week of November 2026>", "when the second instalment falls"),
]


#: docProps carries the client's name too, and NO TAG REACHES IT: `scan` and
#: `apply_tags` both walk paragraphs, and document properties are not
#: paragraphs. Word shows dc:title in its title bar, in File > Info, and in
#: Explorer's preview pane -- so a contract built for one school and sent to
#: another would carry the first school's name in its properties, invisibly to
#: anyone reading the page. Measured on the owner's file: dc:title "Sandur
#: Education Centre", dc:subject "Innovation Nexus", cp:keywords "Chief
#: Executive Officer", and the same name again in app.xml's TitlesOfParts.
#:
#: Neutralised here so the TEMPLATE names nobody. Writing the tag text rather
#: than blanking it makes an unfilled property look like the bug it is,
#: instead of silently naming the wrong client.
#: Measured across the whole package, not just docProps: dc:creator carries
#: the SCHOOL'S SIGNATORY as the document's author, cp:category their office,
#: and Word's CoverPageProperties part carries the school's address, the
#: student count and the contract value.
METADATA = {
    "Sandur Education Centre": "<School Name>",
    "Innovation Nexus": "<Program name>",
    "Smt. Y S Ghorpade": "<School Signatory>",
    "President": "<School Signatory Title>",
    "Chief Executive Officer": "<ask:Chief Executive Officer>",
    ADDRESS: "<School Address>",
    "75": "<ask:75>",
    "3,00,000": "<ask_calculate:Rs. 3,00,000/- Net (Including GST).>",
    # app.xml <Manager>, which the body renders through a DOCPROPERTY
    # field -- so this one is not merely properties, it is on the page.
    "Mr N S Ajith Kumar": "<ask:Mr N S Ajith Kumar>",
    # docProps/custom.xml: the document-control block.
    "New": "<ask:New>",
    "0.85": "<new_version>",
    "2026-09-01T00:00:00": "<ask:MOU date>",
}

#: Which parts to clean. customXml/item1.xml is Word's cover-page property
#: store and is the surprising one.
METADATA_PARTS = ("docProps/core.xml", "docProps/app.xml",
                  "docProps/custom.xml", "customXml/item1.xml")


def _neutralise_metadata(docx_bytes: bytes) -> bytes:
    """Rewrite the package's metadata so the template names nobody.

    NO TAG CAN REACH THIS. `scan` and `apply_tags` both walk paragraphs, and
    document properties are not paragraphs -- so a contract built for one
    school and sent to another would carry the first school's name, address,
    student count and deal value in its properties, invisible to anyone
    reading the page. Word shows dc:title in its title bar, in File > Info and
    in Explorer's preview pane.

    Parsed with lxml and rewritten ELEMENT BY ELEMENT rather than by string
    replacement. A tag contains angle brackets, and pasting one into XML text
    produces a package Word refuses to open -- which is exactly what the first
    version of this function did. Setting `.text` lets lxml escape it.

    Only a whole-value match is replaced, so "75" cannot corrupt a date and
    "President" cannot corrupt a sentence.
    """
    import zipfile

    from lxml import etree

    src = io.BytesIO(docx_bytes)
    out = io.BytesIO()
    changed = []
    with zipfile.ZipFile(src) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in METADATA_PARTS:
                root = etree.fromstring(data)
                for node in root.iter():
                    value = (node.text or "").strip()
                    if value in METADATA:
                        node.text = METADATA[value]
                        changed.append("%s/%s"
                                       % (item.filename.split("/")[-1],
                                          etree.QName(node).localname))
                data = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8",
                    standalone=True)
            zout.writestr(item, data)
    print("  metadata: %d client-specific value(s) neutralised -- %s"
          % (len(changed), ", ".join(changed)))
    return out.getvalue()


def main() -> int:
    write = "--write" in sys.argv
    with open(SOURCE, "rb") as fh:
        source_bytes = fh.read()
    doc = Document(io.BytesIO(source_bytes))
    walk = dt.walk_paragraphs(doc)
    print("source: %s\n        %d bytes, %d paragraphs"
          % (SOURCE, len(source_bytes), len(walk)))
    print("-" * 104)

    failures = 0
    # Right to left within a paragraph, and by descending ordinal, for the
    # same reason the writer works that way: an earlier replacement must not
    # move a later one. Each entry re-reads the LIVE text, so two identical
    # entries for one paragraph correctly take the two occurrences in it.
    for ordinal, old, new, why in sorted(TAGS, reverse=True):
        if not 0 <= ordinal < len(walk):
            print("MISSING  %4d  no such paragraph" % ordinal)
            failures += 1
            continue
        paragraph = walk[ordinal]
        text = dt.node_text(paragraph)
        start = text.rfind(old)
        if start < 0:
            print("MISSING  %4d  %r not in %r" % (ordinal, old, text[:60]))
            failures += 1
            continue
        if write:
            dt.replace_span(paragraph, start, start + len(old), new)
        print("%s %4d  %-34s -> %-38s  (%s)"
              % ("tagged " if write else "would  ", ordinal,
                 repr(old[:32]), new[:38], why))

    print("-" * 104)
    print("%d replacements, %d distinct tags"
          % (len(TAGS), len({t[2] for t in TAGS})))
    if failures:
        print("\n%d target(s) not found; nothing written." % failures)
        return 1
    if not write:
        print("\ndry run only. Pass --write to produce:\n  %s" % TARGET)
        return 0

    buf = io.BytesIO()
    doc.save(buf)
    tagged = _neutralise_metadata(buf.getvalue())
    with open(TARGET, "wb") as fh:
        fh.write(tagged)
    print("\nwrote %s (%d bytes)" % (TARGET, len(tagged)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
