"""Periodic scheduler: follow-up reminders, retention sweep, orphan recovery.

A lightweight asyncio loop (every 60s) with daily tasks tracked by date —
the cron of the platform.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

from sqlalchemy import select

from app.core import clock
from app.config import get_settings
from app.core.constants import FollowUpStatus, MessageStatus
from app.database import SessionLocal
from app.jobs.queue import PRIORITY_SEND, job_queue
from app.models.followup import FollowUp
from app.models.job import JobRecord
from app.models.lead import Lead
from app.models.messaging import OutboundMessage
from app.services import notification_service, retention_service

logger = logging.getLogger(__name__)

_last_daily_run: date | None = None
# The same guard on disk. The memory copy alone was lost on every restart, so
# a restart re-ran the whole daily block — ten "daily" digests in one day on
# 23 Sep 2026, and follow-up reminders repeated the same way.
_DAILY_MARKER = "scheduler_last_daily.txt"
_last_mail_poll: float = 0.0
_task: asyncio.Task | None = None


async def _daily_followup_reminders() -> None:
    """Notify owners of follow-ups due today (doc §9.4)."""
    async with SessionLocal() as db:
        # One query used to cover every tenant against ONE server date. Whose
        # "today" that was depended on where the process happened to run, and it
        # was the same answer for a Kolkata organisation and a London one. The
        # candidate set is now everything not yet reminded, and each row is
        # judged against its own organisation's calendar.
        candidates = (
            await db.execute(
                select(FollowUp).where(
                    FollowUp.status == FollowUpStatus.PENDING.value,
                    FollowUp.reminded.is_(False),
                )
            )
        ).scalars().all()
        today_by_org: dict[str, date] = {}
        due = []
        for followup in candidates:
            if followup.org_id not in today_by_org:
                today_by_org[followup.org_id] = clock.today(
                    await clock.org_zone(db, followup.org_id)
                )
            if followup.due_date <= today_by_org[followup.org_id]:
                due.append(followup)
        for followup in due:
            if not followup.owner_id:
                continue
            lead_name = (
                await db.execute(select(Lead.name).where(Lead.id == followup.lead_id))
            ).scalar_one_or_none()
            await notification_service.notify(
                db,
                org_id=followup.org_id,
                user_id=followup.owner_id,
                title=f"Follow-up due: {lead_name or 'a lead'} ({followup.channel})",
                body=followup.note,
                kind="followup_due",
                entity_type="followup",
                entity_id=followup.id,
            )
            followup.reminded = True
        await db.commit()
        if due:
            logger.info("Follow-up reminders sent: %d", len(due))


async def _recover_orphan_sends() -> None:
    """Re-enqueue approved messages whose send job vanished (crash safety)."""
    async with SessionLocal() as db:
        queued = (
            await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.status == MessageStatus.QUEUED.value
                )
            )
        ).scalars().all()
        if not queued:
            return
        active_jobs = (
            await db.execute(
                select(JobRecord).where(
                    JobRecord.type == "send_message",
                    JobRecord.status.in_(["queued", "running", "failed"]),
                )
            )
        ).scalars().all()
        active_message_ids = {j.payload.get("message_id") for j in active_jobs}
        for message in queued:
            if message.id not in active_message_ids:
                await job_queue.enqueue(
                    "send_message",
                    {"message_id": message.id},
                    org_id=message.org_id,
                    priority=PRIORITY_SEND,
                )


async def _sync_engine_sweeps() -> None:
    """The Sync Engine's daily sweep per organisation: the nudge ladder,
    commitment/reply/payment/vendor watches, overload, revivals, approvals."""
    from app.engines import sync_engine
    from app.models.organisation import Organisation

    async with SessionLocal() as db:
        org_ids = (
            await db.execute(
                select(Organisation.id).where(Organisation.is_active.is_(True))
            )
        ).scalars().all()
    for org_id in org_ids:
        async with SessionLocal() as db:
            try:
                stats = await sync_engine.daily_sweep(db, org_id=org_id)
                await db.commit()
                if any(stats.values()):
                    logger.info("Sync sweep %s: %s", org_id, stats)
            except Exception:  # noqa: BLE001 — one org's sweep never blocks another's
                logger.exception("Sync sweep failed for org %s", org_id)


async def _daily_digests_and_reports() -> None:
    """Daily personal digests for every active user; weekly client + internal
    reports on the org's report day."""
    from app.engines import assistant_engine
    from app.models.organisation import Organisation, OrgSettings
    from app.models.project import Project
    from app.models.user import User

    async with SessionLocal() as db:
        org_ids = (
            await db.execute(
                select(Organisation.id).where(Organisation.is_active.is_(True))
            )
        ).scalars().all()
    for org_id in org_ids:
        async with SessionLocal() as db:
            try:
                # No daily digest notification any more (decided 24 Sep 2026):
                # the same briefing is on Home, built fresh on every visit, and
                # the notification — opening with "Good morning, ..." —
                # flooded the notifications panel.
                settings_row = (
                    await db.execute(
                        select(OrgSettings).where(OrgSettings.org_id == org_id)
                    )
                ).scalar_one_or_none()
                report_day = settings_row.client_report_day if settings_row else "Friday"
                # The organisation's weekday, not this server's. "Friday" for a
                # Kolkata tenant starts five and a half hours before it does in
                # UTC, and the reports it gates are client-facing.
                weekday = clock.today(
                    clock.zone(settings_row.timezone if settings_row else None)
                ).strftime("%A")
                if weekday == report_day:
                    projects = (
                        await db.execute(
                            select(Project).where(
                                Project.org_id == org_id,
                                Project.status.in_(["preparation", "delivery"]),
                            )
                        )
                    ).scalars().all()
                    for project in projects:
                        await assistant_engine.build_weekly_client_report(
                            db, org_id=org_id, project=project
                        )
                        await assistant_engine.build_weekly_internal(
                            db, org_id=org_id, project=project
                        )
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.exception("Digest generation failed for org %s", org_id)


def _daily_marker():
    return get_settings().storage_path / _DAILY_MARKER


def _daily_due(today: date) -> bool:
    """Has today's daily block not run yet — in this process or before a restart?"""
    if _last_daily_run == today:
        return False
    try:
        return _daily_marker().read_text(encoding="utf-8").strip() != today.isoformat()
    except OSError:
        return True


def _mark_daily(today: date) -> None:
    global _last_daily_run
    _last_daily_run = today
    try:
        marker = _daily_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(today.isoformat(), encoding="utf-8")
    except OSError:
        logger.exception("Could not record the daily run; a restart may repeat it")


async def _loop() -> None:
    global _last_mail_poll
    while True:
        try:
            today = date.today()
            if _daily_due(today):
                _mark_daily(today)
                await _daily_followup_reminders()
                await _sync_engine_sweeps()
                await _daily_digests_and_reports()
                async with SessionLocal() as db:
                    counters = await retention_service.run_retention_sweep(db)
                    await db.commit()
                if any(counters.values()):
                    logger.info("Retention sweep: %s", counters)
            await _recover_orphan_sends()

            settings = get_settings()
            if settings.inbound_email_mode == "imap" and (
                time.monotonic() - _last_mail_poll >= settings.inbound_poll_seconds
            ):
                _last_mail_poll = time.monotonic()
                from app.jobs import mail_poller

                await mail_poller.poll_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — the scheduler must keep ticking
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(60)


async def start() -> None:
    global _task
    _task = asyncio.create_task(_loop())
    logger.info("Scheduler started")


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _task = None
