"""Unit tests for the alert command/query handlers (FINTRACK-22):
EvaluateAlertsForTransactionHandler, DismissAlertHandler, ListAlertsHandler.
Fake in-memory repositories stand in for the real SQLAlchemy adapters,
same pattern as tests/unit/test_budget_handlers.py's
FakeBudgetRepository/FakeTransactionRepository.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.application.commands.dismiss_alert import DismissAlertCommand, DismissAlertHandler
from apps.api.application.commands.evaluate_alerts_for_transaction import (
    FALLBACK_BASELINE,
    LARGE_TRANSACTION_MULTIPLIER,
    MIN_SAMPLE_SIZE,
    THRESHOLD_PCT,
    EvaluateAlertsForTransactionCommand,
    EvaluateAlertsForTransactionHandler,
)
from apps.api.application.queries.list_alerts import ListAlertsHandler, ListAlertsQuery
from apps.api.domain.models.alert import Alert, AlertType
from apps.api.domain.models.budget import Budget
from apps.api.domain.repositories.alert_repository import AlertNotFoundError


class FakeAlertRepository:
    """In-memory stand-in for SqlAlchemyAlertRepository. Implements the
    full AlertRepository port, including its documented
    None-for-not-found-or-not-yours semantics on get_by_id_for_user.
    """

    def __init__(self) -> None:
        self.alerts: dict[uuid.UUID, Alert] = {}

    async def add(self, alert: Alert) -> None:
        self.alerts[alert.id] = alert

    async def get_by_id_for_user(self, alert_id: uuid.UUID, user_id: uuid.UUID):
        alert = self.alerts.get(alert_id)
        if alert is None or alert.user_id != user_id:
            return None
        return alert

    async def find_active_threshold_crossing(self, user_id, category, period_start, threshold_pct):
        for alert in self.alerts.values():
            if (
                alert.user_id == user_id
                and alert.category == category
                and alert.alert_type == AlertType.THRESHOLD_CROSSING
                and alert.period_start == period_start
                and alert.threshold_pct == threshold_pct
            ):
                return alert
        return None

    async def find_by_transaction_id(self, transaction_id: uuid.UUID):
        for alert in self.alerts.values():
            if alert.transaction_id == transaction_id:
                return alert
        return None

    async def list_for_user(self, user_id: uuid.UUID, include_dismissed: bool = False) -> list[Alert]:
        result = [a for a in self.alerts.values() if a.user_id == user_id]
        if not include_dismissed:
            result = [a for a in result if a.dismissed_at is None]
        return sorted(result, key=lambda a: a.fired_at, reverse=True)

    async def update(self, alert: Alert) -> None:
        self.alerts[alert.id] = alert


class FakeBudgetRepository:
    """Only implements get_by_category_for_user -- the one method
    EvaluateAlertsForTransactionHandler actually calls."""

    def __init__(self) -> None:
        self.budgets: dict[tuple[uuid.UUID, str], Budget] = {}

    def seed(self, user_id: uuid.UUID, category: str, monthly_limit: str) -> None:
        self.budgets[(user_id, category)] = Budget.new(
            user_id=user_id, category=category, monthly_limit_raw=monthly_limit
        )

    async def get_by_category_for_user(self, user_id: uuid.UUID, category: str):
        return self.budgets.get((user_id, category))


class FakeTransactionRepository:
    """Implements only sum_by_category_for_user_in_range and
    get_recent_amounts_for_category -- the two methods
    EvaluateAlertsForTransactionHandler actually calls."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def seed(self, user_id: uuid.UUID, category: str, amount: str, txn_date: date, txn_id=None) -> uuid.UUID:
        txn_id = txn_id or uuid.uuid4()
        self.rows.append(
            {"user_id": user_id, "category": category, "amount": Decimal(amount), "date": txn_date, "id": txn_id}
        )
        return txn_id

    async def sum_by_category_for_user_in_range(self, user_id, start_date, end_date) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for row in self.rows:
            if row["user_id"] != user_id:
                continue
            if not (start_date <= row["date"] < end_date):
                continue
            totals[row["category"]] = totals.get(row["category"], Decimal("0")) + row["amount"]
        return totals

    async def get_recent_amounts_for_category(self, user_id, category, exclude_transaction_id, limit):
        # Most-recently-seeded-first, matching the real adapter's
        # created_at DESC ordering.
        matches = [
            row
            for row in reversed(self.rows)
            if row["user_id"] == user_id and row["category"] == category and row["id"] != exclude_transaction_id
        ]
        return [row["amount"] for row in matches[:limit]]


@pytest.fixture
def alerts() -> FakeAlertRepository:
    return FakeAlertRepository()


@pytest.fixture
def budgets() -> FakeBudgetRepository:
    return FakeBudgetRepository()


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


# ---------------------------------------------------------------------------
# EvaluateAlertsForTransactionHandler -- threshold crossing (AC1/AC5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_threshold_crossing_fires_at_exactly_90_percent(alerts, budgets, transactions) -> None:
    user_id = uuid.uuid4()
    budgets.seed(user_id, "Groceries", "100.00")
    txn_id = transactions.seed(user_id, "Groceries", "90.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=txn_id, category="Groceries",
            amount=Decimal("90.00"), transaction_date=date(2026, 7, 15),
        )
    )
    threshold_alerts = [a for a in fired if a.alert_type == AlertType.THRESHOLD_CROSSING]
    assert len(threshold_alerts) == 1
    assert threshold_alerts[0].threshold_pct == THRESHOLD_PCT


@pytest.mark.asyncio
async def test_threshold_crossing_does_not_fire_below_90_percent(alerts, budgets, transactions) -> None:
    user_id = uuid.uuid4()
    budgets.seed(user_id, "Groceries", "400.00")
    txn_id = transactions.seed(user_id, "Groceries", "120.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=txn_id, category="Groceries",
            amount=Decimal("120.00"), transaction_date=date(2026, 7, 15),
        )
    )
    assert [a for a in fired if a.alert_type == AlertType.THRESHOLD_CROSSING] == []


@pytest.mark.asyncio
async def test_threshold_crossing_does_not_fire_for_an_unbudgeted_category(alerts, budgets, transactions) -> None:
    user_id = uuid.uuid4()
    txn_id = transactions.seed(user_id, "Entertainment", "999.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=txn_id, category="Entertainment",
            amount=Decimal("999.00"), transaction_date=date(2026, 7, 15),
        )
    )
    assert [a for a in fired if a.alert_type == AlertType.THRESHOLD_CROSSING] == []


@pytest.mark.asyncio
async def test_threshold_crossing_fires_only_once_per_period(alerts, budgets, transactions) -> None:
    """AC5: a second transaction that keeps spend above 90% must not
    produce a second alert for the same (user, category, period,
    threshold)."""
    user_id = uuid.uuid4()
    budgets.seed(user_id, "Groceries", "100.00")
    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )

    first_txn = transactions.seed(user_id, "Groceries", "91.00", date(2026, 7, 10))
    await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=first_txn, category="Groceries",
            amount=Decimal("91.00"), transaction_date=date(2026, 7, 10),
        )
    )
    second_txn = transactions.seed(user_id, "Groceries", "5.00", date(2026, 7, 11))
    await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=second_txn, category="Groceries",
            amount=Decimal("5.00"), transaction_date=date(2026, 7, 11),
        )
    )
    all_alerts = await alerts.list_for_user(user_id, include_dismissed=True)
    threshold_alerts = [a for a in all_alerts if a.alert_type == AlertType.THRESHOLD_CROSSING]
    assert len(threshold_alerts) == 1


@pytest.mark.asyncio
async def test_threshold_crossing_fires_again_in_a_new_month(alerts, budgets, transactions) -> None:
    """AC4/ADR-014 decision D: a *different* period's crossing is a new
    event and must still be able to fire, even if last month's alert for
    the same category was never dismissed."""
    user_id = uuid.uuid4()
    budgets.seed(user_id, "Groceries", "100.00")

    july_handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    july_txn = transactions.seed(user_id, "Groceries", "91.00", date(2026, 7, 10))
    await july_handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=july_txn, category="Groceries",
            amount=Decimal("91.00"), transaction_date=date(2026, 7, 10),
        )
    )

    august_handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 8, 5),
    )
    august_txn = transactions.seed(user_id, "Groceries", "95.00", date(2026, 8, 3))
    await august_handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=august_txn, category="Groceries",
            amount=Decimal("95.00"), transaction_date=date(2026, 8, 3),
        )
    )

    all_alerts = await alerts.list_for_user(user_id, include_dismissed=True)
    threshold_alerts = [a for a in all_alerts if a.alert_type == AlertType.THRESHOLD_CROSSING]
    assert len(threshold_alerts) == 2
    assert {a.period_start for a in threshold_alerts} == {date(2026, 7, 1), date(2026, 8, 1)}


# ---------------------------------------------------------------------------
# EvaluateAlertsForTransactionHandler -- large transaction (AC2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_large_transaction_fires_when_over_3x_the_rolling_average(alerts, budgets, transactions) -> None:
    user_id = uuid.uuid4()
    for amount in ("20.00", "18.00", "22.00"):
        transactions.seed(user_id, "Dining", amount, date(2026, 7, 10))
    # average of the 3 prior transactions is 20.00 -> 3x = 60.00
    new_txn = transactions.seed(user_id, "Dining", "500.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn, category="Dining",
            amount=Decimal("500.00"), transaction_date=date(2026, 7, 15),
        )
    )
    large_alerts = [a for a in fired if a.alert_type == AlertType.LARGE_TRANSACTION]
    assert len(large_alerts) == 1
    assert large_alerts[0].transaction_id == new_txn


@pytest.mark.asyncio
async def test_large_transaction_does_not_fire_within_normal_range(alerts, budgets, transactions) -> None:
    user_id = uuid.uuid4()
    for amount in ("40.00", "38.00", "42.00"):
        transactions.seed(user_id, "Dining", amount, date(2026, 7, 10))
    new_txn = transactions.seed(user_id, "Dining", "45.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn, category="Dining",
            amount=Decimal("45.00"), transaction_date=date(2026, 7, 15),
        )
    )
    assert [a for a in fired if a.alert_type == AlertType.LARGE_TRANSACTION] == []


@pytest.mark.asyncio
async def test_large_transaction_uses_flat_fallback_below_min_sample_size(alerts, budgets, transactions) -> None:
    """With fewer than MIN_SAMPLE_SIZE prior transactions, the $300
    fallback baseline applies -- a $250 transaction must NOT fire even
    though it's huge relative to the one $10 prior transaction, because a
    1-sample average isn't trusted (ADR-014 decision C)."""
    user_id = uuid.uuid4()
    transactions.seed(user_id, "Dining", "10.00", date(2026, 7, 10))
    assert 1 < MIN_SAMPLE_SIZE
    new_txn = transactions.seed(user_id, "Dining", "250.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn, category="Dining",
            amount=Decimal("250.00"), transaction_date=date(2026, 7, 15),
        )
    )
    # 250 < FALLBACK_BASELINE (300) * LARGE_TRANSACTION_MULTIPLIER (3) = 900
    assert [a for a in fired if a.alert_type == AlertType.LARGE_TRANSACTION] == []


@pytest.mark.asyncio
async def test_large_transaction_fallback_still_fires_above_the_flat_threshold(alerts, budgets, transactions) -> None:
    user_id = uuid.uuid4()
    new_txn = transactions.seed(user_id, "Dining", "1000.00", date(2026, 7, 15))
    assert Decimal("1000.00") > FALLBACK_BASELINE * LARGE_TRANSACTION_MULTIPLIER

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn, category="Dining",
            amount=Decimal("1000.00"), transaction_date=date(2026, 7, 15),
        )
    )
    assert len([a for a in fired if a.alert_type == AlertType.LARGE_TRANSACTION]) == 1


@pytest.mark.asyncio
async def test_large_transaction_alert_never_fires_twice_for_the_same_transaction(alerts, budgets, transactions) -> None:
    """Idempotency guard: if evaluation were ever retried for the same
    transaction_id, find_by_transaction_id must prevent a duplicate row."""
    user_id = uuid.uuid4()
    txn_id = transactions.seed(user_id, "Dining", "1000.00", date(2026, 7, 15))
    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    command = EvaluateAlertsForTransactionCommand(
        user_id=user_id, transaction_id=txn_id, category="Dining",
        amount=Decimal("1000.00"), transaction_date=date(2026, 7, 15),
    )
    await handler.handle(command)
    await handler.handle(command)  # simulated retry

    all_alerts = await alerts.list_for_user(user_id, include_dismissed=True)
    large_alerts = [a for a in all_alerts if a.alert_type == AlertType.LARGE_TRANSACTION]
    assert len(large_alerts) == 1


@pytest.mark.asyncio
async def test_a_single_transaction_can_fire_both_alert_types_at_once(alerts, budgets, transactions) -> None:
    """A transaction can simultaneously push a budgeted category over 90%
    AND be unusually large relative to its own category history -- both
    checks are independent and both may fire."""
    user_id = uuid.uuid4()
    budgets.seed(user_id, "Dining", "100.00")
    for amount in ("10.00", "12.00", "11.00"):
        transactions.seed(user_id, "Dining", amount, date(2026, 7, 5))
    new_txn = transactions.seed(user_id, "Dining", "95.00", date(2026, 7, 15))

    handler = EvaluateAlertsForTransactionHandler(
        alert_repository=alerts, budget_repository=budgets, transaction_repository=transactions,
        clock=lambda: date(2026, 7, 19),
    )
    fired = await handler.handle(
        EvaluateAlertsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn, category="Dining",
            amount=Decimal("95.00"), transaction_date=date(2026, 7, 15),
        )
    )
    assert {a.alert_type for a in fired} == {AlertType.THRESHOLD_CROSSING, AlertType.LARGE_TRANSACTION}


# ---------------------------------------------------------------------------
# DismissAlertHandler -- AC4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_alert_sets_dismissed_at(alerts) -> None:
    user_id = uuid.uuid4()
    alert = Alert.new_threshold_crossing(
        user_id=user_id, category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    await alerts.add(alert)

    handler = DismissAlertHandler(alert_repository=alerts)
    await handler.handle(DismissAlertCommand(alert_id=alert.id, user_id=user_id))

    stored = await alerts.get_by_id_for_user(alert.id, user_id)
    assert stored.dismissed_at is not None


@pytest.mark.asyncio
async def test_dismiss_alert_raises_not_found_for_a_nonexistent_id(alerts) -> None:
    handler = DismissAlertHandler(alert_repository=alerts)
    with pytest.raises(AlertNotFoundError):
        await handler.handle(DismissAlertCommand(alert_id=uuid.uuid4(), user_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_dismiss_alert_raises_not_found_for_another_users_alert(alerts) -> None:
    """IDOR at the handler layer -- the attacker gets the same
    AlertNotFoundError as a truly nonexistent id, never a distinct
    'forbidden' signal."""
    owner_id = uuid.uuid4()
    alert = Alert.new_threshold_crossing(
        user_id=owner_id, category="Private", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    await alerts.add(alert)

    handler = DismissAlertHandler(alert_repository=alerts)
    attacker_id = uuid.uuid4()
    with pytest.raises(AlertNotFoundError):
        await handler.handle(DismissAlertCommand(alert_id=alert.id, user_id=attacker_id))

    still_active = await alerts.get_by_id_for_user(alert.id, owner_id)
    assert still_active.dismissed_at is None


@pytest.mark.asyncio
async def test_dismissing_an_already_dismissed_alert_is_a_harmless_no_op(alerts) -> None:
    user_id = uuid.uuid4()
    alert = Alert.new_threshold_crossing(
        user_id=user_id, category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    await alerts.add(alert)
    handler = DismissAlertHandler(alert_repository=alerts)
    await handler.handle(DismissAlertCommand(alert_id=alert.id, user_id=user_id))
    first_dismissed_at = (await alerts.get_by_id_for_user(alert.id, user_id)).dismissed_at

    await handler.handle(DismissAlertCommand(alert_id=alert.id, user_id=user_id))  # no error
    second_dismissed_at = (await alerts.get_by_id_for_user(alert.id, user_id)).dismissed_at
    assert second_dismissed_at == first_dismissed_at  # untouched, not re-stamped


# ---------------------------------------------------------------------------
# ListAlertsHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_alerts_returns_only_active_alerts_by_default(alerts) -> None:
    user_id = uuid.uuid4()
    active = Alert.new_threshold_crossing(
        user_id=user_id, category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    dismissed = Alert.new_threshold_crossing(
        user_id=user_id, category="Dining", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    dismissed.dismiss()
    await alerts.add(active)
    await alerts.add(dismissed)

    handler = ListAlertsHandler(alert_repository=alerts)
    result = await handler.handle(ListAlertsQuery(user_id=user_id))
    assert [a.id for a in result] == [active.id]


@pytest.mark.asyncio
async def test_list_alerts_includes_dismissed_when_requested(alerts) -> None:
    user_id = uuid.uuid4()
    dismissed = Alert.new_threshold_crossing(
        user_id=user_id, category="Dining", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    dismissed.dismiss()
    await alerts.add(dismissed)

    handler = ListAlertsHandler(alert_repository=alerts)
    result = await handler.handle(ListAlertsQuery(user_id=user_id, include_dismissed=True))
    assert [a.id for a in result] == [dismissed.id]


@pytest.mark.asyncio
async def test_list_alerts_only_returns_the_requesting_users_alerts(alerts) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    alert_a = Alert.new_threshold_crossing(
        user_id=user_a, category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    alert_b = Alert.new_threshold_crossing(
        user_id=user_b, category="Groceries", threshold_pct=Decimal("90.00"), period_start=date(2026, 7, 1)
    )
    await alerts.add(alert_a)
    await alerts.add(alert_b)

    handler = ListAlertsHandler(alert_repository=alerts)
    result_a = await handler.handle(ListAlertsQuery(user_id=user_a))
    assert [a.id for a in result_a] == [alert_a.id]
