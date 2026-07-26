"""add betting deadline

Revision ID: 20260726_06
Revises: 20260726_05
Create Date: 2026-07-26 00:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_06"
down_revision = "20260726_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bet_orders", sa.Column("betting_deadline_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("bet_orders", "betting_deadline_at")
