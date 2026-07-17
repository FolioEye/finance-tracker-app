"""create categorisation_rules table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-16
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categorisation_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("merchant_pattern", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_categorisation_rules_user_id", "categorisation_rules", ["user_id"]
    )
    # Backs CategorisationRuleRepository.upsert()'s "one rule per merchant
    # pattern per user" semantics -- a second insert for the same
    # (user_id, merchant_pattern) should update, never duplicate.
    op.create_unique_constraint(
        "uq_categorisation_rules_user_pattern",
        "categorisation_rules",
        ["user_id", "merchant_pattern"],
    )
    # DB role grant: SELECT/INSERT/UPDATE only, never DROP/ALTER, added at
    # deployment time per constraint matrix -- same as migrations 0002/0003.


def downgrade() -> None:
    op.drop_constraint(
        "uq_categorisation_rules_user_pattern", "categorisation_rules", type_="unique"
    )
    op.drop_index("ix_categorisation_rules_user_id", table_name="categorisation_rules")
    op.drop_table("categorisation_rules")
