"""The once-a-day jobs run once a day — even across restarts — and no longer
push the daily digest as a notification (24 Sep 2026).

Reported: the notifications panel was flooded with "Good morning / Good
evening" items. They were "Your daily digest" notifications, and there were
ten in one day because the "already ran today" marker lived only in memory: a
service restart forgot it and the daily block (digests, follow-up reminders,
sweeps) ran again. The developer chose to stop the digest notification
entirely — the same briefing is on Home — and the marker now lives on disk.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs import scheduler
from app.models.user import Notification


def test_a_restart_does_not_rerun_the_daily_jobs():
    today = date(2026, 9, 24)
    scheduler._last_daily_run = None
    marker = scheduler._daily_marker()
    if marker.exists():
        marker.unlink()
    assert scheduler._daily_due(today) is True
    scheduler._mark_daily(today)
    assert scheduler._daily_due(today) is False
    scheduler._last_daily_run = None  # what a restart does to the memory copy
    assert scheduler._daily_due(today) is False
    assert scheduler._daily_due(date(2026, 9, 25)) is True
    marker.unlink()


async def test_the_daily_block_sends_no_digest_notification(org_a):
    await scheduler._daily_digests_and_reports()
    async with SessionLocal() as db:
        digests = (await db.execute(select(Notification).where(
            Notification.title == "Your daily digest"))).scalars().all()
    assert digests == []
