"""The email that leaves: HTML for template emails, everything else as before."""
from __future__ import annotations

import email
from email import policy

from app.services import email_service, storage


def _parse(raw: bytes):
    return email.message_from_bytes(raw, policy=policy.default)


def _payload(**kw) -> email_service.EmailPayload:
    base = dict(sender_name="Asha", sender_email="asha@alpha-example.com",
                to_address="sunil@greenvalley.example", subject="Hello",
                body="Dear Mr. Menon,\n\nPlain body.\n", org_id="org-send-test")
    base.update(kw)
    return email_service.EmailPayload(**base)


def _types(msg) -> list[str]:
    return [part.get_content_type() for part in msg.walk()]


async def test_template_email_sends_html_and_text():
    ref = await email_service.send_email(
        _payload(html_body="<div><p><strong>Dear</strong> Mr. Menon,</p></div>"), None)
    msg = _parse(storage.read_bytes("org-send-test", ref.split(":", 1)[1]))
    assert _types(msg) == ["multipart/alternative", "text/plain", "text/html"]
    assert "Plain body." in msg.get_body(("plain",)).get_content()
    assert "<strong>Dear</strong>" in msg.get_body(("html",)).get_content()


async def test_old_message_still_sends_plain_text():
    ref = await email_service.send_email(_payload(), None)
    msg = _parse(storage.read_bytes("org-send-test", ref.split(":", 1)[1]))
    assert _types(msg) == ["text/plain"]


async def test_calendar_invite_mime_unchanged():
    invite = {"ics_text": "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
              "filename": "invite.ics"}
    ref = await email_service.send_email(_payload(attachments=[invite]), None)
    msg = _parse(storage.read_bytes("org-send-test", ref.split(":", 1)[1]))
    assert _types(msg) == ["multipart/mixed", "multipart/alternative", "text/plain",
                           "text/html", "text/calendar", "application/ics"]


async def test_html_is_ignored_on_a_calendar_invite():
    """An invite already carries its own HTML; a template body never joins it."""
    invite = {"ics_text": "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
              "filename": "invite.ics"}
    ref = await email_service.send_email(
        _payload(attachments=[invite], html_body="<p>should not appear</p>"), None)
    raw = storage.read_bytes("org-send-test", ref.split(":", 1)[1])
    assert b"should not appear" not in raw


async def test_pptx_attachment_gets_its_type():
    path = storage.save_bytes("org-send-test", "email_templates", "deck.pptx", b"PK..")
    ref = await email_service.send_email(
        _payload(attachments=[{"path": path, "filename": "deck.pptx"}]), None)
    msg = _parse(storage.read_bytes("org-send-test", ref.split(":", 1)[1]))
    assert ("application/vnd.openxmlformats-officedocument.presentationml"
            ".presentation") in _types(msg)


async def test_pdf_and_docx_types_unchanged():
    pdf = storage.save_bytes("org-send-test", "proposals", "p.pdf", b"%PDF")
    doc = storage.save_bytes("org-send-test", "proposals", "p.docx", b"PK")
    ref = await email_service.send_email(
        _payload(attachments=[{"path": pdf, "filename": "p.pdf"},
                              {"path": doc, "filename": "p.docx"}]), None)
    types = _types(_parse(storage.read_bytes("org-send-test", ref.split(":", 1)[1])))
    assert "application/pdf" in types
    assert ("application/vnd.openxmlformats-officedocument.wordprocessingml"
            ".document") in types
