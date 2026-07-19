"""UpdateStagedRowsCommand + handler -- AC4: bulk-edit staged rows before
commit (e.g. fixing a row the parser marked INVALID, or re-categorising a
FLAGGED row). Story: FINTRACK-16.

Re-validates every edited row using the same public helpers
parse_csv_statement() itself uses (is_valid_date, is_valid_amount,
sanitise_if_formula) -- one source of truth for what counts as a valid /
flagged / invalid row, rather than a second copy of that logic here.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.import_batch import (
    RowStatus,
    StagedImport,
    is_valid_amount,
    is_valid_date,
    sanitise_if_formula,
)
from apps.api.domain.repositories.import_staging_repository import ImportStagingRepository


@dataclass(frozen=True)
class RowEdit:
    row_index: int
    raw_date: str | None = None
    raw_amount: str | None = None
    category: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class UpdateStagedRowsCommand:
    user_id: uuid.UUID
    import_id: uuid.UUID
    edits: list[RowEdit]


class UpdateStagedRowsHandler:
    def __init__(self, staging_repository: ImportStagingRepository) -> None:
        self._staging = staging_repository

    async def handle(self, command: UpdateStagedRowsCommand) -> StagedImport:
        # Raises StagedImportNotFoundError -- mapped to 404 at the API layer.
        staged_import = await self._staging.get(command.import_id, command.user_id)
        rows_by_index = {row.row_index: row for row in staged_import.rows}

        for edit in command.edits:
            row = rows_by_index.get(edit.row_index)
            if row is None:
                continue  # unknown row index -- ignored rather than aborting the whole batch

            if edit.raw_date is not None:
                row.raw_date = edit.raw_date.strip()
            if edit.raw_amount is not None:
                row.raw_amount = edit.raw_amount.strip()

            category_sanitised = False
            if edit.category is not None:
                stripped = edit.category.strip() or "Uncategorised"
                row.category, category_sanitised = sanitise_if_formula(stripped)
                # FINTRACK-17: a manual category edit during review is no
                # longer "the rule's suggestion" -- clear the audit
                # pointer so auto_categorised_count doesn't keep counting
                # a row the user has since overridden by hand.
                row.matched_rule_id = None

            note_sanitised = False
            if edit.note is not None:
                stripped_note = edit.note.strip()
                if stripped_note:
                    row.note, note_sanitised = sanitise_if_formula(stripped_note)
                else:
                    row.note, note_sanitised = None, False

            # Re-validate exactly the same way parse_csv_statement() did.
            if is_valid_date(row.raw_date) is None or is_valid_amount(row.raw_amount) is None:
                row.status = RowStatus.INVALID
                row.warning = "Could not parse date or amount for this row"
            elif category_sanitised or note_sanitised:
                row.status = RowStatus.FLAGGED
                row.warning = "Suspicious content sanitised (possible spreadsheet formula injection)"
            else:
                row.status = RowStatus.OK
                row.warning = None

        await self._staging.save(staged_import)
        return staged_import
