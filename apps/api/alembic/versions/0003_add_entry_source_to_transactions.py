"""add entry_source to transactions

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

FINTRACK-16: activates the CreateTransactionCommand.entry_source field
that FINTRACK-15 defined but never persisted -- distinguishes manual
entry from statement import (this story) and, later, receipt OCR (P1).
Existing rows default to "manual" via server_default, matching the
domain default in Transaction.new().
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "entry_source",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "entry_source")
