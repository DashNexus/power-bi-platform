"""Tests for the five-field cron matcher used by export schedules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services import cron

# 2026-08-19 is a Wednesday (cron day-of-week 3).
WED_0600 = datetime(2026, 8, 19, 6, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("expression", "moment", "expected"),
    [
        ("* * * * *", WED_0600, True),
        ("0 6 * * *", WED_0600, True),
        ("0 6 * * *", WED_0600.replace(hour=7), False),
        ("0 6 * * 3", WED_0600, True),
        ("0 6 * * 1", WED_0600, False),
        ("*/15 * * * *", WED_0600.replace(minute=15), True),
        ("*/15 * * * *", WED_0600.replace(minute=16), False),
        ("0,30 * * * *", WED_0600.replace(minute=30), True),
        ("0 9-17 * * *", WED_0600.replace(hour=13), True),
        ("0 9-17 * * *", WED_0600.replace(hour=18), False),
        ("0 6 19 8 *", WED_0600, True),
        ("0 6 * aug *", WED_0600, True),
        ("0 6 * * wed", WED_0600, True),
        # Sunday is 0 or 7; 2026-08-23 is a Sunday.
        ("0 6 * * 7", datetime(2026, 8, 23, 6, 0, tzinfo=UTC), True),
        ("0 6 * * 0", datetime(2026, 8, 23, 6, 0, tzinfo=UTC), True),
    ],
)
def test_matches(expression: str, moment: datetime, expected: bool) -> None:
    assert cron.parse(expression).matches(moment) is expected


def test_day_of_month_and_day_of_week_are_a_union_not_an_intersection() -> None:
    # Standard cron: with both fields restricted, either one firing is enough.
    schedule = cron.parse("0 6 1 * 3")

    assert schedule.matches(WED_0600) is True  # a Wednesday, but the 19th
    assert schedule.matches(datetime(2026, 9, 1, 6, 0, tzinfo=UTC)) is True  # the 1st, a Tuesday
    assert schedule.matches(datetime(2026, 9, 3, 6, 0, tzinfo=UTC)) is False  # Thursday the 3rd


@pytest.mark.parametrize(
    "expression",
    ["", "* * * *", "* * * * * *", "61 * * * *", "* 24 * * *", "* * 0 * *", "* * * 13 *",
     "abc * * * *", "5-1 * * * *", "*/0 * * * *", "* * * * 8"],
)
def test_parse_rejects_malformed_expressions(expression: str) -> None:
    with pytest.raises(cron.CronError):
        cron.parse(expression)

    assert cron.is_valid(expression) is False


def test_error_message_names_the_field() -> None:
    with pytest.raises(cron.CronError) as exc:
        cron.parse("* 24 * * *")

    assert "hour" in str(exc.value)


def test_next_run_after_returns_the_following_slot() -> None:
    nxt = cron.parse("0 6 * * *").next_run_after(WED_0600)

    assert nxt == WED_0600 + timedelta(days=1)


def test_next_run_after_returns_none_for_an_unreachable_expression() -> None:
    # 30 February never happens.
    assert cron.parse("0 0 30 2 *").next_run_after(WED_0600) is None


def test_is_due_when_the_expression_matches_now() -> None:
    assert cron.is_due("0 6 * * *", now=WED_0600, last_run_at=None) is True


def test_is_due_is_false_for_a_new_schedule_that_does_not_match_now() -> None:
    # A schedule enabled at an off-minute waits for its slot rather than
    # backfilling every slot since it was created.
    assert cron.is_due("0 6 * * *", now=WED_0600.replace(hour=9), last_run_at=None) is False


def test_is_due_catches_up_a_slot_the_worker_was_down_for() -> None:
    # Last ran yesterday at 06:00; the worker was down over this morning's slot
    # and is asking at 06:05.
    assert (
        cron.is_due(
            "0 6 * * *",
            now=WED_0600 + timedelta(minutes=5),
            last_run_at=WED_0600 - timedelta(days=1),
        )
        is True
    )


def test_is_due_is_false_when_no_slot_fell_since_the_last_run() -> None:
    assert (
        cron.is_due(
            "0 6 * * *",
            now=WED_0600 + timedelta(hours=3),
            last_run_at=WED_0600,
        )
        is False
    )


def test_is_due_does_not_fire_a_burst_after_a_long_outage() -> None:
    # Down for a month, then asked at a non-matching minute: the catch-up window
    # is capped at a day, so this is a single missed slot, not thirty.
    now = WED_0600.replace(hour=6, minute=30)
    assert cron.is_due("0 6 * * *", now=now, last_run_at=WED_0600 - timedelta(days=30)) is True

