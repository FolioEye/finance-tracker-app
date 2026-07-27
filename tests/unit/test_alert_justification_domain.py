"""Unit tests for the AlertJustification domain model (FINTRACK-25,
AC1/AC2). Pure domain-layer tests -- no DB, no HTTP, no auth. Mirrors the
structure of tests/unit/test_alert_domain.py.

See tests/unit/test_alert_handlers.py for JustifyAlertHandler and the
EvaluateAlertsForTransactionHandler ceiling-suppression tests, and
tests/integration/test_alerts_api.py / tests/security/test_alerts_security.py
for the real-API-level equivalents.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from apps.api.domain.models.alert_justification import AlertJustification


# ---------------------------------------------------------------------------
# AlertJustification.new -- AC2
# ---------------------------------------------------------------------------


def test_new_sets_ceiling_to_the_given_amount() -> None:
    user_id = uuid.uuid4()
    justification = AlertJustification.new(user_id=user_id, category="Travel", ceiling_amount=Decimal("900.00"))
    assert justification.user_id == user_id
    assert justification.category == "Travel"
    assert justification.ceiling_amount == Decimal("900.00")
    assert isinstance(justification.id, uuid.UUID)


def test_new_sets_created_at_and_updated_at_to_now_and_equal() -> None:
    before = datetime.now(timezone.utc)
    justification = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    after = datetime.now(timezone.utc)
    assert before <= justification.created_at <= after
    assert justification.created_at == justification.updated_at


def test_two_justifications_get_different_ids() -> None:
    a = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    b = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    assert a.id != b.id


# ---------------------------------------------------------------------------
# AlertJustification.raise_ceiling_if_higher -- AC2 ("is not lowered")
# ---------------------------------------------------------------------------


def test_raise_ceiling_if_higher_raises_and_returns_true_when_amount_is_higher() -> None:
    justification = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    changed = justification.raise_ceiling_if_higher(Decimal("1500.00"))
    assert changed is True
    assert justification.ceiling_amount == Decimal("1500.00")


def test_raise_ceiling_if_higher_is_a_no_op_and_returns_false_when_amount_is_lower() -> None:
    justification = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    changed = justification.raise_ceiling_if_higher(Decimal("500.00"))
    assert changed is False
    assert justification.ceiling_amount == Decimal("900.00")


def test_raise_ceiling_if_higher_is_a_no_op_and_returns_false_when_amount_equals_the_current_ceiling() -> None:
    """AC2's "is not lowered" also means an equal amount doesn't need a
    write -- strictly-greater-than is the only case that changes state."""
    justification = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    changed = justification.raise_ceiling_if_higher(Decimal("900.00"))
    assert changed is False
    assert justification.ceiling_amount == Decimal("900.00")


def test_raise_ceiling_if_higher_updates_updated_at_only_when_it_actually_changes() -> None:
    justification = AlertJustification.new(user_id=uuid.uuid4(), category="Travel", ceiling_amount=Decimal("900.00"))
    original_updated_at = justification.updated_at

    justification.raise_ceiling_if_higher(Decimal("500.00"))  # no-op
    assert justification.updated_at == original_updated_at

    justification.raise_ceiling_if_higher(Decimal("1500.00"))  # real raise
    assert justification.updated_at >= original_updated_at
