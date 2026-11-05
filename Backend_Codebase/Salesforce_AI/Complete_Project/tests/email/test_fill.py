"""Filling one email from the client's record, or by asking (plan Task 5)."""
from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai import docx_tagfill
from app.core import clock
from app.core.context import OrgContext
from app.core.exceptions import ValidationFailedError
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.email_template import EmailFillSession, EmailFillStatus, EmailTemplate
from app.models.lead import Contact
from app.models.messaging import OutboundMessage
from app.models.mou import MouDocument
from app.models.proposal import Proposal
from app.models.scheduled_meeting import ScheduledMeeting
from app.models.user import User
from app.services import email_fill_service as fill
from app.services import storage
from tests.conftest import auth
from tests.email.helpers import (  # noqa: F401  (layer is a fixture)
    API, FACTS, FIXTURES, ctx_for, layer, lead_with_contact, make_program, make_template,
)

async def _open(client, org, filename, **kw):
    token = org["admin_token"]
    ctx = await ctx_for(org)
    template_id = await make_template(client, token, filename, **kw)
    lead_id, contact_id = await lead_with_contact(client, token)
    async with SessionLocal() as db:
        template = await db.get(EmailTemplate, template_id)
        session = await fill.open_session(
            db, ctx, template=template, lead_id=lead_id,
            chat_session_id=f"chat-{uuid.uuid4().hex[:8]}",
            contact_id=contact_id, to_address="sunil@greenvalley.example", cc=[])
        await db.commit()
        return ctx, session.id, lead_id, template_id


async def _session(session_id) -> EmailFillSession:
    async with SessionLocal() as db:
        return await db.get(EmailFillSession, session_id)


async def _message(message_id) -> OutboundMessage:
    async with SessionLocal() as db:
        return await db.get(OutboundMessage, message_id)


def _answer(session, by_raw: dict[str, str]) -> dict:
    return {"resolutions": [
        {"tag_id": t["tag_id"], "value": by_raw[t["raw"]]}
        for t in session.tags_json
        if t.get("outcome") == "question" and t["raw"] in by_raw]}


# --- the first pass ----------------------------------------------------------


async def test_facts_fill_silently_and_the_rest_is_asked(client, org_a, layer):
    layer(by_raw=FACTS)
    _, sid, _, _ = await _open(client, org_a, "Intro and appointment seeking.docx")
    session = await _session(sid)
    assert session.status == EmailFillStatus.ASKING
    filled = {t["raw"]: t["value"] for t in session.tags_json
              if t.get("outcome") == "filled"}
    assert filled["<School Name>"] == "Green Valley"
    assert filled["<Your Name>"] == "Asha Admin"
    asked = [t["raw"] for t in fill.open_questions(session, limit=None)]
    assert asked.count("<ask:>") == 2            # the two meeting options
    assert "<ask:Mr.|Ms.|Mrs.>" in asked


async def test_salutation_is_asked_with_three_taps(client, org_a, layer):
    layer(by_raw=FACTS)
    _, sid, _, _ = await _open(client, org_a, "Final follow-up.docx")
    session = await _session(sid)
    [salutation] = [t for t in fill.open_questions(session)
                    if t["raw"] == "<ask:Mr.|Ms.|Mrs.>"]
    assert salutation["candidates"] == ["Mr.", "Ms.", "Mrs."]


async def test_accepting_suggestions_never_writes_a_multi_choice_default(
        client, org_a, layer):
    """Review Focus 1: "All the suggested values are fine" with the salutation
    on screen. The model accepting the author's default must not write the
    literal Mr.|Ms.|Mrs. into the email."""
    made = layer(by_raw=FACTS)
    ctx, sid, _, _ = await _open(client, org_a, "Final follow-up.docx")
    session = await _session(sid)
    made.answers.append(_answer(session, {"<ask:Mr.|Ms.|Mrs.>": "Mr.|Ms.|Mrs."}))
    async with SessionLocal() as db:
        session = await db.get(EmailFillSession, sid)
        session = await fill.apply_answers(
            db, ctx, session, "All the suggested values are fine")
        await db.commit()
    session = await _session(sid)
    assert session.status == EmailFillStatus.ASKING
    assert session.message_id is None
    [salutation] = fill.open_questions(session)
    assert salutation["raw"] == "<ask:Mr.|Ms.|Mrs.>"


async def test_answers_then_draft_has_no_tags_left(client, org_a, layer):
    made = layer(by_raw=FACTS)
    ctx, sid, _, _ = await _open(client, org_a, "Final follow-up.docx")
    session = await _session(sid)
    made.answers.append(_answer(session, {"<ask:Mr.|Ms.|Mrs.>": "Mr."}))
    async with SessionLocal() as db:
        session = await db.get(EmailFillSession, sid)
        session = await fill.apply_answers(db, ctx, session, "Mr.")
        await db.commit()
    session = await _session(sid)
    assert session.status == EmailFillStatus.DRAFTED
    message = await _message(session.message_id)
    assert message.status == "pending_approval"
    assert message.subject == "Should we stay in touch? | YuviPep and Green Valley"
    assert message.body.startswith("Dear Mr. Menon,")
    assert not re.search(r"<[^<>\n]{1,150}>", message.subject + message.body)
    assert "<strong>Asha Admin</strong>" in session.html_body
    assert message.kind == "follow_up"


async def test_booked_meeting_fills_the_confirmation(client, org_a, layer):
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    lead_id, contact_id = await lead_with_contact(client, token)
    async with SessionLocal() as db:
        today = clock.today(await clock.org_zone(db, ctx.org_id))
        db.add(ScheduledMeeting(org_id=ctx.org_id, lead_id=lead_id,
                                meeting_date=today + timedelta(days=3),
                                start_time="11:00", organizer_id=ctx.user_id,
                                purpose="Introduction"))
        await db.commit()
    layer(by_raw={**FACTS,
                  "<Meeting day and date>": ("Friday", "booked_meetings[0].date"),
                  "<Meeting time>": ("11:00 am", "booked_meetings[0].start_time")})
    template_id = await make_template(client, token, "Meeting confirmation.docx",
                                  category="meeting_confirmation")
    async with SessionLocal() as db:
        template = await db.get(EmailTemplate, template_id)
        session = await fill.open_session(
            db, ctx, template=template, lead_id=lead_id, chat_session_id="c-meet",
            contact_id=contact_id, to_address="sunil@greenvalley.example", cc=[])
        assert session.dossier_json["booked_meetings"][0]["start_time"] == "11:00"
        asked = {t["raw"] for t in fill.open_questions(session, limit=None)}
        assert "<Meeting day and date>" not in asked
        assert "<Meeting time>" not in asked
        await db.commit()


# --- built documents ---------------------------------------------------------


async def _proposal(ctx, lead_id, program_id, *, status="draft") -> str:
    async with SessionLocal() as db:
        proposal = Proposal(
            org_id=ctx.org_id, lead_id=lead_id, program_id=program_id,
            title="IBC Proposal - Green Valley", template_id="t", template_version=1,
            content_md="x", created_by=ctx.user_id, status=status,
            template_kind="docx_simple")
        db.add(proposal)
        await db.flush()
        proposal.docx_path = storage.save_bytes(ctx.org_id, "proposals", "p.docx", b"d")
        proposal.pdf_path = storage.save_bytes(ctx.org_id, "proposals", "p.pdf",
                                               b"%PDF-1.4 proposal")
        await db.commit()
        return proposal.id


async def test_built_document_missing_waits_and_does_not_draft(client, org_a, layer):
    made = layer(by_raw=FACTS)
    program_id = await make_program(client, org_a["admin_token"])
    _, sid, _, _ = await _open(client, org_a, "IBC proposal email.docx",
                               program_id=program_id, built="proposal")
    session = await _session(sid)
    assert session.status == EmailFillStatus.WAITING_FOR_DOCUMENT
    assert session.message_id is None
    assert made.calls == []          # no model call while there is nothing to send


async def test_built_proposal_attached_and_linked(client, org_a, layer):
    made = layer(by_raw=FACTS)
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    program_id = await make_program(client, token)
    lead_id, contact_id = await lead_with_contact(client, token)
    await _proposal(ctx, lead_id, program_id, status="declined")
    proposal_id = await _proposal(ctx, lead_id, program_id)
    template_id = await make_template(client, token, "IBC proposal email.docx",
                                  program_id=program_id, built="proposal")
    async with SessionLocal() as db:
        template = await db.get(EmailTemplate, template_id)
        session = await fill.open_session(
            db, ctx, template=template, lead_id=lead_id, chat_session_id="c-prop",
            contact_id=contact_id, to_address="sunil@greenvalley.example", cc=[])
        made.answers.append(_answer(session, {"<ask:Mr.|Ms.|Mrs.>": "Mr."}))
        session = await fill.apply_answers(db, ctx, session, "Mr.")
        await db.commit()
        sid = session.id
    session = await _session(sid)
    message = await _message(session.message_id)
    assert session.proposal_id == proposal_id
    assert message.proposal_id == proposal_id
    assert message.kind == "proposal"
    assert [a["filename"] for a in message.attachments] == [
        "IBC_Proposal_Green_Valley.pdf"]


async def test_resume_after_the_proposal_is_built(client, org_a, layer):
    layer(by_raw=FACTS)
    program_id = await make_program(client, org_a["admin_token"])
    ctx, sid, lead_id, _ = await _open(client, org_a, "IBC proposal email.docx",
                                       program_id=program_id, built="proposal")
    await _proposal(ctx, lead_id, program_id)
    async with SessionLocal() as db:
        session = await db.get(EmailFillSession, sid)
        session = await fill.resume(db, ctx, session)
        await db.commit()
    session = await _session(sid)
    assert session.status == EmailFillStatus.ASKING
    assert [t["raw"] for t in fill.open_questions(session)] == ["<ask:Mr.|Ms.|Mrs.>"]


async def test_built_mou_attached_and_marked_sent_on_send(client, org_a, layer):
    made = layer(by_raw=FACTS)
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    program_id = await make_program(client, token)
    lead_id, contact_id = await lead_with_contact(client, token)
    async with SessionLocal() as db:
        mou = MouDocument(org_id=ctx.org_id, lead_id=lead_id, program_id=program_id,
                          title="IBC MOU - Green Valley", template_id="t",
                          template_version=1, content_md="x", created_by=ctx.user_id)
        db.add(mou)
        await db.flush()
        mou.pdf_path = storage.save_bytes(ctx.org_id, "proposals", "m.pdf", b"%PDF m")
        await db.commit()
        mou_id = mou.id
    template_id = await make_template(client, token, "IBC MoU cover letter.docx",
                                  program_id=program_id, built="mou")
    async with SessionLocal() as db:
        template = await db.get(EmailTemplate, template_id)
        session = await fill.open_session(
            db, ctx, template=template, lead_id=lead_id, chat_session_id="c-mou",
            contact_id=contact_id, to_address="sunil@greenvalley.example", cc=[])
        made.answers.append(_answer(session, {"<ask:Mr.|Ms.|Mrs.>": "Ms."}))
        session = await fill.apply_answers(db, ctx, session, "Ms.")
        await db.commit()
        message_id = session.message_id
    async with SessionLocal() as db:
        from app.services import message_service
        message = await db.get(OutboundMessage, message_id)
        assert message.attachments[0]["filename"].endswith(".pdf")
        await message_service.approve_message(db, ctx, message_id)
        await message_service.execute_send(db, message)
        await db.commit()
    async with SessionLocal() as db:
        mou = await db.get(MouDocument, mou_id)
        assert mou.status == "sent" and mou.sent_at is not None


# --- changes, refusals and time ----------------------------------------------


async def _drafted(client, org_a, layer, filename="Final follow-up.docx"):
    made = layer(by_raw=FACTS)
    ctx, sid, _, _ = await _open(client, org_a, filename)
    session = await _session(sid)
    made.answers.append(_answer(session, {"<ask:Mr.|Ms.|Mrs.>": "Mr."}))
    async with SessionLocal() as db:
        session = await db.get(EmailFillSession, sid)
        session = await fill.apply_answers(db, ctx, session, "Mr.")
        await db.commit()
    return made, ctx, await _session(sid)


async def test_change_redrafts_the_same_message(client, org_a, layer):
    made, ctx, session = await _drafted(client, org_a, layer)
    surname = next(t for t in session.tags_json if t["raw"] == "<Surname>")
    made.revisions.append({"resolutions": [
        {"tag_id": surname["tag_id"], "value": "Menon-Rao"}]})
    async with SessionLocal() as db:
        live = await db.get(EmailFillSession, session.id)
        live = await fill.apply_change(db, ctx, live, "his surname is Menon-Rao")
        await db.commit()
    after = await _session(session.id)
    assert after.message_id == session.message_id
    message = await _message(after.message_id)
    assert message.body.startswith("Dear Mr. Menon-Rao,")


async def test_change_after_approval_is_refused(client, org_a, layer):
    """Review Focus 2."""
    from app.services import message_service

    made, ctx, session = await _drafted(client, org_a, layer)
    async with SessionLocal() as db:
        await message_service.approve_message(db, ctx, session.message_id)
        await db.commit()
    async with SessionLocal() as db:
        live = await db.get(EmailFillSession, session.id)
        with pytest.raises(ValidationFailedError) as err:
            await fill.apply_change(db, ctx, live, "make it Friday")
    assert "already been approved" in err.value.message
    assert made.revisions == []      # the model was never asked


async def test_missing_attachment_file_refuses_the_draft(client, org_a, layer):
    """Review Focus 3: a default file gone from storage stops the draft."""
    made = layer(by_raw=FACTS)
    token = org_a["admin_token"]
    ctx = await ctx_for(org_a)
    template_id = await make_template(client, token, "Final follow-up.docx")
    resp = await client.post(
        f"{API}/admin/email-templates/{template_id}/attachments",
        headers=auth(token),
        files={"file": ("brochure.pdf", b"%PDF b", "application/pdf")})
    assert resp.status_code == 200
    from app.models.email_template import EmailTemplateAttachment
    async with SessionLocal() as db:
        att = (await db.execute(select(EmailTemplateAttachment).where(
            EmailTemplateAttachment.template_id == template_id))).scalar_one()
        storage.delete_file(ctx.org_id, att.path)
    lead_id, contact_id = await lead_with_contact(client, token)
    async with SessionLocal() as db:
        template = await db.get(EmailTemplate, template_id)
        session = await fill.open_session(
            db, ctx, template=template, lead_id=lead_id, chat_session_id="c-miss",
            contact_id=contact_id, to_address="sunil@greenvalley.example", cc=[])
        made.answers.append(_answer(session, {"<ask:Mr.|Ms.|Mrs.>": "Mr."}))
        with pytest.raises(ValidationFailedError) as err:
            await fill.apply_answers(db, ctx, session, "Mr.")
    assert "brochure.pdf" in err.value.message


async def test_session_past_seven_days_is_abandoned(client, org_a, layer):
    layer(by_raw=FACTS)
    ctx, sid, _, _ = await _open(client, org_a, "Final follow-up.docx")
    async with SessionLocal() as db:
        session = await db.get(EmailFillSession, sid)
        chat = session.chat_session_id
        session.updated_at = utcnow() - timedelta(days=8)
        await db.commit()
    async with SessionLocal() as db:
        assert await fill.find_for_chat(
            db, ctx, chat, statuses=(EmailFillStatus.ASKING,)) is None
    assert (await _session(sid)).status == EmailFillStatus.ABANDONED


async def test_a_chat_with_no_id_matches_nothing(client, org_a, layer):
    layer(by_raw=FACTS)
    ctx, _, _, _ = await _open(client, org_a, "Final follow-up.docx")
    async with SessionLocal() as db:
        assert await fill.find_for_chat(
            db, ctx, None, statuses=(EmailFillStatus.ASKING,)) is None


# --- the shared prompts ------------------------------------------------------


async def test_proposal_prompts_are_unchanged(monkeypatch):
    seen = []

    class Capture:
        async def generate_json(self, **kwargs):
            seen.append((kwargs["purpose"], kwargs["messages"][0]["content"]))
            return {"resolutions": []}

    monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: Capture())
    occ = [{"tag_id": "a" * 12, "kind": "semantic", "raw": "<X>", "context": ""}]
    await docx_tagfill.resolve_tags(None, dossier={}, document_text="d",
                                    occurrences=occ)
    await docx_tagfill.answer_round(None, dossier={}, open_questions=occ,
                                    user_reply="r", asked=[])
    await docx_tagfill.revise(None, dossier={}, resolutions=occ, correction="c")
    await docx_tagfill.resolve_tags(None, dossier={}, document_text="d",
                                    occurrences=occ, document="email")
    await docx_tagfill.answer_round(None, dossier={}, open_questions=occ,
                                    user_reply="r", asked=[], document="email")
    await docx_tagfill.revise(None, dossier={}, resolutions=occ, correction="c",
                              document="email")
    purposes = [p for p, _ in seen]
    assert purposes == ["proposal.docx_tagfill", "proposal.docx_tagfill_answer",
                        "proposal.docx_tagfill_revise", "email.tagfill",
                        "email.tagfill_answer", "email.tagfill_revise"]
    assert seen[0][1].startswith("You are filling in a proposal document for a real client.")
    assert seen[3][1].startswith("You are filling in an email for a real client.")
    assert "proposal document" not in seen[3][1] + seen[4][1] + seen[5][1]


async def test_a_sender_without_a_job_title_is_named_by_role_in_words(client, org_a):
    """Replay defect 2 (28 Oct): with no designation on record the model wrote
    the role code, "sales_lead | YuviPep", into the signature."""
    from app.models.user import User

    ctx = await ctx_for(org_a)
    lead_id, contact_id = await lead_with_contact(client, org_a["admin_token"])
    async with SessionLocal() as db:
        user = await db.get(User, ctx.user_id)
        user.designation = None
        await db.commit()
        dossier = await fill.email_dossier(db, ctx, lead_id=lead_id, program_id=None,
                                           contact_id=contact_id)
        user.designation = "Sales Lead"
        await db.commit()
    assert dossier["sender"]["designation"] == "Org Admin"
    assert dossier["sender"]["role"] == "Org Admin"
