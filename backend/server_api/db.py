from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Float
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    activation_id: Mapped[int] = mapped_column(ForeignKey("activation_codes.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ActivationCode(Base):
    __tablename__ = "activation_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    max_devices: Mapped[int] = mapped_column(Integer, default=1)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DeviceSession(Base):
    __tablename__ = "device_sessions"
    __table_args__ = (UniqueConstraint("user_id", "machine_hash", name="uq_device_session_user_machine"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    machine_hash: Mapped[str] = mapped_column(String(64), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WssCredential(Base):
    __tablename__ = "wss_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    appid: Mapped[str] = mapped_column(String(255))
    accid: Mapped[str] = mapped_column(String(255))
    encrypted_user_sig: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DrawResult(Base):
    __tablename__ = "draw_results"
    __table_args__ = (UniqueConstraint("site", "period", name="uq_draw_result_site_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String(32), index=True)
    period: Mapped[str] = mapped_column(String(64), index=True)
    result: Mapped[str] = mapped_column(String(16))
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BetOrder(Base):
    __tablename__ = "bet_orders"
    __table_args__ = (UniqueConstraint("user_id", "site", "period", "group_id", "play_type", name="uq_bet_order_idempotency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(64))
    group_id: Mapped[str] = mapped_column(String(255))
    group_name: Mapped[str] = mapped_column(String(255), default="")
    play_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="pending_confirmation")
    confirmation_deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    betting_deadline_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    strategy_type: Mapped[str] = mapped_column(String(32), default="three_doors")
    strategy_snapshot: Mapped[str] = mapped_column(String, default="{}")
    result: Mapped[str] = mapped_column(String(16), default="pending")
    result_detail: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BetAttempt(Base):
    __tablename__ = "bet_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("bet_orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AutoBetStrategy(Base):
    __tablename__ = "auto_bet_strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    site: Mapped[str] = mapped_column(String(32), default="pc28")
    target_groups_json: Mapped[str] = mapped_column(String, default="[]")
    target_group_names_json: Mapped[str] = mapped_column(String, default="{}")
    history_count: Mapped[int] = mapped_column(Integer, default=50)
    confidence_threshold: Mapped[int] = mapped_column(Integer, default=45)
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    bet_amount: Mapped[float] = mapped_column(Float, default=10.0)
    strategy_type: Mapped[str] = mapped_column(String(32), default="three_doors")
    play_types_json: Mapped[str] = mapped_column(String, default="[]")
    observation_window: Mapped[int] = mapped_column(Integer, default=10)
    trigger_threshold: Mapped[int] = mapped_column(Integer, default=3)
    martingale_sequence_json: Mapped[str] = mapped_column(String, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    totp_secret_encrypted: Mapped[str] = mapped_column(String(512))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(128))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BootstrapState(Base):
    __tablename__ = "bootstrap_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ServerAiConfiguration(Base):
    __tablename__ = "server_ai_configuration"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(64), default="openai_compatible")
    base_url: Mapped[str] = mapped_column(String(512))
    model: Mapped[str] = mapped_column(String(255))
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    service_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="ok")
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class StrategyEvent(Base):
    """Per-period server decisions presented in the desktop betting log."""

    __tablename__ = "strategy_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    site: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RuntimeLogEvent(Base):
    """Sanitized operational events rendered in the desktop auto-bet panel."""

    __tablename__ = "runtime_log_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    level: Mapped[str] = mapped_column(String(8), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(String(1024))
    details_json: Mapped[str] = mapped_column(String, default="{}")
    request_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exception_traceback: Mapped[str | None] = mapped_column(String, nullable=True)
    service_name: Mapped[str] = mapped_column(String(64), default="api")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True)


async def create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
