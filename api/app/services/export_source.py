"""Resolve a report's data source and run its query read-only.

A report reads either the operations database (the one this application runs
on) or a named warehouse connection. Both paths converge on the same guarantee:
the statement is validated as read-only, and it executes inside a transaction
that is always rolled back — so a write that somehow survived the parser still
leaves nothing behind.

Layered, weakest first:

1. ``sql_guard`` refuses anything that is not a single read-only SELECT.
2. On PostgreSQL the transaction is additionally ``SET TRANSACTION READ ONLY``,
   so the *server* rejects writes rather than us predicting them. SQL Server has
   no equivalent.
3. The transaction is always rolled back, on every engine.
4. The connection should use a login with SELECT rights only.

Only 4 is airtight, and it is the one this module cannot apply — a database that
refuses the write beats any amount of parsing. Note also that 3 does not cover
everything: sequence advances are non-transactional on both engines, which is
why ``sql_guard`` blocks them at step 1 rather than trusting the rollback.
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models.warehouse import WarehouseConnection
from app.services import crypto
from app.services.sql_guard import ReadOnlySqlError, assert_read_only

logger = structlog.get_logger(__name__)

SOURCE_OPERATIONS = "operations"
SOURCE_WAREHOUSE = "warehouse"
VALID_SOURCE_KINDS = frozenset({SOURCE_OPERATIONS, SOURCE_WAREHOUSE})

# A report is delivered as a file, so the cap is about what the API can hold in
# memory while serialising, not about what a screen can show. Both this and the
# timeouts are settings because the right ceiling depends on the warehouse.
MAX_REPORT_ROWS = settings.export_max_rows

# Operations-database tables a report may never read. Everything here stores a
# credential or a second factor: encrypted secrets are still worth stealing
# offline, and password hashes are worth cracking. Reports against the
# operations database are admin-only to begin with, but an admin having a
# reason to read a row is different from being handed every hash in one CSV.
_OPERATIONS_DENYLIST = frozenset(
    {
        "users",
        "auth_provider_configs",
        "warehouse_connections",
        "bi_connections",
        "data_pipeline_connections",
        "password_reset_tokens",
        "refresh_tokens",
        "api_keys",
    }
)


class ExportSourceError(RuntimeError):
    """Raised when a report source cannot be resolved or queried."""


def denied_operations_tables(sql: str) -> list[str]:
    """Return denylisted table names the statement mentions.

    Matched against whole words in the comment- and string-stripped SQL, so a
    column called ``users_created`` does not trip it while ``dbo.users`` does.

    The ``keep_identifiers`` argument to strip_noise is load-bearing here. The
    keyword guard blanks ``[users]`` so a column named ``[delete]`` cannot trip
    it, and that same blanking would let ``SELECT * FROM [dbo].[users]`` walk
    straight past this check — which is exactly the form SQL Server Management
    Studio generates.
    """
    from app.services.sql_guard import strip_noise  # noqa: PLC0415

    cleaned = strip_noise(sql, keep_identifiers=True).lower()
    words = set(re.findall(r"[a-z_][a-z0-9_]*", cleaned))
    return sorted(words & _OPERATIONS_DENYLIST)


# Driver spellings of "the server gave up". No shared exception type covers
# pyodbc, psycopg2 and the rest, so the message is what there is to match on.
_TIMEOUT_MARKERS = (
    "timeout expired",
    "query timeout",
    "statement timeout",
    "canceling statement due to statement timeout",
    "max_execution_time",
    "execution time exceeded",
    "hyt00",
    "hyt01",
)


def _looks_like_timeout(message: str) -> bool:
    """Return True if a driver error message reads as a server-side timeout."""
    lowered = message.lower()
    return any(marker in lowered for marker in _TIMEOUT_MARKERS)


# SQLAlchemy appends a documentation link to every DBAPI error and echoes the
# statement back. Neither helps someone reading "what is wrong with my query",
# and the link is why a naive "does the message contain ://" check redacted
# every error it saw.
_SQLALCHEMY_NOISE = re.compile(
    r"\s*\(Background on this error at: https?://\S+\)|\s*\[SQL: .*|\s*\[parameters: .*",
    re.DOTALL,
)


# pyodbc stringifies as
#   (pyodbc.ProgrammingError) ('42S22', "[42S22] [Microsoft][ODBC Driver 18 for
#   SQL Server][SQL Server]Invalid column name 'nope'. (207) (SQLExecDirectW)")
# Only the middle clause tells the author anything. These strip the wrapper from
# the outside in; anything they do not match is left alone, so an unfamiliar
# driver still reports in full.
_DRIVER_WRAPPERS = (
    re.compile(r"^\(\w+(?:\.\w+)*\)\s*"),                    # (pyodbc.ProgrammingError)
    re.compile(r"^\(\s*'[^']*'\s*,\s*"),                       # ('42S22',
    re.compile(r"^[\"']\s*"),                                   # the opening quote
    re.compile(r"^(?:\[[^\]]*\]\s*)+"),                        # [42S22] [Microsoft] [SQL Server]
)
# Trailing native error codes and the wrapper's closing punctuation:
# `. (207) (SQLExecDirectW)")`
_DRIVER_TAIL = re.compile(r"\s*(?:\(\d+\)\s*)*(?:\(\w+\)\s*)*[\"']?\s*\)?\s*$")


def _humanise_driver_message(message: str) -> str:
    """Strip driver boilerplate so the database's own sentence is what shows.

    The Test panel renders this verbatim to whoever wrote the query, and
    "Invalid column name 'nope'." is the whole of what they need. Reduction
    only — if none of the patterns match, the original is returned untouched.
    """
    text = message.strip()
    for pattern in _DRIVER_WRAPPERS:
        text = pattern.sub("", text, count=1).strip()
    text = _DRIVER_TAIL.sub("", text).strip()
    return text or message.strip()


def _safe_driver_message(message: str, url: str, password: str) -> str:
    """Return a driver error with credentials removed but the diagnosis intact.

    The useful half of a driver error is the part naming the column or table
    that does not exist; the dangerous half is the DSN some drivers append. The
    secrets are known here, so they are removed by value rather than by
    discarding any message that looks like it might contain one.
    """
    cleaned = _SQLALCHEMY_NOISE.sub("", message)
    for secret in (url, password):
        if secret and len(secret) > 3:
            cleaned = cleaned.replace(secret, "***")
    # A DSN this did not recognise would still be a leak, so anything that still
    # carries one is dropped wholesale.
    if "://" in cleaned or "PWD=" in cleaned.upper():
        return "The query could not be run against this connection."
    return (
        _humanise_driver_message(cleaned)[:2000]
        or "The query failed with no message from the driver."
    )


def _connection_dict(conn: WarehouseConnection) -> dict[str, Any]:
    """Build the plain dict warehouse_inspector expects, with the password decrypted."""
    return {
        "db_type": conn.db_type,
        "host": conn.host,
        "port": conn.port,
        "database_name": conn.database_name,
        "username": conn.username,
        "password": crypto.decrypt(conn.password_encrypted) if conn.password_encrypted else "",
        "extra_config": conn.extra_config or {},
    }


def _operations_url() -> str:
    """Return a synchronous URL for the operations database.

    The query runs in a worker thread through a throwaway engine rather than on
    the request session: a report is user-authored SQL that may run for minutes,
    and it must not share a transaction with anything the application is doing.
    """
    url = settings.app_database_url
    for async_driver, sync_driver in (("+aioodbc", "+pyodbc"), ("+asyncpg", "+psycopg2")):
        if async_driver in url:
            return url.replace(async_driver, sync_driver)
    return url


def _apply_statement_timeout(connection: sa.Connection, seconds: int) -> None:
    """Ask the server to abandon the query after `seconds`.

    A ceiling the *database* enforces is the only one that works: cancelling on
    our side leaves the query running and still burning the warehouse's CPU. The
    spelling differs per engine and there is no portable form, so an engine that
    is not handled here simply runs without a server-side limit — the row and
    cell caps still bound what comes back.
    """
    dialect = connection.dialect.name
    try:
        if dialect == "mssql":
            # pyodbc puts the timeout on the DBAPI connection, in seconds.
            connection.connection.driver_connection.timeout = seconds
        elif dialect in ("postgresql", "redshift"):
            connection.execute(sa.text(f"SET statement_timeout = {seconds * 1000}"))
        elif dialect == "mysql":
            connection.execute(sa.text(f"SET SESSION max_execution_time = {seconds * 1000}"))
        elif dialect == "snowflake":
            connection.execute(
                sa.text(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {seconds}")
            )
    except Exception as exc:  # noqa: BLE001 — a missing ceiling must not fail the run
        logger.warning("export.timeout_not_applied", dialect=dialect, error=str(exc))


def _apply_read_only_transaction(connection: sa.Connection) -> None:
    """Ask the server to refuse writes for this transaction, where it can.

    This is the only *server-enforced* read-only guarantee available, and it
    beats every check we make ourselves — PostgreSQL rejects any write in a
    READ ONLY transaction, including the ones a parser would have to be clever
    to spot. It must run after begin(): the setting applies to the current
    transaction, and there is no current transaction before then.

    SQL Server has no equivalent. There, read-only rests on the statement guard,
    the unconditional rollback, and — the one that actually matters — giving the
    connection a login with only SELECT rights.
    """
    if connection.dialect.name in ("postgresql", "redshift"):
        try:
            connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        except Exception as exc:  # noqa: BLE001 — the other layers still apply
            logger.warning("export.read_only_not_applied", error=str(exc))


def _run_select_sync(
    url: str,
    connect_args: dict[str, Any],
    sql: str,
    max_rows: int,
    timeout_seconds: int,
    max_cells: int,
) -> tuple[list[str], list[list[Any]], bool]:
    """Execute sql against url inside a transaction that is always rolled back.

    Returns (columns, rows, truncated). Must be called in a worker thread.
    """
    from app.services.warehouse_inspector import _coerce_cell  # noqa: PLC0415

    engine = sa.create_engine(url, connect_args=connect_args, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _apply_statement_timeout(connection, timeout_seconds)
            # begin() here is explicit rather than relying on autobegin, because
            # the rollback in the finally clause is the actual guarantee and it
            # should be obvious that something opened what it closes.
            trans = connection.begin()
            _apply_read_only_transaction(connection)
            try:
                result = connection.execute(sa.text(sql))
                columns = list(result.keys())

                # A wide result hits the memory ceiling long before the row
                # ceiling, so the effective row limit is whichever binds first.
                width = max(1, len(columns))
                row_ceiling = min(max_rows, max(1, max_cells // width))

                fetched = result.fetchmany(row_ceiling + 1)
                truncated = len(fetched) > row_ceiling
                rows = [[_coerce_cell(v) for v in row] for row in fetched[:row_ceiling]]
                return columns, rows, truncated
            finally:
                trans.rollback()
    finally:
        engine.dispose()


async def run_report_query(
    db: AsyncSession,
    *,
    org_id: int,
    source_kind: str,
    sql: str,
    warehouse_connection_id: int | None,
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
) -> tuple[list[str], list[list[Any]], bool]:
    """Run a report's SQL against its source and return (columns, rows, truncated).

    Args:
        db: Session on the application database, used to look the connection up.
        org_id: Organisation the report belongs to; scopes the connection lookup.
        source_kind: 'operations' or 'warehouse'.
        sql: The report's SELECT statement.
        warehouse_connection_id: Required when source_kind is 'warehouse'.
        max_rows: Row ceiling; defaults to EXPORT_MAX_ROWS. One extra row is
            fetched to detect truncation, and a wide result is capped by
            EXPORT_MAX_CELLS before it reaches this.
        timeout_seconds: Server-side statement timeout; defaults to
            EXPORT_QUERY_TIMEOUT_SECONDS.

    Raises:
        ExportSourceError: If the source is unusable or the SQL is not read-only.
    """
    max_rows = MAX_REPORT_ROWS if max_rows is None else max_rows
    timeout_seconds = (
        settings.export_query_timeout_seconds if timeout_seconds is None else timeout_seconds
    )
    import asyncio  # noqa: PLC0415

    from app.services.warehouse_inspector import _connect_args, build_url  # noqa: PLC0415

    # Re-validated here even though the router checked at write time: this is
    # the last point before a driver sees the statement, and a report row can be
    # older than the rule that now applies to it.
    try:
        assert_read_only(sql)
    except ReadOnlySqlError as exc:
        raise ExportSourceError(str(exc)) from exc

    if source_kind not in VALID_SOURCE_KINDS:
        raise ExportSourceError(f"Unknown report source '{source_kind}'.")

    if source_kind == SOURCE_OPERATIONS:
        denied = denied_operations_tables(sql)
        if denied:
            raise ExportSourceError(
                "These operations tables hold credentials and cannot be exported: "
                f"{', '.join(denied)}."
            )
        url, connect_args, password = _operations_url(), {}, ""
    else:
        if warehouse_connection_id is None:
            raise ExportSourceError("This report has no warehouse connection selected.")
        conn = (
            await db.execute(
                sa.select(WarehouseConnection).where(
                    WarehouseConnection.id == warehouse_connection_id,
                    WarehouseConnection.org_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if conn is None:
            raise ExportSourceError("The warehouse connection this report uses no longer exists.")
        if not conn.is_active:
            raise ExportSourceError(f"The warehouse connection '{conn.name}' is disabled.")
        conn_dict = _connection_dict(conn)
        url, connect_args = build_url(conn_dict), _connect_args(conn_dict)
        password = conn_dict.get("password") or ""

    try:
        return await asyncio.to_thread(
            _run_select_sync,
            url,
            connect_args,
            sql,
            max_rows,
            timeout_seconds,
            settings.export_max_cells,
        )
    except ExportSourceError:
        raise
    except Exception as exc:  # noqa: BLE001 — any driver error is a report failure
        message = str(exc)
        if _looks_like_timeout(message):
            raise ExportSourceError(
                f"The query was still running after {timeout_seconds} seconds and was "
                "stopped. Narrow it — add a WHERE clause, or aggregate before exporting."
            ) from exc
        raise ExportSourceError(_safe_driver_message(message, url, password)) from exc
