"""Embedded dashboards, their filters, role grants, and version snapshots.

Deleting a dashboard cascades to filters, grants, and versions — which is why the
delete handler snapshots the children into the change ledger, or a revert would
restore a dashboard stripped of both.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DashboardConfig(Base, TimestampMixin):
    """Configuration for an embedded dashboard (a Power BI report or a page URL)."""

    __tablename__ = "dashboard_configs"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_dashboard_configs_org_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    # embed_type: 'powerbi' | 'page' (see schemas/dashboard.py::EmbedType).
    # Derived from the linked BI connection's provider when one is set.
    embed_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # The BI connection whose credentials authenticate this dashboard's embed.
    bi_connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bi_connections.id"), nullable=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required_role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )


class DashboardPermission(Base):
    """Grants a specific user or role access to a dashboard."""

    __tablename__ = "dashboard_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dashboard_configs.id", ondelete="CASCADE"), nullable=False
    )
    # At least one of user_id or role_id must be set.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    role_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("roles.id"), nullable=True
    )


class DashboardFilter(Base):
    """A user-facing filter definition attached to a dashboard."""

    __tablename__ = "dashboard_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dashboard_configs.id", ondelete="CASCADE"), nullable=False
    )
    filter_key: Mapped[str] = mapped_column(String(255), nullable=False)
    filter_label: Mapped[str] = mapped_column(String(255), nullable=False)
    # filter_type: 'string' | 'date' | 'number' | 'select'
    filter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    default_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Maps this filter to a field on the authenticated user's session.
    user_attribute: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DashboardConfigVersion(Base):
    """Immutable snapshot of a dashboard configuration at a point in time."""

    __tablename__ = "dashboard_config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dashboard_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("dashboard_configs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    embed_type: Mapped[str] = mapped_column(String(32), nullable=False)
    bi_connection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bi_connections.id"), nullable=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required_role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
