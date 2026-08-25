"""Data pipeline connection management: CRUD, sharing, and run monitoring.

Mirrors the warehouse-connection model — many named connections per org, each
shareable with roles — but for pipeline orchestrators (Prefect, Azure Data
Factory, and planned integrations). Admins manage connections; any user a
connection is shared with can view it and its recent runs.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.data_pipeline import (
    DataPipelineConnection,
    DataPipelineConnectionPermission,
)
from app.services import nav_config
from app.services import pipeline_providers as providers
from app.services.permissions import get_user_role_ids, require_permission_or_admin
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()

# Admins, or a principal explicitly granted the key — see
# services/permissions.py::require_permission_or_admin.
_view_dep = require_permission_or_admin("pipelines.view", "pipelines.manage")
_manage_dep = require_permission_or_admin("pipelines.manage")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PipelineConnectionCreate(BaseModel):
    """Fields to create a data pipeline connection."""

    name: str
    provider: str
    config: dict[str, Any] = {}
    secret: str | None = None  # plaintext; encrypted before storage
    is_active: bool = True


class PipelineConnectionUpdate(BaseModel):
    """Fields that may be updated. secret=None leaves the stored secret unchanged."""

    name: str | None = None
    config: dict[str, Any] | None = None
    secret: str | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize(conn: DataPipelineConnection, *, include_config: bool = False) -> dict[str, Any]:
    """Serialize a connection to a safe response dict — never includes the secret."""
    out: dict[str, Any] = {
        "id": conn.id,
        "org_id": conn.org_id,
        "name": conn.name,
        "provider": conn.provider,
        "is_active": conn.is_active,
        "has_secret": bool(conn.secret_encrypted),
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
    }
    if include_config:
        out["config"] = conn.config or {}
    meta = providers.provider_meta(conn.provider)
    out["provider_label"] = meta.label if meta else conn.provider
    out["provider_implemented"] = meta.implemented if meta else False
    return out


async def _accessible_ids(current_user: CurrentUser, db: AsyncSession) -> set[int] | None:
    """Connection ids the user may access. None means all (admin/superadmin)."""
    if current_user.role in ("admin", "superadmin"):
        return None
    role_ids = await get_user_role_ids(db, current_user)
    conds: list[Any] = [DataPipelineConnectionPermission.user_id == current_user.user_id]
    if role_ids:
        conds.append(DataPipelineConnectionPermission.role_id.in_(role_ids))
    rows = await db.execute(
        select(DataPipelineConnectionPermission.pipeline_connection_id).where(
            DataPipelineConnectionPermission.org_id == current_user.org_id,
            or_(*conds),
        )
    )
    return {r[0] for r in rows.all()}


async def _get_conn(
    connection_id: int, current_user: CurrentUser, db: AsyncSession
) -> DataPipelineConnection:
    """Return the org-scoped connection or raise 404."""
    conn = (
        await db.execute(
            select(DataPipelineConnection).where(
                DataPipelineConnection.id == connection_id,
                DataPipelineConnection.org_id == current_user.org_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Pipeline connection not found")
    return conn


async def _require_view(
    connection_id: int, current_user: CurrentUser, db: AsyncSession
) -> DataPipelineConnection:
    """Return the connection if the user may view it (admin or shared), else 404."""
    conn = await _get_conn(connection_id, current_user, db)
    accessible = await _accessible_ids(current_user, db)
    if accessible is not None and connection_id not in accessible:
        raise HTTPException(status_code=404, detail="Pipeline connection not found")
    return conn


def _decrypt_secret(conn: DataPipelineConnection) -> str | None:
    from app.services.crypto import decrypt  # noqa: PLC0415

    if not conn.secret_encrypted:
        return None
    try:
        return decrypt(conn.secret_encrypted)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Provider catalog
# ---------------------------------------------------------------------------


@router.get("/data-pipelines/providers")
async def list_providers(
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return the catalog of pipeline providers (implemented and planned)."""
    return providers.list_provider_meta()


# ---------------------------------------------------------------------------
# User-facing (shared) access
# ---------------------------------------------------------------------------


@router.get("/data-pipelines")
async def list_pipelines(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return active pipeline connections the user may access (admins see all)."""
    result = await db.execute(
        select(DataPipelineConnection)
        .where(
            DataPipelineConnection.org_id == current_user.org_id,
            is_true(DataPipelineConnection.is_active),
        )
        .order_by(DataPipelineConnection.name)
    )
    conns = list(result.scalars().all())
    accessible = await _accessible_ids(current_user, db)
    if accessible is not None:
        conns = [c for c in conns if c.id in accessible]
    return [_serialize(c) for c in conns]


@router.get("/data-pipelines/{connection_id}")
async def get_pipeline(
    connection_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return one pipeline connection the user may view."""
    conn = await _require_view(connection_id, current_user, db)
    return _serialize(conn, include_config=True)


def _require_implemented_provider(conn: DataPipelineConnection) -> providers.PipelineProvider:
    """Return the provider for a connection, or raise 400/501 if unusable."""
    provider = providers.get_provider(conn.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{conn.provider}'")
    if not provider.meta.implemented:
        raise HTTPException(
            status_code=501,
            detail=f"The {provider.meta.label} integration is planned but not yet available.",
        )
    return provider


@router.get("/data-pipelines/{connection_id}/runs")
async def list_pipeline_runs(
    connection_id: int,
    limit: int = 50,
    days: int = 7,
    pipeline_name: str | None = None,
    cursor: str | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return a page of runs for a pipeline connection via its provider.

    Filter by time window (``days``) and ``pipeline_name``; paginate older runs
    with ``cursor`` (echo back the ``next_cursor`` from the previous response).
    """
    conn = await _require_view(connection_id, current_user, db)
    provider = _require_implemented_provider(conn)
    try:
        result = await provider.list_runs(
            conn.config or {},
            _decrypt_secret(conn),
            limit=limit,
            days=days,
            pipeline_name=pipeline_name,
            cursor=cursor,
        )
    except providers.PipelineNotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except providers.PipelineProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "provider": conn.provider,
        "runs": result.get("runs", []),
        "next_cursor": result.get("next_cursor"),
    }


@router.get("/data-pipelines/{connection_id}/pipelines")
async def list_pipeline_definitions(
    connection_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return the pipeline/flow definitions for a connection via its provider."""
    conn = await _require_view(connection_id, current_user, db)
    provider = _require_implemented_provider(conn)
    try:
        pipelines = await provider.list_pipelines(conn.config or {}, _decrypt_secret(conn))
    except providers.PipelineNotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except providers.PipelineProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"provider": conn.provider, "pipelines": pipelines}


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


@router.get("/admin/data-pipelines")
async def admin_list_pipelines(
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return all pipeline connections for the org (admin)."""
    result = await db.execute(
        select(DataPipelineConnection)
        .where(DataPipelineConnection.org_id == current_user.org_id)
        .order_by(DataPipelineConnection.name)
    )
    return [_serialize(c, include_config=True) for c in result.scalars().all()]


@router.post("/admin/data-pipelines", status_code=201)
async def create_pipeline(
    data: PipelineConnectionCreate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Create a pipeline connection."""
    from app.services.crypto import encrypt  # noqa: PLC0415

    if not providers.is_valid_provider(data.provider):
        raise HTTPException(status_code=400, detail=f"Unknown provider '{data.provider}'")

    conn = DataPipelineConnection(
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
    logger.info("data_pipeline.created", org_id=current_user.org_id, connection_id=conn.id,
                provider=conn.provider)
    return _serialize(conn, include_config=True)


@router.put("/admin/data-pipelines/{connection_id}")
async def update_pipeline(
    connection_id: int,
    data: PipelineConnectionUpdate,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update a pipeline connection. Omit secret to keep the stored one."""
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
    logger.info("data_pipeline.updated", org_id=current_user.org_id, connection_id=conn.id)
    return _serialize(conn, include_config=True)


@router.delete("/admin/data-pipelines/{connection_id}", status_code=204)
async def delete_pipeline(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> None:
    """Delete a pipeline connection."""
    conn = await _get_conn(connection_id, current_user, db)
    pruned = await nav_config.prune_nav_links(
        db, current_user.org_id, nav_config.resource_hrefs("data_pipeline", connection_id)
    )
    await db.delete(conn)
    await db.commit()
    logger.info(
        "data_pipeline.deleted",
        org_id=current_user.org_id,
        connection_id=connection_id,
        nav_links_pruned=len(pruned),
    )


@router.post("/admin/data-pipelines/{connection_id}/test")
async def test_pipeline(
    connection_id: int,
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Test connectivity for a pipeline connection."""
    conn = await _get_conn(connection_id, current_user, db)
    provider = providers.get_provider(conn.provider)
    if provider is None:
        return {"ok": False, "error": f"Unknown provider '{conn.provider}'"}
    result = await provider.test_connection(conn.config or {}, _decrypt_secret(conn))
    logger.info("data_pipeline.test", org_id=current_user.org_id, connection_id=connection_id,
                ok=result.get("ok"))
    return result


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------


@router.get("/admin/data-pipelines/{connection_id}/permissions")
async def get_pipeline_permissions(
    connection_id: int,
    current_user: CurrentUser = Depends(_view_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, list[int]]:
    """Return the role ids granted access to a pipeline connection."""
    await _get_conn(connection_id, current_user, db)
    grants = await db.execute(
        select(DataPipelineConnectionPermission.role_id).where(
            DataPipelineConnectionPermission.org_id == current_user.org_id,
            DataPipelineConnectionPermission.pipeline_connection_id == connection_id,
        )
    )
    return {"role_ids": [r[0] for r in grants.all() if r[0] is not None]}


@router.put("/admin/data-pipelines/{connection_id}/permissions")
async def set_pipeline_permissions(
    connection_id: int,
    data: dict[str, list[int]],
    current_user: CurrentUser = Depends(_manage_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, str | int]:
    """Replace the roles that can access a pipeline connection."""
    await _get_conn(connection_id, current_user, db)
    await db.execute(
        delete(DataPipelineConnectionPermission).where(
            DataPipelineConnectionPermission.org_id == current_user.org_id,
            DataPipelineConnectionPermission.pipeline_connection_id == connection_id,
        )
    )
    role_ids: list[int] = data.get("role_ids", [])
    for rid in role_ids:
        db.add(
            DataPipelineConnectionPermission(
                org_id=current_user.org_id,
                pipeline_connection_id=connection_id,
                role_id=rid,
            )
        )
    await db.commit()
    logger.info("data_pipeline.permissions.updated", org_id=current_user.org_id,
                connection_id=connection_id, grants=len(role_ids))
    return {"message": f"Permissions updated ({len(role_ids)} grants)"}
