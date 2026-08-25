"""Minimal five-field cron parsing for export schedules.

Only what a schedule needs: decide whether a cron expression is due at a given
minute. Deliberately not a dependency — the expressions this accepts are the
standard five fields with ``*``, lists, ranges and steps, which is the whole of
what the schedule editor offers.

Day-of-month and day-of-week follow the usual cron rule: when both are
restricted the match is a union, not an intersection, so ``0 0 1 * 1`` fires on
the 1st *and* on every Monday.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# (min, max) for minute, hour, day-of-month, month, day-of-week.
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_FIELD_NAMES = ("minute", "hour", "day of month", "month", "day of week")

_MONTH_ALIASES = {
    name: i
    for i, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
_DOW_ALIASES = {
    name: i for i, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))
}

# How far ahead next_run_after will search before giving up. Four years covers
# the sparsest sane expression (29 February) with room to spare.
_MAX_LOOKAHEAD_MINUTES = 366 * 4 * 24 * 60

# How far back is_due will look for a slot the worker was down for. A day is
# long enough to cover a restart or a deploy, and short enough that a schedule
# resumed after a week does not fire a burst of catch-up runs.
_CATCHUP_MINUTES = 24 * 60


class CronError(ValueError):
    """Raised when a cron expression cannot be parsed."""


def _alias(token: str, index: int) -> str:
    """Resolve a month or weekday name to its number, leaving digits alone."""
    lowered = token.lower()
    if index == 3 and lowered in _MONTH_ALIASES:
        return str(_MONTH_ALIASES[lowered])
    if index == 4 and lowered in _DOW_ALIASES:
        return str(_DOW_ALIASES[lowered])
    return token


def _parse_field(raw: str, index: int) -> frozenset[int]:
    """Expand one cron field into the set of values it matches."""
    low, high = _FIELD_RANGES[index]
    values: set[int] = set()

    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"Empty value in the {_FIELD_NAMES[index]} field.")

        step = 1
        if "/" in part:
            part, _, step_raw = part.partition("/")
            if not step_raw.isdigit() or int(step_raw) == 0:
                raise CronError(f"Invalid step '/{step_raw}' in the {_FIELD_NAMES[index]} field.")
            step = int(step_raw)

        if part in ("*", ""):
            start, end = low, high
        elif "-" in part.lstrip("-"):
            start_raw, _, end_raw = part.partition("-")
            start, end = _to_int(start_raw, index), _to_int(end_raw, index)
        else:
            start = end = _to_int(part, index)
            if step > 1:
                # `5/15` is cron shorthand for "from 5 to the top of the range".
                end = high

        if start > end:
            raise CronError(f"Range {start}-{end} is backwards in the {_FIELD_NAMES[index]} field.")
        values.update(range(start, end + 1, step))

    # Cron accepts 7 for Sunday; normalise so matching only ever sees 0-6.
    if index == 4 and 7 in values:
        values.discard(7)
        values.add(0)

    out_of_range = sorted(v for v in values if not low <= v <= high)
    if out_of_range:
        raise CronError(
            f"{out_of_range[0]} is outside {low}-{high} in the {_FIELD_NAMES[index]} field."
        )
    return frozenset(values)


def _to_int(token: str, index: int) -> int:
    resolved = _alias(token.strip(), index)
    # Sunday is 7 in some dialects; _parse_field folds it to 0 afterwards.
    if index == 4 and resolved == "7":
        return 7
    if not resolved.lstrip("-").isdigit():
        raise CronError(f"'{token.strip()}' is not a number in the {_FIELD_NAMES[index]} field.")
    return int(resolved)


class CronSchedule:
    """A parsed five-field cron expression."""

    __slots__ = ("expression", "_fields")

    def __init__(self, expression: str) -> None:
        parts = expression.split()
        if len(parts) != 5:
            raise CronError(
                f"A cron expression has five fields "
                f"(minute hour day-of-month month day-of-week); got {len(parts)}."
            )
        self.expression = expression
        self._fields = tuple(_parse_field(p, i) for i, p in enumerate(parts))

    def matches(self, moment: datetime) -> bool:
        """Return True if the expression fires during the given minute."""
        minute, hour, dom, month, dow = self._fields
        # Python's Monday=0 differs from cron's Sunday=0.
        weekday = (moment.weekday() + 1) % 7

        if moment.minute not in minute or moment.hour not in hour or moment.month not in month:
            return False

        dom_restricted = len(dom) < 31
        dow_restricted = len(dow) < 7
        if dom_restricted and dow_restricted:
            return moment.day in dom or weekday in dow
        return (moment.day in dom) and (weekday in dow)

    def next_run_after(self, after: datetime) -> datetime | None:
        """Return the first firing strictly after `after`, or None if unreachable.

        Searched minute by minute rather than solved, because a schedule is
        evaluated at most once a minute and an expression that fires at all
        fires within the lookahead.
        """
        moment = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(_MAX_LOOKAHEAD_MINUTES):
            if self.matches(moment):
                return moment
            moment += timedelta(minutes=1)
        return None


def parse(expression: str) -> CronSchedule:
    """Parse a cron expression, raising CronError if it is malformed."""
    return CronSchedule(expression)


def is_valid(expression: str) -> bool:
    """Return True if the expression parses."""
    try:
        parse(expression)
    except CronError:
        return False
    return True


def is_due(expression: str, *, now: datetime, last_run_at: datetime | None) -> bool:
    """Return True if a schedule should fire at `now`.

    A schedule that has never run fires at its next matching minute rather than
    immediately, so enabling one does not trigger a backfill of every slot since
    it was created.

    Once it has run, a firing that fell between the last run and now also counts
    — that is what lets a schedule survive a worker restart that spanned its
    slot. The catch-up window is capped (see _CATCHUP_MINUTES) so that a sparse
    expression such as "29 February" costs a bounded scan each tick rather than
    four years of minutes.
    """
    schedule = parse(expression)
    now = now.astimezone(UTC).replace(second=0, microsecond=0)

    if schedule.matches(now):
        return True
    if last_run_at is None:
        return False

    moment = last_run_at.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    earliest = now - timedelta(minutes=_CATCHUP_MINUTES)
    if moment < earliest:
        moment = earliest
    while moment < now:
        if schedule.matches(moment):
            return True
        moment += timedelta(minutes=1)
    return False
