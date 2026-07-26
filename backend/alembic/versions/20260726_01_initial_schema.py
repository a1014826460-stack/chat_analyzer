"""create initial server API schema

Revision ID: 20260726_01
Revises:
Create Date: 2026-07-26 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260726_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activation_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("max_devices", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_activation_codes_code_hash", "activation_codes", ["code_hash"])
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("activation_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["activation_id"], ["activation_codes.id"]),
        sa.UniqueConstraint("activation_id"),
    )
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("machine_hash", sa.String(length=64), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id", "machine_hash", name="uq_device_session_user_machine"),
    )
    op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"])
    op.create_index("ix_device_sessions_machine_hash", "device_sessions", ["machine_hash"])
    op.create_table(
        "wss_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("appid", sa.String(length=255), nullable=False),
        sa.Column("accid", sa.String(length=255), nullable=False),
        sa.Column("encrypted_user_sig", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_wss_credentials_user_id", "wss_credentials", ["user_id"])
    op.create_table(
        "draw_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("total", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("site", "period", name="uq_draw_result_site_period"),
    )
    op.create_index("ix_draw_results_site", "draw_results", ["site"])
    op.create_index("ix_draw_results_period", "draw_results", ["period"])
    op.create_table(
        "bet_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("site", sa.String(length=32), nullable=False),
        sa.Column("period", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=255), nullable=False),
        sa.Column("play_type", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id", "site", "period", "group_id", "play_type", name="uq_bet_order_idempotency"),
    )
    op.create_index("ix_bet_orders_user_id", "bet_orders", ["user_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_bet_orders_user_id", table_name="bet_orders")
    op.drop_table("bet_orders")
    op.drop_index("ix_draw_results_period", table_name="draw_results")
    op.drop_index("ix_draw_results_site", table_name="draw_results")
    op.drop_table("draw_results")
    op.drop_index("ix_wss_credentials_user_id", table_name="wss_credentials")
    op.drop_table("wss_credentials")
    op.drop_index("ix_device_sessions_machine_hash", table_name="device_sessions")
    op.drop_index("ix_device_sessions_user_id", table_name="device_sessions")
    op.drop_table("device_sessions")
    op.drop_table("users")
    op.drop_index("ix_activation_codes_code_hash", table_name="activation_codes")
    op.drop_table("activation_codes")
