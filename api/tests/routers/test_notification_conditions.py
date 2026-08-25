"""Tests for the notification condition CRUD endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser


def _scalar_result(obj: object | None) -> MagicMock:
    """A db.execute() result whose .scalar_one_or_none() returns obj."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _scalars_result(objs: list) -> MagicMock:
    """A db.execute() result whose .scalars().all() returns objs."""
    scalars = MagicMock()
    scalars.all.return_value = objs
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _freshness_payload(**overrides: object) -> object:
    from app.routers.pipeline_notifications import NotificationConditionIn

    data = {
        "name": "orders freshness",
        "condition_type": "data_freshness",
        "threshold_minutes": 120,
        "check_frequency_minutes": 60,
        "table_name": "fct_orders",
        "timestamp_column": "updated_at",
        "group_ids": [1],
    }
    data.update(overrides)
    return NotificationConditionIn(**data)


class TestCreateCondition:
    @pytest.mark.asyncio
    async def test_creates_freshness_condition_and_commits(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import create_condition

        # execute #1 pipeline-connection exists-check.
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(MagicMock()))
        mock_db_session.refresh = AsyncMock()

        await create_condition(
            connection_id=10,
            data=_freshness_payload(),
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clamps_check_frequency_to_minimum(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import create_condition

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(MagicMock()))
        mock_db_session.refresh = AsyncMock()

        await create_condition(
            connection_id=10,
            data=_freshness_payload(check_frequency_minutes=1),
            current_user=mock_admin_user,
            db=mock_db_session,
        )

        created = mock_db_session.add.call_args.args[0]
        assert created.check_frequency_minutes == 10

    @pytest.mark.asyncio
    async def test_raises_404_when_pipeline_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import create_condition

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await create_condition(
                connection_id=999,
                data=_freshness_payload(),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_table_identifier_raises_400(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import create_condition

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(MagicMock()))

        with pytest.raises(HTTPException) as exc_info:
            await create_condition(
                connection_id=10,
                data=_freshness_payload(table_name="x; DROP TABLE y"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 400
        mock_db_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_timestamp_column_raises_400(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import create_condition

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(MagicMock()))

        with pytest.raises(HTTPException) as exc_info:
            await create_condition(
                connection_id=10,
                data=_freshness_payload(timestamp_column=None),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_cross_org_warehouse_raises_404(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import create_condition

        # execute #1 pipeline connection found, #2 warehouse lookup misses.
        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(MagicMock()), _scalar_result(None)]
        )

        with pytest.raises(HTTPException) as exc_info:
            await create_condition(
                connection_id=10,
                data=_freshness_payload(warehouse_connection_id=42),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404


class TestListConditions:
    @pytest.mark.asyncio
    async def test_returns_serialized_conditions(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import list_conditions

        cond = MagicMock()
        cond.id = 3
        cond.pipeline_connection_id = 10
        cond.name = "idle check"
        cond.condition_type = "pipeline_idle"
        cond.enabled = True
        cond.threshold_minutes = 360
        cond.check_frequency_minutes = 60
        cond.pipeline_name = None
        cond.warehouse_connection_id = None
        cond.schema_name = None
        cond.table_name = None
        cond.timestamp_column = None
        cond.group_ids = [2]
        cond.message_template = ""
        cond.notify_on_recovery = True
        cond.is_triggered = False
        cond.last_checked_at = None
        cond.last_observed_at = None
        cond.last_error = None
        # execute #1 connection exists-check, #2 conditions listing.
        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar_result(MagicMock()), _scalars_result([cond])]
        )

        result = await list_conditions(
            connection_id=10, current_user=mock_admin_user, db=mock_db_session
        )

        assert len(result) == 1
        assert result[0]["id"] == 3
        assert result[0]["condition_type"] == "pipeline_idle"
        assert result[0]["is_triggered"] is False


class TestUpdateAndDeleteCondition:
    @pytest.mark.asyncio
    async def test_update_raises_404_when_missing_or_cross_org(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import update_condition

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await update_condition(
                condition_id=999,
                data=_freshness_payload(),
                current_user=mock_admin_user,
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_removes_and_commits(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import delete_condition

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(MagicMock()))
        mock_db_session.delete = AsyncMock()

        await delete_condition(condition_id=3, current_user=mock_admin_user, db=mock_db_session)

        mock_db_session.delete.assert_awaited_once()
        mock_db_session.commit.assert_awaited_once()


class TestRunConditionCheck:
    @pytest.mark.asyncio
    async def test_returns_dry_run_result_without_commit(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import run_condition_check

        mock_db_session.execute = AsyncMock(return_value=_scalar_result(MagicMock()))
        outcome = {
            "ok": True,
            "triggered": True,
            "observed_at": None,
            "age_minutes": None,
            "error": None,
        }

        with patch(
            "app.services.condition_checker.evaluate_condition",
            new=AsyncMock(return_value=outcome),
        ):
            result = await run_condition_check(
                condition_id=3, current_user=mock_admin_user, db=mock_db_session
            )

        assert result["triggered"] is True
        assert result["observed_at"] is None
        mock_db_session.commit.assert_not_awaited()
