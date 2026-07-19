"""Unit tests for the categorisation-rule domain model (FINTRACK-17):
CategorisationRule.new/apply_correction, find_matching_rule, and
import_batch.py's apply_auto_categorisation. Pure domain-layer tests -- no
DB, no HTTP, no auth. See tests/integration/test_categorisation_rules_api.py
for the real-API-level equivalents and
tests/security/test_categorisation_rules_security.py for the mandatory
security sweep.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.domain.models.categorisation_rule import (
    CategorisationRule,
    SuspiciousInputError,
    find_matching_rule,
)
from apps.api.domain.models.import_batch import (
    RowStatus,
    StagedImportRow,
    apply_auto_categorisation,
)

# ---------------------------------------------------------------------------
# CategorisationRule.new
# ---------------------------------------------------------------------------


def test_new_normalises_merchant_pattern_to_upper_case() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="  starbucks  ", category="Coffee & Dining")
    assert rule.merchant_pattern == "STARBUCKS"


def test_new_strips_and_keeps_category_case_as_given() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="  Coffee & Dining  ")
    assert rule.category == "Coffee & Dining"


def test_new_assigns_a_fresh_id_and_timestamps() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="Coffee & Dining")
    assert isinstance(rule.id, uuid.UUID)
    assert rule.created_at == rule.updated_at


def test_new_rejects_empty_merchant_pattern() -> None:
    with pytest.raises(SuspiciousInputError, match="Merchant pattern is required"):
        CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="   ", category="Coffee & Dining")


def test_new_rejects_empty_category() -> None:
    with pytest.raises(SuspiciousInputError, match="Category is required"):
        CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="   ")


def test_new_rejects_sqli_shaped_merchant_pattern() -> None:
    """Matches the BA's Gherkin scenario 4 exactly."""
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        CategorisationRule.new(
            user_id=uuid.uuid4(), merchant_pattern="'; DROP TABLE rules; --", category="Groceries"
        )


def test_new_rejects_sqli_shaped_category() -> None:
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        CategorisationRule.new(
            user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="'; DROP TABLE rules; --"
        )


def test_new_rejects_overlong_merchant_pattern() -> None:
    with pytest.raises(SuspiciousInputError, match="too long"):
        CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="A" * 256, category="Groceries")


def test_new_rejects_overlong_category() -> None:
    with pytest.raises(SuspiciousInputError, match="too long"):
        CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="A" * 256)


# ---------------------------------------------------------------------------
# CategorisationRule.apply_correction
# ---------------------------------------------------------------------------


def test_apply_correction_updates_category_in_place() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="Coffee & Dining")
    original_updated_at = rule.updated_at
    rule.apply_correction("Business Expenses")
    assert rule.category == "Business Expenses"
    assert rule.updated_at >= original_updated_at


def test_apply_correction_does_not_change_merchant_pattern_or_id() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="Coffee & Dining")
    rule_id, pattern = rule.id, rule.merchant_pattern
    rule.apply_correction("Business Expenses")
    assert rule.id == rule_id
    assert rule.merchant_pattern == pattern


def test_apply_correction_rejects_empty_category() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="Coffee & Dining")
    with pytest.raises(SuspiciousInputError, match="Category is required"):
        rule.apply_correction("   ")


def test_apply_correction_rejects_sqli_shaped_category() -> None:
    rule = CategorisationRule.new(user_id=uuid.uuid4(), merchant_pattern="Starbucks", category="Coffee & Dining")
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        rule.apply_correction("'; DROP TABLE rules; --")


# ---------------------------------------------------------------------------
# find_matching_rule
# ---------------------------------------------------------------------------


def _rule(user_id: uuid.UUID, pattern: str, category: str, created_at: datetime | None = None) -> CategorisationRule:
    return CategorisationRule(
        id=uuid.uuid4(),
        user_id=user_id,
        merchant_pattern=pattern,
        category=category,
        created_at=created_at or datetime.now(timezone.utc),
        updated_at=created_at or datetime.now(timezone.utc),
    )


def test_find_matching_rule_matches_substring_case_insensitively() -> None:
    """Matches the BA's Gherkin scenario 1 exactly."""
    user_id = uuid.uuid4()
    rule = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    matched = find_matching_rule([rule], "STARBUCKS #4521")
    assert matched is rule


def test_find_matching_rule_returns_none_when_nothing_matches() -> None:
    """Matches the BA's Gherkin scenario 2 exactly."""
    user_id = uuid.uuid4()
    rule = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    assert find_matching_rule([rule], "XZQ HOLDINGS LLC") is None


def test_find_matching_rule_returns_none_for_empty_description() -> None:
    user_id = uuid.uuid4()
    rule = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    assert find_matching_rule([rule], "") is None


def test_find_matching_rule_returns_none_for_empty_rule_list() -> None:
    assert find_matching_rule([], "STARBUCKS #4521") is None


def test_find_matching_rule_prefers_longest_pattern_when_multiple_match() -> None:
    user_id = uuid.uuid4()
    general = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    specific = _rule(user_id, "STARBUCKS AIRPORT", "Travel")
    matched = find_matching_rule([general, specific], "STARBUCKS AIRPORT #99")
    assert matched is specific


def test_find_matching_rule_breaks_ties_by_earliest_created_at() -> None:
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    older = _rule(user_id, "STARBUCKS", "Coffee & Dining", created_at=now - timedelta(days=1))
    newer = _rule(user_id, "STARBUCKS", "Snacks", created_at=now)
    matched = find_matching_rule([newer, older], "STARBUCKS #4521")
    assert matched is older


# ---------------------------------------------------------------------------
# apply_auto_categorisation (import_batch.py)
# ---------------------------------------------------------------------------


def _row(note: str | None, status: RowStatus = RowStatus.OK, category: str = "Uncategorised") -> StagedImportRow:
    return StagedImportRow(
        row_index=0,
        raw_date="2026-07-01",
        raw_amount="10.00",
        category=category,
        note=note,
        status=status,
    )


def test_apply_auto_categorisation_assigns_category_from_matching_rule() -> None:
    """Matches the BA's Gherkin scenario 1: a matched rule's category is
    assigned, and the row records which rule produced the match."""
    user_id = uuid.uuid4()
    rule = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    row = _row(note="STARBUCKS #4521")
    apply_auto_categorisation([row], [rule])
    assert row.category == "Coffee & Dining"
    assert row.matched_rule_id == rule.id


def test_apply_auto_categorisation_falls_back_to_uncategorised_when_no_match() -> None:
    """Matches the BA's Gherkin scenario 2 exactly, and overrides whatever
    the CSV's own category column held (ADR-012's deliberate supersession
    of FINTRACK-16's category-column pass-through)."""
    row = _row(note="XZQ HOLDINGS LLC", category="Some CSV Category")
    apply_auto_categorisation([row], [])
    assert row.category == "Uncategorised"
    assert row.matched_rule_id is None


def test_apply_auto_categorisation_overrides_csv_category_column_even_on_match() -> None:
    user_id = uuid.uuid4()
    rule = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    row = _row(note="STARBUCKS #4521", category="Whatever The CSV Said")
    apply_auto_categorisation([row], [rule])
    assert row.category == "Coffee & Dining"


def test_apply_auto_categorisation_skips_invalid_rows() -> None:
    user_id = uuid.uuid4()
    rule = _rule(user_id, "STARBUCKS", "Coffee & Dining")
    row = _row(note="STARBUCKS #4521", status=RowStatus.INVALID, category="Uncategorised")
    apply_auto_categorisation([row], [rule])
    # Left untouched -- INVALID rows aren't committable regardless of category.
    assert row.category == "Uncategorised"
    assert row.matched_rule_id is None


def test_apply_auto_categorisation_flags_a_formula_injection_payload_in_rule_category() -> None:
    """Defence-in-depth: a rule's own category shouldn't be able to carry
    a spreadsheet-formula-injection payload through to the review screen
    unflagged, even though CategorisationRule.new() doesn't itself check
    for this (only for SQLi-shaped input)."""
    user_id = uuid.uuid4()
    rule = CategorisationRule(
        id=uuid.uuid4(),
        user_id=user_id,
        merchant_pattern="STARBUCKS",
        category="=cmd|'/c calc'!A1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    row = _row(note="STARBUCKS #4521", status=RowStatus.OK)
    apply_auto_categorisation([row], [rule])
    assert row.category.startswith("'=")
    assert row.status == RowStatus.FLAGGED
    assert row.warning == "Suspicious content sanitised (possible spreadsheet formula injection)"


def test_apply_auto_categorisation_handles_empty_rows_list() -> None:
    apply_auto_categorisation([], [])  # must not raise


def test_apply_auto_categorisation_handles_row_with_no_note() -> None:
    row = _row(note=None, category="Whatever")
    apply_auto_categorisation([row], [])
    assert row.category == "Uncategorised"
