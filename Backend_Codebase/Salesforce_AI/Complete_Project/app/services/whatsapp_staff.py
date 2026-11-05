"""Staff updates on WhatsApp (4 Nov 2026).

Every in-app notification (`notification_service.notify`) is also sent to the
person's WhatsApp when their organisation has a provider set up and "staff
updates" switched on. Spec: docs/superpowers/specs/2026-11-04-whatsapp-wati-design.md.

How it hangs off `notify()` without touching its callers:

* `notify()` only remembers the notification on the caller's session
  (`after_commit`). It does no database work of its own, so 73 call sites
  keep exactly the flush and commit behaviour they had.
* When that session COMMITS, a background task (`_queue_later`, own session)
  checks the settings and the person, writes a `whatsapp_log` row and queues
  a `whatsapp_staff` job. A rolled-back notification is never committed, so
  nothing is queued; one rolled back inside a savepoint is not in the database
  either, and `_queue_later` finds no row and stops.
* The job (`handle_job`) builds the message at send time from the
  notification and what it is about, and sends one template. A failure is
  recorded on the log row and never reaches the action that caused it.

Messages wait for the next working moment in the ORGANISATION's timezone and
are skipped while the person is on leave.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, tzinfo
from typing import Any

from sqlalchemy import event, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, signed_links
from app.core.exceptions import ExternalServiceError
from app.database import SessionLocal
from app.engines.worktime import is_on_leave, is_working_day, next_working_moment, parse_hhmm
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.lead import Lead
from app.models.meeting import Meeting, Transcript
from app.models.messaging import WhatsappLog
from app.models.organisation import OrgSettings
from app.models.user import Notification, User
from app.services import whatsapp_providers, whatsapp_settings
from app.services.whatsapp_text import markdown_to_line, normalise_phone

logger = logging.getLogger(__name__)

JOB_TYPE = "whatsapp_staff"
BRIEF = "daily_brief"
#: Every `kind` a notify() call passes today (AST scan, 4 Nov 2026; the
#: reminder ladder passes "reminder" or "escalation"), plus the morning brief.
#: A kind added later is sent unless an admin switches it off.
NOTIFICATION_KINDS = (
    "approval_waiting", "blocked_on_you", "daily_brief", "escalation", "followup_due",
    "general", "lead_assigned", "lead_opened", "meeting_failed", "meeting_processed",
    "plan_failed", "plan_ready", "plan_updated", "relationship_handover",
    "relationship_opportunity", "reminder", "task_assigned",
)
_PENDING = "whatsapp_staff_pending"
_HOOKED = "whatsapp_staff_hooked"
_MAX_ITEMS = 5
_tasks: set[asyncio.Task] = set()


# ── after the caller commits ─────────────────────────────────────────────


def after_commit(db: AsyncSession, n: Notification, *, org_id: str, user_id: str) -> None:
    """Remember `n`; queue its WhatsApp once `db` commits. Never raises."""
    try:
        sync = db.sync_session
        sync.info.setdefault(_PENDING, []).append((n, org_id, user_id))
        if not sync.info.get(_HOOKED):
            sync.info[_HOOKED] = True
            event.listen(sync, "after_commit", _on_commit)
    except Exception:  # noqa: BLE001 — a side channel must not break notify()
        logger.exception("WhatsApp: could not remember a notification")


def _on_commit(session) -> None:
    """SQLAlchemy also fires after_commit when a SAVEPOINT is released
    (`begin_nested`), before the outer transaction commits: those are ignored,
    or the copy would look for a row nobody else can see yet and be lost
    (final review, 4 Nov 2026). Never raises: the data is already committed."""
    try:
        if session.in_nested_transaction():
            return
        items = []
        for n, org_id, user_id in session.info.pop(_PENDING, []):
            identity = inspect(n).identity  # no database read: safe inside the event
            if identity:
                items.append((org_id, user_id, identity[0]))
        if items:
            _spawn(items)
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp: could not hand over committed notifications")


def _spawn(items: list[tuple[str, str, str]]) -> None:
    """ONE task per commit, however many people it notified: a sweep that
    reminds forty people must not open forty sessions at once."""
    try:
        task = asyncio.get_running_loop().create_task(_guarded(items))
    except RuntimeError:  # no running loop (a sync script): nothing to send from
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _guarded(items: list[tuple[str, str, str]]) -> None:
    try:
        await _queue_later(items)
    except Exception:  # noqa: BLE001
        logger.exception("WhatsApp: could not queue copies of %d notification(s)", len(items))


async def drain() -> None:
    """Wait for queueing still in flight (tests). A restart in that moment
    loses those copies; the in-app notifications are unaffected."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def _real_send_delay(now_utc: datetime, zone: tzinfo, org: OrgSettings | None,
                     user: User) -> int:
    """Seconds until the next working moment, judged on the organisation's
    LOCAL clock (`next_working_moment` compares wall-clock times)."""
    if org is None:
        return 0
    local = clock.to_local(now_utc, zone).replace(tzinfo=None)
    return max(0, int((next_working_moment(local, org, user) - local).total_seconds()))


send_delay = _real_send_delay


async def _org_settings(db: AsyncSession, org_id: str) -> OrgSettings | None:
    return (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
    ).scalar_one_or_none()


def recipient_number(user: User | None, cfg: whatsapp_settings.WhatsAppConfig) -> str | None:
    if user is None or not user.is_active:
        return None
    return normalise_phone(user.whatsapp_number or user.phone, cfg.country_code)


async def queue_log(db: AsyncSession, *, org_id: str, user: User, number: str, kind: str,
                    notification_id: str | None = None, local_date: str | None = None,
                    zone: tzinfo, org: OrgSettings | None) -> WhatsappLog:
    """Write the log row and queue its job (or a `skipped` row on leave)."""
    log = WhatsappLog(org_id=org_id, user_id=user.id, to_number=number, kind=kind,
                      notification_id=notification_id, local_date=local_date)
    db.add(log)
    if is_on_leave(user, clock.today(zone)):
        log.status, log.error = "skipped", "on leave"
        await db.flush()
        return log
    await db.flush()
    from app.jobs.queue import PRIORITY_SEND, job_queue

    await job_queue.enqueue(
        JOB_TYPE, {"log_id": log.id}, org_id=org_id, priority=PRIORITY_SEND,
        delay_seconds=send_delay(utcnow(), zone, org, user), max_attempts=3, db=db)
    return log


async def _queue_later(items: list[tuple[str, str, str]]) -> None:
    """One session for one commit's notifications; settings read once per
    organisation."""
    async with SessionLocal() as db:
        orgs: dict[str, tuple] = {}
        for org_id, user_id, notification_id in items:
            if org_id not in orgs:
                cfg = await whatsapp_settings.for_org(db, org_id)
                on = cfg.ready() and cfg.staff_updates
                orgs[org_id] = (cfg, on) + ((await clock.org_zone(db, org_id),
                                             await _org_settings(db, org_id)) if on else (None, None))
            cfg, on, zone, org = orgs[org_id]
            if not on:
                continue
            n = await db.get(Notification, notification_id)
            if n is None or n.kind in cfg.kinds_off:
                continue
            user = await db.get(User, user_id)
            number = recipient_number(user, cfg)
            if number is None:
                continue
            await queue_log(db, org_id=org_id, user=user, number=number, kind=n.kind,
                            notification_id=n.id, zone=zone, org=org)
        await db.commit()


# ── what the message says ────────────────────────────────────────────────


def first_name(user: User) -> str:
    from app.engines.assistant_engine import _greeting_name

    return _greeting_name(user.name)


def _due(item: ActionItem) -> str:
    return f" (due {item.due_date.day} {item.due_date:%b})" if item.due_date else ""


async def build_message(db: AsyncSession, user: User, n: Notification
                        ) -> tuple[str, dict[str, str], dict[str, Any] | None]:
    """(template, values, signed-link payload or None) for one notification."""
    name = first_name(user)
    if n.kind == "meeting_processed" and n.entity_type == "meeting" and n.entity_id:
        meeting = await db.get(Meeting, n.entity_id)
        if meeting is not None and meeting.org_id == n.org_id:
            return await _meeting_message(db, name, n, meeting)
    return "staff_update", {"name": name, "title": n.title, "detail": n.body or "-"}, None


async def _meeting_message(db: AsyncSession, name: str, n: Notification, meeting: Meeting):
    transcript = (
        await db.execute(select(Transcript).where(
            Transcript.org_id == meeting.org_id, Transcript.meeting_id == meeting.id,
            Transcript.archived_at.is_(None)))
    ).scalar_one_or_none()
    lead = await db.get(Lead, meeting.lead_id) if meeting.lead_id else None
    items = (
        await db.execute(
            select(ActionItem)
            .where(ActionItem.org_id == meeting.org_id, ActionItem.meeting_id == meeting.id)
            .order_by(ActionItem.created_at)
            .limit(_MAX_ITEMS)
        )
    ).scalars().all()
    action_items = "; ".join(f"{i.title}{_due(i)}" for i in items) or "none were found"
    summary = (transcript.summary if transcript else None) or n.title
    probe = signed_links.public_url("x")
    if transcript is not None and probe:
        return ("staff_meeting_summary",
                {"name": name, "client": lead.name if lead else "your client",
                 "summary": summary, "action_items": action_items},
                {"k": "transcript", "o": meeting.org_id, "m": meeting.id})
    return ("staff_update",
            {"name": name, "title": n.title,
             "detail": f"{summary} Action items: {action_items}"},
            None)


# ── the job ──────────────────────────────────────────────────────────────


async def handle_job(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    async with SessionLocal() as db:
        log = await db.get(WhatsappLog, payload.get("log_id"))
        if log is None:
            return {"status": "missing"}
        if log.status not in ("queued", "failed"):
            return {"status": log.status}
        cfg = await whatsapp_settings.for_org(db, log.org_id)
        user = await db.get(User, log.user_id) if log.user_id else None
        # Everything is judged again now: a message queued last night waits
        # for 09:00, and by then the admin may have switched its kind off or
        # the person may have started their leave (final review, 4 Nov 2026).
        why_not = None
        if not cfg.ready():
            why_not = "WhatsApp is not set up"
        elif not cfg.staff_updates or log.kind in cfg.kinds_off:
            why_not = "switched off by the admin"
        elif user is None or not user.is_active:
            why_not = "no such active person"
        elif is_on_leave(user, clock.today(await clock.org_zone(db, log.org_id))):
            why_not = "on leave"
        built = None if why_not else await _content(db, log, user)
        if built is None:
            log.status, log.error = "skipped", why_not or "nothing to send"
            await db.commit()
            return {"status": log.status}
        template, values, link = built
        document_url = signed_links.public_url(signed_links.make(link)) if link else None
        log.template = template
        try:
            result = await whatsapp_providers.send_template(
                cfg, org_id=log.org_id, to=log.to_number, template=template,
                values=values, document_url=document_url,
                document_name="transcript.pdf" if link else None, local_id=log.id)
        except ExternalServiceError as exc:
            log.status, log.error = "failed", str(exc)[:1000]
            await db.commit()
            raise
        except ValueError as exc:  # a message this code built wrongly: never retried
            log.status, log.error = "failed", str(exc)[:1000]
            await db.commit()
            return {"status": log.status}
        log.status = "sent" if result.ok else "failed"
        log.provider_id = result.provider_id or None
        log.error = result.error
        await db.commit()
        return {"status": log.status}


async def _content(db: AsyncSession, log: WhatsappLog, user: User):
    if log.kind == BRIEF:
        return await _brief_message(db, log, user)
    n = await db.get(Notification, log.notification_id) if log.notification_id else None
    if n is None:
        return None
    return await build_message(db, user, n)


# ── the morning brief ────────────────────────────────────────────────────


async def _brief_message(db: AsyncSession, log: WhatsappLog, user: User):
    """The person's day, built when it is sent: the same digest as Home."""
    from app.engines.assistant_engine import build_daily_digest

    digest = await build_daily_digest(db, org_id=log.org_id, user=user)
    lines = digest.content_md.splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]  # the digest's own greeting: the template greets
    day = markdown_to_line("\n".join(lines)) or "nothing is due and no meetings are booked."
    when = datetime.fromisoformat(log.local_date) if log.local_date else utcnow()
    return ("staff_daily_brief",
            {"name": first_name(user), "date": f"{when:%a} {when.day} {when:%b}", "day": day},
            None)


async def send_morning_briefs(now_utc: datetime | None = None) -> int:
    """Queue today's brief for everyone whose working day has started and who
    has not had one. Called every scheduler tick; cheap when nothing is due.
    Returns how many were queued."""
    from app.models.organisation import Organisation

    now_utc = now_utc or utcnow()
    queued = 0
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(OrgSettings)
                .join(Organisation, Organisation.id == OrgSettings.org_id)
                .where(Organisation.is_active.is_(True),
                       OrgSettings.whatsapp_integration.is_not(None))
            )
        ).scalars().all()
        orgs = []
        for row in rows:
            cfg = whatsapp_settings.load(row.whatsapp_integration)
            if cfg.ready() and cfg.staff_updates and BRIEF not in cfg.kinds_off:
                orgs.append((row, cfg))
    for org, cfg in orgs:
        try:
            queued += await _briefs_for_org(org, cfg, now_utc)
        except Exception:  # noqa: BLE001 — one organisation must not stop the rest
            logger.exception("WhatsApp morning briefs failed for %s", org.org_id)
    return queued


async def _briefs_for_org(org: OrgSettings, cfg, now_utc: datetime) -> int:
    from datetime import time as dtime

    zone = clock.zone(org.timezone)
    local = clock.to_local(now_utc, zone)
    start = parse_hhmm(org.workday_start, dtime(9, 0))
    end = parse_hhmm(org.workday_end, dtime(18, 30))
    # Only inside the working day: switched on at 19:00, "today's" brief
    # would otherwise wait until tomorrow morning and arrive beside
    # tomorrow's, under yesterday's date (final review, 4 Nov 2026).
    if not (start <= local.time() <= end) or not is_working_day(local.date(), org):
        return 0
    today = local.date().isoformat()
    count = 0
    async with SessionLocal() as db:
        users = (await db.execute(select(User).where(
            User.org_id == org.org_id, User.is_active.is_(True)))).scalars().all()
        done = set((await db.execute(select(WhatsappLog.user_id).where(
            WhatsappLog.org_id == org.org_id, WhatsappLog.kind == BRIEF,
            WhatsappLog.local_date == today))).scalars().all())
        for user in users:
            number = recipient_number(user, cfg)
            if number is None or user.id in done:
                continue
            log = await queue_log(db, org_id=org.org_id, user=user, number=number, kind=BRIEF,
                                  local_date=today, zone=zone, org=org)
            count += log.status == "queued"
        await db.commit()
    return count
