"""Per-org branding, the audit retention window, and the portal navigation.

Deliberately small: this build has no organisation-settings console. Branding is
seeded once by an operator, `audit_retention_days` is owned by the audit page
because it is a property of the audit log rather than a general org preference,
and `nav_config` is owned by `/admin/nav-config` for the same reason.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgSettings(Base):
    """Organisation-level branding and audit retention."""

    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    app_name: Mapped[str] = mapped_column(String(255), default="Power BI Platform", nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Number of days to retain audit log entries before purging (null = keep forever).
    audit_retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Admin-authored top navigation: a list of link and dropdown items that
    # replaces the defaults for the whole org. NULL means "use the defaults" —
    # the shape the API validates is `schemas/nav_config.py`. Nothing constrains
    # an href to a live resource, so `services/nav_config.py` prunes entries
    # whose resource is deleted.
    # none_as_null: SQLAlchemy's JSON type otherwise stores Python None as the
    # JSON *string* 'null', which reads back as None but does not match
    # `WHERE nav_config IS NULL` — a column that quietly disagrees with its own
    # documentation.
    nav_config: Mapped[list | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
