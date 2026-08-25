"""Base types for business-intelligence (embed) providers.

Each provider adapts one BI/embedding platform to a common interface: describe
its config fields and test connectivity. This build ships Power BI only; the
shape is kept generic so a second provider is a new module plus one registry
entry, exactly as in the full platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class BiProviderError(Exception):
    """A provider call failed (bad credentials, unreachable host, etc.)."""


@dataclass
class ProviderField:
    """One configuration input for a provider's connection form.

    secret fields are Fernet-encrypted into BiConnection.secret_encrypted; all
    other fields are stored as-is in the connection's config JSON.
    """

    key: str
    label: str
    type: str = "text"  # text | password | number
    required: bool = False
    secret: bool = False
    placeholder: str = ""
    help: str = ""


@dataclass
class ProviderMeta:
    """Catalog metadata describing a BI provider for the admin UI.

    singleton: only one connection of this provider is allowed per org.
    requires_auth: False for embed surfaces that carry no credentials.
    """

    key: str
    label: str
    implemented: bool
    singleton: bool = False
    requires_auth: bool = True
    fields: list[ProviderField] = field(default_factory=list)
    docs_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize provider metadata for the admin UI / API response."""
        return {
            "key": self.key,
            "label": self.label,
            "implemented": self.implemented,
            "singleton": self.singleton,
            "requires_auth": self.requires_auth,
            "docs_url": self.docs_url,
            "fields": [
                {
                    "key": f.key,
                    "label": f.label,
                    "type": f.type,
                    "required": f.required,
                    "secret": f.secret,
                    "placeholder": f.placeholder,
                    "help": f.help,
                }
                for f in self.fields
            ],
        }


class BiProvider:
    """Interface every BI/embed adapter implements."""

    meta: ProviderMeta

    async def test_connection(self, config: dict[str, Any], secret: str | None) -> dict[str, Any]:
        """Return {"ok": bool, ...} — never raise for expected auth failures."""
        raise NotImplementedError
