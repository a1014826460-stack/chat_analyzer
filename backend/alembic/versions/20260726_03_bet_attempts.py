"""record WSS send attempts

Revision ID: 20260726_03
Revises: 20260726_02
Create Date: 2026-07-26 00:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_03"
down_revision = "20260726_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bet_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=512)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["bet_orders.id"]),
    )
    op.create_index("ix_bet_attempts_order_id", "bet_attempts", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_bet_attempts_order_id", table_name="bet_attempts")
    op.drop_table("bet_attempts")
