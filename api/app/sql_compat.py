"""Dialect differences between PostgreSQL and Azure SQL, in one place.

This build runs on either, and the ORM covers almost all of it. What the ORM
does not cover is the handful of places that issue raw SQL against the
warehouse: row limiting, and the "when was this schema last written to" probe.
Both differ enough between the two engines that a single string cannot serve.

Anything added here should be a *syntax* difference. A behavioural difference
belongs in the caller, where it can be named.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, false, true
from sqlalchemy.ext.asyncio import AsyncSession

#: Dialect names SQLAlchemy reports for Azure SQL / SQL Server.
MSSQL = "mssql"


def is_true(column: ColumnElement[bool]) -> ColumnElement[bool]:
    """Return a portable "this boolean column is true" predicate.

    Use this instead of ``column.is_(True)``. SQLAlchemy renders that as
    ``col IS 1`` on SQL Server, and T-SQL's ``IS`` only accepts NULL — so the
    statement fails to parse with "Incorrect syntax near '1'". Comparing against
    ``true()`` renders ``col = 1`` there and ``col = true`` on PostgreSQL.

    ``is_(None)`` is unaffected and stays as it is: ``IS NULL`` is valid in both.
    """
    return column == true()


def is_false(column: ColumnElement[bool]) -> ColumnElement[bool]:
    """Return a portable "this boolean column is false" predicate.

    See `is_true` for why ``column.is_(False)`` cannot be used.
    """
    return column == false()


def dialect_name(session: AsyncSession) -> str:
    """Return the SQLAlchemy dialect name a session is bound to."""
    return session.get_bind().dialect.name


def paginate_clause(dialect: str) -> str:
    """Return the trailing clause that pages a result set.

    Binds ``:page_size`` and ``:offset``. Both forms require an ORDER BY —
    SQL Server rejects OFFSET without one, and PostgreSQL would otherwise return
    rows in an unspecified order, which makes page 2 unrelated to page 1.
    """
    if dialect == MSSQL:
        return "OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY"
    return "LIMIT :page_size OFFSET :offset"


def row_limit_clause(dialect: str, limit: int) -> tuple[str, str]:
    """Return ``(prefix, suffix)`` fragments that cap a SELECT at ``limit`` rows.

    SQL Server puts the cap before the projection (``SELECT TOP (n) ...``) and
    PostgreSQL after the table (``... LIMIT n``), so a caller has to be handed
    both halves rather than one clause.

    ``limit`` is interpolated, so callers must pass an int they produced — never
    a request value that reached them as a string.
    """
    if dialect == MSSQL:
        return f"TOP ({int(limit)}) ", ""
    return "", f" LIMIT {int(limit)}"


def schema_freshness_sql(dialect: str) -> str:
    """Return SQL yielding one ``last_updated`` column for the marts schema.

    Neither engine records "when did this schema last change" directly, so both
    read the closest thing their statistics expose. The answer is approximate on
    purpose — it drives a "data as of ..." label, not a correctness decision.
    """
    if dialect == MSSQL:
        # Azure SQL keeps per-index statistics update times; the newest across
        # the schema's indexes is the best available proxy.
        return """
            SELECT MAX(STATS_DATE(i.object_id, i.index_id)) AS last_updated
            FROM sys.indexes i
            JOIN sys.tables t ON t.object_id = i.object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = 'marts' AND i.index_id > 0
        """
    return """
        SELECT GREATEST(
            MAX(last_autoanalyze),
            MAX(last_autovacuum),
            MAX(last_analyze),
            MAX(last_vacuum)
        ) AS last_updated
        FROM pg_stat_user_tables
        WHERE schemaname = 'marts'
    """
