"""Data dictionary entries, change-log, and exclusions for warehouse tables and columns."""

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


class DataDictionaryEntry(Base, TimestampMixin):
    """A human- or AI-authored description of a warehouse table or column.

    When column_name is None the entry describes the table as a whole.
    The unique constraint ensures one entry per (org, connection, schema, table,
    column) tuple; callers must upsert rather than blindly insert.

    FK decomposition (fk_schema, fk_table, fk_column) stores the three parts
    of a foreign key reference separately so queries can filter by referenced
    table without string-splitting fk_ref. relationship_type captures the
    cardinality inferred or manually set by the catalog editor.
    """

    __tablename__ = "data_dictionary_entries"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "warehouse_connection_id",
            "schema_name",
            "table_name",
            "column_name",
            name="uq_data_dict_entry",
        ),
    )

    # Identity
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    warehouse_connection_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("warehouse_connections.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Location
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # None means this entry describes the table itself, not a specific column
    column_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Human/AI description and type
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Column structural metadata
    is_pk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Foreign key decomposition — stored as separate columns so lineage queries
    # can join on fk_table without parsing a composite fk_ref string.
    fk_schema: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fk_table: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fk_column: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Cardinality of the relationship this FK represents.
    # Valid values: "many_to_one", "one_to_one", "one_to_many", "many_to_many"
    relationship_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Governance flags
    is_pii: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DataDictionaryChangeLog(Base):
    """Immutable audit trail of field-level changes to data dictionary entries.

    Written on every PUT /data-dictionary/{id} call that changes a field value.
    Entry rows are never updated or deleted — they form an append-only log.
    The entry_id FK is SET NULL when the source entry is deleted so historical
    changes survive the entry's removal.
    """

    __tablename__ = "data_dictionary_changelog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("data_dictionary_entries.id"),
        nullable=True,
    )
    warehouse_connection_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # JSON-encoded old/new values so any type (str, bool, list) can be stored.
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataDictionaryExclusion(Base, TimestampMixin):
    """Marks a schema or table as excluded from the data dictionary UI.

    When table_name is NULL the entire schema is excluded. When table_name is
    set, only that specific table is hidden. The unique constraint prevents
    duplicate exclusion rows.
    """

    __tablename__ = "data_dictionary_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "warehouse_connection_id",
            "schema_name",
            "table_name",
            name="uq_dd_exclusion",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    warehouse_connection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("warehouse_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    schema_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # NULL means the whole schema is excluded; a value means just that table.
    table_name: Mapped[str | None] = mapped_column(String(128), nullable=True)


class DataDictionaryPermission(Base):
    """Grants a role access to a warehouse connection's data dictionary.

    When at least one DataDictionaryPermission row exists for a warehouse
    connection, access to that connection's entries is restricted to only those
    grants (plus admins). When no rows exist, any analyst+ user can view the
    data dictionary for that connection. can_edit distinguishes view-only grants
    from grants that also allow the role to modify the dictionary.
    """

    __tablename__ = "data_dictionary_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id"), nullable=False
    )
    warehouse_connection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("warehouse_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    # user_id is retained for legacy grants; new grants are role-scoped only.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    role_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("roles.id"), nullable=True
    )
    # False = view-only grant; True = the role may also edit the dictionary.
    can_edit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
