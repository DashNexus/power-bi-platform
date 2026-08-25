"""BI (embed) connection management: CRUD and connectivity testing.

Admin-only, modeled on the warehouse-connection routes. Supports many named
Power BI / Tableau connections plus single-instance public surfaces (Tableau
Public, Looker Studio). Secrets are Fernet-encrypted and never returned.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.bi_connection import BiConnection
from app.services import bi_providers as providers
from app.services.permissions import require_permission_or_admin

logger = structlog.get_logger(__name__)

router = APIRouter()

# Admins, or a principal explicitly granted the key — see
# services/permissions.py::require_permission_or_admin.
_view_dep = require_permission_or_admin("bi_connections.view", "bi_connections.manage")
_manage_dep = require_permission_or_admin("bi_connections.manage")


class BiConnectionCreate(BaseModel):
    """Fields to create a BI connection."""

    name: str
    provider: str
    config: dict[str, Any] = {}
    secret: str | None = None  # plaintext; encrypted before storage
    is_active: bool = True


class BiConnectionUpdate(BaseModel):
    """Fields that may be updated. secret=None leaves the stored secret unchanged."""

    name: str | None = None
    config: dict[str, Any] | None = None
    secret: str | None = None
    is_active: bool | None = None


def _serialize(conn: BiConnection, *, include_config: bool = False) -> dict[str, Any]:
    """Serialize a connection to a safe response dict — never includes the secret."""
    meta = providers.provider_meta(conn.provider)
    out: dict[str, Any] = {
        "id": conn.id,
        "org_id": conn.org_id,
        "name": conn.name,
        "provider": conn.provider,
        "provider_label": meta.label if meta else conn.provider,
        "provider_implemented": meta.implemented if meta else False,
        "requires_auth": meta.requires_auth if meta else True,
        "singleton": meta.singleton if meta else False,
        "is_active": conn.is_active,
        "has_secret": bool(conn.secret_encrypted),
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }
    if include_config:
        out["config"] = conn.config or {}
    return out


async def _get_conn(
    connection_id: int, current_user: CurrentUser, db: AsyncSession
) -> BiConnection:
    """Return the org-scoped connection or raise 404."""
    conn = (
        await db.execute(
            select(BiConnection).where(
                BiConnection.id == connection_id,
                BiConnection.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="BI connection not found")
    return conn


def _decrypt_secret(conn: BiConnection) -> str | None:
    from app.services.crypto import decrypt  # noqa: PLC0415

    if not conn.secret_encrypted:
        return None
    try:
        return decrypt(conn.secret_encrypted)
    except Exception:
        return None


@router.get("/bi-connections/providers")
async def list_providers(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return the catalog of BI providers (implemented, public, and planned)."""
    return providers.list_provider_meta()


@router.get("/bi-connections")
async def list_bi_connections(
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return all BI connections for the org."""
    result = await db.execute(
        select(BiConnection)
        .where(BiConnection.org_id == current_user.org_id)
        .order_by(BiConnection.name)
    )
    return [_serialize(c, include_config=True) for c in result.scalars().all()]


@router.post("/bi-connections", status_code=201)
async def create_bi_connection(
    data: BiConnectionCreate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create a BI connection. Public providers are limited to one per org."""
    from app.services.crypto import encrypt  # noqa: PLC0415

    meta = providers.provider_meta(data.provider)
    if meta is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{data.provider}'")

    if meta.singleton:
        existing = (
            await db.execute(
                select(BiConnection.id).where(
                    BiConnection.org_id == current_user.org_id,
                    BiConnection.provider == data.provider,
                )
            )
        ).first()
        if existing is not None:
            raise HTTPException(
                status_code=400,
                detail=f"Only one {meta.label} connection is allowed.",
            )

    conn = BiConnection(
        org_id=current_user.org_id,
        name=data.name,
        provider=data.provider,
        config=data.config,
        secret_encrypted=encrypt(data.secret) if data.secret else None,
        is_active=data.is_active,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    logger.info("bi_connection.created", org_id=current_user.org_id, connection_id=conn.id,
                provider=conn.provider)
    return _serialize(conn, include_config=True)


@router.put("/bi-connections/{connection_id}")
async def update_bi_connection(
    connection_id: int,
    data: BiConnectionUpdate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update a BI connection. Omit secret to keep the stored one."""
    from app.services.crypto import encrypt  # noqa: PLC0415

    conn = await _get_conn(connection_id, current_user, db)
    if data.name is not None:
        conn.name = data.name
    if data.config is not None:
        conn.config = data.config
    if data.secret is not None:
        conn.secret_encrypted = encrypt(data.secret) if data.secret else None
    if data.is_active is not None:
        conn.is_active = data.is_active
    await db.commit()
    await db.refresh(conn)
    logger.info("bi_connection.updated", org_id=current_user.org_id, connection_id=conn.id)
    return _serialize(conn, include_config=True)


@router.delete("/bi-connections/{connection_id}", status_code=204)
async def delete_bi_connection(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Delete a BI connection."""
    conn = await _get_conn(connection_id, current_user, db)
    await db.delete(conn)
    await db.commit()
    logger.info("bi_connection.deleted", org_id=current_user.org_id, connection_id=connection_id)


@router.post("/bi-connections/{connection_id}/test")
async def test_bi_connection(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Test connectivity for a BI connection."""
    conn = await _get_conn(connection_id, current_user, db)
    provider = providers.get_provider(conn.provider)
    if provider is None:
        return {"ok": False, "error": f"Unknown provider '{conn.provider}'"}
    result = await provider.test_connection(conn.config or {}, _decrypt_secret(conn))
    logger.info("bi_connection.test", org_id=current_user.org_id, connection_id=connection_id,
                ok=result.get("ok"))
    return result
