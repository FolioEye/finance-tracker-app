"""create subscriptions table

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("merchant", sa.String(length=255), nullable=False),
        sa.Column("amount_estimate", sa.Numeric(12, 2), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DETECTED"),
        sa.Column(
            "last_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=False,
        ),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    # One evolving row per merchant per user -- see SubscriptionModel's
    # docstring for why this differs from AlertModel's per-period rows.
    op.create_unique_constraint(
        "uq_subscriptions_user_merchant", "subscriptions", ["user_id", "merchant"]
    )
    # DB role grant: SELECT/INSERT/UPDATE only, never DROP/ALTER, added at
    # deployment time per constraint matrix -- same as migrations 0002-0006.
    # No DELETE grant: subscriptions are never hard-deleted, only moved to
    # DISMISSED/NOT_SUBSCRIPTION status, same append-only-with-a-flag shape
    # as CategorisationRule/Alert.


def downgrade() -> None:
    op.drop_constraint("uq_subscriptions_user_merchant", "subscriptions", type_="unique")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
