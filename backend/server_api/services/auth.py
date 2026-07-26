from __future__ import annotations

import hashlib
import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import ActivationCode, DeviceSession, User


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthorizationError(ValueError):
    pass


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_local_license(token: str, *, machine_code: str, public_key_pem: str) -> dict[str, object]:
    if not public_key_pem.strip():
        raise AuthorizationError("服务端未配置授权公钥")
    try:
        payload_part, signature_part = token.strip().split(".", 1)
        raw = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
        from Crypto.PublicKey import ECC
        from Crypto.Signature import eddsa
        eddsa.new(ECC.import_key(public_key_pem), "rfc8032").verify(raw, signature)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise AuthorizationError("本地授权签名无效") from exc
    if not isinstance(payload, dict) or payload.get("edition") != "user" or int(payload.get("schema", 0)) != 1:
        raise AuthorizationError("本地授权类型无效")
    if str(payload.get("machine_code") or "") != machine_code:
        raise AuthorizationError("本地授权与机器码不匹配")
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    except (KeyError, ValueError) as exc:
        raise AuthorizationError("本地授权到期时间无效") from exc
    if expires_at <= datetime.now():
        raise AuthorizationError("本地授权已过期")
    if not str(payload.get("license_id") or ""):
        raise AuthorizationError("本地授权缺少授权标识")
    return payload


async def create_activation_code(
    session: AsyncSession, *, activation_code: str, expires_in_seconds: int, max_devices: int = 1
) -> ActivationCode:
    if not activation_code.strip():
        raise AuthorizationError("激活码不能为空")
    if max_devices < 1:
        raise AuthorizationError("设备上限必须至少为 1")
    code = ActivationCode(
        code_hash=digest(activation_code),
        expires_at=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
        max_devices=max_devices,
    )
    session.add(code)
    await session.commit()
    await session.refresh(code)
    return code


async def revoke_activation_code(session: AsyncSession, activation_id: int) -> bool:
    code = await session.get(ActivationCode, activation_id)
    if code is None:
        return False
    code.revoked = True
    await session.commit()
    return True


async def open_session(session: AsyncSession, *, machine_code: str, activation_code: str) -> tuple[User, DeviceSession]:
    code = await session.scalar(select(ActivationCode).where(ActivationCode.code_hash == digest(activation_code)))
    if code is None or code.revoked or code.expires_at <= datetime.utcnow():
        raise AuthorizationError("授权无效、已过期或已吊销")
    user = await session.scalar(select(User).where(User.activation_id == code.id))
    if user is None:
        user = User(activation_id=code.id)
        session.add(user)
        await session.flush()
    machine_hash = digest(machine_code)
    device = await session.scalar(
        select(DeviceSession).where(DeviceSession.user_id == user.id, DeviceSession.machine_hash == machine_hash)
    )
    if device is None:
        active_devices = await session.scalar(
            select(func.count(DeviceSession.id)).where(DeviceSession.user_id == user.id, DeviceSession.revoked.is_(False))
        )
        if int(active_devices or 0) >= code.max_devices:
            await session.rollback()
            raise AuthorizationError("设备数量已达到授权上限")
        device = DeviceSession(user_id=user.id, machine_hash=machine_hash)
        session.add(device)
    else:
        device.revoked = False
        device.last_seen_at = datetime.utcnow()
    await session.commit()
    await session.refresh(device)
    return user, device


async def open_local_license_session(
    session: AsyncSession, *, machine_code: str, license_token: str, public_key_pem: str
) -> tuple[User, DeviceSession, ActivationCode]:
    payload = verify_local_license(license_token, machine_code=machine_code, public_key_pem=public_key_pem)
    code_hash = digest(str(payload["license_id"]))
    expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    code = await session.scalar(select(ActivationCode).where(ActivationCode.code_hash == code_hash))
    if code is None:
        code = ActivationCode(code_hash=code_hash, expires_at=expires_at, max_devices=1)
        session.add(code)
        await session.flush()
    if code.revoked or code.expires_at <= datetime.utcnow():
        raise AuthorizationError("授权无效、已过期或已吊销")
    user = await session.scalar(select(User).where(User.activation_id == code.id))
    if user is None:
        user = User(activation_id=code.id)
        session.add(user)
        await session.flush()
    machine_hash = digest(machine_code)
    device = await session.scalar(
        select(DeviceSession).where(DeviceSession.user_id == user.id, DeviceSession.machine_hash == machine_hash)
    )
    if device is None:
        active_devices = await session.scalar(
            select(func.count(DeviceSession.id)).where(DeviceSession.user_id == user.id, DeviceSession.revoked.is_(False))
        )
        if int(active_devices or 0) >= code.max_devices:
            raise AuthorizationError("设备数量已达到授权上限")
        device = DeviceSession(user_id=user.id, machine_hash=machine_hash)
        session.add(device)
    else:
        device.revoked = False
        device.last_seen_at = datetime.utcnow()
    await session.commit()
    await session.refresh(device)
    return user, device, code


def issue_access_token(*, user_id: int, device_id: int, jwt_secret: str, expires_in_seconds: int = 900) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user_id), "device_id": device_id, "iat": now, "exp": now + timedelta(seconds=expires_in_seconds)},
        jwt_secret,
        algorithm="HS256",
    )
