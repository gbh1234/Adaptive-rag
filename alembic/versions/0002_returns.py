"""initial schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "returns",
        sa.Column("return_id", sa.String(32), primary_key=True),
        sa.Column("order_id", sa.String(32), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("returns")
