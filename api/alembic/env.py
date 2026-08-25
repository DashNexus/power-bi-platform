from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import all models so Alembic autogenerate discovers every table.
from app.models import *  # noqa: F401, F403
from app.models.base import Base


def _load_dotenv() -> None:
    """Load .env from the project root into os.environ, skipping set vars.

    Only parses simple KEY=VALUE lines — no shell variable expansion. Runs
    before any other code so that `alembic upgrade head` works without
    pre-setting environment variables in the shell.
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# The application talks to the database through an async driver, but Alembic
# runs migrations synchronously. Handing a sync engine an async DBAPI does not
# fail at connect — it fails mid-migration with `MissingGreenlet`, which reads
# like an application bug rather than a configuration one. Every async driver
# the app supports therefore needs its sync counterpart named here.
_SYNC_DRIVERS = {
    "+aioodbc": "+pyodbc",  # Azure SQL / SQL Server
    "+asyncpg": "+psycopg2",  # PostgreSQL (needs the warehouse-postgres extra)
}


def get_url() -> str:
    """Return a synchronous database URL for Alembic migrations.

    Raises:
        RuntimeError: If APP_DATABASE_URL is unset, or names an async driver
            with no sync counterpart registered above.
    """
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise RuntimeError(
            "APP_DATABASE_URL is not set. Copy .env.example to .env at the "
            "repository root, or export it before running alembic."
        )

    for async_driver, sync_driver in _SYNC_DRIVERS.items():
        if async_driver in url:
            return url.replace(async_driver, sync_driver)

    # A URL naming an async driver we do not know about would reach the sync
    # engine and fail confusingly, so say so plainly instead.
    if "+aio" in url or "+async" in url:
        raise RuntimeError(
            f"No synchronous driver is registered for the async driver in "
            f"APP_DATABASE_URL. Add it to _SYNC_DRIVERS in {__file__}."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection).

    Emits migration SQL to stdout for review or manual execution.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database connection."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
