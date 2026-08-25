"""Tests for condition-based notification checks (idle + freshness)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.condition_checker import (
    _apply_result,
    _parse_ts,
    check_due_conditions,
    evaluate_condition,
    human_minutes,
)


def _condition(**overrides: object) -> MagicMock:
    cond = MagicMock()
    cond.id = 1
    cond.org_id = 1
    cond.pipeline_connection_id = 10
    cond.name = "orders freshness"
    cond.condition_type = "data_freshness"
    cond.enabled = True
    cond.threshold_minutes = 120
    cond.check_frequency_minutes = 60
    cond.pipeline_name = None
    cond.warehouse_connection_id = None
    cond.schema_name = None
    cond.table_name = "fct_orders"
    cond.timestamp_column = "updated_at"
    cond.group_ids = [1]
    cond.message_template = ""
    cond.notify_on_recovery = True
    cond.is_triggered = False
    cond.last_checked_at = None
    cond.last_observed_at = None
    cond.last_error = None
    for key, value in overrides.items():
        setattr(cond, key, value)
    return cond


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


class TestParseTs:
    def test_aware_datetime_passthrough(self) -> None:
        dt = datetime(2026, 7, 1, tzinfo=UTC)

        assert _parse_ts(dt) == dt

    def test_naive_datetime_assumed_utc(self) -> None:
        assert _parse_ts(datetime(2026, 7, 1)).tzinfo == UTC

    def test_iso_string_with_z_suffix(self) -> None:
        assert _parse_ts("2026-07-01T10:00:00Z") == datetime(2026, 7, 1, 10, tzinfo=UTC)

    def test_invalid_values_return_none(self) -> None:
        assert _parse_ts(None) is None
        assert _parse_ts("not-a-date") is None
        assert _parse_ts(12345) is None


class TestHumanMinutes:
    def test_formats_scales(self) -> None:
        assert human_minutes(None) == "unknown"
        assert human_minutes(45) == "45m"
        assert human_minutes(200) == "3h 20m"
        assert human_minutes(60 * 24 * 2 + 60 * 4) == "2d 4h"


class TestEvaluatePipelineIdle:
    def _provider(self, runs: list[dict]) -> MagicMock:
        provider = MagicMock()
        provider.meta.implemented = True
        provider.list_runs = AsyncMock(return_value={"runs": runs})
        return provider

    def _pipeline_conn(self) -> MagicMock:
        conn = MagicMock()
        conn.provider = "prefect"
        conn.config = {}
        conn.secret_encrypted = None
        return conn

    @pytest.mark.asyncio
    async def test_recent_run_is_not_triggered(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(condition_type="pipeline_idle", threshold_minutes=360)
        recent = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(self._pipeline_conn()))

        with patch(
            "app.services.condition_checker.providers.get_provider",
            return_value=self._provider([{"started_at": recent}]),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["ok"] is True
        assert result["triggered"] is False
        assert result["age_minutes"] < 60

    @pytest.mark.asyncio
    async def test_stale_run_is_triggered(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(condition_type="pipeline_idle", threshold_minutes=60)
        old = (datetime.now(UTC) - timedelta(hours=8)).isoformat()
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(self._pipeline_conn()))

        with patch(
            "app.services.condition_checker.providers.get_provider",
            return_value=self._provider([{"started_at": old}]),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["triggered"] is True

    @pytest.mark.asyncio
    async def test_no_runs_at_all_is_triggered(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(condition_type="pipeline_idle")
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(self._pipeline_conn()))

        with patch(
            "app.services.condition_checker.providers.get_provider",
            return_value=self._provider([]),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["triggered"] is True
        assert result["observed_at"] is None

    @pytest.mark.asyncio
    async def test_provider_error_reports_not_ok(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(condition_type="pipeline_idle")
        provider = MagicMock()
        provider.meta.implemented = True
        provider.list_runs = AsyncMock(side_effect=RuntimeError("api down"))
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(self._pipeline_conn()))

        with patch("app.services.condition_checker.providers.get_provider", return_value=provider):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["ok"] is False
        assert result["triggered"] is None
        assert "api down" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_connection_reports_not_ok(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(condition_type="pipeline_idle")
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(None))

        result = await evaluate_condition(mock_db_session, cond)

        assert result["ok"] is False


class TestEvaluateDataFreshness:
    @pytest.mark.asyncio
    async def test_invalid_identifier_reports_not_ok(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(table_name="orders; DROP TABLE x")

        result = await evaluate_condition(mock_db_session, cond)

        assert result["ok"] is False
        assert "identifier" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_external_warehouse_fresh_data_not_triggered(
        self, mock_db_session: AsyncMock
    ) -> None:
        wh = MagicMock()
        wh.id = 5
        wh.name = "snowflake"
        wh.db_type = "snowflake"
        wh.host = "acct"
        wh.port = None
        wh.database_name = "db"
        wh.username = "u"
        wh.password_encrypted = None
        wh.schemas = []
        wh.extra_config = {}
        cond = _condition(warehouse_connection_id=5, threshold_minutes=120)
        recent = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(wh))

        with patch(
            "app.services.warehouse_inspector.run_select",
            new=AsyncMock(return_value=(["max"], [[recent]], 1, None)),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["ok"] is True
        assert result["triggered"] is False

    @pytest.mark.asyncio
    async def test_external_warehouse_stale_data_triggered(
        self, mock_db_session: AsyncMock
    ) -> None:
        wh = MagicMock()
        wh.password_encrypted = None
        wh.schemas = []
        wh.extra_config = {}
        cond = _condition(warehouse_connection_id=5, threshold_minutes=60)
        old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(wh))

        with patch(
            "app.services.warehouse_inspector.run_select",
            new=AsyncMock(return_value=(["max"], [[old]], 1, None)),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["triggered"] is True

    @pytest.mark.asyncio
    async def test_empty_table_is_triggered(self, mock_db_session: AsyncMock) -> None:
        wh = MagicMock()
        wh.password_encrypted = None
        wh.schemas = []
        wh.extra_config = {}
        cond = _condition(warehouse_connection_id=5)
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(wh))

        with patch(
            "app.services.warehouse_inspector.run_select",
            new=AsyncMock(return_value=(["max"], [[None]], 1, None)),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["triggered"] is True

    @pytest.mark.asyncio
    async def test_probe_error_reports_not_ok(self, mock_db_session: AsyncMock) -> None:
        wh = MagicMock()
        wh.password_encrypted = None
        wh.schemas = []
        wh.extra_config = {}
        cond = _condition(warehouse_connection_id=5)
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(wh))

        with patch(
            "app.services.warehouse_inspector.run_select",
            new=AsyncMock(return_value=([], [], 0, "relation does not exist")),
        ):
            result = await evaluate_condition(mock_db_session, cond)

        assert result["ok"] is False
        assert "relation" in result["error"]


class TestApplyResult:
    def _ok_result(self, triggered: bool, age: float | None = 30) -> dict:
        return {
            "ok": True,
            "triggered": triggered,
            "observed_at": datetime.now(UTC) - timedelta(minutes=age or 0),
            "age_minutes": age,
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_trip_transition_sends_alert(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(is_triggered=False)

        with patch("app.services.condition_checker.send_to_groups", new=AsyncMock()) as send:
            await _apply_result(mock_db_session, cond, self._ok_result(triggered=True))

        send.assert_awaited_once()
        assert "alert" in send.call_args.args[3].lower()
        assert cond.is_triggered is True

    @pytest.mark.asyncio
    async def test_still_triggered_does_not_realert(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(is_triggered=True)

        with patch("app.services.condition_checker.send_to_groups", new=AsyncMock()) as send:
            await _apply_result(mock_db_session, cond, self._ok_result(triggered=True))

        send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recovery_transition_sends_recovery_notice(
        self, mock_db_session: AsyncMock
    ) -> None:
        cond = _condition(is_triggered=True)

        with patch("app.services.condition_checker.send_to_groups", new=AsyncMock()) as send:
            await _apply_result(mock_db_session, cond, self._ok_result(triggered=False))

        send.assert_awaited_once()
        assert "recovered" in send.call_args.args[3].lower()
        assert cond.is_triggered is False

    @pytest.mark.asyncio
    async def test_recovery_suppressed_when_disabled(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(is_triggered=True, notify_on_recovery=False)

        with patch("app.services.condition_checker.send_to_groups", new=AsyncMock()) as send:
            await _apply_result(mock_db_session, cond, self._ok_result(triggered=False))

        send.assert_not_awaited()
        assert cond.is_triggered is False

    @pytest.mark.asyncio
    async def test_probe_error_keeps_previous_state(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(is_triggered=True)
        error_result = {
            "ok": False,
            "triggered": None,
            "observed_at": None,
            "age_minutes": None,
            "error": "boom",
        }

        with patch("app.services.condition_checker.send_to_groups", new=AsyncMock()) as send:
            await _apply_result(mock_db_session, cond, error_result)

        send.assert_not_awaited()
        assert cond.is_triggered is True
        assert cond.last_error == "boom"


class TestCheckDueConditions:
    @pytest.mark.asyncio
    async def test_skips_conditions_not_yet_due(self, mock_db_session: AsyncMock) -> None:
        cond = _condition(
            last_checked_at=datetime.now(UTC) - timedelta(minutes=5),
            check_frequency_minutes=60,
        )
        scalars = MagicMock()
        scalars.all.return_value = [cond]
        listing = MagicMock()
        listing.scalars.return_value = scalars
        mock_db_session.execute = AsyncMock(return_value=listing)

        with patch(
            "app.services.condition_checker.evaluate_condition", new=AsyncMock()
        ) as evaluate:
            await check_due_conditions(mock_db_session)

        evaluate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_due_condition_is_evaluated_and_committed(
        self, mock_db_session: AsyncMock
    ) -> None:
        cond = _condition(last_checked_at=None)
        scalars = MagicMock()
        scalars.all.return_value = [cond]
        listing = MagicMock()
        listing.scalars.return_value = scalars
        mock_db_session.execute = AsyncMock(return_value=listing)
        ok = {"ok": True, "triggered": False, "observed_at": None, "age_minutes": 1, "error": None}

        with patch(
            "app.services.condition_checker.evaluate_condition",
            new=AsyncMock(return_value=ok),
        ):
            await check_due_conditions(mock_db_session)

        mock_db_session.commit.assert_awaited_once()
