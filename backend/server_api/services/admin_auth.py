"""Administrator bootstrap, password authentication, and cookie sessions."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server_api.db import AdminAuditEvent, AdminSession, AdminUser, BootstrapState
from server_api.services.credentials import encryption_key_from_secret


class AdminAuthorizationError(ValueError):
    pass


_password_hasher = PasswordHasher()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AdminAuthService:
    def __init__(self, session: AsyncSession, *, bootstrap_token: str, encryption_secret: str, session_hours: int = 24) -> None:
        self._session = session
        self._bootstrap_token = bootstrap_token
        self._cipher = Fernet(encryption_key_from_secret(encryption_secret))
        self._session_hours = session_hours

    async def has_admin(self) -> bool:
        return bool(await self._session.scalar(select(func.count(AdminUser.id))))

    async def setup_admin(self, bootstrap_token: str, username: str, password: str) -> None:
        username = username.strip()
        if not username or len(username) > 64 or len(password) < 12:
            raise AdminAuthorizationError("管理员用户名或密码不符合要求")
        state = await self._session.get(BootstrapState, "admin_setup")
        if state is None:
            state = BootstrapState(key="admin_setup", token_hash=_digest(self._bootstrap_token))
            self._session.add(state)
            await self._session.flush()
        if await self.has_admin() or state.consumed_at is not None or not secrets.compare_digest(state.token_hash or "", _digest(bootstrap_token)):
            raise AdminAuthorizationError("管理员引导令牌无效或已被使用")
        admin = AdminUser(
            username=username,
            password_hash=_password_hasher.hash(password),
            # Retain the legacy non-null column while TOTP is no longer part of login.
            totp_secret_encrypted=self._cipher.encrypt(b"unused").decode("ascii"),
        )
        state.consumed_at = datetime.utcnow()
        self._session.add(admin)
        await self.audit(admin_id=None, action="admin_bootstrap", resource_type="admin_user", resource_id=username)
        await self._session.commit()

    async def login(self, username: str, password: str) -> tuple[AdminUser, str] | None:
        admin = await self._session.scalar(select(AdminUser).where(AdminUser.username == username.strip()))
        if admin is None or admin.disabled:
            return None
        try:
            valid_password = _password_hasher.verify(admin.password_hash, password)
        except (InvalidHashError, VerifyMismatchError):
            return None
        if not valid_password:
            return None
        token = secrets.token_urlsafe(48)
        self._session.add(AdminSession(
            admin_id=admin.id,
            token_hash=_digest(token),
            expires_at=datetime.utcnow() + timedelta(hours=self._session_hours),
        ))
        await self.audit(admin_id=admin.id, action="admin_login", resource_type="admin_user", resource_id=str(admin.id))
        await self._session.commit()
        return admin, token

    async def current_admin(self, token: str | None) -> AdminUser | None:
        if not token:
            return None
        record = await self._session.scalar(select(AdminSession).where(
            AdminSession.token_hash == _digest(token),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > datetime.utcnow(),
        ))
        if record is None:
            return None
        admin = await self._session.get(AdminUser, record.admin_id)
        return admin if admin is not None and not admin.disabled else None

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        record = await self._session.scalar(select(AdminSession).where(AdminSession.token_hash == _digest(token)))
        if record is not None and record.revoked_at is None:
            record.revoked_at = datetime.utcnow()
            await self._session.commit()

    async def audit(self, *, admin_id: int | None, action: str, resource_type: str, resource_id: str, details_json: str = "{}") -> None:
        self._session.add(AdminAuditEvent(
            admin_id=admin_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details_json=details_json,
        ))
