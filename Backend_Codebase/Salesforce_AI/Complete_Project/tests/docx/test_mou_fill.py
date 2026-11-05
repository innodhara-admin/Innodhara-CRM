# tests/docx/test_mou_fill.py
"""The fill session serves BOTH document types (D-C).

`proposal_fill_service` is 868 lines, of which only `_write_proposal`,
`_commercials`, `_rewrite_proposal` and `_attach_pdf` -- about 270 -- are
proposal-specific. The status machine is document-type-agnostic: gathering ->
asking -> reviewing -> ready -> built, `mark_ready` as the only door, the
seven-day sweep, the correction path. An MOU inherits all of it rather than
duplicating a machine that took three tasks and thirty-four mutation checks
to get right.

Two columns make that safe. `mou_id` is where a built MOU is recorded, beside
`proposal_id`; exactly one of the two is ever set. `document_type` is the
discriminator, and without it an MOU fill and a proposal fill for the same
lead, the same programme and the same chat are indistinguishable to
`find_for_chat` -- so a reply about one would land on the other.

The model layer is stubbed throughout. What it says belongs to C2's tests;
what is KEPT belongs here.
"""
import io

import pytest
from docx import Document
from sqlalchemy import select

from app.core.exceptions import ValidationFailedError
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.mou import MouDocument, MouRevision, MouStatus
from app.models.proposal import Proposal
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services import storage
from tests.conftest import auth
from tests.docx.test_fill_service import _ctx, _lead, _tagged_docx, _use

API = "/api/v1"
pytestmark = pytest.mark.asyncio


async def _program(client, token, code) -> str:
    return (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"MOU fill {code}", "code": code, "description": "d"},
    )).json()["id"]


async def _upload(client, token, program_id, *, name, document_type):
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": name, "make_current": "true", "flow": "simple",
              "document_type": document_type},
        files={"file": ("t.docx", _tagged_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _both_templates(client, token, code):
    """One programme carrying a current proposal template AND a current MOU
    template -- the state D-B made possible and this task has to tell apart."""
    program_id = await _program(client, token, code)
    proposal = await _upload(client, token, program_id, name="p",
                             document_type="proposal")
    mou = await _upload(client, token, program_id, name="m",
                        document_type="mou")
    return program_id, proposal, mou


# ── the discriminator earns its place ───────────────────────────────────────
async def test_an_mou_fill_and_a_proposal_fill_do_not_collide(
    client, org_a, monkeypatch
):
    """Same lead, same programme, SAME CHAT.

    Without `document_type` these two rows are indistinguishable to
    `find_for_chat`, which keys on the chat alone -- so a reply about the MOU
    would be applied to the proposal, silently.
    """
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _, _ = await _both_templates(client, token, "MFILL1")
    lead_id = await _lead(client, token, "Sandur Education Centre")
    _use(monkeypatch, {"resolutions": []}, {"resolutions": []})

    async with SessionLocal() as db:
        proposal_fill = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-1", document_type="proposal")
        mou_fill = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-1", document_type="mou")

        found_mou = await fs.find_for_chat(db, ctx, chat_session_id="chat-1",
                                           document_type="mou")
        found_proposal = await fs.find_for_chat(
            db, ctx, chat_session_id="chat-1", document_type="proposal")

    assert proposal_fill.id != mou_fill.id
    assert found_mou.id == mou_fill.id
    assert found_proposal.id == proposal_fill.id


async def test_find_open_is_scoped_by_document_type(
    client, org_a, monkeypatch
):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _, _ = await _both_templates(client, token, "MFILL2")
    lead_id = await _lead(client, token, "Sandur Two")
    _use(monkeypatch, {"resolutions": []}, {"resolutions": []})

    # THE MOU IS OPENED FIRST, ON PURPOSE. find_open orders by updated_at
    # descending and takes the first row, so if the newer fill were the one
    # being asked for, deleting the document_type filter would still return
    # it and this test would pass against broken code. Asking for the OLDER
    # of the two means only the filter can produce the right answer.
    async with SessionLocal() as db:
        mou_fill = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-2", document_type="mou")
        proposal_fill = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-2", document_type="proposal")

        found = await fs.find_open(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-2", document_type="mou")

    assert found.id == mou_fill.id
    assert found.id != proposal_fill.id


async def test_a_fill_opens_on_the_template_of_its_own_document_type(
    client, org_a, monkeypatch
):
    """Threaded all the way down: open_session -> _simple_template ->
    _current, which M1 taught to filter."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, proposal, mou = await _both_templates(client, token, "MFILL3")
    lead_id = await _lead(client, token, "Sandur Three")
    _use(monkeypatch, {"resolutions": []}, {"resolutions": []})

    async with SessionLocal() as db:
        proposal_fill = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            document_type="proposal")
        mou_fill = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            document_type="mou")

    assert proposal_fill.template_id == proposal["id"]
    assert mou_fill.template_id == mou["id"]


# ── exactly one of the two id columns is ever set ───────────────────────────
async def test_a_new_fill_records_its_type_and_neither_id(
    client, org_a, monkeypatch
):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _, _ = await _both_templates(client, token, "MFILL4")
    lead_id = await _lead(client, token, "Sandur Four")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            document_type="mou")

    assert session.document_type == "mou"
    assert session.mou_id is None
    assert session.proposal_id is None


async def test_open_session_defaults_to_a_proposal(
    client, org_a, monkeypatch
):
    """No `document_type` argument at all -- every existing caller, including
    J1's agent branch, keeps behaving exactly as it did."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, proposal, _ = await _both_templates(client, token, "MFILL5")
    lead_id = await _lead(client, token, "Sandur Five")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id)

    assert session.document_type == "proposal"
    assert session.template_id == proposal["id"]


async def test_a_row_written_without_a_document_type_is_a_proposal(
    client, org_a
):
    """The model's own default, which is what the migration back-fills onto
    the four rows already in the live database."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, proposal, _ = await _both_templates(client, token, "MFILL6")
    lead_id = await _lead(client, token, "Sandur Six")

    async with SessionLocal() as db:
        row = ProposalFillSession(
            org_id=ctx.org_id, lead_id=lead_id, program_id=program_id,
            template_id=proposal["id"], template_doc_id=proposal["doc_id"],
            user_id=ctx.user_id, status=FillStatus.GATHERING,
            dossier_json={}, tags_json=[], asked_json=[],
        )
        db.add(row)
        await db.commit()
        written = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.id == row.id))).scalar_one()

    assert written.document_type == "proposal"
    assert written.mou_id is None


# ── correcting a built document ─────────────────────────────────────────────
async def test_find_correctable_for_an_mou_keys_on_mou_id(
    client, org_a, monkeypatch
):
    """`find_correctable` asks "is there a document we could write again?".

    For a proposal that means `proposal_id is not None`. For an MOU it must
    mean `mou_id is not None` -- an MOU fill never sets `proposal_id`, so
    keying on the wrong column makes a built MOU permanently uncorrectable
    and the salesperson's only route is answering every question afresh.
    """
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _, _ = await _both_templates(client, token, "MFILL7")
    lead_id = await _lead(client, token, "Sandur Seven")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-7", document_type="mou")
        # F3 sets these when it builds; here they are set directly, because
        # what is under test is the LOOKUP, not the build.
        session.status = FillStatus.BUILT
        session.mou_id = "0" * 32
        session.updated_at = utcnow()
        await db.commit()

        found = await fs.find_correctable(db, ctx, chat_session_id="chat-7",
                                          document_type="mou")

    assert found is not None
    assert found.id == session.id


async def test_a_built_mou_is_not_offered_as_a_correctable_proposal(
    client, org_a, monkeypatch
):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _, _ = await _both_templates(client, token, "MFILL8")
    lead_id = await _lead(client, token, "Sandur Eight")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id="chat-8", document_type="mou")
        session.status = FillStatus.BUILT
        session.mou_id = "0" * 32
        await db.commit()

        found = await fs.find_correctable(db, ctx, chat_session_id="chat-8",
                                          document_type="proposal")

    assert found is None


# ── D-E: the arithmetic reaches the review ──────────────────────────────────
def _priced_mou() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("Pricing Details", level=2)
    doc.add_paragraph("Price per student <ask_calculate:Rs. 4000>.")
    doc.add_paragraph("Students <ask:75>.")
    doc.add_paragraph("Payable annually <ask_calculate:Rs. 3,00,000>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def _priced_session(client, token, code, monkeypatch, answers):
    """An MOU fill whose three commercial tags carry `answers`.

    The fake layer answers BOTH passes -- the resolution pass and the relation
    pass -- by looking at which prompt it was handed, so the test does not
    depend on the order the service happens to call them in.
    """
    from app.ai import docx_tagfill as tf
    from app.services.docx import tags as dtags

    ctx = await _ctx(client, token)
    program_id = await _program(client, token, code)
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "m", "make_current": "true", "flow": "simple",
              "document_type": "mou"},
        files={"file": ("m.docx", _priced_mou(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")})
    assert resp.status_code == 200, resp.text
    lead_id = await _lead(client, token, "Sandur " + code)

    ids = {o.raw: o.tag_id for o in dtags.scan(_priced_mou())}

    class Layer:
        def __init__(self):
            self.calls = []

        async def generate_json(self, **kwargs):
            self.calls.append(kwargs)
            body = kwargs["messages"][-1]["content"]
            if "ARITHMETICALLY RELATED" in body:
                return {"relations": [{
                    "result": ids["<ask_calculate:Rs. 3,00,000>"],
                    "op": "product",
                    "operands": [ids["<ask_calculate:Rs. 4000>"],
                                 ids["<ask:75>"]],
                }]}
            return {"resolutions": [
                {"tag_id": tag_id, "value": answers[raw], "confidence": 1.0,
                 "citation": "turn 1", "reason": "the person said so"}
                for raw, tag_id in ids.items()]}

    monkeypatch.setattr(tf, "get_model_layer", lambda: Layer())

    # THE FIGURES COME FROM A PERSON, not from the first pass, and that is not
    # a convenience: `ask_calculate` always asks whatever the model's
    # confidence (D4), and fill_scrub refuses a money-shaped value the MODEL
    # wrote (C2, D15). So a value only exists here after a clarification turn,
    # which is exactly the path a real fill takes.
    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            document_type="mou")
        await fs.apply_answers(db, ctx, session, "as agreed")
        return session


HOLDS = {"<ask_calculate:Rs. 4000>": "Rs. 4000",
         "<ask:75>": "75",
         "<ask_calculate:Rs. 3,00,000>": "Rs. 3,00,000/- Net"}
BROKEN = dict(HOLDS, **{"<ask_calculate:Rs. 3,00,000>": "Rs. 2,50,000/- Net"})


async def test_a_relation_is_stored_on_the_result_tag(client, org_a,
                                                      monkeypatch):
    session = await _priced_session(client, org_a["admin_token"], "MFILL9",
                                    monkeypatch, HOLDS)
    with_relation = [t for t in session.tags_json if t.get("relation")]
    assert len(with_relation) == 1
    assert with_relation[0]["relation"]["op"] == "product"
    assert len(with_relation[0]["relation"]["operands"]) == 2


async def test_arithmetic_that_holds_warns_about_nothing(client, org_a,
                                                         monkeypatch):
    session = await _priced_session(client, org_a["admin_token"], "MFILLA",
                                    monkeypatch, HOLDS)
    assert fs.arithmetic_warnings(session) == {}
    assert all(not line["warnings"] for line in fs.review_lines(session))


async def test_a_total_that_is_not_price_times_students_reaches_the_review(
    client, org_a, monkeypatch
):
    """THE defect D-E exists for: a payment schedule whose own figures
    disagree, said plainly on the one screen a person is already reading."""
    session = await _priced_session(client, org_a["admin_token"], "MFILLB",
                                    monkeypatch, BROKEN)
    warnings = fs.arithmetic_warnings(session)
    assert len(warnings) == 1
    message = next(iter(warnings.values()))
    assert "2,50,000" in message and "3,00,000" in message

    flagged = [ln for ln in fs.review_lines(session) if ln["warnings"]]
    assert len(flagged) == 1
    assert flagged[0]["value"] == "Rs. 2,50,000/- Net", (
        "the check reports; it must never substitute its own figure"
    )


async def test_a_proposal_fill_asks_for_no_relations_at_all(client, org_a,
                                                            monkeypatch):
    """MOUs only. A proposal's ask_calculate is a figure on a page; an MOU's
    is a payment schedule, and there is no reason to spend a model call on
    the former."""
    from app.ai import docx_tagfill as tf

    calls = []

    class Layer:
        async def generate_json(self, **kwargs):
            calls.append(kwargs["messages"][-1]["content"])
            return {"resolutions": []}

    monkeypatch.setattr(tf, "get_model_layer", lambda: Layer())
    ctx = await _ctx(client, org_a["admin_token"])
    program_id, proposal, _ = await _both_templates(
        client, org_a["admin_token"], "MFILLC")
    lead_id = await _lead(client, org_a["admin_token"], "Sandur C")
    async with SessionLocal() as db:
        await fs.open_session(db, ctx, lead_id=lead_id,
                              program_id=program_id,
                              document_type="proposal")
    assert not any("ARITHMETICALLY RELATED" in c for c in calls)


# ── F3: the document itself ─────────────────────────────────────────────────
# Everything above this line is D-C and D-E: which fill a reply belongs to,
# and whether its arithmetic holds. Everything below is the build -- the one
# step in this flow that cannot be undone.


def _mou_docx() -> bytes:
    """A contract shaped like the owner's, and TAGGED IN ITS PROPERTIES.

    The properties are the point. `scan` and `apply_tags` walk paragraphs, so
    a fixture whose tags are all in the body cannot show the defect plan
    amendment K exists for: the owner opened a document this project had
    called clean and found the school's name still in Word's title bar.
    """
    from docx import Document

    doc = Document()
    doc.add_heading("Memorandum of Understanding", level=1)
    doc.add_paragraph(
        "Between <School Name> and YuviPep, a body paragraph long enough to "
        "serve as a style reference.")
    doc.add_paragraph("Programme: <Program name>. Signed by <School Signatory>.")
    doc.add_heading("Agreed Deliveries and Offers", level=2)
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).text = "S. No"
    table.cell(0, 1).text = "Deliverable"
    table.cell(0, 2).text = "Included"
    for row, item in enumerate(("Innovation Lab", "Teacher Training"), start=1):
        table.cell(row, 0).text = str(row)
        table.cell(row, 1).text = item
        table.cell(row, 2).text = "<ask:Yes>"

    core = doc.core_properties
    core.title = "<School Name>"
    core.subject = "<Program name>"
    core.author = "<School Signatory>"
    core.category = "<School Signatory Title>"
    core.keywords = "<ask:Chief Executive Officer>"
    core.last_modified_by = "Sunila Johnson"
    # Two properties that are neither cleared nor set outright, so what
    # reaches them is whatever the fill resolved -- which is the half of the
    # behaviour the cleared ones cannot show.
    core.content_status = "<Program name>"          # one agreed answer
    core.comments = "<ask:Yes>"                     # answered per row, so none

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


#: What a person answers. `<ask:Yes>` gets a DIFFERENT answer per row on
#: purpose: F1's collapse key is (raw, context) because one literal is often
#: several questions, and a property carrying that literal must therefore be
#: blanked rather than given one row's answer (see test_mou_properties).
MOU_ANSWERS = {
    "<School Name>": "Orchid International School",
    "<Program name>": "Innovation Nexus",
    "<School Signatory>": "Smt. R Kulkarni",
    "<School Signatory Title>": "Principal",
    "<ask:Chief Executive Officer>": "Chief Executive Officer",
    "<ask:Yes>": None,                       # answered per occurrence, below
}
PER_ROW = {"Innovation Lab": "Yes", "Teacher Training": "No"}


async def _mou_template(client, token, code, docx_bytes=None):
    program_id = await _program(client, token, code)
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "MOU", "make_current": "true", "flow": "simple",
              "document_type": "mou"},
        files={"file": ("mou.docx", docx_bytes or _mou_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")})
    assert resp.status_code == 200, resp.text
    return program_id, resp.json()


class _AnswerEverything:
    """Settles every occurrence, so the fill lands in `reviewing`.

    Answers the relation pass with nothing: D-E belongs to F2 and its tests,
    and a build must not depend on a model having proposed any arithmetic.
    """

    def __init__(self, tags, answers):
        self.tags, self.answers = tags, answers
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if "ARITHMETICALLY RELATED" in kwargs["messages"][-1]["content"]:
            return {"relations": []}
        return {"resolutions": [
            {"tag_id": tag["tag_id"], "confidence": 1.0,
             "value": self.answers.get(tag["raw"])
             or PER_ROW.get(tag.get("context"), "Yes"),
             "citation": "turn 1", "reason": "the person said so"}
            for tag in self.tags]}


async def _answered_mou(client, token, code, name, *, docx_bytes=None,
                        answers=None):
    """An MOU fill with every question settled: sitting in `reviewing`."""
    from app.ai import docx_tagfill as tf
    from app.services.docx import tags as dtags

    ctx = await _ctx(client, token)
    program_id, template = await _mou_template(client, token, code, docx_bytes)
    lead_id = await _lead(client, token, name)
    tags = [o.as_dict() for o in dtags.scan(docx_bytes or _mou_docx())]
    layer = _AnswerEverything(tags, dict(answers or MOU_ANSWERS))
    monkey = tf.get_model_layer
    tf.get_model_layer = lambda: layer
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(
                db, ctx, lead_id=lead_id, program_id=program_id,
                chat_session_id=f"chat-{code}", document_type="mou")
            # One reply per round, as a person gives them. An agreement
            # reaches only the round on screen (owner, 11 September), and
            # this contract's rounds are its two sections, so it takes two.
            while fs.open_questions(session, limit=None):
                before = len(fs.open_questions(session, limit=None))
                session = await fs.apply_answers(db, ctx, session, "as agreed")
                assert len(fs.open_questions(session, limit=None)) < before, (
                    "a round settled nothing; this would never terminate")
    finally:
        tf.get_model_layer = monkey
    assert session.status == FillStatus.REVIEWING, session.status
    return ctx, session, program_id, lead_id, template


@pytest.fixture
def no_pdf(monkeypatch):
    """LibreOffice takes seconds a call, and the real conversion is already
    proven for this code path by the proposal suite -- `_attach_pdf` is the
    same function. What is MOU-specific is the FAILURE path, which has its
    own test below."""
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-stub")


async def _built(client, token, code, name, **kwargs):
    """A built MOU.

    The type is asserted HERE, not left to each test. Half of these tests
    passed against a `Proposal` when this helper simply returned whatever
    `build` gave it -- a PDF is attached, a contents page is refreshed and
    `filled_json` carries the same eight keys either way. A fixture that
    hands back the wrong document type quietly makes every test below it a
    statement about the proposal flow.
    """
    ctx, session, program_id, lead_id, template = await _answered_mou(
        client, token, code, name, **kwargs)
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        mou = await fs.build(db, ctx, session)
    assert isinstance(mou, MouDocument), (
        "this fixture builds MOUs; it was handed a %s" % type(mou).__name__)
    return ctx, session, mou, lead_id, program_id


async def _count(model, **where):
    async with SessionLocal() as db:
        rows = (await db.execute(select(model).filter_by(**where))).scalars().all()
    return len(rows)


# --- the document, and the pipeline it must stay out of ----------------------


async def test_a_whole_mou_fill_builds_a_document_and_not_a_proposal(
    client, org_a, no_pdf
):
    """D-A, end to end. An MOU wearing a Proposal's clothes would arrive on an
    already-closed deal -- `inbound_engine` reads a SENT proposal as "the deal
    is agreed" -- and advance its state on its own."""
    _ctx_, _session, mou, lead_id, program_id = await _built(
        client, org_a["admin_token"], "F3ONE", "Orchid F3A")

    assert isinstance(mou, MouDocument)
    assert mou.docx_path and mou.filled_json
    assert mou.lead_id == lead_id and mou.program_id == program_id
    assert mou.status == MouStatus.DRAFT
    assert await _count(Proposal, lead_id=lead_id) == 0, (
        "an MOU created a Proposal row -- it would enter the sales pipeline")


async def test_an_mou_has_no_commercial_figures_to_be_wrong_about(
    client, org_a, no_pdf
):
    """DEFECT 2's lesson. The chat announced "Total amount: 2200" for a
    document reading Rs. 15,00,000 because the complex flow's machinery was
    carried across without asking whether its premise came too. A table with
    no total cannot make that mistake -- these fields are ABSENT, not merely
    unused, so no aggregate written later can pick an MOU up."""
    _c, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3TWO", "Orchid F3B")

    assert not hasattr(mou, "total_amount")
    assert not hasattr(mou, "line_items")
    assert not hasattr(mou, "pricing_table_id")
    assert not hasattr(mou, "project_id")


async def test_the_mou_records_which_template_version_built_it(
    client, org_a, no_pdf
):
    """The source document is never rewritten (D3), so these two resolve the
    exact bytes this contract came from."""
    _c, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3VER", "Orchid F3C")
    assert mou.template_version >= 1
    assert mou.title == "MOU fill F3VER MOU - Orchid F3C"
    assert "Orchid International School" in mou.content_md


# --- nothing half-written ships ----------------------------------------------


async def test_the_build_refuses_an_mou_with_anything_skipped(
    client, org_a, no_pdf, monkeypatch
):
    """`apply_tags` reports rather than raises, so acting on the report is
    this layer's job. A CONTRACT still reading "<ask:Yes>" is worse than no
    contract at all."""
    ctx, session, _p, lead_id, _t = await _answered_mou(
        client, org_a["admin_token"], "F3SKIP", "Orchid F3D")

    def _all_skipped(docx_bytes, occurrences, values):
        return {"docx": docx_bytes, "written": [],
                "skipped": [{"tag_id": o["tag_id"], "raw": o["raw"],
                             "reason": "the tag is no longer at those offsets"}
                            for o in occurrences]}

    monkeypatch.setattr(fs.tagfill, "apply_tags", _all_skipped)
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        with pytest.raises(ValidationFailedError) as err:
            await fs.build(db, ctx, session)

    assert "could not be written" in str(err.value)
    assert "MOU" in str(err.value), (
        "a salesperson correcting a contract must not be told about a proposal")
    assert await _count(MouDocument, lead_id=lead_id) == 0


async def test_an_mou_cannot_be_built_before_its_review(client, org_a, no_pdf):
    """D13 is not relaxed for a contract. `mark_ready` is the only door to
    `ready`, and `build` is reachable from nowhere else."""
    ctx, session, _p, lead_id, _t = await _answered_mou(
        client, org_a["admin_token"], "F3GATE", "Orchid F3E")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        with pytest.raises(ValidationFailedError) as err:
            await fs.build(db, ctx, session)
    assert "MOU" in str(err.value)
    assert await _count(MouDocument, lead_id=lead_id) == 0


async def test_approving_an_mou_twice_does_not_write_two_documents(
    client, org_a, no_pdf
):
    """J2's defect, and it applies unchanged. The status is asked about FIRST:
    a built session is no longer `ready`, so checking readiness first turns a
    double tap into "this has not been approved yet", which is both wrong and
    baffling. The document that exists is the answer to being asked again."""
    ctx, session, first, lead_id, _p = await _built(
        client, org_a["admin_token"], "F3TWICE", "Orchid F3F")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        second = await fs.build(db, ctx, session)

    assert first.id == second.id
    assert await _count(MouDocument, lead_id=lead_id) == 1


# --- what the app reads -------------------------------------------------------


async def test_what_went_into_the_mou_is_recorded_for_the_app(
    client, org_a, no_pdf
):
    """The Android card reads `filled_json`. THE COMPLEX FLOW'S SIX KEYS plus
    `computed_by` and `citation` -- renaming one turns a working card into a
    blank one, which is a defect the last session shipped and had to find by
    hand."""
    _c, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3CARD", "Orchid F3G")

    assert mou.filled_json
    for entry in mou.filled_json:
        assert set(entry) == {"key", "kind", "source", "text", "brief",
                              "anchor", "computed_by", "citation"}
    assert any(e["text"] == "Orchid International School"
               for e in mou.filled_json)


async def test_the_pdf_is_produced_and_a_failure_does_not_lose_the_mou(
    client, org_a, monkeypatch
):
    """The document is already written and stored by the time the converter
    runs, so raising here would throw away an approved CONTRACT over a
    converter hiccup."""
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-ok")
    _c, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3PDF", "Orchid F3H")
    assert mou.pdf_path

    def _broken(*args, **kwargs):
        raise RuntimeError("soffice is not installed")

    monkeypatch.setattr(fs.convert, "docx_to_pdf", _broken)
    _c2, _s2, second, _l2, _p2 = await _built(
        client, org_a["admin_token"], "F3PDX", "Orchid F3I")
    assert second.pdf_path is None
    assert second.docx_path                      # the contract survived


async def test_a_static_contents_page_is_remeasured_for_an_mou_too(
    client, org_a, no_pdf, monkeypatch
):
    """A static contents page carries page numbers only LibreOffice can
    re-measure, and the replacements have just changed the text it counts.
    Exactly what docx_proposal_service does after its own fill."""
    refreshed = []
    monkeypatch.setattr(fs.ix, "detect_bytes", lambda _b: "static")
    monkeypatch.setattr(fs.ix, "refresh_static",
                        lambda b: refreshed.append(len(b)) or b)
    await _built(client, org_a["admin_token"], "F3TOC", "Orchid F3J")
    assert refreshed, "a static contents page was not re-measured"


# --- THE PROPERTIES (plan amendment K) ----------------------------------------


async def test_the_built_mou_names_its_client_in_its_properties(
    client, org_a, no_pdf
):
    """The defect the owner found by opening the file, which no green suite
    had caught: they asked "why haven't you changed the school name?" and it
    was in dc:title, where Word shows it in its title bar, in File > Info and
    in Explorer's preview pane."""
    ctx, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3PROP", "Orchid F3K")
    built = storage.read_bytes(ctx.org_id, mou.docx_path)
    core = Document(io.BytesIO(built)).core_properties

    assert core.title == "Orchid F3K"
    assert core.subject == "MOU fill F3PROP"
    assert core.author == "", "the school's own signatory was left as the author"
    assert core.category == "" and core.keywords == ""


async def test_no_property_of_a_built_mou_still_reads_like_a_tag(
    client, org_a, no_pdf
):
    """COUNTED OVER THE WHOLE PACKAGE, not the paragraph walk. Counting over
    the walk is exactly what let the original defect through."""
    from app.services.docx import properties as props

    ctx, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3PRO2", "Orchid F3L")
    built = storage.read_bytes(ctx.org_id, mou.docx_path)
    assert props.tag_like(built) == []


async def test_a_property_holding_a_literal_answered_differently_per_row_is_blank(
    client, org_a, no_pdf
):
    """`<ask:Yes>` is answered "Yes" for one deliverable and "No" for the
    other -- F1's whole reason for keying on (raw, context). A property
    carries the literal alone, so there is nothing to choose between them and
    an arbitrary choice would be worse than none."""
    from app.services.docx import properties as props

    docx_bytes = _mou_docx()
    ctx, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3PRO3", "Orchid F3M",
        docx_bytes=docx_bytes)
    built = storage.read_bytes(ctx.org_id, mou.docx_path)
    core = Document(io.BytesIO(built)).core_properties

    assert core.content_status == "Innovation Nexus", (
        "a literal the fill agreed on should still reach its property")
    assert core.comments in (None, ""), (
        "<ask:Yes> is answered Yes for one deliverable and No for the other, "
        "so there is nothing to choose between them")
    assert props.tag_like(built) == []


async def test_a_proposal_build_leaves_its_properties_exactly_as_they_were(
    client, org_a, no_pdf
):
    """MOUs only, and this is the guard on that.

    A proposal template's properties were never neutralised, so there is no
    tag text in them to fill -- and writing the client into them anyway would
    be a change to a flow §10 says this project does not change. The proposal
    flow has the same latent defect if a template ever DOES carry a client in
    its properties; that is reported to the owner rather than fixed here,
    because the fix is a change to their proposals.
    """
    from app.ai import docx_tagfill as tf
    from app.services.docx import tags as dtags
    from tests.docx.test_fill_service import _tagged_docx

    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _proposal, _mou = await _both_templates(client, token, "F3NOPR")
    lead_id = await _lead(client, token, "Orchid F3N")

    layer = _AnswerEverything(
        [o.as_dict() for o in dtags.scan(_tagged_docx())], {})
    monkey = tf.get_model_layer
    tf.get_model_layer = lambda: layer
    try:
        async with SessionLocal() as db:
            session = await fs.open_session(
                db, ctx, lead_id=lead_id, program_id=program_id,
                document_type="proposal")
            session = await fs.apply_answers(db, ctx, session, "two of each")
            await fs.mark_ready(db, session)
            proposal = await fs.build(db, ctx, session)
    finally:
        tf.get_model_layer = monkey

    built = storage.read_bytes(ctx.org_id, proposal.docx_path)
    core = Document(io.BytesIO(built)).core_properties
    assert core.title in (None, ""), (
        "the proposal flow's output gained a title it never had before")
    assert core.subject in (None, "")


def _with_core_of(docx_bytes: bytes, other: bytes) -> bytes:
    """`docx_bytes`, but carrying `other`'s core properties.

    What a real LibreOffice re-measure does to a package, in miniature: it
    rewrites the whole thing, so anything written into the properties before
    it is gone afterwards.
    """
    import zipfile

    from app.services.docx import properties as props

    core = zipfile.ZipFile(io.BytesIO(other)).read(props.CORE)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zin,             zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, core if item.filename == props.CORE
                          else zin.read(item.filename))
    return out.getvalue()


async def test_the_properties_are_written_after_the_contents_page_is_remeasured(
    client, org_a, no_pdf, monkeypatch
):
    """The order is not cosmetic, and nothing else in this suite can show it.

    `refresh_static` shells out to LibreOffice, which rewrites the WHOLE
    package -- so properties written BEFORE it are written into bytes that are
    about to be thrown away, and the built contract ships "<School Name>"
    again. No test can run a real LibreOffice, so the re-measure is stubbed
    with one that does the part that matters: it hands back the template's own
    core properties.
    """
    from app.services.docx import properties as props

    template_bytes = _mou_docx()
    monkeypatch.setattr(fs.ix, "detect_bytes", lambda _b: "static")
    monkeypatch.setattr(fs.ix, "refresh_static",
                        lambda b: _with_core_of(b, template_bytes))

    ctx, _s, mou, _l, _p = await _built(
        client, org_a["admin_token"], "F3ORDER", "Orchid F3U",
        docx_bytes=template_bytes)

    built = storage.read_bytes(ctx.org_id, mou.docx_path)
    assert props.tag_like(built) == [], (
        "the re-measure handed back the template's properties and nothing "
        "wrote them again")
    assert Document(io.BytesIO(built)).core_properties.title == "Orchid F3U"


# --- correcting a contract ----------------------------------------------------


async def _corrected(client, token, code, name, new_value, *, monkeypatch=None):
    """Build an MOU, then change one value through the real correction path."""
    from app.ai import docx_tagfill as tf

    ctx, session, mou, lead_id, program_id = await _built(
        client, token, code, name)

    async def _revise(_ctx, *, dossier, resolutions, correction):
        target = next(r for r in resolutions
                      if r["raw"] == "<School Signatory>")
        return [{"tag_id": target["tag_id"], "value": new_value,
                 "confidence": 1.0, "reason": "the person corrected it",
                 "citation": "the correction"}]

    monkey = tf.revise
    tf.revise = _revise
    try:
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.reopen_for_correction(
                db, ctx, session, "the signatory is " + new_value)
            await fs.mark_ready(db, session)
            rebuilt = await fs.build(db, ctx, session)
    finally:
        tf.revise = monkey
    return ctx, session, mou, rebuilt, lead_id


async def test_correcting_a_built_mou_rewrites_the_same_row(
    client, org_a, no_pdf
):
    """The same row, so the id the salesperson is already holding keeps
    working -- and one contract, not two."""
    ctx, _s, first, rebuilt, lead_id = await _corrected(
        client, org_a["admin_token"], "F3FIX", "Orchid F3O", "Dr A Rao")

    assert rebuilt.id == first.id
    assert await _count(MouDocument, lead_id=lead_id) == 1
    assert "Dr A Rao" in rebuilt.content_md
    built = storage.read_bytes(ctx.org_id, rebuilt.docx_path)
    assert any("Dr A Rao" in p.text
               for p in Document(io.BytesIO(built)).paragraphs)


async def test_a_correction_writes_the_file_anew_rather_than_over_it(
    client, org_a, no_pdf
):
    """Someone may already have downloaded the old one, and a path that
    quietly changes underneath a reader is worse than a second file."""
    _c, _s, first, rebuilt, _l = await _corrected(
        client, org_a["admin_token"], "F3ANEW", "Orchid F3P", "Dr A Rao")
    assert rebuilt.docx_path != first.docx_path


async def test_a_correction_keeps_what_the_mou_used_to_say(
    client, org_a, no_pdf
):
    """The file has been written anew by now, so this record is the only place
    the superseded wording survives."""
    _c, _s, _f, rebuilt, _l = await _corrected(
        client, org_a["admin_token"], "F3HIST", "Orchid F3Q", "Dr A Rao")

    async with SessionLocal() as db:
        revisions = (await db.execute(
            select(MouRevision).where(MouRevision.mou_id == rebuilt.id)
            .order_by(MouRevision.revision_no))).scalars().all()

    assert [r.revision_no for r in revisions] == [1, 2]
    assert "Smt. R Kulkarni" in revisions[0].content_md
    assert "Dr A Rao" not in revisions[0].content_md
    assert "Dr A Rao" in revisions[1].content_md
    assert "the signatory is Dr A Rao" in (revisions[1].instruction or "")


async def test_a_failed_reconversion_leaves_no_stale_pdf(
    client, org_a, monkeypatch
):
    """`pdf_path` is cleared BEFORE the converter runs, so a rebuild that
    fails leaves no PDF at all rather than yesterday's PDF -- the one made
    before the correction -- sitting beside today's document."""
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-ok")
    ctx, session, mou, lead_id, _p = await _built(
        client, org_a["admin_token"], "F3STALE", "Orchid F3R")
    stale = mou.pdf_path
    assert stale

    from app.ai import docx_tagfill as tf

    async def _revise(_ctx, *, dossier, resolutions, correction):
        target = next(r for r in resolutions if r["raw"] == "<School Signatory>")
        return [{"tag_id": target["tag_id"], "value": "Dr A Rao",
                 "confidence": 1.0, "reason": "corrected", "citation": "c"}]

    def _broken(*args, **kwargs):
        raise RuntimeError("soffice is not installed")

    monkey = tf.revise
    tf.revise = _revise
    monkeypatch.setattr(fs.convert, "docx_to_pdf", _broken)
    try:
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.reopen_for_correction(
                db, ctx, session, "the signatory is Dr A Rao")
            await fs.mark_ready(db, session)
            rebuilt = await fs.build(db, ctx, session)
    finally:
        tf.revise = monkey

    assert rebuilt.pdf_path is None, (
        "the PDF from before the correction survived a failed rebuild")


async def _refuse_once_sent(client, org_a, code, name, **gone):
    """Put an MOU into a "the client has it" state and try to correct it."""
    ctx, session, mou, _l, _p = await _built(
        client, org_a["admin_token"], code, name)
    async with SessionLocal() as db:
        row = await db.get(MouDocument, mou.id)
        for field, value in gone.items():
            setattr(row, field, value)
        await db.commit()

        session = await db.get(ProposalFillSession, session.id)
        with pytest.raises(ValidationFailedError) as err:
            await fs.reopen_for_correction(db, ctx, session, "change the date")
    return str(err.value)


async def test_a_sent_mou_is_not_rewritten(client, org_a, no_pdf):
    """Once it is sent the client is holding the contract, and rewriting the
    file behind that would leave our record disagreeing with what they were
    sent. An amendment is a new MOU, not a quiet edit of the old one.

    THE STATUS ALONE, with no `sent_at`. Setting both -- which this test did
    at first -- proves neither: deleting the status check survived, because
    the timestamp still refused it.
    """
    message = await _refuse_once_sent(client, org_a, "F3SENT", "Orchid F3S",
                                      status=MouStatus.SENT)
    assert "already been sent" in message


async def test_an_mou_whose_send_was_only_timestamped_is_not_rewritten(
    client, org_a, no_pdf
):
    """THE TIMESTAMP ALONE. A send that recorded when it went and then failed
    to move the status still means the client is holding the document, and
    the half that is set is the half that must be believed."""
    message = await _refuse_once_sent(client, org_a, "F3SEN2", "Orchid F3S2",
                                      sent_at=utcnow())
    assert "already been sent" in message


async def test_there_is_nothing_to_correct_before_an_mou_is_built(
    client, org_a, no_pdf
):
    ctx, session, _p, _l, _t = await _answered_mou(
        client, org_a["admin_token"], "F3NONE", "Orchid F3T")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        with pytest.raises(ValidationFailedError) as err:
            await fs.reopen_for_correction(db, ctx, session, "change it")
    assert "MOU" in str(err.value)


# --- would this programme's contract be filled by the assistant? --------------


async def test_is_mou_flow_sees_a_current_mou_template(client, org_a):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id, _p, _m = await _both_templates(client, token, "F3FLOW")
    async with SessionLocal() as db:
        assert await fs.is_mou_flow(db, ctx, program_id) is True
        assert await fs.is_simple_flow(db, ctx, program_id) is True


async def test_is_mou_flow_is_false_when_only_a_proposal_template_exists(
    client, org_a
):
    """False rather than raising: the ordinary path has its own "ask your Org
    Admin to add one", and this must not replace a message that is already
    right."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    program_id = await _program(client, token, "F3FLOX")
    await _upload(client, token, program_id, name="p", document_type="proposal")
    async with SessionLocal() as db:
        assert await fs.is_mou_flow(db, ctx, program_id) is False
        assert await fs.is_simple_flow(db, ctx, program_id) is True
