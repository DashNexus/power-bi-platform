"""Warehouse data query service for paginated mart table access.

All queries use the read-only warehouse login via warehouse_engine so the marts
schema is the only accessible schema. Validation against information_schema
prevents table namespacing escapes.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.sql_compat import dialect_name, paginate_clause

logger = structlog.get_logger(__name__)


async def list_marts_tables(wh: AsyncSession) -> list[dict]:
    """Return all marts schema tables visible to the warehouse_reader role.

    Queries information_schema.tables scoped to the marts schema.

    Args:
        wh: Async session bound to the warehouse database.

    Returns:
        List of dicts with 'table_name' and 'table_type' keys.
    """
    result = await wh.execute(
        text(
            "SELECT table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema = 'marts'"
        )
    )
    rows = result.fetchall()
    return [{"table_name": row[0], "table_type": row[1]} for row in rows]


async def query_table(
    wh: AsyncSession,
    table: str,
    page: int,
    page_size: int,
    filters: dict[str, Any] | None = None,
    org_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    """Query a marts table with pagination, filtering, and validation.

    Validates the table exists in the marts schema via information_schema
    before issuing the SELECT. Row-level security is applied via org_id
    where the table supports it.

    Args:
        wh: Async session bound to the warehouse database.
        table: Qualified table name (must be in marts schema).
        page: 1-indexed page number.
        page_size: Number of rows per page (max 10,000).
        filters: Optional dict of column-name to value filters.
        org_id: Organisation ID for row-level filtering.
        user_id: User ID for audit logging.

    Returns:
        Dict with 'data', 'total', 'page', and 'page_size' keys.

    Raises:
        ValueError: If the table is not found in the marts schema.
    """
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be positive integers")
    if page_size > 10000:
        raise ValueError("page_size cannot exceed 10,000")

    # Validate the table exists in marts schema.
    schema_check = await wh.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'marts' AND table_name = :tbl"
        ),
        {"tbl": table},
    )
    count = schema_check.scalar_one()
    if count == 0:
        raise ValueError(f"Table '{table}' not found in marts schema")

    # Build the base SELECT.
    base_where = "WHERE 1=1"
    params: dict[str, Any] = {"tbl": table, "page_size": page_size, "offset": (page - 1) * page_size}

    if org_id is not None:
        base_where += " AND org_id = :org_id"
        params["org_id"] = org_id

    if filters:
        for col, val in filters.items():
            base_where += f" AND {col} = :_{col}"
            params[f"_{col}"] = val

    count_sql = text(f"SELECT COUNT(*) FROM marts.{table} {base_where}")
    total = (await wh.execute(count_sql, params)).scalar_one()

    # ORDER BY is required, not cosmetic: SQL Server rejects OFFSET without one,
    # and PostgreSQL would otherwise leave page 2 unrelated to page 1.
    data_sql = text(
        f"SELECT * FROM marts.{table} {base_where} "
        f"ORDER BY 1 {paginate_clause(dialect_name(wh))}"
    )
    result = await wh.execute(data_sql, params)
    columns = result.keys()
    rows = [dict(zip(columns, row)) for row in result.fetchall()]

    await _log_access(wh, table, user_id, org_id)

    return {"data": rows, "total": total, "page": page, "page_size": page_size}


async def _log_access(
    wh: AsyncSession,
    table: str,
    user_id: int | None = None,
    org_id: int | None = None,
) -> None:
    """Log a warehouse data access event for audit purposes.

    Args:
        wh: Async session bound to the warehouse database.
        table: Table that was accessed.
        user_id: User who accessed the data.
        org_id: Organisation scope of the access.
    """
    logger.info(
        "warehouse.query",
        table=table,
        user_id=user_id,
        org_id=org_id,
    )
