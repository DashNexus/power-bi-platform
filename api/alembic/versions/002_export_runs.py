"""Make exports runnable: source selection, run history, on-demand reports.

Before this revision an export job was created with status 'running' and
nothing ever picked it up, so every job sat at 'running' for ever. These columns
are what the worker (``app.services.export_runner``) needs to execute a job,
record what happened, and expire the result.

Changes:
- export_schedules.cron_expression becomes nullable — a report with no cron is
  on-demand only.
- Both tables gain source_kind, so a report can read the operations database or
  a named warehouse connection rather than an implicit default.
- export_jobs becomes the run log: which schedule it came from, what triggered
  it, when it started, how big the result was, and when the result expires.

The column is ``trigger_type`` rather than ``trigger`` because TRIGGER is a
reserved word in T-SQL: the ORM quotes it, but every hand-written query against
the table then fails with "Incorrect syntax near the keyword 'trigger'".
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _drop_default_constraint(table: str, column: str) -> None:
    """Drop the DEFAULT constraint SQL Server auto-creates for a server_default.

    On SQL Server a server_default becomes a separate, auto-named constraint
    object, and DROP COLUMN fails while it exists ("The object
    'DF__export_jo__trigg__04AF' is dependent on column"). PostgreSQL attaches
    the default to the column itself and needs none of this.
    """
    if op.get_bind().dialect.name != "mssql":
        return
    op.execute(
        f"""
        DECLARE @name sysname;
        SELECT @name = dc.name
        FROM sys.default_constraints dc
        JOIN sys.columns c
          ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID('{table}') AND c.name = '{column}';
        IF @name IS NOT NULL
            EXEC('ALTER TABLE [{table}] DROP CONSTRAINT [' + @name + ']');
        """
    )


def upgrade() -> None:
    """Add export source selection and run-history columns."""
    # A report without a cron expression runs only when someone asks for it.
    op.alter_column(
        "export_schedules",
        "cron_expression",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.add_column(
        "export_schedules",
        sa.Column(
            "source_kind", sa.String(length=32), server_default="warehouse", nullable=False
        ),
    )

    op.add_column(
        "export_jobs",
        sa.Column(
            "source_kind", sa.String(length=32), server_default="warehouse", nullable=False
        ),
    )
    op.add_column("export_jobs", sa.Column("name", sa.String(length=255), nullable=True))
    op.add_column("export_jobs", sa.Column("schedule_id", sa.Integer(), nullable=True))
    op.add_column(
        "export_jobs", sa.Column("warehouse_connection_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "export_jobs",
        sa.Column("trigger_type", sa.String(length=16), server_default="manual", nullable=False),
    )
    op.add_column(
        "export_jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "export_jobs", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("export_jobs", sa.Column("file_size_bytes", sa.Integer(), nullable=True))
    op.add_column("export_jobs", sa.Column("file_name", sa.String(length=512), nullable=True))

    # Both foreign keys are NO ACTION on purpose. export_jobs already cascades
    # from users, and export_schedules cascades from users too; making this one
    # cascade or SET NULL would give SQL Server two delete routes from users to
    # export_jobs and it refuses that outright (error 1785). The router nulls
    # schedule_id itself when a report is deleted.
    op.create_foreign_key(
        "fk_export_jobs_schedule_id",
        "export_jobs",
        "export_schedules",
        ["schedule_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_export_jobs_warehouse_connection_id",
        "export_jobs",
        "warehouse_connections",
        ["warehouse_connection_id"],
        ["id"],
    )

    # The worker claims work with `status = 'pending' ORDER BY created_at`, and
    # the retention sweep reads expires_at; both run every tick.
    op.create_index("ix_export_jobs_status", "export_jobs", ["status", "created_at"])
    op.create_index("ix_export_jobs_expires_at", "export_jobs", ["expires_at"])
    op.create_index("ix_export_jobs_schedule_id", "export_jobs", ["schedule_id"])

    # Jobs stranded by the missing worker. They never ran, nothing produced a
    # file, and leaving them at 'running' would mean the reaper reports them as
    # timed out minutes after this deploy.
    op.execute(
        "UPDATE export_jobs "
        "SET status = 'failed', "
        "    error_message = 'Cancelled: this job predates the export worker and never ran.', "
        "    completed_at = CURRENT_TIMESTAMP "
        "WHERE status IN ('running', 'pending')"
    )


def downgrade() -> None:
    """Drop the export source and run-history columns."""
    op.drop_index("ix_export_jobs_schedule_id", table_name="export_jobs")
    op.drop_index("ix_export_jobs_expires_at", table_name="export_jobs")
    op.drop_index("ix_export_jobs_status", table_name="export_jobs")
    op.drop_constraint("fk_export_jobs_warehouse_connection_id", "export_jobs", type_="foreignkey")
    op.drop_constraint("fk_export_jobs_schedule_id", "export_jobs", type_="foreignkey")
    op.drop_column("export_jobs", "file_name")
    op.drop_column("export_jobs", "file_size_bytes")
    op.drop_column("export_jobs", "expires_at")
    op.drop_column("export_jobs", "started_at")
    _drop_default_constraint("export_jobs", "trigger_type")
    op.drop_column("export_jobs", "trigger_type")
    op.drop_column("export_jobs", "warehouse_connection_id")
    op.drop_column("export_jobs", "schedule_id")
    op.drop_column("export_jobs", "name")
    _drop_default_constraint("export_jobs", "source_kind")
    op.drop_column("export_jobs", "source_kind")
    _drop_default_constraint("export_schedules", "source_kind")
    op.drop_column("export_schedules", "source_kind")
    op.alter_column(
        "export_schedules",
        "cron_expression",
        existing_type=sa.String(length=128),
        nullable=False,
    )
