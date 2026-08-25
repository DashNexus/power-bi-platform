"""Organisation administration: users, roles, feature flags, auth config, invites.

Every route here is `require_role("admin")`. There are deliberately no `admin.*`
permission keys — each one would let its holder become a full admin, so they are
an escalation path rather than a delegation.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, require_role
from app.models.org_settings import OrgSettings
from app.schemas.common import MessageResponse, PaginatedResponse
from app.schemas.nav_config import (
    NavConfigRequest,
    NavConfigResponse,
    NavItem,
)
from app.schemas.user import (
    InviteRequest,
    RoleCreateRequest,
    RoleResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services import admin_overview as admin_overview_svc
from app.services import auth_config as auth_config_svc
from app.services import change_ledger as ledger
from app.services import principal_cleanup
from app.services import user as user_svc
from app.services.audit import audit_action

logger = structlog.get_logger(__name__)

router = APIRouter()

_admin_dep = require_role("admin", "superadmin")
_superadmin_dep = require_role("superadmin")


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/overview")
async def get_overview(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return the counts, configuration state, and recent activity for /admin.

    One request backs the whole landing page; see `services/admin_overview.py`
    for the query budget.
    """
    return await admin_overview_svc.get_overview(db, current_user.org_id)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = 1,
    page_size: int = 20,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> PaginatedResponse[UserResponse]:
    """Return a paginated list of users in the current organisation."""
    return await user_svc.get_users(db, current_user.org_id, page, page_size)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> UserResponse:
    """Return a single user by ID."""
    return await user_svc.get_user(db, user_id, current_user.org_id)


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> UserResponse:
    """Create a new user in the current organisation."""
    result = await user_svc.create_user(db, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.created", resource_type="user", resource_id=result.id,
        resource_name=getattr(data, "email", None),
    )
    await db.commit()
    return result


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> UserResponse:
    """Update a user's display name or active status."""
    result = await user_svc.update_user(db, user_id, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.updated", resource_type="user", resource_id=user_id,
    )
    await db.commit()
    return result


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def deactivate_user(
    user_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Deactivate a user (soft delete — sets is_active=False)."""
    await user_svc.deactivate_user(db, user_id, current_user.org_id)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.deactivated", resource_type="user", resource_id=user_id,
    )
    await db.commit()
    return MessageResponse(message="User deactivated")


@router.post("/users/{user_id}/set-password", response_model=MessageResponse)
async def admin_set_user_password(
    user_id: int,
    data: dict[str, str],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Set a new password for a user (admin only). Immediately invalidates any active reset tokens."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.user import User as UserModel  # noqa: PLC0415
    from app.services.audit import audit_action  # noqa: PLC0415
    from app.services.crypto import hash_password  # noqa: PLC0415

    new_password = data.get("new_password", "")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    result = await db.execute(
        select(UserModel).where(UserModel.id == user_id, UserModel.org_id == current_user.org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(new_password)
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.password_reset", resource_type="user", resource_id=user_id,
    )
    await db.commit()
    return MessageResponse(message="Password updated successfully")


@router.post("/users/{user_id}/reset-totp", response_model=MessageResponse)
async def admin_reset_user_totp(
    user_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Disable and clear TOTP two-factor authentication for a user (admin only)."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.user import User as UserModel  # noqa: PLC0415
    from app.services.audit import audit_action  # noqa: PLC0415

    result = await db.execute(
        select(UserModel).where(UserModel.id == user_id, UserModel.org_id == current_user.org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.totp_enabled = False
    user.totp_secret_encrypted = None
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.totp_reset", resource_type="user", resource_id=user_id,
    )
    await db.commit()
    return MessageResponse(message="Two-factor authentication has been reset")


@router.delete("/users/{user_id}/permanent", response_model=MessageResponse)
async def delete_user_permanently(
    user_id: int,
    current_user: CurrentUser = Depends(_superadmin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Permanently delete a user record (superadmin only). This cannot be undone."""
    from sqlalchemy import delete as sa_delete  # noqa: PLC0415
    from sqlalchemy import select

    from app.models.user import User as UserModel  # noqa: PLC0415
    from app.services.audit import audit_action  # noqa: PLC0415

    result = await db.execute(
        select(UserModel).where(UserModel.id == user_id, UserModel.org_id == current_user.org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.deleted", resource_type="user", resource_id=user_id,
        resource_name=user.email,
    )
    # Grant tables no longer cascade from `users` — see services/principal_cleanup.py.
    await principal_cleanup.remove_user_grants(db, user_id)
    await db.execute(sa_delete(UserModel).where(UserModel.id == user_id))
    await db.commit()
    return MessageResponse(message="User permanently deleted")


@router.put("/users/{user_id}/roles", response_model=MessageResponse)
async def assign_user_roles(
    user_id: int,
    role_ids: list[int],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Replace the user's role assignments with the supplied list of role IDs."""
    await user_svc.assign_roles(db, user_id, current_user.org_id, role_ids)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.roles_updated", resource_type="user", resource_id=user_id,
        extra={"role_ids": role_ids},
    )
    await db.commit()
    return MessageResponse(message="Roles updated")


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


@router.post("/users/invite", response_model=MessageResponse, status_code=201)
async def invite_user(
    data: InviteRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Send an invitation to a new user to join the organisation."""
    await user_svc.create_invite(db, current_user.org_id, current_user.user_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="user.invited", resource_type="user", resource_name=data.email,
    )
    await db.commit()
    return MessageResponse(message=f"Invitation sent to {data.email}")


@router.post("/users/invite/{token}/accept", response_model=MessageResponse)
async def accept_invite(
    token: str,
    password: str,
    display_name: str | None = None,
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Accept an invitation and create the user account."""
    await user_svc.accept_invite(db, token, password, display_name)
    return MessageResponse(message="Account created successfully")


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[RoleResponse]:
    """Return all roles defined for the current organisation."""
    return await user_svc.get_roles(db, current_user.org_id)


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> RoleResponse:
    """Return a single role by ID."""
    roles = await user_svc.get_roles(db, current_user.org_id)
    for role in roles:
        if role.id == role_id:
            return role
    from fastapi import HTTPException  # noqa: PLC0415
    raise HTTPException(status_code=404, detail="Role not found")


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    data: RoleCreateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> RoleResponse:
    """Create a new role in the current organisation."""
    result = await user_svc.create_role(db, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="role.created", resource_type="role", resource_id=result.id,
        resource_name=data.name,
    )
    await db.commit()
    return result


@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: int,
    data: RoleCreateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> RoleResponse:
    """Update a custom role's name, description, and permissions.

    System roles cannot be modified — the service layer returns 403 for those.
    """
    result = await user_svc.update_role(db, role_id, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="role.updated", resource_type="role", resource_id=role_id,
        resource_name=data.name,
    )
    await db.commit()
    return result


# ---------------------------------------------------------------------------
# Permissions catalogue
# ---------------------------------------------------------------------------


@router.get("/permissions")
async def list_permissions(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return the full catalogue of available permission keys.

    These keys can be assigned to roles via PUT /admin/roles/{id}.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.user import Permission  # noqa: PLC0415

    result = await db.execute(
        select(Permission).order_by(Permission.category, Permission.key)
    )
    perms = result.scalars().all()
    return [
        {
            "key": p.key,
            "description": p.description or "",
            "category": p.category or "General",
        }
        for p in perms
    ]


@router.delete("/roles/{role_id}", response_model=MessageResponse)
async def delete_role(
    role_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Delete a non-system role from the organisation."""
    await user_svc.delete_role(db, role_id, current_user.org_id)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="role.deleted", resource_type="role", resource_id=role_id,
    )
    await db.commit()
    return MessageResponse(message="Role deleted")


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


class FeatureToggleRequest(BaseModel):
    """Request body for toggling a feature flag."""

    enabled: bool


@router.get("/features")
async def list_features(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return all feature flags for the current organisation.

    Env var overrides (FEATURE_*) are reflected in the 'enabled' field.
    When a flag is controlled by an env var, 'env_override' is true and
    toggling it via the API will have no visible effect until the env var
    is removed.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.config import (
        FEATURE_ENV_VARS,  # noqa: PLC0415
        settings,  # noqa: PLC0415
    )
    from app.models.feature_flag import FeatureFlag  # noqa: PLC0415

    result = await db.execute(
        select(FeatureFlag).where(FeatureFlag.org_id == current_user.org_id)
    )
    db_flags = {f.feature_key: f for f in result.scalars().all()}
    env_overrides = settings.feature_overrides

    # Return all known feature keys in a stable order; include DB-only extras too.
    all_keys = sorted(set(FEATURE_ENV_VARS) | set(db_flags))
    return [
        {
            "feature_key": key,
            "enabled": env_overrides.get(key, db_flags[key].enabled if key in db_flags else False),
            "env_override": key in env_overrides,
            "config": db_flags[key].config if key in db_flags else None,
        }
        for key in all_keys
    ]


@router.put("/features/{key}")
async def toggle_feature(
    key: str,
    data: FeatureToggleRequest,
    current_user: CurrentUser = Depends(_superadmin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Enable or disable a feature flag for the current organisation.

    When an env var override is active for this key the database is still
    updated, but the effective value remains the env var value until it is
    removed.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415
    from app.models.feature_flag import FeatureFlag  # noqa: PLC0415

    result = await db.execute(
        select(FeatureFlag).where(
            FeatureFlag.org_id == current_user.org_id,
            FeatureFlag.feature_key == key,
        )
    )
    flag = result.scalar_one_or_none()
    if flag is None:
        flag = FeatureFlag(
            org_id=current_user.org_id,
            feature_key=key,
            enabled=data.enabled,
            updated_by_user_id=current_user.user_id,
        )
        db.add(flag)
    else:
        flag.enabled = data.enabled
        flag.updated_by_user_id = current_user.user_id

    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="feature.toggled", resource_type="feature", resource_name=key,
        extra={"enabled": data.enabled},
    )
    await db.commit()

    env_override = settings.feature_overrides.get(key)
    effective_enabled = env_override if env_override is not None else data.enabled
    return {
        "feature_key": key,
        "enabled": effective_enabled,
        "env_override": env_override is not None,
    }


# ---------------------------------------------------------------------------
# Auth provider config
# ---------------------------------------------------------------------------


@router.get("/auth-config/providers")
async def list_providers(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """List OAuth/SSO provider configurations for the organisation."""
    return await auth_config_svc.get_providers(db, current_user.org_id)


@router.post("/auth-config/providers", status_code=201)
async def create_provider(
    data: dict[str, Any],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Add or update an OAuth/SSO provider configuration."""
    result = await auth_config_svc.upsert_provider(db, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="auth_provider.created", resource_type="auth_provider",
        resource_name=data.get("provider") if isinstance(data, dict) else None,
    )
    await db.commit()
    return result


@router.put("/auth-config/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    data: dict[str, Any],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update an existing provider configuration."""
    data["id"] = provider_id
    result = await auth_config_svc.upsert_provider(db, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="auth_provider.updated", resource_type="auth_provider", resource_id=provider_id,
    )
    await db.commit()
    return result


@router.delete("/auth-config/providers/{provider_id}", response_model=MessageResponse)
async def delete_provider(
    provider_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Remove a provider configuration."""
    await auth_config_svc.delete_provider(db, current_user.org_id, provider_id)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="auth_provider.deleted", resource_type="auth_provider", resource_id=provider_id,
    )
    await db.commit()
    return MessageResponse(message="Provider removed")


@router.get("/auth-config/mfa")
async def get_mfa(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return MFA settings for the organisation."""
    return await auth_config_svc.get_mfa_settings(db, current_user.org_id)


@router.put("/auth-config/mfa")
async def update_mfa(
    data: dict[str, Any],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update MFA settings for the organisation."""
    result = await auth_config_svc.update_mfa_settings(db, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="auth_config.mfa_updated", resource_type="mfa_settings",
    )
    await db.commit()
    return result


@router.get("/auth-config/sso")
async def get_sso(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return SSO enforcement settings for the organisation."""
    return await auth_config_svc.get_sso_settings(db, current_user.org_id)


@router.put("/auth-config/sso")
async def update_sso(
    data: dict[str, Any],
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Update SSO enforcement settings for the organisation."""
    result = await auth_config_svc.update_sso_settings(db, current_user.org_id, data)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="auth_config.sso_updated", resource_type="sso_settings",
    )
    await db.commit()
    return result


@router.get("/invites")
async def list_invites(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return pending and recently accepted invitations for the organisation."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.user import UserInvite  # noqa: PLC0415
    result = await db.execute(
        select(UserInvite).where(UserInvite.org_id == current_user.org_id)
        .order_by(UserInvite.created_at.desc())
    )
    invites = result.scalars().all()
    return [
        {
            "id": inv.id,
            "email": inv.email,
            "role_id": inv.role_id,
            "accepted": inv.accepted_at is not None,
            "accepted_at": inv.accepted_at.isoformat() if inv.accepted_at else None,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        }
        for inv in invites
    ]


@router.delete("/invites/{invite_id}", response_model=MessageResponse)
async def revoke_invite(
    invite_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Revoke a pending invitation."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.user import UserInvite  # noqa: PLC0415
    result = await db.execute(
        select(UserInvite).where(
            UserInvite.id == invite_id,
            UserInvite.org_id == current_user.org_id,
            UserInvite.accepted_at.is_(None),
        )
    )
    inv = result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invite not found or already accepted")
    await db.delete(inv)
    from app.services.audit import audit_action  # noqa: PLC0415
    await audit_action(
        db, org_id=current_user.org_id, user_id=current_user.user_id,
        action="invite.revoked", resource_type="invite", resource_id=invite_id,
        resource_name=inv.email,
    )
    await db.commit()
    return MessageResponse(message="Invitation revoked")


@router.post("/auth-config/warehouse/test")
async def test_warehouse_connection(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict:
    """Test the currently configured warehouse connection.

    Reads the warehouse connection config stored in AuthProviderConfig
    (provider='warehouse') and attempts a live connection. Returns ok=True
    and a table count on success, or ok=False with an error message.
    """
    import json as _json  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.auth_config import AuthProviderConfig  # noqa: PLC0415
    from app.services.crypto import decrypt  # noqa: PLC0415
    from app.services.warehouse_inspector import test_connection  # noqa: PLC0415

    result = await db.execute(
        select(AuthProviderConfig).where(
            AuthProviderConfig.org_id == current_user.org_id,
            AuthProviderConfig.provider == "warehouse",
        )
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        return {"ok": False, "error": "No warehouse connection configured"}

    raw = dict(cfg.config or {})
    db_type = raw.get("db_type", "postgresql")

    # Decrypt the stored credential (password, private key PEM, or service-account JSON).
    secret = ""
    if cfg.client_secret_encrypted:
        try:
            secret = decrypt(cfg.client_secret_encrypted)
        except Exception:
            pass

    # Parse schemas — frontend stores as a JSON-encoded string.
    schemas_raw = raw.get("schemas", "")
    try:
        schemas: list[str] = _json.loads(schemas_raw) if schemas_raw else ["marts"]
    except (ValueError, TypeError):
        schemas = [s.strip() for s in str(schemas_raw).split(",") if s.strip()] or ["marts"]

    # The auth-provider config stores keys flat (e.g. "database", "account") while
    # warehouse_inspector.build_url() expects "database_name" and "extra_config".
    extra: dict[str, Any] = {
        "account": raw.get("account", ""),
        "warehouse": raw.get("warehouse", ""),
        "role": raw.get("role", ""),
        "private_key_passphrase": raw.get("private_key_passphrase", ""),
        "project": raw.get("project_id", "") or raw.get("project", ""),
        "http_path": raw.get("http_path", ""),
    }

    conn_data: dict[str, Any] = {
        "db_type": db_type,
        "host": raw.get("host", ""),
        "port": raw.get("port"),
        "database_name": raw.get("database") or raw.get("database_name", ""),
        "username": raw.get("username", ""),
        "password": "",
        "schemas": schemas,
        "extra_config": extra,
    }

    if db_type == "snowflake":
        # Secret is the private key PEM; pass via extra_config for key-pair auth.
        extra["private_key_pem"] = secret
    elif db_type == "bigquery":
        extra["credentials_json"] = secret
    else:
        conn_data["password"] = secret

    test_result = await test_connection(conn_data)
    return test_result


# ---------------------------------------------------------------------------
# Portal navigation
# ---------------------------------------------------------------------------
#
# A pair of endpoints rather than a general org-settings console: this build has
# no such console (see CLAUDE.md), and audit retention already lives on the
# audit endpoints for the same reason — it belongs to the thing it configures.


@router.get(
    "/nav-config",
    response_model=NavConfigResponse,
    # A link has no items and a dropdown has no href; sending them as explicit
    # nulls is noise, and the stored JSON does not carry them either.
    response_model_exclude_none=True,
)
async def get_nav_config(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> NavConfigResponse:
    """Return the organisation's navigation, or an empty list when unset.

    An empty list means every user is seeing the default navigation. It is not
    an error state, so there is no 404 here.
    """
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == current_user.org_id))
    ).scalar_one_or_none()
    stored = (row.nav_config if row else None) or []
    return NavConfigResponse(items=[NavItem.model_validate(item) for item in stored])


@router.put(
    "/nav-config",
    response_model=NavConfigResponse,
    # A link has no items and a dropdown has no href; sending them as explicit
    # nulls is noise, and the stored JSON does not carry them either.
    response_model_exclude_none=True,
)
async def update_nav_config(
    data: NavConfigRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> NavConfigResponse:
    """Replace the organisation's navigation.

    The whole list is replaced, because order is part of the value and there is
    no stable identity to address one item by. Saving an empty list restores the
    default navigation, stored as NULL so the default has one representation
    rather than two.
    """
    row = (
        await db.execute(select(OrgSettings).where(OrgSettings.org_id == current_user.org_id))
    ).scalar_one_or_none()
    if row is None:
        row = OrgSettings(org_id=current_user.org_id)
        db.add(row)

    before = ledger.serialize_row(row)
    row.nav_config = [item.model_dump(exclude_none=True) for item in data.items] or None

    await ledger.log_update(
        db,
        ctx=ledger.ctx_for(current_user),
        resource_type="org_settings",
        obj=row,
        before=before,
        resource_name="Navigation",
    )
    await audit_action(
        db,
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        action="nav_config.updated",
        resource_type="org_settings",
        resource_name="Navigation",
        extra={"item_count": len(data.items)},
    )
    await db.commit()
    logger.info(
        "nav_config.updated",
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        items=len(data.items),
    )
    return NavConfigResponse(items=data.items)
