"""Unit tests for the subscription command/query handlers (FINTRACK-18):
DetectSubscriptionsForTransactionHandler, ConfirmSubscriptionHandler,
DismissSubscriptionHandler, MarkNotSubscriptionHandler,
ListSubscriptionsHandler. Fake in-memory repositories stand in for the
real SQLAlchemy adapters, same pattern as tests/unit/test_alert_handlers.py.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.api.application.commands.confirm_subscription import (
    ConfirmSubscriptionCommand,
    ConfirmSubscriptionHandler,
)
from apps.api.application.commands.detect_subscriptions_for_transaction import (
    DetectSubscriptionsForTransactionCommand,
    DetectSubscriptionsForTransactionHandler,
)
from apps.api.application.commands.dismiss_subscription import (
    DismissSubscriptionCommand,
    DismissSubscriptionHandler,
)
from apps.api.application.commands.mark_not_subscription import (
    MarkNotSubscriptionCommand,
    MarkNotSubscriptionHandler,
)
from apps.api.application.queries.list_subscriptions import (
    ListSubscriptionsHandler,
    ListSubscriptionsQuery,
)
from apps.api.domain.models.subscription import Subscription, SubscriptionStatus
from apps.api.domain.repositories.subscription_repository import SubscriptionNotFoundError


class FakeSubscriptionRepository:
    """In-memory stand-in for SqlAlchemySubscriptionRepository. Implements
    the full SubscriptionRepository port, including its documented
    None-for-not-found-or-not-yours semantics on get_by_id_for_user."""

    def __init__(self) -> None:
        self.subs: dict[uuid.UUID, Subscription] = {}

    async def add(self, subscription: Subscription) -> None:
        self.subs[subscription.id] = subscription

    async def get_by_id_for_user(self, subscription_id: uuid.UUID, user_id: uuid.UUID):
        sub = self.subs.get(subscription_id)
        if sub is None or sub.user_id != user_id:
            return None
        return sub

    async def find_by_user_and_merchant(self, user_id: uuid.UUID, merchant: str):
        for sub in self.subs.values():
            if sub.user_id == user_id and sub.merchant == merchant:
                return sub
        return None

    async def list_for_user(self, user_id: uuid.UUID, include_dismissed: bool = False):
        result = [s for s in self.subs.values() if s.user_id == user_id]
        if not include_dismissed:
            result = [s for s in result if s.status not in (SubscriptionStatus.DISMISSED, SubscriptionStatus.NOT_SUBSCRIPTION)]
        return sorted(result, key=lambda s: s.last_seen_at, reverse=True)

    async def update(self, subscription: Subscription) -> None:
        self.subs[subscription.id] = subscription


class _FakeTxn:
    def __init__(self, amount: str, txn_date: date, txn_id=None):
        self.amount = Decimal(amount)
        self.transaction_date = txn_date
        self.id = txn_id or uuid.uuid4()


class FakeTransactionRepository:
    """Implements only list_all_for_user_by_merchant -- the one method
    DetectSubscriptionsForTransactionHandler actually calls."""

    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str], list[_FakeTxn]] = {}

    def seed(self, user_id: uuid.UUID, merchant: str, amount: str, txn_date: date, txn_id=None) -> uuid.UUID:
        txn = _FakeTxn(amount, txn_date, txn_id)
        self.rows.setdefault((user_id, merchant), []).append(txn)
        return txn.id

    async def list_all_for_user_by_merchant(self, user_id: uuid.UUID, merchant: str):
        return list(self.rows.get((user_id, merchant), []))


@pytest.fixture
def subscriptions() -> FakeSubscriptionRepository:
    return FakeSubscriptionRepository()


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


# ---------------------------------------------------------------------------
# DetectSubscriptionsForTransactionHandler -- AC1, AC6
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_a_new_subscription_when_pattern_first_detected(subscriptions, transactions) -> None:
    user_id = uuid.uuid4()
    base = date(2026, 1, 1)
    transactions.seed(user_id, "NETFLIX.COM", "15.99", base)
    transactions.seed(user_id, "NETFLIX.COM", "15.99", base + timedelta(days=30))
    last_txn_id = transactions.seed(user_id, "NETFLIX.COM", "15.99", base + timedelta(days=60))

    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    result = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=last_txn_id, note="Netflix.com",
            amount=Decimal("15.99"), transaction_date=base + timedelta(days=60),
        )
    )
    assert result is not None
    assert result.status == SubscriptionStatus.DETECTED
    assert result.merchant == "NETFLIX.COM"
    stored = await subscriptions.find_by_user_and_merchant(user_id, "NETFLIX.COM")
    assert stored is not None


@pytest.mark.asyncio
async def test_returns_none_and_creates_nothing_when_pattern_not_yet_present(subscriptions, transactions) -> None:
    """AC2: below MIN_OCCURRENCES (only 2 seen so far) -- no row created."""
    user_id = uuid.uuid4()
    base = date(2026, 1, 1)
    transactions.seed(user_id, "AMAZON", "42.10", base)
    last_txn_id = transactions.seed(user_id, "AMAZON", "9.99", base + timedelta(days=75))

    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    result = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=last_txn_id, note="AMAZON",
            amount=Decimal("9.99"), transaction_date=base + timedelta(days=75),
        )
    )
    assert result is None
    assert await subscriptions.find_by_user_and_merchant(user_id, "AMAZON") is None


@pytest.mark.asyncio
async def test_refreshes_existing_subscription_stats_on_re_detection(subscriptions, transactions) -> None:
    """AC6: re-runs when new transactions are added -- a 4th occurrence
    updates the existing row's stats (and last_transaction_id) rather than
    creating a duplicate."""
    user_id = uuid.uuid4()
    base = date(2026, 1, 1)
    for i in range(3):
        transactions.seed(user_id, "NETFLIX.COM", "15.99", base + timedelta(days=30 * i))
    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    first = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=uuid.uuid4(), note="NETFLIX.COM",
            amount=Decimal("15.99"), transaction_date=base + timedelta(days=60),
        )
    )
    original_id = first.id

    fourth_txn_id = transactions.seed(user_id, "NETFLIX.COM", "15.99", base + timedelta(days=90))
    second = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=fourth_txn_id, note="NETFLIX.COM",
            amount=Decimal("15.99"), transaction_date=base + timedelta(days=90),
        )
    )
    assert second.id == original_id  # same row, not a duplicate
    assert second.occurrences == 4
    assert second.last_transaction_id == fourth_txn_id
    all_subs = await subscriptions.list_for_user(user_id, include_dismissed=True)
    assert len(all_subs) == 1


@pytest.mark.asyncio
async def test_dismissed_subscription_is_never_resurfaced_by_re_detection(subscriptions, transactions) -> None:
    """AC5: dismissed pattern not re-suggested -- even though the pattern
    still matches perfectly, a DISMISSED row must not be touched."""
    user_id = uuid.uuid4()
    base = date(2026, 1, 1)
    for i in range(3):
        transactions.seed(user_id, "NETFLIX.COM", "15.99", base + timedelta(days=30 * i))
    existing = Subscription.new_detected(
        user_id=user_id, merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    existing.dismiss()
    await subscriptions.add(existing)
    original_updated_at = existing.updated_at

    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    new_txn_id = transactions.seed(user_id, "NETFLIX.COM", "15.99", base + timedelta(days=120))
    result = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn_id, note="NETFLIX.COM",
            amount=Decimal("15.99"), transaction_date=base + timedelta(days=120),
        )
    )
    assert result is None
    stored = await subscriptions.get_by_id_for_user(existing.id, user_id)
    assert stored.status == SubscriptionStatus.DISMISSED
    assert stored.updated_at == original_updated_at  # completely untouched


@pytest.mark.asyncio
async def test_not_subscription_marked_row_is_never_resurfaced_either(subscriptions, transactions) -> None:
    user_id = uuid.uuid4()
    base = date(2026, 1, 1)
    existing = Subscription.new_detected(
        user_id=user_id, merchant="AMAZON", amount_estimate=Decimal("20.00"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    existing.mark_not_subscription()
    await subscriptions.add(existing)

    for i in range(3):
        transactions.seed(user_id, "AMAZON", "20.00", base + timedelta(days=30 * i))
    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    new_txn_id = transactions.seed(user_id, "AMAZON", "20.00", base + timedelta(days=90))
    result = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=new_txn_id, note="AMAZON",
            amount=Decimal("20.00"), transaction_date=base + timedelta(days=90),
        )
    )
    assert result is None


@pytest.mark.asyncio
async def test_note_less_transaction_is_skipped_entirely(subscriptions, transactions) -> None:
    user_id = uuid.uuid4()
    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    result = await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_id, transaction_id=uuid.uuid4(), note=None,
            amount=Decimal("10.00"), transaction_date=date(2026, 1, 1),
        )
    )
    assert result is None


@pytest.mark.asyncio
async def test_two_different_users_with_the_same_merchant_get_independent_rows(subscriptions, transactions) -> None:
    """One row per (user_id, merchant) -- a merchant pattern for one user
    must never be visible to, or updated by, another user's transactions."""
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    base = date(2026, 1, 1)
    for i in range(3):
        transactions.seed(user_a, "NETFLIX.COM", "15.99", base + timedelta(days=30 * i))
    handler = DetectSubscriptionsForTransactionHandler(subscriptions, transactions)
    await handler.handle(
        DetectSubscriptionsForTransactionCommand(
            user_id=user_a, transaction_id=uuid.uuid4(), note="NETFLIX.COM",
            amount=Decimal("15.99"), transaction_date=base + timedelta(days=60),
        )
    )
    assert await subscriptions.find_by_user_and_merchant(user_b, "NETFLIX.COM") is None
    assert await subscriptions.find_by_user_and_merchant(user_a, "NETFLIX.COM") is not None


# ---------------------------------------------------------------------------
# ConfirmSubscriptionHandler / DismissSubscriptionHandler /
# MarkNotSubscriptionHandler -- AC3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_sets_status_confirmed(subscriptions) -> None:
    user_id = uuid.uuid4()
    sub = Subscription.new_detected(
        user_id=user_id, merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub)
    handler = ConfirmSubscriptionHandler(subscriptions)
    await handler.handle(ConfirmSubscriptionCommand(subscription_id=sub.id, user_id=user_id))
    stored = await subscriptions.get_by_id_for_user(sub.id, user_id)
    assert stored.status == SubscriptionStatus.CONFIRMED


@pytest.mark.asyncio
async def test_confirm_raises_not_found_for_nonexistent_id(subscriptions) -> None:
    handler = ConfirmSubscriptionHandler(subscriptions)
    with pytest.raises(SubscriptionNotFoundError):
        await handler.handle(ConfirmSubscriptionCommand(subscription_id=uuid.uuid4(), user_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_confirm_raises_not_found_for_another_users_subscription(subscriptions) -> None:
    """IDOR at the handler layer -- the attacker gets the same
    SubscriptionNotFoundError as a truly nonexistent id."""
    owner_id = uuid.uuid4()
    sub = Subscription.new_detected(
        user_id=owner_id, merchant="PRIVATE.COM", amount_estimate=Decimal("9.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub)
    handler = ConfirmSubscriptionHandler(subscriptions)
    attacker_id = uuid.uuid4()
    with pytest.raises(SubscriptionNotFoundError):
        await handler.handle(ConfirmSubscriptionCommand(subscription_id=sub.id, user_id=attacker_id))
    still_detected = await subscriptions.get_by_id_for_user(sub.id, owner_id)
    assert still_detected.status == SubscriptionStatus.DETECTED


@pytest.mark.asyncio
async def test_dismiss_sets_status_dismissed(subscriptions) -> None:
    user_id = uuid.uuid4()
    sub = Subscription.new_detected(
        user_id=user_id, merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub)
    handler = DismissSubscriptionHandler(subscriptions)
    await handler.handle(DismissSubscriptionCommand(subscription_id=sub.id, user_id=user_id))
    stored = await subscriptions.get_by_id_for_user(sub.id, user_id)
    assert stored.status == SubscriptionStatus.DISMISSED


@pytest.mark.asyncio
async def test_dismiss_raises_not_found_for_another_users_subscription(subscriptions) -> None:
    owner_id = uuid.uuid4()
    sub = Subscription.new_detected(
        user_id=owner_id, merchant="PRIVATE.COM", amount_estimate=Decimal("9.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub)
    handler = DismissSubscriptionHandler(subscriptions)
    with pytest.raises(SubscriptionNotFoundError):
        await handler.handle(DismissSubscriptionCommand(subscription_id=sub.id, user_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_mark_not_subscription_sets_status(subscriptions) -> None:
    user_id = uuid.uuid4()
    sub = Subscription.new_detected(
        user_id=user_id, merchant="AMAZON", amount_estimate=Decimal("20.00"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub)
    handler = MarkNotSubscriptionHandler(subscriptions)
    await handler.handle(MarkNotSubscriptionCommand(subscription_id=sub.id, user_id=user_id))
    stored = await subscriptions.get_by_id_for_user(sub.id, user_id)
    assert stored.status == SubscriptionStatus.NOT_SUBSCRIPTION


@pytest.mark.asyncio
async def test_mark_not_subscription_raises_not_found_for_another_users_subscription(subscriptions) -> None:
    owner_id = uuid.uuid4()
    sub = Subscription.new_detected(
        user_id=owner_id, merchant="PRIVATE.COM", amount_estimate=Decimal("9.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub)
    handler = MarkNotSubscriptionHandler(subscriptions)
    with pytest.raises(SubscriptionNotFoundError):
        await handler.handle(MarkNotSubscriptionCommand(subscription_id=sub.id, user_id=uuid.uuid4()))


# ---------------------------------------------------------------------------
# ListSubscriptionsHandler -- AC2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_active_subscriptions_by_default(subscriptions) -> None:
    user_id = uuid.uuid4()
    active = Subscription.new_detected(
        user_id=user_id, merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    dismissed = Subscription.new_detected(
        user_id=user_id, merchant="HULU.COM", amount_estimate=Decimal("11.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    dismissed.dismiss()
    await subscriptions.add(active)
    await subscriptions.add(dismissed)

    handler = ListSubscriptionsHandler(subscriptions)
    result = await handler.handle(ListSubscriptionsQuery(user_id=user_id))
    assert [s.id for s in result] == [active.id]


@pytest.mark.asyncio
async def test_list_includes_dismissed_when_requested(subscriptions) -> None:
    user_id = uuid.uuid4()
    dismissed = Subscription.new_detected(
        user_id=user_id, merchant="HULU.COM", amount_estimate=Decimal("11.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    dismissed.dismiss()
    await subscriptions.add(dismissed)

    handler = ListSubscriptionsHandler(subscriptions)
    result = await handler.handle(ListSubscriptionsQuery(user_id=user_id, include_dismissed=True))
    assert [s.id for s in result] == [dismissed.id]


@pytest.mark.asyncio
async def test_list_only_returns_the_requesting_users_subscriptions(subscriptions) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    sub_a = Subscription.new_detected(
        user_id=user_a, merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    sub_b = Subscription.new_detected(
        user_id=user_b, merchant="NETFLIX.COM", amount_estimate=Decimal("15.99"),
        interval_days=30, occurrences=3, last_transaction_id=uuid.uuid4(),
    )
    await subscriptions.add(sub_a)
    await subscriptions.add(sub_b)
    handler = ListSubscriptionsHandler(subscriptions)
    result_a = await handler.handle(ListSubscriptionsQuery(user_id=user_a))
    assert [s.id for s in result_a] == [sub_a.id]
