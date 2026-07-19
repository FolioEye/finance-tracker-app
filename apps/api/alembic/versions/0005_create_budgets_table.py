"""create budgets table

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("monthly_limit", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_budgets_user_id", "budgets", ["user_id"])
    # Backs the one-budget-per-category-per-user invariant -- a second
    # POST for a category the user already has a budget for is rejected
    # (409) at the application layer, and this constraint is the backstop
    # against any race that slips past that check.
    op.create_unique_constraint(
        "uq_budgets_user_category", "budgets", ["user_id", "category"]
    )
    # DB role grant: SELECT/INSERT/UPDATE/DELETE only, never DROP/ALTER,
    # added at deployment time per constraint matrix -- same as migrations
    # 0002/0003/0004. DELETE is included here (unlike categorisation_rules)
    # because budgets are explicitly user-removable (AC4), not append-only.


def downgrade() -> None:
    op.drop_constraint("uq_budgets_user_category", "budgets", type_="unique")
    op.drop_index("ix_budgets_user_id", table_name="budgets")
    op.drop_table("budgets")
