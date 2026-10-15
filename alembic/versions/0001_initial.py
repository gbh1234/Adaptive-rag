"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tracking_no", sa.String(64), nullable=True),
        sa.Column("receiver_city", sa.String(64), nullable=True),
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("orders.order_id")),
        sa.Column("sku", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("customized", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "products",
        sa.Column("sku", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False, index=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("inventory", sa.Integer(), nullable=False),
        sa.Column("tags", sa.String(256), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    op.create_table(
        "refunds",
        sa.Column("refund_id", sa.String(32), primary_key=True),
        sa.Column("order_id", sa.String(32), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(64), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "idempotency_keys",
        "audit_logs",
        "messages",
        "sessions",
        "refunds",
        "order_items",
        "orders",
        "products",
    ]:
        op.drop_table(table)
