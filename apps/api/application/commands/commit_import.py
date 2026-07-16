"""CommitImportCommand + handler -- AC5: commits a staged import's
committable rows through the exact same Money.parse() / Transaction.new()
/ TransactionRepository.add() path FINTRACK-15 already built and tested,
with entry_source="csv_import" (the same CreateTransactionCommand shape
as manual entry, per the PM's epic-level architecture constraint).
Story: FINTRACK-16.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.import_batch import is_valid_date
from apps.api.domain.models.transaction import (
    AmountExceedsMaximumError,
    InvalidAmountError,
    Money,
    SuspiciousInputError,
    Transaction,
)
from apps.api.domain.repositories.import_staging_repository import ImportStagingRepository
from apps.api.domain.repositories.transaction_repository import TransactionRepository


class NothingToCommitError(ValueError):
    """Raised when a staged import has zero committable rows (all rows
    are INVALID) -- mapped to 400 at the API layer rather than silently
    committing nothing."""


@dataclass(frozen=True)
class CommitImportCommand:
    user_id: uuid.UUID
    import_id: uuid.UUID


@dataclass(frozen=True)
class CommitImportResult:
    committed_count: int
    skipped_count: int


class CommitImportHandler:
    def __init__(
        self,
        staging_repository: ImportStagingRepository,
        transaction_repository: TransactionRepository,
    ) -> None:
        self._staging = staging_repository
        self._transactions = transaction_repository

    async def handle(self, command: CommitImportCommand) -> CommitImportResult:
        # Raises StagedImportNotFoundError -- mapped to 404 at the API layer.
        staged_import = await self._staging.get(command.import_id, command.user_id)

        committable = staged_import.committable_rows
        if not committable:
            raise NothingToCommitError("No committable rows in this import")

        committed = 0
        skipped = 0
        for row in committable:
            # Re-validate through the domain layer's own authoritative
            # validators as a final per-row safety net -- committable_rows
            # already passed the lighter is_valid_*/sanitise_if_formula
            # checks at stage/edit time, but Money.parse()/Transaction.new()
            # are the actual source of truth (e.g. the exact
            # MAX_TRANSACTION_AMOUNT ceiling) and a failure here skips just
            # this one row rather than aborting the whole commit.
            transaction_date = is_valid_date(row.raw_date)
            if transaction_date is None:
                skipped += 1
                continue

            try:
                amount = Money.parse(row.raw_amount)
                transaction = Transaction.new(
                    user_id=command.user_id,
                    amount=amount,
                    category=row.category,
                    transaction_date=transaction_date,
                    note=row.note,
                    entry_source="csv_import",
                )
                await self._transactions.add(transaction)
                committed += 1
            except (InvalidAmountError, AmountExceedsMaximumError, SuspiciousInputError):
                # AmountExceedsMaximumError found missing from this tuple
                # during QA Lead's test-writing pass: is_valid_amount()'s
                # lighter check doesn't enforce MAX_TRANSACTION_AMOUNT, so
                # a row could pass staging/edit and still hit this ceiling
                # only at commit time -- without this exception type here,
                # that would have propagated as an unhandled 500 instead
                # of skipping just the one row as intended.
                skipped += 1
                continue

        await self._staging.delete(command.import_id, command.user_id)
        return CommitImportResult(committed_count=committed, skipped_count=skipped)
