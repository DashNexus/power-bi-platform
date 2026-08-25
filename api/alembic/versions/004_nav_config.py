"""Add the admin-authored portal navigation to org settings.

``org_settings.nav_config`` holds a list of nav items — each a link or a dropdown
of links — that replaces the default top navigation for every user in the org.
NULL means "use the defaults", which is what every existing row gets, so adding
the column changes nothing until an admin saves a navigation.

Plain JSON rather than JSONB: nothing queries *into* the config, it is read whole
on every page load, and Azure SQL has no binary JSON type.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nav_config column."""
    op.add_column("org_settings", sa.Column("nav_config", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drop the nav_config column.

    No default constraint to drop first — the column is nullable with no
    ``server_default``, which is the case ``002``'s helper exists for.
    """
    op.drop_column("org_settings", "nav_config")
