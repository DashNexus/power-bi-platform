"""Azure Data Factory orchestrator provider.

Acquires an Azure AD token via the client-credentials grant and calls the ADF
Management REST API directly over httpx (no Azure SDK import). Works from a
self-contained connection config rather than the legacy global auth config.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.services.pipeline_providers.base import (
    PipelineProvider,
    PipelineProviderError,
    ProviderField,
    ProviderMeta,
)

_API_VERSION = "2018-06-01"
_MANAGEMENT_BASE = "https://management.azure.com"
_AAD_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/token"


class AzureDataFactoryProvider(PipelineProvider):
    """List pipeline runs from an Azure Data Factory instance."""

    meta = ProviderMeta(
        key="adf",
        label="Azure Data Factory",
        implemented=True,
        docs_url="https://learn.microsoft.com/azure/data-factory",
        fields=[
            ProviderField(key="tenant_id", label="Tenant ID", required=True),
            ProviderField(key="subscription_id", label="Subscription ID", required=True),
            ProviderField(key="resource_group", label="Resource group", required=True),
            ProviderField(key="factory_name", label="Data Factory name", required=True),
            ProviderField(key="client_id", label="Service principal client ID", required=True),
            ProviderField(
                key="secret",
                label="Service principal client secret",
                type="password",
                secret=True,
                required=True,
            ),
        ],
    )

    async def _token(self, config: dict[str, Any], secret: str | None) -> str:
        token_url = _AAD_TOKEN_URL.format(tenant_id=config.get("tenant_id", ""))
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": config.get("client_id", ""),
                        "client_secret": secret or "",
                        "resource": f"{_MANAGEMENT_BASE}/",
                    },
                )
        except httpx.HTTPError as exc:
            raise PipelineProviderError(f"Failed to reach Azure AD: {exc}") from exc
        if resp.status_code != 200:
            try:
                body = resp.json()
                detail = body.get("error_description") or body.get("error") or resp.text
            except Exception:
                detail = resp.text
            raise PipelineProviderError(f"Azure AD rejected the credentials: {str(detail)[:300]}")
        return str(resp.json()["access_token"])

    def _factory_url(self, config: dict[str, Any]) -> str:
        return (
            f"{_MANAGEMENT_BASE}"
            f"/subscriptions/{config.get('subscription_id', '')}"
            f"/resourceGroups/{config.get('resource_group', '')}"
            f"/providers/Microsoft.DataFactory"
            f"/factories/{config.get('factory_name', '')}"
        )

    async def test_connection(self, config: dict[str, Any], secret: str | None) -> dict[str, Any]:
        """Acquire a token and list pipelines to verify the credentials."""
        try:
            token = await self._token(config, secret)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self._factory_url(config)}/pipelines",
                    params={"api-version": _API_VERSION},
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code == 200:
                return {"ok": True, "pipeline_count": len(resp.json().get("value", []))}
            return {
                "ok": False,
                "error": f"ADF returned HTTP {resp.status_code}: {resp.text[:300]}",
            }
        except PipelineProviderError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 — surface any unexpected error to the admin
            return {"ok": False, "error": str(exc)}

    async def list_runs(
        self,
        config: dict[str, Any],
        secret: str | None,
        *,
        limit: int = 50,
        days: int = 7,
        pipeline_name: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return one page of pipeline runs within the last ``days``, newest first.

        ADF caps a page at 100 and returns a continuationToken when more exist;
        that token is surfaced as ``next_cursor`` and passed back as ``cursor``
        to load older runs.
        """
        token = await self._token(config, secret)
        now = datetime.now(UTC)
        body: dict[str, Any] = {
            "lastUpdatedAfter": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lastUpdatedBefore": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "orderBy": [{"orderBy": "RunStart", "order": "DESC"}],
        }
        if pipeline_name:
            body["filters"] = [
                {"operand": "PipelineName", "operator": "Equals", "values": [pipeline_name]}
            ]
        if cursor:
            body["continuationToken"] = cursor
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self._factory_url(config)}/queryPipelineRuns",
                    params={"api-version": _API_VERSION},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise PipelineProviderError(f"Could not reach Azure Data Factory: {exc}") from exc
        if resp.status_code != 200:
            raise PipelineProviderError(f"ADF returned HTTP {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        runs: list[dict[str, Any]] = []
        for r in payload.get("value", [])[:limit]:
            invoked = r.get("invokedBy") or {}
            invoked_type = invoked.get("invokedByType")
            # When one pipeline triggers another via an Execute Pipeline activity,
            # ADF sets invokedByType to "PipelineActivity" and pipelineRunId to the
            # parent run's id — used to nest child runs under their parent.
            parent_run_id = (
                invoked.get("pipelineRunId") if invoked_type == "PipelineActivity" else None
            )
            runs.append(
                {
                    "run_id": r.get("runId"),
                    "name": r.get("pipelineName"),
                    "status": r.get("status") or "Unknown",
                    "started_at": r.get("runStart"),
                    "ended_at": r.get("runEnd"),
                    "duration_ms": r.get("durationInMs"),
                    "message": r.get("message"),
                    "invoked_by": invoked.get("name"),
                    "invoked_by_type": invoked_type,
                    "parent_run_id": parent_run_id,
                }
            )
        return {"runs": runs, "next_cursor": payload.get("continuationToken") or None}

    async def list_pipelines(
        self, config: dict[str, Any], secret: str | None
    ) -> list[dict[str, Any]]:
        """Return the pipeline definitions in the configured factory."""
        token = await self._token(config, secret)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self._factory_url(config)}/pipelines",
                    params={"api-version": _API_VERSION},
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError as exc:
            raise PipelineProviderError(f"Could not reach Azure Data Factory: {exc}") from exc
        if resp.status_code != 200:
            raise PipelineProviderError(f"ADF returned HTTP {resp.status_code}: {resp.text[:300]}")
        return [
            {
                "name": p.get("name"),
                "description": (p.get("properties") or {}).get("description"),
                "activities_count": len((p.get("properties") or {}).get("activities", [])),
            }
            for p in resp.json().get("value", [])
        ]
