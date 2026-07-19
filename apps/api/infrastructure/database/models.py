"""SQLAlchemy ORM models. Infrastructure layer only -- domain never imports these."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(60), nullable=False)  # bcrypt hash is fixed 60 chars
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TransactionModel(Base):
    """FINTRACK-15. Numeric(12, 2) matches Money's <= 2dp / < 10-digit-integer-part
    constraint (MAX_TRANSACTION_AMOUNT is just under 1_000_000_000.00) --
    using Numeric rather than Float for the same exact-currency-arithmetic
    reason domain.models.transaction.Money is Decimal-based, not float.
    """

    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # FINTRACK-16: distinguishes manual entry from statement import (and,
    # later, receipt OCR) -- all three share the same CreateTransactionCommand
    # shape per the PM's epic-level architecture constraint.
    entry_source: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CategorisationRuleModel(Base):
    """FINTRACK-17. merchant_pattern is stored upper-cased (normalised at
    the domain layer, CategorisationRule.new()) so matching is a plain
    case-insensitive substring check with no per-query LOWER()/ILIKE
    needed. unique(user_id, merchant_pattern) backs the upsert semantics
    in SqlAlchemyCategorisationRuleRepository.upsert() -- one rule per
    merchant pattern per user, not an append-only history.
    """

    __tablename__ = "categorisation_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "merchant_pattern", name="uq_categorisation_rules_user_pattern"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    merchant_pattern: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BudgetModel(Base):
    """FINTRACK-20. Evergreen -- no month/year column. "Resets each
    calendar month" (AC3) is a read-time concern (see
    TransactionRepository.sum_by_category_for_user_in_range and
    docs/adr/ADR-013-budget-tracking-compute-on-read.md), not a write-time
    one, so there is nothing here to reset. unique(user_id, category)
    backs the one-budget-per-category-per-user invariant enforced at the
    application layer (BudgetAlreadyExistsError on a second POST for the
    same category).
    """

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_budgets_user_category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertModel(Base):
    """FINTRACK-22. Two alert shapes share this table (see
    domain.models.alert.Alert's docstring for the full rationale):
    THRESHOLD_CROSSING rows are deduplicated per (user_id, category,
    alert_type, period_start, threshold_pct); LARGE_TRANSACTION rows are
    deduplicated per transaction_id. Both unique constraints below rely
    on Postgres's standard "NULL is distinct from NULL" semantics --
    threshold_pct is NULL on LARGE_TRANSACTION rows and transaction_id is
    NULL on THRESHOLD_CROSSING rows, so each constraint only meaningfully
    binds the alert type it's meant for, with no partial/filtered index
    needed.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category", "alert_type", "period_start", "threshold_pct",
            name="uq_alerts_threshold_crossing",
        ),
        UniqueConstraint("transaction_id", name="uq_alerts_transaction_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    threshold_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
