# tests/docx/test_api.py
"""The docx template routes, driven through the real app like every other API
test in this suite."""
import io

import pytest
from docx import Document

from tests.conftest import auth

API = "/api/v1"


def _docx(client_literal="School Name") -> bytes:
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph(client_literal)
    doc.add_paragraph("A body paragraph long enough to serve as a style reference.")
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "Description"; t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Item"; t.cell(1, 1).text = "Rs 0"
    t.cell(2, 0).text = "Total"; t.cell(2, 1).text = "Rs 0"
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


async def _program(client, token, code="DOCXP") -> str:
    resp = await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": "Docx Program", "code": code, "description": "d"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload(client, token, program_id, *, name="Branded", data=None,
                  filename="branded.docx", flow="complex"):
    """`flow` defaults to complex here because every test that predates the
    simple flow is about the complex one. Pass flow=None to omit the field
    entirely and exercise the route's own default, which is simple."""
    form = {"name": name, "make_current": "true"}
    if flow is not None:
        form["flow"] = flow
    return await client.post(
        f"{API}/admin/programs/{program_id}/proposal-templates/docx",
        headers=auth(token),
        data=form,
        files={"file": (filename, data if data is not None else _docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )


@pytest.mark.asyncio
async def test_upload_creates_a_docx_template_and_its_document(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXA")
    resp = await _upload(client, token, program_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "docx"
    assert body["version"] == 1
    assert body["is_current"] is True
    assert body["index_kind"] == "none"
    assert body["blocks"] > 0
    assert body["doc_id"]

    listed = await client.get(
        f"{API}/admin/programs/{program_id}/proposal-templates", headers=auth(token)
    )
    assert listed.status_code == 200
    assert [t["kind"] for t in listed.json()] == ["docx"]


@pytest.mark.asyncio
async def test_upload_rejects_something_that_is_not_a_docx(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXB")
    resp = await _upload(client, token, program_id,
                         data=b"this is not a document", filename="notes.txt")
    assert resp.status_code == 422
    assert ".docx" in resp.text


@pytest.mark.asyncio
async def test_upload_rejects_a_docx_extension_that_is_not_really_a_docx(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXC")
    resp = await _upload(client, token, program_id,
                         data=b"PK\x03\x04 not really", filename="fake.docx")
    assert resp.status_code == 422
    assert "Word document" in resp.text


@pytest.mark.asyncio
async def test_get_returns_the_outline_plan_and_index_kind(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXD")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]

    resp = await client.get(f"{API}/admin/proposal-template-docs/{doc_id}",
                            headers=auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["index_kind"] == "none"
    assert body["outline"]["blocks"]
    assert body["plan"] == {"version": 1, "entries": []}
    assert "School Name" in [t["literal"] for t in body["outline"]["tokens"]]


@pytest.mark.asyncio
async def test_plan_is_refused_when_it_does_not_match_the_document(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXE")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]

    resp = await client.put(
        f"{API}/admin/proposal-template-docs/{doc_id}/plan", headers=auth(token),
        json={"plan": {"version": 1, "entries": [
            {"kind": "replace", "key": "x", "path": "body[999]"},
        ]}},
    )
    assert resp.status_code == 422
    assert "body[999]" in resp.text


@pytest.mark.asyncio
async def test_a_coherent_plan_is_saved(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXF")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]
    outline = (await client.get(f"{API}/admin/proposal-template-docs/{doc_id}",
                                headers=auth(token))).json()["outline"]
    table = next(b for b in outline["blocks"] if b["kind"] == "table")

    plan = {"version": 1, "entries": [
        {"kind": "token", "key": "client_name", "literal": "School Name"},
        {"kind": "table", "key": "pricing_table", "path": table["path"],
         "fingerprint": table["fingerprint"],
         "columns": [{"col": 0, "field": "label"}, {"col": 1, "field": "line_total"}],
         "header_rows": 1, "total_row": {"label_col": 0, "value_col": 1}},
    ]}
    resp = await client.put(f"{API}/admin/proposal-template-docs/{doc_id}/plan",
                            headers=auth(token), json={"plan": plan})
    assert resp.status_code == 200, resp.text
    assert resp.json()["entries"] == 2

    again = await client.get(f"{API}/admin/proposal-template-docs/{doc_id}",
                             headers=auth(token))
    assert len(again.json()["plan"]["entries"]) == 2


@pytest.mark.asyncio
async def test_preview_returns_a_pdf_without_calling_a_model(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXG")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]

    resp = await client.post(f"{API}/admin/proposal-template-docs/{doc_id}/preview",
                             headers=auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.content[:5] == b"%PDF-"
    assert "inline" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_media_serves_a_real_part_and_refuses_anything_else(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXH")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]

    # this fixture embeds no images, so any name must be refused
    for name in ("image1.png", "../../../etc/passwd", "document.xml"):
        resp = await client.get(
            f"{API}/admin/proposal-template-docs/{doc_id}/media/{name}",
            headers=auth(token),
        )
        assert resp.status_code == 404, f"{name} -> {resp.status_code}"


@pytest.mark.asyncio
async def test_another_org_cannot_read_the_document(client, org_a, org_b):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXI")
    doc_id = (await _upload(client, token, program_id)).json()["doc_id"]

    resp = await client.get(f"{API}/admin/proposal-template-docs/{doc_id}",
                            headers=auth(org_b["admin_token"]))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_second_upload_of_the_same_name_becomes_version_two(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXJ")
    first = await _upload(client, token, program_id, name="Branded")
    second = await _upload(client, token, program_id, name="Branded")
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert second.json()["is_current"] is True

    listed = (await client.get(
        f"{API}/admin/programs/{program_id}/proposal-templates", headers=auth(token)
    )).json()
    current = [t for t in listed if t["is_current"]]
    assert len(current) == 1 and current[0]["version"] == 2


# --- the simple flow on the upload route (Task B1) --------------------------


def _tagged_docx() -> bytes:
    """The same shape as `_docx`, with the placeholders written in by hand.

    That is the whole difference between the two flows: in the simple one the
    template author marks the document, and the administrator only uploads it.
    """
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph(
        "Prepared for <School Name>, in a body paragraph long enough to serve "
        "as a style reference."
    )
    t = doc.add_table(rows=3, cols=2)
    t.cell(0, 0).text = "Description"; t.cell(0, 1).text = "Estimation"
    t.cell(1, 0).text = "Laptops"; t.cell(1, 1).text = "<ask:6 Units>"
    t.cell(2, 0).text = "Interactive Panel"; t.cell(2, 1).text = "<ask:1 Unit>"
    buf = io.BytesIO(); doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_the_upload_route_defaults_to_the_simple_flow(client, org_a):
    """No `flow` field at all: the owner asked for simple to be the default."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS1")
    resp = await _upload(client, token, program_id, data=_tagged_docx(), flow=None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "docx_simple"
    assert body["flow"] == "simple"


@pytest.mark.asyncio
async def test_a_simple_upload_reports_what_it_found(client, org_a):
    """Plan section 6.3: how many tags, how many will always be asked, and the
    distinct literals. That summary is the entire success screen -- no editor,
    no next step."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS2")
    body = (await _upload(client, token, program_id,
                          data=_tagged_docx(), flow="simple")).json()

    assert body["tags"] == 3
    assert body["always_asked"] == 2
    assert body["distinct"] == ["<School Name>", "<ask:1 Unit>", "<ask:6 Units>"]


@pytest.mark.asyncio
async def test_a_simple_upload_stores_the_occurrence_map(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS3")
    doc_id = (await _upload(client, token, program_id,
                            data=_tagged_docx(), flow="simple")).json()["doc_id"]

    fetched = await client.get(
        f"{API}/admin/proposal-template-docs/{doc_id}", headers=auth(token)
    )
    plan = fetched.json()["plan"]
    assert plan["flow"] == "simple"
    assert plan["version"] == 1
    assert len(plan["tags"]) == 3
    for tag in plan["tags"]:
        assert set(tag) == {
            "tag_id", "kind", "raw", "default", "ordinal",
            "start", "end", "context", "duplicate_of",
        }
    by_raw = {t["raw"]: t for t in plan["tags"]}
    assert by_raw["<ask:1 Unit>"]["context"] == "Interactive Panel"
    assert by_raw["<ask:6 Units>"]["default"] == "6 Units"


@pytest.mark.asyncio
async def test_a_document_with_no_tags_is_refused_by_the_simple_flow(client, org_a):
    """A simple-flow template with no tags produces the same document for every
    client, so the refusal names that consequence and offers the other flow."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS4")
    resp = await _upload(client, token, program_id, data=_docx(), flow="simple")

    assert resp.status_code == 422
    message = resp.text.lower()
    assert "no placeholders" in message or "no tags" in message
    assert "every client" in message
    assert "marked here" in message or "complex" in message or "console" in message


@pytest.mark.asyncio
async def test_a_refused_upload_creates_nothing(client, org_a):
    """The refusal happens before any row is written or any file is stored."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS5")
    assert (await _upload(client, token, program_id,
                          data=_docx(), flow="simple")).status_code == 422

    listed = await client.get(
        f"{API}/admin/programs/{program_id}/proposal-templates", headers=auth(token)
    )
    assert listed.json() == []


@pytest.mark.asyncio
async def test_the_complex_flow_still_accepts_a_document_with_no_tags(client, org_a):
    """The complex flow is unchanged: its placeholders are marked in the
    console afterwards, so an untagged document is exactly what it expects."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS6")
    body = (await _upload(client, token, program_id,
                          data=_docx(), flow="complex")).json()

    assert body["kind"] == "docx"
    assert body["flow"] == "complex"
    assert body["tags"] == 0


@pytest.mark.asyncio
async def test_the_complex_flow_ignores_tags_that_happen_to_be_there(client, org_a):
    """A tagged document uploaded as complex behaves exactly as it did before
    this feature existed -- kind `docx`, an empty entries plan, an editor."""
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS7")
    doc_id = (await _upload(client, token, program_id,
                            data=_tagged_docx(), flow="complex")).json()["doc_id"]

    fetched = await client.get(
        f"{API}/admin/proposal-template-docs/{doc_id}", headers=auth(token)
    )
    assert fetched.json()["plan"] == {"version": 1, "entries": []}


@pytest.mark.asyncio
async def test_an_unknown_flow_is_refused(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS8")
    resp = await _upload(client, token, program_id,
                         data=_tagged_docx(), flow="whichever")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_simple_template_refuses_to_build_instead_of_rendering_markdown(
    client, org_a
):
    """The failure this guard exists to prevent is silent and client-facing.

    proposal_service branches on `kind == "docx"`, so a `docx_simple` template
    falls through to the MARKDOWN path and renders body_md -- which for a docx
    template is the projected plain text of the document, tags and all. The
    client would receive a proposal reading "<ask:6 Units>" with none of the
    branding, and nothing would have gone wrong loudly.

    This is not hypothetical: the complex flow's own deployment notes record a
    salesperson asking Jarvis for a proposal and silently getting a markdown
    one. Uploading a simple template is what makes that state reachable, so the
    refusal lands in the same task. J1 replaces it with the fill conversation.
    """
    token = org_a["admin_token"]
    program_id = await _program(client, token, "DOCXS9")
    priced = await client.post(
        f"{API}/admin/programs/{program_id}/pricing", headers=auth(token),
        json={"currency": "INR", "items": [
            {"code": "lab", "label": "Innovation Lab", "unit": "per lab",
             "unit_price": 850000, "default_quantity": 1}]},
    )
    assert priced.status_code == 200, priced.text
    uploaded = await _upload(client, token, program_id,
                             data=_tagged_docx(), flow="simple")
    assert uploaded.status_code == 200, uploaded.text
    lead = (await client.post(f"{API}/leads", headers=auth(token),
                              json={"name": "Simple Flow School"})).json()

    resp = await client.post(
        f"{API}/proposals", headers=auth(token),
        json={"lead_id": lead["id"], "program_id": program_id},
    )

    assert resp.status_code == 422, resp.text
    assert "assistant" in resp.text.lower()
    assert "<ask:6 units>" not in resp.text.lower()
