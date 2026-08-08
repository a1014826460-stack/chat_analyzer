"""add strategy snapshot columns to bet_orders

Revision ID: 20260808_11
Revises: 20260808_10
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260808_11"
down_revision = "20260808_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bet_orders", sa.Column("strategy_type", sa.String(32), nullable=False, server_default="three_doors"))
    op.add_column("bet_orders", sa.Column("strategy_snapshot", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("bet_orders", sa.Column("result", sa.String(16), nullable=False, server_default="pending"))
    op.add_column("bet_orders", sa.Column("result_detail", sa.String(32), nullable=False, server_default=""))


def downgrade() -> None:
    for column in ("strategy_type", "strategy_snapshot", "result", "result_detail"):
        op.drop_column("bet_orders", column)
