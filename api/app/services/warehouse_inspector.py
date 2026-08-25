"""Warehouse connection testing and schema introspection.

Connects to any supported warehouse type using synchronous SQLAlchemy and
inspects table/column structure. All public entry points are async wrappers
that run the synchronous work in a thread pool via asyncio.to_thread, keeping
the FastAPI event loop unblocked.

Supported db_type values:
    postgresql, redshift, mysql, sqlserver, snowflake, bigquery, databricks
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.pool import NullPool

# Default ports per db_type; callers may override via the port field.
_DEFAULT_PORTS: dict[str, int] = {
    "postgresql": 5432,
    "redshift": 5439,
    "mysql": 3306,
    "sqlserver": 1433,
    "snowflake": 443,
    "databricks": 443,
}


def build_url(conn: dict[str, Any]) -> str:
    """Construct a SQLAlchemy connection URL from a warehouse connection dict.

    Args:
        conn: Warehouse connection dict with keys matching WarehouseConnection
            model fields (db_type, host, port, database_name, username,
            password_encrypted is already decrypted by caller, extra_config).

    Returns:
        A SQLAlchemy connection URL string.

    Raises:
        ValueError: If the db_type is unknown or required fields are missing.
    """
    db_type = conn.get("db_type", "")
    password = conn.get("password", "")  # caller must decrypt before calling
    username = conn.get("username") or ""
    host = conn.get("host") or "localhost"
    port = conn.get("port") or _DEFAULT_PORTS.get(db_type)
    database = conn.get("database_name") or ""
    extra = conn.get("extra_config") or {}

    # Percent-encode so that special characters in passwords (@, #, /, :, %)
    # don't break URL parsing — the driver decodes them before connecting.
    enc_user = quote(username, safe="")
    enc_pass = quote(password, safe="")

    if db_type in ("postgresql", "redshift"):
        driver = "postgresql+psycopg2" if db_type == "postgresql" else "redshift+psycopg2"
        return f"{driver}://{enc_user}:{enc_pass}@{host}:{port}/{database}"

    if db_type == "mysql":
        return f"mysql+pymysql://{enc_user}:{enc_pass}@{host}:{port}/{database}"

    if db_type == "sqlserver":
        # pyodbc driver string embedded as query param
        driver_str = extra.get("driver", "ODBC Driver 18 for SQL Server")
        encoded_driver = driver_str.replace(" ", "+")
        return (
            f"mssql+pyodbc://{enc_user}:{enc_pass}@{host}:{port}/{database}"
            f"?driver={encoded_driver}&TrustServerCertificate=yes"
        )

    if db_type == "snowflake":
        account = extra.get("account", "")
        warehouse_name = extra.get("warehouse", "")
        role = extra.get("role", "")
        private_key_pem = extra.get("private_key_pem", "")
        if private_key_pem:
            # Key-pair auth: no password in URL; key bytes go to connect_args.
            url = f"snowflake://{enc_user}@{account}/{database}"
        else:
            url = f"snowflake://{enc_user}:{enc_pass}@{account}/{database}"
        params: list[str] = []
        if warehouse_name:
            params.append(f"warehouse={warehouse_name}")
        if role:
            params.append(f"role={role}")
        if params:
            url = f"{url}?{'&'.join(params)}"
        return url

    if db_type == "bigquery":
        # BigQuery uses a service account JSON; project is required.
        # Accept both "project" (auth-config path) and "project_id" (warehouses page path).
        project = extra.get("project") or extra.get("project_id") or database
        if not project:
            raise ValueError("BigQuery connection requires extra_config.project or database_name")
        # Accept both "credentials_json" (auth-config path) and "service_account_json"
        # (warehouses page path — stored directly in extra_config JSON column).
        credentials_json = extra.get("credentials_json") or extra.get("service_account_json")
        if credentials_json:
            # Write credentials to a temp file; SQLAlchemy BigQuery reads a path.
            # We pass the JSON inline via create_engine credentials_base64 instead.
            import base64  # noqa: PLC0415

            if isinstance(credentials_json, dict):
                credentials_json = json.dumps(credentials_json)
            encoded = base64.b64encode(credentials_json.encode()).decode()
            return f"bigquery://{project}?credentials_base64={encoded}"
        return f"bigquery://{project}"

    if db_type == "databricks":
        http_path = extra.get("http_path", "")
        token = password or extra.get("token", "")
        return (
            f"databricks://token:{token}@{host}:{port or 443}"
            f"?http_path={http_path}&catalog={database}"
        )

    raise ValueError(f"Unsupported db_type: {db_type!r}")


def _connect_args(conn: dict[str, Any]) -> dict[str, Any]:
    """Return driver-specific connect_args for the given connection."""
    db_type = conn.get("db_type", "")
    extra = conn.get("extra_config") or {}

    if db_type in ("postgresql", "redshift"):
        return {"connect_timeout": 10}
    if db_type == "mysql":
        return {"connect_timeout": 10}
    if db_type == "snowflake":
        private_key_pem = extra.get("private_key_pem", "")
        if private_key_pem:
            # Convert PEM → DER for Snowflake key-pair auth.
            # cryptography is already a core dependency (cryptography>=42.0.0).
            from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

            passphrase_str = extra.get("private_key_passphrase", "") or ""
            passphrase = passphrase_str.encode() if passphrase_str else None
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=passphrase,
            )
            pkb = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            return {"private_key": pkb}
    # other drivers handle timeout differently or via URL params
    return {}


def test_connection_sync(conn: dict[str, Any]) -> dict[str, Any]:
    """Test a warehouse connection synchronously.

    Executes a trivial query (SELECT 1) and counts tables in the configured
    schemas. Must be called via asyncio.to_thread from async callers.

    Args:
        conn: Warehouse connection dict. The 'password' key must already be
            the decrypted plaintext (not password_encrypted).

    Returns:
        {"ok": True, "table_count": N} on success, or
        {"ok": False, "error": "<message>"} on failure.
    """
    try:
        url = build_url(conn)
        # NullPool creates a fresh physical connection per connect() call and
        # closes it immediately on release — no pool bookkeeping, no pool-size
        # limits. Safe for one-shot test/introspect operations and avoids
        # QueuePool exhaustion when the dialect opens extra connections
        # internally during schema reflection.
        engine = sa.create_engine(
            url,
            connect_args=_connect_args(conn),
            poolclass=NullPool,
        )
        schemas: list[str | None] = conn.get("schemas") or [None]
        if not schemas:
            schemas = [None]

        table_count = 0
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
            insp = sa_inspect(connection)
            for schema in schemas:
                try:
                    table_count += len(insp.get_table_names(schema=schema))
                except Exception:
                    # Schema may not exist or driver may not support listing by schema
                    pass

        engine.dispose()
        return {"ok": True, "table_count": table_count}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def test_connection(conn: dict[str, Any]) -> dict[str, Any]:
    """Async wrapper for test_connection_sync.

    Args:
        conn: Warehouse connection dict with plaintext 'password' key.

    Returns:
        Same dict as test_connection_sync.
    """
    import asyncio  # noqa: PLC0415

    return await asyncio.to_thread(test_connection_sync, conn)


def _introspect_bigquery_sync(
    conn: dict[str, Any],
    schemas: list[str | None],
) -> list[dict[str, Any]]:
    """BigQuery introspection via INFORMATION_SCHEMA SQL queries.

    Uses direct SQL against INFORMATION_SCHEMA views instead of SQLAlchemy
    Inspector calls. The Inspector path is unreliable for BigQuery: it makes
    one round-trip per table for get_columns, fails silently on views and
    external tables, and does not expose column descriptions.

    Args:
        conn: Warehouse connection dict with plaintext credentials.
        schemas: List of dataset names to introspect. [None] triggers
            auto-discovery of all datasets in the project.

    Returns:
        Same structure as introspect_schemas_sync.
    """
    url = build_url(conn)
    engine = sa.create_engine(url, connect_args=_connect_args(conn), poolclass=NullPool)
    extra = conn.get("extra_config") or {}
    project = (
        extra.get("project")
        or extra.get("project_id")
        or conn.get("database_name")
        or ""
    )

    result: list[dict[str, Any]] = []
    connection = engine.connect()
    try:
        # Auto-discover datasets when none are configured
        if schemas == [None]:
            try:
                insp = sa_inspect(connection)
                discovered = insp.get_schema_names()
                schemas = [s for s in (discovered or []) if s]
            except Exception:
                schemas = []

        for schema in schemas:
            if not schema:
                continue

            schema_entry: dict[str, Any] = {"name": schema, "tables": []}

            # ---- Tables ----
            try:
                table_rows = connection.execute(
                    sa.text(
                        f"SELECT table_name, table_type "
                        f"FROM `{project}.{schema}.INFORMATION_SCHEMA.TABLES` "
                        f"WHERE table_type IN ('BASE TABLE', 'VIEW', 'EXTERNAL') "
                        f"ORDER BY table_name"
                    )
                ).fetchall()
            except Exception:
                result.append(schema_entry)
                continue

            # ---- All columns ordered by position ----
            # INFORMATION_SCHEMA.COLUMNS has ordinal_position; COLUMN_FIELD_PATHS does not.
            try:
                col_rows = connection.execute(
                    sa.text(
                        f"SELECT table_name, column_name, data_type, "
                        f"  CASE is_nullable WHEN 'YES' THEN TRUE ELSE FALSE END AS is_nullable "
                        f"FROM `{project}.{schema}.INFORMATION_SCHEMA.COLUMNS` "
                        f"ORDER BY table_name, ordinal_position"
                    )
                ).fetchall()
            except Exception:
                col_rows = []

            # ---- Column descriptions (COLUMN_FIELD_PATHS, top-level fields only) ----
            col_desc_map: dict[tuple[str, str], str | None] = {}
            try:
                desc_rows = connection.execute(
                    sa.text(
                        f"SELECT table_name, column_name, description "
                        f"FROM `{project}.{schema}.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` "
                        f"WHERE field_path = column_name"
                    )
                ).fetchall()
                col_desc_map = {(r[0], r[1]): r[2] or None for r in desc_rows}
            except Exception:
                pass

            cols_by_table: dict[str, list[dict[str, Any]]] = {}
            for row in col_rows:
                t_name: str = row[0]
                if t_name not in cols_by_table:
                    cols_by_table[t_name] = []
                cols_by_table[t_name].append(
                    {
                        "name": row[1],
                        "type": row[2],
                        "description": col_desc_map.get((t_name, row[1])),
                        "nullable": bool(row[3]),
                        "pk": False,
                        "fk_ref": None,
                    }
                )

            # ---- PK constraints (unenforced BigQuery PKs via ALTER TABLE … NOT ENFORCED) ----
            pk_by_table: dict[str, set[str]] = {}
            try:
                pk_rows = connection.execute(
                    sa.text(
                        f"SELECT kcu.table_name, kcu.column_name "
                        f"FROM `{project}.{schema}.INFORMATION_SCHEMA.TABLE_CONSTRAINTS` tc "
                        f"JOIN `{project}.{schema}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE` kcu "
                        f"  ON tc.constraint_name = kcu.constraint_name "
                        f"  AND tc.table_name = kcu.table_name "
                        f"WHERE tc.constraint_type = 'PRIMARY KEY'"
                    )
                ).fetchall()
                for pk_row in pk_rows:
                    pk_by_table.setdefault(pk_row[0], set()).add(pk_row[1])
            except Exception:
                pass

            # ---- Table-level descriptions ----
            table_desc: dict[str, str | None] = {}
            try:
                desc_rows = connection.execute(
                    sa.text(
                        f"SELECT table_name, option_value "
                        f"FROM `{project}.{schema}.INFORMATION_SCHEMA.TABLE_OPTIONS` "
                        f"WHERE option_name = 'description'"
                    )
                ).fetchall()
                for dr in desc_rows:
                    # BigQuery wraps string option values in double quotes
                    raw = (dr[1] or "").strip('"')
                    table_desc[dr[0]] = raw or None
            except Exception:
                pass

            for table_name, table_type in table_rows:
                pk_cols = pk_by_table.get(table_name, set())
                columns = cols_by_table.get(table_name, [])
                for col in columns:
                    col["pk"] = col["name"] in pk_cols

                schema_entry["tables"].append(
                    {
                        "name": table_name,
                        "object_type": "view" if table_type == "VIEW" else "table",
                        "description": table_desc.get(table_name),
                        "columns": columns,
                    }
                )

            result.append(schema_entry)
    finally:
        connection.close()
        engine.dispose()

    return result


def introspect_schemas_sync(
    conn: dict[str, Any],
    target_schemas: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Introspect warehouse schema structure synchronously.

    Connects to the warehouse and returns table/column metadata for each
    schema. Must be called via asyncio.to_thread from async callers.

    Args:
        conn: Warehouse connection dict with plaintext 'password' key.
        target_schemas: Schema names to inspect. When None, falls back to
            conn["schemas"]. When that is also empty, inspects the default
            schema only.

    Returns:
        List of schema dicts:
        [{
            "name": "<schema>",
            "tables": [{
                "name": "<table>",
                "object_type": "table" | "view",
                "description": "<table comment>" | None,
                "columns": [{
                    "name": "<col>",
                    "type": "<type_string>",
                    "nullable": True|False,
                    "pk": True|False,
                    "fk_ref": "<schema>.<table>.<col>" | None,
                    "description": "<column comment>" | None,
                }],
            }],
        }]

    Raises:
        Exception: Re-raises any connection or inspection error to the caller.
    """
    url = build_url(conn)
    engine = sa.create_engine(
        url,
        connect_args=_connect_args(conn),
        poolclass=NullPool,
    )

    schemas = target_schemas or conn.get("schemas") or [None]
    if not schemas:
        schemas = [None]

    # BigQuery uses a dedicated INFORMATION_SCHEMA path: SQLAlchemy Inspector
    # makes one round-trip per table for get_columns, fails silently on views
    # and external tables, and cannot surface column descriptions.
    if conn.get("db_type") == "bigquery":
        engine.dispose()
        return _introspect_bigquery_sync(conn, schemas)

    result: list[dict[str, Any]] = []

    connection = engine.connect()
    try:
        insp = sa_inspect(connection)

        # Deduplicate schema list — a misconfigured connection can produce
        # duplicate entries for the same schema.
        seen_schemas: set[str | None] = set()
        unique_schemas: list[str | None] = []
        for s in schemas:
            if s not in seen_schemas:
                seen_schemas.add(s)
                unique_schemas.append(s)
        schemas = unique_schemas

        for schema in schemas:
            schema_entry: dict[str, Any] = {
                "name": schema or "default",
                "tables": [],
            }

            try:
                table_names = insp.get_table_names(schema=schema)
            except Exception:
                result.append(schema_entry)
                continue

            try:
                view_names = insp.get_view_names(schema=schema)
            except Exception:
                view_names = []

            view_name_set = set(view_names)
            for table_name in list(table_names) + list(view_names):
                is_view = table_name in view_name_set
                table_entry: dict[str, Any] = {
                    "name": table_name,
                    "object_type": "view" if is_view else "table",
                    "description": None,
                    "columns": [],
                }

                # Table-level comment — many dialects don't implement this, so
                # swallow any error and leave description as None.
                try:
                    comment_info = insp.get_table_comment(table_name, schema=schema)
                    table_entry["description"] = comment_info.get("text") or None
                except Exception:
                    pass

                # Primary key columns
                try:
                    pk_info = insp.get_pk_constraint(table_name, schema=schema)
                    pk_cols: set[str] = set(pk_info.get("constrained_columns") or [])
                except Exception:
                    pk_cols = set()

                # Foreign key mapping: col_name → "target_schema.target_table.target_col"
                fk_map: dict[str, str] = {}
                try:
                    fk_list = insp.get_foreign_keys(table_name, schema=schema)
                    for fk in fk_list:
                        local_cols: list[str] = fk.get("constrained_columns") or []
                        referred_schema: str = fk.get("referred_schema") or schema or ""
                        referred_table: str = fk.get("referred_table") or ""
                        referred_cols: list[str] = fk.get("referred_columns") or []
                        for local_col, ref_col in zip(local_cols, referred_cols):
                            ref_parts = [p for p in [referred_schema, referred_table, ref_col] if p]
                            fk_map[local_col] = ".".join(ref_parts)
                except Exception:
                    pass

                # Columns
                try:
                    columns = insp.get_columns(table_name, schema=schema)
                except Exception:
                    # Column introspection failed; still include the table with
                    # no column metadata so it remains visible in the tree.
                    schema_entry["tables"].append(table_entry)
                    continue

                for col in columns:
                    col_name: str = col.get("name") or ""
                    col_type = col.get("type")
                    try:
                        type_str = str(col_type)
                    except Exception:
                        type_str = "unknown"

                    table_entry["columns"].append(
                        {
                            "name": col_name,
                            "type": type_str,
                            "nullable": bool(col.get("nullable", True)),
                            "pk": col_name in pk_cols,
                            "fk_ref": fk_map.get(col_name),
                            "description": col.get("comment") or None,
                        }
                    )

                schema_entry["tables"].append(table_entry)

            result.append(schema_entry)
    finally:
        connection.close()
        engine.dispose()

    return result


async def introspect_schemas(
    conn: dict[str, Any],
    target_schemas: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Async wrapper for introspect_schemas_sync.

    Args:
        conn: Warehouse connection dict with plaintext 'password' key.
        target_schemas: Schema names to inspect; see introspect_schemas_sync.

    Returns:
        Same list as introspect_schemas_sync.
    """
    import asyncio  # noqa: PLC0415

    return await asyncio.to_thread(introspect_schemas_sync, conn, target_schemas)


def run_select_sync(
    conn: dict[str, Any],
    sql: str,
    max_rows: int,
) -> tuple[list[str], list[list[Any]], int, str | None]:
    """Execute a SELECT against a warehouse connection synchronously.

    Returns (columns, rows, total_fetched, error). Caller is responsible for
    validating that sql is SELECT-only before calling. Must be invoked via
    asyncio.to_thread from async callers.

    Args:
        conn: Warehouse connection dict with a decrypted plaintext 'password'.
        sql: A validated SELECT statement.
        max_rows: Maximum number of rows to return.
    """
    engine = None
    try:
        engine = sa.create_engine(
            build_url(conn),
            connect_args=_connect_args(conn),
            poolclass=NullPool,
        )
        with engine.connect() as connection:
            result = connection.execute(sa.text(sql))
            columns = list(result.keys())
            fetched = result.fetchmany(max_rows + 1)
            total = len(fetched)
            rows = [[_coerce_cell(v) for v in row] for row in fetched[:max_rows]]
            return columns, rows, total, None
    except Exception as exc:
        msg = str(exc)
        if "\nDETAIL:" in msg:
            msg = msg[: msg.index("\nDETAIL:")]
        return [], [], 0, msg
    finally:
        if engine is not None:
            engine.dispose()


def _coerce_cell(v: Any) -> Any:
    """JSON-safe coercion of a driver cell value."""
    import datetime as _dt  # noqa: PLC0415
    import decimal as _decimal  # noqa: PLC0415
    import uuid as _uuid  # noqa: PLC0415

    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, _decimal.Decimal):
        return float(v)
    if isinstance(v, _uuid.UUID):
        return str(v)
    if isinstance(v, bytes):
        return v.hex()
    return v


async def run_select(
    conn: dict[str, Any],
    sql: str,
    max_rows: int,
) -> tuple[list[str], list[list[Any]], int, str | None]:
    """Async wrapper for run_select_sync (runs in a thread)."""
    import asyncio  # noqa: PLC0415

    return await asyncio.to_thread(run_select_sync, conn, sql, max_rows)
