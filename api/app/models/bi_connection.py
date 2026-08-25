"""Business-intelligence (embed) connection configurations.

A BI connection points at an external analytics/embedding platform — Power BI,
Tableau, the public Tableau Public / Looker Studio surfaces, and (planned)
Looker, Qlik, Superset, and others. Unlike the legacy single global embed
config, an org may hold many named connections.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BiConnection(Base, TimestampMixin):
    """A named connection to an external BI / embedding platform.

    Non-secret settings live in ``config`` (provider-specific: e.g. tenant_id /
    client_id / workspace_id for Power BI; server_url / site_id / connected-app
    ids for Tableau). The single primary secret (client secret or connected-app
    secret value) is Fernet-encrypted in ``secret_encrypted`` and never returned.

    Public providers (Tableau Public, Looker Studio) carry no secret and are
    limited to one connection per org (enforced in the router).
    """

    __tablename__ = "bi_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # provider key — see app.services.bi_providers registry
    # (powerbi | tableau | tableau_public | looker_studio | looker | qlik | ...)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Fernet-encrypted primary secret — never store or return plaintext
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
