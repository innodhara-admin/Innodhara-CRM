# tests/docx/test_mou_upload.py
"""Uploading an MOU template (U1, D-F).

An MOU is always the simple flow: there is no console editor for a contract
and every value in one is a tag. It gets its own `kind`, `mou_simple`, so that
nothing which branches on kind can confuse a contract with a proposal -- and
so `_simple_template` can refuse to open a proposal fill on an MOU template
even though both are tag-filled Word documents.

D-F is the other half. The MOU carries ruled blanks -- `Date: ___________` --
which `TAG_RE` cannot see, because a tag needs angle brackets. An author who
leaves one gets underscores in front of a client. The upload counts them and
says so, at the one moment somebody can still fix it, and does NOT refuse: a
genuinely hand-signed blank is legitimate.
"""
import io
from pathlib import Path

import pytest
from docx import Document

from app.services.docx_template_service import count_ruled_blanks, plan_summary
from tests.conftest import auth

API = "/api/v1"
pytestmark = pytest.mark.asyncio

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"
MOU = SAMPLES_DIR / "Sandur Education Centre_IBC Nexus and Lab2_MoU.docx"


def _tagged() -> bytes:
    doc = Document()
    doc.add_heading("Memorandum of Understanding", level=1)
    doc.add_paragraph("Between <School Name> and YuviPep, a body paragraph "
                      "long enough to serve as a style reference.")
    doc.add_paragraph("Programme: <ask:Innovation Nexus>")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _blank_in_a_footer() -> bytes:
    """A ruled blank where NOBODY SCROLLING THE BODY WOULD SEE IT.

    The owner's real MOU has both its blanks in the signature table, in the
    body -- so a counter that walked the body alone would pass against the
    real document and still be wrong. 47 of that document's 240 paragraphs
    are in headers and footers. This fixture is what makes the test able to
    fail.
    """
    doc = Document()
    doc.add_paragraph("Signed for <School Name>.")
    doc.add_paragraph("Programme: <ask:Innovation Nexus>")
    doc.sections[0].footer.paragraphs[0].text = "Date: ____________"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def _program(client, token, code) -> str:
    return (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"Up {code}", "code": code, "description": "d"},
    )).json()["id"]


async def _upload(client, token, program_id, *, data=None, document_type="mou",
                  flow="simple", name="t"):
    form = {"name": name, "make_current": "true", "flow": flow}
    if document_type is not None:
        form["document_type"] = document_type
    return await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token), data=form,
        files={"file": ("t.docx", data if data is not None else _tagged(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )


# ── the kind ────────────────────────────────────────────────────────────────
async def test_an_mou_upload_is_stored_as_mou_simple(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPA")
    body = (await _upload(client, token, program_id)).json()
    assert body["kind"] == "mou_simple"
    assert body["document_type"] == "mou"


async def test_a_proposal_upload_is_still_docx_simple(client, org_a):
    """The flow this pipeline copies is untouched."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPB")
    body = (await _upload(client, token, program_id,
                          document_type="proposal")).json()
    assert body["kind"] == "docx_simple"
    assert body["document_type"] == "proposal"


async def test_an_mou_may_not_be_uploaded_as_the_complex_flow(client, org_a):
    """There is no console editor for a contract, and every value in an MOU
    is a tag. Refused before anything is stored."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPC")
    resp = await _upload(client, token, program_id, flow="complex")
    assert resp.status_code == 422
    # B1's rule: a refusal names the CONSEQUENCE and the way forward, not the
    # rule it enforces. Asserting on the word "simple" would pass for a
    # message that only said no.
    assert "filled by the assistant" in resp.text.lower()
    assert "editor" in resp.text.lower()

    listed = await client.get(
        f"{API}/admin/programs/{program_id}/proposal-templates",
        headers=auth(token))
    assert listed.json() == [], "a refused upload left a template behind"


async def test_the_plan_records_which_document_type_it_is(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPD")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]
    plan = (await client.get(f"{API}/admin/proposal-template-docs/{doc_id}",
                             headers=auth(token))).json()["plan"]
    assert plan["flow"] == "simple"
    assert plan["document_type"] == "mou"


# ── D-F, the ruled blanks ───────────────────────────────────────────────────
async def test_ruled_blanks_are_counted_over_the_whole_walk():
    """Counted over headers and footers too, not just the body."""
    assert count_ruled_blanks(_blank_in_a_footer()) == 1
    assert count_ruled_blanks(_tagged()) == 0


@pytest.mark.skipif(not MOU.is_file(), reason="data/samples/ not present")
async def test_the_real_mou_carries_two_ruled_blanks():
    """Measured on the owner's own document: ordinals 85 and 87, both in the
    signature table. One has eleven underscores and the other twelve, which
    is why they are different literals and are tagged separately."""
    assert count_ruled_blanks(MOU.read_bytes()) == 2


async def test_a_ruled_blank_is_reported_but_does_not_refuse(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPE")
    resp = await _upload(client, token, program_id, data=_blank_in_a_footer())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ruled_blanks"] == 1
    assert body["tags"] == 2, "the document was still tagged and stored"


async def test_a_document_with_no_ruled_blanks_reports_zero(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPF")
    body = (await _upload(client, token, program_id)).json()
    assert body["ruled_blanks"] == 0


async def test_plan_summary_reports_ruled_blanks_for_a_simple_plan():
    summary = plan_summary({"flow": "simple", "version": 1, "tags": [],
                            "ruled_blanks": 3})
    assert summary["ruled_blanks"] == 3


async def test_a_template_from_before_this_feature_reports_no_blanks():
    """Every template uploaded before D-F has no `ruled_blanks` key at all."""
    assert plan_summary({"flow": "simple", "version": 1,
                         "tags": []})["ruled_blanks"] == 0
    assert plan_summary({"version": 1, "entries": []})["ruled_blanks"] == 0


# â”€â”€ the two kinds do not substitute for one another â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def test_a_programme_with_only_an_mou_template_cannot_fill_a_proposal(
    client, org_a
):
    """The observable a salesperson would actually meet.

    An MOU template is current for the programme and no proposal template is.
    Asking for a proposal fill must say so plainly rather than quietly opening
    the fill on the contract -- which is what would happen if either the
    document_type filter (M1) or the kind check (U1) were missing.
    """
    from app.core.context import OrgContext
    from app.core.exceptions import NotFoundError
    from app.database import SessionLocal
    from app.services import proposal_fill_service as fs

    token = org_a["admin_token"]
    program_id = await _program(client, token, "UPG")
    await _upload(client, token, program_id, document_type="mou")

    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    ctx = OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                     role=me["role"], email=me["email"])
    async with SessionLocal() as db:
        with pytest.raises(NotFoundError, match="No proposal template"):
            await fs._simple_template(db, ctx, program_id, None,
                                      document_type="proposal")
        # ...while the MOU fill finds it perfectly well.
        template, _, occurrences = await fs._simple_template(
            db, ctx, program_id, None, document_type="mou")
    assert template.kind == "mou_simple"
    assert len(occurrences) == 2
