# tests/docx/test_mou_properties.py
"""The properties no tag can reach (plan amendment K, spec 12.7).

The owner opened an MOU this project had declared clean and asked "why haven't
you changed the school name?". Every verification until then had counted
literals over the PARAGRAPH WALK, and a .docx is a zip of many parts. The name
was in `dc:title`, which Word shows in its title bar, in File > Info and in
Explorer's preview pane -- and in twelve other metadata values across four
parts, including the school's own signatory as the document's AUTHOR and, in
Word's cover-page store, the school's address, its student count and the
contract value.

The tagging script neutralised all of them, so the template names nobody.
Nothing filled them. These tests are the other half.
"""
import io
import zipfile

import pytest
from docx import Document

from app.services.docx import properties as props

CUSTOM = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties">
<property name="Status"><lpwstr>&lt;ask:New&gt;</lpwstr></property>
<property name="Document version"><lpwstr>&lt;new_version&gt;</lpwstr></property>
</Properties>"""

COVER = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<CoverPageProperties xmlns="http://schemas.microsoft.com/office/2006/coverPageProps">
<PublishDate/><Abstract>&lt;ask:75&gt;</Abstract>
<CompanyAddress>&lt;School Address&gt;</CompanyAddress>
<CompanyFax>&lt;ask_calculate:Rs. 3,00,000&gt;</CompanyFax>
</CoverPageProperties>"""


def _template(**core) -> bytes:
    """A package shaped like the owner's tagged MOU: tag text in all four
    property parts, including the two python-docx does not write itself."""
    document = Document()
    document.add_paragraph("Prepared for <School Name>.")
    properties = document.core_properties
    properties.title = core.get("title", "<School Name>")
    properties.subject = core.get("subject", "<Program name>")
    properties.author = core.get("author", "<School Signatory>")
    properties.keywords = core.get("keywords", "<ask:Chief Executive Officer>")
    properties.category = core.get("category", "<School Signatory Title>")
    properties.last_modified_by = core.get("last_modified_by", "Sunila Johnson")
    buf = io.BytesIO()
    document.save(buf)
    return _with_parts(buf.getvalue(), {
        "docProps/custom.xml": CUSTOM,
        "customXml/item1.xml": COVER,
    })


def _with_parts(docx_bytes: bytes, parts: dict[str, bytes]) -> bytes:
    """REPLACES rather than appends. python-docx's own default template
    already ships a `customXml/item1.xml`, and a zip carrying the name twice
    is a fixture that reads whichever copy the reader happens to reach."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename not in parts:
                zout.writestr(item, zin.read(item.filename))
        for name, data in parts.items():
            zout.writestr(name, data)
    return out.getvalue()


def _manager(docx_bytes: bytes, value: str) -> bytes:
    """app.xml's <Manager>. Not merely properties: the owner's document
    RENDERS it on the page through a DOCPROPERTY field."""
    from lxml import etree

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/app.xml":
                root = etree.fromstring(data)
                node = etree.SubElement(
                    root, "{http://schemas.openxmlformats.org/"
                          "officeDocument/2006/extended-properties}Manager")
                node.text = value
                data = etree.tostring(root, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    return out.getvalue()


def _core(docx_bytes: bytes):
    return Document(io.BytesIO(docx_bytes)).core_properties


def _texts(docx_bytes: bytes) -> set[str]:
    return {text for _part, _name, text in props.read(docx_bytes)}


# --- the map from the fill's own record --------------------------------------


def test_a_literal_the_fill_settled_is_available_to_a_property():
    tags = [{"raw": "<School Name>", "outcome": "filled",
             "value": "Orchid International School"}]
    assert props.values_from(tags) == {
        "<School Name>": "Orchid International School"}


def test_a_literal_whose_occurrences_disagree_yields_nothing():
    """F1's `(raw, context)` key exists because one literal is often several
    questions: the MOU's `<ask:Yes>` is once per deliverables row. A property
    carries the literal alone, so there is nothing to choose between them --
    and choosing one of seven answers arbitrarily is worse than choosing none.
    """
    tags = [{"raw": "<ask:Yes>", "outcome": "filled", "value": "Yes"},
            {"raw": "<ask:Yes>", "outcome": "filled", "value": "No"}]
    assert props.values_from(tags) == {}


def test_the_same_answer_twice_is_not_a_disagreement():
    tags = [{"raw": "<ask:75>", "outcome": "filled", "value": "80"},
            {"raw": "<ask:75>", "outcome": "filled", "value": "80"}]
    assert props.values_from(tags) == {"<ask:75>": "80"}


def test_an_unanswered_question_has_no_value_to_give():
    """Its `value` still holds whatever the template's author proposed, which
    is the template's words and not this client's."""
    tags = [{"raw": "<ask:75>", "outcome": "question", "value": "75"}]
    assert props.values_from(tags) == {}


# --- filling ------------------------------------------------------------------


def test_a_tag_in_a_property_is_filled_from_the_value_that_filled_the_body():
    built = props.fill(_template(), {"<School Address>": "12 Hosur Road"})
    assert "12 Hosur Road" in _texts(built)


def test_no_property_anywhere_still_reads_like_a_tag():
    """THE defect. Counted over the whole package, not the paragraph walk."""
    built = props.fill(_template(), {"<School Address>": "12 Hosur Road"},
                       title="Orchid International School",
                       subject="Innovation Nexus")
    assert props.tag_like(built) == []


def test_a_tag_with_nothing_to_fill_it_is_blanked_rather_than_shipped():
    """There is no value for any of these. A property reading "<School Name>"
    in a signed contract is the defect, not a smaller version of it."""
    built = props.fill(_template(), {})
    assert props.tag_like(built) == []
    assert "<School Address>" not in _texts(built)


def test_the_manager_field_is_reached_too():
    """app.xml, and the owner's document renders it ON THE PAGE through a
    DOCPROPERTY field -- so leaving this one would print tag text."""
    source = _manager(_template(), "<ask:Mr N S Ajith Kumar>")
    built = props.fill(source, {"<ask:Mr N S Ajith Kumar>": "Jakati Vikram"})
    assert "Jakati Vikram" in _texts(built)


def test_the_cover_page_store_is_reached_too():
    """customXml/item1.xml, the surprising part: it carried the school's
    address, its student count and the contract value."""
    built = props.fill(_template(), {
        "<ask:75>": "80",
        "<ask_calculate:Rs. 3,00,000>": "Rs. 3,20,000/- Net",
    })
    texts = _texts(built)
    assert "80" in texts and "Rs. 3,20,000/- Net" in texts


def test_the_document_control_block_is_reached_too():
    built = props.fill(_template(), {"<new_version>": "1.0"})
    assert "1.0" in _texts(built)


def test_words_around_a_tag_survive_it():
    """A property that merely CONTAINS a tag keeps its own words. The run is
    replaced in place; the property is not overwritten."""
    document = Document()
    document.core_properties.comments = "Prepared for <School Name> in 2026"
    buf = io.BytesIO()
    document.save(buf)
    built = props.fill(buf.getvalue(), {"<School Name>": "Orchid"})
    assert "Prepared for Orchid in 2026" in _texts(built)


# --- what the document IS ------------------------------------------------------


def test_the_client_and_the_programme_are_written_into_the_core_properties():
    built = props.fill(_template(), {}, title="Orchid International School",
                       subject="Innovation Nexus")
    core = _core(built)
    assert core.title == "Orchid International School"
    assert core.subject == "Innovation Nexus"


def test_the_stated_title_wins_over_whatever_a_literal_would_have_given():
    """`title` is not a guess from a literal; it is what this document is."""
    built = props.fill(_template(), {"<School Name>": "Somebody Else"},
                       title="Orchid International School")
    assert _core(built).title == "Orchid International School"


def test_a_client_whose_own_name_has_angle_brackets_keeps_it():
    """Why the stated title is written AFTER the literals are filled, and not
    before. The order looks cosmetic -- either way the title ends up as the
    client -- until the client is really called "Orchid <Pvt> Ltd". That name
    matches the tag grammar, so filling literals over it afterwards blanks the
    client out of their own contract.

    This is the test that discriminates. Its neighbour above pins the outcome
    but passes in both orders, because by then the title holds no literal for
    the second pass to find."""
    built = props.fill(_template(), {}, title="Orchid <Pvt> Ltd",
                       subject="Nexus <2026>")
    core = _core(built)
    assert core.title == "Orchid <Pvt> Ltd"
    assert core.subject == "Nexus <2026>"


def test_nobody_is_left_as_the_author_of_a_contract():
    """The template carried the SCHOOL'S signatory as dc:creator, so an MOU
    would go out authored by a person at the previous client. `keywords` held
    an office and `category` a title; `lastModifiedBy` is a member of staff."""
    built = props.fill(_template(), {}, title="Orchid", subject="Nexus")
    core = _core(built)
    assert core.author == ""
    assert core.keywords == ""
    assert core.category == ""
    assert core.last_modified_by == ""


def test_a_missing_core_property_is_created_rather_than_skipped():
    """Declining to write dc:title because the element was absent would
    reproduce the defect this module closes."""
    from lxml import etree

    source = _template()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(source)) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == props.CORE:
                root = etree.fromstring(data)
                for node in list(root):
                    if etree.QName(node).localname == "title":
                        root.remove(node)
                data = etree.tostring(root, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
            zout.writestr(item, data)

    built = props.fill(out.getvalue(), {}, title="Orchid International School")
    assert _core(built).title == "Orchid International School"


# --- the package must survive being written ------------------------------------


def test_the_package_still_opens_after_its_properties_are_written():
    """The neutraliser's first version pasted a tag's ANGLE BRACKETS into
    element text and produced a package python-docx and Word both refuse. The
    fix -- and the reason this module parses with lxml rather than replacing
    strings -- is that escaping becomes lxml's job. This is the guard that
    turned that silent corruption into an immediate failure."""
    built = props.fill(_template(), {"<School Name>": "Orchid & Sons <Pvt>"},
                       title="Orchid & Sons <Pvt> Ltd")
    document = Document(io.BytesIO(built))
    assert document.paragraphs[0].text == "Prepared for <School Name>."
    assert document.core_properties.title == "Orchid & Sons <Pvt> Ltd"


def test_every_other_part_of_the_package_is_left_exactly_alone():
    """11 images, 8 tables and the body itself. Only properties change."""
    source = _template()
    built = props.fill(source, {}, title="Orchid")
    with zipfile.ZipFile(io.BytesIO(source)) as before, \
            zipfile.ZipFile(io.BytesIO(built)) as after:
        assert before.namelist() == after.namelist()
        untouched = [n for n in before.namelist() if n not in props.PARTS]
        assert untouched, "the fixture proves nothing if it is all properties"
        for name in untouched:
            assert before.read(name) == after.read(name), name


@pytest.mark.parametrize("part", props.PARTS)
def test_every_part_this_module_claims_is_actually_in_the_fixture(part):
    """A test that silently walks a part the fixture does not contain proves
    nothing about that part."""
    with zipfile.ZipFile(io.BytesIO(_manager(_template(), "x"))) as zin:
        assert part in zin.namelist()
