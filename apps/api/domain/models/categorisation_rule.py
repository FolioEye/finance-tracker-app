"""Categorisation rule domain model + matching engine. Story: FINTRACK-17
(AI Auto-Categorisation Rules Engine).

A CategorisationRule maps a merchant/description substring pattern to a
category, scoped per-user. Rules are created two ways: directly (POST
/api/v1/categorisation-rules) or implicitly, via the correction-feedback
loop (AC3 -- see application/commands/update_transaction.py), which is
this story's fifth Gherkin scenario and the reason the repository exposes
an upsert rather than only add().

Scope: v1 is rules-based only, substring/pattern matching -- no per-user
ML model training (explicit out-of-scope per the PM's "rules engine"
framing in the story description).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from apps.api.domain.models.transaction import SuspiciousInputError

# Reuses the same exception type FINTRACK-13/14/15/16 already use for
# SQLi-shaped input (SuspiciousInputError from domain.models.transaction)
# so callers/tests share one vocabulary for this class of rejection,
# rather than this story inventing a parallel exception type for the same
# concept. The pattern itself is duplicated (not imported) because
# transaction.py's is a private module-level constant -- each domain
# module owns its own validation, same precedent as import_batch.py's
# separate sanitise_if_formula() next to transaction.py's SQLi check.
_SQLI_PATTERN = re.compile(
    r"(;|--)\s*\b(drop|delete|truncate|alter|update|insert|exec|union)\b",
    re.IGNORECASE,
)


def _reject_if_suspicious(value: str, field_name: str) -> None:
    if _SQLI_PATTERN.search(value):
        raise SuspiciousInputError("Invalid characters detected")
    if len(value) > 255:
        raise SuspiciousInputError(f"{field_name} is too long")


@dataclass
class CategorisationRule:
    """A single user's merchant-pattern -> category mapping.

    merchant_pattern is stored upper-cased for case-insensitive substring
    matching (see find_matching_rule below) -- "STARBUCKS" matches a
    transaction description of "STARBUCKS #4521" via `in`, not an exact
    match, since bank exports append store numbers/locations to the base
    merchant name.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    merchant_pattern: str  # normalised upper-case
    category: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def new(user_id: uuid.UUID, merchant_pattern: str, category: str) -> "CategorisationRule":
        merchant_pattern = merchant_pattern.strip()
        if not merchant_pattern:
            raise SuspiciousInputError("Merchant pattern is required")
        _reject_if_suspicious(merchant_pattern, "Merchant pattern")

        category = category.strip()
        if not category:
            raise SuspiciousInputError("Category is required")
        _reject_if_suspicious(category, "Category")

        now = datetime.now(timezone.utc)
        return CategorisationRule(
            id=uuid.uuid4(),
            user_id=user_id,
            merchant_pattern=merchant_pattern.upper(),
            category=category,
            created_at=now,
            updated_at=now,
        )

    def apply_correction(self, category: str) -> None:
        """Used when an existing rule is upserted with a new category
        (the user corrected the same merchant again) -- mutates in place,
        repository is responsible for persisting."""
        category = category.strip()
        if not category:
            raise SuspiciousInputError("Category is required")
        _reject_if_suspicious(category, "Category")
        self.category = category
        self.updated_at = datetime.now(timezone.utc)


def find_matching_rule(
    rules: list[CategorisationRule], description: str
) -> CategorisationRule | None:
    """Case-insensitive substring match of a rule's merchant_pattern
    against a transaction's merchant/description text (AC1). Returns None
    if nothing matches -- callers should treat that as "low confidence",
    per AC2, and fall back to 'Uncategorised' rather than guessing.

    If multiple rules match, the longest pattern wins (most specific --
    e.g. a rule for "STARBUCKS" and a more specific one for "STARBUCKS
    AIRPORT" should prefer the latter for a description containing both).
    Ties broken by earliest created_at for determinism.
    """
    if not description:
        return None
    normalised = description.upper()
    candidates = [r for r in rules if r.merchant_pattern in normalised]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-len(r.merchant_pattern), r.created_at))
    return candidates[0]
