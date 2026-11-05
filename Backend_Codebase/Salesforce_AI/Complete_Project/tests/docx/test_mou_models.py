# tests/docx/test_mou_models.py
"""A programme carries TWO current templates: one proposal, one MOU (D-B).

`is_current` was current-per-(org, programme). An MOU is a second kind of
document for the same offering, so it has to become
current-per-(org, programme, document_type) -- and `kind` cannot serve as the
discriminator, because `markdown`, `docx` and `docx_simple` are all proposals.

Four call sites decide which template is current, and missing any one of them
is the whole failure mode. There is a test here for each:

  * the retire loop in `docx_template_service`     -- uploading
  * `proposal_service._current_template`           -- building a proposal
  * `proposal_fill_service._current`               -- opening a fill
  * `_promote_predecessor`'s call site in admin.py -- deleting

The first one is not hypothetical. Measured on the live database before this
column existed: IBC carries six template rows with `ibc_proposal_v4` current,
and uploading an MOU for IBC cleared it -- after which `_current_template`
returned None and every "create the IBC proposal" answered "No proposal
template for this program. Ask your Org Admin to add one."
"""
import io

import pytest
from docx import Document
from sqlalchemy import select

from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.mou import MouDocument, MouStatus
from app.models.program import ProposalTemplate
from app.services import proposal_fill_service as fs
from app.services import proposal_service
from tests.conftest import auth

API = "/api/v1"
pytestmark = pytest.mark.asyncio


def _tagged_docx() -> bytes:
    """A tagged document, because the simple flow refuses one with no tags."""
    doc = Document()
    doc.add_heading("Document For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    doc.add_paragraph("Programme: <ask:Innovation Nexus>")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def _ctx(client, token) -> OrgContext:
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                      role=me["role"], email=me["email"])


async def _program(client, token, code) -> str:
    return (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"MOU {code}", "code": code, "description": "d"},
    )).json()["id"]


async def _upload(client, token, program_id, *, name, document_type=None):
    """`document_type` omitted entirely exercises the route's own default."""
    form = {"name": name, "make_current": "true", "flow": "simple"}
    if document_type is not None:
        form["document_type"] = document_type
    return await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token), data=form,
        files={"file": ("t.docx", _tagged_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )


async def _current_flags(client, token, program_id) -> dict[str, bool]:
    listed = await client.get(
        f"{API}/admin/programs/{program_id}/proposal-templates",
        headers=auth(token))
    return {t["id"]: t["is_current"] for t in listed.json()}


# ── the retire loop ─────────────────────────────────────────────────────────
async def test_uploading_an_mou_does_not_retire_the_proposal_template(
    client, org_a
):
    """THE defect this column exists to prevent.

    Before D-B the retire loop cleared every `is_current` row for the
    programme, so uploading an MOU left the offering with no current proposal
    template at all.
    """
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD1")

    proposal = await _upload(client, token, program_id,
                             name="ibc_proposal", document_type="proposal")
    assert proposal.status_code == 200, proposal.text
    mou = await _upload(client, token, program_id,
                        name="ibc_mou", document_type="mou")
    assert mou.status_code == 200, mou.text

    flags = await _current_flags(client, token, program_id)
    assert flags[proposal.json()["id"]] is True, (
        "uploading an MOU retired the proposal template"
    )
    assert flags[mou.json()["id"]] is True, "the MOU is not current either"


async def test_the_upload_route_defaults_to_proposal(client, org_a):
    """No `document_type` field at all -- the route's own default, not a
    value a test happened to pass."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD2")
    body = (await _upload(client, token, program_id, name="p",
                          document_type=None)).json()
    assert body["document_type"] == "proposal"


# ── building a proposal ─────────────────────────────────────────────────────
async def test_a_proposal_is_never_built_from_an_mou_template(client, org_a):
    """Both are current. `_current_template` must still pick the proposal.

    THE MOU IS UPLOADED TWICE ON PURPOSE, so it is version 2. `_current_template`
    orders by `version.desc()` and takes the first row, so with both templates
    at version 1 the ordering is a tie and SQLite returned the proposal anyway
    -- the test passed even with the filter removed, because the wrong code
    never actually produced a wrong answer. At version 2 the MOU genuinely
    wins the ordering, so only the filter can keep it out.
    """
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD3")
    proposal = (await _upload(client, token, program_id, name="p",
                              document_type="proposal")).json()
    await _upload(client, token, program_id, name="m", document_type="mou")
    mou_v2 = (await _upload(client, token, program_id, name="m",
                            document_type="mou")).json()
    assert mou_v2["version"] == 2, "the MOU must outrank the proposal by version"

    ctx = await _ctx(client, token)
    async with SessionLocal() as db:
        chosen = await proposal_service._current_template(
            db, ctx.org_id, program_id, None)
    assert chosen.id == proposal["id"]
    assert chosen.document_type == "proposal"


# ── opening a fill ──────────────────────────────────────────────────────────
async def test_a_fill_opens_on_the_template_of_the_type_it_asked_for(
    client, org_a
):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD4")
    proposal = (await _upload(client, token, program_id, name="p",
                              document_type="proposal")).json()
    mou = (await _upload(client, token, program_id, name="m",
                         document_type="mou")).json()

    ctx = await _ctx(client, token)
    async with SessionLocal() as db:
        for_proposal = await fs._current(db, ctx, program_id, None,
                                         document_type="proposal")
        for_mou = await fs._current(db, ctx, program_id, None,
                                    document_type="mou")
    assert for_proposal.id == proposal["id"]
    assert for_mou.id == mou["id"]


# ── deleting ────────────────────────────────────────────────────────────────
async def test_deleting_the_current_mou_promotes_the_previous_mou(
    client, org_a
):
    """`_promote_predecessor` un-supersedes the highest remaining version.

    Scoped on (org, programme) alone it would promote a PROPOSAL template into
    the MOU's place -- the same confusion as the retire loop, running the
    other way.
    """
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD5")
    proposal = (await _upload(client, token, program_id, name="p",
                              document_type="proposal")).json()
    mou_v1 = (await _upload(client, token, program_id, name="m",
                            document_type="mou")).json()
    mou_v2 = (await _upload(client, token, program_id, name="m",
                            document_type="mou")).json()
    assert mou_v2["version"] == 2

    deleted = await client.delete(
        f"{API}/admin/programs/{program_id}/proposal-templates/{mou_v2['id']}",
        headers=auth(token))
    assert deleted.status_code == 200, deleted.text

    flags = await _current_flags(client, token, program_id)
    assert flags[mou_v1["id"]] is True, "the previous MOU was not promoted"
    assert flags[proposal["id"]] is True, (
        "deleting an MOU disturbed the proposal template"
    )


async def test_a_template_row_written_without_a_document_type_is_a_proposal(
    client, org_a
):
    """The MODEL's own default, exercised by constructing a row directly.

    Going through the upload route cannot test this: the route's own
    `Form("proposal")` always supplies the value, so mutating the column
    default changed nothing and the first version of this test passed either
    way. What the default actually protects is a row written by any other
    path -- and, with `server_default`, the 18 rows the migration back-fills
    on a database that already exists.
    """
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD6")
    ctx = await _ctx(client, token)

    async with SessionLocal() as db:
        row = ProposalTemplate(
            org_id=ctx.org_id, program_id=program_id, name="written directly",
            version=1, kind="markdown", body_md="body", is_current=False,
        )
        db.add(row)
        await db.commit()
        written = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.id == row.id))).scalar_one()
        assert written.document_type == "proposal"


# ── Task M2: the mou_documents table (D-A) ──────────────────────────────────
async def test_create_all_builds_the_mou_table_and_a_row_round_trips(
    client, org_a
):
    """`create_all` builds a missing table at startup, which is what makes a
    new table free where a new column is a migration. Proved by writing a row
    with real foreign key targets and reading it back, not by asking the
    metadata whether it knows about itself."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "MOUD7")
    from tests.conftest import fresh_lead

    lead_id = (await fresh_lead(client, token, "Sandur Education Centre"))["id"]
    template = (await _upload(client, token, program_id, name="m",
                              document_type="mou")).json()
    ctx = await _ctx(client, token)

    async with SessionLocal() as db:
        row = MouDocument(
            org_id=ctx.org_id, lead_id=lead_id, program_id=program_id,
            title="MoU for Innovation Nexus", status=MouStatus.DRAFT,
            template_id=template["id"], template_version=template["version"],
            content_md="Memorandum of Understanding", filled_json=[],
            created_by=ctx.user_id,
        )
        db.add(row)
        await db.commit()
        written = (await db.execute(select(MouDocument).where(
            MouDocument.id == row.id))).scalar_one()

    assert written.title == "MoU for Innovation Nexus"
    assert written.status == "draft"
    assert written.pdf_path is None


async def test_an_mou_carries_no_commercial_fields_at_all():
    """D-A, and the reason it is a separate table.

    `total_amount` and `line_items` are ABSENT rather than merely unused, so
    that no aggregate written later can pick an MOU up by accident. The last
    session shipped "Total amount: 2200" into a chat about a document reading
    Rs. 15,00,000, because the rate-card machinery was carried across from the
    complex flow without asking whether its premise came with it. A table with
    no total cannot make that mistake.
    """
    columns = set(MouDocument.__table__.columns.keys())
    for forbidden in ("total_amount", "line_items", "pricing_table_id",
                      "pricing_version", "project_id", "amends_proposal_id"):
        assert forbidden not in columns, (
            f"mou_documents.{forbidden} would let an MOU into the pipeline"
        )


async def test_an_mou_is_wiped_after_the_fills_that_name_it_and_before_proposals():
    """Ordering in WIPE is a constraint, not a preference: the list is deleted
    in order, `proposal_fill_sessions.mou_id` is a foreign key to this table,
    and nothing in this schema declares `ondelete=`. Child before parent is
    the only thing keeping a reset from failing on a constraint."""
    from app.core.reset_taxonomy import WIPE

    assert WIPE.index("proposal_fill_sessions") < WIPE.index("mou_documents")
    assert WIPE.index("mou_documents") < WIPE.index("proposals")


async def test_an_mou_is_transactional_work_and_not_catalogue():
    """A reset that kept a client's contract while wiping the client is
    incoherent. WIPE, never REPLACE or CONFIG."""
    from app.core.reset_taxonomy import CONFIG, KEEP, REPLACE, WIPE

    assert "mou_documents" in WIPE
    assert "mou_documents" not in REPLACE
    assert "mou_documents" not in CONFIG
    assert "mou_documents" not in KEEP
