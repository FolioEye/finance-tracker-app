"""Unit tests for the date_ranges helpers (FINTRACK-19). Pure functions,
no fakes/DB needed.
"""
from __future__ import annotations

from datetime import date

from apps.api.application.queries.date_ranges import (
    current_month_bounds,
    month_sequence,
    shift_month,
    trailing_months_bounds,
)


def test_current_month_bounds_mid_month() -> None:
    start, end = current_month_bounds(date(2026, 7, 19))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 8, 1)


def test_current_month_bounds_december_rolls_into_next_january() -> None:
    start, end = current_month_bounds(date(2026, 12, 25))
    assert start == date(2026, 12, 1)
    assert end == date(2027, 1, 1)


def test_shift_month_forward_within_year() -> None:
    assert shift_month(date(2026, 7, 15), 1) == date(2026, 8, 1)


def test_shift_month_forward_across_year_boundary() -> None:
    assert shift_month(date(2026, 12, 15), 1) == date(2027, 1, 1)


def test_shift_month_backward_across_year_boundary() -> None:
    assert shift_month(date(2026, 1, 15), -1) == date(2025, 12, 1)


def test_shift_month_backward_several_months_across_year_boundary() -> None:
    assert shift_month(date(2026, 2, 1), -3) == date(2025, 11, 1)


def test_shift_month_zero_delta_returns_first_of_same_month() -> None:
    assert shift_month(date(2026, 7, 19), 0) == date(2026, 7, 1)


def test_trailing_months_bounds_six_months_including_current() -> None:
    # 2026-07-24 with months=6 -> Feb through Jul inclusive (BA's AC2:
    # "trend view (3-6 months)").
    start, end = trailing_months_bounds(date(2026, 7, 24), months=6)
    assert start == date(2026, 2, 1)
    assert end == date(2026, 8, 1)


def test_trailing_months_bounds_one_month_is_just_the_current_month() -> None:
    start, end = trailing_months_bounds(date(2026, 7, 24), months=1)
    assert start == date(2026, 7, 1)
    assert end == date(2026, 8, 1)


def test_trailing_months_bounds_crosses_year_boundary() -> None:
    # 2026-02-01 with months=6 -> Sep 2025 through Feb 2026 inclusive.
    start, end = trailing_months_bounds(date(2026, 2, 1), months=6)
    assert start == date(2025, 9, 1)
    assert end == date(2026, 3, 1)


def test_month_sequence_is_gap_free_and_chronological() -> None:
    start, end = date(2026, 5, 1), date(2026, 8, 1)
    assert month_sequence(start, end) == [(2026, 5), (2026, 6), (2026, 7)]


def test_month_sequence_across_year_boundary() -> None:
    start, end = date(2025, 11, 1), date(2026, 2, 1)
    assert month_sequence(start, end) == [(2025, 11), (2025, 12), (2026, 1)]


def test_month_sequence_empty_range_returns_empty_list() -> None:
    d = date(2026, 7, 1)
    assert month_sequence(d, d) == []
