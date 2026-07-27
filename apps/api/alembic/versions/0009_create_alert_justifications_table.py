"""create alert_justifications table

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_justifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("ceiling_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_alert_justifications_user_id", "alert_justifications", ["user_id"])
    # AC2: at most one justification ceiling per (user, category) -- see
    # AlertJustificationModel's docstring.
    op.create_unique_constraint(
        "uq_alert_justifications_user_category",
        "alert_justifications",
        ["user_id", "category"],
    )
    # DB role grant: SELECT/INSERT/UPDATE only, never DROP/ALTER, added at
    # deployment time per constraint matrix -- same as migrations
    # 0002-0008. No DELETE grant: a justification ceiling is never
    # hard-deleted, only ever raised in place (per AC2 -- there is no
    # "remove justification" feature in this story, P2 per its own scope
    # line).


def downgrade() -> None:
    op.drop_constraint("uq_alert_justifications_user_category", "alert_justifications", type_="unique")
    op.drop_index("ix_alert_justifications_user_id", table_name="alert_justifications")
    op.drop_table("alert_justifications")
