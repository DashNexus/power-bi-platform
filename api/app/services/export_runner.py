"""Background worker that executes export jobs and fires due report schedules.

Every export job used to be created with status 'running' and nothing ever
picked it up, so jobs sat at 'running' indefinitely and no schedule ever fired.
This module is the missing half: one tick claims pending jobs, runs each
against its source, stores and delivers the result, and records the outcome.

The tick also does the housekeeping a run log needs — reclaiming jobs whose
worker died mid-run, and purging results past the retention window.

Runs as a single in-process asyncio loop guarded by a Redis lock, matching
``app.services.pipeline_poller``. Without Redis the lock degrades to "always
acquired", which is correct for a single node and is why the API's maxReplicas
is pinned to 1 in the deployment template.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.export import ExportJob, ExportSchedule
from app.services import cron, export_generator
from app.services.export_source import ExportSourceError, run_report_query
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

_TICK_SECONDS = 30

# How long a job may stay 'running' before it is presumed dead. Generous: a
# report against a slow warehouse legitimately takes minutes. The reaper exists
# so a killed worker cannot strand a job at 'running' for ever, which is exactly
# what happened before this module existed.
STUCK_JOB_TIMEOUT = timedelta(minutes=30)

# How long a completed run's file and log entry are kept.
RESULT_RETENTION_DAYS = 30

# Jobs claimed per tick. Bounded so one enormous backlog cannot monopolise the
# loop and starve schedule evaluation.
_MAX_JOBS_PER_TICK = 5


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(moment: datetime | None) -> datetime | None:
    """Attach UTC to a naive timestamp.

    SQL Server hands back naive datetimes for DATETIMEOFFSET columns through
    some driver paths; comparing one of those to an aware `now` raises
    TypeError, which inside the tick would look like an unrelated failure.
    """
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def run_job(db: AsyncSession, job: ExportJob) -> None:
    """Execute one export job to completion, recording success or failure.

    Never raises: a failed job is a recorded outcome, not a worker error.
    """
    job.status = "running"
    job.started_at = _utcnow()
    await db.commit()

    sql = (job.query_params or {}).get("sql_query")
    try:
        if not sql:
            raise ExportSourceError(
                "This job has no query. Only SQL reports can be run by the worker."
            )

        columns, rows, truncated = await run_report_query(
            db,
            org_id=job.org_id,
            source_kind=job.source_kind,
            sql=sql,
            warehouse_connection_id=job.warehouse_connection_id,
        )
        content, filename = export_generator.serialise(
            columns, rows, job.format, job.name or f"export_{job.id}"
        )
        path = export_generator.store_result(job.id, content, filename)

        # Delivery failure still leaves a usable file, so it is reported on the
        # job rather than discarding a result the user can download.
        delivery_error: str | None = None
        if job.delivery_method != "download":
            from app.services.export_delivery import deliver_export  # noqa: PLC0415

            try:
                await deliver_export(path, job.format, job.delivery_method, job.delivery_config)
            except Exception as exc:  # noqa: BLE001
                delivery_error = f"The file was generated but delivery failed: {exc}"
                logger.warning("export.delivery_failed", job_id=job.id, error=str(exc))

        now = _utcnow()
        job.status = "completed"
        job.file_path = path
        job.file_name = filename
        job.file_size_bytes = len(content)
        job.row_count = len(rows)
        job.completed_at = now
        job.expires_at = now + timedelta(days=RESULT_RETENTION_DAYS)
        notes = []
        if truncated:
            notes.append(
                f"Only the first {len(rows):,} rows were exported; the query returned more."
            )
        if delivery_error:
            notes.append(delivery_error)
        job.error_message = " ".join(notes) or None
        logger.info("export.job_completed", job_id=job.id, rows=len(rows), bytes=len(content))

    except ExportSourceError as exc:
        job.status = "failed"
        job.completed_at = _utcnow()
        job.error_message = str(exc)[:2000]
        logger.warning("export.job_failed", job_id=job.id, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — the loop must survive any job
        job.status = "failed"
        job.completed_at = _utcnow()
        job.error_message = str(exc)[:2000]
        logger.exception("export.job_error", job_id=job.id)

    await db.commit()


async def reap_stuck_jobs(db: AsyncSession, now: datetime | None = None) -> int:
    """Fail any job that has been 'running' longer than STUCK_JOB_TIMEOUT.

    Returns the number of jobs reaped.
    """
    now = now or _utcnow()
    cutoff = now - STUCK_JOB_TIMEOUT
    stuck = (
        await db.execute(
            select(ExportJob).where(
                ExportJob.status == "running",
                ExportJob.started_at.is_not(None),
                ExportJob.started_at < cutoff,
            )
        )
    ).scalars().all()

    for job in stuck:
        job.status = "failed"
        job.completed_at = now
        job.error_message = (
            f"Timed out: the job was still running after "
            f"{int(STUCK_JOB_TIMEOUT.total_seconds() // 60)} minutes and was stopped."
        )
        logger.warning("export.job_reaped", job_id=job.id)

    if stuck:
        await db.commit()
    return len(stuck)


async def enqueue_due_schedules(db: AsyncSession, now: datetime | None = None) -> int:
    """Create a job for every active schedule whose cron is due.

    A schedule with no cron expression is on-demand only and is skipped.
    Returns the number of jobs enqueued.
    """
    now = now or _utcnow()
    schedules = (
        await db.execute(
            select(ExportSchedule).where(
                is_true(ExportSchedule.is_active),
                ExportSchedule.cron_expression.is_not(None),
                ExportSchedule.sql_query.is_not(None),
            )
        )
    ).scalars().all()

    enqueued = 0
    for schedule in schedules:
        try:
            due = cron.is_due(
                schedule.cron_expression or "",
                now=now,
                last_run_at=_as_utc(schedule.last_run_at),
            )
        except cron.CronError as exc:
            # A malformed expression is the user's to fix; log once per tick
            # rather than failing the whole sweep.
            logger.warning(
                "export.schedule_bad_cron",
                schedule_id=schedule.id,
                expression=schedule.cron_expression,
                error=str(exc),
            )
            continue

        if not due:
            continue

        db.add(
            ExportJob(
                org_id=schedule.org_id,
                user_id=schedule.user_id,
                name=schedule.name,
                schedule_id=schedule.id,
                format=schedule.format,
                query_params={"sql_query": schedule.sql_query},
                source_kind=schedule.source_kind,
                warehouse_connection_id=schedule.warehouse_connection_id,
                status="pending",
                trigger_type="schedule",
                delivery_method=schedule.delivery_method,
                delivery_config=schedule.delivery_config,
            )
        )
        # Stamped now rather than on completion, so a run that takes longer than
        # the cron interval cannot be enqueued twice.
        schedule.last_run_at = now
        enqueued += 1
        logger.info("export.schedule_enqueued", schedule_id=schedule.id)

    if enqueued:
        await db.commit()
    return enqueued


async def claim_pending_jobs(db: AsyncSession, limit: int = _MAX_JOBS_PER_TICK) -> list[ExportJob]:
    """Return the oldest pending jobs, oldest first."""
    result = await db.execute(
        select(ExportJob)
        .where(ExportJob.status == "pending")
        .order_by(ExportJob.created_at, ExportJob.id)
        .limit(limit)
    )
    return list(result.scalars().all())


async def purge_expired_results(db: AsyncSession, now: datetime | None = None) -> int:
    """Delete stored files and run-log rows past the retention window.

    The file goes first: a row deleted before its file leaves an orphan nothing
    references, whereas a file deleted before its row is merely a run whose
    result is gone, which the next pass tidies.

    Returns the number of runs purged.
    """
    now = now or _utcnow()
    expired = (
        await db.execute(
            select(ExportJob).where(
                ExportJob.expires_at.is_not(None),
                ExportJob.expires_at < now,
            )
        )
    ).scalars().all()

    for job in expired:
        if job.file_path:
            await asyncio.to_thread(export_generator.delete_result, job.file_path)

    if expired:
        await db.execute(delete(ExportJob).where(ExportJob.id.in_([j.id for j in expired])))
        await db.commit()
        logger.info("export.results_purged", count=len(expired))

    # Runs that never produced a file still age out, so the log does not grow
    # without bound. expires_at is only set on completion, so failures need
    # their own cutoff.
    cutoff = now - timedelta(days=RESULT_RETENTION_DAYS)
    stale = await db.execute(
        delete(ExportJob).where(
            ExportJob.expires_at.is_(None),
            ExportJob.status.in_(("failed", "completed")),
            ExportJob.created_at < cutoff,
        )
    )
    if stale.rowcount:
        await db.commit()

    return len(expired) + (stale.rowcount or 0)


async def export_tick() -> None:
    """Run one full pass: reap, enqueue, execute, purge."""
    from app.database import AsyncSessionLocal  # noqa: PLC0415

    now = _utcnow()
    async with AsyncSessionLocal() as db:
        await reap_stuck_jobs(db, now)
        await enqueue_due_schedules(db, now)
        for job in await claim_pending_jobs(db):
            await run_job(db, job)
        await purge_expired_results(db, now)


async def run_export_worker_loop() -> None:
    """Forever loop: take a short Redis lock and run one export tick.

    Every error is swallowed so a single bad job or a brief database outage
    cannot take the worker down for the life of the process.
    """
    from app.redis import get_redis  # noqa: PLC0415

    logger.info("export_worker.started")
    while True:
        try:
            lock_ok = True
            try:
                redis_client = await get_redis()
                lock_ok = bool(
                    await redis_client.set(
                        "export_worker:lock", "1", ex=_TICK_SECONDS - 5, nx=True
                    )
                )
            except Exception:  # noqa: BLE001 — no Redis → still run (single node)
                lock_ok = True
            if lock_ok:
                await export_tick()
        except Exception as exc:  # noqa: BLE001
            logger.warning("export_worker.tick_error", error=str(exc))
        await asyncio.sleep(_TICK_SECONDS)


async def cancel_job(db: AsyncSession, job: ExportJob) -> None:
    """Mark a pending or running job cancelled."""
    job.status = "failed"
    job.completed_at = _utcnow()
    job.error_message = "Cancelled."
    await db.commit()


async def clear_schedule_links(db: AsyncSession, schedule_id: int) -> None:
    """Detach run history from a report that is being deleted.

    The foreign key is NO ACTION on purpose (see the model), so the link has to
    be cleared here or the delete fails. History is kept: the run happened, and
    the job row carries its own copy of the report's name.
    """
    await db.execute(
        update(ExportJob).where(ExportJob.schedule_id == schedule_id).values(schedule_id=None)
    )
