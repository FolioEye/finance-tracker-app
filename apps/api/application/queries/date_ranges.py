"""Shared calendar-month bounds helpers for read-side aggregation queries.

New for FINTRACK-19. Deliberately NOT a refactor of
get_budget_overview.py's existing private `_current_month_bounds` --
that file already shipped as part of FINTRACK-20; touching it here would
put an already-released story back in scope for no behavioural gain.
This module exists so this story (and any future one needing month
bucketing) doesn't duplicate the same off-by-one-prone year-rollover
arithmetic ad hoc.
"""
from __future__ import annotations

from datetime import date as date_type


def current_month_bounds(today: date_type) -> tuple[date_type, date_type]:
    """[start, end) -- start is the 1st of the current month, end is the
    1st of the following month (exclusive)."""
    start = today.replace(day=1)
    return start, shift_month(start, 1)


def shift_month(d: date_type, delta: int) -> date_type:
    """Returns the 1st of the month `delta` months away from `d` (whose
    own day-of-month is ignored). Pure integer arithmetic over a
    zero-based (year*12 + month) index -- avoids relative-delta
    dependencies and handles year rollover in both directions the same
    way `_current_month_bounds` in get_budget_overview.py already does
    for a single-month step.
    """
    total = (d.year * 12 + (d.month - 1)) + delta
    year, month0 = divmod(total, 12)
    return d.replace(year=year, month=month0 + 1, day=1)


def trailing_months_bounds(today: date_type, months: int) -> tuple[date_type, date_type]:
    """[start, end) spanning the last `months` calendar months INCLUDING
    the current one -- e.g. months=6 on 2026-07-24 returns
    (2026-02-01, 2026-08-01), covering Feb through Jul inclusive.
    """
    current_start = today.replace(day=1)
    start = shift_month(current_start, -(months - 1))
    end = shift_month(current_start, 1)
    return start, end


def month_sequence(start: date_type, end: date_type) -> list[tuple[int, int]]:
    """All (year, month) pairs in [start, end), in chronological order --
    used so the trend response has no gaps for months with zero spend."""
    months: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        months.append((cursor.year, cursor.month))
        cursor = shift_month(cursor, 1)
    return months
