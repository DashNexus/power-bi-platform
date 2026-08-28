"""Give an invitation the name fields it was already being sent, and drop department.

``POST /admin/users/invite`` has always accepted ``first_name``/``last_name``
and the admin console has always offered the inputs, but ``user_invites`` had
nowhere to keep them: they were parsed, ignored, and the account created on
accept had no name on it. The two columns close that.

``users.department`` goes the other way. This build publishes Power BI reports
to an organisation; it has no staffing model, no assignment, and nothing that
ever read the column — it was inherited from the parent platform along with the
user type, capacity, bill rate and skills fields that were never created here at
all.

Nullable with no ``server_default`` in either direction, so ``002``'s
``_drop_default_constraint`` helper is not needed.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the invitee name columns and drop the unused department column."""
    op.add_column("user_invites", sa.Column("first_name", sa.String(length=255), nullable=True))
    op.add_column("user_invites", sa.Column("last_name", sa.String(length=255), nullable=True))
    op.drop_column("users", "department")


def downgrade() -> None:
    """Restore the department column and drop the invitee name columns.

    The department values themselves are gone — the upgrade drops the column
    rather than parking the data, because nothing in this build reads it.
    """
    op.add_column("users", sa.Column("department", sa.String(length=255), nullable=True))
    op.drop_column("user_invites", "last_name")
    op.drop_column("user_invites", "first_name")
