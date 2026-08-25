"""User favorites model — stores per-user resource bookmarks."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserFavorite(Base):
    """A single bookmarked resource belonging to a user.

    resource_type is one of 'dashboard', 'page', or 'streamlit_app'.
    resource_id is the primary key of the bookmarked row in its own table.
    """

    __tablename__ = "user_favorites"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "resource_type", "resource_id", name="uq_user_favorites"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
