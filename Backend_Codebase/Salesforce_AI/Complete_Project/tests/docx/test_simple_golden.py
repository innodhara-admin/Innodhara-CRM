# tests/docx/test_simple_golden.py
"""The simple flow, end to end, over a real branded proposal (Task J3).

Opt-in like `test_golden_samples.py`: `data/samples/` is 27 MB of the
organisation's own material and is not in git, so every test here skips on a
clean checkout and runs on the VM, where it is the real proof.

The fixture is `School_YuviPep 360_2 1 (tagged).docx` -- the second real
document, tagged the way its author would tag it. Everything it exercises that
the synthetic fixtures cannot: eighteen tables, twenty-three sections,
thirty-three images, and a placeholder that appears NINE times, six of them in
the footers of three different sections.

The model is scripted. What is real is the document, the scan, the writer, the
status machine and the PDF.
"""
import io
from pathlib import Path

import pytest
from docx import Document
from sqlalchemy import select

from app.ai import docx_tagfill
from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.program import ProposalTemplate, ProposalTemplateDoc
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services import storage
from app.services.docx import convert
from app.services.docx import tags as docx_tags
from tests.conftest import auth
from tests.docx.test_text import raw_count

API = "/api/v1"
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
TAGGED = SAMPLES_DIR / "School_YuviPep 360_2 1 (tagged).docx"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not TAGGED.exists(),
                       reason="data/samples/ not present"),
]

#: Measured against the tagged document on 2026-09-08. Sixteen occurrences of
#: eight distinct literals: `<School Name>` nine times, and seven single tags
#: in the pricing and deliverables tables.
EXPECTED_OCCURRENCES = 16
EXPECTED_DISTINCT = 8
EXPECTED_BY_KIND = {"semantic": 9, "ask": 6, "ask_calculate": 1}

#: The untagged original's shape, from test_golden_samples.EXPECTED_SHAPE.
#: Tagging replaces text in place and inserts nothing, so the tagged document
#: has to match it exactly -- and so does the document built from it.
EXPECTED_SECTIONS = 23
EXPECTED_MEDIA = 33
EXPECTED_TABLES = 18

#: What the salesperson answers. Keyed by the tag's literal, because a tag_id
#: is a hash of a position and would make this table unreadable.
ANSWERS = {
    "<School Name>": "Orchid International School",
    "<ask:Nexus>": "Nexus",
    "<ask:1 Set>": "2 Sets",
    "<ask_calculate:Rs. 2500/- net>": "Rs. 2,200/- net per student, all inclusive",
    "<ask:10 months>": "10 months",
    "<ask:Weekly once>": "Twice weekly",
    "<ask:2700>": "1,850",
    "<ask:1 to 10>": "1 to 8",
}


class FillLayer:
    """Answers whatever it is asked, from ANSWERS, by reading the prompt."""

    def __init__(self, occurrences, *, confident=()):
        self.occurrences = occurrences
        self.confident = set(confident)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["messages"][-1]["content"]
        out = []
        for occurrence in self.occurrences:
            if occurrence["tag_id"] not in prompt:
                continue
            answer = ANSWERS[occurrence["raw"]]
            item = {"tag_id": occurrence["tag_id"], "value": answer,
                    "reason": "scripted"}
            if occurrence["raw"] in self.confident:
                item["confidence"] = 0.97
                item["citation"] = "client.name"
            out.append(item)
        return {"resolutions": out}


async def _ctx(client, token) -> OrgContext:
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                      role=me["role"], email=me["email"])


async def _ground(client, token, code):
    """Upload the tagged document as a simple-flow template, with a rate card.

    `code` is per-test: `client` and `org_a` are session-scoped, so one
    programme code shared by three tests makes the second and third upload
    into a conflict -- and the failure surfaces as a KeyError on the
    response body rather than as anything about programmes.
    """
    resp = await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"YuviPep 360 {code}", "code": code,
              "description": "d"},
    )
    assert resp.status_code == 200, resp.text[:300]
    program = resp.json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "YuviPep 360 tagged", "make_current": "true",
              "flow": "simple"},
        files={"file": (TAGGED.name, TAGGED.read_bytes(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text[:400]
    assert (await client.post(
        f"{API}/admin/programs/{program['id']}/pricing", headers=auth(token),
        json={"currency": "INR", "make_current": True,
              "items": [{"code": "IBC", "label": "Innovation Base Course",
                         "unit": "student", "unit_price": 2500,
                         "default_quantity": 1850}]},
    )).status_code == 200
    # The filled document names this school, so every test uses the same one.
    from tests.conftest import lead_named

    lead_id = (await lead_named(client, token, "Orchid International School"))["id"]
    return program["id"], resp.json(), lead_id


async def _plan_tags(program_id):
    async with SessionLocal() as db:
        template = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.program_id == program_id,
            ProposalTemplate.is_current.is_(True)))).scalars().first()
        row = (await db.execute(select(ProposalTemplateDoc).where(
            ProposalTemplateDoc.template_id == template.id))).scalar_one()
    return (row.plan_json or {}).get("tags") or []


# --- the fixture itself ------------------------------------------------------


async def test_the_tagged_document_is_the_original_with_tags_in_it():
    """Tagging replaced text in place. If it had inserted or dropped anything,
    every assertion about the BUILT document's shape would be measuring the
    wrong baseline."""
    original = SAMPLES_DIR / "School_YuviPep 360_2 1.docx"
    if not original.exists():
        pytest.skip("the untagged original is not present")
    tagged = Document(io.BytesIO(TAGGED.read_bytes()))
    plain = Document(io.BytesIO(original.read_bytes()))

    assert len(tagged.sections) == len(plain.sections) == EXPECTED_SECTIONS
    assert (len(tagged.part.package.image_parts)
            == len(plain.part.package.image_parts) == EXPECTED_MEDIA)
    assert len(tagged.tables) == len(plain.tables) == EXPECTED_TABLES
    # The placeholder the untagged document carries is gone from the tagged one
    # -- all nine of them, not the three a reader of the body would find.
    assert raw_count(original.read_bytes(), "School School") == 9
    assert raw_count(TAGGED.read_bytes(), "School School") == 0


async def test_the_scan_finds_every_tag_the_author_wrote():
    occurrences = docx_tags.scan(TAGGED.read_bytes())
    by_kind = {}
    for occurrence in occurrences:
        by_kind[occurrence.kind] = by_kind.get(occurrence.kind, 0) + 1

    assert len(occurrences) == EXPECTED_OCCURRENCES
    assert len({o.raw for o in occurrences}) == EXPECTED_DISTINCT
    assert by_kind == EXPECTED_BY_KIND
    # D1: one literal, nine places, nine identities. `replace_token` would have
    # written one answer into all nine; that is why nothing here works on
    # literals.
    school = [o for o in occurrences if o.raw == "<School Name>"]
    assert len(school) == 9
    assert len({o.tag_id for o in school}) == 9
    assert len({o.tag_id for o in occurrences}) == EXPECTED_OCCURRENCES
    # D9: the row label is what tells the pricing tags apart.
    contexts = {o.raw: o.context for o in occurrences if o.raw != "<School Name>"}
    assert contexts["<ask:2700>"] == "Number of Students"
    assert contexts["<ask:1 to 10>"] == "Grades"
    assert contexts["<ask_calculate:Rs. 2500/- net>"] == "Innovation Nexus"


# --- the whole flow ----------------------------------------------------------


async def test_the_upload_summarises_the_document_without_an_editor(
        client, org_a):
    _, body, _ = await _ground(client, org_a["admin_token"], "Y360UP")

    assert body["kind"] == "docx_simple"
    assert body["flow"] == "simple"
    summary = body.get("plan_summary") or body
    assert summary["tags"] == EXPECTED_OCCURRENCES
    # D4: every `ask` and `ask_calculate` is asked whatever the model thinks.
    assert summary["always_asked"] == 7
    assert len(summary["distinct"]) == EXPECTED_DISTINCT


async def test_a_whole_proposal_is_filled_from_a_scripted_conversation(
        client, org_a, monkeypatch):
    """Upload, resolve, answer, review, approve, build -- over the real
    document, and then every claim the plan makes about the result."""
    token = org_a["admin_token"]
    program_id, _, lead_id = await _ground(client, token, "Y360FL")
    ctx = await _ctx(client, token)
    tags = await _plan_tags(program_id)
    assert len(tags) == EXPECTED_OCCURRENCES

    # The model is confident about the client's name and about nothing else,
    # so the nine `<School Name>` fill silently and the seven others are asked.
    layer = FillLayer(tags, confident={"<School Name>"})
    monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: layer)

    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-golden")
    assert session.status == FillStatus.ASKING
    open_now = fs.open_questions(session, limit=None)
    assert len(open_now) == 7
    assert {t["raw"] for t in open_now} == {
        "<ask:Nexus>", "<ask:1 Set>", "<ask_calculate:Rs. 2500/- net>",
        "<ask:10 months>", "<ask:Weekly once>", "<ask:2700>", "<ask:1 to 10>"}
    # D5: seven questions is two rounds, not seven round trips.
    assert len(fs.open_questions(session)) == fs.QUESTIONS_PER_ROUND

    rounds = 0
    while fs.open_questions(session, limit=None):
        rounds += 1
        assert rounds <= 4, "a seven-tag fill should not take four rounds"
        async with SessionLocal() as db:
            session = await db.get(ProposalFillSession, session.id)
            session = await fs.apply_answers(db, ctx, session, "as discussed")

    assert session.status == FillStatus.REVIEWING
    assert rounds == 1               # one reply settled every outstanding one

    # D13: the review lists all sixteen, the nine nobody was asked about too.
    lines = fs.review_lines(session)
    assert len(lines) == EXPECTED_OCCURRENCES
    assert sum(1 for line in lines if line["source"] == "ai") == 9
    assert sum(1 for line in lines if line["source"] == "user") == 7
    assert all(line["reviewed"] is False for line in lines)

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    # --- the document ---------------------------------------------------
    built = storage.read_bytes(ctx.org_id, proposal.docx_path)
    assert docx_tags.scan(built) == [], "a tag survived into the proposal"
    assert raw_count(built, "School School") == 0

    document = Document(io.BytesIO(built))
    assert len(document.sections) == EXPECTED_SECTIONS
    assert len(document.part.package.image_parts) == EXPECTED_MEDIA
    assert len(document.tables) == EXPECTED_TABLES

    text = fs._document_text(built)
    assert text.count("Orchid International School") == 9
    assert "Rs. 2,200/- net per student, all inclusive" in text
    assert "Twice weekly" in text
    assert "1,850" in text
    assert "1 to 8" in text
    assert "2700" not in text             # the author's default was replaced

    # --- the record -----------------------------------------------------
    assert proposal.template_kind == "docx_simple"
    assert len(proposal.filled_json) == EXPECTED_OCCURRENCES
    sources = {}
    for row in proposal.filled_json:
        sources[row["source"]] = sources.get(row["source"], 0) + 1
    # Two of the seven answers accepted the author's own wording verbatim.
    assert sources["ai"] == 9
    assert sources["user"] == 5
    assert sources["default"] == 2
    assert all(row["computed_by"] is None for row in proposal.filled_json)
    # The rate card is recorded but not claimed (owner, 8 September): its
    # figures describe nothing on this page, because the document's price
    # table is filled by tags only.
    assert proposal.pricing_version
    assert proposal.total_amount == 0.0
    assert proposal.line_items == []

    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
    assert session.status == FillStatus.BUILT
    assert session.proposal_id == proposal.id


async def test_the_filled_document_converts_to_a_pdf(client, org_a, monkeypatch):
    """The last thing that happens to a real proposal, over the real document
    and the real LibreOffice."""
    token = org_a["admin_token"]
    program_id, _, lead_id = await _ground(client, token, "Y360PD")
    ctx = await _ctx(client, token)
    tags = await _plan_tags(program_id)
    monkeypatch.setattr(docx_tagfill, "get_model_layer",
                        lambda: FillLayer(tags))

    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-golden-pdf")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.apply_answers(db, ctx, session, "as discussed")
        session = await fs.mark_ready(db, session)
        proposal = await fs.build(db, ctx, session)

    assert proposal.pdf_path, "the build produced no PDF"
    pdf = storage.read_bytes(ctx.org_id, proposal.pdf_path)
    assert pdf[:5] == b"%PDF-"

    from pypdf import PdfReader
    read = "".join(p.extract_text() or ""
                   for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Orchid International School" in read
    assert "School School" not in read
    assert convert.docx_to_pdf(storage.read_bytes(
        ctx.org_id, proposal.docx_path))[:5] == b"%PDF-"
