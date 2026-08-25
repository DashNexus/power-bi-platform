"""Registry of business-intelligence (embed) providers.

This build ships **Power BI** only. Dashboards that embed an ordinary URL (a
"page embed") carry no BI connection at all, so they need no provider here.

Look up a provider by key with get_provider(), or read the whole catalog with
list_provider_meta() — the admin connection form renders itself from that
metadata, so adding a provider needs no frontend change.
"""

from __future__ import annotations

from typing import Any

from app.services.bi_providers.base import BiProvider, BiProviderError, ProviderMeta
from app.services.bi_providers.powerbi import PowerBiProvider

_PROVIDER_CLASSES: list[type[BiProvider]] = [PowerBiProvider]

_REGISTRY: dict[str, BiProvider] = {cls.meta.key: cls() for cls in _PROVIDER_CLASSES}


def get_provider(key: str) -> BiProvider | None:
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
    "BiProvider",
    "BiProviderError",
    "get_provider",
    "is_valid_provider",
    "list_provider_meta",
    "provider_meta",
]
