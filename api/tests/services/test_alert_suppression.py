"""Unit tests for pipeline alert suppression (throttle + quiet hours)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.alert_suppression import (
    REASON_QUIET_HOURS,
    REASON_THROTTLED,
    is_quiet_hour,
    should_suppress,
    throttle_key,
)

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


class TestThrottleKey:
    def test_key_combines_pipeline_and_kind(self) -> None:
        assert throttle_key("LoadOrders", "failure") == "LoadOrders|failure"

    def test_same_pipeline_different_kind_gets_distinct_key(self) -> None:
        assert throttle_key("p", "success") != throttle_key("p", "failure")


class TestIsQuietHour:
    def test_no_window_configured_is_never_quiet(self) -> None:
        assert is_quiet_hour(NOW, None, None) is False

    def test_half_configured_window_is_never_quiet(self) -> None:
        assert is_quiet_hour(NOW, 22, None) is False
        assert is_quiet_hour(NOW, None, 6) is False

    def test_daytime_window_includes_start_hour(self) -> None:
        assert is_quiet_hour(NOW.replace(hour=9), 9, 17) is True

    def test_daytime_window_excludes_end_hour(self) -> None:
        assert is_quiet_hour(NOW.replace(hour=17), 9, 17) is False

    def test_outside_daytime_window_is_not_quiet(self) -> None:
        assert is_quiet_hour(NOW.replace(hour=8), 9, 17) is False

    def test_window_wrapping_midnight_covers_late_evening(self) -> None:
        assert is_quiet_hour(NOW.replace(hour=23), 22, 6) is True

    def test_window_wrapping_midnight_covers_early_morning(self) -> None:
        assert is_quiet_hour(NOW.replace(hour=3), 22, 6) is True

    def test_window_wrapping_midnight_excludes_midday(self) -> None:
        assert is_quiet_hour(NOW.replace(hour=12), 22, 6) is False

    def test_equal_bounds_never_silence_everything(self) -> None:
        # A mis-set start == end must not mute every hour of the day.
        for hour in range(24):
            assert is_quiet_hour(NOW.replace(hour=hour), 9, 9) is False

    def test_window_is_evaluated_in_the_configured_timezone(self) -> None:
        # 12:00 UTC is 08:00 in New York, inside a 7-9 local window.
        assert is_quiet_hour(NOW, 7, 9, "America/New_York") is True
        assert is_quiet_hour(NOW, 7, 9, "UTC") is False

    def test_unknown_timezone_falls_back_to_utc(self) -> None:
        # A bad timezone must not silence alerts; UTC 12:00 is outside 22-6.
        assert is_quiet_hour(NOW, 22, 6, "Not/AZone") is False


class TestThrottle:
    def test_zero_interval_disables_throttling(self) -> None:
        last = {throttle_key("p", "failure"): NOW.isoformat()}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=0,
                last_alert_at=last,
            )
            is None
        )

    def test_alert_inside_window_is_throttled(self) -> None:
        last = {throttle_key("p", "failure"): (NOW - timedelta(minutes=5)).isoformat()}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=last,
            )
            == REASON_THROTTLED
        )

    def test_alert_after_window_is_allowed(self) -> None:
        last = {throttle_key("p", "failure"): (NOW - timedelta(minutes=31)).isoformat()}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=last,
            )
            is None
        )

    def test_throttle_is_scoped_per_pipeline(self) -> None:
        last = {throttle_key("other", "failure"): NOW.isoformat()}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=last,
            )
            is None
        )

    def test_throttle_is_scoped_per_kind(self) -> None:
        last = {throttle_key("p", "success"): NOW.isoformat()}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=last,
            )
            is None
        )

    def test_missing_bookkeeping_allows_the_first_alert(self) -> None:
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=None,
            )
            is None
        )

    def test_unparseable_timestamp_allows_the_alert(self) -> None:
        last = {throttle_key("p", "failure"): "not-a-date"}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=last,
            )
            is None
        )

    def test_naive_timestamp_is_treated_as_utc(self) -> None:
        naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
        last = {throttle_key("p", "failure"): naive.isoformat()}
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=30,
                last_alert_at=last,
            )
            == REASON_THROTTLED
        )


class TestQuietHoursSuppression:
    def test_success_is_held_during_quiet_hours(self) -> None:
        assert (
            should_suppress(
                kind="success",
                pipeline_name="p",
                now=NOW.replace(hour=23),
                min_interval_minutes=0,
                last_alert_at={},
                quiet_hours_start=22,
                quiet_hours_end=6,
            )
            == REASON_QUIET_HOURS
        )

    def test_failure_passes_quiet_hours_by_default(self) -> None:
        assert (
            should_suppress(
                kind="failure",
                pipeline_name="p",
                now=NOW.replace(hour=23),
                min_interval_minutes=0,
                last_alert_at={},
                quiet_hours_start=22,
                quiet_hours_end=6,
            )
            is None
        )

    def test_failure_is_held_when_explicitly_included(self) -> None:
        reason = should_suppress(
            kind="failure",
            pipeline_name="p",
            now=NOW.replace(hour=23),
            min_interval_minutes=0,
            last_alert_at={},
            quiet_hours_start=22,
            quiet_hours_end=6,
            quiet_hours_include_failures=True,
        )
        assert reason == REASON_QUIET_HOURS

    def test_quiet_hours_take_precedence_over_throttle(self) -> None:
        # A held alert must not consume the throttle window, or the first alert
        # after quiet hours end would itself be throttled away.
        last = {throttle_key("p", "success"): (NOW - timedelta(minutes=1)).isoformat()}
        reason = should_suppress(
            kind="success",
            pipeline_name="p",
            now=NOW.replace(hour=23),
            min_interval_minutes=30,
            last_alert_at=last,
            quiet_hours_start=22,
            quiet_hours_end=6,
        )
        assert reason == REASON_QUIET_HOURS

    def test_outside_quiet_hours_the_throttle_still_applies(self) -> None:
        last = {throttle_key("p", "success"): (NOW - timedelta(minutes=1)).isoformat()}
        reason = should_suppress(
            kind="success",
            pipeline_name="p",
            now=NOW.replace(hour=12),
            min_interval_minutes=30,
            last_alert_at=last,
            quiet_hours_start=22,
            quiet_hours_end=6,
        )
        assert reason == REASON_THROTTLED

    def test_nothing_configured_allows_the_alert(self) -> None:
        assert (
            should_suppress(
                kind="success",
                pipeline_name="p",
                now=NOW,
                min_interval_minutes=0,
                last_alert_at={},
            )
            is None
        )
