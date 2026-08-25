"""Named warehouse connection configurations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WarehouseConnection(Base, TimestampMixin):
    """A named connection to an external data warehouse.

    Stores connection parameters for supported warehouse types. Passwords are
    stored Fernet-encrypted via app.services.crypto; never access
    password_encrypted directly in API responses.

    Config keys (stored in extra_config JSON column):
        account: Snowflake account identifier (Snowflake only).
        credentials_json: Service account JSON string (BigQuery only).
        warehouse: Snowflake virtual warehouse name (Snowflake only).
        role: Snowflake role name (Snowflake only).
    """

    __tablename__ = "warehouse_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # db_type: postgresql | redshift | mysql | sqlserver | snowflake | bigquery | databricks
    db_type: Mapped[str] = mapped_column(String(32), nullable=False)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Fernet-encrypted password — never store or return plaintext
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    schemas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    extra_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WarehouseConnectionPermission(Base):
    """Grants a role access to a warehouse connection.

    Distinct from DataDictionaryPermission: this controls who can query the
    warehouse (e.g. in AI chat), whereas the data dictionary permission controls
    who can view the warehouse's data dictionary. With no rows the warehouse is
    accessible only to admins.
    """

    __tablename__ = "warehouse_connection_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    warehouse_connection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("warehouse_connections.id", ondelete="CASCADE"), nullable=False
    )
    # user_id retained for parity with other grant tables; new grants are role-scoped.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    role_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("roles.id"), nullable=True
    )
