"""Unit tests for GetWeeklyRecommendationHandler's FINTRACK-27 within-tier
reordering. Companion to test_weekly_recommendation_handler.py (FINTRACK-21,
which covers the base fixed-priority-chain behavior with no follow-through
history) and test_recommendation_prioritisation.py (which covers
RecommendationPrioritisationService.evaluate() in isolation).

Same fake-repository-at-the-port-boundary convention as
test_weekly_recommendation_handler.py -- FakeBudgetRepository/
FakeSubscriptionRepository/FakeTransactionRepository are duplicated here
rather than imported, matching this codebase's existing per-file-
self-contained-fakes convention (e.g. test_follow_through_security.py
does not import from test_recommendations_security.py despite testing
adjacent things).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from apps.api.application.queries.get_weekly_recommendation import (
    GetWeeklyRecommendationHandler,
    GetWeeklyRecommendationQuery,
    RecommendationType,
)
from apps.api.domain.models.follow_through_record import FollowThroughStatus
from apps.api.domain.models.subscription import SubscriptionStatus


# ---------------------------------------------------------------------------
# Fakes (budgets/subscriptions/transactions -- same shape as FINTRACK-21's
# own unit test file)
# ---------------------------------------------------------------------------


@dataclass
class _FakeBudget:
    category: str
    monthly_limit: Decimal


class FakeBudgetRepository:
    def __init__(self) -> None:
        self._budgets: dict[uuid.UUID, list[_FakeBudget]] = {}

    def seed(self, user_id, category: str, monthly_limit: str) -> None:
        self._budgets.setdefault(user_id, []).append(
            _FakeBudget(category=category, monthly_limit=Decimal(monthly_limit))
        )

    async def list_for_user(self, user_id) -> list[_FakeBudget]:
        return list(self._budgets.get(user_id, []))


@dataclass
class _FakeSubscription:
    merchant: str
    amount_estimate: Decimal
    interval_days: int
    status: SubscriptionStatus
    first_detected_at: datetime


class FakeSubscriptionRepository:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, list[_FakeSubscription]] = {}

    def seed(self, user_id, merchant: str, first_detected_at: datetime) -> None:
        self._subs.setdefault(user_id, []).append(
            _FakeSubscription(
                merchant=merchant,
                amount_estimate=Decimal("12.99"),
                interval_days=30,
                status=SubscriptionStatus.DETECTED,
                first_detected_at=first_detected_at,
            )
        )

    async def list_for_user(self, user_id, include_dismissed: bool = False) -> list[_FakeSubscription]:
        return list(self._subs.get(user_id, []))


class FakeTransactionRepository:
    def __init__(self) -> None:
        self.rows: list[tuple] = []

    def seed(self, user_id, category: str, amount: str, txn_date: date) -> None:
        self.rows.append((user_id, category, Decimal(amount), txn_date))

    async def sum_by_category_for_user_in_range(self, user_id, start_date, end_date) -> dict:
        totals: dict = {}
        for row_user_id, category, amount, txn_date in self.rows:
            if row_user_id != user_id or not (start_date <= txn_date < end_date):
                continue
            totals[category] = totals.get(category, Decimal("0")) + amount
        return totals


@dataclass
class _FakeFollowThroughRecord:
    status: FollowThroughStatus

    def is_overdue(self, today) -> bool:
        return False


class FakeFollowThroughRepository:
    def __init__(self) -> None:
        self._by_key: dict[tuple, list[_FakeFollowThroughRecord]] = {}

    def seed_deprioritised(self, user_id, recommendation_type: str, recommendation_key: str) -> None:
        """2 done of 10 (20%) -- comfortably below the 30% threshold. The
        2 DONE occurrences are placed OLDEST (successes long ago), with
        IGNORED filling the 8 most recent slots, so the most-recent
        occurrence is NOT done and the instant-recovery rule correctly
        stays out of the way (letting the sustained-low-rate check fire
        instead).
        """
        statuses_oldest_first = [FollowThroughStatus.DONE] * 2 + [FollowThroughStatus.IGNORED] * 8
        self._by_key[(user_id, recommendation_type, recommendation_key)] = [
            _FakeFollowThroughRecord(status=s) for s in reversed(statuses_oldest_first)
        ]

    def seed_normal(self, user_id, recommendation_type: str, recommendation_key: str) -> None:
        """8 done of 10 (80%) -- comfortably above the 30% threshold."""
        statuses_oldest_first = [FollowThroughStatus.DONE] * 8 + [FollowThroughStatus.DISMISSED] * 2
        self._by_key[(user_id, recommendation_type, recommendation_key)] = [
            _FakeFollowThroughRecord(status=s) for s in reversed(statuses_oldest_first)
        ]

    async def list_recent_for_user_type_and_key(
        self, user_id, recommendation_type, recommendation_key, limit=10
    ) -> list[_FakeFollowThroughRecord]:
        return self._by_key.get((user_id, recommendation_type, recommendation_key), [])[:limit]

    async def update(self, record) -> None:  # pragma: no cover
        pass


@pytest.fixture
def budgets() -> FakeBudgetRepository:
    return FakeBudgetRepository()


@pytest.fixture
def subscriptions() -> FakeSubscriptionRepository:
    return FakeSubscriptionRepository()


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


@pytest.fixture
def follow_through() -> FakeFollowThroughRepository:
    return FakeFollowThroughRepository()


def _handler(budgets, subscriptions, transactions, follow_through, today: date) -> GetWeeklyRecommendationHandler:
    return GetWeeklyRecommendationHandler(
        budget_repository=budgets,
        subscription_repository=subscriptions,
        transaction_repository=transactions,
        follow_through_repository=follow_through,
        clock=lambda: today,
    )


# ---------------------------------------------------------------------------
# Within-tier reordering: BUDGET_RISK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprioritised_budget_category_is_passed_over_for_a_normal_one(
    budgets, subscriptions, transactions, follow_through
) -> None:
    """Groceries is the native top pick (95% used > Dining's 85%), but
    Groceries has been mostly ignored -- Dining should be shown instead."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    budgets.seed(user_id, "Groceries", "100.00")
    transactions.seed(user_id, "Dining", "85.00", date(2026, 7, 5))
    transactions.seed(user_id, "Groceries", "95.00", date(2026, 7, 5))
    follow_through.seed_deprioritised(user_id, "BUDGET_RISK", "Groceries")
    follow_through.seed_normal(user_id, "BUDGET_RISK", "Dining")

    handler = _handler(budgets, subscriptions, transactions, follow_through, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Dining"
    assert rec.deprioritization_reason is not None
    assert "Groceries" in rec.deprioritization_reason
    assert "moved down" in rec.deprioritization_reason


@pytest.mark.asyncio
async def test_no_reorder_reason_when_native_top_pick_is_not_deprioritised(
    budgets, subscriptions, transactions, follow_through
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    budgets.seed(user_id, "Groceries", "100.00")
    transactions.seed(user_id, "Dining", "85.00", date(2026, 7, 5))
    transactions.seed(user_id, "Groceries", "95.00", date(2026, 7, 5))
    follow_through.seed_normal(user_id, "BUDGET_RISK", "Groceries")
    follow_through.seed_normal(user_id, "BUDGET_RISK", "Dining")

    handler = _handler(budgets, subscriptions, transactions, follow_through, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.category == "Groceries"  # native order (highest percent-used) unchanged
    assert rec.deprioritization_reason is None


@pytest.mark.asyncio
async def test_qualifying_tier_never_suppressed_even_if_every_candidate_is_deprioritised(
    budgets, subscriptions, transactions, follow_through
) -> None:
    """Only one at-risk budget exists and it's deprioritised -- BUDGET_RISK
    must still fire (never fall through to NEUTRAL or a lower tier) with
    no reorder reason, since nothing was actually reordered."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    transactions.seed(user_id, "Dining", "85.00", date(2026, 7, 5))
    follow_through.seed_deprioritised(user_id, "BUDGET_RISK", "Dining")

    handler = _handler(budgets, subscriptions, transactions, follow_through, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Dining"
    assert rec.deprioritization_reason is None


# ---------------------------------------------------------------------------
# AC4: follow-through-based reordering never crosses trigger tiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_risk_with_low_follow_through_still_outranks_subscription_with_high(
    budgets, subscriptions, transactions, follow_through
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    transactions.seed(user_id, "Dining", "90.00", date(2026, 7, 5))
    subscriptions.seed(user_id, "HULU", datetime(2026, 7, 18, tzinfo=timezone.utc))
    follow_through.seed_deprioritised(user_id, "BUDGET_RISK", "Dining")
    follow_through.seed_normal(user_id, "NEW_SUBSCRIPTION", "HULU")

    handler = _handler(budgets, subscriptions, transactions, follow_through, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    # AC4: tier ordering holds regardless of follow-through -- BUDGET_RISK
    # still wins even though its only candidate is (genuinely) deprioritised
    # and NEW_SUBSCRIPTION's candidate isn't.
    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Dining"


# ---------------------------------------------------------------------------
# Within-tier reordering: NEW_SUBSCRIPTION
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprioritised_subscription_merchant_is_passed_over_for_a_normal_one(
    budgets, subscriptions, transactions, follow_through
) -> None:
    """HULU is the native top pick (detected most recently), but the user
    has consistently ignored HULU recommendations -- DISNEY+ (detected
    earlier, but not ignored) should be shown instead."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    subscriptions.seed(user_id, "DISNEY+", datetime(2026, 7, 16, tzinfo=timezone.utc))
    subscriptions.seed(user_id, "HULU", datetime(2026, 7, 18, tzinfo=timezone.utc))
    follow_through.seed_deprioritised(user_id, "NEW_SUBSCRIPTION", "HULU")
    follow_through.seed_normal(user_id, "NEW_SUBSCRIPTION", "DISNEY+")

    handler = _handler(budgets, subscriptions, transactions, follow_through, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEW_SUBSCRIPTION
    assert rec.merchant == "DISNEY+"
    assert "HULU" in rec.deprioritization_reason


# ---------------------------------------------------------------------------
# Within-tier reordering: SPENDING_SPIKE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprioritised_spike_category_is_passed_over_for_a_normal_one(
    budgets, subscriptions, transactions, follow_through
) -> None:
    """Dining-out spikes harder (native top pick by spend amount), but the
    user has consistently ignored dining-out spike alerts -- Entertainment
    (a smaller but still-qualifying spike) should be shown instead."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)  # this week: Jul 14-20

    for i in range(4):
        from datetime import timedelta

        transactions.seed(user_id, "Dining", "20.00", date(2026, 6, 17) + timedelta(days=7 * i))
        transactions.seed(user_id, "Entertainment", "20.00", date(2026, 6, 17) + timedelta(days=7 * i))
    transactions.seed(user_id, "Dining", "80.00", date(2026, 7, 18))  # 4x baseline
    transactions.seed(user_id, "Entertainment", "35.00", date(2026, 7, 18))  # 1.75x baseline

    follow_through.seed_deprioritised(user_id, "SPENDING_SPIKE", "Dining")
    follow_through.seed_normal(user_id, "SPENDING_SPIKE", "Entertainment")

    handler = _handler(budgets, subscriptions, transactions, follow_through, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.SPENDING_SPIKE
    assert rec.category == "Entertainment"
    assert "Dining" in rec.deprioritization_reason
