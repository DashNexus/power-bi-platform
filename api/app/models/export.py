"""Async export jobs and their schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ExportJob(Base):
    """A one-off data export job requested by a user."""

    __tablename__ = "export_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # format: 'csv' | 'xlsx' | 'pdf'
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    query_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # status: 'pending' | 'running' | 'completed' | 'failed'
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Copied from the report at run time so history survives the report being
    # renamed or deleted.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # No ondelete: export_jobs already cascades from users, and so does
    # export_schedules — a second route would be SQL Server error 1785. The
    # report delete handler clears this column itself.
    schedule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("export_schedules.id"), nullable=True
    )
    # source_kind: 'warehouse' | 'operations'
    source_kind: Mapped[str] = mapped_column(
        String(32), default="warehouse", server_default="warehouse", nullable=False
    )
    warehouse_connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("warehouse_connections.id"), nullable=True
    )
    # trigger_type: 'manual' | 'schedule'. Not "trigger" — that is a reserved
    # word in T-SQL and breaks every hand-written query against this table.
    trigger_type: Mapped[str] = mapped_column(
        String(16), default="manual", server_default="manual", nullable=False
    )
    # delivery_method: 'download' | 'email' | 'sftp'
    delivery_method: Mapped[str] = mapped_column(
        String(32), default="download", nullable=False, server_default="download"
    )
    delivery_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the stored result is purged. Set on completion, not on creation, so
    # the window measures the life of the file rather than of the request.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExportSchedule(Base, TimestampMixin):
    """A recurring export schedule defined by a cron expression."""

    __tablename__ = "export_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    query_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # NULL means on-demand only: the report runs when someone asks, never on a
    # timer.
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # source_kind: 'warehouse' | 'operations'
    source_kind: Mapped[str] = mapped_column(
        String(32), default="warehouse", server_default="warehouse", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # delivery_method: 'download' | 'email' | 'sftp'
    delivery_method: Mapped[str] = mapped_column(
        String(32), default="download", nullable=False, server_default="download"
    )
    delivery_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # SQL report support — when set, the schedule runs sql_query against the warehouse
    sql_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    warehouse_connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("warehouse_connections.id"), nullable=True
    )
