# tests/docx/test_mou_golden.py
"""The MOU pipeline, end to end, over the owner's real contract (Task G1).

Opt-in like `test_golden_samples.py` and `test_simple_golden.py`:
`data/samples/` is the organisation's own material and is not in git, so every
test here skips on a clean checkout and runs on the VM, where it is the real
proof.

The fixture is `Sandur Education Centre_IBC Nexus and Lab2_MoU (tagged).docx`
-- a signed contract for a real school, tagged over three passes by
`scripts/tag_mou_sample.py`. Everything it exercises that the synthetic
fixtures cannot: 240 paragraphs of which 47 are outside the body, eight
tables, eleven images, sixty-five tags of thirty-three distinct literals, and
a client's name in THIRTEEN metadata values that no tag can reach.

**The model is scripted.** What is real is the document, the scan, the writer,
the properties, the status machine, the PDF and the refusal to write a
`Proposal` row. How many ROUNDS a live model needs is not knowable here and is
not claimed here -- amendment L withdrew four separate projections, and a
scripted layer that answers everything at once would only produce a fifth.

**Counted over the WHOLE PACKAGE, not the paragraph walk.** The owner opened a
document this project had called clean and found the school's name still in
it; every check until then had counted over `word/*.xml`. `_package_count`
below is the check that would have caught it.
"""
import io
import zipfile
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select

from app.ai import docx_tagfill
from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.mou import MouDocument, MouStatus
from app.models.program import ProposalTemplate, ProposalTemplateDoc
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services import storage
from app.services.docx import convert
from app.services.docx import properties as props
from app.services.docx import tags as docx_tags
from tests.conftest import auth
from tests.docx.test_text import raw_count

API = "/api/v1"
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
ORIGINAL = SAMPLES_DIR / "Sandur Education Centre_IBC Nexus and Lab2_MoU.docx"
TAGGED = SAMPLES_DIR / (
    "Sandur Education Centre_IBC Nexus and Lab2_MoU (tagged).docx")

pytestmark = [
    pytest.mark.skipif(not TAGGED.exists(),
                       reason="data/samples/ not present"),
]

#: Measured against both documents on 2026-09-10, by this session, rather than
#: copied from the plan. Tagging replaces text in place and inserts nothing,
#: so the tagged document matches the original exactly -- and so must the
#: document built from it.
EXPECTED_PARAGRAPHS = 240
EXPECTED_SECTIONS = 3
EXPECTED_TABLES = 8
EXPECTED_MEDIA = 11

#: Sixty-five occurrences of thirty-three distinct literals, after three
#: tagging passes. The third pass is the one that found the metadata.
EXPECTED_OCCURRENCES = 65
EXPECTED_DISTINCT = 33
EXPECTED_BY_KIND = {"semantic": 22, "ask": 39, "ask_calculate": 4}

#: What the previous client's contract said. NONE of it may survive anywhere
#: in a document built for somebody else -- and two of the ten occurrences of
#: the school's name are outside the body, where nobody scrolling would look.
THE_PREVIOUS_CLIENT = (
    "Sandur Education Centre",
    "Innovation Nexus",
    "Y S Ghorpade",
    "Rs. 1,50,000",
    "Rs. 3,00,000",
    "N S Ajith Kumar",
    "Sunila Johnson",
)

#: What the salesperson answers, keyed by the tag's literal -- a tag_id is a
#: hash of a position and would make this table unreadable. Every one of the
#: thirty-three is here; a missing one leaves a question open for ever and the
#: fill never reaches its review.
ANSWERS = {
    # semantic -- filled without asking when the dossier supports them
    "<School Name>": "Orchid International School",
    "<School Signatory>": "Dr Anitha Rao",
    "<School Signatory Title>": "Principal",
    "<School Address>": "12 Hosur Road, Bengaluru 560095",
    "<Program name>": "Innovation Base Course",
    "<org address>": "YuviPep Education Private Limited, Bengaluru",
    "<slug>": "'First Party'",
    "<new_version>": "1.0",
    "<duration>": "AY 2026-27",
    "<no. of years>": "one academic year",
    # ask -- always put to a person, whatever the model's confidence (D4)
    "<ask:Innovation Nexus>": "Innovation Base Course",
    "<ask:Yes>": "Yes",
    "<ask:75>": "80",
    "<ask:32>": "36",
    "<ask:1>": "1",
    "<ask:1 Set>": "2 Sets",
    "<ask:Eligible>": "Eligible",
    "<ask:3, 5, 6, 7, 8 and 9>": "3, 5, 6, 7 and 8",
    "<ask:AY 2026-27>": "AY 2026-27",
    "<ask:AY 2027-28>": "AY 2027-28",
    "<ask:Chief Executive Officer>": "Chief Executive Officer",
    "<ask:Mr N S Ajith Kumar>": "Mr Jakati Vikram",
    "<ask:Mr Jakati Vikram>": "Mr Jakati Vikram",
    "<ask:Sunila Johnson>": "R Menon",
    "<ask:New>": "New",
    "<ask:1.9.2026>": "10.9.2026",
    "<ask:date of signing>": "10.9.2026",
    "<ask:second week of February 2027>": "second week of March 2027",
    "<ask:first week of November 2026>": "first week of December 2026",
    "<ask:First Day of September, Two Thousand Twenty-Six (01-09-2026)>":
        "Tenth Day of September, Two Thousand Twenty-Six (10-09-2026)",
    # ask_calculate -- a figure, always asked, never computed by a model (D15)
    "<ask_calculate:Rs. 4000/- net (including GST) per student annually.>":
        "Rs. 4,200/- net (including GST) per student annually.",
    "<ask_calculate:Rs. 1,50,000/- Net (including GST).>":
        "Rs. 1,68,000/- Net (including GST).",
    "<ask_calculate:Rs. 3,00,000/- Net (Including GST).>":
        "Rs. 3,36,000/- Net (Including GST).",
}


THE_NEW_CLIENT = ANSWERS["<School Name>"]


def _package_count(data: bytes, literal: str) -> int:
    """Count a literal across EVERY part of the package.

    `raw_count` is the body's ground truth and walks `word/*.xml` only, which
    is precisely the blind spot the owner found by hand: the school's name was
    in `docProps/core.xml`, `docProps/app.xml`, `docProps/custom.xml` and
    Word's `customXml` cover-page store, and every check this project had said
    the document was clean.
    """
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        for name in package.namelist():
            if name.endswith((".png", ".jpeg", ".jpg", ".gif", ".emf",
                              ".wmf", ".bin")):
                continue
            total += package.read(name).decode("utf8", "replace").count(literal)
    return total


def _shape(data: bytes) -> dict:
    from app.services.docx import text as dt

    document = Document(io.BytesIO(data))
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        media = [n for n in package.namelist()
                 if n.startswith("word/media/")]
    return {"paragraphs": len(list(dt.walk_paragraphs(document))),
            "sections": len(document.sections),
            "tables": len(document.tables),
            "media": len(media)}


class FillLayer:
    """Answers whatever it is asked, from ANSWERS, by reading the prompt.

    Scripted on purpose. The subject of this file is the DOCUMENT -- that
    sixty-five tags in a real contract are found, written and left behind
    nowhere -- and a live model would make every assertion below flaky without
    making any of them stronger.
    """

    def __init__(self, occurrences):
        self.occurrences = occurrences
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]
        if "ARITHMETICALLY RELATED" in prompt:
            # D-E belongs to F2's tests. A build must not depend on a model
            # having proposed any arithmetic.
            return {"relations": []}
        return {"resolutions": [
            {"tag_id": o["tag_id"], "value": ANSWERS[o["raw"]],
             "reason": "scripted", "citation": "turn 1", "confidence": 1.0}
            for o in self.occurrences if o["tag_id"] in prompt]}


async def _ctx(client, token) -> OrgContext:
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                      role=me["role"], email=me["email"])


async def _ground(client, token, code):
    """Upload the tagged contract as this programme's current MOU template.

    `code` is per-test: `client` and `org_a` are session-scoped, so one
    programme code shared by three tests turns the second upload into a 409
    and the failure surfaces as a KeyError on the response body.
    """
    resp = await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"IBC Nexus {code}", "code": code, "description": "d"})
    assert resp.status_code == 200, resp.text[:300]
    program = resp.json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Sandur MoU tagged", "make_current": "true",
              "flow": "simple", "document_type": "mou"},
        files={"file": (TAGGED.name, TAGGED.read_bytes(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")})
    assert resp.status_code == 200, resp.text[:400]
    lead_id = (await client.post(
        f"{API}/leads", headers=auth(token),
        json={"name": THE_NEW_CLIENT + " " + code})).json()["id"]
    return program["id"], resp.json(), lead_id


async def _plan_tags(program_id):
    async with SessionLocal() as db:
        template = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.program_id == program_id,
            ProposalTemplate.is_current.is_(True)))).scalars().first()
        row = (await db.execute(select(ProposalTemplateDoc).where(
            ProposalTemplateDoc.template_id == template.id))).scalar_one()
    return (row.plan_json or {}).get("tags") or []


# --- the fixture itself -------------------------------------------------------


def test_tagging_changed_no_structure():
    """`replace_span` writes in place and inserts nothing. If tagging had
    changed the shape, every later assertion about the BUILT document would be
    measuring the wrong baseline."""
    if not ORIGINAL.exists():
        pytest.skip("the untagged original is not present")
    tagged, plain = _shape(TAGGED.read_bytes()), _shape(ORIGINAL.read_bytes())

    assert tagged == plain
    assert tagged["paragraphs"] == EXPECTED_PARAGRAPHS
    assert tagged["sections"] == EXPECTED_SECTIONS
    assert tagged["tables"] == EXPECTED_TABLES
    assert tagged["media"] == EXPECTED_MEDIA


def test_the_scan_finds_every_tag_the_owner_wrote():
    occurrences = docx_tags.scan(TAGGED.read_bytes())
    by_kind = {}
    for occurrence in occurrences:
        by_kind[occurrence.kind] = by_kind.get(occurrence.kind, 0) + 1

    assert len(occurrences) == EXPECTED_OCCURRENCES
    assert len({o.raw for o in occurrences}) == EXPECTED_DISTINCT
    assert by_kind == EXPECTED_BY_KIND
    # D1 again, on a contract: one literal, ten places, ten identities.
    school = [o for o in occurrences if o.raw == "<School Name>"]
    assert len(school) == 10
    assert len({o.tag_id for o in school}) == 10


def test_every_tag_has_an_answer_in_this_file():
    """A literal with no answer leaves a question open for ever, and the fill
    below would never reach its review -- as a timeout rather than as
    anything that names the missing tag."""
    missing = {o.raw for o in docx_tags.scan(TAGGED.read_bytes())} - set(ANSWERS)
    assert missing == set()


def test_the_tagged_template_names_nobody_ANYWHERE_in_the_package():
    """THE CHECK THAT WAS MISSING. Counted over every part of the zip, not
    over the paragraph walk -- the walk is what said the document was clean
    while `dc:title` still read "Sandur Education Centre"."""
    data = TAGGED.read_bytes()
    for literal in ("Sandur Education Centre", "Smt. Y S Ghorpade"):
        assert _package_count(data, literal) == 0, literal
    # And the original really did carry them, so the check above is not
    # passing because it is looking in the wrong place.
    if ORIGINAL.exists():
        assert _package_count(ORIGINAL.read_bytes(),
                              "Sandur Education Centre") > 0


# --- the whole flow -----------------------------------------------------------


#: Built ONCE and reused. `monkeypatch` is function-scoped so the fixture has
#: to be too, but the work behind it -- a real fill over 65 tags and a real
#: LibreOffice conversion of a 2 MB contract -- is done a single time. Doing
#: it per test also collided on the programme code, which surfaced as a
#: KeyError on a 409 body rather than as anything about programmes.
_BUILT: dict = {}


@pytest.fixture
async def built(client, org_a, monkeypatch):
    """Upload, resolve, answer, review, approve, build. The real thing."""
    if _BUILT:
        return _BUILT["it"]
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, template, lead_id = await _ground(client, token, "G1MOU")
    occurrences = await _plan_tags(program_id)
    monkeypatch.setattr(docx_tagfill, "get_model_layer",
                        lambda: FillLayer(occurrences))

    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-g1mou", document_type="mou")
        rounds = 0
        while fs.open_questions(session, limit=None):
            before = len(fs.open_questions(session, limit=None))
            session = await fs.apply_answers(db, ctx, session, "as agreed")
            rounds += 1
            assert len(fs.open_questions(session, limit=None)) < before, (
                "a round settled nothing; this would never terminate")
        assert session.status == FillStatus.REVIEWING
        await fs.mark_ready(db, session)
        mou = await fs.build(db, ctx, session)

    _BUILT["it"] = {
        "ctx": ctx, "mou": mou, "lead_id": lead_id, "rounds": rounds,
        "program_id": program_id, "session_id": session.id,
        "docx": storage.read_bytes(ctx.org_id, mou.docx_path)}
    return _BUILT["it"]


async def test_the_contract_is_built_and_is_not_a_proposal(built):
    """D-A, over the real document. An MOU wearing a Proposal's clothes would
    arrive on an already-closed deal and advance its state on its own."""
    mou = built["mou"]
    assert isinstance(mou, MouDocument)
    assert mou.status == MouStatus.DRAFT
    assert mou.docx_path and mou.filled_json

    async with SessionLocal() as db:
        proposals = (await db.execute(select(Proposal).where(
            Proposal.lead_id == built["lead_id"]))).scalars().all()
    assert proposals == [], "the contract created a Proposal row"


async def test_no_placeholder_survives_anywhere_including_the_footers(built):
    """47 of the 240 paragraphs are outside the body, and two of the ten
    `<School Name>` are among them."""
    assert docx_tags.scan(built["docx"]) == []
    for literal in THE_PREVIOUS_CLIENT:
        assert _package_count(built["docx"], literal) == 0, literal


async def test_the_built_contract_names_the_NEW_client(built):
    data = built["docx"]
    assert raw_count(data, THE_NEW_CLIENT) >= 10, (
        "the client's name reached fewer places than the template had tags")
    assert "Dr Anitha Rao" in built["mou"].content_md


async def test_the_built_contract_keeps_the_documents_shape(built):
    """Eight tables and eleven images survive being written into. A fill that
    reflowed the document would be a different bug wearing this one's
    clothes."""
    assert _shape(built["docx"]) == {
        "paragraphs": EXPECTED_PARAGRAPHS, "sections": EXPECTED_SECTIONS,
        "tables": EXPECTED_TABLES, "media": EXPECTED_MEDIA}


async def test_the_built_contract_carries_no_tag_text_in_its_PROPERTIES(built):
    """Plan amendment K, over the real document. The template's `dc:title`
    reads `<School Name>` on purpose, and until F3 nothing filled it."""
    assert props.tag_like(built["docx"]) == []
    core = Document(io.BytesIO(built["docx"])).core_properties
    assert core.title.startswith(THE_NEW_CLIENT)
    assert core.author == "", "a person at the previous client is the author"
    assert core.category == "" and core.keywords == ""


async def test_the_pdf_carries_the_new_client_and_not_the_old(built):
    """One real LibreOffice conversion over a real contract -- the last thing
    between this pipeline and a client's inbox."""
    from pypdf import PdfReader

    mou = built["mou"]
    assert mou.pdf_path, "the build produced no PDF"
    pdf = storage.read_bytes(built["ctx"].org_id, mou.pdf_path)
    assert pdf[:5] == b"%PDF-"

    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    assert len(text) > 2000, "the PDF has no text layer to check"
    assert THE_NEW_CLIENT in text, "the client is not named in the PDF"
    for literal in ("Sandur", "Ghorpade"):
        assert literal not in text, (
            "%r reached the PDF a client actually receives" % literal)
    # 6, not 8 (13 Oct 2026): Word lays this built contract out on 6 pages.
    # The old 8 was LibreOffice 7.3 overflowing it with substituted fonts;
    # the converter now matches Word.
    assert len(reader.pages) >= 6, (
        "a conversion that produced a near-empty PDF would satisfy every "
        "assertion above; this contract is %d pages" % len(reader.pages))


async def test_what_went_into_the_contract_is_recorded_for_the_app(built):
    """Sixty-five entries, one per occurrence, with the complex flow's six
    keys plus computed_by and citation."""
    filled = built["mou"].filled_json
    assert len(filled) == EXPECTED_OCCURRENCES
    for entry in filled:
        assert set(entry) == {"key", "kind", "source", "text", "brief",
                              "anchor", "computed_by", "citation"}
    assert all(e["text"] for e in filled), "a value reached the app empty"


async def test_the_broken_word_fields_are_neither_added_nor_removed(built):
    """FOR THE OWNER, and unchanged since it was first reported: three field
    references in their source document read "Error! Reference source not
    found." and "Error! No text of specified style in document.", at walk
    ordinals 209, 232 and 236. No tag can fix them and they print into every
    MOU built from this template. This test does not fail while they are
    there -- it fails if the BUILD starts adding or dropping them, which would
    mean the writer is touching fields it has no business touching.
    """
    before = _package_count(TAGGED.read_bytes(), "Error!")
    assert _package_count(built["docx"], "Error!") == before
