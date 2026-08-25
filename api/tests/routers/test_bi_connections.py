"""Unit tests for BI connection CRUD, secret handling, and singleton enforcement."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.middleware.auth import CurrentUser


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _first_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.first.return_value = obj
    return result


def _scalars_result(items: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _conn(conn_id: int, provider: str = "powerbi", name: str = "C") -> MagicMock:
    c = MagicMock()
    c.id = conn_id
    c.org_id = 1
    c.name = f"{name}{conn_id}"
    c.provider = provider
    c.config = {}
    c.secret_encrypted = None
    c.is_active = True
    c.created_at = MagicMock()
    c.created_at.isoformat.return_value = "2025-01-01T00:00:00"
    c.updated_at = MagicMock()
    c.updated_at.isoformat.return_value = "2025-01-01T00:00:00"
    return c


class TestProviderCatalog:
    def test_registry_has_expected_providers(self) -> None:
        from app.services import bi_providers as providers

        metas = {m["key"]: m for m in providers.list_provider_meta()}
        # This build ships Power BI alone; a page embed carries no BI connection.
        assert list(metas) == ["powerbi"]
        assert metas["powerbi"]["implemented"] is True
        assert metas["powerbi"]["requires_auth"] is True


class TestListBiConnections:
    @pytest.mark.asyncio
    async def test_serialized_never_includes_secret(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.bi_connections import list_bi_connections

        c = _conn(1)
        c.secret_encrypted = "encrypted-blob"
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([c]))
        result = await list_bi_connections(current_user=mock_admin_user, db=mock_db_session)
        assert "secret" not in result[0]
        assert "secret_encrypted" not in result[0]
        assert result[0]["has_secret"] is True
        assert result[0]["provider_label"] == "Power BI"


class TestCreateBiConnection:
    @pytest.mark.asyncio
    async def test_rejects_unknown_provider(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.bi_connections import BiConnectionCreate, create_bi_connection

        with pytest.raises(HTTPException) as exc:
            await create_bi_connection(
                data=BiConnectionCreate(name="X", provider="not-a-provider"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert exc.value.status_code == 400

class TestTestConnection:
    @pytest.mark.asyncio
    async def test_delete_404_when_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.bi_connections import delete_bi_connection

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))
        with pytest.raises(HTTPException) as exc:
            await delete_bi_connection(
                connection_id=999, current_user=mock_admin_user, db=mock_db_session
            )
        assert exc.value.status_code == 404
