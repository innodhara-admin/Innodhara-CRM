# app/services/email_fill_service.py
"""The working memory of one email being filled from a Word template (28 Oct 2026).

The same engine as a proposal fill, much shorter: `docx_tagfill` proposes a
value for every tag and refuses any it cannot back with a fact from the client
dossier, so what is left becomes a question. When nothing is left the email is
drafted at once. There is no separate review of values: the approval card that
every email already waits behind is the one check (spec, decision 12).

    asking -> drafted              (questions, then the draft)
    waiting_for_document -> asking (the proposal or MOU it carries is built)
    any -> abandoned

Two rules belong to email only:

* **A multi-choice tag** (`<ask:Mr.|Ms.|Mrs.>`) is answered only by one of its
  choices. The author's default is the list itself, so "All the suggested
  values are fine" -- which accepts defaults -- would otherwise write the
  literal `Mr.|Ms.|Mrs.` into a client's email.
* **A template that carries a built document** never drafts without it. Its
  words say the proposal is attached.
"""
from __future__ import annotations

import io
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import docx_tagfill
from app.core import clock
from app.core.constants import BuiltDocument, MessageChannel, MessageKind, MessageStatus
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.base import utcnow
from app.models.email_template import EmailFillSession, EmailFillStatus, EmailTemplate
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.mou import MouDocument, MouStatus
from app.models.project import Project, ProjectMember
from app.models.proposal import Proposal
from app.models.scheduled_meeting import ScheduledMeeting
from app.models.user import User
from app.services import (
    client_dossier,
    email_render,
    email_template_service,
    message_service,
    proposal_email_service,
    storage,
)
from app.services.docx import convert
from app.services.docx import tagfill
from app.services.docx import text as dt

logger = logging.getLogger(__name__)

QUESTIONS_PER_ROUND = 6
SESSION_TTL_DAYS = 7
MULTI = "|"

ALREADY_APPROVED = ("That email has already been approved, so I will not change "
                    "it. Ask me for a new one.")
NOT_UNDERSTOOD = ("I could not tell which part of the email you meant. Say which "
                  "line it is and what it should say.")
TEMPLATE_GONE = ("The template this email was being filled from has been "
                 "removed. Ask me for the email again.")
SALUTATION_QUESTION = "Which salutation should the email use?"

_LIVE = (MessageStatus.DRAFT.value, MessageStatus.PENDING_APPROVAL.value)
_FOLLOW_UP_CATEGORIES = ("follow_up", "final_follow_up", "after_meeting")


# --- what a tag may hold -----------------------------------------------------


def choices_of(tag: dict[str, Any]) -> list[str]:
    """The choices of a multi-choice `<ask:a|b|c>` tag, or [] for any other."""
    default = str(tag.get("default") or "")
    if tag.get("kind") != "ask" or MULTI not in default:
        return []
    return [part.strip() for part in default.split(MULTI) if part.strip()]


def _choice_for(value: Any, choices: list[str]) -> str | None:
    said = str(value or "").strip().rstrip(".").casefold()
    for choice in choices:
        if choice.rstrip(".").casefold() == said:
            return choice
    return None


def _apply_choices(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hold every multi-choice tag to its choices (see the module docstring)."""
    out = []
    for tag in tags:
        choices = choices_of(tag)
        if not choices:
            out.append(tag)
            continue
        entry = dict(tag)
        picked = (_choice_for(entry.get("value"), choices)
                  if entry.get("outcome") == "filled" else None)
        if picked is not None:
            entry["value"] = picked
        else:
            entry.update(outcome="question", value=None, source=None,
                         citation=None, question=SALUTATION_QUESTION
                         if entry.get("context", "").strip().lower() == "dear"
                         else (entry.get("question") or f"Which one: {', '.join(choices)}?"))
        entry["candidates"] = list(choices)
        out.append(entry)
    return out


def _record(session: EmailFillSession, resolutions: list[dict[str, Any]]) -> None:
    """Merge a pass's resolutions into the session. Reassigned, never mutated:
    a JSON column tracks assignment, not mutation."""
    by_id = {r["tag_id"]: r for r in resolutions}
    merged = []
    for tag in session.tags_json:
        entry = dict(tag)
        if tag["tag_id"] in by_id:
            entry.update(by_id[tag["tag_id"]])
        merged.append(entry)
    session.tags_json = _apply_choices(merged)


def open_questions(session: EmailFillSession, *,
                   limit: int | None = QUESTIONS_PER_ROUND) -> list[dict[str, Any]]:
    """The questions still open. With a limit: one per (literal, place), at most
    one round, which is what a person is shown."""
    waiting = [t for t in session.tags_json if t.get("outcome") == "question"]
    if limit is None:
        return waiting
    seen: set[tuple[str, str]] = set()
    distinct = []
    for tag in waiting:
        key = (tag.get("raw") or "", tag.get("context") or "")
        if key not in seen:
            seen.add(key)
            distinct.append(tag)
    return distinct[:limit]


def message_kind_for(template: EmailTemplate) -> str:
    if template.built_document == BuiltDocument.PROPOSAL.value:
        return MessageKind.PROPOSAL.value
    if template.category == "intro":
        return MessageKind.INTRO.value
    if template.category in _FOLLOW_UP_CATEGORIES:
        return MessageKind.FOLLOW_UP.value
    return MessageKind.TEMPLATE_EMAIL.value


# --- what the model is told --------------------------------------------------


async def email_dossier(db: AsyncSession, ctx: OrgContext, *, lead_id: str,
                        program_id: str | None,
                        contact_id: str | None) -> dict[str, Any]:
    """The client dossier, plus what only an email needs: who it is going to,
    the meetings already booked, and the people on the client's project. Added
    here and not in `client_dossier`, so proposal and MOU prompts are unchanged."""
    dossier = await client_dossier.build(db, ctx, lead_id, program_id or "")
    sender = dossier.get("sender")
    if sender:
        # The signature line takes a job title. With none on record the model
        # wrote the role CODE ("sales_lead | YuviPep", replay of 28 Oct), so
        # the email's own copy of the sender says the role in words, and
        # stands it in for a missing title.
        role = str(sender.get("role") or "").replace("_", " ").title()
        sender["role"] = role or None
        if not sender.get("designation"):
            sender["designation"] = role or None
    contact = await db.get(Contact, contact_id) if contact_id else None
    dossier["recipient"] = None if contact is None else {
        "name": contact.name, "title": contact.title, "email": contact.email}

    today = clock.today(await clock.org_zone(db, ctx.org_id))
    meetings = (await db.execute(select(ScheduledMeeting).where(
        ScheduledMeeting.org_id == ctx.org_id,
        ScheduledMeeting.lead_id == lead_id,
        ScheduledMeeting.status != "cancelled",
        ScheduledMeeting.meeting_date >= today,
    ).order_by(ScheduledMeeting.meeting_date, ScheduledMeeting.start_time))).scalars().all()
    dossier["booked_meetings"] = [
        {"date": m.meeting_date.isoformat(), "weekday": m.meeting_date.strftime("%A"),
         "start_time": m.start_time, "duration_minutes": m.duration_minutes,
         "purpose": m.purpose}
        for m in meetings]

    project = (await db.execute(select(Project).where(
        Project.org_id == ctx.org_id, Project.lead_id == lead_id,
    ).order_by(Project.created_at.desc()))).scalars().first()
    team = []
    if project is not None:
        rows = (await db.execute(
            select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project.id,
                   ProjectMember.left_at.is_(None)))).all()
        team = [{"name": u.name, "role": m.role_in_project, "phone": u.phone,
                 "email": u.email} for m, u in rows]
    dossier["project_team"] = team
    return dossier


def _document_text(docx_bytes: bytes) -> str:
    """The email as the model reads it: the same walk the tags came from."""
    from docx import Document  # noqa: PLC0415 -- heavy, only needed here

    lines = [dt.node_text(p) for p in dt.walk_paragraphs(Document(io.BytesIO(docx_bytes)))]
    return "\n".join(line for line in lines if line.strip())


async def _today(db: AsyncSession, ctx: OrgContext):
    return clock.today(await clock.org_zone(db, ctx.org_id))


# --- the built document ------------------------------------------------------


async def built_document_for(db: AsyncSession, ctx: OrgContext,
                             template: EmailTemplate,
                             lead_id: str) -> Proposal | MouDocument | None:
    """The client's latest proposal (not declined) or MOU for the template's
    product, or None when the template carries nothing or none is built."""
    if template.built_document == BuiltDocument.PROPOSAL.value:
        return (await db.execute(select(Proposal).where(
            Proposal.org_id == ctx.org_id, Proposal.lead_id == lead_id,
            Proposal.program_id == template.program_id,
            Proposal.status != "declined",
        ).order_by(Proposal.created_at.desc()))).scalars().first()
    if template.built_document == BuiltDocument.MOU.value:
        return (await db.execute(select(MouDocument).where(
            MouDocument.org_id == ctx.org_id, MouDocument.lead_id == lead_id,
            MouDocument.program_id == template.program_id,
        ).order_by(MouDocument.created_at.desc()))).scalars().first()
    return None


def _needs_document(template: EmailTemplate) -> bool:
    return template.built_document != BuiltDocument.NONE.value


def _link(session: EmailFillSession, document) -> None:
    if isinstance(document, Proposal):
        session.proposal_id = document.id
    elif isinstance(document, MouDocument):
        session.mou_id = document.id


# --- the session -------------------------------------------------------------


async def _template_of(db: AsyncSession, ctx: OrgContext,
                       session: EmailFillSession) -> EmailTemplate:
    template = await db.get(EmailTemplate, session.template_id)
    if template is None or template.org_id != ctx.org_id:
        raise NotFoundError(TEMPLATE_GONE)
    return template


async def _first_pass(db: AsyncSession, ctx: OrgContext, session: EmailFillSession,
                      template: EmailTemplate) -> None:
    session.dossier_json = await email_dossier(
        db, ctx, lead_id=session.lead_id, program_id=template.program_id,
        contact_id=session.contact_id)
    source = storage.read_bytes(ctx.org_id, template.source_path)
    resolutions = await docx_tagfill.resolve_tags(
        ctx, dossier=session.dossier_json, document_text=_document_text(source),
        occurrences=session.tags_json, today=await _today(db, ctx),
        document="email")
    _record(session, resolutions)
    session.status = EmailFillStatus.ASKING


async def open_session(db: AsyncSession, ctx: OrgContext, *, template: EmailTemplate,
                       lead_id: str, chat_session_id: str | None,
                       contact_id: str | None, to_address: str,
                       cc: list[str]) -> EmailFillSession:
    lead = await db.get(Lead, lead_id)
    if lead is None or lead.org_id != ctx.org_id:
        raise NotFoundError("Client not found.")
    session = EmailFillSession(
        org_id=ctx.org_id, user_id=ctx.user_id, chat_session_id=chat_session_id,
        lead_id=lead_id, template_id=template.id, contact_id=contact_id,
        to_address=to_address, cc=list(cc or []),
        tags_json=[dict(t) for t in template.tags_json or []], asked_json=[],
        status=EmailFillStatus.ASKING)
    if _needs_document(template):
        document = await built_document_for(db, ctx, template, lead_id)
        if document is None:
            session.status = EmailFillStatus.WAITING_FOR_DOCUMENT
            db.add(session)
            await db.commit()
            return session
        _link(session, document)
    # The model is called before the row is added, so no write transaction is
    # held open across it (SQLite blocks every other writer meanwhile).
    await _first_pass(db, ctx, session, template)
    db.add(session)
    await db.flush()
    if not open_questions(session, limit=None):
        await draft(db, ctx, session)
    await db.commit()
    return session


async def resume(db: AsyncSession, ctx: OrgContext,
                 session: EmailFillSession) -> EmailFillSession:
    """A session waiting for its proposal or MOU carries on once one exists."""
    if session.status != EmailFillStatus.WAITING_FOR_DOCUMENT:
        return session
    template = await _template_of(db, ctx, session)
    document = await built_document_for(db, ctx, template, session.lead_id)
    if document is None:
        return session
    _link(session, document)
    await _first_pass(db, ctx, session, template)
    if not open_questions(session, limit=None):
        await draft(db, ctx, session)
    await db.commit()
    return session


async def apply_answers(db: AsyncSession, ctx: OrgContext, session: EmailFillSession,
                        reply: str) -> EmailFillSession:
    if session.status != EmailFillStatus.ASKING:
        raise ValidationFailedError("That email is not waiting for any answers.")
    outstanding = open_questions(session, limit=None)
    if not outstanding:
        return session
    resolutions = await docx_tagfill.answer_round(
        ctx, dossier=session.dossier_json, open_questions=outstanding,
        user_reply=reply, asked=session.asked_json,
        on_screen=open_questions(session), today=await _today(db, ctx),
        document="email")
    session.asked_json = list(session.asked_json or []) + [{
        "round": len(session.asked_json or []) + 1, "reply": reply,
        "asked": [q["tag_id"] for q in outstanding], "at": utcnow().isoformat()}]
    _record(session, resolutions)
    if not open_questions(session, limit=None):
        await draft(db, ctx, session)
    await db.commit()
    return session


async def apply_change(db: AsyncSession, ctx: OrgContext, session: EmailFillSession,
                       change: str) -> EmailFillSession:
    """Change a drafted email that is still waiting for approval, and redraft
    the SAME message. Approved or sent is final: a change is a new email."""
    message = (await db.get(OutboundMessage, session.message_id)
               if session.message_id else None)
    if message is None:
        raise ValidationFailedError(
            "That email has not been drafted yet, so there is nothing to change.")
    if message.status not in _LIVE:
        raise ValidationFailedError(ALREADY_APPROVED)
    changed = await docx_tagfill.revise(
        ctx, dossier=session.dossier_json, resolutions=session.tags_json,
        correction=change, document="email")
    if not changed:
        raise ValidationFailedError(NOT_UNDERSTOOD)
    session.asked_json = list(session.asked_json or []) + [{
        "round": len(session.asked_json or []) + 1, "correction": change,
        "at": utcnow().isoformat()}]
    _record(session, changed)
    if open_questions(session, limit=None):
        # A change that named a choice the tag does not offer reopens it.
        session.status = EmailFillStatus.ASKING
    else:
        await draft(db, ctx, session)
    await db.commit()
    return session


async def abandon(db: AsyncSession, session: EmailFillSession) -> None:
    session.status = EmailFillStatus.ABANDONED
    await db.commit()


async def find_for_chat(db: AsyncSession, ctx: OrgContext,
                        chat_session_id: str | None, *,
                        statuses: tuple[str, ...]) -> EmailFillSession | None:
    """This person's latest email in this chat with one of `statuses`. A chat
    with no id matches nothing: a one-off command must not answer somebody's
    half-finished email. Untouched for a week means abandoned, not resumed."""
    if not chat_session_id:
        return None
    row = (await db.execute(select(EmailFillSession).where(
        EmailFillSession.org_id == ctx.org_id,
        EmailFillSession.user_id == ctx.user_id,
        EmailFillSession.chat_session_id == chat_session_id,
        EmailFillSession.status.in_(statuses),
    ).order_by(EmailFillSession.updated_at.desc()))).scalars().first()
    if row is None:
        return None
    if row.updated_at < utcnow() - timedelta(days=SESSION_TTL_DAYS):
        logger.info("Abandoning email fill %s: untouched since %s", row.id,
                    row.updated_at)
        await abandon(db, row)
        return None
    return row


# --- the draft ---------------------------------------------------------------


def _readable(org_id: str, path: str | None, filename: str) -> None:
    try:
        if path and storage.read_bytes(org_id, path):
            return
    except Exception:  # noqa: BLE001 -- any failure means the file is not there
        pass
    raise ValidationFailedError(
        f"The file {filename} that this email sends is missing, so nothing was "
        "drafted. Ask an admin to upload it again on the dashboard.")


async def _built_attachment(db: AsyncSession, ctx: OrgContext,
                            session: EmailFillSession) -> dict[str, str] | None:
    if session.proposal_id:
        proposal = await db.get(Proposal, session.proposal_id)
        if proposal is None:
            raise ValidationFailedError(
                "The proposal this email carries is gone, so nothing was drafted.")
        await proposal_email_service.ensure_rendered_files(db, proposal)
        name = f"{proposal_email_service._safe_name(proposal.title)}.pdf"
        _readable(ctx.org_id, proposal.pdf_path, name)
        return {"path": proposal.pdf_path, "filename": name}
    if session.mou_id:
        mou = await db.get(MouDocument, session.mou_id)
        if mou is None:
            raise ValidationFailedError(
                "The MoU this email carries is gone, so nothing was drafted.")
        name = f"{proposal_email_service._safe_name(mou.title)}.pdf"
        if not mou.pdf_path and mou.docx_path:
            mou.pdf_path = storage.save_bytes(
                ctx.org_id, storage.CATEGORY_PROPOSALS, name,
                convert.docx_to_pdf(storage.read_bytes(ctx.org_id, mou.docx_path)))
        _readable(ctx.org_id, mou.pdf_path, name)
        return {"path": mou.pdf_path, "filename": name}
    return None


async def draft(db: AsyncSession, ctx: OrgContext,
                session: EmailFillSession) -> OutboundMessage:
    """Write the values, render the email, and park it for approval.

    The idempotency key is the session's, so a redraft after a change refreshes
    the same pending message (message_service does that for a key it has seen)."""
    template = await _template_of(db, ctx, session)
    source = storage.read_bytes(ctx.org_id, template.source_path)
    values = {t["tag_id"]: str(t.get("value") or "") for t in session.tags_json
              if t.get("outcome") == "filled"}
    result = tagfill.apply_tags(source, session.tags_json, values)
    if result["skipped"]:
        names = ", ".join(str(s.get("raw")) for s in result["skipped"][:6])
        raise ValidationFailedError(
            f"{len(result['skipped'])} blank(s) could not be written into the "
            f"email: {names}. Nothing was drafted. Ask me for the email again.")
    rendered = email_render.render(result["docx"])

    attachments = []
    for att in await email_template_service.attachments_of(db, template.id):
        _readable(ctx.org_id, att.path, att.filename)
        attachments.append({"path": att.path, "filename": att.filename})
    built = await _built_attachment(db, ctx, session)
    if built is not None:
        attachments.append(built)

    message = await message_service.create_message(
        db, ctx, kind=message_kind_for(template),
        channel=MessageChannel.EMAIL.value, to_address=session.to_address,
        cc=list(session.cc or []), subject=rendered.subject[:500],
        body=rendered.text, lead_id=session.lead_id, contact_id=session.contact_id,
        proposal_id=session.proposal_id, attachments=attachments,
        idempotency_key=f"email-fill-{session.id}")
    session.html_body = rendered.html
    session.message_id = message.id
    session.status = EmailFillStatus.DRAFTED
    await db.flush()
    return message


# --- sending -----------------------------------------------------------------


async def html_for_message(db: AsyncSession, org_id: str,
                           message_id: str) -> str | None:
    return (await db.execute(select(EmailFillSession.html_body).where(
        EmailFillSession.org_id == org_id,
        EmailFillSession.message_id == message_id,
    ).order_by(EmailFillSession.updated_at.desc()))).scalars().first()


async def after_sent(db: AsyncSession, message: OutboundMessage) -> None:
    """An MOU that went out with a template email is the client's now."""
    session = (await db.execute(select(EmailFillSession).where(
        EmailFillSession.org_id == message.org_id,
        EmailFillSession.message_id == message.id,
        EmailFillSession.mou_id.isnot(None),
    ))).scalars().first()
    if session is None:
        return
    mou = await db.get(MouDocument, session.mou_id)
    if mou is not None and mou.status != MouStatus.SENT:
        mou.status = MouStatus.SENT
        mou.sent_at = utcnow()
        mou.sent_message_id = message.id
