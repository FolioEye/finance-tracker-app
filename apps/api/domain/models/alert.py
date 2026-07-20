"""Alert domain entity. Story: FINTRACK-22 (Threshold-Based Alerts).

An Alert is a persisted, individually-dismissible record of something the
system noticed and told the user about -- unlike Budget (FINTRACK-20),
which is pure compute-on-read, an Alert has to be written down the first
time it fires so a later read can tell "already told them" from "haven't
yet" (AC5's "no spam -- max once per threshold crossing per period").
See docs/adr/ADR-014-threshold-alerts-write-time-detection.md for the
full rationale on why this story can't stay pure compute-on-read the way
ADR-013's budget overview did.

Two distinct alert shapes share this one table/model rather than being
split into separate entities, because they share every field except how
they're keyed for uniqueness:

- THRESHOLD_CROSSING: category spend crossed a fixed percentage of its
  budget this period (AC1). Deduplicated per (user, category, period,
  threshold_pct) -- at most one row per crossing per period (AC5).
- LARGE_TRANSACTION: a single transaction was unusually large relative to
  the user's own recent spending in that category (AC2). Deduplicated per
  transaction_id -- at most one row per triggering transaction, since
  each large transaction is its own one-off event, not a recurring state
  the way a threshold crossing is. AC5's "no spam" language is specific
  to threshold crossings; a second, different large transaction next week
  is a new event and should alert again.

No SQLi-shaped-input check here (unlike Budget/Transaction/
CategorisationRule) -- category is never fresh user input at this layer;
it's copied verbatim from an already-validated Transaction or Budget row,
so re-validating it here would be redundant, not defence-in-depth.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class AlertType(str, Enum):
    THRESHOLD_CROSSING = "THRESHOLD_CROSSING"
    LARGE_TRANSACTION = "LARGE_TRANSACTION"


@dataclass
class Alert:
    id: uuid.UUID
    user_id: uuid.UUID
    category: str
    alert_type: AlertType
    period_start: date_type
    fired_at: datetime
    threshold_pct: Optional[Decimal] = None  # THRESHOLD_CROSSING only
    transaction_id: Optional[uuid.UUID] = None  # LARGE_TRANSACTION only
    dismissed_at: Optional[datetime] = None

    @staticmethod
    def new_threshold_crossing(
        user_id: uuid.UUID,
        category: str,
        threshold_pct: Decimal,
        period_start: date_type,
    ) -> "Alert":
        return Alert(
            id=uuid.uuid4(),
            user_id=user_id,
            category=category,
            alert_type=AlertType.THRESHOLD_CROSSING,
            period_start=period_start,
            fired_at=datetime.now(timezone.utc),
            threshold_pct=threshold_pct,
        )

    @staticmethod
    def new_large_transaction(
        user_id: uuid.UUID,
        category: str,
        transaction_id: uuid.UUID,
        period_start: date_type,
    ) -> "Alert":
        return Alert(
            id=uuid.uuid4(),
            user_id=user_id,
            category=category,
            alert_type=AlertType.LARGE_TRANSACTION,
            period_start=period_start,
            fired_at=datetime.now(timezone.utc),
            transaction_id=transaction_id,
        )

    def dismiss(self) -> None:
        """AC4: dismissing this alert has no effect on whether future
        alerts fire -- it only marks this one row as seen. There is
        deliberately no "disable alerts for this category" side effect
        anywhere in this method or its callers."""
        self.dismissed_at = datetime.now(timezone.utc)
