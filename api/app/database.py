"""The two database engines and their session dependencies.

`get_app_db` is read-write on the application database. `get_warehouse_db` is
read-only and restricted to the `marts` schema by the login it authenticates as
— never write through it, and never run mart queries through the app session.

Both URLs accept either engine:

    mssql+aioodbc://user:pass@host:1433/db?driver=ODBC+Driver+18+for+SQL+Server
    postgresql+asyncpg://user:pass@host:5432/db

Where the two dialects disagree on raw-SQL syntax, `app/sql_compat.py` holds the
difference; everything else goes through the ORM, which handles it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy ORM models."""


app_engine = create_async_engine(
    settings.app_database_url,
    echo=False,
    pool_pre_ping=True,
)

warehouse_engine = create_async_engine(
    settings.warehouse_database_url,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=app_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

WarehouseSessionLocal = async_sessionmaker(
    bind=warehouse_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_app_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for the application database.

    Use this as a FastAPI dependency for all app DB operations.
    """
    async with AsyncSessionLocal() as session:
        yield session


async def get_warehouse_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a read-only async session for the warehouse database.

    Use this as a FastAPI dependency for mart data queries only.
    The warehouse_reader role restricts access to the marts schema.
    """
    async with WarehouseSessionLocal() as session:
        yield session
