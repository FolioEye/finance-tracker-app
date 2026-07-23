"""Unit tests for the Subscription domain model + detect_pattern() clustering
engine (FINTRACK-18). Pure domain-layer tests -- no DB, no HTTP, no auth.
See tests/integration/test_subscriptions_api.py for the real-API-level
equivalents and tests/security/test_subscriptions_security.py for the
mandatory security sweep. Structure mirrors
tests/unit/test_alert_domain.py.

Every scenario in tests/features/FINTRACK-18-subscription-detection.feature
is covered here at the pure-function level (detect_pattern is exactly the
function the Gherkin's "When subscription detection runs" step exercises),
plus boundary gap-fill the Gherkin doesn't spell out: exact tolerance/
interval edges, and the AC5 terminal-status contract.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from apps.api.domain.models.subscription import (
    AMOUNT_TOLERANCE_PCT,
    INTERVAL_TARGET_DAYS,
    INTERVAL_TOLERANCE_DAYS,
    MIN_OCCURRENCES,
    TERMINAL_STATUSES,
    Subscription,
    SubscriptionStatus,
    _Occurrence,
    detect_pattern,
    normalise_merchant,
)


def _occ(amount: str, d: date, txn_id=None) -> _Occurrence:
    return _Occurrence(amount=Decimal(amount), transaction_date=d, transaction_id=txn_id or uuid.uuid4())


# ---------------------------------------------------------------------------
# normalise_merchant
# ---------------------------------------------------------------------------


def test_normalise_merchant_upper_cases_and_strips() -> None:
    assert normalise_merchant("  Netflix.com  ") == "NETFLIX.COM"


def test_normalise_merchant_treats_differently_padded_same_merchant_as_equal() -> None:
    assert normalise_merchant("netflix.com") == normalise_merchant("NETFLIX.COM   ")


# ---------------------------------------------------------------------------
# detect_pattern -- Gherkin Scenario 1: three monthly NETFLIX.COM charges
# ---------------------------------------------------------------------------


def test_three_monthly_charges_same_amount_are_flagged() -> None:
    base = date(2026, 1, 1)
    occurrences = [
        _occ("15.99", base),
        _occ("15.99", base + timedelta(days=30)),
        _occ("15.99", base + timedelta(days=60)),
    ]
    result = detect_pattern(occurrences)
    assert result is not None
    amount_estimate, interval_days = result
    assert amount_estimate == Decimal("15.99")
    assert interval_days == INTERVAL_TARGET_DAYS


# ---------------------------------------------------------------------------
# detect_pattern -- Gherkin Scenario 2: two irregular AMAZON charges
# ---------------------------------------------------------------------------


def test_two_irregular_charges_are_not_flagged_below_min_occurrences() -> None:
    """AC2: fewer than MIN_OCCURRENCES is an automatic None regardless of
    amount/interval shape -- matches the Gherkin's own two-transaction
    negative example."""
    assert MIN_OCCURRENCES == 3
    occurrences = [
        _occ("42.10", date(2026, 1, 5)),
        _occ("9.99", date(2026, 3, 20)),
    ]
    assert detect_pattern(occurrences) is None


# ---------------------------------------------------------------------------
# detect_pattern -- Gherkin Scenario 3: ELECTRIC CO, amount varies within
# tolerance
# ---------------------------------------------------------------------------


def test_three_monthly_charges_with_amount_variance_within_tolerance_are_flagged() -> None:
    base = date(2026, 1, 1)
    occurrences = [
        _occ("84.50", base),
        _occ("91.20", base + timedelta(days=30)),
        _occ("88.00", base + timedelta(days=60)),
    ]
    result = detect_pattern(occurrences)
    assert result is not None
    amount_estimate, interval_days = result
    assert amount_estimate == Decimal("87.90")
    assert interval_days == INTERVAL_TARGET_DAYS


# ---------------------------------------------------------------------------
# detect_pattern -- amount tolerance boundary (AMOUNT_TOLERANCE_PCT = 15)
# ---------------------------------------------------------------------------


def test_amount_deviation_well_within_tolerance_is_flagged() -> None:
    assert AMOUNT_TOLERANCE_PCT == Decimal("15")
    base = date(2026, 1, 1)
    occurrences = [
        _occ("100.00", base),
        _occ("100.00", base + timedelta(days=30)),
        _occ("115.00", base + timedelta(days=60)),
    ]
    # avg = 315/3 = 105; deviation of 115 from 105 = 9.52% -- inside tolerance.
    assert detect_pattern(occurrences) is not None


def test_amount_deviation_over_tolerance_is_not_flagged() -> None:
    base = date(2026, 1, 1)
    # avg = (100+100+130)/3 = 110; deviation of 130 from 110 = 18.18% > 15%
    occurrences = [
        _occ("100.00", base),
        _occ("100.00", base + timedelta(days=30)),
        _occ("130.00", base + timedelta(days=60)),
    ]
    assert detect_pattern(occurrences) is None


# ---------------------------------------------------------------------------
# detect_pattern -- interval tolerance boundary (target=30, tolerance=7)
# ---------------------------------------------------------------------------


def test_interval_exactly_at_tolerance_boundary_is_flagged() -> None:
    """Average gap of exactly 37 days (30 + 7) must still pass -- the
    domain's check is `> INTERVAL_TOLERANCE_DAYS` from target."""
    assert INTERVAL_TARGET_DAYS == 30
    assert INTERVAL_TOLERANCE_DAYS == 7
    base = date(2026, 1, 1)
    occurrences = [
        _occ("20.00", base),
        _occ("20.00", base + timedelta(days=37)),
        _occ("20.00", base + timedelta(days=74)),
    ]
    result = detect_pattern(occurrences)
    assert result is not None
    assert result[1] == 37


def test_interval_just_outside_tolerance_is_not_flagged() -> None:
    base = date(2026, 1, 1)
    occurrences = [
        _occ("20.00", base),
        _occ("20.00", base + timedelta(days=45)),
        _occ("20.00", base + timedelta(days=90)),
    ]
    assert detect_pattern(occurrences) is None


def test_interval_much_shorter_than_target_is_not_flagged() -> None:
    """Weekly charges (7-day gaps) are not a monthly subscription pattern
    under this v1 rules engine -- explicitly out of scope per the story's
    'Out of scope' note (only monthly cadence is detected)."""
    base = date(2026, 1, 1)
    occurrences = [
        _occ("20.00", base),
        _occ("20.00", base + timedelta(days=7)),
        _occ("20.00", base + timedelta(days=14)),
    ]
    assert detect_pattern(occurrences) is None


# ---------------------------------------------------------------------------
# detect_pattern -- unsorted input, order independence
# ---------------------------------------------------------------------------


def test_detect_pattern_sorts_occurrences_before_computing_gaps() -> None:
    """Callers (the handler) don't guarantee ordering -- detect_pattern
    must sort by transaction_date itself rather than trusting input order,
    since an out-of-order gap gives a nonsensical (or negative) interval."""
    base = date(2026, 1, 1)
    occurrences = [
        _occ("15.99", base + timedelta(days=60)),
        _occ("15.99", base),
        _occ("15.99", base + timedelta(days=30)),
    ]
    result = detect_pattern(occurrences)
    assert result is not None
    assert result[1] == INTERVAL_TARGET_DAYS


# ---------------------------------------------------------------------------
# Subscription.new_detected / refresh_stats
# ---------------------------------------------------------------------------


def test_new_detected_sets_status_detected() -> None:
    sub = Subscription.new_detected(
        user_id=uuid.uuid4(), merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    assert sub.status == SubscriptionStatus.DETECTED
    assert sub.first_detected_at == sub.last_seen_at == sub.updated_at


def test_refresh_stats_updates_fields_but_never_touches_status() -> None:
    """A CONFIRMED subscription must stay CONFIRMED as its estimate
    sharpens on re-detection; a DETECTED one stays DETECTED. Status is
    exclusively the caller's (handler's) concern -- this documents that
    refresh_stats itself has no opinion on status at all."""
    sub = Subscription.new_detected(
        user_id=uuid.uuid4(), merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    sub.confirm()
    assert sub.status == SubscriptionStatus.CONFIRMED

    new_last_txn = uuid.uuid4()
    sub.refresh_stats(amount_estimate=Decimal("16.99"), interval_days=31, occurrences=4, last_transaction_id=new_last_txn)
    assert sub.status == SubscriptionStatus.CONFIRMED  # untouched
    assert sub.amount_estimate == Decimal("16.99")
    assert sub.interval_days == 31
    assert sub.occurrences == 4
    assert sub.last_transaction_id == new_last_txn


# ---------------------------------------------------------------------------
# confirm / dismiss / mark_not_subscription -- AC3, AC5
# ---------------------------------------------------------------------------


def test_confirm_sets_status_confirmed() -> None:
    sub = Subscription.new_detected(
        user_id=uuid.uuid4(), merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    sub.confirm()
    assert sub.status == SubscriptionStatus.CONFIRMED


def test_dismiss_sets_status_dismissed() -> None:
    sub = Subscription.new_detected(
        user_id=uuid.uuid4(), merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    sub.dismiss()
    assert sub.status == SubscriptionStatus.DISMISSED


def test_mark_not_subscription_sets_status_not_subscription() -> None:
    sub = Subscription.new_detected(
        user_id=uuid.uuid4(), merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    sub.mark_not_subscription()
    assert sub.status == SubscriptionStatus.NOT_SUBSCRIPTION


def test_terminal_statuses_contains_exactly_dismissed_and_not_subscription() -> None:
    """AC5's 'dismissed pattern not re-suggested' guarantee is enforced by
    the handler checking membership in this set -- this pins down exactly
    which statuses count as terminal so that contract can't silently
    drift (e.g. someone adding CONFIRMED here by mistake would stop
    re-detection from ever refining a confirmed subscription's stats)."""
    assert TERMINAL_STATUSES == frozenset({SubscriptionStatus.DISMISSED, SubscriptionStatus.NOT_SUBSCRIPTION})
    assert SubscriptionStatus.CONFIRMED not in TERMINAL_STATUSES
    assert SubscriptionStatus.DETECTED not in TERMINAL_STATUSES
