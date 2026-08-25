"""Declarative base and the shared timestamp mixin.

`TimestampMixin.updated_at` carries `onupdate=func.now()`, which SQL evaluates at
flush — after a snapshot is taken. The change-ledger revert excludes these columns
from its concurrency check for exactly that reason.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
