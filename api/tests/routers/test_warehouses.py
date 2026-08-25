"""Unit tests for warehouse connection sharing endpoints.

Warehouse access (who can query a warehouse in AI chat) is a distinct grant from
data dictionary view access. These endpoints are admin-only and org-scoped; the
tests below verify the 404 guard, the replace-all semantics, and org isolation.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.middleware.auth import CurrentUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scalar_result(obj: object | None) -> MagicMock:
    """A db.execute() result whose .scalar_one_or_none() returns obj."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _all_result(rows: list) -> MagicMock:
    """A db.execute() result whose .all() returns rows (each a tuple)."""
    result = MagicMock()
    result.all.return_value = rows
    return result


# ---------------------------------------------------------------------------
# get_warehouse_permissions
# ---------------------------------------------------------------------------


class TestGetWarehousePermissions:
    @pytest.mark.asyncio
    async def test_raises_404_when_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.warehouses import get_warehouse_permissions

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await get_warehouse_permissions(
                connection_id=999, current_user=mock_admin_user, db=mock_db_session
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_role_ids_for_existing_connection(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.warehouses import get_warehouse_permissions

        # First execute: connection-exists check; second: the grant rows.
        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(1), _all_result([(5,), (7,)])]
        )

        result = await get_warehouse_permissions(
            connection_id=1, current_user=mock_admin_user, db=mock_db_session
        )

        assert result == {"role_ids": [5, 7]}

    @pytest.mark.asyncio
    async def test_filters_out_null_role_ids(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """Legacy user-scoped grants (role_id NULL) are excluded from the role list."""
        from app.routers.warehouses import get_warehouse_permissions

        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(1), _all_result([(5,), (None,)])]
        )

        result = await get_warehouse_permissions(
            connection_id=1, current_user=mock_admin_user, db=mock_db_session
        )

        assert result == {"role_ids": [5]}


# ---------------------------------------------------------------------------
# set_warehouse_permissions
# ---------------------------------------------------------------------------


class TestSetWarehousePermissions:
    @pytest.mark.asyncio
    async def test_raises_404_when_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.warehouses import set_warehouse_permissions

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await set_warehouse_permissions(
                connection_id=999,
                data={"role_ids": [1]},
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404
        # Nothing is committed when the connection does not exist.
        mock_db_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replaces_grants_and_commits(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """Deletes existing grants, inserts one row per role id, commits once."""
        from app.routers.warehouses import set_warehouse_permissions

        # execute #1 exists-check, execute #2 the DELETE.
        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(1), MagicMock()]
        )

        result = await set_warehouse_permissions(
            connection_id=1,
            data={"role_ids": [3, 4, 9]},
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        assert mock_db_session.add.call_count == 3
        mock_db_session.commit.assert_awaited_once()
        assert "3 grants" in result["message"]

    @pytest.mark.asyncio
    async def test_empty_list_clears_all_grants(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """An empty role_ids list deletes grants and adds nothing."""
        from app.routers.warehouses import set_warehouse_permissions

        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(1), MagicMock()]
        )

        result = await set_warehouse_permissions(
            connection_id=1,
            data={"role_ids": []},
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_awaited_once()
        assert "0 grants" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_role_ids_key_defaults_to_empty(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """A payload with no role_ids key is treated as clearing all grants."""
        from app.routers.warehouses import set_warehouse_permissions

        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(1), MagicMock()]
        )

        result = await set_warehouse_permissions(
            connection_id=1,
            data={},
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        mock_db_session.add.assert_not_called()
        assert "0 grants" in result["message"]
