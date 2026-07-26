"""add draw creation timestamp

Revision ID: 20260726_02
Revises: 20260726_01
Create Date: 2026-07-26 00:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_02"
down_revision = "20260726_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("draw_results", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE draw_results SET created_at = updated_at WHERE created_at IS NULL")


def downgrade() -> None:
    op.drop_column("draw_results", "created_at")
