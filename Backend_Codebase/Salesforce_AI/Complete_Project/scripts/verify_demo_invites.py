"""Verify the demo calendar-invite pipeline end to end (dry-run sends).

Books a demo through the real API and checks the whole invite lifecycle:

  1. booking drafts an approval-gated invite email to the lead's primary
     contact, carrying an iCalendar METHOD:REQUEST with the reusable Meet link
  2. approving + sending renders a real .eml with a text/calendar alternative
     part and an invite.ics attachment (the structure Gmail renders as the
     native RSVP card)
  3. rescheduling drafts an updated invite with the same UID and a higher
     SEQUENCE (recipients see "This event has been updated")
  4. cancelling drafts a METHOD:CANCEL that retracts the event

Run:  python scripts/verify_demo_invites.py
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

from dryrun_lib import EMAILS, Runner, lead_by_name  # noqa: E402 (sets env)
from sqlalchemy import select  # noqa: E402

MEET_LINK = "https://meet.google.com/abc-defg-hij"


def _ics_of(message) -> str:
    return next(a["ics_text"] for a in message.attachments if a.get("ics_text"))


def _field(ics: str, name: str) -> str:
    unfolded = ics.replace("\r\n ", "")
    for line in unfolded.splitlines():
        if line.startswith(name + ":") or line.startswith(name + ";"):
            return line
    return ""


async def run(r: Runner) -> None:
    from app.models.messaging import OutboundMessage
    from app.models.organisation import OrgSettings
    from app.services import storage

    r.begin("Demo invite lifecycle — book, approve+send, reschedule, cancel")

    svs = await lead_by_name(r, "Swami Vivekananda School")

    # The org's reusable Meet link (org settings, calendar integration).
    async with r.session() as db:
        org_settings = (
            await db.execute(
                select(OrgSettings).where(OrgSettings.org_id == svs.org_id)
            )
        ).scalar_one()
        org_settings.calendar_integration = {
            **(org_settings.calendar_integration or {}),
            "meet_link": MEET_LINK,
        }
        await db.commit()

    # 1. Book a demo → invite draft.
    demo_date = (date.today() + timedelta(days=3)).isoformat()
    booked = await r.api(
        "POST", "/demos", user=EMAILS["ananya"],
        json={"lead_id": svs.id, "scheduled_date": demo_date,
              "scheduled_time": "11:00", "notes": "Robotics kit walkthrough"},
    )
    invite_id = booked.get("invite_message_id")
    r.check("booking a demo drafts an invite email", bool(invite_id))

    async with r.session() as db:
        msg = (
            await db.execute(
                select(OutboundMessage).where(OutboundMessage.id == invite_id)
            )
        ).scalar_one()
    r.check("invite goes to the lead's primary contact",
            msg.to_address == "principal@svs.edu.in", msg.to_address)
    r.check("invite waits for human approval (never auto-sends)",
            msg.status == "pending_approval", msg.status)
    ics = _ics_of(msg)
    unfolded = ics.replace("\r\n ", "")
    r.check("iCalendar is a METHOD:REQUEST", "METHOD:REQUEST" in unfolded)
    r.check("contact is an attendee with RSVP",
            "RSVP=TRUE" in unfolded and "principal@svs.edu.in" in unfolded)
    r.check("reusable Meet link stamped into the event",
            MEET_LINK in _field(ics, "LOCATION") and MEET_LINK in msg.body)
    first_seq = int(_field(ics, "SEQUENCE").split(":")[1])
    r.check("first invite carries SEQUENCE:0 (Google convention)", first_seq == 0)
    first_uid = _field(ics, "UID")

    # 2. Approve → send (dry-run writes the real MIME to the outbox).
    await r.api("POST", f"/messages/{invite_id}/approve", user=EMAILS["ananya"])
    await r.flush_sends()
    async with r.session() as db:
        msg = (
            await db.execute(
                select(OutboundMessage).where(OutboundMessage.id == invite_id)
            )
        ).scalar_one()
    r.check("approved invite was sent", msg.status == "sent", msg.status)
    rel = (msg.provider_message_id or "").removeprefix("dry_run:")
    eml = storage.read_bytes(msg.org_id, rel).decode("utf-8", errors="replace")
    r.check("email carries a text/calendar part with method=REQUEST",
            "text/calendar" in eml and
            ('method="REQUEST"' in eml or "method=REQUEST" in eml))
    r.check("email carries the invite.ics attachment",
            "invite.ics" in eml and "application/ics" in eml)
    r.check("email carries the styled HTML body (Join with Google Meet button)",
            "text/html" in eml and "Join with Google Meet" in eml)

    # 3. Reschedule → updated invite, same UID, higher SEQUENCE.
    new_date = (date.today() + timedelta(days=5)).isoformat()
    updated = await r.api(
        "PATCH", f"/demos/{booked['id']}", user=EMAILS["ananya"],
        json={"scheduled_date": new_date},
    )
    reschedule_id = updated.get("invite_message_id")
    r.check("rescheduling drafts an update invite", bool(reschedule_id))
    if reschedule_id:
        async with r.session() as db:
            msg2 = (
                await db.execute(
                    select(OutboundMessage).where(OutboundMessage.id == reschedule_id)
                )
            ).scalar_one()
        ics2 = _ics_of(msg2)
        r.check("update keeps the same event UID", _field(ics2, "UID") == first_uid)
        r.check("update outranks the original (higher SEQUENCE)",
                int(_field(ics2, "SEQUENCE").split(":")[1]) > first_seq)
        r.check("update is still METHOD:REQUEST (event moves, not dies)",
                "METHOD:REQUEST" in ics2)

    # 4. Cancel → METHOD:CANCEL retracts the event.
    cancelled = await r.api(
        "PATCH", f"/demos/{booked['id']}", user=EMAILS["ananya"],
        json={"status": "cancelled"},
    )
    cancel_id = cancelled.get("invite_message_id")
    r.check("cancelling drafts a cancellation invite", bool(cancel_id))
    if cancel_id:
        async with r.session() as db:
            msg3 = (
                await db.execute(
                    select(OutboundMessage).where(OutboundMessage.id == cancel_id)
                )
            ).scalar_one()
        ics3 = _ics_of(msg3)
        r.check("cancellation is METHOD:CANCEL with STATUS:CANCELLED",
                "METHOD:CANCEL" in ics3 and "STATUS:CANCELLED" in ics3)
        r.check("cancellation targets the same event UID",
                _field(ics3, "UID") == first_uid)


async def main() -> None:
    r = Runner()
    await r.setup()
    try:
        await run(r)
    except Exception as exc:  # noqa: BLE001
        r.fail(f"{type(exc).__name__}: {exc}")
    finally:
        await r.teardown()
    ok = r.report()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
