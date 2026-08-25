"""Public portal settings and feature flags — accessible to all authenticated users."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user

router = APIRouter()

# Portal features gated by role permissions. A feature is visible to a user only
# when the org flag is enabled AND the user's roles grant one of the mapped
# permissions. Features not listed here are controlled by the org flag alone.
# Admins/superadmins bypass the gate.
_FEATURE_PERMISSIONS: dict[str, list[str]] = {
    "dashboards": ["dashboards.view", "dashboards.manage"],
    "custom_pages": ["pages.view", "pages.manage"],
    "governance": ["data_dictionary.view", "data_dictionary.manage"],
    "pipelines": ["pipelines.view", "pipelines.manage"],
    "exports": ["exports.view", "exports.create"],
}


async def _grant_unlocked_features(
    current_user: CurrentUser, db: AsyncSession
) -> set[str]:
    """Return features unlocked by a per-resource share to the user.

    A role granted one dashboard unlocks 'dashboards'; one data dictionary
    unlocks 'governance' — so shared resources stay visible and openable even
    without the broad view permission.

    These are independent existence checks, and this call sits in the shell on
    **every page load**, so they go out as a single UNION ALL rather than one
    ``SELECT ... LIMIT 1`` per resource type.
    """
    from sqlalchemy import literal, or_, select, union_all  # noqa: PLC0415

    from app.models.dashboard import DashboardConfig, DashboardPermission  # noqa: PLC0415
    from app.models.data_dict import DataDictionaryPermission  # noqa: PLC0415
    from app.models.data_pipeline import DataPipelineConnectionPermission  # noqa: PLC0415
    from app.models.page import CustomPage, CustomPagePermission  # noqa: PLC0415
    from app.services.permissions import get_user_role_ids  # noqa: PLC0415

    role_ids = await get_user_role_ids(db, current_user)
    org_id = current_user.org_id

    def _match(user_col: Any, role_col: Any) -> Any:  # noqa: ANN401
        conds = [user_col == current_user.user_id]
        if role_ids:
            conds.append(role_col.in_(role_ids))
        return or_(*conds)

    # SQLAlchemy models and columns carry no useful static type here, matching
    # `_match` above.
    def _probe(
        feature: str,
        grant: Any,  # noqa: ANN401
        *,
        org_column: Any,  # noqa: ANN401
        joins: Any = None,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """One "does any grant of this kind exist?" branch of the union."""
        stmt = select(literal(feature).label("feature"))
        if joins is not None:
            stmt = stmt.select_from(grant).join(joins[0], joins[1])
        else:
            stmt = stmt.select_from(grant)
        return stmt.where(org_column == org_id, _match(grant.user_id, grant.role_id)).limit(1)

    # Grant tables that carry their own org_id need no join; the rest are scoped
    # through their parent, which is what keeps the check tenant-safe.
    branches = [
        _probe(
            "dashboards",
            DashboardPermission,
            org_column=DashboardConfig.org_id,
            joins=(DashboardConfig, DashboardConfig.id == DashboardPermission.dashboard_id),
        ),
        _probe(
            "custom_pages",
            CustomPagePermission,
            org_column=CustomPage.org_id,
            joins=(CustomPage, CustomPage.id == CustomPagePermission.page_id),
        ),
        _probe(
            "governance",
            DataDictionaryPermission,
            org_column=DataDictionaryPermission.org_id,
        ),
        _probe(
            "pipelines",
            DataPipelineConnectionPermission,
            org_column=DataPipelineConnectionPermission.org_id,
        ),
    ]

    result = await db.execute(union_all(*branches))
    return {row[0] for row in result.all()}


@router.get("/portal/features")
async def get_portal_features(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict[str, Any]]:
    """Return effective feature flags for the current user's portal navigation.

    Accessible to any authenticated user. A feature is enabled when the org flag
    (or env override) is on AND the user's role permissions grant it (see
    _FEATURE_PERMISSIONS) — OR when a specific resource of that type has been
    shared with the user's roles, so a role granted a single dashboard or data
    dictionary can still see and open it. Admins/superadmins are not gated.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.config import FEATURE_ENV_VARS, settings  # noqa: PLC0415
    from app.models.feature_flag import FeatureFlag  # noqa: PLC0415
    from app.services.permissions import get_user_permission_keys  # noqa: PLC0415

    result = await db.execute(
        select(FeatureFlag).where(FeatureFlag.org_id == current_user.org_id)
    )
    db_flags = {f.feature_key: f for f in result.scalars().all()}
    env_overrides = settings.feature_overrides

    is_admin = current_user.role in ("admin", "superadmin")
    user_perms = set() if is_admin else await get_user_permission_keys(db, current_user)

    # Features unlocked by a per-resource grant (not just the broad permission).
    grant_unlocked = set() if is_admin else await _grant_unlocked_features(current_user, db)

    def _effective(key: str, org_enabled: bool) -> bool:
        if not org_enabled:
            return False
        required = _FEATURE_PERMISSIONS.get(key)
        if is_admin or required is None:
            return org_enabled
        if any(p in user_perms for p in required):
            return True
        return key in grant_unlocked

    all_keys = sorted(set(FEATURE_ENV_VARS) | set(db_flags))
    result_flags: list[dict[str, Any]] = []
    for key in all_keys:
        org_enabled = env_overrides.get(
            key, db_flags[key].enabled if key in db_flags else False
        )
        result_flags.append(
            {
                "feature_key": key,
                "enabled": _effective(key, org_enabled),
                "env_override": key in env_overrides,
            }
        )
    return result_flags


@router.get("/portal/settings")
async def get_portal_settings(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Return public org branding and navigation for the portal shell.

    Returns only non-sensitive fields, so any authenticated user may call it —
    which the navigation needs, since it is rendered for everyone. The items are
    returned as stored; whether a given link is *shown* is decided per user by
    `lib/navAccess.ts`, against the same feature flags and grants the routes
    themselves enforce. A null nav_config means the default navigation.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.org_settings import OrgSettings  # noqa: PLC0415

    result = await db.execute(
        select(OrgSettings).where(OrgSettings.org_id == current_user.org_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {"app_name": "Power BI Platform", "logo_url": None, "nav_config": None}
    return {
        "app_name": row.app_name,
        "logo_url": row.logo_url,
        "nav_config": row.nav_config,
    }
