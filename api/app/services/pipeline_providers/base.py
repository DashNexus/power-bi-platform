"""Base types for data pipeline orchestrator providers.

Each provider adapts one orchestration platform to a common interface: describe
its config fields, test connectivity, and list recent runs. This build ships
Azure Data Factory only; the shape is kept generic so a second orchestrator is a
new module plus one registry entry, exactly as in the full platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PipelineProviderError(Exception):
    """A provider call failed (bad credentials, unreachable host, etc.)."""


class PipelineNotImplementedError(NotImplementedError):
    """Raised by providers whose integration is planned but not yet built."""


@dataclass
class ProviderField:
    """One configuration input for a provider's connection form.

    secret fields are Fernet-encrypted into DataPipelineConnection.secret_encrypted;
    all other fields are stored as-is in the connection's config JSON.
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
    """Catalog metadata describing a provider for the admin UI."""

    key: str
    label: str
    implemented: bool
    fields: list[ProviderField] = field(default_factory=list)
    docs_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize provider metadata for the admin UI / API response."""
        return {
            "key": self.key,
            "label": self.label,
            "implemented": self.implemented,
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


class PipelineProvider:
    """Interface every pipeline orchestrator adapter implements.

    Run dicts are normalised to: {run_id, name, status, started_at, ended_at,
    duration_ms, message} so the frontend renders every provider identically.
    """

    meta: ProviderMeta

    async def test_connection(self, config: dict[str, Any], secret: str | None) -> dict[str, Any]:
        """Return {"ok": bool, ...} — never raise for expected auth failures."""
        raise NotImplementedError

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
        """Return a page of pipeline runs, newest first.

        Returns {"runs": [...], "next_cursor": str | None}. next_cursor is an
        opaque token to pass back as ``cursor`` for the next (older) page, or
        None when no more pages exist. ``days`` bounds the time window and
        ``pipeline_name`` filters to one pipeline when supported.
        """
        raise NotImplementedError

    async def list_pipelines(
        self, config: dict[str, Any], secret: str | None
    ) -> list[dict[str, Any]]:
        """Return the pipeline/flow definitions in this connection.

        Each dict has at least ``name``; providers may add ``description`` and
        ``activities_count``.
        """
        raise NotImplementedError
