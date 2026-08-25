"""Tests for the notification event dispatcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services.notifications.dispatcher import (
    _build_subject_and_message,
    _deliver,
    dispatch_event,
)


def _pref(channel: str, user_id: int = 2, config: dict | None = None) -> MagicMock:
    pref = MagicMock()
    pref.channel = channel
    pref.user_id = user_id
    pref.config = config
    return pref


def _scalars_result(objs: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = objs
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalar_result(obj: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    return result


def _fake_app_db(session: AsyncMock) -> object:
    """An async generator factory standing in for get_app_db."""

    async def gen():  # noqa: ANN202
        yield session

    return gen


def _redis(rate_limit_allows: bool = True) -> AsyncMock:
    client = AsyncMock()
    client.set = AsyncMock(return_value=rate_limit_allows)
    client.xadd = AsyncMock()
    return client


class TestDispatchEvent:
    @pytest.mark.asyncio
    async def test_none_org_id_is_a_noop(self) -> None:
        with patch("app.database.get_app_db") as get_db:
            await dispatch_event("pipeline_failure", {}, org_id=None)

        get_db.assert_not_called()

    @pytest.mark.asyncio
    async def test_delivers_to_enabled_channel(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "notification_channels_enabled", "email")
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([_pref("email")]))

        with (
            patch("app.database.get_app_db", new=_fake_app_db(mock_db_session)),
            patch(
                "app.services.notifications.dispatcher.get_redis",
                new=AsyncMock(return_value=_redis()),
            ),
            patch(
                "app.services.notifications.dispatcher._deliver",
                new=AsyncMock(return_value=(True, None)),
            ) as deliver,
        ):
            await dispatch_event("pipeline_failure", {"subject": "s", "message": "m"}, org_id=1)

        deliver.assert_awaited_once()
        assert deliver.call_args.args[2] == "s"
        assert deliver.call_args.args[3] == "m"

    @pytest.mark.asyncio
    async def test_channel_not_in_enabled_list_is_skipped(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "notification_channels_enabled", "email")
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([_pref("sms")]))

        with (
            patch("app.database.get_app_db", new=_fake_app_db(mock_db_session)),
            patch(
                "app.services.notifications.dispatcher.get_redis",
                new=AsyncMock(return_value=_redis()),
            ),
            patch(
                "app.services.notifications.dispatcher._deliver",
                new=AsyncMock(return_value=(True, None)),
            ) as deliver,
        ):
            await dispatch_event("pipeline_failure", {}, org_id=1)

        deliver.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rate_limited_user_is_skipped(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "notification_channels_enabled", "email")
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([_pref("email")]))

        with (
            patch("app.database.get_app_db", new=_fake_app_db(mock_db_session)),
            patch(
                "app.services.notifications.dispatcher.get_redis",
                new=AsyncMock(return_value=_redis(rate_limit_allows=False)),
            ),
            patch(
                "app.services.notifications.dispatcher._deliver",
                new=AsyncMock(return_value=(True, None)),
            ) as deliver,
        ):
            await dispatch_event("pipeline_failure", {}, org_id=1)

        deliver.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_audit_trail_written_to_redis_stream(
        self, mock_db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "notification_channels_enabled", "email")
        mock_db_session.execute = AsyncMock(return_value=_scalars_result([_pref("email")]))
        redis_client = _redis()

        with (
            patch("app.database.get_app_db", new=_fake_app_db(mock_db_session)),
            patch(
                "app.services.notifications.dispatcher.get_redis",
                new=AsyncMock(return_value=redis_client),
            ),
            patch(
                "app.services.notifications.dispatcher._deliver",
                new=AsyncMock(return_value=(True, None)),
            ),
        ):
            await dispatch_event("data_freshness", {"message": "stale"}, org_id=1)

        redis_client.xadd.assert_awaited_once()
        stream, fields = redis_client.xadd.call_args.args
        assert stream == "notifications:email"
        assert fields["ok"] == "1"


class TestDeliver:
    @pytest.mark.asyncio
    async def test_email_resolves_user_address(self, mock_db_session: AsyncMock) -> None:
        user = MagicMock()
        user.email = "u@example.com"
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(user))

        with patch(
            "app.services.pipeline_notifications._send_email",
            new=AsyncMock(return_value=(True, None)),
        ) as send:
            ok, error = await _deliver(mock_db_session, _pref("email"), "subj", "body")

        assert ok is True
        send.assert_awaited_once_with(["u@example.com"], "subj", "body")

    @pytest.mark.asyncio
    async def test_webhook_channel_without_url_fails(self, mock_db_session: AsyncMock) -> None:
        ok, error = await _deliver(mock_db_session, _pref("slack", config={}), "s", "m")

        assert ok is False
        assert "webhook_url" in error

    @pytest.mark.asyncio
    async def test_webhook_channel_with_url_sends(self, mock_db_session: AsyncMock) -> None:
        pref = _pref("slack", config={"webhook_url": "https://hooks.slack.com/x"})

        with patch(
            "app.services.pipeline_notifications._send_slack",
            new=AsyncMock(return_value=(True, None)),
        ) as send:
            ok, _ = await _deliver(mock_db_session, pref, "s", "m")

        assert ok is True
        send.assert_awaited_once_with("https://hooks.slack.com/x", "m")

    @pytest.mark.asyncio
    async def test_sms_without_phone_fails(self, mock_db_session: AsyncMock) -> None:
        user = MagicMock()
        user.phone_number = None
        mock_db_session.execute = AsyncMock(return_value=_scalar_result(user))

        ok, error = await _deliver(mock_db_session, _pref("sms"), "s", "m")

        assert ok is False
        assert "phone" in error.lower()


class TestBuildSubjectAndMessage:
    def test_explicit_subject_and_message_used(self) -> None:
        subject, message = _build_subject_and_message(
            "pipeline_failure", {"subject": "S", "message": "M"}
        )

        assert (subject, message) == ("S", "M")

    def test_fallbacks_render_event_type_and_details(self) -> None:
        subject, message = _build_subject_and_message(
            "data_freshness", {"table": "fct_orders", "age": "3h"}
        )

        assert "data freshness" in subject
        assert "table: fct_orders" in message
        assert "age: 3h" in message
