"""QA Lead unit suite -- FollowThroughRecord domain entity. Story:
FINTRACK-23. Pure domain logic, no I/O, no fakes needed.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from apps.api.domain.models.follow_through_record import (
    FollowThroughRecord,
    FollowThroughStatus,
)


def _new_record(period_start: date) -> FollowThroughRecord:
    return FollowThroughRecord.new_pending(
        user_id=uuid.uuid4(), period_start=period_start, recommendation_type="BUDGET_RISK"
    )


def test_new_pending_starts_in_pending_status_with_no_actioned_at() -> None:
    record = _new_record(date(2026, 7, 1))
    assert record.status == FollowThroughStatus.PENDING
    assert record.actioned_at is None
    assert isinstance(record.created_at, datetime)


def test_mark_done_sets_status_and_actioned_at() -> None:
    record = _new_record(date(2026, 7, 1))
    record.mark_done()
    assert record.status == FollowThroughStatus.DONE
    assert record.actioned_at is not None
    assert record.actioned_at.tzinfo is not None


def test_mark_dismissed_sets_status_and_actioned_at() -> None:
    record = _new_record(date(2026, 7, 1))
    record.mark_dismissed()
    assert record.status == FollowThroughStatus.DISMISSED
    assert record.actioned_at is not None


def test_mark_ignored_sets_status_but_does_not_set_actioned_at() -> None:
    """AC4's auto-ignore is a system transition, not a user action --
    actioned_at stays None so a later query can distinguish a real click
    from the automatic timeout."""
    record = _new_record(date(2026, 7, 1))
    record.mark_ignored()
    assert record.status == FollowThroughStatus.IGNORED
    assert record.actioned_at is None


def test_is_overdue_false_for_a_record_created_today() -> None:
    record = _new_record(date(2026, 7, 20))
    assert record.is_overdue(date(2026, 7, 20)) is False


def test_is_overdue_false_at_exactly_seven_days() -> None:
    """Boundary: exactly 7 days elapsed is NOT yet overdue -- the Gherkin
    scenario specifically uses "8 days ago" for the ignored case, so day 7
    itself must still read as within the window."""
    record = _new_record(date(2026, 7, 1))
    assert record.is_overdue(date(2026, 7, 8)) is False


def test_is_overdue_true_at_eight_days() -> None:
    """Matches the Gherkin scenario verbatim: "received a recommendation
    8 days ago and took no action" -> should be auto-ignored."""
    record = _new_record(date(2026, 7, 1))
    assert record.is_overdue(date(2026, 7, 9)) is True


def test_is_overdue_true_well_past_the_window() -> None:
    record = _new_record(date(2026, 6, 1))
    assert record.is_overdue(date(2026, 7, 20)) is True


def test_is_overdue_false_once_already_done_even_if_old() -> None:
    record = _new_record(date(2026, 6, 1))
    record.mark_done()
    assert record.is_overdue(date(2026, 7, 20)) is False


def test_is_overdue_false_once_already_dismissed_even_if_old() -> None:
    record = _new_record(date(2026, 6, 1))
    record.mark_dismissed()
    assert record.is_overdue(date(2026, 7, 20)) is False


def test_is_overdue_false_once_already_ignored_even_if_old() -> None:
    """Reconciliation must be idempotent -- an already-IGNORED record
    should never be re-processed as newly overdue."""
    record = _new_record(date(2026, 6, 1))
    record.mark_ignored()
    assert record.is_overdue(date(2026, 7, 20)) is False


def test_new_pending_generates_a_fresh_uuid_each_call() -> None:
    a = _new_record(date(2026, 7, 1))
    b = _new_record(date(2026, 7, 1))
    assert a.id != b.id
