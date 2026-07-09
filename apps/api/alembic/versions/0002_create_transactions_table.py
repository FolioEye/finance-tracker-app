"""create transactions table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    # Supports list_for_user's cursor-based ORDER BY created_at DESC, id DESC.
    op.create_index(
        "ix_transactions_user_id_created_at_id",
        "transactions",
        ["user_id", "created_at", "id"],
    )
    # The DB role used by the app should be granted SELECT/INSERT/UPDATE
    # only (never DROP/ALTER) -- enforced at deployment/infra level per
    # constraint matrix, not in this migration. DELETE is also needed here
    # (unlike the users table) since this story's AC5 requires deletable
    # transactions -- that grant should be added alongside this migration
    # at deployment time.


def downgrade() -> None:
    op.drop_index("ix_transactions_user_id_created_at_id", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_table("transactions")
