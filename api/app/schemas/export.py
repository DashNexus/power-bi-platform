"""Schemas for export jobs, export schedules, and report definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


class ExportJobRequest(BaseModel):
    """Request body for triggering a one-off export.

    Attributes:
        format: Output format - 'csv', 'xlsx', or 'pdf'.
        query_params: Query parameters used to select the data to export. A
            'sql_query' key is what the worker runs.
        source_kind: 'warehouse' or 'operations' — which database to read.
        warehouse_connection_id: Connection to query when source_kind is 'warehouse'.
        delivery_method: How to deliver the result - 'download', 'email', or 'sftp'.
        delivery_config: Delivery destination config (recipients for email, host
            and credentials for SFTP).
    """

    format: str
    query_params: dict[str, Any] = {}
    source_kind: str = "warehouse"
    warehouse_connection_id: int | None = None
    delivery_method: str = "download"
    delivery_config: dict[str, Any] | None = None


class ExportJobResponse(BaseModel):
    """Status and result of an export job.

    Attributes:
        id: Database primary key.
        format: Output format requested.
        status: Current status - 'pending', 'running', 'completed', 'failed', 'cancelled'.
        delivery_method: How the result is delivered.
        name: Report name copied at run time, so history survives a rename.
        schedule_id: Report this run came from, or None for a one-off export.
        source_kind: 'operations' or 'warehouse'.
        warehouse_connection_id: Connection queried when source_kind is 'warehouse'.
        trigger_type: 'manual' (someone pressed Run) or 'schedule' (cron fired it).
        row_count: Number of rows in the export (set on completion).
        file_path: Storage path to the exported file (set on completion).
        file_name: Suggested download filename.
        file_size_bytes: Size of the stored result.
        error_message: Error description if status is 'failed'. Also carries
            warnings on a completed run — truncation, or a delivery that failed
            after the file was written.
        created_at: When the job was created.
        started_at: When the worker picked it up.
        completed_at: When the job completed (or failed).
        expires_at: When the stored result is purged.
    """

    id: int
    format: str
    status: str
    delivery_method: str = "download"
    name: str | None = None
    schedule_id: int | None = None
    source_kind: str = "warehouse"
    warehouse_connection_id: int | None = None
    trigger_type: str = "manual"
    row_count: int | None = None
    file_path: str | None = None
    file_name: str | None = None
    file_size_bytes: int | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class ExportScheduleRequest(BaseModel):
    """Request body for creating or updating an export schedule.

    Attributes:
        name: Display name for the schedule.
        format: Output format - 'csv', 'xlsx', or 'pdf'.
        cron_expression: Cron expression for scheduling (e.g. '0 6 * * *'), or
            None for a report that only runs on demand.
        query_params: Query parameters used when the schedule runs.
        delivery_method: How to deliver results - 'download', 'email', or 'sftp'.
        delivery_config: Delivery destination config dict.
        sql_query: Custom SQL to run (makes this a report). Must be read-only.
        source_kind: 'warehouse' to query a named warehouse connection, or
            'operations' to query the application's own database.
        warehouse_connection_id: Warehouse connection to run sql_query against.
            Required when source_kind is 'warehouse'.
        is_active: Whether the schedule is active.
    """

    name: str
    format: str
    # None means on-demand only: the report runs when someone asks, never on a
    # timer. An empty string from a form field means the same thing.
    cron_expression: str | None = None
    query_params: dict[str, Any] = {}
    delivery_method: str = "download"
    delivery_config: dict[str, Any] | None = None
    sql_query: str | None = None
    source_kind: str = "warehouse"
    warehouse_connection_id: int | None = None
    is_active: bool | None = None

    @field_validator("cron_expression", mode="before")
    @classmethod
    def _blank_cron_is_none(cls, value: object) -> object:
        """Treat an empty or whitespace-only cron field as on-demand."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ExportScheduleResponse(BaseModel):
    """Export schedule details.

    Attributes:
        id: Database primary key.
        name: Display name.
        format: Output format.
        cron_expression: Cron expression, or None for an on-demand report.
        is_active: Whether the schedule is currently active.
        delivery_method: Configured delivery method.
        sql_query: Custom SQL query if this is a report.
        warehouse_connection_id: Warehouse connection for SQL reports.
        last_run_at: When the schedule last ran (if ever).
    """

    id: int
    name: str
    format: str
    cron_expression: str | None = None
    is_active: bool
    delivery_method: str = "download"
    delivery_config: dict[str, Any] | None = None
    sql_query: str | None = None
    source_kind: str = "warehouse"
    warehouse_connection_id: int | None = None
    last_run_at: datetime | None = None

    model_config = {"from_attributes": True}


class ReportRunRequest(BaseModel):
    """Request body for triggering a one-off report run.

    Attributes:
        schedule_id: ID of the report schedule to run immediately.
    """

    schedule_id: int


class ReportPreviewResponse(BaseModel):
    """Result of a report test run.

    Attributes:
        columns: Column names the query returned.
        rows: Up to EXPORT_PREVIEW_ROWS rows, each a list aligned with columns.
        row_count: How many rows the preview holds — not the size of the full
            result, which a test deliberately does not fetch.
        truncated: True when the query returned more rows than the preview cap.
        elapsed_ms: Wall-clock time the query took, so a slow one shows up
            before it is scheduled rather than after.
        source_kind: Which database the test actually ran against.
    """

    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int
    source_kind: str


class ExportDownloadResponse(BaseModel):
    """Response containing a presigned URL for downloading an export.

    Attributes:
        download_url: Presigned URL valid for a limited time.
        file_name: Suggested filename for the download.
        file_size_bytes: Size of the exported file in bytes.
    """

    download_url: str
    file_name: str
    file_size_bytes: int
