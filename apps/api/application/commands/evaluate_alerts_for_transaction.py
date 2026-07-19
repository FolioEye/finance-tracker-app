"""EvaluateAlertsForTransactionCommand + handler. Story: FINTRACK-22.

Runs after a transaction is successfully created (called from the
transactions API endpoint, not from CreateTransactionHandler itself --
see docs/adr/ADR-014-threshold-alerts-write-time-detection.md for why
this is composed at the presentation layer rather than folded into the
already-shipped, already-fully-tested CreateTransactionHandler). Evaluates
both alert types for the just-created transaction:

1. LARGE_TRANSACTION (AC2): is this one transaction unusually large
   relative to the user's own recent spending in this category?
2. THRESHOLD_CROSSING (AC1/AC5): did this transaction push the category's
   month-to-date spend across a fixed threshold of its budget, for a
   category that has a budget?

Both checks are best-effort from the caller's point of view: a bug here
must never prevent the transaction itself from being created. See
presentation/api/v1/transactions.py for how failures here are isolated
from the transaction-creation response.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Callable, Optional

from apps.api.domain.models.alert import Alert
from apps.api.domain.repositories.alert_repository import AlertRepository
from apps.api.domain.repositories.budget_repository import BudgetRepository
from apps.api.domain.repositories.transaction_repository import TransactionRepository

# AC1's Gherkin is explicit about one fixed threshold ("90%"), not a
# multi-tier system (50/75/90/100%) -- v1 keeps this as a single constant.
# A future story could parametrise this per-user; out of scope here, same
# as this story's own "custom user-defined thresholds (P1)" line.
THRESHOLD_PCT = Decimal("90.00")

# A transaction is "unusually large" (AC2) if it's at least this many
# times the user's own recent average in that category.
LARGE_TRANSACTION_MULTIPLIER = Decimal("3")

# Below this many prior transactions in a category, there isn't enough
# history for a personal average to mean anything -- fall back to a flat
# platform default instead of a noisy 1-2-sample average. See ADR-014.
MIN_SAMPLE_SIZE = 3
FALLBACK_BASELINE = Decimal("300.00")
ROLLING_WINDOW = 10


def _current_month_start(today: date_type) -> date_type:
    return today.replace(day=1)


def _current_month_bounds(today: date_type) -> tuple[date_type, date_type]:
    start = _current_month_start(today)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@dataclass(frozen=True)
class EvaluateAlertsForTransactionCommand:
    user_id: uuid.UUID
    transaction_id: uuid.UUID
    category: str
    amount: Decimal
    transaction_date: date_type


class EvaluateAlertsForTransactionHandler:
    def __init__(
        self,
        alert_repository: AlertRepository,
        budget_repository: BudgetRepository,
        transaction_repository: TransactionRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._alerts = alert_repository
        self._budgets = budget_repository
        self._transactions = transaction_repository
        # Same injected-clock rationale as ADR-013's GetBudgetOverviewHandler
        # -- lets tests pin "today" to exercise period-boundary behaviour
        # deterministically.
        self._clock = clock

    async def handle(self, command: EvaluateAlertsForTransactionCommand) -> list[Alert]:
        fired: list[Alert] = []

        large_txn_alert = await self._evaluate_large_transaction(command)
        if large_txn_alert is not None:
            fired.append(large_txn_alert)

        threshold_alert = await self._evaluate_threshold_crossing(command)
        if threshold_alert is not None:
            fired.append(threshold_alert)

        return fired

    async def _evaluate_large_transaction(
        self, command: EvaluateAlertsForTransactionCommand
    ) -> Optional[Alert]:
        # Idempotency guard first -- cheap, and avoids computing a
        # baseline we won't end up using.
        existing = await self._alerts.find_by_transaction_id(command.transaction_id)
        if existing is not None:
            return None

        recent_amounts = await self._transactions.get_recent_amounts_for_category(
            user_id=command.user_id,
            category=command.category,
            exclude_transaction_id=command.transaction_id,
            limit=ROLLING_WINDOW,
        )

        if len(recent_amounts) < MIN_SAMPLE_SIZE:
            baseline = FALLBACK_BASELINE
        else:
            baseline = sum(recent_amounts) / Decimal(len(recent_amounts))

        if command.amount < baseline * LARGE_TRANSACTION_MULTIPLIER:
            return None

        alert = Alert.new_large_transaction(
            user_id=command.user_id,
            category=command.category,
            transaction_id=command.transaction_id,
            period_start=_current_month_start(self._clock()),
        )
        await self._alerts.add(alert)
        return alert

    async def _evaluate_threshold_crossing(
        self, command: EvaluateAlertsForTransactionCommand
    ) -> Optional[Alert]:
        budget = await self._budgets.get_by_category_for_user(command.user_id, command.category)
        if budget is None:
            # AC1 only applies to budgeted categories -- same "no budget,
            # no false signal" principle as FINTRACK-20's AC5.
            return None

        period_start, period_end = _current_month_bounds(self._clock())
        spend_by_category = await self._transactions.sum_by_category_for_user_in_range(
            command.user_id, period_start, period_end
        )
        spent = spend_by_category.get(command.category, Decimal("0"))
        percent_used = (spent / budget.monthly_limit) * Decimal("100")

        if percent_used < THRESHOLD_PCT:
            return None

        # AC5: at most one alert per (user, category, period, threshold).
        # Checked explicitly here (not relied on purely via the DB unique
        # constraint) so a duplicate never even reaches an add() call in
        # the common path -- the constraint is the defence-in-depth
        # backstop for a race, not the primary mechanism.
        existing = await self._alerts.find_active_threshold_crossing(
            command.user_id, command.category, period_start, THRESHOLD_PCT
        )
        if existing is not None:
            return None

        alert = Alert.new_threshold_crossing(
            user_id=command.user_id,
            category=command.category,
            threshold_pct=THRESHOLD_PCT,
            period_start=period_start,
        )
        await self._alerts.add(alert)
        return alert
