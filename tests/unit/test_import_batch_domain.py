"""Unit tests for the statement-import domain model (FINTRACK-16):
parse_csv_statement, sanitise_if_formula, is_valid_date/is_valid_amount,
StagedImport/StagedImportRow. Pure domain-layer tests -- no DB, no HTTP,
no auth. See tests/integration/test_imports_api.py for the real-API-level
equivalents and tests/security/test_imports_security.py for the mandatory
security sweep.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.domain.models.import_batch import (
    CorruptedFileError,
    RowStatus,
    StagedImport,
    StagedImportRow,
    is_valid_amount,
    is_valid_date,
    parse_csv_statement,
    sanitise_if_formula,
)

# ---------------------------------------------------------------------------
# sanitise_if_formula -- the CSV-formula-injection mitigation
# ---------------------------------------------------------------------------


def test_sanitise_if_formula_prefixes_equals_sign() -> None:
    value, sanitised = sanitise_if_formula('=cmd|\'/c calc\'!A1')
    assert sanitised is True
    assert value == "'=cmd|'/c calc'!A1"


def test_sanitise_if_formula_prefixes_plus_sign() -> None:
    value, sanitised = sanitise_if_formula("+1;DROP TABLE")
    assert sanitised is True
    assert value.startswith("'+")


def test_sanitise_if_formula_prefixes_minus_sign() -> None:
    value, sanitised = sanitise_if_formula("-2+3")
    assert sanitised is True
    assert value == "'-2+3"


def test_sanitise_if_formula_prefixes_at_sign() -> None:
    value, sanitised = sanitise_if_formula("@SUM(A1:A2)")
    assert sanitised is True
    assert value == "'@SUM(A1:A2)"


def test_sanitise_if_formula_prefixes_leading_tab() -> None:
    value, sanitised = sanitise_if_formula("\tmalicious")
    assert sanitised is True
    assert value.startswith("'\t")


def test_sanitise_if_formula_prefixes_leading_carriage_return() -> None:
    value, sanitised = sanitise_if_formula("\rmalicious")
    assert sanitised is True


def test_sanitise_if_formula_leaves_normal_text_untouched() -> None:
    value, sanitised = sanitise_if_formula("Coffee shop")
    assert sanitised is False
    assert value == "Coffee shop"


def test_sanitise_if_formula_leaves_empty_string_untouched() -> None:
    value, sanitised = sanitise_if_formula("")
    assert sanitised is False
    assert value == ""


def test_sanitise_if_formula_does_not_flag_a_trigger_char_mid_string() -> None:
    """Only a LEADING trigger char is dangerous to Excel/Sheets -- a
    normal sentence containing one of these characters elsewhere must not
    be flagged."""
    value, sanitised = sanitise_if_formula("Rent - July")
    assert sanitised is False
    assert value == "Rent - July"


# ---------------------------------------------------------------------------
# is_valid_date
# ---------------------------------------------------------------------------


def test_is_valid_date_accepts_iso_format() -> None:
    assert is_valid_date("2026-07-01") == date(2026, 7, 1)


def test_is_valid_date_accepts_us_slash_format() -> None:
    assert is_valid_date("07/01/2026") == date(2026, 7, 1)


def test_is_valid_date_accepts_dashed_us_format() -> None:
    assert is_valid_date("07-01-2026") == date(2026, 7, 1)


def test_is_valid_date_strips_whitespace() -> None:
    assert is_valid_date("  2026-07-01  ") == date(2026, 7, 1)


def test_is_valid_date_rejects_garbage_returns_none_not_raise() -> None:
    assert is_valid_date("not-a-date") is None


def test_is_valid_date_rejects_empty_string() -> None:
    assert is_valid_date("") is None


# ---------------------------------------------------------------------------
# is_valid_amount
# ---------------------------------------------------------------------------


def test_is_valid_amount_accepts_plain_decimal() -> None:
    assert is_valid_amount("12.50") == Decimal("12.50")


def test_is_valid_amount_strips_thousands_separator() -> None:
    assert is_valid_amount("1,234.56") == Decimal("1234.56")


def test_is_valid_amount_rejects_zero() -> None:
    assert is_valid_amount("0") is None
    assert is_valid_amount("0.00") is None


def test_is_valid_amount_rejects_negative() -> None:
    assert is_valid_amount("-5.00") is None


def test_is_valid_amount_rejects_more_than_two_decimal_places() -> None:
    assert is_valid_amount("10.999") is None


def test_is_valid_amount_rejects_non_numeric_returns_none_not_raise() -> None:
    assert is_valid_amount("not-a-number") is None
    assert is_valid_amount("=cmd|'/c calc'!A1") is None


# ---------------------------------------------------------------------------
# StagedImport / StagedImportRow -- counts and committable_rows
# ---------------------------------------------------------------------------


def _row(status: RowStatus, index: int = 0) -> StagedImportRow:
    return StagedImportRow(
        row_index=index,
        raw_date="2026-07-01",
        raw_amount="10.00",
        category="Groceries",
        note=None,
        status=status,
    )


def test_staged_import_counts_reflect_row_statuses() -> None:
    staged = StagedImport(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        rows=[
            _row(RowStatus.OK, 0),
            _row(RowStatus.OK, 1),
            _row(RowStatus.FLAGGED, 2),
            _row(RowStatus.INVALID, 3),
        ],
    )
    assert staged.found_count == 4
    assert staged.flagged_count == 1
    assert staged.invalid_count == 1


def test_committable_rows_includes_ok_and_flagged_excludes_invalid() -> None:
    ok_row = _row(RowStatus.OK, 0)
    flagged_row = _row(RowStatus.FLAGGED, 1)
    invalid_row = _row(RowStatus.INVALID, 2)
    staged = StagedImport(
        id=uuid.uuid4(), user_id=uuid.uuid4(), rows=[ok_row, flagged_row, invalid_row]
    )
    assert staged.committable_rows == [ok_row, flagged_row]


def test_staged_import_with_zero_rows_has_zero_counts_and_no_committable_rows() -> None:
    staged = StagedImport(id=uuid.uuid4(), user_id=uuid.uuid4(), rows=[])
    assert staged.found_count == 0
    assert staged.committable_rows == []


# ---------------------------------------------------------------------------
# parse_csv_statement -- happy path (Gherkin scenario 1)
# ---------------------------------------------------------------------------


def _csv_bytes(*data_rows: str, header: str = "Date,Amount,Description,Category") -> bytes:
    return (header + "\n" + "\n".join(data_rows) + "\n").encode("utf-8")


def test_parse_csv_statement_50_well_formed_rows_all_ok() -> None:
    """Matches Gherkin scenario 1 exactly: 50 well-formed transactions."""
    rows_text = [f"2026-07-{(i % 28) + 1:02d},{i + 1}.00,Purchase {i},Groceries" for i in range(50)]
    rows = parse_csv_statement(_csv_bytes(*rows_text))
    assert len(rows) == 50
    assert all(r.status == RowStatus.OK for r in rows)


def test_parse_csv_statement_defaults_empty_category_to_uncategorised() -> None:
    rows = parse_csv_statement(_csv_bytes("2026-07-01,10.00,Coffee,"))
    assert rows[0].category == "Uncategorised"


def test_parse_csv_statement_row_index_is_zero_based_position() -> None:
    rows = parse_csv_statement(_csv_bytes("2026-07-01,10.00,First,Food", "2026-07-02,20.00,Second,Food"))
    assert rows[0].row_index == 0
    assert rows[1].row_index == 1


def test_parse_csv_statement_flexible_header_matching() -> None:
    """AC2: parses date/amount/description columns even when the header
    names differ from the exact strings 'Date'/'Amount'/'Description' --
    real bank exports vary (e.g. 'Posted Date', 'Debit', 'Memo')."""
    csv_bytes = b"Posted Date,Debit,Memo\n2026-07-01,15.00,Groceries run\n"
    rows = parse_csv_statement(csv_bytes)
    assert len(rows) == 1
    assert rows[0].raw_date == "2026-07-01"
    assert rows[0].raw_amount == "15.00"
    assert rows[0].note == "Groceries run"


# ---------------------------------------------------------------------------
# parse_csv_statement -- corrupted file (Gherkin scenario 2)
# ---------------------------------------------------------------------------


def test_parse_csv_statement_rejects_undecodable_bytes() -> None:
    """Matches Gherkin scenario 2: a corrupted file must raise a clear
    error, not silently import a partial/garbage result."""
    with pytest.raises(CorruptedFileError, match="File is not valid UTF-8 text"):
        parse_csv_statement(b"\xff\xfe\x00\x01garbage-not-utf8")


def test_parse_csv_statement_rejects_missing_required_columns() -> None:
    with pytest.raises(CorruptedFileError, match="Could not find date/amount columns"):
        parse_csv_statement(b"Foo,Bar\n1,2\n")


def test_parse_csv_statement_rejects_empty_file_with_no_header() -> None:
    with pytest.raises(CorruptedFileError, match="File has no header row"):
        parse_csv_statement(b"")


# ---------------------------------------------------------------------------
# parse_csv_statement -- zero valid transactions (Gherkin scenario 3)
# ---------------------------------------------------------------------------


def test_parse_csv_statement_header_only_zero_data_rows_returns_empty_list_not_error() -> None:
    """Matches Gherkin scenario 3 exactly: a header row with no data rows
    is NOT corrupted -- it stages successfully showing "0 transactions
    found". This was a real bug found during this QA pass: the function
    previously raised CorruptedFileError here, contradicting the Gherkin.
    """
    rows = parse_csv_statement(b"Date,Amount,Description\n")
    assert rows == []


def test_parse_csv_statement_all_rows_invalid_is_not_an_error_either() -> None:
    """Distinct from the header-only case above: rows are present but
    every one fails date/amount validation. Also not a CorruptedFileError
    -- surfaced as RowStatus.INVALID on the review screen instead."""
    csv_bytes = _csv_bytes(
        "not-a-date,not-a-number,Junk,Food",
        "also-bad,still-bad,More junk,Food",
    )
    rows = parse_csv_statement(csv_bytes)
    assert len(rows) == 2
    assert all(r.status == RowStatus.INVALID for r in rows)


# ---------------------------------------------------------------------------
# parse_csv_statement -- CSV formula injection (Gherkin scenario 4)
# ---------------------------------------------------------------------------


def test_parse_csv_statement_flags_and_sanitises_formula_injection_in_description() -> None:
    """Matches Gherkin scenario 4 exactly: a description cell containing
    "=cmd|'/c calc'!A1" must be treated as inert text (never evaluated as
    a formula) and the row flagged with a warning."""
    csv_bytes = _csv_bytes("2026-07-01,10.00,\"=cmd|'/c calc'!A1\",Groceries")
    rows = parse_csv_statement(csv_bytes)
    assert len(rows) == 1
    assert rows[0].status == RowStatus.FLAGGED
    assert rows[0].note == "'=cmd|'/c calc'!A1"  # quote-prefixed, original preserved
    assert rows[0].warning == "Suspicious content sanitised (possible spreadsheet formula injection)"


def test_parse_csv_statement_flags_and_sanitises_formula_injection_in_category() -> None:
    csv_bytes = _csv_bytes("2026-07-01,10.00,Normal purchase,+1;DROP TABLE")
    rows = parse_csv_statement(csv_bytes)
    assert rows[0].status == RowStatus.FLAGGED
    assert rows[0].category == "'+1;DROP TABLE"


def test_parse_csv_statement_does_not_flag_normal_rows_alongside_a_flagged_one() -> None:
    csv_bytes = _csv_bytes(
        "2026-07-01,10.00,Normal purchase,Groceries",
        "2026-07-02,20.00,\"=HYPERLINK(malicious)\",Groceries",
    )
    rows = parse_csv_statement(csv_bytes)
    assert rows[0].status == RowStatus.OK
    assert rows[1].status == RowStatus.FLAGGED
