"""add encrypted administrator AI configuration

Revision ID: 20260806_11
Revises: 20260805_10
"""
from alembic import op
import sqlalchemy as sa


revision = "20260806_11"
down_revision = "20260805_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "server_ai_configuration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("server_ai_configuration")
