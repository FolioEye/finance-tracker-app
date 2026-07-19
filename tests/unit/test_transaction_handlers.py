"""Unit tests for the transaction command/query handlers. External deps
faked at the port boundary (FakeTransactionRepository implements the same
TransactionRepository ABC the real SQLAlchemy adapter does) -- no real DB
in this file. See tests/integration/test_transactions_api.py for the
real-API-level equivalents.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.api.application.commands.create_transaction import (
    CreateTransactionCommand,
    CreateTransactionHandler,
)
from apps.api.application.commands.delete_transaction import (
    DeleteTransactionCommand,
    DeleteTransactionHandler,
)
from apps.api.application.commands.update_transaction import (
    UpdateTransactionCommand,
    UpdateTransactionHandler,
)
from apps.api.application.queries.list_transactions import (
    MAX_PAGE_SIZE,
    ListTransactionsHandler,
    ListTransactionsQuery,
)
from apps.api.domain.models.transaction import (
    AmountExceedsMaximumError,
    InvalidAmountError,
    Money,
    SuspiciousInputError,
    Transaction,
)
from apps.api.domain.models.categorisation_rule import CategorisationRule
from apps.api.domain.repositories.transaction_repository import (
    TransactionNotFoundError,
    TransactionPage,
)


class FakeCategorisationRuleRepository:
    """In-memory stand-in for SqlAlchemyCategorisationRuleRepository.
    FINTRACK-17. Mirrors the real adapter's upsert semantics (one rule per
    normalised merchant_pattern per user) in plain Python -- no real DB in
    this file."""

    def __init__(self) -> None:
        self.rules: dict[uuid.UUID, CategorisationRule] = {}

    async def add(self, rule: CategorisationRule) -> None:
        self.rules[rule.id] = rule

    async def list_for_user(self, user_id: uuid.UUID) -> list[CategorisationRule]:
        return [r for r in self.rules.values() if r.user_id == user_id]

    async def find_by_pattern_for_user(self, user_id: uuid.UUID, merchant_pattern: str):
        normalised = merchant_pattern.strip().upper()
        for rule in self.rules.values():
            if rule.user_id == user_id and rule.merchant_pattern == normalised:
                return rule
        return None

    async def upsert(self, user_id: uuid.UUID, merchant_pattern: str, category: str) -> CategorisationRule:
        existing = await self.find_by_pattern_for_user(user_id, merchant_pattern)
        if existing is not None:
            existing.apply_correction(category)
            return existing
        rule = CategorisationRule.new(user_id=user_id, merchant_pattern=merchant_pattern, category=category)
        await self.add(rule)
        return rule


class FakeTransactionRepository:
    """In-memory stand-in for SqlAlchemyTransactionRepository. Deliberately
    re-implements the user_id-scoping the real adapter does at the SQL
    WHERE-clause level, in plain Python, so handler tests can prove the
    handlers themselves never bypass that scoping even with a repository
    that has zero SQL of its own to get right or wrong.
    """

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
        items.sort(key=lambda t: (t.created_at, t.id), reverse=True)
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
def repo() -> FakeTransactionRepository:
    return FakeTransactionRepository()


@pytest.fixture
def categorisation_rules() -> FakeCategorisationRuleRepository:
    return FakeCategorisationRuleRepository()


# ---------------------------------------------------------------------------
# CreateTransactionHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_transaction_handler_persists_and_returns_the_transaction(repo) -> None:
    user_id = uuid.uuid4()
    handler = CreateTransactionHandler(transaction_repository=repo)

    result = await handler.handle(
        CreateTransactionCommand(
            user_id=user_id,
            amount="42.50",
            category="Groceries",
            transaction_date=date(2026, 7, 2),
            note="Weekly shop",
        )
    )

    assert result.id in repo.rows
    assert str(result.amount) == "42.50"
    assert result.user_id == user_id


@pytest.mark.asyncio
async def test_create_transaction_handler_propagates_invalid_amount_error(repo) -> None:
    handler = CreateTransactionHandler(transaction_repository=repo)

    with pytest.raises(InvalidAmountError):
        await handler.handle(
            CreateTransactionCommand(
                user_id=uuid.uuid4(),
                amount="-15.00",
                category="Groceries",
                transaction_date=date(2026, 7, 2),
            )
        )
    assert repo.rows == {}


@pytest.mark.asyncio
async def test_create_transaction_handler_propagates_amount_exceeds_maximum_error(repo) -> None:
    handler = CreateTransactionHandler(transaction_repository=repo)

    with pytest.raises(AmountExceedsMaximumError):
        await handler.handle(
            CreateTransactionCommand(
                user_id=uuid.uuid4(),
                amount="999999999.99",
                category="Groceries",
                transaction_date=date(2026, 7, 2),
            )
        )
    assert repo.rows == {}


@pytest.mark.asyncio
async def test_create_transaction_handler_propagates_suspicious_input_error(repo) -> None:
    handler = CreateTransactionHandler(transaction_repository=repo)

    with pytest.raises(SuspiciousInputError):
        await handler.handle(
            CreateTransactionCommand(
                user_id=uuid.uuid4(),
                amount="42.50",
                category="Groceries",
                transaction_date=date(2026, 7, 2),
                note="'; DROP TABLE transactions; --",
            )
        )
    assert repo.rows == {}


# ---------------------------------------------------------------------------
# UpdateTransactionHandler -- AC5, no Gherkin coverage (QA Lead gap-fill)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_transaction_handler_applies_a_partial_update(repo, categorisation_rules) -> None:
    user_id = uuid.uuid4()
    handler_create = CreateTransactionHandler(transaction_repository=repo)
    created = await handler_create.handle(
        CreateTransactionCommand(
            user_id=user_id, amount="42.50", category="Groceries", transaction_date=date(2026, 7, 2)
        )
    )

    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    updated = await handler.handle(
        UpdateTransactionCommand(transaction_id=created.id, user_id=user_id, amount="55.00")
    )

    assert str(updated.amount) == "55.00"
    assert updated.category == "Groceries"  # untouched


@pytest.mark.asyncio
async def test_update_transaction_handler_raises_not_found_for_unknown_id(repo, categorisation_rules) -> None:
    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    with pytest.raises(TransactionNotFoundError):
        await handler.handle(
            UpdateTransactionCommand(transaction_id=uuid.uuid4(), user_id=uuid.uuid4(), amount="10.00")
        )


@pytest.mark.asyncio
async def test_update_transaction_handler_raises_not_found_for_another_users_transaction(
    repo, categorisation_rules
) -> None:
    """IDOR prevention at the handler layer: owner_a's transaction must be
    invisible to owner_b, surfaced as the same TransactionNotFoundError a
    truly-nonexistent id would raise -- not a distinguishable 403."""
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    handler_create = CreateTransactionHandler(transaction_repository=repo)
    created = await handler_create.handle(
        CreateTransactionCommand(
            user_id=owner_a, amount="42.50", category="Groceries", transaction_date=date(2026, 7, 2)
        )
    )

    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    with pytest.raises(TransactionNotFoundError):
        await handler.handle(
            UpdateTransactionCommand(transaction_id=created.id, user_id=owner_b, amount="99.00")
        )


# ---------------------------------------------------------------------------
# UpdateTransactionHandler -- FINTRACK-17 AC3 correction-feedback loop
# (Gherkin scenario 5: "User's manual category correction updates their
# personal rule set")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_transaction_handler_creates_a_rule_when_correcting_an_imported_uncategorised_transaction(
    repo, categorisation_rules
) -> None:
    user_id = uuid.uuid4()
    txn = Transaction.new(
        user_id=user_id,
        amount=Money.parse("42.50"),
        category="Uncategorised",
        transaction_date=date(2026, 7, 2),
        note="XZQ HOLDINGS LLC",
        entry_source="csv_import",
    )
    await repo.add(txn)

    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    await handler.handle(
        UpdateTransactionCommand(transaction_id=txn.id, user_id=user_id, category="Business Expenses")
    )

    rules = await categorisation_rules.list_for_user(user_id)
    assert len(rules) == 1
    assert rules[0].merchant_pattern == "XZQ HOLDINGS LLC"
    assert rules[0].category == "Business Expenses"


@pytest.mark.asyncio
async def test_update_transaction_handler_does_not_create_a_rule_for_a_manual_entry(
    repo, categorisation_rules
) -> None:
    """AC3's Gherkin is explicit about "an imported transaction" -- a
    manual entry correction (entry_source="manual") must not feed the
    rule set, even if its category happens to be the literal string
    "Uncategorised"."""
    user_id = uuid.uuid4()
    handler_create = CreateTransactionHandler(transaction_repository=repo)
    created = await handler_create.handle(
        CreateTransactionCommand(
            user_id=user_id,
            amount="42.50",
            category="Uncategorised",
            transaction_date=date(2026, 7, 2),
            note="XZQ HOLDINGS LLC",
        )
    )
    assert created.entry_source == "manual"

    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    await handler.handle(
        UpdateTransactionCommand(transaction_id=created.id, user_id=user_id, category="Business Expenses")
    )

    assert await categorisation_rules.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_update_transaction_handler_does_not_create_a_rule_when_category_stays_uncategorised(
    repo, categorisation_rules
) -> None:
    user_id = uuid.uuid4()
    txn = Transaction.new(
        user_id=user_id,
        amount=Money.parse("42.50"),
        category="Uncategorised",
        transaction_date=date(2026, 7, 2),
        note="XZQ HOLDINGS LLC",
        entry_source="csv_import",
    )
    await repo.add(txn)

    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    # Update something other than category -- no correction happened.
    await handler.handle(UpdateTransactionCommand(transaction_id=txn.id, user_id=user_id, amount="10.00"))

    assert await categorisation_rules.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_update_transaction_handler_upserts_rather_than_duplicates_on_repeated_correction(
    repo, categorisation_rules
) -> None:
    """A second correction for the same merchant updates the existing
    rule's category rather than creating a second one -- backs AC3's
    "personal rule set" framing (one current mapping per merchant, not an
    append-only history)."""
    user_id = uuid.uuid4()
    txn_1 = Transaction.new(
        user_id=user_id,
        amount=Money.parse("10.00"),
        category="Uncategorised",
        transaction_date=date(2026, 7, 1),
        note="XZQ HOLDINGS LLC",
        entry_source="csv_import",
    )
    txn_2 = Transaction.new(
        user_id=user_id,
        amount=Money.parse("20.00"),
        category="Uncategorised",
        transaction_date=date(2026, 7, 2),
        note="XZQ HOLDINGS LLC",
        entry_source="csv_import",
    )
    await repo.add(txn_1)
    await repo.add(txn_2)

    handler = UpdateTransactionHandler(
        transaction_repository=repo, categorisation_rule_repository=categorisation_rules
    )
    await handler.handle(
        UpdateTransactionCommand(transaction_id=txn_1.id, user_id=user_id, category="Business Expenses")
    )
    await handler.handle(
        UpdateTransactionCommand(transaction_id=txn_2.id, user_id=user_id, category="Office Supplies")
    )

    rules = await categorisation_rules.list_for_user(user_id)
    assert len(rules) == 1
    assert rules[0].category == "Office Supplies"


# ---------------------------------------------------------------------------
# DeleteTransactionHandler -- AC5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_transaction_handler_deletes_an_owned_transaction(repo) -> None:
    user_id = uuid.uuid4()
    handler_create = CreateTransactionHandler(transaction_repository=repo)
    created = await handler_create.handle(
        CreateTransactionCommand(
            user_id=user_id, amount="42.50", category="Groceries", transaction_date=date(2026, 7, 2)
        )
    )

    handler = DeleteTransactionHandler(transaction_repository=repo)
    await handler.handle(DeleteTransactionCommand(transaction_id=created.id, user_id=user_id))

    assert created.id not in repo.rows


@pytest.mark.asyncio
async def test_delete_transaction_handler_raises_not_found_for_unknown_id(repo) -> None:
    handler = DeleteTransactionHandler(transaction_repository=repo)
    with pytest.raises(TransactionNotFoundError):
        await handler.handle(DeleteTransactionCommand(transaction_id=uuid.uuid4(), user_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_delete_transaction_handler_raises_not_found_for_another_users_transaction(repo) -> None:
    """IDOR prevention: owner_b cannot delete owner_a's transaction."""
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    handler_create = CreateTransactionHandler(transaction_repository=repo)
    created = await handler_create.handle(
        CreateTransactionCommand(
            user_id=owner_a, amount="42.50", category="Groceries", transaction_date=date(2026, 7, 2)
        )
    )

    handler = DeleteTransactionHandler(transaction_repository=repo)
    with pytest.raises(TransactionNotFoundError):
        await handler.handle(DeleteTransactionCommand(transaction_id=created.id, user_id=owner_b))

    assert created.id in repo.rows  # untouched


# ---------------------------------------------------------------------------
# ListTransactionsHandler -- AC4 ("appears immediately in list")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_transactions_handler_returns_only_the_requesting_users_transactions(repo) -> None:
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    handler_create = CreateTransactionHandler(transaction_repository=repo)
    await handler_create.handle(
        CreateTransactionCommand(
            user_id=owner_a, amount="10.00", category="Groceries", transaction_date=date(2026, 7, 1)
        )
    )
    await handler_create.handle(
        CreateTransactionCommand(
            user_id=owner_b, amount="20.00", category="Fuel", transaction_date=date(2026, 7, 1)
        )
    )

    handler = ListTransactionsHandler(transaction_repository=repo)
    page = await handler.handle(ListTransactionsQuery(user_id=owner_a))

    assert len(page.items) == 1
    assert page.items[0].user_id == owner_a


@pytest.mark.asyncio
async def test_list_transactions_handler_clamps_limit_to_max_page_size(repo) -> None:
    handler = ListTransactionsHandler(transaction_repository=repo)
    # FakeTransactionRepository.list_for_user just slices by whatever limit
    # it's handed -- the clamping behaviour under test lives in the handler
    # itself (max(1, min(limit, MAX_PAGE_SIZE))), so this proves the
    # handler, not the repository, enforces the ceiling.
    captured_limits: list[int] = []
    original_list_for_user = repo.list_for_user

    async def capturing_list_for_user(user_id, limit, cursor):
        captured_limits.append(limit)
        return await original_list_for_user(user_id, limit, cursor)

    repo.list_for_user = capturing_list_for_user

    await handler.handle(ListTransactionsQuery(user_id=uuid.uuid4(), limit=999999))
    assert captured_limits == [MAX_PAGE_SIZE]


@pytest.mark.asyncio
async def test_list_transactions_handler_clamps_limit_to_at_least_one(repo) -> None:
    handler = ListTransactionsHandler(transaction_repository=repo)
    captured_limits: list[int] = []
    original_list_for_user = repo.list_for_user

    async def capturing_list_for_user(user_id, limit, cursor):
        captured_limits.append(limit)
        return await original_list_for_user(user_id, limit, cursor)

    repo.list_for_user = capturing_list_for_user

    await handler.handle(ListTransactionsQuery(user_id=uuid.uuid4(), limit=0))
    assert captured_limits == [1]
