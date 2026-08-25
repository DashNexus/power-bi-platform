"""Delete export schedules that carry no query.

An ``export_schedules`` row with a NULL ``sql_query`` came from the old
Schedules tab: it recorded a name, a cron expression, a format and a delivery
target, but nothing identifying *what* to export. Nothing could run one, and
nothing ever did — the worker filters them out and the UI that created them is
gone.

Leaving them would mean rows no screen shows and no code reads, which is how a
future reader concludes a feature exists. A report with a cron expression is
what replaced them.

This deletes data, so it is deliberately narrow: only rows where sql_query IS
NULL, which by construction have never produced a run.
"""

from __future__ import annotations

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove query-less export schedules."""
    # Detach any run that somehow points at one before deleting the parent: the
    # FK is NO ACTION (see models/export.py), so a stray child would block this.
    op.execute(
        "UPDATE export_jobs SET schedule_id = NULL "
        "WHERE schedule_id IN (SELECT id FROM export_schedules WHERE sql_query IS NULL)"
    )
    op.execute("DELETE FROM export_schedules WHERE sql_query IS NULL")


def downgrade() -> None:
    """No-op: the deleted rows described no exportable data.

    Recreating them would mean inventing a name and a cron for rows that could
    not run in the first place, so there is nothing faithful to restore.
    """
