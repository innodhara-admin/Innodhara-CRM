"""Email sending via SMTP (Gmail app passwords) with a dry-run fallback.

Sender resolution order (doc §3: "the school always sees a real person's
email"):
  1. the sending user's own email + their stored app password
  2. the organisation's default SMTP account (org settings)
  3. the platform-wide default in .env
In dry-run mode (EMAIL_MODE=dry_run or no credentials) the full RFC-822
message is composed and written to storage so the flow is fully testable.
"""
from __future__ import annotations

import asyncio
import mimetypes
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr

from app.config import get_settings
from app.core.crypto import decrypt_secret
from app.core.exceptions import ExternalServiceError
from app.services import storage


@dataclass
class EmailPayload:
    sender_name: str
    sender_email: str
    to_address: str
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)  # {"path","filename"}
    org_id: str = ""
    # Delivered to but never written into a header — that is what blind means.
    bcc: list[str] = field(default_factory=list)
    # The formatted body of an email made from a Word email template
    # (28 Oct 2026), sent beside `body` as its HTML alternative. None for
    # every other message, which therefore sends exactly as before.
    html_body: str | None = None


def recipients(payload: EmailPayload) -> list[str]:
    """Everyone the SMTP envelope goes to: to, cc and bcc, each once."""
    out: list[str] = []
    for address in [payload.to_address, *payload.cc, *payload.bcc]:
        if address and address.lower() not in {a.lower() for a in out}:
            out.append(address)
    return out


@dataclass
class SmtpCredentials:
    username: str
    app_password: str
    # None = the server-wide SMTP_HOST / SMTP_PORT, which is what every
    # account used before 12 Oct 2026. Set only for an organisation account
    # whose mail is not hosted where the server points (see `_smtp_server_for`).
    host: str | None = None
    port: int | None = None


#: Mail hosts recognised from a domain's MX records -> (SMTP host, port).
#: Google is mapped to None on purpose: Google-hosted mail keeps the server's
#: own setting, exactly as before this table existed.
_MX_PROVIDERS: tuple[tuple[str, tuple[str, int] | None], ...] = (
    ("zoho.in", ("smtp.zoho.in", 587)),
    ("zoho.eu", ("smtp.zoho.eu", 587)),
    ("zoho.com", ("smtp.zoho.com", 587)),
    ("google.com", None),
    ("googlemail.com", None),
    ("outlook.com", ("smtp.office365.com", 587)),
)
_GOOGLE_DOMAINS = {"gmail.com", "googlemail.com"}
_mx_cache: dict[str, tuple[str, int] | None] = {}


def _mx_hosts(domain: str) -> list[str]:
    """The domain's MX hosts, lower-case, or [] when they cannot be read.

    `dig` rather than a new Python dependency; a missing binary, a timeout or
    an empty answer all mean "unknown", which keeps the server's own host.
    """
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(
            ["dig", "+short", "MX", domain], capture_output=True, text=True,
            timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    hosts = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            hosts.append(parts[-1].rstrip(".").lower())
    return hosts


def _smtp_server_for(username: str) -> tuple[str, int] | None:
    """Where an organisation account's mail is hosted, when that is NOT the
    server's own SMTP host; None means "use the server setting" (unchanged).

    Live, 12 Oct 2026: Innodhara's account is admin@innodhara.com, hosted by
    Zoho, but every send went to smtp.gmail.com and failed with "Connection
    unexpectedly closed" -- Innodhara had never sent a single email. A gmail.com
    account (YuviPep's) never reaches the lookup.
    """
    domain = username.rsplit("@", 1)[-1].strip().lower() if "@" in username else ""
    if not domain or domain in _GOOGLE_DOMAINS:
        return None
    if domain not in _mx_cache:
        found: tuple[str, int] | None = None
        for mx in _mx_hosts(domain):
            match = next((server for suffix, server in _MX_PROVIDERS
                          if mx == suffix or mx.endswith("." + suffix)), "none")
            if match != "none":
                found = match
                break
        _mx_cache[domain] = found
    return _mx_cache[domain]


def resolve_credentials(
    *,
    user_email: str,
    user_app_password_enc: str | None,
    org_email_integration: dict | None,
) -> SmtpCredentials | None:
    settings = get_settings()
    if user_app_password_enc:
        password = decrypt_secret(user_app_password_enc)
        if password:
            return SmtpCredentials(username=user_email, app_password=password)
    integ = org_email_integration or {}
    if integ.get("smtp_username") and integ.get("smtp_app_password_enc"):
        password = decrypt_secret(integ["smtp_app_password_enc"])
        if password:
            server = (
                (integ["smtp_host"], int(integ.get("smtp_port") or 587))
                if integ.get("smtp_host")
                else _smtp_server_for(integ["smtp_username"])
            )
            return SmtpCredentials(
                username=integ["smtp_username"], app_password=password,
                host=server[0] if server else None,
                port=server[1] if server else None,
            )
    if settings.smtp_default_username and settings.smtp_default_app_password:
        return SmtpCredentials(
            username=settings.smtp_default_username,
            app_password=settings.smtp_default_app_password,
        )
    return None


def _build_mime(payload: EmailPayload) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((payload.sender_name, payload.sender_email))
    msg["To"] = payload.to_address
    if payload.cc:
        msg["Cc"] = ", ".join(payload.cc)
    msg["Subject"] = payload.subject
    msg.set_content(payload.body)

    # Calendar invites (attachment dicts carrying "ics_text") reproduce the
    # exact MIME shape of Google Calendar's own invitation emails —
    # multipart/alternative [text/plain, text/html, base64 text/calendar]
    # inside multipart/mixed with an invite.ics attachment — so Gmail/Outlook
    # render the native RSVP card. See app/services/ics_service.py.
    # A styled body ("html_body" on the invite dict, e.g. the Join-with-Meet
    # button block) replaces the default text-to-HTML conversion.
    ics_parts = [a for a in payload.attachments if a.get("ics_text")]
    if payload.html_body and not ics_parts:
        # A calendar invite builds its own HTML part below; a template body
        # never joins one.
        msg.add_alternative(payload.html_body, subtype="html")
    if ics_parts:
        import html as _html

        html_body = next(
            (a["html_body"] for a in ics_parts if a.get("html_body")),
            "<div>{}</div>".format(
                _html.escape(payload.body).replace("\n", "<br>\n")
            ),
        )
        msg.add_alternative(html_body, subtype="html")
    for att in ics_parts:
        msg.add_alternative(
            att["ics_text"],
            subtype="calendar",
            params={"method": att.get("ics_method", "REQUEST")},
            cte="base64",
        )
    for att in ics_parts:
        msg.add_attachment(
            att["ics_text"].encode("utf-8"),
            maintype="application",
            subtype="ics",
            filename=att.get("filename", "invite.ics"),
        )

    for att in payload.attachments:
        if att.get("ics_text"):
            continue
        try:
            data = storage.read_bytes(payload.org_id, att["path"])
        except Exception:
            continue
        filename = att.get("filename", "attachment")
        if filename.lower().endswith(".pdf"):
            maintype, subtype = "application", "pdf"
        elif filename.lower().endswith(".docx"):
            maintype = "application"
            subtype = "vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            # Template attachments can be slides, sheets or images (28 Oct
            # 2026). PDF and DOCX above keep exactly the types they had.
            guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            maintype, subtype = guessed.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return msg


def _sender_for_host(msg: EmailMessage, payload: EmailPayload,
                     creds: SmtpCredentials) -> None:
    """On an organisation's own mail host, send FROM the account that logged in.

    Gmail accepts a From that is not the signed-in account; Zoho and Office 365
    refuse it ("sender is not allowed to relay"). So where the account has its
    own host, the mail goes from that account under the salesperson's name,
    and replies still reach the salesperson. The server's own host (YuviPep,
    every send before 12 Oct 2026) is left exactly as it was.
    """
    if creds.host is None:
        return
    if creds.username.lower() == (payload.sender_email or "").lower():
        return
    del msg["From"]
    msg["From"] = formataddr((payload.sender_name, creds.username))
    if payload.sender_email and "Reply-To" not in msg:
        msg["Reply-To"] = payload.sender_email


def _smtp_send_sync(msg: EmailMessage, creds: SmtpCredentials, recipients: list[str]) -> None:
    settings = get_settings()
    host = creds.host or settings.smtp_host
    port = creds.port or settings.smtp_port
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(creds.username, creds.app_password)
        smtp.send_message(msg, to_addrs=recipients)


async def send_email(payload: EmailPayload, creds: SmtpCredentials | None) -> str:
    """Send (or dry-run) an email. Returns a provider reference string.

    Raises ExternalServiceError on transient failure so the job queue retries
    with backoff (doc §11.6).
    """
    settings = get_settings()
    msg = _build_mime(payload)
    envelope = recipients(payload)

    if settings.email_mode != "smtp" or creds is None:
        rel = storage.save_bytes(
            payload.org_id or "platform",
            storage.CATEGORY_OUTBOX,
            f"email_{payload.to_address}.eml",
            bytes(msg),
        )
        return f"dry_run:{rel}"

    _sender_for_host(msg, payload, creds)
    try:
        await asyncio.to_thread(_smtp_send_sync, msg, creds, envelope)
        return f"smtp:{creds.username}"
    except smtplib.SMTPAuthenticationError as exc:
        raise ExternalServiceError(f"SMTP authentication failed: {exc}") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise ExternalServiceError(f"SMTP send failed: {exc}") from exc
