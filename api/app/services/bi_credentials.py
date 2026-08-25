"""Adapt a stored BI connection into the credential shape the embedders use.

The Power BI and Tableau embedders were written against AuthProviderConfig rows
(``.config`` dict, ``.client_id``, ``.client_secret_encrypted`` bytes). A
DashboardConfig now links to a BiConnection instead; this module exposes that
connection through the same attribute surface so the embedders can source
credentials per-dashboard with minimal change. When a dashboard has no linked
connection the embedders fall back to their original global config.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bi_connection import BiConnection


async def load_connection_as_config(
    db: AsyncSession, org_id: int, connection_id: int, *, client_id_key: str
) -> SimpleNamespace:
    """Return a config shim for a BI connection.

    Args:
        db: Async DB session.
        org_id: Organisation scope.
        connection_id: BiConnection primary key.
        client_id_key: Which config field holds the client id for this provider
            (``client_id`` for Power BI, ``connected_app_client_id`` for Tableau).

    Returns:
        An object with ``config`` (dict), ``client_id`` (str), and
        ``client_secret_encrypted`` (bytes) — matching AuthProviderConfig usage.

    Raises:
        HTTPException: 400 if the connection is missing or inactive.
    """
    conn = (
        await db.execute(
            select(BiConnection).where(
                BiConnection.id == connection_id,
                BiConnection.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=400, detail="Linked BI connection not found")
    if not conn.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"BI connection '{conn.name}' is disabled",
        )
    cfg = dict(conn.config or {})
    return SimpleNamespace(
        config=cfg,
        client_id=cfg.get(client_id_key, ""),
        # Embedders call .decode() then crypto.decrypt(); secret_encrypted is a
        # Fernet-token str, so encoding to bytes round-trips cleanly.
        client_secret_encrypted=(conn.secret_encrypted or "").encode(),
    )
