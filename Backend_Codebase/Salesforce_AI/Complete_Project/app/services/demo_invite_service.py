"""Demo calendar-invite emails.

When a demo is booked / rescheduled / cancelled, this composes an email
carrying an iCalendar invite (see ics_service) to the school's primary
contact, CC the demo team — as a normal OutboundMessage draft, so nothing
sends without a human tapping Approve.

The reusable Google Meet link (org settings calendar_integration
{"meet_link": ...}) is stamped into the event location and body when set.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.demo import Demo, DemoTeam, DemoTeamMember
from app.models.lead import Contact, Lead
from app.models.messaging import OutboundMessage
from app.models.organisation import OrgSettings
from app.models.user import User
from app.services import ics_service, message_service


async def _demo_contact(db: AsyncSession, lead: Lead) -> Contact | None:
    contacts = (
        (
            await db.execute(
                select(Contact).where(
                    Contact.lead_id == lead.id,
                    Contact.org_id == lead.org_id,
                    Contact.email.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    contacts = [c for c in contacts if c.email]
    if not contacts:
        return None
    return next((c for c in contacts if c.is_primary), contacts[0])


async def _team_attendees(
    db: AsyncSession, org_id: str, team: DemoTeam | None
) -> list[tuple[str, str]]:
    if team is None:
        return []
    user_ids = {u for u in (team.lead_user_id, team.media_rep_id, team.sales_rep_id) if u}
    member_ids = (
        (
            await db.execute(
                select(DemoTeamMember.user_id).where(
                    DemoTeamMember.team_id == team.id,
                    DemoTeamMember.org_id == org_id,
                )
            )
        )
        .scalars()
        .all()
    )
    user_ids.update(member_ids)
    if not user_ids:
        return []
    users = (
        (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    )
    return [(u.name, u.email) for u in users if u.email]


async def compose_demo_invite(
    db: AsyncSession,
    ctx,
    *,
    demo: Demo,
    lead: Lead,
    team: DemoTeam | None = None,
    change: str = "scheduled",  # scheduled | rescheduled | cancelled
) -> OutboundMessage | None:
    """Draft the invite email (PENDING_APPROVAL). Returns None when the
    lead has no contact with an email address — nothing to invite."""
    contact = await _demo_contact(db, lead)
    if contact is None:
        return None

    sender = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one_or_none()
    organizer_name = sender.name if sender else "YuviPep"
    organizer_email = sender.email if sender else ctx.email

    settings_row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == ctx.org_id))
    ).scalar_one_or_none()
    calendar_integ = (settings_row.calendar_integration if settings_row else None) or {}
    meet_link = calendar_integ.get("meet_link") or get_settings().google_meet_link

    staff = await _team_attendees(db, ctx.org_id, team)
    staff = [(n, e) for n, e in staff if e.lower() not in
             (contact.email.lower(), organizer_email.lower())]
    attendees = [(contact.name, contact.email)] + staff

    cancelled = change == "cancelled"
    when_text = demo.scheduled_date.strftime("%A, %d %B %Y") + (
        f" at {demo.scheduled_time}" if demo.scheduled_time else ""
    )
    title = f"Demo: {lead.name}" + (f" ({team.name})" if team else "")
    description_lines = [f"Product demo for {lead.name}."]
    if demo.notes:
        description_lines.append(demo.notes)
    if meet_link and not cancelled:
        description_lines.append(f"Join the video call: {meet_link}")
    description = "\n".join(description_lines)

    # SEQUENCE like Google: 0 on the first invite, +1 per demo change —
    # derived from how many invites this demo has already produced.
    sequence = (
        await db.execute(
            select(func.count()).select_from(OutboundMessage).where(
                OutboundMessage.org_id == ctx.org_id,
                OutboundMessage.idempotency_key.like(f"demo-invite:{demo.id}:%"),
            )
        )
    ).scalar_one()
    ics_text = ics_service.build_invite(
        uid=f"demo-{demo.id}@yuvipep.platform",
        sequence=sequence,
        title=title,
        description=description,
        organizer_name=organizer_name,
        organizer_email=organizer_email,
        attendees=attendees,
        on_date=demo.scheduled_date,
        time_hhmm=demo.scheduled_time,
        location=meet_link if not cancelled else None,
        conference_link=meet_link,
        method="CANCEL" if cancelled else "REQUEST",
    )

    if cancelled:
        subject = f"Cancelled: demo on {when_text} — {lead.name}"
        body = (
            f"Dear {contact.name},\n\n"
            f"The demo planned for {when_text} has been cancelled. "
            "We will reach out shortly to arrange a new time.\n\n"
            f"Warm regards,\n{organizer_name}"
        )
    else:
        verb = "rescheduled to" if change == "rescheduled" else "confirmed for"
        body_lines = [
            f"Dear {contact.name},",
            "",
            f"Your demo has been {verb} {when_text}.",
        ]
        if meet_link:
            body_lines += ["", f"Join the video call: {meet_link}"]
        body_lines += [
            "",
            "The attached calendar invitation adds the session to your "
            "calendar — please tap Yes to confirm.",
            "",
            f"Warm regards,\n{organizer_name}",
        ]
        subject = (
            f"Updated: demo rescheduled to {when_text} — {lead.name}"
            if change == "rescheduled"
            else f"Demo confirmed for {when_text} — {lead.name}"
        )
        body = "\n".join(body_lines)

    html_body = ics_service.build_invite_html(
        title=(f"Cancelled: {title}" if cancelled else title),
        when_text=when_text,
        guests=[f"{organizer_name} — organizer"]
        + [f"{n} ({e})" for n, e in attendees],
        meet_link=meet_link if not cancelled else None,
        message_text=body,
    )

    return await message_service.create_message(
        db,
        ctx,
        kind="demo_invite",
        channel="email",
        to_address=contact.email,
        subject=subject,
        body=body,
        cc=[e for _, e in staff],
        lead_id=lead.id,
        contact_id=contact.id,
        attachments=[{
            "ics_text": ics_text,
            "ics_method": "CANCEL" if cancelled else "REQUEST",
            "html_body": html_body,
            "filename": "invite.ics",
        }],
        idempotency_key=f"demo-invite:{demo.id}:{sequence}:{change}",
        # The demo-booking result says "drafted and waiting in Approvals".
        # Same as the intro: the inbox is the only route to a demo invite, so
        # without this row the statement was false (finding F2).
        request_approval=True,
    )
