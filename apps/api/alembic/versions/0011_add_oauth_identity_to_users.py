"""add oauth identity columns to users, make password_hash nullable

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FINTRACK-42/43 (ADR-016): OAuth-only users (Google or Apple sign-in,
    # no password ever set) need password_hash to be nullable -- existing
    # rows are all password-based and keep their real hash, so no backfill
    # is needed for this direction of the change.
    op.alter_column("users", "password_hash", existing_type=sa.String(length=60), nullable=True)
    op.add_column("users", sa.Column("oauth_provider", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("oauth_subject", sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        "uq_users_oauth_identity", "users", ["oauth_provider", "oauth_subject"]
    )
    # DB role grant unchanged -- SELECT/INSERT/UPDATE only, additive/nullable
    # changes, no new grant needed (same role already has UPDATE/INSERT on
    # this table from migration 0001).


def downgrade() -> None:
    op.drop_constraint("uq_users_oauth_identity", "users", type_="unique")
    op.drop_column("users", "oauth_subject")
    op.drop_column("users", "oauth_provider")
    # Reverting password_hash to NOT NULL is only safe if no OAuth-only
    # (null-password) rows exist -- this downgrade deliberately does NOT
    # attempt that revert automatically, since silently deleting or
    # fabricating a password for those rows would be far worse than
    # leaving the column nullable. Handle manually if a downgrade is ever
    # actually needed post-OAuth-launch.
