"""iCalendar (RFC 5545) invite generation.

A calendar invite is an ordinary email carrying a text/calendar part with
METHOD:REQUEST — Gmail/Outlook render it as the native invitation card
(Yes/No/Maybe buttons, event auto-added to the recipient's calendar) and
recipients RSVP by mail. Plain SMTP carries it; no Google Workspace,
Domain-Wide Delegation or Calendar API is involved.

Updates re-send the same UID with a higher SEQUENCE ("This event has been
updated"); cancellations send METHOD:CANCEL with STATUS:CANCELLED.
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta, timezone



def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545 §3.1 — lines over 75 octets continue on the next line
    after a single space; never split inside a UTF-8 sequence."""
    out: list[str] = []
    raw = line.encode("utf-8")
    while len(raw) > 74:
        cut = 74
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# Fixed-offset VTIMEZONE for India (no DST) — copied from Google Calendar's
# own invite files so DTSTART;TZID=Asia/Kolkata resolves everywhere.
_VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    "TZID:Asia/Kolkata",
    "X-LIC-LOCATION:Asia/Kolkata",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0530",
    "TZOFFSETTO:+0530",
    "TZNAME:GMT+5:30",
    "DTSTART:19700101T000000",
    "END:STANDARD",
    "END:VTIMEZONE",
]


def build_invite_html(
    *,
    title: str,
    when_text: str,
    guests: list[str],
    meet_link: str | None,
    message_text: str,
) -> str:
    """Styled HTML body in the visual language of Google Calendar's own
    invitation emails: event card, blue Join-with-Google-Meet button,
    meeting link, guest list. The plain-text part carries message_text."""
    import html as _html

    e = _html.escape
    message = e(message_text).replace("\n", "<br>\n")
    meet_block = ""
    if meet_link:
        link = e(meet_link, quote=True)
        display = e(meet_link.removeprefix("https://").removeprefix("http://"))
        meet_block = (
            '<div style="margin:20px 0 8px 0">'
            f'<a href="{link}" style="background:#1a73e8;color:#ffffff;'
            "text-decoration:none;padding:10px 24px;border-radius:4px;"
            'font-weight:500;display:inline-block">Join with Google Meet</a>'
            "</div>"
            '<div style="color:#5f6368;font-size:13px">Meeting link: '
            f'<a href="{link}" style="color:#1a73e8;text-decoration:none">'
            f"{display}</a></div>"
        )
    guest_lines = "".join(
        f'<div style="margin-top:2px">{e(g)}</div>' for g in guests
    )
    return (
        '<div style="font-family:Roboto,Arial,sans-serif;color:#202124;'
        'max-width:560px">'
        f'<p>{message}</p>'
        '<div style="border:1px solid #dadce0;border-radius:8px;'
        'padding:20px;margin:16px 0">'
        f'<div style="font-size:22px;line-height:28px">{e(title)}</div>'
        f'<div style="color:#5f6368;margin-top:4px">{e(when_text)}</div>'
        f"{meet_block}"
        '<div style="margin-top:16px;font-size:13px">'
        '<div style="font-weight:500">Guests</div>'
        f'<div style="color:#5f6368">{guest_lines}</div>'
        "</div></div>"
        '<div style="color:#5f6368;font-size:12px">Please respond with the '
        "Yes / No / Maybe buttons above so the team knows to expect you."
        "</div></div>"
    )


def build_invite(
    *,
    uid: str,
    sequence: int,
    title: str,
    description: str,
    organizer_name: str,
    organizer_email: str,
    attendees: list[tuple[str, str]],  # (name, email)
    on_date: date,
    time_hhmm: str | None = None,
    duration_minutes: int = 60,
    location: str | None = None,
    conference_link: str | None = None,
    method: str = "REQUEST",  # REQUEST | CANCEL
) -> str:
    """Return the full iCalendar document for one event invitation."""
    cancelled = method.upper() == "CANCEL"
    if time_hhmm:
        try:
            hour, minute = (int(x) for x in time_hhmm.split(":"))
        except ValueError:
            hour, minute = 10, 0
        start = datetime(on_date.year, on_date.month, on_date.day, hour, minute)
        end = start + timedelta(minutes=duration_minutes)
        when = [
            f"DTSTART;TZID=Asia/Kolkata:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Asia/Kolkata:{end.strftime('%Y%m%dT%H%M%S')}",
        ]
    else:
        when = [
            f"DTSTART;VALUE=DATE:{on_date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(on_date + timedelta(days=1)).strftime('%Y%m%d')}",
        ]

    # Structure, property order and parameter conventions deliberately mirror
    # the ICS that Google Calendar's own invitation emails carry — Gmail's
    # invite card renderer is strict, and matching Google's shape
    # byte-for-byte is the reliable path.
    now = _utc(datetime.now(timezone.utc))
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//YuviPep AI Sales Platform//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method.upper()}",
        *(_VTIMEZONE if time_hhmm else []),
        "BEGIN:VEVENT",
        *when,
        f"DTSTAMP:{now}",
        f"ORGANIZER;CN={_escape(organizer_name)}:mailto:{organizer_email}",
        f"UID:{uid}",
    ]
    for name, email in attendees:
        lines.append(
            f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;"
            f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE;CN={_escape(name)};"
            f"X-NUM-GUESTS=0:mailto:{email}"
        )
    if conference_link and not cancelled:
        lines.append(f"X-GOOGLE-CONFERENCE:{conference_link}")
    lines += [
        f"CREATED:{now}",
        f"DESCRIPTION:{_escape(description)}",
        f"LAST-MODIFIED:{now}",
        f"LOCATION:{_escape(location or '')}",
        f"SEQUENCE:{sequence}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        f"SUMMARY:{_escape(title)}",
        "TRANSP:OPAQUE",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
