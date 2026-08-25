"""Universal change ledger recording every create/update/delete for revert.

Each row captures a single mutation to a platform resource — performed by a
human, by the AI assistant, or by the system — with a full before/after snapshot
of the affected row. Rows are immutable except for the ``reverted_*`` columns,
which are stamped when the change is undone. A ``correlation_id`` groups the
mutations of one logical action (e.g. a single assistant turn) so they can be
reverted together.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SOURCES = ("user", "ai", "system")
ACTIONS = ("create", "update", "delete")


class ChangeLedgerEntry(Base):
    """Immutable record of one resource mutation, with revert bookkeeping."""

    __tablename__ = "change_ledger"
    __table_args__ = (
        CheckConstraint(
            "source IN ('user', 'ai', 'system')", name="ck_change_ledger_source"
        ),
        CheckConstraint(
            "action IN ('create', 'update', 'delete')", name="ck_change_ledger_action"
        ),
        Index("ix_change_ledger_resource", "org_id", "resource_type", "resource_id"),
        Index("ix_change_ledger_org_created", "org_id", "created_at"),
        Index("ix_change_ledger_correlation", "correlation_id"),
        Index("ix_change_ledger_org_source", "org_id", "source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    # Groups the mutations of one logical action for unit revert.
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # Full serialized row before / after the mutation. None on create (no before)
    # and delete (no after) respectively.
    # JSONB where it exists (PostgreSQL indexes and queries it natively); plain
    # JSON — NVARCHAR(MAX) with JSON serialisation — on Azure SQL, which has no
    # binary JSON type. Nothing here queries *into* the snapshot, so the two
    # behave identically for this table's purposes.
    before: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    after: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    resource_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set when this entry is itself a revert of an earlier entry.
    revert_of_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("change_ledger.id"), nullable=True
    )
    reverted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reverted_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
