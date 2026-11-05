"""Persistent background job queue (doc §11, Figure 8).

Design goals implemented here:
  • jobs are persisted (DB) until processed — a restart loses nothing
  • prioritised: interactive work beats heavy background work
  • per-organisation fairness — no noisy neighbour (§11.7)
  • retry with exponential backoff; after max attempts -> dead-letter + alert
  • handlers are plain async functions registered by type

This runs in-process on asyncio (zero extra infrastructure). The JobRecord
contract is Celery-shaped, so swapping the executor for Celery+Redis later
changes only this module.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.core.constants import JobStatus
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.job import JobRecord

logger = logging.getLogger(__name__)

# handler(payload, job_id) -> optional result dict
JobHandler = Callable[[dict[str, Any], str], Awaitable[dict[str, Any] | None]]

PRIORITY_INTERACTIVE = 10
PRIORITY_SEND = 50
PRIORITY_BACKGROUND = 100

_BACKOFF_BASE_SECONDS = 30


class JobQueue:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._claim_lock = asyncio.Lock()
        self._running_orgs: dict[str, int] = {}
        self._stopping = False

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        org_id: str | None = None,
        priority: int = PRIORITY_BACKGROUND,
        delay_seconds: int = 0,
        max_attempts: int | None = None,
        db: Any | None = None,
    ) -> str:
        """Persist a job. Callers already inside a request transaction MUST
        pass their session as `db`: the job then commits atomically with the
        work it carries — and a second session's insert would deadlock on
        SQLite's single write lock until busy_timeout expires."""
        job = JobRecord(
            org_id=org_id,
            type=job_type,
            payload=payload,
            priority=priority,
            max_attempts=max_attempts or get_settings().job_max_attempts,
            next_run_at=utcnow() + timedelta(seconds=delay_seconds),
        )
        if db is not None:
            db.add(job)
            await db.flush()
            job_id = job.id
        else:
            async with SessionLocal() as session:
                session.add(job)
                await session.commit()
                job_id = job.id
        # Workers waking before the caller's commit just poll again within 5s.
        self._wake.set()
        return job_id

    async def start(self) -> None:
        self._stopping = False
        # Recover jobs left 'running' by a previous crash.
        async with SessionLocal() as db:
            stale = (
                await db.execute(
                    select(JobRecord).where(JobRecord.status == JobStatus.RUNNING.value)
                )
            ).scalars().all()
            for job in stale:
                job.status = JobStatus.QUEUED.value
            await db.commit()
        worker_count = get_settings().job_workers
        self._workers = [
            asyncio.create_task(self._worker_loop(i)) for i in range(worker_count)
        ]
        logger.info("Job queue started with %d workers", worker_count)

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._workers = []

    async def _claim_next(self) -> JobRecord | None:
        """Pick the next runnable job — priority first, then org fairness."""
        async with self._claim_lock:
            async with SessionLocal() as db:
                candidates = (
                    await db.execute(
                        select(JobRecord)
                        .where(
                            JobRecord.status.in_(
                                [JobStatus.QUEUED.value, JobStatus.FAILED.value]
                            ),
                            JobRecord.next_run_at <= utcnow(),
                        )
                        .order_by(JobRecord.priority, JobRecord.next_run_at)
                        .limit(25)
                    )
                ).scalars().all()
                if not candidates:
                    return None
                # Fairness: prefer a job from an org with nothing running now.
                chosen = None
                for job in candidates:
                    if self._running_orgs.get(job.org_id or "_", 0) == 0:
                        chosen = job
                        break
                if chosen is None:
                    chosen = candidates[0]
                chosen.status = JobStatus.RUNNING.value
                chosen.started_at = utcnow()
                await db.commit()
                key = chosen.org_id or "_"
                self._running_orgs[key] = self._running_orgs.get(key, 0) + 1
                return chosen

    def _release_org(self, org_id: str | None) -> None:
        key = org_id or "_"
        self._running_orgs[key] = max(0, self._running_orgs.get(key, 0) - 1)

    async def _worker_loop(self, worker_no: int) -> None:
        while not self._stopping:
            job = None
            try:
                job = await self._claim_next()
                if job is None:
                    try:
                        await asyncio.wait_for(self._wake.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                    self._wake.clear()
                    continue
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a worker must never die
                logger.exception("Worker %d crashed on a job; continuing", worker_no)
            finally:
                if job is not None:
                    self._release_org(job.org_id)

    async def _run_job(self, job: JobRecord) -> None:
        handler = self._handlers.get(job.type)
        job_id, job_type = job.id, job.type
        if handler is None:
            await self._finish(job_id, error=f"No handler for job type '{job_type}'",
                               dead_letter=True)
            return
        try:
            result = await handler(job.payload, job_id)
            await self._finish(job_id, result=result)
        except _Deferred as deferred:
            await self._defer(job_id, deferred.delay_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Job %s (%s) failed: %s", job_id, job_type, exc)
            await self._handle_failure(job_id, str(exc))

    async def _finish(
        self,
        job_id: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        dead_letter: bool = False,
    ) -> None:
        async with SessionLocal() as db:
            job = (
                await db.execute(select(JobRecord).where(JobRecord.id == job_id))
            ).scalar_one_or_none()
            if job is None:
                return
            if dead_letter:
                job.status = JobStatus.DEAD_LETTER.value
                job.last_error = error
                logger.error("Job %s dead-lettered: %s", job_id, error)
            else:
                job.status = JobStatus.DONE.value
                job.result = result
            job.finished_at = utcnow()
            await db.commit()

    async def _defer(self, job_id: str, delay_seconds: int) -> None:
        """Push a job back without burning an attempt (e.g. rate pacing)."""
        async with SessionLocal() as db:
            job = (
                await db.execute(select(JobRecord).where(JobRecord.id == job_id))
            ).scalar_one_or_none()
            if job is None:
                return
            job.status = JobStatus.QUEUED.value
            job.next_run_at = utcnow() + timedelta(seconds=delay_seconds)
            await db.commit()

    async def _handle_failure(self, job_id: str, error: str) -> None:
        async with SessionLocal() as db:
            job = (
                await db.execute(select(JobRecord).where(JobRecord.id == job_id))
            ).scalar_one_or_none()
            if job is None:
                return
            job.attempts += 1
            job.last_error = error[:2000]
            if job.attempts >= job.max_attempts:
                job.status = JobStatus.DEAD_LETTER.value
                job.finished_at = utcnow()
                logger.error(
                    "ALERT: job %s (%s) moved to dead-letter after %d attempts: %s",
                    job.id, job.type, job.attempts, error,
                )
                await self._on_dead_letter(db, job)
            else:
                backoff = _BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1))
                job.status = JobStatus.FAILED.value
                job.next_run_at = utcnow() + timedelta(seconds=backoff)
                logger.info("Job %s retry %d scheduled in %ds", job.id, job.attempts, backoff)
            await db.commit()

    async def _on_dead_letter(self, db: Any, job: JobRecord) -> None:
        """Dead-lettered sends also mark their message so nothing fails silently."""
        if job.type != "send_message":
            return
        from app.core.constants import MessageStatus
        from app.models.messaging import MessageDeliveryLog, OutboundMessage

        message_id = job.payload.get("message_id")
        if not message_id:
            return
        message = (
            await db.execute(
                select(OutboundMessage).where(OutboundMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if message is not None:
            message.status = MessageStatus.DEAD_LETTER.value
            db.add(
                MessageDeliveryLog(
                    org_id=message.org_id,
                    message_id=message.id,
                    event="dead_letter",
                    detail=job.last_error,
                )
            )


class _Deferred(Exception):
    def __init__(self, delay_seconds: int):
        super().__init__(f"deferred {delay_seconds}s")
        self.delay_seconds = delay_seconds


def defer(delay_seconds: int) -> _Deferred:
    """Raise inside a handler to re-run later without burning an attempt."""
    return _Deferred(delay_seconds)


job_queue = JobQueue()
