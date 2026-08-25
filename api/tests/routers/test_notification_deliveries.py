"""Unit tests for notification delivery history, preview, and test send."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.middleware.auth import CurrentUser


def _scalar(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _scalars(items: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _rows(items: list[tuple[object, ...]]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = items
    return result


def _scalar_value(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _conn(cid: int = 1, provider: str = "adf") -> MagicMock:
    c = MagicMock()
    c.id = cid
    c.org_id = 1
    c.name = "Prod"
    c.provider = provider
    c.config = {}
    c.secret_encrypted = None
    return c


def _cfg(**overrides: object) -> MagicMock:
    cfg = MagicMock()
    cfg.pipeline_connection_id = 1
    cfg.enabled = True
    cfg.notify_on_success = True
    cfg.notify_on_failure = True
    cfg.success_message = "OK {pipeline} on {connection}"
    cfg.failure_message = "FAIL {pipeline}: {message}"
    cfg.poll_frequency_minutes = 60
    cfg.success_group_ids = [7]
    cfg.failure_group_ids = [8]
    cfg.pipeline_overrides = {}
    cfg.min_interval_minutes = 0
    cfg.quiet_hours_start = None
    cfg.quiet_hours_end = None
    cfg.quiet_hours_tz = "UTC"
    cfg.quiet_hours_include_failures = False
    cfg.last_polled_at = None
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _delivery(did: int = 1, sent: int = 2, failed: int = 0) -> MagicMock:
    d = MagicMock()
    d.id = did
    d.source = "run_failure"
    d.pipeline_name = "LoadOrders"
    d.run_id = "r1"
    d.condition_id = None
    d.subject = "Pipeline LoadOrders failure — Prod"
    d.message = "FAIL LoadOrders: boom"
    d.group_ids = [8]
    d.sent_count = sent
    d.failed_count = failed
    d.details = [
        {"channel": "slack", "target": "hooks.slack.com/…abc123", "ok": True, "error": None}
    ]
    d.created_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    return d


class TestRedaction:
    def test_webhook_url_is_reduced_to_host_and_suffix(self) -> None:
        from app.services.pipeline_notifications import _redact

        out = _redact("https://hooks.slack.com/services/T00/B00/XXXXsecretYYYY", "slack")
        assert "secret" not in out
        assert out.startswith("hooks.slack.com/")

    def test_phone_number_keeps_only_last_four_digits(self) -> None:
        from app.services.pipeline_notifications import _redact

        assert _redact("+14155550123", "sms") == "…0123"

    def test_email_target_is_left_intact(self) -> None:
        from app.services.pipeline_notifications import _redact

        assert _redact("ops@example.com", "email") == "ops@example.com"


class TestDeliveryLogging:
    @pytest.mark.asyncio
    async def test_send_records_a_delivery_row(self, mock_db_session: AsyncMock) -> None:
        from app.services.pipeline_notifications import send_to_groups

        group = MagicMock()
        group.channels = {"slack": ["https://hooks.slack.com/services/A/B/C"]}
        mock_db_session.execute = AsyncMock(return_value=_scalars([group]))
        mock_db_session.flush = AsyncMock()

        with patch(
            "app.services.pipeline_notifications._send_slack",
            AsyncMock(return_value=(True, None)),
        ):
            result = await send_to_groups(
                mock_db_session, 1, [7], "subject", "message",
                source="run_failure", pipeline_connection_id=1,
                pipeline_name="LoadOrders", run_id="r1",
            )

        assert result["sent"] == 1
        recorded = mock_db_session.add.call_args[0][0]
        assert recorded.source == "run_failure"
        assert recorded.run_id == "r1"
        assert recorded.sent_count == 1
        assert recorded.failed_count == 0

    @pytest.mark.asyncio
    async def test_recorded_target_is_redacted(self, mock_db_session: AsyncMock) -> None:
        from app.services.pipeline_notifications import send_to_groups

        group = MagicMock()
        group.channels = {"slack": ["https://hooks.slack.com/services/T/B/SUPERSECRET"]}
        mock_db_session.execute = AsyncMock(return_value=_scalars([group]))
        mock_db_session.flush = AsyncMock()

        with patch(
            "app.services.pipeline_notifications._send_slack",
            AsyncMock(return_value=(True, None)),
        ):
            await send_to_groups(mock_db_session, 1, [7], "s", "m")

        recorded = mock_db_session.add.call_args[0][0]
        assert "SUPERSECRET" not in recorded.details[0]["target"]

    @pytest.mark.asyncio
    async def test_failed_send_is_recorded_with_its_error(self, mock_db_session: AsyncMock) -> None:
        from app.services.pipeline_notifications import send_to_groups

        group = MagicMock()
        group.channels = {"slack": ["https://hooks.slack.com/services/A/B/C"]}
        mock_db_session.execute = AsyncMock(return_value=_scalars([group]))
        mock_db_session.flush = AsyncMock()

        with patch(
            "app.services.pipeline_notifications._send_slack",
            AsyncMock(return_value=(False, "HTTP 404: no_service")),
        ):
            result = await send_to_groups(mock_db_session, 1, [7], "s", "m")

        assert result["failed"] == 1
        recorded = mock_db_session.add.call_args[0][0]
        assert recorded.failed_count == 1
        assert recorded.details[0]["error"] == "HTTP 404: no_service"

    @pytest.mark.asyncio
    async def test_record_false_skips_the_audit_row(self, mock_db_session: AsyncMock) -> None:
        from app.services.pipeline_notifications import send_to_groups

        group = MagicMock()
        group.channels = {"slack": ["https://hooks.slack.com/x"]}
        mock_db_session.execute = AsyncMock(return_value=_scalars([group]))

        with patch(
            "app.services.pipeline_notifications._send_slack",
            AsyncMock(return_value=(True, None)),
        ):
            await send_to_groups(mock_db_session, 1, [7], "s", "m", record=False)

        mock_db_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_group_list_sends_and_records_nothing(
        self, mock_db_session: AsyncMock
    ) -> None:
        from app.services.pipeline_notifications import send_to_groups

        result = await send_to_groups(mock_db_session, 1, [], "s", "m")

        assert result == {"sent": 0, "failed": 0, "details": []}
        mock_db_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_the_send(
        self, mock_db_session: AsyncMock
    ) -> None:
        """Losing the history row must never lose the notification."""
        from app.services.pipeline_notifications import send_to_groups

        group = MagicMock()
        group.channels = {"slack": ["https://hooks.slack.com/x"]}
        mock_db_session.execute = AsyncMock(return_value=_scalars([group]))
        mock_db_session.flush = AsyncMock(side_effect=RuntimeError("db gone"))

        with patch(
            "app.services.pipeline_notifications._send_slack",
            AsyncMock(return_value=(True, None)),
        ):
            result = await send_to_groups(mock_db_session, 1, [7], "s", "m")

        assert result["sent"] == 1


class TestListDeliveries:
    @pytest.mark.asyncio
    async def test_returns_serialised_rows(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import list_deliveries

        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar(_conn()), _scalars([_delivery()])]
        )
        result = await list_deliveries(
            connection_id=1, limit=50, current_user=mock_admin_user, db=mock_db_session
        )
        assert len(result["deliveries"]) == 1
        assert result["deliveries"][0]["source"] == "run_failure"
        assert result["deliveries"][0]["sent_count"] == 2

    @pytest.mark.asyncio
    async def test_404_when_connection_missing(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import list_deliveries

        mock_db_session.execute = AsyncMock(return_value=_scalar(None))
        with pytest.raises(HTTPException) as exc:
            await list_deliveries(
                connection_id=999, limit=50, current_user=mock_admin_user, db=mock_db_session
            )
        assert exc.value.status_code == 404


class TestNotificationSummary:
    @pytest.mark.asyncio
    async def test_aggregates_counts_across_sources(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import notification_summary

        mock_db_session.execute = AsyncMock(
            side_effect=[
                _scalar(_conn()),
                _rows([("run_failure", 3, 6, 1), ("test", 1, 2, 0)]),
                _scalar_value(datetime(2026, 7, 30, 12, 0, tzinfo=UTC)),
            ]
        )
        result = await notification_summary(
            connection_id=1, days=7, current_user=mock_admin_user, db=mock_db_session
        )
        assert result["attempts"] == 4
        assert result["sent"] == 8
        assert result["failed"] == 1
        assert result["by_source"]["run_failure"]["attempts"] == 3

    @pytest.mark.asyncio
    async def test_empty_history_returns_zeroes(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import notification_summary

        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar(_conn()), _rows([]), _scalar_value(None)]
        )
        result = await notification_summary(
            connection_id=1, days=7, current_user=mock_admin_user, db=mock_db_session
        )
        assert result == {
            "days": 7,
            "by_source": {},
            "attempts": 0,
            "sent": 0,
            "failed": 0,
            "last_delivery_at": None,
        }


class TestPreview:
    @pytest.mark.asyncio
    async def test_falls_back_to_a_sample_run_when_none_available(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import PreviewIn, preview_notification

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        with patch("app.services.pipeline_providers.get_provider", return_value=None):
            result = await preview_notification(
                connection_id=1,
                data=PreviewIn(kind="failure"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert result["used_sample"] is True
        # The saved failure template is rendered with the sample run's message.
        assert result["message"].startswith("FAIL SamplePipeline:")

    @pytest.mark.asyncio
    async def test_renders_an_unsaved_template_override(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import PreviewIn, preview_notification

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        with patch("app.services.pipeline_providers.get_provider", return_value=None):
            result = await preview_notification(
                connection_id=1,
                data=PreviewIn(kind="failure", template="Custom {pipeline} @ {connection}"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert result["message"] == "Custom SamplePipeline @ Prod"

    @pytest.mark.asyncio
    async def test_unknown_placeholder_renders_empty_not_error(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import PreviewIn, preview_notification

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        with patch("app.services.pipeline_providers.get_provider", return_value=None):
            result = await preview_notification(
                connection_id=1,
                data=PreviewIn(kind="success", template="A{nope}B"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert result["message"] == "AB"

    @pytest.mark.asyncio
    async def test_uses_a_real_matching_run_when_one_exists(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import PreviewIn, preview_notification

        provider = MagicMock()
        provider.meta.implemented = True
        provider.list_runs = AsyncMock(
            return_value={
                "runs": [
                    {"run_id": "x", "name": "Skip", "status": "Succeeded"},
                    {"run_id": "y", "name": "LoadOrders", "status": "Failed", "message": "boom"},
                ]
            }
        )
        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        with patch("app.services.pipeline_providers.get_provider", return_value=provider):
            result = await preview_notification(
                connection_id=1,
                data=PreviewIn(kind="failure", pipeline_name="LoadOrders"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert result["used_sample"] is False
        assert result["run_id"] == "y"
        assert result["message"] == "FAIL LoadOrders: boom"

    @pytest.mark.asyncio
    async def test_provider_error_still_produces_a_preview(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import PreviewIn, preview_notification

        provider = MagicMock()
        provider.meta.implemented = True
        provider.list_runs = AsyncMock(side_effect=RuntimeError("unreachable"))
        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        with patch("app.services.pipeline_providers.get_provider", return_value=provider):
            result = await preview_notification(
                connection_id=1,
                data=PreviewIn(kind="failure"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert result["used_sample"] is True


class TestTestSend:
    @pytest.mark.asyncio
    async def test_rejects_group_ids_from_another_org(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from fastapi import HTTPException

        from app.routers.pipeline_notifications import TestNotificationIn, test_notification

        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(
            side_effect=[_scalar(_conn()), _scalar(_cfg()), empty]
        )
        with pytest.raises(HTTPException) as exc:
            await test_notification(
                connection_id=1,
                data=TestNotificationIn(group_ids=[999]),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_kind_success_sends_the_real_rendered_template(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import TestNotificationIn, test_notification

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        sender = AsyncMock(return_value={"sent": 1, "failed": 0, "details": []})
        with (
            patch("app.services.pipeline_notifications.send_to_groups", sender),
            patch("app.services.pipeline_providers.get_provider", return_value=None),
        ):
            await test_notification(
                connection_id=1,
                data=TestNotificationIn(kind="success"),
                current_user=mock_admin_user,
                db=mock_db_session,
            )
        message = sender.await_args.kwargs["message"]
        subject = sender.await_args.kwargs["subject"]
        assert message.startswith("OK SamplePipeline on Prod")
        assert subject.startswith("[TEST]")
        assert sender.await_args.kwargs["source"] == "test"

    @pytest.mark.asyncio
    async def test_plain_kind_keeps_the_original_fixed_message(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import test_notification

        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(_cfg())])
        sender = AsyncMock(return_value={"sent": 1, "failed": 0, "details": []})
        with patch("app.services.pipeline_notifications.send_to_groups", sender):
            await test_notification(
                connection_id=1, current_user=mock_admin_user, db=mock_db_session
            )
        assert "test notification" in sender.await_args.kwargs["message"]

    @pytest.mark.asyncio
    async def test_400_when_no_group_is_configured(
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


class TestQuietHoursPersistence:
    @pytest.mark.asyncio
    async def test_half_configured_window_is_stored_as_off(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        """A start without an end would never trigger; save it as disabled."""
        from app.routers.pipeline_notifications import NotificationConfigIn, upsert_config

        cfg = _cfg()
        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(cfg)])
        mock_db_session.refresh = AsyncMock()
        await upsert_config(
            connection_id=1,
            data=NotificationConfigIn(
                success_message="s", failure_message="f", quiet_hours_start=22
            ),
            current_user=mock_admin_user,
            db=mock_db_session,
        )
        assert cfg.quiet_hours_start is None
        assert cfg.quiet_hours_end is None

    @pytest.mark.asyncio
    async def test_unknown_timezone_is_stored_as_utc(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import NotificationConfigIn, upsert_config

        cfg = _cfg()
        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(cfg)])
        mock_db_session.refresh = AsyncMock()
        await upsert_config(
            connection_id=1,
            data=NotificationConfigIn(
                success_message="s", failure_message="f", quiet_hours_tz="Mars/Olympus"
            ),
            current_user=mock_admin_user,
            db=mock_db_session,
        )
        assert cfg.quiet_hours_tz == "UTC"

    @pytest.mark.asyncio
    async def test_valid_window_and_timezone_are_persisted(
        self, mock_admin_user: CurrentUser, mock_db_session: AsyncMock
    ) -> None:
        from app.routers.pipeline_notifications import NotificationConfigIn, upsert_config

        cfg = _cfg()
        mock_db_session.execute = AsyncMock(side_effect=[_scalar(_conn()), _scalar(cfg)])
        mock_db_session.refresh = AsyncMock()
        await upsert_config(
            connection_id=1,
            data=NotificationConfigIn(
                success_message="s",
                failure_message="f",
                quiet_hours_start=22,
                quiet_hours_end=6,
                quiet_hours_tz="America/New_York",
                min_interval_minutes=45,
            ),
            current_user=mock_admin_user,
            db=mock_db_session,
        )
        assert (cfg.quiet_hours_start, cfg.quiet_hours_end) == (22, 6)
        assert cfg.quiet_hours_tz == "America/New_York"
        assert cfg.min_interval_minutes == 45
