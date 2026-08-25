"""Power BI embed token generation and workspace/report discovery."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_app_db
from app.middleware.auth import ROLE_HIERARCHY, CurrentUser, get_current_user, require_role
from app.models.dashboard import DashboardConfig, DashboardPermission
from app.models.user import UserRole
from app.schemas.dashboard import (
    PowerBIEmbedFilter,
    PowerBIEmbedToken,
    PowerBIReport,
    PowerBIWorkspace,
)
from app.services.embedders import powerbi as powerbi_svc
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

router = APIRouter()

_admin_dep = require_role("admin", "superadmin")


# ---------------------------------------------------------------------------
# Access control helper
# ---------------------------------------------------------------------------


async def _assert_dashboard_access(
    dashboard_id: int, current_user: CurrentUser, db: AsyncSession
) -> DashboardConfig:
    """Verify the user has access to the dashboard and return the config row.

    Args:
        dashboard_id: Primary key of the DashboardConfig row.
        current_user: The authenticated user requesting the embed token.
        db: Async SQLAlchemy session.

    Returns:
        The DashboardConfig row.

    Raises:
        HTTPException: With status 404 if the dashboard does not exist for the org,
            or 403 if the user has no permission grant.
    """
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == current_user.org_id,
            is_true(DashboardConfig.is_active),
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    # Admins and superadmins can access any active dashboard in their organisation.
    if ROLE_HIERARCHY.get(current_user.role, -1) >= ROLE_HIERARCHY.get("admin", 3):
        return dashboard

    # For other roles, require an explicit permission grant (user-level or role-level).
    role_result = await db.execute(
        select(UserRole.role_id).where(UserRole.user_id == current_user.user_id)
    )
    role_ids: list[int] = [row[0] for row in role_result.all()]

    perm_conditions: list[Any] = [DashboardPermission.user_id == current_user.user_id]
    if role_ids:
        perm_conditions.append(DashboardPermission.role_id.in_(role_ids))

    perm_result = await db.execute(
        select(DashboardPermission).where(
            DashboardPermission.dashboard_id == dashboard_id,
            or_(*perm_conditions),
        )
    )
    if perm_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to access this dashboard",
        )

    return dashboard


# ---------------------------------------------------------------------------
# Power BI endpoints
# ---------------------------------------------------------------------------


@router.post("/powerbi/test-connection")
async def test_powerbi_connection(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> dict[str, Any]:
    """Test the Power BI service principal configuration.

    Returns a result dict rather than raising so the admin UI can display a
    human-readable message without a 502 surfacing in the browser.
    """
    return await powerbi_svc.test_connection(current_user.org_id, db)


@router.get("/powerbi/workspaces", response_model=list[PowerBIWorkspace])
async def list_powerbi_workspaces(
    connection_id: int | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[PowerBIWorkspace]:
    """Return all Power BI workspaces visible to the service principal."""
    workspaces = await powerbi_svc.get_workspaces(
        current_user.org_id, db, connection_id=connection_id
    )
    return [PowerBIWorkspace(id=ws["id"], name=ws["name"]) for ws in workspaces]


@router.get(
    "/powerbi/workspaces/{workspace_id}/reports",
    response_model=list[PowerBIReport],
)
async def list_powerbi_reports(
    workspace_id: str,
    connection_id: int | None = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> list[PowerBIReport]:
    """Return all Power BI reports within a workspace."""
    reports = await powerbi_svc.get_reports(
        workspace_id, current_user.org_id, db, connection_id=connection_id
    )
    return [
        PowerBIReport(
            id=r["id"],
            name=r["name"],
            workspace_id=workspace_id,
            embed_url=r.get("embedUrl", ""),
        )
        for r in reports
    ]


@router.post(
    "/dashboards/{dashboard_id}/embed-token",
    response_model=PowerBIEmbedToken,
)
async def generate_powerbi_token(
    dashboard_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_app_db),
) -> PowerBIEmbedToken:
    """Generate a Power BI embed token for the specified dashboard.

    Verifies the user has a permission grant before calling the Power BI API.
    """
    await _assert_dashboard_access(dashboard_id, current_user, db)
    token_data = await powerbi_svc.generate_embed_token(
        dashboard_id,
        current_user.email,
        current_user.user_id,
        current_user.role,
        current_user.org_id,
        db,
    )
    return PowerBIEmbedToken(
        token=token_data["token"],
        token_id=token_data.get("token_id", ""),
        expiration=token_data.get("expiration", ""),
        embed_url=token_data.get("embed_url", ""),
        embed_filters=[
            PowerBIEmbedFilter(table=f["table"], column=f["column"], value=f["value"])
            for f in token_data.get("embed_filters", [])
        ],
    )
