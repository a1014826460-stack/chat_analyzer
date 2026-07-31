"""add runtime log events

Revision ID: 20260731_08
Revises: 20260727_07
"""
from alembic import op
import sqlalchemy as sa


revision = "20260731_08"
down_revision = "20260727_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_log_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=1024), nullable=False),
        sa.Column("details_json", sa.String(), nullable=False),
        sa.Column("request_url", sa.String(length=2048), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("exception_traceback", sa.String(), nullable=True),
        sa.Column("service_name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_runtime_log_events_user_id", "runtime_log_events", ["user_id"])
    op.create_index("ix_runtime_log_events_level", "runtime_log_events", ["level"])
    op.create_index("ix_runtime_log_events_category", "runtime_log_events", ["category"])
    op.create_index("ix_runtime_log_events_created_at", "runtime_log_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_runtime_log_events_created_at", table_name="runtime_log_events")
    op.drop_index("ix_runtime_log_events_category", table_name="runtime_log_events")
    op.drop_index("ix_runtime_log_events_level", table_name="runtime_log_events")
    op.drop_index("ix_runtime_log_events_user_id", table_name="runtime_log_events")
    op.drop_table("runtime_log_events")
