"""add strategy type columns to auto_bet_strategies

Revision ID: 20260808_10
Revises: 20260806_11
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260808_10"
down_revision = "20260806_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auto_bet_strategies", sa.Column("strategy_type", sa.String(32), nullable=False, server_default="three_doors"))
    op.add_column("auto_bet_strategies", sa.Column("play_types_json", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("auto_bet_strategies", sa.Column("observation_window", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("auto_bet_strategies", sa.Column("trigger_threshold", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("auto_bet_strategies", sa.Column("martingale_sequence_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    for column in ("strategy_type", "play_types_json", "observation_window", "trigger_threshold", "martingale_sequence_json"):
        op.drop_column("auto_bet_strategies", column)
