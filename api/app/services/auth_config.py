"""Reads and writes per-org identity-provider configuration.

Secrets are masked on read and encrypted on write; the login page cannot use this —
it reads providers from env vars via the frontend's `lib/authProviders.ts`.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_config import AuthProviderConfig, MfaSettings
from app.services.crypto import encrypt

logger = structlog.get_logger(__name__)


async def get_providers(db: AsyncSession, org_id: int) -> list[dict[str, Any]]:
    """Return all OAuth/SSO provider configurations for the organisation.

    The client_secret is never returned; its presence is indicated by
    the has_client_secret boolean field.

    Args:
        db: Active async database session.
        org_id: Organisation to scope the query to.

    Returns:
        List of provider config dicts with client_secret masked.
    """
    result = await db.execute(
        select(AuthProviderConfig).where(AuthProviderConfig.org_id == org_id)
    )
    providers = result.scalars().all()
    return [
        {
            "id": p.id,
            "provider": p.provider,
            "enabled": p.enabled,
            "display_name": p.display_name,
            "client_id": p.client_id,
            "has_client_secret": p.client_secret_encrypted is not None,
            "config": p.config,
        }
        for p in providers
    ]


async def upsert_provider(
    db: AsyncSession, org_id: int, data: dict[str, Any]
) -> dict[str, Any]:
    """Create or update an OAuth/SSO provider configuration.

    Encrypts client_secret with Fernet before persisting. If client_secret
    is absent in data, the existing encrypted value is preserved.

    Args:
        db: Active async database session.
        org_id: Organisation that owns this provider config.
        data: Provider fields. Recognised keys: provider, enabled,
            display_name, client_id, client_secret, config.

    Returns:
        Saved provider config dict (client_secret masked).
    """
    provider_id: int | None = data.get("id")
    provider_name: str | None = data.get("provider")

    if provider_id is not None:
        # PUT by ID — look up the existing row directly.
        result = await db.execute(
            select(AuthProviderConfig).where(
                AuthProviderConfig.id == provider_id,
                AuthProviderConfig.org_id == org_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=404, detail="Provider not found")
    else:
        # POST by provider name — upsert.
        result = await db.execute(
            select(AuthProviderConfig).where(
                AuthProviderConfig.org_id == org_id,
                AuthProviderConfig.provider == provider_name,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            existing = AuthProviderConfig(org_id=org_id, provider=provider_name)
            db.add(existing)

    if "enabled" in data:
        existing.enabled = data["enabled"]
    if "display_name" in data:
        existing.display_name = data["display_name"]
    if "client_id" in data:
        existing.client_id = data["client_id"]
    if "client_secret" in data and data["client_secret"]:
        # Encrypt the secret before storing — never persist plaintext.
        encrypted = encrypt(data["client_secret"])
        existing.client_secret_encrypted = encrypted.encode()
    if "config" in data:
        existing.config = data["config"]

    await db.commit()
    await db.refresh(existing)
    logger.info("auth_config.provider_upserted", org_id=org_id, provider=provider_name)
    return {
        "id": existing.id,
        "provider": existing.provider,
        "enabled": existing.enabled,
        "display_name": existing.display_name,
        "client_id": existing.client_id,
        "has_client_secret": existing.client_secret_encrypted is not None,
        "config": existing.config,
    }


async def delete_provider(db: AsyncSession, org_id: int, provider_id: int) -> None:
    """Remove a provider configuration from the organisation.

    Args:
        db: Active async database session.
        org_id: Organisation scope guard.
        provider_id: Primary key of the provider to remove.

    Raises:
        HTTPException: 404 if the provider does not exist.
    """
    result = await db.execute(
        select(AuthProviderConfig).where(
            AuthProviderConfig.id == provider_id,
            AuthProviderConfig.org_id == org_id,
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    await db.delete(provider)
    await db.commit()


async def get_mfa_settings(db: AsyncSession, org_id: int) -> dict[str, Any]:
    """Return MFA settings for the organisation, creating defaults if absent.

    Args:
        db: Active async database session.
        org_id: Organisation to look up.

    Returns:
        MFA settings dict.
    """
    result = await db.execute(
        select(MfaSettings).where(MfaSettings.org_id == org_id)
    )
    mfa = result.scalar_one_or_none()
    if mfa is None:
        return {
            "org_id": org_id,
            "totp_enabled": True,
            "totp_required": False,
            "email_otp_enabled": False,
            "grace_period_days": 0,
        }
    return {
        "org_id": mfa.org_id,
        "totp_enabled": mfa.totp_enabled,
        "totp_required": mfa.totp_required,
        "email_otp_enabled": mfa.email_otp_enabled,
        "grace_period_days": mfa.grace_period_days,
    }


async def update_mfa_settings(
    db: AsyncSession, org_id: int, data: dict[str, Any]
) -> dict[str, Any]:
    """Create or update MFA settings for the organisation.

    Args:
        db: Active async database session.
        org_id: Organisation to update settings for.
        data: MFA setting fields to update.

    Returns:
        Updated MFA settings dict.
    """
    result = await db.execute(
        select(MfaSettings).where(MfaSettings.org_id == org_id)
    )
    mfa = result.scalar_one_or_none()
    if mfa is None:
        mfa = MfaSettings(org_id=org_id)
        db.add(mfa)

    if "totp_enabled" in data:
        mfa.totp_enabled = data["totp_enabled"]
    if "totp_required" in data:
        mfa.totp_required = data["totp_required"]
    if "email_otp_enabled" in data:
        mfa.email_otp_enabled = data["email_otp_enabled"]
    if "grace_period_days" in data:
        mfa.grace_period_days = data["grace_period_days"]

    await db.commit()
    await db.refresh(mfa)
    return {
        "org_id": mfa.org_id,
        "totp_enabled": mfa.totp_enabled,
        "totp_required": mfa.totp_required,
        "email_otp_enabled": mfa.email_otp_enabled,
        "grace_period_days": mfa.grace_period_days,
    }


async def get_sso_settings(db: AsyncSession, org_id: int) -> dict[str, Any]:
    """Return SSO enforcement settings for the organisation.

    SSO settings are stored as a synthetic AuthProviderConfig row with
    provider = 'sso_policy' so no new table is needed.

    Args:
        db: Active async database session.
        org_id: Organisation to look up.

    Returns:
        SSO settings dict with require_sso and allowed_providers keys.
    """
    result = await db.execute(
        select(AuthProviderConfig).where(
            AuthProviderConfig.org_id == org_id,
            AuthProviderConfig.provider == "sso_policy",
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {"require_sso": False, "allowed_providers": []}
    cfg = row.config or {}
    return {
        "require_sso": cfg.get("require_sso", False),
        "allowed_providers": cfg.get("allowed_providers", []),
    }


async def update_sso_settings(
    db: AsyncSession, org_id: int, data: dict[str, Any]
) -> dict[str, Any]:
    """Create or update SSO enforcement settings for the organisation.

    Args:
        db: Active async database session.
        org_id: Organisation to update.
        data: Dict with require_sso (bool) and allowed_providers (list[str]).

    Returns:
        Updated SSO settings dict.
    """
    result = await db.execute(
        select(AuthProviderConfig).where(
            AuthProviderConfig.org_id == org_id,
            AuthProviderConfig.provider == "sso_policy",
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = AuthProviderConfig(org_id=org_id, provider="sso_policy", enabled=True)
        db.add(row)

    cfg: dict[str, Any] = dict(row.config or {})
    if "require_sso" in data:
        cfg["require_sso"] = bool(data["require_sso"])
    if "allowed_providers" in data:
        cfg["allowed_providers"] = data["allowed_providers"]
    row.config = cfg

    await db.commit()
    return {
        "require_sso": cfg.get("require_sso", False),
        "allowed_providers": cfg.get("allowed_providers", []),
    }
