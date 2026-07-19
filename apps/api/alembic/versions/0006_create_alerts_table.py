"""create alerts table

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("alert_type", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("threshold_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alerts_user_id", "alerts", ["user_id"])
    # See AlertModel's docstring: both constraints rely on Postgres's
    # standard NULL-is-distinct-from-NULL behaviour to only meaningfully
    # bind the alert type each is meant for.
    op.create_unique_constraint(
        "uq_alerts_threshold_crossing",
        "alerts",
        ["user_id", "category", "alert_type", "period_start", "threshold_pct"],
    )
    op.create_unique_constraint(
        "uq_alerts_transaction_id", "alerts", ["transaction_id"]
    )
    # DB role grant: SELECT/INSERT/UPDATE only, never DROP/ALTER, added at
    # deployment time per constraint matrix -- same as migrations
    # 0002-0005. No DELETE grant: alerts are never hard-deleted, only
    # dismissed (dismissed_at set), same append-only-with-a-flag shape as
    # CategorisationRule.


def downgrade() -> None:
    op.drop_constraint("uq_alerts_transaction_id", "alerts", type_="unique")
    op.drop_constraint("uq_alerts_threshold_crossing", "alerts", type_="unique")
    op.drop_index("ix_alerts_user_id", table_name="alerts")
    op.drop_table("alerts")
