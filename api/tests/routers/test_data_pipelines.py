"""Unit tests for data pipeline connection access control and sharing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser


def _viewer(user_id: int = 2, org_id: int = 1) -> CurrentUser:
    return CurrentUser(user_id=user_id, org_id=org_id, role="viewer", email="v@example.com")


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _all_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


def _scalars_result(items: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _conn(conn_id: int, provider: str = "prefect", name: str = "P") -> MagicMock:
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


class TestAccessibleIds:
    @pytest.mark.asyncio
    async def test_admin_gets_none(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_pipelines import _accessible_ids

        assert await _accessible_ids(mock_admin_user, mock_db_session) is None

    @pytest.mark.asyncio
    async def test_viewer_gets_granted_ids(self, mock_db_session: AsyncMock) -> None:
        from app.routers.data_pipelines import _accessible_ids

        mock_db_session.execute = AsyncMock(return_value=_all_result([(2,), (5,)]))
        with patch(
            "app.routers.data_pipelines.get_user_role_ids", new=AsyncMock(return_value=[7])
        ):
            result = await _accessible_ids(_viewer(), mock_db_session)
        assert result == {2, 5}


class TestListPipelines:
    @pytest.mark.asyncio
    async def test_admin_sees_all(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_pipelines import list_pipelines

        mock_db_session.execute = AsyncMock(return_value=_scalars_result([_conn(1), _conn(2)]))
        with patch(
            "app.routers.data_pipelines._accessible_ids", new=AsyncMock(return_value=None)
        ):
            result = await list_pipelines(current_user=mock_admin_user, db=mock_db_session)
        assert [c["id"] for c in result] == [1, 2]

    @pytest.mark.asyncio
    async def test_viewer_sees_only_granted(self, mock_db_session: AsyncMock) -> None:
        from app.routers.data_pipelines import list_pipelines

        mock_db_session.execute = AsyncMock(
            return_value=_scalars_result([_conn(1), _conn(2), _conn(3)])
        )
        with patch(
            "app.routers.data_pipelines._accessible_ids", new=AsyncMock(return_value={2})
        ):
            result = await list_pipelines(current_user=_viewer(), db=mock_db_session)
        assert [c["id"] for c in result] == [2]

    @pytest.mark.asyncio
    async def test_serialized_never_includes_secret(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_pipelines import list_pipelines

        c = _conn(1)
        c.secret_encrypted = "encrypted-blob"
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([c]))
        with patch(
            "app.routers.data_pipelines._accessible_ids", new=AsyncMock(return_value=None)
        ):
            result = await list_pipelines(current_user=mock_admin_user, db=mock_db_session)
        assert "secret" not in result[0]
        assert "secret_encrypted" not in result[0]
        assert result[0]["has_secret"] is True


class TestCreatePipeline:
    @pytest.mark.asyncio
    async def test_rejects_unknown_provider(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.data_pipelines import PipelineConnectionCreate, create_pipeline

        with pytest.raises(HTTPException) as exc:
            await create_pipeline(
                data=PipelineConnectionCreate(name="X", provider="not-a-provider"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert exc.value.status_code == 400


class TestRuns:
    @pytest.mark.asyncio
    async def test_runs_surfaces_next_cursor(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """The runs endpoint passes through the provider's pagination cursor."""
        from app.routers.data_pipelines import list_pipeline_runs

        conn = _conn(1, provider="prefect")
        fake = MagicMock()
        fake.meta.implemented = True
        fake.list_runs = AsyncMock(return_value={"runs": [{"run_id": "a"}], "next_cursor": "50"})
        with patch(
            "app.routers.data_pipelines._require_view", new=AsyncMock(return_value=conn)
        ), patch("app.routers.data_pipelines.providers.get_provider", return_value=fake):
            result = await list_pipeline_runs(
                connection_id=1, days=14, current_user=mock_admin_user, db=mock_db_session
            )
        assert result["next_cursor"] == "50"
        assert result["runs"] == [{"run_id": "a"}]
        assert fake.list_runs.call_args.kwargs["days"] == 14


class TestPipelineDefinitions:
    @pytest.mark.asyncio
    async def test_returns_pipeline_defs(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_pipelines import list_pipeline_definitions

        conn = _conn(1, provider="adf")
        fake = MagicMock()
        fake.meta.implemented = True
        fake.list_pipelines = AsyncMock(return_value=[{"name": "ETL", "activities_count": 3}])
        with patch(
            "app.routers.data_pipelines._require_view", new=AsyncMock(return_value=conn)
        ), patch("app.routers.data_pipelines.providers.get_provider", return_value=fake):
            result = await list_pipeline_definitions(
                connection_id=1, current_user=mock_admin_user, db=mock_db_session
            )
        assert result["pipelines"] == [{"name": "ETL", "activities_count": 3}]


class TestPermissions:
    @pytest.mark.asyncio
    async def test_get_permissions_404_when_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.data_pipelines import get_pipeline_permissions

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))
        with pytest.raises(HTTPException) as exc:
            await get_pipeline_permissions(
                connection_id=999, current_user=mock_admin_user, db=mock_db_session
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_set_permissions_replaces_and_commits(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.data_pipelines import set_pipeline_permissions

        # execute #1 exists-check (returns the conn), #2 the DELETE.
        mock_db_session.execute = AsyncMock(side_effect=[_scalar_result(_conn(1)), MagicMock()])
        result = await set_pipeline_permissions(
            connection_id=1,
            data={"role_ids": [3, 4]},
            current_user=mock_admin_user,
            db=mock_db_session,
        )
        assert mock_db_session.add.call_count == 2
        mock_db_session.commit.assert_awaited_once()
        assert "2 grants" in result["message"]
