"""store per-user server auto-bet strategies

Revision ID: 20260726_04
Revises: 20260726_03
Create Date: 2026-07-26 00:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_04"
down_revision = "20260726_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_bet_strategies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("site", sa.String(length=32), nullable=False),
        sa.Column("target_groups_json", sa.String(), nullable=False),
        sa.Column("history_count", sa.Integer(), nullable=False),
        sa.Column("confidence_threshold", sa.Integer(), nullable=False),
        sa.Column("require_confirmation", sa.Boolean(), nullable=False),
        sa.Column("bet_amount", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_auto_bet_strategies_user_id", "auto_bet_strategies", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_auto_bet_strategies_user_id", table_name="auto_bet_strategies")
    op.drop_table("auto_bet_strategies")
