"""Read models and controlled mutations used exclusively by the admin console."""
from __future__ import annotations

import secrets
import base64
import json
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import ActivationCode, AdminAuditEvent, AdminUser, BetAttempt, BetOrder, DeviceSession, RuntimeLogEvent, User
from server_api.services.auth import create_activation_code


def _sign_license(payload: dict[str, object], private_key_pem: str) -> str:
    from Crypto.PublicKey import ECC
    from Crypto.Signature import eddsa

    if not private_key_pem.strip():
        raise ValueError("服务端未配置普通用户版授权签名私钥")
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(ECC.import_key(private_key_pem), "rfc8032").sign(raw)
    encode = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
    return f"{encode(raw)}.{encode(signature)}"


def activation_token() -> str:
    return f"ST-{secrets.token_urlsafe(18).upper()}"


async def create_codes(
    session: AsyncSession, *, admin: AdminUser, machine_code: str, private_key_pem: str, expires_in_days: int = 1, max_devices: int = 1
) -> list[tuple[ActivationCode, str]]:
    if not 8 <= len(machine_code.strip()) <= 512 or not 1 <= expires_in_days <= 3650 or max_devices != 1:
        raise ValueError("激活码参数超出允许范围")
    license_id = uuid.uuid4().hex
    expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    token = _sign_license({"license_id": license_id, "edition": "user", "schema": 1, "machine_code": machine_code.strip(), "duration_value": expires_in_days, "duration_unit": "days", "features": ["standard"], "expires_at": expires_at.isoformat(timespec="seconds"), "issued_at": datetime.utcnow().isoformat(timespec="seconds")}, private_key_pem)
    row = await create_activation_code(session, activation_code=license_id, expires_in_seconds=expires_in_days * 86400, max_devices=1)
    created = [(row, token)]
    session.add(AdminAuditEvent(
        admin_id=admin.id, action="activation_codes_created", resource_type="activation_code",
        resource_id=",".join(str(item[0].id) for item in created),
    ))
    await session.commit()
    return created


async def list_users(session: AsyncSession, *, keyword: str = "") -> list[dict[str, object]]:
    statement = select(User, ActivationCode).join(ActivationCode, User.activation_id == ActivationCode.id).order_by(User.id.desc())
    if keyword.strip().isdigit():
        statement = statement.where(User.id == int(keyword.strip()))
    rows = (await session.execute(statement)).all()
    result = []
    for user, code in rows:
        devices = (await session.scalars(select(DeviceSession).where(DeviceSession.user_id == user.id))).all()
        result.append({
            "id": user.id, "authorization_id": code.id, "expires_at": code.expires_at.isoformat(),
            "revoked": code.revoked, "max_devices": code.max_devices,
            "active_devices": sum(not device.revoked for device in devices),
            "last_seen_at": max((device.last_seen_at for device in devices), default=None),
            "devices": [{"id": device.id, "revoked": device.revoked, "last_seen_at": device.last_seen_at.isoformat()} for device in devices],
        })
    return result


async def dashboard_metrics(session: AsyncSession, redis: object) -> dict[str, object]:
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    errors = await session.scalar(select(func.count(RuntimeLogEvent.id)).where(
        RuntimeLogEvent.level == "ERROR", RuntimeLogEvent.created_at >= today
    ))
    requests = await redis.get("metrics:api:requests") if hasattr(redis, "get") else None
    online = await redis.get("metrics:online_users") if hasattr(redis, "get") else None
    return {
        "online_users": int(online or 0), "api_requests": int(requests or 0), "errors": int(errors or 0),
        "api_status": "healthy", "checked_at": now.isoformat(),
    }


async def list_orders(session: AsyncSession, *, user_id: int | None = None, limit: int = 100) -> list[dict[str, object]]:
    statement = select(BetOrder).order_by(BetOrder.id.desc()).limit(limit)
    if user_id:
        statement = statement.where(BetOrder.user_id == user_id)
    rows = (await session.scalars(statement)).all()
    return [{
        "id": row.id, "user_id": row.user_id, "site": row.site, "period": row.period,
        "group_name": row.group_name, "play_type": row.play_type, "amount": row.amount,
        "status": row.status, "created_at": row.created_at.isoformat(),
    } for row in rows]


async def list_admin_audit(session: AsyncSession, limit: int = 100) -> list[dict[str, object]]:
    rows = (await session.scalars(select(AdminAuditEvent).order_by(AdminAuditEvent.id.desc()).limit(limit))).all()
    return [{"id": row.id, "admin_id": row.admin_id, "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id, "created_at": row.created_at.isoformat()} for row in rows]
