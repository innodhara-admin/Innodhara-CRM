"""Communication Engine — drafts every outward message using templates,
project context, thread history and stakeholder preferences; runs the
coverage check; never invents numbers; every draft goes to the Approval
Engine — never straight to the school (30-Workflows §4 engine 5).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ApprovalEntityType,
    DecisionType,
    MessageChannel,
    MessageStatus,
    Role,
    ThreadStatus,
)
from app.engines import document_engine, nlu
from app.engines.common import get_org_settings, get_user, record_decision
from app.engines.worktime import next_working_moment
from app.models.base import utcnow
from app.models.comms import Approval, Thread
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.project import Project, Stakeholder
from app.models.user import User

logger = logging.getLogger(__name__)

ENGINE = "communication"


# ─────────────────────────────────────────────────────────────────────────────
# Threads
# ─────────────────────────────────────────────────────────────────────────────


async def ensure_thread(
    db: AsyncSession,
    *,
    org_id: str,
    lead_id: str,
    contact_id: str,
    channel: str,
    project_id: str | None = None,
    stakeholder_id: str | None = None,
    subject: str | None = None,
    owner_user_id: str | None = None,
) -> Thread:
    """One conversation per person+channel(+project). Pre-project threads gain
    project_id when a project is born — history intact (Data Model §8.1)."""
    stmt = select(Thread).where(
        Thread.org_id == org_id,
        Thread.contact_id == contact_id,
        Thread.channel == channel,
    )
    if project_id:
        stmt = stmt.where(
            (Thread.project_id == project_id) | (Thread.project_id.is_(None))
        )
    thread = (await db.execute(stmt.order_by(Thread.created_at))).scalars().first()
    if thread is not None:
        if project_id and not thread.project_id:
            thread.project_id = project_id
            thread.stakeholder_id = stakeholder_id
        if owner_user_id and not thread.owner_user_id:
            thread.owner_user_id = owner_user_id
        if thread.status == ThreadStatus.DORMANT.value:
            thread.status = ThreadStatus.OPEN.value
        return thread
    thread = Thread(
        org_id=org_id,
        lead_id=lead_id,
        project_id=project_id,
        contact_id=contact_id,
        stakeholder_id=stakeholder_id,
        channel=channel,
        subject=subject,
        status=ThreadStatus.OPEN.value,
        owner_user_id=owner_user_id,
    )
    db.add(thread)
    await db.flush()
    return thread


async def pick_sender(
    db: AsyncSession, *, org_id: str, thread: Thread | None, project: Project | None
) -> User | None:
    """The sender is the face the school knows — picked by thread history,
    then the project's sales owner, then the lead's owner (Workflow 3.6)."""
    if thread is not None:
        top = (
            await db.execute(
                select(OutboundMessage.sender_user_id, func.count(OutboundMessage.id))
                .where(
                    OutboundMessage.org_id == org_id,
                    OutboundMessage.thread_id == thread.id,
                )
                .group_by(OutboundMessage.sender_user_id)
                .order_by(func.count(OutboundMessage.id).desc())
            )
        ).first()
        if top and top[0]:
            user = await get_user(db, org_id, top[0])
            if user is not None and user.is_active:
                return user
        if thread.owner_user_id:
            user = await get_user(db, org_id, thread.owner_user_id)
            if user is not None and user.is_active:
                return user
    if project is not None and project.sales_owner_id:
        user = await get_user(db, org_id, project.sales_owner_id)
        if user is not None and user.is_active:
            return user
    if thread is not None:
        lead = (
            await db.execute(select(Lead).where(Lead.id == thread.lead_id))
        ).scalar_one_or_none()
        if lead is not None and lead.owner_id:
            return await get_user(db, org_id, lead.owner_id)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────────────────────


_SUBJECT_LINE = re.compile(r"^[ \t]*subject[ \t]*:[ \t]*(?P<value>[^\n]*)\n+", re.IGNORECASE)


def split_leading_subject(body: str, subject: str | None) -> tuple[str, str | None]:
    """Lift a `Subject:` line out of a message body into the subject field (F44).

    The model reliably writes a good subject and reliably puts it in the wrong
    place. Every pending draft on the system carried one — three for three — and
    nothing ever stripped it, so an approved reply would reach the client with
    **no subject** and a body opening `Subject: Re: Content Change Request`.

    The two halves of that bug look straight at each other: the subject exists,
    in the body; the subject field is empty. So this promotes rather than
    discards — the model's own words end up in the field they were meant for.

    Only a *leading* line counts. A "Subject:" appearing mid-body is prose (a
    person quoting an email), and rewriting that would be a new defect.
    """
    if not body:
        return body, subject
    match = _SUBJECT_LINE.match(body)
    if match is None:
        return body, subject
    value = match.group("value").strip()
    remainder = body[match.end():].lstrip("\n")
    # A malformed header is stripped even when we cannot use it: a body that
    # opens "Subject: …" is wrong for a message that already has a subject.
    return remainder, (subject or value or None)


async def compose_body(
    *,
    org_id: str,
    purpose: str,
    contact_name: str,
    sender_name: str,
    org_name: str,
    facts: dict[str, Any],
    instruction: str | None = None,
    language: str = "english",
    channel: str = "email",
) -> str:
    """Draft the message text. Uses ONLY the facts given — never invents."""
    if nlu.llm_available():
        try:
            from app.ai.llm import get_model_layer

            resp = await get_model_layer().generate(
                purpose=f"communication.{purpose}",
                org_id=org_id,
                system=(
                    # Finding F11 / same class as F4: naming an industry here
                    # makes the model write in that industry's vocabulary
                    # whatever the client actually is.
                    "You draft messages on behalf of an organisation to its "
                    f"clients. Channel: {channel}. Language: {language}. Warm, "
                    "brief, factual. Use ONLY the facts provided — never invent "
                    "numbers, dates or promises, and never assume an industry "
                    "or type of organisation that the facts do not state. "
                    "Sign with the sender's name."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Purpose: {purpose}\nTo: {contact_name}\n"
                        f"From: {sender_name} ({org_name})\n"
                        + (f"Instruction: {instruction}\n" if instruction else "")
                        + "Facts:\n"
                        + "\n".join(f"- {k}: {v}" for k, v in facts.items())
                    ),
                }],
            )
            if resp.text.strip():
                return resp.text.strip()
        except Exception:  # noqa: BLE001
            logger.exception("LLM draft failed; using deterministic composition")

    lines = [f"Dear {contact_name},", ""]
    if instruction:
        lines += [instruction, ""]
    for key, value in facts.items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, list):
            lines += [f"{label}:"] + [f"  • {v}" for v in value] + [""]
        else:
            lines.append(f"{label}: {value}")
    lines += ["", f"Warm regards,", f"{sender_name}", org_name]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# The one drafting entry point
# ─────────────────────────────────────────────────────────────────────────────


async def draft_client_message(
    db: AsyncSession,
    *,
    org_id: str,
    kind: str,
    purpose: str,
    lead_id: str,
    contact: Contact,
    facts: dict[str, Any],
    project: Project | None = None,
    stakeholder: Stakeholder | None = None,
    channel: str | None = None,
    subject: str | None = None,
    instruction: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    cc: list[str] | None = None,
    triggered_by: str = "manual",
    sender: User | None = None,
    urgent: bool = False,
    extracted_points: list[dict[str, Any]] | None = None,
    request_approval: bool = True,
    approval_facts: dict[str, Any] | None = None,
) -> tuple[OutboundMessage | None, Approval | None, list[dict[str, Any]]]:
    """Draft one outward message, honouring every stakeholder preference and
    org courtesy rule, then hand it to the Approval Engine.

    Returns (message, approval, uncovered_points). message is None whenever
    drafting stopped, which happens on four paths — do_not_contact, the contact
    having no address at all, needs_review, and no resolvable sender. **Every one
    of them writes an `ai_decisions` row** (F50: two of the four used to return
    silently, so a client update could vanish with no trace anywhere). Callers
    are therefore free to discard the return value: the refusal is already on the
    record without their help. Eleven of the sixteen call sites do exactly that.
    """
    org = await get_org_settings(db, org_id)

    # Absolute stop. "The person asked to stop" holds even when the draft has
    # no project context: ANY current do_not_contact stakeholder row for this
    # contact refuses the draft.
    blocked = stakeholder is not None and stakeholder.do_not_contact
    if not blocked and stakeholder is None:
        from app.models.project import Stakeholder as _Stakeholder

        blocked = (
            await db.execute(
                select(_Stakeholder).where(
                    _Stakeholder.org_id == org_id,
                    _Stakeholder.contact_id == contact.id,
                    _Stakeholder.do_not_contact.is_(True),
                )
            )
        ).scalars().first() is not None
    if blocked:
        await record_decision(
            db, org_id=org_id, project_id=project.id if project else None,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine=ENGINE,
            decision="Draft refused", confidence=1.0,
            reason=f"{contact.name} has do_not_contact set — nothing may be drafted to them",
        )
        return None, None, []

    # Channel: explicit > stakeholder preference > email.
    channel = channel or (stakeholder.preferred_channel if stakeholder else None) or "email"
    if channel == "call":  # a call is a task, not a message
        channel = MessageChannel.WHATSAPP.value
    to_address = contact.email if channel == MessageChannel.EMAIL.value else contact.phone
    if not to_address:
        # fall back to whichever address exists
        channel = (
            MessageChannel.EMAIL.value if contact.email else MessageChannel.WHATSAPP.value
        )
        to_address = contact.email or contact.phone
    if not to_address:
        # F50: refusing to invent an address is correct — being SILENT about it
        # is not. This branch dropped a client update with no draft, no approval,
        # no decision row and no log line. Data Model §5.5: one row = one decision
        # an engine took, and `needs_human` = "the engine stopped and routed to a
        # person". Same shape as the do_not_contact / needs_review branches above.
        await record_decision(
            db, org_id=org_id, project_id=project.id if project else None,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine=ENGINE,
            decision="Client message not drafted", needs_human=True, confidence=1.0,
            reason=(
                f"{contact.name} has no email address and no phone number on record, "
                f"so there is nowhere to send \"{purpose}\". Add a contact address to "
                f"reach them."
            ),
            input_summary=f"kind={kind}, purpose={purpose}, contact={contact.name}",
            entity_type="contact", entity_id=contact.id,
        )
        return None, None, []
    if contact.needs_review:
        # Nothing is ever sent to an unverified address (Workflow 2).
        await record_decision(
            db, org_id=org_id, project_id=project.id if project else None,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine=ENGINE,
            decision="Draft held", needs_human=True, confidence=0.5,
            reason=f"Contact {contact.name} is flagged needs_review — held until verified",
        )
        return None, None, []

    thread = await ensure_thread(
        db, org_id=org_id, lead_id=lead_id, contact_id=contact.id,
        channel=channel, project_id=project.id if project else None,
        stakeholder_id=stakeholder.id if stakeholder else None,
        subject=subject,
        owner_user_id=sender.id if sender else None,
    )
    if sender is None:
        sender = await pick_sender(db, org_id=org_id, thread=thread, project=project)
    if sender is None:
        # F50, second silent branch: nobody can be found to send AS. Same rule —
        # stopping is fine, stopping invisibly is not.
        await record_decision(
            db, org_id=org_id, project_id=project.id if project else None,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine=ENGINE,
            decision="Client message not drafted", needs_human=True, confidence=1.0,
            reason=(
                f"No sender could be resolved for this thread, so \"{purpose}\" was "
                f"not drafted to {contact.name}. Assign an owner to the project or "
                f"the thread."
            ),
            input_summary=f"kind={kind}, purpose={purpose}, contact={contact.name}",
            entity_type="contact", entity_id=contact.id,
        )
        return None, None, []

    from app.models.organisation import Organisation

    org_row = (
        await db.execute(select(Organisation).where(Organisation.id == org_id))
    ).scalar_one_or_none()
    body = await compose_body(
        org_id=org_id, purpose=purpose,
        contact_name=contact.name, sender_name=sender.name,
        org_name=org_row.name if org_row else "",
        facts=facts, instruction=instruction,
        language=(stakeholder.preferred_language if stakeholder else "english"),
        channel=channel,
    )
    # F44: the model puts its subject in the body. Promote it into the field it
    # belongs in — which also fills the subject replies never had.
    body, subject = split_leading_subject(body, subject)

    # Coverage check: the reply must answer every extracted point, or say why not.
    uncovered = document_engine.coverage_check(body, extracted_points or [])
    if uncovered:
        await record_decision(
            db, org_id=org_id, project_id=project.id if project else None,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine=ENGINE,
            decision="Coverage gap flagged", needs_human=True, confidence=0.5,
            reason="Draft does not clearly address: "
            + "; ".join(str(p.get("detail") or p.get("type")) for p in uncovered),
        )

    # Working-hours scheduling + weekly pacing cap per stakeholder.
    now = utcnow()
    scheduled = now if urgent else next_working_moment(now, org)
    week_ago = now - timedelta(days=7)
    sent_this_week = (
        await db.execute(
            select(func.count(OutboundMessage.id)).where(
                OutboundMessage.org_id == org_id,
                OutboundMessage.contact_id == contact.id,
                OutboundMessage.created_at >= week_ago,
                OutboundMessage.status.notin_(
                    [MessageStatus.REJECTED.value, MessageStatus.DEAD_LETTER.value]
                ),
            )
        )
    ).scalar_one()
    if not urgent and sent_this_week >= (org.max_client_messages_per_week or 3):
        scheduled = max(scheduled, now + timedelta(days=7 - min(6, sent_this_week)))
        await record_decision(
            db, org_id=org_id, project_id=project.id if project else None,
            decision_type=DecisionType.DRAFT_MESSAGE.value, engine=ENGINE,
            decision="Send deferred by courtesy cap", confidence=1.0,
            reason=(
                f"{contact.name} already received {sent_this_week} messages this "
                f"week (cap {org.max_client_messages_per_week}); send scheduled later"
            ),
        )

    message = OutboundMessage(
        org_id=org_id,
        kind=kind,
        channel=channel,
        status=MessageStatus.PENDING_APPROVAL.value,
        lead_id=lead_id,
        contact_id=contact.id,
        project_id=project.id if project else None,
        thread_id=thread.id,
        sender_user_id=sender.id,
        to_address=to_address,
        cc=cc or [],
        subject=subject if channel == MessageChannel.EMAIL.value else None,
        body=body,
        attachments=attachments or [],
        idempotency_key=uuid4().hex,
        triggered_by=triggered_by,
        scheduled_send_at=scheduled,
    )
    db.add(message)
    await db.flush()

    approval = None
    if request_approval:
        from app.engines import approval_engine

        facts_for_rule = {
            "kind": kind,
            "channel": channel,
            "sender_user_id": sender.id,
            "thread_owner_user_id": thread.owner_user_id or sender.id,
            "sender_is_thread_owner": (thread.owner_user_id or sender.id) == sender.id,
            "urgent": urgent,
        }
        facts_for_rule.update(approval_facts or {})
        approval = await approval_engine.request_approval(
            db, org_id=org_id,
            entity_type=ApprovalEntityType.OUTBOUND_MESSAGE.value,
            entity_id=message.id,
            project_id=project.id if project else None,
            facts=facts_for_rule,
            reason=(
                f"{kind.replace('_', ' ').capitalize()} to {contact.name} "
                f"({channel}) — {purpose}"
            ),
            default_approver_role=Role.SALES_LEAD.value,
        )
    return message, approval, uncovered


async def redraft_rejected(
    db: AsyncSession, *, org_id: str, message: OutboundMessage, instruction: str
) -> OutboundMessage:
    """A rejection with a note loops the draft back — the note becomes the
    instruction (Workflow 26 rejection loop)."""
    if message.kind == "meeting_invite":
        # A meeting invite is rebuilt, not copied: the reason may move the
        # meeting or change who is invited, and its calendar attachment and
        # styled body must carry the new details (a copied html_body would
        # show the client the OLD text). No reason: closed, not redrafted.
        from app.services import meeting_invite_service

        return await meeting_invite_service.after_rejection(
            db, org_id=org_id, message=message, reason=instruction,
        )
    contact = (
        await db.execute(
            select(Contact).where(Contact.org_id == org_id, Contact.id == message.contact_id)
        )
    ).scalar_one_or_none()
    body = message.body
    if instruction:
        if nlu.llm_available():
            # F69: the redraft used to be handed `{"original_draft": ...}` and
            # nothing else — no sender, no org, no project, no demo. So a
            # rejection note that asks for a FACT ("add the demo date too")
            # could not be obeyed: the model had the email in front of it and
            # no way to look anything up, and the best it could do was ask the
            # CLIENT to confirm a date we had already scheduled and told them.
            #
            # Not a hallucination — the honest failure of a blind path. But the
            # first draft is built with rich `facts`, the sender's real name,
            # the org name and the stakeholder's language; the redraft threw all
            # four away and re-derived nothing. The fix is symmetry.
            facts: dict[str, Any] = {"original_draft": message.body}
            sender_name = ""
            org_name = ""

            from app.models.organisation import Organisation
            from app.models.user import User

            if message.sender_user_id:
                sender_row = (
                    await db.execute(
                        select(User).where(User.id == message.sender_user_id)
                    )
                ).scalar_one_or_none()
                if sender_row is not None:
                    sender_name = sender_row.name or ""
            org_row = (
                await db.execute(select(Organisation).where(Organisation.id == org_id))
            ).scalar_one_or_none()
            if org_row is not None:
                org_name = org_row.name or ""

            if message.lead_id:
                from app.models.demo import Demo

                demos = (
                    await db.execute(
                        select(Demo)
                        .where(
                            Demo.org_id == org_id,
                            Demo.lead_id == message.lead_id,
                            Demo.status == "scheduled",
                        )
                        .order_by(Demo.scheduled_date)
                    )
                ).scalars().all()
                if demos:
                    # Stated, never implied: the model may only repeat a date it
                    # is given here. Nothing scheduled means no line, so it
                    # still cannot invent one.
                    facts["scheduled_demos"] = [
                        {
                            "date": d.scheduled_date.isoformat(),
                            "time": d.scheduled_time or "time not set",
                        }
                        for d in demos
                    ]
            if message.project_id:
                from app.models.project import Project

                project_row = (
                    await db.execute(
                        select(Project).where(
                            Project.id == message.project_id, Project.org_id == org_id
                        )
                    )
                ).scalar_one_or_none()
                if project_row is not None:
                    facts["project_name"] = project_row.name
                    if project_row.objective:
                        facts["project_objective"] = project_row.objective

            # The model applies the note as an editing instruction — any
            # phrasing works ("softer tone", "drop the second paragraph",
            # "change 'kids' to 'students'", "add the demo date too").
            body = await compose_body(
                org_id=org_id, purpose="redraft",
                contact_name=contact.name if contact else "",
                sender_name=sender_name, org_name=org_name,
                facts=facts,
                instruction=instruction,
                channel=message.channel,
            )
        else:
            # Stub-provider path: honour simple word-replacement notes
            # ("change 'kids' to 'students'"), else prepend the correction.
            import re

            m = re.search(r"change\s+'([^']+)'\s+to\s+'([^']+)'", instruction, re.IGNORECASE)
            if not m:
                m = re.search(r'change\s+"([^"]+)"\s+to\s+"([^"]+)"', instruction, re.IGNORECASE)
            if m:
                body = body.replace(m.group(1), m.group(2))
    # F44: same treatment on the redraft path, where this was first seen — a
    # rejected intro came back with "Subject: Updated contact email" as its
    # opening line while the real subject was unchanged.
    body, redraft_subject = split_leading_subject(body, message.subject)
    redraft = OutboundMessage(
        org_id=org_id,
        kind=message.kind,
        channel=message.channel,
        status=MessageStatus.PENDING_APPROVAL.value,
        lead_id=message.lead_id,
        contact_id=message.contact_id,
        project_id=message.project_id,
        thread_id=message.thread_id,
        sender_user_id=message.sender_user_id,
        to_address=message.to_address,
        cc=list(message.cc or []),
        bcc=list(message.bcc or []),
        subject=redraft_subject,
        body=body,
        attachments=list(message.attachments or []),
        idempotency_key=uuid4().hex,
        triggered_by=message.triggered_by,
        scheduled_send_at=message.scheduled_send_at,
    )
    db.add(redraft)
    await db.flush()

    from app.engines import approval_engine

    await approval_engine.request_approval(
        db, org_id=org_id,
        entity_type=ApprovalEntityType.OUTBOUND_MESSAGE.value,
        entity_id=redraft.id,
        project_id=message.project_id,
        facts={"kind": redraft.kind, "channel": redraft.channel, "redraft": True},
        reason=f"Redraft after rejection — note applied: {instruction or '—'}",
        default_approver_role=Role.SALES_LEAD.value,
    )
    return redraft
