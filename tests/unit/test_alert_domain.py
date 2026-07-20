"""Unit tests for the Alert domain model (FINTRACK-22):
Alert.new_threshold_crossing, Alert.new_large_transaction, and
Alert.dismiss. Pure domain-layer tests -- no DB, no HTTP, no auth. See
tests/integration/test_alerts_api.py for the real-API-level equivalents
and tests/security/test_alerts_security.py for the mandatory security
sweep.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from apps.api.domain.models.alert import Alert, AlertType

# ---------------------------------------------------------------------------
# Alert.new_threshold_crossing -- AC1
# ---------------------------------------------------------------------------


def test_new_threshold_crossing_sets_all_fields() -> None:
    user_id = uuid.uuid4()
    period_start = date(2026, 7, 1)
    alert = Alert.new_threshold_crossing(
        user_id=user_id, category="Groceries", threshold_pct=Decimal("90.00"), period_start=period_start
    )
    assert alert.user_id == user_id
    assert alert.category == "Groceries"
    assert alert.alert_type == AlertType.THRESHOLD_CROSSING
    assert alert.threshold_pct == Decimal("90.00")
    assert alert.period_start == period_start
    assert isinstance(alert.id, uuid.UUID)
    assert alert.dismissed_at is None


def test_new_threshold_crossing_leaves_transaction_id_none() -> None:
    """A THRESHOLD_CROSSING alert isn't tied to one specific transaction --
    transaction_id must stay None so the (user, category, alert_type,
    period_start, threshold_pct) unique constraint is the only thing that
    can dedupe it, per ADR-014 decision B."""
    alert = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    assert alert.transaction_id is None


def test_new_threshold_crossing_sets_fired_at_to_now() -> None:
    before = datetime.now(timezone.utc)
    alert = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    after = datetime.now(timezone.utc)
    assert before <= alert.fired_at <= after


def test_two_threshold_crossing_alerts_get_different_ids() -> None:
    alert_a = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    alert_b = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    assert alert_a.id != alert_b.id


# ---------------------------------------------------------------------------
# Alert.new_large_transaction -- AC2
# ---------------------------------------------------------------------------


def test_new_large_transaction_sets_all_fields() -> None:
    user_id = uuid.uuid4()
    transaction_id = uuid.uuid4()
    period_start = date(2026, 7, 1)
    alert = Alert.new_large_transaction(
        user_id=user_id, category="Dining", transaction_id=transaction_id, period_start=period_start
    )
    assert alert.user_id == user_id
    assert alert.category == "Dining"
    assert alert.alert_type == AlertType.LARGE_TRANSACTION
    assert alert.transaction_id == transaction_id
    assert alert.period_start == period_start
    assert alert.dismissed_at is None


def test_new_large_transaction_leaves_threshold_pct_none() -> None:
    """A LARGE_TRANSACTION alert has no threshold percentage -- it's
    keyed by transaction_id alone, per ADR-014 decision B."""
    alert = Alert.new_large_transaction(
        user_id=uuid.uuid4(), category="Dining", transaction_id=uuid.uuid4(), period_start=date(2026, 7, 1)
    )
    assert alert.threshold_pct is None


def test_alert_type_enum_values_match_db_storage_strings() -> None:
    """AlertType is a str Enum specifically so .value round-trips exactly
    with what's stored in AlertModel.alert_type (a plain String column) --
    a mismatch here would silently break find_active_threshold_crossing's
    equality filter."""
    assert AlertType.THRESHOLD_CROSSING.value == "THRESHOLD_CROSSING"
    assert AlertType.LARGE_TRANSACTION.value == "LARGE_TRANSACTION"


# ---------------------------------------------------------------------------
# Alert.dismiss -- AC4
# ---------------------------------------------------------------------------


def test_dismiss_sets_dismissed_at() -> None:
    alert = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    assert alert.dismissed_at is None
    alert.dismiss()
    assert alert.dismissed_at is not None


def test_dismiss_does_not_change_any_other_field() -> None:
    """AC4: dismissing must have no effect on whether future alerts fire --
    at the domain level, that means dismiss() touches dismissed_at and
    nothing else (no category/threshold/period mutation that could
    accidentally change how a future dedup lookup matches this row)."""
    alert = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    original_id, original_category, original_type = alert.id, alert.category, alert.alert_type
    original_period, original_threshold = alert.period_start, alert.threshold_pct
    alert.dismiss()
    assert alert.id == original_id
    assert alert.category == original_category
    assert alert.alert_type == original_type
    assert alert.period_start == original_period
    assert alert.threshold_pct == original_threshold


def test_dismiss_can_be_called_again_and_updates_the_timestamp() -> None:
    """The domain method itself is not idempotency-guarded -- that's
    DismissAlertHandler's job (only calls dismiss() once, guarded by
    `if alert.dismissed_at is None`). At the pure domain level, calling
    dismiss() twice just re-stamps the time; this documents that
    boundary rather than asserting a domain-level guard that doesn't
    exist."""
    alert = Alert.new_threshold_crossing(
        user_id=uuid.uuid4(), category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    alert.dismiss()
    first_dismissed_at = alert.dismissed_at
    alert.dismiss()
    assert alert.dismissed_at >= first_dismissed_at
