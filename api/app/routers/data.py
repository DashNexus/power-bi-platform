"""Paginated queries against marts schema and table listing."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db, get_warehouse_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.audit import AuditLog
from app.schemas.data import DataTableResponse, TableListResponse
from app.services import data_query
from app.sql_compat import dialect_name, schema_freshness_sql

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/tables", response_model=TableListResponse)
async def list_marts_tables(
    _current_user: CurrentUser = Depends(get_current_user),
    wh: AsyncSession = Depends(get_warehouse_db),
) -> TableListResponse:
    """Return all available marts tables with metadata.

    Returns:
        List of marts tables with name, description, row_count, and last_updated.
    """
    return TableListResponse(tables=await data_query.list_marts_tables(wh))


@router.get("/freshness")
async def get_data_freshness(
    wh: AsyncSession = Depends(get_warehouse_db),
) -> dict[str, Any]:
    """Return the approximate last-updated timestamp for the marts schema.

    Reads whichever statistics the warehouse engine exposes (see
    `sql_compat.schema_freshness_sql`). Returns null when none are available yet
    — a fresh database has no statistics, which is not an error.
    """
    try:
        result = await wh.execute(text(schema_freshness_sql(dialect_name(wh))))
        row = result.fetchone()
        last_updated = row[0] if row and row[0] else None
        return {"last_updated": last_updated.isoformat() if last_updated else None}
    except Exception:
        return {"last_updated": None}


@router.get("/tables/{table}", response_model=DataTableResponse)
async def query_table(
    table: str,
    page: int = 1,
    page_size: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
    wh: AsyncSession = Depends(get_warehouse_db),
    db: AsyncSession = Depends(get_app_db),
) -> DataTableResponse:
    """Paginated query against a marts table.

    Args:
        table: Table name (must be in marts schema).
        page: 1-indexed page number.
        page_size: Number of rows per page (max 1000).
        current_user: Authenticated user — used for org scoping and audit.
        wh: Warehouse read-only database session.
        db: App database session for writing the audit record.

    Returns:
        Paginated table data with columns, rows, and total count.

    Raises:
        HTTPException: With status 404 if the table is not in the marts schema.
    """
    page_size = min(page_size, 1000)
    try:
        result = await data_query.query_table(wh, table, page, page_size)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit = AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        action="data.query",
        resource_type="mart_table",
        resource_name=table,
    )
    db.add(audit)
    await db.commit()

    return DataTableResponse(**result)
