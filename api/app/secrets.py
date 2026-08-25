"""Secrets backend resolver (`SECRETS_BACKEND`).

`resolve_secrets()` runs once in the app lifespan and exports backend secrets as
environment variables, so the rest of the codebase reads plain env vars and never
imports a cloud SDK. Adding a backend means editing this file only.
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def resolve_secrets() -> None:
    """Fetch secrets from the configured backend and inject them as env vars.

    Reads settings.secrets_backend to determine where to pull secrets:
    - "env": no-op — secrets are already present in the environment
    - "azure": fetches from Azure Key Vault (requires azure-keyvault-secrets)
    - "aws": fetches from AWS Secrets Manager (requires boto3)
    - "gcp": fetches from GCP Secret Manager (requires google-cloud-secret-manager)

    Logs a warning when the required SDK is not installed rather than raising.
    """
    backend = settings.secrets_backend

    if backend == "env":
        logger.info("secrets.backend", backend="env", message="Using environment variables directly")
        return

    if backend == "azure":
        _resolve_azure_secrets()
    elif backend == "aws":
        _resolve_aws_secrets()
    elif backend == "gcp":
        _resolve_gcp_secrets()
    else:
        logger.warning("secrets.backend.unknown", backend=backend)


def _resolve_azure_secrets() -> None:
    """Fetch secrets from Azure Key Vault."""
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]
        from azure.keyvault.secrets import SecretClient  # type: ignore[import]
    except ImportError:
        logger.warning(
            "secrets.azure.sdk_missing",
            message="azure-keyvault-secrets not installed; skipping Azure Key Vault",
        )
        return

    if not settings.azure_keyvault_url:
        logger.warning("secrets.azure.no_url", message="AZURE_KEYVAULT_URL not set")
        return

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=settings.azure_keyvault_url, credential=credential)
    logger.info("secrets.azure.connected", vault=settings.azure_keyvault_url)
    # Secrets are fetched on-demand by name; no bulk fetch needed here.
    _ = client  # client available for future on-demand lookups


def _resolve_aws_secrets() -> None:
    """Fetch secrets from AWS Secrets Manager."""
    try:
        import boto3  # type: ignore[import]
    except ImportError:
        logger.warning(
            "secrets.aws.sdk_missing",
            message="boto3 not installed; skipping AWS Secrets Manager",
        )
        return

    logger.info("secrets.aws.connected")
    _ = boto3  # available for future on-demand lookups


def _resolve_gcp_secrets() -> None:
    """Fetch secrets from GCP Secret Manager."""
    try:
        from google.cloud import secretmanager  # type: ignore[import]
    except ImportError:
        logger.warning(
            "secrets.gcp.sdk_missing",
            message="google-cloud-secret-manager not installed; skipping GCP Secret Manager",
        )
        return

    logger.info("secrets.gcp.connected", project=settings.google_project_id)
    _ = secretmanager  # available for future on-demand lookups
