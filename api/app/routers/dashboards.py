"""Dashboard configuration management endpoints."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import ROLE_HIERARCHY, CurrentUser, get_current_user, require_role
from app.models.audit import AuditLog
from app.models.dashboard import (
    DashboardConfig,
    DashboardConfigVersion,
    DashboardFilter,
    DashboardPermission,
)
from app.models.user import UserRole
from app.schemas.common import MessageResponse
from app.schemas.dashboard import (
    DashboardCreateRequest,
    DashboardFilterSchema,
    DashboardPermissionRequest,
    DashboardResponse,
    DashboardUpdateRequest,
)
from app.services import change_ledger as ledger
from app.services import nav_config
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()

_admin_dep = require_role("admin", "superadmin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin_role(current_user: CurrentUser) -> None:
    """Gate dashboard change history and revert.

    Dashboard configuration is created and edited only by admins, so its ledger
    history and reverts follow the same rule. Viewers reach dashboards through
    ``DashboardPermission`` grants, which say nothing about editing the config.
    """
    if ROLE_HIERARCHY.get(current_user.role, -1) < ROLE_HIERARCHY["admin"]:
        raise HTTPException(
            status_code=403, detail="Dashboard changes are managed by administrators"
        )


async def _load_dashboard_with_filters(
    dashboard_id: int, org_id: int, db: AsyncSession
) -> DashboardResponse:
    """Load a dashboard row and its filters, scoped to the given organisation.

    Args:
        dashboard_id: Primary key of the DashboardConfig row.
        org_id: Organisation primary key — used to prevent cross-org access.
        db: Async SQLAlchemy session.

    Returns:
        DashboardResponse populated with filter data.

    Raises:
        HTTPException: With status 404 if the dashboard does not exist for the org.
    """
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == org_id,
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    filter_result = await db.execute(
        select(DashboardFilter)
        .where(DashboardFilter.dashboard_id == dashboard_id)
        .order_by(DashboardFilter.display_order)
    )
    filters = filter_result.scalars().all()

    _settings = dashboard.settings or {}
    return DashboardResponse(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        slug=dashboard.slug,
        embed_type=dashboard.embed_type,
        bi_connection_id=dashboard.bi_connection_id,
        embed_url=_settings.get("embed_url") or _settings.get("view_url") or "",
        settings=dashboard.settings,
        required_role=dashboard.required_role,
        is_active=dashboard.is_active,
        tags=dashboard.tags or [],
        filters=[
            DashboardFilterSchema(
                filter_key=f.filter_key,
                filter_label=f.filter_label,
                filter_type=f.filter_type,
                default_value=f.default_value,
                user_attribute=f.user_attribute,
                is_required=f.is_required,
                display_order=f.display_order,
            )
            for f in filters
        ],
    )


async def _user_has_dashboard_access(
    dashboard_id: int, current_user: CurrentUser, db: AsyncSession
) -> bool:
    """Return True if the user has access to the dashboard.

    Admins and superadmins always have access to all active dashboards in their
    org. Other users require an explicit DashboardPermission grant (direct user
    grant or via a role they hold).

    Args:
        dashboard_id: Primary key of the DashboardConfig row.
        current_user: The authenticated user requesting access.
        db: Async SQLAlchemy session.

    Returns:
        True if the user is authorised to view this dashboard.
    """
    if ROLE_HIERARCHY.get(current_user.role, -1) >= ROLE_HIERARCHY.get("admin", 3):
        return True

    role_result = await db.execute(
        select(UserRole.role_id).where(UserRole.user_id == current_user.user_id)
    )
    role_ids: list[int] = [row[0] for row in role_result.all()]

    conditions = [DashboardPermission.user_id == current_user.user_id]
    if role_ids:
        conditions.append(DashboardPermission.role_id.in_(role_ids))

    perm_result = await db.execute(
        select(DashboardPermission).where(
            DashboardPermission.dashboard_id == dashboard_id,
            or_(*conditions),
        )
    )
    return perm_result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Admin endpoints (require admin+)
# ---------------------------------------------------------------------------


@router.get("/admin/dashboards", response_model=list[DashboardResponse])
async def list_dashboards(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[DashboardResponse]:
    """Return all dashboard configurations for the current organisation."""
    result = await db.execute(
        select(DashboardConfig).where(DashboardConfig.org_id == current_user.org_id)
    )
    dashboards = result.scalars().all()

    responses: list[DashboardResponse] = []
    for dashboard in dashboards:
        filter_result = await db.execute(
            select(DashboardFilter)
            .where(DashboardFilter.dashboard_id == dashboard.id)
            .order_by(DashboardFilter.display_order)
        )
        filters = filter_result.scalars().all()
        responses.append(
            DashboardResponse(
                id=dashboard.id,
                name=dashboard.name,
                description=dashboard.description,
                slug=dashboard.slug,
                embed_type=dashboard.embed_type,
                settings=dashboard.settings,
                required_role=dashboard.required_role,
                is_active=dashboard.is_active,
                tags=dashboard.tags or [],
                filters=[
                    DashboardFilterSchema(
                        filter_key=f.filter_key,
                        filter_label=f.filter_label,
                        filter_type=f.filter_type,
                        default_value=f.default_value,
                        user_attribute=f.user_attribute,
                        is_required=f.is_required,
                        display_order=f.display_order,
                    )
                    for f in filters
                ],
            )
        )
    return responses


# Maps a BI connection's provider to the dashboard embed_type the frontend
# renders. A dashboard with no BI connection is a "page" embed — an ordinary URL
# in an iframe, with no credentials and no token flow.
_PROVIDER_EMBED_TYPE = {"powerbi": "powerbi"}


async def _embed_type_for_connection(db: AsyncSession, org_id: int, connection_id: int) -> str:
    """Derive a dashboard embed_type from the linked BI connection's provider."""
    from app.models.bi_connection import BiConnection  # noqa: PLC0415

    conn = (
        await db.execute(
            select(BiConnection).where(
                BiConnection.id == connection_id,
                BiConnection.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=400, detail="BI connection not found")
    return _PROVIDER_EMBED_TYPE.get(conn.provider, "page")


@router.post("/admin/dashboards", response_model=DashboardResponse, status_code=201)
async def create_dashboard(
    data: DashboardCreateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> DashboardResponse:
    """Create a new dashboard configuration with optional filters."""
    embed_type = data.embed_type
    if data.bi_connection_id is not None:
        embed_type = await _embed_type_for_connection(
            db, current_user.org_id, data.bi_connection_id
        )
    dashboard = DashboardConfig(
        org_id=current_user.org_id,
        name=data.name,
        description=data.description,
        slug=data.slug,
        embed_type=embed_type,
        bi_connection_id=data.bi_connection_id,
        settings=data.settings,
        required_role=data.required_role,
        is_active=True,
        tags=data.tags or None,
        created_by_user_id=current_user.user_id,
    )
    db.add(dashboard)
    await db.flush()  # populate dashboard.id before inserting filters

    for filter_schema in data.filters:
        db.add(
            DashboardFilter(
                dashboard_id=dashboard.id,
                filter_key=filter_schema.filter_key,
                filter_label=filter_schema.filter_label,
                filter_type=filter_schema.filter_type,
                default_value=filter_schema.default_value,
                user_attribute=filter_schema.user_attribute,
                is_required=filter_schema.is_required,
                display_order=filter_schema.display_order,
            )
        )

    db.add(AuditLog(
        org_id=current_user.org_id, user_id=current_user.user_id,
        action="dashboard.created", resource_type="dashboard",
        resource_id=dashboard.id, resource_name=data.name,
    ))
    # Filters are not logged individually: reverting this create deletes the
    # dashboard row and the FK cascade takes them with it.
    await ledger.log_create(
        db, ctx=ledger.ctx_for(current_user), resource_type="dashboard", obj=dashboard,
        resource_name=dashboard.name,
    )
    await db.commit()
    logger.info(
        "dashboard.created",
        dashboard_id=dashboard.id,
        slug=data.slug,
        org_id=current_user.org_id,
    )
    return await _load_dashboard_with_filters(dashboard.id, current_user.org_id, db)


@router.get("/admin/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def get_dashboard(
    dashboard_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> DashboardResponse:
    """Return a single dashboard configuration by ID."""
    return await _load_dashboard_with_filters(dashboard_id, current_user.org_id, db)


@router.put("/admin/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def update_dashboard(
    dashboard_id: int,
    data: DashboardUpdateRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> DashboardResponse:
    """Partially update a dashboard configuration.

    Only the fields present in the request body are updated.
    """
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    before = ledger.serialize_row(dashboard)

    # Save a version snapshot before mutating any fields.
    version = DashboardConfigVersion(
        dashboard_id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        embed_type=dashboard.embed_type,
        settings=dict(dashboard.settings or {}),
        required_role=dashboard.required_role,
        created_by_user_id=current_user.user_id,
    )
    db.add(version)

    if data.name is not None:
        dashboard.name = data.name
    if data.description is not None:
        dashboard.description = data.description
    if data.bi_connection_id is not None:
        dashboard.bi_connection_id = data.bi_connection_id
        dashboard.embed_type = await _embed_type_for_connection(
            db, current_user.org_id, data.bi_connection_id
        )
    elif data.embed_type is not None:
        dashboard.embed_type = data.embed_type
    if data.settings is not None:
        dashboard.settings = data.settings
    if data.required_role is not None:
        dashboard.required_role = data.required_role
    if data.is_active is not None:
        dashboard.is_active = data.is_active
    if data.tags is not None:
        dashboard.tags = data.tags or None

    db.add(AuditLog(
        org_id=current_user.org_id, user_id=current_user.user_id,
        action="dashboard.updated", resource_type="dashboard",
        resource_id=dashboard_id, resource_name=dashboard.name,
    ))
    await ledger.log_update(
        db, ctx=ledger.ctx_for(current_user), resource_type="dashboard", obj=dashboard,
        before=before, resource_name=dashboard.name,
    )
    await db.commit()
    logger.info(
        "dashboard.updated",
        dashboard_id=dashboard_id,
        org_id=current_user.org_id,
    )
    return await _load_dashboard_with_filters(dashboard_id, current_user.org_id, db)


@router.delete("/admin/dashboards/{dashboard_id}", response_model=MessageResponse)
async def delete_dashboard(
    dashboard_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Permanently delete a dashboard and its associated permissions and filters."""
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    db.add(AuditLog(
        org_id=current_user.org_id, user_id=current_user.user_id,
        action="dashboard.deleted", resource_type="dashboard",
        resource_id=dashboard_id, resource_name=dashboard.name,
    ))

    # The FK cascade takes filters and permissions with the dashboard, so they
    # have to be snapshotted here or a revert would restore a dashboard with no
    # filters that nobody it was shared with can see. One correlation id ties the
    # rows together; the parent is logged first so the group revert recreates it
    # before remapping the children's dashboard_id onto its new primary key.
    ctx = ledger.ctx_for(current_user)
    await ledger.log_delete(
        db, ctx=ctx, resource_type="dashboard", obj=dashboard, resource_name=dashboard.name,
    )
    filters = (
        await db.execute(
            select(DashboardFilter)
            .where(DashboardFilter.dashboard_id == dashboard_id)
            .order_by(DashboardFilter.display_order, DashboardFilter.id)
        )
    ).scalars().all()
    for dashboard_filter in filters:
        await ledger.log_delete(
            db, ctx=ctx, resource_type="dashboard_filter", obj=dashboard_filter,
            resource_name=dashboard_filter.filter_label,
        )
    grants = (
        await db.execute(
            select(DashboardPermission).where(DashboardPermission.dashboard_id == dashboard_id)
        )
    ).scalars().all()
    for grant in grants:
        await ledger.log_delete(
            db, ctx=ctx, resource_type="dashboard_permission", obj=grant,
            resource_name=f"{dashboard.name} share",
        )

    # A nav link to this dashboard would 404 for everyone once it is gone.
    # Pruned under the same correlation id, so reverting the delete restores the
    # link with the dashboard.
    pruned = await nav_config.prune_nav_links(
        db, current_user.org_id, nav_config.resource_hrefs("dashboard", dashboard_id), ctx=ctx
    )

    await db.delete(dashboard)
    await db.commit()
    logger.info(
        "dashboard.deleted",
        nav_links_pruned=len(pruned),
        dashboard_id=dashboard_id,
        org_id=current_user.org_id,
        filters_logged=len(filters),
        grants_logged=len(grants),
    )
    return MessageResponse(message="Dashboard deleted")


@router.get("/admin/dashboards/{dashboard_id}/permissions")
async def get_permissions(
    dashboard_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, list[int]]:
    """Return the current access grants for a dashboard."""
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    perm_result = await db.execute(
        select(DashboardPermission).where(DashboardPermission.dashboard_id == dashboard_id)
    )
    perms = perm_result.scalars().all()
    return {
        "user_ids": [p.user_id for p in perms if p.user_id is not None],
        "role_ids": [p.role_id for p in perms if p.role_id is not None],
    }


@router.put("/admin/dashboards/{dashboard_id}/permissions", response_model=MessageResponse)
async def set_permissions(
    dashboard_id: int,
    data: DashboardPermissionRequest,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> MessageResponse:
    """Replace the access control list for a dashboard.

    All existing permission rows for the dashboard are deleted and replaced with
    the supplied user_ids and role_ids. Pass empty lists to revoke all access.
    """
    # Verify the dashboard belongs to this org.
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    await db.execute(
        delete(DashboardPermission).where(
            DashboardPermission.dashboard_id == dashboard_id
        )
    )

    for user_id in data.user_ids:
        db.add(DashboardPermission(dashboard_id=dashboard_id, user_id=user_id))
    for role_id in data.role_ids:
        db.add(DashboardPermission(dashboard_id=dashboard_id, role_id=role_id))

    total = len(data.user_ids) + len(data.role_ids)
    db.add(AuditLog(
        org_id=current_user.org_id, user_id=current_user.user_id,
        action="dashboard.permissions_updated", resource_type="dashboard",
        resource_id=dashboard_id, extra={"grants": total},
    ))
    await db.commit()
    logger.info(
        "dashboard.permissions_set",
        dashboard_id=dashboard_id,
        grants=total,
        org_id=current_user.org_id,
    )
    return MessageResponse(message=f"Permissions updated ({total} grants)")


# ---------------------------------------------------------------------------
# User-facing endpoints (any authenticated user, filtered by permissions)
# ---------------------------------------------------------------------------


@router.get("/dashboards", response_model=list[DashboardResponse])
async def list_user_dashboards(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[DashboardResponse]:
    """Return active dashboards accessible to the current user.

    Admins and superadmins see all active dashboards in the organisation.
    Other users see only dashboards they have an explicit permission grant for
    (direct user grant or via a role they hold).
    """
    is_admin = ROLE_HIERARCHY.get(current_user.role, -1) >= ROLE_HIERARCHY.get("admin", 3)

    if is_admin:
        result = await db.execute(
            select(DashboardConfig).where(
                DashboardConfig.org_id == current_user.org_id,
                is_true(DashboardConfig.is_active),
            )
        )
    else:
        role_result = await db.execute(
            select(UserRole.role_id).where(UserRole.user_id == current_user.user_id)
        )
        role_ids: list[int] = [row[0] for row in role_result.all()]

        perm_conditions: list[Any] = [
            DashboardPermission.user_id == current_user.user_id,
        ]
        if role_ids:
            perm_conditions.append(DashboardPermission.role_id.in_(role_ids))

        perm_result = await db.execute(
            select(DashboardPermission.dashboard_id).where(or_(*perm_conditions))
        )
        permitted_ids: list[int] = [row[0] for row in perm_result.all()]

        if not permitted_ids:
            return []

        result = await db.execute(
            select(DashboardConfig).where(
                DashboardConfig.org_id == current_user.org_id,
                is_true(DashboardConfig.is_active),
                DashboardConfig.id.in_(permitted_ids),
            )
        )
    dashboards = result.scalars().all()

    responses: list[DashboardResponse] = []
    for dashboard in dashboards:
        filter_result = await db.execute(
            select(DashboardFilter)
            .where(DashboardFilter.dashboard_id == dashboard.id)
            .order_by(DashboardFilter.display_order)
        )
        filters = filter_result.scalars().all()
        responses.append(
            DashboardResponse(
                id=dashboard.id,
                name=dashboard.name,
                description=dashboard.description,
                slug=dashboard.slug,
                embed_type=dashboard.embed_type,
                settings=dashboard.settings,
                required_role=dashboard.required_role,
                is_active=dashboard.is_active,
                tags=dashboard.tags or [],
                filters=[
                    DashboardFilterSchema(
                        filter_key=f.filter_key,
                        filter_label=f.filter_label,
                        filter_type=f.filter_type,
                        default_value=f.default_value,
                        user_attribute=f.user_attribute,
                        is_required=f.is_required,
                        display_order=f.display_order,
                    )
                    for f in filters
                ],
            )
        )
    return responses


@router.get("/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def get_user_dashboard(
    dashboard_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> DashboardResponse:
    """Return a single active dashboard if the current user has access."""
    # Check that the dashboard exists, is active, and belongs to the user's org.
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
            is_true(DashboardConfig.is_active),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    if not await _user_has_dashboard_access(dashboard_id, current_user, db):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this dashboard",
        )

    response = await _load_dashboard_with_filters(dashboard_id, current_user.org_id, db)
    audit = AuditLog(
        org_id=current_user.org_id,
        user_id=current_user.user_id,
        action="dashboard.view",
        resource_type="dashboard",
        resource_id=dashboard_id,
        resource_name=response.name,
    )
    db.add(audit)
    await db.commit()
    return response


# ---------------------------------------------------------------------------
# Dashboard version history
# ---------------------------------------------------------------------------


@router.get("/admin/dashboards/{dashboard_id}/versions")
async def list_dashboard_versions(
    dashboard_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict]:
    """Return the version history for a dashboard in reverse chronological order."""
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    ver_result = await db.execute(
        select(DashboardConfigVersion)
        .where(DashboardConfigVersion.dashboard_id == dashboard_id)
        .order_by(DashboardConfigVersion.created_at.desc())
    )
    versions = ver_result.scalars().all()
    return [
        {
            "id": v.id,
            "dashboard_id": v.dashboard_id,
            "name": v.name,
            "description": v.description,
            "embed_type": v.embed_type,
            "settings": v.settings,
            "required_role": v.required_role,
            "created_by_user_id": v.created_by_user_id,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]


@router.post("/admin/dashboards/{dashboard_id}/versions/{version_id}/restore",
             response_model=DashboardResponse)
async def restore_dashboard_version(
    dashboard_id: int,
    version_id: int,
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> DashboardResponse:
    """Restore a dashboard to a previous version snapshot."""
    dash_result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
        )
    )
    dashboard = dash_result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    ver_result = await db.execute(
        select(DashboardConfigVersion).where(
            DashboardConfigVersion.id == version_id,
            DashboardConfigVersion.dashboard_id == dashboard_id,
        )
    )
    version = ver_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    before = ledger.serialize_row(dashboard)

    # Save current state as a new version before restoring.
    db.add(DashboardConfigVersion(
        dashboard_id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        embed_type=dashboard.embed_type,
        settings=dict(dashboard.settings or {}),
        required_role=dashboard.required_role,
        created_by_user_id=current_user.user_id,
    ))

    dashboard.name = version.name
    dashboard.description = version.description
    dashboard.embed_type = version.embed_type
    dashboard.settings = version.settings
    dashboard.required_role = version.required_role

    db.add(AuditLog(
        org_id=current_user.org_id, user_id=current_user.user_id,
        action="dashboard.version_restored", resource_type="dashboard",
        resource_id=dashboard_id, extra={"restored_from_version_id": version_id},
    ))
    # A version restore is an edit like any other, so it belongs in the ledger —
    # otherwise /changes shows a gap where the dashboard silently changed.
    await ledger.log_update(
        db, ctx=ledger.ctx_for(current_user), resource_type="dashboard", obj=dashboard,
        before=before, resource_name=dashboard.name,
    )
    await db.commit()
    logger.info(
        "dashboard.version_restored",
        dashboard_id=dashboard_id,
        version_id=version_id,
        org_id=current_user.org_id,
    )
    return await _load_dashboard_with_filters(dashboard_id, current_user.org_id, db)
