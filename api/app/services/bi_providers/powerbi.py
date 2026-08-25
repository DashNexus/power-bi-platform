"""Power BI embed provider.

Verifies an Azure AD service-principal connection by acquiring a token via the
client-credentials grant and listing workspaces — the same flow used by
app.services.embedders.powerbi, but from a self-contained connection config.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.services.bi_providers.base import BiProvider, ProviderField, ProviderMeta

_API_BASE = "https://api.powerbi.com/v1.0/myorg"
_AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


class PowerBiProvider(BiProvider):
    """Power BI service-principal embedding."""

    meta = ProviderMeta(
        key="powerbi",
        label="Power BI",
        implemented=True,
        docs_url="https://learn.microsoft.com/power-bi/developer/embedded",
        fields=[
            ProviderField(key="tenant_id", label="Azure tenant ID", required=True),
            ProviderField(key="client_id", label="Service principal client ID", required=True),
            ProviderField(
                key="secret",
                label="Service principal client secret",
                type="password",
                secret=True,
                required=True,
            ),
            ProviderField(
                key="workspace_id",
                label="Default workspace ID",
                help="Optional. A default Power BI workspace (group) GUID.",
            ),
        ],
    )

    async def test_connection(self, config: dict[str, Any], secret: str | None) -> dict[str, Any]:
        """Acquire an AAD token and list workspaces to verify the credentials."""
        tenant_id = config.get("tenant_id", "")
        client_id = config.get("client_id", "")
        if not tenant_id:
            return {"ok": False, "error": "Azure tenant ID is required."}
        if not client_id:
            return {"ok": False, "error": "Client ID is required."}
        if not secret:
            return {"ok": False, "error": "Client secret is required."}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                token_resp = await client.post(
                    _AAD_TOKEN_URL.format(tenant_id=tenant_id),
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": secret,
                        "scope": _SCOPE,
                    },
                )
            if token_resp.status_code != 200:
                try:
                    body = token_resp.json()
                    detail = body.get("error_description") or body.get("error") or token_resp.text
                except Exception:
                    detail = token_resp.text
                return {
                    "ok": False,
                    "error": f"Azure AD rejected the credentials: {str(detail)[:300]}",
                }
            token = token_resp.json()["access_token"]
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{_API_BASE}/groups",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code == 200:
                return {"ok": True, "workspace_count": len(resp.json().get("value", []))}
            return {
                "ok": False,
                "error": f"Power BI API returned HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"Could not reach Power BI: {exc}"}
