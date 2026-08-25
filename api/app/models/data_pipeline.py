"""Data pipeline (orchestrator) connection configurations.

A data pipeline connection points at an external orchestration platform —
Prefect, Azure Data Factory, and (planned) Airflow, Dagster, and others. Unlike
the legacy single global Prefect/ADF config, an org may hold many named
connections, each shareable with roles like a dashboard or warehouse.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DataPipelineConnection(Base, TimestampMixin):
    """A named connection to an external pipeline orchestration platform.

    Non-secret settings live in the ``config`` JSON column (provider-specific:
    e.g. api_url for Prefect; tenant_id/subscription_id/resource_group/
    factory_name/client_id for Azure Data Factory). The single primary secret
    (API key, password, or client secret) is Fernet-encrypted in
    ``secret_encrypted`` and never returned in API responses.
    """

    __tablename__ = "data_pipeline_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # provider key — see app.services.pipeline_providers registry
    # (prefect | adf | airflow | dagster | ...)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Fernet-encrypted primary secret — never store or return plaintext
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class DataPipelineConnectionPermission(Base):
    """Grants a role access to a data pipeline connection.

    Mirrors WarehouseConnectionPermission: with no rows the connection is
    accessible only to admins; each row shares it with a role (role-scoped
    grants; user_id retained for parity with other grant tables).
    """

    __tablename__ = "data_pipeline_connection_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    pipeline_connection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("data_pipeline_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    role_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("roles.id"), nullable=True
    )
