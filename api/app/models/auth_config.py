"""Per-org identity-provider and MFA configuration.

Client secrets are Fernet-encrypted via `services/crypto.py`; never store plaintext.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuthProviderConfig(Base):
    """OAuth/SSO provider configuration for an organisation.

    Stores provider-specific credentials and settings. client_secret is
    stored Fernet-encrypted; never expose the plaintext value in API responses.

    Config keys (stored in the config JSON column):
        tenant_id: Azure AD / Entra tenant ID (Microsoft provider).
        server_url: Tableau server URL (tableau_connected_app provider).
        site_id: Tableau site ID.
    """

    __tablename__ = "auth_provider_configs"
    __table_args__ = (
        UniqueConstraint("org_id", "provider", name="uq_auth_provider_org_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MfaSettings(Base):
    """MFA configuration for an organisation."""

    __tablename__ = "mfa_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orgs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    totp_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_otp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
