"""Warehouse connection management: CRUD, connectivity testing, and schema introspection."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser
from app.services import nav_config
from app.services.permissions import require_permission_or_admin
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()

# Admins, or a principal explicitly granted the key — see
# services/permissions.py::require_permission_or_admin.
_view_dep = require_permission_or_admin("warehouses.view", "warehouses.manage")
_manage_dep = require_permission_or_admin("warehouses.manage")


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class WarehouseConnectionCreate(BaseModel):
    """Fields required to create a new warehouse connection."""

    name: str
    db_type: str
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None  # plaintext; encrypted before storage
    schemas: list[str] = []
    extra_config: dict[str, Any] = {}
    is_default: bool = False
    is_active: bool = True


class WarehouseConnectionUpdate(BaseModel):
    """Fields that may be updated on an existing connection."""

    name: str | None = None
    db_type: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None  # plaintext; encrypted before storage; None = no change
    schemas: list[str] | None = None
    extra_config: dict[str, Any] | None = None
    is_default: bool | None = None
    is_active: bool | None = None


def _serialize_conn(conn: Any) -> dict[str, Any]:
    """Serialize a WarehouseConnection ORM row to a safe response dict.

    The encrypted password is never included in API responses.
    """
    return {
        "id": conn.id,
        "org_id": conn.org_id,
        "name": conn.name,
        "db_type": conn.db_type,
        "host": conn.host,
        "port": conn.port,
        "database_name": conn.database_name,
        "username": conn.username,
        "schemas": conn.schemas,
        "extra_config": conn.extra_config,
        "is_default": conn.is_default,
        "is_active": conn.is_active,
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }


def _decrypt_conn_for_test(conn: Any) -> dict[str, Any]:
    """Build the dict expected by warehouse_inspector with the password decrypted."""
    from app.services.crypto import decrypt  # noqa: PLC0415

    password = ""
    if conn.password_encrypted:
        try:
            password = decrypt(conn.password_encrypted)
        except Exception:
            password = ""

    return {
        "db_type": conn.db_type,
        "host": conn.host,
        "port": conn.port,
        "database_name": conn.database_name,
        "username": conn.username,
        "password": password,
        "schemas": conn.schemas or [],
        "extra_config": conn.extra_config or {},
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/warehouses")
async def list_warehouses(
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return all warehouse connections for the current organisation."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection)
        .where(WarehouseConnection.org_id == current_user.org_id)
        .order_by(WarehouseConnection.name)
    )
    rows = result.scalars().all()
    return [_serialize_conn(r) for r in rows]


@router.post("/warehouses", status_code=201)
async def create_warehouse(
    data: WarehouseConnectionCreate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create a new warehouse connection for the current organisation."""
    from sqlalchemy import update  # noqa: PLC0415

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415
    from app.services.crypto import encrypt  # noqa: PLC0415

    password_encrypted: str | None = None
    if data.password:
        password_encrypted = encrypt(data.password)

    conn = WarehouseConnection(
        org_id=current_user.org_id,
        name=data.name,
        db_type=data.db_type,
        host=data.host,
        port=data.port,
        database_name=data.database_name,
        username=data.username,
        password_encrypted=password_encrypted,
        schemas=data.schemas,
        extra_config=data.extra_config,
        is_default=data.is_default,
        is_active=data.is_active,
    )

    # If this connection is being set as default, unset all others first.
    if data.is_default:
        await db.execute(
            update(WarehouseConnection)
            .where(
                WarehouseConnection.org_id == current_user.org_id,
                is_true(WarehouseConnection.is_default),
            )
            .values(is_default=False)
        )

    db.add(conn)
    await db.commit()
    await db.refresh(conn)

    logger.info(
        "warehouse.created",
        org_id=current_user.org_id,
        connection_id=conn.id,
        name=conn.name,
    )
    return _serialize_conn(conn)


@router.put("/warehouses/{connection_id}")
async def update_warehouse(
    connection_id: int,
    data: WarehouseConnectionUpdate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update an existing warehouse connection."""
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy import update as sa_update

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415
    from app.services.crypto import encrypt  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    if data.name is not None:
        conn.name = data.name
    if data.db_type is not None:
        conn.db_type = data.db_type
    if data.host is not None:
        conn.host = data.host
    if data.port is not None:
        conn.port = data.port
    if data.database_name is not None:
        conn.database_name = data.database_name
    if data.username is not None:
        conn.username = data.username
    if data.password is not None:
        conn.password_encrypted = encrypt(data.password)
    if data.schemas is not None:
        conn.schemas = data.schemas
    if data.extra_config is not None:
        conn.extra_config = data.extra_config
    if data.is_active is not None:
        conn.is_active = data.is_active

    # If marking as default, unset all other defaults first.
    if data.is_default is True:
        await db.execute(
            sa_update(WarehouseConnection)
            .where(
                WarehouseConnection.org_id == current_user.org_id,
                WarehouseConnection.id != connection_id,
                is_true(WarehouseConnection.is_default),
            )
            .values(is_default=False)
        )
        conn.is_default = True
    elif data.is_default is False:
        conn.is_default = False

    await db.commit()
    await db.refresh(conn)

    logger.info(
        "warehouse.updated",
        org_id=current_user.org_id,
        connection_id=conn.id,
    )
    return _serialize_conn(conn)


@router.delete("/warehouses/{connection_id}", status_code=204)
async def delete_warehouse(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Delete a warehouse connection."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    # A nav link to this connection's data dictionary would 404 once it is gone.
    # No ledger ctx: warehouse connections are not ledger-tracked, so there is no
    # delete to revert the pruned link alongside.
    pruned = await nav_config.prune_nav_links(
        db,
        current_user.org_id,
        nav_config.resource_hrefs("warehouse_connection", connection_id),
    )

    await db.delete(conn)
    await db.commit()

    logger.info(
        "warehouse.deleted",
        org_id=current_user.org_id,
        connection_id=connection_id,
        nav_links_pruned=len(pruned),
    )


@router.post("/warehouses/{connection_id}/test")
async def test_warehouse_connection(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Test connectivity for an existing warehouse connection.

    Attempts a live connection (SELECT 1) and counts accessible tables in
    the configured schemas. Returns ok=True on success.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415
    from app.services.warehouse_inspector import test_connection  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    conn_dict = _decrypt_conn_for_test(conn)
    test_result = await test_connection(conn_dict)

    logger.info(
        "warehouse.test",
        org_id=current_user.org_id,
        connection_id=connection_id,
        ok=test_result.get("ok"),
    )
    return test_result


@router.post("/warehouses/{connection_id}/set-default")
async def set_default_warehouse(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Mark a warehouse connection as the default for the organisation.

    Unsets the is_default flag on all other connections in the same org.
    """
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy import update as sa_update

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    # Unset existing defaults
    await db.execute(
        sa_update(WarehouseConnection)
        .where(
            WarehouseConnection.org_id == current_user.org_id,
            is_true(WarehouseConnection.is_default),
        )
        .values(is_default=False)
    )

    conn.is_default = True
    await db.commit()
    await db.refresh(conn)

    logger.info(
        "warehouse.set_default",
        org_id=current_user.org_id,
        connection_id=connection_id,
    )
    return _serialize_conn(conn)


@router.get("/admin/warehouses/{connection_id}/permissions")
async def get_warehouse_permissions(
    connection_id: int,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, list[int]]:
    """Return the role ids granted access to a warehouse connection."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.warehouse import (  # noqa: PLC0415
        WarehouseConnection,
        WarehouseConnectionPermission,
    )

    exists = await db.execute(
        select(WarehouseConnection.id).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    grants = await db.execute(
        select(WarehouseConnectionPermission.role_id).where(
            WarehouseConnectionPermission.org_id == current_user.org_id,
            WarehouseConnectionPermission.warehouse_connection_id == connection_id,
        )
    )
    return {"role_ids": [r[0] for r in grants.all() if r[0] is not None]}


@router.put("/admin/warehouses/{connection_id}/permissions")
async def set_warehouse_permissions(
    connection_id: int,
    data: dict[str, list[int]],
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str | int]:
    """Replace the roles that can access (query) a warehouse connection.

    Warehouse access is separate from data dictionary access. Pass an empty list
    to remove all grants (admins retain access).
    """
    from sqlalchemy import delete, select  # noqa: PLC0415

    from app.models.warehouse import (  # noqa: PLC0415
        WarehouseConnection,
        WarehouseConnectionPermission,
    )

    exists = await db.execute(
        select(WarehouseConnection.id).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    if exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    await db.execute(
        delete(WarehouseConnectionPermission).where(
            WarehouseConnectionPermission.org_id == current_user.org_id,
            WarehouseConnectionPermission.warehouse_connection_id == connection_id,
        )
    )
    role_ids: list[int] = data.get("role_ids", [])
    for rid in role_ids:
        db.add(
            WarehouseConnectionPermission(
                org_id=current_user.org_id,
                warehouse_connection_id=connection_id,
                role_id=rid,
            )
        )
    await db.commit()
    logger.info(
        "warehouse.permissions.updated",
        org_id=current_user.org_id, connection_id=connection_id, grants=len(role_ids),
    )
    return {"message": f"Permissions updated ({len(role_ids)} grants)"}


@router.get("/warehouses/{connection_id}/schemas")
async def get_warehouse_schemas(
    connection_id: int,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Introspect and return the schema/table/column structure of the warehouse.

    Connects live to the warehouse and returns all tables and columns within
    the configured schemas. This may take several seconds for large warehouses.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.warehouse import WarehouseConnection  # noqa: PLC0415
    from app.services.warehouse_inspector import introspect_schemas  # noqa: PLC0415

    result = await db.execute(
        select(WarehouseConnection).where(
            WarehouseConnection.id == connection_id,
            WarehouseConnection.org_id == current_user.org_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Warehouse connection not found")

    conn_dict = _decrypt_conn_for_test(conn)

    try:
        schemas = await introspect_schemas(conn_dict)
    except Exception as exc:
        logger.warning(
            "warehouse.introspect_failed",
            org_id=current_user.org_id,
            connection_id=connection_id,
            error=str(exc),
        )
        raise HTTPException(
            status_code=502, detail=f"Failed to introspect warehouse schemas: {exc}"
        ) from exc

    return schemas
