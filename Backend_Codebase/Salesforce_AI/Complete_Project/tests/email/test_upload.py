"""Uploading and managing Word email templates (spec 7, plan Task 4)."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from docx import Document

from tests.conftest import auth

API = "/api/v1"
URL = f"{API}/admin/email-templates"
FIXTURES = Path(__file__).parent / "fixtures"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _unique(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:6]}"


def _docx(*lines: str) -> bytes:
    doc = Document()
    for line in lines:
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def _program(client, token) -> str:
    code = f"P{uuid.uuid4().hex[:6].upper()}"
    resp = await client.post(f"{API}/admin/programs", headers=auth(token),
                             json={"name": f"Prog {code}", "code": code,
                                   "description": "d"})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload(client, token, *, data: bytes, name: str, template_type="common",
                  category="follow_up", program_id=None, built_document="none",
                  filename="t.docx", when_to_use=None):
    form = {"template_type": template_type, "name": name,
            "built_document": built_document}
    if category is not None:
        form["category"] = category
    if program_id is not None:
        form["program_id"] = program_id
    if when_to_use is not None:
        form["when_to_use"] = when_to_use
    return await client.post(URL, headers=auth(token), data=form,
                             files={"file": (filename, data, DOCX)})


async def test_upload_a_common_template(client, org_a):
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("No reply follow-up.docx"),
                         name=_unique("No reply"), category="Follow-up",
                         when_to_use="The client has not replied.")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "common"
    assert body["category"] == "follow_up"
    assert body["category_label"] == "Follow-up"
    assert body["subject"] == "Innovation learning for <School Name> | YuviPep"
    assert body["tags"] > 0
    assert body["always_asked"] == 3  # salutation + two links
    assert body["is_current"] is True and body["version"] == 1
    assert body["when_to_use"] == "The client has not replied."
    assert body["leftover_blanks"] == []


async def test_upload_a_product_template_with_built_proposal(client, org_a):
    program_id = await _program(client, org_a["admin_token"])
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("IBC proposal email.docx"),
                         name=_unique("Proposal email"), template_type="product",
                         category=None, program_id=program_id,
                         built_document="proposal")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_type"] == "product"
    assert body["program_id"] == program_id
    assert body["program_name"].startswith("Prog ")
    assert body["category"] is None
    assert body["built_document"] == "proposal"


async def test_common_with_a_program_is_refused(client, org_a):
    program_id = await _program(client, org_a["admin_token"])
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("Final follow-up.docx"),
                         name=_unique("x"), program_id=program_id)
    assert resp.status_code == 422
    assert "product" in resp.json()["detail"].lower()


async def test_product_without_a_program_is_refused(client, org_a):
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("IBC proposal email.docx"),
                         name=_unique("x"), template_type="product",
                         category=None)
    assert resp.status_code == 422
    assert "product" in resp.json()["detail"].lower()


async def test_common_with_built_document_is_refused(client, org_a):
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("Final follow-up.docx"),
                         name=_unique("x"), built_document="proposal")
    assert resp.status_code == 422


async def test_common_without_a_category_is_refused(client, org_a):
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("Final follow-up.docx"),
                         name=_unique("x"), category=None)
    assert resp.status_code == 422
    assert "category" in resp.json()["detail"].lower()


async def test_no_subject_line_is_refused(client, org_a):
    resp = await _upload(client, org_a["admin_token"],
                         data=_docx("Dear <Contact Name>,", "Hello."),
                         name=_unique("x"))
    assert resp.status_code == 422
    assert "Subject:" in resp.json()["detail"]


async def test_not_a_word_file_is_refused(client, org_a):
    resp = await _upload(client, org_a["admin_token"], data=b"not a zip",
                         name=_unique("x"))
    assert resp.status_code == 422
    resp = await _upload(client, org_a["admin_token"],
                         data=_fixture("Final follow-up.docx"),
                         name=_unique("x"), filename="t.pdf")
    assert resp.status_code == 422


async def test_too_large_is_refused(client, org_a):
    from app.services import email_template_service as svc

    big = b"PK" + b"0" * (svc.MAX_TEMPLATE_BYTES + 1)
    resp = await _upload(client, org_a["admin_token"], data=big, name=_unique("x"))
    assert resp.status_code == 422
    assert "MB" in resp.json()["detail"]


async def test_leftover_square_brackets_are_reported(client, org_a):
    resp = await _upload(client, org_a["admin_token"],
                         data=_docx("Subject: Hi <School Name>",
                                    "Dear [Name],", "Thanks."),
                         name=_unique("Brackets"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["leftover_blanks"] == ["[Name]"]


async def test_new_version_supersedes_only_its_own_name_and_keeps_attachments(
        client, org_a):
    token = org_a["admin_token"]
    name, other = _unique("Versioned"), _unique("Other")
    first = (await _upload(client, token, data=_fixture("Final follow-up.docx"),
                           name=name)).json()
    kept = (await _upload(client, token, data=_fixture("Final follow-up.docx"),
                          name=other)).json()
    att = await client.post(f"{URL}/{first['id']}/attachments", headers=auth(token),
                            files={"file": ("brochure.pdf", b"%PDF-1.4 x",
                                            "application/pdf")})
    assert att.status_code == 200, att.text
    second = (await _upload(client, token, data=_fixture("Final follow-up.docx"),
                            name=name)).json()
    assert second["version"] == 2 and second["is_current"] is True
    assert [a["filename"] for a in second["attachments"]] == ["brochure.pdf"]
    rows = {r["id"]: r for r in (await client.get(URL, headers=auth(token))).json()}
    assert rows[first["id"]]["is_current"] is False
    assert rows[kept["id"]]["is_current"] is True


async def test_two_current_templates_in_one_product(client, org_a):
    token = org_a["admin_token"]
    program_id = await _program(client, token)
    a = (await _upload(client, token, data=_fixture("IBC proposal email.docx"),
                       name=_unique("P"), template_type="product", category=None,
                       program_id=program_id, built_document="proposal")).json()
    b = (await _upload(client, token, data=_fixture("IBC MoU cover letter.docx"),
                       name=_unique("M"), template_type="product", category=None,
                       program_id=program_id, built_document="mou")).json()
    rows = {r["id"]: r for r in (await client.get(URL, headers=auth(token))).json()}
    assert rows[a["id"]]["is_current"] and rows[b["id"]]["is_current"]


async def test_attachment_rules(client, org_a):
    from app.services import email_template_service as svc

    token = org_a["admin_token"]
    tpl = (await _upload(client, token, data=_fixture("Final follow-up.docx"),
                         name=_unique("Att"))).json()
    url = f"{URL}/{tpl['id']}/attachments"
    bad = await client.post(url, headers=auth(token),
                            files={"file": ("run.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 422
    huge = await client.post(url, headers=auth(token), files={
        "file": ("big.pdf", b"0" * (svc.MAX_ATTACHMENT_BYTES + 1), "application/pdf")})
    assert huge.status_code == 422
    nine = b"0" * (9 * 1024 * 1024)
    for i in (1, 2):
        ok = await client.post(url, headers=auth(token),
                               files={"file": (f"part{i}.pdf", nine, "application/pdf")})
        assert ok.status_code == 200, ok.text
    over = await client.post(url, headers=auth(token),
                             files={"file": ("part3.pdf", nine, "application/pdf")})
    assert over.status_code == 422
    assert "20 MB" in over.json()["detail"]
    first_id = ok.json()["id"]
    gone = await client.delete(f"{url}/{first_id}", headers=auth(token))
    assert gone.status_code == 200
    rows = {r["id"]: r for r in (await client.get(URL, headers=auth(token))).json()}
    assert [a["filename"] for a in rows[tpl["id"]]["attachments"]] == ["part1.pdf"]


async def test_remove_promotes_the_previous_version(client, org_a):
    token = org_a["admin_token"]
    name = _unique("Promote")
    v1 = (await _upload(client, token, data=_fixture("Final follow-up.docx"),
                        name=name)).json()
    v2 = (await _upload(client, token, data=_fixture("Final follow-up.docx"),
                        name=name)).json()
    resp = await client.delete(f"{URL}/{v2['id']}", headers=auth(token))
    assert resp.status_code == 200
    rows = {r["id"]: r for r in (await client.get(URL, headers=auth(token))).json()}
    assert v2["id"] not in rows
    assert rows[v1["id"]]["is_current"] is True


async def test_only_manage_templates_can_write(client, org_a):
    resp = await _upload(client, org_a["agent_token"],
                         data=_fixture("Final follow-up.docx"), name=_unique("x"))
    assert resp.status_code == 403
    tpl = (await _upload(client, org_a["admin_token"],
                         data=_fixture("Final follow-up.docx"),
                         name=_unique("x"))).json()
    resp = await client.delete(f"{URL}/{tpl['id']}", headers=auth(org_a["agent_token"]))
    assert resp.status_code == 403


async def test_categories_lists_presets_and_custom(client, org_a):
    token = org_a["admin_token"]
    await _upload(client, token, data=_fixture("Final follow-up.docx"),
                  name=_unique("Custom"), category="Exam season note")
    rows = (await client.get(f"{URL}/categories", headers=auth(token))).json()
    keys = [r["key"] for r in rows]
    assert keys[:6] == ["intro", "meeting_confirmation", "after_meeting",
                        "follow_up", "final_follow_up", "onboarding"]
    assert "exam_season_note" in keys


async def test_old_message_templates_untouched(client, org_a):
    token = org_a["admin_token"]
    before = (await client.get(f"{API}/admin/message-templates",
                               headers=auth(token))).json()
    await _upload(client, token, data=_fixture("Final follow-up.docx"),
                  name=_unique("x"))
    after = (await client.get(f"{API}/admin/message-templates",
                              headers=auth(token))).json()
    assert before == after


async def test_another_orgs_templates_are_invisible(client, org_a, org_b):
    tpl = (await _upload(client, org_a["admin_token"],
                         data=_fixture("Final follow-up.docx"),
                         name=_unique("Private"))).json()
    rows = (await client.get(URL, headers=auth(org_b["admin_token"]))).json()
    assert tpl["id"] not in {r["id"] for r in rows}
    resp = await client.delete(f"{URL}/{tpl['id']}", headers=auth(org_b["admin_token"]))
    assert resp.status_code == 404
