"""SQLAlchemy adapter implementing the TransactionRepository port.

Every query goes through SQLAlchemy's parameterised query builder -- no
string-concatenated SQL exists anywhere in this file. Every query is also
filtered by user_id, never trusting a client-supplied identifier alone,
per this project's IDOR-prevention discipline.
"""
from __future__ import annotations

import base64
import uuid
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, delete, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.transaction import Money, Transaction
from apps.api.domain.repositories.transaction_repository import (
    TransactionPage,
    TransactionRepository,
)
from apps.api.infrastructure.database.models import TransactionModel


def _to_domain(row: TransactionModel) -> Transaction:
    return Transaction(
        id=row.id,
        user_id=row.user_id,
        amount=Money(value=row.amount),
        category=row.category,
        transaction_date=row.transaction_date,
        note=row.note,
        entry_source=row.entry_source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts_str, id_str = raw.split("|", 1)
    return datetime.fromisoformat(ts_str), uuid.UUID(id_str)


class SqlAlchemyTransactionRepository(TransactionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, transaction: Transaction) -> None:
        # created_at/updated_at are set explicitly from the domain object
        # (computed with microsecond precision by Transaction.new()) rather
        # than left to the DB's server_default=func.now(). Two reasons:
        # (1) it's the only way the Transaction returned to the API caller
        # here actually matches what's persisted, rather than silently
        # diverging from whatever timestamp the DB assigns later; (2) under
        # SQLite (this project's test backend), CURRENT_TIMESTAMP has only
        # second-level precision while a bound Python datetime is compared
        # with microsecond precision -- ties between rows created in the
        # same second broke list_for_user's cursor pagination tie-break
        # (found by a QA Lead large-dataset test, FINTRACK-15).
        row = TransactionModel(
            id=transaction.id,
            user_id=transaction.user_id,
            amount=transaction.amount.value,
            category=transaction.category,
            transaction_date=transaction.transaction_date,
            note=transaction.note,
            entry_source=transaction.entry_source,
            created_at=transaction.created_at,
            updated_at=transaction.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get_by_id_for_user(
        self, transaction_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Transaction]:
        stmt = select(TransactionModel).where(
            and_(TransactionModel.id == transaction_id, TransactionModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def list_for_user(
        self, user_id: uuid.UUID, limit: int, cursor: str | None
    ) -> TransactionPage:
        stmt = select(TransactionModel).where(TransactionModel.user_id == user_id)

        if cursor:
            cursor_created_at, cursor_id = _decode_cursor(cursor)
            # Most-recent-first: continue strictly after the cursor's
            # position in (created_at DESC, id DESC) order. The id
            # tie-breaker matters when two rows share a created_at value
            # (e.g. two transactions created in the same instant).
            stmt = stmt.where(
                or_(
                    TransactionModel.created_at < cursor_created_at,
                    and_(
                        TransactionModel.created_at == cursor_created_at,
                        TransactionModel.id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(TransactionModel.created_at.desc(), TransactionModel.id.desc())
        # Fetch one extra row to know whether a next page exists, without
        # a separate COUNT query.
        stmt = stmt.limit(limit + 1)

        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = (
            _encode_cursor(page_rows[-1].created_at, page_rows[-1].id) if has_more else None
        )

        return TransactionPage(items=[_to_domain(r) for r in page_rows], next_cursor=next_cursor)

    async def update(self, transaction: Transaction) -> None:
        stmt = select(TransactionModel).where(
            and_(
                TransactionModel.id == transaction.id,
                TransactionModel.user_id == transaction.user_id,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return  # caller (the command handler) already checked existence
        row.amount = transaction.amount.value
        row.category = transaction.category
        row.transaction_date = transaction.transaction_date
        row.note = transaction.note
        # Reuse the timestamp apply_update() already set on the domain
        # object rather than calling now() a second time here -- one
        # source of truth for "when did this update happen", and
        # consistent microsecond precision for the pagination cursor (see
        # the comment in add() above).
        row.updated_at = transaction.updated_at
        await self._session.flush()

    async def delete(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(TransactionModel).where(
            and_(TransactionModel.id == transaction_id, TransactionModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0

    async def sum_by_category_for_user_in_range(
        self, user_id: uuid.UUID, start_date: date_type, end_date: date_type
    ) -> dict[str, Decimal]:
        # SUM/GROUP BY pushed down to the DB rather than summing in Python
        # over a full row fetch -- same "aggregate at the query layer, not
        # in application code" principle as list_for_user's cursor
        # pagination avoiding an in-memory OFFSET scan.
        stmt = (
            select(TransactionModel.category, func.sum(TransactionModel.amount))
            .where(
                and_(
                    TransactionModel.user_id == user_id,
                    TransactionModel.transaction_date >= start_date,
                    TransactionModel.transaction_date < end_date,
                )
            )
            .group_by(TransactionModel.category)
        )
        result = await self._session.execute(stmt)
        return {category: total for category, total in result.all()}

    async def sum_by_month_for_user_in_range(
        self, user_id: uuid.UUID, start_date: date_type, end_date: date_type
    ) -> dict[tuple[int, int], Decimal]:
        # FINTRACK-19: same aggregate-at-the-query-layer principle as
        # sum_by_category_for_user_in_range, bucketed by calendar month
        # instead of category. `extract()` is SQLAlchemy's cross-dialect
        # construct -- it compiles to EXTRACT(...) on PostgreSQL
        # (production) and to strftime(...) on SQLite (this project's
        # test backend), so this works identically against both without
        # a dialect-specific date-formatting function.
        year = extract("year", TransactionModel.transaction_date)
        month = extract("month", TransactionModel.transaction_date)
        stmt = (
            select(year.label("year"), month.label("month"), func.sum(TransactionModel.amount))
            .where(
                and_(
                    TransactionModel.user_id == user_id,
                    TransactionModel.transaction_date >= start_date,
                    TransactionModel.transaction_date < end_date,
                )
            )
            .group_by(year, month)
        )
        result = await self._session.execute(stmt)
        return {(int(y), int(m)): total for y, m, total in result.all()}

    async def get_recent_amounts_for_category(
        self, user_id: uuid.UUID, category: str, exclude_transaction_id: uuid.UUID, limit: int
    ) -> list[Decimal]:
        stmt = (
            select(TransactionModel.amount)
            .where(
                and_(
                    TransactionModel.user_id == user_id,
                    TransactionModel.category == category,
                    TransactionModel.id != exclude_transaction_id,
                )
            )
            .order_by(TransactionModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [amount for (amount,) in result.all()]

    async def list_all_for_user_by_merchant(
        self, user_id: uuid.UUID, merchant: str
    ) -> list[Transaction]:
        # Case-insensitive comparison via func.upper() pushed to the DB
        # (not Python-side filtering after a full fetch) -- consistent
        # with this repository's other aggregate-at-the-query-layer
        # methods. `merchant` is expected pre-normalised (upper-cased,
        # stripped) by the caller, but comparing via func.upper(note) here
        # too means this method is correct even if that convention is
        # ever violated by a future caller.
        stmt = (
            select(TransactionModel)
            .where(
                and_(
                    TransactionModel.user_id == user_id,
                    TransactionModel.note.isnot(None),
                    func.upper(func.trim(TransactionModel.note)) == merchant,
                )
            )
            .order_by(TransactionModel.transaction_date.asc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]
