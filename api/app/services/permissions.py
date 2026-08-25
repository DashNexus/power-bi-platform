"""Permission resolution for role-and-grant-based authorization.

Access decisions are driven by the permissions attached to a user's roles
(role_permissions) rather than the legacy ROLE_HIERARCHY level check. Resource
sharing (dashboards, pages, data dictionaries, warehouse and pipeline
connections) layers per-resource role grants on top of these permission keys.

Both resolvers take the **principal**, not a user id, so a call site can never
resolve one person's access under another's identity by accident.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import CurrentUser, get_current_user
from app.models.user import Permission, RolePermission, UserRole


async def get_user_permission_keys(db: AsyncSession, principal: CurrentUser) -> set[str]:
    """Return the permission keys the principal holds, via their roles."""
    result = await db.execute(
        select(Permission.key)
        .select_from(UserRole)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == principal.user_id)
    )
    return {row[0] for row in result.all()}


async def get_user_role_ids(db: AsyncSession, principal: CurrentUser) -> list[int]:
    """Return the ids of every role assigned to the principal.

    Used by per-resource share checks (dashboards, pages, data dictionaries,
    warehouse and pipeline connections) which match grants against roles. Kept
    here so every access path shares one query rather than reimplementing it —
    divergence here is a security risk.
    """
    result = await db.execute(
        select(UserRole.role_id).where(UserRole.user_id == principal.user_id)
    )
    return [row[0] for row in result.all()]


async def user_has_permission(db: AsyncSession, principal: CurrentUser, *keys: str) -> bool:
    """Return True when the principal holds at least one of the given keys."""
    if not keys:
        return False
    granted = await get_user_permission_keys(db, principal)
    return any(key in granted for key in keys)


def require_permission(*keys: str):  # noqa: ANN201
    """Return a FastAPI dependency that requires one of the given permission keys.

    Args:
        *keys: Permission keys; the user must hold at least one to pass.

    Returns:
        An async FastAPI dependency yielding the authenticated CurrentUser.
    """

    async def _dependency(
        current_user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_app_db),
    ) -> CurrentUser:
        if not await user_has_permission(db, current_user, *keys):
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return _dependency


def require_permission_or_admin(*keys: str):  # noqa: ANN201
    """Dependency passing for admins, or any principal holding one of ``keys``.

    **Admin bypass is by role**, so an org whose admin role was edited (or a
    freshly seeded org) can never lock itself out of its own console.

    Args:
        *keys: Permission keys; holding any one is enough.
    """
    from app.middleware.auth import ROLE_HIERARCHY  # noqa: PLC0415

    admin_level = ROLE_HIERARCHY["admin"]

    async def _dependency(
        current_user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_app_db),
    ) -> CurrentUser:
        if ROLE_HIERARCHY.get(current_user.role, -1) >= admin_level:
            return current_user
        if await user_has_permission(db, current_user, *keys):
            return current_user
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this resource",
        )

    return _dependency


async def user_can_query_connection(
    db: AsyncSession, principal: CurrentUser, connection_id: int
) -> bool:
    """Return True if the principal may run queries against a warehouse connection.

    Query access is granted per connection to a role, and is separate from
    data-dictionary access — being able to read a table's description does not
    imply being able to read its rows. A connection with no grant rows is
    reachable by admins only, which is the model's documented default.
    """
    from app.middleware.auth import ROLE_HIERARCHY  # noqa: PLC0415
    from app.models.warehouse import WarehouseConnectionPermission  # noqa: PLC0415

    if ROLE_HIERARCHY.get(principal.role, -1) >= ROLE_HIERARCHY["admin"]:
        return True

    role_ids = await get_user_role_ids(db, principal)
    if not role_ids:
        return False

    result = await db.execute(
        select(WarehouseConnectionPermission.id).where(
            WarehouseConnectionPermission.org_id == principal.org_id,
            WarehouseConnectionPermission.warehouse_connection_id == connection_id,
            WarehouseConnectionPermission.role_id.in_(role_ids),
        )
    )
    return result.first() is not None
