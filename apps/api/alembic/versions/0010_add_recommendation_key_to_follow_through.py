"""add recommendation_key to follow_through_records

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FINTRACK-27: the coarse recommendation_type (BUDGET_RISK/
    # NEW_SUBSCRIPTION/SPENDING_SPIKE) alone can't distinguish "dining-out"
    # spikes from "entertainment" spikes, or one new-subscription merchant
    # from another -- follow-through-based prioritisation needs that finer
    # identity to reorder candidates within a tier. Nullable: existing rows
    # predate this story and have no fine-grained identity to backfill;
    # NEUTRAL recommendations also have no category/merchant to store here.
    op.add_column(
        "follow_through_records",
        sa.Column("recommendation_key", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_follow_through_records_user_type_key",
        "follow_through_records",
        ["user_id", "recommendation_type", "recommendation_key"],
    )
    # DB role grant unchanged -- SELECT/INSERT/UPDATE only, additive column,
    # no new grant needed (same role already has UPDATE/INSERT on this
    # table from migration 0008).


def downgrade() -> None:
    op.drop_index("ix_follow_through_records_user_type_key", table_name="follow_through_records")
    op.drop_column("follow_through_records", "recommendation_key")
