"""SQLAlchemy adapter implementing the TransactionRepository port.

Every query goes through SQLAlchemy's parameterised query builder -- no
string-concatenated SQL exists anywhere in this file. Every query is also
filtered by user_id, never trusting a client-supplied identifier alone,
per this project's IDOR-prevention discipline.
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, delete, or_, select
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
        row = TransactionModel(
            id=transaction.id,
            user_id=transaction.user_id,
            amount=transaction.amount.value,
            category=transaction.category,
            transaction_date=transaction.transaction_date,
            note=transaction.note,
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
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def delete(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(TransactionModel).where(
            and_(TransactionModel.id == transaction_id, TransactionModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0
