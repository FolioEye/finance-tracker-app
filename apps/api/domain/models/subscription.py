"""Subscription domain entity + detection engine. Story: FINTRACK-18
(Subscription / Recurring-Charge Detection).

A Subscription is a persisted, individually-actionable record of a
recurring-charge pattern the system noticed -- same "write it down so a
later read can tell already-told-them from haven't-yet" rationale as
Alert (FINTRACK-22, see domain.models.alert's docstring), but keyed
differently: one row per (user_id, merchant), not per-period, since a
merchant either currently looks like a subscription or it doesn't -- there
is no "period" a subscription pattern resets on the way a monthly budget
does.

merchant is derived from Transaction.note (the same field FINTRACK-17's
CategorisationRule already pattern-matches against as the transaction's
merchant/description text), normalised upper-case with the same rationale
as CategorisationRule.merchant_pattern. No SQLi-shaped-input re-check here
-- same reasoning as Alert.category's docstring: this value is never fresh
user input at this layer, it's copied verbatim from an already-validated
Transaction.note (validated by Transaction.new()/apply_update() at
creation/edit time), so re-validating it here would be redundant, not
defence-in-depth.

Re-detection (AC6, "re-runs when new transactions are added") follows the
same write-time-detection pattern ADR-014 established for alerts, not a
background batch job -- see application/commands/detect_subscriptions_for_transaction.py.
Detection is rules-based pattern matching (merchant + amount tolerance +
interval), not ML -- same explicit v1 scope boundary as FINTRACK-17's
categorisation engine.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

# AC1: "pattern-match merchant+amount(tolerance)+interval". A merchant
# needs at least this many transactions before a recurring pattern means
# anything -- same "not enough history for a personal signal" principle
# as FINTRACK-22's MIN_SAMPLE_SIZE, and matches the Gherkin's own minimum
# evidence bar (all three flagged scenarios use exactly three
# transactions; the negative scenario uses two).
MIN_OCCURRENCES = 3

# Amounts within this percentage of the cluster's average still count as
# "the same recurring charge" (AC3's amount-varies-slightly scenario:
# $84.50/$91.20/$88.00 -- max deviation from their ~$87.90 average is
# ~3.9%, comfortably inside this tolerance while still excluding
# obviously-unrelated one-off charges of wildly different amounts).
AMOUNT_TOLERANCE_PCT = Decimal("15")

# A subscription is assumed monthly for v1 (matches every Gherkin example
# and the PM's business case) -- a fixed target with a generous window
# rather than attempting to auto-detect weekly/quarterly/annual cadences,
# which is out of scope for this rules-based first pass.
INTERVAL_TARGET_DAYS = 30
INTERVAL_TOLERANCE_DAYS = 7


class SubscriptionStatus(str, Enum):
    DETECTED = "DETECTED"  # system-flagged, no user action yet
    CONFIRMED = "CONFIRMED"  # user confirmed this is a real subscription
    DISMISSED = "DISMISSED"  # user dismissed -- AC5: not re-suggested
    NOT_SUBSCRIPTION = "NOT_SUBSCRIPTION"  # user explicitly said no -- also not re-suggested


# Statuses a re-detection run must never overwrite back to DETECTED --
# AC5's "dismissed pattern not re-suggested" applies to both terminal
# outcomes, not just a literal "Dismiss" click.
TERMINAL_STATUSES = frozenset({SubscriptionStatus.DISMISSED, SubscriptionStatus.NOT_SUBSCRIPTION})


@dataclass
class Subscription:
    id: uuid.UUID
    user_id: uuid.UUID
    merchant: str  # normalised upper-case, matches CategorisationRule's convention
    amount_estimate: Decimal  # average amount across matched occurrences
    interval_days: int  # average day-gap across matched occurrences, rounded
    occurrences: int
    status: SubscriptionStatus
    last_transaction_id: uuid.UUID
    first_detected_at: datetime
    last_seen_at: datetime
    updated_at: datetime

    @staticmethod
    def new_detected(
        user_id: uuid.UUID,
        merchant: str,
        amount_estimate: Decimal,
        interval_days: int,
        occurrences: int,
        last_transaction_id: uuid.UUID,
    ) -> "Subscription":
        now = datetime.now(timezone.utc)
        return Subscription(
            id=uuid.uuid4(),
            user_id=user_id,
            merchant=merchant,
            amount_estimate=amount_estimate,
            interval_days=interval_days,
            occurrences=occurrences,
            status=SubscriptionStatus.DETECTED,
            last_transaction_id=last_transaction_id,
            first_detected_at=now,
            last_seen_at=now,
            updated_at=now,
        )

    def refresh_stats(
        self,
        amount_estimate: Decimal,
        interval_days: int,
        occurrences: int,
        last_transaction_id: uuid.UUID,
    ) -> None:
        """AC6: re-run on new data. Updates the cluster's stats in place
        without touching `status` -- a CONFIRMED subscription stays
        CONFIRMED as its estimate sharpens; a DETECTED one stays DETECTED
        pending user action. Callers must not call this on a row whose
        status is in TERMINAL_STATUSES -- see
        detect_subscriptions_for_transaction.py's handler, which checks
        that before calling this method at all."""
        self.amount_estimate = amount_estimate
        self.interval_days = interval_days
        self.occurrences = occurrences
        self.last_transaction_id = last_transaction_id
        now = datetime.now(timezone.utc)
        self.last_seen_at = now
        self.updated_at = now

    def confirm(self) -> None:
        self.status = SubscriptionStatus.CONFIRMED
        self.updated_at = datetime.now(timezone.utc)

    def dismiss(self) -> None:
        """AC5: dismissing must not be re-suggested -- enforced by
        detect_subscriptions_for_transaction.py checking TERMINAL_STATUSES
        before ever mutating a row back toward DETECTED, not by anything
        in this method."""
        self.status = SubscriptionStatus.DISMISSED
        self.updated_at = datetime.now(timezone.utc)

    def mark_not_subscription(self) -> None:
        self.status = SubscriptionStatus.NOT_SUBSCRIPTION
        self.updated_at = datetime.now(timezone.utc)


@dataclass(frozen=True)
class _Occurrence:
    amount: Decimal
    transaction_date: date_type
    transaction_id: uuid.UUID


def detect_pattern(occurrences: list[_Occurrence]) -> Optional[tuple[Decimal, int]]:
    """Pure clustering function -- given every one of a user's
    transactions for a single already-grouped merchant, returns
    (amount_estimate, interval_days) if they form a recurring-charge
    pattern per AC1, or None if they don't (AC2's negative case: fewer
    than MIN_OCCURRENCES, amounts too varied, or no regular interval).

    No I/O, no repository access -- this is deliberately a plain function
    over plain data so it can be unit-tested without a database, same
    "pure domain logic separate from persistence" shape as
    find_matching_rule in categorisation_rule.py.
    """
    if len(occurrences) < MIN_OCCURRENCES:
        return None

    ordered = sorted(occurrences, key=lambda o: o.transaction_date)
    avg_amount = sum((o.amount for o in ordered), Decimal("0")) / Decimal(len(ordered))

    for occ in ordered:
        deviation_pct = abs(occ.amount - avg_amount) / avg_amount * Decimal("100")
        if deviation_pct > AMOUNT_TOLERANCE_PCT:
            return None

    gaps = [
        (ordered[i + 1].transaction_date - ordered[i].transaction_date).days
        for i in range(len(ordered) - 1)
    ]
    avg_gap = sum(gaps) / len(gaps)
    if abs(avg_gap - INTERVAL_TARGET_DAYS) > INTERVAL_TOLERANCE_DAYS:
        return None

    return (avg_amount.quantize(Decimal("0.01")), round(avg_gap))


def normalise_merchant(note: str) -> str:
    """Same normalisation convention as CategorisationRule.merchant_pattern
    -- upper-cased, stripped, so 'Netflix.com' and 'NETFLIX.COM #123' can
    still be compared consistently. Callers group transactions by this
    value before calling detect_pattern, mirroring
    find_matching_rule's use of upper-cased substring matching."""
    return note.strip().upper()
