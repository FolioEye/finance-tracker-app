"""Domain model for statement/CSV import staging. Story: FINTRACK-16.

Two-phase flow per the PM's epic-level architecture constraint (manual
entry, CSV import, and receipt OCR all produce the same
CreateTransactionCommand, staged pending user confirmation before
commit): parse_csv_statement() turns raw upload bytes into a StagedImport
of StagedImportRow objects; the user reviews/edits (AC3/AC4) before
commit_import.py replays each committable row through the exact same
Transaction.new() / TransactionRepository.add() path FINTRACK-15 built
and tested.

Scope: CSV only for this pass. AC1 nominally says "CSV/PDF/XLSX" but none
of the BA's 4 Gherkin scenarios exercise PDF or XLSX -- PDF/XLSX parsing
is a documented, deferred gap (see
docs/adr/ADR-011-statement-import-staged-review.md), not implemented
here, mirroring the same AC/Gherkin-mismatch-flagging discipline used for
FINTRACK-15's AC4/AC5 gaps.
"""
from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum


class CorruptedFileError(ValueError):
    """Raised only when the whole file can't be safely reviewed at all --
    undecodable bytes, no header row, missing a required column, or zero
    data rows. AC6: "clear error, not a silent partial import". A file
    that parses structurally but whose rows fail date/amount validation
    is NOT corrupted -- see RowStatus.INVALID below, which is surfaced on
    the review screen (AC3) instead, since the BA's zero-valid-rows
    scenario expects a normal staged-import response with 0 committable
    rows, not an exception.
    """


class RowStatus(str, Enum):
    OK = "ok"
    FLAGGED = "flagged"  # parsed but sanitised (e.g. formula-injection char stripped-and-quoted)
    INVALID = "invalid"  # unparseable date/amount -- excluded from commit until the user edits it


# Same class of attack as FINTRACK-15's SQLi check, but for the
# spreadsheet-formula-injection vector: a leading one of these characters
# makes Excel/Sheets evaluate the cell as a formula when the exported
# file is later reopened. Mitigation here is prefix-with-quote (preserve
# + neutralise), not reject -- deliberately different from FINTRACK-15's
# SQLi handling (hard 400 reject), because this Gherkin wants "sanitised"
# + a warning + continued processing, not an outright rejection of the
# whole row.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitise_if_formula(value: str) -> tuple[str, bool]:
    """Returns (possibly-sanitised value, was_sanitised). Prefixes with a
    single quote so Excel/Sheets render the cell as literal text rather
    than evaluating it, while preserving the original characters for user
    visibility -- the AC calls for "flagged", not silently stripped."""
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return f"'{value}", True
    return value, False


def is_valid_date(raw: str) -> date_type | None:
    """Tries a small set of common statement date formats. Returns None
    rather than raising, so callers can mark just this one row INVALID
    instead of aborting the whole batch -- a single bad row must not sink
    AC3's "X found, Y flagged" review screen for the other 49."""
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def is_valid_amount(raw: str) -> Decimal | None:
    """Mirrors Money.parse()'s shape (positive, <=2dp) but returns None
    instead of raising -- same per-row-not-whole-batch reasoning as
    is_valid_date(). Thousands separators are stripped since statement
    exports commonly include them (Money.parse() itself does not need to,
    since manual entry never types a comma)."""
    raw = raw.strip().replace(",", "")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if amount <= 0:
        return None
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return None
    return amount


@dataclass
class StagedImportRow:
    row_index: int  # 0-based position in the uploaded file, for user-facing "row N" messages
    raw_date: str
    raw_amount: str
    category: str
    note: str | None
    status: RowStatus
    warning: str | None = None


@dataclass
class StagedImport:
    id: uuid.UUID
    user_id: uuid.UUID
    rows: list[StagedImportRow]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def found_count(self) -> int:
        return len(self.rows)

    @property
    def flagged_count(self) -> int:
        return sum(1 for r in self.rows if r.status == RowStatus.FLAGGED)

    @property
    def invalid_count(self) -> int:
        return sum(1 for r in self.rows if r.status == RowStatus.INVALID)

    @property
    def committable_rows(self) -> list[StagedImportRow]:
        """OK and FLAGGED rows are committable -- flagged rows were
        sanitised, not rejected. INVALID rows are excluded until the user
        edits them via update_staged_rows.py (AC4)."""
        return [r for r in self.rows if r.status in (RowStatus.OK, RowStatus.FLAGGED)]


# Flexible header matching -- bank export column names vary widely and
# this story's Gherkin doesn't mandate a fixed schema, only that "date/
# amount/description columns" (AC2) get parsed.
_DATE_HEADER_CANDIDATES = ("date", "transaction date", "posted date", "posting date")
_AMOUNT_HEADER_CANDIDATES = ("amount", "value", "debit", "transaction amount")
_DESCRIPTION_HEADER_CANDIDATES = ("description", "memo", "note", "details", "narrative")
_CATEGORY_HEADER_CANDIDATES = ("category", "type")


def _find_column(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {f.strip().lower(): f for f in fieldnames}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def parse_csv_statement(raw_bytes: bytes) -> list[StagedImportRow]:
    """Parses a CSV bank statement export into staged rows for review.

    Raises CorruptedFileError only for cases that would otherwise produce
    a silent partial import (AC6): undecodable bytes, no header row,
    missing a required date/amount column, or zero data rows at all.
    Rows with unparseable date/amount values are NOT an error here --
    they're marked RowStatus.INVALID and surfaced on the review screen
    (AC3's "X found, Y flagged"), matching the BA's zero-valid-rows edge
    case, which expects a normal (if all-invalid) staged import back, not
    an exception.
    """
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CorruptedFileError("File is not valid UTF-8 text") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CorruptedFileError("File has no header row")

    date_col = _find_column(reader.fieldnames, _DATE_HEADER_CANDIDATES)
    amount_col = _find_column(reader.fieldnames, _AMOUNT_HEADER_CANDIDATES)
    if date_col is None or amount_col is None:
        raise CorruptedFileError(
            "Could not find date/amount columns -- expected headers like 'Date' and 'Amount'"
        )
    description_col = _find_column(reader.fieldnames, _DESCRIPTION_HEADER_CANDIDATES)
    category_col = _find_column(reader.fieldnames, _CATEGORY_HEADER_CANDIDATES)

    rows: list[StagedImportRow] = []
    for index, record in enumerate(reader):
        raw_date = (record.get(date_col) or "").strip()
        raw_amount = (record.get(amount_col) or "").strip()
        raw_category = (record.get(category_col) or "").strip() if category_col else ""
        raw_note = (record.get(description_col) or "").strip() if description_col else ""

        category, category_sanitised = sanitise_if_formula(raw_category or "Uncategorised")
        note, note_sanitised = sanitise_if_formula(raw_note) if raw_note else (raw_note, False)

        status = RowStatus.OK
        warning: str | None = None

        if is_valid_date(raw_date) is None or is_valid_amount(raw_amount) is None:
            status = RowStatus.INVALID
            warning = "Could not parse date or amount for this row"
        elif category_sanitised or note_sanitised:
            status = RowStatus.FLAGGED
            warning = "Suspicious content sanitised (possible spreadsheet formula injection)"

        rows.append(
            StagedImportRow(
                row_index=index,
                raw_date=raw_date,
                raw_amount=raw_amount,
                category=category,
                note=note or None,
                status=status,
                warning=warning,
            )
        )

    if not rows:
        raise CorruptedFileError("File contains no data rows")

    return rows
