"""Registry of data pipeline orchestrator providers.

This build ships **Azure Data Factory** only. Look up a provider instance by key
with get_provider(), or read the whole catalog for the admin UI with
list_provider_meta() — the connection form renders itself from that metadata, so
adding a provider needs no frontend change.
"""

from __future__ import annotations

from typing import Any

from app.services.pipeline_providers.adf import AzureDataFactoryProvider
from app.services.pipeline_providers.base import (
    PipelineNotImplementedError,
    PipelineProvider,
    PipelineProviderError,
    ProviderMeta,
)

_PROVIDER_CLASSES: list[type[PipelineProvider]] = [AzureDataFactoryProvider]

_REGISTRY: dict[str, PipelineProvider] = {cls.meta.key: cls() for cls in _PROVIDER_CLASSES}


def get_provider(key: str) -> PipelineProvider | None:
    """Return the provider instance for a key, or None if unknown."""
    return _REGISTRY.get(key)


def provider_meta(key: str) -> ProviderMeta | None:
    """Return a provider's catalog metadata, or None if unknown."""
    prov = _REGISTRY.get(key)
    return prov.meta if prov else None


def list_provider_meta() -> list[dict[str, Any]]:
    """Return catalog metadata for every registered provider."""
    return [prov.meta.to_dict() for prov in _REGISTRY.values()]


def is_valid_provider(key: str) -> bool:
    """Return True if the key names a registered provider."""
    return key in _REGISTRY


__all__ = [
    "PipelineNotImplementedError",
    "PipelineProvider",
    "PipelineProviderError",
    "get_provider",
    "is_valid_provider",
    "list_provider_meta",
    "provider_meta",
]
