"""Power BI embed token generation via the Power BI REST API."""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_config import AuthProviderConfig
from app.models.dashboard import DashboardConfig
from app.services import crypto
from app.sql_compat import is_true

logger = structlog.get_logger(__name__)

_POWERBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
_AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


async def _get_aad_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Acquire an Azure AD access token via client_credentials grant.

    Args:
        tenant_id: Azure AD / Entra tenant GUID.
        client_id: Service principal application (client) ID.
        client_secret: Decrypted service principal client secret.

    Returns:
        Bearer access token string.

    Raises:
        HTTPException: With status 502 if the Azure AD token endpoint returns an error.
    """
    url = _AAD_TOKEN_URL.format(tenant_id=tenant_id)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": _POWERBI_SCOPE,
            },
        )

    if response.status_code != 200:
        error_detail = ""
        try:
            err = response.json()
            error_detail = err.get("error_description") or err.get("error") or ""
        except Exception:
            error_detail = response.text[:300]
        logger.error(
            "powerbi.aad_token_failed",
            tenant_id=tenant_id,
            status_code=response.status_code,
            error=error_detail,
        )
        detail = f"Azure AD token error: {error_detail}" if error_detail else "Failed to acquire Azure AD token for Power BI"
        raise HTTPException(status_code=502, detail=detail)

    return response.json()["access_token"]


async def _load_powerbi_config(
    org_id: int,
    db: AsyncSession,
    *,
    require_enabled: bool = True,
    connection_id: int | None = None,
) -> AuthProviderConfig:
    """Load the Power BI service principal config for the organisation.

    Args:
        org_id: Organisation primary key.
        db: Async SQLAlchemy session.
        require_enabled: When True (default) only returns a row with enabled=True.
            Pass False for admin operations (listing workspaces, test connection)
            where the config may exist but not yet be toggled on.
        connection_id: When set, source credentials from this BI connection
            instead of the org-global auth_provider_configs row.

    Returns:
        The AuthProviderConfig row (or a BI-connection-backed shim).

    Raises:
        HTTPException: With status 400 if no Power BI config exists for the org.
    """
    if connection_id is not None:
        from app.services.bi_credentials import load_connection_as_config  # noqa: PLC0415

        return await load_connection_as_config(
            db, org_id, connection_id, client_id_key="client_id"
        )
    conditions = [
        AuthProviderConfig.org_id == org_id,
        AuthProviderConfig.provider == "powerbi_sp",
    ]
    if require_enabled:
        conditions.append(is_true(AuthProviderConfig.enabled))

    result = await db.execute(select(AuthProviderConfig).where(*conditions))
    config = result.scalar_one_or_none()
    if config is None:
        detail = (
            "Power BI service principal is not enabled for this organisation"
            if require_enabled
            else "No Power BI service principal configuration found for this organisation"
        )
        raise HTTPException(status_code=400, detail=detail)
    return config


async def get_workspaces(
    org_id: int, db: AsyncSession, *, connection_id: int | None = None
) -> list[dict[str, Any]]:
    """Return all Power BI workspaces visible to the service principal.

    Args:
        org_id: Organisation primary key.
        db: Async SQLAlchemy session.
        connection_id: Optional BI connection to source credentials from.

    Returns:
        List of workspace dicts with 'id' and 'name' keys.

    Raises:
        HTTPException: With status 400 if no Power BI config found, or 502 on API error.
    """
    config = await _load_powerbi_config(
        org_id, db, require_enabled=False, connection_id=connection_id
    )
    tenant_id: str = (config.config or {}).get("tenant_id", "")
    client_id: str = config.client_id or ""
    client_secret = crypto.decrypt(config.client_secret_encrypted.decode())

    access_token = await _get_aad_token(tenant_id, client_id, client_secret)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_POWERBI_API_BASE}/groups",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        logger.error(
            "powerbi.list_workspaces_failed",
            org_id=org_id,
            status_code=response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to list Power BI workspaces",
        )

    workspaces = response.json().get("value", [])
    logger.info("powerbi.list_workspaces", org_id=org_id, count=len(workspaces))
    return [{"id": ws["id"], "name": ws["name"]} for ws in workspaces]


async def get_reports(
    workspace_id: str, org_id: int, db: AsyncSession, *, connection_id: int | None = None
) -> list[dict[str, Any]]:
    """Return all reports within a Power BI workspace.

    Args:
        workspace_id: Power BI workspace (group) GUID.
        org_id: Organisation primary key.
        db: Async SQLAlchemy session.
        connection_id: Optional BI connection to source credentials from.

    Returns:
        List of report dicts with 'id', 'name', 'embedUrl', and 'webUrl' keys.

    Raises:
        HTTPException: With status 400 if no Power BI config found, or 502 on API error.
    """
    config = await _load_powerbi_config(
        org_id, db, require_enabled=False, connection_id=connection_id
    )
    tenant_id: str = (config.config or {}).get("tenant_id", "")
    client_id: str = config.client_id or ""
    client_secret = crypto.decrypt(config.client_secret_encrypted.decode())

    access_token = await _get_aad_token(tenant_id, client_id, client_secret)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_POWERBI_API_BASE}/groups/{workspace_id}/reports",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        logger.error(
            "powerbi.list_reports_failed",
            org_id=org_id,
            workspace_id=workspace_id,
            status_code=response.status_code,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to list Power BI reports",
        )

    reports = response.json().get("value", [])
    logger.info(
        "powerbi.list_reports",
        org_id=org_id,
        workspace_id=workspace_id,
        count=len(reports),
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "embedUrl": r.get("embedUrl", ""),
            "webUrl": r.get("webUrl", ""),
        }
        for r in reports
    ]


async def test_connection(org_id: int, db: AsyncSession) -> dict[str, Any]:
    """Test the Power BI service principal configuration.

    Attempts to acquire an AAD token and list workspaces. Returns a result
    dict — never raises — so the admin UI can display a human-readable
    message without a 502.

    Args:
        org_id: Organisation primary key.
        db: Async SQLAlchemy session.

    Returns:
        Dict with 'ok' bool and 'workspace_count' on success, or 'error' string on failure.
    """
    try:
        config = await _load_powerbi_config(org_id, db, require_enabled=False)
    except HTTPException as exc:
        return {"ok": False, "error": exc.detail}

    tenant_id: str = (config.config or {}).get("tenant_id", "")
    client_id: str = config.client_id or ""

    if not config.client_secret_encrypted:
        return {"ok": False, "error": "No client secret stored — save a client secret first"}
    if not tenant_id:
        return {"ok": False, "error": "Tenant ID is required"}
    if not client_id:
        return {"ok": False, "error": "Client ID is required"}

    try:
        client_secret = crypto.decrypt(config.client_secret_encrypted.decode())
    except Exception as exc:
        return {"ok": False, "error": f"Failed to decrypt credentials: {exc}"}

    try:
        access_token = await _get_aad_token(tenant_id, client_id, client_secret)
    except HTTPException as exc:
        return {"ok": False, "error": exc.detail}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_POWERBI_API_BASE}/groups",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if response.status_code != 200:
        return {
            "ok": False,
            "error": f"Power BI API returned status {response.status_code}: {response.text[:200]}",
        }

    workspace_count = len(response.json().get("value", []))
    logger.info("powerbi.test_connection", org_id=org_id, workspace_count=workspace_count)
    return {"ok": True, "workspace_count": workspace_count}


async def generate_embed_token(
    dashboard_id: int,
    user_email: str,
    user_id: int,
    role: str,
    org_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    """Generate a Power BI embed token for a dashboard configuration.

    Loads the dashboard's workspace_id and report_id from its settings JSON,
    acquires an Azure AD access token via the service principal, then calls
    the Power BI GenerateToken API. Resolves any admin-configured embed_config
    filters against the current user's session attributes.

    Args:
        dashboard_id: Primary key of the DashboardConfig row.
        user_email: Email of the user requesting the embed token.
        user_id: User primary key — may be used for RLS filter resolution.
        role: User role string — may be used for RLS filter resolution.
        org_id: Organisation primary key.
        db: Async SQLAlchemy session.

    Returns:
        Dict with 'token', 'token_id', 'embed_url', 'expiration', and 'embed_filters' keys.

    Raises:
        HTTPException: With status 404 if the dashboard is not found, 400 if config
            is missing, or 502 if the Power BI API returns an error.
    """
    result = await db.execute(
        select(DashboardConfig).where(
            DashboardConfig.id == dashboard_id,
            DashboardConfig.org_id == org_id,
            is_true(DashboardConfig.is_active),
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    settings_json: dict[str, Any] = dashboard.settings or {}
    workspace_id: str = settings_json.get("workspace_id", "")
    report_id: str = settings_json.get("report_id", "")
    embed_url: str = settings_json.get("embed_url", "")
    embed_config: dict[str, Any] = settings_json.get("embed_config", {})

    if not workspace_id or not report_id:
        raise HTTPException(
            status_code=400,
            detail="Dashboard settings missing workspace_id or report_id",
        )

    config = await _load_powerbi_config(org_id, db, connection_id=dashboard.bi_connection_id)
    tenant_id: str = (config.config or {}).get("tenant_id", "")
    client_id: str = config.client_id or ""
    client_secret = crypto.decrypt(config.client_secret_encrypted.decode())

    access_token = await _get_aad_token(tenant_id, client_id, client_secret)

    token_url = (
        f"{_POWERBI_API_BASE}/groups/{workspace_id}/reports/{report_id}/GenerateToken"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            token_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"accessLevel": "View"},
        )

    if response.status_code != 200:
        error_detail = ""
        try:
            err = response.json()
            error_detail = err.get("error", {}).get("message") or str(err)[:300]
        except Exception:
            error_detail = response.text[:300]
        logger.error(
            "powerbi.generate_token_failed",
            dashboard_id=dashboard_id,
            user_email=user_email,
            status_code=response.status_code,
            error=error_detail,
        )
        if response.status_code == 403:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Power BI service principal does not have permission to generate an embed token. "
                    "In Power BI, open the workspace → Settings → Access and add the service "
                    "principal as a Member or Admin. The workspace must also be on Premium or Embedded "
                    f"capacity. Power BI error: {error_detail}"
                ),
            )
        detail = f"Power BI GenerateToken error: {error_detail}" if error_detail else "Failed to generate Power BI embed token"
        raise HTTPException(status_code=502, detail=detail)

    token_data = response.json()

    # If embed_url wasn't stored in dashboard settings, fetch it from the report metadata.
    # This handles dashboards created before embed_url was persisted by the creator form.
    if not embed_url:
        async with httpx.AsyncClient(timeout=30.0) as client:
            report_resp = await client.get(
                f"{_POWERBI_API_BASE}/groups/{workspace_id}/reports/{report_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if report_resp.status_code == 200:
            embed_url = report_resp.json().get("embedUrl", "")

    # Resolve admin-configured RLS filters against the current user's attributes
    user_attrs = {"email": user_email, "user_id": str(user_id), "role": role}
    embed_filters: list[dict[str, str]] = []
    for f in embed_config.get("filters", []):
        table = f.get("table", "").strip()
        column = f.get("column", "").strip()
        if not table or not column:
            continue
        if f.get("value_type") == "user_attribute":
            value = user_attrs.get(f.get("user_attribute", ""), "")
        else:
            value = f.get("static_value", "")
        embed_filters.append({"table": table, "column": column, "value": value})

    logger.info(
        "powerbi.token_generated",
        dashboard_id=dashboard_id,
        user_email=user_email,
    )
    return {
        "token": token_data["token"],
        "token_id": token_data.get("tokenId", ""),
        "embed_url": embed_url or token_data.get("embedUrl", ""),
        "expiration": token_data.get("expiration", ""),
        "embed_filters": embed_filters,
    }
