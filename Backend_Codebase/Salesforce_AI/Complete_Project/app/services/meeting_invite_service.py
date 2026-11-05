"""Meetings arranged with a client, and their invite emails.

Customer ask, 21 Sep 2026: a meeting path completely separate from demos.

* `schedule` records a ScheduledMeeting, puts a task with the date and time in
  the organiser's list, mirrors it to Google Calendar when that is set up, and
  drafts the invite. Used by the app, by Jarvis and by the recording pipeline
  (`schedule_from_recording`).
* The invite is an OutboundMessage of kind "meeting_invite": to the client's
  primary contact, cc / bcc as asked, a body written from the context, the
  org's Google Meet room, and a calendar attachment — the same shape as a demo
  invite. It waits in Approvals; nothing is sent without a human tap.
* `after_rejection` is the loop: a rejection WITH a reason reads the reason
  (it may move the meeting or change who is copied), rebuilds the invite from
  it and files it for approval again; a rejection with no reason just closes
  it. Rebuilt rather than copied, because a copied attachment would carry the
  old time and a copied styled body would show the client the old text.

Anyone who can see clients may arrange a meeting (`view_leads`); demos stay
with the roles that hold `schedule_demos`.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.context import OrgContext
from app.core.exceptions import ConflictError, PermissionDeniedError, ValidationFailedError
from app.core.permissions import has_permission
from app.models.action_item import ActionItem
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.organisation import Organisation, OrgSettings
from app.models.scheduled_meeting import ScheduledMeeting
from app.models.user import User
from app.services import audit_service, calendar_service, ics_service, message_service

logger = logging.getLogger(__name__)

KIND = "meeting_invite"
DEFAULT_DURATION = 30
MAX_DURATION = 8 * 60
_KEY_PREFIX = "meeting-invite:"
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def may_schedule(role: str) -> bool:
    return has_permission(role, "view_leads")


_MEETING_ITSELF = re.compile(
    r"\b(invite|invitation|calendar|attend|join|meeting|video call|call)\b", re.IGNORECASE)
_INVITE_WORDS = re.compile(r"\b(invite|invitation|calendar)\b", re.IGNORECASE)
_PREPARATION = re.compile(r"\b(prepare|print|draft|review|share|send the|bring|collect)\b",
                          re.IGNORECASE)


def is_only_the_meeting(title: str) -> bool:
    """A to-do that is only the scheduled meeting or its invite — "Send
    calendar invite for Monday meeting", "Attend the follow-up meeting",
    "Prepare calendar invite" — which the meeting's own task and drafted
    invite already cover. Not "Print the brochure for the meeting".
    Seen on the first real upload (Risabh Public School, 23 Sep 2026), from
    both the extraction and, later, the Planner."""
    if _INVITE_WORDS.search(title):
        return True
    return bool(_MEETING_ITSELF.search(title)) and not _PREPARATION.search(title)


def normalise_time(value: str | None) -> str | None:
    """"9:00" → "09:00"; None stays None; anything else is refused."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d:\d\d", text):
        text = "0" + text
    if not _TIME.fullmatch(text):
        raise ValidationFailedError(f"Time must be HH:MM (24-hour), got '{value}'")
    return text


def _clean_addresses(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = (value or "").strip()
        if not _EMAIL.fullmatch(text):
            raise ValidationFailedError(f"'{value}' is not an email address")
        if text.lower() not in {a.lower() for a in out}:
            out.append(text)
    return out


def when_text(meeting: ScheduledMeeting) -> str:
    day = meeting.meeting_date.strftime("%A, %d %B %Y")
    return f"{day} at {meeting.start_time}" if meeting.start_time else day


def _task_title(client: str, meeting: ScheduledMeeting) -> str:
    day = meeting.meeting_date.strftime("%a %d %b")
    at = f" at {meeting.start_time}" if meeting.start_time else " (time to be agreed)"
    return f"Meeting with {client} on {day}{at}"


def _task_due(meeting: ScheduledMeeting) -> datetime:
    d = meeting.meeting_date
    if meeting.start_time:
        hour, minute = (int(x) for x in meeting.start_time.split(":"))
        return datetime(d.year, d.month, d.day, hour, minute)
    return datetime(d.year, d.month, d.day)


async def _org_settings(db: AsyncSession, org_id: str) -> OrgSettings | None:
    return (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    ).scalar_one_or_none()


async def _meet_link(db: AsyncSession, org_id: str) -> str | None:
    """The org's one reusable Meet room (decided 23 Sep 2026: shared room for
    now, not a fresh link per meeting) — the same source demos use."""
    row = await _org_settings(db, org_id)
    integ = (row.calendar_integration if row else None) or {}
    return integ.get("meet_link") or get_settings().google_meet_link or None


async def _primary_contact(db: AsyncSession, lead: Lead) -> Contact | None:
    contacts = (
        await db.execute(
            select(Contact).where(
                Contact.lead_id == lead.id, Contact.org_id == lead.org_id,
                Contact.email.is_not(None),
            ).order_by(Contact.created_at)
        )
    ).scalars().all()
    contacts = [c for c in contacts if c.email]
    if not contacts:
        return None
    return next((c for c in contacts if c.is_primary), contacts[0])


async def _ctx_for(db: AsyncSession, org_id: str, user_id: str) -> OrgContext:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    return OrgContext(org_id=org_id, user_id=user.id, role=user.role,
                      email=user.email, name=user.name or "")


# ── the body, written from the context ───────────────────────────────────

_BODY_SYSTEM = (
    "You write a short meeting invitation email on behalf of an organisation to "
    "a person at its client. Warm, brief, factual. Use ONLY the facts given: "
    "never invent dates, times, names, numbers, agenda points or promises, and "
    "never assume an industry or type of organisation the facts do not state. "
    "State the day and time exactly as given. If a video link is given, include "
    "it once. Mention that a calendar invitation is attached. No subject line. "
    "Plain text only: no markdown, no asterisks, no bullet symbols. "
    "The email is addressed to the person in contact_name, whose role is "
    "contact_role: write to them as 'you' and to their colleagues as 'your "
    "...'. The purpose may be worded from our side ('with the director and "
    "their coordinator'); reword it for the reader, and never describe the "
    "reader in the third person. "
    "The meeting is between our_organisation (us, the sender) and "
    "reader_organisation (the reader's own organisation): it is a meeting "
    "with us, never 'with' the reader's own organisation. "
    "Sign with the sender's name."
)


def plain_text(text: str) -> str:
    """Email bodies are plain text. Live test, 23 Sep 2026: the model wrote
    "**Friday, 02 October**" and the client would have seen the asterisks."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", text)
    return text


def _template_body(facts: dict[str, Any], sender_name: str) -> str:
    lines = [f"Dear {facts.get('contact_name') or 'Sir/Madam'},", ""]
    if facts.get("change") == "rescheduled":
        lines.append(f"Our meeting has moved to {facts['when']} ({facts['duration']}).")
    else:
        lines.append(f"I would like to invite you to a meeting on {facts['when']} "
                     f"({facts['duration']}).")
    if facts.get("purpose"):
        lines += ["", f"Purpose: {facts['purpose']}"]
    if facts.get("meet_link"):
        lines += ["", f"Join the video call: {facts['meet_link']}"]
    lines += ["", "The attached calendar invitation adds it to your calendar.",
              "", "Warm regards,", sender_name]
    return "\n".join(lines)


async def _write_body(
    *, org_id: str, facts: dict[str, Any], instruction: str | None = None,
    sender_name: str, org_name: str,
) -> str:
    """The invite text. A model writes it when one is configured; the template
    is the honest fallback (it never invents anything either)."""
    from app.engines import nlu

    if nlu.llm_available():
        try:
            from app.ai.llm import get_model_layer

            content = (
                f"From: {sender_name} ({org_name})\n"
                + (f"Change requested by the approver — apply it: {instruction}\n"
                   if instruction else "")
                + "Facts:\n"
                + "\n".join(f"- {k}: {v}" for k, v in facts.items() if v)
            )
            resp = await get_model_layer().generate(
                purpose="communication.meeting_invite", org_id=org_id,
                system=_BODY_SYSTEM, messages=[{"role": "user", "content": content}],
            )
            text = plain_text((resp.text or "").strip())
            if text:
                return text
        except Exception:  # noqa: BLE001 — a drafting failure must not lose the meeting
            logger.exception("Meeting invite body: model failed; using the template")
    return _template_body(facts, sender_name)


# ── reading a rejection reason ───────────────────────────────────────────

_REJECTION_PROMPT = """An approver rejected a meeting invitation email and wrote
why. Work out which meeting details the reason changes. Today is {today}.

The meeting now: {meeting}

Reason: "{reason}"

Return JSON with only the keys the reason actually changes:
  "date": "YYYY-MM-DD", "time": "HH:MM" (24-hour), "duration_minutes": number,
  "add_cc": [emails], "remove_cc": [emails], "add_bcc": [emails],
  "remove_bcc": [emails].
Wording changes ("warmer", "shorter", "mention the fees") change no detail:
return {{}} for those. Never invent an email address that is not in the reason."""

_REJECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"}, "time": {"type": "string"},
        "duration_minutes": {"type": "integer"},
        "add_cc": {"type": "array", "items": {"type": "string"}},
        "remove_cc": {"type": "array", "items": {"type": "string"}},
        "add_bcc": {"type": "array", "items": {"type": "string"}},
        "remove_bcc": {"type": "array", "items": {"type": "string"}},
    },
}

_STRICT_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b|\b(\d{1,2}):(\d{2})\b",
                          re.IGNORECASE)


def _fallback_changes(reason: str) -> dict[str, Any]:
    """Without a model: a clock time written as one ("4 pm", "16:30") and any
    email addresses, bcc'd when the reason says bcc. Nothing else is guessed."""
    out: dict[str, Any] = {}
    m = _STRICT_TIME.search(reason)
    if m:
        if m.group(4):
            hour, minute = int(m.group(4)), int(m.group(5))
        else:
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            pm = m.group(3).lower().startswith("p")
            hour = (hour % 12) + (12 if pm else 0)
        if hour < 24 and minute < 60:
            out["time"] = f"{hour:02d}:{minute:02d}"
    emails = _EMAIL.findall(reason)
    if emails:
        out["add_bcc" if re.search(r"\bbcc\b", reason, re.IGNORECASE) else "add_cc"] = emails
    return out


async def _read_rejection(
    *, org_id: str, reason: str, meeting: ScheduledMeeting, today: date,
) -> dict[str, Any]:
    from app.engines import nlu

    if nlu.llm_available():
        try:
            from app.ai.llm import TIER_FAST, get_model_layer

            data = await get_model_layer().generate_json(
                purpose="communication.meeting_invite_rejection", tier=TIER_FAST,
                org_id=org_id,
                messages=[{"role": "user", "content": _REJECTION_PROMPT.format(
                    today=today.isoformat(), reason=reason[:1000],
                    meeting=(f"{meeting.meeting_date.isoformat()} at "
                             f"{meeting.start_time or 'no time set'}, "
                             f"{meeting.duration_minutes} minutes, cc {meeting.cc or []}, "
                             f"bcc {meeting.bcc or []}"),
                )}],
                json_schema=_REJECTION_SCHEMA, temperature=0.0, max_tokens=300,
            )
            if isinstance(data, dict):
                return data
        except Exception:  # noqa: BLE001
            logger.exception("Could not read the rejection reason; using the fallback")
    return _fallback_changes(reason)


# ── the invite ───────────────────────────────────────────────────────────

async def compose_invite(
    db: AsyncSession, ctx: OrgContext, *, meeting: ScheduledMeeting, lead: Lead,
    change: str = "scheduled",  # scheduled | rescheduled | updated | cancelled
    instruction: str | None = None, context_summary: str | None = None,
) -> OutboundMessage | None:
    """Draft the invite and file it for approval. None when the client has no
    contact with an email address (the meeting still stands)."""
    contact = await _primary_contact(db, lead)
    if contact is None:
        meeting.invite_status = "no_contact"
        return None
    sender = (await db.execute(select(User).where(User.id == ctx.user_id))).scalar_one_or_none()
    sender_name = (sender.name if sender else None) or "YuviPep"
    sender_email = (sender.email if sender else None) or ctx.email
    org = (await db.execute(select(Organisation).where(Organisation.id == ctx.org_id))
           ).scalar_one_or_none()
    org_name = org.name if org else ""
    meet_link = await _meet_link(db, ctx.org_id)
    cancelled = change == "cancelled"
    when = when_text(meeting)

    sequence = (
        await db.execute(
            select(func.count()).select_from(OutboundMessage).where(
                OutboundMessage.org_id == ctx.org_id,
                OutboundMessage.idempotency_key.like(f"{_KEY_PREFIX}{meeting.id}:%"),
            )
        )
    ).scalar_one()
    # "Updated" / "moved" only make sense to someone who received an earlier
    # version. A draft rejected before sending never reached them, so the next
    # one is still, to the reader, the first invitation (Risabh, 23 Sep 2026:
    # a redraft told the principal "this invite has been updated").
    if change in ("rescheduled", "updated"):
        ever_sent = (
            await db.execute(
                select(func.count()).select_from(OutboundMessage).where(
                    OutboundMessage.org_id == ctx.org_id,
                    OutboundMessage.idempotency_key.like(f"{_KEY_PREFIX}{meeting.id}:%"),
                    OutboundMessage.status.in_(("queued", "sending", "sent", "delivered")),
                )
            )
        ).scalar_one()
        if not ever_sent:
            change = "scheduled"

    if cancelled:
        body = (f"Dear {contact.name},\n\nThe meeting planned for {when} has been "
                f"cancelled. We will be in touch to find a new time.\n\n"
                f"Warm regards,\n{sender_name}")
    else:
        facts: dict[str, Any] = {
            # Named from the reader's side: the reader works at the client, so
            # "a call with <client>" would be a call with their own office.
            "reader_organisation": lead.name,
            "our_organisation": org_name,
            "contact_name": contact.name,
            "contact_role": contact.title,
            "when": when,
            "duration": f"{meeting.duration_minutes} minutes",
            "purpose": meeting.purpose,
            "meet_link": meet_link,
            "change": change,
        }
        if context_summary:
            facts["what_was_discussed"] = context_summary
        body = await _write_body(org_id=ctx.org_id, facts=facts, instruction=instruction,
                                 sender_name=sender_name, org_name=org_name)
        if meet_link and meet_link not in body:
            body += f"\n\nJoin the video call: {meet_link}"

    title = f"Meeting: {lead.name}"
    subject = {
        "cancelled": f"Cancelled: meeting on {when} — {lead.name}",
        "rescheduled": f"Updated: meeting moved to {when} — {lead.name}",
    }.get(change, f"Meeting invitation: {when} — {lead.name}")
    # bcc stays out of the calendar file too: an ICS attendee list is visible.
    staff = [(address, address) for address in (meeting.cc or [])
             if address.lower() not in (contact.email.lower(), sender_email.lower())]
    attendees = [(contact.name, contact.email)] + staff
    description = "\n".join(
        part for part in (
            meeting.purpose,
            f"Join the video call: {meet_link}" if meet_link and not cancelled else None,
        ) if part
    )
    ics_text = ics_service.build_invite(
        uid=f"meeting-{meeting.id}@yuvipep.platform", sequence=sequence, title=title,
        description=description, organizer_name=sender_name, organizer_email=sender_email,
        attendees=attendees, on_date=meeting.meeting_date, time_hhmm=meeting.start_time,
        duration_minutes=meeting.duration_minutes or DEFAULT_DURATION,
        location=meet_link if not cancelled else None, conference_link=meet_link,
        method="CANCEL" if cancelled else "REQUEST",
    )
    html_body = ics_service.build_invite_html(
        title=(f"Cancelled: {title}" if cancelled else title), when_text=when,
        guests=[f"{sender_name} — organizer"] + [f"{n} ({e})" for n, e in attendees],
        meet_link=meet_link if not cancelled else None, message_text=body,
    )
    message = await message_service.create_message(
        db, ctx, kind=KIND, channel="email", to_address=contact.email,
        subject=subject, body=body, cc=[e for _, e in staff], bcc=list(meeting.bcc or []),
        lead_id=lead.id, contact_id=contact.id,
        attachments=[{"ics_text": ics_text, "ics_method": "CANCEL" if cancelled else "REQUEST",
                      "html_body": html_body, "filename": "invite.ics"}],
        idempotency_key=f"{_KEY_PREFIX}{meeting.id}:{sequence}:{change}",
        request_approval=True,
    )
    meeting.invite_message_id = message.id
    meeting.invite_status = "pending_approval"
    return message


# ── clashes (25 Sep 2026) ────────────────────────────────────────────────
# Asked for a meeting at a time already taken, Jarvis booked it anyway. Only
# the organiser's own scheduled meetings count, back to back is fine, and a
# meeting with no start time (a day agreed in a recording) blocks nothing.

def _minutes(hhmm: str) -> int:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return hour * 60 + minute


def _hhmm(minutes: int) -> str:
    minutes = min(minutes, 24 * 60 - 1)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


async def find_clash(
    db: AsyncSession, *, org_id: str, organizer_id: str, on_date: date,
    time_hhmm: str | None, duration_minutes: int | None,
    exclude_id: str | None = None,
) -> str | None:
    """The sentence to say when this slot overlaps one of the organiser's
    own meetings, or None when it is free."""
    if not time_hhmm:
        return None
    start = _minutes(time_hhmm)
    end = start + int(duration_minutes or DEFAULT_DURATION)
    rows = (
        await db.execute(
            select(ScheduledMeeting, Lead.name)
            .join(Lead, Lead.id == ScheduledMeeting.lead_id)
            .where(
                ScheduledMeeting.org_id == org_id,
                ScheduledMeeting.organizer_id == organizer_id,
                ScheduledMeeting.meeting_date == on_date,
                ScheduledMeeting.status == "scheduled",
                ScheduledMeeting.start_time.is_not(None),
            )
            .order_by(ScheduledMeeting.start_time)
        )
    ).all()
    for other, client in rows:
        if other.id == exclude_id:
            continue
        other_start = _minutes(other.start_time)
        other_end = other_start + int(other.duration_minutes or DEFAULT_DURATION)
        if start < other_end and other_start < end:
            day = f"{on_date.strftime('%A')} {on_date.day} {on_date.strftime('%B')}"
            return (f"You already have a meeting with {client} on {day} from "
                    f"{other.start_time} to {_hhmm(other_end)}. You can schedule this "
                    f"one from {_hhmm(other_end)} onwards.")
    return None


# ── scheduling ───────────────────────────────────────────────────────────

async def _calendar_event(db: AsyncSession, meeting: ScheduledMeeting, lead: Lead) -> None:
    row = await _org_settings(db, meeting.org_id)
    integ = row.calendar_integration if row else None
    if meeting.calendar_event_id:
        await calendar_service.delete_event(org_calendar_integration=integ,
                                            event_id=meeting.calendar_event_id)
        meeting.calendar_event_id = None
    if meeting.status == "cancelled":
        return
    event_id = await calendar_service.create_event(
        org_calendar_integration=integ, title=f"Meeting: {lead.name}",
        description=meeting.purpose or "", on_date=meeting.meeting_date,
        time_hhmm=meeting.start_time,
        duration_minutes=meeting.duration_minutes or DEFAULT_DURATION,
    )
    if event_id:
        meeting.calendar_event_id = event_id


async def schedule(
    db: AsyncSession, ctx: OrgContext, *, lead: Lead, on_date: date,
    time_hhmm: str | None, duration_minutes: int | None = None,
    purpose: str | None = None, cc: list[str] | None = None, bcc: list[str] | None = None,
    source: str = "app", recording_meeting_id: str | None = None,
    task_status: str = "open", context_summary: str | None = None,
) -> tuple[ScheduledMeeting, OutboundMessage | None]:
    if not may_schedule(ctx.role):
        raise PermissionDeniedError("Your role cannot arrange client meetings.")
    duration = int(duration_minutes or DEFAULT_DURATION)
    if not 5 <= duration <= MAX_DURATION:
        raise ValidationFailedError("A meeting lasts between 5 minutes and 8 hours.")
    if source != "recording":
        # A time the client agreed on a recording stands even if it clashes;
        # anything a person is choosing now is checked.
        clash = await find_clash(
            db, org_id=ctx.org_id, organizer_id=ctx.user_id, on_date=on_date,
            time_hhmm=normalise_time(time_hhmm), duration_minutes=duration)
        if clash:
            raise ConflictError(clash)
    meeting = ScheduledMeeting(
        org_id=ctx.org_id, lead_id=lead.id, purpose=(purpose or "").strip() or None,
        meeting_date=on_date, start_time=normalise_time(time_hhmm),
        duration_minutes=duration, organizer_id=ctx.user_id,
        cc=_clean_addresses(cc), bcc=_clean_addresses(bcc), source=source,
        recording_meeting_id=recording_meeting_id,
    )
    db.add(meeting)
    await db.flush()

    task = ActionItem(
        org_id=ctx.org_id, lead_id=lead.id, meeting_id=recording_meeting_id,
        title=_task_title(lead.name, meeting)[:490], description=meeting.purpose,
        due_date=_task_due(meeting), assignee_id=ctx.user_id, status=task_status,
        created_by=ctx.user_id if source != "recording" else "system",
    )
    db.add(task)
    await db.flush()
    meeting.action_item_id = task.id

    await _calendar_event(db, meeting, lead)
    invite = await compose_invite(db, ctx, meeting=meeting, lead=lead,
                                  context_summary=context_summary)
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="meeting.scheduled",
        entity_type="scheduled_meeting", entity_id=meeting.id,
        detail={"client": lead.name, "date": on_date.isoformat(),
                "time": meeting.start_time, "source": source},
    )
    return meeting, invite


async def schedule_from_recording(
    db: AsyncSession, *, recording, lead: Lead, agreed: dict[str, Any],
    task_status: str, summary: str | None = None, note: str | None = None,
) -> ScheduledMeeting | None:
    """A recording agreed a meeting: schedule it once, whoever recorded it
    organising. A retried pipeline finds the first one and stops.

    `note` (2 Oct 2026) is said to the people who check the meeting -- on its
    task, which the review shows, and on its invite's approval card -- when
    the day was "next <weekday>" and could have been the other one. Never in
    the email itself."""
    existing = (
        await db.execute(
            select(ScheduledMeeting).where(
                ScheduledMeeting.org_id == recording.org_id,
                ScheduledMeeting.recording_meeting_id == recording.id,
            )
        )
    ).scalars().first()
    if existing is not None:
        return existing
    try:
        on_date = date.fromisoformat(str(agreed.get("date"))[:10])
        time_hhmm = normalise_time(agreed.get("time"))
    except (TypeError, ValueError, ValidationFailedError):
        logger.warning("Recording %s agreed a meeting with an unusable date/time: %s",
                       recording.id, agreed)
        return None
    ctx = await _ctx_for(db, recording.org_id, recording.agent_id)
    if not may_schedule(ctx.role):
        return None
    meeting, invite = await schedule(
        db, ctx, lead=lead, on_date=on_date, time_hhmm=time_hhmm,
        duration_minutes=agreed.get("duration_minutes"), purpose=agreed.get("purpose"),
        source="recording", recording_meeting_id=recording.id,
        task_status=task_status, context_summary=summary,
    )
    if note:
        from app.models.comms import Approval

        task = (await db.execute(select(ActionItem).where(
            ActionItem.id == meeting.action_item_id))).scalar_one_or_none()
        if task is not None:
            task.description = " ".join(p for p in (task.description, note) if p)
        approval_id = await approval_id_for(db, invite) if invite is not None else None
        if approval_id:
            approval = (await db.execute(select(Approval).where(
                Approval.id == approval_id))).scalar_one_or_none()
            if approval is not None:
                approval.reason = " ".join(p for p in (approval.reason, note) if p)
    return meeting


async def approval_id_for(db: AsyncSession, message: OutboundMessage) -> str | None:
    """The pending approval an invite waits on — where Jarvis's card opens."""
    from app.core.constants import ApprovalStatus
    from app.models.comms import Approval

    return (
        await db.execute(
            select(Approval.id).where(
                Approval.org_id == message.org_id,
                Approval.entity_type == "outbound_message",
                Approval.entity_id == message.id,
                Approval.status == ApprovalStatus.PENDING.value,
            ).order_by(Approval.requested_at.desc())
        )
    ).scalars().first()


async def invite_waiting_meetings(db: AsyncSession, *, org_id: str, lead_id: str) -> int:
    """A contact with an email has just been added to this client: draft the
    invites that were skipped for want of one.

    Found on the first real upload (Risabh Public School, 23 Sep 2026): the
    recording scheduled the meeting before the lead had any contact, the invite
    was rightly skipped — and then nothing ever drafted it. Only upcoming,
    still-scheduled meetings; each invite is sent as its organiser. Returns how
    many were drafted.
    """
    from app.core import clock

    today = clock.today(await clock.org_zone(db, org_id))
    waiting = (
        await db.execute(
            select(ScheduledMeeting).where(
                ScheduledMeeting.org_id == org_id,
                ScheduledMeeting.lead_id == lead_id,
                ScheduledMeeting.status == "scheduled",
                ScheduledMeeting.invite_status == "no_contact",
                ScheduledMeeting.meeting_date >= today,
            )
        )
    ).scalars().all()
    drafted = 0
    for meeting in waiting:
        ctx = await _ctx_for(db, org_id, meeting.organizer_id)
        lead = await _lead(db, meeting)
        if await compose_invite(db, ctx, meeting=meeting, lead=lead) is not None:
            drafted += 1
    return drafted


async def cancel(
    db: AsyncSession, ctx: OrgContext, meeting: ScheduledMeeting,
) -> OutboundMessage | None:
    """Cancel it: calendar event removed, task closed, and — if the client was
    ever sent (or is about to be sent) an invite — a cancellation drafted."""
    if meeting.status == "cancelled":
        return None
    had_invite = meeting.invite_message_id is not None
    meeting.status = "cancelled"
    await _calendar_event(db, meeting, await _lead(db, meeting))
    if meeting.action_item_id:
        task = (await db.execute(select(ActionItem).where(
            ActionItem.id == meeting.action_item_id))).scalar_one_or_none()
        if task is not None and task.status in ("open", "in_progress", "pending_review"):
            task.status = "cancelled"
    # The pending draft, if any, must not be sent after a cancellation.
    if meeting.invite_message_id:
        pending = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.id == meeting.invite_message_id))).scalar_one_or_none()
        if pending is not None and pending.status in ("pending_approval", "draft"):
            await message_service.reject_message(db, ctx, pending.id,
                                                 "The meeting was cancelled")
    invite = None
    if had_invite:
        invite = await compose_invite(db, ctx, meeting=meeting, lead=await _lead(db, meeting),
                                      change="cancelled")
    await audit_service.record(
        db, org_id=ctx.org_id, user_id=ctx.user_id, action="meeting.cancelled",
        entity_type="scheduled_meeting", entity_id=meeting.id, detail={},
    )
    return invite


async def _lead(db: AsyncSession, meeting: ScheduledMeeting) -> Lead:
    return (await db.execute(select(Lead).where(Lead.id == meeting.lead_id))).scalar_one()


# ── the rejection loop ───────────────────────────────────────────────────

async def meeting_for_message(db: AsyncSession, message: OutboundMessage) -> ScheduledMeeting | None:
    key = message.idempotency_key or ""
    if not key.startswith(_KEY_PREFIX):
        return None
    meeting_id = key[len(_KEY_PREFIX):].split(":", 1)[0]
    return (
        await db.execute(select(ScheduledMeeting).where(
            ScheduledMeeting.org_id == message.org_id, ScheduledMeeting.id == meeting_id))
    ).scalar_one_or_none()


async def after_rejection(
    db: AsyncSession, *, org_id: str, message: OutboundMessage, reason: str,
) -> OutboundMessage | None:
    """The invite was rejected. With a reason: apply it and file a new draft.
    Without one: closed. A cancellation notice is never redrafted."""
    meeting = await meeting_for_message(db, message)
    if meeting is None:
        return None
    if meeting.invite_message_id == message.id:
        meeting.invite_status = "rejected"
    reason = (reason or "").strip()
    if not reason or meeting.status == "cancelled":
        return None

    from app.core import clock

    ctx = await _ctx_for(db, org_id, message.sender_user_id)
    lead = await _lead(db, meeting)
    changes = await _read_rejection(
        org_id=org_id, reason=reason, meeting=meeting,
        today=clock.today(await clock.org_zone(db, org_id)),
    )
    moved = False
    try:
        if changes.get("date"):
            new_date = date.fromisoformat(str(changes["date"])[:10])
            moved |= new_date != meeting.meeting_date
            meeting.meeting_date = new_date
        if changes.get("time"):
            new_time = normalise_time(changes["time"])
            moved |= new_time != meeting.start_time
            meeting.start_time = new_time
        if changes.get("duration_minutes"):
            minutes = int(changes["duration_minutes"])
            if 5 <= minutes <= MAX_DURATION:
                moved |= minutes != meeting.duration_minutes
                meeting.duration_minutes = minutes
    except (TypeError, ValueError, ValidationFailedError):
        logger.warning("Ignoring an unusable date/time read from reason %r: %s", reason, changes)

    def _edit(current: list[str], add: Any, remove: Any) -> list[str]:
        keep = [a for a in current if a.lower() not in {str(r).lower() for r in remove or []}]
        for address in add or []:
            address = str(address).strip()
            if _EMAIL.fullmatch(address) and address.lower() not in {a.lower() for a in keep}:
                keep.append(address)
        return keep

    meeting.cc = _edit(list(meeting.cc or []), changes.get("add_cc"), changes.get("remove_cc"))
    meeting.bcc = _edit(list(meeting.bcc or []), changes.get("add_bcc"), changes.get("remove_bcc"))

    if moved:
        await _calendar_event(db, meeting, lead)
        if meeting.action_item_id:
            task = (await db.execute(select(ActionItem).where(
                ActionItem.id == meeting.action_item_id))).scalar_one_or_none()
            if task is not None:
                task.title = _task_title(lead.name, meeting)[:490]
                task.due_date = _task_due(meeting)
    return await compose_invite(
        db, ctx, meeting=meeting, lead=lead,
        change="rescheduled" if moved else "updated", instruction=reason,
    )
