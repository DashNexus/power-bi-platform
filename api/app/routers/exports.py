"""SQL reports, their run log, and one-off export jobs.

A report is an ExportSchedule row with a sql_query. It runs read-only SQL
against a named warehouse connection or the operations database, on a cron
expression or on demand, and each run is recorded as an ExportJob — which
doubles as the run log. Execution itself belongs to app.services.export_runner;
nothing here waits for a query to finish.

There is deliberately no CRUD for an ExportSchedule *without* a query. The old
/schedules endpoints created rows carrying a name, a cron, a format and a
delivery target but nothing identifying what to export, so nothing could ever
run one. A report with a cron expression is that feature, with the missing half.

There is also deliberately no `POST /jobs`. It queued arbitrary SQL against any
source without going through `_validate_report_source`, so it was a way for a
non-admin to read the operations database and for anyone to query a warehouse
connection they had no grant on. A one-off export is a report plus a run, which
is one set of guards rather than two that must be kept in step.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_app_db
from app.middleware.auth import ROLE_HIERARCHY, CurrentUser, get_current_user
from app.models.audit import AuditLog
from app.models.export import ExportJob, ExportSchedule
from app.models.warehouse import WarehouseConnection
from app.schemas.export import (
    ExportDownloadResponse,
    ExportJobResponse,
    ExportScheduleRequest,
    ExportScheduleResponse,
    ReportPreviewResponse,
)
from app.services import change_ledger as ledger
from app.services import cron
from app.services.export_generator import VALID_FORMATS
from app.services.export_runner import RESULT_RETENTION_DAYS, cancel_job, clear_schedule_links
from app.services.export_source import (
    SOURCE_OPERATIONS,
    VALID_SOURCE_KINDS,
    ExportSourceError,
    denied_operations_tables,
    run_report_query,
)
from app.services.permissions import user_can_query_connection
from app.services.sql_guard import ReadOnlySqlError, assert_read_only
from app.storage import get_filesystem

logger = structlog.get_logger(__name__)

router = APIRouter()

_VALID_DELIVERY_METHODS = {"download", "email", "sftp"}

# Email delivery is built (services/export_delivery.py speaks SMTP) but not
# switched on: it needs SMTP credentials, a verified sender, and a decision
# about attachment size limits that has not been taken. Refused here rather than
# only hidden in the UI, so a report cannot be saved with a delivery that will
# never happen — a report that silently never arrives is worse than one that
# refuses to be created.
_UNAVAILABLE_DELIVERY_METHODS = {
    "email": "Email delivery is not available yet. Choose Download or SFTP.",
}


def _check_delivery_method(method: str) -> None:
    """Reject an unknown or not-yet-available delivery method.

    Raises:
        HTTPException: 400, with a message written for the person choosing.
    """
    if method not in _VALID_DELIVERY_METHODS:
        raise HTTPException(status_code=400, detail=f"Invalid delivery_method '{method}'")
    unavailable = _UNAVAILABLE_DELIVERY_METHODS.get(method)
    if unavailable:
        raise HTTPException(status_code=400, detail=unavailable)


def _build_delivery_config(data: ExportScheduleRequest) -> dict | None:
    """Return delivery_config from the schedule request, or None for download."""
    return data.delivery_config


# ---------------------------------------------------------------------------
# Export jobs
# ---------------------------------------------------------------------------

# The statuses and triggers a run can actually carry. An unknown value is
# rejected rather than quietly matching nothing, because a run log that answers
# "no results" to a typo looks identical to one that answers it to a real query.
# No "cancelled": export_runner.cancel_job marks a cancelled run failed with
# "Cancelled." as its message, so offering it as a filter would be an option
# that can only ever return nothing. The text search finds those runs.
_RUN_STATUSES = ("pending", "running", "completed", "failed")
_TRIGGER_TYPES = ("manual", "schedule")


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so searching for "100%" does not match everything."""
    # Order matters: the backslash itself is doubled first, or the escapes
    # added for % and _ would be doubled again in turn.
    escaped = term.replace("\\", "\\\\")
    return escaped.replace("%", "\\%").replace("_", "\\_")


def _apply_run_filters(
    stmt: Select[tuple[ExportJob]],
    *,
    search: str | None,
    status: str | None,
    trigger_type: str | None,
) -> Select[tuple[ExportJob]]:
    """Narrow a run-log query by free text, status, and what triggered the run.

    The text search covers the report name, the format, and the error message —
    the three things visible in the log, so a search matches what the person can
    see. A run whose name is NULL still matches on its error message: OR treats
    the NULL comparison as unknown rather than excluding the row.

    Raises:
        HTTPException: 400 for a status or trigger that no run can have.
    """
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        stmt = stmt.where(
            or_(
                ExportJob.name.ilike(pattern, escape="\\"),
                ExportJob.format.ilike(pattern, escape="\\"),
                ExportJob.error_message.ilike(pattern, escape="\\"),
            )
        )
    if status:
        if status not in _RUN_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of: {', '.join(_RUN_STATUSES)}",
            )
        stmt = stmt.where(ExportJob.status == status)
    if trigger_type:
        if trigger_type not in _TRIGGER_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"trigger_type must be one of: {', '.join(_TRIGGER_TYPES)}",
            )
        stmt = stmt.where(ExportJob.trigger_type == trigger_type)
    return stmt


@router.get("/jobs", response_model=list[ExportJobResponse])
async def list_jobs(
    limit: int = 100,
    search: str | None = None,
    status: str | None = None,
    trigger_type: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[ExportJobResponse]:
    """Return the current user's export runs, newest first.

    This is the run log: one row per execution, whether it came from a schedule,
    a Run now, or a one-off export.

    Filtering happens here rather than in the browser so a search covers the
    whole retained window, not just the page already loaded — a client-side
    filter over the most recent 100 runs would report "no matches" for a run
    that is sitting in the database.

    Args:
        limit: Maximum runs to return (capped at 500).
        search: Free text matched against the report name, format, and error.
        status: Exact run status to filter by.
        trigger_type: 'manual' or 'schedule'.
        current_user: Authenticated principal, scoping the log to their own runs.
        db: Application database session.
    """
    stmt = _apply_run_filters(
        select(ExportJob).where(
            ExportJob.user_id == current_user.user_id,
            ExportJob.org_id == current_user.org_id,
        ),
        search=search,
        status=status,
        trigger_type=trigger_type,
    )
    result = await db.execute(
        stmt.order_by(ExportJob.created_at.desc(), ExportJob.id.desc()).limit(
            max(1, min(limit, 500))
        )
    )
    return [ExportJobResponse.model_validate(j) for j in result.scalars().all()]


@router.get("/jobs/{job_id}", response_model=ExportJobResponse)
async def get_job(
    job_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportJobResponse:
    """Return a single export job by ID."""
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.user_id == current_user.user_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    return ExportJobResponse.model_validate(job)


@router.get("/jobs/{job_id}/download", response_model=ExportDownloadResponse)
async def download_export(
    job_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportDownloadResponse:
    """Return download information for a completed export run."""
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.user_id == current_user.user_id,
            ExportJob.org_id == current_user.org_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Export not found")
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"This run is {job.status}; there is nothing to download yet.",
        )
    if job.file_path is None:
        # A completed run whose file has been purged: 410 rather than 404, so
        # the client can tell "expired" from "never existed".
        raise HTTPException(
            status_code=410,
            detail=(
                f"The result was deleted after the {RESULT_RETENTION_DAYS}-day retention "
                "window. Run the report again."
            ),
        )
    return ExportDownloadResponse(
        download_url=job.file_path,
        file_name=job.file_name or f"export_{job.id}.{job.format}",
        file_size_bytes=job.file_size_bytes or 0,
    )


_CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get("/jobs/{job_id}/content")
async def download_export_content(
    job_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> Response:
    """Stream the stored result of a completed run.

    /download returns the storage path, which is an fsspec URI — `az://…` or
    `file:///…` — and a browser can fetch neither. This endpoint reads the bytes
    through the storage abstraction and returns them, so a download works the
    same on local disk and on Azure Blob.
    """
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.user_id == current_user.user_id,
            ExportJob.org_id == current_user.org_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Export not found")
    if job.status != "completed" or not job.file_path:
        raise HTTPException(
            status_code=409 if job.status != "completed" else 410,
            detail=(
                f"This run is {job.status}; there is nothing to download yet."
                if job.status != "completed"
                else f"The result was deleted after the {RESULT_RETENTION_DAYS}-day "
                "retention window. Run the report again."
            ),
        )

    def _read() -> bytes:
        fs = get_filesystem()
        with fs.open(job.file_path, "rb") as handle:
            return handle.read()

    try:
        payload = await asyncio.to_thread(_read)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=410, detail="The stored file is no longer available."
        ) from exc

    filename = job.file_name or f"export_{job.id}.{job.format}"
    return Response(
        content=payload,
        media_type=_CONTENT_TYPES.get(job.format, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/jobs/{job_id}/cancel", response_model=ExportJobResponse)
async def cancel_export_job(
    job_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportJobResponse:
    """Cancel a queued or running export run.

    The worker reaps a run that outlives STUCK_JOB_TIMEOUT on its own; this is
    for the case where waiting half an hour to unblock the next run of the same
    report is not acceptable. A run already marked running keeps executing in
    its worker thread — there is no way to interrupt a query mid-flight — but it
    stops blocking the report and its result is discarded.
    """
    result = await db.execute(
        select(ExportJob).where(
            ExportJob.id == job_id,
            ExportJob.user_id == current_user.user_id,
            ExportJob.org_id == current_user.org_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409, detail=f"This run has already finished ({job.status})."
        )
    await cancel_job(db, job)
    logger.info("export.job_cancelled", job_id=job_id, user_id=current_user.user_id)
    return ExportJobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# Reports (SQL-based exports, scheduled or on demand)
# ---------------------------------------------------------------------------


async def _load_report(
    db: AsyncSession, report_id: int, current_user: CurrentUser
) -> ExportSchedule:
    """Return the user's report, or raise 404.

    Scoped by user_id as well as org_id: a report carries a SQL query and a
    delivery destination its author chose, and nothing in this build shares one.
    """
    result = await db.execute(
        select(ExportSchedule).where(
            ExportSchedule.id == report_id,
            ExportSchedule.org_id == current_user.org_id,
            ExportSchedule.user_id == current_user.user_id,
            ExportSchedule.sql_query.is_not(None),
        )
    )
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


async def _validate_report_source(
    db: AsyncSession,
    data: ExportScheduleRequest,
    current_user: CurrentUser,
) -> None:
    """Reject a report whose source, SQL, or cron cannot be run.

    Every check here is repeated at execution time by export_source and
    export_runner. This copy exists so the person editing the report is told
    what is wrong while they can still fix it.

    Raises:
        HTTPException: 400 for an unusable definition, 403 for a source the
            caller may not read.
    """
    if data.source_kind not in VALID_SOURCE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"source_kind must be one of: {', '.join(sorted(VALID_SOURCE_KINDS))}",
        )

    if data.sql_query:
        try:
            assert_read_only(data.sql_query)
        except ReadOnlySqlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if data.cron_expression:
        try:
            cron.parse(data.cron_expression)
        except cron.CronError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if data.source_kind == SOURCE_OPERATIONS:
        # The operations database holds every organisation's rows, so a query
        # against it is not org-scoped the way /data is. That makes it an
        # admin-only capability rather than a report anyone can write.
        if ROLE_HIERARCHY.get(current_user.role, -1) < ROLE_HIERARCHY["admin"]:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Only an administrator can create a report against the operations "
                    "database. Pick a warehouse connection instead."
                ),
            )
        denied = denied_operations_tables(data.sql_query or "")
        if denied:
            raise HTTPException(
                status_code=400,
                detail=(
                    "These operations tables hold credentials and cannot be exported: "
                    f"{', '.join(denied)}."
                ),
            )
        return

    if data.warehouse_connection_id is None:
        raise HTTPException(
            status_code=400,
            detail="Select the warehouse connection this report should run against.",
        )
    conn = (
        await db.execute(
            select(WarehouseConnection).where(
                WarehouseConnection.id == data.warehouse_connection_id,
                WarehouseConnection.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")
    if not await user_can_query_connection(db, current_user, conn.id):
        raise HTTPException(
            status_code=403,
            detail=f"You do not have query access to '{conn.name}'.",
        )


@router.get("/reports", response_model=list[ExportScheduleResponse])
async def list_reports(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[ExportScheduleResponse]:
    """Return the current user's SQL reports, scheduled and on-demand alike."""
    result = await db.execute(
        select(ExportSchedule)
        .where(
            ExportSchedule.org_id == current_user.org_id,
            ExportSchedule.user_id == current_user.user_id,
            ExportSchedule.sql_query.is_not(None),
        )
        .order_by(ExportSchedule.created_at.desc())
    )
    return [ExportScheduleResponse.model_validate(s) for s in result.scalars().all()]


@router.post("/reports/test", response_model=ReportPreviewResponse)
async def test_report(
    data: ExportScheduleRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ReportPreviewResponse:
    """Run a report definition once and return the first rows, without saving it.

    Takes the same body as create, so the editor can test a query before the
    report exists — which is when a mistake is cheapest to fix. Nothing is
    stored, nothing is delivered, and no run is logged: this is a look at the
    data, not an execution.

    It is deliberately cheaper than a real run. Only EXPORT_PREVIEW_ROWS rows
    are fetched and the server-side timeout is EXPORT_PREVIEW_TIMEOUT_SECONDS
    rather than the full one, so testing a runaway query costs seconds rather
    than minutes.
    """
    if not data.sql_query or not data.sql_query.strip():
        raise HTTPException(status_code=400, detail="Enter a query to test.")
    await _validate_report_source(db, data, current_user)

    started = time.monotonic()
    try:
        columns, rows, truncated = await run_report_query(
            db,
            org_id=current_user.org_id,
            source_kind=data.source_kind,
            sql=data.sql_query.strip(),
            warehouse_connection_id=data.warehouse_connection_id,
            max_rows=settings.export_preview_rows,
            timeout_seconds=settings.export_preview_timeout_seconds,
        )
    except ExportSourceError as exc:
        # 400, not 500: the query is the user's input and the message is written
        # for them. The editor renders it verbatim.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "report.tested",
        user_id=current_user.user_id,
        source_kind=data.source_kind,
        rows=len(rows),
        elapsed_ms=elapsed_ms,
    )
    return ReportPreviewResponse(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
        source_kind=data.source_kind,
    )


@router.get("/reports/{report_id}", response_model=ExportScheduleResponse)
async def get_report(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportScheduleResponse:
    """Return one report, including its SQL — the editor loads this."""
    return ExportScheduleResponse.model_validate(await _load_report(db, report_id, current_user))


@router.post("/reports", response_model=ExportScheduleResponse, status_code=201)
async def create_report(
    data: ExportScheduleRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportScheduleResponse:
    """Create a SQL report.

    A report runs read-only SQL against either a named warehouse connection or
    the operations database and delivers the result. With a cron expression it
    also runs on a timer; without one it runs only when someone asks.
    """
    if not data.sql_query or not data.sql_query.strip():
        raise HTTPException(status_code=400, detail="sql_query is required for reports")
    _check_delivery_method(data.delivery_method)
    if data.format not in VALID_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid format '{data.format}'")
    await _validate_report_source(db, data, current_user)

    report = ExportSchedule(
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        name=data.name,
        format=data.format,
        cron_expression=data.cron_expression,
        query_params=data.query_params,
        is_active=True if data.is_active is None else data.is_active,
        delivery_method=data.delivery_method,
        delivery_config=_build_delivery_config(data),
        sql_query=data.sql_query.strip(),
        source_kind=data.source_kind,
        warehouse_connection_id=(
            None if data.source_kind == SOURCE_OPERATIONS else data.warehouse_connection_id
        ),
    )
    db.add(report)
    # Flushed before either log is written: until the insert reaches the
    # database the report has no id, and an audit entry or ledger snapshot
    # without one cannot be tied back to the report it describes.
    await db.flush()
    db.add(
        AuditLog(
            org_id=current_user.org_id,
            user_id=current_user.user_id,
            action="report.created",
            resource_type="report",
            resource_id=report.id,
            resource_name=report.name,
            extra={
                "name": data.name,
                "delivery_method": data.delivery_method,
                "source_kind": data.source_kind,
            },
        )
    )
    await ledger.log_create(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="report",
        obj=report,
        resource_name=report.name,
    )
    await db.commit()
    await db.refresh(report)
    logger.info("report.created", report_id=report.id, user_id=current_user.user_id)
    return ExportScheduleResponse.model_validate(report)


@router.put("/reports/{report_id}", response_model=ExportScheduleResponse)
async def update_report(
    report_id: int,
    data: ExportScheduleRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportScheduleResponse:
    """Update a SQL report.

    The whole definition is replaced, so an edit that clears the cron field
    turns a scheduled report into an on-demand one.
    """
    report = await _load_report(db, report_id, current_user)

    _check_delivery_method(data.delivery_method)
    if data.format not in VALID_FORMATS:
        raise HTTPException(status_code=400, detail=f"Invalid format '{data.format}'")
    if not data.sql_query or not data.sql_query.strip():
        raise HTTPException(status_code=400, detail="sql_query is required for reports")
    await _validate_report_source(db, data, current_user)

    before = ledger.serialize_row(report)
    report.name = data.name
    report.format = data.format
    # Assigned unconditionally: None is a meaningful value here (on-demand), so
    # the usual "only set what was provided" pattern would make it impossible to
    # remove a schedule.
    report.cron_expression = data.cron_expression
    report.sql_query = data.sql_query.strip()
    report.source_kind = data.source_kind
    report.warehouse_connection_id = (
        None if data.source_kind == SOURCE_OPERATIONS else data.warehouse_connection_id
    )
    report.delivery_method = data.delivery_method
    report.delivery_config = data.delivery_config
    if data.query_params is not None:
        report.query_params = data.query_params
    if data.is_active is not None:
        report.is_active = data.is_active

    db.add(
        AuditLog(
            org_id=current_user.org_id,
            user_id=current_user.user_id,
            action="report.updated",
            resource_type="report",
            resource_id=report.id,
            resource_name=report.name,
        )
    )
    await ledger.log_update(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="report",
        obj=report,
        before=before,
        resource_name=report.name,
    )
    await db.commit()
    await db.refresh(report)
    logger.info("report.updated", report_id=report.id, user_id=current_user.user_id)
    return ExportScheduleResponse.model_validate(report)


@router.delete("/reports/{report_id}")
async def delete_report(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict:
    """Delete a SQL report, keeping its run history."""
    report = await _load_report(db, report_id, current_user)
    report_name = report.name
    await ledger.log_delete(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="report",
        obj=report,
        resource_name=report_name,
    )
    # The FK is NO ACTION (see models/export.py), so the link has to go first or
    # the delete fails. Each run keeps its own copy of the report's name.
    await clear_schedule_links(db, report.id)
    await db.delete(report)
    db.add(
        AuditLog(
            org_id=current_user.org_id,
            user_id=current_user.user_id,
            action="report.deleted",
            resource_type="report",
            resource_id=report_id,
            resource_name=report_name,
        )
    )
    await db.commit()
    logger.info("report.deleted", report_id=report_id, user_id=current_user.user_id)
    return {"message": "Report deleted"}


@router.get("/reports/{report_id}/runs", response_model=list[ExportJobResponse])
async def list_report_runs(
    report_id: int,
    limit: int = 50,
    search: str | None = None,
    status: str | None = None,
    trigger_type: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[ExportJobResponse]:
    """Return the run history for one report, newest first.

    Takes the same filters as the org-wide run log, so the history panel under a
    report searches the report's whole retained history rather than the page of
    it already on screen.
    """
    await _load_report(db, report_id, current_user)
    stmt = _apply_run_filters(
        select(ExportJob).where(
            ExportJob.schedule_id == report_id,
            ExportJob.org_id == current_user.org_id,
        ),
        search=search,
        status=status,
        trigger_type=trigger_type,
    )
    result = await db.execute(
        stmt.order_by(ExportJob.created_at.desc(), ExportJob.id.desc()).limit(
            max(1, min(limit, 200))
        )
    )
    return [ExportJobResponse.model_validate(j) for j in result.scalars().all()]


@router.post("/reports/{report_id}/run", response_model=ExportJobResponse, status_code=201)
async def run_report_now(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> ExportJobResponse:
    """Queue an immediate run of a report.

    Returns straight away with a pending job; the export worker picks it up
    within a tick. Poll GET /exports/jobs/{id} for the outcome.
    """
    report = await _load_report(db, report_id, current_user)

    # A run that is already queued or in flight would otherwise be duplicated by
    # an impatient second click, and each one costs a full warehouse query.
    existing = (
        await db.execute(
            select(ExportJob).where(
                ExportJob.schedule_id == report.id,
                ExportJob.status.in_(("pending", "running")),
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "This report is already running. Wait for it to finish before "
                "running it again."
            ),
        )

    job = ExportJob(
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        name=report.name,
        schedule_id=report.id,
        format=report.format,
        query_params={"sql_query": report.sql_query},
        source_kind=report.source_kind,
        warehouse_connection_id=report.warehouse_connection_id,
        status="pending",
        trigger_type="manual",
        delivery_method=report.delivery_method,
        delivery_config=report.delivery_config,
    )
    db.add(job)
    db.add(
        AuditLog(
            org_id=current_user.org_id,
            user_id=current_user.user_id,
            action="report.run_now",
            resource_type="report",
            resource_id=report_id,
            resource_name=report.name,
        )
    )
    await db.flush()
    await db.commit()
    await db.refresh(job)
    logger.info("report.run_now", report_id=report_id, job_id=job.id, user_id=current_user.user_id)
    return ExportJobResponse.model_validate(job)
