"""Custom HTML pages and their version history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CustomPage(Base, TimestampMixin):
    """A rich-text or markdown page authored in the admin interface."""

    __tablename__ = "custom_pages"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_custom_pages_org_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    required_role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_home_page: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )


class CustomPagePermission(Base):
    """Grants a specific user or role access to a custom page.

    A page with no permission rows is open, subject to its required_role. Once
    any grant exists the page is restricted to the granted users and roles,
    which lets custom roles — absent from the role hierarchy — be given access.
    """

    __tablename__ = "custom_page_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("custom_pages.id", ondelete="CASCADE"), nullable=False
    )
    # At least one of user_id or role_id must be set.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    role_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("roles.id"), nullable=True
    )


class CustomPageVersion(Base):
    """Immutable snapshot of a custom page's content at a point in time."""

    __tablename__ = "custom_page_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    page_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("custom_pages.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
