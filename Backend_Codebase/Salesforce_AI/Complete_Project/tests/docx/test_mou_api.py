# tests/docx/test_mou_api.py
"""Reading a built MOU back (Task R1).

Two routes and one key, and the key is the point. A built MOU appears on the
client screen under **its own** `mous` key, NEVER inside the lead's
`proposals` list -- which is D-A arriving at the API boundary. Merging them
would put a signed contract in front of every reader of the sales pipeline,
and `inbound_engine` reads a sent proposal as "the deal is agreed".

The commercial fields are absent here for the same reason they are absent from
the model: `MouDocument` has no `total_amount` and no `line_items`, so a
screen that sums a client's documents cannot pick a contract up by accident.
"""
import io

import pytest
from docx import Document
from sqlalchemy import select

from app.ai import docx_tagfill
from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.mou import MouDocument, MouStatus
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from app.services.docx import tags as dtags
from tests.conftest import auth

API = "/api/v1"


def _mou_docx() -> bytes:
    doc = Document()
    doc.add_heading("Memorandum of Understanding", level=1)
    doc.add_paragraph(
        "Between <School Name> and YuviPep, a body paragraph long enough to "
        "serve as a style reference.")
    doc.add_paragraph("Signed for the school by <ask:Smt. Y S Ghorpade>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _proposal_docx() -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    doc.add_paragraph("Quantity <ask:1 Unit>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


ANSWERS = {
    "<School Name>": "Orchid International School",
    "<ask:Smt. Y S Ghorpade>": "Dr Anitha Rao",
    "<ask:1 Unit>": "2 Units",
}


class FillLayer:
    def __init__(self, tags):
        self.tags = tags

    async def generate_json(self, **kwargs):
        if "ARITHMETICALLY RELATED" in kwargs["messages"][-1]["content"]:
            return {"relations": []}
        return {"resolutions": [
            {"tag_id": t["tag_id"], "value": ANSWERS[t["raw"]],
             "confidence": 1.0, "citation": "turn 1", "reason": "said so"}
            for t in self.tags if t["raw"] in ANSWERS]}


@pytest.fixture
def no_pdf(monkeypatch):
    monkeypatch.setattr(fs.convert, "docx_to_pdf", lambda *a, **k: b"%PDF-stub")


async def _ctx(client, token) -> OrgContext:
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                      role=me["role"], email=me["email"])


async def _upload(client, token, program_id, data, document_type):
    resp = await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data={"name": document_type, "make_current": "true", "flow": "simple",
              "document_type": document_type},
        files={"file": ("t.docx", data,
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _built(client, token, code, name, monkeypatch, *,
                 with_proposal=False):
    """A built MOU, and optionally an ordinary proposal for the same client."""
    ctx = await _ctx(client, token)
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"MOU api {code}", "code": code,
              "description": "d"})).json()
    program_id = program["id"]
    await _upload(client, token, program_id, _mou_docx(), "mou")
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": name})).json()["id"]

    monkeypatch.setattr(docx_tagfill, "get_model_layer",
                        lambda: FillLayer([o.as_dict()
                                           for o in dtags.scan(_mou_docx())]))
    async with SessionLocal() as db:
        session = await fs.open_session(
            db, ctx, lead_id=lead_id, program_id=program_id,
            chat_session_id=f"chat-{code}".lower(), document_type="mou")
        session = await fs.apply_answers(db, ctx, session, "as agreed")
        assert session.status == FillStatus.REVIEWING
        await fs.mark_ready(db, session)
        mou = await fs.build(db, ctx, session)

    proposal_id = None
    if with_proposal:
        await _upload(client, token, program_id, _proposal_docx(), "proposal")
        monkeypatch.setattr(
            docx_tagfill, "get_model_layer",
            lambda: FillLayer([o.as_dict()
                               for o in dtags.scan(_proposal_docx())]))
        async with SessionLocal() as db:
            other = await fs.open_session(
                db, ctx, lead_id=lead_id, program_id=program_id,
                chat_session_id=f"chat-{code}-p".lower(),
                document_type="proposal")
            other = await fs.apply_answers(db, ctx, other, "two of each")
            await fs.mark_ready(db, other)
            proposal_id = (await fs.build(db, ctx, other)).id

    return {"ctx": ctx, "mou": mou, "lead_id": lead_id,
            "program_id": program_id, "proposal_id": proposal_id}


# --- GET /mous/{id} -----------------------------------------------------------


async def test_get_mou_returns_its_provenance_and_both_files(
    client, org_a, no_pdf, monkeypatch
):
    token = org_a["admin_token"]
    made = await _built(client, token, "RAPI1", "Orchid R1", monkeypatch)

    body = (await client.get(f"{API}/mous/{made['mou'].id}",
                             headers=auth(token))).json()

    assert body["id"] == made["mou"].id
    assert body["lead_id"] == made["lead_id"]
    assert body["program_id"] == made["program_id"]
    assert body["status"] == MouStatus.DRAFT
    assert body["title"] == made["mou"].title
    assert body["content_md"]
    assert body["has_docx"] is True and body["has_pdf"] is True
    # The provenance the Android card reads, with the app's eight keys.
    assert body["filled"], "the card would be blank"
    for entry in body["filled"]:
        assert set(entry) == {"key", "kind", "source", "text", "brief",
                              "anchor", "computed_by", "citation"}
    assert any(e["text"] == "Orchid International School"
               for e in body["filled"])


async def test_the_route_carries_no_commercial_fields(
    client, org_a, no_pdf, monkeypatch
):
    """D-A at the API boundary. A screen that sums a client's documents must
    not be able to pick a contract up, and the surest way is for the number
    never to be in the payload."""
    token = org_a["admin_token"]
    made = await _built(client, token, "RAPI2", "Orchid R2", monkeypatch)
    body = (await client.get(f"{API}/mous/{made['mou'].id}",
                             headers=auth(token))).json()

    for absent in ("total_amount", "line_items", "currency",
                   "pricing_version", "project_id"):
        assert absent not in body, absent


async def test_the_revisions_are_listed_newest_first(
    client, org_a, no_pdf, monkeypatch
):
    """Revision 1 is the contract as first built. What it said before the Nth
    correction is revision N, and once the file has been written anew this is
    the only place that survives.

    TWO revisions, because with one the order cannot be wrong: sorting
    ascending instead of descending passed every assertion this test made at
    first, which is a test that pins nothing.
    """
    token = org_a["admin_token"]
    made = await _built(client, token, "RAPI3", "Orchid R3", monkeypatch)

    async def _revise(_ctx, *, dossier, resolutions, correction):
        target = next(r for r in resolutions
                      if r["raw"] == "<ask:Smt. Y S Ghorpade>")
        return [{"tag_id": target["tag_id"], "value": "Dr B Iyer",
                 "confidence": 1.0, "reason": "corrected", "citation": "c"}]

    monkeypatch.setattr(docx_tagfill, "revise", _revise)
    async with SessionLocal() as db:
        session = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.mou_id == made["mou"].id))).scalars().first()
        session = await fs.reopen_for_correction(
            db, made["ctx"], session, "the signatory is Dr B Iyer")
        await fs.mark_ready(db, session)
        await fs.build(db, made["ctx"], session)

    body = (await client.get(f"{API}/mous/{made['mou'].id}",
                             headers=auth(token))).json()

    assert [r["revision_no"] for r in body["revisions"]] == [2, 1], (
        "the newest revision is not first")
    assert "Dr B Iyer" in body["revisions"][0]["instruction"]
    assert all(r["edited_at"] for r in body["revisions"])
    # Still ONE contract, at the id the salesperson already holds.
    assert body["id"] == made["mou"].id


async def test_a_missing_mou_is_a_404(client, org_a):
    resp = await client.get(f"{API}/mous/{'0' * 32}",
                            headers=auth(org_a["admin_token"]))
    assert resp.status_code == 404


async def test_another_organisations_mou_is_not_found(
    client, org_a, org_b, no_pdf, monkeypatch
):
    """Not 403 -- 404. Confirming that an id exists is itself a leak."""
    made = await _built(client, org_a["admin_token"], "RAPI4", "Orchid R4",
                        monkeypatch)
    resp = await client.get(f"{API}/mous/{made['mou'].id}",
                            headers=auth(org_b["admin_token"]))
    assert resp.status_code == 404


# --- the lead's own key -------------------------------------------------------


async def test_a_built_mou_appears_under_its_own_key_on_the_lead(
    client, org_a, no_pdf, monkeypatch
):
    token = org_a["admin_token"]
    made = await _built(client, token, "RAPI5", "Orchid R5", monkeypatch)

    body = (await client.get(f"{API}/leads/{made['lead_id']}",
                             headers=auth(token))).json()

    assert "mous" in body, "the client screen has nowhere to show a contract"
    assert [m["id"] for m in body["mous"]] == [made["mou"].id]
    entry = body["mous"][0]
    assert entry["title"] == made["mou"].title
    assert entry["status"] == MouStatus.DRAFT


async def test_an_mou_NEVER_appears_in_the_leads_proposals_list(
    client, org_a, no_pdf, monkeypatch
):
    """THE test this task exists for.

    The lead here has BOTH a contract and an ordinary proposal, so the lists
    cannot pass by being empty. Merging them would put a signed contract in
    the sales pipeline, where `inbound_engine` reads a sent proposal as "the
    deal is agreed" -- which is the whole of D-A.
    """
    token = org_a["admin_token"]
    made = await _built(client, token, "RAPI6", "Orchid R6", monkeypatch,
                        with_proposal=True)
    assert made["proposal_id"], "the fixture proves nothing without both"

    body = (await client.get(f"{API}/leads/{made['lead_id']}",
                             headers=auth(token))).json()

    proposal_ids = [p["id"] for p in body["proposals"]]
    mou_ids = [m["id"] for m in body["mous"]]
    assert proposal_ids == [made["proposal_id"]]
    assert mou_ids == [made["mou"].id]
    assert made["mou"].id not in proposal_ids, (
        "a contract is listed among the proposals")
    assert made["proposal_id"] not in mou_ids


async def test_a_lead_with_no_contract_carries_an_empty_key(client, org_a):
    """Present and empty, not absent: a client screen that has to test for
    the key's existence will one day forget to."""
    token = org_a["admin_token"]
    lead_id = (await client.post(f"{API}/leads", headers=auth(token),
                                 json={"name": "Orchid R7"})).json()["id"]
    body = (await client.get(f"{API}/leads/{lead_id}",
                             headers=auth(token))).json()
    assert body["mous"] == []


async def test_another_organisations_lead_shows_no_mous(
    client, org_a, org_b, no_pdf, monkeypatch
):
    made = await _built(client, org_a["admin_token"], "RAPI8", "Orchid R8",
                        monkeypatch)
    resp = await client.get(f"{API}/leads/{made['lead_id']}",
                            headers=auth(org_b["admin_token"]))
    assert resp.status_code == 404


# --- the document itself ------------------------------------------------------


async def test_the_contract_can_be_downloaded_as_docx_and_pdf(
    client, org_a, no_pdf, monkeypatch
):
    """Without this the client screen can describe a contract it cannot
    open."""
    token = org_a["admin_token"]
    made = await _built(client, token, "RAPI9", "Orchid R9", monkeypatch)

    docx = await client.get(f"{API}/mous/{made['mou'].id}/download?format=docx",
                            headers=auth(token))
    assert docx.status_code == 200
    assert docx.content[:2] == b"PK"
    assert dtags.scan(docx.content) == []

    pdf = await client.get(f"{API}/mous/{made['mou'].id}/download",
                           headers=auth(token))
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"


async def test_another_organisation_cannot_download_the_contract(
    client, org_a, org_b, no_pdf, monkeypatch
):
    made = await _built(client, org_a["admin_token"], "RAPIA", "Orchid RA",
                        monkeypatch)
    resp = await client.get(f"{API}/mous/{made['mou'].id}/download",
                            headers=auth(org_b["admin_token"]))
    assert resp.status_code == 404
