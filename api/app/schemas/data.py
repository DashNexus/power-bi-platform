"""Schema for paginated mart data queries."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DataTableResponse(BaseModel):
    """Paginated result set from a marts table query.

    Attributes:
        columns: Column names in order.
        rows: Row data as lists of values matching the column order.
        total_rows: Total number of rows matching the query (excluding pagination).
        has_more: True if there are more pages beyond the current result set.
        table_name: The source marts table name.
    """

    columns: list[str]
    rows: list[list[Any]]
    total_rows: int
    has_more: bool
    table_name: str

    model_config = {"from_attributes": True}


class TableListResponse(BaseModel):
    """List of available marts tables with metadata.

    Attributes:
        tables: Table entries with name, description, row_count, and last_updated.
    """

    tables: list[dict[str, Any]]


class DataQueryRequest(BaseModel):
    """Request body for querying a marts table.

    Attributes:
        table_name: Name of the marts table to query.
        columns: Columns to select. Pass [] for all columns.
        filters: Column-value pairs for WHERE clauses.
        order_by: Column name to sort by. Prefix with '-' for descending.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip for pagination.
    """

    table_name: str
    columns: list[str] = []
    filters: dict[str, Any] = {}
    order_by: str | None = None
    limit: int = 100
    offset: int = 0
