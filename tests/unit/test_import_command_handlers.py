"""Unit tests for the statement-import command handlers (FINTRACK-16):
StageImportHandler, UpdateStagedRowsHandler, CommitImportHandler. External
deps faked at the port boundary (FakeImportStagingRepository implements
the same ImportStagingRepository ABC the real Redis adapter does;
FakeTransactionRepository mirrors test_transaction_handlers.py's fake) --
no real DB or Redis in this file. See
tests/integration/test_imports_api.py for the real-API-level equivalents.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.api.application.commands.commit_import import (
    CommitImportCommand,
    CommitImportHandler,
    NothingToCommitError,
)
from apps.api.application.commands.stage_import import StageImportCommand, StageImportHandler
from apps.api.application.commands.update_staged_rows import (
    RowEdit,
    UpdateStagedRowsCommand,
    UpdateStagedRowsHandler,
)
from apps.api.domain.models.import_batch import CorruptedFileError, RowStatus, StagedImport
from apps.api.domain.models.transaction import Transaction
from apps.api.domain.repositories.import_staging_repository import StagedImportNotFoundError
from apps.api.domain.repositories.transaction_repository import TransactionPage


class FakeImportStagingRepository:
    """In-memory stand-in for RedisImportStagingRepository. Re-implements
    the user_id-scoping the real adapter's key (`import:{user_id}:{id}`)
    provides, in plain Python, so handler tests can prove the handlers
    themselves never bypass that scoping."""

    def __init__(self) -> None:
        self.store: dict[uuid.UUID, StagedImport] = {}

    async def save(self, staged_import: StagedImport) -> None:
        self.store[staged_import.id] = staged_import

    async def get(self, import_id: uuid.UUID, user_id: uuid.UUID) -> StagedImport:
        staged = self.store.get(import_id)
        if staged is None or staged.user_id != user_id:
            raise StagedImportNotFoundError(str(import_id))
        return staged

    async def delete(self, import_id: uuid.UUID, user_id: uuid.UUID) -> None:
        staged = self.store.get(import_id)
        if staged is not None and staged.user_id == user_id:
            del self.store[import_id]


class FakeTransactionRepository:
    """Same shape as test_transaction_handlers.py's fake -- only `add` is
    exercised by CommitImportHandler."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Transaction] = {}

    async def add(self, transaction: Transaction) -> None:
        self.rows[transaction.id] = transaction

    async def get_by_id_for_user(self, transaction_id: uuid.UUID, user_id: uuid.UUID):
        row = self.rows.get(transaction_id)
        if row is None or row.user_id != user_id:
            return None
        return row

    async def list_for_user(self, user_id: uuid.UUID, limit: int, cursor: str | None) -> TransactionPage:
        items = [t for t in self.rows.values() if t.user_id == user_id]
        return TransactionPage(items=items[:limit], next_cursor=None)

    async def update(self, transaction: Transaction) -> None:
        if transaction.id in self.rows:
            self.rows[transaction.id] = transaction

    async def delete(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        row = self.rows.get(transaction_id)
        if row is None or row.user_id != user_id:
            return False
        del self.rows[transaction_id]
        return True


@pytest.fixture
def staging() -> FakeImportStagingRepository:
    return FakeImportStagingRepository()


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


def _csv_bytes(*data_rows: str, header: str = "Date,Amount,Description,Category") -> bytes:
    return (header + "\n" + "\n".join(data_rows) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# StageImportHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_import_handler_persists_and_returns_staged_import(staging) -> None:
    user_id = uuid.uuid4()
    handler = StageImportHandler(staging_repository=staging)

    result = await handler.handle(
        StageImportCommand(
            user_id=user_id,
            file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"),
        )
    )

    assert result.id in staging.store
    assert result.found_count == 1
    assert result.user_id == user_id


@pytest.mark.asyncio
async def test_stage_import_handler_propagates_corrupted_file_error_and_saves_nothing(staging) -> None:
    handler = StageImportHandler(staging_repository=staging)

    with pytest.raises(CorruptedFileError):
        await handler.handle(StageImportCommand(user_id=uuid.uuid4(), file_bytes=b"not,a,valid,header\n1,2\n"))
    assert staging.store == {}


# ---------------------------------------------------------------------------
# UpdateStagedRowsHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_staged_rows_handler_fixes_an_invalid_row_and_revalidates(staging) -> None:
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=_csv_bytes("not-a-date,not-a-number,Junk,Food"))
    )
    assert staged.rows[0].status == RowStatus.INVALID

    update_handler = UpdateStagedRowsHandler(staging_repository=staging)
    updated = await update_handler.handle(
        UpdateStagedRowsCommand(
            user_id=user_id,
            import_id=staged.id,
            edits=[RowEdit(row_index=0, raw_date="2026-07-01", raw_amount="12.34")],
        )
    )

    assert updated.rows[0].status == RowStatus.OK
    assert updated.invalid_count == 0


@pytest.mark.asyncio
async def test_update_staged_rows_handler_re_flags_a_row_edited_to_contain_a_formula(staging) -> None:
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"))
    )
    assert staged.rows[0].status == RowStatus.OK

    update_handler = UpdateStagedRowsHandler(staging_repository=staging)
    updated = await update_handler.handle(
        UpdateStagedRowsCommand(
            user_id=user_id,
            import_id=staged.id,
            edits=[RowEdit(row_index=0, category="=cmd|'/c calc'!A1")],
        )
    )

    assert updated.rows[0].status == RowStatus.FLAGGED
    assert updated.rows[0].category.startswith("'=")


@pytest.mark.asyncio
async def test_update_staged_rows_handler_ignores_an_unknown_row_index(staging) -> None:
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"))
    )

    update_handler = UpdateStagedRowsHandler(staging_repository=staging)
    updated = await update_handler.handle(
        UpdateStagedRowsCommand(
            user_id=user_id,
            import_id=staged.id,
            edits=[RowEdit(row_index=999, raw_amount="1.00")],
        )
    )
    # No crash, no change to the one real row.
    assert updated.rows[0].raw_amount == "10.00"


@pytest.mark.asyncio
async def test_update_staged_rows_handler_raises_not_found_for_unknown_import(staging) -> None:
    handler = UpdateStagedRowsHandler(staging_repository=staging)
    with pytest.raises(StagedImportNotFoundError):
        await handler.handle(
            UpdateStagedRowsCommand(user_id=uuid.uuid4(), import_id=uuid.uuid4(), edits=[])
        )


@pytest.mark.asyncio
async def test_update_staged_rows_handler_raises_not_found_for_another_users_import(staging) -> None:
    """IDOR prevention at the handler layer, same pattern as
    UpdateTransactionHandler's equivalent test."""
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=owner_a, file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"))
    )

    update_handler = UpdateStagedRowsHandler(staging_repository=staging)
    with pytest.raises(StagedImportNotFoundError):
        await update_handler.handle(
            UpdateStagedRowsCommand(
                user_id=owner_b, import_id=staged.id, edits=[RowEdit(row_index=0, raw_amount="1.00")]
            )
        )


# ---------------------------------------------------------------------------
# CommitImportHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_import_handler_commits_ok_rows_with_entry_source_csv_import(staging, transactions) -> None:
    """AC5: reviewed rows use the same CreateTransactionCommand shape as
    manual entry, tagged entry_source=csv_import."""
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"))
    )

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    result = await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))

    assert result.committed_count == 1
    assert result.skipped_count == 0
    committed_txn = next(iter(transactions.rows.values()))
    assert committed_txn.entry_source == "csv_import"
    assert committed_txn.user_id == user_id
    assert str(committed_txn.amount) == "10.00"


@pytest.mark.asyncio
async def test_commit_import_handler_commits_flagged_rows_too(staging, transactions) -> None:
    """FLAGGED rows (sanitised, not rejected) are committable -- only
    INVALID rows are excluded."""
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(
            user_id=user_id, file_bytes=_csv_bytes("2026-07-01,10.00,\"=HYPERLINK(evil)\",Food")
        )
    )
    assert staged.rows[0].status == RowStatus.FLAGGED

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    result = await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))

    assert result.committed_count == 1
    committed_txn = next(iter(transactions.rows.values()))
    assert committed_txn.note.startswith("'=")  # sanitised value persisted, not the raw formula


@pytest.mark.asyncio
async def test_commit_import_handler_raises_nothing_to_commit_when_all_rows_invalid(staging, transactions) -> None:
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=_csv_bytes("not-a-date,not-a-number,Junk,Food"))
    )

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    with pytest.raises(NothingToCommitError):
        await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))
    assert transactions.rows == {}


@pytest.mark.asyncio
async def test_commit_import_handler_raises_nothing_to_commit_for_a_header_only_import(staging, transactions) -> None:
    """Matches Gherkin scenario 3's second assertion: "I should not be
    able to commit an empty import"."""
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=b"Date,Amount,Description\n")
    )
    assert staged.found_count == 0

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    with pytest.raises(NothingToCommitError):
        await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))


@pytest.mark.asyncio
async def test_commit_import_handler_skips_a_row_whose_amount_exceeds_the_maximum(staging, transactions) -> None:
    """Regression test for the bug found during this QA pass:
    AmountExceedsMaximumError must be caught per-row (skipped), not
    propagate as an unhandled exception and abort the whole commit.
    is_valid_amount() doesn't enforce MAX_TRANSACTION_AMOUNT, so a row at
    the exact rejected boundary (999999999.99, per ADR-010) stages as OK
    and only fails at commit time."""
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(
            user_id=user_id,
            file_bytes=_csv_bytes(
                "2026-07-01,10.00,Coffee,Food",
                "2026-07-02,999999999.99,Too big,Food",
            ),
        )
    )
    assert staged.rows[1].status == RowStatus.OK  # lighter check doesn't catch this

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    result = await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))

    assert result.committed_count == 1
    assert result.skipped_count == 1
    assert len(transactions.rows) == 1


@pytest.mark.asyncio
async def test_commit_import_handler_skips_a_row_whose_category_is_sqli_shaped(staging, transactions) -> None:
    """SQLi-shaped content (distinct from the formula-injection vector)
    isn't caught by sanitise_if_formula (it doesn't start with a trigger
    char), so it stages as OK -- Transaction.new()'s own
    SuspiciousInputError check is the actual defence-in-depth safety net
    at commit time, skipping just this row."""
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(
            user_id=user_id,
            file_bytes=_csv_bytes(
                "2026-07-01,10.00,Coffee,Food",
                "2026-07-02,20.00,Normal purchase,'; DROP TABLE transactions; --",
            ),
        )
    )
    assert staged.rows[1].status == RowStatus.OK

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    result = await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))

    assert result.committed_count == 1
    assert result.skipped_count == 1


@pytest.mark.asyncio
async def test_commit_import_handler_raises_not_found_for_unknown_import(staging, transactions) -> None:
    handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    with pytest.raises(StagedImportNotFoundError):
        await handler.handle(CommitImportCommand(user_id=uuid.uuid4(), import_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_commit_import_handler_raises_not_found_for_another_users_import(staging, transactions) -> None:
    """IDOR prevention: owner_b cannot commit owner_a's staged import."""
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=owner_a, file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"))
    )

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    with pytest.raises(StagedImportNotFoundError):
        await commit_handler.handle(CommitImportCommand(user_id=owner_b, import_id=staged.id))
    assert transactions.rows == {}


@pytest.mark.asyncio
async def test_commit_import_handler_deletes_the_staged_import_after_successful_commit(staging, transactions) -> None:
    user_id = uuid.uuid4()
    stage_handler = StageImportHandler(staging_repository=staging)
    staged = await stage_handler.handle(
        StageImportCommand(user_id=user_id, file_bytes=_csv_bytes("2026-07-01,10.00,Coffee,Food"))
    )

    commit_handler = CommitImportHandler(staging_repository=staging, transaction_repository=transactions)
    await commit_handler.handle(CommitImportCommand(user_id=user_id, import_id=staged.id))

    assert staged.id not in staging.store
