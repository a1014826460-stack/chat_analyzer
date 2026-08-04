"""store group-name snapshots for server strategy logs

Revision ID: 20260804_09
Revises: 20260731_08
"""
from alembic import op
import sqlalchemy as sa


revision = "20260804_09"
down_revision = "20260731_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auto_bet_strategies", sa.Column("target_group_names_json", sa.String(), nullable=False, server_default="{}"))
    op.add_column("bet_orders", sa.Column("group_name", sa.String(length=255), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("bet_orders", "group_name")
    op.drop_column("auto_bet_strategies", "target_group_names_json")
