"""create follow_through_records table

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "follow_through_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("recommendation_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_follow_through_records_user_id", "follow_through_records", ["user_id"])
    # AC1/AC2: at most one record per user per calendar day -- see
    # FollowThroughRecordModel's docstring.
    op.create_unique_constraint(
        "uq_follow_through_user_period",
        "follow_through_records",
        ["user_id", "period_start"],
    )
    # DB role grant: SELECT/INSERT/UPDATE only, never DROP/ALTER, added at
    # deployment time per constraint matrix -- same as migrations
    # 0002-0007. No DELETE grant: records are never hard-deleted, only
    # transitioned in place (status/actioned_at updated).


def downgrade() -> None:
    op.drop_constraint("uq_follow_through_user_period", "follow_through_records", type_="unique")
    op.drop_index("ix_follow_through_records_user_id", table_name="follow_through_records")
    op.drop_table("follow_through_records")
