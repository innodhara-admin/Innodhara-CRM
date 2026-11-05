"""IMAP inbox poller — connects the inbound machinery to a real mailbox.

Every INBOUND_POLL_SECONDS (when INBOUND_EMAIL_MODE=imap), each organisation
whose email integration carries credentials gets its inbox read over IMAP —
the same Gmail App Password used for SMTP sending also works for reading.

Every unseen email passes through four gates, in order:

  1. Dedupe        — the Message-ID is remembered (idempotency_records), so a
                     crash, restart or re-poll can never ingest twice.
  2. Hygiene       — protocol-level automation signals (Auto-Submitted,
                     Precedence: bulk/list, List-Unsubscribe/List-Id,
                     no-reply/mailer-daemon senders). These are headers that
                     exist precisely to declare "no human wrote this" — not
                     content keywords.
  3. Who wrote it  — an org user's own address is a loop and is skipped; a
                     KNOWN CONTACT is always ingested (the Inbound Engine
                     judges the content from there).
  4. Strangers     — the model reads the email and judges whether a human
                     wrote it about actual or potential business. Noise is
                     ignored WITH an audit-log entry (never silently);
                     anything plausibly human goes to ingest, where an
                     unmatched sender lands in the triage queue. If the model
                     is unreachable, the email is KEPT — doubt never drops.

Attachments are not parsed (bodies only); the stored message notes them.
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import hashlib
import imaplib
import logging
import re
from email.message import EmailMessage
from email.utils import parseaddr
from html import unescape

from sqlalchemy import select

from app.config import get_settings
from app.core.crypto import decrypt_secret
from app.database import SessionLocal
from app.models.audit import IdempotencyRecord
from app.models.lead import Contact
from app.models.organisation import Organisation, OrgSettings
from app.models.user import User

logger = logging.getLogger(__name__)

_ENDPOINT = "imap_poller"
_FETCH_LIMIT = 25  # per org per poll — a flood never starves the event loop


# ─────────────────────────────────────────────────────────────────────────────
# Message parsing (mechanical — no language understanding here)
# ─────────────────────────────────────────────────────────────────────────────


def _sender_address(msg: EmailMessage) -> str:
    return (parseaddr(msg.get("From") or "")[1] or "").strip().lower()


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _body_text(msg: EmailMessage) -> str:
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    content = body.get_content()
    if body.get_content_type() == "text/html":
        content = _strip_html(content)
    attachments = [
        f for f in (p.get_filename() for p in msg.iter_attachments()) if f
    ]
    if attachments:
        content += "\n\n[Attachments: " + ", ".join(attachments[:10]) + "]"
    return content.strip()


def _automation_reason(msg: EmailMessage) -> str | None:
    """Protocol-level 'no human wrote this' signals."""
    if (msg.get("Auto-Submitted") or "no").strip().lower() != "no":
        return "Auto-Submitted header"
    if (msg.get("Precedence") or "").strip().lower() in ("bulk", "list", "junk"):
        return f"Precedence: {msg.get('Precedence')}"
    if msg.get("List-Id") or msg.get("List-Unsubscribe"):
        return "mailing-list headers"
    if msg.get("X-Auto-Response-Suppress"):
        return "X-Auto-Response-Suppress header"
    local = _sender_address(msg).split("@")[0]
    for marker in ("no-reply", "noreply", "donotreply", "do-not-reply",
                   "mailer-daemon", "postmaster", "bounces", "bounce"):
        if marker in local:
            return f"automated sender address ({local})"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# IMAP transport (blocking stdlib — always called via asyncio.to_thread)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_unseen_sync(
    host: str, port: int, username: str, password: str
) -> list[bytes]:
    box = imaplib.IMAP4_SSL(host, port)
    try:
        box.login(username, password)
        box.select("INBOX")
        _, data = box.uid("search", None, "UNSEEN")
        uids = (data[0] or b"").split()[:_FETCH_LIMIT]
        raw_messages: list[bytes] = []
        for uid in uids:
            # A non-PEEK fetch marks the message \Seen on the server; the
            # Message-ID dedupe below covers any re-delivery regardless.
            _, fetched = box.uid("fetch", uid, "(RFC822)")
            for item in fetched or []:
                if isinstance(item, tuple) and len(item) >= 2 and item[1]:
                    raw_messages.append(item[1])
        return raw_messages
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass


# ─────────────────────────────────────────────────────────────────────────────
# The gates + ingest for one raw email (testable without a socket)
# ─────────────────────────────────────────────────────────────────────────────


async def process_raw_email(org_id: str, raw: bytes) -> str:
    """Run one RFC-822 message through the gates. Returns the outcome:
    'duplicate' | 'automation' | 'own_user' | 'ignored_irrelevant'
    | 'ingested:<status>'."""
    from app.engines import inbound_engine, nlu
    from app.services import audit_service

    msg: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)
    message_id = (msg.get("Message-ID") or "").strip() or (
        "sha1:" + hashlib.sha1(raw).hexdigest()
    )
    key = f"imap:{message_id}"[:200]
    sender = _sender_address(msg)
    subject = str(msg.get("Subject") or "").strip()

    async with SessionLocal() as db:
        seen = (
            await db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.org_id == org_id,
                    IdempotencyRecord.key == key,
                )
            )
        ).scalars().first()
        if seen is not None:
            return "duplicate"

        async def remember(entity_id: str | None = None) -> None:
            db.add(
                IdempotencyRecord(
                    org_id=org_id, key=key, endpoint=_ENDPOINT, entity_id=entity_id
                )
            )

        reason = _automation_reason(msg)
        if reason is not None:
            await remember()
            await db.commit()
            logger.info("Mail skipped (%s): %s / %s", reason, sender, subject[:60])
            return "automation"

        if not sender:
            await remember()
            await db.commit()
            return "automation"

        own = (
            await db.execute(
                select(User).where(User.org_id == org_id, User.email == sender)
            )
        ).scalars().first()
        if own is not None:
            await remember()
            await db.commit()
            return "own_user"

        body = _body_text(msg)
        contact = (
            await db.execute(
                select(Contact).where(Contact.org_id == org_id, Contact.email == sender)
            )
        ).scalars().first()
        if contact is None:
            relevant, why = await nlu.screen_stranger_email(
                org_id=org_id, from_address=sender, subject=subject, body=body
            )
            if not relevant:
                # Ignored, never silently: the audit log answers "why?".
                await remember()
                await audit_service.record(
                    db, org_id=org_id, user_id=None,
                    action="inbound.email_ignored",
                    entity_type="email", entity_id=None,
                    detail={"from": sender, "subject": subject[:200], "reason": why},
                )
                await db.commit()
                logger.info("Mail ignored as noise: %s / %s (%s)",
                            sender, subject[:60], why)
                return "ignored_irrelevant"

        inbound = await inbound_engine.ingest(
            db, org_id=org_id, channel="email",
            from_address=sender, to_address=None,
            subject=subject, body=body,
        )
        await remember(entity_id=inbound.id)
        await db.commit()
        return f"ingested:{inbound.status}"


# ─────────────────────────────────────────────────────────────────────────────
# The poll loop entry (called by the scheduler)
# ─────────────────────────────────────────────────────────────────────────────


def _imap_credentials(integ: dict | None) -> tuple[str, str] | None:
    integ = integ or {}
    username = integ.get("imap_username") or integ.get("smtp_username")
    password_enc = integ.get("imap_app_password_enc") or integ.get("smtp_app_password_enc")
    if not username or not password_enc:
        return None
    password = decrypt_secret(password_enc)
    return (username, password) if password else None


async def poll_once() -> dict[str, int]:
    """Poll every configured org's inbox once. Never raises."""
    settings = get_settings()
    stats: dict[str, int] = {}
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(OrgSettings, Organisation)
                .join(Organisation, Organisation.id == OrgSettings.org_id)
                .where(Organisation.is_active.is_(True))
            )
        ).all()
    for org_settings, _org in rows:
        creds = _imap_credentials(org_settings.email_integration)
        if creds is None:
            continue
        try:
            raw_messages = await asyncio.to_thread(
                _fetch_unseen_sync, settings.imap_host, settings.imap_port, *creds
            )
        except Exception as exc:  # noqa: BLE001 — one org's inbox never kills the loop
            logger.warning("IMAP poll failed for org %s: %s", org_settings.org_id, exc)
            stats["errors"] = stats.get("errors", 0) + 1
            continue
        for raw in raw_messages:
            try:
                outcome = await process_raw_email(org_settings.org_id, raw)
            except Exception:  # noqa: BLE001
                logger.exception("Inbound email processing failed (org %s)",
                                 org_settings.org_id)
                outcome = "errors"
            outcome = outcome.split(":")[0]
            stats[outcome] = stats.get(outcome, 0) + 1
    if stats:
        logger.info("IMAP poll: %s", stats)
    return stats
