"""add user-visible strategy events

Revision ID: 20260727_07
Revises: 20260726_06
"""
from alembic import op
import sqlalchemy as sa


revision = "20260727_07"
down_revision = "20260726_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("site", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_strategy_events_user_id", "strategy_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_strategy_events_user_id", table_name="strategy_events")
    op.drop_table("strategy_events")
