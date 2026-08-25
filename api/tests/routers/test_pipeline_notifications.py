"""Unit tests for pipeline notification config, groups, and poller helpers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.middleware.auth import CurrentUser


def _scalar(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _first(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.first.return_value = obj
    return result


def _conn(cid: int = 1) -> MagicMock:
    c = MagicMock()
    c.id = cid
    c.org_id = 1
    c.name = "Prod"
    return c


class TestConfig:
    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_none(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import get_config

        # execute #1 connection check, #2 config lookup (none saved yet).
        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(None)])
        result = await get_config(connection_id=1, current_user=mock_admin_user, db=mock_db_session)
        assert result["enabled"] is False
        assert result["poll_frequency_minutes"] == 60
        assert result["notify_on_failure"] is True

    @pytest.mark.asyncio
    async def test_get_404_when_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import get_config

        mock_db_session.execute = AsyncMock(return_value=_scalar(None))
        with pytest.raises(HTTPException) as exc:
            await get_config(connection_id=999, current_user=mock_admin_user, db=mock_db_session)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_upsert_clamps_poll_frequency_low(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """A too-frequent cadence is clamped up to the 10-minute minimum."""
        from app.routers.pipeline_notifications import NotificationConfigIn, upsert_config

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(None)])
        mock_db_session.refresh = AsyncMock()
        data = NotificationConfigIn(
            success_message="ok", failure_message="bad", poll_frequency_minutes=2
        )
        result = await upsert_config(
            connection_id=1, data=data, current_user=mock_admin_user, db=mock_db_session
        )
        assert result["poll_frequency_minutes"] == 10
        mock_db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_upsert_clamps_poll_frequency_high(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """A too-infrequent cadence is clamped down to the 24-hour maximum."""
        from app.routers.pipeline_notifications import NotificationConfigIn, upsert_config

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(None)])
        mock_db_session.refresh = AsyncMock()
        data = NotificationConfigIn(
            success_message="ok", failure_message="bad", poll_frequency_minutes=99999
        )
        result = await upsert_config(
            connection_id=1, data=data, current_user=mock_admin_user, db=mock_db_session
        )
        assert result["poll_frequency_minutes"] == 1440

    @pytest.mark.asyncio
    async def test_test_notification_400_without_groups(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import test_notification

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(None)])
        with pytest.raises(HTTPException) as exc:
            await test_notification(
                connection_id=1, current_user=mock_admin_user, db=mock_db_session
            )
        assert exc.value.status_code == 400


class TestGroups:
    @pytest.mark.asyncio
    async def test_update_404_when_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import NotificationGroupIn, update_group

        mock_db_session.execute = AsyncMock(return_value=_scalar(None))
        with pytest.raises(HTTPException) as exc:
            await update_group(
                group_id=999,
                data=NotificationGroupIn(name="X", channels={}),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert exc.value.status_code == 404


class TestPollerHelpers:
    def test_terminal_kind(self) -> None:
        from app.services.pipeline_poller import _terminal_kind

        assert _terminal_kind("Succeeded") == "success"
        assert _terminal_kind("COMPLETED") == "success"
        assert _terminal_kind("Failed") == "failure"
        assert _terminal_kind("Crashed") == "failure"
        assert _terminal_kind("InProgress") is None
        assert _terminal_kind(None) is None

    def test_render_fills_placeholders_and_ignores_unknown(self) -> None:
        from app.services.pipeline_poller import _render

        out = _render(
            "{pipeline} on {connection}: {status} {bogus}",
            {"pipeline": "ETL", "connection": "Prod", "status": "Failed"},
        )
        assert out == "ETL on Prod: Failed "

    def test_normalize_override_legacy_bool(self) -> None:
        from app.services.pipeline_poller import normalize_override

        assert normalize_override(False) == {"notify_on_success": False, "notify_on_failure": False}
        assert normalize_override(True) == {}
        assert normalize_override({"notify_on_success": True}) == {"notify_on_success": True}

    def test_effective_settings_override_wins_else_inherits(self) -> None:
        from app.services.pipeline_poller import effective_settings

        cfg = MagicMock()
        cfg.notify_on_success = False
        cfg.notify_on_failure = True
        cfg.success_message = "default-success"
        cfg.failure_message = "default-failure"
        cfg.pipeline_overrides = {
            "special": {"notify_on_success": True, "failure_message": "custom-fail"},
        }
        # Overridden pipeline: success flipped on, custom failure message, others inherited.
        special = effective_settings(cfg, "special")
        assert special["notify_on_success"] is True
        assert special["notify_on_failure"] is True  # inherited
        assert special["success_message"] == "default-success"  # inherited
        assert special["failure_message"] == "custom-fail"  # overridden
        # Non-overridden pipeline: pure inheritance.
        other = effective_settings(cfg, "other")
        assert other["notify_on_success"] is False
        assert other["failure_message"] == "default-failure"

    def test_build_context_includes_all_run_data(self) -> None:
        from app.services.pipeline_poller import build_context

        conn = MagicMock()
        conn.name = "Prod"
        conn.provider = "adf"
        run = {
            "run_id": "r1", "name": "ETL", "status": "Failed",
            "started_at": "2025-01-01T00:00:00", "ended_at": "2025-01-01T00:05:00",
            "duration_ms": 300000, "message": "boom", "invoked_by": "sched",
            "invoked_by_type": "ScheduleTrigger", "parent_run_id": None,
        }
        ctx = build_context(run, conn)
        # Every run field is available as a placeholder…
        assert ctx["run_id"] == "r1" and ctx["invoked_by"] == "sched"
        assert ctx["parent_run_id"] == ""  # None coerced to empty for templating
        # …plus connection + derived fields.
        assert ctx["pipeline"] == "ETL" and ctx["connection"] == "Prod"
        assert ctx["provider"] == "adf" and ctx["duration"] == "5m 0s"
