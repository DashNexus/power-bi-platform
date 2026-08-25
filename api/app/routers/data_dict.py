"""Data dictionary: human- and AI-authored descriptions for warehouse tables and columns."""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.data_dict import DataDictionaryPermission
from app.services import change_ledger as ledger
from app.services.permissions import (
    get_user_permission_keys,
    get_user_role_ids,
    require_permission,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# Data dictionary access is driven by data_dictionary permissions plus
# per-connection role grants (a dictionary is scoped to a warehouse connection).
DD_VIEW = "data_dictionary.view"
DD_MANAGE = "data_dictionary.manage"
_manage_dep = require_permission(DD_MANAGE)
_view_dep = require_permission(DD_VIEW, DD_MANAGE)


async def _user_role_ids(db: AsyncSession, current_user: CurrentUser) -> list[int]:
    """Return the role ids of the principal (delegates to the shared helper)."""
    return await get_user_role_ids(db, current_user)


async def _dict_conn_access(
    db: AsyncSession, current_user: CurrentUser
) -> tuple[bool, set[int]]:
    """Return (can_manage, granted_conn_ids).

    Data dictionaries are private by default — like dashboards. A non-manage user
    sees a connection's dictionary only when it is explicitly shared with one of
    their roles (or with them directly). governance.manage sees every connection.
    The broad data_dictionary.view permission enables the feature but does not, by
    itself, grant visibility of any specific dictionary.
    """
    perms = await get_user_permission_keys(db, current_user)
    can_manage = DD_MANAGE in perms

    role_ids = await _user_role_ids(db, current_user)
    grant_conditions: list[Any] = [DataDictionaryPermission.user_id == current_user.user_id]
    if role_ids:
        grant_conditions.append(DataDictionaryPermission.role_id.in_(role_ids))
    granted = {
        row[0]
        for row in (
            await db.execute(
                select(DataDictionaryPermission.warehouse_connection_id).where(
                    DataDictionaryPermission.org_id == current_user.org_id,
                    or_(*grant_conditions),
                )
            )
        ).all()
    }
    return can_manage, granted


async def _require_conn_view(
    db: AsyncSession, current_user: CurrentUser, connection_id: int
) -> None:
    """Raise 404 unless the user may view the given connection's dictionary."""
    can_manage, granted = await _dict_conn_access(db, current_user)
    if can_manage or connection_id in granted:
        return
    raise HTTPException(status_code=404, detail="Data dictionary not found")


async def _user_can_edit_connection(
    db: AsyncSession, current_user: CurrentUser, connection_id: int | None  # noqa: ARG001
) -> bool:
    """Return True when the user may edit data dictionaries.

    Editing is governed by the governance.manage role permission; per-connection
    grants control view access only.
    """
    perms = await get_user_permission_keys(db, current_user)
    return DD_MANAGE in perms


async def _require_conn_edit(
    db: AsyncSession, current_user: CurrentUser, connection_id: int | None
) -> None:
    """Raise 403 unless the user may edit the given connection's dictionary."""
    if not await _user_can_edit_connection(db, current_user, connection_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have edit access to this data dictionary",
        )


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class DataDictEntryCreate(BaseModel):
    """Fields for creating or upserting a data dictionary entry."""

    warehouse_connection_id: int | None = None
    schema_name: str
    table_name: str
    column_name: str | None = None  # None = table-level entry
    description: str | None = None
    data_type: str | None = None
    is_pii: bool = False
    tags: list[str] = []
    ai_generated: bool = False


class DataDictEntryUpdate(BaseModel):
    """Fields that may be updated on an existing entry.

    For FK fields (fk_schema, fk_table, fk_column, relationship_type), pass
    an empty string ``""`` to clear the value (set to NULL). ``None`` means
    "leave unchanged".
    """

    description: str | None = None
    data_type: str | None = None
    is_pii: bool | None = None
    tags: list[str] | None = None
    is_pk: bool | None = None
    fk_schema: str | None = None
    fk_table: str | None = None
    fk_column: str | None = None
    relationship_type: str | None = None


class PopulateRequest(BaseModel):
    """Request body for the populate endpoint."""

    warehouse_connection_id: int
    schema_name: str
    table_name: str


class PopulateAllRequest(BaseModel):
    """Request body for bulk-populate endpoint."""

    warehouse_connection_id: int
    schema_name: str


class PopulateWarehouseRequest(BaseModel):
    """Request body for full-warehouse refresh endpoint."""

    warehouse_connection_id: int


class GenerateAiRequest(BaseModel):
    """Request body for the AI description generation endpoint."""

    warehouse_connection_id: int
    schema_name: str
    table_name: str


class GenerateAiAllRequest(BaseModel):
    """Request body for bulk AI generation endpoint."""

    warehouse_connection_id: int
    schema_name: str


class ExclusionCreate(BaseModel):
    """Request body for adding a schema or table exclusion."""

    warehouse_connection_id: int
    schema_name: str
    table_name: str | None = None  # None = exclude the whole schema


class SearchRequest(BaseModel):
    """Request body for searching data dictionary entries by keyword."""

    query: str
    warehouse_connection_id: int
    limit: int = 20


class RevertWarehouseRequest(BaseModel):
    """Request body for reverting warehouse data dictionary entries to a point in time."""

    warehouse_connection_id: int
    as_of: str  # ISO 8601 datetime string
    dry_run: bool = True


def _serialize_entry(entry: Any) -> dict[str, Any]:
    """Serialize a DataDictionaryEntry ORM row to a response dict."""
    return {
        "id": entry.id,
        "org_id": entry.org_id,
        "warehouse_connection_id": entry.warehouse_connection_id,
        "schema_name": entry.schema_name,
        "table_name": entry.table_name,
        "column_name": entry.column_name,
        "description": entry.description,
        "data_type": entry.data_type,
        "is_pii": entry.is_pii,
        "tags": entry.tags,
        "ai_generated": entry.ai_generated,
        "is_pk": entry.is_pk,
        "fk_schema": entry.fk_schema,
        "fk_table": entry.fk_table,
        "fk_column": entry.fk_column,
        "relationship_type": entry.relationship_type,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _serialize_changelog(log: Any, display_name: str | None = None) -> dict[str, Any]:
    """Serialize a DataDictionaryChangeLog ORM row to a response dict."""
    return {
        "id": log.id,
        "entry_id": log.entry_id,
        "schema_name": log.schema_name,
        "table_name": log.table_name,
        "column_name": log.column_name,
        "field_name": log.field_name,
        "old_value": log.old_value,
        "new_value": log.new_value,
        "changed_by_user_id": log.changed_by_user_id,
        "changed_by_display_name": display_name,
        "changed_at": log.changed_at.isoformat(),
    }


def _serialize_exclusion(exc: Any) -> dict[str, Any]:
    """Serialize a DataDictionaryExclusion ORM row to a response dict."""
    return {
        "id": exc.id,
        "warehouse_connection_id": exc.warehouse_connection_id,
        "schema_name": exc.schema_name,
        "table_name": exc.table_name,
        "created_at": exc.created_at.isoformat(),
    }


def _parse_fk_ref(fk_ref: str) -> tuple[str | None, str | None, str | None]:
    """Parse a fk_ref string into (schema, table, column) components.

    Handles both ``schema.table.column`` (3 parts) and ``table.column``
    (2 parts) formats produced by warehouse_inspector.

    Args:
        fk_ref: Raw FK reference string from introspection metadata.

    Returns:
        Three-tuple of (fk_schema, fk_table, fk_column). fk_schema may be
        None when the reference has no schema prefix.
    """
    parts = fk_ref.split(".")
    if len(parts) == 3:  # noqa: PLR2004
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:  # noqa: PLR2004
        return None, parts[0], parts[1]
    return None, None, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_warehouse_and_conn(
    db: AsyncSession,
    org_id: int,
    warehouse_connection_id: int,
    schema_name: str,
) -> tuple[Any, dict[str, Any]]:
    """Load a WarehouseConnection and build the introspection conn_dict.

    Args:
        db: App database session.
        org_id: Requesting organisation ID (for access control).
        warehouse_connection_id: ID of the warehouse connection to load.
        schema_name: Schema to target; stored as ``schemas`` in conn_dict.

    Returns:
        Tuple of (WarehouseConnection ORM object, conn_dict for introspection).

    Raises:
        HTTPException: 404 if the connection is not found for the org.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415
    from app.services.crypto import decrypt  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == warehouse_connection_id,
            WarehouseConnection.org_id == org_id,
        )
    )
    wc = result.scalar_one_or_none()
    if wc is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    password = ""
    if wc.password_encrypted:
        try:
            password = decrypt(wc.password_encrypted)
        except Exception:
            password = ""

    conn_dict: dict[str, Any] = {
        "db_type": wc.db_type,
        "host": wc.host,
        "port": wc.port,
        "database_name": wc.database_name,
        "username": wc.username,
        "password": password,
        "schemas": [schema_name],
        "extra_config": wc.extra_config or {},
    }
    return wc, conn_dict


async def _upsert_table_columns(
    db: AsyncSession,
    org_id: int,
    warehouse_connection_id: int,
    schema_name: str,
    table_name: str,
    columns: list[dict[str, Any]],
    table_description_from_introspection: str | None,
) -> dict[str, int]:
    """Upsert data dictionary entries for a single table from introspection data.

    For new entries, description is seeded from introspection metadata when
    available. Existing user-entered descriptions are never overwritten.
    Structural metadata (is_pk, FK references) is always refreshed.
    Columns that are no longer present in the warehouse are deleted.

    Args:
        db: App database session (not committed by this function).
        org_id: Organisation ID for isolation.
        warehouse_connection_id: Source warehouse connection ID.
        schema_name: Schema the table belongs to.
        table_name: Table being populated.
        columns: Column list from warehouse_inspector introspection.
        table_description_from_introspection: Table-level description if available.

    Returns:
        Dict with ``created`` and ``skipped`` counts.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    created = 0
    skipped = 0

    # Batch-load all existing entries for this table in one query
    existing_result = await db.execute(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.org_id == org_id,
            DataDictionaryEntry.warehouse_connection_id == warehouse_connection_id,
            DataDictionaryEntry.schema_name == schema_name,
            DataDictionaryEntry.table_name == table_name,
        )
    )
    all_entries = existing_result.scalars().all()
    entries_by_col: dict[str | None, Any] = {e.column_name: e for e in all_entries}

    # Table-level entry
    tbl_entry = entries_by_col.get(None)
    if tbl_entry is None:
        db.add(
            DataDictionaryEntry(
                org_id=org_id,
                warehouse_connection_id=warehouse_connection_id,
                schema_name=schema_name,
                table_name=table_name,
                column_name=None,
                description=table_description_from_introspection,
                data_type=None,
                is_pii=False,
                tags=[],
                ai_generated=False,
            )
        )
        created += 1
    else:
        if not tbl_entry.description and table_description_from_introspection:
            tbl_entry.description = table_description_from_introspection
        skipped += 1

    current_col_names: set[str] = set()
    for col in columns:
        col_name: str = col["name"]
        current_col_names.add(col_name)
        col_type: str = col.get("type", "")
        col_is_pk: bool = bool(col.get("pk"))
        fk_ref: str | None = col.get("fk_ref")
        fk_schema_val, fk_table_val, fk_column_val = (
            _parse_fk_ref(fk_ref) if fk_ref else (None, None, None)
        )
        col_description: str | None = col.get("description")

        existing = entries_by_col.get(col_name)
        if existing is None:
            db.add(
                DataDictionaryEntry(
                    org_id=org_id,
                    warehouse_connection_id=warehouse_connection_id,
                    schema_name=schema_name,
                    table_name=table_name,
                    column_name=col_name,
                    description=col_description,
                    data_type=col_type,
                    is_pii=False,
                    tags=[],
                    ai_generated=False,
                    is_pk=col_is_pk,
                    fk_schema=fk_schema_val,
                    fk_table=fk_table_val,
                    fk_column=fk_column_val,
                )
            )
            created += 1
        else:
            # Always refresh structural metadata from introspection
            existing.is_pk = col_is_pk
            existing.fk_schema = fk_schema_val
            existing.fk_table = fk_table_val
            existing.fk_column = fk_column_val
            if not existing.description and col_description:
                existing.description = col_description
            skipped += 1

    # Remove columns that no longer exist in the warehouse
    for entry in all_entries:
        if entry.column_name is not None and entry.column_name not in current_col_names:
            await db.delete(entry)

    await db.commit()
    return {"created": created, "skipped": skipped}


async def _write_changelog(
    db: AsyncSession,
    entry: Any,
    changes: list[tuple[str, Any, Any]],
    user_id: int | None,
) -> None:
    """Append change-log rows for each (field, old_value, new_value) tuple.

    Values are JSON-encoded so any type (str, bool, list, None) can be stored.
    Call before committing so changes are atomic with the entry update.

    Args:
        db: App DB session.
        entry: The DataDictionaryEntry ORM object being modified.
        changes: List of (field_name, old_val, new_val) for fields that changed.
        user_id: ID of the user making the change; None for system/AI changes.
    """
    from app.models.data_dict import DataDictionaryChangeLog  # noqa: PLC0415

    for field_name, old_val, new_val in changes:
        db.add(
            DataDictionaryChangeLog(
                org_id=entry.org_id,
                entry_id=entry.id,
                warehouse_connection_id=entry.warehouse_connection_id,
                schema_name=entry.schema_name,
                table_name=entry.table_name,
                column_name=entry.column_name,
                field_name=field_name,
                old_value=json.dumps(old_val),
                new_value=json.dumps(new_val),
                changed_by_user_id=user_id,
            )
        )


async def _connection_or_404(
    db: AsyncSession, connection_id: int, org_id: int
) -> None:
    """Raise 404 unless the warehouse connection exists within the org."""
    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415

    exists = await db.execute(
        select(WarehouseConnection.id).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == org_id,
        )
    )
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")


@router.get("/admin/data-dictionary/{connection_id}/permissions")
async def get_dict_permissions(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, list[int]]:
    """Return the role ids granted view access to a connection's data dictionary."""
    await _connection_or_404(db, connection_id, current_user.org_id)
    perm_result = await db.execute(
        select(DataDictionaryPermission).where(
            DataDictionaryPermission.org_id == current_user.org_id,
            DataDictionaryPermission.warehouse_connection_id == connection_id,
        )
    )
    perms = perm_result.scalars().all()
    return {"role_ids": [p.role_id for p in perms if p.role_id is not None]}


@router.put("/admin/data-dictionary/{connection_id}/permissions")
async def set_dict_permissions(
    connection_id: int,
    data: dict[str, list[int]],
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str | int]:
    """Replace the roles that can access a connection's data dictionary.

    Deletes existing grants and replaces them with the supplied role ids.
    Editing the dictionary is governed by the governance.manage role permission,
    not by these grants. Pass an empty list to remove all restrictions (open to
    governance.view roles).
    """
    from sqlalchemy import delete  # noqa: PLC0415

    await _connection_or_404(db, connection_id, current_user.org_id)

    await db.execute(
        delete(DataDictionaryPermission).where(
            DataDictionaryPermission.org_id == current_user.org_id,
            DataDictionaryPermission.warehouse_connection_id == connection_id,
        )
    )

    role_ids: list[int] = data.get("role_ids", [])
    for rid in role_ids:
        db.add(DataDictionaryPermission(
            org_id=current_user.org_id,
            warehouse_connection_id=connection_id,
            role_id=rid,
        ))

    await db.commit()
    logger.info(
        "data_dict.permissions.updated",
        connection_id=connection_id,
        org_id=current_user.org_id,
        grants=len(role_ids),
    )
    return {"message": f"Permissions updated ({len(role_ids)} grants)"}


@router.get("/data-dictionary")
async def list_entries(
    warehouse_connection_id: int | None = None,
    schema_name: str | None = None,
    table_name: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return data dictionary entries, optionally filtered by warehouse, schema, or table.

    Users with data_dictionary.manage see all entries. Otherwise a user sees
    entries only for connections whose dictionary is explicitly shared with one
    of their roles (private by default, like dashboards).
    """
    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    can_manage, granted = await _dict_conn_access(db, current_user)

    query = select(DataDictionaryEntry).where(
        DataDictionaryEntry.org_id == current_user.org_id
    )

    if not can_manage:
        query = query.where(DataDictionaryEntry.warehouse_connection_id.in_(granted))

    if warehouse_connection_id is not None:
        query = query.where(DataDictionaryEntry.warehouse_connection_id == warehouse_connection_id)
    if schema_name is not None:
        query = query.where(DataDictionaryEntry.schema_name == schema_name)
    if table_name is not None:
        query = query.where(DataDictionaryEntry.table_name == table_name)

    query = query.order_by(
        DataDictionaryEntry.schema_name,
        DataDictionaryEntry.table_name,
        DataDictionaryEntry.column_name,
    )

    result = await db.execute(query)
    rows = result.scalars().all()
    return [_serialize_entry(r) for r in rows]


@router.get("/data-dictionary/warehouses")
async def list_data_dictionary_warehouses(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return warehouses that have data dictionary entries visible to the current user.

    Used by the portal data dictionary browser to populate the warehouse selector.
    Respects the same permission model as list_entries: data_dictionary.manage
    sees all; others see only connections whose dictionary is explicitly shared
    with one of their roles (private by default, like dashboards).
    """
    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415
    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415

    can_manage, granted = await _dict_conn_access(db, current_user)

    base = select(DataDictionaryEntry.warehouse_connection_id.distinct()).where(
        DataDictionaryEntry.org_id == current_user.org_id,
        DataDictionaryEntry.warehouse_connection_id.isnot(None),
    )
    if not can_manage:
        base = base.where(DataDictionaryEntry.warehouse_connection_id.in_(granted))

    id_result = await db.execute(base)
    accessible_ids: list[int] = [row[0] for row in id_result.all()]
    if not accessible_ids:
        return []

    wc_result = await db.execute(
        select(WarehouseConnection)
        .where(
            WarehouseConnection.id.in_(accessible_ids),
            WarehouseConnection.org_id == current_user.org_id,
        )
        .order_by(WarehouseConnection.name)
    )
    warehouses = wc_result.scalars().all()
    return [{"id": w.id, "name": w.name} for w in warehouses]


@router.get("/data-dictionary/tree")
async def get_tree(
    warehouse_connection_id: int,
    include_excluded: bool = False,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return the schema/table tree for a warehouse from the data dictionary.

    Only tables that have been populated appear. Excluded schemas and tables
    are filtered out unless include_excluded=true. This is a fast app-DB query
    — no warehouse connection is made — suitable for initial page load.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry, DataDictionaryExclusion  # noqa: PLC0415

    await _require_conn_view(db, current_user, warehouse_connection_id)

    # Load exclusions for this warehouse so we can filter them out
    excl_result = await db.execute(
        select(DataDictionaryExclusion).where(
            DataDictionaryExclusion.org_id == current_user.org_id,
            DataDictionaryExclusion.warehouse_connection_id == warehouse_connection_id,
        )
    )
    exclusions = excl_result.scalars().all()
    excluded_schemas: set[str] = {e.schema_name for e in exclusions if e.table_name is None}
    excluded_tables: set[tuple[str, str]] = {
        (e.schema_name, e.table_name) for e in exclusions if e.table_name is not None
    }

    result = await db.execute(
        select(
            DataDictionaryEntry.schema_name,
            DataDictionaryEntry.table_name,
        )
        .where(
            DataDictionaryEntry.org_id == current_user.org_id,
            DataDictionaryEntry.warehouse_connection_id == warehouse_connection_id,
            DataDictionaryEntry.column_name.is_(None),
        )
        .order_by(
            DataDictionaryEntry.schema_name,
            DataDictionaryEntry.table_name,
        )
        .distinct()
    )
    rows = result.all()

    # Build map with deduplication — DISTINCT handles the DB layer but we guard
    # against any edge-case duplicates in application code too.
    schema_map: dict[str, list[dict[str, Any]]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        pair = (row.schema_name, row.table_name)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        if not include_excluded:
            if row.schema_name in excluded_schemas:
                continue
            if pair in excluded_tables:
                continue

        if row.schema_name not in schema_map:
            schema_map[row.schema_name] = []
        schema_map[row.schema_name].append({
            "name": row.table_name,
            "excluded": pair in excluded_tables,
        })

    return [
        {
            "name": sname,
            "tables": tables,
            "excluded": sname in excluded_schemas,
        }
        for sname, tables in schema_map.items()
    ]


@router.post("/data-dictionary", status_code=201)
async def create_or_upsert_entry(
    data: DataDictEntryCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create or upsert a data dictionary entry.

    If an entry already exists for the same (org, warehouse_connection_id,
    schema_name, table_name, column_name) tuple, it is updated in-place.
    Requires governance.manage or an edit grant on the target connection.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    await _require_conn_edit(db, current_user, data.warehouse_connection_id)

    result = await db.execute(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.org_id == current_user.org_id,
            DataDictionaryEntry.warehouse_connection_id == data.warehouse_connection_id,
            DataDictionaryEntry.schema_name == data.schema_name,
            DataDictionaryEntry.table_name == data.table_name,
            DataDictionaryEntry.column_name == data.column_name,
        )
    )
    entry = result.scalar_one_or_none()
    is_update = entry is not None
    before = ledger.serialize_row(entry) if entry is not None else None

    if entry is not None:
        if data.description is not None:
            entry.description = data.description
        if data.data_type is not None:
            entry.data_type = data.data_type
        entry.is_pii = data.is_pii
        entry.tags = data.tags
        entry.ai_generated = data.ai_generated
    else:
        entry = DataDictionaryEntry(
            org_id=current_user.org_id,
            warehouse_connection_id=data.warehouse_connection_id,
            schema_name=data.schema_name,
            table_name=data.table_name,
            column_name=data.column_name,
            description=data.description,
            data_type=data.data_type,
            is_pii=data.is_pii,
            tags=data.tags,
            ai_generated=data.ai_generated,
        )
        db.add(entry)

    from app.services.audit import audit_action  # noqa: PLC0415
    action = "data_dict.entry_updated" if is_update else "data_dict.entry_created"
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action=action, resource_type="data_dict_entry",
        resource_name=f"{data.schema_name}.{data.table_name}.{data.column_name or '(table)'}",
        extra={"schema": data.schema_name, "table": data.table_name, "column": data.column_name},
    )

    await db.flush()
    name = f"{entry.schema_name}.{entry.table_name}.{entry.column_name or '(table)'}"
    if is_update:
        await ledger.log_update(
            db, ctx=ledger.ctx_for(current_user), resource_type="data_dict_entry", obj=entry,
            before=before or {}, resource_name=name,
        )
    else:
        await ledger.log_create(
            db, ctx=ledger.ctx_for(current_user), resource_type="data_dict_entry", obj=entry,
            resource_name=name,
        )

    await db.commit()
    await db.refresh(entry)
    return _serialize_entry(entry)


@router.put("/data-dictionary/{entry_id}")
async def update_entry(
    entry_id: int,
    data: DataDictEntryUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update description, PII flag, tags, or FK annotations on a data dictionary entry.

    For FK string fields (fk_schema, fk_table, fk_column, relationship_type),
    pass an empty string to clear the stored value. Pass None to leave it unchanged.
    Requires governance.manage or an edit grant on the entry's connection.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    result = await db.execute(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.id == entry_id,
            DataDictionaryEntry.org_id == current_user.org_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Data dictionary entry not found")

    await _require_conn_edit(db, current_user, entry.warehouse_connection_id)
    before = ledger.serialize_row(entry)

    # Snapshot old values before modification so we can log the diff.
    changes: list[tuple[str, Any, Any]] = []

    if data.description is not None and data.description != entry.description:
        changes.append(("description", entry.description, data.description))
        entry.description = data.description
    if data.data_type is not None and data.data_type != entry.data_type:
        changes.append(("data_type", entry.data_type, data.data_type))
        entry.data_type = data.data_type
    if data.is_pii is not None and data.is_pii != entry.is_pii:
        changes.append(("is_pii", entry.is_pii, data.is_pii))
        entry.is_pii = data.is_pii
    if data.tags is not None and data.tags != list(entry.tags or []):
        changes.append(("tags", list(entry.tags or []), data.tags))
        entry.tags = data.tags
    if data.is_pk is not None and data.is_pk != entry.is_pk:
        changes.append(("is_pk", entry.is_pk, data.is_pk))
        entry.is_pk = data.is_pk

    # Empty string signals "clear this value"; non-None non-empty updates it.
    for field in ("fk_schema", "fk_table", "fk_column", "relationship_type"):
        raw_val: str | None = getattr(data, field)
        if raw_val is None:
            continue
        new_val: str | None = None if raw_val == "" else raw_val
        old_val: str | None = getattr(entry, field)
        if new_val != old_val:
            changes.append((field, old_val, new_val))
        setattr(entry, field, new_val)

    if changes:
        await _write_changelog(db, entry, changes, current_user.user_id)

    if changes:
        from app.services.audit import audit_action  # noqa: PLC0415
        await audit_action(
            db, org_id=current_user.org_id, user_id=current_user.user_id,
            action="data_dict.entry_updated", resource_type="data_dict_entry",
            resource_id=entry_id,
            resource_name=f"{entry.schema_name}.{entry.table_name}.{entry.column_name or '(table)'}",
            extra={"fields_changed": [c[0] for c in changes]},
        )
        # The per-field DataDictionaryChangeLog above keeps its point-in-time
        # revert; additionally record a ledger row so the entry shows in the
        # global/AI feed and reverts uniformly with everything else.
        await ledger.log_update(
            db, ctx=ledger.ctx_for(current_user), resource_type="data_dict_entry", obj=entry,
            before=before,
            resource_name=f"{entry.schema_name}.{entry.table_name}.{entry.column_name or '(table)'}",
        )

    await db.commit()
    await db.refresh(entry)
    return _serialize_entry(entry)


@router.delete("/data-dictionary/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Delete a data dictionary entry.

    Requires governance.manage or an edit grant on the entry's connection.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    result = await db.execute(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.id == entry_id,
            DataDictionaryEntry.org_id == current_user.org_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Data dictionary entry not found")

    await _require_conn_edit(db, current_user, entry.warehouse_connection_id)

    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.entry_deleted", resource_type="data_dict_entry",
        resource_id=entry_id,
        resource_name=f"{entry.schema_name}.{entry.table_name}.{entry.column_name or '(table)'}",
    )
    await ledger.log_delete(
        db, ctx=ledger.ctx_for(current_user), resource_type="data_dict_entry", obj=entry,
        resource_name=f"{entry.schema_name}.{entry.table_name}.{entry.column_name or '(table)'}",
    )
    await db.delete(entry)
    await db.commit()


@router.get("/data-dictionary/relationships")
async def list_relationships(
    warehouse_connection_id: int,
    schema_names: str | None = None,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return all FK-annotated column entries as a relationship list.

    Only entries where fk_table is set are included. Useful for building
    lineage graphs and relationship views without loading all entries.

    Args:
        warehouse_connection_id: Filter to this warehouse connection.
        schema_names: Optional comma-separated list of schema names to include.

    Returns:
        List of relationship dicts with from_table, from_col, to_table,
        to_col, relation_type, and label keys.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    query = select(DataDictionaryEntry).where(
        DataDictionaryEntry.org_id == current_user.org_id,
        DataDictionaryEntry.warehouse_connection_id == warehouse_connection_id,
        DataDictionaryEntry.fk_table.isnot(None),
    )

    if schema_names:
        names = [s.strip() for s in schema_names.split(",") if s.strip()]
        if names:
            query = query.where(DataDictionaryEntry.schema_name.in_(names))

    result = await db.execute(query)
    rows = result.scalars().all()

    out: list[dict[str, Any]] = []
    for row in rows:
        from_table = (
            f"{row.schema_name}.{row.table_name}" if row.schema_name else row.table_name
        )
        to_schema = row.fk_schema or ""
        to_table = (
            f"{to_schema}.{row.fk_table}" if to_schema else (row.fk_table or "")
        )
        out.append(
            {
                "from_table": from_table,
                "from_col": row.column_name or "",
                "to_table": to_table,
                "to_col": row.fk_column or "",
                "relation_type": row.relationship_type or "many_to_one",
                "label": "",
            }
        )
    return out


@router.post("/data-dictionary/populate")
async def populate_entries(
    data: PopulateRequest,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Introspect a warehouse table and create skeleton dictionary entries for each column.

    For new entries, description is seeded from introspection metadata when
    available. Existing user-entered descriptions are never overwritten;
    however, is_pk and FK reference columns are always refreshed from the
    latest introspection data.
    """
    from app.services.warehouse_inspector import introspect_schemas  # noqa: PLC0415

    _wc, conn_dict = await _load_warehouse_and_conn(
        db, current_user.org_id, data.warehouse_connection_id, data.schema_name
    )

    try:
        schema_data = await introspect_schemas(conn_dict, target_schemas=[data.schema_name])
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to introspect warehouse: {exc}"
        ) from exc

    columns: list[dict[str, Any]] = []
    table_description_from_introspection: str | None = None
    for schema_entry in schema_data:
        for table_entry in schema_entry.get("tables", []):
            if table_entry["name"] == data.table_name:
                columns = table_entry.get("columns", [])
                table_description_from_introspection = table_entry.get("description")
                break

    if not columns:
        raise HTTPException(
            status_code=404,
            detail=f"Table '{data.schema_name}.{data.table_name}' not found in warehouse",
        )

    counts = await _upsert_table_columns(
        db,
        current_user.org_id,
        data.warehouse_connection_id,
        data.schema_name,
        data.table_name,
        columns,
        table_description_from_introspection,
    )

    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.table_populated", resource_type="data_dict_table",
        resource_name=f"{data.schema_name}.{data.table_name}",
        extra={"schema": data.schema_name, "table": data.table_name, **counts},
    )
    await db.commit()

    logger.info(
        "data_dict.populate",
        org_id=current_user.org_id,
        schema=data.schema_name,
        table=data.table_name,
        **counts,
    )
    return {
        "schema_name": data.schema_name,
        "table_name": data.table_name,
        **counts,
    }


@router.post("/data-dictionary/populate-all")
async def populate_all_entries(
    data: PopulateAllRequest,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Populate data dictionary entries for every table in a schema.

    Introspects the full schema in one pass, then upserts column entries for
    each table. Existing user descriptions are never overwritten; structural
    metadata (is_pk, FK references) is always refreshed.

    Returns:
        Summary dict with tables_processed, total_created, total_skipped,
        and a per-table breakdown.
    """
    from app.services.warehouse_inspector import introspect_schemas  # noqa: PLC0415

    _wc, conn_dict = await _load_warehouse_and_conn(
        db, current_user.org_id, data.warehouse_connection_id, data.schema_name
    )

    try:
        schema_data = await introspect_schemas(conn_dict, target_schemas=[data.schema_name])
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to introspect warehouse: {exc}"
        ) from exc

    tables_processed = 0
    total_created = 0
    total_skipped = 0
    current_table_names: set[str] = set()

    for schema_entry in schema_data:
        if schema_entry.get("name") != data.schema_name:
            continue
        for table_entry in schema_entry.get("tables", []):
            table_name: str = table_entry["name"]
            if table_name in current_table_names:
                # Skip duplicate table names returned by introspection
                continue
            current_table_names.add(table_name)
            columns: list[dict[str, Any]] = table_entry.get("columns", [])
            if not columns:
                continue
            counts = await _upsert_table_columns(
                db,
                current_user.org_id,
                data.warehouse_connection_id,
                data.schema_name,
                table_name,
                columns,
                table_entry.get("description"),
            )
            tables_processed += 1
            total_created += counts["created"]
            total_skipped += counts["skipped"]

    # Remove entries for tables no longer present in the warehouse schema
    if current_table_names:
        from sqlalchemy import delete  # noqa: PLC0415

        from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

        await db.execute(
            delete(DataDictionaryEntry).where(
                DataDictionaryEntry.org_id == current_user.org_id,
                DataDictionaryEntry.warehouse_connection_id == data.warehouse_connection_id,
                DataDictionaryEntry.schema_name == data.schema_name,
                DataDictionaryEntry.table_name.notin_(current_table_names),
            )
        )
        await db.commit()

    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.schema_populated", resource_type="data_dict_schema",
        resource_name=data.schema_name,
        extra={
            "schema": data.schema_name,
            "tables_processed": tables_processed,
            "total_created": total_created,
            "total_skipped": total_skipped,
        },
    )
    await db.commit()

    logger.info(
        "data_dict.populate_all",
        org_id=current_user.org_id,
        schema=data.schema_name,
        tables_processed=tables_processed,
        total_created=total_created,
        total_skipped=total_skipped,
    )
    return {
        "schema_name": data.schema_name,
        "tables_processed": tables_processed,
        "total_created": total_created,
        "total_skipped": total_skipped,
    }


@router.post("/data-dictionary/populate-warehouse")
async def populate_warehouse_entries(
    data: PopulateWarehouseRequest,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Populate data dictionary entries for all schemas in a warehouse.

    Iterates every schema configured on the warehouse connection, introspects
    each one in turn, and upserts column entries. Removes stale tables from
    schemas that are still present but no longer contain those tables.

    Returns:
        Summary dict with schemas_processed, tables_processed, total_created,
        total_skipped.
    """
    from sqlalchemy import (
        delete,  # noqa: PLC0415
        select,  # noqa: PLC0415
    )

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415
    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415
    from app.services.crypto import decrypt  # noqa: PLC0415
    from app.services.warehouse_inspector import introspect_schemas  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == data.warehouse_connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    wc = result.scalar_one_or_none()
    if wc is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    password = ""
    if wc.password_encrypted:
        try:
            password = decrypt(wc.password_encrypted)
        except Exception:
            password = ""

    schema_names: list[str] = wc.schemas or []
    if not schema_names:
        raise HTTPException(status_code=422, detail="Warehouse connection has no schemas configured")

    conn_dict: dict[str, Any] = {
        "db_type": wc.db_type,
        "host": wc.host,
        "port": wc.port,
        "database_name": wc.database_name,
        "username": wc.username,
        "password": password,
        "schemas": schema_names,
        "extra_config": wc.extra_config or {},
    }

    try:
        schema_data = await introspect_schemas(conn_dict, target_schemas=schema_names)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to introspect warehouse: {exc}"
        ) from exc

    schemas_processed = 0
    tables_processed = 0
    total_created = 0
    total_skipped = 0
    seen_schema_names: set[str] = set()

    for schema_entry in schema_data:
        schema_name = schema_entry.get("name", "")
        if not schema_name:
            continue
        if schema_name in seen_schema_names:
            continue
        seen_schema_names.add(schema_name)
        schemas_processed += 1
        current_table_names: set[str] = set()

        for table_entry in schema_entry.get("tables", []):
            table_name: str = table_entry["name"]
            if table_name in current_table_names:
                continue
            current_table_names.add(table_name)
            columns: list[dict[str, Any]] = table_entry.get("columns", [])
            if not columns:
                continue
            counts = await _upsert_table_columns(
                db,
                current_user.org_id,
                data.warehouse_connection_id,
                schema_name,
                table_name,
                columns,
                table_entry.get("description"),
            )
            tables_processed += 1
            total_created += counts["created"]
            total_skipped += counts["skipped"]

        if current_table_names:
            await db.execute(
                delete(DataDictionaryEntry).where(
                    DataDictionaryEntry.org_id == current_user.org_id,
                    DataDictionaryEntry.warehouse_connection_id == data.warehouse_connection_id,
                    DataDictionaryEntry.schema_name == schema_name,
                    DataDictionaryEntry.table_name.notin_(current_table_names),
                )
            )
            await db.commit()

    # Remove entries for schemas no longer present in the warehouse — catches
    # both truly removed schemas and schemas stored under a different casing
    # from a prior run (e.g. "dimensions" vs "DIMENSIONS").
    if seen_schema_names:
        await db.execute(
            delete(DataDictionaryEntry).where(
                DataDictionaryEntry.org_id == current_user.org_id,
                DataDictionaryEntry.warehouse_connection_id == data.warehouse_connection_id,
                DataDictionaryEntry.schema_name.notin_(seen_schema_names),
            )
        )
        await db.commit()

    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.warehouse_populated", resource_type="data_dict_warehouse",
        extra={
            "warehouse_connection_id": data.warehouse_connection_id,
            "schemas_processed": schemas_processed,
            "tables_processed": tables_processed,
            "total_created": total_created,
            "total_skipped": total_skipped,
        },
    )
    await db.commit()

    logger.info(
        "data_dict.populate_warehouse",
        org_id=current_user.org_id,
        warehouse_connection_id=data.warehouse_connection_id,
        schemas_processed=schemas_processed,
        tables_processed=tables_processed,
        total_created=total_created,
        total_skipped=total_skipped,
    )
    return {
        "schemas_processed": schemas_processed,
        "tables_processed": tables_processed,
        "total_created": total_created,
        "total_skipped": total_skipped,
    }


@router.post("/data-dictionary/search")
async def search_entries(
    data: SearchRequest,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Search data dictionary entries by keyword across all tables in a warehouse.

    Uses PostgreSQL ILIKE across column_name, table_name, description, and tags.

    Args:
        data.query: Free-text search string.
        data.warehouse_connection_id: Restrict search to this warehouse.
        data.limit: Maximum number of entries to return.

    Returns:
        Ranked list of matching data dictionary entry dicts.
    """
    from sqlalchemy import String, cast, or_, select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryEntry  # noqa: PLC0415

    q = data.query.strip()
    if not q:
        return []

    like_q = f"%{q}%"

    candidate_limit = data.limit
    sql = (
        select(DataDictionaryEntry)
        .where(
            DataDictionaryEntry.org_id == current_user.org_id,
            DataDictionaryEntry.warehouse_connection_id == data.warehouse_connection_id,
            or_(
                DataDictionaryEntry.column_name.ilike(like_q),
                DataDictionaryEntry.table_name.ilike(like_q),
                DataDictionaryEntry.description.ilike(like_q),
                cast(DataDictionaryEntry.tags, String).ilike(like_q),
            ),
        )
        .limit(candidate_limit)
    )
    result = await db.execute(sql)
    candidates = result.scalars().all()

    if not candidates:
        return []

    return [_serialize_entry(r) for r in candidates[: data.limit]]


# ---------------------------------------------------------------------------
# Point-in-time revert endpoint
# ---------------------------------------------------------------------------


@router.post("/data-dictionary/revert-to-point-in-time")
async def revert_warehouse_to_point_in_time(
    data: RevertWarehouseRequest,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Revert all data dictionary entries for a warehouse to their state at a given moment.

    For each (entry, field) pair, finds the most recent change log entry at or
    before ``as_of`` and restores ``new_value`` from that log row. If there are
    no log entries before ``as_of`` for a field, restores ``old_value`` from the
    earliest log entry after ``as_of`` (the value that existed before the first
    recorded change). Fields with no log history at all are left untouched.

    When ``dry_run=true`` (default) no rows are modified — the response describes
    what *would* change. Set ``dry_run=false`` to apply.

    Returns:
        Dict with ``as_of``, ``changes_required``, ``changes_applied``,
        ``dry_run``, and a ``changes`` list of per-field change descriptors.
    """
    from collections import defaultdict  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryChangeLog, DataDictionaryEntry  # noqa: PLC0415

    try:
        as_of_dt = datetime.fromisoformat(data.as_of)
        if as_of_dt.tzinfo is None:
            as_of_dt = as_of_dt.replace(tzinfo=UTC)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid datetime: {exc}") from exc

    def _to_aware(dt: datetime) -> datetime:
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt

    # Load all changelog entries for this warehouse (entry_id may be NULL for deleted entries)
    logs_result = await db.execute(
        select(DataDictionaryChangeLog)
        .where(
            DataDictionaryChangeLog.org_id == current_user.org_id,
            DataDictionaryChangeLog.warehouse_connection_id == data.warehouse_connection_id,
            DataDictionaryChangeLog.entry_id.isnot(None),
        )
        .order_by(DataDictionaryChangeLog.changed_at.asc())
    )
    all_logs = logs_result.scalars().all()

    # Group logs by (entry_id, field_name)
    logs_by_key: dict[tuple[int, str], list[Any]] = defaultdict(list)
    for log in all_logs:
        logs_by_key[(log.entry_id, log.field_name)].append(log)  # type: ignore[index]

    # Determine target value at as_of for each (entry_id, field_name)
    targets: dict[tuple[int, str], Any] = {}
    for (entry_id, field_name), logs in logs_by_key.items():
        before = [l for l in logs if _to_aware(l.changed_at) <= as_of_dt]
        after = [l for l in logs if _to_aware(l.changed_at) > as_of_dt]

        if before:
            # Latest change at-or-before as_of: new_value is the state at as_of
            latest = max(before, key=lambda l: _to_aware(l.changed_at))
            targets[(entry_id, field_name)] = (
                json.loads(latest.new_value) if latest.new_value is not None else None
            )
        elif after:
            # No changes before as_of — earliest change after as_of records what existed before it
            earliest = min(after, key=lambda l: _to_aware(l.changed_at))
            targets[(entry_id, field_name)] = (
                json.loads(earliest.old_value) if earliest.old_value is not None else None
            )

    if not targets:
        return {
            "as_of": data.as_of,
            "changes_required": 0,
            "changes_applied": 0,
            "dry_run": data.dry_run,
            "changes": [],
        }

    # Load all affected entries
    affected_ids = {k[0] for k in targets}
    entries_result = await db.execute(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.id.in_(affected_ids),
            DataDictionaryEntry.org_id == current_user.org_id,
        )
    )
    entries_by_id: dict[int, Any] = {e.id: e for e in entries_result.scalars().all()}

    changes_required = 0
    changes_applied = 0
    change_summary: list[dict[str, Any]] = []

    for (entry_id, field_name), target_value in targets.items():
        entry = entries_by_id.get(entry_id)
        if entry is None:
            continue

        current_value: Any = getattr(entry, field_name, None)

        # Normalize lists for comparison (order-insensitive for tags)
        def _comparable(v: Any) -> Any:
            if isinstance(v, list):
                return sorted(str(x) for x in v)
            return v

        if _comparable(current_value) == _comparable(target_value):
            continue

        changes_required += 1
        change_summary.append(
            {
                "entry_id": entry_id,
                "schema": entry.schema_name,
                "table": entry.table_name,
                "column": entry.column_name,
                "field": field_name,
                "current": current_value,
                "target": target_value,
            }
        )

        if not data.dry_run:
            if field_name == "tags":
                entry.tags = target_value if isinstance(target_value, list) else []
                flag_modified(entry, "tags")
            else:
                setattr(entry, field_name, target_value)
            await _write_changelog(
                db, entry, [(field_name, current_value, target_value)], current_user.user_id
            )
            changes_applied += 1

    if not data.dry_run and changes_applied > 0:
        from app.services.audit import audit_action  # noqa: PLC0415
        await audit_action(
            db, org_id=current_user.org_id, user_id=current_user.user_id,
            action="data_dict.point_in_time_reverted", resource_type="data_dict_warehouse",
            extra={
                "warehouse_connection_id": data.warehouse_connection_id,
                "as_of": data.as_of,
                "changes_applied": changes_applied,
            },
        )
        await db.commit()
        logger.info(
            "data_dict.point_in_time_reverted",
            org_id=current_user.org_id,
            warehouse_connection_id=data.warehouse_connection_id,
            as_of=data.as_of,
            changes_applied=changes_applied,
        )

    return {
        "as_of": data.as_of,
        "changes_required": changes_required,
        "changes_applied": changes_applied,
        "dry_run": data.dry_run,
        "changes": change_summary,
    }


# ---------------------------------------------------------------------------
# Change-log endpoints
# ---------------------------------------------------------------------------


@router.get("/data-dictionary/{entry_id}/changes")
async def list_entry_changes(
    entry_id: int,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return the change-log for a single data dictionary entry, newest first."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryChangeLog  # noqa: PLC0415
    from app.models.user import User  # noqa: PLC0415

    result = await db.execute(
        select(DataDictionaryChangeLog)
        .where(
            DataDictionaryChangeLog.entry_id == entry_id,
            DataDictionaryChangeLog.org_id == current_user.org_id,
        )
        .order_by(DataDictionaryChangeLog.changed_at.desc())
    )
    logs = result.scalars().all()

    # Resolve display names for all user IDs in one query
    user_ids = {log.changed_by_user_id for log in logs if log.changed_by_user_id is not None}
    display_names: dict[int, str] = {}
    if user_ids:
        users_result = await db.execute(
            select(User).where(User.id.in_(user_ids))
        )
        for u in users_result.scalars().all():
            display_names[u.id] = (
                u.display_name
                or (f"{u.first_name} {u.last_name}".strip() if u.first_name or u.last_name else None)
                or u.email
            )

    return [
        _serialize_changelog(r, display_names.get(r.changed_by_user_id) if r.changed_by_user_id else None)
        for r in logs
    ]


@router.post("/data-dictionary/{entry_id}/revert/{log_id}")
async def revert_entry_to_log(
    entry_id: int,
    log_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Revert a single field on a data dictionary entry to its value before a log entry.

    Loads the change-log row, restores old_value to the field, and writes a new
    log entry recording the revert. Returns the updated entry. Requires
    governance.manage or an edit grant on the entry's connection.
    """
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryChangeLog, DataDictionaryEntry  # noqa: PLC0415

    log_result = await db.execute(
        select(DataDictionaryChangeLog).where(
            DataDictionaryChangeLog.id == log_id,
            DataDictionaryChangeLog.org_id == current_user.org_id,
            DataDictionaryChangeLog.entry_id == entry_id,
        )
    )
    log_entry = log_result.scalar_one_or_none()
    if log_entry is None:
        raise HTTPException(status_code=404, detail="Change log entry not found")

    entry_result = await db.execute(
        select(DataDictionaryEntry).where(
            DataDictionaryEntry.id == entry_id,
            DataDictionaryEntry.org_id == current_user.org_id,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Data dictionary entry not found")

    await _require_conn_edit(db, current_user, entry.warehouse_connection_id)

    reverted_value: Any = (
        json.loads(log_entry.old_value) if log_entry.old_value is not None else None
    )
    current_value: Any = getattr(entry, log_entry.field_name, None)

    # Apply the reverted value
    if log_entry.field_name == "tags":
        entry.tags = reverted_value if isinstance(reverted_value, list) else []
        flag_modified(entry, "tags")
    else:
        setattr(entry, log_entry.field_name, reverted_value)

    # Record the revert as a new changelog row
    db.add(
        DataDictionaryChangeLog(
            org_id=entry.org_id,
            entry_id=entry.id,
            warehouse_connection_id=entry.warehouse_connection_id,
            schema_name=entry.schema_name,
            table_name=entry.table_name,
            column_name=entry.column_name,
            field_name=log_entry.field_name,
            old_value=json.dumps(current_value),
            new_value=log_entry.old_value,
            changed_by_user_id=current_user.user_id,
        )
    )

    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.entry_field_reverted", resource_type="data_dict_entry",
        resource_id=entry_id,
        resource_name=f"{entry.schema_name}.{entry.table_name}.{entry.column_name or '(table)'}",
        extra={"field": log_entry.field_name, "log_id": log_id},
    )
    await db.commit()
    await db.refresh(entry)
    logger.info(
        "data_dict.reverted",
        org_id=current_user.org_id,
        entry_id=entry_id,
        log_id=log_id,
        field=log_entry.field_name,
    )
    return _serialize_entry(entry)


# ---------------------------------------------------------------------------
# Exclusion endpoints
# ---------------------------------------------------------------------------


@router.get("/data-dictionary/exclusions")
async def list_exclusions(
    warehouse_connection_id: int,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return all schema/table exclusions for a warehouse."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryExclusion  # noqa: PLC0415

    result = await db.execute(
        select(DataDictionaryExclusion).where(
            DataDictionaryExclusion.org_id == current_user.org_id,
            DataDictionaryExclusion.warehouse_connection_id == warehouse_connection_id,
        )
    )
    return [_serialize_exclusion(r) for r in result.scalars().all()]


@router.post("/data-dictionary/exclusions", status_code=201)
async def add_exclusion(
    data: ExclusionCreate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Exclude a schema or table from the data dictionary tree.

    Idempotent — if the exclusion already exists the existing row is returned.
    Pass table_name=null to exclude the whole schema.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryExclusion  # noqa: PLC0415

    # Check for existing exclusion first
    existing = await db.execute(
        select(DataDictionaryExclusion).where(
            DataDictionaryExclusion.org_id == current_user.org_id,
            DataDictionaryExclusion.warehouse_connection_id == data.warehouse_connection_id,
            DataDictionaryExclusion.schema_name == data.schema_name,
            DataDictionaryExclusion.table_name == data.table_name,
        )
    )
    exc_row = existing.scalar_one_or_none()
    if exc_row is not None:
        return _serialize_exclusion(exc_row)

    new_exc = DataDictionaryExclusion(
        org_id=current_user.org_id,
        warehouse_connection_id=data.warehouse_connection_id,
        schema_name=data.schema_name,
        table_name=data.table_name,
    )
    db.add(new_exc)
    from app.services.audit import audit_action  # noqa: PLC0415
    target = f"{data.schema_name}.{data.table_name}" if data.table_name else data.schema_name
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.exclusion_added", resource_type="data_dict_exclusion",
        resource_name=target,
        extra={"schema": data.schema_name, "table": data.table_name},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # Race condition — another request inserted first; just return the existing row
        result2 = await db.execute(
            select(DataDictionaryExclusion).where(
                DataDictionaryExclusion.org_id == current_user.org_id,
                DataDictionaryExclusion.warehouse_connection_id == data.warehouse_connection_id,
                DataDictionaryExclusion.schema_name == data.schema_name,
                DataDictionaryExclusion.table_name == data.table_name,
            )
        )
        new_exc = result2.scalar_one()
    else:
        await db.refresh(new_exc)
    return _serialize_exclusion(new_exc)


@router.delete("/data-dictionary/exclusions/{exclusion_id}", status_code=204)
async def remove_exclusion(
    exclusion_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Remove a schema or table exclusion so it reappears in the data dictionary tree."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.data_dict import DataDictionaryExclusion  # noqa: PLC0415

    result = await db.execute(
        select(DataDictionaryExclusion).where(
            DataDictionaryExclusion.id == exclusion_id,
            DataDictionaryExclusion.org_id == current_user.org_id,
        )
    )
    exc_row = result.scalar_one_or_none()
    if exc_row is None:
        raise HTTPException(status_code=404, detail="Exclusion not found")

    from app.services.audit import audit_action  # noqa: PLC0415
    excl_name = f"{exc_row.schema_name}.{exc_row.table_name}" if exc_row.table_name else exc_row.schema_name
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="data_dict.exclusion_removed", resource_type="data_dict_exclusion",
        resource_id=exclusion_id, resource_name=excl_name,
    )
    await db.delete(exc_row)
    await db.commit()
