"""Suppression rules that decide whether a pipeline run alert may be sent.

Two independent guards, both aimed at the same failure mode: a flapping or
high-frequency pipeline turning a Slack channel into noise until people mute it.

    throttle — at most one alert per (pipeline, outcome) per
        ``min_interval_minutes``. 0 disables it.
    quiet hours — a wall-clock window in the config's timezone during which
        alerts are held. Failures pass through by default, because an outage
        usually outranks the on-call schedule; set
        ``quiet_hours_include_failures`` to silence those too.

Kept separate from the poller so the decision is unit-testable without a
database, a provider, or a clock patch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger(__name__)

# Reasons returned to the caller (and surfaced in the poller logs).
REASON_THROTTLED = "throttled"
REASON_QUIET_HOURS = "quiet_hours"


def throttle_key(pipeline_name: str, kind: str) -> str:
    """Bookkeeping key for one pipeline's outcome stream."""
    return f"{pipeline_name}|{kind}"


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        # A bad timezone must not silence alerts, so fall back to UTC.
        logger.warning("alert_suppression.bad_timezone", tz=tz_name)
        return ZoneInfo("UTC")


def is_quiet_hour(
    now: datetime,
    start: int | None,
    end: int | None,
    tz_name: str | None = "UTC",
) -> bool:
    """Return whether ``now`` falls inside the quiet-hours window.

    The window is [start, end) on the hour. A window where start > end wraps
    midnight (22 → 6 means 22:00-05:59). start == end is treated as "no window"
    rather than "always quiet", so a mis-set pair can never mute everything.
    """
    if start is None or end is None:
        return False
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return False
    hour = now.astimezone(_zone(tz_name)).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def should_suppress(
    *,
    kind: str,
    pipeline_name: str,
    now: datetime,
    min_interval_minutes: int,
    last_alert_at: dict[str, str] | None,
    quiet_hours_start: int | None = None,
    quiet_hours_end: int | None = None,
    quiet_hours_tz: str | None = "UTC",
    quiet_hours_include_failures: bool = False,
) -> str | None:
    """Return a suppression reason, or None when the alert may be sent.

    Quiet hours are evaluated before the throttle: a held alert must not consume
    the throttle window, or the first alert after quiet hours end would itself be
    throttled away.
    """
    if is_quiet_hour(now, quiet_hours_start, quiet_hours_end, quiet_hours_tz):
        if kind != "failure" or quiet_hours_include_failures:
            return REASON_QUIET_HOURS

    if min_interval_minutes > 0:
        previous = _parse_iso((last_alert_at or {}).get(throttle_key(pipeline_name, kind)))
        if previous is not None and now - previous < timedelta(minutes=min_interval_minutes):
            return REASON_THROTTLED

    return None
